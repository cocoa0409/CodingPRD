"""Lookup helpers, serialization, shared validation utilities."""
from db import DB, parse_iso
from errors import err_not_found, err_invalid_request, err_validation
from errors import ApiError as _AE


def err_bad_reference(msg="Referenced entity missing, in wrong state, or outside the program"):
    return _AE("ERR_BAD_REFERENCE", msg)


def err_program_not_active(msg="Rollout is not ACTIVE"):
    return _AE("ERR_PROGRAM_NOT_ACTIVE", msg)


def err_invalid_state(msg="Target resource not in a valid state for this transition"):
    return _AE("ERR_INVALID_STATE", msg)


def pub(entity):
    """Strip internal bookkeeping keys for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def pub_list(entities):
    return [pub(e) for e in entities]


def sorted_by_creation(entities):
    return sorted(entities, key=lambda e: e.get("_order", 0))


def get_rollout(pid):
    r = DB.rollouts.get(pid)
    if r is None:
        raise err_not_found("rollout program not found")
    return r


def get_trade_area(taid):
    t = DB.trade_areas.get(taid)
    if t is None:
        raise err_not_found("trade area not found")
    return t


def get_store(sid):
    s = DB.stores.get(sid)
    if s is None:
        raise err_not_found("store not found")
    return s


def get_developer(did):
    d = DB.developers.get(did)
    if d is None:
        raise err_not_found("developer not found")
    return d


def get_agreement(aid):
    a = DB.agreements.get(aid)
    if a is None:
        raise err_not_found("site control agreement not found")
    return a


def get_dc(dcid):
    d = DB.dcs.get(dcid)
    if d is None:
        raise err_not_found("distribution center not found")
    return d


def get_assignment(aid):
    a = DB.dc_assignments.get(aid)
    if a is None:
        raise err_not_found("dc assignment not found")
    return a


def get_route_plan(rid):
    r = DB.route_plans.get(rid)
    if r is None:
        raise err_not_found("route plan not found")
    return r


def get_opening_plan(oid):
    o = DB.opening_plans.get(oid)
    if o is None:
        raise err_not_found("opening plan not found")
    return o


def get_study(cid):
    c = DB.studies.get(cid)
    if c is None:
        raise err_not_found("cannibalization study not found")
    return c


def get_capital_project(cid):
    c = DB.capital_projects.get(cid)
    if c is None:
        raise err_not_found("capital project not found")
    return c


def get_event(eid):
    e = DB.events.get(eid)
    if e is None:
        raise err_not_found("program event not found")
    return e


def body_rollout(body, expected_pid=None):
    """Extract and validate the rollout_program_id body reference."""
    pid = body.get("rollout_program_id")
    if pid is None or not isinstance(pid, str):
        raise err_invalid_request("rollout_program_id is required")
    r = DB.rollouts.get(pid)
    if r is None:
        raise err_bad_reference("rollout_program_id does not resolve")
    if expected_pid is not None and pid != expected_pid:
        raise err_bad_reference("rollout_program_id does not match the resource's program")
    return r


def require_active(program):
    if program["status"] != "ACTIVE":
        raise err_program_not_active()


def parse_dt_field(value, field):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be a valid ISO 8601 datetime")


def check_name_unique(collection, program_id, name, what):
    for e in collection.values():
        if e.get("rollout_program_id") == program_id and e.get("name") == name:
            raise err_validation(f"{what} name must be unique within the program")
