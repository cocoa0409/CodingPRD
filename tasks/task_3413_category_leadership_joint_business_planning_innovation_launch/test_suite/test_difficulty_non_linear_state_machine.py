"""Difficulty queue — non-linear state machines.

The JointBusinessPlan negotiation machine is cyclic (PROPOSED -> COUNTERED ->
PROPOSED ...) with the round counter accumulating across the loop (PRD §3.1),
and the Forecast carries two independent state axes that evolve without leaking
into each other (PRD §3.7). Each test translates one difficulty-design
instance and cites the PRD rule it pins.
"""
from test_helpers import (
    assert_forecast,
    assert_plan,
    setup_activated_plan,
    setup_proposed_plan,
    validate_success,
)

_WEEK_START = "2027-03-01T00:00:00Z"  # a Monday


def _run_negotiation_loop(api, scenario, manufacturer_planner_headers, targets):
    """Alternate counters (RetailerBuyer from PROPOSED) and re-proposals
    (ManufacturerPlanner from COUNTERED); returns the plan after each move."""
    plans = []
    for i, target in enumerate(targets):
        headers = scenario["buyer_headers"] if i % 2 == 0 else manufacturer_planner_headers
        plans.append(
            validate_success(
                api.negotiate_plan(scenario["plan"]["id"], {"growth_target_pct": target}, headers),
                200,
            )
        )
    return plans


def test_negotiation_loops_back_to_proposed(api, manufacturer_planner_headers):
    """PRD §3.1: "While the plan is `PROPOSED`, the `RetailerBuyer` of the plan's own retailer may counter: the call carries a new `growth_target_pct`, and on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."
    PRD §3.1: "While the plan is `COUNTERED`, the mirror leg belongs to the `ManufacturerPlanner`, whose re-proposal moves the plan `COUNTERED → PROPOSED` with the same field and round bookkeeping."

    Four alternating moves cycle the plan PROPOSED -> COUNTERED -> PROPOSED ->
    COUNTERED -> PROPOSED — back to a previously visited state — and the latest
    re-proposal (10) owns growth_target_pct.

    Design: Difficulty/non_linear_state_machine/plan_negotiation_cycle_rounds
    """
    scenario = setup_proposed_plan()
    plans = _run_negotiation_loop(api, scenario, manufacturer_planner_headers, [10, 9, 11, 10])

    assert [p["status"] for p in plans] == ["COUNTERED", "PROPOSED", "COUNTERED", "PROPOSED"], (
        f"the machine must loop back to the visited PROPOSED state, got "
        f"{[p['status'] for p in plans]}"
    )
    assert [p["growth_target_pct"] for p in plans] == [10, 9, 11, 10]
    final = validate_success(api.get_plan(scenario["plan"]["id"], manufacturer_planner_headers), 200)
    assert_plan(final)
    assert final["status"] == "PROPOSED"
    assert final["growth_target_pct"] == 10, (
        f"the latest re-proposal must win, got {final['growth_target_pct']}"
    )


def test_negotiation_round_and_version_accumulate(api, manufacturer_planner_headers):
    """PRD §3.1: "A plan is born directly into `PROPOSED` with its `negotiation_round` at 1."
    PRD §3.1: "While the plan is `PROPOSED`, the `RetailerBuyer` of the plan's own retailer may counter: the call carries a new `growth_target_pct`, and on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including the automatic transitions the server performs on its own (supersessions, expirations, cascades)."

    Starting at round 1, four successful moves leave negotiation_round == 5 and
    the version exactly four increments above the freshly created plan's.

    Design: Difficulty/non_linear_state_machine/plan_negotiation_cycle_rounds
    """
    scenario = setup_proposed_plan()
    created_version = scenario["plan"]["version"]
    assert scenario["plan"]["negotiation_round"] == 1

    plans = _run_negotiation_loop(api, scenario, manufacturer_planner_headers, [10, 9, 11, 10])

    assert [p["negotiation_round"] for p in plans] == [2, 3, 4, 5]
    for i, plan in enumerate(plans):
        assert plan["version"] == created_version + (i + 1), (
            f"move {i + 1} must increment version by exactly 1, got {plan['version']}"
        )
    final = validate_success(api.get_plan(scenario["plan"]["id"], manufacturer_planner_headers), 200)
    assert final["negotiation_round"] == 5
    assert final["version"] == created_version + 4


