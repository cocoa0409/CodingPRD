"""Store-aware derivations, aggregates and cascades (PRD 2.10, section 3)."""
from decimal import Decimal

import calc
from store import (
    all_rows,
    base_row,
    db,
    hours,
    minutes,
    now,
    sort_key,
    touch,
)

HELD_BATCH_STATUSES = ("CLAIMED", "SHOPPING", "CHECKED_OUT")
CONCURRENCY_STATUSES = ("OFFERED", "CLAIMED", "SHOPPING")
PRICED_LINE_STATUSES = ("PICKED", "REPLACED")


# --- lookups ----------------------------------------------------------------
def item_of(line):
    return db.catalog_items.get(line["catalog_item_id"])


def order_of(line):
    return db.orders.get(line["order_id"])


def retailer_of(order):
    return db.retailers.get(order["retailer_id"])


def customer_of(order):
    return db.customers.get(order["customer_id"])


def lines_of(order_id):
    rows = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    rows.sort(key=sort_key)
    return rows


def membership_of_order(order_id):
    for row in all_rows(db.batch_orders):
        if row["order_id"] == order_id:
            return row
    return None


def memberships_of_batch(batch_id):
    rows = [r for r in db.batch_orders.values() if r["batch_id"] == batch_id]
    rows.sort(key=lambda r: r["sequence_no"])
    return rows


def member_orders(batch_id):
    out = []
    for row in memberships_of_batch(batch_id):
        order = db.orders.get(row["order_id"])
        if order is not None:
            out.append(order)
    return out


def batch_of_order(order_id):
    row = membership_of_order(order_id)
    if row is None:
        return None
    return db.batches.get(row["batch_id"])


def payout_of_batch(batch_id):
    """The provisional/final payout row of a batch (forfeited rows excluded)."""
    for row in all_rows(db.payouts):
        if row["batch_id"] == batch_id and row["status"] in ("PROVISIONAL", "FINAL"):
            return row
    return None


def ratings_of(shopper_id):
    rows = [r for r in db.shopper_ratings.values() if r["shopper_id"] == shopper_id]
    rows.sort(key=sort_key)
    return rows


# --- line and order money ---------------------------------------------------
def line_estimate_cents(line):
    """Estimated money for one line, from its snapshots (ESTIMATE variant)."""
    item = item_of(line)
    unit = item["pricing_unit"] if item else "EACH"
    return calc.est_line_cents(
        line["unit_price_cents_snapshot"], unit, line["requested_qty"], line["requested_weight_lb"]
    )


def line_final_cents(line):
    """PRD 3.6 line-pricing rule."""
    if line["status"] in ("REFUNDED", "REQUESTED", "REPLACEMENT_PENDING"):
        return 0
    item = item_of(line)
    unit = item["pricing_unit"] if item else "EACH"
    if unit == "PER_LB":
        weight = calc.dec(line["final_weight_lb"])
        if weight <= 0:
            weight = calc.dec(line["requested_weight_lb"])
        return calc.cents(calc.dec(line["unit_price_cents_snapshot"]) * weight)
    qty = line["picked_qty"] if line["status"] in PRICED_LINE_STATUSES else line["requested_qty"]
    return int(line["unit_price_cents_snapshot"]) * int(qty)


def line_in_store_cents(line):
    """Same shape as line_final_cents but from the shelf-price snapshot."""
    item = item_of(line)
    unit = item["pricing_unit"] if item else "EACH"
    if unit == "PER_LB":
        weight = calc.dec(line["final_weight_lb"])
        if weight <= 0:
            weight = calc.dec(line["requested_weight_lb"])
        return calc.cents(calc.dec(line["in_store_price_cents_snapshot"]) * weight)
    qty = line["picked_qty"] if line["status"] in PRICED_LINE_STATUSES else line["requested_qty"]
    return int(line["in_store_price_cents_snapshot"]) * int(qty)


def recompute_estimated_subtotal(order):
    total = 0
    for line in lines_of(order["id"]):
        if line["status"] == "REFUNDED":
            continue
        total += line_estimate_cents(line)
    order["estimated_subtotal_cents"] = total
    return total


