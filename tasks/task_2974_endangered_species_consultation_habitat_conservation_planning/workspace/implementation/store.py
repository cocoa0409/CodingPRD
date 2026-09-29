"""In-memory storage and the logical regulatory clock.

Everything lives in plain dicts keyed by id.  Nothing is written to disk and
nothing is pre-seeded, so re-launching the process wipes every byte of state.
"""
import itertools

import util

# PRD 2.5: before the clock has been set even once it reads exactly this
# instant, and it never falls back to the host's wall clock.
DEFAULT_CLOCK = util.parse_instant("2026-08-01T00:00:00Z")

TABLES = (
    "species",
    "proponents",
    "habitat_units",
    "actions",
    "determinations",
    "consultations",
    "opinions",
    "banks",
    "plans",
    "commitments",
    "permits",
    "reports",
    "events",
)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        for table in TABLES:
            setattr(self, table, {})

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        for table in TABLES:
            setattr(self, table, {})

    def next_seq(self):
        return next(self._seq)


DB = Store()


def now():
    return DB.clock


def set_clock(moment):
    DB.clock = moment


def new_row(**fields):
    """Mint a row carrying the common id / created_at / updated_at / version
    set.  `_seq` is an internal insertion counter used only to break
    created_at ties deterministically; it is never serialised."""
    row = {
        "id": util.new_uuid(),
        "created_at": DB.clock,
        "updated_at": DB.clock,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and bump version, exactly as a direct write would --
    cascade hops are indistinguishable from direct writes (PRD 2.10)."""
    row["updated_at"] = DB.clock
    row["version"] = row["version"] + 1


def ordered(rows):
    """created_at ascending.  Never id.  `_seq` breaks ties inside a single
    logical-clock instant, which is the common case because the clock only
    moves when a test moves it."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def insert(table, row):
    getattr(DB, table)[row["id"]] = row
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(DB, table).get(row_id)


def values(table):
    return list(getattr(DB, table).values())


def where(table, **match):
    out = []
    for row in getattr(DB, table).values():
        for key, wanted in match.items():
            if row.get(key) != wanted:
                break
        else:
            out.append(row)
    return ordered(out)
