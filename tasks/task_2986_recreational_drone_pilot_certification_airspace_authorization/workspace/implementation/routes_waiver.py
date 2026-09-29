"""Special-operation waivers and the safety-case review loop (PRD 3.5)."""

from flask import Blueprint

import calc
from auth import authenticate, check_body_owner, check_owns
from clockmod import add_days, clock
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import (bad, opt_str, raw_body, req_enum, req_int, req_str, soft_body)
from store import store, touch
from views import view

bp = Blueprint("waiver", __name__)

WAIVER_TYPES = ("OVER_PEOPLE", "NIGHT", "BVLOS")
AIR_RISK_CLASSES = ("ARC_A", "ARC_B", "ARC_C", "ARC_D")
WAIVER_VALIDITY_DAYS = 180


def refresh_open_waiver_count(pilot, force=False):
    """Recompute the pilot's open_waiver_count after a waiver status change."""
    before = pilot["open_waiver_count"]
    calc.recompute_open_waiver_count(pilot)
    if force or pilot["open_waiver_count"] != before:
        touch(pilot)


def safety_cases_of(waiver):
    return [c for c in store.all("safety_cases") if c["waiver_id"] == waiver["id"]]


@bp.post("/waivers")
def create_waiver():
    caller = authenticate(("Pilot",))
    check_body_owner(caller, soft_body())
    body = raw_body()
    pilot_id = req_str(body, "pilot_id")
    aircraft_id = req_str(body, "aircraft_id")
    waiver_type = req_enum(body, "waiver_type", WAIVER_TYPES)
    requested_ceiling_ft = req_int(body, "requested_ceiling_ft", minimum=1, maximum=2000)
    operation_description = req_str(body, "operation_description", max_len=500)
    expected_pilot_version = req_int(body, "expected_pilot_version")
    pilot = must_exist("pilots", pilot_id)
    aircraft = must_exist("aircraft", aircraft_id)
    if aircraft["owner_pilot_id"] != pilot["id"]:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "airframe belongs to another pilot")
    if pilot["version"] != expected_pilot_version:
        raise ApiError("ERR_STALE_PILOT_VERSION")
    if pilot["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    waiver = store.insert("waivers", {
        "pilot_id": pilot["id"],
        "aircraft_id": aircraft["id"],
        "waiver_type": waiver_type,
        "requested_ceiling_ft": requested_ceiling_ft,
        "operation_description": operation_description,
        "status": "DRAFT",
        "revision_round": 0,
        "granted_ceiling_ft": None,
        "valid_until": None,
        "approved_by_user_id": None,
        "denial_reason": None,
    })
    for other in store.all("waivers"):
        if other["id"] == waiver["id"] or other["pilot_id"] != pilot["id"]:
            continue
        if other["waiver_type"] == waiver_type and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)
    refresh_open_waiver_count(pilot, force=True)
    return ok(view(waiver), 201)


@bp.get("/waivers/<waiver_id>")
def read_waiver(waiver_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "SafetyReviewer",
                           "WaiverApprover", "AirspaceAuthority"))
    check_owns(caller, find("waivers", waiver_id))
    waiver = must_exist("waivers", waiver_id)
    return ok(view(waiver))


@bp.get("/waivers")
def list_waivers():
    caller = authenticate(("Pilot", "ComplianceOfficer", "SafetyReviewer",
                           "WaiverApprover", "AirspaceAuthority"))
    filters = string_filters("pilot_id", "aircraft_id", "waiver_type", "status")
    return collection_response(caller, "waivers", filters=filters)


# ---------------------------------------------------------------------------
# safety cases
# ---------------------------------------------------------------------------

@bp.post("/waivers/<waiver_id>/safety-cases")
def attach_safety_case(waiver_id):
    caller = authenticate(("Pilot",))
    check_owns(caller, find("waivers", waiver_id))
    waiver = must_exist("waivers", waiver_id)
    body = raw_body()
    mitigation_summary = req_str(body, "mitigation_summary", max_len=1000)
    ground_risk_class = req_int(body, "ground_risk_class", minimum=1, maximum=4)
    air_risk_class = req_enum(body, "air_risk_class", AIR_RISK_CLASSES)
    contingency_procedures = req_str(body, "contingency_procedures", max_len=1000)
    if waiver["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    case = store.insert("safety_cases", {
        "waiver_id": waiver["id"],
        "mitigation_summary": mitigation_summary,
        "ground_risk_class": ground_risk_class,
        "air_risk_class": air_risk_class,
        "contingency_procedures": contingency_procedures,
        "sail_level": calc.sail_level(ground_risk_class, air_risk_class,
                                      waiver["waiver_type"]),
        "review_status": "PENDING",
        "reviewer_findings": None,
        "cleared_by_user_id": None,
    })
    return ok(view(case), 201)


@bp.get("/safety-cases/<case_id>")
def read_safety_case(case_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "SafetyReviewer",
                           "WaiverApprover"))
    check_owns(caller, find("safety_cases", case_id))
    case = must_exist("safety_cases", case_id)
    return ok(view(case))


@bp.get("/safety-cases")
def list_safety_cases():
    caller = authenticate(("Pilot", "ComplianceOfficer", "SafetyReviewer",
                           "WaiverApprover"))
    filters = string_filters("waiver_id", "review_status")
    return collection_response(caller, "safety_cases", filters=filters)


# ---------------------------------------------------------------------------
# review loop
# ---------------------------------------------------------------------------

@bp.post("/waivers/<waiver_id>/submit")
def submit_waiver(waiver_id):
    caller = authenticate(("Pilot",))
    check_owns(caller, find("waivers", waiver_id))
    waiver = must_exist("waivers", waiver_id)
    if waiver["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    pilot = store.get("pilots", waiver["pilot_id"])
    if pilot["status"] != "CERTIFIED":
        raise ApiError("ERR_PILOT_NOT_CERTIFIED")
    cases = safety_cases_of(waiver)
    if not cases:
        raise ApiError("ERR_SAFETY_CASE_MISSING")
    resubmission = waiver["status"] == "REVISION_REQUESTED"
    waiver["status"] = "SUBMITTED"
    touch(waiver)
    if resubmission:
        for case in cases:
            if case["review_status"] == "REVISION_REQUESTED":
                case["review_status"] = "PENDING"
                case["reviewer_findings"] = None
                touch(case)
    refresh_open_waiver_count(pilot)
    return ok(view(waiver))


@bp.post("/waivers/<waiver_id>/begin-review")
def begin_waiver_review(waiver_id):
    authenticate(("SafetyReviewer",))
    waiver = must_exist("waivers", waiver_id)
    if waiver["status"] != "SUBMITTED":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    waiver["status"] = "UNDER_REVIEW"
    touch(waiver)
    refresh_open_waiver_count(store.get("pilots", waiver["pilot_id"]))
    return ok(view(waiver))


@bp.post("/waivers/<waiver_id>/request-revision")
def request_waiver_revision(waiver_id):
    authenticate(("SafetyReviewer",))
    waiver = must_exist("waivers", waiver_id)
    body = raw_body()
    findings = req_str(body, "reviewer_findings", max_len=1000)
    if waiver["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    if waiver["revision_round"] >= 2:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
    waiver["status"] = "REVISION_REQUESTED"
    waiver["revision_round"] = waiver["revision_round"] + 1
    touch(waiver)
    for case in safety_cases_of(waiver):
        if case["review_status"] == "PENDING":
            case["review_status"] = "REVISION_REQUESTED"
            case["reviewer_findings"] = findings
            touch(case)
    refresh_open_waiver_count(store.get("pilots", waiver["pilot_id"]))
    return ok(view(waiver))


@bp.post("/waivers/<waiver_id>/clear-safety-case")
def clear_safety_case(waiver_id):
    caller = authenticate(("SafetyReviewer",))
    waiver = must_exist("waivers", waiver_id)
    body = raw_body()
    findings = opt_str(body, "reviewer_findings", max_len=1000)
    if waiver["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    cases = safety_cases_of(waiver)
    for case in cases:
        if case["sail_level"] > calc.MAX_APPROVABLE_SAIL:
            raise ApiError("ERR_SAIL_LEVEL_UNACCEPTABLE")
    waiver["status"] = "CLEARED"
    touch(waiver)
    for case in cases:
        if case["review_status"] == "PENDING":
            case["review_status"] = "CLEARED"
            case["cleared_by_user_id"] = caller.user_id
            if findings is not None:
                case["reviewer_findings"] = findings
            touch(case)
    refresh_open_waiver_count(store.get("pilots", waiver["pilot_id"]))
    return ok(view(waiver))


@bp.post("/waivers/<waiver_id>/decide")
def decide_waiver(waiver_id):
    caller = authenticate(("WaiverApprover",))
    candidate = find("waivers", waiver_id)
    if candidate is not None:
        for case in safety_cases_of(candidate):
            if case.get("cleared_by_user_id") == caller.user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "the clearing reviewer may not decide the waiver")
    waiver = must_exist("waivers", waiver_id)
    body = raw_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    granted_ceiling_ft = None
    denial_reason = None
    if decision == "APPROVE":
        granted_ceiling_ft = req_int(body, "granted_ceiling_ft", minimum=1)
        if granted_ceiling_ft > waiver["requested_ceiling_ft"]:
            raise bad("granted_ceiling_ft may not exceed requested_ceiling_ft")
    else:
        denial_reason = req_str(body, "denial_reason", max_len=500)
    if waiver["status"] != "CLEARED":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    if decision == "APPROVE":
        waiver["status"] = "APPROVED"
        waiver["granted_ceiling_ft"] = granted_ceiling_ft
        waiver["approved_by_user_id"] = caller.user_id
        waiver["valid_until"] = add_days(clock.now(), WAIVER_VALIDITY_DAYS)
    else:
        waiver["status"] = "DENIED"
        waiver["denial_reason"] = denial_reason
    touch(waiver)
    refresh_open_waiver_count(store.get("pilots", waiver["pilot_id"]), force=True)
    return ok(view(waiver))
