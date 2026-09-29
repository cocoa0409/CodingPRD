"""
Arithmetic of the LTCH admission and length-of-stay service.

Every test in this module pins a number: a covered length of stay that has to net out
the days a patient spent elsewhere, a denial-risk score that counts only the four
mandatory disciplines and only the queries that came back, a referral-mix threshold
chosen from two constants, a per-diem product that has to round half up exactly once, an
interruption window judged inclusively at its last day, a cumulative ventilator-hour
counter that forgets nothing, a payment variant selected without a weaning plan, and a
period ledger that admits only final determinations.

The expected figures are derived here through the same named calculators and constants
the specification names, so a scenario reads as its arithmetic rather than as a table of
magic integers.
"""

from decimal import Decimal

import pytest

from test_helpers import (
    ANALYST_2_ID,
    ANALYST_3_ID,
    ANSWERED_QUERY_CREDIT,
    BASE_REFERRAL_THRESHOLD_PCT,
    CLOCK_EPOCH,
    DEFAULT_PROTOCOL_LABEL,
    DRG_207,
    DRG_207_FULL_STANDARD_CENTS,
    DRG_207_SSO_THRESHOLD_DAYS,
    DRG_573,
    DRG_573_FULL_STANDARD_CENTS,
    DRG_573_SSO_THRESHOLD_DAYS,
    EXPANDED_REFERRAL_THRESHOLD_PCT,
    INTERRUPTION_WINDOW_DAYS,
    MIN_ADMISSIONS_FOR_MONITORING,
    SSO_IPPS_PER_DIEM_FACTOR,
    SYSTEM_ACTOR,
    VENT_HOURS_SITE_NEUTRAL_MIN,
    ClinicalStatus,
    DeterminationStatus,
    Discipline,
    DischargeDisposition,
    HospitalType,
    InterruptionDestination,
    InterruptionStatus,
    MonitoringState,
    PaymentReviewStatus,
    PaymentVariant,
    QualifyingTrack,
    QueryStatus,
    QueryType,
    ReviewOutcome,
    ReviewStatus,
    RiskBand,
    WeaningPlanStatus,
    assert_cents,
    assert_hospital_posture,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    assert_stay_dimensions,
    assert_unset,
    assert_vent_hours,
    clamped_score,
    day_count,
    discharge_payment_pct,
    expected_share_pct,
    factories,
    fixtures,
    full_standard_amount_cents,
    outlier_payment_cents,
    query_adjusted_score,
    raw_risk_score,
    risk_band_for,
    round_half_up_int,
    sso_threshold_days,
    validate_paginated,
)

# The instants the arithmetic scenarios move the logical clock through.
LEFT_AT = "2026-08-06T00:00:00Z"
RETURNED_AT_INSIDE_WINDOW = "2026-08-10T00:00:00Z"
DISCHARGE_AT_LATE_AUGUST = "2026-08-25T00:00:00Z"
DISCHARGE_AT_MID_AUGUST = "2026-08-15T00:00:00Z"
DISCHARGE_AT_08_08 = "2026-08-08T00:00:00Z"
DISCHARGE_AT_08_20 = "2026-08-20T00:00:00Z"
NINE_DAYS_AFTER_EPOCH = "2026-08-10T00:00:00Z"
TEN_DAYS_AFTER_EPOCH = "2026-08-11T00:00:00Z"

ORDINARY_COST_CENTS = 1000000
WOUND_COST_CENTS = 4000000


# ── The three short-stay-outlier candidates, each computed the pinned way ──
def _ltch_per_diem_component_cents(full_standard_cents, alos_days, covered_los_days):
    """The full amount divided by the average stay and multiplied by the days delivered.

    Exactly one rounding is applied, to the whole product, so the quotient keeps its
    fractional cents until the multiplication is done.
    """
    return round_half_up_int(
        Decimal(full_standard_cents) * Decimal(covered_los_days) / Decimal(alos_days)
    )


def _ipps_per_diem_candidate_cents(ipps_per_diem_cents, covered_los_days):
    """120 percent of the IPPS-comparable per diem for the days actually delivered."""
    return round_half_up_int(
        Decimal(ipps_per_diem_cents)
        * Decimal(covered_los_days)
        * Decimal(str(SSO_IPPS_PER_DIEM_FACTOR))
    )


def _standard_base_cents(drg, covered_los_days, short_stay_outlier_applied):
    """The standard-variant base: the full amount, or the smallest of three candidates."""
    full = full_standard_amount_cents(
        drg["standard_federal_rate_cents"], drg["relative_weight"]
    )
    if not short_stay_outlier_applied:
        return full
    return min(
        min(full, _ltch_per_diem_component_cents(full, drg["alos_days"], covered_los_days)),
        _ipps_per_diem_candidate_cents(drg["ipps_comparable_per_diem_cents"], covered_los_days),
        drg["ipps_comparable_full_cents"],
    )


def _site_neutral_base_cents(drg, estimated_cost_cents):
    """The site-neutral base: the smaller of the IPPS-comparable full amount and the cost."""
    cost = 0 if estimated_cost_cents is None else estimated_cost_cents
    return min(drg["ipps_comparable_full_cents"], cost)


