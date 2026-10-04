"""Purchase pricing: tier discount ordering, proration, week anchoring."""
from test_helpers import (
    CLOCK_DEFAULT,
    create_grant,
    create_offer,
    create_season,
    create_student_verification,
    make_subscriber_headers,
    register_account,
    set_clock,
    validate_success,
)


def _student_setup(base_price_cents=9999, student_discount_pct=10,
                   regular_season_weeks=17, email="stu@x.com"):
    set_clock(CLOCK_DEFAULT)
    grant = create_grant()
    season = create_season(
        grant["id"],
        regular_season_weeks=regular_season_weeks,
        season_start_date="2026-08-05T00:00:00Z",
        season_end_date="2026-12-02T00:00:00Z",
        grace_days=7,
        student_discount_pct=student_discount_pct,
    )
    offer = create_offer(season["id"], plan_tier="STUDENT",
                         base_price_cents=base_price_cents)
    account = register_account(email=email, full_name="Stu Dent",
                               billing_zip="10001")
    create_student_verification(account["id"])
    return season, offer, account


def test_student_tier_base_computed_before_proration(api):
    """PRD §3.5: "the student discount applies to the full-season base *before*
    proration (step 1 before step 2), and reversing the order changes the
    result whenever the discount percent produces a fractional cent."

    Design: Difficulty/dual_variant_calc/charged_price_discount_before_proration_ordering
    """
    _, offer, account = _student_setup()
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    # PRD §3.5: weeks received = regular_season_weeks - purchase_week_index + 1
    # = 17 - 4 + 1 = 14 (buyer receives weeks 4..17 inclusive).
    # Step 1 (discount first): round_half_up(9999 * 90/100) = 8999.
    # Step 2 (prorate): round_half_up(8999 * 14/17) = round_half_up(7411.06) = 7411.
    assert sub["purchase_week_index"] == 4
    assert sub["price_charged_cents"] == 7411, (
        f"expected 7411 (discount-then-prorate), got {sub['price_charged_cents']}"
    )

    # Ordering discrimination: with base 9998 the two orders diverge.
    # Forward: round_half_up(9998*90/100)=8998; round_half_up(8998*14/17)=7410.
    # Reversed: round_half_up(9998*14/17)=8234; round_half_up(8234*90/100)=7411.
    _, offer2, account2 = _student_setup(base_price_cents=9998,
                                         email="stu2@x.com")
    sub2 = validate_success(
        api.create_subscription(account2["id"], offer2["id"],
                                make_subscriber_headers(account2["id"])),
        expected_status=201,
    )
    assert sub2["price_charged_cents"] == 7410, (
        f"expected 7410 (discount-then-prorate), got {sub2['price_charged_cents']}"
    )
    assert sub2["price_charged_cents"] != 7411


def test_student_purchase_records_week_four_purchase_index(api):
    """PRD §3.5: "The purchase week index — stored as `purchase_week_index` —
    is the 1-based season week containing the logical-clock purchase instant,
    clamped so that a purchase before week 1 counts as week 1 and a purchase
    beyond the final week counts as the final week."

    Design: Difficulty/dual_variant_calc/charged_price_discount_before_proration_ordering
    """
    _, offer, account = _student_setup()
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    # Clock at 2026-09-01T00:00:00Z falls in week 4 of a season starting
    # 2026-08-05 (weeks 1-3 cover 08-05..08-25, week 4 covers 08-26..09-01).
    assert sub["purchase_week_index"] == 4
    assert sub["status"] == "PENDING_PAYMENT"
    assert sub["plan_tier"] == "STUDENT"


def _premium_setup(base_price_cents=30000):
    set_clock(CLOCK_DEFAULT)
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], plan_tier="PREMIUM",
                         base_price_cents=base_price_cents,
                         includes_multiview=True, includes_companion=True)
    account = register_account(email="prem@x.com", full_name="Prem Ium",
                               billing_zip="10001")
    return season, offer, account


def test_premium_week_four_proration_exact_cents(api, platform_admin_headers):
    """PRD §3.5: "multiply by the count of weeks the buyer receives — the
    season's `regular_season_weeks` minus the purchase week index plus one,
    since a buyer in week *p* receives weeks *p* through the final week
    inclusive — then divide by `regular_season_weeks` and round half-up to a
    whole cent."

    Design: Difficulty/combinatorial_formula/charged_price_circular_evaluation_order_pinned
    """
    _, offer, account = _premium_setup()
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    # round_half_up(30000 * (18 - 4 + 1) / 18) = round_half_up(25000.0) = 25000.
    assert sub["price_charged_cents"] == 25000
    assert sub["purchase_week_index"] == 4
    assert sub["plan_tier"] == "PREMIUM"


def test_premium_plan_tier_snapshot_survives_offer_withdrawal(
    api, platform_admin_headers
):
    """PRD §3.5: "An offer is born `ACTIVE` and may be withdrawn, moving to
    `WITHDRAWN`; withdrawal rejects new purchases but leaves existing
    subscriptions' snapshots untouched."

    Design: Difficulty/combinatorial_formula/charged_price_circular_evaluation_order_pinned
    """
    _, offer, account = _premium_setup()
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    validate_success(api.withdraw_offer(offer["id"], platform_admin_headers))
    reread = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert reread["plan_tier"] == "PREMIUM"
    assert reread["price_charged_cents"] == 25000
