"""
Deduction intake, matching, valuation and settlement.

The two valuation policies are exercised against byte-identical claim, evidence
and accrual data so that the divergence between the evidence-based and the
agreement-cap bases is visible in the numbers, and the four-hop cascade that a
single validation drives outward from the deduction is followed all the way to
the customer's commercial axis.
"""

from test_helpers import (
    AUTO_CREDIT_HOLD_REASON_PREFIX,
    AccrualMethod,
    AllocationPosture,
    ApiErrorId,
    DIRECTOR_HEADERS,
    DIRECTOR_USER_ID,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    DeductionStatus,
    DeductionValidationPolicy,
    DocType,
    FactType,
    MONDAY_AUG_10,
    PromotionLifecycleStatus,
    SPECIALIST_HEADERS,
    SPECIALIST_USER_ID,
    SpendStatus,
    TradingStatus,
    UserRole,
    assert_auto_credit_hold_reason,
    assert_deduction,
    assert_money,
    assert_null_fields,
    assert_ratio,
    create_deduction_payload,
    credit_hold_payload,
    current_promotion_version,
    get_success_data,
    instant,
    make_headers_for_role,
    match_deduction_payload,
    read_allocation,
    read_customer,
    read_deduction,
    read_promotion,
    same_instant,
    setup_allocation_context,
    setup_accrued_promotion,
    setup_approved_allocation,
    setup_approved_promotion,
    setup_deduction,
    setup_draft_promotion,
    setup_matched_deduction,
    setup_second_customer,
    setup_verified_evidence_document,
    validate_deduction,
    validate_deduction_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

EVIDENCE_BASED = DeductionValidationPolicy.EVIDENCE_BASED.value
AGREEMENT_CAP = DeductionValidationPolicy.AGREEMENT_CAP.value


def _policy_valuation_context(api, policy, claimed_amount=3000.00,
                              evidence_units=1800):
    """
    One accrued promotion whose customer carries the supplied policy flag.

    The commercial inputs are fixed so the only difference between two calls is
    the policy: a `TPR` line of 8000 cases at 1.250 gives a subtotal of
    10000.00, which earns the 0.020 allowance band and a `planned_total_spend`
    of 10200.00, and a single week of 2000 shipped cases accrues 2500.00.
    """
    context = setup_allocation_context(
        api, customer_overrides={"deduction_validation_policy": policy}
    )
    context = setup_accrued_promotion(
        api, context, fact_units=2000, planned_units=8000, rate_per_case=1.250
    )
    context["evidence_document"] = setup_verified_evidence_document(
        api, context["promotion"]["id"], units_verified=evidence_units
    )
    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=claimed_amount,
    )
    return context


