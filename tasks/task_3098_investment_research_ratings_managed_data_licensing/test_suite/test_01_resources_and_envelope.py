"""Resource creation, retrieval, envelope shape, pagination, and listing tests.

Every test translates exactly one non-stub design-index instance; each
docstring ends with its Design tag.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_fund,
    assert_holding,
    assert_licensee,
    create_category,
    create_fund,
    create_fund_company,
    create_fund_company_payload,
    create_fund_payload,
    create_licensee,
    get_success_data,
    ingest_holdings,
    is_valid_uuid,
    make_analyst_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["research_ops_headers"]
LIC = TEST_USERS["license_admin_headers"]


class TestResourceCreationAndDefaults:
    def test_fund_company_create_defaults_and_round_trip(self, api):
        """PRD §3.1: "The new company's `company_status` begins as `ACTIVE` and
        its `open_dispute_count` begins at 0."
        PRD §3.1: "an optional `commercial_relationship` — one of `NONE`,
        `LICENSED_CLIENT`, or `INDEX_LICENSEE` — that defaults to `NONE` when
        omitted."
        PRD §3.7: "A fund company's `quality_score_bp`, computed on every read
        of the company, starts from 10000"
        PRD §2.5: "`id` (string): a unique, server-minted UUID with no type
        prefix."
        PRD §2.5: "`version` (integer): starting at its initial value on
        creation and incremented by exactly 1 on every mutation of the
        resource"

        Design: Corner/entities/fund_company_create_defaults_and_round_trip
        """
        resp = api.create_fund_company({"legal_name": "Roundtrip Row"}, OPS)
        data = validate_success(resp, expected_status=201)
        assert data["company_status"] == "ACTIVE"
        assert data["commercial_relationship"] == "NONE"
        assert data["open_dispute_count"] == 0
        assert data["quality_score_bp"] == 10000
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_licensee_create_defaults(self, api):
        """PRD §3.8: "A `LicenseAdmin` registers a licensee with its
        `licensee_name`; the licensee's `licensee_status` begins as `ACTIVE`
        with `arrears_cents` at 0."

        Design: Corner/entities/licensee_create_defaults
        """
        resp = api.create_licensee({"licensee_name": "Defaulty"}, LIC)
        data = validate_success(resp, expected_status=201)
        assert_licensee(data)
        assert data["licensee_status"] == "ACTIVE"
        assert data["arrears_cents"] == 0
        assert data["version"] == 1


class TestRetrievalAndListing:
    def test_fund_get_returns_stored_fields(self, api):
        """PRD §3.1: "A new fund's `fund_status` is `ACTIVE`; its `category_id`
        remains null until the first category assignment, and its
        `category_assignment_revision` begins at 0."
        PRD §3.1: "optionally the trailing five-year return as
        `trailing_return_5y_bp` (null when the fund is younger than five
        years)"

        Design: Corner/entities/fund_get_returns_stored_fields
        """
        company = create_fund_company(legal_name="Retrieval Co")
        # Create without trailing_return_5y_bp to exercise the null path
        payload = create_fund_payload(
            company["id"],
            ticker="RTF2",
            inception_date="2024-02-01",
            trailing_return_3y_bp=4500,
            risk_score_bp=1200,
        )
        payload.pop("trailing_return_5y_bp", None)
        fund2 = get_success_data(api.create_fund(payload, OPS))

        got = validate_success(api.get_fund(fund2["id"], make_analyst_headers("analyst-reader")))
        assert_fund(got)
        assert got["ticker"] == "RTF2"
        assert got["trailing_return_3y_bp"] == 4500
        assert got["risk_score_bp"] == 1200
        assert got["trailing_return_5y_bp"] is None
        assert got["fund_status"] == "ACTIVE"
        assert got["category_id"] is None
        assert got["category_assignment_revision"] == 0

    def test_funds_list_pagination_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries exactly
        the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/funds_list_pagination_total_count_and_has_more
        """
        company = create_fund_company(legal_name="Pagination Co")
        for ticker in ("PG1", "PG2", "PG3"):
            create_fund(company["id"], ticker=ticker)

        page1, meta1 = validate_paginated(
            api.list_funds(OPS, params={"fund_company_id": company["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_funds(OPS, params={"fund_company_id": company["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Default limit is 10 when omitted
        _, meta_default = validate_paginated(
            api.list_funds(OPS, params={"fund_company_id": company["id"]})
        )
        assert meta_default["limit"] == 10

    def test_fund_company_get_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve"

        Design: Corner/entities/fund_company_get_unknown_id_returns_not_found
        """
        resp = api.get_fund_company(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)

    def test_fund_create_missing_required_ticker_rejected(self, api):
        """PRD §2.4: "A malformed request body — a missing required field, an
        invalid enum value, or a value of the wrong type — is rejected with
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "Funds are registered against their issuer by supplying
        `fund_company_id`, a globally unique `ticker`, an `inception_date`,
        the trailing three-year total return in basis points as
        `trailing_return_3y_bp`, optionally the trailing five-year return as
        `trailing_return_5y_bp` (null when the fund is younger than five
        years), and a downside-deviation `risk_score_bp`"

        Design: Corner/entities/fund_create_missing_required_ticker_rejected
        """
        company = create_fund_company(legal_name="Required Co")
        payload = create_fund_payload(company["id"])
        payload.pop("ticker")
        resp = api.create_fund(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

        # Omitting the optional trailing_return_5y_bp succeeds with null
        ok_payload = create_fund_payload(company["id"], ticker="OPTOK")
        ok_payload.pop("trailing_return_5y_bp", None)
        ok_resp = api.create_fund(ok_payload, OPS)
        ok_fund = validate_success(ok_resp, expected_status=201)
        assert ok_fund["trailing_return_5y_bp"] is None

    def test_holding_immutable_no_update_endpoint(self, api):
        """PRD §2.5: "Three subordinate resource kinds — holdings rows,
        committee votes, and client notices — are immutable ledger-style
        records. They carry only `id` and `created_at`; both `updated_at` and
        `version` are absent from them."

        Design: Corner/entities/holding_immutable_no_update_endpoint
        """
        company = create_fund_company(legal_name="Immutable Co")
        fund = create_fund(company["id"], ticker="IMF")
        ingest_holdings(
            fund["id"],
            holdings=[
                {
                    "security_ticker": "IM1",
                    "asset_class": "BOND",
                    "sector": "FINANCE",
                    "weight_bp": 10000,
                }
            ],
        )
        data, _meta = validate_paginated(api.list_holdings(fund["id"], OPS))
        assert len(data) == 1
        for row in data:
            assert_holding(row)


class TestEnvelopeShape:
    def test_response_envelope_error_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        resp = api.get_fund_company(NON_EXISTENT_UUID, OPS)
        body = resp.json()
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0
