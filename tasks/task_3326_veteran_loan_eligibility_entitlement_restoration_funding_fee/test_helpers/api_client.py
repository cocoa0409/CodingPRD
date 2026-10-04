"""API client: one method per endpoint defined in the PRD (§4)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .test_users import LOAN_OFFICER, PROGRAM_ADMIN, UNDERWRITER


class ApiClient(GenericApiClient):
    """One method per PRD endpoint; acting headers are always explicit."""

    # ------------------------------------------------------------------
    # Logical clock (§2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", "/va-loans/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Veterans (§3.1)
    # ------------------------------------------------------------------
    def create_veteran(self, payload: Dict[str, Any], headers: Dict[str, str] = LOAN_OFFICER):
        return self._request("POST", "/va-loans/veterans", payload=payload, headers=headers)

    def get_veteran(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request("GET", f"/va-loans/veterans/{veteran_id}", headers=headers)

    # ------------------------------------------------------------------
    # Service periods (§3.1)
    # ------------------------------------------------------------------
    def create_service_period(self, veteran_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/veterans/{veteran_id}/service-periods",
            payload=payload, headers=headers,
        )

    def list_service_periods(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/service-periods",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Certificates of eligibility (§3.2)
    # ------------------------------------------------------------------
    def create_coe_request(self, veteran_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/veterans/{veteran_id}/coe-requests",
            payload=payload, headers=headers,
        )

    def list_coe_requests(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/coe-requests",
            headers=headers, params=params,
        )

    def issue_coe(self, coe_id: str, payload: Optional[Dict[str, Any]] = None,
                  headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", f"/va-loans/coe-requests/{coe_id}/issue",
            payload=payload or {}, headers=headers,
        )

    def deny_coe(self, coe_id: str, headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", f"/va-loans/coe-requests/{coe_id}/deny", payload={}, headers=headers,
        )

    def reconsider_coe(self, coe_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/coe-requests/{coe_id}/reconsider", payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Entitlement account (§2.6) — array of 0-1
    # ------------------------------------------------------------------
    def get_entitlement_account(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/entitlement-account", headers=headers,
        )

    # ------------------------------------------------------------------
    # Loans (§3.3, §3.4)
    # ------------------------------------------------------------------
    def create_loan(self, veteran_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/veterans/{veteran_id}/loans",
            payload=payload, headers=headers,
        )

    def list_veteran_loans(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/loans", headers=headers, params=params,
        )

    def get_loan(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request("GET", f"/va-loans/loans/{loan_id}", headers=headers)

    def list_loans(self, headers: Dict[str, str] = LOAN_OFFICER,
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/va-loans/loans", headers=headers, params=params)

    def create_underwriting_decision(self, loan_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str] = UNDERWRITER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/underwriting-decisions",
            payload=payload, headers=headers,
        )

    def list_underwriting_decisions(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/underwriting-decisions",
            headers=headers, params=params,
        )

    def close_loan(self, loan_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/close", payload=payload, headers=headers,
        )

    def record_payoff(self, loan_id: str, payoff_type: str,
                      headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/record-payoff",
            payload={"payoff_type": payoff_type}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Funding fee assessments (§3.3, §3.4)
    # ------------------------------------------------------------------
    def list_funding_fee_assessments(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/funding-fee-assessments", headers=headers,
        )

    def refund_funding_fee(self, assessment_id: str, disability_evidence: bool = True,
                           headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", f"/va-loans/funding-fee-assessments/{assessment_id}/refund",
            payload={"disability_evidence": disability_evidence}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Appraisers and appraisals (§3.5)
    # ------------------------------------------------------------------
    def create_appraiser(self, payload: Dict[str, Any], headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request("POST", "/va-loans/appraisers", payload=payload, headers=headers)

    def list_appraisal_requests(self, headers: Dict[str, str] = LOAN_OFFICER,
                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/va-loans/appraisal-requests", headers=headers, params=params)

    def create_appraisal_request(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/appraisal-requests",
            payload={}, headers=headers,
        )

    def list_loan_appraisals(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/appraisal-requests",
            headers=headers, params=params,
        )

    def get_appraisal(self, appraisal_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request("GET", f"/va-loans/appraisal-requests/{appraisal_id}", headers=headers)

    def submit_appraisal_report(self, appraisal_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/va-loans/appraisal-requests/{appraisal_id}/submit-report",
            payload=payload, headers=headers,
        )

    def list_repair_requirements(self, appraisal_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/appraisal-requests/{appraisal_id}/repair-requirements",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Repair requirements (§3.5)
    # ------------------------------------------------------------------
    def complete_repair(self, repair_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/repair-requirements/{repair_id}/complete",
            payload={}, headers=headers,
        )

    def verify_repair(self, repair_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/va-loans/repair-requirements/{repair_id}/verify",
            payload={}, headers=headers,
        )

    def waive_repair(self, repair_id: str, headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", f"/va-loans/repair-requirements/{repair_id}/waive",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Occupancy certificates (§3.6)
    # ------------------------------------------------------------------
    def list_occupancy_certificates(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/occupancy-certificates", headers=headers,
        )

    def verify_occupancy(self, certificate_id: str, move_in_date: str,
                         headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/occupancy-certificates/{certificate_id}/verify-occupancy",
            payload={"move_in_date": move_in_date}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Deployment exceptions (§3.6)
    # ------------------------------------------------------------------
    def create_deployment_exception(self, veteran_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/veterans/{veteran_id}/deployment-exceptions",
            payload=payload, headers=headers,
        )

    def list_deployment_exceptions(self, veteran_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/deployment-exceptions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Assumption requests (§3.7)
    # ------------------------------------------------------------------
    def create_assumption_request(self, loan_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/assumption-requests",
            payload=payload, headers=headers,
        )

    def list_loan_assumption_requests(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/assumption-requests",
            headers=headers, params=params,
        )

    def list_veteran_assumption_requests(self, veteran_id: str,
                                         headers: Dict[str, str] = LOAN_OFFICER,
                                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/assumption-requests",
            headers=headers, params=params,
        )

    def approve_assumption(self, assumption_id: str, headers: Dict[str, str] = UNDERWRITER):
        return self._request(
            "POST", f"/va-loans/assumption-requests/{assumption_id}/approve",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Refinance requests (§3.8)
    # ------------------------------------------------------------------
    def create_refinance_request(self, loan_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/loans/{loan_id}/refinance-requests",
            payload=payload, headers=headers,
        )

    def list_refinance_requests(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/refinance-requests",
            headers=headers, params=params,
        )

    def evaluate_refinance(self, refinance_id: str, headers: Dict[str, str] = UNDERWRITER):
        return self._request(
            "POST", f"/va-loans/refinance-requests/{refinance_id}/evaluate",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Entitlement restoration requests (§3.7)
    # ------------------------------------------------------------------
    def create_restoration_request(self, veteran_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str] = LOAN_OFFICER):
        return self._request(
            "POST", f"/va-loans/veterans/{veteran_id}/entitlement-restoration-requests",
            payload=payload, headers=headers,
        )

    def list_veteran_restoration_requests(self, veteran_id: str,
                                          headers: Dict[str, str] = LOAN_OFFICER,
                                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/veterans/{veteran_id}/entitlement-restoration-requests",
            headers=headers, params=params,
        )

    def list_loan_restoration_requests(self, loan_id: str, headers: Dict[str, str] = LOAN_OFFICER,
                                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/va-loans/loans/{loan_id}/entitlement-restoration-requests",
            headers=headers, params=params,
        )

    def grant_restoration(self, restoration_id: str, headers: Dict[str, str] = PROGRAM_ADMIN):
        return self._request(
            "POST", f"/va-loans/entitlement-restoration-requests/{restoration_id}/grant",
            payload={}, headers=headers,
        )

    # ------------------------------------------------------------------
    # Audit events (§2.10)
    # ------------------------------------------------------------------
    def list_audit_events(self, headers: Dict[str, str] = PROGRAM_ADMIN,
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/va-loans/audit-events", headers=headers, params=params)


api_client = ApiClient()
