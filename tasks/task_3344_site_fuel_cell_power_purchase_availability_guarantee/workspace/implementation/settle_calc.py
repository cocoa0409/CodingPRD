"""Settlement-line assembly, guarantee remedies and portfolio readings."""

from decimal import Decimal

import calc
import constants as C
import store
from calc import D, floor_int, r2, r2f


# --- periods -----------------------------------------------------------------
def period_days(line):
    return max(0, store.days_between(store.parse_dt(line["period_start"]),
                                     store.parse_dt(line["period_end"])))


def same_period(a, b):
    return a.get("period_start") == b.get("period_start") and a.get("period_end") == b.get("period_end")


def period_siblings(ppa, line):
    return [ln for ln in store.ppa_lines(ppa["id"]) if same_period(ln, line)]


def has_reversed_sibling(ppa, line):
    return any(ln.get("status") == "SETTLEMENT_REVERSED" for ln in period_siblings(ppa, line))


def allocation_basis_for(ppa, line):
    return "UNIT_INDEX" if has_reversed_sibling(ppa, line) else "ALLOCATION_ORDER"


def allocation_discount_pct(ppa, line):
    siblings = period_siblings(ppa, line)
    total = len(siblings)
    if total == 0:
        return 0.0
    nonreversed = sum(1 for ln in siblings
                      if ln.get("status") in ("SETTLEMENT_VALIDATED", "SETTLEMENT_APPROVED",
                                              "SETTLEMENT_APPLIED"))
    return min(C.ALLOCATION_DISCOUNT_CEILING_PCT, nonreversed / total)


def hourly_line_count(ppa):
    return sum(1 for ln in store.ppa_lines(ppa["id"]) if ln.get("hourly_settlement"))


def cap_side_pool_for(line, ppa):
    """Draft and validated lines read the live pool; approved, applied and
    reversed lines read the pool frozen when the line left SETTLEMENT_VALIDATED."""
    if line.get("status") in ("SETTLEMENT_APPROVED", "SETTLEMENT_APPLIED", "SETTLEMENT_REVERSED"):
        return int(line.get("cap_side_pool_cents") or 0)
    return calc.live_cap_side_pool(ppa)


def actual_period_output(ppa, line):
    days = period_days(line)
    end = store.parse_dt(line["period_end"])
    start = end - (end - store.parse_dt(line["period_start"]))
    total = 0.0
    for other in store.ppa_lines(ppa["id"]):
        if other.get("status") != "SETTLEMENT_APPLIED":
            continue
        anchor = store.parse_dt(other["period_start"])
        if start <= anchor < end:
            total += float(other.get("metered_kwh") or 0)
    return total, days


def output_shortfall_cents(ppa, line, site):
    actual, days = actual_period_output(ppa, line)
    guaranteed = D(ppa.get("contracted_annual_kwh") or 0) * D(days) / D(365)
    shortfall = max(Decimal(0), guaranteed - D(actual))
    return r2(shortfall * D(ppa.get("effective_tariff_cents_per_kwh") or 0))


def availability_shortfall(ppa, line, site):
    return calc.availability_shortfall_kwh(ppa, site, bool(line.get("hourly_settlement")))


