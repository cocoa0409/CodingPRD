"""Calculation rules: money discipline, price quote, cancellation charge,
settlement waterfall and the continuing-education evaluation (PRD §2.6, §3.5,
§3.8, §3.9, §3.3).

Every monetary amount is an integer number of cents; every rate is expressed in
basis points and applied as `amount * bp / 10000` rounded half up.
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# --- price quote -----------------------------------------------------------
ROOM_CLASS_MULTIPLIER_BP = {"DRY": 10000, "WET": 11500, "HYDRO": 13000, "COUPLES": 12500}
PEAK_SURCHARGE_BP = 1500
HIGH_DEMAND_SURCHARGE_BP = 1000
SURCHARGE_CAP_BP = 2000
LOYALTY_DISCOUNT_BP = {"NONE": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500}
MAX_DISCOUNT_CENTS = 4000
PRICE_FLOOR_BP = 8000
PEAK_HOUR_START = 16
PEAK_HOUR_END = 20

# --- scheduling ------------------------------------------------------------
SCOPE_RANK = {"BASIC": 1, "ADVANCED": 2}
MIN_LEAD_MINUTES = 120

# --- settlement ------------------------------------------------------------
OVERTIME_GRACE_MINUTES = 5
SHORTFALL_GRACE_MINUTES = 5
OVERTIME_BLOCK_CENTS = 2500
OVERTIME_BLOCK_MINUTES = 15
SERVICE_CHARGE_STANDARD_BP = 1800
SERVICE_CHARGE_REDUCED_BP = 1500
SERVICE_CHARGE_TIER_THRESHOLD_CENTS = 50000
THERAPIST_SHARE_BP = 6000
SUPPORT_SHARE_BP = 2500
HOUSE_SHARE_BP = 1500
COMMISSION_BP = {"JUNIOR": 3000, "SENIOR": 3800, "MASTER": 4500}
RETAIL_COMMISSION_BP = 1200
GRATUITY_CAP_BP = 5000

# --- cancellation ----------------------------------------------------------
FREE_CANCEL_HOURS = 24
SHORT_NOTICE_HOURS = 4
LATE_CANCEL_BP = 5000
SHORT_NOTICE_BP = 10000
NO_SHOW_BP = 10000
HIGH_DEMAND_UPLIFT_BP = 2000
CHARGE_CAP_BP = 10000
NO_SHOW_GRACE_MINUTES = 15
LATE_CANCEL_RESTRICTION_THRESHOLD = 2
NO_SHOW_RESTRICTION_THRESHOLD = 1

# --- continuing education --------------------------------------------------
CE_PER_CATEGORY_CAP_HOURS = Decimal("8")
CE_ETHICS_MIN_HOURS = Decimal("2")
ROLLING_WINDOW_MONTHS = 24
CE_CATEGORIES = ("ETHICS", "CLINICAL", "SAFETY")
DEFAULT_CE_HOURS_REQUIRED = Decimal("12")

# --- clinical --------------------------------------------------------------
HIGH_RISK_CONDITION_CODES = (
    "ACUTE_HYPERTENSION",
    "PREGNANCY_FIRST_TRIMESTER",
    "DEEP_VEIN_THROMBOSIS",
    "RECENT_SURGERY_90D",
    "ACTIVE_INFECTION",
)
MAX_AMENDMENT_ROUNDS = 2

# --- reports / sweeps ------------------------------------------------------
MAX_REPORT_WINDOW_DAYS = 92
SWEEP_AUTO_CANCEL_HORIZON_HOURS = 48


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal to a whole number of cents, half up."""
    return int(round_half_up(value, 0))


def apply_bp(amount, rate_bp):
    """amount * rate_bp / 10000, rounded half up to a whole cent."""
    return cents(Decimal(amount) * Decimal(rate_bp) / Decimal(10000))


def pct2(numerator, denominator):
    """A percentage carrying exactly two decimal places; 0.00 on a zero denominator."""
    if denominator == 0:
        return Decimal("0.00")
    value = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return round_half_up(value, 2)


def hours(value):
    return round_half_up(Decimal(value), 1)