class TestValuationPolicyDivergence:
    """The two valuation bases priced from identical claim and accrual data."""

    def test_evidence_based_entitlement_is_units_times_the_contract_rate(self, api):
        """
        Under the evidence policy entitlement is built up from verified cases and is never capped by the accrual balance.

        PRD: "Two inputs are then gathered from the matched promotion: the **contract rate**, which is the sum of `rate_per_case` across the promotion's `TPR` lines whose `status` is `PLANNED`, `ACTIVE` or `COMPLETED` — `DISPLAY` and `FEATURE` lines contribute no per-case rate; and the **evidence units**, which is the sum of `units_verified` across the promotion's documents whose `doc_class` is `EVIDENCE` and whose `status` is `VERIFIED`, with `SUBMITTED` evidence never counting."
        PRD: "Under `EVIDENCE_BASED`, `entitled_amount` is built bottom-up from substantiated cases: the evidence units multiplied by the contract rate, rounded half up to 2 decimal places, and it is **not** capped by the accrual balance — so a well-evidenced claim can legitimately exceed what was ever accrued and push the promotion over budget."
        PRD: "From `entitled_amount` two figures follow: `validated_amount` is the lesser of the claim's `claimed_amount` and its `entitled_amount` — the portion that will actually consume promotion accrual — and `variance_amount` is `claimed_amount` minus `validated_amount`, rounded half up to 2 decimal places, which is the invalid portion eligible for dispute."

        Design: Difficulty/dual_variant_calc/deduction_valuation_evidence_based_vs_agreement_cap_diverge
        """
        context = _policy_valuation_context(api, EVIDENCE_BASED)

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert_money(promotion["accrued_balance"], 2500.00, "accrued_balance")

        deduction = validate_deduction(
            api, context["deduction"]["id"], context["promotion"]["id"]
        )
        assert_deduction(deduction)
        assert deduction["status"] == DeductionStatus.VALIDATED.value
        assert deduction["validation_basis"] == EVIDENCE_BASED
        assert_money(deduction["entitled_amount"], 2250.00, "entitled_amount")
        assert_money(deduction["validated_amount"], 2250.00, "validated_amount")
        assert_money(deduction["variance_amount"], 750.00, "variance_amount")
        assert deduction["validated_by_user_id"] == ANALYST_USER_ID

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["consumed_deduction_amount"], 2250.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], 250.00, "accrued_balance")

    def test_agreement_cap_entitlement_is_the_accrued_balance(self, api):
        """
        Under the agreement-cap policy entitlement is the promotion's accrued balance and the verified evidence is ignored.

        PRD: "Under `AGREEMENT_CAP`, `entitled_amount` is top-down: it is exactly the matched promotion's `accrued_balance` as it stands at the moment of the request, before this deduction is applied, and evidence is ignored entirely."
        PRD: "From `entitled_amount` two figures follow: `validated_amount` is the lesser of the claim's `claimed_amount` and its `entitled_amount` — the portion that will actually consume promotion accrual — and `variance_amount` is `claimed_amount` minus `validated_amount`, rounded half up to 2 decimal places, which is the invalid portion eligible for dispute."

        Design: Difficulty/dual_variant_calc/deduction_valuation_evidence_based_vs_agreement_cap_diverge
        """
        context = _policy_valuation_context(api, AGREEMENT_CAP)

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert_money(promotion["accrued_balance"], 2500.00, "accrued_balance")

        deduction = validate_deduction(
            api, context["deduction"]["id"], context["promotion"]["id"]
        )
        assert_deduction(deduction)
        assert deduction["status"] == DeductionStatus.VALIDATED.value
        assert deduction["validation_basis"] == AGREEMENT_CAP
        assert_money(deduction["entitled_amount"], 2500.00, "entitled_amount")
        assert_money(deduction["validated_amount"], 2500.00, "validated_amount")
        assert_money(deduction["variance_amount"], 500.00, "variance_amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["consumed_deduction_amount"], 2500.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")

    def test_the_two_bases_return_different_figures_from_identical_data(self, api):
        """
        The same claim, the same verified evidence and the same accrual book value differently on the two bases.

        PRD: "From identical claim, evidence and accrual data the two bases return different figures, and which one is larger flips depending on whether evidence or accrual is the scarcer resource."
        PRD: "Valuation itself begins by copying the customer's `deduction_validation_policy` as it stands at that moment into the deduction's `validation_basis`, freezing the basis on the row."

        Design: Difficulty/dual_variant_calc/deduction_valuation_evidence_based_vs_agreement_cap_diverge
        """
        evidence_context = _policy_valuation_context(api, EVIDENCE_BASED)
        evidence_claim = validate_deduction(
            api, evidence_context["deduction"]["id"],
            evidence_context["promotion"]["id"],
        )

        cap_context = _policy_valuation_context(api, AGREEMENT_CAP)
        cap_claim = validate_deduction(
            api, cap_context["deduction"]["id"], cap_context["promotion"]["id"]
        )

        assert_money(evidence_claim["claimed_amount"], 3000.00, "claimed_amount")
        assert_money(cap_claim["claimed_amount"], 3000.00, "claimed_amount")

        assert evidence_claim["validation_basis"] == EVIDENCE_BASED
        assert cap_claim["validation_basis"] == AGREEMENT_CAP

        assert_money(evidence_claim["entitled_amount"], 2250.00, "entitled_amount")
        assert_money(cap_claim["entitled_amount"], 2500.00, "entitled_amount")
        assert evidence_claim["entitled_amount"] != cap_claim["entitled_amount"]
        assert evidence_claim["validated_amount"] < cap_claim["validated_amount"]
        assert evidence_claim["variance_amount"] > cap_claim["variance_amount"]


def _validated_agreement_cap_claim(api, claimed_amount=1000.00):
    """
    A `VALIDATED` claim of 1000.00 on an agreement-cap customer.

    The promotion accrues 2500.00 against a `planned_total_spend` of 10200.00,
    so the whole claim is entitled and 1500.00 of balance is left behind.
    """
    context = setup_allocation_context(
        api, customer_overrides={"deduction_validation_policy": AGREEMENT_CAP}
    )
    context = setup_accrued_promotion(
        api, context, fact_units=2000, planned_units=8000, rate_per_case=1.250
    )
    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=claimed_amount,
    )
    context["deduction"] = validate_deduction(
        api, context["deduction"]["id"], context["promotion"]["id"]
    )
    return context


