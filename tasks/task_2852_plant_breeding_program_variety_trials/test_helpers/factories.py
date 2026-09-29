"""
Payload factories for the Plant Breeding Variety Trials API.

Each factory returns the request body for one create/transition endpoint with
sensible PRD-legal defaults, overridable per call. Money and decimal amounts are
emitted as JSON numbers because the PRD declares them as numeric values; the
only string-typed temporal fields are the date-only calendar fields
(`YYYY-MM-DD`) and the clock's full instant (`YYYY-MM-DDTHH:MM:SSZ`).
"""

from typing import Any, Dict, List, Optional

from .types import (
    AnalysisVariant,
    CropCode,
    DecisionType,
    EnvironmentClass,
    NurseryType,
    PlotDesign,
    QcStatus,
    ReviewOutcome,
    TraitCode,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel: pass ``OMIT`` to drop an optional key from a payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Programmes and objectives (PRD 3.1) ──────────────

def program_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Soy North Central",
            "crop_code": CropCode.SOYBEAN,
            "market_zone": "NORTH_CENTRAL",
            "total_plot_budget": 5000,
            "total_budget_usd": 2000000.00,
        },
        overrides,
    )


def objective_payload(**overrides) -> Dict[str, Any]:
    """
    The canonical objective: target 11000.00 kg/ha, RUST and SDS required at a
    minimum score of 6, weights 0.50 / 0.30 / 0.20 summing to exactly 1.00, an
    advancement bar of 85.00 and a minimum generation of 5.
    """
    return _merge(
        {
            "market_segment": "MG2_NORTH",
            "target_yield_kg_per_ha": 11000.00,
            "required_disease_resistances": ["RUST", "SDS"],
            "min_resistance_score": 6,
            "quality_trait_specs": {"PROTEIN_MIN": 13.0, "TEST_WEIGHT_MIN": 76.0},
            "yield_weight": 0.50,
            "disease_weight": 0.30,
            "quality_weight": 0.20,
            "min_advancement_index": 85.00,
            "min_generation_number": 5,
        },
        overrides,
    )


# ─── Breeding lines (PRD 3.2) ─────────────────────────

def line_payload(program_id: str, objective_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "objective_id": objective_id,
            "designation": "SX-1001",
            "generation_number": 6,
            "seed_inventory_g": 500000,
        },
        overrides,
    )


def line_a_payload(program_id: str, objective_id: str, **overrides) -> Dict[str, Any]:
    """Line A: SX-1001, RUST 8 / SDS 7, PROTEIN 13.4 / TEST_WEIGHT 75.0."""
    return _merge(
        {
            "program_id": program_id,
            "objective_id": objective_id,
            "designation": "SX-1001",
            "generation_number": 6,
            "seed_inventory_g": 500000,
            "disease_resistance_scores": {"RUST": 8, "SDS": 7},
            "quality_trait_values": {"PROTEIN": 13.4, "TEST_WEIGHT": 75.0},
        },
        overrides,
    )


def line_b_payload(program_id: str, objective_id: str, **overrides) -> Dict[str, Any]:
    """Line B: SX-1002, RUST 8 / SDS 4, no quality measurements at all."""
    return _merge(
        {
            "program_id": program_id,
            "objective_id": objective_id,
            "designation": "SX-1002",
            "generation_number": 6,
            "seed_inventory_g": 400000,
            "disease_resistance_scores": {"RUST": 8, "SDS": 4},
            "quality_trait_values": {},
        },
        overrides,
    )


def progeny_payload(objective_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "objective_id": objective_id,
            "designation": "PRG-0001",
            "generation_number": 2,
            "female_parent_line_id": None,
            "male_parent_line_id": None,
            "seed_inventory_g": 400,
        },
        overrides,
    )


# ─── Nursery (PRD 3.3) ────────────────────────────────

def nursery_block_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "block_code": "NB-001",
            "nursery_type": NurseryType.WINTER,
            "location_code": "PR_ISABELA",
            "plot_count": 200,
            "fallow_buffer_days": 14,
        },
        overrides,
    )


def crossing_block_payload(program_id: str, nursery_block_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "nursery_block_id": nursery_block_id,
            "season_code": "2026W",
            "planned_cross_count": 4,
        },
        overrides,
    )


