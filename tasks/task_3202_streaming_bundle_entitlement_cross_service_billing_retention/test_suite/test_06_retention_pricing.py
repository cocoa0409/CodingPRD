"""Retention offers, redemptions, eligibility, and effective-price coverage."""
from test_helpers import (
    TEST_USERS,
    create_retention_offer,
    get_account,
    get_subscription,
    redeem_offer,
    run_renewal,
    set_clock,
    setup_active_standalone_subscription,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]


def test_retention_price_stacking_cap_and_floor(api):
    """PRD §3.5: "Over that base, the discounts of every ACTIVE retention
    redemption on the subscription are summed — but the total discount may not
    exceed 60 percent of the base, floored to whole cents, so the applied
    discount is the smaller of the raw sum and that cap. The price is the base
    minus the applied discount, recorded on the subscription as
    retention_discount_cents and price_cents respectively."
    PRD §3.10: "A successful redemption starts ACTIVE with months_remaining
    initialized to the offer's duration_months, and the subscription's
    retention_discount_cents and price_cents are recomputed per §3.5."

    Design: Difficulty/combinatorial_formula/retention_price_stacking_cap_and_floor
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cf1@x.com"
    )
    create_retention_offer(
        offer_code="BIGSAVE", discount_cents=600, duration_months=2,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redemption = redeem_offer(sub["id"], "BIGSAVE", hdrs)
    assert redemption["months_remaining"] == 2
    after = get_subscription(sub["id"], hdrs)
    # Raw discount 600 exceeds the cap floor(799 * 60 / 100) = 479.
    assert after["retention_discount_cents"] == 479, (
        f"cap binds at 479, got {after['retention_discount_cents']}"
    )
    assert after["price_cents"] == 320, (
        f"price must be 799 - 479 = 320, got {after['price_cents']}"
    )


def test_retention_cap_applies_to_grandfathered_base(api):
    """PRD §3.5: "The base is the account's grandfathered_price_cents whenever
    the account's grandfathered_plan_code equals the subscription's current
    plan_code and the lock is set; otherwise the base is the plan's
    monthly_price_cents."
    PRD §3.5: "Over that base, the discounts of every ACTIVE retention
    redemption on the subscription are summed — but the total discount may not
    exceed 60 percent of the base, floored to whole cents, so the applied
    discount is the smaller of the raw sum and that cap."

    Design: Difficulty/combinatorial_formula/retention_price_stacking_cap_and_floor
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cf1b@x.com"
    )
    # Grandfathered lock is 799 (== plan list price here); a discount exactly
    # at the cap boundary floor(799*0.6) = 479 applies uncapped.
    create_retention_offer(
        offer_code="CAP479", discount_cents=479, duration_months=2,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redeem_offer(sub["id"], "CAP479", hdrs)
    after = get_subscription(sub["id"], hdrs)
    assert after["retention_discount_cents"] == 479
    assert after["price_cents"] == 320


def test_grandfathered_lock_evaluation_order_on_activation(api):
    """PRD §3.5: "First, if the account's grandfathered_price_cents is still
    null, the lock is written: grandfathered_plan_code becomes the activating
    subscription's plan code and grandfathered_price_cents becomes that plan's
    current monthly_price_cents list price. Only after the lock is written is
    the subscription's price_cents computed."
    PRD §3.5: "The base is the account's grandfathered_price_cents whenever
    the account's grandfathered_plan_code equals the subscription's current
    plan_code and the lock is set; otherwise the base is the plan's
    monthly_price_cents."

    Design: Difficulty/combinatorial_formula/grandfathered_lock_evaluation_order_on_activation
    """
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cf3@x.com"
    )
    acct = get_account(account["id"], hdrs)
    assert acct["grandfathered_price_cents"] == 799
    assert acct["grandfathered_plan_code"] == "DPLUS_ADS"
    redeem_offer(sub["id"], "SMALL100", hdrs)
    after = get_subscription(sub["id"], hdrs)
    assert after["price_cents"] == 699
    assert after["retention_discount_cents"] == 100


