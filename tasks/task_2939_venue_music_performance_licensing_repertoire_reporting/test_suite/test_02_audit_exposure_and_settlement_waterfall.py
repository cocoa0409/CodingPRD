"""
The pinned arithmetic of back-licence exposure, settlement and the fee clamp.

Three derivations in this contract look like ordinary formulas but are only
determinate because the document fixes the order in which their steps run. The
back-licence walk rounds a society's monthly instalment before any months are
summed. The settlement waterfall picks its goodwill tier once, from the
pre-credit total, and never re-picks it from the discounted figure. And the
annual fee clamps the whole-repertoire price against the schedule's floor before
the society's share apportions it, so the fee an individual society bills may end
up far below that floor. This file pins each of the three, together with the
near-miss figures the alternative orderings would have produced.
"""

from test_helpers import (
    ASSESSMENT_KIND_AUDIT_BACK_LICENSE,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    AUDIT_TRIGGER_ROUTINE,
    BILLING_INVOICED,
    CASE_STATUS_FINDINGS_ISSUED,
    COVERAGE_ACTIVE,
    LICENSE_TYPES,
    POSTURE_PARTIALLY_COVERED,
    SHARE_SESAC_BP,
    VENUE_CATEGORIES,
    activate,
    admin_headers,
    assert_assessment,
    assert_coverage,
    assert_count,
    assert_license_dimensions,
    assert_money,
    assert_not_money,
    auditor_headers,
    bmi_payload,
    case_row,
    concert_hall_venue_payload,
    fitness_studio_venue_payload,
    get_success_data,
    given_approved_application,
    given_effective_schedule,
    given_open_case,
    given_society,
    given_venue,
    license_of_application,
    license_row,
    read_rows,
    sesac_payload,
    venue_row,
)

# Enum values the PRD declares but the shared constants expose only as tuples.
_LICENSE_TYPE_BLANKET = "BLANKET"
_CONCERT_HALL = "CONCERT_HALL"
_FITNESS_STUDIO = "FITNESS_STUDIO"

assert _LICENSE_TYPE_BLANKET in LICENSE_TYPES
assert _CONCERT_HALL in VENUE_CATEGORIES
assert _FITNESS_STUDIO in VENUE_CATEGORIES

# The unlicensed concert hall: occupancy 1200 in the top tier, LIVE_ONLY, five
# live nights and 62000000 cents of cover revenue price the whole repertoire at
# 2903175 cents, of which BMI's 4600 basis points is 1335461 cents a year.
# 1335461 divided by 12 is 111288.416..., which rounds half up to 111288 cents.
_MONTHLY_INSTALMENT_CENTS = 111288

_LOOKBACK_START = "2025-01-01T00:00:00Z"
_LOOKBACK_END_18_MONTHS = "2026-07-01T00:00:00Z"
_LOOKBACK_END_16_MONTHS = "2026-05-01T00:00:00Z"

_EXPOSURE_18_MONTHS_CENTS = 2003184
_EXPOSURE_18_MONTHS_SUMMED_FIRST_CENTS = 2003192
_PENALTY_18_MONTHS_CENTS = 1001592
_PRE_CREDIT_18_MONTHS_CENTS = 3004776

_EXPOSURE_16_MONTHS_CENTS = 1780608
_PENALTY_16_MONTHS_CENTS = 890304
_PRE_CREDIT_16_MONTHS_CENTS = 2670912
_GOODWILL_CREDIT_CENTS = 267091
_GOODWILL_CREDIT_LOWER_TIER_CENTS = 133546
_SETTLEMENT_TOTAL_CENTS = 2403821
_SETTLEMENT_TOTAL_LOWER_TIER_CENTS = 2537366
_SETTLEMENT_FLOOR_CENTS = 1442293

# The fitness studio: occupancy max(0, 40) = 40 in the first tier, priced down
# to 29520 cents by the BACKGROUND_ONLY multiplier, lifted to the schedule's
# 30000-cent floor, and only then reduced to SESAC's 500 basis points of it.
_STUDIO_SCHEDULE_MIN_CENTS = 30000
_STUDIO_SCHEDULE_MAX_CENTS = 4500000
_STUDIO_FEE_CENTS = 1500
_STUDIO_TERM_START = "2026-08-01T00:00:00Z"


