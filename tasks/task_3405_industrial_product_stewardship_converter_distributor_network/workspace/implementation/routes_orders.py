"""Order placement, fulfillment advance, and cancellation (PRD §3.6).

Creation gauntlet: auth(1) -> role(2) -> ownership(3) -> shape(5) ->
existence(6) -> OCC(7) -> clearance CLEARED(11) -> agreement effective(13) ->
LTB window(14) -> buyer consistency(17) -> converter standing(18) ->
capability coverage(19)."""

from flask import Blueprint, request

import auth
import calcs
import cascades
import envelope
import serialization as ser
import store
import validation
from errors import (api_err, invalid_request, invalid_state, not_found,
                    stale_version)

bp = Blueprint("orders", __name__)

CAPABILITIES = {"SLITTING", "DIE_CUTTING", "LAMINATION"}


def _get_order(oid):
    row = store.STORE["orders"].get(oid)
    if row is None:
        raise not_found("Order not found")
    return row


def _check_order_ownership(order, uid, role):
    """Tier 3: entity-backed roles act only on their own orders."""
    if role == "Converter":
        if order["converter_id"] is None or order["converter_id"] != uid:
            raise api_err("ERR_OWNERSHIP_VIOLATION",
                          "Converter role may only act on its own orders")
    elif role == "Distributor":
        if order["distributor_id"] is None or order["distributor_id"] != uid:
            raise api_err("ERR_OWNERSHIP_VIOLATION",
                          "Distributor role may only act on its own orders")


@bp.post("/stewardship/orders")
def create_order():
    uid, role = auth.authenticate()
    auth.require_role(role, ["Converter", "Distributor"])
    payload = validation.get_payload()
    # Tier 3 ownership (payload-based): the caller's X-User-ID must equal the
    # buyer id of its own kind when that id is present.
    raw_converter_id = payload.get("converter_id")
    raw_distributor_id = payload.get("distributor_id")
    if (role == "Converter" and isinstance(raw_converter_id, str)
            and raw_converter_id != uid):
        raise api_err("ERR_OWNERSHIP_VIOLATION",
                      "Converter X-User-ID must equal the order's converter_id")
    if (role == "Distributor" and isinstance(raw_distributor_id, str)
            and raw_distributor_id != uid):
        raise api_err("ERR_OWNERSHIP_VIOLATION",
                      "Distributor X-User-ID must equal the order's distributor_id")
    # Tier 5 shape.
    agreement_id = validation.req_str(payload, "agreement_id")
    quantity = validation.req_int(payload, "quantity")
    if quantity <= 0:
        raise invalid_request("quantity must be > 0")
    requested_ship_date = validation.req_dt(payload, "requested_ship_date")
    expected = validation.req_int(payload, "expected_price_agreement_version")
    lot_code = validation.opt_str(payload, "lot_code")
    converter_id = (raw_converter_id if isinstance(raw_converter_id, str)
                    else None)
    distributor_id = (raw_distributor_id if isinstance(raw_distributor_id, str)
                      else None)
    if converter_id is None and distributor_id is None:
        raise invalid_request(
            "Exactly one of converter_id / distributor_id must be set")
    intended_capability = payload.get("intended_capability")
    is_converter_buyer = converter_id is not None and distributor_id is None
    is_distributor_buyer = distributor_id is not None and converter_id is None
    if is_converter_buyer:
        # Required for converter buyers, validated as an enum at intake.
        intended_capability = validation.req_enum(
            payload, "intended_capability", CAPABILITIES)
    elif is_distributor_buyer:
        # Forbidden for distributor buyers.
        if intended_capability is not None:
            raise invalid_request(
                "intended_capability is forbidden for distributor buyers")
        intended_capability = None
    else:
        # Both present: leave the capability check to the ambiguity gate.
        intended_capability = None
    # Tier 6 existence.
    agreement = store.STORE["agreements"].get(agreement_id)
    if agreement is None:
        raise not_found("PriceAgreement not found")
    if (converter_id is not None
            and store.STORE["converters"].get(converter_id) is None):
        raise not_found("Converter not found")
    if (distributor_id is not None
            and store.STORE["distributors"].get(distributor_id) is None):
        raise not_found("Distributor not found")
    # Tier 7 OCC on the agreement's version.
    if expected != agreement["version"]:
        raise stale_version(
            "expected_price_agreement_version does not match the agreement's "
            "current version")
    formulation = store.STORE["formulations"][agreement["formulation_id"]]
    jurisdiction = store.STORE["jurisdictions"][agreement["jurisdiction_id"]]
    now = store.now()
    # Priority 11: a CLEARED clearance must exist for (formulation, ship-to).
    cleared = any(
        c["formulation_id"] == formulation["id"]
        and c["jurisdiction_id"] == jurisdiction["id"]
        and c["status"] == "CLEARED"
        for c in store.STORE["clearances"].values())
    if not cleared:
        raise api_err("ERR_CLEARANCE_NOT_CLEARED",
                      "No CLEARED clearance exists for the agreement's "
                      "(formulation, jurisdiction)")
    # Priority 13: clock inside [effective_from, effective_to).
    if not (agreement["effective_from"] <= now < agreement["effective_to"]):
        raise api_err("ERR_AGREEMENT_NOT_EFFECTIVE",
                      "Current clock is outside the agreement's effectiveness "
                      "window")
    # Priority 14: last-time-buy window on DISCONTINUED formulations
    # (inclusive deadlines, not half-open bounds).
    if formulation["status"] == "DISCONTINUED":
        if (now > formulation["ltb_deadline"]
                or requested_ship_date > formulation["last_ship_date"]):
            raise api_err("ERR_LTB_WINDOW_CLOSED",
                          "The last-time-buy window is closed for this order")
    # Priority 17: buyer identity consistency with the agreement and the role.
    if converter_id is not None and distributor_id is not None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "Both converter_id and distributor_id were supplied")
    if role == "Converter" and converter_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "A Converter caller must buy as a converter")
    if role == "Distributor" and distributor_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "A Distributor caller must buy as a distributor")
    if converter_id is not None and agreement["converter_id"] != converter_id:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "Order buyer does not match the agreement's buyer")
    if distributor_id is not None and agreement["distributor_id"] != distributor_id:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "Order buyer does not match the agreement's buyer")
    # Priorities 18-19: converter standing and capability coverage.
    if converter_id is not None:
        converter = store.STORE["converters"][converter_id]
        if converter["status"] != "AUTHORIZED":
            raise api_err("ERR_CONVERTER_NOT_AUTHORIZED",
                          "Converter must be AUTHORIZED to place orders")
        covered = any(
            a["converter_id"] == converter_id
            and a["capability"] == intended_capability
            and a["territory_code"] == jurisdiction["code"]
            and a["valid_from"] <= now < a["valid_to"]
            for a in store.STORE["authorizations"].values())
        if not covered:
            raise api_err(
                "ERR_AUTHORIZATION_CAPABILITY_MISMATCH",
                "No authorization covers this (converter, capability, "
                "territory) at the current clock")
    # Pricing: computed once at creation and frozen (calc order_unit_price).
    unit_price, line_total = calcs.order_unit_price(agreement, quantity)
    row = store.stamp_new({
        "agreement_id": agreement_id,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "formulation_id": agreement["formulation_id"],
        "ship_to_jurisdiction_id": agreement["jurisdiction_id"],
        "quantity": quantity,
        "requested_ship_date": requested_ship_date,
        "intended_capability": intended_capability,
        "lot_code": lot_code,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "is_ltb_order": formulation["status"] == "DISCONTINUED",
        "fulfillment_status": "PENDING",
        "compliance_status": "CLEAR",
        "shipped_at": None,
        "flagged_by_report_id": None,
    })
    store.STORE["orders"][row["id"]] = row
    # Cross-entity bump: order placement mutates the agreement (§2.5).
    store.touch(agreement)
    return envelope.success_object(ser.order(row), 201)