class TestCoveredLosDaysNetsReturnedInterruptionDays:
    """A stay that left for four days, came back, and was discharged three weeks later."""

    def test_a_four_day_absence_returned_inside_its_window_banks_four_interruption_days(
        self, api, nurse, officer
    ):
        """An absence of four days settles as RETURNED and adds four days to the stay's total.

        The patient is admitted at the clock epoch, leaves for an acute-care hospital on
        6 August and returns on 10 August. The whole-day count between those two calendar
        dates is four, comfortably inside the nine-day acute-care window, so the event
        closes as RETURNED, the stay comes back to ADMITTED, and exactly those four days
        land in `interruption_days_total` — which is the figure the covered length of stay
        must later subtract.

        PRD 3.5: "The system stamps `returned_at` with the current logical instant and computes `interruption_days` as the whole-day count from `left_at` to `returned_at`."
        PRD 3.5: "When the return is inside the window, the event moves `OPEN → RETURNED` with `within_window` true, its `interruption_days` are added to the stay's `interruption_days_total`, and the stay moves `INTERRUPTED → ADMITTED`."

        Design: Corner/calculations/covered_los_days_subtracts_the_returned_interruption_days
        """
        expected_interruption_days = day_count(LEFT_AT, RETURNED_AT_INSIDE_WINDOW)

        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)

        fixtures.advance_clock(api, LEFT_AT, headers=officer)
        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )
        fixtures.advance_clock(api, RETURNED_AT_INSIDE_WINDOW, headers=officer)
        returned = fixtures.return_from_interruption(api, event["id"], headers=nurse)

        assert_integer_field(returned, "interruption_days", expected_interruption_days)
        assert returned["status"] == InterruptionStatus.RETURNED
        assert returned["within_window"] is True

        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["clinical_status"] == ClinicalStatus.ADMITTED
        assert_integer_field(stay, "interruption_days_total", expected_interruption_days)

    def test_covered_los_days_is_the_admission_to_discharge_span_less_the_interruption_days(
        self, api, nurse, officer
    ):
        """The covered stay is the whole span from admission to discharge minus the four days away.

        Nothing reopened this stay, so `carried_los_days` is 0 and `resumed_at` is still
        null — only a recombination stamps that field — which makes the segment start the
        stay's own `admitted_at`. The segment from 1 August to 25 August is 24 whole days,
        and the four days the patient spent in acute care come off it, leaving 20 covered
        days. Against a 30-day average stay the short-stay threshold is 25 days, so 20
        days is a short stay.

        PRD 3.3: "Its `carried_los_days` starts at 0, its `interruption_days_total` at 0, its `interruption_count` at 0, and its `interrupted_parent_stay_id`, `resumed_at`, `discharged_at`, `covered_los_days`, `sso_threshold_days`, `short_stay_outlier_applied` and `discharge_payment_pct` all start null."
        PRD 3.6: "The segment start is the stay's `resumed_at` when that field is non-null, and otherwise its `admitted_at`."
        PRD 3.6: "The stay's `covered_los_days` is then `carried_los_days` plus that segment length, minus `interruption_days_total`."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."

        Design: Corner/calculations/covered_los_days_subtracts_the_returned_interruption_days
        """
        interruption_days = day_count(LEFT_AT, RETURNED_AT_INSIDE_WINDOW)
        expected_covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_LATE_AUGUST) - interruption_days

        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)
        fixtures.advance_clock(api, LEFT_AT, headers=officer)
        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )
        fixtures.advance_clock(api, RETURNED_AT_INSIDE_WINDOW, headers=officer)
        fixtures.return_from_interruption(api, event["id"], headers=nurse)
        fixtures.advance_clock(api, DISCHARGE_AT_LATE_AUGUST, headers=officer)

        stay = fixtures.discharge(
            api,
            admission.stay_id,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=ORDINARY_COST_CENTS,
            headers=nurse,
        )

        assert_unset(stay, "resumed_at")
        assert_integer_field(stay, "carried_los_days", 0)
        assert_integer_field(stay, "interruption_days_total", interruption_days)
        assert_integer_field(stay, "covered_los_days", expected_covered)
        assert_integer_field(
            stay, "sso_threshold_days", sso_threshold_days(DRG_207["alos_days"])
        )
        assert stay["sso_threshold_days"] == DRG_207_SSO_THRESHOLD_DAYS
        assert stay["short_stay_outlier_applied"] is True

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert_integer_field(determination, "covered_los_days_used", expected_covered)

    def test_the_shortened_stay_prices_on_the_120_percent_ipps_per_diem_candidate(
        self, api, nurse, officer
    ):
        """At 20 covered days the smallest of the three short-stay candidates is the IPPS per diem.

        With a full amount of 6,000,000 cents over a 30-day average, the LTCH per-diem
        component for 20 days is 4,000,000 cents and the IPPS-comparable full amount is
        2,400,000 cents, but 120 percent of the 90,000-cent IPPS per diem across 20 days
        is only 2,160,000 cents — so that third figure is the standard base. The estimated
        cost of 1,000,000 cents never reaches the base plus the 3,000,000-cent fixed loss,
        so the high-cost add-on is nil and the total is the base alone, which is 36.00
        percent of the full amount.

        PRD 3.7: "The second candidate is the DRG's `ipps_comparable_per_diem_cents` multiplied by the `covered_los_days` and then by 1.20, rounded half up to whole cents — that is, 120 percent of the IPPS-comparable per diem for the days actually delivered."
        PRD 3.7: "The standard base is the minimum of those three."
        PRD 3.7: "Third, if the excess is less than or equal to zero the add-on is 0; otherwise the add-on is 0.80 multiplied by the excess, rounded half up to whole cents."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."
        PRD 3.7: "The percentage is mirrored onto the stay's `discharge_payment_pct`, which is null until a determination exists."

        Design: Corner/calculations/covered_los_days_subtracts_the_returned_interruption_days
        """
        interruption_days = day_count(LEFT_AT, RETURNED_AT_INSIDE_WINDOW)
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_LATE_AUGUST) - interruption_days
        ltch_candidate = _ltch_per_diem_component_cents(
            DRG_207_FULL_STANDARD_CENTS, DRG_207["alos_days"], covered
        )
        ipps_per_diem_candidate = _ipps_per_diem_candidate_cents(
            DRG_207["ipps_comparable_per_diem_cents"], covered
        )
        expected_base = _standard_base_cents(DRG_207, covered, True)
        expected_outlier = outlier_payment_cents(expected_base, ORDINARY_COST_CENTS)
        expected_pct = discharge_payment_pct(expected_base, DRG_207_FULL_STANDARD_CENTS)

        # The candidate that wins does so strictly: the other two are larger.
        assert expected_base == ipps_per_diem_candidate
        assert ipps_per_diem_candidate < ltch_candidate
        assert ipps_per_diem_candidate < DRG_207["ipps_comparable_full_cents"]

        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)
        fixtures.advance_clock(api, LEFT_AT, headers=officer)
        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )
        fixtures.advance_clock(api, RETURNED_AT_INSIDE_WINDOW, headers=officer)
        fixtures.return_from_interruption(api, event["id"], headers=nurse)
        fixtures.advance_clock(api, DISCHARGE_AT_LATE_AUGUST, headers=officer)
        stay = fixtures.discharge(
            api,
            admission.stay_id,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=ORDINARY_COST_CENTS,
            headers=nurse,
        )

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert_cents(determination, "full_standard_amount_cents", DRG_207_FULL_STANDARD_CENTS)
        assert_cents(determination, "base_payment_cents", expected_base)
        assert_cents(determination, "outlier_payment_cents", expected_outlier)
        assert_cents(determination, "total_payment_cents", expected_base + expected_outlier)
        assert_pct(determination, "discharge_payment_pct", expected_pct)
        assert_pct(stay, "discharge_payment_pct", expected_pct)


def _undocumented_short_stay(api, world):
    """A 14-day stay discharged with no notes and no weaning plan, so the review scores high."""
    admission = fixtures.admitted_stay(api, world)
    fixtures.advance_clock(api, DISCHARGE_AT_MID_AUGUST)
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.HOME,
        estimated_cost_cents=ORDINARY_COST_CENTS,
        file_notes=False,
    )


