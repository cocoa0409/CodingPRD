"""Flight tests and the delivery acceptance pipeline (PRD 3.8)."""
from flask import Blueprint, g

import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    new_row,
    paginate,
    parse_dt,
    q_enum,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("delivery", __name__, url_prefix="/api")

RANGE_CODES = ("RANGE_ALPHA", "RANGE_BRAVO")
FLIGHT_TEST_STATUSES = ("SCHEDULED", "COMPLETED")
OUTCOMES = ("PASS", "FAIL")


# ---------------------------------------------------------------------------
# Flight tests
# ---------------------------------------------------------------------------
@bp.post("/aircraft-units/<aircraft_id>/flight-tests")
@endpoint("DeliveryManager")
def create_flight_test(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    payload = body()
    # rung 5a -- pipeline stage: aircraft must be in FLIGHT_TESTING
    if aircraft["delivery_status"] != "FLIGHT_TESTING":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 5b -- quality status must be CLEAR
    if aircraft["quality_status"] != "CLEAR":
        raise ApiError("ERR_QUALITY_HOLD")
    # rung 7 -- window_end strictly after window_start
    window_start = parse_dt(payload.get("window_start"))
    window_end = parse_dt(payload.get("window_end"))
    if window_start is not None and window_end is not None and not window_end > window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    # rung 8 -- half-open [start, end) must not intersect another SCHEDULED test
    # on the same range_code; exact adjacency is permitted.
    range_code = payload.get("range_code")
    if (
        window_start is not None
        and window_end is not None
        and isinstance(range_code, str)
    ):
        for other in db.flight_tests.values():
            if other["range_code"] != range_code or other["status"] != "SCHEDULED":
                continue
            if window_start < other["window_end"] and other["window_start"] < window_end:
                raise ApiError("ERR_RANGE_WINDOW_OVERLAP")
    # rung 10 -- body shape
    range_code = f_enum(payload, "range_code", RANGE_CODES)
    window_start = f_dt(payload, "window_start")
    window_end = f_dt(payload, "window_end")
    test = new_row(
        "FlightTest",
        aircraft_id=aircraft["id"],
        range_code=range_code,
        window_start=window_start,
        window_end=window_end,
        outcome=None,
        status="SCHEDULED",
    )
    db.flight_tests[test["id"]] = test
    return respond_object(svc.dump_flight_test(test), 201)


@bp.get("/aircraft-units/<aircraft_id>/flight-tests")
@endpoint("ProgramAdmin", "DeliveryManager", "Customer")
def list_flight_tests(aircraft_id):
    svc.need_aircraft(aircraft_id)
    status = q_enum("status", FLIGHT_TEST_STATUSES)
    rows = [t for t in db.flight_tests.values() if t["aircraft_id"] == aircraft_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return paginate(sort_created(rows), svc.dump_flight_test)


@bp.post("/flight-tests/<test_id>/record-outcome")
@endpoint("DeliveryManager")
def record_outcome(test_id):
    test = svc.need_flight_test(test_id)
    payload = body()
    # rung 5 -- state gate
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 10 -- body shape
    outcome = f_enum(payload, "outcome", OUTCOMES)
    rework_estimated_hours = f_int(
        payload, "rework_estimated_hours", required=False, minimum=0
    )
    test["outcome"] = outcome
    test["status"] = "COMPLETED"
    touch(test)
    if outcome == "FAIL":
        aircraft = svc.need_aircraft(test["aircraft_id"])
        # Cascade 1: the aircraft drops to REJECTED.
        aircraft["delivery_status"] = "REJECTED"
        touch(aircraft)
        # Cascade 2: provisional FLIGHT_TEST_FAILURE rework order; the payload's
        # rework_estimated_hours is optional and defaults to a zero hours basis.
        svc.create_rework_order(
            aircraft["id"], "FLIGHT_TEST_FAILURE", rework_estimated_hours or 0
        )
        # Cascade 3: every live negotiation of the aircraft auto-expires.
        svc.expire_live_negotiations(aircraft["id"])
    # PASS advances nothing by itself; the pipeline moves via verify-configuration.
    return respond_object(svc.dump_flight_test(test))


# ---------------------------------------------------------------------------
# Delivery acceptance pipeline stages
# ---------------------------------------------------------------------------
@bp.post("/aircraft-units/<aircraft_id>/begin-delivery")
@endpoint("DeliveryManager")
def begin_delivery(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    if aircraft["production_status"] != "ASSEMBLY_COMPLETE" or aircraft[
        "delivery_status"
    ] not in ("NOT_STARTED", "REJECTED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    # The REJECTED retry is gated on no OPEN rework remaining (PRD 3.8).
    if aircraft["delivery_status"] == "REJECTED" and svc.any_open_rework(aircraft["id"]):
        raise ApiError("ERR_INVALID_TRANSITION")
    aircraft["delivery_status"] = "FLIGHT_TESTING"
    touch(aircraft)
    return respond_object(svc.dump_aircraft(aircraft))


@bp.post("/aircraft-units/<aircraft_id>/verify-configuration")
@endpoint("DeliveryManager")
def verify_configuration(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    # rung 5 -- pipeline stage plus a clean flight-test record: at least one
    # COMPLETED, every COMPLETED a PASS, and no SCHEDULED test remaining.
    if aircraft["delivery_status"] != "FLIGHT_TESTING":
        raise ApiError("ERR_INVALID_TRANSITION")
    tests = [t for t in db.flight_tests.values() if t["aircraft_id"] == aircraft["id"]]
    completed = [t for t in tests if t["status"] == "COMPLETED"]
    scheduled = [t for t in tests if t["status"] == "SCHEDULED"]
    if (
        len(completed) < 1
        or len(scheduled) > 0
        or any(t["outcome"] != "PASS" for t in completed)
    ):
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 8 -- as-built configuration must equal the contracted configuration
    if aircraft["configuration_code"] != aircraft["ordered_configuration_code"]:
        raise ApiError("ERR_CONFIGURATION_MISMATCH")
    aircraft["delivery_status"] = "CONFIG_VERIFIED"
    touch(aircraft)
    return respond_object(svc.dump_aircraft(aircraft))


@bp.post("/aircraft-units/<aircraft_id>/conduct-walkthrough")
@endpoint("Customer")
def conduct_walkthrough(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    # Entity-backed ownership: the acting Customer must be the buyer (PRD 2.1).
    if g.user_id != aircraft["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    payload = body()
    # rung 5 -- pipeline stage
    if aircraft["delivery_status"] != "CONFIG_VERIFIED":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 10 -- body shape
    snag_count = f_int(payload, "snag_count", minimum=0)
    if snag_count == 0:
        aircraft["delivery_status"] = "WALKTHROUGH_PASSED"
    else:
        aircraft["delivery_status"] = "REJECTED"
        # One or more snags reject the walkthrough and spawn WALKTHROUGH_SNAG
        # rework on a basis of four hours per snag (PRD 3.8/3.5).
        svc.create_rework_order(
            aircraft["id"], "WALKTHROUGH_SNAG", snag_count * 4
        )
    touch(aircraft)
    return respond_object(svc.dump_aircraft(aircraft))


@bp.post("/aircraft-units/<aircraft_id>/accept-delivery")
@endpoint("Customer")
def accept_delivery(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    # Entity-backed ownership: the acting Customer must be the buyer (PRD 2.1).
    if g.user_id != aircraft["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    # rung 5a -- the one gate reading all three state dimensions (PRD 3.8)
    if not (
        aircraft["production_status"] == "ASSEMBLY_COMPLETE"
        and aircraft["delivery_status"] == "WALKTHROUGH_PASSED"
        and aircraft["quality_status"] == "CLEAR"
    ):
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 5b -- no OPEN rework order may remain on the aircraft
    if svc.any_open_rework(aircraft["id"]):
        raise ApiError("ERR_REWORK_ORDERS_OPEN")
    aircraft["delivery_status"] = "ACCEPTED"
    aircraft["production_status"] = "DELIVERED"
    touch(aircraft)
    return respond_object(svc.dump_aircraft(aircraft))
