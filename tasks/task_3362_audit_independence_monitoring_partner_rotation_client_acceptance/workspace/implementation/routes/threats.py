"""Personal independence threats: declarations and remediation actions."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_THREAT_NOT_FOUND,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.independence import sweep_cooling_off
from services.threats import apply_threat_action, create_threat_row

bp = Blueprint("threats", __name__)

CREATE_FIELDS = ("professional_id", "client_id", "threat_type", "instrument_type",
                 "relationship_type", "value_cents", "effective_on")
ACTIONS = ("DIVEST", "MITIGATE", "CONFIRM_CLEARANCE")


@bp.route("/independence-threats", methods=["POST"])
def create_threat():
    payload = body(CREATE_FIELDS)
    professional_id = V.string(payload, "professional_id", required=True)
    client_id = V.string(payload, "client_id", required=True)
    threat_type = V.enum(payload, "threat_type", C.THREAT_TYPES, required=True)
    instrument_type = V.enum(payload, "instrument_type", C.INSTRUMENT_TYPES,
                             default=None, nullable=True)
    relationship_type = V.enum(payload, "relationship_type", C.RELATIONSHIP_TYPES,
                               default=None, nullable=True)
    value_cents = V.number(payload, "value_cents", default=0, minimum=0)
    effective_on = V.datetime_field(payload, "effective_on", required=True)
    require_role([C.ROLE_INDEPENDENCE_OFFICER])
    if store.professionals.get(professional_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "professional_id does not resolve to an existing professional.")
    if store.clients.get(client_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "client_id does not resolve to an existing client.")
    if threat_type == "FINANCIAL_INTEREST":
        relationship_type = None
    else:
        instrument_type = None
        value_cents = 0
    row = create_threat_row(professional_id, client_id, threat_type, instrument_type,
                            relationship_type, value_cents, effective_on)
    return send(serialize("threat", row), 201)


@bp.route("/independence-threats", methods=["GET"])
def list_threats():
    require_role(C.READ_ALL_ROLES)
    sweep_cooling_off()
    rows = filter_rows(all_rows("threats"), {
        "professional_id": "professional_id",
        "client_id": "client_id",
        "threat_type": "threat_type",
        "status": "status",
        "is_material": "is_material",
    })
    return list_response(rows, lambda row: serialize("threat", row))


@bp.route("/independence-threats/<threat_id>", methods=["GET"])
def get_threat(threat_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("threats", threat_id, ERR_THREAT_NOT_FOUND)
    sweep_cooling_off()
    return send(serialize("threat", row))


@bp.route("/independence-threats/<threat_id>/transitions", methods=["POST"])
def transition_threat(threat_id):
    payload = body(("action",))
    action = V.string(payload, "action", required=True)
    if action not in ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    require_role([C.ROLE_INDEPENDENCE_OFFICER])
    row = fetch("threats", threat_id, ERR_THREAT_NOT_FOUND)
    apply_threat_action(row, action)
    return send(serialize("threat", row))
