"""Request shape validation - step 5 of the order of rejection (PRD 2.10).

Every violation here is ERR_INVALID_REQUEST (HTTP 400).  Unknown fields in a
body are ignored rather than rejected.
"""

import errors
from errors import ApiError
from util import parse_dt

_MISSING = object()


def bad(message):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def _present(body, name):
    if name not in body:
        return False
    return body[name] is not None


def s_str(body, name, required=True, default=None, min_len=None, max_len=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if required and value == "":
        bad("%s may not be empty." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def s_num(body, name, required=True, default=None,
          gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        bad("%s must be a finite number." % name)
    if gt is not None and not value > gt:
        bad("%s must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        bad("%s must be at least %s." % (name, ge))
    if lt is not None and not value < lt:
        bad("%s must be less than %s." % (name, lt))
    if le is not None and not value <= le:
        bad("%s must be at most %s." % (name, le))
    return value


def s_int(body, name, required=True, default=None,
          gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool):
        bad("%s must be an integer." % name)
    if isinstance(value, float):
        if not value.is_integer():
            bad("%s must be an integer." % name)
        value = int(value)
    if not isinstance(value, int):
        bad("%s must be an integer." % name)
    if gt is not None and not value > gt:
        bad("%s must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        bad("%s must be at least %s." % (name, ge))
    if lt is not None and not value < lt:
        bad("%s must be less than %s." % (name, lt))
    if le is not None and not value <= le:
        bad("%s must be at most %s." % (name, le))
    return value


def s_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def s_num_enum(body, name, allowed, required=True, default=None):
    """A numeric field restricted to a fixed set of declared values."""
    value = s_num(body, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    for candidate in allowed:
        if abs(value - candidate) < 1e-12:
            return candidate
    bad("%s must be one of %s." % (name, ", ".join(str(a) for a in allowed)))


def s_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def s_dt(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    parsed = parse_dt(body[name])
    if parsed is None:
        bad("%s must be an ISO-8601 UTC instant." % name)
    return parsed


def s_array(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if not value:
        bad("%s may not be empty." % name)
    return value


def s_str_array(body, name, required=True, default=None):
    value = s_array(body, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    for item in value:
        if not isinstance(item, str) or item == "":
            bad("%s must hold non-empty strings." % name)
    return value


def s_point_readings(body, name="point_readings"):
    """Array of {point_index >= 1, elevation_in} objects."""
    value = s_array(body, name)
    parsed = []
    for item in value:
        if not isinstance(item, dict):
            bad("%s entries must be objects." % name)
        index = s_int(item, "point_index", required=True, ge=1)
        elevation = s_num(item, "elevation_in", required=True)
        parsed.append({"point_index": index, "elevation_in": elevation})
    return parsed


def s_spot_readings(body, name="spot_readings"):
    """Array of spots, each spot exactly three numeric gauge readings."""
    value = s_array(body, name)
    parsed = []
    for spot in value:
        if not isinstance(spot, list) or len(spot) != 3:
            bad("every spot in %s must carry exactly three gauge readings." % name)
        readings = []
        for reading in spot:
            if isinstance(reading, bool) or not isinstance(reading, (int, float)):
                bad("every gauge reading in %s must be numeric." % name)
            readings.append(float(reading))
        parsed.append(readings)
    return parsed
