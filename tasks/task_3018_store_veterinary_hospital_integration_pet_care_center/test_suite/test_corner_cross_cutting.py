"""Concurrency, deferred deadlines and the clinic-day overlap scope."""

from test_helpers import (
    ApiErrorId,
    bump_occupancy,
    create_clinic,
    get_success_data,
    set_clock,
    setup_grooming_booking,
    setup_store_at_capacity,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VACCINATION = TEST_USERS["vaccination_staff_headers"]
ANY = TEST_USERS["any_headers"]


def test_a_second_occupancy_bump_carrying_the_pre_bump_version_is_refused(api):
    """The bump advances the store row, so the earlier snapshot is stale.

    PRD §2.6: "The occupancy-bump capability is a write against a `Store`, so it
    must carry `expected_store_version`; a mismatch means the occupancy and
    posture recalculations have already advanced the store row and the caller's
    occupancy snapshot is stale, and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.6: "Supplying the field but with a value that does not equal the parent
    row's current `version` is rejected with `ERR_STALE_VERSION` carrying HTTP
    412."

    Design: Corner/cross_cutting_complexity_layers/repeated_bump_with_a_stale_store_version_is_refused
    """
    # A capacity of three with one scheduled encounter keeps the store below every
# posture boundary, so the second call reaches the staleness rule rather than
# being short-circuited by the frozen-store gate.
    world = setup_store_at_capacity(api, hospital_capacity=3, encounter_count=1)
    store_id = world["store"]["id"]
    version_before = world["store"]["version"]

    first = bump_occupancy(api, store_id, version_before, 1)
    assert first["version"] > version_before

    # The second bump moves nothing, so the store row it writes against is the
    # same one the first bump advanced.
    stale = api.bump_occupancy(
        store_id, {"expected_store_version": version_before, "magnitude": 0}, ADMIN
    )
    validate_error(stale, ApiErrorId.STALE_VERSION.value, 412)

    refreshed = bump_occupancy(api, store_id, first["version"], 0)
    assert refreshed["version"] > first["version"]


def test_screening_validity_lapse_re_arms_the_screening_gate(api):
    """The deadline is deferred: the clock, not a caller, arms the flag.

    PRD §3.2: "A screening does not stay valid indefinitely. It lapses 30 days
    after it was recorded, and the booking's `screening_valid_until` marks that
    horizon. A booking that is still non-terminal once the logical clock passes
    that instant has its `re_screen_required` flag set to true and is pulled back
    to the screening gate"
    PRD §3.2: "A booking that is still in `SCREENED` when its validity lapses
    returns to `REQUESTED` instead."
    PRD §3.2: "Recording the screening also appends an immutable
    `GroomingRiskScreening` row capturing the booking, the `risk_total`, the
    `health_condition_points`, the derived `handling_level`, the
    `aggression_acknowledged` flag and the `recorded_at` instant"
    PRD §3.2: "the cycle is `REQUESTED` to `SCREENED` and back again for as long
    as the booking lives"

    Design: Corner/cross_cutting_complexity_layers/screening_validity_lapse_re_arms_the_screening_gate
    """
    world = setup_grooming_booking(api, pet=("Wisp", "CANINE", "Whippet", 11.2))
    store_id = world["store"]["id"]
    pet = world["pet"]
    booking = world["booking"]

    from test_helpers import screen_booking

    # The screening is recorded on the clock the booking world was built with,
    # so the horizon is exactly thirty days later.
    set_clock(api, "2026-09-01T00:00:00Z")
    screened = screen_booking(
        api, store_id, booking, pet["version"], health_condition_points=0,
        aggression_acknowledged=True,
    )
    assert screened["screening_valid_until"] == "2026-10-01T00:00:00Z"
    assert screened["re_screen_required"] is False

    # Advance past the horizon; the flag arms and the grooming booking drops back
    # to the screening gate it had already cleared.
    set_clock(api, "2026-10-02T00:00:00Z")
    lapsed = get_success_data(api.get_booking(screened["id"], ANY))
    assert lapsed["re_screen_required"] is True
    assert lapsed["status"] == "REQUESTED"
    assert lapsed["screening_valid_until"] == "2026-10-01T00:00:00Z"


def test_two_clinics_of_one_store_may_not_hold_overlapping_windows_on_one_day(api):
    """The same occupancy idea applies to clinics, scoped to the clinic date.

    PRD §3.7: "No two clinics of the same store may hold overlapping `open_time`
    to `close_time` windows on the same `clinic_date`, so a second clinic that
    overlaps the first on that day is refused with `ERR_CLINIC_OVERLAP`."
    PRD §2.11: "no two clinics of the same store may hold overlapping `open_time`
    to `close_time` windows on the same `clinic_date`, reported as
    `ERR_CLINIC_OVERLAP`."
    PRD §3.7: "A new clinic begins in `SCHEDULED`."

    Design: Corner/cross_cutting_complexity_layers/two_walk_in_clinics_may_not_hold_overlapping_windows
    """
    from test_helpers import factories

    world = setup_store_at_capacity(api, hospital_capacity=3, encounter_count=0, state_code="CA")
    store_id = world["store"]["id"]
    create_clinic(
        api,
        store_id,
        clinic_date="2026-07-06T00:00:00Z",
        open_time="2026-07-06T09:00:00Z",
        close_time="2026-07-06T12:00:00Z",
    )

    overlapping = api.create_clinic(
        store_id,
        factories.clinic_payload(
            clinic_date="2026-07-06T00:00:00Z",
            open_time="2026-07-06T11:00:00Z",
            close_time="2026-07-06T14:00:00Z",
        ),
        VACCINATION,
    )
    validate_error(overlapping, ApiErrorId.CLINIC_OVERLAP.value, 409)

    # The identical clock times on the following day are admitted, which is what
    # makes the scope the clinic date rather than the store.
    next_day = create_clinic(
        api,
        store_id,
        clinic_date="2026-07-07T00:00:00Z",
        open_time="2026-07-07T11:00:00Z",
        close_time="2026-07-07T14:00:00Z",
    )
    assert next_day["clinic_status"] == "SCHEDULED"