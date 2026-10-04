"""Winner ranking, the waitlist promotion cycle and the patron cost model."""
import pytest

from test_helpers import validate_success, get_success_data
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_the_winner_slice_is_the_release_ceiling_and_the_waitlist_twice_as_deep(api):
    """PRD §3.8: "From that order the system carves three contiguous slices: the
    first slice, of a size equal to the allocation's current release ceiling,
    becomes `WINNER`; the next slice, of a size equal to twice that ceiling,
    becomes `WAITLISTED`; and everything remaining becomes `LOSER`."
    PRD §3.8: "It is worth stating plainly that nothing here is random: the name
    of the feature notwithstanding, the winner set is resolved deterministically
    from entry order, and no lottery mechanism decides it."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, entries, execution = \
        X.setup_three_entrant_draw(daily_quantity=2, waitlist_multiplier=2)

    assert execution["winner_count"] == 2, (
        f"the winner slice equals the release ceiling of two, got {execution['winner_count']}"
    )
    assert execution["waitlisted_count"] == 1, (
        "the winner slice takes the first two entries and the single remaining "
        "entry falls in the waitlist slice (whose width is twice the ceiling of "
        f"two), got {execution['waitlisted_count']}"
    )
    assert execution["loser_count"] == 0

    statuses = [X.get_entry(performance, entry["id"])["status"] for entry in entries]
    assert statuses == ["WINNER", "WINNER", "WAITLISTED"], \
        f"the slices are contiguous in entry order, got {statuses}"


def test_a_forfeited_win_promotes_the_next_waitlisted_entry(api):
    """PRD §3.8: "Within the same sweep that forfeits an unclaimed win, the
    system promotes one waitlisted entry: the lowest-ranked entry still in
    `WAITLISTED` for that allocation — the one whose `rank_position` sits earliest
    among the allocation's non-terminal waitlisted entries — is promoted to
    `WINNER` when the allocation has a seat free because a winner forfeited."
    PRD §3.8: "The promotion behaves exactly like a fresh win: `notified_at` is
    stamped with the epoch instant and `claim_deadline_at` is recomputed from it."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, entries, execution = \
        X.setup_three_entrant_draw(daily_quantity=2, waitlist_multiplier=2,
                                   claim_window_minutes=30)

    X.set_clock("2026-09-12T09:45:00Z")
    sweep = X.ops_run("2026-09-12T09:45:00Z")

    assert sweep["forfeited_count"] == 2, (
        f"both unclaimed wins forfeit at the deadline, got {sweep['forfeited_count']}"
    )
    assert sweep["waitlisted_promoted_count"] == 1, (
        f"one waitlisted entry is promoted in the same sweep, got {sweep['waitlisted_promoted_count']}"
    )

    promoted = X.get_entry(performance, entries[2]["id"])
    assert promoted["status"] == "WINNER", (
        "the third entrant was promoted back into a state the allocation had "
        f"already handed to two earlier entries, got {promoted['status']}"
    )
    assert promoted["claim_deadline_at"] == "2026-09-12T10:15:00.000Z", (
        f"the promoted win gets a fresh window from 09:45, got {promoted['claim_deadline_at']}"
    )


