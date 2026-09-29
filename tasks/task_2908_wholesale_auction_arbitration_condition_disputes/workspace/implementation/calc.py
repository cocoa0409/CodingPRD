"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.4, 3.7, 3.8, 3.9)."""
from decimal import Decimal

import store as C
from util import bps_of, round_half_up, round_half_up_3

# --- transport allocation profiles: (buyer_bps, seller_bps) ------------------
ALLOCATION_BPS = {
    "UNWIND": {
        "SELLER": (0, 10000),
        "NONE": (5000, 5000),
        "BUYER": (10000, 0),
    },
    "REPAIR_ALLOWANCE": {
        "SELLER": (2000, 7000),
        "NONE": (2000, 7000),
        "BUYER": (2000, 7000),
    },
    "CLAIM_DENIED": {
        "SELLER": (10000, 0),
        "NONE": (10000, 0),
        "BUYER": (10000, 0),
    },
    "FRIVOLOUS_DENIED": {
        "SELLER": (10000, 0),
        "NONE": (10000, 0),
        "BUYER": (10000, 0),
    },
}


def leg_cost_cents(miles):
    """Dispatch fee plus a marginal-band distance charge (PRD 3.7)."""
    miles = int(miles)
    tier1 = min(miles, C.TRANSPORT_TIER1_MILES)
    tier2 = min(max(miles - C.TRANSPORT_TIER1_MILES, 0), C.TRANSPORT_TIER2_MILES)
    tier3 = max(miles - (C.TRANSPORT_TIER1_MILES + C.TRANSPORT_TIER2_MILES), 0)
    return (
        C.TRANSPORT_DISPATCH_FEE_CENTS
        + C.TRANSPORT_TIER1_CENTS_PER_MILE * tier1
        + C.TRANSPORT_TIER2_CENTS_PER_MILE * tier2
        + C.TRANSPORT_TIER3_CENTS_PER_MILE * tier3
    )


def allocate_transport(legs, outcome, fault_party):
    """Round each party's share PER LEG, then sum across legs (PRD 3.7).

    `legs` must already be in ascending created_at order. Returns the four
    stored totals plus the per-leg share triples in that same order.
    """
    buyer_bps, seller_bps = ALLOCATION_BPS[outcome][fault_party]
    per_leg = []
    total = 0
    buyer_total = 0
    seller_total = 0
    auction_total = 0
    for leg in legs:
        cost = int(leg["cost_cents"])
        buyer_leg = bps_of(cost, buyer_bps)
        seller_leg = bps_of(cost, seller_bps)
        auction_leg = cost - buyer_leg - seller_leg
        per_leg.append({"leg": leg, "cost": cost, "buyer": buyer_leg,
                        "seller": seller_leg, "auction": auction_leg})
        total += cost
        buyer_total += buyer_leg
        seller_total += seller_leg
        auction_total += auction_leg
    return {
        "transport_total_cents": total,
        "transport_buyer_share_cents": buyer_total,
        "transport_seller_share_cents": seller_total,
        "transport_auction_share_cents": auction_total,
        "per_leg": per_leg,
    }


def allowance_cap_cents(sale, policy):
    return bps_of(sale["sale_price_cents"], policy["max_allowance_bps"])


def award_base_cents(case, sale):
    """Base amount for the arbitrator award formula (PRD 3.8)."""
    if case["defect_class"] == "MILEAGE_DISCREPANCY":
        true_mileage = case["verified_true_mileage"]
        if true_mileage is None:
            true_mileage = case["odometer_at_claim"]
        overage = max(0, int(true_mileage) - int(sale["announced_odometer_miles"]))
        return overage * C.MILEAGE_DIMINUTION_CENTS_PER_MILE
    return int(case["latest_verified_estimate_cents"])


def computed_award_cents(case, sale, policy):
    severity = C.SEVERITY_MULTIPLIER_BPS[sale["light_channel"]]
    base = award_base_cents(case, sale)
    cap = allowance_cap_cents(sale, policy)
    return min(bps_of(base, severity), cap)


def rate_bps(upheld, sales):
    if not sales:
        return 0
    return round_half_up(Decimal(10000) * Decimal(int(upheld)) / Decimal(int(sales)))


def tier_for(current_tier, rolling_sales_count, rolling_rate_bps):
    """Tier is a pure function of the rolling rate; BLOCKED is sticky (PRD 3.9)."""
    if current_tier == "BLOCKED":
        return "BLOCKED"
    if rolling_sales_count < C.MIN_SCORECARD_SALES:
        return "GOOD_STANDING"
    if rolling_rate_bps >= C.TIER_BLOCK_BPS:
        return "BLOCKED"
    if rolling_rate_bps >= C.TIER_PROBATION_BPS:
        return "PROBATION"
    if rolling_rate_bps >= C.TIER_WATCH_BPS:
        return "WATCH"
    return "GOOD_STANDING"


def frivolous_fee_cents(prior_frivolous_count):
    return min(C.FRIVOLOUS_FEE_BASE_CENTS * (1 + int(prior_frivolous_count)),
               C.FRIVOLOUS_FEE_CAP_CENTS)


def hours_between(later, earlier):
    """Elapsed hours, rounded half up to three decimal places (PRD 3.4)."""
    seconds = Decimal((later - earlier).total_seconds())
    return round_half_up_3(seconds / Decimal(3600))


def window_evaluation(policy, hours_elapsed, miles_driven, psi_extension_hours):
    """Two independently nullable axes; time outranks mileage (PRD 3.4)."""
    if policy["window_hours"] is None:
        effective = None
        time_ok = True
    else:
        effective = int(policy["window_hours"]) + int(psi_extension_hours)
        time_ok = hours_elapsed <= Decimal(effective)
    if policy["mileage_limit"] is None:
        mileage_ok = True
    else:
        mileage_ok = miles_driven <= int(policy["mileage_limit"])
    return {
        "effective_window_hours": effective,
        "time_ok": time_ok,
        "mileage_ok": mileage_ok,
        "window_eligible": bool(time_ok and mileage_ok),
    }
