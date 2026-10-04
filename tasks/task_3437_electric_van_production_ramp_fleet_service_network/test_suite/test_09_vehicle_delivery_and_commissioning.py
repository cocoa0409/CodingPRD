"""Vehicle delivery and telematics: parallel state dimensions, the depot
charging demand gate at commissioning, and the software-hold block left by
a campaign rollback."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_delivery_to_at_depot,
    create_and_commission_project,
    create_campaign,
    provision_and_activate_telematics,
    read_vehicle,
    record_campaign_result,
    setup_base_fleet,
    transition_campaign,
    transition_vehicle,
    vehicle_transition_payload,
    validate_error,
    validate_success,
)

_DISPATCHER = TEST_USERS["service_dispatcher_headers"]


def test_vehicle_parallel_dimensions_move_independently(api):
    """PRD section 3.6: "A `ServiceDispatcher` advances one dimension at a
    time by naming a `dimension` (`DELIVERY` or `TELEMATICS`) and a
    `to_state`. On the delivery dimension the van moves `ASSEMBLED →
    IN_TRANSIT → AT_DEPOT → COMMISSIONED` in strict sequence ... On the
    telematics dimension the van is provisioned `OFFLINE → PROVISIONED`,
    activated `PROVISIONED → ACTIVE`, may be suspended `ACTIVE → SUSPENDED`,
    and re-activated `SUSPENDED → ACTIVE`; telematics has no terminal state."

    Design: Corner/state_machines/vehicle_parallel_dimensions_move_independently
    """
    fleet = setup_base_fleet(quantity=2)
    veh_id = fleet["vehicles"][0]["id"]
    transition_vehicle(veh_id, "TELEMATICS", "PROVISIONED")
    mid = read_vehicle(veh_id)
    assert mid["telematics_status"] == "PROVISIONED"
    assert mid["delivery_status"] == "ASSEMBLED", (
        "telematics progression has no delivery precondition and leaves delivery untouched"
    )
    transition_vehicle(veh_id, "TELEMATICS", "ACTIVE")
    transition_vehicle(veh_id, "DELIVERY", "IN_TRANSIT")
    suspended = transition_vehicle(veh_id, "TELEMATICS", "SUSPENDED")
    assert suspended["telematics_status"] == "SUSPENDED"
    final = read_vehicle(veh_id)
    assert final["delivery_status"] == "IN_TRANSIT", (
        "the delivery dimension is untouched by the telematics suspend"
    )
    assert final["telematics_status"] == "SUSPENDED"


def _setup_at_depot_with_charging_requirement():
    """One-vehicle order with requires_depot_charging true; the vehicle is
    telematics ACTIVE and parked AT_DEPOT."""
    fleet = setup_base_fleet(quantity=1, requires_depot_charging=True)
    veh_id = fleet["vehicles"][0]["id"]
    provision_and_activate_telematics(veh_id)
    advance_delivery_to_at_depot(veh_id)
    return fleet, veh_id


def test_commission_blocked_without_commissioned_charging_capacity(api):
    """PRD section 3.6: "When the parent order's `requires_depot_charging` is
    true, one further gate applies — the depot charging demand gate, which
    looks only at finished infrastructure: sum `commissioned_capacity_kw` over
    the depot's `COMMISSIONED` charging projects (in-flight projects never
    count), multiply by a utilization factor of 0.8, and require the result to
    be at least the draw of the in-service fleet plus the commissioning
    candidate ... A shortfall is rejected with
    `ERR_CHARGING_CAPACITY_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/commission_requires_depot_charging_capacity
    """
    fleet, veh_id = _setup_at_depot_with_charging_requirement()
    resp = api.transition_vehicle(
        veh_id, vehicle_transition_payload("DELIVERY", "COMMISSIONED"), _DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CHARGING_CAPACITY_INSUFFICIENT)
    vehicle = read_vehicle(veh_id)
    assert vehicle["delivery_status"] == "AT_DEPOT", "the gated transition did not advance"
    assert vehicle["telematics_status"] == "ACTIVE", (
        "the telematics dimension is independent and untouched"
    )


def test_commission_unlocked_once_charging_project_commissioned(api):
    """PRD section 3.6: "multiply by a utilization factor of 0.8, and require
    the result to be at least the draw of the in-service fleet plus the
    commissioning candidate — the number of vehicles already `COMMISSIONED` at
    that depot across all customers' orders, plus one, times 19.2 kW per
    vehicle. Equality passes, because the comparison is at-least."

    Design: Difficulty/cross_entity_state_dependency/commission_requires_depot_charging_capacity
    """
    fleet, veh_id = _setup_at_depot_with_charging_requirement()
    resp = api.transition_vehicle(
        veh_id, vehicle_transition_payload("DELIVERY", "COMMISSIONED"), _DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CHARGING_CAPACITY_INSUFFICIENT)
    create_and_commission_project(fleet["customer"], fleet["depot"], requested_capacity_kw=25)
    done = transition_vehicle(veh_id, "DELIVERY", "COMMISSIONED")
    assert done["delivery_status"] == "COMMISSIONED", (
        "25 kW commissioned x 0.8 = 20 >= 19.2 required for one vehicle"
    )
    assert read_vehicle(veh_id)["telematics_status"] == "ACTIVE"


def test_campaign_rollback_hold_blocks_commissioning(api):
    """PRD section 3.7: "Link 1: every vehicle holding a `SUCCESS` entry in
    this campaign's `results` and currently telematics `ACTIVE` gets
    `software_hold` set true. Link 2: each such vehicle whose `delivery_status`
    is `IN_TRANSIT` reverts to `ASSEMBLED` — a physical recall of vans on the
    road."; PRD section 3.6: "that `software_hold` be false (a held vehicle
    is refused with `ERR_SOFTWARE_HOLD`)".

    Design: Corner/state_machines/campaign_rollback_hold_blocks_commissioning
    """
    fleet = setup_base_fleet(quantity=2)
    veh_id = fleet["vehicles"][0]["id"]
    provision_and_activate_telematics(veh_id)
    advance_delivery_to_at_depot(veh_id)
    campaign = create_campaign(target_version="2.0.0", telematics_tier_scope="ALL")
    transition_campaign(campaign["id"], "CANARY")
    record_campaign_result(campaign["id"], veh_id, "SUCCESS")
    transition_campaign(campaign["id"], "ROLLED_BACK")
    vehicle = read_vehicle(veh_id)
    assert vehicle["software_hold"] is True
    assert vehicle["delivery_status"] == "AT_DEPOT", (
        "AT_DEPOT is not recalled — only IN_TRANSIT reverts"
    )
    resp = api.transition_vehicle(
        veh_id, vehicle_transition_payload("DELIVERY", "COMMISSIONED"), _DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_SOFTWARE_HOLD)
    assert read_vehicle(veh_id)["delivery_status"] == "AT_DEPOT"
