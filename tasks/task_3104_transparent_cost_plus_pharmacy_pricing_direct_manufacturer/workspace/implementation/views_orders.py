"""Route handlers: orders and shipments."""

from clock import add_days, now, now_iso, parse_iso, to_iso
from cascades import (
    apply_decomposition,
    cancel_order,
    cancel_claims_of_prescription,
    recompute_drug_quiet,
)
from errors import fail, success_payload
from pricing import (
    demand_units_30d,
    order_decomposition,
    slot_conflict,
    supply_units as compute_supply_units,
)
from registry import (
    active_license_for,
    find,
    get,
    of_parent,
    ordered_by_created,
    ordered_by_seq,
    shipments_of_order,
)
from resources import blank_record, internal_of, touch
from store import store


def _object(record):
    return success_payload(record, "object")


def _array(ctx, records):
    return success_payload(records, "array", ctx.pagination(len(records)))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def create_order(ctx):
    prescription_id = ctx.text("prescription_id")
    request_id = ctx.text("request_id")
    pharmacy_id = ctx.text("pharmacy_id")
    quantity_raw = ctx.key("quantity")
    source_price_id = ctx.text("source_price_id")
    sub_source_price_id = ctx.key("sub_source_price_id")

    prescription = find("prescriptions", prescription_id)
    request = find("requests", request_id)
    find("pharmacies", pharmacy_id)
    source_price = find("prices", source_price_id)
    if sub_source_price_id is not None:
        find("prices", sub_source_price_id)

    drug = get("drugs", prescription.get("drug_id"))
    if request.get("prescription_id") != prescription_id:
        fail("ERR_RESOURCE_NOT_FOUND", "The intake request does not belong to this prescription.")
    if drug is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The prescription carries no resolvable drug.")

    # Validation order per PRD §2.12: the controlled-substance exclusion, then
    # the remaining business gates, then the lower-bound numeric check.
    if drug.get("is_controlled") is True:
        fail("ERR_CONTROLLED_SUBSTANCE_EXCLUDED")
    if drug.get("state") == "DELISTED":
        fail("ERR_DRUG_DELISTED")
    if request.get("status") != "ACCEPTED":
        fail("ERR_REQUEST_NOT_ACCEPTED")

    quantity = _int_or_none(quantity_raw)
    if quantity is None:
        fail("ERR_INVALID_AMOUNT", "quantity must be an integer.")
    remaining_capacity = int(request.get("packaged_quantity") or 0) - int(
        request.get("consumed_quantity") or 0
    )
    if quantity > remaining_capacity:
        fail("ERR_REQUEST_CAPACITY_EXCEEDED", "The request's remaining capacity is exhausted.")
    if quantity > compute_supply_units(drug.get("id")):
        fail("ERR_REQUEST_CAPACITY_EXCEEDED", "The drug's supply cannot cover this order.")
    if source_price.get("drug_id") != prescription.get("drug_id"):
        fail("ERR_SOURCE_PRICE_DRUG_MISMATCH")
    if quantity < 1:
        fail("ERR_INVALID_AMOUNT", "quantity must be at least 1.")

    record = blank_record()
    record["prescription_id"] = prescription_id
    record["request_id"] = request_id
    record["pharmacy_id"] = pharmacy_id
    record["quantity"] = quantity
    record["ship_state_code"] = prescription.get("ship_state_code")
    record["paid_at"] = None
    record["status"] = "CREATED"
    record["source_price_id"] = source_price_id
    record["sub_source_price_id"] = sub_source_price_id
    record["retail_reference_price_cents"] = drug.get("retail_reference_price_cents")
    record["insured_reference_price_cents"] = drug.get("insured_reference_price_cents")
    record["cancel_reason_code"] = None
    apply_decomposition(record)
    store.orders[record["id"]] = internal_of("orders", record)

    created = parse_iso(record.get("created_at"))
    comparison = blank_record()
    comparison["order_id"] = record["id"]
    comparison["typical_retail_price_cents"] = record.get("retail_reference_price_cents")
    comparison["benefit_covered_price_cents"] = record.get("insured_reference_price_cents")
    comparison["substantiated"] = False
    comparison["substantiation_digest"] = None
    comparison["status"] = "UNSUBSTANTIATED"
    comparison["state"] = "FRESH"
    comparison["stale_deadline_at"] = to_iso(add_days(created, 30))
    comparison["comparison_created_at"] = record.get("created_at")
    comparison["ever_substantiated"] = False
    comparison["first_retail_cents"] = record.get("retail_reference_price_cents")
    comparison["first_benefit_cents"] = record.get("insured_reference_price_cents")
    store.comparisons[comparison["id"]] = internal_of("comparisons", comparison)

    if drug.get("state") == "FORMULARY":
        recompute_drug_quiet(drug.get("id"), now())
    return _object(record), 201


