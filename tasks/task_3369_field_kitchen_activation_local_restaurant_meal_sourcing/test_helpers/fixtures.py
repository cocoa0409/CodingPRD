"""Composite setup helpers — multi-step API sequences behind one call.

Every helper builds its preconditions from scratch through PRD-declared
endpoints and returns the created rows, so tests assert behaviour instead
of plumbing.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .factories import (
    create_assessment_payload,
    create_distribution_run_payload,
    create_distribution_site_payload,
    create_distribution_stop_payload,
    create_donor_commitment_payload,
    create_field_kitchen_payload,
    create_incident_payload,
    create_ingredient_purchase_payload,
    create_meal_order_payload,
    create_partner_kitchen_payload,
    create_supplier_payload,
    inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_kitchen_operator_headers,
    make_site_coordinator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["field_coordinator_headers"]
SAFETY = TEST_USERS["food_safety_officer_headers"]
PARTNER = TEST_USERS["partnership_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SOURCING = TEST_USERS["sourcing_officer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
DONOR = TEST_USERS["donor_liaison_headers"]


# --- Tier 0: clock and primitive creates ------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. The clock starts at the default instant."""
    return get_success_data(api.set_current_utc(to_iso8601, ADMIN))


def create_incident(**overrides) -> dict:
    return get_success_data(
        api.create_incident(create_incident_payload(**overrides), ADMIN)
    )


def create_assessment(incident_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_assessment(
            create_assessment_payload(incident_id, **overrides), COORD
        )
    )


def activate_incident(incident_id: str, headers=None) -> dict:
    return get_success_data(
        api.transition_incident(incident_id, {"to_state": "ACTIVE"}, headers or COORD)
    )


def transition_incident(incident_id: str, to_state: str, headers=None) -> dict:
    return get_success_data(
        api.transition_incident(incident_id, {"to_state": to_state}, headers or ADMIN)
    )


def create_field_kitchen(incident_id: str, assessment_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_field_kitchen(
            create_field_kitchen_payload(incident_id, assessment_id, **overrides), COORD
        )
    )


def transition_field_kitchen(field_kitchen_id: str, to_state: str, headers=None) -> dict:
    return get_success_data(
        api.transition_field_kitchen(
            field_kitchen_id, {"to_state": to_state}, headers or COORD
        )
    )


def inspect_field_kitchen(field_kitchen_id: str, **overrides) -> dict:
    return get_success_data(
        api.inspect_field_kitchen(field_kitchen_id, inspection_payload(**overrides), SAFETY)
    )


def create_partner_kitchen(incident_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_partner_kitchen(create_partner_kitchen_payload(incident_id, **overrides), PARTNER)
    )


def transition_partner_kitchen(partner_kitchen_id: str, dimension: str, to_state: str,
                               headers=None, **extra) -> dict:
    payload = {"dimension": dimension, "to_state": to_state}
    payload.update(extra)
    return get_success_data(
        api.transition_partner_kitchen(partner_kitchen_id, payload, headers or PARTNER)
    )


def create_meal_order(incident_id: str, partner_kitchen_id: str, headers=None,
                      **overrides) -> dict:
    """Fetch the kitchen's current version, then place the batch."""
    kitchen = get_success_data(api.get_partner_kitchen(partner_kitchen_id, PLANNER))
    payload = create_meal_order_payload(
        incident_id, partner_kitchen_id, kitchen["version"], **overrides
    )
    return get_success_data(api.create_meal_order(payload, headers or PLANNER))


