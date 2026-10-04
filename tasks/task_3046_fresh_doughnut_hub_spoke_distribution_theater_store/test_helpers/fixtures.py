"""Composite setup helpers for the doughnut hub-and-spoke domain.

Every helper builds its preconditions from scratch against a freshly restarted
server: the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_batch_payload,
    create_door_payload,
    create_fundraiser_order_payload,
    create_hot_light_window_payload,
    create_hub_payload,
    create_line_payload,
    create_mix_plan_line_payload,
    create_mix_plan_payload,
    create_network_payload,
    create_route_payload,
    create_route_stop_payload,
    create_shipment_payload,
    create_stale_credit_payload,
    create_variety_payload,
)
from .test_users import TEST_USERS, make_door_manager_headers

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
RD = TEST_USERS["route_driver_headers"]

DEFAULT_DATE = "2026-09-01"


def dm(door_id):
    """DoorManager headers threaded to the owning door's id (ownership-gated)."""
    return make_door_manager_headers(door_id)


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def create_network(network_code="N1", **overrides):
    return get_success_data(
        api.create_network(create_network_payload(network_code=network_code, **overrides), NA)
    )


def create_hub(network_id, hub_code="H1", region="R1", capacity=500, **overrides):
    return get_success_data(
        api.create_hub(
            network_id,
            create_hub_payload(
                hub_code=hub_code,
                daily_capacity_dozens=capacity,
                territory_region=region,
                **overrides,
            ),
            NA,
        )
    )


def create_line(network_id, hub_id, **overrides):
    return get_success_data(
        api.create_line(network_id, hub_id, create_line_payload(**overrides), HM)
    )


def create_door(network_id, door_kind="THEATER", ownership="COMPANY", region="R1",
                hub_id=None, **overrides):
    payload = create_door_payload(
        door_kind=door_kind, ownership=ownership, territory_region=region, **overrides
    )
    if hub_id is not None:
        payload["hub_id"] = hub_id
    return get_success_data(api.create_door(network_id, payload, NA))


def create_variety(network_id, variety_code="GLAZED", collection_kind="CORE",
                   unit_cost_cents=80, **overrides):
    return get_success_data(
        api.create_variety(
            network_id,
            create_variety_payload(
                variety_code=variety_code,
                collection_kind=collection_kind,
                unit_cost_cents=unit_cost_cents,
                **overrides,
            ),
            NA,
        )
    )


def create_batch(network_id, hub_id, line_id, planned_dozens=50,
                 production_date=DEFAULT_DATE, **overrides):
    return get_success_data(
        api.create_batch(
            network_id,
            hub_id,
            create_batch_payload(
                equipment_line_id=line_id,
                production_date=production_date,
                planned_dozens=planned_dozens,
                **overrides,
            ),
            HM,
        )
    )


def create_route(network_id, hub_id, route_code="RT1", service_date=DEFAULT_DATE,
                 vehicle_capacity_dozens=200, **overrides):
    return get_success_data(
        api.create_route(
            network_id,
            hub_id,
            create_route_payload(
                route_code=route_code,
                service_date=service_date,
                vehicle_capacity_dozens=vehicle_capacity_dozens,
                **overrides,
            ),
            RP,
        )
    )


def add_route_stop(network_id, hub_id, route_id, door_id, sequence_no=1,
                   window_start="2026-09-01T08:00:00Z",
                   window_end="2026-09-01T12:00:00Z", **overrides):
    return get_success_data(
        api.add_route_stop(
            network_id,
            hub_id,
            route_id,
            create_route_stop_payload(
                door_id=door_id,
                sequence_no=sequence_no,
                window_start=window_start,
                window_end=window_end,
                **overrides,
            ),
            RP,
        )
    )


def stage_shipment(network_id, hub_id, route_id, stop_id, batch_id, dozens_shipped=10):
    return get_success_data(
        api.stage_shipment(
            network_id,
            hub_id,
            route_id,
            stop_id,
            create_shipment_payload(
                production_batch_id=batch_id, dozens_shipped=dozens_shipped
            ),
            RP,
        )
    )


