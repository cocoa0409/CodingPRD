"""Quality tests: scheduling into bays and recording results (PRD 3.7)."""

from flask import Blueprint

import shapes
from db import (by_creation, db, get_or_404, make_record, now_iso, public,
                touch, values)
from errors import ApiError
from middleware import QUALITY_INSPECTOR, actor
from response import created, list_response, object_response, q_enum, q_str
from services import calc, domain

bp = Blueprint("quality", __name__)

TEST_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "VOIDED")
OCCUPYING_STATUSES = ("SCHEDULED", "PASSED", "FAILED")
OUTCOMES = ("PASS", "FAIL")


def _overlaps(start_a, end_a, start_b, end_b):
    """Closed-interval intersection on whole days."""
    return start_a <= end_b and start_b <= end_a


@bp.post("/quality-tests")
def schedule_test():
    actor(QUALITY_INSPECTOR)
    data = shapes.body()
    unit_id = shapes.get_str(data, "bus_unit_id")
    bay_id = shapes.get_str(data, "test_bay_id")
    test_type = shapes.get_enum(data, "test_type", calc.TEST_TYPES)
    start_raw, start_dt = shapes.get_instant(data, "window_start")
    end_raw, end_dt = shapes.get_instant(data, "window_end")

    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")
    bay = get_or_404(db.bays, bay_id, "ERR_TEST_BAY_NOT_FOUND")

    if unit["production_status"] not in ("SLOTTED", "BODY_JOINED", "BUILT"):
        raise ApiError("ERR_UNIT_PHASE_INVALID")
    if end_dt < start_dt:
        raise ApiError("ERR_INVALID_TEST_WINDOW", "window_end must not precede window_start.")

    start_date = start_dt.date()
    end_date = end_dt.date()
    bay_tests = [t for t in values(db.tests) if t["test_bay_id"] == bay["id"]]

    for other in bay_tests:
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if test_type == "ELECTRICAL" and other["test_type"] == "ELECTRICAL":
            continue
        if _overlaps(start_date, end_date,
                     domain.to_date(other["window_start"]),
                     domain.to_date(other["window_end"])):
            raise ApiError("ERR_TEST_BAY_CONFLICT")

    if test_type not in bay["supported_test_types"]:
        raise ApiError("ERR_TEST_TYPE_UNSUPPORTED")

    if test_type == "ELECTRICAL":
        concurrent = 0
        for other in bay_tests:
            if other["status"] != "SCHEDULED" or other["test_type"] != "ELECTRICAL":
                continue
            if _overlaps(start_date, end_date,
                         domain.to_date(other["window_start"]),
                         domain.to_date(other["window_end"])):
                concurrent += 1
        if concurrent >= int(bay["max_concurrent_electrical"]):
            raise ApiError("ERR_BAY_CONCURRENCY_LIMIT")

    model = db.models[unit["bus_model_id"]]
    profile = db.profiles[unit["spec_profile_id"]]
    test = make_record({
        "bus_unit_id": unit["id"],
        "test_bay_id": bay["id"],
        "test_type": test_type,
        "window_start": start_raw,
        "window_end": end_raw,
        "status": "SCHEDULED",
        "min_required_value": calc.test_minimum_value(test_type, model, profile),
        "measured_value": None,
        "recorded_by_user_id": None,
        "recorded_at": None,
        "result_notes": None,
    })
    db.tests[test["id"]] = test
    return created(public(test))


@bp.get("/quality-tests")
def list_tests():
    actor()
    unit_id = q_str("bus_unit_id")
    bay_id = q_str("test_bay_id")
    test_type = q_enum("test_type", calc.TEST_TYPES)
    status = q_enum("status", TEST_STATUSES)
    rows = []
    for test in values(db.tests):
        if unit_id is not None and test["bus_unit_id"] != unit_id:
            continue
        if bay_id is not None and test["test_bay_id"] != bay_id:
            continue
        if test_type is not None and test["test_type"] != test_type:
            continue
        if status is not None and test["status"] != status:
            continue
        rows.append(test)
    return list_response(by_creation(rows))


@bp.get("/quality-tests/<test_id>")
def read_test(test_id):
    actor()
    test = get_or_404(db.tests, test_id, "ERR_QUALITY_TEST_NOT_FOUND")
    return object_response(public(test))


@bp.post("/quality-tests/<test_id>/record-result")
def record_result(test_id):
    user_id, _role = actor(QUALITY_INSPECTOR)
    data = shapes.body()
    outcome = shapes.get_enum(data, "outcome", OUTCOMES)
    measured = shapes.get_number(data, "measured_value", required=False, default=None)
    notes = shapes.get_str(data, "result_notes", required=False, default=None, allow_empty=True)

    test = get_or_404(db.tests, test_id, "ERR_QUALITY_TEST_NOT_FOUND")
    minimum = test["min_required_value"]
    if minimum is not None and measured is None:
        shapes.bad("Field 'measured_value' is required for a measured test.")
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_NOT_SCHEDULED")
    if outcome == "PASS" and minimum is not None:
        if not calc.dec(measured) >= calc.dec(minimum):
            raise ApiError("ERR_MEASURED_VALUE_BELOW_MINIMUM")

    unit = db.units.get(test["bus_unit_id"])
    test["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    test["measured_value"] = measured if minimum is not None else None
    test["recorded_by_user_id"] = user_id
    test["recorded_at"] = now_iso()
    test["result_notes"] = notes
    touch(test)

    if unit is not None:
        if outcome == "PASS":
            remaining = [t for t in domain.tests_of_unit(unit["id"]) if t["status"] == "FAILED"]
            if unit["certification_status"] == "NONCONFORMING" and not remaining:
                unit["certification_status"] = "PENDING"
                touch(unit)
                domain.recompute_order(domain.order_of_unit(unit))
        else:
            domain.fail_cascade(test, unit)
    return object_response(public(test))
