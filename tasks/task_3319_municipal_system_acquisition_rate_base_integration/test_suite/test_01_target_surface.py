"""Target registration, envelope, listing, and role enforcement tests."""
from test_helpers import (
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_target, assert_transition_item,
    create_target_payload,
    create_target, list_transition_items,
    make_headers,
)


def test_create_target_applies_defaults_and_autocreates_transition_items(api):
    """PRD §3.1: "A freshly created target starts in `SCREENING`, with
    `council_approved` false and `filing_estimate_cents` zero".
    PRD §3.1: "Four `TransitionItem` rows spring into existence alongside the
    target, in this fixed order — `BILLING_RECORDS`, `DEPOSITS`,
    `SERVICE_AGREEMENTS`, `METER_READS` — each in `PENDING`."

    Design: Corner/entities/create_target_applies_defaults_and_autocreates_transition_items
    """
    payload = create_target_payload(system_type="COMBINED", customer_count=42,
                                    permitted_valuation_methods=["FMV_INDEPENDENT",
                                                                 "REPLACEMENT_COST"])
    resp = api.create_target(payload, TEST_USERS["analyst_headers"])
    target = validate_success(resp, 201)
    assert_target(target)
    assert target["status"] == "SCREENING"
    assert target["council_approved"] is False
    assert target["filing_estimate_cents"] == 0

    resp = api.list_transition_items(target["id"], TEST_USERS["analyst_headers"])
    items, meta = validate_paginated(resp)
    assert len(items) == 4, f"expected 4 transition items, got {len(items)}"
    assert [i["category"] for i in items] == [
        "BILLING_RECORDS", "DEPOSITS", "SERVICE_AGREEMENTS", "METER_READS"]
    for item in items:
        assert_transition_item(item)
        assert item["status"] == "PENDING"
        assert item["target_id"] == target["id"]


def test_create_target_rejects_nonpositive_customer_count(api):
    """PRD §3.1: "The size of the customer base is captured as `customer_count`,
    which must be greater than zero".

    Design: Corner/entities/create_target_rejects_nonpositive_customer_count
    """
    payload = create_target_payload(customer_count=0)
    resp = api.create_target(payload, TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_target_rejects_empty_permitted_methods(api):
    """PRD §3.1: "`permitted_valuation_methods` is a non-empty list drawn from
    `FMV_INDEPENDENT`, `REPLACEMENT_COST`, and `ORIGINAL_COST_LESS_DEPRECIATION`."

    Design: Corner/entities/create_target_rejects_empty_permitted_methods
    """
    payload = create_target_payload(customer_count=5, permitted_valuation_methods=[])
    resp = api.create_target(payload, TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_target_rejects_invalid_system_type_enum(api):
    """PRD §3.1: "`system_type` is one of `WATER`, `WASTEWATER`, or `COMBINED`."

    Design: Corner/entities/create_target_rejects_invalid_system_type_enum
    """
    payload = create_target_payload(customer_count=5, system_type="GAS")
    resp = api.create_target(payload, TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_target_not_found_returns_404(api):
    """PRD §2.8: "Any missing id, or a child that belongs to a different parent,
    is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_target_not_found_returns_404
    """
    resp = api.get_target(NON_EXISTENT_UUID, TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_targets_paginates_with_envelope_fields(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100. `offset` defaults to 0. Every list response reports `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` envelope."

    Design: Corner/entities/list_targets_paginates_with_envelope_fields
    """
    create_target(system_name="T1", municipality_name="M1", state_code="PA",
                  system_type="WATER", customer_count=5)
    create_target(system_name="T2", municipality_name="M2", state_code="OH",
                  system_type="WASTEWATER", customer_count=6)
    resp = api.list_targets(TEST_USERS["analyst_headers"],
                            params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_error_response_uses_envelope_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/endpoints/error_response_uses_envelope_shape
    """
    resp = api.get_target(NON_EXISTENT_UUID, TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_appraiser_cannot_create_target(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)." and "An `Appraiser` is the
    independent appraiser who submits valuation entries into open valuation
    cases."

    Design: Corner/rbac/appraiser_cannot_create_target
    """
    payload = create_target_payload(customer_count=5)
    resp = api.create_target(payload, TEST_USERS["appraiser_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, carrying a blank header, or
    naming a role outside the declared set is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    payload = create_target_payload(customer_count=5)
    resp = api.create_target(payload, headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
