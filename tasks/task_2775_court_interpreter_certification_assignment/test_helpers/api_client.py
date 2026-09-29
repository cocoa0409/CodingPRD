"""API client: one method per endpoint in PRD §4 (55 rows).

Subclasses GenericApiClient from prd_bench_local_runner.testing; the base
_request() does the HTTP work and returns the raw requests.Response so tests
can assert status codes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Languages ----------------
    def create_language(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/languages", payload, headers)

    def list_languages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/languages", headers=headers, params=params)

    def get_language(self, language_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/languages/{language_id}", headers=headers)

    # ---------------- Courthouses ----------------
    def create_courthouse(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/courthouses", payload, headers)

    def list_courthouses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/courthouses", headers=headers, params=params)

    def get_courthouse(self, courthouse_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/courthouses/{courthouse_id}", headers=headers)

    def patch_courthouse(self, courthouse_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("PATCH", f"/courthouses/{courthouse_id}", payload, headers)

    def list_courthouse_unmet_need_reports(self, courthouse_id: str,
                                           headers: Dict[str, str],
                                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/courthouses/{courthouse_id}/unmet-need-reports",
            headers=headers, params=params,
        )

    # ---------------- Rate schedules ----------------
    def create_rate_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, rate_schedule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rate-schedules/{rate_schedule_id}", headers=headers)

    # ---------------- Interpreters ----------------
    def create_interpreter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/interpreters", payload, headers)

    def list_interpreters(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/interpreters", headers=headers, params=params)

    def get_interpreter(self, interpreter_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/interpreters/{interpreter_id}", headers=headers)

    def record_ethics_training(self, interpreter_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/interpreters/{interpreter_id}/ethics-training", payload, headers
        )

    def get_quality_score(self, interpreter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/interpreters/{interpreter_id}/quality-score", headers=headers
        )

    # ---------------- Credentials ----------------
    def create_credential(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/credentials", payload, headers)

    def list_credentials(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def get_credential(self, credential_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def create_exam_attempt(self, credential_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/credentials/{credential_id}/exam-attempts", payload, headers
        )

    def list_exam_attempts(self, credential_id: str, headers: Dict[str, str],
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/credentials/{credential_id}/exam-attempts",
            headers=headers, params=params,
        )

    def advance_credential(self, credential_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/credentials/{credential_id}/advance", payload or {}, headers
        )

    def renew_credential(self, credential_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/credentials/{credential_id}/renew", payload, headers
        )

    def revoke_credential(self, credential_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/credentials/{credential_id}/revoke", payload, headers
        )

    # ---------------- Hearings ----------------
    def create_hearing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hearings", payload, headers)

    def list_hearings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def continue_hearing(self, hearing_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearings/{hearing_id}/continue", payload, headers
        )

    def list_eligible_interpreters(self, hearing_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/hearings/{hearing_id}/eligible-interpreters",
            headers=headers, params=params,
        )

    # ---------------- Assignments ----------------
    def create_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/confirm", payload or {}, headers
        )

    def decline_assignment(self, assignment_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/decline", payload, headers
        )

    def check_in_assignment(self, assignment_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/check-in", payload or {}, headers
        )

    def complete_assignment(self, assignment_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/complete", payload, headers
        )

    def cancel_assignment(self, assignment_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/cancel", payload, headers
        )

    def no_show_assignment(self, assignment_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/no-show", payload or {}, headers
        )

    # ---------------- Pay claims ----------------
    def list_pay_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pay-claims", headers=headers, params=params)

    def get_pay_claim(self, pay_claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pay-claims/{pay_claim_id}", headers=headers)

    def submit_pay_claim(self, pay_claim_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pay-claims/{pay_claim_id}/submit", payload or {}, headers
        )

    def approve_pay_claim(self, pay_claim_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pay-claims/{pay_claim_id}/approve", payload or {}, headers
        )

    def pay_pay_claim(self, pay_claim_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pay-claims/{pay_claim_id}/pay", payload, headers
        )

    # ---------------- Complaints ----------------
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def review_complaint(self, complaint_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/review", payload, headers
        )

    def adjudicate_complaint(self, complaint_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/adjudicate", payload, headers
        )

    def appeal_complaint(self, complaint_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/appeal", payload, headers
        )

    def decide_appeal(self, complaint_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/appeal-decision", payload, headers
        )

    # ---------------- Disciplinary actions ----------------
    def list_disciplinary_actions(self, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request("GET", "/disciplinary-actions", headers=headers, params=params)

    def get_disciplinary_action(self, action_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disciplinary-actions/{action_id}", headers=headers)

    # ---------------- Reporting and operations ----------------
    def create_unmet_need_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/unmet-need-reports", payload, headers)

    def run_daily_sweep(self, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/ops/daily-sweep", payload or {}, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
