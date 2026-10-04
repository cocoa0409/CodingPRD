"""Machines whose lifecycle is cyclic rather than a one-way pipeline.

A bay is frozen and thawed by its parent store's posture, so ACTIVE to FROZEN
to ACTIVE is reachable more than once and a thawed bay must be usable again. A
booking carries two independent progression axes on one row: the screening axis
exists only for grooming, while the occupancy axis admits every service type
directly from REQUESTED.
"""

from test_helpers import (
    ApiErrorId,
    create_bay,
    create_booking,
    factories,
    get_success_data,
    setup_bay_frozen_then_thawed,
    setup_store_posture_frozen,
    setup_store_at_capacity,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]


def test_a_bay_frozen_by_the_store_posture_returns_to_active_on_the_thaw(api):
    """The bay's flag follows the parent store in both directions.

    PRD §3.3: "A bay moves from `ACTIVE` to `FROZEN` when its parent store's
    posture becomes `FROZEN`, which is the cascade above, and moves back to
    `ACTIVE` when the parent posture returns to `OPEN`."
    PRD §3.1: "it carries an `is_frozen` flag computed from the parent store's
    `hospital_posture`: the flag is true exactly when the store is `FROZEN`, so
    bays are frozen by the store rather than by anyone touching the bay directly."

    Design: Difficulty/non_linear_state_machine/service_bay_freeze_thaw_cycle
    """
    world = setup_bay_frozen_then_thawed(api)
    assert world["frozen_bay"]["status"] == "FROZEN"
    assert world["frozen_bay"]["is_frozen"] is True
    assert world["store"]["hospital_posture"] == "OPEN"
    assert world["bay"]["status"] == "ACTIVE"
    assert world["bay"]["is_frozen"] is False


def test_a_thawed_bay_is_schedulable_again(api):
    """A bay that has been frozen and thawed still takes bookings.

    PRD §3.3: "Bays belonging to the store whose status is `FROZEN` return to
    `ACTIVE` with `is_frozen` cleared to false"
    PRD §3.1: "A new bay starts `ACTIVE`"
    PRD §3.2: "The booking is created in `REQUESTED` with its
    `re_screen_required` flag false, its `screening_valid_until` null and its
    `screening_score` at zero"

    Design: Difficulty/non_linear_state_machine/service_bay_freeze_thaw_cycle
    """
    world = setup_bay_frozen_then_thawed(api)
    store_id = world["store"]["id"]
    pet = world["pet"]
    booking = create_booking(
        api,
        store_id,
        world["bay"]["id"],
        pet["id"],
        pet["version"],
        service_type="GROOMING",
        starts_at="2026-08-20T09:00:00Z",
        ends_at="2026-08-20T10:00:00Z",
    )
    assert booking["status"] == "REQUESTED"
    assert booking["screening_score"] == 0
    assert booking["re_screen_required"] is False


def test_screening_a_non_grooming_booking_is_refused_and_leaves_it_requested(api):
    """Only grooming carries a screening obligation.

    PRD §3.2: "Only grooming carries a screening obligation; the other three
    service types proceed to confirmation directly."
    PRD §3.2: "Screening is a `GroomingStaff` act against a booking in
    `REQUESTED`; against any other state it is refused with
    `ERR_BOOKING_NOT_SCREENABLE`, and against a booking that is not a grooming
    booking at all it is refused with `ERR_BOOKING_NOT_GROOMING`."

    Design: Difficulty/non_linear_state_machine/service_booking_parallel_screening_and_occupancy_dimensions
    """
    world = setup_store_at_capacity(api, hospital_capacity=4, encounter_count=0)
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "TRAINING")
    pet = world["pet"]
    booking = create_booking(
        api,
        store_id,
        bay["id"],
        pet["id"],
        pet["version"],
        service_type="TRAINING",
        starts_at="2026-08-21T09:00:00Z",
        ends_at="2026-08-21T10:00:00Z",
    )
    assert booking["screening_score"] == 0
    assert booking["screening_valid_until"] is None

    resp = api.screen_booking(
        store_id,
        booking["id"],
        factories.screening_payload(
            health_condition_points=0,
            aggression_acknowledged=True,
            expected_pet_version=pet["version"],
        ),
        GROOMER,
    )
    validate_error(resp, ApiErrorId.BOOKING_NOT_GROOMING.value)
    assert get_success_data(api.get_booking(booking["id"], ADMIN))["status"] == "REQUESTED"


def test_a_non_grooming_booking_is_bay_confirmed_directly_from_requested(api):
    """The occupancy axis admits a non-grooming booking without screening.

    PRD §3.2: "Only grooming carries a screening obligation; the other three
    service types proceed to confirmation directly."
    PRD §3.2: "A grooming booking must be in `SCREENED` to be confirmed and a
    non-grooming booking must not be, refused with `ERR_BOOKING_NOT_SCREENED` in
    either case where the check fails."
    PRD §3.2: "Confirmation is a `StoreManager` act"

    Design: Difficulty/non_linear_state_machine/service_booking_parallel_screening_and_occupancy_dimensions
    """
    from test_helpers import confirm_booking

    world = setup_store_at_capacity(api, hospital_capacity=4, encounter_count=0)
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "TRAINING")
    pet = world["pet"]
    booking = create_booking(
        api,
        store_id,
        bay["id"],
        pet["id"],
        pet["version"],
        service_type="TRAINING",
        starts_at="2026-08-21T09:00:00Z",
        ends_at="2026-08-21T10:00:00Z",
    )
    confirmed = confirm_booking(api, store_id, booking)
    assert confirmed["status"] == "BAY_CONFIRMED"
    assert confirmed["version"] > booking["version"]


def test_a_surge_escalation_carries_the_bay_into_the_frozen_state(api):
    """The direct OPEN to FROZEN jump freezes the store's bays.

    PRD §2.7: "A store may jump directly from `OPEN` to `FROZEN` when a surge
    pushes the ratio to the freeze boundary, bypassing `RESTRICTED` entirely."
    PRD §3.3: "Every bay of the store moves to `FROZEN` with `is_frozen` set true."
    PRD §2.7: "a ratio of at least 0.90 escalates it to `FROZEN`"

    Design: Difficulty/non_linear_state_machine/service_bay_freeze_thaw_cycle
    """
    world = setup_store_posture_frozen(api)
    store_id = world["store"]["id"]
    assert world["store"]["hospital_posture"] == "FROZEN"
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))
    assert bay["status"] == "FROZEN"
    assert bay["is_frozen"] is True