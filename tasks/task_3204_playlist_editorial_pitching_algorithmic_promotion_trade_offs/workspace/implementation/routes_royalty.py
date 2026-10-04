"""Routes: royalty periods and statements."""
from flask import Blueprint

from store import store
from util import (auth, require_role, body_json, need, as_int, as_enum, as_dt,
                  ok_object, list_response, pub, opt_enum_filter, opt_str_filter, err)
import services as S

bp = Blueprint("royalty", __name__)

STATEMENT_READERS = ["PlatformAdmin", "RightsHolder", "FraudAnalyst"]


def get_period(pid):
    p = store.periods.get(pid)
    if p is None:
        err("ERR_NOT_FOUND", 404, "Royalty period not found")
    return p


def get_statement(sid):
    s = store.statements.get(sid)
    if s is None:
        err("ERR_NOT_FOUND", 404, "Royalty statement not found")
    return s


@bp.post("/catalog/royalty-periods")
def create_period():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = body_json()
    ps_raw, ps_dt = as_dt(need(b, "period_start"), "period_start")
    pe_raw, pe_dt = as_dt(need(b, "period_end"), "period_end")
    if ps_dt >= pe_dt:
        err("ERR_INVALID_REQUEST", 400, "period_start must be strictly before period_end")
    pool = as_int(need(b, "pool_cents"), "pool_cents")
    if pool < 0:
        err("ERR_INVALID_REQUEST", 400, "pool_cents must be >= 0")
    p = S.base_entity()
    p.update({
        "period_start": ps_raw,
        "period_end": pe_raw,
        "_ps_dt": ps_dt,
        "_pe_dt": pe_dt,
        "pool_cents": pool,
        "status": "OPEN",
        "closed_variant": None,
    })
    store.periods[p["id"]] = p
    return ok_object(pub(p), 201)


@bp.get("/catalog/royalty-periods/<pid>")
def fetch_period(pid):
    uid, role = auth()
    require_role(role, STATEMENT_READERS)
    p = get_period(pid)
    return ok_object(pub(p))


@bp.get("/catalog/royalty-periods")
def list_periods():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "FraudAnalyst"])
    f_status = opt_enum_filter("status", S.PERIOD_STATUSES)
    items = list(store.periods.values())
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/royalty-periods/<pid>/close")
def close_period(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    p = get_period(pid)
    b = body_json()
    variant = as_enum(need(b, "variant"), "variant", ["GROSS", "EFFECTIVE"])
    expected = as_int(need(b, "expected_period_version"), "expected_period_version")
    if p["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN period can be closed")
    if store.clock < p["_pe_dt"]:
        err("ERR_PERIOD_NOT_CLOSABLE", 409, "Logical clock has not reached period_end")
    for o in store.periods.values():
        if (o["id"] != p["id"] and o["status"] == "OPEN"
                and p["_ps_dt"] < o["_pe_dt"] and o["_ps_dt"] < p["_pe_dt"]):
            err("ERR_PERIOD_NOT_CLOSABLE", 409, "Another OPEN period overlaps this window")
    if expected != p["version"]:
        err("ERR_STALE_VERSION", 412, "expected_period_version does not match the period version")
    p["closed_variant"] = variant
    p["status"] = "CLOSED"
    S.touch(p)
    S.generate_statements(p)
    return ok_object(pub(p))


@bp.post("/catalog/royalty-periods/<pid>/settle")
def settle_period(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    p = get_period(pid)
    if p["status"] != "CLOSED":
        err("ERR_INVALID_STATE", 409, "Only a CLOSED period can be settled")
    p["status"] = "SETTLED"
    S.touch(p)
    return ok_object(pub(p))


@bp.get("/catalog/royalty-statements/<sid>")
def fetch_statement(sid):
    uid, role = auth()
    require_role(role, STATEMENT_READERS)
    s = get_statement(sid)
    if role == "RightsHolder" and s["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own statements")
    return ok_object(pub(s))


@bp.get("/catalog/royalty-statements")
def list_statements():
    uid, role = auth()
    require_role(role, STATEMENT_READERS)
    f_period = opt_str_filter("period_id")
    f_artist = opt_str_filter("artist_id")
    items = list(store.statements.values())
    if role == "RightsHolder":
        items = [s for s in items if s["artist_id"] == uid]
    if f_period is not None:
        items = [s for s in items if s["period_id"] == f_period]
    if f_artist is not None:
        items = [s for s in items if s["artist_id"] == f_artist]
    return list_response(items)
