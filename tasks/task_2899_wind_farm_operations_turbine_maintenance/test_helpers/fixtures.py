"""Composite setup helpers.

The harness restarts the API before every test, so each test begins against an
empty store.  Every helper below therefore builds its state from scratch through
the public endpoints; nothing is seeded out of band.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import WindOpsApiClient
from .constants import (
    CERT_CRANE_BANKSMAN,
    CERT_GWO_BASIC,
    CURTAILMENT_REASON_NOISE,
    DAMAGE_LEADING_EDGE_EROSION,
    DISPOSITION_DISPATCH,
    DISPOSITION_REMOTE_RESET,
    INSPECTION_DRONE,
    RESET_OUTCOME_SUCCEEDED,
    ROYALTY_METERED_ONLY,
    SEVERITY_LOCKOUT,
    SEVERITY_RESETTABLE,
    WORK_TYPE_MAJOR_COMPONENT,
)
from .test_users import (
    ENGINEER_2_USER_ID,
    make_commercial_headers,
    make_control_room_headers,
    make_crew_lead_headers,
    make_engineer_headers,
    make_planner_headers,
    make_site_admin_headers,
)

Row = Dict[str, Any]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(client: WindOpsApiClient, current_utc: str) -> Row:
    """Advance the logical clock to ``current_utc``."""
    return get_success_data(client.set_clock(current_utc, make_site_admin_headers()))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def create_farm(client: WindOpsApiClient, **kwargs: Any) -> Row:
    """Register a wind farm."""
    return get_success_data(
        client.create_farm(f.farm_payload(**kwargs), make_site_admin_headers())
    )


def create_model(client: WindOpsApiClient, **kwargs: Any) -> Row:
    """Register a turbine model."""
    return get_success_data(
        client.create_turbine_model(f.turbine_model_payload(**kwargs), make_site_admin_headers())
    )


def create_turbine(
    client: WindOpsApiClient, farm_id: str, model_id: str, **kwargs: Any
) -> Row:
    """Commission a turbine on ``farm_id`` against ``model_id``."""
    return get_success_data(
        client.create_turbine(
            farm_id, f.turbine_payload(model_id, **kwargs), make_site_admin_headers()
        )
    )


def create_crew(client: WindOpsApiClient, farm_id: str, **kwargs: Any) -> Row:
    """Register a crew on ``farm_id``."""
    return get_success_data(
        client.create_crew(f.crew_payload(farm_id, **kwargs), make_site_admin_headers())
    )


def create_fault_rule(client: WindOpsApiClient, **kwargs: Any) -> Row:
    """Register a fault code rule."""
    return get_success_data(
        client.create_fault_code_rule(
            f.fault_code_rule_payload(**kwargs), make_site_admin_headers()
        )
    )


def amend_fault_rule(client: WindOpsApiClient, rule_id: str, **kwargs: Any) -> Row:
    """Amend the three amendable fields of a registered fault code rule."""
    return get_success_data(
        client.patch_fault_code_rule(
            rule_id, f.fault_code_rule_amendment_payload(**kwargs), make_site_admin_headers()
        )
    )


def create_spare_part(client: WindOpsApiClient, **kwargs: Any) -> Row:
    """Register a spare part line."""
    return get_success_data(
        client.create_spare_part(f.spare_part_payload(**kwargs), make_site_admin_headers())
    )


def base_site(client: WindOpsApiClient, **farm_kwargs: Any) -> Dict[str, Row]:
    """A farm, one turbine model and one turbine commissioned on it."""
    farm = create_farm(client, **farm_kwargs)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    return {"farm": farm, "model": model, "turbine": turbine}


# ---------------------------------------------------------------------------
# Telemetry and faults
# ---------------------------------------------------------------------------
def post_scada(
    client: WindOpsApiClient,
    turbine_id: str,
    operating_hours_delta: float,
    actual_energy_kwh: float,
    potential_energy_kwh: float,
) -> Row:
    """Post one telemetry sample against ``turbine_id``."""
    return get_success_data(
        client.scada_sync(
            turbine_id,
            f.scada_payload(operating_hours_delta, actual_energy_kwh, potential_energy_kwh),
            make_control_room_headers(),
        )
    )


def raise_fault(
    client: WindOpsApiClient,
    turbine_id: str,
    fault_code: str = "F-3001",
    raised_at: str = "2026-08-01T00:00:00Z",
) -> Row:
    """Raise a fault event against ``turbine_id``."""
    return get_success_data(
        client.raise_fault_event(
            turbine_id, f.fault_event_payload(fault_code, raised_at), make_control_room_headers()
        )
    )


def triage(client: WindOpsApiClient, event_id: str, disposition: str) -> Row:
    """Triage a fault event with the given disposition."""
    return get_success_data(
        client.triage_fault_event(event_id, disposition, make_control_room_headers())
    )


def remote_reset(
    client: WindOpsApiClient, event_id: str, reset_outcome: str = RESET_OUTCOME_SUCCEEDED
) -> Row:
    """Attempt a remote reset against a reset-pending fault event."""
    return get_success_data(
        client.remote_reset(event_id, reset_outcome, make_control_room_headers())
    )


def close_fault(client: WindOpsApiClient, event_id: str) -> Row:
    """Close a cleared fault event, admitting its downtime and lost energy."""
    return get_success_data(client.close_fault_event(event_id, make_engineer_headers()))


def cleared_fault_event(
    client: WindOpsApiClient,
    turbine_id: str,
    fault_code: str = "F-3001",
    raised_at: str = "2026-08-01T00:00:00Z",
) -> Row:
    """Raise a fault and drive it through remote reset to CLEARED."""
    event = raise_fault(client, turbine_id, fault_code, raised_at)
    triage(client, event["id"], DISPOSITION_REMOTE_RESET)
    return remote_reset(client, event["id"], RESET_OUTCOME_SUCCEEDED)


def dispatch_required_fault_event(
    client: WindOpsApiClient,
    turbine_id: str,
    fault_code: str = "F-3001",
    raised_at: str = "2026-08-01T00:00:00Z",
) -> Row:
    """Raise a fault and triage it for dispatch."""
    event = raise_fault(client, turbine_id, fault_code, raised_at)
    return triage(client, event["id"], DISPOSITION_DISPATCH)


# ---------------------------------------------------------------------------
# Weather windows
# ---------------------------------------------------------------------------
def create_window(client: WindOpsApiClient, farm_id: str, **kwargs: Any) -> Row:
    """Open a forecast weather window on ``farm_id``."""
    return get_success_data(
        client.create_weather_window(
            f.weather_window_payload(farm_id, **kwargs), make_planner_headers()
        )
    )


def confirmed_window(client: WindOpsApiClient, farm_id: str, **kwargs: Any) -> Row:
    """Open and confirm a weather window on ``farm_id``."""
    window = create_window(client, farm_id, **kwargs)
    return get_success_data(client.confirm_weather_window(window["id"], make_planner_headers()))


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------
def create_work_order(
    client: WindOpsApiClient,
    turbine_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Raise a draft work order against ``turbine_id``."""
    return get_success_data(
        client.create_work_order(
            f.work_order_payload(turbine_id, **kwargs), headers or make_planner_headers()
        )
    )


