"""HTTP with a disk cache, polite rate limiting and an offline (fixture) mode.

Offline mode (--offline DIR or CONFLUENCE_OFFLINE): every request is answered
from DIR/<cache key> instead of the network. Tests and demos use this.
"""

import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import config

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class NetError(Exception):
    pass


def safe_key(key):
    k = re.sub(r"[^A-Za-z0-9._=-]+", "_", key)
    if len(k) > 120:
        k = k[:80] + "_" + hashlib.sha1(key.encode()).hexdigest()[:16]
    return k


class Fetcher(object):
    """get(url, key, ttl_minutes, kind) -> bytes. Thread safe."""

    def __init__(self, cfg=None, offline=None, sec_ua=None, cache=True):
        self.cfg = cfg or config.load()
        self.offline = offline or os.environ.get("CONFLUENCE_OFFLINE") or None
        self.sec_ua = sec_ua if sec_ua is not None else self.cfg.get("sec_user_agent")
        self.cache = cache
        self.cache_dir = os.path.join(config.data_dir(), "cache")
        self._lock = threading.Lock()
        self._last = {}
        self.errors = []

    # one request per host per `gap` seconds; SEC allows 10/s, we stay well under
    def _throttle(self, host, gap):
        with self._lock:
            now = time.time()
            wait = self._last.get(host, 0) + gap - now
            self._last[host] = max(now, self._last.get(host, 0) + gap)
        if wait > 0:
            time.sleep(wait)

    def get(self, url, key, ttl=60, sec=False, headers=None):
        key = safe_key(key)
        if self.offline:
            path = os.path.join(self.offline, key)
            if not os.path.isfile(path):
                raise NetError("offline: no fixture %s" % key)
            with open(path, "rb") as fh:
                return fh.read()
        path = os.path.join(self.cache_dir, key)
        if self.cache and ttl and os.path.isfile(path):
            if (time.time() - os.path.getmtime(path)) < ttl * 60:
                with open(path, "rb") as fh:
                    return fh.read()
        if sec and not self.sec_ua:
            raise NetError("SEC needs a User-Agent: set sec_user_agent in config.json "
                           "or SEC_USER_AGENT=\"Your Name you@example.com\"")
        host = url.split("/")[2]
        self._throttle(host, 0.15 if sec else 0.05)
        h = {"User-Agent": self.sec_ua if sec else BROWSER_UA,
             "Accept-Encoding": "gzip", "Accept": "*/*"}
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        last_exc = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                break
            except urllib.error.HTTPError as exc:
                last_exc = NetError("HTTP %s for %s" % (exc.code, url))
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise last_exc
            except (urllib.error.URLError, OSError) as exc:
                last_exc = NetError("could not reach %s: %s" % (url, getattr(exc, "reason", exc)))
                time.sleep(1.0 * (attempt + 1))
        else:
            raise last_exc
        if self.cache:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = path + ".tmp%d" % threading.get_ident()
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return data

    def json(self, url, key, ttl=60, sec=False, headers=None):
        raw = self.get(url, key, ttl=ttl, sec=sec, headers=headers)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise NetError("not JSON: %s" % url)

    def note(self, msg):
        with self._lock:
            if msg not in self.errors:
                self.errors.append(msg)
