"""Business logic: state machines, cascade chains and the pinned calculations."""

from decimal import Decimal, ROUND_HALF_UP

import db
import timeutil
from errors import fail

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------

TIER_BONUS_HIGH = Decimal("0.02")
TIER_BONUS_MID = Decimal("0.01")
TIER_BONUS_LOW = Decimal("0.00")
TIER_BONUS_HIGH_THRESHOLD_CENTS = Decimal(20000000)
TIER_BONUS_MID_THRESHOLD_CENTS = Decimal(10000000)
SPLIT_PCT_CAP = Decimal("0.75")

RISK_BAND_A_MIN_CENTS = Decimal(15000000)
RISK_BAND_B_MIN_CENTS = Decimal(5000000)

DRAW_CEILING_CENTS = Decimal(5000000)

WASTE_TIER_HIGH_THRESHOLD_CENTS = Decimal(500000)
WASTE_TIER_MEDIUM_THRESHOLD_CENTS = Decimal(100000)
WASTE_TIER_HIGH_ADDER = Decimal("0.05")
WASTE_TIER_MEDIUM_ADDER = Decimal("0.02")
WASTE_TIER_LOW_ADDER = Decimal("0.00")
WASTE_SHARE_PCT_CAP = Decimal("0.60")

ELIGIBILITY_OPEN_MIN = 60
PROVISIONAL_HIGH = 75
PROVISIONAL_MID = 55
RENEWAL_NET_WORTH_HIGH_CENTS = Decimal(15000000)
RENEWAL_NET_WORTH_MID_CENTS = Decimal(10000000)
RENEWAL_NET_WORTH_BASE_CENTS = Decimal(7500000)

MONTHLY_RENT_BANDS = {
    "URBAN": Decimal(500000),
    "SUBURBAN": Decimal(350000),
    "RURAL": Decimal(200000),
}

AGREEMENT_AMENDABLE = (
    "split_pct", "waste_share_pct", "shrink_responsibility_pct",
    "rebate_pass_pct", "minimum_net_worth_cents",
)


