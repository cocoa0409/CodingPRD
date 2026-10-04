"""Fail management: the daily mark-to-market on failed net positions."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_net_position,
    set_clock, create_active_participant, create_security, create_window,
    submit_trade, lock_in, net_window, fund_net_position,
    setup_two_active_members, setup_security_and_window,
    book_fresh_long_on_a_new_cycle,
    net_position_of, member, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_suspension_fails_the_members_net_position_and_stamps_the_basis_price():
    """PRD §3.1: "Every net position belonging to the member that is not already
    `FAILED` is marked `FAILED`, with `failed_at` stamped at the current logical
    clock, `failed_at_price_cents` taken from the security's
    `prev_settlement_price_cents` at that instant".

    Design: Difficulty/dual_variant_calc/fail_mark_forward_vs_prior_day_mark
    """
    set_clock()
    a, b = setup_two_active_members(name_a="Mark Alpha", name_b="Mark Beta",
                                    lei_a="LEI-MA", lei_b="LEI-MB")
    security, window = setup_security_and_window("MRK1", "912828XK3", 5000)
    submit_trade(security["id"], a["id"], b["id"], "SELL", 10, 4000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 10, 4000)
    lock_in(trade["id"], a["id"])
    net_window(window["id"])

    validate_success(api_client.suspend_participant(a["id"], ADMIN), 200)

    failed = net_position_of(a["id"], window["id"])
    assert_net_position(failed)
    assert failed["dvp_status"] == "FAILED"
    assert failed["failed_at_price_cents"] == 5000
    assert failed["failed_at"] is not None


def test_mark_to_market_only_recomputes_the_signed_mark_without_moving_funds():
    """PRD §3.7: "The mark is the signed failed quantity multiplied by that price
    move, with the single product rounded half up to a whole cent."
    PRD §3.6: "In that mode the call performs only the fail mark recomputation of
    §3.7 and does not move any funds."

    Design: Difficulty/dual_variant_calc/fail_mark_forward_vs_prior_day_mark
    """
    set_clock()
    a, b = setup_two_active_members(name_a="Mark Alpha", name_b="Mark Beta",
                                    lei_a="LEI-MA", lei_b="LEI-MB")
    security, window = setup_security_and_window("MRK1", "912828XK3", 5000)
    submit_trade(security["id"], b["id"], a["id"], "SELL", 10, 4000)
    trade = submit_trade(security["id"], a["id"], b["id"], "BUY", 10, 4000)
    lock_in(trade["id"], a["id"])
    net_window(window["id"])
    validate_success(api_client.suspend_participant(a["id"], ADMIN), 200)
    validate_success(api_client.reinstate_participant(a["id"], ADMIN), 200)
    # The suspension cancelled A's own rows, so the fail mark needs a fresh
    # locked-in long booked after reinstatement.
    book_fresh_long_on_a_new_cycle(security["id"], a, b, 10, 4000)

    failed = net_position_of(a["id"], window["id"])
    assert failed["failed_at_price_cents"] == 5000

    validate_success(api_client.update_security(
        security["id"], {"prev_settlement_price_cents": 3000}, ADMIN), 200)

    marked = fund_net_position(failed["id"], a["id"], 0, mark_to_market_only=True)
    assert marked["mark_to_market_cents"] == -20000
    assert marked["funded_amount_cents"] == 0


def test_prior_day_mark_convention_would_report_zero():
    """PRD §3.7: "A price fall makes a net-long fail report a negative mark, which
    is the risk convention the house uses; the reconciliation convention, which
    marks every fail at zero, is not the rule."

    Design: Difficulty/dual_variant_calc/fail_mark_forward_vs_prior_day_mark
    """
    set_clock()
    a, b = setup_two_active_members(name_a="Mark Alpha", name_b="Mark Beta",
                                    lei_a="LEI-MA", lei_b="LEI-MB")
    security, window = setup_security_and_window("MRK2", "912828XKA", 5000)
    submit_trade(security["id"], b["id"], a["id"], "SELL", 10, 4000)
    trade = submit_trade(security["id"], a["id"], b["id"], "BUY", 10, 4000)
    lock_in(trade["id"], a["id"])
    net_window(window["id"])
    validate_success(api_client.suspend_participant(a["id"], ADMIN), 200)
    validate_success(api_client.reinstate_participant(a["id"], ADMIN), 200)
    book_fresh_long_on_a_new_cycle(security["id"], a, b, 10, 4000)

    validate_success(api_client.update_security(
        security["id"], {"prev_settlement_price_cents": 3000}, ADMIN), 200)
    failed = net_position_of(a["id"], window["id"])

    marked = fund_net_position(failed["id"], a["id"], 0, mark_to_market_only=True)
    signed_failed_qty = 10
    price_move = 3000 - failed["failed_at_price_cents"]
    assert marked["mark_to_market_cents"] == signed_failed_qty * price_move
    assert marked["mark_to_market_cents"] != 0


def test_trade_submission_requires_an_active_member():
    """PRD §3.3: "Only a member whose `membership_status` is `ACTIVE` may submit:
    a member that is `SUSPENDED`, `DEFAULTED` or `EXPELLED` is refused with
    `ERR_PARTICIPANT_NOT_ACTIVE`".

    Design: Corner/rbac/clearing_member_well_formed_role_wrong_operation_forbidden
    """
    set_clock()
    a, b = setup_two_active_members(
        name_a="Susp Alpha", name_b="Susp Beta", lei_a="LEI-XX1", lei_b="LEI-XX2")
    security, window = setup_security_and_window("SUSP1", "912828XY1", 5000)

    validate_success(api_client.suspend_participant(a["id"], ADMIN), 200)

    res = api_client.create_trade_submission(
        {"counterparty_participant_id": b["id"], "security_id": security["id"],
         "side": "BUY", "quantity": 1, "trade_price_cents": 100,
         "trade_date": "2026-09-08T14:00:00Z"},
        member(a["id"]))
    validate_error(res, "ERR_PARTICIPANT_NOT_ACTIVE")


def test_clearing_member_cannot_recompute_a_clearing_fund():
    """PRD §2.1: "`RiskOfficer` owns financial-standard reviews, clearing-fund
    establishment and sizing".
    PRD §2.1: "is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/clearing_member_well_formed_role_wrong_operation_forbidden
    """
    from test_helpers import create_fund

    set_clock()
    a = create_active_participant("Role Wrong Co", "LEI-RM2")
    security = create_security("RLW1", "912828XV7", 5000)
    fund = create_fund(security["id"], "BANK")

    res = api_client.recompute_clearing_fund(
        fund["id"], {"expected_fund_version": fund["version"]}, member(a["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")

    rows = validate_success(api_client.list_fund_components(fund["id"], ADMIN), 200)
    assert rows == []

    ok = validate_success(api_client.recompute_clearing_fund(
        fund["id"], {"expected_fund_version": fund["version"]},
        TEST_USERS["risk_officer_headers"]), 200)
    assert ok["status"] == "RECOMPUTED"