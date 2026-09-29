"""Composite setup helpers.

The helpers are layered. The first layer positions the logical clock and
registers reference configuration; the second opens a plan and buys units;
the third walks a car through in-fleeting to service; the fourth accumulates
usage or drives a plan to a chosen fill ratio; the fifth carries a unit into
the disposal or damage workflows. Every helper uses the lenient success
reader so that a setup failure surfaces as the API error it really was.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import BASE_CLOCK
from .test_users import (
    FLEET_CONTROLLER_A_ID,
    FLEET_CONTROLLER_B_ID,
    REMARKETING_MANAGER_A_ID,
    REMARKETING_MANAGER_B_ID,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    make_market_operator_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
)
from .types import ChannelCode, RecoverySource, Season

# --------------------------------------------------------------------------
# Layer 0: the logical clock
# --------------------------------------------------------------------------


def set_clock(client: ApiClient, instant: str) -> Dict[str, Any]:
    """Reposition the logical clock. Repositioning is never retroactive."""
    return get_success_data(
        client.set_clock(f.clock_payload(instant), make_platform_admin_headers())
    )


def read_clock(client: ApiClient) -> Dict[str, Any]:
    return get_success_data(client.get_clock(make_platform_admin_headers()))


# --------------------------------------------------------------------------
# Layer 1: reference configuration
# --------------------------------------------------------------------------


class FleetWorld:
    """Identifier book for a scenario's reference configuration."""

    def __init__(self) -> None:
        self.markets: Dict[str, Dict[str, Any]] = {}
        self.segments: Dict[str, Dict[str, Any]] = {}
        self.programs: Dict[str, Dict[str, Any]] = {}
        self.channels: Dict[str, Dict[str, Any]] = {}
        self.policies: Dict[str, Dict[str, Any]] = {}

    # -- markets
    def market_id(self, code: str) -> str:
        return self.markets[code]["id"]

    def operator(self, code: str) -> Dict[str, str]:
        """Headers for the branch operator of the market with that code."""
        return make_market_operator_headers(self.market_id(code))

    # -- segments / programs / channels / policies
    def segment_id(self, code: str) -> str:
        return self.segments[code]["id"]

    def program_id(self, key: str) -> str:
        return self.programs[key]["id"]

    def channel_id(self, code: str) -> str:
        return self.channels[code]["id"]

    def policy_id(self, segment_code: str) -> str:
        return self.policies[segment_code]["id"]


