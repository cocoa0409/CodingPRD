"""Production runs: scheduling (slot assignment, changeover, capacity, OCC),
start (recipe draw), complete (BoardLot creation, fg_store), cancel."""
from flask import Blueprint

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_CAPACITY_EXCEEDED, ERR_LINE_OCCUPIED,
                    ERR_RESIN_SHORTFALL, ERR_RUN_NOT_TODAY, ERR_OVERAGE_LIMIT,
                    ERR_SUPPORT_STOCK_BARRED, ERR_LINE_SUPPORT_ONLY, ERR_LINE_SUNSET,
                    ERR_NOT_FOUND)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import (body, ok_object, ok_list, req_int, parse_date, opt_enum, opt_str,
                  new_resource, touch, logical_now_iso)

bp = Blueprint("production", __name__)

RUN_KINDS = ("SELLABLE", "SUPPORT_STOCK", "NULL_SLOT")


def run_view(r):
    return dict(r)


def _check_line_sellable(line, run_kind):
    if run_kind == "NULL_SLOT":
        if line["status"] == "SUNSET":
            raise_err(ERR_LINE_SUNSET, "SUNSET forbids all runs")
        return
    if line["status"] == "SUNSET":
        raise_err(ERR_LINE_SUNSET, "SUNSET forbids all runs")
    if run_kind == "SELLABLE":
        if line["status"] != "ACTIVE":
            raise_err(ERR_LINE_SUPPORT_ONLY, "SELLABLE runs require line status ACTIVE")
    elif run_kind == "SUPPORT_STOCK":
        if not line["repair_support_only"]:
            raise_err(ERR_LINE_SUPPORT_ONLY,
                      "SUPPORT_STOCK runs require repair_support_only == true")


def _used_slots(plant_id, production_date):
    used = set()
    for r in dbmod.db.production_runs.values():
        if r["plant_id"] == plant_id and r["production_date"] == production_date \
                and r["status"] in ("PLANNED", "RUNNING", "COMPLETED") \
                and r.get("line_slot") is not None:
            used.add(r["line_slot"])
    return used


def _assign_slot(plant, production_date, run_kind):
    if run_kind == "NULL_SLOT":
        return None
    used = _used_slots(plant["id"], production_date)
    for slot in range(1, plant["lines"] + 1):
        if slot not in used:
            return slot
    # no free slot — capacity exceeded
    raise_err(ERR_CAPACITY_EXCEEDED, "no free line slot for this production_date")


