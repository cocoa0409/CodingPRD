"""A thin helper facade over the in-memory store and the logical clock.

Every module imports ``h`` and talks to the store through it, so the collection
names live in exactly one place.
"""
import db
from db import STORE, new_id, stamp, now_iso
import clockutil as _cu


class Helper(object):
    # --- store access -----------------------------------------------------
    def put(self, name, rec):
        return STORE.put(name, rec)

    def get(self, name, key):
        return STORE.get(name, key)

    def all(self, name):
        return STORE.all(name)

    def find(self, name, **criteria):
        return STORE.find(name, **criteria)

    def collection(self, name):
        return getattr(STORE, name)

    # --- creation ---------------------------------------------------------
    def create(self, name, fields):
        return db.create(name, fields)

    def create_with_id(self, name, fields):
        """Create a record but force a caller-supplied id (used for aliases)."""
        rec = dict(fields)
        rec.setdefault("id", new_id())
        STORE.put(name, rec)
        return rec

    # --- mutation ---------------------------------------------------------
    def touch(self, rec):
        return stamp(rec)

    # --- clock ------------------------------------------------------------
    @property
    def now(self):
        return _cu.clock()

    def now_iso(self):
        return _cu.fmt(_cu.clock())

    def parse(self, value):
        return _cu.parse_ts(value)

    def fmt(self, value):
        return _cu.fmt(value)

    # --- raw ids ----------------------------------------------------------
    def new_id(self):
        return new_id()

    def now_stamp(self):
        return now_iso()


h = Helper()