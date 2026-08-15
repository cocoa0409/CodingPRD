"""Calculation rules (SCAFFOLD calculations table; PRD §2.9 rounding conventions).

All computed quantities round half-up via Decimal; retained precision varies per
quantity. Input fields keep client-supplied precision; rounding applies to
computed fields only.
"""
from decimal import ROUND_HALF_UP, Decimal

PL_RANK = {"PLc": 1, "PLd": 2, "PLe": 3}

MIN_PAYLOAD_MARGIN_PCT = Decimal("20.0")
PLE_THRESHOLD = Decimal("9.0")
PLD_THRESHOLD = Decimal("6.0")
BUDGET_FULL_POINTS = Decimal("10.0")


def d(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu(x, places):
    """Round half-up to `places` decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return d(x).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_float(x, places):
    return float(rhu(x, places))


def rhu_int(x):
    return int(rhu(x, 0))


# --- adjusted_cycle_time (ApplicationStudy submit) ---
def adjusted_cycle_time(sim_cycle_time_s, sim_confidence_pct):
    return rhu_float(d(sim_cycle_time_s) / (d(sim_confidence_pct) / Decimal(100)), 3)


def feasibility(adjusted_cycle_time_s, contracted_cycle_time_s):
    a = d(adjusted_cycle_time_s)
    c = d(contracted_cycle_time_s)
    if a <= c:
        return "FEASIBLE"
    if a <= c * Decimal("1.10"):
        return "MARGINAL"
    return "INFEASIBLE"


# --- payload_margin_check (RobotSelection validate) ---
def payload_margin_pct(rated_payload_kg, end_effector_weight_kg, part_weight_kg):
    total_load = d(end_effector_weight_kg) + d(part_weight_kg)
    return rhu(Decimal(100) * (d(rated_payload_kg) - total_load) / d(rated_payload_kg), 2)


# --- retention_release_schedule ---
def retention_total_cents(contract_value_cents, retention_rate_bps):
    return rhu_int(d(contract_value_cents) * d(retention_rate_bps) / Decimal(10000))


def milestone_amounts(total_retention_cents):
    """Pinned waterfall: total -> fat -> sat -> guarantee (residual absorbs rounding)."""
    fat = rhu_int(d(total_retention_cents) * Decimal(30) / Decimal(100))
    sat = rhu_int(d(total_retention_cents) * Decimal(40) / Decimal(100))
    guarantee = total_retention_cents - fat - sat
    return fat, sat, guarantee


def conditional_half(milestone_amount_cents):
    return rhu_int(d(milestone_amount_cents) * Decimal("0.5"))


# --- training_completion_score ---
def training_completion(audience, practical_score_pct, written_score_pct):
    if audience == "OPERATOR":
        score = Decimal("0.6") * d(practical_score_pct) + Decimal("0.4") * d(written_score_pct)
    else:  # TECHNICIAN
        score = Decimal("0.5") * d(practical_score_pct) + Decimal("0.5") * d(written_score_pct)
    return rhu_float(score, 1)


# --- spare_parts_consumption_forecast ---
def spare_forecast(recommended_coverage_months, shift_windows_per_day):
    """forecast = units / (eff_daily_burn * 30) where
    eff_daily_burn = (units / (months*30)) * (shifts/2). The catalog unit count
    cancels algebraically, giving months*2/shifts exactly (round half-up, 1 dp).
    """
    return rhu_float(d(recommended_coverage_months) * Decimal(2) / d(shift_windows_per_day), 1)


# --- safety_function_budget (SafetyRiskAssessment submit) ---
def safety_budget(fencing_length_m, light_curtain_zones, muting_required):
    fencing_points = min(d(fencing_length_m) / Decimal("10.0"), Decimal("5.0"))
    curtain_points = d(light_curtain_zones) * Decimal("1.5")
    muting_penalty = Decimal("2.0") if muting_required else Decimal("0.0")
    raw = fencing_points + curtain_points - muting_penalty
    budget_pct = rhu_float(Decimal(100) * raw / BUDGET_FULL_POINTS, 1)
    if raw >= PLE_THRESHOLD:
        pl = "PLe"
    elif raw >= PLD_THRESHOLD:
        pl = "PLd"
    else:
        pl = "PLc"
    return budget_pct, pl


# --- throughput_shortfall (ThroughputGuarantee close MISSED) ---
def throughput_shortfall(observed_cycle_time_s, contracted_cycle_time_s,
                         observed_uptime_pct, guaranteed_oee_pct):
    cycle_sf = max(
        Decimal(0),
        Decimal(100) * (d(observed_cycle_time_s) - d(contracted_cycle_time_s)) / d(contracted_cycle_time_s),
    )
    uptime_sf = max(Decimal(0), d(guaranteed_oee_pct) - d(observed_uptime_pct))
    return rhu_float(max(cycle_sf, uptime_sf), 2)


def guarantee_penalty_cents(retention_balance_cents, contract_value_cents, shortfall_pct):
    return min(
        retention_balance_cents,
        rhu_int(d(contract_value_cents) * d(shortfall_pct) / Decimal(100)),
    )


# --- MaintenancePlan hours_until_due ---
def hours_until_due(first_due_at_hours, interval_operating_hours, current_operating_hours):
    """Smallest non-negative first_due + k*interval - current over integer k >= 0."""
    if first_due_at_hours >= current_operating_hours:
        return first_due_at_hours - current_operating_hours
    k = -(-(current_operating_hours - first_due_at_hours) // interval_operating_hours)
    return first_due_at_hours + k * interval_operating_hours - current_operating_hours
