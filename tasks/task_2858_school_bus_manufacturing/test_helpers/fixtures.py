"""Composite setup helpers.

Each helper drives the real API through the sequence of calls needed to put the
system into a particular state, and returns the resources it created so tests
can assert against them. Setup calls use the lenient success validator so a
broken preamble reports itself as a setup failure rather than as a confusing
assertion error deep inside a test.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    bid_payload,
    build_slot_payload,
    bus_model_payload,
    ca_profile_payload,
    dealer_payload,
    diesel_package_payload,
    electric_package_payload,
    legacy_fleet_record_payload,
    nv_profile_payload,
    production_line_payload,
    quality_test_payload,
    recall_campaign_payload,
    record_result_payload,
    solicitation_payload,
    spec_profile_payload,
    test_bay_payload,
    tx_profile_payload,
)
from .test_users import (
    TEST_USERS,
    make_dealer_agent_headers,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CONTRACTS = TEST_USERS["contracts_admin_headers"]
CONTRACTS_2 = TEST_USERS["contracts_admin_2_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
PLANT = TEST_USERS["plant_scheduler_headers"]
QUALITY = TEST_USERS["quality_inspector_headers"]


# ==========================================================================
# Tier 0: single-step wrappers
# ==========================================================================
def set_clock(current_utc: str) -> None:
    """Move the logical clock forward to `current_utc`."""
    get_success_data(api_client.set_clock(current_utc, CONTRACTS))


def create_bus_model(payload: Optional[dict] = None, **overrides) -> dict:
    body = payload if payload is not None else bus_model_payload(**overrides)
    return get_success_data(api_client.create_bus_model(body, COMPLIANCE))


def create_propulsion_package(payload: dict) -> dict:
    return get_success_data(api_client.create_propulsion_package(payload, COMPLIANCE))


def create_profile(payload: dict, publish: bool = True) -> dict:
    """Draft a specification profile, publishing it unless asked not to."""
    profile = get_success_data(api_client.create_state_spec_profile(payload, COMPLIANCE))
    if publish:
        profile = get_success_data(
            api_client.publish_state_spec_profile(profile["id"], COMPLIANCE)
        )
    return profile


def publish_profile(profile_id: str) -> dict:
    return get_success_data(
        api_client.publish_state_spec_profile(profile_id, COMPLIANCE)
    )


def create_solicitation(profile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_solicitation(solicitation_payload(profile_id, **overrides), SALES)
    )


def create_bid(solicitation_id: str, bus_model_id: str, propulsion_package_id: str,
               headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_bid(
            bid_payload(solicitation_id, bus_model_id, propulsion_package_id, **overrides),
            headers or SALES,
        )
    )


def submit_bid(bid_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.submit_bid(bid_id, headers or SALES))


def close_solicitation(solicitation_id: str) -> dict:
    return get_success_data(api_client.close_solicitation(solicitation_id, CONTRACTS))


def award_bid(bid_id: str, promised_delivery_date: str,
              headers: Optional[dict] = None) -> dict:
    """Award a bid, returning the newly minted contract order."""
    return get_success_data(
        api_client.award_bid(bid_id, promised_delivery_date, headers or CONTRACTS_2)
    )


def mint_unit(order_id: str, vin: str) -> dict:
    return get_success_data(api_client.mint_bus_unit(order_id, vin, PLANT))


def create_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_production_line(production_line_payload(**overrides), PLANT)
    )


def read_line(line_id: str) -> dict:
    return get_success_data(api_client.get_production_line(line_id, PLANT))


def line_version(line_id: str) -> int:
    return read_line(line_id)["version"]


def plan_slot(line_id: str, bus_unit_id: str, start_date: str, end_date: str,
              expected_version: Optional[int] = None) -> dict:
    """Plan a slot. With no explicit version the line's current one is read
    first, which is what a well-behaved scheduler does."""
    version = expected_version if expected_version is not None else line_version(line_id)
    return get_success_data(
        api_client.create_build_slot(
            build_slot_payload(version, line_id, bus_unit_id, start_date, end_date),
            PLANT,
        )
    )


def commit_slot(slot_id: str) -> dict:
    return get_success_data(api_client.commit_build_slot(slot_id, PLANT))


def release_slot(slot_id: str) -> dict:
    return get_success_data(api_client.release_build_slot(slot_id, PLANT))


def advance_build(unit_id: str, to_status: str) -> dict:
    return get_success_data(api_client.advance_build(unit_id, to_status, PLANT))


def create_bay(**overrides) -> dict:
    return get_success_data(api_client.create_test_bay(test_bay_payload(**overrides), PLANT))


def schedule_test(bus_unit_id: str, test_bay_id: str, test_type: str,
                  window_start: str, window_end: str) -> dict:
    return get_success_data(
        api_client.create_quality_test(
            quality_test_payload(
                bus_unit_id, test_bay_id, test_type, window_start, window_end
            ),
            QUALITY,
        )
    )


def record_result(test_id: str, outcome: str, measured_value: Optional[float] = None,
                  result_notes: Optional[str] = None,
                  headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.record_test_result(
            test_id,
            record_result_payload(outcome, measured_value, result_notes),
            headers or QUALITY,
        )
    )


def create_dealer(**overrides) -> dict:
    return get_success_data(api_client.create_dealer(dealer_payload(**overrides), CONTRACTS))


def create_legacy_unit(dealer_id: str, bus_model_id: str, propulsion_package_id: str,
                       spec_profile_id: str, vin: str, delivered_at: str) -> dict:
    """Record a bus this dealer delivered before the plant system went live."""
    return get_success_data(
        api_client.create_legacy_fleet_record(
            dealer_id,
            legacy_fleet_record_payload(
                bus_model_id, propulsion_package_id, spec_profile_id, vin, delivered_at
            ),
            CONTRACTS,
        )
    )


def create_campaign(affected_bus_model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_recall_campaign(
            recall_campaign_payload(affected_bus_model_id, **overrides), COMPLIANCE
        )
    )


def launch_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.launch_recall_campaign(campaign_id, COMPLIANCE))


def read_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_recall_campaign(campaign_id, COMPLIANCE))


def read_dealer(dealer_id: str) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, CONTRACTS))


def read_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_bus_unit(unit_id, PLANT))


def read_bid(bid_id: str) -> dict:
    return get_success_data(api_client.get_bid(bid_id, SALES))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_contract_order(order_id, CONTRACTS))


def read_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_build_slot(slot_id, PLANT))


def read_test(test_id: str) -> dict:
    return get_success_data(api_client.get_quality_test(test_id, QUALITY))


def read_profile(profile_id: str) -> dict:
    return get_success_data(api_client.get_state_spec_profile(profile_id, COMPLIANCE))


def list_tasks(**params) -> List[dict]:
    """Remedy tasks in creation order, optionally filtered."""
    return get_success_data(api_client.list_remedy_tasks(COMPLIANCE, params or None))


def read_task(task_id: str) -> dict:
    return get_success_data(api_client.get_remedy_task(task_id, COMPLIANCE))


def start_task(task_id: str, dealer_id: str) -> dict:
    return get_success_data(
        api_client.start_remedy_task(task_id, make_dealer_agent_headers(dealer_id))
    )


def complete_task(task_id: str, dealer_id: str) -> dict:
    return get_success_data(
        api_client.complete_remedy_task(task_id, make_dealer_agent_headers(dealer_id))
    )


def cancel_task(task_id: str) -> dict:
    return get_success_data(api_client.cancel_remedy_task(task_id, COMPLIANCE))


# ==========================================================================
# Tier 1: catalogue scenarios
# ==========================================================================
# The configuration a Texas district bid offers by default: the body's own
# seat and exit counts, crossview mirrors and the two mandated lighting items.
TX_BID_CONFIG: Dict[str, object] = {
    "offered_seat_capacity": 71,
    "offered_emergency_exit_count": 5,
    "offered_mirror_config": "CROSSVIEW",
    "offered_lap_shoulder_belts": False,
    "offered_eight_lamp_system": True,
    "offered_crossing_arm": True,
    "offered_rollover_reinforcement": False,
}

# A fully optioned California bid: every mandate met, rollover reinforced.
CA_BID_CONFIG: Dict[str, object] = {
    "offered_seat_capacity": 78,
    "offered_emergency_exit_count": 6,
    "offered_mirror_config": "CROSSVIEW_HEATED",
    "offered_lap_shoulder_belts": True,
    "offered_eight_lamp_system": True,
    "offered_crossing_arm": True,
    "offered_rollover_reinforcement": True,
}


def setup_tx_catalogue(publish: bool = True, **profile_overrides) -> dict:
    """Conventional Type C body, 100 gallon diesel package and a published
    Texas profile. Returns model, package and profile."""
    model = create_bus_model()
    package = create_propulsion_package(diesel_package_payload(model["id"]))
    profile = create_profile(tx_profile_payload(**profile_overrides), publish=publish)
    return {"model": model, "package": package, "profile": profile}


def setup_ca_catalogue(publish: bool = True, **profile_overrides) -> dict:
    """Conventional Type C body, 155 kWh electric package and a published
    California profile with every optional mandate switched on."""
    model = create_bus_model()
    package = create_propulsion_package(electric_package_payload(model["id"]))
    profile = create_profile(ca_profile_payload(**profile_overrides), publish=publish)
    return {"model": model, "package": package, "profile": profile}


def setup_nv_catalogue(propulsion: str = "DIESEL", publish: bool = True,
                       **profile_overrides) -> dict:
    """Nevada profile with the caller's choice of propulsion family."""
    model = create_bus_model()
    if propulsion == "ELECTRIC":
        package = create_propulsion_package(electric_package_payload(model["id"]))
    else:
        package = create_propulsion_package(diesel_package_payload(model["id"]))
    profile = create_profile(nv_profile_payload(**profile_overrides), publish=publish)
    return {"model": model, "package": package, "profile": profile}


