"""Domain constants, calculations, roll-up recomputes and cascade helpers."""
from decimal import Decimal

from core import (
    D, by_created, ceil_int, cents, d2, db, dsum, epoch_seconds, fail, floor2,
    iso, new_record, parse_instant, r2, touch,
)

# --------------------------------------------------------------------------
# Pinned constants (PRD 3.1 - 3.8)
# --------------------------------------------------------------------------
MOISTURE_REFERENCE_PCT = Decimal("15.0")
MOISTURE_MULTIPLIER_MIN = Decimal("0.80")
MOISTURE_MULTIPLIER_MAX = Decimal("1.00")

VOLUME_DISCOUNT_TIERS = (
    (0, 100000, Decimal("0.0")),
    (100000, 250000, Decimal("3.0")),
    (250000, None, Decimal("6.0")),
)

MIN_LOAD_FEE_CENTS = 7500
MIN_LOAD_THRESHOLD_CENTS = 25000
DELIVERY_RATE_CENTS_PER_MILE = Decimal("425")
DELIVERY_BASE_CENTS_BY_AXLE = {"SINGLE": 6500, "TANDEM": 9500, "TRI_AXLE": 13500}
MAX_AXLE_BY_ACCESS_CLASS = {
    "CLASS_A": "TRI_AXLE",
    "CLASS_B": "TANDEM",
    "CLASS_C": "SINGLE",
}
DRIVEWAY_VOLUME_CAP_CY = {
    "CLASS_A": Decimal("999.0"),
    "CLASS_B": Decimal("12.0"),
    "CLASS_C": Decimal("6.0"),
}
ACCESS_RANK = {"CLASS_A": 3, "CLASS_B": 2, "CLASS_C": 1}

DRIVEWAY_DAMAGE_DEDUCTIBLE_CENTS = 15000
SPILLAGE_CLEANUP_CAP_CENTS = 40000

BAGS_PER_CONTAINER = 48
CONTAINER_TYPE_BY_CATEGORY = {
    "MULCH": "PALLET",
    "AGGREGATE": "PALLET",
    "SOIL": "SUPER_SACK",
    "SALT": "SALT_TOTE",
}
CONTAINER_DEPOSIT_BY_TYPE = {"PALLET": 2500, "SUPER_SACK": 6000, "SALT_TOTE": 4500}
CONTAINER_GRACE_SECONDS = 30 * 86400
SECONDS_PER_WEEK = 604800
DECAY_PER_WEEK = Decimal("0.25")

WILL_CALL_STAGING_CAPACITY = 2
TURNAROUND_BUFFER_SECONDS = 45 * 60
CREDIT_RELEASE_RATIO = Decimal("0.90")

CREDIT_CONSUMING_FULFILLMENT = ("CONFIRMED", "ALLOCATED", "FULFILLED")
CREDIT_CONSUMING_SETTLEMENT = ("UNBILLED", "INVOICED", "CREDIT_MEMO_ISSUED")
RESERVING_FULFILLMENT = ("CONFIRMED", "ALLOCATED")


# --------------------------------------------------------------------------
# Relationship accessors
# --------------------------------------------------------------------------
def lines_of(order_id):
    return by_created([l for l in db.order_lines.values()
                       if l["material_order_id"] == order_id])


def bulk_lines_of(order_id):
    return [l for l in lines_of(order_id) if l["form"] == "BULK"]


def bagged_lines_of(order_id):
    return [l for l in lines_of(order_id) if l["form"] == "BAGGED"]


def orders_of_account(account_id):
    return by_created([o for o in db.material_orders.values()
                       if o["contractor_account_id"] == account_id])


def orders_of_po(po_id):
    return by_created([o for o in db.material_orders.values()
                       if o.get("job_purchase_order_id") == po_id])


def loads_of(order_id):
    return by_created([l for l in db.delivery_loads.values()
                       if l["material_order_id"] == order_id])


def tickets_of(order_id):
    return by_created([t for t in db.will_call_tickets.values()
                       if t["material_order_id"] == order_id])


