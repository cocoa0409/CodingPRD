"""Which refusal a call reports when more than one rule could bite.

Two families live here. The un-groomable-breed rule is checked against a
request that trips no other rule, so the assertion pins the breed refusal on its
own footing. The pharmacy handoff rules are separated into two single-failure
scenarios: a revoked prescription with an in-range quantity, and an active
prescription with an over-large quantity.

Note on scope: the relative priority of a *pair* of simultaneously violated
business rules is not asserted anywhere in this file, because the PRD states the
ordering of the conditions inside a workflow but does not state which of two
independent refusals is reported first.
"""

from test_helpers import (
    create_booking,
    create_bay,
    create_breed_rule,
    create_pet,
    factories,
    get_success_data,
    read_booking,
    read_prescription,
    revoke_prescription,
    setup_authorized_prescription,
    setup_store_at_capacity,
    validate_error,
)
from test_helpers import ApiErrorId
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VET = TEST_USERS["veterinary_staff_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]
PHARMACY = TEST_USERS["pharmacy_staff_headers"]


def test_grooming_a_breed_whose_rule_forbids_it_is_refused(api):
    """The refusal is the breed rule, and no booking row is created.

    PRD §3.1: "A rule whose `allowed_for_grooming` is false makes that breed
    unschedulable for grooming outright: attempting to book or to bay-confirm a
    grooming service for such a breed is refused with `ERR_BREED_NOT_GROOMABLE`."

    Design: Difficulty/priority_pair_validation_conflict/groomable_breed_check_beats_bay_capacity_and_slot
    """
    create_breed_rule(
        api,
        breed="Dogo Argentino",
        species="CANINE",
        risk_points=40,
        handling_tier="HIGH_RISK",
        allowed_for_grooming=False,
    )
    world = setup_store_at_capacity(api, hospital_capacity=4, encounter_count=0)
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "GROOMING")
    bruno = create_pet(
        api, world["member"]["id"], name="Bruno", breed="Dogo Argentino", weight_kg=42.0
    )

    resp = api.create_booking(
        store_id,
        factories.booking_payload(
            bay_id=bay["id"],
            pet_id=bruno["id"],
            service_type="GROOMING",
            starts_at="2026-08-25T09:00:00Z",
            ends_at="2026-08-25T10:00:00Z",
            expected_pet_version=bruno["version"],
        ),
        GROOMER,
    )
    validate_error(resp, ApiErrorId.BREED_NOT_GROOMABLE.value)

    bookings = get_success_data(api.list_service_bookings(ADMIN, {"pet_id": bruno["id"], "limit": 100}))
    assert bookings == [], f"no booking may exist for an un-groomable breed, got {bookings}"


def test_confirming_a_booking_for_an_ungroomable_breed_is_refused(api):
    """The same breed rule blocks the confirmation as well as the booking.

    PRD §3.1: "A rule whose `allowed_for_grooming` is false makes that breed
    unschedulable for grooming outright: attempting to book or to bay-confirm a
    grooming service for such a breed is refused with `ERR_BREED_NOT_GROOMABLE`."
    PRD §3.2: "Confirmation is a `StoreManager` act, and it is where the screening
    result is enforced."
    PRD §3.2: "Only one rule may exist per breed and species pair."

    Design: Difficulty/priority_pair_validation_conflict/groomable_breed_check_beats_bay_capacity_and_slot
    """
    from test_helpers import screen_booking, setup_store_at_capacity

    world = setup_store_at_capacity(api, hospital_capacity=4, encounter_count=0)
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "GROOMING")
    bruno = create_pet(
        api, world["member"]["id"], name="Bruno", breed="Dogo Argentino", weight_kg=42.0
    )
    # The rule is registered after the booking exists, so the booking itself was
    # admissible at creation and only the confirmation meets the rule.
    booking = create_booking(
        api, store_id, bay["id"], bruno["id"], bruno["version"],
        service_type="GROOMING", starts_at="2026-08-26T09:00:00Z", ends_at="2026-08-26T10:00:00Z",
    )
    create_breed_rule(
        api, breed="Dogo Argentino", species="CANINE", risk_points=40,
        handling_tier="HIGH_RISK", allowed_for_grooming=False,
    )
    screened = screen_booking(api, store_id, booking, bruno["version"])
    assert screened["status"] == "SCREENED"
    assert screened["screening_score"] == 35

    resp = api.confirm_bay(
        store_id,
        screened["id"],
        {
            "expected_booking_version": screened["version"],
            "expected_pet_version": screened["pet_version"],
        },
        MANAGER,
    )
    validate_error(resp, ApiErrorId.BREED_NOT_GROOMABLE.value)
    assert read_booking(api, screened["id"])["status"] == "SCREENED"


