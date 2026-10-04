"""Domain shape, defaults, pagination and resource-retrieval behaviour."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    get_site,
    get_shipper,
)


def test_product_configuration_derives_doses_per_carton(api):
    """PRD §3.1: "Creation also materialises the presentation's `doses_per_carton`,
    which is the label `doses_per_vial` multiplied by `vials_per_carton`; that
    derived figure is what every later dose count in this document divides or
    multiplies by."

    Design: Corner/entities/product_configuration_create_derives_doses_per_carton
    """
    res = api.create_product_configuration(
        {
            "product_code": "PZ-UCV-2026",
            "presentation": "MULTI_DOSE_VIAL",
            "doses_per_vial": 6,
            "vials_per_carton": 195,
            "min_order_cartons": 1,
        },
        TEST_USERS["manufacturing_qa_headers"],
    )
    pc = validate_success(res, 201)
    assert pc["doses_per_carton"] == 1170, "doses_per_carton is label doses times vials per carton"
    assert pc["cartons_per_pallet"] == 12
    assert pc["ship_box_cartons"] == 5
    assert pc["thaw_stability_hours"] == 120
    assert pc["refrigerated_shelf_life_hours"] == 720
    assert pc["refreeze_prohibited"] is True
    assert pc["punctured_bud_hours"] == 6

    retrieved = validate_success(
        api.get_product_configuration(pc["id"], TEST_USERS["manufacturing_qa_headers"]), 200)
    assert retrieved["doses_per_carton"] == 1170
    assert retrieved["id"] == pc["id"]


def test_jurisdiction_program_omitted_optionals_take_declared_defaults(api):
    """PRD §3.1: "a program-level `min_order_cartons` that defaults to 2, and a
    `reservable_carton_pct` that defaults to 0.5"

    PRD §3.1: "`standing_status`, starts at `OPEN` and is the aggregate that gates
    every child operation".

    Design: Corner/entities/jurisdiction_program_omitted_optional_fields_use_declared_defaults
    """
    res = api.create_jurisdiction_program(
        {
            "jurisdiction_code": "NV",
            "regulatory_body": "Nevada State Health Division",
            "allocation_basis": "FIXED_QUANTITY",
            "fixed_weekly_cartons": 20,
            "weekly_allocation_cap_cartons": 30,
            "acceptance_window_hours": 24,
            "shipping_days": ["TUESDAY"],
            "shipping_cutoff_utc": "11:30:00",
            "quarantine_on_review": False,
            "adjudication_sla_hours": 48,
            "segment_rule": "STOP",
            "reporting_period_days": 14,
        },
        TEST_USERS["regulatory_affairs_headers"],
    )
    program = validate_success(res, 201)
    assert program["min_order_cartons"] == 2
    assert program["reservable_carton_pct"] == 0.5
    assert program["standing_status"] == "OPEN"
    assert program["released_cartons_to_date"] == 0
    assert program["credit_balance_cartons"] == 0
    assert program["lapsed_carton_count"] == 0
    assert program["shipping_days"] == ["TUESDAY"]


def test_storage_site_round_trips_its_configuration(api):
    """PRD §3.3: "A new site begins uncertified and open: `equipment_certified` is
    false, `equipment_verification_id` is null, and `inventory_status` is `OPEN`."

    PRD §3.3: "Its `reported_entry_type` is the carton-count-weighted mode of the
    physical cartons it holds and defaults to `ULTRA_COLD`".

    Design: Corner/entities/storage_site_get_round_trips_its_configuration
    """
    program = make_program()
    site = make_site(program["id"], site_code="MI-RIV-09", site_name="Riverbend Cold Room",
                     storage_capability="REFRIGERATED", ultra_cold_capacity_cartons=0,
                     refrigerated_capacity_cartons=12,
                     cold_chain_equipment_type="THERMAL_SHIPPER",
                     expected_weekly_doses=1500)

    res = api.get_storage_site(site["id"], make_site_coordinator_headers(site["id"]))
    fetched = validate_success(res, 200)
    assert fetched["storage_capability"] == "REFRIGERATED"
    assert fetched["ultra_cold_capacity_cartons"] == 0
    assert fetched["cold_chain_equipment_type"] == "THERMAL_SHIPPER"
    assert fetched["equipment_certified"] is False
    assert fetched["equipment_verification_id"] is None
    assert fetched["inventory_status"] == "OPEN"
    assert fetched["reported_entry_type"] == "ULTRA_COLD"
    assert fetched["usable_doses"] == 0


def test_cartons_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List responses carry the pagination fields in the `meta` object of
    the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    PRD §2.3: "Unless a specific endpoint says otherwise, list endpoints return
    resources sorted by `created_at` in ascending order."

    Design: Corner/entities/cartons_list_paginates_with_total_count_and_has_more
    """
    product = make_product()
    program = make_program()
    batch = make_batch(product["id"], program["id"])
    for serial in ("C-01", "C-02", "C-03"):
        register_carton(batch["id"], serial=serial)
    release_batch(batch["id"])

    page1, meta1 = validate_paginated(
        api.list_cartons(TEST_USERS["manufacturing_qa_headers"],
                         params={"allocation_batch_id": batch["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_cartons(TEST_USERS["manufacturing_qa_headers"],
                         params={"allocation_batch_id": batch["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False

    frozen, meta_all = validate_paginated(
        api.list_cartons(TEST_USERS["manufacturing_qa_headers"],
                         params={"allocation_batch_id": batch["id"],
                                 "temperature_state": "ULTRA_COLD"}))
    assert len(frozen) == 3
    assert meta_all["total_count"] == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_carton_get_with_an_unknown_id_returns_resource_not_found(api):
    """PRD §2.7: "the system resolves each path segment left to right and stops at
    the first that does not resolve, returning `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/carton_get_with_an_unknown_id_returns_resource_not_found
    """
    res = api.get_carton(NON_EXISTENT_UUID, TEST_USERS["cold_chain_reviewer_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_site_order_create_missing_requested_doses_returns_invalid_request(api):
    """PRD §3.3: "A `SiteCoordinator` drafts an order against an entitlement for a
    site, supplying `requested_cartons`, a `requested_doses` figure the clinic
    actually needs"

    PRD §2.9: "A request whose body is malformed, missing a required field, carrying
    a wrong type, or holding a value outside a field's declared enum or numeric
    range is refused with `ERR_INVALID_REQUEST` (HTTP 400), and this shape check
    applies to every endpoint."

    Design: Corner/entities/site_order_create_missing_requested_doses_returns_invalid_request
    """
    from test_helpers import setup_entitled_site

    ctx = setup_entitled_site()
    res = api.create_site_order(
        {
            "allocation_entitlement_id": ctx["entitlement"]["id"],
            "storage_site_id": ctx["site"]["id"],
            "requested_cartons": 2,
        },
        make_site_coordinator_headers(ctx["site"]["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    listed = get_success_data(api.list_site_orders(
        TEST_USERS["distribution_planner_headers"],
        params={"allocation_entitlement_id": ctx["entitlement"]["id"]}))
    assert listed == []
    assert get_success_data(api.get_allocation_entitlement(
        ctx["entitlement"]["id"], TEST_USERS["distribution_planner_headers"]))["held_cartons"] == 0


def test_carton_thaw_ignores_client_supplied_system_fields(api):
    """PRD §2.5: "`version` is a system-managed integer that increments on every
    modification to the resource."

    PRD §2.5: "Derived-field recomputation counts as a modification: recomputing a
    jurisdiction program's `released_cartons_to_date`, or a site's `usable_doses`,
    or a carton's `remaining_doses`, refreshes `updated_at` and increments
    `version`."

    Design: Corner/entities/carton_thaw_invalid_input_extra_fields_are_ignored
    """
    from test_helpers import anchor_delivered_carton

    ctx = anchor_delivered_carton()
    carton = ctx["carton"]
    print("...")  # carton is ULTRA_COLD back at the site

    res = api.thaw_carton(carton["id"],
                          make_site_coordinator_headers(ctx["site"]["id"]),
                          payload={"temperature_state": "DESTROYED",
                                   "thawed_at": "2000-01-01T00:00:00Z",
                                   "version": 99})
    thawed = validate_success(res, 200)
    # PRD §2.5: "`version` is a system-managed integer".  The carton has already been
    # through registration, the ledger release at dispatch and the physical dose
    # recomputation at delivery, so the assertion is that the thaw advances it by
    # exactly one -- and that neither the client's 99 nor the client's forged
    # `thawed_at` survives.
    assert thawed["temperature_state"] == "THAWED"
    assert thawed["thawed_at"] == "2026-09-01T00:00:00Z"
    assert thawed["version"] == carton["version"] + 1
    assert thawed["current_expires_at"] == "2026-09-06T00:00:00Z"
    assert thawed["thaw_window_expires_at"] == "2026-09-06T00:00:00Z"


def test_product_configuration_out_of_enum_presentation_rejected(api):
    """PRD §3.1: "a `presentation` that is either `SINGLE_DOSE_VIAL` or
    `MULTI_DOSE_VIAL`"

    Design: Corner/entities/product_configuration_out_of_enum_presentation_rejected
    """
    res = api.create_product_configuration(
        {
            "product_code": "PZ-BAD-1",
            "presentation": "LYOPHILIZED",
            "doses_per_vial": 6,
            "vials_per_carton": 195,
            "min_order_cartons": 1,
        },
        TEST_USERS["manufacturing_qa_headers"],
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    listed = get_success_data(
        api.list_product_configurations(TEST_USERS["manufacturing_qa_headers"]))
    assert listed == []


def test_equipment_certified_is_derived_on_read_from_the_verification_ledger(api):
    """PRD §2.8: "A site's `equipment_certified` flag is true only under that
    condition and is false otherwise, and `equipment_verification_id` names the
    newest qualifying verification or is null."

    PRD §2.8: "Recording a new verification invalidates every earlier `RECORDED`
    verification on the same site whose `equipment_type` is `ULTRA_COLD_FREEZER`,
    timestamping the older row's `invalidated_at` with the logical clock and
    setting its `status` to `INVALIDATED`."

    Design: Corner/entities/equipment_certified_is_derived_on_read_from_the_verification_ledger
    """
    program = make_program()
    site = make_site(program["id"], site_code="MI-RIV-06")
    assert get_site(site["id"])["equipment_certified"] is False

    first = certify_site(site["id"], certificate_number="CERT-MI-0006A")
    assert get_site(site["id"])["equipment_certified"] is True
    assert get_site(site["id"])["equipment_verification_id"] == first["id"]

    certify_site(site["id"], certificate_number="CERT-MI-0006B",
                 verified_at="2026-09-02T00:00:00Z", outcome="FAILED")
    assert get_site(site["id"])["equipment_certified"] is False

    verifications = get_success_data(
        api.list_site_equipment_verifications(site["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    earlier = [v for v in verifications if v["id"] == first["id"]][0]
    assert earlier["status"] == "INVALIDATED"
    assert earlier["invalidated_at"] is not None


def test_reporting_period_reopen_versions_the_report(api):
    """PRD §3.9: "Reopening a submitted period returns it to `OPEN`, increments
    `report_version` by one, and drops the prior materialisation so that
    `accounted_doses` is recomputed under the effective variant when the period is
    resubmitted."

    Design: Corner/entities/reporting_period_reopen_versions_the_report
    """
    from test_helpers import make_reporting_period

    program = make_program()
    period = make_reporting_period(program["id"], period_start="2026-08-01T00:00:00Z",
                                   period_end="2026-08-08T00:00:00Z")

    submitted = validate_success(
        api.submit_reporting_period(period["id"], TEST_USERS["regulatory_affairs_headers"]), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["report_version"] == 1

    reopened = validate_success(
        api.reopen_reporting_period(period["id"], TEST_USERS["regulatory_affairs_headers"]), 200)
    assert reopened["status"] == "OPEN"
    assert reopened["report_version"] == 2
    assert reopened["released_doses"] == 0
    assert reopened["wastage_rate_basis_points"] == 0


def test_carton_family_create_links_the_two_sites_both_ways(api):
    """PRD §3.9: "A family membership is created by a `ColdChainReviewer` linking
    one site, `site_id`, to another, `member_site_id`, as two members of one
    excursion-sharing family, with `linked_at` recording the instant the link was
    made".

    Design: Corner/entities/carton_family_create_links_the_two_sites_both_ways
    """
    from test_helpers import make_family

    program = make_program()
    site_a = make_site(program["id"], site_code="MI-RIV-01")
    site_b = make_site(program["id"], site_code="MI-RIV-05",
                       storage_capability="REFRIGERATED", ultra_cold_capacity_cartons=0,
                       cold_chain_equipment_type="THERMAL_SHIPPER")

    family = make_family(site_a["id"], site_b["id"])
    assert family["site_id"] == site_a["id"]
    assert family["member_site_id"] == site_b["id"]
    assert family["shared_dose_count"] == 0

    found = get_success_data(
        api.list_carton_families(TEST_USERS["cold_chain_reviewer_headers"],
                                 params={"site_id": site_b["id"]}))
    assert len(found) == 1
    assert found[0]["id"] == family["id"]

    none_found = get_success_data(
        api.list_carton_families(TEST_USERS["cold_chain_reviewer_headers"],
                                 params={"site_id": "00000000-0000-4000-8000-000000000009"}))
    assert none_found == []