class TestSettlementGatedOnTradingStatus:
    """Settlement of a priced claim turns on the customer's commercial axis."""

    def test_settlement_closes_the_claim_for_an_active_customer(self, api):
        """
        A validated claim on an `ACTIVE` retailer settles, stamping the logical clock and clearing the open figure.

        PRD: "A `TradeFinanceAnalyst` settles a claim that is currently `VALIDATED`, and the customer must be in `trading_status` `ACTIVE`: a retailer on `CREDIT_HOLD` or `SUSPENDED` cannot have deductions settled, and the attempt is refused with `ERR_CUSTOMER_CREDIT_HOLD`."
        PRD: "The move `VALIDATED` → `SETTLED` is terminal; `settled_at` is stamped with the logical clock instant, the allocation's `settled_amount` and the customer's `open_deduction_amount` are recomputed, and the deduction's, allocation's and customer's `version` values are each incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/deduction_settle_gated_on_customer_trading_status
        """
        context = _validated_agreement_cap_claim(api)
        assert_money(context["deduction"]["validated_amount"], 1000.00,
                     "validated_amount")
        assert_money(context["deduction"]["variance_amount"], 0.00, "variance_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert customer["trading_status"] == TradingStatus.ACTIVE.value

        settled = validate_success(
            api.settle_deduction(context["deduction"]["id"], ANALYST_HEADERS)
        )
        assert settled["status"] == DeductionStatus.SETTLED.value
        assert same_instant(settled["settled_at"], instant(MONDAY_AUG_10))

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["settled_amount"], 1000.00, "settled_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["open_deduction_amount"], 0.00, "open_deduction_amount")

    def test_settlement_is_refused_while_the_customer_is_on_credit_hold(self, api):
        """
        The identical settle request is refused once the retailer sits on `CREDIT_HOLD`, and nothing on the claim moves.

        PRD: "A `TradeFinanceAnalyst` settles a claim that is currently `VALIDATED`, and the customer must be in `trading_status` `ACTIVE`: a retailer on `CREDIT_HOLD` or `SUSPENDED` cannot have deductions settled, and the attempt is refused with `ERR_CUSTOMER_CREDIT_HOLD`."
        PRD: "Two rollups are maintained on the customer row: `open_deduction_amount`, the sum of `claimed_amount` over that customer's deductions whose status is `RECEIVED`, `MATCHED`, `VALIDATED` or `DISPUTED`, rounded half up to 2 decimal places; and `write_off_ytd_amount`, the sum of `write_off_amount` over every `WRITTEN_OFF` dispute raised on that customer's deductions, likewise rounded to 2 decimal places."

        Design: Difficulty/cross_entity_state_dependency/deduction_settle_gated_on_customer_trading_status
        """
        context = _validated_agreement_cap_claim(api)

        held = get_success_data(
            api.place_customer_credit_hold(
                context["customer"]["id"], credit_hold_payload(), SPECIALIST_HEADERS
            )
        )
        assert held["trading_status"] == TradingStatus.CREDIT_HOLD.value

        validate_error(
            api.settle_deduction(context["deduction"]["id"], ANALYST_HEADERS),
            ApiErrorId.CUSTOMER_CREDIT_HOLD.value,
        )

        deduction = read_deduction(api, context["deduction"]["id"])
        assert deduction["status"] == DeductionStatus.VALIDATED.value
        assert_null_fields(deduction, ["settled_at"])

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["settled_amount"], 0.00, "settled_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["open_deduction_amount"], 1000.00,
                     "open_deduction_amount")


def _overspend_cascade_context(api):
    """
    A validation large enough to push its promotion past its plan.

    Verified evidence of 9800 cases at the 1.250 contract rate entitles
    12250.00 against a `planned_total_spend` of 10200.00, so the recomputed
    ratio lands above 1.0000.
    """
    context = setup_allocation_context(api)
    context = setup_accrued_promotion(
        api, context, fact_units=2000, planned_units=8000, rate_per_case=1.250
    )
    context["evidence_document"] = setup_verified_evidence_document(
        api, context["promotion"]["id"], units_verified=9800
    )
    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=12500.00,
    )
    context["deduction"] = validate_deduction(
        api, context["deduction"]["id"], context["promotion"]["id"]
    )
    return context