def submitted_work_order(
    client: WindOpsApiClient,
    turbine_id: str,
    submitter: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Raise a work order and submit it, stamping the acting submitter."""
    order = create_work_order(client, turbine_id, **kwargs)
    return get_success_data(
        client.submit_work_order(order["id"], submitter or make_planner_headers())
    )


def scheduled_work_order(
    client: WindOpsApiClient,
    turbine_id: str,
    crew_id: str,
    window_id: str,
    planned_start_utc: str,
    planned_end_utc: str,
    submitter: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Raise, submit and schedule a work order into a confirmed window."""
    order = submitted_work_order(client, turbine_id, submitter=submitter, **kwargs)
    return get_success_data(
        client.schedule_work_order(
            order["id"],
            f.schedule_payload(crew_id, window_id, planned_start_utc, planned_end_utc),
            make_planner_headers(),
        )
    )


def in_progress_work_order(
    client: WindOpsApiClient,
    turbine_id: str,
    crew_id: str,
    window_id: str,
    planned_start_utc: str,
    planned_end_utc: str,
    submitter: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Drive a work order all the way to IN_PROGRESS, started by its assigned crew."""
    order = scheduled_work_order(
        client,
        turbine_id,
        crew_id,
        window_id,
        planned_start_utc,
        planned_end_utc,
        submitter=submitter,
        **kwargs,
    )
    return get_success_data(
        client.start_work_order(order["id"], make_crew_lead_headers(crew_id))
    )


def major_component_order_in_progress(
    client: WindOpsApiClient,
    turbine_id: str,
    farm_id: str,
    estimated_hours: float = 8,
    crew_kwargs: Optional[Dict[str, Any]] = None,
    window_kwargs: Optional[Dict[str, Any]] = None,
    planned_start_utc: str = "2026-08-10T06:00:00Z",
    planned_end_utc: str = "2026-08-10T14:00:00Z",
) -> Dict[str, Row]:
    """A crew, a confirmed window and a major-component order already IN_PROGRESS."""
    crew = create_crew(client, farm_id, **(crew_kwargs or {}))
    window = confirmed_window(client, farm_id, **(window_kwargs or {}))
    order = in_progress_work_order(
        client,
        turbine_id,
        crew["id"],
        window["id"],
        planned_start_utc,
        planned_end_utc,
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=estimated_hours,
    )
    return {"crew": crew, "window": window, "order": order}


# ---------------------------------------------------------------------------
# Cranes and replacements
# ---------------------------------------------------------------------------
def create_crane(client: WindOpsApiClient, farm_id: str, **kwargs: Any) -> Row:
    """Request a crane mobilization slot on ``farm_id``."""
    return get_success_data(
        client.create_crane_mobilization(f.crane_payload(farm_id, **kwargs), make_planner_headers())
    )


def create_replacement(
    client: WindOpsApiClient, work_order_id: str, spare_part_id: str, **kwargs: Any
) -> Row:
    """Plan a component replacement, reserving one unit of the named part."""
    return get_success_data(
        client.create_component_replacement(
            f.replacement_payload(work_order_id, spare_part_id, **kwargs),
            make_planner_headers(),
        )
    )


def reserve_crane(client: WindOpsApiClient, replacement_id: str, crane_id: str) -> Row:
    """Take the crane-lift branch for a planned replacement."""
    return get_success_data(
        client.reserve_crane(replacement_id, crane_id, make_planner_headers())
    )


def plan_uptower(client: WindOpsApiClient, replacement_id: str) -> Row:
    """Take the up-tower branch for a planned replacement."""
    return get_success_data(client.plan_uptower(replacement_id, make_planner_headers()))


def execute_replacement(
    client: WindOpsApiClient, replacement_id: str, headers: Optional[Dict[str, str]] = None
) -> Row:
    """Execute a reserved replacement, consuming its unit."""
    return get_success_data(
        client.execute_replacement(replacement_id, headers or make_engineer_headers())
    )


# ---------------------------------------------------------------------------
# Blade findings
# ---------------------------------------------------------------------------
def record_blade_damage(
    client: WindOpsApiClient,
    turbine_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Record a blade finding against ``turbine_id``."""
    return get_success_data(
        client.record_blade_damage(
            turbine_id, f.blade_damage_payload(**kwargs), headers or make_engineer_headers()
        )
    )


def prioritized_blade_damage(
    client: WindOpsApiClient,
    turbine_id: str,
    recorder: Optional[Dict[str, str]] = None,
    prioritizer: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Row:
    """Record a blade finding and have a different actor prioritize it."""
    finding = record_blade_damage(client, turbine_id, headers=recorder, **kwargs)
    return get_success_data(
        client.prioritize_blade_damage(
            finding["id"], prioritizer or make_engineer_headers(ENGINEER_2_USER_ID)
        )
    )


# ---------------------------------------------------------------------------
# Commercial
# ---------------------------------------------------------------------------
def create_agreement(client: WindOpsApiClient, farm_id: str, **kwargs: Any) -> Row:
    """Register a service agreement on ``farm_id``."""
    return get_success_data(
        client.create_service_agreement(
            f.service_agreement_payload(farm_id, **kwargs), make_commercial_headers()
        )
    )


def create_curtailment(
    client: WindOpsApiClient, turbine_id: str, expected_turbine_version: int, **kwargs: Any
) -> Row:
    """Issue a pending curtailment order against ``turbine_id``."""
    return get_success_data(
        client.create_curtailment_order(
            turbine_id,
            f.curtailment_payload(expected_turbine_version, **kwargs),
            make_control_room_headers(),
        )
    )


def active_curtailment(
    client: WindOpsApiClient, turbine_id: str, expected_turbine_version: int, **kwargs: Any
) -> Row:
    """Issue and activate a curtailment order against ``turbine_id``."""
    order = create_curtailment(client, turbine_id, expected_turbine_version, **kwargs)
    return get_success_data(
        client.activate_curtailment_order(order["id"], make_control_room_headers())
    )


def create_settlement(
    client: WindOpsApiClient, farm_id: str, expected_wind_farm_version: int, **kwargs: Any
) -> Row:
    """Draft a landowner settlement on ``farm_id``."""
    return get_success_data(
        client.create_landowner_settlement(
            farm_id,
            f.landowner_settlement_payload(expected_wind_farm_version, **kwargs),
            make_commercial_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Read-back convenience
# ---------------------------------------------------------------------------
def read_farm(client: WindOpsApiClient, farm_id: str) -> Row:
    """Re-read a farm as its administrator."""
    return get_success_data(client.get_farm(farm_id, make_site_admin_headers()))


def read_turbine(client: WindOpsApiClient, turbine_id: str) -> Row:
    """Re-read a turbine as its administrator."""
    return get_success_data(client.get_turbine(turbine_id, make_site_admin_headers()))


def read_work_order(client: WindOpsApiClient, order_id: str) -> Row:
    """Re-read a work order as a planner."""
    return get_success_data(client.get_work_order(order_id, make_planner_headers()))


def read_crew(client: WindOpsApiClient, crew_id: str) -> Row:
    """Re-read a crew as a planner."""
    return get_success_data(client.get_crew(crew_id, make_planner_headers()))


def read_window(client: WindOpsApiClient, window_id: str) -> Row:
    """Re-read a weather window as a planner."""
    return get_success_data(client.get_weather_window(window_id, make_planner_headers()))


def read_fault_event(client: WindOpsApiClient, event_id: str) -> Row:
    """Re-read a fault event as a reliability engineer."""
    return get_success_data(client.get_fault_event(event_id, make_engineer_headers()))


def read_spare_part(client: WindOpsApiClient, part_id: str) -> Row:
    """Re-read a spare part line as a planner."""
    return get_success_data(client.get_spare_part(part_id, make_planner_headers()))


def read_crane(client: WindOpsApiClient, crane_id: str) -> Row:
    """Re-read a crane mobilization as a planner."""
    return get_success_data(client.get_crane_mobilization(crane_id, make_planner_headers()))


def read_replacement(client: WindOpsApiClient, replacement_id: str) -> Row:
    """Re-read a component replacement as a planner."""
    return get_success_data(
        client.get_component_replacement(replacement_id, make_planner_headers())
    )


def read_blade_damage(client: WindOpsApiClient, damage_id: str) -> Row:
    """Re-read a blade finding as a reliability engineer."""
    return get_success_data(client.get_blade_damage(damage_id, make_engineer_headers()))


def read_agreement(client: WindOpsApiClient, agreement_id: str) -> Row:
    """Re-read a service agreement as its commercial manager."""
    return get_success_data(client.get_service_agreement(agreement_id, make_commercial_headers()))


def read_curtailment(client: WindOpsApiClient, order_id: str) -> Row:
    """Re-read a curtailment order as a control room operator."""
    return get_success_data(client.get_curtailment_order(order_id, make_control_room_headers()))


def read_settlement(client: WindOpsApiClient, settlement_id: str) -> Row:
    """Re-read a landowner settlement as its commercial manager."""
    return get_success_data(
        client.get_landowner_settlement(settlement_id, make_commercial_headers())
    )


def farm_version(client: WindOpsApiClient, farm_id: str) -> int:
    """The farm's current version, for the settlement guard field."""
    return read_farm(client, farm_id)["version"]


def turbine_version(client: WindOpsApiClient, turbine_id: str) -> int:
    """The turbine's current version, for the curtailment guard field."""
    return read_turbine(client, turbine_id)["version"]


# ===========================================================================
# Composite scenarios
# ===========================================================================
def setup_availability_basis_divergence(client: WindOpsApiClient) -> Dict[str, Row]:
    """One farm, two turbines, one closed non-excluded fault and two agreements.

    The two agreements share the farm, the period and the telemetry and differ
    only in ``availability_basis``, so the settled figures may be compared.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Ridgeline North",
        region_code="TX-W",
        grid_operator_code="ERCOT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    rule = create_fault_rule(
        client,
        fault_code="FC-1000",
        severity_class="RESETTABLE",
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    post_scada(client, t1["id"], 720, 1000000, 1440000)
    post_scada(client, t2["id"], 720, 1400000, 1440000)

    set_clock(client, "2026-06-02T00:00:00Z")
    event = raise_fault(client, t1["id"], "FC-1000", "2026-06-02T00:00:00Z")
    triage(client, event["id"], DISPOSITION_REMOTE_RESET)
    set_clock(client, "2026-06-03T00:00:00Z")
    remote_reset(client, event["id"], RESET_OUTCOME_SUCCEEDED)
    close_fault(client, event["id"])

    set_clock(client, "2026-07-01T00:00:00Z")
    sa_time = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="TIME_BASED",
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=20000000,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
    )
    sa_energy = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="ENERGY_BASED",
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=20000000,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
    )
    return {
        "farm": farm,
        "model": model,
        "rule": rule,
        "t1": t1,
        "t2": t2,
        "fault_event": event,
        "sa_time": sa_time,
        "sa_energy": sa_energy,
    }


def setup_royalty_basis_divergence(client: WindOpsApiClient) -> Dict[str, Row]:
    """One farm with metered telemetry and one released compensable curtailment.

    The curtailment contributes deemed energy that only a deemed-inclusive
    settlement scales into its royalty.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Caprock South",
        region_code="TX-W",
        grid_operator_code="ERCOT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    post_scada(client, t1["id"], 720, 1000000, 1440000)
    order = create_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="GRID",
        start_utc="2026-06-10T00:00:00Z",
        end_utc="2026-06-12T00:00:00Z",
        power_limit_kw=1000,
        deemed_kwh_per_hour=1800,
    )
    get_success_data(
        client.activate_curtailment_order(order["id"], make_control_room_headers())
    )
    released = get_success_data(
        client.release_curtailment_order(
            order["id"], "2026-06-11T00:00:00Z", make_control_room_headers()
        )
    )
    set_clock(client, "2026-07-01T00:00:00Z")
    return {"farm": farm, "model": model, "t1": t1, "curtailment": released}


def setup_priority_score_scenario(client: WindOpsApiClient) -> Dict[str, Row]:
    """A submitted blade-repair order, an active agreement and a cleared fault.

    Closing the fault is the trigger that flips the agreement's at-risk flag and
    re-scores the order without naming it.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Mesa Verde",
        region_code="NM-E",
        grid_operator_code="ERCOT",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    create_fault_rule(
        client,
        fault_code="FC-1000",
        severity_class="RESETTABLE",
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    finding = record_blade_damage(
        client,
        t1["id"],
        inspection_method="DRONE",
        blade_position="A",
        inspected_at="2026-05-28T10:00:00Z",
        damage_category=3,
        damage_type="LEADING_EDGE_EROSION",
        chord_position_pct=12.5,
        damage_length_mm=500,
        exposed_area_cm2=400,
    )
    get_success_data(
        client.prioritize_blade_damage(
            finding["id"], make_engineer_headers(ENGINEER_2_USER_ID)
        )
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type="BLADE_REPAIR",
        required_certification="BLADE_COMPOSITE",
        estimated_hours=4,
        blade_damage_id=finding["id"],
    )
    submitted = get_success_data(
        client.submit_work_order(order["id"], make_planner_headers())
    )
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="TIME_BASED",
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=20000000,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
    )
    event = raise_fault(client, t1["id"], "FC-1000", "2026-06-01T00:00:00Z")
    triage(client, event["id"], DISPOSITION_REMOTE_RESET)
    set_clock(client, "2026-06-04T09:00:00Z")
    remote_reset(client, event["id"], RESET_OUTCOME_SUCCEEDED)
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "finding": finding,
        "order": submitted,
        "agreement": agreement,
        "fault_event": event,
    }


def setup_blade_severity_scenario(client: WindOpsApiClient) -> Dict[str, Row]:
    """A bare farm and one online turbine with no blade findings recorded yet."""
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Mesa Verde",
        region_code="NM-E",
        grid_operator_code="ERCOT",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    return {"farm": farm, "model": model, "t1": t1}


def setup_crane_waterfall_scenario(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two planned replacements, one requested crane and two high-wind windows.

    The crane spans five calendar dates, two of which are fully covered by a
    confirmed window forecasting above the crane's lift ceiling.
    """
    set_clock(client, "2026-06-15T00:00:00Z")
    farm = create_farm(
        client,
        name="Sandhill West",
        region_code="NE-C",
        grid_operator_code="SPP",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    part = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-1",
        quantity_on_hand=2,
        lead_time_days=210,
        reorder_point=1,
        unit_cost_cents=90000000,
        uptower_repairable=False,
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type="MAJOR_COMPONENT",
        required_certification="CRANE_BANKSMAN",
        estimated_hours=60,
    )
    r1 = create_replacement(
        client,
        order["id"],
        part["id"],
        component_type="GEARBOX",
        estimated_lift_hours=15,
        uptower_labor_hours=40,
    )
    r2 = create_replacement(
        client,
        order["id"],
        part["id"],
        component_type="GEARBOX",
        estimated_lift_hours=8,
        uptower_labor_hours=30,
    )
    crane = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-06-20T00:00:00Z",
        demobilization_end_utc="2026-06-25T00:00:00Z",
        day_rate_cents=2240000,
        mobilization_fee_cents=4000000,
        max_lift_wind_speed_ms=12,
    )
    ww1 = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-21T00:00:00Z",
        end_utc="2026-06-22T00:00:00Z",
        forecast_wind_speed_ms=15,
        forecast_gust_ms=20,
        icing_risk=False,
    )
    ww2 = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-22T00:00:00Z",
        end_utc="2026-06-23T00:00:00Z",
        forecast_wind_speed_ms=16,
        forecast_gust_ms=22,
        icing_risk=False,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "part": part,
        "order": order,
        "r1": r1,
        "r2": r2,
        "crane": crane,
        "ww1": ww1,
        "ww2": ww2,
    }


def setup_dual_dimension_turbine(client: WindOpsApiClient) -> Dict[str, Row]:
    """One ONLINE, UNCONSTRAINED turbine plus a RESETTABLE rule with a 2-per-24h quota."""
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client, name="Mesa Verde", region_code="NM-E", grid_operator_code="ERCOT"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    rule = create_fault_rule(
        client,
        fault_code="FC-1000",
        severity_class="RESETTABLE",
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    return {"farm": farm, "model": model, "t1": t1, "rule": rule}


def setup_revision_cycle_order(client: WindOpsApiClient) -> Dict[str, Row]:
    """A DRAFT major-component order on a healthy turbine, with the clock at 2026-06-01."""
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client, name="Mesa Verde", region_code="NM-E", grid_operator_code="ERCOT"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {"farm": farm, "model": model, "t1": t1, "order": order}


def setup_fork_join_replacements(client: WindOpsApiClient) -> Dict[str, Row]:
    """An IN_PROGRESS major-component order carrying one CRANE_RESERVED and one UPTOWER_READY line."""
    set_clock(client, "2026-06-15T00:00:00Z")
    farm = create_farm(
        client, name="Sandhill West", region_code="NE-C", grid_operator_code="SPP"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    sp_gb = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-2",
        quantity_on_hand=1,
        lead_time_days=210,
        reorder_point=1,
        unit_cost_cents=90000000,
        uptower_repairable=False,
    )
    sp_gen = create_spare_part(
        client,
        component_type="GENERATOR",
        part_number="GEN-7",
        quantity_on_hand=1,
        lead_time_days=120,
        reorder_point=1,
        unit_cost_cents=41000000,
        uptower_repairable=True,
    )
    crew = create_crew(
        client,
        farm["id"],
        crew_code="CRW-A",
        technician_count=4,
        certifications=["GWO_BASIC", "CRANE_BANKSMAN"],
        max_work_wind_speed_ms=20,
        daily_hours_capacity=60,
        hourly_rate_cents=18000,
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=10,
    )
    ra = create_replacement(
        client,
        order["id"],
        sp_gb["id"],
        component_type="GEARBOX",
        estimated_lift_hours=15,
        uptower_labor_hours=40,
    )
    rb = create_replacement(
        client,
        order["id"],
        sp_gen["id"],
        component_type="GENERATOR",
        estimated_lift_hours=9,
        uptower_labor_hours=30,
    )
    crane = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-06-20T00:00:00Z",
        demobilization_end_utc="2026-06-25T00:00:00Z",
        day_rate_cents=2240000,
        mobilization_fee_cents=4000000,
        max_lift_wind_speed_ms=12,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-20T00:00:00Z",
        end_utc="2026-06-21T00:00:00Z",
        forecast_wind_speed_ms=8,
        forecast_gust_ms=12,
        icing_risk=False,
    )
    reserve_crane(client, ra["id"], crane["id"])
    plan_uptower(client, rb["id"])
    get_success_data(client.submit_work_order(order["id"], make_planner_headers()))
    get_success_data(
        client.schedule_work_order(
            order["id"],
            f.schedule_payload(
                crew["id"], window["id"], "2026-06-20T06:00:00Z", "2026-06-20T16:00:00Z"
            ),
            make_planner_headers(),
        )
    )
    get_success_data(client.start_work_order(order["id"], make_crew_lead_headers(crew["id"])))
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "sp_gb": sp_gb,
        "sp_gen": sp_gen,
        "crew": crew,
        "order": order,
        "ra": ra,
        "rb": rb,
        "crane": crane,
        "window": window,
    }


