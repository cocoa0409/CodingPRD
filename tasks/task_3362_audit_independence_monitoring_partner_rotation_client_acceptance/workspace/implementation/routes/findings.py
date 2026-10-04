"""Independence findings: the OCC-guarded raise and the remediation lifecycle."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_FINDING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_STALE_VERSION,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.findings import apply_finding_action, cascade_finding_posture, create_finding_row
from services.independence import sweep_cooling_off

bp = Blueprint("findings", __name__)

CREATE_FIELDS = ("professional_id", "engagement_id", "origin", "origin_ref_id",
                 "finding_type", "severity", "discovered_on", "expected_engagement_version")
ACTIONS = ("START_REMEDIATION", "CLOSE_NO_ACTION", "SUBMIT_FOR_RETEST",
           "PASS_RETEST", "FAIL_RETEST", "RESTART_REMEDIATION")


@bp.route("/independence-findings", methods=["POST"])
def create_finding():
    payload = body(CREATE_FIELDS)
    professional_id = V.string(payload, "professional_id", required=True)
    engagement_id = V.string(payload, "engagement_id", required=True)
    origin = V.enum(payload, "origin", C.FINDING_ORIGINS, required=True)
    origin_ref_id = V.string(payload, "origin_ref_id", required=True)
    finding_type = V.enum(payload, "finding_type", C.FINDING_TYPES, required=True)
    severity = V.enum(payload, "severity", C.SEVERITIES, required=True)
    discovered_on = V.datetime_field(payload, "discovered_on", required=True)
    expected_version = V.integer(payload, "expected_engagement_version", required=True)
    require_role([C.ROLE_INDEPENDENCE_OFFICER])
    if store.professionals.get(professional_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "professional_id does not resolve to an existing professional.")
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    if engagement.get("status") not in C.STAFFABLE_ENGAGEMENT_STATUSES:
        raise ApiError(ERR_INVALID_STATE,
                       "The engagement's status does not admit new findings.")
    if expected_version != engagement.get("version"):
        raise ApiError(ERR_STALE_VERSION,
                       "expected_engagement_version does not match the engagement's current version.")
    row = create_finding_row(professional_id, engagement_id, origin, origin_ref_id,
                             finding_type, severity, discovered_on)
    cascade_finding_posture(row, force_engagement=True)
    return send(serialize("finding", row), 201)


@bp.route("/independence-findings", methods=["GET"])
def list_findings():
    require_role(C.READ_ALL_ROLES)
    sweep_cooling_off()
    rows = filter_rows(all_rows("findings"), {
        "professional_id": "professional_id",
        "engagement_id": "engagement_id",
        "status": "status",
        "severity": "severity",
        "finding_type": "finding_type",
        "origin": "origin",
    })
    return list_response(rows, lambda row: serialize("finding", row))


@bp.route("/independence-findings/<finding_id>", methods=["GET"])
def get_finding(finding_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("findings", finding_id, ERR_FINDING_NOT_FOUND)
    return send(serialize("finding", row))


@bp.route("/independence-findings/<finding_id>/transitions", methods=["POST"])
def transition_finding(finding_id):
    payload = body(("action",))
    action = V.string(payload, "action", required=True)
    if action not in ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    require_role([C.ROLE_INDEPENDENCE_OFFICER])
    row = fetch("findings", finding_id, ERR_FINDING_NOT_FOUND)
    apply_finding_action(row, action)
    return send(serialize("finding", row))
