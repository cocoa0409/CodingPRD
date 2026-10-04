"""Analytical team assignments and conflict screenings."""

from flask import Blueprint

from auth import authed
from db import base_row, db, now
import domain as dom
from errors import fail
from query import apply_filters, body, paginate
from response import created, listing, ok
from services import teams as team_service

bp = Blueprint("teams", __name__)


@bp.route("/team-assignments", methods=["POST"])
@authed("CommitteeChair")
def create_team_assignment(actor):
    payload = body()
    request_id = payload.get("rating_request_id")
    if request_id is None or request_id not in db.rating_requests:
        fail("ERR_RESOURCE_NOT_FOUND")
    lead_id = payload.get("lead_analyst_id")
    if lead_id is None or lead_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    support_id = payload.get("support_analyst_id")
    if support_id is None or support_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")

    row = team_service.create(
        request_id,
        lead_id,
        support_id,
        payload.get("window_start"),
        payload.get("window_end"),
        payload.get("rotation_exemption_granted"),
        payload.get("rotation_exemption_reason"),
    )
    return created(dom.team_assignment(row))


@bp.route("/team-assignments", methods=["GET"])
@authed("Any")
def list_team_assignments(actor):
    rows = apply_filters(
        list(db.team_assignments.values()),
        ("rating_request_id", "lead_analyst_id", "support_analyst_id", "status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.team_assignment(r) for r in window], limit, offset, total)


@bp.route("/team-assignments/<team_assignment_id>", methods=["GET"])
@authed("Any")
def get_team_assignment(actor, team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.team_assignment(row))


@bp.route("/team-assignments/<team_assignment_id>/screenings", methods=["GET"])
@authed("Any")
def list_team_screenings(actor, team_assignment_id):
    if team_assignment_id not in db.team_assignments:
        fail("ERR_RESOURCE_NOT_FOUND")
    rows = [r for r in db.conflict_screenings.values() if r["team_assignment_id"] == team_assignment_id]
    window, limit, offset, total = paginate(rows)
    return listing([dom.conflict_screening(r) for r in window], limit, offset, total)


@bp.route("/team-assignments/<team_assignment_id>/screen", methods=["POST"])
@authed("ComplianceOfficer")
def screen_team_assignment(actor, team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.team_assignment(team_service.screen(row)))


@bp.route("/team-assignments/<team_assignment_id>/return-to-proposed", methods=["POST"])
@authed("ComplianceOfficer")
def return_team_assignment(actor, team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.team_assignment(team_service.return_to_proposed(row)))


@bp.route("/team-assignments/<team_assignment_id>/confirm", methods=["POST"])
@authed("CommitteeChair")
def confirm_team_assignment(actor, team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    version = payload.get("expected_rating_request_version")
    return ok(dom.team_assignment(team_service.confirm(row, version)))


@bp.route("/team-assignments/<team_assignment_id>/revoke", methods=["POST"])
@authed("ComplianceOfficer")
def revoke_team_assignment(actor, team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    return ok(
        dom.team_assignment(team_service.revoke(row, payload.get("revocation_reason")))
    )


# ---------------------------------------------------------------------------
# Conflict screenings
# ---------------------------------------------------------------------------
@bp.route("/conflict-screenings", methods=["POST"])
@authed("ComplianceOfficer")
def create_conflict_screening(actor):
    payload = body()
    assignment_id = payload.get("team_assignment_id")
    if assignment_id is None or assignment_id not in db.team_assignments:
        fail("ERR_RESOURCE_NOT_FOUND")
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")

    row = base_row(common=False)
    row.update(
        {
            "team_assignment_id": assignment_id,
            "analyst_id": analyst_id,
            "conflict_type": payload.get("conflict_type"),
            "screening_result": payload.get("screening_result"),
            "reviewer_user_id": actor.user_id,
            "screened_at": now(),
        }
    )
    db.conflict_screenings[row["id"]] = row
    return created(dom.conflict_screening(row))


@bp.route("/conflict-screenings", methods=["GET"])
@authed("Any")
def list_conflict_screenings(actor):
    rows = apply_filters(
        list(db.conflict_screenings.values()),
        ("team_assignment_id", "analyst_id", "screening_result"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.conflict_screening(r) for r in window], limit, offset, total)