class TestRiskScoreCountsOnlyRequiredDisciplinesAndSettledQueries:
    """Notes outside the mandatory four, and queries still out, both earn nothing."""

    def test_notes_in_unrequired_disciplines_leave_the_missing_discipline_count_at_four(
        self, api, officer
    ):
        """Nutrition and therapy notes do not reduce a missing-discipline count of four.

        The stay is discharged undocumented, so all four mandatory disciplines are missing:
        32 points for the four gaps, 15 for having no weaning plan and 20 for the short-stay
        outlier give a raw total of 67, a MODERATE band. Filing a nutrition note and a
        physical-and-occupational-therapy note adds two notes to the stay but touches none
        of the four disciplines the score looks at, so a rescore returns the same count and
        the same score.

        PRD 3.8: "Four disciplines are treated as mandatory on every stay: `PHYSICIAN`, `NURSING`, `RESPIRATORY_THERAPY` and `CASE_MANAGEMENT`."
        PRD 3.8: "The review's `missing_discipline_count` is how many of those four have zero interdisciplinary notes on the stay — a number from 0 through 4, counting notes in any state since notes are immutable."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."

        Design: Corner/calculations/risk_score_counts_only_required_disciplines_and_settled_queries
        """
        expected_score = clamped_score(raw_risk_score(4, 1, 1, 0, 0))

        world = fixtures.build_world(api)
        admission = _undocumented_short_stay(api, world)

        assert_integer_field(admission.review, "missing_discipline_count", 4)
        assert_integer_field(admission.review, "as_documented_score", expected_score)
        assert admission.review["risk_band"] == risk_band_for(expected_score)

        fixtures.file_note(api, admission.stay_id, Discipline.NUTRITION)
        fixtures.file_note(api, admission.stay_id, Discipline.PT_OT)
        rescored = fixtures.rescore(api, admission.review_id, headers=officer)

        assert_integer_field(rescored, "missing_discipline_count", 4)
        assert_integer_field(rescored, "as_documented_score", expected_score)
        assert rescored["risk_band"] == risk_band_for(expected_score)

        assert len(fixtures.notes_of(api, admission.stay_id, discipline=Discipline.NUTRITION)) == 1
        assert len(fixtures.notes_of(api, admission.stay_id)) == 2

    def test_filing_all_four_mandatory_disciplines_clears_the_missing_discipline_points(
        self, api, officer
    ):
        """Once each mandatory discipline has a note the 32 gap points disappear.

        The same undocumented stay is documented in all four mandatory disciplines and
        rescored. The 32 points of missing-discipline weight fall away and only the weaning
        gap and the short-stay outlier remain, for a raw total of 35 — below 40, so the band
        drops from MODERATE to LOW.

        PRD 3.8: "The review's `missing_discipline_count` is how many of those four have zero interdisciplinary notes on the stay — a number from 0 through 4, counting notes in any state since notes are immutable."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."
        PRD 3.8: "`risk_band` is `HIGH` when `effective_score` is at least 70, `MODERATE` when `effective_score` is at least 40 but below 70, and `LOW` below 40."

        Design: Corner/calculations/risk_score_counts_only_required_disciplines_and_settled_queries
        """
        documented_score = clamped_score(raw_risk_score(0, 1, 1, 0, 0))

        world = fixtures.build_world(api)
        admission = _undocumented_short_stay(api, world)
        fixtures.file_required_notes(api, admission.stay_id)

        rescored = fixtures.rescore(api, admission.review_id, headers=officer)

        assert_integer_field(rescored, "missing_discipline_count", 0)
        assert_integer_field(rescored, "as_documented_score", documented_score)
        assert_integer_field(rescored, "effective_score", documented_score)
        assert rescored["risk_band"] == risk_band_for(documented_score)
        assert rescored["risk_band"] == RiskBand.LOW

    def test_an_issued_query_earns_no_credit_until_the_physician_answers_it(
        self, api, officer, nurse
    ):
        """A query still out counts for nothing; answering it takes 12 points off.

        The documented stay sits at 35 points. A site-neutral-justification query is issued
        and a rescore runs while it is still outstanding: `answered_query_count` stays 0, no
        `query_adjusted_score` exists yet, and the effective score is still the as-documented
        35. When the attending physician answers, the count rises to 1, the credit of 12
        points applies and the effective score becomes 23.

        PRD 3.8: "The count of answered queries, `answered_query_count`, counts the review's `DocumentationQuery` rows whose `status` is `ANSWERED` or `CLOSED`; queries in `ISSUED`, `EXPIRED` or `VOIDED` earn no credit."
        PRD 3.8: "The `query_adjusted_score` starts from the same raw total, subtracts 12 points for each answered query, then rounds half up and clamps into the same 0-through-100 range."
        PRD 3.8: "`query_adjusted_score` is null until a rescore observes a non-zero `answered_query_count`."
        PRD 3.8: "The review's `effective_score` is the `query_adjusted_score` when `answered_query_count` is greater than 0, and the `as_documented_score` otherwise."
        PRD 3.8: "On success the query moves `ISSUED → ANSWERED`, `answered_at` is stamped from the logical clock, `answered_by_physician_id` records the acting physician's `X-User-ID`, the review's `answered_query_count` increases by 1, and the denial-risk score is recomputed, so the `risk_band` may fall."

        Design: Corner/calculations/risk_score_counts_only_required_disciplines_and_settled_queries
        """
        raw = raw_risk_score(0, 1, 1, 0, 0)
        documented_score = clamped_score(raw)
        credited_score = query_adjusted_score(raw, 1)
        assert credited_score == documented_score - ANSWERED_QUERY_CREDIT

        world = fixtures.build_world(api)
        admission = _undocumented_short_stay(api, world)
        fixtures.file_required_notes(api, admission.stay_id)
        fixtures.rescore(api, admission.review_id, headers=officer)

        query = fixtures.issue_query(
            api,
            admission.review_id,
            query_type=QueryType.SITE_NEUTRAL_JUSTIFICATION,
            headers=nurse,
        )
        assert query["status"] == QueryStatus.ISSUED

        with_query_outstanding = fixtures.rescore(api, admission.review_id, headers=officer)
        assert_integer_field(with_query_outstanding, "answered_query_count", 0)
        assert_unset(with_query_outstanding, "query_adjusted_score")
        assert_integer_field(with_query_outstanding, "effective_score", documented_score)
        assert with_query_outstanding["status"] == ReviewStatus.QUERIES_ISSUED

        fixtures.answer_query(api, query["id"], world.physician_headers)

        answered = fixtures.read_review(api, admission.review_id, headers=officer)
        assert_integer_field(answered, "answered_query_count", 1)
        assert_integer_field(answered, "query_adjusted_score", credited_score)
        assert_integer_field(answered, "effective_score", credited_score)
        assert answered["risk_band"] == risk_band_for(credited_score)