def create_fundraiser_order(network_id, door_id, organization_name="Test Org",
                            requested_dozens=10, pickup_at="2026-09-03T10:00:00Z",
                            **overrides):
    return get_success_data(
        api.create_fundraiser_order(
            network_id,
            door_id,
            create_fundraiser_order_payload(
                organization_name=organization_name,
                requested_dozens=requested_dozens,
                pickup_at=pickup_at,
                **overrides,
            ),
            dm(door_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: hub + line + door scenario
# ---------------------------------------------------------------------------

def setup_hub_with_line(network_code="N1", hub_code="H1", region="R1", capacity=500,
                        line_overrides=None):
    """Network + hub + one OPERATIONAL equipment line. Returns (network, hub, line)."""
    network = create_network(network_code=network_code)
    hub = create_hub(network["id"], hub_code=hub_code, region=region, capacity=capacity)
    line = create_line(network["id"], hub["id"], **(line_overrides or {}))
    return network, hub, line


# ---------------------------------------------------------------------------
# Tier 3: batch lifecycle shortcuts
# ---------------------------------------------------------------------------

def hub_version(network_id, hub_id):
    return get_success_data(api.get_hub(network_id, hub_id, NA))["version"]


def commit_batch(network_id, hub_id, batch_id):
    """Commit with the hub's current version (fresh OCC read)."""
    return get_success_data(
        api.commit_batch(
            network_id, hub_id, batch_id,
            {"expected_hub_version": hub_version(network_id, hub_id)}, HM,
        )
    )


def complete_batch(network_id, hub_id, batch_id, produced_dozens):
    return get_success_data(
        api.complete_batch(network_id, hub_id, batch_id, {"produced_dozens": produced_dozens}, HM)
    )


def create_completed_batch(network_id, hub_id, line_id, planned_dozens=50,
                           produced_dozens=None, production_date=DEFAULT_DATE):
    """Schedule -> commit -> start -> complete. Returns the COMPLETED batch."""
    batch = create_batch(network_id, hub_id, line_id,
                         planned_dozens=planned_dozens, production_date=production_date)
    commit_batch(network_id, hub_id, batch["id"])
    get_success_data(api.start_batch(network_id, hub_id, batch["id"], HM))
    return complete_batch(
        network_id, hub_id, batch["id"],
        produced_dozens if produced_dozens is not None else planned_dozens,
    )


# ---------------------------------------------------------------------------
# Tier 3: mix plan shortcuts
# ---------------------------------------------------------------------------

def create_mix_plan(network_id, door_id, effective_date=DEFAULT_DATE):
    return get_success_data(
        api.create_mix_plan(
            network_id, door_id,
            create_mix_plan_payload(effective_date=effective_date),
            dm(door_id),
        )
    )


def upsert_line(network_id, door_id, mix_plan_id, variety_id, planned_dozens):
    return get_success_data(
        api.upsert_mix_plan_line(
            network_id, door_id, mix_plan_id,
            create_mix_plan_line_payload(variety_id=variety_id, planned_dozens=planned_dozens),
            dm(door_id),
        )
    )


def mix_plan_version(network_id, door_id, mix_plan_id):
    return get_success_data(
        api.get_mix_plan(network_id, door_id, mix_plan_id, dm(door_id))
    )["version"]


def publish_mix_plan(network_id, door_id, mix_plan_id):
    """Publish with the plan's current version (fresh OCC read)."""
    return get_success_data(
        api.publish_mix_plan(
            network_id, door_id, mix_plan_id,
            {"expected_mix_plan_version": mix_plan_version(network_id, door_id, mix_plan_id)},
            dm(door_id),
        )
    )


def create_published_mix_plan(network_id, door_id, variety_id, planned_dozens=40,
                              effective_date=DEFAULT_DATE):
    """DRAFT plan with one line, published. Returns the PUBLISHED plan."""
    plan = create_mix_plan(network_id, door_id, effective_date=effective_date)
    upsert_line(network_id, door_id, plan["id"], variety_id, planned_dozens)
    return publish_mix_plan(network_id, door_id, plan["id"])


# ---------------------------------------------------------------------------
# Tier 5: full distribution pipeline (batch -> route -> delivery)
# ---------------------------------------------------------------------------

def create_dispatched_route(network_id, hub_id, door_id, batch_id,
                            dozens_shipped=10,
                            window_start="2026-09-01T08:00:00Z",
                            window_end="2026-09-01T12:00:00Z",
                            vehicle_capacity_dozens=200,
                            service_date=DEFAULT_DATE, route_code="RT1"):
    """Create route + one stop for door_id + one shipment from batch_id,
    then lock and dispatch. Returns (route, stop, shipment)."""
    route = create_route(
        network_id, hub_id, route_code=route_code, service_date=service_date,
        vehicle_capacity_dozens=vehicle_capacity_dozens,
    )
    stop = add_route_stop(
        network_id, hub_id, route["id"], door_id,
        window_start=window_start, window_end=window_end,
    )
    shipment = stage_shipment(
        network_id, hub_id, route["id"], stop["id"], batch_id, dozens_shipped
    )
    get_success_data(api.lock_route(network_id, hub_id, route["id"], RP))
    get_success_data(api.dispatch_route(network_id, hub_id, route["id"], RP))
    route = get_success_data(api.get_route(network_id, hub_id, route["id"], RP))
    return route, stop, shipment


def deliver_stop_fully(network_id, hub_id, route_id, stop_id, shipment_ids,
                       arrive_at="2026-09-01T09:00:00Z"):
    """Set clock into the window, arrive, record full delivery on each
    shipment, deliver the stop. Returns the delivered stop."""
    get_success_data(api.set_clock(arrive_at, NA))
    get_success_data(api.arrive_stop(network_id, hub_id, route_id, stop_id, RD))
    for shipment_id, dozens in shipment_ids:
        get_success_data(
            api.record_delivery(network_id, shipment_id, {"dozens_delivered": dozens}, RD)
        )
    return get_success_data(api.deliver_stop(network_id, hub_id, route_id, stop_id, RD))


def setup_delivered_shipment(network_code="N1", region="R1", planned_dozens=100,
                             produced_dozens=None, dozens_shipped=40,
                             dozens_delivered=None, capacity=500,
                             window_start="2026-09-01T08:00:00Z",
                             window_end="2026-09-01T12:00:00Z",
                             arrive_at="2026-09-01T09:00:00Z",
                             line_overrides=None):
    """Full happy path: network, hub with one line, SPOKE FRANCHISE door,
    COMPLETED batch, dispatched route, fully delivered stop.

    Returns a dict with keys: network, hub, line, door, batch, route, stop,
    shipment.
    """
    network, hub, line = setup_hub_with_line(
        network_code=network_code, region=region, capacity=capacity,
        line_overrides=line_overrides,
    )
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE",
        region=region, hub_id=hub["id"],
    )
    batch = create_completed_batch(
        network["id"], hub["id"], line["id"],
        planned_dozens=planned_dozens, produced_dozens=produced_dozens,
    )
    route, stop, shipment = create_dispatched_route(
        network["id"], hub["id"], door["id"], batch["id"],
        dozens_shipped=dozens_shipped,
        window_start=window_start, window_end=window_end,
    )
    deliver_stop_fully(
        network["id"], hub["id"], route["id"], stop["id"],
        [(shipment["id"], dozens_delivered if dozens_delivered is not None else dozens_shipped)],
        arrive_at=arrive_at,
    )
    return {
        "network": network, "hub": hub, "line": line, "door": door,
        "batch": batch, "route": route, "stop": stop, "shipment": shipment,
    }


def create_stale_pull(network_id, door_id, shipment_id, pulled_dozens,
                      pull_time="2026-09-01T13:00:00Z"):
    """Set the clock to pull_time, then report a same-day stale pull.
    Returns the PROVISIONAL StaleCredit."""
    get_success_data(api.set_clock(pull_time, NA))
    return get_success_data(
        api.create_stale_credit(
            network_id, door_id,
            create_stale_credit_payload(shipment_id=shipment_id, pulled_dozens=pulled_dozens),
            dm(door_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: fundraiser lifecycle shortcuts
# ---------------------------------------------------------------------------

def approve_order(network_id, door_id, order_id):
    return get_success_data(
        api.approve_fundraiser_order(network_id, door_id, order_id, dm(door_id))
    )


def schedule_order(network_id, door_id, order_id):
    return get_success_data(
        api.schedule_fundraiser_order(network_id, door_id, order_id, dm(door_id))
    )


def ready_order(network_id, door_id, order_id):
    return get_success_data(
        api.ready_fundraiser_order(network_id, door_id, order_id, dm(door_id))
    )


def setup_ready_fundraiser(network_code="NF", region="RF", capacity=1000,
                           requested_dozens=5, covering_planned_dozens=20,
                           covering_produced_dozens=None,
                           pickup_at="2026-09-01T15:00:00Z",
                           organization_name="Test Org"):
    """THEATER COMPANY door; order approved, scheduled against a covering
    batch, batch completed, order READY (pickup_code minted).

    Returns a dict with keys: network, hub, line, door, order, batch.
    """
    network, hub, line = setup_hub_with_line(
        network_code=network_code, hub_code="HF", region=region, capacity=capacity,
        line_overrides={"service_interval_hours": 300},
    )
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region=region)
    order = create_fundraiser_order(
        network["id"], door["id"],
        organization_name=organization_name,
        requested_dozens=requested_dozens,
        pickup_at=pickup_at,
    )
    approve_order(network["id"], door["id"], order["id"])
    batch = create_batch(
        network["id"], hub["id"], line["id"], planned_dozens=covering_planned_dozens
    )
    commit_batch(network["id"], hub["id"], batch["id"])
    schedule_order(network["id"], door["id"], order["id"])
    get_success_data(api.start_batch(network["id"], hub["id"], batch["id"], HM))
    batch = complete_batch(
        network["id"], hub["id"], batch["id"],
        covering_produced_dozens if covering_produced_dozens is not None else covering_planned_dozens,
    )
    order = ready_order(network["id"], door["id"], order["id"])
    return {
        "network": network, "hub": hub, "line": line, "door": door,
        "order": order, "batch": batch,
    }


# ---------------------------------------------------------------------------
# Tier 3: hot-light shortcuts
# ---------------------------------------------------------------------------

def create_hot_light_window(network_id, door_id,
                            lit_start="2026-09-01T06:00:00Z",
                            lit_end="2026-09-01T08:00:00Z", **overrides):
    return get_success_data(
        api.create_hot_light_window(
            network_id, door_id,
            create_hot_light_window_payload(
                lit_start=lit_start, lit_end=lit_end, **overrides
            ),
            dm(door_id),
        )
    )


def ignite_window(network_id, door_id, window_id):
    return get_success_data(
        api.ignite_hot_light_window(network_id, door_id, window_id, dm(door_id))
    )


def setup_lit_window(network_code="NH", region="R1", batch_dozens=40, capacity=500,
                     lit_start="2026-09-01T06:00:00Z",
                     lit_end="2026-09-01T08:00:00Z",
                     ignite_at="2026-09-01T07:00:00Z"):
    """THEATER COMPANY door at a hub with one fresh COMPLETED batch; a
    hot-light window scheduled and ignited inside its span.

    Returns a dict with keys: network, hub, line, door, batch, window.
    """
    network, hub, line = setup_hub_with_line(
        network_code=network_code, hub_code="HH", region=region, capacity=capacity,
        line_overrides={"service_interval_hours": 500},
    )
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region=region)
    batch = create_completed_batch(
        network["id"], hub["id"], line["id"],
        planned_dozens=batch_dozens, produced_dozens=batch_dozens,
    )
    window = create_hot_light_window(
        network["id"], door["id"], lit_start=lit_start, lit_end=lit_end
    )
    get_success_data(api.set_clock(ignite_at, NA))
    window = ignite_window(network["id"], door["id"], window["id"])
    return {
        "network": network, "hub": hub, "line": line, "door": door,
        "batch": batch, "window": window,
    }
