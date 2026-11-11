from __future__ import division

import json
import weakref

from twisted.internet import defer
from twisted.protocols import basic
from twisted.python import failure, log
from twisted.web import client, error

from p2pool.util import deferral, deferred_resource, memoize

class Error(Exception):
    def __init__(self, code, message, data=None):
        if type(self) is Error:
            raise TypeError("can't directly instantiate Error class; use Error_for_code")
        if not isinstance(code, int):
            raise TypeError('code must be an int')
        #if not isinstance(message, unicode):
        #    raise TypeError('message must be a unicode')
        self.code, self.message, self.data = code, message, data
    def __str__(self):
        return '%i %s' % (self.code, self.message) + (' %r' % (self.data, ) if self.data is not None else '')
    def _to_obj(self):
        return {
            'code': self.code,
            'message': self.message,
            'data': self.data,
        }

@memoize.memoize_with_backing(weakref.WeakValueDictionary())
def Error_for_code(code):
    class NarrowError(Error):
        def __init__(self, *args, **kwargs):
            Error.__init__(self, code, *args, **kwargs)
    return NarrowError


class Proxy(object):
    def __init__(self, func, services=[]):
        self._func = func
        self._services = services
    
    def __getattr__(self, attr):
        if attr.startswith('rpc_'):
            return lambda *params: self._func('.'.join(self._services + [attr[len('rpc_'):]]), params)
        elif attr.startswith('svc_'):
            return Proxy(self._func, self._services + [attr[len('svc_'):]])
        else:
            raise AttributeError('%r object has no attribute %r' % (self.__class__.__name__, attr))

@defer.inlineCallbacks
def _handle(data, provider, preargs=(), response_handler=None):
        id_ = None
        
        try:
            try:
                try:
                    req = json.loads(data)
                except Exception:
                    raise Error_for_code(-32700)(u'Parse error')
                
                if 'result' in req or 'error' in req:
                    response_handler(req['id'], req['result'] if 'error' not in req or req['error'] is None else
                        failure.Failure(Error_for_code(req['error']['code'])(req['error']['message'], req['error'].get('data', None))))
                    defer.returnValue(None)
                
                id_ = req.get('id', None)
                method = req.get('method', None)
                if not isinstance(method, basestring):
                    raise Error_for_code(-32600)(u'Invalid Request')
                params = req.get('params', [])
                if not isinstance(params, list):
                    raise Error_for_code(-32600)(u'Invalid Request')
                
                for service_name in method.split('.')[:-1]:
                    provider = getattr(provider, 'svc_' + service_name, None)
                    if provider is None:
                        raise Error_for_code(-32601)(u'Service not found')
                
                method_meth = getattr(provider, 'rpc_' + method.split('.')[-1], None)
                if method_meth is None:
                    raise Error_for_code(-32601)(u'Method not found')
                
                result = yield method_meth(*list(preargs) + list(params))
                error = None
            except Error:
                raise
            except Exception:
                log.err(None, 'Squelched JSON error:')
                raise Error_for_code(-32099)(u'Unknown error')
        except Error, e:
            result = None
            error = e._to_obj()
        
        defer.returnValue(json.dumps(dict(
            jsonrpc='2.0',
            id=id_,
            result=result,
            error=error,
        )))

# HTTP

@defer.inlineCallbacks
def _http_do(url, headers, timeout, method, params):
    id_ = 0
    
    try:
        data = yield client.getPage(
            url=url,
            method='POST',
            headers=dict(headers, **{'Content-Type': 'application/json'}),
            postdata=json.dumps({
                'jsonrpc': '2.0',
                'method': method,
                'params': params,
                'id': id_,
            }),
            timeout=timeout,
        )
    except error.Error, e:
        try:
            resp = json.loads(e.response)
        except:
            raise e
    else:
        resp = json.loads(data)
    
    if resp['id'] != id_:
        raise ValueError('invalid id')
    if 'error' in resp and resp['error'] is not None:
        raise Error_for_code(resp['error']['code'])(resp['error']['message'], resp['error'].get('data', None))
    defer.returnValue(resp['result'])
HTTPProxy = lambda url, headers={}, timeout=5: Proxy(lambda method, params: _http_do(url, headers, timeout, method, params))

