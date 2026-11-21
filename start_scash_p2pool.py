#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.3.9).
Publisher: magicalgirlsunite | Community: ScashNetworkCommunity
Compatible with BOTH PyPy 2.7 (bundled runtime) and Python 3.x!
- Wraps stdout/stderr safely on PyPy 2.7 so Unicode strings from Scash Core 30.4.0
  (e.g. u"Loading block index\u2026") NEVER raise UnicodeEncodeError on cp437!
- Includes Win32 Job Object (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) + ConsoleCtrlHandler
  and Linux PR_SET_PDEATHSIG + SIGHUP/SIGTERM handlers for zero-orphan shutdown.
"""
from __future__ import print_function
import argparse
import atexit
import base64
import codecs
import ctypes
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zlib

# Register cp65001 -> utf-8 alias so PyPy 2.7 on Windows UTF-8 consoles never raises LookupError
try:
    codecs.register(lambda n: codecs.lookup("utf-8") if n.lower().replace("-", "").replace("_", "") in ("cp65001", "65001") else None)
except Exception:
    pass


def ascii_safe(val):
    if val is None:
        return ""
    try:
        u = val.decode("utf-8", "replace") if isinstance(val, bytes) else val
        if not isinstance(u, str) and sys.version_info[0] < 3:
            # Python 2 unicode
            u = (
                u.replace(u"\u2026", u"...")
                .replace(u"\u2014", u"--")
                .replace(u"\u2013", u"-")
                .replace(u"\u2022", u"*")
                .replace(u"\u2018", u"'")
                .replace(u"\u2019", u"'")
                .replace(u"\u201c", u'"')
                .replace(u"\u201d", u'"')
            )
            return u.encode("ascii", "replace")
        if sys.version_info[0] >= 3 and isinstance(u, str):
            return (
                u.replace("\u2026", "...")
                .replace("\u2014", "--")
                .replace("\u2013", "-")
                .replace("\u2022", "*")
            )
        return str(u)
    except Exception:
        try:
            return repr(val)
        except Exception:
            return ""


class _SafeConsoleStream(object):
    """Prevents PyPy 2.7 cp437/cp1252 UnicodeEncodeError on any print() call."""
    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        if sys.version_info[0] < 3:
            try:
                if not isinstance(data, bytes):
                    data = (
                        data.replace(u"\u2026", u"...")
                        .replace(u"\u2014", u"--")
                        .replace(u"\u2013", u"-")
                        .replace(u"\u2022", u"*")
                    )
                    enc = getattr(self._inner, "encoding", None) or "ascii"
                    data = data.encode(enc, "replace")
            except Exception:
                try:
                    data = data.encode("ascii", "replace")
                except Exception:
                    pass
        else:
            if isinstance(data, str):
                try:
                    enc = getattr(self._inner, "encoding", None) or "utf-8"
                    data.encode(enc)
                except Exception:
                    data = ascii_safe(data).encode(enc, "replace").decode(enc, "replace")
        return self._inner.write(data)

    def flush(self):
        try:
            return self._inner.flush()
        except Exception:
            pass

    def __getattr__(self, attr):
        return getattr(self._inner, attr)


if not isinstance(sys.stdout, _SafeConsoleStream):
    sys.stdout = _SafeConsoleStream(sys.stdout)
if not isinstance(sys.stderr, _SafeConsoleStream):
    sys.stderr = _SafeConsoleStream(sys.stderr)

try:
    import urllib.request as urllib_req
    import urllib.error as urllib_err
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
except ImportError:
    import urllib2 as urllib_req
    import urllib2 as urllib_err
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from urlparse import urlparse, parse_qs

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ROOT_DIR)
from p2pool import scash_nodes
from p2pool import xmrig_manager

_NO_PROXY_OPENER = urllib_req.build_opener(urllib_req.ProxyHandler({}))

_WIN_JOB_HANDLE = None
_WIN_CTRL_HANDLER = None

# Pre-rendered 80x21 24-bit TrueColor ANSI QtKawaii Wallet Terminal Header (WGL4/CP437 safe)
KAWAII_ANSI_HIRES_ZB64 = (
    "eNrtfUuvZddx3jx/QZOTQQAJBlvr/dAZSbQSCbHINmnDBoQMWtSF2FA/iO6WGAEeCB5n4IFgOIAHgRHkR+Tn8JdkVdV6VNXa+9zbEptNIZZa"
    "Ld7DfffeZ++1qr6q+uqr7/zcl6u75nx18A8+XAP87PzVtn+0z7/6w//46g+///c/3+Cff/rOz83z//Cde1/MP37n5/hRMFdvrik+v1z6L9la"
    "r9bFq4vx+Vf//L/Gxy54Oll0zz/97Mnrzy+P3eOXL59dPrh8cXf3ysFfH3wBH3z3r9/81ydfPnn69PJb88g/qt+7vPV/tvvvl/zw5au7izeP"
    "wiNDhx18rbf6+h6+5zWW5+xk5mpNuXr3fH71GMf/2hP5v5ePf3v36rdP77687CcZH7W/2lVzen7wVf6yfZNfvHzy6peXHxQf4tucRbyEN6+e"
    "vPnN87c4SX9h7f/wl8LbXLnAxdviiKa/ik8ef4hncUdnUS8T/721BU5rSzx8sD+/0Hn/2+Xo1Tzgfa73btvfueKZ9XH/+u824pv9878fuiH5"
    "Zvbw2Vwk/QP9K//8+7M/4xfbYsvXAHv29+pcz9mxtNjaneVrTM/XR/deafyquTp7jZH9qm+7NFxjfZuzva8/B49d3vCfbLrfwipf/oi7Ya82"
    "zGXi69Xba7bsDURzbQasOrYcwM3ZdiFb+r1Y2z4wtq2bwg8Dw+fbJUzth8XQPmgWxonD2t/oOI3vh+V2JjRvXly0/bJt/1/G2eAO4KLFqqW6"
    "vo8tqZ0OlhVfomTgrPF87bVv7q7pcO299VuEhRyvCc9/ecDLOXvF7ebTtwcQ/tN23+9miR6+SQBczT3xV5bSNbVXbDL/rL3d3D4LbEk059/e"
    "bvZriafml/kBBj7KB6by+FYy/OM4w/D78BE3ZnBSN2+YroMrI4d5I6FdNfMDKp6mXyeFa83Xyg0xrPe2/m0o/VYCeGyx65xpQKyY5cbbpqv2"
    "WvmN1HhtR8B2pCOaCWf7ga7UkItNfp3GVthKoaO5eVj717bdhXPDFFRwH0UdVhsSas8wuv7NKtyStVbs7/aJg4vmflA7UTNGtbKD2spqj20c"
    "AadMaH1O3xWYEjAaRrwah3s9yxfYfruIj9pZ2nMK0ki0fZ35R81btm2ayrndYHbUAzQ8PHBcExzvvMBcvRkexrY4bxuiP93m/OPlq//5fy6f"
    "fvjDT39yefzjH3/ywd98/AH8/+XDx397+dlPP/rpR//l8vjjj/+KrriCg3dpH9hDaU899ccwVkdG9J3XRvdyf7VFnxOusrF+2sHW6RVmp7Eg"
    "q5PEJsbFlfspXHte+L9g2DGwodqiT30N1raKAMcrk2Pg38zX3m6nni7jfsIst5RtWN+68XVpawg/3RwvesAQTk0bbBDXDmtWY6znFnBkfghs"
    "VdxmdR4Cj1kYFLhQuxnvx2NZ7+d05aGlswMcNGPUHmrhW7l91CxQObfLpRsgOwxZRVRQvHznNsJ1hh2zFjFEs6H8qETf0cXTizVz3HzNfKtg"
    "C9qLTeokgHmcOT1JW7jtReY0XysCEb52CDsMZ9ROBx6BXwUMcgITjgfUAHfU7luZjAJfnFZ5xRsTy6+Ze3AL3aj0n/hF2ttDILi2UpDOl2/L"
    "wyWbLJy0nP/OhGLgjN4Kdo0vUa/txVZzumvaN2hu6cw2fz0mcrpL2CTNDlj3/IfPnn3w9MUHH7+4u3z08pd3l69+/2+XTz9/8urus8+fPH2B"
    "P6IFffri7tUp8P8mkNYxukFTIlxQf/15GSuj9lhuGASxfuj7AMysd/KQkjFDxNZ1EsAF/g6O5x8KZW6iMGrN1gDGcX6a4PYB7hp+z5A2se01"
    "2dj3Glo5D/hCmPsCu3iY+4MN29YQbIQ88ZZX392D8QdX0kMcD6DNCjsGf+Vlx2yzSBD9eoGQMuwYADx0nnYlsG7ZCLDVTu4R3dEWQ3/Xnik/"
    "JoOraWc3YxPAI5NuEAMsuIthRCC0akZfADu4G+NXuAUxX5HrAnxPYY/Ywx6Ym5kWagQrML1L2+vtd6p4wBkcygDFzciisRauMBLE6sYqoa8U"
    "FtGiRbzxEsljDS+BYExFtIADyoLEDjBt0DDWtSu1qJQtUdfXX9A4f6FU9FBRv0swj4Xth7JF2X3X9RtquwXQTHmYoRSugl7IA4J/fNS0PcQG"
    "QCMqjilqA2QIvHaA+vWY2If/55uynMe5BghgDIZV+1vsm6jZLghavAD4iVz8WFEZYyi58NpdpzBSwfQrXnq+tqKjmz6/fRTMDDZ6DrxtowAB"
    "zDkYRC8GKethPBr2vQaBC2gT9y9sKKoLyo45ZscqQo/2tbyIUSOlfAZ4TRHtlJEBIcbkNuZpgNpuy05hJTPXJsVwIl5s528H5DKtT1usAufA"
    "dzFw0+O5+rwdgCddZ2g/8V1IHwGGu7DfynAibvbYnc1LVfjowmJ/gwH+9DRZIn5A8WbiT3LDCjtWck88TyGPUL6+gtWRgX9bAvBSzTmGZeWH"
    "/pINefYWWHELl8DCDasc8Y8IcSjYre4cLOPrGEnGgPmSUm/FFCr4r/BE3hpcTkN3ih3ZMV4e03+tzmMg0AvS/ZINzQdWly3rlY/qP7ntDKle"
    "2TXFAcqwY149+Vvf5WuCwbqE1FYo4Mn3mMGcWctxu+8PcZ8mNhVoApOH3mRsHsiJYeJc7GVM0QH4sDPb7TEAdVYYfsiTY0auny0Z2EgzJTbS"
    "Hu3pjBVlqwE74KzKjACQHHu+/Qh3JTIFttlxSAMMcwl3ZhNkBwX8LJh+dMObNUSOV5P5x3bX7UbtcDYecKbMdDZH5sALrl1Q5XMkaDl8Yo9b"
    "ojLuYZoo2CYtkKlqo6Xpm6MjcxnUKfLyD6Xb/d2DlHkXZ0dUlY/M09F44Wj4iYS3U74qb+5wOJ2ZhcWF5uRLdvgOh8n1Oj9Bqe55G/CM60yc"
    "eu6ZrHRUTh0CJ+m2n3Kc0v0nxPWwDKYL9cq5S/jV7qho9EXW90YGCeMsg/tj4pW2oiRcCYWilu5VMtyvtUFabKweLaxe5UJKmJLJ8TCLe5zy"
    "i/B2Sr2dc4HQx/dLnQUBeMh4BoGQ4U0vSv6C+x+vHBQ5vnoecCXyWaJgYtQ6q6sUQh7Mbgtx3gP95NUBaVV16KewJ9LY5o67F/UrcAFD2kwO"
    "X2Bgca/HePmbcZqH+SVk8/zglGHiHvlH5vJdxvn5nlgP63Lc771v73jsGwusnexvLVawlGmBRDR6oiJswXU4dFULWluZxIFMCNaJXV2pQysX"
    "Pawkg375PHzCeH05tma0klPJIAvpISDpzKOaX86QXJERUvO28JbswOGIBxKkvTQEaMib1c4N+DMnfJSlCoSzI8aEKiLWLqRvcMy9QG7pdvBA"
    "y1VYZAgEwP+nfpJ2v7kokxzRJI+IC1L3UF8Qex8yJ3VFu5C6hwKKPE2E9zjzJ3DFDN6CnyZiimW8MIhH4JCsdrid6fh8NTLaJdM5L1IxkLfR"
    "Sp/LH1uF6p2qLbT3AXFsmLwF0yuXcnFh+m9VprD8KZJPiQe7R6Uc+r6jBoMvIwN2lNWQFBFL0nUigjgZ4iOsmpgnEFj0+jWDwRjPBQ2AfC6E"
    "ICd8S1jAsgIHAiRiBazmIuH2rcxCVkyDzuUCp4W947eVO1IsORC0yLcqske2JqLTdreDxZXhS3EiS4df5CS+OrmaRawZFLAq05AdmReohoNV"
    "MfI5A0wW72e7lCYiUM56uOfu7r1yjRIBaN+Ji2SeIfSo9zQCTdsZIsK+kavogMGrKlZY6B0rvuUAInhxibBDhCAOiDtEEN9C3MMABVdGWUvu"
    "vcbRJyWnX71ckIDTXV/99++/RljwXfOfLshj/c93d9/T6/nbiQlO0tTovpPOJLlpsjqJ7TwfUtHkgWfg3qJiaXgER5C3BMckqGptc0azisQd"
    "WQvT2KJdeCez2txWEFg1Weky5COnQwaKSsS4nx+FmWDw+HVlAZqRtCLva6nSYMcqn8F0VtAFbOKk613LVeSXCybLmmVZLgqOtjItAZ4jwg2N"
    "kAseBgSAks9nK52gDKPtidkj0xJwCKKuuK4JLybtZqaweq6TWzzRgzN52bosuU60dW64zeZ32/qpZtEDsFxuJC8L4+DAw1VxFUA1mcW8dU/O"
    "RnJ381Yx5S3YXW09QX46r2+bJSVpsyUUm0xuA1ZCFbct4DlH8QxvUxYOEgEpN1BDIKZDUP4iTtcE7DNkUQgoCpuB5QVgbQArxGdZHKhUEBsI"
    "0meZE6Y4edwulD2qug7kMLA2OqvVWXLxzlK8DDhG+YwcPgIWzrZ7F6jJo18eCQCs4EB9u9wTl0DyaX1VSIY7XWFtv7PosS0qqF6RaCGg8fPS"
    "8OXNTcpD2IN1j16rCGdvVZKkLtpUD7zVGbyIxYPkCN+Th3cWDC5GV5yqSaGaXmfyQirxHbAaP6tceMBWz8/zuxxlJjKeNO1oKIqrCpjQ/f5C"
    "AUYSrdTXLZAojf69JwoeP/ndhaECKNkAI8y4522bNjTw+K8++vTyDxcGDP58UUFADoAkpaXu5uPMJrQ9KJkQ6KeE57tCjlQR5MxKMx+x0Dxt"
    "3RnSVmLBBkXXA9/trDSzwjwWT/AizcqAdYqVAaw6lso4uhuLvsqx1RolbnbICJnVo7olcB2y6oF8kxbnIimfgGApY24h9FIr8EOqSvTDrbJC"
    "ocVoX0TyQMqMK/S9l37d3mIz+2xztSUVozTYyLeAjMnkLMLixxcj8xWFOIg3CHuY7q6s8K4oyQGNDq8hBGVe0OLMWLHebz0ReAJWiGYVW5DQ"
    "JGh+fa2uSL5KZk32hI3Gg203PimZrDJk8XoL/FiViMciDjxLz54lmBgrcRZ4/8D425jCglURsqanB0ZiglcE68Sq1ABmWsxKNVXFFwdOz+LK"
    "d1Kkctp+RX8AT8KkDT04K+CRaSGIrB7ZkuINBjz/KT9ymLEaMGfScDQ7sOArVNl1IB3no1rBcSYOUV1RPv3ED14YtF6gp3ted54ksLzWfVRs"
    "7wxZs+HGkV6DpX/aYrOIxJGoWGGldmSsR07/hof3nJF/nLgEWkCQ7MRIfMEwnSh6/XMzlOwOX7a6fZBfdyYQLt+u9MHf3f2CAQXm0D9/8+aL"
    "H3z/+20bPzLtvxabZr//+s2TN08/+/63Cif41YwRDXd90Wx1qRjPt8WGKlI4Y5AwB8CyTGWjz/beknplneOyZYdcp+M9BzWc48u6MTED2ou5"
    "0Q5QQQInPpnpxIQq5iZlJG8sS17HxnYDSZWigvNCW3BA2XmwkVsUaXLMPXXFzeTELG06mcKwFSXc5BnR7hcZb8y0ZIcdANOZNogvrmz6MdGx"
    "oAZ/KerUDn66XBfa84dHS+DoG5zQdHxW7ASECLx/QYa4YnmqZ8l7Y5T4ltTRZRZd10HGAgsrwkH7Xg5LhXVtuqSS95C3gcoVINKeFfC4vqx1"
    "Ki+CsLtXpzI1Y8jmMGSS1HDjrQdqPRMcgoYYYNeN3+udEuIesU4PsCRPRwnwzd1sSwF3j92mkySBnkFGodACVGf1A1gEMmOkEo6WMgZGUDwq"
    "dre4c9AwPDkcqZg4cTGDPcLfrNg8yayIFnsOZWdNxOTMzFJiEi8pwo+yOtCrKPs5vKFCCMecHfP5uBqBymwQ79g8SfogspaSLpoVSpAkfwMG"
    "wWWw3ugWNaNoGil818CykQ2AxqxqazlRoW9kuPBrWFW5Jf5lcjdzCzp1QrjK33AxmASLVd6NdzPFBXVp3FgC0thKr21xxFyPo27QPZFDk8LN"
    "OlUkbxUFVkyHFER0jpPA4WSfHNrUa1zsCsiJhPeeE4Gum+NKyWsSBvmLN5/tkOe95kSO5BwCajSE2+QgqL0bN6ri7GV67XcxBzAzgAURSlSN"
    "yYwmXTfX3gvpLOmgEvU9Co5X1hx92xB3OKHoznYDVhNwZLyrIE2sr/hLp/AOIy3Vp2TnOe+FINRVBIkcCRbA5A8HUTDNm7V1wxSyWckTk1Vu"
    "Cu0oVVjG3UKhqKi2oZKuhWc5oLQsiQOR2CbTBGIAv9Va6DDIh22fQtYwG/7LYJ39dljCraYO26+REIuwvAx2ZKrlNgrixMDM8i1Rw8mAFdD2"
    "Ca2wIlqrxMqY6Q/wMlBiUpyX9mcSvEzC1JesnRXksS3XgBH7zYULt5XWhaF/ISu67fjMSpKFSl/w6jZ1SeXT1gXofXZXXTrIKyjw+F3FrobE"
    "JxYhBokGXY9MomBBLZaHSiNgXJHvafqEqErlJD065RE6Ix4xmsaUqNo581DIiMYVL1VH+qeD7oyBPNB0xBYFZgy4y0l59r6fTOXuGM8DbD/w"
    "sJxTeZKwGqRSorZrJ3tv8Cmmhz7Fgn7a3OIZRDSiUsMAkYSgJ1AnsPD4FLglxaWCZuy8SmpVbTd5exhpCDQCJw3wqMZ+RHwsMT7s0sGkclAj"
    "SUm9E9gPUGO20/pGXKDOq7v1a1m3NYwnzqobHX51dA5BPRfaU4Lb0Nw4DfQdqqAbNqVbtKKD9Fa7cDLTV2C3JAjhiOXYfHA1LLMEeUzkBCrd"
    "D+QerejT30oAECYWMhTgycw9S+Y9FaHc48sx4MKiEymqXf7h0nXM4Gf/notQo+sUIdY1aAWsh4Xx0VKIxSN/izwCoXl1ANu6ckzm8UFRfHTM"
    "vayacFGcByQuc3a1ZgVQJ1wQqZqbNFsKnQXBwco12psLomjGyzIXQKQIjujEEWCM8yFLfhp3Km3N/YQwo/itD8VjYWqSSxBiQFAnq0TtBWMa"
    "Z2STJzEoSzuAjdezjzxSYUsYQIwwWY0EkyaJaNkK/kBq3lWFxIo+DBsnhwubH0ju2YRxXkgDEuza4FrcrpDRuqpzycN8F/RhZyNqstXqH27Z"
    "20rKPdJYWuyiH1i2dwXpehyYz+oWV5bKqKru5ZAHVDBj0d9u6kpfokCJipRx1QAhom/LUyBAlePwtG/2pKbjyVuZFu1QLizZC6t68jubMiys"
    "X1V9ovAOd6jMZBV/Fd4qSfBYsEC6tFQ+UQlaOCTovGbl1BZ4EFVmMCDkcCgo4Ka9gfyiZAQjFCPJhtn0Dp3GLhrFYKW3FyZtG2XcBBMPH2dd"
    "rT/tkQJSE480UDvpSJHAJjaYh9uUeqZY1MBmivu0ulAyys3IEDNj4t6ODrsciQ+gY+PVF5crhQtF4oS48BUyo6zi+7cHEe18wbYL4zgh2gLU"
    "QscYVoaUb2xUpPf2Z2TpMciECrzYitT4NRVkKkmKqXwYPizOzTOK4W2xl3pZGhTog5eguI4WrfZsZEANDgwoVUAM79gJpUC4b5nJJzmfucgC"
    "IS6dF0ZG/7QhWHF2QWk0jOb1NGxI6P5AyptZ3Pt2IFuwl9i6aOS9F7eo7phgdCrwrch3mvE+pgyQZZEVvbQwKp4lAr/M4iNDBN7F7FjL/RWr"
    "te/dzFViywGyIQ5EPZe8x2lG6R3Cw7+5e/JccpRQry2l58+f/OrpZ0+e/erpq2evf/Pi6Zu7Qzrft6b2SJpM0w80Cw4xrWzDyTLxDYGLcypW"
    "RJZQWCVwjyqHOd/TB0j8h8Cb/IqqWXg3KZyk2VH2HOAMArGhsYYddUbRXRpvZvCw1Da9FsaI1e7OtYhT3igpdoSpuExlKUDQXUuyk+8FOXtl"
    "gbNkh8OeCmkZlozwXXJlkPQSF3mVPnCqloWfBmwSYodFr3Yx/XJmtbhIFTdpYgndRnUY2IT9orD4Zp4GPwDrZu4DfWif054uzIio2GFmq3S6"
    "AZbHYa6XEzexCLyGSD5iYL9907TyMfSBU94Ny6uYbg388VoV27tA5KFJ66PXYnRHFXwKSfLEzwZhflIdz7CVz3NgFGDN6nuiVLiyxovES50v"
    "Eh0PHns9RJGnxANWhox4maoyU97fko4UTKlRaesdwqryFevkWpVAWRqv1TvhUQ5IlknAUxaDEy/0loC1O59k+TAxyprteMd5keFLlGzpnwqh"
    "Qqy0hpsHv43G82xCyxSAscWkJXos0ixZ2dyg7KwMACFuLZYVzRPhHFVoNMh6MjPmcKpACM4aK5YPzk28C9f9yd0XrOmIzz/AVM5Hd2++fPnq"
    "1x++fP4c3Pfvvr2ue1cNtJM2dJqkIRlQz2tPMvtuSTNxVZqCzOJQ91A1gsCY9va1uqpyVmVxulzRIjeofIpyn1Ix6KT3H5unBgzA1Llqy8si"
    "dUSJJJ1bqqtWmDdJJXjAdYkyeQ4kZv/vavFAzWMjE1yQrUf8PLppIK+IVFaRfJ1OJHntfDbHiHyWoPxn3M9mtUuauZnIS1pGi6GXThNxbm39"
    "GjRZAaIsQICDseIc9ZtZQWlCN1gC59oWyncIri19U7/konMX79puv7JAaN7+9i0hTHzAI8pBZ66M5hgN+BPY2Rzy0oV/tvQV5+ujXqV0znCA"
    "MM9sZBlI2eTTTQInjWiuTxueVY6n7zt/swtHt7ui/HNZYrfhJsdP9jCeMoqhpWH56lsCCbNekvcua+g7CCzaLz1gFsF3zSTqaVl3uVP7jWJ7"
    "x6pqyEgBgxqVT66ZJYsSJlD/GBd9MsICg+QspUQBoiiXnbE25GxcqYmgO+YxaxhYvO2pb0CmbAe1Zhk9fxU0b/BrGF+/u+LLW2skvudOnuOF"
    "j25OCkxSaTuI7KhXOtc5MGdg+vCJ7FR1Mbu10Z0l6XoZiHhPmqrM+aSqeSdZ1ELAchrJBB/CemYlbHVmkTDcBOfgfc7l5liVsGbheXXHvJs2"
    "hmazFCUSyWWXAIE4xeOR5jTzUGZGN042uGCEijyYgWr9VYmmUxSYV0EmIorYvDCFmeM0sTeeWHdYHClL/xddk4zXAep0byo7gERaBKsNlqU6"
    "pyeSFRmgz8C64IUb9M2CkgGKsRR3Z3XYQX3HsbAeZ6ccxcRUuIo8hS3pOWiJAs/CXpPs7aYO4Om3HV9ox+xyZ3aF1wVEYRkqRDfEWFiAG5Xi"
    "11BfCXO4w0ar7ayxvNaeV6oUlat5xbgP8uh5r+FWekE+6X4tIciKsew577XT++Np49AqE/q6+n3dJgHWwBhGe2b1Nmu2NNKsjV9NddgcVRUW"
    "w8JI5dQVg4ZNNetjPCx8LLT0sZh5fY4O8nhuG0yAuHx4+WH7+yc4D+Kh55cOGb6YDdxxgZgbCCor3cPEeGrwD1XjEADQgFfXIwpI8FBFKzSU"
    "c7vWQJNAqiy62TLFbImuGuI7DKL/8J4UMP/l2+Xvh4df2Q0lf4pvOC8K/gwqqhbbwvbdKcjlaNKFCs96H6WdEztiLy/lzasA7p1lfou8P6m1"
    "gWiW6VslBPVVd6iX5aR79+hN2ohIYUMpWGXfevk43lTbyytRQH01WseKpdUGf2SznLNHBkuacmjOnimADtBZUUgFNaBuGNKETZzSkg2m1mwt"
    "DT2pHnQVrr2byRkFf+2qUq6kwGYG4RA6ej2EAPt9A9PaTtRn69WsohxmvARLLJdbICmSAIu9zQ2K+FqzKvq7NXpgzxorv9zxonKYbC6D2WYT"
    "UNOroJkG5ZdHa7dfPDid2w2Ib29Qovt9BC4aKofZuEoStAMhZtJcSdt+jqsxGH8pAiawimmAaYfZ6xQp8yEuCF98CWGXRLnodDPcPu3KllKa"
    "S9OjkoCNVypC0K4x6Em1p6lkWsaSjlfySwuAyjJqqWIlYpJXMJGnxH8SsgWlE3ZfYyANuLpGjKdnLR0kiWSJx+Lyx36ylYxzupbeJ1wMIFpJ"
    "ES7ave17VsmNoRJBkQO3wG2nP4NhAkNchsOMW7n68yYFpeXvkSA8B/z0SR1SngEZNJlzOBLtMWERq+iNRLFNNTZgOsZFEgcqkjDjUPgBADWy"
    "fp27XjclXlXJVR6I55XRqpRwqx3Nmb17dLEe79eRyPTYAs+HexrGoKNqvzLiedPT6GE0S8OrUV2O2msir4MX3RIH72Yqa1VKbVvROAftd3XB"
    "IjKo20A+fDlTjwKYe26jtTg3yqEzm1eITSNLvFhGTSsbjfodcAsimoXfg//Nk5GCtFLhSv2KwwNgDCOWCI4doHPNblEcriK/IKibOYawkSFu"
    "kzosEXyLi7mPhNCqlcqgTzKvZGWu9wgUdD0te0pZoETv8rnDBR8Ue8P1bMLqoevfx9RNccRAS1Q8cE+dlnblzr2aGQIeqPJeZSw8q1QFErpw"
    "KSwCu9NFkET7uczqdVITJ2mcRVkUQgjd432trxFrbGlhabVvUk9mL83amLfCdE9ODTAAsy+9un1cmY7NPUHGBg4cccrdQmzH3W1OX2feGqJF"
    "I/LWAVepHIGFNhlt7NwCBb+UBFSGsNzSnY1I4hNbvCLlZ+nBekqHBKmOhpExl/n5E+JkGH/24yevf3fxH3z65u6Ly6dvnrx684P3Ns9HVImm"
    "BEPcRpwlHHFW2eC+eKsCRGZCYlLiP9UrG3xX69YFMkxWT9/6DdUyLSLIw4VdrChzEUIZuZDXTMuu3GfvEL7Cfp9WuVTE8XoObMY2wdV1hSSB"
    "7TBLE6BnmyCyuyERJERtbbv52XqRUZFfkuR6r+d5K3YvrqfzbgVSr/Y3xLxJenNtMjA1MJlJijDBjFzL5+SiW/ZHz8eyqbwYsySv4pZO5MQu"
    "sxFc5m1SbuqTsFe7XMVHJDlQtgstjfWCRePgNk4tQYqJ3QZxx+tn4ZjBKaT9FfQ4EhrXF1c3BeTNZYnQ0eRPz/S/zbI4p63AfF2nvYZbqPG/"
    "CPqUVYP8MJ88MzcpapVLVOe5gR9h1a+MB3XACwRD3MJV9jHolqMqHS2taiDiRdW8hi+jlJtDW2uafnhEohQBVNW6yUwabigB7TvnPDxYDAc3"
    "3YaNFzHMoy6qwA90jYmGMk2GFBN3MxHz/TokFvnQiI65xqpiUiDphZxIhk90OUOLiZNqMJb0Tiej2yLxRpEWfR3l4lsRLSQhABvN3uCKs2I0"
    "IMfUyLotR3Iq6qhErszkVYNHW5PVbMfquA3BtKBqe+kCwJ7XlnBpyzGRmB6ZCn9oHMzGacvInHBzKTpKxh2U0QNW3NaAS7B1knCfPeYqlh9B"
    "uKEQVkF9oJlvAGAGkE6CY9MpffM5UAOzyuhCLokc0AheqIVecLKpMJH5uUgpSbJfcJgovy+HzcqyVR4rf5764Ccsw+Yu2Z+ccb1PzT3EX2Bf"
    "jQpNQmImPo4JUFraCAkLYU0NxbWlRinhKN5VV0WB5qRql2CJU1l5cjwCCThFbZ/K5+VYUpIJugMDOreGSwHrXJUddLxhmKbBHFEcA4+A/vTq"
    "DG8/tY8uj5+8fnN3QX10++jRo8uXT549u3tzefri8otXL798fffq8rc/vbyfEb1MUm4N14SnpqR+YEXGNQSLMrFxm3BbgszvOjWK1K1EUZca"
    "SPfpTgeuKg33oPqzvJu3RT+VunMXpfx/uTHd6QqIWokXmLDUUnF8iw2aK4xDXbgVWHhNaTE7Xp/ckgoM1Eb9y0Oeag4scUQHlG1CvheSmcsu"
    "qmMt2vtgrQQYA+XKl4l8lfNzVJqqNYXM4MVnndGzfbr8iNgrprbrNmE5umXJIKMbZIUiJj7DFge5OKWUhdr367kgb8PpHsuAmt0rSIX2Nac6"
    "UAHIzli3Ii9WygH3XsM1z4loH4I2guVbN4UoMNKG3VAkG5CpDFpU55JNlSShMIMLkoVSTaPRLMJSwilTigtgSRR38lwyrgzFbje2x1TDq0JN"
    "PugVqgpxNJXHHNQYz5X36BWslWe22JJkIUbINQgeWea9Ql3pmh4jm1MCR0+sHozTLUKIyKg8c+YjUHUYTgXnzKXJ49ZoGN1IFy7skPSA00oA"
    "Y2VHASqBdZBxGA6pTYzVgAOCkoqeAIkh7M8cvoKFkDRiwBOwVqSAzpb7CagPYAtnNWFDaVK54hiYZo+ju5MVNxT29cyE0itWDU2GpnxPqGgx"
    "fa/zbL0Hcn1J28dcyQ5OqCRzKWFSqcnb2ajjYBXSHBaJZUuJ9UVW27ynLVPUu4ysuQsPwolbTkEk2DlrZAWFNrLV0+KcQiR4TauHzVlW87Yw"
    "EZIUkNpF3izWBuZRRatNkYC5Z+NEvKcZFtvK8Y7dPRbfnW6uD4Uq8PN5wXPBec1myy6Etfgr1aEkzxeAJuo9u5V71fdVaejByC9C57FyRpUm"
    "cqxahcXfsEr1PNcVIkIYodXC+jCJmXWn+Yq6hQfdiF+l7Bg37Y3g+Ewh0NcpKs+QltYPmIOrzN4GgWy/puYdNgbQPbp8+OzpZ7+m1OrlR795"
    "+uzNBw3T/v3PPnn6q8ubl5fnT1/c/cfLOwK2J73FC70zfxMLPyCep1NJWUJsxkyCULaIKcn+VJMu4ftWrft9qJRQrdOs/VVFio7SUBvOLZ6X"
    "astBu4wRgy79rYncUeMs2EHIP50bl7RbdRR+iHTDQaJBId1wCIjdQLr8sP1sQR92eFFEyGXNe8fpR0ZftJZh5ZceWb4prAq7FWY6+H3q71TT"
    "heOTyvN5s5iavUCnO7WhMrLGGIZ83VtumWYi/ayEnx3qzV2z48c4Ka8BVokpwRWcE7Mp8IFlmiF3Jj5j0SE+ajYE/iuSEepIPWGOKsQWw7J1"
    "+Ti3yE/QsqIQmIvki+W1zAFrwC6BDvo5ya+uX6Wn1a8mOLpFGh7cOtUbsGQlO9KOaval4+gF/B+wqp3szcdsf9LrXRefCxY550QRSuIbpWLT"
    "RzycR2Aw6TDh8wk8mFZfay1RCNq121QNw73WE6TqSGCRYK9Li9JeoiyWW5ScsqWjrSO76Vj9F5XOqlbHdo7BUvByINUvY71eSJq4FM9mdRM9"
    "zlsRjzmTeTOywk1dazOgQ9sRnGL4z7YC1pmcg3qas6mgWlkFqduZ2MAmIAs4PVEUs84eZbSZSLm0Lwh7IVqYLSTEjRIQKyNjvq6yNc2zkaux"
    "xAWMKlXzxUiZTgxiEle1M9IkZO2SO4HNpMWieHQq3Vgd018xeJeyV67iMN717hzlQEV8VWSSgsLfor48EcxHuSklGedRL8RkHHgUt0zqGqs5"
    "NuNVxMLIjmT2FmLUFZSMfNJxBEE6YVxI7Key3kLVBJwqhdqrMQLuScXVaY0uxDGiKlOKGHQYf5CPUzOBmj3mB6CvyoqREteklIA1J5nQIDGl"
    "NaoMVQ2Vx1xqMo6629zW0svgHAxReweTsln3uQeU+/L13eXLpy9++fLLy3f//nuXJy9+9+bp8zvAuK/fvPzi8uTZs3eKcjuuXZrMUaFchCJc"
    "1yspKEKzSurcwFgMyJtE1UrOFtIGVBkPuzxt3STMuup9FH1jRkm/lHmG3rxa90skccBNUjvNrvZseKUlh2DlhCj0slZXz3eYGUc2lpn6CKW3"
    "stXiBRpNGGmrNpOtZI+zOO2W7HUTGK+ul6J+FW8iK50z2PZ14RZyquD5RPIFa6EzxWGJvy7bgWBF5TW/6URXxK3mZ3tP4p6oQ2vuLqG3fAAD"
    "bWDNiR5Tp1mPhQK+blIAOElOPrIXRlRuyKluvXB8VJGjxLis5YXeCqWRdJDjr5NjMo0Fri1WGyYtGhTgRbWqWaaRBGh5Nz9OmrAqL1MYsMci"
    "olcXQ3q/3JbbXMay2PuWxkVqkQNY+WPz195dLQvanoawuZH7yJRk8V4iTuxRWMJTWQM9VOS9NXul32Faq1GBfsyCL+47Nc7JFk9cwvMatmt3"
    "ykWPpfa6BLCm5uSBSlFclchzzSPSF7daStNLsBDdeudgp1BWrRyIFriRzYJli4KBTkkcYoZunqscAGEw8zatwRW292AoHAyGCgTJw+KlRbNr"
    "E8S6nnpyOybNhVr3lyA5jgyP6t3llU0h0CHCCSgs+UWxAd10q6o01LFgFs85qs0FR1TWOJ3JTCpubCqMQoMjEYua15sSJwMBdgkqpA4iaVNl"
    "RA1QtwTB0UWAtJU7cuRj/8TupcxQymKtO8V8iaspq5KWuGqrWYWIiKmiokoZqNa5PL+aVQAVl8DhBdxD2qBhWXPevRL39FR7W0PgonIFHqUh"
    "WGtZVM/SZ8Lu07BU3bDtcSnM+h6mPvV4WZ5SNdsgT4fM39kpVfYDSH1h8oOgSp5UzhUR6eyBxiG/52KI4U8UQ/wmu0x4ijU9l/LVU4bFkkVT"
    "sKqXiFbRJpKsp7NB+yF8JJlFhwAa3abJ49jgqKF64Lam20lKO8iXUnJOSFfL1BLK52YxVyYfiF8zx3sfKCI+e1yzdCqZMes1cYeSmGGaL4Tr"
    "ypFQXXwUbZEzrIq22NfAByCNJIgkmxcsyC2oCd8Voavsh4u9dcSx0hUepjRK8VuOqk7BDlzNLnZxzhCjn2TOkx4sk4ayirIBN7h2uohEbsBR"
    "oKckNhfA6DQqZhwjE7IjPJ023MZmpOFwM43JCqblVlHXYF4362GnZs3dcJ14WDaxQt6z23+WciPAb1pzAXEHGjVXHCt3Zg2fh/eNs+eU2jWo"
    "FISl9IQCfCoTRgSNyeWrfleYXsCXJM6krBd+Og09zfgOMiNT6gIRiFZwRRW9tD2LjwBXJLnOsGkbU3XsfSI0l5Teq5/ToyjOkFRb5McloR8V"
    "VX+PQ91hK4vlOFw3pkMFL6O1rfImt04A86KVPISCJMpp+YPM4VK3hK8LpXc1uqTbHbsIEF6Lz4z+Ir8esFGJyt5eswYeIgXXKX0au0ZSFuzG"
    "NQo5MKRGNFFpqCu8nplVwIZeOYI24AF+AqCg4htf6XdE4koNcw9rfCxNm8uKZxNWmSZg2VWL2oa0TFaGRycsEhyguTlYghmpR/gdp7YKApB5"
    "VSSpaLlM+cW8nmFraYLKGt2jgRuh2vMp34AnV/LAU0Yu7dOPrThAVU7CUowPNOwkqekmq1/lWPYUp5aotrS6obtoeP5SpycBdS7hFI8wLas2"
    "d2pMHc8bH430O3xsBL6xpNpewpor6suWp3WhTyA6osJ/HQnMb77tOGKfFuONAJlbUmNS7q0eq48Ysy9BkbsRTvjAijEoK1828McLQAcdNb63"
    "Eo1pEugotsmVrNQJaECtsP6R57MUJMYgwBcWhbYDlQVbzE2mKUTiypXb3t8cJsHGIqwzmoZDvs+vFFTx173BB1KNvOxJPVZZXxGbd1Zth3Ke"
    "gvTSmTmRTY5FUpFO3kbDVYC9HqYGz9Qu0U/nCG+VcwqhdwQnzmfO2C0NLeFjV7+4IatBo5qdEhqgQQFhsPKrnvRtCEG5JTME6g9RdcYCgpJn"
    "xkrQXFYGtYklwKSkQWQgCw6JitQFZx5m21S6F31xfn+Zxj0dnMXLQ5xi25W0YUKrRNmKY6lOFKsVXgiq5ZLKpOkAvY1/pmKc2owFB0mUwJpV"
    "SWhbi6sXwwYnDxlyua+xzTRogdGkBUZRdeZhiq6VTXReh+1acv5Ii5yAnp6hs0UcNFlnHBa6WrsGoTT3OMxKrh7vFRHKTHFQTKnUg9EfbrGx"
    "i552kvs0lbI2MRUmVK0wsGJ+TITydGNkXtCw4r14lX/LC4AG1PEQNU1wsH7FEpR2UhSdEPkBWpG/p4Ti6RkcjchbTwwazlVfBKS+Mk+eZY1f"
    "mRTQYbdfUDaufzGlSRdWYDWA3X1icT1XVxWqHN11TLoVsp/nygA+cwgWVpuBhj+eSSMdCGNg+77Kr6+M5uXrnSA3R4pCSPL7f7v87NNPLn9x"
    "+bunLz55+uJXBhvEV0vOj+4++9w7KRz+Diq5qGU1WtMKTWPVZFZP+3hEwMhIkAs/565KvaC/Uzlbj+Sg4kWTt2a4G8FJtLdoU10kPO19rPm0"
    "INwPiOISBxjK32rHKQrc1Y4VJ/M1jFFh8UiRO5rb4yCo+VDoSKOkhVLIGkPoeaUSSo6y4Gs9KYgv8SmlT+qnuNMAgNJTIkhbARmQkYD8c/6A"
    "UqCoRFFeF7UuIA4TMXdvzmcAycpKf/sOsI+XoIerV9XNiBMQJjXPocS4fAEAHTKDDiSPFfQhYR1iUfJKqqsa7DlLljVNKu7DxC0LxgC/wRzA"
    "GLfm7+5IpwMkhnSimmBmkgBDFjtvklaowq/AZj3BuGW3i8Ek1uRg5eD64LQOWr21M7GPWz/8Sgy1cB4lYfEx8/QYUlijog+wGc58YEo6HPQX"
    "NV7a1HLXLtQzX9Ih5Cladj9vu7cwkbbY036y2be3sk1+AAzu2rpAXeI4wKVtBAJ7J70fzktWQLarU75LJDulKIcE5cqon4DWnNUJ0rQmtEXq"
    "b5WVkphogJef/f9a2MejlxmIGQ5QkjaexkasRO2GEypignxLjQ8jvAXr96IfJqTWPehITQsCB79jjCyFQyLdVjpFPpeVcXM3REemfljY2BKe"
    "mQoxy+Y0RFWK2rB+lMpf/0h8OYp6svy+wFvg7CDsYrpuXXaeC5R9LS3LfK4KQKO/fPrq7rM3lx89e/nZrz/7/MnTF5fHT3738jdvXl+++9HL"
    "y09ePvvl9y7vvLcj6s5sQTeg3PHgo3QSXFVCGl7Np90Up/PK2ZB0R7xnGBKbb9ZbC9N5+qHuaaDCYdPASBtsKqKpJZ/rneLQREWRoDqF1Y15"
    "eckXb0HtZTP4YkJW1ZFvSGpOGRLvoqIVKim8K+jVi+Ij/OvZtwvJJ4l2wDulxfgErJZVRQ7C58xINaR6mcqpMB5S4JQDwOa3lQ/M96BhqvNL"
    "imFGVmW+McI+UO4yr9l3wOxJWjDP1FkVOBJLscRuWSQiSy0X8m4p/ucZA6ssHSYM7Apu50Gbi4USZGKqxsdnWiNQEQ+q+a+QykwsZ9WHH6jk"
    "LlAR800BWLt6YXDAqwI+m56dHnawjxXA4AF1BfONV9fz2kuh0BG1bZNzSSxRepScxloxm98YN7Zluea54MeANrNbmHJTJ5epb+1Kz91sraQF"
    "EgRV5wgbMhnC1v/sPZd7oI41laeePeN5zr1FGSZV40oLZWAHAY5k1VpGTAoRfYIMZUnko97w2aOot/hFdmPQ483OzjHAD9CXI6AkaWRMUf9E"
    "jSEy8DZ8yJ3D0mJKD5/nHrD39/bAywEwuFTojRR3H9KqWuRhPPAaJh1Ujyr01cdZlUthPyDysitZmnLupWhLyHpb5VoAwW3SHN19n8cwvdy4"
    "2gHaKUUoBY9mPagjsqkjqL8elLnqgTtuSUIE4IYrIfYgDijbAXAPZqb8/Z7yQFXp2cnbAV9RGjVR8P/DnwtpjCs7liufUJS3wR+syux0szNB"
    "t8wbA9L5YiMEJVACzaXlQ+7aOzGqkL0sEewwv8v+Wg4R0C3eKjzZlZM72flzqoqeT1bqfVFznwV3c2LNit3FYZ4C+HWY6WPpvKogYjnXMsUq"
    "UMfPqnPATHBgMTC50V4N7hOgWlCaV3VxJ5zpbVgHxazMhmwZxabAyhozFpCs8ZJzBaTqnNkhYUtJpSLr8yRWdmuKjae+Nxk0ADa2yuc2j0CU"
    "U9k56zaB86i6Wb1GZJ0UFhQiSxtsY5ZvHLRju7XviP+m+B2E7QyDkqdnYi0kkbQvZGbXIdtl5m0d9rgqKI9d8rM86oihLRttDS65suiDWVFs"
    "k24w0CA7CmYngUSz46csdvrBSIV6n3UISgPAagNkZdYVM0hioKXM2XjurAo6FalxCN893mquGJiZm+KkdQTyasEqWy0WmoTzSnR1US+h90K6"
    "mzM9BY9G2dLa23hZuiyoMDl4mmQqfEJ+OI4i2JtUOgk+ihLQ+cw7DsFvGOneczmMx9ZYlWgf4Iw8vxFUdhJmJVPL7ODIwKu2KkUtz4pxg1jX"
    "pDg0Wfh5SywET4tuAY0iv2xE1lRZ0901oSwZcQBO4MiqrSKk1WaKjDOpdFH4zNWj+BZ7PgXLSpEosDcJVLYK44mDzXVBTTcuYQJUbG7UQlFb"
    "uAjGXyVjoYpWZzIHDlAUSLcq6sfdTH7FYh3HqGwP5SPmS0kTw0q898cUQ9/XLKjDuVBfQ+NB5gOEwTSZ1XeNmrYbHpvO/KBtlhplvVAcL5tR"
    "V2dIm6eYXJ3RHKHlJaP8YhL+EGY6UulhmvFmkXVxuCBWQbchfmYjrPijibg0BEZjRHN4tqQRp9M1JJyvW9WsS6+GCLhFsoZvDK9Phki2XJdi"
    "KwpmS3jnSOLEMuxmFaWexnltDZX+oOty0e79QTrLU21lfXeaGCRrFwabW5eAfqJeATmOiDgwq6pIoHTD9nxAZ4hHfanYvqbgnKbej/aFdC8w"
    "5DHz6HnYzsQyKvPMt7olxpn3g/x+T1nIPw/4aFlAsn09T50U81SeZAJlMNG1AxOfEGQU/rMkBZb5RrHhFsqHrqSoiStolqM73bh968tsZtwP"
    "0OYiL3NxYLKwRCH1rELaiK3JbaHvfJkHZg5R3niR2VJ77Q1HuX/ZPsy+3ndf6SgHwO9L2428dk/c8wZkn+P5O9gq5cr8Ut6fdfTBA1dsCjjA"
    "rftWg837AVYcoGR6mIM/OANEOXl9i/0ejrLaIR2pXkhVAZQWN+H0wPGQbV1f8HDJ2awfUdrzVzfkKegAuarD1q2nxt3jR2x7Hf9OELcVH/jU"
    "ugmHY+RJUVFEPnzkVk0H3UX15Pv1LKzFxxmUmBNS0oN5qx1lxKrANRLqw3Dh2/3npIL7IHz2bcCX/1/9+Rd8Mf8PtBBl8A=="
)
KAWAII_ANSI_BANNER_ZB64 = (
    "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"
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.3.9)          Core 30.4.0 |
| [ > Overview ]  [ Stratum :8345 ]  [ P2Pool :8344 ]  [ Scash RPC :8342 ]     |
+------------------------------------------------------------------------------+
|  * SCASH PEER-TO-PEER MINING POOL (Sovereign Node + Sharechain + CPU Miner)  |
|  +------------------------------------------------------------------------+  |
|  | Core  : Scash 2.3.0 (Core 30.4.0)   | UI   : http://127.0.0.1:8345/    |  |
|  | Algo  : rx/scash (0% Pool Fee)      | Mine : stratum+tcp://127.0.0.1   |  |
|  | Team  : magicalgirlsunite           | Repo : ScashNetworkCommunity     |  |
|  +------------------------------------------------------------------------+  |
+------------------------------------------------------------------------------+"""


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def setup_win32_kill_on_close_job():
    global _WIN_JOB_HANDLE
    if platform.system() != "Windows":
        return None
    if _WIN_JOB_HANDLE is not None:
        return _WIN_JOB_HANDLE
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        k32.SetHandleInformation.restype = ctypes.c_int
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        k32.SetInformationJobObject.restype = ctypes.c_int
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.AssignProcessToJobObject.restype = ctypes.c_int
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p

        h_job = k32.CreateJobObjectW(None, None)
        if not h_job:
            return None
        HANDLE_FLAG_INHERIT = 0x00000001
        k32.SetHandleInformation(h_job, HANDLE_FLAG_INHERIT, 0)

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        if not k32.SetInformationJobObject(h_job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            return None

        k32.AssignProcessToJobObject(h_job, k32.GetCurrentProcess())
        _WIN_JOB_HANDLE = h_job
        return h_job
    except Exception:
        return None


def assign_popen_to_win32_job(proc):
    if platform.system() != "Windows" or _WIN_JOB_HANDLE is None or proc is None:
        return
    try:
        k32 = ctypes.windll.kernel32
        h_proc = getattr(proc, "_handle", None)
        if h_proc:
            k32.AssignProcessToJobObject(ctypes.c_void_p(_WIN_JOB_HANDLE), ctypes.c_void_p(int(h_proc)))
    except Exception:
        pass


def _make_linux_pdeathsig_preexec():
    if not platform.system().startswith("Linux"):
        return None

    def _preexec():
        try:
            libc = ctypes.CDLL("libc.so.6")
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
        except Exception:
            pass

    return _preexec


class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class _CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", _COORD),
        ("dwCursorPosition", _COORD),
        ("wAttributes", ctypes.c_uint16),
        ("srWindow", _SMALL_RECT),
        ("dwMaximumWindowSize", _COORD),
    ]