class TestThresholdPctComesFromColocationAndHospitalType:
    """Two facts about a referral source decide which of two thresholds it lives under."""

    @pytest.mark.parametrize(
        "hospital_type, is_colocated, expected_threshold_pct",
        [
            (HospitalType.ACUTE_CARE, False, BASE_REFERRAL_THRESHOLD_PCT),
            (HospitalType.ACUTE_CARE, True, EXPANDED_REFERRAL_THRESHOLD_PCT),
            (HospitalType.CRITICAL_ACCESS, False, EXPANDED_REFERRAL_THRESHOLD_PCT),
        ],
    )
    def test_a_new_referral_source_gets_fifty_percent_only_when_colocated_or_critical_access(
        self, api, officer, hospital_type, is_colocated, expected_threshold_pct
    ):
        """Co-location or critical-access status buys the expanded 50.00 threshold; nothing else does.

        The threshold is a property of the source hospital, fixed the moment it is
        registered and before any referral exists. A plain acute-care hospital that is not
        co-located sits at 25.00; either co-location on its own or critical-access status on
        its own lifts it to 50.00.

        PRD 3.1: "Two of those inputs determine how much of the LTCH's admission mix this hospital is allowed to supply: a hospital's `threshold_pct` is 50.00 when `is_colocated` is true **or** its `hospital_type` is `CRITICAL_ACCESS`, and 25.00 otherwise."

        Design: Corner/calculations/threshold_pct_comes_from_colocation_and_hospital_type
        """
        hospital = fixtures.add_hospital(
            api, headers=officer, hospital_type=hospital_type, is_colocated=is_colocated
        )

        assert_pct(hospital, "threshold_pct", expected_threshold_pct)

    def test_two_sources_at_the_same_share_land_in_different_states_because_thresholds_differ(
        self, api, officer
    ):
        """A 25.00 share is a warning against a 25.00 threshold and compliant against 50.00.

        Four admissions fill the period: two from a co-located acute-care source, one from a
        critical-access source and one from a plain acute-care source. The critical-access
        and plain sources hold identical 25.00 shares, but the plain source's threshold is
        also 25.00 — not a breach, since the comparison is strict, yet above the threshold
        less the 5.00-point margin, so it warns — while the critical-access source's 50.00
        threshold leaves it comfortably compliant. The co-located source's own 50.00 share
        sits exactly on its 50.00 threshold and therefore also warns rather than breaches.

        PRD 3.3: "A hospital's `share_pct` is its `admissions_in_period` divided by the period's `total_admissions`, multiplied by 100 and rounded half up to two decimal places; when the denominator is zero, `share_pct` is stored as 0.00."
        PRD 3.3: "Its `threshold_pct` is recomputed at the same time from the rule in §3.1 — 50.00 for a co-located or critical-access source, 25.00 otherwise."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."
        PRD 3.3: "Otherwise, if `share_pct` is strictly greater than `threshold_pct` reduced by a warning margin of 5.00 percentage points, `monitoring_state` becomes `WARNING`."

        Design: Corner/calculations/threshold_pct_comes_from_colocation_and_hospital_type
        """
        world = fixtures.build_world(api, hospital={"is_colocated": True})
        critical_access = fixtures.add_hospital(
            api, headers=officer, hospital_type=HospitalType.CRITICAL_ACCESS
        )
        plain = fixtures.add_hospital(api, headers=officer)

        fixtures.admitted_stay(api, world)
        for hospital_id in (world.hospital_id, critical_access["id"], plain["id"]):
            patient = fixtures.add_patient(api)
            fixtures.admitted_stay(
                api,
                world,
                patient_id=patient["id"],
                patient_version=patient["version"],
                hospital_id=hospital_id,
            )

        fixtures.recompute_shares(api, world.period_id, headers=officer)

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", MIN_ADMISSIONS_FOR_MONITORING)

        colocated_after = fixtures.read_hospital(api, world.hospital_id)
        critical_after = fixtures.read_hospital(api, critical_access["id"])
        plain_after = fixtures.read_hospital(api, plain["id"])

        assert_pct(colocated_after, "threshold_pct", EXPANDED_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(
            colocated_after,
            2,
            expected_share_pct(2, MIN_ADMISSIONS_FOR_MONITORING),
            MonitoringState.WARNING,
        )

        assert_pct(critical_after, "threshold_pct", EXPANDED_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(
            critical_after,
            1,
            expected_share_pct(1, MIN_ADMISSIONS_FOR_MONITORING),
            MonitoringState.COMPLIANT,
        )

        assert_pct(plain_after, "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(
            plain_after,
            1,
            expected_share_pct(1, MIN_ADMISSIONS_FOR_MONITORING),
            MonitoringState.WARNING,
        )

        shares = sum(
            Decimal(str(hospital["share_pct"]))
            for hospital in (colocated_after, critical_after, plain_after)
        )
        assert shares == Decimal("100.00")


class TestSsoPerDiemProductAndPercentageRoundHalfUp:
    """A seven-day stay on a thirteen-day DRG, where every rounding step is visible."""

    def test_the_per_diem_component_is_rounded_once_on_the_whole_product(self, api, officer):
        """3,600,000 over 13 days across 7 days is 1,938,462 cents, not 1,938,461.

        The exact product is 1,938,461.538… cents. Rounding half up once, at the end,
        gives 1,938,462; truncating the product, or rounding the daily quotient before
        multiplying by the seven days delivered, both lose that cent. Seven covered days
        against a short-stay threshold of 10 days makes this a short stay, and the
        per-diem component is the smallest of the three candidates, so it is the base.

        PRD 2.5: "Where a monetary computation produces a fractional cent, the result is rounded to the nearest whole cent with ties rounded away from zero."
        PRD 3.6: "Alongside it, `sso_threshold_days` is computed as five-sixths of the `alos_days` of the DRG in force, rounded **down** to a whole number and never rounded to nearest."
        PRD 3.7: "The first candidate is the smaller of `full_standard_amount_cents` and the LTCH per-diem component, where that component is `full_standard_amount_cents` divided by the DRG's `alos_days` and multiplied by the stay's `covered_los_days`, with exactly **one** rounding — half up to whole cents — applied to the whole product; the per-diem quotient must never be rounded before it is multiplied by the length of stay."
        PRD 3.7: "The standard base is the minimum of those three."

        Design: Corner/calculations/sso_per_diem_product_and_percentage_round_half_up
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_08_08)
        alos = DRG_573["alos_days"]
        full = full_standard_amount_cents(
            DRG_573["standard_federal_rate_cents"], DRG_573["relative_weight"]
        )
        per_diem_component = _ltch_per_diem_component_cents(full, alos, covered)
        truncated_product = int(Decimal(full) * Decimal(covered) / Decimal(alos))
        quotient_rounded_first = round_half_up_int(
            Decimal(round_half_up_int(Decimal(full) / Decimal(alos))) * Decimal(covered)
        )
        expected_base = _standard_base_cents(DRG_573, covered, True)

        assert full == DRG_573_FULL_STANDARD_CENTS
        assert per_diem_component == truncated_product + 1
        assert per_diem_component != quotient_rounded_first
        assert expected_base == per_diem_component

        world = fixtures.build_world(api, drg_rate=DRG_573)
        admission = fixtures.admitted_stay(api, world)
        fixtures.advance_clock(api, DISCHARGE_AT_08_08, headers=officer)
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=ORDINARY_COST_CENTS,
        )

        assert_integer_field(admission.stay, "covered_los_days", covered)
        assert_integer_field(admission.stay, "sso_threshold_days", sso_threshold_days(alos))
        assert admission.stay["sso_threshold_days"] == DRG_573_SSO_THRESHOLD_DAYS
        assert admission.stay["short_stay_outlier_applied"] is True

        determination = admission.determination
        assert_cents(determination, "full_standard_amount_cents", DRG_573_FULL_STANDARD_CENTS)
        assert_cents(determination, "base_payment_cents", expected_base)
        assert_cents(
            determination,
            "outlier_payment_cents",
            outlier_payment_cents(expected_base, ORDINARY_COST_CENTS),
        )
        assert_cents(determination, "total_payment_cents", expected_base)

    def test_the_discharge_percentage_of_that_base_rounds_half_up_to_two_decimals(
        self, api, officer
    ):
        """1,938,462 of 3,600,000 cents is 53.846…, stored and mirrored as 53.85.

        The percentage is computed from the base payment, not the total, and carries exactly
        two decimals rounded half up — 53.846166… rounds up to 53.85. The same figure appears
        on the determination and is mirrored onto the stay.

        PRD 2.5: "Percentages — `share_pct`, `threshold_pct`, `discharge_payment_pct` — are stored and returned with exactly two decimal places, likewise rounded half up with ties away from zero."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."
        PRD 3.7: "The percentage is mirrored onto the stay's `discharge_payment_pct`, which is null until a determination exists."

        Design: Corner/calculations/sso_per_diem_product_and_percentage_round_half_up
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_08_08)
        expected_base = _standard_base_cents(DRG_573, covered, True)
        expected_pct = discharge_payment_pct(expected_base, DRG_573_FULL_STANDARD_CENTS)
        assert expected_pct == Decimal("53.85")

        world = fixtures.build_world(api, drg_rate=DRG_573)
        admission = fixtures.admitted_stay(api, world)
        fixtures.advance_clock(api, DISCHARGE_AT_08_08, headers=officer)
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=ORDINARY_COST_CENTS,
        )

        assert_pct(admission.determination, "discharge_payment_pct", expected_pct)
        assert_pct(admission.stay, "discharge_payment_pct", expected_pct)


