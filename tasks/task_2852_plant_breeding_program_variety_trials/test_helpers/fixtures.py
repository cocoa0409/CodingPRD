"""
Composite setup helpers.

Every helper drives the API through its declared endpoints only — no test ever
reaches behind the HTTP surface to plant state — so a suite run with a fresh
server per test can rebuild any scenario it needs from scratch.

The vocabulary is the one both design walks share: a programme with a 5000-plot
and 2000000.00 USD budget, one objective targeting 11000.00 kg/ha with weights
0.50 / 0.30 / 0.20 and an advancement bar of 85.00, line A (SX-1001, full trait
maps) and line B (SX-1002, no quality measurements), and trial sites whose
season runs 2027-03-01 to 2027-10-31.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    AGRONOMIST_HEADERS,
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_APPROVER_HEADERS,
    REGULATORY_HEADERS,
    SCIENTIST_HEADERS,
)
from .types import AnalysisVariant, DecisionType


# ─── Tier 1: single-entity creation ───────────────────

def create_program(api: ApiClient, headers=DIRECTOR_HEADERS, **overrides) -> Dict[str, Any]:
    """Register a programme and return its record."""
    return get_success_data(
        api.create_program(f.program_payload(**overrides), headers), 201
    )


def create_objective(
    api: ApiClient, program_id: str, headers=DIRECTOR_HEADERS, **overrides
) -> Dict[str, Any]:
    """Define an objective under a programme and return its record."""
    return get_success_data(
        api.create_objective(program_id, f.objective_payload(**overrides), headers), 201
    )


def create_line(
    api: ApiClient,
    program_id: str,
    objective_id: str,
    headers=SCIENTIST_HEADERS,
    **overrides,
) -> Dict[str, Any]:
    """Directly register a breeding line and return its record."""
    return get_success_data(
        api.create_line(f.line_payload(program_id, objective_id, **overrides), headers),
        201,
    )


def create_line_a(api: ApiClient, program_id: str, objective_id: str, **overrides):
    return get_success_data(
        api.create_line(
            f.line_a_payload(program_id, objective_id, **overrides), SCIENTIST_HEADERS
        ),
        201,
    )


def create_line_b(api: ApiClient, program_id: str, objective_id: str, **overrides):
    return get_success_data(
        api.create_line(
            f.line_b_payload(program_id, objective_id, **overrides), SCIENTIST_HEADERS
        ),
        201,
    )


def create_site(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_site(f.site_payload(**overrides), AGRONOMIST_HEADERS), 201
    )


def create_series(api: ApiClient, program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_series(f.series_payload(program_id, **overrides), AGRONOMIST_HEADERS),
        201,
    )


def create_entry(
    api: ApiClient, series_id: str, line_id: str, site_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_entry(
            series_id, f.entry_payload(line_id, site_id, **overrides), AGRONOMIST_HEADERS
        ),
        201,
    )


def create_nursery_block(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_nursery_block(f.nursery_block_payload(**overrides), SCIENTIST_HEADERS),
        201,
    )


def create_crossing_block(
    api: ApiClient, program_id: str, nursery_block_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_crossing_block(
            f.crossing_block_payload(program_id, nursery_block_id, **overrides),
            SCIENTIST_HEADERS,
        ),
        201,
    )


def create_planting(
    api: ApiClient, block_id: str, line_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_planting(
            f.planting_payload(block_id, line_id, **overrides), SCIENTIST_HEADERS
        ),
        201,
    )


# ─── Tier 2: the programme/objective/line hierarchy ───

def program_with_objective(
    api: ApiClient, program_overrides: Optional[Dict[str, Any]] = None,
    objective_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Return (program_id, objective_id) for the canonical pair."""
    program = create_program(api, **(program_overrides or {}))
    objective = create_objective(api, program["id"], **(objective_overrides or {}))
    return program["id"], objective["id"]


