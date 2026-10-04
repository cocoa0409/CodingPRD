"""Programs, patients, and providers: creation defaults, required-field
validation, duplicate rejection, not-found handling, and envelope shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_patient,
    create_patient_payload,
    create_program_payload,
    get_success_data,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_create_program_missing_measure_year_rejected(api):
    """PRD §2.9: "request-body well-formedness (required fields present, types
    correct, enum values known — any failure here is `ERR_VALIDATION`)".
    PRD §3.1: "A `ProgramAdmin` supplies a unique `program_code`, a
    human-readable `program_name`, the `measure_year` the program reports
    against, and the `outreach_mode`".

    Design: Corner/entities/create_program_requires_core_fields
    """
    resp = api.create_program(
        {"program_code": "G-REQ", "program_name": "GReq", "outreach_mode": "PUSH"}, PA
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_program_success_applies_zero_counters(api):
    """PRD §3.1: "Newly created programs start with `population_size`,
    `attributed_count`, and `adherent_count` all at zero; these are
    system-maintained and never supplied by the client."

    Design: Corner/entities/create_program_requires_core_fields
    """
    resp = api.create_program(create_program_payload(program_code="G-REQ2"), PA)
    data = validate_success(resp, expected_status=201)
    assert data["population_size"] == 0
    assert data["attributed_count"] == 0
    assert data["adherent_count"] == 0


def test_create_patient_duplicate_external_ref_rejected(api):
    """PRD §3.2: "Attempting to register a patient whose `external_ref`
    duplicates an existing patient is rejected with `ERR_DUPLICATE_PATIENT`
    (HTTP 409)."

    Design: Corner/entities/create_patient_duplicate_external_ref_rejected
    """
    create_patient(external_ref="p-dup")
    resp = api.create_patient(
        create_patient_payload(external_ref="p-dup", date_of_birth="1971-01-01",
                               risk_category="ELEVATED"),
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PATIENT)


def test_patient_defaults_applied(api):
    """PRD §3.2: "Three advisory flags may accompany registration —
    `recent_symptoms`, `comorbidity`, and `family_history` — each a boolean
    defaulting to false, plus `contraindication_flags`, a list of
    contraindication codes defaulting to empty. A new patient's `status`
    starts at `ACTIVE`".

    Design: Corner/entities/patient_defaults_applied
    """
    patient = create_patient(external_ref="p-def")
    resp = api.get_patient(patient["id"], PA)
    data = validate_success(resp)
    assert data["contraindication_flags"] == []
    assert data["status"] == "ACTIVE"
    assert data["recent_symptoms"] is False
    assert data["comorbidity"] is False
    assert data["family_history"] is False


def test_program_computed_counters_start_at_zero(api):
    """PRD §3.1: "Newly created programs start with `population_size`,
    `attributed_count`, and `adherent_count` all at zero; these are
    system-maintained and never supplied by the client."

    Design: Corner/entities/computed_fields_ignore_client_input
    """
    resp = api.create_program(create_program_payload(program_code="G-CMP"), PA)
    data = validate_success(resp, expected_status=201)
    assert data["adherent_count"] == 0
    assert data["population_size"] == 0
    assert data["attributed_count"] == 0


def test_order_get_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve to an existing
    resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/order_get_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, PA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` of "error" and a `data`
    object carrying `error_id` and `message`; "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_order(NON_EXISTENT_UUID, PA)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
