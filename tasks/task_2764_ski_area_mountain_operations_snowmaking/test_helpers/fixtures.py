"""Composite state builders for the mountain operations API.

The server starts with an empty database for every test, so all state is built
from scratch through the published endpoints. This module offers one scenario
object that walks the mountain up its readiness ladder step by step, plus
pytest fixtures for the states tests reach for repeatedly.

Nothing here asserts business behaviour: setup calls are checked only for
having succeeded, so a failure in a fixture reads as a setup failure rather
than as a false claim about the rule under test.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import INITIAL_CLOCK
from .test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
    make_patroller_headers,
)


class MountainScenario:
    """Builds mountain operations state through the published endpoints."""

    def __init__(self, api: ApiClient):
        self.api = api

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, DIRECTOR_HEADERS))

    # ─── Reads ────────────────────────────────────────
    def season(self, season_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_season(season_id, DIRECTOR_HEADERS))

    def lift(self, lift_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_lift(lift_id, DIRECTOR_HEADERS))

    def area(self, area_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_terrain_area(area_id, DIRECTOR_HEADERS))

    def pump_house(self, pump_house_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_pump_house(pump_house_id, DIRECTOR_HEADERS))

    def session(self, session_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_session(session_id, DIRECTOR_HEADERS))

    def grooming_task(self, task_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_grooming_task(task_id, DIRECTOR_HEADERS))

    def patroller(self, patroller_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_patroller(patroller_id, DIRECTOR_HEADERS))

    def mission(self, mission_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_mission(mission_id, DIRECTOR_HEADERS))

    def incident(self, incident_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_incident(incident_id, DIRECTOR_HEADERS))

    def day_plan(self, day_plan_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))

    def reservation(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_reservation(reservation_id, DIRECTOR_HEADERS))

    def area_version(self, area_id: str) -> int:
        return self.area(area_id)["version"]

    def day_plan_version(self, day_plan_id: str) -> int:
        return self.day_plan(day_plan_id)["version"]

    # ─── Season and inventory ─────────────────────────
    def create_season(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_season(f.season_payload(**overrides), DIRECTOR_HEADERS)
        )

    def create_lift(self, season_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_lift(f.lift_payload(season_id, **overrides), LIFT_OPS_HEADERS)
        )

    def create_terrain_area(
        self, season_id: str, serving_lift_id: str, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_terrain_area(
                f.terrain_area_payload(season_id, serving_lift_id, **overrides),
                DIRECTOR_HEADERS,
            )
        )

    def create_pump_house(self, season_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_pump_house(
                f.pump_house_payload(season_id, **overrides), SNOWMAKING_HEADERS
            )
        )

    def set_pump_house_status(self, pump_house_id: str, status: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_pump_house_status(
                pump_house_id, f.pump_house_status_payload(status), SNOWMAKING_HEADERS
            )
        )

    # ─── Lift mechanical and service posture ──────────
    def inspect_lift(self, lift_id: str, result: str = "PASS", **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_lift_inspection(
                lift_id, f.inspection_payload(result, **overrides), LIFT_OPS_HEADERS
            )
        )

    def set_lift_status(self, lift_id: str, target_status: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_lift_service_status(
                lift_id, f.service_status_payload(target_status), LIFT_OPS_HEADERS
            )
        )

    def assign_operator(self, lift_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_lift_staff_assignment(
                f.staff_assignment_payload(lift_id, **overrides), LIFT_OPS_HEADERS
            )
        )

    def staff_lift(
        self,
        lift_id: str,
        operator_codes: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        shift_start: str = "2026-08-01T00:00:00Z",
        shift_end: str = "2026-08-01T16:00:00Z",
    ) -> List[Dict[str, Any]]:
        """Cover a lift with the operator assignments its posture change needs."""
        operator_codes = operator_codes or ["OP-1", "OP-2"]
        roles = roles or ["TOP_OP", "BOTTOM_OP"]
        return [
            self.assign_operator(
                lift_id,
                operator_code=code,
                role_on_lift=role,
                shift_start=shift_start,
                shift_end=shift_end,
            )
            for code, role in zip(operator_codes, roles)
        ]

    def release_operator(self, assignment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.release_lift_staff_assignment(assignment_id, LIFT_OPS_HEADERS)
        )

    def ready_lift(self, season_id: str, **overrides: Any) -> Dict[str, Any]:
        """A registered lift with a passing inspection, two covering operators
        and a service status of STANDBY."""
        lift = self.create_lift(season_id, **overrides)
        self.inspect_lift(lift["id"], "PASS")
        self.staff_lift(lift["id"])
        self.set_lift_status(lift["id"], "STANDBY")
        return self.lift(lift["id"])

    # ─── Stake readings and grooming ──────────────────
    def record_reading(self, area_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_snow_depth_reading(
                area_id, f.snow_depth_reading_payload(**overrides), GROOMING_HEADERS
            )
        )

    def plan_groom(self, area_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_grooming_task(
                f.grooming_task_payload(area_id, **overrides), GROOMING_HEADERS
            )
        )

    def dispatch_groom(self, task_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.dispatch_grooming_task(task_id, GROOMING_HEADERS)
        )

    def complete_groom(self, task_id: str, passes_completed: int = 20) -> Dict[str, Any]:
        return get_success_data(
            self.api.complete_grooming_task(
                task_id, f.grooming_completion_payload(passes_completed), GROOMING_HEADERS
            )
        )

    def groom_area(
        self, area_id: str, passes_completed: int = 20, **overrides: Any
    ) -> Dict[str, Any]:
        """Plan, dispatch and complete one grooming task, which is what makes an
        area groom-current."""
        task = self.plan_groom(area_id, **overrides)
        self.dispatch_groom(task["id"])
        return self.complete_groom(task["id"], passes_completed)

    # ─── Patrol roster ────────────────────────────────
    def create_patroller(self, season_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_patroller(
                f.patroller_payload(season_id, **overrides), DIRECTOR_HEADERS
            )
        )

    def set_duty(self, patroller_id: str, on_duty: bool) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_patroller_duty(
                patroller_id, f.duty_payload(on_duty), DIRECTOR_HEADERS
            )
        )

    def staff_patrol(
        self,
        season_id: str,
        area_id: str,
        count: int = 2,
        cert_levels: Optional[List[str]] = None,
        blaster_certified: bool = False,
    ) -> List[Dict[str, Any]]:
        """Roster on-duty patrollers onto an area so its staffing gate holds."""
        cert_levels = cert_levels or ["EMT", "PARAMEDIC", "EMT", "PARAMEDIC"]
        return [
            self.create_patroller(
                season_id,
                patroller_code=f"P{index + 1}",
                cert_level=cert_levels[index % len(cert_levels)],
                on_duty=True,
                blaster_certified=blaster_certified,
                assigned_terrain_area_id=area_id,
            )
            for index in range(count)
        ]

    # ─── Avalanche mitigation ─────────────────────────
    def plan_mission(self, area_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_mission(
                f.mission_payload(area_id, **overrides), DIRECTOR_HEADERS
            )
        )

    def execute_mission(
        self, mission_id: str, patroller_id: str, charges_used: int = 4
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.execute_mission(
                mission_id,
                f.mission_execute_payload(charges_used),
                make_patroller_headers(patroller_id),
            )
        )

    def clear_mission(
        self, mission_id: str, patroller_id: str, hazard_rating_post: str = "LOW"
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.clear_mission(
                mission_id,
                f.mission_clear_payload(hazard_rating_post),
                make_patroller_headers(patroller_id),
            )
        )

    def clear_avalanche_terrain(
        self,
        area_id: str,
        executing_patroller_id: str,
        clearing_patroller_id: str,
        method: str = "EXPLOSIVE",
        charges_used: int = 4,
        hazard_rating_post: str = "LOW",
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Plan, execute and sign off one mission, which is what gives an
        avalanche area a current clearance."""
        mission = self.plan_mission(area_id, method=method, **overrides)
        self.execute_mission(mission["id"], executing_patroller_id, charges_used)
        return self.clear_mission(mission["id"], clearing_patroller_id, hazard_rating_post)

    # ─── Terrain parks ────────────────────────────────
    def build_park(
        self, area_id: str, features: Optional[List[Dict[str, str]]] = None, headers=None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.build_park(
                area_id,
                f.park_build_payload(features),
                headers if headers is not None else GROOMING_HEADERS,
            )
        )

    def inspect_park(self, area_id: str, patroller_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.inspect_park(
                area_id,
                f.park_inspection_payload(**overrides),
                make_patroller_headers(patroller_id),
            )
        )

    # ─── Snowmaking sessions ──────────────────────────
    def schedule_session(
        self,
        area_id: str,
        pump_house_id: str,
        expected_terrain_area_version: Optional[int] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Schedule a session, reading the terrain area version the create
        demands unless the caller declares one."""
        version = (
            expected_terrain_area_version
            if expected_terrain_area_version is not None
            else self.area_version(area_id)
        )
        return get_success_data(
            self.api.create_session(
                f.session_payload(area_id, pump_house_id, version, **overrides),
                SNOWMAKING_HEADERS,
            )
        )

    def drive_session(self, session_id: str, target_state: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_session_status(
                session_id, f.session_status_payload(target_state), SNOWMAKING_HEADERS
            )
        )

    def run_session_cycle(self, session_id: str, cycle: List[Any]) -> Dict[str, Any]:
        """Drive a session through a sequence of (clock instant, target state)
        steps, which is how accumulated run minutes are built up."""
        row: Dict[str, Any] = {}
        for instant, target_state in cycle:
            if instant is not None:
                self.set_clock(instant)
            row = self.drive_session(session_id, target_state)
        return row

    # ─── Patrol incidents ─────────────────────────────
    def report_incident(self, area_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_incident(
                f.incident_payload(area_id, **overrides), DIRECTOR_HEADERS
            )
        )

    def dispatch_incident(self, incident_id: str, patroller_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.dispatch_incident(
                incident_id, f.incident_dispatch_payload(patroller_id), DIRECTOR_HEADERS
            )
        )

    def order_transport(
        self, incident_id: str, patroller_id: str, transport_mode: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.order_incident_transport(
                incident_id,
                f.incident_transport_payload(transport_mode),
                make_patroller_headers(patroller_id),
            )
        )

    def close_incident(
        self, incident_id: str, patroller_id: str, disposition: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.close_incident(
                incident_id,
                f.incident_close_payload(disposition),
                make_patroller_headers(patroller_id),
            )
        )

    # ─── Operating day ────────────────────────────────
    def create_day_plan(self, season_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_day_plan(
                f.day_plan_payload(season_id, **overrides), DIRECTOR_HEADERS
            )
        )

    def publish_day_plan(self, day_plan_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.publish_day_plan(day_plan_id, DIRECTOR_HEADERS))

    def post_weather(
        self, day_plan_id: str, wind_speed_mph: float = 10.0, wet_bulb_f: float = 22.0, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.post_weather(
                day_plan_id,
                f.weather_payload(wind_speed_mph, wet_bulb_f, **overrides),
                DIRECTOR_HEADERS,
            )
        )

    def close_day(self, day_plan_id: str, season_final: bool = False) -> Dict[str, Any]:
        return get_success_data(
            self.api.close_day(
                day_plan_id, DIRECTOR_HEADERS, f.close_day_payload(season_final)
            )
        )

    def decide_opening(self, area_id: str, decision: str = "OPEN") -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_opening(
                area_id, f.opening_decision_payload(decision), DIRECTOR_HEADERS
            )
        )

    # ─── Guest admission ──────────────────────────────
    def create_reservation(
        self,
        day_plan_id: str,
        expected_day_plan_version: Optional[int] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        version = (
            expected_day_plan_version
            if expected_day_plan_version is not None
            else self.day_plan_version(day_plan_id)
        )
        return get_success_data(
            self.api.create_reservation(
                f.reservation_payload(day_plan_id, version, **overrides),
                GUEST_SERVICES_HEADERS,
            )
        )

    def check_in(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.check_in_reservation(reservation_id, GUEST_SERVICES_HEADERS)
        )

    def release_reservation(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.release_reservation(reservation_id, GUEST_SERVICES_HEADERS)
        )

    # ─── Composite states ─────────────────────────────
    def ready_area(
        self,
        season_overrides: Optional[Dict[str, Any]] = None,
        lift_overrides: Optional[Dict[str, Any]] = None,
        area_overrides: Optional[Dict[str, Any]] = None,
        passes_completed: int = 20,
        patroller_count: int = 2,
        blaster_certified: bool = False,
    ) -> Dict[str, Any]:
        """A season whose one terrain area has cleared every readiness gate: a
        measured base depth, a completed groom, and enough available patrollers,
        served by a lift on STANDBY with a current inspection."""
        season = self.create_season(**(season_overrides or {}))
        lift = self.ready_lift(season["id"], **(lift_overrides or {}))
        area = self.create_terrain_area(season["id"], lift["id"], **(area_overrides or {}))
        self.record_reading(area["id"], stake_code="S1", depth_in=40.0)
        self.groom_area(area["id"], passes_completed)
        patrollers = self.staff_patrol(
            season["id"], area["id"], patroller_count, blaster_certified=blaster_certified
        )
        return {
            "season": self.season(season["id"]),
            "lift": self.lift(lift["id"]),
            "area": self.area(area["id"]),
            "patrollers": patrollers,
            "season_id": season["id"],
            "lift_id": lift["id"],
            "area_id": area["id"],
            "patroller_ids": [row["id"] for row in patrollers],
        }

    def open_mountain(
        self,
        season_overrides: Optional[Dict[str, Any]] = None,
        lift_overrides: Optional[Dict[str, Any]] = None,
        area_overrides: Optional[Dict[str, Any]] = None,
        day_plan_overrides: Optional[Dict[str, Any]] = None,
        wind_speed_mph: float = 10.0,
        wet_bulb_f: float = 22.0,
        passes_completed: int = 20,
        patroller_count: int = 2,
        blaster_certified: bool = False,
        with_pump_house: bool = False,
        pump_house_overrides: Optional[Dict[str, Any]] = None,
        open_the_area: bool = True,
    ) -> Dict[str, Any]:
        """The whole mountain standing open: a published operating day carrying
        real weather, a lift in OPEN, and one terrain area in OPEN."""
        state = self.ready_area(
            season_overrides=season_overrides,
            lift_overrides=lift_overrides,
            area_overrides=area_overrides,
            passes_completed=passes_completed,
            patroller_count=patroller_count,
            blaster_certified=blaster_certified,
        )
        day_plan = self.create_day_plan(state["season_id"], **(day_plan_overrides or {}))
        self.publish_day_plan(day_plan["id"])
        self.post_weather(day_plan["id"], wind_speed_mph, wet_bulb_f)
        self.set_lift_status(state["lift_id"], "OPEN")
        if open_the_area:
            self.decide_opening(state["area_id"], "OPEN")
        if with_pump_house:
            pump_house = self.create_pump_house(
                state["season_id"], **(pump_house_overrides or {})
            )
            state["pump_house"] = self.pump_house(pump_house["id"])
            state["pump_house_id"] = pump_house["id"]
        state.update(
            {
                "day_plan": self.day_plan(day_plan["id"]),
                "day_plan_id": day_plan["id"],
                "season": self.season(state["season_id"]),
                "lift": self.lift(state["lift_id"]),
                "area": self.area(state["area_id"]),
            }
        )
        return state

    def operating_season(
        self,
        season_overrides: Optional[Dict[str, Any]] = None,
        day_plan_overrides: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """A published operating day with the area left in READY, for rules that
        need the season OPERATING without the area actually open."""
        return self.open_mountain(
            season_overrides=season_overrides,
            day_plan_overrides=day_plan_overrides,
            open_the_area=False,
            **kwargs,
        )

    def refresh(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Re-read every row a composite state holds, after a cascade."""
        refreshed = dict(state)
        if "season_id" in state:
            refreshed["season"] = self.season(state["season_id"])
        if "lift_id" in state:
            refreshed["lift"] = self.lift(state["lift_id"])
        if "area_id" in state:
            refreshed["area"] = self.area(state["area_id"])
        if "day_plan_id" in state:
            refreshed["day_plan"] = self.day_plan(state["day_plan_id"])
        if "pump_house_id" in state:
            refreshed["pump_house"] = self.pump_house(state["pump_house_id"])
        return refreshed


# ─── pytest fixtures ──────────────────────────────────

@pytest.fixture
def mountain(api: ApiClient) -> MountainScenario:
    """Scenario builder bound to the client under test."""
    return MountainScenario(api)


@pytest.fixture
def season(mountain: MountainScenario) -> Dict[str, Any]:
    """A freshly created season configuration, still in PRESEASON."""
    return mountain.create_season()


@pytest.fixture
def season_with_lift(mountain: MountainScenario) -> Dict[str, Any]:
    """A season with one registered lift, fresh out of registration."""
    season_row = mountain.create_season()
    lift_row = mountain.create_lift(season_row["id"])
    return {
        "season": season_row,
        "lift": lift_row,
        "season_id": season_row["id"],
        "lift_id": lift_row["id"],
    }


@pytest.fixture
def inventory(mountain: MountainScenario) -> Dict[str, Any]:
    """A season with a lift, a terrain area it serves and a pump house."""
    season_row = mountain.create_season()
    lift_row = mountain.create_lift(season_row["id"])
    area_row = mountain.create_terrain_area(season_row["id"], lift_row["id"])
    pump_house_row = mountain.create_pump_house(season_row["id"])
    return {
        "season": season_row,
        "lift": lift_row,
        "area": area_row,
        "pump_house": pump_house_row,
        "season_id": season_row["id"],
        "lift_id": lift_row["id"],
        "area_id": area_row["id"],
        "pump_house_id": pump_house_row["id"],
    }


@pytest.fixture
def ready_area(mountain: MountainScenario) -> Dict[str, Any]:
    """A terrain area that has cleared every readiness gate."""
    return mountain.ready_area()


@pytest.fixture
def open_mountain(mountain: MountainScenario) -> Dict[str, Any]:
    """A published operating day with one lift and one terrain area open."""
    return mountain.open_mountain()


@pytest.fixture
def open_mountain_with_plant(mountain: MountainScenario) -> Dict[str, Any]:
    """The open mountain plus an online pump house, ready to schedule snow."""
    return mountain.open_mountain(with_pump_house=True)


@pytest.fixture
def initial_clock() -> str:
    """The instant the logical clock reads before any call is made."""
    return INITIAL_CLOCK
