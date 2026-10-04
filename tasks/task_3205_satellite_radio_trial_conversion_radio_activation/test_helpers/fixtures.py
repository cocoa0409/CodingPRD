"""Composite setup helpers. Each fixture builds its preconditions through the
public API only, starting from the empty database the harness guarantees.
Setup calls use the lenient validator so failures surface as clear
"Setup failed" errors.
"""

from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .api_client import ApiClient
from .test_users import (
    ANONYMOUS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    RETENTION_AGENT_HEADERS,
    SYSTEM_OPERATOR_HEADERS,
    make_automaker_headers,
    make_customer_headers,
    make_dealer_headers,
)

ADMIN = PLATFORM_ADMIN_HEADERS
SYSOP = SYSTEM_OPERATOR_HEADERS
RETENTION = RETENTION_AGENT_HEADERS


# --- small builders ---------------------------------------------------------

def set_clock(api: ApiClient, to_iso8601: str):
    get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_customer(api: ApiClient, household_size: int = 1, **overrides):
    data = get_success_data(
        api.create_customer(
            factories.create_customer_payload(household_size=household_size, **overrides),
            ANONYMOUS_HEADERS,
        )
    )
    return data


def create_automaker(api: ApiClient, **overrides):
    return get_success_data(
        api.create_automaker(factories.create_automaker_payload(**overrides), ADMIN)
    )


def create_dealer(api: ApiClient, enrolled: bool = False, **overrides):
    return get_success_data(
        api.create_dealer(
            factories.create_dealer_payload(used_program_enrolled=enrolled, **overrides),
            ADMIN,
        )
    )


def enroll_dealer(api: ApiClient, dealer_id: str):
    return get_success_data(api.enroll_used_program(dealer_id, ADMIN))


def create_tier(api: ApiClient, **overrides):
    return get_success_data(
        api.create_package_tier(factories.create_package_tier_payload(**overrides), ADMIN)
    )


def create_paid_plan(api: ApiClient, tier_id: str, **overrides):
    return get_success_data(
        api.create_subscription_plan(
            factories.create_subscription_plan_payload(tier_id, **overrides), ADMIN
        )
    )


def create_trial_plan(api: ApiClient, tier_id: str, **overrides):
    return get_success_data(
        api.create_subscription_plan(
            factories.create_trial_plan_payload(tier_id, **overrides), ADMIN
        )
    )


def create_vehicle(api: ApiClient, automaker_id: str, owner_customer_id: str,
                   condition: str = "NEW", **overrides):
    return get_success_data(
        api.create_vehicle(
            factories.create_vehicle_payload(
                automaker_id, owner_customer_id, condition=condition, **overrides
            ),
            ADMIN,
        )
    )


def create_radio(api: ApiClient, vehicle_id: str, hardware_generation: str = "GEN2",
                 **overrides):
    return get_success_data(
        api.create_radio(
            factories.create_radio_payload(
                vehicle_id, hardware_generation=hardware_generation, **overrides
            ),
            ADMIN,
        )
    )


def customer_headers(customer) -> dict:
    cid = customer["id"] if isinstance(customer, dict) else customer
    return make_customer_headers(cid)


# --- composite: subscription creation --------------------------------------

def create_streaming_subscription(api: ApiClient, customer, plan, auto_renew=None):
    """Direct purchase of a STREAMING_ONLY plan: ACTIVE immediately."""
    payload = {"customer_id": customer["id"], "plan_id": plan["id"]}
    if auto_renew is not None:
        payload["auto_renew"] = auto_renew
    return get_success_data(
        api.create_subscription(payload, customer_headers(customer))
    )


def create_paid_radio_subscription(api: ApiClient, customer, plan, radio,
                                   auto_renew=None):
    """Direct purchase of an in-vehicle plan: PENDING_ACTIVATION with an
    enqueued ACTIVATE signal."""
    payload = {
        "customer_id": customer["id"],
        "plan_id": plan["id"],
        "radio_id": radio["id"],
    }
    if auto_renew is not None:
        payload["auto_renew"] = auto_renew
    return get_success_data(
        api.create_subscription(payload, customer_headers(customer))
    )


def provision_trial(api: ApiClient, radio, customer, plan, expected_version=None):
    """Direct trial provisioning on a radio (OCC-guarded)."""
    version = expected_version if expected_version is not None else radio["version"]
    return get_success_data(
        api.provision_trial(
            radio["id"],
            {
                "plan_id": plan["id"],
                "customer_id": customer["id"],
                "expected_radio_version": version,
            },
            customer_headers(customer),
        )
    )


def first_signal_for_radio(api: ApiClient, radio_id: str):
    data = get_success_data(api.list_radio_signal_commands(radio_id, SYSOP))
    assert data, f"expected at least one signal command for radio {radio_id}"
    return data[0]


