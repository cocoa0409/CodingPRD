"""In-memory storage. Every collection starts empty on every boot; nothing is seeded."""

import itertools
import uuid

import clock

_seq = itertools.count(1)

# One dict per entity collection, keyed by id.
plans = {}
authorities = {}
participants = {}
assignments = {}
grants = {}
tranches = {}
cycles = {}
events = {}
tax_allocations = {}
windows = {}
preclearances = {}
trading_plans = {}
reports = {}


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    stamp = clock.fmt_instant(clock.now())
    row = {"id": new_id(), "created_at": stamp, "_seq": next(_seq)}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version on a mutated row (PRD 2.11)."""
    row["updated_at"] = clock.fmt_instant(clock.now())
    row["version"] = row.get("version", 1) + 1


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_default(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_by(rows, field):
    return sorted(rows, key=lambda r: ((r.get(field) is None), r.get(field), r["_seq"]))


def children(collection, field, value):
    return [r for r in collection.values() if r.get(field) == value]
