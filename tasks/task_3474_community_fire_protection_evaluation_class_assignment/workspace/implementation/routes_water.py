"""Water supply systems, hydrants, and certified flow testing."""
from flask import Blueprint, request

import db
from cascade import (DATA_WINDOW_STATES, window_or_fail, recompute_draft_if_scoring,
                     recompute_hydrant, recompute_system_aggregates)
from errors import fail
from middleware import auth, require_role, require_owner
from response import ok, ok_list
from scoring import compute_flow_20
from util import (body, need, v_int, v_num, v_str, v_enum, v_range, v_date,
                  pagination_params, page_of, parse_date, dec)
from decimal import Decimal

bp = Blueprint("water", __name__)

HYDRANT_STATUSES = ("ACTIVE", "OUT_OF_SERVICE")
FLOW_TEST_TARGETS = ("WITNESSED", "CERTIFIED", "REJECTED", "CORRECTED")
FLOW_TEST_EDGES = {
    ("SUBMITTED", "WITNESSED"),
    ("WITNESSED", "CERTIFIED"),
    ("WITNESSED", "REJECTED"),
    ("CERTIFIED", "CORRECTED"),
}


def _validate_psi(static_psi, residual_psi, measured_flow_gpm):
    s = dec(v_num(static_psi, "static_psi"))
    v_range(static_psi, "static_psi", lo=Decimal("20"), lo_inclusive=False, hi=Decimal("300"))
    r = dec(v_num(residual_psi, "residual_psi"))
    v_range(residual_psi, "residual_psi", lo=Decimal("10"))
    if not (r < s):
        fail("ERR_INVALID_REQUEST", "residual_psi must be strictly below static_psi")
    v_range(v_num(measured_flow_gpm, "measured_flow_gpm"), "measured_flow_gpm",
            lo=Decimal("0"), lo_inclusive=False)


@bp.route("/ppc/water-supply-systems", methods=["GET"])
def list_systems():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("systems")
    v = request.args.get("community_id")
    if v is not None:
        items = [s for s in items if s["community_id"] == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(s) for s in page], total, limit, offset)


@bp.route("/ppc/water-supply-systems/<systemId>", methods=["GET"])
def get_system(systemId):
    auth()
    system = db.find("systems", systemId)
    if system is None:
        fail("ERR_SYSTEM_NOT_FOUND", "water supply system does not exist")
    return ok(db.pub(system))


@bp.route("/ppc/water-supply-systems/<systemId>", methods=["PATCH"])
def patch_system(systemId):
    uid, role = auth()
    require_role(role, "WaterUtilityManager")
    require_owner(systemId == uid)
    system = db.find("systems", systemId)
    if system is None:
        fail("ERR_SYSTEM_NOT_FOUND", "water supply system does not exist")
    window_or_fail(system["community_id"], DATA_WINDOW_STATES)
    b = body()
    if "needed_fire_flow_gpm" in b:
        system["needed_fire_flow_gpm"] = v_range(v_int(b["needed_fire_flow_gpm"], "needed_fire_flow_gpm"),
                                                 "needed_fire_flow_gpm", lo=500, hi=50000)
    if "storage_capacity_gal" in b:
        system["storage_capacity_gal"] = v_range(v_int(b["storage_capacity_gal"], "storage_capacity_gal"),
                                                 "storage_capacity_gal", lo=0)
    if "supply_works_capacity_gpm" in b:
        system["supply_works_capacity_gpm"] = v_range(v_int(b["supply_works_capacity_gpm"], "supply_works_capacity_gpm"),
                                                      "supply_works_capacity_gpm", lo=0, lo_inclusive=False)
    if "daily_consumption_gpm" in b:
        system["daily_consumption_gpm"] = v_range(v_int(b["daily_consumption_gpm"], "daily_consumption_gpm"),
                                                  "daily_consumption_gpm", lo=0)
    if "alternate_shuttle_capacity_gpm" in b:
        system["alternate_shuttle_capacity_gpm"] = v_range(
            v_int(b["alternate_shuttle_capacity_gpm"], "alternate_shuttle_capacity_gpm"),
            "alternate_shuttle_capacity_gpm", lo=0)
    if "alternate_sites_count" in b:
        system["alternate_sites_count"] = v_range(v_int(b["alternate_sites_count"], "alternate_sites_count"),
                                                  "alternate_sites_count", lo=0)
    db.touch(system)
    recompute_draft_if_scoring(system["community_id"])
    return ok(db.pub(system))


