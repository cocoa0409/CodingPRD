"""Domain calculations and multi-entity cascades.

Every monetary figure here is an integer number of minor units and every
percentage is in basis points.  The rounding mode of each step is the one the
PRD pins for that step: floor for derivations, ceiling for protective floors and
round-half-up for per-line labour and the channel fee.
"""

import constants as C
import store
from errors import ApiError


# --------------------------------------------------------------------------
# integer rounding primitives
# --------------------------------------------------------------------------
def bp_floor(amount, bp):
    return (amount * bp) // 10000


def bp_ceil(amount, bp):
    product = amount * bp
    return -((-product) // 10000)


def bp_half_up(amount, bp):
    product = amount * bp
    return (2 * product + 10000) // 20000


def ratio_bp_floor(numerator, denominator):
    return (numerator * 10000) // denominator


# --------------------------------------------------------------------------
# policy resolution
# --------------------------------------------------------------------------
def grade_policy_or_error(product_category, condition_grade):
    policy = store.active_grade_policy(product_category, condition_grade)
    if policy is None:
        raise ApiError("ERR_GRADE_POLICY_MISSING")
    return policy


def credit_policy_or_error():
    policy = store.active_credit_policy()
    if policy is None:
        raise ApiError("ERR_CREDIT_POLICY_MISSING")
    return policy


# --------------------------------------------------------------------------
# trade_in_appraised_credit
# --------------------------------------------------------------------------
def appraise(trade_in, grade_policy, credit_policy, loyalty_tier=None):
    base = bp_floor(trade_in["msrp_minor"], grade_policy["base_credit_pct_bp"])
    channel_bonus = 0
    if trade_in["channel"] == "MAIL_IN":
        channel_bonus = bp_floor(base, credit_policy["mail_in_bonus_pct_bp"])
    tier_bonus = 0
    if loyalty_tier == "PLUS":
        tier_bonus = bp_floor(base, C.PLUS_TIER_BONUS_BP)
    raw = base + channel_bonus + tier_bonus
    return min(raw, C.MAX_CREDIT_PER_TRADE_IN_MINOR)


def quote_provisional(trade_in):
    grade_policy = grade_policy_or_error(trade_in["product_category"], trade_in["declared_grade"])
    credit_policy = credit_policy_or_error()
    return appraise(trade_in, grade_policy, credit_policy, loyalty_tier=None)


def issuance_final(trade_in, customer, grade_policy, credit_policy):
    return appraise(trade_in, grade_policy, credit_policy, loyalty_tier=customer["loyalty_tier"])


# --------------------------------------------------------------------------
# refurbishment costing and viability
# --------------------------------------------------------------------------
def task_line_cost(bay, labor_minutes, parts_cost_minor):
    multiplier_bp = C.BAY_TYPE_MULTIPLIER_BP[bay["bay_type"]]
    labour_raw = labor_minutes * C.LABOR_RATE_MINOR_PER_MINUTE
    labour = bp_half_up(labour_raw, multiplier_bp)
    return labour + parts_cost_minor


def order_task_lines(order_id):
    lines = [t for t in store.rows("refurb_tasks") if t["refurb_order_id"] == order_id]
    return sorted(lines, key=lambda t: t["sequence_no"])


def baseline_resale_value(unit, grade_policy):
    return bp_floor(unit["reference_msrp_minor"], grade_policy["resale_price_pct_bp"])


def viability_ratio(logged_cost_minor, unit):
    policy = store.active_grade_policy(unit["product_category"], unit["condition_grade"])
    baseline = 0 if policy is None else baseline_resale_value(unit, policy)
    if baseline == 0:
        return 10001
    return ratio_bp_floor(logged_cost_minor, baseline)


def rematerialize_order(order):
    """Recompute logged_cost_minor and viability_ratio_bp; the caller bumps."""
    lines = order_task_lines(order["id"])
    order["logged_cost_minor"] = sum(line["cost_minor"] for line in lines)
    unit = store.get("resale_units", order["resale_unit_id"])
    if unit is None:
        order["viability_ratio_bp"] = 0
    else:
        order["viability_ratio_bp"] = viability_ratio(order["logged_cost_minor"], unit)
    return order


def capitalized_cost(unit, order):
    if unit["ownership_treatment"] != "OWNED_INVENTORY":
        return 0
    acquisition = 0
    for grant in store.rows("credit_grants"):
        if grant["trade_in_id"] == unit["trade_in_id"]:
            acquisition = grant["issued_amount_minor"]
            break
    return acquisition + order["logged_cost_minor"]


# --------------------------------------------------------------------------
# listing price
# --------------------------------------------------------------------------
def list_price(unit, channel, grade_policy):
    base_resale = baseline_resale_value(unit, grade_policy)
    margin_floor = bp_ceil(unit["capitalized_cost_minor"], C.MIN_MARGIN_BP)
    channel_cap = bp_floor(unit["reference_msrp_minor"], channel["max_resale_price_ratio_bp"])
    if margin_floor > channel_cap:
        raise ApiError("ERR_MARGIN_FLOOR_ABOVE_CHANNEL_CEILING")
    return min(channel_cap, max(base_resale, margin_floor))


# --------------------------------------------------------------------------
# resale order settlement arithmetic
# --------------------------------------------------------------------------
def channel_fee_bp(gross_price_minor):
    for up_to_minor, fee_bp in C.CHANNEL_FEE_TIERS:
        if up_to_minor is None or gross_price_minor <= up_to_minor:
            return fee_bp
    return C.CHANNEL_FEE_TIERS[-1][1]


def channel_fee(gross_price_minor):
    return bp_half_up(gross_price_minor, channel_fee_bp(gross_price_minor))


def redemption_cap(order_total_minor, credit_policy):
    return bp_floor(order_total_minor, credit_policy["max_redemption_pct_bp"])


def restock_fee(order, grade_policy):
    if order["reason_type"] != "BUYER_REMORSE":
        return 0
    return bp_ceil(order["gross_price_minor"], grade_policy["restock_fee_pct_bp"])


def refund_figures(order, grade_policy):
    fee = restock_fee(order, grade_policy)
    if order["reason_type"] == "BUYER_REMORSE":
        non_refundable = order["channel_fee_minor"] + fee
    else:
        non_refundable = 0
    refund_cash = max(0, order["cash_due_minor"] - non_refundable)
    shortfall = max(0, non_refundable - order["cash_due_minor"])
    refund_credit = max(0, order["credit_applied_minor"] - shortfall)
    return fee, refund_cash, refund_credit


# --------------------------------------------------------------------------
# customer derived quantities (PRD 3.1) — recomputed from scratch, never
# incremented, and the row is touched exactly once per cascade
# --------------------------------------------------------------------------
def customer_balance(customer_id):
    total = 0
    for grant in store.rows("credit_grants"):
        if grant["customer_id"] == customer_id and grant["status"] in C.LIVE_GRANT_STATUSES:
            total += grant["remaining_minor"]
    return total


def customer_diverted_grams(customer_id):
    accepted = set(
        t["id"]
        for t in store.rows("trade_ins")
        if t["customer_id"] == customer_id and t["status"] == "ACCEPTED"
    )
    total = 0
    for unit in store.rows("resale_units"):
        if unit["trade_in_id"] in accepted and unit["lifecycle_state"] != "SALVAGED":
            total += unit["mass_grams"]
    return total


def recompute_customer(customer, balance=False, diverted=False):
    if customer is None:
        return None
    if balance:
        customer["credit_balance_minor"] = customer_balance(customer["id"])
    if diverted:
        customer["diverted_grams_total"] = customer_diverted_grams(customer["id"])
    store.touch(customer)
    return customer


# --------------------------------------------------------------------------
# the append-only ledger (PRD 2.9)
# --------------------------------------------------------------------------
def append_entry(grant, entry_type, amount_minor, balance_after_minor, resale_order_id=None):
    return store.create(
        "ledger_entries",
        {
            "credit_grant_id": grant["id"],
            "resale_order_id": resale_order_id,
            "entry_type": entry_type,
            "amount_minor": amount_minor,
            "balance_after_minor": balance_after_minor,
            "occurred_at": store.now(),
        },
        versioned=False,
    )


def grant_entries(grant_id):
    return [e for e in store.rows("ledger_entries") if e["credit_grant_id"] == grant_id]


def order_entries(order_id):
    return [e for e in store.rows("ledger_entries") if e.get("resale_order_id") == order_id]


# --------------------------------------------------------------------------
# redemption (PRD 3.7)
# --------------------------------------------------------------------------
def live_unexpired_grants(customer_id):
    now = store.now()
    return [
        g
        for g in store.rows("credit_grants")
        if g["customer_id"] == customer_id
        and g["status"] in C.LIVE_GRANT_STATUSES
        and g["expires_at"] > now
    ]


def grant_admits_channel(grant, channel):
    policy = store.get("credit_policies", grant.get("credit_policy_id"))
    if policy is None:
        return False
    admitted = C.ASSORTMENT_ADMITS.get(policy["eligible_assortment"], ())
    return channel["channel_type"] in admitted


def eligible_grants(customer_id, channel):
    found = [g for g in live_unexpired_grants(customer_id) if grant_admits_channel(g, channel)]
    return sorted(found, key=lambda g: (g["expires_at"], g["created_at"], g["_seq"]))


def redeem_waterfall(grants, amount_minor, order_id):
    """Drain each grant to zero before touching the next one."""
    outstanding = amount_minor
    for grant in grants:
        if outstanding <= 0:
            break
        drawn = min(grant["remaining_minor"], outstanding)
        if drawn <= 0:
            continue
        grant["remaining_minor"] -= drawn
        outstanding -= drawn
        grant["status"] = "EXHAUSTED" if grant["remaining_minor"] == 0 else "PARTIALLY_REDEEMED"
        append_entry(
            grant,
            "REDEEM",
            -drawn,
            grant["remaining_minor"],
            resale_order_id=order_id,
        )
        store.touch(grant)
    return amount_minor - outstanding


def release_waterfall(order, amount_minor):
    """Return brand currency along this order's own REDEEM entries, reversed."""
    redeems = [e for e in order_entries(order["id"]) if e["entry_type"] == "REDEEM"]
    redeems.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]), reverse=True)
    outstanding = amount_minor
    now = store.now()
    for entry in redeems:
        if outstanding <= 0:
            break
        grant = store.get("credit_grants", entry["credit_grant_id"])
        if grant is None:
            continue
        restorable = min(-entry["amount_minor"], outstanding)
        headroom = grant["issued_amount_minor"] - grant["remaining_minor"]
        restorable = min(restorable, headroom)
        if restorable <= 0:
            continue
        grant["remaining_minor"] += restorable
        outstanding -= restorable
        if grant["remaining_minor"] >= grant["issued_amount_minor"]:
            grant["status"] = "ISSUED"
        else:
            grant["status"] = "PARTIALLY_REDEEMED"
        append_entry(
            grant,
            "RELEASE",
            restorable,
            grant["remaining_minor"],
            resale_order_id=order["id"],
        )
        store.touch(grant)
        # Third link: currency that had already lapsed is re-expired at once.
        if grant["expires_at"] <= now:
            append_entry(grant, "EXPIRE", -grant["remaining_minor"], 0)
            grant["remaining_minor"] = 0
            grant["status"] = "EXPIRED"
            store.touch(grant)
    return amount_minor - outstanding


