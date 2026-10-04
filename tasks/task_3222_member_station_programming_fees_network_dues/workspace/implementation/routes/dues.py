"""Membership drives, audience reports, dues proposals, votes and governance."""
import re

from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import check_station_ownership, route
from core.response import array_response, object_response
from core.store import STORE
from services import drives, fees, governance

bp = Blueprint("dues", __name__)

REGIONS = ["REGION_NORTHEAST", "REGION_SOUTH", "REGION_MIDWEST", "REGION_WEST"]
DRIVE_STATUSES = ["PLANNED", "ACTIVE", "CLOSED", "REPORTED", "SETTLED", "CANCELLED"]
VOTE_CHOICES = ["YES", "NO"]


def _station_or_404(station_id):
    station = STORE.member_stations.get(station_id)
    if station is None:
        raise not_found("member station")
    return station


def drive_or_404(drive_id):
    drive = STORE.drives.get(drive_id)
    if drive is None:
        raise not_found("membership drive")
    return drive


def proposal_or_404(proposal_id):
    proposal = STORE.proposals.get(proposal_id)
    if proposal is None:
        raise not_found("dues structure proposal")
    return proposal


def vote_or_404(vote_id):
    vote = STORE.votes.get(vote_id)
    if vote is None:
        raise not_found("station vote")
    return vote


def election_or_404(election_id):
    election = STORE.elections.get(election_id)
    if election is None:
        raise not_found("board election")
    return election


def candidate_or_404(candidate_id):
    candidate = STORE.candidates.get(candidate_id)
    if candidate is None:
        raise not_found("board candidate")
    return candidate


def seat_or_404(seat_id):
    seat = STORE.seats.get(seat_id)
    if seat is None:
        raise not_found("board seat")
    return seat


def projection_view(store, row):
    return public(row)


def _quorum_scope_ids(proposal):
    region = proposal.get("board_region")
    out = {}
    for station in STORE.member_stations.values():
        if region is not None and station.get("board_seat_region") != region:
            continue
        if governance.projection_eligible(station):
            out[station["id"]] = True
    return out


# --- membership drives -------------------------------------------------------
@bp.route("/network/membership-drives", methods=["POST"])
@route("/network/membership-drives", "POST")
def create_drive():
    body = base.get_body(request.get_json(silent=True))
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    _station_or_404(station_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station_id)
    name = base.as_text(body.get("drive_name"), "drive_name")
    close_at = base.as_instant(body.get("drive_close_at"), "drive_close_at")
    drive = new_record(
        "MembershipDrive",
        station_id=station_id,
        drive_name=name,
        drive_status="PLANNED",
        pledged_cents=0,
        collected_cents=0,
        collection_ratio_bps=0,
        drive_close_at=close_at,
        drive_deduction_cents=0,
        fiscal_year=body.get("fiscal_year") or C.now().year,
    )
    STORE.put("drives", drive)
    return object_response(public(drive), 201)


@bp.route("/network/membership-drives", methods=["GET"])
@route("/network/membership-drives", "GET")
def list_drives():
    args = request.args
    recs = STORE.all("drives")
    for field in ("station_id", "drive_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/membership-drives/<did>", methods=["GET"])
