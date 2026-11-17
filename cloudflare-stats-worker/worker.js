// Scash P2Pool (v0.2.0) — 100% Serverless Community Consensus Stats API for MiningPoolStats
// Runs on Cloudflare Workers Free Plan + Free D1 SQLite Database (binding name: DB)
// Zero home servers, zero GitHub tokens, true 1-minute updates, median anti-spoof consensus.

const POOL_AUTHOR_ADDR = "scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc";
const REPORT_TTL_SEC = 195; // Expire silent nodes after ~3.25 minutes (nodes report every 60s)

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS node_reports (
  ip_hash TEXT PRIMARY KEY,
  updated_ep INTEGER NOT NULL,
  p2pool_peers INTEGER NOT NULL,
  chain_height INTEGER NOT NULL,
  best_share TEXT NOT NULL,
  miners_cnt INTEGER NOT NULL,
  workers_cnt INTEGER NOT NULL,
  pool_hr REAL NOT NULL,
  shares_ps REAL NOT NULL,
  total_blocks INTEGER NOT NULL,
  last_block_iso TEXT,
  block_height INTEGER NOT NULL,
  net_diff REAL NOT NULL,
  net_hr REAL NOT NULL,
  net_peers INTEGER NOT NULL
);`;

let schemaReady = false;

async function ensureSchema(db) {
  if (!schemaReady && db) {
    await db.prepare(SCHEMA_SQL).run();
    schemaReady = true;
  }
}

async function sha256Short(text) {
  const buf = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest)).slice(0, 12).map(b => b.toString(16).padStart(2, "0")).join("");
}

function median(values) {
  if (!values || values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2.0;
}

function buildMiningcorePool(agg, nowSec) {
  const isoNow = new Date(nowSec * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  return {
    id: "scash-p2pool",
    coin: {
      type: "SCASH",
      name: "Satoshicash",
      symbol: "SCASH",
      website: "https://scashnetwork.org",
      market: "SCASH-USDT",
      family: "bitcoin",
      algorithm: "RandomSCASH"
    },
    ports: {
      "8345": {
        name: "Decentralized P2Pool Local Stratum (rx/scash)",
        listenAddress: "127.0.0.1",
        difficulty: 0.0625,
        varDiff: {
          minDiff: 0.015625,
          maxDiff: null,
          targetTime: 15,
          retargetTime: 60,
          variancePercent: 30
        }
      }
    },
    paymentProcessing: {
      enabled: true,
      minimumPayment: 0.0,
      payoutScheme: "PPLNS",
      payoutSchemeConfig: { factor: 1.0 }
    },
    clientConnectionTimeout: 600,
    jobRebroadcastTimeout: 15,
    blockRefreshInterval: 1000,
    poolFeePercent: 1.0,
    address: POOL_AUTHOR_ADDR,
    addressInfoLink: "https://scash.tv/address/" + POOL_AUTHOR_ADDR,
    poolStats: {
      connectedMiners: agg.miners_cnt,
      connectedWorkers: agg.workers_cnt,
      poolHashrate: Number(agg.pool_hr.toFixed(2)),
      sharesPerSecond: Number(agg.shares_ps.toFixed(4))
    },
    networkStats: {
      networkType: "main",
      networkHashrate: Number(agg.net_hr.toFixed(2)),
      networkDifficulty: Number(agg.net_diff),
      lastNetworkBlockTime: isoNow,
      blockHeight: agg.block_height,
      connectedPeers: agg.net_peers,
      rewardType: "POW"
    },
    topMiners: [],
    totalPaid: 0.0,
    totalBlocks: agg.total_blocks,
    lastPoolBlockTime: agg.last_block_iso || null,
    blockReward: 50.0,
    activeReportingNodes: agg.active_nodes,
    updatedAt: isoNow,
    updatedAtEpoch: nowSec
  };
}

export function aggregateReports(rows, nowSec) {
  const fresh = (rows || []).filter(r => (nowSec - Number(r.updated_ep || 0)) <= REPORT_TTL_SEC);
  const latestChain = (rows && rows.length > 0)
    ? rows.reduce((best, r) => (Number(r.block_height || 0) >= Number(best.block_height || 0) ? r : best), rows[0])
    : null;

  if (fresh.length === 0) {
    return {
      active_nodes: 0,
      miners_cnt: 0,
      workers_cnt: 0,
      pool_hr: 0.0,
      shares_ps: 0.0,
      total_blocks: latestChain ? Number(latestChain.total_blocks || 0) : 0,
      last_block_iso: latestChain ? (latestChain.last_block_iso || null) : null,
      block_height: latestChain ? Number(latestChain.block_height || 0) : 0,
      net_diff: latestChain ? Number(latestChain.net_diff || 0) : 0.0,
      net_hr: latestChain ? Number(latestChain.net_hr || 0) : 0.0,
      net_peers: latestChain ? Number(latestChain.net_peers || 0) : 0
    };
  }

  // Prefer nodes connected to at least 1 P2Pool peer when 2+ nodes are online so lone spoofers cannot skew stats
  const connected = fresh.filter(r => Number(r.p2pool_peers || 0) >= 1);
  let cohort = connected.length > 0 ? connected : fresh;

  // Group by best_share tip if a majority cluster exists
  const tipCounts = {};
  for (const r of cohort) {
    const k = String(r.best_share || "");
    if (k) tipCounts[k] = (tipCounts[k] || 0) + 1;
  }
  let topTip = "";
  let topCnt = 0;
  for (const [k, c] of Object.entries(tipCounts)) {
    if (c > topCnt) { topTip = k; topCnt = c; }
  }
  if (topTip && topCnt >= 2) {
    cohort = cohort.filter(r => String(r.best_share || "") === topTip);
  }

  const medNetHr = median(cohort.map(r => Number(r.net_hr || 0)));
  const medPoolHr = median(cohort.map(r => Number(r.pool_hr || 0)));
  const safePoolHr = medNetHr > 0 ? Math.min(medPoolHr, medNetHr * 1.25) : medPoolHr;
  const medMiners = Math.max(
    fresh.filter(r => Number(r.pool_hr || 0) > 0).length > 0 ? 1 : 0,
    Math.round(median(cohort.map(r => Number(r.miners_cnt || 0))))
  );

  return {
    active_nodes: fresh.length,
    miners_cnt: medMiners,
    workers_cnt: Math.max(medMiners, Math.round(median(cohort.map(r => Number(r.workers_cnt || 0))))),
    pool_hr: safePoolHr,
    shares_ps: median(cohort.map(r => Number(r.shares_ps || 0))),
    total_blocks: Math.round(median(cohort.map(r => Number(r.total_blocks || 0)))),
    last_block_iso: (cohort.find(r => r.last_block_iso) || {}).last_block_iso || null,
    block_height: Math.round(median(cohort.map(r => Number(r.block_height || 0)))),
    net_diff: median(cohort.map(r => Number(r.net_diff || 0))),
    net_hr: medNetHr,
    net_peers: Math.round(median(cohort.map(r => Number(r.net_peers || 0))))
  };
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type"
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response("", { status: 204, headers: CORS_HEADERS });
    }
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const nowSec = Math.floor(Date.now() / 1000);

    if (!env.DB) {
      return new Response(
        JSON.stringify({ error: "D1 database binding 'DB' not attached yet. In Cloudflare Worker -> Bindings -> Add D1 database named DB." }),
        { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }
    await ensureSchema(env.DB);

    if (request.method === "POST" && path === "/api/report") {
      try {
        const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
        const ipHash = await sha256Short("scash-p2pool-v020|" + ip);

        const existing = await env.DB.prepare("SELECT updated_ep FROM node_reports WHERE ip_hash = ?").bind(ipHash).first();
        if (existing && (nowSec - Number(existing.updated_ep || 0)) < 40) {
          return new Response(JSON.stringify({ ok: true, throttled: true }), {
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
          });
        }

        const body = await request.json();
        const pp = body.pool_payload || {};
        const ps = pp.poolStats || {};
        const ns = pp.networkStats || {};

        const blkH = Math.max(0, parseInt(ns.blockHeight || 0, 10) || 0);
        const netDiff = Math.max(0, Number(ns.networkDifficulty || 0) || 0);
        const netHr = Math.max(0, Number(ns.networkHashrate || 0) || 0);
        const rawPoolHr = Math.max(0, Number(ps.poolHashrate || 0) || 0);

        // Sanity bound: reject impossible single-node claims (> 1.5x total Scash network hashrate when chain is synced)
        if (blkH < 100 || (netHr > 0 && rawPoolHr > netHr * 1.5)) {
          return new Response(JSON.stringify({ ok: false, reason: "sanity_check" }), {
            status: 400,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
          });
        }

        const p2pPeers = Math.max(0, Math.min(256, parseInt(body.p2pool_peers || 0, 10) || 0));
        const chainH = Math.max(0, parseInt(body.chain_height || 0, 10) || 0);
        const bestShare = String(body.best_share_hash || "").slice(0, 80);
        const minersCnt = Math.max(0, Math.min(10000, parseInt(ps.connectedMiners || 0, 10) || 0));
        const workersCnt = Math.max(minersCnt, Math.min(50000, parseInt(ps.connectedWorkers || 0, 10) || 0));
        const sharesPs = Math.max(0, Number(ps.sharesPerSecond || 0) || 0);
        const totalBlocks = Math.max(0, parseInt(pp.totalBlocks || 0, 10) || 0);
        const lastBlockIso = pp.lastPoolBlockTime ? String(pp.lastPoolBlockTime).slice(0, 40) : null;
        const netPeers = Math.max(0, Math.min(500, parseInt(ns.connectedPeers || 0, 10) || 0));

        await env.DB.prepare(`
          INSERT INTO node_reports (
            ip_hash, updated_ep, p2pool_peers, chain_height, best_share,
            miners_cnt, workers_cnt, pool_hr, shares_ps, total_blocks,
            last_block_iso, block_height, net_diff, net_hr, net_peers
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(ip_hash) DO UPDATE SET
            updated_ep=excluded.updated_ep, p2pool_peers=excluded.p2pool_peers,
            chain_height=excluded.chain_height, best_share=excluded.best_share,
            miners_cnt=excluded.miners_cnt, workers_cnt=excluded.workers_cnt,
            pool_hr=excluded.pool_hr, shares_ps=excluded.shares_ps,
            total_blocks=excluded.total_blocks, last_block_iso=excluded.last_block_iso,
            block_height=excluded.block_height, net_diff=excluded.net_diff,
            net_hr=excluded.net_hr, net_peers=excluded.net_peers
        `).bind(
          ipHash, nowSec, p2pPeers, chainH, bestShare,
          minersCnt, workersCnt, rawPoolHr, sharesPs, totalBlocks,
          lastBlockIso, blkH, netDiff, netHr, netPeers
        ).run();

        // Opportunistically prune rows older than 24h (~5% of writes) to keep DB tiny (< 1 MB forever)
        if (Math.random() < 0.05) {
          await env.DB.prepare("DELETE FROM node_reports WHERE updated_ep < ?").bind(nowSec - 86400).run();
        }

        return new Response(JSON.stringify({ ok: true }), {
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
        });
      } catch (err) {
        return new Response(JSON.stringify({ ok: false, error: String(err) }), {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
        });
      }
    }

    const { results } = await env.DB.prepare(
      "SELECT * FROM node_reports ORDER BY updated_ep DESC LIMIT 200"
    ).all();
    const agg = aggregateReports(results || [], nowSec);
    const poolObj = buildMiningcorePool(agg, nowSec);

    if (path === "/api/pools/scash-p2pool/blocks") {
      return new Response("[]", { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });
    }
    if (path === "/api/pools/scash-p2pool" || path === "/api/pools/scash") {
      return new Response(JSON.stringify({ pool: poolObj }, null, 2), {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json", "Cache-Control": "public, max-age=15" }
      });
    }
    if (path === "/api" || path === "/api/pools" || path === "/api/pools.json" || path === "/api/v1/public") {
      return new Response(JSON.stringify({ pools: [poolObj] }, null, 2), {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json", "Cache-Control": "public, max-age=15" }
      });
    }

    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scash P2Pool — Live Decentralized Sharechain Stats</title>
<style>body{background:#12101c;color:#f3eefc;font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;line-height:1.55}
.card{background:#1c182b;border:1px solid #352d52;border-radius:14px;padding:22px;margin:18px 0}
code,pre{background:#100d1a;color:#a5f3fc;padding:3px 7px;border-radius:6px;font-size:13px;overflow-x:auto}pre{padding:14px}a{color:#c084fc}</style></head>
<body><h1>Scash P2Pool (<code>v0.2.0</code>) — Serverless Pool Stats</h1>
<p>100% decentralized community-reported P2Pool stats (1-minute live consensus across active P2Pool nodes):</p>
<div class="card"><p><strong>MiningPoolStats Endpoint:</strong> <a href="./api/pools"><code>/api/pools</code></a> &middot; <a href="https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases/latest">Download Scash P2Pool v0.2.0</a></p>
<pre>${JSON.stringify({ pools: [poolObj] }, null, 2)}</pre></div></body></html>`;
    return new Response(html, { headers: { ...CORS_HEADERS, "Content-Type": "text/html; charset=utf-8" } });
  }
};