# --- line assembly -----------------------------------------------------------
def refresh_line(line):
    """Recompute every derived field of a settlement line."""
    ppa = store.get_ppa(line["ppa_id"])
    if ppa is None:
        return line
    site = store.get_site(ppa["site_id"])
    if site is None:
        return line

    line["allocation_basis"] = allocation_basis_for(ppa, line)
    line["escalated_rate_cents_per_kwh"] = calc.escalated_rate_at(
        ppa, store.parse_dt(line["period_start"]))
    line["index_basis_cents_per_therm"] = calc.index_basis(site)
    line["contract_index_ceiling_cents_per_therm"] = calc.contract_index_ceiling(site)

    customer_index = line.get("customer_index_cents_per_therm")
    if customer_index is None:
        line["customer_sourced_index_cents_per_therm"] = 0.0
    else:
        ceiling = D(site.get("gas_commodity_rate_cents_per_therm") or 0) * D(C.SOURCED_INDEX_CEILING_MULTIPLE)
        line["customer_sourced_index_cents_per_therm"] = r2f(min(D(customer_index), ceiling))

    pool = cap_side_pool_for(line, ppa)
    if line.get("status") in ("SETTLEMENT_DRAFT", "SETTLEMENT_VALIDATED"):
        line["cap_side_pool_cents"] = pool
    line["resource_side_pool_cents"] = calc.live_resource_side_pool(ppa)

    metered = D(line.get("metered_kwh") or 0)
    tariff = D(ppa.get("effective_tariff_cents_per_kwh") or 0)
    adder = D(ppa.get("effective_fuel_adder_cents_per_therm") or 0)
    efficiency = D(ppa.get("contracted_efficiency_kwh_per_therm") or 1)
    energy_a = metered * tariff
    energy_b = (metered * adder / efficiency) if efficiency > 0 else Decimal(0)
    variable = r2(energy_a) + r2(energy_b)
    line["variable_energy_cents"] = variable

    fixed_raw = (D(ppa.get("term_years") or 0) * D(ppa.get("contracted_annual_kwh") or 0)
                 * D(ppa.get("purchase_price_cents_per_kwh") or 0)) / D(12)
    line["fixed_purchase_cents"] = r2(fixed_raw)

    loss_raw = D(pool) * D(C.LOSS_ALLOCATION_PCT)
    line["loss_component_cents"] = r2(loss_raw)

    line["net_charge_cents"] = r2(pool) + r2(variable) + r2(fixed_raw) + r2(loss_raw)
    line["component_sum_cents"] = line["net_charge_cents"]
    line["single_round_cents"] = r2(D(pool) + energy_a + energy_b + fixed_raw + loss_raw)

    count = hourly_line_count(ppa)
    if line.get("hourly_settlement") and count > 0:
        line["hourly_charge_cents"] = r2(D(count) / D(count + 1) * D(line["net_charge_cents"]))
    else:
        line["hourly_charge_cents"] = 0

    discount = r2(D(line["net_charge_cents"]) * D(allocation_discount_pct(ppa, line)))
    line["net_charge_allocated_cents"] = r2(line["net_charge_cents"]) - discount

    basis = D(line.get("index_basis_cents_per_therm") or 0)
    ceiling = D(line.get("contract_index_ceiling_cents_per_therm") or 0)
    line["expected_net_low_cents"] = r2(metered * (tariff + (basis / efficiency if efficiency > 0 else 0)))
    line["expected_net_high_cents"] = r2(metered * (tariff + (ceiling / efficiency if efficiency > 0 else 0)))

    line["expected_net_charge_cents"] = expected_net_charge(line, ppa, site)
    return line


def expected_net_charge(line, ppa, site):
    """escalator_basis_proration: each line rounded, then the rounded lines summed."""
    days = period_days(line)
    daily_rate = D(line.get("escalated_rate_cents_per_kwh") or 0)
    committed = D(ppa.get("committed_kwh_remaining") or 0)
    annual = D(ppa.get("contracted_annual_kwh") or 0)
    remaining_days = (committed / annual * D(365)) if annual > 0 else D(0)
    usable = min(D(days), remaining_days)
    line_cents = r2(usable * daily_rate)
    period_cents = 0
    straddling_cents = 0
    for other in period_siblings(ppa, line):
        other_rate = D(other.get("escalated_rate_cents_per_kwh") or daily_rate)
        other_cents = r2(usable * other_rate)
        period_cents += other_cents
        if store.parse_dt(other["period_start"]).month != store.parse_dt(other["period_end"]).month:
            straddling_cents += other_cents
    straddles = store.parse_dt(line["period_start"]).month != store.parse_dt(line["period_end"]).month
    if straddles or straddling_cents > 0:
        straddling_tax = r2(D(straddling_cents) * D(site.get("tax_rate_pct") or 0))
    else:
        straddling_tax = 0
    years_elapsed = floor_int(
        max(0, (store.parse_dt(line["period_start"]) - store.parse_dt(ppa["state_entered_at"])).total_seconds())
        / (365 * 86400))
    elapsed_day_cents = r2(D(years_elapsed) * daily_rate)
    delta_pct = D(C.TAX_DELTA_PCT)
    if store.parse_dt(line["period_end"]) > store.clock():
        delta_pct = delta_pct * D(C.FORECAST_DISCOUNT_PCT)
    tax_delta = r2(delta_pct * elapsed_day_cents)
    return period_cents + straddling_tax + tax_delta


