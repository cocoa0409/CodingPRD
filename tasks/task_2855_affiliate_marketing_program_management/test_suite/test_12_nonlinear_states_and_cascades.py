"""Review loops, parallel order dimensions and multi-hop server-side cascades.

Three shapes of behaviour live here.  An application that goes round the
revision loop and reaches `SCREENED` twice with two different outcomes, taking
the other outgoing branch of the decision the second time.  An order whose
credit dimension and money dimension advance on different triggers and are
therefore never in step.  And two long chains the server walks by itself: a
monitoring scan that opens cases, drives the point-in-time fraud score over the
suspension threshold and pulls a sub-affiliate, its tracking link and its payout
line down with it; and a full return that claws a booked commission back through
the ledger, the partner's balance, the payout line and the batch totals.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_created,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
    assert_version_bumped,
    assert_version_unchanged,
)
from test_helpers.fixtures import (
    activated_partner,
    attributed_order,
    batch_lines,
    build_program,
    create_network,
    decide_application,
    file_application,
    generate_batch,
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
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    make_affiliate_partner_headers,
)

# The §2.9 logical clock is pinned explicitly at every instant a temporal rule
# is read: admission, trading, and the settlement run thirty days later.
CLOCK_ADMISSION = "2026-08-01T00:00:00.000Z"
CLOCK_TRADING = "2026-08-12T12:00:00.000Z"
CLOCK_SETTLEMENT = "2026-09-15T00:00:00.000Z"

CLICK_AT = "2026-08-10T10:00:00.000Z"
PLACED_AT = "2026-08-12T09:00:00.000Z"
ADJUSTMENT_AT = "2026-09-15T06:00:00.000Z"
CASE_DETECTED_AT = "2026-08-20T00:00:00.000Z"

PERIOD_START = "2026-08-01T00:00:00.000Z"
PERIOD_END = "2026-09-01T00:00:00.000Z"

SCAN_WINDOW_START = "2026-08-01T00:00:00.000Z"
SCAN_WINDOW_END = "2026-08-15T00:00:00.000Z"


def _submitted_application(api):
    """A `CONTENT` partner in `PENDING_APPLICATION` with one `SUBMITTED` application."""
    pin_clock(api, CLOCK_ADMISSION)
    network = create_network(api, fee_bps=0, flat_fee_cents=0)
    affiliate = register_affiliate(
        api, network["id"], partner_type="CONTENT", legal_name="Revise Media Ltd"
    )
    application = file_application(
        api,
        affiliate["id"],
        site_url="https://revise.example",
        primary_traffic_source="CONTENT_NEWSLETTER",
        monthly_traffic_estimate=40000,
        declared_promo_methods=["EDITORIAL_CONTENT"],
        product_categories=["APPAREL"],
    )
    return affiliate, application


#: The thin first-round screen: 0.45*50 + 0.35*60 + 0.20*90 = 61.5, times 0.95.
THIN_SCREEN = {
    "domain_authority": 50,
    "content_originality_pct": 60,
    "broken_link_ratio_bps": 1000,
    "brand_safety_flag_count": 0,
    "restricted_vertical_overlap_bps": 0,
}
#: The revised screen: 0.45*80 + 0.35*92 + 0.20*98 = 87.8, times 1.00.
STRONG_SCREEN = {
    "domain_authority": 80,
    "content_originality_pct": 92,
    "broken_link_ratio_bps": 200,
    "brand_safety_flag_count": 0,
    "restricted_vertical_overlap_bps": 0,
}


class TestApplicationRevisionLoopAndDivergentBranch:
    def test_first_screening_round_is_conditional_and_request_changes_holds_the_partner(
        self, api
    ):
        """A thin newsletter site screens `CONDITIONAL`, and sending it back moves no partner.

        PRD §3.2: "It is `CONDITIONAL` when `brand_suitability_score` is at least 70.0
        and `site_quality_score` is at least 45.0 but strictly below 60.0."
        PRD §3.2: "Unlike the other three branches it performs **no** partner cascade at
        all: the applicant's `status` is untouched and remains `PENDING_APPLICATION`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_then_divergent_approve_branch
        """
        affiliate, application = _submitted_application(api)

        screened = assert_object_response(
            api.screen_application(
                application["id"], f.screen_payload(**THIN_SCREEN), COMPLIANCE_ANALYST
            )
        )
        assert_field(screened, "review_state", "SCREENED")
        # §3.2: "The link-health term is 100 minus one hundredth of
        # `broken_link_ratio_bps`", and §3.2: "0.95 for `CONTENT_NEWSLETTER`".
        assert_one_decimal_score(screened, "site_quality_score", 58.4)
        # §3.2: "It starts at 100, subtracts one hundredth of
        # `restricted_vertical_overlap_bps`".
        assert_one_decimal_score(screened, "brand_suitability_score", 100.0)
        assert_field(screened, "screening_outcome", "CONDITIONAL")

        before = read_affiliate(api, affiliate["id"])
        decided = assert_object_response(
            api.decide_application(
                application["id"],
                f.decide_payload(
                    "REQUEST_CHANGES", before["version"], decision_notes="thin content"
                ),
                PARTNER_MANAGER,
            )
        )
        assert_fields(
            decided,
            {
                "review_state": "CHANGES_REQUESTED",
                "screening_outcome": "CONDITIONAL",
                # Only a resubmission "increments `revision_round_count` by 1".
                "revision_round_count": 0,
            },
        )
        assert_version_bumped(decided, screened["version"], "application")

        after = read_affiliate(api, affiliate["id"])
        assert_fields(after, {"status": "PENDING_APPLICATION", "suspension_cause": "NONE"})
        assert_version_unchanged(after, before["version"], "applicant partner")

    def test_resubmission_clears_both_scores_and_returns_the_application_to_submitted(
        self, api
    ):
        """The revision loop rewinds the screening dimension and counts the round.

        PRD §3.2: "Resubmission overwrites `site_url`, `primary_traffic_source` and
        `declared_promo_methods` with the values supplied on the resubmission, increments
        `revision_round_count` by 1, clears `site_quality_score`,
        `brand_suitability_score` and `screened_by_user_id` back to null, resets
        `screening_outcome` to `NOT_SCREENED`, moves the application
        `CHANGES_REQUESTED → SUBMITTED`, and increments the application's `version`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_then_divergent_approve_branch
        """
        affiliate, application = _submitted_application(api)
        screened = screen_application(api, application["id"], **THIN_SCREEN)
        assert_field(screened, "screening_outcome", "CONDITIONAL")
        sent_back = decide_application(
            api,
            application["id"],
            "REQUEST_CHANGES",
            read_affiliate(api, affiliate["id"])["version"],
            decision_notes="thin content",
        )
        assert_field(sent_back, "review_state", "CHANGES_REQUESTED")

        resubmitted = assert_object_response(
            api.resubmit_application(
                application["id"],
                f.resubmit_payload(
                    site_url="https://revise.example/v2",
                    primary_traffic_source="ORGANIC_SEARCH",
                    declared_promo_methods=["EDITORIAL_CONTENT"],
                ),
                make_affiliate_partner_headers(affiliate["id"]),
            )
        )
        assert_fields(
            resubmitted,
            {
                "review_state": "SUBMITTED",
                "revision_round_count": 1,
                "screening_outcome": "NOT_SCREENED",
                "site_url": "https://revise.example/v2",
                "primary_traffic_source": "ORGANIC_SEARCH",
                "declared_promo_methods": ["EDITORIAL_CONTENT"],
            },
        )
        assert_null(
            resubmitted,
            "site_quality_score",
            "brand_suitability_score",
            "screened_by_user_id",
        )
        assert_version_bumped(resubmitted, sent_back["version"], "application")

        reread = assert_object_response(
            api.get_application(application["id"], PROGRAM_ADMIN)
        )
        assert_fields(
            reread,
            {
                "review_state": "SUBMITTED",
                "revision_round_count": 1,
                "screening_outcome": "NOT_SCREENED",
                "primary_traffic_source": "ORGANIC_SEARCH",
            },
        )
        assert_null(reread, "site_quality_score", "brand_suitability_score")

    def test_second_screening_round_passes_and_the_approve_branch_activates_the_partner(
        self, api
    ):
        """The same application reaches `SCREENED` twice, and the second visit is approvable.

        PRD §3.2: "The outcome is `PASS` when `site_quality_score` is at least 60.0 and
        `brand_suitability_score` is at least 70.0."
        PRD §3.2: "`APPROVE` moves the application `SCREENED → APPROVED` and requires the
        `screening_outcome` to be exactly `PASS`. It cascades the applicant partner
        `PENDING_APPLICATION → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_then_divergent_approve_branch
        """
        affiliate, application = _submitted_application(api)
        first = screen_application(api, application["id"], **THIN_SCREEN)
        assert_field(first, "screening_outcome", "CONDITIONAL")
        decide_application(
            api,
            application["id"],
            "REQUEST_CHANGES",
            read_affiliate(api, affiliate["id"])["version"],
            decision_notes="thin content",
        )
        assert_object_response(
            api.resubmit_application(
                application["id"],
                f.resubmit_payload(
                    site_url="https://revise.example/v2",
                    primary_traffic_source="ORGANIC_SEARCH",
                    declared_promo_methods=["EDITORIAL_CONTENT"],
                ),
                make_affiliate_partner_headers(affiliate["id"]),
            )
        )

        second = assert_object_response(
            api.screen_application(
                application["id"], f.screen_payload(**STRONG_SCREEN), COMPLIANCE_ANALYST
            )
        )
        assert_field(second, "review_state", "SCREENED")
        # The resubmission replaced the traffic source, so §3.2's "1.00 for
        # `ORGANIC_SEARCH`" multiplier now applies to the same base figure.
        assert_one_decimal_score(second, "site_quality_score", 87.8)
        assert_one_decimal_score(second, "brand_suitability_score", 100.0)
        assert_field(second, "screening_outcome", "PASS")
        assert_field(second, "revision_round_count", 1)

        before = read_affiliate(api, affiliate["id"])
        approved = assert_object_response(
            api.decide_application(
                application["id"],
                f.decide_payload(
                    "APPROVE", before["version"], decision_notes="revision accepted"
                ),
                PARTNER_MANAGER,
            )
        )
        assert_fields(
            approved, {"review_state": "APPROVED", "screening_outcome": "PASS"}
        )

        activated = read_affiliate(api, affiliate["id"])
        assert_fields(
            activated,
            {
                "status": "ACTIVE",
                "suspension_cause": "NONE",
                # §3.5: "which places `CONTENT` and `INFLUENCER` partners at 4500
                # in `MEDIUM`".
                "incrementality_tier": "MEDIUM",
            },
        )
        assert_bps(activated, "incrementality_score_bps", 4500)
        assert_version_bumped(activated, before["version"], "activated partner")


def _attributed_program(api, with_tax_document: bool = False):
    """A priced program, one 100000-cent returning-customer order, attributed.

    §3.5 prices it at the card's `returning_customer_rate_bps` of 400, so the
    gross commission is 4000 cents and, at a `MEDIUM` tier, the payable
    commission is the same 4000 cents.
    """
    program = build_program(
        api,
        setup_clock=CLOCK_TRADING,
        partner_type="CONTENT",
        fee_bps=0,
        flat_fee_cents=0,
        policy_category="APPAREL",
        policy_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=400,
    )
    if with_tax_document:
        # §3.9 reads `treaty_withholding_bps` from a `VALID` document, and §3.8
        # pins a `W9` filing to a zero treaty rate.
        valid_tax_document(api, program["affiliate_id"], form_type="W9", tax_id_last4="3333")
    order = attributed_order(
        api,
        program,
        order_total_cents=100000,
        is_new_customer=False,
        click_at=CLICK_AT,
        placed_at=PLACED_AT,
    )
    return program, order


def _draft_batch(api, program):
    """Advance the clock past the thirty-day hold and generate the settlement run."""
    pin_clock(api, CLOCK_SETTLEMENT)
    return generate_batch(
        api, program["network_id"], period_start=PERIOD_START, period_end=PERIOD_END
    )


class TestOrderCreditAndMoneyDimensionsAdvanceIndependently:
    def test_attribution_moves_only_the_credit_dimension(self, api):
        """Booking the commission leaves the money dimension waiting for the hold to close.

        PRD §3.5: "Under it `credit_share_bps` is 10000, so the payable commission equals
        the gross commission exactly, and the order moves
        `UNATTRIBUTED → AFFILIATE_ATTRIBUTED`."
        PRD §3.6: "An order sits at `PENDING_VALIDATION` until the retailer's return
        window has closed, and the sweep that closes it runs at the start of payout-batch
        generation."

        Design: Difficulty/non_linear_state_machine/conversion_parallel_attribution_and_validation_dimensions
        """
        program, order = _attributed_program(api)

        conversion = read_conversion(api, order["conversion_id"])
        assert_fields(
            conversion,
            {
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "validation_status": "PENDING_VALIDATION",
                "attributed_affiliate_id": program["affiliate_id"],
            },
        )
        assert_cents(conversion, "gross_commission_cents", 4000)
        assert_cents(conversion, "payable_commission_cents", 4000)
        assert_cents(conversion, "clawed_back_cents", 0)
        assert_cents(conversion, "returned_amount_cents", 0)

        partner = read_affiliate(api, program["affiliate_id"])
        assert_cents(partner, "accrued_balance_cents", 4000)
        # §3.1: "Its `tax_document_status` is `NONE`, meaning no tax form is on
        # file at all."
        assert_field(partner, "tax_document_status", "NONE")

    def test_generation_sweep_validates_the_money_dimension_only(self, api):
        """The thirty-day sweep flips `validation_status` while the credit dimension holds.

        PRD §3.6: "That sweep moves an order `PENDING_VALIDATION → VALIDATED` when the
        order's `attribution_status` is `AFFILIATE_ATTRIBUTED` or `CREDIT_REDUCED` and
        thirty days have elapsed since its `placed_at` as measured against the logical
        clock."

        Design: Difficulty/non_linear_state_machine/conversion_parallel_attribution_and_validation_dimensions
        """
        program, order = _attributed_program(api)
        before = read_conversion(api, order["conversion_id"])

        batch = _draft_batch(api, program)

        swept = read_conversion(api, order["conversion_id"])
        assert_fields(
            swept,
            {
                "validation_status": "VALIDATED",
                "attribution_status": "AFFILIATE_ATTRIBUTED",
            },
        )
        assert_version_bumped(swept, before["version"], "swept order")

        lines = batch_lines(api, batch["id"])
        assert len(lines) == 1, "one line is created per distinct partner among the claimed entries"
        line = lines[0]
        assert_cents(line, "gross_cents", 4000)
        assert_cents(line, "clawback_cents", 0)
        assert_cents(line, "net_before_fees_cents", 4000)
        assert_field(line, "conversion_count", 1)
        assert_cents(line, "network_fee_cents", 0)
        # §3.9: "the line uses the default backup withholding rate of 2400 basis
        # points" whenever there is "no document at all".
        assert_bps(line, "withholding_bps", 2400)
        assert_cents(line, "withholding_cents", 960)
        assert_cents(line, "net_cents", 3040)
        assert_field(line, "state", "INCLUDED")
        assert_null(line, "hold_reason")

        assert_fields(batch, {"state": "DRAFT", "line_count": 1})
        assert_cents(batch, "gross_commission_cents", 4000)
        assert_cents(batch, "withholding_cents", 960)
        assert_cents(batch, "net_payable_cents", 3040)

    def test_partial_return_cuts_the_accrual_without_moving_either_dimension(self, api):
        """A pro-rata clawback recovers 1200 cents and leaves both state dimensions alone.

        PRD §3.6: "Crucially, `attribution_status` is **not** changed and the partner's
        attribution counters are **not** decremented in this window: the conversion really
        happened, and its incrementality signal is retained even though its money is being
        recovered."
        PRD §3.6: "The order's `validation_status` becomes `CLAWED_BACK` when the
        cumulative return has reached the full `order_total_cents`, and otherwise stays
        `VALIDATED` so that further partial returns can follow."

        Design: Difficulty/non_linear_state_machine/conversion_parallel_attribution_and_validation_dimensions
        """
        program, order = _attributed_program(api)
        batch = _draft_batch(api, program)

        adjusted = assert_object_response(
            api.adjust_order(
                order["conversion_id"],
                f.order_adjustment_payload(
                    "PARTIAL_RETURN", 30000, occurred_at=ADJUSTMENT_AT
                ),
                FINANCE_ANALYST,
            )
        )
        assert_fields(
            adjusted,
            {
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "validation_status": "VALIDATED",
            },
        )

        reread = read_conversion(api, order["conversion_id"])
        assert_cents(reread, "returned_amount_cents", 30000)
        # §3.6: "The target total is the order's `payable_commission_cents`
        # multiplied by the cumulative returned amount, divided by the order's
        # `order_total_cents`, and rounded half up to a whole cent."
        assert_cents(reread, "clawed_back_cents", 1200)
        # The multiplicand of that target is untouched by the recovery.
        assert_cents(reread, "payable_commission_cents", 4000)
        assert_cents(reread, "gross_commission_cents", 4000)

        partner = read_affiliate(api, program["affiliate_id"])
        # §3.6: "The append lowers the partner's `accrued_balance_cents` by the
        # magnitude".
        assert_cents(partner, "accrued_balance_cents", 2800)

        lines = batch_lines(api, batch["id"])
        assert len(lines) == 1, "the clawback entry is stamped to the accrual's own batch"
        line = lines[0]
        assert_cents(line, "gross_cents", 4000)
        assert_cents(line, "clawback_cents", 1200)
        assert_cents(line, "net_before_fees_cents", 2800)
        assert_cents(line, "withholding_cents", 672)
        assert_cents(line, "net_cents", 2128)
        # §3.6: "the line moves `INCLUDED → HELD_BELOW_MINIMUM` and the batch
        # totals are recomputed again without it".
        assert_fields(
            line, {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"}
        )

        after = read_batch(api, batch["id"])
        assert_cents(after, "net_payable_cents", 0)
        assert_cents(after, "gross_commission_cents", 4000)
        assert_cents(after, "clawback_cents", 1200)
        assert_field(after, "state", "DRAFT")


def _parent_sub_and_draft_batch(api):
    """A `SUB_NETWORK` parent with one nested `CONTENT` partner that already earned.

    The sub-affiliate holds one 4000-cent accrual and one `INCLUDED` payout line
    on a `DRAFT` batch, and the parent already carries one hand-filed
    `UNAUTHORIZED_COUPON` case worth 25 points — on its own well below the
    suspension threshold.
    """
    program = build_program(
        api,
        setup_clock=CLOCK_TRADING,
        partner_type="SUB_NETWORK",
        fee_bps=0,
        flat_fee_cents=0,
        policy_category="APPAREL",
        policy_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=400,
        application_kwargs={
            "site_url": "https://parent.example",
            "primary_traffic_source": "PAID_SEARCH",
            "monthly_traffic_estimate": 500000,
            "declared_promo_methods": ["EMAIL"],
        },
        with_link=False,
    )
    parent_id = program["affiliate_id"]
    sub = activated_partner(
        api,
        program["network_id"],
        partner_type="CONTENT",
        affiliate_kwargs={"parent_affiliate_id": parent_id},
    )
    link = mint_link(api, sub["affiliate_id"], sub_id="s-1")
    order = attributed_order(
        api,
        {"link_id": link["id"]},
        order_total_cents=100000,
        is_new_customer=False,
        click_at=CLICK_AT,
        placed_at=PLACED_AT,
    )
    batch = _draft_batch(api, program)
    case = open_case(
        api,
        parent_id,
        violation_type="UNAUTHORIZED_COUPON",
        detected_at=CASE_DETECTED_AT,
    )
    return {
        "parent_id": parent_id,
        "sub_id": sub["affiliate_id"],
        "link_id": link["id"],
        "order": order,
        "batch": batch,
        "case": case,
    }


def _record_trademark_and_forced_click_scan(api, affiliate_id):
    """The one ingestion that fires the whole chain."""
    return assert_created(
        api.create_monitoring_scan(
            f.monitoring_scan_payload(
                affiliate_id,
                engine="GOOGLE_ADS",
                window_start=SCAN_WINDOW_START,
                window_end=SCAN_WINDOW_END,
                trademark_hits=2,
                forced_click_ratio_bps=1800,
                cookie_stuffing_index=0,
                unauthorized_coupon_hits=0,
            ),
            COMPLIANCE_ANALYST,
        )
    )


class TestMonitoringScanFraudSuspensionCascade:
    def test_one_scan_opens_two_cases_for_the_two_signals_that_fired(self, api):
        """Two of the four signals breach, so the scan opens exactly two cases itself.

        PRD §3.7: "The four signals are examined in a **fixed order**, and each condition
        that holds opens at most one case for this scan: `trademark_hits` greater than zero
        opens a `TRADEMARK_BIDDING` case; `forced_click_ratio_bps` of 1500 or more opens a
        `FORCED_CLICK` case; `cookie_stuffing_index` of 60 or more opens a
        `COOKIE_STUFFING` case; and `unauthorized_coupon_hits` greater than zero opens an
        `UNAUTHORIZED_COUPON` case."

        Design: Difficulty/transitive_cascade/monitoring_scan_fraud_suspension_cascade_depth_five
        """
        ctx = _parent_sub_and_draft_batch(api)

        scan = _record_trademark_and_forced_click_scan(api, ctx["parent_id"])
        assert_field(scan, "opened_case_count", 2)

        rows, meta = assert_list_response(
            api.list_violation_cases(
                COMPLIANCE_ANALYST,
                {"affiliate_id": ctx["parent_id"], "limit": 20, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=3)
        assert [row["state"] for row in rows] == ["OPEN", "OPEN", "OPEN"], (
            "a case opened by a scan or filed by hand \"starts at `OPEN`\""
        )

        from_scan = [row for row in rows if row["source_scan_id"] == scan["id"]]
        assert len(from_scan) == 2, (
            "exactly the two breaching signals may open a case for this scan, "
            f"got {len(from_scan)} rows citing it"
        )
        assert {row["violation_type"] for row in from_scan} == {
            "TRADEMARK_BIDDING",
            "FORCED_CLICK",
        }, "the trademark and forced-click signals are the two that breached"
        for row in from_scan:
            # §3.7: "leaves `opened_by_user_id` null, because no human filed it".
            assert_null(row, "opened_by_user_id")
            assert_field(row, "failed_verification_count", 0)
        # §3.7: "30 for `FORCED_CLICK`" and "20 for `TRADEMARK_BIDDING`".
        weights = {row["violation_type"]: row["severity_weight"] for row in from_scan}
        assert weights == {"TRADEMARK_BIDDING": 20, "FORCED_CLICK": 30}, (
            f"severity weights must come from the fixed table, got {weights}"
        )

        parent = read_affiliate(api, ctx["parent_id"])
        assert_field(parent, "open_violation_case_count", 3)

    def test_the_breaching_score_suspends_the_parent_and_propagates_to_the_sub_affiliate(
        self, api
    ):
        """25 plus 20 plus 30 crosses the threshold, and the nested partner follows.

        PRD §3.7: "Whenever a recompute leaves an `ACTIVE` partner's point-in-time
        `fraud_risk_score` at 70 or above, the program suspends that partner in the same
        request, setting `status` to `SUSPENDED` and `suspension_cause` to
        `FRAUD_SCORE_BREACH`, and the suspension cascade described in §2.11 runs in full:
        every `ACTIVE` partner whose `parent_affiliate_id` is this partner is suspended
        with `suspension_cause` `PARENT_SUSPENSION`; for every partner newly suspended in
        the request, its `ACTIVE` tracking links are disabled with `disabled_reason`
        `AFFILIATE_SUSPENDED` and its `INCLUDED` payout lines on batches that are `DRAFT`
        or `VALIDATED` move to `HELD_FRAUD` with `hold_reason` `AFFILIATE_SUSPENDED`; and
        the `network_fee_cents`, `withholding_cents` and `net_payable_cents` totals of
        every touched batch are recomputed."

        Design: Difficulty/transitive_cascade/monitoring_scan_fraud_suspension_cascade_depth_five
        """
        ctx = _parent_sub_and_draft_batch(api)
        parent_before = read_affiliate(api, ctx["parent_id"])
        sub_before = read_affiliate(api, ctx["sub_id"])
        assert_fields(parent_before, {"status": "ACTIVE", "fraud_risk_score": 25})
        assert_field(sub_before, "status", "ACTIVE")

        _record_trademark_and_forced_click_scan(api, ctx["parent_id"])

        parent = read_affiliate(api, ctx["parent_id"])
        # §3.7: the point-in-time figure "sums their `severity_weight` values, and
        # caps the result at 100".
        assert_field(parent, "fraud_risk_score", 75)
        assert_field(parent, "open_violation_case_count", 3)
        assert_fields(
            parent, {"status": "SUSPENDED", "suspension_cause": "FRAUD_SCORE_BREACH"}
        )

        sub = read_affiliate(api, ctx["sub_id"])
        assert_fields(
            sub, {"status": "SUSPENDED", "suspension_cause": "PARENT_SUSPENSION"}
        )
        # §3.7: "Sub-affiliate suspension is a pure parent-propagation hop: a
        # child's own fraud score is **not** re-evaluated".
        assert_field(sub, "fraud_risk_score", 0)
        assert_field(sub, "open_violation_case_count", 0)
        assert_version_bumped(sub, sub_before["version"], "sub-affiliate")

    def test_the_suspension_disables_the_sub_link_holds_its_line_and_zeroes_the_payable(
        self, api
    ):
        """The last hops reach a tracking link, a payout line and the batch totals.

        PRD §2.11: "Suspending a partner, for example, is a four-hop operation: the partner
        itself moves to `SUSPENDED`; then every `ACTIVE` partner whose
        `parent_affiliate_id` names it is suspended too; then, for every partner newly
        suspended anywhere in that fan-out, its `ACTIVE` tracking links are disabled and
        its `INCLUDED` payout lines on non-terminal batches are moved to a fraud hold; and
        finally every batch touched by those holds has its fee, withholding and payable
        totals recomputed."

        Design: Difficulty/transitive_cascade/monitoring_scan_fraud_suspension_cascade_depth_five
        """
        ctx = _parent_sub_and_draft_batch(api)
        line_before = batch_lines(api, ctx["batch"]["id"])
        assert len(line_before) == 1, "the sub-affiliate is the only partner with entries"
        assert_field(line_before[0], "state", "INCLUDED")
        assert_cents(line_before[0], "net_cents", 3040)

        _record_trademark_and_forced_click_scan(api, ctx["parent_id"])

        link = assert_object_response(
            api.get_tracking_link(ctx["link_id"], PROGRAM_ADMIN)
        )
        # §3.7: "its `ACTIVE` tracking links are disabled with `disabled_reason`
        # `AFFILIATE_SUSPENDED`".
        assert_fields(link, {"status": "DISABLED", "disabled_reason": "AFFILIATE_SUSPENDED"})

        rows, meta = assert_list_response(
            api.list_payout_lines(
                FINANCE_ANALYST,
                {"payout_batch_id": ctx["batch"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        line = rows[0]
        # §3.7: its `INCLUDED` payout lines "move to `HELD_FRAUD` with
        # `hold_reason` `AFFILIATE_SUSPENDED`".
        assert_fields(line, {"state": "HELD_FRAUD", "hold_reason": "AFFILIATE_SUSPENDED"})
        assert_cents(line, "gross_cents", 4000)
        assert_version_bumped(line, line_before[0]["version"], "held payout line")

        batch = read_batch(api, ctx["batch"]["id"])
        # §3.9: "A held line is excluded from the batch's payable totals, which
        # are recomputed when it leaves them."
        assert_cents(batch, "net_payable_cents", 0)
        assert_cents(batch, "withholding_cents", 0)
        assert_cents(batch, "network_fee_cents", 0)
        # §3.9: `gross_commission_cents` includes "**every** line whatever its state".
        assert_cents(batch, "gross_commission_cents", 4000)
        assert_field(batch, "state", "DRAFT")

        sub = read_affiliate(api, ctx["sub_id"])
        # §3.6: the accrued pool is "the sum of every ledger entry for that
        # partner that is not reserved by an approved batch" — a hold moves none.
        assert_cents(sub, "accrued_balance_cents", 4000)


class TestFullReturnClawbackCascade:
    def test_full_return_on_a_validated_order_moves_only_the_money_dimension(self, api):
        """The whole order comes back, so the money dimension goes terminal on its own.

        PRD §3.6: "The order's `validation_status` becomes `CLAWED_BACK` when the
        cumulative return has reached the full `order_total_cents`, and otherwise stays
        `VALIDATED` so that further partial returns can follow."
        PRD §3.6: "Crucially, `attribution_status` is **not** changed and the partner's
        attribution counters are **not** decremented in this window: the conversion really
        happened, and its incrementality signal is retained even though its money is being
        recovered."

        Design: Difficulty/transitive_cascade/full_return_clawback_cascade_depth_four
        """
        program, order = _attributed_program(api, with_tax_document=True)
        _draft_batch(api, program)
        before = read_conversion(api, order["conversion_id"])
        assert_field(before, "validation_status", "VALIDATED")

        adjusted = assert_object_response(
            api.adjust_order(
                order["conversion_id"],
                f.order_adjustment_payload(
                    "FULL_RETURN", 100000, occurred_at=ADJUSTMENT_AT
                ),
                FINANCE_ANALYST,
            )
        )
        assert_fields(
            adjusted,
            {
                "validation_status": "CLAWED_BACK",
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "attributed_affiliate_id": program["affiliate_id"],
            },
        )

        reread = read_conversion(api, order["conversion_id"])
        assert_cents(reread, "returned_amount_cents", 100000)
        assert_cents(reread, "clawed_back_cents", 4000)
        assert_cents(reread, "payable_commission_cents", 4000)
        assert_version_bumped(reread, before["version"], "clawed-back order")

        partner = read_affiliate(api, program["affiliate_id"])
        # The counters that feed incrementality survive the recovery of the money.
        assert_field(partner, "attributed_conversion_count", 1)

    def test_the_clawback_appends_a_negative_ledger_row_and_empties_the_accrued_pool(
        self, api
    ):
        """Nothing is edited: a second, signed entry lands against the same order and batch.

        PRD §3.6: "The entry raised is a `CLAWBACK`, except that it is an `ADJUSTMENT` of
        the same magnitude when the order's original `ACCRUAL` entry has already been
        stamped to a batch that is `PAID`."
        PRD §3.6: "Its `amount_cents` is signed: positive for an `ACCRUAL`, and negative
        for a `REVERSAL`, a `CLAWBACK`, a `SETTLEMENT`, and for an `ADJUSTMENT` raised
        after settlement."

        Design: Difficulty/transitive_cascade/full_return_clawback_cascade_depth_four
        """
        program, order = _attributed_program(api, with_tax_document=True)
        batch = _draft_batch(api, program)

        assert_object_response(
            api.adjust_order(
                order["conversion_id"],
                f.order_adjustment_payload(
                    "FULL_RETURN", 100000, occurred_at=ADJUSTMENT_AT
                ),
                FINANCE_ANALYST,
            )
        )

        rows, meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"conversion_id": order["conversion_id"], "limit": 20, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=2)
        assert [row["entry_type"] for row in rows] == ["ACCRUAL", "CLAWBACK"], (
            "the accrual is never edited; the recovery is appended behind it, and "
            f"§2.3 sorts the pair by `created_at` ascending, got {[r['entry_type'] for r in rows]}"
        )
        assert_cents(rows[0], "amount_cents", 4000)
        assert_cents(rows[1], "amount_cents", -4000)
        for row in rows:
            # §3.6: "the new entry is stamped to that same batch".
            assert_field(row, "payout_batch_id", batch["id"])
            assert_field(row, "affiliate_id", program["affiliate_id"])

        partner = read_affiliate(api, program["affiliate_id"])
        # §3.6: "The append lowers the partner's `accrued_balance_cents` by the
        # magnitude" — 4000 booked less 4000 recovered.
        assert_cents(partner, "accrued_balance_cents", 0)

    def test_the_clawback_recompute_holds_the_line_and_zeroes_the_batch_payable(self, api):
        """The recomputed line falls to nothing, holds below the minimum, and the batch follows.

        PRD §3.6: "When the original `ACCRUAL` is stamped to a batch that is `DRAFT` or
        `VALIDATED`, the new entry is stamped to that same batch, which triggers a recompute
        of that partner's line in it and of the batch totals; if the recomputed net amount
        on that line falls below the 2,500-cent minimum, the line moves
        `INCLUDED → HELD_BELOW_MINIMUM` and the batch totals are recomputed again without
        it."

        Design: Difficulty/transitive_cascade/full_return_clawback_cascade_depth_four
        """
        program, order = _attributed_program(api, with_tax_document=True)
        batch = _draft_batch(api, program)
        before = batch_lines(api, batch["id"])
        assert len(before) == 1, "one line is created per distinct partner among the claimed entries"
        # §3.9: "when that document's `status` is `VALID` the line uses its
        # `treaty_withholding_bps`", which a `W9` pins to zero.
        assert_bps(before[0], "withholding_bps", 0)
        assert_cents(before[0], "net_cents", 4000)
        assert_field(before[0], "state", "INCLUDED")
        assert_cents(batch, "net_payable_cents", 4000)

        assert_object_response(
            api.adjust_order(
                order["conversion_id"],
                f.order_adjustment_payload(
                    "FULL_RETURN", 100000, occurred_at=ADJUSTMENT_AT
                ),
                FINANCE_ANALYST,
            )
        )

        rows, meta = assert_list_response(
            api.list_payout_lines(
                FINANCE_ANALYST,
                {"payout_batch_id": batch["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        line = rows[0]
        assert_cents(line, "gross_cents", 4000)
        assert_cents(line, "clawback_cents", 4000)
        assert_cents(line, "net_before_fees_cents", 0)
        assert_cents(line, "withholding_cents", 0)
        assert_cents(line, "net_cents", 0)
        assert_fields(
            line, {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"}
        )

        after = read_batch(api, batch["id"])
        # §3.9: `gross_commission_cents` and `clawback_cents` include "**every**
        # line whatever its state", while the payable total takes only the
        # "lines that are `INCLUDED` or `PAID`".
        assert_cents(after, "gross_commission_cents", 4000)
        assert_cents(after, "clawback_cents", 4000)
        assert_cents(after, "net_payable_cents", 0)
        assert_field(after, "state", "DRAFT")
