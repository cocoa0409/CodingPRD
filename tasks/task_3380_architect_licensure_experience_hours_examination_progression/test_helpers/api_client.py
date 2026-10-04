"""API client: one method per endpoint defined in PRD §4 (all under /licensure)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ops / clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/licensure/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_expiry_sweep(self, headers):
        return self._request(
            "POST", "/licensure/_maintenance/run_expiry_sweep", {}, headers
        )

    # --- candidates (PRD §3.1, §3.3) ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/licensure/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}", headers=headers
        )

    def get_candidate_summary(self, candidate_id, headers):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/summary", headers=headers
        )

    # --- jurisdictions (PRD §3.1) ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/licensure/jurisdictions", payload, headers)

    def update_jurisdiction(self, jurisdiction_id, payload, headers):
        return self._request(
            "PATCH", f"/licensure/jurisdictions/{jurisdiction_id}", payload, headers
        )

    # --- supervisors (PRD §3.1) ---
    def create_supervisor(self, payload, headers):
        return self._request("POST", "/licensure/supervisors", payload, headers)

    def update_supervisor(self, supervisor_id, payload, headers):
        return self._request(
            "PATCH", f"/licensure/supervisors/{supervisor_id}", payload, headers
        )

    # --- education evaluations (PRD §3.2) ---
    def create_education_evaluation(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"/licensure/candidates/{candidate_id}/education-evaluations",
            payload, headers,
        )

    def list_education_evaluations(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/education-evaluations",
            headers=headers, params=params,
        )

    def review_education_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/licensure/education-evaluations/{evaluation_id}/review",
            payload, headers,
        )

    def resubmit_education_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/licensure/education-evaluations/{evaluation_id}/resubmit",
            payload, headers,
        )

    # --- experience reports (PRD §3.3) ---
    def create_experience_report(self, payload, headers):
        return self._request(
            "POST", "/licensure/experience-reports", payload, headers
        )

    def get_experience_report(self, report_id, headers):
        return self._request(
            "GET", f"/licensure/experience-reports/{report_id}", headers=headers
        )

    def list_experience_reports(self, headers, params=None):
        return self._request(
            "GET", "/licensure/experience-reports", headers=headers, params=params
        )

    def submit_experience_report(self, report_id, headers):
        return self._request(
            "POST", f"/licensure/experience-reports/{report_id}/submit", {}, headers
        )

    def verify_experience_report(self, report_id, headers):
        return self._request(
            "POST", f"/licensure/experience-reports/{report_id}/verify", {}, headers
        )

    def return_experience_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensure/experience-reports/{report_id}/return",
            payload, headers,
        )

    def reassign_experience_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensure/experience-reports/{report_id}/reassign",
            payload, headers,
        )

    # --- examination (PRD §3.4) ---
    def create_exam_authorization(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"/licensure/candidates/{candidate_id}/exam-authorizations",
            payload, headers,
        )

    def list_exam_progress(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/exam-progress",
            headers=headers, params=params,
        )

    def schedule_exam_division(self, progress_id, payload, headers):
        return self._request(
            "POST", f"/licensure/exam-progress/{progress_id}/schedule",
            payload, headers,
        )

    def report_exam_score(self, progress_id, payload, headers):
        return self._request(
            "POST", f"/licensure/exam-progress/{progress_id}/report-score",
            payload, headers,
        )

    # --- supplemental examinations (PRD §3.5) ---
    def create_supplemental_exam(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"/licensure/candidates/{candidate_id}/supplemental-exams",
            payload, headers,
        )

    def list_supplemental_exams(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/supplemental-exams",
            headers=headers, params=params,
        )

    def report_supplemental_result(self, supplemental_id, payload, headers):
        return self._request(
            "POST", f"/licensure/supplemental-exams/{supplemental_id}/report-result",
            payload, headers,
        )

    # --- certificates (PRD §3.6, §3.7) ---
    def issue_certificate(self, candidate_id, headers):
        return self._request(
            "POST", f"/licensure/candidates/{candidate_id}/certificate", {}, headers
        )

    def get_candidate_certificate(self, candidate_id, headers):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/certificate",
            headers=headers,
        )

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/licensure/certificates/{certificate_id}", headers=headers
        )

    def renew_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/licensure/certificates/{certificate_id}/renew", {}, headers
        )

    def create_ce_entry(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/licensure/certificates/{certificate_id}/ce-entries",
            payload, headers,
        )

    def list_ce_entries(self, certificate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/certificates/{certificate_id}/ce-entries",
            headers=headers, params=params,
        )

    def void_ce_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/licensure/ce-entries/{entry_id}/void", {}, headers
        )

    # --- transmittals (PRD §3.8) ---
    def create_transmittal(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/licensure/certificates/{certificate_id}/transmittals",
            payload, headers,
        )

    def list_transmittals(self, certificate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/certificates/{certificate_id}/transmittals",
            headers=headers, params=params,
        )

    def decide_transmittal(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"/licensure/transmittals/{transmittal_id}/decide",
            payload, headers,
        )

    # --- disciplinary reports (PRD §3.8) ---
    def create_disciplinary_report(self, payload, headers):
        return self._request(
            "POST", "/licensure/disciplinary-reports", payload, headers
        )

    def resolve_disciplinary_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensure/disciplinary-reports/{report_id}/resolve",
            payload, headers,
        )

    def list_disciplinary_reports(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/licensure/candidates/{candidate_id}/disciplinary-reports",
            headers=headers, params=params,
        )


api_client = ApiClient()