def _ensure_wide_console_and_get_cols(target_cols=128, target_rows=42):
    cols = 80
    if platform.system() == "Windows":
        try:
            k32 = ctypes.windll.kernel32
            # Disable Windows Console QuickEdit Mode (0x0040) so clicking inside the terminal never pauses P2Pool in 'Select ...' mode!
            h_in = k32.GetStdHandle(-10)
            m_in = ctypes.c_uint32(0)
            if h_in and h_in != -1 and k32.GetConsoleMode(h_in, ctypes.byref(m_in)):
                k32.SetConsoleMode(h_in, ctypes.c_uint32((int(m_in.value) & ~0x0040) | 0x0080))
            h_out = k32.GetStdHandle(-11)
            csbi = _CONSOLE_SCREEN_BUFFER_INFO()
            if h_out and h_out != -1 and k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(csbi)):
                cur_w = int(csbi.srWindow.Right - csbi.srWindow.Left + 1)
                cur_h = int(csbi.srWindow.Bottom - csbi.srWindow.Top + 1)
                max_w = int(csbi.dwMaximumWindowSize.X) or target_cols
                max_h = int(csbi.dwMaximumWindowSize.Y) or target_rows
                want_w = min(target_cols, max_w - 2) if max_w > 84 else target_cols
                want_h = min(target_rows, max_h - 2) if max_h > 28 else target_rows
                if cur_w < 124 and want_w >= 124:
                    new_buf = _COORD(max(int(csbi.dwSize.X), want_w), max(int(csbi.dwSize.Y), want_h, 300))
                    k32.SetConsoleScreenBufferSize(h_out, new_buf)
                    rect = _SMALL_RECT(0, 0, want_w - 1, max(cur_h, want_h) - 1)
                    k32.SetConsoleWindowInfo(h_out, 1, ctypes.byref(rect))
                if k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(csbi)):
                    cols = int(csbi.srWindow.Right - csbi.srWindow.Left + 1)
        except Exception:
            pass
        if cols < 124 and os.environ.get("WT_SESSION"):
            try:
                os.write(1, b"\x1b[8;42;128t")
                cols = 128
            except Exception:
                pass
        return cols

    try:
        import fcntl, struct, termios
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            rc = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"1234"))
            cols = int(rc[1]) or 80
            if cols < 124 and "xterm" in os.environ.get("TERM", "").lower():
                os.write(1, b"\x1b[8;42;128t")
                time.sleep(0.08)
                rc2 = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"1234"))
                if int(rc2[1]) >= 124:
                    cols = int(rc2[1])
    except Exception:
        try:
            cols = int(os.environ.get("COLUMNS", "80"))
        except Exception:
            cols = 80
    return cols


