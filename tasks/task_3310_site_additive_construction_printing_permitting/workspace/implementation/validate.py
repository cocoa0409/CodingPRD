"""Request body field validation helpers."""
from errors import raise_err, ERR_INVALID_REQUEST
from db import parse_dt


def body_dict(body):
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "field %s is required and must be a string" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a string" % field)
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v is None or v not in values:
        raise_err(
            ERR_INVALID_REQUEST,
            "field %s must be one of %s" % (field, sorted(values)),
        )
    return v


def req_int(body, field, minimum=None, gt=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "field %s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "field %s must be >= %s" % (field, minimum))
    if gt is not None and not v > gt:
        raise_err(ERR_INVALID_REQUEST, "field %s must be > %s" % (field, gt))
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % field)
    return v


def req_num(body, field, minimum=None, gt=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "field %s is required and must be a number" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "field %s must be >= %s" % (field, minimum))
    if gt is not None and not v > gt:
        raise_err(ERR_INVALID_REQUEST, "field %s must be > %s" % (field, gt))
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "field %s is required and must be a boolean" % field)
    return v


def req_dt(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "field %s is required and must be a datetime string" % field)
    try:
        return parse_dt(v)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "field %s is not a valid ISO-8601 datetime" % field)
