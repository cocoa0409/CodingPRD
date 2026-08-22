"""Request-shape validation (ladder rung 5 -> ERR_INVALID_REQUEST 400)."""

from decimal import Decimal

from errors import ApiError, ERR_INVALID_REQUEST
from store import parse_iso, iso

MISSING = object()


def bad(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def _present(body, field):
    return body.get(field, MISSING)


def _missing_or_null(value):
    return value is MISSING or value is None


def v_string(body, field, required=True, default=None, pattern=None, nullable=False,
             allow_empty=True):
    value = _present(body, field)
    if value is MISSING:
        if required:
            bad("Field '%s' is required." % field)
        return default
    if value is None:
        if nullable:
            return None
        if required:
            bad("Field '%s' must not be null." % field)
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must not be empty." % field)
    if pattern is not None and pattern.match(value) is None:
        bad("Field '%s' does not match the required format." % field)
    return value


def v_bool(body, field, required=True, default=None):
    value = _present(body, field)
    if _missing_or_null(value):
        if required:
            bad("Field '%s' is required." % field)
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def v_int(body, field, required=True, default=None, gt=None, ge=None, lt=None,
          le=None, nullable=False):
    value = _present(body, field)
    if value is MISSING:
        if required:
            bad("Field '%s' is required." % field)
        return default
    if value is None:
        if nullable:
            return None
        if required:
            bad("Field '%s' must not be null." % field)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        # A Decimal that happens to be integral is still not an integer literal
        # unless it was written without a fractional part.
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % field)
    return _check_bounds(field, value, gt, ge, lt, le)


def v_number(body, field, required=True, default=None, gt=None, ge=None, lt=None,
             le=None, max_dp=None, nullable=False):
    value = _present(body, field)
    if value is MISSING:
        if required:
            bad("Field '%s' is required." % field)
        return default
    if value is None:
        if nullable:
            return None
        if required:
            bad("Field '%s' must not be null." % field)
        return default
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % field)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        value = Decimal(str(value))
    else:
        bad("Field '%s' must be a number." % field)
    if not value.is_finite():
        bad("Field '%s' must be a finite number." % field)
    if max_dp is not None:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_dp:
            bad("Field '%s' carries more than %d decimal places." % (field, max_dp))
    return _check_bounds(field, value, gt, ge, lt, le)


def _check_bounds(field, value, gt, ge, lt, le):
    if gt is not None and not value > gt:
        bad("Field '%s' must be greater than %s." % (field, gt))
    if ge is not None and not value >= ge:
        bad("Field '%s' must be at least %s." % (field, ge))
    if lt is not None and not value < lt:
        bad("Field '%s' must be less than %s." % (field, lt))
    if le is not None and not value <= le:
        bad("Field '%s' must be at most %s." % (field, le))
    return value


def v_enum(body, field, choices, required=True, default=None, nullable=False):
    value = _present(body, field)
    if value is MISSING:
        if required:
            bad("Field '%s' is required." % field)
        return default
    if value is None:
        if nullable:
            return None
        if required:
            bad("Field '%s' must not be null." % field)
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if value not in choices:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(choices))))
    return value


def v_datetime(body, field, required=True, default=None, nullable=False):
    """Returns (normalized_string, datetime).

    PRD 2.7: "Timestamps returned by the API are ISO 8601 UTC with three
    fractional-second digits", so a client-supplied instant is normalized to
    that shape before it is stored and echoed.
    """
    value = _present(body, field)
    if value is MISSING:
        if required:
            bad("Field '%s' is required." % field)
        return default, None
    if value is None:
        if nullable:
            return None, None
        if required:
            bad("Field '%s' must not be null." % field)
        return default, None
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime string." % field)
    try:
        parsed = parse_iso(value)
    except Exception:
        bad("Field '%s' must be an ISO 8601 datetime string." % field)
    return iso(parsed), parsed


def v_string_array(body, field, required=True, default=None):
    value = _present(body, field)
    if _missing_or_null(value):
        if required:
            bad("Field '%s' is required." % field)
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    for entry in value:
        if not isinstance(entry, str):
            bad("Every entry of '%s' must be a string." % field)
    return list(value)


def v_components(body, field="components", required=True):
    """Blend-trial component draw list: >= 2 entries, distinct source_lot_id."""
    value = _present(body, field)
    if _missing_or_null(value):
        if required:
            bad("Field '%s' is required." % field)
        return None
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if len(value) < 2:
        bad("Field '%s' must hold at least two entries." % field)
    parsed = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            bad("Every entry of '%s' must be an object." % field)
        lot_id = entry.get("source_lot_id", MISSING)
        if _missing_or_null(lot_id) or not isinstance(lot_id, str):
            bad("Every component requires a string 'source_lot_id'.")
        volume = entry.get("volume_gallons", MISSING)
        if _missing_or_null(volume) or isinstance(volume, bool):
            bad("Every component requires a numeric 'volume_gallons'.")
        if isinstance(volume, int):
            volume = Decimal(volume)
        elif isinstance(volume, float):
            volume = Decimal(str(volume))
        elif not isinstance(volume, Decimal):
            bad("Every component requires a numeric 'volume_gallons'.")
        if not volume.is_finite() or volume <= 0:
            bad("Every component's 'volume_gallons' must be greater than zero.")
        if lot_id in seen:
            bad("Component 'source_lot_id' values must be distinct.")
        seen.add(lot_id)
        parsed.append({"source_lot_id": lot_id, "volume_gallons": volume})
    return parsed


def v_pagination(args):
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit))
        except Exception:
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must lie between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset))
        except Exception:
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit], len(items)
