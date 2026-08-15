"""Response envelope shape, pagination defaults/bounds, and 404 variants."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_equity_snapshot_payload, create_candidate_payload,
    is_iso8601_timestamp,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
VP = TEST_USERS["vp_headers"]
SCR = TEST_USERS["screener_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def test_envelope_success_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/envelope_success_shape
    """
    resp = api.create_candidate(create_candidate_payload(full_name="Cand ENV"), REC)
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"] is not None
    assert str(body["meta"]["api_request_id"]).startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["status"] == "PROSPECT"
    assert body["data"]["id"]


def test_envelope_error_shape(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error." and "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/envelope_error_shape
    """
    resp = api.get_offer(NON_EXISTENT_UUID, REC)
    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_OFFER_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_offer_not_found_returns_404(api):
    """PRD §2.10: "Path identifiers are validated left to right, and the first
    segment that does not resolve rejects the request: ... `ERR_OFFER_NOT_FOUND`
    ... each HTTP 404."

    Design: Corner/entities/offer_not_found_returns_404
    """
    resp = api.get_offer("11111111-2222-3333-4444-555555555555", REC)
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_FOUND)


def test_not_found_variants_across_entities(api):
    """PRD §2.10: "Path identifiers are validated left to right, and the first
    segment that does not resolve rejects the request:
    `ERR_REQUISITION_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
    `ERR_APPROVAL_STEP_NOT_FOUND`, `ERR_NEGOTIATION_ROUND_NOT_FOUND`,
    `ERR_PERK_NOT_FOUND`, `ERR_CLEARANCE_CHECK_NOT_FOUND`,
    `ERR_DELEGATION_GRANT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or
    `ERR_SNAPSHOT_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/not_found_variants_across_entities
    """
    missing = "11111111-2222-3333-4444-555555555555"
    checks = [
        (api.get_requisition(missing, REC), ApiErrorId.ERR_REQUISITION_NOT_FOUND),
        (api.get_candidate(missing, REC), ApiErrorId.ERR_CANDIDATE_NOT_FOUND),
        (api.get_equity_snapshot(missing, CA), ApiErrorId.ERR_SNAPSHOT_NOT_FOUND),
        (api.decide_approval_step(missing, {"decision": "APPROVED"}, HM), ApiErrorId.ERR_APPROVAL_STEP_NOT_FOUND),
        (api.decide_negotiation_round(missing, {"outcome": "ACCEPTED"}, VP), ApiErrorId.ERR_NEGOTIATION_ROUND_NOT_FOUND),
        (api.get_clawback_quote(missing, ADMIN, months_worked=1), ApiErrorId.ERR_PERK_NOT_FOUND),
        (api.transition_clearance_check(missing, {"to": "CLEARED"}, SCR), ApiErrorId.ERR_CLEARANCE_CHECK_NOT_FOUND),
        (api.revoke_delegation_grant(missing, ADMIN), ApiErrorId.ERR_DELEGATION_GRANT_NOT_FOUND),
        (api.deactivate_approval_policy(missing, ADMIN), ApiErrorId.ERR_POLICY_NOT_FOUND),
    ]
    for resp, err_id in checks:
        validate_error(resp, err_id)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value that is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.10 tier 1: "Authentication. Headers present and role declared, else
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    # No X-User-Role / X-User-ID headers at all: auth (tier 1) precedes existence (tier 5),
    # so even a nonexistent offer id surfaces 401, not 404.
    resp = api.get_offer("11111111-2222-3333-4444-555555555555", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_list_pagination_defaults_and_filtering(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100,
    and a value outside that range is rejected as a malformed request with
    `ERR_INVALID_REQUEST`." PRD §3.2: "The collection is listable with optional
    `role_level` and `geo_tier` filters."

    Design: Corner/entities/list_pagination_defaults_and_filtering
    """
    for i in range(12):
        resp = api.create_equity_snapshot(
            create_equity_snapshot_payload(role_level="L3", geo_tier="T3", base_cents=10000000 + i * 100000),
            CA,
        )
        assert resp.status_code == 201, f"Setup failed creating snapshot {i}: {resp.text}"

    # Default page: limit 10, total 12, has_more true
    page1, meta1 = validate_paginated(api.list_equity_snapshots(CA))
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    # offset=10 returns the remaining 2 with has_more false
    page2, meta2 = validate_paginated(api.list_equity_snapshots(CA, params={"offset": 10}))
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    # role_level filter narrows the set (all 12 are L3)
    page3, meta3 = validate_paginated(api.list_equity_snapshots(CA, params={"role_level": "L3"}))
    assert meta3["total_count"] == 12
    assert all(row["role_level"] == "L3" for row in page3)

    # limit outside [1, 100] rejected
    validate_error(api.list_equity_snapshots(CA, params={"limit": 0}), ApiErrorId.ERR_INVALID_REQUEST)
    validate_error(api.list_equity_snapshots(CA, params={"limit": 101}), ApiErrorId.ERR_INVALID_REQUEST)