@bp.get("/stewardship/orders/<oid>")
def get_order(oid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.order(_get_order(oid)), 200)


@bp.get("/stewardship/orders")
def list_orders():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["orders"].values(), request.args,
        ["agreement_id", "converter_id", "distributor_id", "formulation_id",
         "ship_to_jurisdiction_id", "flagged_by_report_id",
         "fulfillment_status", "compliance_status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.order(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/orders/<oid>/advance")
def advance_order(oid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["Converter", "Distributor"])
    order = _get_order(oid)
    _check_order_ownership(order, uid, role)
    if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
        raise invalid_state(
            "Terminal orders (SHIPPED, CANCELLED) cannot advance")
    # Priority 12: compliance gate applies to both advance steps.
    if order["compliance_status"] != "CLEAR":
        raise api_err("ERR_ORDER_COMPLIANCE_BLOCKED",
                      "A FLAGGED order cannot advance")
    if order["fulfillment_status"] == "PENDING":
        # ALLOCATE: reserve LTB pool units when this is a last-time-buy order.
        if order["is_ltb_order"]:
            formulation = store.STORE["formulations"][order["formulation_id"]]
            if formulation["ltb_pool_remaining"] < order["quantity"]:
                raise api_err("ERR_LTB_POOL_EXHAUSTED",
                              "The last-time-buy pool cannot cover this order")
            formulation["ltb_pool_remaining"] -= order["quantity"]
            store.touch(formulation)
        order["fulfillment_status"] = "ALLOCATED"
        store.touch(order)
    else:
        # SHIP: stamp the clock and recompute matching provisional accruals.
        order["fulfillment_status"] = "SHIPPED"
        order["shipped_at"] = store.now()
        store.touch(order)
        cascades.recompute_provisional_accruals(
            order["formulation_id"], order["converter_id"],
            order["distributor_id"])
    return envelope.success_object(ser.order(order), 200)


@bp.post("/stewardship/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["Converter", "Distributor"])
    order = _get_order(oid)
    _check_order_ownership(order, uid, role)
    if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
        raise invalid_state(
            "Only PENDING or ALLOCATED orders can be cancelled")
    if order["fulfillment_status"] == "ALLOCATED" and order["is_ltb_order"]:
        # Compensation: return the reserved units to the pool.
        formulation = store.STORE["formulations"][order["formulation_id"]]
        formulation["ltb_pool_remaining"] += order["quantity"]
        store.touch(formulation)
    order["fulfillment_status"] = "CANCELLED"
    store.touch(order)
    return envelope.success_object(ser.order(order), 200)