def run_estimate_authorization(order):
    """ESTIMATE variant of the authorization arithmetic (PRD 3.2)."""
    subtotal = recompute_estimated_subtotal(order)
    ceiling = (
        calc.cents(calc.dec(subtotal) * calc.AUTH_BUFFER_MULT)
        + calc.SERVICE_FEE_CENTS
        + int(order["tip_amount_cents"])
    )
    retailer = retailer_of(order)
    eligible = 0
    if order["ebt_requested"] and retailer is not None and retailer["ebt_snap_enabled"]:
        for line in lines_of(order["id"]):
            if line["status"] == "REFUNDED":
                continue
            if line["ebt_eligible_snapshot"]:
                eligible += line_estimate_cents(line)
    customer = customer_of(order)
    balance = int(customer["ebt_snap_balance_cents"]) if customer else 0
    authorized_ebt = min(balance, eligible)
    order["authorization_ceiling_cents"] = ceiling
    order["authorized_ebt_cents"] = authorized_ebt
    order["authorized_card_cents"] = ceiling - authorized_ebt


def recompute_captured_subtotal(order):
    total = 0
    for line in lines_of(order["id"]):
        total += line["final_price_cents"]
    order["captured_subtotal_cents"] = total
    return total


# --- customer aggregates ----------------------------------------------------
def recompute_customer_balances(customer):
    captured = 0
    for order in db.orders.values():
        if order["customer_id"] != customer["id"]:
            continue
        if order["payment_status"] in ("CAPTURED", "REFUNDED"):
            captured += int(order["ebt_captured_cents"])
    credit = 0
    for entry in db.credits.values():
        if entry["customer_id"] == customer["id"]:
            credit += int(entry["amount_cents"])
    customer["ebt_captured_total_cents"] = captured
    customer["credit_balance_cents"] = credit
    touch(customer)


def create_credit(customer, order_id, amount_cents, reason_code):
    entry = base_row(with_version=False)
    entry.update(
        {
            "customer_id": customer["id"],
            "order_id": order_id,
            "amount_cents": int(amount_cents),
            "reason_code": reason_code,
        }
    )
    db.credits[entry["id"]] = entry
    recompute_customer_balances(customer)
    return entry


# --- batch composition ------------------------------------------------------
def batch_line_weight(line):
    """Weight this line contributes to its batch (PRD 3.4)."""
    item = item_of(line)
    unit = item["pricing_unit"] if item else "EACH"
    if unit == "PER_LB":
        weight = calc.dec(line["final_weight_lb"])
        if weight > 0:
            return weight
        return calc.dec(line["requested_weight_lb"])
    qty = line["picked_qty"] if line["status"] in PRICED_LINE_STATUSES else line["requested_qty"]
    unit_weight = calc.dec(item["unit_weight_lb"]) if item else Decimal("0")
    return unit_weight * calc.dec(qty)


def membership_units(order):
    """Units frozen onto a membership row at attachment time."""
    total = 0
    for line in lines_of(order["id"]):
        item = item_of(line)
        unit = item["pricing_unit"] if item else "EACH"
        if unit == "PER_LB":
            total += 1
        else:
            total += int(line["requested_qty"])
    return total


def recompute_batch_aggregates(batch):
    rows = memberships_of_batch(batch["id"])
    orders = member_orders(batch["id"])
    batch["total_units"] = sum(int(r["units"]) for r in rows)
    distance = Decimal("0")
    weight = Decimal("0")
    retailers = []
    deadline = None
    blocked = 0
    for order in orders:
        distance += calc.dec(order["delivery_distance_mi"])
        if order["retailer_id"] not in retailers:
            retailers.append(order["retailer_id"])
        if deadline is None or order["delivery_deadline"] < deadline:
            deadline = order["delivery_deadline"]
        if order["payment_status"] == "REAUTH_HELD":
            blocked += 1
        for line in lines_of(order["id"]):
            if line["status"] == "REFUNDED":
                continue
            weight += batch_line_weight(line)
    batch["total_distance_mi"] = calc.one_dp(distance)
    batch["total_weight_lb"] = calc.one_dp(weight)
    batch["store_count"] = len(retailers)
    batch["delivery_deadline"] = deadline
    batch["checkout_blocked_count"] = blocked
    touch(batch)


