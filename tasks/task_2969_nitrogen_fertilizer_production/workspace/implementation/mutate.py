"""Version bookkeeping.

Every specified mutation advances a row's `version` by exactly 1 per request,
even when two hops of the same cascade touch the row, so the bump is recorded
against the request rather than against the call site.
"""
from flask import g

from store import bump


def touch(row):
    if row is None or "version" not in row:
        return row
    seen = getattr(g, "touched_ids", None)
    if seen is None:
        seen = set()
        g.touched_ids = seen
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    return bump(row)