def transition_meal_order(meal_order_id: str, to_state: str, headers=None, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(
        api.transition_meal_order(meal_order_id, payload, headers or PLANNER)
    )


def create_supplier(incident_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_supplier(create_supplier_payload(incident_id, **overrides), SOURCING)
    )


def create_ingredient_purchase(incident_id: str, supplier_id: str,
                               partner_kitchen_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_ingredient_purchase(
            create_ingredient_purchase_payload(
                incident_id, supplier_id, partner_kitchen_id, **overrides
            ),
            SOURCING,
        )
    )


def transition_ingredient_purchase(purchase_id: str, to_state: str, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(
        api.transition_ingredient_purchase(purchase_id, payload, SOURCING)
    )


def confirm_and_deliver_purchase(purchase_id: str) -> dict:
    """REQUESTED -> CONFIRMED -> DELIVERED for one sourcing order."""
    transition_ingredient_purchase(purchase_id, "CONFIRMED")
    return transition_ingredient_purchase(purchase_id, "DELIVERED")


def setup_supplier_with_delivered_purchase(incident_id: str, partner_kitchen_id: str,
                                           **overrides) -> tuple:
    """A producer whose first order has already been delivered into a kitchen.

    Returns (supplier, purchase).
    """
    supplier = create_supplier(incident_id, **overrides)
    purchase = create_ingredient_purchase(
        incident_id, supplier["id"], partner_kitchen_id
    )
    purchase = confirm_and_deliver_purchase(purchase["id"])
    return supplier, purchase


def create_distribution_site(incident_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_distribution_site(
            create_distribution_site_payload(incident_id, **overrides), LOGISTICS
        )
    )


def create_distribution_run(incident_id: str, field_kitchen_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_distribution_run(
            create_distribution_run_payload(incident_id, field_kitchen_id, **overrides),
            LOGISTICS,
        )
    )


def transition_distribution_run(run_id: str, to_state: str, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(api.transition_distribution_run(run_id, payload, LOGISTICS))


def add_stop(run_id: str, site_id: str, stop_sequence: int, planned_meals: int,
             **overrides) -> dict:
    """Read the run's current version, then add the stop."""
    run = get_success_data(api.get_distribution_run(run_id, LOGISTICS))
    payload = create_distribution_stop_payload(
        run_id, site_id, stop_sequence, planned_meals, run["version"], **overrides
    )
    return get_success_data(api.create_distribution_stop(payload, LOGISTICS))


def transition_stop(stop_id: str, to_state: str, site_id=None, **extra) -> dict:
    """Record a stop outcome. SiteCoordinator calls are ownership-gated, so the
    site's own id is threaded through when it is supplied."""
    headers = make_site_coordinator_headers(site_id) if site_id else LOGISTICS
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(api.transition_distribution_stop(stop_id, payload, headers))


def create_donor_commitment(incident_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_donor_commitment(
            create_donor_commitment_payload(incident_id, **overrides), DONOR
        )
    )


def transition_donor_commitment(commitment_id: str, to_state: str, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(
        api.transition_donor_commitment(commitment_id, payload, DONOR)
    )


# --- Tier 1: state progression ----------------------------------------------

def setup_active_incident(**overrides) -> tuple:
    """Incident + one SUBMITTED assessment + the transition into ACTIVE."""
    incident = create_incident(**overrides)
    assessment = create_assessment(incident["id"])
    activate_incident(incident["id"])
    return incident, assessment


def setup_operational_field_kitchen(incident_id: str = None, assessment_id: str = None,
                                    **overrides) -> tuple:
    """Incident (ACTIVE) + assessment + field kitchen walked to OPERATIONAL.

    Returns (incident, assessment, field_kitchen). Pass an existing incident
    and assessment to reuse them instead of creating a fresh pair.
    """
    if incident_id is None or assessment_id is None:
        incident, assessment = setup_active_incident()
        incident_id, assessment_id = incident["id"], assessment["id"]
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
        assessment = None
    kitchen = create_field_kitchen(incident_id, assessment_id, **overrides)
    transition_field_kitchen(kitchen["id"], "UTILITIES_PENDING")
    transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)
    kitchen = transition_field_kitchen(kitchen["id"], "OPERATIONAL")
    return incident, assessment, kitchen


def setup_operational_field_kitchen_for(incident_id: str, **overrides) -> dict:
    """Siting an additional OPERATIONAL field kitchen inside an existing activation."""
    assessment = create_assessment(incident_id)
    kitchen = create_field_kitchen(incident_id, assessment["id"], **overrides)
    transition_field_kitchen(kitchen["id"], "UTILITIES_PENDING")
    transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)
    return transition_field_kitchen(kitchen["id"], "OPERATIONAL")


def setup_contracted_partner_kitchen(incident_id: str = None, **overrides) -> tuple:
    """Incident (ACTIVE) + a restaurant walked to CONTRACTED.

    Returns (incident, partner_kitchen).
    """
    if incident_id is None:
        incident, _ = setup_active_incident()
        incident_id = incident["id"]
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
    kitchen = create_partner_kitchen(incident_id, **overrides)
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "VETTING")
    kitchen = transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    return incident, kitchen


def setup_producing_partner_kitchen(incident_id: str = None, **overrides) -> tuple:
    """CONTRACTED kitchen whose own account has opened a production window."""
    incident, kitchen = setup_contracted_partner_kitchen(incident_id, **overrides)
    kitchen = transition_partner_kitchen(
        kitchen["id"], "PRODUCTION", "PRODUCING",
        headers=make_kitchen_operator_headers(kitchen["id"]),
    )
    return incident, kitchen


# --- Tier 2: batch lifecycle shortcuts --------------------------------------

def setup_placed_meal_order(incident_id: str = None, partner_kitchen_id: str = None,
                            producing: bool = True, **overrides) -> tuple:
    """Incident (ACTIVE) + a CONTRACTED (optionally PRODUCING) kitchen + a PLACED batch.

    Returns (incident, partner_kitchen, meal_order).
    """
    if incident_id is None or partner_kitchen_id is None:
        if producing:
            incident, kitchen = setup_producing_partner_kitchen(incident_id)
        else:
            incident, kitchen = setup_contracted_partner_kitchen(incident_id)
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
        kitchen = get_success_data(api.get_partner_kitchen(partner_kitchen_id, PLANNER))
    order = create_meal_order(incident["id"], kitchen["id"], **overrides)
    return incident, kitchen, order


def advance_meal_order_to_quality_hold(meal_order_id: str, partner_kitchen_id: str,
                                       produced_meals: int) -> dict:
    """Walk a batch into QUALITY_HOLD with a produced-meal count.

    A PLACED batch is opened for production first; a batch already back in
    IN_PRODUCTION on the rework cycle (PRD 3.5: QUALITY_HOLD to IN_PRODUCTION
    to QUALITY_HOLD) is only walked through the QUALITY_HOLD leg, since
    re-issuing the move it already made is not a declared transition.
    """
    if get_meal_order_row(meal_order_id)["status"] == "PLACED":
        transition_meal_order(meal_order_id, "IN_PRODUCTION")
    return transition_meal_order(
        meal_order_id, "QUALITY_HOLD", produced_meals=produced_meals,
        headers=make_kitchen_operator_headers(partner_kitchen_id),
    )


def advance_meal_order_to_rejected(meal_order_id: str, partner_kitchen_id: str,
                                   produced_meals: int, quality_check_score: int) -> dict:
    advance_meal_order_to_quality_hold(meal_order_id, partner_kitchen_id, produced_meals)
    return transition_meal_order(
        meal_order_id, "REJECTED", quality_check_score=quality_check_score,
        headers=SAFETY,
    )


def setup_ready_meal_order(incident_id: str = None, partner_kitchen_id: str = None,
                           run_id: str = None, produced_meals: int = 500,
                           quality_check_score: int = 88, rejected_meals: int = None,
                           **overrides) -> tuple:
    """Incident + PRODUCING kitchen + a run in LOADING + a batch in READY.

    Returns (incident, partner_kitchen, run, meal_order).
    """
    if incident_id is None or partner_kitchen_id is None:
        incident, kitchen = setup_producing_partner_kitchen(incident_id)
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
        kitchen = get_success_data(api.get_partner_kitchen(partner_kitchen_id, PLANNER))
    if run_id is None:
        # the run must load from a field kitchen of the batch's own activation
        field_kitchen = setup_operational_field_kitchen_for(incident["id"])
        run = create_distribution_run(incident["id"], field_kitchen["id"])
        run = transition_distribution_run(run["id"], "LOADING")
    else:
        run = get_success_data(api.get_distribution_run(run_id, LOGISTICS))
    order = create_meal_order(incident["id"], kitchen["id"], **overrides)
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], produced_meals)
    ready_payload = {"quality_check_score": quality_check_score}
    if rejected_meals is not None:
        ready_payload["rejected_meals"] = rejected_meals
    order = transition_meal_order(order["id"], "READY", headers=SAFETY, **ready_payload)
    return incident, kitchen, run, order


