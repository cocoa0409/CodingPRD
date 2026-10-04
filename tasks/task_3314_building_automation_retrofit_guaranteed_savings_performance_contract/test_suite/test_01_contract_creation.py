"""Contract creation and envelope basics (corner design, entities section)."""
from test_helpers import (
    ApiErrorId,
    create_contract_payload,
    make_actor_ids,
    make_esco_engineer_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


def test_contract_create_returns_defaults_and_initial_state(api):
    """PRD §3.1: "The new contract begins life in `AUDIT` status with
    `version` 1."
    PRD §2.9: "The contract keeps two ledger fields that the whole lifecycle
    feeds: `cumulative_verified_savings_cents`, the running sum of verified
    savings across all reconciled guarantee years, and
    `guarantee_shortfall_reserve_cents`, the vendor's cumulative liability —
    shortfall payments owed minus shortfall payments settled, floored at zero."

    Design: Corner/entities/contract_create_returns_defaults_and_initial_state
    """
    set_clock("2026-09-01T00:00:00Z")
    eng_id, _owner_id = make_actor_ids()
    response = api.create_contract(
        create_contract_payload(
            facility_name="Plainview High", contract_term_years=12
        ),
        make_esco_engineer_headers(eng_id),
    )
    data = validate_success(response, 201)
    assert data["status"] == "AUDIT"
    assert data["version"] == 1
    assert data["guarantee_shortfall_reserve_cents"] == 0
    assert data["cumulative_verified_savings_cents"] == 0
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")


def test_contract_create_missing_required_field_rejected(api):
    """PRD §2.6: "A malformed body, an invalid enum value, or a negative or
    zero value that violates a field constraint is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/contract_create_missing_required_field_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    eng_id, _owner_id = make_actor_ids()
    payload = create_contract_payload(facility_name="No Protocol")
    del payload["mv_protocol"]
    response = api.create_contract(payload, make_esco_engineer_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_contract_create_invalid_mv_protocol_enum_rejected(api):
    """PRD §3.1: "the measurement-and-verification `mv_protocol` (one of
    `IPMVP_A`, `IPMVP_B`, `IPMVP_C`, or `IPMVP_D`)"
    PRD §2.6: "A malformed body, an invalid enum value, or a negative or zero
    value that violates a field constraint is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/contract_create_invalid_mv_protocol_enum_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    eng_id, _owner_id = make_actor_ids()
    payload = create_contract_payload(
        facility_name="Bad Enum", mv_protocol="IPMVP_Z"
    )
    response = api.create_contract(payload, make_esco_engineer_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
