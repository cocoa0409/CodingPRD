"""Scoring and money arithmetic: screening variants, incrementality, fraud decay,
network fee variance, cumulative clawback and rate-card selection."""

from typing import Any, Dict, Tuple

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ERR_NETWORK_FEE_VARIANCE
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_object_response,
    assert_one_decimal_score,
    assert_total_count,
    assert_version_unchanged,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

SETUP_CLOCK = f.JUL_05_00_00
SETTLEMENT_CLOCK = f.AUG_05_00_00

#: §3.7 anchors the trailing decay on `detected_at`, so both cases below are
#: filed with an explicit instant rather than the filing time.
CASE_DETECTED_96_DAYS_BACK = "2026-05-01T00:00:00.000Z"
CASE_DETECTED_10_DAYS_BACK = "2026-07-26T00:00:00.000Z"
#: The instant both fraud figures below are evaluated at: 96 days after the stale
#: case's `detected_at` and 10 whole days after the recent one's.
FRAUD_CLOCK = f.AUG_05_00_00

#: The narrower §3.3 window of the rate card that must win selection.
JUN_01_2026 = "2026-06-01T00:00:00.000Z"
SEP_01_2026 = "2026-09-01T00:00:00.000Z"


def _batch_over_one_attributed_order(
    api, fee_bps: int, order_total_cents: int
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A DRAFT batch holding one line for one attributed, validated order.

    Registers the network at ``fee_bps``, activates a `CONTENT` partner with a
    `VALID` `W9` at a zero treaty rate, attributes one returning-customer order
    of ``order_total_cents`` at the 400-bps returning rate, then moves the clock
    thirty-plus days past `placed_at` so the §3.6 validation sweep inside batch
    generation promotes the order and the batch claims its `ACCRUAL`.
    """
    program = fixtures.build_program(api, setup_clock=SETUP_CLOCK, fee_bps=fee_bps)
    fixtures.valid_tax_document(api, program["affiliate_id"], treaty_withholding_bps=0)
    order = fixtures.attributed_order(
        api, program, order_total_cents=order_total_cents
    )
    fixtures.pin_clock(api, SETTLEMENT_CLOCK)
    batch = fixtures.generate_batch(api, program["network_id"])
    return program, order, batch


class TestRestrictedScreenVariant:
    def test_restricted_promo_methods_apply_extra_multiplier_and_wider_penalty_cap(
        self, api
    ):
        """Two identical screens diverge only because one applicant declared a coupon feed.

        PRD §3.2: "Where `declared_promo_methods` contains neither
        `TRADEMARK_PAID_SEARCH` nor `COUPON_FEED`, the standard screen applies: the
        penalty is capped at 30 points and no further multiplier is used. Where
        `declared_promo_methods` contains `TRADEMARK_PAID_SEARCH` or `COUPON_FEED`, the
        restricted screen applies instead: the penalty cap rises to 45 points, and the
        product of base and source multiplier is additionally multiplied by 0.90 before
        the penalty is subtracted."

        Design: Corner/calculations/restricted_screen_variant_applies_multiplier_and_wider_penalty_cap
        """
        fixtures.pin_clock(api, SETUP_CLOCK)
        network = fixtures.create_network(api)

        standard_partner = fixtures.register_affiliate(
            api,
            network["id"],
            partner_type="CONTENT",
            legal_name="Beacon Content LLC",
        )
        restricted_partner = fixtures.register_affiliate(
            api,
            network["id"],
            partner_type="COUPON",
            legal_name="SaverFeed Coupons LLC",
        )

        standard_application = fixtures.file_application(
            api,
            standard_partner["id"],
            site_url="https://beacon.example",
            primary_traffic_source="ORGANIC_SEARCH",
            declared_promo_methods=["EDITORIAL_CONTENT"],
        )
        restricted_application = fixtures.file_application(
            api,
            restricted_partner["id"],
            site_url="https://saverfeed.example",
            primary_traffic_source="ORGANIC_SEARCH",
            declared_promo_methods=["COUPON_FEED"],
        )

        # §3.2: base = 0.45*72 + 0.35*88 + 0.20*(100 - 450/100) = 32.4 + 30.8 + 19.1
        # = 82.3, and `ORGANIC_SEARCH` contributes the "1.00" source multiplier.
        measurements = dict(
            domain_authority=72,
            content_originality_pct=88,
            broken_link_ratio_bps=450,
            brand_safety_flag_count=5,
            restricted_vertical_overlap_bps=0,
        )

        screened_standard = assert_object_response(
            api.screen_application(
                standard_application["id"],
                f.screen_payload(**measurements),
                COMPLIANCE_ANALYST,
            )
        )
        screened_restricted = assert_object_response(
            api.screen_application(
                restricted_application["id"],
                f.screen_payload(**measurements),
                COMPLIANCE_ANALYST,
            )
        )

        # 82.3 * 1.00 - min(30, 10 * 5) = 82.3 - 30 = 52.3
        assert_one_decimal_score(screened_standard, "site_quality_score", 52.3)
        # 82.3 * 1.00 * 0.90 = 74.07, less min(45, 10 * 5) = 45, rounded once: 29.1
        assert_one_decimal_score(screened_restricted, "site_quality_score", 29.1)
        assert (
            screened_standard["site_quality_score"]
            != screened_restricted["site_quality_score"]
        ), "the restricted screen must not score the same inputs as the standard screen"

        # §3.2: brand suitability "starts at 100, subtracts one hundredth of
        # `restricted_vertical_overlap_bps`, and subtracts a further 12 points for each
        # brand-safety flag": 100 - 0 - 12 * 5 = 40.0 on both applications.
        # §3.2: "It is `FAIL` when `site_quality_score` is strictly below 45.0, or when
        # `brand_suitability_score` is strictly below 70.0 regardless of site quality."
        for screened in (screened_standard, screened_restricted):
            assert_one_decimal_score(screened, "brand_suitability_score", 40.0)
            assert_fields(
                screened,
                {"screening_outcome": "FAIL", "review_state": "SCREENED"},
            )


class TestIncrementalityScoreClamp:
    def test_coupon_assisted_conversion_clamps_incrementality_score_at_zero(self, api):
        """A coupon partner's one coupon-assisted sale drives its raw score negative, and it lands at 0.

        PRD §3.5: "The score is then fifty-five hundredths of the new-customer share,
        plus forty-five hundredths of the amount by which the coupon-assisted share falls
        short of 10,000, minus a fixed discount chosen by `partner_type`: 0 for
        `CONTENT`, 0 for `INFLUENCER`, 500 for `PAID_SEARCH`, 500 for `SUB_NETWORK`, 1500
        for `COUPON` and 2000 for `LOYALTY_CASHBACK`. That figure is rounded half up to a
        whole basis point and clamped into the range 0 to 10000, and the result is
        `incrementality_score_bps`."

        Design: Corner/calculations/incrementality_score_clamps_at_zero_after_coupon_assisted_conversion
        """
        program = fixtures.build_program(
            api,
            setup_clock=SETUP_CLOCK,
            partner_type="COUPON",
            fee_bps=0,
            policy_scope=["COUPON"],
            new_customer_rate_bps=900,
            returning_customer_rate_bps=400,
            application_kwargs={
                "site_url": "https://saverfeed.example",
                "declared_promo_methods": ["COUPON_FEED"],
            },
            screen_kwargs={
                "domain_authority": 95,
                "content_originality_pct": 100,
                "broken_link_ratio_bps": 0,
                "brand_safety_flag_count": 0,
                "restricted_vertical_overlap_bps": 0,
            },
        )
        affiliate_id = program["affiliate_id"]

        # §3.2 restricted screen: (0.45*95 + 0.35*100 + 0.20*100) * 1.00 * 0.90
        # = 97.75 * 0.90 = 87.975, no penalty, rounded once to one decimal.
        assert_one_decimal_score(program["application"], "site_quality_score", 88.0)
        assert_one_decimal_score(program["application"], "brand_suitability_score", 100.0)

        # §3.5 fresh-partner table: a `COUPON` partner starts at 4500 - 1500 = 3000, `LOW`.
        before = fixtures.read_affiliate(api, affiliate_id)
        assert_field(before, "status", "ACTIVE")
        assert_bps(before, "incrementality_score_bps", 3000)
        assert_field(before, "incrementality_tier", "LOW")

        link_id = program["link_id"]
        fixtures.ingest_click(api, link_id, occurred_at=f.JUL_04_10_00, device_id="D1")
        conversion = fixtures.create_conversion(
            api,
            order_ref="ORD-CLAMP-1",
            order_total_cents=100000,
            product_category="APPAREL",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            coupon_code_used="SAVE10",
        )

        attributed = assert_object_response(
            api.attribute_conversion(
                conversion["id"],
                f.attribute_payload(conversion["version"]),
                TRACKING_INGESTOR,
            )
        )

        # §3.5: the coupon override forces `INCREMENTALITY_ADJUSTED`, whose
        # `credit_share_bps` is 3000: gross 100000*400/10000 = 4000, payable 30% of it.
        assert_field(attributed, "attribution_status", "CREDIT_REDUCED")
        assert_cents(attributed, "gross_commission_cents", 4000)
        assert_cents(attributed, "payable_commission_cents", 1200)

        after = fixtures.read_affiliate(api, affiliate_id)
        assert_fields(
            after,
            {
                "attributed_conversion_count": 1,
                "new_customer_attributed_count": 0,
                "coupon_assisted_conversion_count": 1,
            },
        )
        # coupon-assisted share 1*10000/1 = 10000, new-customer share 0, so the raw
        # figure is 0.55*0 + 0.45*(10000 - 10000) - 1500 = -1500, clamped up to 0.
        assert_bps(after, "incrementality_score_bps", 0)
        # §3.5: "`LOW` when the score is 3500 or below".
        assert_field(after, "incrementality_tier", "LOW")
        assert_cents(after, "accrued_balance_cents", 1200)

        # §3.5: "An `ACCRUAL` ledger entry is appended for the partner in the amount of
        # the payable commission, positive in sign."
        rows = assert_total_count(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"affiliate_id": affiliate_id, "entry_type": "ACCRUAL"},
            ),
            1,
        )
        assert_cents(rows[0], "amount_cents", 1200)


class TestTrailingFraudScoreWindowAndDecay:
    def test_stale_case_drops_from_trailing_window_and_cleared_case_is_discounted(
        self, api
    ):
        """A 96-day-old open case counts in full point-in-time yet nothing in the trailing figure.

        PRD §3.7: "It counts cases in **any** state, `VERIFIED_CLEARED` included, whose
        `detected_at` is at or after ninety days before the current logical clock; a case
        older than that drops out of the figure entirely. Each surviving case contributes
        its `severity_weight` multiplied by an age decay and by a state factor."

        Design: Corner/calculations/fraud_trailing_window_drops_stale_case_and_discounts_cleared_case
        """
        fixtures.pin_clock(api, FRAUD_CLOCK)
        network = fixtures.create_network(api)
        partner = fixtures.activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]

        # §3.7 severity table: 20 for `TRADEMARK_BIDDING`, 40 for `COOKIE_STUFFING`.
        stale_case = fixtures.open_case(
            api,
            affiliate_id,
            violation_type="TRADEMARK_BIDDING",
            detected_at=CASE_DETECTED_96_DAYS_BACK,
        )
        recent_case = fixtures.open_case(
            api,
            affiliate_id,
            violation_type="COOKIE_STUFFING",
            detected_at=CASE_DETECTED_10_DAYS_BACK,
        )
        assert stale_case["severity_weight"] == 20, (
            "§3.7 copies 20 onto a TRADEMARK_BIDDING case at creation"
        )
        assert recent_case["severity_weight"] == 40, (
            "§3.7 copies 40 onto a COOKIE_STUFFING case at creation"
        )

        before = fixtures.read_affiliate(api, affiliate_id, COMPLIANCE_ANALYST)
        # §3.7 point-in-time: both cases are `OPEN`, it "applies no decay at all and
        # ignores `detected_at` entirely", so 20 + 40 = 60.
        assert_field(before, "fraud_risk_score", 60)
        # §3.7: auto-suspension fires only at 70 or above, so 60 leaves the partner alone.
        assert_field(before, "status", "ACTIVE")
        # Trailing: the 2026-05-01 case is 96 days old, outside the ninety-day window and
        # so contributes nothing; the 2026-07-26 case is 10 whole days old, so its decay
        # is 1.00 - 0.01*10 = 0.90 and its `OPEN` state factor is 1.00: 40*0.90 = 36.0.
        assert_one_decimal_score(before, "fraud_risk_score_trailing", 36.0)

        fixtures.clear_case(api, recent_case["id"], affiliate_id)

        cleared = assert_object_response(
            api.get_violation_case(recent_case["id"], COMPLIANCE_ANALYST)
        )
        assert_field(cleared, "state", "VERIFIED_CLEARED")
        still_open = assert_object_response(
            api.get_violation_case(stale_case["id"], COMPLIANCE_ANALYST)
        )
        assert_field(still_open, "state", "OPEN")

        after = fixtures.read_affiliate(api, affiliate_id, COMPLIANCE_ANALYST)
        # §3.7: "a `VERIFIED_CLEARED` case contributes exactly zero" to the point-in-time
        # figure, leaving only the stale but still-open 20.
        assert_field(after, "fraud_risk_score", 20)
        # §3.7: "The state factor is 0.25 for a `VERIFIED_CLEARED` case and 1.00 for
        # every other state": 40 * 0.90 * 0.25 = 9.0, the stale case still excluded.
        assert_one_decimal_score(after, "fraud_risk_score_trailing", 9.0)
        assert after["fraud_risk_score_trailing"] < after["fraud_risk_score"], (
            "§3.7 allows the trailing figure to sit strictly below the point-in-time one"
        )
        assert_field(after, "open_violation_case_count", 1)

        assert_total_count(
            api.list_violation_cases(
                COMPLIANCE_ANALYST, {"affiliate_id": affiliate_id, "state": "OPEN"}
            ),
            1,
        )


class TestNetworkFeeVarianceTolerance:
    def test_statement_gross_mismatch_fails_before_any_fee_arithmetic(self, api):
        """A statement gross that differs at all from the retailer's own gross kills validation.

        PRD §3.9: "The gross check runs first and is exact: if `statement_gross_cents`
        differs at all from the batch's own recomputed `gross_commission_cents`, the
        request fails with the network-fee-variance error and nothing whatsoever is
        written."

        Design: Corner/calculations/network_fee_variance_tolerance_boundary_and_gross_mismatch_rejected
        """
        _program, order, batch = _batch_over_one_attributed_order(
            api, fee_bps=375, order_total_cents=133000
        )

        # §3.5: gross = 133000 * 400 / 10000 = 5320 on the returning-customer rate.
        assert_cents(order["conversion"], "gross_commission_cents", 5320)
        assert_cents(batch, "gross_commission_cents", 5320)
        # §3.9: the line's fee is 5320 * 375 / 10000 = 199.5, "rounded half up to a whole
        # cent", so the batch's own fee figure the statement is measured against is 200.
        assert_cents(batch, "network_fee_cents", 200)
        batch_version = batch["version"]

        # The fee the statement quotes matches the batch exactly; only the gross is wrong.
        response = api.validate_payout_batch(
            batch["id"],
            f.validate_batch_payload(
                statement_gross_cents=5000, statement_fee_cents=200
            ),
            FINANCE_ANALYST,
        )

        assert_error_response(response, ERR_NETWORK_FEE_VARIANCE, 422)

        unchanged = fixtures.read_batch(api, batch["id"])
        assert_field(unchanged, "state", "DRAFT")
        assert_version_unchanged(unchanged, batch_version, "payout batch")

    def test_fee_variance_of_fifty_bps_is_accepted_and_annotates_only(self, api):
        """A 100-bps fee variance is refused while exactly 50 bps is accepted as an annotation.

        PRD §3.9: "Otherwise a `network_fee_variance_bps` of 50 or less sets
        `reconciliation_status` to `ACCEPTED_WITH_VARIANCE` — the boundary is inclusive —
        and anything larger fails with the network-fee-variance error."

        Design: Corner/calculations/network_fee_variance_tolerance_boundary_and_gross_mismatch_rejected
        """
        _program, _order, batch = _batch_over_one_attributed_order(
            api, fee_bps=375, order_total_cents=133000
        )
        batch_id = batch["id"]
        assert_cents(batch, "gross_commission_cents", 5320)
        assert_cents(batch, "network_fee_cents", 200)
        assert_cents(batch, "net_payable_cents", 5120)
        batch_version = batch["version"]

        # §3.9: variance 202 - 200 = 2 cents, so |2| * 10000 / 200 = 100 bps > 50.
        rejected = api.validate_payout_batch(
            batch_id,
            f.validate_batch_payload(
                statement_gross_cents=5320, statement_fee_cents=202
            ),
            FINANCE_ANALYST,
        )
        assert_error_response(rejected, ERR_NETWORK_FEE_VARIANCE, 422)
        still_draft = fixtures.read_batch(api, batch_id)
        assert_field(still_draft, "state", "DRAFT")
        assert_version_unchanged(still_draft, batch_version, "payout batch")

        # §3.9: variance 201 - 200 = 1 cent, so 1 * 10000 / 200 = 50 bps, exactly the
        # inclusive tolerance.
        validated = assert_object_response(
            api.validate_payout_batch(
                batch_id,
                f.validate_batch_payload(
                    statement_gross_cents=5320, statement_fee_cents=201
                ),
                FINANCE_ANALYST,
            )
        )

        assert_fields(
            validated,
            {"state": "VALIDATED", "reconciliation_status": "ACCEPTED_WITH_VARIANCE"},
        )
        assert_cents(validated, "network_fee_variance_cents", 1)
        assert_bps(validated, "network_fee_variance_bps", 50)
        # §3.9: "Accepting a variance **annotates only**: it records the two variance
        # fields and the status, and adjusts neither `network_fee_cents`, nor
        # `net_payable_cents`, nor any ledger entry."
        assert_cents(validated, "network_fee_cents", 200)
        assert_cents(validated, "net_payable_cents", 5120)

        line = fixtures.first_line(api, batch_id)
        assert_cents(line, "network_fee_cents", 200)
        assert_cents(line, "net_cents", 5120)

        rows = assert_total_count(
            api.list_ledger_entries(FINANCE_ANALYST, {"payout_batch_id": batch_id}), 1
        )
        assert_field(rows[0], "entry_type", "ACCRUAL")
        assert_cents(rows[0], "amount_cents", 5320)


class TestCumulativeClawbackOnPartialReturns:
    def test_two_partial_returns_difference_against_the_cumulative_target_total(
        self, api
    ):
        """The second partial return claws back only the balance of the cumulative target.

        PRD §3.6: "The target total is the order's `payable_commission_cents` multiplied
        by the cumulative returned amount, divided by the order's `order_total_cents`, and
        rounded half up to a whole cent. The magnitude of this adjustment is that target
        total minus the `clawed_back_cents` already recorded on the order, and
        `clawed_back_cents` accumulates to the new target while `returned_amount_cents`
        accumulates the merchandise value."

        Design: Corner/calculations/two_partial_returns_clawback_against_cumulative_target_total
        """
        program, order, batch = _batch_over_one_attributed_order(
            api, fee_bps=0, order_total_cents=100000
        )
        conversion_id = order["conversion_id"]
        affiliate_id = program["affiliate_id"]
        line_id = fixtures.first_line(api, batch["id"])["id"]

        # §3.5: gross = 100000 * 400 / 10000 = 4000, and a `MEDIUM` `CONTENT` partner
        # takes the full 10000-bps credit share, so the payable equals the gross.
        assert_cents(order["conversion"], "gross_commission_cents", 4000)
        assert_cents(order["conversion"], "payable_commission_cents", 4000)
        validated_order = fixtures.read_conversion(api, conversion_id)
        assert_field(validated_order, "validation_status", "VALIDATED")

        first = assert_object_response(
            api.adjust_order(
                conversion_id,
                f.order_adjustment_payload(
                    "PARTIAL_RETURN", 30000, occurred_at="2026-08-05T01:00:00.000Z"
                ),
                FINANCE_ANALYST,
            )
        )

        # Target total = 4000 * 30000 / 100000 = 1200, less 0 already clawed back.
        assert_cents(first, "returned_amount_cents", 30000)
        assert_cents(first, "clawed_back_cents", 1200)
        # §3.6: below the full order total the money dimension "stays `VALIDATED` so that
        # further partial returns can follow", and `attribution_status` "is **not** changed".
        assert_fields(
            first,
            {
                "validation_status": "VALIDATED",
                "attribution_status": "AFFILIATE_ATTRIBUTED",
            },
        )

        after_first = fixtures.read_line(api, line_id)
        assert_cents(after_first, "gross_cents", 4000)
        assert_cents(after_first, "clawback_cents", 1200)
        assert_cents(after_first, "net_before_fees_cents", 2800)
        assert_cents(after_first, "net_cents", 2800)
        # §3.9: the 2500-cent minimum "is inclusive on the pay side", and 2800 clears it.
        assert_field(after_first, "state", "INCLUDED")

        clawbacks = assert_total_count(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"conversion_id": conversion_id, "entry_type": "CLAWBACK"},
            ),
            1,
        )
        assert_cents(clawbacks[0], "amount_cents", -1200)

        second = assert_object_response(
            api.adjust_order(
                conversion_id,
                f.order_adjustment_payload(
                    "PARTIAL_RETURN", 70000, occurred_at="2026-08-05T02:00:00.000Z"
                ),
                FINANCE_ANALYST,
            )
        )

        # Target total = 4000 * 100000 / 100000 = 4000, less the 1200 already recorded,
        # so this event moves exactly 2800 rather than a freshly computed 2800-cent slice.
        assert_cents(second, "returned_amount_cents", 100000)
        assert_cents(second, "clawed_back_cents", 4000)
        assert_fields(
            second,
            {
                "validation_status": "CLAWED_BACK",
                "attribution_status": "AFFILIATE_ATTRIBUTED",
            },
        )

        after_second = fixtures.read_line(api, line_id)
        assert_cents(after_second, "clawback_cents", 4000)
        assert_cents(after_second, "net_cents", 0)
        # §3.6: "if the recomputed net amount on that line falls below the 2,500-cent
        # minimum, the line moves `INCLUDED → HELD_BELOW_MINIMUM`".
        assert_field(after_second, "state", "HELD_BELOW_MINIMUM")

        final_batch = fixtures.read_batch(api, batch["id"])
        assert_cents(final_batch, "gross_commission_cents", 4000)
        assert_cents(final_batch, "clawback_cents", 4000)
        # §3.9: the payable total counts "only lines that are `INCLUDED` or `PAID`".
        assert_cents(final_batch, "net_payable_cents", 0)

        rows, _meta = assert_list_response(
            api.list_ledger_entries(FINANCE_ANALYST, {"conversion_id": conversion_id})
        )
        assert len(rows) == 3, (
            "the order must carry one ACCRUAL and two CLAWBACK entries, never an edit"
        )
        assert sum(row["amount_cents"] for row in rows) == 0, (
            "the signed ledger for a fully returned order must net back to zero"
        )
        assert sorted(
            row["amount_cents"] for row in rows if row["entry_type"] == "CLAWBACK"
        ) == [-2800, -1200], (
            "the two clawback magnitudes must be 1200 then the 2800 balance of the target"
        )

        partner = fixtures.read_affiliate(api, affiliate_id)
        assert_cents(partner, "accrued_balance_cents", 0)
        # §3.6: in this window "the partner's attribution counters are **not** decremented".
        assert_field(partner, "attributed_conversion_count", 1)


class TestRateCardSelection:
    def test_selection_skips_draft_and_out_of_scope_rate_cards(self, api):
        """Only an active card whose scope covers the winning partner may price the order.

        PRD §3.5: "The candidate set is every rate card whose `status` is `ACTIVE`, whose
        `product_category` equals the order's `product_category`, whose
        `partner_type_scope` contains the winning partner's `partner_type`, and whose
        half-open window contains the order's `placed_at` — that is, `effective_from` is
        at or before `placed_at` and `effective_to` is strictly after it."

        Design: Corner/calculations/policy_selection_skips_draft_and_out_of_scope_rate_cards
        """
        program = fixtures.build_program(
            api,
            setup_clock=SETUP_CLOCK,
            partner_type="CONTENT",
            fee_bps=0,
            with_policy=False,
        )

        # Card A: right category and scope, right window — but never activated.
        draft_card = fixtures.draft_policy(
            api,
            policy_code="APPAREL-CONTENT-DRAFT",
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=900,
            returning_customer_rate_bps=400,
            effective_from=f.YEAR_2026_START,
            effective_to=f.YEAR_2027_START,
        )
        # Card B: ACTIVE over the whole year, but scoped to COUPON partners only.
        coupon_card = fixtures.draft_and_activate_policy(
            api,
            policy_code="APPAREL-COUPON-2026",
            product_category="APPAREL",
            partner_type_scope=["COUPON"],
            new_customer_rate_bps=1000,
            returning_customer_rate_bps=500,
            effective_from=f.YEAR_2026_START,
            effective_to=f.YEAR_2027_START,
        )
        # Card C: the only ACTIVE card whose scope contains CONTENT at `placed_at`.
        content_card = fixtures.draft_and_activate_policy(
            api,
            policy_code="APPAREL-CONTENT-H2",
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=800,
            returning_customer_rate_bps=300,
            effective_from=JUN_01_2026,
            effective_to=SEP_01_2026,
        )

        fixtures.ingest_click(api, program["link_id"], occurred_at=f.JUL_04_10_00)
        conversion = fixtures.create_conversion(
            api,
            order_ref="ORD-SELECT-1",
            order_total_cents=100000,
            product_category="APPAREL",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
        )

        attributed = assert_object_response(
            api.attribute_conversion(
                conversion["id"],
                f.attribute_payload(conversion["version"]),
                TRACKING_INGESTOR,
            )
        )

        assert_field(attributed, "commission_policy_id", content_card["id"])
        # §3.3: "`returning_customer_rate_bps`, applied when the buyer was not" new:
        # 100000 * 300 / 10000 = 3000, and a MEDIUM CONTENT partner keeps all of it.
        assert_cents(attributed, "gross_commission_cents", 3000)
        assert_cents(attributed, "payable_commission_cents", 3000)
        assert_field(attributed, "attribution_status", "AFFILIATE_ATTRIBUTED")

        assert_field(
            assert_object_response(
                api.get_commission_policy(draft_card["id"], PROGRAM_ADMIN)
            ),
            "status",
            "DRAFT",
        )
        assert_field(
            assert_object_response(
                api.get_commission_policy(coupon_card["id"], PROGRAM_ADMIN)
            ),
            "status",
            "ACTIVE",
        )

        # §3.3: activation only compares against a card that "shares at least one partner
        # type with the activating card's `partner_type_scope`", so B survives untouched.
        assert_total_count(
            api.list_commission_policies(
                PROGRAM_ADMIN, {"product_category": "APPAREL", "status": "ACTIVE"}
            ),
            2,
        )

        assert_cents(
            fixtures.read_affiliate(api, program["affiliate_id"]),
            "accrued_balance_cents",
            3000,
        )
