"""Underwriting agreements: the parallel status/airplay dimensions and §3.8 rules."""
from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, ack_violation, bad_request, invalid_state, not_found
from core.middleware import check_station_ownership, route
from core.response import array_response, object_response
from core.store import STORE
from services import scoring

bp = Blueprint("underwriting", __name__)

AGREEMENT_STATUSES = [
    "SUBMITTED", "COMPLIANCE_REVIEW", "APPROVED", "SCHEDULED", "AIRING",
    "AIRING_COMPLETE", "REJECTED", "NO_AIRED",
]
AIRPLAY_STATUSES = [
    "NOT_SCHEDULED", "SLOTTED", "PARTIALLY_AIRED", "FULLY_AIRED", "AIRING_BLOCKED",
]
TERMINAL_STATUSES = ("AIRING_COMPLETE", "REJECTED", "NO_AIRED")


def agreement_or_404(agreement_id):
    agreement = STORE.underwriting.get(agreement_id)
    if agreement is None:
        raise not_found("underwriting agreement")
    return agreement


def _station_or_404(station_id):
    station = STORE.member_stations.get(station_id)
    if station is None:
        raise not_found("member station")
    return station


def _freeze_guard(station):
    if station is not None and station.get("_underwriting_freeze"):
        raise ApiError("ERR_TRANSMISSION_FREEZE")


@bp.route("/network/underwriting-agreements", methods=["POST"])
@route("/network/underwriting-agreements", "POST")
def create_underwriting():
    body = base.get_body(request.get_json(silent=True))
    sponsor = base.as_text(body.get("sponsor_name"), "sponsor_name")
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    station = _station_or_404(station_id)
    if station.get("eligibility_status") in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError("ERR_STATION_SUSPENDED")
    _freeze_guard(station)
    program_code = base.as_text(body.get("program_code"), "program_code")
    script = base.as_text(body.get("ack_script_text"), "ack_script_text", required=False)
    script = "" if script is None else script
    consideration = base.as_cents(
        body.get("consideration_cents"), "consideration_cents", strictly_positive=True
    )
    segments = base.as_int(
        body.get("compliance_segment_count"), "compliance_segment_count", low=1, required=False
    )
    segments = 1 if segments is None else segments
    agreement = new_record(
        "UnderwritingAgreement",
        sponsor_name=sponsor,
        station_id=station_id,
        program_code=program_code,
        ack_script_text=script,
        consideration_cents=consideration,
        agreement_status="SUBMITTED",
        airplay_status="NOT_SCHEDULED",
        compliance_segment_count=segments,
        aired_segment_count=0,
        disclosure_test_passed=scoring.acknowledgment_passes(script),
    )
    STORE.put("underwriting", agreement)
    return object_response(public(agreement), 201)


@bp.route("/network/underwriting-agreements", methods=["GET"])
@route("/network/underwriting-agreements", "GET")
def list_underwriting():
    args = request.args
    recs = STORE.all("underwriting")
    for field in ("station_id", "program_code", "agreement_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/underwriting-agreements/<uid>", methods=["GET"])
@route("/network/underwriting-agreements/<uid>", "GET")
def read_underwriting(uid):
    return object_response(public(agreement_or_404(uid)))


@bp.route("/network/underwriting-agreements/<uid>/submit-for-review", methods=["POST"])
@route("/network/underwriting-agreements/<uid>/submit-for-review", "POST")
def submit_for_review(uid):
    agreement = agreement_or_404(uid)
    if agreement.get("agreement_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "SUBMITTED":
        raise invalid_state("the agreement is not in submitted status")
    if int(agreement.get("consideration_cents") or 0) <= 0:
        raise invalid_state("the consideration must be strictly positive")
    station = STORE.member_stations.get(agreement.get("station_id"))
    _freeze_guard(station)
    violation = scoring.acknowledgment_violation(agreement.get("ack_script_text"))
    agreement["disclosure_test_passed"] = violation is None
    if violation is not None:
        raise ack_violation(violation)
    agreement["agreement_status"] = "COMPLIANCE_REVIEW"
    touch(agreement)
    return object_response(public(agreement))


@bp.route("/network/underwriting-agreements/<uid>/approve", methods=["POST"])
@route("/network/underwriting-agreements/<uid>/approve", "POST")
def approve_underwriting(uid):
    agreement = agreement_or_404(uid)
    if agreement.get("agreement_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "COMPLIANCE_REVIEW":
        raise invalid_state("the agreement is not under compliance review")
    violation = scoring.acknowledgment_violation(agreement.get("ack_script_text"))
    agreement["disclosure_test_passed"] = violation is None
    if violation is not None:
        raise ack_violation(violation)
    if agreement.get("airplay_status") != "NOT_SCHEDULED":
        raise invalid_state("the airplay dimension has already advanced")
    agreement["agreement_status"] = "APPROVED"
    touch(agreement)
    return object_response(public(agreement))


@bp.route("/network/underwriting-agreements/<uid>/reject", methods=["POST"])
@route("/network/underwriting-agreements/<uid>/reject", "POST")
def reject_underwriting(uid):
    agreement = agreement_or_404(uid)
    if agreement.get("agreement_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "COMPLIANCE_REVIEW":
        raise invalid_state("the agreement is not under compliance review")
    body = base.get_body(request.get_json(silent=True))
    base.as_text(body.get("rejection_reason"), "rejection_reason")
    agreement["disclosure_test_passed"] = False
    agreement["agreement_status"] = "REJECTED"
    agreement["rejection_reason"] = body.get("rejection_reason")
    touch(agreement)
    return object_response(public(agreement))


@bp.route("/network/underwriting-agreements/<uid>/schedule", methods=["POST"])
@route("/network/underwriting-agreements/<uid>/schedule", "POST")
def schedule_underwriting(uid):
    agreement = agreement_or_404(uid)
    if agreement.get("agreement_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "APPROVED":
        raise invalid_state("the agreement is not approved")
    station = STORE.member_stations.get(agreement.get("station_id"))
    _freeze_guard(station)
    if agreement.get("airplay_status") != "NOT_SCHEDULED":
        raise invalid_state("the airplay dimension is not unscheduled")
    agreement["agreement_status"] = "SCHEDULED"
    agreement["airplay_status"] = "SLOTTED"
    touch(agreement)
    return object_response(public(agreement))


@bp.route("/network/underwriting-agreements/<uid>/air-segment", methods=["POST"])
@route("/network/underwriting-agreements/<uid>/air-segment", "POST")
def air_segment(uid):
    agreement = agreement_or_404(uid)
    status = agreement.get("agreement_status")
    if status in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    aired = int(agreement.get("aired_segment_count") or 0)
    required = int(agreement.get("compliance_segment_count") or 1)
    if aired >= required:
        raise ApiError("ERR_SEGMENT_COUNT_EXCEEDED")
    if status == "SCHEDULED":
        pass
    elif status == "AIRING":
        if aired <= 0:
            raise invalid_state("no segment has aired yet")
    else:
        raise invalid_state("the agreement cannot air a segment from its current state")
    agreement["aired_segment_count"] = aired + 1
    if agreement["aired_segment_count"] >= required:
        agreement["airplay_status"] = "FULLY_AIRED"
        agreement["agreement_status"] = "AIRING_COMPLETE"
    else:
        agreement["agreement_status"] = "AIRING"
        agreement["airplay_status"] = "PARTIALLY_AIRED"
    touch(agreement)
    return object_response(public(agreement))