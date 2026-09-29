"""Run cost: four independently rounded components plus the per-case waterfall."""

from decimal import Decimal

from util import round_cents

WATER_RATE_CENTS_PER_GAL = Decimal("0.37")
SANITIZER_RATE_CENTS_PER_PPM_GAL = Decimal("0.0021")
LABOR_RATE_CENTS_PER_CREW_MINUTE = Decimal(58)
ENERGY_RATE_CENTS_PER_SPIN_SECOND_CASE = Decimal("0.014")


def compute(run, closing_topup_ppm, run_minutes):
    gallons = run["water_gal_used"]
    topup = closing_topup_ppm if closing_topup_ppm is not None else Decimal(0)
    water = round_cents(gallons * WATER_RATE_CENTS_PER_GAL)
    sanitizer = round_cents(topup * gallons * SANITIZER_RATE_CENTS_PER_PPM_GAL)
    labour = round_cents(
        Decimal(run_minutes) * Decimal(run["crew_size"]) * LABOR_RATE_CENTS_PER_CREW_MINUTE
    )
    energy = round_cents(
        Decimal(run["spin_seconds"])
        * Decimal(run["cases_produced"])
        * ENERGY_RATE_CENTS_PER_SPIN_SECOND_CASE
    )
    total = water + sanitizer + labour + energy
    cases = run["cases_produced"]
    per_case = total // cases
    remainder = total - per_case * cases
    return {
        "water_cost_cents": water,
        "sanitizer_cost_cents": sanitizer,
        "labor_cost_cents": labour,
        "energy_cost_cents": energy,
        "total_run_cost_cents": total,
        "per_case_cost_cents": per_case,
        "cost_remainder_cents": remainder,
    }


def allocated_for(case_sequence, per_case, remainder):
    if case_sequence <= remainder:
        return per_case + 1
    return per_case