@bp.route("/ppc/water-supply-systems/<systemId>/verify-alternate-supply", methods=["POST"])
def verify_alternate_supply(systemId):
    uid, role = auth()
    require_role(role, "FieldAnalyst")
    system = db.find("systems", systemId)
    if system is None:
        fail("ERR_SYSTEM_NOT_FOUND", "water supply system does not exist")
    window_or_fail(system["community_id"], ("FIELD_VERIFICATION", "SCORING"))
    if not (system["alternate_shuttle_capacity_gpm"] > 0 and system["alternate_sites_count"] >= 1):
        fail("ERR_ALTERNATE_SUPPLY_INSUFFICIENT",
             "alternate supply verification requires shuttle capacity > 0 and at least one site")
    system["alternate_verified"] = True
    db.touch(system)
    recompute_draft_if_scoring(system["community_id"])
    return ok(db.pub(system))


@bp.route("/ppc/hydrants", methods=["POST"])
def create_hydrant():
    uid, role = auth()
    require_role(role, "WaterUtilityManager")
    b = body()
    system_id = v_str(need(b, "system_id"), "system_id")
    require_owner(system_id == uid)
    system = db.find("systems", system_id)
    if system is None:
        fail("ERR_SYSTEM_NOT_FOUND", "water supply system does not exist")
    window_or_fail(system["community_id"], DATA_WINDOW_STATES)
    location = v_str(need(b, "location_descriptor"), "location_descriptor")
    hydrant = db.new_entity("hydrants", {
        "system_id": system_id,
        "location_descriptor": location,
        "status": "ACTIVE",
        "max_flow_gpm": None,
        "last_certified_test_date": None,
    })
    return ok(db.pub(hydrant), 201)


