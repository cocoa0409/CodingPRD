"""Seeded states, terminal states and the transitions that are refused outright.

A loan's three dimensions are seeded independently and advance independently; a
declined loan is finished; a certified valuation and an unproposed operator
agreement each refuse the call that would move them the wrong way; and one fund
call plus one servicing assessment each fire a whole bundle of declared side
effects at once.
"""

from test_helpers import (
    ApiErrorId,
    assert_community,
    assert_insurance_policy,
    assert_instant_equals,
    assert_loan,
    assert_manufactured_unit,
    assert_obligation_buckets_zeroed,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
LAPSE_CLOCK = "2026-09-15T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240
GRANTED_TERM_MONTHS = 240

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

# ─── The same collateral, valued with and without an operator agreement ───
UNEXECUTED_CERTIFIED_CENTS = 5239859
EXECUTED_CERTIFIED_CENTS = 5776403
UNEXECUTED_LTV_BPS = 8779
EXECUTED_LTV_BPS = 7963
EXECUTED_APR_BPS = 1275
LEVERAGE_TIER_FREE_CEILING_BPS = 8000

# ─── Closing and servicing figures ───
DWELLING_COVERAGE_CENTS = 4700000
REQUIRED_COVERAGE_CENTS = 4621122
SHORT_EXPIRY_DATE = "2026-09-01T00:00:00Z"
ACCRUED_INTEREST_CENTS = 72308
DELINQUENT_DAYS = 14
DELINQUENCY_THRESHOLD_DAYS = 30
DECLINE_REASON = "payment-to-income outside program limits"


def _certified_community_collateral(api, agreement="NONE"):
    """A guide, an obligor, a park at ``agreement`` and a certified ORIGINATION value."""
    scenario = fixtures.setup_community_collateral(
        api,
        clock=CLOCK,
        agreement=agreement,
        borrower_overrides=DANA,
        community_overrides=PINE_RIDGE,
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"], "ORIGINATION"
    )
    return scenario


def _priced_then_declined_loan(api):
    """An application priced at submission and then declined by the underwriter."""
    scenario = _certified_community_collateral(api)
    loan = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        scenario["valuation"]["id"],
        PRINCIPAL_CENTS,
        REQUESTED_TERM_MONTHS,
    )
    scenario["opened"] = loan
    scenario["priced"] = fixtures.price_loan(api, loan["id"])
    scenario["loan"] = validate_success(
        api.decline_loan(
            loan["id"],
            fixtures.make_credit_analyst_headers(fixtures.LOAN_APPROVER_USER_ID),
            {"decline_reason": DECLINE_REASON},
        )
    )
    return scenario


