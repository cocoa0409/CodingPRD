"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Institutions ---
    def create_institution(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/integrity/institutions", payload, headers)

    def get_institution(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}", headers=headers)

    def patch_institution(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("PATCH", f"/integrity/institutions/{institution_id}", payload, headers)

    # --- LMS integrations ---
    def create_lms_integration(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/institutions/{institution_id}/lms-integrations", payload, headers)

    def list_lms_integrations(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/lms-integrations", headers=headers)

    def activate_integration(self, integration_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/lms-integrations/{integration_id}/activate", {}, headers)

    def suspend_integration(self, integration_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/lms-integrations/{integration_id}/suspend", {}, headers)

    # --- Instructors ---
    def create_instructor(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/institutions/{institution_id}/instructors", payload, headers)

    def list_instructors(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/instructors", headers=headers)

    # --- Students ---
    def create_student(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/institutions/{institution_id}/students", payload, headers)

    def list_students(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/students", headers=headers)

    def record_consent(self, student_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/students/{student_id}/consents", payload, headers)

    # --- Assignments ---
    def create_assignment(self, integration_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/lms-integrations/{integration_id}/assignments", payload, headers)

    def list_assignments_of_integration(self, integration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/lms-integrations/{integration_id}/assignments", headers=headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/integrity/assignments", headers=headers, params=params)

    def patch_assignment(self, assignment_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("PATCH", f"/integrity/assignments/{assignment_id}", payload, headers)

    # --- Submissions ---
    def create_submission(self, assignment_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/assignments/{assignment_id}/submissions", payload, headers)

    def list_submissions_of_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/assignments/{assignment_id}/submissions", headers=headers)

    def get_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/integrity/submissions", headers=headers, params=params)

    def process_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/submissions/{submission_id}/process", {}, headers)

    # --- Source documents ---
    def create_source_document(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/institutions/{institution_id}/source-documents", payload, headers)

    def list_source_documents(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/source-documents", headers=headers)

    def get_source_document(self, source_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/source-documents/{source_id}", headers=headers)

    def retract_source(self, source_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/source-documents/{source_id}/retract", {}, headers)

    # --- Match fragments ---
    def list_match_fragments_of_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}/match-fragments", headers=headers)

    def list_match_fragments_of_source(self, source_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/source-documents/{source_id}/match-fragments", headers=headers)

    def inject_match(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/integrity/_matches/inject", payload, headers)

    # --- Similarity reports ---
    def list_similarity_reports(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}/similarity-reports", headers=headers)

    def finalize_report(self, report_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/similarity-reports/{report_id}/finalize", payload, headers)

    # --- AI writing assessments ---
    def list_ai_assessments(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}/ai-writing-assessments", headers=headers)

    # --- Repository deposits ---
    def list_deposits_of_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}/repository-deposits", headers=headers)

    def list_deposits_of_institution(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/repository-deposits", headers=headers)

    def withdraw_deposit(self, deposit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/repository-deposits/{deposit_id}/withdraw", {}, headers)

    # --- Retention policies ---
    def create_retention_policy(self, institution_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/institutions/{institution_id}/retention-policies", payload, headers)

    def list_retention_policies(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/institutions/{institution_id}/retention-policies", headers=headers)

    def run_purge(self, policy_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/retention-policies/{policy_id}/run-purge", {}, headers)

    # --- Grade entries ---
    def create_grade_entry(self, submission_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/integrity/submissions/{submission_id}/grade-entries", payload, headers)

    def list_grade_entries(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/submissions/{submission_id}/grade-entries", headers=headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/integrity/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