def containers_of(order_id):
    return by_created([c for c in db.container_returns.values()
                       if c["material_order_id"] == order_id])


def claims_of(order_id):
    return by_created([c for c in db.claim_cases.values()
                       if c["material_order_id"] == order_id])


def lots_of_material(material_id):
    return by_created([l for l in db.inventory_lots.values()
                       if l["material_id"] == material_id])


def account_of_order(order):
    return db.get("contractor_accounts", order["contractor_account_id"])


def order_value_cents(order):
    """Final total where one exists, quoted total otherwise."""
    final = order.get("final_total_cents")
    if final is None:
        return int(order.get("quoted_total_cents") or 0)
    return int(final)


# --------------------------------------------------------------------------
# calculations.inventory_net_sellable_volume  (PRD 3.2)
# --------------------------------------------------------------------------
def moisture_multiplier(moisture_pct):
    raw = Decimal(1) - ((D(moisture_pct) - MOISTURE_REFERENCE_PCT) / Decimal(100))
    if raw < MOISTURE_MULTIPLIER_MIN:
        return MOISTURE_MULTIPLIER_MIN
    if raw > MOISTURE_MULTIPLIER_MAX:
        return MOISTURE_MULTIPLIER_MAX
    return raw


def lot_net_sellable(lot, material):
    shrink = D(material["shrinkage_factor"])
    gross = D(lot["gross_cubic_yards"])
    if lot["basis"] == "INTAKE":
        product = gross * (Decimal(1) - shrink) * moisture_multiplier(
            lot["moisture_pct_at_intake"])
    else:
        remaining = gross - D(lot["withdrawn_gross_cubic_yards"])
        product = remaining * (Decimal(1) - shrink / Decimal(2)) * moisture_multiplier(
            lot["current_moisture_pct"])
    return r2(product)


def lot_withdrawn(lot):
    total = Decimal(0)
    for load in db.delivery_loads.values():
        if load.get("inventory_lot_id") == lot["id"] and load["status"] == "DELIVERED":
            total += D(load.get("actual_net_cubic_yards") or 0)
            total += D(load.get("spillage_cubic_yards") or 0)
    for ticket in db.will_call_tickets.values():
        if ticket.get("inventory_lot_id") == lot["id"] and ticket["status"] in (
                "LOADED", "RELEASED"):
            total += D(ticket.get("loaded_cubic_yards") or 0)
    return r2(total)


def lot_reserved(lot):
    total = Decimal(0)
    for line in db.order_lines.values():
        if line.get("inventory_lot_id") != lot["id"]:
            continue
        order = db.get("material_orders", line["material_order_id"])
        if order is None or order["fulfillment_status"] not in RESERVING_FULFILLMENT:
            continue
        total += D(line["line_volume_cubic_yards"]) - D(
            line["delivered_volume_cubic_yards"])
    return r2(total)


def material_available_net(material):
    total = Decimal(0)
    for lot in lots_of_material(material["id"]):
        if lot["status"] != "AVAILABLE":
            continue
        total += D(lot["net_sellable_cubic_yards"]) - D(lot["reserved_cubic_yards"])
    return r2(total)


def effective_density(material):
    """PRD 3.5: density scaled by the material's moisture, 2dp half up."""
    factor = Decimal(1) + ((D(material["moisture_pct"]) - MOISTURE_REFERENCE_PCT)
                           / Decimal(100))
    return r2(D(material["density_lb_per_cubic_yard"]) * factor)


# --------------------------------------------------------------------------
# Price book (PRD 3.1) -- row in force at an instant
# --------------------------------------------------------------------------
def price_row_in_force(material_id, instant):
    best = None
    for row in db.price_schedules.values():
        if row["material_id"] != material_id:
            continue
        if row["effective_from"] > instant:
            continue
        if best is None or row["effective_from"] > best["effective_from"] or (
                row["effective_from"] == best["effective_from"]
                and row["_seq"] > best["_seq"]):
            best = row
    return best


