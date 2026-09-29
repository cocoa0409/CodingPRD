"""In-memory data store. Starts completely empty on every boot -- no seeding."""
from flask import g

from core import clock_str, new_uuid

programs = {}
athletes = {}
medical_forms = {}
volunteers = {}
credentials = {}
seasons = {}
sessions = {}
attendance = {}
divisions = {}
entries = {}
teams = {}
screenings = {}
contributions = {}

COLLECTIONS = {
    "programs": programs,
    "athletes": athletes,
    "medical_forms": medical_forms,
    "volunteers": volunteers,
    "credentials": credentials,
    "seasons": seasons,
    "sessions": sessions,
    "attendance": attendance,
    "divisions": divisions,
    "entries": entries,
    "teams": teams,
    "screenings": screenings,
    "contributions": contributions,
}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def _created_ids():
    if not hasattr(g, "created_ids"):
        g.created_ids = set()
    return g.created_ids


def _touched_ids():
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def new_row(collection, fields):
    now = clock_str()
    row = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    row.update(fields)
    COLLECTIONS[collection][row["id"]] = row
    _created_ids().add(row["id"])
    return row


def touch(row):
    """Register a mutation of an existing row: bump version once per request."""
    if row["id"] in _created_ids():
        return row
    now = clock_str()
    if row["id"] in _touched_ids():
        row["updated_at"] = now
        return row
    _touched_ids().add(row["id"])
    row["updated_at"] = now
    row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes):
    """Assign changed fields and touch the row only when something differs."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def all_of(collection):
    return list(COLLECTIONS[collection].values())