def _superseded_commitment_scenario(api, supply_chain_planner_headers):
    """ACTIVATED plan; forecast f1 published for one week and committed by the
    retailer, then f2 published for the same week, superseding f1."""
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    f1 = validate_success(
        api.create_forecast(
            plan_id, {"week_start": _WEEK_START, "baseline_cases": 1000}, supply_chain_planner_headers
        ),
        201,
    )
    committed = validate_success(
        api.commit_forecast(f1["id"], {"committed_cases": 1100}, scenario["buyer_headers"]), 200
    )
    f2 = validate_success(
        api.create_forecast(
            plan_id, {"week_start": _WEEK_START, "baseline_cases": 1200}, supply_chain_planner_headers
        ),
        201,
    )
    forecasts = validate_success(
        api.list_forecasts(
            plan_id, supply_chain_planner_headers, params={"week_start": _WEEK_START}
        ),
        200,
    )
    by_id = {f["id"]: f for f in forecasts}
    return by_id[f1["id"]], by_id[f2["id"]], committed


def test_supersession_flips_only_the_publication_axis(api, supply_chain_planner_headers):
    """PRD §3.7: "The axes never leak into each other: when a planner publishes a new forecast for a plan and `week_start` that already has a `PUBLISHED` forecast, the incumbent auto-transitions to `SUPERSEDED` with its `version` incremented — yet its `commit_status` is preserved untouched, so a committed week stays committed even after a fresher baseline replaces it."

    The incumbent flips PUBLISHED -> SUPERSEDED while the fresher baseline is
    born PUBLISHED / UNCOMMITTED.

    Design: Difficulty/non_linear_state_machine/forecast_parallel_dimensions
    """
    f1, f2, _committed = _superseded_commitment_scenario(api, supply_chain_planner_headers)

    assert_forecast(f1)
    assert_forecast(f2)
    assert f1["pub_status"] == "SUPERSEDED", (
        f"the incumbent must be superseded, got {f1['pub_status']}"
    )
    assert f2["pub_status"] == "PUBLISHED"
    assert f2["commit_status"] == "UNCOMMITTED"
    assert f2["baseline_cases"] == 1200


def test_commitment_survives_supersession(api, supply_chain_planner_headers):
    """PRD §3.7: "A successful commit moves `commit_status` to `COMMITTED`, records the `committed_cases`, stamps `committed_at` from the logical clock, and increments the forecast's `version`."
    PRD §3.7: "Supersession never clears a commitment, and a superseded forecast can never receive a new one."
    PRD §3.7: "yet its `commit_status` is preserved untouched, so a committed week stays committed even after a fresher baseline replaces it."

    The superseded incumbent still reads COMMITTED with committed_cases 1100,
    and its version moved exactly one increment past the commit's.

    Design: Difficulty/non_linear_state_machine/forecast_parallel_dimensions
    """
    f1, _f2, committed = _superseded_commitment_scenario(api, supply_chain_planner_headers)

    assert committed["commit_status"] == "COMMITTED"
    assert f1["commit_status"] == "COMMITTED", (
        f"commitment must survive supersession, got {f1['commit_status']}"
    )
    assert f1["committed_cases"] == 1100, (
        f"the recorded commitment must survive, got {f1['committed_cases']}"
    )
    assert f1["committed_at"] is not None
    assert f1["version"] == committed["version"] + 1, (
        "supersession increments the incumbent's version by exactly 1 (PRD §2.5)"
    )
