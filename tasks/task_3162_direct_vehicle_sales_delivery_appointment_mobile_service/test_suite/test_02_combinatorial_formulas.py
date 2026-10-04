"""Combinatorial formulas: nested rounding order, tier selection and bundle caps."""
from test_helpers import (
    MAX_BUNDLE_DISCOUNT_CENTS,
    cover_order_total,
    get_order,
    TEST_USERS,
    create_entitlements,
    create_financing_application_payload,
    get_success_data,
    make_buyer_headers,
    set_clock,
    setup_vehicle_with_entitlements,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]


class TestFinancingAnnuity:
    """PRD §3.5: the monthly payment is the standard annuity at the tiered rate."""

    def test_decision_selects_the_long_term_near_prime_tier(self, api):
        """PRD §3.5: "the applicant's existing `credit_band` is retained when it is
        already `PRIME` or `SUBPRIME`, and otherwise the band defaults to
        `NEAR_PRIME` — notably, an existing band of `NEAR_PRIME` and an existing
        band of `UNRATED` both resolve to `NEAR_PRIME`"
        PRD §3.5: "a `NEAR_PRIME` applicant with a term of 49 months or more
        receives 890 basis points"
        PRD §3.5: "Approval moves the application to `CONDITIONALLY_APPROVED` with
        `apr_bps`, `credit_band`, and `monthly_payment_cents` all written."

        Design: Difficulty/combinatorial_formula/financing_annuity_nested_rounding_order
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center(options=[
            {"option_sku": "PAINT_WHITE", "option_category": "PAINT",
             "price_cents": 100000}])
        # The provisional total grows by the priced option at allocation, and the
        # fee has to cover that recomputed total (PRD 3.7) for the application's
        # principal to be derived from it below.
        cover_order_total(ctx["order"]["id"])
        order = get_order(ctx["order"]["id"])

        application = get_success_data(api.create_financing_application(
            order["id"],
            create_financing_application_payload(
                term_months=60, down_payment_cents=500000,
                include_trade_in_credit=False),
            make_buyer_headers(ctx["buyer"]["id"])))

        # The financed principal is the provisional total less the down payment.
        assert application["amount_financed_cents"] == order["order_total_due_cents"] - 500000

        decided = get_success_data(api.decide_financing_application(
            application["id"], "APPROVED", FINANCE))
        assert decided["status"] == "CONDITIONALLY_APPROVED"
        assert decided["credit_band"] == "NEAR_PRIME", (
            "an UNRATED applicant defaults to NEAR_PRIME"
        )

    def test_monthly_payment_matches_the_annuity_at_890_bps(self, api):
        """PRD §3.5: "The monthly payment is the standard annuity for the financed
        principal at that rate: convert the basis-point rate to a monthly rate by
        dividing it by 10000 and then by 12, take the financed principal
        multiplied by that monthly rate divided by one minus the quantity one plus
        the monthly rate raised to the negative of the term in months, and round
        the quotient half up to a whole cent exactly once at the end."
        PRD §3.5: "a `NEAR_PRIME` applicant with a term of 49 months or more
        receives 890 basis points"

        Design: Difficulty/combinatorial_formula/financing_annuity_nested_rounding_order
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center(options=[
            {"option_sku": "PAINT_WHITE", "option_category": "PAINT",
             "price_cents": 100000}])
        cover_order_total(ctx["order"]["id"])
        application = get_success_data(api.create_financing_application(
            ctx["order"]["id"],
            create_financing_application_payload(
                term_months=60, down_payment_cents=500000,
                include_trade_in_credit=False),
            make_buyer_headers(ctx["buyer"]["id"])))
        decided = get_success_data(api.decide_financing_application(
            application["id"], "APPROVED", FINANCE))

        assert decided["apr_bps"] == 890, "NEAR_PRIME with a 60-month term is the long tier"

        principal = decided["amount_financed_cents"]
        monthly_rate = 890 / 10000 / 12
        expected = round(principal * monthly_rate
                         / (1 - (1 + monthly_rate) ** (-60)))
        assert decided["monthly_payment_cents"] == expected, (
            "the annuity is rounded exactly once, at the end"
        )


class TestEntitlementBundlePricing:
    """PRD §3.11: the bundle is priced collectively, and the pinned order matters."""

    def test_bundle_cap_applies_to_the_whole_bundle_before_the_per_row_split(self, api):
        """PRD §3.11: "Third, the gross discount is that raw total multiplied by
        the tier rate and then divided by 10000, and the applied discount is the
        smaller of the gross discount and the 200000-cent cap."
        PRD §3.11: "Because the truncations do not sum exactly, the residual — the
        bundle net total less the sum of the truncated shares — is added to the
        last row, so the per-row shares always reconcile to the bundle total
        exactly."

        Design: Difficulty/combinatorial_formula/entitlement_bundle_cap_then_per_row_allocation
        """
        set_clock()
        ctx = setup_vehicle_with_entitlements(count=3)
        vehicle_id = ctx["vehicle"]["id"]

        rows = create_entitlements(vehicle_id, [
            {"feature_code": "FSD_SUPERVISED", "price_cents": 2800000},
            {"feature_code": "ACCELERATION_BOOST", "price_cents": 1200000},
        ])
        assert len(rows) == 2, "the response carries exactly one row per request entry"

        raw_total = 4000000
        gross_discount = raw_total * 1000 // 10000
        applied = min(MAX_BUNDLE_DISCOUNT_CENTS, gross_discount)
        expected_net = raw_total - applied
        assert applied == MAX_BUNDLE_DISCOUNT_CENTS, "the 1000-bps discount is capped here"
        assert rows[0]["bundle_net_cents"] == expected_net == 3800000
        assert rows[1]["bundle_net_cents"] == 3800000
        assert sum(r["payable_cents"] for r in rows) == 3800000

    def test_recorded_discount_bps_reflects_the_cap_not_the_nominal_tier(self, api):
        """PRD §3.11: "Fourth, the effective `bundle_discount_bps` actually applied
        is the applied discount multiplied by 10000 and then divided by the raw
        total, truncated down to an integer — this is why the recorded basis
        points can be lower than the tier's nominal rate whenever the cap binds."
        PRD §3.11: "A count of four or more receives a tier rate of 1000 basis
        points."

        Design: Difficulty/combinatorial_formula/entitlement_bundle_cap_then_per_row_allocation
        """
        set_clock()
        ctx = setup_vehicle_with_entitlements(count=3)
        vehicle_id = ctx["vehicle"]["id"]

        rows = create_entitlements(vehicle_id, [
            {"feature_code": "FSD_SUPERVISED", "price_cents": 2800000},
            {"feature_code": "ACCELERATION_BOOST", "price_cents": 1200000},
        ])
        nominal_bps = 1000
        raw_total = 4000000
        applied = raw_total * nominal_bps // 10000
        applied = min(MAX_BUNDLE_DISCOUNT_CENTS, applied)
        expected_bps = applied * 10000 // raw_total

        assert rows[0]["bundle_discount_bps"] == expected_bps == 500, (
            "the cap binds, so the recorded rate is half the nominal tier rate"
        )
        assert rows[1]["bundle_discount_bps"] == 500
