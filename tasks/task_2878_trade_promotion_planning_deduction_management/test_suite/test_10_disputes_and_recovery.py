"""
Disputes: the bounded retailer round-trip, aging escalation and resolution.

The write-off path is followed through the longest cascade in the service, from
the recognised-spend figure on the promotion out to the post-event analysis, the
performance flag and the funding allocation's at-risk money, and the two
authorisation gates that guard it are exercised on both axes.
"""

from test_helpers import (
    AUTO_CREDIT_HOLD_REASON_PREFIX,
    AccrualMethod,
    ApiErrorId,
    BaselineMethod,
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR_ALT_HEADERS,
    DIRECTOR_ALT_USER_ID,
    DataStatus,
    DeductionStatus,
    DisputeReasonCode,
    DisputeStatus,
    FactType,
    MAX_DISPUTE_ROUNDS,
    MONDAY_AUG_10,
    MONDAY_AUG_31,
    PerformanceFlag,
    RetailerResponse,
    SPECIALIST_ALT_HEADERS,
    SPECIALIST_ALT_USER_ID,
    SPECIALIST_HEADERS,
    SPECIALIST_USER_ID,
    SpendStatus,
    TradingStatus,
    assert_aging_run,
    assert_dispute,
    assert_money,
    assert_null_fields,
    assert_ratio,
    create_dispute_payload,
    instant,
    make_portal_user_headers,
    open_dispute,
    read_allocation,
    read_analysis,
    read_customer,
    read_deduction,
    read_dispute,
    read_promotion,
    record_recovery_payload,
    retailer_respond,
    retailer_respond_payload,
    run_activation,
    run_aging_sweep,
    same_instant,
    send_dispute,
    send_to_retailer_payload,
    set_clock,
    setup_accrued_promotion,
    setup_allocation_context,
    setup_analysis,
    setup_approved_promotion,
    setup_deduction,
    setup_matched_deduction,
    setup_reference_data,
    setup_second_customer,
    setup_verified_evidence_document,
    setup_volume_facts,
    validate_deduction,
    validate_error,
    validate_success,
    write_off_payload,
)


def _write_off_cascade_context(api):
    """
    An analysed promotion carrying a second, disputed claim ready to be written off.

    The promotion accrues on the consumption basis: a `TPR` line of 2000 cases
    at 1.250 plans 2500.00, one week of 1450 consumed cases accrues 1812.50, and
    a first claim of 2000.00 is validated against 1600 verified cases. The
    seasonal analysis then rates the promotion from a 600-case weekly baseline.
    """
    context = setup_allocation_context(
        api,
        program_overrides={
            "accrual_method_default": AccrualMethod.CONSUMPTION.value
        },
        brand_overrides={
            "list_price_per_case": 20.00,
            "cogs_per_case": 12.00,
            "baseline_units_per_week": 600,
        },
        planned_amount=50000.00,
        planned_incremental_units=10000,
    )
    context = setup_accrued_promotion(
        api, context, fact_units=1450, fact_type=FactType.CONSUMPTION.value,
        planned_units=2000, rate_per_case=1.250,
    )
    setup_volume_facts(
        api, context["customer"]["id"], context["brand"]["id"],
        {MONDAY_AUG_10: 1450, MONDAY_AUG_31: 1000},
        fact_type=FactType.CONSUMPTION.value,
    )
    setup_verified_evidence_document(
        api, context["promotion"]["id"], units_verified=1600
    )

    first_claim = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=2000.00,
    )
    context["first_claim"] = validate_deduction(
        api, first_claim["id"], context["promotion"]["id"]
    )

    set_clock(api, instant(MONDAY_AUG_31))
    run_activation(api)
    context["analysis"] = setup_analysis(
        api, context["promotion"]["id"],
        baseline_method=BaselineMethod.SEASONAL.value,
    )

    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=600.00,
    )
    context["dispute"] = open_dispute(
        api, context["deduction"]["id"], 450.00, headers=SPECIALIST_HEADERS
    )
    return context


