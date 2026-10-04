"""Shared helpers: logical clock, ids, timestamps, common-field handling,
request-body validation, and domain constant sets."""
import math
import re
import uuid
from datetime import datetime, date, timedelta, timezone

from db import db
from errors import err_invalid_request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def logical_now_dt():
    """Current logical instant as a UTC datetime."""
    s = db.logical_now_iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def logical_today():
    """Current logical calendar date."""
    return logical_now_dt().date()


def set_logical_now(to_iso8601):
    db.logical_now_iso = to_iso8601


def iso_now_3f():
    """Wall-clock timestamp for created_at/updated_at fields (ISO 8601 UTC, 3 fractional digits)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------

def stamp_new(record):
    ts = iso_now_3f()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = iso_now_3f()
    record["version"] = record.get("version", 1) + 1
    return record


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise err_invalid_request("expected ISO 8601 calendar date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise err_invalid_request("invalid calendar date")


def date_to_str(d):
    return d.isoformat()


def add_days_str(date_s, days):
    return (date.fromisoformat(date_s) + timedelta(days=days)).isoformat()


def day_diff(a_str, b_str):
    """a - b in whole days."""
    return (date.fromisoformat(a_str) - date.fromisoformat(b_str)).days


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    if not request.is_json:
        raise err_invalid_request("request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    return body


def req_field(body, name, types, allow_none=False):
    if name not in body:
        raise err_invalid_request(f"missing required field: {name}")
    v = body[name]
    if v is None:
        if allow_none:
            return None
        raise err_invalid_request(f"field {name} must not be null")
    # bool is subclass of int — guard against bools being accepted as ints
    if types and not isinstance(v, types):
        raise err_invalid_request(f"field {name} has wrong type")
    if int in (types if isinstance(types, tuple) else (types,)) and isinstance(v, bool):
        raise err_invalid_request(f"field {name} has wrong type")
    return v


def opt_field(body, name, types=None, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if types and not isinstance(v, types):
        raise err_invalid_request(f"field {name} has wrong type")
    if types and int in (types if isinstance(types, tuple) else (types,)) and isinstance(v, bool):
        raise err_invalid_request(f"field {name} has wrong type")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name, (str,))
    if v not in allowed:
        raise err_invalid_request(f"field {name} not in declared enum set")
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(f"field {name} not in declared enum set")
    return v


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

COVERED_DIAGNOSES = {"E11.9", "E10.9", "O24.415"}
EARLY_REFILL_TOLERANCE_FRACTION = 0.25
WATCH_THRESHOLD = 3
HOLD_THRESHOLD = 7
SAVINGS_CARD_EXCLUDED_STATES = {"MA", "CA", "WA"}
CARD_PROGRAM_CAP_CENTS = 20000
CARD_ANNUAL_FILL_MULTIPLIER = 12
PRO_RATA_MIN_GENERATION = 3

PAYER_SPECIALTIES = {"ENDOCRINOLOGY", "PRIMARY_CARE", "OTHER"}
BENEFIT_ROUTES = {"PHARMACY", "DME"}
COVERAGE_POLICIES = {"STRICT", "STANDARD", "LENIENT"}
READER_CHANNELS = {"READER", "APP", "HYBRID"}
BINDING_CHANNELS = {"READER", "APP"}
INSULIN_USES = {"INTENSIVE", "BASAL_ONLY", "NONE"}
FAILURE_CATEGORIES = {"NO_READINGS", "INACCURATE", "ADHESIVE_FAILURE", "SENSOR_ERROR", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
EVENT_TYPES = {"SKIN_IRRITATION", "INACCURACY_HARM", "SENSOR_DETACHED", "ALLERGIC_REACTION", "OTHER"}
DENIAL_REASONS = {"DIAGNOSIS_NOT_COVERED", "INSUFFICIENT_INSULIN_USE", "MISSING_DOCUMENTATION", "PAYER_INACTIVE"}


# ---------------------------------------------------------------------------
# Coverage criteria evaluation (per payer policy)
# ---------------------------------------------------------------------------

def evaluate_criteria(payer, prescription):
    """Return (diag_met, insulin_met, doc_met) per payer.cgm_coverage_policy."""
    policy = payer["cgm_coverage_policy"]
    diag = prescription["diagnosis_code"] in COVERED_DIAGNOSES
    insulin_use = prescription["insulin_use"]
    doc = bool(prescription["documentation_attached"])
    if policy == "STRICT":
        insulin = insulin_use == "INTENSIVE"
        doc_met = doc
    elif policy == "STANDARD":
        insulin = insulin_use in ("INTENSIVE", "BASAL_ONLY")
        doc_met = True  # documentation not required under STANDARD
    else:  # LENIENT
        insulin = insulin_use != "NONE"
        doc_met = True  # documentation waived under LENIENT
    return diag, insulin, doc_met


def criteria_pass(payer, prescription):
    diag, insulin, doc = evaluate_criteria(payer, prescription)
    policy = payer["cgm_coverage_policy"]
    if policy == "STRICT":
        return diag and insulin and doc
    if policy == "STANDARD":
        return diag and insulin
    # LENIENT
    return diag and insulin
