"""Subscription lifecycle and weekly credit bucket claims."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
    create_on_sale_showtime,
    create_published_plan,
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


def _bucket_for_week(api, subscription_id, week_index):
    resp = api.list_subscription_buckets(subscription_id, ADMIN)
    rows, _meta = validate_paginated(resp)
    for row in rows:
        if row["week_index"] == week_index:
            return row
    raise AssertionError(f"no bucket with week_index {week_index}: {rows}")


class TestBucketGrantVariants:

    def test_fresh_enrollment_week0_bucket_fields(self, api):
        """PRD §3.4: "The fresh-enrollment variant applies to week zero of a
        new subscription: `rollover_in` is unconditionally zero (there is no
        previous week), and `base_granted` is the full weekly quota regardless
        of which day within the week enrollment occurs."
        PRD §3.3: "On success the subscription is created `ACTIVE` with
        `cycle_anchor_date` set to the enrollment date"

        Design: Difficulty/dual_variant_calc/weekly_bucket_fresh_enrollment_vs_paused_week_rollover
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3, max_rollover_credits=2)
        member = create_active_member(email="w0@x.com", full_name="W Zero")
        sub = enroll_member(member["id"], plan["id"])
        assert sub["cycle_anchor_date"] == "2026-09-01"
        bucket = _bucket_for_week(api, sub["id"], 0)
        assert bucket["base_granted"] == 3, f"base_granted {bucket['base_granted']} != 3"
        assert bucket["rollover_in"] == 0, f"rollover_in {bucket['rollover_in']} != 0"
        assert bucket["credits_available"] == 3

    def test_paused_week_rollover_carries_rollover_but_zero_grant(self, api):
        """PRD §3.4: "The paused-week variant applies when the subscription is
        `PAUSED` at the week-open instant: `base_granted` is zero, but
        `rollover_in` is still carried from the previous week as usual, so
        `credits_available` may be positive while paused"
        PRD §3.4: "take that bucket's `base_granted` plus its `rollover_in`
        minus its `credits_used`, cap the result at the plan's
        `max_rollover_credits`, and never let it fall below zero."

        Design: Difficulty/dual_variant_calc/weekly_bucket_fresh_enrollment_vs_paused_week_rollover
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3, max_rollover_credits=2)
        _theater, _auditorium, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-03T19:00:00Z"})
        member = create_active_member(email="pw@x.com", full_name="P Week")
        sub = enroll_member(member["id"], plan["id"])
        # Consume exactly 2 credits in week 0 (3+0-2 = 1 unused)
        st = showtime
        for _ in range(2):
            create_confirmed_reservation(member, sub, st)
            st = current_showtime(st["id"])
        # Pause, then cross the week boundary while PAUSED
        set_clock("2026-09-05T00:00:00Z")
        get_success_data(api.pause_subscription(
            sub["id"], {"pause_days": 14}, make_member_headers(member["id"])))
        set_clock("2026-09-08T00:00:00Z")
        week0 = _bucket_for_week(api, sub["id"], 0)
        week1 = _bucket_for_week(api, sub["id"], 1)
        assert week0["rollover_in"] == 0, "fresh-enrollment week must not carry rollover"
        assert week1["base_granted"] == 0, f"paused-week base_granted {week1['base_granted']} != 0"
        # min(3 + 0 - 2, cap 2) = 1
        assert week1["rollover_in"] == 1, f"paused-week rollover_in {week1['rollover_in']} != 1"
        assert week1["posture"] == "OPEN"
        assert week1["credits_available"] == 1


class TestSubscriptionLifecycle:

    def test_pause_resume_cycle_repeats_across_billing_cycles(self, api):
        """PRD §3.3: "Resumption happens two ways. The system auto-resumes the
        subscription when the clock reaches `pause_resume_at`, or the member
        resumes early by explicit request"
        PRD §2.5: "crossing a monthly billing-cycle boundary (the subscription's
        `cycle_anchor_date` plus a whole number of 30-day cycles) increments
        `current_cycle_index` and resets `pause_count_in_cycle` to zero."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="pc@x.com", full_name="P Cycle")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        set_clock("2026-09-02T00:00:00Z")
        paused = get_success_data(api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr))
        assert paused["status"] == "PAUSED"
        # Auto-resume fires when the clock reaches pause_resume_at
        set_clock("2026-09-09T00:00:01Z")
        # Cross the monthly billing-cycle boundary (anchor + 30 days)
        set_clock("2026-10-01T00:00:00Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], SERVICES))
        assert sub_now["status"] == "ACTIVE", f"expected ACTIVE after auto-resume, got {sub_now['status']}"
        assert sub_now["pause_count_in_cycle"] == 0, \
            f"pause_count_in_cycle {sub_now['pause_count_in_cycle']} != 0 after cycle rollover"
        # The cycle is repeatable: a second pause succeeds in the new cycle
        paused2 = get_success_data(api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr))
        assert paused2["status"] == "PAUSED"

    def test_pause_resume_auto_resume_restores_active_status(self, api):
        """PRD §3.3: "Either path clears `paused_at` and `pause_resume_at` to
        null and restores `ACTIVE` status"

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="ar@x.com", full_name="A Resume")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        get_success_data(api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr))
        set_clock("2026-09-08T00:00:01Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], SERVICES))
        assert sub_now["status"] == "ACTIVE"
        assert sub_now["paused_at"] is None
        assert sub_now["pause_resume_at"] is None

    def test_pause_days_below_range_rejected(self, api):
        """PRD §3.3: "The requested `pause_days` must lie between 7 and 30
        inclusive; anything outside that range is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/pause_days_out_of_range_invalid_request
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="pd@x.com", full_name="P Days")
        sub = enroll_member(member["id"], plan["id"])
        resp = api.pause_subscription(
            sub["id"], {"pause_days": 3}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pause_days_above_range_rejected(self, api):
        """PRD §3.3: "The requested `pause_days` must lie between 7 and 30
        inclusive; anything outside that range is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/pause_days_out_of_range_invalid_request
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="pd2@x.com", full_name="P Days Two")
        sub = enroll_member(member["id"], plan["id"])
        resp = api.pause_subscription(
            sub["id"], {"pause_days": 31}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_pause_in_cycle_rejected(self, api):
        """PRD §3.3: "is permitted at most once per billing cycle: if
        `pause_count_in_cycle` has already reached 1, the request fails with
        `ERR_PAUSE_LIMIT_REACHED`."

        Design: Corner/validations/second_pause_in_cycle_rejected
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="sp@x.com", full_name="S Pause")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        get_success_data(api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr))
        get_success_data(api.resume_subscription(sub["id"], mhdr))
        resp = api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr)
        validate_error(resp, ApiErrorId.ERR_PAUSE_LIMIT_REACHED)

    def test_subscription_cancelled_terminal_no_pause(self, api):
        """PRD §3.3: "moves the subscription to `CANCELLED`, which is terminal
        for that subscription row."
        PRD §2.10: "(5) state admissibility of the requested transition"

        Design: Corner/state_machines/subscription_cancelled_terminal_no_pause
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="inv@x.com", full_name="INV")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        get_success_data(api.cancel_subscription(sub["id"], mhdr))
        resp = api.pause_subscription(sub["id"], {"pause_days": 7}, mhdr)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEnrollmentGates:

    def test_enroll_creates_week0_bucket_side_effect(self, api):
        """PRD §3.3: "On success the subscription is created `ACTIVE` with
        `cycle_anchor_date` set to the enrollment date, `current_cycle_index`
        at zero, and the current week's credit bucket granted under the
        fresh-enrollment rule (§3.4)."

        Design: Corner/endpoints/enroll_creates_week0_bucket_side_effect
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3)
        member = create_active_member(email="en@x.com", full_name="EN")
        sub = enroll_member(member["id"], plan["id"])
        assert sub["status"] == "ACTIVE"
        assert sub["cycle_anchor_date"] == "2026-09-01"
        assert sub["current_cycle_index"] == 0
        resp = api.list_subscription_buckets(sub["id"], ADMIN)
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, f"expected exactly 1 bucket, got {meta['total_count']}"
        bucket = rows[0]
        assert bucket["week_index"] == 0
        assert bucket["base_granted"] == 3
        assert bucket["rollover_in"] == 0
        assert bucket["credits_available"] == 3

    def test_rejoin_after_lock_window_succeeds(self, api):
        """PRD §3.3: "if any of the member's `CANCELLED` subscriptions still
        has `rejoin_locked_until` in the future (the greatest such instant
        governs), enrollment is rejected with `ERR_REJOIN_LOCKED`"
        PRD §3.3: "After the lock window has elapsed, the member may enroll
        again on a fresh subscription row."

        Design: Corner/validations/rejoin_after_lock_window_succeeds
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="rj@x.com", full_name="RJ")
        sub = enroll_member(member["id"], plan["id"])
        mhdr = make_member_headers(member["id"])
        get_success_data(api.cancel_subscription(sub["id"], mhdr))
        # One day before the lock elapses (locked until 2026-10-01)
        set_clock("2026-09-30T00:00:00Z")
        resp = api.enroll_subscription(member["id"], {"plan_id": plan["id"]}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_REJOIN_LOCKED)
        # Just past the lock instant
        set_clock("2026-10-01T00:00:01Z")
        resp2 = api.enroll_subscription(member["id"], {"plan_id": plan["id"]}, SERVICES)
        sub2 = validate_success(resp2, expected_status=201)
        assert sub2["status"] == "ACTIVE"

    def test_plan_retired_blocks_new_enrollment(self, api):
        """PRD §3.2: "from that moment new subscriptions referencing the plan
        are rejected with `ERR_PLAN_NOT_ENROLLABLE`"

        Design: Corner/validations/plan_retired_blocks_new_enrollment
        """
        set_clock()
        plan = create_published_plan()
        get_success_data(api.retire_plan(plan["id"], ADMIN))
        member = create_active_member(email="rt@x.com", full_name="RT")
        resp = api.enroll_subscription(member["id"], {"plan_id": plan["id"]}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ENROLLABLE)

    def test_enroll_rejoin_locked_beats_plan_not_enrollable(self, api):
        """PRD §2.10: "(17) plan enrollability — which is deliberately
        evaluated after the rejoin lock, so an enrollment that violates both
        surfaces `ERR_REJOIN_LOCKED`, not `ERR_PLAN_NOT_ENROLLABLE`."

        Design: Difficulty/priority_pair_validation_conflict/enroll_rejoin_locked_and_plan_retired_temporal_beats_referential
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="m11@x.com", full_name="M Eleven")
        sub = enroll_member(member["id"], plan["id"])
        set_clock("2026-09-10T00:00:00Z")
        get_success_data(api.cancel_subscription(sub["id"], make_member_headers(member["id"])))
        get_success_data(api.retire_plan(plan["id"], ADMIN))
        set_clock("2026-09-12T00:00:00Z")
        resp = api.enroll_subscription(member["id"], {"plan_id": plan["id"]}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_REJOIN_LOCKED)
        subs, meta = validate_paginated(
            api.list_member_subscriptions(member["id"], SERVICES))
        assert meta["total_count"] == 1, "no new subscription row may be created"

    def test_rejoin_lock_blocks_enrollment_while_active(self, api):
        """PRD §3.3: "if any of the member's `CANCELLED` subscriptions still
        has `rejoin_locked_until` in the future (the greatest such instant
        governs), enrollment is rejected with `ERR_REJOIN_LOCKED`"

        Design: Difficulty/priority_pair_validation_conflict/enroll_rejoin_locked_and_plan_retired_temporal_beats_referential
        """
        set_clock()
        plan = create_published_plan()
        other_plan = create_published_plan()
        member = create_active_member(email="rl@x.com", full_name="R Lock")
        sub = enroll_member(member["id"], plan["id"])
        get_success_data(api.cancel_subscription(sub["id"], make_member_headers(member["id"])))
        # Lock active; target plan still PUBLISHED — rejoin lock alone rejects
        resp = api.enroll_subscription(member["id"], {"plan_id": other_plan["id"]}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_REJOIN_LOCKED)


