"""Content contributions: filing, revision rounds, licensing and the ledger hops."""
from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import check_station_ownership, route
from core.response import array_response, object_response
from core.store import STORE
from services import content, governance

bp = Blueprint("contributions", __name__)

EDITOR_STATUSES = ("SUBMITTED", "SHORTLISTED")
TERMINAL_STATUSES = ("WITHDRAWN", "REJECTED")


def contribution_or_404(contribution_id):
    contribution = STORE.contributions.get(contribution_id)
    if contribution is None:
        raise not_found("content contribution")
    return contribution


def _program_or_404(program_id):
    program = STORE.programs.get(program_id)
    if program is None:
        raise not_found("national program")
    return program


def _station_or_404(station_id):
    station = STORE.member_stations.get(station_id)
    if station is None:
        raise not_found("member station")
    return station


@bp.route("/network/content-contributions", methods=["POST"])
@route("/network/content-contributions", "POST")
def create_contribution():
    body = base.get_body(request.get_json(silent=True))
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    station = _station_or_404(station_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station_id)
    program_id = body.get("program_id")
    if program_id is None:
        raise bad_request("program_id is required")
    _program_or_404(program_id)
    headline = base.as_text(body.get("headline"), "headline")
    duration = base.as_int(body.get("duration_seconds"), "duration_seconds", low=1)
    if station.get("eligibility_status") not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_CONTRIBUTION_STATION_INELIGIBLE")
    contribution = new_record(
        "ContentContribution",
        station_id=station_id,
        program_id=program_id,
        headline=headline,
        duration_seconds=duration,
        contribution_status="DRAFT",
        last_request_at=None,
        revision_count=0,
        compensation_credit_cents=0,
        _ever_shortlisted=False,
    )
    STORE.put("contributions", contribution)
    content.recompute_compensation(STORE, contribution)
    return object_response(public(contribution), 201)


@bp.route("/network/content-contributions", methods=["GET"])
@route("/network/content-contributions", "GET")
def list_contributions():
    args = request.args
    recs = STORE.all("contributions")
    for field in ("station_id", "program_id", "contribution_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/content-contributions/<cid>", methods=["GET"])
@route("/network/content-contributions/<cid>", "GET")
def read_contribution(cid):
    return object_response(public(contribution_or_404(cid)))


