"""Class library: licensing windows, on-demand library clamping, waitlists,
scheduling collisions and leaderboard integrity."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_household_user,
    api_client,
    create_class_session_payload,
    create_membership,
    enroll,
    get_membership,
    get_session,
    mint_device,
    owner_headers,
    set_clock,
    setup_one_hour_session,
    setup_published_session,
    validate_paginated,
    validate_success,
)

TECH = TEST_USERS["service_technician_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# =========================================================================
# Queue A — Difficulty instances
# =========================================================================

def test_the_on_demand_library_window_is_ends_at_plus_twenty_four_hours():
    """PRD §3.8: "For an `ON_DEMAND` session the publish step fixes
    `on_demand_window_ends_at` as whichever is earlier of the session end plus 24
    hours and the license end — the library window is clamped to the licence so it
    can never outlive the instructor's rights."

    Design: Difficulty/resource_temporal_overlap/instructor_licensing_window_clamps_the_on_demand_library
    """
    set_clock("2026-09-01T00:00:00Z")
    session = setup_published_session(
        delivery_mode="ON_DEMAND",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T11:00:00Z",
        license_starts_at="2026-09-10T00:00:00Z",
        license_ends_at="2026-09-20T00:00:00Z",
        title="Threshold Ride")
    assert session["on_demand_window_ends_at"] == "2026-09-11T11:00:00Z"


def test_the_on_demand_library_window_is_clamped_to_the_licence_end():
    """PRD §3.8: "For an `ON_DEMAND` session the publish step fixes
    `on_demand_window_ends_at` as whichever is earlier of the session end plus 24
    hours and the license end — the library window is clamped to the licence so it
    can never outlive the instructor's rights."
    PRD §2.9: "An on-demand class library window remains open for 24 hours after the
    session's scheduled end, but it may never outlive the instructor's licensing
    window: the later of the two instants is discarded and the license window end
    prevails."

    Design: Difficulty/resource_temporal_overlap/instructor_licensing_window_clamps_the_on_demand_library
    """
    set_clock("2026-09-01T00:00:00Z")
    clamped = setup_published_session(
        delivery_mode="ON_DEMAND",
        starts_at="2026-09-19T22:00:00Z",
        ends_at="2026-09-19T23:00:00Z",
        license_starts_at="2026-09-10T00:00:00Z",
        license_ends_at="2026-09-20T00:00:00Z",
        title="Late Window Ride")

    # unclamped would be 2026-09-20T23:00:00Z, the licence end prevails instead
    assert clamped["on_demand_window_ends_at"] == "2026-09-20T00:00:00Z"
    assert clamped["on_demand_window_ends_at"] != "2026-09-20T23:00:00Z"


def test_publishing_a_live_session_that_escapes_the_licence_is_refused():
    """PRD §3.8: "For a `LIVE` session the entire live window must sit inside the
    licensing window: the session start must be at or after the license start and the
    session end at or before the license end, and any violation is refused with
    `ERR_LICENSE_WINDOW_INVALID` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/instructor_licensing_window_clamps_the_on_demand_library
    """
    set_clock("2026-09-01T00:00:00Z")
    session = validate_success(api_client.create_class_session(
        create_class_session_payload(
            title="Out Of License Ride",
            delivery_mode="LIVE",
            starts_at="2026-09-21T09:00:00Z",
            ends_at="2026-09-21T11:00:00Z",
            license_starts_at="2026-09-10T00:00:00Z",
            license_ends_at="2026-09-20T00:00:00Z",
        ), INSTRUCTOR), 201)

    res = api_client.publish_class_session(session["id"], {}, INSTRUCTOR)
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_LICENSE_WINDOW_INVALID"

    assert get_session(session["id"])["scheduled_status"] == "DRAFT"


def test_a_publish_that_only_clamps_reports_no_error_at_all():
    """PRD §3.8: "For an `ON_DEMAND` session the publish step fixes
    `on_demand_window_ends_at` as whichever is earlier of the session end plus 24
    hours and the license end — the library window is clamped to the licence so it
    can never outlive the instructor's rights."

    Design: Difficulty/resource_temporal_overlap/instructor_licensing_window_clamps_the_on_demand_library
    """
    set_clock("2026-09-01T00:00:00Z")
    session = validate_success(api_client.create_class_session(
        create_class_session_payload(
            title="Abutting Library Ride",
            delivery_mode="ON_DEMAND",
            starts_at="2026-09-19T22:00:00Z",
            ends_at="2026-09-19T23:00:00Z",
            license_starts_at="2026-09-10T00:00:00Z",
            license_ends_at="2026-09-20T00:00:00Z",
        ), INSTRUCTOR), 201)

    published = validate_success(
        api_client.publish_class_session(session["id"], {}, INSTRUCTOR), 200)
    assert published["scheduled_status"] == "PUBLISHED"
    assert published["on_demand_window_ends_at"] == "2026-09-20T00:00:00Z"




def test_a_licensing_window_that_starts_after_the_session_is_refused():
    """PRD §3.8: "Two validations apply at authoring time. The licensing window must
    be internally sane — its start must precede the session start, and its end must
    follow its own start — and a window that is not sane is refused with
    `ERR_LICENSE_WINDOW_INVALID` (HTTP 409)."

    Design: Corner/entities/class_session_create_rejects_a_license_window_that_starts_after_the_session
    """
    set_clock("2026-09-01T00:00:00Z")

    bad_order = api_client.create_class_session(create_class_session_payload(
        title="Bad Window Ride",
        delivery_mode="LIVE",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T11:00:00Z",
        license_starts_at="2026-09-10T10:00:00Z",
        license_ends_at="2026-09-11T00:00:00Z",
    ), INSTRUCTOR)
    assert bad_order.status_code == 409, bad_order.text
    assert bad_order.json()["data"]["error_id"] == "ERR_LICENSE_WINDOW_INVALID"

    bad_enum = api_client.create_class_session(create_class_session_payload(
        title="Bad Discipline Ride",
        discipline="PILATES",
        delivery_mode="LIVE",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T11:00:00Z",
        license_starts_at="2026-09-10T00:00:00Z",
        license_ends_at="2026-09-11T00:00:00Z",
    ), INSTRUCTOR)
    assert bad_enum.status_code == 400, bad_enum.text
    assert bad_enum.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    rows, meta = validate_paginated(api_client.list_class_sessions(INSTRUCTOR))
    assert meta["total_count"] == 0


def test_an_enrollment_with_a_foreign_device_is_refused():
    """PRD §3.9: "The device must belong to the enroller's own membership, and a
    device belonging to a different household is refused with
    `ERR_DEVICE_NOT_ON_MEMBERSHIP` (HTTP 409)."

    Design: Corner/entities/class_enrollment_create_checks_body_foreign_keys_before_session_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_membership
    membership_a = create_membership(household_name="Quillon Household")
    m_a = membership_a["id"]
    add_household_user(m_a, display_name="Ada Quillon", email="ada@x.com", role="OWNER")

    membership_b = create_membership(household_name="Rhone Household",
                                     billing_email="r@x.com")
    m_b = membership_b["id"]
    device_b = mint_device(m_b, hardware_sku="BIKE", serial="BIKE-0002")

    session = setup_published_session()

    res = api_client.create_class_enrollment({
        "class_session_id": session["id"],
        "device_id": device_b["id"],
        "enroller_user_id": _owner_id(m_a),
    }, owner_headers(m_a))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_DEVICE_NOT_ON_MEMBERSHIP"

    rows, meta = validate_paginated(api_client.list_session_enrollments(session["id"], INSTRUCTOR))
    assert meta["total_count"] == 0
    assert get_session(session["id"])["live_enrollment_count"] == 0


