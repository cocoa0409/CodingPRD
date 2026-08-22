"""All calculation rules (PRD 2.5, 2.10, 2.11 and section 3).

Money is always an integer number of cents.  `round_half_up` is a Decimal
quantize with ROUND_HALF_UP; `ceil`/`floor` are exact integer operations.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

# ---------------------------------------------------------------- primitives

ZERO = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value):
    """Round to a whole cent, half away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------- constants

OFFICE_UNIT_CENTS = 42000
RESTROOM_UNIT_CENTS = 175000
PARTITION_SEGMENT_FT = Decimal("4.0")
PARTITION_SEGMENT_CENTS = 9500
SQFT_PER_INCLUDED_HALF_TON = Decimal("400.0")
HVAC_HALF_TON_CENTS = 68000

WIND_ZONE_MULTIPLIER = {1: Decimal("1.00"), 2: Decimal("1.15"), 3: Decimal("1.35"), 4: Decimal("1.60")}
TIER_DISCOUNT = {
    "PLATINUM": Decimal("0.06"),
    "GOLD": Decimal("0.03"),
    "STANDARD": Decimal("0.00"),
    "WATCH": Decimal("0.00"),
}
CONFIG_AMORT_MONTHS = Decimal(36)

ANCHOR_COST_CENTS = {"NONE": 0, "GROUND_ANCHOR": 85000, "PIER_FOUNDATION": 240000, "ENGINEERED_SLAB": 610000}
TIER1_FLOOR_CENTS = 300000
TIER2_FLOOR_CENTS = 800000

ACCESSORY_BASE_CENTS = {"STEPS": 12500, "RAMP_ADA": 47500, "COMBO": 55000}
RAMP_SEGMENT_FT = Decimal("4.0")
RAMP_SEGMENT_CENTS = 3800
LANDING_CENTS = 6200
LANDING_INTERVAL_FT = Decimal("30.0")

AREA_BLOCK_SQFT = Decimal("100.0")
AREA_BLOCK_CENTS = 1500

BAND1_CAP_MI = Decimal(50)
BAND2_WIDTH_MI = Decimal(100)
BAND2_CEILING_MI = Decimal(150)
BAND2_CENTS_PER_MI = Decimal(950)
BAND3_CENTS_PER_MI = Decimal(1450)
JOB_TYPE_CREW_FACTOR = {
    "DELIVERY_INSTALL": Decimal("1.0"),
    "TEARDOWN_RETURN": Decimal("0.75"),
    "RELOCATION": Decimal("1.5"),
}
OVERSIZE_SECTION_CENTS = 78000
RELOCATION_PASSTHROUGH_PCT = Decimal("0.85")

COMPONENT_BASE_CENTS = {
    "FLOOR": 32000,
    "WALL": 18000,
    "HVAC": 145000,
    "ROOF": 96000,
    "DOOR": 41000,
    "ELECTRICAL": 73000,
}
SEVERITY_FACTOR = {"MINOR": Decimal("0.35"), "MODERATE": Decimal("1.00"), "SEVERE": Decimal("2.25")}

WEAR_CAP_PCT_PER_MONTH = Decimal("0.0025")
DAMAGE_CAP_PCT = Decimal("0.40")
MAX_DISPUTE_ROUNDS = 2

SCOPE_FACTOR = {"COSMETIC": Decimal("0.45"), "STANDARD": Decimal("1.00"), "FULL": Decimal("1.85")}
REFURB_RECOVERY_PCT = Decimal("0.60")

EARLY_TERMINATION_PCT = Decimal("0.35")
HOLDOVER_PCT = Decimal("0.25")

REFURB_BUFFER_DAYS = 14
DAYS_PER_MONTH = 30

YARD_STATUSES = ("IN_FLEET", "RESERVED", "RETURNED", "REFURBISHING")


# ---------------------------------------------------------------- dates

def parse_iso_date(text):
    """Strict yyyy-mm-dd parsing; returns a date or None."""
    if not isinstance(text, str) or len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        year, month, day = text.split("-")
        if len(year) != 4 or len(month) != 2 or len(day) != 2:
            return None
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def format_date(value):
    return value.isoformat() if value is not None else None


def lease_end_date(start, term_months):
    """start_date + (term_months * 30) - 1 day, closed interval end."""
    return start + timedelta(days=term_months * DAYS_PER_MONTH - 1)


def day_diff(later, earlier):
    return (later - earlier).days


# ---------------------------------------------------------------- catalog

