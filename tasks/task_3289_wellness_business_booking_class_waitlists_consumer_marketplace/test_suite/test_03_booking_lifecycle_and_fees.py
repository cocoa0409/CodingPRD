"""Booking lifecycle: check-in, cancellation fees, no-shows and admission."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    TEST_USERS,
    assert_client,
    book,
    create_client,
    create_session,
    ensure_tier,
    get_success_data,
    inject_history,
    make_client_headers,
    make_studio_owner_headers,
    set_clock,
    setup_client_with_session,
    setup_studio_roster,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestCheckInWindow:

    def test_check_in_before_the_window_opens_is_refused(self, api):
        """PRD §3.3: "A booked client checks in once the check-in gate opens at
        the session start minus the platform check-in lead time and up to the
        session end, provided the session is IN_PROGRESS."
        PRD §3.3: "Check-in is only admitted against a booking that is still `RESERVED`; anything else is refused with `ERR_BOOKING_NOT_RESERVED`."

        Design: Corner/state_machines/check_in_before_the_window_opens_returns_invalid_state
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        client = create_client(ctx["studio"]["id"])
        booking = book(client["id"], ctx["session"]["id"])
        set_clock("2026-06-20T12:00:00Z")

        validate_error(api.check_in_booking(booking["id"],
                                            make_client_headers(client["id"])),
                       ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_booking(booking["id"], ctx["owner"]))
        assert still["status"] == "RESERVED", "a refused check-in leaves the booking RESERVED"

    def test_check_in_inside_the_gate_on_an_in_progress_session_succeeds(self, api):
        """PRD §3.3: "A booked client checks in once the check-in gate opens at the session start minus the platform check-in lead time and up to the session end, provided the session is `IN_PROGRESS`; check-in moves the booking from `RESERVED` to `CHECKED_IN` and recomputes the session's posture without changing `seats_taken`, because a checked-in booking still occupies its seat."

        Design: Corner/state_machines/check_in_before_the_window_opens_returns_invalid_state
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        client = create_client(ctx["studio"]["id"])
        booking = book(client["id"], ctx["session"]["id"])
        set_clock("2026-06-20T17:00:00Z")

        checked = validate_success(api.check_in_booking(
            booking["id"], make_client_headers(client["id"])))
        assert checked["status"] == "CHECKED_IN"

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["status"] == "IN_PROGRESS"
        assert session["seats_taken"] == 1, "a checked-in seat still occupies"


class TestLateCancellationWindow:

    def test_late_cancellation_fee_fires_inside_the_twelve_hour_window(self, api):
        """PRD §3.3: "Cancelling at or before the session start minus the late-cancellation window of 720 minutes — twelve hours — yields `CANCELLED` with `fee_status` `NONE` and `booking_fee_cents` remaining 0."
        PRD §3.3: "Cancelling after that boundary but at or before the session start yields `LATE_CANCELLED`, with `booking_fee_cents` computed by the late-cancellation rule and `fee_status` set to `CHARGED`."
        PRD §3.3: "In every other case the fee is the session's `list_price_cents` multiplied by the fraction one, truncated to whole cents."

        Design: Corner/calculations/late_cancellation_fee_fires_exactly_inside_the_twelve_hour_window
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=2,
                                room_code="ROOM-B",
                                start_at="2026-06-22T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        late_booking = book(maya["id"], ctx["session"]["id"])
        free_booking = book(bea["id"], second["id"])

        set_clock("2026-06-20T06:00:00Z")
        late = validate_success(api.cancel_booking(
            late_booking["id"], {"reason": "overslept"},
            make_client_headers(maya["id"])))
        assert late["status"] == "LATE_CANCELLED", \
            "11 hours before the start is inside the late window"
        assert late["booking_fee_cents"] == 3360, "the full list price"
        assert late["fee_status"] == "CHARGED"

        free = validate_success(api.cancel_booking(
            free_booking["id"], {"reason": "travelling"},
            make_client_headers(bea["id"])))
        assert free["status"] == "CANCELLED", \
            "59 hours before the start is outside the window"
        assert free["booking_fee_cents"] == 0
        assert free["fee_status"] == "NONE"

    def test_late_cancel_counters_accumulate_on_the_charged_client_only(self, api):
        """PRD §2.13: "late_cancel_count` accumulates one per booking that reaches `LATE_CANCELLED` and is never reset by any operation; and `outstanding_fee_cents` aggregates the fees currently owed across the client's bookings whose `fee_status` is `CHARGED` or `PAYROLL_DEDUCTED`."

        Design: Corner/calculations/late_cancellation_fee_fires_exactly_inside_the_twelve_hour_window
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=2,
                                room_code="ROOM-B",
                                start_at="2026-06-22T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        late_booking = book(maya["id"], ctx["session"]["id"])
        free_booking = book(bea["id"], second["id"])
        set_clock("2026-06-20T06:00:00Z")

        validate_success(api.cancel_booking(late_booking["id"], {"reason": "x"},
                                            make_client_headers(maya["id"])))
        validate_success(api.cancel_booking(free_booking["id"], {"reason": "x"},
                                            make_client_headers(bea["id"])))

        maya_after = validate_success(api.get_client(maya["id"], ctx["owner"]))
        assert maya_after["late_cancel_count"] == 1
        assert maya_after["outstanding_fee_cents"] == 3360

        bea_after = validate_success(api.get_client(bea["id"], ctx["owner"]))
        assert bea_after["late_cancel_count"] == 0
        assert bea_after["outstanding_fee_cents"] == 0


class TestNoShowFee:

    def test_no_show_fee_strike_multiplier_is_capped_at_twice_list_price(self, api):
        """PRD §3.3: "`credits_remaining` by one; when that debit empties the pack, the pack's status mov"
        PRD §3.3: "Otherwise the fee is the session's `list_price_cents` multiplied by one plus one half of the lesser of 2 and the prior strike count minus 1, truncated to whole cents. The strike multiplier is capped so that a client already at or above the cap never pays more than twice the list price."

        Design: Corner/calculations/no_show_fee_strike_multiplier_is_capped_at_twice_list_price
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=2,
                                room_code="ROOM-B",
                                start_at="2026-06-21T17:00:00Z")
        third = create_session(ctx["studio"]["id"], ctx["owner"],
                               ctx["template"]["id"], ctx["instructor"]["id"],
                               ctx["subscription_version"], capacity=2,
                               room_code="ROOM-C",
                               start_at="2026-06-22T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        cleo = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                             email="cleo@example.com")
        inject_history(maya["id"], 1)
        inject_history(bea["id"], 2)
        inject_history(cleo["id"], 4)

        first = book(maya["id"], ctx["session"]["id"])
        second_booking = book(bea["id"], second["id"])
        third_booking = book(cleo["id"], third["id"])

        for session in (ctx["session"], second, third):
            get_success_data(api.complete_class_session(session["id"], ADMIN))

        one = validate_success(api.get_booking(first["id"], ctx["owner"]))
        assert one["status"] == "NO_SHOW"
        assert one["booking_fee_cents"] == 0, "one prior strike is the free first offence"
        assert one["fee_status"] == "NONE"

        two = validate_success(api.get_booking(second_booking["id"], ctx["owner"]))
        assert two["status"] == "NO_SHOW"
        assert two["booking_fee_cents"] == 5040, "3360 at the 1.5x strike multiplier"

        four = validate_success(api.get_booking(third_booking["id"], ctx["owner"]))
        assert four["status"] == "NO_SHOW"
        assert four["booking_fee_cents"] == 6720, \
            "3360 at the capped 2.0x multiplier, not the uncapped 3.0x"

    def test_no_show_strikes_and_fees_land_on_the_client_row(self, api):
        """PRD §3.3: "Each booking that becomes NO_SHOW increments its client's
        no_show_strike_count by 1, sets booking_fee_cents from the no-show fee
        rule below, and sets fee_status to CHARGED whenever the computed fee is
        above zero."
        PRD §3.3: "The client's `outstanding_fee_cents` grows by the fee that was charged."

        Design: Corner/calculations/no_show_fee_strike_multiplier_is_capped_at_twice_list_price
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        cleo = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                             email="cleo@example.com")
        inject_history(cleo["id"], 4)
        booking = book(cleo["id"], ctx["session"]["id"])
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))

        after = validate_success(api.get_client(cleo["id"], ctx["owner"]))
        assert after["no_show_strike_count"] == 5, "the strike is recorded on the client"
        assert after["outstanding_fee_cents"] == 6720
        charged = validate_success(api.get_booking(booking["id"], ctx["owner"]))
        assert charged["fee_status"] == "CHARGED"


class TestBookingAdmissionAndPrecedence:

    def test_overlapping_client_schedules_are_refused_before_capacity(self, api):
        """PRD §3.2: "Symmetrically, a client may not hold a booking or a waitlist hold on a session whose interval overlaps the target session's interval, or the booking is refused with `ERR_CLIENT_SCHEDULE_OVERLAP`."
        PRD §2.11: "Only after posture is settled are the temporal interval rules
        evaluated (ERR_CLIENT_SCHEDULE_OVERLAP, ERR_ROOM_OVERLAP,
        ERR_BUFFER_INSUFFICIENT, ERR_PAYROLL_PERIOD_GAP and
        ERR_CANCEL_WINDOW_CLOSED, all HTTP 409), then the capacity, quota and
        uniqueness constraints."

        Design: Corner/validations/overlapping_client_schedules_are_refused_before_capacity_is_considered
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A")
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=1,
                                room_code="ROOM-B",
                                start_at="2026-06-20T17:20:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        book(maya["id"], ctx["session"]["id"],
             **{"channel": "STUDIO", "payment_source": "DROP_IN"})
        # Fill the overlapping second session so capacity is also violated.
        book(bea["id"], second["id"])

        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": second["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_CLIENT_SCHEDULE_OVERLAP)

        rows, meta = validate_paginated(api.list_bookings(
            ctx["owner"], params={"class_session_id": second["id"]}))
        assert meta["total_count"] == 1, "no second booking was persisted"

    def test_capacity_shortfall_surfaces_once_the_overlap_is_removed(self, api):
        """PRD §2.11: "Only after posture is settled are the temporal interval
        rules evaluated ..., then the capacity, quota and uniqueness constraints
        (ERR_STUDIO_CAPACITY_EXCEEDED, ERR_ALLOCATION_EXHAUSTED,
        ERR_NO_ACTIVE_PACK, ERR_MEMBERSHIP_INACTIVE, ERR_PAYROLL_PERIOD_OVERLAP,
        ERR_CLIENT_EMAIL_CONFLICT, all HTTP 409)."

        Design: Corner/validations/overlapping_client_schedules_are_refused_before_capacity_is_considered
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A")
        second = create_session(ctx["studio"]["id"], ctx["owner"],
                                ctx["template"]["id"], ctx["instructor"]["id"],
                                ctx["subscription_version"], capacity=1,
                                room_code="ROOM-B",
                                start_at="2026-06-20T17:20:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        first_booking = book(maya["id"], ctx["session"]["id"])
        book(bea["id"], second["id"])

        # Removing the overlap exposes the capacity failure underneath it.
        get_success_data(api.cancel_booking(
            first_booking["id"], {"reason": "schedule conflict"},
            make_client_headers(maya["id"])))

        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": second["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_STUDIO_CAPACITY_EXCEEDED)


class TestNoShowCompensatingRestore:

    def test_no_show_reverses_back_to_reserved_by_compensating_action(self, api):
        """PRD §3.3: "A studio owner may restore a `NO_SHOW` booking by supplying a `reason`, which moves the booking back to `RESERVED`, sets `fee_status` to `WAIVED`, decrements the client's `no_show_strike_count` by 1 and reduces the client's `outstanding_fee_cents` by the booking's `booking_fee_cents`."

        Design: Difficulty/non_linear_state_machine/booking_no_show_reverses_back_to_reserved_by_compensating_action
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))

        shown = validate_success(api.get_booking(booking["id"], ctx["owner"]))
        assert shown["status"] == "NO_SHOW", "completion drove the booking to NO_SHOW"

        restored = validate_success(api.restore_no_show(
            booking["id"], {"reason": "client was present, front desk missed check-in"},
            ctx["owner"]))
        assert restored["status"] == "RESERVED", \
            "the machine moved backwards into a live state"
        assert restored["fee_status"] == "WAIVED"

        client = validate_success(api.get_client(maya["id"], ctx["owner"]))
        assert client["no_show_strike_count"] == 0
        assert client["outstanding_fee_cents"] == 0

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["status"] == "COMPLETED", \
            "a RESERVED booking on a COMPLETED session is reachable only via the cycle"

    def test_listing_reflects_the_restored_state_not_the_no_show(self, api):
        """PRD §2.3: "Filter parameters that a given list endpoint declares (`status`, `channel`, `studio_id`, and the like) narrow `total_count` before pagination, never after."

        Design: Difficulty/non_linear_state_machine/booking_no_show_reverses_back_to_reserved_by_compensating_action
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=1,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))
        get_success_data(api.restore_no_show(
            booking["id"], {"reason": "front desk missed the check-in"}, ctx["owner"]))

        _, no_show_meta = validate_paginated(api.list_bookings(
            ctx["owner"], params={"status": "NO_SHOW"}))
        assert no_show_meta["total_count"] == 0
        _, reserved_meta = validate_paginated(api.list_bookings(
            ctx["owner"], params={"status": "RESERVED"}))
        assert reserved_meta["total_count"] == 1


class TestClientAdmissibility:

    def test_booking_admission_depends_on_the_clients_portability_posture(self, api):
        """PRD §3.3: "An attempt by a client whose own `status` is `PORTABILITY_HOLD`, `PORTED` or `ANONYMIZED` is refused with `ERR_CLIENT_NOT_ADMISSIBLE`, because such a client may not take new bookings or holds."
        PRD §3.10: "The release carries include_booking_history and
        include_financial_history flags, stamps decided_at, moves the studio's
        data_ownership_state to PORTABILITY_GRANTED, and moves the requesting
        client's status to PORTABILITY_HOLD."

        Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_the_clients_portability_posture
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")

        first = validate_success(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), expected_status=201)
        assert first["status"] == "RESERVED", "admitted before the posture changes"

        request = get_success_data(api.create_portability_request({
            "studio_id": ctx["studio"]["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])))
        get_success_data(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            ctx["owner"]))

        held_client = validate_success(api.get_client(maya["id"], ctx["owner"]))
        assert held_client["status"] == "PORTABILITY_HOLD"
        studio = validate_success(api.get_studio(ctx["studio"]["id"], ctx["owner"]))
        assert studio["data_ownership_state"] == "PORTABILITY_GRANTED"

        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_CLIENT_NOT_ADMISSIBLE)

    def test_the_refusal_is_caused_by_the_client_not_the_session(self, api):
        """PRD §2.9: "If the free-seat count is zero or fewer the posture is `FULL` — the zero case is `FULL`, not `OPEN`. If free seats remain but the studio-channel count is zero or fewer the posture is `WAITLIST_ONLY`. Only when a positive number of studio seats remains is the posture `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_the_clients_portability_posture
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        book(maya["id"], ctx["session"]["id"])
        request = get_success_data(api.create_portability_request({
            "studio_id": ctx["studio"]["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])))
        get_success_data(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            ctx["owner"]))

        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_CLIENT_NOT_ADMISSIBLE)

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["fullness_posture"] == "OPEN", \
            "the session itself still has free seats"
        assert session["seats_taken"] == 1


class TestImmediateVisibility:

    def test_every_write_is_visible_without_a_follow_up_write(self, api):
        """PRD §3.3: "The booking begins in `RESERVED`, increments the session's `seats_taken`, and triggers a re-derivation of `fullness_posture`."
        PRD §2.9: "If the free-seat count is zero or fewer the posture is `FULL` — the zero case is `FULL`, not `OPEN`."

        Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_without_a_follow_up_read
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")

        first = validate_success(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), expected_status=201)
        assert first["status"] == "RESERVED"
        after_first = validate_success(api.get_class_session(
            ctx["session"]["id"], ctx["owner"]))
        assert after_first["seats_taken"] == 1
        assert after_first["fullness_posture"] == "OPEN"

        second = validate_success(api.create_booking({
            "client_id": bea["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(bea["id"])), expected_status=201)
        assert second["status"] == "RESERVED"
        after_second = validate_success(api.get_class_session(
            ctx["session"]["id"], ctx["owner"]))
        assert after_second["seats_taken"] == 2
        assert after_second["fullness_posture"] == "FULL", \
            "the zero-free-seat case reports FULL, not OPEN"

        # The posture the second write produced is the posture the third
        # request observes, with no clock advance in between.
        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "DROP_IN",
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_STUDIO_CAPACITY_EXCEEDED)


class TestStudioDerivedCounters:

    def test_roster_count_and_outstanding_balance_reconcile_in_one_read(self, api):
        """PRD §2.6: "The studio's aggregate `outstanding_balance_cents` is the sum of the open balance on every non-terminal membership, plus the outstanding booking fee on every booking sitting in `NO_SHOW` or `LATE_CANCELLED`, plus the class-package overage; it is never permitted to fall below zero."
        PRD §2.4: "The Studio row itself is the tenant root: it aggregates
        client_roster_count, outstanding_balance_cents, subscription_tier,
        feature_gates, data_ownership_state and status."

        Design: Corner/cross_cutting_complexity_layers/studio_roster_count_and_outstanding_balance_are_reconciled_in_the_same_response
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        set_clock("2026-06-20T06:00:00Z")
        late = validate_success(api.cancel_booking(
            booking["id"], {"reason": "overslept"}, make_client_headers(maya["id"])))
        assert late["status"] == "LATE_CANCELLED"

        client = validate_success(api.get_client(maya["id"], ctx["owner"]))
        studio = validate_success(api.get_studio(ctx["studio"]["id"], ctx["owner"]))
        assert client["outstanding_fee_cents"] == 3360
        assert studio["outstanding_balance_cents"] == 3360, \
            "the derived aggregate already includes the charge"
        assert studio["client_roster_count"] == 1, "the ACTIVE client is counted"

    def test_restoring_a_no_show_removes_the_fee_from_the_studio_aggregate(self, api):
        """PRD §3.3: "The booking's `booking_fee_cents` is retained for audit but no longer counts toward the studio's aggregate `outstanding_balance_cents`."

        Design: Corner/cross_cutting_complexity_layers/studio_roster_count_and_outstanding_balance_are_reconciled_in_the_same_response
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        cleo = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                             email="cleo@example.com")
        inject_history(cleo["id"], 4)
        booking = book(cleo["id"], ctx["session"]["id"])
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))

        charged = validate_success(api.get_studio(ctx["studio"]["id"], ctx["owner"]))
        assert charged["outstanding_balance_cents"] == 6720

        get_success_data(api.restore_no_show(
            booking["id"], {"reason": "front desk missed the check-in"}, ctx["owner"]))
        after = validate_success(api.get_studio(ctx["studio"]["id"], ctx["owner"]))
        assert after["outstanding_balance_cents"] == 0, \
            "the waived fee no longer counts toward the studio aggregate"