"""Illness investigations: the scoped traceback, the four-hop recall cascade
on confirmation, and closing unsubstantiated (PRD 3.9).
"""

from flask import Blueprint

import calc
import serializers as ser
from cascades import recall_cascade
from core import (
    ROLE_AUTHORITY,
    SCOPE_VARIANTS,
    apply_changes,
    authenticate,
    clock,
    envelope_object,
    f_enum,
    f_instant,
    f_str,
    get_investigation,
    json_body,
)
from errors import ApiError

bp = Blueprint("investigations", __name__)


@bp.route("/illness-investigations/<investigation_id>", methods=["GET"])
def read_investigation(investigation_id):
    authenticate([ROLE_AUTHORITY])
    investigation = get_investigation(investigation_id)
    return envelope_object(ser.investigation(investigation)), 200


@bp.route("/illness-investigations/<investigation_id>/traceback", methods=["POST"])
def run_traceback(investigation_id):
    authenticate([ROLE_AUTHORITY])
    investigation = get_investigation(investigation_id)
    body = json_body()
    scope_variant = f_enum(body, "scope_variant", SCOPE_VARIANTS)

    # Rung 7 — the traceback runs from OPEN or, re-scoped, from TRACEBACK.
    if investigation["status"] not in ("OPEN", "TRACEBACK"):
        raise ApiError("ERR_INVALID_INVESTIGATION_STATE")

    traced = calc.traceback_lots(investigation, scope_variant)
    traced_ids = [lot["id"] for lot in traced]
    apply_changes(
        investigation,
        {
            "scope_variant": scope_variant,
            "status": "TRACEBACK",
            "traced_lot_ids": traced_ids,
            "traced_lot_count": len(traced_ids),
        },
    )
    return envelope_object(ser.investigation(investigation)), 200


@bp.route("/illness-investigations/<investigation_id>/confirm", methods=["POST"])
def confirm_investigation(investigation_id):
    authenticate([ROLE_AUTHORITY])
    investigation = get_investigation(investigation_id)
    body = json_body()
    confirmed_at = f_instant(body, "confirmed_at", required=False, default=None)

    # Rung 7 — only a traced investigation may be confirmed, and only when the
    # traceback actually found something to recall.
    if investigation["status"] != "TRACEBACK":
        raise ApiError("ERR_INVALID_INVESTIGATION_STATE")
    if investigation["traced_lot_count"] < 1:
        raise ApiError("ERR_INVALID_INVESTIGATION_STATE")

    moment = confirmed_at if confirmed_at is not None else clock.now()
    traced_lot_ids = list(investigation["traced_lot_ids"])
    apply_changes(
        investigation, {"status": "CONFIRMED", "confirmed_at": moment}
    )
    recalled = recall_cascade(investigation, traced_lot_ids)
    apply_changes(investigation, {"recalled_shipment_count": recalled})
    return envelope_object(ser.investigation(investigation)), 200


@bp.route("/illness-investigations/<investigation_id>/close", methods=["POST"])
def close_investigation(investigation_id):
    authenticate([ROLE_AUTHORITY])
    investigation = get_investigation(investigation_id)
    body = json_body()
    f_str(body, "close_note", required=False, default=None)

    # Rung 7 — an already-decided investigation is terminal.
    if investigation["status"] not in ("OPEN", "TRACEBACK"):
        raise ApiError("ERR_INVALID_INVESTIGATION_STATE")

    # The traceback documentation is deliberately retained.
    apply_changes(investigation, {"status": "CLOSED_UNSUBSTANTIATED"})
    return envelope_object(ser.investigation(investigation)), 200
