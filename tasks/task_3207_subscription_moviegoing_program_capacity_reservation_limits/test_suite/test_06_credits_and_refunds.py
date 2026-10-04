"""Credit refund invariants, bucket forfeiture, and week-boundary semantics."""
from datetime import datetime, timezone

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


def _buckets(api, subscription_id):
    resp = api.list_subscription_buckets(subscription_id, ADMIN)
    rows, _meta = validate_paginated(resp)
    return {row["week_index"]: row for row in rows}


class TestCreditConservation:

    def _setup_pristine(self, api, email="m18@x.com"):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        return member, sub, showtime

    def test_bucket_credit_conservation_on_cancel_refund(self, api):
        """PRD §3.5: "when the bucket is `OPEN` or `EXHAUSTED`, its
        `credits_used` decreases by one"
        PRD §3.4: "`credits_available` is `base_granted` plus `rollover_in`
        minus `credits_used`, never negative."

        Design: Difficulty/compensating_invariant/bucket_credit_conservation_on_cancel_refund
        """
        member, sub, showtime = self._setup_pristine(api)
        reservation = create_held_reservation(member, sub, showtime)
        bucket_mid = get_success_data(api.get_bucket(reservation["bucket_id"], ADMIN))
        assert bucket_mid["credits_used"] == 1, "creation must debit one credit"
        get_success_data(api.cancel_reservation(
            reservation["id"], make_member_headers(member["id"])))
        bucket_after = get_success_data(api.get_bucket(reservation["bucket_id"], ADMIN))
        assert bucket_after["credits_used"] == 0, "within-window cancel must refund the credit"
        assert bucket_after["credits_available"] == 3, (
            "credit supply must return to the pre-reservation state — no drift")

    def test_cancel_releases_seat_back_to_showtime(self, api):
        """PRD §3.5: "Every cancellation that succeeds, from `HELD` or
        `CONFIRMED`, releases the seat by decrementing the showtime's
        `seats_held_subscription` by one."

        Design: Difficulty/compensating_invariant/bucket_credit_conservation_on_cancel_refund
        """
        member, sub, showtime = self._setup_pristine(api, email="m18b@x.com")
        reservation = create_confirmed_reservation(member, sub, showtime)
        mid = current_showtime(showtime["id"])
        assert mid["seats_held_subscription"] == 1
        assert mid["seats_available"] == 9
        get_success_data(api.cancel_reservation(
            reservation["id"], make_member_headers(member["id"])))
        after = current_showtime(showtime["id"])
        assert after["seats_held_subscription"] == 0
        assert after["seats_available"] == 10


class TestSubscriptionCancelCascade:

    def _three_confirmed_then_cancel(self, api, email="m9@x.com"):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        rs = []
        st = showtime
        for _ in range(3):
            rs.append(create_confirmed_reservation(member, sub, st))
            st = current_showtime(st["id"])
        return member, sub, st, rs

    def test_subscription_cancel_cascade_refunds_and_expires(self, api):
        """PRD §3.3: "Cancellation cascades: every reservation of the
        subscription still in `HELD` or `CONFIRMED` is force-cancelled with its
        credit refunded per the refund rule of §3.5 regardless of the
        member-facing cancellation window, and the current plus all future
        credit buckets are moved to posture `EXPIRED`."
        PRD §3.5: "System-cascade cancels — driven by subscription
        cancellation, member suspension, or showtime cancellation — carry no
        precondition and refund regardless of the deadline."

        Design: Difficulty/transitive_cascade/subscription_cancel_cascade
        """
        member, sub, st, rs = self._three_confirmed_then_cancel(api)
        get_success_data(api.cancel_subscription(sub["id"], make_member_headers(member["id"])))
        for r in rs:
            after = get_success_data(api.get_reservation(r["id"], SERVICES))
            assert after["status"] == "CANCELLED", (
                f"cascade must cancel every HELD/CONFIRMED reservation, got {after['status']}")
        st_after = current_showtime(st["id"])
        assert st_after["seats_held_subscription"] == 0
        week0 = _buckets(api, sub["id"])[0]
        assert week0["credits_used"] == 0, (
            "refunds run while the bucket is still OPEN, before the expiry pass")
        assert week0["posture"] == "EXPIRED"

    def test_subscription_cancel_sets_terminal_status_and_rejoin_lock(self, api):
        """PRD §3.3: "Cancelling stamps `cancelled_at`, sets
        `rejoin_locked_until` thirty days (the `REJOIN_WAIT_DAYS` constant)
        into the future, and moves the subscription to `CANCELLED`, which is
        terminal for that subscription row."

        Design: Difficulty/transitive_cascade/subscription_cancel_cascade
        """
        member, sub, _st, _rs = self._three_confirmed_then_cancel(api, email="m9b@x.com")
        cancelled = get_success_data(api.cancel_subscription(
            sub["id"], make_member_headers(member["id"])))
        assert cancelled["status"] == "CANCELLED"
        # rejoin_locked_until = cancel instant (2026-09-01T00:00) + 30 days.
        # Compare as datetimes so the PRD-mandated three-fractional-digit
        # serialization is accepted regardless of trailing-zero rendering.
        rejoin = datetime.fromisoformat(
            cancelled["rejoin_locked_until"].replace("Z", "+00:00"))
        assert rejoin == datetime(2026, 10, 1, tzinfo=timezone.utc), (
            f"rejoin_locked_until {cancelled['rejoin_locked_until']!r} != "
            "2026-10-01T00:00:00Z")
        assert cancelled["cancelled_at"] is not None


