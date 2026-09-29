"""One method per endpoint of section 4, plus the clock surface.

Every method returns the raw ``requests.Response`` so that tests can assert
on status codes as well as bodies. No method inspects or unwraps the
envelope: that is the validators' job.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class AccreditationApiClient(GenericApiClient):
    """HTTP surface of the accreditation body assessor programme."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # Accreditation schemes
    # ------------------------------------------------------------------

    def create_scheme(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/schemes", payload, headers)

    def set_scheme_status(self, scheme_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/schemes/{scheme_id}/status", payload, headers
        )

    def list_schemes(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/schemes", params, headers)

    def get_scheme(self, scheme_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/schemes/{scheme_id}", None, headers)

    # ------------------------------------------------------------------
    # Assessors
    # ------------------------------------------------------------------

    def create_assessor(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/assessors", payload, headers)

    def list_assessors(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/assessors", params, headers)

    def get_assessor(self, assessor_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/assessors/{assessor_id}", None, headers
        )

    def screen_assessor(self, assessor_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessors/{assessor_id}/screen",
            {} if payload is None else payload,
            headers,
        )

    def set_assessor_status(self, assessor_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/assessors/{assessor_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Qualifications
    # ------------------------------------------------------------------

    def create_qualification(self, assessor_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessors/{assessor_id}/qualifications",
            payload,
            headers,
        )

    def verify_evidence(self, qualification_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/qualifications/{qualification_id}/verify-evidence",
            payload,
            headers,
        )

    def list_qualifications(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/qualifications", params, headers)

    def get_qualification(self, qualification_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/qualifications/{qualification_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Impartiality declarations
    # ------------------------------------------------------------------

    def create_declaration(self, assessor_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessors/{assessor_id}/impartiality-declarations",
            payload,
            headers,
        )

    def list_declarations(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/impartiality-declarations", params, headers
        )

    def get_declaration(self, declaration_id, headers) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/impartiality-declarations/{declaration_id}",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Applicant organizations
    # ------------------------------------------------------------------

    def create_organization(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/organizations", payload, headers)

    def list_organizations(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/organizations", params, headers)

    def get_organization(self, organization_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/organizations/{organization_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Assessment cycles
    # ------------------------------------------------------------------

    def create_application(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/applications", payload, headers)

    def list_applications(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/applications", params, headers)

    def get_application(self, application_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applications/{application_id}", None, headers
        )

    def close_assessment(self, application_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/close-assessment",
            {} if payload is None else payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Team assignments
    # ------------------------------------------------------------------

    def propose_team_member(self, application_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/team-assignments",
            payload,
            headers,
        )

    def confirm_team_assignment(
        self, assignment_id, headers, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/team-assignments/{assignment_id}/confirm",
            {} if payload is None else payload,
            headers,
        )

    def recuse_team_assignment(self, assignment_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/team-assignments/{assignment_id}/recuse",
            payload,
            headers,
        )

    def list_team_assignments(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/team-assignments", params, headers)

    def get_team_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/team-assignments/{assignment_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Assessment plans
    # ------------------------------------------------------------------

    def create_plan(self, application_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/assessment-plans",
            payload,
            headers,
        )

    def approve_plan(self, plan_id, headers, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessment-plans/{plan_id}/approve",
            {} if payload is None else payload,
            headers,
        )

    def return_plan_to_draft(self, plan_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessment-plans/{plan_id}/return-to-draft",
            payload,
            headers,
        )

    def list_plans(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/assessment-plans", params, headers)

    def get_plan(self, plan_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/assessment-plans/{plan_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Witness sessions
    # ------------------------------------------------------------------

    def schedule_witness_session(self, plan_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessment-plans/{plan_id}/witness-sessions",
            payload,
            headers,
        )

    def record_session_outcome(self, session_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/witness-sessions/{session_id}/outcome",
            payload,
            headers,
        )

    def list_witness_sessions(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/witness-sessions", params, headers)

    def get_witness_session(self, session_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/witness-sessions/{session_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Nonconformities
    # ------------------------------------------------------------------

    def raise_nonconformity(self, application_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/nonconformities",
            payload,
            headers,
        )

    def submit_response(self, nonconformity_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformities/{nonconformity_id}/responses",
            payload,
            headers,
        )

    def review_response(self, nonconformity_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformities/{nonconformity_id}/review",
            payload,
            headers,
        )

    def verify_effectiveness(self, nonconformity_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformities/{nonconformity_id}/verify-effectiveness",
            payload,
            headers,
        )

    def escalate_nonconformity(
        self, nonconformity_id, headers, payload=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformities/{nonconformity_id}/escalate",
            {} if payload is None else payload,
            headers,
        )

    def reopen_nonconformity(self, nonconformity_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformities/{nonconformity_id}/reopen",
            payload,
            headers,
        )

    def list_nonconformities(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/nonconformities", params, headers)

    def get_nonconformity(self, nonconformity_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/nonconformities/{nonconformity_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Decision panel
    # ------------------------------------------------------------------

    def cast_vote(self, decision_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/decisions/{decision_id}/votes", payload, headers
        )

    def finalize_decision(self, decision_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/decisions/{decision_id}/finalize", payload, headers
        )

    def list_decisions(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/decisions", params, headers)

    def get_decision(self, decision_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/decisions/{decision_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Accredited scopes
    # ------------------------------------------------------------------

    def set_scope_status(self, scope_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/scopes/{scope_id}/status", payload, headers
        )

    def open_surveillance_application(self, scope_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/scopes/{scope_id}/surveillance-applications",
            payload,
            headers,
        )

    def list_scopes(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/scopes", params, headers)

    def get_scope(self, scope_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/scopes/{scope_id}", None, headers)

    # ------------------------------------------------------------------
    # Complaints and appeals
    # ------------------------------------------------------------------

    def create_complaint(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/complaints", payload, headers)

    def review_complaint(self, complaint_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/review", payload, headers
        )

    def resolve_complaint(self, complaint_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/resolve", payload, headers
        )

    def escalate_complaint_to_mra(self, complaint_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/complaints/{complaint_id}/mra-escalation",
            payload,
            headers,
        )

    def list_complaints(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/complaints", params, headers)

    def get_complaint(self, complaint_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/complaints/{complaint_id}", None, headers
        )