def building_spec_area(width_ft, length_ft):
    """width_ft * length_ft -- exact, never rounded, sections never multiply."""
    return D(width_ft) * D(length_ft)


def floorplan_config_surcharge(private_offices, restrooms, partition_linear_ft, hvac_tons, floor_area_sqft):
    office_cents = int(private_offices) * OFFICE_UNIT_CENTS
    restroom_cents = int(restrooms) * RESTROOM_UNIT_CENTS
    partition_cents = ceil_int(D(partition_linear_ft) / PARTITION_SEGMENT_FT) * PARTITION_SEGMENT_CENTS
    included_tons = D(floor_int(D(floor_area_sqft) / SQFT_PER_INCLUDED_HALF_TON)) * Decimal("0.5")
    excess_tons = D(hvac_tons) - included_tons
    if excess_tons < ZERO:
        excess_tons = ZERO
    hvac_cents = ceil_int(excess_tons / Decimal("0.5")) * HVAC_HALF_TON_CENTS
    return office_cents + restroom_cents + partition_cents + hvac_cents


# ---------------------------------------------------------------- lease money

def term_factor(term_months):
    if term_months <= 5:
        return Decimal("1.25")
    if term_months <= 11:
        return Decimal("1.10")
    if term_months <= 23:
        return Decimal("1.00")
    return Decimal("0.92")


def lease_monthly_rate(base_monthly_rate_cents, config_surcharge_cents, wind_zone, pinned_credit_tier, term_months):
    tf = term_factor(term_months)
    wf = WIND_ZONE_MULTIPLIER[int(wind_zone)]
    cf = Decimal(1) - TIER_DISCOUNT[pinned_credit_tier]
    spec_line = round_half_up(D(base_monthly_rate_cents) * tf * wf * cf)
    config_line = round_half_up(D(config_surcharge_cents) / CONFIG_AMORT_MONTHS)
    return spec_line + config_line


def lease_mobilization_fee(delivery_base_cents, install_base_cents, anchoring_standard):
    subtotal = int(delivery_base_cents) + int(install_base_cents) + ANCHOR_COST_CENTS[anchoring_standard]
    if subtotal < TIER1_FLOOR_CENTS:
        pct = Decimal("0.00")
    elif subtotal < TIER2_FLOOR_CENTS:
        pct = Decimal("0.05")
    else:
        pct = Decimal("0.09")
    discount = round_half_up(D(subtotal) * pct)
    return subtotal - discount


def quoted_projection(mobilization_fee_cents, monthly_base_rate_cents, monthly_accessory_rate_cents, term_months):
    monthly_total = int(monthly_base_rate_cents) + int(monthly_accessory_rate_cents)
    return int(mobilization_fee_cents) + monthly_total * int(term_months)


def settled_actual(monthly_base_rate_cents, monthly_accessory_rate_cents, term_months,
                   start_date, actual_vacated_date, mobilization_fee_cents,
                   permit_cents, relocation_surcharge_cents, damage_cents):
    monthly_total = int(monthly_base_rate_cents) + int(monthly_accessory_rate_cents)
    occupied_days = day_diff(actual_vacated_date, start_date) + 1
    billable_months = ceil_int(D(occupied_days) / D(DAYS_PER_MONTH))
    rent_cents = monthly_total * billable_months
    if billable_months < term_months:
        adjustment = round_half_up(D(monthly_total) * D(term_months - billable_months) * EARLY_TERMINATION_PCT)
    elif billable_months > term_months:
        adjustment = round_half_up(D(monthly_total) * D(billable_months - term_months) * HOLDOVER_PCT)
    else:
        adjustment = 0
    return (int(mobilization_fee_cents) + int(permit_cents) + rent_cents + adjustment
            + int(relocation_surcharge_cents) + int(damage_cents))


# ---------------------------------------------------------------- accessories

def accessory_package_rate(package_type, ramp_run_ft, landing_count):
    ramp_cents = ceil_int(D(ramp_run_ft) / RAMP_SEGMENT_FT) * RAMP_SEGMENT_CENTS
    landing_cents = int(landing_count) * LANDING_CENTS
    return ACCESSORY_BASE_CENTS[package_type] + ramp_cents + landing_cents


