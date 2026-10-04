"""Baseline envelope, entity-shape, auth, and pagination corners."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS, api_client, create_agency,
    create_batch, create_contract_in_implementation, create_draft_contract,
    get_success_data, ingest_records, record_payload, reset_clock,
    staff_payload, validate_error, validate_paginated, validate_success,
)


def test_agency_create_returns_system_fields_and_active_status():
    """PRD §3.1: "An agency begins `ACTIVE`; once `ARCHIVED`, it rejects all new
    child creation." PRD §3.1: "A `PlatformAdmin` onboards each participating
    agency with its `agency_code` ... and optionally a `primary_time_zone` — an
    IANA zone that defaults to America/Chicago when omitted".

    Design: Corner/entities/agency_create_returns_system_fields_and_active_status
    """
    reset_clock()
    resp = api_client.create_agency(
        {"agency_code": "REV", "display_name": "Dept of Revenue"},
        TEST_USERS["platform_admin"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["primary_time_zone"] == "America/Chicago"
    for field in ("id", "created_at", "updated_at"):
        assert data.get(field) is not None, f"missing system field {field}"


def test_contract_get_missing_returns_not_found():
    """PRD §2.6: "Path-templated resources are then resolved left to right —
    each path segment must exist before the next is examined — with any miss
    returning `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/contract_get_missing_returns_not_found
    """
    reset_clock()
    resp = api_client.get_contract(NON_EXISTENT_UUID, TEST_USERS["procurement_officer"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_migration_record_has_no_version_field_immutable_log():
    """PRD §2.5: "`MigrationRecord`, `ReconciliationReport`, `TrainingEnrollment`,
    `UnavailabilityWindow`, and `AuditLogEntry` carry only `id` and `created_at`;
    both `updated_at` and `version` are absent from them, and nothing may target
    them with an optimistic-concurrency field."

    Design: Corner/entities/migration_record_has_no_version_field_immutable_log
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PAYROLL",
        expected_record_count=2, expected_net_value_cents=300,
    )
    ingest_records(batch["id"], [
        record_payload("A1", 100, field_payload={"x": 1}),
        record_payload("A2", 200, field_payload={"x": 2}),
    ])
    resp = api_client.list_records(batch["id"], TEST_USERS["data_migration_lead"])
    rows, _meta = validate_paginated(resp)
    assert len(rows) == 2
    keys = set()
    for row in rows:
        assert row.get("id"), "record id missing"
        assert row.get("created_at"), "record created_at missing"
        assert "version" not in row, "MigrationRecord must not carry version"
        assert "updated_at" not in row, "MigrationRecord must not carry updated_at"
        keys.add(row["legacy_primary_key"])
    assert keys == {"A1", "A2"}, "legacy_primary_key values must round-trip exactly"


def test_staff_default_status_and_function_enum():
    """PRD §3.1: "Agency staff are registered under their agency with
    `full_name`, an `email` unique within the agency, a whole number of
    `tenure_years`, and a `staff_function` of `SUBJECT_MATTER_EXPERT`,
    `UAT_TESTER`, `TRAINEE`, or `PROJECT_SPONSOR`." PRD §3.1: "Staff have a
    `status` of `ACTIVE` or `INACTIVE` and can be listed per agency with a
    `staff_function` filter."

    Design: Corner/entities/staff_default_status_and_function_enum
    """
    reset_clock()
    agency = create_agency()
    bad = api_client.create_staff(
        agency["id"],
        staff_payload(full_name="Bad Func", email="bf@x.gov", staff_function="MANAGER"),
        TEST_USERS["agency_pm"],
    )
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)
    ok = api_client.create_staff(
        agency["id"],
        staff_payload(full_name="Ok Func", email="of@x.gov", staff_function="TRAINEE"),
        TEST_USERS["agency_pm"],
    )
    data = validate_success(ok, expected_status=201)
    assert data["status"] == "ACTIVE"


def test_list_endpoint_pagination_envelope():
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. List responses are sorted by `created_at`
    ascending. The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_endpoint_pagination_envelope
    """
    reset_clock()
    agency = create_agency()
    create_draft_contract(agency["id"])
    create_draft_contract(agency["id"], solicitation_number="RFP-2026-002",
                          vendor_name="OtherVendor", contract_value_cents=1000)
    resp = api_client.list_contracts(TEST_USERS["procurement_officer"])
    rows, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing either header, or presenting a role outside
    the catalog below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.list_contracts(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_not_permitted_returns_forbidden():
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: the contract
    transition endpoint lists only ProcurementOfficer as authorized.

    Design: Corner/validations/role_not_permitted_returns_forbidden
    """
    reset_clock()
    agency = create_agency()
    contract = create_draft_contract(agency["id"])
    resp = api_client.transition_contract(
        contract["id"], {"target": "POSTED"}, TEST_USERS["vendor_pm"]
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_envelope_shape_on_failure():
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." PRD §2.2: "The `error_id` is
    a unique, machine-readable string that identifies the specific error. The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    reset_clock()
    resp = api_client.get_contract(NON_EXISTENT_UUID, TEST_USERS["platform_admin"])
    body = resp.json()
    assert body.get("response_type") == "error"
    data = body["data"]
    assert data["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(data["message"], str) and data["message"].strip()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
