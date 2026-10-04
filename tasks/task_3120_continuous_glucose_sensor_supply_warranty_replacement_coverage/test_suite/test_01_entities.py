"""Entities: creation defaults, server-minted fields, required-field and enum
checks, not-found handling, and default pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_patient,
    create_patient_payload,
    create_prescriber,
    create_prescriber_payload,
    create_prescription_payload,
    create_product,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_prescriber_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_patient_creation_returns_201_with_server_minted_fields(api):
    """PRD §2.4: "Every primary resource in the system carries a standard set
    of system-managed fields. The `id` is a server-minted UUID with no type
    prefix. The `created_at` field is an ISO 8601 UTC timestamp with three
    fractional digits captured when the resource was first persisted. The
    `updated_at` field uses the same format and refreshes on every mutation.
    The `version` field is an integer starting at 1 that increments on every
    mutation and serves as the optimistic-concurrency token for endpoints that
    accept one."
    PRD §3.1: "patients are created in `ACTIVE` status and may later be marked
    `DECEASED` or `TRANSFERRED_OUT` through administrative action."

    Design: Corner/entities/patient_creation_returns_201_with_server_minted_fields
    """
    resp = api.create_patient(
        {"full_name": "PT1", "date_of_birth": "1980-01-01", "state_code": "TX"}, ADMIN
    )
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"


def test_patient_missing_required_state_code_returns_invalid_request(api):
    """PRD §2.7: "`ERR_INVALID_REQUEST` covers malformed request payloads — a
    missing required field, a type mismatch, or an enum value outside the
    declared set — and is reported with HTTP 400."
    PRD §3.1: "A patient record captures the patient's `full_name`,
    `date_of_birth` as an ISO calendar date, and the `state_code` used for
    savings-card eligibility gating"

    Design: Corner/entities/patient_missing_required_state_code_returns_invalid_request
    """
    resp = api.create_patient({"full_name": "PT2", "date_of_birth": "1980-01-01"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_patient_default_status_active(api):
    """PRD §3.1: "patients are created in `ACTIVE` status and may later be
    marked `DECEASED` or `TRANSFERRED_OUT` through administrative action."

    Design: Corner/entities/patient_default_status_active
    """
    resp = api.create_patient(
        {"full_name": "PT3", "date_of_birth": "1980-01-01", "state_code": "NY"}, ADMIN
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


def test_sensor_lot_computed_complaint_count_starts_at_zero(api):
    """PRD §3.2: "New lots are created with `complaint_count` at zero and
    `complaint_posture` of `NORMAL`."

    Design: Corner/entities/sensor_lot_computed_complaint_count_starts_at_zero
    """
    product = create_product()
    resp = api.create_sensor_lot(
        product["id"],
        {
            "lot_code": "LC1",
            "quantity_manufactured": 5,
            "manufacture_date": "2026-08-01",
            "expiry_date": "2027-08-01",
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["complaint_count"] == 0
    assert data["complaint_posture"] == "NORMAL"


def test_patient_not_found_returns_404(api):
    """PRD §2.7: "The server first confirms the existence of the leftmost
    identifier, then the next, and so on; the first identifier that does not
    resolve to an existing resource yields `ERR_NOT_FOUND`, and deeper
    validation does not proceed."

    Design: Corner/entities/patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_invalid_enum_value_for_insulin_use_rejected(api):
    """PRD §2.7: "`ERR_INVALID_REQUEST` covers malformed request payloads — a
    missing required field, a type mismatch, or an enum value outside the
    declared set — and is reported with HTTP 400."
    PRD §3.3: "the patient's `insulin_use` classification (`INTENSIVE`,
    `BASAL_ONLY`, or `NONE`)"

    Design: Corner/entities/invalid_enum_value_for_insulin_use_rejected
    """
    patient = create_patient()
    prescriber = create_prescriber()
    product = create_product()
    payload = create_prescription_payload(
        prescriber["id"], product["id"], patient["version"], insulin_use="SOMETIMES"
    )
    resp = api.create_prescription(
        patient["id"], payload, make_prescriber_headers(prescriber["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_patient_list_pagination_default_limit_10(api):
    """PRD §2.3: "All list endpoints accept pagination via query string. The
    `limit` parameter specifies the maximum number of items to return; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` block of the envelope."

    Design: Corner/entities/patient_list_pagination_default_limit_10
    """
    for i in range(12):
        create_patient(full_name=f"PN{i + 1}")
    resp = api.list_patients(ADMIN)
    items, meta = validate_paginated(resp)
    assert len(items) == 10, f"expected default page of 10, got {len(items)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
