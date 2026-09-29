"""Clock, pilots, knowledge tests and certifications (PRD 3.1, 3.2, 3.9)."""

from flask import Blueprint

import calc
import cascades
from auth import authenticate, check_body_owner, check_owns
from clockmod import add_days, clock, fmt_dt, parse_dt
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import (bad, opt_enum, pagination, query_dt, query_str, raw_body, req_dt,
                   req_enum, req_int, req_str, soft_body)
from store import store, touch
from views import view

bp = Blueprint("pilot", __name__)

OPERATOR_CATEGORIES = ("RECREATIONAL", "COMMERCIAL")
TEST_CODES = ("TRUST_RECREATIONAL", "PART107_COMMERCIAL")
CURRENCY_BASES = ("RECREATIONAL_BASIS", "COMMERCIAL_BASIS")
CLOCK_ROLES = ("ComplianceOfficer", "AirspaceAuthority", "SafetyReviewer",
               "WaiverApprover", "InvestigationOfficer")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(CLOCK_ROLES)
    body = raw_body()
    target = req_dt(body, "to_iso8601")
    previous = clock.set(target)
    return ok({"current_utc": fmt_dt(clock.now()), "previous_utc": fmt_dt(previous)})


# ---------------------------------------------------------------------------
# pilots
# ---------------------------------------------------------------------------

@bp.post("/pilots")
def create_pilot():
    authenticate(("ComplianceOfficer",))
    body = raw_body()
    full_name = req_str(body, "full_name", max_len=120)
    email = req_str(body, "email", max_len=254)
    if "@" not in email:
        raise bad("email must contain '@'")
    operator_category = req_enum(body, "operator_category", OPERATOR_CATEGORIES)
    for other in store.all("pilots"):
        if other["email"].lower() == email.lower():
            raise ApiError("ERR_DUPLICATE_PILOT_EMAIL")
    pilot = store.insert("pilots", {
        "full_name": full_name,
        "email": email,
        "operator_category": operator_category,
        "status": "UNCERTIFIED",
        "certified_at": None,
        "currency_expires_at": None,
        "currency_basis": "RECREATIONAL_BASIS"
        if operator_category == "RECREATIONAL" else "COMMERCIAL_BASIS",
        "last_completed_flight_end": None,
        "knowledge_attempt_count": 0,
        "risk_score": 0,
        "open_waiver_count": 0,
        "suspension_reason": None,
    })
    return ok(view(pilot), 201)


@bp.get("/pilots/<pilot_id>")
def read_pilot(pilot_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "SafetyReviewer", "WaiverApprover", "InvestigationOfficer"))
    check_owns(caller, find("pilots", pilot_id))
    pilot = must_exist("pilots", pilot_id)
    return ok(view(pilot))


@bp.get("/pilots")
def list_pilots():
    caller = authenticate(("ComplianceOfficer", "AirspaceAuthority", "SafetyReviewer",
                           "WaiverApprover", "InvestigationOfficer"))
    filters = string_filters("status", "operator_category")
    return collection_response(caller, "pilots", filters=filters, descending=True)


@bp.post("/pilots/<pilot_id>/suspend")
def suspend_pilot_route(pilot_id):
    authenticate(("ComplianceOfficer",))
    pilot = must_exist("pilots", pilot_id)
    body = raw_body()
    reason = req_str(body, "suspension_reason", max_len=500)
    if pilot["status"] not in ("CERTIFIED", "LAPSED"):
        raise ApiError("ERR_PILOT_INVALID_STATE")
    cascades.suspend_pilot(pilot, reason)
    return ok(view(pilot))


@bp.post("/pilots/<pilot_id>/reinstate")
def reinstate_pilot(pilot_id):
    authenticate(("ComplianceOfficer",))
    pilot = must_exist("pilots", pilot_id)
    if pilot["status"] != "SUSPENDED":
        raise ApiError("ERR_PILOT_INVALID_STATE")
    flight_ids = {f["id"] for f in store.all("flights") if f["pilot_id"] == pilot["id"]}
    for report in store.all("reports"):
        if report["flight_id"] in flight_ids \
                and report["status"] not in ("CLOSED", "WITHDRAWN"):
            raise ApiError("ERR_PILOT_INVALID_STATE",
                           "an open accident report blocks reinstatement")
    projected, _, _, _ = calc.currency_projection(pilot)
    if projected is None or projected <= clock.now():
        raise ApiError("ERR_PILOT_INVALID_STATE", "currency has lapsed")
    pilot["status"] = "CERTIFIED"
    pilot["suspension_reason"] = None
    calc.recompute_risk_score(pilot)
    touch(pilot)
    return ok(view(pilot))


