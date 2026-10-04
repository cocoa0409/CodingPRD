"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch through PRD-declared
endpoints — the harness restarts the server before every test, so nothing is
carried over. All setup calls use get_success_data() so a setup failure surfaces
as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    create_plant_payload, create_customer_payload, create_agreement_payload,
    publish_index_payload, create_line_payload, create_format_payload,
    create_run_payload, complete_run_payload, create_forecast_payload,
    create_scrap_return_payload, credit_scrap_payload, create_incident_payload,
)
from .test_users import (
    TEST_USERS, make_customer_planner_headers, admin, manager, scheduler,
    engineer,
)


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = DEFAULT_CLOCK_UTC) -> dict:
    """Pin the logical clock (PRD §2.4). Default is the startup instant."""
    return get_success_data(api_client.set_clock(current_utc, admin()))


def create_plant(**overrides) -> dict:
    return get_success_data(
        api_client.create_plant(create_plant_payload(**overrides), admin()),
        expected_status=201)


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), admin()),
        expected_status=201)


def publish_index(period: str, index_cents_per_lb: float) -> dict:
    return get_success_data(
        api_client.publish_index(publish_index_payload(period, index_cents_per_lb),
                                 admin()),
        expected_status=201)


def create_line(plant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_line(plant_id, create_line_payload(**overrides),
                               manager()),
        expected_status=201)


def create_format(plant_id: str, customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_format(plant_id, create_format_payload(customer_id,
                                                                 **overrides),
                                 manager()),
        expected_status=201)


def create_qualified_format(plant_id: str, customer_id: str, **overrides) -> dict:
    """PROPOSED -> TOOLED -> QUALIFIED (PRD §3.3)."""
    fmt = create_format(plant_id, customer_id, **overrides)
    get_success_data(api_client.tool_format(fmt["id"], manager()))
    return get_success_data(api_client.qualify_format(fmt["id"], manager()))


# ---------------------------------------------------------------------------
# Tier 1: agreement lifecycle
# ---------------------------------------------------------------------------

def create_agreement(plant_id: str, customer_id: str, **overrides) -> dict:
    """Create a DRAFT agreement."""
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(plant_id, customer_id, **overrides),
            manager()),
        expected_status=201)


def sign_agreement(agreement: dict) -> dict:
    """DRAFT -> ACTIVE, signed by the owning customer (PRD §2.1, §3.2)."""
    return get_success_data(api_client.sign_agreement(
        agreement["id"], make_customer_planner_headers(agreement["customer_id"])))


def create_active_agreement(plant_id: str, customer_id: str, **overrides) -> dict:
    """Create + sign. Returns the ACTIVE agreement."""
    return sign_agreement(create_agreement(plant_id, customer_id, **overrides))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, manager()))


def get_agreement_version(agreement_id: str) -> int:
    return get_agreement(agreement_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: production runs
# ---------------------------------------------------------------------------

def create_run(agreement_id: str, line_id: str, format_id: str,
               expected_version=None, **overrides) -> dict:
    """Schedule a run; re-reads the agreement version unless one is supplied
    (PRD §2.9 OCC token, §3.4)."""
    version = expected_version if expected_version is not None \
        else get_agreement_version(agreement_id)
    return get_success_data(
        api_client.create_run(
            agreement_id,
            create_run_payload(line_id, format_id, version, **overrides),
            scheduler()),
        expected_status=201)


def start_run(run_id: str) -> dict:
    return get_success_data(api_client.start_run(run_id, scheduler()))


def complete_run(run_id: str, produced_qty: int, spoiled_qty: int = 0) -> dict:
    return get_success_data(api_client.complete_run(
        run_id, complete_run_payload(produced_qty=produced_qty,
                                     spoiled_qty=spoiled_qty),
        scheduler()))


def settle_run(run_id: str) -> dict:
    return get_success_data(api_client.settle_run(run_id, manager()))


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_run(run_id, manager()))


def get_plant(plant_id: str) -> dict:
    return get_success_data(api_client.get_plant(plant_id, manager()))


# ---------------------------------------------------------------------------
# Tier 3: composite scenarios
# ---------------------------------------------------------------------------

