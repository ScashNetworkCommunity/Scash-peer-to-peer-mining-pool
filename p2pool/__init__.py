import codecs
import sys

__version__ = 'v0.2.0-beta.6-scash-kawaii'
DEBUG = False

try:
    codecs.register(lambda n: codecs.lookup('utf-8') if n.lower().replace('-', '').replace('_', '') in ('cp65001', '65001') else None)
except Exception:
    pass

if sys.version_info[0] < 3:
    class _P2PoolSafeStream(object):
        def __init__(self, inner):
            self._inner = inner
        def write(self, data):
            try:
                if not isinstance(data, bytes):
                    data = (
                        data.replace(u'\u2026', u'...')
                        .replace(u'\u2014', u'--')
                        .replace(u'\u2013', u'-')
                        .replace(u'\u2022', u'*')
                    )
                    enc = getattr(self._inner, 'encoding', None) or 'ascii'
                    data = data.encode(enc, 'replace')
            except Exception:
                try:
                    data = data.encode('ascii', 'replace')
                except Exception:
                    pass
            return self._inner.write(data)
        def flush(self):
            try:
                return self._inner.flush()
            except Exception:
                pass
        def __getattr__(self, attr):
            return getattr(self._inner, attr)

    if not hasattr(sys.stdout, '_inner'):
        sys.stdout = _P2PoolSafeStream(sys.stdout)
    if not hasattr(sys.stderr, '_inner'):
        sys.stderr = _P2PoolSafeStream(sys.stderr)

    try:
        import ssl as _stdlib_ssl
        import urllib2 as _stdlib_urllib2
        from twisted.internet import threads as _tw_threads
        from twisted.web import client as _tw_client

        _orig_tw_getPage = _tw_client.getPage

        def _scash_fetch_bytes(url, method='GET', postdata=None, headers=None, timeout=10):
            u = url.decode('utf-8') if isinstance(url, bytes) else str(url)
            hdrs = {'User-Agent': 'Scash-P2Pool/0.2.0-beta.6'}
            if headers:
                for hk, hv in headers.items():
                    ks = hk.decode('utf-8') if isinstance(hk, bytes) else str(hk)
                    if isinstance(hv, (list, tuple)):
                        hv = hv[0] if hv else ''
                    vs = hv.decode('utf-8') if isinstance(hv, bytes) else str(hv)
                    hdrs[ks] = vs
            req = _stdlib_urllib2.Request(u, data=postdata, headers=hdrs)
            if method and method.upper() != ('POST' if postdata is not None else 'GET'):
                req.get_method = lambda: method.upper()
            if u.lower().startswith('https://') and hasattr(_stdlib_ssl, '_create_unverified_context'):
                ctx = _stdlib_ssl._create_unverified_context()
                return _stdlib_urllib2.urlopen(req, timeout=timeout, context=ctx).read()
            return _stdlib_urllib2.urlopen(req, timeout=timeout).read()

        def _scash_safe_getPage(url, contextFactory=None, *args, **kwargs):
            u = url.decode('utf-8') if isinstance(url, bytes) else str(url)
            if not u.lower().startswith('https://'):
                return _orig_tw_getPage(url, contextFactory=contextFactory, *args, **kwargs)
            timeout = kwargs.get('timeout', 10)
            method = kwargs.get('method', 'GET')
            postdata = kwargs.get('postdata', None)
            headers = kwargs.get('headers', None)
            return _tw_threads.deferToThread(_scash_fetch_bytes, u, method, postdata, headers, timeout)

        _tw_client.getPage = _scash_safe_getPage

        if hasattr(_tw_client, 'HTTPPageGetter'):
            _orig_301 = _tw_client.HTTPPageGetter.handleStatus_301

            def _safe_redirect(self):
                l = self.headers.get('location')
                if l and l[0].lower().startswith('https://'):
                    target_u = l[0]
                    d = _tw_threads.deferToThread(_scash_fetch_bytes, target_u, 'GET', None, None, 10)
                    d.addCallbacks(lambda body: self.factory.page(body), lambda f: self.factory.noPage(f))
                    self.quietLoss = 1
                    self.transport.loseConnection()
                    return
                return _orig_301(self)

            _tw_client.HTTPPageGetter.handleStatus_301 = _safe_redirect
            _tw_client.HTTPPageGetter.handleStatus_302 = _safe_redirect
            _tw_client.HTTPPageGetter.handleStatus_303 = _safe_redirect
            if hasattr(_tw_client.HTTPPageGetter, 'handleStatus_307'):
                _tw_client.HTTPPageGetter.handleStatus_307 = _safe_redirect
    except Exception:
        pass
