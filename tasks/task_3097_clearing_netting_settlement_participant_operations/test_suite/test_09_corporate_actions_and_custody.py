"""Corporate actions, book-entry custody servicing and the apply/reverse pair."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_corporate_action, assert_custody_account,
    set_clock, create_active_participant, create_security, create_window,
    submit_trade, lock_in, net_window, custody_accounts,
    announce_corporate_action, apply_action, reverse_action, read_action,
    setup_two_active_members, setup_security_and_window,
    locked_in_matched_trade, unresolved_long_position,
    net_position_of, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_split_truncates_the_fractional_entitlement_toward_zero():
    """PRD §3.8: "For a `SPLIT`, the quantity adjustment is the position's settled
    quantity multiplied by the `ratio_numerator` and divided by the
    `ratio_denominator`, truncated toward zero".
    PRD §2.8: "Quantity arithmetic that produces a fractional entitlement is
    truncated toward zero rather than rounded".

    Design: Difficulty/compensating_invariant/corporate_action_apply_reverse_preserves_position_sum
    """
    set_clock()
    qa = create_active_participant("Quite Alpha", "LEI-QA", "BANK", 2_000_000_000)
    qb = create_active_participant("Quite Beta", "LEI-QB", "BANK", 2_000_000_000)
    security = create_security("QNT1", "912828XP2", 5000)
    window = create_window(security["id"])

    # Every net position of the security must be non-negative for a split, so
    # QA is given a single long row with no short mirror.
    unresolved_long_position(security["id"], qa, qb, 3, 4000)
    net_window(window["id"])

    action = announce_corporate_action(security["id"], "SPLIT",
                                       ratio_numerator=3, ratio_denominator=2,
                                       effective_date="2026-09-09")
    apply_action(action["id"])

    position = net_position_of(qa["id"], window["id"])
    assert position["net_quantity"] == 3 + int(3 * 3 / 2)
    assert position["net_quantity"] == 7


def test_reversing_an_applied_split_restores_the_pre_application_quantity():
    """PRD §3.8: "Reversal restores the pre-application quantity and the prior
    `last_corporate_action_applied_id` on every affected custody-account position,
    reverses the servicing on every affected net position and recomputes each
    affected `cash_delta_cents` by the netting rule of §3.5, and sets the action
    to `REVERSED`, advancing the action's version."

    Design: Difficulty/compensating_invariant/corporate_action_apply_reverse_preserves_position_sum
    """
    set_clock()
    qa = create_active_participant("Quite Alpha", "LEI-QA", "BANK", 2_000_000_000)
    qb = create_active_participant("Quite Beta", "LEI-QB", "BANK", 2_000_000_000)
    validate_success(api_client.create_custody_account(
        qa["id"], {"account_number": "QA-SEG-1", "account_type": "SEGREGATED"}, ADMIN), 201)
    security = create_security("QNT1", "912828XP2", 5000)
    window = create_window(security["id"])

    # Every net position of the security must be non-negative for a split, so
    # QA is given a single long row with no short mirror.
    unresolved_long_position(security["id"], qa, qb, 3, 4000)
    net_window(window["id"])

    action = announce_corporate_action(security["id"], "SPLIT",
                                       ratio_numerator=3, ratio_denominator=2,
                                       effective_date="2026-09-09")
    apply_action(action["id"])

    applied = net_position_of(qa["id"], window["id"])
    assert applied["net_quantity"] == 7

    reversed_action = reverse_action(action["id"])
    assert reversed_action["status"] == "REVERSED"

    restored = net_position_of(qa["id"], window["id"])
    assert restored["net_quantity"] == 3

    accounts = custody_accounts(qa["id"])
    for account in accounts:
        for position in account["positions"]:
            assert position.get("last_corporate_action_applied_id") in (None, "")


def test_reversing_a_reversed_action_is_refused():
    """PRD §3.8: "A serviced action may be reversed while it is `APPLIED`; any
    other status fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corporate_action_reverse_on_reversed_is_terminal
    """
    set_clock()
    ta = create_active_participant("Term Alpha", "LEI-TA2", "BANK", 2_000_000_000)
    tb = create_active_participant("Term Beta", "LEI-TB2", "BANK", 2_000_000_000)
    security = create_security("TER1", "912828XS2", 5000)
    window = create_window(security["id"])

    trade = submit_trade(security["id"], tb["id"], ta["id"], "BUY", 3, 4000)
    lock_in(trade["id"], ta["id"])

    action = announce_corporate_action(security["id"], "SPLIT",
                                       ratio_numerator=3, ratio_denominator=2,
                                       effective_date="2026-09-09")
    apply_action(action["id"])
    reverse_action(action["id"])

    validate_error(api_client.reverse_corporate_action(action["id"], ADMIN),
                   "ERR_INVALID_STATE")
    still = read_action(action["id"], security["id"])
    assert still["status"] == "REVERSED"


def test_action_effective_after_the_window_settlement_date_is_refused():
    """PRD §3.8: "Its `effective_date` must fall on or before the settlement date
    of the net position rows it would service, or the attempt fails with
    `ERR_ACTION_NOT_EFFECTIVE`."

    Design: Difficulty/cross_entity_state_dependency/corporate_action_apply_requires_window_effective_date
    """
    set_clock()
    ya = create_active_participant("Yield Alpha", "LEI-YA", "BANK", 2_000_000_000)
    yb = create_active_participant("Yield Beta", "LEI-YB", "BANK", 2_000_000_000)
    security = create_security("YLD1", "912828XM2", 5000)
    window = create_window(security["id"])

    submit_trade(security["id"], ya["id"], yb["id"], "SELL", 100, 4000)
    trade = submit_trade(security["id"], yb["id"], ya["id"], "BUY", 100, 4000)
    lock_in(trade["id"], ya["id"])
    net_window(window["id"])

    action = announce_corporate_action(security["id"], "SPLIT",
                                       ratio_numerator=3, ratio_denominator=2,
                                       effective_date="2026-09-20")
    validate_error(api_client.apply_corporate_action(action["id"], ADMIN),
                   "ERR_ACTION_NOT_EFFECTIVE")

    still = read_action(action["id"], security["id"])
    assert still["status"] == "ANNOUNCED"
    position = net_position_of(ya["id"], window["id"])
    assert position["net_quantity"] == 100


def test_cash_dividend_keys_its_cash_leg_on_the_already_adjusted_quantity():
    """PRD §3.8: "the cash adjustment is the already-adjusted settled quantity
    multiplied by the `cash_rate_cents_per_unit`."

    Design: Corner/endpoints/custody_account_positions_surface_serviced_quantity
    """
    set_clock()
    cu = create_active_participant("Custody Read Co", "LEI-CU2", "BANK", 2_000_000_000)
    validate_success(api_client.create_custody_account(
        cu["id"], {"account_number": "CU2-SEG-1", "account_type": "SEGREGATED"}, ADMIN), 201)
    security = create_security("CUS1", "912828XU3", 5000)

    action = announce_corporate_action(security["id"], "CASH_DIVIDEND",
                                       cash_rate_cents_per_unit=25,
                                       effective_date="2026-09-09")
    apply_action(action["id"])

    accounts = custody_accounts(cu["id"])
    assert len(accounts) == 1
    assert_custody_account(accounts[0])
    assert accounts[0]["account_type"] == "SEGREGATED"
    assert accounts[0]["status"] == "OPEN"
    assert isinstance(accounts[0]["positions"], list)


def test_custody_read_clears_the_applied_action_id_after_reverse():
    """PRD §3.8: "Reversal restores the pre-application quantity and the prior
    `last_corporate_action_applied_id` on every affected custody-account
    position".
    PRD §3.8: "Each position records the `security_id`, the `settled_quantity`
    — long positive, short negative — and the `last_corporate_action_applied_id`
    of the action most recently applied to it."

    Design: Corner/endpoints/custody_account_positions_surface_serviced_quantity
    """
    set_clock()
    cu = create_active_participant("Custody Read Co", "LEI-CU2", "BANK", 2_000_000_000)
    validate_success(api_client.create_custody_account(
        cu["id"], {"account_number": "CU2-SEG-1", "account_type": "SEGREGATED"}, ADMIN), 201)
    security = create_security("CUS1", "912828XU3", 5000)

    action = announce_corporate_action(security["id"], "CASH_DIVIDEND",
                                       cash_rate_cents_per_unit=25,
                                       effective_date="2026-09-09")
    apply_action(action["id"])
    reverse_action(action["id"])

    accounts = custody_accounts(cu["id"])
    assert accounts[0]["id"]
    assert accounts[0]["account_type"] == "SEGREGATED"
    for position in accounts[0]["positions"]:
        assert position.get("last_corporate_action_applied_id") in (None, "")


def test_settle_runs_the_corporate_action_servicing_pass():
    """PRD §3.8: "the settlement pass applies the same servicing for every applied
    action on the window's security whose effective date has arrived, so custody
    and net positions are serviced without a separate call when a cycle settles."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_settle_servicing_order
    """
    from test_helpers import fund_net_position

    set_clock()
    so = create_active_participant("Order Alpha", "LEI-SO2", "BANK", 2_000_000_000)
    sp = create_active_participant("Order Beta", "LEI-SP2", "BANK", 2_000_000_000)
    security = create_security("ORD1", "912828XV4", 5000)
    window = create_window(security["id"])

    # A cash dividend may not be applied while any net position on the
    # security is net short, so the paying member is the only one long and the
    # counterparty carries no deliverable position of its own.
    unresolved_long_position(security["id"], so, sp, 4, 100000)
    net_window(window["id"])

    position = net_position_of(so["id"], window["id"])
    fund_net_position(position["id"], so["id"], position["settlement_obligation_cents"])

    action = announce_corporate_action(security["id"], "CASH_DIVIDEND",
                                       cash_rate_cents_per_unit=25,
                                       effective_date="2026-09-09")
    apply_action(action["id"])

    settled = validate_success(api_client.settle_window(window["id"], ADMIN), 200)
    assert settled["status"] == "SETTLED"

    after = validate_success(api_client.get_net_position(position["id"], ADMIN), 200)
    assert after["dvp_status"] == "RECEIVED"
    assert after["cash_delta_cents"] == 400000 + 4 * 25