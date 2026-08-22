"""Removal from bond: release orders, the bond axis and excise tax."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import CLIENT_REP, COMPLIANCE_OFFICER, FACILITY_ADMIN, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_DESTINATION_PERMIT_REQUIRED,
    ERR_INSUFFICIENT_LOT_VOLUME,
    ERR_INVALID_STATE,
    ERR_REPORTING_PERIOD_LOCKED,
)
from helpers import declared, run_list
from store import db, iso, new_entity, rhu, touch
from validation import v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("release_orders", __name__)

RELEASE_TYPES = {"TAXPAID_REMOVAL", "TRANSFER_IN_BOND"}
RELEASE_ACTIONS = {
    "APPROVE": [COMPLIANCE_OFFICER],
    "REJECT": [COMPLIANCE_OFFICER],
    "EXECUTE": [COMPLIANCE_OFFICER],
    "CANCEL": [CLIENT_REP],
}
READ_ROLES = [FACILITY_ADMIN, COMPLIANCE_OFFICER, CLIENT_REP]


@bp.route("/release-orders", methods=["POST"])
def create_release_order():
    ctx = guard([CLIENT_REP])
    body = ctx.body
    lot_id = v_string(body, "lot_id")
    release_type = v_enum(body, "release_type", RELEASE_TYPES)
    gallons = v_number(body, "gallons", gt=0, max_dp=2)
    cases = v_int(body, "cases", required=False, default=None, ge=0, nullable=True)
    permit = v_string(body, "destination_permit_number", required=False, default=None,
                      nullable=True)

    lot = domain.get_lot(lot_id)
    scope(ctx, domain.lot_client_id(lot))

    # Rung 90 -- the destination-permit pairing.
    if release_type == "TRANSFER_IN_BOND" and not permit:
        raise ApiError(ERR_DESTINATION_PERMIT_REQUIRED,
                       "A transfer in bond must name the receiving premise's permit.")
    if release_type == "TAXPAID_REMOVAL" and permit is not None:
        raise ApiError(ERR_DESTINATION_PERMIT_REQUIRED,
                       "A taxpaid removal must not carry a destination permit.")

    order = new_entity({
        "lot_id": lot_id,
        "release_type": release_type,
        "gallons": gallons,
        "cases": cases,
        "destination_permit_number": permit,
        "status": "REQUESTED",
        "requested_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "excise_tax_cents": 0,
        "executed_at": None,
        "rejection_reason": None,
        "_executed_dt": None,
    })
    db.release_orders[order["id"]] = order
    return respond(domain.serialize(order), 201)


@bp.route("/release-orders/<order_id>", methods=["GET"])
def read_release_order(order_id):
    ctx = guard(READ_ROLES, read_body=False)
    order = domain.get_release_order(order_id)
    scope(ctx, domain.release_order_client_id(order))
    return respond(domain.serialize(order))


@bp.route("/release-orders", methods=["GET"])
def list_release_orders():
    ctx = guard(READ_ROLES, read_body=False)
    return run_list(db.release_orders.values(), ctx, domain.serialize,
                    owner_fn=domain.release_order_client_id,
                    filters=(("lot_id", "lot_id"), ("status", "status"),
                             ("release_type", "release_type")))


@bp.route("/release-orders/<order_id>/transitions", methods=["POST"])
def release_order_transitions(order_id):
    ctx = guard([COMPLIANCE_OFFICER, CLIENT_REP], RELEASE_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(RELEASE_ACTIONS))
    rejection_reason = None
    if action == "REJECT":
        rejection_reason = v_string(body, "rejection_reason", required=False,
                                    nullable=True)

    order = domain.get_release_order(order_id)
    scope(ctx, domain.release_order_client_id(order))

    lot = db.lots.get(order["lot_id"])
    client_id = domain.release_order_client_id(order)
    client = db.clients.get(client_id)

    if action == "APPROVE":
        declared(order["status"] == "REQUESTED")
        if lot is None or lot["bond_status"] != "IN_BOND":
            raise ApiError(ERR_INVALID_STATE, "The lot is not IN_BOND.")
        if lot["production_status"] not in ("AGING", "BOTTLED"):
            raise ApiError(ERR_INVALID_STATE,
                           "The lot's production status does not permit a release.")
        # Rung 40 -- the owning client must be ACTIVE.
        if client is None or client["status"] != "ACTIVE":
            raise ApiError(ERR_CLIENT_NOT_ACTIVE, "The owning client is not ACTIVE.")
        # Rung 78 -- volume sufficiency.
        if D(lot["volume_gallons"]) < D(order["gallons"]):
            raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                           "The lot does not hold the requested gallons.")
        order["status"] = "APPROVED"
        order["approved_by_user_id"] = ctx.user_id
        if order["release_type"] == "TAXPAID_REMOVAL":
            lot["bond_status"] = "TAX_DETERMINED"
            touch(lot)
    elif action == "REJECT":
        declared(order["status"] == "REQUESTED")
        order["status"] = "REJECTED"
        order["rejection_reason"] = rejection_reason
    elif action == "CANCEL":
        declared(order["status"] in ("REQUESTED", "APPROVED"))
        if (order["status"] == "APPROVED"
                and order["release_type"] == "TAXPAID_REMOVAL"
                and lot is not None and lot["bond_status"] == "TAX_DETERMINED"):
            lot["bond_status"] = "IN_BOND"
            touch(lot)
        order["status"] = "CANCELLED"
    else:  # EXECUTE
        declared(order["status"] == "APPROVED")
        # Rung 55 -- the bonded books are frozen while a period is prepared.
        now = db.now()
        for report in domain.client_reports(client_id):
            if report["status"] != "PREPARED":
                continue
            if report["_ps_dt"] <= now < report["_pe_dt"]:
                raise ApiError(ERR_REPORTING_PERIOD_LOCKED,
                               "A reporting period is under preparation.")
        # Rung 78 -- volume sufficiency.
        if lot is None or D(lot["volume_gallons"]) < D(order["gallons"]):
            raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                           "The lot does not hold the requested gallons.")

        gallons = D(order["gallons"])
        remaining = rhu(D(lot["volume_gallons"]) - gallons, 2)
        if order["release_type"] == "TAXPAID_REMOVAL":
            start = domain.taxpaid_gallons_ytd(client_id)
            order["excise_tax_cents"] = calc.excise_tax(start, gallons)
            lot["volume_gallons"] = remaining
            lot["bond_status"] = "REMOVED_TAXPAID" if remaining == 0 else "IN_BOND"
        else:
            order["excise_tax_cents"] = 0
            lot["volume_gallons"] = remaining
            if remaining == 0:
                lot["bond_status"] = "TRANSFERRED_IN_BOND"
        touch(lot)

        order["executed_at"] = iso(now)
        order["_executed_dt"] = now
        order["status"] = "EXECUTED"
        touch(order)
        if client is not None:
            touch(client)
        return respond(domain.serialize(order))

    touch(order)
    return respond(domain.serialize(order))
