"""Trade submission, lock-in, comparison, disputes, reversals and cancellation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_trade_submission, create_trade_submission_payload,
    set_clock, create_active_participant, submit_trade, lock_in, net_window,
    setup_two_active_members, setup_security_and_window, member, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_trade_submission_starts_open_and_unmatched():
    """PRD §3.3: "The trade starts life `OPEN` and `UNMATCHED`, with
    `affirmation_status` placeholder-valued at `UNCONFIRMED` until the
    affirmation deadline for its settlement date is resolved."
    PRD §2.6: "A trade may therefore be `LOCKED_IN` while still `UNMATCHED`, or
    `MATCHED` while still `OPEN`; the dimensions are not locks on each other."

    Design: Difficulty/non_linear_state_machine/trade_submission_parallel_lock_and_match_dimensions
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("TRD1", "912828XK6", 5000)

    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4200)
    assert_trade_submission(trade)
    assert trade["lock_status"] == "OPEN"
    assert trade["match_status"] == "UNMATCHED"
    assert trade["version"] == 1
    assert trade["allegations_received"] == 0

    read = validate_success(api_client.get_trade_submission(trade["id"], ADMIN), 200)
    assert read["lock_status"] == "OPEN"
    assert read["match_status"] == "UNMATCHED"


def test_lock_in_moves_lock_status_without_touching_match_status():
    """PRD §3.3: "If no contra exists, the trade stays `UNMATCHED`."
    PRD §3.3: "When lock-in succeeds, `lock_status` becomes `LOCKED_IN` and
    comparison resolves the `match_status`."
    PRD §2.6: "A trade may therefore be `LOCKED_IN` while still `UNMATCHED`".

    Design: Difficulty/non_linear_state_machine/trade_submission_parallel_lock_and_match_dimensions
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("TRD1", "912828XK6", 5000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4200)

    locked = lock_in(trade["id"], a["id"])
    assert locked["lock_status"] == "LOCKED_IN"
    assert locked["match_status"] == "UNMATCHED"
    assert locked["version"] > trade["version"]


def test_lock_in_from_locked_in_is_refused():
    """PRD §3.3: "The trade must still be `OPEN`, or the attempt fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/trade_lockin_from_locked_in_rejected
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("IDM1", "912828XS3", 5000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 10, 4000)
    lock_in(trade["id"], a["id"])

    validate_error(api_client.lock_in_trade(trade["id"], member(a["id"])),
                   "ERR_INVALID_STATE")
    read = validate_success(api_client.get_trade_submission(trade["id"], ADMIN), 200)
    assert read["lock_status"] == "LOCKED_IN"


