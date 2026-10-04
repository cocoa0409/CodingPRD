"""Draw windows, entry controls, ranking, claiming and forfeiture."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_one_entry_per_person_per_draw_is_a_hard_rule(api):
    """PRD §3.7: "One entry per person per draw is a hard rule: a patron may not
    hold a second entry for the same allocation unless the earlier one has been
    `CANCELLED`, and a duplicate attempt is refused with
    `ERR_DUPLICATE_DRAW_ENTRY` (HTTP 409)."

    Design: Corner/endpoints/claim_a_non_winner_entry_reports_invalid_state
    """
    production, performance, allocation = X.setup_released_draw_allocation()
    patron = X.register_patron(email="duplicate_entry@example.com")
    X.file_draw_entry(performance, allocation, patron)

    response = api.create_draw_entry(
        performance["id"],
        {"allocation_id": allocation["id"],
         "declaration_text": "I would like to attend"},
        X.patron_headers(patron),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DRAW_ENTRY, expected_status=409)


def test_claiming_an_entry_that_is_not_a_winner_is_refused(api):
    """PRD §3.8: "The patron must be the entry's own `patron_id`, must be acting
    under their own identity, and must act while the win is live."
    PRD §2.6: "Second, the transition test: the target row must be in a state from
    which the requested move is defined, and a row that is not receives
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/claim_a_non_winner_entry_reports_invalid_state
    """
    production, performance, allocation = X.setup_released_draw_allocation(
        daily_quantity=1, waitlist_multiplier=1, per_order_limit=1,
    )
    winner = X.register_patron(email="claim_win@example.com")
    waiter = X.register_patron(email="claim_wait@example.com")
    X.file_draw_entry(performance, allocation, winner)
    waitlisted = X.file_draw_entry(performance, allocation, waiter)
    X.execute_draw(allocation, at="2026-09-12T09:05:00Z")

    entry = X.get_entry(performance, waitlisted["id"])
    assert entry["status"] == "WAITLISTED", \
        f"the second entrant must be waitlisted, got {entry['status']}"

    response = api.claim_draw_entry(
        entry["id"],
        {"quantity": 1, "expected_draw_entry_version": entry["version"]},
        X.patron_headers(waiter),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    unchanged = X.get_entry(performance, waitlisted["id"])
    assert unchanged["status"] == "WAITLISTED", \
        "the rejected claim must leave the entry waitlisted"
    assert unchanged["purchase_id"] is None, \
        "no order may be created for a rejected claim"
    purchases = get_success_data(api.list_purchases(
        X.PRODUCER, params={"performance_id": performance["id"], "limit": 100}))
    purchases = purchases.get("data", purchases) if isinstance(purchases, dict) else purchases
    assert len(purchases) == 0, \
        "the rejected claim created no purchase"


def test_a_lapsed_claim_deadline_is_refused_while_the_win_is_live(api):
    """PRD §3.8: "at or after the claim deadline the claim is refused with
    `ERR_CLAIM_DEADLINE_PASSED` (HTTP 409)."
    PRD §3.8: "The sweep at an operational epoch looks for entries still in
    `WINNER` whose claim deadline has been reached, and moves each of them to
    `FORFEITED`."

    Design: Corner/errors/error_claim_deadline_passed_before_the_forfeit_sweep_runs
    """
    production, performance, allocation = X.setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=30, waitlist_multiplier=0,
        per_order_limit=1,
    )
    patron = X.register_patron(email="late_claimer@example.com")
    X.file_draw_entry(performance, allocation, patron)
    X.execute_draw(allocation, at="2026-09-12T09:05:00Z")
    X.set_clock("2026-09-12T09:40:00Z")

    entry = X.get_entry(performance, X.list_entries(performance)[0]["id"])
    assert entry["status"] == "WINNER", \
        "no operational epoch has forfeited the entry yet"
    assert entry["claim_deadline_at"] == "2026-09-12T09:35:00.000Z", (
        f"the deadline is the notification instant plus thirty minutes, got {entry['claim_deadline_at']}"
    )

    response = api.claim_draw_entry(
        entry["id"],
        {"quantity": 1, "expected_draw_entry_version": entry["version"]},
        X.patron_headers(patron),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_DEADLINE_PASSED, expected_status=409)


def test_a_win_at_exactly_its_deadline_is_already_a_lapse(api):
    """PRD §3.8: "a win at exactly its deadline is already a lapse."
    PRD §3.12: "An entry in `WINNER` whose claim deadline still lies in the future
    contributes nothing, but an entry in `WINNER` whose claim deadline has been
    reached does contribute — note the boundary, a win at exactly its deadline is
    already a lapse."

    Design: Corner/errors/error_claim_deadline_passed_before_the_forfeit_sweep_runs
    """
    production, performance, allocation = X.setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=30, waitlist_multiplier=0,
        per_order_limit=1,
    )
    patron = X.register_patron(email="deadline_claimer@example.com")
    X.file_draw_entry(performance, allocation, patron)
    X.execute_draw(allocation, at="2026-09-12T09:05:00Z")
    X.set_clock("2026-09-12T09:35:00Z")

    entry = X.get_entry(performance, X.list_entries(performance)[0]["id"])
    response = api.claim_draw_entry(
        entry["id"],
        {"quantity": 1, "expected_draw_entry_version": entry["version"]},
        X.patron_headers(patron),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_DEADLINE_PASSED, expected_status=409)


def test_an_empty_eligible_pool_refuses_to_resolve_a_winner_set(api):
    """PRD §3.8: "If the eligible set is empty — no `ENTERED` entry with an
    `ACTIVE` patron — the execution fails with `ERR_DRAW_NO_ELIGIBLE_ENTRIES`
    (HTTP 409)."

    Design: Corner/errors/error_draw_no_eligible_entries_when_every_entrant_is_blocked
    """
    production, performance, allocation, entrant, entry = \
        X.setup_blocked_draw_pool(claim_window_minutes=60)

    withdrawn = X.get_entry(performance, entry["id"])
    assert withdrawn["status"] == "CANCELLED", (
        "the entry was withdrawn by the block rather than left ENTERED, got "
        f"{withdrawn['status']}"
    )

    response = api.execute_draw(
        allocation["id"],
        {"expected_allocation_version": X.live_allocation(performance,
                                                          allocation)["version"]},
        X.OPS,
    )
    validate_error(response, ApiErrorId.ERR_DRAW_NO_ELIGIBLE_ENTRIES, expected_status=409)
    rows = get_success_data(api.list_draw_entries(
        performance["id"], X.OPS, params={"limit": 100}))
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    assert not any(row["status"] == "WINNER" for row in rows), \
        "no entry of the allocation may be a winner"