def setup_ok_catalogue(publish: bool = True, **profile_overrides) -> dict:
    """A small Type A body on a 40 gallon diesel package against an Oklahoma
    profile that supplies only the six mandatory specification inputs."""
    from .factories import mini_diesel_package_payload, type_a_mini_model_payload

    model = create_bus_model(type_a_mini_model_payload())
    package = create_propulsion_package(mini_diesel_package_payload(model["id"]))
    profile = create_profile(spec_profile_payload(**profile_overrides), publish=publish)
    return {"model": model, "package": package, "profile": profile}


# ==========================================================================
# Tier 2: solicitation, bid and award progression
# ==========================================================================
def setup_submitted_bid(catalogue: Optional[dict] = None, *, unit_count: int = 1,
                        submit_clock: Optional[str] = None,
                        solicitation_overrides: Optional[dict] = None,
                        bid_config: Optional[dict] = None) -> dict:
    """Catalogue, an open solicitation and one submitted bid on it."""
    scenario = dict(catalogue or setup_tx_catalogue())
    sol_overrides = dict(solicitation_overrides or {})
    sol_overrides.setdefault("unit_count", unit_count)
    solicitation = create_solicitation(scenario["profile"]["id"], **sol_overrides)
    config = dict(TX_BID_CONFIG if bid_config is None else bid_config)
    config["unit_count"] = unit_count
    bid = create_bid(
        solicitation["id"], scenario["model"]["id"], scenario["package"]["id"], **config
    )
    if submit_clock:
        set_clock(submit_clock)
    bid = submit_bid(bid["id"])
    scenario.update({"solicitation": solicitation, "bid": bid})
    return scenario


