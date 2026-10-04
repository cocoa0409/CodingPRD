"""Accounts, catalog access, and the response envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_taxpayer_account,
    create_account,
    create_account_payload,
    create_return,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_taxpayer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestAccountCreation:
    def test_account_creation_applies_system_defaults(self, api):
        """PRD §3.1: "New accounts start in `ACTIVE` status with
        `disclosure_accepted_version` null — the version tag of the
        refund-transfer bank disclosure the taxpayer last accepted, which
        stays null until a disclosure is actually accepted."
        PRD §3.1: "Registration also accepts an optional
        `accuracy_guarantee_enrolled` flag, which defaults to true and later
        gates the claims workflow."

        Design: Corner/entities/account_creation_applies_defaults
        """
        resp = api.create_account(
            create_account_payload(email="ent1@x.com", full_name="Ent One"),
            TEST_USERS["taxpayer_headers"],
        )
        account = validate_success(resp, expected_status=201)
        assert_taxpayer_account(account)
        assert account["status"] == "ACTIVE"
        assert account["accuracy_guarantee_enrolled"] is True
        assert account["disclosure_accepted_version"] is None
        assert account["version"] == 1

    def test_account_creation_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "A new filer begins by registering a `TaxpayerAccount`
        with their `email` (unique across all accounts), `full_name`,
        `filing_status`, `agi_cents`, and `resident_state_code`."

        Design: Corner/entities/account_creation_missing_required_field_returns_invalid_request
        """
        payload = create_account_payload(
            email="ent2@x.com", full_name="Ent Two"
        )
        del payload["agi_cents"]
        resp = api.create_account(payload, TEST_USERS["taxpayer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCatalogAndNotFound:
    def test_get_nonexistent_return_returns_not_found(self, api):
        """PRD §2.8: "Next, path identifiers are resolved left to right —
        account, then return, then the child resource — and the first missing
        segment produces the corresponding 404: `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_RETURN_NOT_FOUND`, `ERR_FORM_NOT_FOUND`, `ERR_PROMPT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, or
        `ERR_STATE_RETURN_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_return_returns_not_found
        """
        resp = api.get_return(NON_EXISTENT_UUID, TEST_USERS["taxpayer_headers"])
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND)


class TestResponseEnvelope:
    def test_success_envelope_shape_on_create(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." PRD §2.2: "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        resp = api.create_account(
            create_account_payload(email="ep1@x.com", full_name="Ep One"),
            TEST_USERS["taxpayer_headers"],
        )
        assert resp.status_code == 201
        body = resp.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." PRD §2.2: "The `meta` object for error
        responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        resp = api.get_return(NON_EXISTENT_UUID, TEST_USERS["taxpayer_headers"])
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_RETURN_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        assert set(meta.keys()) <= {"api_request_id", "api_request_timestamp"}


class TestListPagination:
    def test_list_pagination_defaults_and_fields(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; `offset` defaults to 0." PRD §2.3: "The `meta` object
        of a list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more`, where `has_more` indicates whether
        further records exist beyond the returned window."

        Design: Corner/endpoints/list_pagination_defaults_and_fields
        """
        account = create_account(email="ep2@x.com", full_name="Ep Two")
        headers = make_taxpayer_headers(account["id"])
        first = create_return(account, tax_year=2024)
        second = create_return(account, tax_year=2025)
        resp = api.list_returns(account["id"], headers)
        assert resp.status_code == 200
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        returned_ids = {row["id"] for row in data}
        assert returned_ids == {first.id, second.id}


class TestRbac:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/missing_user_context_header_rejected
        """
        resp = api.create_account(
            create_account_payload(email="rbac2@x.com", full_name="Rbac Two"),
            {},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_claims_adjuster_cannot_seed_catalog(self, api):
        """PRD §2.1: "The `PlatformOperator` exclusively seeds the tier and
        form catalogs, suspends accounts, sets the logical clock, and injects
        authority filing callbacks." PRD §2.1: "A request whose role is not
        permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/claims_adjuster_cannot_seed_catalog_or_file_returns
        """
        from test_helpers import seed_tier_payload

        resp = api.seed_tier(
            seed_tier_payload("FREE", supported_forms=["F1040"]),
            TEST_USERS["claims_adjuster_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_claims_adjuster_cannot_file_returns(self, api):
        """PRD §2.1: "The `Taxpayer` exclusively performs return-graph
        mutations: registering accounts, starting returns, adding and removing
        forms, importing snapshots, selecting tiers, resolving upgrade
        prompts, managing state returns, electing and voiding refund transfer,
        filing, amending, and filing claims." PRD §2.1: "A request whose role
        is not permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/claims_adjuster_cannot_seed_catalog_or_file_returns
        """
        account = create_account(email="rbac3@x.com", full_name="Rbac Three")
        resp = api.create_return(
            account["id"],
            {"tax_year": 2025},
            TEST_USERS["claims_adjuster_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_taxpayer_cannot_adjudicate_claims(self, api):
        """PRD §2.1: "The `ClaimsAdjuster` exclusively performs claim review
        operations (start-review, adjudicate, reopen-review, pay) and
        otherwise has read access to accounts, returns, forms, state returns,
        claims, filing attempts, and the tier and form catalogs."
        PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/taxpayer_cannot_adjudicate_claims
        """
        from test_helpers import setup_filed_claim

        account, ret, _attempt, claim = setup_filed_claim(
            claimed_error_amount_cents=5000, email="rbac1@x.com"
        )
        resp = api.adjudicate_claim(
            claim["id"], 5000, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        # Claim is untouched.
        claims_resp = api.list_claims(ret.id, TEST_USERS["claims_adjuster_headers"])
        claims = get_success_data(claims_resp)
        assert claims[0]["status"] == "FILED"
