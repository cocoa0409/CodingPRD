"""Waitlist ordering, standby positions, offer cascades and the sweep."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    book,
    create_client,
    create_session,
    get_success_data,
    inject_history,
    join_waitlist,
    make_client_headers,
    set_clock,
    setup_full_session_with_waitlists,
    setup_studio_roster,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWaitlistCreation:

    def test_position_mode_selects_the_creation_status_and_effective_sequence(self, api):
        """PRD §3.4: "A hold created in `QUEUED` mode begins in `ACTIVE`; a hold created in `STANDBY_ANY` mode begins in `STANDBY`. Both enumeration values are therefore reachable at creation."
        PRD §3.4: "The `effective_sequence` is the value the offer ordering actually ranks on: it equals `min(raw_sequence_no, 0)` when the hold is in `STANDBY_ANY` mode and equals `raw_sequence_no` otherwise."

        Design: Difficulty/combinatorial_formula/waitlist_offer_ordering_is_non_linear_over_effective_sequence_and_created_at
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        holder = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                               email="cleo@example.com")
        book(holder["id"], ctx["session"]["id"])

        queued = validate_success(api.join_waitlist({
            "class_session_id": ctx["session"]["id"], "client_id": maya["id"],
            "position_mode": "QUEUED"},
            make_client_headers(maya["id"])), expected_status=201)
        assert queued["status"] == "ACTIVE"
        assert queued["position_mode"] == "QUEUED"
        assert queued["raw_sequence_no"] == 1
        assert queued["effective_sequence"] == 1

        standby = validate_success(api.join_waitlist({
            "class_session_id": ctx["session"]["id"], "client_id": bea["id"],
            "position_mode": "STANDBY_ANY"},
            make_client_headers(bea["id"])), expected_status=201)
        assert standby["status"] == "STANDBY"
        assert standby["effective_sequence"] == 0, \
            "a standby hold's effective sequence collapses to zero"

    def test_a_hold_on_a_not_yet_full_session_reserves_nothing(self, api):
        """PRD §3.4: "A hold joined while the session is not yet full is still created `ACTIVE`, but no seat is reserved for it, so the session's `seats_held` is unchanged."

        Design: Difficulty/combinatorial_formula/waitlist_offer_ordering_is_non_linear_over_effective_sequence_and_created_at
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        entry = validate_success(api.join_waitlist({
            "class_session_id": ctx["session"]["id"], "client_id": maya["id"],
            "position_mode": "QUEUED"},
            make_client_headers(maya["id"])), expected_status=201)
        assert entry["status"] == "ACTIVE"
        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_held"] == 0, "an ACTIVE hold reserves nothing"


class TestOfferOrdering:

    def test_waitlist_offer_ordering_ranks_effective_sequence_before_arrival(self, api):
        """PRD §3.4: "Candidates are ranked by ascending `effective_sequence`, then by ascending `created_at`, and if those also tie by ascending `joined_at`. The hold's UUID is never used as a tie-break."

        Design: Difficulty/combinatorial_formula/waitlist_offer_ordering_is_non_linear_over_effective_sequence_and_created_at
        """
        ctx = setup_full_session_with_waitlists(mode_a="QUEUED", mode_b="STANDBY_ANY")
        assert ctx["hold_a"]["effective_sequence"] == 1
        assert ctx["hold_a"]["raw_sequence_no"] == 1
        assert ctx["hold_b"]["effective_sequence"] == 0, \
            "the standby hold outranks the earlier-joined numbered hold"

        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        by_id = {row["id"]: row for row in holds}
        assert by_id[ctx["hold_b"]["id"]]["status"] == "OFFERED", \
            "the standby hold receives the freed seat"
        assert by_id[ctx["hold_a"]["id"]]["status"] == "ACTIVE", \
            "the numbered hold is still waiting"

    def test_the_strike_blocked_hold_is_skipped_without_error(self, api):
        """PRD §3.4: "The candidate pool for an offer is drawn explicitly: holds of the target session whose status is `ACTIVE` or `STANDBY`, whose `joined_at` is at or before the current instant, whose owning client is not in `PORTABILITY_HOLD`, `PORTED` or `ANONYMIZED`, whose owning client's `no_show_strike_count` has not reached the offer block threshold of `STRIKE_OFFER_BLOCK_THRESHOLD`, and whose session is still `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/combinatorial_formula/waitlist_offer_ordering_is_non_linear_over_effective_sequence_and_created_at
        """
        ctx = setup_full_session_with_waitlists(strikes_a=0, strikes_b=3,
                                                mode_a="QUEUED", mode_b="QUEUED")
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        by_id = {row["id"]: row for row in holds}
        assert by_id[ctx["hold_a"]["id"]]["status"] == "OFFERED"
        assert by_id[ctx["hold_b"]["id"]]["status"] == "ACTIVE", \
            "a client at exactly three strikes is removed from the pool"
        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_held"] == 1
        assert session["fullness_posture"] == "FULL"


class TestStrikeBoundary:

    def test_waitlist_offer_refused_at_exactly_three_strikes_and_admitted_below(self, api):
        """PRD §3.4: "whose owning client's `no_show_strike_count` has not reached the offer block threshold of `STRIKE_OFFER_BLOCK_THRESHOLD"

        Design: Difficulty/boundary_precision_check/waitlist_offer_refused_at_exactly_two_strikes_and_admitted_below
        """
        ctx = setup_full_session_with_waitlists(strikes_a=2, strikes_b=3,
                                                mode_a="QUEUED", mode_b="QUEUED")
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        by_id = {row["id"]: row for row in holds}
        assert by_id[ctx["hold_a"]["id"]]["status"] == "OFFERED", \
            "two strikes is below the block threshold, so the hold is admissible"
        assert by_id[ctx["hold_b"]["id"]]["status"] == "ACTIVE", \
            "three strikes meets the threshold and blocks the offer"

    def test_raising_the_first_client_above_the_threshold_moves_the_offer(self, api):
        """PRD §3.4: "whose owning client's `no_show_strike_count` has not reached the offer block threshold of `STRIKE_OFFER_BLOCK_THRESHOLD"

        Design: Difficulty/boundary_precision_check/waitlist_offer_refused_at_exactly_two_strikes_and_admitted_below
        """
        ctx = setup_full_session_with_waitlists(strikes_a=3, strikes_b=3,
                                                mode_a="QUEUED", mode_b="QUEUED")
        # Client A sits at exactly the threshold and client B also blocks, so
        # the pool is empty and the seat is held rather than offered onward.
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        by_id = {row["id"]: row for row in holds}
        assert by_id[ctx["hold_a"]["id"]]["status"] == "ACTIVE"
        assert by_id[ctx["hold_b"]["id"]]["status"] == "ACTIVE"


class TestCompensatingWaitlistActions:

    def test_claim_on_a_hold_that_was_never_offered_is_refused(self, api):
        """PRD §3.4: "A claim attempted against a hold that is not `OFFERED` is refused with `ERR_ENTRY_NOT_OFFERED`."

        Design: Corner/state_machines/claim_on_a_hold_that_was_never_offered_returns_entry_not_offered
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-21T17:00:00Z",
                                  room_code="ROOM-B")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        hold = join_waitlist(maya["id"], ctx["session"]["id"], "QUEUED")

        validate_error(api.claim_waitlist_entry(
            hold["id"], {"payment_source": "DROP_IN"},
            make_client_headers(maya["id"])), ApiErrorId.ERR_ENTRY_NOT_OFFERED)

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        assert holds[0]["status"] == "ACTIVE"
        assert holds[0]["promoted_booking_id"] is None
        rows, meta = validate_paginated(api.list_bookings(
            ctx["owner"], params={"class_session_id": ctx["session"]["id"]}))
        assert meta["total_count"] == 0, "no booking was silently created"

    def test_pack_credit_conservation_survives_a_reverse_claim(self, api):
        """PRD §3.9: "A pack's remaining credits, plus the credits consumed by bookings still in `RESERVED`, `CHECKED_IN` or `ATTENDED`, must equal the pack's original size less the credits voided by the expiry sweep; every booking paired with its compensating cancellation leaves that equation unchanged."
        PRD §3.4: "the hold reverts from CLAIMED to ACTIVE — but with
        position_mode reset to QUEUED and raw_sequence_no reassigned to the
        maximum sequence on the session plus 1, never to zero."

        Design: Difficulty/compensating_invariant/pack_credit_conservation_survives_a_failed_claim_reversal
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        holder = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                               email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": bea["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": bea["version"],
        }, ctx["owner"]), expected_status=201)

        seat_booking = book(holder["id"], ctx["session"]["id"])
        hold = join_waitlist(bea["id"], ctx["session"]["id"], "QUEUED")
        get_success_data(api.cancel_booking(
            seat_booking["id"], {"reason": "schedule conflict"},
            make_client_headers(holder["id"])))

        claimed = validate_success(api.claim_waitlist_entry(
            hold["id"], {"payment_source": "CLASS_PACK","class_pack_id": pack["id"]},
            make_client_headers(bea["id"])))
        assert claimed["status"] == "RESERVED"
        after_claim = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
        assert after_claim["credits_remaining"] == 4

        reversed_booking = validate_success(api.reverse_claim(
            claimed["id"], {"reason": "client called in sick"}, ctx["owner"]))
        assert reversed_booking["status"] == "CANCELLED"
        after_reverse = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
        assert after_reverse["credits_remaining"] == 5, \
            "the compensating action restores the exact number"

        entry = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))[0]
        assert entry["status"] == "ACTIVE"
        assert entry["position_mode"] == "QUEUED"

    def test_reverse_claim_places_the_client_at_the_back_of_the_line(self, api):
        """PRD §3.4: "reassigned to the maximum sequence on the session plus 1,
        never to zero, so the client rejoins at the back of the line rather than
        reclaiming their old slot."

        Design: Difficulty/compensating_invariant/pack_credit_conservation_survives_a_failed_claim_reversal
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        holder = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                               email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        other = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                              email="cleo@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": bea["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": bea["version"],
        }, ctx["owner"]), expected_status=201)

        seat_booking = book(holder["id"], ctx["session"]["id"])
        hold = join_waitlist(bea["id"], ctx["session"]["id"], "QUEUED")
        later_hold = join_waitlist(other["id"], ctx["session"]["id"], "QUEUED")
        get_success_data(api.cancel_booking(
            seat_booking["id"], {"reason": "schedule conflict"},
            make_client_headers(holder["id"])))
        claimed = validate_success(api.claim_waitlist_entry(
            hold["id"], {"payment_source": "CLASS_PACK","class_pack_id": pack["id"]},
            make_client_headers(bea["id"])))
        get_success_data(api.reverse_claim(
            claimed["id"], {"reason": "client called in sick"}, ctx["owner"]))

        entry = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        by_client = {row["client_id"]: row for row in entry}
        assert by_client[bea["id"]]["raw_sequence_no"] > \
            later_hold["raw_sequence_no"], \
            "the reverted hold rejoins behind the client who joined later"


