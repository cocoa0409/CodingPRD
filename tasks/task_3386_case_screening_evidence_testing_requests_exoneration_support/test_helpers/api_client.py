"""API client: one method per endpoint defined in the PRD (section 4).

All resources live at the top level; paths are absolute from the domain root
with no prefix. Every method returns the raw requests.Response so tests can
assert on status code and envelope. Query filters and pagination go through
``params``; request bodies through ``payload``.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock (PRD section 2.4) ────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Ops checkpoint (PRD section 3.7) ───────────────────────────────────

    def run_contact_overdue_sweep(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", "/ops/contact-overdue-sweep", payload or {}, headers)

    # ── Jurisdictions ──────────────────────────────────────────────────────

    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", None, headers)

    def list_jurisdiction_policy_initiatives(
        self, jurisdiction_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/policy-initiatives", params, headers
        )

    # ── Clients ────────────────────────────────────────────────────────────

    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clients/{client_id}", None, headers)

    # ── Intake requests ────────────────────────────────────────────────────

    def create_intake_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/intake-requests", payload, headers)

    def list_intake_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/intake-requests", params, headers)

    def get_intake_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/intake-requests/{request_id}", None, headers)

    def advance_intake_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/intake-requests/{request_id}/advance", payload, headers)

    def submit_intake_supplement(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/intake-requests/{request_id}/submit-supplement", payload, headers
        )

    def decide_intake_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/intake-requests/{request_id}/decide", payload, headers)

    def activate_waitlist_next(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/intake-requests/activate-waitlist-next", {}, headers)

    def list_intake_request_cases(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/intake-requests/{request_id}/cases", params, headers)

    # ── Cases ──────────────────────────────────────────────────────────────

    def get_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}", None, headers)

    def update_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PUT", f"/cases/{case_id}", payload, headers)

    def advance_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cases/{case_id}/advance", payload, headers)

    def log_case_contact(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cases/{case_id}/log-contact", payload, headers)

    def list_case_evidence_items(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/evidence-items", params, headers)

    def list_case_records_requests(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/records-requests", params, headers)

    def list_case_testing_authorizations(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/testing-authorizations", params, headers)

    def list_case_legal_petitions(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/legal-petitions", params, headers)

    def list_case_compensation_claims(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/compensation-claims", params, headers)

    def list_case_reentry_referrals(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}/reentry-referrals", params, headers)

    # ── Evidence items ─────────────────────────────────────────────────────

    def create_evidence_item(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/evidence-items", payload, headers)

    def get_evidence_item(self, item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/evidence-items/{item_id}", None, headers)

    def advance_evidence_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/evidence-items/{item_id}/advance", payload, headers)

    def list_evidence_item_testing_authorizations(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/evidence-items/{item_id}/testing-authorizations", params, headers
        )

    def list_evidence_item_lab_analyses(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/evidence-items/{item_id}/lab-analyses", params, headers)

    # ── Records requests ───────────────────────────────────────────────────

    def create_records_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/records-requests", payload, headers)

    def advance_records_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/records-requests/{request_id}/advance", payload, headers)

    # ── Testing authorizations (agreement + motion) ────────────────────────

    def create_testing_authorization(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/testing-authorizations", payload, headers)

    def get_testing_authorization(
        self, authorization_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/testing-authorizations/{authorization_id}", None, headers)

    def advance_testing_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-authorizations/{authorization_id}/advance", payload, headers
        )

    def amend_testing_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/testing-authorizations/{authorization_id}/amendments", payload, headers
        )

    def list_testing_authorization_lab_analyses(
        self, authorization_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/testing-authorizations/{authorization_id}/lab-analyses", params, headers
        )

    # ── Lab analyses ───────────────────────────────────────────────────────

    def create_lab_analysis(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/lab-analyses", payload, headers)

    def advance_lab_analysis(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lab-analyses/{analysis_id}/advance", payload, headers)

    # ── Legal petitions ────────────────────────────────────────────────────

    def create_legal_petition(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/legal-petitions", payload, headers)

    def advance_legal_petition(
        self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/legal-petitions/{petition_id}/advance", payload, headers)

    # ── Compensation claims ────────────────────────────────────────────────

    def create_compensation_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/compensation-claims", payload, headers)

    def advance_compensation_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/compensation-claims/{claim_id}/advance", payload, headers)

    # ── Reentry providers & referrals ──────────────────────────────────────

    def create_reentry_provider(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reentry-providers", payload, headers)

    def get_reentry_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reentry-providers/{provider_id}", None, headers)

    def list_reentry_provider_referrals(
        self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/reentry-providers/{provider_id}/reentry-referrals", params, headers
        )

    def create_reentry_referral(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reentry-referrals", payload, headers)

    def advance_reentry_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/reentry-referrals/{referral_id}/advance", payload, headers)

    # ── Policy initiatives ─────────────────────────────────────────────────

    def create_policy_initiative(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/policy-initiatives", payload, headers)

    def advance_policy_initiative(
        self, initiative_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/policy-initiatives/{initiative_id}/advance", payload, headers
        )


api_client = ApiClient()
