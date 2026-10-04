"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/housing-network/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/housing-network/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/housing-network/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/housing-network/members/{member_id}", headers=headers)

    def begin_assessment(self, member_id, headers):
        return self._request("POST", f"/housing-network/members/{member_id}/begin-assessment", {}, headers)

    def charter_member(self, member_id, headers):
        return self._request("POST", f"/housing-network/members/{member_id}/charter", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/housing-network/members/{member_id}/reinstate", {}, headers)

    def revoke_member(self, member_id, payload, headers):
        return self._request("POST", f"/housing-network/members/{member_id}/revoke", payload, headers)

    # --- assessments ---
    def list_assessments(self, headers, params=None):
        return self._request("GET", "/housing-network/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/housing-network/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/housing-network/assessments/{assessment_id}/submit", payload, headers)

    def score_assessment(self, assessment_id, headers):
        return self._request("POST", f"/housing-network/assessments/{assessment_id}/score", {}, headers)

    def adjudicate_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/housing-network/assessments/{assessment_id}/adjudicate", payload, headers)

    def withdraw_assessment(self, assessment_id, headers):
        return self._request("POST", f"/housing-network/assessments/{assessment_id}/withdraw", {}, headers)

    # --- counselors ---
    def create_counselor(self, payload, headers):
        return self._request("POST", "/housing-network/counselors", payload, headers)

    def list_counselors(self, headers, params=None):
        return self._request("GET", "/housing-network/counselors", headers=headers, params=params)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/housing-network/counselors/{counselor_id}", headers=headers)

    def suspend_counselor(self, counselor_id, headers):
        return self._request("POST", f"/housing-network/counselors/{counselor_id}/suspend", {}, headers)

    def reactivate_counselor(self, counselor_id, headers):
        return self._request("POST", f"/housing-network/counselors/{counselor_id}/reactivate", {}, headers)

    def separate_counselor(self, counselor_id, headers):
        return self._request("POST", f"/housing-network/counselors/{counselor_id}/separate", {}, headers)

    # --- courses & enrollments ---
    def create_course(self, payload, headers):
        return self._request("POST", "/housing-network/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/housing-network/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/housing-network/courses/{course_id}", headers=headers)

    def list_course_enrollments(self, course_id, headers, params=None):
        return self._request("GET", f"/housing-network/courses/{course_id}/enrollments", headers=headers, params=params)

    def cancel_course(self, course_id, headers):
        return self._request("POST", f"/housing-network/courses/{course_id}/cancel", {}, headers)

    def create_enrollment(self, course_id, payload, headers):
        return self._request("POST", f"/housing-network/courses/{course_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/housing-network/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/housing-network/enrollments", headers=headers, params=params)

    def grade_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/housing-network/enrollments/{enrollment_id}/grade", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/housing-network/enrollments/{enrollment_id}/withdraw", {}, headers)

    # --- certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/housing-network/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/housing-network/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/housing-network/certifications/{certification_id}", headers=headers)

    def certify_certification(self, certification_id, headers):
        return self._request("POST", f"/housing-network/certifications/{certification_id}/certify", {}, headers)

    def evaluate_continuing_requirement(self, certification_id, headers):
        return self._request(
            "POST", f"/housing-network/certifications/{certification_id}/evaluate-continuing-requirement",
            {}, headers,
        )

    def reinstate_certification(self, certification_id, headers):
        return self._request("POST", f"/housing-network/certifications/{certification_id}/reinstate", {}, headers)

    # --- grant cycles & applications ---
    def create_grant_cycle(self, payload, headers):
        return self._request("POST", "/housing-network/grant-cycles", payload, headers)

    def list_grant_cycles(self, headers, params=None):
        return self._request("GET", "/housing-network/grant-cycles", headers=headers, params=params)

    def get_grant_cycle(self, cycle_id, headers):
        return self._request("GET", f"/housing-network/grant-cycles/{cycle_id}", headers=headers)

    def lock_formula(self, cycle_id, headers):
        return self._request("POST", f"/housing-network/grant-cycles/{cycle_id}/lock-formula", {}, headers)

    def open_competitive_review(self, cycle_id, headers):
        return self._request("POST", f"/housing-network/grant-cycles/{cycle_id}/open-competitive-review", {}, headers)

    def finalize_cycle(self, cycle_id, headers):
        return self._request("POST", f"/housing-network/grant-cycles/{cycle_id}/finalize", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/housing-network/grant-cycles/{cycle_id}/close", {}, headers)

    def create_grant_application(self, payload, headers):
        return self._request("POST", "/housing-network/grant-applications", payload, headers)

    def list_grant_applications(self, headers, params=None):
        return self._request("GET", "/housing-network/grant-applications", headers=headers, params=params)

    def get_grant_application(self, application_id, headers):
        return self._request("GET", f"/housing-network/grant-applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/housing-network/grant-applications/{application_id}/submit", {}, headers)

    def score_application(self, application_id, payload, headers):
        return self._request("POST", f"/housing-network/grant-applications/{application_id}/score", payload, headers)

    def award_application(self, application_id, headers):
        return self._request("POST", f"/housing-network/grant-applications/{application_id}/award", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/housing-network/grant-applications/{application_id}/decline", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/housing-network/grant-applications/{application_id}/withdraw", {}, headers)

    # --- awards & disbursements ---
    def list_grant_awards(self, headers, params=None):
        return self._request("GET", "/housing-network/grant-awards", headers=headers, params=params)

    def get_grant_award(self, award_id, headers):
        return self._request("GET", f"/housing-network/grant-awards/{award_id}", headers=headers)

    def verify_match(self, award_id, payload, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/verify-match", payload, headers)

    def activate_award(self, award_id, payload, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/activate", payload, headers)

    def suspend_award(self, award_id, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/suspend", {}, headers)

    def resume_award(self, award_id, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/resume", {}, headers)

    def reconcile_award(self, award_id, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/reconcile", {}, headers)

    def close_award(self, award_id, headers):
        return self._request("POST", f"/housing-network/grant-awards/{award_id}/close", {}, headers)

    def create_disbursement(self, payload, headers):
        return self._request("POST", "/housing-network/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/housing-network/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/housing-network/disbursements/{disbursement_id}", headers=headers)

    def post_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/housing-network/disbursements/{disbursement_id}/post", {}, headers)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/housing-network/disbursements/{disbursement_id}/void", {}, headers)

    # --- client files & reviews ---
    def create_client_file(self, payload, headers):
        return self._request("POST", "/housing-network/client-files", payload, headers)

    def list_client_files(self, headers, params=None):
        return self._request("GET", "/housing-network/client-files", headers=headers, params=params)

    def get_client_file(self, client_file_id, headers):
        return self._request("GET", f"/housing-network/client-files/{client_file_id}", headers=headers)

    def begin_counseling(self, client_file_id, headers):
        return self._request("POST", f"/housing-network/client-files/{client_file_id}/begin-counseling", {}, headers)

    def record_outcome(self, client_file_id, payload, headers):
        return self._request("POST", f"/housing-network/client-files/{client_file_id}/record-outcome", payload, headers)

    def close_client_file(self, client_file_id, headers):
        return self._request("POST", f"/housing-network/client-files/{client_file_id}/close", {}, headers)

    def create_file_review(self, payload, headers):
        return self._request("POST", "/housing-network/file-reviews", payload, headers)

    def list_file_reviews(self, headers, params=None):
        return self._request("GET", "/housing-network/file-reviews", headers=headers, params=params)

    def get_file_review(self, review_id, headers):
        return self._request("GET", f"/housing-network/file-reviews/{review_id}", headers=headers)

    def pass_file_review(self, review_id, headers):
        return self._request("POST", f"/housing-network/file-reviews/{review_id}/pass", {}, headers)

    def fail_file_review(self, review_id, payload, headers):
        return self._request("POST", f"/housing-network/file-reviews/{review_id}/fail", payload, headers)

    def remediate_file_review(self, review_id, headers):
        return self._request("POST", f"/housing-network/file-reviews/{review_id}/remediate", {}, headers)

    # --- expenditure & audit ---
    def create_expenditure_report(self, payload, headers):
        return self._request("POST", "/housing-network/expenditure-reports", payload, headers)

    def list_expenditure_reports(self, headers, params=None):
        return self._request("GET", "/housing-network/expenditure-reports", headers=headers, params=params)

    def get_expenditure_report(self, report_id, headers):
        return self._request("GET", f"/housing-network/expenditure-reports/{report_id}", headers=headers)

    def accept_expenditure_report(self, report_id, headers):
        return self._request("POST", f"/housing-network/expenditure-reports/{report_id}/accept", {}, headers)

    def flag_expenditure_report(self, report_id, headers):
        return self._request("POST", f"/housing-network/expenditure-reports/{report_id}/flag", {}, headers)

    def list_compliance_audits(self, headers, params=None):
        return self._request("GET", "/housing-network/compliance-audits", headers=headers, params=params)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/housing-network/compliance-audits/{audit_id}", headers=headers)

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/housing-network/compliance-audits/{audit_id}/issue-findings", payload, headers)

    def resolve_audit(self, audit_id, headers):
        return self._request("POST", f"/housing-network/compliance-audits/{audit_id}/resolve", {}, headers)

    def escalate_audit(self, audit_id, headers):
        return self._request("POST", f"/housing-network/compliance-audits/{audit_id}/escalate", {}, headers)

    def reopen_audit(self, audit_id, headers):
        return self._request("POST", f"/housing-network/compliance-audits/{audit_id}/reopen", {}, headers)

    # --- performance reviews & congressional reporting ---
    def create_performance_review(self, payload, headers):
        return self._request("POST", "/housing-network/performance-reviews", payload, headers)

    def list_performance_reviews(self, headers, params=None):
        return self._request("GET", "/housing-network/performance-reviews", headers=headers, params=params)

    def get_performance_review(self, review_id, headers):
        return self._request("GET", f"/housing-network/performance-reviews/{review_id}", headers=headers)

    def score_performance_review(self, review_id, payload, headers):
        return self._request("POST", f"/housing-network/performance-reviews/{review_id}/score", payload, headers)

    def resolve_performance_review(self, review_id, payload, headers):
        return self._request("POST", f"/housing-network/performance-reviews/{review_id}/resolve", payload, headers)

    def close_corrective_plan(self, review_id, headers):
        return self._request("POST", f"/housing-network/performance-reviews/{review_id}/close-plan", {}, headers)

    def escalate_performance_review(self, review_id, headers):
        return self._request("POST", f"/housing-network/performance-reviews/{review_id}/escalate", {}, headers)

    def get_congressional_report(self, fiscal_year, headers):
        return self._request(
            "GET", "/housing-network/reports/congressional",
            headers=headers, params={"fiscal_year": fiscal_year},
        )


api_client = ApiClient()