def planting_payload(nursery_block_id: str, line_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "nursery_block_id": nursery_block_id,
            "line_id": line_id,
            "sow_date": "2026-10-05",
            "expected_harvest_date": "2027-02-10",
            "plot_count": 50,
        },
        overrides,
    )


def harvest_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"actual_harvest_date": "2027-02-12", "harvested_seed_g": 5000},
        overrides,
    )


# ─── Trial network (PRD 3.5, 3.6) ─────────────────────

def site_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "site_code": "S1",
            "environment_class": EnvironmentClass.HIGH_YIELD_IRRIGATED,
            "total_plot_capacity": 400,
            "plot_cost_usd": 45.00,
            "season_start_date": "2027-03-01",
            "season_end_date": "2027-10-31",
        },
        overrides,
    )


def series_payload(program_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "stage": "STAGE_1",
            "season_year": 2027,
            "plot_design": PlotDesign.RCBD,
            "replication_count": 4,
            "min_locations": 3,
        },
        overrides,
    )


def entry_payload(line_id: str, trial_site_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "line_id": line_id,
            "trial_site_id": trial_site_id,
            "plot_count": 8,
            "planting_window_start": "2027-04-01",
            "planting_window_end": "2027-08-31",
        },
        overrides,
    )


def observation_payload(rep_number: int, value: float, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "trait_code": TraitCode.YIELD_KG_PLOT,
            "rep_number": rep_number,
            "value": value,
        },
        overrides,
    )


def rejected_observation_payload(rep_number: int, value: float, **overrides) -> Dict[str, Any]:
    return observation_payload(
        rep_number, value, qc_status=QcStatus.REJECTED, **overrides
    )


def withdraw_payload(reason: str = "SITE_REALLOCATION", **overrides) -> Dict[str, Any]:
    return _merge({"withdrawal_reason": reason}, overrides)


# ─── Analysis and decisions (PRD 3.7, 3.8) ────────────

def analysis_payload(expected_series_version: int, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "variant": AnalysisVariant.BALANCED_CORE,
            "expected_series_version": expected_series_version,
        },
        overrides,
    )


def decision_payload(
    line_id: str,
    trial_series_id: str,
    expected_line_version: int,
    decision: str = DecisionType.ADVANCE,
    granted_plots: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "line_id": line_id,
            "trial_series_id": trial_series_id,
            "decision": decision,
            "granted_plots": granted_plots,
            "expected_line_version": expected_line_version,
        },
        overrides,
    )


# ─── Stewardship and seed increase (PRD 3.9) ──────────

def agreement_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "approved_markets": ["US_CORNBELT"],
            "regulatory_dossier_ref": "DOS-2852-01",
            "grower_agreement_ref": "GA-2852-01",
            "effective_from": "2026-09-01",
            "effective_to": "2029-09-01",
        },
        overrides,
    )


def review_payload(outcome: str = ReviewOutcome.APPROVE, **overrides) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


def request_changes_payload(requested_changes: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "outcome": ReviewOutcome.REQUEST_CHANGES,
            "requested_changes": requested_changes,
        },
        overrides,
    )


def suspend_payload(reason: str, **overrides) -> Dict[str, Any]:
    return _merge({"suspension_reason": reason}, overrides)


def lot_payload(
    line_id: str,
    target_market: str,
    allocations: List[Dict[str, Any]],
    launch_year: int = 2028,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "line_id": line_id,
            "target_market": target_market,
            "market_allocations": allocations,
            "launch_year": launch_year,
        },
        overrides,
    )


def allocation(market_code: str, demand_kg: float) -> Dict[str, Any]:
    """One entry of `market_allocations`; `demand_kg` must be greater than zero."""
    return {"market_code": market_code, "demand_kg": demand_kg}


# ─── Backcross (PRD 3.4) ──────────────────────────────

def backcross_payload(
    recurrent_line_id: str, donor_line_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "recurrent_line_id": recurrent_line_id,
            "donor_line_id": donor_line_id,
            "target_trait_code": "SDS",
            "marker_assisted": True,
        },
        overrides,
    )


def marker_cycle_payload(target_marker_present: bool, **overrides) -> Dict[str, Any]:
    return _merge({"target_marker_present": target_marker_present}, overrides)
