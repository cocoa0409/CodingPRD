"""Response envelope shape, master-data creation defaults, entity 404s,
engine listing/pagination, and basic input-validation violations."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_engine,
    assert_directive,
    create_operator,
    create_engine,
    create_directive,
    create_operator_payload,
    create_engine_payload,
    TEST_USERS,
    make_operator_headers,
)


def test_engine_creation_defaults_and_system_fields(api, platform_admin_headers):
    """PRD §3.1: "A freshly registered engine starts with
    `cumulative_flight_hours` and `cumulative_cycles` both at 0, `status` of
    `IN_SERVICE`, `agreement_id` unset, `enrolled_at` unset, and
    `projected_next_removal_date` unset, because the removal projection cannot
    be computed until enrollment supplies the utilization assumptions."
    PRD §2.5: "**`version` (integer):** A system-managed integer that
    increments by 1 with every modification to the resource" (freshly
    created -> 1).

    Design: Corner/entities/engine_creation_defaults_and_system_fields
    """
    operator = create_operator(name="Arc Air", iata_code="AA", credit_rating="B")
    res = api.create_engine(
        create_engine_payload(
            operator_id=operator["id"],
            esn="ESN-C001",
            engine_model="CFM56-7B",
            base_severity_tier="MODERATE",
            llp_remaining_cycles=8000,
        ),
        platform_admin_headers,
    )
    engine = validate_success(res, 201)
    assert_engine(engine)
    assert is_valid_uuid(engine["id"]), "engine id must be a server-minted UUID"
    assert engine["status"] == "IN_SERVICE"
    assert engine["cumulative_flight_hours"] == 0
    assert engine["cumulative_cycles"] == 0
    assert engine["agreement_id"] is None
    assert engine["enrolled_at"] is None
    assert engine["projected_next_removal_date"] is None
    assert engine["version"] == 1


def test_directive_creation_has_no_version_field(api, platform_admin_headers):
    """PRD §2.5: "Two entity types are immutable, append-only records and
    carry **only** `id` and `created_at`: the `Directive` and the
    `RecognitionSnapshot`. Neither has an `updated_at` field nor a `version`
    field; a directive is never modified after issuance, and a recognition
    snapshot is a permanent point-in-time computation in an append-only
    history."

    Design: Corner/entities/directive_creation_has_no_version_field
    """
    res = api.create_directive(
        {
            "directive_ref": "SB-2026-0007",
            "directive_type": "SB",
            "applicability_model": "CFM56-7B",
            "mandatory": False,
            "estimated_cost_usd": 25000,
            "compliance_date": "2027-06-01T00:00:00Z",
        },
        platform_admin_headers,
    )
    directive = validate_success(res, 201)
    assert_directive(directive)
    assert is_valid_uuid(directive["id"])
    assert "created_at" in directive
    assert "version" not in directive, "append-only record must not expose version"
    assert "updated_at" not in directive, "append-only record must not expose updated_at"


def test_get_engine_returns_404_for_unknown_id(api, platform_admin_headers):
    """PRD §2.9: "Each resource type has its own not-found error:
    `ERR_OPERATOR_NOT_FOUND`, `ERR_ENGINE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_SHOP_VISIT_NOT_FOUND`, `ERR_WORKSCOPE_NOT_FOUND`,
    `ERR_REQUISITION_NOT_FOUND`, `ERR_SPARE_ENGINE_NOT_FOUND`,
    `ERR_LEASE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and
    `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/entities/get_engine_returns_404_for_unknown_id
    """
    res = api.get_engine(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_ENGINE_NOT_FOUND.value)


def test_engine_list_pagination_and_filters(api, finance_controller_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return." and "Paginated and non-paginated list-based responses include
    the following fields in the `meta` object of the response envelope:
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: "List engines; optional filters `operator_id` and `agreement_id`".

    Design: Corner/entities/engine_list_pagination_and_filters
    """
    operator = create_operator(name="Bay Air", iata_code="BA", credit_rating="C")
    for esn in ("ESN-C101", "ESN-C102", "ESN-C103"):
        create_engine(operator, esn=esn, base_severity_tier="BENIGN",
                      llp_remaining_cycles=5000)

    page1, meta1 = validate_paginated(
        api.list_engines(
            finance_controller_headers,
            params={"operator_id": operator["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_engines(
            finance_controller_headers,
            params={"operator_id": operator["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_not_found_battery_for_remaining_resources(api):
    """PRD §2.9: "For every request whose path contains resource identifiers,
    the system validates the existence of each identifier in a strict
    left-to-right order and rejects immediately with the `404 Not Found` error
    corresponding to the **first** identifier that does not resolve."
    PRD §3.1: "The referenced operator must exist: an `operator_id` that
    resolves to no registered operator is rejected with
    `ERR_OPERATOR_NOT_FOUND`."

    Design: Corner/entities/not_found_battery_for_remaining_resources
    """
    admin = TEST_USERS["platform_admin_headers"]
    manager = TEST_USERS["contract_manager_headers"]
    planner = TEST_USERS["shop_planner_headers"]
    finance = TEST_USERS["finance_controller_headers"]
    operator = create_operator(name="Cave Air", iata_code="CI", credit_rating="B")

    validate_error(api.get_agreement(NON_EXISTENT_UUID, manager),
                   ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value)
    validate_error(api.get_shop_visit(NON_EXISTENT_UUID, planner),
                   ApiErrorId.ERR_SHOP_VISIT_NOT_FOUND.value)
    validate_error(api.get_workscope(NON_EXISTENT_UUID, planner),
                   ApiErrorId.ERR_WORKSCOPE_NOT_FOUND.value)
    validate_error(api.source_part_requisition(NON_EXISTENT_UUID, planner),
                   ApiErrorId.ERR_REQUISITION_NOT_FOUND.value)
    validate_error(api.get_spare_engine(NON_EXISTENT_UUID, admin),
                   ApiErrorId.ERR_SPARE_ENGINE_NOT_FOUND.value)
    validate_error(
        api.activate_spare_engine_lease(
            NON_EXISTENT_UUID, make_operator_headers(operator["id"])
        ),
        ApiErrorId.ERR_LEASE_NOT_FOUND.value,
    )
    validate_error(api.verify_flight_hour_report(NON_EXISTENT_UUID, finance),
                   ApiErrorId.ERR_REPORT_NOT_FOUND.value)
    validate_error(api.settle_billing_statement(NON_EXISTENT_UUID, finance),
                   ApiErrorId.ERR_STATEMENT_NOT_FOUND.value)
    res = api.create_engine(
        create_engine_payload(
            operator_id=NON_EXISTENT_UUID,
            esn="ESN-C999",
            engine_model="CFM56-7B",
            base_severity_tier="BENIGN",
            llp_remaining_cycles=1000,
        ),
        admin,
    )
    validate_error(res, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value)


def test_invalid_enum_rejected_on_engine_create(api, platform_admin_headers):
    """PRD §2.8 (tier 4): "Required fields are present, types are valid, enum
    values are in range, numeric bounds are respected".
    PRD §3.1: "the `base_severity_tier` of the engine's home operation
    (`BENIGN`, `MODERATE`, or `HARSH`)".

    Design: Corner/validations/invalid_enum_rejected_on_engine_create
    """
    operator = create_operator(name="Hill Air", iata_code="HA", credit_rating="B")
    res = api.create_engine(
        create_engine_payload(
            operator_id=operator["id"],
            esn="ESN-H101",
            engine_model="CFM56-7B",
            base_severity_tier="EXTREME",
            llp_remaining_cycles=8000,
        ),
        platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_iata_rejected(api, platform_admin_headers):
    """PRD §3.1: "Registering any of these records colliding with an existing
    unique key — `iata_code`, `esn`, `spare_serial`, or `directive_ref` — is
    rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_iata_rejected
    """
    create_operator(name="Dune Air", iata_code="DG", credit_rating="A")
    res = api.create_operator(
        create_operator_payload(name="Dune Air Clone", iata_code="DG",
                                credit_rating="B"),
        platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_response_envelope_shape_success_and_error(api, platform_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."
    PRD §2.2 (error format): "The `error_id` is a unique, machine-readable
    string that identifies the specific error." and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    res = api.create_operator(
        create_operator_payload(name="Echo Envelope", iata_code="EI",
                                credit_rating="A"),
        platform_admin_headers,
    )
    operator = validate_success(res, 201)
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["id"] == operator["id"]

    err_res = api.get_agreement(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(err_res, ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value)
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_AGREEMENT_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert len(err_body["data"]["message"]) > 0
