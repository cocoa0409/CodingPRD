"""
Dual-variant arithmetic: two numbers derived from one row.

Two places in this specification compute the same subject twice and keep both readings.
A `PaymentDetermination` prices one discharged stay under both the standard MS-LTC-DRG
system and the site-neutral system, storing `standard_variant_amount_cents` and
`site_neutral_variant_amount_cents` together and paying only one of them. A
`DenialRiskReview` reads one chart twice, as `as_documented_score` and as
`query_adjusted_score`, and the second reading is what lets a chart fall out of the
highest risk band once a physician answers.

Both scenarios are pinned to the cent and to the point.
"""

from decimal import Decimal

from test_helpers import (
    DRG_573,
    FIXED_LOSS_AMOUNT_CENTS,
    SSO_IPPS_PER_DIEM_FACTOR,
    SYSTEM_ACTOR,
    ClinicalStatus,
    DischargeDisposition,
    PaymentReviewStatus,
    PaymentVariant,
    QualifyingTrack,
    QueryStatus,
    QueryType,
    ReviewStatus,
    RiskBand,
    assert_cents,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_stay_dimensions,
    assert_unset,
    clamped_score,
    day_count,
    discharge_payment_pct,
    factories,
    fixtures,
    full_standard_amount_cents,
    outlier_payment_cents,
    query_adjusted_score,
    raw_risk_score,
    risk_band_for,
    round_half_up_int,
    sso_threshold_days,
)

# ── The two reference rate rows these scenarios price against ────────────────
# DRG 207, the long-stay rate: 4,800,000 cents at weight 1.25 over a 30-day average.
DRG_207_RATE = 4800000
DRG_207_WEIGHT = 1.25
DRG_207_ALOS = 30
DRG_207_IPPS_PER_DIEM = 90000
DRG_207_IPPS_FULL = 2400000

# DRG 573, the short-stay rate: 4,800,000 cents at weight 0.75 over a 13-day average.
DRG_573_RATE = 4800000
DRG_573_WEIGHT = 0.75
DRG_573_ALOS = 13
DRG_573_IPPS_PER_DIEM = 400000
DRG_573_IPPS_FULL = 3400000


def _ltch_per_diem_component_cents(full_standard_cents, alos_days, covered_los_days):
    """The full amount divided by the average stay and multiplied by the days delivered.

    The quotient is never rounded on its own: exactly one half-up rounding is applied to
    the whole product.
    """
    return round_half_up_int(
        Decimal(full_standard_cents) / Decimal(alos_days) * Decimal(covered_los_days)
    )


def _ipps_per_diem_cap_cents(ipps_per_diem_cents, covered_los_days):
    """120 percent of the IPPS-comparable per diem for the days actually delivered."""
    return round_half_up_int(
        Decimal(ipps_per_diem_cents)
        * Decimal(covered_los_days)
        * Decimal(str(SSO_IPPS_PER_DIEM_FACTOR))
    )


def _short_stay_standard_base_cents(
    full_standard_cents, alos_days, ipps_per_diem_cents, ipps_full_cents, covered_los_days
):
    """The smallest of the three short-stay candidates."""
    first = min(
        full_standard_cents,
        _ltch_per_diem_component_cents(full_standard_cents, alos_days, covered_los_days),
    )
    second = _ipps_per_diem_cap_cents(ipps_per_diem_cents, covered_los_days)
    return min(first, second, ipps_full_cents)


def _site_neutral_base_cents(ipps_full_cents, estimated_cost_cents):
    """The smaller of the IPPS-comparable full amount and the stay's estimated cost."""
    cost = 0 if estimated_cost_cents is None else estimated_cost_cents
    return min(ipps_full_cents, cost)