def setup_network(region="US-SW", customer_region=None, capacity=1_000_000,
                  clock: str = DEFAULT_CLOCK_UTC, **agreement_overrides):
    """Clock pinned, one plant, one customer. Returns (plant, customer)."""
    set_clock(clock)
    plant = create_plant(region=region, warehouse_capacity_units=capacity)
    customer = create_customer(home_region=customer_region or region)
    return plant, customer


def setup_active_network(clock: str = DEFAULT_CLOCK_UTC, capacity=1_000_000,
                         **agreement_overrides):
    """Plant + customer + ACTIVE agreement. Returns (plant, customer, agreement)."""
    plant, customer = setup_network(capacity=capacity, clock=clock)
    agreement = create_active_agreement(plant["id"], customer["id"],
                                        **agreement_overrides)
    return plant, customer, agreement


def setup_run_env(clock: str = DEFAULT_CLOCK_UTC, capacity=1_000_000,
                  format_overrides: dict = None, **agreement_overrides):
    """ACTIVE agreement + one line + one QUALIFIED format.

    Returns dict with plant, customer, agreement, line, format.
    """
    plant, customer, agreement = setup_active_network(
        clock=clock, capacity=capacity, **agreement_overrides)
    line = create_line(plant["id"])
    fmt = create_qualified_format(plant["id"], customer["id"],
                                  **(format_overrides or {}))
    return {"plant": plant, "customer": customer, "agreement": agreement,
            "line": line, "format": fmt}


def setup_scheduled_run(clock: str = DEFAULT_CLOCK_UTC, capacity=1_000_000,
                        format_overrides: dict = None, run_overrides: dict = None,
                        **agreement_overrides):
    """Run environment plus one SCHEDULED run. Returns env dict + run key."""
    env = setup_run_env(clock=clock, capacity=capacity,
                        format_overrides=format_overrides, **agreement_overrides)
    run = create_run(env["agreement"]["id"], env["line"]["id"],
                     env["format"]["id"], **(run_overrides or {}))
    env["run"] = run
    return env


def setup_in_progress_run(clock: str = DEFAULT_CLOCK_UTC, capacity=1_000_000,
                          format_overrides: dict = None, run_overrides: dict = None,
                          **agreement_overrides):
    """One run walked to IN_PROGRESS."""
    env = setup_scheduled_run(clock=clock, capacity=capacity,
                              format_overrides=format_overrides,
                              run_overrides=run_overrides, **agreement_overrides)
    env["run"] = start_run(env["run"]["id"])
    return env


def setup_completed_run(produced_qty: int, spoiled_qty: int = 0,
                        clock: str = DEFAULT_CLOCK_UTC, capacity=1_000_000,
                        format_overrides: dict = None, run_overrides: dict = None,
                        **agreement_overrides):
    """One run walked to COMPLETED (prior-month index must already exist)."""
    env = setup_in_progress_run(clock=clock, capacity=capacity,
                                format_overrides=format_overrides,
                                run_overrides=run_overrides, **agreement_overrides)
    env["run"] = complete_run(env["run"]["id"], produced_qty, spoiled_qty)
    return env


# ---------------------------------------------------------------------------
# Tier 4: forecasts / scrap / incidents
# ---------------------------------------------------------------------------

def create_forecast(agreement: dict, period: str, forecast_qty: int) -> dict:
    return get_success_data(
        api_client.create_forecast(agreement["id"],
                                   create_forecast_payload(period, forecast_qty),
                                   make_customer_planner_headers(
                                       agreement["customer_id"])),
        expected_status=201)


def close_forecast(agreement: dict, forecast_id: str, actual_qty: int) -> dict:
    return get_success_data(api_client.close_forecast(
        forecast_id, {"actual_qty": actual_qty},
        make_customer_planner_headers(agreement["customer_id"])))


def create_scrap_return(customer_id: str, plant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_scrap_return(
            customer_id, create_scrap_return_payload(plant_id, **overrides),
            make_customer_planner_headers(customer_id)),
        expected_status=201)


def credit_scrap_return(scrap_id: str, actual_weight_lbs, grade="UBC") -> dict:
    return get_success_data(api_client.credit_scrap_return(
        scrap_id, credit_scrap_payload(actual_weight_lbs, grade), manager()))


def create_incident(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(run_id, create_incident_payload(**overrides),
                                   engineer()),
        expected_status=201)
