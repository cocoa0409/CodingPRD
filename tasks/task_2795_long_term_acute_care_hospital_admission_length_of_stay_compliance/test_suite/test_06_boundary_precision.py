"""
The exact instants, hours and percentages at which a rule changes its answer.

Three boundaries are pinned here, each tested on the value the specification names and on
the value one unit either side of it. The short-stay outlier threshold is a floored
five-sixths of the DRG's average length of stay and its comparison is inclusive, so 25
covered days is a short stay and 26 is not, and the difference is a 3,600,000-cent swing in
the priced amount. The ventilator-hour intensity criterion is inclusive at 96 hours accrued
inside the hospital, so 95.0 hours prices the stay as site-neutral and 96.0 prices it under
the full prospective system. And the referral-mix ceiling has two boundaries stacked on one
denominator: monitoring is suspended below four admissions, and above it the breach test is
strictly greater, so a share of exactly the threshold is a warning rather than a breach.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    DRG_207_FULL_STANDARD_CENTS,
    DRG_207_SSO_THRESHOLD_DAYS,
    BASE_REFERRAL_THRESHOLD_PCT,
    EXPANDED_REFERRAL_THRESHOLD_PCT,
    DischargeDisposition,
    MonitoringState,
    PaymentVariant,
    QualifyingTrack,
    WeaningPlanStatus,
    assertions,
    factories,
    fixtures,
)

Json = Dict[str, Any]

# The clock never moves in any scenario below. The length-of-stay cases admit with a
# backdated `admitted_at` and discharge at the clock's own epoch, so the covered length of
# stay is the whole-day distance from the backdate to that epoch.
_ADMIT_FOR_24_DAYS = "2026-07-08T00:00:00.000Z"
_ADMIT_FOR_25_DAYS = "2026-07-07T00:00:00.000Z"
_ADMIT_FOR_26_DAYS = "2026-07-06T00:00:00.000Z"

# Well clear of the 25-day short-stay threshold, so a stay backdated here is priced at the
# full amount and the payment variant is the only thing left to move.
_ADMIT_FOR_30_DAYS = "2026-07-02T00:00:00.000Z"

# The estimated cost every stay below reports. It equals the DRG's IPPS-comparable full
# amount, which keeps the high-cost add-on at zero on both variants and leaves the base
# payment as the only moving part.
_ESTIMATED_COST_CENTS = 2400000


def _stay_of_a_new_patient(
    api: Any,
    world: fixtures.World,
    admitted_at: str,
    clinicals: Json,
    expected_track: str,
) -> fixtures.Admission:
    """Admit a freshly registered patient into an existing world at a backdated instant.

    Each case needs its own patient, because a second concurrent stay of the same patient
    is refused outright and a backdated one would collide on the occupancy interval.
    """
    patient = fixtures.add_patient(api)
    return fixtures.admitted_stay(
        api,
        world,
        clinicals=clinicals,
        admitted_at=admitted_at,
        expected_track=expected_track,
        patient_id=patient["id"],
        patient_version=patient["version"],
    )


class TestShortStayOutlierThresholdAtTwentyFiveDays:
    """The floored threshold of 25 days, and the inclusive comparison against it."""

    @pytest.mark.parametrize(
        "admitted_at,expected_covered_los,expected_flag",
        [
            (_ADMIT_FOR_24_DAYS, 24, True),
            (_ADMIT_FOR_25_DAYS, 25, True),
            (_ADMIT_FOR_26_DAYS, 26, False),
        ],
    )
    def test_the_short_stay_flag_holds_through_25_covered_days_and_drops_at_26(
        self, api, admitted_at, expected_covered_los, expected_flag
    ):
        """A covered stay of 25 days is a short stay; 26 days is not.

        The DRG in force has an average length of stay of 30 days, so the threshold is
        five-sixths of 30 floored to 25. The flag is set when the covered length of stay is
        less than or equal to that figure, which makes 25 the last day inside the reduction
        and 26 the first day outside it. Twenty-four days is included as the value one below
        the boundary, where the flag must still be set.

        PRD 3.6: "Alongside it, `sso_threshold_days` is computed as five-sixths of the `alos_days` of the DRG in force, rounded **down** to a whole number and never rounded to nearest."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."
        PRD 2.5: "The day count between two instants is the difference between their UTC *calendar dates*, expressed in whole days; the later day is not itself counted."

        Design: Difficulty/boundary_precision_check/sso_threshold_at_25_days_versus_26_days
        """
        world = fixtures.build_world(api)
        admission = _stay_of_a_new_patient(
            api, world, admitted_at, factories.PMV_CLINICALS, QualifyingTrack.PMV
        )
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        stay = admission.stay
        assertions.assert_integer_field(stay, "covered_los_days", expected_covered_los)
        assertions.assert_integer_field(
            stay, "sso_threshold_days", DRG_207_SSO_THRESHOLD_DAYS
        )
        assert stay["short_stay_outlier_applied"] is expected_flag
        assert assertions.sso_threshold_days(30) == DRG_207_SSO_THRESHOLD_DAYS

    @pytest.mark.parametrize(
        "admitted_at,expected_covered_los,expected_base_cents,expected_pct",
        [
            (_ADMIT_FOR_24_DAYS, 24, 2400000, 40.00),
            (_ADMIT_FOR_25_DAYS, 25, 2400000, 40.00),
            (_ADMIT_FOR_26_DAYS, 26, DRG_207_FULL_STANDARD_CENTS, 100.00),
        ],
    )
    def test_the_priced_amount_jumps_two_and_a_half_fold_when_the_flag_drops_at_26_days(
        self, api, admitted_at, expected_covered_los, expected_base_cents, expected_pct
    ):
        """At 25 days the base is the IPPS-comparable full amount; at 26 it is the full DRG.

        With the flag set, the standard base is the smallest of three candidates: the
        per-diem component of 6,000,000 divided by 30 and multiplied by the covered days,
        capped at the full amount; 120 percent of the IPPS-comparable per diem for those
        days; and the IPPS-comparable full amount of 2,400,000. At 25 days those come out at
        5,000,000, 2,700,000 and 2,400,000, so the smallest is the flat IPPS-comparable full
        amount. At 26 days the flag is clear and no comparison happens at all: the base is
        the full MS-LTC-DRG amount of 6,000,000. One extra covered day therefore moves the
        payment by 3,600,000 cents and the discharge percentage from 40.00 to 100.00.

        PRD 3.7: "When the stay's `short_stay_outlier_applied` is false, the standard base is simply `full_standard_amount_cents`."
        PRD 3.7: "The standard base is the minimum of those three."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/sso_threshold_at_25_days_versus_26_days
        """
        world = fixtures.build_world(api)
        admission = _stay_of_a_new_patient(
            api, world, admitted_at, factories.PMV_CLINICALS, QualifyingTrack.PMV
        )
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.HOME,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assertions.assert_integer_field(
            determination, "covered_los_days_used", expected_covered_los
        )
        assertions.assert_cents(
            determination, "full_standard_amount_cents", DRG_207_FULL_STANDARD_CENTS
        )
        assertions.assert_cents(determination, "base_payment_cents", expected_base_cents)
        assertions.assert_cents(determination, "outlier_payment_cents", 0)
        assertions.assert_cents(determination, "total_payment_cents", expected_base_cents)
        assertions.assert_pct(determination, "discharge_payment_pct", expected_pct)
        assertions.assert_pct(admission.stay, "discharge_payment_pct", expected_pct)


class TestVentilatorHourBoundaryAtNinetySix:
    """The 96-hour intensity criterion, which selects the payment variant outright."""

    @pytest.mark.parametrize("seeded_hours,expected_total", [(95, 95.0), (96, 96.0), (97, 97.0)])
    def test_the_cumulative_hour_total_stands_at_the_seed_when_every_trial_adds_none(
        self, api, seeded_hours, expected_total
    ):
        """A plan seeded with hours and driven through three zero-hour trials keeps its seed.

        The cumulative total is the create-time seed plus the hours reported on each trial
        record, so three failed trials that each report zero hours since the last record
        leave the total exactly where the seed put it. That is what makes the seed a precise
        instrument for landing on either side of the variant boundary, and the three attempts
        are also what a ventilator-dependent close requires.

        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."
        PRD 3.4: "Every record, whatever its outcome, increases `sbt_attempt_count` by 1 and adds `vent_hours_since_last` to `vent_hours_total`."

        Design: Difficulty/boundary_precision_check/vent_hours_at_95_versus_96_flips_the_payment_variant
        """
        world = fixtures.build_world(api)
        admission = _stay_of_a_new_patient(
            api, world, _ADMIT_FOR_30_DAYS, factories.WOUND_CLINICALS, QualifyingTrack.COMPLEX_WOUND
        )
        plan = fixtures.vent_dependent_plan(
            api, admission, seed_vent_hours=seeded_hours, vent_hours_since_last=0
        )

        assertions.assert_vent_hours(plan, "vent_hours_total", expected_total)
        assertions.assert_integer_field(plan, "sbt_attempt_count", 3)
        assert plan["status"] == WeaningPlanStatus.VENT_DEPENDENT

    @pytest.mark.parametrize(
        "seeded_hours,expected_variant,expected_base_cents,expected_pct",
        [
            (95, PaymentVariant.SITE_NEUTRAL, 2400000, 40.00),
            (96, PaymentVariant.STANDARD_LTCH_PPS, DRG_207_FULL_STANDARD_CENTS, 100.00),
            (97, PaymentVariant.STANDARD_LTCH_PPS, DRG_207_FULL_STANDARD_CENTS, 100.00),
        ],
    )
    def test_ninety_six_accumulated_hours_flips_the_variant_from_site_neutral_to_standard(
        self, api, seeded_hours, expected_variant, expected_base_cents, expected_pct
    ):
        """95.0 hours prices site-neutral; 96.0 hours meets the inclusive threshold.

        Both stays are identical complex-wound admissions whose referral records one ICU
        day, which is below the three-day intensity criterion, and a prior acute discharge,
        which the variant selection requires. The accumulated ventilator hours are therefore
        the only discriminator. The comparison is inclusive at 96, so 95.0 leaves no
        intensity criterion satisfied and the stay is site-neutral, while 96.0 satisfies one
        and the stay is priced under the full prospective system. The covered length of stay
        is 30 days against a threshold of 25, so no short-stay reduction is in play on
        either side and the whole difference is the variant.

        PRD 3.7: "Then at least one of two intensity criteria must hold: the referral's `icu_days_at_referral` is at least 3, **or** the stay has a weaning plan whose `vent_hours_total` has reached at least 96 ventilator hours — four full days of ventilation accrued inside the LTCH, inclusive at the boundary, so 95.0 hours does not qualify and 96.0 does."
        PRD 3.7: "When the referral records a prior acute discharge and at least one intensity criterion holds, `payment_variant` is `STANDARD_LTCH_PPS`; in every other case it is `SITE_NEUTRAL`."
        PRD 3.7: "The site-neutral base is the smaller of the DRG's `ipps_comparable_full_cents` and the stay's `estimated_cost_cents`, with a null `estimated_cost_cents` treated as 0."

        Design: Difficulty/boundary_precision_check/vent_hours_at_95_versus_96_flips_the_payment_variant
        """
        world = fixtures.build_world(api)
        admission = _stay_of_a_new_patient(
            api, world, _ADMIT_FOR_30_DAYS, factories.WOUND_CLINICALS, QualifyingTrack.COMPLEX_WOUND
        )
        fixtures.vent_dependent_plan(
            api, admission, seed_vent_hours=seeded_hours, vent_hours_since_last=0
        )
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.SNF,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        assertions.assert_integer_field(admission.stay, "covered_los_days", 30)
        assert admission.stay["short_stay_outlier_applied"] is False

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["payment_variant"] == expected_variant
        assertions.assert_cents(determination, "base_payment_cents", expected_base_cents)
        assertions.assert_cents(determination, "outlier_payment_cents", 0)
        assertions.assert_cents(determination, "total_payment_cents", expected_base_cents)
        assertions.assert_pct(determination, "discharge_payment_pct", expected_pct)

    @pytest.mark.parametrize("seeded_hours", [95, 96])
    def test_both_variant_amounts_are_stored_on_either_side_of_the_hour_boundary(
        self, api, seeded_hours
    ):
        """Whichever variant is selected, both amounts read off the same determination.

        The point of storing both is that an auditor can compare what the hospital was paid
        against what a general hospital would have received without re-running anything. The
        standard amount is the full MS-LTC-DRG figure of 6,000,000 and the site-neutral
        amount is the IPPS-comparable full amount of 2,400,000, and neither figure depends on
        which of the two the selection landed on — only `base_payment_cents` does.

        PRD 3.7: "Both are stored on every determination regardless of which variant was selected."
        PRD 3.7: "Every determination stores **both** payment variants, always, whichever one is selected."
        PRD 3.7: "Then `base_payment_cents` is the standard base when `payment_variant` is `STANDARD_LTCH_PPS` and the site-neutral base when it is `SITE_NEUTRAL`; `outlier_payment_cents` is the add-on computed from `base_payment_cents`; and `total_payment_cents` is `base_payment_cents` plus `outlier_payment_cents`, in whole cents."

        Design: Difficulty/boundary_precision_check/vent_hours_at_95_versus_96_flips_the_payment_variant
        """
        world = fixtures.build_world(api)
        admission = _stay_of_a_new_patient(
            api, world, _ADMIT_FOR_30_DAYS, factories.WOUND_CLINICALS, QualifyingTrack.COMPLEX_WOUND
        )
        fixtures.vent_dependent_plan(
            api, admission, seed_vent_hours=seeded_hours, vent_hours_since_last=0
        )
        admission = fixtures.discharged_stay(
            api,
            admission=admission,
            discharge_disposition=DischargeDisposition.SNF,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        determination = fixtures.sole_determination(api, admission.stay_id)
        assertions.assert_cents(
            determination, "standard_variant_amount_cents", DRG_207_FULL_STANDARD_CENTS
        )
        assertions.assert_cents(
            determination, "site_neutral_variant_amount_cents", 2400000
        )


def _admit_from_source(api: Any, world: fixtures.World, hospital_id: str) -> None:
    """Admit one freshly registered patient on a referral from the named source.

    Every admission needs its own patient, because a patient already holding a live stay
    cannot be admitted again; the referral source is the only thing that varies.
    """
    patient = fixtures.add_patient(api)
    fixtures.admitted_stay(
        api,
        world,
        patient_id=patient["id"],
        patient_version=patient["version"],
        hospital_id=hospital_id,
    )


class TestReferralShareBoundariesAndTheMinimumAdmissionGuard:
    """Two boundaries stacked on one denominator: the guard, and the strict comparisons."""

    def test_a_period_below_four_admissions_leaves_every_source_compliant(self, api):
        """At three admissions a two-thirds share is still labelled compliant.

        The share itself is computed and stored throughout — the sole referral source of a
        one-admission period reads 100.00 — but the label is suppressed while the period
        holds fewer than four admissions, because a share drawn from so small a denominator
        says nothing about the referral mix. With two admissions of three, the dominant
        source reads 66.67, which is far above its 25.00 threshold, and is nonetheless
        compliant.

        PRD 3.3: "A hospital's `share_pct` is its `admissions_in_period` divided by the period's `total_admissions`, multiplied by 100 and rounded half up to two decimal places; when the denominator is zero, `share_pct` is stored as 0.00."
        PRD 3.3: "If the period's `total_admissions` is fewer than 4, the mix is too thin to judge and `monitoring_state` is `COMPLIANT` regardless of the computed share; note that `share_pct` is still stored in that case, so a hospital may legitimately show a share of 100.00 while sitting at `COMPLIANT`."

        Design: Difficulty/boundary_precision_check/referral_share_at_exactly_25_and_50_percent_with_the_min_admission_guard
        """
        world = fixtures.build_world(api, hospital={"name": "Riverside Regional"})
        metro = fixtures.add_hospital(api, name="Metro General")

        _admit_from_source(api, world, world.hospital_id)
        assertions.assert_hospital_posture(
            fixtures.read_hospital(api, world.hospital_id),
            admissions_in_period=1,
            share_pct=100.00,
            monitoring_state=MonitoringState.COMPLIANT,
        )

        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, metro["id"])

        period = fixtures.read_period(api, world.period_id)
        assertions.assert_integer_field(period, "total_admissions", 3)

        riverside = fixtures.read_hospital(api, world.hospital_id)
        assertions.assert_hospital_posture(
            riverside,
            admissions_in_period=2,
            share_pct=66.67,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        assertions.assert_pct(riverside, "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assertions.assert_hospital_posture(
            fixtures.read_hospital(api, metro["id"]),
            admissions_in_period=1,
            share_pct=33.33,
            monitoring_state=MonitoringState.COMPLIANT,
        )

    def test_the_fourth_admission_switches_monitoring_on_and_relabels_every_source(self, api):
        """The admission that lifts the period to four rewrites all three sources at once.

        Nothing about the two-admission source changes clinically at the fourth admission,
        yet its label moves from compliant to breached, because the guard lifts and its
        50.00 share is now measured against a 25.00 threshold. The source being admitted is
        a third hospital that had no admissions at all, so this is also the case the
        specification calls out: one admission relabels a hospital other than the one it
        touched. Both single-admission sources land on exactly 25.00, which is a warning and
        not a breach, and the counters must still sum to the period's denominator.

        PRD 3.3: "Because the denominator moved, `share_pct`, `threshold_pct` and `monitoring_state` are then recomputed for every referring hospital with a non-zero `admissions_in_period` plus any hospital whose counter just changed."
        PRD 3.3: "A single admission can therefore push a *different* hospital into `WARNING` or out of `BREACHED`."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."
        PRD 3.3: "The denominator is the period's `total_admissions`, which counts every `Stay` in the period whose `counts_toward_admission_threshold` is true."

        Design: Difficulty/boundary_precision_check/referral_share_at_exactly_25_and_50_percent_with_the_min_admission_guard
        """
        world = fixtures.build_world(api, hospital={"name": "Riverside Regional"})
        metro = fixtures.add_hospital(api, name="Metro General")
        suburban = fixtures.add_hospital(api, name="Suburban Community")

        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, metro["id"])
        _admit_from_source(api, world, suburban["id"])

        period = fixtures.read_period(api, world.period_id)
        assertions.assert_integer_field(period, "total_admissions", 4)

        riverside = fixtures.read_hospital(api, world.hospital_id)
        assertions.assert_hospital_posture(
            riverside,
            admissions_in_period=2,
            share_pct=50.00,
            monitoring_state=MonitoringState.BREACHED,
        )
        metro = fixtures.read_hospital(api, metro["id"])
        assertions.assert_hospital_posture(
            metro,
            admissions_in_period=1,
            share_pct=BASE_REFERRAL_THRESHOLD_PCT,
            monitoring_state=MonitoringState.WARNING,
        )
        suburban = fixtures.read_hospital(api, suburban["id"])
        assertions.assert_hospital_posture(
            suburban,
            admissions_in_period=1,
            share_pct=BASE_REFERRAL_THRESHOLD_PCT,
            monitoring_state=MonitoringState.WARNING,
        )
        assertions.assert_counters_reconcile(period, [riverside, metro, suburban])

    def test_shares_of_exactly_25_and_exactly_50_percent_are_warnings_not_breaches(self, api):
        """A source sitting precisely on its own ceiling is warned, never breached.

        Both ceilings appear in one period of four admissions. The co-located source carries
        the expanded 50.00 ceiling and supplies two of the four, landing on exactly 50.00;
        the ordinary source carries 25.00 and supplies one, landing on exactly 25.00. The
        breach test is strictly greater in both cases, so neither is a breach, and both
        shares clear their respective warning floors of 45.00 and 20.00, so both are
        warnings.

        PRD 3.3: "Its `threshold_pct` is recomputed at the same time from the rule in §3.1 — 50.00 for a co-located or critical-access source, 25.00 otherwise."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."
        PRD 3.3: "Otherwise, if `share_pct` is strictly greater than `threshold_pct` reduced by a warning margin of 5.00 percentage points, `monitoring_state` becomes `WARNING`."

        Design: Difficulty/boundary_precision_check/referral_share_at_exactly_25_and_50_percent_with_the_min_admission_guard
        """
        world = fixtures.build_world(
            api, hospital={"name": "Riverside Regional", "is_colocated": True}
        )
        metro = fixtures.add_hospital(api, name="Metro General")
        suburban = fixtures.add_hospital(api, name="Suburban Community")

        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, metro["id"])
        _admit_from_source(api, world, suburban["id"])

        period = fixtures.read_period(api, world.period_id)
        assertions.assert_integer_field(period, "total_admissions", 4)

        riverside = fixtures.read_hospital(api, world.hospital_id)
        assertions.assert_pct(
            riverside, "threshold_pct", EXPANDED_REFERRAL_THRESHOLD_PCT
        )
        assertions.assert_hospital_posture(
            riverside,
            admissions_in_period=2,
            share_pct=EXPANDED_REFERRAL_THRESHOLD_PCT,
            monitoring_state=MonitoringState.WARNING,
        )

        metro_record = fixtures.read_hospital(api, metro["id"])
        assertions.assert_pct(metro_record, "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assertions.assert_hospital_posture(
            metro_record,
            admissions_in_period=1,
            share_pct=BASE_REFERRAL_THRESHOLD_PCT,
            monitoring_state=MonitoringState.WARNING,
        )

    def test_one_admission_past_the_ceiling_breaches_while_the_warning_floor_stays_exclusive(
        self, api
    ):
        """A fifth admission carries the co-located source past 50.00 and drops another to its floor.

        The co-located source moves from two of four, which is exactly its 50.00 ceiling and
        a warning, to three of five, which is 60.00 and therefore a breach — the value one
        admission above the boundary. The same denominator move takes the ordinary source
        from 25.00 down to exactly 20.00, which is its 25.00 ceiling reduced by the 5.00
        margin. That comparison is strictly greater too, so landing precisely on the floor is
        compliant rather than a warning, and the source that was warned a moment ago is now
        clear.

        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."
        PRD 3.3: "Otherwise, if `share_pct` is strictly greater than `threshold_pct` reduced by a warning margin of 5.00 percentage points, `monitoring_state` becomes `WARNING`."
        PRD 3.3: "In every other case it is `COMPLIANT`."

        Design: Difficulty/boundary_precision_check/referral_share_at_exactly_25_and_50_percent_with_the_min_admission_guard
        """
        world = fixtures.build_world(
            api, hospital={"name": "Riverside Regional", "is_colocated": True}
        )
        metro = fixtures.add_hospital(api, name="Metro General")
        suburban = fixtures.add_hospital(api, name="Suburban Community")

        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, world.hospital_id)
        _admit_from_source(api, world, metro["id"])
        _admit_from_source(api, world, suburban["id"])
        _admit_from_source(api, world, world.hospital_id)

        period = fixtures.read_period(api, world.period_id)
        assertions.assert_integer_field(period, "total_admissions", 5)

        riverside = fixtures.read_hospital(api, world.hospital_id)
        assertions.assert_hospital_posture(
            riverside,
            admissions_in_period=3,
            share_pct=60.00,
            monitoring_state=MonitoringState.BREACHED,
        )
        metro_record = fixtures.read_hospital(api, metro["id"])
        assertions.assert_hospital_posture(
            metro_record,
            admissions_in_period=1,
            share_pct=20.00,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        suburban_record = fixtures.read_hospital(api, suburban["id"])
        assertions.assert_hospital_posture(
            suburban_record,
            admissions_in_period=1,
            share_pct=20.00,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        assertions.assert_counters_reconcile(
            period, [riverside, metro_record, suburban_record]
        )
