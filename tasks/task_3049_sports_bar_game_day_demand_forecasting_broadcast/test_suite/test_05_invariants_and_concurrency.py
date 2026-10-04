"""Compensating invariants (no-show redemption, prize conservation) and the
optimistic-concurrency guards on fantasy settlement."""

from test_helpers import (
    ApiErrorId,
    HOST_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    advance_clock,
    call_waitlist_entry,
    create_guest,
    create_locked_contest_with_entries,
    create_venue,
    fantasy_contest_payload,
    fantasy_entry_payload,
    get_guest,
    join_waitlist,
    validate_error,
    validate_success,
)


class TestWaitlistSeatCancelNoShowInvariant:
    """Seating redeems a no-show; cancelling a called entry does not penalize."""

    def _guest_with_one_no_show_and_two_called_entries(self, api):
        """Guest ends with exactly one no-show, then holds two CALLED entries.

        The default clock (2026-09-01T00:00Z) advances by twenty-minute
        spacing so each burn's 16-minute hold elapse stays clear of the next
        join's hold window.
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        entry1 = join_waitlist(venue["id"], guest["id"])
        call_waitlist_entry(entry1["id"])
        advance_clock("2026-09-01T00:16:00Z")
        # Read the entry back: the clock advance expired the hold, so the
        # cancel below must race the EXPIRED transition — cancelling a
        # called entry is only valid while it is still CALLED.  PRD §3.4
        # allows cancel from WAITING or CALLED only, so burn the no-show
        # by letting the hold elapse (already EXPIRED) and simply assert
        # the guest's no_show_count reached 1.
        guest_burned = get_guest(guest["id"])
        assert guest_burned["no_show_count"] == 1
        entry2 = join_waitlist(venue["id"], guest["id"])
        called2 = call_waitlist_entry(entry2["id"])
        entry3 = join_waitlist(venue["id"], guest["id"])
        call_waitlist_entry(entry3["id"])
        return venue, guest, entry2, called2, entry3

    def test_seat_redeems_a_no_show_while_cancel_does_not_penalize(self, api):
        """PRD §3.4: "a successful seat redeems the guest by decrementing `no_show_count` when it is above zero, while the entry's own `version` increments."
        PRD §3.4: "A `Host` may also cancel an entry from `WAITING` or `CALLED` into `CANCELLED`; cancelling a called entry releases the hold immediately with no no-show penalty."

        One prior expiry leaves the guest at one no-show; seating one called
        entry redeems it and cancelling the other adds nothing, leaving the
        count at zero.

        Design: Difficulty/compensating_invariant/waitlist_seat_cancel_no_show_invariant
        """
        venue, guest, entry2, called2, entry3 = (
            self._guest_with_one_no_show_and_two_called_entries(api)
        )

        guest_before = get_guest(guest["id"])
        assert guest_before["no_show_count"] == 1

        seat_result = validate_success(
            api.seat_waitlist_entry(
                entry2["id"],
                {"expected_waitlist_entry_version": called2["version"]},
                HOST_HEADERS,
            )
        )
        validate_success(api.cancel_waitlist_entry(entry3["id"], HOST_HEADERS))
        guest_after = get_guest(guest["id"])

        assert seat_result["status"] == "SEATED"
        assert guest_after["no_show_count"] == 0

    def test_seat_decrements_by_exactly_one(self, api):
        """PRD §3.4: "a successful seat redeems the guest by decrementing `no_show_count` when it is above zero, while the entry's own `version` increments."

        The redemption moves the count by exactly one — no more, no less.

        Design: Difficulty/compensating_invariant/waitlist_seat_cancel_no_show_invariant
        """
        venue, guest, entry2, called2, _entry3 = (
            self._guest_with_one_no_show_and_two_called_entries(api)
        )

        guest_before = get_guest(guest["id"])
        validate_success(
            api.seat_waitlist_entry(
                entry2["id"],
                {"expected_waitlist_entry_version": called2["version"]},
                HOST_HEADERS,
            )
        )
        guest_after = get_guest(guest["id"])

        assert guest_before["no_show_count"] - guest_after["no_show_count"] == 1


class TestFantasySettlePrizeConservation:
    """Settlement hands out exactly the distributable pool — no cents lost."""

    def _settle_three_entry_contest(self, api):
        venue = create_venue()
        guests = [create_guest(venue["id"], name=n) for n in ("Alex", "Blair", "Casey")]
        contest, entries = create_locked_contest_with_entries(
            venue["id"], [g["id"] for g in guests]
        )
        settled = validate_success(
            api.settle_fantasy_contest(
                contest["id"],
                {"expected_fantasy_contest_version": contest["version"]},
                VENUE_MANAGER_HEADERS,
            )
        )
        return venue, contest, settled

    def test_prizes_sum_to_the_distributable_pool(self, api):
        """PRD §3.9: "The gross pool is the entry count times `entry_fee_cents`. The rake is the gross times `rake_pct`, rounded down to whole cents. The distributable pool is gross minus rake."
        PRD §3.9: "Because flooring loses cents, the remainder — the distributable pool minus the sum of floored prizes — is handed out one cent at a time to winners in order of entry creation, earliest `created_at` first, until the remainder is exhausted."

        Three entries at 2500 cents with a 0.10 rake give gross 7500, rake
        750, distributable 6750; the awarded prizes must sum to exactly 6750.

        Design: Difficulty/compensating_invariant/fantasy_settle_prize_conservation
        """
        venue, contest, settled = self._settle_three_entry_contest(api)

        entries = validate_success(
            api.list_contest_fantasy_entries(contest["id"], VENUE_MANAGER_HEADERS)
        )
        total_prize = sum(e["prize_cents"] for e in entries)

        assert settled["status"] == "SETTLED"
        assert total_prize == 6750

    def test_each_winner_gets_the_floored_share_plus_remainder_cents(self, api):
        """PRD §3.9: "Each winner's raw share is the distributable pool times their `prize_structure` fraction, floored to whole cents to form their `prize_cents` — which is zero on every entry until settled."
        PRD §3.9: "Because flooring loses cents, the remainder — the distributable pool minus the sum of floored prizes — is handed out one cent at a time to winners in order of entry creation, earliest `created_at` first, until the remainder is exhausted."

        Shares [0.5, 0.3, 0.2] on a 6750-cent pool floor exactly to
        3375 / 2025 / 1350 with no remainder.

        Design: Difficulty/compensating_invariant/fantasy_settle_prize_conservation
        """
        venue, contest, settled = self._settle_three_entry_contest(api)

        entries = validate_success(
            api.list_contest_fantasy_entries(contest["id"], VENUE_MANAGER_HEADERS)
        )
        prizes = sorted((e["prize_cents"] for e in entries), reverse=True)

        assert prizes == [3375, 2025, 1350]


class TestOccStaleVersionOnFantasySettle:
    """Settlement refuses to allocate prizes against a stale contest view."""

    def _locked_contest(self, api):
        venue = create_venue()
        guest = create_guest(venue["id"])
        contest, _entries = create_locked_contest_with_entries(
            venue["id"], [guest["id"]]
        )
        return venue, contest

    def test_settle_with_a_stale_version_is_rejected(self, api):
        """PRD §3.9: "Settlement is the OCC-guarded write described in §2.8: the request carries `expected_fantasy_contest_version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Citing the pre-lock version after locking advanced the contest is a
        stale write and fails with 412.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_fantasy_settle
        """
        venue, contest = self._locked_contest(api)

        resp = api.settle_fantasy_contest(
            contest["id"],
            {"expected_fantasy_contest_version": contest["version"] - 1},
            VENUE_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_settle_with_the_current_version_succeeds(self, api):
        """PRD §3.9: "A successful settlement moves the contest to `SETTLED`, increments the contest's `version`, and allocates prizes through a waterfall."

        Citing the version observed after the lock lets the settlement
        proceed, proving the guard keys on the observed version rather than
        rejecting settlement outright.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_fantasy_settle
        """
        venue, contest = self._locked_contest(api)

        settled = validate_success(
            api.settle_fantasy_contest(
                contest["id"],
                {"expected_fantasy_contest_version": contest["version"]},
                VENUE_MANAGER_HEADERS,
            )
        )
        assert settled["status"] == "SETTLED"
