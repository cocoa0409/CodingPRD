"""
Composed arithmetic: nested minima, pinned rounding order and pinned evaluation order.

Three calculations in this specification are only right if their internal structure is
right. The short-stay standard base is the smallest of three candidates, one of which is
itself a minimum of two, so an implementation that compares only two of the three still
produces a plausible number. The period ledger sums determination totals that were each
rounded when they were priced, so the order of rounding and summing is observable to the
cent. And the high-cost add-on is formed from a threshold that deliberately excludes the
add-on it is about to produce, so a circular reading converges on a different figure.

Each scenario below is built so that the wrong structure yields a specific wrong number,
and that wrong number is named in the assertions.
"""

from decimal import Decimal

from test_helpers import (
    DRG_573,
    FIXED_LOSS_AMOUNT_CENTS,
    OUTLIER_MARGINAL_COST_FACTOR,
    SSO_IPPS_PER_DIEM_FACTOR,
    ClinicalStatus,
    DeterminationStatus,
    DischargeDisposition,
    PaymentReviewStatus,
    PaymentVariant,
    PeriodStatus,
    ReviewOutcome,
    ReviewStatus,
    RiskBand,
    assert_cents,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    assert_stay_dimensions,
    clamped_score,
    day_count,
    discharge_payment_pct,
    fixtures,
    full_standard_amount_cents,
    outlier_payment_cents,
    raw_risk_score,
    risk_band_for,
    round_half_up_int,
    sso_threshold_days,
)

# DRG 207, the long-stay rate row: full standard 6,000,000 cents, threshold 25 days.
DRG_207_RATE = 4800000
DRG_207_WEIGHT = 1.25
DRG_207_ALOS = 30
DRG_207_IPPS_PER_DIEM = 90000
DRG_207_IPPS_FULL = 2400000

# DRG 573, the short-stay rate row: full standard 3,600,000 cents, threshold 10 days.
DRG_573_RATE = 4800000
DRG_573_WEIGHT = 0.75
DRG_573_ALOS = 13
DRG_573_IPPS_PER_DIEM = 400000
DRG_573_IPPS_FULL = 3400000


def _ltch_per_diem_component_cents(full_standard_cents, alos_days, covered_los_days):
    """The first candidate's second term: one rounding applied to the whole product."""
    return round_half_up_int(
        Decimal(full_standard_cents) / Decimal(alos_days) * Decimal(covered_los_days)
    )


def _ipps_per_diem_cap_cents(ipps_per_diem_cents, covered_los_days):
    """The second candidate: 120 percent of the IPPS per diem for the days delivered."""
    return round_half_up_int(
        Decimal(ipps_per_diem_cents)
        * Decimal(covered_los_days)
        * Decimal(str(SSO_IPPS_PER_DIEM_FACTOR))
    )


def _short_stay_standard_base_cents(
    full_standard_cents, alos_days, ipps_per_diem_cents, ipps_full_cents, covered_los_days
):
    """The smallest of the three short-stay candidates, first candidate nested."""
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


def _fixed_point_add_on_cents(base_payment_cents, estimated_cost_cents):
    """The forbidden circular reading, solved as a fixed point, for contrast only.

    Letting the add-on re-enter its own threshold gives a = 0.80 x (cost - base - fixed
    loss - a), whose solution is 0.80 x (cost - base - fixed loss) / 1.80.
    """
    factor = Decimal(str(OUTLIER_MARGINAL_COST_FACTOR))
    excess = Decimal(estimated_cost_cents - base_payment_cents - FIXED_LOSS_AMOUNT_CENTS)
    if excess <= 0:
        return 0
    return round_half_up_int(factor * excess / (Decimal(1) + factor))