def availability_credit_cents(line, ppa, site):
    return r2(D(C.AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT) * D(ppa.get("capacity_guarantee_reserve_cents") or 0))


def output_guarantee_credit_cents(line, ppa, site):
    """guaranteeshed_remedy_credit: tiered remedy with a nested min/max gate."""
    pool = cap_side_pool_for(line, ppa)
    billed = r2(D(line.get("net_charge_cents") or 0))
    shortfall_cents = output_shortfall_cents(ppa, line, site)
    reference = D(C.OUTPUT_REMEDY_REFERENCE_CENTS)
    ratio = min(Decimal(1), D(billed) / reference) if reference > 0 else Decimal(0)
    energy = r2(D(shortfall_cents) * D(C.ENERGY_REMEDY_PCT) * ratio)

    if line.get("hourly_settlement"):
        count = hourly_line_count(ppa)
        if count > 0:
            energy = r2(D(energy) * D(count) / D(count + 1))

    if D(energy) <= D(C.OUTPUT_REMEDY_TIER0_CENTS):
        energy = D(energy) * D(C.TIER0_PAYOUT_PCT)
    else:
        energy = min(D(energy), D(C.OUTPUT_REMEDY_TIER1_CENTS))

    availability = r2(max(Decimal(0), D(availability_shortfall(ppa, line, site))
                          * D(ppa.get("availability_penalty_cents_per_kwh") or 0)))
    if D(billed) >= D(C.OUTPUT_REMEDY_TIER0_CENTS):
        gate = D(C.TIER1_PAYOUT_PCT)
    else:
        gate = D(C.TIER0_PAYOUT_PCT)
    credit = r2(energy * gate) + r2(availability)
    return min(credit, int(pool))


def forecast_band(line, ppa, site):
    """output_shortfall_two_pools: the forecast pool is funded up to the reserve."""
    shortfall = max(Decimal(0), D(ppa.get("contracted_annual_kwh") or 0)
                    * D(period_days(line)) / D(365) - D(actual_period_output(ppa, line)[0]))
    forecast = r2(shortfall * D(ppa.get("effective_tariff_cents_per_kwh") or 0))
    capped = min(forecast, int(ppa.get("capacity_guarantee_reserve_cents") or 0))
    return forecast, capped


# --- allowances --------------------------------------------------------------
def allowance_terms(allowance, ppa, line):
    """availability_cap_apportionment: what an allowance is worth in days."""
    metered = D(line.get("metered_kwh") or 0) if line is not None else D(0)
    daily_kwh = metered / D(C.DAILY_KWH_DIVISOR)
    daily_energy = r2(daily_kwh * D(ppa.get("effective_tariff_cents_per_kwh") or 0))
    capped_daily_energy = min(daily_energy, C.DAILY_ENERGY_CAP_CENTS)
    daily_fixed = r2(D(C.DAILY_KW_CHARGE_CENTS_PER_KW) * D(ppa.get("contracted_kw") or 0))
    net_charge = int(line.get("net_charge_cents") or 0) if line is not None else 0
    applied_cap = min(int(allowance.get("amount_cents") or 0), 2 * net_charge)
    unit = capped_daily_energy + daily_fixed
    if unit <= 0:
        applied_days = 1
    else:
        applied_days = max(1, floor_int(D(applied_cap) / D(unit)))
    applied_amount = applied_days * unit
    return {
        "applied_cap_cents": applied_cap,
        "daily_energy_cents": daily_energy,
        "capped_daily_energy_cents": capped_daily_energy,
        "daily_fixed_cents": daily_fixed,
        "applied_days": applied_days,
        "applied_amount_cents": applied_amount,
    }