def setup_delivered_meal_order(incident_id: str = None, partner_kitchen_id: str = None,
                               produced_meals: int = 1000, quality_check_score: int = 88,
                               rejected_meals: int = 40, **overrides) -> tuple:
    """Full batch lifecycle through DELIVERED on a run that reached DELIVERING.

    Returns (incident, partner_kitchen, run, meal_order).
    """
    incident, kitchen, run, order = setup_ready_meal_order(
        incident_id, partner_kitchen_id,
        produced_meals=produced_meals, quality_check_score=quality_check_score,
        rejected_meals=rejected_meals, **overrides,
    )
    transition_meal_order(
        order["id"], "DISPATCHED", headers=LOGISTICS, distribution_run_id=run["id"]
    )
    loaded = get_success_data(api.get_distribution_run(run["id"], LOGISTICS))["loaded_meals"]
    transition_distribution_run(run["id"], "EN_ROUTE", loaded_meals=max(loaded, 1))
    transition_distribution_run(run["id"], "DELIVERING")
    order = transition_meal_order(order["id"], "DELIVERED", headers=LOGISTICS)
    return incident, kitchen, run, order


# --- Tier 3: delivery runs, stops and terminal states -----------------------

def setup_planned_run_with_sites(site_count: int = 2, incident_id: str = None,
                                 **run_overrides) -> tuple:
    """ACTIVE incident + OPERATIONAL kitchen + N OPEN sites + a PLANNED run.

    Returns (incident, field_kitchen, run, sites).
    """
    if incident_id is None:
        incident, _, field_kitchen = setup_operational_field_kitchen()
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
        field_kitchen = setup_operational_field_kitchen_for(incident_id)
    sites = [
        create_distribution_site(incident["id"], site_name=f"Site {index + 1}")
        for index in range(site_count)
    ]
    run = create_distribution_run(incident["id"], field_kitchen["id"], **run_overrides)
    return incident, field_kitchen, run, sites