class TestWriteOffCascade:
    """One write-off followed through all four of its declared hops."""

    def test_write_off_raises_recognised_spend_and_sinks_the_analysis_roi(self, api):
        """
        Written-off money becomes recognised spend, so the analysis denominator rises and the promotion flips to `UNDERPERFORMING`.

        PRD: "Written-off money is recognised spend, so hop one adds it to the promotion's `consumed_deduction_amount`, which lowers `accrued_balance`, raises `recognized_spend_amount` and can move `spend_status` toward `OVERSPENT`."
        PRD: "Hop two recomputes the promotion's post-event analysis where one exists, whose `net_spend` has just risen and whose `roi` therefore falls."
        PRD: "Hop three flips the promotion's `performance_flag` to `UNDERPERFORMING` if the new `roi` has dropped below 1.0000."
        PRD: "Recovered total is the sum of `recovered_amount` over `RECOVERED` disputes whose deductions are matched to this promotion, rounded to 2 decimal places, and `net_spend` is the promotion's `recognized_spend_amount` minus that total, rounded to 2 decimal places."

        Design: Difficulty/transitive_cascade/dispute_write_off_chain_reaches_allocation_at_risk_amount
        """
        context = _write_off_cascade_context(api)

        before = read_analysis(api, context["analysis"]["id"])
        assert before["data_status"] == DataStatus.COMPLETE.value
        assert before["promo_consumption_units"] == 2900
        assert before["post_period_units"] == 1000
        assert_money(before["baseline_weekly_units"], 600.00, "baseline_weekly_units")
        assert_money(before["baseline_units"], 2400.00, "baseline_units")
        assert_money(before["lift_units"], 500.00, "lift_units")
        assert_money(before["cannibalization_units"], 200.00, "cannibalization_units")
        assert_money(before["net_incremental_units"], 300.00,
                     "net_incremental_units")
        assert_money(before["incremental_gross_profit"], 2400.00,
                     "incremental_gross_profit")
        assert_money(before["net_spend"], 2000.00, "net_spend")
        assert_ratio(before["roi"], 1.2000, "roi")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["planned_total_spend"], 2500.00, "planned_total_spend")
        assert_money(promotion["gross_accrued_amount"], 1812.50,
                     "gross_accrued_amount")
        assert_money(promotion["recognized_spend_amount"], 2000.00,
                     "recognized_spend_amount")
        assert promotion["performance_flag"] == PerformanceFlag.ON_TRACK.value

        dispute = validate_success(
            api.write_off_dispute(
                context["dispute"]["id"], write_off_payload(450.00),
                SPECIALIST_ALT_HEADERS,
            )
        )
        assert dispute["status"] == DisputeStatus.WRITTEN_OFF.value
        assert_money(dispute["write_off_amount"], 450.00, "write_off_amount")
        assert dispute["resolved_by_user_id"] == SPECIALIST_ALT_USER_ID
        assert read_deduction(api, context["deduction"]["id"])["status"] == (
            DeductionStatus.WRITTEN_OFF.value
        )

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["consumed_deduction_amount"], 2450.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], -637.50, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 2450.00,
                     "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.9800, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.OVERSPEND_WARNING.value
        assert promotion["performance_flag"] == PerformanceFlag.UNDERPERFORMING.value

        after = read_analysis(api, context["analysis"]["id"])
        assert_money(after["net_spend"], 2450.00, "net_spend")
        assert_ratio(after["roi"], 0.9796, "roi")
        assert_money(after["incremental_gross_profit"], 2400.00,
                     "incremental_gross_profit")

    def test_write_off_puts_the_underperforming_spend_at_risk_on_the_allocation(self, api):
        """
        The fourth hop moves the underperforming promotion's net spend into the allocation's at-risk figure and rewrites both customer rollups.

        PRD: "Hop four raises the owning allocation's `at_risk_amount`, because an underperforming promotion's committed money is now money at risk."
        PRD: "`at_risk_amount` is the sum of the `net_spend` figure from the post-event analysis of every child promotion whose `performance_flag` is `UNDERPERFORMING`, rounded to 2 decimal places; because a promotion has at most one analysis, that reference is unambiguous."
        PRD: "The customer's `open_deduction_amount` and `write_off_ytd_amount` are both recomputed, and the `version` of the dispute, the deduction, the promotion and the allocation is each incremented by 1."

        Design: Difficulty/transitive_cascade/dispute_write_off_chain_reaches_allocation_at_risk_amount
        """
        context = _write_off_cascade_context(api)

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["at_risk_amount"], 0.00, "at_risk_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["open_deduction_amount"], 2600.00,
                     "open_deduction_amount")
        assert_money(customer["write_off_ytd_amount"], 0.00, "write_off_ytd_amount")

        validate_success(
            api.write_off_dispute(
                context["dispute"]["id"], write_off_payload(450.00),
                SPECIALIST_ALT_HEADERS,
            )
        )

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["at_risk_amount"], 2450.00, "at_risk_amount")
        assert_money(allocation["accrued_amount"], 1812.50, "accrued_amount")
        assert_money(allocation["settled_amount"], 0.00, "settled_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["write_off_ytd_amount"], 450.00,
                     "write_off_ytd_amount")
        assert_money(customer["open_deduction_amount"], 2000.00,
                     "open_deduction_amount")
        assert customer["trading_status"] == TradingStatus.ACTIVE.value
        assert customer["compliance_penalty_points"] == 0


