"""Reservation lifecycle: holds, TTL, cancel window, check-in window, locks."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
    create_held_reservation,
    create_on_sale_showtime,
    create_published_plan,
    create_reservation_payload,
    create_theater_with_auditorium,
    current_showtime,
    enroll_member,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_theater_with_on_sale_showtime,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]
STAFF = TEST_USERS["theater_staff_headers"]


def _setup_active_sub(api, plan_overrides=None, email="res@x.com"):
    plan = create_published_plan(**(plan_overrides or {}))
    member = create_active_member(email=email, full_name=email)
    sub = enroll_member(member["id"], plan["id"])
    return member, sub


class TestReservationHoldLifecycle:

    def test_confirm_held_reservation_valid_transition(self, api):
        """PRD §3.5: "On success the reservation is created in `HELD` status"
        PRD §3.5: "the member must confirm it within 15 minutes of creation
        (`HOLD_TTL_MINUTES`), and confirmation additionally requires the
        showtime to be `ON_SALE`."

        Design: Corner/state_machines/confirm_held_reservation_valid_transition
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="vt@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        reservation = create_held_reservation(member, sub, showtime)
        assert reservation["status"] == "HELD"
        confirmed = get_success_data(api.confirm_reservation(
            reservation["id"], make_member_headers(member["id"])))
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_stamps_state_only_within_ttl_and_on_sale(self, api):
        """PRD §3.5: "the member must confirm it within 15 minutes of creation
        (`HOLD_TTL_MINUTES`), and confirmation additionally requires the
        showtime to be `ON_SALE`."

        Design: Corner/state_machines/confirm_held_reservation_valid_transition
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="vt2@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        reservation = create_held_reservation(member, sub, showtime)
        # 14 minutes after creation — still inside the 15-minute TTL
        set_clock("2026-09-01T00:14:00Z")
        confirmed = get_success_data(api.confirm_reservation(
            reservation["id"], make_member_headers(member["id"])))
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_after_hold_ttl_returns_invalid_state(self, api):
        """PRD §3.5: "A hold that outlives its window without confirmation is
        auto-swept to `EXPIRED` by the system, releasing the seat and refunding
        the consumed credit in full whenever the originating bucket is not
        `EXPIRED` — hold expiry always refunds."

        Design: Corner/state_machines/confirm_after_hold_ttl_returns_invalid_state
        """
        set_clock("2026-09-01T12:00:00Z")
        member, sub = _setup_active_sub(api, email="ttl@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        reservation = create_held_reservation(member, sub, showtime)
        bucket_id = reservation["bucket_id"]
        set_clock("2026-09-01T12:16:00Z")
        resp = api.confirm_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "EXPIRED", f"expected EXPIRED, got {after['status']}"
        bucket = get_success_data(api.get_bucket(bucket_id, ADMIN))
        assert bucket["credits_used"] == 0, "hold expiry must refund the consumed credit"

    def test_hold_expiry_releases_seat(self, api):
        """PRD §3.5: "A hold that outlives its window without confirmation is
        auto-swept to `EXPIRED` by the system, releasing the seat and refunding
        the consumed credit in full whenever the originating bucket is not
        `EXPIRED` — hold expiry always refunds."

        Design: Corner/state_machines/confirm_after_hold_ttl_returns_invalid_state
        """
        set_clock("2026-09-01T12:00:00Z")
        member, sub = _setup_active_sub(api, email="ttl2@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        create_held_reservation(member, sub, showtime)
        held_mid = current_showtime(showtime["id"])
        assert held_mid["seats_held_subscription"] == 1
        set_clock("2026-09-01T12:16:00Z")
        held_after = current_showtime(showtime["id"])
        assert held_after["seats_held_subscription"] == 0, "expired hold must release the seat"


class TestCancelWindowBoundary:

    def test_cancel_deadline_equality_boundary_rejected(self, api):
        """PRD §3.5: "A member-initiated cancel of a `HELD` or `CONFIRMED`
        reservation is free strictly before `cancel_deadline`; at or after that
        instant it is rejected with `ERR_CANCEL_WINDOW_CLOSED` and no refund
        computation runs."

        Design: Difficulty/boundary_precision_check/cancel_deadline_equality_boundary
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m13@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        reservation = create_confirmed_reservation(member, sub, showtime)
        # Cancel exactly at the stamped cancel_deadline: at-or-after is closed.
        set_clock(reservation["cancel_deadline"])
        resp = api.cancel_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CANCEL_WINDOW_CLOSED)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "CONFIRMED", "rejected cancel must leave the reservation untouched"

    def test_cancel_one_minute_before_deadline_succeeds(self, api):
        """PRD §3.5: "A member-initiated cancel of a `HELD` or `CONFIRMED`
        reservation is free strictly before `cancel_deadline`; at or after that
        instant it is rejected with `ERR_CANCEL_WINDOW_CLOSED` and no refund
        computation runs."

        Design: Difficulty/boundary_precision_check/cancel_deadline_equality_boundary
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m13b@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        reservation = create_confirmed_reservation(member, sub, showtime)
        # One minute strictly before the stamped cancel_deadline.
        deadline = datetime.fromisoformat(
            reservation["cancel_deadline"].replace("Z", "+00:00"))
        one_min_before = (deadline - timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        set_clock(one_min_before)
        cancelled = get_success_data(api.cancel_reservation(
            reservation["id"], make_member_headers(member["id"])))
        assert cancelled["status"] == "CANCELLED"


class TestCheckinWindow:

    def _four_confirmed_on_parallel_showtimes(self, api):
        """One member, four auditoriums, four showtimes all at the same start
        instant, one CONFIRMED reservation on each (single-seat rule)."""
        set_clock()
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, _aud1 = create_theater_with_auditorium(seat_count=10)
        auds = [
            _aud1,
            get_success_data(api.create_auditorium(
                theater["id"], {"label": "A2", "seat_count": 10,
                                "supported_formats": ["STANDARD"]}, ADMIN)),
            get_success_data(api.create_auditorium(
                theater["id"], {"label": "A3", "seat_count": 10,
                                "supported_formats": ["STANDARD"]}, ADMIN)),
            get_success_data(api.create_auditorium(
                theater["id"], {"label": "A4", "seat_count": 10,
                                "supported_formats": ["STANDARD"]}, ADMIN)),
        ]
        member = create_active_member(email="cw@x.com", full_name="CW")
        sub = enroll_member(member["id"], plan["id"])
        reservations = []
        for i, aud in enumerate(auds):
            # runtime_minutes=20 keeps the showtime's COMPLETED sweep
            # (starts_at + runtime + 30m grace) inside the check-in window's
            # upper bound (starts_at + 30m), so the reservation is still
            # CONFIRMED at the inclusive upper boundary.
            st = create_on_sale_showtime(
                aud["id"], film_title=f"W{i+1}", starts_at="2026-09-02T19:00:00Z",
                runtime_minutes=20)
            reservations.append(create_confirmed_reservation(member, sub, st))
        return reservations

    def test_checkin_too_early_rejected(self, api):
        """PRD §3.5: "the instant must fall inside the window from 45 minutes
        before `starts_at` to 30 minutes after it; a check-in outside that
        window is rejected with `ERR_CHECKIN_WINDOW`."

        Design: Corner/validations/checkin_window_boundaries_enforced
        """
        reservations = self._four_confirmed_on_parallel_showtimes(api)
        set_clock("2026-09-02T18:14:00Z")  # starts_at - 46m
        resp = api.check_in_reservation(reservations[0]["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW)

    def test_checkin_at_lower_bound_inclusive_succeeds(self, api):
        """PRD §3.5: "the instant must fall inside the window from 45 minutes
        before `starts_at` to 30 minutes after it; a check-in outside that
        window is rejected with `ERR_CHECKIN_WINDOW`."

        Design: Corner/validations/checkin_window_boundaries_enforced
        """
        reservations = self._four_confirmed_on_parallel_showtimes(api)
        set_clock("2026-09-02T18:15:00Z")  # starts_at - 45m exactly
        checked = get_success_data(api.check_in_reservation(reservations[1]["id"], STAFF))
        assert checked["status"] == "CHECKED_IN"

    def test_checkin_at_upper_bound_inclusive_succeeds(self, api):
        """PRD §3.5: "the instant must fall inside the window from 45 minutes
        before `starts_at` to 30 minutes after it; a check-in outside that
        window is rejected with `ERR_CHECKIN_WINDOW`."

        Design: Corner/validations/checkin_window_boundaries_enforced
        """
        reservations = self._four_confirmed_on_parallel_showtimes(api)
        set_clock("2026-09-02T19:30:00Z")  # starts_at + 30m exactly
        checked = get_success_data(api.check_in_reservation(reservations[2]["id"], STAFF))
        assert checked["status"] == "CHECKED_IN"

    def test_checkin_too_late_rejected(self, api):
        """PRD §3.5: "the instant must fall inside the window from 45 minutes
        before `starts_at` to 30 minutes after it; a check-in outside that
        window is rejected with `ERR_CHECKIN_WINDOW`."

        Design: Corner/validations/checkin_window_boundaries_enforced
        """
        reservations = self._four_confirmed_on_parallel_showtimes(api)
        set_clock("2026-09-02T19:31:00Z")  # starts_at + 31m
        resp = api.check_in_reservation(reservations[3]["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW)


class TestShowtimeLock:

    def test_showtime_locks_ten_minutes_before_start(self, api):
        """PRD §3.6: "From `ON_SALE`, the system locks the showtime
        automatically when the clock reaches ten minutes before start
        (`LOCK_MINUTES_BEFORE_START`): the `ON_SALE → LOCKED` transition
        rejects any further reservation creation or confirmation at the state
        gate with `ERR_SHOWTIME_LOCKED`, while check-ins remain allowed."

        Design: Corner/state_machines/showtime_locks_ten_minutes_before_start
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="lk@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        set_clock("2026-09-02T18:50:00Z")  # exactly starts_at - 10m
        locked = current_showtime(showtime["id"])
        assert locked["status"] == "LOCKED", f"expected LOCKED, got {locked['status']}"
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], locked["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SHOWTIME_LOCKED)

    def test_locked_showtime_still_allows_checkin(self, api):
        """PRD §3.6: "the `ON_SALE → LOCKED` transition rejects any further
        reservation creation or confirmation at the state gate with
        `ERR_SHOWTIME_LOCKED`, while check-ins remain allowed."
        PRD §3.5: "The showtime must be `ON_SALE` or `LOCKED`"

        Design: Corner/state_machines/showtime_locks_ten_minutes_before_start
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="lk2@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        reservation = create_confirmed_reservation(member, sub, showtime)
        set_clock("2026-09-02T18:55:00Z")  # inside LOCKED zone and check-in window
        checked = get_success_data(api.check_in_reservation(reservation["id"], STAFF))
        assert checked["status"] == "CHECKED_IN"


class TestCrossEntityStateDependency:

    def test_reservation_blocked_while_subscription_paused(self, api):
        """PRD §3.3: "While `PAUSED`, no new reservations may be created
        against the subscription — existing `HELD` or `CONFIRMED` reservations
        remain valid"

        Design: Difficulty/cross_entity_state_dependency/reservation_blocked_while_subscription_paused
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m14@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        get_success_data(api.pause_subscription(
            sub["id"], {"pause_days": 7}, make_member_headers(member["id"])))
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        st_after = current_showtime(showtime["id"])
        assert st_after["seats_held_subscription"] == 0

    def test_paused_subscription_blocks_despite_available_credits(self, api):
        """PRD §3.4: "so `credits_available` may be positive while paused —
        reservations remain blocked by state validation, not by credit
        exhaustion."

        Design: Difficulty/cross_entity_state_dependency/reservation_blocked_while_subscription_paused
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m14b@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        get_success_data(api.pause_subscription(
            sub["id"], {"pause_days": 7}, make_member_headers(member["id"])))
        # Bucket still has its full week-0 grant while paused
        resp = api.list_subscription_buckets(sub["id"], ADMIN)
        buckets, _meta = validate_paginated(resp)
        assert buckets[0]["credits_available"] == 3
        resp2 = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    def test_check_in_blocked_when_showtime_cancelled(self, api):
        """PRD §3.6: "every `HELD` or `CONFIRMED` reservation is cancelled with
        a full credit refund regardless of `cancel_deadline`"
        PRD §3.5: "Check-in is performed by `TheaterStaff` on a `CONFIRMED`
        reservation."

        Design: Difficulty/cross_entity_state_dependency/check_in_blocked_when_showtime_cancelled
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m15@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        reservation = create_confirmed_reservation(member, sub, showtime)
        bucket_id = reservation["bucket_id"]
        get_success_data(api.cancel_showtime(showtime["id"], ADMIN))
        set_clock("2026-09-02T19:00:00Z")  # inside what was the check-in window
        resp = api.check_in_reservation(reservation["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "CANCELLED"
        bucket = get_success_data(api.get_bucket(bucket_id, ADMIN))
        assert bucket["credits_used"] == 0, "force-majeure cancel must refund the credit"

    def test_showtime_cancel_cascades_held_reservation_to_cancelled(self, api):
        """PRD §3.6: "every `HELD` or `CONFIRMED` reservation is cancelled with
        a full credit refund regardless of `cancel_deadline`, and both
        seat-held counters reset to zero."

        Design: Difficulty/cross_entity_state_dependency/check_in_blocked_when_showtime_cancelled
        """
        set_clock()
        member, sub = _setup_active_sub(api, email="m15b@x.com")
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        reservation = create_held_reservation(member, sub, showtime)
        get_success_data(api.cancel_showtime(showtime["id"], ADMIN))
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "CANCELLED"
        st = current_showtime(showtime["id"])
        assert st["seats_held_subscription"] == 0
        assert st["seats_held_paid"] == 0
