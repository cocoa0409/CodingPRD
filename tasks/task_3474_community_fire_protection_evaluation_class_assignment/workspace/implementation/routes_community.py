"""Communities, comms attestation, and the (unprefixed) logical clock."""
from flask import Blueprint

import db
from cascade import DATA_WINDOW_STATES, window_or_fail, recompute_draft_if_scoring
from middleware import auth, require_role
from response import ok, ok_list
from util import (body, need, v_int, v_num, v_bool, v_str, v_enum, v_range,
                  pagination_params, page_of, parse_iso_dt)
from errors import fail

bp = Blueprint("community", __name__)

DEPT_TYPES = ("CAREER", "VOLUNTEER", "COMBINATION")


@bp.route("/ppc/communities", methods=["POST"])
def create_community():
    uid, role = auth()
    require_role(role, "EvaluationCoordinator")
    b = body()
    name = v_str(need(b, "name"), "name")
    state_code = v_str(need(b, "state_code"), "state_code")
    population = v_range(v_int(need(b, "population"), "population"), "population", lo=0, lo_inclusive=False)
    area = v_range(v_num(need(b, "area_sq_miles"), "area_sq_miles"), "area_sq_miles", lo=0, lo_inclusive=False)
    rural = v_range(v_num(need(b, "rural_area_pct"), "rural_area_pct"), "rural_area_pct", lo=0, hi=100)
    dept_type = v_enum(need(b, "dept_type"), "dept_type", DEPT_TYPES)
    nff = v_range(v_int(need(b, "needed_fire_flow_gpm"), "needed_fire_flow_gpm"),
                  "needed_fire_flow_gpm", lo=500, hi=50000)
    storage = v_range(v_int(need(b, "storage_capacity_gal"), "storage_capacity_gal"),
                      "storage_capacity_gal", lo=0)
    supply = v_range(v_int(need(b, "supply_works_capacity_gpm"), "supply_works_capacity_gpm"),
                     "supply_works_capacity_gpm", lo=0, lo_inclusive=False)
    consumption = v_range(v_int(need(b, "daily_consumption_gpm"), "daily_consumption_gpm"),
                          "daily_consumption_gpm", lo=0)

    community = db.new_entity("communities", {
        "name": name,
        "state_code": state_code,
        "population": population,
        "area_sq_miles": area,
        "rural_area_pct": rural,
        "comms_operators_on_duty_min": 0,
        "comms_avg_alarm_to_dispatch_seconds": 999,
        "comms_redundant_circuits": False,
        "comms_backup_power": False,
        "comms_attested": False,
        "comms_attested_by": None,
        "comms_attested_at": None,
        "status": "REGISTERED",
        "current_class_number": None,
        "current_split_class": None,
        "current_premium_modifier": None,
        "bound_exposure_cents": 0,
        "next_evaluation_due_date": None,
    })
    db.new_entity("departments", {
        "community_id": community["id"],
        "dept_type": dept_type,
        "stations_active_count": 1,
        "career_on_duty_per_shift": 0,
        "volunteers_on_duty_avg": 0,
        "training_hours_per_firefighter_annual": 0,
        "training_facility_level": "C",
        "live_fire_training": False,
        "coverage_pct_within_5mi": 0,
        "data_submitted": False,
    })
    db.new_entity("systems", {
        "community_id": community["id"],
        "needed_fire_flow_gpm": nff,
        "storage_capacity_gal": storage,
        "supply_works_capacity_gpm": supply,
        "daily_consumption_gpm": consumption,
        "alternate_shuttle_capacity_gpm": 0,
        "alternate_sites_count": 0,
        "alternate_verified": False,
        "active_certified_flow_gpm": 0,
        "creditworthy_hydrant_count": 0,
    })
    return ok(db.pub(community), 201)


@bp.route("/ppc/communities", methods=["GET"])
def list_communities():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("communities")
    status = body_arg("status")
    state_code = body_arg("state_code")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if state_code is not None:
        items = [c for c in items if c["state_code"] == state_code]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(c) for c in page], total, limit, offset)


def body_arg(name):
    from flask import request
    return request.args.get(name)


@bp.route("/ppc/communities/<communityId>", methods=["GET"])
def get_community(communityId):
    auth()
    community = db.find("communities", communityId)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    return ok(db.pub(community))


@bp.route("/ppc/communities/<communityId>/attest-comms", methods=["PATCH"])
def attest_comms(communityId):
    uid, role = auth()
    require_role(role, "CommsSupervisor")
    community = db.find("communities", communityId)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    window_or_fail(communityId, DATA_WINDOW_STATES)
    b = body()
    ops = v_range(v_int(need(b, "operators_on_duty_min"), "operators_on_duty_min"),
                  "operators_on_duty_min", lo=0)
    seconds = v_range(v_int(need(b, "avg_alarm_to_dispatch_seconds"), "avg_alarm_to_dispatch_seconds"),
                      "avg_alarm_to_dispatch_seconds", lo=0)
    redundant = v_bool(need(b, "redundant_circuits"), "redundant_circuits")
    backup = v_bool(need(b, "backup_power"), "backup_power")

    community["comms_operators_on_duty_min"] = ops
    community["comms_avg_alarm_to_dispatch_seconds"] = seconds
    community["comms_redundant_circuits"] = redundant
    community["comms_backup_power"] = backup
    community["comms_attested"] = True
    community["comms_attested_by"] = uid
    community["comms_attested_at"] = db.clock_iso()
    db.touch(community)
    recompute_draft_if_scoring(communityId)
    return ok(db.pub(community))


# --- platform clock: mounted OUTSIDE the /ppc api_prefix (SCAFFOLD §1.5) ---

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = auth()
    require_role(role, "EvaluationCoordinator")
    b = body()
    raw = v_str(need(b, "to_iso8601"), "to_iso8601")
    dt = parse_iso_dt(raw)
    if dt is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(dt, raw)
    return ok({"current_utc": raw})
