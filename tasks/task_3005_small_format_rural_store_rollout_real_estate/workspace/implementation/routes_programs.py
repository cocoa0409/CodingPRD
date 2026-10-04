"""Programs, clock, events, settings, trade areas, screening."""
from flask import Blueprint, request
from decimal import Decimal

from db import DB
from errors import ApiError, err_invalid_request, err_validation
from middleware import require_roles, get_body, req_str, req_int, req_number, opt_int, opt_number
from response import success, parse_pagination, paginate
from services import (base_entity, touch, append_event, compute_trade_area_score,
                      recompute_capital, fmt_dt)
from helpers import (pub, pub_list, sorted_by_creation, get_rollout, get_trade_area,
                     body_rollout, require_active, check_name_unique)

bp = Blueprint("programs", __name__)

ALL = ("PROGRAM_ADMIN", "REAL_ESTATE_MANAGER", "NETWORK_PLANNER",
       "OPERATIONS_LEAD", "FINANCE_ANALYST")
ADMIN = ("PROGRAM_ADMIN",)


def _err_stale():
    return ApiError("ERR_STALE_VERSION", "expected version does not match current version")


@bp.post("/rollouts")
def create_rollout():
    require_roles(*ADMIN)
    body = get_body()
    name = req_str(body, "name")
    fiscal_year = req_int(body, "fiscal_year")
    budget = req_int(body, "new_build_capital_budget_cents")
    if budget < 0:
        raise err_validation("new_build_capital_budget_cents must be >= 0")
    coef = body.get("cannibalization_coefficient", 0.40)
    if isinstance(coef, bool) or not isinstance(coef, (int, float)):
        raise err_invalid_request("cannibalization_coefficient must be a number")
    for r in DB.rollouts.values():
        if r["name"] == name:
            raise err_validation("rollout program name must be unique")
    r = base_entity()
    r.update({
        "name": name,
        "fiscal_year": fiscal_year,
        "new_build_capital_budget_cents": budget,
        "cannibalization_coefficient": coef,
        "status": "DRAFT",
        "committed_capital_cents": 0,
        "available_capital_cents": budget,
        "event_log_cursor": 0,
    })
    DB.rollouts[r["id"]] = r
    return success(pub(r), 201)


@bp.get("/rollouts")
def list_rollouts():
    require_roles(*ALL)
    items = sorted_by_creation(DB.rollouts.values())
    limit, offset = parse_pagination(request.args)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.post("/rollouts/_clock-set")
def clock_set():
    require_roles(*ADMIN)
    body = get_body()
    pid = body.get("rollout_program_id")
    if not isinstance(pid, str):
        raise err_invalid_request("rollout_program_id is required")
    program = DB.rollouts.get(pid)
    if program is None:
        raise ApiError("ERR_NOT_FOUND", "rollout program not found")
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err_invalid_request("to_iso8601 is required")
    from db import parse_iso
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 datetime")
    DB.set_clock(pid, to_iso)
    return success({"current_utc": fmt_dt(dt)}, 200)


@bp.get("/rollouts/program-events")
def list_events():
    require_roles(*ALL)
    items = list(DB.events.values())
    pid = request.args.get("rollout_program_id")
    if pid is not None:
        items = [e for e in items if e["rollout_program_id"] == pid]
    items.sort(key=lambda e: (e["rollout_program_id"], e["sequence_number"]))
    limit, offset = parse_pagination(request.args)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/program-events/<evid>")
def get_event_by_id(evid):
    require_roles(*ALL)
    from helpers import get_event
    return success(pub(get_event(evid)), 200)


@bp.get("/rollouts/<pid>")
def get_rollout_by_id(pid):
    require_roles(*ALL)
    return success(pub(get_rollout(pid)), 200)


@bp.post("/rollouts/<pid>/activate")
def activate(pid):
    require_roles(*ADMIN)
    program = get_rollout(pid)
    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "program must be DRAFT to activate")
    program["status"] = "ACTIVE"
    append_event(program, "PROGRAM_ACTIVATED")
    touch(program)
    return success(pub(program), 200)


@bp.post("/rollouts/<pid>/deactivate")
def deactivate(pid):
    require_roles(*ADMIN)
    program = get_rollout(pid)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "program must be ACTIVE to deactivate")
    for s in DB.stores.values():
        if s["rollout_program_id"] == pid and s["status"] in (
                "SITE_CONTROL", "UNDER_CONSTRUCTION", "DELIVERED"):
            raise ApiError("ERR_PROGRAM_HAS_ACTIVE_STORES",
                           "a store has advanced past PROPOSED and is not KILLED")
    program["status"] = "DRAFT"
    append_event(program, "PROGRAM_DEACTIVATED")
    touch(program)
    return success(pub(program), 200)


