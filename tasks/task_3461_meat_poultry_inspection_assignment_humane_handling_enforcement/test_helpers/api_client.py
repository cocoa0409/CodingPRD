"""HTTP client for the Meat & Poultry Inspection API.

One method per endpoint declared in the PRD endpoint table. Every method
returns the raw ``requests.Response`` so tests assert on status codes and
bodies themselves. The client takes its base URL from the ``API_BASE_URL``
environment variable the runner injects; no port is ever hardcoded here.

Path handling: every business endpoint is mounted under the ``/inspection``
prefix exactly as written. The single exception is the platform logical-clock
endpoint ``POST /_clock/set_current_utc`` (PRD §2.4: "This endpoint sits
outside the ``/inspection`` prefix — its path is exactly
``/_clock/set_current_utc``"), which ``set_clock`` calls directly — it is
never routed through any prefixed helper.

This module deliberately defines NO module-level shared client instance named
``api_client``: the name ``test_helpers.api_client`` must always resolve to
this module (so both ``from test_helpers import api_client`` and
``import test_helpers.api_client as ac`` bind the module). Callers construct
``ApiClient()`` themselves; the pytest ``api`` fixture does exactly that.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The PRD renders timestamps "as ISO 8601 UTC strings with three fractional
    digits", so ``2026-09-01T00:00:00Z`` and ``2026-09-01T00:00:00.000Z`` are
    the same instant spelled two ways. Comparisons run on the canonical
    three-fractional-digit form.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Platform logical clock (OUTSIDE the /inspection prefix) ─────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc — unprefixed platform path, exact."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Establishments ──────────────────────────────────────────────────────

    def create_establishment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/establishments", payload, headers)

    def get_establishment(self, establishment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/establishments/{establishment_id}", headers=headers)

    # ── Grant applications ──────────────────────────────────────────────────

    def create_grant_application(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/grant-applications", payload, headers)

    def list_grant_applications(
        self, establishment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/establishments/{establishment_id}/grant-applications",
            headers=headers, params=params,
        )

    def begin_grant_review(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/grant-applications/{application_id}/begin-review", headers=headers)

    def record_adequacy(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/grant-applications/{application_id}/record-adequacy", payload, headers)

    def decide_grant_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/grant-applications/{application_id}/decide", payload, headers)

    def resubmit_grant_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/grant-applications/{application_id}/resubmit", payload, headers)

    def withdraw_grant_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/grant-applications/{application_id}/withdraw", headers=headers)

    # ── Inspectors ──────────────────────────────────────────────────────────

    def create_inspector(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/inspectors", payload, headers)

    def deactivate_inspector(self, inspector_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/inspectors/{inspector_id}/deactivate", headers=headers)

    # ── Shift windows ───────────────────────────────────────────────────────

    def create_shift_window(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/shift-windows", payload, headers)

    def list_shift_windows(
        self, establishment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/establishments/{establishment_id}/shift-windows",
            headers=headers, params=params,
        )

    def get_shift_window(self, shift_window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/shift-windows/{shift_window_id}", headers=headers)

    def verify_coverage(self, shift_window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/shift-windows/{shift_window_id}/verify-coverage", headers=headers)

    # ── Shift assignments ───────────────────────────────────────────────────

    def create_assignment(self, shift_window_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/shift-windows/{shift_window_id}/assignments", payload, headers)

    def list_shift_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/inspection/shift-assignments", headers=headers, params=params)

    def get_shift_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/shift-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/shift-assignments/{assignment_id}/confirm", headers=headers)

    def cancel_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/shift-assignments/{assignment_id}/cancel", headers=headers)

    # ── Noncompliance records ───────────────────────────────────────────────

    def create_noncompliance_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/noncompliance-records", payload, headers)

    def list_noncompliance_records(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/inspection/noncompliance-records", headers=headers, params=params)

    def get_noncompliance_record(self, record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/noncompliance-records/{record_id}", headers=headers)

    def respond_to_nr(self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/noncompliance-records/{record_id}/respond", payload, headers)

    def verify_nr_response(self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/noncompliance-records/{record_id}/verify-response", payload, headers)

    # ── Enforcement actions ─────────────────────────────────────────────────

    def create_enforcement_action(self, establishment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/establishments/{establishment_id}/enforcement-actions", payload, headers)

    def list_enforcement_actions(
        self, establishment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/establishments/{establishment_id}/enforcement-actions",
            headers=headers, params=params,
        )

    def activate_enforcement_action(self, action_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/enforcement-actions/{action_id}/activate", headers=headers)

    def lift_enforcement_action(self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/enforcement-actions/{action_id}/lift", payload, headers)

    # ── Humane handling events ──────────────────────────────────────────────

    def create_humane_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/humane-handling-events", payload, headers)

    def list_humane_events(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/inspection/humane-handling-events", headers=headers, params=params)

    def get_humane_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/humane-handling-events/{event_id}", headers=headers)

    def confirm_humane_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/humane-handling-events/{event_id}/confirm", headers=headers)

    def dismiss_humane_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/humane-handling-events/{event_id}/dismiss", headers=headers)

    # ── Pathogen samples ────────────────────────────────────────────────────

    def create_pathogen_sample(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/pathogen-samples", payload, headers)

    def list_pathogen_samples(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/inspection/pathogen-samples", headers=headers, params=params)

    def get_pathogen_sample(self, sample_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/pathogen-samples/{sample_id}", headers=headers)

    def record_sample_result(self, sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/pathogen-samples/{sample_id}/record-result", payload, headers)

    # ── Label applications ──────────────────────────────────────────────────

    def create_label_application(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/label-applications", payload, headers)

    def list_label_applications(
        self, establishment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/establishments/{establishment_id}/label-applications",
            headers=headers, params=params,
        )

    def begin_label_review(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/label-applications/{application_id}/begin-review", headers=headers)

    def decide_label_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/label-applications/{application_id}/decide", payload, headers)

    def resubmit_label_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/label-applications/{application_id}/resubmit", payload, headers)

    # ── Recalls ─────────────────────────────────────────────────────────────

    def create_recall(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/recalls", payload, headers)

    def get_recall(self, recall_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspection/recalls/{recall_id}", headers=headers)

    def list_recalls(
        self, establishment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/establishments/{establishment_id}/recalls",
            headers=headers, params=params,
        )

    def determine_recall_class(self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/recalls/{recall_id}/determine-class", payload, headers)

    def record_effectiveness_check(self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/recalls/{recall_id}/effectiveness-checks", payload, headers)

    def list_effectiveness_checks(
        self, recall_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/recalls/{recall_id}/effectiveness-checks",
            headers=headers, params=params,
        )

    def close_recall(self, recall_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/recalls/{recall_id}/close", headers=headers)

    # ── Appeals ─────────────────────────────────────────────────────────────

    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/inspection/appeals", payload, headers)

    def list_appeals(
        self, record_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspection/noncompliance-records/{record_id}/appeals",
            headers=headers, params=params,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/inspection/appeals/{appeal_id}/decide", payload, headers)
