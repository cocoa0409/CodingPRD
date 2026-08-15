"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_PREFIX = "/api/v1"


class ApiClient(GenericApiClient):
    # --- Partner agreements (PRD §3.1) ---
    def create_partner_agreement(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/partner-agreements", payload, headers)

    def activate_partner_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/partner-agreements/{agreement_id}/activate",
            headers=headers,
        )

    # --- Programs (PRD §3.1) ---
    def create_program(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/programs", payload, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{_PREFIX}/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/programs/{program_id}", headers=headers)

    def publish_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/programs/{program_id}/publish", headers=headers,
        )

    # --- Students (PRD §3.2) ---
    def create_student(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/students/{student_id}", headers=headers)

    # --- Applications (PRD §3.2) ---
    def create_application(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/applications", payload, headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{_PREFIX}/applications", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/applications/{application_id}", headers=headers,
        )

    def record_clearance(self, application_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/clearance",
            payload, headers,
        )

    def resubmit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/resubmit",
            headers=headers,
        )

    def approve_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/approve",
            headers=headers,
        )

    def commit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/commit",
            headers=headers,
        )

    def withdraw_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/withdraw",
            headers=headers,
        )

    def application_lifecycle(self, application_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/lifecycle",
            payload, headers,
        )

    # --- Course pre-approvals (PRD §3.3) ---
    def create_course_preapproval(self, application_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/course-preapprovals",
            payload, headers,
        )

    def list_course_preapprovals(self, application_id: str, headers: Dict[str, str],
                                 params: Optional[dict] = None):
        return self._request(
            "GET", f"{_PREFIX}/applications/{application_id}/course-preapprovals",
            headers=headers, params=params,
        )

    def review_course_preapproval(self, cpa_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/course-preapprovals/{cpa_id}/review",
            payload, headers,
        )

    def revise_course_preapproval(self, cpa_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/course-preapprovals/{cpa_id}/revise",
            payload, headers,
        )

    # --- Travel advisories (PRD §3.6) ---
    def create_travel_advisory(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/travel-advisories", payload, headers)

    def lift_travel_advisory(self, advisory_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/travel-advisories/{advisory_id}/lift",
            headers=headers,
        )

    # --- Insurance enrollments (PRD §3.5) ---
    def create_insurance_enrollment(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/insurance-enrollments", payload, headers)

    def list_insurance_enrollments(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request(
            "GET", f"{_PREFIX}/insurance-enrollments", headers=headers, params=params,
        )

    def get_insurance_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/insurance-enrollments/{enrollment_id}", headers=headers,
        )

    def cancel_insurance_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/insurance-enrollments/{enrollment_id}/cancel",
            headers=headers,
        )

    # --- Billing statements (PRD §3.4) ---
    def list_billing_statements(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request(
            "GET", f"{_PREFIX}/billing-statements", headers=headers, params=params,
        )

    def get_billing_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{_PREFIX}/billing-statements/{statement_id}", headers=headers,
        )

    def record_payment(self, statement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/billing-statements/{statement_id}/payments",
            payload, headers,
        )

    # --- Incidents (PRD §3.7) ---
    def create_incident(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/incidents", payload, headers)

    def list_incidents(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{_PREFIX}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/incidents/{incident_id}/transition",
            payload, headers,
        )

    # --- Credit postings (PRD §3.8) ---
    def create_credit_posting(self, application_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/credit-postings",
            payload, headers,
        )

    def list_credit_postings(self, application_id: str, headers: Dict[str, str],
                             params: Optional[dict] = None):
        return self._request(
            "GET", f"{_PREFIX}/applications/{application_id}/credit-postings",
            headers=headers, params=params,
        )

    def post_credit_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/credit-postings/{posting_id}/post",
            headers=headers,
        )

    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
