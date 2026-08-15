"""TransportShipment tendering and carrier lifecycle (§3.8): DRAFT ->
TENDERED -> CARRIER_ACCEPTED -> IN_TRANSIT -> DELIVERED, with the carrier
rejection re-tender loop and per-pack logistics cascades."""

from decimal import Decimal

from flask import Blueprint

import db
import clock
from domain import (
    new_row, touch, sorted_rows, get_program, get_shipment,
    require_program_open, ser_shipment, ser_link, compute_carrier_charge_cents,
    UN_CLASS_CODES,
)
from errors import (
    err_pack_not_found, err_cross_program, err_pack_not_picked,
    err_shipment_not_draft, err_pack_already_attached, err_un_class_mismatch,
    err_shipment_empty, err_shipment_not_tendered,
    err_shipment_not_carrier_accepted, err_shipment_not_in_transit,
    err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, opt_field, as_str, as_decimal, as_enum, round_half_up

bp = Blueprint("shipments", __name__)


def _links_of(shipment_id):
    return sorted_rows(
        [r for r in db.links.values() if r["transport_shipment_id"] == shipment_id]
    )


def _attached_packs(shipment_id):
    return [db.packs[l["battery_pack_id"]] for l in _links_of(shipment_id)]


@bp.route("/integration-programs/<programId>/transport-shipments", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_shipment(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    carrier_code = as_str(req_field(body, "carrier_code"), "carrier_code")
    un_class_code = as_enum(
        req_field(body, "un_class_code"), "un_class_code", UN_CLASS_CODES
    )
    weight = as_decimal(req_field(body, "declared_weight_kg"), "declared_weight_kg")
    if weight < 0:
        raise err_invalid_request("declared_weight_kg must be >= 0")
    weight = round_half_up(weight, 2)
    require_program_open(program)

    row = new_row()
    row.update(
        program_id=program["id"],
        carrier_code=carrier_code,
        un_class_code=un_class_code,
        declared_weight_kg=weight,
        total_pack_count=0,
        total_wh=Decimal("0"),
        carrier_charge_cents=None,
        status="DRAFT",
    )
    db.shipments[row["id"]] = row
    return success_created(ser_shipment(row))


@bp.route("/integration-programs/<programId>/transport-shipments", methods=["GET"])
@require_roles()
def list_shipments(actor, programId):
    get_program(programId)
    rows = sorted_rows(
        [r for r in db.shipments.values() if r["program_id"] == programId]
    )
    return success_list(rows, ser_shipment)


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>", methods=["GET"])
@require_roles()
def get_one_shipment(actor, programId, shipmentId):
    get_program(programId)
    return success_object(ser_shipment(get_shipment(programId, shipmentId)))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/attach", methods=["POST"])
@require_roles("LogisticsCoordinator")
def attach_pack(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    body = get_body(required=True)
    pack_id = as_str(req_field(body, "battery_pack_id"), "battery_pack_id")

    pack = db.packs.get(pack_id)
    if pack is None:
        raise err_pack_not_found()
    require_program_open(program)
    # priority 5: pack must be PICKED, shipment must be DRAFT
    if pack["logistics_status"] != "PICKED":
        raise err_pack_not_picked()
    if shipment["status"] != "DRAFT":
        raise err_shipment_not_draft()
    # priority 12: cross-program referential integrity
    if pack["program_id"] != program["id"]:
        raise err_cross_program()
    # priority 15: not already attached to a non-terminal shipment
    for link in db.links.values():
        if link["battery_pack_id"] != pack["id"]:
            continue
        other = db.shipments.get(link["transport_shipment_id"])
        if other is not None and other["status"] != "DELIVERED":
            raise err_pack_already_attached()
    # priority 18: UN-class agreement
    if pack["shipping_classification"] != shipment["un_class_code"]:
        raise err_un_class_mismatch()

    link = new_row(common=False)
    link.update(
        transport_shipment_id=shipment["id"],
        battery_pack_id=pack["id"],
        program_id=program["id"],
        attached_at_utc=clock.now(),
    )
    db.links[link["id"]] = link

    shipment["total_pack_count"] += 1
    shipment["total_wh"] = round_half_up(shipment["total_wh"] + pack["pack_energy_wh"], 2)
    touch(shipment)
    pack["logistics_status"] = "PACKED_FOR_SHIP"
    touch(pack)
    return success_created(ser_link(link))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/packs", methods=["GET"])
@require_roles()
def list_shipment_packs(actor, programId, shipmentId):
    get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    return success_list(_links_of(shipment["id"]), ser_link)


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/tender", methods=["POST"])
@require_roles("LogisticsCoordinator")
def tender_shipment(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    get_body()
    require_program_open(program)
    if shipment["status"] != "DRAFT":
        raise err_shipment_not_draft()
    # priority 18: UN-class agreement re-verified across every attached pack
    for pack in _attached_packs(shipment["id"]):
        if pack["shipping_classification"] != shipment["un_class_code"]:
            raise err_un_class_mismatch()
    # priority 21: non-emptiness
    if shipment["total_pack_count"] <= 0:
        raise err_shipment_empty()

    shipment["carrier_charge_cents"] = compute_carrier_charge_cents(
        shipment["total_wh"], shipment["declared_weight_kg"], shipment["un_class_code"]
    )
    shipment["status"] = "TENDERED"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/carrier-accept", methods=["POST"])
@require_roles("CarrierAgent")
def carrier_accept(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    body = get_body()
    override = opt_field(body, "declared_weight_kg")
    if override is not None:
        override = as_decimal(override, "declared_weight_kg")
        if override < 0:
            raise err_invalid_request("declared_weight_kg must be >= 0")
        override = round_half_up(override, 2)
    require_program_open(program)
    if shipment["status"] != "TENDERED":
        raise err_shipment_not_tendered()

    if override is not None:
        shipment["declared_weight_kg"] = override
    # final variant: recompute from stored fields (idempotent), reflecting any
    # weight override supplied by the carrier
    shipment["carrier_charge_cents"] = compute_carrier_charge_cents(
        shipment["total_wh"], shipment["declared_weight_kg"], shipment["un_class_code"]
    )
    shipment["status"] = "CARRIER_ACCEPTED"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/carrier-reject", methods=["POST"])
@require_roles("CarrierAgent")
def carrier_reject(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    get_body()
    require_program_open(program)
    if shipment["status"] != "TENDERED":
        raise err_shipment_not_tendered()
    # TENDERED -> CARRIER_REJECTED -> DRAFT (automatic re-tender cycle);
    # attached packs remain PACKED_FOR_SHIP
    shipment["status"] = "DRAFT"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/mark-in-transit", methods=["POST"])
@require_roles("CarrierAgent")
def mark_in_transit(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    get_body()
    require_program_open(program)
    if shipment["status"] != "CARRIER_ACCEPTED":
        raise err_shipment_not_carrier_accepted()

    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    for pack in _attached_packs(shipment["id"]):
        if pack["logistics_status"] == "PACKED_FOR_SHIP":
            pack["logistics_status"] = "SHIPPED"
            touch(pack)
    return success_object(ser_shipment(shipment))


@bp.route("/integration-programs/<programId>/transport-shipments/<shipmentId>/mark-delivered", methods=["POST"])
@require_roles("CarrierAgent")
def mark_delivered(actor, programId, shipmentId):
    program = get_program(programId)
    shipment = get_shipment(programId, shipmentId)
    get_body()
    require_program_open(program)
    if shipment["status"] != "IN_TRANSIT":
        raise err_shipment_not_in_transit()

    shipment["status"] = "DELIVERED"
    touch(shipment)
    for pack in _attached_packs(shipment["id"]):
        if pack["logistics_status"] == "SHIPPED":
            pack["logistics_status"] = "DELIVERED"
            pack["disposition"] = "IN_SERVICE"
            touch(pack)
    return success_object(ser_shipment(shipment))
