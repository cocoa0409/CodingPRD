"""Corner breadth index (entities): applicator registration defaults,
required-field closure, and not-found lookup.
"""
from test_helpers import (
    PLATFORM_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    applicator_payload,
    assert_applicator,
    validate_error,
    validate_success,
)


def test_applicator_creation_defaults_score_500_registered(api: ApiClient):
    """PRD §3.3: "A `PlatformAdmin` registers one with a `company_name` and
    `contact_email`; the record begins in `REGISTERED` status with a
    `quality_history_score` of exactly 500 and a
    `consecutive_passed_inspections` streak of 0."

    Design: Corner/entities/applicator_creation_defaults_score_500_registered
    """
    applicator = validate_success(
        api.create_applicator(
            applicator_payload(company_name="Acme Coaters LLC", contact_email="ops@acme.example"),
            PLATFORM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )

    assert_applicator(applicator)
    assert applicator["quality_history_score"] == 500
    assert applicator["consecutive_passed_inspections"] == 0
    assert applicator["status"] == "REGISTERED"


def test_applicator_creation_missing_contact_email_rejected(api: ApiClient):
    """PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/applicator_creation_missing_contact_email_rejected
    """
    response = api.create_applicator(
        {"company_name": "No Email Coaters"}, PLATFORM_ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_applicator_not_found_on_get(api: ApiClient):
    """PRD §2.8: "the server validates the identifiers' existence
    sequentially, left to right, and rejects the request immediately with the
    not-found error corresponding to the first identifier that does not
    resolve to an existing resource". The not-found catalog includes
    `ERR_APPLICATOR_NOT_FOUND` (HTTP 404).

    Design: Corner/entities/applicator_not_found_on_get
    """
    response = api.get_applicator(
        "00000000-0000-4000-8000-0000000000dd", PLATFORM_ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_APPLICATOR_NOT_FOUND, expected_status=404)