def setup_delivering_run(stop_plans, loaded_meals: int, incident_id: str = None,
                         **run_overrides) -> tuple:
    """A run walked to DELIVERING with one PENDING stop per entry in stop_plans.

    `stop_plans` is a list of (planned_meals, site_overrides) tuples; the run is
    loaded with `loaded_meals` and every stop starts PENDING.

    Returns (incident, field_kitchen, run, sites, stops).
    """
    incident, field_kitchen, run, sites = setup_planned_run_with_sites(
        len(stop_plans), incident_id, **run_overrides
    )
    # the load figure is written before any stop is promised against it
    transition_distribution_run(run["id"], "LOADING", loaded_meals=loaded_meals)
    stops = []
    for index, plan in enumerate(stop_plans):
        planned_meals, site_overrides = plan
        if site_overrides:
            sites[index] = create_distribution_site(incident["id"], **site_overrides)
        stops.append(add_stop(run["id"], sites[index]["id"], index + 1, planned_meals))
    transition_distribution_run(run["id"], "EN_ROUTE", loaded_meals=loaded_meals)
    run = transition_distribution_run(run["id"], "DELIVERING")
    return incident, field_kitchen, run, sites, stops


def deliver_stop(stop_id: str, site_id: str, delivered_meals: int) -> dict:
    """Confirm handover at the stop's own site (ownership-gated call)."""
    return transition_stop(
        stop_id, "DELIVERED", site_id=site_id, delivered_meals=delivered_meals
    )


