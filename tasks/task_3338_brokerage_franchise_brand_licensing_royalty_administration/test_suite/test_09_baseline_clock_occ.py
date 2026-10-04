"""Baseline entities, envelope shape, logical clock, and optimistic concurrency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error, validate_paginated, validate_success, get_success_data,
    is_iso8601_timestamp,
    setup_draft_agreement,
    create_brand_payload,
    ApiErrorId, TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_brand_create_roundtrip_defaults_active(api):
    """PRD §3.1: "A brand is born in `ACTIVE` status; it may later be `RETIRED`,
    after which it can no longer anchor new agreements, though existing
    agreements are unaffected."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
    `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three
    fractional digits"

    Design: Corner/entities/brand_create_success_and_get_roundtrip
    """
    created = validate_success(api.create_brand(
        {"brand_code": "BC", "display_name": "Corner Brand"}, OPS
    ), expected_status=201)
    assert created["brand_code"] == "BC"
    assert created["status"] == "ACTIVE"
    assert created["version"] == 1

    fetched = validate_success(api.get_brand(created["id"], OPS))
    assert fetched["brand_code"] == "BC"
    assert fetched["display_name"] == "Corner Brand"
    assert fetched["status"] == "ACTIVE"
    assert is_iso8601_timestamp(fetched["created_at"])


def test_get_brand_with_random_uuid_returns_not_found(api):
    """PRD §2.8: "The same existence discipline applies to identifiers carried in
    the request body: every referenced `id` — agreement, brand, market,
    brokerage, council, proposal, default case, audit, task, or royalty period —
    must resolve to an existing resource, or the request fails with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/brand_get_not_found_returns_404
    """
    resp = api.get_brand(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_agreement_create_missing_required_field_rejected(api):
    """PRD §3.2: "A franchise agreement is drafted by `FranchisorOps` against a
    specific brokerage, brand, and market, identified by `brokerage_id`,
    `brand_id`, and `market_id`. The commercial heart of the agreement is a set
    of five figures. The `base_royalty_rate_bps` is the royalty rate in basis
    points applied to gross commission income, and must be greater than zero and
    at most 10000."
    PRD §5: "ERR_INVALID_REQUEST | 400"

    Design: Corner/entities/agreement_missing_required_field_returns_invalid_request
    """
    ctx = setup_draft_agreement()
    payload = {
        "brokerage_id": ctx["brokerage"]["id"],
        "brand_id": ctx["brand"]["id"],
        "market_id": ctx["market"]["id"],
        "term_start": "2027-01-01T00:00:00Z",
        "term_end": "2031-12-31T00:00:00Z",
        # base_royalty_rate_bps deliberately omitted
        "annual_royalty_cap_cents": 900_000_000,
        "volume_incentive_threshold_cents": 1_000_000_000,
        "volume_incentive_rate_bps": 300,
        "ad_fund_rate_bps": 200,
    }
    resp = api.create_agreement(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_list_brands_response_carries_pagination_envelope(api):
    """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/response_envelope_pagination_fields_present
    """
    get_success_data(api.create_brand(create_brand_payload(brand_code="PG"), OPS))
    resp = api.list_brands(OPS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in body["meta"], f"missing pagination field {field}"
    assert body["meta"]["total_count"] >= 1


def test_clock_advance_past_term_end_sweeps_agreement_to_expired(api):
    """PRD §2.7: "Advancing the clock triggers a sweep: every `FranchiseAgreement`
    in `ACTIVE` status whose `term_end` is earlier than the new logical date
    transitions to `EXPIRED` as a system side effect, with its `version`
    incremented."
    PRD §2.7: "At startup, before any explicit adjustment, the logical clock
    reads exactly `2026-09-01T00:00:00Z` and never silently falls back to
    wall-clock time."

    Design: Corner/endpoints/clock_set_then_agreement_expires_via_sweep
    """
    ctx = setup_draft_agreement(term_start="2027-01-01T00:00:00Z",
                                term_end="2027-06-30T00:00:00Z")
    plan = get_success_data(
        api.create_conversion_plan(
            ctx["agreement"]["id"],
            {"milestones": [{"name": "m", "target_date": "2027-01-01T00:00:00Z", "sequence": 1}]},
            OPS,
        )
    )
    get_success_data(api.complete_milestone(plan["id"], {"sequence": 1}, OPS))
    get_success_data(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, OPS))
    activated = get_success_data(
        api.activate_agreement(
            ctx["agreement"]["id"],
            {"expected_agreement_version": ctx["agreement"]["version"]},
            OPS,
        )
    )
    assert activated["status"] == "ACTIVE"

    get_success_data(api.set_clock({"to_iso8601": "2027-07-01T00:00:00Z"}, OPS))
    agreement = get_success_data(api.get_agreement(ctx["agreement"]["id"], OPS))
    assert agreement["status"] == "EXPIRED"


def test_clock_regression_rejected(api):
    """PRD §2.7: "the clock moves forward only, and an attempt to set it
    backwards is rejected with `ERR_CLOCK_REGRESSION`."

    Design: Corner/endpoints/clock_regression_rejected
    """
    get_success_data(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, OPS))
    resp = api.set_clock({"to_iso8601": "2026-12-01T00:00:00Z"}, OPS)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


def test_replayed_amend_with_stale_version_rejected(api):
    """PRD §2.6: "If the agreement's current `version` on the server does not
    match the supplied `expected_agreement_version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) — the canonical case being a client that read
    the agreement at some version, another write having since advanced that
    version, and the client's request arriving with a stale expectation."
    PRD §3.2: "Each successful amendment increments the agreement's `version` by
    1."

    Design: Corner/cross_cutting_layers/stale_version_on_amend_returns_412
    """
    ctx = setup_draft_agreement()
    ag_id = ctx["agreement"]["id"]
    observed_version = ctx["agreement"]["version"]

    amended = get_success_data(
        api.amend_agreement(
            ag_id,
            {"expected_agreement_version": observed_version, "ad_fund_rate_bps": 250},
            OPS,
        )
    )
    assert amended["version"] == observed_version + 1

    resp = api.amend_agreement(
        ag_id,
        {"expected_agreement_version": observed_version, "ad_fund_rate_bps": 300},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
