"""Derived-field arithmetic: credit rollups, revenue filters, attainment denominators,
weighted-score rounding, band thresholds, fund sizing, cooldown geometry, doctrine
selection and the portal ladder."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    ApiErrorId,
    add_certification,
    assert_certification_record,
    assert_mdf_allocation,
    assert_mdf_fund_conservation,
    assert_order_invoice,
    assert_order_invoice_margin_conservation,
    assert_paging_meta,
    assert_rate_precision,
    assert_score_precision,
    create_account,
    create_and_invoice_order,
    create_order,
    create_partner,
    make_partner_headers,
    open_allocation,
    prepare_review,
    propose_mapping,
    read_account,
    read_allocation,
    read_invoice,
    read_partner,
    seed_gold_distributor,
    seed_partner_vs_direct_conflict,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreditAndRevenueRollups:
    def test_the_credit_rollup_sums_the_three_track_weights_to_seven(self, api):
        """PRD §3.1: "The `track` is one of `SALES_PRO`, `TECH_ASSOCIATE` or `TECH_EXPERT`, and it
        fixes the record's `credit_weight` at creation and forever after: a `SALES_PRO` record is
        worth 1 credit, a `TECH_ASSOCIATE` record 2 credits, and a `TECH_EXPERT` record 4."
        PRD §3.1: "Recording a certification triggers a full recomputation of the partner's
        `cert_credit_total`, which is the sum of `credit_weight` across every certification record
        belonging to that partner whose `status` is `ACTIVE`."

        Design: Corner/calculations/certification_credit_rollup_sums_the_track_weights
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        assert partner["cert_credit_total"] == 0

        sales_pro = add_certification(
            partner["id"], engineer_name="Iva Sorel", track="SALES_PRO"
        )
        assert_certification_record(sales_pro)
        assert sales_pro["credit_weight"] == 1
        assert sales_pro["status"] == "ACTIVE"
        assert read_partner(partner["id"])["cert_credit_total"] == 1

        add_certification(partner["id"], engineer_name="Jae Kim", track="TECH_ASSOCIATE")
        assert read_partner(partner["id"])["cert_credit_total"] == 3

        add_certification(partner["id"], engineer_name="Kit Vance", track="TECH_EXPERT")
        rolled_up = read_partner(partner["id"])
        assert rolled_up["cert_credit_total"] == 7, "1 + 2 + 4, recomputed over the ACTIVE rows"

        assert rolled_up["tier"] == "REGISTERED", "credits alone never promote a partner"
        assert rolled_up["portal_entitlement_level"] == "BASIC"

    def test_the_revenue_rollup_skips_the_pending_twin_of_an_invoiced_order(self, api):
        """PRD §3.6: "`invoiced_at` is set to the current logical instant, the order's `version`
        advances by 1, and the partner's `trailing_revenue_cents` is recomputed as the sum of
        `invoice_amount_cents` across that partner's orders whose `status` is `INVOICED` or
        `CREDITED`. Orders still in `PENDING` are excluded from that rolling figure entirely — they
        matter only to the provisional scoring variant of §3.9."

        Design: Corner/calculations/revenue_rollup_excludes_pending_orders
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")

        first = create_order(partner["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000)
        second = create_order(partner["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000)

        invoiced = validate_success(api.invoice_order(first["id"], ANALYST))
        assert_order_invoice(invoiced)
        assert invoiced["status"] == "INVOICED"
        assert invoiced["invoiced_at"] == "2026-03-01T00:00:00.000Z"
        assert invoiced["margin_pct"] == pytest.approx(0.1000, abs=1e-9)
        assert invoiced["volume_band"] == "NONE"
        assert invoiced["invoice_amount_cents"] == 900000
        assert invoiced["margin_value_cents"] == 100000
        assert_order_invoice_margin_conservation(invoiced)

        pending = read_invoice(second["id"])
        assert pending["status"] == "PENDING"
        assert pending["invoice_amount_cents"] == 900000, (
            "the twin's margin structure is already resolved and stored while it waits"
        )

        assert read_partner(partner["id"])["trailing_revenue_cents"] == 900000, (
            "the PENDING twin contributes nothing, so the figure is 900000 and not 1800000"
        )

    def test_a_zero_commitment_reads_as_full_attainment_until_the_denominator_moves(self, api):
        """PRD §3.1: "Because a commitment of 0 makes the partner vacuously compliant on
        marketing, `marketing_attainment_pct` reads exactly 1.0000 on such a partner."
        PRD §3.1: "Amending the commitment does not merely store a number:
        `marketing_attainment_pct` is immediately recomputed against the new denominator,
        `portal_entitlement_level` is recomputed from the resulting standing, and the partner's
        `version` advances by 1."

        Design: Corner/calculations/marketing_attainment_zero_commitment_is_vacuously_compliant
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        before = read_partner(partner["id"])
        assert before["marketing_qualified_spend_cents"] == 0
        assert before["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert_rate_precision(before["marketing_attainment_pct"])

        after = validate_success(
            api.update_partner(partner["id"], {"marketing_commitment_cents": 800000}, ANALYST)
        )
        assert after["marketing_commitment_cents"] == 800000
        assert after["marketing_attainment_pct"] == pytest.approx(0.0, abs=1e-9)
        assert after["marketing_qualified_spend_cents"] == 0, (
            "the amendment moves the denominator only"
        )
        assert after["version"] == before["version"] + 1

        assert after["tier_status"] == "COMPLIANT", (
            "attainment below the compliance minimum does not by itself change standing"
        )
        assert after["portal_entitlement_level"] == "BASIC"


class TestWeightedScoreAndBandThresholds:
    def test_the_non_terminating_credit_component_is_rounded_only_after_weighting(self, api):
        """PRD §3.9: "The score is 40 times the certification component plus 35 times the revenue
        component plus 25 times the marketing component, rounded half-up to two decimal places
        **once, at the end**; the three components are held as exact fractions and are never
        rounded individually, because rounding each one before weighting would drift the score."
        PRD §2.5: "Weighted-score components are the mirror image of the first rule: the components
        are held as exact fractions, the weighted sum is computed from those exact fractions, and
        the rounding to two decimal places happens once at the very end — rounding each component
        before weighting would drift the score."

        Design: Corner/calculations/tier_score_rounds_once_after_weighting
        """
        set_clock("2026-02-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        add_certification(partner["id"], engineer_name="Kit Vance", track="TECH_EXPERT")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="SALES_PRO")

        review = prepare_review(partner["id"], findings_count=0)
        assert review["provisional_cert_credit"] == 5, "4 expert credits plus 1 sales credit"
        assert review["provisional_revenue_cents"] == 0
        assert review["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert review["provisional_score"] == pytest.approx(41.67, abs=1e-9), (
            "40 * 5/12 + 0 + 25 = 41.6666..., which rounds half-up to 41.67 and not to 41.80"
        )
        assert_score_precision(review["provisional_score"])
        assert review["recommended_tier"] == "REGISTERED"

        decided = validate_success(
            api.decide_performance_review(review["id"], {"decision": "APPROVE"}, DIRECTOR)
        )
        assert decided["final_cert_credit"] == 5
        assert decided["final_revenue_cents"] == 0
        assert decided["final_score"] == pytest.approx(41.67, abs=1e-9)
        assert_score_precision(decided["final_score"])
        assert decided["approved_tier"] == "REGISTERED", "41.67 sits below the SILVER gate of 45"

        settled = read_partner(partner["id"])
        assert settled["tier"] == "REGISTERED"
        assert settled["cert_credit_total"] == 5
        assert settled["tier_status"] == "COMPLIANT"

    def test_one_cent_of_list_price_decides_the_mid_band_and_inverts_the_invoices(self, api):
        """PRD §3.6: "Multiply `list_amount_cents` by one minus the preliminary margin and round
        half-up to a whole number of cents. This figure exists only to select the band; it is never
        stored."
        PRD §3.6: "Read `volume_band` off the preliminary net alone: `HIGH` when the preliminary net
        is at least 20000000 cents (two hundred thousand dollars), `MID` when it is at least 5000000
        cents (fifty thousand dollars) but below the high threshold, and `NONE` otherwise."

        Design: Corner/calculations/volume_band_mid_minimum_boundary_one_cent_apart
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Northwind Distribution", partner_type="DISTRIBUTOR"
        )

        dearer = create_order(
            partner["id"], order_type="STOCKING", list_amount_cents=5_681_818
        )
        cheaper = create_order(
            partner["id"], order_type="STOCKING", list_amount_cents=5_681_817
        )

        assert dearer["volume_band"] == "MID", (
            "5681818 * 0.88 rounds half-up to exactly 5000000, the MID minimum"
        )
        assert dearer["margin_pct"] == pytest.approx(0.1350, abs=1e-9)
        assert dearer["invoice_amount_cents"] == 4914773
        assert dearer["margin_value_cents"] == 767045
        assert_rate_precision(dearer["margin_pct"])

        assert cheaper["volume_band"] == "NONE", "5681817 * 0.88 rounds to 4999999, one cent short"
        assert cheaper["margin_pct"] == pytest.approx(0.1200, abs=1e-9)
        assert cheaper["invoice_amount_cents"] == 4999999
        assert cheaper["margin_value_cents"] == 681818

        assert cheaper["invoice_amount_cents"] > dearer["invoice_amount_cents"], (
            "the cheaper order invoices for more, which is the observable signature of the band"
        )
        for order in (dearer, cheaper):
            assert (
                order["list_amount_cents"] - order["invoice_amount_cents"]
                == order["margin_value_cents"]
            )
            assert_order_invoice_margin_conservation(order)

    def test_an_entry_tier_fund_period_is_sized_at_zero_and_funds_no_claim(self, api):
        """PRD §3.7: "A `REGISTERED` partner accrues nothing and receives no base grant, so its
        period is sized at 0 and no claim can ever be paid from it."
        PRD §3.7: "`requested_cents` must be at or below the period's current `available_cents`
        (otherwise `ERR_MDF_ALLOCATION_INSUFFICIENT` — which is also what a claim against a
        `REGISTERED` partner's zero-sized period always produces)."

        Design: Corner/calculations/registered_tier_accrues_no_mdf_budget_at_all
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Aster Systems", partner_type="RESELLER", marketing_commitment_cents=0
        )
        create_and_invoice_order(
            partner["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000
        )
        funded = read_partner(partner["id"])
        assert funded["trailing_revenue_cents"] == 900000
        assert funded["tier"] == "REGISTERED"

        set_clock("2026-04-01T00:00:00.000Z")
        allocation = open_allocation(
            partner["id"],
            period_start="2026-04-01T00:00:00.000Z",
            period_end="2026-06-30T23:59:59.999Z",
        )
        assert_mdf_allocation(allocation)
        assert allocation["basis_revenue_cents"] == 900000, (
            "the 900000 was booked strictly before period_start, so it is in the basis"
        )
        assert allocation["allocated_cents"] == 0, "0.0 accrual rate plus a 0 base grant"
        assert allocation["committed_cents"] == 0
        assert allocation["paid_cents"] == 0
        assert allocation["expired_cents"] == 0
        assert allocation["available_cents"] == 0
        assert_mdf_fund_conservation(allocation)

        validate_error(
            api.create_mdf_claim(
                {
                    "allocation_id": allocation["id"],
                    "activity_type": "DIGITAL_CAMPAIGN",
                    "requested_cents": 1000,
                },
                make_partner_headers(partner["id"]),
            ),
            ApiErrorId.ERR_MDF_ALLOCATION_INSUFFICIENT.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_allocation_mdf_claims(allocation["id"], ANALYST)
        )
        assert rows == []
        assert_paging_meta(meta, limit=10, offset=0, total_count=0, has_more=False)
        assert read_allocation(allocation["id"])["committed_cents"] == 0


class TestWindowGeometryDoctrineAndLadder:
    def test_a_candidate_starting_on_the_cooldown_end_conflicts_and_one_millisecond_later_does_not(
        self, api
    ):
        """PRD §3.2: "For each incumbent so selected, the blocked interval runs from that
        incumbent's `effective_from` through its `effective_until` extended by a cooldown of
        fourteen days, and the candidate conflicts with it unless the candidate starts strictly
        after the blocked interval ends or the candidate ends strictly before the blocked interval
        starts."
        PRD §3.2: "a candidate starting exactly at the end of a blocked interval conflicts; a
        candidate starting one millisecond later is allowed"

        Design: Corner/calculations/mapping_cooldown_end_is_inclusive_to_the_millisecond
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        account = create_account()
        first_version = read_account(account["id"])["version"]

        incumbent = propose_mapping(
            partner["id"],
            account["id"],
            first_version,
            effective_from="2026-05-01T00:00:00.000Z",
            effective_until="2026-05-31T23:59:59.999Z",
            product_line="ANALYTICS_ADDON",
            exclusivity_scope="FULL",
        )
        assert incumbent["mapping_status"] == "PROPOSED"
        observed_version = read_account(account["id"])["version"]
        assert observed_version == first_version + 1

        def candidate(effective_from):
            return {
                "partner_id": partner["id"],
                "account_id": account["id"],
                "product_line": "SUPPORT_SERVICES",
                "exclusivity_scope": "PRODUCT_LINE",
                "effective_from": effective_from,
                "effective_until": "2026-08-31T23:59:59.999Z",
                "expected_account_version": observed_version,
            }

        validate_error(
            api.create_account_mapping(candidate("2026-06-14T23:59:59.999Z"), ANALYST),
            ApiErrorId.ERR_MAPPING_WINDOW_CONFLICT.value,
            409,
        )

        untouched = validate_success(api.get_account_mapping(incumbent["id"], ANALYST))
        assert untouched["mapping_status"] == "PROPOSED"
        assert untouched["effective_until"] == "2026-05-31T23:59:59.999Z"
        assert untouched["counter_round"] == 0
        assert read_account(account["id"])["version"] == observed_version, (
            "a rejected create writes nothing, so the same observed version is still current"
        )

        accepted = validate_success(
            api.create_account_mapping(candidate("2026-06-15T00:00:00.000Z"), ANALYST), 201
        )
        assert accepted["mapping_status"] == "PROPOSED"
        assert accepted["effective_from"] == "2026-06-15T00:00:00.000Z"

    def test_a_full_scope_incumbent_blocks_a_candidate_on_a_different_product_line(self, api):
        """PRD §3.2: "A scope of `FULL` blocks every product line on the account; a scope of
        `PRODUCT_LINE` blocks only the named `product_line`."
        PRD §3.2: "It is tested against every other agreement on the same account whose
        `mapping_status` is `PROPOSED`, `COUNTERED`, `ACTIVE` or `EXPIRED`, restricted to those
        whose scope overlaps the candidate's — which means either agreement having
        `exclusivity_scope` `FULL`, or both naming the same `product_line`."

        Design: Corner/calculations/mapping_cooldown_end_is_inclusive_to_the_millisecond
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        account = create_account()

        incumbent = propose_mapping(
            partner["id"],
            account["id"],
            read_account(account["id"])["version"],
            effective_from="2026-05-01T00:00:00.000Z",
            effective_until="2026-05-31T23:59:59.999Z",
            product_line="ANALYTICS_ADDON",
            exclusivity_scope="FULL",
        )
        assert incumbent["exclusivity_scope"] == "FULL"
        assert incumbent["product_line"] == "ANALYTICS_ADDON"

        validate_error(
            api.create_account_mapping(
                {
                    "partner_id": partner["id"],
                    "account_id": account["id"],
                    "product_line": "SUPPORT_SERVICES",
                    "exclusivity_scope": "PRODUCT_LINE",
                    "effective_from": "2026-06-14T23:59:59.999Z",
                    "effective_until": "2026-08-31T23:59:59.999Z",
                    "expected_account_version": read_account(account["id"])["version"],
                },
                ANALYST,
            ),
            ApiErrorId.ERR_MAPPING_WINDOW_CONFLICT.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_account_mappings(ANALYST, params={"account_id": account["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]

    def test_a_direct_sales_case_applies_the_coverage_doctrine_while_storing_both(self, api):
        """PRD §3.5: "Which of the two stored figures is authoritative is recorded in
        `applied_variant`, whose value is `REGISTRATION_FIRST` on a `PARTNER_VS_PARTNER` case and
        `COVERAGE_FIRST` on a `PARTNER_VS_DIRECT` case, and `recommended_resolution` is a copy of
        whichever of the two doctrine fields `applied_variant` names."
        PRD §3.5: "If the account's `coverage_state` is `CHANNEL_PROTECTED` and `detected_at` falls
        strictly before the account's `protected_until`, then the recommendation is `GRANT_SUBJECT`
        when the account's `protected_partner_id` equals the subject registration's `partner_id`"

        Design: Corner/calculations/conflict_recommendation_variant_selected_by_conflict_type
        """
        seed = seed_partner_vs_direct_conflict(
            clock="2026-04-01T00:00:00.000Z",
            pursuit_clock="2026-04-05T00:00:00.000Z",
            pursuit_note="field sales owns this renewal",
        )
        case = seed["case"]

        assert case["conflict_type"] == "PARTNER_VS_DIRECT"
        assert case["applied_variant"] == "COVERAGE_FIRST"
        assert case["recommended_resolution_coverage_first"] == "GRANT_SUBJECT"
        assert case["recommended_resolution"] == "GRANT_SUBJECT"
        assert case["recommended_resolution_registration_first"] == "GRANT_SUBJECT", (
            "the chronological doctrine is stored even though it was not the applied one"
        )
        assert case["status"] == "OPEN"
        assert case["escalation_level"] == 0
        assert case["subject_registration_id"] == seed["incumbent_registration"]["id"]
        assert case["counter_registration_id"] is None
        assert case["detected_at"] == "2026-04-05T00:00:00.000Z"

        account = seed["account"]
        assert account["direct_pursuit_declared_at"] == "2026-04-05T00:00:00.000Z"
        assert account["coverage_state"] == "CHANNEL_PROTECTED"
        assert account["protected_until"] == "2026-05-01T00:00:00.000Z"
        assert account["protected_partner_id"] == seed["incumbent"]["id"]

    def test_a_compliant_gold_partner_over_its_credit_floor_reads_the_third_rung(self, api):
        """PRD §3.1: "The portal ladder has four rungs in ascending order: `BASIC`, `STANDARD`,
        `PREMIUM`, `ELITE`. A partner's starting rung is read straight off its `tier` — a
        `REGISTERED` partner starts at the first rung, `SILVER` at the second, `GOLD` at the third
        and `PLATINUM` at the fourth."
        PRD §3.1: "Otherwise the service counts demotions: one demotion if `tier_status` is
        `PROBATION`, and one further demotion if `cert_credit_total` has fallen below the
        certification floor for the partner's tier. That floor is 0 credits for `REGISTERED`, 2 for
        `SILVER`, 6 for `GOLD` and 12 for `PLATINUM`."

        Design: Corner/calculations/portal_entitlement_index_tracks_the_tier_ladder
        """
        seed = seed_gold_distributor(
            clock="2026-01-05T00:00:00.000Z", seed_list_amount_cents=10_000_000
        )
        invoice = seed["seed_invoice"]
        assert invoice["margin_pct"] == pytest.approx(0.1350, abs=1e-9)
        assert invoice["invoice_amount_cents"] == 8650000
        assert invoice["volume_band"] == "MID"

        review = seed["review"]
        assert review["final_cert_credit"] == 12
        assert review["final_revenue_cents"] == 8650000
        assert review["final_score"] == pytest.approx(71.06, abs=1e-9), (
            "40 * 1.0 + 35 * 8650000/50000000 + 25 * 1.0 = 71.055, rounded half-up once"
        )
        assert_score_precision(review["final_score"])
        assert review["approved_tier"] == "GOLD"

        partner = seed["partner"]
        assert partner["tier"] == "GOLD"
        assert partner["tier_status"] == "COMPLIANT"
        assert partner["cert_credit_total"] == 12
        assert partner["portal_entitlement_level"] == "PREMIUM", (
            "twelve credits clear the GOLD floor of 6, so the third rung takes no demotion"
        )
