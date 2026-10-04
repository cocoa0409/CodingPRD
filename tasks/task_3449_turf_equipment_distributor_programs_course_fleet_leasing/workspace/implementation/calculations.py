"""The 10 pinned calculation rules (SCAFFOLD section 1.3 / PRD section 3).

All money is integer cents; rounding is round-half-up, applied only at the
steps the PRD pins. Fill-rate comparison is exact rational arithmetic.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import storage


def rhu(d):
    """Round a Decimal half-up to integer cents."""
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- equipment_spec_compliance ----------------------------------------------
REQUIRED_TIERS = {
    "CHAMPIONSHIP": ("TOURNAMENT",),
    "CLUB": ("TOURNAMENT", "PRO"),
    "MAINTENANCE": ("TOURNAMENT", "PRO", "STANDARD"),
}


def equipment_spec_compliant(lines, course):
    """Every line: model.tier admitted by the course cut standard AND the
    course turf_profile is in the model's eligible_turf_types. No partial credit."""
    models = storage.STORES["models"]
    for line in lines:
        model = models[line["model_id"]]
        if model["tier"] not in REQUIRED_TIERS[course["cut_quality_standard"]]:
            return False
        if course["turf_profile"] not in model["eligible_turf_types"]:
            return False
    return True


# --- fleet_lease_rate ---------------------------------------------------------
TIER_MULTIPLIER = {
    "CHAMPIONSHIP": Decimal("1.15"),
    "CLUB": Decimal("1.08"),
    "MAINTENANCE": Decimal("1.00"),
}
SPRING_PEAK_MONTHS = (3, 4, 5)
SPRING_PEAK_FACTOR = Decimal("1.06")


def fleet_lease_rate(lease, course, credited_appraisals):
    """Rounding order pinned: round tier x seasonal product ONCE, subtract the
    credit, then round the monthly division ONCE. No per-line rounding."""
    models = storage.STORES["models"]
    base = sum(models[l["model_id"]]["list_price_cents"] * l["qty"] for l in lease["lines"])
    mult = TIER_MULTIPLIER[course["cut_quality_standard"]]
    seasonal = SPRING_PEAK_FACTOR if lease["_start_date"].month in SPRING_PEAK_MONTHS else Decimal("1.00")
    total = rhu(Decimal(base) * mult * seasonal)
    credit = sum(a["valued_cents"] for a in credited_appraisals)
    net = max(0, total - credit)
    monthly = rhu(Decimal(net) / Decimal(lease["cycle_months"]))
    return {
        "base_value_cents": base,
        "total_contract_value_cents": total,
        "trade_in_credit_cents": credit,
        "net_contract_value_cents": net,
        "monthly_rate_cents": monthly,
    }


# --- trade_in_valuation -------------------------------------------------------
MONTHLY_HOURS_NORM = 50
BOOK_DEPRECIATION_MONTHS = 84
BOOK_RESIDUAL_FLOOR_PCT = Decimal("0.15")
MARKET_BASE_PCT = Decimal("0.60")
MARKET_HOURS_CAP = 4000
MARKET_HOURS_DECAY_PCT = Decimal("0.50")
CONDITION_MULTIPLIER = {
    "A": Decimal("1.00"),
    "B": Decimal("0.85"),
    "C": Decimal("0.70"),
    "D": Decimal("0.50"),
}


def trade_in_valuation(model, hours, condition_grade, policy):
    """Both variants computed; each rounded once at its final step."""
    list_price = Decimal(model["list_price_cents"])
    age_months = int(hours) // MONTHLY_HOURS_NORM
    book_raw = list_price * (Decimal(1) - Decimal(age_months) / Decimal(BOOK_DEPRECIATION_MONTHS))
    floor_val = list_price * BOOK_RESIDUAL_FLOOR_PCT
    book_value = rhu(book_raw if book_raw > floor_val else floor_val)
    hours_factor = Decimal(1) - (Decimal(min(hours, MARKET_HOURS_CAP)) / Decimal(MARKET_HOURS_CAP)) * MARKET_HOURS_DECAY_PCT
    market_value = rhu(list_price * MARKET_BASE_PCT * CONDITION_MULTIPLIER[condition_grade] * hours_factor)
    valued = book_value if policy == "BOOK" else market_value
    return {"book_value_cents": book_value, "market_value_cents": market_value, "valued_cents": valued}


