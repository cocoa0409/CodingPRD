"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test centers ---
    def create_test_center(self, payload, headers):
        return self._request("POST", "/ets/test-centers", payload, headers)

    def get_test_center(self, center_id, headers):
        return self._request("GET", f"/ets/test-centers/{center_id}", headers=headers)

    # --- Audits ---
    def create_audit(self, center_id, payload, headers):
        return self._request("POST", f"/ets/test-centers/{center_id}/audits", payload, headers)

    def list_audits(self, center_id, headers, params=None):
        return self._request("GET", f"/ets/test-centers/{center_id}/audits", headers=headers, params=params)

    def complete_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/ets/audits/{audit_id}/complete", payload, headers)

    # --- Staff ---
    def create_staff(self, center_id, payload, headers):
        return self._request("POST", f"/ets/test-centers/{center_id}/staff", payload, headers)

    def list_staff(self, center_id, headers, params=None):
        return self._request("GET", f"/ets/test-centers/{center_id}/staff", headers=headers, params=params)

    # --- Sessions ---
    def create_session(self, center_id, payload, headers):
        return self._request("POST", f"/ets/test-centers/{center_id}/sessions", payload, headers)

    def list_sessions(self, center_id, headers, params=None):
        return self._request("GET", f"/ets/test-centers/{center_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/ets/sessions/{session_id}", headers=headers)

    def publish_session(self, session_id, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/publish", headers=headers)

    def lock_session(self, session_id, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/lock", headers=headers)

    def administer_session(self, session_id, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/administer", headers=headers)

    def assign_proctor(self, session_id, payload, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/proctors", payload, headers)

    # --- Examinees ---
    def create_examinee(self, payload, headers):
        return self._request("POST", "/ets/examinees", payload, headers)

    def get_examinee(self, examinee_id, headers):
        return self._request("GET", f"/ets/examinees/{examinee_id}", headers=headers)

    def list_examinee_registrations(self, examinee_id, headers, params=None):
        return self._request("GET", f"/ets/examinees/{examinee_id}/registrations", headers=headers, params=params)

    # --- Accommodation requests ---
    def create_accommodation_request(self, examinee_id, payload, headers):
        return self._request("POST", f"/ets/examinees/{examinee_id}/accommodation-requests", payload, headers)

    def list_accommodation_requests(self, examinee_id, headers, params=None):
        return self._request("GET", f"/ets/examinees/{examinee_id}/accommodation-requests", headers=headers, params=params)

    def decide_accommodation_request(self, request_id, payload, headers):
        return self._request("POST", f"/ets/accommodation-requests/{request_id}/decide", payload, headers)

    # --- Registrations ---
    def create_registration(self, session_id, payload, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/registrations", payload, headers)

    def list_session_registrations(self, session_id, headers, params=None):
        return self._request("GET", f"/ets/sessions/{session_id}/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/ets/registrations/{registration_id}", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/ets/registrations/{registration_id}/cancel", headers=headers)

    # --- Check-in ---
    def check_in(self, registration_id, payload, headers):
        return self._request("POST", f"/ets/registrations/{registration_id}/check-in", payload, headers)

    def list_check_ins(self, registration_id, headers, params=None):
        return self._request("GET", f"/ets/registrations/{registration_id}/check-ins", headers=headers, params=params)

    # --- Irregularity reports ---
    def create_irregularity_report(self, session_id, payload, headers):
        return self._request("POST", f"/ets/sessions/{session_id}/irregularity-reports", payload, headers)

    def list_irregularity_reports(self, registration_id, headers, params=None):
        return self._request("GET", f"/ets/registrations/{registration_id}/irregularity-reports", headers=headers, params=params)

    def resolve_irregularity_report(self, report_id, payload, headers):
        return self._request("POST", f"/ets/irregularity-reports/{report_id}/resolve", payload, headers)

    # --- Scores ---
    def create_score_entry(self, registration_id, payload, headers):
        return self._request("POST", f"/ets/registrations/{registration_id}/score-entry", payload, headers)

    def get_registration_score(self, registration_id, headers):
        return self._request("GET", f"/ets/registrations/{registration_id}/score", headers=headers)

    def get_score_record(self, score_record_id, headers):
        return self._request("GET", f"/ets/score-records/{score_record_id}", headers=headers)

    def run_score_analysis(self, payload, headers):
        return self._request("POST", "/ets/score-analysis/run", payload, headers)

    # --- Score review cases ---
    def list_review_cases(self, registration_id, headers, params=None):
        return self._request("GET", f"/ets/registrations/{registration_id}/review-cases", headers=headers, params=params)

    def notify_case(self, case_id, headers):
        return self._request("POST", f"/ets/score-review-cases/{case_id}/notify", headers=headers)

    def respond_case(self, case_id, payload, headers):
        return self._request("POST", f"/ets/score-review-cases/{case_id}/respond", payload, headers)

    def adjudicate_case(self, case_id, payload, headers):
        return self._request("POST", f"/ets/score-review-cases/{case_id}/adjudicate", payload, headers)

    # --- Score reports ---
    def create_score_report(self, score_record_id, payload, headers):
        return self._request("POST", f"/ets/score-records/{score_record_id}/reports", payload, headers)

    def list_score_reports(self, score_record_id, headers, params=None):
        return self._request("GET", f"/ets/score-records/{score_record_id}/reports", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ets/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
