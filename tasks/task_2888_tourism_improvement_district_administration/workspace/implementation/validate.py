"""Request-shape validation (ladder rung 4) and existence lookups (rung 5)."""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import fail

_MISSING = object()


class Inst(object):
    """A parsed instant plus the literal text the caller supplied."""

    __slots__ = ("dt", "raw")

    def __init__(self, dt, raw):
        self.dt = dt
        self.raw = raw


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _raw(b, name, required):
    value = b.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return _MISSING
    return value


def text(b, name, required=True, default=None, min_len=1, max_len=None):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s may be at most %d characters." % (name, max_len))
    return value


def enum(b, name, allowed, required=True, default=None):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def integer(b, name, required=True, default=None, minimum=None, maximum=None):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s may not be larger than %d." % (name, maximum))
    return value


def cents(b, name, required=True, default=None, minimum=0):
    return integer(b, name, required=required, default=default, minimum=minimum)


def flag(b, name, required=False, default=None):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def ratio(b, name, required=True, default=None, minimum=None, maximum=None):
    """A four-decimal-place ratio (PRD 2.6)."""
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    if not parsed.is_finite():
        fail("ERR_INVALID_REQUEST", "%s must be a finite number." % name)
    parsed = store.rhu4(parsed)
    if minimum is not None and parsed < minimum:
        fail("ERR_INVALID_REQUEST", "%s may not be smaller than %s." % (name, minimum))
    if maximum is not None and parsed > maximum:
        fail("ERR_INVALID_REQUEST", "%s may not be larger than %s." % (name, maximum))
    return parsed


def instant(b, name, required=True):
    value = _raw(b, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 string." % name)
    try:
        parsed = store.parse_instant(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant." % name)
    return Inst(parsed, value)


def id_ref(b, name, required=True, default=None):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    return value


def array(b, name, required=True, default=None, min_len=1):
    value = _raw(b, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must hold at least %d entries." % (name, min_len))
    return value


def assign(rec, field, inst):
    """Store a caller-supplied instant, remembering its literal text for echo."""
    if inst is None:
        rec[field] = None
        return None
    rec[field] = inst.dt
    rec["_raw"][field] = inst.raw
    return inst.dt


# ---------------------------------------------------------------------------
# rung 5 — existence
# ---------------------------------------------------------------------------
def _lookup(collection, key, error_id):
    rec = getattr(store.state, collection).get(key)
    if rec is None:
        fail(error_id, "%s does not identify an existing record." % key)
    return rec


def district(district_id):
    return _lookup("districts", district_id, "ERR_DISTRICT_NOT_FOUND")


def business(business_id):
    return _lookup("businesses", business_id, "ERR_LODGING_BUSINESS_NOT_FOUND")


def drive(drive_id):
    return _lookup("drives", drive_id, "ERR_PETITION_DRIVE_NOT_FOUND")


def signature(signature_id):
    return _lookup("signatures", signature_id, "ERR_PETITION_SIGNATURE_NOT_FOUND")


def period(period_id):
    return _lookup("periods", period_id, "ERR_ASSESSMENT_PERIOD_NOT_FOUND")


def statement(statement_id):
    return _lookup("statements", statement_id, "ERR_ASSESSMENT_STATEMENT_NOT_FOUND")


def remittance(remittance_id):
    return _lookup("remittances", remittance_id, "ERR_REMITTANCE_NOT_FOUND")


def plan(plan_id):
    return _lookup("plans", plan_id, "ERR_WORK_PLAN_NOT_FOUND")


def program(program_id):
    return _lookup("programs", program_id, "ERR_MARKETING_PROGRAM_NOT_FOUND")


def claim(claim_id):
    return _lookup("claims", claim_id, "ERR_ROOM_NIGHT_CLAIM_NOT_FOUND")


def record(record_id):
    return _lookup("records", record_id, "ERR_TRANSPARENCY_RECORD_NOT_FOUND")


def dispute(dispute_id):
    return _lookup("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
