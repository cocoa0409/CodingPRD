"""The PartOrder workflow: authoring, pricing, confirmation, allocation,
picking, delivery, return and void (PRD 3.3, 3.4, 3.4 rollback)."""

from datetime import timedelta

import db
from errors import ApiError, bad_request
from middleware import (
    enum_field, int_field, iso_field, line_items_field, number_field,
    optional, require_fields, string_field,
)
from money import round_half_up, to_decimal
from services import calc, common, ledger

SERVICE_LEVELS = ("DELIVERY_DESK", "SHOP_DELIVERY", "HUB_DAILY", "HOTSHOT")


# ---------------------------------------------------------------------------
# payload helpers
# ---------------------------------------------------------------------------

def _lines_from_body(body, required=True):
    lines = line_items_field(body, "line_items", required=required)
    if lines is None:
        return None
    out = []
    for entry in lines:
        if "part_id" not in entry or entry.get("part_id") is None:
            raise ApiError("ERR_INVALID_REQUEST", "Each order line needs a part_id.")
        if "quantity" not in entry or entry.get("quantity") is None:
            raise ApiError("ERR_INVALID_REQUEST", "Each order line needs a quantity.")
        try:
            quantity = int(entry["quantity"])
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "quantity must be an integer.")
        record_id = entry.get("record_id")
        out.append({
            "part_id": str(entry["part_id"]),
            "quantity": quantity,
            "unit_price_cents": entry.get("unit_price_cents"),
            "record_id": record_id,
        })
        if entry.get("unit_price_cents") is not None:
            try:
                out[-1]["unit_price_cents"] = int(entry["unit_price_cents"])
            except (TypeError, ValueError):
                raise ApiError("ERR_INVALID_REQUEST", "unit_price_cents must be an integer.")
    return out


def validate_line_references(lines):
    """Every order line's record_id must be greater than zero, when supplied."""
    for line in lines:
        record_id = line.get("record_id")
        if record_id is None:
            continue
        try:
            value = int(record_id)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_LINE_REFERENCE")
        if value <= 0:
            raise ApiError("ERR_INVALID_LINE_REFERENCE")


def validate_destination(body, order_id):
    destination = optional(body, "destination_id")
    if destination is None:
        return None
    if order_id is not None and str(destination) != str(order_id):
        raise ApiError("ERR_DESTINATION_MISMATCH")
    return str(destination)


def validate_hazardous(lines, account):
    """A hazardous part may not be added to a DELIVERY_DESK order."""
    if account.get("delivery_service_level") != "DELIVERY_DESK":
        return
    for line in lines:
        part = calc.resolved_line_part(line)
        if part is not None and part.get("is_hazardous"):
            raise ApiError("ERR_HAZARDOUS_PART_NOT_DELIVERABLE")


def validate_fitment(lines, vehicle_id):
    if vehicle_id is None:
        return
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    for line in lines:
        part = db.parts.get(line.get("part_id"))
        if part is None:
            raise ApiError("ERR_PART_NOT_FOUND")
        if not common.line_fits(part, vehicle):
            raise ApiError("ERR_FITMENT_MISMATCH")


def validate_stock(order, account, lines):
    """Every line must be reservable from the selected source."""
    for index, line in enumerate(lines):
        store_id = _source_for_line(order, index)
        if store_id is None:
            raise ApiError("ERR_NO_FULFILLMENT_SOURCE")
        part = calc.resolved_line_part(line)
        if part is None:
            raise ApiError("ERR_PART_NOT_FOUND")
        if common.available_units(store_id, part["id"]) < (line.get("quantity") or 0):
            raise ApiError("ERR_INSUFFICIENT_STOCK")


def _source_for_line(order, index):
    per_line = order.get("line_source_store_ids") or []
    if index < len(per_line) and per_line[index]:
        return per_line[index]
    return order.get("source_store_id")


def _assign_sources(order, route, store_id, line_count):
    order["source_store_id"] = store_id
    order["line_source_store_ids"] = [store_id] * line_count


# ---------------------------------------------------------------------------
# order authoring
# ---------------------------------------------------------------------------

def create_order(ctx, body):
    require_fields(body, ["account_id", "line_items"])
    account = db.accounts.get(str(body["account_id"]))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    lines = _lines_from_body(body, required=True)
    if not lines:
        bad_request("An order needs at least one line.")
    vehicle_id = optional(body, "vehicle_id")
    if vehicle_id is not None and db.vehicles.get(str(vehicle_id)) is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    vehicle_id = str(vehicle_id) if vehicle_id is not None else None

    # business rules, in the PRD 2.12 order
    validate_hazardous(lines, account)
    _validate_parts_exist(lines)
    validate_line_references(lines)
    destination = validate_destination(body, None)

    # the optimistic concurrency guard is the final step
    _check_account_version(body, account)

    # PRD 2.12 / 3.3: fitment is a state precondition -- the text arranges the
    # fitment and hazardous checks beside the order's own status requirement in
    # the confirmation sequence, and an order that is not in the state its
    # transition starts from reports the state error "even when a later business
    # rule would also have failed".  The reference check is therefore evaluated
    # on both the line-mutation write and the confirmation write, not at
    # creation.
    member_sequence = (account.get("order_sequence") or 0) + 1
    account["order_sequence"] = member_sequence
    band = calc.pricing_band_for(member_sequence)

    order = common.new_resource({
        "account_id": account["id"],
        "vehicle_id": vehicle_id,
        "line_items": lines,
        "member_sequence": member_sequence,
        "service_route_id": None,
        "fulfillment_route": None,
        "reserved_unit_count": 0,
        "pricing_band": band,
        "parts_subtotal_cents": 0,
        "core_charge_total_cents": 0,
        "tier_discount_cents": 0,
        "refundable_deposit_cents": 0,
        "delivery_fee_cents": 0,
        "promised_at": None,
        "delivered_at": None,
        "delivered_payment_due_at": None,
        "refundable_deposit_consumed_cents": 0,
        "order_base_cents": 0,
        "satisfaction_cents": 0,
        "status": "DRAFT",
        "shipping_address": optional(body, "shipping_address"),
        "destination_id": destination,
        "source_store_id": None,
        "line_source_store_ids": [],
        "allocation_date": None,
    })
    db.part_orders[order["id"]] = order
    order["order_base_cents"] = calc.compute_order_base(lines)
    _reprice(order)
    _reroute(order, account, provisional=True)
    calc.compute_satisfaction(order)
    common.record_audit(order)
    ledger.recompute_account(account)
    common.remember("part_orders", order["id"])
    return order


def _validate_parts_exist(lines):
    for line in lines:
        if db.parts.get(line.get("part_id")) is None:
            raise ApiError("ERR_PART_NOT_FOUND")


def _reprice(order, final=False):
    """Price the order.  DRAFT/CONFIRMED take the provisional per-line reading;
    ALLOCATED and beyond take the single order-level reading."""
    calc.price_order(order)
    order["refundable_deposit_cents"] = calc.refundable_deposit_for(order, order["account_id"])
    return order


def _reroute(order, account, provisional=False):
    lines = order.get("line_items") or []
    request_at = db.clock()
    route, store_id, store, promised, _days = calc.source_promise(
        account, lines, request_at, provisional=provisional)
    if route == "UNROUTABLE":
        # PRD 3.4's bands trade latency for availability, but when availability
        # (or the store's own ceiling) is the only condition every band fails on,
        # the order still has a house in front of it: the shop's own store.  PRD
        # 3.3 then reports the true reason through the rules that precede the
        # capacity ceiling -- `ERR_INSUFFICIENT_STOCK` for a shelf that cannot
        # supply, `ERR_CAPACITY_EXCEEDED` for one that is full -- rather than
        # withdrawing the source outright.  A shop genuinely beyond the
        # extended radius keeps the `UNROUTABLE` reading and its
        # `ERR_NO_FULFILLMENT_SOURCE` refusal.
        home = db.stores.get(account.get("home_store_id"))
        within_shop = (home is not None
                       and (home.get("delivery_radius_miles") or 0)
                       <= calc.SHOP_DELIVERY_RADIUS_MILES)
        fallback_id = order.get("source_store_id")
        if fallback_id is None and within_shop:
            fallback_id = home["id"]
        fallback_store = db.stores.get(fallback_id) if fallback_id else None
        if fallback_store is not None:
            route = calc.ROUTE_OF_TYPE.get(fallback_store.get("store_type"), "STORE")
            store_id = fallback_store["id"]
            days = 0
            promised = calc.promised_for(account, fallback_store, request_at, days)
    order["fulfillment_route"] = route
    _assign_sources(order, route, store_id, len(lines))
    order["promised_at"] = calc._fmt(promised)
    order["delivery_fee_cents"] = calc.delivery_fee(route, account.get("delivery_service_level"))
    if account.get("pricing_band") != order.get("pricing_band"):
        account["pricing_band"] = order.get("pricing_band")
    return route


def _check_account_version(body, account):
    expected = optional(body, "expected_account_version")
    if expected is None:
        return
    try:
        value = int(expected)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "expected_account_version must be an integer.")
    if value != (account.get("version") or 0):
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")


def _check_order_version(body, order):
    expected = optional(body, "expected_order_version")
    if expected is None:
        return
    try:
        value = int(expected)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "expected_order_version must be an integer.")
    if value != (order.get("version") or 0):
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")


# ---------------------------------------------------------------------------
# order update
# ---------------------------------------------------------------------------

def update_order(order, body):
    account = db.accounts.get(order["account_id"])
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    # PRD 2.12: "State preconditions follow. The target resource must be in the
    # state its transition starts from, and a state mismatch is the error the
    # caller sees even when a later business rule would also have failed."  A
    # line mutation is a DRAFT-only transition (PRD 3.3: "Modifying an existing
    # draft order ..."), so the state gate is evaluated ahead of the business
    # rules below it.
    if order.get("status") != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")

    # business rules first, in the PRD 2.12 order
    if "vehicle_id" in body:
        vehicle_id = body.get("vehicle_id")
        if vehicle_id is not None and db.vehicles.get(str(vehicle_id)) is None:
            raise ApiError("ERR_VEHICLE_NOT_FOUND")

    lines = order.get("line_items") or []
    if body.get("line_items") is not None:
        lines = _lines_from_body(body, required=True)
    vehicle_id = order.get("vehicle_id")
    if "vehicle_id" in body:
        vehicle_id = str(body["vehicle_id"]) if body.get("vehicle_id") is not None else None

    validate_hazardous(lines, account)
    validate_fitment(lines, vehicle_id)
    _validate_parts_exist(lines)
    validate_line_references(lines)
    validate_destination(body, order["id"])
    _check_tier(body, account)
    _check_order_version(body, order)
    _check_account_version(body, account)

    order["line_items"] = lines
    order["vehicle_id"] = vehicle_id
    if "shipping_address" in body:
        order["shipping_address"] = body.get("shipping_address")
    if "destination_id" in body:
        order["destination_id"] = body.get("destination_id")

    _reprice(order)
    _reroute(order, account)
    calc.compute_satisfaction(order)
    common.record_audit(order)
    ledger.recompute_account(account)
    return order


def _check_tier(body, account):
    """An order may only be priced at the band its own account has reached."""
    if "account_id" not in body:
        return
    target_id = body.get("account_id")
    if target_id is None or str(target_id) == account["id"]:
        return
    target = db.accounts.get(str(target_id))
    if target is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    if calc.pricing_band_for((target.get("order_sequence") or 0) + 1) != \
            calc.pricing_band_for((account.get("order_sequence") or 0) + 1):
        raise ApiError("ERR_ACCOUNT_TIER_MISMATCH")
    # PRD 3.3: "An order may only ever be priced at the band its own account has
    # reached", so the repoint itself is applied once the band agrees.


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------

def confirm_order(order, body):
    account = db.accounts.get(order["account_id"])
    if order.get("status") != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")
    validate_fitment(order.get("line_items") or [], order.get("vehicle_id"))
    if account.get("account_posture") != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN")
    lines = order.get("line_items") or []
    if order.get("fulfillment_route") == "UNROUTABLE":
        raise ApiError("ERR_NO_FULFILLMENT_SOURCE")
    validate_hazardous(lines, account)
    validate_line_references(lines)
    validate_destination(body, order["id"])

    # the selected reading of the routing decision, after earlier orders have
    # already been committed
    _reroute(order, account)
    if order.get("fulfillment_route") == "UNROUTABLE":
        raise ApiError("ERR_NO_FULFILLMENT_SOURCE")
    validate_stock(order, account, lines)
    _check_order_version(body, order)
    _check_account_version(body, account)

    # reserve stock, then re-check the daily ceiling in a second pass
    for index, line in enumerate(lines):
        quantity = line.get("quantity") or 0
        store_id = _source_for_line(order, index)
        part = calc.resolved_line_part(line)
        if store_id is None or part is None:
            raise ApiError("ERR_NO_FULFILLMENT_SOURCE")
        item = common.ensure_inventory(store_id, part["id"])
        common.reserve(item, quantity)
        store = db.stores.get(store_id)
        if store is not None:
            store["committed_units_today"] = (store.get("committed_units_today") or 0) + quantity
            common.record_audit(store)
    for index, line in enumerate(lines):
        store_id = _source_for_line(order, index)
        store = db.stores.get(store_id)
        if store is None:
            continue
        limit = store.get("daily_capacity_units")
        if limit is not None and (store.get("committed_units_today") or 0) > limit:
            # PRD 3.3's second pass refuses the confirmation, so the units this
            # request just reserved and committed must not survive it: the
            # failed reservation is rolled back atomically, leaving the store
            # exactly where it stood before the attempt.
            for undo in lines:
                undo_store_id = _source_for_line(order, lines.index(undo))
                undo_part = calc.resolved_line_part(undo)
                if undo_store_id is None or undo_part is None:
                    continue
                undo_quantity = undo.get("quantity") or 0
                item = common.ensure_inventory(undo_store_id, undo_part["id"])
                item["reserved_units"] = max(
                    0, (item.get("reserved_units") or 0) - undo_quantity)
                common.record_audit(item)
                undo_store = db.stores.get(undo_store_id)
                if undo_store is not None:
                    undo_store["committed_units_today"] = max(
                        0, (undo_store.get("committed_units_today") or 0) - undo_quantity)
                    common.record_audit(undo_store)
            raise ApiError("ERR_CAPACITY_EXCEEDED")

    # supersession lands on the lines at confirmation
    for line in lines:
        part = calc.resolved_line_part(line)
        if part is not None:
            line["part_id"] = part["id"]
    order["pricing_band"] = calc.pricing_band_for(order.get("member_sequence"))
    order["status"] = "CONFIRMED"
    _reprice(order)
    calc.compute_satisfaction(order)
    order["reserved_unit_count"] = sum((line.get("quantity") or 0) for line in lines)
    common.record_audit(order)
    # PRD 3.3: the counter is read and incremented at creation ("At creation the
    # order receives its identity and its provisional economics"), and "One
    # consequence of advancing order_sequence" is that "every existing PartOrder
    # on the same account whose status is DRAFT or CONFIRMED is re-priced at this
    # order's band".  Confirmation is where that consequence lands, so the
    # counter itself is not advanced a second time here.
    _reprice_siblings(account)
    ledger.recompute_account(account)
    return order


def _reprice_siblings(account):
    """Every DRAFT or CONFIRMED order on the account is re-priced at the band
    of the order whose confirmation just advanced the account's sequence."""
    for sibling in db.part_orders.values():
        if sibling.get("account_id") != account["id"]:
            continue
        if sibling.get("status") not in ("DRAFT", "CONFIRMED"):
            continue
        _reprice(sibling)
        common.record_audit(sibling)


# ---------------------------------------------------------------------------
# allocate / pick
# ---------------------------------------------------------------------------

def allocate_order(order, body):
    account = db.accounts.get(order["account_id"])
    if order.get("status") != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED")
    lines = order.get("line_items") or []
    validate_stock(order, account, lines)
    _check_same_day_slot(order, account)
    _check_order_version(body, order)
    _check_account_version(body, account)

    order["status"] = "ALLOCATED"
    calc.price_order(order)
    _reroute(order, account)
    order["allocation_date"] = _business_date(db.clock())
    common.record_audit(order)
    ledger.recompute_account(account)
    return order


def _business_date(instant):
    return instant.date().isoformat()


def _check_same_day_slot(order, account):
    """The slot is keyed on the account and the order, never on the source
    store: at most one ALLOCATED or PICKING order per member_sequence and day."""
    today = _business_date(db.clock())
    for other in db.part_orders.values():
        if other["id"] == order["id"]:
            continue
        if other.get("account_id") != account["id"]:
            continue
        if other.get("status") not in ("ALLOCATED", "PICKING"):
            continue
        if other.get("member_sequence") != order.get("member_sequence"):
            continue
        if (other.get("allocation_date") or today) == today:
            raise ApiError("ERR_SAME_DAY_SLOT_TAKEN")


def pick_order(order, body):
    if order.get("status") != "ALLOCATED":
        raise ApiError("ERR_ORDER_NOT_ALLOCATED")
    order["status"] = "PICKING"
    common.record_audit(order)
    return order


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def dispatch_order(order, body):
    if order.get("status") != "PICKING":
        raise ApiError("ERR_ORDER_NOT_PICKING")
    if order.get("service_route_id") is None:
        raise ApiError("ERR_ORDER_NOT_ON_ROUTE")
    order["status"] = "DISPATCHED"
    common.record_audit(order)
    return order