def _stay_interrupted_to_acute_care_at_admission(api, world=None):
    """A stay admitted at the clock epoch and interrupted to acute care at that same instant."""
    admission = fixtures.admitted_stay(api, world)
    event = fixtures.interrupt(
        api, admission.stay_id, destination=InterruptionDestination.ACUTE_CARE
    )
    return admission, event


class TestInterruptionWindowAtNineDaysReturnsAndAtTenDaysExpires:
    """The last day of a nine-day acute-care window is inside it; the next day is not."""

    def test_an_absence_of_exactly_nine_days_is_inside_the_nine_day_window(self, api, officer):
        """Nine days against a nine-day window returns the patient to the stay.

        The comparison is an inclusive one, so an absence whose whole-day count equals the
        window exactly is still within it. The event settles as RETURNED with `within_window`
        true, the stay goes back to ADMITTED rather than being discharged, and all nine days
        are banked against the stay's interruption total.

        PRD 3.5: "The destination sets the event's `window_days` directly: 9 days for `ACUTE_CARE`, 27 days for both `IRF` and `SNF`, and 3 days for `HOME`."
        PRD 3.5: "The comparison is inclusive: `within_window` is true when `interruption_days` is less than or equal to `window_days`, so an absence of exactly 9 days falls inside a 9-day window while 10 days does not."
        PRD 3.5: "When the return is inside the window, the event moves `OPEN → RETURNED` with `within_window` true, its `interruption_days` are added to the stay's `interruption_days_total`, and the stay moves `INTERRUPTED → ADMITTED`."

        Design: Corner/calculations/interruption_window_at_9_days_returns_and_at_10_days_expires
        """
        window_days = INTERRUPTION_WINDOW_DAYS[InterruptionDestination.ACUTE_CARE]
        days_away = day_count(CLOCK_EPOCH, NINE_DAYS_AFTER_EPOCH)
        assert days_away == window_days

        admission, event = _stay_interrupted_to_acute_care_at_admission(api)
        assert_integer_field(event, "window_days", window_days)
        assert_instant_equals(event["left_at"], CLOCK_EPOCH, field="left_at")

        fixtures.advance_clock(api, NINE_DAYS_AFTER_EPOCH, headers=officer)
        returned = fixtures.return_from_interruption(api, event["id"])

        assert_integer_field(returned, "interruption_days", days_away)
        assert returned["within_window"] is True
        assert returned["status"] == InterruptionStatus.RETURNED

        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["clinical_status"] == ClinicalStatus.ADMITTED
        assert_integer_field(stay, "interruption_days_total", days_away)

    def test_an_absence_of_ten_days_expires_the_window_and_discharges_back_to_the_departure(
        self, api, officer
    ):
        """Ten days against a nine-day window discharges the stay as of the day it left.

        One day past the window the event expires instead of returning. The stay is
        discharged retroactively to the interruption's `left_at` — the epoch instant it
        departed, not the eleventh of August it came back — with the system-only disposition
        `INTERRUPTION_EXPIRED`, and the ten days away are excluded from the stay's
        interruption total because they now fall outside the stay altogether.

        PRD 3.5: "The comparison is inclusive: `within_window` is true when `interruption_days` is less than or equal to `window_days`, so an absence of exactly 9 days falls inside a 9-day window while 10 days does not."
        PRD 3.5: "When the return is outside the window, the event moves `OPEN → EXPIRED` with `within_window` false and the stay is discharged retroactively rather than resumed: the stay moves `INTERRUPTED → DISCHARGED`, its `discharged_at` is set to the interruption's `left_at` — **not** to the return instant — and its `discharge_disposition` is stamped as `INTERRUPTION_EXPIRED`, a value only the system may write."
        PRD 3.5: "An expired event's `interruption_days` are deliberately **not** added to `interruption_days_total`, because those days now fall outside the stay entirely."

        Design: Corner/calculations/interruption_window_at_9_days_returns_and_at_10_days_expires
        """
        window_days = INTERRUPTION_WINDOW_DAYS[InterruptionDestination.ACUTE_CARE]
        days_away = day_count(CLOCK_EPOCH, TEN_DAYS_AFTER_EPOCH)
        assert days_away == window_days + 1

        admission, event = _stay_interrupted_to_acute_care_at_admission(api)
        fixtures.advance_clock(api, TEN_DAYS_AFTER_EPOCH, headers=officer)
        expired = fixtures.return_from_interruption(api, event["id"])

        assert_integer_field(expired, "interruption_days", days_away)
        assert expired["within_window"] is False
        assert expired["status"] == InterruptionStatus.EXPIRED

        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["clinical_status"] == ClinicalStatus.DISCHARGED
        assert stay["discharge_disposition"] == DischargeDisposition.INTERRUPTION_EXPIRED
        assert_instant_equals(stay["discharged_at"], CLOCK_EPOCH, field="discharged_at")
        assert_integer_field(stay, "interruption_days_total", 0)

    def test_the_expiry_discharge_prices_a_zero_day_stay_at_nothing_and_opens_a_review(
        self, api, officer
    ):
        """A stay discharged back to its admission instant has no covered days and no payment.

        The retroactive discharge runs the full cascade over a stay whose admission and
        discharge fall on the same calendar date, so the covered length of stay is 0 days and
        every candidate driven by those days collapses to 0 — the base payment is nil. No
        estimated cost was ever supplied, so the high-cost add-on is 0 too and the total is
        0. The review still opens, and with no documentation, no weaning plan and a
        short-stay-outlier flag set it scores 67, a MODERATE band that issues no query.

        PRD 3.5: "The covered length of stay, the short-stay-outlier threshold and its flag are then computed, and the full discharge cascade of §3.6 runs."
        PRD 3.5: "Because no `estimated_cost_cents` is ever supplied on a window-expiry discharge, that field stays null and the high-cost outlier add-on comes out at zero for such stays."
        PRD 3.6: "The stay's `covered_los_days` is then `carried_los_days` plus that segment length, minus `interruption_days_total`."
        PRD 3.7: "The standard base is the minimum of those three."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."

        Design: Corner/calculations/interruption_window_at_9_days_returns_and_at_10_days_expires
        """
        expected_base = _standard_base_cents(DRG_207, 0, True)
        expected_score = clamped_score(raw_risk_score(4, 1, 1, 0, 0))
        assert expected_base == 0

        admission, event = _stay_interrupted_to_acute_care_at_admission(api)
        fixtures.advance_clock(api, TEN_DAYS_AFTER_EPOCH, headers=officer)
        fixtures.return_from_interruption(api, event["id"])

        stay = fixtures.read_stay(api, admission.stay_id)
        assert_integer_field(stay, "covered_los_days", 0)
        assert_integer_field(
            stay, "sso_threshold_days", sso_threshold_days(DRG_207["alos_days"])
        )
        assert stay["short_stay_outlier_applied"] is True
        assert_unset(stay, "estimated_cost_cents")
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert_integer_field(determination, "covered_los_days_used", 0)
        assert_cents(determination, "full_standard_amount_cents", DRG_207_FULL_STANDARD_CENTS)
        assert_cents(determination, "base_payment_cents", expected_base)
        assert_cents(determination, "outlier_payment_cents", 0)
        assert_cents(determination, "total_payment_cents", 0)

        review = fixtures.sole_review(api, admission.stay_id)
        assert_integer_field(review, "as_documented_score", expected_score)
        assert_integer_field(review, "effective_score", expected_score)
        assert review["risk_band"] == risk_band_for(expected_score)
        assert review["status"] == ReviewStatus.OPEN