# --- offseason_incentive_discount ---------------------------------------------
OFF_SEASON_MONTHS = (11, 12, 1, 2)
TIER2_THRESHOLD_CENTS = 200000
TIER2_PCT = Decimal("0.12")
TIER1_THRESHOLD_CENTS = 50000
TIER1_PCT = Decimal("0.07")
BASE_PCT = Decimal("0.03")


def order_subtotal(lines):
    parts = storage.STORES["parts"]
    return sum(l["qty"] * parts[l["part_id"]]["unit_cost_cents"] for l in lines)


def offseason_incentive(order_type, subtotal_cents, lines):
    """Applies only to STOCK orders submitted with the logical clock in
    Nov-Feb. PINNED: per-line round_half_up, then sum the line discounts."""
    if order_type != "STOCK" or clock.now().month not in OFF_SEASON_MONTHS:
        return {"off_season_applied": False, "discount_tier_pct": 0.0, "discount_cents": 0}
    if subtotal_cents >= TIER2_THRESHOLD_CENTS:
        pct = TIER2_PCT
    elif subtotal_cents >= TIER1_THRESHOLD_CENTS:
        pct = TIER1_PCT
    else:
        pct = BASE_PCT
    parts = storage.STORES["parts"]
    discount = 0
    for line in lines:
        line_base = line["qty"] * parts[line["part_id"]]["unit_cost_cents"]
        discount += rhu(Decimal(line_base) * pct)
    return {"off_season_applied": True, "discount_tier_pct": float(pct), "discount_cents": discount}


# --- warranty_labor_adjudication ----------------------------------------------
PARTS_HANDLING_PCT = Decimal("0.10")


def claim_labor_pair(labor_hours, distributor, model):
    """Computed at claim creation and pinned: distributor-billed vs factory-allowed."""
    hours = Decimal(str(labor_hours))
    claimed = rhu(hours * Decimal(distributor["labor_rate_cents"]))
    allowance = rhu(hours * Decimal(model["warranty_labor_hourly_cap_cents"]))
    return claimed, allowance


def warranty_adjudication(claim, distributor, model, effective_hours):
    """min of the two pricings of the effective hours; parts reimbursement is
    the only rounded step (cost x 1.10, round_half_up)."""
    hours = Decimal(str(effective_hours))
    at_rate = hours * Decimal(distributor["labor_rate_cents"])
    at_cap = hours * Decimal(model["warranty_labor_hourly_cap_cents"])
    adjudicated = rhu(at_rate if at_rate <= at_cap else at_cap)
    parts_reimbursed = rhu(Decimal(claim["parts_cost_cents"]) * (Decimal(1) + PARTS_HANDLING_PCT))
    return {
        "adjudicated_labor_cents": adjudicated,
        "parts_reimbursed_cents": parts_reimbursed,
        "payable_total_cents": adjudicated + parts_reimbursed,
    }


def claims_paid_ytd(distributor_id):
    """Sum of payable_total_cents over the distributor's claims PAID with
    paid_at in the current calendar year of the logical clock."""
    year = clock.now().year
    total = 0
    for c in storage.STORES["claims"].values():
        if c["distributor_id"] == distributor_id and c["status"] == "PAID" and c.get("_paid_dt") is not None:
            if c["_paid_dt"].year == year:
                total += c["payable_total_cents"]
    return total


# --- parts_stocking_compliance --------------------------------------------------
MIN_FILL_RATE_NUM = 92   # 0.92 inclusive boundary, compared as exact rationals
MIN_FILL_RATE_DEN = 100
REVIEW_WINDOW_DAYS = 365