class TestTerminalDisputeIsClosed:
    """A resolved dispute refuses every further resolution action."""

    def test_a_written_off_dispute_refuses_write_off_recovery_and_sending(self, api):
        """
        Once a dispute is written off, a second write-off, a recovery and a send to the retailer are all refused.

        PRD: "Attempting recovery or write-off on a dispute that is already `RECOVERED` or `WRITTEN_OFF` is refused with `ERR_DISPUTE_STATE_INVALID`."
        PRD: "Sending from any status other than `OPEN`, or responding from any status other than `AWAITING_RETAILER`, is refused with `ERR_DISPUTE_STATE_INVALID` (HTTP 409)."
        PRD: "A successful write-off moves the dispute to the terminal `WRITTEN_OFF`, stores `write_off_amount`, `write_off_reason` and `resolved_by_user_id`, and moves the parent deduction's `status` `DISPUTED` → `WRITTEN_OFF`."

        Design: Corner/state_machines/terminal_dispute_refuses_further_resolution_actions
        """
        context = setup_reference_data(api)
        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=100.00
        )
        dispute = open_dispute(
            api, deduction["id"], 100.00, headers=SPECIALIST_HEADERS,
            reason_code=DisputeReasonCode.NO_AGREEMENT.value,
        )

        written_off = validate_success(
            api.write_off_dispute(
                dispute["id"], write_off_payload(100.00), SPECIALIST_ALT_HEADERS
            )
        )
        assert written_off["status"] == DisputeStatus.WRITTEN_OFF.value
        assert_money(written_off["write_off_amount"], 100.00, "write_off_amount")
        assert written_off["resolved_by_user_id"] == SPECIALIST_ALT_USER_ID

        validate_error(
            api.write_off_dispute(
                dispute["id"], write_off_payload(50.00), SPECIALIST_ALT_HEADERS
            ),
            ApiErrorId.DISPUTE_STATE_INVALID.value,
        )
        validate_error(
            api.record_dispute_recovery(
                dispute["id"], record_recovery_payload(50.00), SPECIALIST_HEADERS
            ),
            ApiErrorId.DISPUTE_STATE_INVALID.value,
        )
        validate_error(
            api.send_dispute_to_retailer(
                dispute["id"], SPECIALIST_HEADERS, send_to_retailer_payload()
            ),
            ApiErrorId.DISPUTE_STATE_INVALID.value,
        )

        dispute = read_dispute(api, dispute["id"])
        assert dispute["status"] == DisputeStatus.WRITTEN_OFF.value
        assert_money(dispute["write_off_amount"], 100.00, "write_off_amount")
        assert dispute["round_count"] == 0

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.WRITTEN_OFF.value
        )

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["write_off_ytd_amount"], 100.00,
                     "write_off_ytd_amount")
        assert_money(customer["open_deduction_amount"], 0.00,
                     "open_deduction_amount")


class TestNegotiationLoop:
    """The return leg of the loop restores `OPEN` without rewinding the counter."""

    def test_the_retailer_answer_returns_to_open_and_keeps_the_round_count(self, api):
        """
        A retailer answer moves the dispute back to `OPEN` while leaving `round_count` where the send left it, so the next send takes it to two.

        PRD: "A `DeductionSpecialist` sends an `OPEN` dispute to the retailer, optionally attaching `packet_notes`, which moves `status` `OPEN` → `AWAITING_RETAILER` and increments `round_count` by 1."
        PRD: "The retailer answers through the portal: the `CustomerPortalUser` whose identifier equals the disputed deduction's own `customer_id` posts a `retailer_response` of `ACCEPT_CHARGEBACK`, `PROVIDE_EVIDENCE` or `REFUSE`, which records that answer and returns `status` `AWAITING_RETAILER` → `OPEN`."
        PRD: "Because `round_count` is never reset by the return leg, the loop may run at most twice: a send is permitted only while `round_count` is strictly below 2, so a third send on the same dispute is refused with `ERR_DISPUTE_ROUND_LIMIT` (HTTP 409)."

        Design: Corner/state_machines/dispute_negotiation_loop_returns_to_open_without_resetting_the_counter
        """
        context = setup_reference_data(api)
        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=400.00
        )
        dispute = open_dispute(
            api, deduction["id"], 400.00, headers=SPECIALIST_HEADERS
        )
        assert dispute["status"] == DisputeStatus.OPEN.value
        assert dispute["round_count"] == 0

        sent = send_dispute(api, dispute["id"])
        assert sent["status"] == DisputeStatus.AWAITING_RETAILER.value
        assert sent["round_count"] == 1

        answered = retailer_respond(
            api, dispute["id"], context["customer"]["id"],
            retailer_response=RetailerResponse.PROVIDE_EVIDENCE.value,
        )
        assert answered["status"] == DisputeStatus.OPEN.value
        assert answered["round_count"] == 1
        assert answered["retailer_response"] == (
            RetailerResponse.PROVIDE_EVIDENCE.value
        )

        resent = send_dispute(api, dispute["id"])
        assert resent["status"] == DisputeStatus.AWAITING_RETAILER.value
        assert resent["round_count"] == 2

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.DISPUTED.value
        )


