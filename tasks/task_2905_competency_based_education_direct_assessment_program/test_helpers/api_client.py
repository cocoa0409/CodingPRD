"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert status
codes. The response envelope is peeled exactly once, by the framework
validators (``validate_success`` / ``validate_error`` / ``validate_list``) —
never here.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # ─── Programs ─────────────────────────────────────────────────────────
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def publish_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/programs/{program_id}/publish", {}, headers
        )

    # ─── Competencies ─────────────────────────────────────────────────────
    def create_competency(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/competencies", payload, headers)

    def get_competency(self, competency_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/competencies/{competency_id}", headers=headers)

    def list_competencies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/competencies", headers=headers, params=params)

    def set_competency_prerequisite(
        self, competency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/competencies/{competency_id}/prerequisite", payload, headers
        )

    def retire_competency(self, competency_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/competencies/{competency_id}/retire", {}, headers
        )

    # ─── Assessment blueprints ────────────────────────────────────────────
    def create_blueprint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/assessment-blueprints", payload, headers)

    def get_blueprint(self, blueprint_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/assessment-blueprints/{blueprint_id}", headers=headers
        )

    def list_blueprints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/assessment-blueprints", headers=headers, params=params
        )

    # ─── Students ─────────────────────────────────────────────────────────
    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/students", headers=headers, params=params)

    def activate_student(self, student_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/students/{student_id}/activate", {}, headers
        )

    def reinstate_student(self, student_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/students/{student_id}/reinstate", {}, headers
        )

    def withdraw_student(
        self, student_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/students/{student_id}/withdraw", payload, headers
        )

    def suspend_student(
        self, student_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/students/{student_id}/suspend", payload or {}, headers
        )

    def get_progress_summary(self, student_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/students/{student_id}/progress-summary", headers=headers
        )

    # ─── Subscription terms ───────────────────────────────────────────────
    def create_subscription_term(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subscription-terms", payload, headers)

    def get_subscription_term(self, term_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subscription-terms/{term_id}", headers=headers)

    def list_subscription_terms(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/subscription-terms", headers=headers, params=params
        )

    def activate_subscription_term(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscription-terms/{term_id}/activate", {}, headers
        )

    def close_subscription_term(
        self, term_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subscription-terms/{term_id}/close", payload, headers
        )

    # ─── Mentors ──────────────────────────────────────────────────────────
    def create_mentor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mentors", payload, headers)

    def get_mentor(self, mentor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mentors/{mentor_id}", headers=headers)

    def list_mentors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mentors", headers=headers, params=params)

    def set_mentor_status(
        self, mentor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mentors/{mentor_id}/status", payload, headers
        )

    # ─── Mentor assignments ───────────────────────────────────────────────
    def create_mentor_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mentor-assignments", payload, headers)

    def get_mentor_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mentor-assignments/{assignment_id}", headers=headers
        )

    def list_mentor_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mentor-assignments", headers=headers, params=params
        )

    def record_contact(
        self, assignment_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/mentor-assignments/{assignment_id}/contacts",
            payload or {}, headers,
        )

    def record_endorsement(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mentor-assignments/{assignment_id}/endorsements",
            payload, headers,
        )

    def end_mentor_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mentor-assignments/{assignment_id}/end", {}, headers
        )

    # ─── Evaluators ───────────────────────────────────────────────────────
    def create_evaluator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/evaluators", payload, headers)

    def get_evaluator(self, evaluator_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/evaluators/{evaluator_id}", headers=headers)

    def list_evaluators(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/evaluators", headers=headers, params=params)

    def set_evaluator_status(
        self, evaluator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/evaluators/{evaluator_id}/status", payload, headers
        )

    # ─── Assessment attempts ──────────────────────────────────────────────
    def create_attempt(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/assessment-attempts", payload, headers)

    def get_attempt(self, attempt_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/assessment-attempts/{attempt_id}", headers=headers
        )

    def list_attempts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/assessment-attempts", headers=headers, params=params
        )

    def submit_attempt(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assessment-attempts/{attempt_id}/submit", payload, headers
        )

    def record_score(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assessment-attempts/{attempt_id}/scores", payload, headers
        )

    def request_revision(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assessment-attempts/{attempt_id}/request-revision",
            payload, headers,
        )

    def reopen_attempt(self, attempt_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/assessment-attempts/{attempt_id}/reopen", {}, headers
        )

    # ─── Evaluator scores ─────────────────────────────────────────────────
    def get_evaluator_score(self, score_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/evaluator-scores/{score_id}", headers=headers)

    def list_evaluator_scores(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/evaluator-scores", headers=headers, params=params)

    # ─── Integrity cases ──────────────────────────────────────────────────
    def create_integrity_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/integrity-cases", payload, headers)

    def get_integrity_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity-cases/{case_id}", headers=headers)

    def list_integrity_cases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/integrity-cases", headers=headers, params=params)

    def investigate_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity-cases/{case_id}/investigate", {}, headers
        )

    def resolve_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity-cases/{case_id}/resolve", payload, headers
        )

    # ─── Satisfactory-academic-progress reviews ───────────────────────────
    def create_sap_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sap-reviews", payload, headers)

    def get_sap_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sap-reviews/{review_id}", headers=headers)

    def list_sap_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/sap-reviews", headers=headers, params=params)

    # ─── Aid disbursements ────────────────────────────────────────────────
    def create_aid_disbursement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/aid-disbursements", payload, headers)

    def get_aid_disbursement(self, disbursement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/aid-disbursements/{disbursement_id}", headers=headers
        )

    def list_aid_disbursements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/aid-disbursements", headers=headers, params=params
        )

    def disburse_aid(
        self, disbursement_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/aid-disbursements/{disbursement_id}/disburse",
            payload or {}, headers,
        )

    def return_aid(
        self, disbursement_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/aid-disbursements/{disbursement_id}/return",
            payload or {}, headers,
        )

    def cancel_aid(
        self, disbursement_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/aid-disbursements/{disbursement_id}/cancel",
            payload or {}, headers,
        )

    # ─── Transcript records ───────────────────────────────────────────────
    def create_transcript_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/transcript-records", payload, headers)

    def get_transcript_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transcript-records/{record_id}", headers=headers
        )

    def list_transcript_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/transcript-records", headers=headers, params=params
        )

    def issue_transcript_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transcript-records/{record_id}/issue", {}, headers
        )


api_client = ApiClient()