def setup_six_hop_completion_cascade(client: WindOpsApiClient) -> Dict[str, Row]:
    """An IN_PROGRESS fault-dispatch order on T1, a SUBMITTED order on T2 and a live agreement.

    The clock is left at 2026-07-03T00:00:00Z so a completion posted immediately
    afterwards spans a full 24 hours of fault downtime.
    """
    set_clock(client, "2026-07-01T00:00:00Z")
    farm = create_farm(
        client, name="Coyote Ridge", region_code="TX-W", grid_operator_code="ERCOT"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=1000,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=1000,
    )
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=99.0000,
        availability_basis="TIME_BASED",
        lda_rate_cents_per_pct_point=1000000,
        lda_cap_cents=50000000,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-07-31T00:00:00Z",
    )
    crew = create_crew(
        client,
        farm["id"],
        crew_code="CRW-A",
        technician_count=3,
        certifications=["GWO_BASIC"],
        max_work_wind_speed_ms=20,
        daily_hours_capacity=12,
        hourly_rate_cents=18000,
    )
    wo2 = create_work_order(
        client,
        t2["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification="GWO_BASIC",
        estimated_hours=4,
    )
    wo2 = get_success_data(client.submit_work_order(wo2["id"], make_planner_headers()))

    set_clock(client, "2026-07-02T00:00:00Z")
    rule = create_fault_rule(
        client,
        fault_code="FC-2000",
        severity_class="LOCKOUT",
        max_remote_resets_per_24h=0,
        requires_dispatch=True,
        contractual_exclusion=False,
    )
    fault_event = raise_fault(client, t1["id"], "FC-2000", "2026-07-02T00:00:00Z")
    triage(client, fault_event["id"], DISPOSITION_DISPATCH)
    wo1 = create_work_order(
        client,
        t1["id"],
        work_type="FAULT_DISPATCH",
        required_certification="GWO_BASIC",
        estimated_hours=6,
        fault_event_id=fault_event["id"],
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-07-02T00:00:00Z",
        end_utc="2026-07-03T00:00:00Z",
        forecast_wind_speed_ms=9,
        forecast_gust_ms=14,
        icing_risk=False,
    )
    get_success_data(client.submit_work_order(wo1["id"], make_planner_headers()))
    get_success_data(
        client.schedule_work_order(
            wo1["id"],
            f.schedule_payload(
                crew["id"], window["id"], "2026-07-02T06:00:00Z", "2026-07-02T12:00:00Z"
            ),
            make_planner_headers(),
        )
    )
    wo1 = get_success_data(
        client.start_work_order(wo1["id"], make_crew_lead_headers(crew["id"]))
    )
    set_clock(client, "2026-07-03T00:00:00Z")
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "t2": t2,
        "agreement": agreement,
        "crew": crew,
        "rule": rule,
        "fault_event": fault_event,
        "window": window,
        "wo1": wo1,
        "wo2": wo2,
    }


