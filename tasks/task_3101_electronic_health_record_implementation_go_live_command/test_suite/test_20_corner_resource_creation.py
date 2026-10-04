"""Resource creation: initial values, defaults and declared-field echoes."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_ehr_implementation,
    assert_facility,
    assert_interface_message,
    ApiErrorId,
    get_success_data,
    setup_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_department,
    create_interface_channel,
    create_interface_message_payload,
    create_build_item_payload,
    create_patient_order_payload,
    create_staff_payload,
    DIRECTOR,
    BUILD_ANALYST,
    INTERFACE,
    CONVERSION,
    TRAINING,
    ANALYST,
)


# ===========================================================================
# c_ehr_implementation_create_returns_all_declared_fields_and_planning
# ===========================================================================

def test_created_program_carries_its_declared_fields_and_opens_in_planning(api, director_headers):
    """PRD §3.1: "An `ImplementationDirector` opens a program by naming it. The
    creation payload carries the `program_name`, the `vendor_release` under
    implementation (for example `2026.2`), and the contracted
    `go_live_target_utc`."
    PRD §3.1: "A newly created program is in `PLANNING` status, its
    `current_epoch_index` is 0, and its `readiness_posture` is `OPEN`."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix or other
    decoration."

    Design: Corner/entities/c_ehr_implementation_create_returns_all_declared_fields_and_planning
    """
    created = validate_success(
        api_client.create_ehr_implementation(
            {
                "program_name": "Cascade Valley EHR",
                "vendor_release": "2026.2",
                "go_live_target_utc": "2026-12-01T00:00:00Z",
            },
            director_headers,
        ),
        201,
    )

    assert created["status"] == "PLANNING"
    assert created["readiness_posture"] == "OPEN"
    assert created["current_epoch_index"] == 0
    assert created["version"] == 1
    assert created["program_name"] == "Cascade Valley EHR"
    assert created["vendor_release"] == "2026.2"
    assert created["id"] and created["created_at"] and created["updated_at"]
    assert_ehr_implementation(created)


def test_program_creation_response_envelope_is_object_shaped_with_request_metadata(api, director_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/c_ehr_implementation_create_returns_all_declared_fields_and_planning
    """
    response = api_client.create_ehr_implementation(
        {
            "program_name": "Cascade Valley EHR",
            "vendor_release": "2026.2",
            "go_live_target_utc": "2026-12-01T00:00:00Z",
        },
        director_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]


# ===========================================================================
# c_facility_get_with_unknown_id_returns_facility_not_found
# ===========================================================================

def test_reading_an_unallocated_facility_reports_the_entity_specific_not_found(api, director_headers):
    """PRD §2.8: "The distinct not-found identifiers are
    `ERR_EHR_IMPLEMENTATION_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_BUILD_ITEM_NOT_FOUND`,
    `ERR_TEST_SCENARIO_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_CONVERSION_BATCH_NOT_FOUND`, and
    `ERR_PATIENT_ORDER_NOT_FOUND`, all at HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/c_facility_get_with_unknown_id_returns_facility_not_found
    """
    from test_helpers import set_clock

    set_clock()
    response = api_client.get_facility("00000000-0000-4000-8000-000000000000", director_headers)
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND, expected_status=404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] and body["data"]["message"]


# ===========================================================================
# c_staff_create_missing_required_name_returns_invalid_request
# ===========================================================================

def test_registering_a_staffer_without_a_name_is_a_request_shape_failure(api, director_headers):
    """PRD §2.11: "a request-shape gate refuses a malformed payload with
    `ERR_INVALID_REQUEST` (HTTP 400) — a missing required field, an invalid type
    or enum member, or any attempt to supply a server-managed `id`, `created_at`
    or `version`".
    PRD §3.4: "A `TrainingCoordinator` registers each person who will use the
    system, supplying their `full_name`".

    Design: Corner/entities/c_staff_create_missing_required_name_returns_invalid_request
    """
    prog, fac, dept = setup_program_facility_department()

    incomplete = create_staff_payload(fac["id"], dept["id"])
    del incomplete["full_name"]
    refused = api_client.create_staff(prog["id"], incomplete, TRAINING)
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(
        api_client.list_staffs(ANALYST, params={"department_id": dept["id"]})
    )
    assert meta["total_count"] == 0, "no staff row may be persisted by a refused request"