class TestOfferLapseAndCascade:

    def test_cancelling_a_seat_offers_the_hold_and_the_seat_stays_held(self, api):
        """PRD §3.4: "When a hold is offered, it moves from `ACTIVE` to `OFFERED`, its `offer_expires_at` is set to the current instant plus the offer window, and the session's `seats_held` increments by 1."
        PRD §2.9: "If the free-seat count is zero or fewer the posture is `FULL` — the zero case is `FULL`, not `OPEN`."

        Design: Difficulty/transitive_cascade/cancelling_a_seat_offers_the_hold_and_the_lapse_of_that_offer_reopens_the_session
        """
        ctx = setup_full_session_with_waitlists(mode_a="QUEUED")
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        offered = [row for row in holds if row["status"] == "OFFERED"]
        assert len(offered) == 1, "the freed seat is offered to the top-ranked hold"
        assert offered[0]["offer_expires_at"] is not None

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_taken"] == 0
        assert session["seats_held"] == 1, "the seat is held, not free"
        assert session["fullness_posture"] == "FULL"

    def test_the_lapsed_offer_releases_the_seat_and_leaves_the_posture(self, api):
        """PRD §3.4: "When the clock passes `offer_expires_at` the hold moves from `OFFERED` to `EXPIRED`, and the seat is offered onward: the session's next-lowest-ranking `ACTIVE` hold becomes `OFFERED` with a fresh offer window. If no `ACTIVE` hold remains, the session's `seats_held` decrements by 1 and the posture is re-derived toward `OPEN`."

        Design: Difficulty/transitive_cascade/cancelling_a_seat_offers_the_hold_and_the_lapse_of_that_offer_reopens_the_session
        """
        ctx = setup_full_session_with_waitlists(mode_a="QUEUED", hold_count=1)
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        # The session starts exactly at the clock position, so no hold remains
        # in the candidate pool once the clock reaches the offer's lapse.
        set_clock("2026-06-20T17:00:00Z")

        holds = validate_success(api.list_session_waitlist_entries(
            ctx["session"]["id"], ctx["owner"]))
        for row in holds:
            assert row["status"] in ("EXPIRED", "ACTIVE"), \
                "the lapsed offer is retired rather than left OFFERED"
        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_held"] == 0, "the seat is no longer held"
        assert session["fullness_posture"] != "FULL", \
            "the posture leaves FULL once no hold remains in the pool"


