"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
the harness restarts the server before each test, so nothing may be carried
over. Setup calls use `get_success_data()` so a broken precondition reports
"Setup failed" instead of a confusing assertion failure further down.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_ROTATION_START, TEST_DEFAULTS as D
from .factories import (
    check_out_payload,
    cost_ledger_entry_payload,
    create_assistance_request_payload,
    create_blood_drive_payload,
    create_client_case_payload,
    create_client_payload,
    create_deployment_payload,
    create_fund_pool_payload,
    create_operation_payload,
    create_referral_payload,
    create_region_payload,
    create_shelter_operation_payload,
    create_shelter_site_payload,
    create_shift_payload,
    create_volunteer_payload,
    inspection_payload,
    recovery_plan_payload,
    register_client_payload,
    verify_eligibility_payload,
)
from .test_users import (
    TEST_USERS,
    make_shelter_manager_headers,
    make_volunteer_headers,
)

ADMIN = TEST_USERS["national_hq_admin_headers"]
COORD = TEST_USERS["regional_coordinator_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FINANCE_2 = TEST_USERS["second_finance_officer_headers"]
BLOOD = TEST_USERS["blood_services_coordinator_headers"]


def setup_failed(step, response):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {response.status_code} {response.text[:300]}"
    )


# --------------------------------------------------------------------------
# Tier 1 — primitive builders
# --------------------------------------------------------------------------

def create_region(**overrides) -> dict:
    resp = api.create_region(create_region_payload(**overrides), ADMIN)
    if resp.status_code != 201:
        setup_failed("create_region", resp)
    return resp.json()["data"]


def create_operation(region_id, **overrides) -> dict:
    resp = api.create_operation(create_operation_payload(region_id, **overrides), COORD)
    if resp.status_code != 201:
        setup_failed("create_operation", resp)
    return resp.json()["data"]


def create_shelter_site(region_id, **overrides) -> dict:
    resp = api.create_shelter_site(create_shelter_site_payload(region_id, **overrides), COORD)
    if resp.status_code != 201:
        setup_failed("create_shelter_site", resp)
    return resp.json()["data"]


def inspect_site(site_id, expected_version, **overrides) -> dict:
    resp = api.record_inspection(site_id, inspection_payload(expected_version, **overrides), COORD)
    if resp.status_code != 201:
        setup_failed("inspect_site", resp)
    return resp.json()["data"]


def create_volunteer(region_id, **overrides) -> dict:
    resp = api.create_volunteer(create_volunteer_payload(region_id, **overrides), COORD)
    if resp.status_code != 201:
        setup_failed("create_volunteer", resp)
    return resp.json()["data"]


def refresh_credentials(volunteer_id) -> dict:
    resp = api.refresh_credentials(volunteer_id, COORD)
    if resp.status_code != 200:
        setup_failed("refresh_credentials", resp)
    return resp.json()["data"]


def create_shelter_operation(site_id, operation_id) -> dict:
    resp = api.create_shelter_operation(
        create_shelter_operation_payload(site_id, operation_id), COORD)
    if resp.status_code != 201:
        setup_failed("create_shelter_operation", resp)
    return resp.json()["data"]


def request_deployment(volunteer_id, operation_id, **overrides) -> dict:
    resp = api.create_deployment(
        create_deployment_payload(volunteer_id, operation_id, **overrides), COORD)
    if resp.status_code != 201:
        setup_failed("request_deployment", resp)
    return resp.json()["data"]


def approve_deployment(deployment_id) -> dict:
    resp = api.approve_deployment(deployment_id, COORD)
    if resp.status_code != 200:
        setup_failed("approve_deployment", resp)
    return resp.json()["data"]


def set_clock(to_iso8601):
    resp = api.set_clock(to_iso8601, ADMIN)
    if resp.status_code != 200:
        setup_failed("set_clock", resp)
    return resp.json()["data"]


def open_shelter(shelter_operation_id) -> dict:
    resp = api.open_shelter(shelter_operation_id, COORD)
    if resp.status_code != 200:
        setup_failed("open_shelter", resp)
    return resp.json()["data"]


