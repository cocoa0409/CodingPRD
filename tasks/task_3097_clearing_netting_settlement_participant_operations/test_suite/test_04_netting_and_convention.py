"""Multilateral netting, the net-versus-gross convention and cycle refresh."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_net_position, assert_net_position_invariants,
    set_clock, create_active_participant, create_security, create_window,
    submit_trade, lock_in, net_window, run_cycle, settle_window,
    setup_two_active_members, setup_security_and_window,
    setup_netting_convention_trades, net_position_of, member,
    locked_in_matched_trade, unresolved_long_position, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_net_position_uses_the_net_convention_for_cash_and_obligation():
    """PRD §3.5: "The netting convention is the settled convention: opposite-side
    trades combine into one net quantity and one signed cash leg, rather than the
    reporting convention that keeps a gross receive quantity and a gross deliver
    quantity apart."
    PRD §3.5: "The `settlement_obligation_cents` is the cash delta when the cash
    delta is positive and zero otherwise — funding is never required against a
    net receipt."

    Design: Difficulty/dual_variant_calc/netting_net_vs_gross_position_convention
    """
    a, b, security, window, trades = setup_netting_convention_trades()
    net_window(window["id"])

    position = net_position_of(a["id"], window["id"])
    assert_net_position(position)
    assert_net_position_invariants(position)
    assert position["net_quantity"] == 60
    assert position["cash_delta_cents"] == 240000
    assert position["settlement_obligation_cents"] == 240000


def test_net_convention_differs_from_the_gross_deliver_leg():
    """PRD §3.5: "The two conventions coincide on the net quantity but diverge on
    the obligation whenever a buy exists."

    Design: Difficulty/dual_variant_calc/netting_net_vs_gross_position_convention
    """
    a, b, security, window, trades = setup_netting_convention_trades()
    net_window(window["id"])
    position = net_position_of(a["id"], window["id"])

    net_quantity = position["net_quantity"]
    cash_delta = position["cash_delta_cents"]

    # The reporting convention would keep the deliver leg separate.
    gross_deliver_quantity = 40
    gross_deliver_obligation = gross_deliver_quantity * 4500

    assert net_quantity == 100 - 40
    assert cash_delta == 100 * 4200 - 40 * 4500
    assert position["settlement_obligation_cents"] == cash_delta
    assert position["settlement_obligation_cents"] != gross_deliver_obligation


def test_exactly_one_net_position_row_per_qualifying_participant():
    """PRD §3.5: "Running the cycle creates or replaces exactly one net position
    row per qualifying participant for the window".

    Design: Difficulty/dual_variant_calc/netting_net_vs_gross_position_convention
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("NET2", "912828XK9", 5000)
    # A carries the only LOCKED_IN row on the security: its mirror is pulled
    # out of the netting population by a dispute, so exactly one qualifying
    # participant owns a net position for the window.
    unresolved_long_position(security["id"], a, b, 100, 4200)
    net_window(window["id"])

    rows = validate_success(
        api_client.list_net_positions(ADMIN, params={"window_id": window["id"]}), 200)
    assert len(rows) == 1
    assert rows[0]["participant_id"] == a["id"]
    assert rows[0]["net_quantity"] == 100
    assert rows[0]["cash_delta_cents"] == 100 * 4200


def test_run_cycle_loops_the_window_open_and_bumps_its_version():
    """PRD §3.5: "Refreshing the cycle leaves the window `OPEN` so that the cycle
    may be run again — this is the self-loop the window's state machine
    describes."

    Design: Difficulty/non_linear_state_machine/settlement_window_cyclic_cycle_rerun_and_auto_close
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("WIN1", "912828XK7", 5000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 50, 4000)
    trade = lock_in(trade["id"], a["id"])

    ran = run_cycle(window["id"], window["version"])
    assert ran["status"] == "OPEN"
    assert ran["version"] > window["version"]


def test_stale_window_version_is_rejected_on_a_second_cycle_run():
    """PRD §2.9: "If the supplied value does not equal the parent entity's
    current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Difficulty/non_linear_state_machine/settlement_window_cyclic_cycle_rerun_and_auto_close
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("WIN1", "912828XK7", 5000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 50, 4000)
    trade = lock_in(trade["id"], a["id"])

    first = run_cycle(window["id"], window["version"])

    stale = api_client.run_cycle(
        window["id"], {"expected_window_version": window["version"]}, ADMIN)
    validate_error(stale, "ERR_STALE_VERSION")

    second = run_cycle(window["id"], first["version"])
    assert second["status"] == "OPEN"
    assert second["version"] > first["version"]