class TestExpiredBucketForfeiture:

    def _late_cancel_after_week0_expiry(self, api, email="eb@x.com"):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-20T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        reservation = create_confirmed_reservation(member, sub, showtime)
        # Week 0 [09-01, 09-08) is EXPIRED by 09-15 while the reservation
        # remains future-dated and CONFIRMED
        set_clock("2026-09-15T00:00:00Z")
        return member, sub, reservation

    def test_expired_bucket_forfeits_credit_on_late_cascade(self, api):
        """PRD §3.5: "when the bucket is `EXPIRED`, the credit is forfeited and
        `credits_used` is unchanged."

        Design: Corner/calculations/expired_bucket_forfeits_credit_on_late_cascade
        """
        member, sub, reservation = self._late_cancel_after_week0_expiry(api)
        get_success_data(api.cancel_subscription(sub["id"], make_member_headers(member["id"])))
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "CANCELLED"
        bucket = get_success_data(api.get_bucket(reservation["bucket_id"], ADMIN))
        assert bucket["posture"] == "EXPIRED"
        assert bucket["credits_used"] == 1, "EXPIRED buckets forfeit the refund"

    def test_expired_bucket_posture_before_cascade(self, api):
        """PRD §3.4: "`EXPIRED` once the clock has passed the week's end (or
        once a cancellation cascade has expired it early)."

        Design: Corner/calculations/expired_bucket_forfeits_credit_on_late_cascade
        """
        member, sub, reservation = self._late_cancel_after_week0_expiry(api, email="eb2@x.com")
        bucket = get_success_data(api.get_bucket(reservation["bucket_id"], ADMIN))
        assert bucket["week_index"] == 0
        assert bucket["posture"] == "EXPIRED", "week 0 must be EXPIRED once the clock passes its end"


class TestWeekBoundarySemantics:

    def _setup_at_week_boundary(self, api, email="m16@x.com"):
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-09T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        # Park the clock exactly at the half-open week boundary
        set_clock("2026-09-08T00:00:00Z")
        return member, sub, showtime

    def test_weekly_bucket_half_open_window_membership(self, api):
        """PRD §3.4: "week `week_index` k covers the seven-day span beginning
        at `cycle_anchor_date` plus 7 times k days"
        PRD §3.5: "the reservation is stamped with its `bucket_id`"

        Design: Difficulty/resource_temporal_overlap/weekly_bucket_half_open_window_membership
        """
        member, sub, showtime = self._setup_at_week_boundary(api)
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        reservation = validate_success(resp, expected_status=201)
        buckets = _buckets(api, sub["id"])
        assert buckets[0]["credits_used"] == 0, "boundary instant must not debit week 0"
        assert buckets[0]["posture"] == "EXPIRED", "week 0 is EXPIRED at its end instant"
        assert buckets[1]["credits_used"] == 1
        assert reservation["bucket_id"] == buckets[1]["id"], (
            "a creation at exactly the boundary debits week 1's bucket")

    def test_week_boundary_rollover_capped_and_carried(self, api):
        """PRD §3.4: "take that bucket's `base_granted` plus its `rollover_in`
        minus its `credits_used`, cap the result at the plan's
        `max_rollover_credits`, and never let it fall below zero."

        Design: Difficulty/resource_temporal_overlap/weekly_bucket_half_open_window_membership
        """
        member, sub, showtime = self._setup_at_week_boundary(api, email="m16b@x.com")
        # Week 0 untouched -> 3 unused, capped to 2 on rollover
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        validate_success(resp, expected_status=201)
        week1 = _buckets(api, sub["id"])[1]
        assert week1["rollover_in"] == 2, "rollover clamps at the plan cap"
        assert week1["credits_used"] == 1
