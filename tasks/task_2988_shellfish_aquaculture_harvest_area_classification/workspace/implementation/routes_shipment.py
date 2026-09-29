"""Shipments: assembly from tagged lots, release from the dock, and the
illness investigations opened against a consignment (PRD 3.9).
"""

from flask import Blueprint

import calc
import serializers as ser
from core import (
    INVESTIGATION_STATUSES,
    PATHOGENS,
    ROLE_AUTHORITY,
    ROLE_DEALER,
    SHIPMENT_STATUSES,
    acting_user,
    apply_changes,
    at_or_after_today,
    authenticate,
    body_ref,
    check_not_future_instant,
    db,
    envelope_array,
    envelope_object,
    f_instant,
    f_int,
    f_enum,
    f_str,
    f_str_list,
    get_dealer,
    get_shipment,
    json_body,
    pagination,
    paginate,
    q_bool,
    q_enum,
    q_str,
    sort_default,
    sort_journal,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("shipments", __name__)

SHIPMENT_READ_ROLES = [ROLE_AUTHORITY, ROLE_DEALER]
INVESTIGABLE_SHIPMENT_STATUSES = ("CREATED", "SHIPPED", "HELD")


@bp.route("/shipments", methods=["POST"])
def assemble_shipment():
    authenticate([ROLE_DEALER])
    body = json_body()
    # Rung 3 — the dealer, then every member of the lot roster.
    dealer = get_dealer(body_ref(body, "dealer_id", "ERR_DEALER_NOT_FOUND"))
    lot_ids = f_str_list(body, "lot_ids", min_items=1, max_items=25)
    lots = []
    for lot_id in lot_ids:
        lot = db.harvest_lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_HARVEST_LOT_NOT_FOUND")
        lots.append(lot)
    # Rung 4 — the acting identity IS a dealer identifier.
    if dealer["id"] != acting_user():
        raise ApiError("ERR_DEALER_OWNERSHIP_VIOLATION")
    # Rung 5 — the rest of the shape.
    destination_state = f_str(
        body, "destination_state", pattern=r"^[A-Z]{2}$", min_len=2, max_len=2
    )
    carrier = f_str(body, "carrier")

    # Rung 13 — dealer standing and roster coherence, in the declared order.
    if not at_or_after_today(dealer["certified_through"]):
        raise ApiError("ERR_DEALER_CERTIFICATION_EXPIRED")
    for lot in lots:
        if lot["status"] != "TAGGED":
            raise ApiError("ERR_LOT_NOT_TAGGED")
    for lot in lots:
        if lot["dealer_id"] != dealer["id"] or lot["shipment_id"] is not None:
            raise ApiError("ERR_LOT_DEALER_MISMATCH")
    if dealer["listing_status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED")

    total_bushels = 0
    for lot in lots:
        total_bushels += lot["bushels"]
    shipment = {
        "dealer_id": dealer["id"],
        "destination_state": destination_state,
        "carrier": carrier,
        "lot_ids": list(lot_ids),
        "lot_count": len(lot_ids),
        "total_bushels": total_bushels,
        "is_interstate": destination_state != dealer["state_code"],
        "status": "CREATED",
        "shipped_at": None,
        "held_reason": None,
        "recall_reason": None,
    }
    stamp_new(shipment)
    db.shipments[shipment["id"]] = shipment
    for lot in lots:
        apply_changes(lot, {"shipment_id": shipment["id"]})
    return envelope_object(ser.shipment(shipment)), 201


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def read_shipment(shipment_id):
    authenticate(SHIPMENT_READ_ROLES)
    shipment = get_shipment(shipment_id)
    return envelope_object(ser.shipment(shipment)), 200


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    authenticate(SHIPMENT_READ_ROLES)
    limit, offset = pagination()
    dealer_id = q_str("dealer_id")
    status = q_enum("status", SHIPMENT_STATUSES)
    is_interstate = q_bool("is_interstate")
    rows = []
    for shipment in db.shipments.values():
        if dealer_id is not None and shipment["dealer_id"] != dealer_id:
            continue
        if status is not None and shipment["status"] != status:
            continue
        if is_interstate is not None and shipment["is_interstate"] != is_interstate:
            continue
        rows.append(shipment)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array([ser.shipment(r) for r in page], limit, offset, total), 200


@bp.route("/shipments/<shipment_id>/ship", methods=["POST"])
def ship_shipment(shipment_id):
    authenticate([ROLE_DEALER])
    shipment = get_shipment(shipment_id)
    # Rung 4 — only the consigning dealer releases the shipment.
    if shipment["dealer_id"] != acting_user():
        raise ApiError("ERR_DEALER_OWNERSHIP_VIOLATION")
    body = json_body()
    shipped_at = f_instant(body, "shipped_at")

    # Rung 7 — the shipment state, then the cold-chain ordering.
    if shipment["status"] != "CREATED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    lots = []
    for lot_id in shipment["lot_ids"]:
        lot = db.harvest_lots.get(lot_id)
        if lot is not None:
            lots.append(lot)
    coldest = None
    for lot in lots:
        moment = lot["placed_in_temperature_control_at"]
        if moment is not None and (coldest is None or moment > coldest):
            coldest = moment
    if coldest is not None and shipped_at.replace(microsecond=0) < coldest.replace(
        microsecond=0
    ):
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    # Rung 10 — nothing future-dated.
    check_not_future_instant(shipped_at)
    # Rung 13 — the dealer's standing, then the roster.
    dealer = db.dealers.get(shipment["dealer_id"])
    if dealer is not None:
        if not at_or_after_today(dealer["certified_through"]):
            raise ApiError("ERR_DEALER_CERTIFICATION_EXPIRED")
        # The interstate window only refines a *current* listing, so the two
        # listing-standing grounds are answered first: a NOT_LISTED dealer is
        # refused with ERR_DEALER_NOT_LISTED (PRD 3.9).
        if dealer["listing_status"] == "SUSPENDED":
            raise ApiError("ERR_DEALER_SUSPENDED")
        if dealer["listing_status"] != "LISTED":
            raise ApiError("ERR_DEALER_NOT_LISTED")
        if shipment["is_interstate"] and not at_or_after_today(
            dealer["icssl_listed_through"]
        ):
            raise ApiError("ERR_DEALER_NOT_LISTED_FOR_INTERSTATE")
    for lot in lots:
        if lot["status"] != "TAGGED":
            raise ApiError("ERR_LOT_NOT_TAGGED")

    apply_changes(shipment, {"status": "SHIPPED", "shipped_at": shipped_at})
    for lot in lots:
        if lot["status"] == "TAGGED":
            apply_changes(lot, {"status": "SHIPPED"})
    return envelope_object(ser.shipment(shipment)), 200


# --------------------------------------------------------------------------
# Illness investigations opened against this shipment
# --------------------------------------------------------------------------
@bp.route("/shipments/<shipment_id>/illness-investigations", methods=["POST"])
def open_investigation(shipment_id):
    authenticate([ROLE_AUTHORITY])
    shipment = get_shipment(shipment_id)
    body = json_body()
    reported_at = f_instant(body, "reported_at")
    illness_count = f_int(body, "illness_count", minimum=1)
    pathogen = f_enum(body, "pathogen", PATHOGENS)

    # Rung 7 — a recalled consignment is already dealt with.
    if shipment["status"] not in INVESTIGABLE_SHIPMENT_STATUSES:
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    # Rung 10 — nothing future-dated.
    check_not_future_instant(reported_at)

    investigation = {
        "source_shipment_id": shipment["id"],
        "reported_at": reported_at,
        "illness_count": illness_count,
        "pathogen": pathogen,
        "scope_variant": None,
        "status": "OPEN",
        "traced_lot_ids": [],
        "traced_lot_count": 0,
        "recalled_shipment_count": 0,
        "confirmed_at": None,
    }
    stamp_new(investigation)
    db.investigations[investigation["id"]] = investigation
    return envelope_object(ser.investigation(investigation)), 201


@bp.route("/shipments/<shipment_id>/illness-investigations", methods=["GET"])
def list_shipment_investigations(shipment_id):
    authenticate([ROLE_AUTHORITY])
    shipment = get_shipment(shipment_id)
    limit, offset = pagination()
    status = q_enum("status", INVESTIGATION_STATUSES)
    rows = []
    for investigation in db.investigations.values():
        if investigation["source_shipment_id"] != shipment["id"]:
            continue
        if status is not None and investigation["status"] != status:
            continue
        rows.append(investigation)
    rows = sort_journal(rows, "reported_at", True)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.investigation(r) for r in page], limit, offset, total
    ), 200