# ── Scenario builders ───────────────────────────────────────────────────────
def _long_standard_stay_at_high_cost(api):
    """DRG 207 admitted 2026-07-05, discharged 2026-08-14 at an estimated 12,000,000 cents.

    Forty covered days clear the 25-day short-stay threshold, five ICU days and a recorded
    prior acute discharge select the standard variant, and the cost is high enough that
    both variants earn a high-cost add-on.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world, admitted_at="2026-07-05T00:00:00.000Z")
    fixtures.advance_clock(api, "2026-08-14T00:00:00Z")
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.SNF,
        estimated_cost_cents=12000000,
        file_notes=False,
    )


def _short_site_neutral_stay_with_no_documentation(api):
    """DRG 573 on the complex-wound track with one ICU day and not a single note filed.

    Admitted 2026-07-24 and discharged at the clock epoch 2026-08-01, so eight covered
    days sit inside the 10-day short-stay threshold. One ICU day, no weaning plan and a
    recorded prior acute discharge together force the site-neutral variant.
    """
    world = fixtures.build_world(api, drg_rate=dict(DRG_573))
    return fixtures.discharged_stay(
        api,
        world,
        clinicals=factories.WOUND_CLINICALS,
        expected_track=QualifyingTrack.COMPLEX_WOUND,
        admitted_at="2026-07-24T00:00:00.000Z",
        discharge_disposition=DischargeDisposition.HOME,
        estimated_cost_cents=1500000,
        file_notes=False,
    )


class TestPaymentVariantStandardVersusSiteNeutralOnOneDetermination:
    """One discharged stay, priced under both payment systems on a single row."""

    def test_both_variant_amounts_are_stored_and_the_standard_one_is_selected(self, api):
        """The determination carries 8,400,000 and 7,680,000 at once and pays the first.

        DRG 207 gives a full standard amount of 4,800,000 x 1.25 = 6,000,000 cents. Forty
        covered days leave the short-stay reduction out of play, so the standard base is
        that full amount and its add-on is 0.80 x (12,000,000 - 9,000,000) = 2,400,000,
        making the standard variant 8,400,000. The site-neutral base is instead the smaller
        of the IPPS-comparable full amount and the estimated cost, so 2,400,000, and its
        own add-on of 0.80 x (12,000,000 - 5,400,000) = 5,280,000 brings the site-neutral
        variant to 7,680,000. The referral records a prior acute discharge and five ICU
        days, which selects the standard variant, and the amount actually paid is therefore
        8,400,000 while 7,680,000 remains readable on the same row.

        PRD 3.7: "When the referral records a prior acute discharge and at least one intensity criterion holds, `payment_variant` is `STANDARD_LTCH_PPS`; in every other case it is `SITE_NEUTRAL`."
        PRD 3.7: "Both are stored on every determination regardless of which variant was selected."

        Design: Difficulty/dual_variant_calc/payment_variant_standard_vs_site_neutral_on_one_determination
        """
        admission = _long_standard_stay_at_high_cost(api)
        determination = admission.determination

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        standard_base = full_standard
        site_neutral_base = _site_neutral_base_cents(DRG_207_IPPS_FULL, 12000000)
        standard_variant = standard_base + outlier_payment_cents(standard_base, 12000000)
        site_neutral_variant = site_neutral_base + outlier_payment_cents(
            site_neutral_base, 12000000
        )

        assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assert_cents(determination, "full_standard_amount_cents", full_standard)
        assert_cents(determination, "standard_variant_amount_cents", standard_variant)
        assert_cents(determination, "site_neutral_variant_amount_cents", site_neutral_variant)
        assert_cents(determination, "base_payment_cents", standard_base)
        assert_cents(determination, "outlier_payment_cents", 2400000)
        assert_cents(determination, "total_payment_cents", standard_variant)
        assert_pct(
            determination,
            "discharge_payment_pct",
            discharge_payment_pct(standard_base, full_standard),
        )

        assert determination["standard_variant_amount_cents"] == 8400000
        assert determination["site_neutral_variant_amount_cents"] == 7680000
        assert (
            determination["standard_variant_amount_cents"]
            != determination["site_neutral_variant_amount_cents"]
        ), "the two payment systems must not collapse onto one number for this stay"

    def test_forty_covered_days_clear_the_twenty_five_day_short_stay_threshold(self, api):
        """Covered length of stay 40 against a threshold of 25 leaves the base undiminished.

        Admission on 2026-07-05 and discharge on 2026-08-14 are 40 calendar days apart, and
        DRG 207's 30-day average stay puts the short-stay threshold at floor(0.8333333333333334
        x 30) = 25 days. Because 40 exceeds 25 the stay is not a short-stay outlier, which is
        what leaves the standard base at the full 6,000,000 cents rather than at the smallest
        of the three reduced candidates.

        PRD 3.6: "Alongside it, `sso_threshold_days` is computed as five-sixths of the `alos_days` of the DRG in force, rounded **down** to a whole number and never rounded to nearest."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."
        PRD 3.7: "When the stay's `short_stay_outlier_applied` is false, the standard base is simply `full_standard_amount_cents`."

        Design: Difficulty/dual_variant_calc/payment_variant_standard_vs_site_neutral_on_one_determination
        """
        admission = _long_standard_stay_at_high_cost(api)
        stay = admission.stay
        determination = admission.determination

        expected_los = day_count("2026-07-05T00:00:00.000Z", "2026-08-14T00:00:00Z")
        assert expected_los == 40
        assert_integer_field(stay, "covered_los_days", expected_los)
        assert_integer_field(stay, "sso_threshold_days", sso_threshold_days(DRG_207_ALOS))
        assert stay["sso_threshold_days"] == 25
        assert stay["short_stay_outlier_applied"] is False
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)

        assert determination["short_stay_outlier_applied"] is False
        assert_integer_field(determination, "covered_los_days_used", expected_los)
        assert_cents(
            determination,
            "base_payment_cents",
            full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT),
        )
        assert_pct(stay, "discharge_payment_pct", 100.00)
        assert_pct(determination, "discharge_payment_pct", 100.00)

    def test_the_unpaid_site_neutral_variant_carries_its_own_base_and_its_own_add_on(self, api):
        """The stored site-neutral amount is built from 2,400,000, not from the standard base.

        The site-neutral system ignores the LTCH per-diem and the 120-percent IPPS cap and
        takes the smaller of the IPPS-comparable full amount, 2,400,000 cents, and the
        estimated cost of 12,000,000, so its base is 2,400,000. Its add-on is computed from
        that base and nothing else: a threshold of 5,400,000, an excess of 6,600,000 and
        0.80 of that excess is 5,280,000, giving 7,680,000. Reusing the standard base's
        add-on of 2,400,000 here would store 4,800,000 instead, which is why the two add-ons
        have to be computed separately.

        PRD 3.7: "The site-neutral base is the smaller of the DRG's `ipps_comparable_full_cents` and the stay's `estimated_cost_cents`, with a null `estimated_cost_cents` treated as 0."
        PRD 3.7: "`site_neutral_variant_amount_cents` is the site-neutral base plus the add-on computed from the site-neutral base."

        Design: Difficulty/dual_variant_calc/payment_variant_standard_vs_site_neutral_on_one_determination
        """
        admission = _long_standard_stay_at_high_cost(api)
        determination = admission.determination

        site_neutral_base = _site_neutral_base_cents(DRG_207_IPPS_FULL, 12000000)
        assert site_neutral_base == 2400000
        site_neutral_add_on = outlier_payment_cents(site_neutral_base, 12000000)
        assert site_neutral_add_on == 5280000
        assert site_neutral_base + FIXED_LOSS_AMOUNT_CENTS == 5400000

        assert_cents(
            determination,
            "site_neutral_variant_amount_cents",
            site_neutral_base + site_neutral_add_on,
        )
        assert_cents(determination, "site_neutral_variant_amount_cents", 7680000)
        assert_cents(determination, "ipps_full_used_cents", DRG_207_IPPS_FULL)
        # The paid figures still come from the standard base alone.
        assert_cents(determination, "outlier_payment_cents", 2400000)
        assert_cents(determination, "total_payment_cents", 8400000)
        assert_cents(determination, "standard_variant_amount_cents", 8400000)


class TestDenialRiskAsDocumentedVersusQueryAdjustedBandDrop:
    """One chart read twice: as filed, and again after a physician answers."""

    def test_the_cascade_scores_the_undocumented_chart_at_seventy_seven_and_auto_issues_a_query(
        self, api
    ):
        """As filed the chart scores 77, which is HIGH, and the cascade issues one query.

        Nothing at all is documented on this stay: none of the four mandatory disciplines has
        a note, so the missing-discipline count is 4 and contributes 8 x 4 = 32 points. There
        is no weaning plan, which is itself the weaning gap and adds 15. Eight covered days
        inside the 10-day short-stay threshold add 20, and the site-neutral variant adds 10.
        The covered stay is shorter than DRG 573's 13-day average, so the length-of-stay
        excess floors at zero and contributes nothing. The raw total is therefore 77, and
        because no query has been answered yet the query-adjusted reading is still null and
        the effective score is the as-documented one. Seventy-seven is at least 70, so the
        band is HIGH and the fourth level of the cascade fires.

        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."
        PRD 3.8: "`query_adjusted_score` is null until a rescore observes a non-zero `answered_query_count`."
        PRD 3.6: "*Level four* follows only when that review's `risk_band` came out `HIGH`: a `DocumentationQuery` with `query_type` `IDT_PARTICIPATION` is auto-issued against the review with `issued_by_user_id` set to the literal `SYSTEM`, and the review moves `OPEN → QUERIES_ISSUED`."

        Design: Difficulty/dual_variant_calc/denial_risk_as_documented_vs_query_adjusted_band_drop
        """
        admission = _short_site_neutral_stay_with_no_documentation(api)
        review = admission.review
        determination = admission.determination

        raw = raw_risk_score(
            missing_discipline_count=4,
            weaning_gap=1,
            sso_flag=1,
            site_neutral_flag=1,
            los_excess_days=0,
        )
        assert clamped_score(raw) == 77

        assert_integer_field(review, "missing_discipline_count", 4)
        assert_integer_field(review, "answered_query_count", 0)
        assert_integer_field(review, "as_documented_score", clamped_score(raw))
        assert_unset(review, "query_adjusted_score")
        assert_integer_field(review, "effective_score", clamped_score(raw))
        assert review["risk_band"] == RiskBand.HIGH
        assert review["risk_band"] == risk_band_for(77)
        assert review["status"] == ReviewStatus.QUERIES_ISSUED
        assert review["opened_by_user_id"] is not None

        assert len(admission.queries) == 1, (
            "the HIGH band auto-issues exactly one query, found {}".format(
                len(admission.queries)
            )
        )
        query = admission.queries[0]
        assert query["query_type"] == QueryType.IDT_PARTICIPATION
        assert query["issued_by_user_id"] == SYSTEM_ACTOR
        assert query["status"] == QueryStatus.ISSUED

        # The site-neutral flag that contributes 10 points comes off this determination,
        # which stores both variant amounts whichever one it selected.
        full_standard = full_standard_amount_cents(DRG_573_RATE, DRG_573_WEIGHT)
        standard_variant = _short_stay_standard_base_cents(
            full_standard,
            DRG_573_ALOS,
            DRG_573_IPPS_PER_DIEM,
            DRG_573_IPPS_FULL,
            8,
        )
        site_neutral_variant = _site_neutral_base_cents(DRG_573_IPPS_FULL, 1500000)
        assert determination["payment_variant"] == PaymentVariant.SITE_NEUTRAL
        assert determination["short_stay_outlier_applied"] is True
        assert_cents(determination, "full_standard_amount_cents", full_standard)
        assert_cents(determination, "standard_variant_amount_cents", standard_variant)
        assert_cents(determination, "site_neutral_variant_amount_cents", site_neutral_variant)
        assert_cents(determination, "base_payment_cents", site_neutral_variant)
        assert_cents(determination, "total_payment_cents", site_neutral_variant)

    def test_one_answered_query_drops_the_effective_score_to_sixty_five_and_the_band_to_moderate(
        self, api
    ):
        """The same chart data reads 77 as documented and 65 once one query is answered.

        The chart itself does not change when the physician answers: the four disciplines are
        still absent, there is still no weaning plan, the stay is still a short-stay outlier
        and still site-neutral, so the raw total is still 77 and the as-documented score
        stays at 77. The query-adjusted reading starts from that same raw total and subtracts
        12 points for the one answered query, landing on 65. Because the answered-query count
        is now greater than zero the effective score is the query-adjusted one, and 65 is at
        least 40 but below 70, so the band falls from HIGH to MODERATE.

        PRD 3.8: "The `query_adjusted_score` starts from the same raw total, subtracts 12 points for each answered query, then rounds half up and clamps into the same 0-through-100 range."
        PRD 3.8: "The review's `effective_score` is the `query_adjusted_score` when `answered_query_count` is greater than 0, and the `as_documented_score` otherwise."
        PRD 3.8: "`risk_band` is `HIGH` when `effective_score` is at least 70, `MODERATE` when `effective_score` is at least 40 but below 70, and `LOW` below 40."

        Design: Difficulty/dual_variant_calc/denial_risk_as_documented_vs_query_adjusted_band_drop
        """
        admission = _short_site_neutral_stay_with_no_documentation(api)
        query = admission.queries[0]
        fixtures.answer_query(api, query["id"], admission.world.physician_headers)

        review = fixtures.read_review(api, admission.review_id)
        raw = raw_risk_score(
            missing_discipline_count=4,
            weaning_gap=1,
            sso_flag=1,
            site_neutral_flag=1,
            los_excess_days=0,
        )

        assert_integer_field(review, "as_documented_score", clamped_score(raw))
        assert_integer_field(review, "query_adjusted_score", query_adjusted_score(raw, 1))
        assert_integer_field(review, "effective_score", query_adjusted_score(raw, 1))
        assert review["as_documented_score"] == 77
        assert review["query_adjusted_score"] == 65
        assert review["effective_score"] == 65
        assert review["risk_band"] == RiskBand.MODERATE
        assert review["risk_band"] == risk_band_for(65)
        assert_integer_field(review, "answered_query_count", 1)
        assert_integer_field(review, "missing_discipline_count", 4)

        # The money on the row is untouched by the documentation credit, and both variants
        # are still readable side by side.
        determination = fixtures.read_determination(api, admission.determination_id)
        full_standard = full_standard_amount_cents(DRG_573_RATE, DRG_573_WEIGHT)
        assert_cents(
            determination,
            "standard_variant_amount_cents",
            _short_stay_standard_base_cents(
                full_standard, DRG_573_ALOS, DRG_573_IPPS_PER_DIEM, DRG_573_IPPS_FULL, 8
            ),
        )
        assert_cents(
            determination,
            "site_neutral_variant_amount_cents",
            _site_neutral_base_cents(DRG_573_IPPS_FULL, 1500000),
        )
        assert_pct(
            determination,
            "discharge_payment_pct",
            discharge_payment_pct(
                _site_neutral_base_cents(DRG_573_IPPS_FULL, 1500000), full_standard
            ),
        )

    def test_answering_the_auto_issued_query_stamps_the_physician_and_moves_it_to_answered(
        self, api
    ):
        """The credit that lowers the second reading is earned by an ISSUED to ANSWERED move.

        The query the cascade issued carries `issued_by_user_id` `SYSTEM`, and the attending
        physician who answers it is stamped into `answered_by_physician_id` from that
        request's own `X-User-ID`. The answer is recorded at the logical instant the clock
        holds, which is the epoch here because nothing has advanced it, and the query lands
        in `ANSWERED` — the one status that earns the twelve-point credit alongside `CLOSED`.

        PRD 3.8: "On success the query moves `ISSUED → ANSWERED`, `answered_at` is stamped from the logical clock, `answered_by_physician_id` records the acting physician's `X-User-ID`, the review's `answered_query_count` increases by 1, and the denial-risk score is recomputed, so the `risk_band` may fall."
        PRD 3.8: "The count of answered queries, `answered_query_count`, counts the review's `DocumentationQuery` rows whose `status` is `ANSWERED` or `CLOSED`; queries in `ISSUED`, `EXPIRED` or `VOIDED` earn no credit."

        Design: Difficulty/dual_variant_calc/denial_risk_as_documented_vs_query_adjusted_band_drop
        """
        admission = _short_site_neutral_stay_with_no_documentation(api)
        issued = admission.queries[0]
        assert issued["status"] == QueryStatus.ISSUED
        assert issued["issued_by_user_id"] == SYSTEM_ACTOR

        fixtures.answer_query(api, issued["id"], admission.world.physician_headers)
        answered = fixtures.read_query(api, issued["id"])

        assert answered["status"] == QueryStatus.ANSWERED
        assert answered["answered_by_physician_id"] == admission.world.physician_id
        assert answered["issued_by_user_id"] == SYSTEM_ACTOR
        assert answered["response_text"] is not None
        assert_instant_equals(
            answered["answered_at"], fixtures.clock_epoch(), "answered_at"
        )
        assert answered["closed_by_user_id"] is None
