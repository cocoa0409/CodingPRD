"""Authorization: which role may act, and what X-User-ID must name."""
from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_item,
    create_pet,
    create_plan,
    create_product,
    create_site,
    read_prescription,
    set_clock,
    setup_prescription_item,
)


def test_care_agent_cannot_create_a_dispensing_site(api):
    """PRD §2.1: "A request whose role is declared but not permitted on the targeted
    operation is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."
    PRD §2.1: "Authorisation is evaluated strictly after header validation"
    PRD §4: "| POST | `/v1/pharmacy-sites` | Create a dispensing site with its state
    licences and cold-pack capacity | PlatformAdmin, ComplianceOfficer |"

    Design: Corner/rbac/care_agent_cannot_create_a_dispensing_site
    """
    set_clock()
    payload = {"site_code": "BOGUS1", "site_state": "CA", "licensed_states": ["CA"],
               "cold_pack_capacity_units": 10, "csr_registered": True}
    resp = api_client.create_site(payload,
                                 build_user_headers("cs-nope", "CustomerService"))
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")
    assert resp.status_code == 403

    sites = get_success_data(api_client.list_sites(TEST_USERS["compliance_officer_headers"]))
    assert sites == [], "the refused request created no site"


def test_denied_write_is_distinct_from_a_missing_user_context(api):
    """PRD §2.1: "The declared roles are exactly `Customer`, `ClinicContact`,
    `PharmacyTechnician`, `PharmacyManager`, `CustomerService`, `ComplianceOfficer`,
    and `PlatformAdmin`."
    PRD §2.1: "A request whose role is declared but not permitted on the targeted
    operation is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    Design: Corner/rbac/care_agent_cannot_create_a_dispensing_site
    """
    set_clock()
    site = create_site(site_code="RBAC-01", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=10, csr_registered=True)

    denied = api_client.create_site(
        {"site_code": "BOGUS2", "site_state": "CA", "licensed_states": ["CA"],
         "cold_pack_capacity_units": 10, "csr_registered": True},
        build_user_headers("cs-nope", "CustomerService"))
    assert denied.json()["data"]["error_id"] == "ERR_ROLE_NOT_PERMITTED"
    assert denied.json()["data"]["error_id"] != "ERR_MISSING_USER_CONTEXT"

    readable = get_success_data(api_client.list_sites(TEST_USERS["compliance_officer_headers"]))
    assert [s["id"] for s in readable] == [site["id"]]


def test_clinic_contact_cannot_run_the_callback_workflow(api):
    """PRD §4: "| POST | `/v1/prescriptions/{id}/clinic-contacts` | Record a clinic
    callback attempt | PharmacyTechnician, PharmacyManager |"
    PRD §2.1: "A request whose role is declared but not permitted on the targeted
    operation is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    Design: Corner/rbac/clinic_contact_cannot_run_the_callback_workflow
    """
    bundle = setup_prescription_item()
    vet = bundle["vet"]
    rx = bundle["rx"]

    resp = api_client.record_clinic_contact(
        rx["id"], build_user_headers(vet["id"], "ClinicContact"))
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")
    assert resp.status_code == 403

    rx_after = read_prescription(rx)
    assert rx_after["callback_attempt_count"] == 0
    assert rx_after["rx_status"] == "PENDING_VERIFICATION"


def test_clinic_contact_keeps_its_own_half_of_the_workflow(api):
    """PRD §3.3: "Authorisation itself belongs to a `ClinicContact`, whose `X-User-ID`
    identifies the acting `Veterinarian`."
    PRD §4: "| POST | `/v1/prescriptions/{id}/clinic-authorizations` | Record the
    veterinarian's authorization of a prescription | ClinicContact |"

    Design: Corner/rbac/clinic_contact_cannot_run_the_callback_workflow
    """
    bundle = setup_prescription_item(
        prescription_overrides=dict(script_source="WRITTEN_PRESCRIPTION",
                                    script_document_id=None,
                                    written_prescriber_email_hash="aruiz@bayviewvet.example"))
    vet = bundle["vet"]
    rx = bundle["rx"]
    get_success_data(api_client.record_clinic_contact(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]))

    resp = api_client.authorize_prescription(
        rx["id"], {}, build_user_headers(vet["id"], "ClinicContact"))
    assert resp.status_code == 200, (
        "the same role is permitted on its own half of the workflow"
    )
    assert resp.json()["data"]["rx_status"] == "VERIFIED"


