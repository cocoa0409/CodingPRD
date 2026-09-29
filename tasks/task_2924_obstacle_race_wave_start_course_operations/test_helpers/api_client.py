"""API client: one method per endpoint of PRD §4.

Every path carries the `/ocr` mount prefix, because the framework's base URL is
the bare server root. Methods return the raw `requests.Response` so tests can
assert HTTP status codes; unwrapping is the validators' job.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ocr"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Obstacle Course Race Operations API."""

    # ─── The logical race clock (PRD §2.5) ───────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload: Optional[dict], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Venues (PRD §3.1) ───────────────────────────────────────────────

    def create_venue(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def list_venues(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/venues", headers=headers, params=params)

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", headers=headers)

    # ─── Land-use permits (PRD §3.1) ─────────────────────────────────────

    def create_permit(self, venue_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/permits", payload, headers
        )

    def list_permits(
        self, venue_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/venues/{venue_id}/permits", headers=headers, params=params
        )

    def get_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/submit", headers=headers
        )

    def decide_permit(self, permit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/decision", payload, headers
        )

    # ─── Courses (PRD §3.2) ──────────────────────────────────────────────

    def create_course(self, venue_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/courses", payload, headers
        )

    def list_courses(
        self, venue_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/venues/{venue_id}/courses", headers=headers, params=params
        )

    def get_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/courses/{course_id}", headers=headers)

    def validate_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/courses/{course_id}/validate", headers=headers
        )

    def publish_course(self, course_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/courses/{course_id}/publish", headers=headers
        )

    # ─── Obstacles (PRD §3.2) ────────────────────────────────────────────

    def create_obstacle(self, course_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/courses/{course_id}/obstacles", payload, headers
        )

    def list_obstacles(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/obstacles", headers=headers, params=params
        )

    def get_obstacle(self, obstacle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/obstacles/{obstacle_id}", headers=headers)

    def list_obstacle_attempts(
        self, obstacle_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/obstacles/{obstacle_id}/attempts",
            headers=headers,
            params=params,
        )

    # ─── Divisions (PRD §3.4) ────────────────────────────────────────────

    def create_division(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/divisions", payload, headers)

    def list_divisions(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/divisions", headers=headers, params=params
        )

    def get_division(self, division_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/divisions/{division_id}", headers=headers)

    # ─── Waves / heats (PRD §3.4, §3.6) ──────────────────────────────────

    def create_wave(self, course_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/courses/{course_id}/waves", payload, headers
        )

    def list_waves(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/waves", headers=headers, params=params)

    def get_wave(self, wave_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/waves/{wave_id}", headers=headers)

    def hold_wave(self, wave_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/hold", payload, headers)

    def lock_roster(self, wave_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/waves/{wave_id}/lock-roster", headers=headers
        )

    def release_wave(self, wave_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/waves/{wave_id}/release", headers=headers
        )

    def start_wave(self, wave_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/start", headers=headers)

    def close_wave(self, wave_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/close", headers=headers)

    def create_entry(self, wave_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/waves/{wave_id}/entries", payload, headers
        )

    # ─── Participants (PRD §3.5) ─────────────────────────────────────────

    def create_participant(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/participants", payload, headers)

    def list_participants(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/participants", headers=headers, params=params
        )

    def get_participant(self, participant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/participants/{participant_id}", headers=headers
        )

    def sign_waiver(self, participant_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/participants/{participant_id}/waiver", payload, headers
        )

    # ─── Entries (PRD §3.5, §3.7, §3.8) ──────────────────────────────────

    def list_entries(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/entries", headers=headers, params=params)

    def get_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/entries/{entry_id}", headers=headers)

    def check_in_entry(self, entry_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/check-in", payload, headers
        )

    def reassign_entry(self, entry_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/reassign-wave", payload, headers
        )

    def finish_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/finish", headers=headers
        )

    def create_protest(self, entry_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/protests", payload, headers
        )

    def create_adjudication(self, entry_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/adjudications", payload, headers
        )

    def create_attempt(self, entry_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/attempts", payload, headers
        )

    def list_entry_attempts(
        self, entry_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/entries/{entry_id}/attempts",
            headers=headers,
            params=params,
        )

    # ─── Staff assignments (PRD §3.3) ────────────────────────────────────

    def create_staff_assignment(
        self, course_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/courses/{course_id}/staff-assignments", payload, headers
        )

    def list_staff_assignments(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/staff-assignments", headers=headers, params=params
        )

    def get_staff_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/staff-assignments/{assignment_id}", headers=headers
        )

    def vacate_staff_assignment(
        self, assignment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/staff-assignments/{assignment_id}/vacate",
            payload,
            headers,
        )

    # ─── Festival services (PRD §3.9) ────────────────────────────────────

    def create_festival_service(
        self, venue_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/festival-services", payload, headers
        )

    def list_festival_services(
        self, venue_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/venues/{venue_id}/festival-services",
            headers=headers,
            params=params,
        )

    # ─── Restoration tasks and the bond (PRD §3.9) ───────────────────────

    def create_restoration_task(
        self, venue_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/restoration-tasks", payload, headers
        )

    def list_restoration_tasks(
        self, venue_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/venues/{venue_id}/restoration-tasks",
            headers=headers,
            params=params,
        )

    def get_restoration_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/restoration-tasks/{task_id}", headers=headers
        )

    def inspect_restoration_task(
        self, task_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/restoration-tasks/{task_id}/inspect", payload, headers
        )

    def create_bond_release(self, venue_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/venues/{venue_id}/bond-releases", payload, headers
        )
