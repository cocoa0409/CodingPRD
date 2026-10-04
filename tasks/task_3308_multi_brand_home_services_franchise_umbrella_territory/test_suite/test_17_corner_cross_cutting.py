"""Cross-cutting corner claims: OCC, the portfolio threshold, reconciliation
and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_referral,
    activate_agreement,
    award_territory,
    complete_referral,
    create_agreement,
    create_brand,
    create_franchisee,
    create_lead,
    create_referral,
    create_territory,
    franchisee_version,
    get_agreement,
    get_franchisee,
    get_referral,
    get_territory,
    offer_agreement,
    offer_territory,
    set_clock,
    setup_two_brand_pair,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestTerritoryAwardStaleVersion:
    def test_the_award_refuses_a_stale_version_and_accepts_the_fresh_one(self, api):
        """PRD §2.12: "Awarding a territory requires
        `expected_territory_version`, carrying the client's last observed
        `version` of the `Territory` being awarded. A mismatch is rejected with
        `ERR_STALE_VERSION` at HTTP 412."
        PRD §3.2: "if the territory's stored `version` no longer matches, the
        award is refused with `ERR_STALE_VERSION` before anything else about the
        award is considered".

        Design: Corner/cross_cutting_complexity_layers/stale_territory_award_version_is_rejected_deterministically
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])

        stale = get_territory(territory["id"])["version"]
        offered = offer_territory(territory["id"], franchisee["id"])
        fresh = offered["version"]
        assert fresh == stale + 1, (
            f"the offer must advance the version from {stale} to {stale + 1}, "
            f"got {fresh}"
        )

        resp = api.award_territory(territory["id"], stale, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        refused = get_territory(territory["id"])
        assert refused["status"] == "OFFERED"
        assert refused["allocated_households"] == 0

        resp = api.award_territory(territory["id"], fresh, ADMIN)
        accepted = validate_success(resp, 200)
        assert accepted["status"] == "AWARDED"


class TestMultiBrandThresholdOnLeadCost:
    def test_the_portfolio_boundary_flips_the_price_only_at_the_minimum(self, api):
        """PRD §3.6: "If the receiving franchisee's `active_brand_count` is at
        least 3, the subtotal is multiplied by 0.85 and rounded half up to a
        whole cent to give the `lead_cost_cents`; otherwise the subtotal itself
        is the `lead_cost_cents`."
        PRD §3.6: "The order of operations is pinned: the band base and the value
        surcharge are summed first, and the multi-brand discount is applied to
        that subtotal last".

        Design: Corner/cross_cutting_complexity_layers/lead_allocation_brand_count_flips_the_cost_at_the_portfolio_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ms_brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        il_brand = create_brand(
            brand_code="ILE", display_name="Illume Electric", trade="ELECTRICAL",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="JOURNEYMAN", audit_cycle_months=12,
            cross_brand_fee_table={},
        )

        # Two-brand operator: below the boundary.
        two_brand = create_franchisee()
        ter_two_ms = create_territory(ms_brand["id"], franchisee_id=two_brand["id"])
        ter_two_il = create_territory(il_brand["id"], franchisee_id=two_brand["id"])
        agt_two_ms = create_agreement(
            two_brand["id"], ms_brand["id"], ter_two_ms["id"],
        )
        agt_two_il = create_agreement(
            two_brand["id"], il_brand["id"], ter_two_il["id"], certification_level="MASTER",
        )

        # Three-brand operator: at the boundary.
        three_brand = create_franchisee(
            legal_name="Trident Services LLC", principal_name="Ines Kaur",
            entity_type="PARTNERSHIP", shared_services_enrolled=True,
        )
        ter_three_ms = create_territory(ms_brand["id"], franchisee_id=three_brand["id"])
        ter_three_il = create_territory(il_brand["id"], franchisee_id=three_brand["id"])
        rv_brand = create_brand(
            brand_code="RVR", display_name="Revive Restoration", trade="RESTORATION",
            royalty_rate=0.07, national_ad_fund_rate=0.015,
            min_certification_level="MASTER", audit_cycle_months=6,
            cross_brand_fee_table={},
        )
        ter_three_rv = create_territory(rv_brand["id"], franchisee_id=three_brand["id"])
        agt_three_ms = create_agreement(
            three_brand["id"], ms_brand["id"], ter_three_ms["id"],
        )
        agt_three_il = create_agreement(
            three_brand["id"], il_brand["id"], ter_three_il["id"], certification_level="MASTER",
        )
        agt_three_rv = create_agreement(
            three_brand["id"], rv_brand["id"], ter_three_rv["id"], certification_level="MASTER",
        )

        pairs = (
            (ter_two_ms, agt_two_ms), (ter_two_il, agt_two_il),
            (ter_three_ms, agt_three_ms), (ter_three_il, agt_three_il),
            (ter_three_rv, agt_three_rv),
        )
        for territory, agreement in pairs:
            offer_agreement(agreement["id"])
            offer_territory(territory["id"], agreement["franchisee_id"])
            award_territory(territory["id"])
            activate_agreement(agreement["id"])

        below = create_lead(
            ms_brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=150000,
        )
        at = create_lead(
            ms_brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=150000,
        )

        two = validate_success(api.allocate_lead(
            below["id"], franchisee_version(two_brand["id"]), ADMIN,
            allocated_agreement_id=agt_two_ms["id"],
        ), 200)
        assert get_franchisee(two_brand["id"])["active_brand_count"] == 2, (
            "two ACTIVE agreements under two brands sit below the boundary"
        )
        assert two["lead_cost_cents"] == 4500, (
            "BAND_2 base 4000 plus a two-unit surcharge of 500 is 4500 with no "
            f"portfolio discount, got {two['lead_cost_cents']}"
        )

        three = validate_success(api.allocate_lead(
            at["id"], franchisee_version(three_brand["id"]), ADMIN,
            allocated_agreement_id=agt_three_ms["id"],
        ), 200)
        assert get_franchisee(three_brand["id"])["active_brand_count"] == 3, (
            "three brands sit exactly at the boundary"
        )
        assert three["lead_cost_cents"] == 3825, (
            "the same 4500 subtotal discounted by 0.85 and rounded half up is "
            f"3825, got {three['lead_cost_cents']}"
        )
        assert two["lead_cost_cents"] != three["lead_cost_cents"], (
            "identical band and estimated value must price differently across "
            "the portfolio boundary"
        )


class TestReferralNetPositionReconciles:
    def test_both_agreement_ledgers_stay_exactly_opposite(self, api):
        """PRD §2.8: "The second is the agreement's
        `cumulative_referral_net_cents`, the cross-brand attribution ledger. It
        is increased by a referral's `referral_fee_cents` when that agreement is
        the originator of a settling referral and decreased by the same amount
        when it is the receiver."
        PRD §2.8: "Across any pair of agreements in the same referral, these two
        figures must stay exactly opposite."

        Design: Corner/cross_cutting_complexity_layers/referral_net_position_reconciles_across_both_agreement_ledgers
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
            customer_household_ref="HH-9501",
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 120000)

        resp = api.settle_referral(
            referral["id"], ctx["agt_a1"]["version"], ADMIN,
        )
        settled = validate_success(resp, 200)

        assert settled["status"] == "SETTLED"
        assert settled["fee_variant"] == "TIERED_BRAND_PAIR"

        originator = get_agreement(ctx["agt_a1"]["id"])
        receiver = get_agreement(ctx["agt_a2"]["id"])
        assert originator["cumulative_referral_net_cents"] == 18000
        assert receiver["cumulative_referral_net_cents"] == -18000
        assert (originator["cumulative_referral_net_cents"]
                + receiver["cumulative_referral_net_cents"]) == 0, (
            "the denormalized counters must sum to zero across the pair"
        )