# --------------------------------------------------------------------------
# expiry sweep (PRD 3.9)
# --------------------------------------------------------------------------
def expiry_sweep():
    now = store.now()
    swept = [
        g
        for g in store.rows("credit_grants")
        if g["status"] in C.LIVE_GRANT_STATUSES and g["expires_at"] <= now
    ]
    swept.sort(key=lambda g: (g["expires_at"], g["created_at"], g["_seq"]))
    expired_amount = 0
    customer_ids = []
    for grant in swept:
        amount = grant["remaining_minor"]
        expired_amount += amount
        append_entry(grant, "EXPIRE", -amount, 0)
        grant["remaining_minor"] = 0
        grant["status"] = "EXPIRED"
        store.touch(grant)
        if grant["customer_id"] not in customer_ids:
            customer_ids.append(grant["customer_id"])
    for customer_id in customer_ids:
        recompute_customer(store.get("customers", customer_id), balance=True)
    return {
        "expired_grant_count": len(swept),
        "expired_amount_minor": expired_amount,
        "affected_customer_count": len(customer_ids),
    }


# --------------------------------------------------------------------------
# markdown cadence (PRD 3.6)
# --------------------------------------------------------------------------
def unit_aged_days(unit):
    listed_at = unit.get("listed_at")
    if listed_at is None:
        return 0
    elapsed = int((store.now() - listed_at).total_seconds())
    if elapsed <= 0:
        return 0
    return elapsed // 86400