def program_objective_and_two_lines(
    api: ApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    objective_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """
    Programme + objective + line A (SX-1001) + line B (SX-1002).

    Line A carries RUST 8 / SDS 7 and PROTEIN 13.4 / TEST_WEIGHT 75.0; line B
    carries RUST 8 / SDS 4 and an empty quality map, so B's quality component is
    MISSING for every index calculation.
    """
    program_id, objective_id = program_with_objective(
        api, program_overrides, objective_overrides
    )
    line_a = create_line_a(api, program_id, objective_id)
    line_b = create_line_b(api, program_id, objective_id)
    return SimpleNamespace(
        program_id=program_id,
        objective_id=objective_id,
        line_a_id=line_a["id"],
        line_b_id=line_b["id"],
    )


# ─── Tier 3: lifecycle shortcuts ──────────────────────

def record_yield_reps(
    api: ApiClient,
    entry_id: str,
    values: Sequence[float],
    rejected: Optional[Dict[int, float]] = None,
) -> None:
    """
    Record `YIELD_KG_PLOT` observations for replications 1..len(values), then any
    additional REJECTED replications given as {rep_number: value}.
    """
    for index, value in enumerate(values, start=1):
        get_success_data(
            api.create_observation(
                entry_id, f.observation_payload(index, value), AGRONOMIST_HEADERS
            ),
            201,
        )
    for rep_number, value in (rejected or {}).items():
        get_success_data(
            api.create_observation(
                entry_id,
                f.rejected_observation_payload(rep_number, value),
                AGRONOMIST_HEADERS,
            ),
            201,
        )


def finalize_entry(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.finalize_entry(entry_id, AGRONOMIST_HEADERS), 200)


def plant_series(api: ApiClient, series_id: str) -> Dict[str, Any]:
    return get_success_data(api.plant_series(series_id, AGRONOMIST_HEADERS), 200)


def run_analysis(
    api: ApiClient, series_id: str, variant: str = AnalysisVariant.BALANCED_CORE
) -> Dict[str, Any]:
    """Run one analysis at the series' current version and return its record."""
    version = api.series_version(series_id, ANALYST_HEADERS)
    return get_success_data(
        api.create_analysis(series_id, f.analysis_payload(version, variant=variant), ANALYST_HEADERS),
        201,
    )


def record_decision(
    api: ApiClient,
    line_id: str,
    series_id: str,
    decision: str = DecisionType.ADVANCE,
    granted_plots: int = 0,
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a stage-gate decision at the line's current version."""
    version = api.line_version(line_id, DIRECTOR_HEADERS)
    payload = f.decision_payload(
        line_id, series_id, version, decision=decision, granted_plots=granted_plots
    )
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api.create_decision(payload, DIRECTOR_HEADERS), 201)


def approved_agreement(
    api: ApiClient,
    line_id: str,
    markets: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    Take a stewardship agreement all the way to APPROVED.

    The drafter/submitter (ro-1) and the approver (ro-2) are deliberately
    distinct identities: PRD 3.9's segregation-of-duties rule compares the
    suspending `X-User-ID` against the recorded `approved_by_user_id`, so a
    later suspension by anyone other than ro-2 must be legal.
    """
    payload = f.agreement_payload(**overrides)
    if markets is not None:
        payload["approved_markets"] = markets
    agreement = get_success_data(
        api.create_agreement(line_id, payload, REGULATORY_HEADERS), 201
    )
    get_success_data(api.submit_agreement(agreement["id"], REGULATORY_HEADERS), 200)
    return get_success_data(
        api.review_agreement(
            agreement["id"], f.review_payload(), REGULATORY_APPROVER_HEADERS
        ),
        200,
    )


def reserve_lot(
    api: ApiClient,
    line_id: str,
    target_market: str,
    allocations: List[Dict[str, Any]],
    launch_year: int = 2028,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_lot(
            f.lot_payload(line_id, target_market, allocations, launch_year),
            PLANNER_HEADERS,
        ),
        201,
    )


# ─── Tier 4: accumulation / threshold targeting ───────

def single_site_data_complete(
    api: ApiClient,
    plot_count: int = 8,
    replication_count: int = 4,
    site_overrides: Optional[Dict[str, Any]] = None,
    objective_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """
    One site, one STAGE_1 series with `min_locations` 1, entries A and B, both
    observed and finalised so the series has bubbled to DATA_COMPLETE.

    The observation values are chosen so the rollup lands on pinned figures:
    entry A holds three accepted reps of 14.0 / 15.5 / 15.5 plus a REJECTED
    fourth rep of 20.0, giving a plot mean of 15.000 and 12000.00 kg/ha; entry B
    holds four accepted reps of 13.0 / 14.0 / 14.0 / 15.0, giving 14.000 and
    11200.00 kg/ha.
    """
    base = program_objective_and_two_lines(
        api, program_overrides, objective_overrides
    )
    site = create_site(api, **(site_overrides or {"site_code": "S1"}))
    series = create_series(
        api,
        base.program_id,
        replication_count=replication_count,
        min_locations=1,
    )
    entry_a = create_entry(
        api, series["id"], base.line_a_id, site["id"], plot_count=plot_count
    )
    entry_b = create_entry(
        api, series["id"], base.line_b_id, site["id"], plot_count=plot_count
    )
    plant_series(api, series["id"])
    record_yield_reps(api, entry_a["id"], [14.0, 15.5, 15.5], rejected={4: 20.0})
    record_yield_reps(api, entry_b["id"], [13.0, 14.0, 14.0, 15.0])
    finalize_entry(api, entry_a["id"])
    finalize_entry(api, entry_b["id"])
    return SimpleNamespace(
        program_id=base.program_id,
        objective_id=base.objective_id,
        line_a_id=base.line_a_id,
        line_b_id=base.line_b_id,
        site_id=site["id"],
        series_id=series["id"],
        entry_a_id=entry_a["id"],
        entry_b_id=entry_b["id"],
    )


def single_site_analyzed(
    api: ApiClient,
    variant: str = AnalysisVariant.BALANCED_CORE,
    **kwargs,
) -> SimpleNamespace:
    """`single_site_data_complete` plus one published analysis, so the series is ANALYZED."""
    network = single_site_data_complete(api, **kwargs)
    analysis = run_analysis(api, network.series_id, variant)
    network.analysis_id = analysis["id"]
    return network


def three_site_data_complete(
    api: ApiClient,
    objective_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """
    The full multi-location network: three sites, one STAGE_1 series with
    `replication_count` 4 and `min_locations` 3, five entries of 8 plots each —
    line A at S1, S2 and S3 and line B at S1 and S2 only — every entry observed
    and finalised so the series is DATA_COMPLETE.

    The replication pattern is deliberately unbalanced: entry A@S1 carries three
    accepted reps and a REJECTED fourth, so its rep weight is 3 while every
    other entry weighs 4. The per-entry hectare yields are 12000.00 (A@S1),
    10000.00 (A@S2), 7200.00 (A@S3), 11200.00 (B@S1) and 8800.00 (B@S2).
    """
    base = program_objective_and_two_lines(api, None, objective_overrides)
    site1 = create_site(api, site_code="S1")
    site2 = create_site(api, site_code="S2", environment_class="RAINFED_TEMPERATE")
    site3 = create_site(api, site_code="S3", environment_class="DROUGHT_STRESS")
    series = create_series(
        api, base.program_id, replication_count=4, min_locations=3
    )
    entry_a1 = create_entry(api, series["id"], base.line_a_id, site1["id"])
    entry_a2 = create_entry(api, series["id"], base.line_a_id, site2["id"])
    entry_a3 = create_entry(api, series["id"], base.line_a_id, site3["id"])
    entry_b1 = create_entry(api, series["id"], base.line_b_id, site1["id"])
    entry_b2 = create_entry(api, series["id"], base.line_b_id, site2["id"])
    plant_series(api, series["id"])
    # 12000.00 kg/ha from a 15.000 plot mean over three accepted reps.
    record_yield_reps(api, entry_a1["id"], [15.0, 15.0, 15.0], rejected={4: 20.0})
    # 10000.00 kg/ha from a 12.500 plot mean over four accepted reps.
    record_yield_reps(api, entry_a2["id"], [12.5, 12.5, 12.5, 12.5])
    # 7200.00 kg/ha from a 9.000 plot mean over four accepted reps.
    record_yield_reps(api, entry_a3["id"], [9.0, 9.0, 9.0, 9.0])
    # 11200.00 kg/ha from a 14.000 plot mean over four accepted reps.
    record_yield_reps(api, entry_b1["id"], [14.0, 14.0, 14.0, 14.0])
    # 8800.00 kg/ha from an 11.000 plot mean over four accepted reps.
    record_yield_reps(api, entry_b2["id"], [11.0, 11.0, 11.0, 11.0])
    for entry_id in (
        entry_a1["id"], entry_a2["id"], entry_a3["id"], entry_b1["id"], entry_b2["id"]
    ):
        finalize_entry(api, entry_id)
    return SimpleNamespace(
        program_id=base.program_id,
        objective_id=base.objective_id,
        line_a_id=base.line_a_id,
        line_b_id=base.line_b_id,
        site1_id=site1["id"],
        site2_id=site2["id"],
        site3_id=site3["id"],
        series_id=series["id"],
        entry_a1_id=entry_a1["id"],
        entry_a2_id=entry_a2["id"],
        entry_a3_id=entry_a3["id"],
        entry_b1_id=entry_b1["id"],
        entry_b2_id=entry_b2["id"],
    )


# ─── Tier 5: finalisation / terminal state ────────────

def line_with_reserved_lot(
    api: ApiClient,
    allocations: Optional[List[Dict[str, Any]]] = None,
    markets: Optional[List[str]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """
    A line whose stewardship agreement is APPROVED and which carries one
    RESERVED seed increase lot.

    The default allocations are 4000 / 9000 / 1300 kg across US_CORNBELT,
    CA_PRAIRIE and MX_BAJIO — the per-allocation bag ceilings are 173, 389 and
    57, so the lot plans 619 bags and reserves 386875 g.
    """
    markets = markets or ["US_CORNBELT", "CA_PRAIRIE", "MX_BAJIO"]
    allocations = allocations or [
        f.allocation("US_CORNBELT", 4000),
        f.allocation("CA_PRAIRIE", 9000),
        f.allocation("MX_BAJIO", 1300),
    ]
    program_id, objective_id = program_with_objective(api)
    line = create_line(
        api,
        program_id,
        objective_id,
        **(line_overrides or {"designation": "SX-3001", "seed_inventory_g": 500000}),
    )
    agreement = approved_agreement(api, line["id"], markets=markets)
    lot = reserve_lot(api, line["id"], markets[0], allocations)
    return SimpleNamespace(
        program_id=program_id,
        objective_id=objective_id,
        line_id=line["id"],
        agreement_id=agreement["id"],
        lot_id=lot["id"],
    )


def advanced_line_at_stage_1(api: ApiClient, granted_plots: int = 40) -> SimpleNamespace:
    """
    Line A carried from NURSERY to STAGE_1 by one ADVANCE decision against an
    ANALYZED single-site STAGE_1 series.
    """
    network = single_site_analyzed(api)
    decision = record_decision(
        api,
        network.line_a_id,
        network.series_id,
        decision=DecisionType.ADVANCE,
        granted_plots=granted_plots,
        rationale="clears the bar",
    )
    network.decision_id = decision["id"]
    return network