class TestRetailerRoundTripCap:
    """Two complete cycles are the whole of the negotiation budget."""

    def test_a_third_send_is_refused_after_two_complete_round_trips(self, api):
        """
        After two full round trips the dispute is `OPEN` with two rounds spent, and a third send is refused.

        PRD: "Because `round_count` is never reset by the return leg, the loop may run at most twice: a send is permitted only while `round_count` is strictly below 2, so a third send on the same dispute is refused with `ERR_DISPUTE_ROUND_LIMIT` (HTTP 409)."
        PRD: "A `DeductionSpecialist` sends an `OPEN` dispute to the retailer, optionally attaching `packet_notes`, which moves `status` `OPEN` → `AWAITING_RETAILER` and increments `round_count` by 1."

        Design: Corner/errors/retailer_round_trips_are_capped_at_two
        """
        context = setup_reference_data(api)
        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=400.00
        )
        dispute = open_dispute(
            api, deduction["id"], 400.00, headers=SPECIALIST_HEADERS
        )

        for expected_round in (1, 2):
            sent = send_dispute(api, dispute["id"])
            assert sent["status"] == DisputeStatus.AWAITING_RETAILER.value
            assert sent["round_count"] == expected_round

            answered = retailer_respond(
                api, dispute["id"], context["customer"]["id"]
            )
            assert answered["status"] == DisputeStatus.OPEN.value
            assert answered["round_count"] == expected_round

        validate_error(
            api.send_dispute_to_retailer(
                dispute["id"], SPECIALIST_HEADERS, send_to_retailer_payload()
            ),
            ApiErrorId.DISPUTE_ROUND_LIMIT.value,
        )

        dispute = read_dispute(api, dispute["id"])
        assert_dispute(dispute)
        assert dispute["status"] == DisputeStatus.OPEN.value
        assert dispute["round_count"] == MAX_DISPUTE_ROUNDS
        assert dispute["retailer_response"] == RetailerResponse.REFUSE.value

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.DISPUTED.value
        )


class TestDisputeAgingThreshold:
    """The aging threshold is inclusive at ninety whole days."""

    def test_the_sweep_escalates_at_ninety_days_and_not_at_eighty_nine(self, api):
        """
        A dispute aged 89 days is scanned and left alone; one more day of clock moves it to `ESCALATED` and scores the retailer.

        PRD: "`aging_days` is the floor of the elapsed seconds between `opened_at` and the current logical-clock instant divided by 86400 — whole days, always truncated down — and it is recomputed on every read, so a dispute's age reflects wherever the clock has been moved to."
        PRD: "Every candidate whose `aging_days` has reached 90 moves `OPEN` → `ESCALATED` or `AWAITING_RETAILER` → `ESCALATED`; the threshold is inclusive, so 90 days escalates while 89 does not."
        PRD: "The sweep reports the `run_at` instant, the count of `disputes_scanned`, and the lists `disputes_escalated` and `customers_penalized`."
        PRD: "Each escalation adds 5 points to the disputed deduction's customer via the penalty ledger of §2.10, which can carry that customer `ACTIVE` → `CREDIT_HOLD` or, once already on hold at 25 points or more, `CREDIT_HOLD` → `SUSPENDED`."

        Design: Corner/calculations/dispute_aging_escalates_at_exactly_ninety_days
        """
        context = setup_reference_data(api)
        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=300.00
        )
        dispute = open_dispute(
            api, deduction["id"], 300.00, headers=SPECIALIST_HEADERS
        )
        assert same_instant(dispute["opened_at"], DEFAULT_CLOCK_INSTANT)

        set_clock(api, instant("2026-10-29"))
        assert read_dispute(api, dispute["id"])["aging_days"] == 89

        early = run_aging_sweep(api)
        assert_aging_run(early)
        assert early["disputes_scanned"] == 1
        assert early["disputes_escalated"] == []
        assert early["customers_penalized"] == []
        assert read_dispute(api, dispute["id"])["status"] == DisputeStatus.OPEN.value

        set_clock(api, instant("2026-10-30"))
        assert read_dispute(api, dispute["id"])["aging_days"] == 90

        late = run_aging_sweep(api)
        assert late["disputes_scanned"] == 1
        assert late["disputes_escalated"] == [dispute["id"]]
        assert late["customers_penalized"] == [context["customer"]["id"]]

        dispute = read_dispute(api, dispute["id"])
        assert dispute["status"] == DisputeStatus.ESCALATED.value
        assert dispute["aging_days"] == 90

        customer = read_customer(api, context["customer"]["id"])
        assert customer["compliance_penalty_points"] == 5
        assert customer["trading_status"] == TradingStatus.ACTIVE.value
        assert_null_fields(customer, ["credit_hold_reason"])