def _bulk_basis(line, instant):
    """Returns (unrounded unit basis in cents, surcharge pct) for a bulk line."""
    contract_id = line.get("prebuy_contract_id")
    if contract_id:
        contract = db.get("prebuy_contracts", contract_id)
        if contract is not None:
            return D(contract["locked_price_per_cubic_yard_cents"]), Decimal(0)
    row = price_row_in_force(line["material_id"], instant)
    if row is None:
        return Decimal(0), Decimal(0)
    return D(row["bulk_price_per_cubic_yard_cents"]), D(row["seasonal_surcharge_pct"])


def _bagged_unit(line, instant):
    row = price_row_in_force(line["material_id"], instant)
    if row is None:
        return Decimal(0)
    return D(row["bagged_price_per_bag_cents"])


# --------------------------------------------------------------------------
# calculations.order_line_pricing (PRD 3.4)
# --------------------------------------------------------------------------
def price_lines_at_confirm(order, instant):
    for line in lines_of(order["id"]):
        if line["form"] == "BULK":
            basis, surcharge = _bulk_basis(line, instant)
            factor = Decimal(1) + surcharge / Decimal(100)
            line["unit_price_cents"] = cents(basis * factor)
            line["line_price_cents"] = cents(D(line["quantity"]) * basis * factor)
        else:
            unit = _bagged_unit(line, instant)
            line["unit_price_cents"] = cents(unit)
            line["line_price_cents"] = int(unit * D(line["quantity"]))


def price_lines_final(order, instant):
    """Final basis: bulk lines repriced on delivered volume; bagged untouched."""
    for line in lines_of(order["id"]):
        if line["form"] == "BULK":
            basis, surcharge = _bulk_basis(line, instant)
            factor = Decimal(1) + surcharge / Decimal(100)
            final = cents(D(line["delivered_volume_cubic_yards"]) * basis * factor)
        else:
            final = int(line["line_price_cents"] or 0)
        if line.get("final_line_price_cents") != final:
            line["final_line_price_cents"] = final
            touch(line)


# --------------------------------------------------------------------------
# calculations.order_charge_assembly (PRD 3.4, eight pinned steps)
# --------------------------------------------------------------------------
def volume_discount_pct(bulk_subtotal_cents):
    for lower, upper, pct in VOLUME_DISCOUNT_TIERS:
        if bulk_subtotal_cents >= lower and (upper is None
                                             or bulk_subtotal_cents < upper):
            return pct
    return Decimal("0.0")


def assemble_charges(order, price_key, axle_class):
    lines = lines_of(order["id"])
    bulk_subtotal = 0
    bagged_subtotal = 0
    for line in lines:
        amount = line.get(price_key)
        amount = 0 if amount is None else int(amount)
        if line["form"] == "BULK":
            bulk_subtotal += amount
        else:
            bagged_subtotal += amount
    pct = volume_discount_pct(bulk_subtotal)
    discount = cents(D(bulk_subtotal) * pct / Decimal(100))
    discounted_bulk = bulk_subtotal - discount
    delivery = order["fulfillment_mode"] == "DELIVERY"
    if delivery and bulk_subtotal > 0 and discounted_bulk < MIN_LOAD_THRESHOLD_CENTS:
        min_load_fee = MIN_LOAD_FEE_CENTS
    else:
        min_load_fee = 0
    if not delivery:
        delivery_fee = 0
    else:
        base = DELIVERY_BASE_CENTS_BY_AXLE.get(axle_class, 0)
        miles = D(order.get("delivery_distance_miles") or 0)
        delivery_fee = base + cents(miles * DELIVERY_RATE_CENTS_PER_MILE)
    total = discounted_bulk + bagged_subtotal + min_load_fee + delivery_fee
    return {
        "bulk_subtotal_cents": bulk_subtotal,
        "bagged_subtotal_cents": bagged_subtotal,
        "volume_discount_pct": float(pct),
        "volume_discount_cents": discount,
        "min_load_fee_cents": min_load_fee,
        "delivery_fee_cents": delivery_fee,
        "total_cents": total,
    }


def quote_axle_class(order):
    return MAX_AXLE_BY_ACCESS_CLASS.get(order.get("driveway_access_class"))


