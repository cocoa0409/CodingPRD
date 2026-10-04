"""Corner — state machines: initial states, invalid transitions, lockdown."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers.fixtures import ADMIN, RETENTION, SYSOP


def test_subscription_initial_state_pending_activation(api):
    """PRD §3.5: "it begins `PENDING_ACTIVATION`".
    PRD §3.2: "An `ACTIVATE` `SignalCommand` is enqueued for the radio with
    its `path` computed per §2.8."
    PRD §3.2: "A radio's `activation_status` begins `UNREGISTERED`".

    A provisioned in-vehicle trial sits in PENDING_ACTIVATION until its
    ACTIVATE signal is dispatched and acknowledged; the radio is still
    UNREGISTERED.

    Design: Corner/state_machines/subscription_initial_state_pending_activation
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN1"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    sub = fixtures.provision_trial(api, radio, customer, trial_plan)
    assert sub["status"] == "PENDING_ACTIVATION"

    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_now["activation_status"] == "UNREGISTERED"


def test_cancel_terminal_lockdown(api):
    """PRD §3.5: "ends in one of the terminal states `CANCELLED`, `EXPIRED`,
    or `TRANSFERRED_AWAY`. Any attempt to drive a transition that is not
    declared from the current state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    A second cancel on a CANCELLED subscription is rejected, and the ledger —
    append-only — still holds exactly the original CHARGE and the single
    PRORATION_CREDIT of floor(3000*25/30) = 2500.

    Design: Corner/state_machines/cancel_terminal_lockdown
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=3000, auto_renew_default=True,
    )
    sub = fixtures.create_streaming_subscription(api, customer, plan)
    fixtures.send_renewal_disclosure(api, sub["id"])
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")

    headers = fixtures.customer_headers(customer)
    validate_success(
        api.cancel_subscription(sub["id"], {"effective_mode": "IMMEDIATE"},
                                headers)
    )

    resp = api.cancel_subscription(sub["id"], {"effective_mode": "IMMEDIATE"},
                                   headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    entries = fixtures.ledger_entries(api, sub["id"])
    assert len(entries) == 2, f"expected CHARGE + one credit, got {entries}"
    credits = [e for e in entries if e["entry_type"] == "PRORATION_CREDIT"]
    assert len(credits) == 1 and credits[0]["amount_cents"] == -2500


def test_suspend_on_pending_activation_rejected(api):
    """PRD §3.5: "Suspension moves `ACTIVE → SUSPENDED`".
    PRD §3.5: "Any attempt to drive a transition that is not declared from
    the current state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    PENDING_ACTIVATION declares no suspend edge, so the request fails and no
    SUSPEND signal is enqueued.

    Design: Corner/state_machines/suspend_on_pending_activation_rejected
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN1"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    sub = fixtures.provision_trial(api, radio, customer, trial_plan)

    resp = api.suspend_subscription(sub["id"], fixtures.customer_headers(customer))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    signals = validate_success(
        api.list_radio_signal_commands(radio["id"], SYSOP)
    )
    assert len(signals) == 1, f"no SUSPEND signal may be enqueued: {signals}"
    assert signals[0]["command_type"] == "ACTIVATE"


def test_signal_ack_from_queued_rejected(api):
    """PRD §3.4: "From `SENT` a command is either acknowledged or failed by
    the operator. Acknowledgment moves it `SENT → ACKED`".
    PRD §3.5: "Any attempt to drive a transition that is not declared from
    the current state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Acking a still-QUEUED command fails and the command stays QUEUED with
    zero attempts.

    Design: Corner/state_machines/signal_ack_from_queued_rejected
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN1"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    fixtures.provision_trial(api, radio, customer, trial_plan)
    signal = fixtures.first_signal_for_radio(api, radio["id"])

    resp = api.ack_signal(signal["id"], SYSOP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    signal_now = validate_success(api.get_signal_command(signal["id"], SYSOP))
    assert signal_now["status"] == "QUEUED"
    assert signal_now["attempt_count"] == 0
