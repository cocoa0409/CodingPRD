"""Shared request/response plumbing: pagination, body parsing, lookups and the
clock-relative predicates every workflow shares.
"""

from apptime import parse
from config import DISPUTE_WINDOW_HOURS, REVIEW_WINDOW_HOURS
from db import db
from errors import fail

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


# --- pagination (SCAFFOLD §1.0 pagination_fields / defaults) ---------------
def _int_param(raw, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def paginate(items, args) -> tuple:
    """Return (page_items, pagination_meta) using limit/offset/total_count/has_more."""
    limit = _int_param(args.get("limit"), PAGE_LIMIT_DEFAULT)
    offset = _int_param(args.get("offset"), PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX if limit > PAGE_LIMIT_MAX else PAGE_LIMIT_MIN
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# --- body parsing ---------------------------------------------------------
def body(req) -> dict:
    payload = req.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def require_str(payload: dict, name: str) -> str:
    value = payload.get(name)
    if value is None or not str(value).strip():
        fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
    return str(value)


def require_int(payload: dict, name: str) -> int:
    value = payload.get(name)
    if value is None:
        fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
    return coerce_int(value, name)


def coerce_int(value, name: str) -> int:
    if isinstance(value, bool) or value is None:
        fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an integer.")
    return parsed


def optional_int(payload: dict, name: str, default: int = None) -> int:
    if name not in payload or payload.get(name) is None:
        return default
    return coerce_int(payload[name], name)


def optional_str(payload: dict, name: str, default: str = None) -> str:
    value = payload.get(name)
    if value is None:
        return default
    return str(value)


def require_enum(payload: dict, name: str, allowed) -> str:
    value = require_str(payload, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", f"Field '{name}' has an unsupported value.")
    return value


def optional_enum(payload: dict, name: str, allowed, default: str = None) -> str:
    value = payload.get(name)
    if value is None:
        return default
    value = str(value)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", f"Field '{name}' has an unsupported value.")
    return value


def optional_list(payload: dict, name: str) -> list:
    value = payload.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an array.")
    return [str(v) for v in value]


# --- lookups (existence is resolved left to right, PRD §2.4) --------------
def get_requester(requester_id: str) -> dict:
    row = db.requesters.get(requester_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Requester not found.")
    return row


def get_worker(worker_id: str) -> dict:
    row = db.workers.get(worker_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    return row


def get_hit(hit_id: str) -> dict:
    row = db.hits.get(hit_id)
    if row is None:
        fail("ERR_NOT_FOUND", "HIT not found.")
    return row


def get_assignment(assignment_id: str) -> dict:
    row = db.assignments.get(assignment_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Assignment not found.")
    return row


def get_qualification_type(type_id: str) -> dict:
    row = db.qualification_types.get(type_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Qualification type not found.")
    return row


def get_exam(exam_id: str) -> dict:
    row = db.qualification_exams.get(exam_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Qualification exam not found.")
    return row


def get_deposit(deposit_id: str) -> dict:
    row = db.deposits.get(deposit_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Deposit not found.")
    return row


def get_payout(payout_id: str) -> dict:
    row = db.payouts.get(payout_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Payout request not found.")
    return row


# --- clock-relative predicates -------------------------------------------
def assignment_expired_now(assignment: dict) -> bool:
    """TRUE once the logical clock has reached accepted_at + HIT.time_limit_minutes."""
    hit = db.hits.get(assignment["hit_id"])
    if hit is None:
        return False
    from apptime import now_dt, parse

    limit = parse(assignment["accepted_at"]) + _minutes(hit["time_limit_minutes"])
    return now_dt() >= limit


def _minutes(value: int):
    from datetime import timedelta

    return timedelta(minutes=value)


def review_expires_at(submitted_at: str) -> str:
    from apptime import shift

    return shift(submitted_at, hours=REVIEW_WINDOW_HOURS)


def dispute_deadline(rejected_at: str) -> str:
    from apptime import shift

    return shift(rejected_at, hours=DISPUTE_WINDOW_HOURS)


def elapsed_minutes_since(instant: str) -> int:
    """Whole minutes floored between the logical clock and `instant`."""
    from apptime import now_dt, parse

    delta = (now_dt() - parse(instant)).total_seconds()
    return int(delta // 60)


def is_terminal_assignment(assignment: dict) -> bool:
    return assignment["status"] in {"APPROVED", "REJECTED", "RETURNED", "EXPIRED"}


def live_assignment_count(worker_id: str) -> int:
    return sum(
        1
        for a in db.assignments.values()
        if a["worker_id"] == worker_id
        and a["status"] in {"ACCEPTED", "SUBMITTED", "RETURNED"}
    )