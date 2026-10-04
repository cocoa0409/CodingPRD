"""Procurement and AcceptanceTest endpoints (PRD 3.4, ledger in PRD 2.8).

Placement pins the certificate version and encumbers the jurisdiction budget;
ACCEPTED moves encumbered -> spent; REJECTED/CANCELLED release the
encumbrance. Acceptance tests are immutable records (id + created_at only).
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_acting_official, require_role, require_transition_actor
from constants import (
    ACCEPTANCE_INDEX_CAP,
    ACCEPTANCE_INDEX_MAX,
    W_CALIBRATION,
    W_HARDWARE,
    W_LOGIC,
)
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_request, err_invalid_state, err_not_found, raise_err
from store import db
from util import stamp_new, touch
from validation import body_json, no_extra, opt_str, req_enum, req_int, req_str

bp = Blueprint("procurements", __name__)

PROC_STATES = {"PLACED", "DELIVERED", "ACCEPTANCE_TESTING", "ACCEPTED", "REJECTED", "CANCELLED"}
PROC_ACTORS = {
    "DELIVERED": {"ElectionOfficial"},
    "ACCEPTANCE_TESTING": {"ElectionOfficial"},
    "ACCEPTED": {"ElectionOfficial"},
    "REJECTED": {"ElectionOfficial"},
    "CANCELLED": {"ElectionOfficial"},
}
PROC_FROM = {
    "DELIVERED": {"PLACED"},
    "ACCEPTANCE_TESTING": {"DELIVERED"},
    "ACCEPTED": {"ACCEPTANCE_TESTING"},
    "REJECTED": {"ACCEPTANCE_TESTING"},
    "CANCELLED": {"PLACED", "DELIVERED"},
}
TEST_TYPES = {"HARDWARE_DIAGNOSTIC", "BALLOT_SCAN_CALIBRATION", "LOGIC_VERIFICATION"}
WEIGHTS = {
    "HARDWARE_DIAGNOSTIC": W_HARDWARE,
    "BALLOT_SCAN_CALIBRATION": W_CALIBRATION,
    "LOGIC_VERIFICATION": W_LOGIC,
}
RELEASING_STATES = {"PLACED", "DELIVERED", "ACCEPTANCE_TESTING"}


def release_encumbrance(proc):
    jurisdiction = db.jurisdictions.get(proc["jurisdiction_id"])
    if jurisdiction is not None:
        jurisdiction["encumbered_cents"] -= proc["total_price_cents"]
        jurisdiction["available_cents"] += proc["total_price_cents"]
        touch(jurisdiction)


@bp.post("/evote/procurements")
def create_procurement():
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    body = body_json()
    no_extra(body, {"jurisdiction_id", "voting_system_id", "certificate_id", "quantity", "unit_price_cents"})
    jurisdiction_id = req_str(body, "jurisdiction_id")
    system_id = req_str(body, "voting_system_id")
    certificate_id = req_str(body, "certificate_id")
    quantity = req_int(body, "quantity", minv=1)
    unit_price = req_int(body, "unit_price_cents", minv=0)
    jurisdiction = db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise_err("ERR_JURISDICTION_NOT_FOUND", 404, "jurisdiction_id does not resolve")
    system = db.voting_systems.get(system_id)
    if system is None:
        raise_err("ERR_SYSTEM_NOT_FOUND", 404, "voting_system_id does not resolve")
    cert = db.certificates.get(certificate_id)
    if cert is None:
        raise_err("ERR_CERTIFICATE_NOT_FOUND", 404, "certificate_id does not resolve")
    require_acting_official(uid, jurisdiction_id)
    if cert["voting_system_id"] != system_id:
        raise_err("ERR_CERTIFICATE_SYSTEM_MISMATCH", 422, "certificate belongs to a different system")
    if cert["scope"] != "FEDERAL" and cert["state_code"] != jurisdiction["state_code"]:
        raise_err("ERR_CERTIFICATE_SCOPE_MISMATCH", 422, "certificate scope does not cover jurisdiction state")
    if cert["status"] != "ACTIVE":
        raise_err("ERR_CERTIFICATE_NOT_ACTIVE", 422, "certificate is not ACTIVE")
    if system["status"] == "RETIRED":
        raise_err("ERR_SYSTEM_RETIRED", 422, "voting system is RETIRED")
    total = quantity * unit_price
    if total > jurisdiction["available_cents"]:
        raise_err("ERR_BUDGET_EXCEEDED", 402, "total_price_cents exceeds available_cents")
    rec = stamp_new({})
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "voting_system_id": system_id,
        "certificate_id": certificate_id,
        "certificate_version_pinned": cert["version"],
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "total_price_cents": total,
        "cert_hold": False,
        "status": "PLACED",
        "status_reason": None,
    })
    db.procurements[rec["id"]] = rec
    jurisdiction["available_cents"] -= total
    jurisdiction["encumbered_cents"] += total
    touch(jurisdiction)
    return ok_object(rec, 201)


@bp.get("/evote/procurements")
def list_procurements():
    auth_context()
    items = apply_filters(
        list(db.procurements.values()),
        {"jurisdiction_id", "voting_system_id", "certificate_id", "status"},
    )
    return list_page(items)


def get_procurement_or_404(proc_id):
    proc = db.procurements.get(proc_id)
    if proc is None:
        err_not_found("procurement not found")
    return proc


@bp.get("/evote/procurements/<proc_id>")
def get_procurement(proc_id):
    auth_context()
    return ok_object(get_procurement_or_404(proc_id), 200)


@bp.post("/evote/procurements/<proc_id>/transitions")
def procurement_transition(proc_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    ts = peek_to_state()
    require_transition_actor(role, ts, PROC_ACTORS)
    proc = get_procurement_or_404(proc_id)
    body = body_json()
    no_extra(body, {"to_state", "reason"})
    to_state = req_enum(body, "to_state", PROC_STATES)
    reason = None
    if to_state == "REJECTED":
        reason = opt_str(body, "reason")
        if not reason:
            err_invalid_request("reason is required for REJECTED")
    else:
        reason = opt_str(body, "reason")
    require_acting_official(uid, proc["jurisdiction_id"])
    if proc["status"] not in PROC_FROM[to_state]:
        err_invalid_state("procurement cannot transition from %s to %s" % (proc["status"], to_state))
    if to_state in {"ACCEPTANCE_TESTING", "ACCEPTED"}:
        if to_state == "ACCEPTED":
            tests = [t for t in db.acceptance_tests.values() if t["procurement_id"] == proc_id]
            types_seen = {t["test_type"] for t in tests}
            if "HARDWARE_DIAGNOSTIC" not in types_seen or "BALLOT_SCAN_CALIBRATION" not in types_seen:
                raise_err("ERR_ACCEPTANCE_TESTS_INCOMPLETE", 422, "required acceptance test types missing")
            if any(t["result"] == "FAIL" for t in tests):
                raise_err("ERR_ACCEPTANCE_TEST_FAILURES_PRESENT", 422, "an acceptance test has result FAIL")
        cert = db.certificates.get(proc["certificate_id"])
        if cert is None or cert["status"] != "ACTIVE" or (to_state == "ACCEPTED" and proc["cert_hold"]):
            raise_err("ERR_CERTIFICATE_NOT_ACTIVE", 422, "pinned certificate is not ACTIVE")
    proc["status"] = to_state
    if to_state == "REJECTED":
        proc["status_reason"] = reason
    elif to_state == "CANCELLED" and reason is not None:
        proc["status_reason"] = reason
    if to_state == "ACCEPTED":
        jurisdiction = db.jurisdictions.get(proc["jurisdiction_id"])
        jurisdiction["encumbered_cents"] -= proc["total_price_cents"]
        jurisdiction["spent_cents"] += proc["total_price_cents"]
        touch(jurisdiction)
    elif to_state in {"REJECTED", "CANCELLED"}:
        release_encumbrance(proc)
    touch(proc)
    return ok_object(proc, 200)


@bp.post("/evote/procurements/<proc_id>/acceptance-tests")
def create_acceptance_test(proc_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    proc = get_procurement_or_404(proc_id)
    body = body_json()
    no_extra(body, {"test_type", "critical_defects", "major_defects", "minor_defects"})
    test_type = req_enum(body, "test_type", TEST_TYPES)
    critical = req_int(body, "critical_defects", minv=0)
    major = req_int(body, "major_defects", minv=0)
    minor = req_int(body, "minor_defects", minv=0)
    require_acting_official(uid, proc["jurisdiction_id"])
    if proc["status"] != "ACCEPTANCE_TESTING":
        err_invalid_state("acceptance tests require the procurement to be ACCEPTANCE_TESTING")
    wc, wm, wn = WEIGHTS[test_type]
    index = min(ACCEPTANCE_INDEX_CAP, wc * critical + wm * major + wn * minor)
    result = "PASS" if critical == 0 and index <= ACCEPTANCE_INDEX_MAX else "FAIL"
    rec = stamp_new({}, versioned=False)
    rec.update({
        "procurement_id": proc_id,
        "test_type": test_type,
        "critical_defects": critical,
        "major_defects": major,
        "minor_defects": minor,
        "deficiency_index": index,
        "result": result,
    })
    db.acceptance_tests[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/procurements/<proc_id>/acceptance-tests")
def list_acceptance_tests(proc_id):
    auth_context()
    get_procurement_or_404(proc_id)
    items = [t for t in db.acceptance_tests.values() if t["procurement_id"] == proc_id]
    items = apply_filters(items, {"test_type", "result"})
    return list_page(items)
