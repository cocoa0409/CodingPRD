"""Calculation services: sizing validation, degradation projection, LD, tests,
warranty credit, spare parts pool, dispatch optimization."""

import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store
from util import round2, round4, to_number

DEGRADATION = {
    "ENERGY_ARBITRAGE": {"ONE_CYCLE_DAILY": Decimal("0.0006"), "TWO_CYCLES_DAILY": Decimal("0.0012"), "CONTINUOUS": Decimal("0.0015")},
    "FREQUENCY_REGULATION": {"ONE_CYCLE_DAILY": Decimal("0.0004"), "TWO_CYCLES_DAILY": Decimal("0.0008"), "CONTINUOUS": Decimal("0.0010")},
    "CAPACITY_FIRMING": {"ONE_CYCLE_DAILY": Decimal("0.0005"), "TWO_CYCLES_DAILY": Decimal("0.0010"), "CONTINUOUS": Decimal("0.0012")},
}

AUGMENTATION_PENALTY = Decimal("0.005")
AUGMENTATION_CAPACITY_FLOOR_MWH = Decimal("80")
SPARE_PARTS_POOL_PCT = Decimal("0.30")

MIN_FIRMING_DURATION_HOURS = Decimal("4.00")
MIN_ARBITRAGE_DURATION_HOURS = Decimal("2.00")


def compute_sizing(project):
    """Compute duration_hours and sizing_status per sizing_validation."""
    rated_energy = Decimal(str(project["rated_energy_mwh"]))
    rated_power = Decimal(str(project["rated_power_mw"]))
    duration = round2(rated_energy / rated_power)
    market = project["market_application"]
    duty = project["duty_cycle_profile"]
    if market == "CAPACITY_FIRMING":
        status = "VALID" if (duration >= MIN_FIRMING_DURATION_HOURS and duty == "ONE_CYCLE_DAILY") else "INVALID"
    elif market == "FREQUENCY_REGULATION":
        status = "VALID" if duty == "CONTINUOUS" else "INVALID"
    else:  # ENERGY_ARBITRAGE
        status = "VALID" if (duration >= MIN_ARBITRAGE_DURATION_HOURS and duty != "CONTINUOUS") else "INVALID"
    project["duration_hours"] = to_number(duration)
    project["sizing_status"] = status


def executed_augmentations(project_id):
    return [a for a in store.augmentations.values()
            if a["project_id"] == project_id and a["status"] == "EXECUTED"]


def count_planned_or_executed(project_id):
    return sum(1 for a in store.augmentations.values()
               if a["project_id"] == project_id and a["status"] in ("PLANNED", "EXECUTED"))


def recompute_projection(project):
    """augmentation_requirement: forward-looking capacity projection."""
    commissioned = Decimal(str(project.get("commissioned_capacity_mwh", 0)))
    exec_events = executed_augmentations(project["id"])
    added = sum(Decimal(str(e["added_capacity_mwh"])) for e in exec_events)
    d = DEGRADATION[project["market_application"]][project["duty_cycle_profile"]]
    cycles = Decimal(str(project.get("equivalent_cycles", 0)))
    projected_before = commissioned + added - d * cycles
    excess = max(Decimal("0"), projected_before - AUGMENTATION_CAPACITY_FLOOR_MWH)
    penalty = Decimal(len(exec_events)) * AUGMENTATION_PENALTY * excess
    projected = projected_before - penalty
    project["projected_capacity_mwh"] = to_number(round2(projected))


def recompute_augmentation_count(project):
    project["augmentation_count"] = count_planned_or_executed(project["id"])


def compute_ld(esa, milestone, days_late):
    """liquidated_damages calc: returns ld_applied_cents for this milestone."""
    rate = esa["ld_rate_per_day_cents"]
    if rate <= 0 or days_late <= 0:
        return 0
    headroom = esa["ld_cap_cents"] - esa["accrued_ld_cents"]
    if headroom <= 0:
        return 0
    effective_days = min(days_late, headroom // rate)
    return effective_days * rate


def active_esa_for_project(project_id):
    """The project's ESA in EXECUTED or COMPLETED status (if any)."""
    for esa in store.esas.values():
        if esa["project_id"] == project_id and esa["status"] in ("EXECUTED", "COMPLETED"):
            return esa
    return None


def measurement_basis_for(project):
    return "NAMEPLATE" if project["market_application"] == "FREQUENCY_REGULATION" else "POI"


def evaluate_capacity_test(test, project, esa, measured, aux):
    basis = test["measurement_basis"]
    measured_d = Decimal(str(measured))
    aux_d = Decimal(str(aux)) if basis == "POI" else Decimal("0")
    evaluated = round2(measured_d - aux_d)
    test["evaluated_capacity_mwh"] = to_number(evaluated)
    result = "PASS" if evaluated >= Decimal(str(esa["guaranteed_capacity_mwh"])) else "FAIL"
    test["result"] = result
    return result, evaluated


def evaluate_rte_test(test, esa, intervals):
    charge = sum(Decimal(str(i["charge_mwh"])) for i in intervals)
    discharge = sum(Decimal(str(i["discharge_mwh"])) for i in intervals)
    rte = round4(discharge / charge)
    test["measured_rte_pct"] = to_number(rte)
    result = "PASS" if rte >= Decimal(str(esa["guaranteed_rte_pct"])) else "FAIL"
    test["result"] = result
    return result


def auto_augmentation_added_capacity(esa, projected, evaluated):
    """shortfall grossed up by 1/(1-penalty), ceil at 0.01 MWh granularity."""
    shortfall = Decimal(str(esa["guaranteed_capacity_mwh"])) - min(
        Decimal(str(projected)), Decimal(str(evaluated)))
    if shortfall < 0:
        shortfall = Decimal("0")
    grossed = shortfall / (Decimal("1") - AUGMENTATION_PENALTY)
    return Decimal(math.ceil(grossed * 100)) / 100


def warranty_credit_amount(claim, esa, variant, throughput_mwh):
    from decimal import Decimal as D
    loss = D(str(claim["claimed_capacity_loss_mwh"]))
    p = D(str(esa["price_per_mwh_cents"]))
    if variant == "STRAIGHT_LINE":
        exact = loss * p
        # ceil to next whole cent
        return int(math.ceil(exact))
    else:  # OUTPUT_BASED
        rte = D(str(esa["guaranteed_rte_pct"]))
        throughput = D(str(throughput_mwh))
        degradation = D("1") - rte
        exact = loss * throughput * rte * p * degradation
        return int(exact.quantize(D("1"), rounding=ROUND_HALF_UP))


def compute_credit_pool(annual_fee_cents):
    exact = Decimal(str(annual_fee_cents)) * SPARE_PARTS_POOL_PCT
    return int(exact.to_integral_value(rounding=ROUND_FLOOR))