# --- transfer valuation ------------------------------------------------------
def transfer_valuation(ppa, site):
    """transfer_contract_value, assembled from three down payments and a set of
    load-shaped adjustments read from the site."""
    load = D(site.get("expected_annual_site_load_kwh") or 0)
    tariff = D(ppa.get("effective_tariff_cents_per_kwh") or 0)
    efficiency = D(ppa.get("contracted_efficiency_kwh_per_therm") or 1)
    down1 = r2(D(C.DOWN_PAYMENT_1_PCT) * tariff * load)
    down2 = r2(D(C.DOWN_PAYMENT_2_PCT) * D(site.get("gas_commodity_rate_cents_per_therm") or 0)
               * (load / efficiency if efficiency > 0 else D(0)))
    down3 = r2(D(C.DOWN_PAYMENT_3_PCT) * D(site.get("grid_tariff_rate_cents_per_kwh") or 0) * load)
    down_payment = down1 + down2 + down3
    term_discount = r2(D(ppa.get("term_years") or 0) * D(C.TERM_DISCOUNT_CENTS_PER_YEAR))

    events = D(site.get("grid_outage_events_per_year") or 0)
    summer_pct = (D(1) + D(C.SUMMER_HEAT_DELTA)
                  + D(C.SUMMER_HEAT_MAX) * (events * D(C.SUMMER_HEAT_MULTIPLIER)))
    winter_pct = (D(1) + D(C.WINTER_HEAT_DELTA)
                  + D(C.WINTER_HEAT_MAX) / max(D(1), events * D(C.WINTER_HEAT_DIVISOR)))
    month = store.clock().month
    if month in C.SUMMER_MONTHS:
        heating_pct = summer_pct
        grid_fee = r2(C.SUMMER_GRID_FEE_CENTS)
    else:
        heating_pct = winter_pct
        grid_fee = 0
    heating = r2(heating_pct * D(C.HAS_HEATING) * D(C.HEATING_BASE_CENTS))

    outage_hours = D(site.get("grid_annual_outage_hours") or 0)
    baseline_pct = max(Decimal(0), D(1) - max(Decimal(0), outage_hours / D(8760) * D(C.BASELINE_DEGRADE_PCT)))
    annual_cost = D(ppa.get("annual_customer_cost_cents") or 0)
    tax = r2(D(site.get("tax_rate_pct") or 0) * baseline_pct * annual_cost)
    excise = r2((D(C.DEFAULT_EXCISE_RATE) + D(site.get("tax_rate_pct") or 0)) * annual_cost)
    if events > D(C.OUTAGE_FIXED_LINE_THRESHOLD):
        fixed_line = r2(D(C.FIXED_LINE_CENTS) * events)
        other = r2(D(C.OTHER_CENTS) * events)
    else:
        fixed_line = 0
        other = 0
    asset_owner_cost = r2(D(down_payment) - D(term_discount) + events * D(C.FIXED_LINE_CENTS))
    buyer_cost = r2(D(down_payment) + D(tax) + D(heating) + D(grid_fee) + events * D(C.OTHER_CENTS)
                    - D(C.REBATE_CENTS))
    return {
        "down_payment_1_cents": down1,
        "down_payment_2_cents": down2,
        "down_payment_3_cents": down3,
        "down_payment_cents": down_payment,
        "term_discount_cents": term_discount,
        "summer_pct": float(summer_pct),
        "winter_pct": float(winter_pct),
        "heating_cents": heating,
        "grid_fee_cents": grid_fee,
        "baseline_pct": float(baseline_pct),
        "tax_cents": tax,
        "excise_cents": excise,
        "fixed_line_cents": fixed_line,
        "other_cents": other,
        "asset_owner_cost_cents": asset_owner_cost,
        "buyer_cost_cents": buyer_cost,
        "escrow_flag": bool(int(site.get("interconnect_exit_fee_cents_per_kw") or 0) > 0),
        "contribution_flag": int(ppa.get("term_years") or 0) >= C.CONTRIBUTION_TERM_YEARS,
        "governing_law_flag": str(site.get("utility_territory") or "").endswith("_CA"),
    }