def get_order(ctx, order_id):
    order = find("orders", order_id)
    prescription = get("prescriptions", order.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    return _object(order), 200


def list_orders(ctx):
    records = list(store.orders.values())
    for field in ("prescription_id", "request_id", "pharmacy_id", "ship_state_code", "status"):
        value = ctx.query(field)
        if value:
            records = [rec for rec in records if rec.get(field) == value]
    return _array(ctx, ordered_by_created(records)), 200


def list_request_orders(ctx, request_id):
    find("requests", request_id)
    return _array(ctx, ordered_by_created(of_parent("orders", "request_id", request_id))), 200


def pay_order(ctx, order_id):
    order = find("orders", order_id)
    if order.get("status") != "CREATED":
        fail("ERR_INVALID_STATE", "Only a CREATED order may be paid.")
    prescription = get("prescriptions", order.get("prescription_id"))
    request = get("requests", order.get("request_id"))
    drug = get("drugs", (prescription or {}).get("drug_id"))
    source_price = get("prices", order.get("source_price_id"))
    if drug is None or drug.get("state") != "FORMULARY":
        fail("ERR_INVALID_STATE", "The drug is not on the formulary.")
    if prescription is None or prescription.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "The prescription is not ACTIVE.")
    if source_price is None or source_price.get("sourcing_status") != "SOURCED":
        fail("ERR_INVALID_STATE", "The selected primary price row is not SOURCED.")
    if request is None or request.get("status") != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The referenced intake request is not ACCEPTED.")

    order.update(order_decomposition(order))
    if order.get("acquisition_cost_cents") < 0 or order.get("markup_cents") < 0:
        fail("ERR_PRICE_INVARIANT_BROKEN")
    if order.get("patient_price_cents") < 0:
        fail("ERR_PRICE_INVARIANT_BROKEN")
    expected = (
        order.get("acquisition_cost_cents")
        + order.get("markup_cents")
        + order.get("pharmacy_fee_cents")
        + order.get("shipping_fee_cents")
    )
    if order.get("patient_price_cents") != expected:
        fail("ERR_PRICE_INVARIANT_BROKEN")

    order["status"] = "PAID"
    order["paid_at"] = now_iso()
    touch(order)
    return _object(order), 200