class TestAgingSweepOrder:
    """The sweep walks its candidates oldest first."""

    def test_candidates_are_escalated_in_opened_at_order(self, api):
        """
        Two overdue disputes are escalated oldest first in one run, and the combined ten points carry the retailer onto automatic credit hold.

        PRD: "An **aging sweep**, run by a `TradeFinanceAnalyst` or `DeductionSpecialist` with no payload, scans every dispute whose `status` is `OPEN` or `AWAITING_RETAILER` — `ESCALATED`, `RECOVERED` and `WRITTEN_OFF` disputes are skipped — in `opened_at` ascending order with `created_at` ascending as the tie-break, never in identifier order."
        PRD: "The score is a weighted count of three populations: each of the customer's budget allocations currently in `RESTRICTED` posture contributes 10 points; each `ESCALATED` dispute raised on one of the customer's deductions contributes 5 points; and each compliance audit of that customer currently in `FINDINGS_ISSUED` contributes 10 points."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."

        Design: Corner/calculations/aging_run_escalates_candidates_in_opened_at_order
        """
        context = setup_reference_data(api)
        customer_id = context["customer"]["id"]

        older_deduction = setup_deduction(api, customer_id, claimed_amount=300.00)
        older_dispute = open_dispute(
            api, older_deduction["id"], 300.00, headers=SPECIALIST_HEADERS
        )

        set_clock(api, instant("2026-08-05"))
        newer_deduction = setup_deduction(api, customer_id, claimed_amount=200.00)
        newer_dispute = open_dispute(
            api, newer_deduction["id"], 200.00, headers=SPECIALIST_HEADERS,
            reason_code=DisputeReasonCode.RATE_MISMATCH.value,
        )

        set_clock(api, instant("2026-11-05"))
        assert read_dispute(api, older_dispute["id"])["aging_days"] == 96
        assert read_dispute(api, newer_dispute["id"])["aging_days"] == 92

        run = run_aging_sweep(api)
        assert_aging_run(run)
        assert run["disputes_scanned"] == 2
        assert run["disputes_escalated"] == [
            older_dispute["id"], newer_dispute["id"]
        ]
        assert set(run["customers_penalized"]) == {customer_id}

        for dispute_id in (older_dispute["id"], newer_dispute["id"]):
            assert read_dispute(api, dispute_id)["status"] == (
                DisputeStatus.ESCALATED.value
            )

        customer = read_customer(api, customer_id)
        assert customer["compliance_penalty_points"] == 10
        assert customer["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert customer["credit_hold_reason"] == (
            f"{AUTO_CREDIT_HOLD_REASON_PREFIX} 10"
        )
        assert_money(customer["open_deduction_amount"], 500.00,
                     "open_deduction_amount")