@bp.post("/rollouts/<pid>/close")
def close(pid):
    require_roles(*ADMIN)
    program = get_rollout(pid)
    if program["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "program already closed")
    if program["status"] == "ACTIVE":
        for s in DB.stores.values():
            if s["rollout_program_id"] == pid and s["status"] not in (
                    "KILLED", "OPEN", "EXISTING"):
                raise ApiError("ERR_PROGRAM_CLOSE_BLOCKED",
                               "a store is mid-pipeline")
    for p in DB.capital_projects.values():
        if p["rollout_program_id"] == pid and p["status"] not in (
                "APPROVED", "REJECTED", "CANCELLED"):
            raise ApiError("ERR_PROGRAM_CLOSE_BLOCKED",
                           "a capital project is undecided")
    program["status"] = "CLOSED"
    append_event(program, "PROGRAM_CLOSED")
    touch(program)
    return success(pub(program), 200)


@bp.patch("/rollouts/<pid>/settings")
def update_settings(pid):
    require_roles(*ADMIN)
    program = get_rollout(pid)
    body = get_body()
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE",
                       "settings may be updated only while ACTIVE")
    if "new_build_capital_budget_cents" in body and body["new_build_capital_budget_cents"] is not None:
        v = body["new_build_capital_budget_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_invalid_request("new_build_capital_budget_cents must be an integer")
        if v < 0:
            raise err_validation("new_build_capital_budget_cents must be >= 0")
        program["new_build_capital_budget_cents"] = v
    if "cannibalization_coefficient" in body and body["cannibalization_coefficient"] is not None:
        v = body["cannibalization_coefficient"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err_invalid_request("cannibalization_coefficient must be a number")
        program["cannibalization_coefficient"] = v
    recompute_capital(program)
    touch(program)
    return success(pub(program), 200)


# ---- trade areas -------------------------------------------------------------

TA_FIELDS = ("drive_time_minutes", "household_count",
             "median_household_income_cents", "grocery_gap_pct")


def _validate_ta_value(field, value):
    if field == "grocery_gap_pct":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise err_invalid_request("grocery_gap_pct must be a number")
        if Decimal(str(value)) < 0 or Decimal(str(value)) > 100:
            raise err_validation("grocery_gap_pct must be within 0..100")
    else:
        if isinstance(value, bool) or not isinstance(value, int):
            raise err_invalid_request(f"{field} must be an integer")
        if field == "drive_time_minutes" and (value < 0 or value > 45):
            raise err_validation("drive_time_minutes must be within 0..45")
        if field == "household_count" and value <= 0:
            raise err_validation("household_count must be > 0")


@bp.post("/rollouts/trade-areas")
def create_trade_area():
    require_roles(*ADMIN)
    body = get_body()
    program = body_rollout(body)
    name = req_str(body, "name")
    drive = req_int(body, "drive_time_minutes")
    hh = req_int(body, "household_count")
    income = req_int(body, "median_household_income_cents")
    gap = req_number(body, "grocery_gap_pct")
    _validate_ta_value("drive_time_minutes", drive)
    _validate_ta_value("household_count", hh)
    _validate_ta_value("grocery_gap_pct", gap)
    check_name_unique(DB.trade_areas, program["id"], name, "trade area")
    t = base_entity()
    t.update({
        "rollout_program_id": program["id"],
        "name": name,
        "drive_time_minutes": drive,
        "household_count": hh,
        "median_household_income_cents": income,
        "grocery_gap_pct": gap,
        "status": "SCREENING",
        "trade_area_score": None,
        "projected_revenue_cents": 0,
        "screening_count": 0,
    })
    DB.trade_areas[t["id"]] = t
    return success(pub(t), 201)


@bp.get("/rollouts/trade-areas")
def list_trade_areas():
    require_roles(*ALL)
    items = list(DB.trade_areas.values())
    pid = request.args.get("rollout_program_id")
    if pid is not None:
        items = [t for t in items if t["rollout_program_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(request.args)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/trade-areas/<taid>")
def get_trade_area_by_id(taid):
    require_roles(*ALL)
    return success(pub(get_trade_area(taid)), 200)


@bp.patch("/rollouts/trade-area-updates")
def update_trade_area():
    require_roles(*ADMIN)
    body = get_body()
    program = body_rollout(body)
    taid = body.get("trade_area_id")
    if not isinstance(taid, str):
        raise err_invalid_request("trade_area_id is required")
    ta = DB.trade_areas.get(taid)
    if ta is None or ta["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "trade area not found in program")
    if ta["status"] not in ("SCREENING", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "market data refresh allowed only while SCREENING or REJECTED")
    changed = False
    for f in TA_FIELDS:
        if f in body and body[f] is not None:
            v = body[f]
            _validate_ta_value(f, v)
            ta[f] = v
            changed = True
    touch(ta)
    return success(pub(ta), 200)


@bp.post("/rollouts/trade-areas/<taid>/screen")
def screen_trade_area(taid):
    require_roles(*ADMIN)
    ta = get_trade_area(taid)
    body = get_body()
    program = body_rollout(body, expected_pid=ta["rollout_program_id"])
    if "expected_trade_area_version" not in body or body["expected_trade_area_version"] is None:
        raise err_invalid_request("expected_trade_area_version is required")
    expected = body["expected_trade_area_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_trade_area_version must be an integer")
    require_active(program)

    score, qualifies = compute_trade_area_score(ta, program)

    if ta["status"] == "QUALIFIED" and not qualifies:
        for s in DB.stores.values():
            if s["trade_area_id"] == ta["id"] and s["status"] != "KILLED":
                raise ApiError("ERR_INVALID_STATE",
                               "a live store exists for this trade area")

    if expected != ta["version"]:
        raise _err_stale()

    ta["trade_area_score"] = score
    ta["screening_count"] += 1
    if qualifies:
        ta["status"] = "QUALIFIED"
        append_event(program, "TRADE_AREA_QUALIFIED",
                     payload={"trade_area_score": score})
    else:
        ta["status"] = "REJECTED"
    touch(ta)
    return success(pub(ta), 200)