def test_settlement_window_created_in_open_state():
    """PRD §2.7: "The `status` field moves from `OPEN` to `NETTED` to `SETTLED`
    to `CLOSED`, and a window may also pass directly from `NETTED` to `CLOSED`
    without settling."
    PRD §2.7: "A settlement cycle is opened by a `PlatformAdmin` for one
    `security_id` and one `settlement_date`, with its `trade_entry_deadline` and
    `affirmation_deadline`."

    Design: Corner/state_machines/settlement_window_created_in_open_state
    """
    set_clock()
    security = create_security("INI1", "912828XS1", 5000)
    window = create_window(security["id"])
    assert window["status"] == "OPEN"
    assert window["version"] == 1
    assert window["security_id"] == security["id"]
    assert window["settlement_date"] == "2026-09-10"


def test_window_auto_closes_when_no_participant_is_active():
    """PRD §3.6: "When no participant at all remains `ACTIVE`, every `OPEN`
    window closes automatically".
    PRD §2.7: "The `status` field moves from `OPEN` to `NETTED` to `SETTLED` to
    `CLOSED`".

    Design: Corner/state_machines/window_auto_closed_when_no_active_participant
    """
    set_clock()
    # The auto-close is a system event, so the window is first opened while a
    # member is still ACTIVE and the last ACTIVE membership is then removed.
    member = create_active_participant("Auto Closed Co", "LEI-AUTO1", "BANK", 2000000000)
    security = create_security("AUT1", "912828XS5", 5000)

    window = create_window(security["id"])
    assert window["status"] == "OPEN"

    validate_success(api_client.suspend_participant(member["id"], ADMIN), 200)

    closed = validate_success(
        api_client.get_settlement_window(window["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    validate_error(api_client.net_window(window["id"], {}, ADMIN), "ERR_INVALID_STATE")


def test_settle_marks_net_positions_received_and_delivered_by_sign():
    """PRD §3.6: "each net position's delivery-versus-payment status `dvp_status`
    is resolved by the sign of its `net_quantity`: a positive net quantity is
    marked `RECEIVED`, a negative net quantity is marked `DELIVERED`".

    Design: Corner/endpoints/settle_marks_net_positions_received_and_delivered
    """
    a, b = setup_two_active_members(
        name_a="Dvp Alpha", name_b="Dvp Beta", lei_a="LEI-SA3", lei_b="LEI-SB3")
    security, window = setup_security_and_window("DVP1", "912828XU4", 5000)

    submit_trade(security["id"], a["id"], b["id"], "SELL", 100, 4000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4000)
    lock_in(trade["id"], a["id"])
    net_window(window["id"])

    long_row = net_position_of(a["id"], window["id"])
    from test_helpers import fund_net_position
    fund_net_position(long_row["id"], a["id"], long_row["settlement_obligation_cents"])

    settled = settle_window(window["id"])
    assert settled["status"] == "SETTLED"

    long_after = validate_success(api_client.get_net_position(long_row["id"], ADMIN), 200)
    assert long_after["dvp_status"] == "RECEIVED"

    short_row = net_position_of(b["id"], window["id"])
    assert short_row["net_quantity"] == -100
    assert short_row["settlement_obligation_cents"] == 0
    short_after = validate_success(api_client.get_net_position(short_row["id"], ADMIN), 200)
    assert short_after["dvp_status"] == "DELIVERED"


def test_empty_net_position_set_blocks_settlement():
    """PRD §3.6: "The window must own at least one net position row, or the
    attempt fails with `ERR_EMPTY_NET_POSITION_SET`."
    PRD §3.5: "Trades that are `ALLEGED` are excluded from the calculation".

    Design: Difficulty/boundary_precision_check/zero_net_position_set_boundary_on_empty_window
    """
    a, b = setup_two_active_members(
        name_a="Empty Alpha", name_b="Empty Beta", lei_a="LEI-EA", lei_b="LEI-EB")
    security, window = setup_security_and_window("EMP1", "912828XL4", 5000)

    # The comparison is resolved while both members are still ACTIVE, then B is
    # suspended: B's own row is cancelled and A's contra is swept to the
    # comparison status the suspension cascade assigns, so A's own book holds
    # no settled row and the window nets to nothing.
    submit_trade(security["id"], a["id"], b["id"], "SELL", 10, 4000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 10, 4000)
    trade = lock_in(trade["id"], b["id"])

    validate_success(api_client.suspend_participant(b["id"], ADMIN), 200)
    net_window(window["id"])

    rows = validate_success(
        api_client.list_net_positions(ADMIN, params={"window_id": window["id"]}), 200)
    assert rows == []

    validate_error(api_client.settle_window(window["id"], ADMIN),
                   "ERR_EMPTY_NET_POSITION_SET")
    still = validate_success(api_client.get_settlement_window(window["id"], ADMIN), 200)
    assert still["status"] == "NETTED"


def test_underfunded_obligation_blocks_settlement():
    """PRD §3.6: "Every net position of the window must have `funded_amount_cents`
    at or above its `settlement_obligation_cents`, or the attempt fails with
    `ERR_OBLIGATION_UNDERFUNDED`."

    Design: Corner/validations/unfunded_settlement_obligation_blocks_settlement
    """
    from test_helpers import setup_netted_obligation, fund_net_position

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="FUN1", cusip="912828XT2", quantity=100, trade_price_cents=4000)
    assert obligation["settlement_obligation_cents"] == 400000

    fund_net_position(obligation["id"], owner["id"], 300000)

    validate_error(api_client.settle_window(window["id"], ADMIN),
                   "ERR_OBLIGATION_UNDERFUNDED")
    after = validate_success(api_client.get_net_position(obligation["id"], ADMIN), 200)
    assert after["funded_amount_cents"] == 300000
    assert after["settlement_obligation_cents"] == 400000
    assert validate_success(
        api_client.get_settlement_window(window["id"], ADMIN), 200
    )["status"] == "NETTED"


def test_funding_to_exactly_the_obligation_is_accepted_and_capped():
    """PRD §3.6: "The funded amount saturates at the settlement obligation: a
    posting that would push `funded_amount_cents` above
    `settlement_obligation_cents` is refused with `ERR_FUNDING_EXCEEDS_OBLIGATION`".

    Design: Corner/validations/funding_exactly_at_obligation_is_accepted
    """
    from test_helpers import setup_netted_obligation, fund_net_position

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="SAT1", cusip="912828XT4", quantity=100, trade_price_cents=4000)
    assert obligation["settlement_obligation_cents"] == 400000

    funded = fund_net_position(obligation["id"], owner["id"], 400000)
    assert funded["funded_amount_cents"] == 400000

    validate_error(api_client.fund_net_position(
        obligation["id"], {"amount_cents": 1}, member(owner["id"])),
        "ERR_FUNDING_EXCEEDS_OBLIGATION")

    after = validate_success(api_client.get_net_position(obligation["id"], ADMIN), 200)
    assert after["funded_amount_cents"] == 400000
    assert after["settlement_obligation_cents"] == 400000


def test_zero_funding_amount_is_refused():
    """PRD §3.6: "a funding posting of zero, or a funding against a position
    whose `settlement_obligation_cents` is not positive, is refused with
    `ERR_INVALID_AMOUNT`."

    Design: Corner/errors/zero_amount_funding_rejected
    """
    from test_helpers import setup_netted_obligation

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="ZER1", cusip="912828XV2", quantity=100, trade_price_cents=4000)

    validate_error(api_client.fund_net_position(
        obligation["id"], {"amount_cents": 0}, member(owner["id"])),
        "ERR_INVALID_AMOUNT")
    assert validate_success(
        api_client.get_net_position(obligation["id"], ADMIN), 200
    )["funded_amount_cents"] == 0


def test_funding_visible_in_the_same_response():
    """PRD §3.6: "A `ClearingMember` funds one of its net positions — addressed
    through the `window_id` of the cycle that produced it — by supplying an
    `amount_cents`, which is added to the position's read-only
    `funded_amount_cents`."

    Design: Corner/cross_cutting_complexity_layers/immediate_consistency_funding_visible_in_same_response
    """
    from test_helpers import setup_netted_obligation, fund_net_position

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="IMM2", cusip="912828XV6", quantity=100, trade_price_cents=4000)

    response = fund_net_position(obligation["id"], owner["id"], 400000)
    assert response["funded_amount_cents"] == 400000
    assert response["settlement_obligation_cents"] == 400000