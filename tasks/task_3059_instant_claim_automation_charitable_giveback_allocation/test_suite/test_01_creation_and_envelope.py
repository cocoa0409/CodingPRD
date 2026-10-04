"""Creation, defaults, computed fields, and error-envelope shape tests."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_policyholder,
    assert_rate_filing,
    make_policyholder_headers,
    set_clock,
    create_policyholder,
    create_quote,
    get_success_data,
    validate_error,
    validate_success,
    api_client,
    create_rate_filing_payload,
    create_policyholder_payload,
    create_quote_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


class TestRateFilingCreation:
    def test_rate_filing_create_returns_declared_fields(self, api):
        """PRD §3.1: "A new filing starts in SUBMITTED."
        PRD §2.4: "Primary resources — Rate Filings, Fee Configs, Reinsurance Treaties, Causes, Cohorts, Policyholders, Quotes, Policy Applications, Policies, Claims, and Appeals — each carry id (a server-minted UUID with no type prefix), created_at and updated_at (ISO 8601 UTC timestamps with three fractional digits), and version (an integer that increments by one on every mutation of the resource)."
        PRD §3.1: "Approval by an UnderwritingAdmin moves a filing from SUBMITTED to APPROVED" — "the newly approved filing's approved_at is stamped with the current logical clock (approved_at remains null on filings that were never approved)."

        Design: Corner/entities/rate_filing_create_returns_declared_fields_and_submitted_status
        """
        set_clock()
        data = validate_success(
            api.create_rate_filing(
                create_rate_filing_payload(
                    state_code="TX",
                    max_flat_fee_pct=0.25,
                    max_flat_fee_cap_cents=25000,
                    filing_mode="ABSOLUTE_CENTS",
                ),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        assert_rate_filing(data)
        assert data["status"] == "SUBMITTED"
        assert data["version"] == 1
        assert data["approved_at"] is None
        assert data["state_code"] == "TX"
        assert data["max_flat_fee_pct"] == 0.25
        assert data["max_flat_fee_cap_cents"] == 25000
        assert data["filing_mode"] == "ABSOLUTE_CENTS"

    def test_rate_filing_create_ignores_client_supplied_system_fields(self, api):
        """PRD §2.4: "each carry id (a server-minted UUID with no type prefix), created_at and updated_at (ISO 8601 UTC timestamps with three fractional digits), and version (an integer that increments by one on every mutation of the resource)".
        PRD §3.1: "A new filing starts in SUBMITTED."

        Design: Corner/entities/system_generated_fields_ignore_client_input
        """
        set_clock()
        payload = create_rate_filing_payload(state_code="TX")
        payload.update({"id": "client-supplied-id", "version": 99, "status": "APPROVED"})
        data = validate_success(api.create_rate_filing(payload, UNDERWRITER), expected_status=201)
        assert data["id"] != "client-supplied-id"
        assert data["version"] == 1
        assert data["status"] == "SUBMITTED"


class TestPolicyholderCreation:
    def test_policyholder_create_applies_defaults(self, api):
        """PRD §3.4: "The new policyholder is ACTIVE with a fraud_strike_count of zero."

        Design: Corner/entities/policyholder_create_applies_defaults
        """
        set_clock()
        data = validate_success(
            api.create_policyholder(
                create_policyholder_payload(email="d@x.com", full_name="D Ef", state_code="TX"),
                ANONYMOUS,
            ),
            expected_status=201,
        )
        assert_policyholder(data)
        assert data["status"] == "ACTIVE"
        assert data["fraud_strike_count"] == 0


class TestQuoteCreation:
    def test_quote_create_computes_expires_at_30_days_out(self, api):
        """PRD §3.4: "The quote copies the policyholder's state_code at creation, is owned by the policyholder via policyholder_id, starts OPEN, and carries an expires_at set exactly 30 days after creation."

        Design: Corner/entities/quote_create_computes_expires_at_30_days_out
        """
        set_clock("2026-09-01T00:00:00Z")
        ph = create_policyholder(state_code="TX", email="q@x.com")
        data = validate_success(
            api.create_quote(
                create_quote_payload(coverage_amount_cents=100000, premium_cents=50000),
                make_policyholder_headers(ph["id"]),
            ),
            expected_status=201,
        )
        assert data["expires_at"] == "2026-10-01T00:00:00.000Z"
        assert data["status"] == "OPEN"
        assert data["state_code"] == "TX"

    def test_quote_create_at_startup_default_clock(self, api):
        """PRD §2.7: "The system runs on a logical clock, never wall-clock time. Before any clock-setting call, the clock reads exactly 2026-09-01T00:00:00Z."
        PRD §3.4: "The quote copies the policyholder's state_code at creation, is owned by the policyholder via policyholder_id, starts OPEN, and carries an expires_at set exactly 30 days after creation."

        Design: Corner/cross_cutting_layers/scheduled_quote_expiry_uses_logical_clock
        """
        # No clock-setting call: the startup default 2026-09-01T00:00:00Z applies.
        ph = create_policyholder(state_code="TX", email="p@x.com")
        data = validate_success(
            api.create_quote(
                create_quote_payload(coverage_amount_cents=100000, premium_cents=50000),
                make_policyholder_headers(ph["id"]),
            ),
            expected_status=201,
        )
        assert data["expires_at"] == "2026-10-01T00:00:00.000Z"
        assert data["status"] == "OPEN"


class TestNotFoundAndErrorEnvelope:
    def test_get_unknown_policy_returns_not_found(self, api):
        """PRD §2.8: "Where a path does contain multiple identifiers (for example, listing the applications of a policyholder, or the ledger of a claim), the server validates each path identifier's existence left to right and rejects with ERR_NOT_FOUND (HTTP 404) at the first identifier that does not correspond to an existing resource, before evaluating any business rule."

        Design: Corner/entities/get_unknown_policy_returns_not_found
        """
        resp = api.get_policy(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_error_envelope_shape_on_every_failure(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format" and "The meta object for error responses contains only api_request_id and api_request_timestamp" while "The message provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_every_failure
        """
        resp = api.get_policy(NON_EXISTENT_UUID, ADMIN)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()

    def test_quote_create_with_unknown_policyholder_id_returns_not_found(self, api):
        """PRD §2.8: "Authentication, authorization, and existence checks, in that order, precede every business validation on every endpoint".
        PRD §2.1: "When X-User-Role is Policyholder, X-User-ID is the id of the acting Policyholder entity" and "a mismatch yields ERR_FORBIDDEN".
        An X-User-ID that matches no Policyholder entity fails the role's identity binding, which is an authorization failure (ERR_FORBIDDEN) rather than a resource-existence failure.

        Design: Corner/entities/fk_integrity_quote_references_existing_policyholder
        """
        resp = api.create_quote(
            create_quote_payload(coverage_amount_cents=100000, premium_cents=50000),
            make_policyholder_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
