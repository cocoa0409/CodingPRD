"""Client acceptance evaluations, integrity evidence and committee decisions."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.clock import now as clock_now
from core.db import all_rows, new_row, store
from core.errors import (
    ERR_ACCEPTANCE_NOT_FOUND,
    ERR_ASSESSMENT_DATE_IN_FUTURE,
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.lifecycle import (
    apply_acceptance_decision,
    create_acceptance_row,
    refresh_acceptance_scores,
    submit_acceptance,
)

bp = Blueprint("acceptances", __name__)

CREATE_FIELDS = ("client_id", "engagement_id", "proposed_by",
                 "industry_expertise_required", "industry_expertise_confirmed")
DECISION_FIELDS = ("decision", "decision_notes")
ASSESSMENT_FIELDS = ("source_type", "severity", "score_impact", "assessed_on", "resolved")
DECISIONS = ("APPROVE", "RETURN", "CONDITIONAL", "REJECT", "WITHDRAW")


@bp.route("/client-acceptances", methods=["POST"])
def create_acceptance():
    payload = body(CREATE_FIELDS)
    client_id = V.string(payload, "client_id", required=True)
    engagement_id = V.string(payload, "engagement_id", required=True)
    proposed_by = V.string(payload, "proposed_by", required=True)
    expertise = V.enum(payload, "industry_expertise_required", C.INDUSTRY_CODES, required=True)
    confirmed = V.boolean(payload, "industry_expertise_confirmed", False)
    require_role([C.ROLE_ACCEPTANCE_COMMITTEE])
    client = store.clients.get(client_id)
    if client is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "client_id does not resolve to an existing client.")
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    row = create_acceptance_row(client, engagement, proposed_by, expertise, confirmed)
    return send(serialize("acceptance", row), 201)


@bp.route("/client-acceptances", methods=["GET"])
def list_acceptances():
    require_role(C.READ_ALL_ROLES)
    for row in all_rows("acceptances"):
        refresh_acceptance_scores(row)
    rows = filter_rows(all_rows("acceptances"), {
        "client_id": "client_id",
        "engagement_id": "engagement_id",
        "status": "status",
    })
    return list_response(rows, lambda row: serialize("acceptance", row))


@bp.route("/client-acceptances/<acceptance_id>", methods=["GET"])
def get_acceptance(acceptance_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("acceptances", acceptance_id, ERR_ACCEPTANCE_NOT_FOUND)
    refresh_acceptance_scores(row)
    return send(serialize("acceptance", row))


@bp.route("/client-acceptances/<acceptance_id>/submit", methods=["POST"])
def submit(acceptance_id):
    body(())
    require_role([C.ROLE_ACCEPTANCE_COMMITTEE])
    row = fetch("acceptances", acceptance_id, ERR_ACCEPTANCE_NOT_FOUND)
    submit_acceptance(row)
    return send(serialize("acceptance", row))


@bp.route("/client-acceptances/<acceptance_id>/decision", methods=["POST"])
def decide(acceptance_id):
    payload = body(DECISION_FIELDS)
    decision = V.enum(payload, "decision", DECISIONS, required=True)
    decision_notes = V.string(payload, "decision_notes", default=None, nullable=True)
    require_role([C.ROLE_ACCEPTANCE_COMMITTEE])
    row = fetch("acceptances", acceptance_id, ERR_ACCEPTANCE_NOT_FOUND)
    apply_acceptance_decision(row, decision, decision_notes)
    return send(serialize("acceptance", row))


@bp.route("/client-acceptances/<acceptance_id>/integrity-assessments", methods=["POST"])
def create_assessment(acceptance_id):
    payload = body(ASSESSMENT_FIELDS)
    source_type = V.enum(payload, "source_type", C.INTEGRITY_SOURCE_TYPES, required=True)
    severity = V.enum(payload, "severity", C.SEVERITIES, required=True)
    score_impact = V.integer(payload, "score_impact", required=True, minimum=0, maximum=40)
    assessed_on = V.datetime_field(payload, "assessed_on", required=True)
    resolved = V.boolean(payload, "resolved", False)
    require_role([C.ROLE_ACCEPTANCE_COMMITTEE])
    acceptance = fetch("acceptances", acceptance_id, ERR_ACCEPTANCE_NOT_FOUND)
    if assessed_on > clock_now():
        raise ApiError(ERR_ASSESSMENT_DATE_IN_FUTURE,
                       "assessed_on must not be later than the logical clock.")
    row = new_row("assessments", {
        "acceptance_id": acceptance.get("id"),
        "source_type": source_type,
        "severity": severity,
        "score_impact": int(score_impact),
        "assessed_on": assessed_on,
        "resolved": resolved,
    })
    refresh_acceptance_scores(acceptance, touch_row=True)
    return send(serialize("assessment", row), 201)


@bp.route("/client-acceptances/<acceptance_id>/integrity-assessments", methods=["GET"])
def list_assessments(acceptance_id):
    require_role(C.READ_ALL_ROLES)
    fetch("acceptances", acceptance_id, ERR_ACCEPTANCE_NOT_FOUND)
    rows = [
        row for row in all_rows("assessments")
        if row.get("acceptance_id") == acceptance_id
    ]
    return list_response(rows, lambda row: serialize("assessment", row))