VENT_HOURS_SEED = 40.5
FIRST_FAILED_VENT_HOURS = 24.0
TOLERATED_VENT_HOURS = 20.5
TOLERATED_SBT_HOURS = 6.0
SECOND_FAILED_VENT_HOURS = 0.5


class TestVentHoursTotalAccumulatesTheSeedAndEveryOutcome:
    """A plan seeded at 40.5 hours, then a failed, a tolerated and another failed trial."""

    def test_a_failed_trial_adds_its_hours_without_moving_the_step(self, api, nurse):
        """The seed of 40.5 hours plus a failed trial's 24 hours gives 64.5 hours.

        The plan is opened with an explicit seed, so the counter starts at 40.5 rather than
        0, and the first record is a failure. A failed record still counts as an attempt and
        still adds its ventilator hours; with only one consecutive failure the plan holds its
        place in SBT_TRIAL and its step stays at 0, and no trial has been tolerated so the
        best tolerated duration is still 0.

        PRD 3.4: "Two optional inputs are accepted: `protocol_label`, a 1-to-40-character protocol identifier that defaults to `STANDARD_SBT`, and `vent_hours_total`, which seeds the plan's cumulative ventilator-hour counter and defaults to 0."
        PRD 3.4: "Every record, whatever its outcome, increases `sbt_attempt_count` by 1 and adds `vent_hours_since_last` to `vent_hours_total`."
        PRD 3.4: "It increases `sbt_attempt_count` by 1, increases `consecutive_failed_sbt` by 1, and adds `vent_hours_since_last` to `vent_hours_total`."
        PRD 3.4: "If the resulting `consecutive_failed_sbt` is still below 2, the plan simply stays where it was — `SBT_TRIAL` self-loops to `SBT_TRIAL`, `PROGRESSING` self-loops to `PROGRESSING` — and `current_step` is untouched."

        Design: Corner/calculations/vent_hours_total_accumulates_the_seed_and_every_outcome
        """
        admission = fixtures.admitted_stay(api)
        plan = fixtures.open_weaning_plan(
            api,
            admission.stay_id,
            protocol_label=DEFAULT_PROTOCOL_LABEL,
            vent_hours_total=VENT_HOURS_SEED,
            headers=nurse,
        )
        assert_vent_hours(plan, "vent_hours_total", VENT_HOURS_SEED)
        assert_integer_field(plan, "sbt_attempt_count", 0)
        assert_integer_field(plan, "current_step", 0)
        assert plan["status"] == WeaningPlanStatus.SBT_TRIAL

        after_failure = fixtures.failed_sbt(
            api, plan["id"], vent_hours_since_last=FIRST_FAILED_VENT_HOURS
        )

        assert_vent_hours(
            after_failure, "vent_hours_total", VENT_HOURS_SEED + FIRST_FAILED_VENT_HOURS
        )
        assert_integer_field(after_failure, "sbt_attempt_count", 1)
        assert_integer_field(after_failure, "consecutive_failed_sbt", 1)
        assert_integer_field(after_failure, "current_step", 0)
        assert_vent_hours(after_failure, "max_tolerated_sbt_hours", 0)
        assert after_failure["status"] == WeaningPlanStatus.SBT_TRIAL

    def test_the_counter_is_the_seed_plus_every_record_including_the_failures(self, api, nurse):
        """Three records of 24, 20.5 and 0.5 hours carry the seeded plan to 85.5 hours.

        A tolerated trial between the two failures moves the plan to PROGRESSING and lifts
        the step to 1, and the second failure neither undoes the step — one consecutive
        failure is not a regression — nor removes any hours. The running total is therefore
        the seed plus all three increments: not the tolerated increment alone, and not the
        increments without the seed. At 85.5 hours the plan is still short of the 96
        ventilator hours that would qualify a stay on intensity.

        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."
        PRD 3.4: "It increases `current_step` by 1, resets `consecutive_failed_sbt` to 0, sets `max_tolerated_sbt_hours` to the larger of its previous value and this trial's `sbt_hours`, stamps `last_progression_at` with the current logical instant, and recomputes `liberation_eligible` as true exactly when `current_step` has reached at least 2."
        PRD 3.4: "Hours are carried to one decimal place."
        PRD 3.7: "Then at least one of two intensity criteria must hold: the referral's `icu_days_at_referral` is at least 3, **or** the stay has a weaning plan whose `vent_hours_total` has reached at least 96 ventilator hours — four full days of ventilation accrued inside the LTCH, inclusive at the boundary, so 95.0 hours does not qualify and 96.0 does."

        Design: Corner/calculations/vent_hours_total_accumulates_the_seed_and_every_outcome
        """
        every_increment = (
            FIRST_FAILED_VENT_HOURS + TOLERATED_VENT_HOURS + SECOND_FAILED_VENT_HOURS
        )
        expected_total = VENT_HOURS_SEED + every_increment
        assert expected_total != every_increment
        assert expected_total != VENT_HOURS_SEED + TOLERATED_VENT_HOURS
        assert expected_total < VENT_HOURS_SITE_NEUTRAL_MIN

        admission = fixtures.admitted_stay(api)
        plan = fixtures.open_weaning_plan(
            api,
            admission.stay_id,
            protocol_label=DEFAULT_PROTOCOL_LABEL,
            vent_hours_total=VENT_HOURS_SEED,
            headers=nurse,
        )
        fixtures.failed_sbt(api, plan["id"], vent_hours_since_last=FIRST_FAILED_VENT_HOURS)
        after_progression = fixtures.tolerated_sbt(
            api,
            admission.stay_id,
            plan["id"],
            sbt_hours=TOLERATED_SBT_HOURS,
            vent_hours_since_last=TOLERATED_VENT_HOURS,
        )

        assert_vent_hours(
            after_progression,
            "vent_hours_total",
            VENT_HOURS_SEED + FIRST_FAILED_VENT_HOURS + TOLERATED_VENT_HOURS,
        )
        assert_integer_field(after_progression, "current_step", 1)
        assert_integer_field(after_progression, "consecutive_failed_sbt", 0)
        assert_vent_hours(after_progression, "max_tolerated_sbt_hours", TOLERATED_SBT_HOURS)
        assert after_progression["status"] == WeaningPlanStatus.PROGRESSING

        after_second_failure = fixtures.failed_sbt(
            api, plan["id"], vent_hours_since_last=SECOND_FAILED_VENT_HOURS
        )

        assert_vent_hours(after_second_failure, "vent_hours_total", expected_total)
        assert_integer_field(after_second_failure, "sbt_attempt_count", 3)
        assert_integer_field(after_second_failure, "current_step", 1)
        assert_vent_hours(after_second_failure, "max_tolerated_sbt_hours", TOLERATED_SBT_HOURS)
        assert after_second_failure["status"] == WeaningPlanStatus.PROGRESSING


