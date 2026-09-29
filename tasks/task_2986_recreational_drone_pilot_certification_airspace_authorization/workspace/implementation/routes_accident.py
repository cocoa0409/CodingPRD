"""Accident reports, investigation and settlement (PRD 3.8)."""

from flask import Blueprint

import calc
import cascades
from auth import authenticate, check_owns
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import (opt_str, raw_body, req_dt, req_enum, req_int, req_object_list,
                   req_str, soft_body)
from store import store, touch
from views import view

bp = Blueprint("accident", __name__)

INJURY_LEVELS = ("NONE", "MINOR", "SERIOUS")
BLOCKING_REPORT_STATUSES = ("FILED", "INVESTIGATING", "REMEDIATION_REQUIRED", "CLOSED")
READ_ROLES = ("Pilot", "ComplianceOfficer", "InvestigationOfficer")


def report_pilot(report):
    flight = store.get("flights", report["flight_id"])
    return store.get("pilots", flight["pilot_id"]) if flight is not None else None


def settle_ledger(report, direction):
    """Recompute the covering policy's ledger after a filing, closure or withdrawal."""
    policy = store.get("policies", report.get("policy_id"))
    if policy is None:
        return
    cascades.apply_policy_ledger(policy, direction)


def refresh_pilot_risk(report):
    pilot = report_pilot(report)
    if pilot is None:
        return
    calc.recompute_risk_score(pilot)
    touch(pilot)
    cascades.maybe_auto_suspend(pilot)


@bp.post("/accident-reports")
def file_report():
    caller = authenticate(("Pilot", "InvestigationOfficer"))
    early = soft_body()
    if isinstance(early.get("flight_id"), str):
        check_owns(caller, find("flights", early["flight_id"]))
    body = raw_body()
    flight_id = req_str(body, "flight_id")
    occurred_at = req_dt(body, "occurred_at")
    injury_level = req_enum(body, "injury_level", INJURY_LEVELS)
    damage_cents = req_int(body, "reported_property_damage_cents", minimum=0)
    narrative = req_str(body, "narrative", max_len=2000)
    flight = must_exist("flights", flight_id)
    if flight["status"] not in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        raise ApiError("ERR_FLIGHT_INVALID_STATE")
    for other in store.all("reports"):
        if other["flight_id"] == flight["id"] \
                and other["status"] in BLOCKING_REPORT_STATUSES:
            raise ApiError("ERR_ACCIDENT_REPORT_DUPLICATE")
    policy = store.get("policies", flight.get("covering_policy_id"))
    report = store.insert("reports", {
        "flight_id": flight["id"],
        # The policy is copied at filing so later reselection cannot move cover.
        "policy_id": policy["id"] if policy else None,
        "occurred_at": occurred_at,
        "injury_level": injury_level,
        "reported_property_damage_cents": damage_cents,
        "narrative": narrative,
        "status": "FILED",
        "remediation_round": 0,
        "remediation_findings": None,
        "damage_line_items": None,
        "reserved_cents": 0,
        "settlement_cents": None,
        "probable_cause": None,
        "closed_by_user_id": None,
    })
    report["reserved_cents"] = calc.reserve_for(report, policy)
    flight["investigation_status"] = "OPEN"
    touch(flight)
    settle_ledger(report, "erode")
    refresh_pilot_risk(report)
    return ok(view(report), 201)


@bp.get("/accident-reports/<report_id>")
def read_report(report_id):
    caller = authenticate(READ_ROLES)
    check_owns(caller, find("reports", report_id))
    report = must_exist("reports", report_id)
    return ok(view(report))


@bp.get("/accident-reports")
def list_reports():
    caller = authenticate(READ_ROLES)
    filters = string_filters("flight_id", "policy_id", "status")
    return collection_response(caller, "reports", filters=filters)


@bp.post("/accident-reports/<report_id>/open-investigation")
def open_investigation(report_id):
    authenticate(("InvestigationOfficer",))
    report = must_exist("reports", report_id)
    if report["status"] != "FILED":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    # The reserve is untouched: it was taken at filing.
    report["status"] = "INVESTIGATING"
    touch(report)
    return ok(view(report))


@bp.post("/accident-reports/<report_id>/require-remediation")
def require_remediation(report_id):
    authenticate(("InvestigationOfficer",))
    report = must_exist("reports", report_id)
    body = raw_body()
    findings = req_str(body, "remediation_findings", max_len=2000)
    if report["status"] != "INVESTIGATING":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if report["remediation_round"] >= 2:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
    report["status"] = "REMEDIATION_REQUIRED"
    report["remediation_findings"] = findings
    report["remediation_round"] = report["remediation_round"] + 1
    touch(report)
    return ok(view(report))


@bp.post("/accident-reports/<report_id>/resume-investigation")
def resume_investigation(report_id):
    authenticate(("InvestigationOfficer",))
    report = must_exist("reports", report_id)
    if report["status"] != "REMEDIATION_REQUIRED":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    report["status"] = "INVESTIGATING"
    touch(report)
    return ok(view(report))


@bp.post("/accident-reports/<report_id>/close")
def close_report(report_id):
    caller = authenticate(("InvestigationOfficer",))
    candidate = find("reports", report_id)
    if candidate is not None:
        # Rung 5: the officer who granted the airspace may not sign off the
        # accident that happened in it.
        flight = store.get("flights", candidate["flight_id"])
        authorization = store.get("authorizations", flight.get("authorization_id")) \
            if flight is not None else None
        if authorization is not None \
                and authorization.get("approved_by_user_id") == caller.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the approving authority may not close this report")
    report = must_exist("reports", report_id)
    body = raw_body()
    line_items = req_object_list(body, "damage_line_items")
    cleaned = []
    for item in line_items:
        label = req_str(item, "label", max_len=200)
        amount = req_int(item, "amount_cents", minimum=0)
        cleaned.append({"label": label, "amount_cents": amount})
    probable_cause = req_str(body, "probable_cause", max_len=2000)
    if report["status"] != "INVESTIGATING":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    policy = store.get("policies", report.get("policy_id"))
    report["settlement_cents"] = calc.settlement_for(report, policy, cleaned)
    report["damage_line_items"] = cleaned
    report["probable_cause"] = probable_cause
    report["closed_by_user_id"] = caller.user_id
    report["reserved_cents"] = 0
    report["status"] = "CLOSED"
    touch(report)
    settle_ledger(report, "restore")
    flight = store.get("flights", report["flight_id"])
    if flight is not None:
        flight["investigation_status"] = "CLOSED"
        touch(flight)
    refresh_pilot_risk(report)
    return ok(view(report))


@bp.post("/accident-reports/<report_id>/withdraw")
def withdraw_report(report_id):
    authenticate(("InvestigationOfficer",))
    report = must_exist("reports", report_id)
    body = raw_body()
    probable_cause = opt_str(body, "probable_cause", max_len=2000)
    if report["status"] not in ("FILED", "INVESTIGATING"):
        raise ApiError("ERR_REPORT_INVALID_STATE")
    report["status"] = "WITHDRAWN"
    report["reserved_cents"] = 0
    report["settlement_cents"] = None
    if probable_cause is not None:
        report["probable_cause"] = probable_cause
    touch(report)
    settle_ledger(report, "restore")
    flight = store.get("flights", report["flight_id"])
    if flight is not None:
        flight["investigation_status"] = "CLOSED"
        touch(flight)
    refresh_pilot_risk(report)
    return ok(view(report))
