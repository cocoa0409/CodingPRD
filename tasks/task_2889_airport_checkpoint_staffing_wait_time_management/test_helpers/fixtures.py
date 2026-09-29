"""Composite state builders and pytest fixtures.

The harness restarts the API server before every individual test, so each test
starts against an empty database and every fixture here builds its state from
scratch through the public API.

Setup calls use the lenient ``get_success_data`` validator: a fixture that fails
should say which setup step broke, not assert a business rule.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import REQUIRED_EQUIPMENT_BY_LANE_TYPE
from .test_users import (
    ADMIN_HEADERS,
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    make_screening_officer_headers,
    make_supervisory_officer_headers,
)
from .types import Headers, JsonDict

# ── The canonical operational day used by the scenarios below ──────────────────
OPERATIONAL_DATE = "2026-09-10"
CLOCK_0800 = "2026-09-10T08:00:00Z"
CLOCK_1000 = "2026-09-10T10:00:00Z"
CLOCK_1020 = "2026-09-10T10:20:00Z"
CLOCK_1100 = "2026-09-10T11:00:00Z"
BAND_1000 = "2026-09-10T10:00:00Z"
BAND_1030 = "2026-09-10T10:30:00Z"
BAND_1100 = "2026-09-10T11:00:00Z"
BAND_1130 = "2026-09-10T11:30:00Z"
BAND_1200 = "2026-09-10T12:00:00Z"
FLIGHT_1030 = "2026-09-10T10:30:00Z"
FLIGHT_1230 = "2026-09-10T12:30:00Z"


@dataclass
class Scenario:
    """Incremental builder over the public API.

    Each ``build_*`` method performs the calls a state needs and records the
    resulting rows on the scenario, so a test can pick up wherever it needs to.
    """

    api: ApiClient
    checkpoint: Optional[JsonDict] = None
    curve: Optional[JsonDict] = None
    lane: Optional[JsonDict] = None
    units: Dict[str, JsonDict] = field(default_factory=dict)
    officer: Optional[JsonDict] = None
    supervisor: Optional[JsonDict] = None
    resolver: Optional[JsonDict] = None
    band: Optional[JsonDict] = None
    flight: Optional[JsonDict] = None
    plan: Optional[JsonDict] = None
    assignment: Optional[JsonDict] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    # ── Identity shortcuts ────────────────────────────────────────────────────
    @property
    def checkpoint_id(self) -> str:
        return self.checkpoint["id"]

    @property
    def lane_id(self) -> str:
        return self.lane["id"]

    @property
    def officer_id(self) -> str:
        return self.officer["id"]

    @property
    def supervisor_id(self) -> str:
        return self.supervisor["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def band_id(self) -> str:
        return self.band["id"]

    @property
    def assignment_id(self) -> str:
        return self.assignment["id"]

    @property
    def officer_headers(self) -> Headers:
        return make_screening_officer_headers(self.officer_id)

    @property
    def supervisor_headers(self) -> Headers:
        return make_supervisory_officer_headers(self.supervisor_id)

    # ── Primitive steps ───────────────────────────────────────────────────────
    def set_clock(self, current_utc: str) -> JsonDict:
        return get_success_data(
            self.api.set_clock(f.clock_payload(current_utc), ADMIN_HEADERS)
        )

    def create_checkpoint(self, **overrides: Any) -> JsonDict:
        data = get_success_data(
            self.api.create_checkpoint(f.checkpoint_payload(**overrides), ADMIN_HEADERS)
        )
        return data

    def create_curve(self, **kwargs: Any) -> JsonDict:
        return get_success_data(
            self.api.create_show_up_curve(f.show_up_curve_payload(**kwargs), ADMIN_HEADERS)
        )

    def create_lane(self, checkpoint_id: Optional[str] = None, **overrides: Any) -> JsonDict:
        return get_success_data(
            self.api.create_lane(
                f.lane_payload(checkpoint_id or self.checkpoint_id, **overrides),
                MANAGER_HEADERS,
            )
        )

    def install_unit(self, lane_id: str, equipment_type: str, **kwargs: Any) -> JsonDict:
        return get_success_data(
            self.api.create_equipment_unit(
                f.equipment_payload(lane_id, equipment_type, **kwargs), MANAGER_HEADERS
            )
        )

    def install_required_equipment(
        self,
        lane_id: str,
        lane_type: str = "STANDARD",
        serial_prefix: str = "L1",
        calibration_due_utc: str = f.FAR_FUTURE_CALIBRATION_UTC,
    ) -> Dict[str, JsonDict]:
        """Install every unit the lane's modality requires, all SERVICEABLE."""
        units: Dict[str, JsonDict] = {}
        for equipment_type in REQUIRED_EQUIPMENT_BY_LANE_TYPE[lane_type]:
            units[equipment_type] = self.install_unit(
                lane_id,
                equipment_type,
                serial_number=f"{serial_prefix}-{equipment_type}",
                calibration_due_utc=calibration_due_utc,
            )
        return units

    def open_lane(self, lane_id: Optional[str] = None, headers: Headers = MANAGER_HEADERS) -> JsonDict:
        return get_success_data(self.api.open_lane(lane_id or self.lane_id, headers))

    def create_officer(self, **kwargs: Any) -> JsonDict:
        return get_success_data(
            self.api.create_officer(f.officer_payload(**kwargs), ADMIN_HEADERS)
        )

    def set_duty_status(self, officer_id: str, duty_status: str) -> JsonDict:
        return get_success_data(
            self.api.set_officer_duty_status(
                officer_id, f.duty_status_payload(duty_status), MANAGER_HEADERS
            )
        )

    def create_band(self, band_start_utc: str, **kwargs: Any) -> JsonDict:
        return get_success_data(
            self.api.create_time_band(
                f.time_band_payload(self.checkpoint_id, band_start_utc, **kwargs),
                PLANNER_HEADERS,
            )
        )

    def create_flight(self, scheduled_departure_utc: str, **kwargs: Any) -> JsonDict:
        return get_success_data(
            self.api.create_flight_schedule_entry(
                f.flight_payload(
                    self.checkpoint_id,
                    self.curve["id"],
                    scheduled_departure_utc,
                    **kwargs,
                ),
                PLANNER_HEADERS,
            )
        )

    def forecast(self, band_id: str, variant: str = "CURVE_BLENDED") -> JsonDict:
        return get_success_data(
            self.api.forecast_time_band(band_id, f.forecast_payload(variant), PLANNER_HEADERS)
        )

    def checkpoint_version(self, checkpoint_id: Optional[str] = None) -> int:
        data = get_success_data(
            self.api.get_checkpoint(checkpoint_id or self.checkpoint_id, PLANNER_HEADERS)
        )
        return data["version"]

    def officer_version(self, officer_id: str) -> int:
        data = get_success_data(self.api.get_officer(officer_id, PLANNER_HEADERS))
        return data["version"]

    def create_plan(
        self,
        operational_date: str = OPERATIONAL_DATE,
        expected_checkpoint_version: Optional[int] = None,
        headers: Headers = PLANNER_HEADERS,
    ) -> JsonDict:
        version = (
            expected_checkpoint_version
            if expected_checkpoint_version is not None
            else self.checkpoint_version()
        )
        return get_success_data(
            self.api.create_staffing_plan(
                f.staffing_plan_payload(self.checkpoint_id, operational_date, version),
                headers,
            )
        )

    def create_assignment(
        self,
        plan_id: Optional[str] = None,
        lane_id: Optional[str] = None,
        officer_id: Optional[str] = None,
        band_id: Optional[str] = None,
        headers: Headers = PLANNER_HEADERS,
    ) -> JsonDict:
        return get_success_data(
            self.api.create_lane_assignment(
                f.lane_assignment_payload(
                    plan_id or self.plan_id,
                    lane_id or self.lane_id,
                    officer_id or self.officer_id,
                    band_id or self.band_id,
                ),
                headers,
            )
        )

    def submit_plan(self, plan_id: Optional[str] = None) -> JsonDict:
        return get_success_data(
            self.api.submit_staffing_plan(plan_id or self.plan_id, PLANNER_HEADERS)
        )

    def approve_plan(
        self, plan_id: Optional[str] = None, headers: Headers = DUTY_MANAGER_HEADERS
    ) -> JsonDict:
        return get_success_data(
            self.api.decide_staffing_plan(
                plan_id or self.plan_id, f.plan_decision_payload("APPROVE"), headers
            )
        )

    def reject_plan(
        self,
        plan_id: Optional[str] = None,
        rejection_reason_code: str = "COST",
        headers: Headers = DUTY_MANAGER_HEADERS,
    ) -> JsonDict:
        return get_success_data(
            self.api.decide_staffing_plan(
                plan_id or self.plan_id,
                f.plan_decision_payload("REJECT", rejection_reason_code),
                headers,
            )
        )

    def activate_plan(self, plan_id: Optional[str] = None) -> JsonDict:
        return get_success_data(
            self.api.staffing_plan_lifecycle(
                plan_id or self.plan_id, f.plan_lifecycle_payload("ACTIVATE"), MANAGER_HEADERS
            )
        )

    def close_plan(self, plan_id: Optional[str] = None) -> JsonDict:
        return get_success_data(
            self.api.staffing_plan_lifecycle(
                plan_id or self.plan_id, f.plan_lifecycle_payload("CLOSE"), MANAGER_HEADERS
            )
        )

    def check_in(
        self,
        assignment_id: Optional[str] = None,
        headers: Optional[Headers] = None,
    ) -> JsonDict:
        return get_success_data(
            self.api.assignment_duty(
                assignment_id or self.assignment_id,
                f.duty_action_payload("CHECK_IN"),
                headers or self.officer_headers,
            )
        )

    def raise_referral(
        self, lane_id: Optional[str] = None, headers: Optional[Headers] = None, **kwargs: Any
    ) -> JsonDict:
        return get_success_data(
            self.api.create_screening_referral(
                f.referral_payload(lane_id or self.lane_id, **kwargs),
                headers or self.supervisor_headers,
            )
        )

    def post_observation(
        self, headers: Optional[Headers] = None, **kwargs: Any
    ) -> JsonDict:
        return get_success_data(
            self.api.create_wait_observation(
                self.checkpoint_id,
                f.wait_observation_payload(**kwargs),
                headers or MANAGER_HEADERS,
            )
        )

    def request_detail(
        self,
        officer_id: Optional[str] = None,
        window_start_utc: str = "2026-09-10T12:00:00Z",
        detail_minutes: int = 30,
        expected_officer_version: Optional[int] = None,
        **kwargs: Any,
    ) -> JsonDict:
        target = officer_id or self.officer_id
        version = (
            expected_officer_version
            if expected_officer_version is not None
            else self.officer_version(target)
        )
        return get_success_data(
            self.api.create_surge_detail(
                f.surge_detail_payload(
                    self.plan_id, target, window_start_utc, detail_minutes, version, **kwargs
                ),
                PLANNER_HEADERS,
            )
        )

    def approve_detail(self, detail_id: str) -> JsonDict:
        return get_success_data(
            self.api.decide_surge_detail(
                detail_id, f.surge_decision_payload("APPROVE"), DUTY_MANAGER_HEADERS
            )
        )

    # ── Composite builders ────────────────────────────────────────────────────
    def build_base(self, clock: str = CLOCK_0800, **checkpoint_overrides: Any) -> "Scenario":
        """A logical clock, one checkpoint and the single-bucket show-up curve."""
        self.set_clock(clock)
        self.checkpoint = self.create_checkpoint(**checkpoint_overrides)
        self.curve = self.create_curve()
        return self

    def build_equipped_lane(
        self,
        lane_type: str = "STANDARD",
        position_index: int = 1,
        serial_prefix: str = "L1",
        calibration_due_utc: str = f.FAR_FUTURE_CALIBRATION_UTC,
        **lane_overrides: Any,
    ) -> "Scenario":
        """A CLOSED lane carrying every unit its modality requires."""
        lane = self.create_lane(
            lane_type=lane_type, position_index=position_index, **lane_overrides
        )
        units = self.install_required_equipment(
            lane["id"],
            lane_type=lane_type,
            serial_prefix=serial_prefix,
            calibration_due_utc=calibration_due_utc,
        )
        if self.lane is None:
            self.lane, self.units = lane, units
        self.extras.setdefault("lanes", []).append(lane)
        self.extras.setdefault("lane_units", []).append(units)
        return self

    def build_open_lane(self) -> "Scenario":
        self.lane = self.open_lane()
        return self

    def build_officer(self) -> "Scenario":
        """Officer Ada: standard-lane and advanced-imaging certified."""
        self.officer = self.create_officer(
            badge_number="B-1001",
            full_name="Ada Lane",
            certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
            base_rate_cents_per_minute=100,
            weekly_regular_minutes_cap=45,
            weekly_overtime_minutes_cap=600,
        )
        return self

    def build_supervisor(self, on_duty: bool = False) -> "Scenario":
        """Supervisor Sam, who holds SUPERVISOR among their certifications."""
        self.supervisor = self.create_officer(
            badge_number="B-2001",
            full_name="Sam Sup",
            certifications=[
                "STANDARD_LANE",
                "SUPERVISOR",
                "SPECIAL_PROCEDURES",
                "ETD_RESOLUTION",
            ],
            base_rate_cents_per_minute=120,
            weekly_regular_minutes_cap=2400,
            weekly_overtime_minutes_cap=600,
        )
        if on_duty:
            self.supervisor = self.set_duty_status(self.supervisor["id"], "ON_DUTY")
        return self

    def build_resolver(self, on_duty: bool = True) -> "Scenario":
        """A second officer who may work a secondary screening."""
        self.resolver = self.create_officer(
            badge_number="B-2002",
            full_name="Rin Res",
            certifications=["STANDARD_LANE", "SPECIAL_PROCEDURES", "ETD_RESOLUTION"],
            base_rate_cents_per_minute=110,
            weekly_regular_minutes_cap=2400,
            weekly_overtime_minutes_cap=600,
        )
        if on_duty:
            self.resolver = self.set_duty_status(self.resolver["id"], "ON_DUTY")
        return self

    def build_forecast_band(
        self,
        band_start_utc: str = BAND_1000,
        flight_departure_utc: Optional[str] = FLIGHT_1030,
        seats_sold: int = 10,
        variant: str = "CURVE_BLENDED",
        **band_overrides: Any,
    ) -> "Scenario":
        """One band, one flight feeding it, and the band forecast already run."""
        band = self.create_band(band_start_utc, **band_overrides)
        if flight_departure_utc is not None:
            self.flight = self.create_flight(flight_departure_utc, seats_sold=seats_sold)
        band = self.forecast(band["id"], variant)
        if self.band is None:
            self.band = band
        self.extras.setdefault("bands", []).append(band)
        return self

    def build_draft_plan(self, operational_date: str = OPERATIONAL_DATE) -> "Scenario":
        self.plan = self.create_plan(operational_date=operational_date)
        return self

    def build_assignment(self, **kwargs: Any) -> "Scenario":
        assignment = self.create_assignment(**kwargs)
        if self.assignment is None:
            self.assignment = assignment
        self.extras.setdefault("assignments", []).append(assignment)
        return self

    def build_submitted_plan(self) -> "Scenario":
        self.plan = self.submit_plan()
        return self

    def build_approved_plan(self) -> "Scenario":
        self.plan = self.approve_plan()
        return self

    def build_activated_plan(self) -> "Scenario":
        self.plan = self.activate_plan()
        return self

    def build_checked_in(self) -> "Scenario":
        self.assignment = self.check_in()
        return self

    def build_raised_ticket(self, lane_type: str = "STANDARD") -> JsonDict:
        """Two consecutive breaching publications, which raise one ticket."""
        headers = self.supervisor_headers if self.supervisor else MANAGER_HEADERS
        self.post_observation(
            headers=headers,
            lane_type=lane_type,
            sampled_wait_seconds=1200,
            measurement_method="BLE_SENSOR",
            sample_size=10,
        )
        self.post_observation(
            headers=headers,
            lane_type=lane_type,
            sampled_wait_seconds=1200,
            measurement_method="BLE_SENSOR",
            sample_size=10,
        )
        rows = get_success_data(
            self.api.list_escalation_tickets(
                MANAGER_HEADERS,
                {"checkpoint_id": self.checkpoint_id, "lane_type_scope": lane_type},
            )
        )
        assert rows, "setup expected one escalation ticket to have been raised"
        ticket = rows[0]
        self.extras["ticket"] = ticket
        return ticket


