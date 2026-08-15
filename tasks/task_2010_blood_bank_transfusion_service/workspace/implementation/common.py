"""Shared request plumbing: auth (PRD 2.1), body schema validators (2.9 stage 4),
path-id and body-FK resolution (2.9 stages 3 and 5)."""

from functools import wraps

from flask import request

import store
from errors import ApiError
import errors as E
from timeutil import parse_dt, valid_date_ymd


# ---------------------------------------------------------------------------
# Auth — validation pipeline stages 1 and 2.
# ---------------------------------------------------------------------------

def endpoint(roles):
    """Decorator enforcing X-User-ID / X-User-Role presence then role permission."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or role is None or not user_id.strip() or not role.strip():
                raise ApiError(
                    E.ERR_MISSING_CONTEXT, 400,
                    "X-User-ID and X-User-Role headers are required and must be non-empty",
                )
            if role not in roles:
                raise ApiError(
                    E.ERR_UNAUTHORIZED_ROLE, 403,
                    f"Role {role} is not permitted to call this endpoint",
                )
            return fn(*args, user_id=user_id.strip(), role=role, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# Body parsing and field validators — pipeline stage 4 (ERR_INVALID_REQUEST).
# ---------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _invalid(field, detail):
    raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Field '{field}': {detail}")


def req_field(body, name):
    if name not in body or body[name] is None:
        _invalid(name, "is required")
    return body[name]


def as_str(value, name, allow_empty=False):
    if not isinstance(value, str):
        _invalid(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _invalid(name, "must be a non-empty string")
    return value


def req_str(body, name, allow_empty=False):
    return as_str(req_field(body, name), name, allow_empty)


def opt_str(body, name, default=None, allow_empty=False):
    if name not in body or body[name] is None:
        return default
    return as_str(body[name], name, allow_empty)


def _is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float) and value.is_integer():
        return True
    return False


def as_int(value, name):
    if not _is_int(value):
        _invalid(name, "must be an integer")
    return int(value)


def req_int(body, name, min_value=None, max_value=None):
    value = as_int(req_field(body, name), name)
    if min_value is not None and value < min_value:
        _invalid(name, f"must be >= {min_value}")
    if max_value is not None and value > max_value:
        _invalid(name, f"must be <= {max_value}")
    return value


def opt_int(body, name, default=None, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        return default
    value = as_int(body[name], name)
    if min_value is not None and value < min_value:
        _invalid(name, f"must be >= {min_value}")
    if max_value is not None and value > max_value:
        _invalid(name, f"must be <= {max_value}")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        _invalid(name, "must be a boolean")
    return value


def req_bool(body, name):
    return as_bool(req_field(body, name), name)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    return as_bool(body[name], name)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        _invalid(name, f"must be one of {allowed}")
    return value


def req_enum(body, name, allowed):
    return as_enum(req_field(body, name), name, allowed)


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return as_enum(body[name], name, allowed)


def as_dt(value, name):
    dt = parse_dt(value)
    if dt is None:
        _invalid(name, "must be an ISO-8601 timestamp")
    return dt


def req_dt(body, name):
    return as_dt(req_field(body, name), name)


def opt_dt(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return as_dt(body[name], name)


def as_str_list(value, name, allowed=None):
    if not isinstance(value, list):
        _invalid(name, "must be an array")
    for item in value:
        if not isinstance(item, str):
            _invalid(name, "entries must be strings")
        if allowed is not None and item not in allowed:
            _invalid(name, f"entries must be drawn from {allowed}")
    return list(value)


def opt_str_list(body, name, allowed=None, default=None):
    if name not in body or body[name] is None:
        return [] if default is None else default
    return as_str_list(body[name], name, allowed)


def req_date_ymd(body, name):
    value = req_str(body, name)
    if not valid_date_ymd(value):
        _invalid(name, "must be a YYYY-MM-DD date")
    return value


# ---------------------------------------------------------------------------
# Resource resolution — pipeline stage 3 (path ids, resource-specific 404)
# and stage 5 (body foreign keys, generic ERR_NOT_FOUND).
# ---------------------------------------------------------------------------

def _lookup(table, entity_id, error_id, label):
    entity = table.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise ApiError(error_id, 404, f"{label} not found: {entity_id}")
    return entity


def patient_by_path(entity_id):
    return _lookup(store.DB.patients, entity_id, E.ERR_PATIENT_NOT_FOUND, "Patient")


def supplier_by_path(entity_id):
    return _lookup(store.DB.suppliers, entity_id, E.ERR_SUPPLIER_NOT_FOUND, "Supplier")


def supplier_order_by_path(entity_id):
    return _lookup(store.DB.supplier_orders, entity_id, E.ERR_SUPPLIER_ORDER_NOT_FOUND, "Supplier order")


def unit_by_path(entity_id):
    return _lookup(store.DB.units, entity_id, E.ERR_UNIT_NOT_FOUND, "Blood unit")


def ts_by_path(entity_id):
    return _lookup(store.DB.type_and_screens, entity_id, E.ERR_TS_NOT_FOUND, "TypeAndScreen")


def order_by_path(entity_id):
    return _lookup(store.DB.orders, entity_id, E.ERR_ORDER_NOT_FOUND, "TransfusionOrder")


def xm_by_path(entity_id):
    return _lookup(store.DB.crossmatches, entity_id, E.ERR_CROSSMATCH_NOT_FOUND, "Crossmatch")


def issue_by_path(entity_id):
    return _lookup(store.DB.issues, entity_id, E.ERR_ISSUE_NOT_FOUND, "IssueRecord")


def reaction_by_path(entity_id):
    return _lookup(store.DB.reactions, entity_id, E.ERR_REACTION_NOT_FOUND, "TransfusionReaction")


def recall_by_path(entity_id):
    return _lookup(store.DB.recalls, entity_id, E.ERR_RECALL_NOT_FOUND, "RecallCase")


def wastage_by_path(entity_id):
    return _lookup(store.DB.wastage, entity_id, E.ERR_WASTAGE_RECORD_NOT_FOUND, "WastageRecord")


def policy_by_path(entity_id):
    return _lookup(store.DB.policies, entity_id, E.ERR_POLICY_NOT_FOUND, "ParLevelPolicy")


def cooler_by_path(entity_id):
    return _lookup(store.DB.coolers, entity_id, E.ERR_COOLER_NOT_FOUND, "TransportCooler")


def checkout_by_path(entity_id):
    return _lookup(store.DB.checkouts, entity_id, E.ERR_CHECKOUT_NOT_FOUND, "CoolerCheckout")


def mtp_by_path(entity_id):
    return _lookup(store.DB.mtps, entity_id, E.ERR_MTP_NOT_FOUND, "MTPActivation")


def fk_exists(table, entity_id, label):
    """Body foreign-key resolution — generic ERR_NOT_FOUND per PRD 2.9 stage 5."""
    if not isinstance(entity_id, str) or entity_id not in table:
        raise ApiError(E.ERR_NOT_FOUND, 404, f"Referenced {label} does not exist: {entity_id}")
    return table[entity_id]
