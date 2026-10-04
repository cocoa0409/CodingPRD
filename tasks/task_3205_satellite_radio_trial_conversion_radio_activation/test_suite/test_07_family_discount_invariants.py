"""Family-discount conservation: the anchor swap moves, never multiplies."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.fixtures import ADMIN


def test_family_discount_total_conservation_on_anchor_swap(api):
    """PRD §3.3: "The anchor is the candidate whose plan has the highest base
    `price_cents`, with ties broken by the earliest `created_at`; the anchor's
    `is_primary_for_discount` becomes true and every other candidate's becomes
    false. Non-anchor candidates receive the 25 percent family discount when
    `household_size` is at least 2. When the anchor itself is cancelled,
    transferred, or expired, the next-highest subscription becomes the anchor
    and **loses** its discount".

    Three streaming subs (8000/6000/4000 annual): exactly one anchor and N-1
    discounted subs before the swap; after cancelling the 8000 anchor the
    6000 sub becomes anchor at full price and the 4000 sub keeps its
    discount — the discount grant moved, it did not multiply.

    Design: Difficulty/compensating_invariant/family_discount_total_conservation_on_anchor_swap
    """
    customer = fixtures.create_customer(api, household_size=2)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    pa8 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=8000, auto_renew_default=False,
    )
    pb6 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=6000, auto_renew_default=False,
    )
    pc4 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=4000, auto_renew_default=False,
    )

    sub_a = fixtures.create_streaming_subscription(api, customer, pa8,
                                                   auto_renew=False)
    sub_b = fixtures.create_streaming_subscription(api, customer, pb6,
                                                   auto_renew=False)
    sub_c = fixtures.create_streaming_subscription(api, customer, pc4,
                                                   auto_renew=False)

    sub_a = validate_success(api.get_subscription(sub_a["id"], ADMIN))
    sub_b = validate_success(api.get_subscription(sub_b["id"], ADMIN))
    sub_c = validate_success(api.get_subscription(sub_c["id"], ADMIN))

    primaries = [s for s in (sub_a, sub_b, sub_c) if s["is_primary_for_discount"]]
    assert len(primaries) == 1 and primaries[0]["id"] == sub_a["id"]
    assert sub_b["current_term_price_cents"] == 4500
    assert sub_c["current_term_price_cents"] == 3000
    # no anchor ever carries a discounted price
    assert sub_a["current_term_price_cents"] == 8000

    headers = fixtures.customer_headers(customer)
    validate_success(
        api.cancel_subscription(sub_a["id"], {"effective_mode": "IMMEDIATE"},
                                headers)
    )

    sub_b2 = validate_success(api.get_subscription(sub_b["id"], ADMIN))
    sub_c2 = validate_success(api.get_subscription(sub_c["id"], ADMIN))
    assert sub_b2["is_primary_for_discount"] is True
    assert sub_c2["is_primary_for_discount"] is False
    assert sub_b2["current_term_price_cents"] == 6000
    assert sub_c2["current_term_price_cents"] == 3000


def test_family_discount_absent_for_single_sub_households(api):
    """PRD §3.3: "the family discount is the ceiling of one quarter — 2500
    basis points — of the base price after the offer discount" only "when the
    subscription is not the customer's primary anchor, the customer's
    `household_size` is at least 2".

    A household-1 customer holding two paid subs gets no discount on the
    non-anchor sub: list price verbatim.

    Design: Difficulty/compensating_invariant/family_discount_total_conservation_on_anchor_swap
    """
    customer = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    p8 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=8000, auto_renew_default=False,
    )
    p6 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=6000, auto_renew_default=False,
    )
    fixtures.create_streaming_subscription(api, customer, p8, auto_renew=False)
    sub_b = fixtures.create_streaming_subscription(api, customer, p6,
                                                   auto_renew=False)
    sub_b = validate_success(api.get_subscription(sub_b["id"], ADMIN))
    assert sub_b["is_primary_for_discount"] is False
    assert sub_b["current_term_price_cents"] == 6000