# ── pytest fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def scenario(api: ApiClient) -> Scenario:
    """An empty scenario builder against a freshly started server."""
    return Scenario(api=api)


@pytest.fixture
def base(scenario: Scenario) -> Scenario:
    """Clock at 08:00, one checkpoint, one show-up curve."""
    return scenario.build_base()


@pytest.fixture
def closed_lane_floor(base: Scenario) -> Scenario:
    """A CLOSED lane at position 1 with all three required units installed."""
    return base.build_equipped_lane()


@pytest.fixture
def open_lane_floor(closed_lane_floor: Scenario) -> Scenario:
    """The same floor with lane 1 OPEN."""
    return closed_lane_floor.build_open_lane()


@pytest.fixture
def staffed_floor(open_lane_floor: Scenario) -> Scenario:
    """An OPEN lane plus officer Ada."""
    return open_lane_floor.build_officer()


@pytest.fixture
def supervised_floor(open_lane_floor: Scenario) -> Scenario:
    """An OPEN lane plus an on-duty SUPERVISOR-certified officer."""
    return open_lane_floor.build_supervisor(on_duty=True)


@pytest.fixture
def forecast_floor(staffed_floor: Scenario) -> Scenario:
    """An OPEN lane, officer Ada, and the 10:00 band forecast at 10 passengers."""
    return staffed_floor.build_forecast_band()