def _unlicensed_concert_hall_findings(api, lookback_end):
    """Issue findings on a routine audit of a concert hall that never held a licence.

    BMI, an effective concert-hall schedule and the venue survey are all that the
    exposure walk needs; because the venue holds no licence at all, every month
    of the lookback comes back uncovered.
    """
    society = given_society(api, bmi_payload())
    given_effective_schedule(api, society["id"], _CONCERT_HALL)
    venue = given_venue(api, concert_hall_venue_payload("Harborlight Concert Hall"))
    case = given_open_case(
        api,
        venue["id"],
        [society["id"]],
        lookback_start=_LOOKBACK_START,
        lookback_end=lookback_end,
        audit_trigger=AUDIT_TRIGGER_ROUTINE,
    )
    issued = get_success_data(api.issue_findings(case["id"], auditor_headers()))
    return {
        "society": society,
        "venue": venue,
        "case": case_row(api, case["id"]),
        "issued": issued,
    }


def _background_only_studio_license(api):
    """Approve and activate a SESAC licence for the smallest possible studio.

    The application declares exactly the verified survey figures, so the
    provisional and the verified derivations must agree, and no exemption
    analysis has ever been run against the venue.
    """
    society = given_society(api, sesac_payload())
    given_effective_schedule(
        api,
        society["id"],
        _FITNESS_STUDIO,
        min_annual_fee_cents=_STUDIO_SCHEDULE_MIN_CENTS,
        max_annual_fee_cents=_STUDIO_SCHEDULE_MAX_CENTS,
    )
    venue = given_venue(api, fitness_studio_venue_payload())
    application = given_approved_application(
        api, venue, society["id"], _STUDIO_TERM_START
    )
    minted = license_of_application(api, application["id"])
    activate(api, minted["id"])
    return {
        "society": society,
        "venue": venue,
        "application": application,
        "license": license_row(api, minted["id"]),
    }


def test_exposure_rounds_each_month_before_the_eighteen_months_are_summed(api):
    """The monthly instalment is rounded first, then multiplied by the months.

    BMI would charge this concert hall 1335461 cents a year, so the monthly
    instalment is 111288 cents and eighteen uncovered months accumulate to
    2003184 cents. Dividing the annual fee across eighteen months and rounding
    only the total would have produced 2003192 cents instead — eight cents more,
    and the wrong answer.

    PRD §3.9: "Divide that annual fee by 12 and **round half up to whole cents to
    get the monthly instalment — before any summing takes place**."

    PRD §3.9: "Summing the unrounded monthly amounts and rounding the total at
    the end produces a different figure and is wrong."

    Design: Difficulty/combinatorial_formula/back_license_exposure_rounds_per_month_then_sums
    """
    case = _unlicensed_concert_hall_findings(api, _LOOKBACK_END_18_MONTHS)["case"]

    assert_count(case["unlicensed_month_count"], 18, "unlicensed_month_count")
    assert_money(
        case["back_license_exposure_cents"],
        _EXPOSURE_18_MONTHS_CENTS,
        "back_license_exposure_cents",
    )
    assert_money(
        case["back_license_exposure_cents"],
        18 * _MONTHLY_INSTALMENT_CENTS,
        "eighteen rounded monthly instalments",
    )
    assert_not_money(
        case["back_license_exposure_cents"],
        _EXPOSURE_18_MONTHS_SUMMED_FIRST_CENTS,
        "back_license_exposure_cents",
    )


def test_exposure_penalty_tier_and_pre_credit_total_are_billed_as_one(api):
    """Eighteen uncovered months sit in the middle penalty tier, and are billed.

    A count of eighteen falls inside the seven-to-eighteen band, so the penalty
    is half the exposure: 1001592 cents on top of 2003184, for a pre-credit total
    of 3004776 cents. Issuing findings raises exactly one back-licence assessment
    for that whole total.

    PRD §3.9: "The penalty rate is then chosen from a tier of the total
    `unlicensed_month_count`: 2500 basis points when the count is at most 6
    months, 5000 basis points when the count is from 7 through 18 months
    inclusive, and 10000 basis points when the count is 19 months or more."

    PRD §3.9: "Issuing findings records `findings_issued_by_user_id` as the
    acting `X-User-ID`, moves `status` to `FINDINGS_ISSUED` and increments
    `version`."

    Design: Difficulty/combinatorial_formula/back_license_exposure_rounds_per_month_then_sums
    """
    built = _unlicensed_concert_hall_findings(api, _LOOKBACK_END_18_MONTHS)
    case = built["case"]

    assert_money(case["penalty_cents"], _PENALTY_18_MONTHS_CENTS, "penalty_cents")
    assert_money(
        case["pre_credit_total_cents"],
        _PRE_CREDIT_18_MONTHS_CENTS,
        "pre_credit_total_cents",
    )
    assert case["status"] == CASE_STATUS_FINDINGS_ISSUED, (
        f"expected FINDINGS_ISSUED, got {case['status']!r}"
    )

    billed = read_rows(
        api.list_fee_assessments(admin_headers(), {"audit_case_id": case["id"]}),
        expected_total=1,
    )
    assert_assessment(
        billed[0],
        ASSESSMENT_KIND_AUDIT_BACK_LICENSE,
        _PRE_CREDIT_18_MONTHS_CENTS,
        ASSESSMENT_STATUS_ISSUED,
    )


