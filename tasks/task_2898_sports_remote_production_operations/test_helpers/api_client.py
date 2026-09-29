"""API client for the Broadcast Operations API: one method per endpoint.

Also provides instant canonicalisation so tests can compare timestamps by the
instant they denote rather than by their exact textual rendering.
"""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

#: Every endpoint is mounted under this prefix.
BASE = "/broadcast-ops"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Re-render an ISO 8601 UTC instant as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Returns None unchanged so optional timestamp fields can be compared
    directly. Any string that cannot be parsed is returned unchanged so the
    caller's assertion reports the raw value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    millis = parsed.microsecond // 1000
    return f"{parsed.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """One method per endpoint of the Broadcast Operations API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Production trucks
    # ------------------------------------------------------------------
    def create_truck(self, payload, headers):
        return self._request("POST", f"{BASE}/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"{BASE}/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", f"{BASE}/trucks", headers=headers, params=params)

    def truck_arrive(self, truck_id, headers):
        return self._request("POST", f"{BASE}/trucks/{truck_id}/arrive", None, headers)

    def truck_service_complete(self, truck_id, headers):
        return self._request(
            "POST", f"{BASE}/trucks/{truck_id}/service-complete", None, headers
        )

    # ------------------------------------------------------------------
    # Transmission paths
    # ------------------------------------------------------------------
    def create_transmission_path(self, payload, headers):
        return self._request("POST", f"{BASE}/transmission-paths", payload, headers)

    def get_transmission_path(self, path_id, headers):
        return self._request(
            "GET", f"{BASE}/transmission-paths/{path_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Crew members
    # ------------------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", f"{BASE}/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request(
            "GET", f"{BASE}/crew-members/{crew_member_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Data feeds
    # ------------------------------------------------------------------
    def create_data_feed(self, payload, headers):
        return self._request("POST", f"{BASE}/data-feeds", payload, headers)

    def get_data_feed(self, feed_id, headers):
        return self._request("GET", f"{BASE}/data-feeds/{feed_id}", headers=headers)

    def suspend_data_feed(self, feed_id, headers):
        return self._request(
            "POST", f"{BASE}/data-feeds/{feed_id}/suspend", None, headers
        )

    # ------------------------------------------------------------------
    # Productions
    # ------------------------------------------------------------------
    def create_production(self, payload, headers):
        return self._request("POST", f"{BASE}/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request(
            "GET", f"{BASE}/productions/{production_id}", headers=headers
        )

    def list_productions(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/productions", headers=headers, params=params
        )

    def assign_truck(self, production_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/productions/{production_id}/truck-assignment",
            payload, headers,
        )

    def wrap_production(self, production_id, headers):
        return self._request(
            "POST", f"{BASE}/productions/{production_id}/wrap", None, headers
        )

    def settle_production(self, production_id, headers):
        return self._request(
            "POST", f"{BASE}/productions/{production_id}/settle", None, headers
        )

    # ------------------------------------------------------------------
    # Venue surveys and the camera plot
    # ------------------------------------------------------------------
    def create_venue_survey(self, payload, headers):
        return self._request("POST", f"{BASE}/venue-surveys", payload, headers)

    def get_venue_survey(self, survey_id, headers):
        return self._request(
            "GET", f"{BASE}/venue-surveys/{survey_id}", headers=headers
        )

    def list_production_venue_surveys(self, production_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/productions/{production_id}/venue-surveys",
            headers=headers, params=params,
        )

    def create_camera_position(self, survey_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/venue-surveys/{survey_id}/camera-positions",
            payload, headers,
        )

    def list_camera_positions(self, survey_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/venue-surveys/{survey_id}/camera-positions",
            headers=headers, params=params,
        )

    def submit_venue_survey(self, survey_id, headers):
        return self._request(
            "POST", f"{BASE}/venue-surveys/{survey_id}/submit", None, headers
        )

    def review_venue_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/venue-surveys/{survey_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Path bookings
    # ------------------------------------------------------------------
    def create_path_booking(self, payload, headers):
        return self._request("POST", f"{BASE}/path-bookings", payload, headers)

    def get_path_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{BASE}/path-bookings/{booking_id}", headers=headers
        )

    def list_path_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/path-bookings", headers=headers, params=params
        )

    def schedule_path_test(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/path-bookings/{booking_id}/schedule-test",
            payload, headers,
        )

    def record_path_test_result(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/path-bookings/{booking_id}/test-result", payload, headers
        )

    def release_path_booking(self, booking_id, headers):
        return self._request(
            "POST", f"{BASE}/path-bookings/{booking_id}/release", None, headers
        )

    # ------------------------------------------------------------------
    # Crew calls
    # ------------------------------------------------------------------
    def create_crew_call(self, payload, headers):
        return self._request("POST", f"{BASE}/crew-calls", payload, headers)

    def get_crew_call(self, call_id, headers):
        return self._request("GET", f"{BASE}/crew-calls/{call_id}", headers=headers)

    def list_crew_calls(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/crew-calls", headers=headers, params=params
        )

    def respond_to_crew_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/crew-calls/{call_id}/respond", payload, headers
        )

    def release_crew_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/crew-calls/{call_id}/release", payload, headers
        )

    def cancel_crew_call(self, call_id, headers):
        return self._request(
            "POST", f"{BASE}/crew-calls/{call_id}/cancel", None, headers
        )

    # ------------------------------------------------------------------
    # System preparations
    # ------------------------------------------------------------------
    def create_system_prep(self, payload, headers):
        return self._request("POST", f"{BASE}/system-preps", payload, headers)

    def get_system_prep(self, prep_id, headers):
        return self._request("GET", f"{BASE}/system-preps/{prep_id}", headers=headers)

    def list_system_preps(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/system-preps", headers=headers, params=params
        )

    def validate_prep_feed(self, prep_id, headers):
        return self._request(
            "POST", f"{BASE}/system-preps/{prep_id}/validate-feed", None, headers
        )

    # ------------------------------------------------------------------
    # Rehearsals
    # ------------------------------------------------------------------
    def create_rehearsal(self, payload, headers):
        return self._request("POST", f"{BASE}/rehearsals", payload, headers)

    def get_rehearsal(self, rehearsal_id, headers):
        return self._request("GET", f"{BASE}/rehearsals/{rehearsal_id}", headers=headers)

    def list_production_rehearsals(self, production_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/productions/{production_id}/rehearsals",
            headers=headers, params=params,
        )

    def record_rehearsal_outcome(self, rehearsal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/rehearsals/{rehearsal_id}/outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # Show executions and the incident log
    # ------------------------------------------------------------------
    def create_show_execution(self, payload, headers):
        return self._request("POST", f"{BASE}/show-executions", payload, headers)

    def get_show_execution(self, show_id, headers):
        return self._request(
            "GET", f"{BASE}/show-executions/{show_id}", headers=headers
        )

    def list_production_show_executions(self, production_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/productions/{production_id}/show-executions",
            headers=headers, params=params,
        )

    def set_air_status(self, show_id, target_air_status, headers):
        return self._request(
            "POST", f"{BASE}/show-executions/{show_id}/air-status",
            {"target_air_status": target_air_status}, headers,
        )

    def create_incident(self, show_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/show-executions/{show_id}/incidents", payload, headers
        )

    def list_incidents(self, show_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/show-executions/{show_id}/incidents",
            headers=headers, params=params,
        )


api_client = ApiClient()