@pytest.fixture
def draft_plan_floor(forecast_floor: Scenario) -> Scenario:
    """A DRAFT plan for the operational day, prepared by planner-1."""
    return forecast_floor.build_draft_plan()


@pytest.fixture
def plan_with_assignment(draft_plan_floor: Scenario) -> Scenario:
    """A DRAFT plan carrying one SCHEDULED assignment for the 10:00 band."""
    return draft_plan_floor.build_assignment()


@pytest.fixture
def submitted_plan(plan_with_assignment: Scenario) -> Scenario:
    """The same plan SUBMITTED and therefore priced."""
    return plan_with_assignment.build_submitted_plan()


@pytest.fixture
def approved_plan(submitted_plan: Scenario) -> Scenario:
    """The plan APPROVED by duty-1, who did not prepare it."""
    return submitted_plan.build_approved_plan()


@pytest.fixture
def activated_plan(approved_plan: Scenario) -> Scenario:
    """The plan ACTIVATED, so its assignment may be checked into."""
    return approved_plan.build_activated_plan()


@pytest.fixture
def checked_in_assignment(activated_plan: Scenario) -> Scenario:
    """Officer Ada checked in on the 10:00 assignment at the 08:00 clock."""
    return activated_plan.build_checked_in()


@pytest.fixture
def raised_ticket(supervised_floor: Scenario) -> Scenario:
    """Two breaching standard-queue publications, so one ticket is RAISED."""
    supervised_floor.build_raised_ticket()
    return supervised_floor


@pytest.fixture
def acknowledged_ticket(raised_ticket: Scenario) -> Scenario:
    """The raised ticket ACKNOWLEDGED by the supervisor."""
    ticket = raised_ticket.extras["ticket"]
    raised_ticket.extras["ticket"] = get_success_data(
        raised_ticket.api.acknowledge_escalation_ticket(
            ticket["id"], raised_ticket.supervisor_headers
        )
    )
    return raised_ticket