def setup_replacement_cancellation_cascade(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two CRANE_RESERVED lines on one mobilization under a SCHEDULED major-component order.

    Two of the mobilization's five calendar dates are blown out by confirmed
    high-wind windows, so the slot enters the trigger reading three workable
    dates against three lift days.
    """
    set_clock(client, "2026-06-15T00:00:00Z")
    farm = create_farm(
        client, name="Sandhill West", region_code="NE-C", grid_operator_code="SPP"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    part = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-9",
        quantity_on_hand=2,
        lead_time_days=210,
        reorder_point=2,
        unit_cost_cents=90000000,
        uptower_repairable=False,
    )
    crew = create_crew(
        client,
        farm["id"],
        crew_code="CRW-A",
        technician_count=4,
        certifications=["CRANE_BANKSMAN"],
        max_work_wind_speed_ms=20,
        daily_hours_capacity=12,
        hourly_rate_cents=18000,
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=10,
    )
    r1 = create_replacement(
        client,
        order["id"],
        part["id"],
        component_type="GEARBOX",
        estimated_lift_hours=15,
        uptower_labor_hours=40,
    )
    r2 = create_replacement(
        client,
        order["id"],
        part["id"],
        component_type="GEARBOX",
        estimated_lift_hours=8,
        uptower_labor_hours=40,
    )
    crane = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-06-20T00:00:00Z",
        demobilization_end_utc="2026-06-25T00:00:00Z",
        day_rate_cents=2240000,
        mobilization_fee_cents=4000000,
        max_lift_wind_speed_ms=12,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-20T00:00:00Z",
        end_utc="2026-06-21T00:00:00Z",
        forecast_wind_speed_ms=9,
        forecast_gust_ms=13,
        icing_risk=False,
    )
    storm_1 = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-21T00:00:00Z",
        end_utc="2026-06-22T00:00:00Z",
        forecast_wind_speed_ms=15,
        forecast_gust_ms=22,
        icing_risk=False,
    )
    storm_2 = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-22T00:00:00Z",
        end_utc="2026-06-23T00:00:00Z",
        forecast_wind_speed_ms=16,
        forecast_gust_ms=24,
        icing_risk=False,
    )
    reserve_crane(client, r1["id"], crane["id"])
    reserve_crane(client, r2["id"], crane["id"])
    get_success_data(client.submit_work_order(order["id"], make_planner_headers()))
    order = get_success_data(
        client.schedule_work_order(
            order["id"],
            f.schedule_payload(
                crew["id"], window["id"], "2026-06-20T06:00:00Z", "2026-06-20T16:00:00Z"
            ),
            make_planner_headers(),
        )
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "part": part,
        "crew": crew,
        "order": order,
        "r1": r1,
        "r2": r2,
        "crane": crane,
        "window": window,
        "storm_1": storm_1,
        "storm_2": storm_2,
    }


def setup_schedule_ladder(client: WindOpsApiClient) -> Dict[str, Row]:
    """A SUBMITTED order, an unconfirmed high-wind window and a small, low-limit crew.

    A single schedule request naming both breaches the window-confirmation rung,
    the crew wind limit and the crew daily capacity at once.
    """
    set_clock(client, "2026-06-15T00:00:00Z")
    farm = create_farm(
        client, name="Bitter Creek", region_code="WY-S", grid_operator_code="PACW"
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    crew_a = create_crew(
        client,
        farm["id"],
        crew_code="CRW-A",
        technician_count=2,
        certifications=["GWO_BASIC"],
        max_work_wind_speed_ms=10,
        daily_hours_capacity=6,
        hourly_rate_cents=18000,
    )
    order = submitted_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification="GWO_BASIC",
        estimated_hours=8,
    )
    window_a = create_window(
        client,
        farm["id"],
        start_utc="2026-06-20T00:00:00Z",
        end_utc="2026-06-21T00:00:00Z",
        forecast_wind_speed_ms=18,
        forecast_gust_ms=26,
        icing_risk=False,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "crew_a": crew_a,
        "order": order,
        "window_a": window_a,
    }


def setup_reserve_crane_ladder(client: WindOpsApiClient) -> Dict[str, Row]:
    """A PLANNED gearbox replacement on farm A plus three candidate mobilizations.

    ``c_short`` sits on the wrong farm *and* offers only one workable date;
    ``c_long`` sits on the wrong farm but is long enough; ``c_home`` is both long
    enough and on the right farm.
    """
    set_clock(client, "2026-06-15T00:00:00Z")
    farm_a = create_farm(
        client, name="Alkali Flat A", region_code="NM-W", grid_operator_code="ERCOT"
    )
    farm_b = create_farm(
        client, name="Alkali Flat B", region_code="NM-W", grid_operator_code="ERCOT"
    )
    model = create_model(client)
    ta1 = create_turbine(
        client,
        farm_a["id"],
        model["id"],
        asset_tag="T-A1",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    part = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-11",
        quantity_on_hand=2,
        lead_time_days=210,
        reorder_point=1,
        unit_cost_cents=90000000,
        uptower_repairable=False,
    )
    order = create_work_order(
        client,
        ta1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=10,
    )
    replacement = create_replacement(
        client,
        order["id"],
        part["id"],
        component_type="GEARBOX",
        estimated_lift_hours=15,
        uptower_labor_hours=40,
    )
    crane_kwargs = {
        "crane_class": "CRAWLER_600T",
        "day_rate_cents": 2240000,
        "mobilization_fee_cents": 4000000,
        "max_lift_wind_speed_ms": 12,
    }
    c_short = create_crane(
        client,
        farm_b["id"],
        mobilization_start_utc="2026-06-20T00:00:00Z",
        demobilization_end_utc="2026-06-21T00:00:00Z",
        **crane_kwargs,
    )
    c_long = create_crane(
        client,
        farm_b["id"],
        mobilization_start_utc="2026-08-20T00:00:00Z",
        demobilization_end_utc="2026-08-25T00:00:00Z",
        **crane_kwargs,
    )
    c_home = create_crane(
        client,
        farm_a["id"],
        mobilization_start_utc="2026-07-20T00:00:00Z",
        demobilization_end_utc="2026-07-25T00:00:00Z",
        **crane_kwargs,
    )
    return {
        "farm_a": farm_a,
        "farm_b": farm_b,
        "model": model,
        "ta1": ta1,
        "part": part,
        "order": order,
        "replacement": replacement,
        "c_short": c_short,
        "c_long": c_long,
        "c_home": c_home,
    }


def setup_settlement_ladder(client: WindOpsApiClient) -> Dict[str, Any]:
    """A frozen farm carrying one APPROVED settlement on parcel P-1 and a tight budget cap.

    The farm's cap is 100000000 with 240000 already posted to
    ``landowner_payable_cents``, and one agreement sits in ``IN_SETTLEMENT`` so the
    farm's telemetry and settlement drafting are both frozen.  ``farm_version`` is
    the guard token to present on a drafting attempt.
    """
    set_clock(client, "2026-07-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Willow Bend",
        region_code="IA-N",
        grid_operator_code="MISO",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=100000000,
    )
    model = create_model(client)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    post_scada(client, t1["id"], 720, 1000000, 1440000)
    settlement = create_settlement(
        client,
        farm["id"],
        farm_version(client, farm["id"]),
        parcel_code="P-1",
        royalty_basis="METERED_ONLY",
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=0,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )
    settlement = get_success_data(
        client.approve_landowner_settlement(settlement["id"], make_commercial_headers())
    )
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="TIME_BASED",
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=20000000,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
    )
    agreement = get_success_data(
        client.settle_agreement(agreement["id"], make_commercial_headers())
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "settlement": settlement,
        "agreement": agreement,
        "farm_version": farm_version(client, farm["id"]),
    }


def setup_service_due_boundaries(client: WindOpsApiClient) -> Dict[str, Row]:
    """One turbine parked one hour below the earliest scheduled-service creation point.

    The model's interval is 4000 hours with a 250-hour tolerance and the turbine's
    ``last_service_operating_hours`` is 0, so the due point is 4000, the earliest
    creation point is 3800.0 and the tolerated boundary is 4250.0.  The turbine
    starts at 3799.0, one tenth below the first of those three boundaries.
    """
    farm = create_farm(
        client,
        name="Table Mesa",
        region_code="CO-E",
        grid_operator_code="PSCO",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(
        client,
        model_code="V150-4.2",
        service_interval_hours=4000,
        service_interval_tolerance_hours=250,
    )
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=3799.0,
        last_service_operating_hours=0,
    )
    return {"farm": farm, "model": model, "t1": t1}


def setup_blade_band_boundaries(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two turbines, so each of the blade positions A, B and C carries two findings.

    Each pair of findings straddles one band threshold by exactly one hundredth of
    a point.
    """
    farm = create_farm(
        client,
        name="Salt Fork",
        region_code="OK-N",
        grid_operator_code="SPP",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    return {"farm": farm, "model": model, "t1": t1, "t2": t2}


def setup_lda_boundary_agreements(client: WindOpsApiClient) -> Dict[str, Row]:
    """Five ACTIVE agreements over one identical period, each pinned to a different boundary.

    The farm carries two turbines and no telemetry at all, so both energy sums are
    0, and exactly one closed non-excluded 24-hour fault event on ``t1``, so the
    time-based figure over the 1440-hour denominator is 98.3333.  The agreements
    differ only in basis, guarantee and cap.  None is settled here.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Broken Spur",
        region_code="KS-W",
        grid_operator_code="SPP",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    rule = create_fault_rule(
        client,
        fault_code="FC-1000",
        severity_class="RESETTABLE",
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    set_clock(client, "2026-06-02T00:00:00Z")
    event = raise_fault(client, t1["id"], "FC-1000", "2026-06-02T00:00:00Z")
    triage(client, event["id"], DISPOSITION_REMOTE_RESET)
    set_clock(client, "2026-06-03T00:00:00Z")
    remote_reset(client, event["id"], RESET_OUTCOME_SUCCEEDED)
    event = close_fault(client, event["id"])
    set_clock(client, "2026-07-01T00:00:00Z")
    period = {
        "lda_rate_cents_per_pct_point": 1000000,
        "period_start_utc": "2026-06-01T00:00:00Z",
        "period_end_utc": "2026-07-01T00:00:00Z",
    }
    ag_zero_energy = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="ENERGY_BASED",
        lda_cap_cents=20000000,
        **period,
    )
    ag_equal = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=98.3333,
        availability_basis="TIME_BASED",
        lda_cap_cents=20000000,
        **period,
    )
    ag_one_tick = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=98.3334,
        availability_basis="TIME_BASED",
        lda_cap_cents=20000000,
        **period,
    )
    ag_cap_equal = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=99.0,
        availability_basis="TIME_BASED",
        lda_cap_cents=666700,
        **period,
    )
    ag_cap_binds = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=99.0,
        availability_basis="TIME_BASED",
        lda_cap_cents=666699,
        **period,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "t2": t2,
        "rule": rule,
        "fault_event": event,
        "ag_zero_energy": ag_zero_energy,
        "ag_equal": ag_equal,
        "ag_one_tick": ag_one_tick,
        "ag_cap_equal": ag_cap_equal,
        "ag_cap_binds": ag_cap_binds,
    }


def setup_stock_gated_replacement(client: WindOpsApiClient) -> Dict[str, Row]:
    """One DRAFT major-component order and two stock lines that decide its replacements.

    ``sp_gb`` is a GEARBOX line holding exactly one unit against a reorder point of
    1; ``sp_bl`` is a BLADE line holding none.  The replacement payload never has to
    change for its legality to change.
    """
    farm = create_farm(
        client,
        name="Cedar Draw",
        region_code="TX-P",
        grid_operator_code="ERCOT",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    sp_gb = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-21",
        quantity_on_hand=1,
        lead_time_days=210,
        reorder_point=1,
        unit_cost_cents=90000000,
        uptower_repairable=False,
    )
    sp_bl = create_spare_part(
        client,
        component_type="BLADE",
        part_number="BL-4",
        quantity_on_hand=0,
        lead_time_days=150,
        reorder_point=1,
        unit_cost_cents=30000000,
        uptower_repairable=False,
    )
    order = create_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=10,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "sp_gb": sp_gb,
        "sp_bl": sp_bl,
        "order": order,
    }


def setup_force_stopped_reset_candidate(client: WindOpsApiClient) -> Dict[str, Row]:
    """A RESET_PENDING fault event on a turbine held at FORCED_STOP by a zero-limit order.

    The availability dimension reads ``FAULTED`` and the curtailment dimension
    ``FORCED_STOP``; the fault event and its quota are untouched.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Antelope Gap",
        region_code="WY-E",
        grid_operator_code="PACE",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    rule = create_fault_rule(
        client,
        fault_code="FC-1000",
        severity_class="RESETTABLE",
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    event = raise_fault(client, t1["id"], "FC-1000", "2026-06-01T00:00:00Z")
    event = triage(client, event["id"], DISPOSITION_REMOTE_RESET)
    co1 = active_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="ICING",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-02T00:00:00Z",
        power_limit_kw=0,
        deemed_kwh_per_hour=0,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "rule": rule,
        "fault_event": event,
        "co1": co1,
    }


def setup_force_stopped_scheduled_order(client: WindOpsApiClient) -> Dict[str, Row]:
    """A SCHEDULED major-component order on an ONLINE turbine held at FORCED_STOP.

    The order, its crew and its window are all in order; the only obstacle is a
    zero-limit curtailment order on the turbine's orthogonal dimension.
    """
    set_clock(client, "2026-06-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Antelope Gap",
        region_code="WY-E",
        grid_operator_code="PACE",
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    crew = create_crew(
        client,
        farm["id"],
        crew_code="CRW-A",
        technician_count=3,
        certifications=["GWO_BASIC"],
        max_work_wind_speed_ms=20,
        daily_hours_capacity=12,
        hourly_rate_cents=18000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-06-20T00:00:00Z",
        end_utc="2026-06-21T00:00:00Z",
        forecast_wind_speed_ms=8,
        forecast_gust_ms=12,
        icing_risk=False,
    )
    order = scheduled_work_order(
        client,
        t1["id"],
        crew["id"],
        window["id"],
        "2026-06-20T06:00:00Z",
        "2026-06-20T16:00:00Z",
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification="GWO_BASIC",
        estimated_hours=10,
    )
    co2 = active_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="WILDLIFE",
        start_utc="2026-06-20T00:00:00Z",
        end_utc="2026-06-21T00:00:00Z",
        power_limit_kw=0,
        deemed_kwh_per_hour=0,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "crew": crew,
        "window": window,
        "order": order,
        "co2": co2,
    }


def setup_settlement_freeze_farm(client: WindOpsApiClient) -> Dict[str, Any]:
    """One ACTIVE TIME_BASED agreement over a closed period on a two-turbine farm.

    Neither turbine has any telemetry yet and the agreement's period has already
    elapsed, so it is settleable at once.  ``farm_version`` is the guard token for a
    landowner-settlement draft.
    """
    set_clock(client, "2026-07-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Prairie Gate",
        region_code="ND-S",
        grid_operator_code="MISO",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=100000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        availability_basis="TIME_BASED",
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=20000000,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "t2": t2,
        "agreement": agreement,
        "farm_version": farm_version(client, farm["id"]),
    }


def setup_crew_tiling_day(client: WindOpsApiClient) -> Dict[str, Row]:
    """One crew, one confirmed all-day window and four SUBMITTED orders to tile it.

    The forecast sits well under the crew's wind limit and four six-hour orders
    total 24 hours against a 40 hour capacity, so neither the wind gate nor the
    capacity gate can ever be the binding rule.  The mandatory default clock
    already stands at the declared origin, so no clock move is needed.
    """
    farm = create_farm(
        client,
        name="Coulee Ridge",
        region_code="OR-E",
        grid_operator_code="BPA",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    turbines = [
        create_turbine(
            client,
            farm["id"],
            model["id"],
            asset_tag=tag,
            commissioning_date="2024-03-15",
            expected_kwh_per_hour=2000,
            operating_hours=0,
            last_service_operating_hours=0,
        )
        for tag in ("T-01", "T-02", "T-03", "T-04")
    ]
    crew = create_crew(
        client,
        farm["id"],
        crew_code="C-ALPHA",
        technician_count=4,
        certifications=["GWO_BASIC", "CRANE_BANKSMAN"],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=40,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T00:00:00Z",
        end_utc="2026-08-11T00:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
        icing_risk=False,
    )
    orders = [
        submitted_work_order(
            client,
            turbine["id"],
            work_type=WORK_TYPE_MAJOR_COMPONENT,
            required_certification=CERT_CRANE_BANKSMAN,
            estimated_hours=6,
        )
        for turbine in turbines
    ]
    return {
        "farm": farm,
        "model": model,
        "t1": turbines[0],
        "t2": turbines[1],
        "t3": turbines[2],
        "t4": turbines[3],
        "crew": crew,
        "window": window,
        "wo_a": orders[0],
        "wo_b": orders[1],
        "wo_c": orders[2],
        "wo_d": orders[3],
    }


def setup_touch_point_geometry(client: WindOpsApiClient) -> Dict[str, Row]:
    """One anchoring mobilization and one anchoring window on the same farm.

    The mobilization runs 2026-09-10 to 2026-09-12, so its padded slot spans
    2026-09-08 to 2026-09-14; the forecast window covers only the first half of
    2026-09-10.  No turbine is needed by either resource.
    """
    set_clock(client, "2026-09-01T00:00:00Z")
    farm = create_farm(
        client,
        name="Sand Hills",
        region_code="NE-C",
        grid_operator_code="SPP",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    crane_anchor = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-09-10T00:00:00Z",
        demobilization_end_utc="2026-09-12T00:00:00Z",
        day_rate_cents=3800000,
        mobilization_fee_cents=12000000,
        max_lift_wind_speed_ms=9.0,
    )
    ww_anchor = create_window(
        client,
        farm["id"],
        start_utc="2026-09-10T00:00:00Z",
        end_utc="2026-09-10T12:00:00Z",
        forecast_wind_speed_ms=7.0,
        forecast_gust_ms=10.0,
        icing_risk=False,
    )
    return {"farm": farm, "crane_anchor": crane_anchor, "ww_anchor": ww_anchor}


def setup_curtailment_stack(client: WindOpsApiClient) -> Dict[str, Row]:
    """Four PENDING curtailment orders that all overlap on one turbine.

    Every order is individually legal; only the aggregate live count can refuse
    one.  The turbine's guard version is re-read before each issue because each
    issue advances it.
    """
    farm = create_farm(
        client,
        name="Basin Mesa",
        region_code="NM-N",
        grid_operator_code="PNM",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2", rated_power_kw=4200)
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    co_grid = create_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="GRID",
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-01T06:00:00Z",
        power_limit_kw=1500,
        deemed_kwh_per_hour=500,
    )
    co_noise = create_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="NOISE",
        start_utc="2026-08-01T02:00:00Z",
        end_utc="2026-08-01T08:00:00Z",
        power_limit_kw=800,
        deemed_kwh_per_hour=400,
    )
    co_wildlife = create_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="WILDLIFE",
        start_utc="2026-08-01T03:00:00Z",
        end_utc="2026-08-01T04:00:00Z",
        power_limit_kw=0,
        deemed_kwh_per_hour=0,
    )
    co_icing = create_curtailment(
        client,
        t1["id"],
        turbine_version(client, t1["id"]),
        reason="ICING",
        start_utc="2026-08-01T05:00:00Z",
        end_utc="2026-08-01T09:00:00Z",
        power_limit_kw=1200,
        deemed_kwh_per_hour=300,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "co_grid": co_grid,
        "co_noise": co_noise,
        "co_wildlife": co_wildlife,
        "co_icing": co_icing,
    }


def setup_conserved_stock_line(client: WindOpsApiClient) -> Dict[str, Row]:
    """One GEARBOX stock line opening at two units, with everywhere to move them.

    The line's ``reorder_point`` equals its opening balance, so it starts
    ``IN_STOCK`` and drops below the reorder point on the very first reservation.
    The parent order is already ``IN_PROGRESS`` because execution requires it, and
    the mobilization's two calendar dates are both workable against the confirmed
    window's forecast.
    """
    farm = create_farm(
        client,
        name="Cedar Bluff",
        region_code="KS-W",
        grid_operator_code="SPP",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    part = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-4200-A",
        quantity_on_hand=2,
        lead_time_days=210,
        reorder_point=2,
        unit_cost_cents=25000000,
        uptower_repairable=False,
    )
    crew = create_crew(
        client,
        farm["id"],
        crew_code="C-BRAVO",
        technician_count=5,
        certifications=["GWO_BASIC", "CRANE_BANKSMAN"],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=40,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T00:00:00Z",
        end_utc="2026-08-11T00:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
        icing_risk=False,
    )
    crane = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-08-10T00:00:00Z",
        demobilization_end_utc="2026-08-12T00:00:00Z",
        day_rate_cents=3800000,
        mobilization_fee_cents=12000000,
        max_lift_wind_speed_ms=9.0,
    )
    order = in_progress_work_order(
        client,
        t1["id"],
        crew["id"],
        window["id"],
        "2026-08-10T06:00:00Z",
        "2026-08-10T14:00:00Z",
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "part": part,
        "crew": crew,
        "window": window,
        "crane": crane,
        "order": order,
    }


