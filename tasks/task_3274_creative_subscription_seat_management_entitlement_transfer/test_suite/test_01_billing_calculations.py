"""Billing dual-variant and rounding-order tests (depth queue A)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_reseller,
    create_subscription,
    activate_subscription,
    create_cancellation_request,
    get_subscription,
    set_clock,
    validate_success,
    validate_error,
    get_success_data,
    make_org_admin_headers,
)


def _etf_setup(api):
    """Org + ENTERPRISE annual plan (etf 50, window 14) + PLATINUM reseller +
    activated 10-seat subscription via the reseller + PENDING cancellation.

    monthly_charge_cents: floor(4999*85/100)=4249 per seat * 10 = 42490.
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O1", org_type="ENTERPRISE", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa1@o1.com", full_name="Admin One",
                         admin_kind="SYSTEM_ADMIN")
    plan = create_plan(
        code="P1-ETF", segment="ENTERPRISE", billing_model="ANNUAL_MONTHLY_BILLED",
        monthly_price_cents=5999, annual_monthly_price_cents=4999,
        storage_gb_per_seat=100, seat_limit=-1, deployment_modes=["NAMED_USER"],
        allows_offline_activation=False, max_devices_per_seat=2,
        cancellation_window_days=14, etf_rate_pct=50)
    create_product_version(plan["id"])
    reseller = create_reseller(name="R1", region="NA", tier="PLATINUM")
    sub = create_subscription(org["id"], plan["id"], seats_purchased=10,
                              reseller_id=reseller["id"])
    sub = activate_subscription(sub["id"])
    cr = create_cancellation_request(sub["id"], admin["id"],
                                     make_org_admin_headers(admin["id"]))
    return org, admin, plan, reseller, sub, cr


def test_etf_in_window_finalization_refunds_with_zero_fee(api):
    """PRD: "Finalization within the plan's cancellation window — the logical
    clock being no later than `commitment_start` plus `cancellation_window_days`
    days — moves the subscription `ACTIVE → CANCELLED_IN_WINDOW` and the request
    to `REFUNDED` with `etf_amount_cents` set to zero: a full refund, no fee."

    Design: Difficulty/dual_variant_calc/etf_in_window_vs_out_of_window_same_plan
    """
    org, admin, plan, reseller, sub, cr = _etf_setup(api)
    set_clock("2026-09-10T00:00:00Z")
    resp = api.finalize_cancellation_request(cr["id"], SYS)
    data = validate_success(resp)
    assert data["status"] == "REFUNDED"
    assert data["etf_amount_cents"] == 0
    sub_after = get_subscription(sub["id"])
    assert sub_after["status"] == "CANCELLED_IN_WINDOW", (
        f"Expected CANCELLED_IN_WINDOW, got {sub_after['status']}")


def test_etf_out_of_window_finalization_charges_tiered_fee(api):
    """PRD: "the remaining months are the `commitment_months` (twelve for annual
    plans) minus `months_elapsed`; the remaining value is the remaining months
    multiplied by the subscription's `monthly_charge_cents`; and the fee is that
    remaining value multiplied by the plan's `etf_rate_pct`, divided by one
    hundred, and rounded down to a whole cent."

    At clock 2027-02-16, 5 full months have elapsed since the 2026-09-01
    commitment start: fee = floor(7 * 42490 * 50 / 100) = 148715 cents.

    Design: Difficulty/dual_variant_calc/etf_in_window_vs_out_of_window_same_plan
    """
    org, admin, plan, reseller, sub, cr = _etf_setup(api)
    assert sub["monthly_charge_cents"] == 42490
    set_clock("2027-02-16T00:00:00Z")
    resp = api.finalize_cancellation_request(cr["id"], SYS)
    data = validate_success(resp)
    assert data["status"] == "ETF_CHARGED"
    assert data["etf_amount_cents"] == 148715, (
        f"Expected ETF 148715 cents, got {data['etf_amount_cents']}")
    sub_after = get_subscription(sub["id"])
    assert sub_after["status"] == "CANCELLED_ETF", (
        f"Expected CANCELLED_ETF, got {sub_after['status']}")


def _discount_setup(api):
    """TEAM org with MONTHLY plan 5999; one direct 4-seat sub and one
    GOLD-routed 4-seat sub, both activated."""
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O2", org_type="TEAM", primary_admin_id=ba0["id"])
    plan = create_plan(
        code="P2-DISC", segment="TEAM", billing_model="MONTHLY",
        monthly_price_cents=5999, annual_monthly_price_cents=5999,
        storage_gb_per_seat=20, seat_limit=-1, deployment_modes=["NAMED_USER"],
        allows_offline_activation=False, max_devices_per_seat=2,
        cancellation_window_days=14, etf_rate_pct=0)
    create_product_version(plan["id"])
    reseller = create_reseller(name="R2", region="EMEA", tier="GOLD")
    direct = activate_subscription(
        create_subscription(org["id"], plan["id"], seats_purchased=4)["id"])
    routed = activate_subscription(
        create_subscription(org["id"], plan["id"], seats_purchased=4,
                            reseller_id=reseller["id"])["id"])
    return org, plan, reseller, direct, routed