def test_dropping_an_enrollment_restores_the_session_count():
    """PRD §3.9: "An enrollment may also be dropped by its household while still
    `ENROLLED` or `WAITLISTED`, which moves it to `DROPPED` and recomputes the count;
    and it expires automatically when its session archives or cancels, which moves it
    to `EXPIRED` and recomputes the count."

    Design: Difficulty/compensating_invariant/class_enrollment_drop_returns_the_session_count_to_its_start
    """
    base = setup_one_hour_session()
    session_id = base["session_id"]
    assert get_session(session_id)["live_enrollment_count"] == 0

    enrollment = enroll(base)
    assert enrollment["status"] == "ENROLLED"
    assert get_session(session_id)["live_enrollment_count"] == 1

    dropped = validate_success(
        api_client.drop_enrollment(enrollment["id"], {}, owner_headers(base["membership_id"])), 200)
    assert dropped["status"] == "DROPPED"
    assert get_session(session_id)["live_enrollment_count"] == 0

    validate_success(api_client.run_ops({}, ADMIN), 200)
    assert get_session(session_id)["live_enrollment_count"] == 0

    dropped_rows, dropped_meta = validate_paginated(
        api_client.list_session_enrollments(session_id, INSTRUCTOR, params={"status": "DROPPED"}))
    assert dropped_meta["total_count"] == 1
    enrolled_rows, enrolled_meta = validate_paginated(
        api_client.list_session_enrollments(session_id, INSTRUCTOR, params={"status": "ENROLLED"}))
    assert enrolled_meta["total_count"] == 0
    assert len(dropped_rows) == 1