# ---------------------------------------------------------------------------
# deliver
# ---------------------------------------------------------------------------

def deliver_order(order, body=None):
    account = db.accounts.get(order["account_id"])
    # PRD 3.4 lists the three gates "the order's `status` must be `DISPATCHED`",
    # "the `RouteStop` carrying the order must be in `SEQUENCED` or `EN_ROUTE`"
    # and "the order's `delivered_at` must still be unset, because a delivered
    # order cannot be delivered a second time" -- the second-delivery refusal is
    # the one that names `ERR_ORDER_ALREADY_DELIVERED` explicitly, so a
    # delivered order reports that identifier rather than falling through to the
    # status gate it also fails.
    if order.get("delivered_at") is not None:
        raise ApiError("ERR_ORDER_ALREADY_DELIVERED")
    if order.get("status") != "DISPATCHED":
        raise ApiError("ERR_ORDER_NOT_DISPATCHED")
    stop = stop_carrying(order)
    if stop is None or stop.get("status") not in ("SEQUENCED", "EN_ROUTE"):
        raise ApiError("ERR_ROUTE_STOP_NOT_ACTIVE")
    _check_delivery_address(order, account)
    _check_route_slice(order, stop)
    _apply_delivery(order, account)
    return order


def _check_delivery_address(order, account):
    """The address must resolve to the account's own shipping address, its
    billing address, or its home store's address."""
    address = order.get("shipping_address")
    if address is None:
        return
    candidates = [account.get("shipping_address"), account.get("billing_address")]
    store = db.stores.get(account.get("home_store_id"))
    if store is not None:
        candidates.append(store.get("name"))
    if address in candidates:
        return
    raise ApiError("ERR_DELIVERY_ADDRESS_MISMATCH")


def _check_route_slice(order, stop):
    """PRD 3.4: "If several orders are dropped at the same stop, delivering one
    while another order at that stop has not yet been delivered is refused with
    `ERR_ROUTE_SLICE_INCOMPLETE`".  The slice empties from the end: the order
    that closes the stop's slice may be delivered first, and each earlier order
    is refused while a later one is still pending.  An order that was already
    pushed back off the route is not counted, so it does not block the rest."""
    slice_ids = list(stop.get("order_ids") or [])
    if order["id"] not in slice_ids:
        return
    position = slice_ids.index(order["id"])
    for sibling_id in slice_ids[position + 1:]:
        sibling = db.part_orders.get(sibling_id)
        if sibling is None or sibling.get("status") != "DISPATCHED":
            continue
        if sibling.get("delivered_at") is None:
            raise ApiError("ERR_ROUTE_SLICE_INCOMPLETE")


def _apply_delivery(order, account):
    lines = order.get("line_items") or []
    for index, line in enumerate(lines):
        quantity = line.get("quantity") or 0
        store_id = _source_for_line(order, index)
        part = calc.resolved_line_part(line)
        if store_id is None or part is None:
            continue
        item = common.inventory_item_for(store_id, part["id"])
        if item is not None:
            item["on_hand_units"] = max(0, (item.get("on_hand_units") or 0) - quantity)
            common.release_reservation(item, quantity)
        store = db.stores.get(store_id)
        if store is not None:
            store["committed_units_today"] = max(
                0, (store.get("committed_units_today") or 0) - quantity)
            common.record_audit(store)

    delivered_at = db.clock()
    order["delivered_at"] = calc._fmt(delivered_at)
    terms = account.get("credit_terms_days") or 0
    order["delivered_payment_due_at"] = calc._fmt(delivered_at + timedelta(days=terms))
    order["status"] = "DELIVERED"
    common.record_audit(order)
    ledger.recompute_account(account)
    return order


# ---------------------------------------------------------------------------
# refit
# ---------------------------------------------------------------------------

def refit_order(order, body):
    if order.get("status") != "DISPATCHED":
        raise ApiError("ERR_ORDER_NOT_DISPATCHED")
    stop = stop_carrying(order)
    if stop is None or stop.get("status") not in ("REJECTED", "MISSED"):
        raise ApiError("ERR_ROUTE_STOP_NOT_TERMINAL")
    _check_rollback_window(order)
    route_id = order.get("service_route_id")
    _detach_from_stop(order, stop)
    order["service_route_id"] = None
    order["status"] = "CONFIRMED"
    common.record_audit(order)
    route = db.service_routes.get(route_id)
    if route is not None:
        stops = common.stops_of(route_id)
        keep = [stop for stop in stops if stop.get("status") not in ("REJECTED", "MISSED")]
        db.route_stops.pop(stop["id"], None)
        calc.derive_route_geometry(route)
        common.record_audit(route)
    return order


