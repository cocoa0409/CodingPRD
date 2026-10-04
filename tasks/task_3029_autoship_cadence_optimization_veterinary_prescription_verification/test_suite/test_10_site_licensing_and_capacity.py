"""Site selection, licensing gates, capacity refusals and reprice propagation."""
import math

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_clinic_contact_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_item,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    create_site,
    read_item,
    set_clock,
)


def test_a_second_shipment_for_the_same_order_is_refused(api):
    """PRD §3.5: "A shipment may only be created for an order in `PLACED`, and only
    once per order; a second attempt, or an attempt against an order in any other
    status, is refused with `ERR_ORDER_ALREADY_SHIPPED` and HTTP 409."

    Design: Corner/endpoints/an_order_can_only_be_shipped_once
    """
    set_clock()
    create_site(site_code="SAC2", site_state="CA", licensed_states=["CA"],
                cold_pack_capacity_units=60, csr_registered=True)
    product = create_product(sku="EPT-03", product_name="Single shipment pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Poppy", species="DOG", breed="Dalmatian",
                     weight_kg=25.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)
    shipment = create_shipment(order)

    resp = api_client.create_shipment({"order_id": order["id"]},
                                     TEST_USERS["pharmacy_technician_headers"])
    validate_error(resp, "ERR_ORDER_ALREADY_SHIPPED")
    assert resp.status_code == 409

    shipments = get_success_data(api_client.list_order_shipments(
        order["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert len(shipments) == 1
    assert shipments[0]["id"] == shipment["id"]
    assert read_shipment_status(shipment) == "PENDING"


def read_shipment_status(shipment: dict) -> str:
    return get_success_data(api_client.get_shipment(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))["shipment_status"]


def test_shipment_creation_without_an_order_is_refused(api):
    """PRD §2.10: "The request is rejected with `ERR_RESOURCE_NOT_FOUND` and HTTP 404
    for the first unresolvable identifier."

    Design: Corner/endpoints/shipment_creation_without_an_order_below_it_is_refused
    """
    set_clock()
    resp = api_client.create_shipment({"order_id": "00000000-0000-4000-8000-000000000000"},
                                     TEST_USERS["pharmacy_technician_headers"])
    validate_error(resp, "ERR_RESOURCE_NOT_FOUND")
    assert resp.status_code == 404

    shipments = get_success_data(api_client.list_shipments(
        TEST_USERS["pharmacy_technician_headers"]))
    assert shipments == [], "no shipment row was created"


def test_unknown_destination_has_no_eligible_site(api):
    """PRD §3.5: "when the candidate set is empty the creation fails with
    `ERR_NO_ELIGIBLE_SITE` and HTTP 409 rather than quietly falling back to a
    second-choice site."

    Design: Corner/errors/unknown_destination_contractually_has_no_eligible_site
    """
    set_clock()
    create_site(site_code="SAC3", site_state="CA", licensed_states=["CA"],
                cold_pack_capacity_units=80, csr_registered=True)
    product = create_product(sku="ERR-03", product_name="No site pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Lupin", species="DOG", breed="Akita",
                     weight_kg=30.0, owner_state="NV")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    order = compose_ok(plan, pet)

    resp = api_client.create_shipment({"order_id": order["id"]},
                                     TEST_USERS["pharmacy_technician_headers"])
    validate_error(resp, "ERR_NO_ELIGIBLE_SITE")
    assert resp.status_code == 409

    assert get_success_data(api_client.list_order_shipments(
        order["id"], TEST_USERS["pharmacy_technician_headers"])) == []


def test_read_only_site_selector_confirms_the_empty_pool(api):
    """PRD §3.8: "The second capability runs the site-selection procedure in
    read-only form for a given `destination_state` and an optional `cold_pack_units`
    figure, returning the eligible candidate sites in ranking order."
    PRD §3.5: "The candidates are the sites whose `site_status` is `ACTIVE`, whose
    `licensed_states` contain the shipment's `destination_state`"

    Design: Corner/errors/unknown_destination_contractually_has_no_eligible_site
    """
    set_clock()
    create_site(site_code="SAC3", site_state="CA", licensed_states=["CA"],
                cold_pack_capacity_units=80, csr_registered=True)

    resp = api_client.find_eligible_sites(
        TEST_USERS["compliance_officer_headers"], {"destination_state": "NV"})
    candidates, meta = validate_paginated(resp)
    assert candidates == [], "no site lists NV, so the pool is empty rather than mis-selected"

    ca_resp = api_client.find_eligible_sites(
        TEST_USERS["compliance_officer_headers"], {"destination_state": "CA"})
    ca_candidates = get_success_data(ca_resp)
    assert len(ca_candidates) == 1


def test_controlled_substance_registration_gap_blocks_authorization(api):
    """PRD §3.7: "a `CII` prescription may not be authorised at all unless every site
    whose `licensed_states` contains the owning pet's owner state holds a
    controlled-substance registration."
    PRD §3.3: "for a `CII` schedule, every site licensed for the owning pet's owner
    state must hold a controlled-substance registration, or the attempt is refused
    with `ERR_CSR_AUTH_BLOCKED`."

    Design: Corner/errors/controlled_substance_registration_gap_blocks_authorization
    """
    set_clock()
    create_site(site_code="SAC4", site_state="CA", licensed_states=["CA"],
                cold_pack_capacity_units=70, csr_registered=False)
    product = create_product(sku="ERR-04", product_name="Controlled pack",
                             medication_scope="PRESCRIPTION", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=3000)
    vet = get_success_data(api_client.create_veterinarian(
        {"full_name": "Dr Colin Beale", "clinic_name": "Delta Vet",
         "clinic_phone": "4155550108", "vet_email": "cbeale@deltavet.example",
         "license_number": "VET-CA-9008", "license_state": "CA"},
        TEST_USERS["pharmacy_technician_headers"]))
    pet = create_pet(pet_name="Sorrel", species="DOG", breed="Pointer",
                     weight_kg=26.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    rx = get_success_data(api_client.create_prescription(
        {"autoship_item_id": item["id"], "prescriber_id": vet["id"],
         "script_source": "UPLOADED_SCRIPT", "script_document_id": "doc-csr-1",
         "drug_schedule": "CII", "temperature_sensitive": False,
         "authorized_qty_total": 60, "refills_authorized": 0},
        TEST_USERS["pharmacy_technician_headers"]))
    get_success_data(api_client.record_clinic_contact(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]))

    resp = api_client.authorize_prescription(
        rx["id"], {}, make_clinic_contact_headers(vet["id"]))
    validate_error(resp, "ERR_CSR_AUTH_BLOCKED")
    assert resp.status_code == 422

    vet_after = get_success_data(api_client.get_veterinarian(
        vet["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert vet_after["vet_status"] == "LISTED", (
        "the prescriber is not at fault for a site registration gap"
    )
    rx_after = get_success_data(api_client.get_prescription(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert rx_after["rx_status"] == "VERIFICATION_IN_PROGRESS"


def test_product_price_change_propagates_to_the_item_mirror(api):
    """PRD §3.1: "A list price is changed by supplying a replacement
    `unit_price_cents`, which overwrites the stored price and forces every autoship
    item scheduling that product to recompute both its `unit_price_cents` and its
    `protection_state`."

    Design: Corner/entities/product_price_change_leaves_the_autoship_item_price_mirrored
    """
    set_clock()
    product = create_product(sku="ENT-04", product_name="Mirror price pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1200)
    pet = create_pet(pet_name="Plum", species="CAT", breed="Chartreux",
                     weight_kg=4.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    compose_ok(plan, pet)

    updated = get_success_data(api_client.change_product_price(
        product["id"], {"unit_price_cents": 1350},
        TEST_USERS["compliance_officer_headers"]), 200)
    assert updated["unit_price_cents"] == 1350

    item_after = read_item(plan, pet, item)
    assert item_after["unit_price_cents"] == 1350, (
        "the item mirrors the catalog price without any plan request"
    )
    assert item_after["price_protected_unit_price_cents"] == 1200, (
        "the locked protection price is not rewritten"
    )