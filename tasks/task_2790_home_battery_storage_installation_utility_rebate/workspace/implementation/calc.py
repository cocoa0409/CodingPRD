"""The seven normative calculations of the domain (PRD 2.11, 3.2, 3.6, 3.7, 3.9)."""

from decimal import Decimal

import store
from common import (
    BASE_MULTIPLIER_BP,
    BONUS_HIGH_BP,
    BONUS_MID_BP,
    BONUS_TIER_HIGH_RATIO,
    BONUS_TIER_MID_RATIO,
    BP_DIVISOR,
    CAPACITY_PASS_FRACTION,
    CLAIM_DEAD_STATUSES,
    EMERGENCY_MULTIPLIER_BP,
    ESSENTIAL_REMAINDER_FACTOR,
    ESSENTIAL_TOP_N,
    EXPORT_MULTIPLIER_BP,
    GENERAL_FIRST_VA,
    GENERAL_REMAINDER_FACTOR,
    LIGHTING_VA_PER_SQFT,
    MAX_ANTI_ISLANDING_MS,
    MAX_TRANSITION_MS,
    MEASURED_METHOD_HEADROOM,
    MODEL_CATALOG,
    MOTOR_SURGE_MULTIPLIER,
    PENALTY_FACTOR,
    SHORTFALL_RATIO_FLOOR,
    SURGE_HEADROOM_FACTOR,
    WHOLE_HOME_SURGE_FACTOR,
    cents,
    dec,
    exact_hours,
    floor_cents,
    kw,
    ratio4,
    version_ge,
)

ZERO = Decimal(0)


# --------------------------------------------------------------------------- #
# calculations.load_sizing
# --------------------------------------------------------------------------- #

def load_sizing(calc):
    """Compute connected / continuous / surge kW from the calculation's own inputs."""
    if calc["method"] == "NEC_220_87_MEASURED":
        connected = kw(dec(calc["measured_peak_kw"]) * MEASURED_METHOD_HEADROOM)
    else:
        lighting_va = dec(calc["lighting_area_sqft"]) * LIGHTING_VA_PER_SQFT
        other_load = lighting_va + dec(calc["appliance_load_va"])
        if other_load > GENERAL_FIRST_VA:
            general = GENERAL_FIRST_VA + (
                other_load - GENERAL_FIRST_VA
            ) * GENERAL_REMAINDER_FACTOR
        else:
            general = other_load
        hvac = max(dec(calc["heating_va"]), dec(calc["cooling_va"]))
        connected = kw((general + hvac) / Decimal(1000))

    if calc["backup_scope"] == "WHOLE_HOME":
        required_continuous = connected
        required_surge = kw(connected * WHOLE_HOME_SURGE_FACTOR)
    else:
        circuits = calc.get("essential_circuits") or []
        ranked = sorted(
            enumerate(circuits), key=lambda pair: (-dec(pair[1]["load_kw"]), pair[0])
        )
        top_total = sum(
            (dec(item[1]["load_kw"]) for item in ranked[:ESSENTIAL_TOP_N]), ZERO
        )
        remainder_total = sum(
            (dec(item[1]["load_kw"]) for item in ranked[ESSENTIAL_TOP_N:]), ZERO
        )
        continuous_raw = top_total + remainder_total * ESSENTIAL_REMAINDER_FACTOR
        if continuous_raw > connected:
            continuous_raw = dec(connected)
        required_continuous = kw(continuous_raw)
        motor_candidates = [
            dec(circuit["load_kw"]) * MOTOR_SURGE_MULTIPLIER
            for circuit in circuits
            if circuit.get("has_motor")
        ]
        motor_surge = max(motor_candidates) if motor_candidates else ZERO
        required_surge = kw(motor_surge + required_continuous * SURGE_HEADROOM_FACTOR)

    calc["connected_load_kw"] = connected
    calc["required_continuous_kw"] = required_continuous
    calc["required_surge_kw"] = required_surge
    return calc


# --------------------------------------------------------------------------- #
# Model catalog derivations (PRD 2.11)
# --------------------------------------------------------------------------- #

def bank_capacity(model_code, unit_count):
    spec = MODEL_CATALOG[model_code]
    usable = kw(spec["usable_kwh_per_unit"] * dec(unit_count))
    continuous = kw(spec["continuous_kw_per_unit"] * dec(unit_count))
    return usable, continuous


# --------------------------------------------------------------------------- #
# calculations.rebate_award  (+ stacking waterfall)
# --------------------------------------------------------------------------- #

def effective_hold(claim):
    if claim.get("final_amount_cents") is not None:
        return int(claim["final_amount_cents"])
    if claim.get("reserved_amount_cents") is not None:
        return int(claim["reserved_amount_cents"])
    return 0


def live_claims(system_id, exclude_claim_id=None):
    result = []
    for claim in store.rows("claims"):
        if claim["battery_system_id"] != system_id:
            continue
        if claim["status"] in CLAIM_DEAD_STATUSES:
            continue
        if exclude_claim_id is not None and claim["id"] == exclude_claim_id:
            continue
        result.append(claim)
    return result


def _stack_order_key(claim):
    program = store.get("programs", claim["program_id"])
    priority = program["stack_priority"] if program else 0
    return (priority, claim["created_at"], claim["_seq"])


