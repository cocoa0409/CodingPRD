"""HTTP client for the Service Corps Placement API.

One method per endpoint the PRD declares. Every method returns the raw
response so a test can assert on the status code as well as the body. Request
bodies are passed as ``payload``; query filters and pagination as ``params``.
All resources live under the ``/corps`` prefix.

``headers=None`` sends no auth headers at all, which is how the unauthenticated
probe drives the missing-credentials path.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/_clock/set_current_utc", payload, headers)

    # ── Sites ──────────────────────────────────────────────────────────────

    def create_site(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/sites", payload, headers)

    def get_site(self, site_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/corps/sites/{site_id}", None, headers)

    def transition_site(self, site_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/sites/{site_id}/state", payload, headers)

    def receive_funding(self, site_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/sites/{site_id}/funding/receive", payload, headers)

    # ── Schools ────────────────────────────────────────────────────────────

    def create_school(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/schools", payload, headers)

    def get_school(self, school_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/corps/schools/{school_id}", None, headers)

    def amend_school(self, school_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/schools/{school_id}/amend", payload, headers)

    def transition_school(self, school_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/schools/{school_id}/state", payload, headers)

    # ── Applications ───────────────────────────────────────────────────────

    def create_application(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/applications", payload, headers)

    def transition_application(self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/applications/{application_id}/state", payload, headers)

    # ── Corps members ──────────────────────────────────────────────────────

    def get_member(self, member_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/corps/members/{member_id}", None, headers)

    def transition_member(self, member_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/members/{member_id}/state", payload, headers)

    def exit_member(self, member_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/members/{member_id}/exit", payload, headers)

    # ── Teams and assignments ──────────────────────────────────────────────

    def create_team(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/teams", payload, headers)

    def get_team(self, team_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/corps/teams/{team_id}", None, headers)

    def transition_team(self, team_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/teams/{team_id}/state", payload, headers)

    def create_assignment(self, team_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/teams/{team_id}/assignments", payload, headers)

    def end_assignment(self, assignment_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/team-assignments/{assignment_id}/end", payload or {}, headers)

    # ── Students ───────────────────────────────────────────────────────────

    def create_student(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/students", payload, headers)

    def transition_student(self, student_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/students/{student_id}/state", payload, headers)

    def caseload_student(self, student_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/students/{student_id}/caseload", payload, headers)

    def post_student_metrics(self, student_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/students/{student_id}/metrics", payload, headers)

    # ── Service hour entries ───────────────────────────────────────────────

    def create_hour_entry(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/hour-entries", payload, headers)

    def review_hour_entry(self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/hour-entries/{entry_id}/review", payload, headers)

    # ── Stipend payments ───────────────────────────────────────────────────

    def create_stipend_payment(self, member_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/members/{member_id}/stipend-payments", payload, headers)

    def transition_stipend_payment(self, payment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/stipend-payments/{payment_id}/state", payload, headers)

    # ── Evaluation reports ─────────────────────────────────────────────────

    def create_evaluation_report(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corps/evaluation-reports", payload, headers)

    def transition_evaluation_report(self, report_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corps/evaluation-reports/{report_id}/state", payload, headers)

    # ── Listings (reverse-reachability reads) ──────────────────────────────

    def list_site_schools(self, site_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/sites/{site_id}/schools", None, headers, params)

    def list_site_applications(self, site_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/sites/{site_id}/applications", None, headers, params)

    def list_site_members(self, site_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/sites/{site_id}/members", None, headers, params)

    def list_school_teams(self, school_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/schools/{school_id}/teams", None, headers, params)

    def list_team_assignments(self, team_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/teams/{team_id}/assignments", None, headers, params)

    def list_member_assignments(self, member_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/members/{member_id}/assignments", None, headers, params)

    def list_school_students(self, school_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/schools/{school_id}/students", None, headers, params)

    def list_member_students(self, member_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/members/{member_id}/students", None, headers, params)

    def list_member_hour_entries(self, member_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/members/{member_id}/hour-entries", None, headers, params)

    def list_member_stipend_payments(self, member_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/members/{member_id}/stipend-payments", None, headers, params)

    def list_school_evaluation_reports(self, school_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/corps/schools/{school_id}/evaluation-reports", None, headers, params)


api_client = ApiClient()