def create_client(region_id, **overrides) -> dict:
    resp = api.create_client(create_client_payload(region_id, **overrides), CASEWORKER)
    if resp.status_code != 201:
        setup_failed("create_client", resp)
    return resp.json()["data"]


def register_client(shelter_operation_id, client_id, manager_headers, **overrides) -> dict:
    resp = api.register_client(
        shelter_operation_id, register_client_payload(client_id, **overrides), manager_headers)
    if resp.status_code != 201:
        setup_failed("register_client", resp)
    return resp.json()["data"]


def create_pool(**overrides) -> dict:
    resp = api.create_fund_pool(create_fund_pool_payload(**overrides), FINANCE)
    if resp.status_code != 201:
        setup_failed("create_pool", resp)
    return resp.json()["data"]


def open_case(client_id, operation_id, **overrides) -> dict:
    resp = api.create_client_case(
        create_client_case_payload(client_id, operation_id, **overrides), CASEWORKER)
    if resp.status_code != 201:
        setup_failed("open_case", resp)
    return resp.json()["data"]


def verify_case_eligibility(case_id, **overrides) -> dict:
    resp = api.verify_eligibility(case_id, verify_eligibility_payload(**overrides), CASEWORKER)
    if resp.status_code != 200:
        setup_failed("verify_case_eligibility", resp)
    return resp.json()["data"]


def write_recovery_plan(case_id, expected_version, **overrides) -> dict:
    resp = api.write_recovery_plan(
        case_id, recovery_plan_payload(expected_version, **overrides), CASEWORKER)
    if resp.status_code != 201:
        setup_failed("write_recovery_plan", resp)
    return resp.json()["data"]


def raise_referral(case_id, **overrides) -> dict:
    resp = api.create_referral(case_id, create_referral_payload(**overrides), CASEWORKER)
    if resp.status_code != 201:
        setup_failed("raise_referral", resp)
    return resp.json()["data"]


def resolve_referral(referral_id, decision) -> dict:
    resp = api.resolve_referral(referral_id, decision, CASEWORKER)
    if resp.status_code != 200:
        setup_failed("resolve_referral", resp)
    return resp.json()["data"]


def submit_assistance_request(case_id, fund_pool_id, **overrides) -> dict:
    resp = api.create_assistance_request(
        case_id, create_assistance_request_payload(fund_pool_id, **overrides), CASEWORKER)
    if resp.status_code != 201:
        setup_failed("submit_assistance_request", resp)
    return resp.json()["data"]


def approve_assistance(request_id, headers=None) -> dict:
    resp = api.approve_assistance_request(request_id, headers or FINANCE)
    if resp.status_code != 200:
        setup_failed("approve_assistance", resp)
    return resp.json()["data"]


def create_blood_drive(region_id, **overrides) -> dict:
    resp = api.create_blood_drive(create_blood_drive_payload(region_id, **overrides), BLOOD)
    if resp.status_code != 201:
        setup_failed("create_blood_drive", resp)
    return resp.json()["data"]


def create_shift(deployment_id, shelter_operation_id, **overrides) -> dict:
    resp = api.create_shift(
        create_shift_payload(deployment_id, shelter_operation_id, **overrides),
        TEST_USERS["shelter_manager_headers"])
    if resp.status_code != 201:
        setup_failed("create_shift", resp)
    return resp.json()["data"]


def check_out(registration_id, manager_headers, **overrides) -> dict:
    resp = api.check_out_registration(
        registration_id, check_out_payload(**overrides), manager_headers)
    if resp.status_code != 200:
        setup_failed("check_out", resp)
    return resp.json()["data"]


def book_ledger_entry(operation_id, expected_version, fund_pool_id, **overrides) -> dict:
    resp = api.create_cost_ledger_entry(
        operation_id, cost_ledger_entry_payload(expected_version, fund_pool_id, **overrides),
        FINANCE)
    if resp.status_code != 201:
        setup_failed("book_ledger_entry", resp)
    return resp.json()["data"]


def manager_headers_for(bundle) -> dict:
    return make_shelter_manager_headers(bundle["volunteer_id"])


