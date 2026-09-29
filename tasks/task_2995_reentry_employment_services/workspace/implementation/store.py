"""In-memory data store, id minting, wall-clock stamps and the logical clock.

Nothing is persisted anywhere: every dictionary below starts empty on each boot
and no entity is ever seeded.  PRD section 2.4 fixes the boot value of the
logical clock at 2026-08-01T00:00:00Z.
"""

import random
import string
import uuid
from datetime import datetime, timezone

BOOT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "participants",
    "supervision_cases",
    "partnerships",
    "job_openings",
    "placements",
    "work_shifts",
    "grants",
    "support_requests",
    "sessions",
    "enrollments",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = BOOT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_str():
    return fmt_instant(wall_now())


def now():
    """The logical clock instant."""
    return db.clock


def now_str():
    return fmt_instant(db.clock)


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def new_row(**fields):
    stamp = wall_now_str()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


_touched_marker = {"ids": set()}


def begin_request():
    _touched_marker["ids"] = set()


def touch(row):
    """Refresh updated_at and advance version, at most once per request."""
    marks = _touched_marker["ids"]
    row["updated_at"] = wall_now_str()
    if row["id"] in marks:
        return
    marks.add(row["id"])
    row["version"] = row["version"] + 1


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}
