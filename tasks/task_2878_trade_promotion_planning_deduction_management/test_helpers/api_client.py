"""
Typed HTTP client for the Trade Promotion Deductions API.

One method per endpoint of PRD section 4, plus the logical-clock capability.
Every method takes an explicit `headers` dict so that the caller's role and
identity are always visible at the call site, and returns the raw
`requests.Response` so tests can assert on status codes and error envelopes.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/trade-marketing"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to millisecond precision.

    Comparisons between two instants the service produced must not turn on how
    many fractional digits happen to be printed, so both sides are reduced to
    exactly three fractional digits before they are compared.
    """
    if not isinstance(value, str) or not value.endswith("Z"):
        return value
    body = value[:-1]
    if "." in body:
        whole, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        whole, frac = body, "000"
    return f"{whole}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 UTC instants denote the same millisecond."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Endpoint-per-method wrapper over the generic envelope-aware client."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self.post("/_clock/set_current_utc", json={"current_utc": current_utc},
                         headers=headers)

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post("/_clock/set_current_utc", json=payload, headers=headers)

    # ─── Trade programs ───────────────────────────────

    def create_program(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/programs", json=payload, headers=headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/programs", headers=headers, params=params)

    def lock_program(self, program_id: str, headers: Dict[str, str],
                     payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/programs/{program_id}/lock", json=payload, headers=headers)

    # ─── Brands ───────────────────────────────────────

    def create_brand(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/brands", json=payload, headers=headers)

    def get_brand(self, brand_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/brands/{brand_id}", headers=headers)

    def list_brands(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/brands", headers=headers, params=params)

    # ─── Retail customers ─────────────────────────────

    def create_customer(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/customers", json=payload, headers=headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/customers/{customer_id}", headers=headers)

    def list_customers(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/customers", headers=headers, params=params)

    def place_customer_credit_hold(self, customer_id: str, payload: Any,
                                   headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/customers/{customer_id}/credit-hold",
                         json=payload, headers=headers)

    # ─── Budget allocations ───────────────────────────

    def create_budget_allocation(self, payload: Any,
                                 headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/budget-allocations", json=payload, headers=headers)

    def get_budget_allocation(self, allocation_id: str,
                              headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/budget-allocations/{allocation_id}", headers=headers)

    def list_budget_allocations(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/budget-allocations", headers=headers, params=params)

    def approve_budget_allocation(self, allocation_id: str, headers: Dict[str, str],
                                  payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/budget-allocations/{allocation_id}/approve",
                         json=payload, headers=headers)

    # ─── Promotions ───────────────────────────────────

    def create_promotion(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions", json=payload, headers=headers)

    def get_promotion(self, promotion_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/promotions", headers=headers, params=params)

    def submit_promotion(self, promotion_id: str, headers: Dict[str, str],
                         payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/submit",
                         json=payload, headers=headers)

    def request_changes_promotion(self, promotion_id: str, payload: Any,
                                  headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/request-changes",
                         json=payload, headers=headers)

    def revise_promotion(self, promotion_id: str, headers: Dict[str, str],
                         payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/revise",
                         json=payload, headers=headers)

    def approve_promotion(self, promotion_id: str, headers: Dict[str, str],
                          payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/approve",
                         json=payload, headers=headers)

    def withdraw_promotion(self, promotion_id: str, headers: Dict[str, str],
                           payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/withdraw",
                         json=payload, headers=headers)

    def create_promotion_activation_run(self, headers: Dict[str, str],
                                        payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/promotion-activation-runs", json=payload, headers=headers)

    # ─── Tactic lines ─────────────────────────────────

    def create_tactic(self, promotion_id: str, payload: Any,
                      headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/tactics",
                         json=payload, headers=headers)

    def list_promotion_tactics(self, promotion_id: str, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/promotions/{promotion_id}/tactics",
                        headers=headers, params=params)

    def list_tactics(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/tactics", headers=headers, params=params)

    def get_tactic(self, tactic_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/tactics/{tactic_id}", headers=headers)

    def patch_tactic(self, tactic_id: str, payload: Any,
                     headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"{BASE}/tactics/{tactic_id}",
                             payload=payload, headers=headers)

    def cancel_tactic(self, tactic_id: str, headers: Dict[str, str],
                      payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/tactics/{tactic_id}/cancel", json=payload, headers=headers)

    # ─── Post-event analysis ──────────────────────────

    def analyze_promotion(self, promotion_id: str, payload: Any,
                          headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/analyze",
                         json=payload, headers=headers)

    def list_promotion_post_event_analyses(self, promotion_id: str, headers: Dict[str, str],
                                           params: Optional[Dict[str, Any]] = None
                                           ) -> requests.Response:
        return self.get(f"{BASE}/promotions/{promotion_id}/post-event-analyses",
                        headers=headers, params=params)

    def list_post_event_analyses(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/post-event-analyses", headers=headers, params=params)

    def get_post_event_analysis(self, analysis_id: str,
                                headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/post-event-analyses/{analysis_id}", headers=headers)

    # ─── Retailer documents ───────────────────────────

    def create_document(self, promotion_id: str, payload: Any,
                        headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/documents",
                         json=payload, headers=headers)

    def list_promotion_documents(self, promotion_id: str, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/promotions/{promotion_id}/documents",
                        headers=headers, params=params)

    def list_documents(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/documents", headers=headers, params=params)

    def get_document(self, document_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/documents/{document_id}", headers=headers)

    def verify_document(self, document_id: str, headers: Dict[str, str],
                        payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/documents/{document_id}/verify",
                         json=payload, headers=headers)

    # ─── Volume facts ─────────────────────────────────

    def create_volume_fact(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/volume-facts", json=payload, headers=headers)

    def get_volume_fact(self, fact_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/volume-facts/{fact_id}", headers=headers)

    def list_volume_facts(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/volume-facts", headers=headers, params=params)

    # ─── Accrual ledger ───────────────────────────────

    def create_accrual(self, promotion_id: str, payload: Any,
                       headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/promotions/{promotion_id}/accruals",
                         json=payload, headers=headers)

    def get_accrual(self, accrual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/accruals/{accrual_id}", headers=headers)

    def list_accruals(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/accruals", headers=headers, params=params)

    def reverse_accrual(self, accrual_id: str, payload: Any,
                        headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/accruals/{accrual_id}/reverse",
                         json=payload, headers=headers)

    # ─── Deductions ───────────────────────────────────

    def create_deduction(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/deductions", json=payload, headers=headers)

    def get_deduction(self, deduction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/deductions/{deduction_id}", headers=headers)

    def list_deductions(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/deductions", headers=headers, params=params)

    def match_deduction(self, deduction_id: str, payload: Any,
                        headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/deductions/{deduction_id}/match",
                         json=payload, headers=headers)

    def validate_deduction(self, deduction_id: str, payload: Any,
                           headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/deductions/{deduction_id}/validate",
                         json=payload, headers=headers)

    def settle_deduction(self, deduction_id: str, headers: Dict[str, str],
                         payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/deductions/{deduction_id}/settle",
                         json=payload, headers=headers)

    def dispute_deduction(self, deduction_id: str, payload: Any,
                          headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/deductions/{deduction_id}/dispute",
                         json=payload, headers=headers)

    # ─── Disputes ─────────────────────────────────────

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/disputes", headers=headers, params=params)

    def send_dispute_to_retailer(self, dispute_id: str, headers: Dict[str, str],
                                 payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/disputes/{dispute_id}/send-to-retailer",
                         json=payload, headers=headers)

    def retailer_respond_dispute(self, dispute_id: str, payload: Any,
                                 headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/disputes/{dispute_id}/retailer-respond",
                         json=payload, headers=headers)

    def record_dispute_recovery(self, dispute_id: str, payload: Any,
                                headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/disputes/{dispute_id}/record-recovery",
                         json=payload, headers=headers)

    def write_off_dispute(self, dispute_id: str, payload: Any,
                          headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/disputes/{dispute_id}/write-off",
                         json=payload, headers=headers)

    def create_deduction_aging_run(self, headers: Dict[str, str],
                                   payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/deduction-aging-runs", json=payload, headers=headers)

    # ─── Compliance audits ────────────────────────────

    def create_compliance_audit(self, customer_id: str, payload: Any,
                                headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/customers/{customer_id}/compliance-audits",
                         json=payload, headers=headers)

    def list_customer_compliance_audits(self, customer_id: str, headers: Dict[str, str],
                                        params: Optional[Dict[str, Any]] = None
                                        ) -> requests.Response:
        return self.get(f"{BASE}/customers/{customer_id}/compliance-audits",
                        headers=headers, params=params)

    def list_compliance_audits(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.get(f"{BASE}/compliance-audits", headers=headers, params=params)

    def get_compliance_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/compliance-audits/{audit_id}", headers=headers)

    def record_audit_finding(self, audit_id: str, payload: Any,
                             headers: Dict[str, str]) -> requests.Response:
        return self.post(f"{BASE}/compliance-audits/{audit_id}/record-finding",
                         json=payload, headers=headers)

    def issue_audit_findings(self, audit_id: str, headers: Dict[str, str],
                             payload: Any = None) -> requests.Response:
        return self.post(f"{BASE}/compliance-audits/{audit_id}/issue-findings",
                         json=payload, headers=headers)


# Module-level singleton the conftest bridge hands to every test.
api_client = ApiClient()
