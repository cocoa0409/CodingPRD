"""Explicit disclosures and the disclosure audit log (PRD 2.9 and 3.9)."""

from flask import Blueprint

import constants
import serializers
from domain import cascades
from errors import ApiError, ERR_DISCLOSURE_FORBIDDEN
from helpers import (
    authenticate,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
)
from store import db
from validation import req_enum, req_string
from routes.charges import get_charge_or_404

bp = Blueprint("disclosures", __name__, url_prefix="/eeoc")

_LIST_ROLES = (
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_INTAKE_OFFICER,
)


@bp.post("/charges/<charge_id>/disclosures")
def create_disclosure(charge_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_DIRECTOR,))
    # Schema: INTERNAL_ACCESS is never client-supplied.
    body = request_body()
    legal_basis = req_enum(
        body, "legal_basis", constants.DISCLOSURE_CLIENT_BASES
    )
    target_description = req_string(body, "target_description")

    charge = get_charge_or_404(charge_id)

    # On a SEALED charge only COURT_ORDER is permitted.
    if (
        charge["disclosure_hold"] == constants.HOLD_SEALED
        and legal_basis != constants.DISCLOSURE_COURT_ORDER
    ):
        raise ApiError(
            ERR_DISCLOSURE_FORBIDDEN,
            "On a SEALED charge only COURT_ORDER disclosures are permitted.",
        )

    record = cascades.record_disclosure(
        charge,
        accessor_role=role,
        accessor_user_id=user_id,
        legal_basis=legal_basis,
        target_description=target_description,
    )
    return respond_object(
        serializers.serialize_disclosure_record(record), status=201
    )


@bp.get("/charges/<charge_id>/disclosures")
def list_disclosures(charge_id):
    _, role = authenticate()
    require_roles(role, _LIST_ROLES)
    charge = get_charge_or_404(charge_id)
    rows = [
        r
        for r in db.disclosure_records.values()
        if r["charge_id"] == charge["id"]
    ]
    return paginate_and_respond(rows, serializers.serialize_disclosure_record)