def test_the_required_name_omission_is_rejected_before_any_row_is_created(api, director_headers):
    """PRD §2.11: "a request-shape gate refuses a malformed payload with
    `ERR_INVALID_REQUEST` (HTTP 400) — a missing required field, an invalid type
    or enum member, or any attempt to supply a server-managed `id`, `created_at`
    or `version`".
    PRD §4: "a caller authenticated under any other role receives
    `ERR_UNAUTHORIZED`."

    Design: Corner/entities/c_staff_create_missing_required_name_returns_invalid_request
    """
    prog, fac, dept = setup_program_facility_department()
    before = validate_paginated(api_client.list_staffs(ANALYST, params={"department_id": dept["id"]}))

    incomplete = create_staff_payload(fac["id"], dept["id"])
    del incomplete["full_name"]
    api_client.create_staff(prog["id"], incomplete, TRAINING)

    after = validate_paginated(api_client.list_staffs(ANALYST, params={"department_id": dept["id"]}))
    assert after[1]["total_count"] == before[1]["total_count"] == 0


# ===========================================================================
# c_patient_order_create_defaults_billing_and_clinical_states
# ===========================================================================

def test_converted_order_starts_unposted_and_converted_with_a_computed_charge(api, conversion_headers):
    """PRD §3.7: "Converting a legacy order creates a patient order carrying the
    `patient_mrn` of the converted active patient, its `order_type` (exactly one
    of `MEDICATION`, `LAB`, `IMAGING` or `PROCEDURE`), its legacy `encounter_utc`
    and the `legacy_charge_cents` the old system captured."
    PRD §3.7: "The order starts in clinical state `CONVERTED` and billing state
    `UNPOSTED`, and at creation the system computes and publishes a provisional
    charge."

    A 25000-cent medication order carries a 3.0 percent dispensing line, so the
    provisional charge is 25750.00.

    Design: Corner/entities/c_patient_order_create_defaults_billing_and_clinical_states
    """
    prog, fac = setup_program_and_facility()
    order = validate_success(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-8001", order_type="MEDICATION",
            encounter_utc="2026-08-30T00:00:00Z", legacy_charge_cents=25000,
        ),
        conversion_headers,
    ), 201)

    assert order["billing_state"] == "UNPOSTED"
    assert order["clinical_state"] == "CONVERTED"
    assert order["provisional_charge_cents"] == pytest.approx(25750.00, abs=0.01), (
        f"25000 base + 3% dispensing = 25750.00; got {order['provisional_charge_cents']}"
    )