class TestSpecialistWriteOffBelowTheLimit:
    """A small write-off is a specialist's own decision."""

    def test_a_specialist_who_did_not_open_the_dispute_writes_off_under_the_limit(
        self, api
    ):
        """
        A 400.00 write-off approved by a second specialist succeeds and lands as recognised spend on the promotion.

        PRD: "A `write_off_amount` at or above 500.00 requires a `TradeMarketingDirector`: a `DeductionSpecialist` may approve write-offs strictly below that limit only, and because the comparison is inclusive an amount of exactly 500.00 already needs the director, while 499.99 does not — the refusal is `ERR_WRITE_OFF_APPROVAL_REQUIRED` (HTTP 403)."
        PRD: "A successful write-off moves the dispute to the terminal `WRITTEN_OFF`, stores `write_off_amount`, `write_off_reason` and `resolved_by_user_id`, and moves the parent deduction's `status` `DISPUTED` → `WRITTEN_OFF`."
        PRD: "Written-off money is recognised spend, so hop one adds it to the promotion's `consumed_deduction_amount`, which lowers `accrued_balance`, raises `recognized_spend_amount` and can move `spend_status` toward `OVERSPENT`."
        PRD: "`at_risk_amount` is the sum of the `net_spend` figure from the post-event analysis of every child promotion whose `performance_flag` is `UNDERPERFORMING`, rounded to 2 decimal places; because a promotion has at most one analysis, that reference is unambiguous."

        Design: Corner/endpoints/write_off_below_the_self_approval_limit_is_open_to_the_specialist
        """
        context = setup_allocation_context(api)
        promotion = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )["promotion"]
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=400.00
        )
        dispute = open_dispute(
            api, deduction["id"], 400.00, headers=SPECIALIST_HEADERS
        )

        resolved = validate_success(
            api.write_off_dispute(
                dispute["id"], write_off_payload(400.00), SPECIALIST_ALT_HEADERS
            )
        )
        assert_dispute(resolved)
        assert resolved["status"] == DisputeStatus.WRITTEN_OFF.value
        assert_money(resolved["write_off_amount"], 400.00, "write_off_amount")
        assert resolved["resolved_by_user_id"] == SPECIALIST_ALT_USER_ID
        assert_null_fields(resolved, ["recovered_amount"])

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.WRITTEN_OFF.value
        )

        promotion = read_promotion(api, promotion["id"])
        assert_money(promotion["planned_total_spend"], 4000.00,
                     "planned_total_spend")
        assert_money(promotion["consumed_deduction_amount"], 400.00,
                     "consumed_deduction_amount")
        assert_money(promotion["recognized_spend_amount"], 400.00,
                     "recognized_spend_amount")
        assert_money(promotion["accrued_balance"], -400.00, "accrued_balance")
        assert_ratio(promotion["spend_ratio"], 0.1000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["write_off_ytd_amount"], 400.00,
                     "write_off_ytd_amount")
        assert_money(customer["open_deduction_amount"], 0.00,
                     "open_deduction_amount")

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["at_risk_amount"], 0.00, "at_risk_amount")


class TestDisputedAmountBound:
    """The challenge may not exceed the claim it challenges."""

    def test_the_disputable_base_of_a_matched_claim_is_the_whole_claimed_amount(
        self, api
    ):
        """
        A dispute for more than the matched claim is refused, and one for exactly the claim opens with the documented null row.

        PRD: "That amount must be strictly greater than 0.00 and must not exceed the **disputable base**, which depends on how far the claim has travelled: while the deduction is still `RECEIVED` or `MATCHED` the whole `claimed_amount` is challengeable, but once it has been `VALIDATED` only the `variance_amount` is, because the validated portion has already been conceded."
        PRD: "A request past that ceiling is refused with `ERR_DISPUTED_AMOUNT_EXCEEDS_CLAIM` (HTTP 422)."
        PRD: "Opening a dispute moves the deduction's `status` to `DISPUTED` and creates one dispute row in `status` `OPEN`, with `opened_at` stamped from the logical clock, `opened_by_user_id` set to the acting specialist's identifier, `round_count` 0 and `retailer_response`, `recovered_amount`, `write_off_amount` and `resolved_by_user_id` all null."

        Design: Corner/errors/disputed_amount_is_bounded_by_the_claim
        """
        context = setup_allocation_context(api)
        promotion = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )["promotion"]
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=400.00
        )

        validate_error(
            api.dispute_deduction(
                deduction["id"], create_dispute_payload(500.00), SPECIALIST_HEADERS
            ),
            ApiErrorId.DISPUTED_AMOUNT_EXCEEDS_CLAIM.value,
        )
        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.MATCHED.value
        )

        dispute = validate_success(
            api.dispute_deduction(
                deduction["id"], create_dispute_payload(400.00), SPECIALIST_HEADERS
            ),
            expected_status=201,
        )
        assert_dispute(dispute)
        assert dispute["status"] == DisputeStatus.OPEN.value
        assert_money(dispute["disputed_amount"], 400.00, "disputed_amount")
        assert dispute["round_count"] == 0
        assert dispute["opened_by_user_id"] == SPECIALIST_USER_ID
        assert same_instant(dispute["opened_at"], DEFAULT_CLOCK_INSTANT)
        assert_null_fields(
            dispute,
            [
                "retailer_response",
                "recovered_amount",
                "write_off_amount",
                "resolved_by_user_id",
            ],
        )

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.DISPUTED.value
        )