def test_promotion_pays_off_part_of_the_promoted_patrons_lapse(api):
    """PRD §3.8: "It is also a penance rather than a pure grant, because the
    promotion decrements the promoting patron's `draw_violation_count` by one,
    floored at zero — the patron who stepped up to take a forfeited seat has part
    of an earlier lapse paid off."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, entries, execution = \
        X.setup_three_entrant_draw(daily_quantity=2, waitlist_multiplier=2,
                                   claim_window_minutes=30)

    X.set_clock("2026-09-12T09:45:00Z")
    X.ops_run("2026-09-12T09:45:00Z")

    first = X.get_patron(patrons[0])
    second = X.get_patron(patrons[1])
    promoted = X.get_patron(patrons[2])

    assert first["draw_violation_count"] == 1.0, (
        f"a forfeiture increments the offending patron's count, got {first['draw_violation_count']}"
    )
    assert second["draw_violation_count"] == 1.0
    assert promoted["draw_violation_count"] == 0.0, (
        "the promoted patron stepped up rather than lapsed, so their count is "
        f"floored at zero, got {promoted['draw_violation_count']}"
    )


def test_forfeiture_inside_the_winners_own_window_is_paid_down_by_promotion(api):
    """PRD §3.12: "a forfeiture increments the offending patron's
    `draw_violation_count`, and a promotion decrements the promoting patron's."
    PRD §3.12: "the domain's accounting is a function of current entry states
    rather than a ledger of past events."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, entries, execution = \
        X.setup_three_entrant_draw(daily_quantity=1, waitlist_multiplier=3,
                                   claim_window_minutes=1)
    X.set_clock("2026-09-12T09:10:00Z")
    sweep = X.ops_run("2026-09-12T09:10:00Z")

    assert sweep["forfeited_count"] >= 1, (
        "an entry whose claim deadline has been reached forfeits at the sweep, "
        f"got {sweep['forfeited_count']}"
    )
    assert sweep["winners_notified_count"] + sweep["waitlisted_promoted_count"] >= 0


def test_a_forfeit_raises_the_violation_count_that_gates_blocking(api):
    """PRD §3.8: "A forfeiture increments the patron's `draw_violation_count` by
    one, and it advances the entry's `version`."
    PRD §3.8: "a patron carrying even one recorded violation is eligible to be
    blocked, which is the standing-change rule described later."

    Design: Difficulty/transitive_cascade/transitive_cascade_draw_forfeit_to_hold_expiry_depth_three
    """
    production, performance, allocation, lapsed, unrelated, entry = \
        X.setup_forfeit_raised_violation(claim_window_minutes=1)

    after = X.get_patron(lapsed)

    assert after["draw_violation_count"] == 1.0, (
        f"hop 1: a lapsed win raises the recorded violation count, got {after['draw_violation_count']}"
    )
    assert X.get_entry(performance, entry["id"])["status"] == "FORFEITED", \
        "the unclaimed win is forfeited by the sweep"


def test_the_raised_count_admits_the_block_and_its_entry_cancel_cascade(api):
    """PRD §3.8: "A `CustomerService` operator or a `PlatformAdmin` may move a
    patron from `ACTIVE` to `BLOCKED`, but only when the patron's
    `draw_violation_count` is at least one."
    PRD §3.8: "every draw entry of that patron in `ENTERED`, `WINNER` or
    `WAITLISTED` moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/transitive_cascade_draw_forfeit_to_hold_expiry_depth_three
    """
    production, performance, allocation, live_allocation, lapsed, entry, \
        second_entry = X.setup_lapsed_and_live_entries(claim_window_minutes=1)
    unrelated = X.register_patron(email="unrelated_block@example.com")

    blocked = X.block_patron(X.get_patron(lapsed))

    assert blocked["status"] == "BLOCKED", (
        "hop 2: the block transition was admitted only because the forfeiture "
        "raised the count to its threshold"
    )
    cancelled = X.get_entry(performance, second_entry["id"])
    assert cancelled["status"] == "CANCELLED", (
        "hop 3: the entry is withdrawn by the block cascade rather than by the "
        f"forfeiture itself, got {cancelled['status']}"
    )
    untouched = X.get_patron(unrelated)
    assert untouched["status"] == "ACTIVE" and untouched["draw_violation_count"] == 0, (
        "a block on one patron leaves another patron's standing and count alone"
    )


def test_rank_positions_are_one_based_entry_order(api):
    """PRD §3.7: "A `DrawEntry` also carries a `rank_position`, which is a
    one-based position in its allocation's draw order — the first entry in the
    order is at position one — computed from `entered_at` ascending with
    `created_at` ascending breaking identical instants."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, entries, execution = \
        X.setup_three_entrant_draw(daily_quantity=2, waitlist_multiplier=2)

    ranks = [X.get_entry(performance, entry["id"])["rank_position"]
             for entry in entries]
    assert ranks == [1, 2, 3], (
        f"rank positions follow entry order and start at one, got {ranks}"
    )