def apply_charges(order, figures, total_field):
    for key in ("bulk_subtotal_cents", "bagged_subtotal_cents", "volume_discount_pct",
                "volume_discount_cents", "min_load_fee_cents", "delivery_fee_cents"):
        order[key] = figures[key]
    order[total_field] = figures["total_cents"]


# --------------------------------------------------------------------------
# calculations.truck_load_fit (PRD 3.5)
# --------------------------------------------------------------------------
def load_fit(planned_cy, truck, material, access_class):
    """Returns (planned_payload_lb, max_allowed_cubic_yards).

    planned_payload_lb is None when no material is pinned (nothing to weigh).
    """
    ceilings = [D(truck["bed_capacity_cubic_yards"])]
    cap = DRIVEWAY_VOLUME_CAP_CY.get(access_class)
    if cap is not None:
        ceilings.append(cap)
    payload = None
    if material is not None:
        density = D(effective_density(material))
        if density > 0:
            payload = cents(D(planned_cy) * density)
            ceilings.append(D(floor2(D(truck["max_payload_lb"]) / density)))
    return payload, r2(min(ceilings))


def driveway_cap(access_class):
    return DRIVEWAY_VOLUME_CAP_CY.get(access_class)


def pinned_material_for_order(order):
    """Material of the lot allocated to the order's earliest-created bulk line."""
    for line in bulk_lines_of(order["id"]):
        return db.get("materials", line["material_id"])
    return None


def pinned_lot_for_order(order):
    for line in bulk_lines_of(order["id"]):
        lot_id = line.get("inventory_lot_id")
        if lot_id:
            return db.get("inventory_lots", lot_id)
        return None
    return None


# --------------------------------------------------------------------------
# Roll-up recomputes.  Each advances version/updated_at only on real movement.
# --------------------------------------------------------------------------
def recompute_lot(lot):
    material = db.get("materials", lot["material_id"])
    changed = False
    withdrawn = lot_withdrawn(lot)
    if lot["withdrawn_gross_cubic_yards"] != withdrawn:
        lot["withdrawn_gross_cubic_yards"] = withdrawn
        changed = True
    net = lot_net_sellable(lot, material)
    if lot["net_sellable_cubic_yards"] != net:
        lot["net_sellable_cubic_yards"] = net
        changed = True
    reserved = lot_reserved(lot)
    if lot["reserved_cubic_yards"] != reserved:
        lot["reserved_cubic_yards"] = reserved
        changed = True
    if changed:
        touch(lot)
    return changed


def maybe_deplete_lot(lot):
    if lot["status"] != "AVAILABLE":
        return False
    if D(lot["net_sellable_cubic_yards"]) - D(lot["withdrawn_gross_cubic_yards"]) <= 0:
        lot["status"] = "DEPLETED"
        touch(lot)
        return True
    return False


def recompute_lots_of_order(order):
    seen = []
    for line in lines_of(order["id"]):
        lot_id = line.get("inventory_lot_id")
        if lot_id and lot_id not in seen:
            seen.append(lot_id)
    for lot_id in seen:
        lot = db.get("inventory_lots", lot_id)
        if lot is not None:
            recompute_lot(lot)


def credit_used_cents(account):
    total = 0
    for order in orders_of_account(account["id"]):
        if order["fulfillment_status"] not in CREDIT_CONSUMING_FULFILLMENT:
            continue
        if order["settlement_status"] not in CREDIT_CONSUMING_SETTLEMENT:
            continue
        total += order_value_cents(order) - int(order.get("credit_memo_cents") or 0)
    return total


def pallet_deposit_balance_cents(account):
    total = 0
    for order in orders_of_account(account["id"]):
        for record in containers_of(order["id"]):
            total += (int(record["issued_count"]) * int(record["deposit_per_unit_cents"])
                      - int(record["refund_cents"]) - int(record["forfeited_cents"]))
    return total


