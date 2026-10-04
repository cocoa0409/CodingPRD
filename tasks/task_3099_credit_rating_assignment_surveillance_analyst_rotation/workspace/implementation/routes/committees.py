"""Rating committees, votes, rating decisions, appeals and reconciliations."""

from flask import Blueprint

from auth import authed
from db import db
import domain as dom
from errors import fail
from query import apply_filters, body, paginate
from response import created, listing, ok
from services import committees as committee_service
from services import decisions as decision_service
from services import reconciliations as reconciliation_service

bp = Blueprint("committees", __name__)


# ---------------------------------------------------------------------------
# Rating committees
# ---------------------------------------------------------------------------
@bp.route("/rating-committees", methods=["POST"])
@authed("CommitteeChair")
def create_committee(actor):
    payload = body()
    request_id = payload.get("rating_request_id")
    if request_id is None or request_id not in db.rating_requests:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = committee_service.create(
        request_id,
        payload.get("committee_date"),
        payload.get("required_voting_members"),
    )
    return created(dom.rating_committee(row))


@bp.route("/rating-committees", methods=["GET"])
@authed("Any")
def list_committees(actor):
    rows = committee_service.sweep_all(list(db.rating_committees.values()))
    rows = apply_filters(rows, ("rating_request_id", "committee_status"))
    window, limit, offset, total = paginate(rows)
    return listing([dom.rating_committee(r) for r in window], limit, offset, total)


