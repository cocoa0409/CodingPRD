"""In-memory store, logical clock, id/timestamp plumbing.

A fresh process boots with a completely empty store (no seeding, ever) and the
logical clock reading exactly CLOCK_DEFAULT (PRD §2.4). `created_at` /
`updated_at` / envelope timestamps use a strictly monotonic wall clock with
three fractional digits (PRD §2.5); business timestamps (sat_at, reviewed_at,
...) snapshot the logical clock.
"""

import uuid
from datetime import datetime, timezone, timedelta

import constants as C


def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_clock(dt):
    """Canonical logical-clock rendering: seconds when whole, else fractional."""
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.microsecond
    if micro == 0:
        return base + "Z"
    if micro % 1000 == 0:
        return base + ".%03dZ" % (micro // 1000)
    return base + ".%06dZ" % micro


def _fmt_wall(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.candidates = {}
        self.syllabus_versions = {}
        self.exams = {}
        self.exam_windows = {}
        self.exam_registrations = {}
        self.pass_mark_settings = {}
        self.vee_submissions = {}
        self.track_enrollments = {}
        self.modules = {}
        self.module_attempts = {}
        self.project_assessments = {}
        self.course_sessions = {}
        self.course_attendances = {}
        self.transfer_credit_requests = {}
        self.cpd_attestations = {}
        self.discipline_cases = {}
        self.credential_applications = {}
        self.clock = parse_dt(C.CLOCK_DEFAULT)
        self.seq = 0
        self.last_wall = None


db = Store()


def new_id():
    return str(uuid.uuid4())


def wall_ts_now():
    """Strictly increasing wall-clock timestamp, 3 fractional digits (PRD §2.5)."""
    now = datetime.now(timezone.utc)
    if db.last_wall is not None and now <= db.last_wall:
        now = db.last_wall + timedelta(milliseconds=1)
    db.last_wall = now
    return _fmt_wall(now)


def touch(rec):
    """Record a modification: refresh updated_at and increment version."""
    rec["updated_at"] = wall_ts_now()
    rec["version"] += 1


def new_record():
    ts = wall_ts_now()
    db.seq += 1
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.seq,
    }
