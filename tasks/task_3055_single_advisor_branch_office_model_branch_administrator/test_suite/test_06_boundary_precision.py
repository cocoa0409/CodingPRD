"""Boundary precision: milestone goal inclusivity and service-tier ceilings."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data, api_client,
    create_advisor, post_production, create_territory, create_branch,
    make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def _evaluate(goal_cents, production_cents):
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": goal_cents, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    post_production(advisor["id"], production_cents, "2026-02-01T00:00:00Z")
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    return validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-04-05T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )


def test_production_exactly_at_goal_passes():
    """PRD §3.1: "The `outcome` is `PASS` when `production_cents` reaches at
    least `goal_cents` — the boundary is inclusive, so production exactly
    equal to the goal passes — and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/training_goal_exact_boundary_passes
    """
    evaluation = _evaluate(goal_cents=10000, production_cents=10000)
    assert evaluation["production_cents"] == 10000
    assert evaluation["outcome"] == "PASS"


def test_production_one_cent_below_goal_fails():
    """PRD §3.1: "The `outcome` is `PASS` when `production_cents` reaches at
    least `goal_cents` — the boundary is inclusive, so production exactly
    equal to the goal passes — and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/training_goal_exact_boundary_passes
    """
    evaluation = _evaluate(goal_cents=10000, production_cents=9999)
    assert evaluation["production_cents"] == 9999
    assert evaluation["outcome"] == "FAIL"


def test_tier_score_900_stays_tier_2_then_901_flips():
    """PRD §3.6: "The score maps to tiers with an inclusive upper boundary on
    the middle tier: a score below 300 is `TIER_1`; a score of at least 300
    and at most 900 is `TIER_2` — a score of exactly 900 is still `TIER_2`;
    and a score of 901 or more is `TIER_3`."

    Design: Difficulty/boundary_precision_check/service_tier_score_boundary_900_vs_901
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])

    first = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": branch["version"],
            "household_count": 80,
            "assets_under_care_dollars": 10000000,
        },
        ADMIN,
    ))
    # 80*10 + 10000000//100000 = 800 + 100 = 900 -> TIER_2 (inclusive ceiling)
    assert first["tier_score"] == 900
    assert first["service_tier"] == "TIER_2"

    second = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": first["version"],
            "assets_under_care_dollars": 10100000,
        },
        ADMIN,
    ))
    # 800 + 101 = 901 -> TIER_3
    assert second["tier_score"] == 901
    assert second["service_tier"] == "TIER_3"


def test_tier_score_floor_division_holds_until_threshold():
    """PRD §3.6: "The score maps to tiers with an inclusive upper boundary on
    the middle tier: a score below 300 is `TIER_1`; a score of at least 300
    and at most 900 is `TIER_2` — a score of exactly 900 is still `TIER_2`;
    and a score of 901 or more is `TIER_3`."

    Design: Difficulty/boundary_precision_check/service_tier_score_boundary_900_vs_901
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])

    first = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": branch["version"],
            "household_count": 80,
            "assets_under_care_dollars": 10099999,
        },
        ADMIN,
    ))
    # floor(10099999/100000) = 100 -> score 900 -> still TIER_2
    assert first["tier_score"] == 900
    assert first["service_tier"] == "TIER_2"

    second = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": first["version"],
            "assets_under_care_dollars": 10100000,
        },
        ADMIN,
    ))
    assert second["tier_score"] == 901
    assert second["service_tier"] == "TIER_3"