def test_an_enrollment_outside_the_library_window_is_refused():
    """PRD §3.9: "And an enrollment that cannot be admitted is refused with
    `ERR_CLASS_CAPACITY_EXCEEDED` (HTTP 409) — this covers an on-demand enrollment
    attempted outside its library window as well as a session that is not in a
    publishable state."

    Design: Corner/validations/on_demand_enrollment_outside_the_library_window_is_rejected
    """
    base = setup_one_hour_session(starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T11:00:00Z")
    session_id = base["session_id"]
    assert get_session(session_id)["on_demand_window_ends_at"] == "2026-09-11T11:00:00Z"

    set_clock("2026-09-21T00:00:00Z")
    validate_success(api_client.run_ops({}, ADMIN), 200)
    assert get_session(session_id)["scheduled_status"] == "ARCHIVED"

    res = api_client.create_class_enrollment({
        "class_session_id": session_id,
        "device_id": base["device_id"],
        "enroller_user_id": base["owner"]["id"],
    }, owner_headers(base["membership_id"]))

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_CLASS_CAPACITY_EXCEEDED"
    assert get_session(session_id)["live_enrollment_count"] == 0
    assert get_session(session_id)["capacity"] == 100


def test_a_one_hour_cycling_session_pins_the_caps_at_their_exact_values():
    """PRD §3.9: "Each discipline carries a points-per-percentage weight: 10 for
    `CYCLING`, 7 for `RUNNING`, and 5 for both `STRENGTH` and `YOGA`. The session's
    scheduled length in seconds, divided by 600, scales the session capacity into a
    duration ceiling, floored to a whole number of points. The discipline ceiling is
    the lesser of the session capacity multiplied by a points multiplier of 2 and
    that duration ceiling."
    PRD §3.9: "An unflagged completion earns the lesser of its reported points and
    the discipline ceiling, written to `integrity_points`."

    Design: Corner/calculations/class_session_hour_long_session_scores_exactly_the_upper_benchmark
    """
    base = setup_one_hour_session(discipline="CYCLING",
                                  starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T10:00:00Z", capacity=100)
    m_id = base["membership_id"]

    first = enroll(base)
    second_user = add_household_user(m_id, display_name="Bea Quillon", email="bea@x.com",
                                     role="MEMBER")
    second = enroll(base, user_id=second_user["id"])
    third = enroll(base)

    low = validate_success(api_client.complete_enrollment(first["id"], {
        "output_points": 150, "completion_pct": 100,
        "benchmark_variant": "INDULGENT_BENCHMARK",
    }, owner_headers(m_id)), 200)
    assert low["status"] == "COMPLETED"
    assert low["completion_grade"] == "FULL_CREDIT"
    assert low["integrity_points"] == 150
    assert low["integrity_flagged"] is False

    capped = validate_success(api_client.complete_enrollment(second["id"], {
        "output_points": 250, "completion_pct": 100,
        "benchmark_variant": "INDULGENT_BENCHMARK",
    }, owner_headers(m_id)), 200)
    assert capped["integrity_points"] == 200
    assert capped["integrity_flagged"] is False


def test_a_completion_beyond_both_benchmarks_scores_nothing():
    """PRD §3.9: "A completion is flagged for review when its reported
    `output_points` exceed the benchmark for the session: the enrollment's
    `integrity_flagged` boolean is set true, and its `integrity_points` are forced to
    zero."

    Design: Corner/calculations/class_session_hour_long_session_scores_exactly_the_upper_benchmark
    """
    base = setup_one_hour_session(discipline="CYCLING",
                                  starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T10:00:00Z", capacity=100)
    m_id = base["membership_id"]
    enrollment = enroll(base)

    # the indulgent bar is the one-hour scheduled length (3600 s) plus the 600 s
    # tolerance, so 4201 exceeds both the strict and the indulgent benchmark
    flagged = validate_success(api_client.complete_enrollment(enrollment["id"], {
        "output_points": 4201, "completion_pct": 100,
        "benchmark_variant": "INDULGENT_BENCHMARK",
    }, owner_headers(m_id)), 200)

    assert flagged["integrity_flagged"] is True
    assert flagged["integrity_points"] == 0


def test_completed_workouts_ripple_into_the_device_and_membership_counters():
    """PRD §3.9: "A completed workout also ripples upward. The device's
    `total_workouts` is incremented by one, and the parent membership's derived
    `total_streams_observed` and posture are recomputed."
    PRD §3.9: "`COMPLETED`, `DROPPED` and `EXPIRED` are all terminal, and none of
    them counts toward the open-session figure, so an archived session always
    reconciles its count to zero."

    Design: Corner/cross_cutting_layers/restarting_a_stream_recomputes_the_derived_membership_counters
    """
    base = setup_one_hour_session(discipline="CYCLING",
                                  starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T10:00:00Z", capacity=100)
    m_id = base["membership_id"]
    d_id = base["device_id"]
    session_id = base["session_id"]

    for points in (150, 250, 601):
        user = add_household_user(m_id, display_name=f"Streamer {points}",
                                  email=f"streamer{points}@x.com", role="MEMBER")
        enrollment = enroll(base, user_id=user["id"])
        validate_success(api_client.complete_enrollment(enrollment["id"], {
            "output_points": points, "completion_pct": 100,
            "benchmark_variant": "INDULGENT_BENCHMARK",
        }, owner_headers(m_id)), 200)

    device = validate_success(api_client.get_device(d_id, TECH), 200)
    assert device["total_workouts"] == 3
    assert get_membership(m_id)["total_streams_observed"] == 3
    assert get_session(session_id)["live_enrollment_count"] == 0



def _owner_id(membership_id):
    rows, _ = validate_paginated(
        api_client.list_membership_household_users(
            membership_id, owner_headers(membership_id), params={"status": "ACTIVE"}))
    return rows[0]["id"]


def test_a_dropped_enrollment_leaves_the_session_count_reconciled():
    """PRD §3.9: "`COMPLETED`, `DROPPED` and `EXPIRED` are all terminal, and none of
    them counts toward the open-session figure, so an archived session always
    reconciles its count to zero."

    Design: Difficulty/compensating_invariant/class_enrollment_drop_returns_the_session_count_to_its_start
    """
    base = setup_one_hour_session(discipline="CYCLING",
                                  starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T11:00:00Z", capacity=100)
    session_id = base["session_id"]
    m_id = base["membership_id"]

    enrollment = enroll(base)
    validate_success(api_client.drop_enrollment(
        enrollment["id"], {}, owner_headers(m_id)), 200)

    assert get_session(session_id)["live_enrollment_count"] == 0
    dropped_rows, dropped_meta = validate_paginated(
        api_client.list_session_enrollments(session_id, INSTRUCTOR,
                                            params={"status": "DROPPED"}))
    assert dropped_meta["total_count"] == 1
    enrolled_rows, enrolled_meta = validate_paginated(
        api_client.list_session_enrollments(session_id, INSTRUCTOR,
                                            params={"status": "ENROLLED"}))
    assert enrolled_meta["total_count"] == 0
    assert len(dropped_rows) == 1


def test_the_household_paginated_list_defaults_and_filters_ten_rows_per_page():
    """PRD §2.3: "The `limit` parameter caps the number of items returned and defaults
    to 10 when omitted; its minimum accepted value is 1 and its maximum is 100."
    PRD §2.3: "`total_count` reports the number of resources matching the query across
    all pages, not merely the number on the current page, and `has_more` is a boolean
    that is true while further pages remain."

    Design: Corner/entities/memberships_list_paginates_and_filters_without_losing_total_count
    """
    set_clock("2026-09-01T00:00:00Z")
    for name, tier, fee in (("Quillon Household", "PLUS", 6000),
                            ("Rhone Household", "PLUS", 6000),
                            ("Sable Household", "BUSINESS", 12000)):
        create_membership(household_name=name, billing_email=f"{name[0].lower()}@x.com",
                          plan_tier=tier, monthly_fee_cents=fee)

    rows, meta = validate_paginated(
        api_client.list_memberships(TEST_USERS["membership_owner_headers"],
                                    params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_memberships(TEST_USERS["membership_owner_headers"],
                                    params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_memberships(TEST_USERS["membership_owner_headers"],
                                    params={"plan_tier": "BUSINESS"}))
    assert len(rows) == 1
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_memberships(TEST_USERS["membership_owner_headers"]))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_omitting_the_display_name_on_a_household_user_is_a_shape_failure():
    """PRD §2.4: "People are attached to a membership as household users. Each
    carries a `display_name` shown on the leaderboard, a unique `email`, and a `role`
    drawn from `OWNER` and `MEMBER`, defaulting to `MEMBER`."
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

    Design: Corner/entities/household_user_create_missing_display_name_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    membership = create_membership()
    m_id = membership["id"]

    res = api_client.create_household_user(m_id, {
        "email": "x@x.com",
        "role": "MEMBER",
    }, owner_headers(m_id))

    assert res.status_code == 400, res.text
    assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    rows, meta = validate_paginated(
        api_client.list_membership_household_users(m_id, owner_headers(m_id)))
    assert meta["total_count"] == 0
    assert get_membership(m_id)["active_user_count"] == 0




def test_the_platform_admin_can_complete_a_workout_on_the_shared_surface():
    """PRD §4: "POST | `/fitness/class-enrollments/{enrollmentId}/complete` | Complete
    a workout, applying the integrity cap | MembershipOwner, PlatformAdmin".
    PRD §2.1: "for `PlatformAdmin`, whose identifier names an operations
    administrator covering parts inventory, underwriting, refurbishment resale and the
    logical clock" — the opaque admin identifier is not ownership-compared, and the
    endpoint table admits the role.

    Design: Corner/rbac/platform_admin_can_act_across_all_peer_surfaces_but_is_still_denied_on_student_work
    """
    base = setup_one_hour_session(discipline="CYCLING",
                                  starts_at="2026-09-10T09:00:00Z",
                                  ends_at="2026-09-10T10:00:00Z", capacity=100)
    enrollment = enroll(base)

    completed = validate_success(api_client.complete_enrollment(enrollment["id"], {
        "output_points": 120,
        "completion_pct": 100,
        "benchmark_variant": "INDULGENT_BENCHMARK",
    }, ADMIN), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["integrity_points"] == 120