def _wound_stay_priced_without_a_weaning_plan(api, officer):
    """A 19-day wound-track stay on the short DRG, discharged to a skilled nursing facility."""
    world = fixtures.build_world(api, drg_rate=DRG_573)
    clinicals = dict(factories.WOUND_CLINICALS, wound_stage=4, wound_count=3)
    admission = fixtures.admitted_stay(
        api, world, clinicals=clinicals, expected_track=QualifyingTrack.COMPLEX_WOUND
    )
    fixtures.advance_clock(api, DISCHARGE_AT_08_20, headers=officer)
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.SNF,
        estimated_cost_cents=WOUND_COST_CENTS,
        file_notes=False,
    )


class TestNoWeaningPlanAndLowIcuDaysSelectTheSiteNeutralVariant:
    """A wound patient with one ICU day and no weaning plan cannot qualify on intensity."""

    def test_the_variant_falls_to_site_neutral_and_prices_on_the_ipps_comparable_amount(
        self, api, nurse, officer
    ):
        """One ICU day and no plan leave no intensity criterion, so the stay prices site-neutral.

        The referral records a prior acute discharge, but its single ICU day is below the
        three-day criterion and the stay never opened a weaning plan, so there is no
        ventilator qualification to fall back on. The variant is therefore SITE_NEUTRAL, and
        the site-neutral base is the smaller of the DRG's IPPS-comparable full amount of
        3,400,000 cents and the estimated cost of 4,000,000 cents. Both variant amounts are
        stored anyway: the standard side keeps the full 3,600,000 cents, because 19 covered
        days exceeds the 10-day short-stay threshold and no per-diem reduction applies.

        PRD 3.7: "Then at least one of two intensity criteria must hold: the referral's `icu_days_at_referral` is at least 3, **or** the stay has a weaning plan whose `vent_hours_total` has reached at least 96 ventilator hours — four full days of ventilation accrued inside the LTCH, inclusive at the boundary, so 95.0 hours does not qualify and 96.0 does."
        PRD 3.7: "A stay with no weaning plan at all contributes no ventilator qualification."
        PRD 3.7: "When the referral records a prior acute discharge and at least one intensity criterion holds, `payment_variant` is `STANDARD_LTCH_PPS`; in every other case it is `SITE_NEUTRAL`."
        PRD 3.7: "The site-neutral base is the smaller of the DRG's `ipps_comparable_full_cents` and the stay's `estimated_cost_cents`, with a null `estimated_cost_cents` treated as 0."
        PRD 3.7: "Both are stored on every determination regardless of which variant was selected."
        PRD 3.7: "Then `base_payment_cents` is the standard base when `payment_variant` is `STANDARD_LTCH_PPS` and the site-neutral base when it is `SITE_NEUTRAL`; `outlier_payment_cents` is the add-on computed from `base_payment_cents`; and `total_payment_cents` is `base_payment_cents` plus `outlier_payment_cents`, in whole cents."

        Design: Corner/calculations/no_weaning_plan_and_low_icu_days_select_the_site_neutral_variant
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_08_20)
        standard_base = _standard_base_cents(DRG_573, covered, False)
        site_neutral_base = _site_neutral_base_cents(DRG_573, WOUND_COST_CENTS)
        expected_outlier = outlier_payment_cents(site_neutral_base, WOUND_COST_CENTS)
        assert covered > sso_threshold_days(DRG_573["alos_days"])
        assert site_neutral_base < standard_base

        admission = _wound_stay_priced_without_a_weaning_plan(api, officer)

        plans, _meta = validate_paginated(
            api.list_weaning_plans(params={"stay_id": admission.stay_id}, headers=nurse)
        )
        assert plans == []

        assert_integer_field(admission.stay, "covered_los_days", covered)
        assert admission.stay["short_stay_outlier_applied"] is False

        determination = admission.determination
        assert determination["payment_variant"] == PaymentVariant.SITE_NEUTRAL
        assert_cents(determination, "standard_variant_amount_cents", standard_base)
        assert_cents(determination, "site_neutral_variant_amount_cents", site_neutral_base)
        assert_cents(determination, "base_payment_cents", site_neutral_base)
        assert_cents(determination, "outlier_payment_cents", expected_outlier)
        assert_cents(determination, "total_payment_cents", site_neutral_base + expected_outlier)

    def test_the_site_neutral_stay_scores_its_variant_flag_and_its_length_of_stay_excess(
        self, api, officer
    ):
        """94.44 percent of the full amount, and a review of 60 built from ten and three points.

        The percentage compares the site-neutral base against the standard full amount, so
        3,400,000 of 3,600,000 cents reads 94.44. The review then charges 32 points for four
        undocumented disciplines, 15 for the absent weaning plan, 10 because the variant is
        site-neutral, and half a point for each of the six days by which 19 covered days
        exceed the DRG's 13-day average — 60 in total, a MODERATE band, which issues no
        query of its own.

        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."
        PRD 3.8: "A site-neutral flag contributes 1 when its `payment_variant` is `SITE_NEUTRAL` and 0 otherwise."
        PRD 3.8: "And a length-of-stay excess is the determination's `covered_los_days_used` minus its `alos_days_used`, floored at 0 so that a stay shorter than the DRG's average contributes nothing."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."
        PRD 3.8: "`risk_band` is `HIGH` when `effective_score` is at least 70, `MODERATE` when `effective_score` is at least 40 but below 70, and `LOW` below 40."

        Design: Corner/calculations/no_weaning_plan_and_low_icu_days_select_the_site_neutral_variant
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_08_20)
        los_excess = covered - DRG_573["alos_days"]
        site_neutral_base = _site_neutral_base_cents(DRG_573, WOUND_COST_CENTS)
        expected_pct = discharge_payment_pct(site_neutral_base, DRG_573_FULL_STANDARD_CENTS)
        expected_score = clamped_score(raw_risk_score(4, 1, 0, 1, los_excess))

        admission = _wound_stay_priced_without_a_weaning_plan(api, officer)

        assert_integer_field(admission.determination, "alos_days_used", DRG_573["alos_days"])
        assert_integer_field(admission.determination, "covered_los_days_used", covered)
        assert_pct(admission.determination, "discharge_payment_pct", expected_pct)
        assert_pct(admission.stay, "discharge_payment_pct", expected_pct)

        review = admission.review
        assert_integer_field(review, "missing_discipline_count", 4)
        assert_integer_field(review, "as_documented_score", expected_score)
        assert_integer_field(review, "effective_score", expected_score)
        assert review["risk_band"] == risk_band_for(expected_score)
        assert review["risk_band"] == RiskBand.MODERATE
        assert review["status"] == ReviewStatus.OPEN
        assert admission.queries == []


