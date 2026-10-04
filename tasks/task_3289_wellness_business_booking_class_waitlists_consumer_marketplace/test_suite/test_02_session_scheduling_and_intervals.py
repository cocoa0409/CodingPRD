"""Session scheduling, derived pricing, listing and the interval constraints."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    TEST_USERS,
    create_payroll_period,
    create_session,
    create_staff,
    create_template,
    current_subscription_version,
    ensure_tier,
    make_client_headers,
    make_staff_member_headers,
    make_studio_owner_headers,
    same_instant,
    set_clock,
    setup_studio_roster,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSessionDerivation:

    def test_session_create_derives_end_price_and_posture(self, api):
        """PRD §3.2: "The session begins in `SCHEDULED`, its `end_at` is derived from `start_at` plus the format's `duration_minutes`, and its `capacity` defaults to the format's `default_capacity` when the caller omits it."
        PRD §3.7: "The studio list_price_cents is the base multiplied by the
        off-peak factor and by the tier factor, divided by one hundred million,
        truncated to whole cents, and then raised to the tier's floor."
        PRD §3.7: "The `marketplace_price_cents` for the same seat grosses up the platform commission: it is `list_price_cents` multiplied by 10000 divided by 10000 minus the tier's `marketplace_commission_bps`, rounded upward to whole cents."

        Design: Corner/entities/class_session_create_derives_end_price_and_posture_from_the_template
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        session = ctx["session"]

        assert same_instant(session["end_at"], "2026-06-20T17:50:00Z"), \
            "end_at is start_at plus the 50-minute duration"
        assert session["list_price_cents"] == 3360, \
            "4000 base x 0.80 off-peak x 1.05 GROWTH, floored"
        assert session["marketplace_price_cents"] == 3953, \
            "ceil(3360 * 10000 / 8500)"
        assert session["price_version"] == 1
        assert session["fullness_posture"] == "OPEN"
        assert session["promo_offer_state"] == "NONE"
        assert session["payroll_period_id"] == ctx["period"]["id"]
        assert session["status"] == "SCHEDULED"

    def test_session_capacity_defaults_to_the_template_when_omitted(self, api):
        """PRD §3.2: "The session begins in `SCHEDULED`, its `end_at` is derived from `start_at` plus the format's `duration_minutes`, and its `capacity` defaults to the format's `default_capacity` when the caller omits it."

        Design: Corner/entities/class_session_create_derives_end_price_and_posture_from_the_template
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2)
        # A second session with no explicit capacity and a different room.
        payload = {
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"],
            "room_code": "ROOM-Z",
            "start_at": "2026-06-21T17:00:00Z",
            "expected_subscription_version": ctx["subscription_version"],
        }
        session = validate_success(
            api.create_class_session(payload, ctx["owner"]), expected_status=201)
        assert session["capacity"] == ctx["template"]["default_capacity"], \
            "capacity falls back to the format's default_capacity"


class TestSessionUpdate:

    def test_capacity_update_leaves_derived_counters_under_server_control(self, api):
        """PRD §3.2: "A scheduled session may be updated while it is still `SCHEDULED`, supplying any of `capacity`, `instructor_staff_id`, `room_code` or the promotional fields together with `expected_class_session_version`."

        Design: Corner/entities/class_session_update_ignores_client_supplied_derived_fields
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2)
        session = ctx["session"]

        updated = validate_success(api.update_class_session(
            session["id"],
            {"capacity": 4, "expected_class_session_version": session["version"]},
            ctx["owner"]))

        assert updated["capacity"] == 4
        assert updated["seats_taken"] == 0, "seats_taken is never client-settable"
        assert updated["seats_held"] == 0
        assert updated["status"] == "SCHEDULED"
        assert updated["price_version"] == 1, "capacity alone does not reprice"


