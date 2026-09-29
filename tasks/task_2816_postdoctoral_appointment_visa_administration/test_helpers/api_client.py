"""API client: one method per endpoint defined in the PRD's endpoint directory."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to the 41 declared operations."""

    # ─── Scholars ─────────────────────────────────────────────────────────

    def create_postdoc(self, payload: dict, headers: dict):
        return self._request("POST", "/postdocs", payload, headers)

    def get_postdoc(self, postdoc_id: str, headers: dict):
        return self._request("GET", f"/postdocs/{postdoc_id}", headers=headers)

    # ─── Faculty mentors ──────────────────────────────────────────────────

    def create_faculty_mentor(self, payload: dict, headers: dict):
        return self._request("POST", "/faculty-mentors", payload, headers)

    def get_faculty_mentor(self, mentor_id: str, headers: dict):
        return self._request("GET", f"/faculty-mentors/{mentor_id}", headers=headers)

    # ─── Awards ───────────────────────────────────────────────────────────

    def create_funding_source(self, payload: dict, headers: dict):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, funding_source_id: str, headers: dict):
        return self._request(
            "GET", f"/funding-sources/{funding_source_id}", headers=headers
        )

    def verify_funding_source(self, funding_source_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/funding-sources/{funding_source_id}/verification", payload, headers
        )

    # ─── Laboratories ─────────────────────────────────────────────────────

    def create_laboratory(self, payload: dict, headers: dict):
        return self._request("POST", "/laboratories", payload, headers)

    def get_laboratory(self, laboratory_id: str, headers: dict):
        return self._request("GET", f"/laboratories/{laboratory_id}", headers=headers)

    # ─── Appointments ─────────────────────────────────────────────────────

    def create_appointment(self, payload: dict, headers: dict):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers: dict, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id: str, headers: dict):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def approve_salary_exception(self, appointment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/appointments/{appointment_id}/salary-exception", payload, headers
        )

    def issue_offer(self, appointment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/issue-offer", payload or {}, headers
        )

    def accept_offer(self, appointment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/accept-offer", payload or {}, headers
        )

    def activate_appointment(self, appointment_id: str, headers: dict,
                             payload: Optional[dict] = None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/activate", payload or {}, headers
        )

    def withdraw_appointment(self, appointment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/appointments/{appointment_id}/withdraw", payload, headers
        )

    def list_visa_cases_for_appointment(self, appointment_id: str, headers: dict,
                                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/visa-cases",
            headers=headers, params=params,
        )

    def list_development_documents_for_appointment(self, appointment_id: str, headers: dict,
                                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/development-documents",
            headers=headers, params=params,
        )

    def list_export_control_reviews_for_appointment(self, appointment_id: str, headers: dict,
                                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/export-control-reviews",
            headers=headers, params=params,
        )

    def list_exit_record_for_appointment(self, appointment_id: str, headers: dict,
                                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/appointments/{appointment_id}/exit-record",
            headers=headers, params=params,
        )

    # ─── Visa cases ───────────────────────────────────────────────────────

    def submit_petition(self, visa_case_id: str, headers: dict,
                        payload: Optional[dict] = None):
        return self._request(
            "POST", f"/visa-cases/{visa_case_id}/submit-petition", payload or {}, headers
        )

    def record_adjudication(self, visa_case_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/visa-cases/{visa_case_id}/adjudication", payload, headers
        )

    # ─── Development documents ────────────────────────────────────────────

    def submit_development_document(self, document_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/development-documents/{document_id}/submit", payload, headers
        )

    def acknowledge_development_document(self, document_id: str, headers: dict,
                                         payload: Optional[dict] = None):
        return self._request(
            "POST", f"/development-documents/{document_id}/acknowledge",
            payload or {}, headers,
        )

    def review_development_document(self, document_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/development-documents/{document_id}/review", payload, headers
        )

    # ─── Research-security screening ──────────────────────────────────────

    def decide_export_control_review(self, review_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/export-control-reviews/{review_id}/decision", payload, headers
        )

    # ─── Bench access ─────────────────────────────────────────────────────

    def create_lab_access_grant(self, payload: dict, headers: dict):
        return self._request("POST", "/lab-access-grants", payload, headers)

    def list_lab_access_grants(self, headers: dict,
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/lab-access-grants", headers=headers, params=params)

    def get_lab_access_grant(self, grant_id: str, headers: dict):
        return self._request("GET", f"/lab-access-grants/{grant_id}", headers=headers)

    # ─── Reappointment reviews ────────────────────────────────────────────

    def open_reappointment_review(self, appointment_id: str, headers: dict,
                                  payload: Optional[dict] = None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reappointment-reviews",
            payload or {}, headers,
        )

    def list_reappointment_reviews(self, headers: dict,
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/reappointment-reviews", headers=headers, params=params
        )

    def get_reappointment_review(self, review_id: str, headers: dict):
        return self._request(
            "GET", f"/reappointment-reviews/{review_id}", headers=headers
        )

    def record_recommendation(self, review_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/reappointment-reviews/{review_id}/recommendation", payload, headers
        )

    def finalize_reappointment_review(self, review_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/reappointment-reviews/{review_id}/finalize", payload, headers
        )

    def list_grievances_for_review(self, review_id: str, headers: dict,
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/reappointment-reviews/{review_id}/grievances",
            headers=headers, params=params,
        )

    # ─── Grievances ───────────────────────────────────────────────────────

    def create_grievance(self, payload: dict, headers: dict):
        return self._request("POST", "/grievances", payload, headers)

    def resolve_grievance(self, grievance_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/grievances/{grievance_id}/resolution", payload, headers
        )

    # ─── Exit processing ──────────────────────────────────────────────────

    def initiate_exit(self, appointment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/appointments/{appointment_id}/exit", payload, headers
        )

    def sign_ip_assignment(self, exit_record_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/exit-records/{exit_record_id}/ip-assignment", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Raw escape hatch for header-defect probes ────────────────────────

    def raw(self, method: str, path: str, payload: Any = None,
            headers: Optional[dict] = None, params: Optional[dict] = None):
        """Send an arbitrary request, e.g. with a deliberately malformed header set."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