def recompute_account(account):
    changed = False
    used = credit_used_cents(account)
    if account["credit_used_cents"] != used:
        account["credit_used_cents"] = used
        changed = True
    available = int(account["credit_limit_cents"]) - used
    if account["credit_available_cents"] != available:
        account["credit_available_cents"] = available
        changed = True
    deposit = pallet_deposit_balance_cents(account)
    if account["pallet_deposit_balance_cents"] != deposit:
        account["pallet_deposit_balance_cents"] = deposit
        changed = True
    if changed:
        touch(account)
    return changed


def credit_release_threshold(limit_cents):
    return cents(D(limit_cents) * CREDIT_RELEASE_RATIO)


def evaluate_credit_posture(account, standalone=True):
    """Hysteresis band of PRD 3.3.  Returns the new status when it moved."""
    used = int(account["credit_used_cents"])
    limit = int(account["credit_limit_cents"])
    if account["account_status"] == "ACTIVE":
        if used > limit:
            account["account_status"] = "CREDIT_HOLD"
            if standalone:
                touch(account)
            cancel_queued_tickets_for_account(account)
            return "CREDIT_HOLD"
    elif account["account_status"] == "CREDIT_HOLD":
        if used <= credit_release_threshold(limit):
            account["account_status"] = "ACTIVE"
            if standalone:
                touch(account)
            return "ACTIVE"
    return None


def recompute_po(po):
    committed = 0
    for order in orders_of_po(po["id"]):
        if order["fulfillment_status"] not in CREDIT_CONSUMING_FULFILLMENT:
            continue
        committed += order_value_cents(order) - int(order.get("credit_memo_cents") or 0)
    if po["committed_cents"] != committed:
        po["committed_cents"] = committed
        touch(po)
    if po["status"] == "OPEN" and committed >= int(po["po_limit_cents"]):
        po["status"] = "EXHAUSTED"
        touch(po)
    elif po["status"] == "EXHAUSTED" and committed < int(po["po_limit_cents"]):
        po["status"] = "OPEN"
        touch(po)


def recompute_prebuy(contract):
    drawn = Decimal(0)
    for line in db.order_lines.values():
        if line.get("prebuy_contract_id") != contract["id"]:
            continue
        order = db.get("material_orders", line["material_order_id"])
        if order is None or order["fulfillment_status"] not in (
                CREDIT_CONSUMING_FULFILLMENT):
            continue
        drawn += D(line["line_volume_cubic_yards"])
    drawn_value = r2(drawn)
    remaining = r2(D(contract["contracted_cubic_yards"]) - D(drawn_value))
    changed = False
    if contract["drawn_cubic_yards"] != drawn_value:
        contract["drawn_cubic_yards"] = drawn_value
        changed = True
    if contract["remaining_cubic_yards"] != remaining:
        contract["remaining_cubic_yards"] = remaining
        changed = True
    if changed:
        touch(contract)
    if contract["status"] == "ACTIVE" and D(remaining) <= 0:
        contract["status"] = "EXHAUSTED"
        touch(contract)
    elif contract["status"] == "EXHAUSTED" and D(remaining) > 0:
        if clock_date() <= contract["season_end_date"]:
            contract["status"] = "ACTIVE"
            touch(contract)


def recompute_prebuys_of_order(order):
    seen = []
    for line in lines_of(order["id"]):
        contract_id = line.get("prebuy_contract_id")
        if contract_id and contract_id not in seen:
            seen.append(contract_id)
    for contract_id in seen:
        contract = db.get("prebuy_contracts", contract_id)
        if contract is not None:
            recompute_prebuy(contract)


def clock_date():
    return db.clock.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Order fulfilment transitions shared by the delivery and will-call paths
# --------------------------------------------------------------------------
def evaluate_allocate(order):
    """CONFIRMED -> ALLOCATED on the first load planned or ticket staged."""
    if order["fulfillment_status"] == "CONFIRMED":
        order["fulfillment_status"] = "ALLOCATED"
        touch(order)
        return True
    return False


def evaluate_revert(order):
    """ALLOCATED -> CONFIRMED once nothing physical is committed (PRD 3.5)."""
    if order["fulfillment_status"] != "ALLOCATED":
        return False
    for load in loads_of(order["id"]):
        if load["status"] in ("PLANNED", "DISPATCHED"):
            return False
    for ticket in tickets_of(order["id"]):
        if ticket["status"] in ("STAGED", "LOADING", "LOADED"):
            return False
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return True


