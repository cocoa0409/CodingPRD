"""Validation helpers for request bodies."""
from clock import parse_dt
from errors import err_invalid_request, err_invalid_enum

REGIONS = {"NA", "EU", "APAC", "ROW"}
CURRENCIES = {"USD", "EUR", "GBP"}
LEVEL_STATUSES = {"OPEN", "CLOSED", "RETIRED"}
GOAL_STATUSES = {"LOCKED", "UNLOCKED"}
ADDON_STATUSES = {"OPEN", "RETIRED"}


def body_of(request):
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("JSON body must be an object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} is required and must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise err_invalid_request(f"{field} must be a string")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} is required and must be a number")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str):
        raise err_invalid_request(f"{field} is required")
    if v not in allowed:
        raise err_invalid_enum(f"{field} must be one of {sorted(allowed)}")
    return v


def req_dt(data, field):
    v = data.get(field)
    dt = parse_dt(v)
    if dt is None:
        raise err_invalid_request(f"{field} is required and must be an ISO-8601 datetime")
    return dt


def opt_dt(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    dt = parse_dt(data.get(field))
    if dt is None:
        raise err_invalid_request(f"{field} must be an ISO-8601 datetime")
    return dt


def req_bool(data, field, default=None):
    v = data.get(field, default)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v
