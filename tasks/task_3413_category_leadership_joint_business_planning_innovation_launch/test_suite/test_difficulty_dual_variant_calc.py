"""Difficulty queue — dual-variant calculations.

Two PRD calculations are pinned in paired variants computed from identical
inputs: the trade-fund period accrual keeps an accrual-basis and a cash-basis
ledger side by side (PRD §3.6), and the launch distribution projection keeps a
committed-only and a weighted-pipeline read side by side (PRD §3.5). Each test
translates one difficulty-design instance and cites the PRD rule it pins.
"""
import pytest

from test_helpers import (
    assert_distribution_projections,
    assert_fund_invariants,
    assert_innovation_launch,
    assert_trade_fund,
    create_launch_with_phases,
    get_fund,
    list_phases,
    setup_activated_plan,
    validate_success,
)

# Phase inputs from the design recipe: (distribution_target_pct, capacity_cases,
# trade_spend_cents) per phase_index 1..4.
_PHASE_PATCHES = [
    {"distribution_target_pct": 20, "capacity_cases": 500, "trade_spend_cents": 100000},
    {"distribution_target_pct": 30, "capacity_cases": 400, "trade_spend_cents": 50000},
    {"distribution_target_pct": 25, "capacity_cases": 300, "trade_spend_cents": 40000},
    {"distribution_target_pct": 15, "capacity_cases": 200, "trade_spend_cents": 10000},
]


def _activated_scenario():
    """ACTIVATED plan at accrual rate 4% / EDLP split 60% with a zeroed fund."""
    return setup_activated_plan(accrual_rate_pct=4, edlp_split_pct=60)


