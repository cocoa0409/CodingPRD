"""Clearing-fund sizing: the volatility tier, the clamp pair and the net-capital floor."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_clearing_fund, assert_fund_component,
    set_clock, create_active_participant, create_security, create_window,
    submit_trade, lock_in, net_window, create_fund, recompute_fund, component_of,
    setup_fund_open_risk, reopen_fund_with_fresh_net_position,
    MIN_COMPONENT_CENTS, MAX_COMPONENT_CENTS, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_minimum_component_clamp_lifts_a_small_open_risk():
    """PRD §3.9: "the minimum component of 250,000 cents is applied first, then
    the maximum component of 50,000,000 cents, so a small open risk is lifted to
    the floor and a large one is truncated at the cap."
    PRD §3.9: "Finally a net-capital floor is applied last: a member whose
    `financial_standard_status` is `FAIL` is floored at its
    `required_min_net_capital_cents`, and any other member is floored at zero."

    Design: Difficulty/dual_variant_calc/clearing_fund_tiered_capped_vs_uncapped_marginal
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=1, trade_price_cents=100_000, volatility_bps=3000,
        ticker="FND1", cusip="912828XK2")
    assert_fund_component(component)
    assert component["component_amount_cents"] == MIN_COMPONENT_CENTS

    read = validate_success(api_client.get_clearing_fund(fund["id"], ADMIN), 200)
    assert_clearing_fund(read)
    # The fund's total aggregates the latest component of every sized member of
    # the class. The second member carries no open risk, so its component is
    # the clamped minimum.
    assert read["total_component_cents"] == MIN_COMPONENT_CENTS + MIN_COMPONENT_CENTS


def test_uncapped_marginal_variant_would_not_lift_the_component():
    """PRD §3.9: "The clamps are not commutative with the rounding and are not
    applied in the other order; rounding before clamping, rounding the multiplier
    first, and applying the maximum before the minimum all yield different cents
    and are not this rule."

    Design: Difficulty/dual_variant_calc/clearing_fund_tiered_capped_vs_uncapped_marginal
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=1, trade_price_cents=100_000, volatility_bps=3000,
        ticker="FND2", cusip="912828XKB")

    open_risk = 1 * 100_000
    stacked = open_risk * 15000 // 10000
    assert stacked == 150_000
    assert component["component_amount_cents"] == MIN_COMPONENT_CENTS
    assert component["component_amount_cents"] != stacked


def test_maximum_cap_and_net_capital_floor_govern_a_large_open_risk():
    """PRD §3.9: "Finally a net-capital floor is applied last: a member whose
    `financial_standard_status` is `FAIL` is floored at its
    `required_min_net_capital_cents`".
    PRD §3.9: "The component amount is the greater of the clamped value and that
    floor."

    Design: Difficulty/combinatorial_formula/clearing_fund_nested_min_max_and_precedence_order
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=10000, trade_price_cents=1_000_000, volatility_bps=3000,
        ticker="NOD1", cusip="912828XK4", participant_class="BANK",
        capital=2_000_000_000, review_capital=1_000_000_000,
        review_member_index=0, fund_class="BANK")
    assert_fund_component(component)
    # The review leaves the member FAILing, so its net-capital floor is the
    # 1,500,000,000-cent class base a BANK is held to. Its open risk of
    # 10000 * 1000000 stacks to 15000000000, which the MAX_COMPONENT clamp cuts
    # to 50000000; since the clamped value is the smaller of the two, the floor
    # governs: 50000000 -> 1500000000.
    assert component["component_amount_cents"] == 1_500_000_000