def setup_loaded_run_with_stops(stop_plans, loaded_meals: int, incident_id: str = None,
                                **run_overrides) -> tuple:
    """A LOADING run carrying `loaded_meals` with one PENDING stop per plan.

    The load figure is written before the stops are promised, so the pending
    planned meals never exceed what the vehicle is carrying.

    Returns (incident, field_kitchen, run, sites, stops).
    """
    incident, field_kitchen, run, sites = setup_planned_run_with_sites(
        len(stop_plans), incident_id, **run_overrides
    )
    transition_distribution_run(run["id"], "LOADING", loaded_meals=loaded_meals)
    stops = []
    for index, plan in enumerate(stop_plans):
        planned_meals, site_overrides = plan
        if site_overrides:
            sites[index] = create_distribution_site(incident["id"], **site_overrides)
        stops.append(add_stop(run["id"], sites[index]["id"], index + 1, planned_meals))
    run = get_success_data(api.get_distribution_run(run["id"], LOGISTICS))
    return incident, field_kitchen, run, sites, stops


def setup_completed_run(deliveries, incident_id: str = None) -> tuple:
    """A run completed with `deliveries` meals handed over at each stop.

    `deliveries` is a list of (planned_meals, delivered_meals) pairs.
    Returns (incident, field_kitchen, run, sites, stops).
    """
    stop_plans = [(planned, None) for planned, _ in deliveries]
    total_planned = sum(planned for planned, _ in deliveries)
    incident, field_kitchen, run, sites, stops = setup_delivering_run(
        stop_plans, max(total_planned, 1), incident_id
    )
    for stop, site, (_, delivered) in zip(stops, sites, deliveries):
        if delivered:
            deliver_stop(stop["id"], site["id"], delivered)
        else:
            transition_stop(stop["id"], "FAILED", failure_reason="ROAD_BLOCKED")
    run = transition_distribution_run(run["id"], "COMPLETED")
    return incident, field_kitchen, run, sites, stops


def setup_winding_down_incident(incident_id: str = None, **overrides) -> tuple:
    """An activation moved into WINDING_DOWN (demobilizing SITED kitchens)."""
    if incident_id is None:
        incident, assessment = setup_active_incident(**overrides)
        incident_id = incident["id"]
    else:
        assessment = None
    incident = transition_incident(incident_id, "WINDING_DOWN", ADMIN)
    return incident, assessment


def setup_closed_incident(**overrides) -> tuple:
    """An activation driven all the way to CLOSED.

    Returns (incident, field_kitchen, run).
    """
    incident, _, field_kitchen = setup_operational_field_kitchen(**overrides)
    run = create_distribution_run(incident["id"], field_kitchen["id"])
    transition_distribution_run(run["id"], "ABORTED", abort_reason="STAND_DOWN")
    transition_incident(incident["id"], "WINDING_DOWN", ADMIN)
    transition_field_kitchen(field_kitchen["id"], "DEMOBILIZED")
    incident = transition_incident(incident["id"], "CLOSED", ADMIN)
    return incident, field_kitchen, run


def setup_runs_on_day(incident_id: str, field_kitchen_id: str, count: int,
                      day: str = "2026-09-01", first_hour: int = 6) -> list:
    """Create `count` runs on one UTC calendar day with disjoint windows."""
    runs = []
    for index in range(count):
        start_hour = first_hour + index * 4
        runs.append(
            create_distribution_run(
                incident_id,
                field_kitchen_id,
                planned_date=f"{day}T{start_hour:02d}:00:00Z",
                window_start=f"{day}T{start_hour:02d}:00:00Z",
                window_end=f"{day}T{start_hour + 3:02d}:00:00Z",
            )
        )
    return runs