def fulfill_order(ctx, order_id):
    order = find("orders", order_id)

    # Optimistic concurrency follows existence and precedes state validation
    # (PRD §2.12). The token is mandatory on this endpoint: a request that omits
    # it carries no version to compare, so it is refused as stale rather than
    # admitted (PRD §2.9, "Neither token is optional on its endpoint").
    expected_version = ctx.key("expected_order_version")
    if expected_version is None or _int_or_none(expected_version) != int(order.get("version") or 1):
        fail("ERR_STALE_VERSION")

    if order.get("status") != "PAID":
        fail("ERR_INVALID_STATE", "Only a PAID order may be fulfilled.")
    prescription = get("prescriptions", order.get("prescription_id"))
    drug = get("drugs", (prescription or {}).get("drug_id"))
    if drug is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The order's drug does not resolve.")
    if drug.get("is_controlled") is True:
        fail("ERR_CONTROLLED_SUBSTANCE_EXCLUDED")

    clock = now()
    interval = drug.get("ship_interval_days")
    paid_at = parse_iso(order.get("paid_at"))
    if interval is None:
        fail("ERR_SHIP_INTERVAL_NOT_ELAPSED", "No shipment may be created without an interval.")
    if paid_at is None:
        fail("ERR_SHIP_INTERVAL_NOT_ELAPSED", "The order has no payment instant.")
    if clock < add_days(paid_at, interval):
        fail("ERR_SHIP_INTERVAL_NOT_ELAPSED")

    request = get("requests", order.get("request_id"))
    shipment = blank_record()
    shipment["order_id"] = order.get("id")
    shipment["request_id"] = order.get("request_id")
    shipment["shipment_seq"] = len(shipments_of_order(order.get("id"))) + 1
    shipment["status"] = "PENDING"
    shipment["dispatch_at"] = None
    shipment["delivery_at"] = None
    store.shipments[shipment["id"]] = internal_of("shipments", shipment)

    if request is not None:
        consumed = min(int(order.get("quantity") or 0), int(request.get("packaged_quantity") or 0))
        request["consumed_quantity"] = int(request.get("consumed_quantity") or 0) + consumed
        touch(request)
    order["status"] = "FULFILLING"
    touch(order)
    return _object(order), 200


def ship_order(ctx, order_id):
    order = find("orders", order_id)
    if order.get("status") != "FULFILLING":
        fail("ERR_INVALID_STATE", "Only a FULFILLING order may be dispatched.")
    pharmacy = get("pharmacies", order.get("pharmacy_id"))
    if pharmacy is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The order's pharmacy does not resolve.")

    prescription = get("prescriptions", order.get("prescription_id"))
    drug = get("drugs", (prescription or {}).get("drug_id"))
    if drug is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The order's drug does not resolve.")

    licence = active_license_for(pharmacy.get("id"), order.get("ship_state_code"))
    if licence is None or pharmacy.get("shipping_enabled") is not True:
        fail("ERR_NOT_LICENSED_IN_STATE")
    if drug.get("is_controlled") is True:
        fail("ERR_CONTROLLED_SUBSTANCE_EXCLUDED")

    shipment = None
    for candidate in shipments_of_order(order.get("id")):
        if candidate.get("status") in ("PENDING", "DISPATCHED"):
            shipment = candidate
            break
    if shipment is None:
        fail("ERR_INVALID_STATE", "The order carries no dispatchable shipment.")

    clock = now()
    if slot_conflict(drug.get("id"), clock):
        fail("ERR_SHIP_SLOT_CONFLICT")

    shipment["status"] = "DISPATCHED"
    shipment["dispatch_at"] = now_iso()
    touch(shipment)

    for claim in store.claims.values():
        if claim.get("prescription_id") != prescription.get("id"):
            continue
        if claim.get("status") not in ("PENDING", "AUTHORIZED"):
            continue
        claim["status"] = "SHIPPED"
        claim["denied_at"] = None
        claim["denial_reason_code"] = None
        claim["reserved_quantity"] = 0
        claim["order_id"] = order.get("id")
        touch(claim)

    recompute_drug_quiet(drug.get("id"), clock)
    touch(drug)
    touch(prescription)
    order["status"] = "SHIPPED"
    touch(order)
    return _object(order), 200


def deliver_order(ctx, order_id):
    order = find("orders", order_id)
    if order.get("status") != "SHIPPED":
        fail("ERR_INVALID_STATE", "Only a SHIPPED order may be delivered.")
    shipment = None
    for candidate in shipments_of_order(order.get("id")):
        if candidate.get("status") in ("DISPATCHED", "IN_TRANSIT"):
            shipment = candidate
            break
    if shipment is None:
        fail("ERR_INVALID_STATE", "The order carries no deliverable shipment.")

    clock = now()
    shipment["status"] = "DELIVERED"
    shipment["delivery_at"] = now_iso()
    touch(shipment)
    order["status"] = "DELIVERED"
    touch(order)

    prescription = get("prescriptions", order.get("prescription_id"))
    drug = None
    if prescription is not None:
        prescription["refills_consumed"] = int(prescription.get("refills_consumed") or 0) + 1
        touch(prescription)
        drug = get("drugs", prescription.get("drug_id"))
        if drug is not None:
            recompute_drug_quiet(drug.get("id"), clock)
        if int(prescription.get("refills_consumed") or 0) >= int(
            prescription.get("total_refills_authorized") or 0
        ):
            if prescription.get("status") == "ACTIVE":
                prescription["status"] = "DEPLETED"
                touch(prescription)
            cancel_claims_of_prescription(
                prescription.get("id"), states=("PENDING", "AUTHORIZED", "SHIPPED")
            )
    if drug is not None:
        touch(drug)
    return _object(order), 200