def test_maximum_component_cap_truncates_an_unfloored_large_open_risk():
    """PRD §3.9: "the minimum component of 250,000 cents is applied first, then
    the maximum component of 50,000,000 cents, so a small open risk is lifted to
    the floor and a large one is truncated at the cap."

    Design: Difficulty/combinatorial_formula/clearing_fund_nested_min_max_and_precedence_order
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=10000, trade_price_cents=1_000_000, volatility_bps=2000,
        ticker="NOD2", cusip="912828XKC", participant_class="BANK",
        capital=2_000_000_000, fund_class="BANK")

    stacked = 10_000 * 1_000_000 * 10000 // 10000
    assert stacked > MAX_COMPONENT_CENTS
    assert component["component_amount_cents"] == MAX_COMPONENT_CENTS


def test_recomputing_a_recomputed_fund_without_a_fresh_net_position_is_refused():
    """PRD §3.9: "a fund that has already been recomputed and has seen no
    intervening new or replaced net position on its security is refused a second
    recompute with `ERR_FUND_ALREADY_RECOMPUTED`."

    Design: Corner/state_machines/fund_recompute_twice_rejected
    """
    set_clock()
    fa = create_active_participant("Fund Alpha Two", "LEI-FA2", "BANK", 2_000_000_000)
    create_active_participant("Fund Beta Two", "LEI-FB2", "BANK", 2_000_000_000)
    security = create_security("FRC1", "912828XS4", 5000)
    fund = create_fund(security["id"], "BANK")
    first = recompute_fund(fund["id"], fund["version"])
    assert first["status"] == "RECOMPUTED"

    validate_error(api_client.recompute_clearing_fund(
        fund["id"], {"expected_fund_version": first["version"]}, RISK),
        "ERR_FUND_ALREADY_RECOMPUTED")

    rows = validate_success(api_client.list_fund_components(fund["id"], ADMIN), 200)
    generations = {r["generation"] for r in rows}
    assert generations == {1}


def test_fresh_net_position_reopens_a_recomputed_fund_for_a_new_generation():
    """PRD §3.9: "A fresh net position on the fund's security reopens a
    recomputed fund, so the next recompute is legitimate and begins a new
    generation."
    PRD §3.9: "generation 1 for the first sizing and one higher for each
    subsequent sizing, with earlier generations left untouched".

    Design: Corner/cross_cutting_complexity_layers/fund_reopened_by_fresh_net_position_after_recompute
    """
    set_clock()
    go = create_active_participant("Reopen Alpha", "LEI-GO2", "BANK", 2_000_000_000)
    gp = create_active_participant("Reopen Beta", "LEI-GP2", "BANK", 2_000_000_000)
    security = create_security("REO1", "912828XW1", 5000)
    window = create_window(security["id"])

    from test_helpers import locked_in_matched_trade
    locked_in_matched_trade(security["id"], go, gp, "BUY", 100, 4000)
    net_window(window["id"])

    fund = create_fund(security["id"], "BANK")
    first = recompute_fund(fund["id"], fund["version"])
    assert first["status"] == "RECOMPUTED"

    reopen_fund_with_fresh_net_position(security["id"], go, gp)

    reopened = validate_success(api_client.get_clearing_fund(fund["id"], ADMIN), 200)
    assert reopened["status"] == "OPEN"

    recompute_fund(fund["id"], reopened["version"])

    rows = validate_success(api_client.list_fund_components(fund["id"], ADMIN), 200)
    generations = sorted({r["generation"] for r in rows})
    assert generations == [1, 2]


def test_stale_fund_version_is_rejected_on_recompute():
    """PRD §2.9: "Re-sizing a clearing fund requires the field
    `expected_fund_version`, carrying the client's last-observed `version` of the
    target `ClearingFund`."
    PRD §2.9: "If the supplied value does not equal the parent entity's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/state_machines/fund_recompute_twice_rejected
    """
    set_clock()
    create_active_participant("Stale Alpha", "LEI-ST1", "BANK", 2_000_000_000)
    security = create_security("STL1", "912828XS6", 5000)
    fund = create_fund(security["id"], "BANK")
    stale_version = fund["version"]

    recompute_fund(fund["id"], stale_version)

    validate_error(api_client.recompute_clearing_fund(
        fund["id"], {"expected_fund_version": stale_version}, RISK),
        "ERR_STALE_VERSION", expected_status=412)