class TestRolloverCap:

    def test_rollover_capped_at_max_rollover_credits(self, api):
        """PRD §3.4: "take that bucket's `base_granted` plus its `rollover_in`
        minus its `credits_used`, cap the result at the plan's
        `max_rollover_credits`, and never let it fall below zero."

        Design: Corner/calculations/rollover_capped_at_max_rollover_credits
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3, max_rollover_credits=2)
        member = create_active_member(email="rc@x.com", full_name="RC")
        sub = enroll_member(member["id"], plan["id"])
        # Week 0 untouched: 3 unused; cap 2 -> rollover_in == 2
        set_clock("2026-09-08T00:00:00Z")
        week1 = _bucket_for_week(api, sub["id"], 1)
        assert week1["rollover_in"] == 2, f"rollover_in {week1['rollover_in']} != 2"
        assert week1["base_granted"] == 3
        assert week1["credits_available"] == 5

    def test_rollover_below_cap_carries_full_unused(self, api):
        """PRD §3.4: "take that bucket's `base_granted` plus its `rollover_in`
        minus its `credits_used`, cap the result at the plan's
        `max_rollover_credits`, and never let it fall below zero."

        Design: Corner/calculations/rollover_capped_at_max_rollover_credits
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3, max_rollover_credits=2)
        _theater, _auditorium, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-06T19:00:00Z"})
        member = create_active_member(email="rc2@x.com", full_name="RC Two")
        sub = enroll_member(member["id"], plan["id"])
        # Consume 2 of 3 in week 0 -> 1 unused, under the cap
        st = showtime
        for _ in range(2):
            create_confirmed_reservation(member, sub, st)
            st = current_showtime(st["id"])
        set_clock("2026-09-08T00:00:00Z")
        week1 = _bucket_for_week(api, sub["id"], 1)
        assert week1["rollover_in"] == 1, f"rollover_in {week1['rollover_in']} != 1"
        assert week1["credits_available"] == 4