@bp.route("/ppc/hydrants", methods=["GET"])
def list_hydrants():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("hydrants")
    for f in ("system_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [h for h in items if str(h[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(h) for h in page], total, limit, offset)


@bp.route("/ppc/hydrants/<hydrantId>", methods=["GET"])
def get_hydrant(hydrantId):
    auth()
    hydrant = db.find("hydrants", hydrantId)
    if hydrant is None:
        fail("ERR_HYDRANT_NOT_FOUND", "hydrant does not exist")
    return ok(db.pub(hydrant))


@bp.route("/ppc/hydrants/<hydrantId>", methods=["PATCH"])
def patch_hydrant(hydrantId):
    uid, role = auth()
    require_role(role, "WaterUtilityManager")
    hydrant = db.find("hydrants", hydrantId)
    if hydrant is None:
        fail("ERR_HYDRANT_NOT_FOUND", "hydrant does not exist")
    require_owner(hydrant["system_id"] == uid)
    b = body()
    target = v_enum(need(b, "status"), "status", HYDRANT_STATUSES)
    system = db.find("systems", hydrant["system_id"])
    window_or_fail(system["community_id"], DATA_WINDOW_STATES)
    hydrant["status"] = target
    db.touch(hydrant)
    recompute_system_aggregates(system)
    recompute_draft_if_scoring(system["community_id"])
    return ok(db.pub(hydrant))


@bp.route("/ppc/flow-tests", methods=["POST"])
def create_flow_test():
    uid, role = auth()
    require_role(role, "WaterUtilityManager")
    b = body()
    system_id = v_str(need(b, "system_id"), "system_id")
    require_owner(system_id == uid)
    system = db.find("systems", system_id)
    if system is None:
        fail("ERR_SYSTEM_NOT_FOUND", "water supply system does not exist")
    hydrant_id = v_str(need(b, "hydrant_id"), "hydrant_id")
    hydrant = db.find("hydrants", hydrant_id)
    if hydrant is None:
        fail("ERR_HYDRANT_NOT_FOUND", "hydrant does not exist")
    window_or_fail(system["community_id"], ("DATA_COLLECTION", "FIELD_VERIFICATION"))
    test_date = v_date(need(b, "test_date"), "test_date")
    if test_date > db.clock_date():
        fail("ERR_TEST_DATE_IN_FUTURE", "flow test date is after the logical clock date")
    if hydrant["system_id"] != system["id"]:
        fail("ERR_INVALID_REQUEST", "hydrant does not belong to the named water supply system")
    _validate_psi(need(b, "static_psi"), need(b, "residual_psi"), need(b, "measured_flow_gpm"))

    test = db.new_entity("flow_tests", {
        "system_id": system_id,
        "hydrant_id": hydrant_id,
        "supersedes_test_id": None,
        "test_date": test_date.isoformat(),
        "static_psi": b["static_psi"],
        "residual_psi": b["residual_psi"],
        "measured_flow_gpm": b["measured_flow_gpm"],
        "flow_at_20psi_gpm": None,
        "status": "SUBMITTED",
        "witnessed_by": None,
        "certified_by": None,
        "correction_reason": None,
    })
    return ok(db.pub(test), 201)


@bp.route("/ppc/flow-tests", methods=["GET"])
def list_flow_tests():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("flow_tests")
    for f in ("system_id", "hydrant_id", "status", "supersedes_test_id"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if str(t[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(t) for t in page], total, limit, offset)


@bp.route("/ppc/flow-tests/<testId>", methods=["GET"])
def get_flow_test(testId):
    auth()
    test = db.find("flow_tests", testId)
    if test is None:
        fail("ERR_FLOW_TEST_NOT_FOUND", "flow test does not exist")
    return ok(db.pub(test))


@bp.route("/ppc/flow-tests/<testId>/transition", methods=["POST"])
def transition_flow_test(testId):
    uid, role = auth()
    require_role(role, "FieldAnalyst")
    test = db.find("flow_tests", testId)
    if test is None:
        fail("ERR_FLOW_TEST_NOT_FOUND", "flow test does not exist")
    b = body()
    target = v_str(need(b, "target_state"), "target_state")
    if target not in FLOW_TEST_TARGETS or (test["status"], target) not in FLOW_TEST_EDGES:
        fail("ERR_FLOW_TEST_INVALID_STATE",
             "flow test cannot move from %s to %s" % (test["status"], target))
    system = db.find("systems", test["system_id"])
    if target == "CORRECTED":
        window_or_fail(system["community_id"], ("FIELD_VERIFICATION", "SCORING"))
    else:
        window_or_fail(system["community_id"], ("FIELD_VERIFICATION",))
    hydrant = db.find("hydrants", test["hydrant_id"])

    if target == "WITNESSED":
        test["status"] = "WITNESSED"
        test["witnessed_by"] = uid
        db.touch(test)
        return ok(db.pub(test))

    if target == "REJECTED":
        test["status"] = "REJECTED"
        db.touch(test)
        return ok(db.pub(test))

    if target == "CERTIFIED":
        test["status"] = "CERTIFIED"
        test["certified_by"] = uid
        test["flow_at_20psi_gpm"] = compute_flow_20(
            test["static_psi"], test["residual_psi"], test["measured_flow_gpm"])
        db.touch(test)
        recompute_hydrant(hydrant)
        db.touch(hydrant)
        recompute_system_aggregates(system)
        return ok(db.pub(test))

    # CORRECTED: original becomes SUPERSEDED, replacement created in CERTIFIED
    c_static = need(b, "corrected_static_psi")
    c_residual = need(b, "corrected_residual_psi")
    c_measured = need(b, "corrected_measured_flow_gpm")
    reason = v_str(need(b, "correction_reason"), "correction_reason")
    _validate_psi(c_static, c_residual, c_measured)

    test["status"] = "SUPERSEDED"
    db.touch(test)
    replacement = db.new_entity("flow_tests", {
        "system_id": test["system_id"],
        "hydrant_id": test["hydrant_id"],
        "supersedes_test_id": test["id"],
        "test_date": test["test_date"],
        "static_psi": c_static,
        "residual_psi": c_residual,
        "measured_flow_gpm": c_measured,
        "flow_at_20psi_gpm": compute_flow_20(c_static, c_residual, c_measured),
        "status": "CERTIFIED",
        "witnessed_by": None,
        "certified_by": uid,
        "correction_reason": reason,
    })
    recompute_hydrant(hydrant)
    db.touch(hydrant)
    recompute_system_aggregates(system)
    recompute_draft_if_scoring(system["community_id"])
    return ok(db.pub(replacement))
