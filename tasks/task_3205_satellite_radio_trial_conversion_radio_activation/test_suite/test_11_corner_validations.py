"""Corner — validations: hardware gate, offer sequencing, eligibility,
campaign window, save cap, exhausted-signal block."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers.fixtures import ADMIN, RETENTION, SYSOP


def test_hardware_gate_gen1_radio_gen2_tier(api):
    """PRD §3.7: "Because redemption creates a radio-backed subscription, the
    hardware gate applies: the plan's tier `min_hardware_generation` must be
    no newer than the radio's `hardware_generation`, else
    `ERR_HARDWARE_INCOMPATIBLE` (HTTP 422); `STREAMING_ONLY` plans are exempt
    because they touch no radio."

    A GEN1 radio cannot carry a GEN2-minimum tier plan, and no subscription
    is created for the customer.

    Design: Corner/validations/hardware_gate_gen1_radio_gen2_tier
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN1"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN2")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=1000, auto_renew_default=False,
    )
    headers = fixtures.customer_headers(customer)
    resp = api.create_subscription(
        {"customer_id": customer["id"], "plan_id": plan["id"],
         "radio_id": radio["id"], "auto_renew": False},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_HARDWARE_INCOMPATIBLE)

    items, meta = validate_paginated(
        api.list_customer_subscriptions(customer["id"], headers)
    )
    assert meta["total_count"] == 0
    assert items == []


def test_offer_sequence_step_up_rank_gating(api):
    """PRD §3.7: "the step-up sequence must be respected — a step of
    `step_up_rank` R is redeemable only if every step in the campaign with
    rank below R has already been redeemed by this customer or fails its own
    eligibility expression (`ERR_OFFER_SEQUENCE_VIOLATION`, HTTP 422)".

    Rank-1 is rejected while rank-0 is unredeemed; after rank-0, rank-1
    redeems at 6000 - floor(6000*2000/10000) = 4800.

    Design: Corner/validations/offer_sequence_step_up_rank_gating
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=6000, auto_renew_default=False,
    )
    campaign = get_success_data(
        api.create_offer_campaign(fixtures.factories.create_campaign_payload(),
                                  ADMIN)
    )
    step0 = get_success_data(api.add_offer_step(
        campaign["id"],
        {"step_index": 0, "plan_id": plan["id"], "step_up_rank": 0,
         "discount_pct_bps": 1000, "flat_discount_cents": 0},
        ADMIN,
    ))
    step1 = get_success_data(api.add_offer_step(
        campaign["id"],
        {"step_index": 1, "plan_id": plan["id"], "step_up_rank": 1,
         "discount_pct_bps": 2000, "flat_discount_cents": 0},
        ADMIN,
    ))
    get_success_data(api.activate_campaign(campaign["id"], ADMIN))

    headers = fixtures.customer_headers(customer)
    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step1["id"], "customer_id": customer["id"]},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_SEQUENCE_VIOLATION)

    validate_success(
        api.redeem_offer(
            campaign["id"],
            {"offer_step_id": step0["id"], "customer_id": customer["id"]},
            headers,
        ),
        expected_status=201,
    )
    redemption1 = validate_success(
        api.redeem_offer(
            campaign["id"],
            {"offer_step_id": step1["id"], "customer_id": customer["id"]},
            headers,
        ),
        expected_status=201,
    )
    assert redemption1["redeemed_price_cents"] == 4800


def test_offer_eligibility_min_household(api):
    """PRD §3.7: "The eligibility predicate may declare a
    `min_household_size` ... and the step's own `eligibility_expr` must hold
    with its per-customer redemption cap not yet reached
    (`ERR_OFFER_INELIGIBLE`, HTTP 422)."

    A step requiring household_size >= 3 rejects a household-2 customer and
    accepts a household-3 customer at 4000 - floor(4000*500/10000) = 3800
    (single paid sub: the customer IS the anchor, so no family discount).

    Design: Corner/validations/offer_eligibility_min_household
    """
    h2 = fixtures.create_customer(api, household_size=2)
    h3 = fixtures.create_customer(api, household_size=3)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=4000, auto_renew_default=False,
    )
    campaign = get_success_data(
        api.create_offer_campaign(fixtures.factories.create_campaign_payload(),
                                  ADMIN)
    )
    step = get_success_data(api.add_offer_step(
        campaign["id"],
        {"step_index": 0, "plan_id": plan["id"], "step_up_rank": 0,
         "discount_pct_bps": 500, "flat_discount_cents": 0,
         "eligibility_expr": {"min_household_size": 3}},
        ADMIN,
    ))
    get_success_data(api.activate_campaign(campaign["id"], ADMIN))

    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step["id"], "customer_id": h2["id"]},
        fixtures.customer_headers(h2),
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_INELIGIBLE)

    redemption = validate_success(
        api.redeem_offer(
            campaign["id"],
            {"offer_step_id": step["id"], "customer_id": h3["id"]},
            fixtures.customer_headers(h3),
        ),
        expected_status=201,
    )
    assert redemption["redeemed_price_cents"] == 3800


def test_redeem_outside_campaign_window_rejected(api):
    """PRD §3.7: "the campaign must be `ACTIVE` with the current time inside
    its inclusive window (`ERR_CAMPAIGN_WINDOW`)".

    Once the logical clock has passed window_end_at, redeem fails with
    ERR_CAMPAIGN_WINDOW.

    Design: Corner/validations/redeem_outside_campaign_window_rejected
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=3000, auto_renew_default=False,
    )
    campaign = get_success_data(
        api.create_offer_campaign(
            fixtures.factories.create_campaign_payload(
                window_start_at="2026-08-01T00:00:00Z",
                window_end_at="2026-09-15T00:00:00Z",
            ),
            ADMIN,
        )
    )
    step = get_success_data(api.add_offer_step(
        campaign["id"],
        {"step_index": 0, "plan_id": plan["id"], "step_up_rank": 0,
         "discount_pct_bps": 1000},
        ADMIN,
    ))
    get_success_data(api.activate_campaign(campaign["id"], ADMIN))

    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step["id"], "customer_id": customer["id"]},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW)


