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


def storage_key(client_name, client_id=None):
    """Folder key for a client's saved pieces.

    Prefer an explicit, coach-supplied identifier (the optional "Client ID or
    email" field) so two different clients who share a display name (e.g. two
    "John Smith"s) never collide in the same folder. Fall back to the name slug
    when no identifier is given — that keeps already-saved name-slug folders
    readable and behavior unchanged for the single-client case.
    """
    basis = client_id if (client_id or "").strip() else client_name
    return slugify(basis)


def _client_dir(key, create=False):
    """key is an already-computed storage slug (see storage_key)."""
    d = os.path.join(_data_dir(), key)
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


def save_piece(client_name, key, content, client_id=None):
    """Persist one generated piece. No-op for keys not in the package set.

    The folder is chosen by client_id when provided, else by the name slug
    (see storage_key), so separate runs for the same client land together
    while distinct clients sharing a name stay apart. The display name (and
    identifier) are recorded in meta.json so the UI can show the real name.
    """
    if key not in PIECE_LABELS or not content:
        return
    skey = storage_key(client_name, client_id)
    cdir = _client_dir(skey, create=True)
    with open(os.path.join(cdir, key + _ext(key)), "w", encoding="utf-8") as f:
        f.write(content)
    meta = _read_meta(cdir)
    meta["client_name"] = client_name
    if (client_id or "").strip():
        meta["client_id"] = client_id.strip()
    meta.setdefault("pieces", {})[key] = datetime.now(timezone.utc).isoformat()
    meta["updated"] = datetime.now(timezone.utc).isoformat()
    with open(_meta_path(cdir), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def load_piece(key, piece):
    """key is a storage slug (see storage_key); piece is a PIECE_LABELS key."""
    cdir = _client_dir(key)
    p = os.path.join(cdir, piece + _ext(piece))
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    return None


def load_all(key):
    """Return {piece: content} for every saved package piece in this folder.

    key is a storage slug as returned by list_clients()/storage_key().
    """
    return {
        piece: content
        for piece in PIECE_LABELS
        if (content := load_piece(key, piece)) is not None
    }


def list_clients():
    """Return [{slug, name, pieces:[keys], updated}] for all saved clients.

    "slug" is the storage key the caller passes back to load_all()/build; it
    may be a coach-supplied identifier slug or, for older saves, a name slug.
    """
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
            "client_id": meta.get("client_id", ""),
            "pieces": pieces,
            "updated": meta.get("updated", ""),
        })
    out.sort(key=lambda c: c.get("updated", ""), reverse=True)
    return out
