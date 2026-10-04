"""Engagements: creation, reads, the independence roll-up and manual actions."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.independence import (
    commit_engagement,
    posture_counts,
    recompute_engagement,
    refresh_engagement_derived,
    sweep_cooling_off,
)
from services.lifecycle import apply_engagement_action, create_engagement_row

bp = Blueprint("engagements", __name__)

ENGAGEMENT_ACTIONS = ("SUSPEND", "RESUME", "CLOSE")
CREATE_FIELDS = ("client_id", "engagement_type", "fiscal_year_end", "is_multinational")
TRANSITION_FIELDS = ("action",)


def refresh_engagement(engagement):
    recompute_engagement(engagement)
    commit_engagement(engagement)
    refresh_engagement_derived(engagement)
    return engagement


@bp.route("/engagements", methods=["POST"])
def create_engagement():
    payload = body(CREATE_FIELDS)
    client_id = V.string(payload, "client_id", required=True)
    engagement_type = V.enum(payload, "engagement_type", C.ENGAGEMENT_TYPES, required=True)
    fiscal_year_end = V.datetime_field(payload, "fiscal_year_end", required=True)
    is_multinational = V.boolean(payload, "is_multinational", False)
    require_role([C.ROLE_ENGAGEMENT_PARTNER])
    client = store.clients.get(client_id)
    if client is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "client_id does not resolve to an existing client.")
    row = create_engagement_row(client, engagement_type, fiscal_year_end, is_multinational)
    return send(serialize("engagement", row), 201)


@bp.route("/engagements", methods=["GET"])
def list_engagements():
    require_role(C.READ_ALL_ROLES)
    sweep_cooling_off()
    for row in all_rows("engagements"):
        refresh_engagement(row)
    rows = filter_rows(all_rows("engagements"), {
        "client_id": "client_id",
        "lead_partner_id": "lead_partner_id",
        "concurring_partner_id": "concurring_partner_id",
        "status": "status",
        "independence_status": "independence_status",
        "risk_tier": "risk_tier",
    })
    return list_response(rows, lambda row: serialize("engagement", row))


@bp.route("/engagements/<engagement_id>", methods=["GET"])
def get_engagement(engagement_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("engagements", engagement_id, ERR_ENGAGEMENT_NOT_FOUND)
    sweep_cooling_off()
    refresh_engagement(row)
    return send(serialize("engagement", row))


@bp.route("/engagements/<engagement_id>/independence-summary", methods=["GET"])
def independence_summary(engagement_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("engagements", engagement_id, ERR_ENGAGEMENT_NOT_FOUND)
    sweep_cooling_off()
    counts = recompute_engagement(row)
    commit_engagement(row)
    payload = {"engagement_id": row.get("id"), "independence_status": row.get("independence_status")}
    payload.update(counts)
    return send(payload)


@bp.route("/engagements/<engagement_id>/transitions", methods=["POST"])
def transition_engagement(engagement_id):
    payload = body(TRANSITION_FIELDS)
    action = V.string(payload, "action", required=True)
    if action not in ENGAGEMENT_ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    require_role([C.ROLE_ENGAGEMENT_PARTNER])
    row = fetch("engagements", engagement_id, ERR_ENGAGEMENT_NOT_FOUND)
    apply_engagement_action(row, action)
    return send(serialize("engagement", row))