def setup_awarded_order(catalogue: Optional[dict] = None, *, unit_count: int = 1,
                        submit_clock: str = "2026-08-15T00:00:00Z",
                        award_clock: str = "2026-09-01T00:00:00Z",
                        promised_delivery_date: str = "2026-12-01",
                        required_delivery_date: Optional[str] = None,
                        solicitation_overrides: Optional[dict] = None,
                        bid_config: Optional[dict] = None) -> dict:
    """Walk a bid all the way to an awarded contract order.

    The bid is submitted at `submit_clock` and awarded at `award_clock`, which
    is what determines the escalation applied to the awarded unit price.
    """
    sol_overrides = dict(solicitation_overrides or {})
    sol_overrides.setdefault(
        "required_delivery_date", required_delivery_date or promised_delivery_date
    )
    scenario = setup_submitted_bid(
        catalogue,
        unit_count=unit_count,
        submit_clock=submit_clock,
        solicitation_overrides=sol_overrides,
        bid_config=bid_config,
    )
    close_solicitation(scenario["solicitation"]["id"])
    if award_clock:
        set_clock(award_clock)
    order = award_bid(scenario["bid"]["id"], promised_delivery_date)
    scenario["order"] = order
    return scenario


def setup_order_with_units(catalogue: Optional[dict] = None, *, vin_list: List[str],
                           **award_kwargs) -> dict:
    """An awarded order with one minted bus per supplied identification number."""
    award_kwargs.setdefault("unit_count", len(vin_list))
    scenario = setup_awarded_order(catalogue, **award_kwargs)
    scenario["units"] = [mint_unit(scenario["order"]["id"], vin) for vin in vin_list]
    return scenario