class TestSessionListing:

    def test_session_list_paginates_with_total_count_over_the_filtered_set(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the four pagination fields: `limit` and `offset` echo the request, `total_count` reports the total number of rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the returned page."

        Design: Corner/entities/sessions_list_paginates_and_total_count_counts_the_whole_filtered_set
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2)
        studio_id = ctx["studio"]["id"]
        create_session(studio_id, ctx["owner"], ctx["template"]["id"],
                       ctx["instructor"]["id"], ctx["subscription_version"],
                       room_code="ROOM-B", start_at="2026-06-21T17:00:00Z")
        create_session(studio_id, ctx["owner"], ctx["template"]["id"],
                       ctx["instructor"]["id"], ctx["subscription_version"],
                       room_code="ROOM-C", start_at="2026-06-22T17:00:00Z")

        first_page = api.list_class_sessions(
            make_staff_member_headers(ctx["instructor"]["id"]),
            params={"studio_id": studio_id, "limit": 2, "offset": 0})
        rows, meta = validate_paginated(first_page)
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2 and meta["offset"] == 0

        second = api.list_class_sessions(
            make_staff_member_headers(ctx["instructor"]["id"]),
            params={"studio_id": studio_id, "limit": 2, "offset": 2})
        rows2, meta2 = validate_paginated(second)
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_session_list_narrows_by_class_template_filter(self, api):
        """PRD §2.3: "Filter parameters that a given list endpoint declares (`status`, `channel`, `studio_id`, and the like) narrow `total_count` before pagination, never after."

        Design: Corner/entities/sessions_list_paginates_and_total_count_counts_the_whole_filtered_set
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2)
        studio_id = ctx["studio"]["id"]
        restore = create_template(studio_id, ctx["owner"], name="Candlelight Restore 60",
                                  duration_minutes=60, base_price_cents=5000,
                                  default_capacity=30, credit_cost=2,
                                  is_off_peak=False, buffer_minutes=30)
        create_session(studio_id, ctx["owner"], restore["id"],
                       ctx["instructor"]["id"], ctx["subscription_version"],
                       room_code="ROOM-B", start_at="2026-06-21T17:00:00Z")

        rows, meta = validate_paginated(api.list_class_sessions(
            make_staff_member_headers(ctx["instructor"]["id"]),
            params={"studio_id": studio_id,
                    "class_template_id": restore["id"]}))
        assert len(rows) == 1
        assert meta["total_count"] == 1

        all_rows, all_meta = validate_paginated(api.list_class_sessions(
            make_staff_member_headers(ctx["instructor"]["id"]),
            params={"studio_id": studio_id}))
        assert all_meta["total_count"] == 2
        assert all_meta["limit"] == 10 and all_meta["offset"] == 0, \
            "the documented defaults are limit 10 and offset 0"


class TestRoomOverlapSemantics:

    def test_room_overlap_uses_a_half_open_interval_so_adjacency_is_admitted(self, api):
        """PRD §3.2: "Two sessions in the same room_code may not collide: their
        half-open intervals from start_at up to but excluding end_at must not
        intersect, or the schedule is refused with ERR_ROOM_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/room_overlap_uses_a_half_open_interval_so_adjacency_is_admitted
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A")
        studio_id, owner = ctx["studio"]["id"], ctx["owner"]

        # A different room at the same instant: admitted.  Each schedule advances
        # the subscription's version, so the next write re-observes it (PRD §2.8).
        other_room = validate_success(api.create_class_session({
            "studio_id": studio_id, "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-B",
            "start_at": "2026-06-20T17:00:00Z", "capacity": 2,
            "expected_subscription_version": current_subscription_version(studio_id),
        }, owner), expected_status=201)
        assert other_room["id"]

        # The same room starting exactly when the first ends: the interval is
        # half-open, so adjacency is admitted.
        boundary = validate_success(api.create_class_session({
            "studio_id": studio_id, "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-20T17:50:00Z", "capacity": 2,
            "expected_subscription_version": current_subscription_version(studio_id),
        }, owner), expected_status=201)
        assert same_instant(boundary["start_at"], "2026-06-20T17:50:00Z")
        assert same_instant(boundary["end_at"], "2026-06-20T18:40:00Z")

    def test_room_collision_inside_the_interval_is_refused(self, api):
        """PRD §3.2: "Two sessions in the same room_code may not collide: their
        half-open intervals from start_at up to but excluding end_at must not
        intersect, or the schedule is refused with ERR_ROOM_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/room_overlap_uses_a_half_open_interval_so_adjacency_is_admitted
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A")

        validate_error(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-20T17:20:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"]), ApiErrorId.ERR_ROOM_OVERLAP)


class TestInstructorBuffer:

    def test_a_gap_equal_to_the_buffer_is_admitted(self, api):
        """PRD §3.2: "where two sessions in a room are close but not colliding, the gap between them must be at least as large as the greater of the two formats' `buffer_minutes` values, or the schedule is refused with `ERR_BUFFER_INSUFFICIENT`."

        Design: Difficulty/resource_temporal_overlap/instructor_buffer_uses_a_closed_gap_so_a_short_changeover_is_rejected
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z",
                                  room_code="ROOM-A", buffer_minutes=15)

        admitted = validate_success(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-C",
            "start_at": "2026-06-20T18:05:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"]), expected_status=201)
        assert same_instant(admitted["start_at"], "2026-06-20T18:05:00Z"), \
            "a gap exactly equal to the required changeover is admitted"


class TestPayrollPeriodCoverageBoundary:

    def test_session_at_the_period_end_date_resolves_to_that_period(self, api):
        """PRD §3.2: "The session's `payroll_period_id` is resolved by coverage: the studio must already have a `PayrollPeriod` whose inclusive range between `start_date` and `end_date` contains `start_at`."

        Design: Difficulty/boundary_precision_check/payroll_period_boundary_is_inclusive_so_gap_only_fires_past_the_endpoint
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=True,
                                  with_instructor=True, capacity=2,
                                  start_at="2026-06-30T23:59:59Z",
                                  room_code="ROOM-A")
        assert ctx["session"]["payroll_period_id"] == ctx["period"]["id"], \
            "the instant equal to end_date is inside the inclusive range"

    def test_session_past_the_period_end_raises_the_gap_error(self, api):
        """PRD §3.2: "If no period covers the instant the request is refused with `ERR_PAYROLL_PERIOD_GAP`."

        Design: Difficulty/boundary_precision_check/payroll_period_boundary_is_inclusive_so_gap_only_fires_past_the_endpoint
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-30T23:59:59Z",
                                  room_code="ROOM-A")

        validate_error(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-B",
            "start_at": "2026-07-01T00:00:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"]), ApiErrorId.ERR_PAYROLL_PERIOD_GAP)

        rows, meta = validate_paginated(api.list_class_sessions(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"]}))
        assert meta["total_count"] == 1, "the refused session was not persisted"