"""Purely in-memory data store.

Nothing is persisted to disk and nothing is seeded at import time: every boot
starts with an empty store and the logical clock at its declared startup value.
"""
import copy
import threading
import uuid
from datetime import datetime, timezone

from constants import CLOCK_STARTUP_ISO
from timeutil import parse_iso8601

# collection name -> { id: record dict }
COLLECTIONS = (
    "cases",
    "vendors",
    "packages",
    "documents",
    "listings",
    "offers",
    "net_sheets",
    "valuations",
    "disputes",
    "liens",
    "mi_claims",
    "approvals",
    "extensions",
)

# fields that are NOT part of an entity's "domain state" for change detection
_NON_DOMAIN = ("version", "updated_at", "_seq", "_kind")


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.current_utc = parse_iso8601(CLOCK_STARTUP_ISO)
        self._snapshot = None
        self._forced = set()

    # ---- clock ------------------------------------------------------------
    def now(self):
        return self.current_utc

    def set_clock(self, instant):
        self.current_utc = instant

    # ---- ids / sequence ---------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- record helpers ---------------------------------------------------
    def insert(self, collection, record, common_fields=True):
        record["_seq"] = self.next_seq()
        record["created_at"] = self.now()
        if common_fields:
            record["updated_at"] = self.now()
            record["version"] = 1
        getattr(self, collection)[record["id"]] = record
        return record

    def all(self, collection):
        return sorted(getattr(self, collection).values(), key=lambda r: r["_seq"])

    def get(self, collection, rid):
        if not isinstance(rid, str):
            return None
        return getattr(self, collection).get(rid)

    # ---- per-request version tracking -------------------------------------
    def begin_request(self):
        snap = {}
        for name in COLLECTIONS:
            for rid, rec in getattr(self, name).items():
                snap[(name, rid)] = _domain_view(rec)
        self._snapshot = snap
        self._forced = set()

    def force_touch(self, collection, rid):
        self._forced.add((collection, rid))

    def finalize(self):
        """Bump version/updated_at on every record whose domain state moved."""
        snap = self._snapshot
        if snap is None:
            return
        self._snapshot = None
        now = self.now()
        for name in COLLECTIONS:
            for rid, rec in getattr(self, name).items():
                if "version" not in rec:
                    continue  # immutable configuration row (BpoVendor)
                key = (name, rid)
                before = snap.get(key)
                if before is None:
                    continue  # freshly created this request: stays at version 1
                if key in self._forced or before != _domain_view(rec):
                    rec["version"] = rec.get("version", 1) + 1
                    rec["updated_at"] = now
        self._forced = set()


def _domain_view(rec):
    return {k: copy.deepcopy(v) for k, v in rec.items() if k not in _NON_DOMAIN}


db = Store()
