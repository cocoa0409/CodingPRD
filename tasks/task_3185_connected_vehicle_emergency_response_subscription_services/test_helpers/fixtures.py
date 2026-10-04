"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and returns plain dicts of created
resources. Setup calls use get_success_data() so a setup failure surfaces a
clear 'Setup failed' error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_account_headers,
    make_law_enforcement_headers,
    make_emergency_operator_headers,
)
from .factories import (
    create_plan_tier_payload,
    create_account_payload,
    create_coverage_zone_payload,
    create_vehicle_payload,
    create_psap_payload,
    create_dealer_payload,
    create_diagnostic_report_payload,
    create_stolen_case_payload,
    create_remote_command_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
PSAP_OP = TEST_USERS["psap_operator_headers"]
LE_1 = TEST_USERS["law_enforcement_headers"]            # le-officer-1
EO_1 = TEST_USERS["emergency_operator_headers"]         # eo-ops-1
DEALER_SVC = TEST_USERS["dealer_service_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
INGESTION = TEST_USERS["system_ingestion_headers"]


# ---------------------------------------------------------------------------
# Tier 1: reference data and base entities
# ---------------------------------------------------------------------------

def create_tier(code="SAFETY", monthly_fee_cents=2000, allows_emergency=True,
                allows_remote_commands=False, allows_navigation=False,
                allows_data_gb=0):
    """Create a plan tier, or reuse the existing one with the same code.

    PlanTier.code is unique across tiers (PRD §3.1), so a composite setup
    that runs twice in one test (e.g. two accounts on the same default
    tier) would otherwise trip ERR_DUPLICATE on the second creation. The
    tier is pure reference data, so returning the already-created row with
    the same code keeps the precondition identical without violating the
    PRD-required uniqueness constraint.
    """
    existing = get_success_data(_api.list_plan_tiers(ADMIN))
    for t in existing:
        if t.get("code") == code:
            return t
    resp = _api.create_plan_tier(
        create_plan_tier_payload(
            code=code,
            monthly_fee_cents=monthly_fee_cents,
            allows_emergency=allows_emergency,
            allows_remote_commands=allows_remote_commands,
            allows_navigation=allows_navigation,
            allows_data_gb=allows_data_gb,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_zone(region_code="TX", has_cellular=True, supports_data=True,
                supports_navigation=True):
    """Create a coverage zone, or reuse the existing one for the region.

    CoverageZone.region_code is unique across zones (PRD §3.1), so the same
    dedup rationale as create_tier applies: reusing the already-created row
    keeps the precondition identical without violating uniqueness.
    """
    existing = get_success_data(_api.list_coverage_zones(ADMIN))
    for z in existing:
        if z.get("region_code") == region_code:
            return z
    resp = _api.create_coverage_zone(
        create_coverage_zone_payload(
            region_code=region_code,
            has_cellular=has_cellular,
            supports_data=supports_data,
            supports_navigation=supports_navigation,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_account(**overrides):
    """Register an account (PlatformAdmin). Returns the account dict."""
    resp = _api.create_account(create_account_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_vehicle(account, **overrides):
    """Register a vehicle on the account (ownership-gated). Returns vehicle."""
    resp = _api.create_vehicle(
        account["id"],
        create_vehicle_payload(**overrides),
        make_account_headers(account["id"]),
    )
    return get_success_data(resp, 201)


def create_trial_subscription(account, vehicle, tier_code="SAFETY"):
    """Create a TRIAL subscription for the vehicle. Returns subscription."""
    resp = _api.create_subscription(
        account["id"],
        {"vehicle_id": vehicle["id"], "tier_code": tier_code},
        make_account_headers(account["id"]),
    )
    return get_success_data(resp, 201)


def create_psap(name="Austin PSAP", region_code="TX", accepts_location_transfer=True):
    resp = _api.create_psap(
        create_psap_payload(
            name=name,
            region_code=region_code,
            accepts_location_transfer=accepts_location_transfer,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=2):
    resp = _api.create_dealer(
        create_dealer_payload(name=name, region_code=region_code,
                              service_capacity_per_day=capacity),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_diagnostic_report(vehicle, **overrides):
    """Upload a diagnostic report via the ingestion identity. Returns report."""
    resp = _api.create_diagnostic_report(
        vehicle["id"], create_diagnostic_report_payload(**overrides), INGESTION,
    )
    return get_success_data(resp, 201)


def set_clock(to_iso8601):
    resp = _api.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: full account scenario (zone + account + vehicle + subscription)
# ---------------------------------------------------------------------------

def setup_account_scenario(tier_code="SAFETY", tier_fee=2000,
                           allows_remote_commands=False,
                           region_code="TX", has_cellular=True,
                           hardware_generation=5, **account_overrides):
    """Zone + tier + account + vehicle + TRIAL subscription.

    Returns (tier, zone, account, vehicle, subscription).
    """
    tier = create_tier(
        code=tier_code,
        monthly_fee_cents=tier_fee,
        allows_remote_commands=allows_remote_commands,
    )
    zone = create_zone(region_code=region_code, has_cellular=has_cellular,
                       supports_data=has_cellular, supports_navigation=has_cellular)
    account = create_account(home_region_code=region_code, **account_overrides)
    vehicle = create_vehicle(account, region_code=region_code,
                             hardware_generation=hardware_generation)
    subscription = create_trial_subscription(account, vehicle, tier_code=tier_code)
    return tier, zone, account, vehicle, subscription


# ---------------------------------------------------------------------------
# Tier 3: subscription lifecycle shortcuts
# ---------------------------------------------------------------------------

def convert_subscription(account, subscription):
    """Convert TRIAL -> ACTIVE at the subscription's current version.

    Returns the ACTIVE subscription.
    """
    headers = make_account_headers(account["id"])
    resp = _api.convert_subscription(
        account["id"], subscription["id"],
        {"expected_subscription_version": subscription["version"]},
        headers,
    )
    return get_success_data(resp)


def convert_and_fail_payment(account, subscription):
    """Convert to ACTIVE then record PAYMENT_FAILED -> PAST_DUE.

    Returns the PAST_DUE subscription.
    """
    sub = convert_subscription(account, subscription)
    resp = _api.record_billing_event(
        account["id"], sub["id"], {"outcome": "PAYMENT_FAILED"}, BILLING,
    )
    return get_success_data(resp)


def drive_to_emergency_retained(account, subscription,
                                past_due_date="2026-09-01T00:00:00Z",
                                lapse_clock="2026-09-12T00:00:00Z"):
    """Drive a TRIAL subscription to EMERGENCY_RETAINED.

    Convert -> PAYMENT_FAILED -> advance clock past the retry window (lapse)
    -> retain-emergency. Returns the EMERGENCY_RETAINED subscription.
    """
    sub = convert_and_fail_payment(account, subscription)
    set_clock(lapse_clock)
    resp = _api.get_subscription(account["id"], sub["id"],
                                 make_account_headers(account["id"]))
    sub = get_success_data(resp)
    assert sub["status"] == "LAPSED", (
        f"Setup failed: expected LAPSED after clock advance, got {sub['status']}"
    )
    resp = _api.retain_emergency(account["id"], sub["id"],
                                 make_account_headers(account["id"]))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3b: crash workflow shortcuts
# ---------------------------------------------------------------------------

def create_crash_event(vehicle, delta_v_kph=70, rollover_detected=False,
                       airbag_deployed=True, location_region_code="TX"):
    """Ingest a crash event. Returns the CrashEvent dict (201)."""
    resp = _api.create_crash_event(
        vehicle["id"],
        {
            "delta_v_kph": delta_v_kph,
            "rollover_detected": rollover_detected,
            "airbag_deployed": airbag_deployed,
            "location_region_code": location_region_code,
        },
        INGESTION,
    )
    return get_success_data(resp, 201)


def create_advisor_connected_event(vehicle, **crash_kwargs):
    """Crash event RECEIVED -> ADVISOR_CONNECTED. Returns the event."""
    event = create_crash_event(vehicle, **crash_kwargs)
    resp = _api.connect_advisor(vehicle["id"], event["id"], ADVISOR)
    return get_success_data(resp)


def create_dispatched_event(vehicle, psap, **crash_kwargs):
    """Crash event through to DISPATCH_COORDINATED with a LOCATION_SENT dispatch.

    Returns (event, dispatch).
    """
    event = create_advisor_connected_event(vehicle, **crash_kwargs)
    resp = _api.create_dispatch_request(
        vehicle["id"], event["id"], {"psap_id": psap["id"]}, ADVISOR,
    )
    dispatch = get_success_data(resp, 201)
    resp = _api.get_crash_event(vehicle["id"], event["id"], ADVISOR)
    event = get_success_data(resp)
    return event, dispatch


# ---------------------------------------------------------------------------
# Tier 3c: stolen-vehicle workflow shortcuts
# ---------------------------------------------------------------------------

def report_stolen_case(vehicle, reporter_id="le-officer-1", **overrides):
    """Report a stolen vehicle. Returns the REPORTED case."""
    resp = _api.create_stolen_case(
        vehicle["id"],
        create_stolen_case_payload(**overrides),
        make_law_enforcement_headers(reporter_id),
    )
    return get_success_data(resp, 201)


def verify_stolen_case(vehicle, case, verifier_id="le-officer-2"):
    """Verify a REPORTED case with a different officer. Returns the case."""
    resp = _api.verify_stolen_case(
        vehicle["id"], case["id"], make_law_enforcement_headers(verifier_id),
    )
    return get_success_data(resp)


def arm_slowdown(vehicle, case, operator_id="eo-ops-1"):
    """Arm slowdown on a VERIFIED case. Returns the case."""
    resp = _api.arm_slowdown(
        vehicle["id"], case["id"], make_emergency_operator_headers(operator_id),
    )
    return get_success_data(resp)


def execute_slowdown(vehicle, case, operator_id="eo-ops-1"):
    """Execute an armed slowdown. Returns the case."""
    resp = _api.execute_slowdown(
        vehicle["id"], case["id"], make_emergency_operator_headers(operator_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: accumulation / cap targeting
# ---------------------------------------------------------------------------

def issue_and_acknowledge_remote_command(account, vehicle, command_type="LOCK"):
    """Issue a remote command and acknowledge it (consumes the period cap).

    Returns the ACKNOWLEDGED command.
    """
    headers = make_account_headers(account["id"])
    resp = _api.create_remote_command(
        vehicle["id"], create_remote_command_payload(command_type=command_type),
        headers,
    )
    command = get_success_data(resp, 201)
    resp = _api.acknowledge_remote_command(command["id"], INGESTION)
    return get_success_data(resp)


def fill_remote_command_cap(account, vehicle, count, command_type="LOCK"):
    """Issue and acknowledge `count` remote commands. Returns the commands."""
    return [
        issue_and_acknowledge_remote_command(account, vehicle, command_type)
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------
# Tier 3d: dealer appointment shortcuts
# ---------------------------------------------------------------------------

def create_requested_appointment(dealer, vehicle, report, scheduled_date):
    resp = _api.create_appointment(
        dealer["id"],
        {
            "vehicle_id": vehicle["id"],
            "diagnostic_report_id": report["id"],
            "scheduled_date": scheduled_date,
        },
        DEALER_SVC,
    )
    return get_success_data(resp, 201)


def create_confirmed_appointment(dealer, vehicle, report, scheduled_date):
    appointment = create_requested_appointment(dealer, vehicle, report, scheduled_date)
    resp = _api.confirm_appointment(dealer["id"], appointment["id"], DEALER_SVC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3e: consent shortcuts
# ---------------------------------------------------------------------------

def create_consent(account, consent_type):
    resp = _api.create_consent(
        account["id"], {"consent_type": consent_type},
        make_account_headers(account["id"]),
    )
    return get_success_data(resp, 201)