@bp.route("/rating-committees/<rating_committee_id>", methods=["GET"])
@authed("Any")
def get_committee(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    committee_service.sweep(row)
    return ok(dom.rating_committee(row))


@bp.route("/rating-committees/<rating_committee_id>/votes", methods=["GET"])
@authed("Any")
def list_committee_votes(actor, rating_committee_id):
    if rating_committee_id not in db.rating_committees:
        fail("ERR_RESOURCE_NOT_FOUND")
    rows = committee_service.votes_for(rating_committee_id)
    window, limit, offset, total = paginate(rows)
    return listing([dom.committee_vote(r) for r in window], limit, offset, total)


@bp.route("/rating-committees/<rating_committee_id>/open-session", methods=["POST"])
@authed("CommitteeChair")
def open_committee_session(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_committee(committee_service.open_session(row)))


@bp.route("/rating-committees/<rating_committee_id>/votes", methods=["POST"])
@authed("RatingAnalyst")
def cast_committee_vote(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    vote = committee_service.cast_vote(
        row,
        analyst_id,
        payload.get("vote_value"),
        payload.get("assigned_grade"),
        payload.get("dissent_rationale"),
    )
    return created(dom.committee_vote(vote))


def _decision_payload():
    # The 200-character rationale gate is a validation, not a parse step — it
    # runs inside the service after the state and quorum guards, matching the
    # validations[] priority order.
    return body()


@bp.route("/rating-committees/<rating_committee_id>/decide", methods=["POST"])
@authed("CommitteeChair")
def decide_committee(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = _decision_payload()
    decision = committee_service.decide(
        row,
        payload.get("assigned_grade"),
        payload.get("outlook"),
        payload.get("watch_status"),
        payload.get("rationale"),
    )
    return ok(dom.rating_decision(decision))


@bp.route("/rating-committees/<rating_committee_id>/reopen", methods=["POST"])
@authed("CommitteeChair")
def reopen_committee(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_committee(committee_service.reopen(row)))


@bp.route("/rating-committees/<rating_committee_id>/redecide", methods=["POST"])
@authed("CommitteeChair")
def redecide_committee(actor, rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = _decision_payload()
    decision = committee_service.redecide(
        row,
        payload.get("assigned_grade"),
        payload.get("outlook"),
        payload.get("watch_status"),
        payload.get("rationale"),
    )
    return ok(dom.rating_decision(decision))


# ---------------------------------------------------------------------------
# Rating decisions
# ---------------------------------------------------------------------------
@bp.route("/rating-decisions", methods=["GET"])
@authed("Any")
def list_decisions(actor):
    rows = apply_filters(
        list(db.rating_decisions.values()),
        ("rating_request_id", "decision_status", "assigned_grade"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.rating_decision(r) for r in window], limit, offset, total)


@bp.route("/rating-decisions/<rating_decision_id>", methods=["GET"])
@authed("Any")
def get_decision(actor, rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_decision(row))


@bp.route("/rating-decisions/<rating_decision_id>/open-appeal-window", methods=["POST"])
@authed("CommitteeChair")
def open_appeal_window(actor, rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_decision(decision_service.open_appeal_window(row)))


@bp.route("/rating-decisions/<rating_decision_id>/publish", methods=["POST"])
@authed("CommitteeChair")
def publish_decision(actor, rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    version = payload.get("expected_rating_request_version")
    return ok(dom.rating_decision(decision_service.publish(row, version)))


@bp.route("/rating-decisions/<rating_decision_id>/withdraw", methods=["POST"])
@authed("CommitteeChair")
def withdraw_decision(actor, rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_decision(decision_service.withdraw(row)))


@bp.route("/rating-decisions/<rating_decision_id>/appeals", methods=["POST"])
@authed("Anonymous")
def file_appeal(actor, rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    appeal = decision_service.file_appeal(
        row, payload.get("filer_user_id"), payload.get("new_information_summary")
    )
    return created(dom.issuer_appeal(appeal))


# ---------------------------------------------------------------------------
# Issuer appeals
# ---------------------------------------------------------------------------
@bp.route("/issuer-appeals", methods=["GET"])
@authed("Any")
def list_appeals(actor):
    rows = apply_filters(
        list(db.issuer_appeals.values()), ("rating_decision_id", "appeal_outcome")
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.issuer_appeal(r) for r in window], limit, offset, total)


@bp.route("/issuer-appeals/<issuer_appeal_id>", methods=["GET"])
@authed("Any")
def get_appeal(actor, issuer_appeal_id):
    row = db.issuer_appeals.get(issuer_appeal_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.issuer_appeal(row))


@bp.route("/issuer-appeals/<issuer_appeal_id>/resolve", methods=["POST"])
@authed("CommitteeChair")
def resolve_appeal(actor, issuer_appeal_id):
    row = db.issuer_appeals.get(issuer_appeal_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    appeal = decision_service.resolve_appeal(
        row, payload.get("appeal_outcome"), payload.get("resolution_notes")
    )
    return ok(dom.issuer_appeal(appeal))


# ---------------------------------------------------------------------------
# Appearance reconciliations
# ---------------------------------------------------------------------------
@bp.route("/appearance-reconciliations", methods=["POST"])
@authed("ComplianceOfficer")
def create_reconciliation(actor):
    payload = body()
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    decision_id = payload.get("rating_decision_id")
    if decision_id is None or decision_id not in db.rating_decisions:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = reconciliation_service.create(
        analyst_id,
        decision_id,
        payload.get("stated_role"),
        payload.get("evidence_reference"),
    )
    return created(dom.appearance_reconciliation(row))


@bp.route("/appearance-reconciliations", methods=["GET"])
@authed("Any")
def list_reconciliations(actor):
    rows = apply_filters(
        list(db.appearance_reconciliations.values()),
        ("analyst_id", "rating_decision_id", "reconciliation_status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.appearance_reconciliation(r) for r in window], limit, offset, total)


@bp.route("/appearance-reconciliations/<appearance_reconciliation_id>", methods=["GET"])
@authed("Any")
def get_reconciliation(actor, appearance_reconciliation_id):
    row = db.appearance_reconciliations.get(appearance_reconciliation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.appearance_reconciliation(row))


@bp.route(
    "/appearance-reconciliations/<appearance_reconciliation_id>/confirm-breach",
    methods=["POST"],
)
@authed("CommitteeChair")
def confirm_reconciliation_breach(actor, appearance_reconciliation_id):
    row = db.appearance_reconciliations.get(appearance_reconciliation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.appearance_reconciliation(reconciliation_service.confirm_breach(row)))


@bp.route(
    "/appearance-reconciliations/<appearance_reconciliation_id>/appeal", methods=["POST"]
)
@authed("RatingAnalyst")
def appeal_reconciliation(actor, appearance_reconciliation_id):
    row = db.appearance_reconciliations.get(appearance_reconciliation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.appearance_reconciliation(reconciliation_service.appeal(row)))


@bp.route(
    "/appearance-reconciliations/<appearance_reconciliation_id>/clear", methods=["POST"]
)
@authed("CommitteeChair")
def clear_reconciliation(actor, appearance_reconciliation_id):
    row = db.appearance_reconciliations.get(appearance_reconciliation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.appearance_reconciliation(reconciliation_service.clear(row)))