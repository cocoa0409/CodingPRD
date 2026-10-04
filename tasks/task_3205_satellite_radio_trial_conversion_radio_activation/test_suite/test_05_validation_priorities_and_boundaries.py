"""Validation priority pairs, disclosure boundary, and refund day boundary."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures, ledger_amount_of
from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import ADMIN, RETENTION, SYSOP


def _two_save_cycles(api):
    """ACTIVE auto-renew paid sub with two completed cancel/save cycles, plus
    the SAVE campaign step. Returns (customer, sub, step)."""
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=5000, term_days=30, auto_renew=True
    )
    campaign, step = fixtures.create_active_campaign(
        api, plan, lifecycle_phase="SAVE",
        step_overrides={"step_up_rank": 0, "discount_pct_bps": 1000,
                        "flat_discount_cents": 0,
                        "max_redemptions_per_customer": 10},
    )
    headers = fixtures.customer_headers(customer)
    for _ in range(2):
        get_success_data(
            api.cancel_subscription(sub["id"], {"effective_mode": "END_OF_TERM"},
                                    headers)
        )
        get_success_data(
            api.accept_save_offer(sub["id"], {"offer_step_id": step["id"]}, headers)
        )
    return customer, sub, step


def test_invalid_state_vs_save_cap_priority(api):
    """PRD §2.9: "State-legality is next (`ERR_INVALID_STATE` for a transition
    not declared from the current state), then ownership ... Only after those
    structural checks do the business rules fire, in this order: ... the
    save-offer cap (`ERR_SAVE_CAP_REACHED`)".

    With the counter already at 2 and the subscription back in ACTIVE, the
    third save-accept violates both the state machine (no
    CANCEL_SCHEDULED -> ACTIVE edge from ACTIVE) and the save cap; the state
    check outranks the fiscal cap, so ERR_INVALID_STATE must surface.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_save_cap_priority
    """
    customer, sub, step = _two_save_cycles(api)
    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["status"] == "ACTIVE"
    assert sub_now["save_offers_used_in_term"] == 2

    resp = api.accept_save_offer(
        sub["id"], {"offer_step_id": step["id"]},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_save_cap_state_outranks_even_with_cap_reached(api):
    """PRD §2.9: "State-legality is next (`ERR_INVALID_STATE` for a transition
    not declared from the current state)".

    Even the first save attempt on an ACTIVE (never cancel-scheduled)
    subscription is rejected with ERR_INVALID_STATE — the state gate fires
    before any save-specific rule regardless of the counter.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_save_cap_priority
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=5000, term_days=30, auto_renew=True
    )
    campaign, step = fixtures.create_active_campaign(
        api, plan, lifecycle_phase="SAVE",
        step_overrides={"step_up_rank": 0, "discount_pct_bps": 1000},
    )
    resp = api.accept_save_offer(
        sub["id"], {"offer_step_id": step["id"]},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _suspended_sub_with_exhausted_suspend_signal(api, auto_renew=True):
    """ACTIVE auto-renew paid sub -> suspended -> its SUSPEND signal driven to
    EXHAUSTED. This lands the subscription in SUSPENDED with an EXHAUSTED
    command, the state in which PRD §3.6 makes both the disclosure gate and
    the exhausted-signal block fire on an IMMEDIATE cancel.

    Returns (customer, sub).
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=5000, term_days=30, auto_renew=auto_renew
    )
    get_success_data(
        api.suspend_subscription(sub["id"], fixtures.customer_headers(customer))
    )
    suspend_signal = [
        s for s in get_success_data(
            api.list_radio_signal_commands(radio["id"], SYSOP))
        if s["command_type"] == "SUSPEND"
    ][0]
    fixtures.exhaust_signal(api, suspend_signal["id"])
    return customer, sub


def test_disclosure_safety_vs_signal_block_priority_on_immediate_cancel(api):
    """PRD §2.9: "Only after those structural checks do the business rules
    fire, in this order: the regulatory renewal-disclosure gate
    (`ERR_RENEWAL_DISCLOSURE_REQUIRED`); the exhausted-signal block
    (`ERR_SIGNAL_EXHAUSTED_BLOCK`)".
    PRD §3.6: "the law does not permit silently immediate-cancelling an
    auto-renewing paid subscription whose renewal disclosure was never sent —
    the retention flow must disclose first."

    An IMMEDIATE cancel on an auto-renew paid sub that is SUSPENDED with an
    EXHAUSTED command and whose disclosure was never sent violates both gates;
    the disclosure gate is declared first, so ERR_RENEWAL_DISCLOSURE_REQUIRED
    must surface. (The cancel guards of PRD §3.6 apply only from ACTIVE or
    SUSPENDED — a still-PENDING_ACTIVATION subscription cancels freely — so
    the exhausted signal is raised on a SUSPEND command, not the ACTIVATE.)

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_vs_signal_block_priority_on_immediate_cancel
    """
    customer, sub = _suspended_sub_with_exhausted_suspend_signal(
        api, auto_renew=True
    )

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_DISCLOSURE_REQUIRED)


def test_signal_block_alone_surfaces_when_disclosure_sent(api):
    """PRD §3.4: "A subscription with an `EXHAUSTED` command cannot be
    suspended and cannot be immediately cancelled — both actions are rejected
    with `ERR_SIGNAL_EXHAUSTED_BLOCK` (HTTP 409)".

    With the renewal disclosure already sent, the disclosure gate passes and
    the exhausted-signal block is the surviving rejection on IMMEDIATE cancel.
    (The subscription is SUSPENDED with an exhausted SUSPEND command: per PRD
    §3.6 the cancel guards do not apply from PENDING_ACTIVATION.)

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_vs_signal_block_priority_on_immediate_cancel
    """
    customer, sub = _suspended_sub_with_exhausted_suspend_signal(
        api, auto_renew=True
    )
    fixtures.send_renewal_disclosure(api, sub["id"])

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_SIGNAL_EXHAUSTED_BLOCK)


def _streaming_sub_with_disclosure(api, email_household=1, send_at=None):
    """A 5000/30d auto-renew STREAMING_ONLY sub created at the default clock;
    optionally a RENEWAL_NOTICE sent at `send_at` (clock is moved there and
    restored to the default)."""
    customer = fixtures.create_customer(api, household_size=email_household)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=5000, auto_renew_default=True,
    )
    sub = fixtures.create_streaming_subscription(api, customer, plan)
    assert sub["status"] == "ACTIVE"
    if send_at is not None:
        fixtures.set_clock(api, send_at)
        fixtures.send_renewal_disclosure(api, sub["id"])
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    return customer, sub


def test_renewal_disclosure_exactly_15_days_before_passes(api):
    """PRD §3.8: "renewal is forbidden unless a `DisclosureRecord` of type
    `RENEWAL_NOTICE` ... exists whose `sent_at` is no later than 15 days
    before the subscription's `end_at`."

    The term created at 2026-09-01 ends at 2026-10-01; a disclosure sent at
    2026-09-16T00:00:00Z is exactly 15 days before end_at and renews, while a
    sibling whose disclosure went out at 2026-09-17 (14 days) is blocked.

    Design: Difficulty/boundary_precision_check/renewal_disclosure_exactly_15_days_before_passes
    """
    customer_a, sub_a = _streaming_sub_with_disclosure(
        api, send_at="2026-09-16T00:00:00Z"
    )
    customer_b, sub_b = _streaming_sub_with_disclosure(
        api, send_at="2026-09-17T00:00:00Z"
    )

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    # PRD §2.7: advancing the clock itself re-evaluates time-based
    # transitions, so the renewal/block may already have been applied by the
    # clock advance; the explicit batch then reports only what remained. The
    # observable contract is the resulting state, asserted below.
    fixtures.run_renewals(api)

    sub_a_now = validate_success(api.get_subscription(sub_a["id"], ADMIN))
    assert_same_instant(sub_a_now["start_at"], "2026-10-01T00:00:00Z",
                        "sub_a start_at")
    assert_same_instant(sub_a_now["end_at"], "2026-10-31T00:00:00Z",
                        "sub_a end_at")
    entries_a = fixtures.ledger_entries(api, sub_a["id"])
    charges = [e for e in entries_a if e["entry_type"] == "CHARGE"]
    assert len(charges) == 2 and charges[-1]["amount_cents"] == 5000

    sub_b_now = validate_success(api.get_subscription(sub_b["id"], ADMIN))
    assert sub_b_now["status"] == "ACTIVE"
    assert_same_instant(sub_b_now["start_at"], "2026-09-01T00:00:00Z",
                        "sub_b start_at")
    assert sub_b_now["disclosure_state"] == "REQUIRED"
    entries_b = fixtures.ledger_entries(api, sub_b["id"])
    assert len([e for e in entries_b if e["entry_type"] == "CHARGE"]) == 1


def test_renewal_disclosure_sent_well_before_boundary_renews(api):
    """PRD §3.8: "renewal is forbidden unless a `DisclosureRecord` of type
    `RENEWAL_NOTICE` ... exists whose `sent_at` is no later than 15 days
    before the subscription's `end_at`."

    A disclosure sent 16 days before end_at clears the gate.

    Design: Difficulty/boundary_precision_check/renewal_disclosure_exactly_15_days_before_passes
    """
    customer, sub = _streaming_sub_with_disclosure(
        api, send_at="2026-09-15T00:00:00Z"
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    # PRD §2.7: the clock advance itself re-evaluates time-based transitions;
    # the explicit batch only processes whatever remains.
    fixtures.run_renewals(api)
    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert_same_instant(sub_now["start_at"], "2026-10-01T00:00:00Z",
                        "start_at")


def test_cancel_refund_at_exact_day_boundary_vs_fraction(api):
    """PRD §3.6: "The unused time is the whole number of days between the
    cancellation time and `end_at` — the difference in seconds divided by
    86400, floored. The refund is the subscription's
    `current_term_price_cents` multiplied by those unused days and divided by
    the plan's `term_length_days`, floored."

    A 9000/30d term ending 2026-10-01T00:00:00Z cancelled at
    2026-09-15T00:00:00Z has exactly 16 whole days remaining -> refund 4800;
    one second later the count floors to 15 -> refund 4500.

    Design: Difficulty/boundary_precision_check/cancel_refund_at_exact_day_boundary_vs_fraction
    """
    customer1, vehicle1, radio1, plan1, sub1 = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )
    customer2, vehicle2, radio2, plan2, sub2 = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )

    fixtures.set_clock(api, "2026-09-15T00:00:00Z")
    resp1 = api.cancel_subscription(
        sub1["id"], {"effective_mode": "IMMEDIATE"},
        fixtures.customer_headers(customer1),
    )
    validate_success(resp1)

    fixtures.set_clock(api, "2026-09-15T00:00:01Z")
    resp2 = api.cancel_subscription(
        sub2["id"], {"effective_mode": "IMMEDIATE"},
        fixtures.customer_headers(customer2),
    )
    validate_success(resp2)

    credit1 = ledger_amount_of(fixtures.ledger_entries(api, sub1["id"]),
                               "PRORATION_CREDIT")
    credit2 = ledger_amount_of(fixtures.ledger_entries(api, sub2["id"]),
                               "PRORATION_CREDIT")
    assert credit1 == -4800, f"16 whole days must refund 4800, got {credit1}"
    assert credit2 == -4500, f"15 whole days must refund 4500, got {credit2}"


def test_cancel_refund_mid_term_fractional_day_floors(api):
    """PRD §3.6: "The unused time is the whole number of days between the
    cancellation time and `end_at` — the difference in seconds divided by
    86400, floored."

    At 2026-09-15T12:00:00Z there are 15.5 days remaining; the floor gives 15
    and the refund is floor(9000*15/30) = 4500.

    Design: Difficulty/boundary_precision_check/cancel_refund_at_exact_day_boundary_vs_fraction
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )
    fixtures.set_clock(api, "2026-09-15T12:00:00Z")
    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"},
        fixtures.customer_headers(customer),
    )
    validate_success(resp)
    credit = ledger_amount_of(fixtures.ledger_entries(api, sub["id"]),
                              "PRORATION_CREDIT")
    assert credit == -4500, f"15.5 days must floor to 15 -> 4500, got {credit}"