def test_save_offer_third_accept_cap(api):
    """PRD §3.6: "The subscription's `save_offers_used_in_term` — counting
    accepted save offers in the current term, bounded from 0 to 2 — must
    still be below 2; a third acceptance in the same term is rejected with
    `ERR_SAVE_CAP_REACHED` (HTTP 422)."

    After two full cancel/save cycles (counter at 2) and a third END_OF_TERM
    cancel, the third accept reaches the cap: the state gate passes
    (CANCEL_SCHEDULED) and ERR_SAVE_CAP_REACHED fires.

    Design: Corner/validations/save_offer_third_accept_cap
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=5000, term_days=30, auto_renew=True
    )
    campaign, step = fixtures.create_active_campaign(
        api, plan, lifecycle_phase="SAVE",
        step_overrides={"step_up_rank": 0, "discount_pct_bps": 500,
                        "max_redemptions_per_customer": 10},
    )
    headers = fixtures.customer_headers(customer)
    for _ in range(2):
        get_success_data(api.cancel_subscription(
            sub["id"], {"effective_mode": "END_OF_TERM"}, headers))
        get_success_data(api.accept_save_offer(
            sub["id"], {"offer_step_id": step["id"]}, headers))
    get_success_data(api.cancel_subscription(
        sub["id"], {"effective_mode": "END_OF_TERM"}, headers))

    resp = api.accept_save_offer(
        sub["id"], {"offer_step_id": step["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_SAVE_CAP_REACHED)

    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["save_offers_used_in_term"] == 2
    assert sub_now["status"] == "CANCEL_SCHEDULED"


def test_exhausted_signal_blocks_suspend_until_requeue(api):
    """PRD §3.4: "A subscription with an `EXHAUSTED` command cannot be
    suspended and cannot be immediately cancelled — both actions are rejected
    with `ERR_SIGNAL_EXHAUSTED_BLOCK` (HTTP 409) — until a `RetentionAgent`
    re-enqueues a replacement signal, supplying a fresh `command_type` and
    `idempotency_key`. The replacement is a brand-new `QUEUED` command; the
    exhausted one remains terminal history."
    PRD §3.6: "From `SUSPENDED`, two extra guards apply: the exhausted-signal
    block of §3.4, and, for a `PAID` subscription with `auto_renew` true, a
    regulatory gate".

    With auto_renew false the disclosure gate is out of the way. The
    subscription is SUSPENDED with an exhausted SUSPEND command (PRD §3.6
    scopes the cancel guards to ACTIVE/SUSPENDED — a PENDING_ACTIVATION
    subscription cancels freely): the exhausted block rejects the IMMEDIATE
    cancel, the requeue clears it, and the retried cancel succeeds, refunding
    floor(5000*29/30) = 4833 for the 29 whole days remaining at
    2026-09-01T00:45:00Z.

    Design: Corner/validations/exhausted_signal_blocks_suspend_until_requeue
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=5000, term_days=30, auto_renew=False
    )
    headers = fixtures.customer_headers(customer)
    get_success_data(api.suspend_subscription(sub["id"], headers))
    suspend_signal = [
        s for s in get_success_data(
            api.list_radio_signal_commands(radio["id"], SYSOP))
        if s["command_type"] == "SUSPEND"
    ][0]
    fixtures.exhaust_signal(api, suspend_signal["id"])

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"}, headers)
    validate_error(resp, ApiErrorId.ERR_SIGNAL_EXHAUSTED_BLOCK)

    requeued = validate_success(
        api.requeue_signal(
            sub["id"], {"command_type": "SUSPEND", "idempotency_key": "rq-001"},
            RETENTION,
        ),
        expected_status=201,
    )
    assert requeued["status"] == "QUEUED"
    assert requeued["attempt_count"] == 0
    assert requeued["id"] != suspend_signal["id"]

    cancelled = validate_success(
        api.cancel_subscription(
            sub["id"], {"effective_mode": "IMMEDIATE"}, headers)
    )
    assert cancelled["status"] == "CANCELLED"

    from test_helpers import ledger_amount_of
    credit = ledger_amount_of(fixtures.ledger_entries(api, sub["id"]),
                              "PRORATION_CREDIT")
    assert credit == -4833, f"expected floor(5000*29/30) = -4833, got {credit}"
