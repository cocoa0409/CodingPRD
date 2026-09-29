"""API client: one method per endpoint defined in the PRD.

All business paths are mounted under `/integrity`; the logical-clock endpoint
sits at `/_clock/set_current_utc`.
"""
import contextlib
import re
from typing import Any, Dict, List, Optional

import requests.models as _requests_models

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    The server mints audit timestamps with three fractional digits, but an
    equally faithful implementation may echo a client-supplied instant back
    with none, or with a trailing `+00:00` offset instead of `Z`.  Comparisons
    should therefore be precision-insensitive: run both sides of any instant
    comparison through this function.
    """
    if not isinstance(value, str):
        return value
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return value
    seconds, frac, _offset = m.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{seconds}.{frac}Z"


def instants_equal(left: Any, right: Any) -> bool:
    """True when two instants denote the same moment, ignoring sub-second width."""
    return canonical_instant(left) == canonical_instant(right)


@contextlib.contextmanager
def _allow_whitespace_only_headers(headers: Optional[Dict[str, str]]):
    """Let a deliberately whitespace-only header value reach the server.

    PRD §2.1 requires `ERR_UNAUTHENTICATED` when `X-User-Role` or `X-User-ID`
    carries "a value consisting only of spaces".  `requests` refuses, purely
    client-side, to serialise a header value that begins with whitespace, so
    without this bypass those two probes could never leave the test process at
    all.  Validation is suspended only for values that are entirely whitespace
    (so never for a value containing CR or LF), and is always restored.
    """
    needs_bypass = any(
        isinstance(value, str) and value != "" and value.strip() == ""
        for value in (headers or {}).values()
    )
    if not needs_bypass:
        yield
        return
    original = _requests_models.check_header_validity
    _requests_models.check_header_validity = lambda header: None
    try:
        yield
    finally:
        _requests_models.check_header_validity = original


class ApiClient(GenericApiClient):
    """One method per PRD endpoint.  `_request` is inherited from the framework."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        with _allow_whitespace_only_headers(headers):
            return super()._request(method, path, payload, headers, params)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------

    def create_department(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/departments", payload, headers)

    def list_departments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/departments", headers=headers, params=params
        )

    def get_department(self, department_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/departments/{department_id}", headers=headers
        )

    def get_department_reporting_metrics(
        self, department_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/integrity/departments/{department_id}/reporting-metrics",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Faculty members
    # ------------------------------------------------------------------

    def create_faculty_member(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/faculty-members", payload, headers)

    def list_faculty_members(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/faculty-members", headers=headers, params=params
        )

    def get_faculty_member(self, faculty_member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/faculty-members/{faculty_member_id}", headers=headers
        )

    def create_training_completion(
        self, faculty_member_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/integrity/faculty-members/{faculty_member_id}/training-completions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------

    def create_student(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/students", payload, headers)

    def list_students(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/students", headers=headers, params=params
        )

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/students/{student_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Course offerings
    # ------------------------------------------------------------------

    def create_course_offering(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/course-offerings", payload, headers)

    def list_course_offerings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/course-offerings", headers=headers, params=params
        )

    def get_course_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/course-offerings/{offering_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Integrity reports
    # ------------------------------------------------------------------

    def create_report(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/reports", payload, headers)

    def list_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/integrity/reports", headers=headers, params=params)

    def get_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/reports/{report_id}", headers=headers)

    def submit_report(self, report_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/integrity/reports/{report_id}/submit", payload, headers
        )

    def triage_report(self, report_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity/reports/{report_id}/triage", payload, headers
        )

    # ------------------------------------------------------------------
    # Evidence items
    # ------------------------------------------------------------------

    def create_evidence_item(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/evidence-items", payload, headers)

    def list_evidence_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/evidence-items", headers=headers, params=params
        )

    def get_evidence_item(self, evidence_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/evidence-items/{evidence_item_id}", headers=headers
        )

    def list_report_evidence_items(
        self, report_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/integrity/reports/{report_id}/evidence-items",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------

    def create_case(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/cases", payload, headers)

    def legacy_import_case(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", "/integrity/cases/legacy-import", payload, headers
        )

    def list_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/integrity/cases", headers=headers, params=params)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/cases/{case_id}", headers=headers)

    def set_case_pathway(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/pathway", payload, headers
        )

    def get_severity_assessment(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/integrity/cases/{case_id}/severity-assessment",
            headers=headers,
            params=params,
        )

    def dismiss_case(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/dismiss", payload, headers
        )

    def create_informal_resolution(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/informal-resolution", payload, headers
        )

    def create_informal_response(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/informal-response", payload, headers
        )

    # ------------------------------------------------------------------
    # Transcript notation
    # ------------------------------------------------------------------

    def post_notation(self, case_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/notation/post", payload, headers
        )

    def request_expungement(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/integrity/cases/{case_id}/notation/expungement-request",
            payload,
            headers,
        )

    def decide_expungement(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/integrity/cases/{case_id}/notation/expungement-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def create_case_notification(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/cases/{case_id}/notifications", payload, headers
        )

    def list_case_notifications(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/integrity/cases/{case_id}/notifications",
            headers=headers,
            params=params,
        )

    def list_notifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/notifications", headers=headers, params=params
        )

    def get_notification(self, notification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/notifications/{notification_id}", headers=headers
        )

    def acknowledge_notification(
        self, notification_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/integrity/notifications/{notification_id}/acknowledge",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Advisor engagements
    # ------------------------------------------------------------------

    def create_advisor_engagement(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", "/integrity/advisor-engagements", payload, headers
        )

    def list_advisor_engagements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/advisor-engagements", headers=headers, params=params
        )

    def get_advisor_engagement(self, engagement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/advisor-engagements/{engagement_id}", headers=headers
        )

    def list_case_advisor_engagements(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/integrity/cases/{case_id}/advisor-engagements",
            headers=headers,
            params=params,
        )

    def review_advisor_engagement(
        self, engagement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/integrity/advisor-engagements/{engagement_id}/review",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Case meetings
    # ------------------------------------------------------------------

    def create_case_meeting(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/case-meetings", payload, headers)

    def list_case_meetings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/case-meetings", headers=headers, params=params
        )

    def get_case_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/case-meetings/{meeting_id}", headers=headers
        )

    def record_meeting_outcome(
        self, meeting_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/case-meetings/{meeting_id}/outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # Hearing rooms
    # ------------------------------------------------------------------

    def create_hearing_room(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/hearing-rooms", payload, headers)

    def list_hearing_rooms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/hearing-rooms", headers=headers, params=params
        )

    def get_hearing_room(self, room_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/hearing-rooms/{room_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Hearing sessions
    # ------------------------------------------------------------------

    def create_hearing_session(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/hearing-sessions", payload, headers)

    def list_hearing_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/integrity/hearing-sessions", headers=headers, params=params
        )

    def get_hearing_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/hearing-sessions/{session_id}", headers=headers
        )

    def convene_hearing_session(
        self, session_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/integrity/hearing-sessions/{session_id}/convene", payload, headers
        )

    def adjourn_hearing_session(
        self, session_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/hearing-sessions/{session_id}/adjourn", payload, headers
        )

    def decide_hearing_session(
        self, session_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/integrity/hearing-sessions/{session_id}/decide", payload, headers
        )

    def cancel_hearing_session(
        self, session_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/integrity/hearing-sessions/{session_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Panel votes
    # ------------------------------------------------------------------

    def create_panel_vote(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/panel-votes", payload, headers)

    def list_panel_votes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/panel-votes", headers=headers, params=params
        )

    def get_panel_vote(self, vote_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/panel-votes/{vote_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Sanctions
    # ------------------------------------------------------------------

    def create_sanction(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/sanctions", payload, headers)

    def list_sanctions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/integrity/sanctions", headers=headers, params=params
        )

    def get_sanction(self, sanction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/integrity/sanctions/{sanction_id}", headers=headers
        )

    def impose_sanction(
        self, sanction_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/integrity/sanctions/{sanction_id}/impose", payload, headers
        )

    def complete_sanction(
        self, sanction_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/integrity/sanctions/{sanction_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------

    def create_appeal(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/integrity/appeals", payload, headers)

    def list_appeals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/integrity/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/integrity/appeals/{appeal_id}", headers=headers)

    def list_case_appeals(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/integrity/cases/{case_id}/appeals", headers=headers, params=params
        )

    def screen_appeal(self, appeal_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity/appeals/{appeal_id}/screen", payload, headers
        )

    def decide_appeal(self, appeal_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/integrity/appeals/{appeal_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Generic raw helpers (for method-not-allowed / unknown-path probes)
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
