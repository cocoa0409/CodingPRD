"""Term pricing order-of-operations and family-discount conservation."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures

ADMIN_HEADERS = fixtures.ADMIN


def _setup_offer_pricing_world(api, price_cents, pct_bps, flat_cents,
                               household_size=1, anchor_price=None):
    """Customer + streaming tier + paid plan + active POST_TRIAL campaign with
    one step. Optionally pre-create an anchor streaming sub of `anchor_price`.
    Returns (customer, plan, campaign, step, anchor_sub or None).
    """
    customer = fixtures.create_customer(api, household_size=household_size)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=price_cents, auto_renew_default=False,
    )
    anchor_sub = None
    if anchor_price is not None:
        anchor_plan = fixtures.create_paid_plan(
            api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
            term_length_days=30, price_cents=anchor_price, auto_renew_default=False,
        )
        anchor_sub = fixtures.create_streaming_subscription(
            api, customer, anchor_plan, auto_renew=False
        )
    campaign, step = fixtures.create_active_campaign(
        api, plan, lifecycle_phase="POST_TRIAL",
        step_overrides={
            "step_up_rank": 0,
            "discount_pct_bps": pct_bps,
            "flat_discount_cents": flat_cents,
        },
    )
    return customer, plan, campaign, step, anchor_sub


def test_term_pricing_offer_then_family_order_pinned(api):
    """PRD §3.3: "The offer discount applies **first**: it is the floor of the
    base multiplied by the redeeming step's `discount_pct_bps` divided by ten
    thousand, followed by subtraction of the step's `flat_discount_cents`,
    with the result floored at zero."
    PRD §3.3: "the family discount is the ceiling of one quarter — 2500 basis
    points — of the base price after the offer discount."

    Base 6000 with a 2000-bps offer step: offer discount floor(6000*2000/10000)
    = 1200 -> 4800; family discount ceil(4800*2500/10000) = 1200 -> 3600.
    The pre-existing 8000-cent streaming sub is the anchor (highest base).

    Design: Difficulty/combinatorial_formula/term_pricing_offer_then_family_order_pinned
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN2", household_size=2
    )
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    p6 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=6000, auto_renew_default=False,
    )
    p8 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=8000, auto_renew_default=False,
    )
    campaign, step = fixtures.create_active_campaign(
        api, p6, lifecycle_phase="POST_TRIAL",
        step_overrides={"step_up_rank": 0, "discount_pct_bps": 2000,
                        "flat_discount_cents": 0},
    )
    anchor = fixtures.create_streaming_subscription(api, customer, p8,
                                                    auto_renew=False)

    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step["id"], "customer_id": customer["id"],
         "radio_id": radio["id"]},
        fixtures.customer_headers(customer),
    )
    redemption = validate_success(resp, expected_status=201)
    assert redemption["redeemed_price_cents"] == 3600, (
        f"expected 3600 (offer-then-family), got {redemption['redeemed_price_cents']}"
    )

    redeemed_sub = validate_success(
        api.get_subscription(redemption["subscription_id"], ADMIN_HEADERS)
    )
    assert redeemed_sub["current_term_price_cents"] == 3600

    anchor_now = validate_success(api.get_subscription(anchor["id"], ADMIN_HEADERS))
    assert anchor_now["is_primary_for_discount"] is True


def test_term_pricing_list_price_variant_when_no_discounts(api):
    """PRD §3.3: "When no offer redemption applies and the subscription is not
    family-eligible, the list-price variant holds: the term price is the plan's
    `price_cents` verbatim."

    Design: Difficulty/combinatorial_formula/term_pricing_offer_then_family_order_pinned
    """
    customer = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=6000)
    sub = fixtures.create_streaming_subscription(api, customer, plan,
                                                 auto_renew=False)
    assert sub["current_term_price_cents"] == 6000


def test_offer_step_pricing_per_step_rounding_before_flat(api):
    """PRD §3.7: "A successful redemption prices the step in isolation — floor
    of the plan's `price_cents` times `discount_pct_bps` over ten thousand,
    then minus `flat_discount_cents`, floored at zero, rounded per step and
    never summed-then-rounded".

    Plan 5999 with pct 3333 bps and flat 1000: floor(5999*3333/10000) = 1999;
    5999 - 1999 - 1000 = 3000. Flat-before-pct would give 3332 and a
    round-half-up pct step would give 2999 — both forbidden orders.

    Design: Difficulty/combinatorial_formula/offer_step_pricing_per_step_rounding_before_flat
    """
    customer, plan, campaign, step, _ = _setup_offer_pricing_world(
        api, price_cents=5999, pct_bps=3333, flat_cents=1000
    )
    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step["id"], "customer_id": customer["id"]},
        fixtures.customer_headers(customer),
    )
    redemption = validate_success(resp, expected_status=201)
    assert redemption["redeemed_price_cents"] == 3000, (
        f"expected 3000, got {redemption['redeemed_price_cents']}"
    )


def test_offer_step_pricing_flat_cannot_push_below_zero(api):
    """PRD §3.7: "then minus `flat_discount_cents`, floored at zero".

    A 3000-cent plan with a 100-percent step (10000 bps) plus a 500-cent flat
    discount floors at 0, never negative.

    Design: Difficulty/combinatorial_formula/offer_step_pricing_per_step_rounding_before_flat
    """
    customer, plan, campaign, step, _ = _setup_offer_pricing_world(
        api, price_cents=3000, pct_bps=10000, flat_cents=500
    )
    resp = api.redeem_offer(
        campaign["id"],
        {"offer_step_id": step["id"], "customer_id": customer["id"]},
        fixtures.customer_headers(customer),
    )
    redemption = validate_success(resp, expected_status=201)
    assert redemption["redeemed_price_cents"] == 0
