"""Signed adjustments, variant deductions, four-way term caps and two filtered sums.

Each figure here is pinned by one arithmetic rule of the PRD rather than by a
state transition: the location adjustment that turns negative without a signed
operator agreement, the liquidation deductions, the useful-life cap that starves
the term floor, the two-legged coverage requirement, and the exposure sum that
ignores loans nobody is servicing.
"""

from test_helpers import (
    ApiErrorId,
    assert_insurance_policy,
    assert_valuation,
    assert_valuation_breakdown,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
VALUATION_YEAR = 2026

DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}
MARCUS = {
    "full_name": "Marcus Bell",
    "credit_score": 728,
    "monthly_income_cents": 610000,
    "state_code": "GA",
}
PINE_RIDGE = {
    "name": "Pine Ridge MHC",
    "state_code": "GA",
    "lot_count": 180,
    "monthly_lot_rent_cents": 52000,
    "sales_commission_bps": 150,
}

# ─── The 1440 sqft 2018 MULTI_WIDE on a rented lot, both variants ───
BOOK_BASE_CENTS = 5365440
CONDITION_ADJUSTMENT_CENTS = 0
UNAGREED_LOCATION_ADJUSTMENT_CENTS = -375581
ORIGINATION_INSTALLATION_CENTS = 250000
ORIGINATION_CERTIFIED_CENTS = 5239859
AGREED_CERTIFIED_CENTS = 5776403
LIQUIDATION_INSTALLATION_CENTS = 0
FORCED_SALE_DISCOUNT_CENTS = 1097769
DETACH_AND_MOVE_COST_CENTS = 675000
LIQUIDATION_CERTIFIED_CENTS = 3217090

# ─── The 1988 SINGLE_WIDE with two years of life left ───
OLD_UNIT = {
    "hud_label_number": "ALB8801234",
    "manufacturer": "Fleetwood",
    "model_year": 1988,
    "width_class": "SINGLE_WIDE",
    "square_feet": 1080,
    "condition_grade": "GOOD",
    "installation_type": "PIER_AND_ANCHOR",
    "wind_zone": 1,
    "land_parcel_apn": "072-114-003",
    "land_county": "Bibb",
}
OLD_PRINCIPAL_CENTS = 1700000
OLD_REQUESTED_TERM_MONTHS = 180
REMAINING_USEFUL_LIFE_MONTHS = 24
MIN_TERM_MONTHS = 60

# ─── The loan whose exposure leg beats the ratio leg ───
THIN_PRINCIPAL_CENTS = 4700000
RATIO_LEG_CENTS = 4621122
DEFICIENT_DWELLING_COVERAGE_CENTS = 4650000
COVERAGE_DAYS = 365

# ─── Three loans on one obligor, only one of them serviced ───
FUNDED_PRINCIPAL_CENTS = 4600000
FUNDED_DWELLING_COVERAGE_CENTS = 4700000
DECLINED_PRINCIPAL_CENTS = 1000000
DECLINED_LOT = "A-15"
DRAFT_PRINCIPAL_CENTS = 500000
DRAFT_LOT = "A-16"
REQUESTED_TERM_MONTHS = 240
DECLINE_REASON = "second lien not permitted on the same collateral"


def _unagreed_park_with_one_unit(api):
    """A guide and a 1440 sqft piered unit on a lot whose operator never signed."""
    fixtures.set_clock(api, CLOCK)
    guide = fixtures.publish_guide(api)
    community = fixtures.register_community(api, **PINE_RIDGE)
    unit = fixtures.register_community_unit(api, community["id"])
    assert community["operator_agreement_status"] == "NONE"
    return {"guide": guide, "community": community, "unit": unit}


def _executed_park_with_an_approved_loan(api, principal_cents):
    """An APPROVED, title-lien-perfected loan in a park that signed the agreement."""
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
        principal_cents=principal_cents,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    scenario["filing"] = fixtures.perfect_with_title_lien(api, scenario["loan"]["id"])
    return scenario