@bp.post("/pilots/<pilot_id>/revoke")
def revoke_pilot_route(pilot_id):
    authenticate(("ComplianceOfficer",))
    pilot = must_exist("pilots", pilot_id)
    body = raw_body()
    reason = req_str(body, "suspension_reason", max_len=500)
    if pilot["status"] != "SUSPENDED":
        raise ApiError("ERR_PILOT_INVALID_STATE")
    cascades.revoke_pilot(pilot, reason)
    return ok(view(pilot))


@bp.post("/pilots/<pilot_id>/currency-review")
def currency_review(pilot_id):
    authenticate(("ComplianceOfficer",))
    pilot = must_exist("pilots", pilot_id)
    if pilot["status"] not in ("CERTIFIED", "LAPSED"):
        raise ApiError("ERR_PILOT_INVALID_STATE")
    projected = calc.write_currency(pilot)
    lapsed = projected is None or projected <= clock.now()
    if pilot["status"] == "CERTIFIED" and lapsed:
        pilot["status"] = "LAPSED"
    elif pilot["status"] == "LAPSED" and not lapsed:
        pilot["status"] = "CERTIFIED"
    for cert in store.all("certifications"):
        if cert["pilot_id"] != pilot["id"] or cert["status"] != "ACTIVE":
            continue
        if cert["expires_at"] <= clock.now():
            cert["status"] = "EXPIRED"
            touch(cert)
    calc.recompute_risk_score(pilot)
    touch(pilot)
    cascades.maybe_auto_suspend(pilot)
    return ok(view(pilot))


