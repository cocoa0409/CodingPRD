"""Servicing and recovery refusals: state gates, exact cash and two temporal bars.

Every case here is a request the platform must turn away, and each one is paired
with the neighbouring request that must succeed — one cent lower, one arm over, or
one instant later — so that a gate cannot be passed by being permanently shut. The
refused writes leave no row, no bucket movement and no version bump behind.
"""

from test_helpers import (
    ApiErrorId,
    assert_allocation_sums_to_amount,
    assert_insurance_policy,
    assert_instant_equals,
    assert_obligation_buckets_zeroed,
    assert_payment_transaction,
    assert_recovery_case,
    assert_reversal_negates,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ACCRUAL_CLOCK = "2026-09-01T00:00:00Z"

# ─── The canonical funded chattel loan ───
PRINCIPAL_CENTS = 4_600_000
REQUESTED_TERM_MONTHS = 240
DWELLING_COVERAGE_CENTS = 4_700_000
REQUIRED_COVERAGE_CENTS = 4_621_122
POLICY_EFFECTIVE_DATE = "2026-08-01T00:00:00Z"
POLICY_EXPIRY_DATE = "2027-08-01T00:00:00Z"

# ─── Thirty-one days of interest at 1275 bps on 4,600,000 ───
# apr_bps 1275 = 875 base + 225 community + 175 personal property, a 705 score
# taking neither credit nor charge and an ltv of 7964 taking no leverage spread.
ACCRUAL_DAYS = 31
ACCRUED_INTEREST_CENTS = 49_812
TOTAL_OBLIGATION_CENTS = 4_649_812
ONE_CENT_TOO_MUCH_CENTS = 4_649_813
TWELVE_CENTS_SHORT_CENTS = 4_649_800
ABSORBED_PAYMENT_CENTS = 100_000
TO_PRINCIPAL_CENTS = 50_188
PRINCIPAL_AFTER_PAYMENT_CENTS = 4_549_812

# ─── Delinquency and default on the repossession arm ───
FIRST_ASSESSMENT_CLOCK = "2026-10-01T00:00:00Z"
SECOND_ASSESSMENT_CLOCK = "2026-11-01T00:00:00Z"
DELINQUENT_DAYS_AT_THIRTY = 30
DELINQUENT_DAYS_AT_SIXTY_ONE = 61
INTEREST_AT_SIXTY_ONE_DAYS_CENTS = 98_018
INTEREST_AT_NINETY_TWO_DAYS_CENTS = 147_830
LATE_FEE_CENTS = 3_500
REPOSSESSION_EXPENSE_CENTS = 185_000
CURE_DEADLINE = "2026-11-11T00:00:00Z"
NOTICE_REFERENCE = "RTC-2026-11-0007"

# ─── The real-property foreclosure arm ───
# apr_bps 975 = 875 base + 50 private land + 175 personal property (the pricing-time
# classification) less a 125 credit for a 728 score; 122 days on 1,500,000.
LAND_PRINCIPAL_CENTS = 1_500_000
LAND_INTEREST_CENTS = 48_884
FORECLOSURE_ASSESSMENT_CLOCK = "2026-12-01T00:00:00Z"
DELINQUENT_DAYS_AT_NINETY_ONE = 91
FORECLOSURE_EXPENSE_CENTS = 425_000
REDEMPTION_WINDOW_END = "2027-01-15T00:00:00Z"
DOCKET_REFERENCE = "FC-2026-12-0042"


def _funded_chattel_loan(api):
    """A piered MULTI_WIDE on an executed Pine Ridge lot, funded on 2026-08-01."""
    return fixtures.setup_funded_community_loan(
        api,
        clock=CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
    )


def _funded_chattel_loan_one_month_on(api):
    """The same loan with the clock at 2026-09-01, exactly 31 days after funding."""
    scenario = _funded_chattel_loan(api)
    fixtures.set_clock(api, ACCRUAL_CLOCK)
    return scenario


def _defaulted_repossession_case(api):
    """The same loan taken to 61 delinquent days and default-declared."""
    return fixtures.setup_defaulted_community_loan(
        api,
        assessment_clock=SECOND_ASSESSMENT_CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
    )


def test_force_placement_has_nothing_to_buy_against_a_covered_loan(api):
    """PRD §3.6: "A `Servicer` force-places coverage on a loan whose
    `insurance_compliance` is `NON_COMPLIANT`, naming a `carrier_name`, a
    `policy_number` and the `effective_date` and `expiry_date` of the placed coverage.
    There is nothing to force-place against a loan that is already compliant, and the
    attempt is refused with `ERR_INSURANCE_ALREADY_COMPLIANT` (HTTP 409). The created
    policy carries `source` `FORCE_PLACED`, `wind_endorsement` true, and
    `dwelling_coverage_cents` set exactly to `required_coverage_cents` — the lender
    buys precisely what the matrix demands and no more."
    PRD §3.6: "The insurable value is the `certified_value_cents` of the loan's
    certified origination valuation. The exposure is the loan's
    `principal_balance_cents` once the loan has reached `FUNDED`, and its
    `principal_cents` before that. The `required_coverage_cents` figure is then the
    greater of that exposure and the insurable value multiplied by the
    required-coverage ratio for the loan's `collateral_classification` divided by ten
    thousand, rounded half up — where the ratio is 8000 basis points, four fifths of
    insurable value, for `PERSONAL_PROPERTY` and 10000 basis points, the whole
    insurable value, for `REAL_PROPERTY`."
    PRD §3.6: "A policy's `compliance_state` is therefore `DEFICIENT_WIND` when wind
    coverage is required and the policy carries no `wind_endorsement`; otherwise it is
    `DEFICIENT_COVERAGE` when the policy's `dwelling_coverage_cents` is below
    `required_coverage_cents`; otherwise it is `COMPLIANT`."
    PRD §3.6: "The resulting `premium_cents` is added to the loan's
    `force_placed_premium_outstanding_cents`, which is the unreimbursed advance the
    borrower now owes on top of principal, interest and fees. Force-placement
    recomputes the loan's `insurance_compliance` to `COMPLIANT` and increments the
    loan's `version`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."

    Design: Corner/validations/force_placing_against_a_compliant_loan_is_refused
    """
    scenario = _funded_chattel_loan(api)
    loan_id = scenario["loan"]["id"]
    funded_version = scenario["loan"]["version"]
    policy = fixtures.read_policy(api, scenario["policy"]["id"])

    assert_insurance_policy(policy)
    assert policy["source"] == "BORROWER_PROVIDED"
    assert policy["required_coverage_cents"] == REQUIRED_COVERAGE_CENTS, (
        "8000 bps of the certified 5,776,403 beats the 4,600,000 exposure"
    )
    assert policy["dwelling_coverage_cents"] == DWELLING_COVERAGE_CENTS
    assert policy["compliance_state"] == "COMPLIANT"

    validate_error(
        api.force_place_insurance(
            loan_id,
            factories.force_place_payload(POLICY_EFFECTIVE_DATE, POLICY_EXPIRY_DATE),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_INSURANCE_ALREADY_COMPLIANT.value,
        409,
    )

    loan = fixtures.read_loan(api, loan_id)
    assert loan["insurance_compliance"] == "COMPLIANT"
    assert loan["force_placed_premium_outstanding_cents"] == 0, (
        "a refused placement advances nothing, so there is no premium to reimburse"
    )
    assert loan["version"] == funded_version, (
        "only a placement that happens increments the loan"
    )

    rows, meta = validate_paginated(
        api.list_insurance_policies(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1, "no lender-placed row was written"
    assert [row["id"] for row in rows] == [policy["id"]]
    assert rows[0]["source"] == "BORROWER_PROVIDED"


def test_an_approved_loan_has_no_servicing_life_until_it_is_funded(api):
    """PRD §3.7: "Servicing writes are only available while the loan's
    `servicing_state` is `CURRENT` or `DELINQUENT` — payments, periodic assessment,
    lot-rent reporting and force-placement all require one of those two, and default
    declaration requires `DELINQUENT` specifically. Any of them attempted from the
    wrong servicing standing is refused with `ERR_LOAN_SERVICING_INVALID_STATE`
    (HTTP 409)."
    PRD §3.4: "A successful funding advances `underwriting_state` from `APPROVED` to
    `FUNDED` and, as a cascade onto the servicing dimension, advances
    `servicing_state` from `NOT_SERVICING` to `CURRENT`. It stamps `funded_at` and
    `last_accrual_date` with the logical clock and sets `next_due_date` to the
    supplied `first_due_date`. It sets `principal_balance_cents` to `principal_cents`,
    opening the loan's unpaid principal."
    PRD §3.7: "The operator may only report on loans whose collateral sits in its own
    community."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that starts
    at 1 and increments by exactly one on every mutation."

    Design: Corner/validations/servicing_actions_on_an_approved_but_unfunded_loan_are_refused
    """
    scenario = fixtures.setup_community_collateral(api, clock=CLOCK)
    scenario = fixtures.setup_approved_loan(
        api,
        scenario,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    loan_id = scenario["loan"]["id"]
    fixtures.record_policy(api, loan_id, DWELLING_COVERAGE_CENTS)
    fixtures.perfect_with_title_lien(api, loan_id)

    approved = fixtures.read_loan(api, loan_id)
    assert approved["underwriting_state"] == "APPROVED"
    assert approved["servicing_state"] == "NOT_SERVICING", (
        "priced, insured and perfected is still not funded"
    )
    version_before = approved["version"]

    validate_error(
        api.create_payment(
            loan_id,
            factories.payment_payload(ABSORBED_PAYMENT_CENTS),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_LOAN_SERVICING_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.servicing_assessment(loan_id, fixtures.SERVICER),
        ApiErrorId.ERR_LOAN_SERVICING_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.lot_rent_report(
            loan_id,
            factories.lot_rent_report_payload(1),
            fixtures.make_community_operator_headers(scenario["community"]["id"]),
        ),
        ApiErrorId.ERR_LOAN_SERVICING_INVALID_STATE.value,
        409,
    )

    loan = fixtures.read_loan(api, loan_id)
    assert loan["underwriting_state"] == "APPROVED"
    assert loan["servicing_state"] == "NOT_SERVICING"
    assert loan["principal_balance_cents"] == 0, (
        "principal is opened by funding, and funding has not happened"
    )
    assert loan["interest_accrued_unpaid_cents"] == 0
    assert loan["version"] == version_before, "three refusals, no mutation"

    _, meta = validate_paginated(
        api.list_payments(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 0


def test_a_scheduled_payment_one_cent_past_the_last_bucket_is_refused(api):
    """PRD §3.7: "Cash that the buckets cannot absorb is refused rather than held. If
    any amount remains unallocated after the whole waterfall has run and the
    `payment_kind` is `SCHEDULED` or `PARTIAL`, the posting is rejected with
    `ERR_OVERPAYMENT_NOT_PERMITTED` (HTTP 422)."
    PRD §3.7: "The `accrual_days` figure is the whole calendar days from the loan's
    `last_accrual_date` up to the logical clock, over a half-open interval. The accrued
    amount is the loan's `principal_balance_cents` multiplied by its `apr_bps` divided
    by ten thousand, multiplied by `accrual_days` and divided by 365 — an
    actual-over-365 day count — with the whole product evaluated exactly and rounded
    half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the logical
    clock."
    PRD §3.7: "The platform stamps `posted_at` with the logical clock, records on the
    row the `accrual_days` it counted and the `accrued_interest_at_posting_cents` it
    added to the loan, and then applies the cash through a waterfall."
    PRD §3.7: "Which waterfall is the single most consequential effect of collateral
    classification on the servicing side, and the row records the choice in
    `allocation_variant`. When the loan's `collateral_classification` is
    `PERSONAL_PROPERTY` the order is `CHATTEL_CONTRACT_ORDER`: accrued interest, then
    outstanding fees, then the force-placed premium, then the escrow shortfall, then
    principal."
    PRD §3.7: "The escrow bucket for this purpose is the shortfall — the
    `escrow_target_cents` less the current `escrow_balance_cents`, floored at zero, so a
    fully funded escrow absorbs nothing. Each bucket in turn absorbs the smaller of the
    cash still unallocated and its own outstanding amount, and the cash remaining is
    reduced by what was absorbed. The five amounts absorbed are recorded on the row as
    `to_interest_cents`,
    `to_fees_cents`, `to_force_placed_cents`, `to_escrow_cents` and
    `to_principal_cents`, and the loan's corresponding buckets are decremented by
    exactly those amounts while `escrow_balance_cents` is credited by the escrow
    allocation."

    Design: Corner/validations/scheduled_payment_one_cent_beyond_the_last_bucket_is_refused
    """
    scenario = _funded_chattel_loan_one_month_on(api)
    loan_id = scenario["loan"]["id"]

    validate_error(
        api.create_payment(
            loan_id,
            factories.payment_payload(ONE_CENT_TOO_MUCH_CENTS, "SCHEDULED"),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_OVERPAYMENT_NOT_PERMITTED.value,
        422,
    )

    payment = validate_success(
        api.create_payment(
            loan_id,
            factories.payment_payload(ABSORBED_PAYMENT_CENTS, "SCHEDULED"),
            fixtures.SERVICER,
        ),
        201,
    )

    assert_payment_transaction(payment)
    assert payment["accrual_days"] == ACCRUAL_DAYS, (
        "the refused posting did not advance last_accrual_date, so all 31 days are "
        "still here to accrue"
    )
    assert payment["accrued_interest_at_posting_cents"] == ACCRUED_INTEREST_CENTS
    assert payment["allocation_variant"] == "CHATTEL_CONTRACT_ORDER"
    assert payment["to_interest_cents"] == ACCRUED_INTEREST_CENTS
    assert payment["to_fees_cents"] == 0
    assert payment["to_force_placed_cents"] == 0
    assert payment["to_escrow_cents"] == 0
    assert payment["to_principal_cents"] == TO_PRINCIPAL_CENTS
    assert_allocation_sums_to_amount(payment)

    loan = fixtures.read_loan(api, loan_id)
    assert loan["interest_accrued_unpaid_cents"] == 0
    assert loan["principal_balance_cents"] == PRINCIPAL_AFTER_PAYMENT_CENTS, (
        "one cent more than the whole obligation is refused, but every cent up to it "
        "is absorbed"
    )
    assert_instant_equals(loan["last_accrual_date"], ACCRUAL_CLOCK, "Loan.last_accrual_date")
    assert loan["servicing_state"] == "CURRENT"

    _, meta = validate_paginated(
        api.list_payments(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1, "the refused posting left no row behind"


def test_a_payoff_must_match_the_computed_figure_to_the_cent(api):
    """PRD §3.7: "For a `payment_kind` of `PAYOFF`, the `amount_cents` must equal the
    sum of `interest_accrued_unpaid_cents` measured after accrual has run, plus
    `fees_outstanding_cents`, plus `force_placed_premium_outstanding_cents`, plus
    `principal_balance_cents`, less `escrow_balance_cents` — the escrow being the
    borrower's own money and therefore a credit against what is owed. Any other figure,
    high or low, is refused with `ERR_PAYOFF_AMOUNT_MISMATCH` (HTTP 422). A payoff that
    matches zeroes every obligation bucket, refunds whatever sat in
    `escrow_balance_cents`, moves the loan's servicing standing from `CURRENT` to
    `PAID_OFF`, moves the lien dimension from `PERFECTED` to `RELEASED`, and moves the
    recorded filing to `RELEASED` with `released_at` stamped."
    PRD §3.7: "The `accrual_days` figure is the whole calendar days from the loan's
    `last_accrual_date` up to the logical clock, over a half-open interval. The accrued
    amount is the loan's `principal_balance_cents` multiplied by its `apr_bps` divided
    by ten thousand, multiplied by `accrual_days` and divided by 365 — an
    actual-over-365 day count — with the whole product evaluated exactly and rounded
    half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the logical
    clock."
    PRD §3.7: "If any amount remains unallocated after the whole waterfall has run and
    the `payment_kind` is `SCHEDULED` or `PARTIAL`, the posting is rejected with
    `ERR_OVERPAYMENT_NOT_PERMITTED` (HTTP 422)."
    PRD §3.1: "A borrower's `total_outstanding_principal_cents` begins at 0 and is at
    all times the sum of `principal_balance_cents` across that borrower's loans whose
    servicing standing is `CURRENT`, `DELINQUENT`, `DEFAULT` or `RECOVERY` — loans that
    have reached `PAID_OFF` or `CHARGED_OFF` are excluded from the total entirely."

    Design: Corner/validations/payoff_amount_must_match_the_computed_payoff_to_the_cent
    """
    scenario = _funded_chattel_loan_one_month_on(api)
    loan_id = scenario["loan"]["id"]
    filing_id = scenario["filing"]["id"]
    borrower_id = scenario["borrower"]["id"]

    validate_error(
        api.create_payment(
            loan_id,
            factories.payment_payload(TWELVE_CENTS_SHORT_CENTS, "PAYOFF"),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_PAYOFF_AMOUNT_MISMATCH.value,
        422,
    )

    payoff = validate_success(
        api.create_payment(
            loan_id,
            factories.payment_payload(TOTAL_OBLIGATION_CENTS, "PAYOFF"),
            fixtures.SERVICER,
        ),
        201,
    )

    assert_payment_transaction(payoff)
    assert payoff["accrual_days"] == ACCRUAL_DAYS, (
        "the refused attempt accrued nothing, so the accepted one still counts 31 days"
    )
    assert payoff["accrued_interest_at_posting_cents"] == ACCRUED_INTEREST_CENTS
    assert payoff["to_interest_cents"] == ACCRUED_INTEREST_CENTS
    assert payoff["to_principal_cents"] == PRINCIPAL_CENTS
    assert_allocation_sums_to_amount(payoff)

    loan = fixtures.read_loan(api, loan_id)
    assert_obligation_buckets_zeroed(loan)
    assert loan["servicing_state"] == "PAID_OFF"
    assert loan["perfection_state"] == "RELEASED"

    filing = fixtures.read_filing(api, filing_id)
    assert filing["status"] == "RELEASED"
    assert_instant_equals(filing["released_at"], ACCRUAL_CLOCK, "LienFiling.released_at")

    borrower = fixtures.read_borrower(api, borrower_id)
    assert borrower["total_outstanding_principal_cents"] == 0, (
        "a paid-off loan leaves the exposure input set entirely"
    )


def test_neither_a_reversed_row_nor_the_reversal_itself_can_be_reversed_again(api):
    """PRD §3.7: "Mistakes are corrected by compensation, never by editing history. A
    `Servicer` reverses a posted payment with an optional `reversal_reason`, and the
    platform writes a new row whose `payment_kind` is `REVERSAL`, whose
    `reverses_payment_id` points at the original, whose `amount_cents` is negative, and
    whose five allocation fields are the exact negatives of the original row's five.
    Applying those negatives restores every loan obligation bucket to its pre-payment
    amount, and it does so *without* re-accruing interest — the reversal undoes an
    allocation, it does not rewind the clock. The original row's `reversed` flag is set
    to true, and the loan's `version` increments. A row that has already been reversed,
    or a row that is itself a `REVERSAL`, cannot be reversed again, and the attempt is
    refused with `ERR_PAYMENT_ALREADY_REVERSED` (HTTP 409). Reversed rows are excluded
    from any later allocation arithmetic. Payment rows can be listed and filtered by
    `loan_id`, by `reverses_payment_id` and by `payment_kind`, always in ascending
    creation order, and read individually with their five allocation buckets."
    PRD §3.7: "The accrued amount is the loan's `principal_balance_cents` multiplied by
    its `apr_bps` divided by ten thousand, multiplied by `accrual_days` and divided by
    365 — an actual-over-365 day count — with the whole product evaluated exactly and
    rounded half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the logical
    clock."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."

    Design: Corner/validations/a_reversed_payment_and_a_reversal_row_cannot_be_reversed_again
    """
    scenario = _funded_chattel_loan_one_month_on(api)
    loan_id = scenario["loan"]["id"]

    payment = fixtures.post_payment(api, loan_id, ABSORBED_PAYMENT_CENTS, "PARTIAL")
    assert payment["to_interest_cents"] == ACCRUED_INTEREST_CENTS
    assert payment["to_principal_cents"] == TO_PRINCIPAL_CENTS

    reversal = fixtures.reverse_payment(api, payment["id"])
    assert_payment_transaction(reversal)
    assert_reversal_negates(payment, reversal)
    assert reversal["reversed"] is False, "the compensating row was never itself reversed"

    validate_error(
        api.reverse_payment(
            payment["id"], fixtures.SERVICER, {"reversal_reason": "DUPLICATE_ENTRY"}
        ),
        ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED.value,
        409,
    )
    validate_error(
        api.reverse_payment(
            reversal["id"], fixtures.SERVICER, {"reversal_reason": "DUPLICATE_ENTRY"}
        ),
        ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED.value,
        409,
    )

    assert fixtures.read_payment(api, payment["id"])["reversed"] is True

    loan = fixtures.read_loan(api, loan_id)
    assert loan["interest_accrued_unpaid_cents"] == ACCRUED_INTEREST_CENTS, (
        "the buckets are back where the allocation found them, with no re-accrual"
    )
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS

    rows, meta = validate_paginated(
        api.list_payments(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 2, "two refusals wrote no third row"
    assert [row["id"] for row in rows] == [payment["id"], reversal["id"]]

    linked, linked_meta = validate_paginated(
        api.list_payments(fixtures.SERVICER, {"reverses_payment_id": payment["id"]})
    )
    assert linked_meta["total_count"] == 1
    assert linked[0]["id"] == reversal["id"]


def test_thirty_delinquent_days_is_delinquent_but_not_yet_default_eligible(api):
    """PRD §3.9: "A `RecoveryManager` declares default on a loan whose servicing
    standing is `DELINQUENT`, and the declaration takes no request body. The gate is
    `delinquent_days` against a classification-specific threshold: 60 days for a loan
    classified `PERSONAL_PROPERTY`, and 90 days for one classified `REAL_PROPERTY` —
    real property enjoys the longer runway that mortgage practice affords it. That
    threshold is then pulled forward in one circumstance: when the loan's
    `placement_type` is `COMMUNITY` and the operator has reported
    `lot_rent_months_delinquent` of 2 or more, the threshold is reduced by 30 days, but
    never below the 30-day delinquency threshold itself. A borrower two months behind on
    lot rent is about to be evicted, and the lender's collateral is about to be stranded
    on someone else's land. If `delinquent_days` has not reached the threshold that
    survives that adjustment, the declaration is refused with `ERR_DEFAULT_NOT_ELIGIBLE`
    (HTTP 409)."
    PRD §3.9: "A successful declaration is a five-way cascade. The loan's servicing
    standing moves from `DELINQUENT` to `DEFAULT`. A recovery case is created — the
    client never supplies the case's `loan_id`, which is written by the cascade itself —
    opening at `status` `OPENED` with `path` derived from the loan's
    `collateral_classification`: `REPOSSESSION` for `PERSONAL_PROPERTY` and
    `FORECLOSURE` for `REAL_PROPERTY`. The case's `recovery_expense_cents` is seeded
    with the path's expense constant, 185,000 cents for a repossession and 425,000 cents
    for a foreclosure — the foreclosure arm costing well over twice as much because it
    runs through a court. The collateral unit has `recovery_hold` set to true and
    `title_status` set to `TITLE_ENCUMBERED`. And the borrower's
    `units_under_recovery_hold_count` rises by one, which by the rule in §3.1 sets that
    borrower's `status` to `SUSPENDED` and shuts off any new origination against them."
    PRD §3.7: "The assessment accrues interest up to the logical clock, refreshes
    `delinquent_days` as the whole calendar days from `next_due_date` up to the logical
    clock floored at zero, lapses an `ACTIVE` policy whose `expiry_date` the clock has
    reached or passed, and — when `delinquent_days` has reached 30 or more — moves the
    loan from `CURRENT` to `DELINQUENT` and adds a flat late fee of 3,500 cents to
    `fees_outstanding_cents`. That late fee is charged once per crossing of the
    threshold, not once per assessment: repeated assessments on an already-delinquent
    loan accrue interest but do not stack further flat fees."
    PRD §3.7: "The accrued amount is the loan's `principal_balance_cents` multiplied by
    its `apr_bps` divided by ten thousand, multiplied by `accrual_days` and divided by
    365 — an actual-over-365 day count — with the whole product evaluated exactly and
    rounded half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the logical
    clock."

    Design: Corner/validations/default_declaration_before_sixty_delinquent_days_is_refused
    """
    scenario = _funded_chattel_loan(api)
    loan_id = scenario["loan"]["id"]

    fixtures.set_clock(api, FIRST_ASSESSMENT_CLOCK)
    loan = fixtures.run_servicing_assessment(api, loan_id)
    assert loan["servicing_state"] == "DELINQUENT"
    assert loan["delinquent_days"] == DELINQUENT_DAYS_AT_THIRTY
    assert loan["interest_accrued_unpaid_cents"] == INTEREST_AT_SIXTY_ONE_DAYS_CENTS, (
        "61 days have run from funding even though only 30 are delinquent"
    )
    assert loan["fees_outstanding_cents"] == LATE_FEE_CENTS

    validate_error(
        api.declare_default(loan_id, fixtures.RECOVERY),
        ApiErrorId.ERR_DEFAULT_NOT_ELIGIBLE.value,
        409,
    )

    fixtures.set_clock(api, SECOND_ASSESSMENT_CLOCK)
    loan = fixtures.run_servicing_assessment(api, loan_id)
    assert loan["delinquent_days"] == DELINQUENT_DAYS_AT_SIXTY_ONE
    assert loan["interest_accrued_unpaid_cents"] == INTEREST_AT_NINETY_TWO_DAYS_CENTS
    assert loan["fees_outstanding_cents"] == LATE_FEE_CENTS, (
        "the flat fee is charged once per crossing, not once per assessment"
    )

    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)
    assert_recovery_case(case)
    assert case["loan_id"] == loan_id
    assert case["path"] == "REPOSSESSION"
    assert case["status"] == "OPENED"
    assert case["recovery_expense_cents"] == REPOSSESSION_EXPENSE_CENTS
    assert case["cure_deadline_date"] is None, "the cascade issues no notice"
    assert case["redemption_window_ends_at"] is None

    loan = fixtures.read_loan(api, loan_id)
    assert loan["servicing_state"] == "DEFAULT"
    assert loan["interest_accrued_unpaid_cents"] == INTEREST_AT_NINETY_TWO_DAYS_CENTS, (
        "declaring default is not a servicing call and accrues nothing"
    )

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["recovery_hold"] is True
    assert unit["title_status"] == "TITLE_ENCUMBERED"

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["units_under_recovery_hold_count"] == 1
    assert borrower["status"] == "SUSPENDED"


def test_the_cure_period_bars_possession_and_redemption_is_not_on_this_arm(api):
    """PRD §3.9: "Every recovery action requires the case to be in the standing that
    action expects — notice issuance requires `OPENED`, redemption requires
    `REDEMPTION_WINDOW`, possession requires `REPO_NOTICE_ISSUED` or
    `REDEMPTION_WINDOW`, refurbishment start requires `POSSESSION_OBTAINED`, listing and
    cost recording both require `REFURBISHING`, and sale finalization requires
    `REMARKETING` — and any mismatch is refused with `ERR_RECOVERY_CASE_INVALID_STATE`
    (HTTP 409)."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this order:
    guide effectiveness for a valuation; duplicate HUD label, placement-field
    consistency and lot-occupancy conflict for a unit registration; the two
    stale-version checks of §2.9, with the unit check on valuation creation preceding
    the loan check on policy creation; then the state-machine gates — unit
    classification state, recovery hold, valuation certifiability, operator-agreement
    state, filing state, recovery-path availability, recovery-case state, loan
    underwriting state, loan servicing state, and payment-reversal eligibility, in that
    sequence."
    PRD §2.7: "Only after all of those does the system evaluate the substantive credit,
    perfection, insurance and cash rules: segregation of duties, then valuation variant
    suitability, then filing-type match, filing document completeness and the filing
    attempt limit, then insurance date ordering and coverage-period overlap, then
    land-document completeness for a conversion, then the three funding insurance gates
    (existence of active coverage, wind endorsement sufficiency, dwelling coverage
    sufficiency), then force-placement eligibility, then the operator-agreement
    requirement for funding, then lender access rights for possession, then perfection
    establishment, then the LTV cap and the term floor, then borrower suspension, then
    the exposure cap, then default eligibility, then the cure-period,
    redemption-window-open and redemption-window-closed timing checks, and finally the
    two cash-integrity checks on a payment: overpayment refusal and payoff-amount
    exactness."
    PRD §3.9: "Redemption is available on the foreclosure arm only. Because a
    repossession-path case carries a cure period rather than a redemption window and can
    never reach `REDEMPTION_WINDOW` at all, an attempt to redeem such a case is refused
    with `ERR_CLASSIFICATION_PATH_MISMATCH` (HTTP 409) — and, as §2.7 notes, that answer
    comes before any complaint about the case's status."
    PRD §3.9: "The `RecoveryManager` supplies a `notice_reference`, which is the
    right-to-cure notice reference on the repossession arm and the foreclosure docket
    reference on the foreclosure arm. On a `REPOSSESSION` case, the status moves from
    `OPENED` to `REPO_NOTICE_ISSUED` and `cure_deadline_date` is set to the logical clock
    plus 10 days, the chattel right-to-cure period; `redemption_window_ends_at` remains
    null on this arm."
    PRD §3.9: "Both arms move the loan's servicing standing from `DEFAULT` to
    `RECOVERY`."
    PRD §3.9: "On the repossession arm the logical clock must have reached or passed
    `cure_deadline_date`, or the attempt is refused with `ERR_CURE_PERIOD_ACTIVE`
    (HTTP 409)."
    PRD §3.9: "Both arms further require that the lien actually be recorded — a filing
    in `RECORDED` standing on the unit with the loan's lien dimension at `PERFECTED` —
    failing which the attempt is refused with `ERR_PERFECTION_NOT_ESTABLISHED`
    (HTTP 409); a lender with no perfected security interest has no right to seize
    anything."
    PRD §3.9: "A successful possession moves the case to `POSSESSION_OBTAINED` and
    stamps `possession_date` with the logical clock."

    Design: Corner/validations/possession_before_the_cure_deadline_is_refused_and_redeem_does_not_exist_on_the_repossession_arm
    """
    scenario = _defaulted_repossession_case(api)
    case_id = scenario["case"]["id"]
    loan_id = scenario["loan"]["id"]
    assert scenario["case"]["path"] == "REPOSSESSION"
    assert scenario["case"]["status"] == "OPENED"
    assert fixtures.read_filing(api, scenario["filing"]["id"])["status"] == "RECORDED"
    assert scenario["loan"]["perfection_state"] == "PERFECTED"

    validate_error(
        api.begin_refurbishment(
            case_id,
            {"recovery_valuation_id": scenario["valuation"]["id"]},
            fixtures.RECOVERY,
        ),
        ApiErrorId.ERR_RECOVERY_CASE_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.redeem_case(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_CLASSIFICATION_PATH_MISMATCH.value,
        409,
    )

    case = fixtures.issue_notice(api, case_id, NOTICE_REFERENCE)
    assert case["status"] == "REPO_NOTICE_ISSUED"
    assert case["notice_reference"] == NOTICE_REFERENCE
    assert_instant_equals(case["cure_deadline_date"], CURE_DEADLINE, "RecoveryCase.cure_deadline_date")
    assert case["redemption_window_ends_at"] is None, "this arm has no window"
    assert fixtures.read_loan(api, loan_id)["servicing_state"] == "RECOVERY"

    validate_error(
        api.obtain_possession(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_CURE_PERIOD_ACTIVE.value,
        409,
    )
    assert fixtures.read_case(api, case_id)["possession_date"] is None

    fixtures.set_clock(api, CURE_DEADLINE)
    seized = validate_success(api.obtain_possession(case_id, fixtures.RECOVERY), 200)
    assert seized["status"] == "POSSESSION_OBTAINED", (
        "the bar is clock at or past the deadline, so the deadline instant is allowed"
    )
    assert_instant_equals(seized["possession_date"], CURE_DEADLINE, "RecoveryCase.possession_date")

    validate_error(
        api.redeem_case(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_CLASSIFICATION_PATH_MISMATCH.value,
        409,
    )


def test_a_terminated_agreement_bars_possession_and_a_held_unit_bars_land_work(api):
    """PRD §3.1: "From `EXECUTED`, the `action` value `TERMINATE` — again a
    `PlatformAdmin` action — moves the community to `TERMINATED`, sets
    `lender_access_rights` back to false, and from that moment blocks the funding of any
    further loan on a unit in that community."
    PRD §3.9: "On the repossession arm the logical clock must have reached or passed
    `cure_deadline_date`, or the attempt is refused with `ERR_CURE_PERIOD_ACTIVE`
    (HTTP 409)."
    PRD §3.9: "And when the unit sits on a community lot, that community's
    `lender_access_rights` must be true, or the attempt is refused with
    `ERR_LENDER_ACCESS_NOT_GRANTED` (HTTP 409): without an executed operator agreement
    granting on-site access, the lender cannot lawfully drive onto the operator's land."
    PRD §3.9: "A successful possession moves the case to `POSSESSION_OBTAINED` and
    stamps `possession_date` with the logical clock."
    PRD §3.2: "The `document_type` value `DEED` sets `deed_recorded` to true; the value
    `AFFIXATION_AFFIDAVIT` sets `affixation_affidavit_recorded` to true. Recording a
    document increments the unit's `version`. Land documents are only meaningful on a
    private-land placement. A unit that is under a recovery hold, or that secures any
    loan whose servicing standing is `RECOVERY` or `CHARGED_OFF`, is off limits to
    land-document recording: the request is refused with `ERR_RECOVERY_HOLD_ACTIVE`
    (HTTP 409). The same guard applies to classification conversion."
    PRD §3.8: "Because the cycle rewrites the collateral character of every loan on the
    unit, it is available only while the unit is clean: a unit whose `recovery_hold` is
    set, or that secures any loan whose servicing standing is `RECOVERY` or
    `CHARGED_OFF`, is refused with `ERR_RECOVERY_HOLD_ACTIVE` (HTTP 409)."
    PRD §3.8: "It is nonetheless gated on real paperwork: the unit's `placement_type`
    must be `PRIVATE_LAND`, and both `deed_recorded` and `affixation_affidavit_recorded`
    must already be true. A unit on a community lot, or one missing either land
    document, is refused with `ERR_LAND_DOCUMENTS_INCOMPLETE` (HTTP 409)."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this order:
    guide effectiveness for a valuation; duplicate HUD label, placement-field
    consistency and lot-occupancy conflict for a unit registration; the two
    stale-version checks of §2.9, with the unit check on valuation creation preceding
    the loan check on policy creation; then the state-machine gates — unit
    classification state, recovery hold, valuation certifiability, operator-agreement
    state, filing state, recovery-path availability, recovery-case state, loan
    underwriting state, loan servicing state, and payment-reversal eligibility, in that
    sequence."
    PRD §2.7: "Only after all of those does the system evaluate the substantive credit,
    perfection, insurance and cash rules: segregation of duties, then valuation variant
    suitability, then filing-type match, filing document completeness and the filing
    attempt limit, then insurance date ordering and coverage-period overlap, then
    land-document completeness for a conversion, then the three funding insurance gates
    (existence of active coverage, wind endorsement sufficiency, dwelling coverage
    sufficiency), then force-placement eligibility, then the operator-agreement
    requirement for funding, then lender access rights for possession, then perfection
    establishment, then the LTV cap and the term floor, then borrower suspension, then
    the exposure cap, then default eligibility, then the cure-period,
    redemption-window-open and redemption-window-closed timing checks, and finally the
    two cash-integrity checks on a payment: overpayment refusal and payoff-amount
    exactness."

    Design: Corner/validations/possession_needs_community_access_rights_and_a_held_unit_refuses_land_work
    """
    scenario = _defaulted_repossession_case(api)
    case_id = scenario["case"]["id"]
    unit_id = scenario["unit"]["id"]

    case = fixtures.issue_notice(api, case_id, NOTICE_REFERENCE)
    assert_instant_equals(case["cure_deadline_date"], CURE_DEADLINE, "RecoveryCase.cure_deadline_date")
    fixtures.set_clock(api, CURE_DEADLINE)

    community = fixtures.terminate_agreement(api, scenario["community"]["id"])
    assert community["operator_agreement_status"] == "TERMINATED"
    assert community["lender_access_rights"] is False

    validate_error(
        api.obtain_possession(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_LENDER_ACCESS_NOT_GRANTED.value,
        409,
    )
    held = fixtures.read_case(api, case_id)
    assert held["status"] == "REPO_NOTICE_ISSUED", (
        "the cure period has expired, so access rights are the first failing rule"
    )
    assert held["possession_date"] is None

    validate_error(
        api.record_land_document(unit_id, "DEED", fixtures.CLOSER),
        ApiErrorId.ERR_RECOVERY_HOLD_ACTIVE.value,
        409,
    )
    assert fixtures.read_unit(api, unit_id)["deed_recorded"] is False

    validate_error(
        api.convert_classification(unit_id, "INITIATE", fixtures.CLOSER),
        ApiErrorId.ERR_RECOVERY_HOLD_ACTIVE.value,
        409,
    )

    unit = fixtures.read_unit(api, unit_id)
    assert unit["recovery_hold"] is True
    assert unit["classification"] == "PERSONAL_PROPERTY", (
        "the hold check pre-empts the land-document check that this lot would also fail"
    )


def test_the_redemption_window_shuts_at_the_instant_possession_opens(api):
    """PRD §3.8: "The `COMPLETE` action moves the unit from `CONVERSION_PENDING` to
    `REAL_PROPERTY` and fans out into the widest cascade in the system. It requires that
    no filing on this unit still be in `SUBMITTED` standing, because an instrument in
    flight at the recording office cannot be reasoned about. Completion then does four
    things. The unit's `title_status` moves to `TITLE_SURRENDERED`, since the certificate
    of title is handed back to the state. Every filing on the unit that is a `RECORDED`
    `TITLE_LIEN` moves to `RELEASED` with `released_at` stamped, because a title lien has
    nothing left to attach to. Every non-terminal loan on the unit has its
    `collateral_classification` rewritten to `REAL_PROPERTY`, and any such loan whose
    lien dimension stood at `PERFECTED` is moved to `RE_PERFECTION_REQUIRED` — the loan
    is now unsecured in substance until a deed of trust is recorded. And every `ACTIVE`
    policy on those loans is re-scored against the real-property requirement of 10000
    basis points of insurable value, which is a materially higher bar than the 8000 basis
    points that applied a moment earlier, so a policy that was `COMPLIANT` can land on
    `DEFICIENT_COVERAGE` and flip the loan's `insurance_compliance` to `NON_COMPLIANT`."
    PRD §3.8: "A loan sitting at `RE_PERFECTION_REQUIRED` is re-perfected by tendering a
    fresh `LAND_HOME_DEED_OF_TRUST` filing — a second filing on the same loan,
    coexisting with the released title lien — which moves the lien dimension from
    `RE_PERFECTION_REQUIRED` to `FILING_SUBMITTED` and then, on a recorded outcome, to
    `PERFECTED`."
    PRD §3.6: "The insurable value is the `certified_value_cents` of the loan's
    certified origination valuation. The exposure is the loan's
    `principal_balance_cents` once the loan has reached `FUNDED`, and its
    `principal_cents` before that. The `required_coverage_cents` figure is then the
    greater of that exposure and the insurable value multiplied by the
    required-coverage ratio for the loan's `collateral_classification` divided by ten
    thousand, rounded half up — where the ratio is 8000 basis points, four fifths of
    insurable value, for `PERSONAL_PROPERTY` and 10000 basis points, the whole
    insurable value, for `REAL_PROPERTY`."
    PRD §3.6: "A policy's `compliance_state` is therefore `DEFICIENT_WIND` when wind
    coverage is required and the policy carries no `wind_endorsement`; otherwise it is
    `DEFICIENT_COVERAGE` when the policy's `dwelling_coverage_cents` is below
    `required_coverage_cents`; otherwise it is `COMPLIANT`."
    PRD §3.7: "The accrued amount is the loan's `principal_balance_cents` multiplied by
    its `apr_bps` divided by ten thousand, multiplied by `accrual_days` and divided by
    365 — an actual-over-365 day count — with the whole product evaluated exactly and
    rounded half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the logical
    clock."
    PRD §3.7: "The assessment accrues interest up to the logical clock, refreshes
    `delinquent_days` as the whole calendar days from `next_due_date` up to the logical
    clock floored at zero, lapses an `ACTIVE` policy whose `expiry_date` the clock has
    reached or passed, and — when `delinquent_days` has reached 30 or more — moves the
    loan from `CURRENT` to `DELINQUENT` and adds a flat late fee of 3,500 cents to
    `fees_outstanding_cents`."
    PRD §3.9: "The gate is `delinquent_days` against a classification-specific
    threshold: 60 days for a loan classified `PERSONAL_PROPERTY`, and 90 days for one
    classified `REAL_PROPERTY` — real property enjoys the longer runway that mortgage
    practice affords it."
    PRD §3.9: "A recovery case is created — the client never supplies the case's
    `loan_id`, which is written by the cascade itself — opening at `status` `OPENED` with
    `path` derived from the loan's `collateral_classification`: `REPOSSESSION` for
    `PERSONAL_PROPERTY` and `FORECLOSURE` for `REAL_PROPERTY`. The case's
    `recovery_expense_cents` is seeded with the path's expense constant, 185,000 cents
    for a repossession and 425,000 cents for a foreclosure — the foreclosure arm costing
    well over twice as much because it runs through a court."
    PRD §3.9: "On a `FORECLOSURE` case, the status moves from `OPENED` to
    `REDEMPTION_WINDOW` and `redemption_window_ends_at` is set to the logical clock plus
    45 days, the statutory redemption period — a month and a half rather than a week and
    a half; `cure_deadline_date` remains null on this arm."
    PRD §3.9: "On a foreclosure case in `REDEMPTION_WINDOW`, redemption is only open
    while the logical clock is strictly before `redemption_window_ends_at`; at or after
    that instant the window has shut and the attempt is refused with
    `ERR_REDEMPTION_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.9: "On the foreclosure arm the logical clock must have reached or passed
    `redemption_window_ends_at`, or the attempt is refused with
    `ERR_REDEMPTION_WINDOW_OPEN` (HTTP 409)."
    PRD §3.9: "A successful possession moves the case to `POSSESSION_OBTAINED` and
    stamps `possession_date` with the logical clock."

    Design: Corner/validations/redemption_window_is_closed_at_its_end_instant_and_open_before_it
    """
    scenario = fixtures.setup_funded_private_land_loan(
        api,
        clock=CLOCK,
        principal_cents=LAND_PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        first_due_date=FIRST_DUE_DATE,
    )
    loan_id = scenario["loan"]["id"]
    unit_id = scenario["unit"]["id"]
    insurable_value_cents = scenario["valuation"]["certified_value_cents"]

    unit = fixtures.complete_conversion(api, unit_id)
    assert unit["classification"] == "REAL_PROPERTY"
    assert unit["title_status"] == "TITLE_SURRENDERED"
    assert fixtures.read_filing(api, scenario["filing"]["id"])["status"] == "RELEASED"

    deed = fixtures.perfect_with_deed_of_trust(api, loan_id)
    assert deed["filing_type"] == "LAND_HOME_DEED_OF_TRUST"
    assert deed["status"] == "RECORDED"

    policy = fixtures.read_policy(api, scenario["policy"]["id"])
    assert policy["required_coverage_cents"] == insurable_value_cents, (
        "the real-property ratio is the whole insurable value, not four fifths of it"
    )
    assert policy["compliance_state"] == "COMPLIANT"

    loan = fixtures.read_loan(api, loan_id)
    assert loan["collateral_classification"] == "REAL_PROPERTY"
    assert loan["perfection_state"] == "PERFECTED"

    fixtures.set_clock(api, FORECLOSURE_ASSESSMENT_CLOCK)
    loan = fixtures.run_servicing_assessment(api, loan_id)
    assert loan["servicing_state"] == "DELINQUENT"
    assert loan["delinquent_days"] == DELINQUENT_DAYS_AT_NINETY_ONE
    assert loan["interest_accrued_unpaid_cents"] == LAND_INTEREST_CENTS
    assert loan["fees_outstanding_cents"] == LATE_FEE_CENTS

    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)
    assert_recovery_case(case)
    assert case["path"] == "FORECLOSURE", (
        "the classification picks the arm, and this unit is now real property"
    )
    assert case["recovery_expense_cents"] == FORECLOSURE_EXPENSE_CENTS

    case = fixtures.issue_notice(api, case["id"], DOCKET_REFERENCE)
    assert case["status"] == "REDEMPTION_WINDOW"
    assert case["notice_reference"] == DOCKET_REFERENCE
    assert_instant_equals(case["redemption_window_ends_at"], REDEMPTION_WINDOW_END, "RecoveryCase.redemption_window_ends_at")
    assert case["cure_deadline_date"] is None, "this arm has no cure period"

    validate_error(
        api.obtain_possession(case["id"], fixtures.RECOVERY),
        ApiErrorId.ERR_REDEMPTION_WINDOW_OPEN.value,
        409,
    )

    fixtures.set_clock(api, REDEMPTION_WINDOW_END)
    validate_error(
        api.redeem_case(case["id"], fixtures.RECOVERY),
        ApiErrorId.ERR_REDEMPTION_WINDOW_CLOSED.value,
        409,
    )

    seized = validate_success(api.obtain_possession(case["id"], fixtures.RECOVERY), 200)
    assert seized["status"] == "POSSESSION_OBTAINED", (
        "redemption is strictly before the instant and possession is at or after it, so "
        "the pair flips exactly there"
    )
    assert_instant_equals(seized["possession_date"], REDEMPTION_WINDOW_END, "RecoveryCase.possession_date")
