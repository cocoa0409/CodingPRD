"""In-memory data store.  Starts completely empty on every boot: no seeding."""
import uuid

import logical_clock as clockmod

COLLECTIONS = (
    "price_zones",
    "clusters",
    "stores",
    "menu_items",
    "price_requests",
    "availabilities",
    "campaigns",
    "upsell_rules",
    "bundles",
    "devices",
    "orders",
)


class Database(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.audit_events = []
        self._insert_seq = 0
        self._audit_seq = {}

    def next_seq(self):
        self._insert_seq += 1
        return self._insert_seq


DB = Database()


def new_row(extra=None):
    stamp = clockmod.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clockmod.now_iso()
    row["version"] = row.get("version", 1) + 1


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=sort_key)


def append_audit(subject_kind, subject_id, action, actor_role, actor_user_id,
                 detail=None, before_value_cents=None, after_value_cents=None):
    key = (subject_kind, subject_id)
    DB._audit_seq[key] = DB._audit_seq.get(key, 0) + 1
    row = {
        "id": str(uuid.uuid4()),
        "created_at": clockmod.now_iso(),
        "_seq": DB.next_seq(),
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "at_utc": clockmod.now_iso(),
        "before_value_cents": before_value_cents,
        "after_value_cents": after_value_cents,
        "sequence_no": DB._audit_seq[key],
        "detail": detail,
    }
    DB.audit_events.append(row)
    return row


def all_of(name):
    return ordered(list(getattr(DB, name).values()))