@bp.route("/network/content-contributions/<cid>/submit", methods=["POST"])
@route("/network/content-contributions/<cid>/submit", "POST")
def submit_contribution(cid):
    contribution = contribution_or_404(cid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, contribution.get("station_id"))
    if contribution.get("contribution_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contribution.get("contribution_status") != "DRAFT":
        raise invalid_state("the contribution is not a draft")
    if int(contribution.get("duration_seconds") or 0) < 1:
        raise invalid_state("the contribution has no runtime")
    returned = contribution.get("last_request_at") is not None
    contribution["last_request_at"] = None
    if returned:
        contribution["revision_count"] = int(contribution.get("revision_count") or 0) + 1
    contribution["contribution_status"] = "SUBMITTED"
    content.recompute_compensation(STORE, contribution)
    touch(contribution)
    return object_response(public(contribution))


@bp.route("/network/content-contributions/<cid>/shortlist", methods=["POST"])
@route("/network/content-contributions/<cid>/shortlist", "POST")
def shortlist_contribution(cid):
    contribution = contribution_or_404(cid)
    if contribution.get("contribution_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contribution.get("contribution_status") != "SUBMITTED":
        raise invalid_state("the contribution is not submitted")
    station = _station_or_404(contribution.get("station_id"))
    if station.get("eligibility_status") not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_CONTRIBUTION_STATION_INELIGIBLE")
    contribution["contribution_status"] = "SHORTLISTED"
    contribution["_ever_shortlisted"] = True
    content.recompute_compensation(STORE, contribution)
    touch(contribution)
    return object_response(public(contribution))


@bp.route("/network/content-contributions/<cid>/request-resubmission", methods=["POST"])
@route("/network/content-contributions/<cid>/request-resubmission", "POST")
def request_resubmission(cid):
    contribution = contribution_or_404(cid)
    if contribution.get("contribution_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contribution.get("contribution_status") != "SHORTLISTED":
        raise invalid_state("the contribution is not shortlisted")
    contribution["contribution_status"] = "DRAFT"
    contribution["last_request_at"] = C.iso(C.now())
    content.recompute_compensation(STORE, contribution)
    touch(contribution)
    return object_response(public(contribution))


@bp.route("/network/content-contributions/<cid>/license", methods=["POST"])
@route("/network/content-contributions/<cid>/license", "POST")
def license_contribution(cid):
    contribution = contribution_or_404(cid)
    if contribution.get("contribution_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contribution.get("contribution_status") != "SHORTLISTED":
        raise invalid_state("the contribution is not shortlisted")
    station = _station_or_404(contribution.get("station_id"))
    if station.get("eligibility_status") in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError("ERR_STATION_SUSPENDED")
    program = _program_or_404(contribution.get("program_id"))
    body = base.get_body(request.get_json(silent=True))
    expected = base.as_int(
        body.get("expected_program_version"), "expected_program_version", required=False
    )
    if expected is None:
        raise bad_request("expected_program_version is required")
    if expected != int(program.get("version") or 0):
        raise ApiError("ERR_STALE_PROGRAM_VERSION")
    contribution["contribution_status"] = "LICENSED"
    credit = content.recompute_compensation(STORE, contribution)
    program["licensed_contribution_count"] = int(
        program.get("licensed_contribution_count") or 0
    ) + 1
    program["preliminary_license_credit_cents"] = int(
        program.get("preliminary_license_credit_cents") or 0
    ) - credit
    station["contribution_credit_cents"] = int(
        station.get("contribution_credit_cents") or 0
    ) + credit
    content.note_credited_program(station, program["id"])
    touch(program)
    touch(station)
    governance.upsert_projection(STORE, station)
    touch(contribution)
    data = public(contribution)
    data["program_licensed_contribution_count"] = program["licensed_contribution_count"]
    data["station_contribution_credit_cents"] = station["contribution_credit_cents"]
    return object_response(data)


@bp.route("/network/content-contributions/<cid>/mark-used", methods=["POST"])
@route("/network/content-contributions/<cid>/mark-used", "POST")
def mark_used(cid):
    contribution = contribution_or_404(cid)
    if contribution.get("contribution_status") in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contribution.get("contribution_status") != "LICENSED":
        raise invalid_state("the contribution is not licensed")
    contribution["contribution_status"] = "USED"
    content.recompute_compensation(STORE, contribution)
    touch(contribution)
    return object_response(public(contribution))


@bp.route("/network/content-contributions/<cid>/reject", methods=["POST"])
@route("/network/content-contributions/<cid>/reject", "POST")
def reject_contribution(cid):
    contribution = contribution_or_404(cid)
    status = contribution.get("contribution_status")
    if status in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in EDITOR_STATUSES:
        raise invalid_state("the contribution is not submitted or shortlisted")
    body = base.get_body(request.get_json(silent=True))
    reason = base.as_text(body.get("rejection_reason"), "rejection_reason")
    contribution["contribution_status"] = "REJECTED"
    contribution["rejection_reason"] = reason
    touch(contribution)
    return object_response(public(contribution))


@bp.route("/network/content-contributions/<cid>/withdraw", methods=["POST"])
@route("/network/content-contributions/<cid>/withdraw", "POST")
def withdraw_contribution(cid):
    contribution = contribution_or_404(cid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, contribution.get("station_id"))
    status = contribution.get("contribution_status")
    if status in TERMINAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("the contribution cannot be withdrawn from its current state")
    contribution["contribution_status"] = "WITHDRAWN"
    touch(contribution)
    return object_response(public(contribution))