class TestResolutionAmountsBound:
    """Both endings are capped by the amount actually in dispute."""

    def test_write_off_and_recovery_may_not_exceed_the_disputed_amount(self, api):
        """
        A partial dispute refuses both an oversized write-off and an oversized recovery, then settles at exactly the disputed amount as a recovery.

        PRD: "The request carries a `write_off_amount` and an optional `write_off_reason`; the amount must be strictly greater than 0.00 and no greater than the dispute's `disputed_amount`, or it is refused with `ERR_WRITE_OFF_EXCEEDS_OPEN_AMOUNT` (HTTP 422)."
        PRD: "**Recovery** is the good outcome: a `DeductionSpecialist` records a `recovered_amount` that is strictly greater than 0.00 and no greater than the dispute's `disputed_amount` — beyond that it is refused with `ERR_RECOVERY_EXCEEDS_OPEN_AMOUNT` (HTTP 422)."
        PRD: "The dispute moves to the terminal `RECOVERED`, storing `recovered_amount` and the acting user in `resolved_by_user_id`, and the parent deduction's `status` moves `DISPUTED` → `RECOVERED`."
        PRD: "Recovered cash is money back, so it lowers `net_spend` on the promotion's post-event analysis where one exists and lifts `roi` accordingly; the customer's `open_deduction_amount` drops because a `RECOVERED` deduction is closed."

        Design: Corner/errors/write_off_and_recovery_are_bounded_by_the_disputed_amount
        """
        context = setup_allocation_context(api)
        promotion = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )["promotion"]
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=500.00
        )
        dispute = open_dispute(
            api, deduction["id"], 100.00, headers=SPECIALIST_HEADERS
        )

        validate_error(
            api.write_off_dispute(
                dispute["id"], write_off_payload(200.00), SPECIALIST_ALT_HEADERS
            ),
            ApiErrorId.WRITE_OFF_EXCEEDS_OPEN_AMOUNT.value,
        )
        validate_error(
            api.record_dispute_recovery(
                dispute["id"], record_recovery_payload(150.00), SPECIALIST_HEADERS
            ),
            ApiErrorId.RECOVERY_EXCEEDS_OPEN_AMOUNT.value,
        )
        assert read_dispute(api, dispute["id"])["status"] == (
            DisputeStatus.OPEN.value
        )

        recovered = validate_success(
            api.record_dispute_recovery(
                dispute["id"], record_recovery_payload(100.00), SPECIALIST_HEADERS
            )
        )
        assert recovered["status"] == DisputeStatus.RECOVERED.value
        assert_money(recovered["recovered_amount"], 100.00, "recovered_amount")
        assert recovered["resolved_by_user_id"] == SPECIALIST_USER_ID
        assert_null_fields(recovered, ["write_off_amount"])

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.RECOVERED.value
        )

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["open_deduction_amount"], 0.00,
                     "open_deduction_amount")
        assert_money(customer["write_off_ytd_amount"], 0.00,
                     "write_off_ytd_amount")

        promotion = read_promotion(api, promotion["id"])
        assert_money(promotion["consumed_deduction_amount"], 0.00,
                     "consumed_deduction_amount")


