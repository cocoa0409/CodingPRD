"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        # PRD §4: "Every endpoint is mounted under the `/api` prefix". The
        # runner exports API_BASE_URL as the bare scheme://host:port, so the
        # prefix is appended here; the per-endpoint paths below stay relative.
        self.base_url = self.base_url.rstrip("/") + "/api"

    # --- Funding landscape ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def create_funder(self, payload, headers):
        return self._request("POST", "/funders", payload, headers)

    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def list_grant_outcome_reports(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/outcome-reports", headers=headers, params=params
        )

    def list_grant_in_kind_donations(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/in-kind-donations", headers=headers, params=params
        )

    def recompute_grant_posture(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/posture-recompute", {}, headers)

    # --- Single door ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def create_intake_assessment(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/intake-assessments", payload, headers
        )

    def list_intake_assessments(self, headers, params=None):
        return self._request("GET", "/intake-assessments", headers=headers, params=params)

    def get_intake_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/intake-assessments/{assessment_id}", headers=headers
        )

    def submit_intake_assessment(self, assessment_id, headers):
        return self._request("POST", f"/intake-assessments/{assessment_id}/submit", {}, headers)

    def route_intake_assessment(self, assessment_id, headers):
        return self._request("POST", f"/intake-assessments/{assessment_id}/route", {}, headers)

    def return_intake_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/intake-assessments/{assessment_id}/return", payload, headers
        )

    def create_eligibility_screen(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/intake-assessments/{assessment_id}/eligibility-screens", payload, headers
        )

    def list_eligibility_screens(self, headers, params=None):
        return self._request("GET", "/eligibility-screens", headers=headers, params=params)

    def get_eligibility_screen(self, screen_id, headers):
        return self._request("GET", f"/eligibility-screens/{screen_id}", headers=headers)

    def determine_eligibility_screen(self, screen_id, payload, headers):
        return self._request(
            "POST", f"/eligibility-screens/{screen_id}/determine", payload, headers
        )

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def exit_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/exit", payload, headers)

    # --- Authorizations and deliveries ---
    def create_service_authorization(self, payload, headers):
        return self._request("POST", "/service-authorizations", payload, headers)

    def list_service_authorizations(self, headers, params=None):
        return self._request("GET", "/service-authorizations", headers=headers, params=params)

    def get_service_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/service-authorizations/{authorization_id}", headers=headers
        )

    def create_service_delivery(self, payload, headers):
        return self._request("POST", "/service-deliveries", payload, headers)

    def list_service_deliveries(self, headers, params=None):
        return self._request("GET", "/service-deliveries", headers=headers, params=params)

    def get_service_delivery(self, delivery_id, headers):
        return self._request("GET", f"/service-deliveries/{delivery_id}", headers=headers)

    def document_service_delivery(self, delivery_id, headers):
        return self._request("POST", f"/service-deliveries/{delivery_id}/document", {}, headers)

    def bill_service_delivery(self, delivery_id, headers):
        return self._request("POST", f"/service-deliveries/{delivery_id}/bill", {}, headers)

    def void_service_delivery(self, delivery_id, headers):
        return self._request("POST", f"/service-deliveries/{delivery_id}/void", {}, headers)

    def list_cost_allocations(self, headers, params=None):
        return self._request("GET", "/cost-allocations", headers=headers, params=params)

    def get_cost_allocation(self, allocation_id, headers):
        return self._request("GET", f"/cost-allocations/{allocation_id}", headers=headers)

    # --- In-kind and outcome reporting ---
    def create_in_kind_donation(self, payload, headers):
        return self._request("POST", "/in-kind-donations", payload, headers)

    def create_outcome_report(self, payload, headers):
        return self._request("POST", "/outcome-reports", payload, headers)

    def submit_outcome_report(self, report_id, headers):
        return self._request("POST", f"/outcome-reports/{report_id}/submit", {}, headers)

    def accept_outcome_report(self, report_id, headers):
        return self._request("POST", f"/outcome-reports/{report_id}/accept", {}, headers)

    def reject_outcome_report(self, report_id, headers):
        return self._request("POST", f"/outcome-reports/{report_id}/reject", {}, headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