@route("/network/membership-drives/<did>", "GET")
def read_drive(did):
    drive = drive_or_404(did)
    drives.recompute_drive(STORE, drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/open", methods=["POST"])
@route("/network/membership-drives/<did>/open", "POST")
def open_drive(did):
    drive = drive_or_404(did)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, drive.get("station_id"))
    if drive.get("drive_status") != "PLANNED":
        raise invalid_state("the drive is not planned")
    station = _station_or_404(drive.get("station_id"))
    if station.get("eligibility_status") not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_STATION_NOT_ELIGIBLE")
    if not drives.drive_has_audience_report(
        STORE, station["id"], drive.get("fiscal_year")
    ):
        raise invalid_state(
            "the drive carries no audience report for the current fiscal year"
        )
    drive["drive_status"] = "ACTIVE"
    drive["pledged_cents"] = 0
    drive["collected_cents"] = 0
    drives.recompute_drive(STORE, drive)
    touch(drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/pledge", methods=["POST"])
@route("/network/membership-drives/<did>/pledge", "POST")
def pledge(did):
    drive = drive_or_404(did)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, drive.get("station_id"))
    if drive.get("drive_status") == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if drive.get("drive_status") != "ACTIVE":
        raise invalid_state("the drive is not active")
    body = base.get_body(request.get_json(silent=True))
    amount = base.as_cents(body.get("pledge_cents"), "pledge_cents", strictly_positive=True)
    collected = base.as_cents(body.get("collected_cents"), "collected_cents", required=False)
    collected = 0 if collected is None else collected
    drive["pledged_cents"] = int(drive.get("pledged_cents") or 0) + amount
    drive["collected_cents"] = int(drive.get("collected_cents") or 0) + collected
    drives.recompute_drive(STORE, drive)
    touch(drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/close", methods=["POST"])
@route("/network/membership-drives/<did>/close", "POST")
def close_drive(did):
    drive = drive_or_404(did)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, drive.get("station_id"))
    if drive.get("drive_status") == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if drive.get("drive_status") != "ACTIVE":
        raise invalid_state("the drive is not active")
    close_at = C.parse_dt(drive.get("drive_close_at"))
    if close_at is None or C.now() < close_at:
        raise invalid_state("the drive's close instant has not arrived")
    drive["drive_status"] = "CLOSED"
    touch(drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/report", methods=["POST"])
@route("/network/membership-drives/<did>/report", "POST")
def report_drive(did):
    drive = drive_or_404(did)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, drive.get("station_id"))
    if drive.get("drive_status") == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if drive.get("drive_status") != "CLOSED":
        raise invalid_state("the drive is not closed")
    drive["drive_status"] = "REPORTED"
    drives.recompute_drive(STORE, drive)
    touch(drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/settle", methods=["POST"])
@route("/network/membership-drives/<did>/settle", "POST")
def settle_drive(did):
    drive = drive_or_404(did)
    if drive.get("drive_status") == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if drive.get("drive_status") != "REPORTED":
        raise invalid_state("the drive is not reported")
    if int(drive.get("collection_ratio_bps") or 0) < drives.SETTLE_COLLECTION_FLOOR_BPS:
        raise invalid_state("the drive did not reach the collection floor")
    drives.settle_drive(STORE, drive)
    drive["drive_status"] = "SETTLED"
    touch(drive)
    return object_response(public(drive))


@bp.route("/network/membership-drives/<did>/cancel", methods=["POST"])
@route("/network/membership-drives/<did>/cancel", "POST")
def cancel_drive(did):
    drive = drive_or_404(did)
    if drive.get("drive_status") == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if drive.get("drive_status") not in ("PLANNED", "REPORTED"):
        raise invalid_state("the drive cannot be cancelled from its current state")
    drive["drive_status"] = "CANCELLED"
    drive["drive_deduction_cents"] = 0
    touch(drive)
    return object_response(public(drive))


# --- audience reports --------------------------------------------------------
@bp.route("/network/audience-reports", methods=["POST"])
@route("/network/audience-reports", "POST")
def create_audience_report():
    body = base.get_body(request.get_json(silent=True))
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    _station_or_404(station_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station_id)
    fiscal_year = base.as_int(body.get("fiscal_year"), "fiscal_year", low=2024, high=2100)
    cume = base.as_cents(body.get("cume_persons"), "cume_persons")
    share = base.as_int(body.get("nielsen_share_bps"), "nielsen_share_bps", low=0, high=10000)
    hours = base.as_cents(body.get("local_content_hours"), "local_content_hours")
    report = new_record(
        "AudienceReport",
        common=False,
        station_id=station_id,
        fiscal_year=fiscal_year,
        cume_persons=cume,
        nielsen_share_bps=share,
        local_content_hours=hours,
        reported_at=C.iso(C.now()),
    )
    STORE.put("audience_reports", report)
    return object_response(public(report), 201)


@bp.route("/network/audience-reports", methods=["GET"])
@route("/network/audience-reports", "GET")
def list_audience_reports():
    args = request.args
    recs = STORE.all("audience_reports")
    station_id = base.scalar_arg(args, "station_id")
    if station_id is not None:
        recs = [r for r in recs if r.get("station_id") == station_id]
    fiscal_year = base.scalar_arg(args, "fiscal_year", "int")
    if fiscal_year is not None:
        recs = [r for r in recs if r.get("fiscal_year") == fiscal_year]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/audience-reports/<rid>", methods=["GET"])
@route("/network/audience-reports/<rid>", "GET")
def read_audience_report(rid):
    report = STORE.audience_reports.get(rid)
    if report is None:
        raise not_found("audience report")
    return object_response(public(report))


# --- dues proposals and votes ------------------------------------------------
@bp.route("/network/dues-proposals", methods=["POST"])
@route("/network/dues-proposals", "POST")
def create_proposal():
    body = base.get_body(request.get_json(silent=True))
    fiscal_year = base.as_int(body.get("fiscal_year"), "fiscal_year", low=2024, high=2100)
    proposed_base = base.as_cents(body.get("proposed_base_fee_cents"), "proposed_base_fee_cents")
    proposed_rate = base.as_int(body.get("proposed_revenue_rate_bps"), "proposed_revenue_rate_bps", low=0)
    quorum = base.as_int(body.get("quorum_required_votes"), "quorum_required_votes", low=1)
    effective_from = base.as_instant(body.get("effective_from"), "effective_from")
    proposal = new_record(
        "DuesStructureProposal",
        fiscal_year=fiscal_year,
        proposal_status="DRAFT",
        current_rate_bps=250,
        proposed_base_fee_cents=proposed_base,
        proposed_revenue_rate_bps=proposed_rate,
        quorum_required_votes=quorum,
        eligible_station_count=0,
        yes_votes=0,
        no_votes=0,
        votes_cast_count=0,
        proposal_cycle=0,
        effective_from=effective_from,
        board_region=body.get("board_region"),
    )
    STORE.put("proposals", proposal)
    return object_response(public(proposal), 201)


@bp.route("/network/dues-proposals", methods=["GET"])
@route("/network/dues-proposals", "GET")
def list_proposals():
    args = request.args
    recs = STORE.all("proposals")
    fiscal_year = base.scalar_arg(args, "fiscal_year", "int")
    if fiscal_year is not None:
        recs = [r for r in recs if r.get("fiscal_year") == fiscal_year]
    status = base.scalar_arg(args, "proposal_status")
    if status is not None:
        recs = [r for r in recs if r.get("proposal_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/dues-proposals/<pid>", methods=["GET"])
@route("/network/dues-proposals/<pid>", "GET")
def read_proposal(pid):
    proposal = proposal_or_404(pid)
    governance.recompute_vote_weights(STORE, proposal)
    return object_response(public(proposal))


@bp.route("/network/dues-proposals/<pid>/votes", methods=["GET"])
@route("/network/dues-proposals/<pid>/votes", "GET")
def proposal_votes(pid):
    proposal_or_404(pid)
    args = request.args
    recs = [v for v in STORE.votes.values() if v.get("parent_proposal_id") == pid]
    for field in ("station_id", "vote_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/station-votes", methods=["GET"])
@route("/network/station-votes", "GET")
def list_votes():
    args = request.args
    recs = STORE.all("votes")
    for field in ("station_id", "parent_proposal_id", "vote_status", "superseded_by_vote_id"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/station-votes/<vid>", methods=["GET"])
@route("/network/station-votes/<vid>", "GET")
def read_vote(vid):
    return object_response(public(vote_or_404(vid)))


@bp.route("/network/dues-proposals/<pid>/open", methods=["POST"])
@route("/network/dues-proposals/<pid>/open", "POST")
def open_proposal(pid):
    proposal = proposal_or_404(pid)
    status = proposal.get("proposal_status")
    if status in ("ENACTMENT_CLOSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    eligible = governance.recompute_quorum_denominators(STORE)
    if status == "DRAFT":
        if int(proposal.get("quorum_required_votes") or 0) > eligible:
            raise invalid_state("the quorum exceeds the eligible station count")
        if int(proposal.get("proposed_revenue_rate_bps") or 0) < 0:
            raise invalid_state("the proposed rate is negative")
        proposal["eligible_station_count"] = eligible
        proposal["current_rate_bps"] = fees.current_network_rate_bps(STORE)
        proposal["yes_votes"] = 0
        proposal["no_votes"] = 0
        proposal["votes_cast_count"] = 0
    elif status == "TABLED":
        if int(proposal.get("quorum_required_votes") or 0) > eligible:
            raise invalid_state("the quorum exceeds the eligible station count")
        proposal["eligible_station_count"] = eligible
    else:
        raise invalid_state("the proposal cannot be opened from its current state")
    proposal["proposal_status"] = "OPEN"
    touch(proposal)
    return object_response(public(proposal))


@bp.route("/network/dues-proposals/<pid>/votes", methods=["POST"])
@route("/network/dues-proposals/<pid>/votes", "POST")
def cast_vote(pid):
    proposal = proposal_or_404(pid)
    if proposal.get("proposal_status") != "OPEN":
        raise invalid_state("the proposal is not open")
    body = base.get_body(request.get_json(silent=True))
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    station = _station_or_404(station_id)
    check_station_ownership(
        request.headers.get("X-User-Role"), request.headers.get("X-User-ID"), station_id
    )
    choice = base.as_enum(body.get("vote_choice"), VOTE_CHOICES, "vote_choice")
    base.as_int(body.get("current_rate_bps"), "current_rate_bps", low=0)
    expected = base.as_int(
        body.get("expected_station_version"), "expected_station_version", required=False
    )
    if expected is None:
        raise bad_request("expected_station_version is required")
    if station.get("eligibility_status") == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    # PRD §3.9 gates the act before the version check matters: eligibility,
    # suspension, an existing recorded vote and an unsettled supersede pair are
    # all settled ahead of the §2.6 stale-version rejection.
    if station.get("eligibility_status") in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError("ERR_STATION_SUSPENDED")
    eligible_from = C.parse_dt(station.get("eligible_from"))
    if eligible_from is None or eligible_from > C.now():
        raise invalid_state("the station holds no current vote eligibility")
    live = [
        v for v in STORE.votes.values()
        if v.get("parent_proposal_id") == pid
        and v.get("station_id") == station_id
        and v.get("vote_status") == "RECORDED"
    ]
    if live:
        raise ApiError("ERR_VOTE_ALREADY_RECORDED")
    outstanding = [
        v for v in STORE.votes.values()
        if v.get("parent_proposal_id") == pid
        and v.get("station_id") == station_id
        and v.get("vote_status") == "SUPERSEDED"
        and v.get("_superseder_live")
    ]
    if outstanding:
        raise ApiError("ERR_DUES_VOTE_IN_PROGRESS")
    if int(expected) != int(station.get("version") or 0):
        raise ApiError("ERR_STALE_STATION_VERSION")
    vote = new_record(
        "StationVote",
        parent_proposal_id=pid,
        station_id=station_id,
        vote_choice=choice,
        current_rate_bps=int(body.get("current_rate_bps")),
        recorded_weight=0,
        cast_at=C.iso(C.now()),
        vote_status="RECORDED",
        superseded_by_vote_id=None,
        compensated_at=None,
    )
    STORE.put("votes", vote)
    governance.recompute_vote_weights(STORE, proposal)
    station["dues_vote_eligible"] = bool(governance.projection_eligible(station))
    touch(station)
    touch(proposal)
    return object_response(public(vote))


@bp.route("/network/station-votes/<vid>/supersede", methods=["POST"])
@route("/network/station-votes/<vid>/supersede", "POST")
def supersede_vote(vid):
    vote = vote_or_404(vid)
    proposal = proposal_or_404(vote.get("parent_proposal_id"))
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, vote.get("station_id"))
    if vote.get("vote_status") == "INVALIDATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if vote.get("vote_status") != "RECORDED":
        raise invalid_state("the vote is not recorded")
    if proposal.get("proposal_status") != "OPEN":
        raise invalid_state("the proposal is not open")
    station = _station_or_404(vote.get("station_id"))
    if station.get("eligibility_status") in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError("ERR_STATION_SUSPENDED")
    body = base.get_body(request.get_json(silent=True))
    choice = base.as_enum(body.get("vote_choice"), VOTE_CHOICES, "vote_choice")
    replacement = new_record(
        "StationVote",
        parent_proposal_id=proposal["id"],
        station_id=vote.get("station_id"),
        vote_choice=choice,
        current_rate_bps=int(body.get("current_rate_bps") or vote.get("current_rate_bps") or 0),
        recorded_weight=0,
        cast_at=C.iso(C.now()),
        vote_status="RECORDED",
        superseded_by_vote_id=None,
        compensated_at=None,
    )
    STORE.put("votes", replacement)
    vote["vote_status"] = "SUPERSEDED"
    vote["recorded_weight"] = 0
    vote["superseded_by_vote_id"] = replacement["id"]
    vote["compensated_at"] = C.iso(C.now())
    vote["_superseder_live"] = True
    touch(vote)
    governance.recompute_vote_weights(STORE, proposal)
    touch(proposal)
    data = public(replacement)
    data["superseded_vote_id"] = vote["id"]
    return object_response(data)


@bp.route("/network/station-votes/<vid>/restore", methods=["POST"])
@route("/network/station-votes/<vid>/restore", "POST")
def restore_vote(vid):
    vote = vote_or_404(vid)
    proposal = proposal_or_404(vote.get("parent_proposal_id"))
    superseding_id = vote.get("superseded_by_vote_id")
    if vote.get("vote_status") == "SUPERSEDED" and superseding_id:
        superseding = STORE.votes.get(superseding_id)
        if superseding is None:
            raise not_found("station vote")
        if superseding.get("vote_status") != "RECORDED":
            raise invalid_state("the superseding row is not recorded")
        superseding["vote_status"] = "INVALIDATED"
        superseding["recorded_weight"] = 0
        touch(superseding)
        vote["vote_status"] = "RECORDED"
        vote.pop("_superseder_live", None)
        vote["compensated_at"] = C.iso(C.now())
        station = STORE.member_stations.get(vote.get("station_id"))
        vote["recorded_weight"] = governance.recorded_weight_for(
            vote.get("vote_choice"), governance.base_weight(station)
        )
    elif vote.get("vote_status") == "RECORDED" and superseding_id:
        vote["vote_status"] = "INVALIDATED"
        vote["recorded_weight"] = 0
        vote["compensated_at"] = C.iso(C.now())
    else:
        raise invalid_state("the vote cannot be restored from its current state")
    touch(vote)
    governance.recompute_vote_weights(STORE, proposal)
    touch(proposal)
    return object_response(public(vote))


@bp.route("/network/dues-proposals/<pid>/tally", methods=["POST"])
@route("/network/dues-proposals/<pid>/tally", "POST")
def tally_proposal(pid):
    proposal = proposal_or_404(pid)
    status = proposal.get("proposal_status")
    if status in ("ENACTMENT_CLOSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "OPEN":
        raise invalid_state("the proposal is not open")
    governance.recompute_vote_weights(STORE, proposal)
    if not governance.quorum_met(proposal):
        raise invalid_state("the proposal has not reached its quorum")
    proposal["proposal_status"] = (
        "PASSED" if governance.proposal_passes(proposal) else "REJECTED"
    )
    touch(proposal)
    return object_response(public(proposal))


@bp.route("/network/dues-proposals/<pid>/table", methods=["POST"])
@route("/network/dues-proposals/<pid>/table", "POST")
def table_proposal(pid):
    proposal = proposal_or_404(pid)
    status = proposal.get("proposal_status")
    if status in ("ENACTMENT_CLOSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "OPEN":
        raise invalid_state("the proposal is not open")
    governance.recompute_vote_weights(STORE, proposal)
    if governance.quorum_met(proposal):
        raise invalid_state("the proposal has reached its quorum")
    proposal["proposal_status"] = "TABLED"
    touch(proposal)
    return object_response(public(proposal))


@bp.route("/network/dues-proposals/<pid>/enact", methods=["POST"])
@route("/network/dues-proposals/<pid>/enact", "POST")
def enact_proposal(pid):
    proposal = proposal_or_404(pid)
    status = proposal.get("proposal_status")
    if status in ("ENACTMENT_CLOSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PASSED":
        raise invalid_state("the proposal has not passed")
    effective_from = C.parse_dt(proposal.get("effective_from"))
    if effective_from is None or C.now() < effective_from:
        raise invalid_state("the proposal's effective instant has not arrived")
    body = base.get_body(request.get_json(silent=True))
    expected = base.as_int(
        body.get("expected_proposal_version"), "expected_proposal_version", required=False
    )
    if expected is None:
        raise bad_request("expected_proposal_version is required")
    if int(expected) != int(proposal.get("version") or 0):
        raise ApiError("ERR_STALE_PROPOSAL_VERSION")
    batch = [
        a for a in STORE.assessments.values()
        if a.get("fiscal_year") == proposal.get("fiscal_year")
    ]
    if batch:
        pot = sum(int(a.get("total_pot_cents") or 0) for a in batch)
        if pot > 0:
            governance.allocate_pool(STORE, batch, pot, proposal.get("fiscal_year"))
    for schedule in STORE.schedules.values():
        start = C.parse_dt(schedule.get("effective_from"))
        end = C.parse_dt(schedule.get("effective_to"))
        if start is not None and effective_from < start:
            continue
        if end is not None and effective_from >= end:
            continue
        schedule["base_fee_cents"] = int(proposal.get("proposed_base_fee_cents") or 0)
        schedule["revenue_rate_bps"] = int(proposal.get("proposed_revenue_rate_bps") or 0)
    for assessment in batch:
        station = STORE.member_stations.get(assessment.get("station_id"))
        if station is None:
            continue
        fees.compute_assessment(STORE, assessment, station)
    proposal["proposal_status"] = "ENACTED"
    proposal["proposal_cycle"] = int(proposal.get("proposal_cycle") or 0) + 1
    touch(proposal)
    return object_response(public(proposal))


@bp.route("/network/dues-proposals/<pid>/close-enactment", methods=["POST"])
@route("/network/dues-proposals/<pid>/close-enactment", "POST")
def close_enactment(pid):
    proposal = proposal_or_404(pid)
    if proposal.get("proposal_status") == "ENACTMENT_CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal.get("proposal_status") != "ENACTED":
        raise invalid_state("the proposal is not enacted")
    effective_from = C.parse_dt(proposal.get("effective_from"))
    if effective_from is None or C.now() < effective_from:
        raise invalid_state("the proposal's effective instant has not arrived")
    proposal["proposal_status"] = "ENACTMENT_CLOSED"
    for vote in STORE.votes.values():
        if vote.get("parent_proposal_id") != pid:
            continue
        if vote.get("vote_status") == "SUPERSEDED":
            vote["vote_status"] = "INVALIDATED"
            vote["recorded_weight"] = 0
            touch(vote)
    touch(proposal)
    return object_response(public(proposal))


# --- projections -------------------------------------------------------------
@bp.route("/network/dues-vote-eligibility-projections", methods=["GET"])
@route("/network/dues-vote-eligibility-projections", "GET")
def list_projections():
    args = request.args
    recs = STORE.all("projections")
    station_id = base.scalar_arg(args, "station_id")
    if station_id is not None:
        recs = [r for r in recs if r.get("station_id") == station_id]
    fiscal_year = base.scalar_arg(args, "fiscal_year", "int")
    if fiscal_year is not None:
        recs = [r for r in recs if r.get("fiscal_year") == fiscal_year]
    eligible = base.scalar_arg(args, "dues_vote_eligible", "bool")
    if eligible is not None:
        recs = [r for r in recs if bool(r.get("dues_vote_eligible")) == eligible]
    page, meta = base.paginate(recs, args)
    return array_response([projection_view(STORE, r) for r in page], meta)


@bp.route("/network/dues-vote-eligibility-projections/<pid>", methods=["GET"])
@route("/network/dues-vote-eligibility-projections/<pid>", "GET")
def read_projection(pid):
    row = STORE.projections.get(pid)
    if row is None:
        raise not_found("dues vote eligibility projection")
    return object_response(projection_view(STORE, row))


# --- board elections, candidacies and seats ----------------------------------
@bp.route("/network/board-elections", methods=["POST"])
@route("/network/board-elections", "POST")
def create_election():
    body = base.get_body(request.get_json(silent=True))
    region = base.as_enum(body.get("board_region"), REGIONS, "board_region")
    fiscal_year = base.as_int(body.get("fiscal_year"), "fiscal_year", low=2024, high=2100)
    seats = base.as_int(body.get("seats_available"), "seats_available", low=1)
    deadline = base.as_instant(body.get("certification_deadline"), "certification_deadline")
    election = new_record(
        "BoardElection",
        board_region=region,
        fiscal_year=fiscal_year,
        election_status="OPEN",
        cycle_number=0,
        seats_available=seats,
        certification_deadline=deadline,
    )
    STORE.put("elections", election)
    return object_response(public(election), 201)


@bp.route("/network/board-elections", methods=["GET"])
@route("/network/board-elections", "GET")
def list_elections():
    args = request.args
    recs = STORE.all("elections")
    for field in ("board_region", "election_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    fiscal_year = base.scalar_arg(args, "fiscal_year", "int")
    if fiscal_year is not None:
        recs = [r for r in recs if r.get("fiscal_year") == fiscal_year]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/board-elections/<eid>", methods=["GET"])
@route("/network/board-elections/<eid>", "GET")
def read_election(eid):
    return object_response(public(election_or_404(eid)))


@bp.route("/network/board-elections/<eid>/candidates", methods=["GET"])
@route("/network/board-elections/<eid>/candidates", "GET")
def election_candidates(eid):
    election_or_404(eid)
    args = request.args
    recs = [c for c in STORE.candidates.values() if c.get("parent_election_id") == eid]
    status = base.scalar_arg(args, "candidate_status")
    if status is not None:
        recs = [r for r in recs if r.get("candidate_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


def _board_seat_for_election(store, election, candidate=None):
    region = election.get("board_region")
    seats = sorted(
        [s for s in store.seats.values() if s.get("board_region") == region],
        key=lambda s: int(s.get("board_rank") or 0),
    )
    if candidate is not None:
        seat_id = candidate.get("_seat_id")
        if seat_id and seat_id in store.seats:
            return store.seats[seat_id]
    for seat in seats:
        if seat.get("seat_status") == "VACANT":
            return seat
    for seat in seats:
        if seat.get("seat_status") == "CONTESTED":
            return seat
    return None


@bp.route("/network/board-elections/<eid>/close", methods=["POST"])
@route("/network/board-elections/<eid>/close", "POST")
def close_election(eid):
    election = election_or_404(eid)
    status = election.get("election_status")
    if status == "FINALIZED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    deadline = C.parse_dt(election.get("certification_deadline"))
    if status == "OPEN":
        if deadline is None or C.now() < deadline:
            raise invalid_state("the certification deadline has not arrived")
        election["election_status"] = "CLOSED"
        for candidate in STORE.candidates.values():
            if candidate.get("parent_election_id") != eid:
                continue
            if candidate.get("candidate_status") != "QUALIFIED":
                continue
            station = STORE.member_stations.get(candidate.get("station_id"))
            if not governance.projection_eligible(station):
                candidate["candidate_status"] = "LAPSED"
                touch(candidate)
    elif status == "REOPENED":
        if deadline is None or C.now() >= deadline:
            raise invalid_state("the certification deadline has already passed")
        election["election_status"] = "OPEN"
    else:
        raise invalid_state("the election cannot be closed from its current state")
    touch(election)
    return object_response(public(election))


@bp.route("/network/board-elections/<eid>/certify", methods=["POST"])
@route("/network/board-elections/<eid>/certify", "POST")
def certify_election(eid):
    election = election_or_404(eid)
    if election.get("election_status") == "FINALIZED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if election.get("election_status") != "CLOSED":
        raise invalid_state("the election is not closed")
    body = base.get_body(request.get_json(silent=True))
    expected = base.as_int(
        body.get("expected_election_version"), "expected_election_version", required=False
    )
    if expected is None:
        raise bad_request("expected_election_version is required")
    if int(expected) != int(election.get("version") or 0):
        raise ApiError("ERR_STALE_ELECTION_VERSION")
    qualified = [
        c for c in STORE.candidates.values()
        if c.get("parent_election_id") == eid
        and c.get("candidate_status") == "QUALIFIED"
    ]
    if not qualified:
        raise invalid_state("the election has no qualified candidacy")
    for candidate in qualified:
        stamp = C.parse_dt(candidate.get("last_candidacy_cycle"))
        if stamp is None or stamp > C.now():
            raise ApiError("ERR_CANDIDACY_NOT_QUALIFIED")
    ranked = governance.rank_qualified(STORE, election)
    elected = None
    for index, candidate in enumerate(ranked):
        if index == 0 and int(candidate.get("votes_recorded") or 0) >= 1:
            candidate["candidate_status"] = "ELECTED"
            elected = candidate
        else:
            candidate["candidate_status"] = "DEFEATED"
        touch(candidate)
    if elected is not None:
        seat = _board_seat_for_election(STORE, election, elected)
        if seat is not None:
            governance.fill_seat_for_candidate(STORE, seat, elected)
    election["election_status"] = "CERTIFIED"
    election["cycle_number"] = int(election.get("cycle_number") or 0) + 1
    election["_elected_candidate_id"] = elected["id"] if elected else None
    touch(election)
    return object_response(public(election))


@bp.route("/network/board-elections/<eid>/contest", methods=["POST"])
@route("/network/board-elections/<eid>/contest", "POST")
def contest_election(eid):
    election = election_or_404(eid)
    if election.get("election_status") == "FINALIZED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if election.get("election_status") != "CERTIFIED":
        raise invalid_state("the election is not certified")
    body = base.get_body(request.get_json(silent=True))
    base.as_text(body.get("contest_reason"), "contest_reason")
    elected = None
    for candidate in STORE.candidates.values():
        if candidate.get("parent_election_id") != eid:
            continue
        if candidate.get("candidate_status") == "ELECTED":
            elected = candidate
            break
    if elected is None and election.get("_elected_candidate_id"):
        elected = STORE.candidates.get(election.get("_elected_candidate_id"))
    if elected is None:
        raise invalid_state("the election has no elected candidacy")
    elected["candidate_status"] = "QUALIFIED"
    elected["votes_recorded"] = 0
    elected["last_candidacy_cycle"] = C.iso(C.now())
    touch(elected)
    seat = _board_seat_for_election(STORE, election, elected)
    if seat is not None:
        seat["seat_status"] = "CONTESTED"
        touch(seat)
    election["election_status"] = "CONTESTED"
    touch(election)
    return object_response(public(election))


@bp.route("/network/board-elections/<eid>/reopen", methods=["POST"])
@route("/network/board-elections/<eid>/reopen", "POST")
def reopen_election(eid):
    election = election_or_404(eid)
    if election.get("election_status") == "FINALIZED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if election.get("election_status") != "CONTESTED":
        raise invalid_state("the election is not contested")
    for candidate in STORE.candidates.values():
        if candidate.get("parent_election_id") != eid:
            continue
        candidate["votes_recorded"] = 0
        touch(candidate)
    for seat in STORE.seats.values():
        if seat.get("board_region") != election.get("board_region"):
            continue
        if seat.get("seat_status") == "CONTESTED":
            seat["seat_status"] = "VACANT"
            seat["station_id"] = None
            seat["term_start"] = None
            touch(seat)
    election["election_status"] = "REOPENED"
    touch(election)
    return object_response(public(election))


@bp.route("/network/board-elections/<eid>/hold-over", methods=["POST"])
@route("/network/board-elections/<eid>/hold-over", "POST")
def hold_over(eid):
    election = election_or_404(eid)
    seat = None
    for candidate in STORE.seats.values():
        if candidate.get("board_region") == election.get("board_region"):
            if candidate.get("seat_status") == "CONTESTED":
                seat = candidate
                break
    if seat is None:
        raise invalid_state("the region has no contested seat")
    term_end = C.parse_dt(seat.get("term_end"))
    if term_end is None or C.now() >= term_end:
        raise invalid_state("the seat's term has already ended")
    seat["seat_status"] = "HOLDOVER"
    touch(seat)
    data = public(election)
    data["seat"] = public(seat)
    return object_response(data)


@bp.route("/network/board-elections/<eid>/vacate-seat", methods=["POST"])
@route("/network/board-elections/<eid>/vacate-seat", "POST")
def vacate_seat(eid):
    election = election_or_404(eid)
    seat = None
    for candidate in STORE.seats.values():
        if candidate.get("board_region") == election.get("board_region"):
            if candidate.get("seat_status") == "HOLDOVER":
                seat = candidate
                break
    if seat is None:
        raise invalid_state("the region has no holdover seat")
    term_end = C.parse_dt(seat.get("term_end"))
    if term_end is None or C.now() <= term_end:
        raise invalid_state("the seat's term has not ended")
    seat["seat_status"] = "VACANT"
    seat["station_id"] = None
    touch(seat)
    data = public(election)
    data["seat"] = public(seat)
    return object_response(data)


@bp.route("/network/board-elections/<eid>/finalize", methods=["POST"])
@route("/network/board-elections/<eid>/finalize", "POST")
def finalize_election(eid):
    election = election_or_404(eid)
    if election.get("election_status") == "FINALIZED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if election.get("election_status") != "CERTIFIED":
        raise invalid_state("the election is not certified")
    deadline = C.parse_dt(election.get("certification_deadline"))
    if deadline is None or C.now() <= deadline:
        raise invalid_state("the certification deadline has not passed")
    election["election_status"] = "FINALIZED"
    touch(election)
    return object_response(public(election))


# --- candidacies -------------------------------------------------------------
@bp.route("/network/board-candidates", methods=["POST"])
@route("/network/board-candidates", "POST")
def create_candidate():
    body = base.get_body(request.get_json(silent=True))
    election_id = body.get("parent_election_id")
    if election_id is None:
        raise bad_request("parent_election_id is required")
    election_or_404(election_id)
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    _station_or_404(station_id)
    check_station_ownership(
        request.headers.get("X-User-Role"), request.headers.get("X-User-ID"), station_id
    )
    statement = base.as_text(body.get("nomination_statement"), "nomination_statement", required=False)
    candidate = new_record(
        "BoardCandidate",
        parent_election_id=election_id,
        station_id=station_id,
        candidate_status="FILED",
        votes_recorded=0,
        last_candidacy_cycle=None,
        nomination_statement=statement,
        _board_rank=0,
        _seat_id=None,
    )
    STORE.put("candidates", candidate)
    return object_response(public(candidate), 201)


@bp.route("/network/board-candidates", methods=["GET"])
@route("/network/board-candidates", "GET")
def list_candidates():
    args = request.args
    recs = STORE.all("candidates")
    for field in ("parent_election_id", "station_id", "candidate_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/board-candidates/<cid>", methods=["GET"])
@route("/network/board-candidates/<cid>", "GET")
def read_candidate(cid):
    return object_response(public(candidate_or_404(cid)))


@bp.route("/network/board-candidates/<cid>/qualify", methods=["POST"])
@route("/network/board-candidates/<cid>/qualify", "POST")
def qualify_candidate(cid):
    candidate = candidate_or_404(cid)
    if candidate.get("candidate_status") in ("ELECTED", "DEFEATED", "LAPSED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if candidate.get("candidate_status") != "FILED":
        raise invalid_state("the candidacy is not filed")
    station = _station_or_404(candidate.get("station_id"))
    eligible_from = C.parse_dt(station.get("eligible_from"))
    if eligible_from is None or eligible_from > C.now():
        raise invalid_state("the station has not reached its eligible_from instant")
    candidate["candidate_status"] = "QUALIFIED"
    candidate["last_candidacy_cycle"] = C.iso(C.now())
    touch(candidate)
    return object_response(public(candidate))


@bp.route("/network/board-candidates/<cid>/lapse", methods=["POST"])
@route("/network/board-candidates/<cid>/lapse", "POST")
def lapse_candidate(cid):
    candidate = candidate_or_404(cid)
    if candidate.get("candidate_status") in ("ELECTED", "DEFEATED", "LAPSED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if candidate.get("candidate_status") not in ("FILED", "QUALIFIED"):
        raise invalid_state("the candidacy cannot lapse from its current state")
    station = _station_or_404(candidate.get("station_id"))
    if governance.projection_eligible(station):
        raise invalid_state("the station still holds vote eligibility")
    candidate["candidate_status"] = "LAPSED"
    touch(candidate)
    return object_response(public(candidate))


@bp.route("/network/board-candidates/<cid>/record-votes", methods=["POST"])
@route("/network/board-candidates/<cid>/record-votes", "POST")
def record_candidate_votes(cid):
    candidate = candidate_or_404(cid)
    if candidate.get("candidate_status") in ("ELECTED", "DEFEATED", "LAPSED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if candidate.get("candidate_status") != "QUALIFIED":
        raise invalid_state("the candidacy is not qualified")
    body = base.get_body(request.get_json(silent=True))
    votes = base.as_cents(body.get("votes_recorded"), "votes_recorded")
    candidate["votes_recorded"] = votes
    touch(candidate)
    return object_response(public(candidate))


@bp.route("/network/board-candidates/<cid>/withdraw", methods=["POST"])
@route("/network/board-candidates/<cid>/withdraw", "POST")
def withdraw_candidate(cid):
    candidate = candidate_or_404(cid)
    check_station_ownership(
        request.headers.get("X-User-Role"),
        request.headers.get("X-User-ID"),
        candidate.get("station_id"),
    )
    if candidate.get("candidate_status") in ("ELECTED", "DEFEATED", "LAPSED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if candidate.get("candidate_status") not in ("FILED", "QUALIFIED"):
        raise invalid_state("the candidacy cannot be withdrawn from its current state")
    candidate["candidate_status"] = "WITHDRAWN"
    touch(candidate)
    return object_response(public(candidate))


# --- board seats -------------------------------------------------------------
@bp.route("/network/board-seats", methods=["POST"])
@route("/network/board-seats", "POST")
def create_seat():
    body = base.get_body(request.get_json(silent=True))
    region = base.as_enum(body.get("board_region"), REGIONS, "board_region")
    term_start = base.as_instant(body.get("term_start"), "term_start")
    term_end = base.as_instant(body.get("term_end"), "term_end")
    if C.parse_dt(term_end) <= C.parse_dt(term_start):
        raise bad_request("term_end must be after term_start")
    rank = base.as_int(body.get("board_rank"), "board_rank", low=0, required=False)
    seat = new_record(
        "BoardSeat",
        board_region=region,
        station_id=None,
        seat_status="VACANT",
        term_start=term_start,
        term_end=term_end,
        board_rank=0 if rank is None else rank,
        carried_credit_cents=0,
        contribution_deduction_cents=0,
    )
    STORE.put("seats", seat)
    return object_response(public(seat), 201)


@bp.route("/network/board-seats", methods=["GET"])
@route("/network/board-seats", "GET")
def list_seats():
    args = request.args
    recs = STORE.all("seats")
    for field in ("board_region", "station_id", "seat_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/board-seats/<sid>", methods=["GET"])
@route("/network/board-seats/<sid>", "GET")
def read_seat(sid):
    return object_response(public(seat_or_404(sid)))


@bp.route("/network/board-seats/<sid>/deallocate", methods=["POST"])
@route("/network/board-seats/<sid>/deallocate", "POST")
def deallocate_seat(sid):
    seat = seat_or_404(sid)
    if seat.get("seat_status") == "RECALLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if seat.get("seat_status") != "FILLED":
        raise invalid_state("the seat is not filled")
    body = base.get_body(request.get_json(silent=True))
    target = body.get("deallocation_of_seat_id")
    if target is None:
        raise bad_request("deallocation_of_seat_id is required")
    if target != seat["id"]:
        raise invalid_state("deallocation_of_seat_id must name this seat")
    seat["station_id"] = None
    seat["term_start"] = None
    seat["carried_credit_cents"] = 0
    seat["seat_status"] = "VACANT"
    touch(seat)
    return object_response(public(seat))


@bp.route("/network/board-seats/<sid>/recall", methods=["POST"])
@route("/network/board-seats/<sid>/recall", "POST")
def recall_seat(sid):
    seat = seat_or_404(sid)
    if seat.get("seat_status") == "RECALLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if seat.get("seat_status") != "FILLED":
        raise invalid_state("the seat is not filled")
    body = base.get_body(request.get_json(silent=True))
    reference = base.as_text(body.get("recall_resolution_ref"), "recall_resolution_ref")
    seat["seat_status"] = "RECALLED"
    seat["station_id"] = None
    seat["_recall_resolution_ref"] = reference
    touch(seat)
    return object_response(public(seat))