def cancel_order_view(ctx, order_id):
    order = find("orders", order_id)
    reason_code = ctx.key("reason_code")
    if reason_code is None or (isinstance(reason_code, str) and not reason_code.strip()):
        fail("ERR_CANCELLATION_REASON_REQUIRED")
    status = order.get("status")
    if status == "PAID":
        for shipment in shipments_of_order(order.get("id")):
            if shipment.get("status") == "DISPATCHED":
                fail("ERR_INVALID_STATE", "A dispatched shipment blocks cancellation.")
    if status == "FULFILLING":
        for shipment in shipments_of_order(order.get("id")):
            if shipment.get("status") == "DISPATCHED":
                fail("ERR_INVALID_STATE", "A dispatched shipment blocks cancellation.")
    if status == "SHIPPED":
        for shipment in shipments_of_order(order.get("id")):
            if shipment.get("status") == "DELIVERED":
                fail("ERR_INVALID_STATE", "A delivered shipment blocks cancellation.")
    if status not in ("CREATED", "PAID", "FULFILLING", "SHIPPED"):
        fail("ERR_INVALID_STATE", "An order at %s may not be cancelled." % status)

    cancel_order(order, str(reason_code), now())
    prescription = get("prescriptions", order.get("prescription_id"))
    if status in ("PAID", "FULFILLING") and prescription is not None:
        from cascades import deny_claims_of_prescription

        deny_claims_of_prescription(prescription.get("id"), "ORDER_CANCELED", clock=now())
        recompute_drug_quiet(prescription.get("drug_id"), now())
    return _object(order), 200


def list_price_orders(ctx, price_id):
    find("prices", price_id)
    records = [
        order
        for order in store.orders.values()
        if order.get("source_price_id") == price_id or order.get("sub_source_price_id") == price_id
    ]
    return _array(ctx, ordered_by_created(records)), 200


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

def list_order_shipments(ctx, order_id):
    order = find("orders", order_id)
    prescription = get("prescriptions", order.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    return _array(ctx, ordered_by_seq(shipments_of_order(order_id), "shipment_seq")), 200


def list_request_shipments(ctx, request_id):
    find("requests", request_id)
    return _array(ctx, ordered_by_created(of_parent("shipments", "request_id", request_id))), 200


def list_shipments(ctx):
    records = list(store.shipments.values())
    order_id = ctx.query("order_id")
    request_id = ctx.query("request_id")
    if order_id:
        records = [rec for rec in records if rec.get("order_id") == order_id]
    if request_id:
        records = [rec for rec in records if rec.get("request_id") == request_id]
    return _array(ctx, ordered_by_created(records)), 200


def get_shipment_summary(ctx, shipment_id):
    shipment = find("shipments", shipment_id)
    order = get("orders", shipment.get("order_id"))
    prescription = get("prescriptions", (order or {}).get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    return _object(
        {
            "shipment_id": shipment.get("id"),
            "order_id": shipment.get("order_id"),
            "shipment_seq": shipment.get("shipment_seq"),
            "status": shipment.get("status"),
            "dispatch_at": shipment.get("dispatch_at"),
            "delivery_at": shipment.get("delivery_at"),
        }
    ), 200


def _int_or_none(value):
    from resources import _as_int

    if isinstance(value, bool):
        return None
    return _as_int(value)