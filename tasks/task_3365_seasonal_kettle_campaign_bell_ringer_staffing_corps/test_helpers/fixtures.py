"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the runner restarts the server before every test, so each
test starts against an empty database.

Setup calls use `get_success_data()` so a broken precondition reports a
clear "Setup failed" instead of a confusing assertion error deep in a test.
"""
from dataclasses import dataclass, field
from typing import Optional, List

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    CAMPAIGN_STARTS_ON,
    CAMPAIGN_ENDS_ON,
    PLACEMENT_STARTS_ON,
    PLACEMENT_ENDS_ON,
    INTAKE_OPENS_ON,
    INTAKE_CLOSES_ON,
    DEFAULT_DAILY_REQUIRED_MINUTES,
    DEFAULT_CAMPAIGN_GOAL_CENTS,
    DEFAULT_LABOR_BUDGET_CENTS,
)
from .factories import (
    create_unit_payload,
    create_campaign_payload,
    create_host_site_payload,
    create_kettle_location_payload,
    create_bell_ringer_payload,
    create_shift_payload,
    create_collection_payload,
    create_digital_giving_payload,
    create_assistance_program_payload,
    create_assistance_application_payload,
    create_corps_program_payload,
    create_deployment_payload,
    create_reallocation_payload,
)
from .test_users import TEST_USERS, make_bell_ringer_headers


@dataclass
class KettleNetwork:
    """An ACTIVE campaign with an APPROVED host site and an ACTIVE kettle location."""
    unit: dict
    campaign: dict
    host_site: dict
    location: dict
    ringer: Optional[dict] = None


# --- logical clock -------------------------------------------------------
def set_clock(iso8601: str) -> dict:
    """PRD §2.11: only PlatformAdmin may move the logical clock."""
    resp = api_client.set_clock(iso8601, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def ensure_clock(iso8601: str = DEFAULT_CLOCK) -> dict:
    return set_clock(iso8601)


# --- units ---------------------------------------------------------------
def create_unit(**overrides) -> dict:
    resp = api_client.create_unit(create_unit_payload(**overrides),
                                  TEST_USERS["platform_admin_headers"])
    return get_success_data(resp, expected_status=201)


def get_unit(unit_id: str) -> dict:
    resp = api_client.get_unit(unit_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


# --- campaigns -----------------------------------------------------------
def create_campaign(**overrides) -> dict:
    resp = api_client.create_campaign(create_campaign_payload(**overrides),
                                      TEST_USERS["platform_admin_headers"])
    return get_success_data(resp, expected_status=201)


def get_campaign(campaign_id: str) -> dict:
    resp = api_client.get_campaign(campaign_id, TEST_USERS["territorial_commander_headers"])
    return get_success_data(resp)


def activate_campaign(campaign_id: str) -> dict:
    """PRD §3.2: activation requires an APPROVED host site and a future ends_on."""
    current = get_campaign(campaign_id)
    resp = api_client.activate_campaign(
        campaign_id,
        {"expected_campaign_version": current["version"]},
        TEST_USERS["territorial_commander_headers"],
    )
    return get_success_data(resp)


def get_campaign_summary(campaign_id: str) -> dict:
    resp = api_client.get_campaign_summary(campaign_id, TEST_USERS["finance_officer_headers"])
    return get_success_data(resp)


# --- host sites ----------------------------------------------------------
def create_host_site(campaign_id: str, **overrides) -> dict:
    resp = api_client.create_host_site(create_host_site_payload(campaign_id, **overrides),
                                       TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp, expected_status=201)


def get_host_site(host_site_id: str) -> dict:
    resp = api_client.get_host_site(host_site_id, TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp)


def decide_host_site(host_site_id: str, decision: str = "APPROVE",
                     expected_version: Optional[int] = None):
    """Raw decision call; pass expected_version=None to use the current version."""
    if expected_version is None:
        expected_version = get_host_site(host_site_id)["version"]
    payload = {"decision": decision, "expected_host_site_version": expected_version}
    return api_client.decide_host_site(host_site_id, payload,
                                       TEST_USERS["kettle_coordinator_headers"])


def approve_host_site(host_site_id: str, expected_version: Optional[int] = None) -> dict:
    return get_success_data(decide_host_site(host_site_id, "APPROVE", expected_version))


def approve_host_site_raw(host_site_id: str, decision: str = "APPROVE",
                          expected_version: Optional[int] = None):
    return decide_host_site(host_site_id, decision, expected_version)


# --- kettle locations ----------------------------------------------------
def create_kettle_location(host_site_id: str, campaign_id: str, **overrides) -> dict:
    resp = api_client.create_kettle_location(
        create_kettle_location_payload(host_site_id, campaign_id, **overrides),
        TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp, expected_status=201)


def get_kettle_location(location_id: str) -> dict:
    resp = api_client.get_kettle_location(location_id,
                                          TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp)


def activate_kettle_location(location_id: str, expected_version: Optional[int] = None):
    """Raw activation call so tests can assert the rejection error."""
    if expected_version is None:
        expected_version = get_kettle_location(location_id)["version"]
    return api_client.activate_kettle_location(
        location_id, {"expected_kettle_location_version": expected_version},
        TEST_USERS["kettle_coordinator_headers"])


def activate_kettle_location_ok(location_id: str) -> dict:
    return get_success_data(activate_kettle_location(location_id))


def close_kettle_location(location_id: str) -> dict:
    resp = api_client.close_kettle_location(location_id,
                                            TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp)


def suspend_kettle_location(location_id: str) -> dict:
    resp = api_client.suspend_kettle_location(location_id,
                                              TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp)


def get_location_performance(location_id: str, on_date: Optional[str] = None) -> dict:
    params = {"on_date": on_date} if on_date else None
    resp = api_client.get_location_performance(
        location_id, TEST_USERS["kettle_coordinator_headers"], params=params)
    return get_success_data(resp)


def list_kettle_locations(**params) -> tuple:
    resp = api_client.list_kettle_locations(TEST_USERS["kettle_coordinator_headers"],
                                            params=params or None)
    return get_success_data(resp), resp


# --- bell ringers --------------------------------------------------------
def create_ringer(unit_id: str, **overrides) -> dict:
    resp = api_client.create_bell_ringer(create_bell_ringer_payload(unit_id, **overrides),
                                         TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp, expected_status=201)


def get_ringer(ringer_id: str) -> dict:
    resp = api_client.get_bell_ringer(ringer_id,
                                      TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def request_screening(ringer_id: str, vendor: str = "SafeGuard Screening",
                      package_level: str = "STANDARD") -> dict:
    resp = api_client.request_screening(
        ringer_id, {"vendor": vendor, "package_level": package_level},
        TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def complete_screening(ringer_id: str, result: str = "CLEAR",
                       completed_at: str = "2026-11-10T00:00:00Z") -> dict:
    resp = api_client.complete_screening(
        ringer_id, {"result": result, "completed_at": completed_at},
        TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def create_cleared_ringer(unit_id: str, completed_at: str = "2026-11-10T00:00:00Z",
                          **overrides) -> dict:
    """Register a ringer, submit a screening request and record a CLEAR result."""
    ringer = create_ringer(unit_id, **overrides)
    request_screening(ringer["id"])
    return complete_screening(ringer["id"], "CLEAR", completed_at)


# --- shifts --------------------------------------------------------------
def create_shift(location_id: str, ringer_id: str, starts_at: str, ends_at: str,
                 expected_location_version: Optional[int] = None, **overrides):
    """Raw shift create so tests can assert the rejection error.

    `expected_kettle_location_version` is mandatory (PRD §2.10); when not given
    it is read fresh from the location.
    """
    if expected_location_version is None:
        expected_location_version = get_kettle_location(location_id)["version"]
    payload = create_shift_payload(location_id, ringer_id, starts_at, ends_at,
                                   expected_location_version, **overrides)
    return api_client.create_shift(payload, TEST_USERS["volunteer_coordinator_headers"])


def create_shift_ok(location_id: str, ringer_id: str, starts_at: str, ends_at: str,
                    **overrides) -> dict:
    return get_success_data(
        create_shift(location_id, ringer_id, starts_at, ends_at, **overrides),
        expected_status=201)


def get_shift(shift_id: str) -> dict:
    resp = api_client.get_shift(shift_id, TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def check_in(shift_id: str, ringer_id: str):
    """PRD §3.3: check-in belongs to the ringer — X-User-ID must equal bell_ringer_id."""
    return api_client.check_in_shift(shift_id, make_bell_ringer_headers(ringer_id))


def confirm_shift(shift_id: str) -> dict:
    resp = api_client.confirm_shift(shift_id,
                                    TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def complete_shift(shift_id: str) -> dict:
    resp = api_client.complete_shift(shift_id,
                                     TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def cancel_shift(shift_id: str, reason: str = "weather closure") -> dict:
    resp = api_client.cancel_shift(shift_id, {"reason": reason},
                                   TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def no_show_shift(shift_id: str) -> dict:
    resp = api_client.no_show_shift(shift_id,
                                    TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def rebook_shift(shift_id: str, starts_at: str, ends_at: str) -> dict:
    resp = api_client.rebook_shift(
        shift_id, {"starts_at": starts_at, "ends_at": ends_at},
        TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def work_shift(shift_id: str, ringer_id: str, clock_iso: str) -> dict:
    """Move the clock to the shift start, check in as the ringer and complete."""
    set_clock(clock_iso)
    get_success_data(check_in(shift_id, ringer_id))
    return complete_shift(shift_id)


def count_shifts_for_ringer(ringer_id: str) -> int:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_shifts(TEST_USERS["volunteer_coordinator_headers"],
                                  params={"bell_ringer_id": ringer_id, "limit": 100})
    _, meta = validate_paginated(resp)
    return meta["total_count"]


def count_shifts_for_location(location_id: str) -> int:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_shifts(TEST_USERS["volunteer_coordinator_headers"],
                                  params={"kettle_location_id": location_id, "limit": 100})
    _, meta = validate_paginated(resp)
    return meta["total_count"]


# --- kettle collections --------------------------------------------------
def create_collection(location_id: str, collected_on: str, declared_cents: int,
                      **overrides) -> dict:
    resp = api_client.create_collection(
        create_collection_payload(location_id, collected_on, declared_cents, **overrides),
        TEST_USERS["counting_room_teller_headers"])
    return get_success_data(resp, expected_status=201)


def get_collection(collection_id: str) -> dict:
    resp = api_client.get_collection(collection_id,
                                     TEST_USERS["counting_room_teller_headers"])
    return get_success_data(resp)


def verify_collection(collection_id: str, expected_version: Optional[int] = None):
    """Raw verify call so tests can assert the rejection error."""
    if expected_version is None:
        expected_version = get_collection(collection_id)["version"]
    return api_client.verify_collection(
        collection_id, {"expected_kettle_collection_version": expected_version},
        TEST_USERS["counting_room_teller_headers"])


def verify_collection_ok(collection_id: str) -> dict:
    return get_success_data(verify_collection(collection_id))


def recount_collection(collection_id: str, coin_cents: int, currency_cents: int,
                       check_cents: int) -> dict:
    resp = api_client.recount_collection(
        collection_id,
        {"coin_cents": coin_cents, "currency_cents": currency_cents,
         "check_cents": check_cents},
        TEST_USERS["counting_room_teller_headers"])
    return get_success_data(resp)


def deposit_collection(collection_id: str, deposited_cents: int):
    return api_client.deposit_collection(
        collection_id, {"deposited_cents": deposited_cents},
        TEST_USERS["finance_officer_headers"])


def deposit_collection_ok(collection_id: str, deposited_cents: int) -> dict:
    return get_success_data(deposit_collection(collection_id, deposited_cents))


def reconcile_collection(collection_id: str, matched: bool,
                         bank_confirmed_cents: Optional[int] = None):
    payload = {"matched": matched}
    if bank_confirmed_cents is not None:
        payload["bank_confirmed_cents"] = bank_confirmed_cents
    return api_client.reconcile_collection(collection_id, payload,
                                           TEST_USERS["finance_officer_headers"])


def count_collections_for_location(location_id: str) -> int:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_collections(TEST_USERS["counting_room_teller_headers"],
                                       params={"kettle_location_id": location_id, "limit": 100})
    _, meta = validate_paginated(resp)
    return meta["total_count"]


# --- digital givings -----------------------------------------------------
def create_digital_giving(campaign_id: str, unit_id: str, amount_cents: int,
                          external_ref: str, **overrides) -> dict:
    resp = api_client.create_digital_giving(
        create_digital_giving_payload(campaign_id, unit_id, amount_cents, external_ref,
                                      **overrides),
        TEST_USERS["digital_giving_processor_headers"])
    return get_success_data(resp, expected_status=201)


def create_digital_giving_raw(campaign_id: str, unit_id: str, amount_cents: int,
                              external_ref: str, **overrides):
    return api_client.create_digital_giving(
        create_digital_giving_payload(campaign_id, unit_id, amount_cents, external_ref,
                                      **overrides),
        TEST_USERS["digital_giving_processor_headers"])


def get_digital_giving(giving_id: str) -> dict:
    resp = api_client.get_digital_giving(giving_id,
                                         TEST_USERS["digital_giving_processor_headers"])
    return get_success_data(resp)


def attribute_giving(giving_id: str, location_id: Optional[str] = None):
    payload = {"kettle_location_id": location_id} if location_id else {}
    return api_client.attribute_digital_giving(
        giving_id, payload, TEST_USERS["digital_giving_processor_headers"])


def attribute_giving_ok(giving_id: str, location_id: Optional[str] = None) -> dict:
    return get_success_data(attribute_giving(giving_id, location_id))


def reverse_giving(giving_id: str, reason: str = "donor chargeback"):
    return api_client.reverse_digital_giving(
        giving_id, {"reason": reason}, TEST_USERS["digital_giving_processor_headers"])


def reverse_giving_ok(giving_id: str, reason: str = "donor chargeback") -> dict:
    return get_success_data(reverse_giving(giving_id, reason))


def count_digital_givings_for_campaign(campaign_id: str) -> int:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_digital_givings(
        TEST_USERS["digital_giving_processor_headers"],
        params={"campaign_id": campaign_id, "limit": 100})
    _, meta = validate_paginated(resp)
    return meta["total_count"]


# --- assistance programs and applications --------------------------------
def create_assistance_program(campaign_id: str, **overrides) -> dict:
    resp = api_client.create_assistance_program(
        create_assistance_program_payload(campaign_id, **overrides),
        TEST_USERS["assistance_caseworker_headers"])
    return get_success_data(resp, expected_status=201)


def open_assistance_program(program_id: str) -> dict:
    resp = api_client.open_assistance_program(program_id,
                                              TEST_USERS["assistance_caseworker_headers"])
    return get_success_data(resp)


def create_application(program_id: str, **overrides):
    """Raw intake call so tests can assert the rejection error."""
    return api_client.create_assistance_application(
        create_assistance_application_payload(program_id, **overrides),
        TEST_USERS["assistance_caseworker_headers"])


def create_application_ok(program_id: str, **overrides) -> dict:
    return get_success_data(create_application(program_id, **overrides),
                            expected_status=201)


def get_application(application_id: str) -> dict:
    resp = api_client.get_assistance_application(
        application_id, TEST_USERS["assistance_caseworker_headers"])
    return get_success_data(resp)


def screen_application(application_id: str, verified_income_cents: int) -> dict:
    resp = api_client.screen_assistance_application(
        application_id, {"verified_income_cents": verified_income_cents},
        TEST_USERS["assistance_caseworker_headers"])
    return get_success_data(resp)


# --- corps programs ------------------------------------------------------
def create_corps_program(unit_id: str, **overrides) -> dict:
    resp = api_client.create_corps_program(
        create_corps_program_payload(unit_id, **overrides),
        TEST_USERS["program_director_headers"])
    return get_success_data(resp, expected_status=201)


def enroll_participant(program_id: str, participant_name: str,
                       participant_type: str = "YOUTH") -> dict:
    resp = api_client.enroll_corps_program(
        program_id, {"participant_name": participant_name,
                     "participant_type": participant_type},
        TEST_USERS["program_director_headers"])
    return get_success_data(resp)


def withdraw_participant(program_id: str, participant_name: str) -> dict:
    resp = api_client.withdraw_corps_program(
        program_id, {"participant_name": participant_name},
        TEST_USERS["program_director_headers"])
    return get_success_data(resp)


# --- disaster deployments ------------------------------------------------
def create_deployment(unit_id: str, **overrides) -> dict:
    resp = api_client.create_deployment(create_deployment_payload(unit_id, **overrides),
                                        TEST_USERS["disaster_services_coordinator_headers"])
    return get_success_data(resp, expected_status=201)


def approve_deployment(deployment_id: str, decision: str = "APPROVE") -> dict:
    resp = api_client.decide_deployment(deployment_id, {"decision": decision},
                                        TEST_USERS["territorial_commander_headers"])
    return get_success_data(resp)


def stage_deployment(deployment_id: str) -> dict:
    resp = api_client.stage_deployment(
        deployment_id, TEST_USERS["disaster_services_coordinator_headers"])
    return get_success_data(resp)


def deploy_deployment(deployment_id: str) -> dict:
    resp = api_client.deploy_deployment(
        deployment_id, TEST_USERS["disaster_services_coordinator_headers"])
    return get_success_data(resp)


def demobilize_deployment(deployment_id: str, demobilized_at: str) -> dict:
    resp = api_client.demobilize_deployment(
        deployment_id, {"demobilized_at": demobilized_at},
        TEST_USERS["disaster_services_coordinator_headers"])
    return get_success_data(resp)


def setup_deployed_deployment(unit_id: str, **overrides) -> dict:
    """Request -> approve -> stage -> deploy. Returns the DEPLOYED deployment."""
    deployment = create_deployment(unit_id, **overrides)
    approve_deployment(deployment["id"])
    stage_deployment(deployment["id"])
    return deploy_deployment(deployment["id"])


# --- reallocation decisions ----------------------------------------------
def propose_reallocation(campaign_id: str, from_location_id: str, to_location_id: str,
                         moved_hours, effective_on: str, **overrides) -> dict:
    resp = api_client.create_reallocation(
        create_reallocation_payload(campaign_id, from_location_id, to_location_id,
                                    moved_hours, effective_on, **overrides),
        TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp, expected_status=201)


def approve_reallocation(decision_id: str) -> dict:
    resp = api_client.approve_reallocation(
        decision_id, TEST_USERS["territorial_commander_headers"])
    return get_success_data(resp)


def apply_reallocation(decision_id: str) -> dict:
    resp = api_client.apply_reallocation(decision_id,
                                         TEST_USERS["kettle_coordinator_headers"])
    return get_success_data(resp)


# =========================================================================
# Composite setups
# =========================================================================
def setup_campaign_with_approved_host_site(clock: str = DEFAULT_CLOCK,
                                           unit_overrides: Optional[dict] = None,
                                           campaign_overrides: Optional[dict] = None,
                                           host_overrides: Optional[dict] = None,
                                           activate: bool = True):
    """Clock + CORPS unit + campaign + one APPROVED host site.

    With activate=True the campaign is moved PLANNING -> ACTIVE, which is the
    posture every campaign-scoped write requires (PRD §2.6).
    Returns (unit, campaign, host_site).
    """
    set_clock(clock)
    unit = create_unit(**(unit_overrides or {}))
    campaign_payload = create_campaign_payload(**(campaign_overrides or {}))
    campaign = create_campaign(**(campaign_overrides or {}))
    # The default permission window in create_host_site_payload is pinned to the
    # default 2026 campaign season; when the caller moves the campaign window the
    # permission must move with it, otherwise a placement inside the campaign
    # would fall outside its own site's permission (PRD §2.7 / ladder step 23).
    effective_host_overrides = {
        "permission_starts_on": campaign_payload["starts_on"],
        "permission_ends_on": campaign_payload["ends_on"],
    }
    effective_host_overrides.update(host_overrides or {})
    host_site = create_host_site(campaign["id"], **effective_host_overrides)
    host_site = approve_host_site(host_site["id"])
    if activate:
        campaign = activate_campaign(campaign["id"])
    return unit, campaign, host_site


def setup_kettle_network(clock: str = DEFAULT_CLOCK,
                         unit_overrides: Optional[dict] = None,
                         campaign_overrides: Optional[dict] = None,
                         host_overrides: Optional[dict] = None,
                         location_overrides: Optional[dict] = None,
                         location_code: str = "K-114-A",
                         placement: str = "OUTDOOR",
                         activate_location: bool = True) -> KettleNetwork:
    """Active campaign + APPROVED host site + one kettle location.

    With activate_location=True the location is DRAFT -> ACTIVE, the posture
    shifts and collections require (PRD §3.1).
    """
    unit, campaign, host_site = setup_campaign_with_approved_host_site(
        clock=clock, unit_overrides=unit_overrides, campaign_overrides=campaign_overrides,
        host_overrides=host_overrides)
    location = create_kettle_location(
        host_site["id"], campaign["id"], location_code=location_code, placement=placement,
        **(location_overrides or {}))
    if activate_location:
        location = activate_kettle_location_ok(location["id"])
    return KettleNetwork(unit=unit, campaign=campaign, host_site=host_site, location=location)


def setup_ringing_scenario(clock: str = DEFAULT_CLOCK,
                           ringer_overrides: Optional[dict] = None,
                           screening_completed_at: str = "2026-11-10T00:00:00Z",
                           **network_kwargs) -> KettleNetwork:
    """The kettle network plus a CLEARED, ACTIVE ringer ready to be scheduled."""
    network = setup_kettle_network(clock=clock, **network_kwargs)
    network.ringer = create_cleared_ringer(
        network.unit["id"], completed_at=screening_completed_at, **(ringer_overrides or {}))
    return network


def setup_assistance_program(clock: str = DEFAULT_CLOCK,
                             campaign_overrides: Optional[dict] = None,
                             program_overrides: Optional[dict] = None,
                             open_program: bool = True):
    """Active campaign + one assistance program (OPEN by default).

    Returns (unit, campaign, program).
    """
    unit, campaign, _host = setup_campaign_with_approved_host_site(
        clock=clock, campaign_overrides=campaign_overrides)
    program = create_assistance_program(campaign["id"], **(program_overrides or {}))
    if open_program:
        program = open_assistance_program(program["id"])
    return unit, campaign, program
