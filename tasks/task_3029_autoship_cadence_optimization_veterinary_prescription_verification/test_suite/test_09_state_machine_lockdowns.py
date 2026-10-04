"""Terminal states, non-idempotent triggers and clock-driven expiry."""
from test_helpers import TEST_USERS, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    add_item,
    authorize,
    cancel_order,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    create_site,
    deliver_order,
    read_item,
    read_order,
    read_plan,
    read_prescription,
    run_callback_attempt,
    set_clock,
    setup_prescription_item,
    setup_prescription_with_callback_attempts,
    ship_order,
    ship_order_ok,
)


def test_second_pause_of_the_same_plan_is_refused(api):
    """PRD §3.1: "An attempt to pause, resume or cancel from a status that does not
    admit the operation is refused with `ERR_INVALID_STATE` and HTTP 409."
    PRD §2.12: "a resource whose current status is not the transition's `from` status
    is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Corner/state_machines/paise_a_plan_that_is_already_paused_returns_invalid_state
    """
    set_clock()
    pet = create_pet(pet_name="Sable", species="CAT", breed="Korat",
                     weight_kg=4.0, owner_state="CA")
    plan = create_plan(pet)
    get_success_data(api_client.pause_plan(
        plan["id"], TEST_USERS["customer_service_headers"]), 200)

    resp = api_client.pause_plan(plan["id"], TEST_USERS["customer_service_headers"])
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409
    assert read_plan(plan, pet)["plan_status"] == "PAUSED"