def test_settlement_pre_credit_total_over_sixteen_uncovered_months(api):
    """A sixteen-month lookback accumulates sixteen rounded monthly instalments.

    Sixteen months at 111288 cents each is 1780608 cents of exposure; sixteen
    months is still inside the seven-to-eighteen penalty band, so the penalty is
    890304 cents and the pre-credit total is 2670912 cents — the figure the
    goodwill tier is then read from.

    PRD §3.9: "For every society-and-month pairing that comes back uncovered,
    `unlicensed_month_count` increases by 1 and the exposure accumulates that
    society's rounded monthly instalment."

    PRD §3.9: "`pre_credit_total_cents` is `back_license_exposure_cents` plus
    `penalty_cents`."

    Design: Difficulty/combinatorial_formula/settlement_goodwill_tier_pinned_to_pre_credit_total
    """
    case = _unlicensed_concert_hall_findings(api, _LOOKBACK_END_16_MONTHS)["case"]

    assert_count(case["unlicensed_month_count"], 16, "unlicensed_month_count")
    assert_money(
        case["back_license_exposure_cents"],
        _EXPOSURE_16_MONTHS_CENTS,
        "back_license_exposure_cents",
    )
    assert_money(case["penalty_cents"], _PENALTY_16_MONTHS_CENTS, "penalty_cents")
    assert_money(
        case["pre_credit_total_cents"],
        _PRE_CREDIT_16_MONTHS_CENTS,
        "pre_credit_total_cents",
    )


def test_settlement_goodwill_tier_is_read_once_from_the_pre_credit_total(api):
    """The goodwill tier is chosen from the pre-credit total and never re-chosen.

    A pre-credit total of 2670912 cents sits in the 1000 basis-point band, giving
    a credit of 267091 cents and a settlement target of 2403821 cents. That
    post-credit figure has fallen back below 2500000 cents, but re-reading the
    tier from it — a 500 basis-point credit of 133546 cents and a target of
    2537366 cents — is exactly what the pinned order forbids. The floor is sixty
    percent of the target that survives.

    PRD §3.9: "It is not circular, because **the tier is selected once, from the
    pre-credit total, and is never re-evaluated after the credit is applied**."

    PRD §3.9: "`settlement_total_cents` is `pre_credit_total_cents` less
    `goodwill_credit_cents`, and that post-credit figure never re-enters the tier
    selection."

    PRD §3.9: "Finally, `settlement_floor_cents` — the minimum offer the
    societies will entertain — is `settlement_total_cents` multiplied by 6000
    basis points, divided by 10000, rounded half up to whole cents, which is
    sixty percent of the settlement target."

    Design: Difficulty/combinatorial_formula/settlement_goodwill_tier_pinned_to_pre_credit_total
    """
    case = _unlicensed_concert_hall_findings(api, _LOOKBACK_END_16_MONTHS)["case"]

    assert_money(
        case["goodwill_credit_cents"],
        _GOODWILL_CREDIT_CENTS,
        "goodwill_credit_cents",
    )
    assert_not_money(
        case["goodwill_credit_cents"],
        _GOODWILL_CREDIT_LOWER_TIER_CENTS,
        "goodwill_credit_cents",
    )
    assert_money(
        case["settlement_total_cents"],
        _SETTLEMENT_TOTAL_CENTS,
        "settlement_total_cents",
    )
    assert_not_money(
        case["settlement_total_cents"],
        _SETTLEMENT_TOTAL_LOWER_TIER_CENTS,
        "settlement_total_cents",
    )
    assert_money(
        case["settlement_floor_cents"],
        _SETTLEMENT_FLOOR_CENTS,
        "settlement_floor_cents",
    )


