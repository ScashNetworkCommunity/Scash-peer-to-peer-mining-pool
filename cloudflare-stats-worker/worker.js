// Scash P2Pool (v0.4.1) — 100% Serverless Community Consensus Stats + Dual-Stack IPv4/IPv6 /64 Peer Rendezvous & Diagnostics API
// Runs on Cloudflare Workers Free Plan + Free D1 SQLite Database (DB) + SQLite Durable Object WebSocket Relay (RELAY_DO)
// Zero home servers, zero GitHub tokens, 1-minute consensus, IPv6 /64 home-LAN grouping, STUN IPv4 fallback, privacy-masked /api/nodes.

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
  net_peers INTEGER NOT NULL,
  peer_ip TEXT DEFAULT '',
  p2p_port INTEGER DEFAULT 8344,
  stun_udp_port INTEGER DEFAULT 0,
  upnp_open INTEGER DEFAULT 0,
  nat_mapping TEXT DEFAULT 'unknown',
  wan_peers INTEGER DEFAULT 0,
  lan_peers INTEGER DEFAULT 0,
  hp_tunnels INTEGER DEFAULT 0,
  node_ver TEXT DEFAULT '',
  instance_id TEXT DEFAULT ''
);`;

const MIGRATION_COLS = [
  "ALTER TABLE node_reports ADD COLUMN peer_ip TEXT DEFAULT ''",
  "ALTER TABLE node_reports ADD COLUMN p2p_port INTEGER DEFAULT 8344",
  "ALTER TABLE node_reports ADD COLUMN stun_udp_port INTEGER DEFAULT 0",
  "ALTER TABLE node_reports ADD COLUMN upnp_open INTEGER DEFAULT 0",
  "ALTER TABLE node_reports ADD COLUMN nat_mapping TEXT DEFAULT 'unknown'",
  "ALTER TABLE node_reports ADD COLUMN wan_peers INTEGER DEFAULT 0",
  "ALTER TABLE node_reports ADD COLUMN lan_peers INTEGER DEFAULT 0",
  "ALTER TABLE node_reports ADD COLUMN hp_tunnels INTEGER DEFAULT 0",
  "ALTER TABLE node_reports ADD COLUMN node_ver TEXT DEFAULT ''",
  "ALTER TABLE node_reports ADD COLUMN instance_id TEXT DEFAULT ''"
];

let schemaReady = false;

async function ensureSchema(db) {
  if (!schemaReady && db) {
    await db.prepare(SCHEMA_SQL).run();
    for (const alterSql of MIGRATION_COLS) {
      try {
        await db.prepare(alterSql).run();
      } catch (_) {
        // Column already exists on upgraded D1 database
      }
    }
    schemaReady = true;
  }
}

async function sha256Short(text) {
  const buf = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest)).slice(0, 12).map(b => b.toString(16).padStart(2, "0")).join("");
}

function isRoutableIpv4(ip) {
  if (!ip || typeof ip !== "string") return false;
  const parts = ip.trim().split(".");
  if (parts.length !== 4) return false;
  const nums = parts.map(p => Number(p));
  if (nums.some(n => !Number.isInteger(n) || n < 0 || n > 255)) return false;
  const [a, b] = nums;
  if (a === 0 || a === 10 || a === 127 || a >= 224) return false;
  if (a === 192 && b === 168) return false;
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 169 && b === 254) return false;
  if (a === 100 && b >= 64 && b <= 127) return false;
  return true;
}

export function expandIpv6Hextets(rawIp) {
  if (!rawIp || typeof rawIp !== "string" || !rawIp.includes(":")) return null;
  let s = rawIp.trim().toLowerCase().split("%")[0];
  if (!s) return null;
  // Handle IPv4-mapped IPv6 (e.g. ::ffff:198.51.100.7)
  if (s.includes(".")) {
    const lastColon = s.lastIndexOf(":");
    const v4Part = s.slice(lastColon + 1);
    if (!isRoutableIpv4(v4Part)) return null;
    const oct = v4Part.split(".").map(Number);
    const h6 = ((oct[0] << 8) | oct[1]).toString(16);
    const h7 = ((oct[2] << 8) | oct[3]).toString(16);
    s = s.slice(0, lastColon + 1) + h6 + ":" + h7;
  }
  const dbl = s.split("::");
  if (dbl.length > 2) return null;
  const left = dbl[0] ? dbl[0].split(":") : [];
  const right = dbl.length === 2 && dbl[1] ? dbl[1].split(":") : [];
  const missing = 8 - (left.length + right.length);
  if ((dbl.length === 1 && left.length !== 8) || (dbl.length === 2 && missing < 1)) return null;
  const full = dbl.length === 2
    ? [...left, ...Array(missing).fill("0"), ...right]
    : left;
  if (full.length !== 8) return null;
  const norm = [];
  for (const h of full) {
    if (!/^[0-9a-f]{1,4}$/.test(h)) return null;
    norm.push(h.padStart(4, "0"));
  }
  return norm;
}

export function normalizeNetworkPrefix(ip) {
  const s = String(ip || "").trim();
  if (isRoutableIpv4(s)) return "v4:" + s;
  const hx = expandIpv6Hextets(s);
  if (hx) {
    // Group residential dual-stack IPv6 LAN devices by /64 prefix (first 4 hextets)
    return "v6:" + hx.slice(0, 4).join(":");
  }
  return "raw:" + s.toLowerCase();
}

function maskIp(ip) {
  if (!ip || typeof ip !== "string") return "hidden";
  const s = ip.trim();
  const parts = s.split(".");
  if (parts.length === 4) return `${parts[0]}.${parts[1]}.x.x`;
  const hx = expandIpv6Hextets(s);
  if (hx) {
    return `${hx[0].replace(/^0+/, "") || "0"}:${hx[1].replace(/^0+/, "") || "0"}:${hx[2].replace(/^0+/, "") || "0"}:*`;
  }
  if (s.includes(":")) return s.split(":").slice(0, 3).join(":") + ":*";
  return "hidden";
}

function baseNetHash(ipHashKey) {
  return String(ipHashKey || "").split(":")[0];
}

function median(values) {
  if (!values || values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2.0;
}

function buildRendezvousPeers(rows, nowSec, callerNetHash, callerIpv4, callerInst) {
  const fresh = (rows || []).filter(r => (nowSec - Number(r.updated_ep || 0)) <= REPORT_TTL_SEC);
  const out = [];
  const seen = new Set();
  fresh.sort((a, b) => {
    const sa = (Number(a.upnp_open || 0) ? 4 : 0) + (a.nat_mapping === "endpoint_independent" ? 2 : 0);
    const sb = (Number(b.upnp_open || 0) ? 4 : 0) + (b.nat_mapping === "endpoint_independent" ? 2 : 0);
    return sb - sa || Number(b.updated_ep || 0) - Number(a.updated_ep || 0);
  });
  for (const r of fresh) {
    const rip = String(r.peer_ip || "").trim();
    const rinst = String(r.instance_id || "").trim();
    const rNet = baseNetHash(r.ip_hash);
    if (!isRoutableIpv4(rip)) continue;
    if (callerNetHash && rNet === callerNetHash) continue;
    if (callerIpv4 && rip === callerIpv4) continue;
    if (callerInst && rinst && rinst === callerInst) continue;
    const p2pPort = Math.max(1, Math.min(65535, Number(r.p2p_port || 8344)));
    const udpPort = Math.max(1, Math.min(65535, Number(r.stun_udp_port || p2pPort)));
    const dedupKey = `${rip}:${p2pPort}:${udpPort}`;
    if (seen.has(dedupKey)) continue;
    seen.add(dedupKey);
    out.push({
      ip: rip,
      p2p_port: p2pPort,
      udp_port: udpPort,
      upnp_open: Boolean(Number(r.upnp_open || 0)),
      nat_mapping: String(r.nat_mapping || "unknown"),
      instance_id: rinst
    });
    if (out.length >= 24) break;
  }
  return out;
}

export function buildNodesDiagnostics(rows, nowSec) {
  const fresh = (rows || []).filter(r => (nowSec - Number(r.updated_ep || 0)) <= REPORT_TTL_SEC);
  const netSet = new Set();
  const tipMap = new Map();
  let wanConnectedNodes = 0;
  let openPortNodes = 0;
  let hpActiveTotal = 0;

  const nodeItems = fresh.map(r => {
    const netKey = baseNetHash(r.ip_hash);
    if (netKey) netSet.add(netKey);
    const tip = String(r.best_share || "").trim();
    if (tip && Number(r.chain_height || 0) > 0) {
      tipMap.set(tip, (tipMap.get(tip) || 0) + 1);
    }
    const wanP = Number(r.wan_peers || 0);
    const lanP = Number(r.lan_peers || 0);
    const totP = Number(r.p2pool_peers || 0);
    const upnp = Boolean(Number(r.upnp_open || 0));
    const hp = Number(r.hp_tunnels || 0);
    if (wanP > 0) wanConnectedNodes += 1;
    if (upnp) openPortNodes += 1;
    hpActiveTotal += hp;
    return {
      node_key: String(r.ip_hash || "").slice(0, 17),
      network_id: netKey.slice(0, 8),
      masked_ip: maskIp(r.peer_ip),
      version: String(r.node_ver || "unknown"),
      age_sec: Math.max(0, nowSec - Number(r.updated_ep || 0)),
      chain_height: Number(r.chain_height || 0),
      best_share_prefix: tip ? tip.slice(0, 16) : "",
      p2pool_peers: totP,
      wan_peers: wanP,
      lan_peers: lanP,
      holepunch_tunnels: hp,
      upnp_open: upnp,
      nat_mapping: String(r.nat_mapping || "unknown"),
      pool_hashrate_hs: Number(Number(r.pool_hr || 0).toFixed(2)),
      connected_miners: Number(r.miners_cnt || 0),
      scash_block_height: Number(r.block_height || 0)
    };
  });

  let consensusTip = "";
  let consensusCnt = 0;
  for (const [t, c] of tipMap.entries()) {
    if (c > consensusCnt) {
      consensusTip = t;
      consensusCnt = c;
    }
  }

  // Only flag split_brain_warning when >= 2 genuinely distinct WAN networks are online AND
  // either NO network has any WAN peer connected or sharechain heights diverge by > 25 shares
  // (preventing false positives from normal 60-second heartbeat timing offsets!).
  let splitBrain = false;
  const byNet = new Map();
  for (const r of fresh) {
    if (Number(r.chain_height || 0) <= 0) continue;
    const nk = baseNetHash(r.ip_hash);
    const cur = byNet.get(nk);
    if (!cur || Number(r.wan_peers || 0) > Number(cur.wan_peers || 0) || Number(r.updated_ep || 0) > Number(cur.updated_ep || 0)) {
      byNet.set(nk, r);
    }
  }
  if (byNet.size >= 2) {
    const reps = Array.from(byNet.values());
    const allZeroWan = reps.every(r => Number(r.wan_peers || 0) === 0);
    const heights = reps.map(r => Number(r.chain_height || 0));
    const heightSpread = Math.max(...heights) - Math.min(...heights);
    if (allZeroWan || heightSpread > 25) {
      splitBrain = true;
    }
  }

  return {
    ok: true,
    updatedAt: new Date(nowSec * 1000).toISOString().replace(/\.\d{3}Z$/, "Z"),
    summary: {
      active_nodes: fresh.length,
      unique_wan_networks: netSet.size,
      nodes_with_wan_peers: wanConnectedNodes,
      nodes_with_open_port_or_upnp: openPortNodes,
      holepunch_tunnels_active: hpActiveTotal,
      consensus_share_tip_prefix: consensusTip ? consensusTip.slice(0, 16) : "",
      distinct_share_tips: tipMap.size,
      split_brain_warning: splitBrain
    },
    nodes: nodeItems
  };
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
    poolFeePercent: 0.0,
    address: "",
    addressInfoLink: "https://explorer.scash.network/",
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
    uniqueWanNetworks: agg.unique_wan_networks,
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
      unique_wan_networks: 0,
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

  const uniqueNets = new Set(fresh.map(r => baseNetHash(r.ip_hash))).size;

  const connected = fresh.filter(r => Number(r.p2pool_peers || 0) >= 1);
  let cohort = connected.length > 0 ? connected : fresh;

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
  const maxAllowedHr = medNetHr > 0 ? Math.max(medNetHr * 50.0, 50000000.0) : 50000000.0;
  const safePoolHr = Math.min(medPoolHr, maxAllowedHr);
  const medMiners = Math.max(
    fresh.filter(r => Number(r.pool_hr || 0) > 0).length > 0 ? 1 : 0,
    Math.round(median(cohort.map(r => Number(r.miners_cnt || 0))))
  );

  return {
    active_nodes: fresh.length,
    unique_wan_networks: uniqueNets,
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

    if (path === "/p2p-relay" || path === "/api/p2p-relay") {
      if (!env.RELAY_DO) {
        return new Response(
          JSON.stringify({
            ok: false,
            relay_enabled: false,
            error: "Durable Object binding 'RELAY_DO' (class P2PoolRelayRoom) is not attached yet. Add RELAY_DO in Worker -> Settings -> Bindings or deploy with wrangler.toml."
          }),
          { status: 503, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }
      const rawIp = (request.headers.get("CF-Connecting-IP") || "0.0.0.0").trim();
      const netPrefix = normalizeNetworkPrefix(rawIp);
      const netHash = (await sha256Short("scash-net-v039|" + netPrefix)).slice(0, 8);
      const netParam = String(url.searchParams.get("net") || "7363617368703236").replace(/[^0-9a-fA-F]/g, "").toLowerCase().slice(0, 32) || "7363617368703236";
      const roomId = env.RELAY_DO.idFromName("scash-p2pool-" + netParam);
      const stub = env.RELAY_DO.get(roomId);
      const fwdHeaders = new Headers(request.headers);
      fwdHeaders.set("X-Scash-NetHash", netHash);
      return stub.fetch(new Request(request.url, { method: request.method, headers: fwdHeaders }));
    }

    if (!env.DB) {
      return new Response(
        JSON.stringify({ error: "D1 database binding 'DB' not attached yet. In Cloudflare Worker -> Bindings -> Add D1 database named DB." }),
        { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }
    await ensureSchema(env.DB);

    if (request.method === "POST" && (path === "/api/report" || path === "/" || path === "/api/pools")) {
      try {
        const ip = (request.headers.get("CF-Connecting-IP") || "0.0.0.0").trim();
        const body = await request.json();
        const mesh = body.mesh || {};
        const instClean = String(mesh.instance_id || "").replace(/[^0-9a-fA-F]/g, "").slice(0, 16);
        const stunV4 = String(mesh.external_ip || "").trim();

        // Group dual-stack IPv6 LAN PCs under a single /64 home network hash while keeping per-PC row keys!
        const netPrefix = normalizeNetworkPrefix(ip);
        const netHash = (await sha256Short("scash-net-v039|" + netPrefix)).slice(0, 8);
        const devKey = instClean ? instClean.slice(0, 8) : (await sha256Short("scash-dev|" + ip)).slice(0, 8);
        const rowKey = `${netHash}:${devKey}`;

        const pp = body.pool_payload || {};
        const ps = pp.poolStats || {};
        const ns = pp.networkStats || {};

        const blkH = Math.max(0, parseInt(ns.blockHeight || 0, 10) || 0);
        const netDiff = Math.max(0, Number(ns.networkDifficulty || 0) || 0);
        const netHr = Math.max(0, Number(ns.networkHashrate || 0) || 0);
        const rawPoolHr = Math.max(0, Number(ps.poolHashrate || 0) || 0);

        const sanityCap = netHr > 0 ? Math.max(netHr * 50.0, 50000000.0) : 50000000.0;
        if (blkH < 100 || rawPoolHr > sanityCap) {
          return new Response(JSON.stringify({ ok: false, reason: "sanity_check" }), {
            status: 400,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
          });
        }

        const callerV4 = isRoutableIpv4(ip) ? ip : (ip.includes(":") && isRoutableIpv4(stunV4) ? stunV4 : "");
        const peerIpStored = callerV4 || (ip.includes(":") ? ip : "");

        const existing = await env.DB.prepare("SELECT updated_ep FROM node_reports WHERE ip_hash = ?").bind(rowKey).first();
        if (!existing || (nowSec - Number(existing.updated_ep || 0)) >= 10) {
          const p2pPeers = Math.max(0, Math.min(256, parseInt(body.p2pool_peers || 0, 10) || 0));
          const chainH = Math.max(0, parseInt(body.chain_height || 0, 10) || 0);
          const bestShare = String(body.best_share_hash || "").slice(0, 80);
          const minersCnt = Math.max(0, Math.min(10000, parseInt(ps.connectedMiners || 0, 10) || 0));
          const workersCnt = Math.max(minersCnt, Math.min(50000, parseInt(ps.connectedWorkers || 0, 10) || 0));
          const sharesPs = Math.max(0, Number(ps.sharesPerSecond || 0) || 0);
          const totalBlocks = Math.max(0, parseInt(pp.totalBlocks || 0, 10) || 0);
          const lastBlockIso = pp.lastPoolBlockTime ? String(pp.lastPoolBlockTime).slice(0, 40) : null;
          const netPeers = Math.max(0, Math.min(500, parseInt(ns.connectedPeers || 0, 10) || 0));

          const p2pPort = Math.max(1, Math.min(65535, parseInt(mesh.p2p_port || 8344, 10) || 8344));
          const stunUdpPort = Math.max(0, Math.min(65535, parseInt(mesh.external_udp_port || mesh.udp_port || 0, 10) || 0));
          const upnpOpen = mesh.upnp_open ? 1 : 0;
          const natMap = String(mesh.nat_mapping || "unknown").replace(/[^a-z_]/g, "").slice(0, 28) || "unknown";
          const wanPeers = Math.max(0, Math.min(256, parseInt(mesh.wan_peers || 0, 10) || 0));
          const lanPeers = Math.max(0, Math.min(256, parseInt(mesh.lan_peers || 0, 10) || 0));
          const hpTunnels = Math.max(0, Math.min(64, parseInt(mesh.holepunch_tunnels || 0, 10) || 0));
          const nodeVer = String(body.version || "").slice(0, 24);

          await env.DB.prepare(`
            INSERT INTO node_reports (
              ip_hash, updated_ep, p2pool_peers, chain_height, best_share,
              miners_cnt, workers_cnt, pool_hr, shares_ps, total_blocks,
              last_block_iso, block_height, net_diff, net_hr, net_peers,
              peer_ip, p2p_port, stun_udp_port, upnp_open, nat_mapping,
              wan_peers, lan_peers, hp_tunnels, node_ver, instance_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ip_hash) DO UPDATE SET
              updated_ep=excluded.updated_ep, p2pool_peers=excluded.p2pool_peers,
              chain_height=excluded.chain_height, best_share=excluded.best_share,
              miners_cnt=excluded.miners_cnt, workers_cnt=excluded.workers_cnt,
              pool_hr=excluded.pool_hr, shares_ps=excluded.shares_ps,
              total_blocks=excluded.total_blocks, last_block_iso=excluded.last_block_iso,
              block_height=excluded.block_height, net_diff=excluded.net_diff,
              net_hr=excluded.net_hr, net_peers=excluded.net_peers,
              peer_ip=excluded.peer_ip, p2p_port=excluded.p2p_port,
              stun_udp_port=excluded.stun_udp_port, upnp_open=excluded.upnp_open,
              nat_mapping=excluded.nat_mapping, wan_peers=excluded.wan_peers,
              lan_peers=excluded.lan_peers, hp_tunnels=excluded.hp_tunnels,
              node_ver=excluded.node_ver, instance_id=excluded.instance_id
          `).bind(
            rowKey, nowSec, p2pPeers, chainH, bestShare,
            minersCnt, workersCnt, rawPoolHr, sharesPs, totalBlocks,
            lastBlockIso, blkH, netDiff, netHr, netPeers,
            peerIpStored, p2pPort, stunUdpPort, upnpOpen, natMap,
            wanPeers, lanPeers, hpTunnels, nodeVer, instClean
          ).run();

          if (Math.random() < 0.08) {
            await env.DB.prepare("DELETE FROM node_reports WHERE updated_ep < ?").bind(nowSec - 86400).run();
          }
        }

        const { results: peerRows } = await env.DB.prepare(
          "SELECT * FROM node_reports ORDER BY updated_ep DESC LIMIT 200"
        ).all();
        const rPeers = buildRendezvousPeers(peerRows || [], nowSec, netHash, callerV4, instClean);
        const diag = buildNodesDiagnostics(peerRows || [], nowSec);

        const relayWssUrl = env.RELAY_DO
          ? new URL("/p2p-relay", url.origin).toString().replace(/^http:/i, "ws:").replace(/^https:/i, "wss:")
          : "";
        return new Response(JSON.stringify({
          ok: true,
          relay_enabled: Boolean(env.RELAY_DO),
          relay_wss_url: relayWssUrl,
          rendezvous_peers: rPeers,
          unique_wan_networks: diag.summary.unique_wan_networks,
          split_brain_warning: diag.summary.split_brain_warning
        }), {
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

    if (path === "/api/nodes" || path === "/api/nodes.json") {
      const diag = buildNodesDiagnostics(results || [], nowSec);
      diag.summary.relay_enabled = Boolean(env.RELAY_DO);
      return new Response(JSON.stringify(diag, null, 2), {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json", "Cache-Control": "no-store" }
      });
    }

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

    const diagSummary = buildNodesDiagnostics(results || [], nowSec).summary;
    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scash P2Pool — Live Decentralized Sharechain Stats & Mesh Diagnostics</title>
<style>body{background:#12101c;color:#f3eefc;font-family:system-ui,sans-serif;max-width:780px;margin:40px auto;padding:0 20px;line-height:1.55}
.card{background:#1c182b;border:1px solid #352d52;border-radius:14px;padding:22px;margin:18px 0}
code,pre{background:#100d1a;color:#a5f3fc;padding:3px 7px;border-radius:6px;font-size:13px;overflow-x:auto}pre{padding:14px}a{color:#c084fc}</style></head>
<body><h1>Scash P2Pool (<code>v0.4.1</code>) — Serverless Pool Stats &amp; Global Mesh</h1>
<p>100% decentralized community-reported P2Pool stats &amp; Dual-Stack IPv4/IPv6 HTTPS :443 NAT peer rendezvous:</p>
<div class="card"><p><strong>Live Endpoints:</strong> <a href="./api/pools"><code>/api/pools</code></a> &middot; <a href="./api/nodes"><code>/api/nodes</code> (Global Mesh Diagnostics)</a> &middot; <a href="https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases">Download Scash P2Pool</a></p>
<p style="font-size:13px;color:#d8b4fe">Active Nodes: <strong>${diagSummary.active_nodes}</strong> &middot; Unique WAN Networks: <strong>${diagSummary.unique_wan_networks}</strong> &middot; Split-Brain Warning: <strong>${diagSummary.split_brain_warning ? "YES" : "No"}</strong></p>
<pre>${JSON.stringify({ pools: [poolObj] }, null, 2)}</pre></div></body></html>`;
    return new Response(html, { headers: { ...CORS_HEADERS, "Content-Type": "text/html; charset=utf-8" } });
  }
};

