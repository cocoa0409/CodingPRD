"""Calculation rules (PRD sections 2.6, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.9)."""

from errors import ApiError
from store import db, fmt_dt, new_row, ordered, parse_date

# ------------------------------------------------------------------ constants

CLASS_WEIGHT_BP = {"ECONOMY": 10000, "PREMIUM": 12500, "BUSINESS": 16000,
                   "FIRST": 20000}
FFP_MULTIPLIER_BP = {"ECONOMY": 5000, "PREMIUM": 10000, "BUSINESS": 15000,
                     "FIRST": 20000}
DEFAULT_FACTOR_BP = 10000
RATE_SCALE = 1000000

TIER_A_CEILING_MILES = 10000
TIER_B_CEILING_MILES = 40000
TIER_A_RATE_PER_1000 = 1400
TIER_B_RATE_PER_1000 = 1150
TIER_C_RATE_PER_1000 = 900

FEE_TIER_1_CEILING = 500000
FEE_TIER_2_CEILING = 5000000
FEE_BP_TIER_1 = 75
FEE_BP_TIER_2 = 50
FEE_BP_TIER_3 = 25
LATE_PENALTY_BP = 200

MATERIALITY_BP = 200
COVERAGE_TIER_HIGH_BP = 2000
COVERAGE_TIER_MID_BP = 500
HAIRCUT_HIGH_BP = 0
HAIRCUT_MID_BP = 1500
HAIRCUT_LOW_BP = 3500
CAP_MULTIPLE = 25

MEMO_RAISE_WINDOW_DAYS = 45
ARBITRATION_MIN_AGE_DAYS = 90
AUDIT_TIME_BAR_DAYS = 730

RESOLVED_MEMO_STATUSES = ("ACCEPTED", "WITHDRAWN", "RESOLVED_UPHELD",
                          "RESOLVED_DENIED")
LIVE_INVOICE_STATUSES = ("SUBMITTED", "CLEARED", "PARTIALLY_REJECTED",
                         "FULLY_REJECTED", "SETTLED")


# ------------------------------------------------------------------ rounding