def print_kawaii_terminal_banner(force_ascii=False):
    if force_ascii or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        print(KAWAII_ASCII_FALLBACK)
        return False

    term_cols = _ensure_wide_console_and_get_cols(128, 42)
    chosen_b64 = KAWAII_ANSI_HIRES_ZB64 if term_cols >= 124 else KAWAII_ANSI_BANNER_ZB64

    try:
        raw_utf8 = zlib.decompress(base64.b64decode(chosen_b64.encode("ascii")))
        u_banner = raw_utf8.decode("utf-8")
    except Exception:
        print(KAWAII_ASCII_FALLBACK)
        return False

    is_win = platform.system() == "Windows"
    if is_win:
        try:
            k32 = ctypes.windll.kernel32
            h_out = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32(0)
            if h_out and h_out != -1 and k32.GetConsoleMode(h_out, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                if k32.SetConsoleMode(h_out, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                    written = ctypes.c_uint32(0)
                    k32.WriteConsoleW(h_out, ctypes.c_wchar_p(u_banner), len(u_banner), ctypes.byref(written), None)
                    return True
        except Exception:
            pass
        if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or "xterm" in os.environ.get("TERM", "").lower():
            try:
                os.write(1, raw_utf8)
                return True
            except Exception:
                pass
        print(KAWAII_ASCII_FALLBACK)
        return False

    try:
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            os.write(1, raw_utf8)
            return True
    except Exception:
        pass

    print(KAWAII_ASCII_FALLBACK)
    return False


def is_port_open(host, port, timeout=1.2):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        s.close()
        return True
    except Exception:
        return False


def jsonrpc_call(host, port, user, password, method, params=None, timeout=5.0):
    url = "http://%s:%d/" % (host, int(port))
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": "scash-launcher",
        "method": method,
        "params": params or [],
    }).encode("utf-8")
    auth_raw = ("%s:%s" % (user, password)).encode("utf-8")
    auth_hdr = "Basic " + base64.b64encode(auth_raw).decode("ascii")
    req = urllib_req.Request(url, payload, {
        "Content-Type": "application/json",
        "Authorization": auth_hdr,
    })
    try:
        resp = _NO_PROXY_OPENER.open(req, timeout=timeout)
        body = json.loads(resp.read().decode("utf-8", "replace"))
        if body.get("error") is not None:
            return False, None, body.get("error")
        return True, body.get("result"), None
    except urllib_err.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8", "replace"))
            err_obj = err_body.get("error") or {"code": e.code, "message": str(e)}
            return False, None, err_obj
        except Exception:
            return False, None, {"code": e.code, "message": str(e)}
    except Exception as e:
        return False, None, {"code": -999, "message": str(e)}


