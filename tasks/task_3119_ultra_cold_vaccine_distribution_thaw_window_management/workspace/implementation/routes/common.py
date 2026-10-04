"""Shared route helpers: body parsing, filtering, listing, lookups."""
from flask import request

from errors import ApiError
from helpers import h
from response import ok, paginate
from clockutil import parse_ts, fmt
from services import derive as D

PREFIX = "/vaccine-distribution"


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def has(data, name):
    return name in data and data[name] is not None


def required(data, name):
    if not has(data, name):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return data[name]


def q(name, default=None):
    v = request.args.get(name)
    return default if v is None else v


# --- typed field readers ---------------------------------------------------
def as_str(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def as_num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def as_enum(value, allowed, name):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def as_ts(value, name):
    try:
        dt = parse_ts(value)
    except ApiError:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return fmt(dt)


def as_array(value, name):
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    return value


def opt_str(data, name, default=None):
    if not has(data, name):
        return default
    return as_str(data[name], name)


def opt_int(data, name, default=None):
    if not has(data, name):
        return default
    return as_int(data[name], name)


def opt_num(data, name, default=None):
    if not has(data, name):
        return default
    return as_num(data[name], name)


def opt_bool(data, name, default=None):
    if not has(data, name):
        return default
    return as_bool(data[name], name)


def opt_ts(data, name, default=None):
    if not has(data, name):
        return default
    return as_ts(data[name], name)


def opt_enum(data, name, allowed, default=None):
    if not has(data, name):
        return default
    return as_enum(data[name], allowed, name)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def fetch(collection, key, label=None):
    rec = h.get(collection, key)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "%s was not found." % (label or collection))
    return rec


# ---------------------------------------------------------------------------
# terminal-state gate (validation priority 6)
# ---------------------------------------------------------------------------
TERMINAL_STATES = {
    "allocation_batches": ["DEPLETED", "RECALLED"],
    "allocation_windows": ["CLOSED"],
    "allocation_entitlements": ["FULFILLED", "LAPSED"],
    "site_orders": ["REJECTED", "FULFILLED"],
    "dispatch_orders": ["DELIVERED", "REJECTED_AT_DOCK"],
    "cold_chain_shippers": ["RELEASED"],
    "cartons": ["DESTROYED"],
    "site_transfers": ["RECEIVED", "REJECTED", "CANCELLED"],
    "wastage_reports": ["RECONCILED"],
    "reporting_periods": ["SUBMITTED"],
    "carton_storage_reservations": ["RELEASED", "LAPSED"],
    "excursion_adjudications": ["SUPERSEDED", "WITHDRAWN"],
    "temperature_excursions": [],
    "dose_ledger_entries": [],
    "doses_affected_slices": [],
    "adjudication_appeals": [],
}


def ensure_not_terminal(record, collection, field="status"):
    """Raise ERR_ALREADY_TERMINAL when the entity sits in a terminal state."""
    value = record.get(field)
    if value in TERMINAL_STATES.get(collection, []):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "The resource is already in the terminal state %s." % value)
    return record


def path_id(name="id"):
    return request.view_args.get(name)


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------
def list_response(items, filters=None, sort_key="created_at"):
    """Filter by the endpoint's declared query parameters, then paginate."""
    out = items
    if filters:
        for key, checker in filters.items():
            value = request.args.get(key)
            if value is None:
                continue
            out = [r for r in out if checker(r, value)]
    out = sorted(out, key=lambda r: (r.get(sort_key) or "", r.get("id", "")))
    window, meta = paginate(out, request.args)
    return ok(window, pagination=meta)


def eq(field):
    return lambda rec, value: str(rec.get(field)) == str(value)


def eq_num(field):
    return lambda rec, value: rec.get(field) == int(value)


def involves_site(field):
    return lambda rec, value: rec.get(field) == value


def either_site(a, b):
    return lambda rec, value: rec.get(a) == value or rec.get(b) == value


def single(record):
    return ok(record)


def created(record):
    return ok(record, status=201)


# ---------------------------------------------------------------------------
# common recompute fan-out
# ---------------------------------------------------------------------------
def recompute_all_sites():
    for site in h.all("storage_sites"):
        D.recompute_site(site)


def project(record, fields):
    return {k: record.get(k) for k in fields}


def recompute_program_and_sites(program):
    D.recompute_program(program)
    for site in h.all("storage_sites"):
        if site.get("jurisdiction_program_id") == program["id"]:
            D.recompute_site(site)