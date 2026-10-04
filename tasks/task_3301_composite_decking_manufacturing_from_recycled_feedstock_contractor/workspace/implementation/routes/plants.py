"""Clock and plant routes."""
from flask import Blueprint

import db as dbmod
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from services import calcs
from services.lookup import get_path
from services.review import run_capacity_review
from util import body, ok_object, parse_date, req_int, req_str, new_resource, touch

bp = Blueprint("clock_plants", __name__)

ALL_READ_ROLES = ("OpsManager", "QualityEngineer", "ProcessEngineer", "ProductManager",
                  "DealerSalesRep", "ChannelManager", "ClaimsAdjuster", "ProgramAdmin")


@bp.post("/decking/_clock/set_current_utc")
@require_roles("OpsManager")
def set_clock():
    data = body()
    to = data.get("to_iso8601")
    if not isinstance(to, str) or not to:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dbmod.set_clock(to)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO8601 datetime")
    dt = dbmod.clock_now()
    cur = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return ok_object({"current_utc": cur})


def plant_view(p):
    return dict(p)


@bp.post("/decking/plants")
@require_roles("OpsManager")
def create_plant():
    data = body()
    for f in ("name", "daily_capacity_lf", "lines", "pre_season_window_start", "pre_season_window_end"):
        if f not in data or data[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"missing required field: {f}")
    name = req_str(data, "name")
    cap = req_int(data, "daily_capacity_lf", minimum=1)
    lines = req_int(data, "lines", minimum=1)
    ws = req_str(data, "pre_season_window_start")
    we = req_str(data, "pre_season_window_end")
    import re
    if not re.fullmatch(r"\d{2}-\d{2}", ws) or not re.fullmatch(r"\d{2}-\d{2}", we):
        raise_err(ERR_INVALID_REQUEST, "pre-season window bounds must be MM-DD")
    if not ws < we:
        raise_err(ERR_INVALID_REQUEST, "pre_season_window_start must precede pre_season_window_end")
    p = new_resource({
        "name": name,
        "daily_capacity_lf": cap,
        "lines": lines,
        "resin_store": {"VIRGIN_PE": 0, "REPRO_PE": 0, "PCR_FILM": 0, "WOOD_FLOUR": 0},
        "fg_store": {},
        "reserved_fg_store": {},
        "pre_season_window_start": ws,
        "pre_season_window_end": we,
        "created_logical_date": dbmod.clock_date().isoformat(),
        "season_posture": calcs.compute_posture(
            {"pre_season_window_start": ws, "pre_season_window_end": we},
            dbmod.clock_date()),
    })
    dbmod.db.plants[p["id"]] = p
    dbmod.db.pcr_origin[p["id"]] = {"production_lbs": 0, "support_lbs": 0}
    return ok_object(plant_view(p), status=201)


@bp.get("/decking/plants/<pid>")
@require_roles(*ALL_READ_ROLES)
def get_plant(pid):
    return ok_object(plant_view(get_path("plants", pid)))


@bp.post("/decking/plants/<pid>/run-capacity-review")
@require_roles("OpsManager")
def capacity_review(pid):
    plant = get_path("plants", pid)
    run_capacity_review(plant)
    return ok_object(plant_view(plant))
