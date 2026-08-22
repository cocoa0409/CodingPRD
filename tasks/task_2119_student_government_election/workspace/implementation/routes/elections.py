"""Election endpoints (PRD 3.1, 3.7, 3.8, 3.9)."""
import re
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("elections", __name__)

_ACADEMIC_YEAR_RE = re.compile(r"^\d{4}-\d{4}$")


@bp.post("/elections")
def create_election():
    auth.require(constants.ELECTION_COMMISSIONER)
    body = validation.get_body()

    title = validation.req_str(body, "title", min_len=1, max_len=200)
    academic_year = validation.req_str(body, "academic_year")
    if not _ACADEMIC_YEAR_RE.match(academic_year):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "academic_year must be two four-digit years joined by a hyphen.")
    petition_deadline = validation.req_dt(body, "petition_deadline")
    spending_cap_cents = validation.req_int(body, "spending_cap_cents", minimum=0)
    poster_cap = validation.req_int(body, "poster_cap", minimum=0)
    quorum_pct = validation.req_decimal(body, "quorum_pct", minimum=0, maximum=100)
    runoff_threshold_pct = validation.req_decimal(body, "runoff_threshold_pct",
                                                  minimum=0, maximum=100)
    quiet_period_hours = validation.opt_int(body, "quiet_period_hours",
                                            default=constants.DEFAULT_QUIET_PERIOD_HOURS,
                                            minimum=0)

    row = db.new_row(db.store.elections, {
        "title": title,
        "academic_year": academic_year,
        "status": "DRAFT",
        "current_round": 1,
        "petition_deadline": petition_deadline,
        "quiet_period_hours": quiet_period_hours,
        "voting_opens_at": None,
        "voting_closes_at": None,
        "spending_cap_cents": spending_cap_cents,
        "poster_cap": poster_cap,
        "quorum_pct": quorum_pct,
        "runoff_threshold_pct": runoff_threshold_pct,
        "eligible_voter_count": 0,
        "ballots_cast_count": 0,
        "turnout_pct": Decimal("0.00"),
        "runoff_required_office_count": 0,
        "ballot_integrity_status": "INTACT",
        "certified_by_user_id": None,
        "certified_at": None,
    })
    return response.object_response(serialize.election(row), 201)


@bp.get("/elections")
def list_elections():
    auth.require_any()
    rows = listing.filtered(db.store.elections, {
        "academic_year": ("academic_year", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.election)


@bp.get("/elections/<election_id>")
def read_election(election_id):
    auth.require_any()
    row = lookup.election(election_id)
    return response.object_response(serialize.election(row))


@bp.post("/elections/<election_id>/open-petitioning")
def open_petitioning(election_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    election = lookup.election(election_id)

    # PRD 3.1: refused with ERR_INVALID_STATE unless DRAFT, at least one office
    # is declared, and the clock stands strictly before petition_deadline.
    if election["status"] != "DRAFT":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Petitioning may only be opened from DRAFT.")
    if not lookup.offices_of(election["id"]):
        errors.fail(errors.ERR_INVALID_STATE,
                    "At least one office must be declared before petitioning opens.")
    if not db.now() < election["petition_deadline"]:
        errors.fail(errors.ERR_INVALID_STATE,
                    "The petition deadline has already been reached.")

    db.set_fields(election, status="PETITIONING")
    db.touch(election)
    return response.object_response(serialize.election(election))


@bp.post("/elections/<election_id>/open-voting")
def open_voting(election_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    election = lookup.election(election_id)

    body = validation.get_body()
    validation.req_int(body, "round", minimum=1)
    opens_at = validation.req_dt(body, "voting_opens_at")
    closes_at = validation.req_dt(body, "voting_closes_at")
    if not opens_at < closes_at:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "voting_opens_at must be strictly earlier than voting_closes_at.")

    if election["status"] != "BALLOT_PUBLISHED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Voting may only be opened from BALLOT_PUBLISHED.")
    published = [b for b in lookup.ballots_of(election["id"])
                 if b["round"] == election["current_round"] and b["status"] == "PUBLISHED"]
    if not published:
        errors.fail(errors.ERR_INVALID_STATE,
                    "No PUBLISHED ballot exists for the current round.")

    # PRD 2.10 geometry A — half-open, no buffer, adjacency accepted.
    for other in db.store.elections.values():
        if other["id"] == election["id"]:
            continue
        if other["academic_year"] != election["academic_year"]:
            continue
        if other["voting_opens_at"] is None or other["voting_closes_at"] is None:
            continue
        if opens_at < other["voting_closes_at"] and other["voting_opens_at"] < closes_at:
            errors.fail(errors.ERR_VOTING_WINDOW_OVERLAP,
                        "The requested window collides with another election of this academic year.")

    db.set_fields(election, voting_opens_at=opens_at, voting_closes_at=closes_at)
    if election["current_round"] == 1:
        db.set_fields(election, eligible_voter_count=calc.freeze_electorate(election))
    calc.recompute_turnout(election)
    db.set_fields(election, status="VOTING_OPEN")
    db.touch(election)
    return response.object_response(serialize.election(election))


@bp.post("/elections/<election_id>/close-voting")
def close_voting(election_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    election = lookup.election(election_id)

    if election["status"] != "VOTING_OPEN":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Voting may only be closed from VOTING_OPEN.")
    if election["voting_closes_at"] is None or not db.now() >= election["voting_closes_at"]:
        errors.fail(errors.ERR_INVALID_STATE,
                    "The logical clock has not reached voting_closes_at.")

    for ballot in lookup.ballots_of(election["id"]):
        if ballot["round"] == election["current_round"] and ballot["status"] == "PUBLISHED":
            db.set_fields(ballot, status="CLOSED")
    calc.recompute_turnout(election)
    db.set_fields(election, status="VOTING_CLOSED")
    db.touch(election)
    return response.object_response(serialize.election(election))


@bp.post("/elections/<election_id>/tally")
def tally(election_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    election = lookup.election(election_id)

    if election["status"] != "VOTING_CLOSED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "The tally may only run from VOTING_CLOSED.")

    cascades.run_tally(election)
    return response.object_response(serialize.election(election))


@bp.post("/elections/<election_id>/certify")
def certify(election_id):
    user_id, _role = auth.require(constants.FACULTY_ADVISOR)
    election = lookup.election(election_id)

    if election["status"] != "TALLYING":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Certification may only run from TALLYING.")

    if election["runoff_required_office_count"] == 0:
        cascades.certify_arm_a(election, user_id)
    else:
        cascades.certify_arm_b(election)
    return response.object_response(serialize.election(election))


@bp.post("/elections/<election_id>/run-transition-checkpoint")
def run_transition_checkpoint(election_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    election = lookup.election(election_id)

    if election["status"] != "CERTIFIED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "The transition checkpoint runs only on a CERTIFIED election.")

    cascades.run_transition_checkpoint(election)
    return response.object_response(serialize.election(election))