class TestOfferSweep:

    def test_sweep_expires_lapsed_offers_and_reports_the_count(self, api):
        """PRD §3.4: "The sweep that finds and expires lapsed offers is an operator-and-owner capability that walks the studio's offered holds, moves every offer whose window has passed to `EXPIRED`, offers each freed seat onward to the next-ranked hold with a fresh window, and reports how many seats it swept along with the identifiers of the holds it offered and the holds it expired."

        Design: Corner/endpoints/session_aftercare_sweep_expires_every_lapsed_offer_and_reports_the_count
        """
        ctx = setup_full_session_with_waitlists(mode_a="QUEUED")
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))

        result = validate_success(api.sweep_offers(
            {"studio_id": ctx["studio"]["id"]}, ctx["owner"]))
        # The offer was made at 2026-06-01 and lapses two hours later; moving
        # the clock past that window makes the sweep collect it.
        assert "swept_count" in result

        set_clock("2026-06-14T10:00:00Z")
        swept = validate_success(api.sweep_offers(
            {"studio_id": ctx["studio"]["id"]}, ctx["owner"]))
        assert swept["swept_count"] >= 1
        assert ctx["hold_a"]["id"] in swept["expired_entry_ids"]

    def test_repeating_the_sweep_is_idempotent(self, api):
        """PRD §3.4: "The sweep that finds and expires lapsed offers is an
        operator-and-owner capability that walks the studio's offered holds,
        moves every offer whose window has passed to EXPIRED."

        Design: Corner/endpoints/session_aftercare_sweep_expires_every_lapsed_offer_and_reports_the_count
        """
        ctx = setup_full_session_with_waitlists(mode_a="QUEUED")
        get_success_data(api.cancel_booking(
            ctx["seat_booking"]["id"], {"reason": "schedule conflict"},
            make_client_headers(ctx["holder"]["id"])))
        set_clock("2026-06-14T10:00:00Z")

        first = validate_success(api.sweep_offers(
            {"studio_id": ctx["studio"]["id"]}, ctx["owner"]))
        assert first["swept_count"] == 1
        second = validate_success(api.sweep_offers(
            {"studio_id": ctx["studio"]["id"]}, ctx["owner"]))
        assert second["swept_count"] == 0, \
            "the operation is idempotent over already-expired holds"