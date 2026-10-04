"""Numeric results that follow from the PRD's stated arithmetic (PRD §2.8, §3.1–§3.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    commit_allocation,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_order,
    create_season,
    declare_capacity,
    make_auditor_headers,
    onboard_partner,
    pay_order,
    register_claim,
    set_clock,
    ship_allocation,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


class TestRefundDiscountSpread:
    """Corner/calculations — the discount is spread across every unit of the line."""

    def test_a_one_unit_return_refunds_the_discounted_effective_price(self, api):
        """PRD §3.6: "The refund figure is assembled in three steps. The effective unit ratio is the line's total after discount divided by its total before discount — that is, the unit price multiplied by the quantity, less the line discount, over the unit price multiplied by the quantity. The effective unit refund is the unit price multiplied by that ratio, rounded half up once to a whole cent. The refund amount is that rounded unit refund multiplied by the number of units returned."
        PRD §3.6: "A discount is therefore spread across all of a line's units rather than carved out of the refunded units alone: a line of two units at 1800 cents apiece with a 500-cent discount refunds 1300 cents for a one-unit return and 2600 cents for a two-unit return, where an undiscounted line at the same price refunds 1800 cents per unit."

        Design: Corner/calculations/refund_uses_the_discounted_effective_unit_price_at_a_mid_cent_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000605", "M", True)
        order = create_order(order_number="SO-REFUND-1", channel="RETAIL_ECOM")
        soline = add_line(
            order["id"], line["id"], quantity=2, unit_price_cents=1800,
            line_discount_cents=500,
        )
        pay_order(order["id"])
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]

        ret = validate_success(
            api_client.create_return_request(
                {
                    "sales_order_line_id": soline["id"],
                    "request_reason": "SIZE",
                    "requested_units": 1,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )
        validate_success(api_client.approve_return_request(ret["id"], {}, SERVICE), 200)
        credited = validate_success(
            api_client.credit_return_request(
                ret["id"], {"replacement_product_id": NON_EXISTENT_UUID}, SERVICE
            ),
            200,
        )

        assert credited["refund_amount_cents"] == 1300, "not 1550 and not 1800"
        assert credited["status"] == "CREDITED"
        assert credited["terminal_outcome"] == "REFUNDED"
        assert credited["liability_delta_units"] == 0

    def test_the_ledger_is_untouched_by_the_credit(self, api):
        """PRD §3.6: "The firewall itself is absolute. Crediting a return never reduces the final liability ledger and never decreases a line's `obligated_units`; the request's `liability_delta_units` is zero on every path, whether the customer took a refund or a replacement, and the liability row behind the original sale — recorded on the request as the `donation_liability_id` of the sale — retains its units throughout."

        Design: Corner/calculations/refund_uses_the_discounted_effective_unit_price_at_a_mid_cent_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000606", "M", True)
        order = create_order(order_number="SO-REFUND-2", channel="RETAIL_ECOM")
        soline = add_line(
            order["id"], line["id"], quantity=2, unit_price_cents=1800,
            line_discount_cents=500,
        )
        pay_order(order["id"])
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]
        ret = validate_success(
            api_client.create_return_request(
                {
                    "sales_order_line_id": soline["id"],
                    "request_reason": "SIZE",
                    "requested_units": 1,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )
        validate_success(api_client.approve_return_request(ret["id"], {}, SERVICE), 200)
        validate_success(
            api_client.credit_return_request(
                ret["id"], {"replacement_product_id": NON_EXISTENT_UUID}, SERVICE
            ),
            200,
        )

        liability = validate_success(
            api_client.list_liabilities(
                TEST_USERS["auditor_headers"],
                {"donation_product_id": product["id"], "impact_season_id": season["id"]},
            ),
            200,
        )[0]
        # PRD §3.6's firewall: "never decreases a line's `obligated_units`",
        # and "the request's `liability_delta_units` is zero on every path".
        credited_line = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )
        assert credited_line["obligated_units"] == 2
        assert ret["liability_delta_units"] == 0


class TestNeedScoreAccessCap:
    """Corner/calculations — the access component clamps at twenty points."""

    def test_two_large_recipient_counts_both_hit_the_clamp(self, api):
        """PRD §3.1: "A separate access component is added: the partner's average unduplicated recipients per facility divided by one thousand in truncating integer division, capped at 20."

        Design: Corner/calculations/need_score_access_component_clamps_at_twenty_points
        """
        set_clock("2026-09-01T00:00:00Z")
        big = onboard_partner(
            legal_name="Phi Relief Large",
            partner_type="DISASTER_RELIEF",
            operating_region="MIDWEST",
            operating_state_code="OH",
            registry_id="OH-CHR-210021",
            ein="300400500",
            unduplicated_recipients_per_facility=25000,
            need_tier="CRITICAL",
        )
        set_clock("2026-09-02T00:00:00Z")
        small = onboard_partner(
            legal_name="Chi Relief Large",
            partner_type="DISASTER_RELIEF",
            operating_region="MIDWEST",
            operating_state_code="OH",
            registry_id="OH-CHR-220022",
            ein="300400600",
            unduplicated_recipients_per_facility=20000,
            need_tier="CRITICAL",
        )

        big_row = validate_success(api_client.get_giving_partner(big["id"], COORD), 200)
        small_row = validate_success(api_client.get_giving_partner(small["id"], COORD), 200)
        assert big_row["need_score"] == 100, "clamped from 95 + 6 + 20"
        assert small_row["need_score"] == 100
        assert small_row["need_score"] == big_row["need_score"]


class TestRankScoreCaps:
    """Corner/calculations — each term caps separately and the total clamps."""

    def _tier_fixture(self, order_number):
        # PRD §2.4 makes `order_number` unique across all sales orders, so each
        # funding order is numbered distinctly; the partner, product and season
        # are shared so the two ranks sit on identical other terms.
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000607", "M", True)
        order = create_order(order_number=order_number, channel="RETAIL_ECOM")
        add_line(order["id"], line["id"], quantity=3, unit_price_cents=1600)
        pay_order(order["id"])
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        return season, product, partner, claim

    def _tier_commit(self, tier, season, product, partner, claim):
        return commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=10, priority_tier=tier,
        )

    def test_an_emergency_commit_is_pinned_at_the_ceiling(self, api):
        """PRD §3.2: "The priority term reads the tier directly (an emergency commitment contributes 40 points, a critical one 30, a high one 20 and a moderate one 10)."
        PRD §3.2: "The allocation is created pending and approved within the request, its `rank_score` is computed, the partner's `committed_units` rises by `allocated_units`, and the partner's `version` advances by one."

        Design: Corner/calculations/rank_score_caps_each_term_and_clamps_the_total
        """
        season, product, partner, claim = self._tier_fixture("SO-RANK-EM")
        allocation = self._tier_commit("EMERGENCY", season, product, partner, claim)
        assert allocation["priority_tier"] == "EMERGENCY"
        assert allocation["status"] == "APPROVED"
        assert 0 <= allocation["rank_score"] <= 100

    def test_a_moderate_tier_ranks_strictly_lower(self, api):
        """PRD §3.2: "A priority-led rank means a `CRITICAL` partner outranks every `MODERATE` partner regardless of the other terms, because the priority term alone exceeds the whole moderate ladder's ceiling plus its caps."

        Design: Corner/calculations/rank_score_caps_each_term_and_clamps_the_total
        """
        season, product, partner, claim = self._tier_fixture("SO-RANK-EM")
        emergency = self._tier_commit("EMERGENCY", season, product, partner, claim)
        moderate = self._tier_commit("MODERATE", season, product, partner, claim)
        assert moderate["rank_score"] < emergency["rank_score"]


class TestAttributionResidual:
    """Corner/calculations — the rounding residual lands on the last partner."""

    def test_three_equal_partners_still_total_exactly_one_hundred(self, api):
        """PRD §2.8: "partner attribution percentages are rounded to one decimal place, half up, with the rounding residual folded into the last partner so the reported `attributed_percentage`, and the `attributed_percentage_total` summed over the rolled-up pool, come to exactly 100.0 and never 99.9 or 100.1 — the last partner in descending `claim_attributed_units` with ascending `legal_name` as the tie-break carries the residual share; allocation weights are held to six decimal places, half up; and a partner's mean completion time in days is reported to two decimal places, half up."

        Design: Corner/calculations/attributed_percentage_residual_is_folded_into_the_last_partner
        """
        from test_helpers import setup_three_partner_pool

        pool = setup_three_partner_pool(cap_units=10000)
        for partner in pool["partners"]:
            commit_allocation(
                pool["season"]["id"], partner["id"], pool["claim"]["id"],
                pool["product"]["id"], allocated_units=5, priority_tier="CRITICAL",
            )

        summary = validate_success(
            api_client.get_season_summary(pool["season"]["id"], TEST_USERS["auditor_headers"]),
            200,
        )
        assert summary["attributed_units_total"] == 15
        assert summary["attributed_percentage_total"] == 100.0

        percentages = []
        for partner in pool["partners"]:
            row = validate_success(
                api_client.get_giving_partner(partner["id"], COORD), 200
            )
            percentages.append(row["attributed_percentage"])
        assert sorted(percentages) == [33.3, 33.3, 33.4]


class TestClearanceRoundingBeforeWeighting:
    """Corner/calculations — the ratio is rounded to four decimals before it is weighted."""

    def test_a_repeating_ratio_rounds_before_it_enters_the_scorecard(self, api):
        """PRD §3.9: "`unit_clearance_rate` is the received figure divided by the shipped figure, rounded half up to four decimal places and null when nothing shipped."
        PRD §3.9: "The partner performance grade is a weighted scorecard floored to an integer after clamping."

        Design: Corner/calculations/clearance_ratio_rounds_to_four_decimals_before_weighting
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner(unduplicated_recipients_per_facility=15000)
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=300, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 300, "TRK-PR-1", "UPS")
        confirm_receipt(distribution["id"], 250, "RCV-PR-1")

        set_clock("2026-12-02T00:00:00Z")
        audit = validate_success(
            api_client.create_impact_audit(
                {
                    "impact_season_id": season["id"],
                    "claim_id": claim["id"],
                    "audit_kind": "PARTNER_PERFORMANCE",
                },
                TEST_USERS["auditor_headers"],
            ),
            201,
        )
        started = validate_success(
            api_client.start_audit(audit["id"], {}, TEST_USERS["auditor_headers"]), 200
        )
        # PRD §2.12: the acting identifier may not be the one that performed
        # the preliminary review, so a second auditor finalizes.
        finalized = validate_success(
            api_client.finalize_audit(
                audit["id"],
                {
                    "transaction_test_sample_size": 20,
                    "transaction_test_exceptions": 4,
                    "claimed_donation_units": 250,
                    "expected_audit_version": started["version"],
                },
                make_auditor_headers("aud-postreview"),
            ),
            200,
        )

        assert finalized["unit_clearance_rate"] == 0.8333
        assert finalized["shipped_units_verified"] == 300
        assert finalized["received_units_verified"] == 250
        # PRD §3.9: the clearance term is the four-decimal rate weighted at
        # fifty and rounded (0.8333 -> 41.665 -> 42), the receipt-logging term
        # is the capped proportion weighted at fifteen (1.0 -> 15), and the
        # exception penalty is ten per sampled exception (4 -> 40); the clamped
        # total truncates toward zero.
        assert finalized["scorecard_total"] == 17
        assert finalized["partner_performance_grade"] == "PROBATION"


class TestDonationUnitCostMinimum:
    """Corner/calculations — the smaller-of is taken over already-rounded terms."""

    def test_dual_channel_takes_the_offset_and_donation_only_does_not(self, api):
        """PRD §3.4: "A dual-channel product is thus never charged more than its own manufacturing cost, and a donation-only product takes no retail offset at all: at a manufacturing cost of 1150 cents and a retail price of 1600 cents, the donation-only variant costs 805 cents and the dual-channel variant 725 cents, because the 80-cent retail offset is subtracted first."

        Design: Corner/calculations/donation_unit_cost_takes_the_minimum_over_already_rounded_terms
        """
        set_clock("2026-09-01T00:00:00Z")
        dual = create_active_product(
            product_name="Offset Probe Sock",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            retail_price_cents=1600,
            unit_cost_cents=1150,
        )
        donation_only = create_active_product(
            product_name="Offset Probe Underlayer",
            product_kind="ATHLETIC_SOCK",
            design_channel="DONATION_ONLY",
            obligation_model="AT_VESTING",
            retail_price_cents=1600,
            unit_cost_cents=1150,
        )
        dual_line = add_product_line(dual["id"], "00000000000401", "M", False)
        don_line = add_product_line(donation_only["id"], "00000000000402", "M", False)

        assert dual_line["unit_obligation_cost_cents"] == 725, "min(1150, max(0, 805 - 80))"
        assert don_line["unit_obligation_cost_cents"] == 805
        assert dual_line["design_variant_code"] == "retail_dual"
        assert don_line["design_variant_code"] == "donation_specific"


class TestProvisionalLedgerIncludeSet:
    """Corner/calculations — the status list is explicit."""

    def test_a_refunded_order_keeps_its_units_and_a_cancelled_one_drops_them(self, api):
        """PRD §3.5: "The provisional ledger counts units of obligation across all lines whose owning order is in `CREATED` or any later non-cancelled status — `CREATED`, `PAID`, `DONATION_SATISFIED`, `PARTIALLY_REFUNDED` or `REFUNDED` — but only for lines whose variant is donation-eligible and whose product's obligation model is `AT_SALE`."
        PRD §3.5: "The final ledger is narrower and counts only settled, completed sales."

        Design: Corner/calculations/provisional_ledger_excludes_cancelled_orders_but_keeps_refunded_ones
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000608", "M", True)

        order_a = create_order(order_number="SO-SET-1", channel="RETAIL_ECOM")
        soline_a = add_line(order_a["id"], line["id"], quantity=3, unit_price_cents=1600)
        pay_order(order_a["id"])
        line_version = validate_success(
            api_client.get_order_line(order_a["id"], soline_a["id"], SERVICE), 200
        )["version"]
        ret = validate_success(
            api_client.create_return_request(
                {
                    "sales_order_line_id": soline_a["id"],
                    "request_reason": "CHANGE_OF_MIND",
                    "requested_units": 3,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )
        validate_success(api_client.approve_return_request(ret["id"], {}, SERVICE), 200)
        validate_success(
            api_client.credit_return_request(
                ret["id"], {"replacement_product_id": NON_EXISTENT_UUID}, SERVICE
            ),
            200,
        )

        order_b = create_order(order_number="SO-SET-2", channel="RETAIL_POS")
        add_line(order_b["id"], line["id"], quantity=3, unit_price_cents=1600)

        before = validate_success(
            api_client.list_liabilities(
                TEST_USERS["auditor_headers"],
                {"donation_product_id": product["id"], "impact_season_id": season["id"]},
            ),
            200,
        )[0]
        assert before["provisional_liability_units"] == 6

        validate_success(
            api_client.cancel_order(order_b["id"], {"reason": "Payment not captured"}, SERVICE),
            200,
        )

        after = validate_success(
            api_client.list_liabilities(
                TEST_USERS["auditor_headers"],
                {"donation_product_id": product["id"], "impact_season_id": season["id"]},
            ),
            200,
        )[0]
        assert after["provisional_liability_units"] == 3
        assert after["final_liability_units"] == 0, "the cancelled order was never settled"