"""Typed API client: exactly one method per endpoint of the EPLI API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Timestamps are compared in a handful of tests; the API declares three
    fractional digits, so this collapses any sub-second width difference before
    a comparison rather than asserting on raw text.
    """
    if value is None:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/jurisdictions/{jurisdiction_id}", None, headers
        )

    def list_jurisdictions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/jurisdictions", params, headers)

    # ------------------------------------------------------------------
    # Rate plans
    # ------------------------------------------------------------------
    def create_rate_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/rate-plans", payload, headers)

    def activate_rate_plan(self, rate_plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/rate-plans/{rate_plan_id}/activate", {}, headers
        )

    def get_rate_plan(self, rate_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/rate-plans/{rate_plan_id}", None, headers)

    def list_rate_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/rate-plans", params, headers)

    # ------------------------------------------------------------------
    # Defense panel firms
    # ------------------------------------------------------------------
    def create_panel_firm(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/defense-panel-firms", payload, headers)

    def suspend_panel_firm(self, panel_firm_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-panel-firms/{panel_firm_id}/suspend", {}, headers
        )

    def get_panel_firm(self, panel_firm_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/defense-panel-firms/{panel_firm_id}", None, headers
        )

    def list_panel_firms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/defense-panel-firms", params, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def patch_applicant(self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{API_PREFIX}/applicants/{applicant_id}", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/applicants/{applicant_id}", None, headers)

    # ------------------------------------------------------------------
    # Risk-management services
    # ------------------------------------------------------------------
    def create_risk_service(
        self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/risk-management-services",
            payload,
            headers,
        )

    def complete_risk_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/risk-management-services/{service_id}/complete", {}, headers
        )

    def revoke_risk_service(self, service_id: str, revocation_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/risk-management-services/{service_id}/revoke",
            {"revocation_reason": revocation_reason},
            headers,
        )

    def revoke_risk_service_raw(
        self, service_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/risk-management-services/{service_id}/revoke", payload, headers
        )

    def get_risk_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/risk-management-services/{service_id}", None, headers
        )

    def list_risk_services(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/risk-management-services", params, headers)

    # ------------------------------------------------------------------
    # Exposure assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/exposure-assessments", payload, headers)

    def price_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/exposure-assessments/{assessment_id}/price", {}, headers
        )

    def approve_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/exposure-assessments/{assessment_id}/approve", {}, headers
        )

    def reject_assessment(self, assessment_id: str, rejection_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/exposure-assessments/{assessment_id}/reject",
            {"rejection_reason": rejection_reason},
            headers,
        )

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/exposure-assessments/{assessment_id}", None, headers
        )

    def list_assessments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/exposure-assessments", params, headers)

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/policies", payload, headers)

    def suspend_policy(self, policy_id: str, suspension_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/policies/{policy_id}/suspend",
            {"suspension_reason": suspension_reason},
            headers,
        )

    def suspend_policy_raw(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/policies/{policy_id}/suspend", payload, headers)

    def reinstate_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/policies/{policy_id}/reinstate", {}, headers)

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/policies/{policy_id}", None, headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/policies", params, headers)

    def get_limit_ledger(self, policy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/policies/{policy_id}/limit-ledger", None, headers
        )

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def report_claim(self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/policies/{policy_id}/claims", payload, headers)

    def start_claim_review(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/start-review", {}, headers)

    def coverage_decision(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/coverage-decision", payload, headers
        )

    def close_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/close", {}, headers)

    def reopen_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/reopen", {}, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/claims/{claim_id}", None, headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/claims", params, headers)

    # ------------------------------------------------------------------
    # Related-claim groups
    # ------------------------------------------------------------------
    def create_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/related-claim-groups", payload, headers)

    def attach_claim_to_group(
        self, group_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/related-claim-groups/{group_id}/claims", payload, headers
        )

    def get_group(self, group_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/related-claim-groups/{group_id}", None, headers
        )

    def list_groups(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/related-claim-groups", params, headers)

    # ------------------------------------------------------------------
    # Pre-suit resolutions
    # ------------------------------------------------------------------
    def create_pre_suit_resolution(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/pre-suit-resolutions", payload, headers
        )

    def accept_pre_suit_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/pre-suit-resolutions/{resolution_id}/accept", {}, headers
        )

    def get_pre_suit_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/pre-suit-resolutions/{resolution_id}", None, headers
        )

    def list_pre_suit_resolutions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/pre-suit-resolutions", params, headers)

    # ------------------------------------------------------------------
    # Indemnity payments
    # ------------------------------------------------------------------
    def create_payment(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/indemnity-payments", payload, headers
        )

    def approve_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/indemnity-payments/{payment_id}/approve", {}, headers
        )

    def void_payment(self, payment_id: str, void_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/indemnity-payments/{payment_id}/void",
            {"void_reason": void_reason},
            headers,
        )

    def void_payment_raw(self, payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/indemnity-payments/{payment_id}/void", payload, headers
        )

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/indemnity-payments/{payment_id}", None, headers)

    def list_payments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/indemnity-payments", params, headers)

    # ------------------------------------------------------------------
    # Defense assignments
    # ------------------------------------------------------------------
    def create_assignment(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/defense-assignments", payload, headers
        )

    def close_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-assignments/{assignment_id}/close", {}, headers
        )

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/defense-assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/defense-assignments", params, headers)

    # ------------------------------------------------------------------
    # Defense invoices
    # ------------------------------------------------------------------
    def submit_invoice(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-assignments/{assignment_id}/invoices", payload, headers
        )

    def audit_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-invoices/{invoice_id}/audit", {}, headers
        )

    def dispute_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-invoices/{invoice_id}/dispute", payload, headers
        )

    def approve_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/defense-invoices/{invoice_id}/approve", {}, headers
        )

    def void_invoice(self, invoice_id: str, void_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/defense-invoices/{invoice_id}/void",
            {"void_reason": void_reason},
            headers,
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/defense-invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/defense-invoices", params, headers)