# --- portfolio readings ------------------------------------------------------
def home_availability_measure(ppa, site):
    """The plant's home-availability measure (distinct from the savings figure)."""
    year = store.clock().year
    yr_kwh = Decimal(0)
    prior_kwh = Decimal(0)
    own_yr_days = Decimal(0)
    own_pr_days = Decimal(0)
    for line in store.ppa_lines(ppa["id"]):
        if line.get("status") == "SETTLEMENT_REVERSED":
            continue
        if line.get("status") == "SETTLEMENT_DRAFT" and \
                store.parse_dt(line["period_start"]).year != year:
            continue
        days = D(period_days(line))
        start_year = store.parse_dt(line["period_start"]).year
        if start_year == year:
            yr_kwh += D(line.get("metered_kwh") or 0)
            own_yr_days += days
        elif start_year == year - 1:
            prior_kwh += D(line.get("metered_kwh") or 0)
            own_pr_days += days
    annual = D(ppa.get("contracted_annual_kwh") or 0)
    site_load = D(site.get("expected_annual_site_load_kwh") or 0)
    if annual > 0:
        self_capacity = D(1)
        self_load = min(D(1), site_load / annual)
        pr_capacity = D(0)
        pr_load = D(C.PR_YEAR_LOAD_FALLBACK_PCT)
        cap_adds = sum(max(Decimal(0), D(p.get("contracted_kw") or 0))
                       for p in store.site_ppas(site["id"]))
        load_adds = sum(max(Decimal(0), D(p.get("committed_kwh_remaining") or 0))
                        for p in store.site_ppas(site["id"]))
    else:
        self_capacity = D(0)
        self_load = D(0)
        pr_capacity = D(1)
        pr_load = min(D(1), annual / max(D(1), site_load))
        cap_adds = D(0)
        load_adds = D(1)
    year_avail = (yr_kwh + cap_adds) / max(D(1), own_yr_days + load_adds)
    prior_avail = (prior_kwh + pr_capacity * cap_adds) / max(D(1), own_pr_days + pr_load * load_adds)
    guarantee = D(ppa.get("guaranteed_availability_pct") or 0)
    if year_avail >= guarantee:
        headroom = min(D(C.AVAILABILITY_HEADROOM_CEILING_PCT), year_avail - guarantee)
    else:
        headroom = D(0)
    availability_ratio = min(D(1), year_avail) + headroom
    potential_ratio = min(D(1), prior_avail)
    return {
        "year_availability_pct": float(year_avail.quantize(Decimal("0.000001"))),
        "prior_availability_pct": float(prior_avail.quantize(Decimal("0.000001"))),
        "availability_ratio": float(availability_ratio.quantize(Decimal("0.000001"))),
        "potential_availability_ratio": float(potential_ratio.quantize(Decimal("0.000001"))),
        "expected_annual_site_kwh": float(r2(site_load * availability_ratio)),
        "expected_annual_site_prior_kwh": float(r2(site_load * potential_ratio)),
    }


def availability_savings(site, period_lines):
    """availability_savings_two_offtakers, evaluated as a four-step chain."""
    billed_kwh = sum(D(ln.get("metered_kwh") or 0) for ln in period_lines)
    commitments = []
    for ppa in store.by_created(store.site_ppas(site["id"])):
        if ppa.get("state") not in ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED"):
            continue
        commitments.append((ppa, max(Decimal(0), D(ppa.get("contracted_kw") or 0))))
    total_commit = sum(c for _, c in commitments)
    if total_commit <= 0:
        split_a = billed_kwh
        split_b = Decimal(0)
    else:
        first = commitments[0][1] if commitments else Decimal(0)
        split_a = billed_kwh * first / total_commit
        split_b = billed_kwh - split_a
    rate = D(C.DEFAULT_RATE_DIFFERENCE_CENTS_PER_KWH)
    base = (split_a + split_b) * rate
    if base >= D(C.RATE_CAP_REFERENCE_CENTS):
        adjustment = D(C.BASE_SAVINGS_REFERENCE_CENTS)
    else:
        adjustment = base / D(C.RATE_CAP_REFERENCE_CENTS) * D(C.BASE_SAVINGS_REFERENCE_CENTS)
    savings = base + adjustment
    if savings > D(C.MAX_SAVINGS_CAP_CENTS):
        savings = D(C.MAX_SAVINGS_CAP_CENTS)
    return r2(savings)


def extension_days(ppa, site):
    """contract_extension_days: only uncorroborated downtime is granted."""
    year = store.clock().year
    measured = Decimal(0)
    found = False
    for line in store.ppa_lines(ppa["id"]):
        if line.get("status") != "SETTLEMENT_APPLIED":
            continue
        if store.parse_dt(line["period_start"]).year != year:
            continue
        found = True
        measured += D(line.get("downtime_hours") or 0)
    allowed = D(site.get("allowed_downtime_hours_per_year") or 0)
    shortfall = max(Decimal(0), allowed - measured)
    if shortfall <= 0:
        return 0
    return min(C.EXTENSION_DAYS_MAX, floor_int(shortfall / D(C.HOURS_PER_DAY)))
