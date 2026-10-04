"""Quality control reviews and regulatory inspection responses."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
    ERR_REVIEW_WINDOW_CONFLICT,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services import calc
from services.reviews import apply_review_action, create_review_row

bp = Blueprint("reviews", __name__)

CREATE_FIELDS = ("engagement_id", "reviewer_id", "review_type", "inspection_body",
                 "received_on", "due_on", "deficiency_count", "remediation_plan_ref")
ACTIONS = ("START", "PASS", "FAIL", "REMEDIATE", "REOPEN")


@bp.route("/quality-reviews", methods=["POST"])
def create_review():
    payload = body(CREATE_FIELDS)
    engagement_id = V.string(payload, "engagement_id", required=True)
    reviewer_id = V.string(payload, "reviewer_id", required=True)
    review_type = V.enum(payload, "review_type", C.REVIEW_TYPES, required=True)
    inspection_body = V.enum(payload, "inspection_body", C.INSPECTION_BODIES,
                             default=None, nullable=True)
    received_on = V.datetime_field(payload, "received_on", required=True)
    due_on = V.datetime_field(payload, "due_on", required=True)
    deficiency_count = V.integer(payload, "deficiency_count", default=0, minimum=0)
    remediation_plan_ref = V.string(payload, "remediation_plan_ref", default=None, nullable=True)
    require_role([C.ROLE_QUALITY_REVIEWER])
    if store.engagements.get(engagement_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    if store.professionals.get(reviewer_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "reviewer_id does not resolve to an existing professional.")
    peers = [
        row for row in all_rows("reviews")
        if row.get("reviewer_id") == reviewer_id and row.get("review_type") == review_type
    ]
    if calc.review_buffer_conflict(received_on, due_on, peers):
        raise ApiError(ERR_REVIEW_WINDOW_CONFLICT,
                       "The review window falls inside the mandatory reviewer buffer.")
    row = create_review_row(engagement_id, reviewer_id, review_type, inspection_body,
                            received_on, due_on, deficiency_count, remediation_plan_ref)
    return send(serialize("review", row), 201)


@bp.route("/quality-reviews", methods=["GET"])
def list_reviews():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("reviews"), {
        "engagement_id": "engagement_id",
        "reviewer_id": "reviewer_id",
        "status": "status",
        "review_type": "review_type",
    })
    return list_response(rows, lambda row: serialize("review", row))


@bp.route("/quality-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("reviews", review_id, ERR_REVIEW_NOT_FOUND)
    return send(serialize("review", row))


@bp.route("/quality-reviews/<review_id>/transitions", methods=["POST"])
def transition_review(review_id):
    payload = body(("action",))
    action = V.string(payload, "action", required=True)
    if action not in ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    require_role([C.ROLE_QUALITY_REVIEWER])
    row = fetch("reviews", review_id, ERR_REVIEW_NOT_FOUND)
    apply_review_action(row, action)
    return send(serialize("review", row))
