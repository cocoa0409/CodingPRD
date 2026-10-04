"""HTTP client for the Air Traffic Flow Management API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination are passed as ``params``; request bodies as ``payload``.

The business surface is mounted under the ``/atfm`` prefix; the logical-clock
endpoint is mounted OUTSIDE that prefix (PRD §2.5), and ``set_clock`` therefore
uses the bare ``/_clock/set_current_utc`` path.

No module-level client instance is created here on purpose: conftest builds a
fresh ``ApiClient`` per test, so ``test_helpers.api_client`` always resolves to
this module and never to a shadowing singleton.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders system instants with three fractional digits, but an
    equal instant may legitimately arrive with none or with trailing zeroes.
    Comparisons therefore run on the canonical form
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so ``2026-09-15T13:00:00Z`` and
    ``2026-09-15T13:00:00.000Z`` compare equal.
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
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock (UNPREFIXED — outside /atfm, PRD §2.5) ───────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Facilities ─────────────────────────────────────────────────────────

    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/atfm/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/facilities/{facility_id}", headers=headers)

    def patch_facility(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/atfm/facilities/{facility_id}", payload, headers)

    # ── Operators ──────────────────────────────────────────────────────────

    def create_operator(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/atfm/operators", payload, headers)

    def get_operator(self, operator_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/operators/{operator_id}", headers=headers)

    # ── Constraint events ──────────────────────────────────────────────────

    def create_constraint_event(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/atfm/facilities/{facility_id}/constraint-events", payload, headers
        )

    def list_constraint_events(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/atfm/facilities/{facility_id}/constraint-events", headers=headers, params=params
        )

    def confirm_constraint_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/constraint-events/{event_id}/confirm", headers=headers)

    def clear_constraint_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/constraint-events/{event_id}/clear", headers=headers)

    def extend_constraint_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/atfm/constraint-events/{event_id}/extend", payload, headers
        )

    # ── Capacity forecasts ─────────────────────────────────────────────────

    def create_capacity_forecast(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/atfm/facilities/{facility_id}/capacity-forecasts", payload, headers
        )

    def list_capacity_forecasts(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/atfm/facilities/{facility_id}/capacity-forecasts", headers=headers, params=params
        )

    def publish_capacity_forecast(self, forecast_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/atfm/capacity-forecasts/{forecast_id}/publish", headers=headers
        )

    # ── Traffic management initiatives ─────────────────────────────────────

    def create_tmi(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/facilities/{facility_id}/tmis", payload, headers)

    def list_tmil_of_facility(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/atfm/facilities/{facility_id}/tmis", headers=headers, params=params
        )

    def get_tmi(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}", headers=headers)

    def publish_tmi(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/publish", headers=headers)

    def activate_tmi(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/activate", headers=headers)

    def create_tmi_revision(
        self, tmi_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/revisions", payload, headers)

    def list_tmi_revisions(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}/revisions", headers=headers)

    def cancel_tmi(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/cancel", headers=headers)

    def complete_tmi(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/complete", headers=headers)

    # ── Flights ────────────────────────────────────────────────────────────

    def create_flight(
        self, operator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/operators/{operator_id}/flights", payload, headers)

    def list_flights(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/atfm/flights", headers=headers, params=params)

    def get_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/flights/{flight_id}", headers=headers)

    def update_flight(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/flights/{flight_id}/updates", payload, headers)

    def cancel_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/flights/{flight_id}/cancel", headers=headers)

    def list_flight_slots(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/flights/{flight_id}/slots", headers=headers)

    # ── Slots, substitutions, compression ──────────────────────────────────

    def list_tmi_slots(
        self, tmi_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}/slots", headers=headers, params=params)

    def create_substitution(
        self, tmi_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/substitutions", payload, headers)

    def create_compression_run(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/atfm/tmis/{tmi_id}/compression-runs", headers=headers)

    def list_compression_runs(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}/compression-runs", headers=headers)

    # ── GA accommodation ───────────────────────────────────────────────────

    def create_ga_request(
        self, operator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/atfm/operators/{operator_id}/ga-requests", payload, headers)

    def adjudicate_ga_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/atfm/ga-requests/{request_id}/adjudicate", payload, headers
        )

    def list_operator_ga_requests(
        self, operator_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/atfm/operators/{operator_id}/ga-requests", headers=headers, params=params
        )

    def list_tmi_ga_requests(
        self, tmi_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}/ga-requests", headers=headers, params=params)

    # ── Reroute assignments ────────────────────────────────────────────────

    def create_reroute_assignment(
        self, tmi_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/atfm/tmis/{tmi_id}/reroute-assignments", payload, headers
        )

    def list_reroute_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/atfm/reroute-assignments", headers=headers, params=params)

    def get_reroute_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/reroute-assignments/{assignment_id}", headers=headers)

    # ── Delay ledgers and the transaction log ──────────────────────────────

    def list_operator_delay_ledgers(
        self, operator_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/atfm/operators/{operator_id}/delay-ledgers", headers=headers)

    def list_tmi_delay_ledgers(self, tmi_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/atfm/tmis/{tmi_id}/delay-ledgers", headers=headers)

    def list_slot_transactions(
        self, tmi_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/atfm/tmis/{tmi_id}/slot-transactions", headers=headers, params=params
        )

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
