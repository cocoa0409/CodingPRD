"""No-show strikes, the suspension ladder, and cascading suspensions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
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


def _premier_plan(api):
    return create_published_plan(
        tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
        max_rollover_credits=2, premium_format_allowed=True,
        max_future_reservations=6, loyalty_points_multiplier_pct=150,
        concession_discount_pct=15)


def _no_show_at(api, member, sub, auditorium_id, starts_at):
    """Confirm a reservation on a showtime starting at `starts_at`, then never
    check in. Caller advances the clock past the sweep afterwards."""
    st = create_on_sale_showtime(auditorium_id, starts_at=starts_at)
    return create_confirmed_reservation(member, sub, st)


class TestNoShowSuspensionCascade:

    def _three_no_shows_plus_future(self, api):
        """Member with quota-4 PREMIER plan holds CONFIRMED reservations on
        showtimes 09-02/03/04 (all swept to NO_SHOW) plus one future 09-06
        CONFIRMED reservation. Clock ends at 2026-09-05T12:00:00Z."""
        set_clock()
        plan = _premier_plan(api)
        theater, auditorium = create_theater_with_auditorium(seat_count=10)
        sts = [create_on_sale_showtime(auditorium["id"], film_title=f"F{i}",
                                       starts_at=f"2026-09-0{d}T19:00:00Z")
               for i, d in enumerate((2, 3, 4, 6), start=1)]
        member = create_active_member(email="m8@x.com", full_name="M Eight")
        sub = enroll_member(member["id"], plan["id"])
        rs = [create_confirmed_reservation(member, sub, st) for st in sts]
        set_clock("2026-09-05T12:00:00Z")
        return member, sub, rs

    def test_no_show_strike_to_suspension_cascade(self, api):
        """PRD §3.5: "A `CONFIRMED` reservation that is never checked in is
        swept to `NO_SHOW` once the clock passes `starts_at` plus 30 minutes of
        grace (`NO_SHOW_GRACE_MINUTES`)."
        PRD §3.10: "At 3 or more active strikes (`SUSPENSION_THRESHOLD`), the
        member's account transitions `ACTIVE → SUSPENDED` with
        `suspended_until` set thirty days (`SUSPENSION_DAYS`) ahead."

        Design: Difficulty/transitive_cascade/no_show_strike_to_suspension_cascade
        """
        member, sub, rs = self._three_no_shows_plus_future(api)
        statuses = [get_success_data(api.get_reservation(r["id"], SERVICES))["status"]
                    for r in rs]
        assert statuses[:3] == ["NO_SHOW", "NO_SHOW", "NO_SHOW"], (
            f"first three must be swept to NO_SHOW, got {statuses}")
        assert statuses[3] == "CANCELLED", (
            "future reservation must be cancelled by the suspension cascade, "
            f"got {statuses[3]}")
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["status"] == "SUSPENDED"
        assert m["no_show_strikes_active"] == 3
        # Third strike issued at the third no-show sweep (09-05T12:00:00Z clock
        # advance; PRD pins issued_at to the sweep instant), so
        # suspended_until = 09-05T12:00 + 30d = 10-05T12:00.
        assert m["suspended_until"] == "2026-10-05T12:00:00.000Z"
        s = get_success_data(api.get_subscription(sub["id"], SERVICES))
        assert s["status"] == "PAUSED", "suspension must force-pause the subscription"
        assert s["pause_resume_at"] == "2026-10-05T12:00:00.000Z"

    def test_no_show_never_refunds_but_cascade_cancel_refunds(self, api):
        """PRD §3.5: "the consumed credit is not refunded"
        PRD §3.10: "Every reservation the member holds in `HELD` or `CONFIRMED`
        is cancelled, with each credit refunded to its originating bucket only
        when that bucket's posture is `OPEN`"

        Design: Difficulty/transitive_cascade/no_show_strike_to_suspension_cascade
        """
        member, sub, rs = self._three_no_shows_plus_future(api)
        buckets, _meta = validate_paginated(
            api.list_subscription_buckets(sub["id"], ADMIN))
        week0 = buckets[0]
        # At the suspension instant the week-0 bucket is EXHAUSTED (all 4
        # credits consumed, week still open), so the cascade cancel of the
        # future reservation forfeits its credit: the 3 NO_SHOW debits are
        # forfeited by the no-show rule and the fourth stays consumed.
        assert week0["credits_used"] == 4, (
            f"EXHAUSTED bucket forfeits the cascade-cancelled credit — "
            f"credits_used {week0['credits_used']} != 4")


class TestSuspensionAutoLift:

    def _suspended_member(self, api):
        """Member driven to SUSPENDED by three no-shows; subscription
        force-paused. Returns (member, sub). Clock at 2026-09-05T12:00:00Z."""
        set_clock()
        plan = _premier_plan(api)
        theater, auditorium = create_theater_with_auditorium(seat_count=10)
        member = create_active_member(email="lift@x.com", full_name="LIFT")
        sub = enroll_member(member["id"], plan["id"])
        for d in (2, 3, 4):
            _no_show_at(api, member, sub, auditorium["id"],
                        starts_at=f"2026-09-0{d}T19:00:00Z")
        set_clock("2026-09-05T12:00:00Z")
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["status"] == "SUSPENDED"
        return member, sub

    def test_suspension_auto_lifts_at_suspended_until(self, api):
        """PRD §3.10: "When the clock reaches `suspended_until`, or when
        `MemberServices` lifts the suspension early by explicit request (which
        carries no precondition), the member returns to `ACTIVE`,
        `suspended_until` clears to null, and a subscription that was paused
        solely because of the suspension — recognizable because its
        `pause_resume_at` equals the suspension's `suspended_until` —
        auto-resumes to `ACTIVE` alongside it."

        Design: Corner/state_machines/suspension_auto_lifts_at_suspended_until
        """
        member, sub = self._suspended_member(api)
        set_clock("2026-10-05T12:00:01Z")
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["status"] == "ACTIVE", f"expected ACTIVE after lift, got {m['status']}"
        assert m["suspended_until"] is None
        s = get_success_data(api.get_subscription(sub["id"], SERVICES))
        assert s["status"] == "ACTIVE", "suspension-driven pause must auto-resume"

    def test_manual_unsuspend_resumes_suspension_paused_subscription(self, api):
        """PRD §3.10: "When the clock reaches `suspended_until`, or when
        `MemberServices` lifts the suspension early by explicit request (which
        carries no precondition), the member returns to `ACTIVE`"

        Design: Corner/state_machines/suspension_auto_lifts_at_suspended_until
        """
        member, sub = self._suspended_member(api)
        get_success_data(api.unsuspend_member(member["id"], SERVICES))
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["status"] == "ACTIVE"
        assert m["suspended_until"] is None
        s = get_success_data(api.get_subscription(sub["id"], SERVICES))
        assert s["status"] == "ACTIVE"


class TestMemberSuspendedGate:

    def _suspended_member_with_future_showtime(self, api):
        """SUSPENDED member (three no-shows), plus a future ON_SALE showtime
        created after the suspension. Clock stays before suspended_until."""
        set_clock()
        plan = _premier_plan(api)
        theater, auditorium = create_theater_with_auditorium(seat_count=10)
        member = create_active_member(email="sg@x.com", full_name="SG")
        sub = enroll_member(member["id"], plan["id"])
        for d in (2, 3, 4):
            _no_show_at(api, member, sub, auditorium["id"],
                        starts_at=f"2026-09-0{d}T19:00:00Z")
        set_clock("2026-09-05T12:00:00Z")
        future = create_on_sale_showtime(auditorium["id"],
                                         starts_at="2026-09-07T19:00:00Z")
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["status"] == "SUSPENDED"
        return member, sub, future

    def test_member_suspended_gate_blocks_reservation(self, api):
        """PRD §3.5: "The member must be `ACTIVE` — a `SUSPENDED` member is
        rejected with `ERR_MEMBER_SUSPENDED` even if their subscription row
        still reads `ACTIVE`."

        Design: Corner/validations/member_suspended_gate_blocks_reservation
        """
        member, sub, future = self._suspended_member_with_future_showtime(api)
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], future["id"], future["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)

    def test_member_suspended_gate_blocks_concession_purchase(self, api):
        """PRD §3.9: "The member must be `ACTIVE` — a suspended member's
        purchase is rejected with `ERR_MEMBER_SUSPENDED`."

        Design: Corner/validations/member_suspended_gate_blocks_reservation
        """
        member, sub, future = self._suspended_member_with_future_showtime(api)
        theater_id = get_success_data(api.get_showtime(future["id"], ADMIN))["auditorium_id"]
        # resolve theater via auditorium
        aud = get_success_data(api.get_auditorium(theater_id, ADMIN))
        resp = api.create_concession_purchase(
            {"member_id": member["id"], "theater_id": aud["theater_id"],
             "pre_discount_cents": 1000},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