def test_lock_written_before_price_computed_on_first_activation(api):
    """PRD §3.5: "First, if the account's grandfathered_price_cents is still
    null, the lock is written: grandfathered_plan_code becomes the activating
    subscription's plan code and grandfathered_price_cents becomes that plan's
    current monthly_price_cents list price. Only after the lock is written is
    the subscription's price_cents computed."
    PRD §3.5: "The first time any subscription of an account reaches ACTIVE,
    the grandfathered price lock engages — and the evaluation order is pinned,
    because the subscription's own price depends on the lock that the
    activation itself creates."

    Design: Difficulty/combinatorial_formula/grandfathered_lock_evaluation_order_on_activation
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cf3b@x.com"
    )
    # Create response already reflects lock-then-price ordering.
    assert sub["price_cents"] == 799
    assert sub["retention_discount_cents"] == 0
    acct = get_account(account["id"], hdrs)
    assert acct["grandfathered_price_cents"] == 799
    assert acct["grandfathered_plan_code"] == "DPLUS_ADS"


def test_retention_min_price_floor_binds(api):
    """PRD §3.5: "Finally, a floor rule: the effective price may not fall
    below 100 cents; if it would, the price is pinned to 100 cents and the
    recorded discount is reduced to the base minus 100."

    Design: Corner/calculations/retention_min_price_floor_binds
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        plan_code="CHEAP150", price=150, email="calc5@x.com"
    )
    create_retention_offer(
        offer_code="HUGE200", discount_cents=200, duration_months=2,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redeem_offer(sub["id"], "HUGE200", hdrs)
    after = get_subscription(sub["id"], hdrs)
    # Cap floor(150*60/100)=90 would price at 60 < 100, so the floor pins the
    # price at 100 and the recorded discount is 150 - 100 = 50.
    assert after["price_cents"] == 100
    assert after["retention_discount_cents"] == 50


def test_retention_cap_count_equal_to_max_rejected(api):
    """PRD §3.10: "the count of this offer's redemptions on this account in
    ACTIVE or EXPIRED status must be strictly below
    max_redemptions_per_account — VOIDED redemptions do not count, so an
    account at one below the cap succeeds while one at the cap fails; and no
    other redemption on this same subscription may be ACTIVE."
    PRD §3.10: "Each successful renewal of the host subscription decrements
    months_remaining by 1; when a decrement brings it to exactly 0 the
    redemption moves to EXPIRED and the subscription's discount and price are
    recomputed."

    Design: Difficulty/boundary_precision_check/retention_cap_count_equal_to_max_rejected
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="bp3@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=1,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redemption = redeem_offer(sub["id"], "SMALL100", hdrs)
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "SUCCEEDED")
    reds = validate_success(api.list_subscription_redemptions(sub["id"], hdrs), 200)
    target = [r for r in reds if r["id"] == redemption["id"]][0]
    assert target["redemption_status"] == "EXPIRED"
    resp = api.redeem_retention_offer(sub["id"], {"offer_code": "SMALL100"}, hdrs)
    validate_error(resp, "ERR_RETENTION_NOT_ELIGIBLE", 422)


def test_retention_one_below_cap_succeeds(api):
    """PRD §3.10: "the count of this offer's redemptions on this account in
    ACTIVE or EXPIRED status must be strictly below
    max_redemptions_per_account — VOIDED redemptions do not count, so an
    account at one below the cap succeeds while one at the cap fails; and no
    other redemption on this same subscription may be ACTIVE."
    PRD §3.10: "Each successful renewal of the host subscription decrements
    months_remaining by 1; when a decrement brings it to exactly 0 the
    redemption moves to EXPIRED and the subscription's discount and price are
    recomputed."

    Design: Difficulty/boundary_precision_check/retention_cap_count_equal_to_max_rejected
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="bp3b@x.com"
    )
    create_retention_offer(
        offer_code="CAP2", discount_cents=100, duration_months=1,
        max_redemptions_per_account=2,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redeem_offer(sub["id"], "CAP2", hdrs)
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "SUCCEEDED")  # first redemption expires
    # count(ACTIVE+EXPIRED) == 1 < max 2: the second redemption succeeds.
    second = api.redeem_retention_offer(sub["id"], {"offer_code": "CAP2"}, hdrs)
    validate_success(second, 201)