def parts_stocking_compliance(distributor):
    """Window: own RECEIVED orders with created_at in [review-365d, review]
    (both bounds inclusive). Vacuous fill pass when the window is empty."""
    review_dt = clock.now()
    lo = review_dt - timedelta(days=REVIEW_WINDOW_DAYS)
    window = [
        o for o in storage.STORES["orders"].values()
        if o["distributor_id"] == distributor["id"]
        and o["status"] == "RECEIVED"
        and lo <= o["_created_dt"] <= review_dt
    ]
    parts = storage.STORES["parts"]
    if not window:
        fill_rate = 1.0
        fill_ok = True
    else:
        received = sum(o["received_units"] for o in window)
        ordered = sum(o["ordered_units"] for o in window)
        fill_ok = received * MIN_FILL_RATE_DEN >= MIN_FILL_RATE_NUM * ordered
        fill_rate = received / ordered if ordered else 1.0
    stock_value = 0
    for o in window:
        for pid, qty in o.get("_received_lines", {}).items():
            part = parts.get(pid)
            if part is not None:
                stock_value += qty * part["unit_cost_cents"]
    stock_ok = stock_value >= distributor["min_parts_stock_value_cents"]
    return fill_rate, stock_value, (fill_ok and stock_ok)


# --- remarketing_pricing --------------------------------------------------------
REMARKET_BASE_PCT = Decimal("0.55")
WEEKLY_DECAY_PCT = Decimal("0.02")
FLOOR_PCT = Decimal("0.60")
RESERVATION_HOLD_DAYS = 7


def remarketing_listing(model, condition_grade):
    ask = rhu(Decimal(model["list_price_cents"]) * REMARKET_BASE_PCT * CONDITION_MULTIPLIER[condition_grade])
    floor = rhu(Decimal(ask) * FLOOR_PCT)
    return ask, floor


def remarketing_decay(asking, floor):
    """One decay step per rollover, compounding, round_half_up at the step,
    never below the floor. Reservation expiry is NOT a decay step."""
    decayed = rhu(Decimal(asking) * (Decimal(1) - WEEKLY_DECAY_PCT))
    return max(floor, decayed)


# --- irrigation_design_spec -----------------------------------------------------
ZONES_PER_CONTROLLER = 8
BASE_DESIGN_FEE_CENTS = 250000
CONTROLLER_FEE_CENTS = 45000
ACRE_FEE_CENTS = 12000
GPD_PER_ACRE = {
    "BENTGRASS": 22000,
    "BERMUDA": 16000,
    "POA_ANNUA": 20000,
    "MIXED": 18000,
}


def irrigation_design_spec(acreage, zone_count, turf_profile):
    """Pinned order: controllers first, then the fee (fee never feeds
    controllers), then the water budget. ceil on controllers."""
    controllers = (zone_count + ZONES_PER_CONTROLLER - 1) // ZONES_PER_CONTROLLER
    fee = BASE_DESIGN_FEE_CENTS + controllers * CONTROLLER_FEE_CENTS + acreage * ACRE_FEE_CENTS
    budget = acreage * GPD_PER_ACRE[turf_profile]
    return {"controllers_required": controllers, "design_fee_cents": fee, "water_budget_gpd": budget}


# --- lease_billing_progression ----------------------------------------------------
def lease_billing(lease, today):
    """Months 1..cycle-1 bill monthly_rate_cents; the final month absorbs the
    remainder. Invariant INV-1: billed + remaining == net at every instant."""
    net = lease["net_contract_value_cents"]
    rate = lease["monthly_rate_cents"]
    cycle = lease["cycle_months"]
    elapsed = clock.whole_months_between(lease["_start_date"], today)
    elapsed = max(0, min(cycle, elapsed))
    if elapsed >= cycle:
        billed = net
    else:
        billed = min(net, elapsed * rate)
    return billed, net - billed


# --- model_sales_window_expiry ----------------------------------------------------
MODEL_SALES_WINDOW_MONTHS = 240


def model_is_aged_out(model):
    """Strict boundary: only an age strictly greater than 240 months
    discontinues the model."""
    return clock.add_months(model["_created_dt"], MODEL_SALES_WINDOW_MONTHS) < clock.now()