def setup_opex_ledger_farm(client: WindOpsApiClient) -> Dict[str, Row]:
    """One metered turbine and one IN_PROGRESS order, ready to post to two buckets.

    The metered figure 1041750 kWh is chosen so that a 4 percent royalty at 6
    cents per kWh lands on 250020 cents, whose 2.5 percent road levy is exactly
    6250.5 cents — a genuine half-cent rounding boundary.  The order is submitted
    by the planner so that a different actor may complete it.
    """
    farm = create_farm(
        client,
        name="Whitetail Draw",
        region_code="WY-S",
        grid_operator_code="PACW",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=100000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
        operating_hours=0,
        last_service_operating_hours=0,
    )
    post_scada(client, t1["id"], 720, 1041750, 1440000)
    crew = create_crew(
        client,
        farm["id"],
        crew_code="C-CHARLIE",
        technician_count=4,
        certifications=["GWO_BASIC", "CRANE_BANKSMAN"],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=40,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T00:00:00Z",
        end_utc="2026-08-11T00:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
        icing_risk=False,
    )
    order = in_progress_work_order(
        client,
        t1["id"],
        crew["id"],
        window["id"],
        "2026-08-10T06:00:00Z",
        "2026-08-10T14:00:00Z",
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "crew": crew,
        "window": window,
        "order": order,
    }


