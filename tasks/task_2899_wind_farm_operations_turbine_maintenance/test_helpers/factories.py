"""Request-payload builders.

Every monetary amount is emitted as a JSON number of cents, never a string.
Every field the contract declares as an instant is emitted as a full ISO 8601
UTC instant, never a bare calendar date; ``commissioning_date`` is the single
declared calendar date and is emitted as ``YYYY-MM-DD``.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    BASIS_TIME_BASED,
    CERT_CRANE_BANKSMAN,
    CERT_GWO_BASIC,
    COMPONENT_GEARBOX,
    CRANE_CRAWLER_600T,
    CURTAILMENT_REASON_GRID,
    DAMAGE_DELAMINATION,
    INSPECTION_DRONE,
    ROYALTY_METERED_ONLY,
    SEVERITY_RESETTABLE,
    WORK_TYPE_MAJOR_COMPONENT,
)

Payload = Dict[str, Any]

_counter = itertools.count(1)


def _seq() -> int:
    """Monotonic suffix source for the identifiers the contract requires unique."""
    return next(_counter)


# ---------------------------------------------------------------------------
# Wind farms
# ---------------------------------------------------------------------------
def farm_payload(
    name: str = "Cedar Bluff",
    region_code: str = "KS-W",
    grid_operator_code: str = "SPP",
    landowner_budget_cap_cents: int = 500000000,
    road_levy_pct: Optional[float] = None,
    community_levy_pct: Optional[float] = None,
    **overrides: Any,
) -> Payload:
    """A wind farm creation body; both levies are omitted unless supplied."""
    payload: Payload = {
        "name": name,
        "region_code": region_code,
        "grid_operator_code": grid_operator_code,
        "landowner_budget_cap_cents": landowner_budget_cap_cents,
    }
    if road_levy_pct is not None:
        payload["road_levy_pct"] = road_levy_pct
    if community_levy_pct is not None:
        payload["community_levy_pct"] = community_levy_pct
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Turbine models
# ---------------------------------------------------------------------------
def turbine_model_payload(
    model_code: str = "V150-4.2",
    rated_power_kw: float = 4200,
    hub_height_m: float = 105,
    rotor_diameter_m: float = 150,
    service_interval_hours: float = 4000,
    service_interval_tolerance_hours: float = 250,
    gearbox_lead_time_days: int = 210,
    blade_lead_time_days: int = 150,
    generator_lead_time_days: int = 120,
    **overrides: Any,
) -> Payload:
    """A turbine model creation body."""
    payload: Payload = {
        "model_code": model_code,
        "rated_power_kw": rated_power_kw,
        "hub_height_m": hub_height_m,
        "rotor_diameter_m": rotor_diameter_m,
        "service_interval_hours": service_interval_hours,
        "service_interval_tolerance_hours": service_interval_tolerance_hours,
        "gearbox_lead_time_days": gearbox_lead_time_days,
        "blade_lead_time_days": blade_lead_time_days,
        "generator_lead_time_days": generator_lead_time_days,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Turbines
# ---------------------------------------------------------------------------
def turbine_payload(
    turbine_model_id: str,
    asset_tag: str = "T-01",
    commissioning_date: str = "2024-05-15",
    expected_kwh_per_hour: float = 2000,
    operating_hours: Optional[float] = None,
    last_service_operating_hours: Optional[float] = None,
    **overrides: Any,
) -> Payload:
    """A turbine commissioning body; both hour counters are omitted unless supplied."""
    payload: Payload = {
        "turbine_model_id": turbine_model_id,
        "asset_tag": asset_tag,
        "commissioning_date": commissioning_date,
        "expected_kwh_per_hour": expected_kwh_per_hour,
    }
    if operating_hours is not None:
        payload["operating_hours"] = operating_hours
    if last_service_operating_hours is not None:
        payload["last_service_operating_hours"] = last_service_operating_hours
    payload.update(overrides)
    return payload


def scada_payload(
    operating_hours_delta: float,
    actual_energy_kwh: float,
    potential_energy_kwh: float,
) -> Payload:
    """A telemetry posting body; all three figures are additive."""
    return {
        "operating_hours_delta": operating_hours_delta,
        "actual_energy_kwh": actual_energy_kwh,
        "potential_energy_kwh": potential_energy_kwh,
    }


# ---------------------------------------------------------------------------
# Fault code rules and events
# ---------------------------------------------------------------------------
def fault_code_rule_payload(
    fault_code: str = "F-3001",
    severity_class: str = SEVERITY_RESETTABLE,
    max_remote_resets_per_24h: int = 2,
    requires_dispatch: bool = False,
    contractual_exclusion: bool = False,
    **overrides: Any,
) -> Payload:
    """A fault code rule creation body."""
    payload: Payload = {
        "fault_code": fault_code,
        "severity_class": severity_class,
        "max_remote_resets_per_24h": max_remote_resets_per_24h,
        "requires_dispatch": requires_dispatch,
        "contractual_exclusion": contractual_exclusion,
    }
    payload.update(overrides)
    return payload


def fault_code_rule_amendment_payload(
    max_remote_resets_per_24h: Optional[int] = None,
    requires_dispatch: Optional[bool] = None,
    contractual_exclusion: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    """An amendment body over the three amendable rule fields; each one is optional."""
    payload: Payload = {}
    if max_remote_resets_per_24h is not None:
        payload["max_remote_resets_per_24h"] = max_remote_resets_per_24h
    if requires_dispatch is not None:
        payload["requires_dispatch"] = requires_dispatch
    if contractual_exclusion is not None:
        payload["contractual_exclusion"] = contractual_exclusion
    payload.update(overrides)
    return payload


def fault_event_payload(fault_code: str = "F-3001", raised_at: str = "2026-08-01T00:00:00Z") -> Payload:
    """A fault raise body; the raise instant is a full UTC instant."""
    return {"fault_code": fault_code, "raised_at": raised_at}


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------
def crew_payload(
    wind_farm_id: str,
    crew_code: str = "C-ALPHA",
    technician_count: int = 4,
    certifications: Optional[List[str]] = None,
    max_work_wind_speed_ms: float = 14.0,
    daily_hours_capacity: float = 40,
    hourly_rate_cents: int = 90000,
    status: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A crew creation body; the status is omitted unless supplied."""
    payload: Payload = {
        "wind_farm_id": wind_farm_id,
        "crew_code": crew_code,
        "technician_count": technician_count,
        "certifications": (
            list(certifications)
            if certifications is not None
            else [CERT_GWO_BASIC, CERT_CRANE_BANKSMAN]
        ),
        "max_work_wind_speed_ms": max_work_wind_speed_ms,
        "daily_hours_capacity": daily_hours_capacity,
        "hourly_rate_cents": hourly_rate_cents,
    }
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Weather windows
# ---------------------------------------------------------------------------
def weather_window_payload(
    wind_farm_id: str,
    start_utc: str = "2026-08-10T00:00:00Z",
    end_utc: str = "2026-08-11T00:00:00Z",
    forecast_wind_speed_ms: float = 8.0,
    forecast_gust_ms: float = 11.0,
    icing_risk: bool = False,
    **overrides: Any,
) -> Payload:
    """A weather window creation body over a half-open interval."""
    payload: Payload = {
        "wind_farm_id": wind_farm_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "forecast_wind_speed_ms": forecast_wind_speed_ms,
        "forecast_gust_ms": forecast_gust_ms,
        "icing_risk": icing_risk,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------
def work_order_payload(
    turbine_id: str,
    work_type: str = WORK_TYPE_MAJOR_COMPONENT,
    required_certification: str = CERT_CRANE_BANKSMAN,
    estimated_hours: float = 8,
    fault_event_id: Optional[str] = None,
    blade_damage_id: Optional[str] = None,
    parent_work_order_id: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A work order creation body; the three optional links are omitted unless supplied."""
    payload: Payload = {
        "turbine_id": turbine_id,
        "work_type": work_type,
        "required_certification": required_certification,
        "estimated_hours": estimated_hours,
    }
    if fault_event_id is not None:
        payload["fault_event_id"] = fault_event_id
    if blade_damage_id is not None:
        payload["blade_damage_id"] = blade_damage_id
    if parent_work_order_id is not None:
        payload["parent_work_order_id"] = parent_work_order_id
    payload.update(overrides)
    return payload


def schedule_payload(
    crew_id: str,
    weather_window_id: str,
    planned_start_utc: str,
    planned_end_utc: str,
) -> Payload:
    """A scheduling body naming the crew, the window and the planned interval."""
    return {
        "crew_id": crew_id,
        "weather_window_id": weather_window_id,
        "planned_start_utc": planned_start_utc,
        "planned_end_utc": planned_end_utc,
    }


# ---------------------------------------------------------------------------
# Cranes, spare parts and replacements
# ---------------------------------------------------------------------------
def crane_payload(
    wind_farm_id: str,
    crane_class: str = CRANE_CRAWLER_600T,
    mobilization_start_utc: str = "2026-08-10T00:00:00Z",
    demobilization_end_utc: str = "2026-08-12T00:00:00Z",
    day_rate_cents: int = 3800000,
    mobilization_fee_cents: int = 12000000,
    max_lift_wind_speed_ms: float = 9.0,
    **overrides: Any,
) -> Payload:
    """A crane mobilization request body; both rates are integer cents."""
    payload: Payload = {
        "wind_farm_id": wind_farm_id,
        "crane_class": crane_class,
        "mobilization_start_utc": mobilization_start_utc,
        "demobilization_end_utc": demobilization_end_utc,
        "day_rate_cents": day_rate_cents,
        "mobilization_fee_cents": mobilization_fee_cents,
        "max_lift_wind_speed_ms": max_lift_wind_speed_ms,
    }
    payload.update(overrides)
    return payload


def spare_part_payload(
    component_type: str = COMPONENT_GEARBOX,
    part_number: Optional[str] = None,
    quantity_on_hand: int = 2,
    lead_time_days: int = 210,
    reorder_point: int = 2,
    unit_cost_cents: int = 25000000,
    uptower_repairable: bool = False,
    **overrides: Any,
) -> Payload:
    """A spare part creation body; the part number is unique per call unless supplied."""
    payload: Payload = {
        "component_type": component_type,
        "part_number": part_number if part_number is not None else f"PN-{_seq():04d}",
        "quantity_on_hand": quantity_on_hand,
        "lead_time_days": lead_time_days,
        "reorder_point": reorder_point,
        "unit_cost_cents": unit_cost_cents,
        "uptower_repairable": uptower_repairable,
    }
    payload.update(overrides)
    return payload


def replacement_payload(
    work_order_id: str,
    spare_part_id: str,
    component_type: str = COMPONENT_GEARBOX,
    estimated_lift_hours: float = 12,
    uptower_labor_hours: Optional[float] = None,
    **overrides: Any,
) -> Payload:
    """A component replacement planning body."""
    payload: Payload = {
        "work_order_id": work_order_id,
        "spare_part_id": spare_part_id,
        "component_type": component_type,
        "estimated_lift_hours": estimated_lift_hours,
    }
    if uptower_labor_hours is not None:
        payload["uptower_labor_hours"] = uptower_labor_hours
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Blade findings
# ---------------------------------------------------------------------------
def blade_damage_payload(
    inspection_method: str = INSPECTION_DRONE,
    blade_position: str = "A",
    inspected_at: str = "2026-08-01T00:00:00Z",
    damage_category: int = 3,
    damage_type: str = DAMAGE_DELAMINATION,
    chord_position_pct: float = 35.0,
    damage_length_mm: float = 700,
    exposed_area_cm2: float = 1000,
    **overrides: Any,
) -> Payload:
    """A blade finding body; the inspection stamp is a full UTC instant."""
    payload: Payload = {
        "inspection_method": inspection_method,
        "blade_position": blade_position,
        "inspected_at": inspected_at,
        "damage_category": damage_category,
        "damage_type": damage_type,
        "chord_position_pct": chord_position_pct,
        "damage_length_mm": damage_length_mm,
        "exposed_area_cm2": exposed_area_cm2,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service agreements
# ---------------------------------------------------------------------------
def service_agreement_payload(
    wind_farm_id: str,
    guaranteed_availability_pct: float = 97.0,
    availability_basis: str = BASIS_TIME_BASED,
    lda_rate_cents_per_pct_point: int = 500000,
    lda_cap_cents: int = 20000000,
    period_start_utc: str = "2026-06-01T00:00:00Z",
    period_end_utc: str = "2026-07-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    """A service agreement creation body; both money figures are integer cents."""
    payload: Payload = {
        "wind_farm_id": wind_farm_id,
        "guaranteed_availability_pct": guaranteed_availability_pct,
        "availability_basis": availability_basis,
        "lda_rate_cents_per_pct_point": lda_rate_cents_per_pct_point,
        "lda_cap_cents": lda_cap_cents,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Curtailment orders
# ---------------------------------------------------------------------------
def curtailment_payload(
    expected_turbine_version: int,
    reason: str = CURTAILMENT_REASON_GRID,
    start_utc: str = "2026-08-01T00:00:00Z",
    end_utc: str = "2026-08-02T00:00:00Z",
    power_limit_kw: float = 1500,
    deemed_kwh_per_hour: float = 500,
    **overrides: Any,
) -> Payload:
    """A curtailment issue body; the guard version is mandatory, never optional."""
    payload: Payload = {
        "reason": reason,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "power_limit_kw": power_limit_kw,
        "deemed_kwh_per_hour": deemed_kwh_per_hour,
        "expected_turbine_version": expected_turbine_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Landowner settlements
# ---------------------------------------------------------------------------
def landowner_settlement_payload(
    expected_wind_farm_version: int,
    parcel_code: str = "P-14",
    royalty_basis: str = ROYALTY_METERED_ONLY,
    period_start_utc: str = "2026-07-01T00:00:00Z",
    period_end_utc: str = "2026-08-01T00:00:00Z",
    royalty_pct: float = 4.0,
    minimum_payment_cents: int = 200000,
    energy_price_cents_per_kwh: float = 6,
    road_damage_assessment_cents: int = 15000,
    **overrides: Any,
) -> Payload:
    """A landowner settlement drafting body; the guard version is mandatory."""
    payload: Payload = {
        "parcel_code": parcel_code,
        "royalty_basis": royalty_basis,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "royalty_pct": royalty_pct,
        "minimum_payment_cents": minimum_payment_cents,
        "energy_price_cents_per_kwh": energy_price_cents_per_kwh,
        "road_damage_assessment_cents": road_damage_assessment_cents,
        "expected_wind_farm_version": expected_wind_farm_version,
    }
    payload.update(overrides)
    return payload