def test_tier_clamp_background_only_studio_is_typed_blanket(api):
    """A background-only studio that was never analysed still gets a blanket type.

    The venue's exemption verdict is untouched, so the exempt branch of the type
    table cannot fire; the very next clause reads the BACKGROUND_ONLY profile and
    assigns BLANKET, which is what puts the studio on the priced calculation
    rather than the zero-fee exempt short circuit.

    PRD §3.4: "Otherwise, when the venue's `music_use_profile` is
    `BACKGROUND_ONLY`, `assigned_license_type` becomes `BLANKET`."

    PRD §3.4: "A background-only venue that failed the exemption analysis still
    needs a blanket licence."

    Design: Difficulty/combinatorial_formula/annual_fee_occupancy_max_tier_and_clamp_interaction
    """
    built = _background_only_studio_license(api)

    assert built["application"]["assigned_license_type"] == _LICENSE_TYPE_BLANKET, (
        "a background-only studio must be assigned a blanket licence type, got "
        f"{built['application']['assigned_license_type']!r}"
    )
    assert built["license"]["license_type"] == _LICENSE_TYPE_BLANKET, (
        f"licence type: expected BLANKET, got {built['license']['license_type']!r}"
    )


def test_tier_clamp_schedule_floor_lifts_the_fee_before_the_society_share(api):
    """The floor lifts the whole-repertoire price; the society's share then cuts it.

    Zero seats against forty standing places give a billable occupancy of 40, the
    lowest tier, and the BACKGROUND_ONLY multiplier drags the priced amount down
    to 29520 cents. The schedule's 30000-cent floor lifts it back to 30000 before
    apportionment, and only then does SESAC's 500 basis points reduce it to 1500
    cents — a fee far below the floor, and correctly so. The declaration mirrored
    the survey exactly, so both derivations agree and no delta is recorded.

    PRD §3.5: "The billable occupancy is the **larger** of the seating figure and
    the standing figure — never their sum."

    PRD §3.5: "The scaled amount is raised to the schedule's
    `min_annual_fee_cents` if it falls below it, and lowered to the schedule's
    `max_annual_fee_cents` if it rises above it."

    PRD §3.5: "Only now is the society's `repertoire_share_bp` applied: the
    clamped amount is multiplied by `repertoire_share_bp`, divided by 10000, and
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/annual_fee_occupancy_max_tier_and_clamp_interaction
    """
    built = _background_only_studio_license(api)
    licence = built["license"]

    # The clamped whole-repertoire price is 30000 cents; SESAC's 500 basis points
    # of it is exactly the 1500 cents the licence carries.
    assert_money(
        _STUDIO_SCHEDULE_MIN_CENTS * SHARE_SESAC_BP // 10000,
        _STUDIO_FEE_CENTS,
        "SESAC's share of the clamped price",
    )
    assert_money(licence["annual_fee_cents"], _STUDIO_FEE_CENTS, "annual_fee_cents")
    assert_money(
        licence["provisional_annual_fee_cents"],
        _STUDIO_FEE_CENTS,
        "provisional_annual_fee_cents",
    )
    assert_money(
        licence["verified_fee_delta_cents"], 0, "verified_fee_delta_cents"
    )
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_INVOICED)


def test_tier_clamp_apportioned_fee_is_what_the_studio_is_billed(api):
    """The studio is billed the apportioned 1500 cents, not the 30000-cent floor.

    Activation raises one initial assessment for the licence's own fee and moves
    the venue's outstanding balance by that amount. SESAC's 500 basis points of
    repertoire is also all the coverage the studio has, which reads back as a
    partially covered posture.

    PRD §3.5: "Note carefully that the fee **may legitimately end up below the
    schedule's `min_annual_fee_cents`** — a society controlling 2000 basis points
    of the repertoire bills a fifth of the clamped amount, and that is correct,
    not a floor violation."

    PRD §2.10: "`coverage_posture` is then read off that sum: `FULLY_COVERED`
    when `covered_share_bp` is at least 9500, `PARTIALLY_COVERED` when
    `covered_share_bp` is at least 1 and below 9500, and `UNCOVERED` when
    `covered_share_bp` is exactly 0."

    Design: Difficulty/combinatorial_formula/annual_fee_occupancy_max_tier_and_clamp_interaction
    """
    built = _background_only_studio_license(api)

    billed = read_rows(
        api.list_fee_assessments(
            admin_headers(), {"license_id": built["license"]["id"]}
        ),
        expected_total=1,
    )
    assert_assessment(
        billed[0],
        ASSESSMENT_KIND_INITIAL,
        _STUDIO_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    venue = venue_row(api, built["venue"]["id"])
    assert_money(
        venue["outstanding_balance_cents"],
        _STUDIO_FEE_CENTS,
        "outstanding_balance_cents",
    )
    assert_coverage(venue, SHARE_SESAC_BP, POSTURE_PARTIALLY_COVERED)