# ── Scenario builders ───────────────────────────────────────────────────────
def _stay_of_exactly_the_threshold_length(api):
    """DRG 207 admitted 2026-07-07 and discharged at the clock epoch 2026-08-01.

    Twenty-five covered days is exactly the short-stay threshold, so the reduction applies
    and the standard base is the smallest of the three candidates. Five ICU days and a
    recorded prior acute discharge select the standard variant.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world, admitted_at="2026-07-07T00:00:00.000Z")
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.HOME_HEALTH,
        estimated_cost_cents=1000000,
        file_notes=False,
    )


def _two_short_standard_stays_finalized(api, finalize_headers=None):
    """Two DRG 573 stays of 5 and 6 covered days, both cleared and both finalized.

    Both are on the prolonged-mechanical-ventilation track with five ICU days, so both take
    the standard variant, and both carry an estimated cost of 500,000 cents, far below any
    fixed-loss threshold, so neither earns a high-cost add-on. Their per-diem products are
    the two figures whose rounding order the period ledger makes observable.
    """
    world = fixtures.build_world(api, drg_rate=dict(DRG_573))
    five_day = fixtures.admitted_stay(api, world, admitted_at="2026-07-27T00:00:00.000Z")
    second_patient = fixtures.add_patient(api)
    six_day = fixtures.admitted_stay(
        api,
        world,
        admitted_at="2026-07-26T00:00:00.000Z",
        patient_id=second_patient["id"],
        patient_version=second_patient["version"],
    )
    for admission in (five_day, six_day):
        fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=500000,
            file_notes=False,
        )
    for admission in (five_day, six_day):
        fixtures.resolve_review(
            api, admission.review_id, outcome=ReviewOutcome.CLEARED
        )
        admission.determination = fixtures.finalize(
            api, admission.determination_id, headers=finalize_headers
        )
    return world, five_day, six_day


def _high_cost_long_standard_stay(api):
    """DRG 207 admitted 2026-07-05, discharged 2026-08-14, estimated cost 12,000,000 cents.

    Forty covered days mean no short-stay reduction, so the standard base is the full
    6,000,000 cents, and the cost sits far above both variants' fixed-loss thresholds.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world, admitted_at="2026-07-05T00:00:00.000Z")
    fixtures.advance_clock(api, "2026-08-14T00:00:00Z")
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.ACUTE_TRANSFER,
        estimated_cost_cents=12000000,
        file_notes=False,
    )


