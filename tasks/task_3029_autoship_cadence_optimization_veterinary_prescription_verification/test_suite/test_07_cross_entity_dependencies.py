"""Transitions whose validity depends on a separate resource's status."""
from test_helpers import TEST_USERS, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    add_item,
    cancel_order,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    create_site,
    decide_review,
    order_lines,
    read_order,
    read_plan,
    read_shipment,
    read_site,
    report_passing,
    set_clock,
    setup_canceled_cold_pack_order,
    ship_order,
    ship_order_ok,
)


def test_ship_is_gated_on_the_origin_sites_status(api):
    """PRD §3.7: "A restricted site is excluded from the candidate pool for new
    autoship work and is refused for a new autoship order, while remaining available
    to work already committed."
    PRD §3.5: "A shipment whose origin site is closed is refused with
    `ERR_SITE_RESTRICTED` and HTTP 409, and a site that is restricted is likewise
    refused for a new autoship order"

    Design: Difficulty/cross_entity_state_dependency/ship_is_gated_on_the_origin_sites_status_and_license
    """
    set_clock()
    site = create_site(site_code="OAK5", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=200, csr_registered=True)
    product = create_product(sku="XEN-H1", product_name="Cross-entity kibble",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Kip", species="DOG", breed="Terrier",
                     weight_kg=9.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)

    first_order = compose_ok(plan, pet)
    create_shipment(first_order)
    ship_order_ok(first_order)
    assert read_order(first_order, as_pet=pet)["order_status"] == "SHIPPED"

    set_clock("2026-10-02T00:00:00Z")
    second_order = compose_ok(plan, pet)
    second_shipment = create_shipment(second_order)
    get_success_data(api_client.restrict_site(
        site["id"], TEST_USERS["compliance_officer_headers"]), 200)

    resp = ship_order(second_order)
    validate_error(resp, "ERR_SITE_RESTRICTED")
    assert resp.status_code == 409

    assert read_order(second_order, as_pet=pet)["order_status"] == "PLACED"
    assert read_shipment(second_shipment)["shipment_status"] == "PENDING"
    assert read_site(site)["site_status"] == "RESTRICTED", (
        "the refusal leaked no side effect onto the site itself"
    )


def test_clearing_the_site_restriction_unblocks_the_same_request(api):
    """PRD §3.5: "Moving a site's `site_status` from `ACTIVE` to `RESTRICTED` removes
    it from the candidate pool used for new autoship work; clearing the restriction
    returns it to `ACTIVE`."
    PRD §3.5: "A shipment whose origin site is closed is refused with
    `ERR_SITE_RESTRICTED` and HTTP 409"

    Design: Difficulty/cross_entity_state_dependency/ship_is_gated_on_the_origin_sites_status_and_license
    """
    set_clock()
    site = create_site(site_code="OAK5", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=200, csr_registered=True)
    product = create_product(sku="XEN-H1", product_name="Cross-entity kibble",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Kip", species="DOG", breed="Terrier",
                     weight_kg=9.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    first_order = compose_ok(plan, pet)
    create_shipment(first_order)
    ship_order_ok(first_order)

    set_clock("2026-10-02T00:00:00Z")
    second_order = compose_ok(plan, pet)
    create_shipment(second_order)
    get_success_data(api_client.restrict_site(
        site["id"], TEST_USERS["compliance_officer_headers"]), 200)
    validate_error(ship_order(second_order), "ERR_SITE_RESTRICTED")

    get_success_data(api_client.clear_site_restriction(
        site["id"], TEST_USERS["compliance_officer_headers"]), 200)
    assert read_site(site)["site_status"] == "ACTIVE"

    ship_order_ok(second_order)
    assert read_order(second_order, as_pet=pet)["order_status"] == "SHIPPED"


def test_no_refund_is_written_before_the_review_is_decided(api):
    """PRD §3.6: "Approving writes a refund onto every cancelled order belonging to
    the linked pet's plans and cancels the parked shipment, releasing its
    reservation. Rejecting writes no refund at all and does not run the settlement"
    PRD §3.6: "while the pet is `PASSED` and the linked review is still `OPEN`, it
    reads `PASSED`"

    Design: Difficulty/cross_entity_state_dependency/review_decision_is_gated_on_the_pets_status
    """
    bundle = setup_canceled_cold_pack_order()
    pet = bundle["pet"]
    order = bundle["order"]
    plan = bundle["plan"]

    refund_after_cancel = order["refunded_amount_cents"]
    assert refund_after_cancel > 0, (
        "the cancellation settlement recomputes the affected orders' refunds"
    )
    pet_after = report_passing(pet, "WALLET")
    assert pet_after["pet_status"] == "PASSED"
    assert pet_after["pet_lifecycle_state"] == "PASSED"
    assert read_order(order, as_pet=pet)["refunded_amount_cents"] == refund_after_cancel, (
        "reporting the passing writes no further refund of its own"
    )
    assert read_plan(plan, pet)["plan_status"] == "COMPASSIONATE_CANCELED"
    assert pet_after["compassionate_review_id"] is not None, (
        "the passing opens the review whose approval settles the refund"
    )


def test_approving_the_review_writes_the_settled_refund(api):
    """PRD §3.6: "Within a contributing order, lines are walked in ascending line
    position but only lines whose product is cold-pack-required are counted: the
    first such line refunds its full `line_item_subtotal_cents`"
    PRD §3.6: "Either way the review becomes terminal, `APPROVED` or `REJECTED`, and
    the pet's `pet_lifecycle_state` is recomputed to `ARCHIVED`."

    Design: Difficulty/cross_entity_state_dependency/review_decision_is_gated_on_the_pets_status
    """
    bundle = setup_canceled_cold_pack_order(
        product_overrides=dict(unit_price_cents=1200, cold_pack_required=True,
                               sku="XEN-H2", product_name="Review gate pack"))
    pet = bundle["pet"]
    order = bundle["order"]
    plan = bundle["plan"]

    pet_after = report_passing(pet, "WALLET")
    review_id = pet_after["compassionate_review_id"]

    resp = decide_review(review_id, "APPROVED", "cs-morgan")
    assert resp.status_code == 200

    refunded = read_order(order, as_pet=pet)["refunded_amount_cents"]
    review = get_success_data(api_client.get_review(
        review_id, TEST_USERS["customer_service_headers"]))
    assert review["review_status"] == "APPROVED"
    assert refunded == 1200, (
        "the order's single cold-pack line refunds its full subtotal of 1200 cents"
    )
    assert review["refunded_amount_cents"] == 1200
    assert read_plan(plan, pet)["plan_status"] == "COMPASSIONATE_CANCELED"
    pet_final = get_success_data(api_client.get_pet(pet["id"],
                                                    TEST_USERS["customer_service_headers"]))
    assert pet_final["pet_lifecycle_state"] == "ARCHIVED"