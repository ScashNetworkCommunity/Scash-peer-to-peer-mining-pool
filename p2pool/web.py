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
    import sys as _w_usys
    import base64 as _w_b64
    def _w_str(v):
        if v is None: return ''
        if isinstance(v, str): return v
        try:
            return v.encode('utf-8', 'replace') if _w_usys.version_info[0] < 3 else (v.decode('utf-8', 'replace') if isinstance(v, bytes) else str(v))
        except Exception: return ''
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
    _w_wan_unverified = None
    try:
        import ssl as _w_ssl
        try:
            import certifi as _w_certifi
            _w_cctx = _w_ssl.create_default_context(cafile=_w_certifi.where())
            _w_wan_opener = _w_ureq.build_opener(_w_ureq.HTTPSHandler(context=_w_cctx))
        except Exception:
            pass
        if hasattr(_w_ssl, '_create_unverified_context'):
            _w_wan_unverified = _w_ureq.build_opener(_w_ureq.HTTPSHandler(context=_w_ssl._create_unverified_context()))
    except Exception:
        pass

    def _scash_open_url(req_obj, timeout=4.5, is_local=False):
        if is_local:
            return _w_noproxy.open(req_obj, timeout=timeout).read()
        try:
            return _w_wan_opener.open(req_obj, timeout=timeout).read()
        except Exception:
            if _w_wan_unverified is not None:
                return _w_wan_unverified.open(req_obj, timeout=timeout).read()
            raise
    _node_status_cache = {'ts': 0.0, 'data': None, 'refreshing': False}
    _ghpages_started = {'active': False}
    _GHPAGES_INDEX_HTML = _w_b64.b64decode('PCFET0NUWVBFIGh0bWw+PGh0bWwgbGFuZz0iZW4iPjxoZWFkPjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij48bWV0YSBuYW1lPSJ2aWV3cG9ydCIgY29udGVudD0id2lkdGg9ZGV2aWNlLXdpZHRoLGluaXRpYWwtc2NhbGU9MSI+PHRpdGxlPlNjYXNoIFAyUG9vbCDigJQgUHVibGljIE1pbmluZ2NvcmUgLyBNaW5pbmdQb29sU3RhdHMgQVBJPC90aXRsZT48c3R5bGU+Ym9keXtiYWNrZ3JvdW5kOiMxMjEwMWM7Y29sb3I6I2YzZWVmYztmb250LWZhbWlseTpzeXN0ZW0tdWksLWFwcGxlLXN5c3RlbSxzYW5zLXNlcmlmO21heC13aWR0aDo3NjBweDttYXJnaW46NDBweCBhdXRvO3BhZGRpbmc6MCAyMHB4O2xpbmUtaGVpZ2h0OjEuNTV9LmNhcmR7YmFja2dyb3VuZDojMWMxODJiO2JvcmRlcjoxcHggc29saWQgIzM1MmQ1Mjtib3JkZXItcmFkaXVzOjE0cHg7cGFkZGluZzoyMnB4O21hcmdpbjoxOHB4IDB9Y29kZSxwcmV7YmFja2dyb3VuZDojMTAwZDFhO2NvbG9yOiNhNWYzZmM7cGFkZGluZzozcHggN3B4O2JvcmRlci1yYWRpdXM6NnB4O2ZvbnQtc2l6ZToxM3B4O292ZXJmbG93LXg6YXV0b31wcmV7cGFkZGluZzoxNHB4fWF7Y29sb3I6I2MwODRmY308L3N0eWxlPjwvaGVhZD48Ym9keT48aDE+U2Nhc2ggUDJQb29sICg8Y29kZT52MC4zLjU8L2NvZGU+KSDigJQgUHVibGljIFBvb2wgU3RhdHMgQVBJPC9oMT48cD5NaW5pbmdjb3JlLWNvbXBhdGlibGUgcmVhZC1vbmx5IEpTT04gZW5kcG9pbnQgZm9yIDxhIGhyZWY9Imh0dHBzOi8vbWluaW5ncG9vbHN0YXRzLnN0cmVhbS9zYXRvc2hpY2FzaCI+TWluaW5nUG9vbFN0YXRzPC9hPiBhbmQgcG9vbCB0cmFja2Vyczo8L3A+PGRpdiBjbGFzcz0iY2FyZCI+PHA+PHN0cm9uZz5UcmFja2VyIEFQSSBFbmRwb2ludHM6PC9zdHJvbmc+IDxhIGhyZWY9Ii4vYXBpL3Bvb2xzIj48Y29kZT4vYXBpL3Bvb2xzPC9jb2RlPjwvYT4gJm1pZGRvdDsgPGEgaHJlZj0iLi9hcGkvcG9vbHMuanNvbiI+PGNvZGU+L2FwaS9wb29scy5qc29uPC9jb2RlPjwvYT4gJm1pZGRvdDsgPGEgaHJlZj0iaHR0cHM6Ly9naXRodWIuY29tL1NjYXNoTmV0d29ya0NvbW11bml0eS9TY2FzaC1wZWVyLXRvLXBlZXItbWluaW5nLXBvb2wvcmVsZWFzZXMvbGF0ZXN0Ij5Eb3dubG9hZCBTY2FzaCBQMlBvb2wgdjAuMy41PC9hPjwvcD48cHJlIGlkPSJvdXQiPkxvYWRpbmcgLi9hcGkvcG9vbHMuanNvbiAuLi48L3ByZT48L2Rpdj48c2NyaXB0PmZldGNoKCcuL2FwaS9wb29scy5qc29uJyx7Y2FjaGU6J25vLXN0b3JlJ30pLnRoZW4ocj0+ci5qc29uKCkpLnRoZW4oZD0+e2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdvdXQnKS50ZXh0Q29udGVudD1KU09OLnN0cmluZ2lmeShkLG51bGwsMik7fSkuY2F0Y2goZT0+e2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdvdXQnKS50ZXh0Q29udGVudD1TdHJpbmcoZSk7fSk7PC9zY3JpcHQ+PC9ib2R5PjwvaHRtbD4K').decode('utf-8')

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


    # --- v0.4.0 Real 10s/60s/30m Averages + On-Chain P2Pool Block Ledger + Liquidity-Weighted SCASH Market Tracker ---
    import binascii as _w_binascii
    from p2pool.bitcoin import bech32_scash as _w_b32

    _hr_ring_lock = _w_threading.Lock()
    _pool_hr_ring = []
    _stratum_hr_ring = []
    _hr_sampler_started = {'active': False}

    def _ring_push(ring_list, now_ts, val):
        v = max(0.0, float(val or 0.0))
        t_now = float(now_ts)
        if ring_list and (t_now - ring_list[-1][0]) < 1.5:
            ring_list[-1] = (t_now, v)
        else:
            ring_list.append((t_now, v))
        cutoff = t_now - 2100.0
        if len(ring_list) > 40 and ring_list[0][0] < cutoff:
            del ring_list[:-480]
            while ring_list and ring_list[0][0] < cutoff:
                ring_list.pop(0)

    def _ring_avg(ring_list, window_sec, now_ts):
        if not ring_list:
            return 0.0
        cutoff = float(now_ts) - float(window_sec)
        vals = [ x[1] for x in ring_list if x[0] >= cutoff ]
        if not vals:
            return float(ring_list[-1][1])
        return sum(vals) / float(len(vals))

    def _measure_instant_stratum_hs(_wb_ref):
        try:
            _st_mon = getattr(_wb_ref, 'local_rate_monitor', None)
            if _st_mon is None:
                return 0.0
            datums, dt = _st_mon.get_datums_in_last()
            if not datums or not dt or float(dt) <= 0.0:
                return 0.0
            work_sum = 0.0
            from p2pool.bitcoin import data as _b_d2
            for d in datums:
                if isinstance(d, dict) and d.get('work') is not None:
                    work_sum += float(d.get('work') or 0.0)
                elif isinstance(d, dict) and d.get('target') is not None:
                    work_sum += float(_b_d2.target_to_average_attempts(int(d['target'])))
            return max(0.0, work_sum / float(dt))
        except Exception:
            return 0.0

    def _measure_sharechain_rates(_wb_ref, now_ts):
        live_hs = 0.0
        sc_60s_hs = 0.0
        sc_30m_hs = 0.0
        has_sc_30m = False
        try:
            from p2pool import data as _p2p_d2
            _node = getattr(_wb_ref, 'node', None)
            _tracker = getattr(_node, 'tracker', None)
            _net = getattr(_node, 'net', None)
            _best = getattr(getattr(_node, 'best_share_var', None), 'value', None)
            if _best is not None and _tracker is not None and _best in _tracker.items:
                _ch_h = int(_tracker.get_height(_best))
                _real_len = int(getattr(_net, 'REAL_CHAIN_LENGTH', 5760))
                if _ch_h >= 2:
                    _s_tip = _tracker.items[_best]
                    _tip_age = max(0.0, float(now_ts) - float(_s_tip.timestamp))
                    _lb = min(_ch_h, 360, _real_len)
                    if _lb >= 2:
                        live_hs = float(_p2p_d2.get_pool_attempts_per_second(_tracker, _best, _lb))
                    # Measure contiguous active window (up to 60 shares, stopping at any >300s power-outage gap)
                    if _tip_age <= 300.0:
                        _act_n = 1
                        _cur_h = _best
                        _prev_t = float(_s_tip.timestamp)
                        for _ in range(min(_ch_h - 1, 60)):
                            _par_h = _tracker.items[_cur_h].previous_hash
                            if _par_h not in _tracker.items:
                                break
                            _par_t = float(_tracker.items[_par_h].timestamp)
                            if (_prev_t - _par_t) > 300.0:
                                break
                            _act_n += 1
                            _cur_h = _par_h
                            _prev_t = _par_t
                        if _act_n >= 3:
                            _act_hr = float(_p2p_d2.get_pool_attempts_per_second(_tracker, _best, _act_n))
                            # Always adopt the post-gap contiguous window (reflects BOTH increases and miner drops!)
                            live_hs = _act_hr
                            sc_60s_hs = _act_hr
                    elif _tip_age > 300.0:
                        live_hs = 0.0
                    # Strict 30-minute (1800s) sharechain window: only count shares actually mined in the last 30m!
                    if _tip_age <= 1800.0:
                        _cur30 = _best
                        _work30 = 0.0
                        _cnt30 = 0
                        _oldest_t = float(_s_tip.timestamp)
                        for _ in range(min(_ch_h, _real_len, 720)):
                            _sh30 = _tracker.items.get(_cur30)
                            if _sh30 is None:
                                break
                            _st30 = float(_sh30.timestamp)
                            if (float(now_ts) - _st30) > 1800.0:
                                break
                            _work30 += float(2**256) / max(1.0, float(_sh30.target) + 1.0)
                            _cnt30 += 1
                            _oldest_t = _st30
                            _cur30 = getattr(_sh30, 'previous_hash', None)
                            if _cur30 is None:
                                break
                        if _cnt30 >= 2:
                            _span30 = max(60.0, min(1800.0, float(now_ts) - _oldest_t))
                            sc_30m_hs = _work30 / _span30
                            has_sc_30m = True
                elif _ch_h == 1:
                    _s0 = _tracker.items[_best]
                    _att = float(2**256) / max(1.0, float(_s0.target) + 1.0)
                    _dt1 = max(15.0, float(now_ts - _s0.timestamp))
                    live_hs = _att / _dt1
                    if (now_ts - float(_s0.timestamp)) <= 1800.0:
                        sc_30m_hs = _att / max(1800.0, _dt1)
                        has_sc_30m = True
        except Exception:
            pass
        return live_hs, sc_60s_hs, sc_30m_hs, has_sc_30m

    def _sample_hashrate_rings(_wb_ref, now_ts=None):
        t_now = float(now_ts if now_ts is not None else _w_time.time())
        xst = _xmrig_mgr.GLOBAL_XMRIG.get_status() or {}
        xm_live = float(xst.get('hashrate_hs') or 0.0) if xst.get('running') else 0.0
        xm_10 = float(xst.get('hashrate_10s_hs') or xm_live) if xst.get('running') else 0.0
        xm_60 = float(xst.get('hashrate_60s_hs') or xm_10) if xst.get('running') else 0.0
        xm_30m = float(xst.get('hashrate_30m_hs') or xm_60) if xst.get('running') else 0.0

        st_inst = _measure_instant_stratum_hs(_wb_ref)
        sc_live, sc_60, sc_30m, has_sc_30m = _measure_sharechain_rates(_wb_ref, t_now)
        loc_live = max(xm_live, st_inst)

        # Count live P2Pool peers + truly active miners (shares in last 15m) vs 24h PPLNS payout wallets
        _p2p_peer_cnt = 0
        _recent_15m_scripts = set()
        _pplns_24h_scripts = set()
        _don_sc_m = None
        try:
            from p2pool import data as _p2p_d_m
            _don_sc_m = getattr(_p2p_d_m, 'DONATION_SCRIPT', None)
        except Exception:
            _don_sc_m = None
        try:
            _nd_m = getattr(_wb_ref, 'node', None)
            _p2pn_m = getattr(_nd_m, 'p2p_node', None)
            if _p2pn_m is not None and getattr(_p2pn_m, 'peers', None) is not None:
                _p2p_peer_cnt = len(_p2pn_m.peers)
            _tr_m = getattr(_nd_m, 'tracker', None)
            _best_m = getattr(getattr(_nd_m, 'best_share_var', None), 'value', None)
            if _best_m is not None and _tr_m is not None and _best_m in _tr_m.items:
                _ch_m = int(_tr_m.get_height(_best_m))
                _net_m = getattr(_nd_m, 'net', None)
                _rl_m = int(getattr(_net_m, 'REAL_CHAIN_LENGTH', 5760))
                for _shm in _tr_m.get_chain(_best_m, min(_ch_m, _rl_m)):
                    _scm = getattr(_shm, 'new_script', None)
                    if _scm and _scm != _don_sc_m:
                        _pplns_24h_scripts.add(_scm)
                        if (t_now - float(getattr(_shm, 'timestamp', 0) or 0)) <= 900.0:
                            _recent_15m_scripts.add(_scm)
        except Exception:
            pass

        # When 0 P2Pool peers are connected, no remote rig can contribute live hashrate right now!
        if _p2p_peer_cnt == 0:
            pool_inst = loc_live
        else:
            pool_inst = max(sc_live, loc_live)

        with _hr_ring_lock:
            _ring_push(_stratum_hr_ring, t_now, st_inst)
            _ring_push(_pool_hr_ring, t_now, pool_inst)
            st_10 = _ring_avg(_stratum_hr_ring, 10.0, t_now)
            st_60 = _ring_avg(_stratum_hr_ring, 60.0, t_now)
            st_30m = _ring_avg(_stratum_hr_ring, 1800.0, t_now)
            p_roll_10 = _ring_avg(_pool_hr_ring, 10.0, t_now)
            p_roll_60 = _ring_avg(_pool_hr_ring, 60.0, t_now)
            p_roll_30m = _ring_avg(_pool_hr_ring, 1800.0, t_now)
            ring_span = (t_now - _pool_hr_ring[0][0]) if len(_pool_hr_ring) >= 2 else 0.0

        local_10s = max(xm_10, st_10)
        local_60s = max(xm_60, st_60)
        local_30m = max(xm_30m, st_30m)

        if _p2p_peer_cnt == 0:
            pool_10s = local_10s
            pool_60s = local_60s
            pool_30m = local_30m if local_30m > 0 else (sc_30m if has_sc_30m else p_roll_30m)
        else:
            pool_10s = max(p_roll_10, local_10s)
            pool_60s = max(p_roll_60, sc_60 if sc_60 > 0 else 0.0, local_60s)
            if has_sc_30m and ring_span < 1500.0:
                pool_30m = max(sc_30m, local_30m)
            else:
                pool_30m = max(p_roll_30m, sc_30m if has_sc_30m else 0.0, local_30m)

        _loc_workers = 1 if (xm_live > 0 or st_inst > 0) else 0
        if _p2p_peer_cnt == 0:
            _active_now = _loc_workers
        else:
            _active_now = max(len(_recent_15m_scripts), _loc_workers)

        return {
            'local_live_hs': round(loc_live, 2),
            'local_10s_hs': round(local_10s, 2),
            'local_60s_hs': round(local_60s, 2),
            'local_30m_hs': round(local_30m, 2),
            'pool_live_hs': round(pool_inst, 2),
            'pool_10s_hs': round(pool_10s, 2),
            'pool_60s_hs': round(pool_60s, 2),
            'pool_30m_hs': round(pool_30m, 2),
            'active_miners_now': int(_active_now),
            'pplns_miners_24h': int(max(len(_pplns_24h_scripts), _active_now)),
        }

    # --- Incremental Local Scashd P2Pool Block & Miner Payout Ledger ---
    _P2POOL_CB_HEX_TAGS = ('2f5032506f6f6c2f', '7363617368703236')  # '/P2Pool/' and 'scashp26'
    _ledger_lock = _w_threading.Lock()
    _ledger_state = {
        'loaded_path': '',
        'chain': '',
        'min_scanned_height': None,
        'max_scanned_height': None,
        'last_tip_hash': '',
        'blocks': {},
        'scanning': False,
        'last_scan_ts': 0.0,
    }
    _ledger_daemon_started = {'active': False}

    def _get_rpc_conn_params():
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
        return dd, port, u, pw

    def _scashd_rpc_batch(port, u, pw, calls, timeout=6.0):
        url = 'http://127.0.0.1:%d/' % int(port)
        payload = []
        for idx, (m, params) in enumerate(calls):
            payload.append({'jsonrpc': '1.0', 'id': idx, 'method': m, 'params': params})
        body = _w_json.dumps(payload).encode('utf-8')
        auth = _w_b64.b64encode(('%s:%s' % (u, pw)).encode('utf-8')).decode('ascii')
        req = _w_ureq.Request(url, body, {'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
        raw = _w_noproxy.open(req, timeout=timeout).read().decode('utf-8', 'replace')
        parsed = _w_json.loads(raw)
        if isinstance(parsed, list):
            by_id = {}
            for item in parsed:
                if isinstance(item, dict) and item.get('id') is not None:
                    by_id[int(item['id'])] = item.get('result')
            return [ by_id.get(i) for i in range(len(calls)) ]
        return []

    def _resolve_ledger_path(dd):
        for cand_dir in (dd, _xmrig_mgr.MINER_DIR):
            if cand_dir and os.path.isdir(cand_dir):
                return os.path.join(cand_dir, 'p2pool_blocks_ledger.json')
        return os.path.join(_xmrig_mgr.MINER_DIR, 'p2pool_blocks_ledger.json')

    def _load_ledger_if_needed(lpath, chain_name):
        with _ledger_lock:
            if _ledger_state['loaded_path'] == lpath and _ledger_state['chain'] == chain_name:
                return
            _ledger_state['loaded_path'] = lpath
            _ledger_state['chain'] = chain_name
            _ledger_state['min_scanned_height'] = None
            _ledger_state['max_scanned_height'] = None
            _ledger_state['blocks'] = {}
            if os.path.isfile(lpath):
                try:
                    raw = open(lpath, 'r').read()
                    obj = _w_json.loads(raw) or {}
                    if obj.get('chain') == chain_name and isinstance(obj.get('blocks'), dict):
                        _ledger_state['min_scanned_height'] = obj.get('min_scanned_height')
                        _ledger_state['max_scanned_height'] = obj.get('max_scanned_height')
                        _ledger_state['blocks'] = obj.get('blocks') or {}
                except Exception:
                    pass

    def _save_ledger_disk():
        with _ledger_lock:
            lpath = _ledger_state['loaded_path']
            if not lpath:
                return
            snap = {
                'version': 1,
                'chain': _ledger_state['chain'],
                'min_scanned_height': _ledger_state['min_scanned_height'],
                'max_scanned_height': _ledger_state['max_scanned_height'],
                'updated_at': int(_w_time.time()),
                'blocks': _ledger_state['blocks'],
            }
        try:
            d = os.path.dirname(lpath)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            tmp_p = lpath + '.tmp'
            with open(tmp_p, 'w') as f:
                f.write(_w_json.dumps(snap, sort_keys=True))
            if os.path.exists(lpath):
                try:
                    os.remove(lpath)
                except Exception:
                    pass
            os.rename(tmp_p, lpath)
        except Exception:
            pass

    def _extract_p2pool_block_record(blk_obj, share_block_hashes=None):
        if not isinstance(blk_obj, dict):
            return None
        bhash = str(blk_obj.get('hash') or '').strip().lower()
        height = int(blk_obj.get('height') or 0)
        btime = int(blk_obj.get('time') or 0)
        txs = blk_obj.get('tx') or []
        if not txs or not isinstance(txs[0], dict):
            return None
        cb_tx = txs[0]
        vins = cb_tx.get('vin') or []
        cb_hex = ''
        for vin in vins:
            if isinstance(vin, dict) and vin.get('coinbase'):
                cb_hex = str(vin.get('coinbase') or '').lower()
                break
        is_p2pool = any(tag in cb_hex for tag in _P2POOL_CB_HEX_TAGS)
        if (not is_p2pool) and share_block_hashes and bhash in share_block_hashes:
            is_p2pool = True
        if not is_p2pool:
            return None

        payouts = {}
        total_reward = 0.0
        for vout in (cb_tx.get('vout') or []):
            if not isinstance(vout, dict):
                continue
            val = float(vout.get('value') or 0.0)
            if val <= 0.0:
                continue
            spk = vout.get('scriptPubKey') or {}
            spk_type = str(spk.get('type') or '').lower()
            spk_hex = str(spk.get('hex') or '').lower()
            if spk_type == 'nulldata' or spk_hex.startswith('6a'):
                continue
            total_reward += val
            addrs = set()
            a1 = spk.get('address')
            if a1:
                addrs.add(str(a1).strip().lower())
            for a_extra in (spk.get('addresses') or []):
                if a_extra:
                    addrs.add(str(a_extra).strip().lower())
            # Decode P2WPKH 0014<20-byte-hash> directly to scash1... so both Mainnet & Regtest match scash1 wallets!
            if len(spk_hex) == 44 and spk_hex.startswith('0014'):
                try:
                    raw20 = _w_binascii.unhexlify(spk_hex[4:])
                    sc_addr = _w_b32.encode_scash_address(raw20, 'scash')
                    if sc_addr:
                        addrs.add(str(sc_addr).strip().lower())
                except Exception:
                    pass
            for ad in addrs:
                payouts[ad] = round(float(payouts.get(ad, 0.0)) + val, 8)
        return {
            'height': height,
            'hash': bhash,
            'ts': btime,
            'reward': round(total_reward, 8),
            'payouts': payouts,
        }

    def _collect_sharechain_solved_hashes(_wb_ref):
        out = set()
        try:
            _node = getattr(_wb_ref, 'node', None)
            _tracker = getattr(_node, 'tracker', None)
            _best = getattr(getattr(_node, 'best_share_var', None), 'value', None)
            if _best is not None and _tracker is not None and _best in _tracker.items:
                _ch_h = int(_tracker.get_height(_best))
                for _sh in _tracker.get_chain(_best, min(_ch_h, 5760)):
                    if getattr(_sh, 'pow_hash', None) is not None and getattr(_sh, 'header', None) is not None:
                        if _sh.pow_hash <= _sh.header['bits'].target:
                            if getattr(_sh, 'header_hash', None) is not None:
                                out.add('%064x' % int(_sh.header_hash))
        except Exception:
            pass
        return out

    def _scan_height_slice(port, u, pw, heights, share_hashes):
        if not heights:
            return
        hashes = _scashd_rpc_batch(port, u, pw, [ ('getblockhash', [int(h)]) for h in heights ], timeout=8.0)
        valid_pairs = []
        for h, bh in zip(heights, hashes):
            if bh and isinstance(bh, (str, type(u''))):
                valid_pairs.append((int(h), str(bh).strip()))
        if not valid_pairs:
            return
        blocks_raw = _scashd_rpc_batch(port, u, pw, [ ('getblock', [bh, 2]) for _, bh in valid_pairs ], timeout=12.0)
        with _ledger_lock:
            for (h, bh), bobj in zip(valid_pairs, blocks_raw):
                h_key = str(h)
                rec = _extract_p2pool_block_record(bobj, share_hashes)
                if rec is not None:
                    _ledger_state['blocks'][h_key] = rec
                elif h_key in _ledger_state['blocks']:
                    # Remove stale/reorged entry if canonical block at height h is no longer a P2Pool block
                    del _ledger_state['blocks'][h_key]

    def _sync_p2pool_ledger_once(_wb_ref=None, max_backfill_blocks=600):
        with _ledger_lock:
            if _ledger_state['scanning']:
                return False
            _ledger_state['scanning'] = True
        try:
            dd, port, u, pw = _get_rpc_conn_params()
            bc_list = _scashd_rpc_batch(port, u, pw, [('getblockchaininfo', [])], timeout=3.0)
            bc = bc_list[0] if bc_list and isinstance(bc_list[0], dict) else None
            if not bc:
                return False
            tip_h = int(bc.get('blocks') or 0)
            if tip_h <= 0:
                return False
            chain_name = str(bc.get('chain') or 'scash')
            prune_h = int(bc.get('pruneheight') or 0) if bc.get('pruned') else 0
            # Scash P2Pool launched around block #153,000 in Nov 2026; scanning back to 140,000 covers 100% of all-time Mainnet history!
            floor_h = max(1, prune_h, 140000 if (chain_name in ('scash', 'main') and tip_h >= 140000) else 1)

            lpath = _resolve_ledger_path(dd)
            _load_ledger_if_needed(lpath, chain_name)
            share_hashes = _collect_sharechain_solved_hashes(_wb_ref)

            with _ledger_lock:
                min_s = _ledger_state['min_scanned_height']
                max_s = _ledger_state['max_scanned_height']

            dirty = False
            batch_sz = 50

            if max_s is None or min_s is None:
                # Scan newest tip blocks first so recent blocks appear immediately!
                low_start = max(floor_h, tip_h - batch_sz + 1)
                _scan_height_slice(port, u, pw, list(range(low_start, tip_h + 1)), share_hashes)
                with _ledger_lock:
                    _ledger_state['min_scanned_height'] = low_start
                    _ledger_state['max_scanned_height'] = tip_h
                    _ledger_state['last_tip_hash'] = str(bc.get('bestblockhash') or '').strip().lower()
                    min_s = low_start
                    max_s = tip_h
                dirty = True
            else:
                tip_bh = str(bc.get('bestblockhash') or '').strip().lower()
                with _ledger_lock:
                    prev_tip_bh = _ledger_state.get('last_tip_hash') or ''
                # Only re-scan 6-block tail over RPC when Scash chain tip height or bestblockhash actually changed!
                if tip_h != int(max_s) or (tip_bh and tip_bh != prev_tip_bh):
                    fwd_start = max(floor_h, int(max_s) - 6)
                    if tip_h >= fwd_start:
                        cur = fwd_start
                        while cur <= tip_h:
                            top_c = min(tip_h, cur + batch_sz - 1)
                            _scan_height_slice(port, u, pw, list(range(cur, top_c + 1)), share_hashes)
                            with _ledger_lock:
                                if _ledger_state['max_scanned_height'] is None or top_c > _ledger_state['max_scanned_height']:
                                    _ledger_state['max_scanned_height'] = top_c
                            cur = top_c + 1
                            dirty = True
                    with _ledger_lock:
                        _ledger_state['last_tip_hash'] = tip_bh

            # Backfill older history down to floor_h in bounded chunks
            backfilled = 0
            while min_s is not None and int(min_s) > floor_h and backfilled < int(max_backfill_blocks):
                hi_b = int(min_s) - 1
                lo_b = max(floor_h, hi_b - batch_sz + 1)
                _scan_height_slice(port, u, pw, list(range(lo_b, hi_b + 1)), share_hashes)
                with _ledger_lock:
                    _ledger_state['min_scanned_height'] = lo_b
                    min_s = lo_b
                backfilled += (hi_b - lo_b + 1)
                dirty = True
                if backfilled < int(max_backfill_blocks) and lo_b > floor_h:
                    _w_time.sleep(0.015)

            with _ledger_lock:
                _ledger_state['last_scan_ts'] = _w_time.time()
            if dirty:
                _save_ledger_disk()
            return True
        except Exception:
            return False
        finally:
            with _ledger_lock:
                _ledger_state['scanning'] = False

    def _summarize_ledger_stats(wallet_addr=None, now_ts=None):
        t_now = float(now_ts if now_ts is not None else _w_time.time())
        cut_7d = t_now - (7.0 * 86400.0)
        cut_30d = t_now - (30.0 * 86400.0)
        w_clean = ''
        if wallet_addr:
            try:
                from p2pool.bitcoin import data as _bd_strip
                w_clean = str(_bd_strip._strip_scash_worker_suffix(wallet_addr) or '').strip().lower()
            except Exception:
                w_clean = str(wallet_addr).strip().split('.')[0].lower()

        with _ledger_lock:
            recs = list(_ledger_state['blocks'].values())
            min_s = _ledger_state['min_scanned_height']
            max_s = _ledger_state['max_scanned_height']
            is_scanning = bool(_ledger_state['scanning'])

        recs.sort(key=lambda r: int(r.get('height') or 0), reverse=True)
        pool_all = len(recs)
        pool_7d = 0
        pool_30d = 0
        pool_scash_all = 0.0
        miner_7d = 0.0
        miner_30d = 0.0
        miner_all = 0.0
        miner_blocks = 0

        for r in recs:
            bts = float(r.get('ts') or 0.0)
            rew = float(r.get('reward') or 0.0)
            pool_scash_all += rew
            if bts >= cut_30d:
                pool_30d += 1
            if bts >= cut_7d:
                pool_7d += 1
            if w_clean:
                pmap = r.get('payouts') or {}
                m_amt = float(pmap.get(w_clean) or 0.0)
                if m_amt > 0.0:
                    miner_all += m_amt
                    miner_blocks += 1
                    if bts >= cut_30d:
                        miner_30d += m_amt
                    if bts >= cut_7d:
                        miner_7d += m_amt

        last_blk = recs[0] if recs else None
        recent_list = [
            {
                'number': int(r.get('height') or 0),
                'hash': str(r.get('hash') or ''),
                'ts': int(r.get('ts') or 0),
                'reward': round(float(r.get('reward') or 0.0), 8),
            }
            for r in recs[:25]
        ]
        return {
            'wallet': w_clean,
            'miner_scash_7d': round(miner_7d, 8),
            'miner_scash_30d': round(miner_30d, 8),
            'miner_scash_all_time': round(miner_all, 8),
            'miner_blocks_paid': int(miner_blocks),
            'pool_blocks_7d': int(pool_7d),
            'pool_blocks_30d': int(pool_30d),
            'pool_blocks_all_time': int(pool_all),
            'pool_scash_all_time': round(pool_scash_all, 8),
            'last_block_height': int(last_blk['height']) if last_blk else None,
            'last_block_hash': str(last_blk['hash']) if last_blk else None,
            'last_block_ts': int(last_blk['ts']) if last_blk else None,
            'min_scanned_height': min_s,
            'max_scanned_height': max_s,
            'backfill_scanning': is_scanning,
            'recent_blocks': recent_list,
        }

    # --- Liquidity-Weighted Multi-Exchange SCASH Price Tracker (Ourbit + NonKYC + NestEx + Auto-Discovered Venues) ---
    _CANONICAL_EXCHANGES = {
        'ourbit': {
            'key': 'ourbit',
            'name': 'Ourbit',
            'pair': 'SCASH/USDT',
            'url': 'https://www.ourbit.com/exchange/SCASH_USDT',
        },
        'nonkyc': {
            'key': 'nonkyc',
            'name': 'NonKYC',
            'pair': 'SCASH/USDT',
            'url': 'https://nonkyc.io/market/SCASH_USDT',
        },
        'nestex': {
            'key': 'nestex',
            'name': 'NestEx',
            'pair': 'SCASH/USDT',
            'url': 'https://trade.nestex.one/spot/SCASH',
        },
    }
    _REFERENCE_MARKET_LINKS = [
        {'name': 'Ourbit', 'url': 'https://www.ourbit.com/exchange/SCASH_USDT'},
        {'name': 'NonKYC', 'url': 'https://nonkyc.io/market/SCASH_USDT'},
        {'name': 'NestEx', 'url': 'https://trade.nestex.one/spot/SCASH'},
        {'name': 'CoinGecko', 'url': 'https://www.coingecko.com/en/coins/satoshi-cash-network'},
    ]
    _market_lock = _w_threading.Lock()
    _market_cache = {
        'ts': 0.0,
        'refreshing': False,
        'data': {
            'ok': False,
            'weighted_price_usd': None,
            'block_value_usd': None,
            'total_liquidity_usd': 0.0,
            'total_volume_24h_usd': 0.0,
            'exchanges': [
                {'key': 'ourbit', 'name': 'Ourbit', 'pair': 'SCASH/USDT', 'price_usd': None, 'depth_usd': 0.0, 'volume_24h_usd': 0.0, 'liquidity_usd': 0.0, 'weight_pct': 0.0, 'url': 'https://www.ourbit.com/exchange/SCASH_USDT'},
                {'key': 'nonkyc', 'name': 'NonKYC', 'pair': 'SCASH/USDT', 'price_usd': None, 'depth_usd': 0.0, 'volume_24h_usd': 0.0, 'liquidity_usd': 0.0, 'weight_pct': 0.0, 'url': 'https://nonkyc.io/market/SCASH_USDT'},
                {'key': 'nestex', 'name': 'NestEx', 'pair': 'SCASH/USDT', 'price_usd': None, 'depth_usd': 0.0, 'volume_24h_usd': 0.0, 'liquidity_usd': 0.0, 'weight_pct': 0.0, 'url': 'https://trade.nestex.one/spot/SCASH'},
            ],
            'reference_links': _REFERENCE_MARKET_LINKS,
            'updated_at': 0,
        },
    }

    def _http_get_json_wan(url, timeout=4.5):
        req = _w_ureq.Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
        })
        raw = _scash_open_url(req, timeout=timeout, is_local=url.startswith('http://127.0.0.1'))
        return _w_json.loads(raw.decode('utf-8', 'replace'))

    def _calc_orderbook_band_usd(bids, asks, ref_price):
        if ref_price <= 0:
            return 0.0
        lo = ref_price * 0.90
        hi = ref_price * 1.10
        band_usd = 0.0
        full_usd = 0.0
        for raw_side, is_bid in ((bids, True), (asks, False)):
            if isinstance(raw_side, dict):
                side_rows = list(raw_side.items())
            elif isinstance(raw_side, (list, tuple)):
                side_rows = list(raw_side)
            else:
                side_rows = []
            for row in side_rows[:80]:
                try:
                    if isinstance(row, dict):
                        p = float(row.get('price') or row.get('rate') or 0.0)
                        q = float(row.get('quantity') or row.get('amount') or row.get('volume') or 0.0)
                    elif isinstance(row, (list, tuple)) and len(row) >= 2:
                        p = float(row[0] or 0.0)
                        q = float(row[1] or 0.0)
                    else:
                        continue
                    if p <= 0 or q <= 0:
                        continue
                    notional = p * q
                    # Guard against extreme spoof orders (> 5x or < 0.2x mid price)
                    if 0.2 * ref_price <= p <= 5.0 * ref_price:
                        full_usd += notional
                    if (is_bid and p >= lo and p <= ref_price * 1.05) or ((not is_bid) and p <= hi and p >= ref_price * 0.95):
                        band_usd += notional
                except Exception:
                    pass
        return band_usd if band_usd > 0 else min(full_usd, 25000.0)

    def _norm_exchange_key(raw_id, raw_name):
        s = ('%s %s' % (raw_id or '', raw_name or '')).strip().lower()
        if 'ourbit' in s:
            return 'ourbit'
        if 'nonkyc' in s or 'non-kyc' in s:
            return 'nonkyc'
        if 'nestex' in s:
            return 'nestex'
        clean = ''.join(ch if ch.isalnum() else '_' for ch in _w_str(raw_id or raw_name or 'exchange').lower()).strip('_')
        return clean or 'exchange'

    def _compute_weighted_market_snapshot(raw_venues, block_reward=50.0, now_ep=None):
        t_ep = int(now_ep if now_ep is not None else _w_time.time())
        active = []
        for k, v in raw_venues.items():
            price = float(v.get('price_usd') or 0.0)
            depth = max(0.0, float(v.get('depth_usd') or 0.0))
            vol = max(0.0, float(v.get('volume_24h_usd') or 0.0))
            if v.get('is_stale') or v.get('is_anomaly'):
                continue
            if price <= 0.0 or (depth < 1.0 and vol < 1.0):
                continue
            # Effective USD liquidity combines active +-10% orderbook / AMM LP depth with 24h USD turnover
            liq = depth + (0.25 * vol)
            if liq <= 0.0:
                continue
            item = {
                'key': k,
                'name': v.get('name') or k.capitalize(),
                'pair': v.get('pair') or 'SCASH/USDT',
                'price_usd': round(price, 6),
                'depth_usd': round(depth, 2),
                'volume_24h_usd': round(vol, 2),
                'liquidity_usd': round(liq, 2),
                'weight_pct': 0.0,
                'url': v.get('url') or '',
            }
            active.append(item)

        tot_liq = sum(x['liquidity_usd'] for x in active)
        tot_vol = sum(x['volume_24h_usd'] for x in active)
        w_price = None
        if tot_liq > 0.0 and active:
            w_price = sum(x['price_usd'] * x['liquidity_usd'] for x in active) / tot_liq
            for x in active:
                x['weight_pct'] = round(100.0 * x['liquidity_usd'] / tot_liq, 1)
        active.sort(key=lambda x: x['liquidity_usd'], reverse=True)

        # Always keep Ourbit, NonKYC & NestEx hyperlinks present even if one API is temporarily unreachable
        present_keys = set(x['key'] for x in active)
        for req_k in ('ourbit', 'nonkyc', 'nestex'):
            if req_k not in present_keys:
                meta = _CANONICAL_EXCHANGES[req_k]
                active.append({
                    'key': req_k,
                    'name': meta['name'],
                    'pair': meta['pair'],
                    'price_usd': None,
                    'depth_usd': 0.0,
                    'volume_24h_usd': 0.0,
                    'liquidity_usd': 0.0,
                    'weight_pct': 0.0,
                    'url': meta['url'],
                })

        return {
            'ok': bool(w_price is not None and w_price > 0),
            'weighted_price_usd': round(w_price, 6) if w_price is not None else None,
            'block_value_usd': round(w_price * float(block_reward or 50.0), 4) if w_price is not None else None,
            'total_liquidity_usd': round(tot_liq, 2),
            'total_volume_24h_usd': round(tot_vol, 2),
            'exchanges': active,
            'reference_links': _REFERENCE_MARKET_LINKS,
            'updated_at': t_ep,
        }

    def _refresh_scash_market_once():
        if os.environ.get('SCASH_CI_ISOLATED_MESH') == '1' and not os.environ.get('SCASH_MARKET_TEST_URLS'):
            return _market_cache['data']
        with _market_lock:
            if _market_cache['refreshing']:
                return _market_cache['data']
            _market_cache['refreshing'] = True
        try:
            venues = {}
            ourbit_base = (os.environ.get('SCASH_OURBIT_API_BASE') or 'https://www.ourbit.com').rstrip('/')
            nonkyc_base = (os.environ.get('SCASH_NONKYC_API_BASE') or 'https://api.nonkyc.io/api/v2').rstrip('/')
            nestex_base = (os.environ.get('SCASH_NESTEX_API_BASE') or 'https://api.nestex.one').rstrip('/')
            cg_url = os.environ.get('SCASH_COINGECKO_TICKERS_URL') or 'https://api.coingecko.com/api/v3/coins/satoshi-cash-network/tickers?depth=true'
            cp_url = os.environ.get('SCASH_COINPAPRIKA_MARKETS_URL') or 'https://api.coinpaprika.com/v1/coins/scash-satoshi-cash-network/markets?quotes=USD'

            # 1) Direct Ourbit public REST v2 ticker + orderbook depth
            try:
                ob_tk = _http_get_json_wan('%s/open/api/v2/market/ticker?symbol=SCASH_USDT' % ourbit_base, timeout=4.0)
                ob_rows = (ob_tk or {}).get('data') or []
                if isinstance(ob_rows, list) and ob_rows:
                    r0 = ob_rows[0] or {}
                    p_ob = float(r0.get('last') or 0.0)
                    vol_quote = float(r0.get('amount') or 0.0)
                    if vol_quote <= 0.0 and p_ob > 0.0:
                        vol_quote = float(r0.get('volume') or 0.0) * p_ob
                    d_ob = 0.0
                    if p_ob > 0.0:
                        try:
                            ob_dp = _http_get_json_wan('%s/open/api/v2/market/depth?symbol=SCASH_USDT&depth=50' % ourbit_base, timeout=4.0)
                            dp_d = (ob_dp or {}).get('data') or {}
                            d_ob = _calc_orderbook_band_usd(dp_d.get('bids'), dp_d.get('asks'), p_ob)
                        except Exception:
                            pass
                    if p_ob > 0.0:
                        venues['ourbit'] = {
                            'name': 'Ourbit',
                            'pair': 'SCASH/USDT',
                            'price_usd': p_ob,
                            'depth_usd': d_ob,
                            'volume_24h_usd': vol_quote,
                            'url': _CANONICAL_EXCHANGES['ourbit']['url'],
                        }
            except Exception:
                pass

            # 2) Direct NonKYC public REST v2 ticker + orderbook depth
            #    IMPORTANT: On NonKYC /market/getbysymbol/SCASH_USDT, 'volume' is BASE SCASH coins (NOT USD)!
            #    Always read CoinGecko-spec 'target_volume' / explicit 'usdVolume' / 'volumeUsd', or multiply base 'volume' by p_nk!
            try:
                p_nk = 0.0
                vol_nk = 0.0
                try:
                    nk_cg = _http_get_json_wan('%s/ticker/SCASH_USDT' % nonkyc_base, timeout=3.5)
                    if isinstance(nk_cg, dict):
                        p_nk = float(nk_cg.get('last_price') or nk_cg.get('lastPrice') or 0.0)
                        if nk_cg.get('target_volume') is not None:
                            vol_nk = float(nk_cg.get('target_volume') or 0.0)
                        elif nk_cg.get('base_volume') is not None and p_nk > 0.0:
                            vol_nk = float(nk_cg.get('base_volume') or 0.0) * p_nk
                except Exception:
                    pass
                if p_nk <= 0.0 or vol_nk <= 0.0:
                    nk_tk = _http_get_json_wan('%s/market/getbysymbol/SCASH_USDT' % nonkyc_base, timeout=4.0)
                    if isinstance(nk_tk, dict):
                        if p_nk <= 0.0:
                            p_nk = float(nk_tk.get('lastPrice') or nk_tk.get('last_price') or nk_tk.get('last') or 0.0)
                        if vol_nk <= 0.0:
                            explicit_usd = nk_tk.get('usdVolume') if nk_tk.get('usdVolume') is not None else nk_tk.get('volumeUsd')
                            if explicit_usd is not None and float(explicit_usd or 0.0) > 0.0:
                                vol_nk = float(explicit_usd)
                            elif nk_tk.get('target_volume') is not None and float(nk_tk.get('target_volume') or 0.0) > 0.0:
                                vol_nk = float(nk_tk.get('target_volume'))
                            elif p_nk > 0.0:
                                # 'volume' on NonKYC getbysymbol is in base SCASH coins -> convert to USD!
                                vol_nk = float(nk_tk.get('volume') or 0.0) * p_nk
                d_nk = 0.0
                if p_nk > 0.0:
                    try:
                        nk_dp = _http_get_json_wan('%s/market/getorderbookbysymbol/SCASH_USDT' % nonkyc_base, timeout=4.0)
                        if isinstance(nk_dp, dict):
                            d_nk = _calc_orderbook_band_usd(nk_dp.get('bids'), nk_dp.get('asks'), p_nk)
                    except Exception:
                        pass
                if p_nk > 0.0:
                    venues['nonkyc'] = {
                        'name': 'NonKYC',
                        'pair': 'SCASH/USDT',
                        'price_usd': p_nk,
                        'depth_usd': d_nk,
                        'volume_24h_usd': vol_nk,
                        'url': _CANONICAL_EXCHANGES['nonkyc']['url'],
                    }
            except Exception:
                pass

            # 3) Direct NestEx public REST API v1.31 (/cg/tickers/SCASH_USDT + /cg/orderbook/SCASH_USDT + /v1/liquidity/SCASH)
            try:
                nx_tk = None
                try:
                    nx_single = _http_get_json_wan('%s/cg/tickers/SCASH_USDT' % nestex_base, timeout=4.0)
                    if isinstance(nx_single, dict) and (nx_single.get('last_price') or nx_single.get('bid') or nx_single.get('ask')):
                        nx_tk = nx_single
                    elif isinstance(nx_single, list):
                        for row in nx_single:
                            if isinstance(row, dict) and str(row.get('ticker_id') or '').upper() == 'SCASH_USDT':
                                nx_tk = row
                                break
                except Exception:
                    pass
                if nx_tk is None:
                    nx_all = _http_get_json_wan('%s/cg/tickers' % nestex_base, timeout=4.5)
                    if isinstance(nx_all, list):
                        for row in nx_all:
                            if not isinstance(row, dict):
                                continue
                            tid = str(row.get('ticker_id') or '').upper()
                            bcur = str(row.get('base_currency') or '').upper()
                            tcur = str(row.get('target_currency') or '').upper()
                            if tid == 'SCASH_USDT' or (bcur == 'SCASH' and tcur in ('USDT', 'USD', 'USDC')):
                                nx_tk = row
                                break
                if isinstance(nx_tk, dict):
                    p_nx = float(nx_tk.get('last_price') or nx_tk.get('last') or 0.0)
                    if p_nx <= 0.0:
                        b_nx = float(nx_tk.get('bid') or 0.0)
                        a_nx = float(nx_tk.get('ask') or 0.0)
                        if b_nx > 0.0 and a_nx > 0.0:
                            p_nx = 0.5 * (b_nx + a_nx)
                    # Per NestEx API v1.31, target_volume is 24h volume in USDT, base_volume is in SCASH
                    vol_nx = float(nx_tk.get('target_volume') or 0.0)
                    if vol_nx <= 0.0 and p_nx > 0.0:
                        vol_nx = float(nx_tk.get('base_volume') or 0.0) * p_nx
                    liq_rec_nx = float(nx_tk.get('liquidity') or 0.0)
                    d_nx = 0.0
                    if p_nx > 0.0:
                        try:
                            nx_dp = _http_get_json_wan('%s/cg/orderbook/SCASH_USDT?depth=100' % nestex_base, timeout=4.0)
                            if isinstance(nx_dp, dict):
                                d_nx = _calc_orderbook_band_usd(nx_dp.get('bids'), nx_dp.get('asks'), p_nx)
                        except Exception:
                            pass
                        try:
                            nx_lp = _http_get_json_wan('%s/v1/liquidity/SCASH' % nestex_base, timeout=3.5)
                            lp_d = (nx_lp or {}).get('data') or {}
                            if isinstance(lp_d, dict):
                                lp_tot = float(lp_d.get('total') or 0.0)
                                if lp_tot > 0.0:
                                    d_nx += lp_tot
                        except Exception:
                            pass
                    if d_nx <= 0.0 and liq_rec_nx > 0.0:
                        d_nx = liq_rec_nx
                    if p_nx > 0.0:
                        venues['nestex'] = {
                            'name': 'NestEx',
                            'pair': 'SCASH/USDT',
                            'price_usd': p_nx,
                            'depth_usd': d_nx,
                            'volume_24h_usd': vol_nx,
                            'url': _CANONICAL_EXCHANGES['nestex']['url'],
                        }
            except Exception:
                pass

            # 4) CoinGecko multi-exchange tickers (?depth=true) -> auto-discovers ANY new SCASH exchange + cross-checks USD volumes!
            try:
                cg_obj = _http_get_json_wan(cg_url, timeout=5.0)
                for tk in ((cg_obj or {}).get('tickers') or []):
                    if not isinstance(tk, dict):
                        continue
                    if tk.get('is_stale') or tk.get('is_anomaly'):
                        continue
                    mkt = tk.get('market') or {}
                    m_name = _w_str(mkt.get('name') or '').strip()
                    m_id = _w_str(mkt.get('identifier') or '').strip()
                    ekey = _norm_exchange_key(m_id, m_name)
                    p_usd = float((tk.get('converted_last') or {}).get('usd') or 0.0)
                    v_usd = float((tk.get('converted_volume') or {}).get('usd') or 0.0)
                    cg_d = float(tk.get('cost_to_move_up_usd') or 0.0) + float(tk.get('cost_to_move_down_usd') or 0.0)
                    if p_usd <= 0.0 or (v_usd < 1.0 and cg_d < 1.0):
                        continue
                    pair_str = '%s/%s' % (str(tk.get('base') or 'SCASH').upper(), str(tk.get('target') or 'USDT').upper())
                    t_url = str(tk.get('trade_url') or '').strip()
                    if ekey in _CANONICAL_EXCHANGES and not t_url:
                        t_url = _CANONICAL_EXCHANGES[ekey]['url']
                    elif ekey in _CANONICAL_EXCHANGES:
                        m_name = _CANONICAL_EXCHANGES[ekey]['name']
                    if ekey in venues:
                        cur = venues[ekey]
                        cur_v = float(cur.get('volume_24h_usd') or 0.0)
                        # Guard against base-coin vs USD volume unit mismatch (>4x CoinGecko's verified converted_volume.usd)
                        if (cur_v <= 0.0 and v_usd > 0.0) or (v_usd > 0.0 and cur_v > 4.0 * v_usd):
                            cur['volume_24h_usd'] = v_usd
                        if float(cur.get('depth_usd') or 0.0) <= 0.0 and cg_d > 0.0:
                            cur['depth_usd'] = cg_d
                        if t_url and not cur.get('url'):
                            cur['url'] = t_url
                    else:
                        venues[ekey] = {
                            'name': m_name or ekey.capitalize(),
                            'pair': pair_str,
                            'price_usd': p_usd,
                            'depth_usd': cg_d,
                            'volume_24h_usd': v_usd,
                            'url': t_url or 'https://www.coingecko.com/en/coins/satoshi-cash-network',
                        }
            except Exception:
                pass

            # 5) CoinPaprika multi-market feed (runs every cycle too so exchanges indexed on CoinPaprika but not CoinGecko are included!)
            try:
                cp_arr = _http_get_json_wan(cp_url, timeout=4.5)
                if isinstance(cp_arr, list):
                    for mk in cp_arr:
                        if not isinstance(mk, dict) or mk.get('outlier'):
                            continue
                        q_usd = ((mk.get('quotes') or {}).get('USD')) or {}
                        p_cp = float(q_usd.get('price') or 0.0)
                        v_cp = float(q_usd.get('volume_24h') or 0.0)
                        if p_cp <= 0.0 or v_cp < 1.0:
                            continue
                        ex_nm = _w_str(mk.get('exchange_name') or '').strip()
                        ekey = _norm_exchange_key(mk.get('exchange_id'), ex_nm)
                        if ekey not in venues:
                            venues[ekey] = {
                                'name': _CANONICAL_EXCHANGES[ekey]['name'] if ekey in _CANONICAL_EXCHANGES else (ex_nm or ekey.capitalize()),
                                'pair': str(mk.get('pair') or 'SCASH/USDT'),
                                'price_usd': p_cp,
                                'depth_usd': 0.0,
                                'volume_24h_usd': v_cp,
                                'url': str(mk.get('market_url') or (_CANONICAL_EXCHANGES.get(ekey) or {}).get('url') or 'https://www.coingecko.com/en/coins/satoshi-cash-network'),
                            }
            except Exception:
                pass

            if venues:
                snap = _compute_weighted_market_snapshot(venues, block_reward=50.0)
                with _market_lock:
                    _market_cache['data'] = snap
                    _market_cache['ts'] = _w_time.time()
            else:
                with _market_lock:
                    _market_cache['ts'] = _w_time.time() - 40.0
        finally:
            with _market_lock:
                _market_cache['refreshing'] = False
        return _market_cache['data']

    def _get_cached_scash_market():
        now_t = _w_time.time()
        with _market_lock:
            age = now_t - float(_market_cache['ts'] or 0.0)
            busy = bool(_market_cache['refreshing'])
            cur = _market_cache['data']
        if age >= 60.0 and not busy:
            _mt = _w_threading.Thread(target=_refresh_scash_market_once)
            _mt.daemon = True
            _mt.start()
        return cur

    # --- Multi-Explorer Health Cycling & Automatic Failover (v0.4.0) ---
    def _get_scash_explorer_defs():
        e1_base = 'https://explorer.scash.network'
        e2_base = 'https://scash.tv'
        if os.environ.get('SCASH_EXPLORER_TEST_URLS') == '1':
            e1_base = (os.environ.get('SCASH_EXPLORER_1_BASE') or e1_base).rstrip('/')
            e2_base = (os.environ.get('SCASH_EXPLORER_2_BASE') or e2_base).rstrip('/')
        return [
            {
                'key': 'scash_network',
                'name': 'explorer.scash.network',
                'short': 'scash.network',
                'home_url': e1_base + '/',
                'probe_url': e1_base + '/',
                'block_tpl': e1_base + '/block/{id}/20/1',
                'address_tpl': e1_base + '/address/{id}/20/1',
                'is_public': True,
            },
            {
                'key': 'scash_tv',
                'name': 'scash.tv',
                'short': 'scash.tv',
                'home_url': e2_base + '/',
                'probe_url': e2_base + '/',
                'block_tpl': e2_base + '/block/{id}',
                'address_tpl': e2_base + '/address/{id}',
                'is_public': True,
            },
            {
                'key': 'local_node',
                'name': 'Local Scash Node',
                'short': 'Local Coinbase',
                'home_url': '/local_explorer',
                'probe_url': '',
                'block_tpl': '/local_explorer?block={id}',
                'address_tpl': '/local_explorer?address={id}',
                'is_public': False,
            },
        ]

    _explorer_lock = _w_threading.Lock()
    _explorer_cache = {
        'ts': 0.0,
        'probing': False,
        'data': None,
    }

    def _build_default_explorer_snapshot():
        defs = _get_scash_explorer_defs()
        items = []
        for d in defs:
            items.append({
                'key': d['key'],
                'name': d['name'],
                'short': d['short'],
                'home_url': d['home_url'],
                'block_tpl': d['block_tpl'],
                'address_tpl': d['address_tpl'],
                'online': True if not d['is_public'] else None,
            })
        return {
            'active_key': defs[0]['key'],
            'active_name': defs[0]['name'],
            'active_url': defs[0]['home_url'],
            'checked_at': 0,
            'items': items,
        }

    def _check_single_explorer_url(probe_url, timeout=3.2):
        if not probe_url:
            return True
        try:
            req = _w_ureq.Request(probe_url, headers={
                'Accept': 'text/html,application/json,*/*;q=0.8',
                'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
            })
            raw = _scash_open_url(req, timeout=timeout, is_local=probe_url.startswith('http://127.0.0.1'))
            if not raw or len(raw) < 16:
                return False
            sample = raw[:4096].decode('utf-8', 'replace').lower()
            for bad_sig in ('502 bad gateway', '503 service temporarily unavailable', '504 gateway time-out', 'error code 52', 'origin is unreachable'):
                if bad_sig in sample:
                    return False
            return True
        except Exception:
            return False

    def _probe_scash_explorers_once(timeout=3.2):
        if os.environ.get('SCASH_CI_ISOLATED_MESH') == '1' and os.environ.get('SCASH_EXPLORER_TEST_URLS') != '1':
            snap = _build_default_explorer_snapshot()
            with _explorer_lock:
                _explorer_cache['data'] = snap
                _explorer_cache['ts'] = _w_time.time()
            return snap
        with _explorer_lock:
            if _explorer_cache['probing'] and _explorer_cache['data'] is not None:
                return _explorer_cache['data']
            _explorer_cache['probing'] = True
        try:
            defs = _get_scash_explorer_defs()
            items = []
            chosen = None
            for d in defs:
                ok = True if not d['is_public'] else _check_single_explorer_url(d['probe_url'], timeout=timeout)
                entry = {
                    'key': d['key'],
                    'name': d['name'],
                    'short': d['short'],
                    'home_url': d['home_url'],
                    'block_tpl': d['block_tpl'],
                    'address_tpl': d['address_tpl'],
                    'online': bool(ok),
                }
                items.append(entry)
                if ok and chosen is None:
                    chosen = entry
            if chosen is None:
                chosen = items[-1]
            snap = {
                'active_key': chosen['key'],
                'active_name': chosen['name'],
                'active_url': chosen['home_url'],
                'checked_at': int(_w_time.time()),
                'items': items,
            }
            with _explorer_lock:
                _explorer_cache['data'] = snap
                _explorer_cache['ts'] = _w_time.time()
            return snap
        finally:
            with _explorer_lock:
                _explorer_cache['probing'] = False

    def _get_cached_explorers():
        now_t = _w_time.time()
        with _explorer_lock:
            cur = _explorer_cache['data']
            age = now_t - float(_explorer_cache['ts'] or 0.0)
            busy = bool(_explorer_cache['probing'])
        if cur is None:
            cur = _build_default_explorer_snapshot()
        if age >= 90.0 and not busy:
            _et = _w_threading.Thread(target=_probe_scash_explorers_once)
            _et.daemon = True
            _et.start()
        return cur

    def _html_esc(val):
        s = _w_str(val if val is not None else '')
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

    def _resolve_block_hash_and_obj(raw_block_id):
        bid = str(raw_block_id or '').strip().lower()
        if not bid:
            return '', None
        bhash = ''
        bobj = None
        if len(bid) < 64 and bid.isdigit():
            h_int = int(bid)
            with _ledger_lock:
                rec = _ledger_state['blocks'].get(str(h_int))
                if rec and rec.get('hash'):
                    bhash = str(rec.get('hash')).strip().lower()
            try:
                _, port, u, pw = _get_rpc_conn_params()
                if not bhash:
                    r_h = _scashd_rpc_batch(port, u, pw, [('getblockhash', [h_int])], timeout=3.0)
                    if r_h and isinstance(r_h[0], (str, type(u''))):
                        bhash = str(r_h[0]).strip().lower()
                if bhash:
                    r_b = _scashd_rpc_batch(port, u, pw, [('getblock', [bhash, 2])], timeout=4.0)
                    if r_b and isinstance(r_b[0], dict):
                        bobj = r_b[0]
            except Exception:
                pass
        else:
            clean_hex = ''.join(ch for ch in bid if ch in '0123456789abcdef')
            if len(clean_hex) == 64:
                bhash = clean_hex
                try:
                    _, port, u, pw = _get_rpc_conn_params()
                    r_b = _scashd_rpc_batch(port, u, pw, [('getblock', [bhash, 2])], timeout=4.0)
                    if r_b and isinstance(r_b[0], dict):
                        bobj = r_b[0]
                except Exception:
                    pass
        return bhash, bobj

    def _cycle_and_pick_explorer_url(kind, raw_target, prefer_key=''):
        k_norm = 'address' if str(kind or '').strip().lower() == 'address' else 'block'
        raw_s = str(raw_target or '').strip()
        if k_norm == 'address':
            try:
                from p2pool.bitcoin import data as _bd_ex
                clean_id = str(_bd_ex._strip_scash_worker_suffix(raw_s) or '').strip()
            except Exception:
                clean_id = raw_s.split('.')[0].strip()
        else:
            bhash, _ = _resolve_block_hash_and_obj(raw_s)
            clean_id = bhash if bhash else raw_s

        if not clean_id:
            snap = _probe_scash_explorers_once(timeout=2.5)
            return snap.get('active_url') or '/local_explorer'

        defs = _get_scash_explorer_defs()
        if prefer_key:
            for d in defs:
                if d['key'] == prefer_key:
                    tpl = d['address_tpl'] if k_norm == 'address' else d['block_tpl']
                    if d['is_public'] and k_norm == 'block' and len(clean_id) != 64:
                        break
                    return tpl.replace('{id}', clean_id)

        # If a public block explorer requires a 64-hex block hash and we only have an unresolved height, use local_explorer
        if k_norm == 'block' and len(clean_id) != 64:
            return '/local_explorer?block=' + clean_id

        now_t = _w_time.time()
        with _explorer_lock:
            cached = _explorer_cache['data']
            cache_age = now_t - float(_explorer_cache['ts'] or 0.0)

        if cached is not None and cache_age <= 45.0 and cached.get('checked_at'):
            for it in (cached.get('items') or []):
                if it.get('online'):
                    tpl = it.get('address_tpl') if k_norm == 'address' else it.get('block_tpl')
                    if tpl:
                        return str(tpl).replace('{id}', clean_id)

        snap = _probe_scash_explorers_once(timeout=2.5)
        for it in (snap.get('items') or []):
            if it.get('online'):
                tpl = it.get('address_tpl') if k_norm == 'address' else it.get('block_tpl')
                if tpl:
                    return str(tpl).replace('{id}', clean_id)
        return ('/local_explorer?address=' + clean_id) if k_norm == 'address' else ('/local_explorer?block=' + clean_id)

    def _decode_vout_scash_address(vout):
        if not isinstance(vout, dict):
            return ''
        spk = vout.get('scriptPubKey') or {}
        a1 = spk.get('address')
        if a1:
            return str(a1).strip().lower()
        for ax in (spk.get('addresses') or []):
            if ax:
                return str(ax).strip().lower()
        spk_hex = str(spk.get('hex') or '').lower()
        if len(spk_hex) == 44 and spk_hex.startswith('0014'):
            try:
                return str(_w_b32.encode_scash_address(_w_binascii.unhexlify(spk_hex[4:]), 'scash') or '').strip().lower()
            except Exception:
                pass
        return ''

    def _render_local_explorer_html(_wb_ref, block_q='', addr_q=''):
        defs = _get_scash_explorer_defs()
        e1_blk = defs[0]['block_tpl']
        e2_blk = defs[1]['block_tpl']
        e1_adr = defs[0]['address_tpl']
        e2_adr = defs[1]['address_tpl']
        parts = [
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>Scash P2Pool v0.4.0 — Local Full-Node Block &amp; Payout Explorer</title>',
            '<style>',
            'body{background:#120b1e;color:#f3ecff;font-family:Inter,system-ui,-apple-system,sans-serif;max-width:920px;margin:28px auto;padding:0 16px;line-height:1.55}',
            '.card{background:#1b112c;border:1px solid rgba(77,238,234,0.45);border-radius:14px;padding:18px 20px;margin-bottom:16px;box-shadow:0 10px 28px rgba(0,0,0,0.4)}',
            'h1{font-size:18px;margin:0 0 6px;color:#4deeea}h2{font-size:14px;margin:0 0 10px;color:#ffd166;text-transform:uppercase;letter-spacing:0.04em}',
            'code,.mono{font-family:JetBrains Mono,Consolas,monospace;font-size:12px}',
            'a{color:#4deeea;text-decoration:none}a:hover{text-decoration:underline}',
            'table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}th,td{padding:8px 10px;border-bottom:1px solid rgba(168,85,247,0.22);text-align:left}',
            'th{color:#d8b4fe;background:#24163b}.amt{color:#34d399;font-weight:700;text-align:right}.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;border:1px solid rgba(77,238,234,0.5);background:#140b23;margin-right:6px}',
            '</style></head><body>',
            '<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">',
            '<div><h1>Scash P2Pool (v0.4.0) &mdash; Local Scash Core 30.4 Coinbase &amp; Payout Inspector</h1>',
            '<div style="font-size:12px;color:#c4b5fd">100% trustless verification directly from your local <code>scashd</code> blockchain &amp; P2Pool ledger (built-in fallback when external web explorers are unreachable).</div></div>',
            '<a class="pill" href="/static/">&larr; Back to Dashboard</a></div></div>',
        ]
        if block_q:
            bhash, bobj = _resolve_block_hash_and_obj(block_q)
            parts.append('<div class="card"><h2>On-Chain Block Inspection</h2>')
            if bobj and isinstance(bobj, dict):
                bh_s = _html_esc(bobj.get('hash') or bhash)
                ht_i = int(bobj.get('height') or 0)
                ts_i = int(bobj.get('time') or 0)
                iso_t = _w_time.strftime('%Y-%m-%d %H:%M:%S UTC', _w_time.gmtime(ts_i)) if ts_i > 0 else '—'
                conf_i = int(bobj.get('confirmations') or 0)
                txs = bobj.get('tx') or []
                cb_tx = txs[0] if (txs and isinstance(txs[0], dict)) else {}
                parts.append('<div class="mono" style="font-size:12px;margin-bottom:10px">')
                parts.append('<div><strong>Block Height:</strong> #%d (%d confirmations)</div>' % (ht_i, conf_i))
                parts.append('<div><strong>Block Hash:</strong> %s</div>' % bh_s)
                parts.append('<div><strong>Timestamp:</strong> %s</div>' % _html_esc(iso_t))
                parts.append('<div style="margin-top:8px"><strong>External Explorers:</strong> ')
                parts.append('<a class="pill" target="_blank" rel="noopener" href="%s">explorer.scash.network &#8599;</a>' % _html_esc(e1_blk.replace('{id}', str(bobj.get('hash') or bhash))))
                parts.append('<a class="pill" target="_blank" rel="noopener" href="%s">scash.tv &#8599;</a></div></div>' % _html_esc(e2_blk.replace('{id}', str(bobj.get('hash') or bhash))))
                parts.append('<h2>Coinbase Transaction (tx[0]) Direct Miner Payouts</h2>')
                parts.append('<table><thead><tr><th>#</th><th>Recipient Wallet (scash1...)</th><th style="text-align:right">Payout (SCASH)</th></tr></thead><tbody>')
                for idx, vo in enumerate(cb_tx.get('vout') or []):
                    if not isinstance(vo, dict):
                        continue
                    val = float(vo.get('value') or 0.0)
                    spk = vo.get('scriptPubKey') or {}
                    ad = _decode_vout_scash_address(vo)
                    if val <= 0.0 and str(spk.get('type') or '') == 'nulldata':
                        continue
                    ad_cell = ('<a class="mono" href="/local_explorer?address=%s">%s</a>' % (_html_esc(ad), _html_esc(ad))) if ad else ('<span class="mono" style="color:#a78bfa">%s</span>' % _html_esc(spk.get('type') or 'script'))
                    parts.append('<tr><td class="mono">%d</td><td>%s</td><td class="mono amt">%.8f SCASH</td></tr>' % (idx, ad_cell, val))
                parts.append('</tbody></table>')
            else:
                parts.append('<div class="mono">Block <strong>%s</strong> not found in local scashd yet (node may still be syncing).</div>' % _html_esc(block_q))
                if len(bhash) == 64:
                    parts.append('<div style="margin-top:8px"><a class="pill" target="_blank" rel="noopener" href="%s">Open on explorer.scash.network &#8599;</a><a class="pill" target="_blank" rel="noopener" href="%s">Open on scash.tv &#8599;</a></div>' % (_html_esc(e1_blk.replace('{id}', bhash)), _html_esc(e2_blk.replace('{id}', bhash))))
            parts.append('</div>')

        if addr_q:
            try:
                from p2pool.bitcoin import data as _bd_loc
                clean_a = str(_bd_loc._strip_scash_worker_suffix(addr_q) or '').strip().lower()
            except Exception:
                clean_a = str(addr_q).strip().split('.')[0].lower()
            lg_a = _summarize_ledger_stats(wallet_addr=clean_a)
            with _ledger_lock:
                all_recs = sorted(list(_ledger_state['blocks'].values()), key=lambda r: int(r.get('height') or 0), reverse=True)
            paid_rows = []
            for r in all_recs:
                pmap = r.get('payouts') or {}
                amt = float(pmap.get(clean_a) or 0.0)
                if amt > 0.0:
                    paid_rows.append((int(r.get('height') or 0), str(r.get('hash') or ''), int(r.get('ts') or 0), amt))
            parts.append('<div class="card"><h2>On-Chain P2Pool Payout History for Wallet</h2>')
            parts.append('<div class="mono" style="margin-bottom:10px"><div><strong>Wallet:</strong> %s</div>' % _html_esc(clean_a))
            parts.append('<div><strong>7d:</strong> %.4f SCASH &bull; <strong>30d:</strong> %.4f SCASH &bull; <strong>All-Time:</strong> %.4f SCASH (%d blocks paid)</div>' % (
                float(lg_a.get('miner_scash_7d') or 0.0),
                float(lg_a.get('miner_scash_30d') or 0.0),
                float(lg_a.get('miner_scash_all_time') or 0.0),
                int(lg_a.get('miner_blocks_paid') or 0),
            ))
            parts.append('<div style="margin-top:8px"><strong>External Explorers:</strong> ')
            parts.append('<a class="pill" target="_blank" rel="noopener" href="%s">explorer.scash.network &#8599;</a>' % _html_esc(e1_adr.replace('{id}', clean_a)))
            parts.append('<a class="pill" target="_blank" rel="noopener" href="%s">scash.tv &#8599;</a></div></div>' % _html_esc(e2_adr.replace('{id}', clean_a)))
            if paid_rows:
                parts.append('<table><thead><tr><th>Block</th><th>Block Hash</th><th>Time (UTC)</th><th style="text-align:right">Your Coinbase Payout</th></tr></thead><tbody>')
                for ht_i, bh_s, ts_i, amt_v in paid_rows[:100]:
                    iso_t = _w_time.strftime('%Y-%m-%d %H:%M:%S', _w_time.gmtime(ts_i)) if ts_i > 0 else '—'
                    short_h = (bh_s[:14] + '...' + bh_s[-8:]) if len(bh_s) >= 24 else bh_s
                    parts.append('<tr><td class="mono"><a href="/local_explorer?block=%s">#%d</a></td><td class="mono"><a href="/explorer_go?type=block&amp;id=%s" target="_blank" rel="noopener">%s &#8599;</a></td><td class="mono">%s</td><td class="mono amt">+%.8f SCASH</td></tr>' % (
                        _html_esc(bh_s or str(ht_i)), ht_i, _html_esc(bh_s or str(ht_i)), _html_esc(short_h), _html_esc(iso_t), amt_v
                    ))
                parts.append('</tbody></table>')
            else:
                parts.append('<div class="mono" style="color:#c4b5fd">No solved P2Pool coinbase payouts recorded for this address in local scanned blocks yet.</div>')
            parts.append('</div>')

        if not block_q and not addr_q:
            lg_all = _summarize_ledger_stats()
            parts.append('<div class="card"><h2>Recent Solved Scash P2Pool Blocks (Local Blockchain Ledger)</h2>')
            rbs = lg_all.get('recent_blocks') or []
            if rbs:
                parts.append('<table><thead><tr><th>Block</th><th>Block Hash</th><th>Time (UTC)</th><th style="text-align:right">Reward</th></tr></thead><tbody>')
                for b in rbs:
                    bh_s = str(b.get('hash') or '')
                    ht_i = int(b.get('number') or 0)
                    ts_i = int(b.get('ts') or 0)
                    iso_t = _w_time.strftime('%Y-%m-%d %H:%M:%S', _w_time.gmtime(ts_i)) if ts_i > 0 else '—'
                    short_h = (bh_s[:16] + '...' + bh_s[-8:]) if len(bh_s) >= 26 else bh_s
                    parts.append('<tr><td class="mono"><a href="/local_explorer?block=%s">#%d</a></td><td class="mono"><a href="/explorer_go?type=block&amp;id=%s" target="_blank" rel="noopener">%s &#8599;</a></td><td class="mono">%s</td><td class="mono amt">%.8f SCASH</td></tr>' % (
                        _html_esc(bh_s or str(ht_i)), ht_i, _html_esc(bh_s or str(ht_i)), _html_esc(short_h), _html_esc(iso_t), float(b.get('reward') or 50.0)
                    ))
                parts.append('</tbody></table>')
            else:
                parts.append('<div class="mono">No P2Pool blocks recorded in local ledger yet.</div>')
            parts.append('</div>')

        parts.append('</body></html>')
        return ''.join(parts)

    class _ScashExplorerGoResource(_tw_resource.Resource):
        isLeaf = True
        def __init__(self, mode='go', wb_ref=None):
            _tw_resource.Resource.__init__(self)
            self.mode = mode
            self.wb_ref = wb_ref
        def render_GET(self, request):
            def _arg(k):
                vals = request.args.get(k, request.args.get(k.encode('utf-8'), [None]))
                v = vals[0] if vals else None
                return v.decode('utf-8', 'replace') if isinstance(v, bytes) else v
            if self.mode == 'local':
                request.setHeader('Content-Type', 'text/html; charset=utf-8')
                request.setHeader('Cache-Control', 'no-store')
                html_s = _render_local_explorer_html(
                    self.wb_ref,
                    block_q=_arg('block') or '',
                    addr_q=_arg('address') or '',
                )
                return html_s if isinstance(html_s, bytes) else html_s.encode('utf-8')
            kind = _arg('type') or ('address' if _arg('address') else 'block')
            tid = _arg('id') or _arg('block') or _arg('address') or ''
            pref = _arg('prefer') or ''
            dest = _cycle_and_pick_explorer_url(kind, tid, prefer_key=pref)
            request.setResponseCode(302)
            request.setHeader('Location', dest.encode('utf-8') if isinstance(dest, type(u'')) and bytes is str else dest)
            request.setHeader('Cache-Control', 'no-store')
            body = '<html><body>Redirecting to working Scash explorer: <a href="%s">%s</a></body></html>' % (_html_esc(dest), _html_esc(dest))
            return body if isinstance(body, bytes) else body.encode('utf-8')

    _sc_sync_lock = _w_threading.Lock()
    _sc_sync_tracker = {
        'boot_ts': _w_time.time(),
        'last_items_len': 0,
        'last_ver_len': 0,
        'last_growth_ts': _w_time.time(),
        'settled': False,
    }

    def _get_sharechain_sync_state(_wb_ref, now_ts=None):
        t_now = float(now_ts if now_ts is not None else _w_time.time())
        p_cnt = 0
        tot_n = 0
        ver_n = 0
        ch_h = 0
        real_len = 5760
        try:
            _node = getattr(_wb_ref, 'node', None)
            _p2pn = getattr(_node, 'p2p_node', None)
            if _p2pn is not None and getattr(_p2pn, 'peers', None) is not None:
                p_cnt = len(_p2pn.peers)
            _tr = getattr(_node, 'tracker', None)
            _net = getattr(_node, 'net', None)
            if _net is not None:
                real_len = int(getattr(_net, 'REAL_CHAIN_LENGTH', 5760))
            if _tr is not None and hasattr(_tr, 'items'):
                tot_n = len(_tr.items)
                _ver_obj = getattr(_tr, 'verified', None)
                if _ver_obj is not None and hasattr(_ver_obj, 'items'):
                    ver_n = len(_ver_obj.items)
                _best = getattr(getattr(_node, 'best_share_var', None), 'value', None)
                if _best is not None and _best in _tr.items:
                    ch_h = int(_tr.get_height(_best))
        except Exception:
            pass

        if os.environ.get('SCASH_CI_FAST_DIFF') == '1' or os.environ.get('SCASH_SKIP_SHARECHAIN_GATE') == '1':
            return {
                'syncing': False,
                'settled': True,
                'peers': int(p_cnt),
                'chain_height': int(ch_h),
                'verified_shares': int(ver_n),
                'total_shares': int(tot_n),
                'status_text': 'Ready',
            }

        with _sc_sync_lock:
            age = max(0.0, t_now - float(_sc_sync_tracker['boot_ts']))
            if (
                (tot_n - _sc_sync_tracker['last_items_len']) >= 6
                or ((tot_n > _sc_sync_tracker['last_items_len']) and (ver_n == 0 or tot_n > ver_n))
                or ((ver_n - _sc_sync_tracker['last_ver_len']) >= 6 and ver_n < (min(int(ch_h), int(real_len)) - 5))
            ):
                _sc_sync_tracker['last_growth_ts'] = t_now
            _sc_sync_tracker['last_items_len'] = tot_n
            _sc_sync_tracker['last_ver_len'] = ver_n
            since_growth = max(0.0, t_now - float(_sc_sync_tracker['last_growth_ts']))

            if _sc_sync_tracker['settled'] or age >= 75.0:
                _sc_sync_tracker['settled'] = True
                return {
                    'syncing': False,
                    'settled': True,
                    'peers': int(p_cnt),
                    'chain_height': int(ch_h),
                    'verified_shares': int(ver_n),
                    'total_shares': int(tot_n),
                    'status_text': 'Sharechain synced',
                }

            # 1) Brief 7s startup window to let LAN/WAN peers connect before mining at genesis diff
            if p_cnt == 0 and tot_n == 0:
                if age < 7.0:
                    return {
                        'syncing': True,
                        'settled': False,
                        'peers': 0,
                        'chain_height': 0,
                        'verified_shares': 0,
                        'total_shares': 0,
                        'status_text': 'Connecting to P2Pool peers (:8344)...',
                    }
                _sc_sync_tracker['settled'] = True
                return {
                    'syncing': False,
                    'settled': True,
                    'peers': 0,
                    'chain_height': 0,
                    'verified_shares': 0,
                    'total_shares': 0,
                    'status_text': 'Solo/Seed ready (0 peers)',
                }

            # 2) Peer(s) connected: wait while share batches are actively streaming or 24h window is verifying
            target_ver = min(int(ch_h), int(real_len))
            if p_cnt > 0 and tot_n == 0 and age < 20.0:
                return {
                    'syncing': True,
                    'settled': False,
                    'peers': int(p_cnt),
                    'chain_height': 0,
                    'verified_shares': 0,
                    'total_shares': 0,
                    'status_text': 'Downloading P2Pool sharechain from %d peer(s)...' % int(p_cnt),
                }
            if since_growth < 3.5 or (tot_n > ver_n and since_growth < 12.0 and age < 60.0) or (target_ver >= 50 and ver_n < (target_ver - 10) and since_growth < 12.0 and age < 60.0):
                return {
                    'syncing': True,
                    'settled': False,
                    'peers': int(p_cnt),
                    'chain_height': int(ch_h),
                    'verified_shares': int(ver_n),
                    'total_shares': int(tot_n),
                    'status_text': 'Verifying P2Pool sharechain (%d / %d shares)...' % (int(ver_n), int(max(tot_n, target_ver))),
                }

            _sc_sync_tracker['settled'] = True
            return {
                'syncing': False,
                'settled': True,
                'peers': int(p_cnt),
                'chain_height': int(ch_h),
                'verified_shares': int(ver_n),
                'total_shares': int(tot_n),
                'status_text': 'Sharechain synced',
            }

    def _maybe_start_v032_telemetry_daemons(_wb_ref):
        if not _hr_sampler_started['active']:
            _hr_sampler_started['active'] = True
            def _hr_loop():
                while True:
                    try:
                        _sample_hashrate_rings(_wb_ref)
                    except Exception:
                        pass
                    _w_time.sleep(5.0)
            _ht = _w_threading.Thread(target=_hr_loop)
            _ht.daemon = True
            _ht.start()

        if not _ledger_daemon_started['active']:
            _ledger_daemon_started['active'] = True
            def _lg_loop():
                _w_time.sleep(8.0)
                while True:
                    try:
                        _sync_p2pool_ledger_once(_wb_ref, max_backfill_blocks=400)
                        with _ledger_lock:
                            min_s = _ledger_state['min_scanned_height']
                            ch = _ledger_state['chain']
                        target_floor = 140000 if ch in ('scash', 'main') else 1
                        if min_s is not None and int(min_s) > target_floor:
                            _w_time.sleep(1.0)
                            continue
                    except Exception:
                        pass
                    _w_time.sleep(15.0)
            _lt = _w_threading.Thread(target=_lg_loop)
            _lt.daemon = True
            _lt.start()
        _get_cached_scash_market()
        _get_cached_explorers()

    def _build_pool_telemetry_payload(_wb_ref, wallet_param=None):
        w_eff = (wallet_param or _xmrig_mgr.GLOBAL_XMRIG.wallet or '').strip()
        # Ensure initial tip scan runs immediately if ledger hasn't scanned yet
        with _ledger_lock:
            uninitialized = (_ledger_state['max_scanned_height'] is None and not _ledger_state['scanning'])
        if uninitialized:
            _init_lt = _w_threading.Thread(target=_sync_p2pool_ledger_once, args=(_wb_ref, 100))
            _init_lt.daemon = True
            _init_lt.start()
        rates = _sample_hashrate_rings(_wb_ref)
        ledger = _summarize_ledger_stats(wallet_addr=w_eff)
        market = _get_cached_scash_market()
        explorers = _get_cached_explorers()
        sc_sync = _get_sharechain_sync_state(_wb_ref)
        return {
            'ok': True,
            'version': '0.4.0',
            'hashrates': rates,
            'ledger': ledger,
            'market': market,
            'explorers': explorers,
            'sharechain_sync': sc_sync,
        }

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
                            # If actively mining right now (tip share < 300s old) after an earlier offline gap,
                            # measure the contiguous active window (no > 300s gap between shares, up to 60 shares)
                            if (now_ts - float(_s_tip.timestamp)) <= 300.0:
                                _act_n = 1
                                _cur_h = _best
                                _prev_t = float(_s_tip.timestamp)
                                for _ in range(min(_ch_h - 1, 60)):
                                    _par_h = _tracker.items[_cur_h].previous_hash
                                    if _par_h not in _tracker.items:
                                        break
                                    _par_t = float(_tracker.items[_par_h].timestamp)
                                    if (_prev_t - _par_t) > 300.0:
                                        break
                                    _act_n += 1
                                    _cur_h = _par_h
                                    _prev_t = _par_t
                                if _act_n >= 3 and _act_n < _lb:
                                    _recent_hr = float(_p2p_data.get_pool_attempts_per_second(_tracker, _best, _act_n))
                                    pool_hr = _recent_hr
                                    _dt_r = max(1.0, float(_s_tip.timestamp) - _prev_t)
                                    shares_ps = round(float(_act_n - 1) / _dt_r, 4)
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
            _lg_sum = _summarize_ledger_stats()
            if int(_lg_sum.get('pool_blocks_all_time') or 0) > total_blocks:
                total_blocks = int(_lg_sum['pool_blocks_all_time'])
            if _lg_sum.get('last_block_ts') and not last_block_iso:
                last_block_iso = _w_time.strftime('%Y-%m-%dT%H:%M:%SZ', _w_time.gmtime(int(_lg_sum['last_block_ts'])))
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
            'poolFeePercent': 0.0,
            'address': '',
            'addressInfoLink': (_get_cached_explorers().get('active_url') if str(_get_cached_explorers().get('active_url') or '').startswith('http') else 'https://explorer.scash.network/'),
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
            r_req = _w_ureq.Request('%s/%s/gh-pages/api/pools.json' % (raw_base, repo_slug), headers={'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)'})
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
                'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
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


    _DEFAULT_COLLECTOR_REPORT_URL = 'https://scash-p2pool-stats.magicalgirlsunited.workers.dev/api/report'
    _community_reporter_started = {'active': False, 'logged': False}
    _collector_cache = {'ts': 0.0, 'url': ''}

    def _norm_report_url(raw_u):
        u = str(raw_u or '').strip()
        if not u:
            return ''
        if not (u.startswith('https://') or u.startswith('http://127.0.0.1')):
            return ''
        # If user put the root Worker URL (e.g. https://...workers.dev/), append /api/report automatically
        stripped = u.rstrip('/')
        if stripped.count('/') == 2:
            return stripped + '/api/report'
        return u

    def _resolve_collector_report_url():
        override = _norm_report_url(os.environ.get('SCASH_STATS_REPORT_URL') or '')
        if override:
            return override
        now_t = _w_time.time()
        ttl = 900.0 if _collector_cache['url'] else 45.0
        if _collector_cache['ts'] > 0 and (now_t - _collector_cache['ts']) < ttl:
            return _collector_cache['url'] or _DEFAULT_COLLECTOR_REPORT_URL
        _collector_cache['ts'] = now_t
        repo_slug = (os.environ.get('SCASH_GHPAGES_REPO') or 'ScashNetworkCommunity/Scash-peer-to-peer-mining-pool').strip()
        raw_base = (os.environ.get('SCASH_GH_RAW_BASE') or 'https://raw.githubusercontent.com').rstrip('/')
        for u in (
            '%s/%s/gh-pages/collector.json' % (raw_base, repo_slug),
            'https://scashnetworkcommunity.github.io/Scash-peer-to-peer-mining-pool/collector.json',
        ):
            try:
                req = _w_ureq.Request(u, headers={'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)'})
                txt = _scash_open_url(req, timeout=4.0, is_local=u.startswith('http://127.0.0.1')).decode('utf-8', 'replace')
                obj = _w_json.loads(txt) or {}
                if 'report_url' in obj:
                    raw_ru = str(obj.get('report_url') or '').strip()
                    if raw_ru.lower() in ('off', 'disabled', 'none'):
                        _collector_cache['url'] = 'DISABLED'
                        return ''
                    ru = _norm_report_url(raw_ru)
                    if ru:
                        _collector_cache['url'] = ru
                        return ru
            except Exception:
                pass
        return _collector_cache['url'] if _collector_cache['url'] and _collector_cache['url'] != 'DISABLED' else _DEFAULT_COLLECTOR_REPORT_URL

    def _send_community_report_once(_wb_ref, report_url=None):
        if os.environ.get('SCASH_DISABLE_PUBLIC_STATS') == '1':
            return False
        target_url = _norm_report_url(report_url) if report_url else _resolve_collector_report_url()
        if not target_url:
            return False
        pool_obj = _build_miningcore_pool_payload(_wb_ref)
        best_hex = ''
        chain_h = 0
        p2p_peers = 0
        _p2pn = None
        _mesh_meta = {}
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
        try:
            from p2pool import auto_mesh as _scash_am_rep
            _mst = _scash_am_rep.get_mesh_status() or {}
            if _mst.get('started') and int(_mst.get('external_udp_port') or 0) == 0 and report_url is None and os.environ.get('SCASH_CI_ISOLATED_MESH') != '1':
                _scash_am_rep.refresh_stun_on_shared_socket(wait_s=0.9)
                _mst = _scash_am_rep.get_mesh_status() or {}
            _mesh_meta = {
                'instance_id': str(_mst.get('instance_id') or ''),
                'external_ip': str(_mst.get('external_ip') or ''),
                'p2p_port': int(_mst.get('p2p_port') or 8344),
                'udp_port': int(_mst.get('udp_port') or 8344),
                'external_udp_port': int(_mst.get('external_udp_port') or 0),
                'upnp_open': bool(_mst.get('upnp_mapped') or _mst.get('pcp_mapped') or _mst.get('natpmp_mapped')),
                'nat_mapping': str(_mst.get('nat_mapping') or 'unknown'),
                'wan_peers': int(_mst.get('connected_wan_peers') or 0),
                'lan_peers': int(_mst.get('connected_lan_peers') or 0),
                'holepunch_tunnels': int(_mst.get('holepunch_tunnels') or 0),
                'wss_relay_tunnels': int(_mst.get('wss_relay_tunnels') or 0),
            }
        except Exception:
            _mesh_meta = {}
        body = _w_json.dumps({
            'version': '0.4.0',
            'best_share_hash': best_hex,
            'chain_height': int(chain_h),
            'p2pool_peers': int(p2p_peers),
            'mesh': _mesh_meta,
            'pool_payload': pool_obj,
        }).encode('utf-8')
        req = _w_ureq.Request(target_url, body, {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (compatible; Scash-P2Pool/0.4.0; +https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool)',
        })
        raw_rep_resp = _scash_open_url(req, timeout=5.0, is_local=target_url.startswith('http://127.0.0.1'))
        try:
            if raw_rep_resp:
                rep_obj = _w_json.loads(raw_rep_resp.decode('utf-8', 'replace')) or {}
                if 'relay_enabled' in rep_obj or 'relay_wss_url' in rep_obj:
                    from p2pool import auto_mesh as _scash_am_rel
                    if hasattr(_scash_am_rel, 'update_wss_relay_from_report'):
                        _scash_am_rel.update_wss_relay_from_report(
                            rep_obj.get('relay_wss_url') or '',
                            bool(rep_obj.get('relay_enabled', True)),
                        )
                r_peers = rep_obj.get('rendezvous_peers')
                if isinstance(r_peers, list) and r_peers:
                    from p2pool import auto_mesh as _scash_am_ing
                    _scash_am_ing.ingest_https_rendezvous_peers(_p2pn, r_peers)
        except Exception:
            pass
        if not _community_reporter_started.get('logged'):
            _community_reporter_started['logged'] = True
            try:
                import sys as _w_sys2
                _w_sys2.stdout.write('[Stats API] Connected to live Scash P2Pool stats feed (60s updates active)' + chr(10))
                _w_sys2.stdout.flush()
            except Exception:
                pass
        return True

    def _maybe_start_community_reporter(_wb_ref):
        if _community_reporter_started['active'] or os.environ.get('SCASH_DISABLE_PUBLIC_STATS') == '1':
            return
        if os.environ.get('SCASH_CI_ISOLATED_MESH') == '1':
            return
        _community_reporter_started['active'] = True

        def _c_loop():
            _w_time.sleep(5.0)
            try:
                _send_community_report_once(_wb_ref)
            except Exception:
                pass
            _w_time.sleep(15.0)
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
        def __init__(self, action, wb_ref=None):
            _tw_resource.Resource.__init__(self)
            self.action = action
            self.wb_ref = wb_ref
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
                _w_in = _arg('wallet')
                if _w_in and self.wb_ref is not None:
                    try:
                        from p2pool.bitcoin import data as _b_d
                        _pnet = getattr(getattr(self.wb_ref, 'node', None), 'net', None)
                        _parent = getattr(_pnet, 'PARENT', None)
                        if _parent is not None and hasattr(self.wb_ref, 'my_pubkey_hash'):
                            self.wb_ref.my_pubkey_hash = _b_d.address_to_pubkey_hash(_w_in, _parent)
                    except Exception:
                        pass
                return _jb(_xmrig_mgr.GLOBAL_XMRIG.start_mining(
                    wallet=_w_in,
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
            elif self.action == 'telemetry':
                return _jb(_build_pool_telemetry_payload(self.wb_ref, wallet_param=_arg('wallet')))
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
            _maybe_start_v032_telemetry_daemons(_wb_obj)
            _maybe_start_ghpages_publisher(_wb_obj)
            _maybe_start_community_reporter(_wb_obj)
        except Exception:
            pass
        _wr.putChild(b'pool_telemetry', _ScashMinerControlResource('telemetry', wb_ref=_wb_obj))
        _wr.putChild(b'explorer_go', _ScashExplorerGoResource('go', wb_ref=_wb_obj))
        _wr.putChild(b'local_explorer', _ScashExplorerGoResource('local', wb_ref=_wb_obj))
        _wr.putChild(b'miner_status', _ScashMinerControlResource('status'))
        _wr.putChild(b'miner_start', _ScashMinerControlResource('start', wb_ref=_wb_obj))
        _wr.putChild(b'miner_stop', _ScashMinerControlResource('stop'))
        _wr.putChild(b'nodes_list', _ScashMinerControlResource('nodes'))
        _wr.putChild(b'node_sync_status', _ScashMinerControlResource('sync'))
        _wr.putChild(b'mesh_status', _ScashMinerControlResource('mesh'))
        _wr.putChild(b'api', _ScashMiningcoreApiResource(_wb_obj))
        return _wr
except Exception:
    pass