class TestShortStayStandardBaseIsTheMinimumOfThreeCandidates:
    """The nested minimum inside the short-stay branch, where the third candidate wins."""

    def test_the_short_stay_standard_base_is_the_smallest_of_the_three_candidates(self, api):
        """The base lands on the IPPS-comparable full amount of 2,400,000 cents.

        With DRG 207's full standard amount of 6,000,000 cents over a 30-day average and a
        covered stay of exactly 25 days, the first candidate is the smaller of 6,000,000 and
        the LTCH per-diem product 6,000,000 / 30 x 25 = 5,000,000, so 5,000,000. The second
        candidate is 90,000 x 25 x 1.20 = 2,700,000. The third is the IPPS-comparable full
        amount, 2,400,000, unchanged. The minimum of the three is the third, so the standard
        base is 2,400,000 cents, the estimated cost of 1,000,000 is far below the 5,400,000
        fixed-loss threshold so no add-on applies, and the total is 2,400,000.

        PRD 3.7: "The first candidate is the smaller of `full_standard_amount_cents` and the LTCH per-diem component, where that component is `full_standard_amount_cents` divided by the DRG's `alos_days` and multiplied by the stay's `covered_los_days`, with exactly **one** rounding — half up to whole cents — applied to the whole product; the per-diem quotient must never be rounded before it is multiplied by the length of stay."
        PRD 3.7: "The standard base is the minimum of those three."

        Design: Difficulty/combinatorial_formula/sso_nested_min_of_three_candidates_selects_ipps_full
        """
        admission = _stay_of_exactly_the_threshold_length(api)
        determination = admission.determination

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        standard_base = _short_stay_standard_base_cents(
            full_standard, DRG_207_ALOS, DRG_207_IPPS_PER_DIEM, DRG_207_IPPS_FULL, 25
        )
        assert standard_base == 2400000
        site_neutral_base = _site_neutral_base_cents(DRG_207_IPPS_FULL, 1000000)

        assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assert_cents(determination, "full_standard_amount_cents", full_standard)
        assert_cents(determination, "base_payment_cents", standard_base)
        assert_cents(determination, "outlier_payment_cents", 0)
        assert_cents(determination, "total_payment_cents", standard_base)
        assert_cents(determination, "standard_variant_amount_cents", standard_base)
        assert_cents(determination, "site_neutral_variant_amount_cents", site_neutral_base)
        assert determination["standard_variant_amount_cents"] == 2400000
        assert determination["site_neutral_variant_amount_cents"] == 1000000
        assert_pct(
            determination,
            "discharge_payment_pct",
            discharge_payment_pct(standard_base, full_standard),
        )
        assert_pct(determination, "discharge_payment_pct", 40.00)

    def test_the_base_is_neither_the_per_diem_product_nor_the_hundred_and_twenty_percent_cap(
        self, api
    ):
        """Comparing only two of the three candidates would leave 5,000,000 or 2,700,000.

        The three candidates are genuinely distinct here — 5,000,000 from the LTCH per-diem
        comparison, 2,700,000 from the 120-percent IPPS per-diem cap and 2,400,000 from the
        IPPS-comparable full amount — and they are ordered so that only a comparison across
        all three reaches the right answer. An implementation that stops after the first two
        pays 2,700,000, and one that never applies the IPPS comparisons at all pays
        5,000,000; both are wrong by construction.

        PRD 3.7: "The second candidate is the DRG's `ipps_comparable_per_diem_cents` multiplied by the `covered_los_days` and then by 1.20, rounded half up to whole cents — that is, 120 percent of the IPPS-comparable per diem for the days actually delivered."
        PRD 3.7: "The third candidate is the DRG's `ipps_comparable_full_cents` unchanged."

        Design: Difficulty/combinatorial_formula/sso_nested_min_of_three_candidates_selects_ipps_full
        """
        admission = _stay_of_exactly_the_threshold_length(api)
        determination = admission.determination

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        per_diem_component = _ltch_per_diem_component_cents(full_standard, DRG_207_ALOS, 25)
        ipps_cap = _ipps_per_diem_cap_cents(DRG_207_IPPS_PER_DIEM, 25)
        assert per_diem_component == 5000000
        assert ipps_cap == 2700000
        assert DRG_207_IPPS_FULL == 2400000

        assert_cents(determination, "base_payment_cents", DRG_207_IPPS_FULL)
        assert determination["base_payment_cents"] != per_diem_component
        assert determination["base_payment_cents"] != ipps_cap
        assert determination["total_payment_cents"] != 2700000
        assert determination["total_payment_cents"] != 5000000
        assert_cents(determination, "standard_variant_amount_cents", DRG_207_IPPS_FULL)
        assert_cents(
            determination,
            "site_neutral_variant_amount_cents",
            _site_neutral_base_cents(DRG_207_IPPS_FULL, 1000000),
        )
        assert_cents(determination, "ipps_per_diem_used_cents", DRG_207_IPPS_PER_DIEM)
        assert_cents(determination, "ipps_full_used_cents", DRG_207_IPPS_FULL)

    def test_a_covered_stay_of_exactly_the_threshold_length_is_a_short_stay_outlier(self, api):
        """Twenty-five covered days against a threshold of 25 enters the reduced branch.

        Admission on 2026-07-07 and discharge at the logical clock's own epoch of
        2026-08-01 are 25 calendar days apart, and floor(0.8333333333333334 x 30) is also
        25. The comparison is inclusive, so equality applies the reduction — which is what
        puts the nested minimum in play at all rather than leaving the base at the full
        6,000,000 cents.

        PRD 3.6: "The precise fraction used for that multiplication is 0.8333333333333334."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."

        Design: Difficulty/combinatorial_formula/sso_nested_min_of_three_candidates_selects_ipps_full
        """
        admission = _stay_of_exactly_the_threshold_length(api)
        stay = admission.stay
        determination = admission.determination

        expected_los = day_count("2026-07-07T00:00:00.000Z", fixtures.clock_epoch())
        assert expected_los == 25
        assert_integer_field(stay, "covered_los_days", expected_los)
        assert_integer_field(stay, "sso_threshold_days", sso_threshold_days(DRG_207_ALOS))
        assert stay["sso_threshold_days"] == 25
        assert stay["covered_los_days"] == stay["sso_threshold_days"]
        assert stay["short_stay_outlier_applied"] is True
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)

        assert determination["short_stay_outlier_applied"] is True
        assert_integer_field(determination, "covered_los_days_used", 25)
        assert_integer_field(determination, "alos_days_used", DRG_207_ALOS)
        assert_cents(
            determination,
            "base_payment_cents",
            _short_stay_standard_base_cents(
                full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT),
                DRG_207_ALOS,
                DRG_207_IPPS_PER_DIEM,
                DRG_207_IPPS_FULL,
                25,
            ),
        )


