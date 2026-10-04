"""Applicant registration and application creation fundamentals (PRD §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_applicant,
    create_applicant_payload,
    create_application_payload,
    make_applicant_headers,
    register_applicant,
    setup_open_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_applicant_register_enrolled_missing_required_institution_returns_invalid_request(
    api, anonymous_headers,
):
    """PRD §3.2: "The `home_institution_name` is required exactly when the
    applicant type is ENROLLED_STUDENT and omitted otherwise
    (`ERR_VALIDATION`)."

    Design: Corner/entities/applicant_register_enrolled_missing_required_institution_returns_invalid_request
    """
    enrolled = api.create_applicant(
        create_applicant_payload(
            full_name="No Institution",
            applicant_type="ENROLLED_STUDENT",
            citizenship_country_code="US",
        ),
        anonymous_headers,
    )
    validate_error(enrolled, ApiErrorId.ERR_VALIDATION)

    independent = api.create_applicant(
        create_applicant_payload(
            full_name="Free Agent",
            applicant_type="INDEPENDENT",
            citizenship_country_code="US",
        ),
        anonymous_headers,
    )
    data = validate_success(independent, 201)
    assert_applicant(data)
    assert data["applicant_type"] == "INDEPENDENT"


def test_applicant_register_duplicate_email_rejected(api, anonymous_headers):
    """PRD §3.2: "Email addresses are unique across applicants: a duplicate
    registration is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/applicant_register_duplicate_email_rejected
    """
    first = api.create_applicant(
        create_applicant_payload(full_name="Twin One", email="twin@example.com"),
        anonymous_headers,
    )
    validate_success(first, 201)

    second = api.create_applicant(
        create_applicant_payload(
            full_name="Twin Two",
            email="twin@example.com",
            applicant_type="ENROLLED_STUDENT",
            home_institution_name="State University",
            citizenship_country_code="CA",
        ),
        anonymous_headers,
    )
    validate_error(second, ApiErrorId.ERR_DUPLICATE_EMAIL)


def test_application_create_with_unknown_field_rejected(
    api, program_officer_headers,
):
    """PRD §2.7: "Structural validation (`ERR_VALIDATION`, 400): required
    fields present, enum members valid, scores within 0–100, `end_date` after
    `start_date`, a stay's end not before its start, orientation not in the
    future, no unknown request fields, and `country_program_id` belonging to
    the addressed cycle."

    Design: Corner/entities/application_create_with_unknown_field_rejected
    """
    base = setup_open_cycle()
    applicant = register_applicant()
    payload = create_application_payload(
        applicant["id"], base["cycle"]["id"], base["program"]["id"],
        status="SELECTED",  # system-owned field: an unknown request field
    )
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    rows, meta = validate_paginated(
        api.list_applications(
            program_officer_headers, params={"applicant_id": applicant["id"]},
        )
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a rejected create must not persist an application"
    )


def test_application_get_with_unknown_id_returns_application_not_found(
    api, program_officer_headers,
):
    """PRD §2.7: "Each identifier in the path is resolved in left-to-right
    order: a missing cycle yields `ERR_CYCLE_NOT_FOUND`, country program
    `ERR_COUNTRY_PROGRAM_NOT_FOUND`, applicant `ERR_APPLICANT_NOT_FOUND`,
    application `ERR_APPLICATION_NOT_FOUND`, placement round
    `ERR_ROUND_NOT_FOUND`, grant `ERR_GRANT_NOT_FOUND`, visa sponsorship
    `ERR_VISA_NOT_FOUND`, residency ledger `ERR_LEDGER_NOT_FOUND`, report
    `ERR_REPORT_NOT_FOUND`, and incident `ERR_INCIDENT_NOT_FOUND` — all 404,
    and the first missing identifier wins."

    Design: Corner/entities/application_get_with_unknown_id_returns_application_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, program_officer_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_follow_on_without_history_returns_follow_on_ineligible(
    api, program_officer_headers,
):
    """PRD §3.2: "A follow-on application — `is_follow_on` set to true — is
    only accepted when the applicant's most recent alumni profile by
    `created_at` reports `follow_on_eligible` as ELIGIBLE
    (`ERR_FOLLOW_ON_INELIGIBLE`)."

    Design: Corner/cross_cutting_complexity_layers/follow_on_without_history_returns_follow_on_ineligible
    """
    base = setup_open_cycle()
    applicant = register_applicant()
    payload = create_application_payload(
        applicant["id"], base["cycle"]["id"], base["program"]["id"],
        proposed_duration_months=6, is_follow_on=True,
    )
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_FOLLOW_ON_INELIGIBLE)

    rows, meta = validate_paginated(
        api.list_applications(
            program_officer_headers, params={"applicant_id": applicant["id"]},
        )
    )
    assert rows == [] and meta["total_count"] == 0, (
        "an ineligible follow-on application must not be persisted"
    )