def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    """Round to exactly 2 decimal places, half up."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Cross-aggregate lookups
# ---------------------------------------------------------------------------

def covering_agreement(store_id, statuses=("ACTIVE", "RENEWAL_PENDING")):
    """The store's designated agreement.

    Prefers an agreement written for the store's *current* operator, so an
    incumbent agreement terminated by a transfer cannot keep moving money on a
    store that has since moved to a different franchisee.
    """
    store = db.get("stores", store_id)
    candidates = [a for a in db.all_of("agreements")
                  if a["store_id"] == store_id and a["status"] in statuses]
    if not candidates or store is None:
        return candidates[0] if candidates else None
    owned = [a for a in candidates if a["franchisee_id"] == store["franchisee_id"]]
    pool = owned or candidates
    return min(pool, key=lambda a: a["created_at"])


def agreement_for_store(store_id, statuses=None):
    agreements = [a for a in db.all_of("agreements") if a["store_id"] == store_id]
    if statuses is not None:
        agreements = [a for a in agreements if a["status"] in statuses]
    return agreements


def recalculate_franchisee(franchisee):
    """`franchisee_net_worth` — recomputed and re-derived in a pinned order."""
    if franchisee is None:
        return None
    draw_outstanding = sum(
        (d["amount_cents"] - d["recovered_cents"])
        for d in db.all_of("draws")
        if d["franchisee_id"] == franchisee["id"]
        and d["status"] in ("ISSUED", "PARTIALLY_RECOVERED")
    )
    open_shrink = sum(
        audit["shrink_charge_cents"]
        for audit in db.all_of("shrink_audits")
        if audit["status"] == "FINALIZED"
        and audit["shrink_charge_cents"] > 0
        and not audit["recovered_in_settlement"]
        and _store_owner(audit["store_id"]) == franchisee["id"]
    )
    franchisee["draw_outstanding_cents"] = int(draw_outstanding)
    franchisee["open_shrink_charge_cents"] = int(open_shrink)
    adjusted = dec(franchisee["stated_net_worth_cents"]) - dec(draw_outstanding) - dec(open_shrink)
    franchisee["audit_adjusted_net_worth_cents"] = int(adjusted)
    if adjusted >= RISK_BAND_A_MIN_CENTS:
        franchisee["risk_band"] = "A"
    elif adjusted >= RISK_BAND_B_MIN_CENTS:
        franchisee["risk_band"] = "B"
    else:
        franchisee["risk_band"] = "C"
    db.touch(franchisee)
    return franchisee


def _store_owner(store_id):
    store = db.get("stores", store_id)
    return store["franchisee_id"] if store else None


# ---------------------------------------------------------------------------
# Lease recognition
# ---------------------------------------------------------------------------

def monthly_rent_for_format(store_format):
    return MONTHLY_RENT_BANDS.get(store_format, MONTHLY_RENT_BANDS["RURAL"])


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def tier_bonus(gross_profit):
    if gross_profit >= TIER_BONUS_HIGH_THRESHOLD_CENTS:
        return TIER_BONUS_HIGH
    if gross_profit >= TIER_BONUS_MID_THRESHOLD_CENTS:
        return TIER_BONUS_MID
    return TIER_BONUS_LOW


def performance_tier_for(gross_profit):
    if gross_profit >= TIER_BONUS_HIGH_THRESHOLD_CENTS:
        return "PREMIER"
    if gross_profit >= TIER_BONUS_MID_THRESHOLD_CENTS:
        return "PREFERRED"
    return "STANDARD"


def rebate_flowthrough(rebate_cents, pass_pct, category_weights):
    """`rebate_flowthrough` — nested rounding in the pinned per-category order.

    category_weights is a list of (category, gross_sales) pairs. Each category's
    attribution is ``rebate_cents * (gross_sales_cat / total_gross_sales)``,
    rounded per category; each rounded attribution is then multiplied by
    ``rebate_pass_pct`` and rounded per category again; ``flowthrough_cents`` is
    the sum of those per-category figures. The forbidden alternative —
    ``round(rebate_cents * pass_pct, 2)`` applied to the whole rebate once — is
    deliberately not used.
    """
    rebate = dec(rebate_cents)
    pct = dec(pass_pct)
    total_sales = sum(dec(weight) for _, weight in category_weights)
    if not category_weights or total_sales <= 0:
        return q2(rebate * pct)

    flows = []
    for _category, gross_sales in category_weights:
        weight = dec(gross_sales) / total_sales
        attribution = q2(rebate * weight)
        flows.append(q2(attribution * pct))
    return sum(flows)


def in_scope_fresh_orders(store_id, period_start, period_end):
    """Orders whose bound window overlaps the settlement period and are RECONCILED."""
    out = []
    for order in db.all_of("fresh_orders"):
        if order["store_id"] != store_id or order["status"] != "RECONCILED":
            continue
        window = db.get("delivery_windows", order["delivery_window_id"])
        if window is None:
            continue
        if timeutil.overlaps(window["window_start"], window["window_end"],
                             period_start, period_end):
            out.append(order)
    return out


def waste_share_allocation(store_id, period_start, period_end, waste_share_pct):
    """`waste_share_allocation` — tier keyed off the whole-period total first.

    Steps: (1) accumulate the whole-period waste cost from the rounded per-order
    bases; (2) key the tier off that whole-period total, never off a running
    figure; (3) derive the capped effective share; (4) multiply each order's own
    rounded base by the effective share; (5) the settlement's charge is the sum
    of those per-order shares. The final order absorbs the residual so the parts
    add up exactly to ``round(period_waste_cost * effective_share, 2)`` and a
    single order's share matches the scaffold's one-order arithmetic exactly.
    """
    orders = in_scope_fresh_orders(store_id, period_start, period_end)
    bases = [(order, q2(dec(order["unit_cost_cents"]) * dec(order["waste_units"])))
             for order in orders]
    period_waste_cost = sum(base for _, base in bases)

    if period_waste_cost >= WASTE_TIER_HIGH_THRESHOLD_CENTS:
        adder = WASTE_TIER_HIGH_ADDER
    elif period_waste_cost >= WASTE_TIER_MEDIUM_THRESHOLD_CENTS:
        adder = WASTE_TIER_MEDIUM_ADDER
    else:
        adder = WASTE_TIER_LOW_ADDER
    effective_share = min(WASTE_SHARE_PCT_CAP, dec(waste_share_pct) + adder)

    total = Decimal(0)
    allocated = Decimal(0)
    for index, (order, base) in enumerate(bases):
        if index == len(bases) - 1:
            share = q2(period_waste_cost * effective_share) - allocated
        else:
            share = q2(base * effective_share)
            allocated += share
        if order.get("waste_share_cents") != share:
            order["waste_share_cents"] = share
            order["line_waste_cents"] = share
            db.touch(order)
        total += share
    return total, orders


def recalculate_settlement_money(settlement):
    """Steps 1-8 of `gross_profit_split`, in the pinned evaluation order."""
    lines = db.find("revenue_lines", settlement_id=settlement["id"])
    gross_sales = sum(dec(line["gross_sales_cents"]) for line in lines)
    cost_of_goods = sum(dec(line["cost_of_goods_cents"]) for line in lines)

    credit = Decimal(0)
    for rebate in db.all_of("rebates"):
        if rebate["store_id"] != settlement["store_id"]:
            continue
        if rebate["status"] != "APPLIED" or rebate.get("covering_settlement_id") != settlement["id"]:
            continue
        credit += dec(rebate["flowthrough_cents"])

    gross_profit = (gross_sales - cost_of_goods) + credit
    provisional_gross_profit = dec(settlement["trailing_avg_gross_profit_cents"]) + credit

    agreement = covering_agreement(settlement["store_id"])
    split_pct = dec(agreement["split_pct"]) if agreement else Decimal(0)
    effective_pct = min(SPLIT_PCT_CAP, split_pct + tier_bonus(gross_profit))

    settlement["gross_sales_cents"] = int(gross_sales)
    settlement["cost_of_goods_cents"] = int(cost_of_goods)
    settlement["rebate_credit_cents"] = credit
    settlement["gross_profit_cents"] = gross_profit
    settlement["provisional_gross_profit_cents"] = provisional_gross_profit
    settlement["eligible_split_pct"] = effective_pct
    settlement["provisional_split_cents"] = q2(provisional_gross_profit * split_pct)
    settlement["franchisee_split_cents"] = q2(gross_profit * effective_pct)
    settlement["franchisor_share_cents"] = gross_profit - q2(gross_profit * effective_pct)

    if agreement is not None:
        tier = performance_tier_for(gross_profit)
        if agreement["performance_tier"] != tier:
            agreement["performance_tier"] = tier
            db.touch(agreement)

    recalculate_settlement_net(settlement)
    db.touch(settlement)
    return settlement


def recompute_settlement_waste(settlement):
    agreement = covering_agreement(settlement["store_id"])
    share_pct = dec(agreement["waste_share_pct"]) if agreement else Decimal(0)
    total, _ = waste_share_allocation(
        settlement["store_id"], settlement["period_start"], settlement["period_end"], share_pct)
    settlement["waste_charge_cents"] = total
    return total


def apply_waste_share(store_id, window):
    """Recompute in-scope per-order waste shares and any in-flight settlement.

    Waste belongs to a settlement by reference; an order reconciled while a
    settlement covering its window is in flight sits inside that settlement's
    week, and the settlement's charge is refreshed on the spot.
    """
    agreement = covering_agreement(store_id)
    share_pct = dec(agreement["waste_share_pct"]) if agreement else Decimal(0)

    covered = False
    for settlement in db.all_of("settlements"):
        if settlement["store_id"] != store_id:
            continue
        if not timeutil.overlaps(window["window_start"], window["window_end"],
                                 settlement["period_start"], settlement["period_end"]):
            continue
        covered = True
        total, _ = waste_share_allocation(
            store_id, settlement["period_start"], settlement["period_end"], share_pct)
        if settlement["status"] in ("DRAW_PAID", "RECONCILED", "DISPUTED"):
            settlement["waste_charge_cents"] = total
            recalculate_settlement_net(settlement)
            db.touch(settlement)
    if covered:
        return

    reconciled = [o for o in db.all_of("fresh_orders")
                  if o["store_id"] == store_id and o["status"] == "RECONCILED"]
    spans = []
    for order in reconciled:
        bound = db.get("delivery_windows", order["delivery_window_id"])
        if bound is not None:
            spans.append(bound)
    if not spans:
        return
    period_start = min(b["window_start"] for b in spans)
    period_end = max(b["window_end"] for b in spans)
    waste_share_allocation(store_id, period_start, period_end, share_pct)


def recalculate_settlement_net(settlement):
    """franchisee_split - shrink - waste - draw recovery, without a version bump.

    The settlement's net payout is the pool the recovery waterfall draws on; it
    is recomputed whenever the settlement's charges move and frozen once the
    week is reconciled.
    """
    if settlement["provisional"]:
        base = settlement["provisional_split_cents"]
    else:
        base = settlement["franchisee_split_cents"]

    net = (dec(base)
           - dec(settlement["shrink_charge_cents"])
           - dec(settlement["waste_charge_cents"])
           - dec(settlement["draw_recovery_cents"]))
    settlement["net_settlement_cents"] = net
    return net


def draw_recovery_allocation(franchisee_id, net_settlement_cents, settlement):
    """`draw_recovery_allocation` — waterfall in drawn_on ASC, created_at ASC."""
    remaining = max(Decimal(0), dec(net_settlement_cents))
    previous = dec(settlement["draw_recovery_cents"])
    take_back = min(previous, remaining)
    remaining -= take_back
    settlement["draw_recovery_cents"] = take_back
    total = take_back

    candidates = [d for d in db.all_of("draws")
                  if d["franchisee_id"] == franchisee_id
                  and d["status"] in ("ISSUED", "PARTIALLY_RECOVERED")]
    candidates.sort(key=lambda d: (d["drawn_on"], d["created_at"]))

    for draw in candidates:
        if remaining <= 0:
            break
        outstanding = dec(draw["amount_cents"]) - dec(draw["recovered_cents"])
        if outstanding <= 0:
            continue
        take = min(outstanding, remaining)
        draw["recovered_cents"] = dec(draw["recovered_cents"]) + take
        remaining -= take
        total += take
        draw["status"] = "RECOVERED" if dec(draw["recovered_cents"]) >= dec(draw["amount_cents"]) else "PARTIALLY_RECOVERED"
        db.touch(draw)

    settlement["draw_recovery_cents"] = total
    franchisee = db.get("franchisees", franchisee_id)
    if franchisee is not None:
        recalculate_franchisee(franchisee)
    recalculate_settlement_net(settlement)
    return total


def renewal_eligibility(agreement):
    """`renewal_eligibility` — the band is keyed off the provisional score."""
    store_id = agreement["store_id"]
    franchisee = db.get("franchisees", agreement["franchisee_id"])
    term_start, term_end = agreement["term_start"], agreement["term_end"]

    settlements = [s for s in db.all_of("settlements") if s["store_id"] == store_id]
    in_term = [s for s in settlements
               if timeutil.overlaps(s["period_start"], s["period_end"], term_start, term_end)]
    finalized = [s for s in in_term if s["status"] == "FINALIZED"]
    disputed_count = sum(1 for s in in_term if s["status"] == "DISPUTED")

    if len(finalized) >= 3:
        sales_activity_score = 40
    elif len(finalized) >= 1:
        sales_activity_score = 25
    else:
        sales_activity_score = 10

    settlement_score = max(0, 30 - 5 * disputed_count)

    audits = [a for a in db.all_of("shrink_audits")
              if a["store_id"] == store_id and a["status"] == "FINALIZED"
              and timeutil.overlaps(a["period_start"], a["period_end"], term_start, term_end)]
    audit_score = 10 if any(dec(a["shrink_cents"]) > 0 for a in audits) else 20

    provisional_score = sales_activity_score + settlement_score + audit_score

    if provisional_score >= PROVISIONAL_HIGH:
        band = RENEWAL_NET_WORTH_HIGH_CENTS
    elif provisional_score >= PROVISIONAL_MID:
        band = RENEWAL_NET_WORTH_MID_CENTS
    else:
        band = RENEWAL_NET_WORTH_BASE_CENTS

    adjusted = dec(franchisee["audit_adjusted_net_worth_cents"]) if franchisee else Decimal(0)
    minimum = dec(agreement["minimum_net_worth_cents"])
    if adjusted >= band:
        net_worth_score = 10
    elif adjusted >= minimum:
        net_worth_score = 5
    else:
        net_worth_score = 0

    final_score = max(0, min(100, provisional_score + net_worth_score))
    return {
        "score": final_score,
        "provisional_score": provisional_score,
        "required_band": band,
    }


def shrink_charge(audit, percentage):
    shrink_cents = dec(audit["book_inventory_cents"]) - dec(audit["physical_inventory_cents"])
    if shrink_cents <= 0:
        return Decimal("0.00")
    return q2(shrink_cents * dec(percentage))


def agreement_responsibility_pct(store_id, field):
    agreement = covering_agreement(store_id, statuses=("DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED"))
    if agreement is None:
        agreement = covering_agreement(store_id, statuses=("TERMINATED",))
    if agreement is None:
        return Decimal(0)
    return dec(agreement[field])


# ---------------------------------------------------------------------------
# Cascade: store termination (hops 2 and 3)
# ---------------------------------------------------------------------------

def terminate_store(store):
    """Store ACTIVE -> TERMINATED, continuing the chain into its children."""
    if store["status"] != "ACTIVE":
        return
    store["status"] = "TERMINATED"
    if store["transfer_status"] in ("PENDING", "APPROVED"):
        store["transfer_status"] = "NONE"
    db.touch(store)

    for order in db.find("fresh_orders", store_id=store["id"]):
        if order["status"] in ("PLACED", "CONFIRMED", "DELIVERED"):
            cancel_order_by_cascade(order)

    for window in db.find("delivery_windows", store_id=store["id"]):
        if window["status"] in ("SCHEDULED", "LOCKED"):
            window["status"] = "CANCELLED"
            db.touch(window)


def cancel_order_by_cascade(order):
    order["status"] = "CANCELLED"
    db.touch(order)
    window = db.get("delivery_windows", order["delivery_window_id"])
    if window is not None:
        window["reserved_units"] = max(0, int(window["reserved_units"]) - int(order["ordered_units"]))
        db.touch(window)
    for settlement in db.find("settlements", store_id=order["store_id"]):
        if settlement["status"] in ("OPEN", "DRAW_PAID"):
            finalize_settlement(settlement)


def finalize_settlement(settlement):
    """Settlement -> FINALIZED, then run the draw recovery waterfall."""
    if settlement["status"] == "FINALIZED":
        return
    if settlement["provisional"]:
        # Leaving the provisional variant settles at the final, capped share.
        share = q2(dec(settlement["gross_profit_cents"]) * dec(settlement["eligible_split_pct"]))
        settlement["franchisee_split_cents"] = share
        settlement["franchisor_share_cents"] = dec(settlement["gross_profit_cents"]) - share
        settlement["provisional"] = False
    settlement["status"] = "FINALIZED"
    recalculate_settlement_net(settlement)
    draw_recovery_allocation(settlement["franchisee_id"], settlement["net_settlement_cents"], settlement)
    recalculate_settlement_net(settlement)
    release_recovered_shrink_charges(settlement["franchisee_id"])
    db.touch(settlement)


def release_recovered_shrink_charges(franchisee_id):
    """A FINALIZED settlement recovers the operator's open shrink charges."""
    franchisee = db.get("franchisees", franchisee_id)
    if franchisee is None:
        return
    for audit in db.all_of("shrink_audits"):
        if audit["status"] != "FINALIZED" or audit["recovered_in_settlement"]:
            continue
        if _store_owner(audit["store_id"]) != franchisee_id:
            continue
        audit["recovered_in_settlement"] = True
    recalculate_franchisee(franchisee)