@bp.post("/decking/plants/<pid>/production-runs")
@require_roles("OpsManager")
def create_run(pid):
    plant = get_path("plants", pid)
    data = body()
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    reservation = None
    if data.get("reservation_id") is not None:
        reservation = get_body_ref("allocation_commitments", data["reservation_id"], "reservation_id")
    planned_lf = req_int(data, "planned_lf", minimum=1)
    pdate = data.get("production_date")
    parse_date(pdate, "production_date")
    run_kind = opt_enum(data, "run_kind", RUN_KINDS, default="SELLABLE")
    if "expected_plant_version" not in data or data["expected_plant_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "expected_plant_version is required")
    epv = data["expected_plant_version"]
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise_err(ERR_INVALID_REQUEST, "expected_plant_version must be an integer")
    # OCC check
    if epv != plant["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plant_version does not match current plant version")
    # line sellability
    _check_line_sellable(line, run_kind)
    # reservation rule: when reservations exist for the line, a SELLABLE run must carry one
    if run_kind == "SELLABLE" and reservation is None:
        for ac in dbmod.db.allocation_commitments.values():
            if ac["product_line_id"] == line["id"] and ac["status"] == "OPEN":
                raise_err(ERR_INVALID_REQUEST,
                          "reservation_id required: OPEN reservations exist for this product line")
    if reservation is not None and reservation["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "reservation is not OPEN")
    # formulation must exist; pin active revision
    frm = dbmod.db.formulations.get(line["formulation_id"])
    if frm is None:
        raise_err(ERR_INVALID_REQUEST, "product line references a missing formulation")
    # slot + changeover + capacity
    slot = _assign_slot(plant, pdate, run_kind)
    # The changeover compares against the previous run on the same line slot;
    # for NULL_SLOT runs (no slot) the natural reading of that sentence is
    # chronological: the previous run for the plant, whichever slot it held.
    prev = calcs.prev_run_on_slot(plant["id"], slot, pdate)
    changeover = calcs.changeover_minutes_for(prev, line)
    rmin = calcs.run_minutes(plant, planned_lf)
    total = rmin + changeover
    day_total = total
    for r in dbmod.db.production_runs.values():
        if r["plant_id"] == plant["id"] and r["production_date"] == pdate \
                and r["status"] in ("PLANNED", "RUNNING", "COMPLETED"):
            day_total += r["total_minutes"]
    if day_total > calcs.day_capacity_minutes(plant):
        raise_err(ERR_CAPACITY_EXCEEDED, "daily minute capacity exceeded")
    run = new_resource({
        "plant_id": plant["id"],
        "product_line_id": line["id"],
        "formulation_revision": frm["active_revision"],
        "planned_lf": planned_lf,
        "actual_lf": None,
        "production_date": pdate,
        "line_slot": slot,
        "changeover_minutes": changeover,
        "total_minutes": total,
        "run_kind": run_kind,
        "reservation_id": reservation["id"] if reservation else None,
        "board_lot_id": None,
        "status": "PLANNED",
    })
    dbmod.db.production_runs[run["id"]] = run
    touch(plant)
    return ok_object(run_view(run), status=201)


@bp.get("/decking/plants/<pid>/production-runs/<rid>")
@require_roles("OpsManager", "ProcessEngineer", "QualityEngineer")
def get_run_nested(pid, rid):
    get_path("plants", pid)
    run = get_path("production_runs", rid)
    if run["plant_id"] != pid:
        raise_err(ERR_NOT_FOUND, "run not under this plant")
    return ok_object(run_view(run))


@bp.get("/decking/plants/<pid>/production-runs")
@require_roles("OpsManager", "ProcessEngineer")
def list_runs_nested(pid):
    get_path("plants", pid)
    items = [r for r in dbmod.db.production_runs.values() if r["plant_id"] == pid]
    from flask import request
    pd_filter = request.args.get("production_date")
    st_filter = request.args.get("status")
    if pd_filter:
        items = [r for r in items if r["production_date"] == pd_filter]
    if st_filter:
        items = [r for r in items if r["status"] == st_filter]
    return ok_list([run_view(r) for r in items])


@bp.get("/decking/production-runs/<rid>")
@require_roles("OpsManager", "ProcessEngineer", "QualityEngineer")
def get_run(rid):
    return ok_object(run_view(get_path("production_runs", rid)))


@bp.get("/decking/production-runs")
@require_roles("OpsManager", "ProcessEngineer", "QualityEngineer")
def list_runs():
    from flask import request
    items = list(dbmod.db.production_runs.values())
    for f in ("product_line_id", "reservation_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if r.get(f) == v]
    return ok_list([run_view(r) for r in items])


def _get_run_checked(pid, rid):
    get_path("plants", pid)
    run = get_path("production_runs", rid)
    if run["plant_id"] != pid:
        raise_err(ERR_NOT_FOUND, "run not under this plant")
    return run


@bp.post("/decking/plants/<pid>/production-runs/<rid>/start")
@require_roles("OpsManager")
def start_run(pid, rid):
    run = _get_run_checked(pid, rid)
    plant = dbmod.db.plants[pid]
    if run["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, f"run is {run['status']}")
    if run["production_date"] != dbmod.clock_date().isoformat():
        raise_err(ERR_RUN_NOT_TODAY, "run start on a date other than production_date")
    if run.get("line_slot") is not None:
        for other in dbmod.db.production_runs.values():
            if other["id"] != run["id"] and other["plant_id"] == pid \
                    and other["status"] == "RUNNING" \
                    and other["production_date"] == run["production_date"] \
                    and other.get("line_slot") == run["line_slot"]:
                raise_err(ERR_LINE_OCCUPIED, "another run RUNNING on the same line slot")
    line = dbmod.db.product_lines[run["product_line_id"]]
    frm = dbmod.db.formulations[line["formulation_id"]]
    rev = dbmod.db.formulation_revisions[frm["id"]][run["formulation_revision"]]
    draw = calcs.recipe_draw(rev["lines"], run["planned_lf"])
    for m, need in draw.items():
        if plant["resin_store"][m] < need:
            raise_err(ERR_RESIN_SHORTFALL, f"resin_store below recipe draw for {m}")
    # support-stock bar: capped lines may not draw PCR exclusively from support lots
    if line["capped"] and draw.get("PCR_FILM", 0) > 0:
        origin = dbmod.db.pcr_origin[pid]
        if origin["production_lbs"] <= 0 and plant["resin_store"]["PCR_FILM"] > 0:
            raise_err(ERR_SUPPORT_STOCK_BARRED,
                      "capped line would draw support-stock PCR")
    for m, need in draw.items():
        plant["resin_store"][m] -= need
    # decrement PCR provenance (production stock consumed first)
    if draw.get("PCR_FILM", 0) > 0:
        origin = dbmod.db.pcr_origin[pid]
        from_prod = min(origin["production_lbs"], draw["PCR_FILM"])
        origin["production_lbs"] -= from_prod
        origin["support_lbs"] -= (draw["PCR_FILM"] - from_prod)
        if origin["support_lbs"] < 0:
            origin["support_lbs"] = 0
    run["status"] = "RUNNING"
    touch(run)
    touch(plant)
    return ok_object(run_view(run))


@bp.post("/decking/plants/<pid>/production-runs/<rid>/complete")
@require_roles("OpsManager")
def complete_run(pid, rid):
    run = _get_run_checked(pid, rid)
    plant = dbmod.db.plants[pid]
    if run["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, f"run is {run['status']}")
    data = body()
    actual = req_int(data, "actual_lf", minimum=1)
    import math as _math
    if actual > int(_math.floor(run["planned_lf"] * 1.10)):
        raise_err(ERR_OVERAGE_LIMIT, "actual_lf above 110% of planned_lf")
    run["actual_lf"] = actual
    run["status"] = "COMPLETED"
    line_id = run["product_line_id"]
    support = run["run_kind"] != "SELLABLE"
    lot = new_resource({
        "plant_id": pid,
        "production_run_id": run["id"],
        "product_line_id": line_id,
        "formulation_revision": run["formulation_revision"],
        "lf": actual,
        "produced_at": logical_now_iso(),
        "support_tagged": support,
        "disposition": "AVAILABLE",
    })
    dbmod.db.board_lots[lot["id"]] = lot
    run["board_lot_id"] = lot["id"]
    if not support:
        plant["fg_store"][line_id] = plant["fg_store"].get(line_id, 0) + actual
        if run.get("reservation_id"):
            ac = dbmod.db.allocation_commitments.get(run["reservation_id"])
            if ac is not None and ac["status"] == "OPEN":
                remaining = ac.get("remaining_lf", ac["reserved_lf"])
                consumed = min(actual, remaining)
                ac["remaining_lf"] = remaining - consumed
                plant["reserved_fg_store"][line_id] = max(
                    0, plant["reserved_fg_store"].get(line_id, 0) - consumed)
                if ac["remaining_lf"] <= 0:
                    ac["status"] = "CONSUMED"
                touch(ac)
    touch(run)
    touch(plant)
    return ok_object(run_view(run))


@bp.post("/decking/plants/<pid>/production-runs/<rid>/cancel")
@require_roles("OpsManager")
def cancel_run(pid, rid):
    run = _get_run_checked(pid, rid)
    if run["status"] not in ("PLANNED", "RUNNING"):
        raise_err(ERR_INVALID_STATE, f"run is {run['status']}")
    run["status"] = "CANCELLED"
    touch(run)
    return ok_object(run_view(run))


@bp.get("/decking/production-runs/<rid>/board-lots")
@require_roles("OpsManager", "QualityEngineer", "ClaimsAdjuster")
def run_board_lots(rid):
    get_path("production_runs", rid)
    items = [dict(l) for l in dbmod.db.board_lots.values() if l["production_run_id"] == rid]
    return ok_list(items)