def dispatch_and_ack(api: ApiClient, signal_id: str):
    get_success_data(api.dispatch_signals(SYSOP))
    return get_success_data(api.ack_signal(signal_id, SYSOP))


def dispatch_and_fail(api: ApiClient, signal_id: str):
    get_success_data(api.dispatch_signals(SYSOP))
    return get_success_data(api.fail_signal(signal_id, SYSOP))


def activate_subscription(api: ApiClient, subscription, radio_id: str):
    """Dispatch + ack the ACTIVATE signal so the subscription reaches ACTIVE."""
    signal = first_signal_for_radio(api, radio_id)
    dispatch_and_ack(api, signal["id"])
    return get_success_data(api.get_subscription(subscription["id"], ADMIN))


def exhaust_signal(api: ApiClient, signal_id: str, start_clock="2026-09-01T00:00:00Z",
                   base_minutes: int = 15):
    """Drive a QUEUED signal to EXHAUSTED: three dispatch+fail rounds, hopping
    the logical clock past each linear-backoff retry deadline."""
    now = start_clock
    attempts = 0
    while True:
        get_success_data(api.dispatch_signals(SYSOP))
        signal = get_success_data(api.fail_signal(signal_id, SYSOP))
        attempts = signal["attempt_count"]
        if signal["status"] == "EXHAUSTED":
            return signal
        # hop to the computed next_retry_at, then loop
        next_retry = signal["next_retry_at"]
        set_clock(api, next_retry)


# --- composite: vehicle/radio world ----------------------------------------

def setup_customer_with_radio(api: ApiClient, hardware_generation: str = "GEN2",
                              condition: str = "NEW", household_size: int = 1):
    """Customer + automaker + vehicle + radio. Returns all four."""
    customer = create_customer(api, household_size=household_size)
    automaker = create_automaker(api)
    vehicle = create_vehicle(api, automaker["id"], customer["id"], condition=condition)
    radio = create_radio(api, vehicle["id"], hardware_generation=hardware_generation)
    return customer, automaker, vehicle, radio


def setup_active_paid_sub(api: ApiClient, price_cents: int = 6000,
                          term_days: int = 30, auto_renew: bool = False,
                          hardware_generation: str = "GEN2",
                          household_size: int = 1):
    """World with one ACTIVE in-vehicle paid subscription.

    Returns (customer, vehicle, radio, plan, subscription).
    """
    customer, automaker, vehicle, radio = setup_customer_with_radio(
        api, hardware_generation=hardware_generation, household_size=household_size
    )
    tier = create_tier(api, includes_streaming=False,
                       min_hardware_generation="GEN1")
    plan = create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE",
        term_kind="MONTHLY", term_length_days=term_days,
        price_cents=price_cents, auto_renew_default=auto_renew,
    )
    sub = create_paid_radio_subscription(api, customer, plan, radio,
                                         auto_renew=auto_renew)
    sub = activate_subscription(api, sub, radio["id"])
    return customer, vehicle, radio, plan, sub


# --- composite: campaigns ----------------------------------------------------

def create_active_campaign(api: ApiClient, plan, lifecycle_phase: str = "POST_TRIAL",
                           step_overrides: Optional[dict] = None,
                           window_start="2026-08-01T00:00:00Z",
                           window_end="2026-12-01T00:00:00Z",
                           **campaign_overrides):
    """Create a campaign, add one step, activate it.

    Returns (campaign, step).
    """
    campaign = get_success_data(
        api.create_offer_campaign(
            factories.create_campaign_payload(
                lifecycle_phase=lifecycle_phase,
                window_start_at=window_start,
                window_end_at=window_end,
                **campaign_overrides,
            ),
            ADMIN,
        )
    )
    step = get_success_data(
        api.add_offer_step(
            campaign["id"],
            factories.create_offer_step_payload(plan["id"], **(step_overrides or {})),
            ADMIN,
        )
    )
    get_success_data(api.activate_campaign(campaign["id"], ADMIN))
    return campaign, step


def send_renewal_disclosure(api: ApiClient, subscription_id: str,
                            channel: str = "EMAIL",
                            disclosure_type: str = "RENEWAL_NOTICE"):
    return get_success_data(
        api.send_disclosure(
            subscription_id,
            {"disclosure_type": disclosure_type, "channel": channel},
            RETENTION,
        )
    )


def ledger_entries(api: ApiClient, subscription_id: str):
    return get_success_data(api.list_subscription_ledger(subscription_id, ADMIN))


def run_renewals(api: ApiClient):
    return get_success_data(api.run_renewals(SYSOP))