# ==========================================================================
# Tier 3: plant progression
# ==========================================================================
def setup_committed_slot(catalogue: Optional[dict] = None, *,
                         vin: str = "1TXDSL0000000001",
                         start_date: str = "2026-09-07",
                         end_date: str = "2026-09-14",
                         line_overrides: Optional[dict] = None,
                         **award_kwargs) -> dict:
    """An awarded order, one minted bus, a line and a committed slot on it."""
    scenario = setup_order_with_units(catalogue, vin_list=[vin], **award_kwargs)
    line = create_line(**(line_overrides or {}))
    unit = scenario["units"][0]
    slot = plan_slot(line["id"], unit["id"], start_date, end_date)
    slot = commit_slot(slot["id"])
    scenario.update({"line": line, "slot": slot, "unit": unit})
    return scenario


def setup_built_unit(catalogue: Optional[dict] = None, *,
                     vin: str = "1TXDSL0000000001",
                     start_date: str = "2026-09-07",
                     end_date: str = "2026-09-14",
                     line_overrides: Optional[dict] = None,
                     **award_kwargs) -> dict:
    """Drive one bus from minting through body joining to a built body."""
    scenario = setup_committed_slot(
        catalogue, vin=vin, start_date=start_date, end_date=end_date,
        line_overrides=line_overrides, **award_kwargs
    )
    advance_build(scenario["unit"]["id"], "BODY_JOINED")
    scenario["unit"] = advance_build(scenario["unit"]["id"], "BUILT")
    return scenario


def pass_always_required_tests(unit_id: str, bay_id: str,
                               windows: Optional[List[str]] = None,
                               headers: Optional[dict] = None) -> List[dict]:
    """Schedule and pass the three tests every bus needs, one per day so their
    closed windows never collide in the bay."""
    days = windows or ["2026-09-15", "2026-09-16", "2026-09-17"]
    passed = []
    for test_type, day in zip(["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"], days):
        test = schedule_test(unit_id, bay_id, test_type, day, day)
        passed.append(record_result(test["id"], "PASS", headers=headers))
    return passed


