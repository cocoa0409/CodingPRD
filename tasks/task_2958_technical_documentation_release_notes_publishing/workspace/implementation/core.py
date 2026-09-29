"""Core primitives: logical clock, in-memory store, response envelope, errors."""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ROLE_IDENTITY_MISMATCH": 403,
    "ERR_NOT_ASSIGNED_WRITER": 403,
    "ERR_SIGNOFF_NOT_OWNED": 403,
    "ERR_SELF_REVIEW_FORBIDDEN": 403,
    "ERR_EDITORIAL_SOD_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_DATE_WINDOW": 400,
    "ERR_RELEASE_TRAIN_NOT_FOUND": 404,
    "ERR_WRITER_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_PLAN_ITEM_NOT_FOUND": 404,
    "ERR_TOPIC_NOT_FOUND": 404,
    "ERR_PARENT_TOPIC_NOT_FOUND": 404,
    "ERR_SIGNOFF_NOT_FOUND": 404,
    "ERR_DOC_SET_VERSION_NOT_FOUND": 404,
    "ERR_CHANGE_RECORD_NOT_FOUND": 404,
    "ERR_RELEASE_NOTE_NOT_FOUND": 404,
    "ERR_LOCALE_PROFILE_NOT_FOUND": 404,
    "ERR_LOCALIZATION_JOB_NOT_FOUND": 404,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_DEPRECATION_NOTICE_NOT_FOUND": 404,
    "ERR_STALE_RELEASE_TRAIN_VERSION": 412,
    "ERR_STALE_DOC_SET_VERSION": 412,
    "ERR_RELEASE_TRAIN_INVALID_ADVANCE": 409,
    "ERR_SUPPORT_END_DATE_NOT_REACHED": 409,
    "ERR_RELEASE_TRAIN_CLOSED_FOR_PLANNING": 409,
    "ERR_WRITER_ON_LEAVE": 409,
    "ERR_PLAN_ITEM_NOT_ASSIGNABLE": 409,
    "ERR_PLAN_ITEM_NOT_CANCELLABLE": 409,
    "ERR_TOPIC_ALREADY_IN_REVIEW": 409,
    "ERR_NO_REVISIONS": 409,
    "ERR_NO_NEW_REVISION": 409,
    "ERR_TERMINOLOGY_BLOCKER_PRESENT": 409,
    "ERR_DOC_FREEZE_POSTURE_BLOCKED": 409,
    "ERR_TOPIC_NOT_IN_REVIEW": 409,
    "ERR_SIGNOFF_ALREADY_DECIDED": 409,
    "ERR_DOC_SET_NOT_DRAFT": 409,
    "ERR_DOC_SET_NOT_PUBLISHED": 409,
    "ERR_CHANGE_RECORD_NOT_EDITABLE": 409,
    "ERR_RELEASE_NOTE_ALREADY_PUBLISHED": 409,
    "ERR_RELEASE_NOTE_SUPERSEDED": 409,
    "ERR_LOCALIZATION_JOB_NOT_DELIVERABLE": 409,
    "ERR_LOCALIZATION_JOB_NOT_TRANSLATED": 409,
    "ERR_LOCALIZATION_JOB_NOT_CANCELLABLE": 409,
    "ERR_SOURCE_TOPIC_NOT_PUBLISHED": 409,
    "ERR_LOCALE_PAUSED": 409,
    "ERR_TRAIN_NOT_GA": 409,
    "ERR_FEEDBACK_TOPIC_NOT_PUBLISHED": 409,
    "ERR_TERM_ALREADY_RETIRED": 409,
    "ERR_DEPRECATION_NOTICE_ALREADY_PUBLISHED": 409,
    "ERR_CLOCK_BACKWARD": 409,
    "ERR_MIGRATION_GUIDE_NOT_PUBLISHED": 409,
    "ERR_MIGRATION_GUIDE_PRODUCT_MISMATCH": 409,
    "ERR_PARENT_TOPIC_MISMATCH": 409,
    "ERR_IA_DEPTH_EXCEEDED": 409,
    "ERR_NOTICE_PERIOD_TOO_SHORT": 409,
    "ERR_ANNOUNCE_DATE_NOT_REACHED": 409,
    "ERR_LOCALIZATION_SLA_BREACH": 409,
    "ERR_DUPLICATE_VERSION_LABEL": 409,
    "ERR_DUPLICATE_PERSON_KEY": 409,
    "ERR_DUPLICATE_TOPIC_SLUG": 409,
    "ERR_DUPLICATE_LOCALE_CODE": 409,
    "ERR_DUPLICATE_TERM": 409,
    "ERR_DUPLICATE_SIGNOFF_DISCIPLINE": 409,
    "ERR_DUPLICATE_LOCALIZATION_JOB": 409,
    "ERR_WRITER_WINDOW_OVERLAP": 409,
    "ERR_LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED": 409,
    "ERR_NO_APPROVED_TOPICS": 409,
    "ERR_NO_PUBLISHABLE_CHANGES": 409,
    "ERR_LOCALIZATION_BUDGET_EXCEEDED": 409,
    "ERR_WRITER_CAPACITY_EXCEEDED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Numeric helpers (PRD section 2.7): half-up rounding, never float arithmetic
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def r2(value):
    """Round half up to two decimal places."""
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rcents(value):
    """Round half up to a whole number of cents (integer)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dfloor(value):
    """Discard any fraction downwards, returning an int."""
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def num_out(value):
    """Serialise a stored decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Instants and calendar dates
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 UTC instant with a trailing Z. Returns None if invalid."""
    if not isinstance(text, str) or not text.endswith("Z"):
        return None
    body = text[:-1]
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(body, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_date(text):
    """Parse a YYYY-MM-DD calendar date. Returns None if invalid."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(day):
    return None if day is None else day.isoformat()