@bp.get("/pilots/<pilot_id>/currency-projection")
def currency_projection_route(pilot_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    check_owns(caller, find("pilots", pilot_id))
    pilot = must_exist("pilots", pilot_id)
    basis = query_str("basis")
    if basis is not None and basis not in CURRENCY_BASES:
        raise bad("basis must be one of %s" % ", ".join(CURRENCY_BASES))
    projected, basis_applied, base_expiry, recency_expiry = \
        calc.currency_projection(pilot, basis)
    if projected is None:
        days_remaining = 0
        lapse_due = True
    else:
        delta = projected - clock.now()
        days_remaining = int(delta.total_seconds() // 86400) \
            if delta.total_seconds() >= 0 else -int((-delta).total_seconds() // 86400)
        lapse_due = projected <= clock.now()
    return ok({
        "pilot_id": pilot["id"],
        "projected_expires_at": fmt_dt(projected),
        "basis_applied": basis_applied,
        "base_expiry": fmt_dt(base_expiry),
        "recency_expiry": fmt_dt(recency_expiry),
        "days_remaining": days_remaining,
        "lapse_due": lapse_due,
    })


@bp.get("/pilots/<pilot_id>/flight-summary")
def flight_summary_route(pilot_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "InvestigationOfficer"))
    check_owns(caller, find("pilots", pilot_id))
    pilot = must_exist("pilots", pilot_id)
    window_start = query_dt("window_start") or pilot["created_at"]
    window_end = query_dt("window_end") or clock.now()
    summary = calc.flight_summary(pilot, window_start, window_end)
    summary["pilot_id"] = pilot["id"]
    summary["window_start"] = fmt_dt(window_start)
    summary["window_end"] = fmt_dt(window_end)
    return ok(summary)


# ---------------------------------------------------------------------------
# knowledge tests
# ---------------------------------------------------------------------------

@bp.post("/pilots/<pilot_id>/knowledge-tests")
def schedule_knowledge_test(pilot_id):
    authenticate(("ComplianceOfficer",))
    pilot = must_exist("pilots", pilot_id)
    body = raw_body()
    test_code = req_enum(body, "test_code", TEST_CODES)
    scheduled_at = req_dt(body, "scheduled_at")
    if pilot["status"] not in ("UNCERTIFIED", "LAPSED"):
        raise ApiError("ERR_PILOT_INVALID_STATE")
    expected_code = "TRUST_RECREATIONAL" \
        if pilot["operator_category"] == "RECREATIONAL" else "PART107_COMMERCIAL"
    if test_code != expected_code:
        raise ApiError("ERR_RECREATIONAL_OPERATION_FORBIDDEN",
                       "a %s operator may sit only %s"
                       % (pilot["operator_category"], expected_code))
    window_open = add_days(clock.now(), -365)
    recent = 0
    existing = 0
    for test in store.all("knowledge_tests"):
        if test["pilot_id"] != pilot["id"]:
            continue
        existing += 1
        if window_open <= test["scheduled_at"] <= clock.now():
            recent += 1
    if recent >= 3:
        raise ApiError("ERR_TEST_ATTEMPT_LIMIT")
    test = store.insert("knowledge_tests", {
        "pilot_id": pilot["id"],
        "test_code": test_code,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "attempt_number": existing + 1,
        "raw_score": None,
        "passed": None,
        "graded_at": None,
    })
    pilot["status"] = "KNOWLEDGE_PENDING"
    touch(pilot)
    return ok(view(test), 201)


@bp.get("/knowledge-tests/<test_id>")
def read_knowledge_test(test_id):
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_owns(caller, find("knowledge_tests", test_id))
    test = must_exist("knowledge_tests", test_id)
    return ok(view(test))


@bp.get("/knowledge-tests")
def list_knowledge_tests():
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    filters = string_filters("pilot_id", "status")
    return collection_response(caller, "knowledge_tests", filters=filters)


@bp.post("/knowledge-tests/<test_id>/grade")
def grade_knowledge_test(test_id):
    authenticate(("ComplianceOfficer",))
    test = must_exist("knowledge_tests", test_id)
    body = raw_body()
    raw_score = req_int(body, "raw_score", minimum=0, maximum=100)
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_ALREADY_GRADED")
    pilot = store.get("pilots", test["pilot_id"])
    passed = calc.test_passed(test["test_code"], raw_score)
    test["raw_score"] = raw_score
    test["passed"] = passed
    test["graded_at"] = clock.now()
    test["status"] = "PASSED" if passed else "FAILED"
    touch(test)
    if passed:
        issue_certificate(pilot, test)
    else:
        if pilot["status"] == "KNOWLEDGE_PENDING":
            pilot["status"] = "UNCERTIFIED"
        calc.recompute_knowledge_attempt_count(pilot)
        touch(pilot)
    return ok(view(test))


def issue_certificate(pilot, test):
    """PRD 3.1: a passing grade mints a certificate and re-certifies the pilot."""
    previous = calc.active_certification(pilot)
    issued_at = clock.now()
    cert = store.insert("certifications", {
        "pilot_id": pilot["id"],
        "originating_test_id": test["id"],
        "supersedes_certification_id": previous["id"] if previous else None,
        "certificate_number": store.next_certificate_number(),
        "category": pilot["operator_category"],
        "issued_at": issued_at,
        "expires_at": calc.certificate_expiry(issued_at),
        "status": "ACTIVE",
    })
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        touch(previous)
    if pilot["status"] == "KNOWLEDGE_PENDING":
        pilot["status"] = "CERTIFIED"
    pilot["certified_at"] = issued_at
    calc.write_currency(pilot)
    calc.recompute_knowledge_attempt_count(pilot)
    touch(pilot)
    return cert


# ---------------------------------------------------------------------------
# certifications
# ---------------------------------------------------------------------------

@bp.get("/certifications/<cert_id>")
def read_certification(cert_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    check_owns(caller, find("certifications", cert_id))
    cert = must_exist("certifications", cert_id)
    return ok(view(cert))


@bp.get("/certifications")
def list_certifications():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    filters = string_filters("pilot_id", "originating_test_id",
                             "supersedes_certification_id", "status")
    return collection_response(caller, "certifications", filters=filters)