# --- shopper counters, scores and tiers -------------------------------------
def recompute_committed_units(shopper):
    total = 0
    for batch in db.batches.values():
        if batch["claimed_shopper_id"] == shopper["id"] and batch["status"] in HELD_BATCH_STATUSES:
            total += int(batch["total_units"])
    shopper["committed_units"] = total


def recompute_shopper_counters(shopper):
    recompute_committed_units(shopper)
    shopper["completed_batch_count"] = int(shopper["_injected_completed"]) + int(
        shopper["_delivered_events"]
    )
    shopper["abandonment_count"] = int(shopper["_injected_abandonments"]) + int(
        shopper["_abandon_events"]
    )


def score_shopper(shopper):
    """Both scoring variants (PRD 3.3)."""
    history = ratings_of(shopper["id"])
    recent = sorted(history, key=lambda r: (r["created_at"], r["sequence_no"]), reverse=True)[
        : calc.ROLLING_WINDOW_N
    ]
    shopper["rolling_recent_avg"] = calc.mean_stars([r["stars"] for r in recent])
    shopper["lifetime_rating_avg"] = calc.mean_stars([r["stars"] for r in history])
    abandonments = int(shopper["abandonment_count"])
    shopper["rolling_tier_score"] = calc.tier_score(
        shopper["rolling_recent_avg"], bool(recent), abandonments
    )
    shopper["lifetime_tier_score"] = calc.tier_score(
        shopper["lifetime_rating_avg"], bool(history), abandonments
    )
    completed = int(shopper["completed_batch_count"])
    if abandonments >= calc.ABANDONMENT_SUSPENSION_THRESHOLD:
        shopper["tier"] = "PROBATION"
    else:
        shopper["tier"] = calc.tier_of(shopper["rolling_tier_score"], completed)
    shopper["lifetime_tier"] = calc.tier_of(shopper["lifetime_tier_score"], completed)


def refresh_shopper(shopper, bump=True):
    recompute_shopper_counters(shopper)
    score_shopper(shopper)
    if bump:
        touch(shopper)


# --- interval arithmetic ----------------------------------------------------
def window_conflict(batch, shopper):
    """PRD 3.5 window-conflict test with the 15-minute turnaround buffer."""
    cand_start = batch["shop_window_start"]
    cand_end = batch["delivery_deadline"]
    if cand_start is None or cand_end is None:
        return False
    for other in db.batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["claimed_shopper_id"] != shopper["id"]:
            continue
        if other["status"] not in HELD_BATCH_STATUSES:
            continue
        held_start = other["shop_window_start"]
        held_deadline = other["delivery_deadline"]
        if held_start is None or held_deadline is None:
            continue
        held_end = held_deadline + minutes(calc.SHOPPER_TURNAROUND_BUFFER_MIN)
        if cand_start < held_end and held_start < cand_end:
            return True
    return False


def retailer_concurrency_count(retailer_id, target_batch):
    """PRD 3.4 closed-interval overlap count at one retailer."""
    count = 0
    for other in db.batches.values():
        if other["id"] == target_batch["id"]:
            continue
        if other["status"] not in CONCURRENCY_STATUSES:
            continue
        has_retailer = False
        for order in member_orders(other["id"]):
            if order["retailer_id"] == retailer_id:
                has_retailer = True
                break
        if not has_retailer:
            continue
        if (
            other["shop_window_start"] <= target_batch["shop_window_end"]
            and target_batch["shop_window_start"] <= other["shop_window_end"]
        ):
            count += 1
    return count


