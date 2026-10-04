"""API client: one method per endpoint defined in the PRD (§4).

All resources are mounted under the /actuarial prefix. Creation endpoints
return 201; action/read endpoints return 200 (PRD §4 preamble).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (PRD §2.4) ----
    def set_clock(self, payload, headers):
        """POST /actuarial/_clock/set_current_utc (200)."""
        return self._request("POST", "/actuarial/_clock/set_current_utc", payload, headers)

    # ---- Candidates (PRD §3.1) ----
    def create_candidate(self, payload, headers):
        """POST /actuarial/candidates (201)."""
        return self._request("POST", "/actuarial/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}", headers=headers)

    # ---- Syllabus versions (PRD §3.2) ----
    def create_syllabus_version(self, payload, headers):
        """POST /actuarial/syllabus-versions (201)."""
        return self._request("POST", "/actuarial/syllabus-versions", payload, headers)

    def activate_syllabus_version(self, syllabus_id, headers):
        return self._request("POST", f"/actuarial/syllabus-versions/{syllabus_id}/activate", {}, headers)

    def get_syllabus_version(self, syllabus_id, headers):
        return self._request("GET", f"/actuarial/syllabus-versions/{syllabus_id}", headers=headers)

    # ---- Exams (PRD §3.2) ----
    def create_exam(self, payload, headers):
        """POST /actuarial/exams (201)."""
        return self._request("POST", "/actuarial/exams", payload, headers)

    def get_exam(self, exam_id, headers):
        return self._request("GET", f"/actuarial/exams/{exam_id}", headers=headers)

    def list_exams(self, headers, params=None):
        return self._request("GET", "/actuarial/exams", headers=headers, params=params)

    # ---- Exam windows (PRD §3.3) ----
    def create_exam_window(self, payload, headers):
        """POST /actuarial/exam-windows (201)."""
        return self._request("POST", "/actuarial/exam-windows", payload, headers)

    def get_exam_window(self, window_id, headers):
        return self._request("GET", f"/actuarial/exam-windows/{window_id}", headers=headers)

    def list_exam_windows(self, headers, params=None):
        return self._request("GET", "/actuarial/exam-windows", headers=headers, params=params)

    # ---- Exam registrations (PRD §3.3) ----
    def create_exam_registration(self, payload, headers):
        """POST /actuarial/exam-registrations (201)."""
        return self._request("POST", "/actuarial/exam-registrations", payload, headers)

    def cancel_exam_registration(self, registration_id, headers):
        return self._request("POST", f"/actuarial/exam-registrations/{registration_id}/cancel", {}, headers)

    def record_score(self, registration_id, payload, headers):
        return self._request("POST", f"/actuarial/exam-registrations/{registration_id}/record-score", payload, headers)

    def list_candidate_registrations(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/registrations", headers=headers, params=params)

    def list_window_registrations(self, window_id, headers, params=None):
        return self._request("GET", f"/actuarial/exam-windows/{window_id}/registrations", headers=headers, params=params)

    # ---- Pass mark settings (PRD §3.3) ----
    def create_pass_mark_setting(self, window_id, payload, headers):
        """POST /actuarial/exam-windows/{wid}/pass-mark-settings (201, OCC)."""
        return self._request("POST", f"/actuarial/exam-windows/{window_id}/pass-mark-settings", payload, headers)

    def ratify_pass_mark(self, setting_id, payload, headers):
        return self._request("POST", f"/actuarial/pass-mark-settings/{setting_id}/ratify", payload, headers)

    def publish_pass_mark(self, setting_id, headers):
        return self._request("POST", f"/actuarial/pass-mark-settings/{setting_id}/publish", {}, headers)

    def list_pass_mark_settings(self, window_id, headers, params=None):
        return self._request("GET", f"/actuarial/exam-windows/{window_id}/pass-mark-settings", headers=headers, params=params)

    # ---- VEE submissions (PRD §3.4) ----
    def create_vee_submission(self, payload, headers):
        """POST /actuarial/vee-submissions (201)."""
        return self._request("POST", "/actuarial/vee-submissions", payload, headers)

    def review_vee_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/actuarial/vee-submissions/{submission_id}/review", payload, headers)

    def list_candidate_vee_submissions(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/vee-submissions", headers=headers, params=params)

    # ---- Track enrollments (PRD §3.5) ----
    def create_track_enrollment(self, payload, headers):
        """POST /actuarial/track-enrollments (201)."""
        return self._request("POST", "/actuarial/track-enrollments", payload, headers)

    def list_candidate_track_enrollments(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/track-enrollments", headers=headers, params=params)

    # ---- Modules (PRD §3.5) ----
    def create_module(self, payload, headers):
        """POST /actuarial/modules (201)."""
        return self._request("POST", "/actuarial/modules", payload, headers)

    # ---- Module attempts (PRD §3.5) ----
    def create_module_attempt(self, payload, headers):
        """POST /actuarial/module-attempts (201)."""
        return self._request("POST", "/actuarial/module-attempts", payload, headers)

    def submit_module_attempt(self, attempt_id, payload, headers):
        return self._request("POST", f"/actuarial/module-attempts/{attempt_id}/submit", payload, headers)

    def get_module_attempt(self, attempt_id, headers):
        return self._request("GET", f"/actuarial/module-attempts/{attempt_id}", headers=headers)

    def list_module_attempts(self, headers, params=None):
        return self._request("GET", "/actuarial/module-attempts", headers=headers, params=params)

    # ---- Project assessments (PRD §3.6) ----
    def create_project_assessment(self, payload, headers):
        """POST /actuarial/project-assessments (201)."""
        return self._request("POST", "/actuarial/project-assessments", payload, headers)

    def grade_project_assessment(self, project_id, payload, headers):
        return self._request("POST", f"/actuarial/project-assessments/{project_id}/grades", payload, headers)

    def get_project_assessment(self, project_id, headers):
        return self._request("GET", f"/actuarial/project-assessments/{project_id}", headers=headers)

    def list_project_assessments(self, headers, params=None):
        return self._request("GET", "/actuarial/project-assessments", headers=headers, params=params)

    # ---- Professionalism course (PRD §3.7) ----
    def create_course_session(self, payload, headers):
        """POST /actuarial/course-sessions (201)."""
        return self._request("POST", "/actuarial/course-sessions", payload, headers)

    def create_course_attendance(self, payload, headers):
        """POST /actuarial/course-attendances (201)."""
        return self._request("POST", "/actuarial/course-attendances", payload, headers)

    def verify_course_attendance(self, attendance_id, payload, headers):
        return self._request("POST", f"/actuarial/course-attendances/{attendance_id}/verify", payload, headers)

    def get_course_attendance(self, attendance_id, headers):
        return self._request("GET", f"/actuarial/course-attendances/{attendance_id}", headers=headers)

    def list_course_attendances(self, headers, params=None):
        return self._request("GET", "/actuarial/course-attendances", headers=headers, params=params)

    # ---- Transfer credit (PRD §3.8) ----
    def create_transfer_credit_request(self, payload, headers):
        """POST /actuarial/transfer-credit-requests (201)."""
        return self._request("POST", "/actuarial/transfer-credit-requests", payload, headers)

    def list_candidate_transfer_credit_requests(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/transfer-credit-requests", headers=headers, params=params)

    # ---- CPD attestations (PRD §3.8) ----
    def create_cpd_attestation(self, payload, headers):
        """POST /actuarial/cpd-attestations (201)."""
        return self._request("POST", "/actuarial/cpd-attestations", payload, headers)

    def verify_cpd_attestation(self, attestation_id, payload, headers):
        return self._request("POST", f"/actuarial/cpd-attestations/{attestation_id}/verify", payload, headers)

    def list_candidate_cpd_attestations(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/cpd-attestations", headers=headers, params=params)

    # ---- Discipline cases (PRD §3.9) ----
    def create_discipline_case(self, payload, headers):
        """POST /actuarial/discipline-cases (201)."""
        return self._request("POST", "/actuarial/discipline-cases", payload, headers)

    def sanction_discipline_case(self, case_id, payload, headers):
        return self._request("POST", f"/actuarial/discipline-cases/{case_id}/sanction", payload, headers)

    def list_candidate_discipline_cases(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/discipline-cases", headers=headers, params=params)

    # ---- Credential applications (PRD §3.9) ----
    def create_credential_application(self, payload, headers):
        """POST /actuarial/credential-applications (201, OCC)."""
        return self._request("POST", "/actuarial/credential-applications", payload, headers)

    def list_candidate_credential_applications(self, candidate_id, headers, params=None):
        return self._request("GET", f"/actuarial/candidates/{candidate_id}/credential-applications", headers=headers, params=params)


api_client = ApiClient()
