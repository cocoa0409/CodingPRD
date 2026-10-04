"""LogicAccuracyTest endpoints (PRD 3.6).

Exact integer verification: result is PASS iff
10000 * total_discrepancy <= LA_DISCREPANCY_MAX_BP * total_expected (boundary
inclusive; the rounded discrepancy_bp is display only). Segregation of duties:
the conductor may not certify or challenge their own test.
"""
from flask import Blueprint

from auth import auth_context, require_acting_official, require_role
from constants import BP_SCALE, LA_DISCREPANCY_MAX_BP
from domains.definitions import get_definition_or_404
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import stamp_new, touch
from validation import body_json, is_int_value, no_extra, req_enum, req_obj

bp = Blueprint("la_tests", __name__)

LA_STATES = {"CONDUCTED", "CERTIFIED", "CHALLENGED"}
LA_FROM = {
    "CERTIFIED": {"CONDUCTED"},
    "CHALLENGED": {"CONDUCTED"},
    "CONDUCTED": {"CHALLENGED"},
}


def validate_tallies(expected, scanned):
    """ERR_INVALID_TALLIES on key mismatch, bad values, or zero expected total."""
    if set(expected.keys()) != set(scanned.keys()):
        raise_err("ERR_INVALID_TALLIES", 422, "tally key sets differ")
    for mapping in (expected, scanned):
        for value in mapping.values():
            if not is_int_value(value) or value < 0:
                raise_err("ERR_INVALID_TALLIES", 422, "tally values must be non-negative integers")
    total_expected = sum(expected.values())
    if total_expected < 1:
        raise_err("ERR_INVALID_TALLIES", 422, "total_expected must be at least 1")
    return total_expected


def compute_result(expected, scanned):
    total_expected = sum(expected.values())
    total_discrepancy = sum(abs(expected[k] - scanned[k]) for k in expected)
    discrepancy_bp = (BP_SCALE * total_discrepancy) // total_expected
    passes = BP_SCALE * total_discrepancy <= LA_DISCREPANCY_MAX_BP * total_expected
    return total_expected, total_discrepancy, discrepancy_bp, "PASS" if passes else "FAIL"


@bp.post("/evote/election-definitions/<definition_id>/la-tests")
def create_la_test(definition_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    definition = get_definition_or_404(definition_id)
    body = body_json()
    no_extra(body, {"expected_tallies", "scanned_tallies"})
    expected = req_obj(body, "expected_tallies")
    scanned = req_obj(body, "scanned_tallies")
    require_acting_official(uid, definition["jurisdiction_id"])
    if definition["status"] not in {"PROGRAMMED", "LA_PASSED"}:
        err_invalid_state("L&A tests require a PROGRAMMED or LA_PASSED definition")
    validate_tallies(expected, scanned)
    total_expected, total_discrepancy, discrepancy_bp, result = compute_result(expected, scanned)
    rec = stamp_new({})
    rec.update({
        "election_definition_id": definition_id,
        "conducted_by": uid,
        "certified_by": None,
        "expected_tallies": expected,
        "scanned_tallies": scanned,
        "total_expected": total_expected,
        "total_discrepancy": total_discrepancy,
        "discrepancy_bp": discrepancy_bp,
        "result": result,
        "status": "CONDUCTED",
    })
    db.logic_accuracy_tests[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/election-definitions/<definition_id>/la-tests")
def list_la_tests(definition_id):
    auth_context()
    get_definition_or_404(definition_id)
    items = [t for t in db.logic_accuracy_tests.values() if t["election_definition_id"] == definition_id]
    items = apply_filters(items, {"status", "result"})
    return list_page(items)


def get_la_test_or_404(test_id):
    test = db.logic_accuracy_tests.get(test_id)
    if test is None:
        err_not_found("logic & accuracy test not found")
    return test


@bp.post("/evote/logic-accuracy-tests/<test_id>/transitions")
def la_test_transition(test_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    test = get_la_test_or_404(test_id)
    body = body_json()
    no_extra(body, {"to_state", "scanned_tallies"})
    to_state = req_enum(body, "to_state", LA_STATES)
    definition = get_definition_or_404(test["election_definition_id"])
    require_acting_official(uid, definition["jurisdiction_id"])
    # Priority 7: segregation of duties (before state legality).
    if to_state in {"CERTIFIED", "CHALLENGED"} and uid == test["conducted_by"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", 403, "conductor may not certify or challenge their own test")
    if test["status"] not in LA_FROM[to_state]:
        err_invalid_state("L&A test cannot transition from %s to %s" % (test["status"], to_state))
    if to_state == "CERTIFIED":
        test["certified_by"] = uid
    elif to_state == "CONDUCTED":
        # Reopen: fresh scanned_tallies whose key set equals expected_tallies
        # (missing or malformed -> ERR_INVALID_TALLIES per the transition
        # precondition).
        new_scanned = body.get("scanned_tallies")
        if not isinstance(new_scanned, dict):
            raise_err("ERR_INVALID_TALLIES", 422, "scanned_tallies is required to reopen")
        validate_tallies(test["expected_tallies"], new_scanned)
        _, total_discrepancy, discrepancy_bp, result = compute_result(test["expected_tallies"], new_scanned)
        test["scanned_tallies"] = new_scanned
        test["total_discrepancy"] = total_discrepancy
        test["discrepancy_bp"] = discrepancy_bp
        test["result"] = result
        test["certified_by"] = None
    test["status"] = to_state
    touch(test)
    return ok_object(test, 200)
