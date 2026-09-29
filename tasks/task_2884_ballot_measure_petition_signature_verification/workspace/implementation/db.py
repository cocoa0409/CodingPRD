"""In-memory data store, logical clock and common-field helpers.

Every collection starts EMPTY on boot: nothing is seeded, preloaded or
hardcoded. Re-invoking start.sh therefore wipes every byte of state.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

UTC = timezone.utc

# PRD 2.4 — the deterministic logical clock's default position.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# fixed statutory constants (PRD 2.5)
# ---------------------------------------------------------------------------
MAX_FORMAT_REVIEW_ROUNDS = 2
CHALLENGE_REVIEW_DAYS = 15
ASSIGNMENT_BUFFER_DAYS = 3
MISCONDUCT_SUSPENSION_THRESHOLD = 1
APPROVED_TRAINING_COURSES = ["SOS-CIRC-101", "SOS-CIRC-201"]
MAX_CURE_PERIODS = 2
MIN_ASSUMED_VALIDITY_BPS = 2500
TIER_A_FLOOR_CENTS = 20
TIER_B_FLOOR_CENTS = 100
TIER_A_DISCOUNT_BPS = 1000
TIER_B_DISCOUNT_BPS = 1500
PROVISIONAL_WEIGHT_BPS = 5000
ADJUDICATED_WEIGHT_BPS = 10000
PROVISIONAL_OPEN_REFERRAL_PENALTY_BPS = 500
SUBSTANTIATED_STRIKE_PENALTY_BPS = 2000
CREDIBILITY_FLOOR_BPS = 1000

ACCEPTED_BATCH_STATUSES = ("AFFIDAVIT_VERIFIED", "SAMPLED", "FULLY_CHECKED")
TERMINAL_BATCH_STATUSES = ("REJECTED_FORMAT", "INVALIDATED")


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.standards = {}
        self.counties = {}
        self.voter_records = {}
        self.petitions = {}
        self.circulators = {}
        self.assignments = {}
        self.batches = {}
        self.signature_records = {}
        self.rounds = {}
        self.cure_periods = {}
        self.challenges = {}
        self.fraud_referrals = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# ids and instants
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def fmt_instant(dt):
    """ISO-8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        try:
            oh, om = int(body[:2]), int(body[2:4])
        except ValueError:
            return None
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def now():
    """The logical clock's current position."""
    return db.clock


def now_str():
    return fmt_instant(db.clock)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# common fields (PRD 2.7)
# ---------------------------------------------------------------------------
def new_resource(extra=None):
    """id / created_at / updated_at / version for the nine resource types."""
    stamp = now_str()
    obj = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        obj.update(extra)
    return obj


def new_config(extra=None):
    """id / created_at only — configuration types carry no updated_at/version."""
    obj = {
        "id": new_id(),
        "created_at": now_str(),
        "_seq": db.next_seq(),
    }
    if extra:
        obj.update(extra)
    return obj


def touch(obj):
    """Refresh updated_at and bump version — at most once per request."""
    if obj is None or "version" not in obj:
        return obj
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        try:
            seen = g._touched = set()
        except RuntimeError:
            seen = set()
    if obj["id"] not in seen:
        seen.add(obj["id"])
        obj["version"] += 1
    obj["updated_at"] = now_str()
    return obj


def serialize(obj):
    """Expose exactly the declared fields — internal keys start with '_'."""
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def ordered(collection):
    return sorted(collection.values(), key=lambda o: o["_seq"])


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def _find(collection, resource_id, error_id):
    if not isinstance(resource_id, str):
        raise ApiError(error_id)
    obj = collection.get(resource_id)
    if obj is None:
        raise ApiError(error_id)
    return obj


def get_standard(sid):
    return _find(db.standards, sid, "ERR_VERIFICATION_STANDARD_NOT_FOUND")


def get_county(cid):
    return _find(db.counties, cid, "ERR_COUNTY_NOT_FOUND")


def get_voter_record(vid):
    return _find(db.voter_records, vid, "ERR_VOTER_RECORD_NOT_FOUND")


def get_petition(pid):
    return _find(db.petitions, pid, "ERR_PETITION_NOT_FOUND")


def get_circulator(cid):
    return _find(db.circulators, cid, "ERR_CIRCULATOR_NOT_FOUND")


def get_assignment(aid):
    return _find(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")


def get_batch(bid):
    return _find(db.batches, bid, "ERR_BATCH_NOT_FOUND")


def get_signature_record(rid):
    return _find(db.signature_records, rid, "ERR_SIGNATURE_RECORD_NOT_FOUND")


def get_round(rid):
    return _find(db.rounds, rid, "ERR_ROUND_NOT_FOUND")


def get_cure_period(cid):
    return _find(db.cure_periods, cid, "ERR_CURE_PERIOD_NOT_FOUND")


def get_challenge(cid):
    return _find(db.challenges, cid, "ERR_CHALLENGE_NOT_FOUND")


def get_referral(rid):
    return _find(db.fraud_referrals, rid, "ERR_FRAUD_REFERRAL_NOT_FOUND")


# ---------------------------------------------------------------------------
# relational helpers
# ---------------------------------------------------------------------------
def batches_of_petition(petition_id):
    return [b for b in ordered(db.batches) if b["petition_id"] == petition_id]


def batches_of_circulator(circulator_id):
    return [b for b in ordered(db.batches) if b["circulator_id"] == circulator_id]


def records_of_batch(batch_id):
    return [r for r in ordered(db.signature_records) if r["batch_id"] == batch_id]


def records_of_petition(petition_id):
    out = []
    for b in batches_of_petition(petition_id):
        out.extend(records_of_batch(b["id"]))
    return out


def rounds_of_petition(petition_id):
    return [r for r in ordered(db.rounds) if r["petition_id"] == petition_id]


def cure_periods_of_petition(petition_id):
    return [c for c in ordered(db.cure_periods) if c["petition_id"] == petition_id]


def assignments_of_circulator(circulator_id):
    return [a for a in ordered(db.assignments) if a["circulator_id"] == circulator_id]


def referrals_of_circulator(circulator_id):
    return [r for r in ordered(db.fraud_referrals)
            if r["circulator_id"] == circulator_id]


def county_of_batch(batch):
    return db.counties.get(batch["county_id"])


def county_code_of_batch(batch):
    county = county_of_batch(batch)
    return county["county_code"] if county else ""


def batch_of_record(record):
    return db.batches.get(record["batch_id"])


def petition_of_record(record):
    batch = batch_of_record(record)
    return db.petitions.get(batch["petition_id"]) if batch else None
