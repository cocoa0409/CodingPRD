"""Calculation details: share floor at zero, low tier boundary, valuation input set."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data, api_client,
    create_open_branch, setup_open_branch_with_period,
    setup_retiring_advisor_with_transfer,
    create_territory, create_branch,
    create_validated_advisor, create_site_approved_branch, create_advisor,
    create_goodwill_transfer_payload, make_advisor_headers,
    post_production, post_charge, set_clock,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_profit_share_zero_when_net_is_zero():
    """PRD §3.6: "Given a period's `net_profit_cents`: when the net is zero or
    negative, the share is zero."

    Design: Corner/calculations/profit_share_zero_when_net_nonpositive
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 500000, "2026-09-10T00:00:00Z")
    post_charge(period["id"], branch["id"], 500000, "LEASE_RENT")
    set_clock("2026-10-02T00:00:00Z")

    closed = validate_success(api_client.close_period(period["id"], ADMIN))
    assert closed["net_profit_cents"] == 0
    assert closed["advisor_share_cents"] == 0


def test_tier_1_to_tier_2_boundary_at_300():
    """PRD §3.6: "The score maps to tiers with an inclusive upper boundary on
    the middle tier: a score below 300 is `TIER_1`; a score of at least 300
    and at most 900 is `TIER_2` — a score of exactly 900 is still `TIER_2`;
    and a score of 901 or more is `TIER_3`."

    Design: Corner/calculations/tier1_boundary_299_vs_300
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])

    first = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": branch["version"],
            "household_count": 29,
            "assets_under_care_dollars": 900000,
        },
        ADMIN,
    ))
    # 29*10 + 900000//100000 = 290 + 9 = 299 -> TIER_1
    assert first["tier_score"] == 299
    assert first["service_tier"] == "TIER_1"

    second = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": first["version"],
            "household_count": 30,
        },
        ADMIN,
    ))
    # 30*10 + 9 = 309 -> TIER_2
    assert second["tier_score"] == 309
    assert second["service_tier"] == "TIER_2"


def test_reversed_production_excluded_from_valuation():
    """PRD §3.7: "The `trailing_revenue_cents` is the sum of
    `gross_commission_cents` across `POSTED` production records of the
    branch's advisors — reversed rows excluded — whose `posted_at` falls in
    the trailing window: the twelve complete calendar months before the
    offer's creation month, running from the first day of the month twelve
    months before creation up to but not including the first day of the
    creation month."

    Design: Corner/calculations/reversed_production_excluded_from_valuation
    """
    # Branch with a retiring advisor; a trailing-window record is reversed
    # before the transfer is created.
    advisor = create_validated_advisor(
        start_date="2020-01-01T00:00:00Z",
        seed_posted_at="2020-01-02T00:00:00Z",
        eval_window_end="2020-04-01T00:00:00Z",
    )
    branch, _ = create_site_approved_branch(
        term_start="2020-01-01T00:00:00Z", term_end="2030-12-31T00:00:00Z",
    )
    validate_success(
        api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN)
    )
    set_clock("2026-09-05T00:00:00Z")
    post_production(advisor["id"], 2400000, "2026-03-10T00:00:00Z")
    reversed_record = post_production(advisor["id"], 500000, "2026-04-10T00:00:00Z")
    validate_success(api_client.reverse_production_record(reversed_record["id"], ADMIN))

    validate_success(
        api_client.declare_retirement(advisor["id"], make_advisor_headers(advisor["id"]))
    )
    successor = create_advisor(hire_date="2024-01-01T00:00:00Z")
    transfer = validate_success(api_client.create_goodwill_transfer(
        create_goodwill_transfer_payload(
            branch["id"], advisor["id"], successor["id"],
            valuation_mode="INTERNAL_SUCCESSION", escrow_deposit_cents=0,
        ),
        ADMIN,
    ), expected_status=201)

    # The REVERSED 500000 record must not feed the valuation.
    assert transfer["trailing_revenue_cents"] == 2400000
    assert transfer["offer_price_cents"] == 1800000