class HTTPServer(deferred_resource.DeferredResource):
    def __init__(self, provider):
        deferred_resource.DeferredResource.__init__(self)
        self._provider = provider
    
    @defer.inlineCallbacks
    def render_POST(self, request):
        data = yield _handle(request.content.read(), self._provider, preargs=[request])
        assert data is not None
        request.setHeader('Content-Type', 'application/json')
        request.setHeader('Content-Length', len(data))
        request.write(data)

class LineBasedPeer(basic.LineOnlyReceiver):
    delimiter = '\n'
    
    def __init__(self):
        #basic.LineOnlyReceiver.__init__(self)
        self._matcher = deferral.GenericDeferrer(max_id=2**30, func=lambda id, method, params: self.sendLine(json.dumps({
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': id,
        })))
        self.other = Proxy(self._matcher)
    
    def lineReceived(self, line):
        _handle(line, self, response_handler=self._matcher.got_response).addCallback(lambda line2: self.sendLine(line2) if line2 is not None else None)

# --- Scash Core 30.4.0 HTTPProxy & rpc_help shim ---
from twisted.internet import defer as _jr_defer

def _norm_core30_response(obj, method_attr=''):
    if isinstance(obj, dict):
        if isinstance(obj.get('warnings'), list):
            obj = dict(obj)
            obj['warnings'] = '; '.join(str(x) for x in obj['warnings'])
        if method_attr == 'rpc_validateaddress' and 'ismine' not in obj:
            obj = dict(obj)
            obj.setdefault('ismine', False)
            obj.setdefault('iswatchonly', False)
        if method_attr == 'rpc_getblocktemplate':
            obj = dict(obj)
            cb_aux = dict(obj.get('coinbaseaux') or {})
            cb_aux.setdefault('flags', '')
            obj['coinbaseaux'] = cb_aux
    return obj

_orig_HTTPProxy = HTTPProxy

class _ScashBitcoindProxy(object):
    def __init__(self, inner):
        self._inner = inner

    def rpc_help(self, *args):
        return _jr_defer.succeed(
            'getblock\ngetblockchaininfo\ngetblockhash\ngetblockheader\n'
            'getblocktemplate\ngetinfo\ngetmininginfo\ngetnetworkinfo\n'
            'getpeerinfo\nsubmitblock\nvalidateaddress\n'
        )

    @_jr_defer.inlineCallbacks
    def rpc_getinfo(self):
        bc = yield self.rpc_getblockchaininfo()
        try:
            net = yield self.rpc_getnetworkinfo()
        except Exception:
            net = {}
        w_bc = bc.get('warnings', '')
        w_net = net.get('warnings', '')
        if isinstance(w_bc, list):
            w_bc = '; '.join(str(x) for x in w_bc)
        if isinstance(w_net, list):
            w_net = '; '.join(str(x) for x in w_net)
        _jr_defer.returnValue({
            'version': net.get('version', 300400),
            'protocolversion': net.get('protocolversion', 70016),
            'blocks': bc.get('blocks', 0),
            'connections': net.get('connections', 0),
            'difficulty': bc.get('difficulty', 1.0),
            'testnet': bc.get('chain', 'scash') not in ('scash', 'main'),
            'relayfee': net.get('relayfee', 0.00001),
            'errors': w_bc or w_net,
            'warnings': w_bc or w_net,
        })

    def __getattr__(self, attr):
        fn = getattr(self._inner, attr)
        if attr.startswith('rpc_'):
            def _wrapped(*a, **kw):
                if attr == 'rpc_getblocktemplate':
                    if not a:
                        a = ({'mode': 'template', 'rules': ['segwit']},)
                    elif isinstance(a[0], dict) and a[0].get('mode', 'template') == 'template' and 'rules' not in a[0]:
                        d0 = dict(a[0])
                        d0['rules'] = ['segwit']
                        a = (d0,) + a[1:]
                d = fn(*a, **kw)
                d.addCallback(_norm_core30_response, attr)
                return d
            return _wrapped
        return fn

def HTTPProxy(*args, **kwargs):
    return _ScashBitcoindProxy(_orig_HTTPProxy(*args, **kwargs))