class TestValidationOverspendCascade:
    """One validation walked outward from the claim to the customer row."""

    def test_validation_drives_the_promotion_overspent_and_restricts_the_allocation(self, api):
        """
        Consuming more accrual than was ever posted moves the promotion to `OVERSPENT` and restricts the funding allocation.

        PRD: "It then walks the four-hop chain of §2.9: the promotion's `consumed_deduction_amount` rises by `validated_amount` and its `accrued_balance` falls by the same amount; the spend status is recomputed from the new consumed figure and may reach `OVERSPENT`; reaching `OVERSPENT` for the first time increments the allocation's `overspend_event_count` and drives its `posture` `OPEN` → `RESTRICTED`; and the newly `RESTRICTED` allocation adds 10 points to the customer's `compliance_penalty_points`, which can drive that customer's `trading_status` `ACTIVE` → `CREDIT_HOLD`."
        PRD: "`recognized_spend_amount` is the **greater** of two views — the accrual-book view, `gross_accrued_amount` minus `reversed_accrual_amount`, and the deduction-book view, `consumed_deduction_amount` — rounded to 2 decimal places."
        PRD: "Otherwise `spend_ratio` is `recognized_spend_amount` divided by `planned_total_spend`, rounded half up to 4 decimal places, and `spend_status` follows exact boundaries: a ratio strictly greater than 1.0000 is `OVERSPENT`; a ratio at or above 0.9000 but not exceeding 1.0000 is `OVERSPEND_WARNING`; anything below 0.9000 is `WITHIN_BUDGET`."

        Design: Difficulty/transitive_cascade/deduction_validation_overspend_chain_reaches_customer_credit_hold
        """
        context = _overspend_cascade_context(api)

        deduction = context["deduction"]
        assert_money(deduction["entitled_amount"], 12250.00, "entitled_amount")
        assert_money(deduction["validated_amount"], 12250.00, "validated_amount")
        assert_money(deduction["variance_amount"], 250.00, "variance_amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["consumed_deduction_amount"], 12250.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], -9750.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 12250.00,
                     "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 1.2010, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.OVERSPENT.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert allocation["overspend_event_count"] == 1
        assert allocation["posture"] == AllocationPosture.RESTRICTED.value
        assert_money(allocation["accrued_amount"], 2500.00, "accrued_amount")

    def test_the_restricted_allocation_carries_the_customer_onto_credit_hold(self, api):
        """
        The fourth hop scores the restricted allocation on the customer and moves that retailer onto automatic credit hold.

        PRD: "The score is a weighted count of three populations: each of the customer's budget allocations currently in `RESTRICTED` posture contributes 10 points; each `ESCALATED` dispute raised on one of the customer's deductions contributes 5 points; and each compliance audit of that customer currently in `FINDINGS_ISSUED` contributes 10 points."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/deduction_validation_overspend_chain_reaches_customer_credit_hold
        """
        context = _overspend_cascade_context(api)

        customer = read_customer(api, context["customer"]["id"])
        assert customer["compliance_penalty_points"] == 10
        assert customer["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert customer["credit_hold_reason"] == (
            f"{AUTO_CREDIT_HOLD_REASON_PREFIX} 10"
        )
        assert_auto_credit_hold_reason(customer)
        assert_money(customer["open_deduction_amount"], 12500.00,
                     "open_deduction_amount")


class TestValuationReadsTheCustomerPolicy:
    """The stored policy flag, not the request, selects the valuation basis."""

    def test_an_agreement_cap_customer_is_valued_from_accrual_not_evidence(self, api):
        """
        A richly evidenced claim on an agreement-cap retailer is still capped by the accrual book, and the evidence never enters the figure.

        PRD: "The policy flag, by contrast, is one of the most consequential fields in the system: it is the **only** selector of how every future deduction from this retailer is valued, and it is never inferred from the claim itself."
        PRD: "Under `AGREEMENT_CAP`, `entitled_amount` is top-down: it is exactly the matched promotion's `accrued_balance` as it stands at the moment of the request, before this deduction is applied, and evidence is ignored entirely."
        PRD: "Valuation itself begins by copying the customer's `deduction_validation_policy` as it stands at that moment into the deduction's `validation_basis`, freezing the basis on the row."

        Design: Corner/calculations/deduction_valuation_reads_the_customer_policy_not_the_request
        """
        context = setup_allocation_context(
            api,
            program_overrides={
                "accrual_method_default": AccrualMethod.CONSUMPTION.value
            },
            customer_overrides={"deduction_validation_policy": AGREEMENT_CAP},
        )
        context = setup_accrued_promotion(
            api, context, fact_units=1000, fact_type=FactType.CONSUMPTION.value,
            planned_units=3000, rate_per_case=1.000,
        )
        setup_verified_evidence_document(
            api, context["promotion"]["id"], units_verified=2500
        )

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["planned_total_spend"], 3000.00, "planned_total_spend")
        assert_money(promotion["gross_accrued_amount"], 1000.00,
                     "gross_accrued_amount")
        assert_money(promotion["accrued_balance"], 1000.00, "accrued_balance")

        deduction = setup_matched_deduction(
            api, context["customer"]["id"], context["promotion"]["id"],
            claimed_amount=2000.00,
        )
        deduction = validate_deduction(
            api, deduction["id"], context["promotion"]["id"]
        )
        assert deduction["validation_basis"] == AGREEMENT_CAP
        assert_money(deduction["entitled_amount"], 1000.00, "entitled_amount")
        assert_money(deduction["validated_amount"], 1000.00, "validated_amount")
        assert_money(deduction["variance_amount"], 1000.00, "variance_amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["consumed_deduction_amount"], 1000.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 1000.00,
                     "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.3333, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value


class TestEvidenceEntitlementReEvaluation:
    """Entitlement is recomputed from the evidence standing at request time."""

    def test_verifying_more_evidence_raises_the_next_claim_entitlement(self, api):
        """
        A second verified evidence document lifts the entitlement of the next claim without touching the claim already priced.

        PRD: "Under `EVIDENCE_BASED`, `entitled_amount` is built bottom-up from substantiated cases: the evidence units multiplied by the contract rate, rounded half up to 2 decimal places, and it is **not** capped by the accrual balance — so a well-evidenced claim can legitimately exceed what was ever accrued and push the promotion over budget."
        PRD: "Two inputs are then gathered from the matched promotion: the **contract rate**, which is the sum of `rate_per_case` across the promotion's `TPR` lines whose `status` is `PLANNED`, `ACTIVE` or `COMPLETED` — `DISPLAY` and `FEATURE` lines contribute no per-case rate; and the **evidence units**, which is the sum of `units_verified` across the promotion's documents whose `doc_class` is `EVIDENCE` and whose `status` is `VERIFIED`, with `SUBMITTED` evidence never counting."
        PRD: "`consumed_deduction_amount` is the sum of two populations, each rounded to 2 decimal places and then added: `validated_amount` over the promotion's deductions whose `status` is `VALIDATED` or `SETTLED`, plus `write_off_amount` over every `WRITTEN_OFF` dispute raised on one of the promotion's deductions."

        Design: Corner/calculations/evidence_entitlement_re_evaluates_when_more_evidence_is_verified
        """
        context = setup_approved_promotion(
            api, planned_units=5000, rate_per_case=1.000
        )
        promotion_id = context["promotion"]["id"]
        promotion = read_promotion(api, promotion_id)
        assert_money(promotion["planned_total_spend"], 5000.00, "planned_total_spend")

        setup_verified_evidence_document(api, promotion_id, units_verified=400)

        first = setup_matched_deduction(
            api, context["customer"]["id"], promotion_id, claimed_amount=1000.00
        )
        first = validate_deduction(api, first["id"], promotion_id)
        assert_money(first["entitled_amount"], 400.00, "entitled_amount")
        assert_money(first["validated_amount"], 400.00, "validated_amount")
        assert_money(first["variance_amount"], 600.00, "variance_amount")

        setup_verified_evidence_document(
            api, promotion_id, units_verified=300,
            doc_type=DocType.DISPLAY_PHOTO.value,
        )

        second = setup_matched_deduction(
            api, context["customer"]["id"], promotion_id, claimed_amount=1000.00
        )
        second = validate_deduction(api, second["id"], promotion_id)
        assert_money(second["entitled_amount"], 700.00, "entitled_amount")
        assert_money(second["validated_amount"], 700.00, "validated_amount")
        assert_money(second["variance_amount"], 300.00, "variance_amount")

        reread_first = read_deduction(api, first["id"])
        assert_money(reread_first["entitled_amount"], 400.00, "entitled_amount")
        assert_money(reread_first["validated_amount"], 400.00, "validated_amount")

        promotion = read_promotion(api, promotion_id)
        assert_money(promotion["consumed_deduction_amount"], 1100.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], -1100.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 1100.00,
                     "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.2200, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value


class TestMatchCoherenceOrder:
    """The two coherence conditions of matching, in their declared order."""

    def test_customer_mismatch_is_reported_before_promotion_matchability(self, api):
        """
        Matching a claim to another retailer's `DRAFT` promotion reports the ownership failure, not the matchability failure.

        PRD: "A `DeductionSpecialist` matches a claim that is currently `RECEIVED` by supplying the `promotion_id` of the target agreement, and two coherence conditions apply in this order: the promotion must belong to the deduction's own `customer_id`, or the request is refused with `ERR_DEDUCTION_CUSTOMER_MISMATCH` (HTTP 422); and the promotion's `lifecycle_status` must be `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, because a promotion still in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`, or one already `WITHDRAWN`, is not a matchable agreement — that refusal is `ERR_PROMOTION_NOT_MATCHABLE` (HTTP 409)."

        Design: Corner/validations/deduction_customer_mismatch_outranks_promotion_matchability
        """
        context = setup_allocation_context(api)
        other_customer = setup_second_customer(api, context)
        other_allocation = setup_approved_allocation(
            api, context["program"]["id"], other_customer["id"],
            context["brand"]["id"],
        )
        other_context = setup_draft_promotion(
            api,
            {
                "program": context["program"],
                "brand": context["brand"],
                "customer": other_customer,
                "allocation": other_allocation,
            },
        )
        other_promotion = other_context["promotion"]
        assert other_promotion["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value

        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=750.00
        )
        validate_error(
            api.match_deduction(
                deduction["id"], match_deduction_payload(other_promotion["id"]),
                SPECIALIST_HEADERS,
            ),
            ApiErrorId.DEDUCTION_CUSTOMER_MISMATCH.value,
        )

        deduction = read_deduction(api, deduction["id"])
        assert deduction["status"] == DeductionStatus.RECEIVED.value
        assert_null_fields(deduction, ["promotion_id", "matched_by_user_id"])

        assert read_promotion(api, other_promotion["id"])["lifecycle_status"] == (
            PromotionLifecycleStatus.DRAFT.value
        )


class TestEvidencePreconditionScope:
    """The evidence precondition is scoped to the evidence-based policy alone."""

    def test_the_evidence_requirement_binds_only_the_evidence_based_policy(self, api):
        """
        A claim with no evidence at all is refused under the evidence policy and priced under the agreement-cap policy.

        PRD: "Under the `EVIDENCE_BASED` policy the matched promotion must carry at least one `VERIFIED` `EVIDENCE` document with a `units_verified` greater than zero, or the request is refused with `ERR_NO_PERFORMANCE_EVIDENCE` (HTTP 422)."
        PRD: "Under the `AGREEMENT_CAP` policy that rule does not apply at all; instead the promotion's `accrued_balance` must be strictly greater than 0.00, or the request is refused with `ERR_ACCRUAL_BALANCE_INSUFFICIENT` (HTTP 422) because there is nothing left on the agreement to allow."
        PRD: "The same request body therefore succeeds or fails purely on the customer's policy flag."

        Design: Corner/validations/evidence_requirement_applies_only_under_the_evidence_policy
        """
        evidence_context = setup_approved_promotion(
            api, planned_units=5000, rate_per_case=1.000
        )
        evidence_claim = setup_matched_deduction(
            api, evidence_context["customer"]["id"],
            evidence_context["promotion"]["id"], claimed_amount=800.00,
        )
        validate_error(
            api.validate_deduction(
                evidence_claim["id"],
                validate_deduction_payload(
                    current_promotion_version(api, evidence_context["promotion"]["id"])
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.NO_PERFORMANCE_EVIDENCE.value,
        )
        evidence_claim = read_deduction(api, evidence_claim["id"])
        assert evidence_claim["status"] == DeductionStatus.MATCHED.value
        assert_null_fields(
            evidence_claim,
            ["validation_basis", "entitled_amount", "validated_amount",
             "variance_amount", "validated_by_user_id"],
        )

        cap_context = setup_allocation_context(
            api,
            program_overrides={
                "accrual_method_default": AccrualMethod.CONSUMPTION.value
            },
            customer_overrides={"deduction_validation_policy": AGREEMENT_CAP},
        )
        cap_context = setup_accrued_promotion(
            api, cap_context, fact_units=1000,
            fact_type=FactType.CONSUMPTION.value,
            planned_units=5000, rate_per_case=1.000,
        )
        cap_claim = setup_matched_deduction(
            api, cap_context["customer"]["id"], cap_context["promotion"]["id"],
            claimed_amount=800.00,
        )
        cap_claim = validate_deduction(
            api, cap_claim["id"], cap_context["promotion"]["id"]
        )
        assert cap_claim["status"] == DeductionStatus.VALIDATED.value
        assert cap_claim["validation_basis"] == AGREEMENT_CAP
        assert_money(cap_claim["entitled_amount"], 1000.00, "entitled_amount")
        assert_money(cap_claim["validated_amount"], 800.00, "validated_amount")
        assert_money(cap_claim["variance_amount"], 0.00, "variance_amount")

        promotion = read_promotion(api, cap_context["promotion"]["id"])
        assert_money(promotion["accrued_balance"], 200.00, "accrued_balance")


class TestDeductionMatchEndpoint:
    """Matching writes the foreign key the whole valuation pipeline hangs on."""

    def test_match_links_the_claim_to_its_promotion_and_the_list_filter(self, api):
        """
        A successful match stores the promotion, records the acting specialist and makes the claim visible under the promotion filter.

        PRD: "A new claim is created in `status` `RECEIVED` with `promotion_id`, `validation_basis`, `entitled_amount`, `validated_amount`, `variance_amount`, `matched_by_user_id`, `validated_by_user_id` and `settled_at` all null."
        PRD: "A successful match moves `status` `RECEIVED` → `MATCHED`, stores the `promotion_id` and records the acting specialist in `matched_by_user_id`, and increments the deduction's `version` by 1."
        PRD: "Deductions may be listed with optional `customer_id`, `promotion_id`, `status` and `supersedes_deduction_id` filters."

        Design: Corner/endpoints/deduction_match_links_the_claim_to_its_promotion
        """
        context = setup_approved_promotion(
            api, planned_units=4000, rate_per_case=1.000
        )
        promotion_id = context["promotion"]["id"]

        deduction = setup_deduction(
            api, context["customer"]["id"], claimed_amount=1200.00
        )
        assert deduction["status"] == DeductionStatus.RECEIVED.value
        assert_null_fields(
            deduction,
            ["promotion_id", "validation_basis", "entitled_amount",
             "validated_amount", "variance_amount", "matched_by_user_id",
             "validated_by_user_id", "settled_at"],
        )

        rows, meta = validate_paginated(
            api.list_deductions(SPECIALIST_HEADERS,
                                params={"promotion_id": promotion_id})
        )
        assert meta["total_count"] == 0
        assert rows == []

        matched = validate_success(
            api.match_deduction(
                deduction["id"], match_deduction_payload(promotion_id),
                SPECIALIST_HEADERS,
            )
        )
        assert matched["status"] == DeductionStatus.MATCHED.value
        assert matched["promotion_id"] == promotion_id
        assert matched["matched_by_user_id"] == SPECIALIST_USER_ID
        assert_null_fields(
            matched, ["validation_basis", "validated_amount", "variance_amount"]
        )

        rows, meta = validate_paginated(
            api.list_deductions(SPECIALIST_HEADERS,
                                params={"promotion_id": promotion_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [deduction["id"]]

        customer = read_customer(api, context["customer"]["id"])
        assert_money(customer["open_deduction_amount"], 1200.00,
                     "open_deduction_amount")


class TestClaimReferenceUniqueness:
    """The retailer's own reference is unique inside one customer."""

    def test_a_repeated_claim_reference_is_refused_for_the_same_customer(self, api):
        """
        Booking the same retailer reference twice against one customer is refused and leaves the first claim alone.

        PRD: "`claim_reference` must be unique per `customer_id` across every deduction of that customer in every status; a repeat is refused with `ERR_DUPLICATE_CLAIM_REFERENCE` (HTTP 409)."
        PRD: "Two rollups are maintained on the customer row: `open_deduction_amount`, the sum of `claimed_amount` over that customer's deductions whose status is `RECEIVED`, `MATCHED`, `VALIDATED` or `DISPUTED`, rounded half up to 2 decimal places; and `write_off_ytd_amount`, the sum of `write_off_amount` over every `WRITTEN_OFF` dispute raised on that customer's deductions, likewise rounded to 2 decimal places."

        Design: Corner/errors/claim_reference_is_unique_within_the_customer
        """
        context = setup_allocation_context(api)
        customer_id = context["customer"]["id"]

        first = validate_success(
            api.create_deduction(
                create_deduction_payload(
                    customer_id, claim_reference="MM-CHK-77421",
                    claimed_amount=900.00,
                ),
                SPECIALIST_HEADERS,
            ),
            expected_status=201,
        )
        assert first["claim_reference"] == "MM-CHK-77421"

        validate_error(
            api.create_deduction(
                create_deduction_payload(
                    customer_id, claim_reference="MM-CHK-77421",
                    claimed_amount=250.00,
                ),
                SPECIALIST_HEADERS,
            ),
            ApiErrorId.DUPLICATE_CLAIM_REFERENCE.value,
        )

        rows, meta = validate_paginated(
            api.list_deductions(SPECIALIST_HEADERS,
                                params={"customer_id": customer_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]

        customer = read_customer(api, customer_id)
        assert_money(customer["open_deduction_amount"], 900.00,
                     "open_deduction_amount")


class TestAgreementCapNeedsAnAccrualBook:
    """The agreement-cap policy has nothing to allow on an unaccrued promotion."""

    def test_validation_is_refused_when_the_accrued_balance_is_zero(self, api):
        """
        An agreement-cap claim matched to a promotion that has never been accrued is refused and stays `MATCHED`.

        PRD: "Under the `AGREEMENT_CAP` policy that rule does not apply at all; instead the promotion's `accrued_balance` must be strictly greater than 0.00, or the request is refused with `ERR_ACCRUAL_BALANCE_INSUFFICIENT` (HTTP 422) because there is nothing left on the agreement to allow."
        PRD: "`accrued_balance` is `gross_accrued_amount` minus `reversed_accrual_amount` minus `consumed_deduction_amount`, rounded to 2 decimal places, and it may legitimately be negative when a retailer has deducted more than was ever accrued."

        Design: Corner/errors/agreement_cap_validation_needs_an_accrual_book
        """
        context = setup_allocation_context(
            api, customer_overrides={"deduction_validation_policy": AGREEMENT_CAP}
        )
        context = setup_approved_promotion(
            api, context, planned_units=4000, rate_per_case=1.000
        )
        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 0.00, "gross_accrued_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")

        claim = setup_matched_deduction(
            api, context["customer"]["id"], promotion["id"], claimed_amount=600.00
        )
        validate_error(
            api.validate_deduction(
                claim["id"],
                validate_deduction_payload(
                    current_promotion_version(api, promotion["id"])
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ACCRUAL_BALANCE_INSUFFICIENT.value,
        )

        claim = read_deduction(api, claim["id"])
        assert claim["status"] == DeductionStatus.MATCHED.value
        assert_null_fields(
            claim,
            ["validation_basis", "entitled_amount", "validated_amount",
             "variance_amount", "validated_by_user_id"],
        )


class TestValidationSegregationOfDuties:
    """The approving operator hands valuation to a second analyst."""

    def test_the_promotion_approver_may_not_validate_but_another_analyst_may(self, api):
        """
        The operator who approved the promotion is refused on validation, and a different analyst succeeds against the same version.

        PRD: "The operator recorded in a promotion's `approved_by_user_id` may not validate any deduction matched to that promotion."
        PRD: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "Four conditions guard it beyond the state check: the stale-version rejection of §2.6; the segregation-of-duties rule, so the operator whose identifier sits in the matched promotion's `approved_by_user_id` may not validate this claim and is refused with `ERR_SEGREGATION_OF_DUTIES` while any other analyst succeeds; and then one of two policy-specific preconditions."
        PRD: "A successful validation moves `status` `MATCHED` → `VALIDATED`, writes `validation_basis`, `entitled_amount`, `validated_amount` and `variance_amount`, and records the acting analyst in `validated_by_user_id`."

        Design: Corner/rbac/promotion_approver_hands_validation_to_a_second_analyst
        """
        context = setup_approved_promotion(
            api, approver_headers=DIRECTOR_HEADERS,
            planned_units=4000, rate_per_case=1.000,
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["approved_by_user_id"] == DIRECTOR_USER_ID

        setup_verified_evidence_document(api, promotion_id, units_verified=500)
        claim = setup_matched_deduction(
            api, context["customer"]["id"], promotion_id, claimed_amount=400.00
        )

        expected_version = current_promotion_version(api, promotion_id)
        approver_as_analyst = make_headers_for_role(
            UserRole.TRADE_FINANCE_ANALYST.value, DIRECTOR_USER_ID
        )
        validate_error(
            api.validate_deduction(
                claim["id"], validate_deduction_payload(expected_version),
                approver_as_analyst,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        assert read_deduction(api, claim["id"])["status"] == (
            DeductionStatus.MATCHED.value
        )
        assert current_promotion_version(api, promotion_id) == expected_version

        validated = validate_success(
            api.validate_deduction(
                claim["id"], validate_deduction_payload(expected_version),
                ANALYST_HEADERS,
            )
        )
        assert validated["status"] == DeductionStatus.VALIDATED.value
        assert validated["validation_basis"] == EVIDENCE_BASED
        assert_money(validated["entitled_amount"], 500.00, "entitled_amount")
        assert_money(validated["validated_amount"], 400.00, "validated_amount")
        assert_money(validated["variance_amount"], 0.00, "variance_amount")
        assert validated["validated_by_user_id"] == ANALYST_USER_ID

        promotion = read_promotion(api, promotion_id)
        assert_money(promotion["consumed_deduction_amount"], 400.00,
                     "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], -400.00, "accrued_balance")
