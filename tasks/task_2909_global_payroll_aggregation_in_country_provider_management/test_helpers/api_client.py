"""HTTP client for the Global Payroll Aggregation API.

One method per endpoint of PRD section 4. Every method returns the raw
`requests.Response` so tests can assert status codes and envelopes themselves.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Endpoint methods for the `/payroll` surface plus the logical clock."""

    # ── Logical clock (PRD 2.5) ───────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ── Country profiles (PRD 3.1) ────────────────────────────────────────────

    def create_country_profile(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/country-profiles", payload, headers)

    def get_country_profile(self, country_profile_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/country-profiles/{country_profile_id}", None, headers
        )

    # ── Providers (PRD 3.1) ───────────────────────────────────────────────────

    def create_provider(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/providers/{provider_id}", None, headers
        )

    # ── Engagements (PRD 3.2, 3.8) ────────────────────────────────────────────

    def create_engagement(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/engagements/{engagement_id}", None, headers
        )

    def list_engagements(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/engagements", params, headers)

    def residency_decision(self, engagement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/residency-decision",
            payload,
            headers,
        )

    def transition_plan(self, engagement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/transition-plan",
            payload,
            headers,
        )

    def transition_decision(self, engagement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/transition-decision",
            payload,
            headers,
        )

    def list_engagement_bank_accounts(
        self, engagement_id: str, headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/engagements/{engagement_id}/bank-accounts",
            params,
            headers,
        )

    # ── Local bank accounts (PRD 3.1) ─────────────────────────────────────────

    def create_bank_account(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/bank-accounts", payload, headers)

    def verify_bank_account(self, bank_account_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/bank-accounts/{bank_account_id}/verify", {}, headers
        )

    # ── Payroll cycles (PRD 3.3, 3.9) ─────────────────────────────────────────

    def create_cycle(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/cycles", payload, headers)

    def get_cycle(self, cycle_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/cycles/{cycle_id}", None, headers)

    def list_cycles(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/cycles", params, headers)

    def lock_inputs(self, cycle_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/lock-inputs", {}, headers
        )

    def release_hold(self, cycle_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/release-hold", {}, headers
        )

    def cancel_cycle(self, cycle_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/cancel", payload, headers
        )

    def close_cycle(self, cycle_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/close", {}, headers
        )

    def filing_sweep(self, cycle_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/filing-sweep", {}, headers
        )

    def list_cycle_audit_evidence(
        self, cycle_id: str, headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/cycles/{cycle_id}/audit-evidence", params, headers
        )

    def list_cycle_input_files(
        self, cycle_id: str, headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/cycles/{cycle_id}/input-files", params, headers
        )

    # ── HR input files (PRD 3.4) ──────────────────────────────────────────────

    def create_input_file(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/input-files", payload, headers)

    def validate_input_file(self, input_file_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/input-files/{input_file_id}/validate", {}, headers
        )

    def resubmit_input_file(self, input_file_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/input-files/{input_file_id}/resubmit",
            payload,
            headers,
        )

    # ── Gross-to-net runs (PRD 3.5) ───────────────────────────────────────────

    def create_gtn_run(self, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-to-net-runs", payload, headers
        )

    def get_gtn_run(self, run_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/gross-to-net-runs/{run_id}", None, headers
        )

    def list_gtn_runs(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/gross-to-net-runs", params, headers)

    def review_gtn_run(self, run_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/gross-to-net-runs/{run_id}/review", payload, headers
        )

    def resubmit_gtn_run(self, run_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/gross-to-net-runs/{run_id}/resubmit",
            payload,
            headers,
        )

    # ── Funding instructions (PRD 3.6) ────────────────────────────────────────

    def create_funding_instruction(self, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/funding-instructions", payload, headers
        )

    def get_funding_instruction(self, funding_instruction_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/funding-instructions/{funding_instruction_id}",
            None,
            headers,
        )

    def list_funding_instructions(
        self, headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/funding-instructions", params, headers
        )

    def approve_funding_instruction(self, funding_instruction_id: str, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/funding-instructions/{funding_instruction_id}/approve",
            {},
            headers,
        )

    def release_funding_instruction(self, funding_instruction_id: str, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/funding-instructions/{funding_instruction_id}/release",
            {},
            headers,
        )

    def recall_funding_instruction(
        self, funding_instruction_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/funding-instructions/{funding_instruction_id}/recall",
            payload,
            headers,
        )

    # ── Statutory filings (PRD 3.7) ───────────────────────────────────────────

    def get_filing(self, filing_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/filings/{filing_id}", None, headers)

    def list_filings(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/filings", params, headers)

    def file_filing(self, filing_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/filings/{filing_id}/file", payload, headers
        )

    def confirm_filing(self, filing_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/filings/{filing_id}/confirm", payload, headers
        )

    def penalty_dispute(self, filing_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/filings/{filing_id}/penalty-dispute",
            payload,
            headers,
        )

    def penalty_dispute_decision(
        self, filing_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/filings/{filing_id}/penalty-dispute-decision",
            payload,
            headers,
        )

    # ── Service-level incidents (PRD 3.8) ─────────────────────────────────────

    def create_incident(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/sla-incidents", payload, headers)

    def get_incident(self, incident_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sla-incidents/{incident_id}", None, headers
        )

    def list_incidents(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/sla-incidents", params, headers)

    def confirm_incident(self, incident_id: str, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sla-incidents/{incident_id}/confirm", {}, headers
        )

    def escalate_incident(
        self, incident_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/sla-incidents/{incident_id}/escalate",
            payload if payload is not None else {},
            headers,
        )

    def remediate_incident(self, incident_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sla-incidents/{incident_id}/remediate",
            payload,
            headers,
        )

    # ── Audit evidence (PRD 3.9) ──────────────────────────────────────────────

    def create_audit_evidence(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/audit-evidence", payload, headers)


api_client = ApiClient()
