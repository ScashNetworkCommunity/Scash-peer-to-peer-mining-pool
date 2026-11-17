from __future__ import division

import errno
import json
import os
import sys
import time
import traceback

from twisted.internet import defer, reactor
from twisted.python import log
from twisted.web import resource, static

import p2pool
from bitcoin import data as bitcoin_data
from . import data as p2pool_data, p2p
from util import deferral, deferred_resource, graph, math, memory, pack, variable

def _atomic_read(filename):
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    try:
        with open(filename + '.new', 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    return None

def _atomic_write(filename, data):
    with open(filename + '.new', 'wb') as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except:
            pass
    try:
        os.rename(filename + '.new', filename)
    except: # XXX windows can't overwrite
        os.remove(filename)
        os.rename(filename + '.new', filename)

def get_web_root(wb, datadir_path, bitcoind_getinfo_var, stop_event=variable.Event(), static_dir=None):
    node = wb.node
    start_time = time.time()
    
    web_root = resource.Resource()
    
    def get_users():
        height, last = node.tracker.get_height_and_last(node.best_share_var.value)
        weights, total_weight, donation_weight = node.tracker.get_cumulative_weights(node.best_share_var.value, min(height, 720), 65535*2**256)
        res = {}
        for script in sorted(weights, key=lambda s: weights[s]):
            res[bitcoin_data.script2_to_address(script, node.net.PARENT)] = weights[script]/total_weight
        return res
    
    def get_current_scaled_txouts(scale, trunc=0):
        txouts = node.get_current_txouts()
        total = sum(txouts.itervalues())
        results = dict((script, value*scale//total) for script, value in txouts.iteritems())
        if trunc > 0:
            total_random = 0
            random_set = set()
            for s in sorted(results, key=results.__getitem__):
                if results[s] >= trunc:
                    break
                total_random += results[s]
                random_set.add(s)
            if total_random:
                winner = math.weighted_choice((script, results[script]) for script in random_set)
                for script in random_set:
                    del results[script]
                results[winner] = total_random
        if sum(results.itervalues()) < int(scale):
            results[math.weighted_choice(results.iteritems())] += int(scale) - sum(results.itervalues())
        return results
    
    def get_patron_sendmany(total=None, trunc='0.01'):
        if total is None:
            return 'need total argument. go to patron_sendmany/<TOTAL>'
        total = int(float(total)*1e8)
        trunc = int(float(trunc)*1e8)
        return json.dumps(dict(
            (bitcoin_data.script2_to_address(script, node.net.PARENT), value/1e8)
            for script, value in get_current_scaled_txouts(total, trunc).iteritems()
            if bitcoin_data.script2_to_address(script, node.net.PARENT) is not None
        ))
    
    def get_global_stats():
        # averaged over last hour
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        nonstale_hash_rate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
        stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)

        return dict(
            pool_nonstale_hash_rate=nonstale_hash_rate,
            pool_hash_rate=nonstale_hash_rate/(1 - stale_prop),
            pool_stale_prop=stale_prop,
            min_difficulty=bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target),
            network_block_difficulty=diff,
            network_hashrate=(diff * 2**32 // node.net.PARENT.BLOCK_PERIOD),
        )
    
    def get_local_stats():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        
        my_unstale_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes)
        my_orphan_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'orphan')
        my_doa_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'doa')
        my_share_count = my_unstale_count + my_orphan_count + my_doa_count
        my_stale_count = my_orphan_count + my_doa_count
        
        my_stale_prop = my_stale_count/my_share_count if my_share_count != 0 else None
        
        my_work = sum(bitcoin_data.target_to_average_attempts(share.target)
            for share in node.tracker.get_chain(node.best_share_var.value, lookbehind - 1)
            if share.hash in wb.my_share_hashes)
        actual_time = (node.tracker.items[node.best_share_var.value].timestamp -
            node.tracker.items[node.tracker.get_nth_parent_hash(node.best_share_var.value, lookbehind - 1)].timestamp)
        share_att_s = my_work / actual_time
        
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()

        miner_last_difficulties = {}
        for addr in wb.last_work_shares.value:
            miner_last_difficulties[addr] = bitcoin_data.target_to_difficulty(wb.last_work_shares.value[addr].target)
        
        return dict(
            my_hash_rates_in_last_hour=dict(
                note="DEPRECATED",
                nonstale=share_att_s,
                rewarded=share_att_s/(1 - global_stale_prop),
                actual=share_att_s/(1 - my_stale_prop) if my_stale_prop is not None else 0, # 0 because we don't have any shares anyway
            ),
            my_share_counts_in_last_hour=dict(
                shares=my_share_count,
                unstale_shares=my_unstale_count,
                stale_shares=my_stale_count,
                orphan_stale_shares=my_orphan_count,
                doa_stale_shares=my_doa_count,
            ),
            my_stale_proportions_in_last_hour=dict(
                stale=my_stale_prop,
                orphan_stale=my_orphan_count/my_share_count if my_share_count != 0 else None,
                dead_stale=my_doa_count/my_share_count if my_share_count != 0 else None,
            ),
            miner_hash_rates=miner_hash_rates,
            miner_dead_hash_rates=miner_dead_hash_rates,
            miner_last_difficulties=miner_last_difficulties,
            efficiency_if_miner_perfect=(1 - stale_orphan_shares/shares)/(1 - global_stale_prop) if shares else None, # ignores dead shares because those are miner's fault and indicated by pseudoshare rejection
            efficiency=(1 - (stale_orphan_shares+stale_doa_shares)/shares)/(1 - global_stale_prop) if shares else None,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            shares=dict(
                total=shares,
                orphan=stale_orphan_shares,
                dead=stale_doa_shares,
            ),
            uptime=time.time() - start_time,
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
            warnings=p2pool_data.get_warnings(node.tracker, node.best_share_var.value, node.net, bitcoind_getinfo_var.value, node.bitcoind_work.value),
            donation_proportion=wb.donation_percentage/100,
            version=p2pool.__version__,
            protocol_version=p2p.Protocol.VERSION,
            fee=wb.worker_fee,
        )
    
    class WebInterface(deferred_resource.DeferredResource):
        def __init__(self, func, mime_type='application/json', args=()):
            deferred_resource.DeferredResource.__init__(self)
            self.func, self.mime_type, self.args = func, mime_type, args
        
        def getChild(self, child, request):
            return WebInterface(self.func, self.mime_type, self.args + (child,))
        
        @defer.inlineCallbacks
        def render_GET(self, request):
            request.setHeader('Content-Type', self.mime_type)
            request.setHeader('Access-Control-Allow-Origin', '*')
            res = yield self.func(*self.args)
            defer.returnValue(json.dumps(res) if self.mime_type == 'application/json' else res)
    
    def decent_height():
        return min(node.tracker.get_height(node.best_share_var.value), 720)
    web_root.putChild('rate', WebInterface(lambda: p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, decent_height())/(1-p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, decent_height()))))
    web_root.putChild('difficulty', WebInterface(lambda: bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target)))
    web_root.putChild('users', WebInterface(get_users))
    web_root.putChild('user_stales', WebInterface(lambda: dict((bitcoin_data.pubkey_hash_to_address(ph, node.net.PARENT), prop) for ph, prop in
        p2pool_data.get_user_stale_props(node.tracker, node.best_share_var.value, node.tracker.get_height(node.best_share_var.value)).iteritems())))
    web_root.putChild('fee', WebInterface(lambda: wb.worker_fee))
    web_root.putChild('current_payouts', WebInterface(lambda: dict((bitcoin_data.script2_to_address(script, node.net.PARENT), value/1e8) for script, value in node.get_current_txouts().iteritems())))
    web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain'))
    web_root.putChild('global_stats', WebInterface(get_global_stats))
    web_root.putChild('local_stats', WebInterface(get_local_stats))
    web_root.putChild('peer_addresses', WebInterface(lambda: ' '.join('%s%s' % (peer.transport.getPeer().host, ':'+str(peer.transport.getPeer().port) if peer.transport.getPeer().port != node.net.P2P_PORT else '') for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('peer_txpool_sizes', WebInterface(lambda: dict(('%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port), peer.remembered_txs_size) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('pings', WebInterface(defer.inlineCallbacks(lambda: defer.returnValue(
        dict([(a, (yield b)) for a, b in
            [(
                '%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port),
                defer.inlineCallbacks(lambda peer=peer: defer.returnValue(
                    min([(yield peer.do_ping().addCallback(lambda x: x/0.001).addErrback(lambda fail: None)) for i in xrange(3)])
                ))()
            ) for peer in list(node.p2p_node.peers.itervalues())]
        ])
    ))))
    web_root.putChild('peer_versions', WebInterface(lambda: dict(('%s:%i' % peer.addr, peer.other_sub_version) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('payout_addr', WebInterface(lambda: bitcoin_data.pubkey_hash_to_address(wb.my_pubkey_hash, node.net.PARENT)))
    web_root.putChild('payout_addrs', WebInterface(lambda: list(('%s' % bitcoin_data.pubkey_hash_to_address(add, node.net.PARENT)) for add in wb.pubkeys.keys)))
    web_root.putChild('recent_blocks', WebInterface(lambda: [dict(
        ts=s.timestamp,
        hash='%064x' % s.header_hash,
        number=p2pool_data.parse_bip0034(s.share_data['coinbase'])[0],
        share='%064x' % s.hash,
    ) for s in node.tracker.get_chain(node.best_share_var.value, min(node.tracker.get_height(node.best_share_var.value), 24*60*60//node.net.SHARE_PERIOD)) if s.pow_hash <= s.header['bits'].target]))
    web_root.putChild('uptime', WebInterface(lambda: time.time() - start_time))
    web_root.putChild('stale_rates', WebInterface(lambda: p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, decent_height(), rates=True)))
    
    new_root = resource.Resource()
    web_root.putChild('web', new_root)
    
    stat_log = []
    if os.path.exists(os.path.join(datadir_path, 'stats')):
        try:
            with open(os.path.join(datadir_path, 'stats'), 'rb') as f:
                stat_log = json.loads(f.read())
        except:
            log.err(None, 'Error loading stats:')
    def update_stat_log():
        while stat_log and stat_log[0]['time'] < time.time() - 24*60*60:
            stat_log.pop(0)
        
        lookbehind = 3600//node.net.SHARE_PERIOD
        if node.tracker.get_height(node.best_share_var.value) < lookbehind:
            return None
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        
        my_current_payout=0.0
        for add in wb.pubkeys.keys:
            my_current_payout+=node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(add), 0)*1e-8
        stat_log.append(dict(
            time=time.time(),
            pool_hash_rate=p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)/(1-global_stale_prop),
            pool_stale_prop=global_stale_prop,
            local_hash_rates=miner_hash_rates,
            local_dead_hash_rates=miner_dead_hash_rates,
            shares=shares,
            stale_shares=stale_orphan_shares + stale_doa_shares,
            stale_shares_breakdown=dict(orphan=stale_orphan_shares, doa=stale_doa_shares),
            current_payout=my_current_payout,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
        ))
        
        with open(os.path.join(datadir_path, 'stats'), 'wb') as f:
            f.write(json.dumps(stat_log))
    x = deferral.RobustLoopingCall(update_stat_log)
    x.start(5*60)
    stop_event.watch(x.stop)
    new_root.putChild('log', WebInterface(lambda: stat_log))
    
    def get_share(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        
        return dict(
            parent='%064x' % share.previous_hash,
            far_parent='%064x' % share.share_info['far_share_hash'],
            children=['%064x' % x for x in sorted(node.tracker.reverse.get(share.hash, set()), key=lambda sh: -len(node.tracker.reverse.get(sh, set())))], # sorted from most children to least children
            type_name=type(share).__name__,
            local=dict(
                verified=share.hash in node.tracker.verified.items,
                time_first_seen=start_time if share.time_seen == 0 else share.time_seen,
                peer_first_received_from=share.peer_addr,
            ),
            share_data=dict(
                timestamp=share.timestamp,
                target=share.target,
                max_target=share.max_target,
                payout_address=bitcoin_data.script2_to_address(share.new_script, node.net.PARENT),
                donation=share.share_data['donation']/65535,
                stale_info=share.share_data['stale_info'],
                nonce=share.share_data['nonce'],
                desired_version=share.share_data['desired_version'],
                absheight=share.absheight,
                abswork=share.abswork,
            ),
            block=dict(
                hash='%064x' % share.header_hash,
                header=dict(
                    version=share.header['version'],
                    previous_block='%064x' % share.header['previous_block'],
                    merkle_root='%064x' % share.header['merkle_root'],
                    timestamp=share.header['timestamp'],
                    target=share.header['bits'].target,
                    nonce=share.header['nonce'],
                ),
                gentx=dict(
                    hash='%064x' % share.gentx_hash,
                    coinbase=share.share_data['coinbase'].ljust(2, '\x00').encode('hex'),
                    value=share.share_data['subsidy']*1e-8,
                    last_txout_nonce='%016x' % share.contents['last_txout_nonce'],
                ),
                other_transaction_hashes=['%064x' % x for x in share.get_other_tx_hashes(node.tracker)],
            ),
        )

    def get_share_address(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        return bitcoin_data.script2_to_address(share.new_script, node.net.PARENT)

    new_root.putChild('payout_address', WebInterface(lambda share_hash_str: get_share_address(share_hash_str)))
    new_root.putChild('share', WebInterface(lambda share_hash_str: get_share(share_hash_str)))
    new_root.putChild('heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.heads]))
    new_root.putChild('verified_heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.verified.heads]))
    new_root.putChild('tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.tails for x in node.tracker.reverse.get(t, set())]))
    new_root.putChild('verified_tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.verified.tails for x in node.tracker.verified.reverse.get(t, set())]))
    new_root.putChild('best_share_hash', WebInterface(lambda: '%064x' % node.best_share_var.value))
    new_root.putChild('my_share_hashes', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in wb.my_share_hashes]))
    def get_share_data(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return ''
        share = node.tracker.items[int(share_hash_str, 16)]
        return p2pool_data.share_type.pack(share.as_share())
    new_root.putChild('share_data', WebInterface(lambda share_hash_str: get_share_data(share_hash_str), 'application/octet-stream'))
    new_root.putChild('currency_info', WebInterface(lambda: dict(
        symbol=node.net.PARENT.SYMBOL,
        block_explorer_url_prefix=node.net.PARENT.BLOCK_EXPLORER_URL_PREFIX,
        address_explorer_url_prefix=node.net.PARENT.ADDRESS_EXPLORER_URL_PREFIX,
        tx_explorer_url_prefix=node.net.PARENT.TX_EXPLORER_URL_PREFIX,
    )))
    new_root.putChild('version', WebInterface(lambda: p2pool.__version__))
    
    hd_path = os.path.join(datadir_path, 'graph_db')
    hd_data = _atomic_read(hd_path)
    hd_obj = {}
    if hd_data is not None:
        try:
            hd_obj = json.loads(hd_data)
        except Exception:
            log.err(None, 'Error reading graph database:')
    dataview_descriptions = {
        'last_hour': graph.DataViewDescription(150, 60*60),
        'last_day': graph.DataViewDescription(300, 60*60*24),
        'last_week': graph.DataViewDescription(300, 60*60*24*7),
        'last_month': graph.DataViewDescription(300, 60*60*24*30),
        'last_year': graph.DataViewDescription(300, 60*60*24*365.25),
    }
    hd = graph.HistoryDatabase.from_obj({
        'local_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_dead_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_share_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False,
            multivalues=True, multivalue_undefined_means_0=True,
            default_func=graph.make_multivalue_migrator(dict(good='local_share_hash_rate', dead='local_dead_share_hash_rate', orphan='local_orphan_share_hash_rate'),
                post_func=lambda bins: [dict((k, (v[0] - (sum(bin.get(rem_k, (0, 0))[0] for rem_k in ['dead', 'orphan']) if k == 'good' else 0), v[1])) for k, v in bin.iteritems()) for bin in bins])),
        'pool_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'current_payout': graph.DataStreamDescription(dataview_descriptions),
        'current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'peers': graph.DataStreamDescription(dataview_descriptions, multivalues=True, default_func=graph.make_multivalue_migrator(dict(incoming='incoming_peers', outgoing='outgoing_peers'))),
        'miner_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'miner_dead_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'desired_version_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'traffic_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'getwork_latency': graph.DataStreamDescription(dataview_descriptions),
        'memory_usage': graph.DataStreamDescription(dataview_descriptions),
    }, hd_obj)
    x = deferral.RobustLoopingCall(lambda: _atomic_write(hd_path, json.dumps(hd.to_obj())))
    x.start(100)
    stop_event.watch(x.stop)
    @wb.pseudoshare_received.watch
    def _(work, dead, user):
        t = time.time()
        hd.datastreams['local_hash_rate'].add_datum(t, work)
        if dead:
            hd.datastreams['local_dead_hash_rate'].add_datum(t, work)
        if user is not None:
            hd.datastreams['miner_hash_rates'].add_datum(t, {user: work})
            if dead:
                hd.datastreams['miner_dead_hash_rates'].add_datum(t, {user: work})
    @wb.share_received.watch
    def _(work, dead, share_hash):
        t = time.time()
        if not dead:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=work))
        else:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=work))
        def later():
            res = node.tracker.is_child_of(share_hash, node.best_share_var.value)
            if res is None: res = False # share isn't connected to sharechain? assume orphaned
            if res and dead: # share was DOA, but is now in sharechain
                # move from dead to good
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=-work, good=work))
            elif not res and not dead: # share wasn't DOA, and isn't in sharechain
                # move from good to orphan
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=-work, orphan=work))
        reactor.callLater(200, later)
    @node.p2p_node.traffic_happened.watch
    def _(name, bytes):
        hd.datastreams['traffic_rate'].add_datum(time.time(), {name: bytes})
    def add_point():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.net.CHAIN_LENGTH, 60*60//node.net.SHARE_PERIOD, node.tracker.get_height(node.best_share_var.value))
        t = time.time()
        
        pool_rates = p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, lookbehind, rates=True)
        pool_total = sum(pool_rates.itervalues())
        hd.datastreams['pool_rates'].add_datum(t, pool_rates)
        
        current_txouts = node.get_current_txouts()
        my_current_payouts = 0.0
        for add in wb.pubkeys.keys:
             my_current_payouts += current_txouts.get(bitcoin_data.pubkey_hash_to_script2(add), 0)*1e-8
        hd.datastreams['current_payout'].add_datum(t, my_current_payouts)
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        current_txouts_by_address = dict((bitcoin_data.script2_to_address(script, node.net.PARENT), amount) for script, amount in current_txouts.iteritems())
        hd.datastreams['current_payouts'].add_datum(t, dict((user, current_txouts_by_address[user]*1e-8) for user in miner_hash_rates if user in current_txouts_by_address))
        
        hd.datastreams['peers'].add_datum(t, dict(
            incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
            outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
        ))
        
        vs = p2pool_data.get_desired_version_counts(node.tracker, node.best_share_var.value, lookbehind)
        vs_total = sum(vs.itervalues())
        hd.datastreams['desired_version_rates'].add_datum(t, dict((str(k), v/vs_total*pool_total) for k, v in vs.iteritems()))
        try:
            hd.datastreams['memory_usage'].add_datum(t, memory.resident())
        except:
            if p2pool.DEBUG:
                traceback.print_exc()
    x = deferral.RobustLoopingCall(add_point)
    x.start(5)
    stop_event.watch(x.stop)
    @node.bitcoind_work.changed.watch
    def _(new_work):
        hd.datastreams['getwork_latency'].add_datum(time.time(), new_work['latency'])
    new_root.putChild('graph_data', WebInterface(lambda source, view: hd.datastreams[source].dataviews[view].get_data(time.time())))
    
    if static_dir is None:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'web-static')
    web_root.putChild('static', static.File(static_dir))
    
    return web_root

# --- Scash QtKawaii Built-in XMRig & Community Nodes Web Endpoints ---
try:
    import os
    import base64 as _w_b64
    import json as _w_json
    import time as _w_time
    import threading as _w_threading
    try:
        import urllib.request as _w_ureq
    except ImportError:
        import urllib2 as _w_ureq
    from twisted.web import resource as _tw_resource
    from p2pool import xmrig_manager as _xmrig_mgr
    from p2pool import scash_nodes as _scash_nodes

    _w_noproxy = _w_ureq.build_opener(_w_ureq.ProxyHandler({}))
    _w_wan_opener = _w_ureq.build_opener()
    _node_status_cache = {'ts': 0.0, 'data': None, 'refreshing': False}
    _ghpages_started = {'active': False}
    _GHPAGES_INDEX_HTML = _w_b64.b64decode('PCFET0NUWVBFIGh0bWw+PGh0bWwgbGFuZz0iZW4iPjxoZWFkPjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij48bWV0YSBuYW1lPSJ2aWV3cG9ydCIgY29udGVudD0id2lkdGg9ZGV2aWNlLXdpZHRoLGluaXRpYWwtc2NhbGU9MSI+PHRpdGxlPlNjYXNoIFAyUG9vbCDigJQgUHVibGljIE1pbmluZ2NvcmUgLyBNaW5pbmdQb29sU3RhdHMgQVBJPC90aXRsZT48c3R5bGU+Ym9keXtiYWNrZ3JvdW5kOiMxMjEwMWM7Y29sb3I6I2YzZWVmYztmb250LWZhbWlseTpzeXN0ZW0tdWksLWFwcGxlLXN5c3RlbSxzYW5zLXNlcmlmO21heC13aWR0aDo3NjBweDttYXJnaW46NDBweCBhdXRvO3BhZGRpbmc6MCAyMHB4O2xpbmUtaGVpZ2h0OjEuNTV9LmNhcmR7YmFja2dyb3VuZDojMWMxODJiO2JvcmRlcjoxcHggc29saWQgIzM1MmQ1Mjtib3JkZXItcmFkaXVzOjE0cHg7cGFkZGluZzoyMnB4O21hcmdpbjoxOHB4IDB9Y29kZSxwcmV7YmFja2dyb3VuZDojMTAwZDFhO2NvbG9yOiNhNWYzZmM7cGFkZGluZzozcHggN3B4O2JvcmRlci1yYWRpdXM6NnB4O2ZvbnQtc2l6ZToxM3B4O292ZXJmbG93LXg6YXV0b31wcmV7cGFkZGluZzoxNHB4fWF7Y29sb3I6I2MwODRmY308L3N0eWxlPjwvaGVhZD48Ym9keT48aDE+U2Nhc2ggUDJQb29sICg8Y29kZT52MC4yLjA8L2NvZGU+KSDigJQgUHVibGljIFBvb2wgU3RhdHMgQVBJPC9oMT48cD5NaW5pbmdjb3JlLWNvbXBhdGlibGUgcmVhZC1vbmx5IEpTT04gZW5kcG9pbnQgZm9yIDxhIGhyZWY9Imh0dHBzOi8vbWluaW5ncG9vbHN0YXRzLnN0cmVhbS9zYXRvc2hpY2FzaCI+TWluaW5nUG9vbFN0YXRzPC9hPiBhbmQgcG9vbCB0cmFja2Vyczo8L3A+PGRpdiBjbGFzcz0iY2FyZCI+PHA+PHN0cm9uZz5UcmFja2VyIEFQSSBFbmRwb2ludHM6PC9zdHJvbmc+IDxhIGhyZWY9Ii4vYXBpL3Bvb2xzIj48Y29kZT4vYXBpL3Bvb2xzPC9jb2RlPjwvYT4gJm1pZGRvdDsgPGEgaHJlZj0iLi9hcGkvcG9vbHMuanNvbiI+PGNvZGU+L2FwaS9wb29scy5qc29uPC9jb2RlPjwvYT4gJm1pZGRvdDsgPGEgaHJlZj0iaHR0cHM6Ly9naXRodWIuY29tL1NjYXNoTmV0d29ya0NvbW11bml0eS9TY2FzaC1wZWVyLXRvLXBlZXItbWluaW5nLXBvb2wvcmVsZWFzZXMvbGF0ZXN0Ij5Eb3dubG9hZCBTY2FzaCBQMlBvb2wgdjAuMi4wPC9hPjwvcD48cHJlIGlkPSJvdXQiPkxvYWRpbmcgLi9hcGkvcG9vbHMuanNvbiAuLi48L3ByZT48L2Rpdj48c2NyaXB0PmZldGNoKCcuL2FwaS9wb29scy5qc29uJyx7Y2FjaGU6J25vLXN0b3JlJ30pLnRoZW4ocj0+ci5qc29uKCkpLnRoZW4oZD0+e2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdvdXQnKS50ZXh0Q29udGVudD1KU09OLnN0cmluZ2lmeShkLG51bGwsMik7fSkuY2F0Y2goZT0+e2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdvdXQnKS50ZXh0Q29udGVudD1TdHJpbmcoZSk7fSk7PC9zY3JpcHQ+PC9ib2R5PjwvaHRtbD4K').decode('utf-8')

    def _do_refresh_scashd_node():
        try:
            dd = os.environ.get('SCASH_ACTIVE_DATADIR') or _scash_nodes.get_scash_datadir()
            port = int(os.environ.get('SCASH_RPC_PORT') or 8342)
            u = os.environ.get('SCASH_RPC_USER') or ''
            pw = os.environ.get('SCASH_RPC_PASS') or ''
            if not u or not pw:
                cu, cp = _scash_nodes.read_cookie_credentials(dd)
                if cu and cp:
                    u, pw = cu, cp
                else:
                    fu, fp = _scash_nodes.read_conf_credentials(dd)
                    u, pw = fu or 'scashminer', fp or 'kawaiip2poolpass'

            def _rpc(method):
                url = 'http://127.0.0.1:%d/' % port
                body = _w_json.dumps({'jsonrpc': '1.0', 'id': 'web', 'method': method, 'params': []}).encode('utf-8')
                auth = _w_b64.b64encode(('%s:%s' % (u, pw)).encode('utf-8')).decode('ascii')
                req = _w_ureq.Request(url, body, {'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
                raw = _w_noproxy.open(req, timeout=1.8).read().decode('utf-8', 'replace')
                return (_w_json.loads(raw) or {}).get('result') or {}

            out = dict(_node_status_cache['data'] or {})
            out.update({
                'syncing': False,
                'p2pool_ready': True,
                'datadir': dd,
                'status_text': 'Local Scash Core 30.4 Node + P2Pool Active',
            })
            try:
                bc = _rpc('getblockchaininfo')
                net = _rpc('getnetworkinfo')
                mp = _rpc('getmempoolinfo')
                blks = int(bc.get('blocks', 0))
                hdrs = int(bc.get('headers', blks))
                diff_v = float(bc.get('difficulty', 0.0) or 0.0)
                nhps = diff_v * 4294967296.0 / 600.0 if diff_v > 0 else 0.0
                try:
                    mi = _rpc('getmininginfo')
                    if isinstance(mi, dict) and mi.get('networkhashps') is not None:
                        nhps = float(mi.get('networkhashps') or nhps)
                except Exception:
                    pass
                out.update({
                    'blocks': blks,
                    'headers': hdrs,
                    'progress_pct': round((100.0 * blks / hdrs), 2) if hdrs > 0 else 100.0,
                    'chain': bc.get('chain', 'scash'),
                    'bestblockhash': bc.get('bestblockhash', ''),
                    'difficulty': diff_v,
                    'networkhashps': nhps,
                    'connections': int(net.get('connections', 0)),
                    'subversion': net.get('subversion', '/Scash:30.4.0/'),
                    'mempool_txs': int(mp.get('size', 0)),
                    'mempool_bytes': int(mp.get('bytes', 0)),
                })
            except Exception:
                pass
            _node_status_cache['ts'] = _w_time.time()
            _node_status_cache['data'] = out
        finally:
            _node_status_cache['refreshing'] = False
        return _node_status_cache['data']

    def _query_live_scashd_node():
        if _node_status_cache['data'] is None:
            return _do_refresh_scashd_node()
        now = _w_time.time()
        if (now - _node_status_cache['ts']) >= 2.5 and not _node_status_cache['refreshing']:
            _node_status_cache['refreshing'] = True
            _t = _w_threading.Thread(target=_do_refresh_scashd_node)
            _t.daemon = True
            _t.start()
        return _node_status_cache['data']

    def _build_miningcore_pool_payload(_wb_ref):
        now_ts = _w_time.time()
        iso_now = _w_time.strftime('%Y-%m-%dT%H:%M:%SZ', _w_time.gmtime(now_ts))
        nd = _query_live_scashd_node() or {}
        blk_h = int(nd.get('blocks') or 0)
        net_diff = float(nd.get('difficulty') or 0.0)
        net_conns = int(nd.get('connections') or 0)
        net_hr = float(nd.get('networkhashps') or (net_diff * 4294967296.0 / 600.0 if net_diff > 0 else 0.0))

        pool_hr = 0.0
        shares_ps = 0.0
        miners_cnt = 0
        workers_cnt = 0
        total_blocks = 0
        last_block_iso = None

        try:
            from p2pool import data as _p2p_data
            _don_script = getattr(_p2p_data, 'DONATION_SCRIPT', None)
            _node = getattr(_wb_ref, 'node', None)
            _tracker = getattr(_node, 'tracker', None)
            _net = getattr(_node, 'net', None)
            _best = getattr(getattr(_node, 'best_share_var', None), 'value', None)
            if _best is not None and _tracker is not None and _best in _tracker.items:
                _ch_h = int(_tracker.get_height(_best))
                _real_len = int(getattr(_net, 'REAL_CHAIN_LENGTH', 5760))
                _scan_n = min(_ch_h, _real_len)
                if _ch_h >= 2:
                    try:
                        _lb = min(_ch_h, 360, _real_len)
                        if _lb >= 2:
                            pool_hr = float(_p2p_data.get_pool_attempts_per_second(_tracker, _best, _lb))
                            _s_tip = _tracker.items[_best]
                            _s_old = _tracker.items[_tracker.get_nth_parent_hash(_best, _lb - 1)]
                            _dt = max(1.0, float(_s_tip.timestamp - _s_old.timestamp))
                            shares_ps = round(float(_lb - 1) / _dt, 4)
                    except Exception:
                        pass
                elif _ch_h == 1:
                    try:
                        _s0 = _tracker.items[_best]
                        _att = float(2**256) / max(1.0, float(_s0.target) + 1.0)
                        _dt1 = max(15.0, float(now_ts - _s0.timestamp))
                        pool_hr = _att / _dt1
                        shares_ps = round(1.0 / _dt1, 4)
                    except Exception:
                        pass

                _scripts = set()
                _solved_ts = []
                for _sh in _tracker.get_chain(_best, _scan_n):
                    _sc = getattr(_sh, 'new_script', None)
                    if _sc and _sc != _don_script:
                        _scripts.add(_sc)
                    try:
                        if getattr(_sh, 'pow_hash', None) is not None and getattr(_sh, 'header', None) is not None:
                            if _sh.pow_hash <= _sh.header['bits'].target:
                                _solved_ts.append(int(_sh.timestamp))
                    except Exception:
                        pass
                if not _scripts and hasattr(_p2p_data, 'get_expected_payouts'):
                    try:
                        _exp = _p2p_data.get_expected_payouts(_tracker, _best, 2**256 - 1, 5000000000, _net) or {}
                        for _ek in _exp.keys():
                            if _ek and _ek != _don_script:
                                _scripts.add(_ek)
                    except Exception:
                        pass
                miners_cnt = len(_scripts)
                total_blocks = len(_solved_ts)
                if _solved_ts:
                    last_block_iso = _w_time.strftime('%Y-%m-%dT%H:%M:%SZ', _w_time.gmtime(max(_solved_ts)))
        except Exception:
            pass

        try:
            _xst = _xmrig_mgr.GLOBAL_XMRIG.get_status() or {}
            if _xst.get('running'):
                _lhr = float(_xst.get('hashrate_hs') or 0.0)
                if _lhr > pool_hr:
                    pool_hr = _lhr
                if miners_cnt < 1:
                    miners_cnt = 1
            _st_mon = getattr(_wb_ref, 'local_rate_monitor', None)
            if _st_mon is not None:
                _datums = [x for x in _st_mon.get_datums_in_last()[0]]
                _wset = set(d.get('user') for d in _datums if isinstance(d, dict) and d.get('user'))
                workers_cnt = max(miners_cnt, len(_wset))
            else:
                workers_cnt = miners_cnt
        except Exception:
            workers_cnt = miners_cnt

        return {
            'id': 'scash-p2pool',
            'coin': {
                'type': 'SCASH',
                'name': 'Satoshicash',
                'symbol': 'SCASH',
                'website': 'https://scashnetwork.org',
                'market': 'SCASH-USDT',
                'family': 'bitcoin',
                'algorithm': 'RandomSCASH',
            },
            'ports': {
                '8345': {
                    'name': 'Decentralized P2Pool Local Stratum (rx/scash)',
                    'listenAddress': '127.0.0.1',
                    'difficulty': 0.0625,
                    'varDiff': {
                        'minDiff': 0.015625,
                        'maxDiff': None,
                        'targetTime': 15,
                        'retargetTime': 60,
                        'variancePercent': 30,
                    },
                }
            },
            'paymentProcessing': {
                'enabled': True,
                'minimumPayment': 0.0,
                'payoutScheme': 'PPLNS',
                'payoutSchemeConfig': {'factor': 1.0},
            },
            'clientConnectionTimeout': 600,
            'jobRebroadcastTimeout': 15,
            'blockRefreshInterval': 1000,
            'poolFeePercent': 1.0,
            'address': 'scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc',
            'addressInfoLink': 'https://scash.tv/address/scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc',
            'poolStats': {
                'connectedMiners': int(miners_cnt),
                'connectedWorkers': int(max(miners_cnt, workers_cnt)),
                'poolHashrate': round(float(pool_hr), 2),
                'sharesPerSecond': float(shares_ps),
            },
            'networkStats': {
                'networkType': 'main',
                'networkHashrate': round(float(net_hr), 2),
                'networkDifficulty': float(net_diff),
                'lastNetworkBlockTime': iso_now,
                'blockHeight': int(blk_h),
                'connectedPeers': int(net_conns),
                'rewardType': 'POW',
            },
            'topMiners': [],
            'totalPaid': 0.0,
            'totalBlocks': int(total_blocks),
            'lastPoolBlockTime': last_block_iso,
            'blockReward': 50.0,
            'updatedAt': iso_now,
            'updatedAtEpoch': int(now_ts),
        }

    def _read_ghpages_token():
        tok = (os.environ.get('SCASH_GHPAGES_TOKEN') or '').strip()
        if tok:
            return tok
        dirs = ['.']
        try:
            _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for _d in (_here, os.path.dirname(_here)):
                if _d and _d not in dirs:
                    dirs.append(_d)
        except Exception:
            pass
        try:
            _sdd = os.environ.get('SCASH_ACTIVE_DATADIR') or _scash_nodes.get_scash_datadir()
            if _sdd and _sdd not in dirs:
                dirs.append(_sdd)
        except Exception:
            pass
        for _base in dirs:
            for _fn in ('ghpages_token.txt', 'ghpages_token.txt.txt', '.ghpages_token'):
                try:
                    _fp = os.path.join(_base, _fn)
                    if os.path.isfile(_fp):
                        _t = open(_fp, 'r').read().strip()
                        if _t:
                            return _t
                except Exception:
                    pass
        return ''

    def _push_ghpages_snapshot_once(tok, repo_slug, payload_obj, push_state=None):
        api_base = (os.environ.get('SCASH_GH_API_BASE') or 'https://api.github.com').rstrip('/')
        raw_base = (os.environ.get('SCASH_GH_RAW_BASE') or 'https://raw.githubusercontent.com').rstrip('/')
        now_ep = int(_w_time.time())
        if push_state is None:
            push_state = {'history': [], 'last_miners': None, 'last_blocks': None, 'last_push_ts': 0}

        # Enforce GitHub Pages soft limit (<= 9 builds per rolling 3600s hour; official cap is 10/hour)
        push_state['history'] = [t for t in push_state.get('history', []) if (now_ep - t) < 3600]
        if len(push_state['history']) >= 9:
            return False

        p0 = (payload_obj.get('pools') or [{}])[0]
        ps = p0.get('poolStats') or {}
        local_hr = float(ps.get('poolHashrate') or 0.0)
        local_miners = int(ps.get('connectedMiners') or 0)
        local_blocks = int(p0.get('totalBlocks') or 0)

        event_changed = (
            (push_state.get('last_miners') is not None and local_miners != push_state.get('last_miners'))
            or (push_state.get('last_blocks') is not None and local_blocks != push_state.get('last_blocks'))
        )
        since_last = now_ep - int(push_state.get('last_push_ts') or 0)
        # Push within 60s when miners join/leave or a block is solved; otherwise pace steady-state updates at 390s (~9/hr)
        min_gap = 60 if event_changed else 390
        if push_state.get('last_push_ts') and since_last < min_gap:
            return False

        try:
            r_req = _w_ureq.Request('%s/%s/gh-pages/api/pools.json' % (raw_base, repo_slug), headers={'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.2.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)'})
            r_txt = _w_wan_opener.open(r_req, timeout=4.0).read().decode('utf-8', 'replace')
            r_obj = (_w_json.loads(r_txt) or {}).get('pools') or []
            if r_obj:
                r_ep = int(r_obj[0].get('updatedAtEpoch') or 0)
                r_ps = r_obj[0].get('poolStats') or {}
                r_hr = float(r_ps.get('poolHashrate') or 0.0)
                r_miners = int(r_ps.get('connectedMiners') or 0)
                r_blocks = int(r_obj[0].get('totalBlocks') or 0)
                r_age = now_ep - r_ep
                # Multi-rig coordination: don't double-push right after another rig updated gh-pages
                if r_age < (55 if (local_miners != r_miners or local_blocks != r_blocks) else 360):
                    return False
                # Don't let an idle rig overwrite an active rig's live hashrate for 15 minutes
                if local_hr <= 0.0 and r_hr > 0.0 and r_age < 900:
                    return False
                # Avoid wasting hourly builds pushing identical 0-miner idle state more than once per 30 minutes
                if local_hr <= 0.0 and r_hr <= 0.0 and local_miners == 0 and r_miners == 0 and r_age < 1800:
                    return False
        except Exception:
            pass

        def _gh_call(method, path, body_dict):
            url = '%s/repos/%s%s' % (api_base, repo_slug, path)
            data = _w_json.dumps(body_dict).encode('utf-8')
            hdrs = {
                'Authorization': 'Bearer ' + tok,
                'Accept': 'application/vnd.github+json',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.2.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
            }
            req = _w_ureq.Request(url, data, hdrs)
            req.get_method = lambda: method
            resp = _w_wan_opener.open(req, timeout=8.0).read().decode('utf-8', 'replace')
            return _w_json.loads(resp)

        json_body = _w_json.dumps(payload_obj, indent=2, sort_keys=True) + chr(10)
        tree_res = _gh_call('POST', '/git/trees', {
            'tree': [
                {'path': '.nojekyll', 'mode': '100644', 'type': 'blob', 'content': ''},
                {'path': 'index.html', 'mode': '100644', 'type': 'blob', 'content': _GHPAGES_INDEX_HTML},
                {'path': 'api/pools', 'mode': '100644', 'type': 'blob', 'content': json_body},
                {'path': 'api/pools.json', 'mode': '100644', 'type': 'blob', 'content': json_body},
            ]
        })
        commit_res = _gh_call('POST', '/git/commits', {
            'message': 'Update live Scash P2Pool stats snapshot [skip ci]',
            'tree': tree_res['sha'],
            'parents': [],
        })
        c_sha = commit_res['sha']
        try:
            _gh_call('PATCH', '/git/refs/heads/gh-pages', {'sha': c_sha, 'force': True})
        except Exception:
            _gh_call('POST', '/git/refs', {'ref': 'refs/heads/gh-pages', 'sha': c_sha})

        push_state['history'].append(now_ep)
        push_state['last_push_ts'] = now_ep
        push_state['last_miners'] = local_miners
        push_state['last_blocks'] = local_blocks
        return True

    def _maybe_start_ghpages_publisher(_wb_ref):
        if _ghpages_started['active']:
            return
        tok = _read_ghpages_token()
        if not tok:
            return
        _ghpages_started['active'] = True
        try:
            import sys as _w_sys
            _w_sys.stdout.write('[Stats API] GitHub Pages auto-publisher enabled (gh-pages /api/pools)' + chr(10))
            _w_sys.stdout.flush()
        except Exception:
            pass
        repo_slug = (os.environ.get('SCASH_GHPAGES_REPO') or 'ScashNetworkCommunity/Scash-peer-to-peer-mining-pool').strip()
        push_state = {'history': [], 'last_miners': None, 'last_blocks': None, 'last_push_ts': 0}

        def _loop():
            _w_time.sleep(20.0)
            while True:
                try:
                    cur_tok = _read_ghpages_token()
                    if cur_tok:
                        payload = {'pools': [_build_miningcore_pool_payload(_wb_ref)]}
                        _push_ghpages_snapshot_once(cur_tok, repo_slug, payload, push_state=push_state)
                except Exception:
                    pass
                # Poll local pool state every 60s (1 minute) so miner joins & solved blocks push within 1 minute
                # while steady-state updates automatically respect GitHub Pages' <= 10 builds/hour cap!
                _w_time.sleep(60.0)

        _t = _w_threading.Thread(target=_loop)
        _t.daemon = True
        _t.start()


    _community_reporter_started = {'active': False}
    _collector_cache = {'ts': 0.0, 'url': ''}

    def _resolve_collector_report_url():
        override = (os.environ.get('SCASH_STATS_REPORT_URL') or '').strip()
        if override:
            return override
        now_t = _w_time.time()
        if (now_t - _collector_cache['ts']) < 900.0:
            return _collector_cache['url']
        _collector_cache['ts'] = now_t
        repo_slug = (os.environ.get('SCASH_GHPAGES_REPO') or 'ScashNetworkCommunity/Scash-peer-to-peer-mining-pool').strip()
        raw_base = (os.environ.get('SCASH_GH_RAW_BASE') or 'https://raw.githubusercontent.com').rstrip('/')
        for u in (
            '%s/%s/gh-pages/collector.json' % (raw_base, repo_slug),
            'https://scashnetworkcommunity.github.io/Scash-peer-to-peer-mining-pool/collector.json',
        ):
            try:
                req = _w_ureq.Request(u, headers={'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.2.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)'})
                txt = _w_wan_opener.open(req, timeout=4.0).read().decode('utf-8', 'replace')
                obj = _w_json.loads(txt) or {}
                ru = str(obj.get('report_url') or '').strip()
                if ru.startswith('https://') or ru.startswith('http://127.0.0.1'):
                    _collector_cache['url'] = ru
                    return ru
                if 'report_url' in obj:
                    _collector_cache['url'] = ''
                    return ''
            except Exception:
                pass
        return _collector_cache['url']

    def _send_community_report_once(_wb_ref, report_url=None):
        if os.environ.get('SCASH_DISABLE_PUBLIC_STATS') == '1':
            return False
        target_url = report_url or _resolve_collector_report_url()
        if not target_url or not (target_url.startswith('https://') or target_url.startswith('http://127.0.0.1')):
            return False
        pool_obj = _build_miningcore_pool_payload(_wb_ref)
        best_hex = ''
        chain_h = 0
        p2p_peers = 0
        try:
            _node = getattr(_wb_ref, 'node', None)
            _tracker = getattr(_node, 'tracker', None)
            _best = getattr(getattr(_node, 'best_share_var', None), 'value', None)
            if _best is not None:
                best_hex = ('%064x' % int(_best)) if isinstance(_best, (int, getattr(__builtins__, 'long', int))) else str(_best)
                if _tracker is not None and _best in _tracker.items:
                    chain_h = int(_tracker.get_height(_best))
            _p2pn = getattr(_node, 'p2p_node', None)
            if _p2pn is not None and getattr(_p2pn, 'peers', None) is not None:
                p2p_peers = len(_p2pn.peers)
        except Exception:
            pass
        body = _w_json.dumps({
            'version': '0.2.0',
            'best_share_hash': best_hex,
            'chain_height': int(chain_h),
            'p2pool_peers': int(p2p_peers),
            'pool_payload': pool_obj,
        }).encode('utf-8')
        opener = _w_noproxy if target_url.startswith('http://127.0.0.1') else _w_wan_opener
        req = _w_ureq.Request(target_url, body, {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.2.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
        })
        opener.open(req, timeout=4.5).read()
        return True

    def _maybe_start_community_reporter(_wb_ref):
        if _community_reporter_started['active'] or os.environ.get('SCASH_DISABLE_PUBLIC_STATS') == '1':
            return
        if os.environ.get('SCASH_CI_ISOLATED_MESH') == '1':
            return
        _community_reporter_started['active'] = True

        def _c_loop():
            _w_time.sleep(12.0)
            while True:
                try:
                    _send_community_report_once(_wb_ref)
                except Exception:
                    pass
                _w_time.sleep(60.0)

        _ct = _w_threading.Thread(target=_c_loop)
        _ct.daemon = True
        _ct.start()

    class _ScashMiningcoreApiResource(_tw_resource.Resource):
        isLeaf = True
        def __init__(self, wb_ref=None):
            _tw_resource.Resource.__init__(self)
            self.wb_ref = wb_ref
        def render_OPTIONS(self, request):
            request.setHeader('Access-Control-Allow-Origin', '*')
            request.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS')
            request.setHeader('Access-Control-Allow-Headers', 'Content-Type')
            return b''
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            request.setHeader('Cache-Control', 'public, max-age=15')
            raw_pp = getattr(request, 'postpath', None) or []
            segs = []
            for _s in raw_pp:
                _st = _s.decode('utf-8', 'replace') if isinstance(_s, bytes) else str(_s)
                if _st:
                    segs.append(_st)
            pool_obj = _build_miningcore_pool_payload(self.wb_ref)
            if len(segs) >= 3 and segs[0] == 'pools' and segs[2] == 'blocks':
                out = []
            elif len(segs) >= 2 and segs[0] == 'pools' and segs[1] in ('scash-p2pool', 'scash'):
                out = {'pool': pool_obj}
            else:
                out = {'pools': [pool_obj]}
            s = _w_json.dumps(out)
            return s if isinstance(s, bytes) else s.encode('utf-8')

    class _ScashMinerControlResource(_tw_resource.Resource):
        isLeaf = True
        def __init__(self, action):
            _tw_resource.Resource.__init__(self)
            self.action = action
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Cache-Control', 'no-store')
            try:
                _h = request.getHost()
                if hasattr(_h, 'port') and _h.port:
                    _xmrig_mgr.GLOBAL_XMRIG.stratum_port = int(_h.port)
            except Exception:
                pass
            def _arg(k):
                vals = request.args.get(k, request.args.get(k.encode('utf-8'), [None]))
                v = vals[0] if vals else None
                return v.decode('utf-8', 'replace') if isinstance(v, bytes) else v
            def _jb(obj):
                s = _w_json.dumps(obj)
                return s if isinstance(s, bytes) else s.encode('utf-8')
            if self.action in ('start', 'stop'):
                try:
                    _cip = request.getClientIP()
                except Exception:
                    _cip = '127.0.0.1'
                if _cip and str(_cip) not in ('127.0.0.1', '::1', 'localhost'):
                    try:
                        request.setResponseCode(403)
                    except Exception:
                        pass
                    return _jb({'ok': False, 'error': 'Localhost only'})
            if self.action == 'status':
                return _jb(_xmrig_mgr.GLOBAL_XMRIG.get_status())
            elif self.action == 'start':
                return _jb(_xmrig_mgr.GLOBAL_XMRIG.start_mining(
                    wallet=_arg('wallet'),
                    threads=_arg('threads'),
                    worker=_arg('worker'),
                    large_pages=_arg('large_pages'),
                ))
            elif self.action == 'stop':
                return _jb(_xmrig_mgr.GLOBAL_XMRIG.stop_mining())
            elif self.action == 'sync':
                return _jb(_query_live_scashd_node())
            elif self.action == 'nodes':
                return _jb({
                    'addnodes': _scash_nodes.DEFAULT_SCASH_ADDNODES,
                    'dns_seeds': _scash_nodes.DEFAULT_DNS_SEEDS,
                })
            elif self.action == 'mesh':
                from p2pool import auto_mesh as _scash_auto_mesh
                return _jb(_scash_auto_mesh.get_mesh_status())
            return _jb({'ok': False})

    _orig_scash_get_web_root = get_web_root
    def get_web_root(*args, **kwargs):
        _wr = _orig_scash_get_web_root(*args, **kwargs)
        _wb_obj = args[0] if args else kwargs.get('wb')
        try:
            from p2pool import auto_mesh as _scash_auto_mesh
            _p2p_n = getattr(getattr(_wb_obj, 'node', None), 'p2p_node', None)
            if _p2p_n is not None:
                _scash_auto_mesh.start_for_p2p_node(_p2p_n)
        except Exception:
            pass
        try:
            _maybe_start_ghpages_publisher(_wb_obj)
            _maybe_start_community_reporter(_wb_obj)
        except Exception:
            pass
        _wr.putChild(b'miner_status', _ScashMinerControlResource('status'))
        _wr.putChild(b'miner_start', _ScashMinerControlResource('start'))
        _wr.putChild(b'miner_stop', _ScashMinerControlResource('stop'))
        _wr.putChild(b'nodes_list', _ScashMinerControlResource('nodes'))
        _wr.putChild(b'node_sync_status', _ScashMinerControlResource('sync'))
        _wr.putChild(b'mesh_status', _ScashMinerControlResource('mesh'))
        _wr.putChild(b'api', _ScashMiningcoreApiResource(_wb_obj))
        return _wr
except Exception:
    pass
