"""In-memory data store. Starts completely empty on every boot."""
from common import DEFAULT_CLOCK, new_uuid

COLLECTIONS = (
    "clubs", "shows", "judges", "slots", "classes", "handlers", "dogs",
    "entries", "blocks", "runs", "protests", "filings",
)

db = {name: {} for name in COLLECTIONS}
state = {"clock": DEFAULT_CLOCK, "seq": 0, "touched": None}


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    state["clock"] = DEFAULT_CLOCK
    state["seq"] = 0
    state["touched"] = None


def begin_request():
    """A resource mutated during one request has its version bumped once."""
    state["touched"] = set()


def now():
    return state["clock"]


def set_clock(iso_text):
    state["clock"] = iso_text


def next_seq():
    state["seq"] += 1
    return state["seq"]


def insert(collection, fields, versioned=True):
    """Create a record. `fields` is an ordered dict of the entity's own fields."""
    rec = {"id": new_uuid()}
    rec.update(fields)
    rec["created_at"] = now()
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    touched = state.get("touched")
    if touched is not None:
        touched.add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and bump version once per request."""
    if "version" not in rec:
        return rec
    rec["updated_at"] = now()
    touched = state.get("touched")
    if touched is None:
        rec["version"] = rec["version"] + 1
    elif rec["id"] not in touched:
        rec["version"] = rec["version"] + 1
        touched.add(rec["id"])
    return rec


def set_fields(rec, **changes):
    """Apply changes; refresh updated_at / version only when something changed."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def get(collection, ident):
    if not isinstance(ident, str):
        return None
    return db[collection].get(ident)


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def rows(collection):
    return sorted(db[collection].values(), key=sort_key)


def where(collection, **filters):
    out = []
    for rec in rows(collection):
        if all(rec.get(k) == v for k, v in filters.items()):
            out.append(rec)
    return out


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
