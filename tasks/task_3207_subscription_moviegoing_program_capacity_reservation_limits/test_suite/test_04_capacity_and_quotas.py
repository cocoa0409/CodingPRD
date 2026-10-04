"""Capacity, weekly quota, premium eligibility, and anti-hoarding claims."""
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
    create_auditorium_payload,
    current_showtime,
    earn_no_show_strike,
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


class TestDisplacementCap:

    def _setup_opening_weekend_showtime(self, api):
        """10-seat auditorium, DOLBY opening-weekend showtime with 40% cap,
        PREMIER plan; returns (plan, showtime)."""
        set_clock("2026-09-04T00:00:00Z")
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=3,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, _aud = create_theater_with_auditorium(
            seat_count=10, formats=("STANDARD", "DOLBY"))
        showtime = create_on_sale_showtime(
            _aud["id"], film_title="Blockbuster", studio_code="DIS",
            format="DOLBY", starts_at="2026-09-05T20:00:00Z",
            base_price_cents=1400, premium_surcharge_cents=400,
            opening_weekend=True, subscriber_displacement_cap_pct=40)
        return plan, showtime

    def _book_member_on(self, api, plan, showtime, email):
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        st = current_showtime(showtime["id"])
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], st["id"], st["version"]),
            make_member_headers(member["id"]))
        return resp

    def test_displacement_cap_inclusive_boundary(self, api):
        """PRD §3.7: "a new subscription reservation is allowed only if, after
        taking the seat, the subscriber share stays within the cap: one hundred
        times the sum of `seats_held_subscription` plus one must be less than
        or equal to `subscriber_displacement_cap_pct` times the auditorium's
        `seat_count`."

        Design: Difficulty/combinatorial_formula/displacement_cap_nested_min_max_opening_weekend
        """
        plan, showtime = self._setup_opening_weekend_showtime(api)
        for i, email in enumerate(["m3a@x.com", "m3b@x.com", "m3c@x.com"]):
            resp = self._book_member_on(api, plan, showtime, email)
            validate_success(resp, expected_status=201)
        # Fourth: (3+1)*100 = 400 <= 40*10 = 400 — inclusive boundary succeeds
        resp4 = self._book_member_on(api, plan, showtime, "m3d@x.com")
        validate_success(resp4, expected_status=201)
        st = current_showtime(showtime["id"])
        assert st["seats_held_subscription"] == 4

    def test_displacement_cap_breach_rejected_with_seats_free(self, api):
        """PRD §3.7: "a new subscription reservation is allowed only if, after
        taking the seat, the subscriber share stays within the cap: one hundred
        times the sum of `seats_held_subscription` plus one must be less than
        or equal to `subscriber_displacement_cap_pct` times the auditorium's
        `seat_count`."
        PRD §3.7: "A failure of either the availability check or the
        displacement gate is reported as `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/displacement_cap_nested_min_max_opening_weekend
        """
        plan, showtime = self._setup_opening_weekend_showtime(api)
        for email in ["m4a@x.com", "m4b@x.com", "m4c@x.com", "m4d@x.com"]:
            resp = self._book_member_on(api, plan, showtime, email)
            validate_success(resp, expected_status=201)
        # Fifth: (4+1)*100 = 500 > 400 — cap blocks even with physical seats free
        resp5 = self._book_member_on(api, plan, showtime, "m4e@x.com")
        validate_error(resp5, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        st = current_showtime(showtime["id"])
        assert st["seats_available"] == 6, "physical seats remain — the cap, not the house, blocks"


class TestWeeklyQuotaBoundary:

    def _setup_quota_three_with_two_used(self, api, email="m12@x.com"):
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3, max_rollover_credits=2)
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        st = showtime
        for _ in range(2):
            create_confirmed_reservation(member, sub, st)
            st = current_showtime(st["id"])
        return member, sub, st

    def test_weekly_quota_last_credit_boundary(self, api):
        """PRD §3.5: "The current week's bucket must be in posture `OPEN` with
        at least one credit available, else `ERR_WEEKLY_QUOTA_EXHAUSTED`."
        PRD §3.4: "`EXHAUSTED` when `credits_available` reaches zero while the
        week is still open"

        Design: Difficulty/boundary_precision_check/weekly_quota_last_credit_boundary
        """
        member, sub, st = self._setup_quota_three_with_two_used(api)
        # Third reservation at credits_available == 1 succeeds
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], st["id"], st["version"]),
            make_member_headers(member["id"]))
        r3 = validate_success(resp, expected_status=201)
        bucket = get_success_data(api.get_bucket(r3["bucket_id"], ADMIN))
        assert bucket["credits_available"] == 0
        assert bucket["posture"] == "EXHAUSTED", f"expected EXHAUSTED, got {bucket['posture']}"

    def test_weekly_quota_exhausted_fourth_reservation_rejected(self, api):
        """PRD §3.5: "The current week's bucket must be in posture `OPEN` with
        at least one credit available, else `ERR_WEEKLY_QUOTA_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/weekly_quota_last_credit_boundary
        """
        member, sub, st = self._setup_quota_three_with_two_used(api)
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], st["id"], st["version"]),
            make_member_headers(member["id"]))
        validate_success(resp, expected_status=201)
        st2 = current_showtime(st["id"])
        resp4 = api.create_reservation(
            create_reservation_payload(sub["id"], st2["id"], st2["version"]),
            make_member_headers(member["id"]))
        validate_error(resp4, ApiErrorId.ERR_WEEKLY_QUOTA_EXHAUSTED)


