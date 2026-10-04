"""Envelope shape, auth gating, and nested-existence errors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_approved_baseline,
    create_baseline_payload,
    create_contract,
    eng_headers,
    make_actor_ids,
    own_headers,
    reset_clock,
    scoped_contract,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_bundle_payload


def test_envelope_error_shape_on_every_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/envelope_error_shape_on_every_failure
    """
    reset_clock()
    eng_id, _owner_id = make_actor_ids()
    response = api.get_contract(NON_EXISTENT_UUID, eng_headers(eng_id))
    data = validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")
    assert data.get("message")


def test_missing_auth_headers_rejected_before_any_business_check(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed
    value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected_before_any_business_check
    """
    reset_clock()
    response = api.create_contract(
        {
            "facility_name": "No Auth",
            "contract_term_years": 10,
            "guarantee_start_date": "2026-10-01T00:00:00Z",
            "mv_protocol": "IPMVP_C",
            "guaranteed_annual_savings_cents": 250000,
            "contract_value_cents": 2000000,
        },
        {},
    )
    validate_error(
        response,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        400,
    )


def test_nested_get_with_wrong_parent_returns_not_found(api):
    """PRD §2.6: "A segment that does not exist, or that exists but is not
    nested under the previously validated parent, yields the segment's own
    not-found error"

    Design: Corner/entities/nested_get_with_wrong_parent_returns_not_found
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = create_contract(eng_id)
    bundle_resp = api.create_bundle(
        contract["id"], create_bundle_payload(), eng_headers(eng_id)
    )
    bundle = validate_success(bundle_resp, 201)
    contract2 = create_contract(
        eng_id,
        facility_name="Second School",
        guaranteed_annual_savings_cents=100000,
        contract_value_cents=1000000,
    )
    response = api.get_bundle(contract2["id"], bundle["id"], own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_BUNDLE_NOT_FOUND.value, 404)


def test_baseline_submit_from_approved_returns_invalid_state(api):
    """PRD §3.1: "a baseline not in `DRAFT` is rejected with
    `ERR_BASELINE_NOT_DRAFT`"

    Design: Corner/state_machines/baseline_submit_from_approved_returns_invalid_state
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = create_contract(eng_id)
    baseline = add_approved_baseline(contract["id"], eng_id, owner_id)
    assert baseline["status"] == "APPROVED"
    assert baseline["adjusted_annual_cost_cents"] == 1200000
    response = api.submit_baseline(
        contract["id"], baseline["id"], eng_headers(eng_id)
    )
    validate_error(response, ApiErrorId.ERR_BASELINE_NOT_DRAFT.value, 409)
    reread = validate_success(
        api.get_baseline(contract["id"], baseline["id"], eng_headers(eng_id))
    )
    assert reread["status"] == "APPROVED"
    assert reread["adjusted_annual_cost_cents"] == 1200000
