"""API client: one method per endpoint the PRD declares."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint surface over the Aging Life Care Coordination API."""

    # ------------------------------------------------------------- clients ---
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/clients", payload, headers)

    def list_clients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/clients", headers=headers, params=params)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/care/clients/{client_id}", headers=headers)

    def patch_client_state(
        self, client_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/clients/{client_id}/state", payload, headers
        )

    def record_capacity_determination(
        self, client_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/care/clients/{client_id}/capacity-determination", payload, headers
        )

    def post_retainer_deposit(
        self, client_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/care/clients/{client_id}/retainer-deposits", payload, headers
        )

    # ------------------------------------------------------- care managers ---
    def create_care_manager(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/care-managers", payload, headers)

    def get_care_manager(self, care_manager_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/care-managers/{care_manager_id}", headers=headers
        )

    # ------------------------------------------------------------- vendors ---
    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/vendors", payload, headers)

    def list_vendors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/care/vendors/{vendor_id}", headers=headers)

    def update_vendor(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/care/vendors/{vendor_id}", payload, headers)

    # ----------------------------------------------------- family contacts ---
    def create_family_contact(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/family-contacts", payload, headers)

    def list_family_contacts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/care/family-contacts", headers=headers, params=params
        )

    def get_family_contact(self, contact_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/family-contacts/{contact_id}", headers=headers
        )

    def send_family_report(
        self, contact_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/care/family-contacts/{contact_id}/reports", payload, headers
        )

    # --------------------------------------------------------- assessments ---
    def create_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/assessments", payload, headers)

    def list_assessments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/assessments/{assessment_id}", headers=headers
        )

    def update_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/assessments/{assessment_id}", payload, headers
        )

    def patch_assessment_state(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/assessments/{assessment_id}/state", payload, headers
        )

    # ---------------------------------------------------------- care plans ---
    def create_care_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/care-plans", payload, headers)

    def list_care_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/care-plans", headers=headers, params=params)

    def get_care_plan(self, care_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/care/care-plans/{care_plan_id}", headers=headers)

    def patch_care_plan_state(
        self, care_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/care-plans/{care_plan_id}/state", payload, headers
        )

    # ----------------------------------------------- service authorizations --
    def create_service_authorization(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/care/service-authorizations", payload, headers)

    def list_service_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/care/service-authorizations", headers=headers, params=params
        )

    def get_service_authorization(self, authorization_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/service-authorizations/{authorization_id}", headers=headers
        )

    def patch_service_authorization_state(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH",
            f"/care/service-authorizations/{authorization_id}/state",
            payload,
            headers,
        )

    def post_coi_event(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/care/service-authorizations/{authorization_id}/coi-events",
            payload,
            headers,
        )

    # -------------------------------------------------- family conferences ---
    def create_family_conference(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/family-conferences", payload, headers)

    def list_family_conferences(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/care/family-conferences", headers=headers, params=params
        )

    def get_family_conference(self, conference_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/family-conferences/{conference_id}", headers=headers
        )

    def patch_family_conference_state(
        self, conference_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/family-conferences/{conference_id}/state", payload, headers
        )

    # ------------------------------------------------- conference decisions --
    def create_conference_decision(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/care/conference-decisions", payload, headers)

    def list_conference_decisions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/care/conference-decisions", headers=headers, params=params
        )

    def get_conference_decision(self, decision_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/conference-decisions/{decision_id}", headers=headers
        )

    def patch_conference_decision_state(
        self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/conference-decisions/{decision_id}/state", payload, headers
        )

    # ------------------------------------------------------ crisis episodes --
    def create_crisis_episode(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/crisis-episodes", payload, headers)

    def list_crisis_episodes(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/care/crisis-episodes", headers=headers, params=params
        )

    def get_crisis_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/crisis-episodes/{episode_id}", headers=headers
        )

    def patch_crisis_episode_state(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/crisis-episodes/{episode_id}/state", payload, headers
        )

    # ---------------------------------------------------------- time entries -
    def create_time_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/time-entries", payload, headers)

    def list_time_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/time-entries", headers=headers, params=params)

    def get_time_entry(self, time_entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/care/time-entries/{time_entry_id}", headers=headers
        )

    def patch_time_entry_state(
        self, time_entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/time-entries/{time_entry_id}/state", payload, headers
        )

    # -------------------------------------------------------------- invoices -
    def create_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/care/invoices", payload, headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/care/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/care/invoices/{invoice_id}", headers=headers)

    def patch_invoice_state(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/care/invoices/{invoice_id}/state", payload, headers
        )

    def post_invoice_payment(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/care/invoices/{invoice_id}/payments", payload, headers
        )

    # --------------------------------------------------------- logical clock -
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
