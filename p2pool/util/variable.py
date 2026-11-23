import itertools
import weakref

from twisted.internet import defer, reactor
from twisted.python import failure, log

class Event(object):
    def __init__(self):
        self.observers = {}
        self.id_generator = itertools.count()
        self._once = None
        self.times = 0
    
    def run_and_watch(self, func):
        func()
        return self.watch(func)
    def watch_weakref(self, obj, func):
        # func must not contain a reference to obj!
        watch_id = self.watch(lambda *args: func(obj_ref(), *args))
        obj_ref = weakref.ref(obj, lambda _: self.unwatch(watch_id))
    def watch(self, func):
        id = self.id_generator.next()
        self.observers[id] = func
        return id
    def unwatch(self, id):
        self.observers.pop(id)
    
    @property
    def once(self):
        res = self._once
        if res is None:
            res = self._once = Event()
        return res
    
    def happened(self, *event):
        self.times += 1
        
        once, self._once = self._once, None
        
        for id, func in sorted(self.observers.iteritems()):
            try:
                func(*event)
            except:
                log.err(None, "Error while processing Event callbacks:")
        
        if once is not None:
            once.happened(*event)
    
    def get_deferred(self, timeout=None):
        once = self.once
        df = defer.Deferred()
        id1 = once.watch(lambda *event: df.callback(event))
        if timeout is not None:
            def do_timeout():
                df.errback(failure.Failure(defer.TimeoutError('in Event.get_deferred')))
                once.unwatch(id1)
                once.unwatch(x)
            delay = reactor.callLater(timeout, do_timeout)
            x = once.watch(lambda *event: delay.cancel())
        return df

class Variable(object):
    def __init__(self, value):
        self.value = value
        self.changed = Event()
        self.transitioned = Event()
    
    def set(self, value):
        if value == self.value:
            return
        
        oldvalue = self.value
        self.value = value
        self.changed.happened(value)
        self.transitioned.happened(oldvalue, value)
    
    @defer.inlineCallbacks
    def get_when_satisfies(self, func):
        while True:
            if func(self.value):
                defer.returnValue(self.value)
            yield self.changed.once.get_deferred()
    
    def get_not_none(self):
        return self.get_when_satisfies(lambda val: val is not None)

# --- Scash PyPy Weakref GC Safe Watch Guard ---
import weakref as _scash_var_weakref

def _scash_install_safe_watch_weakref(_cls):
    if _cls is None or not hasattr(_cls, 'watch_weakref'):
        return
    _orig_ww = getattr(_cls, '_scash_orig_ww', _cls.watch_weakref)
    _cls._scash_orig_ww = _orig_ww
    def _safe_watch_weakref(self, obj, func):
        _wid_box = [None]
        def _safe_unwatch():
            _wid = _wid_box[0]
            if _wid is not None:
                _wid_box[0] = None
                try:
                    _obs = getattr(self, 'observers', None)
                    if _obs is None or _wid in _obs:
                        self.unwatch(_wid)
                except Exception:
                    pass
        _obj_ref = _scash_var_weakref.ref(obj, lambda _r: _safe_unwatch())
        def _cb(*args):
            _o = _obj_ref()
            if _o is None:
                _safe_unwatch()
                return None
            return func(_o, *args)
        _wid_box[0] = self.watch(_cb)
        return _wid_box[0]
    _cls.watch_weakref = _safe_watch_weakref

for _vcls_name in ('Event', 'Variable'):
    if _vcls_name in globals():
        _scash_install_safe_watch_weakref(globals()[_vcls_name])