def test_direct_subscription_charges_full_price(api):
    """PRD: "The discount percentage is 0 when the subscription's `reseller_id`
    is null (the direct variant, where the per-seat price equals the base)"

    Direct: 5999 per seat x 4 seats = 23996 cents.

    Design: Difficulty/dual_variant_calc/reseller_discount_direct_vs_gold_charge
    """
    org, plan, reseller, direct, routed = _discount_setup(api)
    data = get_subscription(direct["id"])
    assert data["monthly_charge_cents"] == 23996, (
        f"Expected 23996, got {data['monthly_charge_cents']}")


def test_gold_routed_subscription_charges_discounted_price(api):
    """PRD: "otherwise follows the reseller's tier: 5 for `CERTIFIED`, 10 for
    `GOLD`, 15 for `PLATINUM`. The discounted per-seat price is the base
    multiplied by one hundred minus the discount percentage, divided by one
    hundred, and rounded down to a whole cent"

    GOLD: floor(5999*90/100)=5399 per seat x 4 = 21596 cents.

    Design: Difficulty/dual_variant_calc/reseller_discount_direct_vs_gold_charge
    """
    org, plan, reseller, direct, routed = _discount_setup(api)
    data = get_subscription(routed["id"])
    assert data["monthly_charge_cents"] == 21596, (
        f"Expected 21596, got {data['monthly_charge_cents']}")


def test_monthly_charge_per_seat_floor_then_multiply(api):
    """PRD: "The rounding order is pinned: per-seat floor first, then multiply
    by seats."

    annual 4999 with PLATINUM 15%: floor(4999*85/100)=4249 per seat, x10 =
    42490. The opposite order (floor(49990*85/100)=42491) differs by 1 cent.

    Design: Difficulty/combinatorial_formula/monthly_charge_per_seat_floor_then_multiply_rounding_order
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O1R", org_type="ENTERPRISE", primary_admin_id=ba0["id"])
    plan = create_plan(
        code="P1-ROUND", segment="ENTERPRISE", billing_model="ANNUAL_MONTHLY_BILLED",
        monthly_price_cents=5999, annual_monthly_price_cents=4999,
        storage_gb_per_seat=100, seat_limit=-1, deployment_modes=["NAMED_USER"],
        allows_offline_activation=False, max_devices_per_seat=2,
        cancellation_window_days=14, etf_rate_pct=50)
    create_product_version(plan["id"])
    reseller = create_reseller(name="R1R", region="NA", tier="PLATINUM")
    sub = create_subscription(org["id"], plan["id"], seats_purchased=10,
                              reseller_id=reseller["id"])
    resp = api.activate_subscription(sub["id"], SYS)
    data = validate_success(resp)
    assert data["monthly_charge_cents"] == 42490, (
        f"Per-seat floor then multiply must give 42490, got "
        f"{data['monthly_charge_cents']}")


def test_monthly_charge_is_stamped_at_activation(api):
    """PRD: "Upon activation the system stamps `commitment_start` with the
    current logical clock, sets `commitment_months` to 1 for a `MONTHLY` plan
    and 12 for either annual billing model, computes `monthly_charge_cents` per
    the billing calculation below"

    Before activation monthly_charge_cents is 0; activation computes it and
    sets commitment_months to 12 for an annual plan.

    Design: Difficulty/combinatorial_formula/monthly_charge_per_seat_floor_then_multiply_rounding_order
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O1S", org_type="ENTERPRISE", primary_admin_id=ba0["id"])
    plan = create_plan(
        code="P1-STAMP", segment="ENTERPRISE", billing_model="ANNUAL_MONTHLY_BILLED",
        monthly_price_cents=5999, annual_monthly_price_cents=4999,
        storage_gb_per_seat=100, seat_limit=-1, deployment_modes=["NAMED_USER"],
        allows_offline_activation=False, max_devices_per_seat=2,
        cancellation_window_days=14, etf_rate_pct=50)
    create_product_version(plan["id"])
    reseller = create_reseller(name="R1S", region="NA", tier="PLATINUM")
    sub = create_subscription(org["id"], plan["id"], seats_purchased=10,
                              reseller_id=reseller["id"])
    assert sub["monthly_charge_cents"] == 0
    activated = activate_subscription(sub["id"])
    assert activated["monthly_charge_cents"] == 42490
    assert activated["commitment_months"] == 12
    assert activated["commitment_start"] is not None