def cancel_queued_tickets_for_account(account):
    """Entering CREDIT_HOLD cancels every QUEUED ticket of the account."""
    affected = []
    for order in orders_of_account(account["id"]):
        for ticket in tickets_of(order["id"]):
            if ticket["status"] == "QUEUED":
                ticket["status"] = "CANCELLED"
                touch(ticket)
                if order["id"] not in [o["id"] for o in affected]:
                    affected.append(order)
    for order in affected:
        evaluate_revert(order)
        recompute_lots_of_order(order)


def distribute_delivered_volume(order, volume):
    """created_at ascending waterfall; leftover lands on the newest bulk line."""
    bulk = bulk_lines_of(order["id"])
    if not bulk:
        return
    remaining = D(volume)
    updated = {}
    for line in bulk:
        shortfall = D(line["line_volume_cubic_yards"]) - D(
            line["delivered_volume_cubic_yards"])
        if shortfall < 0:
            shortfall = Decimal(0)
        take = remaining if remaining < shortfall else shortfall
        if take > 0:
            updated[line["id"]] = D(updated.get(
                line["id"], D(line["delivered_volume_cubic_yards"]))) + take
            remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        last = bulk[-1]
        base = updated.get(last["id"], D(last["delivered_volume_cubic_yards"]))
        updated[last["id"]] = base + remaining
    for line in bulk:
        if line["id"] in updated:
            new_value = r2(updated[line["id"]])
            if line["delivered_volume_cubic_yards"] != new_value:
                line["delivered_volume_cubic_yards"] = new_value
                touch(line)


def outstanding_bulk_balance(order):
    total = Decimal(0)
    for line in bulk_lines_of(order["id"]):
        total += (D(line["line_volume_cubic_yards"])
                  - D(line["delivered_volume_cubic_yards"]))
    return total


# --------------------------------------------------------------------------
# calculations.container_deposit_refund (PRD 3.8)
# --------------------------------------------------------------------------
def create_container_return(order, issued_count=None):
    bagged = bagged_lines_of(order["id"])
    if not bagged:
        return None
    if containers_of(order["id"]):
        return None
    material = db.get("materials", bagged[0]["material_id"])
    if material is None:
        return None
    container_type = CONTAINER_TYPE_BY_CATEGORY.get(material["seasonal_category"])
    if container_type is None:
        return None
    if issued_count is None:
        total_bags = dsum(line["quantity"] for line in bagged)
        issued_count = ceil_int(total_bags / D(BAGS_PER_CONTAINER))
    issued_count = int(issued_count)
    if issued_count < 1:
        return None
    record = new_record(
        material_order_id=order["id"],
        container_type=container_type,
        issued_count=issued_count,
        returned_count=0,
        deposit_per_unit_cents=CONTAINER_DEPOSIT_BY_TYPE[container_type],
        issued_at=db.clock,
        last_received_at=None,
        refund_cents=0,
        forfeited_cents=0,
        status="OUTSTANDING",
    )
    return db.insert("container_returns", record)


def refund_delta_cents(record, returned_count, received_at):
    late_seconds = (epoch_seconds(received_at) - epoch_seconds(record["issued_at"])
                    - CONTAINER_GRACE_SECONDS)
    if late_seconds < 0:
        late_seconds = 0
    weeks_late = ceil_int(D(late_seconds) / D(SECONDS_PER_WEEK))
    multiplier = Decimal(1) - DECAY_PER_WEEK * D(weeks_late)
    if multiplier < 0:
        multiplier = Decimal(0)
    return cents(D(returned_count) * D(record["deposit_per_unit_cents"]) * multiplier)


def full_deposit_cents(record):
    return int(record["issued_count"]) * int(record["deposit_per_unit_cents"])


