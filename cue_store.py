"""
Ephemeral storage for Session Cue links.

A generated cue screen is saved as a standalone HTML file under a random,
unguessable token on the same volume as the strategy data, with a short expiry.
Anyone holding the link can view it until it expires (the "anyone with the link"
model); expired files are purged lazily whenever a new link is created.

Storage lives under STRATEGY_DATA_DIR (a Railway Volume in production) so links
survive deploys. Nothing here is committed to git or linked from anywhere, so
the only way to reach a cue page is to possess its exact token.
"""
import os
import re
import json
import time
import secrets

from strategy_store import _data_dir  # reuse the configured volume base

CUE_DIRNAME = "_cue"
DEFAULT_TTL_DAYS = 7
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _cue_dir(create=False):
    d = os.path.join(_data_dir(), CUE_DIRNAME)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _purge_expired():
    d = _cue_dir()
    if not os.path.isdir(d):
        return
    now = time.time()
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        token = fn[:-5]
        try:
            exp = json.load(open(os.path.join(d, fn), encoding="utf-8")).get("expires", 0)
        except Exception:
            exp = 0
        if exp and exp < now:
            for p in (os.path.join(d, token + ".html"), os.path.join(d, fn)):
                try:
                    os.remove(p)
                except OSError:
                    pass


def save_cue(html, client_name="", ttl_days=DEFAULT_TTL_DAYS):
    """Persist a cue HTML page under a fresh token; return the token."""
    _purge_expired()
    d = _cue_dir(create=True)
    token = secrets.token_urlsafe(9)  # ~12 url-safe chars
    expires = time.time() + ttl_days * 86400
    with open(os.path.join(d, token + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(d, token + ".json"), "w", encoding="utf-8") as f:
        json.dump({"client_name": client_name, "expires": expires,
                   "created": time.time()}, f)
    return token, expires


def load_cue(token):
    """Return the stored HTML for a token, or None if missing/expired/invalid."""
    if not (token and _TOKEN_RE.fullmatch(token)):  # reject path parts / junk
        return None
    d = _cue_dir()
    meta_p = os.path.join(d, token + ".json")
    html_p = os.path.join(d, token + ".html")
    if not (os.path.exists(meta_p) and os.path.exists(html_p)):
        return None
    try:
        exp = json.load(open(meta_p, encoding="utf-8")).get("expires", 0)
    except Exception:
        exp = 0
    if exp and exp < time.time():
        return None
    return open(html_p, encoding="utf-8").read()