class TestPeriodRollupRoundsEachDeterminationBeforeSumming:
    """Rounding happens at pricing time, so the period total is a sum of integers."""

    def test_each_determination_rounds_its_own_per_diem_product_to_whole_cents(
        self, api, second_analyst
    ):
        """The two stays are priced at 1,384,615 and 1,661,538 cents.

        DRG 573's full standard amount is 3,600,000 cents over a 13-day average. A covered
        stay of 5 days gives 3,600,000 / 13 x 5 = 1,384,615.3846..., rounded half up to
        1,384,615, and 6 days gives 3,600,000 / 13 x 6 = 1,661,538.4615..., rounded half up
        to 1,661,538. Both are below the 120-percent IPPS per-diem cap and below the
        IPPS-comparable full amount, so both are the winning candidate, and each figure is
        already a whole number of cents on the determination before the period sees it.

        PRD 2.5: "Each determination's `total_payment_cents` is rounded to whole cents when the determination is priced."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/period_rollup_rounds_per_determination_then_sums
        """
        _, five_day, six_day = _two_short_standard_stays_finalized(
            api, finalize_headers=second_analyst
        )

        full_standard = full_standard_amount_cents(DRG_573_RATE, DRG_573_WEIGHT)
        assert full_standard == 3600000
        expected = {}
        for covered_days, admission in ((5, five_day), (6, six_day)):
            expected[covered_days] = _short_stay_standard_base_cents(
                full_standard,
                DRG_573_ALOS,
                DRG_573_IPPS_PER_DIEM,
                DRG_573_IPPS_FULL,
                covered_days,
            )
            determination = admission.determination
            assert_integer_field(determination, "covered_los_days_used", covered_days)
            assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
            assert determination["short_stay_outlier_applied"] is True
            assert_cents(determination, "full_standard_amount_cents", full_standard)
            assert_cents(determination, "base_payment_cents", expected[covered_days])
            assert_cents(determination, "outlier_payment_cents", 0)
            assert_cents(determination, "total_payment_cents", expected[covered_days])
            assert_cents(
                determination, "standard_variant_amount_cents", expected[covered_days]
            )
            assert_cents(
                determination,
                "site_neutral_variant_amount_cents",
                _site_neutral_base_cents(DRG_573_IPPS_FULL, 500000),
            )
            assert determination["site_neutral_variant_amount_cents"] == 500000
            assert_pct(
                determination,
                "discharge_payment_pct",
                discharge_payment_pct(expected[covered_days], full_standard),
            )

        assert expected[5] == 1384615
        assert expected[6] == 1661538
        assert_pct(five_day.determination, "discharge_payment_pct", 38.46)
        assert_pct(six_day.determination, "discharge_payment_pct", 46.15)
        assert five_day.determination["status"] == DeterminationStatus.FINAL
        assert six_day.determination["status"] == DeterminationStatus.FINAL

    def test_the_period_total_is_the_sum_of_the_already_rounded_determination_totals(
        self, api, second_analyst
    ):
        """The period holds 3,046,153 cents, not the 3,046,154 a late rounding would give.

        Finalizing each determination adds its own already-rounded total to the period, so
        the ledger reads 1,384,615 + 1,661,538 = 3,046,153 cents across two finalized
        determinations. Re-deriving the same money from the unrounded per-diem products —
        3,600,000 / 13 x 11 = 3,046,153.846..., rounded once at the end — would post
        3,046,154 instead, one cent too much. The two orderings differ observably, and only
        the per-determination rounding is correct.

        PRD 2.5: "A period's `total_payment_cents` is then the sum of those already-rounded integers — never a re-derivation from unrounded per-diem products with a single rounding applied at the end."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Difficulty/combinatorial_formula/period_rollup_rounds_per_determination_then_sums
        """
        world, five_day, six_day = _two_short_standard_stays_finalized(
            api, finalize_headers=second_analyst
        )

        rounded_sum = (
            five_day.determination["total_payment_cents"]
            + six_day.determination["total_payment_cents"]
        )
        assert rounded_sum == 3046153
        late_rounding = round_half_up_int(
            Decimal(full_standard_amount_cents(DRG_573_RATE, DRG_573_WEIGHT))
            / Decimal(DRG_573_ALOS)
            * Decimal(11)
        )
        assert late_rounding == 3046154

        period = fixtures.read_period(api, world.period_id)
        assert_period_ledger(period, rounded_sum, 2)
        assert period["total_payment_cents"] == 3046153
        assert period["total_payment_cents"] != late_rounding
        assert period["status"] == PeriodStatus.OPEN

        for admission in (five_day, six_day):
            stay = fixtures.read_stay(api, admission.stay_id)
            assert_stay_dimensions(
                stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.FINALIZED
            )
            review = fixtures.read_review(api, admission.review_id)
            assert review["status"] == ReviewStatus.CLEARED
            assert review["risk_band"] == RiskBand.MODERATE
            assert_integer_field(
                review,
                "as_documented_score",
                clamped_score(raw_risk_score(4, 1, 1, 0, 0)),
            )
            assert review["as_documented_score"] == 67
            assert risk_band_for(review["as_documented_score"]) == RiskBand.MODERATE


