"""HTTP client for the Ski Area Mountain Operations API.

One method per endpoint of the specification, plus the administrative logical
clock control. Every method returns the raw response so tests can assert on
status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _query(**filters: Any) -> Dict[str, Any]:
    """Drop unset filters so an omitted parameter is genuinely absent."""
    return {key: value for key, value in filters.items() if value is not None}


class ApiClient(GenericApiClient):
    """Endpoint-level client for the mountain operations service."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ─── Seasons ──────────────────────────────────────
    def create_season(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/seasons", payload, headers)

    def get_season(self, season_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/seasons/{season_id}", None, headers)

    def get_season_snow_accounting(self, season_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/seasons/{season_id}/snow-accounting", None, headers
        )

    # ─── Lifts ────────────────────────────────────────
    def create_lift(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lifts", payload, headers)

    def get_lift(self, lift_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/lifts/{lift_id}", None, headers)

    def list_lifts(
        self,
        headers,
        season_id: Optional[str] = None,
        service_status: Optional[str] = None,
        mechanical_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/lifts",
            _query(
                season_id=season_id,
                service_status=service_status,
                mechanical_status=mechanical_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def record_lift_inspection(
        self, lift_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/lifts/{lift_id}/inspections", payload, headers
        )

    def set_lift_service_status(
        self, lift_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/lifts/{lift_id}/service-status", payload, headers
        )

    def list_lift_staff_assignments(
        self,
        lift_id: str,
        headers,
        state: Optional[str] = None,
        role_on_lift: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/lifts/{lift_id}/staff-assignments",
            _query(state=state, role_on_lift=role_on_lift, limit=limit, offset=offset),
            headers,
        )

    def create_lift_staff_assignment(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/lift-staff-assignments", payload, headers
        )

    def release_lift_staff_assignment(
        self, assignment_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/lift-staff-assignments/{assignment_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # ─── Terrain areas ────────────────────────────────
    def create_terrain_area(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/terrain-areas", payload, headers)

    def get_terrain_area(self, area_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/terrain-areas/{area_id}", None, headers
        )

    def list_terrain_areas(
        self,
        headers,
        season_id: Optional[str] = None,
        serving_lift_id: Optional[str] = None,
        opening_state: Optional[str] = None,
        terrain_class: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/terrain-areas",
            _query(
                season_id=season_id,
                serving_lift_id=serving_lift_id,
                opening_state=opening_state,
                terrain_class=terrain_class,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def record_snow_depth_reading(
        self, area_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/terrain-areas/{area_id}/snow-depth-readings",
            payload,
            headers,
        )

    def list_snow_depth_readings(
        self,
        area_id: str,
        headers,
        stake_code: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/terrain-areas/{area_id}/snow-depth-readings",
            _query(stake_code=stake_code, source=source, limit=limit, offset=offset),
            headers,
        )

    def build_park(
        self, area_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/terrain-areas/{area_id}/park-build", payload, headers
        )

    def inspect_park(
        self, area_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/terrain-areas/{area_id}/park-inspection",
            payload,
            headers,
        )

    def decide_opening(
        self, area_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/terrain-areas/{area_id}/opening-decision",
            payload,
            headers,
        )

    # ─── Pump houses ──────────────────────────────────
    def create_pump_house(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/pump-houses", payload, headers)

    def get_pump_house(self, pump_house_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/pump-houses/{pump_house_id}", None, headers
        )

    def list_pump_houses(
        self,
        headers,
        season_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/pump-houses",
            _query(season_id=season_id, status=status, limit=limit, offset=offset),
            headers,
        )

    def set_pump_house_status(
        self, pump_house_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pump-houses/{pump_house_id}/status",
            payload,
            headers,
        )

    # ─── Snowmaking sessions ──────────────────────────
    def create_session(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/snowmaking-sessions", payload, headers
        )

    def get_session(self, session_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/snowmaking-sessions/{session_id}", None, headers
        )

    def list_sessions(
        self,
        headers,
        terrain_area_id: Optional[str] = None,
        pump_house_id: Optional[str] = None,
        state: Optional[str] = None,
        abort_reason: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/snowmaking-sessions",
            _query(
                terrain_area_id=terrain_area_id,
                pump_house_id=pump_house_id,
                state=state,
                abort_reason=abort_reason,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def set_session_status(
        self, session_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/snowmaking-sessions/{session_id}/status",
            payload,
            headers,
        )

    # ─── Grooming tasks ───────────────────────────────
    def create_grooming_task(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/grooming-tasks", payload, headers)

    def get_grooming_task(self, task_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/grooming-tasks/{task_id}", None, headers
        )

    def list_grooming_tasks(
        self,
        headers,
        terrain_area_id: Optional[str] = None,
        cat_route_code: Optional[str] = None,
        snowcat_unit_code: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/grooming-tasks",
            _query(
                terrain_area_id=terrain_area_id,
                cat_route_code=cat_route_code,
                snowcat_unit_code=snowcat_unit_code,
                state=state,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def dispatch_grooming_task(
        self, task_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/grooming-tasks/{task_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    def complete_grooming_task(
        self, task_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/grooming-tasks/{task_id}/complete", payload, headers
        )

    # ─── Patrollers ───────────────────────────────────
    def create_patroller(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/patrollers", payload, headers)

    def get_patroller(self, patroller_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/patrollers/{patroller_id}", None, headers
        )

    def list_patrollers(
        self,
        headers,
        season_id: Optional[str] = None,
        assigned_terrain_area_id: Optional[str] = None,
        status: Optional[str] = None,
        on_duty: Optional[Any] = None,
        cert_level: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/patrollers",
            _query(
                season_id=season_id,
                assigned_terrain_area_id=assigned_terrain_area_id,
                status=status,
                on_duty=on_duty,
                cert_level=cert_level,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def set_patroller_duty(
        self, patroller_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/patrollers/{patroller_id}/duty", payload, headers
        )

    # ─── Avalanche mitigation missions ────────────────
    def create_mission(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/mitigation-missions", payload, headers
        )

    def get_mission(self, mission_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/mitigation-missions/{mission_id}", None, headers
        )

    def list_missions(
        self,
        headers,
        terrain_area_id: Optional[str] = None,
        executed_by_patroller_id: Optional[str] = None,
        cleared_by_patroller_id: Optional[str] = None,
        method: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/mitigation-missions",
            _query(
                terrain_area_id=terrain_area_id,
                executed_by_patroller_id=executed_by_patroller_id,
                cleared_by_patroller_id=cleared_by_patroller_id,
                method=method,
                state=state,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def execute_mission(
        self, mission_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/mitigation-missions/{mission_id}/execute",
            payload,
            headers,
        )

    def clear_mission(
        self, mission_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/mitigation-missions/{mission_id}/clear",
            payload,
            headers,
        )

    # ─── Patrol incidents ─────────────────────────────
    def create_incident(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/incidents/{incident_id}", None, headers
        )

    def list_incidents(
        self,
        headers,
        terrain_area_id: Optional[str] = None,
        responder_patroller_id: Optional[str] = None,
        severity: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/incidents",
            _query(
                terrain_area_id=terrain_area_id,
                responder_patroller_id=responder_patroller_id,
                severity=severity,
                state=state,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def dispatch_incident(
        self, incident_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/dispatch", payload, headers
        )

    def order_incident_transport(
        self, incident_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/transport", payload, headers
        )

    def close_incident(
        self, incident_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/close", payload, headers
        )

    # ─── Day plans ────────────────────────────────────
    def create_day_plan(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/day-plans", payload, headers)

    def get_day_plan(self, day_plan_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/day-plans/{day_plan_id}", None, headers
        )

    def list_day_plans(
        self,
        headers,
        season_id: Optional[str] = None,
        operating_date: Optional[str] = None,
        posture: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/day-plans",
            _query(
                season_id=season_id,
                operating_date=operating_date,
                posture=posture,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def post_weather(
        self, day_plan_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/day-plans/{day_plan_id}/weather", payload, headers
        )

    def publish_day_plan(
        self, day_plan_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/day-plans/{day_plan_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def close_day(
        self, day_plan_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/day-plans/{day_plan_id}/close-day",
            payload if payload is not None else {},
            headers,
        )

    def get_opening_report(self, day_plan_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/day-plans/{day_plan_id}/opening-report", None, headers
        )

    # ─── Access reservations ──────────────────────────
    def create_reservation(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/access-reservations", payload, headers
        )

    def get_reservation(self, reservation_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/access-reservations/{reservation_id}", None, headers
        )

    def list_day_plan_reservations(
        self,
        day_plan_id: str,
        headers,
        state: Optional[str] = None,
        pass_type: Optional[str] = None,
        waitlist_reason: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/day-plans/{day_plan_id}/access-reservations",
            _query(
                state=state,
                pass_type=pass_type,
                waitlist_reason=waitlist_reason,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def check_in_reservation(
        self, reservation_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/access-reservations/{reservation_id}/check-in",
            payload if payload is not None else {},
            headers,
        )

    def release_reservation(
        self, reservation_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/access-reservations/{reservation_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # ─── Raw escape hatches ───────────────────────────
    def raw_post(
        self, path: str, payload: Any, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        """POST an arbitrary path, for tests that must bypass a typed method."""
        return self._request("POST", path, payload, headers, params)

    def raw_get(
        self, path: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        """GET an arbitrary path, for pagination and filter probes."""
        return self._request("GET", path, None, headers, params)