def test_opaque_operations_roles_accept_arbitrary_operator_ids(api):
    """PRD §2.1: "When `X-User-Role` is `PharmacyTechnician`, `PharmacyManager`,
    `CustomerService`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an
    opaque operator identifier that is not tied to any persisted entity. The server
    may record it ... but never compares it to any entity's `id`, and resources are
    not scoped to it."

    Design: Corner/rbac/opaque_operations_roles_are_not_entity_backed
    """
    from test_helpers.fixtures import set_clock as _set_clock
    _set_clock()
    site = get_success_data(api_client.create_site(
        {"site_code": "OPQ1", "site_state": "CA", "licensed_states": ["CA"],
         "cold_pack_capacity_units": 12, "csr_registered": True},
        build_user_headers("co-arbitrary-operator-handle", "ComplianceOfficer")), 201)

    assert site["site_code"] == "OPQ1"
    fetched = get_success_data(api_client.get_site(
        site["id"], build_user_headers("some-other-handle", "PharmacyManager")))
    assert fetched["id"] == site["id"], (
        "the created site is addressable afterwards by any permitted operator"
    )


def test_the_pet_backed_role_is_held_to_a_stricter_standard(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Pet`; every ownership check on a resource that references a `Pet`
    compares the resource's foreign-key field to `X-User-ID`."
    PRD §2.10: "An identifier that does exist but belongs to a different owning
    party is reported as absent rather than as forbidden"

    Design: Corner/rbac/opaque_operations_roles_are_not_entity_backed
    """
    set_clock()
    pet = create_pet(pet_name="Basil", species="CAT", breed="Moggy",
                     weight_kg=4.5, owner_state="CA")

    resp = api_client.create_plan(
        {"pet_id": "00000000-0000-4000-8000-000000000000"},
        build_user_headers("00000000-0000-4000-8000-000000000000", "Customer"))
    validate_error(resp, "ERR_RESOURCE_NOT_FOUND")
    assert resp.status_code == 404


def test_plan_list_filters_by_the_pet_foreign_key(api):
    """PRD §3.1: "Plans may be listed and narrowed by `pet_id` or by `plan_status`,
    and read individually afterwards."
    PRD §2.3: "limit` defaults to 10, may be no smaller than 1 and no larger than
    100; `offset` defaults to 0."

    Design: Corner/entities/autoship_plan_filters_children_by_pet
    """
    set_clock()
    clover = create_pet(pet_name="Clover", species="DOG", breed="Mutt",
                        weight_kg=10.0, owner_state="CA")
    basil = create_pet(pet_name="Basil", species="CAT", breed="Moggy",
                       weight_kg=4.5, owner_state="NV")
    clover_plan_a = create_plan(clover)
    clover_plan_b = create_plan(clover)
    basil_plan = create_plan(basil)

    all_rows, meta = validate_paginated(api_client.list_plans(
        TEST_USERS["customer_service_headers"]))
    assert len(all_rows) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    clover_rows, clover_meta = validate_paginated(api_client.list_plans(
        TEST_USERS["customer_service_headers"],
        {"pet_id": clover["id"], "limit": 1, "offset": 0}))
    assert len(clover_rows) == 1
    assert clover_meta["total_count"] == 2
    assert clover_meta["has_more"] is True

    second_page, second_meta = validate_paginated(api_client.list_plans(
        TEST_USERS["customer_service_headers"],
        {"pet_id": clover["id"], "limit": 1, "offset": 1}))
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert {clover_plan_a["id"], clover_plan_b["id"]} == {
        clover_rows[0]["id"], second_page[0]["id"],
    }

    basil_rows, basil_meta = validate_paginated(api_client.list_plans(
        TEST_USERS["customer_service_headers"], {"pet_id": basil["id"]}))
    assert [r["id"] for r in basil_rows] == [basil_plan["id"]]
    assert basil_meta["total_count"] == 1