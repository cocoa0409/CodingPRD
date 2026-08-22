"""Appeals, segregation of duties and the remedy branches (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("appeals", __name__)


@bp.post("/appeals")
def create_appeal():
    auth.require(constants.CANDIDATE)
    body = validation.get_body()

    # rule 4 — body foreign keys, in input-list order
    election = lookup.fk_election(body)
    candidacy = lookup.fk_candidacy(body)
    case = lookup.fk_case(body)

    # rule 5 — schema
    validation.req_str(body, "election_id")
    validation.req_str(body, "candidacy_id")
    grounds = validation.req_text(body, "grounds")
    remedy = validation.req_enum(body, "remedy_requested", constants.REMEDIES)
    if validation.present(body, "compliance_case_id"):
        validation.req_str(body, "compliance_case_id")

    # rule 7 — ownership
    auth.require_owner(candidacy["student_id"])

    # rule 29 — appeal scope
    if case is not None:
        if case["election_id"] != election["id"] or case["candidacy_id"] != candidacy["id"]:
            errors.fail(errors.ERR_APPEAL_SCOPE_INVALID,
                        "The cited compliance case belongs to another election or candidacy.")

    row = db.new_row(db.store.appeals, {
        "election_id": election["id"],
        "candidacy_id": candidacy["id"],
        "compliance_case_id": case["id"] if case else None,
        "grounds": grounds,
        "remedy_requested": remedy,
        "status": "FILED",
        "resolved_by_user_id": None,
        "resolution_note": None,
        "filed_at": db.now(),
    })
    return response.object_response(serialize.appeal(row), 201)


@bp.get("/appeals")
def list_appeals():
    auth.require_any()
    rows = listing.filtered(db.store.appeals, {
        "election_id": ("election_id", None),
        "candidacy_id": ("candidacy_id", None),
        "compliance_case_id": ("compliance_case_id", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.appeal)


@bp.get("/appeals/<appeal_id>")
def read_appeal(appeal_id):
    auth.require_any()
    row = lookup.appeal(appeal_id)
    return response.object_response(serialize.appeal(row))


def _segregation_of_duties(user_id, appeal):
    """Rule 8 — the advisor who blessed the result, or who upheld the cited
    case, may not sit in judgment on the challenge to it."""
    election = db.store.elections.get(appeal["election_id"])
    if election is not None and election["certified_by_user_id"] is not None:
        if user_id == election["certified_by_user_id"]:
            errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                        "The advisor who certified this election may not resolve its appeals.")
    if appeal["compliance_case_id"]:
        case = db.store.compliance_cases.get(appeal["compliance_case_id"])
        if case is not None and case["adjudicated_by_user_id"] is not None:
            if user_id == case["adjudicated_by_user_id"]:
                errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                            "The advisor who adjudicated the cited case may not hear its appeal.")


def _apply_recount(election):
    if election["status"] != "CERTIFIED":
        return
    db.set_fields(election, status="TALLYING",
                  certified_by_user_id=None, certified_at=None)
    for candidacy in lookup.candidacies_of(election["id"]):
        if candidacy["status"] == "ELECTED":
            db.set_fields(candidacy, status="ON_BALLOT", transition_status="NOT_APPLICABLE")
        elif candidacy["status"] == "ELIMINATED":
            db.set_fields(candidacy, status="ON_BALLOT")
    db.touch(election)


def _apply_reinstatement(appeal):
    case = db.store.compliance_cases.get(appeal["compliance_case_id"])
    if case is None:
        errors.fail(errors.ERR_INVALID_STATE,
                    "A REINSTATEMENT appeal must cite a compliance case.")
    candidacy = db.store.candidacies.get(appeal["candidacy_id"])

    if case["status"] == "UPHELD":
        db.set_fields(case, status="DISMISSED", penalty_points=0)
        db.touch(case)
    if candidacy is None:
        return
    calc.recompute_penalty_total(candidacy)
    db.set_fields(candidacy, disqualified_reason=None)
    if candidacy["status"] == "DISQUALIFIED":
        db.set_fields(candidacy, status="ON_BALLOT")
    for line in lookup.lines_of_candidacy(candidacy["id"]):
        if line["status"] != "VOIDED":
            continue
        ballot = db.store.ballots.get(line["ballot_id"])
        if ballot is None or ballot["status"] == "VOIDED":
            continue
        db.set_fields(line, status="ACTIVE")
        db.set_fields(ballot, active_line_count=ballot["active_line_count"] + 1)


@bp.post("/appeals/<appeal_id>/sustain")
def sustain_appeal(appeal_id):
    user_id, _role = auth.require(constants.FACULTY_ADVISOR)
    appeal = lookup.appeal(appeal_id)

    body = validation.get_body()
    resolution_note = validation.opt_text(body, "resolution_note")

    # rule 8 — segregation of duties, before the state gate
    _segregation_of_duties(user_id, appeal)

    # rule 9 — state
    if appeal["status"] != "FILED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a FILED appeal may be sustained.")

    db.set_fields(appeal, status="SUSTAINED", resolved_by_user_id=user_id,
                  resolution_note=resolution_note)
    db.touch(appeal)

    election = db.store.elections.get(appeal["election_id"])
    remedy = appeal["remedy_requested"]
    if remedy == "RECOUNT":
        if election is not None:
            _apply_recount(election)
    elif remedy == "REINSTATEMENT":
        _apply_reinstatement(appeal)
    elif remedy == "VOID_ELECTION":
        if election is not None:
            db.set_fields(election, ballot_integrity_status="RECOUNT_REQUIRED")

    return response.object_response(serialize.appeal(appeal))


@bp.post("/appeals/<appeal_id>/deny")
def deny_appeal(appeal_id):
    user_id, _role = auth.require(constants.FACULTY_ADVISOR)
    appeal = lookup.appeal(appeal_id)

    body = validation.get_body()
    resolution_note = validation.opt_text(body, "resolution_note")

    _segregation_of_duties(user_id, appeal)

    if appeal["status"] != "FILED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a FILED appeal may be denied.")

    # nothing else in the system changes
    db.set_fields(appeal, status="DENIED", resolved_by_user_id=user_id,
                  resolution_note=resolution_note)
    db.touch(appeal)
    return response.object_response(serialize.appeal(appeal))