def setup_levied_read_back_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm carrying non-default levies plus one turbine, for read-back checks.

    The two levy percentages are deliberately away from the declared 2.5 and 1.5
    fallbacks so that a read proves the supplied values were stored.  The logical
    clock is left at its declared origin.
    """
    farm = create_farm(
        client,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=3.25,
        community_levy_pct=0.75,
        landowner_budget_cap_cents=250000000,
    )
    model = create_model(client, model_code="V150-4.2")
    turbine = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-07",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    return {"farm": farm, "model": model, "turbine": turbine}


def setup_three_turbine_farm(client: WindOpsApiClient) -> Dict[str, Row]:
    """One farm carrying exactly three ONLINE, UNCONSTRAINED turbines.

    Three rows is one more than a page of two and well inside a page of ten,
    which is what lets one listing sweep exercise both the default page size and
    a two-row window.
    """
    farm = create_farm(
        client,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    turbines = [
        create_turbine(
            client,
            farm["id"],
            model["id"],
            asset_tag=tag,
            commissioning_date="2024-03-15",
            expected_kwh_per_hour=2000,
        )
        for tag in ("T-01", "T-02", "T-03")
    ]
    return {
        "farm": farm,
        "model": model,
        "t1": turbines[0],
        "t2": turbines[1],
        "t3": turbines[2],
    }


def setup_two_model_farm(client: WindOpsApiClient) -> Dict[str, Row]:
    """One farm with two turbines drawn from two differently rated models.

    The ratings 4200 kW and 2800 kW are distinct, so the farm's capacity rollup
    cannot be mistaken for a turbine count multiplied by a single rating.
    """
    farm = create_farm(
        client,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model_a = create_model(client, model_code="V150-4.2", rated_power_kw=4200)
    model_b = create_model(
        client,
        model_code="V112-2.8",
        rated_power_kw=2800,
        hub_height_m=94,
        rotor_diameter_m=112,
        service_interval_hours=3500,
        service_interval_tolerance_hours=200,
        gearbox_lead_time_days=180,
        blade_lead_time_days=130,
        generator_lead_time_days=110,
    )
    t1 = create_turbine(
        client,
        farm["id"],
        model_a["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    t2 = create_turbine(
        client,
        farm["id"],
        model_b["id"],
        asset_tag="T-02",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=1400,
    )
    return {"farm": farm, "model_a": model_a, "model_b": model_b, "t1": t1, "t2": t2}


def setup_junction_graph(client: WindOpsApiClient) -> Dict[str, Row]:
    """A turbine, a stock line, a major-component order and one crane slot.

    Everything a replacement junction row needs to point at is present before the
    replacement itself is planned, so that each of its three foreign keys can be
    followed back through its own list filter.
    """
    farm = create_farm(
        client,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(client, model_code="V150-4.2")
    t1 = create_turbine(
        client,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    part = create_spare_part(
        client,
        component_type="GEARBOX",
        part_number="GB-4200-A",
        quantity_on_hand=2,
        lead_time_days=210,
        reorder_point=1,
        unit_cost_cents=48000000,
        uptower_repairable=False,
    )
    wo_parent = create_work_order(
        client,
        t1["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=20,
    )
    crane = create_crane(
        client,
        farm["id"],
        crane_class="CRAWLER_600T",
        mobilization_start_utc="2026-08-09T00:00:00Z",
        demobilization_end_utc="2026-08-12T00:00:00Z",
        day_rate_cents=3800000,
        mobilization_fee_cents=12000000,
        max_lift_wind_speed_ms=9.0,
    )
    return {
        "farm": farm,
        "model": model,
        "t1": t1,
        "part": part,
        "wo_parent": wo_parent,
        "crane": crane,
    }


def setup_work_order_walk(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm, a certified crew, a confirmed window and one DRAFT major-component order.

    The crew holds both GWO_BASIC and CRANE_BANKSMAN so a major-component order
    schedules cleanly, its wind limit of 14.0 m/s sits above the window's 8.0 m/s
    forecast and 11.0 m/s gust, and its 24-hour daily capacity leaves room for the
    order's 8 estimated hours.  The order is left in DRAFT so a test can walk the
    whole loop itself.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    crew = create_crew(
        client,
        farm["id"],
        crew_code="C-ALPHA",
        technician_count=4,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T06:00:00Z",
        end_utc="2026-08-10T18:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
    )
    order = create_work_order(
        client,
        turbine["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {
        "farm": farm,
        "model": model,
        "turbine": turbine,
        "crew": crew,
        "window": window,
        "order": order,
    }


def setup_decommissioned_turbine_with_draft_order(client: WindOpsApiClient) -> Dict[str, Row]:
    """A retired turbine that already carries a fault rule and a DRAFT order.

    Both artefacts are created while the turbine is still ONLINE, so a test can
    show that retirement blocks the onward triggers rather than the creations.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    rule = create_fault_rule(client, fault_code="F-3001", severity_class=SEVERITY_RESETTABLE)
    order = create_work_order(client, turbine["id"])
    retired = get_success_data(
        client.decommission_turbine(
            turbine["id"], "tower foundation condemned", make_site_admin_headers()
        )
    )
    return {
        "farm": farm,
        "model": model,
        "turbine": retired,
        "rule": rule,
        "order": order,
    }