def test_converted_order_carries_no_paper_backfill_and_no_applied_balance(api, conversion_headers):
    """PRD §3.7: "Paper backfill is the compensating action for the downtime
    window."
    PRD §3.2: "a `BALANCES` load records its `reconciled_count` as
    `applied_balance_cents`, applying that many cents to the `balance_cents`
    carried by the affected patient orders."

    The client supplies none of the state fields, so the counters start at zero.

    Design: Corner/entities/c_patient_order_create_defaults_billing_and_clinical_states
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-8001", order_type="MEDICATION",
            encounter_utc="2026-08-30T00:00:00Z", legacy_charge_cents=25000,
        ),
        conversion_headers,
    ))

    assert order["paper_backfill_count"] == 0
    assert order["balance_cents"] == 0
    assert order["patient_mrn"] == "MRN-8001"


# ===========================================================================
# c_build_item_create_out_of_enum_classification_rejected
# ===========================================================================

def test_a_classification_outside_the_closed_enum_is_refused(api, build_analyst_headers):
    """PRD §2.12: "The `build_classification` is exactly one of
    `FOUNDATION_ADOPTED`, `FOUNDATION_ADAPTED` or `LOCAL_CUSTOM`".
    PRD §2.11: "a request-shape gate refuses a malformed payload with
    `ERR_INVALID_REQUEST` (HTTP 400) — a missing required field, an invalid type
    or enum member, or any attempt to supply a server-managed `id`, `created_at`
    or `version`".

    Design: Corner/entities/c_build_item_create_out_of_enum_classification_rejected
    """
    prog, fac, dept = setup_program_facility_department()

    refused = api_client.create_build_item(
        dept["id"],
        create_build_item_payload(
            application_code="LAB", build_classification="FULL_LOCAL_COPY",
            customization_depth=1, local_custom_fields=[],
        ),
        build_analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_the_refused_out_of_enum_build_item_is_never_persisted(api, build_analyst_headers, analyst_headers):
    """PRD §2.12: "`FOUNDATION_ADOPTED` means the foundation content was taken
    as shipped, `FOUNDATION_ADAPTED` means it was taken and lightly adjusted, and
    `LOCAL_CUSTOM` means it was replaced or extended locally."
    PRD §2.11: "a request-shape gate refuses a malformed payload with
    `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/c_build_item_create_out_of_enum_classification_rejected
    """
    prog, fac, dept = setup_program_facility_department()
    api_client.create_build_item(
        dept["id"],
        create_build_item_payload(build_classification="FULL_LOCAL_COPY"),
        build_analyst_headers,
    )

    rows, meta = validate_paginated(
        api_client.list_department_build_items(dept["id"], analyst_headers)
    )
    assert meta["total_count"] == 0


# ===========================================================================
# c_interface_message_is_immutable_and_carries_no_version_field
# ===========================================================================

def test_interface_message_read_exposes_no_version_and_no_updated_at(api, interface_headers):
    """PRD §2.4: "`InterfaceMessage` is the exception: it does not use the
    common-field treatment. A message row carries only `id` and `created_at`. It
    has no `updated_at` and no `version`, and no operation compares a version
    against it."
    PRD §2.4: "This matters because message rows are immutable observations".

    Design: Corner/entities/c_interface_message_is_immutable_and_carries_no_version_field
    """
    from test_helpers import create_program, set_clock

    set_clock()
    prog = create_program()
    channel = create_interface_channel(prog["id"])
    get_success_data(api_client.begin_channel_build(channel["id"], interface_headers))
    message = get_success_data(api_client.receive_message(
        channel["id"],
        create_interface_message_payload(
            message_code="ORU_R01", direction="INBOUND", sent_utc="2026-09-01T00:00:00Z"
        ),
        interface_headers,
    ))

    read = validate_success(api_client.get_interface_message(message["id"], interface_headers), 200)
    assert "version" not in read, "an append-only message row has no mutation counter"
    assert "updated_at" not in read
    assert read["id"] and read["created_at"]
    assert read["interface_channel_id"] == channel["id"]
    assert_interface_message(read)


def test_a_received_message_records_the_logical_clock_as_its_receipt_instant(api, interface_headers):
    """PRD §3.6: "the server stamps `received_utc` with the logical clock and
    computes `latency_minutes` as the interval between send and receipt expressed
    in minutes and rounded to two decimals."
    PRD §3.6: "A message begins with `validation_status` of `RECEIVED`, and its
    vocabulary is `RECEIVED`, `VALIDATED` and `REJECTED`."

    Design: Corner/entities/c_interface_message_is_immutable_and_carries_no_version_field
    """
    from test_helpers import create_program, set_clock

    set_clock()
    prog = create_program()
    channel = create_interface_channel(prog["id"])
    get_success_data(api_client.begin_channel_build(channel["id"], interface_headers))
    message = get_success_data(api_client.receive_message(
        channel["id"],
        create_interface_message_payload(
            message_code="ORU_R01", direction="INBOUND", sent_utc="2026-09-01T00:00:00Z"
        ),
        interface_headers,
    ))

    read = validate_success(api_client.get_interface_message(message["id"], interface_headers), 200)
    assert read["validation_status"] == "RECEIVED"
    assert read["received_utc"].startswith("2026-09-01T00:00:00")
    assert read["latency_minutes"] == pytest.approx(0.0, abs=0.01)


# ===========================================================================
# c_build_item_create_with_unknown_department_returns_not_found
# ===========================================================================

def test_creating_a_build_item_under_an_unallocated_department_reports_department_not_found(api, build_analyst_headers):
    """PRD §2.8: "The API validates path resources strictly left to right. When a
    path names more than one resource identifier, the system confirms the
    existence of the first, then the second, then the third, in the order the
    route declares them, and the request is rejected with the error corresponding
    to the *first* identifier that does not resolve."
    PRD §2.8: "Body-supplied foreign keys are validated with the same discipline.
    Where a creating endpoint's input list declares several foreign-key fields,
    they are checked strictly in the order declared, and the first unresolved key
    determines the error."

    Design: Corner/entities/c_build_item_create_with_unknown_department_returns_not_found
    """
    from test_helpers import set_clock

    set_clock()
    refused = api_client.create_build_item(
        "00000000-0000-4000-8000-000000000000",
        create_build_item_payload(
            application_code="LAB", build_classification="LOCAL_CUSTOM",
            customization_depth=2, local_custom_fields=["CF01"],
        ),
        build_analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND, expected_status=404)


def test_the_unresolved_parent_is_decided_before_any_body_field_is_examined(api, build_analyst_headers, analyst_headers):
    """PRD §2.8: "When a path names more than one resource identifier, the system
    confirms the existence of the first, then the second, then the third, in the
    order the route declares them, and the request is rejected with the error
    corresponding to the *first* identifier that does not resolve."
    PRD §2.8: "Body-supplied foreign keys are validated with the same discipline."

    Design: Corner/entities/c_build_item_create_with_unknown_department_returns_not_found
    """
    from test_helpers import set_clock

    set_clock()
    api_client.create_build_item(
        "00000000-0000-4000-8000-000000000000",
        create_build_item_payload(build_classification="LOCAL_CUSTOM"),
        build_analyst_headers,
    )
    rows, meta = validate_paginated(api_client.list_build_items(analyst_headers))
    assert meta["total_count"] == 0


# ===========================================================================
# c_created_resources_are_immediately_visible_on_read
# ===========================================================================

def test_a_registered_facility_is_fully_visible_on_the_next_read(api, director_headers):
    """PRD §3.2: "A facility joins the program through an `ImplementationDirector`
    who supplies its `name`, its `facility_type`, its `bed_count`, its
    `rollout_wave` and its `conversion_scope`."
    PRD §3.2: "A new facility starts in `SITE_REGISTERED` with `is_live` false."

    Design: Corner/consistency_model/c_created_resources_are_immediately_visible_on_read
    """
    prog = setup_program()
    created = validate_success(api_client.create_facility(
        prog["id"],
        {
            "name": "Cascade Valley West", "facility_type": "SPECIALTY",
            "bed_count": 40, "rollout_wave": 3, "conversion_scope": "DEMOGRAPHICS_ONLY",
        },
        director_headers,
    ), 201)

    read = validate_success(api_client.get_facility(created["id"], director_headers), 200)
    assert read["name"] == "Cascade Valley West"
    assert read["facility_type"] == "SPECIALTY"
    assert read["bed_count"] == 40
    assert read["rollout_wave"] == 3
    assert read["conversion_scope"] == "DEMOGRAPHICS_ONLY"
    assert read["status"] == "SITE_REGISTERED"
    assert read["is_live"] is False
    assert_facility(read)


def test_the_created_facility_echoes_its_own_id_and_parent_backlink(api, director_headers):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix or other
    decoration."
    PRD §3.2: "facilities can also be listed across programs, filtered by program
    or by wave."

    Design: Corner/consistency_model/c_created_resources_are_immediately_visible_on_read
    """
    prog = setup_program()
    created = validate_success(api_client.create_facility(
        prog["id"],
        {
            "name": "Cascade Valley West", "facility_type": "SPECIALTY",
            "bed_count": 40, "rollout_wave": 3, "conversion_scope": "DEMOGRAPHICS_ONLY",
        },
        director_headers,
    ), 201)

    read = validate_success(api_client.get_facility(created["id"], director_headers), 200)
    assert read["id"] == created["id"]
    assert read["ehr_implementation_id"] == prog["id"]

    listed, meta = validate_paginated(
        api_client.list_facilities(director_headers, params={"ehr_implementation_id": prog["id"]})
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == created["id"]