// === Scash P2Pool v0.4.1 Durable Object Hibernation WebSocket CGNAT Relay ===
const MAX_WS_FRAME_BYTES = 262144; // 256 KB max P2Pool message frame
const MAX_ROOM_SOCKETS = 96;

function makePairKey(instA, instB) {
  return instA < instB ? `${instA}|${instB}` : `${instB}|${instA}`;
}

function canPairEntries(a, b, activePairKeys) {
  if (!a || !b || a.att.inst === b.att.inst) return false;
  if (activePairKeys.has(makePairKey(a.att.inst, b.att.inst))) return false;
  // Never pair two rigs behind the exact same home router/LAN (they connect directly over LAN :8344)
  if (a.att.netHash && b.att.netHash && a.att.netHash === b.att.netHash) return false;
  const skipA = Array.isArray(a.att.skip) ? a.att.skip : [];
  const skipB = Array.isArray(b.att.skip) ? b.att.skip : [];
  if (skipA.includes(b.att.inst) || skipB.includes(a.att.inst)) return false;
  return true;
}

export class P2PoolRelayRoom {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this._connMap = null;
  }

  _getSockets() {
    if (this.ctx && typeof this.ctx.getWebSockets === "function") {
      return this.ctx.getWebSockets();
    }
    return this._fallbackSockets || [];
  }

  _readAtt(ws) {
    try {
      if (ws && typeof ws.deserializeAttachment === "function") {
        const a = ws.deserializeAttachment();
        if (a && typeof a === "object") return a;
      }
    } catch (_) {}
    return (ws && ws._scashAtt) ? ws._scashAtt : null;
  }

  _writeAtt(ws, att) {
    if (!ws) return;
    ws._scashAtt = att;
    try {
      if (typeof ws.serializeAttachment === "function") {
        ws.serializeAttachment(att);
      }
    } catch (_) {}
  }

  _rebuildConnMap() {
    const m = new Map();
    for (const ws of this._getSockets()) {
      const att = this._readAtt(ws);
      if (att && att.connId) {
        m.set(att.connId, { ws, att });
      }
    }
    this._connMap = m;
    return m;
  }

  _safeClose(ws, code = 1000, reason = "closed") {
    if (!ws) return;
    try {
      const validCode = (code >= 1000 && code < 5000 && code !== 1004 && code !== 1005 && code !== 1006 && code !== 1015) ? code : 1000;
      ws.close(validCode, String(reason || "closed").slice(0, 64));
    } catch (_) {
      try { ws.close(); } catch (_2) {}
    }
    if (this._fallbackSockets) {
      this._fallbackSockets = this._fallbackSockets.filter(s => s !== ws);
    }
  }

  _pairSockets(entryA, entryB) {
    const aIsInit = String(entryA.att.inst) < String(entryB.att.inst);
    entryA.att.partnerConnId = entryB.att.connId;
    entryA.att.partnerInst = entryB.att.inst;
    entryA.att.role = aIsInit ? "initiator" : "responder";

    entryB.att.partnerConnId = entryA.att.connId;
    entryB.att.partnerInst = entryA.att.inst;
    entryB.att.role = aIsInit ? "responder" : "initiator";

    this._writeAtt(entryA.ws, entryA.att);
    this._writeAtt(entryB.ws, entryB.att);
    if (this._connMap) {
      this._connMap.set(entryA.att.connId, entryA);
      this._connMap.set(entryB.att.connId, entryB);
    }

    try {
      entryA.ws.send(JSON.stringify({
        type: "paired",
        role: entryA.att.role,
        peer_inst: entryB.att.inst,
        conn_id: entryA.att.connId
      }));
      entryB.ws.send(JSON.stringify({
        type: "paired",
        role: entryB.att.role,
        peer_inst: entryA.att.inst,
        conn_id: entryB.att.connId
      }));
      return true;
    } catch (_) {
      this._safeClose(entryA.ws, 1011, "pair_send_failed");
      this._safeClose(entryB.ws, 1011, "pair_send_failed");
      return false;
    }
  }

  async _matchWaitingSockets(forceSeekerPair = false) {
    const cmap = this._rebuildConnMap();
    const activePairKeys = new Set();
    const seekers = [];
    const acceptors = [];
    const nowMs = Date.now();

    for (const entry of cmap.values()) {
      const { ws, att } = entry;
      if (att.partnerConnId) {
        const partner = cmap.get(att.partnerConnId);
        if (!partner) {
          this._safeClose(ws, 1001, "partner_gone");
          cmap.delete(att.connId);
          continue;
        }
        activePairKeys.add(makePairKey(att.inst, partner.att.inst));
      } else if (Number(att.slot || 0) === 0) {
        seekers.push(entry);
      } else {
        acceptors.push(entry);
      }
    }

    seekers.sort((a, b) => Number(a.att.connectedAtMs || 0) - Number(b.att.connectedAtMs || 0));
    acceptors.sort((a, b) => Number(a.att.connectedAtMs || 0) - Number(b.att.connectedAtMs || 0));

    let hasActiveMesh = activePairKeys.size > 0;
    const unmatchedSeekers = [];

    // 1. Always attach unconnected Seekers (slot=0) to waiting Standby Acceptors (slot>=1) first!
    //    Because slot=1 sockets NEVER pair with other slot=1 sockets, connected miners never waste
    //    their standby slots forming closed cycles that would starve future CGNAT miners!
    for (const sk of seekers) {
      let bestIdx = -1;
      for (let i = 0; i < acceptors.length; i++) {
        const ac = acceptors[i];
        if (!canPairEntries(sk, ac, activePairKeys)) continue;
        bestIdx = i;
        break;
      }
      if (bestIdx >= 0) {
        const ac = acceptors.splice(bestIdx, 1)[0];
        if (this._pairSockets(sk, ac)) {
          activePairKeys.add(makePairKey(sk.att.inst, ac.att.inst));
          hasActiveMesh = true;
        }
      } else {
        unmatchedSeekers.push(sk);
      }
    }

    // 2. Bootstrap Seeker + Seeker (slot=0 + slot=0) when no mesh exists yet (or after 1.2s alarm safety net)
    let idx = 0;
    while (idx < unmatchedSeekers.length) {
      const s1 = unmatchedSeekers[idx];
      const waitedMs = nowMs - Number(s1.att.connectedAtMs || nowMs);
      if (hasActiveMesh && !forceSeekerPair && waitedMs < 1200) {
        idx += 1;
        continue;
      }
      let partnerIdx = -1;
      for (let j = idx + 1; j < unmatchedSeekers.length; j++) {
        const s2 = unmatchedSeekers[j];
        if (!canPairEntries(s1, s2, activePairKeys)) continue;
        partnerIdx = j;
        break;
      }
      if (partnerIdx >= 0) {
        const s2 = unmatchedSeekers.splice(partnerIdx, 1)[0];
        unmatchedSeekers.splice(idx, 1);
        if (this._pairSockets(s1, s2)) {
          activePairKeys.add(makePairKey(s1.att.inst, s2.att.inst));
          hasActiveMesh = true;
        }
      } else {
        idx += 1;
      }
    }

    if (unmatchedSeekers.length >= 2 && hasActiveMesh && !forceSeekerPair) {
      try {
        if (this.ctx && this.ctx.storage && typeof this.ctx.storage.setAlarm === "function") {
          await this.ctx.storage.setAlarm(Date.now() + 1250);
        }
      } catch (_) {}
    }
  }

  async alarm() {
    await this._matchWaitingSockets(true);
  }

  async fetch(request) {
    const url = new URL(request.url);
    const upgrade = (request.headers.get("Upgrade") || "").toLowerCase();
    if (upgrade !== "websocket") {
      const cmap = this._rebuildConnMap();
      let pairedCnt = 0;
      let waitingSeekers = 0;
      let waitingAcceptors = 0;
      for (const { att } of cmap.values()) {
        if (att.partnerConnId) pairedCnt += 1;
        else if (Number(att.slot || 0) === 0) waitingSeekers += 1;
        else waitingAcceptors += 1;
      }
      return new Response(JSON.stringify({
        ok: true,
        relay_enabled: true,
        protocol: "scash-p2pool-wss-relay-v1",
        active_sockets: cmap.size,
        paired_circuits: Math.floor(pairedCnt / 2),
        waiting_seekers: waitingSeekers,
        waiting_acceptors: waitingAcceptors
      }, null, 2), {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json", "Cache-Control": "no-store" }
      });
    }

    const net = String(url.searchParams.get("net") || "7363617368703236").replace(/[^0-9a-fA-F]/g, "").toLowerCase().slice(0, 32) || "7363617368703236";
    const inst = String(url.searchParams.get("inst") || "").replace(/[^0-9a-fA-F]/g, "").toLowerCase().slice(0, 24);
    const slot = Math.max(0, Math.min(2, parseInt(url.searchParams.get("slot") || "0", 10) || 0));
    const skipRaw = String(url.searchParams.get("skip") || "");
    const skip = skipRaw.split(",").map(s => s.replace(/[^0-9a-fA-F]/g, "").toLowerCase().slice(0, 24)).filter(Boolean).slice(0, 12);
    const netHash = String(request.headers.get("X-Scash-NetHash") || "").slice(0, 16);

    if (!inst || inst.length < 6) {
      return new Response(JSON.stringify({ ok: false, error: "missing_inst" }), { status: 400, headers: CORS_HEADERS });
    }

    const cmap = this._rebuildConnMap();
    // Replace any stale UNPAIRED waiting socket from the exact same (inst, slot)
    for (const [cid, entry] of Array.from(cmap.entries())) {
      if (!entry.att.partnerConnId && entry.att.inst === inst && Number(entry.att.slot || 0) === slot) {
        this._safeClose(entry.ws, 1000, "replaced_waiting_slot");
        cmap.delete(cid);
      }
    }

    if (cmap.size >= MAX_ROOM_SOCKETS) {
      return new Response(JSON.stringify({ ok: false, error: "relay_room_full" }), { status: 503, headers: CORS_HEADERS });
    }

    // Create WebSocketPair (supports both Cloudflare Workers global WebSocketPair and custom test factory)
    const pairFactory = globalThis.WebSocketPair;
    const pair = new pairFactory();
    const client = pair[0];
    const server = pair[1];

    const connId = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`);
    const att = {
      connId,
      net,
      inst,
      slot,
      netHash,
      skip,
      partnerConnId: null,
      partnerInst: null,
      role: null,
      connectedAtMs: Date.now()
    };

    if (this.ctx && typeof this.ctx.acceptWebSocket === "function") {
      this.ctx.acceptWebSocket(server);
    } else {
      if (!this._fallbackSockets) this._fallbackSockets = [];
      this._fallbackSockets.push(server);
    }
    this._writeAtt(server, att);

    await this._matchWaitingSockets(false);
    const updatedAtt = this._readAtt(server) || att;
    if (!updatedAtt.partnerConnId) {
      try {
        server.send(JSON.stringify({ type: "waiting", slot, conn_id: connId }));
      } catch (_) {}
    }

    if (typeof globalThis.SCASH_MAKE_WS_RESPONSE === "function") {
      return globalThis.SCASH_MAKE_WS_RESPONSE(client, server);
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, message) {
    const att = this._readAtt(ws);
    if (!att) {
      this._safeClose(ws, 1002, "missing_attachment");
      return;
    }

    if (typeof message === "string") {
      if (message.length <= 256 && message.includes('"ping"')) {
        try { ws.send(JSON.stringify({ type: "pong", ts: Date.now() })); } catch (_) {}
      }
      return;
    }

    const byteLen = message instanceof ArrayBuffer ? message.byteLength : (message && message.byteLength ? message.byteLength : 0);
    if (byteLen <= 0 || byteLen > MAX_WS_FRAME_BYTES) {
      if (byteLen > MAX_WS_FRAME_BYTES) {
        this._safeClose(ws, 1009, "frame_too_large");
      }
      return;
    }

    if (!att.partnerConnId) return;
    if (!this._connMap || !this._connMap.has(att.partnerConnId)) {
      this._rebuildConnMap();
    }
    const partner = this._connMap ? this._connMap.get(att.partnerConnId) : null;
    if (!partner || !partner.ws) {
      this._safeClose(ws, 1001, "partner_disconnected");
      return;
    }
    try {
      partner.ws.send(message);
    } catch (_) {
      this._handleDisconnect(partner.ws);
      this._safeClose(ws, 1001, "partner_send_error");
    }
  }

  _handleDisconnect(ws, code = 1000, reason = "closed") {
    const att = this._readAtt(ws);
    if (att && att.connId && this._connMap) {
      this._connMap.delete(att.connId);
    }
    this._safeClose(ws, code, reason);

    if (att && att.partnerConnId) {
      const cmap = this._rebuildConnMap();
      const partner = cmap.get(att.partnerConnId);
      if (partner && partner.ws) {
        partner.att.partnerConnId = null;
        this._writeAtt(partner.ws, partner.att);
        cmap.delete(partner.att.connId);
        try {
          partner.ws.send(JSON.stringify({ type: "peer_closed", peer_inst: att.inst }));
        } catch (_) {}
        this._safeClose(partner.ws, 1001, "peer_closed");
      }
    }
  }

  async webSocketClose(ws, code, reason, _wasClean) {
    this._handleDisconnect(ws, code, reason);
  }

  async webSocketError(ws, _error) {
    this._handleDisconnect(ws, 1011, "ws_error");
  }
}