def test_paused_plan_composition_reports_the_paused_error(api):
    """PRD §3.6: "it moves `plan_status` to `PAUSED` while leaving every item's
    `item_status` untouched, so the item roster survives the pause and composition
    against the paused plan reports `ERR_PLAN_PAUSED`."
    PRD §2.12: "a resource whose current status is not the transition's `from` status
    is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Corner/state_machines/paise_a_plan_that_is_already_paused_returns_invalid_state
    """
    set_clock()
    product = create_product(sku="STM-P1", product_name="Paused pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=900)
    pet = create_pet(pet_name="Sable", species="CAT", breed="Korat",
                     weight_kg=4.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    get_success_data(api_client.pause_plan(
        plan["id"], TEST_USERS["customer_service_headers"]), 200)

    resp = api_client.compose_order(plan["id"], {"expected_plan_version": 1},
                                   TEST_USERS["customer_service_headers"])
    validate_error(resp, "ERR_PLAN_PAUSED")
    assert resp.status_code == 409


def test_terminal_plan_cannot_be_resumed(api):
    """PRD §3.6: "the plan moves to the terminal `CANCELED`"
    PRD §3.1: "Cancelling, permitted from either `ACTIVE` or `PAUSED`, moves the
    item to the terminal `CANCELED`"
    PRD §2.12: "a resource whose current status is not the transition's `from` status
    is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Corner/state_machines/terminal_plan_cannot_be_resumed
    """
    set_clock()
    product = create_product(sku="STM-02", product_name="Terminal test pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=900)
    pet = create_pet(pet_name="Lark", species="DOG", breed="Basenji",
                     weight_kg=9.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    get_success_data(api_client.cancel_plan(
        plan["id"], {"cancellation_reason": "CUSTOMER_REQUEST"},
        TEST_USERS["customer_service_headers"]), 200)

    resp = api_client.resume_plan(plan["id"], TEST_USERS["customer_service_headers"])
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409
    assert read_plan(plan, pet)["plan_status"] == "CANCELED"


def test_cancelling_the_plan_leaves_the_item_roster_intact(api):
    """PRD §3.6: "the plan moves to the terminal `CANCELED`, and every order of the
    plan that is in `PLACED`, `PROCESSING`, `SHIPPED` or
    `AWAITING_PET_PASSING_DECISION` is cancelled along with its shipment."

    Design: Corner/state_machines/terminal_plan_cannot_be_resumed
    """
    set_clock()
    product = create_product(sku="STM-02", product_name="Terminal test pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=900)
    pet = create_pet(pet_name="Lark", species="DOG", breed="Basenji",
                     weight_kg=9.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    get_success_data(api_client.cancel_plan(
        plan["id"], {"cancellation_reason": "CUSTOMER_REQUEST"},
        TEST_USERS["customer_service_headers"]), 200)

    item_after = read_item(plan, pet, item)
    assert item_after["item_status"] == "ACTIVE", (
        "cancelling the plan did not cascade into item cancellation"
    )
    assert read_plan(plan, pet)["autoship_item_count"] == 1


def test_delivered_order_refuses_further_shipment_and_cancellation(api):
    """PRD §3.5: "Moving the order from `SHIPPED` to the terminal `DELIVERED` also
    moves its shipment from `DISPATCHED` to `DELIVERED`, and a delivered order
    carries no refund."
    PRD §2.12: "a resource whose current status is not the transition's `from` status
    is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Corner/state_machines/delivered_order_refuses_further_shipment_and_cancellation
    """
    set_clock()
    site = create_site(site_code="SAN9", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=90, csr_registered=True)
    product = create_product(sku="STM-03", product_name="Terminal order pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Juniper", species="DOG", breed="Kelpie",
                     weight_kg=16.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)
    shipment = create_shipment(order)
    ship_order_ok(order)
    deliver_order(order)

    assert read_order(order, as_pet=pet)["order_status"] == "DELIVERED"

    resp = cancel_order(order, "CUSTOMER_REQUEST", as_pet=pet)
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409

    order_after = read_order(order, as_pet=pet)
    assert order_after["order_status"] == "DELIVERED"
    assert order_after["refunded_amount_cents"] == 0
    shipment_after = get_success_data(api_client.get_shipment(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert shipment_after["shipment_status"] == "DELIVERED"


def test_delivered_order_refuses_a_repeat_ship_and_deliver(api):
    """PRD §2.12: "a resource whose current status is not the transition's `from`
    status is refused with `ERR_INVALID_STATE` at HTTP 409, except that composition
    against a non-`ACTIVE` plan is refused with the more specific `ERR_PLAN_PAUSED`"

    Design: Corner/state_machines/delivered_order_refuses_further_shipment_and_cancellation
    """
    set_clock()
    create_site(site_code="SAN9", site_state="CA", licensed_states=["CA"],
                cold_pack_capacity_units=90, csr_registered=True)
    product = create_product(sku="STM-03", product_name="Terminal order pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Juniper", species="DOG", breed="Kelpie",
                     weight_kg=16.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)
    create_shipment(order)
    ship_order_ok(order)
    deliver_order(order)

    ship_again = ship_order(order)
    validate_error(ship_again, "ERR_INVALID_STATE")
    deliver_again = api_client.deliver_order(order["id"],
                                            TEST_USERS["pharmacy_technician_headers"])
    validate_error(deliver_again, "ERR_INVALID_STATE")


def test_cancelling_the_same_order_twice_is_refused(api):
    """PRD §3.6: "Cancelling an order requires the order to be in `PLACED` or
    `PROCESSING` and requires a `cancellation_reason`"
    PRD §2.12: "a resource whose current status is not the transition's `from` status
    is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Corner/state_machines/cancelling_the_same_order_twice_is_refused
    """
    set_clock()
    product = create_product(sku="STM-04", product_name="Idempotency pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1770)
    pet = create_pet(pet_name="Rue", species="CAT", breed="Devon Rex",
                     weight_kg=3.5, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)
    first_cancel = cancel_order(order, "CUSTOMER_REQUEST")
    assert first_cancel.status_code == 200

    resp = cancel_order(order, "NON_DELIVERY")
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409
    assert read_order(order, as_pet=pet)["order_status"] == "CANCELED"


def test_a_refused_second_cancel_does_not_double_write_the_refund(api):
    """PRD §3.6: "In both cases the cancellation settlement recomputes the affected
    orders' refunds and the plan's released refunds."
    PRD §3.6: "An order's `refunded_amount_cents` stays 0 until it is cancelled or a
    compassionate review covering it is approved."

    Design: Corner/state_machines/cancelling_the_same_order_twice_is_refused
    """
    set_clock()
    product = create_product(sku="STM-04", product_name="Idempotency pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1770)
    pet = create_pet(pet_name="Rue", species="CAT", breed="Devon Rex",
                     weight_kg=3.5, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)
    cancel_order(order, "CUSTOMER_REQUEST")
    refund_after_first = read_order(order, as_pet=pet)["refunded_amount_cents"]

    validate_error(cancel_order(order, "NON_DELIVERY"), "ERR_INVALID_STATE")

    assert read_order(order, as_pet=pet)["refunded_amount_cents"] == refund_after_first
    orders = get_success_data(api_client.list_plan_orders(
        plan["id"], TEST_USERS["customer_service_headers"]))
    assert len(orders) == 1, "the refusal left no second order row behind"


def test_prescription_expires_when_the_clock_reaches_the_stamped_instant(api):
    """PRD §3.8: "every prescription whose `verification_expires_at` is at or before
    the new clock value is moved from `VERIFIED` to the terminal `EXPIRED` and has
    its owning item's verification marked `EXPIRATION_MARKED`"
    PRD §2.8: "The clock advancing to or past the expiry instant moves the
    prescription out of `VERIFIED` and marks the owning item's verification as
    expired."

    Design: Corner/state_machines/prescription_expires_when_the_clock_crosses_the_stamped_instant
    """
    bundle = setup_prescription_item(
        prescription_overrides=dict(authorized_qty_total=900, refills_authorized=12))
    rx = bundle["rx"]
    item = bundle["item"]

    run_callback_attempt(rx)
    authorized = get_success_data(authorize(rx, bundle["vet"]), 200)
    assert authorized["rx_status"] == "VERIFIED"
    expires_at = authorized["verification_expires_at"]

    set_clock("2027-08-31T00:00:00Z")
    assert read_prescription(rx)["rx_status"] == "VERIFIED", (
        "one day before the stamped instant the prescription is still usable"
    )

    set_clock(expires_at)
    manager_read = get_success_data(api_client.get_prescription(
        rx["id"], TEST_USERS["pharmacy_manager_headers"]))
    assert manager_read["rx_status"] == "EXPIRED"
    assert read_item(bundle["plan"], bundle["pet"], item)["verification_state"] == (
        "EXPIRATION_MARKED"
    )


def test_authorization_stamp_is_exactly_365_days_after_confirmation(api):
    """PRD §2.8: "Authorisation stamps an expiry instant exactly 365 days after the
    confirming authorisation, preserving the time of day of that confirmation."
    PRD §3.3: "the authorisation interval is half-open, so the prescription is usable
    strictly before the stamped instant and unusable from that instant onward."

    Design: Corner/state_machines/prescription_expires_when_the_clock_crosses_the_stamped_instant
    """
    bundle = setup_prescription_item()
    run_callback_attempt(bundle["rx"])
    authorized = get_success_data(authorize(bundle["rx"], bundle["vet"]), 200)

    assert authorized["verification_expires_at"] == "2027-09-01T00:00:00.000Z", (
        "confirmed on 2026-09-01, so the stamp is exactly 365 days later"
    )


def test_callback_attempt_beyond_the_cap_is_refused(api):
    """PRD §3.3: "The callback workflow is capped at three attempts. A pharmacy
    technician or manager records an attempt; the operation is available while
    `rx_status` is `PENDING_VERIFICATION` or `VERIFICATION_IN_PROGRESS`"
    PRD §3.3: "it moves the prescription to the terminal `VERIFICATION_FAILED` and
    fixes `callback_attempt_count` at 3"

    Design: Corner/endpoints/callback_attempt_beyond_the_cap_leaves_the_prescription_failed
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    rx = bundle["rx"]
    third = run_callback_attempt(rx)
    assert third["rx_status"] == "VERIFICATION_FAILED"

    resp = api_client.record_clinic_contact(rx["id"],
                                           TEST_USERS["pharmacy_technician_headers"])
    validate_error(resp, "ERR_INVALID_STATE")
    assert resp.status_code == 409

    rx_after = read_prescription(rx)
    assert rx_after["callback_attempt_count"] == 3, (
        "the refused attempt did not increment the count"
    )
    assert rx_after["rx_status"] == "VERIFICATION_FAILED"


def test_reopening_resets_the_attempt_window(api):
    """PRD §3.3: "A pharmacy manager can unwind that state with the reopen
    capability, which returns the prescription from `VERIFICATION_FAILED` to
    `PENDING_VERIFICATION`, resets `callback_attempt_count` to zero"
    PRD §2.8: "A verification block is only ever cleared by the pharmacy manager's
    reopen capability"

    Design: Corner/endpoints/callback_attempt_beyond_the_cap_leaves_the_prescription_failed
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    rx = bundle["rx"]
    run_callback_attempt(rx)
    validate_error(api_client.record_clinic_contact(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]), "ERR_INVALID_STATE")

    reopened = get_success_data(api_client.reopen_prescription(
        rx["id"], TEST_USERS["pharmacy_manager_headers"]), 200)
    assert reopened["rx_status"] == "PENDING_VERIFICATION"
    assert reopened["callback_attempt_count"] == 0

    after = run_callback_attempt(reopened)
    assert after["callback_attempt_count"] == 1
    assert after["rx_status"] == "VERIFICATION_IN_PROGRESS"