class TestSettlementIsImmediatelyVisible:
    def test_every_settlement_side_effect_is_readable_in_the_same_request(self, api):
        """PRD §2.9: "The general reconciliation principle is that any field
        marked as computed must be reproducible from the records it summarizes
        at the moment it is read".
        PRD §3.5: "On success the referral's `settled_clock_iso` is stamped, its
        status becomes `SETTLED`, and the fee is posted to both sides at once".

        Design: Corner/consistency_model/all_settlement_side_effects_are_visible_in_the_same_request
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
            customer_household_ref="HH-9601",
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 120000)
        version = api.get_agreement(
            ctx["agt_a1"]["id"], ADMIN,
        ).json()["data"]["version"]
        api.settle_referral(referral["id"], version, ADMIN)

        # A plain re-read, with no clock advance and no retry.
        stored = get_referral(referral["id"])
        assert stored["status"] == "SETTLED"
        assert stored["settled_clock_iso"] == "2026-09-01T00:00:00Z", (
            f"the settlement instant is the logical clock, got {stored['settled_clock_iso']}"
        )
        assert stored["referral_fee_cents"] == 18000
        assert stored["fee_variant"] == "TIERED_BRAND_PAIR"

        assert get_agreement(ctx["agt_a1"]["id"])["cumulative_referral_net_cents"] == 18000
        assert get_agreement(ctx["agt_a2"]["id"])["cumulative_referral_net_cents"] == -18000