"""Shared primitives: record creation/stamping, round-half-up helpers, and
request-body accessors.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db, iso, utcnow_iso

ROLES = {"Borrower", "Cosigner", "School", "Underwriter", "Servicer", "PlatformAdmin"}

# Entity name -> role whose X-User-ID is entity-backed (PRD 2.1 / SCAFFOLD 1.7)
ENTITY_ROLE = {
    "Borrower": "Borrower",
    "Cosigner": "Cosigner",
    "School": "School",
}


# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_half_up_int(value):
    """Round to zero decimal places, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quantize(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def whole_days(delta):
    """Whole days with any fractional part discarded (floor for positives)."""
    return delta.days if delta.days > 0 else 0


# --------------------------------------------------------------------------
# record stamping
# --------------------------------------------------------------------------
def stamp(record, new=False):
    """Fill the system-managed common fields (PRD 2.6)."""
    now = db.now()
    now_iso = iso(now)
    if new:
        record["id"] = db.new_id()
        record["created_at"] = now_iso
        record["created_seq"] = db.next_seq()
        record["updated_at"] = now_iso
        record["version"] = 1
    else:
        record["updated_at"] = now_iso
        record["version"] = record.get("version", 1) + 1
    return record


def touch(record):
    """Refresh updated_at and bump version after a mutation."""
    record["updated_at"] = iso(db.now())
    record["version"] = record.get("version", 1) + 1
    return record


# --------------------------------------------------------------------------
# request accessors
# --------------------------------------------------------------------------
def body_of(req):
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def query_int(req, name, default, minimum=None, maximum=None):
    raw = req.args.get(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def enum(value, allowed, error_id="ERR_INVALID_REQUEST"):
    from errors import fail
    if value not in allowed:
        fail(error_id, "value %r is not a declared member" % (value,))


def required(data, field, error_id="ERR_INVALID_REQUEST"):
    from errors import fail
    if field not in data or data[field] is None:
        fail(error_id, "required field %s is missing" % field)
    return data[field]