def setup_two_partner_kitchens(incident_id: str = None, **overrides) -> tuple:
    """One ACTIVE incident with two CONTRACTED restaurants.

    Returns (incident, kitchen_a, kitchen_b).
    """
    if incident_id is None:
        incident, _ = setup_active_incident()
        incident_id = incident["id"]
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
    first = create_partner_kitchen(incident_id, **overrides)
    transition_partner_kitchen(first["id"], "CONTRACT", "VETTING")
    first = transition_partner_kitchen(
        first["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    second = create_partner_kitchen(
        incident_id, business_name="El Comal", owner_name="Luis Pena",
        daily_capacity_meals=800, per_meal_price_cents=1400,
    )
    transition_partner_kitchen(second["id"], "CONTRACT", "VETTING")
    second = transition_partner_kitchen(
        second["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    return incident, first, second


def setup_allocated_commitment(incident_id: str = None, amount_cents: int = 1_000_000,
                               **overrides) -> tuple:
    """ACTIVE incident + a commitment walked to ALLOCATED.

    Returns (incident, commitment).
    """
    if incident_id is None:
        incident, _ = setup_active_incident()
        incident_id = incident["id"]
    else:
        incident = get_success_data(api.get_incident(incident_id, ADMIN))
    commitment = create_donor_commitment(incident_id, amount_cents=amount_cents, **overrides)
    transition_donor_commitment(commitment["id"], "RECEIVED")
    commitment = transition_donor_commitment(commitment["id"], "ALLOCATED")
    return incident, commitment


def get_kitchen(partner_kitchen_id: str) -> dict:
    return get_success_data(api.get_partner_kitchen(partner_kitchen_id, PLANNER))


def get_kitchen_version(partner_kitchen_id: str) -> int:
    """The value a client echoes back as expected_partner_kitchen_version."""
    return get_kitchen(partner_kitchen_id)["version"]


def get_run(run_id: str) -> dict:
    return get_success_data(api.get_distribution_run(run_id, LOGISTICS))


def get_stop(stop_id: str) -> dict:
    return get_success_data(api.get_distribution_stop(stop_id, LOGISTICS))


def get_incident_row(incident_id: str) -> dict:
    return get_success_data(api.get_incident(incident_id, ADMIN))


def get_field_kitchen_row(field_kitchen_id: str) -> dict:
    return get_success_data(api.get_field_kitchen(field_kitchen_id, COORD))


def get_meal_order_row(meal_order_id: str) -> dict:
    return get_success_data(api.get_meal_order(meal_order_id, PLANNER))


def get_purchase_row(purchase_id: str) -> dict:
    return get_success_data(api.get_ingredient_purchase(purchase_id, SOURCING))


def get_supplier_row(incident_id: str, supplier_id: str) -> dict:
    """The supplier list is the only read path for a producer's derived standing."""
    response = api.list_incident_suppliers(incident_id, SOURCING, {"limit": 100})
    rows, _ = validate_paginated(response)
    for row in rows:
        if row["id"] == supplier_id:
            return row
    raise AssertionError(f"supplier {supplier_id} not present in the activation")


def pending_planned_meals(run_id: str) -> int:
    """Sum of planned_meals over the run's stops that are still PENDING."""
    stops, _ = get_paginated_stops(run_id)
    return sum(stop["planned_meals"] for stop in stops if stop["status"] == "PENDING")


def get_paginated_stops(run_id: str) -> tuple:
    response = api.list_distribution_stops(
        LOGISTICS, {"distribution_run_id": run_id, "limit": 100}
    )
    return validate_paginated(response)


def get_accountability(incident_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_accountability_report(incident_id, headers or DONOR)
    )
