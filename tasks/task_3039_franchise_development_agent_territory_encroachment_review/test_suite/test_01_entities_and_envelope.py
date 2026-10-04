"""Entity creation/retrieval, response envelope, not-found and required-field
corners (PRD §2.2, §2.4, §3.1, §3.6)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_territory,
    create_franchisee,
    create_site_application_payload,
    create_territory_payload,
    create_transfer_request_payload,
    get_territory,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_development_agent_headers,
    make_franchisee_headers,
    setup_assigned_territory,
    setup_territory_with_stores,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_territory_create_returns_all_fields_and_unassigned_status(api, franchisor_ops_headers):
    """PRD §3.1: "A new territory is `UNASSIGNED`, its `assigned_agent_id` is
    null, and its `open_store_count` ... starts at zero."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix. `created_at`
    and `updated_at` are ISO 8601 UTC timestamps with three fractional digits"

    Design: Corner/entities/territory_create_returns_all_fields_and_unassigned_status
    """
    payload = create_territory_payload(code="T-CR-1", region="Corner")
    resp = api.create_territory(payload, franchisor_ops_headers)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert_territory(data)
    assert data["status"] == "UNASSIGNED"
    assert data["assigned_agent_id"] is None
    assert data["open_store_count"] == 0
    assert data["version"] == 1
    assert data["code"] == "T-CR-1" and data["region"] == "Corner"
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(resp.json()["meta"].get("api_request_id"), str)


def test_store_get_returns_stored_data_unchanged(api):
    """PRD §3.6: "Directly registered pre-existing stores ... enter `OPEN`
    immediately, flipping their `PROSPECT` franchisee to `ACTIVE`"
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/entities/store_get_returns_stored_data_unchanged
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store = ctx["stores"][0]
    owner = ctx["owners"][0]
    resp = api.get_store(store["id"], make_franchisee_headers(owner["id"]))
    data = validate_success(resp, 200)
    assert data["store_number"] == store["store_number"]
    assert data["status"] == "OPEN"
    assert data["estimated_weekly_sales_cents"] == 1_000_000
    assert data["actual_avg_weekly_sales_cents"] == 1_000_000
    assert data["consecutive_failed_inspections"] == 0
    assert data["source_site_application_id"] is None
    assert data["territory_id"] == ctx["territory"]["id"]
    assert data["franchisee_id"] == owner["id"]
    assert data["geo_lat"] == pytest.approx(store["geo_lat"])
    assert data["geo_lng"] == pytest.approx(store["geo_lng"])


def test_store_get_unknown_id_returns_store_not_found(api, franchisor_ops_headers):
    """PRD §2.8: "Existence failures return the resource-specific 404 error id
    (for example `ERR_TERRITORY_NOT_FOUND`, ..., `ERR_STORE_NOT_FOUND`, ...)."

    Design: Corner/entities/store_get_unknown_id_returns_store_not_found
    """
    resp = api.get_store(NON_EXISTENT_UUID, franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND, 404)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()


def test_site_application_create_missing_open_date_returns_invalid_request(api):
    """PRD §3.2: "a site application carrying `territory_id`,
    `applicant_franchisee_id`, `proposed_address`, `proposed_lat`,
    `proposed_lng`, and `proposed_open_date`"
    PRD §2.8: "(12) request shape — field presence, enum membership, numeric
    ranges"

    Design: Corner/entities/site_application_create_missing_open_date_returns_invalid_request
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    territory = get_territory(ctx["territory"]["id"])
    payload = create_site_application_payload(
        ctx["territory"]["id"], applicant["id"], territory["version"]
    )
    payload.pop("proposed_open_date")
    resp = api.create_site_application(
        payload, make_development_agent_headers(ctx["agent"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    # No application may have been persisted.
    rows, meta = validate_paginated(
        api.list_territory_site_applications(
            ctx["territory"]["id"],
            make_development_agent_headers(ctx["agent"]["id"]),
        )
    )
    assert rows == [], f"Expected 0 site applications, got {len(rows)}"
    assert meta["total_count"] == 0


def test_promotion_create_supplied_status_is_ignored_input(api, franchisor_ops_headers):
    """PRD §3.7: "A national promotion is created with a `name`, a voting
    window from `voting_open` (inclusive) to `voting_close` (exclusive), a
    campaign window from `active_start` (inclusive) to `active_end`
    (exclusive), and a `base_cost_per_store_cents`; it enters `PROPOSED` with
    all tallies at zero."

    Design: Corner/entities/promotion_create_supplied_status_is_ignored_input
    """
    payload = {
        "name": "Sneaky",
        "voting_open": "2026-09-01T00:00:00Z",
        "voting_close": "2026-09-10T00:00:00Z",
        "active_start": "2026-10-01T00:00:00Z",
        "active_end": "2026-11-01T00:00:00Z",
        "base_cost_per_store_cents": 200_000,
        "status": "ACTIVE",
    }
    resp = api.create_promotion(payload, franchisor_ops_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "PROPOSED", (
        f"Client-supplied status must be ignored; got {data['status']}"
    )
    assert data["version"] == 1
    assert data["votes_for"] == 0
    assert data["votes_against"] == 0
    assert data["votes_abstain"] == 0
    assert data["eligible_voter_count"] == 0


def test_transfer_create_unknown_store_id_returns_store_not_found(api):
    """PRD §2.8: "(4) request-body foreign-key existence, validated in the
    endpoint's declared input order" and "Existence failures return the
    resource-specific 404 error id (for example ... `ERR_STORE_NOT_FOUND` ...)."

    Design: Corner/entities/transfer_create_unknown_store_id_returns_store_not_found
    """
    buyer = create_franchisee()
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    any_store_v = ctx["stores"][0]["version"]
    payload = create_transfer_request_payload(
        NON_EXISTENT_UUID, buyer["id"], any_store_v
    )
    resp = api.create_transfer_request(payload, make_franchisee_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND, 404)
