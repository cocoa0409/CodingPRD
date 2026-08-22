"""Constitutional-amendment referendum endpoints (PRD 3.6).

A referendum carries two entirely independent status axes: drafting_status and
outcome_status.
"""
from decimal import Decimal

from flask import Blueprint

import auth
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("referenda", __name__)


@bp.post("/referenda")
def create_referendum():
    user_id, _role = auth.require(constants.STUDENT_VOTER)
    body = validation.get_body()

    # rule 4 — body foreign key
    election = lookup.fk_election(body)

    # rule 5 — schema
    validation.req_str(body, "election_id")
    title = validation.req_str(body, "title")
    article_reference = validation.req_str(body, "article_reference")
    body_text = validation.req_text(body, "body_text")
    approval_threshold_pct = validation.opt_decimal(
        body, "approval_threshold_pct",
        default=constants.DEFAULT_APPROVAL_THRESHOLD_PCT, minimum=0, maximum=100)

    # rule 10 — election phase
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Referenda may only be drafted while the election is PETITIONING.")

    row = db.new_row(db.store.referenda, {
        "election_id": election["id"],
        "title": title,
        "article_reference": article_reference,
        "body_text": body_text,
        "approval_threshold_pct": approval_threshold_pct,
        "drafting_status": "DRAFT",
        "outcome_status": "PENDING",
        "yes_votes_count": 0,
        "no_votes_count": 0,
        "abstain_votes_count": 0,
        "approval_pct": Decimal("0.00"),
        "return_reason": None,
        # the drafting student, for the rule-7 ownership check on submission
        "_drafted_by_user_id": user_id,
    })
    return response.object_response(serialize.referendum(row), 201)


@bp.get("/referenda")
def list_referenda():
    auth.require_any()
    rows = listing.filtered(db.store.referenda, {
        "election_id": ("election_id", None),
        "drafting_status": ("drafting_status", None),
        "outcome_status": ("outcome_status", None),
    })
    return listing.list_response(rows, serialize.referendum)


@bp.get("/referenda/<referendum_id>")
def read_referendum(referendum_id):
    auth.require_any()
    row = lookup.referendum(referendum_id)
    return response.object_response(serialize.referendum(row))


@bp.post("/referenda/<referendum_id>/submit")
def submit_referendum(referendum_id):
    auth.require(constants.STUDENT_VOTER)
    referendum = lookup.referendum(referendum_id)
    election = db.store.elections[referendum["election_id"]]

    # rule 7 — the acting student must be the one who drafted the amendment
    auth.require_owner(referendum.get("_drafted_by_user_id"))

    if referendum["drafting_status"] not in ("DRAFT", "RETURNED"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a DRAFT or RETURNED amendment may be submitted.")
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Amendments may only be submitted while the election is PETITIONING.")

    db.set_fields(referendum, drafting_status="SUBMITTED", return_reason=None)
    db.touch(referendum)
    return response.object_response(serialize.referendum(referendum))


@bp.post("/referenda/<referendum_id>/review")
def review_referendum(referendum_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    referendum = lookup.referendum(referendum_id)
    election = db.store.elections[referendum["election_id"]]

    body = validation.get_body()
    outcome = validation.req_enum(body, "outcome", constants.REVIEW_OUTCOMES)
    return_reason = validation.opt_text(body, "return_reason")

    if referendum["drafting_status"] != "SUBMITTED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a SUBMITTED amendment may be reviewed.")
    if election["status"] not in ("PETITIONING", "BALLOT_BUILDING"):
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Amendments may only be reviewed while the election is PETITIONING or BALLOT_BUILDING.")

    if outcome == "APPROVE":
        db.set_fields(referendum, drafting_status="APPROVED_FOR_BALLOT")
    else:
        db.set_fields(referendum, drafting_status="RETURNED", return_reason=return_reason)
    db.touch(referendum)
    return response.object_response(serialize.referendum(referendum))