# --- dispatch selection -----------------------------------------------------
def eligible_shoppers(batch, declined_ids):
    floor_rank = calc.TIER_RANK[batch["tier_access_floor"]]
    candidates = []
    for shopper in db.shoppers.values():
        if shopper["status"] != "ACTIVE":
            continue
        if shopper["service_area_code"] != batch["service_area_code"]:
            continue
        if calc.TIER_RANK[shopper["tier"]] < floor_rank:
            continue
        if int(shopper["committed_units"]) + int(batch["total_units"]) > int(
            shopper["vehicle_capacity_units"]
        ):
            continue
        if shopper["id"] in declined_ids:
            continue
        if window_conflict(batch, shopper):
            continue
        candidates.append(shopper)
    candidates.sort(
        key=lambda s: (
            -calc.TIER_RANK[s["tier"]],
            -s["rolling_tier_score"],
            int(s["committed_units"]),
            s["created_at"],
            s["_seq"],
        )
    )
    return candidates


def select_shopper(batch, declined_ids):
    pool = eligible_shoppers(batch, declined_ids)
    if not pool:
        return None
    return pool[0]


# --- price parity -----------------------------------------------------------
def parity_totals(order):
    catalog = 0
    in_store = 0
    for line in lines_of(order["id"]):
        if line["status"] not in PRICED_LINE_STATUSES:
            continue
        catalog += int(line["final_price_cents"])
        in_store += line_in_store_cents(line)
    return catalog, in_store


def apply_parity_at_checkout(order, retailer):
    catalog, in_store = parity_totals(order)
    markup = catalog - in_store
    order["parity_markup_cents"] = markup
    order["parity_disclosed"] = bool(retailer["parity_disclosure_required"])
    credit = calc.parity_credit_cents(markup, in_store, retailer["parity_disclosure_required"])
    if credit > 0:
        customer = customer_of(order)
        if customer is not None:
            create_credit(customer, order["id"], credit, "PARITY_ADJUSTMENT")
    return credit


# --- payouts ----------------------------------------------------------------
def payout_money(batch, variant):
    work = calc.work_pay(
        batch["total_units"],
        batch["total_weight_lb"],
        batch["total_distance_mi"],
        batch["store_count"],
    )
    orders = member_orders(batch["id"])
    tip_pass = sum(int(o["tip_amount_cents"]) for o in orders)
    baseline = sum(int(o["tip_original_cents"]) for o in orders)
    assembled = calc.assemble_payout(
        work["batch_pay_cents"], tip_pass, baseline, batch["total_units"], variant
    )
    money = {
        "base_pay_cents": work["base_pay_cents"],
        "heavy_pay_cents": work["heavy_pay_cents"],
        "mileage_bonus_cents": work["mileage_bonus_cents"],
        "multi_store_bonus_cents": work["multi_store_bonus_cents"],
    }
    money.update(assembled)
    return money


ZERO_MONEY = {
    "base_pay_cents": 0,
    "heavy_pay_cents": 0,
    "mileage_bonus_cents": 0,
    "multi_store_bonus_cents": 0,
    "tip_pass_through_cents": 0,
    "tip_protection_cents": 0,
    "guarantee_top_up_cents": 0,
    "total_payout_cents": 0,
}


def create_payout(batch, shopper_id, status, variant):
    row = base_row(with_version=True)
    row.update({"batch_id": batch["id"], "shopper_id": shopper_id, "status": status})
    if variant == "FORFEITED":
        row.update(dict(ZERO_MONEY))
    else:
        row.update(payout_money(batch, variant))
    db.payouts[row["id"]] = row
    return row


def apply_payout(payout, batch, variant):
    payout.update(payout_money(batch, variant))
    touch(payout)
    return payout


# --- abandonment and system release -----------------------------------------
def abandonment_credit_for(order):
    lines = lines_of(order["id"])
    total = len(lines)
    picked = sum(1 for l in lines if l["status"] in PRICED_LINE_STATUSES)
    return calc.abandonment_credit_cents(order["estimated_subtotal_cents"], total, picked)


def _release_common(batch, shopper_id):
    batch["abandoned_at"] = now()
    batch["claimed_shopper_id"] = None
    if shopper_id not in batch["declined_shopper_ids"]:
        batch["declined_shopper_ids"].append(shopper_id)
    batch["status"] = "ABANDONED"
    touch(batch)
    create_payout(batch, shopper_id, "FORFEITED", "FORFEITED")


