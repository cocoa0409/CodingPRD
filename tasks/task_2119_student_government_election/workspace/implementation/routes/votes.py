"""Vote casting and voiding (PRD 3.7)."""
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

bp = Blueprint("votes", __name__)


@bp.post("/votes")
def cast_vote():
    user_id, _role = auth.require(constants.STUDENT_VOTER)
    body = validation.get_body()

    # rule 4 — body foreign key
    ballot = lookup.fk_ballot(body)

    # rule 5 — schema
    validation.req_str(body, "ballot_id")
    selections = validation.req_object_array(body, "selections")

    election = db.store.elections[ballot["election_id"]]

    # rule 9 — the ballot must be PUBLISHED
    if ballot["status"] != "PUBLISHED":
        errors.fail(errors.ERR_INVALID_STATE, "Votes may only be cast on a PUBLISHED ballot.")

    # rule 13 — the half-open voting window
    now = db.now()
    opens = election["voting_opens_at"]
    closes = election["voting_closes_at"]
    if (election["status"] != "VOTING_OPEN" or opens is None or closes is None
            or not (opens <= now < closes)):
        errors.fail(errors.ERR_VOTING_WINDOW_CLOSED, "The voting window is not open.")

    # rule 19 — voter eligibility
    student = db.store.students.get(user_id)
    if student is None or student["enrollment_status"] != "ENROLLED" or student["disciplinary_hold"]:
        errors.fail(errors.ERR_VOTER_INELIGIBLE, "The acting student may not vote.")
    lines = lookup.lines_of_ballot(ballot["id"])
    active_lines = [l for l in lines if l["status"] == "ACTIVE"]
    ballot_office_ids = {l["office_id"] for l in active_lines if l["line_type"] == "CANDIDATE"}
    admitted = False
    for office_id in ballot_office_ids:
        office = db.store.offices.get(office_id)
        if office is not None and student["class_year"] in (office["eligible_class_years"] or []):
            admitted = True
            break
    if not admitted:
        errors.fail(errors.ERR_VOTER_INELIGIBLE,
                    "No office on this ballot admits the student's class year.")

    # rule 20 — one cast vote per election, round and student
    for existing in lookup.votes_of(election["id"]):
        if (existing["round"] == ballot["round"] and existing["student_id"] == student["id"]
                and existing["status"] == "CAST"):
            errors.fail(errors.ERR_DUPLICATE_VOTE,
                        "The student has already cast a ballot for this round.")

    # rule 27 — selection shape
    seen_offices = set()
    seen_referenda = set()
    for mark in selections:
        if "office_id" in mark:
            office_id = mark.get("office_id")
            candidacy_id = mark.get("candidacy_id")
            if office_id in seen_offices:
                errors.fail(errors.ERR_INVALID_SELECTION,
                            "An office is marked more than once.")
            seen_offices.add(office_id)
            office_lines = [l for l in active_lines
                            if l["line_type"] == "CANDIDATE" and l["office_id"] == office_id]
            if not office_lines:
                errors.fail(errors.ERR_INVALID_SELECTION,
                            "The mark names an office with no active line on this ballot.")
            if candidacy_id is not None:
                if not any(l["candidacy_id"] == candidacy_id for l in office_lines):
                    errors.fail(errors.ERR_INVALID_SELECTION,
                                "The mark names a candidacy with no active line on this ballot.")
        elif "referendum_id" in mark:
            referendum_id = mark.get("referendum_id")
            if referendum_id in seen_referenda:
                errors.fail(errors.ERR_INVALID_SELECTION,
                            "A referendum is marked more than once.")
            seen_referenda.add(referendum_id)
            if not any(l["line_type"] == "REFERENDUM" and l["referendum_id"] == referendum_id
                       for l in active_lines):
                errors.fail(errors.ERR_INVALID_SELECTION,
                            "The mark names a referendum with no active line on this ballot.")
            if mark.get("choice") not in constants.VOTE_CHOICES:
                errors.fail(errors.ERR_INVALID_SELECTION,
                            "A referendum mark must carry a choice of YES, NO or ABSTAIN.")
        else:
            errors.fail(errors.ERR_INVALID_SELECTION, "A mark resolves to no ballot line.")

    row = db.new_row(db.store.votes, {
        "election_id": election["id"],
        "ballot_id": ballot["id"],
        "student_id": student["id"],
        "round": ballot["round"],
        "selections": selections,
        "status": "CAST",
        "cast_at": now,
        "void_reason": None,
    })
    calc.recompute_turnout(election)
    return response.object_response(serialize.vote(row), 201)


@bp.get("/votes")
def list_votes():
    auth.require_any()
    rows = listing.filtered(db.store.votes, {
        "election_id": ("election_id", None),
        "ballot_id": ("ballot_id", None),
        "student_id": ("student_id", None),
        "round": ("round", listing.as_int),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.vote)


@bp.get("/votes/<vote_id>")
def read_vote(vote_id):
    auth.require_any()
    row = lookup.vote(vote_id)
    return response.object_response(serialize.vote(row))


@bp.post("/votes/<vote_id>/void")
def void_vote(vote_id):
    auth.require(constants.FACULTY_ADVISOR)
    vote = lookup.vote(vote_id)
    election = db.store.elections[vote["election_id"]]

    body = validation.get_body()
    void_reason = validation.req_text(body, "void_reason")

    if vote["status"] != "CAST":
        errors.fail(errors.ERR_INVALID_STATE, "Only a CAST vote may be voided.")
    if election["status"] not in ("VOTING_OPEN", "VOTING_CLOSED", "TALLYING"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Votes may only be voided while the election is VOTING_OPEN, VOTING_CLOSED or TALLYING.")

    db.set_fields(vote, status="VOIDED", void_reason=void_reason)
    db.touch(vote)
    calc.recompute_turnout(election)
    return response.object_response(serialize.vote(vote))
