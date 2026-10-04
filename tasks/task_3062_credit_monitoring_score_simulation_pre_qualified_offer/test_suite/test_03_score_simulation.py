"""Score simulation: the recursive projection walk and the tier lookup."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    create_active_score_tier,
    create_simulation,
    setup_simulation_consumer,
)


def test_simulation_floors_each_utilization_decile_term(api, as_consumer):
    """PRD §3.3: "the score gains 3 points (`UTIL_TERMINAL_STEP_POINTS`) for each
    complete group of 10 utilization percentage points in the final utilization, minus
    3 points for each complete group of 10 points in the consumer's original utilization."
    PRD §3.3: "Every quantity in this walk is a whole number of points, and each
    group-of-ten term is floored to a whole number before the points are summed."

    Design: Difficulty/combinatorial_formula/simulation_recursive_floor_term
    """
    create_active_score_tier(tier_code="GOOD", min_score=670, max_score=739, api=api)
    consumer, snapshot = setup_simulation_consumer(
        score=680, balance_cents=300_000, limit_cents=1_200_000, api=api,
        email="vera@example.com", bureau_pin="5510", dti_pct=20.0,
    )
    simulation = create_simulation(
        consumer["id"], [{"action_code": "PAY_DOWN_REVOLVING", "amount_cents": 72_000}], api=api
    )

    assert simulation["projected_score"] == 682
    assert simulation["delta_points"] == 2
    assert simulation["base_utilization_pct"] == 25.00
    assert simulation["baseline_score"] == 680
    assert simulation["status"] == "FINALIZED"


def test_simulation_saturates_at_the_score_floor(api, as_consumer):
    """PRD §3.3: "The result is then clamped into the platform's score range, which
    runs from a floor of 300 (`SCORE_MIN`) to a ceiling of 850 (`SCORE_MAX`); the
    clamped value becomes `projected_score`, and `delta_points` is that value minus
    the consumer's current score."

    Design: Difficulty/combinatorial_formula/simulation_recursive_floor_term
    """
    create_active_score_tier(tier_code="GOOD", min_score=670, max_score=739, api=api)
    consumer, snapshot = setup_simulation_consumer(
        score=303, balance_cents=480_000, limit_cents=1_200_000, api=api,
        email="wes@example.com", bureau_pin="8802", dti_pct=20.0,
    )
    simulation = create_simulation(
        consumer["id"], [{"action_code": "PAY_DOWN_REVOLVING", "amount_cents": 300_000}], api=api
    )

    assert simulation["projected_score"] == 300
    assert simulation["delta_points"] == -3
    assert simulation["base_utilization_pct"] == 40.00


def test_simulation_tier_lookup_hits_the_inclusive_lower_bound(api, as_consumer):
    """PRD §3.3: "the projected score is placed into a tier by looking at every active
    `ScoreTierThreshold` sorted by `min_score` ascending and then `max_score` ascending,
    and taking the `tier_code` of the first tier whose inclusive band contains the
    projected score".

    Design: Corner/calculations/simulation_clamps_at_the_tier_lookup_boundary
    """
    create_active_score_tier(tier_code="GOOD", min_score=670, max_score=739, api=api)
    create_active_score_tier(tier_code="VERY_GOOD", min_score=740, max_score=799, api=api)

    on_bound = setup_simulation_consumer(
        score=752, balance_cents=240_000, limit_cents=1_200_000, api=api,
        email="bound@example.com", bureau_pin="4680", dti_pct=20.0,
    )[0]
    below_floor = setup_simulation_consumer(
        score=740, balance_cents=240_000, limit_cents=1_200_000, api=api,
        email="cusp@example.com", bureau_pin="5791", dti_pct=20.0,
    )[0]

    on_bound_sim = create_simulation(
        on_bound["id"], [{"action_code": "CLOSE_OLDEST_TRADELINE"}], api=api
    )
    below_floor_sim = create_simulation(
        below_floor["id"], [{"action_code": "CLOSE_OLDEST_TRADELINE"}], api=api
    )

    assert on_bound_sim["projected_score"] == 740
    assert on_bound_sim["tier_code"] == "VERY_GOOD"
    assert below_floor_sim["projected_score"] == 728
    assert below_floor_sim["tier_code"] == "GOOD"
    assert on_bound_sim["delta_points"] == -12
    assert below_floor_sim["delta_points"] == -12
    assert on_bound_sim["base_utilization_pct"] == 20.00


def test_simulation_delta_is_measured_against_the_current_score(api, as_consumer):
    """PRD §3.3: "the clamped value becomes `projected_score`, and `delta_points` is
    that value minus the consumer's current score."
    PRD §3.3: "A `CLOSE_OLDEST_TRADELINE` action subtracts 12 points
    (`CLOSE_OLDEST_TRADELINE_PENALTY_POINTS`)."

    Design: Corner/calculations/simulation_clamps_at_the_tier_lookup_boundary
    """
    create_active_score_tier(tier_code="GOOD", min_score=670, max_score=739, api=api)
    create_active_score_tier(tier_code="VERY_GOOD", min_score=740, max_score=799, api=api)
    consumer, snapshot = setup_simulation_consumer(
        score=740, balance_cents=240_000, limit_cents=1_200_000, api=api,
        email="upper@example.com", bureau_pin="5792", dti_pct=20.0,
    )
    simulation = create_simulation(
        consumer["id"], [{"action_code": "CLOSE_OLDEST_TRADELINE"}], api=api
    )
    assert simulation["projected_score"] == 728
    assert simulation["tier_code"] == "GOOD"