"""Shape, domain and writability checks - the low layers of the ladder (PRD 2.8)."""
import re

from flask import request

from errors import fail
from util import D, parse_dt
import db

CAS_RE = re.compile(r"^[0-9]{2,7}-[0-9]{2}-[0-9]$")

MISSING = object()


def body_json():
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return raw


def present(body, name):
    return name in body and body[name] is not None


def _required_missing(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)


def v_str(body, name, required=False, minlen=None, maxlen=None, default=None):
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if minlen is not None and len(value) < minlen:
        fail("ERR_INVALID_REQUEST", "%s is shorter than %d characters" % (name, minlen))
    if maxlen is not None and len(value) > maxlen:
        fail("ERR_INVALID_REQUEST", "%s is longer than %d characters" % (name, maxlen))
    return value


def v_enum(body, name, values, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in values:
        fail("ERR_INVALID_REQUEST", "%s is not a declared value" % name)
    return value


def v_num(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    return D(value)


def v_int(body, name, required=False, default=None):
    value = v_num(body, name, required=required, default=MISSING)
    if value is MISSING:
        return default
    if value != value.to_integral_value():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return int(value)


def v_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def v_dt(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    return parse_dt(body[name], name)


def v_id(body, name, required=False, default=None):
    return v_str(body, name, required=required, default=default)


def v_channels(body, name, required=False, values=(), default=None):
    """distribution_channels: non-empty, no duplicates, declared members only."""
    if name not in body or body[name] is None:
        if required:
            _required_missing(body, name)
        return default
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or item not in values:
            fail("ERR_INVALID_REQUEST", "%s contains an undeclared value" % name)
    if len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "%s must not contain duplicates" % name)
    return list(value)


# --- ladder position 5: numeric domains -------------------------------------
NON_NEGATIVE = (
    "declared_concentration_ppm", "lab_result_ppm", "annual_units",
    "alleged_units", "requested_attorney_fees_cents", "indemnity_cap_cents",
    "target_concentration_ppm",
)
STRICTLY_POSITIVE = (
    "lab_loq_ppm", "quantity_grams_per_unit", "uses_per_day", "label_area_sq_in",
)


def v_domain(body):
    for name in NON_NEGATIVE:
        if present(body, name) and D(body[name]) < 0:
            fail("ERR_VALUE_OUT_OF_RANGE", "%s must not be negative" % name)
    for name in STRICTLY_POSITIVE:
        if present(body, name) and D(body[name]) <= 0:
            fail("ERR_VALUE_OUT_OF_RANGE", "%s must be strictly positive" % name)


def v_level_domain(body):
    """safe_harbor_level_ug_per_day zero or negative while the basis is not NONE."""
    if present(body, "safe_harbor_level_ug_per_day") and \
            body.get("safe_harbor_basis") != "NONE" and \
            D(body["safe_harbor_level_ug_per_day"]) <= 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "safe_harbor_level_ug_per_day must be positive")


# --- ladder position 6: fraction domains ------------------------------------
def v_fractions(body):
    if present(body, "contact_factor"):
        value = D(body["contact_factor"])
        if value < 0 or value > 1:
            fail("ERR_VALUE_OUT_OF_RANGE", "contact_factor must lie in [0.0, 1.0]")
    if present(body, "parent_mass_fraction"):
        value = D(body["parent_mass_fraction"])
        if value <= 0 or value > 1:
            fail("ERR_VALUE_OUT_OF_RANGE", "parent_mass_fraction must lie in (0.0, 1.0]")


# --- ladder position 7: CAS registry shape ----------------------------------
def v_cas(value):
    if value is None or not CAS_RE.match(value):
        fail("ERR_INVALID_CAS_NUMBER", "cas_number does not match the CAS registry shape")


# --- ladder position 10: interval ordering ----------------------------------
def v_interval(start, end):
    if start is not None and end is not None and not end > start:
        fail("ERR_INVALID_INTERVAL", "the end of an interval must be strictly after its start")


# --- ladder layer 4 rule 4: writability -------------------------------------
def v_writable(body, allowed):
    allowed = set(allowed)
    for key in body.keys():
        if key in allowed:
            continue
        if key in db.NON_WRITABLE or key in ("expected_product_version", "expected_notice_version"):
            fail("ERR_FIELD_NOT_WRITABLE", "%s is not writable on this endpoint" % key)


# --- ladder position 11: declared triggers ----------------------------------
def v_action(body, triggers):
    action = body.get("action")
    if action is None:
        fail("ERR_INVALID_REQUEST", "action is required")
    if not isinstance(action, str):
        fail("ERR_INVALID_REQUEST", "action must be a string")
    if action not in triggers:
        fail("ERR_UNKNOWN_ACTION", "%s is not a declared trigger of this state machine" % action)
    return action


# --- ladder layer 2 ---------------------------------------------------------
def must_exist(kind, row_id, label=None):
    row = db.get(kind, row_id)
    if row is None:
        fail("ERR_NOT_FOUND", "%s %s does not resolve" % (label or kind, row_id))
    return row


def fk(kind, body, name, required=False):
    value = body.get(name)
    if value is None:
        if required:
            _required_missing(body, name)
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return must_exist(kind, value, name)


def v_version(body, name):
    """expected_product_version / expected_notice_version: a non-optional integer."""
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = body[name]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if isinstance(value, str):
        text = value.strip()
        if not re.match(r"^-?[0-9]+$", text):
            fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
        return int(text)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if D(value) != D(value).to_integral_value():
            fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
        return int(value)
    fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