def test_retention_redemption_duration_overlap_gate(api):
    """PRD §3.10: "Redeeming an offer against a subscription is a six-clause
    conjunction, and any failure is ERR_RETENTION_NOT_ELIGIBLE (HTTP 422): the
    offer must be OPEN; the subscription's lifecycle must be ACTIVE — not
    PAST_DUE, not CANCEL_SCHEDULED; the billing account's biller_type must
    appear in eligible_biller_types; the plan's plan_kind must appear in
    eligible_plan_kinds; the count of this offer's redemptions on this account
    in ACTIVE or EXPIRED status must be strictly below
    max_redemptions_per_account — VOIDED redemptions do not count, so an
    account at one below the cap succeeds while one at the cap fails; and no
    other redemption on this same subscription may be ACTIVE."
    PRD §3.10: "and no other redemption on this same subscription may be
    ACTIVE."
    PRD §3.10: "Each successful renewal of the host subscription decrements
    months_remaining by 1; when a decrement brings it to exactly 0 the
    redemption moves to EXPIRED and the subscription's discount and price are
    recomputed."

    Design: Difficulty/resource_temporal_overlap/retention_redemption_duration_overlap_gate
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="ov2@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=1,
        max_redemptions_per_account=5,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    create_retention_offer(
        offer_code="OTHER50", discount_cents=50, duration_months=2,
        max_redemptions_per_account=5,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    red1 = redeem_offer(sub["id"], "SMALL100", hdrs)
    blocked = api.redeem_retention_offer(sub["id"], {"offer_code": "OTHER50"}, hdrs)
    validate_error(blocked, "ERR_RETENTION_NOT_ELIGIBLE", 422)
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "SUCCEEDED")
    reds = validate_success(api.list_subscription_redemptions(sub["id"], hdrs), 200)
    first = [r for r in reds if r["id"] == red1["id"]][0]
    assert first["redemption_status"] == "EXPIRED"
    resp = api.redeem_retention_offer(sub["id"], {"offer_code": "OTHER50"}, hdrs)
    red2 = validate_success(resp, 201)
    assert red2["months_remaining"] == 2
    after = get_subscription(sub["id"], hdrs)
    assert after["price_cents"] == 749


def test_retention_slot_blocked_even_for_different_offer(api):
    """PRD §3.10: "Redeeming an offer against a subscription is a six-clause
    conjunction, and any failure is ERR_RETENTION_NOT_ELIGIBLE (HTTP 422): the
    offer must be OPEN; the subscription's lifecycle must be ACTIVE — not
    PAST_DUE, not CANCEL_SCHEDULED; the billing account's biller_type must
    appear in eligible_biller_types; the plan's plan_kind must appear in
    eligible_plan_kinds; the count of this offer's redemptions on this account
    in ACTIVE or EXPIRED status must be strictly below
    max_redemptions_per_account — VOIDED redemptions do not count, so an
    account at one below the cap succeeds while one at the cap fails; and no
    other redemption on this same subscription may be ACTIVE."
    PRD §3.10: "and no other redemption on this same subscription may be
    ACTIVE."

    Design: Difficulty/resource_temporal_overlap/retention_redemption_duration_overlap_gate
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="ov2b@x.com"
    )
    create_retention_offer(
        offer_code="A100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=5,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    create_retention_offer(
        offer_code="B50", discount_cents=50, duration_months=2,
        max_redemptions_per_account=5,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redeem_offer(sub["id"], "A100", hdrs)
    resp = api.redeem_retention_offer(sub["id"], {"offer_code": "B50"}, hdrs)
    validate_error(resp, "ERR_RETENTION_NOT_ELIGIBLE", 422)
    after = get_subscription(sub["id"], hdrs)
    # Only the first discount applies.
    assert after["retention_discount_cents"] == 100
    assert after["price_cents"] == 699


def test_retention_offer_retired_rejects_new_redemption(api):
    """PRD §3.10: "Offers default to OPEN; a RETIRED offer rejects new
    redemptions but never disturbs existing ones."
    PRD §3.10: "Redeeming an offer against a subscription is a six-clause
    conjunction, and any failure is ERR_RETENTION_NOT_ELIGIBLE (HTTP 422): the
    offer must be OPEN; the subscription's lifecycle must be ACTIVE — not
    PAST_DUE, not CANCEL_SCHEDULED; the billing account's biller_type must
    appear in eligible_biller_types; the plan's plan_kind must appear in
    eligible_plan_kinds; the count of this offer's redemptions on this account
    in ACTIVE or EXPIRED status must be strictly below
    max_redemptions_per_account — VOIDED redemptions do not count, so an
    account at one below the cap succeeds while one at the cap fails; and no
    other redemption on this same subscription may be ACTIVE."

    Design: Corner/errors/retention_offer_retired_rejects_new_redemption
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="err2@x.com"
    )
    create_retention_offer(
        offer_code="OLD50", discount_cents=50, duration_months=1,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
        offer_status="RETIRED",
    )
    create_retention_offer(
        offer_code="NEW50", discount_cents=50, duration_months=1,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    retired = api.redeem_retention_offer(sub["id"], {"offer_code": "OLD50"}, hdrs)
    validate_error(retired, "ERR_RETENTION_NOT_ELIGIBLE", 422)
    ok = api.redeem_retention_offer(sub["id"], {"offer_code": "NEW50"}, hdrs)
    validate_success(ok, 201)
    assert get_subscription(sub["id"], hdrs)["price_cents"] == 749


def test_immediate_consistency_visible_in_same_response(api):
    """PRD §3.10: "A successful redemption starts ACTIVE with months_remaining
    initialized to the offer's duration_months, and the subscription's
    retention_discount_cents and price_cents are recomputed per §3.5."
    PRD §3.5: "This recomputation runs whenever a retention redemption is
    created, expires, or is voided, whenever the grandfathered lock changes,
    and on every plan change."

    Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cm1@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redeem_offer(sub["id"], "SMALL100", hdrs)
    after = validate_success(api.get_subscription(sub["id"], hdrs), 200)
    assert after["price_cents"] == 699
    assert after["retention_discount_cents"] == 100