def eligible_markdown_units(campaign):
    found = []
    for unit in store.rows("resale_units"):
        if unit["lifecycle_state"] != "LISTED":
            continue
        if unit.get("listed_channel_id") != campaign["channel_id"]:
            continue
        if unit["product_category"] != campaign["product_category"]:
            continue
        threshold = campaign["cadence_days"] * (unit["markdown_step_count"] + 1)
        if unit_aged_days(unit) < threshold:
            continue
        found.append(unit)
    return sorted(found, key=lambda u: (u["listed_at"], u["created_at"], u["_seq"]))


def run_markdown_step(campaign):
    counters = {
        "evaluated_unit_count": 0,
        "marked_down_unit_count": 0,
        "skipped_at_floor_count": 0,
        "written_down_unit_count": 0,
        "total_markdown_minor": 0,
    }
    for unit in eligible_markdown_units(campaign):
        counters["evaluated_unit_count"] += 1
        floor_price = bp_ceil(unit["list_price_minor"], campaign["floor_pct_bp"])
        stepped = bp_floor(unit["current_price_minor"], 10000 - campaign["step_bp"])
        new_price = max(stepped, floor_price)
        if new_price == unit["current_price_minor"]:
            counters["skipped_at_floor_count"] += 1
            continue
        counters["total_markdown_minor"] += unit["current_price_minor"] - new_price
        unit["current_price_minor"] = new_price
        unit["markdown_step_count"] += 1
        if new_price == floor_price and unit["accounting_state"] == "CAPITALIZED":
            unit["accounting_state"] = "WRITTEN_DOWN"
            counters["written_down_unit_count"] += 1
        store.touch(unit)
        counters["marked_down_unit_count"] += 1
    return counters


