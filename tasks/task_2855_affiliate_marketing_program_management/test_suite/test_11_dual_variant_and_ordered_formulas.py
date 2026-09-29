"""The calculations the contract defines twice, or in an order that decides the cents.

Four behaviours live here.  Both credit-share variants are materialised on a
single order so the gross and the payable figure diverge on the same row.  The
point-in-time and the trailing fraud score are maintained side by side on one
partner from the same two cases.  Each payout line is rounded to whole cents
before the batch sums them, so the batch fee differs from the sum-then-round
answer by a cent.  And the pinned evaluation order inside an attribution run
means the first coupon order on a content partner keeps full credit while the
second — priced from the tier the first one produced — is reduced.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
    rows_by,
)
from test_helpers.constants import (
    VARIANT_INCREMENTALITY_ADJUSTED,
    VARIANT_LAST_CLICK_RAW,
)
from test_helpers.fixtures import (
    activated_partner,
    attribute,
    batch_lines,
    create_conversion,
    create_network,
    decide_application,
    draft_and_activate_policy,
    file_application,
    generate_batch,
    ingest_click,
    mint_link,
    open_case,
    pin_clock,
    read_affiliate,
    read_batch,
    read_conversion,
    register_affiliate,
    screen_application,
    valid_tax_document,
)
from test_helpers.test_users import PROGRAM_ADMIN

# ── instants (§2.9: every temporal rule reads the pinned logical clock) ───────

CLOCK_ATTRIBUTION = "2026-08-12T12:00:00.000Z"
CLOCK_SETTLEMENT = "2026-09-15T00:00:00.000Z"
CLOCK_FRAUD = "2026-08-01T00:00:00.000Z"

CLICK_AT = "2026-08-10T10:00:00.000Z"
SECOND_CLICK_AT = "2026-08-11T10:00:00.000Z"
PLACED_AT = "2026-08-12T09:00:00.000Z"
SECOND_PLACED_AT = "2026-08-12T10:00:00.000Z"

PERIOD_START = "2026-08-01T00:00:00.000Z"
PERIOD_END = "2026-09-01T00:00:00.000Z"

TRADEMARK_DETECTED_AT = "2026-07-22T00:00:00.000Z"
FORCED_CLICK_DETECTED_AT = "2026-06-02T00:00:00.000Z"

# ── the money literals, recomputed from the §3.5 and §3.9 formulas ───────────

ORDER_TOTAL_CENTS = 133000
RETURNING_RATE_BPS = 400
# §3.5: "the order's `order_total_cents` multiplied by that rate in basis
# points, divided by 10,000, and rounded half up to a whole cent" →
# 133000 * 400 / 10000 = 5320.
GROSS_COMMISSION_CENTS = 5320
# §3.5: "`gross_commission_cents` multiplied by the variant's
# `credit_share_bps`, divided by 10,000" → 5320 * 3000 / 10000 = 1596.
REDUCED_COMMISSION_CENTS = 1596

NETWORK_FEE_BPS = 375
# §3.9: "`net_before_fees_cents` multiplied by the network's `fee_bps`,
# divided by 10000 and rounded half up to a whole cent" → 5320 * 375 / 10000
# = 199.5, which rounds half up to 200 on each line.
LINE_NETWORK_FEE_CENTS = 200
LINE_NET_CENTS = 5120
BATCH_GROSS_CENTS = 2 * GROSS_COMMISSION_CENTS
BATCH_NETWORK_FEE_CENTS = 2 * LINE_NETWORK_FEE_CENTS
BATCH_NET_PAYABLE_CENTS = 2 * LINE_NET_CENTS
# The forbidden order: 10640 * 375 / 10000 = 399.0 exactly, one cent short.
SUM_THEN_ROUND_NETWORK_FEE_CENTS = 399


# ── private setup helpers (this module's own, to keep the recipes readable) ──


def _coupon_partner_program(api):
    """A `COUPON` partner admitted with conditions, priced by an `APPAREL` card."""
    pin_clock(api, CLOCK_ATTRIBUTION)
    network = create_network(
        api, fee_model="HYBRID", fee_bps=NETWORK_FEE_BPS, flat_fee_cents=0
    )
    affiliate = register_affiliate(api, network["id"], partner_type="COUPON")
    application = file_application(
        api,
        affiliate["id"],
        site_url="https://couponcove.example",
        primary_traffic_source="COUPON_DIRECTORY",
        monthly_traffic_estimate=400000,
        declared_promo_methods=["COUPON_FEED"],
        product_categories=["APPAREL"],
    )
    # §3.2 restricted screen: (0.45*95 + 0.35*95 + 0.20*100) * 0.65 * 0.90
    # = 56.16 → 56.2, brand suitability 100.0, so the outcome is CONDITIONAL.
    screened = screen_application(
        api,
        application["id"],
        domain_authority=95,
        content_originality_pct=95,
        broken_link_ratio_bps=0,
        brand_safety_flag_count=0,
        restricted_vertical_overlap_bps=0,
    )
    assert screened["screening_outcome"] == "CONDITIONAL", (
        "setup expects a CONDITIONAL screen for the coupon directory applicant, got "
        f"{screened['screening_outcome']!r}"
    )
    decide_application(
        api,
        application["id"],
        "APPROVE_WITH_CONDITIONS",
        affiliate["version"],
        decision_notes="clean coupon directory",
        conditional_requirements=["no trademark bidding", "monthly coupon feed audit"],
    )
    policy = draft_and_activate_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["COUPON"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )
    link = mint_link(
        api, affiliate["id"], cookie_window_days=30, device_graph_enabled=False
    )
    return {
        "network_id": network["id"],
        "affiliate_id": affiliate["id"],
        "policy_id": policy["id"],
        "link_id": link["id"],
    }


def _coupon_order_attributed(api):
    """One coupon-redeeming order on the `COUPON` partner, attribution resolved."""
    program = _coupon_partner_program(api)
    click = ingest_click(
        api,
        program["link_id"],
        occurred_at=CLICK_AT,
        device_id="D1",
        referrer_domain="couponcove.example",
    )
    conversion = create_conversion(
        api,
        order_ref="ORD-DV-1",
        order_total_cents=ORDER_TOTAL_CENTS,
        product_category="APPAREL",
        customer_ref="CUST-1",
        is_new_customer=False,
        placed_at=PLACED_AT,
        device_id="D1",
        coupon_code_used="SAVE10",
        other_channel_touch="NONE",
    )
    attributed = attribute(api, conversion["id"], conversion["version"])
    program.update(
        {
            "click_id": click["id"],
            "conversion_id": conversion["id"],
            "conversion": attributed,
        }
    )
    return program


def _content_partner_with_two_open_cases(api):
    """One `ACTIVE` `CONTENT` partner carrying two `OPEN` cases of different ages."""
    pin_clock(api, CLOCK_FRAUD)
    network = create_network(api, fee_model="PERCENT_OF_COMMISSION", fee_bps=0)
    partner = activated_partner(
        api,
        network["id"],
        partner_type="CONTENT",
        application_kwargs={
            "site_url": "https://contentbarn.example",
            "primary_traffic_source": "CONTENT_NEWSLETTER",
            "monthly_traffic_estimate": 90000,
            "declared_promo_methods": ["EDITORIAL_CONTENT"],
            "product_categories": ["APPAREL"],
        },
    )
    trademark_case = open_case(
        api,
        partner["affiliate_id"],
        violation_type="TRADEMARK_BIDDING",
        detected_at=TRADEMARK_DETECTED_AT,
    )
    forced_click_case = open_case(
        api,
        partner["affiliate_id"],
        violation_type="FORCED_CLICK",
        detected_at=FORCED_CLICK_DETECTED_AT,
    )
    return {
        "affiliate_id": partner["affiliate_id"],
        "trademark_case": trademark_case,
        "forced_click_case": forced_click_case,
    }


def _accrued_content_partner(api, network_id, device_id, sub_id, order_ref, customer_ref):
    """One `ACTIVE` `CONTENT` partner with a `VALID` W9 and one attributed order."""
    partner = activated_partner(
        api,
        network_id,
        partner_type="CONTENT",
        application_kwargs={
            "primary_traffic_source": "CONTENT_NEWSLETTER",
            "monthly_traffic_estimate": 90000,
        },
    )
    # §3.9 line withholding reads "the partner's most recent tax document": a
    # VALID W9 declaring `treaty_withholding_bps` 0 keeps the line's
    # withholding at zero so the network fee is the only rounded term.
    valid_tax_document(api, partner["affiliate_id"], treaty_withholding_bps=0)
    link = mint_link(
        api,
        partner["affiliate_id"],
        sub_id=sub_id,
        cookie_window_days=30,
        device_graph_enabled=False,
    )
    ingest_click(api, link["id"], occurred_at=CLICK_AT, device_id=device_id)
    conversion = create_conversion(
        api,
        order_ref=order_ref,
        order_total_cents=ORDER_TOTAL_CENTS,
        product_category="APPAREL",
        customer_ref=customer_ref,
        is_new_customer=False,
        placed_at=PLACED_AT,
        device_id=device_id,
        other_channel_touch="NONE",
    )
    attributed = attribute(api, conversion["id"], conversion["version"])
    return {
        "affiliate_id": partner["affiliate_id"],
        "conversion_id": conversion["id"],
        "conversion": attributed,
    }


def _two_line_batch(api):
    """Two identical 5320-cent accruals on one network, settled in one batch."""
    pin_clock(api, CLOCK_ATTRIBUTION)
    network = create_network(
        api, fee_model="HYBRID", fee_bps=NETWORK_FEE_BPS, flat_fee_cents=0
    )
    draft_and_activate_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )
    first = _accrued_content_partner(
        api, network["id"], "DA", "a-1", "ORD-RO-A", "CUST-A"
    )
    second = _accrued_content_partner(
        api, network["id"], "DB", "b-1", "ORD-RO-B", "CUST-B"
    )
    # §3.6: the validation sweep needs "thirty days have elapsed since its
    # `placed_at` as measured against the logical clock".
    pin_clock(api, CLOCK_SETTLEMENT)
    batch = generate_batch(
        api, network["id"], period_start=PERIOD_START, period_end=PERIOD_END
    )
    return {"first": first, "second": second, "batch": batch}


def _two_coupon_orders_on_content_partner(api):
    """Two coupon-redeeming orders on one `CONTENT` partner, attributed in order."""
    pin_clock(api, CLOCK_ATTRIBUTION)
    network = create_network(api, fee_model="PERCENT_OF_COMMISSION", fee_bps=0)
    draft_and_activate_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )
    partner = activated_partner(
        api,
        network["id"],
        partner_type="CONTENT",
        application_kwargs={
            "site_url": "https://contentbarn.example",
            "primary_traffic_source": "CONTENT_NEWSLETTER",
            "monthly_traffic_estimate": 90000,
        },
    )
    fresh = read_affiliate(api, partner["affiliate_id"])
    assert_bps(fresh, "incrementality_score_bps", 4500)
    assert_field(fresh, "incrementality_tier", "MEDIUM")

    link = mint_link(
        api,
        partner["affiliate_id"],
        cookie_window_days=30,
        device_graph_enabled=False,
    )
    ingest_click(api, link["id"], occurred_at=CLICK_AT, device_id="D1")
    first_order = create_conversion(
        api,
        order_ref="ORD-PO-1",
        order_total_cents=ORDER_TOTAL_CENTS,
        product_category="APPAREL",
        customer_ref="CUST-1",
        is_new_customer=False,
        placed_at=PLACED_AT,
        device_id="D1",
        coupon_code_used="SAVE10",
        other_channel_touch="NONE",
    )
    first_attributed = attribute(api, first_order["id"], first_order["version"])
    after_first = read_affiliate(api, partner["affiliate_id"])

    ingest_click(api, link["id"], occurred_at=SECOND_CLICK_AT, device_id="D2")
    second_order = create_conversion(
        api,
        order_ref="ORD-PO-2",
        order_total_cents=ORDER_TOTAL_CENTS,
        product_category="APPAREL",
        customer_ref="CUST-2",
        is_new_customer=False,
        placed_at=SECOND_PLACED_AT,
        device_id="D2",
        coupon_code_used="SAVE10",
        other_channel_touch="NONE",
    )
    second_attributed = attribute(api, second_order["id"], second_order["version"])
    return {
        "affiliate_id": partner["affiliate_id"],
        "link_id": link["id"],
        "affiliate_after_first": after_first,
        "first_conversion_id": first_order["id"],
        "first_conversion": first_attributed,
        "second_conversion_id": second_order["id"],
        "second_conversion": second_attributed,
    }


class TestDualVariantCreditShareOnOneConversion:
    def test_reduced_coupon_order_keeps_gross_and_payable_apart_on_one_row(self, api):
        """A coupon-reduced order stores the raw gross and the reduced payable together.

        PRD §3.5: "On a reduced order `gross_commission_cents` keeps the unreduced
        figure, so the two money fields deliberately diverge on the same row and the
        size of the reduction stays auditable."

        Design: Difficulty/dual_variant_calc/dual_variant_attribution_credit_share_on_conversion
        """
        program = _coupon_order_attributed(api)

        order = assert_object_response(
            api.get_conversion(program["conversion_id"], PROGRAM_ADMIN)
        )
        # §3.5: gross is 133000 * 400 / 10000 = 5320, and the payable figure is
        # rounded from that already-rounded gross: 5320 * 3000 / 10000 = 1596.
        assert_cents(order, "gross_commission_cents", GROSS_COMMISSION_CENTS)
        assert_cents(order, "payable_commission_cents", REDUCED_COMMISSION_CENTS)
        assert order["gross_commission_cents"] != order["payable_commission_cents"], (
            "a credit-reduced order must keep the unreduced gross alongside the "
            "reduced payable figure, not overwrite one with the other"
        )
        assert_fields(
            order,
            {
                "attribution_status": "CREDIT_REDUCED",
                "attributed_affiliate_id": program["affiliate_id"],
                "attributed_click_id": program["click_id"],
                "commission_policy_id": program["policy_id"],
                "candidate_click_count": 1,
            },
        )

    def test_both_credit_share_variants_are_materialised_for_the_order(self, api):
        """One run writes both variants, the raw one at 10000 bps and the adjusted at 3000.

        PRD §3.5: "Which variant supplies that credit share is the incrementality
        policy at the heart of this program, and both variants are **always**
        materialised so the divergence between them stays observable."

        Design: Difficulty/dual_variant_calc/dual_variant_attribution_credit_share_on_conversion
        """
        program = _coupon_order_attributed(api)

        rows, meta = assert_list_response(
            api.list_attribution_decisions(program["conversion_id"], PROGRAM_ADMIN)
        )
        # §3.5: "Every attribution run writes exactly one row per declared variant".
        assert_pagination_meta(meta, total_count=2)
        by_variant = rows_by(rows, "algorithm_variant")
        assert set(by_variant) == {
            VARIANT_LAST_CLICK_RAW,
            VARIANT_INCREMENTALITY_ADJUSTED,
        }, f"expected one row per declared variant, got {sorted(by_variant)}"

        raw = by_variant[VARIANT_LAST_CLICK_RAW]
        # §3.5: "Under it `credit_share_bps` is 10000, so the payable commission
        # equals the gross commission exactly".
        assert_bps(raw, "credit_share_bps", 10000)
        assert_cents(raw, "computed_commission_cents", GROSS_COMMISSION_CENTS)
        assert_field(raw, "selected", False)

        adjusted = by_variant[VARIANT_INCREMENTALITY_ADJUSTED]
        # §3.5: "Under it `credit_share_bps` is 3000, so the payable commission is
        # thirty per cent of the gross rounded half up to a whole cent".
        assert_bps(adjusted, "credit_share_bps", 3000)
        assert_cents(adjusted, "computed_commission_cents", REDUCED_COMMISSION_CENTS)
        assert_fields(
            adjusted,
            {
                "selected": True,
                "dedup_reason": "LOW_INCREMENTALITY_PARTNER",
                "candidate_click_count": 1,
                "winning_click_occurred_at": CLICK_AT,
                "device_match_mode": "DEVICE_EXACT",
                "evaluated_at": CLOCK_ATTRIBUTION,
            },
        )

    def test_coupon_partner_accrues_only_the_reduced_commission(self, api):
        """The partner's pool moves by the reduced payable figure, never by the gross.

        PRD §3.5: "An `ACCRUAL` ledger entry is appended for the partner in the amount
        of the payable commission, positive in sign. That ledger append raises the
        partner's `accrued_balance_cents` by the same amount."

        Design: Difficulty/dual_variant_calc/dual_variant_attribution_credit_share_on_conversion
        """
        program = _coupon_order_attributed(api)

        partner = read_affiliate(api, program["affiliate_id"])
        assert_cents(partner, "accrued_balance_cents", REDUCED_COMMISSION_CENTS)
        assert_fields(
            partner,
            {
                "attributed_conversion_count": 1,
                "coupon_assisted_conversion_count": 1,
                "new_customer_attributed_count": 0,
            },
        )
        # §3.5 post-state: coupon-assisted share 1 * 10000 / 1 = 10000, so
        # 0.55 * 0 + 0.45 * (10000 - 10000) - 1500 = -1500, clamped to 0 → LOW.
        assert_bps(partner, "incrementality_score_bps", 0)
        assert_field(partner, "incrementality_tier", "LOW")


class TestPointInTimeVersusTrailingFraudScore:
    def test_point_in_time_score_sums_the_undecayed_severity_weights(self, api):
        """The point-in-time figure adds the two open cases at their table weights.

        PRD §3.7: "It counts only cases whose `state` is `OPEN`,
        `REMEDIATION_REQUESTED`, `REMEDIATION_SUBMITTED`, `ESCALATED` or `UPHELD`, sums
        their `severity_weight` values, and caps the result at 100. It applies no decay
        at all and ignores `detected_at` entirely, so a three-year-old `OPEN` case still
        counts at its full weight, and a `VERIFIED_CLEARED` case contributes exactly
        zero."

        Design: Difficulty/dual_variant_calc/dual_variant_fraud_score_point_in_time_versus_trailing_on_affiliate
        """
        setup = _content_partner_with_two_open_cases(api)

        # §3.7: "a `severity_weight` copied from the fixed severity table at
        # creation: 40 for `COOKIE_STUFFING`, 30 for `FORCED_CLICK`, 25 for
        # `UNAUTHORIZED_COUPON` and 20 for `TRADEMARK_BIDDING`."
        assert_fields(setup["trademark_case"], {"severity_weight": 20, "state": "OPEN"})
        assert_fields(
            setup["forced_click_case"], {"severity_weight": 30, "state": "OPEN"}
        )

        partner = read_affiliate(api, setup["affiliate_id"])
        assert_field(partner, "fraud_risk_score", 20 + 30)
        assert isinstance(partner["fraud_risk_score"], int) and not isinstance(
            partner["fraud_risk_score"], bool
        ), (
            "the point-in-time fraud score is an integer from 0 to 100, got "
            f"{partner['fraud_risk_score']!r}"
        )
        assert_field(partner, "open_violation_case_count", 2)

    def test_trailing_score_decays_each_case_by_its_whole_days_of_age(self, api):
        """The trailing figure discounts the same two cases by 0.01 per whole day of age.

        PRD §3.7: "The age in days is the whole number of complete days between the
        case's `detected_at` and the clock, discarding any partial day. The decay is
        1.00 minus 0.01 for each whole day of age, with a floor of 0.20 that it never
        falls below."

        Design: Difficulty/dual_variant_calc/dual_variant_fraud_score_point_in_time_versus_trailing_on_affiliate
        """
        setup = _content_partner_with_two_open_cases(api)

        partner = read_affiliate(api, setup["affiliate_id"])
        # §3.7: "Each surviving case contributes its `severity_weight` multiplied by
        # an age decay and by a state factor."  Against the clock 2026-08-01, the
        # trademark case detected 2026-07-22 is 10 whole days old (20 * 0.90 = 18.0)
        # and the forced-click case detected 2026-06-02 is 60 days old
        # (30 * 0.40 = 12.0), both inside the ninety-day window, so the sum is 30.0.
        assert_one_decimal_score(
            partner, "fraud_risk_score_trailing", 20 * 0.90 + 30 * 0.40
        )

    def test_both_fraud_figures_persist_together_below_the_suspension_threshold(
        self, api
    ):
        """The undecayed 50 and the decayed 30.0 sit on one row and leave it `ACTIVE`.

        PRD §3.7: "Whenever a recompute leaves an `ACTIVE` partner's point-in-time
        `fraud_risk_score` at 70 or above, the program suspends that partner in the same
        request, setting `status` to `SUSPENDED` and `suspension_cause` to
        `FRAUD_SCORE_BREACH`, and the suspension cascade described in §2.11 runs in
        full: every `ACTIVE` partner whose `parent_affiliate_id` is this partner is
        suspended with `suspension_cause` `PARENT_SUSPENSION`; for every partner newly
        suspended in the request, its `ACTIVE` tracking links are disabled with
        `disabled_reason` `AFFILIATE_SUSPENDED` and its `INCLUDED` payout lines on
        batches that are `DRAFT` or `VALIDATED` move to `HELD_FRAUD` with `hold_reason`
        `AFFILIATE_SUSPENDED`; and the `network_fee_cents`, `withholding_cents` and
        `net_payable_cents` totals of every touched batch are recomputed."

        Design: Difficulty/dual_variant_calc/dual_variant_fraud_score_point_in_time_versus_trailing_on_affiliate
        """
        setup = _content_partner_with_two_open_cases(api)

        partner = read_affiliate(api, setup["affiliate_id"])
        assert_field(partner, "fraud_risk_score", 50)
        assert_one_decimal_score(partner, "fraud_risk_score_trailing", 30.0)
        # §3.7: "Because the two figures select different case sets, the trailing
        # figure can be strictly lower than the point-in-time figure for the same
        # cases when they are old".
        assert partner["fraud_risk_score_trailing"] < partner["fraud_risk_score"], (
            "only the trailing variant applies the per-day decay, so on two ageing "
            "cases it must fall strictly below the point-in-time figure"
        )
        # 50 never reaches the 70 auto-suspension threshold.
        assert_fields(partner, {"status": "ACTIVE", "suspension_cause": "NONE"})


class TestPerLineRoundingBeforeBatchSummation:
    def test_each_line_rounds_its_own_network_fee_to_a_whole_cent(self, api):
        """Both 5320-cent lines round their 199.5-cent fee up to 200 before any summing.

        PRD §3.9: "Its `network_fee_cents` is the network's percentage component —
        `net_before_fees_cents` multiplied by the network's `fee_bps`, divided by 10000
        and rounded half up to a whole cent — plus the network's `flat_fee_cents`
        multiplied by the line's `conversion_count`; a network configured for one fee
        model contributes nothing from the other, because the unused field is pinned to
        zero at registration."

        Design: Difficulty/combinatorial_formula/rounding_order_pinned_per_line_then_sum_on_payout_batch
        """
        settled = _two_line_batch(api)

        for label in ("first", "second"):
            order = read_conversion(api, settled[label]["conversion_id"])
            assert_cents(order, "payable_commission_cents", GROSS_COMMISSION_CENTS)
            assert_field(order, "validation_status", "VALIDATED")

        lines = batch_lines(api, settled["batch"]["id"])
        assert len(lines) == 2, (
            "one payout line is created per distinct partner among the claimed "
            f"entries, so two partners must produce two lines, got {len(lines)}"
        )
        for line in lines:
            assert_cents(line, "gross_cents", GROSS_COMMISSION_CENTS)
            assert_cents(line, "clawback_cents", 0)
            assert_cents(line, "net_before_fees_cents", GROSS_COMMISSION_CENTS)
            # 5320 * 375 / 10000 = 199.5, which rounds half up to 200.
            assert_cents(line, "network_fee_cents", LINE_NETWORK_FEE_CENTS)
            # A VALID W9 claiming no treaty rate keeps the withholding at zero,
            # so net_cents is 5320 - 200 - 0.
            assert_bps(line, "withholding_bps", 0)
            assert_cents(line, "withholding_cents", 0)
            assert_cents(line, "net_cents", LINE_NET_CENTS)
            assert_field(line, "state", "INCLUDED")

    def test_batch_network_fee_is_the_sum_of_rounded_lines_not_the_rounded_sum(
        self, api
    ):
        """The batch fee is 400 — one cent above the answer a batch-level rounding gives.

        PRD §2.6: "When a payout batch aggregates its partner lines, each line is
        rounded to whole cents first and the batch totals are plain integer sums of
        those already-rounded per-line values; summing unrounded per-line products and
        rounding once at the batch level is wrong and produces a different answer."

        Design: Difficulty/combinatorial_formula/rounding_order_pinned_per_line_then_sum_on_payout_batch
        """
        settled = _two_line_batch(api)

        batch = read_batch(api, settled["batch"]["id"])
        assert_cents(batch, "network_fee_cents", BATCH_NETWORK_FEE_CENTS)
        # Rounding once at the batch level would give 10640 * 375 / 10000 = 399.0.
        assert batch["network_fee_cents"] != SUM_THEN_ROUND_NETWORK_FEE_CENTS, (
            "summing the unrounded per-line products and rounding once at the batch "
            f"level yields {SUM_THEN_ROUND_NETWORK_FEE_CENTS} and is forbidden"
        )
        lines = batch_lines(api, settled["batch"]["id"])
        assert batch["network_fee_cents"] == sum(
            line["network_fee_cents"] for line in lines
        ), (
            "the batch network fee must be the plain integer sum of the already-"
            "rounded per-line fees"
        )

    def test_batch_totals_are_plain_integer_sums_of_the_line_values(self, api):
        """Every batch total is the integer sum of the corresponding per-line figures.

        PRD §3.9: "Each line is rounded to whole cents first, and the batch totals are
        plain integer sums of the already-rounded per-line values:
        `gross_commission_cents` sums the lines' `gross_cents`, `clawback_cents` sums
        the lines' `clawback_cents`, `network_fee_cents` sums the lines'
        `network_fee_cents`, `withholding_cents` sums the lines' `withholding_cents`,
        and `net_payable_cents` sums the lines' `net_cents`."

        Design: Difficulty/combinatorial_formula/rounding_order_pinned_per_line_then_sum_on_payout_batch
        """
        settled = _two_line_batch(api)

        batch = read_batch(api, settled["batch"]["id"])
        assert_field(batch, "line_count", 2)
        assert_cents(batch, "gross_commission_cents", BATCH_GROSS_CENTS)
        assert_cents(batch, "clawback_cents", 0)
        assert_cents(batch, "network_fee_cents", BATCH_NETWORK_FEE_CENTS)
        assert_cents(batch, "withholding_cents", 0)
        assert_cents(batch, "net_payable_cents", BATCH_NET_PAYABLE_CENTS)

        lines = batch_lines(api, settled["batch"]["id"])
        for batch_field, line_field in (
            ("gross_commission_cents", "gross_cents"),
            ("clawback_cents", "clawback_cents"),
            ("network_fee_cents", "network_fee_cents"),
            ("withholding_cents", "withholding_cents"),
            ("net_payable_cents", "net_cents"),
        ):
            assert batch[batch_field] == sum(line[line_field] for line in lines), (
                f"batch {batch_field} must be the plain integer sum of the lines' "
                f"{line_field}"
            )


def _selected_decision(api, conversion_id):
    """The one attribution audit row a run marked as selected."""
    rows, _meta = assert_list_response(
        api.list_attribution_decisions(conversion_id, PROGRAM_ADMIN)
    )
    selected = [row for row in rows if row["selected"]]
    assert len(selected) == 1, (
        "exactly one audit row per run carries selected true, got "
        f"{[row['algorithm_variant'] for row in selected]}"
    )
    return selected[0]


class TestPinnedEvaluationOrderAcrossTwoOrders:
    def test_first_coupon_order_is_paid_at_the_pre_state_tier_it_then_destroys(
        self, api
    ):
        """The first coupon order keeps full credit although the same run drops the tier.

        PRD §3.5: "Second, the `incrementality_tier` is read from the counters as they
        stand before this order — the pre-state — and the variant is chosen from that
        reading." The consequence is spelled out in the same paragraph: "The consequence
        is a rule worth stating plainly: an order never reduces its own credit share."

        Design: Difficulty/combinatorial_formula/circular_incrementality_pinned_evaluation_order_across_two_conversions
        """
        setup = _two_coupon_orders_on_content_partner(api)

        first = read_conversion(api, setup["first_conversion_id"])
        # The partner was freshly activated at 4500 bps in MEDIUM, and a CONTENT
        # partner is not a coupon-partner override, so the raw variant applies.
        assert_cents(first, "gross_commission_cents", GROSS_COMMISSION_CENTS)
        assert_cents(first, "payable_commission_cents", GROSS_COMMISSION_CENTS)
        assert_field(first, "attribution_status", "AFFILIATE_ATTRIBUTED")

        selected = _selected_decision(api, setup["first_conversion_id"])
        assert_field(selected, "algorithm_variant", VARIANT_LAST_CLICK_RAW)
        assert_bps(selected, "credit_share_bps", 10000)
        assert_cents(selected, "computed_commission_cents", GROSS_COMMISSION_CENTS)

        # The very same request that paid full credit recomputed the score to its
        # post-state value: 0.55 * 0 + 0.45 * (10000 - 10000) - 0 = 0, tier LOW.
        partner = setup["affiliate_after_first"]
        assert_bps(partner, "incrementality_score_bps", 0)
        assert_field(partner, "incrementality_tier", "LOW")

    def test_second_coupon_order_is_reduced_by_the_tier_the_first_one_produced(
        self, api
    ):
        """The second order reads the pre-state tier `LOW` and is cut to 3000 bps.

        PRD §3.5: "The adjusted variant, named `INCREMENTALITY_ADJUSTED`, applies when
        the winning partner's pre-state `incrementality_tier` is `LOW`, **or** when the
        partner's `partner_type` is `COUPON` or `LOYALTY_CASHBACK` and the order's
        `coupon_code_used` is non-null."

        Design: Difficulty/combinatorial_formula/circular_incrementality_pinned_evaluation_order_across_two_conversions
        """
        setup = _two_coupon_orders_on_content_partner(api)

        second = read_conversion(api, setup["second_conversion_id"])
        # §3.5: "Only the next order sees the effect of this one."
        assert_cents(second, "gross_commission_cents", GROSS_COMMISSION_CENTS)
        assert_cents(second, "payable_commission_cents", REDUCED_COMMISSION_CENTS)
        assert_field(second, "attribution_status", "CREDIT_REDUCED")

        selected = _selected_decision(api, setup["second_conversion_id"])
        assert_field(selected, "algorithm_variant", VARIANT_INCREMENTALITY_ADJUSTED)
        assert_bps(selected, "credit_share_bps", 3000)
        assert_cents(selected, "computed_commission_cents", REDUCED_COMMISSION_CENTS)
        assert_field(selected, "dedup_reason", "LOW_INCREMENTALITY_PARTNER")

        first = read_conversion(api, setup["first_conversion_id"])
        assert first["payable_commission_cents"] > second["payable_commission_cents"], (
            "the two orders are identical apart from their position in the pinned "
            "evaluation order, so only the second may be reduced"
        )

    def test_partner_counters_and_balance_after_both_coupon_orders(self, api):
        """Both orders are counted, and the balance holds full credit plus reduced credit.

        PRD §3.5: "Fourth, and only then, `attributed_conversion_count` increments,
        together with `new_customer_attributed_count` when the buyer was new and
        `coupon_assisted_conversion_count` when a coupon was redeemed. Fifth,
        `incrementality_score_bps` and `incrementality_tier` are recomputed to their
        post-state values and persisted."

        Design: Difficulty/combinatorial_formula/circular_incrementality_pinned_evaluation_order_across_two_conversions
        """
        setup = _two_coupon_orders_on_content_partner(api)

        partner = read_affiliate(api, setup["affiliate_id"])
        assert_fields(
            partner,
            {
                "attributed_conversion_count": 2,
                "coupon_assisted_conversion_count": 2,
                "new_customer_attributed_count": 0,
            },
        )
        # Post-state: coupon-assisted share 2 * 10000 / 2 = 10000, new-customer
        # share 0, no CONTENT discount, so the score is 0 and the tier LOW.
        assert_bps(partner, "incrementality_score_bps", 0)
        assert_field(partner, "incrementality_tier", "LOW")
        # 5320 accrued at full credit plus 1596 accrued at the reduced share.
        assert_cents(
            partner,
            "accrued_balance_cents",
            GROSS_COMMISSION_CENTS + REDUCED_COMMISSION_CENTS,
        )
