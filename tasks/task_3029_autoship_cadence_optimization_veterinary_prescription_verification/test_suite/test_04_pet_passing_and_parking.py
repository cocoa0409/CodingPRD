"""The pet-passing cascade, the parked order branch and read-your-writes behaviour."""
from test_helpers import TEST_USERS, api_client, validate_error
from test_helpers.fixtures import (
    decide_review,
    read_order,
    read_plan,
    read_shipment,
    report_passing,
    setup_dispatched_order,
)


def test_passing_forks_the_shipped_order_into_the_park_branch(api):
    """PRD §3.6: "The cascade then runs in order: every shipment of the pet's plans
    that is `DISPATCHED` becomes `AWAITING_PET_PASSING_DECISION`; each such
    shipment's order moves from `SHIPPED` to `AWAITING_PET_PASSING_DECISION` and
    stops advancing"
    PRD §3.6: "every plan of that pet moves from `ACTIVE` to the terminal
    `COMPASSIONATE_CANCELED`"

    Design: Difficulty/non_linear_state_machine/order_carries_a_second_parking_axis_beside_delivery
    """
    bundle = setup_dispatched_order()
    order = bundle["order"]
    shipment = bundle["shipment"]
    pet = bundle["pet"]

    assert order["order_status"] == "SHIPPED"
    assert read_shipment(shipment)["shipment_status"] == "DISPATCHED"

    report_passing(pet, "WALLET")

    assert read_order(order, as_pet=pet)["order_status"] == "AWAITING_PET_PASSING_DECISION"
    assert read_shipment(shipment)["shipment_status"] == "AWAITING_PET_PASSING_DECISION"
    assert read_plan(bundle["plan"], pet)["plan_status"] == "COMPASSIONATE_CANCELED"


def test_rejecting_the_review_still_cancels_the_parked_shipment(api):
    """PRD §3.6: "Rejecting writes no refund at all and does not run the settlement,
    but still cancels the parked shipment and releases its reservation."

    Design: Difficulty/non_linear_state_machine/order_carries_a_second_parking_axis_beside_delivery
    """
    bundle = setup_dispatched_order()
    order = bundle["order"]
    shipment = bundle["shipment"]
    pet = bundle["pet"]

    pet_after = report_passing(pet, "WALLET")
    review_id = pet_after["compassionate_review_id"]
    assert review_id is not None

    resp = decide_review(review_id, "REJECTED", "cs-dana")
    assert resp.status_code == 200

    assert read_shipment(shipment)["shipment_status"] == "CANCELED", (
        "the park branch terminates rather than joining the delivered join"
    )
    assert read_order(order, as_pet=pet)["refunded_amount_cents"] == 0, (
        "a rejected review writes no refund"
    )


def test_parked_order_cannot_take_the_delivery_join(api):
    """PRD §2.12: "a resource whose current status is not the transition's `from`
    status is refused with `ERR_INVALID_STATE` at HTTP 409"
    PRD §3.6: "Reporting a passing ... moves `pet_status` from `ACTIVE` to the
    terminal `PASSED`"

    Design: Difficulty/non_linear_state_machine/order_carries_a_second_parking_axis_beside_delivery
    """
    bundle = setup_dispatched_order()
    order = bundle["order"]
    pet = bundle["pet"]
    report_passing(pet, "WALLET")

    resp = api_client.deliver_order(order["id"], TEST_USERS["pharmacy_technician_headers"])
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409


def test_passing_parks_the_shipment_before_the_order_and_plan(api):
    """PRD §3.6: "every shipment of the pet's plans that is `DISPATCHED` becomes
    `AWAITING_PET_PASSING_DECISION`; each such shipment's order moves from `SHIPPED`
    to `AWAITING_PET_PASSING_DECISION` and stops advancing; every plan of that pet
    moves from `ACTIVE` to the terminal `COMPASSIONATE_CANCELED`; and a
    `CompassionateReview` is opened in `OPEN` with its `affected_shipment_id` bound
    to the parked shipment, or left null when nothing was in transit."

    Design: Difficulty/transitive_cascade/pet_passing_parks_the_shipment_order_and_plan_in_turn
    """
    bundle = setup_dispatched_order()
    shipment = bundle["shipment"]
    order = bundle["order"]
    plan = bundle["plan"]
    pet = bundle["pet"]

    pet_after = report_passing(pet, "ORIGINAL_PAYMENT")

    assert read_shipment(shipment)["shipment_status"] == "AWAITING_PET_PASSING_DECISION"
    assert read_order(order, as_pet=pet)["order_status"] == "AWAITING_PET_PASSING_DECISION"
    assert read_plan(plan, pet)["plan_status"] == "COMPASSIONATE_CANCELED"
    assert pet_after["pet_status"] == "PASSED"
    assert pet_after["pet_lifecycle_state"] == "PASSED"
    review_id = pet_after["compassionate_review_id"]
    review = api_client.get_review(review_id, TEST_USERS["customer_service_headers"])
    review_data = review.json()["data"]
    assert review_data["affected_shipment_id"] == shipment["id"]
    assert review_data["review_status"] == "OPEN"


def test_passing_opens_a_review_with_the_in_transit_shipment_bound(api):
    """PRD §3.6: "a `CompassionateReview` is opened in `OPEN` with its
    `affected_shipment_id` bound to the parked shipment, or left null when nothing
    was in transit."
    PRD §3.6: "A decision requires the review to be `OPEN`, requires the linked pet's
    `pet_status` to be `PASSED`, and requires the deciding identity to differ from
    the identity that recorded the passing"

    Design: Difficulty/transitive_cascade/pet_passing_parks_the_shipment_order_and_plan_in_turn
    """
    bundle = setup_dispatched_order()
    shipment = bundle["shipment"]
    pet = bundle["pet"]

    pet_after = report_passing(pet, "WALLET")

    review_id = pet_after["compassionate_review_id"]
    assert review_id is not None
    review = api_client.get_review(review_id, TEST_USERS["customer_service_headers"])
    review_data = review.json()["data"]
    assert review_data["review_status"] == "OPEN"
    assert review_data["affected_shipment_id"] == shipment["id"]
    assert review_data["pet_id"] == pet["id"]


def test_passing_effects_are_readable_on_the_very_next_request(api):
    """PRD §2.4: "When a parent resource is driven into a non-operational status, the
    platform resolves every dependent child in the same transaction rather than
    leaving orphans: cancelling a plan cancels its non-terminal orders and their
    shipments"
    PRD §3.6: "every plan of that pet moves from `ACTIVE` to the terminal
    `COMPASSIONATE_CANCELED`"

    Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_response
    """
    bundle = setup_dispatched_order()
    plan = bundle["plan"]
    shipment = bundle["shipment"]
    pet = bundle["pet"]

    pet_after = report_passing(pet, "WALLET")
    assert pet_after["compassionate_review_id"] is not None

    first_plan_read = read_plan(plan, pet)["plan_status"]
    first_shipment_read = read_shipment(shipment)["shipment_status"]
    assert first_plan_read == "COMPASSIONATE_CANCELED"
    assert first_shipment_read == "AWAITING_PET_PASSING_DECISION"

    assert read_plan(plan, pet)["plan_status"] == first_plan_read
    assert read_shipment(shipment)["shipment_status"] == first_shipment_read