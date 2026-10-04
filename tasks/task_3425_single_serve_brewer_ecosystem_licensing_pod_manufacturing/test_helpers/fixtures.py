"""Composite setup helpers.

Every helper builds preconditions from scratch via the public API (the runner
restarts the server before every test, so each test starts on an empty store).
Helpers use the lenient get_success_data validator so a failed setup step
raises a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_brewer_model_payload,
    create_brewer_payload,
    create_brand_payload,
    create_consumption_record_payload,
    create_facility_payload,
    create_filling_line_payload,
    create_household_payload,
    create_license_agreement_payload,
    create_pod_variety_payload,
    create_production_run_payload,
    create_quality_audit_payload,
    create_retail_account_payload,
    create_royalty_statement_payload,
    make_slot,
)
from .test_users import TEST_USERS, make_brand_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
LICENSING = TEST_USERS["licensing_manager_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
OPS = TEST_USERS["operations_director_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
CATEGORY = TEST_USERS["category_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Brands / license agreements / audits
# ---------------------------------------------------------------------------
def create_brand(kind="PLATFORM_OWNED", name=None, home_region="US"):
    payload = create_brand_payload(kind=kind, home_region=home_region)
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_brand(payload, ADMIN), 201)


def create_agreement(brand_id, **overrides):
    """Create a license agreement; returns it in DRAFT."""
    payload = create_license_agreement_payload(brand_id, **overrides)
    return get_success_data(api_client.create_license_agreement(payload, LICENSING), 201)


def activate_agreement(agreement_id):
    return get_success_data(
        api_client.transition_license_agreement(
            agreement_id, {"target_state": "ACTIVE"}, LICENSING))


def create_active_agreement(brand_id, **overrides):
    """Create + activate a license agreement. Returns the ACTIVE agreement."""
    agreement = create_agreement(brand_id, **overrides)
    return activate_agreement(agreement["id"])


def create_audit(agreement_id, **overrides):
    payload = create_quality_audit_payload(**overrides)
    return get_success_data(
        api_client.create_quality_audit(agreement_id, payload, AUDITOR), 201)


# ---------------------------------------------------------------------------
# Pod varieties (BrandManager is entity-backed: headers carry the brand id)
# ---------------------------------------------------------------------------
def create_variety(brand_id, **overrides):
    payload = create_pod_variety_payload(brand_id, **overrides)
    return get_success_data(
        api_client.create_pod_variety(payload, make_brand_manager_headers(brand_id)),
        201)


def transition_variety(variety_id, brand_id, target_state, **extra):
    payload = {"target_state": target_state}
    payload.update(extra)
    return api_client.transition_pod_variety(
        variety_id, payload, make_brand_manager_headers(brand_id))


# ---------------------------------------------------------------------------
# Facilities / filling lines / production runs
# ---------------------------------------------------------------------------
def create_facility(**overrides):
    payload = create_facility_payload(**overrides)
    return get_success_data(api_client.create_facility(payload, OPS), 201)


def create_line(facility_id, **overrides):
    payload = create_filling_line_payload(**overrides)
    return get_success_data(api_client.create_filling_line(facility_id, payload, OPS), 201)


def create_facility_with_line(facility_overrides=None, **line_overrides):
    """One facility plus one filling line. Returns (facility, line)."""
    facility = create_facility(**(facility_overrides or {}))
    line = create_line(facility["id"], **line_overrides)
    return facility, line


def reserve_run(line_id, variety_id, **overrides):
    payload = create_production_run_payload(line_id, variety_id, **overrides)
    return get_success_data(api_client.create_production_run(payload, PLANNER), 201)


def transition_run(run_id, target_state, **extra):
    payload = {"target_state": target_state}
    payload.update(extra)
    return api_client.transition_production_run(run_id, payload, PLANNER)


# ---------------------------------------------------------------------------
# Households / brewers / consumption
# ---------------------------------------------------------------------------
def create_household(size=2, region="NW"):
    payload = create_household_payload(region=region, size=size)
    return get_success_data(api_client.create_household(payload, ADMIN), 201)


def create_brewer_model(**overrides):
    payload = create_brewer_model_payload(**overrides)
    return get_success_data(api_client.create_brewer_model(payload, ADMIN), 201)


def register_brewer(household_id, model_id, serial_number=None):
    payload = create_brewer_payload(model_id)
    if serial_number is not None:
        payload["serial_number"] = serial_number
    return get_success_data(api_client.create_brewer(household_id, payload, ADMIN), 201)


def setup_household_with_brewer(size=4, region="NW", **model_overrides):
    """Household + brewer model + one registered brewer.
    Returns (household, model, brewer)."""
    household = create_household(size=size, region=region)
    model = create_brewer_model(**model_overrides)
    brewer = register_brewer(household["id"], model["id"])
    return household, model, brewer


def add_consumption_record(household_id, period, pods_brewed):
    payload = create_consumption_record_payload(period=period, pods_brewed=pods_brewed)
    return get_success_data(
        api_client.create_consumption_record(household_id, payload, ADMIN), 201)


def record_brews(brewer_id, brews, variety_id):
    return get_success_data(
        api_client.record_brews(
            brewer_id, {"brews": brews, "variety_id": variety_id}, ADMIN))


# ---------------------------------------------------------------------------
# Service events
# ---------------------------------------------------------------------------
def open_service_event(brewer_id, kind, note="routine service"):
    return get_success_data(
        api_client.create_service_event(
            brewer_id, {"kind": kind, "note": note}, SUPPORT), 201)


def resolve_event(event_id, outcome):
    return get_success_data(
        api_client.resolve_service_event(event_id, {"outcome": outcome}, SUPPORT))


# ---------------------------------------------------------------------------
# Retail accounts / assortment plans
# ---------------------------------------------------------------------------
def create_account(shelf_slots_total=10, productivity_floor_cents=0, **overrides):
    payload = create_retail_account_payload(
        shelf_slots_total=shelf_slots_total,
        productivity_floor_cents=productivity_floor_cents, **overrides)
    return get_success_data(api_client.create_retail_account(payload, CATEGORY), 201)


def get_account(account_id):
    return get_success_data(api_client.get_retail_account(account_id, CATEGORY))


def create_plan(account_id, period="2026-10", slots=None, variety_id=None,
                facings=1, clearance_flag=False):
    """Create a DRAFT plan under the account, reading the account's current
    version first so the OCC guard passes. Returns the plan."""
    if slots is None:
        slots = [make_slot(variety_id, facings=facings, clearance_flag=clearance_flag)]
    account = get_account(account_id)
    payload = {
        "expected_retail_account_version": account["version"],
        "period": period,
        "slots": slots,
    }
    return get_success_data(
        api_client.create_assortment_plan(account_id, payload, CATEGORY), 201)


def transition_plan(plan_id, target_state):
    return api_client.transition_assortment_plan(
        plan_id, {"target_state": target_state}, CATEGORY)


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------
def create_statement(agreement_id, **overrides):
    payload = create_royalty_statement_payload(**overrides)
    return get_success_data(
        api_client.create_royalty_statement(agreement_id, payload, FINANCE), 201)


def transition_statement(statement_id, target_state, **extra):
    payload = {"target_state": target_state}
    payload.update(extra)
    return api_client.transition_royalty_statement(statement_id, payload, FINANCE)


def issue_statement(statement_id, **extra):
    return get_success_data(transition_statement(statement_id, "ISSUED", **extra))


