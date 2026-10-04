"""Cross-entity gates: a booking is judged by an entity it does not own.

A confirmation turns on the parent bay's state, and beginning a course on a
training enrolment turns on the parent package's state. Both are
setup-versus-branch: the request is identical and the outcome separates on the
state of a neighbouring row.

The store-posture half of the same confirmation branch is not exercised here.
The specification's freeze cascade cancels every non-terminal booking of the
store's bays when the posture becomes FROZEN, so no booking can remain in
SCREENED for a confirmation to be refused on that ground.
"""

from test_helpers import (
    ApiErrorId,
    begin_course,
    create_bay,
    create_booking,
    pause_package,
    read_booking,
    read_enrollment,
    read_pet,
    read_store,
    screen_booking,
    setup_grooming_booking,
    setup_package_with_enrollment,
    setup_store_at_capacity,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TRAINER = TEST_USERS["training_staff_headers"]


def test_confirm_bay_is_refused_while_the_parent_bay_is_disabled(api):
    """A booking whose own state is valid is blocked by its bay's state.

    PRD §3.2: "whether the parent bay is `ACTIVE` (`ERR_BAY_NOT_ACTIVE`)"
    PRD §3.1: "When the last live booking clears, the bay moves to `DISABLED`,
    which is terminal, and it never returns to the schedule."
    PRD §3.2: "A grooming booking must be in `SCREENED` to be confirmed"

    Design: Difficulty/cross_entity_state_dependency/confirmation_requires_balancing_entity_active_and_store_unfrozen
    """
    # The bay is taken idle and disabled first (PRD §3.1 forbids disabling a bay
    # that still holds a live booking), and the screening is then recorded against
    # a fresh booking requested on that disabled bay.
    world = setup_store_at_capacity(api, hospital_capacity=4, encounter_count=0)
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "GROOMING")

    current_bay = api.get_store_service_bay(store_id, bay["id"], ADMIN).json()["data"]
    disabled = api.disable_service_bay(
        store_id, bay["id"], {"expected_bay_version": current_bay["version"]}, MANAGER
    )
    assert disabled.status_code == 200, disabled.text

    pet = read_pet(api, world["pet"]["id"])
    booking = create_booking(
        api, store_id, bay["id"], pet["id"], pet["version"],
        service_type="GROOMING", starts_at="2026-07-05T09:00:00Z", ends_at="2026-07-05T10:00:00Z",
    )
    booking = screen_booking(api, store_id, booking, pet["version"], aggression_acknowledged=True)
    assert booking["status"] == "SCREENED"

    resp = api.confirm_bay(
        store_id,
        booking["id"],
        {
            "expected_booking_version": booking["version"],
            "expected_pet_version": booking["pet_version"],
        },
        MANAGER,
    )
    validate_error(resp, ApiErrorId.BAY_NOT_ACTIVE.value)


def test_confirm_bay_is_refused_while_a_grooming_booking_is_still_unscreened(api):
    """The booking's own state gate and the bay gate are the same request shape.

    PRD §3.2: "A grooming booking must be in `SCREENED` to be confirmed and a
    non-grooming booking must not be, refused with `ERR_BOOKING_NOT_SCREENED` in
    either case where the check fails."
    PRD §3.2: "The call carries both `expected_booking_version` and
    `expected_pet_version`."
    PRD §3.2: "Only grooming carries a screening obligation; the other three
    service types proceed to confirmation directly."

    Design: Difficulty/cross_entity_state_dependency/confirmation_requires_balancing_entity_active_and_store_unfrozen
    """
    world = setup_grooming_booking(api, pet=("Tofu", "FELINE", "Ragdoll", 5.2))
    store_id = world["store"]["id"]
    booking = world["booking"]
    assert booking["status"] == "REQUESTED"

    response = api.confirm_bay(
        store_id,
        booking["id"],
        {
            "expected_booking_version": booking["version"],
            "expected_pet_version": booking["pet_version"],
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.BOOKING_NOT_SCREENED.value)
    assert read_booking(api, booking["id"])["status"] == "REQUESTED"


def test_begin_course_is_refused_while_the_parent_package_is_paused(api):
    """The training enrolment is PENDING_ACK and valid; its package is not.

    PRD §3.9: "it is refused when the parent package is not `ACTIVE`
    (`ERR_PACKAGE_NOT_ACTIVE`)"
    PRD §3.9: "Beginning a course is a distinct act from starting one, and it is
    the step that claims a trainer's slot. It is available only from
    `PENDING_ACK`"

    Design: Difficulty/cross_entity_state_dependency/training_start_requires_active_package_and_unfrozen_store_branch
    """
    world = setup_package_with_enrollment(api, tier="PLUS", courses_required=3, state_code="NY")
    store_id = world["store"]["id"]
    member_id = world["member"]["id"]
    enrollment = read_enrollment(api, world["enrollment"]["id"])

    pause_package(api, store_id, member_id, world["package"])

    resp = api.begin_course(
        store_id,
        enrollment["id"],
        {"expected_enrollment_version": enrollment["version"]},
        TRAINER,
    )
    validate_error(resp, ApiErrorId.PACKAGE_NOT_ACTIVE.value)


def test_begin_course_succeeds_while_the_parent_package_is_active(api):
    """The same call separates on the package's status: ACTIVE admits it.

    PRD §3.9: "It is available only from `PENDING_ACK`, and it is refused when the
    parent package is not `ACTIVE` (`ERR_PACKAGE_NOT_ACTIVE`)"
    PRD §3.9: "Beginning a course moves the enrolment to `RESTRICTED` and
    recomputes the store's `restricted_training_slots_pending` counter"
    PRD §3.9: "Beginning a course is a distinct act from starting one"

    Design: Difficulty/cross_entity_state_dependency/training_start_requires_active_package_and_unfrozen_store_branch
    """
    world = setup_package_with_enrollment(api, tier="PLUS", courses_required=3, state_code="NY")
    store_id = world["store"]["id"]
    enrollment = world["enrollment"]
    assert enrollment["status"] == "PENDING_ACK"

    moved = begin_course(api, store_id, enrollment)
    assert moved["status"] == "RESTRICTED"
    assert moved["version"] > enrollment["version"]
    store = read_store(api, store_id)
    assert store["restricted_training_slots_pending"] == 1