# --------------------------------------------------------------------------
# calculations.claim_settlement_waterfall (PRD 3.7)
# --------------------------------------------------------------------------
def claim_payable_cap(claim, order, approved_cents):
    claim_type = claim["claim_type"]
    if claim_type == "DRIVEWAY_DAMAGE":
        deductible = DRIVEWAY_DAMAGE_DEDUCTIBLE_CENTS
        load_id = claim.get("delivery_load_id")
        if load_id:
            load = db.get("delivery_loads", load_id)
            if load is not None and load.get("driveway_protection_used") is False:
                deductible = 0
        payable = approved_cents - deductible
        return payable if payable > 0 else 0
    if claim_type == "SPILLAGE":
        return min(approved_cents, SPILLAGE_CLEANUP_CAP_CENTS)
    return min(approved_cents, order_value_cents(order))


def claim_waterfall(claim, order, approved_cents):
    payable = claim_payable_cap(claim, order, approved_cents)
    remaining = payable
    outstanding = (order_value_cents(order)
                   - int(order.get("credit_memo_cents") or 0)
                   - int(order.get("paid_amount_cents") or 0))
    if outstanding < 0:
        outstanding = 0
    invoice_offset = min(remaining, outstanding)
    remaining -= invoice_offset
    exposure = 0
    for record in containers_of(order["id"]):
        exposure += int(record["forfeited_cents"])
    deposit_offset = min(remaining, exposure)
    remaining -= deposit_offset
    goodwill = remaining if remaining > 0 else 0
    return {
        "payable_cents": payable,
        "invoice_offset_cents": invoice_offset,
        "deposit_offset_cents": deposit_offset,
        "goodwill_credit_cents": goodwill,
    }


# --------------------------------------------------------------------------
# Will-call queue ranking (PRD 3.6)
# --------------------------------------------------------------------------
def ticket_priority_class(ticket):
    for line in lines_of(ticket["material_order_id"]):
        if line.get("prebuy_contract_id"):
            return 2
    return 1


def _queue_sort_key(ticket):
    return (-ticket_priority_class(ticket), ticket["requested_pickup_at"],
            ticket["_seq"])


def queued_tickets_ranked():
    queued = [t for t in db.will_call_tickets.values() if t["status"] == "QUEUED"]
    return sorted(queued, key=_queue_sort_key)


def ticket_queue_position(ticket):
    if ticket["status"] != "QUEUED":
        return None
    for index, row in enumerate(queued_tickets_ranked()):
        if row["id"] == ticket["id"]:
            return index + 1
    return None


def stage_candidates():
    candidates = []
    for ticket in db.will_call_tickets.values():
        if ticket["status"] != "QUEUED":
            continue
        order = db.get("material_orders", ticket["material_order_id"])
        if order is None or order["fulfillment_status"] not in RESERVING_FULFILLMENT:
            continue
        account = account_of_order(order)
        if account is None or account["account_status"] != "ACTIVE":
            continue
        if ticket["requested_pickup_at"] > db.clock:
            continue
        candidates.append(ticket)
    return sorted(candidates, key=_queue_sort_key)


# --------------------------------------------------------------------------
# Final-basis money, shared by the delivery close-out and the will-call release
# --------------------------------------------------------------------------
def finalize_order_money(order, instant, axle_class):
    """Reprices bulk lines on delivered volume and writes final_total_cents.

    The final basis re-runs the same eight assembly steps, so the published
    breakdown fields are rewritten from the final figures; only the total lands
    in `final_total_cents` instead of `quoted_total_cents`.
    """
    price_lines_final(order, instant)
    figures = assemble_charges(order, "final_line_price_cents", axle_class)
    apply_charges(order, figures, "final_total_cents")
    return figures


def order_fully_delivered(order):
    for line in bulk_lines_of(order["id"]):
        if D(line["delivered_volume_cubic_yards"]) < D(line["line_volume_cubic_yards"]):
            return False
    return True


def collapse_line_versions(lines, before):
    """Keeps one version bump per line for a single cascade hop."""
    for line in lines:
        base = before.get(line["id"])
        if base is None:
            continue
        if line["version"] > base + 1:
            line["version"] = base + 1