def is_mainnet_node_synced(bc_info, net_info=None, allow_unsynced=False):
    if not isinstance(bc_info, dict):
        return False
    if allow_unsynced:
        return True
    chain = bc_info.get("chain", "scash")
    blks = int(bc_info.get("blocks", 0))
    hdrs = int(bc_info.get("headers", 0))
    ibd = bool(bc_info.get("initialblockdownload", True))
    peers = int((net_info or {}).get("connections", 0)) if isinstance(net_info, dict) else 0

    if chain in ("scash", "main"):
        if hdrs <= 0 or blks <= 0:
            return False
        if ibd:
            return False
        if blks < hdrs - 1:
            return False
        if peers <= 0 and blks < 100000:
            return False
        return True

    return (not ibd) and blks >= hdrs


def open_dashboard_browser(url):
    if platform.system().startswith("Linux"):
        disp = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        if not disp:
            return False
        devnull = open(os.devnull, "wb")
        sudo_user = os.environ.get("SUDO_USER", "").strip()
        try:
            if hasattr(os, "geteuid") and os.geteuid() == 0 and sudo_user and sudo_user != "root":
                subprocess.Popen(["sudo", "-u", sudo_user, "xdg-open", url], stdout=devnull, stderr=devnull)
                return True
            subprocess.Popen(["xdg-open", url], stdout=devnull, stderr=devnull)
            return True
        except Exception:
            pass
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def probe_working_credentials(host, port, datadirs, conf_user, conf_pass, rpc_timeout=12.0):
    candidates = [(conf_user, conf_pass)]
    for dd in datadirs:
        cu, cp = scash_nodes.read_cookie_credentials(dd)
        if cu and cp and (cu, cp) not in candidates:
            candidates.insert(0, (cu, cp))
        fu, fp = scash_nodes.read_conf_credentials(dd)
        if fu and fp and (fu, fp) not in candidates:
            candidates.append((fu, fp))
    last_err = {"code": -999, "message": "RPC unreachable"}
    for u, pw in candidates:
        ok, res, err = jsonrpc_call(host, port, u, pw, "getblockchaininfo", timeout=rpc_timeout)
        if ok or (err and err.get("code") not in (401, 403, -999)):
            return u, pw, ok, res, err
        if err:
            last_err = err
    return conf_user, conf_pass, False, None, last_err