def create_market(client: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(client.create_market(payload, make_platform_admin_headers()))


def create_segment(client: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.create_vehicle_segment(payload, make_platform_admin_headers())
    )


def create_program(client: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.create_manufacturer_program(payload, make_platform_admin_headers())
    )


def create_channel(client: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.create_remarketing_channel(payload, make_platform_admin_headers())
    )


def create_active_policy(
    client: ApiClient,
    segment_id: str,
    name: str = "MID-2026",
    monthly_depreciation_pct: float = 0.015,
    mileage_depreciation_cents_per_km: int = 12,
    floor_residual_pct: float = 0.35,
    effective_from: str = "2026-01-01T00:00:00.000Z",
    supersedes_policy_id: Optional[str] = None,
    drafted_by: str = FLEET_CONTROLLER_A_ID,
    activated_by: str = FLEET_CONTROLLER_B_ID,
) -> Dict[str, Any]:
    """Draft a policy with one controller and activate it with another."""
    draft = get_success_data(
        client.create_depreciation_policy(
            f.depreciation_policy_payload(
                segment_id,
                name=name,
                monthly_depreciation_pct=monthly_depreciation_pct,
                mileage_depreciation_cents_per_km=mileage_depreciation_cents_per_km,
                floor_residual_pct=floor_residual_pct,
                effective_from=effective_from,
                supersedes_policy_id=supersedes_policy_id,
            ),
            make_fleet_controller_headers(drafted_by),
        )
    )
    return get_success_data(
        client.activate_depreciation_policy(
            draft["id"], make_fleet_controller_headers(activated_by)
        )
    )


def setup_reference_world(
    client: ApiClient,
    clock: str = BASE_CLOCK,
    market_payloads: Optional[List[Dict[str, Any]]] = None,
    segment_payloads: Optional[List[Dict[str, Any]]] = None,
    channel_payloads: Optional[List[Dict[str, Any]]] = None,
    with_programs: bool = True,
    with_policy: bool = True,
) -> FleetWorld:
    """Position the clock, then register markets, segments, programs, channels.

    The default world holds three markets, the midsize segment, one guaranteed
    and one full-risk program, and the auction, retail-lot and repurchase
    channels — enough for the valuation and channel-selection rules to have
    something to choose between.
    """
    set_clock(client, clock)
    world = FleetWorld()

    for payload in market_payloads if market_payloads is not None else [f.ATL, f.DFW, f.ORD]:
        row = create_market(client, dict(payload))
        world.markets[row["code"]] = row

    for payload in segment_payloads if segment_payloads is not None else [f.MIDSIZE]:
        row = create_segment(client, dict(payload))
        world.segments[row["code"]] = row

    if with_programs:
        world.programs["PGM"] = create_program(client, dict(f.PROGRAM_GUARANTEED))
        world.programs["RSK"] = create_program(client, dict(f.PROGRAM_RISK))

    channels = (
        channel_payloads
        if channel_payloads is not None
        else [f.CHANNEL_AUCTION, f.CHANNEL_RETAIL_LOT, f.CHANNEL_PROGRAM_REPURCHASE]
    )
    for payload in channels:
        row = create_channel(client, dict(payload))
        world.channels[row["code"]] = row

    if with_policy:
        for code in world.segments:
            world.policies[code] = create_active_policy(
                client, world.segment_id(code), name=f"{code}-2026"
            )

    return world


# --------------------------------------------------------------------------
# Layer 2: plans, allocations and minted cars
# --------------------------------------------------------------------------


def draft_plan(
    client: ApiClient,
    market_id: str,
    season: str = Season.PEAK,
    plan_year: int = 2026,
    planned_unit_count: int = 10,
    revenue_per_unit_target_cents: int = 132000,
    utilization_target_pct: float = 0.80,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_fleet_plan(
            f.fleet_plan_payload(
                market_id,
                season=season,
                plan_year=plan_year,
                planned_unit_count=planned_unit_count,
                revenue_per_unit_target_cents=revenue_per_unit_target_cents,
                utilization_target_pct=utilization_target_pct,
            ),
            make_fleet_planner_headers(),
        )
    )


def lock_plan(client: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.lock_fleet_plan(plan_id, make_fleet_controller_headers())
    )


def setup_locked_plan(
    client: ApiClient,
    world: FleetWorld,
    market_code: str = "ATL",
    season: str = Season.PEAK,
    plan_year: int = 2026,
    planned_unit_count: int = 10,
) -> Dict[str, Any]:
    """A plan committed to its sizing and ready to take allocations."""
    plan = draft_plan(
        client,
        world.market_id(market_code),
        season=season,
        plan_year=plan_year,
        planned_unit_count=planned_unit_count,
    )
    return lock_plan(client, plan["id"])


def add_allocation(
    client: ApiClient,
    plan_id: str,
    program_id: str,
    segment_id: str,
    unit_count: int,
    expected_plan_version: int,
    capitalized_cost_per_unit_cents: int = f.CAPITALIZED_COST_CENTS,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_purchase_allocation(
            plan_id,
            f.purchase_allocation_payload(
                program_id,
                segment_id,
                unit_count,
                expected_plan_version,
                capitalized_cost_per_unit_cents=capitalized_cost_per_unit_cents,
            ),
            make_fleet_planner_headers(),
        )
    )


def read_plan(client: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_fleet_plan(plan_id, make_fleet_planner_headers()))


def read_allocation(client: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_purchase_allocation(allocation_id, make_fleet_planner_headers())
    )


def read_vehicle(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_vehicle(vehicle_id, make_fleet_planner_headers()))


def read_market(client: ApiClient, market_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_market(market_id, make_platform_admin_headers()))


def census(client: ApiClient, market_id: str) -> int:
    """The market's live in-service census."""
    return read_market(client, market_id)["in_service_unit_count"]


def mint_vehicle(
    client: ApiClient,
    allocation_id: str,
    vin: str,
    market_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_vehicle(
            allocation_id, f.vehicle_payload(vin, market_id), make_fleet_planner_headers()
        )
    )


def setup_allocation_with_units(
    client: ApiClient,
    world: FleetWorld,
    market_code: str = "ATL",
    program_key: str = "RSK",
    segment_code: str = "MIDSIZE",
    unit_count: int = 1,
    planned_unit_count: int = 10,
    vin_prefix: str = "A",
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A locked plan, one allocation and its minted cars.

    Returns a dict with the plan, the allocation and the list of vehicles.
    """
    if plan is None:
        plan = setup_locked_plan(
            client, world, market_code=market_code, planned_unit_count=planned_unit_count
        )
    allocation = add_allocation(
        client,
        plan["id"],
        world.program_id(program_key),
        world.segment_id(segment_code),
        unit_count,
        plan["version"],
    )
    vehicles = [
        mint_vehicle(
            client,
            allocation["id"],
            f.vin(f"{vin_prefix}{index}"),
            world.market_id(market_code),
        )
        for index in range(1, unit_count + 1)
    ]
    return {
        "plan": read_plan(client, plan["id"]),
        "allocation": read_allocation(client, allocation["id"]),
        "vehicles": vehicles,
    }


# --------------------------------------------------------------------------
# Layer 3: the in-fleeting chain, from delivery to first rent
# --------------------------------------------------------------------------


def in_fleet(client: ApiClient, world: FleetWorld, vehicle_id: str, market_code: str) -> Dict[str, Any]:
    """Take delivery: ON_ORDER to IN_FLEETING, done by the branch."""
    return get_success_data(
        client.in_fleet_vehicle(vehicle_id, world.operator(market_code))
    )


def schedule_task(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    payload: Dict[str, Any],
    market_code: str = "ATL",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_in_fleeting_task(vehicle_id, payload, world.operator(market_code))
    )


def complete_task(
    client: ApiClient, world: FleetWorld, task_id: str, market_code: str = "ATL"
) -> Dict[str, Any]:
    return get_success_data(
        client.complete_in_fleeting_task(task_id, world.operator(market_code))
    )


def waive_task(
    client: ApiClient, task_id: str, controller_id: str = FLEET_CONTROLLER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.waive_in_fleeting_task(task_id, make_fleet_controller_headers(controller_id))
    )


def bring_to_in_service(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    market_code: str = "ATL",
    prep_date: str = "2026-01-07",
    bay_code: str = "B1",
    registration_cost_cents: int = 14000,
    licensing_cost_cents: int = 9000,
    prep_cost_cents: int = 21000,
    in_service_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk one car from ON_ORDER to IN_SERVICE through all three tasks.

    The preparation window sits on ``prep_date`` so that callers driving
    several cars through the same market can spread the bay calendar and stay
    inside the market's daily preparation capacity. When ``in_service_clock``
    is given the clock is repositioned just before the final completion, so
    the promotion instants land on a chosen date.
    """
    in_fleet(client, world, vehicle_id, market_code)

    registration = schedule_task(
        client,
        world,
        vehicle_id,
        f.registration_task_payload(cost_cents=registration_cost_cents),
        market_code,
    )
    complete_task(client, world, registration["id"], market_code)

    licensing = schedule_task(
        client,
        world,
        vehicle_id,
        f.licensing_task_payload(cost_cents=licensing_cost_cents),
        market_code,
    )
    complete_task(client, world, licensing["id"], market_code)

    preparation = schedule_task(
        client,
        world,
        vehicle_id,
        f.preparation_task_payload(
            bay_code=bay_code,
            window_start=f"{prep_date}T08:00:00.000Z",
            window_end=f"{prep_date}T10:00:00.000Z",
            cost_cents=prep_cost_cents,
        ),
        market_code,
    )
    if in_service_clock is not None:
        set_clock(client, in_service_clock)
    complete_task(client, world, preparation["id"], market_code)

    return {
        "vehicle": read_vehicle(client, vehicle_id),
        "registration_task": registration,
        "licensing_task": licensing,
        "preparation_task": preparation,
    }


def setup_in_service_vehicle(
    client: ApiClient,
    world: FleetWorld,
    market_code: str = "ATL",
    program_key: str = "RSK",
    segment_code: str = "MIDSIZE",
    planned_unit_count: int = 10,
    unit_count: int = 1,
    vin_prefix: str = "A",
    prep_date: str = "2026-01-07",
    bay_code: str = "B1",
    in_service_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A single earning car, with its whole ancestry, ready to be driven."""
    bought = setup_allocation_with_units(
        client,
        world,
        market_code=market_code,
        program_key=program_key,
        segment_code=segment_code,
        unit_count=unit_count,
        planned_unit_count=planned_unit_count,
        vin_prefix=vin_prefix,
    )
    vehicle_id = bought["vehicles"][0]["id"]
    promoted = bring_to_in_service(
        client,
        world,
        vehicle_id,
        market_code=market_code,
        prep_date=prep_date,
        bay_code=bay_code,
        in_service_clock=in_service_clock,
    )
    return {
        "plan": read_plan(client, bought["plan"]["id"]),
        "allocation": read_allocation(client, bought["allocation"]["id"]),
        "vehicle": promoted["vehicle"],
        "tasks": {
            "registration": promoted["registration_task"],
            "licensing": promoted["licensing_task"],
            "preparation": promoted["preparation_task"],
        },
    }


# --------------------------------------------------------------------------
# Layer 4: accumulation and threshold targeting
# --------------------------------------------------------------------------


def post_usage(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    odometer_km: int,
    market_code: str = "ATL",
    rented_days_delta: int = 0,
    available_days_delta: int = 0,
    revenue_cents_delta: int = 0,
) -> Dict[str, Any]:
    """Report a cumulative odometer reading plus three increments."""
    return get_success_data(
        client.post_usage(
            vehicle_id,
            f.usage_payload(
                odometer_km,
                rented_days_delta=rented_days_delta,
                available_days_delta=available_days_delta,
                revenue_cents_delta=revenue_cents_delta,
            ),
            world.operator(market_code),
        )
    )


def drive_to_odometer(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    odometer_km: int,
    market_code: str = "ATL",
) -> Dict[str, Any]:
    """Move a car's odometer to an exact reading and nothing else."""
    return post_usage(client, world, vehicle_id, odometer_km, market_code=market_code)


def fill_plan_to(
    client: ApiClient,
    world: FleetWorld,
    plan: Dict[str, Any],
    unit_counts: List[int],
    program_key: str = "RSK",
    segment_code: str = "MIDSIZE",
) -> Dict[str, Any]:
    """Add one allocation per entry, refreshing the plan version each time.

    Returns the plan as it reads after the last allocation, together with the
    allocations created, so a caller can walk a fill ratio up to a chosen
    posture boundary one step at a time.
    """
    allocations = []
    current = plan
    for units in unit_counts:
        allocation = add_allocation(
            client,
            current["id"],
            world.program_id(program_key),
            world.segment_id(segment_code),
            units,
            current["version"],
        )
        allocations.append(allocation)
        current = read_plan(client, current["id"])
    return {"plan": current, "allocations": allocations}


def setup_earning_vehicle(
    client: ApiClient,
    world: FleetWorld,
    market_code: str = "ATL",
    program_key: str = "RSK",
    odometer_km: int = 0,
    rented_days: int = 0,
    available_days: int = 0,
    revenue_cents: int = 0,
    in_service_clock: Optional[str] = None,
    vin_prefix: str = "A",
    prep_date: str = "2026-01-07",
) -> Dict[str, Any]:
    """An in-service car carrying a chosen odometer and usage history."""
    built = setup_in_service_vehicle(
        client,
        world,
        market_code=market_code,
        program_key=program_key,
        vin_prefix=vin_prefix,
        prep_date=prep_date,
        in_service_clock=in_service_clock,
    )
    if odometer_km or rented_days or available_days or revenue_cents:
        post_usage(
            client,
            world,
            built["vehicle"]["id"],
            odometer_km,
            market_code=market_code,
            rented_days_delta=rented_days,
            available_days_delta=available_days,
            revenue_cents_delta=revenue_cents,
        )
        built["vehicle"] = read_vehicle(client, built["vehicle"]["id"])
    return built


# --------------------------------------------------------------------------
# Layer 5a: damage, recovery and total loss
# --------------------------------------------------------------------------


def report_damage(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    estimate_cents: int,
    market_code: str = "ATL",
    damage_type: str = "COLLISION",
) -> Dict[str, Any]:
    """File a claim from the branch holding the car."""
    return get_success_data(
        client.create_damage_event(
            vehicle_id,
            f.damage_event_payload(estimate_cents, damage_type=damage_type),
            world.operator(market_code),
        )
    )


def revise_estimate(
    client: ApiClient,
    world: FleetWorld,
    damage_event_id: str,
    estimate_cents: int,
    market_code: str = "ATL",
) -> Dict[str, Any]:
    return get_success_data(
        client.revise_damage_estimate(
            damage_event_id,
            f.revise_estimate_payload(estimate_cents),
            world.operator(market_code),
        )
    )


def open_recovery(
    client: ApiClient,
    damage_event_id: str,
    recovery_source: str = RecoverySource.THIRD_PARTY_INSURER,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.open_damage_recovery(
            damage_event_id,
            f.open_recovery_payload(recovery_source),
            make_remarketing_manager_headers(manager_id),
        )
    )


def settle_recovery(
    client: ApiClient,
    damage_event_id: str,
    recovered_cents: int,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.settle_damage_recovery(
            damage_event_id,
            f.settle_recovery_payload(recovered_cents),
            make_remarketing_manager_headers(manager_id),
        )
    )


def write_off_damage(
    client: ApiClient, damage_event_id: str, controller_id: str = FLEET_CONTROLLER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.write_off_damage_event(
            damage_event_id, make_fleet_controller_headers(controller_id)
        )
    )


def declare_total_loss(
    client: ApiClient,
    damage_event_id: str,
    salvage_proceeds_cents: int,
    controller_id: str = FLEET_CONTROLLER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.declare_total_loss(
            damage_event_id,
            f.total_loss_payload(salvage_proceeds_cents),
            make_fleet_controller_headers(controller_id),
        )
    )


def setup_recovery_pending_event(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    estimate_cents: int,
    market_code: str = "ATL",
    recovery_source: str = RecoverySource.THIRD_PARTY_INSURER,
) -> Dict[str, Any]:
    """A claim opened against an insurer and waiting to be settled."""
    event = report_damage(
        client, world, vehicle_id, estimate_cents, market_code=market_code
    )
    return open_recovery(client, event["id"], recovery_source=recovery_source)


# --------------------------------------------------------------------------
# Layer 5b: redistribution
# --------------------------------------------------------------------------


def draft_order(
    client: ApiClient,
    vehicle_id: str,
    destination_market_id: str,
    distance_km: int = 200,
    planned_depart_at: str = "2026-03-01T00:00:00.000Z",
    planned_receive_at: str = "2026-03-05T00:00:00.000Z",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_redistribution_order(
            f.redistribution_order_payload(
                vehicle_id,
                destination_market_id,
                distance_km=distance_km,
                planned_depart_at=planned_depart_at,
                planned_receive_at=planned_receive_at,
            ),
            make_fleet_planner_headers(),
        )
    )


def propose_order(client: ApiClient, order_id: str, planner_id: Optional[str] = None):
    headers = (
        make_fleet_planner_headers(planner_id)
        if planner_id is not None
        else make_fleet_planner_headers()
    )
    return get_success_data(client.propose_order(order_id, headers))


def reject_order(
    client: ApiClient,
    order_id: str,
    reason: str = "sizing revisited",
    controller_id: str = FLEET_CONTROLLER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.reject_order(
            order_id,
            f.rejection_payload(reason),
            make_fleet_controller_headers(controller_id),
        )
    )


def authorize_order(
    client: ApiClient, order_id: str, controller_id: str = FLEET_CONTROLLER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.authorize_order(order_id, make_fleet_controller_headers(controller_id))
    )


def depart_order(
    client: ApiClient, world: FleetWorld, order_id: str, origin_market_code: str
) -> Dict[str, Any]:
    return get_success_data(
        client.depart_order(order_id, world.operator(origin_market_code))
    )


def receive_order(
    client: ApiClient,
    world: FleetWorld,
    order_id: str,
    destination_market_code: str,
    actual_transport_cost_cents: int,
    odometer_km: int,
) -> Dict[str, Any]:
    return get_success_data(
        client.receive_order(
            order_id,
            f.receive_payload(actual_transport_cost_cents, odometer_km),
            world.operator(destination_market_code),
        )
    )


def cancel_order(
    client: ApiClient, order_id: str, controller_id: str = FLEET_CONTROLLER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.cancel_order(order_id, make_fleet_controller_headers(controller_id))
    )


def setup_authorized_order(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    destination_code: str = "DFW",
    distance_km: int = 200,
    planned_depart_at: str = "2026-03-01T00:00:00.000Z",
    planned_receive_at: str = "2026-03-05T00:00:00.000Z",
    proposer_id: Optional[str] = None,
    authorizer_id: str = FLEET_CONTROLLER_A_ID,
) -> Dict[str, Any]:
    """A haul signed off by a controller other than its proposer."""
    order = draft_order(
        client,
        vehicle_id,
        world.market_id(destination_code),
        distance_km=distance_km,
        planned_depart_at=planned_depart_at,
        planned_receive_at=planned_receive_at,
    )
    propose_order(client, order["id"], planner_id=proposer_id)
    return authorize_order(client, order["id"], controller_id=authorizer_id)


def setup_in_transit_order(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    origin_code: str = "ATL",
    destination_code: str = "DFW",
    distance_km: int = 200,
    planned_depart_at: str = "2026-03-01T00:00:00.000Z",
    planned_receive_at: str = "2026-03-05T00:00:00.000Z",
    depart_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A car already on the truck, out of both markets' censuses."""
    order = setup_authorized_order(
        client,
        world,
        vehicle_id,
        destination_code=destination_code,
        distance_km=distance_km,
        planned_depart_at=planned_depart_at,
        planned_receive_at=planned_receive_at,
    )
    if depart_clock is not None:
        set_clock(client, depart_clock)
    return depart_order(client, world, order["id"], origin_code)


# --------------------------------------------------------------------------
# Layer 5c: consignment and disposal
# --------------------------------------------------------------------------


def consign(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    channel_code: str = ChannelCode.AUCTION,
    manager_id: str = REMARKETING_MANAGER_A_ID,
    expected_vehicle_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Hold a car for sale on one channel, freezing its reserve."""
    version = (
        expected_vehicle_version
        if expected_vehicle_version is not None
        else read_vehicle(client, vehicle_id)["version"]
    )
    return get_success_data(
        client.create_consignment(
            f.consignment_payload(vehicle_id, world.channel_id(channel_code), version),
            make_remarketing_manager_headers(manager_id),
        )
    )


def authorize_recondition(
    client: ApiClient,
    consignment_id: str,
    recondition_authorized_cents: int,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.authorize_recondition(
            consignment_id,
            f.authorize_recondition_payload(recondition_authorized_cents),
            make_remarketing_manager_headers(manager_id),
        )
    )


def complete_recondition(
    client: ApiClient,
    consignment_id: str,
    recondition_actual_cents: int,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.complete_recondition(
            consignment_id,
            f.complete_recondition_payload(recondition_actual_cents),
            make_remarketing_manager_headers(manager_id),
        )
    )


def publish_consignment(
    client: ApiClient, consignment_id: str, manager_id: str = REMARKETING_MANAGER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.list_consignment(consignment_id, make_remarketing_manager_headers(manager_id))
    )


def record_sale(
    client: ApiClient,
    consignment_id: str,
    gross_proceeds_cents: int,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    return get_success_data(
        client.record_sale(
            consignment_id,
            f.record_sale_payload(gross_proceeds_cents),
            make_remarketing_manager_headers(manager_id),
        )
    )


def settle_consignment(
    client: ApiClient, consignment_id: str, manager_id: str = REMARKETING_MANAGER_B_ID
) -> Dict[str, Any]:
    """Settlement is the second half of a two-man control."""
    return get_success_data(
        client.settle_consignment(consignment_id, make_remarketing_manager_headers(manager_id))
    )


def withdraw_consignment(
    client: ApiClient, consignment_id: str, manager_id: str = REMARKETING_MANAGER_A_ID
) -> Dict[str, Any]:
    return get_success_data(
        client.withdraw_consignment(
            consignment_id, make_remarketing_manager_headers(manager_id)
        )
    )


def setup_reconditioned_consignment(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    channel_code: str = ChannelCode.AUCTION,
    recondition_authorized_cents: int = 90000,
    recondition_actual_cents: int = 45500,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    """A consignment that went through the shop and booked its spend."""
    consignment = consign(
        client, world, vehicle_id, channel_code=channel_code, manager_id=manager_id
    )
    authorize_recondition(
        client, consignment["id"], recondition_authorized_cents, manager_id=manager_id
    )
    return complete_recondition(
        client, consignment["id"], recondition_actual_cents, manager_id=manager_id
    )


def setup_listed_consignment(
    client: ApiClient,
    world: FleetWorld,
    vehicle_id: str,
    channel_code: str = ChannelCode.AUCTION,
    through_shop: bool = False,
    recondition_authorized_cents: int = 90000,
    recondition_actual_cents: int = 45500,
    manager_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, Any]:
    """A published consignment, optionally by way of the body shop."""
    if through_shop:
        consignment = setup_reconditioned_consignment(
            client,
            world,
            vehicle_id,
            channel_code=channel_code,
            recondition_authorized_cents=recondition_authorized_cents,
            recondition_actual_cents=recondition_actual_cents,
            manager_id=manager_id,
        )
    else:
        consignment = consign(
            client, world, vehicle_id, channel_code=channel_code, manager_id=manager_id
        )
    return publish_consignment(client, consignment["id"], manager_id=manager_id)


def read_consignment(client: ApiClient, consignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_consignment(consignment_id, make_remarketing_manager_headers())
    )


def read_order(client: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_redistribution_order(order_id, make_fleet_planner_headers())
    )


def read_damage_event(client: ApiClient, damage_event_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_damage_event(damage_event_id, make_fleet_planner_headers())
    )


def read_task(client: ApiClient, task_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_in_fleeting_task(task_id, make_fleet_planner_headers())
    )


def read_valuation(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_valuation(vehicle_id, make_fleet_planner_headers()))


def read_ledger(client: ApiClient, vehicle_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Every ledger row for one unit, oldest posting first."""
    body = client.list_vehicle_ledger_entries(
        vehicle_id, make_fleet_planner_headers(), limit=limit
    )
    return get_success_data(body)


def suspend_market(client: ApiClient, market_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.suspend_market(market_id, make_platform_admin_headers())
    )


def suspend_channel(client: ApiClient, channel_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.suspend_remarketing_channel(channel_id, make_platform_admin_headers())
    )


def close_program(client: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.close_manufacturer_program(program_id, make_platform_admin_headers())
    )
