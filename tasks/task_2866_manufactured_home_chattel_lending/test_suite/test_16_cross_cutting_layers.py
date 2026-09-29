"""The two optimistic-concurrency guards, and the outside signal that moves a gate.

Both guarded writes are guarded against the same mistake — a client acting on a
parent it read too long ago — and in both cases the version it held was
invalidated by its own earlier call. The third case is the one input the lender
does not control: the park operator's report of lot-rent arrears, which pulls the
default threshold forward once it reaches two months.
"""

from test_helpers import (
    ApiErrorId,
    assert_insurance_policy,
    assert_recovery_case,
    assert_valuation,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}
PINE_RIDGE = {
    "name": "Pine Ridge MHC",
    "state_code": "GA",
    "lot_count": 180,
    "monthly_lot_rent_cents": 52000,
    "sales_commission_bps": 150,
}
PIERED = {"installation_type": "PIER_AND_ANCHOR", "wind_zone": 2}

STALE_UNIT_VERSION = 1
UNIT_VERSION_AFTER_FIRST_VALUATION = 2
UNIT_VERSION_AFTER_RETRY = 3

# ─── The policy tendered against a loan the client last read at creation ───
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240
DWELLING_COVERAGE_CENTS = 4700000
PERSONAL_PROPERTY_COVERAGE_BPS = 8000
BPS_WHOLE = 10000
POLICY_EFFECTIVE_DATE = "2026-08-01T00:00:00Z"
POLICY_EXPIRY_DATE = "2027-08-01T00:00:00Z"
CARRIER_NAME = "Foremost"
WIND_DEDUCTIBLE_CENTS = 100000

# ─── Delinquency at thirty days, then the operator's report ───
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ASSESSMENT_CLOCK = "2026-10-01T00:00:00Z"
DELINQUENT_DAYS_AT_THIRTY = 30
# apr_bps 1275 = 875 base + 225 community + 175 personal property, a 705 score taking
# neither credit nor charge and an ltv of 7964 taking no leverage spread; 61 days from
# funding on 2026-08-01 to the assessment on 2026-10-01, on a balance of 4,600,000.
INTEREST_AT_SIXTY_ONE_DAYS_CENTS = 98018
LATE_FEE_CENTS = 3500
ONE_MONTH_BEHIND = 1
TWO_MONTHS_BEHIND = 2
REPOSSESSION_EXPENSE_CENTS = 185000


def _guide_and_piered_parcel_unit(api):
    """One in-force guide and one piered MULTI_WIDE on land its obligor owns."""
    return fixtures.setup_private_land_collateral(
        api,
        borrower_overrides=DANA,
        unit_overrides=PIERED,
        record_documents=False,
    )


def _perfected_community_loan(api):
    """An approved, title-lien-perfected chattel loan. ``loan`` is deliberately the
    application-time view the client kept, not a fresh read."""
    scenario = fixtures.setup_community_collateral(
        api,
        agreement="EXECUTED",
        borrower_overrides=DANA,
        community_overrides=PINE_RIDGE,
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"]
    )
    opened = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        scenario["valuation"]["id"],
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    fixtures.price_loan(api, opened["id"])
    fixtures.approve_loan(api, opened["id"])
    scenario["filing"] = fixtures.perfect_with_title_lien(api, opened["id"])
    scenario["loan"] = opened
    return scenario


def _delinquent_community_loan(api):
    """The canonical chattel loan, funded on 2026-08-01 and assessed a month after
    its first payment fell due."""
    return fixtures.setup_delinquent_community_loan(
        api,
        assessment_clock=ASSESSMENT_CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
        borrower_overrides=DANA,
        community_overrides=PINE_RIDGE,
    )


