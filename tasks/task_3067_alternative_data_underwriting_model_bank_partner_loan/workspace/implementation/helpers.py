"""Shared helpers: resource creation, serialization, pagination, input checks."""
import uuid

from flask import request

from db import store
from errors import invalid_request, validation
from response import logical_now_iso

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

MODEL_STATUSES = {"DRAFT", "VALIDATED", "ACTIVE", "RETIRED"}
PARTNER_TYPES = {"BANK", "CREDIT_UNION", "LOAN_BUYER", "SECURITIZATION_TRUST"}
PARTNER_STATUSES = {"ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"}
CREDIT_BOX_STATUSES = {"DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"}
EDUCATION_LEVELS = {"HIGH_SCHOOL", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE"}
EMPLOYMENT_STATUSES = {"EMPLOYED", "SELF_EMPLOYED", "UNEMPLOYED", "RETIRED"}
CHANNELS = {"DIRECT", "PARTNER_REFERRAL"}
APPLICATION_STATUSES = {
    "SUBMITTED", "VERIFICATION_PENDING", "DOCS_REQUIRED",
    "UNDERWRITTEN", "APPROVED", "DECLINED", "WITHDRAWN",
}
VERIFICATION_KINDS = {"INCOME", "IDENTITY"}
VERIFICATION_STATUSES = {
    "PENDING", "INSTANT_PASSED", "INSTANT_FAILED",
    "MANUAL_REVIEW", "MANUAL_PASSED", "MANUAL_FAILED",
}
REVIEW_TYPES = {"VARIABLE_EXCLUSION", "DISPARATE_IMPACT"}
REVIEW_OUTCOMES = {"PENDING", "PASSED", "FAILED"}
LOAN_STATUSES = {
    "FUNDED", "CURRENT", "DELINQUENT", "DEFAULTED", "CHARGED_OFF", "PAID_OFF",
}
ALLOCATION_CHANNELS = {
    "PARTNER_RETAINED", "REFERRAL_RETAINED", "WHOLE_LOAN_SALE",
    "SECURITIZATION", "UNALLOCATED",
}
SERVICING_EVENT_TYPES = {
    "PAYMENT_APPLIED", "LATE_FEE_ASSESSED", "DELINQUENCY_ADVANCED",
    "DEFAULT_DECLARED", "CHARGE_OFF_REPORTED", "PAYOFF_RECORDED",
}
POOL_STATUSES = {"OPEN", "CLOSED"}

# ---------------------------------------------------------------------------
# Identity / timestamps
# ---------------------------------------------------------------------------

_seq = 0


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock timestamp for created_at/updated_at/occurred_at."""
    return logical_now_iso()


# ---------------------------------------------------------------------------
# Resource construction
# ---------------------------------------------------------------------------

def new_resource(common=True):
    global _seq
    _seq += 1
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": _seq}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination / filters
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise validation("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise validation("limit out of range")
    if offset < 0:
        raise validation("offset out of range")
    return limit, offset


def list_collection(records, filters):
    """filters: list of (query_param, record_field) equality filters."""
    items = list(records)
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        items = [r for r in items if str(r.get(field)) == raw]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise invalid_request(f"Missing or invalid field: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Missing or invalid field: {field}")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Missing or invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise invalid_request(f"Missing or invalid field: {field}")
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise invalid_request(f"Missing or invalid field: {field}")
    return v