# --------------------------------------------------------------------------
# warranty replacement selection (PRD 3.8)
# --------------------------------------------------------------------------
def select_replacement_unit(order, defective_unit):
    candidates = []
    for unit in store.rows("resale_units"):
        if unit["id"] == defective_unit["id"]:
            continue
        if unit["lifecycle_state"] != "LISTED":
            continue
        if unit.get("listed_channel_id") != order["channel_id"]:
            continue
        if unit["product_category"] != defective_unit["product_category"]:
            continue
        if unit["condition_grade"] != defective_unit["condition_grade"]:
            continue
        candidates.append(unit)
    if not candidates:
        raise ApiError("ERR_NO_REPLACEMENT_UNIT")
    candidates.sort(
        key=lambda u: (
            u["current_price_minor"],
            u["listed_at"] or u["created_at"],
            u["created_at"],
            u["_seq"],
        )
    )
    return candidates[0]


# --------------------------------------------------------------------------
# diversion metrics (PRD 3.9)
# --------------------------------------------------------------------------
def diversion_metrics(period_start_at, period_end_at):
    accepted_ids = set()
    for trade_in in store.rows("trade_ins"):
        if trade_in["status"] != "ACCEPTED":
            continue
        accepted_at = trade_in.get("accepted_at")
        if accepted_at is None:
            continue
        if period_start_at <= accepted_at < period_end_at:
            accepted_ids.add(trade_in["id"])
    units_diverted_count = 0
    diverted_grams = 0
    salvage_grams = 0
    for unit in store.rows("resale_units"):
        if unit["trade_in_id"] not in accepted_ids:
            continue
        if unit["lifecycle_state"] == "SALVAGED":
            salvage_grams += unit["mass_grams"]
        else:
            units_diverted_count += 1
            diverted_grams += unit["mass_grams"]
    total_grams = diverted_grams + salvage_grams
    if total_grams == 0:
        rate_bp = 0
    else:
        rate_bp = ratio_bp_floor(diverted_grams, total_grams)
    credit_liability = 0
    for grant in store.rows("credit_grants"):
        if grant["status"] not in C.LIVE_GRANT_STATUSES:
            continue
        if period_start_at <= grant["issued_at"] < period_end_at:
            credit_liability += grant["remaining_minor"]
    return {
        "units_diverted_count": units_diverted_count,
        "diverted_grams": diverted_grams,
        "salvage_grams": salvage_grams,
        "landfill_diversion_rate_bp": rate_bp,
        "credit_liability_minor": credit_liability,
    }


# --------------------------------------------------------------------------
# window helpers
# --------------------------------------------------------------------------
def whole_days_apart(start_at, end_at):
    seconds = (end_at - start_at).total_seconds()
    return float(seconds).is_integer() and int(seconds) % 86400 == 0


def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def closed_window_conflict(a_start, a_end, b_start, b_end):
    """Closed intervals conflict when they overlap or sit less than the
    sanitation buffer apart (PRD 3.5)."""
    gap_after = (b_start - a_end).total_seconds()
    gap_before = (a_start - b_end).total_seconds()
    return gap_after < C.SANITATION_BUFFER_SECONDS and gap_before < C.SANITATION_BUFFER_SECONDS