def test_a_writer_must_re_read_the_unit_before_superseding_its_own_valuation(api):
    """PRD §2.9: "Exactly two write operations in this system carry an
    optimistic-concurrency guard, and both guard against a client acting on a parent it
    read too long ago. Each of the two requires a mandatory field — it is not optional
    and it has no default — carrying the client's last observed `version` of the parent
    resource."
    PRD §2.9: "Creating a `Valuation` requires `expected_unit_version`, carrying the
    client's last observed `version` of the `ManufacturedUnit` being valued. If it does
    not equal the unit's current `version`, the create is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD §3.3: "It moves any earlier `CERTIFIED` valuation of the same unit and the
    same variant to `SUPERSEDED` — which is precisely why the stale-version guard of
    §2.9 exists on this write, and why `ERR_STALE_UNIT_VERSION` is returned when
    `expected_unit_version` does not match. It increments the unit's own `version`, so
    a client that creates two valuations back to back must re-read the unit between
    them. And it leaves the new valuation in `status` `DRAFT`, with
    `certified_by_user_id` and `certified_at` both null."
    PRD §3.3: "A draft valuation is a working figure; only a certified one may be
    cited by a loan or a recovery case. Certification is performed by a
    `CreditAnalyst` or a `RecoveryManager` and freezes the row: `status` moves to
    `CERTIFIED`, `certified_by_user_id` is stamped with the acting `X-User-ID`, and
    `certified_at` is stamped with the logical clock."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that starts
    at 1 and increments by exactly one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_blocks_a_superseding_valuation
    """
    scenario = _guide_and_piered_parcel_unit(api)
    unit_id, guide_id = scenario["unit"]["id"], scenario["guide"]["id"]
    assert scenario["unit"]["version"] == STALE_UNIT_VERSION

    first = fixtures.create_certified_valuation(
        api, unit_id, guide_id, expected_unit_version=STALE_UNIT_VERSION
    )
    assert_valuation(first)
    assert first["status"] == "CERTIFIED"
    frozen_value_cents = first["certified_value_cents"]

    validate_error(
        api.create_valuation(
            factories.valuation_payload(unit_id, guide_id, STALE_UNIT_VERSION),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_STALE_UNIT_VERSION.value,
        412,
    )

    # One bump from the first create and none from the refusal: the client's own
    # earlier call is what made the version it still holds stale.
    assert (
        fixtures.read_unit(api, unit_id)["version"]
        == UNIT_VERSION_AFTER_FIRST_VALUATION
    )

    second = validate_success(
        api.create_valuation(
            factories.valuation_payload(
                unit_id, guide_id, UNIT_VERSION_AFTER_FIRST_VALUATION
            ),
            fixtures.ANALYST,
        ),
        201,
    )
    assert second["status"] == "DRAFT"
    assert fixtures.read_unit(api, unit_id)["version"] == UNIT_VERSION_AFTER_RETRY

    retired = fixtures.read_valuation(api, first["id"])
    assert retired["status"] == "SUPERSEDED", (
        "the supersede happened on the attempt that carried the current version"
    )
    assert retired["certified_value_cents"] == frozen_value_cents, (
        "certification froze the row; being superseded does not re-compute it"
    )

def test_a_stale_loan_version_outranks_even_an_inverted_coverage_interval(api):
    """PRD §2.9: "Exactly two write operations in this system carry an
    optimistic-concurrency guard, and both guard against a client acting on a parent it
    read too long ago. Each of the two requires a mandatory field — it is not optional
    and it has no default — carrying the client's last observed `version` of the parent
    resource."
    PRD §2.9: "Creating an `InsurancePolicy` requires `expected_loan_version`, carrying
    the client's last observed `version` of the `Loan` the policy covers. If it does not
    equal the loan's current `version`, the create is rejected with
    `ERR_STALE_LOAN_VERSION` (HTTP 412)."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this order:
    guide effectiveness for a valuation; duplicate HUD label, placement-field consistency
    and lot-occupancy conflict for a unit registration; the two stale-version checks of
    §2.9, with the unit check on valuation creation preceding the loan check on policy
    creation; then the state-machine gates — unit classification state, recovery hold,
    valuation certifiability, operator-agreement state, filing state, recovery-path
    availability, recovery-case state, loan underwriting state, loan servicing state,
    and payment-reversal eligibility, in that sequence."
    PRD §3.6: "The `expiry_date` must be strictly after the `effective_date`, and a
    non-positive interval is rejected with `ERR_INVALID_REQUEST` (HTTP 422) — a rule that
    governs force-placed coverage just as it governs borrower-provided coverage. Policy
    creation also requires `expected_loan_version` under §2.9. The platform computes
    `coverage_days` as the whole calendar days from `effective_date` up to `expiry_date`."
    PRD §3.6: "The insurable value is the `certified_value_cents` of the loan's certified
    origination valuation. The exposure is the loan's `principal_balance_cents` once the
    loan has reached `FUNDED`, and its `principal_cents` before that. The
    `required_coverage_cents` figure is then the greater of that exposure and the
    insurable value multiplied by the required-coverage ratio for the loan's
    `collateral_classification` divided by ten thousand, rounded half up — where the ratio
    is 8000 basis points, four fifths of insurable value, for `PERSONAL_PROPERTY` and
    10000 basis points, the whole insurable value, for `REAL_PROPERTY`."
    PRD §3.6: "A policy's `compliance_state` is therefore `DEFICIENT_WIND` when wind
    coverage is required and the policy carries no `wind_endorsement`; otherwise it is
    `DEFICIENT_COVERAGE` when the policy's `dwelling_coverage_cents` is below
    `required_coverage_cents`; otherwise it is `COMPLIANT`."
    PRD §3.6: "A borrower-provided policy is recorded with `source` `BORROWER_PROVIDED`,
    `status` `ACTIVE` and `premium_cents` 0 — the borrower pays their own carrier, so the
    lender advances nothing. Creating it moves any earlier `ACTIVE` borrower-provided
    policy on the same loan to `SUPERSEDED` and recomputes the loan's
    `insurance_compliance` from whichever policy survives as `ACTIVE`, which is either
    `COMPLIANT` or `NON_COMPLIANT`. It increments the loan's `version`."
    PRD §2.8: "Wherever a formula in §3 requires a division, the whole product is
    evaluated in exact arithmetic and then the single resulting quotient is rounded half
    up to the nearest whole cent."

    Design: Corner/cross_cutting_complexity_layers/stale_loan_version_blocks_a_superseding_insurance_policy
    """
    scenario = _perfected_community_loan(api)
    loan_id = scenario["loan"]["id"]
    stale_loan_version = scenario["loan"]["version"]

    # The interval is inverted on purpose. Date ordering is a substantive insurance rule
    # and sits far below the stale-version check on the §2.7 ladder, so the 412 must win.
    refused = api.create_insurance_policy(
        factories.insurance_policy_payload(
            loan_id,
            stale_loan_version,
            dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
            carrier_name=CARRIER_NAME,
            wind_deductible_cents=WIND_DEDUCTIBLE_CENTS,
            effective_date=POLICY_EXPIRY_DATE,
            expiry_date=POLICY_EFFECTIVE_DATE,
        ),
        fixtures.SERVICER,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_LOAN_VERSION.value, 412)

    fresh = fixtures.read_loan(api, loan_id)
    assert fresh["version"] > stale_loan_version, (
        "pricing, approval and perfection each moved the loan past the version the "
        "client kept from its application"
    )
    assert fresh["insurance_compliance"] == "UNKNOWN", (
        "the refused tender proved nothing about coverage"
    )

    policy = validate_success(
        api.create_insurance_policy(
            factories.insurance_policy_payload(
                loan_id,
                fresh["version"],
                dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
                carrier_name=CARRIER_NAME,
                wind_deductible_cents=WIND_DEDUCTIBLE_CENTS,
                effective_date=POLICY_EFFECTIVE_DATE,
                expiry_date=POLICY_EXPIRY_DATE,
            ),
            fixtures.SERVICER,
        ),
        201,
    )
    assert_insurance_policy(policy)
    assert policy["source"] == "BORROWER_PROVIDED"
    assert policy["status"] == "ACTIVE"
    assert policy["premium_cents"] == 0
    assert policy["carrier_name"] == CARRIER_NAME
    assert policy["wind_deductible_cents"] == WIND_DEDUCTIBLE_CENTS

    insurable_value_cents = scenario["valuation"]["certified_value_cents"]
    ratio_leg_cents = (
        insurable_value_cents * PERSONAL_PROPERTY_COVERAGE_BPS + BPS_WHOLE // 2
    ) // BPS_WHOLE
    assert policy["required_coverage_cents"] == max(ratio_leg_cents, PRINCIPAL_CENTS), (
        "the matrix reads the collateral: four fifths of certified value against the "
        "unfunded loan's principal_cents, whichever is greater"
    )
    assert policy["compliance_state"] == "COMPLIANT", (
        "wind is graded first and the endorsement is attached, and the dwelling limit "
        "clears the requirement"
    )

    covered = fixtures.read_loan(api, loan_id)
    assert covered["insurance_compliance"] == "COMPLIANT"
    assert covered["version"] > fresh["version"]

    rows, meta = validate_paginated(
        api.list_insurance_policies(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1, "the refused tender left no row behind"
    assert rows[0]["id"] == policy["id"]

def test_two_months_of_lot_rent_arrears_pull_the_default_gate_forward(api):
    """PRD §3.7: "Interest accrues on demand rather than on a schedule, and it accrues
    exactly once per servicing call. The `accrual_days` figure is the whole calendar days
    from the loan's `last_accrual_date` up to the logical clock, over a half-open
    interval. The accrued amount is the loan's `principal_balance_cents` multiplied by its
    `apr_bps` divided by ten thousand, multiplied by `accrual_days` and divided by 365 —
    an actual-over-365 day count — with the whole product evaluated exactly and rounded
    half up to a whole cent one time."
    PRD §3.5: "It stamps `funded_at` and `last_accrual_date` with the logical clock and
    sets `next_due_date` to the supplied `first_due_date`."
    PRD §3.7: "Time passing is itself an event, and a `Servicer` makes the platform notice
    it by running a periodic servicing assessment, which takes no request body. The
    assessment accrues interest up to the logical clock, refreshes `delinquent_days` as
    the whole calendar days from `next_due_date` up to the logical clock floored at zero,
    lapses an `ACTIVE` policy whose `expiry_date` the clock has reached or passed, and —
    when `delinquent_days` has reached 30 or more — moves the loan from `CURRENT` to
    `DELINQUENT` and adds a flat late fee of 3,500 cents to `fees_outstanding_cents`."
    PRD §3.7: "A `CommunityOperator` reports the borrower's standing on the lot by
    supplying `months_delinquent` and a `lot_rent_state` of `CURRENT`, `DELINQUENT` or
    `EVICTION_FILED`. The report writes `lot_rent_months_delinquent` from the reported
    months and `lot_rent_state` from the reported standing, so a report that returns the
    standing to `CURRENT` with zero months delinquent clears the counter back to 0. A loan
    starts life with `lot_rent_months_delinquent` at 0 and `lot_rent_state` at `CURRENT`.
    Reporting increments the loan's `version`."
    PRD §3.9: "The gate is `delinquent_days` against a classification-specific threshold:
    60 days for a loan classified `PERSONAL_PROPERTY`, and 90 days for one classified
    `REAL_PROPERTY` — real property enjoys the longer runway that mortgage practice
    affords it. That threshold is then pulled forward in one circumstance: when the loan's
    `placement_type` is `COMMUNITY` and the operator has reported
    `lot_rent_months_delinquent` of 2 or more, the threshold is reduced by 30 days, but
    never below the 30-day delinquency threshold itself. A borrower two months behind on
    lot rent is about to be evicted, and the lender's collateral is about to be stranded
    on someone else's land. If `delinquent_days` has not reached the threshold that
    survives that adjustment, the declaration is refused with `ERR_DEFAULT_NOT_ELIGIBLE`
    (HTTP 409)."
    PRD §3.9: "A successful declaration is a five-way cascade. The loan's servicing
    standing moves from `DELINQUENT` to `DEFAULT`. A recovery case is created — the client
    never supplies the case's `loan_id`, which is written by the cascade itself — opening
    at `status` `OPENED` with `path` derived from the loan's `collateral_classification`:
    `REPOSSESSION` for `PERSONAL_PROPERTY` and `FORECLOSURE` for `REAL_PROPERTY`. The
    case's `recovery_expense_cents` is seeded with the path's expense constant, 185,000
    cents for a repossession and 425,000 cents for a foreclosure — the foreclosure arm
    costing well over twice as much because it runs through a court. The collateral unit
    has `recovery_hold` set to true and `title_status` set to `TITLE_ENCUMBERED`. And the
    borrower's `units_under_recovery_hold_count` rises by one, which by the rule in §3.1
    sets that borrower's `status` to `SUSPENDED` and shuts off any new origination against
    them."
    PRD §3.1: "The relationship between the two derived fields and credit standing is
    mechanical: `status` is `SUSPENDED` whenever `units_under_recovery_hold_count` is
    greater than zero and `ACTIVE` otherwise."
    PRD §4: "Operations that bring a brand-new resource into existence return `201
    Created`: publishing a guide edition, registering a borrower, a community or a unit,
    creating a valuation, opening a loan application, tendering a lien filing, recording
    or force-placing an insurance policy, posting or reversing a payment, and declaring
    default (which creates the recovery case)."

    Design: Corner/cross_cutting_complexity_layers/lot_rent_arrears_accelerate_the_default_threshold_at_two_months
    """
    scenario = _delinquent_community_loan(api)
    loan_id = scenario["loan"]["id"]
    community_id = scenario["community"]["id"]

    assessed = scenario["loan"]
    assert assessed["servicing_state"] == "DELINQUENT"
    assert assessed["delinquent_days"] == DELINQUENT_DAYS_AT_THIRTY, (
        "one month from the first due date to the assessment clock"
    )
    assert assessed["interest_accrued_unpaid_cents"] == (
        INTEREST_AT_SIXTY_ONE_DAYS_CENTS
    ), "sixty-one days accrued in the single call the assessment made"
    assert assessed["fees_outstanding_cents"] == LATE_FEE_CENTS
    assert assessed["lot_rent_months_delinquent"] == 0, (
        "nothing has come in from the park yet"
    )
    assert assessed["lot_rent_state"] == "CURRENT"

    # Thirty delinquent days is well short of the 60-day personal-property threshold, and
    # one month of lot-rent arrears is short of the two that would accelerate it.
    one_month = fixtures.report_lot_rent(
        api, loan_id, community_id, ONE_MONTH_BEHIND, "DELINQUENT"
    )
    assert one_month["lot_rent_months_delinquent"] == ONE_MONTH_BEHIND
    assert one_month["lot_rent_state"] == "DELINQUENT"
    validate_error(
        api.declare_default(loan_id, fixtures.RECOVERY),
        ApiErrorId.ERR_DEFAULT_NOT_ELIGIBLE.value,
        409,
    )
    assert fixtures.read_loan(api, loan_id)["servicing_state"] == "DELINQUENT", (
        "a refused declaration leaves the loan in collections, not in default"
    )

    two_months = fixtures.report_lot_rent(
        api, loan_id, community_id, TWO_MONTHS_BEHIND, "EVICTION_FILED"
    )
    assert two_months["lot_rent_months_delinquent"] == TWO_MONTHS_BEHIND
    assert two_months["delinquent_days"] == DELINQUENT_DAYS_AT_THIRTY, (
        "the clock did not move, so the lender-side counter is untouched"
    )

    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)
    assert_recovery_case(case)
    assert case["loan_id"] == loan_id, "the cascade wrote the link, the client did not"
    assert case["status"] == "OPENED"
    assert case["path"] == "REPOSSESSION"
    assert case["recovery_expense_cents"] == REPOSSESSION_EXPENSE_CENTS

    defaulted = fixtures.read_loan(api, loan_id)
    assert defaulted["servicing_state"] == "DEFAULT"
    assert defaulted["delinquent_days"] == DELINQUENT_DAYS_AT_THIRTY, (
        "the threshold moved; the days behind did not"
    )
    assert defaulted["interest_accrued_unpaid_cents"] == (
        INTEREST_AT_SIXTY_ONE_DAYS_CENTS
    ), "neither the lot-rent reports nor the declaration is a servicing accrual"
    assert defaulted["fees_outstanding_cents"] == LATE_FEE_CENTS
    assert defaulted["lot_rent_state"] == "EVICTION_FILED"

    held = fixtures.read_unit(api, scenario["unit"]["id"])
    assert held["recovery_hold"] is True
    assert held["title_status"] == "TITLE_ENCUMBERED"

    obligor = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert obligor["units_under_recovery_hold_count"] == 1
    assert obligor["status"] == "SUSPENDED"
