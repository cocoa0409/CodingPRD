"""HTTP client for the Police Professional Standards & Early Intervention API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination are passed as ``params``; request bodies as ``payload``.

The API has no path prefix, so paths are used exactly as the contract writes
them.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form -
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` - instead of on the raw strings, so that
    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` compare equal.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Units ──────────────────────────────────────────────────────────────

    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/units/{unit_id}", None, headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/units", params, headers)

    # ── Hearing rooms ──────────────────────────────────────────────────────

    def create_hearing_room(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/hearing-rooms", payload, headers)

    def get_hearing_room(self, room_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/hearing-rooms/{room_id}", None, headers)

    def list_hearing_rooms(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/hearing-rooms", params, headers)

    # ── Officers ───────────────────────────────────────────────────────────

    def create_officer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/officers", payload, headers)

    def get_officer(self, officer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/officers/{officer_id}", None, headers)

    def list_officers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/officers", params, headers)

    def set_employment_status(
        self, officer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/officers/{officer_id}/employment-status", payload, headers)

    def create_activity_event(
        self, officer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/officers/{officer_id}/activity-events", payload, headers)

    def list_activity_events(
        self, officer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/officers/{officer_id}/activity-events", params, headers)

    def get_eis_profile(
        self, officer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/officers/{officer_id}/eis-profile", params, headers)

    # ── Complaints ─────────────────────────────────────────────────────────

    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/complaints/{complaint_id}", None, headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/complaints", params, headers)

    def create_allegation(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/complaints/{complaint_id}/allegations", payload, headers)

    def classify_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/complaints/{complaint_id}/classify", payload, headers)

    def withdraw_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/complaints/{complaint_id}/withdraw", payload, headers)

    def purge_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/complaints/{complaint_id}/purge", payload, headers)

    def open_investigation(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/complaints/{complaint_id}/investigations", payload, headers)

    # ── Allegations ────────────────────────────────────────────────────────

    def get_allegation(self, allegation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/allegations/{allegation_id}", None, headers)

    def list_allegations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/allegations", params, headers)

    def dispose_allegation(
        self, allegation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/allegations/{allegation_id}/disposition", payload, headers)

    # ── Investigations ─────────────────────────────────────────────────────

    def get_investigation(self, investigation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/investigations/{investigation_id}", None, headers)

    def list_investigations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/investigations", params, headers)

    def assign_investigation(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/investigations/{investigation_id}/assignments", payload, headers)

    def toll_investigation(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/investigations/{investigation_id}/tolling", payload, headers)

    def submit_findings(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/investigations/{investigation_id}/findings", payload, headers)

    def close_investigation(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/investigations/{investigation_id}/close", payload, headers)

    def schedule_interview_session(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/investigations/{investigation_id}/interview-sessions", payload, headers
        )

    # ── Interview sessions ─────────────────────────────────────────────────

    def get_interview_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/interview-sessions/{session_id}", None, headers)

    def list_interview_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/interview-sessions", params, headers)

    def hold_interview_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/interview-sessions/{session_id}/hold", payload, headers)

    def postpone_interview_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/interview-sessions/{session_id}/postpone", payload, headers)

    # ── Discipline ─────────────────────────────────────────────────────────

    def get_discipline(self, discipline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/disciplines/{discipline_id}", None, headers)

    def list_disciplines(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/disciplines", params, headers)

    def impose_discipline(
        self, discipline_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/disciplines/{discipline_id}/impose", payload, headers)

    def file_appeal(
        self, discipline_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/disciplines/{discipline_id}/appeals", payload, headers)

    # ── Appeals and reinstatements ─────────────────────────────────────────

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}", None, headers)

    def list_appeals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/appeals", params, headers)

    def hear_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/hear", payload, headers)

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    def list_appeal_reinstatements(
        self, appeal_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}/reinstatements", params, headers)

    def finalize_reinstatement(
        self, reinstatement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/reinstatements/{reinstatement_id}/finalize", payload, headers)

    # ── Early intervention ─────────────────────────────────────────────────

    def run_eis_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/eis-runs", payload, headers)

    def get_eis_alert(self, alert_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/eis-alerts/{alert_id}", None, headers)

    def list_eis_alerts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/eis-alerts", params, headers)

    def dismiss_eis_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/eis-alerts/{alert_id}/dismiss", payload, headers)

    def create_intervention_plan(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/eis-alerts/{alert_id}/intervention-plans", payload, headers)

    # ── Intervention plans and check-ins ───────────────────────────────────

    def get_intervention_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/intervention-plans/{plan_id}", None, headers)

    def list_intervention_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/intervention-plans", params, headers)

    def activate_intervention_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/intervention-plans/{plan_id}/activate", payload, headers)

    def list_plan_check_ins(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/intervention-plans/{plan_id}/check-ins", params, headers)

    def complete_check_in(
        self, check_in_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/check-ins/{check_in_id}/complete", payload, headers)

    def close_intervention_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/intervention-plans/{plan_id}/close", payload, headers)

    # ── Credibility disclosures ────────────────────────────────────────────

    def get_credibility_disclosure(self, disclosure_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/credibility-disclosures/{disclosure_id}", None, headers)

    def list_credibility_disclosures(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/credibility-disclosures", params, headers)

    def release_credibility_disclosure(
        self, disclosure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/credibility-disclosures/{disclosure_id}/release", payload, headers)

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_complaint_outcome_report(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/reports/complaint-outcomes", params, headers)

    # ── Raw request escape hatch ───────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers)