def _launch_with_mixed_phase_gates(api, manufacturer_planner_headers):
    """Launch whose phases land GATE_PASSED, GATE_PASSED, GATE_FAILED, PENDING.

    Phase 3 is patched to a zero distribution target before evaluation, so its
    gate fails; phase 4 is never evaluated and stays PENDING.
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"],
        launch_date="2027-03-01T00:00:00Z",
        total_trade_budget_cents=1000000,
    )
    for phase, patch in zip(phases, _PHASE_PATCHES):
        validate_success(
            api.patch_launch_phase(launch["id"], phase["id"], patch, manufacturer_planner_headers),
            200,
        )
    for phase in phases[:2]:
        passed = validate_success(
            api.evaluate_launch_phase(launch["id"], phase["id"], manufacturer_planner_headers), 200
        )
        assert passed["status"] == "GATE_PASSED"
    validate_success(
        api.patch_launch_phase(
            launch["id"], phases[2]["id"], {"distribution_target_pct": 0}, manufacturer_planner_headers
        ),
        200,
    )
    failed = validate_success(
        api.evaluate_launch_phase(launch["id"], phases[2]["id"], manufacturer_planner_headers), 200
    )
    assert failed["status"] == "GATE_FAILED"
    return scenario, launch


def test_accrual_basis_credit_and_bucket_shares(api, finance_analyst_headers):
    """PRD §3.6: "The period credit is the `invoiced_sales_cents` multiplied by the fund's `accrual_rate_pct` and divided by 100, rounded half-up to a whole cent."
    PRD §3.6: "The EDLP bucket's share of that credit is the period credit multiplied by the fund's `edlp_split_pct` and divided by 100, again rounded half-up to a whole cent, and the EVENT bucket receives the remainder — the period credit minus the EDLP share — so the rounding remainder always routes to the event side."

    One posted period of 1,000,000 invoiced cents at rate 4% / split 60 credits
    40,000 cents, routing 24,000 to EDLP and the 16,000 remainder to EVENT.

    Design: Difficulty/dual_variant_calc/fund_accrual_basis_vs_cash_basis
    """
    scenario = _activated_scenario()
    fund_id = scenario["fund"]["id"]

    fund = validate_success(
        api.post_fund_accrual(
            fund_id, {"period": "2027-01", "invoiced_sales_cents": 1000000}, finance_analyst_headers
        ),
        201,
    )
    assert_trade_fund(fund)
    assert fund["edlp_accrued_cents"] == 24000, (
        f"edlp_accrued_cents must be round_half_up(40000*0.6)=24000, got {fund['edlp_accrued_cents']}"
    )
    assert fund["event_accrued_cents"] == 16000, (
        f"event bucket takes the remainder 40000-24000=16000, got {fund['event_accrued_cents']}"
    )
    assert fund["total_invoiced_cents"] == 1000000
    assert_fund_invariants(fund)

    reread = validate_success(api.get_fund(fund_id, finance_analyst_headers), 200)
    assert reread["edlp_accrued_cents"] == 24000
    assert reread["event_accrued_cents"] == 16000


def test_cash_basis_shadow_strictly_below_accrual(api, finance_analyst_headers):
    """PRD §3.6: "In the same pass the server computes the cash-basis shadow: each bucket's share is multiplied by the collection factor 0.92 and rounded half-up to a whole cent, which makes the cash figures strictly smaller than their accrual counterparts whenever a share is positive."

    Identical inputs under the cash lens: EDLP 24,000 -> 22,080 and EVENT
    16,000 -> 14,720, each strictly below its accrual counterpart.

    Design: Difficulty/dual_variant_calc/fund_accrual_basis_vs_cash_basis
    """
    scenario = _activated_scenario()
    fund_id = scenario["fund"]["id"]

    fund = validate_success(
        api.post_fund_accrual(
            fund_id, {"period": "2027-01", "invoiced_sales_cents": 1000000}, finance_analyst_headers
        ),
        201,
    )
    assert_trade_fund(fund)
    assert fund["edlp_cash_cents"] == 22080, (
        f"edlp_cash_cents must be round_half_up(24000*0.92)=22080, got {fund['edlp_cash_cents']}"
    )
    assert fund["event_cash_cents"] == 14720, (
        f"event_cash_cents must be round_half_up(16000*0.92)=14720, got {fund['event_cash_cents']}"
    )
    assert fund["edlp_cash_cents"] < fund["edlp_accrued_cents"]
    assert fund["event_cash_cents"] < fund["event_accrued_cents"]


def test_committed_projection_counts_only_gate_passed_phases(api, manufacturer_planner_headers):
    """PRD §3.5: "The committed read, `projected_distribution_committed_pct`, sums each phase's `distribution_target_pct` with `GATE_PASSED` phases weighted at 1.0 and phases in any other status weighted at 0.0."
    PRD §3.5: "If the launch is still `PLANNING` but any of the gate's own conditions fails — a lower-indexed phase not yet passed, a zero distribution target, or zero capacity — the phase moves `PENDING → GATE_FAILED` instead: the evaluation itself always succeeds as a call; it is the gate that fails."

    Targets 20/30/25/15 with phases GATE_PASSED, GATE_PASSED, GATE_FAILED
    (zeroed target), PENDING give a committed read of exactly 50.0.

    Design: Difficulty/dual_variant_calc/launch_distribution_weighted_vs_committed
    """
    scenario, launch = _launch_with_mixed_phase_gates(api, manufacturer_planner_headers)

    refreshed = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert_innovation_launch(refreshed)
    phases = list_phases(launch["id"])
    assert [p["status"] for p in phases] == [
        "GATE_PASSED",
        "GATE_PASSED",
        "GATE_FAILED",
        "PENDING",
    ]
    assert refreshed["projected_distribution_committed_pct"] == pytest.approx(50.0, abs=0.001), (
        "committed read must be 20*1.0 + 30*1.0 + 0*0.0 + 15*0.0 = 50.0, got "
        f"{refreshed['projected_distribution_committed_pct']}"
    )
    assert_distribution_projections(refreshed, phases)


def test_weighted_projection_counts_pending_phases_fractionally(api, manufacturer_planner_headers):
    """PRD §3.5: "The pipeline read, `projected_distribution_weighted_pct`, sums the same targets fractionally: a weight of 1.0 for `GATE_PASSED`, 0.25 for `PENDING`, and 0.0 for `GATE_FAILED`."
    PRD §3.5: "Both are stored rounded half-up to 2 decimal places and are refreshed on every phase creation, patch, and evaluation."

    Identical phase data under the pipeline lens: 20 + 30 + 0*0.0 + 15*0.25
    gives 53.75, so the two variants disagree by exactly 3.75 points.

    Design: Difficulty/dual_variant_calc/launch_distribution_weighted_vs_committed
    """
    scenario, launch = _launch_with_mixed_phase_gates(api, manufacturer_planner_headers)

    refreshed = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert_innovation_launch(refreshed)
    assert refreshed["projected_distribution_weighted_pct"] == pytest.approx(53.75, abs=0.001), (
        "weighted read must be 20 + 30 + 0 + 15*0.25 = 53.75, got "
        f"{refreshed['projected_distribution_weighted_pct']}"
    )
    delta = (
        refreshed["projected_distribution_weighted_pct"]
        - refreshed["projected_distribution_committed_pct"]
    )
    assert delta == pytest.approx(3.75, abs=0.001), (
        f"the two variants must disagree by exactly 3.75 for identical phase data, got {delta}"
    )
    assert_distribution_projections(refreshed, list_phases(launch["id"]))
