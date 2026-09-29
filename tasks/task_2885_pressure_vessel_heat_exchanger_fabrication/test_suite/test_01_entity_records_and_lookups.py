"""Record creation, retrieval, defaults, derived fields and the not-found family."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_append_only_audit_fields,
    assert_full_audit_fields,
    assert_number_equals,
    assert_pagination_meta,
    assert_response_type,
    assert_three_fractional_digits,
)
from test_helpers.constants import (
    CERT_STATUS_ACTIVE,
    FAB_STATUS_PLANNED,
    FORM_PLATE,
    HEAT_STATUS_QUARANTINE,
    JOB_STATUS_DRAFT,
    JOINT_CATEGORY_A,
    JOINT_TYPE_BUTT,
    METHOD_PT,
    METHOD_RT,
    NDE_STATUS_NOT_PLANNED,
    PWHT_STATUS_NOT_REQUIRED,
    REQUIRED_COMPONENTS_PRESSURE_VESSEL,
    REQUIRED_TEST_SIDES_PRESSURE_VESSEL,
    ROLE_CODE_AUTHORIZED_INSPECTOR,
    ROLE_CODE_DESIGN_ENGINEER,
    RT_EXTENT_FULL,
    SPEC_SA_240_304L,
    SPEC_SA_516_70,
    UNKNOWN_UUID,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def test_recording_a_certificate_of_authorization_seeds_its_licence_posture(client, admin_headers):
    """Creation answers 201 with every posture field derived rather than supplied.

    PRD §3.1: "A fresh certificate opens at `status` `ACTIVE` with `open_major_findings_count` and `open_minor_findings_count` at 0, `renewal_count` at 0, `last_audit_closed_on` null and `stamping_authorized` true."

    Design: Corner/entities/entity_certificate_creation_returns_201_with_derived_posture
    """
    payload = factories.certificate_payload(
        cert_number="CA-U-8901",
        scope_codes=["U", "U2"],
        issued_on="2026-01-01",
        expires_on="2029-01-01",
    )

    response = client.create_certificate(payload, admin_headers)

    certificate = validate_success(response, 201)
    assert_response_type(response, "object")
    assert certificate["cert_number"] == "CA-U-8901"
    assert certificate["scope_codes"] == ["U", "U2"]
    assert certificate["status"] == CERT_STATUS_ACTIVE
    assert certificate["stamping_authorized"] is True
    assert certificate["open_major_findings_count"] == 0
    assert certificate["open_minor_findings_count"] == 0
    assert certificate["renewal_count"] == 0
    assert certificate["last_audit_closed_on"] is None
    assert_full_audit_fields(certificate, expected_version=1)


def test_reading_a_certificate_returns_the_stored_row_and_its_version(client, admin_headers):
    """A read of an untouched certificate mutates nothing and reports version 1.

    PRD §3.1: "Certificates can be listed and filtered by `status` and `cert_number`, and a single-certificate read is how a client obtains the `version` it will later need for a renewal."

    Design: Corner/entities/entity_certificate_retrieval_returns_stored_row_with_version
    """
    created = validate_success(
        client.create_certificate(
            factories.certificate_payload(
                cert_number="CA-U-8902",
                scope_codes=["U"],
                issued_on="2026-01-01",
                expires_on="2029-01-01",
            ),
            admin_headers,
        ),
        201,
    )

    response = client.get_certificate(created["id"], admin_headers)

    fetched = validate_success(response, 200)
    assert fetched["cert_number"] == "CA-U-8902"
    assert fetched["issued_on"] == "2026-01-01"
    assert fetched["expires_on"] == "2029-01-01"
    assert fetched["status"] == CERT_STATUS_ACTIVE
    assert fetched["stamping_authorized"] is True
    assert fetched["version"] == 1
    assert fetched["id"] == created["id"]


def test_listing_heats_counts_the_whole_filtered_set_rather_than_the_page(client, shop, admin_headers):
    """total_count spans the filtered set while has_more describes the window.

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope; `total_count` counts the records matching the filters before pagination is applied, and `has_more` states whether any matching record remains beyond the returned window."

    Design: Corner/entities/entity_material_heat_listing_paginated_with_total_count_and_has_more
    """
    heats = [
        shop.heat(heat_number="H-500{0}".format(index), spec=SPEC_SA_516_70, form=FORM_PLATE)
        for index in (1, 2, 3)
    ]

    first_response = client.list_heats(admin_headers, params={"limit": 2, "offset": 0})
    second_response = client.list_heats(admin_headers, params={"limit": 2, "offset": 2})
    filtered_response = client.list_heats(
        admin_headers,
        params={"spec": SPEC_SA_516_70, "status": HEAT_STATUS_QUARANTINE, "limit": 10, "offset": 0},
    )

    first_page, _ = validate_paginated(first_response)
    assert_response_type(first_response, "array")
    assert len(first_page) == 2
    assert_pagination_meta(first_response, limit=2, offset=0, total_count=3, has_more=True)

    second_page, _ = validate_paginated(second_response)
    assert len(second_page) == 1
    assert_pagination_meta(second_response, limit=2, offset=2, total_count=3, has_more=False)

    filtered, _ = validate_paginated(filtered_response)
    assert len(filtered) == 3
    assert_pagination_meta(filtered_response, limit=10, offset=0, total_count=3, has_more=False)
    assert all(row["status"] == HEAT_STATUS_QUARANTINE for row in filtered)

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == {heat["id"] for heat in heats}


def test_an_unknown_identifier_draws_the_resource_family_not_found(client, shop, admin_headers):
    """Each read-by-id endpoint reports the 404 belonging to its own resource type.

    PRD §2.9: "Wherever a path carries more than one identifier, the server resolves them strictly left to right and reports the **first** identifier that names nothing, with the 404 belonging to that segment's resource type."

    Design: Corner/entities/entity_lookup_with_unknown_uuid_returns_not_found_family
    """
    inspector = shop.qc_inspector()

    probes = [
        ("/personnel", api_errors.ERR_PERSONNEL_NOT_FOUND),
        ("/certificates", api_errors.ERR_CERTIFICATE_NOT_FOUND),
        ("/shop-audits", api_errors.ERR_AUDIT_NOT_FOUND),
        ("/vessel-jobs", api_errors.ERR_JOB_NOT_FOUND),
        ("/design-calculations", api_errors.ERR_CALCULATION_NOT_FOUND),
        ("/material-heats", api_errors.ERR_HEAT_NOT_FOUND),
        ("/parts", api_errors.ERR_PART_NOT_FOUND),
        ("/wps", api_errors.ERR_WPS_NOT_FOUND),
        ("/welder-qualifications", api_errors.ERR_QUALIFICATION_NOT_FOUND),
        ("/production-welds", api_errors.ERR_WELD_NOT_FOUND),
        ("/nde-exams", api_errors.ERR_EXAM_NOT_FOUND),
        ("/nonconformances", api_errors.ERR_NONCONFORMANCE_NOT_FOUND),
        ("/pwht-batches", api_errors.ERR_BATCH_NOT_FOUND),
        ("/pressure-tests", api_errors.ERR_TEST_NOT_FOUND),
        ("/data-reports", api_errors.ERR_REPORT_NOT_FOUND),
    ]

    for collection, expected_error_id in probes:
        response = client.get("{0}/{1}".format(collection, UNKNOWN_UUID), headers=admin_headers)
        assert response.status_code == 404, "{0} answered {1}".format(collection, response.status_code)
        validate_error(response, expected_error_id, 404)

    still_there = validate_success(client.get_person(inspector["id"], admin_headers), 200)
    assert still_there["id"] == inspector["id"]


def test_a_procedure_without_its_upper_thickness_limit_is_refused_by_the_shape_gate(client, shop, admin_headers):
    """Omitting a required field fails the shape gate and writes nothing.

    PRD §2.8: "**Request shape.** The body parses as JSON, every required field is present and non-null, every field carries its declared type, enum fields carry a declared value, decimal fields respect their declared scale, instant fields are ISO 8601 UTC instants and date fields are ISO 8601 calendar dates, quantities declared strictly positive are strictly positive, `limit` sits in the range 1 to 100 and `offset` is zero or greater, and `weld_ids` is an array whose entries are distinct."

    Design: Corner/entities/entity_wps_missing_required_thickness_max_returns_invalid_request
    """
    engineer = shop.welding_engineer()
    payload = factories.wps_payload(wps_number="WPS-90")
    payload.pop("thickness_max_in")

    response = client.create_wps(payload, shop.acting_as(engineer))

    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(client.list_wps(admin_headers, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_a_pressure_vessel_job_takes_its_declared_defaults_and_obligations(client, admin_headers, active_certificate):
    """The optional envelope inputs default and the structural obligations derive.

    PRD §3.2: "`required_components` — the design components that must each carry an approved calculation sheet before fabrication can be released — is `SHELL` and `HEAD` for a `PRESSURE_VESSEL`, and `SHELL`, `HEAD` and `TUBESHEET` for a `HEAT_EXCHANGER`."

    Design: Corner/entities/entity_vessel_job_defaults_applied_when_optional_inputs_omitted
    """
    payload = factories.vessel_job_payload(
        active_certificate["id"],
        job_number="J-2885-C06",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        mawp_psi=350,
    )
    assert "stress_ratio" not in payload
    assert "pneumatic_justification" not in payload

    response = client.create_job(payload, admin_headers)

    job = validate_success(response, 201)
    assert_number_equals(job["stress_ratio"], 1.00, 2, "stress_ratio")
    assert job["pneumatic_justification"] is None
    assert job["required_components"] == REQUIRED_COMPONENTS_PRESSURE_VESSEL
    assert job["required_test_sides"] == REQUIRED_TEST_SIDES_PRESSURE_VESSEL
    assert job["status"] == JOB_STATUS_DRAFT
    assert job["governing_joint_efficiency"] is None
    assert job["design_release_at"] is None
    assert job["nonconformance_open_count"] == 0
    assert_number_equals(job["weld_completion_pct"], 0.00, 2, "weld_completion_pct")
    assert_full_audit_fields(job, expected_version=1)


def test_material_class_and_p_number_come_from_the_specification_alone(client, shop):
    """A body that smuggles the derived material properties cannot override them.

    PRD §3.4: "Two properties are derived from `spec` alone and drive decisions much later in the process."

    Design: Corner/entities/entity_material_heat_computed_class_and_p_number_input_ignored
    """
    inspector = shop.qc_inspector()
    payload = factories.material_heat_payload(
        heat_number="H-5100",
        spec=SPEC_SA_240_304L,
        form=FORM_PLATE,
        quantity_received_lb=4000.00,
        yield_ksi=30.0,
        tensile_ksi=75.0,
    )
    payload["material_class"] = "FERRITIC"
    payload["p_number"] = 1

    response = client.create_heat(payload, shop.acting_as(inspector))

    heat = validate_success(response, 201)
    assert heat["material_class"] == "AUSTENITIC"
    assert heat["p_number"] == 8
    assert_number_equals(heat["quantity_issued_lb"], 0.00, 2, "quantity_issued_lb")
    assert_number_equals(heat["quantity_remaining_lb"], 4000.00, 2, "quantity_remaining_lb")
    assert heat["status"] == HEAT_STATUS_QUARANTINE
    assert_full_audit_fields(heat, expected_version=1)


def test_a_person_record_takes_a_server_minted_identity(client, shop, admin_headers):
    """The identifier and creation stamp are server-generated, never client-supplied.

    PRD §2.4: "Every record the API mints carries an `id`: a server-generated UUID, with no type prefix and no shop-specific formatting."

    Design: Corner/entities/entity_personnel_system_fields_generated_client_supplied_id_input_ignored
    """
    first = shop.register(ROLE_CODE_DESIGN_ENGINEER, full_name="Dana Reyes", stamp_initials="DR")
    payload = factories.personnel_payload(
        ROLE_CODE_DESIGN_ENGINEER, full_name="Efrain Cole", stamp_initials="EC"
    )
    payload["id"] = UNKNOWN_UUID
    payload["created_at"] = "1999-01-01T00:00:00.000Z"

    response = client.register_person(payload, admin_headers)

    person = validate_success(response, 201)
    assert person["id"] != UNKNOWN_UUID
    assert person["id"] != first["id"]
    assert person["created_at"] != "1999-01-01T00:00:00.000Z"
    assert person["created_at"] == "2026-08-01T00:00:00.000Z"
    assert person["full_name"] == "Efrain Cole"
    assert person["role_code"] == ROLE_CODE_DESIGN_ENGINEER
    assert person["stamp_initials"] == "EC"
    validate_error(
        client.get_person(UNKNOWN_UUID, admin_headers), api_errors.ERR_PERSONNEL_NOT_FOUND, 404
    )


def test_three_kinds_of_type_violation_are_all_refused_before_anything_is_written(client, shop, admin_headers):
    """An undeclared enum, a non-positive decimal and an inverted date pair all draw 400.

    PRD §2.6: "Values that a caller supplies at a finer scale than the field declares are a shape violation and draw `ERR_INVALID_REQUEST` (400) rather than being silently truncated."

    Design: Corner/entities/entity_type_constraint_violations_rejected_by_shape_gate
    """
    engineer = shop.welding_engineer()

    undeclared_enum = client.create_wps(
        factories.wps_payload(wps_number="WPS-91", process="TIG"), shop.acting_as(engineer)
    )
    non_positive = client.create_wps(
        factories.wps_payload(wps_number="WPS-92", thickness_min_in=0), shop.acting_as(engineer)
    )
    inverted_dates = client.create_certificate(
        factories.certificate_payload(
            cert_number="CA-U-8904", issued_on="2029-01-01", expires_on="2026-01-01"
        ),
        admin_headers,
    )

    validate_error(undeclared_enum, api_errors.ERR_INVALID_REQUEST, 400)
    validate_error(non_positive, api_errors.ERR_INVALID_REQUEST, 400)
    validate_error(inverted_dates, api_errors.ERR_INVALID_REQUEST, 400)

    _, wps_meta = validate_paginated(client.list_wps(admin_headers, params={"limit": 10, "offset": 0}))
    assert wps_meta["total_count"] == 0
    _, cert_meta = validate_paginated(
        client.list_certificates(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert cert_meta["total_count"] == 0


def test_a_person_record_exposes_neither_a_version_nor_an_update_stamp(client, shop, admin_headers):
    """Personnel is the append-only exception to the mutation-tracking fields.

    PRD §2.4: "A person record is immutable once registered, so it carries only `id` and `created_at`; it has no `updated_at` field and no `version` field, and no endpoint mutates it."

    Design: Corner/entities/entity_personnel_is_immutable_and_exposes_no_version_field
    """
    inspector = shop.register(
        ROLE_CODE_AUTHORIZED_INSPECTOR,
        full_name="Ada Nunes",
        stamp_initials="AN",
        ai_agency="Hartford Steam Boiler",
    )

    response = client.get_person(inspector["id"], admin_headers)

    person = validate_success(response, 200)
    assert person["full_name"] == "Ada Nunes"
    assert person["ai_agency"] == "Hartford Steam Boiler"
    assert "version" not in person
    assert "updated_at" not in person
    assert_append_only_audit_fields(person)
    assert_three_fractional_digits(person["created_at"], "created_at")

    listed, meta = validate_paginated(
        client.list_people(
            admin_headers,
            params={"role_code": ROLE_CODE_AUTHORIZED_INSPECTOR, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [inspector["id"]]
    assert "version" not in listed[0]


def test_an_unknown_parent_is_diagnosed_before_any_child_field(client, shop, admin_headers):
    """A path parent and a body parent each report their own 404.

    PRD §2.8: "**Body-reference existence.** Every identifier carried in the request body resolves to a live row, validated in the field order the endpoint declares — `certificate_id`, then `heat_id`, then `wps_id`, then `welder_qualification_id`, then `part_a_id`, then `part_b_id`, then `repair_of_weld_id`, then the entries of `weld_ids` — otherwise `ERR_CERTIFICATE_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_WPS_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_PART_NOT_FOUND` or `ERR_WELD_NOT_FOUND` (404)."

    Design: Corner/entities/entity_child_creation_under_unknown_parent_returns_not_found
    """
    engineer = shop.welding_engineer()
    heat = shop.accepted_heat(heat_number="H-5200", quantity_received_lb=2000.00)

    part_under_unknown_job = client.issue_part(
        UNKNOWN_UUID,
        factories.part_payload(heat["id"], part_mark="SH-01", issued_quantity_lb=1200.00),
        shop.acting_as(engineer),
    )
    job_under_unknown_certificate = client.create_job(
        factories.vessel_job_payload(UNKNOWN_UUID, job_number="J-2885-C11"), admin_headers
    )

    validate_error(part_under_unknown_job, api_errors.ERR_JOB_NOT_FOUND, 404)
    validate_error(job_under_unknown_certificate, api_errors.ERR_CERTIFICATE_NOT_FOUND, 404)

    unchanged = shop.read_heat(heat["id"])
    assert_number_equals(unchanged["quantity_issued_lb"], 0.00, 2, "quantity_issued_lb")
    assert_number_equals(unchanged["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb")
    _, meta = validate_paginated(client.list_parts(admin_headers, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_one_joint_is_the_junction_of_two_pieces_drawn_from_a_single_heat(client, shop, admin_headers):
    """The heat-part-joint closure fans in and every reverse filter resolves it.

    PRD §3.6: "It is `PT` when either joined piece traces to a heat whose `material_class` is `AUSTENITIC` — magnetic-particle examination is not valid on non-magnetic stainless, so dye penetrant is substituted."

    Design: Corner/entities/entity_graph_topology_weld_joins_two_parts_of_one_heat_and_reverse_filters_resolve
    """
    engineer = shop.welding_engineer()
    job = shop.job(job_number="J-2885-C12", mawp_psi=350, inside_radius_in=30)
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    heat = shop.accepted_heat(
        heat_number="H-5300",
        spec=SPEC_SA_240_304L,
        form=FORM_PLATE,
        quantity_received_lb=4000.00,
        yield_ksi=30.0,
        tensile_ksi=75.0,
    )
    part_a = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", component_type="SHELL", issued_quantity_lb=1200.00
    )
    part_b = shop.issue_part(
        job["id"], heat["id"], part_mark="HD-01", component_type="HEAD", issued_quantity_lb=600.00
    )
    wps = shop.qualified_wps(
        wps_number="WPS-93", process="GTAW", base_metal_p_number=8, filler_f_number=6
    )

    response = client.plan_weld(
        job["id"],
        factories.production_weld_payload(
            wps["id"],
            part_a["id"],
            weld_number="W-101",
            joint_category=JOINT_CATEGORY_A,
            joint_type=JOINT_TYPE_BUTT,
            thickness_in=0.7500,
            part_b_id=part_b["id"],
        ),
        shop.acting_as(engineer),
    )

    weld = validate_success(response, 201)
    assert weld["part_a_id"] == part_a["id"]
    assert weld["part_b_id"] == part_b["id"]
    assert weld["fab_status"] == FAB_STATUS_PLANNED
    assert weld["nde_status"] == NDE_STATUS_NOT_PLANNED
    assert weld["repair_generation"] == 0
    assert weld["pwht_status"] == PWHT_STATUS_NOT_REQUIRED
    assert weld["required_volumetric_pct"] == 100
    assert weld["volumetric_method"] == METHOD_RT
    assert weld["required_surface_method"] == METHOD_PT

    parts_of_heat, parts_meta = validate_paginated(
        client.list_parts(admin_headers, params={"heat_id": heat["id"], "limit": 10, "offset": 0})
    )
    assert parts_meta["total_count"] == 2
    assert {row["id"] for row in parts_of_heat} == {part_a["id"], part_b["id"]}

    by_part_a, meta_a = validate_paginated(
        client.list_welds(admin_headers, params={"part_a_id": part_a["id"], "limit": 10, "offset": 0})
    )
    assert meta_a["total_count"] == 1
    assert [row["id"] for row in by_part_a] == [weld["id"]]

    by_part_b, meta_b = validate_paginated(
        client.list_welds(admin_headers, params={"part_b_id": part_b["id"], "limit": 10, "offset": 0})
    )
    assert meta_b["total_count"] == 1
    assert [row["id"] for row in by_part_b] == [weld["id"]]

    _, swapped_meta = validate_paginated(
        client.list_welds(admin_headers, params={"part_a_id": part_b["id"], "limit": 10, "offset": 0})
    )
    assert swapped_meta["total_count"] == 0

    ledger = shop.read_heat(heat["id"])
    assert_number_equals(ledger["quantity_issued_lb"], 1800.00, 2, "quantity_issued_lb")
    assert_number_equals(ledger["quantity_remaining_lb"], 2200.00, 2, "quantity_remaining_lb")