def setup_three_machine_snapshot(client: WindOpsApiClient) -> Dict[str, Row]:
    """A SUBMITTED work order, a RAISED fault event and a DRAFT landowner settlement.

    Three separate machines parked one hop into their lifecycles, so a single test
    can aim an undeclared trigger at each of them.  The settlement's optimistic
    token is re-read from the farm immediately before the draft, because
    commissioning a turbine and raising a fault both advance the farm.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    create_fault_rule(client, fault_code="F-3001", severity_class=SEVERITY_RESETTABLE)
    order = submitted_work_order(client, turbine["id"], submitter=make_planner_headers())
    event = raise_fault(client, turbine["id"], "F-3001", "2026-08-01T00:00:00Z")
    settlement = create_settlement(
        client,
        farm["id"],
        farm_version(client, farm["id"]),
        parcel_code="P-11",
        royalty_basis=ROYALTY_METERED_ONLY,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=100000,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )
    return {
        "farm": farm,
        "turbine": turbine,
        "order": order,
        "event": event,
        "settlement": settlement,
    }


def setup_faultable_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm, a turbine and one resettable fault rule that allows two resets a day."""
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    rule = create_fault_rule(
        client,
        fault_code="F-3001",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
    )
    return {"farm": farm, "model": model, "turbine": turbine, "rule": rule}