def round_half_up(numerator, denominator):
    """Integer division rounded half away from zero (PRD section 2.6)."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


# ------------------------------------------------------------- carrier money

def recompute_net_position(carrier):
    carrier["net_position_minor"] = (
        carrier["pending_receivable_minor"] + carrier["settled_receivable_minor"]
        - carrier["pending_payable_minor"] - carrier["settled_payable_minor"]
    )


# ---------------------------------------------------------- fx_rate_selection

def select_rate_scaled(from_ccy, to_ccy, anchor):
    if from_ccy == to_ccy:
        return RATE_SCALE
    candidates = [r for r in db.rates.values()
                  if r["from_currency"] == from_ccy
                  and r["to_currency"] == to_ccy
                  and r["_effective_date"] <= anchor]
    if not candidates:
        return None
    latest = max(c["_effective_date"] for c in candidates)
    best = [c for c in candidates if c["_effective_date"] == latest]
    best.sort(key=lambda r: r["_seq"])
    return best[0]["rate_scaled"]


def convert(amount_minor, from_ccy, to_ccy, anchor):
    rate = select_rate_scaled(from_ccy, to_ccy, anchor)
    if rate is None:
        raise ApiError("ERR_NO_EXCHANGE_RATE")
    return round_half_up(amount_minor * rate, RATE_SCALE), rate


# --------------------------------------------------- prorate_factor_selection

def coupons_of_ticket(ticket_id):
    return ordered([c for c in db.coupons.values() if c["ticket_id"] == ticket_id])


def factors_of_agreement(agreement_id):
    return ordered([f for f in db.factors.values()
                    if f["agreement_id"] == agreement_id])


def select_prorate_factor(coupon, ticket):
    """Returns (agreement, factor) or (None, None).  Pure lookup."""
    flown = coupon.get("_flown_at")
    if flown is None:
        return None, None
    flown_date = flown.date()
    candidates = []
    for agreement in db.agreements.values():
        if agreement["status"] != "ACTIVE":
            continue
        if agreement["issuing_carrier_id"] != ticket["validating_carrier_id"]:
            continue
        if agreement["partner_carrier_id"] != coupon["operating_carrier_id"]:
            continue
        eff_from = agreement["_effective_from"]
        eff_to = agreement["_effective_to"]
        if flown_date < eff_from or flown_date > eff_to:
            continue
        for factor in factors_of_agreement(agreement["id"]):
            if factor["class_of_service"] != coupon["class_of_service"]:
                continue
            if factor["origin"] != coupon["origin"] and factor["origin"] != "*":
                continue
            if (factor["destination"] != coupon["destination"]
                    and factor["destination"] != "*"):
                continue
            candidates.append((agreement, factor))
    if not candidates:
        return None, None
    top = max(c[1]["specificity_score"] for c in candidates)
    best = [c for c in candidates if c[1]["specificity_score"] == top]
    best.sort(key=lambda pair: pair[1]["_seq"])
    return best[0]


# --------------------------------------------------- coupon_revenue_allocation

def plan_proration(ticket, run_type):
    """Validates and computes a proration run without mutating anything."""
    all_coupons = coupons_of_ticket(ticket["id"])
    pool = ticket["total_fare_minor"]

    if run_type == "PROVISIONAL":
        wanted = ("OPEN", "FLOWN")
    else:
        wanted = ("FLOWN", "ADJUSTED")
    included = [c for c in all_coupons if c["coupon_status"] in wanted]
    included.sort(key=lambda c: c["coupon_number"])

    # Ladder step 27 — currency agreement on a matched pair (FINAL only).
    matches = {}
    if run_type == "FINAL":
        for coupon in included:
            agreement, factor = select_prorate_factor(coupon, ticket)
            if (agreement is not None
                    and agreement["settlement_currency"] != ticket["sale_currency"]):
                raise ApiError("ERR_CURRENCY_MISMATCH")
            matches[coupon["id"]] = (agreement, factor)

    # Ladder step 34 — non-empty run input.
    if not included:
        raise ApiError("ERR_NO_PRORATABLE_COUPONS")

    # Step 2 — off-the-top special prorate amounts (FINAL variant only).
    spa_total = 0
    planned = {}
    for coupon in included:
        agreement, factor = matches.get(coupon["id"], (None, None))
        if agreement is None:
            continue
        if agreement["agreement_type"] == "SPA_FLAT":
            amount = factor["flat_amount_minor"]
            planned[coupon["id"]] = (amount, "SPA_FLAT")
            spa_total += amount
        elif agreement["agreement_type"] == "SPA_PERCENT":
            amount = round_half_up(pool * factor["percent_bp"], 10000)
            planned[coupon["id"]] = (amount, "SPA_PERCENT")
            spa_total += amount

    # Ladder step 39 — special-prorate headroom.
    if spa_total > pool:
        raise ApiError("ERR_SPA_OVERALLOCATION")

    straight_rate_pool = pool - spa_total
    rest = [c for c in included if c["id"] not in planned]

    # Step 3 — weights.
    weights = {}
    for coupon in rest:
        agreement, factor = matches.get(coupon["id"], (None, None))
        if agreement is not None and agreement["agreement_type"] == "STRAIGHT_RATE":
            factor_bp = factor["factor_bp"]
        else:
            factor_bp = DEFAULT_FACTOR_BP
        weights[coupon["id"]] = round_half_up(
            coupon["tpm_miles"] * CLASS_WEIGHT_BP[coupon["class_of_service"]]
            * factor_bp, 10000)
    total_weight = sum(weights.values())

    # Step 4 — round per coupon, then grant the residual to one coupon.
    shares = {}
    if rest:
        for coupon in rest:
            shares[coupon["id"]] = round_half_up(
                straight_rate_pool * weights[coupon["id"]], total_weight)
        rounding_residual = straight_rate_pool - sum(shares.values())
        winner = sorted(
            rest, key=lambda c: (-weights[c["id"]], c["coupon_number"]))[0]
        shares[winner["id"]] += rounding_residual
        run_unallocated = 0
    else:
        rounding_residual = 0
        run_unallocated = straight_rate_pool

    return {
        "all_coupons": all_coupons,
        "pool": pool,
        "planned": planned,
        "shares": shares,
        "weights": weights,
        "spa_total": spa_total,
        "straight_rate_pool": straight_rate_pool,
        "total_weight": total_weight,
        "included_count": len(included),
        "rounding_residual": rounding_residual,
        "run_unallocated": run_unallocated,
    }


def commit_proration(ticket, run_type, plan):
    """Writes the planned allocation and records the ProrationRun ledger row."""
    all_coupons = plan["all_coupons"]
    pool = plan["pool"]
    planned = plan["planned"]
    shares = plan["shares"]
    weights = plan["weights"]

    allocated_total = 0
    for coupon in all_coupons:
        if coupon["id"] in planned:
            amount, basis = planned[coupon["id"]]
            coupon["allocated_amount_minor"] = amount
            coupon["allocation_basis"] = basis
            coupon["weight_units"] = 0
            allocated_total += amount
        elif coupon["id"] in shares:
            coupon["allocated_amount_minor"] = shares[coupon["id"]]
            coupon["allocation_basis"] = "STRAIGHT_RATE"
            coupon["weight_units"] = weights[coupon["id"]]
            allocated_total += shares[coupon["id"]]
        else:
            coupon["allocated_amount_minor"] = 0
            coupon["allocation_basis"] = "UNALLOCATED"
            coupon["weight_units"] = 0

    ticket["unallocated_residual_minor"] = pool - sum(
        c["allocated_amount_minor"] for c in all_coupons)
    ticket["last_run_type"] = run_type
    ticket["proration_status"] = run_type

    run = new_row({
        "ticket_id": ticket["id"],
        "run_type": run_type,
        "pool_minor": pool,
        "spa_total_minor": plan["spa_total"],
        "straight_rate_pool_minor": plan["straight_rate_pool"],
        "total_weight_units": plan["total_weight"],
        "included_coupon_count": plan["included_count"],
        "rounding_residual_minor": plan["rounding_residual"],
        "allocated_total_minor": allocated_total,
        "unallocated_residual_minor": plan["run_unallocated"],
    }, versioned=False)
    db.runs[run["id"]] = run
    return run


# ------------------------------------------------------------ ffp_mileage_cost

def ffp_tier_of(cumulative_miles):
    if cumulative_miles < TIER_A_CEILING_MILES:
        return "TIER_A", TIER_A_RATE_PER_1000
    if cumulative_miles < TIER_B_CEILING_MILES:
        return "TIER_B", TIER_B_RATE_PER_1000
    return "TIER_C", TIER_C_RATE_PER_1000


def ffp_estimate(coupon, carrier):
    miles = round_half_up(
        coupon["tpm_miles"] * FFP_MULTIPLIER_BP[coupon["class_of_service"]], 10000)
    tier, rate = ffp_tier_of(carrier["period_accrued_miles"])
    cost = round_half_up(miles * rate, 1000)
    coupon["ffp_miles_awarded"] = miles
    coupon["ffp_tier"] = tier
    coupon["ffp_accrual_cost_minor"] = cost
    return miles, cost


def ffp_period_true_up(carrier, period):
    period_coupons = [
        c for c in db.coupons.values()
        if c["operating_carrier_id"] == carrier["id"]
        and c["coupon_status"] in ("FLOWN", "ADJUSTED")
        and c.get("_flown_at") is not None
        and period["_period_start"] <= c["_flown_at"] < period["_period_end"]
    ]
    if not period_coupons:
        return False
    period_miles = sum(c["ffp_miles_awarded"] for c in period_coupons)
    _tier, rate = ffp_tier_of(period_miles)
    trued = round_half_up(period_miles * rate, 1000)
    estimates = sum(c["ffp_accrual_cost_minor"] for c in period_coupons)
    carrier["period_ffp_cost_trued_up_minor"] = trued
    carrier["ffp_true_up_delta_minor"] = trued - estimates
    return True


# ---------------------------------------------------------- invoice_claim_build

def coupons_of_invoice(invoice_id):
    return ordered([c for c in db.coupons.values()
                    if c.get("billing_invoice_id") == invoice_id])


def build_claim(invoice, late):
    gross = sum(c["allocated_amount_minor"]
                for c in coupons_of_invoice(invoice["id"]))
    if gross < FEE_TIER_1_CEILING:
        fee_bp = FEE_BP_TIER_1
    elif gross < FEE_TIER_2_CEILING:
        fee_bp = FEE_BP_TIER_2
    else:
        fee_bp = FEE_BP_TIER_3
    handling_fee = round_half_up(gross * fee_bp, 10000)
    penalty = round_half_up(gross * LATE_PENALTY_BP, 10000) if late else 0
    total_claim = gross - handling_fee - penalty
    net_billed = total_claim - invoice["rejected_amount_minor"]
    return {
        "gross_billed_minor": gross,
        "ich_fee_bp": fee_bp,
        "ich_handling_fee_minor": handling_fee,
        "late_submission_penalty_minor": penalty,
        "total_claim_minor": total_claim,
        "net_billed_minor": net_billed,
    }


# ------------------------------------------------------------------ memo aging

def memo_age_days(memo):
    raised = memo.get("_raised_at")
    if raised is None:
        return 0
    if memo["status"] in RESOLVED_MEMO_STATUSES and memo.get("_resolved_at"):
        anchor = memo["_resolved_at"]
    else:
        anchor = db.clock
    seconds = int((anchor - raised).total_seconds())
    return seconds // 86400


def aging_bucket_of(age_days):
    if age_days < 30:
        return "CURRENT"
    if age_days < 60:
        return "AGED_30"
    if age_days < 90:
        return "AGED_60"
    return "AGED_90"


def refresh_memo_aging(memo):
    age = memo_age_days(memo)
    memo["age_days"] = age
    memo["aging_bucket"] = aging_bucket_of(age)
    return memo


# --------------------------------------------- audit population + extrapolation

def derive_audit_population(audited_carrier_id, period, claim_currency):
    population = []
    for coupon in ordered(list(db.coupons.values())):
        if coupon["operating_carrier_id"] != audited_carrier_id:
            continue
        if coupon["coupon_status"] not in ("FLOWN", "ADJUSTED"):
            continue
        flown = coupon.get("_flown_at")
        if flown is None:
            continue
        if not (period["_period_start"] <= flown < period["_period_end"]):
            continue
        if not coupon.get("billing_invoice_id"):
            continue
        ticket = db.tickets.get(coupon["ticket_id"])
        if ticket is None or ticket["sale_currency"] != claim_currency:
            continue
        population.append(coupon)
    return population


def close_extrapolation(sample, period):
    undercharge = sample["sampled_undercharge_minor"]
    sampled = sample["sampled_allocated_minor"]
    population = sample["population_allocated_minor"]

    ratio_bp = round_half_up(undercharge * 10000, sampled) if sampled else 0
    coverage_bp = round_half_up(sampled * 10000, population) if population else 0

    if coverage_bp >= COVERAGE_TIER_HIGH_BP:
        haircut_bp = HAIRCUT_HIGH_BP
    elif coverage_bp >= COVERAGE_TIER_MID_BP:
        haircut_bp = HAIRCUT_MID_BP
    else:
        haircut_bp = HAIRCUT_LOW_BP

    extrapolated = round_half_up(undercharge * population, sampled) if sampled else 0

    result = {
        "undercharge_ratio_bp": ratio_bp,
        "coverage_bp": coverage_bp,
        "haircut_bp": haircut_bp,
        "extrapolated_gross_minor": extrapolated,
    }
    if ratio_bp < MATERIALITY_BP:
        result["claim_amount_minor"] = 0
        result["claim_settlement_minor"] = 0
        result["status"] = "CLOSED_IMMATERIAL"
        return result

    capped = min(extrapolated, CAP_MULTIPLE * undercharge)
    claim = round_half_up(capped * (10000 - haircut_bp), 10000)
    settlement, _rate = convert(claim, sample["claim_currency"],
                                period["settlement_currency"],
                                period["_rate_fixing_date"])
    result["claim_amount_minor"] = claim
    result["claim_settlement_minor"] = settlement
    result["status"] = "CLAIM_RAISED"
    return result
