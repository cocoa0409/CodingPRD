"""Endoscope disinfection shelf life, scope interval discipline and surgery-center block capacity."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def _warmed_scope(api, plan_code, patient_mrn, scope_serial):
    """One adult chart and one scope carrying a full disinfection history.

    The scope is registered, used through a diagnostic endoscopy and disinfected
    again at the default clock, so it ends `READY` with a `cycle_count` of 1, a
    `last_reprocessed_at` of 2026-08-01T00:00:00Z and a shelf life running to
    2026-08-08T00:00:00Z.
    """
    world = SETUP.policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides={"payer_name": "Shelf Life Mutual"},
        patient_overrides={"full_name": "Scope Patient", "date_of_birth": "1972-01-30"},
    )
    scope = SETUP.register_scope(
        api, serial=scope_serial, model="ENF-V4 rhinolaryngoscope"
    )
    SETUP.soil_scope(api, scope["id"], world["patient"]["id"])
    scope = SETUP.reprocess_scope(api, scope["id"])
    return {"patient_id": world["patient"]["id"], "scope": scope}


def test_scope_start_accepted_one_minute_before_the_disinfection_expiry(api):
    """PRD 3.8: "A scope is shelf-valid when `last_reprocessed_at` is null, or when
    the logical clock is **strictly before** `hld_expires_at`; the boundary is
    exclusive, so a scope reprocessed at 2026-08-01T00:00:00Z expires at
    2026-08-08T00:00:00Z, is still usable at 2026-08-07T23:59:00Z, and is no longer
    usable at exactly 2026-08-08T00:00:00Z."

    Design: Difficulty/boundary_precision_check/hld_shelf_life_boundary_exclusive_at_booking_start
    """
    base = _warmed_scope(api, "HLD-2999A", C.mrn(10121), C.scope_serial(2))
    scope_id = base["scope"]["id"]

    # The freshly disinfected scope advertises a seven-day window off the default clock.
    check.assert_endoscope(
        base["scope"], status=C.SCOPE_READY, cycle_count=1, mec_test_due=False
    )
    check.assert_hld_window(base["scope"])
    check.assert_instant_equals(base["scope"]["last_reprocessed_at"], C.CLOCK_DEFAULT)
    check.assert_instant_equals(base["scope"]["hld_expires_at"], "2026-08-08T00:00:00Z")

    # A booking whose start sits one minute inside that window.
    booking = SETUP.create_booking(
        api,
        base["patient_id"],
        "2026-08-07T23:59:00Z",
        "2026-08-08T00:59:00Z",
        endoscope_asset_id=scope_id,
    )

    # The clock is parked one minute below the expiry and the physician of record starts.
    SETUP.set_clock(api, "2026-08-07T23:59:00Z")
    started = check.validate_unpaginated(
        api.start_procedure_booking(booking["id"], USERS.ENT_1)
    )
    check.assert_procedure_booking(
        started, status=C.BOOKING_IN_PROGRESS, endoscope_asset_id=scope_id
    )

    # The accepted start claimed the scope and left its shelf life exactly where it was.
    scope = SETUP.read_scope(api, scope_id)
    check.assert_endoscope(
        scope,
        status=C.SCOPE_IN_USE,
        cycle_count=1,
        last_used_by_user_id=C.USER_ENT_1,
    )
    check.assert_instant_equals(scope["hld_expires_at"], "2026-08-08T00:00:00Z")


def test_scope_start_refused_at_exactly_the_disinfection_expiry(api):
    """PRD 3.9: "Then, when the booking names an endoscope: the scope's
    high-level-disinfection shelf life must not have lapsed — that is,
    `last_reprocessed_at` is null, or the clock is strictly before `hld_expires_at` —
    or the start is refused with `ERR_HLD_EXPIRED`; and the scope must be in status
    `READY`, or the start is refused with `ERR_SCOPE_NOT_READY`."

    Design: Difficulty/boundary_precision_check/hld_shelf_life_boundary_exclusive_at_booking_start
    """
    base = _warmed_scope(api, "HLD-2999B", C.mrn(10122), C.scope_serial(3))
    scope_id = base["scope"]["id"]

    # This scope carries a byte-identical history to its sibling: expiry at 2026-08-08T00:00:00Z.
    check.assert_endoscope(base["scope"], status=C.SCOPE_READY, cycle_count=1)
    check.assert_instant_equals(base["scope"]["hld_expires_at"], "2026-08-08T00:00:00Z")

    # A booking whose start sits exactly on the expiry instant.
    booking = SETUP.create_booking(
        api,
        base["patient_id"],
        "2026-08-08T00:00:00Z",
        "2026-08-08T01:00:00Z",
        endoscope_asset_id=scope_id,
    )

    # The clock is moved onto the expiry instant itself and the same start is issued.
    SETUP.set_clock(api, "2026-08-08T00:00:00Z")
    validate_error(
        api.start_procedure_booking(booking["id"], USERS.ENT_1),
        ApiErrorId.HLD_EXPIRED.value,
    )

    # The rejected start consumed nothing: the booking still waits and the scope is untouched.
    check.assert_procedure_booking(
        SETUP.read_booking(api, booking["id"]),
        status=C.BOOKING_SCHEDULED,
        version=booking["version"],
    )
    scope = SETUP.read_scope(api, scope_id)
    check.assert_endoscope(scope, status=C.SCOPE_READY, cycle_count=1)
    check.assert_instant_equals(scope["hld_expires_at"], "2026-08-08T00:00:00Z")


def _two_bookings_on_one_scope(api, plan_code, patient_mrn, scope_serial):
    """One never-disinfected scope and two scheduled endoscopies an hour apart.

    The scope has no reprocessing history, so the shelf-life rule cannot fire, and
    the second booking begins sixty minutes after the first one ends, which clears
    both the inclusive-endpoint rule and the forty-five minute turnaround. The only
    obstacle left for the second booking is the scope's own status.
    """
    world = SETUP.policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides={"payer_name": "Crosslink Health"},
        patient_overrides={
            "full_name": "Endoscopy Patient",
            "date_of_birth": "1968-12-11",
        },
    )
    patient_id = world["patient"]["id"]
    scope = SETUP.register_scope(
        api, serial=scope_serial, model="ENF-V4 rhinolaryngoscope"
    )
    check.assert_endoscope(
        scope,
        status=C.SCOPE_READY,
        cycle_count=0,
        last_reprocessed_at=None,
        hld_expires_at=None,
    )
    first = SETUP.create_booking(
        api,
        patient_id,
        "2026-08-03T09:00:00Z",
        "2026-08-03T10:00:00Z",
        endoscope_asset_id=scope["id"],
    )
    second = SETUP.create_booking(
        api,
        patient_id,
        "2026-08-03T11:00:00Z",
        "2026-08-03T12:00:00Z",
        endoscope_asset_id=scope["id"],
    )
    return {"scope_id": scope["id"], "first": first, "second": second}


def test_second_booking_start_refused_from_every_still_serviceable_scope_posture(api):
    """PRD 3.9: "That second error deliberately covers only the still-serviceable
    postures `IN_USE`, `SOILED`, `REPROCESSING` and `QUARANTINED`, because each of
    those resolves with time and the operator should wait."

    Design: Difficulty/cross_entity_state_dependency/booking_start_gated_by_endoscope_readiness
    """
    base = _two_bookings_on_one_scope(api, "CROSS-2999A", C.mrn(10131), C.scope_serial(4))
    scope_id = base["scope_id"]
    second_id = base["second"]["id"]

    # The first endoscopy starts and claims the scope.
    started = check.validate_unpaginated(
        api.start_procedure_booking(base["first"]["id"], USERS.ENT_1)
    )
    check.assert_procedure_booking(started, status=C.BOOKING_IN_PROGRESS)
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id),
        status=C.SCOPE_IN_USE,
        last_used_by_user_id=C.USER_ENT_1,
    )

    # Scope IN_USE — the second booking's own start is refused.
    validate_error(
        api.start_procedure_booking(second_id, USERS.ENT_1),
        ApiErrorId.SCOPE_NOT_READY.value,
    )

    # Completing the first endoscopy soils the scope and voids its disinfection.
    SETUP.complete_booking(api, base["first"]["id"], devices_used_count=0)
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id), status=C.SCOPE_SOILED, hld_expires_at=None
    )

    # Scope SOILED — the identical start is refused a second time.
    validate_error(
        api.start_procedure_booking(second_id, USERS.ENT_1),
        ApiErrorId.SCOPE_NOT_READY.value,
    )

    # A disinfection run is opened, so the scope is mid-cycle.
    SETUP.start_reprocessing(api, scope_id)
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id),
        status=C.SCOPE_REPROCESSING,
        reprocessing_started_by_user_id=C.USER_TECH_1,
    )

    # Scope REPROCESSING — the identical start is refused a third time.
    validate_error(
        api.start_procedure_booking(second_id, USERS.ENT_1),
        ApiErrorId.SCOPE_NOT_READY.value,
    )

    # The booking row was never the obstacle: it still waits at the version it was created with.
    check.assert_procedure_booking(
        SETUP.read_booking(api, second_id),
        status=C.BOOKING_SCHEDULED,
        version=base["second"]["version"],
        endoscope_asset_id=scope_id,
    )


def test_second_booking_start_admitted_once_the_scope_returns_to_ready(api):
    """PRD 3.9: "On success the booking moves `SCHEDULED → IN_PROGRESS`, and the scope
    moves `READY → IN_USE` with `last_used_by_user_id` set to the booking's
    `physician_user_id` — note that it records the physician of record from the
    booking, not the acting identifier, though the identity check has just guaranteed
    the two are equal."

    Design: Difficulty/cross_entity_state_dependency/booking_start_gated_by_endoscope_readiness
    """
    base = _two_bookings_on_one_scope(api, "CROSS-2999B", C.mrn(10132), C.scope_serial(14))
    scope_id = base["scope_id"]
    second_id = base["second"]["id"]

    # The scope walks the whole loop: used by the first endoscopy, soiled, then disinfected.
    SETUP.start_booking(api, base["first"]["id"])
    SETUP.complete_booking(api, base["first"]["id"], devices_used_count=0)
    scope = SETUP.reprocess_scope(api, scope_id)
    check.assert_endoscope(
        scope,
        status=C.SCOPE_READY,
        cycle_count=1,
        mec_test_due=False,
        consecutive_mec_failures=0,
        reprocessing_started_by_user_id=None,
    )
    check.assert_instant_equals(scope["last_reprocessed_at"], C.CLOCK_DEFAULT)
    check.assert_instant_equals(scope["hld_expires_at"], "2026-08-08T00:00:00Z")

    # Scope READY — the identical start that was refused three times now succeeds.
    started = check.validate_unpaginated(
        api.start_procedure_booking(second_id, USERS.ENT_1)
    )
    check.assert_procedure_booking(
        started,
        status=C.BOOKING_IN_PROGRESS,
        physician_user_id=C.USER_ENT_1,
        endoscope_asset_id=scope_id,
    )

    # The scope moved with it, recording the booking's physician of record.
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id),
        status=C.SCOPE_IN_USE,
        cycle_count=1,
        last_used_by_user_id=C.USER_ENT_1,
    )


def _fresh_scope_world(api, plan_code, patient_mrn, scope_serial):
    """One adult chart and one scope with no bookings and no disinfection history.

    Nothing constrains the candidates that follow except the interval each one asks
    for, and every candidate sits on 2026-08-03 while the clock stays at its default.
    """
    world = SETUP.policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides={"payer_name": "Overlap Health"},
        patient_overrides={
            "full_name": "Interval Patient",
            "date_of_birth": "1966-07-03",
        },
    )
    scope = SETUP.register_scope(
        api, serial=scope_serial, model="ENF-V4 rhinolaryngoscope"
    )
    return {"patient_id": world["patient"]["id"], "scope_id": scope["id"]}


def test_touching_scope_intervals_conflict_on_their_shared_endpoint(api):
    """PRD 3.9: "Then the temporal rung: the requested interval may not overlap any
    existing `SCHEDULED` or `IN_PROGRESS` booking on the same endoscope, treating both
    endpoints as inclusive so two bookings that merely touch already conflict, or the
    booking is refused with `ERR_SCOPE_INTERVAL_CONFLICT`; the requested `start_at`
    must be at least 45 minutes after the `end_at` of the scope's preceding booking
    and the requested `end_at` must be at least 45 minutes before the `start_at` of
    the scope's following booking, or the booking is refused with
    `ERR_REPROCESSING_BUFFER_VIOLATION`; a booking naming a block must lie entirely
    inside that block's half-open window, so it may begin at exactly `block_start_at`
    but must end at or before `block_end_at`, or it is refused with
    `ERR_BLOCK_WINDOW_EXCEEDED`; and a `BALLOON_SINUPLASTY` booking whose case is
    `AUTHORIZED` but whose `auth_expires_at` the logical clock has reached is refused
    with `ERR_AUTHORIZATION_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/endoscope_closed_interval_and_turnaround_buffer
    """
    base = _fresh_scope_world(api, "OVL-2999A", C.mrn(10151), C.scope_serial(5))
    scope_id = base["scope_id"]

    # The incumbent takes the scope from nine to ten.
    incumbent = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T09:00:00Z",
                "2026-08-03T10:00:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        incumbent,
        status=C.BOOKING_SCHEDULED,
        duration_minutes=60,
        endoscope_asset_id=scope_id,
    )

    # A candidate that merely starts where the incumbent ends already overlaps it.
    validate_error(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T10:00:00Z",
                "2026-08-03T11:00:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.SCOPE_INTERVAL_CONFLICT.value,
    )

    # The refused candidate left no row behind, and the scope's own lifecycle never moved.
    rows, meta = validate_paginated(
        api.list_procedure_bookings(USERS.ADMIN_1, params={"endoscope_asset_id": scope_id})
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    check.assert_procedure_booking(
        check.find_by_id(rows, incumbent["id"]), status=C.BOOKING_SCHEDULED
    )
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id), status=C.SCOPE_READY, cycle_count=0
    )


def test_scope_turnaround_buffer_admits_a_candidate_exactly_forty_five_minutes_later(api):
    """PRD 3.8: "And consecutive scope bookings must leave a reprocessing turnaround: a
    candidate booking may start only at or after 45 minutes past the end of the scope's
    immediately prior booking, inclusive at the boundary, so if a prior booking ends at
    10:00 a next start at 10:30 is refused with `ERR_REPROCESSING_BUFFER_VIOLATION`
    while a next start at exactly 10:45 is accepted."

    Design: Difficulty/resource_temporal_overlap/endoscope_closed_interval_and_turnaround_buffer
    """
    base = _fresh_scope_world(api, "OVL-2999B", C.mrn(10152), C.scope_serial(15))
    scope_id = base["scope_id"]

    # The incumbent again ends at ten, so the turnaround runs from ten to a quarter to eleven.
    SETUP.create_booking(
        api,
        base["patient_id"],
        "2026-08-03T09:00:00Z",
        "2026-08-03T10:00:00Z",
        endoscope_asset_id=scope_id,
    )

    # Thirty minutes after that end clears the interval but not the turnaround.
    validate_error(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T10:30:00Z",
                "2026-08-03T11:30:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.REPROCESSING_BUFFER_VIOLATION.value,
    )

    # Exactly forty-five minutes after that end is admissible: the boundary is inclusive.
    accepted = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T10:45:00Z",
                "2026-08-03T11:45:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        accepted, status=C.BOOKING_SCHEDULED, duration_minutes=60
    )
    check.assert_instant_equals(accepted["start_at"], "2026-08-03T10:45:00Z")

    # Two bookings stand on the scope; the thirty-minute candidate is not one of them.
    rows, meta = validate_paginated(
        api.list_procedure_bookings(USERS.ADMIN_1, params={"endoscope_asset_id": scope_id})
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=2, has_more=False
    )


def test_scope_turnaround_buffer_is_measured_backwards_from_the_following_booking(api):
    """PRD 3.9: "Then the temporal rung: the requested interval may not overlap any
    existing `SCHEDULED` or `IN_PROGRESS` booking on the same endoscope, treating both
    endpoints as inclusive so two bookings that merely touch already conflict, or the
    booking is refused with `ERR_SCOPE_INTERVAL_CONFLICT`; the requested `start_at`
    must be at least 45 minutes after the `end_at` of the scope's preceding booking
    and the requested `end_at` must be at least 45 minutes before the `start_at` of
    the scope's following booking, or the booking is refused with
    `ERR_REPROCESSING_BUFFER_VIOLATION`; a booking naming a block must lie entirely
    inside that block's half-open window, so it may begin at exactly `block_start_at`
    but must end at or before `block_end_at`, or it is refused with
    `ERR_BLOCK_WINDOW_EXCEEDED`; and a `BALLOON_SINUPLASTY` booking whose case is
    `AUTHORIZED` but whose `auth_expires_at` the logical clock has reached is refused
    with `ERR_AUTHORIZATION_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/endoscope_closed_interval_and_turnaround_buffer
    """
    base = _fresh_scope_world(api, "OVL-2999C", C.mrn(10153), C.scope_serial(25))
    scope_id = base["scope_id"]

    # The incumbent starts at nine, so anything ending after a quarter past eight crowds it.
    SETUP.create_booking(
        api,
        base["patient_id"],
        "2026-08-03T09:00:00Z",
        "2026-08-03T10:00:00Z",
        endoscope_asset_id=scope_id,
    )

    # An earlier candidate ending thirty minutes before that start is refused.
    validate_error(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T08:00:00Z",
                "2026-08-03T08:30:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.REPROCESSING_BUFFER_VIOLATION.value,
    )

    # Ending sixty minutes before that start leaves the turnaround intact.
    accepted = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                base["patient_id"],
                "2026-08-03T07:00:00Z",
                "2026-08-03T08:00:00Z",
                endoscope_asset_id=scope_id,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        accepted, status=C.BOOKING_SCHEDULED, duration_minutes=60
    )
    check.assert_instant_equals(accepted["end_at"], "2026-08-03T08:00:00Z")

    # Two bookings stand on the scope and its own lifecycle never moved.
    rows, meta = validate_paginated(
        api.list_procedure_bookings(USERS.ADMIN_1, params={"endoscope_asset_id": scope_id})
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=2, has_more=False
    )
    check.assert_endoscope(
        SETUP.read_scope(api, scope_id), status=C.SCOPE_READY, cycle_count=0
    )


def _block_world(api, plan_code, first_mrn_number, patient_count):
    """A four-hour two-room block and enough charts to fill it.

    Every chart is born on 2020-01-01, so each is 79 months old at the default clock
    and well clear of the thirty-six month line that forces a pediatric venue. The
    block runs 08:00 to 12:00 with two rooms, giving 480 capacity minutes.
    """
    policy = SETUP.create_policy(api, plan_code=plan_code, payer_name="Block Health")
    patients = [
        SETUP.create_patient(
            api,
            policy["id"],
            patient_mrn=C.mrn(first_mrn_number + index),
            full_name="Block Child",
            date_of_birth="2020-01-01",
        )
        for index in range(patient_count)
    ]
    block = SETUP.publish_block(
        api,
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        max_concurrent_cases=2,
        center_name="Northside Surgery Center",
    )
    return {"patients": patients, "block": block}


def _tube_case_payload(patient_id, start_at, end_at, block_id):
    """A tympanostomy body venued at the surgery center inside one block."""
    return SETUP.booking_payload(
        patient_id,
        start_at,
        end_at,
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block_id,
    )


def test_block_refuses_a_third_case_live_at_the_same_instant(api):
    """PRD 3.9: "The booking may not push the block's `booked_minutes` past its
    `capacity_minutes`, nor cause more than `max_concurrent_cases` bookings to be live
    at any instant inside its half-open interval, or it is refused with
    `ERR_BLOCK_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/surgery_block_half_open_window_and_aggregate_concurrency
    """
    base = _block_world(api, "BLK-2999A", 10161, 3)
    block_id = base["block"]["id"]

    # The block opens empty with two rooms over four hours.
    check.assert_patient(base["patients"][0], age_months=79)
    check.assert_surgery_center_block(
        base["block"],
        max_concurrent_cases=2,
        capacity_minutes=480,
        booked_minutes=0,
        booked_case_count=0,
        utilization_bps=0,
        status=C.BLOCK_OPEN,
    )

    # Two cases overlap between nine and ten, which is exactly both rooms.
    SETUP.create_booking(
        api,
        base["patients"][0]["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T10:00:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block_id,
    )
    second = validate_success(
        api.create_procedure_booking(
            _tube_case_payload(
                base["patients"][1]["id"],
                "2026-08-10T09:00:00Z",
                "2026-08-10T11:00:00Z",
                block_id,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        second, status=C.BOOKING_SCHEDULED, duration_minutes=120
    )
    check.assert_surgery_center_block(
        SETUP.read_block(api, block_id),
        booked_minutes=240,
        booked_case_count=2,
        utilization_bps=5000,
        status=C.BLOCK_OPEN,
    )

    # A third case live between half past nine and ten is refused, though the minutes fit.
    validate_error(
        api.create_procedure_booking(
            _tube_case_payload(
                base["patients"][2]["id"],
                "2026-08-10T09:30:00Z",
                "2026-08-10T10:30:00Z",
                block_id,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.BLOCK_CAPACITY_EXCEEDED.value,
    )

    # The refused case consumed no capacity.
    check.assert_surgery_center_block(
        SETUP.read_block(api, block_id),
        booked_minutes=240,
        booked_case_count=2,
        utilization_bps=5000,
        status=C.BLOCK_OPEN,
    )


def test_block_window_admits_a_case_ending_at_the_closing_instant_but_nothing_past_it(api):
    """PRD 3.9: "Then the temporal rung: the requested interval may not overlap any
    existing `SCHEDULED` or `IN_PROGRESS` booking on the same endoscope, treating both
    endpoints as inclusive so two bookings that merely touch already conflict, or the
    booking is refused with `ERR_SCOPE_INTERVAL_CONFLICT`; the requested `start_at`
    must be at least 45 minutes after the `end_at` of the scope's preceding booking
    and the requested `end_at` must be at least 45 minutes before the `start_at` of
    the scope's following booking, or the booking is refused with
    `ERR_REPROCESSING_BUFFER_VIOLATION`; a booking naming a block must lie entirely
    inside that block's half-open window, so it may begin at exactly `block_start_at`
    but must end at or before `block_end_at`, or it is refused with
    `ERR_BLOCK_WINDOW_EXCEEDED`; and a `BALLOON_SINUPLASTY` booking whose case is
    `AUTHORIZED` but whose `auth_expires_at` the logical clock has reached is refused
    with `ERR_AUTHORIZATION_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/surgery_block_half_open_window_and_aggregate_concurrency
    """
    base = _block_world(api, "BLK-2999B", 10171, 3)
    block_id = base["block"]["id"]

    # Two cases already stand in the block, one ending at ten and one running to eleven.
    SETUP.create_booking(
        api,
        base["patients"][0]["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T10:00:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block_id,
    )
    SETUP.create_booking(
        api,
        base["patients"][1]["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T11:00:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block_id,
    )

    # A case running past the closing instant is a containment failure, not a capacity one.
    validate_error(
        api.create_procedure_booking(
            _tube_case_payload(
                base["patients"][2]["id"],
                "2026-08-10T11:00:00Z",
                "2026-08-10T13:00:00Z",
                block_id,
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.BLOCK_WINDOW_EXCEEDED.value,
    )

    # Starting where the first case ended is an adjacency here, and ending at noon is inside.
    accepted = validate_success(
        api.create_procedure_booking(
            _tube_case_payload(
                base["patients"][2]["id"],
                "2026-08-10T10:00:00Z",
                "2026-08-10T12:00:00Z",
                block_id,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        accepted,
        status=C.BOOKING_SCHEDULED,
        duration_minutes=120,
        surgery_center_block_id=block_id,
    )
    check.assert_instant_equals(accepted["end_at"], base["block"]["block_end_at"])

    # Three cases hold 360 of the 480 capacity minutes, so the block is busy but still open.
    check.assert_surgery_center_block(
        SETUP.read_block(api, block_id),
        booked_minutes=360,
        booked_case_count=3,
        capacity_minutes=480,
        utilization_bps=7500,
        status=C.BLOCK_OPEN,
    )
    rows, meta = validate_paginated(
        api.list_procedure_bookings(
            USERS.ADMIN_1, params={"surgery_center_block_id": block_id}
        )
    )
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=3, has_more=False
    )
    check.assert_procedure_booking(
        check.find_by_id(rows, accepted["id"]), status=C.BOOKING_SCHEDULED
    )