class TestWriteOffAuthority:
    """Write-off authority is two gates, not one."""

    def test_both_the_identity_gate_and_the_amount_gate_must_be_cleared(self, api):
        """
        The opening specialist is refused on identity, a second specialist is refused on the 500.00 limit, and a director who did not open the dispute clears both.

        PRD: "Separately, and regardless of amount or role, the user recorded in the dispute's `opened_by_user_id` may never approve its write-off; that self-approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "A `write_off_amount` at or above 500.00 requires a `TradeMarketingDirector`: a `DeductionSpecialist` may approve write-offs strictly below that limit only, and because the comparison is inclusive an amount of exactly 500.00 already needs the director, while 499.99 does not — the refusal is `ERR_WRITE_OFF_APPROVAL_REQUIRED` (HTTP 403)."
        PRD: "A director who did not open the dispute clears both gates."
        PRD: "A successful write-off moves the dispute to the terminal `WRITTEN_OFF`, stores `write_off_amount`, `write_off_reason` and `resolved_by_user_id`, and moves the parent deduction's `status` `DISPUTED` → `WRITTEN_OFF`."

        Design: Corner/rbac/write_off_authority_turns_on_both_identity_and_amount
        """
        context = setup_allocation_context(api)
        promotion = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )["promotion"]
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=600.00
        )
        dispute = open_dispute(
            api, deduction["id"], 600.00, headers=SPECIALIST_HEADERS
        )

        validate_error(
            api.write_off_dispute(
                dispute["id"], write_off_payload(100.00), SPECIALIST_HEADERS
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )
        validate_error(
            api.write_off_dispute(
                dispute["id"], write_off_payload(500.00), SPECIALIST_ALT_HEADERS
            ),
            ApiErrorId.WRITE_OFF_APPROVAL_REQUIRED.value,
        )
        assert read_dispute(api, dispute["id"])["status"] == (
            DisputeStatus.OPEN.value
        )
        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.DISPUTED.value
        )

        resolved = validate_success(
            api.write_off_dispute(
                dispute["id"], write_off_payload(500.00), DIRECTOR_ALT_HEADERS
            )
        )
        assert resolved["status"] == DisputeStatus.WRITTEN_OFF.value
        assert_money(resolved["write_off_amount"], 500.00, "write_off_amount")
        assert resolved["resolved_by_user_id"] == DIRECTOR_ALT_USER_ID

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.WRITTEN_OFF.value
        )

        promotion = read_promotion(api, promotion["id"])
        assert_money(promotion["consumed_deduction_amount"], 500.00,
                     "consumed_deduction_amount")
        assert_money(promotion["recognized_spend_amount"], 500.00,
                     "recognized_spend_amount")
        assert_money(promotion["accrued_balance"], -500.00, "accrued_balance")

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["write_off_ytd_amount"], 500.00,
                     "write_off_ytd_amount")
        assert_money(customer["open_deduction_amount"], 0.00,
                     "open_deduction_amount")


class TestPortalAnswersItsOwnDispute:
    """The portal login answers only the dispute addressed to it."""

    def test_only_the_disputed_customers_own_portal_login_may_respond(self, api):
        """
        Another retailer's portal login and an internal specialist are both refused the answer, while the addressed customer's own login records it and returns the dispute to `OPEN`.

        PRD: "The retailer answers through the portal: the `CustomerPortalUser` whose identifier equals the disputed deduction's own `customer_id` posts a `retailer_response` of `ACCEPT_CHARGEBACK`, `PROVIDE_EVIDENCE` or `REFUSE`, which records that answer and returns `status` `AWAITING_RETAILER` → `OPEN`."
        PRD: "A portal user that addresses or filters a resource belonging to any other customer is refused with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."
        PRD: "Once the role is recognised, it is checked against the set of roles the target endpoint permits; a recognised role that is not on that list is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "`CustomerPortalUser` is the retailer's own portal login. Its only write capability is answering a dispute that has been sent to it."

        Design: Corner/rbac/the_portal_login_answers_a_dispute_addressed_to_it
        """
        context = setup_allocation_context(api)
        other_customer = setup_second_customer(api, context)
        promotion = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )["promotion"]
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=400.00
        )
        dispute = open_dispute(
            api, deduction["id"], 400.00, headers=SPECIALIST_HEADERS
        )
        sent = send_dispute(api, dispute["id"])
        assert sent["status"] == DisputeStatus.AWAITING_RETAILER.value
        assert sent["round_count"] == 1

        answer = retailer_respond_payload(
            retailer_response=RetailerResponse.PROVIDE_EVIDENCE.value
        )

        validate_error(
            api.retailer_respond_dispute(
                dispute["id"], answer, make_portal_user_headers(other_customer["id"])
            ),
            ApiErrorId.CUSTOMER_SCOPE_VIOLATION.value,
        )
        validate_error(
            api.retailer_respond_dispute(dispute["id"], answer, SPECIALIST_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )
        assert read_dispute(api, dispute["id"])["status"] == (
            DisputeStatus.AWAITING_RETAILER.value
        )

        answered = validate_success(
            api.retailer_respond_dispute(
                dispute["id"],
                answer,
                make_portal_user_headers(context["customer"]["id"]),
            )
        )
        assert_dispute(answered)
        assert answered["status"] == DisputeStatus.OPEN.value
        assert answered["retailer_response"] == (
            RetailerResponse.PROVIDE_EVIDENCE.value
        )
        assert answered["round_count"] == 1

        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.DISPUTED.value
        )
