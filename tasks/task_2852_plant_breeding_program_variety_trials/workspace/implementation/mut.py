"""Record versioning (PRD 2.4 / 2.10).

`version` starts at 1 and increments by exactly 1 on every mutation of the
record, including mutations the server performs on its own initiative as part
of a cascade, and including a change to a derived counter.  Each record is
therefore bumped at most once per request: watch() records a signature before
the record is touched, force() marks a record the PRD says explicitly advances,
and commit() bumps every watched record whose observable state changed.
"""

from flask import g

import store


def _sig(rec):
    return repr(sorted(
        (k, repr(v)) for k, v in rec.items()
        if not k.startswith("_") and k not in ("updated_at", "version")
    ))


def _table():
    tbl = getattr(g, "_mut_table", None)
    if tbl is None:
        tbl = {}
        g._mut_table = tbl
    return tbl


def reset():
    g._mut_table = {}


def watch(*recs):
    tbl = _table()
    for rec in recs:
        if rec is None or "version" not in rec:
            continue
        key = id(rec)
        if key not in tbl:
            tbl[key] = [rec, _sig(rec), False]


def force(*recs):
    tbl = _table()
    for rec in recs:
        if rec is None or "version" not in rec:
            continue
        watch(rec)
        tbl[id(rec)][2] = True


def commit():
    tbl = _table()
    for rec, sig, forced in list(tbl.values()):
        if forced or _sig(rec) != sig:
            rec["version"] = rec.get("version", 1) + 1
            rec["updated_at"] = store.instant_now()
    g._mut_table = {}
