"""Order, order-line, shipment and cold-pack reservation endpoints."""

from flask import request

import clock
import db
import serializers
from errors import fail
from middleware import body
from routing import Arr, Obj, endpoint, resolve
from services import calculations, compose as compose_svc, plans as plan_svc
from services.constants import CANCELLATION_REASONS, MAX_RX_UNITS_PER_ORDER


def _plan_of_order(order):
    return db.AUTOSHIP_PLANS.get(order.get("autoship_plan_id"))


def _pet_of_order(order):
    plan = _plan_of_order(order)
    return db.PETS.get(plan.get("pet_id")) if plan else None


def _shipment_of_order(order_id):
    return next((s for s in db.SHIPMENTS.values() if s.get("order_id") == order_id), None)


def _lines_of_order(order_id):
    return compose_svc.lines_of_order(order_id)


def _rx_for_line(line):
    return next(
        (
            p
            for p in db.PRESCRIPTIONS.values()
            if p.get("autoship_item_id") == line.get("autoship_item_id")
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@endpoint(
    "/v1/orders",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def list_orders(caller, ):
    plan_svc.expiry_sweep()
    rows = db.ordered(db.ORDERS.values())
    plan_id = request.args.get("autoship_plan_id")
    status = request.args.get("order_status")
    if plan_id:
        rows = [r for r in rows if r.get("autoship_plan_id") == plan_id]
    if status:
        rows = [r for r in rows if r.get("order_status") == status]
    return Arr([serializers.order(r) for r in rows])


@endpoint(
    "/v1/orders/<order_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def read_order(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    return Obj(serializers.order(order))


@endpoint(
    "/v1/orders/<order_id>/lines",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def order_lines(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    return Arr([serializers.order_line(l) for l in _lines_of_order(order["id"])])


@endpoint(
    "/v1/orders/<order_id>/shipments",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def order_shipments(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    rows = [s for s in db.SHIPMENTS.values() if s.get("order_id") == order["id"]]
    return Arr([serializers.shipment(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/order-lines",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def list_order_lines(caller, ):
    rows = db.ordered(db.ORDER_LINES.values())
    for key in ("order_id", "autoship_item_id", "product_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    return Arr([serializers.order_line(r) for r in rows])


@endpoint("/v1/orders/<order_id>/cancel", ["POST"], ["Customer", "CustomerService", "PharmacyTechnician"])
def cancel_order(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    payload = body()
    reason = payload.get("cancellation_reason")

    shipment = _shipment_of_order(order["id"])
    # A dispatched order whose cold-pack reservation is still held re-enters the
    # cancellation path so that reservation can be released and the site's
    # capacity restored exactly (PRD SS3.6: "any held or committed cold-pack
    # reservation at the origin site is released", and the Shipment state machine
    # carries a DISPATCHED -> CANCELED edge for this trigger).  Every other
    # status keeps the order-level PLACED/PROCESSING precondition.
    holds_cold_pack = bool(
        shipment is not None
        and plan_svc.existing_reservation_for_shipment(shipment["id"]) is not None
        and plan_svc.existing_reservation_for_shipment(shipment["id"]).get(
            "reservation_status") == "HELD"
    )
    admits_cancellation = order.get("order_status") in ("PLACED", "PROCESSING") or (
        order.get("order_status") == "SHIPPED" and holds_cold_pack
    )
    if not admits_cancellation:
        fail("ERR_INVALID_STATE", "This order status does not admit cancellation.")
    if reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'cancellation_reason' is required.")
    if reason not in CANCELLATION_REASONS:
        fail("ERR_INVALID_REQUEST", "cancellation_reason is not a declared value.")

    order["order_status"] = "CANCELED"
    order["cancellation_reason"] = reason
    db.touch(order)

    if shipment is not None:
        if shipment.get("shipment_status") in ("PENDING", "PACKED", "DISPATCHED"):
            shipment["shipment_status"] = "CANCELED"
            db.touch(shipment)
        plan_svc.release_shipment_reservations(shipment)

    plan = _plan_of_order(order)
    if plan is not None:
        calculations.settle_orders_of_pet(plan.get("pet_id"))
        review_id = (db.PETS.get(plan.get("pet_id")) or {}).get("compassionate_review_id")
        if review_id and review_id in db.COMPASSIONATE_REVIEWS:
            db.COMPASSIONATE_REVIEWS[review_id]["refunded_amount_cents"] = (
                calculations.review_refund_total(plan.get("pet_id"))
            )
        calculations.payment_settlement_net(plan)
    return Obj(serializers.order(order))


@endpoint("/v1/orders/<order_id>/ship", ["POST"], ["PharmacyTechnician", "PharmacyManager"])
def ship_order(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    pl = _plan_of_order(order)
    pet = _pet_of_order(order)

    # priority 4: state
    if order.get("order_status") not in ("PLACED", "PROCESSING"):
        fail("ERR_INVALID_STATE", "Only a PLACED or PROCESSING order can be shipped.")

    shipment = _shipment_of_order(order["id"])
    if shipment is None:
        fail("ERR_INVALID_STATE", "The order has no shipment to pack.")
    site = db.PHARMACY_SITES.get(shipment.get("origin_site_id"))

    lines = _lines_of_order(order["id"])
    rx_lines = [l for l in lines if l.get("line_requires_clinic_auth")]
    needs_cold = any(
        (db.PRODUCTS.get(l.get("product_id")) or {}).get("cold_pack_required") for l in lines
    )

    cold_units, _quantity_sum = calculations.cold_pack_units(order["id"])
    already_committed = plan_svc.existing_reservation_for_shipment(shipment["id"]) is not None

    # priority 5: cold-pack capacity (the units are recomputed before the check)
    if needs_cold and not already_committed and site is not None:
        committed = serializers.committed_units(site["id"])
        if committed + cold_units > int(site.get("cold_pack_capacity_units", 0)):
            fail(
                "ERR_COLD_PACK_CAPACITY_EXCEEDED",
                "Committing this shipment's cold-pack units would exceed the site's capacity.",
            )

    # priority 10: site licensing for prescription-scope lines
    if rx_lines and site is not None:
        if shipment.get("destination_state") not in (site.get("licensed_states") or []):
            fail(
                "ERR_SITE_NOT_LICENSED",
                "The origin site is not licensed for the shipment's destination state.",
            )

    # priority 11: prescription coverage (an EXPIRED prescription passes here)
    for line in rx_lines:
        rx = _rx_for_line(line)
        if rx is None or rx.get("rx_status") not in ("VERIFIED", "EXPIRED"):
            fail(
                "ERR_RX_NOT_VERIFIED",
                "Every prescription-scope line must carry a VERIFIED prescription.",
            )

    # priority 13: refill cap
    for line in rx_lines:
        rx = _rx_for_line(line)
        if rx is None:
            continue
        item = db.AUTOSHIP_ITEMS.get(line.get("autoship_item_id"))
        product = db.PRODUCTS.get(line.get("product_id"))
        units = serializers.refill_units_consumed(pet, product, item)
        if units > int(rx.get("authorized_qty_remaining", 0) or 0):
            fail(
                "ERR_REFILL_LIMIT_EXCEEDED",
                "The requested refill exceeds the prescription's remaining authorized quantity.",
            )
        if int(rx.get("refills_used", 0) or 0) >= int(rx.get("refills_authorized", 0) or 0):
            fail(
                "ERR_REFILL_LIMIT_EXCEEDED",
                "The prescription has no refills left.",
            )

    # priority 14: cumulative prescription quantity per order
    totals = serializers.order_quantities_by_prescription(order["id"])
    for value in totals.values():
        if value > MAX_RX_UNITS_PER_ORDER:
            fail(
                "ERR_RX_QUANTITY_LIMIT_EXCEEDED",
                "The order's cumulative prescription quantity exceeds the per-order cap.",
            )

    # priority 15: site operability
    if site is not None:
        if site.get("site_status") == "CLOSED":
            fail("ERR_SITE_RESTRICTED", "The origin site is CLOSED.")
        if site.get("site_status") == "RESTRICTED":
            fail(
                "ERR_SITE_RESTRICTED",
                "The origin site is RESTRICTED for a new autoship order.",
            )

    # priority 16: buffered transit window against the plan's blackout interval
    if needs_cold and pl is not None:
        now = clock.current()
        start = now
        end = clock.add_days(now, calculations.TRANSIT_DAYS)
        if calculations.transit_conflicts_blackout(start, end, pl):
            fail(
                "ERR_TEMPERATURE_CHAIN_RISK",
                "The buffered transit window intersects the plan's blackout interval.",
            )

    # priority 18: prescription currency
    for line in rx_lines:
        rx = _rx_for_line(line)
        if rx is None:
            continue
        if compose_svc._rx_currency_failure(rx):
            fail(
                "ERR_RX_EXPIRED",
                "The prescription is expired or outside its usable interval.",
            )

    # priority 22: pet must still be ACTIVE
    if pet is not None and pet.get("pet_status") != "ACTIVE":
        fail("ERR_PET_INACTIVE", "The plan's owning pet is not ACTIVE.")

    # ------------------------- commit -------------------------------------
    now = clock.current()
    if order.get("order_status") == "PLACED":
        order["order_status"] = "PROCESSING"
        db.touch(order)
        shipment["shipment_status"] = "PACKED"
        db.touch(shipment)
        if needs_cold and site is not None and not already_committed:
            shipment["cold_pack_units"] = cold_units
            db.touch(shipment)
            db.mint(
                db.COLD_PACK_RESERVATIONS,
                shipment_id=shipment["id"],
                site_id=site["id"],
                units=cold_units,
                reservation_status="HELD",
            )
        elif site is not None and not already_committed:
            shipment["cold_pack_units"] = 0
            db.touch(shipment)

    # dispatch step
    shipment["shipment_status"] = "DISPATCHED"
    shipment["tracking_code"] = _tracking_code(shipment["id"])
    shipment["transit_window_start_date"] = now
    shipment["transit_window_end_date"] = clock.add_days(now, calculations.TRANSIT_DAYS)
    db.touch(shipment)
    plan_svc.commit_shipment_reservations(shipment)

    order["order_status"] = "SHIPPED"
    db.touch(order)

    consume_refills(order, pet, lines)

    if pl is not None:
        calculations.payment_settlement_net(pl)
    return Obj(serializers.order(order))


def consume_refills(order, pet, lines):
    """refill_consumption_applied: debit each prescription, complete empty items."""
    for line in lines:
        if not line.get("line_requires_clinic_auth"):
            continue
        rx = _rx_for_line(line)
        if rx is None or rx.get("rx_status") != "VERIFIED":
            continue
        item = db.AUTOSHIP_ITEMS.get(line.get("autoship_item_id"))
        product = db.PRODUCTS.get(line.get("product_id"))
        units = serializers.refill_units_consumed(pet, product, item)
        rx["authorized_qty_remaining"] = max(
            0, int(rx.get("authorized_qty_remaining", 0)) - units
        )
        rx["refills_used"] = int(rx.get("refills_used", 0)) + 1
        db.touch(rx)
        plan_svc.complete_item_if_exhausted(rx)


def _tracking_code(shipment_id):
    return "TRK" + shipment_id.replace("-", "")[:18].upper()


@endpoint("/v1/orders/<order_id>/deliver", ["POST"], ["PharmacyTechnician", "PharmacyManager"])
def deliver_order(caller, order_id):
    order = resolve(db.ORDERS, order_id, "order")
    if order.get("order_status") != "SHIPPED":
        fail("ERR_INVALID_STATE", "Only a SHIPPED order can be delivered.")
    order["order_status"] = "DELIVERED"
    db.touch(order)
    shipment = _shipment_of_order(order["id"])
    if shipment is not None and shipment.get("shipment_status") == "DISPATCHED":
        shipment["shipment_status"] = "DELIVERED"
        db.touch(shipment)
    plan = _plan_of_order(order)
    if plan is not None:
        calculations.payment_settlement_net(plan)
    return Obj(serializers.order(order))


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

@endpoint("/v1/shipments", ["POST"], ["PharmacyTechnician", "PharmacyManager"], 201)
def create_shipment(caller, ):
    payload = body()
    order_id = payload.get("order_id")
    if not order_id:
        fail("ERR_INVALID_REQUEST", "Field 'order_id' is required.")
    order = resolve(db.ORDERS, order_id, "order")

    # priority 21: only for a PLACED order and only once per order
    if order.get("order_status") != "PLACED":
        fail(
            "ERR_ORDER_ALREADY_SHIPPED",
            "A shipment may only be created for an order in PLACED.",
        )
    if _shipment_of_order(order["id"]) is not None:
        fail(
            "ERR_ORDER_ALREADY_SHIPPED",
            "This order already has a shipment.",
        )

    pet = _pet_of_order(order)
    destination_state = pet.get("owner_state") if pet else None

    lines = _lines_of_order(order["id"])
    needs_cold = any(
        (db.PRODUCTS.get(l.get("product_id")) or {}).get("cold_pack_required") for l in lines
    )

    # origin_site_selection runs in two phases: a capacity-agnostic eligibility
    # filter first (its empty result is ERR_NO_ELIGIBLE_SITE), then the
    # cold-pack headroom test, whose empty result is ERR_COLD_PACK_CAPACITY_EXCEEDED.
    ranked = calculations.eligible_sites(destination_state, 0)
    if not ranked:
        fail("ERR_NO_ELIGIBLE_SITE", "No eligible origin site serves this destination state.")

    cold_units = 0
    if needs_cold:
        cold_units, _q = calculations.cold_pack_units(order["id"])
    site = None
    for candidate in ranked:
        committed = serializers.committed_units(candidate["id"])
        if cold_units > int(candidate.get("cold_pack_capacity_units", 0)) - committed:
            continue
        site = candidate
        break
    if site is None:
        fail(
            "ERR_COLD_PACK_CAPACITY_EXCEEDED",
            "No eligible origin site has cold-pack headroom for this shipment.",
        )

    shipment = db.mint(
        db.SHIPMENTS,
        order_id=order["id"],
        origin_site_id=site["id"],
        destination_state=destination_state,
        shipment_status="PENDING",
        cold_pack_required=needs_cold,
        cold_pack_units=0,
        transit_window_start_date=None,
        transit_window_end_date=None,
        tracking_code=None,
    )
    return Obj(serializers.shipment(shipment), 201)


@endpoint(
    "/v1/shipments",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def list_shipments(caller, ):
    rows = db.ordered(db.SHIPMENTS.values())
    for key in ("order_id", "origin_site_id", "shipment_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    return Arr([serializers.shipment(r) for r in rows])


@endpoint(
    "/v1/shipments/<shipment_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def read_shipment(caller, shipment_id):
    row = resolve(db.SHIPMENTS, shipment_id, "shipment")
    return Obj(serializers.shipment(row))


@endpoint(
    "/v1/shipments/<shipment_id>/cold-pack-reservations",
    ["GET"],
    ["PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def shipment_reservations(caller, shipment_id):
    shipment = resolve(db.SHIPMENTS, shipment_id, "shipment")
    rows = [r for r in db.COLD_PACK_RESERVATIONS.values() if r.get("shipment_id") == shipment["id"]]
    return Arr([serializers.cold_pack_reservation(r) for r in db.ordered(rows)])


@endpoint(
    "/v1/cold-pack-reservations",
    ["GET"],
    ["PharmacyTechnician", "PharmacyManager", "ComplianceOfficer"],
)
def list_reservations(caller, ):
    rows = db.ordered(db.COLD_PACK_RESERVATIONS.values())
    for key in ("shipment_id", "site_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    return Arr([serializers.cold_pack_reservation(r) for r in rows])