def test_a_park_that_never_signed_drags_the_location_adjustment_negative(api):
    """PRD §3.3: "The platform stamps `valuation_year` with the calendar year of the
    logical clock at the moment of creation, which fixes the age used for
    depreciation for the life of this valuation. Age in years is `valuation_year`
    minus the unit's `model_year`, floored at zero so that a unit newer than the
    current year never ages negatively. Depreciation in basis points is that age in
    years multiplied by the guide's `annual_depreciation_bps`, but capped: the
    depreciation may never exceed 7000 basis points, which is ten thousand basis
    points less a 3000-basis-point residual floor, so at least thirty percent of
    guide value always survives no matter how old the unit is."
    PRD §3.3: "The width multiplier is the guide's `multi_wide_multiplier_bps` when
    the unit's `width_class` is `MULTI_WIDE` and its `single_wide_multiplier_bps`
    otherwise. The platform then computes `book_base_cents` as the unit's
    `square_feet` multiplied by the guide's `base_value_per_sqft_cents`, multiplied by
    the width multiplier in basis points divided by ten thousand, multiplied by the
    surviving fraction of value — ten thousand basis points less the depreciation in
    basis points, divided by ten thousand."
    PRD §3.3: "Otherwise the unit sits on a community lot, and the key is
    `COMMUNITY_WITH_AGREEMENT` when that community's `operator_agreement_status` is
    `EXECUTED` and `COMMUNITY_WITHOUT_AGREEMENT` in every other case — including
    `PENDING` and `TERMINATED`, neither of which grants the lender anything."
    PRD §3.3: "The fourth step applies three adjustments, and a detail here is easy
    to get wrong: both proportional adjustments are taken on `book_base_cents`
    itself, never on a running subtotal that already includes the other adjustment.
    The `condition_adjustment_cents` figure is `book_base_cents` multiplied by the
    condition rate for the unit's `condition_grade` divided by ten thousand, rounded
    half up — where the rate is a credit of 800 basis points for `EXCELLENT`, exactly
    zero for `GOOD`, a charge of 1200 basis points for `FAIR`, and a charge of 2500
    basis points for `POOR`. The `location_adjustment_cents` figure is
    `book_base_cents` multiplied by the location rate for `location_key` divided by
    ten thousand, rounded half up — a credit of 300 basis points for
    `COMMUNITY_WITH_AGREEMENT`, a charge of 700 basis points for
    `COMMUNITY_WITHOUT_AGREEMENT`, and a credit of 900 basis points for
    `PRIVATE_LAND`. Both of these are signed quantities: a charge is stored as a
    negative number of cents."
    PRD §3.3: "On the `ORIGINATION` variant, both liquidation deductions are recorded
    as zero — `forced_sale_discount_cents` is 0 and `detach_and_move_cost_cents` is 0
    — and `certified_value_cents` is the adjusted subtotal exactly as computed."
    PRD §3.3: "It increments the unit's own `version`, so a client that creates two
    valuations back to back must re-read the unit between them. And it leaves the new
    valuation in `status` `DRAFT`, with `certified_by_user_id` and `certified_at` both
    null."

    Design: Corner/calculations/valuation_location_adjustment_is_negative_without_an_operator_agreement
    """
    scenario = _unagreed_park_with_one_unit(api)

    valuation = validate_success(
        api.create_valuation(
            factories.valuation_payload(
                scenario["unit"]["id"],
                scenario["guide"]["id"],
                scenario["unit"]["version"],
                "ORIGINATION",
            ),
            fixtures.ANALYST,
        ),
        201,
    )

    assert_valuation(valuation)
    assert valuation["valuation_year"] == VALUATION_YEAR
    assert valuation["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"
    assert_valuation_breakdown(
        valuation,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=CONDITION_ADJUSTMENT_CENTS,
        location_adjustment_cents=UNAGREED_LOCATION_ADJUSTMENT_CENTS,
        installation_adjustment_cents=ORIGINATION_INSTALLATION_CENTS,
        forced_sale_discount_cents=0,
        detach_and_move_cost_cents=0,
        certified_value_cents=ORIGINATION_CERTIFIED_CENTS,
    )
    assert valuation["location_adjustment_cents"] < 0, (
        "an unsigned park is a charge against value, not a credit"
    )
    assert valuation["certified_value_cents"] < AGREED_CERTIFIED_CENTS, (
        "the identical unit would certify higher on a lot whose operator signed"
    )
    assert valuation["status"] == "DRAFT"
    assert valuation["certified_by_user_id"] is None
    assert valuation["certified_at"] is None

    assert fixtures.read_unit(api, scenario["unit"]["id"])["version"] == 2


def test_the_liquidation_variant_drops_installation_and_charges_the_move(api):
    """PRD §3.3: "The `variant` is either `ORIGINATION` — the value that underwriting
    leans on — or `RECOVERY_LIQUIDATION`, the value a recovered unit is expected to
    fetch in a forced sale."
    PRD §3.3: "The `installation_adjustment_cents` figure is not proportional at all
    — on the `ORIGINATION` variant it is a flat 850,000 cents for a unit on a
    `PERMANENT_FOUNDATION` and a flat 250,000 cents for a unit on `PIER_AND_ANCHOR`,
    and on the `RECOVERY_LIQUIDATION` variant it is dropped entirely and recorded as
    zero. The adjusted subtotal is `book_base_cents` plus all three adjustments."
    PRD §3.3: "On the `RECOVERY_LIQUIDATION` variant, two deductions apply. The
    `forced_sale_discount_cents` figure is the adjusted subtotal multiplied by 2200
    basis points divided by ten thousand, rounded half up — the haircut a forced sale
    takes. The `detach_and_move_cost_cents` figure is a flat 675,000 cents when, and
    only when, `location_key` is `COMMUNITY_WITHOUT_AGREEMENT`; on private land, or in
    a community whose operator agreement is executed, it is zero, because in those
    cases the unit can be sold where it stands rather than detached and hauled away.
    Then `certified_value_cents` is the adjusted subtotal less the forced-sale
    discount less the detach-and-move cost, floored at zero so that a badly
    depreciated unit reports a value of 0 rather than a negative one."
    PRD §3.3: "It moves any earlier `CERTIFIED` valuation of the same unit and the
    same variant to `SUPERSEDED` — which is precisely why the stale-version guard of
    §2.9 exists on this write, and why `ERR_STALE_UNIT_VERSION` is returned when
    `expected_unit_version` does not match."

    Design: Corner/calculations/recovery_liquidation_on_an_unagreed_community_lot_subtracts_detach_and_move_cost
    """
    scenario = _unagreed_park_with_one_unit(api)
    unit_id = scenario["unit"]["id"]
    origination = fixtures.create_valuation(
        api, unit_id, scenario["guide"]["id"], scenario["unit"]["version"], "ORIGINATION"
    )

    liquidation = validate_success(
        api.create_valuation(
            factories.valuation_payload(
                unit_id,
                scenario["guide"]["id"],
                fixtures.read_unit(api, unit_id)["version"],
                "RECOVERY_LIQUIDATION",
            ),
            fixtures.RECOVERY,
        ),
        201,
    )

    assert_valuation(liquidation)
    assert liquidation["variant"] == "RECOVERY_LIQUIDATION"
    assert liquidation["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"
    assert_valuation_breakdown(
        liquidation,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=CONDITION_ADJUSTMENT_CENTS,
        location_adjustment_cents=UNAGREED_LOCATION_ADJUSTMENT_CENTS,
        installation_adjustment_cents=LIQUIDATION_INSTALLATION_CENTS,
        forced_sale_discount_cents=FORCED_SALE_DISCOUNT_CENTS,
        detach_and_move_cost_cents=DETACH_AND_MOVE_COST_CENTS,
        certified_value_cents=LIQUIDATION_CERTIFIED_CENTS,
    )

    untouched = fixtures.read_valuation(api, origination["id"])
    assert untouched["status"] == "DRAFT", (
        "supersession is keyed on the variant as well as the unit, so the "
        "origination row is left alone"
    )
    assert untouched["certified_value_cents"] == ORIGINATION_CERTIFIED_CENTS
    assert untouched["installation_adjustment_cents"] == ORIGINATION_INSTALLATION_CENTS


def test_a_unit_with_two_years_of_life_left_cannot_reach_the_term_floor(api):
    """PRD §3.4: "Term is the smallest survivor of four independent caps, every one of
    which applies. The first is the borrower's own `requested_term_months`. The second
    is a placement cap of 240 months for a `COMMUNITY` placement and 300 months for
    `PRIVATE_LAND`. The third is a classification cap of 240 months for
    `PERSONAL_PROPERTY` and 360 months for `REAL_PROPERTY`. The fourth is the
    collateral's remaining useful life in months, computed as forty years less the age
    implied by the valuation — that is, forty less the difference between the
    valuation's `valuation_year` and the unit's `model_year` — multiplied by twelve,
    and floored at zero so an over-age unit contributes a cap of zero rather than a
    negative one. The granted `term_months` is the minimum of those four. If that
    minimum falls below the five-year floor of 60 months, the submission is refused
    with `ERR_TERM_FLOOR_UNREACHABLE` (HTTP 422)."
    PRD §3.4: "Submitting the application for underwriting is the pricing act: it
    advances `underwriting_state` from `DRAFT` to `UNDERWRITING` and, in doing so,
    computes and stores `ltv_bps`, `apr_bps` and `term_months`, all three of which are
    null until this succeeds."
    PRD §3.3: "The platform stamps `valuation_year` with the calendar year of the
    logical clock at the moment of creation, which fixes the age used for depreciation
    for the life of this valuation."

    Design: Corner/calculations/term_clamped_to_remaining_useful_life_below_the_floor_is_refused
    """
    scenario = fixtures.setup_private_land_collateral(
        api,
        clock=CLOCK,
        borrower_overrides=MARCUS,
        unit_overrides=OLD_UNIT,
        record_documents=False,
    )
    unit = scenario["unit"]
    valuation = fixtures.create_certified_valuation(
        api, unit["id"], scenario["guide"]["id"]
    )
    assert unit["model_year"] == OLD_UNIT["model_year"]
    assert valuation["status"] == "CERTIFIED"
    assert valuation["valuation_year"] == VALUATION_YEAR
    assert (
        (40 - (valuation["valuation_year"] - unit["model_year"])) * 12
        == REMAINING_USEFUL_LIFE_MONTHS
        < MIN_TERM_MONTHS
    ), "the useful-life cap is the binding one and it sits under the floor"

    loan = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        unit["id"],
        valuation["id"],
        principal_cents=OLD_PRINCIPAL_CENTS,
        requested_term_months=OLD_REQUESTED_TERM_MONTHS,
    )

    validate_error(
        api.submit_underwriting(loan["id"], fixtures.ANALYST),
        ApiErrorId.ERR_TERM_FLOOR_UNREACHABLE.value,
        422,
    )

    refused = fixtures.read_loan(api, loan["id"])
    assert refused["underwriting_state"] == "DRAFT", (
        "a refused submission leaves the application where it was"
    )
    assert refused["term_months"] is None
    assert refused["ltv_bps"] is None
    assert refused["apr_bps"] is None
    assert refused["version"] == loan["version"]


def test_required_coverage_takes_the_exposure_leg_when_the_ratio_leg_is_lower(api):
    """PRD §3.6: "The insurable value is the `certified_value_cents` of the loan's
    certified origination valuation. The exposure is the loan's
    `principal_balance_cents` once the loan has reached `FUNDED`, and its
    `principal_cents` before that. The `required_coverage_cents` figure is then the
    greater of that exposure and the insurable value multiplied by the
    required-coverage ratio for the loan's `collateral_classification` divided by ten
    thousand, rounded half up — where the ratio is 8000 basis points, four fifths of
    insurable value, for `PERSONAL_PROPERTY` and 10000 basis points, the whole
    insurable value, for `REAL_PROPERTY`."
    PRD §3.6: "Wind coverage is required when the unit's `wind_zone` is 3, and also
    when the `wind_zone` is 2 and the `installation_type` is `PIER_AND_ANCHOR` — an
    anchored unit in a moderate zone being treated as exposed as a foundation-set unit
    in the worst zone. A policy's `compliance_state` is therefore `DEFICIENT_WIND`
    when wind coverage is required and the policy carries no `wind_endorsement`;
    otherwise it is `DEFICIENT_COVERAGE` when the policy's `dwelling_coverage_cents`
    is below `required_coverage_cents`; otherwise it is `COMPLIANT`."
    PRD §3.6: "A borrower-provided policy is recorded with `source` `BORROWER_PROVIDED`,
    `status` `ACTIVE` and `premium_cents` 0 — the borrower pays their own carrier, so
    the lender advances nothing. Creating it moves any earlier `ACTIVE`
    borrower-provided policy on the same loan to `SUPERSEDED` and recomputes the
    loan's `insurance_compliance` from whichever policy survives as `ACTIVE`, which is
    either `COMPLIANT` or `NON_COMPLIANT`."
    PRD §3.6: "The platform computes `coverage_days` as the whole calendar days from
    `effective_date` up to `expiry_date`."
    PRD §3.6: "Third, the active policy's `dwelling_coverage_cents` must be at least
    `required_coverage_cents`, or funding is refused with
    `ERR_DWELLING_COVERAGE_INSUFFICIENT` (HTTP 422)."

    Design: Corner/calculations/required_coverage_floors_at_principal_when_the_bps_leg_is_lower
    """
    scenario = _executed_park_with_an_approved_loan(api, THIN_PRINCIPAL_CENTS)
    loan_id = scenario["loan"]["id"]
    assert scenario["valuation"]["certified_value_cents"] == AGREED_CERTIFIED_CENTS
    assert scenario["loan"]["principal_cents"] == THIN_PRINCIPAL_CENTS
    assert fixtures.read_loan(api, loan_id)["principal_balance_cents"] == 0

    policy = fixtures.record_policy(
        api, loan_id, DEFICIENT_DWELLING_COVERAGE_CENTS
    )

    assert_insurance_policy(policy)
    assert policy["required_coverage_cents"] == THIN_PRINCIPAL_CENTS, (
        "the unfunded principal beats four fifths of insurable value"
    )
    assert policy["required_coverage_cents"] > RATIO_LEG_CENTS
    assert policy["coverage_days"] == COVERAGE_DAYS
    assert policy["source"] == "BORROWER_PROVIDED"
    assert policy["status"] == "ACTIVE"
    assert policy["premium_cents"] == 0
    assert policy["wind_endorsement"] is True
    assert policy["compliance_state"] == "DEFICIENT_COVERAGE", (
        "the wind endorsement clears the first grade, so the shortfall is graded "
        "against the requirement rather than reported as a wind defect"
    )
    assert fixtures.read_loan(api, loan_id)["insurance_compliance"] == "NON_COMPLIANT"

    validate_error(
        api.fund_loan(
            loan_id,
            factories.fund_payload(first_due_date=FIRST_DUE_DATE),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_DWELLING_COVERAGE_INSUFFICIENT.value,
        422,
    )


def test_exposure_counts_only_the_loan_that_is_actually_being_serviced(api):
    """PRD §3.1: "A borrower's `total_outstanding_principal_cents` begins at 0 and is
    at all times the sum of `principal_balance_cents` across that borrower's loans
    whose servicing standing is `CURRENT`, `DELINQUENT`, `DEFAULT` or `RECOVERY` —
    loans that have reached `PAID_OFF` or `CHARGED_OFF` are excluded from the total
    entirely."
    PRD §3.4: "A successful funding advances `underwriting_state` from `APPROVED` to
    `FUNDED` and, as a cascade onto the servicing dimension, advances `servicing_state`
    from `NOT_SERVICING` to `CURRENT`. It stamps `funded_at` and `last_accrual_date`
    with the logical clock and sets `next_due_date` to the supplied `first_due_date`.
    It sets `principal_balance_cents` to `principal_cents`, opening the loan's unpaid
    principal. It records `escrow_target_cents` from the request, defaulting to 0 when
    the field is omitted — and a target of zero means the escrow bucket of the payment
    waterfall is permanently empty, which materially changes how cash is applied. It
    increases the borrower's `total_outstanding_principal_cents` by `principal_cents`."
    PRD §3.4: "The alternative outcome is a decline, which moves the loan from
    `UNDERWRITING` to `DECLINED` with no preconditions at all and accepts an optional
    `decline_reason`. A declined loan is finished: `DECLINED` is terminal on the
    underwriting dimension and the loan's `servicing_state` stays at `NOT_SERVICING`
    forever."
    PRD §3.4: "A new loan starts with `underwriting_state` `DRAFT`, `servicing_state`
    `NOT_SERVICING` and `perfection_state` `UNPERFECTED`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."

    Design: Corner/calculations/borrower_exposure_excludes_declined_and_never_funded_loans
    """
    scenario = _executed_park_with_an_approved_loan(api, FUNDED_PRINCIPAL_CENTS)
    borrower_id = scenario["borrower"]["id"]
    community_id = scenario["community"]["id"]
    guide_id = scenario["guide"]["id"]
    fixtures.record_policy(api, scenario["loan"]["id"], FUNDED_DWELLING_COVERAGE_CENTS)
    funded = fixtures.fund_loan(api, scenario["loan"]["id"], FIRST_DUE_DATE)

    declined_unit = fixtures.register_community_unit(
        api, community_id, lot_number=DECLINED_LOT
    )
    declined = fixtures.open_loan(
        api,
        borrower_id,
        declined_unit["id"],
        fixtures.create_certified_valuation(api, declined_unit["id"], guide_id)["id"],
        principal_cents=DECLINED_PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    fixtures.price_loan(api, declined["id"])
    declined = validate_success(
        api.decline_loan(
            declined["id"], fixtures.ANALYST, {"decline_reason": DECLINE_REASON}
        )
    )

    draft_unit = fixtures.register_community_unit(
        api, community_id, lot_number=DRAFT_LOT
    )
    draft = fixtures.open_loan(
        api,
        borrower_id,
        draft_unit["id"],
        fixtures.create_certified_valuation(api, draft_unit["id"], guide_id)["id"],
        principal_cents=DRAFT_PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )

    assert funded["servicing_state"] == "CURRENT"
    assert funded["principal_balance_cents"] == FUNDED_PRINCIPAL_CENTS
    assert declined["underwriting_state"] == "DECLINED"
    assert declined["servicing_state"] == "NOT_SERVICING"
    assert declined["principal_cents"] == DECLINED_PRINCIPAL_CENTS
    assert draft["underwriting_state"] == "DRAFT"
    assert draft["servicing_state"] == "NOT_SERVICING"
    assert draft["principal_balance_cents"] == 0

    borrower = fixtures.read_borrower(api, borrower_id)
    assert borrower["total_outstanding_principal_cents"] == FUNDED_PRINCIPAL_CENTS, (
        "neither the declined application nor the untouched draft is being serviced, "
        "so neither contributes a cent of exposure"
    )

    rows, meta = validate_paginated(
        api.list_loans(fixtures.ANALYST, {"borrower_id": borrower_id})
    )
    assert meta["total_count"] == 3, "all three applications really do exist"
    assert sum(row["principal_balance_cents"] for row in rows) == FUNDED_PRINCIPAL_CENTS