def test_lock_in_cascades_lock_to_the_contra_pair():
    """PRD §3.3: "When a trade becomes `MATCHED`, every one of those contra rows
    is also set to `LOCKED_IN` — even a contra that was still `OPEN`".
    PRD §3.3: "In every case `allegations_received` is recomputed as the count of
    non-`CANCELLED` contra rows matching that tuple."

    Design: Corner/state_machines/trade_lockin_from_locked_in_rejected
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("CAS0", "912828YX0", 5000)

    first = submit_trade(security["id"], b["id"], a["id"], "BUY", 10, 4000)
    assert first["lock_status"] == "OPEN"

    contra = submit_trade(security["id"], a["id"], b["id"], "SELL", 10, 4000)
    locked = lock_in(contra["id"], b["id"])
    assert locked["lock_status"] == "LOCKED_IN"
    assert locked["match_status"] == "MATCHED"

    first_after = validate_success(api_client.get_trade_submission(first["id"], ADMIN), 200)
    assert first_after["lock_status"] == "LOCKED_IN"
    assert first_after["match_status"] == "MATCHED"
    assert first_after["allegations_received"] == 1
    assert locked["allegations_received"] == 1


def test_cancel_locked_in_trade_by_admin_releases_the_contra():
    """PRD §3.4: "While a trade is `LOCKED_IN` or `DISPUTED`, only a
    `PlatformAdmin` may cancel it, and only while its settlement window is still
    `OPEN`".
    PRD §3.4: "Cancelling a `LOCKED_IN` trade reopens every non-`CANCELLED`
    contra row of the tuple that is not already cancelled to `OPEN` and
    `UNMATCHED`".

    Design: Corner/endpoints/trade_cancel_from_locked_in_reverted_by_admin
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("CAN1", "912828XU1", 5000)

    trade_a = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4000)
    trade_b = submit_trade(security["id"], a["id"], b["id"], "SELL", 100, 4000)
    trade_b = lock_in(trade_b["id"], b["id"])

    cancelled = validate_success(
        api_client.cancel_trade(trade_b["id"], ADMIN), 200)
    assert cancelled["lock_status"] == "CANCELLED"
    assert cancelled["match_status"] == "UNRESOLVED"

    contra_after = validate_success(
        api_client.get_trade_submission(trade_a["id"], ADMIN), 200)
    assert contra_after["lock_status"] == "OPEN"
    assert contra_after["match_status"] == "UNMATCHED"

    # A ClearingMember may not cancel a LOCKED_IN trade.
    a2, b2 = setup_two_active_members(
        name_a="Cancel Two Alpha", name_b="Cancel Two Beta",
        lei_a="LEI-CA4", lei_b="LEI-CB4")
    security2, window2 = setup_security_and_window("CAN2", "912828XU5", 5000)
    t2a = submit_trade(security2["id"], b2["id"], a2["id"], "BUY", 100, 4000)
    t2b = submit_trade(security2["id"], a2["id"], b2["id"], "SELL", 100, 4000)
    t2b = lock_in(t2b["id"], b2["id"])
    validate_error(api_client.cancel_trade(t2b["id"], member(b2["id"])),
                   "ERR_UNAUTHORIZED")


def test_unmatch_after_window_netted_reports_window_already_netted():
    """PRD §3.4: "an attempt once the window has left `OPEN` is refused with
    `ERR_WINDOW_ALREADY_NETTED`".

    Design: Corner/errors/netting_after_window_left_open_refused
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("WNT1", "912828XV1", 5000)
    trade = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4000)
    trade = lock_in(trade["id"], a["id"])
    net_window(window["id"])

    validate_error(api_client.unmatch_trade(trade["id"], ADMIN),
                   "ERR_WINDOW_ALREADY_NETTED")
    read = validate_success(api_client.get_trade_submission(trade["id"], ADMIN), 200)
    assert read["lock_status"] == "LOCKED_IN"


def test_unmatch_reverts_a_locked_in_pair_while_window_open():
    """PRD §3.4: "Reverting returns the trade to `OPEN` and `UNMATCHED` and
    applies the same to every non-`CANCELLED` contra row, recomputing
    `allegations_received` across the tuple."

    Design: Corner/errors/netting_after_window_left_open_refused
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("UMT1", "912828XV8", 5000)

    first = submit_trade(security["id"], b["id"], a["id"], "BUY", 100, 4000)
    contra = submit_trade(security["id"], a["id"], b["id"], "SELL", 100, 4000)
    locked = lock_in(contra["id"], b["id"])
    assert locked["lock_status"] == "LOCKED_IN"

    reverted = validate_success(api_client.unmatch_trade(locked["id"], ADMIN), 200)
    assert reverted["lock_status"] == "OPEN"
    assert reverted["match_status"] == "UNMATCHED"

    first_after = validate_success(
        api_client.get_trade_submission(first["id"], ADMIN), 200)
    assert first_after["lock_status"] == "OPEN"
    assert first_after["match_status"] == "UNMATCHED"


def test_trade_submission_unknown_security_returns_security_not_found():
    """PRD §2.11: "a security identifier that does not resolve is reported as
    `ERR_SECURITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/unknown_security_on_trade_submission_returns_not_found
    """
    set_clock()
    participant = create_active_participant("NotFound Co", "LEI-NF2")
    payload = create_trade_submission_payload(
        "11111111-1111-4111-8111-111111111111", participant["id"], side="BUY",
        quantity=1, trade_price_cents=1)
    res = api_client.create_trade_submission(payload, member(participant["id"]))
    validate_error(res, "ERR_SECURITY_NOT_FOUND", expected_status=404)