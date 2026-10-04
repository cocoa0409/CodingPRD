"""Worker intake defaults, request-shape validation, 404 resolution, and the
standard response envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_worker,
    create_worker,
    create_worker_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestWorkerIntake:
    def test_worker_create_defaults_and_computed_fields(self, api, claims_specialist_headers):
        """PRD §3.1: "A new worker begins `LIVING` with `death_date` null and
        `withdrawal_used` false."
        PRD §3.1: "The `fra_months` field holds the full retirement age in months:
        804 months (67 years) for workers born in 1960 or later, and 792 months
        (66 years) otherwise."
        PRD §3.1: "The `eligibility_year` is the worker's benefit eligibility year,
        exactly `birth_year` plus 62, and it drives both wage indexation and the
        bend points of §3.5."
        PRD §2.6: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` timestamp records creation as ISO 8601 UTC with three
        fractional digits."

        Design: Corner/entities/worker_create_defaults_and_computed_fields
        """
        resp = api.create_worker(
            create_worker_payload(full_name="Defaults Worker", birth_year=1964, birth_month=6),
            claims_specialist_headers,
        )
        worker = validate_success(resp, 201)
        assert_worker(worker)
        assert worker["status"] == "LIVING"
        assert worker["death_date"] is None
        assert worker["noncovered_pension_monthly_cents"] == 0
        assert worker["noncovered_pension_start_month"] is None
        assert worker["withdrawal_used"] is False
        assert worker["fra_months"] == 804, "born 1964 (>= 1960): FRA is 804 months"
        assert worker["eligibility_year"] == 2026, "birth_year 1964 + 62"
        assert worker["version"] == 1
        assert is_valid_uuid(worker["id"]) and "-" in worker["id"]
        assert "." in worker["created_at"] and len(worker["created_at"].split(".")[-1].rstrip("Z")) == 3

        fetched = validate_success(api.get_worker(worker["id"], claims_specialist_headers))
        assert fetched == worker

    def test_worker_create_missing_required_field_returns_400(self, api, claims_specialist_headers):
        """PRD §3.1: "Intake records the worker's `full_name`, `birth_year` (a
        four-digit year between 1900 and 2100), and `birth_month` (1 through 12),
        and optionally the two pension fields: `noncovered_pension_monthly_cents`,
        the monthly pension from employment not covered by Social Security, which
        defaults to 0 and may never be negative, and
        `noncovered_pension_start_month`, the first month (YYYY-MM) that pension
        is received, which defaults to null when there is no such pension."
        PRD §2.9: "**Request-body well-formedness**: required fields are present,
        types and enums parse, and scalar ranges hold — `amount_cents` strictly
        positive on wage reports and overpayment cases, `claimed_earnings_cents`
        never negative, `relationship_id` present exactly when the claim type is
        auxiliary, `divorce_date` present on divorced-spouse relationships,
        `recovery_mode` one of `FULL`, `PARTIAL`, `PROPORTIONAL` with
        `monthly_rate_cents` required exactly when `PARTIAL` is elected,
        `outcome` drawn from `GRANTED` or `DENIED` for waivers and from
        `APPROVED` or `DENIED` for payee decisions — otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/worker_create_missing_required_field_returns_400
        """
        resp = api.create_worker(
            {"full_name": "No Birthyear", "birth_month": 6}, claims_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_worker_get_nonexistent_returns_404(self, api, claims_specialist_headers):
        """PRD §2.11: "a missing worker yields `ERR_WORKER_NOT_FOUND` (404)".

        Design: Corner/entities/worker_get_nonexistent_returns_404
        """
        resp = api.get_worker("11111111-2222-4333-8444-555555555555", claims_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FOUND, 404)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api, claims_specialist_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        create_resp = api.create_worker(
            create_worker_payload(full_name="Env Check", birth_year=1964, birth_month=6),
            claims_specialist_headers,
        )
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])

        err_resp = api.get_worker("99999999-8888-4777-8666-555555555555", claims_specialist_headers)
        err_body = err_resp.json()
        assert err_resp.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_WORKER_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()
        assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