def volunteer_headers_for(bundle) -> dict:
    return make_volunteer_headers(bundle["volunteer_id"])


# --------------------------------------------------------------------------
# Tier 2 — the canonical shelter hierarchy
# --------------------------------------------------------------------------

def setup_open_shelter(capacity_beds=8,
                       functional_needs_support=True,
                       accessibility_rating="FULL",
                       inspection_result="PASS",
                       inspected_at=None,
                       capacity_verified_beds=None,
                       functional_needs_verified=None,
                       volunteer_roles=None,
                       rotation_days=14,
                       travel_mode="AIR",
                       rotation_start_at=None,
                       open_clock=None,
                       open_the_shelter=True,
                       site_overrides=None,
                       region_overrides=None,
                       **deployment_overrides) -> dict:
    """Region + operation + APPROVED site + credentialed volunteer + shelter.

    Returns a bundle of the created resources, their ids, and the role headers
    that are safe for ownership-gated calls on this scenario.
    """
    region = create_region(**(region_overrides or {}))
    operation = create_operation(region["id"])
    site = create_shelter_site(
        region["id"],
        capacity_beds=capacity_beds,
        accessibility_rating=accessibility_rating,
        functional_needs_support=functional_needs_support,
        **(site_overrides or {}))

    inspection = {
        "result": inspection_result,
        "capacity_verified_beds": (
            capacity_verified_beds if capacity_verified_beds is not None else capacity_beds),
    }
    if inspected_at is not None:
        inspection["inspected_at"] = inspected_at
    if functional_needs_verified is not None:
        inspection["functional_needs_verified"] = functional_needs_verified
    site = inspect_site(site["id"], site["version"], **inspection)

    volunteer = create_volunteer(
        region["id"],
        qualified_role_codes=list(volunteer_roles or D["VOLUNTEER_ROLES"]))
    volunteer = refresh_credentials(volunteer["id"])

    shelter = create_shelter_operation(site["id"], operation["id"])
    # The creation response is the only observation that carries the
    # PENDING_OPEN snapshot PRD 3.1 pins (zero counts, 0.0 sufficiency); later
    # reads recompute those derived fields from whatever children now exist.
    shelter_created = shelter

    deployment = request_deployment(
        volunteer["id"], operation["id"],
        shelter_operation_id=shelter["id"],
        role_code="SHELTER_MANAGER",
        travel_mode=travel_mode,
        rotation_start_at=rotation_start_at or D["ROTATION_START_AT"],
        rotation_days=rotation_days,
        **deployment_overrides)
    deployment = approve_deployment(deployment["id"])

    set_clock(open_clock or CLOCK_ROTATION_START)
    if open_the_shelter:
        shelter = open_shelter(shelter["id"])
    else:
        shelter = get_success_data(api.get_shelter_operation(shelter["id"], COORD))

    bundle = {
        "region": region,
        "operation": operation,
        "site": site,
        "volunteer": volunteer,
        "shelter": shelter,
        "shelter_created": shelter_created,
        "deployment": deployment,
        "region_id": region["id"],
        "operation_id": operation["id"],
        "site_id": site["id"],
        "volunteer_id": volunteer["id"],
        "shelter_id": shelter["id"],
        "deployment_id": deployment["id"],
        "admin_headers": ADMIN,
        "coordinator_headers": COORD,
        "caseworker_headers": CASEWORKER,
        "finance_headers": FINANCE,
        "blood_headers": BLOOD,
    }
    bundle["manager_headers"] = make_shelter_manager_headers(volunteer["id"])
    bundle["volunteer_headers"] = make_volunteer_headers(volunteer["id"])
    return bundle


def setup_shelter_with_client(**options) -> dict:
    """`setup_open_shelter` plus one client registered at the shelter."""
    client_overrides = options.pop("client_overrides", None) or {}
    registration_overrides = options.pop("registration_overrides", None) or {}
    bundle = setup_open_shelter(**options)
    client = create_client(bundle["region_id"], **client_overrides)
    registration = register_client(
        bundle["shelter_id"], client["id"], bundle["manager_headers"],
        **registration_overrides)
    bundle.update({
        "client": client,
        "registration": registration,
        "client_id": client["id"],
        "registration_id": registration["id"],
    })
    return bundle