def setup_unit_ready_to_certify(catalogue: Optional[dict] = None, *,
                                vin: str = "1TXDSL0000000001",
                                bay_overrides: Optional[dict] = None,
                                **built_kwargs) -> dict:
    """A built bus in a bay with all three always-required tests passed."""
    scenario = setup_built_unit(catalogue, vin=vin, **built_kwargs)
    bay = create_bay(**(bay_overrides or {}))
    tests = pass_always_required_tests(scenario["unit"]["id"], bay["id"])
    scenario.update({"bay": bay, "passed_tests": tests})
    return scenario


# ==========================================================================
# Tier 4: delivery network and installed base
# ==========================================================================
def setup_dealer_with_legacy_units(catalogue: Optional[dict] = None, *,
                                   deliveries: Optional[List[tuple]] = None,
                                   dealer_overrides: Optional[dict] = None,
                                   clock: str = "2026-09-01T00:00:00Z") -> dict:
    """A dealer plus one legacy fleet record per (vin, delivered_at) pair.

    Legacy records are the only way to build an installed base a recall
    campaign can reach without walking the whole production lifecycle.
    """
    set_clock(clock)
    scenario = dict(catalogue or setup_tx_catalogue())
    dealer_kwargs = dict(dealer_overrides or {})
    dealer_kwargs.setdefault("licensed_state_codes", [scenario["profile"]["state_code"]])
    dealer = create_dealer(**dealer_kwargs)
    pairs = deliveries or [
        ("1TXDSL0000009101", "2026-05-10T00:00:00Z"),
        ("1TXDSL0000009102", "2026-06-02T00:00:00Z"),
    ]
    units = [
        create_legacy_unit(
            dealer["id"], scenario["model"]["id"], scenario["package"]["id"],
            scenario["profile"]["id"], vin, delivered_at,
        )
        for vin, delivered_at in pairs
    ]
    scenario.update({"dealer": dealer, "legacy_units": units})
    return scenario


def setup_launched_campaign(catalogue: Optional[dict] = None, *,
                            deliveries: Optional[List[tuple]] = None,
                            dealer_overrides: Optional[dict] = None,
                            campaign_overrides: Optional[dict] = None,
                            clock: str = "2026-09-01T00:00:00Z") -> dict:
    """A dealer with an installed base and one launched recall campaign over it."""
    scenario = setup_dealer_with_legacy_units(
        catalogue, deliveries=deliveries, dealer_overrides=dealer_overrides, clock=clock
    )
    campaign = create_campaign(scenario["model"]["id"], **(campaign_overrides or {}))
    scenario["campaign"] = launch_campaign(campaign["id"])
    scenario["tasks"] = list_tasks(recall_campaign_id=campaign["id"])
    return scenario


def setup_delivered_unit(catalogue: Optional[dict] = None, *,
                         vin: str = "1TXDSL0000000001",
                         dealer_overrides: Optional[dict] = None,
                         deliver_clock: str = "2026-09-20T00:00:00Z",
                         **ready_kwargs) -> dict:
    """Take one bus all the way to delivery: built, tested, certified,
    dealer-assigned, driver training complete, delivered."""
    scenario = setup_unit_ready_to_certify(catalogue, vin=vin, **ready_kwargs)
    unit_id = scenario["unit"]["id"]
    get_success_data(api_client.certify_bus_unit(unit_id, COMPLIANCE))
    dealer_kwargs = dict(dealer_overrides or {})
    dealer_kwargs.setdefault("licensed_state_codes", [scenario["profile"]["state_code"]])
    dealer = create_dealer(**dealer_kwargs)
    get_success_data(api_client.assign_dealer(unit_id, dealer["id"], CONTRACTS))
    get_success_data(
        api_client.complete_driver_training(unit_id, make_dealer_agent_headers(dealer["id"]))
    )
    if deliver_clock:
        set_clock(deliver_clock)
    scenario["dealer"] = dealer
    scenario["unit"] = get_success_data(api_client.deliver_bus_unit(unit_id, CONTRACTS))
    return scenario
