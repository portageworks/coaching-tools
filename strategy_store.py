"""
Per-client persistence for the Strategy Package.

Each generated piece (summary, branding, interview program, success stories,
roleplay analysis, positioning) is saved to a per-client folder so the final
assembly step can recombine them with no additional model runs.

Storage location is configurable via STRATEGY_DATA_DIR so it can point at a
Railway Volume in production (e.g. /data) and fall back to ./outputs locally.
Railway's container filesystem is ephemeral, so production MUST mount a volume
and set STRATEGY_DATA_DIR to its mount path, or saved content is lost on deploy.
"""
import os
import re
import json
from datetime import datetime, timezone

# Keys that belong in the client strategy package, with display labels.
# "positioning" is stored as JSON; everything else is markdown.
PIECE_LABELS = {
    "summary":     "Session Summary",
    "branding":    "Branding Profile",
    "ip":          "Interview Program",
    "stories":     "Success Stories",
    "roleplay":    "Roleplay Analysis",
    "positioning": "Where to Look",
}
JSON_KEYS = {"positioning"}


def _data_dir():
    base = os.environ.get("STRATEGY_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "outputs"
    )
    os.makedirs(base, exist_ok=True)
    return base


def slugify(client_name):
    slug = re.sub(r"[^a-z0-9]+", "_", (client_name or "").lower()).strip("_")
    return slug or "client"


def _client_dir(client_name, create=False):
    d = os.path.join(_data_dir(), slugify(client_name))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _ext(key):
    return ".json" if key in JSON_KEYS else ".md"


def _meta_path(client_dir):
    return os.path.join(client_dir, "meta.json")


def _read_meta(client_dir):
    p = _meta_path(client_dir)
    if os.path.exists(p):
        try:
            return json.loads(open(p, encoding="utf-8").read())
        except Exception:
            pass
    return {"client_name": "", "pieces": {}}


def save_piece(client_name, key, content):
    """Persist one generated piece. No-op for keys not in the package set."""
    if key not in PIECE_LABELS or not content:
        return
    cdir = _client_dir(client_name, create=True)
    with open(os.path.join(cdir, key + _ext(key)), "w", encoding="utf-8") as f:
        f.write(content)
    meta = _read_meta(cdir)
    meta["client_name"] = client_name
    meta.setdefault("pieces", {})[key] = datetime.now(timezone.utc).isoformat()
    meta["updated"] = datetime.now(timezone.utc).isoformat()
    with open(_meta_path(cdir), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def load_piece(client_name, key):
    cdir = _client_dir(client_name)
    p = os.path.join(cdir, key + _ext(key))
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    return None


def load_all(client_name):
    """Return {key: content} for every saved package piece for this client."""
    return {
        key: content
        for key in PIECE_LABELS
        if (content := load_piece(client_name, key)) is not None
    }


def list_clients():
    """Return [{slug, name, pieces:[keys], updated}] for all saved clients."""
    base = _data_dir()
    out = []
    for slug in sorted(os.listdir(base)):
        cdir = os.path.join(base, slug)
        if not os.path.isdir(cdir):
            continue
        meta = _read_meta(cdir)
        pieces = [k for k in PIECE_LABELS if os.path.exists(os.path.join(cdir, k + _ext(k)))]
        if not pieces:
            continue
        out.append({
            "slug": slug,
            "name": meta.get("client_name") or slug,
            "pieces": pieces,
            "updated": meta.get("updated", ""),
        })
    out.sort(key=lambda c: c.get("updated", ""), reverse=True)
    return out
