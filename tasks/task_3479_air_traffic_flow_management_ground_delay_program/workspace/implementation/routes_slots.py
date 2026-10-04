"""ArrivalSlot listing and the append-only SlotTransaction log (PRD 3.4)."""

from flask import Blueprint, request

from allocation import slots_of
from constants import ROLES
from errors import ApiError
from serialize import serialize_slot, serialize_transaction
from storage import DB
from util import paginate
from validation import auth_context, get_tmi, require_roles

bp = Blueprint("slots", __name__)


@bp.route("/atfm/tmis/<tmi_id>/slots", methods=["GET"])
def list_tmi_slots(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    # Slot listings are meaningful only for a GROUND_DELAY_PROGRAM.
    if tmi["tmi_type"] != "GROUND_DELAY_PROGRAM":
        raise ApiError(
            "ERR_TMI_TYPE_NOT_GDP",
            "slot listing is only available on a GROUND_DELAY_PROGRAM",
        )
    status_filter = request.args.get("status")
    rows = [
        s
        for s in slots_of(tmi["id"])
        if status_filter is None or s["status"] == status_filter
    ]
    return paginate([serialize_slot(s) for s in rows])


@bp.route("/atfm/tmis/<tmi_id>/slot-transactions", methods=["GET"])
def list_slot_transactions(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    type_filter = request.args.get("transaction_type")
    rows = [
        t
        for t in DB["transactions"].values()
        if t["tmi_id"] == tmi["id"]
        and (type_filter is None or t["transaction_type"] == type_filter)
    ]
    # Chronological (created_at ASC) order.
    rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return paginate([serialize_transaction(t) for t in rows])