# ---------------------------------------------------------------------------
# Cascades driven by the Franchisee state machine
# ---------------------------------------------------------------------------

def cascade_stores_out_of_active(franchisee_id):
    for store in db.all_of("stores"):
        if store["franchisee_id"] == franchisee_id and store["status"] == "ACTIVE":
            terminate_store(store)
    for agreement in db.all_of("agreements"):
        if agreement["franchisee_id"] == franchisee_id and agreement["status"] == "ACTIVE":
            agreement["status"] = "TERMINATED"
            db.touch(agreement)


def cascade_reinstate(franchisee):
    """Hop 1: finalize COUNTED audits; hop 2: refresh standing; hop 3: restore stores."""
    store_ids = [s["id"] for s in db.all_of("stores") if s["franchisee_id"] == franchisee["id"]]
    for audit in db.all_of("shrink_audits"):
        if audit["store_id"] in store_ids and audit["status"] == "COUNTED":
            percentage = agreement_responsibility_pct(audit["store_id"], "shrink_responsibility_pct")
            audit["status"] = "FINALIZED"
            audit["shrink_charge_cents"] = shrink_charge(audit, percentage)
            audit["recovered_in_settlement"] = False
            db.touch(audit)

    recalculate_franchisee(franchisee)
    recalculate_franchisee(franchisee)

    for store in db.all_of("stores"):
        if store["franchisee_id"] == franchisee["id"] and store["status"] == "TERMINATED":
            store["status"] = "ACTIVE"
            store["transfer_status"] = "NONE"
            db.touch(store)


# ---------------------------------------------------------------------------
# Guarded lookups
# ---------------------------------------------------------------------------

def require_franchisee(franchisee_id):
    franchisee = db.get("franchisees", franchisee_id)
    if franchisee is None:
        fail("ERR_FRANCHISEE_NOT_FOUND")
    return franchisee


def require_store(store_id):
    store = db.get("stores", store_id)
    if store is None:
        fail("ERR_STORE_NOT_FOUND")
    return store


def require(table, record_id):
    record = db.get(table, record_id)
    if record is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return record


def require_state(record, expected):
    if record["status"] != expected:
        fail("ERR_INVALID_STATE")
    return record