class TestHighCostOutlierThresholdExcludesItsOwnAddOn:
    """The add-on is formed from a threshold computed before the add-on exists."""

    def test_the_add_on_is_eighty_percent_of_the_cost_above_the_base_plus_fixed_loss(
        self, api
    ):
        """A base of 6,000,000 against a cost of 12,000,000 earns 2,400,000 cents.

        Forty covered days clear DRG 207's 25-day short-stay threshold, so the standard base
        stays at the full 6,000,000 cents. The threshold is then 6,000,000 + 3,000,000 =
        9,000,000, the excess is 12,000,000 - 9,000,000 = 3,000,000, and the add-on is
        0.80 x 3,000,000 = 2,400,000 cents exactly. The total payable is 6,000,000 +
        2,400,000 = 8,400,000 cents.

        PRD 3.7: "First, a threshold is formed as the variant's base payment plus a fixed-loss amount of 3,000,000 cents (30,000 dollars)."
        PRD 3.7: "Third, if the excess is less than or equal to zero the add-on is 0; otherwise the add-on is 0.80 multiplied by the excess, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/high_cost_outlier_threshold_excludes_its_own_add_on
        """
        admission = _high_cost_long_standard_stay(api)
        stay = admission.stay
        determination = admission.determination

        covered_days = day_count("2026-07-05T00:00:00.000Z", "2026-08-14T00:00:00.000Z")
        assert covered_days == 40
        assert_integer_field(stay, "covered_los_days", covered_days)
        assert_integer_field(stay, "sso_threshold_days", sso_threshold_days(DRG_207_ALOS))
        assert stay["covered_los_days"] > stay["sso_threshold_days"]
        assert stay["short_stay_outlier_applied"] is False

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        add_on = outlier_payment_cents(full_standard, 12000000)
        assert add_on == 2400000

        assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assert determination["short_stay_outlier_applied"] is False
        assert_cents(determination, "full_standard_amount_cents", full_standard)
        assert_cents(determination, "base_payment_cents", full_standard)
        assert_cents(determination, "outlier_payment_cents", add_on)
        assert_cents(determination, "total_payment_cents", full_standard + add_on)
        assert determination["total_payment_cents"] == 8400000
        assert_cents(
            determination, "standard_variant_amount_cents", full_standard + add_on
        )
        assert_pct(
            determination,
            "discharge_payment_pct",
            discharge_payment_pct(full_standard, full_standard),
        )
        assert_pct(determination, "discharge_payment_pct", 100.00)

    def test_the_add_on_never_re_enters_its_own_threshold(self, api):
        """The circular reading would pay 1,333,333 cents; only 2,400,000 is correct.

        Reading the threshold as base plus fixed loss plus the add-on itself makes the
        add-on its own input: a = 0.80 x (12,000,000 - 6,000,000 - 3,000,000 - a), whose
        fixed point is 2,400,000 / 1.80 = 1,333,333.33..., or 1,333,333 cents. The
        specification fixes the evaluation order so the threshold is complete before the
        add-on is formed, which is why the excess is a flat 3,000,000 and the add-on is
        1,066,667 cents larger than the circular figure.

        PRD 3.7: "The add-on must never re-enter its own threshold: reading the threshold as base plus add-on plus fixed loss and solving it as a fixed point is forbidden."
        PRD 3.7: "For a base of 6,000,000 cents against an estimated cost of 12,000,000 cents, the pinned order yields an add-on of 2,400,000 cents; the fixed-point reading would yield 1,333,333, and only 2,400,000 is correct."

        Design: Difficulty/combinatorial_formula/high_cost_outlier_threshold_excludes_its_own_add_on
        """
        admission = _high_cost_long_standard_stay(api)
        determination = admission.determination

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        pinned = outlier_payment_cents(full_standard, 12000000)
        circular = _fixed_point_add_on_cents(full_standard, 12000000)
        assert pinned == 2400000
        assert circular == 1333333

        assert_cents(determination, "outlier_payment_cents", pinned)
        assert determination["outlier_payment_cents"] != circular
        assert determination["outlier_payment_cents"] != 1333333
        assert determination["total_payment_cents"] != full_standard + circular
        assert_cents(determination, "total_payment_cents", full_standard + pinned)
        assert 12000000 - full_standard - FIXED_LOSS_AMOUNT_CENTS == 3000000
        assert_cents(determination, "outlier_payment_cents", 2400000)
        assert determination["status"] == DeterminationStatus.DRAFT

    def test_each_variant_forms_its_own_threshold_from_its_own_base(self, api):
        """The unpaid site-neutral variant reaches 7,680,000 cents on a base of 2,400,000.

        Both variants are priced on the same stay, and each one's threshold is its own base
        plus the same 3,000,000 fixed loss. The site-neutral base is the smaller of the
        IPPS-comparable full amount and the estimated cost, so 2,400,000; its threshold is
        5,400,000, its excess is 6,600,000, and its add-on is 0.80 x 6,600,000 = 5,280,000,
        for a stored variant amount of 7,680,000 cents. Borrowing the standard variant's
        threshold would understate it, and the two amounts are deliberately different.

        PRD 3.7: "Second, an excess is formed as the stay's `estimated_cost_cents`, with null treated as 0, minus that threshold."
        PRD 3.7: "`site_neutral_variant_amount_cents` is the site-neutral base plus the add-on computed from the site-neutral base."

        Design: Difficulty/combinatorial_formula/high_cost_outlier_threshold_excludes_its_own_add_on
        """
        admission = _high_cost_long_standard_stay(api)
        determination = admission.determination

        site_neutral_base = _site_neutral_base_cents(DRG_207_IPPS_FULL, 12000000)
        assert site_neutral_base == 2400000
        site_neutral_add_on = outlier_payment_cents(site_neutral_base, 12000000)
        assert site_neutral_add_on == 5280000
        site_neutral_total = site_neutral_base + site_neutral_add_on

        full_standard = full_standard_amount_cents(DRG_207_RATE, DRG_207_WEIGHT)
        standard_total = full_standard + outlier_payment_cents(full_standard, 12000000)

        assert_cents(
            determination, "site_neutral_variant_amount_cents", site_neutral_total
        )
        assert determination["site_neutral_variant_amount_cents"] == 7680000
        assert_cents(determination, "standard_variant_amount_cents", standard_total)
        assert (
            determination["site_neutral_variant_amount_cents"]
            != determination["standard_variant_amount_cents"]
        )
        assert_cents(determination, "total_payment_cents", standard_total)
        assert determination["total_payment_cents"] > full_standard

        review = fixtures.sole_review(api, admission.stay_id)
        expected_score = clamped_score(raw_risk_score(4, 1, 0, 0, 10))
        assert expected_score == 52
        assert_integer_field(review, "as_documented_score", expected_score)
        assert review["risk_band"] == risk_band_for(expected_score)
        assert review["risk_band"] == RiskBand.MODERATE