def ada_ramp_compliance(package_type, ramp_run_ft, landing_count, floor_height_in, min_ramp_run_ratio):
    rise_ft = D(floor_height_in) / Decimal("12.0")
    required_run_ft = rise_ft * D(min_ramp_run_ratio)
    required_landings = ceil_int(D(ramp_run_ft) / LANDING_INTERVAL_FT)
    compliant = (
        package_type in ("RAMP_ADA", "COMBO")
        and D(ramp_run_ft) >= required_run_ft
        and int(landing_count) >= required_landings
    )
    return "COMPLIANT" if compliant else "NON_COMPLIANT"


# ---------------------------------------------------------------- permits

def permit_fee(jurisdiction_permit_fee_cents, floor_area_sqft):
    blocks = ceil_int(D(floor_area_sqft) / AREA_BLOCK_SQFT)
    return int(jurisdiction_permit_fee_cents) + blocks * AREA_BLOCK_CENTS


# ---------------------------------------------------------------- logistics

def transport_cost(mileage_miles, crew_hours, labor_rate_cents_per_hour, job_type, sections):
    miles = D(mileage_miles)
    band2 = miles - BAND1_CAP_MI
    if band2 < ZERO:
        band2 = ZERO
    if band2 > BAND2_WIDTH_MI:
        band2 = BAND2_WIDTH_MI
    band3 = miles - BAND2_CEILING_MI
    if band3 < ZERO:
        band3 = ZERO
    mileage_cents = round_half_up(band2 * BAND2_CENTS_PER_MI + band3 * BAND3_CENTS_PER_MI)
    crew_cents = round_half_up(
        D(ceil_int(D(crew_hours))) * D(labor_rate_cents_per_hour) * JOB_TYPE_CREW_FACTOR[job_type]
    )
    oversize_cents = (int(sections) - 1) * OVERSIZE_SECTION_CENTS
    return mileage_cents + crew_cents + oversize_cents


def relocation_passthrough(transport_cost_cents):
    return round_half_up(D(transport_cost_cents) * RELOCATION_PASSTHROUGH_PCT)


# ---------------------------------------------------------------- damage

def damage_line_repair_cost(component, severity, quantity):
    return round_half_up(D(COMPONENT_BASE_CENTS[component]) * SEVERITY_FACTOR[severity] * D(quantity))


def damage_gross(line_items):
    """assessor_provisional: every line at full repair cost, wear included."""
    return sum(int(li["repair_cost_cents"]) for li in line_items)


def damage_finalized_net(line_items, gross_damage_cents, start_date, actual_vacated_date, replacement_value_cents):
    """finalized_net -> (wear_allowance_cents, chargeable_cents)."""
    wear_line_total = sum(int(li["repair_cost_cents"]) for li in line_items if li["wear_and_tear"])
    occupied_days = day_diff(actual_vacated_date, start_date) + 1
    months_on_lease = ceil_int(D(occupied_days) / D(DAYS_PER_MONTH))
    wear_cap = round_half_up(D(replacement_value_cents) * WEAR_CAP_PCT_PER_MONTH * D(months_on_lease))
    wear_allowance = min(wear_line_total, wear_cap)
    net = gross_damage_cents - wear_allowance
    if net < 0:
        net = 0
    chargeable = min(net, round_half_up(D(replacement_value_cents) * DAMAGE_CAP_PCT))
    return wear_allowance, chargeable


# ---------------------------------------------------------------- refurb

def refurbishment_estimate(labor_hours, labor_rate_cents_per_hour, scope, parts_cost_cents, chargeable_cents):
    factor = SCOPE_FACTOR[scope]
    labor_line = round_half_up(D(labor_hours) * D(labor_rate_cents_per_hour) * factor)
    parts_line = round_half_up(D(parts_cost_cents) * factor)
    damage_line = round_half_up(D(chargeable_cents) * REFURB_RECOVERY_PCT)
    return labor_line + parts_line + damage_line


# ---------------------------------------------------------------- aggregates

def branch_counters(units):
    """(units_in_yard, units_available, utilization_pct) recomputed from scratch."""
    total_assigned = len(units)
    units_in_yard = len([u for u in units if u["status"] in YARD_STATUSES])
    units_available = len([u for u in units if u["status"] == "IN_FLEET"])
    if total_assigned == 0:
        utilization = Decimal("0.00")
    else:
        utilization = round_half_up_2dp(
            Decimal(100) * D(total_assigned - units_available) / D(total_assigned)
        )
    return units_in_yard, units_available, utilization


def customer_balance(leases_in_creation_order):
    return sum(int(l["billed_to_date_cents"]) - int(l["credited_cents"]) for l in leases_in_creation_order)
