"""Office registry: creation envelope, required fields, enum validation,
state_code uniqueness, entity-scoped 404s, and system-minted ids.

Timestamp equality is asserted by instant (not by string) because the PRD
renders created_at/updated_at with three fractional digits while the logical
clock default is written without them; both denote the same instant.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_state_office,
    create_investigation_payload,
    create_state_office,
    create_state_office_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]


def _same_instant(actual: str, expected: str) -> bool:
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == (
        datetime.fromisoformat(expected.replace("Z", "+00:00"))
    )


def test_office_create_success_defaults_and_envelope():
    """PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources." and "The `api_request_id` is
    a server-generated unique identifier for the request that starts with
    `req_`."
    PRD section 2.4: "Before any test-driving call, the logical clock's value
    is exactly `2026-09-01T00:00:00Z`."
    PRD section 2.5: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/office_create_success_defaults_and_envelope
    """
    payload = create_state_office_payload(
        state_code="CA", population=100, harm_measure_cents=50,
        appropriation_rule="PREAPPROPRIATED",
    )
    resp = api_client.create_state_office(payload, CHAIR)
    body = resp.json()
    assert body.get("response_type") == "object", (
        f"single-resource create must use response_type object, got {body.get('response_type')!r}"
    )
    assert str(body["meta"]["api_request_id"]).startswith("req_")
    assert body["meta"].get("api_request_timestamp")
    data = validate_success(resp, 201)
    assert_state_office(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["state_code"] == "CA"
    assert data["population"] == 100
    assert data["harm_measure_cents"] == 50
    assert data["appropriation_rule"] == "PREAPPROPRIATED"
    assert isinstance(data["version"], int)
    assert _same_instant(data["created_at"], "2026-09-01T00:00:00Z"), (
        f"created_at must equal the logical clock default, got {data['created_at']}"
    )


def test_office_missing_required_population_returns_invalid_request():
    """PRD section 2.8: "required fields must be present, types must be valid,
    enum members must be among the declared values, and extraneous id fields
    are ignored (`ERR_INVALID_REQUEST`)."
    PRD section 3.1: "Registration supplies a two-letter `state_code`, an
    integer `population`, an integer `harm_measure_cents` estimating in-state
    harm in cents, and an `appropriation_rule`."

    Design: Corner/entities/office_missing_required_population_returns_invalid_request
    """
    payload = create_state_office_payload(state_code="CA")
    payload.pop("population")
    resp = api_client.create_state_office(payload, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_office_invalid_enum_value_returns_invalid_request():
    """PRD section 2.8: "required fields must be present, types must be valid,
    enum members must be among the declared values, and extraneous id fields
    are ignored (`ERR_INVALID_REQUEST`)."
    PRD section 3.1: "an `appropriation_rule` of `PREAPPROPRIATED`,
    `CERTIFICATION_REQUIRED`, or `GENERAL_FUND_ONLY` describing how that
    state's legislature controls use of proceeds."

    Design: Corner/entities/office_invalid_enum_value_returns_invalid_request
    """
    payload = create_state_office_payload(
        state_code="CA", population=100, harm_measure_cents=50,
        appropriation_rule="MAYBE",
    )
    resp = api_client.create_state_office(payload, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_office_duplicate_state_code_rejected():
    """PRD section 3.1: "The `state_code` is unique across all registered
    offices: a duplicate registration is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/office_duplicate_state_code_rejected
    """
    create_state_office(state_code="CA")
    payload = create_state_office_payload(
        state_code="CA", population=999, harm_measure_cents=1,
        appropriation_rule="GENERAL_FUND_ONLY",
    )
    resp = api_client.create_state_office(payload, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_unknown_id_returns_entity_not_found():
    """PRD section 2.8: "path identifiers are resolved left to right along the
    URL hierarchy, and an unresolvable segment yields the not-found error of
    its own resource type: `ERR_STATE_OFFICE_NOT_FOUND` under a state-office
    path, `ERR_INVESTIGATION_NOT_FOUND` under an investigation path,
    `ERR_PARTICIPATION_NOT_FOUND` under a participation path, ...
    `ERR_SETTLEMENT_NOT_FOUND` under a settlement path,
    `ERR_ALLOCATION_LINE_NOT_FOUND` under an allocation-line path ... (all
    HTTP 404)."

    Design: Corner/entities/get_unknown_id_returns_entity_not_found
    """
    cases = [
        (api_client.get_state_office, ApiErrorId.ERR_STATE_OFFICE_NOT_FOUND),
        (api_client.get_investigation, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND),
        (api_client.get_participation, ApiErrorId.ERR_PARTICIPATION_NOT_FOUND),
        (api_client.get_settlement, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
        (api_client.get_allocation_line, ApiErrorId.ERR_ALLOCATION_LINE_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, CHAIR)
        validate_error(resp, error_id)


def test_create_office_with_client_supplied_id_input_ignored():
    """PRD section 2.8: "required fields must be present, types must be valid,
    enum members must be among the declared values, and extraneous id fields
    are ignored (`ERR_INVALID_REQUEST`)."
    PRD section 2.5: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/create_office_with_client_supplied_id_input_ignored
    """
    supplied = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    payload = create_state_office_payload(
        state_code="CA", population=100, harm_measure_cents=50,
        appropriation_rule="PREAPPROPRIATED",
    )
    payload["id"] = supplied
    resp = api_client.create_state_office(payload, CHAIR)
    data = validate_success(resp, 201)
    assert data["id"] != supplied, (
        "server must mint its own id and ignore the client-supplied id field"
    )
    assert is_valid_uuid(data["id"])
