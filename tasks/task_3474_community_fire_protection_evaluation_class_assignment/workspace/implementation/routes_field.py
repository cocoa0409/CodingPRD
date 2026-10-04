"""Fire departments and the apparatus fleet (FireChief-owned)."""
from flask import Blueprint, request

import db
from cascade import DATA_WINDOW_STATES, window_or_fail, recompute_draft_if_scoring
from errors import fail
from middleware import auth, require_role, require_owner
from response import ok, ok_list
from util import (body, need, v_int, v_num, v_bool, v_str, v_enum, v_range,
                  pagination_params, page_of)

bp = Blueprint("field", __name__)

APPARATUS_KINDS = ("ENGINE", "LADDER", "QUINT", "TANKER", "RESCUE")
APPARATUS_STATUSES = ("FRONTLINE", "RESERVE", "OUT_OF_SERVICE")
APPARATUS_EDGES = {
    ("FRONTLINE", "RESERVE"),
    ("FRONTLINE", "OUT_OF_SERVICE"),
    ("RESERVE", "FRONTLINE"),
    ("RESERVE", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "RESERVE"),
    # OUT_OF_SERVICE -> FRONTLINE deliberately forbidden (PRD §3.3)
}
FACILITY_LEVELS = ("A", "B", "C")


@bp.route("/ppc/fire-departments", methods=["GET"])
def list_departments():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("departments")
    v = request.args.get("community_id")
    if v is not None:
        items = [d for d in items if d["community_id"] == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(d) for d in page], total, limit, offset)


@bp.route("/ppc/fire-departments/<departmentId>", methods=["GET"])
def get_department(departmentId):
    auth()
    dept = db.find("departments", departmentId)
    if dept is None:
        fail("ERR_DEPARTMENT_NOT_FOUND", "fire department does not exist")
    return ok(db.pub(dept))


@bp.route("/ppc/fire-departments/<departmentId>", methods=["PATCH"])
def patch_department(departmentId):
    uid, role = auth()
    require_role(role, "FireChief")
    require_owner(departmentId == uid)
    dept = db.find("departments", departmentId)
    if dept is None:
        fail("ERR_DEPARTMENT_NOT_FOUND", "fire department does not exist")
    window_or_fail(dept["community_id"], DATA_WINDOW_STATES)
    b = body()
    if "stations_active_count" in b:
        dept["stations_active_count"] = v_range(v_int(b["stations_active_count"], "stations_active_count"),
                                                "stations_active_count", lo=0)
    if "career_on_duty_per_shift" in b:
        dept["career_on_duty_per_shift"] = v_range(v_int(b["career_on_duty_per_shift"], "career_on_duty_per_shift"),
                                                   "career_on_duty_per_shift", lo=0)
    if "volunteers_on_duty_avg" in b:
        dept["volunteers_on_duty_avg"] = v_range(v_num(b["volunteers_on_duty_avg"], "volunteers_on_duty_avg"),
                                                 "volunteers_on_duty_avg", lo=0)
    if "training_hours_per_firefighter_annual" in b:
        dept["training_hours_per_firefighter_annual"] = v_range(
            v_num(b["training_hours_per_firefighter_annual"], "training_hours_per_firefighter_annual"),
            "training_hours_per_firefighter_annual", lo=0)
    if "training_facility_level" in b:
        dept["training_facility_level"] = v_enum(b["training_facility_level"],
                                                 "training_facility_level", FACILITY_LEVELS)
    if "live_fire_training" in b:
        dept["live_fire_training"] = v_bool(b["live_fire_training"], "live_fire_training")
    if "coverage_pct_within_5mi" in b:
        dept["coverage_pct_within_5mi"] = v_range(v_num(b["coverage_pct_within_5mi"], "coverage_pct_within_5mi"),
                                                  "coverage_pct_within_5mi", lo=0, hi=100)
    dept["data_submitted"] = True
    db.touch(dept)
    recompute_draft_if_scoring(dept["community_id"])
    return ok(db.pub(dept))


@bp.route("/ppc/apparatus", methods=["POST"])
def create_apparatus():
    uid, role = auth()
    require_role(role, "FireChief")
    b = body()
    department_id = v_str(need(b, "department_id"), "department_id")
    require_owner(department_id == uid)
    dept = db.find("departments", department_id)
    if dept is None:
        fail("ERR_DEPARTMENT_NOT_FOUND", "fire department does not exist")
    window_or_fail(dept["community_id"], DATA_WINDOW_STATES)
    kind = v_enum(need(b, "kind"), "kind", APPARATUS_KINDS)

    pump = b.get("pump_capacity_gpm")
    tank = b.get("tank_capacity_gal")
    ladder = b.get("ladder_height_ft")
    if pump is not None:
        pump = v_range(v_int(pump, "pump_capacity_gpm"), "pump_capacity_gpm", lo=0)
    if tank is not None:
        tank = v_range(v_int(tank, "tank_capacity_gal"), "tank_capacity_gal", lo=0)
    if ladder is not None:
        ladder = v_range(v_int(ladder, "ladder_height_ft"), "ladder_height_ft", lo=0)
    if kind in ("ENGINE", "QUINT") and pump is None:
        fail("ERR_INVALID_REQUEST", "pump_capacity_gpm is required for kind %s" % kind)
    if kind == "TANKER" and tank is None:
        fail("ERR_INVALID_REQUEST", "tank_capacity_gal is required for kind TANKER")
    if kind in ("LADDER", "QUINT") and ladder is None:
        fail("ERR_INVALID_REQUEST", "ladder_height_ft is required for kind %s" % kind)

    apparatus = db.new_entity("apparatus", {
        "department_id": department_id,
        "kind": kind,
        "pump_capacity_gpm": pump,
        "tank_capacity_gal": tank,
        "ladder_height_ft": ladder,
        "status": "FRONTLINE",
    })
    recompute_draft_if_scoring(dept["community_id"])
    return ok(db.pub(apparatus), 201)


@bp.route("/ppc/apparatus", methods=["GET"])
def list_apparatus():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("apparatus")
    for f in ("department_id", "status", "kind"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(a) for a in page], total, limit, offset)


@bp.route("/ppc/apparatus/<apparatusId>", methods=["GET"])
def get_apparatus(apparatusId):
    auth()
    apparatus = db.find("apparatus", apparatusId)
    if apparatus is None:
        fail("ERR_APPARATUS_NOT_FOUND", "apparatus does not exist")
    return ok(db.pub(apparatus))


@bp.route("/ppc/apparatus/<apparatusId>", methods=["PATCH"])
def patch_apparatus(apparatusId):
    uid, role = auth()
    require_role(role, "FireChief")
    apparatus = db.find("apparatus", apparatusId)
    if apparatus is None:
        fail("ERR_APPARATUS_NOT_FOUND", "apparatus does not exist")
    require_owner(apparatus["department_id"] == uid)
    b = body()
    target = v_enum(need(b, "status"), "status", APPARATUS_STATUSES)
    if (apparatus["status"], target) not in APPARATUS_EDGES:
        fail("ERR_APPARATUS_INVALID_STATE",
             "apparatus cannot move from %s to %s" % (apparatus["status"], target))
    dept = db.find("departments", apparatus["department_id"])
    window_or_fail(dept["community_id"], DATA_WINDOW_STATES)
    apparatus["status"] = target
    db.touch(apparatus)
    recompute_draft_if_scoring(dept["community_id"])
    return ok(db.pub(apparatus))
