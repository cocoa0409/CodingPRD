"""Application engineering cases: open, book lab bench time (capacity-gated),
record adhesion results (threshold-judged), retest loop (PRD §3.4)."""

from flask import Blueprint, request

import auth
import calcs
import constants
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_request, invalid_state, not_found

bp = Blueprint("cases", __name__)

SUBSTRATE_CLASSES = {"METAL", "POLYMER", "GLASS", "COMPOSITE"}
TEST_STANDARDS = {"NOMINAL", "APPLICATION_DERATED"}


def _get_case(cid):
    row = store.STORE["cases"].get(cid)
    if row is None:
        raise not_found("ApplicationCase not found")
    return row


@bp.post("/stewardship/application-cases")
def create_case():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["TechnicalEngineer"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    customer_ref = validation.req_str(payload, "customer_ref")
    substrate_class = validation.req_enum(
        payload, "substrate_class", SUBSTRATE_CLASSES)
    description = validation.opt_str(payload, "application_description")
    formulation = store.STORE["formulations"].get(formulation_id)
    if formulation is None:
        raise not_found("Formulation not found")
    if formulation["status"] != "ACTIVE":
        raise invalid_state(
            "Application cases require an ACTIVE formulation")
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "customer_ref": customer_ref,
        "substrate_class": substrate_class,
        "application_description": description,
        "status": "OPEN",
        "failure_count": 0,
        "bench_id": None,
        "bench_date": None,
        "bench_hours": None,
        "peel_strength_n_per_25mm": None,
        "test_temp_c": None,
        "test_standard": None,
        "pass_threshold_applied": None,
    })
    store.STORE["cases"][row["id"]] = row
    return envelope.success_object(ser.application_case(row), 201)


@bp.get("/stewardship/application-cases/<cid>")
def get_case(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.application_case(_get_case(cid)), 200)


@bp.get("/stewardship/application-cases")
def list_cases():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["cases"].values(), request.args,
        ["formulation_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.application_case(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/application-cases/<cid>/book-lab")
def book_lab(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["TechnicalEngineer"])
    payload = validation.get_payload()
    bench_id = validation.req_str(payload, "bench_id")
    bench_date = validation.req_dt(payload, "bench_date")
    bench_hours = validation.req_number(payload, "bench_hours")
    if bench_hours <= 0:
        raise invalid_request("bench_hours must be > 0")
    case = _get_case(cid)
    if case["status"] not in ("OPEN", "CLOSED_FAIL"):
        raise invalid_state(
            "Only an OPEN or CLOSED_FAIL case can book lab time")
    # Priority 21: retest limit when booking from CLOSED_FAIL.
    if (case["status"] == "CLOSED_FAIL"
            and case["failure_count"] >= constants.RETEST_MAX_FAILURES):
        raise api_err("ERR_RETEST_LIMIT_EXCEEDED",
                      "failure_count has reached the retest limit")
    # Priority 27: bench daily capacity, boundary at exactly 8.0 admitted.
    if not calcs.bench_admission_ok(bench_id, bench_date, bench_hours):
        raise api_err("ERR_BENCH_CAPACITY_EXCEEDED",
                      "Booking would exceed the bench's daily capacity")
    case["bench_id"] = bench_id
    case["bench_date"] = bench_date
    case["bench_hours"] = bench_hours
    case["status"] = "LAB_BOOKED"
    store.touch(case)
    return envelope.success_object(ser.application_case(case), 200)


@bp.post("/stewardship/application-cases/<cid>/record-result")
def record_result(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["TechnicalEngineer"])
    payload = validation.get_payload()
    peel = validation.req_number(payload, "peel_strength_n_per_25mm")
    test_temp_c = validation.req_int(payload, "test_temp_c")
    test_standard = validation.req_enum(payload, "test_standard", TEST_STANDARDS)
    case = _get_case(cid)
    if case["status"] != "LAB_BOOKED":
        raise invalid_state(
            "Only a LAB_BOOKED case can record a result")
    passed, threshold = calcs.adhesion_pass(
        case["substrate_class"], test_standard, test_temp_c, peel)
    case["peel_strength_n_per_25mm"] = peel
    case["test_temp_c"] = test_temp_c
    case["test_standard"] = test_standard
    case["pass_threshold_applied"] = float(threshold)
    if passed:
        case["status"] = "CLOSED_PASS"
    else:
        case["status"] = "CLOSED_FAIL"
        case["failure_count"] += 1
    # Leaving LAB_BOOKED releases the bench hours (compensating pair).
    store.touch(case)
    return envelope.success_object(ser.application_case(case), 200)