def setup_case_for_client(client_id, operation_id, eligibility_status="VERIFIED", **overrides):
    """Open a case for an existing client and optionally settle eligibility."""
    case = open_case(client_id, operation_id, **overrides)
    if eligibility_status is not None:
        case = verify_case_eligibility(case["id"], eligibility_status=eligibility_status)
    return case


def setup_casework_scenario(eligibility_status="VERIFIED",
                            client_overrides=None,
                            case_overrides=None,
                            **options) -> dict:
    """Open shelter + registered client + a case in the requested eligibility state."""
    bundle = setup_shelter_with_client(
        client_overrides=client_overrides, **options)
    case = setup_case_for_client(
        bundle["client_id"], bundle["operation_id"],
        eligibility_status=eligibility_status, **(case_overrides or {}))
    bundle["case"] = case
    bundle["case_id"] = case["id"]
    return bundle


def setup_funded_casework_scenario(pool_overrides=None,
                                   requested_amount_cents=30000,
                                   assistance_type="HOUSING",
                                   approve_twice=False,
                                   **options) -> dict:
    """Casework scenario plus an UNRESTRICTED pool and one assistance request."""
    bundle = setup_casework_scenario(**options)
    pool = create_pool(**{
        "fund_code": "DR-9101-GEN",
        "restriction_type": "UNRESTRICTED",
        "region_id": bundle["region_id"],
        "total_received_cents": 500000,
        **(pool_overrides or {}),
    })
    request = submit_assistance_request(
        bundle["case_id"], pool["id"],
        assistance_type=assistance_type,
        requested_amount_cents=requested_amount_cents)
    bundle.update({"pool": pool, "pool_id": pool["id"], "request": request,
                   "request_id": request["id"]})
    if approve_twice:
        approve_assistance(request["id"])
        bundle["request"] = approve_assistance(request["id"])
    return bundle


# --------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_disbursed_assistance(pool_overrides=None,
                               requested_amount_cents=50000,
                               assistance_type="HOUSING",
                               **options) -> dict:
    """Casework scenario through to a DISBURSED award with a redeemed card."""
    bundle = setup_funded_casework_scenario(
        pool_overrides=pool_overrides,
        requested_amount_cents=requested_amount_cents,
        assistance_type=assistance_type,
        approve_twice=True,
        **options)
    # PRD 3.7: the officer who approved the award may not also issue its card,
    # so issuance must come from the second FinanceOfficer identity.
    issued = get_success_data(api.issue_card(bundle["request_id"], FINANCE_2))
    redeemed = get_success_data(api.redeem_card(bundle["request_id"], FINANCE))
    bundle["issued_request"] = issued
    bundle["request"] = redeemed
    return bundle


def setup_shifted_deployment(shift_overrides=None,
                             check_in=False,
                             check_in_clock=None,
                             **options) -> dict:
    """Open shelter + ARRIVED deployment + one scheduled shift."""
    bundle = setup_open_shelter(**options)
    shift = create_shift(
        bundle["deployment_id"], bundle["shelter_id"], **(shift_overrides or {}))
    bundle["shift"] = shift
    bundle["shift_id"] = shift["id"]
    if check_in:
        set_clock(check_in_clock or "2026-09-03T07:30:00Z")
        shift = get_success_data(
            api.check_in_shift(shift["id"], make_volunteer_headers(bundle["volunteer_id"])))
        bundle["shift"] = shift
    return bundle


def setup_operation_with_shelter(phase="MOBILIZATION", **options) -> dict:
    """Open shelter scenario whose parent operation is advanced to `phase`."""
    bundle = setup_open_shelter(**options)
    order = ["MOBILIZATION", "ACTIVE", "DEMOBILIZATION", "CLOSED"]
    target = order.index(phase)
    for _ in range(target):
        get_success_data(api.advance_operation_phase(bundle["operation_id"], COORD))
    bundle["operation"] = get_success_data(api.get_operation(bundle["operation_id"], COORD))
    return bundle
