"""Service booking policy: posture gating, per-type duration ceilings,
the daily quota boundary, FAMILY_ROOM cleaning-buffer semantics, and the
overlap-beats-quota pipeline ordering."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_service_booking,
    book_service,
    create_center_with_active_agreement,
    create_guest,
    get_center,
    set_clock,
    setup_open_center,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def test_posture_blocked_sleeping_area(api: ApiClient):
    """PRD §3.5: "A `RESTRICTED` center runs reduced services: only `SHOWER` and `CONNECTIVITY` may be booked, and a `SLEEPING_AREA` or `FAMILY_ROOM` request is rejected with `ERR_POSTURE_SERVICE_BLOCKED`."

    Design: Corner/validations/posture_blocked_sleeping_area
    """
    set_clock()
    # ACTIVE agreement but no confirmed staffing: coverage 0 -> RESTRICTED.
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Nun Center",
            "airport_code": "CHS",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 2,
        }
    )
    assert get_center(center["id"])["posture"] == "RESTRICTED"
    guest = create_guest(full_name="G Sleep")

    denied = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "SLEEPING_AREA",
            "start_at": "2026-09-01T20:00:00Z",
            "end_at": "2026-09-01T23:00:00Z",
        },
        MGR,
    )
    validate_error(denied, ApiErrorId.ERR_POSTURE_SERVICE_BLOCKED)

    ok = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "SHOWER",
            "start_at": "2026-09-01T18:00:00Z",
            "end_at": "2026-09-01T18:30:00Z",
        },
        MGR,
    )
    booking = validate_success(ok, 201)
    assert_service_booking(booking)
    assert booking["status"] == "BOOKED", (
        "SHOWER remains bookable under RESTRICTED at the same instant"
    )


def test_booking_duration_type_max(api: ApiClient):
    """PRD §3.5: "Duration is checked against the service ceiling: 480 minutes for `SLEEPING_AREA`, 30 minutes for `SHOWER`, 120 minutes for `CONNECTIVITY`, and 240 minutes for `FAMILY_ROOM`; a longer request is rejected with `ERR_BOOKING_DURATION_INVALID`."

    Design: Corner/calculations/booking_duration_type_max
    """
    set_clock()
    # RESTRICTED is fine here: SHOWER is one of the reduced services.
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Heth Center",
            "airport_code": "SBA",
            "occupancy_cap": 25,
            "required_daily_confirmed_assignments": 1,
        }
    )
    guest = create_guest(full_name="G Dur")

    ok = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "SHOWER",
            "start_at": "2026-09-01T10:00:00Z",
            "end_at": "2026-09-01T10:30:00Z",
        },
        MGR,
    )
    booking = validate_success(ok, 201)
    assert booking["status"] == "BOOKED", (
        "a 30-minute SHOWER is exactly at the type ceiling and must pass"
    )

    denied = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "SHOWER",
            "start_at": "2026-09-01T12:00:00Z",
            "end_at": "2026-09-01T12:31:00Z",
        },
        MGR,
    )
    validate_error(denied, ApiErrorId.ERR_BOOKING_DURATION_INVALID)


def test_service_quota_three_way_min(api: ApiClient):
    """PRD §3.5: "Duration is checked against the service ceiling: 480 minutes for `SLEEPING_AREA`, 30 minutes for `SHOWER`, 120 minutes for `CONNECTIVITY`, and 240 minutes for `FAMILY_ROOM`; a longer request is rejected with `ERR_BOOKING_DURATION_INVALID`."
    PRD §3.5: "The daily quota follows: a guest may hold at most 360 minutes of services per day — 240 minutes when the guest's `category` is `DEPENDENT` — where the minutes already used are the sum of durations of that guest's `BOOKED` bookings, at any center and of any service type, whose `start_at` falls on the current clock date; `COMPLETED` bookings no longer count. When the new booking's minutes exceed the remaining allowance, it is rejected with `ERR_QUOTA_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/service_quota_three_way_min
    """
    # OPEN center (coverage 1.0): the posture gate does not interfere.
    center, _volunteer, _shift, _assignment = setup_open_center(
        center_overrides={
            "name": "Gamma Center",
            "airport_code": "DFW",
            "occupancy_cap": 50,
        }
    )
    guest = create_guest(full_name="Dep Guest", category="DEPENDENT")
    # 120 + 90 = 210 of the DEPENDENT daily 240 already used.
    book_service(
        center["id"],
        guest["id"],
        service_type="CONNECTIVITY",
        start_at="2026-09-01T08:00:00Z",
        end_at="2026-09-01T10:00:00Z",
    )
    book_service(
        center["id"],
        guest["id"],
        service_type="CONNECTIVITY",
        start_at="2026-09-01T12:00:00Z",
        end_at="2026-09-01T13:30:00Z",
    )

    # 60 minutes passes the FAMILY_ROOM type ceiling (240) but exceeds the
    # 30 minutes of remaining daily quota.
    over = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "FAMILY_ROOM",
            "start_at": "2026-09-01T15:00:00Z",
            "end_at": "2026-09-01T16:00:00Z",
        },
        MGR,
    )
    validate_error(over, ApiErrorId.ERR_QUOTA_EXCEEDED)

    # 30 minutes is exactly the remaining allowance: not "exceeding" it.
    ok = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "SHOWER",
            "start_at": "2026-09-01T16:00:00Z",
            "end_at": "2026-09-01T16:30:00Z",
        },
        MGR,
    )
    booking = validate_success(ok, 201)
    assert booking["status"] == "BOOKED", (
        "30 <= 30 remaining quota and 30 <= 30 type max: the exact-boundary "
        "booking must succeed"
    )


def test_family_room_buffer_gap_semantics(api: ApiClient):
    """PRD §3.5: "The `FAMILY_ROOM` is exclusive, capacity 1, and carries a 45-minute cleaning buffer on each side: every existing pool booking blocks the buffered interval from 45 minutes before its `start_at` until 45 minutes after its `end_at`, and a new booking whose window intersects any buffered interval is rejected with `ERR_BOOKING_OVERLAP`. A gap of exactly 45 minutes is allowed — the new booking passes when it starts at or after an existing booking's buffered end, or ends at or before an existing booking's buffered start."

    Design: Difficulty/resource_temporal_overlap/family_room_buffer_gap_semantics
    """
    center, _volunteer, _shift, _assignment = setup_open_center(
        center_overrides={
            "name": "Pi Center",
            "airport_code": "TUS",
            "occupancy_cap": 30,
        }
    )
    guest = create_guest(full_name="G Room")
    # Existing booking 10:00-11:00 blocks the buffered interval 09:15-11:45.
    book_service(
        center["id"],
        guest["id"],
        service_type="FAMILY_ROOM",
        start_at="2026-09-01T10:00:00Z",
        end_at="2026-09-01T11:00:00Z",
    )

    adjacent = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "FAMILY_ROOM",
            "start_at": "2026-09-01T11:00:00Z",
            "end_at": "2026-09-01T11:30:00Z",
        },
        MGR,
    )
    validate_error(adjacent, ApiErrorId.ERR_BOOKING_OVERLAP)

    gap30 = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "FAMILY_ROOM",
            "start_at": "2026-09-01T11:30:00Z",
            "end_at": "2026-09-01T12:00:00Z",
        },
        MGR,
    )
    validate_error(gap30, ApiErrorId.ERR_BOOKING_OVERLAP)

    # 11:45 is exactly the existing booking's buffered end: allowed.
    ok = api.create_service_booking(
        center["id"],
        {
            "guest_id": guest["id"],
            "service_type": "FAMILY_ROOM",
            "start_at": "2026-09-01T11:45:00Z",
            "end_at": "2026-09-01T12:15:00Z",
        },
        MGR,
    )
    booking = validate_success(ok, 201)
    assert booking["status"] == "BOOKED", (
        "a gap of exactly 45 minutes (ROOM_BUFFER_MINUTES) must pass"
    )
    # Quota never interferes: 60 + 30 = 90 of 360 daily minutes used.


def test_booking_overlap_beats_quota(api: ApiClient):
    """PRD §2.7: "Only then do business rules run, in this relative order: state admissibility — the target entity must be in a from-state its transition allows, covering `ERR_INVALID_STATE`, `ERR_CENTER_CLOSED`, `ERR_ALREADY_CHECKED_IN`, `ERR_SCREENING_ALREADY_OPEN`, and `ERR_RENEWAL_WINDOW_NOT_OPEN`; then safety and compliance — `ERR_GUEST_INELIGIBLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_SECURITY_LEVEL_INSUFFICIENT`, `ERR_TALENT_AGREEMENT_UNSIGNED`, and `ERR_SEGREGATION_OF_DUTIES`; then temporal conflicts — `ERR_SHIFT_OVERLAP`, `ERR_BOOKING_OVERLAP`, and `ERR_EVENT_OVERLAP`; then capacity, quota, and selection — `ERR_CENTER_AT_CAPACITY`, `ERR_SHIFT_FULL`, `ERR_BOOKING_DURATION_INVALID`, `ERR_QUOTA_EXCEEDED`, `ERR_FEFO_VIOLATION`, `ERR_LOT_EXPIRED`, `ERR_INSUFFICIENT_QUANTITY`, and `ERR_STAFFING_SHORTFALL`; and finally fiscal sufficiency — `ERR_BUDGET_EXCEEDED`. A state error therefore surfaces before an overlap error, and an overlap error before a capacity one."

    Design: Difficulty/priority_pair_validation_conflict/booking_overlap_beats_quota
    """
    center, _volunteer, _shift, _assignment = setup_open_center(
        center_overrides={
            "name": "Kappa Center",
            "airport_code": "SFO",
            "occupancy_cap": 50,
        }
    )
    g1 = create_guest(full_name="G Book")
    g2 = create_guest(full_name="G Quota", category="DEPENDENT")
    # g1 holds the FAMILY_ROOM 10:00-11:00 (buffered interval 09:15-11:45).
    book_service(
        center["id"],
        g1["id"],
        service_type="FAMILY_ROOM",
        start_at="2026-09-01T10:00:00Z",
        end_at="2026-09-01T11:00:00Z",
    )
    # g2 (DEPENDENT) has used 210 of the 240 daily minutes: 30 remaining.
    book_service(
        center["id"],
        g2["id"],
        service_type="CONNECTIVITY",
        start_at="2026-09-01T08:00:00Z",
        end_at="2026-09-01T10:00:00Z",
    )
    book_service(
        center["id"],
        g2["id"],
        service_type="CONNECTIVITY",
        start_at="2026-09-01T12:00:00Z",
        end_at="2026-09-01T13:30:00Z",
    )

    # This request violates both the buffered-overlap rule (10:30 < 11:45)
    # and the quota (60 > 30 remaining); the temporal check runs first.
    resp = api.create_service_booking(
        center["id"],
        {
            "guest_id": g2["id"],
            "service_type": "FAMILY_ROOM",
            "start_at": "2026-09-01T10:30:00Z",
            "end_at": "2026-09-01T11:30:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP)
