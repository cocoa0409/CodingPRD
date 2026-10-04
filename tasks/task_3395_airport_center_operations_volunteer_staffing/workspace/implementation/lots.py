"""Donation lot endpoints (PRD 3.6): intake with partner match, FEFO consume."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from constants import LOT_CATEGORIES, MATCH_PCT
from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_center,
    get_lot,
    opt_str,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    today,
    validation,
)
from services import date_from_str
from storage import STORE

bp = Blueprint("lots", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")


@bp.route("/centers/<cid>/donation-lots", methods=["POST"])
def intake_lot(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    item_name = req_str(b, "item_name")
    category = req_enum(b, "category", LOT_CATEGORIES)
    received_qty = req_int(b, "received_qty", minimum=1)
    expiry = req_date(b, "expiry_date")
    if expiry < today():
        validation("expiry_date must not be earlier than the current date")
    declared = req_int(b, "declared_value_cents", minimum=0)
    partner_name = opt_str(b, "partner_name")
    center = get_center(cid)

    if partner_name is not None:
        match = int(
            (Decimal(declared) * Decimal(MATCH_PCT)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        match = 0

    lot = base_entity()
    lot.update({
        "center_id": center["id"],
        "item_name": item_name,
        "category": category,
        "received_qty": received_qty,
        "remaining_qty": received_qty,
        "expiry_date": expiry.isoformat(),
        "declared_value_cents": declared,
        "partner_name": partner_name,
        "partner_match_cents": match,
        "status": "AVAILABLE",
    })
    STORE.lots[lot["id"]] = lot
    return success_object(serialize(lot), status=201)


@bp.route("/centers/<cid>/donation-lots", methods=["GET"])
def list_lots(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    items = [l for l in STORE.lots.values() if l["center_id"] == center["id"]]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/donation-lots/<lid>/consume", methods=["POST"])
def consume_lot(lid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    quantity = req_int(b, "quantity", minimum=1)
    lot = get_lot(lid)

    if lot["status"] != "AVAILABLE":
        err("ERR_INVALID_STATE", 409, "Lot is not AVAILABLE")

    d = today()
    candidates = [
        l for l in STORE.lots.values()
        if l["center_id"] == lot["center_id"]
        and l["status"] == "AVAILABLE"
        and l["remaining_qty"] > 0
        and date_from_str(l["expiry_date"]) >= d
    ]
    if not candidates:
        if date_from_str(lot["expiry_date"]) < d:
            err("ERR_LOT_EXPIRED", 409, "Lot is expired")
        err("ERR_INVALID_STATE", 409, "No consumable lot available")

    head = min(candidates, key=lambda l: (l["expiry_date"], l["created_at"], l["_seq"]))
    if head["id"] != lot["id"]:
        err("ERR_FEFO_VIOLATION", 409, "Lot is not the first-expiry-first-out head")

    if quantity > lot["remaining_qty"]:
        err("ERR_INSUFFICIENT_QUANTITY", 409, "Quantity exceeds remaining stock")

    lot["remaining_qty"] -= quantity
    if lot["remaining_qty"] == 0:
        lot["status"] = "DEPLETED"
    bump(lot)
    return success_object(serialize(lot))
