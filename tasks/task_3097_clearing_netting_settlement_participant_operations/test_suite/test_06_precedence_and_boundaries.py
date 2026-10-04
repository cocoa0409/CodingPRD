"""Validation precedence pairs and numeric / collection boundary precision."""
from test_helpers import (
    api_client, validate_success, validate_error,
    set_clock, create_active_participant, create_security, create_window, read_action,
    submit_trade, lock_in, net_window, run_cycle,
    setup_two_active_members, setup_security_and_window,
    setup_fund_open_risk, reopen_fund_with_fresh_net_position,
    net_position_of, member, TEST_USERS,
    VOLATILITY_ELEVATED_BPS, MIN_COMPONENT_CENTS, MAX_COMPONENT_CENTS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_authorization_precedes_business_safety_on_a_double_violation():
    """PRD §2.12: "Authorization is next: a role that is known but not permitted
    yields `ERR_UNAUTHORIZED` before any resource is inspected."
    PRD §2.1: "A request whose role is known but not permitted for the attempted
    operation, per the RBAC matrix, is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/suspension_beats_self_trade_error_category_pair
    """
    set_clock()
    participant = create_active_participant("Unauth Alpha", "LEI-UA")
    security = create_security("UNA1", "912828XL1", 5000)
    window = create_window(security["id"])

    # Both violated: RiskOfficer may not submit trades (priority 2), and the
    # counterparty equals the acting participant (priority 8).
    res = api_client.create_trade_submission(
        {"counterparty_participant_id": participant["id"],
         "security_id": security["id"], "side": "BUY", "quantity": 100,
         "trade_price_cents": 4200, "trade_date": "2026-09-08T14:00:00Z"},
        RISK)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    rows = validate_success(
        api_client.list_trade_submissions(ADMIN, params={"participant_id": participant["id"]}),
        200)
    assert rows == []


def test_state_gate_precedes_the_funding_gate_on_settlement():
    """PRD §2.12: "Only then is state evaluated, yielding `ERR_INVALID_STATE`
    when the target is not in the state a transition requires."
    PRD §2.12: "Business safety rules sit below state."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_underfunded_settlement_error_category_pair
    """
    a, b = setup_two_active_members(name_a="Prior Alpha", name_b="Prior Beta",
                                    lei_a="LEI-PA", lei_b="LEI-PB")
    security, window = setup_security_and_window("PRI1", "912828XL2", 5000)
    submit_trade(security["id"], a["id"], b["id"], "SELL", 100, 4000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4000)
    lock_in(trade["id"], a["id"])

    # The window is still OPEN and nothing is funded, so both the state gate
    # and the funding gate are violated; the state error wins.
    validate_error(api_client.settle_window(window["id"], ADMIN), "ERR_INVALID_STATE")

    still = validate_success(api_client.get_settlement_window(window["id"], ADMIN), 200)
    assert still["status"] == "OPEN"


def test_authorization_precedes_business_temporal_on_corporate_action_apply():
    """PRD §2.1: "`PlatformAdmin` owns participant lifecycle, security and window
    registration, netting and settlement cycles, corporate actions, and dispute
    resolution."
    PRD §2.12: "Authorization is next: a role that is known but not permitted
    yields `ERR_UNAUTHORIZED` before any resource is inspected."

    Design: Corner/validations/auth_precedence_over_state_conflict
    """
    set_clock()
    participant = create_active_participant("Precedence Alpha", "LEI-PR2")
    security = create_security("PRC1", "912828XT3", 5000)
    action = validate_success(api_client.create_corporate_action(
        {"security_id": security["id"], "action_type": "SPLIT",
         "ratio_numerator": 3, "ratio_denominator": 2,
         "effective_date": "2026-09-20"}, ADMIN), 201)

    res = api_client.apply_corporate_action(action["id"], member(participant["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    still = read_action(action["id"], security["id"])
    assert still["status"] == "ANNOUNCED"


def test_volatility_multiplier_tier_boundary_at_2500_bps():
    """PRD §3.9: "That open risk is multiplied by a volatility multiplier of 15000
    basis points when the security's `current_volatility_bps` is strictly above
    2500, and by 10000 basis points otherwise."

    Design: Difficulty/boundary_precision_check/volatility_multiplier_boundary_at_2500_bps
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=1, trade_price_cents=1_000_000,
        volatility_bps=VOLATILITY_ELEVATED_BPS,
        ticker="VOL1", cusip="912828XL3", participant_class="BANK",
        capital=2_000_000_000, fund_class="BANK")
    assert component["component_amount_cents"] == 1_000_000


def test_volatility_multiplier_switches_one_basis_point_above_the_boundary():
    """PRD §3.9: "That open risk is multiplied by a volatility multiplier of 15000
    basis points when the security's `current_volatility_bps` is strictly above
    2500, and by 10000 basis points otherwise."

    Design: Difficulty/boundary_precision_check/volatility_multiplier_boundary_at_2500_bps
    """
    a, b, security, window, fund, component = setup_fund_open_risk(
        quantity=1, trade_price_cents=1_000_000,
        volatility_bps=VOLATILITY_ELEVATED_BPS + 1,
        ticker="VOL1", cusip="912828XL3", participant_class="BANK",
        capital=2_000_000_000, fund_class="BANK")
    assert component["component_amount_cents"] == 1_500_000


def test_open_risk_counts_only_locked_in_trades():
    """PRD §3.9: "Each sized participant's component is the open risk on the
    fund's security, measured over that member's `LOCKED_IN` trades on that
    security carrying a `match_status` of `MATCHED` or `UNRESOLVED`".

    Design: Corner/calculations/fund_scaling_counts_only_locked_in_trades
    """
    set_clock()
    ka = create_active_participant("Filter Alpha", "LEI-KA2", "BANK", 2_000_000_000)
    kb = create_active_participant("Filter Beta", "LEI-KB2", "BANK", 2_000_000_000)
    security = create_security("FIL1", "912828XT1", 5000)
    window = create_window(security["id"])

    submit_trade(security["id"], ka["id"], kb["id"], "SELL", 100, 10000)
    locked = submit_trade(security["id"], kb["id"], ka["id"], "BUY", 100, 10000)
    lock_in(locked["id"], ka["id"])

    # A far larger notional that is never locked in must contribute nothing.
    submit_trade(security["id"], kb["id"], ka["id"], "BUY", 999, 100000,
                 "2026-09-08T15:00:00Z")

    from test_helpers import create_fund, recompute_fund, component_of
    fund = create_fund(security["id"], "BANK")
    fund = recompute_fund(fund["id"], fund["version"])
    component = component_of(ka["id"], fund["id"], 1)
    assert component["component_amount_cents"] == 100 * 10000


def test_fully_funded_position_holds_the_funded_status_until_settlement():
    """PRD §3.6: "A position whose obligation has been fully funded but which has
    not yet been delivered or received holds the `FUNDED`
    delivery-versus-payment status until settlement resolves it."

    Design: Difficulty/dual_variant_calc/netting_net_vs_gross_position_convention
    """
    from test_helpers import fund_net_position, setup_netted_obligation

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="FND9", cusip="912828XG1", quantity=100, trade_price_cents=4000)
    funded = fund_net_position(obligation["id"], owner["id"],
                               obligation["settlement_obligation_cents"])
    assert funded["funded_amount_cents"] == obligation["settlement_obligation_cents"]
    assert funded["dvp_status"] == "FUNDED"