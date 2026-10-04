"""HTTP client for the Host Railroad Dispatch API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination go through ``params``; request bodies go through ``payload``.

The API is mounted under the ``/rail`` prefix, and paths are used exactly as
the contract writes them.
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
    ``2026-09-02T08:27:00Z`` and ``2026-09-02T08:27:00.000Z`` compare equal.
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

    # -- Logical clock -------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/_clock/set_current_utc", payload, headers)

    # -- Host railroads ------------------------------------------------------

    def create_host_railroad(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/host-railroads", payload, headers)

    def get_host_railroad(self, host_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/host-railroads/{host_id}", None, headers)

    # -- Corridors -----------------------------------------------------------

    def create_corridor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/corridors", payload, headers)

    def list_corridors(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/corridors", params, headers)

    def get_corridor(self, corridor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/corridors/{corridor_id}", None, headers)

    # -- Track segments ------------------------------------------------------

    def create_track_segment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/track-segments", payload, headers)

    def list_track_segments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/track-segments", params, headers)

    def get_track_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/track-segments/{segment_id}", None, headers)

    # -- Operating agreements -------------------------------------------------

    def create_operating_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/operating-agreements", payload, headers)

    def list_operating_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/operating-agreements", params, headers)

    def get_operating_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/operating-agreements/{agreement_id}", None, headers)

    def activate_operating_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/operating-agreements/{agreement_id}/activate", {}, headers)

    def amend_operating_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/operating-agreements/{agreement_id}/amend", payload, headers)

    def suspend_operating_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/operating-agreements/{agreement_id}/suspend", payload, headers)

    # -- Timetables -----------------------------------------------------------

    def create_timetable(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/timetables", payload, headers)

    def list_timetables(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/timetables", params, headers)

    def get_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/timetables/{timetable_id}", None, headers)

    def propose_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/timetables/{timetable_id}/propose", {}, headers)

    def review_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/timetables/{timetable_id}/review", {}, headers)

    def revise_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/timetables/{timetable_id}/revise", {}, headers)

    def ratify_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/timetables/{timetable_id}/ratify", {}, headers)

    def publish_timetable(self, timetable_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/timetables/{timetable_id}/publish", {}, headers)

    # -- Train runs -----------------------------------------------------------

    def list_train_runs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/train-runs", params, headers)

    def get_train_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/train-runs/{run_id}", None, headers)

    def depart_train_run(self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/train-runs/{run_id}/depart", payload, headers)

    def complete_train_run(self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/train-runs/{run_id}/complete", payload, headers)

    def cancel_train_run(self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/train-runs/{run_id}/cancel", payload, headers)

    # -- Segment passages -----------------------------------------------------

    def list_segment_passages(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/segment-passages", params, headers)

    def get_segment_passage(self, passage_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/segment-passages/{passage_id}", None, headers)

    def actualize_segment_passage(self, passage_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/segment-passages/{passage_id}/actualize", payload, headers)

    # -- Delay incidents and disputes -----------------------------------------

    def create_delay_incident(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/delay-incidents", payload, headers)

    def list_delay_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/delay-incidents", params, headers)

    def get_delay_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/delay-incidents/{incident_id}", None, headers)

    def confirm_delay_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/delay-incidents/{incident_id}/confirm", {}, headers)

    def dispute_delay_incident(self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/delay-incidents/{incident_id}/dispute", payload, headers)

    def list_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/disputes", params, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/disputes/{dispute_id}", None, headers)

    def escalate_dispute(self, dispute_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/disputes/{dispute_id}/escalate", {}, headers)

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/disputes/{dispute_id}/resolve", payload, headers)

    # -- Capital projects -----------------------------------------------------

    def create_capital_project(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/capital-projects", payload, headers)

    def list_capital_projects(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/capital-projects", params, headers)

    def get_capital_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/capital-projects/{project_id}", None, headers)

    def approve_capital_project(self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/capital-projects/{project_id}/approve", payload, headers)

    def start_capital_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/capital-projects/{project_id}/start", {}, headers)

    def suspend_capital_project(self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/capital-projects/{project_id}/suspend", payload, headers)

    def complete_capital_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/capital-projects/{project_id}/complete", {}, headers)

    # -- Maintenance windows --------------------------------------------------

    def create_maintenance_window(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/maintenance-windows", params, headers)

    def get_maintenance_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/maintenance-windows/{window_id}", None, headers)

    def lock_maintenance_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/maintenance-windows/{window_id}/lock", {}, headers)

    def release_maintenance_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/maintenance-windows/{window_id}/release", {}, headers)

    # -- Service disruptions --------------------------------------------------

    def create_service_disruption(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/service-disruptions", payload, headers)

    def list_service_disruptions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/service-disruptions", params, headers)

    def get_service_disruption(self, disruption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/service-disruptions/{disruption_id}", None, headers)

    def bridge_service_disruption(self, disruption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/service-disruptions/{disruption_id}/bridge", {}, headers)

    def recover_service_disruption(self, disruption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/service-disruptions/{disruption_id}/recover", {}, headers)

    # -- Funding agreements ---------------------------------------------------

    def create_funding_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/funding-agreements", payload, headers)

    def list_funding_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/funding-agreements", params, headers)

    def get_funding_agreement(self, funding_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/funding-agreements/{funding_id}", None, headers)

    def commit_funding_agreement(self, funding_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/funding-agreements/{funding_id}/commit", {}, headers)

    def settle_funding_agreement(self, funding_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/funding-agreements/{funding_id}/settle", {}, headers)

    # -- Settlement statements ------------------------------------------------

    def create_settlement_statement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rail/settlement-statements", payload, headers)

    def list_settlement_statements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/rail/settlement-statements", params, headers)

    def get_settlement_statement(self, statement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rail/settlement-statements/{statement_id}", None, headers)

    def issue_settlement_statement(self, statement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/settlement-statements/{statement_id}/issue", {}, headers)

    def dispute_settlement_statement(self, statement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/settlement-statements/{statement_id}/dispute", payload, headers)

    def reissue_settlement_statement(self, statement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/settlement-statements/{statement_id}/reissue", {}, headers)

    def pay_settlement_statement(self, statement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rail/settlement-statements/{statement_id}/pay", {}, headers)


api_client = ApiClient()