def stacking(system, program, exclude_claim_id=None):
    """Return (stack_ceiling_cents, committed_cents, headroom_cents)."""
    siblings = live_claims(system["id"], exclude_claim_id)
    programs = [program]
    for claim in siblings:
        sibling_program = store.get("programs", claim["program_id"])
        if sibling_program is not None:
            programs.append(sibling_program)
    tightest_bp = min(dec(item["max_stack_pct_of_cost_bp"]) for item in programs)
    ceiling = floor_cents(
        tightest_bp * dec(system["installed_cost_cents"]) / BP_DIVISOR
    )
    committed = 0
    for claim in sorted(siblings, key=_stack_order_key):
        committed += effective_hold(claim)
    headroom = ceiling - committed
    if headroom < 0:
        headroom = 0
    return ceiling, committed, headroom


def scheduled_award(program, export_commitment, basis_kwh):
    """Steps 1 to 4: two-tier schedule, export multiplier, per-project cap."""
    basis = dec(basis_kwh)
    tier1_limit = dec(program["tier1_limit_kwh"])
    tier1_energy = basis if basis < tier1_limit else tier1_limit
    tier2_energy = basis - tier1_limit
    if tier2_energy < 0:
        tier2_energy = ZERO
    raw = tier1_energy * dec(program["tier1_rate_cents_per_kwh"]) + tier2_energy * dec(
        program["tier2_rate_cents_per_kwh"]
    )
    amount = cents(raw * EXPORT_MULTIPLIER_BP[export_commitment] / BP_DIVISOR)
    cap = int(program["per_project_cap_cents"])
    return amount if amount < cap else cap


def rebate_award(system, program, export_commitment, basis_kwh, exclude_claim_id=None):
    """Full six-step award. Returns (amount, ceiling, headroom)."""
    ceiling, _committed, headroom = stacking(system, program, exclude_claim_id)
    amount = scheduled_award(program, export_commitment, basis_kwh)
    if amount > headroom:
        amount = headroom
    return amount, ceiling, headroom


def reserved_basis(system):
    return dec(system["usable_kwh"])


def final_basis(system):
    design = dec(system["usable_kwh"])
    verified = system.get("verified_capacity_kwh")
    if verified is None:
        return design
    verified = dec(verified)
    return verified if verified < design else design


# --------------------------------------------------------------------------- #
# calculations.commissioning_verdict
# --------------------------------------------------------------------------- #

def commissioning_verdict(test, system):
    kind = test["test_type"]
    if kind == "BACKUP_TRANSITION":
        return "PASS" if dec(test["transition_ms"]) <= MAX_TRANSITION_MS else "FAIL"
    if kind == "ANTI_ISLANDING":
        return (
            "PASS"
            if dec(test["anti_islanding_trip_ms"]) <= MAX_ANTI_ISLANDING_MS
            else "FAIL"
        )
    if kind == "CAPACITY_DISCHARGE":
        threshold = dec(system["usable_kwh"]) * CAPACITY_PASS_FRACTION
        return "PASS" if dec(test["delivered_kwh"]) >= threshold else "FAIL"
    minimum = MODEL_CATALOG[system["model_code"]]["min_firmware"]
    return "PASS" if version_ge(test["reported_firmware_version"], minimum) else "FAIL"


# --------------------------------------------------------------------------- #
# calculations.byod_settlement
# --------------------------------------------------------------------------- #

def delivery_figures(event, performance, delivered_kwh):
    hours = exact_hours(event["window_start"], event["window_end"])
    pledged = dec(performance["pledged_kw_snapshot"])
    avg = kw(dec(delivered_kwh) / hours)
    credited = avg if avg < pledged else pledged
    ratio = ratio4(avg / pledged) if pledged > 0 else ratio4(ZERO)
    return avg, kw(credited), ratio


def settlement_money(event, performance, enrollment):
    """Steps 1 to 6 for one participation; mutates nothing, returns the figures."""
    rate = dec(event["payment_rate_cents_per_kw"])
    multiplier = (
        EMERGENCY_MULTIPLIER_BP
        if event["event_type"] == "EMERGENCY"
        else BASE_MULTIPLIER_BP
    )
    credited = dec(performance["credited_kw"])
    gross = cents(credited * rate * multiplier / BP_DIVISOR)

    ratio = dec(performance["performance_ratio"])
    if ratio < SHORTFALL_RATIO_FLOOR:
        pledged = dec(performance["pledged_kw_snapshot"])
        shortfall_kw = pledged * SHORTFALL_RATIO_FLOOR - dec(
            performance["avg_delivered_kw"]
        )
        penalty = cents(shortfall_kw * rate * PENALTY_FACTOR)
        if penalty < 0:
            penalty = 0
    else:
        penalty = 0

    cumulative_credited = kw(dec(enrollment["cumulative_credited_kw"]) + credited)
    cumulative_pledged = kw(
        dec(enrollment["cumulative_pledged_kw"]) + dec(performance["pledged_kw_snapshot"])
    )
    if cumulative_pledged > 0:
        season_ratio = ratio4(cumulative_credited / cumulative_pledged)
    else:
        season_ratio = ratio4(ZERO)

    if season_ratio >= BONUS_TIER_HIGH_RATIO:
        bonus_bp = BONUS_HIGH_BP
    elif season_ratio >= BONUS_TIER_MID_RATIO:
        bonus_bp = BONUS_MID_BP
    else:
        bonus_bp = ZERO
    bonus = cents(dec(gross) * bonus_bp / BP_DIVISOR)

    net = gross - penalty + bonus
    if net < 0:
        net = 0
    return {
        "gross_payment_cents": gross,
        "shortfall_penalty_cents": penalty,
        "bonus_cents": bonus,
        "net_payment_cents": net,
        "cumulative_credited_kw": cumulative_credited,
        "cumulative_pledged_kw": cumulative_pledged,
        "season_compliance_ratio": season_ratio,
    }
