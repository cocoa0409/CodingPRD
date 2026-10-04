"""Optimistic-concurrency failure modes and the ceiling on hospital bookings."""

from test_helpers import (
    ApiErrorId,
    create_bay,
    create_encounter,
    create_store,
    disable_bay,
    get_success_data,
    read_store,
    setup_bay_frozen_then_thawed,
    setup_store_at_capacity,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VET = TEST_USERS["veterinary_staff_headers"]


def test_omitting_the_expected_version_is_a_request_error_while_an_outdated_one_is_a_precondition_error(api):
    """Two neighbouring concurrency failures carry different statuses.

    PRD §2.6: "Omitting the field entirely is rejected with
    `ERR_MISSING_EXPECTED_VERSION`. Supplying the field but with a value that does
    not equal the parent row's current `version` is rejected with
    `ERR_STALE_VERSION` carrying HTTP 412."
    PRD §2.6: "disabling a bay carries `expected_bay_version`"
    PRD §2.4: "The `version` starts at 1 for a newly created row and is
    incremented by exactly 1 on every mutation of that row"

    Design: Corner/errors/missing_expected_version_is_distinct_from_a_stale_one
    """
    world = setup_bay_frozen_then_thawed(api)
    store_id = world["store"]["id"]
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))

    omitted = api.disable_service_bay(store_id, bay["id"], {}, MANAGER)
    validate_error(omitted, ApiErrorId.MISSING_EXPECTED_VERSION.value, 400)

    stale = api.disable_service_bay(
        store_id, bay["id"], {"expected_bay_version": bay["version"] - 1}, MANAGER
    )
    validate_error(stale, ApiErrorId.STALE_VERSION.value, 412)

    current = disable_bay(api, store_id, bay)
    assert current["status"] == "DISABLED"


def test_the_disabled_bay_distinguishes_the_missing_version_from_a_stale_one(api):
    """The same pair of failures on the same endpoint, isolated from the thaw.

    PRD §2.6: "The declaration is made through a request-body field named
    `expected_` followed by the parent entity's snake-case name and the suffix
    `_version`"
    PRD §2.6: "Supplying the field but with a value that does not equal the
    parent row's current `version` is rejected with `ERR_STALE_VERSION` carrying
    HTTP 412."
    PRD §3.1: "When the last live booking clears, the bay moves to `DISABLED`"

    Design: Corner/errors/missing_expected_version_is_distinct_from_a_stale_one
    """
    store = create_store(api, store_code="ST-1501", state_code="TX", hospital_capacity=3)
    bay = create_bay(api, store["id"], "GROOMING")

    omitted = api.disable_service_bay(store["id"], bay["id"], {}, MANAGER)
    validate_error(omitted, ApiErrorId.MISSING_EXPECTED_VERSION.value, 400)

    stale = api.disable_service_bay(
        store["id"], bay["id"], {"expected_bay_version": bay["version"] - 1}, MANAGER
    )
    validate_error(stale, ApiErrorId.STALE_VERSION.value, 412)

    disabled = disable_bay(api, store["id"], bay)
    assert disabled["status"] == "DISABLED"


def test_a_hospital_booking_is_refused_once_the_one_slot_over_capacity_allowance_is_spent(api):
    """Occupancy may exceed capacity by exactly one slot, no more.

    PRD §3.4: "A hospital booking may be created at exactly one occupancy slot
    above capacity and no more; a further booking past that is refused with
    `ERR_HOSPITAL_AT_CAPACITY`."
    PRD §2.7: "`hospital_occupancy`, recomputed as the number of that store's
    encounters currently in `SCHEDULED`, `CHECKED_IN` or `IN_EXAM`"
    PRD §2.7: "A scheduled appointment that has not yet checked in raises
    `hospital_occupancy` but not the occupied count"

    Design: Corner/errors/pharmacy_hold_blocks_new_encounters_while_orders_are_held
    """
    world = setup_store_at_capacity(api, hospital_capacity=1, encounter_count=1)
    store_id = world["store"]["id"]
    cached = read_store(api, store_id)
    assert cached["hospital_occupancy"] == 1
    assert cached["hospital_posture"] == "OPEN"

    # The allow bucket starts at two: the existing encounter holds one slot and
    # one further booking is still permitted.
    second = create_encounter(api, store_id, world["pet"]["id"], scheduled_at="2026-06-22T09:00:00Z")
    assert second["status"] == "SCHEDULED"

    from test_helpers import factories

    third = api.create_encounter(
        store_id,
        factories.encounter_payload(
            pet_id=world["pet"]["id"], scheduled_at="2026-06-23T09:00:00Z"
        ),
        VET,
    )
    validate_error(third, ApiErrorId.HOSPITAL_AT_CAPACITY.value)
    assert read_store(api, store_id)["hospital_occupancy"] == 2