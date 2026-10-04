"""Save-offer loop and signal retry/exhaustion cycles."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import ADMIN, SYSOP


def _setup_cancel_scheduled_paid_sub(api, price_cents=4000):
    """ACTIVE paid sub (auto_renew true) moved to CANCEL_SCHEDULED, plus an
    active SAVE campaign step on the same plan.

    Returns (customer, radio, plan, sub, campaign, step).
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=price_cents, term_days=30, auto_renew=True
    )
    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "END_OF_TERM"},
        fixtures.customer_headers(customer),
    )
    sub = validate_success(resp)
    assert sub["status"] == "CANCEL_SCHEDULED"
    campaign, step = fixtures.create_active_campaign(
        api, plan, lifecycle_phase="SAVE",
        step_overrides={"step_up_rank": 0, "discount_pct_bps": 5000,
                        "flat_discount_cents": 0,
                        "max_redemptions_per_customer": 10},
    )
    return customer, radio, plan, sub, campaign, step


def test_save_offer_cycle_reverts_cancel(api):
    """PRD §3.6: "On acceptance, `cancel_requested_at` is cleared back to
    null, `auto_renew` is restored to true, `kind` becomes `SAVE_OFFER` ... and
    `save_offers_used_in_term` increments by one."
    PRD §3.6: "an informational `SAVE_CREDIT` ledger entry records the
    next-term discount amount ... `disclosure_state` returns to `REQUIRED`,
    demanding fresh disclosure."

    Save rate for the next term: 4000 - floor(4000*5000/10000) = 2000.

    Design: Difficulty/non_linear_state_machine/subscription_save_offer_cycle_reverts_cancel
    """
    customer, radio, plan, sub, campaign, step = _setup_cancel_scheduled_paid_sub(api)

    resp = api.accept_save_offer(
        sub["id"], {"offer_step_id": step["id"]},
        fixtures.customer_headers(customer),
    )
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["kind"] == "SAVE_OFFER"
    assert data["cancel_requested_at"] is None
    assert data["auto_renew"] is True
    assert data["save_offers_used_in_term"] == 1
    assert data["current_term_price_cents"] == 2000
    assert data["disclosure_state"] == "REQUIRED"

    entries = fixtures.ledger_entries(api, sub["id"])
    save_credits = [e for e in entries if e["entry_type"] == "SAVE_CREDIT"]
    assert len(save_credits) == 1, f"expected one SAVE_CREDIT, got {entries}"


def test_save_offer_restores_cyclic_edge_back_to_active(api):
    """PRD §3.6: "accepting a save offer moves `CANCEL_SCHEDULED → ACTIVE`."
    PRD §3.6: "The acceptance names an `offer_step_id` drawn from a campaign
    whose `lifecycle_phase` is `SAVE` and whose `state` is `ACTIVE`".

    After the save accept the subscription is once again cancellable from
    ACTIVE — the cyclic edge closes the loop.

    Design: Difficulty/non_linear_state_machine/subscription_save_offer_cycle_reverts_cancel
    """
    customer, radio, plan, sub, campaign, step = _setup_cancel_scheduled_paid_sub(api)

    resp = api.accept_save_offer(
        sub["id"], {"offer_step_id": step["id"]},
        fixtures.customer_headers(customer),
    )
    validate_success(resp)

    resp2 = api.cancel_subscription(
        sub["id"], {"effective_mode": "END_OF_TERM"},
        fixtures.customer_headers(customer),
    )
    data2 = validate_success(resp2)
    assert data2["status"] == "CANCEL_SCHEDULED"
    assert data2["cancel_requested_at"] is not None


def _setup_trial_with_signal(api):
    """Trial subscription provisioned on a GEN2 radio; returns
    (customer, radio, trial_sub, signal)."""
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN2"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=90)
    sub = fixtures.provision_trial(api, radio, customer, trial_plan)
    signal = fixtures.first_signal_for_radio(api, radio["id"])
    return customer, radio, sub, signal


def test_signal_retry_cycle_exhausts_at_three(api):
    """PRD §3.4: "while `attempt_count` is below 3 the command is automatically
    requeued to `QUEUED` with `next_retry_at` set to the failure time plus
    `attempt_count` times the path's base interval; the moment `attempt_count`
    reaches 3 the command instead becomes terminal `EXHAUSTED`."
    PRD §2.8: "A `CELLULAR` command retries with a base interval of 15
    minutes".

    GEN2 radio -> CELLULAR path -> 15-minute base: after the first failure
    next_retry_at is 2026-09-01T00:15:00Z; after the second,
    2026-09-01T00:45:00Z; the third failure exhausts the command.

    Design: Difficulty/non_linear_state_machine/signal_command_retry_cycle_exhausts_at_three
    """
    customer, radio, sub, signal = _setup_trial_with_signal(api)
    sig_id = signal["id"]

    from prd_bench_local_runner.testing import get_success_data

    get_success_data(api.dispatch_signals(SYSOP))
    s1 = get_success_data(api.fail_signal(sig_id, SYSOP))
    assert s1["status"] == "QUEUED"
    assert s1["attempt_count"] == 1
    assert_same_instant(s1["next_retry_at"], "2026-09-01T00:15:00Z",
                        "next_retry_at after first failure")

    fixtures.set_clock(api, "2026-09-01T00:15:00Z")
    get_success_data(api.dispatch_signals(SYSOP))
    s2 = get_success_data(api.fail_signal(sig_id, SYSOP))
    assert s2["status"] == "QUEUED"
    assert s2["attempt_count"] == 2
    assert_same_instant(s2["next_retry_at"], "2026-09-01T00:45:00Z",
                        "next_retry_at after second failure")

    fixtures.set_clock(api, "2026-09-01T00:45:00Z")
    get_success_data(api.dispatch_signals(SYSOP))
    s3 = get_success_data(api.fail_signal(sig_id, SYSOP))
    assert s3["attempt_count"] == 3
    assert s3["status"] == "EXHAUSTED"

    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["status"] == "PENDING_ACTIVATION"
    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_now["activation_status"] == "UNREGISTERED"


def test_exhausted_signal_is_terminal(api):
    """PRD §3.4: "`ACKED`, `EXHAUSTED`, and `SUPERSEDED` are the terminal
    states."

    A further dispatch cycle after exhaustion never revives the command.

    Design: Difficulty/non_linear_state_machine/signal_command_retry_cycle_exhausts_at_three
    """
    customer, radio, sub, signal = _setup_trial_with_signal(api)
    fixtures.exhaust_signal(api, signal["id"])

    from prd_bench_local_runner.testing import get_success_data
    get_success_data(api.dispatch_signals(SYSOP))
    final = validate_success(api.get_signal_command(signal["id"], SYSOP))
    assert final["status"] == "EXHAUSTED"
    assert final["attempt_count"] == 3