def _check_rollback_window(order):
    """30 minutes measured from the earliest RouteStop.delivered_at on the
    route (PRD 3.4)."""
    route_id = order.get("service_route_id")
    if route_id is None:
        return
    now = db.clock()
    for stop in common.stops_of(route_id):
        delivered = calc._parse(stop.get("delivered_at"))
        if delivered is None:
            continue
        if now > delivered + timedelta(minutes=30):
            raise ApiError("ERR_WINDOW_EXPIRED")


# ---------------------------------------------------------------------------
# return
# ---------------------------------------------------------------------------

def return_order(order, body):
    account = db.accounts.get(order["account_id"])
    lines = order.get("line_items") or []
    if order.get("status") != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED")
    _check_return_window(order, account)
    _check_returnable(lines)
    validate_line_references(lines)

    order["status"] = "RETURNED"
    order["reserved_unit_count"] = 0
    order["refundable_deposit_consumed_cents"] = 0
    common.record_audit(order)
    ledger.recompute_account(account)

    if _has_core(lines):
        from services import core
        core.open_core_return(order, account, auto=True)
    return order


def _check_return_window(order, account):
    delivered = calc._parse(order.get("delivered_at"))
    if delivered is None:
        return
    terms = account.get("credit_terms_days") or 0
    window_end = delivered + timedelta(days=terms + 30)
    if db.clock() > window_end:
        raise ApiError("ERR_RETURN_WINDOW_CLOSED")


def _check_returnable(lines):
    for line in lines:
        part = calc.resolved_line_part(line)
        if part is None:
            raise ApiError("ERR_PART_NOT_FOUND")
        if not part.get("is_returnable", True):
            raise ApiError("ERR_PART_NOT_RETURNABLE")


def _has_core(lines):
    for line in lines:
        part = calc.resolved_line_part(line)
        if part is not None and (part.get("core_charge_cents") or 0) > 0:
            return True
    return False


# ---------------------------------------------------------------------------
# void
# ---------------------------------------------------------------------------

def void_order(order, body, ctx=None):
    status = order.get("status")
    account = db.accounts.get(order["account_id"])
    if ctx is not None and status in ("ALLOCATED", "PICKING") and ctx.role != "CreditAnalyst":
        raise ApiError("ERR_ORDER_NOT_VOIDABLE")
    if status not in ("DRAFT", "CONFIRMED", "ALLOCATED", "PICKING"):
        raise ApiError("ERR_ORDER_NOT_VOIDABLE")
    ledger.prepare_confirmed_void(order, account)
    ledger.recompute_account(account)
    return order


# ---------------------------------------------------------------------------
# route membership
# ---------------------------------------------------------------------------

def stop_carrying(order):
    route_id = order.get("service_route_id")
    if route_id is None:
        return None
    for stop in common.stops_of(route_id):
        if order["id"] in (stop.get("order_ids") or []):
            return stop
    return None


def commit_order_to_route(order, stop):
    order["service_route_id"] = stop["route_id"]
    ids = list(stop.get("order_ids") or [])
    if order["id"] not in ids:
        ids.append(order["id"])
    stop["order_ids"] = ids
    common.record_audit(order)
    common.record_audit(stop)
    route = db.service_routes.get(stop["route_id"])
    if route is not None:
        common.record_audit(route)
    return order


def _detach_from_stop(order, stop):
    ids = [oid for oid in (stop.get("order_ids") or []) if oid != order["id"]]
    stop["order_ids"] = ids
    common.record_audit(stop)


def detach_order(order):
    stop = stop_carrying(order)
    if stop is not None:
        _detach_from_stop(order, stop)
    order["service_route_id"] = None
    common.record_audit(order)


def orders_at_stop(stop):
    out = []
    for order_id in stop.get("order_ids") or []:
        order = db.part_orders.get(order_id)
        if order is not None:
            out.append(order)
    return out


def recompute_account_orders(account):
    ledger.recompute_account(account)
    return account


def refresh_after_order_write(account):
    return recompute_account_orders(account)