def _cleanup_stale_linux_processes(rpc_port, all_datadirs, conf_user, conf_pass):
    my_pid = os.getpid()
    my_ppid = os.getppid() if hasattr(os, "getppid") else -1
    stale_launcher_pids = []
    stale_miner_pids = []
    stale_scashd_pids = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid in (my_pid, my_ppid, 1):
                continue
            try:
                raw_cmd = open("/proc/%d/cmdline" % pid, "rb").read()
                parts = [p.decode("utf-8", "replace") for p in raw_cmd.split(b"\x00") if p]
                if not parts:
                    continue
                joined = " ".join(parts)
                low = joined.lower()
                bn0 = os.path.basename(parts[0]).lower()
                if ("start_scash_p2pool.py" in low or "run_p2pool.py" in low) and "grep" not in bn0:
                    stale_launcher_pids.append(pid)
                elif bn0 in ("xmrigminer", "xmrigdaemon") and ("p2pool" in low or "127.0.0.1:8345" in low or "--daemonized" in low):
                    stale_miner_pids.append(pid)
                elif bn0 == "scashd" and ("scash-p2pool" in low or "/node/scashd" in low or "node_data" in low):
                    stale_scashd_pids.append(pid)
            except Exception:
                continue
    except Exception:
        return

    if not (stale_launcher_pids or stale_miner_pids or stale_scashd_pids):
        return

    print("[1/3] Stopping leftover background P2Pool process from previous Linux session...")
    for pid in stale_launcher_pids + stale_miner_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    if stale_scashd_pids:
        u, pw, ok, _, err = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass, rpc_timeout=3.0)
        if ok or (err and err.get("code") != -999):
            jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=2.5)
        for pid in stale_scashd_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        for _ in range(15):
            if not any(os.path.exists("/proc/%d" % p) for p in stale_scashd_pids):
                break
            time.sleep(0.4)

    for _ in range(8):
        if not any(os.path.exists("/proc/%d" % p) for p in (stale_launcher_pids + stale_miner_pids)):
            break
        time.sleep(0.25)

    for pid in stale_launcher_pids + stale_miner_pids:
        if os.path.exists("/proc/%d" % pid):
            try:
                os.kill(pid, getattr(signal, "SIGKILL", 9))
            except Exception:
                pass

    for _ in range(16):
        if (not is_port_open("127.0.0.1", 8345, timeout=0.25)) and (not is_port_open("127.0.0.1", 8344, timeout=0.25)):
            break
        time.sleep(0.3)

    if is_port_open("127.0.0.1", 8344, timeout=0.25):
        print("[Notice] Port 8344 is still held by another user/root process! Run: sudo ./stop-scash-p2pool-linux.sh")