def date_of_instant(text_or_dt):
    """Reduce a stored instant to its UTC calendar date."""
    if text_or_dt is None:
        return None
    if isinstance(text_or_dt, str):
        dt = parse_instant(text_or_dt)
        return None if dt is None else dt.date()
    return text_or_dt.astimezone(timezone.utc).date()


def add_days(day, count):
    return day + timedelta(days=int(count))


# ---------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot; nothing is seeded.
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "release_trains",
    "writers",
    "reviewers",
    "plan_items",
    "topics",
    "source_revisions",
    "signoffs",
    "doc_set_versions",
    "change_records",
    "release_notes",
    "locale_profiles",
    "localization_jobs",
    "terminology_terms",
    "page_feedback",
    "deprecation_notices",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_instant(self.clock)

    def today(self):
        return self.clock.astimezone(timezone.utc).date()


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now_iso():
    return fmt_instant(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Record lifecycle helpers
# ---------------------------------------------------------------------------
def base_record(versioned=True):
    """Common audit fields (PRD section 2.4)."""
    record = {"id": new_id(), "created_at": db.now_iso()}
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a record as mutated: refresh updated_at and bump version by one."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


def snap(record):
    """Snapshot of a record's observable state, excluding the audit fields."""
    return {k: v for k, v in record.items()
            if k not in ("updated_at", "version") and not k.startswith("_")}


def commit(record, snapshot):
    """Bump version/updated_at only when something actually changed."""
    if snap(record) != snapshot:
        touch(record)
        return True
    return False


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------
def meta_block():
    return {"api_request_id": request_id(), "api_request_timestamp": wall_now_iso()}


def ok(data, status=200):
    body = {"meta": meta_block(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = meta_block()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
def public(record):
    """Strip internal bookkeeping keys and render Decimals as JSON numbers."""
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = num_out(value) if isinstance(value, Decimal) else value
    return out


def public_list(records):
    return [public(r) for r in records]


def page(records, limit, offset):
    total = len(records)
    window = records[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Path / body reference resolution (PRD section 2.5 bands 6 and 7)
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "release_trains": "ERR_RELEASE_TRAIN_NOT_FOUND",
    "writers": "ERR_WRITER_NOT_FOUND",
    "reviewers": "ERR_REVIEWER_NOT_FOUND",
    "plan_items": "ERR_PLAN_ITEM_NOT_FOUND",
    "topics": "ERR_TOPIC_NOT_FOUND",
    "signoffs": "ERR_SIGNOFF_NOT_FOUND",
    "doc_set_versions": "ERR_DOC_SET_VERSION_NOT_FOUND",
    "change_records": "ERR_CHANGE_RECORD_NOT_FOUND",
    "release_notes": "ERR_RELEASE_NOTE_NOT_FOUND",
    "locale_profiles": "ERR_LOCALE_PROFILE_NOT_FOUND",
    "localization_jobs": "ERR_LOCALIZATION_JOB_NOT_FOUND",
    "terminology_terms": "ERR_TERM_NOT_FOUND",
    "deprecation_notices": "ERR_DEPRECATION_NOTICE_NOT_FOUND",
}


def must_get(collection, record_id, error_id=None):
    table = getattr(db, collection)
    record = table.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        fail(error_id or NOT_FOUND[collection])
    return record


def all_of(collection):
    return by_seq(list(getattr(db, collection).values()))
