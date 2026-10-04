"""Preparation-fee and interest/pricing calculation tests (difficulty queue A).

Covers the tiered fee calculation (single rounding after the multiply), the
dual quote-vs-final variant, premium banding, and the pinned interest-accrual
rounding order.
"""
from test_helpers import (
    TEST_USERS,
    create_client,
    create_notice,
    create_office,
    create_preparer,
    create_return,
    set_clock,
    setup_filed_return,
    setup_office_preparer_client,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestFeeTieredMultiplierModes:
    def test_quote_uses_associate_multiplier(self, api):
        """PRD §3.2: "The credits for all listed components are summed into a
        single integer total; that total is then multiplied by the tier
        multiplier — 1.0 for `ASSOCIATE`, 1.25 for `SENIOR`, 1.5 for `MASTER`,
        1.75 for `ENROLLED_AGENT` — producing a possibly fractional cent
        figure; and the product is rounded half-up to the nearest whole dollar
        (100 cents)."

        Components 1040_SIMPLE + 1040_MULTI_STATE give 27500 credits; ASSOCIATE
        (1.0) quotes exactly 27500.

        Design: Difficulty/combinatorial_formula/fee_tiered_multiplier_modes
        """
        office, preparer, client = setup_office_preparer_client(
            preparer_overrides={"tier": "ASSOCIATE"}
        )
        ret = create_return(
            client["id"], office["id"], preparer["id"],
            components=["1040_SIMPLE", "1040_MULTI_STATE"],
        )
        assert ret["quoted_fee_cents"] == 27500

    def test_quote_scales_across_all_tiers(self, api):
        """PRD §3.2: "that total is then multiplied by the tier multiplier —
        1.0 for `ASSOCIATE`, 1.25 for `SENIOR`, 1.5 for `MASTER`, 1.75 for
        `ENROLLED_AGENT` — producing a possibly fractional cent figure; and
        the product is rounded half-up to the nearest whole dollar (100
        cents). The rounding order is pinned: multiply the total credits by
        the multiplier first, then round once."

        Same 27500-credit components quoted under all four tiers.

        Design: Difficulty/combinatorial_formula/fee_tiered_multiplier_modes
        """
        office = create_office()
        preparers = {
            tier: create_preparer(office["id"], tier=tier)
            for tier in ("ASSOCIATE", "SENIOR", "MASTER", "ENROLLED_AGENT")
        }
        expected = {"ASSOCIATE": 27500, "SENIOR": 34400, "MASTER": 41300, "ENROLLED_AGENT": 48100}
        for tier, preparer in preparers.items():
            client = create_client()
            ret = create_return(
                client["id"], office["id"], preparer["id"],
                components=["1040_SIMPLE", "1040_MULTI_STATE"],
            )
            assert ret["quoted_fee_cents"] == expected[tier], (
                f"{tier}: expected {expected[tier]}, got {ret['quoted_fee_cents']}"
            )


class TestQuotedVsFinalFeePreparerUpgrade:
    def test_quote_and_final_fee_diverge_after_upgrade(self, api):
        """PRD §3.2: "Filing recomputes the fee with the same credit table and
        the same rounding rule, but using the preparer's tier **at filing
        time**, and locks the result into `final_fee_cents`, which stays null
        until that moment and is never recomputed afterwards."

        Quoted under ASSOCIATE (27500), filed after upgrade to SENIOR (34400).

        Design: Difficulty/dual_variant_calc/quoted_vs_final_fee_preparer_upgrade
        """
        office, preparer, client = setup_office_preparer_client()
        ret = create_return(
            client["id"], office["id"], preparer["id"],
            components=["1040_SIMPLE", "1040_MULTI_STATE"],
        )
        assert ret["quoted_fee_cents"] == 27500
        validate_success(
            api.upgrade_preparer(preparer["id"], {"tier": "SENIOR"}, OM), 200
        )
        filed = validate_success(api.file_return(ret["id"], OM), 200)
        assert filed["quoted_fee_cents"] == 27500
        assert filed["final_fee_cents"] == 34400

    def test_final_fee_null_until_filing_and_quoted_preserved(self, api):
        """PRD §3.2: "Because a preparer swap between quote and filing changes
        the tier input, identical components can legitimately produce a
        `quoted_fee_cents` that differs from `final_fee_cents`; this
        divergence is by design, not an error."

        The quote is not retroactively changed by the upgrade, and the final
        fee is locked only at filing.

        Design: Difficulty/dual_variant_calc/quoted_vs_final_fee_preparer_upgrade
        """
        office, preparer, client = setup_office_preparer_client()
        ret = create_return(
            client["id"], office["id"], preparer["id"],
            components=["1040_SIMPLE", "1040_MULTI_STATE"],
        )
        assert ret["final_fee_cents"] is None
        validate_success(api.upgrade_preparer(preparer["id"], {"tier": "SENIOR"}, OM), 200)
        after_upgrade = validate_success(api.get_return(ret["id"], OM), 200)
        assert after_upgrade["quoted_fee_cents"] == 27500, "upgrade must not re-quote retroactively"
        assert after_upgrade["final_fee_cents"] is None
        filed = validate_success(api.file_return(ret["id"], OM), 200)
        assert filed["status"] == "FILED"
        assert filed["final_fee_cents"] == 34400


class TestInterestBoundaryRounding:
    def test_interest_paid_on_due_date_and_after_45_days(self, api):
        """PRD §3.4: "the due date itself is excluded and the payment date
        included, so paying on or before `due_at` yields zero days and zero
        interest. For a positive day count, the interest is the notice's
        `tax_delta_cents` multiplied by a daily rate of 0.000273972602739726
        and by the number of days, with the full-precision product rounded
        half-up once to cents."

        Paying exactly on due_at gives 0; paying 45 days late on a 38000 delta
        gives round_half_up(38000 * rate * 45) = 468.

        Design: Difficulty/combinatorial_formula/interest_boundary_rounding
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"])
        ret_id = ctx["tax_return"]["id"]
        n1 = create_notice(ret_id, tax_delta_cents=38000, penalty_cents=0,
                           issued_at="2026-09-10T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        n45 = create_notice(ret_id, tax_delta_cents=38000, penalty_cents=0,
                            issued_at="2026-09-10T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        paid1 = validate_success(api.pay_notice(n1["id"], OM), 200)
        assert paid1["interest_cents"] == 0, "payment on the due date accrues zero interest"
        set_clock("2026-11-15T00:00:00Z")
        paid45 = validate_success(api.pay_notice(n45["id"], OM), 200)
        assert paid45["interest_cents"] == 468

    def test_interest_rounds_once_on_the_full_product(self, api):
        """PRD §3.4: "Rounding a per-day amount first and then multiplying is
        forbidden — the pinned order is product-then-round."

        38000 * 0.000273972602739726 * 45 = 468.49... rounds to 468; the
        forbidden per-day rounding would yield 4686 (round(10.41) * 45). A
        second boundary: paying before the due date also yields zero.

        Design: Difficulty/combinatorial_formula/interest_boundary_rounding
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"])
        ret_id = ctx["tax_return"]["id"]
        n_early = create_notice(ret_id, tax_delta_cents=38000, penalty_cents=0,
                                issued_at="2026-09-10T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        n45 = create_notice(ret_id, tax_delta_cents=38000, penalty_cents=0,
                            issued_at="2026-09-10T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        # Default clock is 2026-09-01, before the due date.
        paid_early = validate_success(api.pay_notice(n_early["id"], OM), 200)
        assert paid_early["interest_cents"] == 0
        set_clock("2026-11-15T00:00:00Z")
        paid45 = validate_success(api.pay_notice(n45["id"], OM), 200)
        assert paid45["interest_cents"] == 468
        assert paid45["interest_cents"] != 4686, "per-day rounding is the forbidden order"


class TestPremiumTierBands:
    def test_credits_at_simple_cap_stay_in_base_band(self, api):
        """PRD §3.3: "When the total is at or below the simple cap, the
        premium is the flat base premium for the tier: 4900 cents for
        `STANDARD`, 9900 cents for `PLUS`."
        PRD §3.3: "The tier boundary rule is inclusive downward: a total
        exactly equal to a cap falls into the lower band."

        [1040_ITEMIZED] totals exactly 15000 credits (the simple cap):
        premium stays at the 4900 base.

        Design: Corner/calculations/premium_tier_bands
        """
        ctx = setup_filed_return(components=["1040_ITEMIZED"])
        res = api.create_product({"return_id": ctx["tax_return"]["id"], "tier": "STANDARD"}, OM)
        product = validate_success(res, 201)
        assert product["premium_cents"] == 4900

    def test_credits_above_simple_cap_hit_one_and_a_half_band(self, api):
        """PRD §3.3: "When the total exceeds the simple cap but is at or below
        the standard cap, the premium is one and a half times the base
        premium, rounded half-up to cents where fractional."

        [1040_SIMPLE, 1040_MULTI_STATE] totals 27500 credits (> 15000,
        <= 30000): 4900 * 1.5 = 7350 exactly.

        Design: Corner/calculations/premium_tier_bands
        """
        ctx = setup_filed_return(components=["1040_SIMPLE", "1040_MULTI_STATE"])
        res = api.create_product({"return_id": ctx["tax_return"]["id"], "tier": "STANDARD"}, OM)
        product = validate_success(res, 201)
        assert product["premium_cents"] == 7350


class TestDerivedFieldReconciliationRequoteOnPatch:
    def test_patch_components_requotes(self, api):
        """PRD §3.2: "Updates to a `PREPARING` return go through the patch
        capability, which accepts `components` and/or `preparer_id`, re-quotes
        `quoted_fee_cents` using the then-current tier, and bumps the
        return's `version`."

        Patching [1040_SIMPLE] (7500) to [1040_ITEMIZED, 1040_MULTI_STATE]
        (35000) re-quotes to exactly 35000 under ASSOCIATE.

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_requote_on_patch
        """
        office, preparer, client = setup_office_preparer_client()
        ret = create_return(client["id"], office["id"], preparer["id"],
                            components=["1040_SIMPLE"])
        assert ret["quoted_fee_cents"] == 7500
        patched = validate_success(
            api.patch_return(ret["id"], {"components": ["1040_ITEMIZED", "1040_MULTI_STATE"]}, OM), 200
        )
        assert patched["quoted_fee_cents"] == 35000
