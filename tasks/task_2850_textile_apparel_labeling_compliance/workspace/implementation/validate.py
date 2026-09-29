"""Request-shape validation (ladder step 6) and body reference resolution (step 5)."""
import re

from flask import request

from errors import fail
from store import db
from util import dec, r1, r2, r3

MISSING = object()


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


def _missing(field):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)


def req_string(payload, field, min_len=1, max_len=None, pattern=None, nonblank=True):
    if not present(payload, field):
        _missing(field)
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if nonblank and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % field)
    check = value
    if min_len is not None and len(check) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % field)
    if max_len is not None and len(check) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % field)
    if pattern is not None and not re.match(pattern, check):
        fail("ERR_INVALID_REQUEST", "Field '%s' has an invalid format." % field)
    return value


def req_enum(payload, field, members):
    if not present(payload, field):
        _missing(field)
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(payload, field, members, default=None):
    if not present(payload, field):
        return default
    return req_enum(payload, field, members)


def req_int(payload, field, minimum=None, maximum=None, allowed=None):
    if not present(payload, field):
        _missing(field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % field)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % field)
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s."
             % (field, ", ".join(str(a) for a in allowed)))
    return value


def req_number(payload, field, places, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
    if not present(payload, field):
        _missing(field)
    return _number(payload[field], field, places, minimum, maximum, exclusive_min, exclusive_max)


def _number(value, field, places, minimum, maximum, exclusive_min, exclusive_max):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    try:
        raw = dec(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    quant = {1: r1, 2: r2, 3: r3}[places](raw)
    if minimum is not None and quant < dec(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % field)
    if maximum is not None and quant > dec(maximum):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % field)
    if exclusive_min is not None and quant <= dec(exclusive_min):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (field, exclusive_min))
    if exclusive_max is not None and quant >= dec(exclusive_max):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be less than %s." % (field, exclusive_max))
    return quant


def req_array(payload, field, non_empty=True):
    if not present(payload, field):
        _missing(field)
    value = payload[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % field)
    return value


def distinct_codes(values, field, pattern, min_len=None, max_len=None):
    out = []
    for entry in values:
        if not isinstance(entry, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain strings." % field)
        if not re.match(pattern, entry):
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an invalid value." % field)
        if min_len is not None and len(entry) < min_len:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains a value that is too short." % field)
        if max_len is not None and len(entry) > max_len:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains a value that is too long." % field)
        if entry in out:
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain distinct values." % field)
        out.append(entry)
    return out


def distinct_members(values, field, members):
    out = []
    for entry in values:
        if not isinstance(entry, str) or entry not in members:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an unknown value." % field)
        if entry in out:
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain distinct values." % field)
        out.append(entry)
    return out


# --- body reference resolution (ladder step 5) ----------------------------
def find_brand(brand_id):
    row = db.brands.get(brand_id) if isinstance(brand_id, str) else None
    if row is None:
        fail("ERR_BRAND_NOT_FOUND", "Brand not found.")
    return row


def find_style(style_id):
    row = db.styles.get(style_id) if isinstance(style_id, str) else None
    if row is None:
        fail("ERR_STYLE_NOT_FOUND", "Style not found.")
    return row


def find_material_input(mid):
    row = db.material_inputs.get(mid) if isinstance(mid, str) else None
    if row is None:
        fail("ERR_MATERIAL_INPUT_NOT_FOUND", "Material input not found.")
    return row


def find_lab_test(tid):
    row = db.lab_tests.get(tid) if isinstance(tid, str) else None
    if row is None:
        fail("ERR_LAB_TEST_NOT_FOUND", "Lab test not found.")
    return row


def find_origin_determination(oid):
    row = db.origin_determinations.get(oid) if isinstance(oid, str) else None
    if row is None:
        fail("ERR_ORIGIN_DETERMINATION_NOT_FOUND", "Origin determination not found.")
    return row


def find_label_spec(lid):
    row = db.label_specs.get(lid) if isinstance(lid, str) else None
    if row is None:
        fail("ERR_LABEL_SPEC_NOT_FOUND", "Label spec not found.")
    return row


def find_shipment(sid):
    row = db.import_shipments.get(sid) if isinstance(sid, str) else None
    if row is None:
        fail("ERR_IMPORT_SHIPMENT_NOT_FOUND", "Import shipment not found.")
    return row


def find_audit(aid):
    row = db.compliance_audits.get(aid) if isinstance(aid, str) else None
    if row is None:
        fail("ERR_COMPLIANCE_AUDIT_NOT_FOUND", "Compliance audit not found.")
    return row


def find_finding(fid):
    row = db.audit_findings.get(fid) if isinstance(fid, str) else None
    if row is None:
        fail("ERR_AUDIT_FINDING_NOT_FOUND", "Audit finding not found.")
    return row


def find_market(code):
    if not isinstance(code, str):
        fail("ERR_MARKET_REQUIREMENT_NOT_FOUND", "Market requirement not found.")
    for row in db.market_requirements.values():
        if row["market_code"] == code:
            return row
    fail("ERR_MARKET_REQUIREMENT_NOT_FOUND", "Market requirement not found.")


def market_of(code):
    """Non-raising regime lookup."""
    for row in db.market_requirements.values():
        if row["market_code"] == code:
            return row
    return None