def _two_priced_stays_in_one_period(api, officer):
    """Two patients admitted at the epoch and discharged on the same day, both priced in DRAFT."""
    world = fixtures.build_world(api)
    first = fixtures.admitted_stay(api, world)
    second_patient = fixtures.add_patient(api)
    second = fixtures.admitted_stay(
        api,
        world,
        patient_id=second_patient["id"],
        patient_version=second_patient["version"],
    )
    fixtures.advance_clock(api, DISCHARGE_AT_MID_AUGUST, headers=officer)
    first = fixtures.discharged_stay(
        api,
        admission=first,
        discharge_disposition=DischargeDisposition.HOME,
        estimated_cost_cents=ORDINARY_COST_CENTS,
        file_notes=False,
    )
    second = fixtures.discharged_stay(
        api,
        admission=second,
        discharge_disposition=DischargeDisposition.HOME,
        estimated_cost_cents=ORDINARY_COST_CENTS,
        file_notes=False,
    )
    return world, first, second


class TestPeriodLedgerCountsOnlyFinalDeterminations:
    """Two priced stays in one period, only one of which is ever finalized."""

    def test_draft_determinations_contribute_nothing_until_one_of_them_is_finalized(
        self, api, officer, second_analyst
    ):
        """The ledger stays at zero while both determinations are DRAFT, then moves by exactly one.

        Both stays are 14 covered days on the same DRG, so each cascade prices the same
        1,512,000 cents into a DRAFT determination stamped as priced by SYSTEM. A period
        holding two priced-but-unfinalized stays still reports a total of 0 cents and a count
        of 0. Once the first stay's review is cleared and an analyst finalizes it, the total
        rises by that determination's own total and the count by 1 — the second stay, still
        DRAFT, adds nothing and appears in no FINAL listing.

        PRD 3.9: "Second, the incrementally maintained ledger must equal a full recomputation: the period's `total_payment_cents` must equal the sum of the `total_payment_cents` of every determination whose `status` is `FINAL` and whose stay belongs to this period, and its `final_determination_count` must equal the count of those same determinations."
        PRD 3.9: "Determinations in `DRAFT` or `VOIDED` contribute nothing to either figure."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."
        PRD 3.7: "Note that a determination the discharge cascade priced carries `priced_by_user_id` `SYSTEM`, so any analyst may finalize it."

        Design: Corner/calculations/period_ledger_counts_only_final_determinations
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_MID_AUGUST)
        expected_total = _standard_base_cents(DRG_207, covered, True)

        world, first, second = _two_priced_stays_in_one_period(api, officer)

        for admission in (first, second):
            assert admission.determination["status"] == DeterminationStatus.DRAFT
            assert admission.determination["priced_by_user_id"] == SYSTEM_ACTOR
            assert_cents(admission.determination, "total_payment_cents", expected_total)

        assert_period_ledger(fixtures.read_period(api, world.period_id), 0, 0)

        fixtures.resolve_review(
            api, first.review_id, outcome=ReviewOutcome.CLEARED, headers=officer
        )
        finalized = fixtures.finalize(api, first.determination_id, headers=second_analyst)

        assert finalized["status"] == DeterminationStatus.FINAL
        assert finalized["finalized_by_user_id"] == ANALYST_2_ID
        assert_stay_dimensions(
            fixtures.read_stay(api, first.stay_id),
            ClinicalStatus.DISCHARGED,
            PaymentReviewStatus.FINALIZED,
        )
        assert_period_ledger(
            fixtures.read_period(api, world.period_id), expected_total, 1
        )
        assert (
            fixtures.determinations_of(api, second.stay_id, status=DeterminationStatus.FINAL)
            == []
        )

    def test_voiding_the_only_final_determination_returns_the_ledger_to_zero(
        self, api, officer, second_analyst, third_analyst
    ):
        """Unwinding the one FINAL determination puts the period back to 0 cents and 0 count.

        A void of a FINAL determination is a compensating reversal, not an adjustment: the
        period's total falls by exactly the amount the finalization added and the count falls
        by one, returning both to the figures they held while the determination was still a
        draft. The stay itself drops back to PENDING and loses its discharge percentage.

        PRD 3.7: "Voiding a `FINAL` determination is `FINAL → VOIDED`, requires that the acting `X-User-ID` differ from the determination's `finalized_by_user_id`, sets the stay's `payment_review_status` back to `PENDING` and clears `discharge_payment_pct`, and unwinds the ledger exactly: the period's `total_payment_cents` is decreased by this determination's `total_payment_cents` and its `final_determination_count` is decreased by 1, returning both to their pre-finalization values."
        PRD 3.9: "Determinations in `DRAFT` or `VOIDED` contribute nothing to either figure."

        Design: Corner/calculations/period_ledger_counts_only_final_determinations
        """
        covered = day_count(CLOCK_EPOCH, DISCHARGE_AT_MID_AUGUST)
        expected_total = _standard_base_cents(DRG_207, covered, True)

        world, first, _second = _two_priced_stays_in_one_period(api, officer)
        fixtures.resolve_review(
            api, first.review_id, outcome=ReviewOutcome.CLEARED, headers=officer
        )
        fixtures.finalize(api, first.determination_id, headers=second_analyst)
        assert_period_ledger(fixtures.read_period(api, world.period_id), expected_total, 1)

        voided = fixtures.void(api, first.determination_id, headers=third_analyst)

        assert voided["status"] == DeterminationStatus.VOIDED
        assert ANALYST_3_ID != ANALYST_2_ID
        assert_period_ledger(fixtures.read_period(api, world.period_id), 0, 0)

        stay = fixtures.read_stay(api, first.stay_id)
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PENDING)
        assert_unset(stay, "discharge_payment_pct")
