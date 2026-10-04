"""Corner breadth index (entities): VOC regulation creation, required-field
and enum closure, and not-found lookup.
"""
from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_voc_regulation,
    set_clock,
    validate_error,
    validate_success,
    voc_regulation_payload,
)


def test_voc_regulation_creation_happy_path(api: ApiClient):
    """PRD §3.2: "A regulation is created `ACTIVE`."
    PRD §3.2: "no coating may be applied whose VOC exceeds `voc_limit_gpl`
    grams per litre during the half-open window from `effective_from`
    (inclusive) to `effective_to` (exclusive)."

    Design: Corner/entities/voc_regulation_creation_happy_path
    """
    set_clock(api)
    regulation = validate_success(
        api.create_voc_regulation(
            voc_regulation_payload(
                jurisdiction_code="US-CA-SCAQMD",
                application_method="SPRAY_AIRLESS",
                voc_limit_gpl=340,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2027-09-01T00:00:00Z",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        expected_status=201,
    )

    assert_voc_regulation(regulation)
    assert regulation["status"] == "ACTIVE"
    assert regulation["voc_limit_gpl"] == 340
    assert regulation["application_method"] == "SPRAY_AIRLESS"
    assert regulation["jurisdiction_code"] == "US-CA-SCAQMD"


def test_voc_regulation_creation_missing_effective_to_rejected(api: ApiClient):
    """PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/voc_regulation_creation_missing_effective_to_rejected
    """
    payload = voc_regulation_payload(jurisdiction_code="US-CA-SCAQMD")
    del payload["effective_to"]

    response = api.create_voc_regulation(payload, COMPLIANCE_OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_voc_regulation_creation_invalid_application_method_enum(api: ApiClient):
    """PRD §3.2: "for one `application_method` — `SPRAY_AIRLESS`,
    `SPRAY_CONVENTIONAL`, or `BRUSH_ROLLER`".
    PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/voc_regulation_creation_invalid_application_method_enum
    """
    payload = voc_regulation_payload(jurisdiction_code="US-FED", application_method="DIP")
    response = api.create_voc_regulation(payload, COMPLIANCE_OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_voc_regulation_not_found_on_get(api: ApiClient):
    """PRD §2.8: "the server validates the identifiers' existence
    sequentially, left to right, and rejects the request immediately with the
    not-found error corresponding to the first identifier that does not
    resolve to an existing resource". The not-found catalog includes
    `ERR_VOC_REGULATION_NOT_FOUND` (HTTP 404).

    Design: Corner/entities/voc_regulation_not_found_on_get
    """
    response = api.get_voc_regulation(
        "00000000-0000-4000-8000-0000000000ee", COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_VOC_REGULATION_NOT_FOUND, expected_status=404)