def cleanup_stale_p2pool_processes(rpc_port, all_datadirs, conf_user, conf_pass, primary_datadir):
    if platform.system() != "Windows":
        _cleanup_stale_linux_processes(rpc_port, all_datadirs, conf_user, conf_pass)
        return
    try:
        ps_cmd = (
            "Get-Process scashd,xmrigMiner,xmrigDaemon -ErrorAction SilentlyContinue | "
            "Select-Object Id,ProcessName,Path | ConvertTo-Json -Compress"
        )
        CREATE_NO_WINDOW = 0x08000000
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            creationflags=CREATE_NO_WINDOW,
        ).decode("utf-8", "replace").strip()
        if not raw:
            return
        parsed = json.loads(raw)
        procs = parsed if isinstance(parsed, list) else [parsed]
        stale_pids = []
        has_stale_scashd = False
        for item in procs:
            if not isinstance(item, dict):
                continue
            pid = item.get("Id")
            pname = (item.get("ProcessName") or "").lower()
            ppath = (item.get("Path") or "").lower()
            if pname in ("xmrigminer", "xmrigdaemon"):
                if "p2pool" in ppath or not ppath:
                    stale_pids.append((pid, pname))
            elif pname == "scashd":
                if ("p2pool" in ppath) or ("\\node\\scashd.exe" in ppath):
                    has_stale_scashd = True
                    stale_pids.append((pid, pname))

        if not has_stale_scashd and any((x.get("ProcessName") or "").lower() == "scashd" for x in procs if isinstance(x, dict)):
            u, pw, ok, info, _ = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass)
            if ok and isinstance(info, dict) and int(info.get("blocks", 0)) == 0 and scash_nodes._has_blocks_dir(primary_datadir):
                has_stale_scashd = True
                for item in procs:
                    if isinstance(item, dict) and (item.get("ProcessName") or "").lower() == "scashd":
                        stale_pids.append((item.get("Id"), "scashd"))

        if not stale_pids:
            return

        print("[1/3] Detected leftover background process from previous P2Pool session -- stopping cleanly...")
        if has_stale_scashd:
            u, pw, ok, _, err = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass)
            if ok or (err and err.get("code") != -999):
                jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=2.5)
                for _ in range(12):
                    if not is_port_open("127.0.0.1", rpc_port, timeout=0.4):
                        break
                    time.sleep(0.4)

        for pid, _ in stale_pids:
            if pid:
                subprocess.call(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=open(os.devnull, "wb"),
                    stderr=open(os.devnull, "wb"),
                    creationflags=CREATE_NO_WINDOW,
                )
        time.sleep(0.5)
    except Exception:
        pass


def find_scashd_binary(custom_bin=None):
    if custom_bin and os.path.isfile(custom_bin):
        return os.path.abspath(custom_bin)
    is_win = platform.system() == "Windows"
    daemon_names = ["scashd.exe"] if is_win else ["scashd"]
    search_dirs = [
        os.path.join(ROOT_DIR, "node"),
        os.path.join(ROOT_DIR, "bin"),
        ROOT_DIR,
    ]
    if is_win:
        for env_k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_k, "")
            if base:
                search_dirs.append(os.path.join(base, "Scash", "daemon"))
                search_dirs.append(os.path.join(base, "Scash"))
    else:
        search_dirs.extend([
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
            "/usr/bin",
        ])
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p:
            search_dirs.append(p)

    for name in daemon_names:
        for d in search_dirs:
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return os.path.abspath(cand)
    return None


def _lower_win32_process_priority(proc_obj):
    """Lowers background node/P2Pool processes to BELOW_NORMAL_PRIORITY_CLASS on Windows after sync so XMRig gets 100% physical-core priority."""
    if platform.system() != "Windows" or proc_obj is None:
        return
    try:
        pid = getattr(proc_obj, "pid", None)
        if not pid:
            return
        PROCESS_SET_INFORMATION = 0x0200
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, int(pid))
        if h_proc:
            try:
                ctypes.windll.kernel32.SetPriorityClass(h_proc, BELOW_NORMAL_PRIORITY_CLASS)
            finally:
                ctypes.windll.kernel32.CloseHandle(h_proc)
    except Exception:
        pass


def ensure_windows_p2p_firewall_rule(p2p_port=8344):
    """When elevated on Windows, allow inbound TCP/UDP :8344 so P2Pool LAN & mesh peers connect cleanly."""
    if platform.system() != "Windows":
        return
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            return
        CREATE_NO_WINDOW = 0x08000000
        devnull = open(os.devnull, "wb")
        for proto in ("TCP", "UDP"):
            rule_name = "Scash P2Pool P2P %s %d" % (proto, int(p2p_port))
            chk = subprocess.call(
                ["netsh", "advfirewall", "firewall", "show", "rule", "name=%s" % rule_name],
                stdout=devnull,
                stderr=devnull,
                creationflags=CREATE_NO_WINDOW,
            )
            if chk != 0:
                subprocess.call(
                    [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        "name=%s" % rule_name,
                        "dir=in", "action=allow",
                        "protocol=%s" % proto,
                        "localport=%d" % int(p2p_port),
                        "profile=any",
                    ],
                    stdout=devnull,
                    stderr=devnull,
                    creationflags=CREATE_NO_WINDOW,
                )
    except Exception:
        pass


def start_bundled_scashd(scashd_bin, datadir, rpc_port=8342, p2p_port=None):
    cmd = [
        scashd_bin,
        "-datadir=%s" % datadir,
        "-chain=scash",
        "-server=1",
        "-listen=1",
        "-dnsseed=1",
        "-uacomment=p2pool",
        "-rpcport=%d" % int(rpc_port),
        "-rpcbind=127.0.0.1",
        "-rpcallowip=127.0.0.1",
    ]
    if p2p_port is not None:
        cmd.append("-port=%d" % int(p2p_port))
    for peer in scash_nodes.DEFAULT_SCASH_ADDNODES[:8]:
        cmd.append("-addnode=%s" % peer)
    if platform.system() != "Windows":
        cmd.append("-daemon=0")
    kwargs = {}
    if platform.system() == "Windows":
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NO_WINDOW
    else:
        preexec = _make_linux_pdeathsig_preexec()
        if preexec is not None:
            kwargs["preexec_fn"] = preexec
    devnull = open(os.devnull, "wb")
    kwargs["stdout"] = devnull
    kwargs["stderr"] = devnull
    proc = subprocess.Popen(cmd, **kwargs)
    assign_popen_to_win32_job(proc)
    return proc


