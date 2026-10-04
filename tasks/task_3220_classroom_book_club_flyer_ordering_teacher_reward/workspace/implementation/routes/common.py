"""Shared route helpers."""

from flask import request

import db
from errors import raise_err


def get_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def path_get(store, entity_id, name="resource"):
    rec = store.get(entity_id)
    if rec is None:
        raise_err("ERR_NOT_FOUND", "%s %s not found" % (name, entity_id))
    return rec


def ref_get(store, entity_id, name="resource"):
    rec = store.get(entity_id)
    if rec is None:
        raise_err("ERR_REFERENCE_NOT_FOUND", "Referenced %s %s not found" % (name, entity_id))
    return rec


def req_field(body, field):
    val = body.get(field)
    if val is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return val


def req_int(body, field, min_val=None):
    val = req_field(body, field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise_err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if min_val is not None and val < min_val:
        raise_err("ERR_INVALID_REQUEST", "%s must be >= %d" % (field, min_val))
    return val


def req_enum(body, field, allowed):
    val = req_field(body, field)
    if val not in allowed:
        raise_err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum(body, field, allowed):
    val = body.get(field)
    if val is not None and val not in allowed:
        raise_err("ERR_INVALID_REQUEST", "%s must be one of %s or null" % (field, sorted(allowed)))
    return val