def months_before(reference, months):
    """The same calendar day `months` months earlier, clamped to month length."""
    total = (reference.year * 12 + (reference.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(reference.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --------------------------------------------------------------------------
# appointment_price_quote (PRD §3.5)
# --------------------------------------------------------------------------

def appointment_price_quote(treatment_type, room, guest, start_at):
    base = treatment_type["base_price_cents"]
    room_adjusted = apply_bp(base, ROOM_CLASS_MULTIPLIER_BP[room["room_class"]])
    peak_bp = PEAK_SURCHARGE_BP if PEAK_HOUR_START <= start_at.hour < PEAK_HOUR_END else 0
    demand_bp = HIGH_DEMAND_SURCHARGE_BP if treatment_type["high_demand"] else 0
    surcharge_bp = min(peak_bp + demand_bp, SURCHARGE_CAP_BP)
    surcharge = apply_bp(room_adjusted, surcharge_bp)
    subtotal = room_adjusted + surcharge
    raw_discount = apply_bp(subtotal, LOYALTY_DISCOUNT_BP[guest["loyalty_tier"]])
    discount = min(raw_discount, MAX_DISCOUNT_CENTS)
    price_floor = apply_bp(base, PRICE_FLOOR_BP)
    return max(subtotal - discount, price_floor)


# --------------------------------------------------------------------------
# cancellation_charge (PRD §3.8)
# --------------------------------------------------------------------------

def cancellation_band(appointment, clock, no_show=False):
    """Returns (charge_cents, is_charged_band)."""
    delta = appointment["start_at"] - clock
    hours_before = Decimal(delta.total_seconds()) / Decimal(3600)
    if no_show:
        band_bp = NO_SHOW_BP
    elif hours_before >= FREE_CANCEL_HOURS:
        return 0, False
    elif hours_before >= SHORT_NOTICE_HOURS:
        band_bp = LATE_CANCEL_BP
    else:
        band_bp = SHORT_NOTICE_BP
    if appointment["high_demand_slot"]:
        band_bp = band_bp + HIGH_DEMAND_UPLIFT_BP
    band_bp = min(band_bp, CHARGE_CAP_BP)
    return apply_bp(appointment["quoted_price_cents"], band_bp), True


# --------------------------------------------------------------------------
# settlement_distribution (PRD §3.9)
# --------------------------------------------------------------------------

def settlement_distribution(variant, appointment, therapist, room, purchased):
    """Six-step waterfall. `purchased` is the list of PURCHASED attachments."""
    quoted = appointment["quoted_price_cents"]

    # step 1 — basis and realised revenue
    if variant == "PROVISIONAL":
        basis_minutes = appointment["scheduled_duration_minutes"]
        realized = quoted
    else:
        scheduled = appointment["scheduled_duration_minutes"]
        actual = appointment["actual_duration_minutes"]
        basis_minutes = actual
        over = actual - scheduled - OVERTIME_GRACE_MINUTES
        if over <= 0:
            overtime_cents = 0
        else:
            blocks = int((Decimal(over) / Decimal(OVERTIME_BLOCK_MINUTES)).to_integral_value(
                rounding=ROUND_CEILING))
            overtime_cents = blocks * OVERTIME_BLOCK_CENTS
        if actual >= scheduled - SHORTFALL_GRACE_MINUTES:
            shortfall_cents = 0
        else:
            shortfall_cents = cents(
                Decimal(quoted) * Decimal(scheduled - actual) / Decimal(scheduled))
        realized = quoted + overtime_cents - shortfall_cents

    # step 2 — retail revenue
    retail_revenue = sum(a["amount_cents"] for a in purchased)

    # step 3 — service charge (tier keyed on the pre-charge basis)
    tier_basis = realized + retail_revenue
    service_charge_bp = (SERVICE_CHARGE_REDUCED_BP
                         if tier_basis >= SERVICE_CHARGE_TIER_THRESHOLD_CENTS
                         else SERVICE_CHARGE_STANDARD_BP)
    service_charge_pool = apply_bp(realized, service_charge_bp)

    # step 4 — distributable pool; the house takes the residual
    gratuity = appointment["gratuity_cents"] or 0
    pool = service_charge_pool + gratuity
    therapist_share = apply_bp(pool, THERAPIST_SHARE_BP)
    support_pool = apply_bp(pool, SUPPORT_SHARE_BP)
    house_share = pool - therapist_share - support_pool

    # step 5 — commissions
    therapist_commission = apply_bp(realized, COMMISSION_BP[therapist["commission_tier"]])
    retail_commission = sum(apply_bp(a["amount_cents"], RETAIL_COMMISSION_BP)
                            for a in purchased)

    # step 6 — costs, folio total, margin
    labor_cost = (apply_bp_per_hour(therapist["base_hourly_cost_cents"], basis_minutes)
                  + therapist_commission + therapist_share + retail_commission)
    room_fixed_cost = apply_bp_per_hour(room["hourly_fixed_cost_cents"], basis_minutes)
    folio_total = realized + retail_revenue + service_charge_pool + gratuity
    net_margin = realized + retail_revenue - labor_cost - room_fixed_cost

    return {
        "basis_duration_minutes": basis_minutes,
        "realized_price_cents": realized,
        "retail_revenue_cents": retail_revenue,
        "service_charge_bp": service_charge_bp,
        "service_charge_pool_cents": service_charge_pool,
        "gratuity_cents": gratuity,
        "distributable_pool_cents": pool,
        "therapist_share_cents": therapist_share,
        "support_pool_cents": support_pool,
        "house_share_cents": house_share,
        "therapist_commission_cents": therapist_commission,
        "retail_commission_cents": retail_commission,
        "labor_cost_cents": labor_cost,
        "room_fixed_cost_cents": room_fixed_cost,
        "folio_total_cents": folio_total,
        "net_margin_cents": net_margin,
    }


def apply_bp_per_hour(hourly_cents, minutes):
    """hourly_cents * minutes / 60, rounded half up."""
    return cents(Decimal(hourly_cents) * Decimal(minutes) / Decimal(60))


def gratuity_cap_for(appointment):
    return apply_bp(appointment["quoted_price_cents"], GRATUITY_CAP_BP)


# --------------------------------------------------------------------------
# ce_compliance_evaluation (PRD §3.3)
# --------------------------------------------------------------------------

def ce_window(license_row, variant, as_of_date):
    if variant == "ROLLING_24M":
        lower = months_before(as_of_date, ROLLING_WINDOW_MONTHS)
        return lower, as_of_date, False
    return license_row["current_period_start_on"], license_row["expires_on"], True


def ce_compliance_evaluation(license_row, records, variant="CALENDAR_WINDOW",
                             as_of_date=None):
    lower, upper, lower_inclusive = ce_window(license_row, variant, as_of_date)
    in_window = []
    for record in records:
        completed = record["completed_on"]
        if lower_inclusive:
            if lower <= completed <= upper:
                in_window.append(record)
        else:
            if lower < completed <= upper:
                in_window.append(record)

    credited = {}
    for category in CE_CATEGORIES:
        raw = sum((r["ce_hours"] for r in in_window if r["category"] == category),
                  Decimal("0"))
        credited[category] = min(hours(raw), CE_PER_CATEGORY_CAP_HOURS)

    credited_hours = hours(credited["ETHICS"] + credited["CLINICAL"] + credited["SAFETY"])
    ethics_credited = hours(credited["ETHICS"])
    required = Decimal(license_row["ce_hours_required"])
    shortfall = required - credited_hours
    if shortfall < 0:
        shortfall = Decimal("0")
    shortfall = hours(shortfall)
    if required > 0:
        ethics_met = ethics_credited >= CE_ETHICS_MIN_HOURS
    else:
        ethics_met = True
    compliant = shortfall == 0 and ethics_met
    return {
        "variant": variant,
        "window_start_on": lower,
        "window_end_on": upper,
        "credited_hours": credited_hours,
        "ethics_hours_credited": ethics_credited,
        "ce_hours_required": hours(required),
        "shortfall_hours": shortfall,
        "ethics_requirement_met": ethics_met,
        "compliant": compliant,
    }