def test_handoff_against_a_revoked_prescription_is_refused(api):
    """A revoked prescription funds no handoff, even at a quantity it once had.

    PRD §3.5: "An order raised against a prescription that is not `AUTHORIZED`
    or `PARTIALLY_DISPENSED`, or against one whose expiry has passed, is refused
    with `ERR_AUTHORIZATION_NOT_ACTIVE`."
    PRD §3.5: "a veterinarian may revoke a prescription while it is `AUTHORIZED`
    or `PARTIALLY_DISPENSED`"

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_fiscal_quantity
    """
    world = setup_authorized_prescription(
        api, item_type="MEDICATION", unit_price_cents=1800, quantity=2
    )
    store_id = world["store"]["id"]
    authorization = read_prescription(api, world["prescription"]["id"])
    assert authorization["status"] == "AUTHORIZED"

    revoked = revoke_prescription(api, store_id, authorization)
    assert revoked.status_code == 200, revoked.text

    # The requested quantity is inside what the prescription was written for, so
    # the quantity budget is satisfied and only the state rule can refuse.
    resp = raise_pharmacy_order_raw(api, store_id, authorization, requested_quantity=2)
    validate_error(resp, ApiErrorId.AUTHORIZATION_NOT_ACTIVE.value)
    orders = get_success_data(
        api.list_pharmacy_orders(ADMIN, {"authorization_id": authorization["id"], "limit": 100})
    )
    assert orders == []


def test_handoff_exceeding_the_prescribed_quantity_is_refused(api):
    """An active prescription refuses a handoff larger than what it was written for.

    PRD §3.5: "An order requesting more than the prescription's remaining
    quantity is refused with `ERR_QUANTITY_EXCEEDS_AUTHORIZATION`, which carries
    HTTP 402 rather than the 409 used by the other state conflicts, because it is
    a fiscal rather than a structural refusal."
    PRD §3.5: "The call carries `expected_order_version`, requires that the linked
    prescription's remaining quantity still support the order's
    `requested_quantity` (refused with `ERR_QUANTITY_EXCEEDS_AUTHORIZATION`
    otherwise)"

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_fiscal_quantity
    """
    world = setup_authorized_prescription(
        api, item_type="MEDICATION", unit_price_cents=1800, quantity=2
    )
    store_id = world["store"]["id"]
    authorization = read_prescription(api, world["prescription"]["id"])
    assert authorization["status"] == "AUTHORIZED"

    resp = raise_pharmacy_order_raw(api, store_id, authorization, requested_quantity=5)
    validate_error(resp, ApiErrorId.QUANTITY_EXCEEDS_AUTHORIZATION.value, 402)


def raise_pharmacy_order_raw(api, store_id, authorization, requested_quantity):
    """Raise a handoff without asserting a 201, so refusal cases can be checked."""
    return api.create_pharmacy_order(
        store_id,
        factories.pharmacy_order_payload(
            authorization_id=authorization["id"],
            requested_quantity=requested_quantity,
            expected_authorization_version=authorization["version"],
        ),
        PHARMACY,
    )
