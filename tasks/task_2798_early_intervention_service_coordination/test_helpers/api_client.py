"""
Endpoint client for the Early Intervention Service Coordination API.

One method per endpoint, each returning the raw ``requests.Response`` so that
tests can assert status codes and error envelopes. All business paths sit under
the ``/ei`` prefix; the logical clock endpoint sits outside it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ei"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the early intervention service."""

    # ─── Logical clock ────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Children ─────────────────────────────────────────────────────

    def create_child(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/children", payload, headers)

    def get_child(self, child_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/children/{child_id}", None, headers)

    # ─── Service coordinators ─────────────────────────────────────────

    def create_coordinator(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/service-coordinators", payload, headers)

    def get_coordinator(self, coordinator_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/service-coordinators/{coordinator_id}", None, headers
        )

    def get_caseload_summary(self, coordinator_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/service-coordinators/{coordinator_id}/caseload-summary",
            None,
            headers,
        )

    # ─── Referrals ────────────────────────────────────────────────────

    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", None, headers)

    def list_referrals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/referrals", params, headers)

    def assign_coordinator(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/assign-coordinator", payload, headers
        )

    def record_eligibility_determination(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/referrals/{referral_id}/eligibility-determination",
            payload,
            headers,
        )

    def record_entry_outcomes(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/entry-outcomes", payload, headers
        )

    def exit_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/exit", payload, headers
        )

    def get_timeline_compliance(self, referral_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/referrals/{referral_id}/timeline-compliance", None, headers
        )

    # ─── Contact logs ─────────────────────────────────────────────────

    def create_contact_log(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/contact-logs", payload, headers
        )

    def list_contact_logs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/contact-logs", params, headers)

    def get_contact_log(self, contact_log_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/contact-logs/{contact_log_id}", None, headers
        )

    # ─── Assessments ──────────────────────────────────────────────────

    def create_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/assessments", payload, headers)

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/assessments/{assessment_id}", None, headers)

    def list_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/assessments", params, headers)

    def complete_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/complete", payload, headers
        )

    # ─── Plans ────────────────────────────────────────────────────────

    def create_ifsp(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ifsps", payload, headers)

    def get_ifsp(self, ifsp_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ifsps/{ifsp_id}", None, headers)

    def list_ifsps(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ifsps", params, headers)

    def record_consent(
        self, ifsp_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/ifsps/{ifsp_id}/consent", payload, headers
        )

    # ─── Service lines ────────────────────────────────────────────────

    def create_ifsp_service(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ifsp-services", payload, headers)

    def get_ifsp_service(self, service_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ifsp-services/{service_id}", None, headers)

    def list_ifsp_services(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ifsp-services", params, headers)

    # ─── Providers ────────────────────────────────────────────────────

    def create_provider(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", None, headers)

    def suspend_provider(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/suspend", payload, headers
        )

    # ─── Authorizations ───────────────────────────────────────────────

    def create_authorization(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/provider-authorizations", payload, headers)

    def get_authorization(self, authorization_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/provider-authorizations/{authorization_id}", None, headers
        )

    def list_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/provider-authorizations", params, headers)

    def revoke_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/provider-authorizations/{authorization_id}/revoke",
            payload,
            headers,
        )

    # ─── Visits ───────────────────────────────────────────────────────

    def create_visit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/service-visits", payload, headers)

    def get_visit(self, visit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-visits/{visit_id}", None, headers)

    def list_visits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-visits", params, headers)

    def document_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/document", payload, headers
        )

    def void_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/void", payload, headers
        )

    # ─── Cost shares ──────────────────────────────────────────────────

    def create_cost_share(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/cost-shares", payload, headers)

    def get_cost_share(self, cost_share_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cost-shares/{cost_share_id}", None, headers)

    def list_cost_shares(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/cost-shares", params, headers)

    def finalize_cost_share(
        self, cost_share_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/cost-shares/{cost_share_id}/finalize", payload, headers
        )

    def waive_cost_share(
        self, cost_share_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/cost-shares/{cost_share_id}/waive", payload, headers
        )

    def record_insurance_consent(
        self, cost_share_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/cost-shares/{cost_share_id}/insurance-consent",
            payload,
            headers,
        )

    # ─── Transition plans ─────────────────────────────────────────────

    def create_transition_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/transition-plans", payload, headers)

    def get_transition_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/transition-plans/{plan_id}", None, headers)

    def list_transition_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/transition-plans", params, headers)

    def notify_lea(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/transition-plans/{plan_id}/notify-lea", payload, headers
        )


# Module-level singleton used by fixtures and tests.
api_client = ApiClient()