def setup_released_curtailment_and_waived_damage(client: WindOpsApiClient) -> Dict[str, Row]:
    """One RELEASED curtailment order and one WAIVED blade finding on the same turbine.

    The order runs from midnight to 06:00 and is released exactly at its own end,
    so it accrues six curtailed hours at 500 deemed kWh per hour.  The finding is
    the mildest classification the schema allows — category 1 leading-edge erosion,
    60 mm long over 8 square centimetres — which lands in the ``LOW`` band, the
    only kind of finding a waiver is permitted to touch.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    order = active_curtailment(
        client,
        turbine["id"],
        turbine["version"],
        reason=CURTAILMENT_REASON_NOISE,
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-01T06:00:00Z",
        power_limit_kw=1500,
        deemed_kwh_per_hour=500,
    )
    released = get_success_data(
        client.release_curtailment_order(
            order["id"], "2026-08-01T06:00:00Z", make_control_room_headers()
        )
    )
    finding = record_blade_damage(
        client,
        turbine["id"],
        inspection_method=INSPECTION_DRONE,
        blade_position="A",
        inspected_at="2026-08-01T00:00:00Z",
        damage_category=1,
        damage_type=DAMAGE_LEADING_EDGE_EROSION,
        chord_position_pct=12.0,
        damage_length_mm=60,
        exposed_area_cm2=8,
    )
    waived = get_success_data(
        client.waive_blade_damage(
            finding["id"], "cosmetic coating loss inside tolerance", make_engineer_headers()
        )
    )
    return {
        "farm": farm,
        "turbine": turbine,
        "curtailment": released,
        "finding": waived,
    }


def setup_replay_targets(client: WindOpsApiClient) -> Dict[str, Row]:
    """A window already CONFIRMED and an order already SUBMITTED, ready to be re-triggered."""
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    window = confirmed_window(client, farm["id"])
    order = submitted_work_order(client, turbine["id"], submitter=make_planner_headers())
    return {"farm": farm, "turbine": turbine, "window": window, "order": order}


def setup_shared_window_two_orders(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two crews holding two SCHEDULED orders inside one confirmed window.

    The two four-hour bookings meet end-to-start at noon, so neither the turbine
    nor either crew is double-booked, and both are driven by distinct crews so the
    window itself is the only shared resource.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    crew_a = create_crew(
        client,
        farm["id"],
        crew_code="C-ALPHA",
        technician_count=4,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    crew_b = create_crew(
        client,
        farm["id"],
        crew_code="C-BRAVO",
        technician_count=3,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=80000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T06:00:00Z",
        end_utc="2026-08-10T18:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
    )
    order_a = scheduled_work_order(
        client,
        turbine["id"],
        crew_a["id"],
        window["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=4,
    )
    order_b = scheduled_work_order(
        client,
        turbine["id"],
        crew_b["id"],
        window["id"],
        "2026-08-10T12:00:00Z",
        "2026-08-10T16:00:00Z",
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=4,
    )
    return {
        "farm": farm,
        "turbine": turbine,
        "crew_a": crew_a,
        "crew_b": crew_b,
        "window": window,
        "order_a": order_a,
        "order_b": order_b,
    }


def setup_reset_track_trio(client: WindOpsApiClient) -> Dict[str, Row]:
    """Three turbines, each carrying a freshly raised fault under a different rule.

    The three rules separate the reasons a remote reset can be refused: F-9001 is
    resettable but marked dispatch-only, F-4002 is a lockout class, and F-5003 is
    resettable with a one-per-day quota so a single spent attempt exhausts it.
    """
    farm = create_farm(client)
    model = create_model(client)
    t1 = create_turbine(client, farm["id"], model["id"], asset_tag="T-01")
    t2 = create_turbine(client, farm["id"], model["id"], asset_tag="T-02")
    t3 = create_turbine(client, farm["id"], model["id"], asset_tag="T-03")
    create_fault_rule(
        client,
        fault_code="F-9001",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        requires_dispatch=True,
    )
    create_fault_rule(
        client,
        fault_code="F-4002",
        severity_class=SEVERITY_LOCKOUT,
        max_remote_resets_per_24h=1,
        requires_dispatch=False,
    )
    create_fault_rule(
        client,
        fault_code="F-5003",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=1,
        requires_dispatch=False,
    )
    return {
        "farm": farm,
        "turbine_dispatch_only": t1,
        "turbine_lockout": t2,
        "turbine_quota": t3,
        "event_dispatch_only": raise_fault(client, t1["id"], "F-9001", "2026-08-01T00:00:00Z"),
        "event_lockout": raise_fault(client, t2["id"], "F-4002", "2026-08-01T00:00:00Z"),
        "event_quota": raise_fault(client, t3["id"], "F-5003", "2026-08-01T00:00:00Z"),
    }


def setup_exclusion_pair_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """A 2000 kWh/h turbine and two rules that differ only in the exclusion flag.

    F-3001 counts against the availability guarantee and F-7002 does not, which is
    the only difference between the two accumulators downstream.  The clock is
    parked at 01:00 so a fault can be raised at that instant.
    """
    set_clock(client, "2026-08-01T01:00:00Z")
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"], expected_kwh_per_hour=2000)
    counted = create_fault_rule(
        client,
        fault_code="F-3001",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        contractual_exclusion=False,
    )
    excluded = create_fault_rule(
        client,
        fault_code="F-7002",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        contractual_exclusion=True,
    )
    return {
        "farm": farm,
        "turbine": turbine,
        "counted_rule": counted,
        "excluded_rule": excluded,
    }


def setup_precision_fault_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """A 1234 kWh/h turbine carrying one fault raised at exactly 01:00:00.

    The awkward production rate is deliberate: a 45-second outage against it lands
    exactly on a half-cent-style tie at the second decimal place.
    """
    set_clock(client, "2026-08-01T01:00:00Z")
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"], expected_kwh_per_hour=1234)
    create_fault_rule(
        client,
        fault_code="F-3001",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        contractual_exclusion=False,
    )
    event = raise_fault(client, turbine["id"], "F-3001", "2026-08-01T01:00:00Z")
    return {"farm": farm, "turbine": turbine, "event": event}


def setup_retired_farm_with_agreement(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm whose only turbine is retired, still carrying one ACTIVE agreement.

    The agreement is opened while the turbine is in service, then the turbine is
    retired, which empties the availability denominator without touching the
    agreement's own state.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=4000000,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
    )
    retired = get_success_data(
        client.decommission_turbine(turbine["id"], "site repowering", make_site_admin_headers())
    )
    return {"farm": farm, "turbine": retired, "agreement": agreement}


def setup_two_farm_crew_pair(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two farms: an uncertified local crew and a certified crew rostered elsewhere.

    The submitted order needs a crane banksman, which only the foreign crew holds, so
    each candidate crew violates exactly one scheduling condition and no other.
    """
    farm_a = create_farm(client)
    farm_b = create_farm(client, name="Judith Gap", region_code="MT-C")
    model = create_model(client)
    turbine = create_turbine(client, farm_a["id"], model["id"])
    crew_local = create_crew(
        client,
        farm_a["id"],
        crew_code="C-LOCAL",
        technician_count=3,
        certifications=[CERT_GWO_BASIC],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    crew_foreign = create_crew(
        client,
        farm_b["id"],
        crew_code="C-FOREIGN",
        technician_count=3,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm_a["id"],
        start_utc="2026-08-10T06:00:00Z",
        end_utc="2026-08-10T18:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
    )
    order = submitted_work_order(
        client,
        turbine["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {
        "farm_a": farm_a,
        "farm_b": farm_b,
        "turbine": turbine,
        "crew_local": crew_local,
        "crew_foreign": crew_foreign,
        "window": window,
        "order": order,
    }


def setup_exact_limit_schedule(client: WindOpsApiClient) -> Dict[str, Row]:
    """A crew, a window and an order whose figures meet three gates by exact equality.

    The crew's wind ceiling equals the window's forecast, its daily capacity equals the
    order's estimated hours, and the window interval is exactly the interval the order
    will claim.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    crew = create_crew(
        client,
        farm["id"],
        crew_code="C-EDGE",
        technician_count=4,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=12,
        hourly_rate_cents=90000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T06:00:00Z",
        end_utc="2026-08-10T18:00:00Z",
        forecast_wind_speed_ms=14.0,
        forecast_gust_ms=19.0,
    )
    order = submitted_work_order(
        client,
        turbine["id"],
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=12,
    )
    return {"farm": farm, "turbine": turbine, "crew": crew, "window": window, "order": order}


def setup_pinning_pair_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """Two turbines on one farm, one resettable rule and one fault already raised.

    The second turbine is left untouched so a later fault on it can be raised against an
    amended rule while the first event keeps the snapshot it was born with.
    """
    set_clock(client, "2026-08-01T01:00:00Z")
    farm = create_farm(client)
    model = create_model(client)
    turbine_one = create_turbine(client, farm["id"], model["id"], asset_tag="T-01")
    turbine_two = create_turbine(client, farm["id"], model["id"], asset_tag="T-02")
    rule = create_fault_rule(
        client,
        fault_code="F-3001",
        severity_class=SEVERITY_RESETTABLE,
        max_remote_resets_per_24h=2,
        requires_dispatch=False,
        contractual_exclusion=False,
    )
    event = raise_fault(client, turbine_one["id"], "F-3001", "2026-08-01T01:00:00Z")
    return {
        "farm": farm,
        "turbine_one": turbine_one,
        "turbine_two": turbine_two,
        "rule": rule,
        "event": event,
    }


def setup_dispatch_required_lockout(client: WindOpsApiClient) -> Dict[str, Row]:
    """A lockout fault already triaged for dispatch, awaiting its dispatch order."""
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    create_fault_rule(
        client,
        fault_code="F-4002",
        severity_class=SEVERITY_LOCKOUT,
        max_remote_resets_per_24h=0,
        requires_dispatch=True,
        contractual_exclusion=False,
    )
    event = dispatch_required_fault_event(
        client, turbine["id"], "F-4002", "2026-08-01T00:00:00Z"
    )
    return {"farm": farm, "turbine": turbine, "event": event}


def setup_crane_lifecycle_site(client: WindOpsApiClient) -> Dict[str, Row]:
    """A planned gearbox replacement under a running order, plus one requested crane.

    The parent order is already in progress so the replacement can be executed, which is
    what eventually frees the crane to leave site.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    part = create_spare_part(client, quantity_on_hand=2, reorder_point=1)
    work = major_component_order_in_progress(
        client, turbine["id"], farm["id"], estimated_hours=20
    )
    replacement = create_replacement(
        client, work["order"]["id"], part["id"], estimated_lift_hours=8.0
    )
    crane = create_crane(client, farm["id"])
    return {
        "farm": farm,
        "turbine": turbine,
        "part": part,
        "order": work["order"],
        "crew": work["crew"],
        "window": work["window"],
        "replacement": replacement,
        "crane": crane,
    }


def setup_role_denial_targets(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm, a turbine and one active agreement, each owned by a different role."""
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    agreement = create_agreement(
        client,
        farm["id"],
        guaranteed_availability_pct=97.0,
        lda_rate_cents_per_pct_point=500000,
        lda_cap_cents=4000000,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
    )
    return {"farm": farm, "model": model, "turbine": turbine, "agreement": agreement}


def setup_wrong_crew_order(client: WindOpsApiClient) -> Dict[str, Row]:
    """An order submitted by the engineer and reserved to crew A, with crew B idle nearby.

    Crew B is certified and free, so the only thing standing between it and the order is
    the assignment itself.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])
    crew_a = create_crew(
        client,
        farm["id"],
        crew_code="C-ALPHA",
        technician_count=4,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    crew_b = create_crew(
        client,
        farm["id"],
        crew_code="C-BRAVO",
        technician_count=3,
        certifications=[CERT_GWO_BASIC, CERT_CRANE_BANKSMAN],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=80000,
    )
    window = confirmed_window(
        client,
        farm["id"],
        start_utc="2026-08-10T06:00:00Z",
        end_utc="2026-08-10T18:00:00Z",
        forecast_wind_speed_ms=8.0,
        forecast_gust_ms=11.0,
    )
    order = scheduled_work_order(
        client,
        turbine["id"],
        crew_a["id"],
        window["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T16:00:00Z",
        submitter=make_engineer_headers(),
        headers=make_engineer_headers(),
        work_type=WORK_TYPE_MAJOR_COMPONENT,
        required_certification=CERT_CRANE_BANKSMAN,
        estimated_hours=8,
    )
    return {
        "farm": farm,
        "turbine": turbine,
        "crew_a": crew_a,
        "crew_b": crew_b,
        "window": window,
        "order": order,
    }


def setup_stale_version_parents(client: WindOpsApiClient) -> Dict[str, Any]:
    """A farm and a turbine whose versions have both moved on since a client read them.

    Each parent is advanced by an ordinary business write — an approved settlement on the
    farm, a telemetry post on the turbine — so the two observed versions are stale without
    anything having poked the rows for the sake of it.
    """
    farm = create_farm(client)
    model = create_model(client)
    turbine = create_turbine(client, farm["id"], model["id"])

    farm_version_seen = read_farm(client, farm["id"])["version"]
    settlement = create_settlement(
        client,
        farm["id"],
        farm_version_seen,
        parcel_code="P-11",
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
        minimum_payment_cents=100000,
        road_damage_assessment_cents=0,
    )
    approved = get_success_data(
        client.approve_landowner_settlement(settlement["id"], make_commercial_headers())
    )

    turbine_version_seen = read_turbine(client, turbine["id"])["version"]
    post_scada(client, turbine["id"], 12.0, 24000.0, 25000.0)

    return {
        "farm": farm,
        "model": model,
        "turbine": turbine,
        "settlement": approved,
        "farm_version_seen": farm_version_seen,
        "turbine_version_seen": turbine_version_seen,
    }


def setup_farm_and_model(client: WindOpsApiClient) -> Dict[str, Row]:
    """A farm and one turbine model, with no turbine commissioned on it yet."""
    return {"farm": create_farm(client), "model": create_model(client)}
