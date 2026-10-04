"""Tiered profit-share boundary arithmetic and per-record milestone rounding."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data, api_client,
    setup_open_branch_with_period, post_production, post_charge,
    set_clock, get_period, create_advisor, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def _enroll_and_produce(goal_cents, productions):
    """Create an advisor, enroll with goal_cents, post the given
    (gross, payout_rate, posted_at) records, submit the milestone.
    Returns (advisor, program, production_records)."""
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": goal_cents, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    records = [
        post_production(advisor["id"], gross, posted_at, payout_rate=rate)
        for gross, rate, posted_at in productions
    ]
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    return advisor, program, records


def test_profit_share_all_three_tiers_net_1000010():
    """PRD §3.6: "The first tier covers the lesser of the net and 500,000
    cents; the second tier covers whatever remains above 500,000 cents, up to
    another 500,000 cents; the third tier covers everything above 1,000,000
    cents. Each tier's base is multiplied by its rate — thirty-eight percent
    for the first tier, forty-two percent for the second, forty-six percent
    for the third — and each tier's product is rounded half-up to whole cents
    first; the three rounded amounts are then summed into
    `advisor_share_cents`."

    Design: Difficulty/combinatorial_formula/profit_share_tiered_nested_min_max
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 1500010, "2026-09-10T00:00:00Z")
    post_charge(period["id"], branch["id"], 500000, "LEASE_RENT")
    set_clock("2026-10-02T00:00:00Z")

    closed = validate_success(api_client.close_period(period["id"], ADMIN))
    assert closed["net_profit_cents"] == 1000010
    # 190000 + 210000 + round_half_up(10 * 0.46) = 400005
    assert closed["advisor_share_cents"] == 400005


def test_profit_share_nested_min_max_at_tier_ceiling():
    """PRD §3.6: "The first tier covers the lesser of the net and 500,000
    cents; the second tier covers whatever remains above 500,000 cents, up to
    another 500,000 cents; the third tier covers everything above 1,000,000
    cents. Each tier's base is multiplied by its rate — thirty-eight percent
    for the first tier, forty-two percent for the second, forty-six percent
    for the third — and each tier's product is rounded half-up to whole cents
    first; the three rounded amounts are then summed into
    `advisor_share_cents`."

    Design: Difficulty/combinatorial_formula/profit_share_tiered_nested_min_max
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 2000000, "2026-09-10T00:00:00Z")
    post_charge(period["id"], branch["id"], 1000000, "LEASE_RENT")
    set_clock("2026-10-02T00:00:00Z")

    closed = validate_success(api_client.close_period(period["id"], ADMIN))
    # net 1000000 sits exactly at the tier-2 ceiling: 190000 + 210000 + 0
    assert closed["net_profit_cents"] == 1000000
    assert closed["advisor_share_cents"] == 400000


def test_milestone_sums_per_record_rounded_values():
    """PRD §3.1: "Each production record already carries its own per-record
    rounded `commissions_cents`, and the milestone simply sums those rounded
    values; it does not re-round the gross sum."
    PRD §3.1: "The `outcome` is `PASS` when `production_cents` reaches at
    least `goal_cents` — the boundary is inclusive, so production exactly
    equal to the goal passes — and `FAIL` otherwise."

    Design: Difficulty/combinatorial_formula/training_milestone_per_record_rounding
    """
    advisor, program, records = _enroll_and_produce(
        goal_cents=102,
        productions=[
            (101, 0.5, "2026-02-01T00:00:00Z"),
            (101, 0.5, "2026-02-02T00:00:00Z"),
        ],
    )
    # round_half_up(101 * 0.5) = 51 per record.
    assert all(r["commissions_cents"] == 51 for r in records)

    evaluation = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-04-05T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    # Sum-then-round of the gross sum (202 * 0.5 = 101) would miss the goal;
    # the pinned per-record order gives 51 + 51 = 102 == goal.
    assert evaluation["production_cents"] == 102
    assert evaluation["outcome"] == "PASS"


def test_milestone_per_record_rounding_diverges_from_sum_then_round():
    """PRD §2.6: "Second, for multi-component sums, the rounding order is
    pinned: each component is rounded half-up individually and only then are
    the rounded components summed. The system never sums unrounded products
    and rounds the total."
    PRD §3.1: "The `outcome` is `PASS` when `production_cents` reaches at
    least `goal_cents` — the boundary is inclusive, so production exactly
    equal to the goal passes — and `FAIL` otherwise."

    Design: Difficulty/combinatorial_formula/training_milestone_per_record_rounding
    """
    advisor, program, records = _enroll_and_produce(
        goal_cents=152,
        productions=[
            (101, 0.5, "2026-02-01T00:00:00Z"),
            (101, 0.5, "2026-02-02T00:00:00Z"),
            (100, 0.5, "2026-02-03T00:00:00Z"),
        ],
    )
    assert [r["commissions_cents"] for r in records] == [51, 51, 50]

    evaluation = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-04-05T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    # Per-record: 51 + 51 + 50 = 152 (exactly at goal, inclusive PASS).
    # Sum-then-round of the raw products (50.5 + 50.5 + 50 = 151) would FAIL.
    assert evaluation["production_cents"] == 152
    assert evaluation["outcome"] == "PASS"

    program_data = get_success_data(api_client.get_training_program(program["id"], ADMIN))
    assert program_data["status"] == "COMPLETED"
    advisor_data = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert advisor_data["status"] == "VALIDATED"
