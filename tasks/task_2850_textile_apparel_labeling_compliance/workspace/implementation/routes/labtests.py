"""Laboratory benches, tolerances and wash performance (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import services
from auth import require_roles
from envelope import created, listing, ok
from errors import fail
from serializers import lab_test_json
from store import create_row, db, ordered, touch
from util import dec, parse_second_instant, plus_days, plus_hours, r1
from validate import (body, find_lab_test, find_style, present, req_array,
                      req_enum, req_int, req_number, req_string)

bp = Blueprint("labtests", __name__)

TEST_TYPES = ("FIBER_CONTENT", "CARE_PERFORMANCE")
METHODS = ("AATCC_20A", "ISO_1833", "AATCC_135", "ISO_6330")
FIBER_METHODS = ("AATCC_20A", "ISO_1833")
CARE_METHODS = ("AATCC_135", "ISO_6330")
WASH_TEMPS = (20, 30, 40, 60, 95)
VALIDITY_DAYS = {"FIBER_CONTENT": calc.FIBER_TEST_VALIDITY_DAYS,
                 "CARE_PERFORMANCE": calc.CARE_TEST_VALIDITY_DAYS}


def _check_method(test_type, method):
    allowed = FIBER_METHODS if test_type == "FIBER_CONTENT" else CARE_METHODS
    if method not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Method %s does not match test type %s." % (method, test_type))


def _window(payload):
    received = parse_second_instant(payload.get("specimen_received_at")
                                    if present(payload, "specimen_received_at") else None)
    due = parse_second_instant(payload.get("results_due_at")
                               if present(payload, "results_due_at") else None)
    if not (due > received):
        fail("ERR_INVALID_REQUEST", "results_due_at must be strictly after specimen_received_at.")
    return received, due


def _occupancy(received, due):
    return received, plus_hours(due, calc.CONDITIONING_BUFFER_HOURS)


def _check_bench(lab_code, method, received, due, exclude_id=None):
    """Ladder 28: at most LAB_BENCH_CAPACITY overlapping reservations per (lab, method).

    The occupancy interval is closed at both ends, so touching intervals collide.
    """
    start, end = _occupancy(received, due)
    overlapping = 0
    for row in db.lab_tests.values():
        if row["id"] == exclude_id or row["state"] != "BENCH_RESERVED":
            continue
        if row["lab_code"] != lab_code or row["method"] != method:
            continue
        other_start, other_end = _occupancy(row["specimen_received_at"], row["results_due_at"])
        if start <= other_end and other_start <= end:
            overlapping += 1
    if overlapping >= calc.LAB_BENCH_CAPACITY:
        fail("ERR_LAB_BENCH_CAPACITY",
             "The requested laboratory and method pair is fully occupied for that window.")


@bp.post("/labeling/lab-tests")
def reserve_bench():
    require_roles("AccreditedLab", "ComplianceAdmin")
    payload = body()
    style = None                                              # ladder 5
    if present(payload, "style_id"):
        style = find_style(payload["style_id"])
    req_string(payload, "style_id")                            # ladder 6
    test_type = req_enum(payload, "test_type", TEST_TYPES)
    lab_code = req_string(payload, "lab_code", min_len=1, max_len=16, pattern=r"^[A-Z0-9\-]+$")
    method = req_enum(payload, "method", METHODS)
    _check_method(test_type, method)
    received, due = _window(payload)
    wash_temp = None
    if test_type == "CARE_PERFORMANCE":
        wash_temp = req_int(payload, "wash_temp_c", allowed=WASH_TEMPS)
    elif present(payload, "wash_temp_c"):
        fail("ERR_INVALID_REQUEST", "wash_temp_c must be null on a fiber-content reservation.")
    if test_type == "FIBER_CONTENT" and not style["declared_fibers"]:   # ladder 24
        fail("ERR_FIBER_DECLARATION_EMPTY", "The style carries no fiber declaration.")
    for row in db.lab_tests.values():                          # ladder 26
        if (row["style_id"] == style["id"] and row["test_type"] == test_type
                and row["state"] == "BENCH_RESERVED"):
            fail("ERR_TEST_ALREADY_RESERVED",
                 "This style already holds a %s reservation." % test_type)
    _check_bench(lab_code, method, received, due)               # ladder 28
    row = create_row(db.lab_tests, {
        "style_id": style["id"],
        "test_type": test_type,
        "lab_code": lab_code,
        "method": method,
        "specimen_received_at": received,
        "results_due_at": due,
        "wash_temp_c": wash_temp,
        "state": "BENCH_RESERVED",
        "attempt_no": 1,
        "measured_fibers": None,
        "dimensional_change_pct": None,
        "colorfastness_grade": None,
        "legibility_cycles": None,
        "cycles_run": None,
        "result_delta_pp_max": None,
        "valid_until": None,
    })
    if test_type == "FIBER_CONTENT":
        style["substantiation_state"] = "FIBER_TEST_PENDING"
        touch(style)
    return created(lab_test_json(row))


def _parse_measured(payload):
    raw = req_array(payload, "measured_fibers")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each measured fiber must be an object.")
        name = req_string(entry, "fiber_generic_name", min_len=1)
        pct = req_number(entry, "measured_pct", 1)
        lines.append({"fiber_generic_name": name, "measured_pct": pct})
    return lines


@bp.post("/labeling/lab-tests/<tid>/results")
def post_results(tid):
    require_roles("AccreditedLab")
    test = find_lab_test(tid)                                  # ladder 3
    payload = body()
    measured = None                                            # ladder 6
    cycles = change = grade = legibility = None
    if test["test_type"] == "FIBER_CONTENT":
        measured = _parse_measured(payload)
    else:
        cycles = req_int(payload, "cycles_run", minimum=0)
        change = req_number(payload, "dimensional_change_pct", 1)
        grade = req_number(payload, "colorfastness_grade", 1, minimum=1.0, maximum=5.0)
        legibility = req_int(payload, "legibility_cycles", minimum=0)
    if test["state"] != "BENCH_RESERVED":                      # ladder 9
        fail("ERR_LAB_TEST_STATE_INVALID", "The laboratory row is not on the bench.")
    style = db.styles.get(test["style_id"])
    if test["test_type"] == "FIBER_CONTENT":
        total = r1(sum((line["measured_pct"] for line in measured), Decimal("0")))
        if total < dec("99.0") or total > dec("101.0"):        # ladder 33
            fail("ERR_LAB_RESULT_INCOHERENT",
                 "Measured percentages must sum to a value within 99.0 through 101.0.")
        delta, passed = calc.fiber_tolerance_evaluation(style, measured)
        test["measured_fibers"] = measured
        test["result_delta_pp_max"] = delta
        if passed:
            test["state"] = "PASSED"
            test["valid_until"] = plus_days(test["specimen_received_at"],
                                            calc.FIBER_TEST_VALIDITY_DAYS)
            touch(test)
            services.supersede_passed_tests(style["id"], "FIBER_CONTENT",
                                            except_id=test["id"])
            style["substantiation_state"] = "FIBER_SUBSTANTIATED"
            touch(style)
        else:
            test["state"] = "FAILED"                           # HOP 1
            touch(test)
            services.fiber_misstated_cascade(style)            # HOP 2..4
    else:
        test["cycles_run"] = cycles
        test["dimensional_change_pct"] = change
        test["colorfastness_grade"] = grade
        test["legibility_cycles"] = legibility
        if calc.care_performance_evaluation(test):
            test["state"] = "PASSED"
            test["valid_until"] = plus_days(test["specimen_received_at"],
                                            calc.CARE_TEST_VALIDITY_DAYS)
            touch(test)
            services.supersede_passed_tests(style["id"], "CARE_PERFORMANCE",
                                            except_id=test["id"])
        else:
            test["state"] = "FAILED"
            touch(test)
    return ok(lab_test_json(test))


@bp.post("/labeling/lab-tests/<tid>/retest")
def retest(tid):
    require_roles("AccreditedLab", "ComplianceAdmin")
    test = find_lab_test(tid)                                  # ladder 3
    payload = body()
    received, due = _window(payload)                           # ladder 6
    lab_code = test["lab_code"]
    if present(payload, "lab_code"):
        lab_code = req_string(payload, "lab_code", min_len=1, max_len=16,
                              pattern=r"^[A-Z0-9\-]+$")
    method = test["method"]
    if present(payload, "method"):
        method = req_enum(payload, "method", METHODS)
    _check_method(test["test_type"], method)
    wash_temp = test["wash_temp_c"]
    if present(payload, "wash_temp_c"):
        if test["test_type"] == "FIBER_CONTENT":
            fail("ERR_INVALID_REQUEST", "wash_temp_c must be null on a fiber-content run.")
        wash_temp = req_int(payload, "wash_temp_c", allowed=WASH_TEMPS)
    if test["state"] != "FAILED":                              # ladder 9
        fail("ERR_LAB_TEST_STATE_INVALID", "Only a failed specimen may be re-benched.")
    _check_bench(lab_code, method, received, due, exclude_id=test["id"])   # ladder 28
    test["specimen_received_at"] = received
    test["results_due_at"] = due
    test["lab_code"] = lab_code
    test["method"] = method
    test["wash_temp_c"] = wash_temp
    test["state"] = "BENCH_RESERVED"
    test["attempt_no"] = test["attempt_no"] + 1
    test["measured_fibers"] = None
    test["dimensional_change_pct"] = None
    test["colorfastness_grade"] = None
    test["legibility_cycles"] = None
    test["cycles_run"] = None
    test["result_delta_pp_max"] = None
    test["valid_until"] = None
    touch(test)
    if test["test_type"] == "FIBER_CONTENT":
        style = db.styles.get(test["style_id"])
        style["substantiation_state"] = "FIBER_TEST_PENDING"
        touch(style)
    return ok(lab_test_json(test))


@bp.get("/labeling/lab-tests/<tid>")
def read_lab_test(tid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "AccreditedLab", "Auditor")
    return ok(lab_test_json(find_lab_test(tid)))


@bp.get("/labeling/styles/<sid>/lab-tests")
def list_style_lab_tests(sid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "AccreditedLab", "Auditor")
    style = find_style(sid)
    rows = ordered([t for t in db.lab_tests.values() if t["style_id"] == style["id"]])
    args = request.args
    for field in ("test_type", "state", "lab_code", "method"):
        if args.get(field) is not None:
            rows = [r for r in rows if r[field] == args.get(field)]
    return listing(rows, lab_test_json)