def _closable_loan_on_an_executed_lot(api, policy_overrides=None):
    """An APPROVED loan whose park signed, insured to 4700000 and title-lien perfected."""
    scenario = fixtures.setup_community_collateral(
        api,
        clock=CLOCK,
        agreement="EXECUTED",
        borrower_overrides=DANA,
        community_overrides=PINE_RIDGE,
    )
    scenario = fixtures.setup_approved_loan(
        api,
        scenario,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    scenario["policy"] = fixtures.record_policy(
        api,
        scenario["loan"]["id"],
        DWELLING_COVERAGE_CENTS,
        **(policy_overrides or {}),
    )
    scenario["filing"] = fixtures.perfect_with_title_lien(api, scenario["loan"]["id"])
    return scenario


def test_a_new_application_is_seeded_draft_not_servicing_and_unperfected(api):
    """PRD §3.4: "Creation takes two snapshots off the unit that then live on the
    loan. The loan's `collateral_classification` is copied from the unit's current
    classification and is either `PERSONAL_PROPERTY` or `REAL_PROPERTY`; note that a
    unit sitting in `CONVERSION_PENDING` is mid-flight and its loans hold whichever
    of the two settled values applies. The loan's `placement_type` is copied from the
    unit's placement and is `COMMUNITY` or `PRIVATE_LAND`. Both snapshots then drive
    pricing, term, the perfection instrument, the payment waterfall and the default
    path — and the first of them is re-synced later if the unit converts, as §3.9
    describes. A new loan starts with `underwriting_state` `DRAFT`, `servicing_state`
    `NOT_SERVICING` and `perfection_state` `UNPERFECTED`."
    PRD §3.4: "Submitting the application for underwriting is the pricing act: it
    advances `underwriting_state` from `DRAFT` to `UNDERWRITING` and, in doing so,
    computes and stores `ltv_bps`, `apr_bps` and `term_months`, all three of which
    are null until this succeeds."
    PRD §3.6: "A loan starts life with `insurance_compliance` at `UNKNOWN` and can
    only be funded once coverage has been proved."
    PRD §3.7: "Once a loan is funded, five obligation buckets sit on it and every
    servicing act moves one or more of them: `interest_accrued_unpaid_cents` holds
    interest that has accrued but has not yet been satisfied, `fees_outstanding_cents`
    holds unpaid late fees, `force_placed_premium_outstanding_cents` holds the
    unreimbursed lender-advanced premium, `escrow_balance_cents` holds cash held for
    taxes and insurance against the `escrow_target_cents` the servicer is collecting
    toward, and `principal_balance_cents` holds unpaid principal. Principal is set
    once at funding and thereafter moves only through payment allocation and its
    reversal."
    PRD §3.7: "A loan starts life with `lot_rent_months_delinquent` at 0 and
    `lot_rent_state` at `CURRENT`."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that
    starts at 1 and increments by exactly one on every mutation."

    Design: Corner/state_machines/new_loan_starts_draft_not_servicing_unperfected
    """
    scenario = _certified_community_collateral(api)

    loan = validate_success(
        api.create_loan(
            factories.loan_payload(
                scenario["borrower"]["id"],
                scenario["unit"]["id"],
                scenario["valuation"]["id"],
                PRINCIPAL_CENTS,
                REQUESTED_TERM_MONTHS,
            ),
            fixtures.ANALYST,
        ),
        201,
    )

    assert_loan(loan)
    assert loan["underwriting_state"] == "DRAFT"
    assert loan["servicing_state"] == "NOT_SERVICING"
    assert loan["perfection_state"] == "UNPERFECTED"
    assert loan["collateral_classification"] == "PERSONAL_PROPERTY"
    assert loan["placement_type"] == "COMMUNITY"
    assert loan["ltv_bps"] is None
    assert loan["apr_bps"] is None
    assert loan["term_months"] is None, "pricing waits for submit-underwriting"

    assert_obligation_buckets_zeroed(loan)
    assert loan["escrow_balance_cents"] == 0
    assert loan["insurance_compliance"] == "UNKNOWN"
    assert loan["lot_rent_months_delinquent"] == 0
    assert loan["lot_rent_state"] == "CURRENT"
    assert loan["delinquent_days"] == 0, "nothing has fallen due on an unfunded loan"
    assert loan["next_due_date"] is None
    assert loan["last_accrual_date"] is None
    assert loan["funded_at"] is None
    assert loan["approved_by_user_id"] is None
    assert loan["version"] == 1

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == 0, (
        "an unfunded application advances no money, so it adds no exposure"
    )


def test_declining_moves_only_the_underwriting_dimension(api):
    """PRD §3.4: "The alternative outcome is a decline, which moves the loan from
    `UNDERWRITING` to `DECLINED` with no preconditions at all and accepts an optional
    `decline_reason`. A declined loan is finished: `DECLINED` is terminal on the
    underwriting dimension and the loan's `servicing_state` stays at `NOT_SERVICING`
    forever. Declining also increments the loan's `version`."
    PRD §3.4: "Submitting the application for underwriting is the pricing act: it
    advances `underwriting_state` from `DRAFT` to `UNDERWRITING` and, in doing so,
    computes and stores `ltv_bps`, `apr_bps` and `term_months`, all three of which
    are null until this succeeds."
    PRD §3.4: "A successful submission increments the loan's `version`."
    PRD §3.4: "A successful approval stamps `approved_by_user_id` with the acting
    `X-User-ID` and increments the loan's `version`."
    PRD §3.4: "The `ltv_bps` figure is `principal_cents` multiplied by ten thousand
    and divided by the valuation's `certified_value_cents`, rounded half up to a
    whole basis point — the only rounded quantity in the whole pricing walk."
    PRD §3.3: "Otherwise the unit sits on a community lot, and the key is
    `COMMUNITY_WITH_AGREEMENT` when that community's `operator_agreement_status` is
    `EXECUTED` and `COMMUNITY_WITHOUT_AGREEMENT` in every other case — including
    `PENDING` and `TERMINATED`, neither of which grants the lender anything."

    Design: Corner/state_machines/decline_moves_underwriting_state_to_declined
    """
    scenario = _priced_then_declined_loan(api)
    priced = scenario["priced"]
    declined = scenario["loan"]

    assert scenario["community"]["operator_agreement_status"] == "NONE"
    assert scenario["valuation"]["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"
    assert scenario["valuation"]["certified_value_cents"] == UNEXECUTED_CERTIFIED_CENTS
    assert priced["underwriting_state"] == "UNDERWRITING"
    assert priced["ltv_bps"] == UNEXECUTED_LTV_BPS
    assert priced["version"] == 2, "creation then submission"

    assert_loan(declined)
    assert declined["underwriting_state"] == "DECLINED"
    assert declined["servicing_state"] == "NOT_SERVICING"
    assert declined["perfection_state"] == "UNPERFECTED"
    assert declined["ltv_bps"] == UNEXECUTED_LTV_BPS
    assert declined["apr_bps"] == priced["apr_bps"]
    assert declined["term_months"] == priced["term_months"], (
        "a decline records a decision; it does not re-price or unprice the loan"
    )
    assert declined["version"] == 3, "creation, submission, decline"
    assert declined["approved_by_user_id"] is None
    assert declined["funded_at"] is None
    assert declined["principal_balance_cents"] == 0

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == 0
    assert borrower["status"] == "ACTIVE", "a refused application is not a black mark"


def test_funding_a_declined_loan_reports_the_terminal_state_not_the_missing_lien(api):
    """PRD §3.4: "Any origination action attempted from the wrong underwriting
    standing — submitting from anything but `DRAFT`, approving or declining from
    anything but `UNDERWRITING`, funding from anything but `APPROVED` — is refused
    with `ERR_LOAN_UNDERWRITING_INVALID_STATE` (HTTP 409)."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this order:
    guide effectiveness for a valuation; duplicate HUD label, placement-field
    consistency and lot-occupancy conflict for a unit registration; the two
    stale-version checks of §2.9, with the unit check on valuation creation preceding
    the loan check on policy creation; then the state-machine gates — unit
    classification state, recovery hold, valuation certifiability,
    operator-agreement state, filing state, recovery-path availability,
    recovery-case state, loan underwriting state, loan servicing state, and
    payment-reversal eligibility, in that sequence."
    PRD §3.4: "The loan's `perfection_state` must be `PERFECTED` with exactly one
    filing in `RECORDED` standing, or the request is refused with
    `ERR_PERFECTION_NOT_ESTABLISHED` (HTTP 409)."

    Design: Corner/state_machines/fund_a_declined_loan_is_refused
    """
    scenario = _priced_then_declined_loan(api)
    loan_id = scenario["loan"]["id"]
    assert scenario["loan"]["underwriting_state"] == "DECLINED"
    assert scenario["loan"]["perfection_state"] == "UNPERFECTED"
    assert scenario["loan"]["insurance_compliance"] == "UNKNOWN"

    _, filing_meta = validate_paginated(
        api.list_lien_filings(fixtures.CLOSER, {"loan_id": loan_id})
    )
    _, policy_meta = validate_paginated(
        api.list_insurance_policies(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert filing_meta["total_count"] == 0, "no instrument was ever tendered"
    assert policy_meta["total_count"] == 0, "no coverage was ever proved"

    validate_error(
        api.fund_loan(
            loan_id,
            factories.fund_payload(FIRST_DUE_DATE),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_LOAN_UNDERWRITING_INVALID_STATE.value,
        409,
    )

    unchanged = fixtures.read_loan(api, loan_id)
    assert unchanged["underwriting_state"] == "DECLINED", (
        "the state-machine gate is climbed before the perfection and insurance "
        "gates, so the caller hears about the terminal decision and not about the "
        "paperwork it never filed"
    )
    assert unchanged["servicing_state"] == "NOT_SERVICING"
    assert unchanged["version"] == 3
    assert unchanged["principal_balance_cents"] == 0
    assert unchanged["funded_at"] is None
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == 0


def test_initiating_a_conversion_on_a_rented_lot_is_refused(api):
    """PRD §3.8: "The `INITIATE` action moves the unit's `classification` from
    `PERSONAL_PROPERTY` to `CONVERSION_PENDING` and does nothing else — it is a
    declaration of intent that changes no other resource. It is nonetheless gated on
    real paperwork: the unit's `placement_type` must be `PRIVATE_LAND`, and both
    `deed_recorded` and `affixation_affidavit_recorded` must already be true. A unit
    on a community lot, or one missing either land document, is refused with
    `ERR_LAND_DOCUMENTS_INCOMPLETE` (HTTP 409)."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that
    starts at 1 and increments by exactly one on every mutation."

    Design: Corner/state_machines/conversion_initiate_on_community_unit_returns_land_documents_incomplete
    """
    fixtures.set_clock(api, CLOCK)
    community = fixtures.register_community(api, **PINE_RIDGE)
    unit = fixtures.register_community_unit(api, community["id"])
    assert_manufactured_unit(unit)
    assert unit["placement_type"] == "COMMUNITY"
    assert unit["classification"] == "PERSONAL_PROPERTY"

    validate_error(
        api.convert_classification(unit["id"], "INITIATE", fixtures.CLOSER),
        ApiErrorId.ERR_LAND_DOCUMENTS_INCOMPLETE.value,
        409,
    )

    unchanged = fixtures.read_unit(api, unit["id"])
    assert unchanged["classification"] == "PERSONAL_PROPERTY"
    assert unchanged["title_status"] == "ACTIVE_TITLE"
    assert unchanged["deed_recorded"] is False
    assert unchanged["affixation_affidavit_recorded"] is False
    assert unchanged["version"] == 1, (
        "a home on a rented lot can never become real property, and the refusal "
        "leaves the row exactly as registered"
    )


def test_a_second_certification_cannot_overwrite_the_first_certifier(api):
    """PRD §3.3: "Certification is performed by a `CreditAnalyst` or a
    `RecoveryManager` and freezes the row: `status` moves to `CERTIFIED`,
    `certified_by_user_id` is stamped with the acting `X-User-ID`, and `certified_at`
    is stamped with the logical clock."
    PRD §3.3: "Certification is only available on a valuation whose `status` is
    `DRAFT`; attempting it on one that is already `CERTIFIED` or has been
    `SUPERSEDED` is refused with `ERR_VALUATION_NOT_CERTIFIABLE` (HTTP 409)."
    PRD §3.3: "Otherwise the unit sits on a community lot, and the key is
    `COMMUNITY_WITH_AGREEMENT` when that community's `operator_agreement_status` is
    `EXECUTED` and `COMMUNITY_WITHOUT_AGREEMENT` in every other case — including
    `PENDING` and `TERMINATED`, neither of which grants the lender anything."

    Design: Corner/state_machines/second_certify_on_certified_valuation_is_refused
    """
    fixtures.set_clock(api, CLOCK)
    guide = fixtures.publish_guide(api)
    community = fixtures.register_community(api, **PINE_RIDGE)
    unit = fixtures.register_community_unit(api, community["id"])
    valuation = fixtures.create_certified_valuation(
        api, unit["id"], guide["id"], "ORIGINATION"
    )
    assert valuation["status"] == "CERTIFIED"
    assert valuation["certified_by_user_id"] == fixtures.VALUATION_CERTIFIER_USER_ID
    assert valuation["certified_value_cents"] == UNEXECUTED_CERTIFIED_CENTS

    validate_error(
        api.certify_valuation(
            valuation["id"],
            fixtures.make_recovery_manager_headers(
                fixtures.RECOVERY_CERTIFIER_USER_ID
            ),
        ),
        ApiErrorId.ERR_VALUATION_NOT_CERTIFIABLE.value,
        409,
    )

    unchanged = fixtures.read_valuation(api, valuation["id"])
    assert unchanged["status"] == "CERTIFIED"
    assert unchanged["certified_by_user_id"] == fixtures.VALUATION_CERTIFIER_USER_ID, (
        "the identity frozen here is the counterparty of the segregation-of-duties "
        "control, so a repeat call must not be able to substitute a new certifier"
    )
    assert unchanged["certified_by_user_id"] != fixtures.RECOVERY_CERTIFIER_USER_ID
    assert_instant_equals(
        unchanged["certified_at"], CLOCK, "Valuation.certified_at"
    )
    assert unchanged["certified_value_cents"] == UNEXECUTED_CERTIFIED_CENTS


def test_the_operator_cannot_execute_an_agreement_that_was_never_proposed(api):
    """PRD §3.1: "A newly registered community starts with
    `operator_agreement_status` at `NONE`, `lender_access_rights` false, and
    `agreement_executed_at` null."
    PRD §3.1: "From `PENDING`, the `action` value `EXECUTE` moves the community to
    `EXECUTED`, and this is the one write in the system reserved to the
    `CommunityOperator` role: the acting `X-User-ID` must equal the community's own
    `id`."
    PRD §3.1: "An `action` that does not match the community's current standing —
    proposing while `PENDING` or `EXECUTED`, executing while not `PENDING`,
    terminating while not `EXECUTED` — is rejected with
    `ERR_OPERATOR_AGREEMENT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/execute_operator_agreement_from_none_status_is_refused
    """
    fixtures.set_clock(api, CLOCK)
    community = fixtures.register_community(api, **PINE_RIDGE)
    assert_community(community)
    assert community["operator_agreement_status"] == "NONE"
    assert community["version"] == 1

    validate_error(
        api.operator_agreement(
            community["id"],
            "EXECUTE",
            fixtures.make_community_operator_headers(community["id"]),
        ),
        ApiErrorId.ERR_OPERATOR_AGREEMENT_INVALID_STATE.value,
        409,
    )

    unchanged = fixtures.read_community(api, community["id"])
    assert unchanged["operator_agreement_status"] == "NONE", (
        "the acting identity is the community's own id, so ownership was satisfied "
        "and the standing of the agreement is the first and only failure"
    )
    assert unchanged["lender_access_rights"] is False
    assert unchanged["agreement_executed_at"] is None
    assert unchanged["version"] == 1


def test_one_fund_call_fires_every_declared_side_effect(api):
    """PRD §3.4: "A successful funding advances `underwriting_state` from `APPROVED`
    to `FUNDED` and, as a cascade onto the servicing dimension, advances
    `servicing_state` from `NOT_SERVICING` to `CURRENT`. It stamps `funded_at` and
    `last_accrual_date` with the logical clock and sets `next_due_date` to the
    supplied `first_due_date`. It sets `principal_balance_cents` to `principal_cents`,
    opening the loan's unpaid principal. It records `escrow_target_cents` from the
    request, defaulting to 0 when the field is omitted — and a target of zero means
    the escrow bucket of the payment waterfall is permanently empty, which materially
    changes how cash is applied. It increases the borrower's
    `total_outstanding_principal_cents` by `principal_cents`. And it increments the
    loan's `version`."
    PRD §3.4: "The `ltv_bps` figure is `principal_cents` multiplied by ten thousand
    and divided by the valuation's `certified_value_cents`, rounded half up to a
    whole basis point — the only rounded quantity in the whole pricing walk."
    PRD §3.4: "The stack starts at a base of 875 basis points. To it is added a
    placement spread of 225 basis points when the loan's `placement_type` is
    `COMMUNITY` and 50 basis points when it is `PRIVATE_LAND`. To that is added a
    classification spread of 175 basis points when `collateral_classification` is
    `PERSONAL_PROPERTY` and zero when it is `REAL_PROPERTY`. To that is added a
    credit-tier spread read off the borrower's `credit_score`: a credit of 200 basis
    points at a score of 780 or above, a credit of 125 basis points from 720 through
    779, exactly zero from 660 through 719, a charge of 200 basis points from 600
    through 659, and a charge of 425 basis points below 600. To that is added a
    leverage-tier spread read off the `ltv_bps` just computed: zero at 8000 basis
    points or below, 75 basis points from 8001 through 9000, and 150 basis points
    from 9001 through 9500 — anything above 9500 having already been refused."
    PRD §3.3: "The `location_adjustment_cents` figure is `book_base_cents` multiplied
    by the location rate for `location_key` divided by ten thousand, rounded half up
    — a credit of 300 basis points for `COMMUNITY_WITH_AGREEMENT`, a charge of 700
    basis points for `COMMUNITY_WITHOUT_AGREEMENT`, and a credit of 900 basis points
    for `PRIVATE_LAND`."
    PRD §3.6: "The `required_coverage_cents` figure is then the greater of that
    exposure and the insurable value multiplied by the required-coverage ratio for
    the loan's `collateral_classification` divided by ten thousand, rounded half up —
    where the ratio is 8000 basis points, four fifths of insurable value, for
    `PERSONAL_PROPERTY` and 10000 basis points, the whole insurable value, for
    `REAL_PROPERTY`."

    Design: Corner/state_machines/funding_executes_every_declared_side_effect_on_loan_and_borrower
    """
    scenario = _closable_loan_on_an_executed_lot(api)
    loan_id = scenario["loan"]["id"]
    assert scenario["community"]["operator_agreement_status"] == "EXECUTED"
    assert scenario["valuation"]["location_key"] == "COMMUNITY_WITH_AGREEMENT"
    assert scenario["valuation"]["certified_value_cents"] == EXECUTED_CERTIFIED_CENTS
    assert scenario["loan"]["underwriting_state"] == "APPROVED"
    assert scenario["loan"]["principal_balance_cents"] == 0

    loan = validate_success(
        api.fund_loan(
            loan_id, factories.fund_payload(FIRST_DUE_DATE), fixtures.CLOSER
        )
    )

    assert_loan(loan)
    assert loan["underwriting_state"] == "FUNDED"
    assert loan["servicing_state"] == "CURRENT"
    assert loan["perfection_state"] == "PERFECTED"
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS
    assert_instant_equals(loan["funded_at"], CLOCK, "Loan.funded_at")
    assert_instant_equals(loan["last_accrual_date"], CLOCK, "Loan.last_accrual_date")
    assert_instant_equals(loan["next_due_date"], FIRST_DUE_DATE, "Loan.next_due_date")
    assert loan["escrow_target_cents"] == 0, "the field was omitted from the request"
    assert loan["escrow_balance_cents"] == 0
    assert loan["ltv_bps"] == EXECUTED_LTV_BPS
    assert loan["ltv_bps"] <= LEVERAGE_TIER_FREE_CEILING_BPS, (
        "the executed agreement lifted the collateral value enough to keep the loan "
        "out of the leverage-tier surcharge altogether"
    )
    assert loan["apr_bps"] == EXECUTED_APR_BPS
    assert loan["term_months"] == GRANTED_TERM_MONTHS
    assert loan["interest_accrued_unpaid_cents"] == 0
    assert loan["fees_outstanding_cents"] == 0
    assert loan["delinquent_days"] == 0

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == PRINCIPAL_CENTS
    assert borrower["units_under_recovery_hold_count"] == 0
    assert borrower["status"] == "ACTIVE"

    policy = fixtures.read_policy(api, scenario["policy"]["id"])
    assert_insurance_policy(policy)
    assert policy["required_coverage_cents"] == REQUIRED_COVERAGE_CENTS
    assert policy["compliance_state"] == "COMPLIANT"
    assert fixtures.read_filing(api, scenario["filing"]["id"])["status"] == "RECORDED"


def test_one_assessment_lapses_the_policy_and_accrues_without_a_late_fee(api):
    """PRD §3.6: "Lapse is driven by the clock rather than by a request: a periodic
    servicing assessment that observes the logical clock at or after an `ACTIVE`
    policy's `expiry_date` moves that policy to `LAPSED` and sets the loan's
    `insurance_compliance` to `NON_COMPLIANT`, which in turn is what makes
    force-placement available."
    PRD §3.6: "A policy that is superseded or lapses rather than being cancelled
    keeps `unearned_premium_refund_cents` at 0."
    PRD §3.7: "The assessment accrues interest up to the logical clock, refreshes
    `delinquent_days` as the whole calendar days from `next_due_date` up to the
    logical clock floored at zero, lapses an `ACTIVE` policy whose `expiry_date` the
    clock has reached or passed, and — when `delinquent_days` has reached 30 or more
    — moves the loan from `CURRENT` to `DELINQUENT` and adds a flat late fee of 3,500
    cents to `fees_outstanding_cents`."
    PRD §3.7: "The `accrual_days` figure is the whole calendar days from the loan's
    `last_accrual_date` up to the logical clock, over a half-open interval. The
    accrued amount is the loan's `principal_balance_cents` multiplied by its `apr_bps`
    divided by ten thousand, multiplied by `accrual_days` and divided by 365 — an
    actual-over-365 day count — with the whole product evaluated exactly and rounded
    half up to a whole cent one time. That amount is added to
    `interest_accrued_unpaid_cents`, and `last_accrual_date` is advanced to the
    logical clock."

    Design: Corner/state_machines/servicing_assessment_lapses_expired_policy_and_flips_compliance
    """
    scenario = _closable_loan_on_an_executed_lot(
        api, policy_overrides={"expiry_date": SHORT_EXPIRY_DATE}
    )
    loan_id = scenario["loan"]["id"]
    funded = fixtures.fund_loan(api, loan_id, FIRST_DUE_DATE)
    assert funded["servicing_state"] == "CURRENT"
    assert funded["insurance_compliance"] == "COMPLIANT"
    assert funded["apr_bps"] == EXECUTED_APR_BPS
    assert scenario["policy"]["status"] == "ACTIVE"

    fixtures.set_clock(api, LAPSE_CLOCK)
    loan = validate_success(api.servicing_assessment(loan_id, fixtures.SERVICER))

    policy = fixtures.read_policy(api, scenario["policy"]["id"])
    assert policy["status"] == "LAPSED"
    assert policy["unearned_premium_refund_cents"] == 0
    assert loan["insurance_compliance"] == "NON_COMPLIANT"
    assert loan["interest_accrued_unpaid_cents"] == ACCRUED_INTEREST_CENTS
    assert_instant_equals(
        loan["last_accrual_date"], LAPSE_CLOCK, "Loan.last_accrual_date"
    )
    assert loan["delinquent_days"] == DELINQUENT_DAYS
    assert loan["delinquent_days"] < DELINQUENCY_THRESHOLD_DAYS
    assert loan["servicing_state"] == "CURRENT", (
        "coverage and cash are graded independently: the policy expired but the "
        "instalment is only a fortnight late"
    )
    assert loan["fees_outstanding_cents"] == 0
    assert loan["force_placed_premium_outstanding_cents"] == 0
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS
