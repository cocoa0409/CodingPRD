"""Every calculation of PRD 3 / SCAFFOLD 1.3.

Money is integer cents throughout. Rounding is half up (away from zero at the
midpoint) and happens only at the declared positions; the rounded integer is what
the next step consumes.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# --- quote pricing constants ------------------------------------------------
SCREEN_FACTOR = {"NONE": Decimal("1.00"), "MESH_70": Decimal("1.15"), "SOLID_130": Decimal("1.35")}
SCREEN_ADDER_CENTS_PER_FT = {"NONE": 0, "MESH_70": 12, "SOLID_130": 26}
CONDITION_LABOR_CENTS_PER_FT = {"SOIL": 95, "ASPHALT": 140, "CONCRETE": 210}
MOBILIZATION_MINIMUM_CENTS = 35000
ADDON_INSTALL_LABOR_CENTS = 2500
EVENT_SURGE_FACTOR = Decimal("1.25")
DELIVERY_FEE_CENTS = 18500
PERMIT_HANDLING_FEE_CENTS = 12500
PERMIT_FEE_WAIVER_THRESHOLD_CENTS = 150000
QUOTE_VALIDITY_DAYS = 14
MINIMUM_CONSTRUCTION_TERM_MONTHS = 3

# --- billing constants ------------------------------------------------------
DAYS_PER_RENTAL_MONTH = 30
BILLING_CYCLE_DAYS = 28
MINIMUM_EVENT_BILLABLE_DAYS = 3
LATE_FEE_RATE = Decimal("0.015")
NET_TERMS_DAYS = 30
TAX_BASIS_POINTS_DENOMINATOR = 10000

# --- reconciliation constants ----------------------------------------------
DAMAGE_CHARGE_PCT = Decimal("0.35")
DEPRECIATION_PCT_PER_MONTH = Decimal("0.02")
DEPRECIATION_FLOOR_PCT = Decimal("0.40")

# --- labor constants --------------------------------------------------------
TYPE_PRODUCTIVITY_FT_PER_HOUR = {
    "DELIVERY_INSTALL": 120, "RELOCATION": 80, "REMOVAL": 200, "RESET": 90,
}
ADDON_HANDLING_HOURS_PER_UNIT = Decimal("0.25")
MINIMUM_BILLABLE_LABOR_HOURS = Decimal("2.00")
QUARTER_HOUR = Decimal("0.25")
CREW_TRAVEL_BUFFER_MINUTES = 90

# --- cancellation constants -------------------------------------------------
FREE_CANCELLATION_NOTICE_HOURS = {"EVENT": 72, "CONSTRUCTION": 168}
EVENT_CANCELLATION_PCT = Decimal("0.50")
CONSTRUCTION_CANCELLATION_PCT = Decimal("0.25")


def round_half_up(value):
    """Round a Decimal to a whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    """Exact integer ceiling division on non-negative integers."""
    if denominator <= 0:
        return 0
    return -((-numerator) // denominator)


def ceil_to_quarter(hours):
    steps = (Decimal(hours) / QUARTER_HOUR).to_integral_value(rounding=ROUND_CEILING)
    return steps * QUARTER_HOUR


def tier_rate_cents_per_ft(linear_feet):
    """S1: flat rate on the TOTAL footage, not marginal."""
    if linear_feet <= 250:
        return 62
    if linear_feet <= 500:
        return 54
    if linear_feet <= 1000:
        return 47
    return 41


def price_quote(linear_feet, wind_screen, contract_type, term_months,
                site_condition, panel_product, addon_lines, addon_products):
    """calculations.quote_pricing S1..S13.

    addon_lines is the ordered list of {product_code, quantity}; addon_products
    maps a product code to its stored product row.
    """
    tier = tier_rate_cents_per_ft(linear_feet)                       # S1
    panel_base_cents = linear_feet * tier                            # S2 exact
    screened_panel_cents = round_half_up(                            # S3 round
        Decimal(panel_base_cents) * SCREEN_FACTOR[wind_screen])
    screen_adder_cents = linear_feet * SCREEN_ADDER_CENTS_PER_FT[wind_screen]   # S4 exact
    addon_monthly_cents = 0                                          # S5 exact
    addon_line_amounts = []
    for line in addon_lines:
        product = addon_products[line["product_code"]]
        amount = line["quantity"] * product["unit_monthly_rate_cents"]
        addon_line_amounts.append(amount)
        addon_monthly_cents += amount
    pre_adjustment_monthly_cents = (                                 # S6 exact
        screened_panel_cents + screen_adder_cents + addon_monthly_cents)
    if contract_type == "EVENT":                                     # S7
        adjustment_factor = EVENT_SURGE_FACTOR
    else:
        if term_months >= 12:
            rate = Decimal("0.14")
        elif term_months >= 6:
            rate = Decimal("0.08")
        else:
            rate = Decimal("0.00")
        adjustment_factor = Decimal(1) - rate
    monthly_recurring_cents = round_half_up(                         # S8 round
        Decimal(pre_adjustment_monthly_cents) * adjustment_factor)
    addon_unit_count = sum(line["quantity"] for line in addon_lines)  # S13
    install_labor_cents = max(                                       # S9 exact
        MOBILIZATION_MINIMUM_CENTS,
        linear_feet * CONDITION_LABOR_CENTS_PER_FT[site_condition]
        + ADDON_INSTALL_LABOR_CENTS * addon_unit_count)
    permit_handling_fee_cents = (                                    # S10
        0 if monthly_recurring_cents >= PERMIT_FEE_WAIVER_THRESHOLD_CENTS
        else PERMIT_HANDLING_FEE_CENTS)
    one_time_cents = (                                               # S11 exact
        install_labor_cents + DELIVERY_FEE_CENTS + permit_handling_fee_cents)
    panel_unit_count = ceil_div(linear_feet, panel_product["panel_length_ft"])   # S12

    priced_lines = [{
        "line_type": "PANEL_RENTAL",
        "product_code": panel_product["code"],
        "quantity": panel_unit_count,
        "amount_cents": screened_panel_cents,
    }]
    if wind_screen != "NONE":
        priced_lines.append({
            "line_type": "WIND_SCREEN",
            "product_code": None,
            "quantity": linear_feet,
            "amount_cents": screen_adder_cents,
        })
    for line, amount in zip(addon_lines, addon_line_amounts):
        priced_lines.append({
            "line_type": "ADDON_RENTAL",
            "product_code": line["product_code"],
            "quantity": line["quantity"],
            "amount_cents": amount,
        })
    return {
        "tier_rate_cents_per_ft": tier,
        "panel_unit_count": panel_unit_count,
        "monthly_recurring_cents": monthly_recurring_cents,
        "install_labor_cents": install_labor_cents,
        "permit_handling_fee_cents": permit_handling_fee_cents,
        "one_time_cents": one_time_cents,
        "priced_lines": priced_lines,
        "addon_unit_count": addon_unit_count,
    }


def crew_labor_hours(work_order_type, ordered_linear_feet, addon_unit_count):
    """calculations.crew_labor_hours H1..H6 -> Decimal multiple of 0.25."""
    rate = TYPE_PRODUCTIVITY_FT_PER_HOUR[work_order_type]
    base_hours = Decimal(ordered_linear_feet) / Decimal(rate)          # H2 exact
    if work_order_type in ("DELIVERY_INSTALL", "REMOVAL"):             # H3
        addon_hours = ADDON_HANDLING_HOURS_PER_UNIT * Decimal(addon_unit_count)
    else:
        addon_hours = Decimal(0)
    raw_hours = base_hours + addon_hours                               # H4
    quantised = ceil_to_quarter(raw_hours)                             # H5 ceiling
    return max(MINIMUM_BILLABLE_LABOR_HOURS, quantised)                # H6


def whole_days(start, end):
    """Whole days in the half-open window [start, end)."""
    seconds = int((end - start).total_seconds())
    return seconds // 86400


def period_charge(contract_type, monthly_recurring_cents, raw_days):
    """calculations.invoice_period_charge. Returns the RENTAL line amount."""
    if contract_type == "EVENT":
        day_count = max(MINIMUM_EVENT_BILLABLE_DAYS, raw_days)                 # E2
        daily_rate_cents = round_half_up(                                      # E3 round
            Decimal(monthly_recurring_cents) / Decimal(DAYS_PER_RENTAL_MONTH))
        return daily_rate_cents * day_count                                    # E4
    full_cycles = int((Decimal(raw_days) / Decimal(BILLING_CYCLE_DAYS)).to_integral_value(
        rounding=ROUND_FLOOR))                                                 # C2
    remainder_days = raw_days - full_cycles * BILLING_CYCLE_DAYS               # C3
    remainder_term = round_half_up(                                            # C4 round once
        Decimal(monthly_recurring_cents) * Decimal(remainder_days) / Decimal(BILLING_CYCLE_DAYS))
    return full_cycles * monthly_recurring_cents + remainder_term


def invoice_rollup(lines, rental_tax_rate_bp, past_due_open_cents, apply_late_fee):
    """calculations.invoice_total_rollup R2..R5."""
    subtotal_cents = sum(line["amount_cents"] for line in lines)               # R2 exact
    tax_cents = round_half_up(                                                 # R3 round
        Decimal(subtotal_cents) * Decimal(rental_tax_rate_bp)
        / Decimal(TAX_BASIS_POINTS_DENOMINATOR))
    late_fee_cents = 0                                                         # R4
    if apply_late_fee:
        late_fee_cents = round_half_up(Decimal(past_due_open_cents) * LATE_FEE_RATE)
    total_cents = subtotal_cents + tax_cents + late_fee_cents                  # R5
    return subtotal_cents, tax_cents, late_fee_cents, total_cents


def depreciation_factor(fleet_age_months):
    """B2: per-product factor, floored at 0.40."""
    return max(DEPRECIATION_FLOOR_PCT,
               Decimal(1) - DEPRECIATION_PCT_PER_MONTH * Decimal(fleet_age_months))


def loss_assessment(unit_returns, products_by_code, police_report_present, contract_type):
    """calculations.reconciliation_loss_assessment. Returns (variant, loss, damage)."""
    depreciated = bool(police_report_present) and contract_type == "CONSTRUCTION"
    variant = "DEPRECIATED_VALUE" if depreciated else "REPLACEMENT_COST"
    loss_charge_cents = 0
    damage_charge_cents = 0
    for entry in unit_returns:
        product = products_by_code[entry["product_code"]]
        unit_cost = product["replacement_cost_cents_per_unit"]
        if depreciated:
            factor = depreciation_factor(product["fleet_age_months"])
            loss_charge_cents += round_half_up(                                # B3 per product
                Decimal(entry["missing"]) * Decimal(unit_cost) * factor)
        else:
            loss_charge_cents += entry["missing"] * unit_cost                  # A1 exact
        damage_charge_cents += round_half_up(                                  # D1 per product
            Decimal(entry["damaged"]) * Decimal(unit_cost) * DAMAGE_CHARGE_PCT)
    return variant, loss_charge_cents, damage_charge_cents


def cancellation_fee(contract_type, monthly_recurring_cents, install_labor_cents,
                     notice_seconds):
    """calculations.cancellation_fee F3..F6. notice_seconds None -> no reference order."""
    if notice_seconds is None:
        return 0
    allowance = FREE_CANCELLATION_NOTICE_HOURS[contract_type] * 3600
    if notice_seconds >= allowance:
        return 0
    if contract_type == "EVENT":
        return (round_half_up(Decimal(monthly_recurring_cents) * EVENT_CANCELLATION_PCT)
                + install_labor_cents)
    return (round_half_up(Decimal(monthly_recurring_cents) * CONSTRUCTION_CANCELLATION_PCT)
            + MOBILIZATION_MINIMUM_CENTS)
