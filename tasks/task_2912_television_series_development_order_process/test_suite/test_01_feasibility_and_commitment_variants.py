"""The two-variant reads: feasibility by basis, and a step deal's two commitment sums.

Each test names the PRD sentence that fixes the arithmetic it checks.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    FEASIBILITY_BASIS_LICENSE,
    FEASIBILITY_BASIS_PATTERN,
    GUILD_TIER_LOW,
    STEP_FIRST_DRAFT,
    STEP_PENDING,
    STEP_STORY,
    VERDICT_FEASIBLE,
    VERDICT_INFEASIBLE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import business_affairs_headers, finance_controller_headers


def test_pattern_basis_calls_the_series_order_feasible(api):
    """PATTERN takes the slate's pattern budget as its cost base and clears the deficit ceiling.

    PRD 3.8: "On the `PATTERN` basis - the network's own view, what it believes the
    show costs to make in its slot - the cost base is the slate's
    `pattern_budget_per_episode_cents` taken directly, with no platform factor applied."

    Design: Difficulty/dual_variant_calc/feasibility_pattern_basis_feasible_while_license_basis_infeasible
    """
    ctx = build_scenario(api, "pilot_ordered")

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    a.assert_cents(project["cumulative_dev_cost_cents"], 37375000, "cumulative_dev_cost_cents")

    data = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 10},
        )
    )
    a.assert_feasibility(
        data,
        basis=FEASIBILITY_BASIS_PATTERN,
        episode_count=10,
        per_episode_cost_cents=35737500,
        tier_factor_bps=9000,
        license_fee_final_cents=30000000,
        deficit_per_episode_cents=5737500,
        total_deficit_cents=57375000,
        verdict=VERDICT_FEASIBLE,
    )


def test_license_basis_on_the_same_project_reports_the_opposite_verdict(api):
    """LICENSE scales the cap by the STREAMING cost factor and lands infeasible on identical data.

    PRD 3.8: "the two bases can and do return opposite verdicts on the same project,
    which is exactly why the caller must choose one."

    Design: Difficulty/dual_variant_calc/feasibility_pattern_basis_feasible_while_license_basis_infeasible
    """
    ctx = build_scenario(api, "pilot_ordered")

    license_data = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_LICENSE, "episode_count": 10},
        )
    )
    a.assert_feasibility(
        license_data,
        basis=FEASIBILITY_BASIS_LICENSE,
        episode_count=10,
        per_episode_cost_cents=39737500,
        tier_factor_bps=9000,
        license_fee_final_cents=30000000,
        deficit_per_episode_cents=9737500,
        total_deficit_cents=97375000,
        verdict=VERDICT_INFEASIBLE,
    )

    pattern_data = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 10},
        )
    )
    assert pattern_data["verdict"] == VERDICT_FEASIBLE
    assert (
        license_data["deficit_per_episode_cents"]
        - pattern_data["deficit_per_episode_cents"]
        == 4000000
    ), "the LICENSE base exceeds the PATTERN base by the platform factor applied to the cap"


def test_guaranteed_and_full_option_exposure_diverge_on_one_stored_ladder(api):
    """One step list yields a guaranteed floor of 4375000 and a full exposure of 12375000.

    PRD 3.4: "`full_option_exposure_cents` is the total of `effective_fee_cents` over
    every step of the deal without exception - the worst case if every option is
    exercised - and so it is always at least the guaranteed figure and strictly larger
    whenever the deal has any optional step at all."

    Design: Difficulty/dual_variant_calc/script_deal_guaranteed_only_and_full_option_variants_diverge
    """
    ctx = build_scenario(
        api,
        "deal",
        deal={
            "steps": [
                f.step_spec(STEP_STORY, 3000000),
                f.step_spec(STEP_FIRST_DRAFT, 8000000),
            ],
            "guaranteed_step_count": 1,
        },
    )

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    a.assert_cents(deal["guaranteed_commitment_cents"], 4375000, "guaranteed_commitment_cents")
    a.assert_cents(deal["full_option_exposure_cents"], 12375000, "full_option_exposure_cents")
    assert (
        deal["full_option_exposure_cents"] - deal["guaranteed_commitment_cents"]
        == 8000000
    ), "the optional FIRST_DRAFT step is the whole difference between the two variants"

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    a.assert_step(a.find_step(steps, 1), step_type=STEP_STORY, effective_fee_cents=4375000)
    a.assert_step(
        a.find_step(steps, 2),
        step_type=STEP_FIRST_DRAFT,
        effective_fee_cents=8000000,
        status=STEP_PENDING,
    )


def test_the_slate_carries_only_the_guaranteed_half_of_that_ladder(api):
    """With the optional step still PENDING, encumbered equals the guaranteed commitment.

    PRD 3.4: "A deal whose optional steps are all still `PENDING` therefore has an
    `encumbered_cents` exactly equal to its `guaranteed_commitment_cents`."

    Design: Difficulty/dual_variant_calc/script_deal_guaranteed_only_and_full_option_variants_diverge
    """
    ctx = build_scenario(
        api,
        "deal",
        deal={
            "steps": [
                f.step_spec(STEP_STORY, 3000000),
                f.step_spec(STEP_FIRST_DRAFT, 8000000),
            ],
            "guaranteed_step_count": 1,
        },
    )

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4375000, available=395625000)


def test_the_pricing_tier_is_read_off_the_provisional_deficit(api):
    """At ten episodes the provisional deficit is 1000000, which pins the tier at 9500.

    PRD 3.8: "the final license fee depends on the tier and the tier depends on the
    provisional deficit, so the tier must be read off the provisional figure in a
    single forward pass."

    Design: Difficulty/combinatorial_formula/feasibility_tier_pinned_to_provisional_deficit_not_final_deficit
    """
    ctx = build_scenario(
        api,
        "deal",
        slate={
            "total_dev_budget_cents": 100000000,
            "pattern_budget_per_episode_cents": 30500000,
            "license_fee_cap_per_episode_cents": 30000000,
            "max_deficit_per_episode_cents": 2000000,
        },
        writer={"guild_minimum_tier": GUILD_TIER_LOW},
        deal={"steps": [f.step_spec(STEP_STORY, 5000000)], "guaranteed_step_count": 1},
    )

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    a.assert_cents(project["cumulative_dev_cost_cents"], 5000000, "cumulative_dev_cost_cents")

    data = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 10},
        )
    )
    a.assert_feasibility(
        data,
        episode_count=10,
        per_episode_cost_cents=31000000,
        tier_factor_bps=9500,
        license_fee_final_cents=29450000,
        deficit_per_episode_cents=1550000,
        total_deficit_cents=15500000,
        verdict=VERDICT_FEASIBLE,
    )
    assert data["deficit_per_episode_cents"] > 1500000, (
        "the reported deficit is above the breakpoint while the tier came from the "
        "provisional deficit below it"
    )


def test_a_shorter_order_pushes_the_provisional_deficit_into_the_deepest_tier(api):
    """At four episodes the amortised cost lifts the provisional deficit past 1500000.

    PRD 3.8: "When it is greater than that, `tier_factor_bps` is 9000."

    Design: Difficulty/combinatorial_formula/feasibility_tier_pinned_to_provisional_deficit_not_final_deficit
    """
    ctx = build_scenario(
        api,
        "deal",
        slate={
            "total_dev_budget_cents": 100000000,
            "pattern_budget_per_episode_cents": 30500000,
            "license_fee_cap_per_episode_cents": 30000000,
            "max_deficit_per_episode_cents": 2000000,
        },
        writer={"guild_minimum_tier": GUILD_TIER_LOW},
        deal={"steps": [f.step_spec(STEP_STORY, 5000000)], "guaranteed_step_count": 1},
    )

    data = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 4},
        )
    )
    a.assert_feasibility(
        data,
        episode_count=4,
        per_episode_cost_cents=31750000,
        tier_factor_bps=9000,
        license_fee_final_cents=28575000,
        deficit_per_episode_cents=3175000,
        total_deficit_cents=12700000,
        verdict=VERDICT_INFEASIBLE,
    )