def system_release(batch, shopper):
    """Link 4 of the cascade: never touches abandonment_count (PRD 3.9)."""
    orders = member_orders(batch["id"])
    credits = [(o, abandonment_credit_for(o)) for o in orders]
    _release_common(batch, shopper["id"])
    for order, amount in credits:
        order["fulfillment_status"] = "REASSIGN_PENDING"
        touch(order)
        customer = customer_of(order)
        if customer is not None:
            create_credit(customer, order["id"], amount, "ABANDONMENT_INCONVENIENCE")
    recompute_committed_units(shopper)


def abandon_batch(batch, shopper):
    """Shopper-initiated abandonment plus the four cascade links (PRD 3.9)."""
    start_status = batch["status"]
    orders = member_orders(batch["id"])
    credits = [(o, abandonment_credit_for(o)) for o in orders]

    _release_common(batch, shopper["id"])

    for order, amount in credits:
        customer = customer_of(order)
        if start_status == "CHECKED_OUT":
            ebt = int(order["ebt_captured_cents"])
            card = int(order["card_captured_cents"])
            order["payment_status"] = "REFUNDED"
            order["refunded_cents"] = ebt + card
            if customer is not None:
                customer["ebt_snap_balance_cents"] = int(customer["ebt_snap_balance_cents"]) + ebt
            order["ebt_captured_cents"] = 0
            if customer is not None:
                recompute_customer_balances(customer)
            if customer is not None and card > 0:
                create_credit(customer, order["id"], card, "POST_CHECKOUT_REVERSAL")
        order["fulfillment_status"] = "REASSIGN_PENDING"
        touch(order)
        if customer is not None:
            create_credit(customer, order["id"], amount, "ABANDONMENT_INCONVENIENCE")

    if start_status == "SHOPPING":
        for order in orders:
            for line in lines_of(order["id"]):
                if line["status"] == "PICKED":
                    line["status"] = "REQUESTED"
                    line["picked_qty"] = 0
                    line["final_weight_lb"] = Decimal("0")
                    line["final_price_cents"] = 0
                    touch(line)
        for req in all_rows(db.replacements):
            if req["status"] != "PENDING":
                continue
            line = db.order_lines.get(req["order_line_id"])
            if line is None or order_of(line) is None:
                continue
            if batch_of_order(line["order_id"]) is None:
                continue
            if batch_of_order(line["order_id"])["id"] != batch["id"]:
                continue
            req["status"] = "EXPIRED"
            req["resolution_effect"] = "NONE"
            touch(req)
            if line["status"] == "REPLACEMENT_PENDING":
                line["status"] = "REQUESTED"
                touch(line)
    elif start_status == "CHECKED_OUT":
        for order in orders:
            for line in lines_of(order["id"]):
                line["status"] = "REQUESTED"
                line["final_price_cents"] = 0
                touch(line)

    # Link 1: capacity falls, abandonment count rises.
    shopper["_abandon_events"] = int(shopper["_abandon_events"]) + 1
    recompute_shopper_counters(shopper)
    # Link 2: both scoring variants and both tiers are re-derived.
    score_shopper(shopper)
    # Link 3: the abandonment override suspends the shopper.
    suspended = False
    if int(shopper["abandonment_count"]) >= calc.ABANDONMENT_SUSPENSION_THRESHOLD:
        if shopper["status"] == "ACTIVE":
            shopper["status"] = "SUSPENDED_REVIEW"
            suspended = True
    touch(shopper)
    # Link 4: every other batch the shopper still holds is released by the system.
    if suspended:
        siblings = [
            b
            for b in all_rows(db.batches)
            if b["id"] != batch["id"]
            and b["claimed_shopper_id"] == shopper["id"]
            and b["status"] in HELD_BATCH_STATUSES
        ]
        for sibling in siblings:
            system_release(sibling, shopper)
        recompute_shopper_counters(shopper)
        score_shopper(shopper)