class TestPremiumFormat:

    def test_premium_format_rejected_on_basic_plan(self, api):
        """PRD §3.5: "Premium-format showings — any showtime whose `format` is
        not `STANDARD`, a fact denormalized onto the reservation as
        `is_premium_format` — require the plan's `premium_format_allowed` to be
        true, else `ERR_PREMIUM_NOT_INCLUDED`."

        Design: Corner/calculations/premium_format_rejected_on_basic_plan
        """
        set_clock()
        plan = create_published_plan(premium_format_allowed=False)
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            formats=("STANDARD", "IMAX"),
            showtime_overrides={
                "format": "IMAX", "starts_at": "2026-09-06T19:00:00Z",
                "premium_surcharge_cents": 500,
            })
        member = create_active_member(email="pf@x.com", full_name="PF")
        sub = enroll_member(member["id"], plan["id"])
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_INCLUDED)
        st = current_showtime(showtime["id"])
        assert st["seats_held_subscription"] == 0, "rejected creation must not hold a seat"

    def test_premium_format_rejected_no_credit_debited(self, api):
        """PRD §3.5: "Premium-format showings — any showtime whose `format` is
        not `STANDARD`, a fact denormalized onto the reservation as
        `is_premium_format` — require the plan's `premium_format_allowed` to be
        true, else `ERR_PREMIUM_NOT_INCLUDED`."

        Design: Corner/calculations/premium_format_rejected_on_basic_plan
        """
        set_clock()
        plan = create_published_plan(premium_format_allowed=False)
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            formats=("STANDARD", "IMAX"),
            showtime_overrides={
                "format": "IMAX", "starts_at": "2026-09-06T19:00:00Z",
                "premium_surcharge_cents": 500,
            })
        member = create_active_member(email="pf2@x.com", full_name="PF2")
        sub = enroll_member(member["id"], plan["id"])
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], showtime["id"], showtime["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_INCLUDED)
        buckets, _meta = validate_paginated(api.list_subscription_buckets(sub["id"], ADMIN))
        assert buckets[0]["credits_used"] == 0, "rejected creation must not debit a credit"

    def test_premium_format_included_no_surcharge_on_premier(self, api):
        """PRD §3.11: "A `SUBSCRIPTION` line is valued at the flat studio
        contract rate of 899 cents (`STUDIO_CONTRACT_RATE_CENTS`) regardless of
        format, surcharge, or attendance — a checked-in admission and a no-show
        both count."
        PRD §3.5: "Premium-format showings — any showtime whose `format` is
        not `STANDARD`, a fact denormalized onto the reservation as
        `is_premium_format` — require the plan's `premium_format_allowed` to be
        true, else `ERR_PREMIUM_NOT_INCLUDED`."

        Design: Corner/calculations/premium_format_included_no_surcharge_on_premier
        """
        set_clock()
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, _aud = create_theater_with_auditorium(
            seat_count=10, formats=("STANDARD", "IMAX"))
        showtime = create_on_sale_showtime(
            _aud["id"], format="IMAX", starts_at="2026-09-02T19:00:00Z",
            base_price_cents=1200, premium_surcharge_cents=500)
        member = create_active_member(email="pi@x.com", full_name="PI")
        sub = enroll_member(member["id"], plan["id"])
        reservation = create_confirmed_reservation(member, sub, showtime)
        assert reservation["is_premium_format"] is True
        set_clock("2026-09-02T19:05:00Z")
        get_success_data(api.check_in_reservation(reservation["id"],
                                                  TEST_USERS["theater_staff_headers"]))
        report = get_success_data(api.create_settlement_report(
            theater["id"],
            {"studio_code": "WB", "period_start": "2026-09-02T00:00:00Z",
             "period_end": "2026-09-03T00:00:00Z"},
            TEST_USERS["theater_staff_headers"]))
        line = get_success_data(api.add_settlement_line(
            report["id"], {"reservation_id": reservation["id"]},
            TEST_USERS["theater_staff_headers"]))
        assert line["line_kind"] == "SUBSCRIPTION"
        assert line["reported_value_cents"] == 899, (
            f"subscription line must be the flat contract rate 899, got "
            f"{line['reported_value_cents']}")


class TestAntiHoardingHalvedCap:

    def _setup_two_strikes_and_three_future(self, api):
        """PREMIER (quota 4, max_future 6); member earns 2 no-show strikes,
        then holds 3 CONFIRMED future reservations. Returns (member, sub,
        auditorium, future_showtime_for_fourth)."""
        set_clock()
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, auditorium = create_theater_with_auditorium(seat_count=10)
        member = create_active_member(email="hf@x.com", full_name="HF")
        sub = enroll_member(member["id"], plan["id"])
        # Two no-show strikes (week 0)
        earn_no_show_strike(member, sub, auditorium["id"],
                            starts_at="2026-09-02T19:00:00Z",
                            sweep_clock="2026-09-02T19:30:00Z")
        earn_no_show_strike(member, sub, auditorium["id"],
                            starts_at="2026-09-03T19:00:00Z",
                            sweep_clock="2026-09-03T19:30:00Z")
        # Pause across the week-0 to week-1 boundary so week 1 opens with
        # base_granted 0 (paused-week variant), then resume mid-week-1: the
        # top-up restores the full weekly quota for the current week, so the
        # three future bookings below debit week 1 rather than the two
        # credits still open in week 0.
        get_success_data(api.pause_subscription(
            sub["id"], {"pause_days": 7}, make_member_headers(member["id"])))
        set_clock("2026-09-08T12:00:00Z")  # week 1 open, subscription PAUSED
        get_success_data(api.resume_subscription(
            sub["id"], make_member_headers(member["id"])))
        # Three future CONFIRMED reservations across later weeks
        for starts_at in ("2026-09-10T19:00:00Z", "2026-09-11T19:00:00Z",
                          "2026-09-12T19:00:00Z"):
            st = create_on_sale_showtime(auditorium["id"], starts_at=starts_at)
            create_confirmed_reservation(member, sub, st)
        fourth = create_on_sale_showtime(auditorium["id"],
                                         starts_at="2026-09-13T19:00:00Z")
        return member, sub, fourth

    def test_two_strikes_halve_future_reservation_cap(self, api):
        """PRD §3.8: "a member carrying exactly 2 active no-show strikes
        (`FLAG_LEVEL`) sees their effective cap halved, computed as the plan's
        `max_future_reservations` divided by two and rounded down."
        PRD §3.8: "Breaching the effective cap rejects creation with
        `ERR_FUTURE_RESERVATION_LIMIT`."

        Design: Corner/calculations/two_strikes_halve_future_reservation_cap
        """
        member, sub, fourth = self._setup_two_strikes_and_three_future(api)
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["no_show_strikes_active"] == 2
        assert m["status"] == "ACTIVE", "two strikes must not suspend the member"
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], fourth["id"], fourth["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FUTURE_RESERVATION_LIMIT)

    def test_two_strikes_third_future_reservation_still_admitted(self, api):
        """PRD §3.8: "Creation requires that count to be strictly below the
        effective cap."
        PRD §3.8: "a member carrying exactly 2 active no-show strikes
        (`FLAG_LEVEL`) sees their effective cap halved, computed as the plan's
        `max_future_reservations` divided by two and rounded down."

        Design: Corner/calculations/two_strikes_halve_future_reservation_cap
        """
        set_clock()
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=4,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, auditorium = create_theater_with_auditorium(seat_count=10)
        member = create_active_member(email="hf2@x.com", full_name="HF2")
        sub = enroll_member(member["id"], plan["id"])
        earn_no_show_strike(member, sub, auditorium["id"],
                            starts_at="2026-09-02T19:00:00Z",
                            sweep_clock="2026-09-02T19:30:00Z")
        earn_no_show_strike(member, sub, auditorium["id"],
                            starts_at="2026-09-03T19:00:00Z",
                            sweep_clock="2026-09-03T19:30:00Z")
        # Pause across the week boundary and resume in week 1 so the future
        # bookings debit the topped-up week-1 bucket, not week 0's two
        # remaining credits.
        get_success_data(api.pause_subscription(
            sub["id"], {"pause_days": 7}, make_member_headers(member["id"])))
        set_clock("2026-09-08T12:00:00Z")
        get_success_data(api.resume_subscription(
            sub["id"], make_member_headers(member["id"])))
        # effective cap = floor(6/2) = 3; holds 2 -> third (count 2 < 3) admitted
        for starts_at in ("2026-09-10T19:00:00Z", "2026-09-11T19:00:00Z"):
            st = create_on_sale_showtime(auditorium["id"], starts_at=starts_at)
            create_confirmed_reservation(member, sub, st)
        third = create_on_sale_showtime(auditorium["id"],
                                        starts_at="2026-09-12T19:00:00Z")
        resp = api.create_reservation(
            create_reservation_payload(sub["id"], third["id"], third["version"]),
            make_member_headers(member["id"]))
        validate_success(resp, expected_status=201)