def kick_peer_connections(host, port, user, pw):
    for peer in scash_nodes.DEFAULT_SCASH_ADDNODES:
        jsonrpc_call(host, port, user, pw, "addnode", [peer, "add"], timeout=1.5)
        jsonrpc_call(host, port, user, pw, "addnode", [peer, "onetry"], timeout=1.5)


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def make_sync_handler(sync_state, ctrl):
    web_static_dir = os.path.join(ROOT_DIR, "web-static")

    class SyncHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send_json(self, obj, code=200):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/":
                self.send_response(302)
                self.send_header("Location", "/static/")
                self.send_header("Connection", "close")
                self.end_headers()
                return

            if path == "/node_sync_status":
                self._send_json(sync_state)
                return

            if path == "/local_stats":
                self._send_json({"syncing": True, "p2pool_ready": False}, code=503)
                return

            if path == "/miner_status":
                st = ctrl.get_status()
                st["node_syncing"] = True
                self._send_json(st)
                return

            if path == "/miner_start":
                w = qs.get("wallet", [None])[0]
                t = qs.get("threads", [None])[0]
                wk = qs.get("worker", [None])[0]
                lp = qs.get("large_pages", [None])[0]
                ctrl.save_wallet_settings(w if w is not None else ctrl.wallet, threads=t, worker=wk, large_pages=lp)
                st = ctrl.get_status()
                st["running"] = False
                st["queued_after_sync"] = True
                st["node_syncing"] = True
                self._send_json(st)
                return

            if path == "/miner_stop":
                self._send_json(ctrl.stop_mining())
                return

            if path == "/nodes_list":
                self._send_json({
                    "addnodes": scash_nodes.DEFAULT_SCASH_ADDNODES,
                    "dns_seeds": scash_nodes.DEFAULT_DNS_SEEDS,
                })
                return

            if path == "/pool_telemetry":
                self._send_json({
                    "ok": True,
                    "syncing": True,
                    "version": "0.3.9",
                    "hashrates": {
                        "local_live_hs": 0.0, "local_10s_hs": 0.0, "local_60s_hs": 0.0, "local_30m_hs": 0.0,
                        "pool_live_hs": 0.0, "pool_10s_hs": 0.0, "pool_60s_hs": 0.0, "pool_30m_hs": 0.0,
                    },
                    "ledger": {
                        "wallet": ctrl.wallet or "",
                        "miner_scash_7d": 0.0, "miner_scash_30d": 0.0, "miner_scash_all_time": 0.0,
                        "miner_blocks_paid": 0, "pool_blocks_7d": 0, "pool_blocks_30d": 0,
                        "pool_blocks_all_time": 0, "pool_scash_all_time": 0.0,
                        "backfill_scanning": True, "recent_blocks": [],
                    },
                    "market": {
                        "ok": False,
                        "weighted_price_usd": None,
                        "block_value_usd": None,
                        "total_liquidity_usd": 0.0,
                        "total_volume_24h_usd": 0.0,
                        "exchanges": [
                            {"key": "ourbit", "name": "Ourbit", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://www.ourbit.com/exchange/SCASH_USDT"},
                            {"key": "nonkyc", "name": "NonKYC", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://nonkyc.io/market/SCASH_USDT"},
                            {"key": "nestex", "name": "NestEx", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://trade.nestex.one/spot/SCASH"},
                        ],
                        "reference_links": [
                            {"name": "Ourbit", "url": "https://www.ourbit.com/exchange/SCASH_USDT"},
                            {"name": "NonKYC", "url": "https://nonkyc.io/market/SCASH_USDT"},
                            {"name": "NestEx", "url": "https://trade.nestex.one/spot/SCASH"},
                            {"name": "CoinGecko", "url": "https://www.coingecko.com/en/coins/satoshi-cash-network"},
                        ],
                    },
                    "explorers": {
                        "active_key": "scash_network",
                        "active_name": "explorer.scash.network",
                        "active_url": "https://explorer.scash.network/",
                        "checked_at": 0,
                        "items": [
                            {"key": "scash_network", "name": "explorer.scash.network", "short": "scash.network", "home_url": "https://explorer.scash.network/", "block_tpl": "https://explorer.scash.network/block/{id}/20/1", "address_tpl": "https://explorer.scash.network/address/{id}/20/1", "online": True},
                            {"key": "scash_tv", "name": "scash.tv", "short": "scash.tv", "home_url": "https://scash.tv/", "block_tpl": "https://scash.tv/block/{id}", "address_tpl": "https://scash.tv/address/{id}", "online": True},
                            {"key": "local_node", "name": "Local Scash Node", "short": "Local Coinbase", "home_url": "/local_explorer", "block_tpl": "/local_explorer?block={id}", "address_tpl": "/local_explorer?address={id}", "online": True},
                        ],
                    },
                })
                return

            if path in ("/explorer_go", "/local_explorer"):
                qtype = (qs.get("type", [None])[0] or ("address" if qs.get("address") else "block")).strip().lower()
                qid = (qs.get("id", [None])[0] or qs.get("block", [None])[0] or qs.get("address", [None])[0] or "").strip()
                if qtype == "address" and qid:
                    qid = qid.split(".")[0]
                    dest_u = "https://explorer.scash.network/address/%s/20/1" % qid
                elif qid and len(qid) == 64:
                    dest_u = "https://explorer.scash.network/block/%s/20/1" % qid
                else:
                    dest_u = "https://explorer.scash.network/"
                self.send_response(302)
                self.send_header("Location", dest_u)
                self.end_headers()
                return

            if path.startswith("/static"):
                rel = path[len("/static"):].lstrip("/") or "index.html"
                fp = os.path.abspath(os.path.join(web_static_dir, rel))
                if fp.startswith(os.path.abspath(web_static_dir)) and os.path.isfile(fp):
                    ext = os.path.splitext(fp)[1].lower()
                    ctype = "text/html; charset=utf-8"
                    if ext == ".js":
                        ctype = "application/javascript"
                    elif ext == ".css":
                        ctype = "text/css"
                    elif ext == ".svg":
                        ctype = "image/svg+xml"
                    elif ext == ".png":
                        ctype = "image/png"
                    elif ext == ".webp":
                        ctype = "image/webp"
                    raw = open(fp, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

            self.send_response(404)
            self.send_header("Connection", "close")
            self.end_headers()

    return SyncHTTPHandler


def main():
    global _WIN_CTRL_HANDLER
    parser = argparse.ArgumentParser(description="One-Click Scash Node + P2Pool + Launcher")
    parser.add_argument("--wallet", default=None, help="Optional scash1... wallet address")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads for local mining")
    parser.add_argument("--peer", action="append", default=[], help="Additional P2Pool peer address (host:8344)")
    parser.add_argument("--scashd-bin", default=None, help="Custom path to scashd binary")
    parser.add_argument("--datadir", default=None, help="Custom Scash Core data directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--no-banner", action="store_true", help="Skip QtKawaii terminal header")
    parser.add_argument("--allow-unsynced", action="store_true", help="Start P2Pool without waiting for Mainnet block sync")
    args, unknown = parser.parse_known_args()

    setup_win32_kill_on_close_job()

    if not args.no_banner:
        print_kawaii_terminal_banner()
        print("")

    ctrl = xmrig_manager.GLOBAL_XMRIG
    if args.wallet:
        ctrl.save_wallet_settings(args.wallet, threads=args.threads)
    elif args.threads:
        ctrl.save_wallet_settings(ctrl.wallet, threads=args.threads)

    primary_datadir = args.datadir or scash_nodes.get_scash_datadir()
    conf_path, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=primary_datadir)
    print("[1/3] Configured scash.conf with active Scash peers:", ascii_safe(conf_path))

    active_datadir = primary_datadir
    all_datadirs = scash_nodes.get_candidate_datadirs(primary_datadir)
    spawned_proc = [None]
    p2pool_proc = [None]
    active_creds = [rpc_user, rpc_pass, rpc_port]
    shutting_down = [False]

    def _graceful_shutdown_all():
        if shutting_down[0]:
            return
        shutting_down[0] = True
        try:
            _NO_PROXY_OPENER.open("http://127.0.0.1:8345/miner_stop", timeout=0.8).read()
        except Exception:
            pass
        try:
            ctrl.stop_mining()
        except Exception:
            pass
        if p2pool_proc[0] is not None and p2pool_proc[0].poll() is None:
            try:
                p2pool_proc[0].terminate()
            except Exception:
                pass
        if spawned_proc[0] is not None and spawned_proc[0].poll() is None:
            try:
                print("\n[Shutdown] Stopping bundled Scash Core 30.4 node cleanly...")
            except Exception:
                pass
            jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "stop", timeout=2.0)
            for _ in range(15):
                if spawned_proc[0].poll() is not None:
                    break
                time.sleep(0.2)
            if spawned_proc[0].poll() is None:
                try:
                    spawned_proc[0].terminate()
                except Exception:
                    pass

    atexit.register(_graceful_shutdown_all)

    if platform.system() == "Windows":
        try:
            CTRL_HANDLER_FUNC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint32)

            def _win_ctrl_cb(ctrl_type):
                if ctrl_type in (0, 1, 2, 5, 6):
                    _graceful_shutdown_all()
                    if ctrl_type in (2, 5, 6):
                        os._exit(0)
                    return 1
                return 0

            _WIN_CTRL_HANDLER = CTRL_HANDLER_FUNC(_win_ctrl_cb)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_WIN_CTRL_HANDLER, 1)
        except Exception:
            pass
    else:
        def _posix_sig_handler(signum, frame):
            _graceful_shutdown_all()
            sys.exit(0)

        for sig_name in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig_val = getattr(signal, sig_name, None)
            if sig_val is not None:
                try:
                    signal.signal(sig_val, _posix_sig_handler)
                except Exception:
                    pass

    cleanup_stale_p2pool_processes(rpc_port, all_datadirs, rpc_user, rpc_pass, primary_datadir)

    u, pw, ok, info, err = probe_working_credentials(
        "127.0.0.1", rpc_port, all_datadirs, rpc_user, rpc_pass, rpc_timeout=12.0
    )
    if (not ok) and (not err or err.get("code") == -999) and is_port_open("127.0.0.1", rpc_port, timeout=1.0):
        print("[1/3] Local Scash node on 127.0.0.1:%d is busy verifying headers -- waiting for RPC..." % rpc_port)
        u, pw, ok, info, err = probe_working_credentials(
            "127.0.0.1", rpc_port, all_datadirs, rpc_user, rpc_pass, rpc_timeout=20.0
        )
    if ok or (err and err.get("code") != -999):
        active_creds[0], active_creds[1] = u, pw
        print("[1/3] Connected to running local Scash node on 127.0.0.1:%d." % rpc_port)
    else:
        scashd_bin = find_scashd_binary(args.scashd_bin)
        if not scashd_bin:
            print("[ERROR] Bundled scashd binary not found and 127.0.0.1:%d is offline." % rpc_port)
            sys.exit(1)

        print("[1/3] Spinning up bundled local Scash Core 30.4 node (%s)..." % ascii_safe(os.path.basename(scashd_bin)))
        proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
        spawned_proc[0] = proc

        connected = False
        used_fallback = False
        for _ in range(120):
            if shutting_down[0]:
                sys.exit(0)
            if proc.poll() is not None and not used_fallback:
                used_fallback = True
                fallback_dd = os.path.join(ROOT_DIR, "node_data")
                print("[1/3] Notice: %s is currently locked by an open Scash-Qt Wallet window." % ascii_safe(primary_datadir))
                print("      Tip: Restart Scash-Qt Wallet once (or close it before launching P2Pool)")
                print("      to share your existing synced Scash blocks immediately without re-syncing!")
                print("      Spinning up dedicated P2Pool Scash node in:", ascii_safe(fallback_dd))
                active_datadir = fallback_dd
                _, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=active_datadir)
                active_creds = [rpc_user, rpc_pass, rpc_port]
                proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
                spawned_proc[0] = proc
                time.sleep(1.5)
            u, pw, ok, info, err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir] + all_datadirs, active_creds[0], active_creds[1]
            )
            if ok or (err and err.get("code") != -999):
                active_creds[0], active_creds[1] = u, pw
                connected = True
                break
            time.sleep(0.5)

        if not connected:
            print("[ERROR] Local Scash node did not open RPC port 127.0.0.1:%d." % active_creds[2])
            print("        Check debug.log in:", ascii_safe(active_datadir))
            sys.exit(1)

    ui_url = "http://127.0.0.1:8345/static/"
    browser_opened = [False]

    _, init_bc, _ = jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "getblockchaininfo", timeout=4.0)
    _, init_net, _ = jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "getnetworkinfo", timeout=4.0)
    already_synced = is_mainnet_node_synced(init_bc, init_net, allow_unsynced=args.allow_unsynced)
    if already_synced:
        gbt_ok, gbt_res, _ = jsonrpc_call(
            "127.0.0.1", active_creds[2], active_creds[0], active_creds[1],
            "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}], timeout=5.0
        )
        already_synced = bool(gbt_ok and isinstance(gbt_res, dict))

    if not already_synced:
        sync_state = {
            "syncing": True,
            "p2pool_ready": False,
            "blocks": 0,
            "headers": 0,
            "progress_pct": 0.0,
            "connections": 0,
            "datadir": active_datadir,
            "status_text": "Connecting to Scash Mainnet peers on :8343...",
        }
        sync_srv = None
        try:
            sync_srv = _ReusableHTTPServer(("127.0.0.1", 8345), make_sync_handler(sync_state, ctrl))
            srv_thread = threading.Thread(target=sync_srv.serve_forever)
            srv_thread.daemon = True
            srv_thread.start()
            print("[2/3] QtKawaii Sync Dashboard live at:", ui_url)
        except Exception as e:
            print("[2/3] Note: Port 8345 already active:", ascii_safe(e))
        if (not args.no_browser) and (not browser_opened[0]) and is_port_open("127.0.0.1", 8345, timeout=1.0):
            if open_dashboard_browser(ui_url):
                browser_opened[0] = True

        print("      Waiting for local Scash node to finish syncing before starting P2Pool sharechain...")
        last_kick = 0.0
        synced_height = 0
        while not shutting_down[0]:
            u, pw, bc_ok, bc_info, bc_err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir] + all_datadirs, active_creds[0], active_creds[1], rpc_timeout=15.0
            )
            active_creds[0], active_creds[1] = u, pw
            _, net_info, _ = jsonrpc_call(
                "127.0.0.1", active_creds[2], u, pw, "getnetworkinfo", timeout=8.0
            )
            peers = int((net_info or {}).get("connections", 0)) if isinstance(net_info, dict) else 0
            subver = ascii_safe((net_info or {}).get("subversion", "/Scash:30.4.0/")) if isinstance(net_info, dict) else "/Scash:30.4.0/"

            if peers == 0 and (time.time() - last_kick) >= 15.0:
                last_kick = time.time()
                t_kick = threading.Thread(target=kick_peer_connections, args=("127.0.0.1", active_creds[2], u, pw))
                t_kick.daemon = True
                t_kick.start()

            if bc_ok and isinstance(bc_info, dict):
                blks = int(bc_info.get("blocks", 0))
                hdrs = int(bc_info.get("headers", 0))
                pct = round((100.0 * blks / hdrs), 1) if hdrs > 0 else 0.0
                if hdrs == 0 and peers == 0:
                    msg = "Connecting to Scash Mainnet peers on :8343... (Peers: 0 - discovering network headers)"
                elif hdrs == 0:
                    msg = "Connected to %d Scash peer(s) - downloading block headers..." % peers
                else:
                    msg = "Syncing Scash blockchain: %d / %d blocks (%.1f%%) | Peers: %d" % (blks, hdrs, pct, peers)
                sync_state.update({
                    "syncing": True,
                    "p2pool_ready": False,
                    "blocks": blks,
                    "headers": hdrs,
                    "progress_pct": pct,
                    "connections": peers,
                    "subversion": subver,
                    "bestblockhash": bc_info.get("bestblockhash", ""),
                    "datadir": active_datadir,
                    "status_text": msg,
                })
                print("      [Scash Node]", ascii_safe(msg))
                if is_mainnet_node_synced(bc_info, net_info, allow_unsynced=args.allow_unsynced):
                    gbt_ok2, gbt_res2, _ = jsonrpc_call(
                        "127.0.0.1", active_creds[2], u, pw,
                        "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}], timeout=5.0
                    )
                    if gbt_ok2 and isinstance(gbt_res2, dict):
                        synced_height = blks
                        break
            else:
                prev_hdrs = int(sync_state.get("headers", 0))
                prev_blks = int(sync_state.get("blocks", 0))
                if prev_hdrs > 0 and is_port_open("127.0.0.1", active_creds[2], timeout=0.8):
                    busy_msg = "Verifying RandomX block headers... (%d / %d blocks, headers: %d)" % (prev_blks, prev_hdrs, prev_hdrs)
                    sync_state["status_text"] = busy_msg
                    print("      [Scash Node]", busy_msg)
                else:
                    raw_warm = (bc_err or {}).get("message", "Starting Scash node...")
                    warm_msg = ascii_safe(raw_warm)
                    sync_state.update({
                        "syncing": True,
                        "p2pool_ready": False,
                        "datadir": active_datadir,
                        "status_text": "Scash node warming up: %s" % warm_msg,
                    })
                    print("      [Scash Node] Warming up:", warm_msg)

            for _ in range(10):
                if shutting_down[0]:
                    break
                time.sleep(0.5)

        if sync_srv is not None:
            sync_srv.shutdown()
            sync_srv.server_close()
            for _ in range(15):
                if not is_port_open("127.0.0.1", 8345, timeout=0.25):
                    break
                time.sleep(0.2)
        if shutting_down[0]:
            sys.exit(0)
        print("[2/3] Local Scash node is synced at block #%d and serving SegWit block templates!" % synced_height)
    else:
        print("[2/3] Local Scash node is already synced at block #%d!" % int((init_bc or {}).get("blocks", 0)))

    ctrl._load_saved_wallet()
    # Internal fallback address ONLY for run_p2pool.py's required -a flag if user hasn't saved their own wallet yet
    node_fallback_wallet = ctrl.wallet
    if not node_fallback_wallet:
        from p2pool.bitcoin import bech32_scash as _fb_b32
        _fb_file = os.path.join(ROOT_DIR, "miner", "node_bootstrap_addr.txt")
        if os.path.isfile(_fb_file):
            try:
                node_fallback_wallet = open(_fb_file, "r").read().strip()
            except Exception:
                node_fallback_wallet = ""
        if not (node_fallback_wallet and node_fallback_wallet.startswith("scash1") and len(node_fallback_wallet) >= 40):
            node_fallback_wallet = _fb_b32.encode_scash_address(os.urandom(20), "scash")
            try:
                if not os.path.isdir(os.path.dirname(_fb_file)):
                    os.makedirs(os.path.dirname(_fb_file))
                open(_fb_file, "w").write(node_fallback_wallet + "\n")
            except Exception:
                pass

    def _post_p2pool_ready():
        for _ in range(45):
            if shutting_down[0]:
                return
            if is_port_open("127.0.0.1", 8345):
                if (not args.no_browser) and (not browser_opened[0]):
                    open_dashboard_browser(ui_url)
                    browser_opened[0] = True
                if ctrl.wallet and ctrl.wallet.lower().startswith(("scash1", "tcash1")) and len(ctrl.wallet) >= 26:
                    # Wait for initial P2Pool sharechain download/verification so XMRig doesn't mine genesis-diff stales!
                    last_wait_log = 0.0
                    for _w_idx in range(75):
                        if shutting_down[0]:
                            return
                        try:
                            raw_tel = _NO_PROXY_OPENER.open("http://127.0.0.1:8345/pool_telemetry", timeout=3.0).read()
                            tel_obj = json.loads(raw_tel.decode("utf-8", "replace")) or {}
                            sc_st = tel_obj.get("sharechain_sync") or {}
                            if not sc_st.get("syncing"):
                                break
                            now_lg = time.time()
                            if (now_lg - last_wait_log) >= 5.0:
                                print("[3/3] %s (holding XMRig start so startup shares aren't orphaned)" % ascii_safe(sc_st.get("status_text") or "Syncing P2Pool sharechain..."))
                                last_wait_log = now_lg
                        except Exception:
                            break
                        time.sleep(1.0)
                    try:
                        start_url = "http://127.0.0.1:8345/miner_start?wallet=%s" % ctrl.wallet
                        if getattr(ctrl, "custom_threads", False):
                            start_url += "&threads=%d" % int(ctrl.threads)
                        _NO_PROXY_OPENER.open(start_url, timeout=5.0).read()
                        print("[3/3] Sharechain ready! Auto-started local XMRig worker on 127.0.0.1:8345 for:", ascii_safe(ctrl.wallet))
                    except Exception as e:
                        print("[3/3] Note: Start worker from Web UI (%s)" % ascii_safe(e))
                break
            time.sleep(1.0)

    t_ready = threading.Thread(target=_post_p2pool_ready)
    t_ready.daemon = True
    t_ready.start()

    ensure_windows_p2p_firewall_rule(8344)
    print("[3/3] Launching Scash P2Pool Sharechain Node on :8344 (P2P) & :8345 (Stratum + QtKawaii UI)...")
    # Verify native RandomX PoW engine against Scash Genesis Block #0 before starting P2Pool!
    os.environ["SCASH_REQUIRE_NATIVE_RANDOMX"] = "1"
    from p2pool.bitcoin import scash_randomx as _srx_chk
    import binascii as _b_chk, struct as _st_chk
    _ml0 = _b_chk.unhexlify("2f7b90fafd8247ee73d213d49699fcfe12a37c608f1d9d1c06f10e43cb6426c6")[::-1]
    _gh0 = _st_chk.pack("<I32s32sIII", 1, b"\x00" * 32, _ml0, 1708650456, 0x1e0fffff, 20076863)
    _rxh0, _ = _srx_chk.calculate_scash_hash_and_cm_bytes(_gh0)
    assert _b_chk.hexlify(_rxh0[::-1]).decode("ascii") == "33c450e0152826e3a8948b01464cf9182344a1544b3ddcf6153dd04b62938d01", "RandomX Genesis self-test mismatch!"
    print("[2/3] Verified native RandomX v1.2.1 PoW engine (Genesis hash match OK)!")

    # One-time cleanup on Linux to purge any stale corrupt shares.0 created by older non-static librandomx builds
    if platform.system() != "Windows":
        _scash_share_dir = os.path.join(ROOT_DIR, "data", "scash")
        _rx_ok_flag = os.path.join(_scash_share_dir, "LINUX_RX_VERIFIED_V2.flag")
        if os.path.isdir(_scash_share_dir) and not os.path.isfile(_rx_ok_flag):
            for _sfn in os.listdir(_scash_share_dir):
                if _sfn.startswith("shares.") or _sfn == "addrs":
                    try:
                        os.remove(os.path.join(_scash_share_dir, _sfn))
                    except Exception:
                        pass
        try:
            if not os.path.isdir(_scash_share_dir): os.makedirs(_scash_share_dir)
            open(_rx_ok_flag, "w").write("1\n")
        except Exception:
            pass

    p2pool_env = dict(os.environ)
    p2pool_env["SCASH_REQUIRE_NATIVE_RANDOMX"] = "1"
    p2pool_env["SCASH_ACTIVE_DATADIR"] = str(active_datadir)
    p2pool_env["SCASH_RPC_PORT"] = str(active_creds[2])
    p2pool_env["SCASH_RPC_USER"] = str(active_creds[0])
    p2pool_env["SCASH_RPC_PASS"] = str(active_creds[1])

    p2pool_cmd = [
        sys.executable,
        os.path.join(ROOT_DIR, "run_p2pool.py"),
        "--net", "scash",
        "--disable-upnp",
        "--bitcoind-address", "127.0.0.1",
        "--bitcoind-rpc-port", str(active_creds[2]),
        "--bitcoind-p2p-port", "8343",
        "--give-author", "0",
        "-a", node_fallback_wallet,
    ]
    for peer in args.peer:
        p2pool_cmd.extend(["-n", peer])
    p2pool_cmd.extend(unknown)
    p2pool_cmd.extend([str(active_creds[0]), str(active_creds[1])])

    p2p_kwargs = {"env": p2pool_env}
    if platform.system() != "Windows":
        preexec = _make_linux_pdeathsig_preexec()
        if preexec is not None:
            p2p_kwargs["preexec_fn"] = preexec

    p2pool_proc[0] = subprocess.Popen(p2pool_cmd, **p2p_kwargs)
    assign_popen_to_win32_job(p2pool_proc[0])

    try:
        while p2pool_proc[0].poll() is None:
            time.sleep(0.4)
        rc = p2pool_proc[0].returncode
    except KeyboardInterrupt:
        _graceful_shutdown_all()
        rc = 0
    finally:
        _graceful_shutdown_all()

    sys.exit(rc if rc is not None else 0)


if __name__ == "__main__":
    main()
