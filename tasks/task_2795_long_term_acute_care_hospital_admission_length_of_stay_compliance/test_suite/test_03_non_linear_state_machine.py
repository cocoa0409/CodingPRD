"""
Paths that re-enter a state the record had already left.

Two of them are specified. The ventilator weaning protocol oscillates: a plan that reached
`PROGRESSING` absorbs one failed trial without moving, drops to `REGRESSED` on the second
consecutive failure, and climbs back to `PROGRESSING` on the next tolerated trial, with
`current_step` walking 2 → 2 → 1 → 2 while the cumulative ventilator hours only ever grow.
A stay does the same thing across rows rather than within one: a `DISCHARGED` stay is
reopened to `ADMITTED` because a later readmission of the same patient was folded into it,
and the second discharge continues the length-of-stay count instead of restarting it.
"""

from test_helpers import (
    ANALYST_2_HEADERS,
    CLOCK_EPOCH,
    ClinicalStatus,
    DischargeDisposition,
    PaymentReviewStatus,
    ReviewOutcome,
    WeaningPlanStatus,
    assert_cents,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    assert_stay_dimensions,
    assert_unset,
    assert_vent_hours,
    fixtures,
)

# ── The weaning oscillation ──────────────────────────
# The plan opens with 90 ventilator hours already accrued inside the LTCH, so the trials
# below land the cumulative total on 97.0 without any of them being large.
_PLAN_SEED_VENT_HOURS = 90


def _plan_progressed_twice(api):
    """A PMV stay whose weaning plan has been carried to `PROGRESSING` at step 2.

    The clock is never advanced in this scenario, so the admission, the notes, the plan and
    every trial share the one logical instant; that is what keeps the documentation window
    of each tolerated trial satisfied.
    """
    admission = fixtures.admitted_stay(api)
    plan = fixtures.open_weaning_plan(
        api, admission.stay_id, vent_hours_total=_PLAN_SEED_VENT_HOURS
    )
    step_one = fixtures.tolerated_sbt(
        api, admission.stay_id, plan["id"], sbt_hours=2, vent_hours_since_last=5
    )
    step_two = fixtures.tolerated_sbt(
        api, admission.stay_id, plan["id"], sbt_hours=4, vent_hours_since_last=0
    )
    return admission, plan, step_one, step_two


class TestWeaningPlanOscillation:
    """The hysteresis counter that decides when a progressing plan actually regresses."""

    def test_the_first_failed_trial_leaves_the_plan_progressing_at_step_two(self, api):
        """One failed trial on a progressing plan moves the counter, not the state.

        The plan reaches `PROGRESSING` with `current_step` 2 after two tolerated trials.
        The next trial fails, which takes `consecutive_failed_sbt` from 0 to 1 — still below
        2 — so the plan self-loops in `PROGRESSING` and `current_step` is untouched. The
        attempt count and the cumulative ventilator hours move anyway, because they move on
        every record regardless of outcome: 3 attempts and 90 + 5 + 0 + 1 = 96.0 hours.

        PRD 3.4: "A `FAILED` record carries no documentation precondition and its effect depends on the running count."
        PRD 3.4: "If the resulting `consecutive_failed_sbt` is still below 2, the plan simply stays where it was — `SBT_TRIAL` self-loops to `SBT_TRIAL`, `PROGRESSING` self-loops to `PROGRESSING` — and `current_step` is untouched."
        PRD 3.4: "It increases `sbt_attempt_count` by 1, increases `consecutive_failed_sbt` by 1, and adds `vent_hours_since_last` to `vent_hours_total`."

        Design: Difficulty/non_linear_state_machine/weaning_plan_progresses_regresses_and_progresses_again
        """
        _admission, plan, step_one, step_two = _plan_progressed_twice(api)

        assert step_one["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(step_one, "current_step", 1)
        assert step_one["liberation_eligible"] is False
        assert step_two["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(step_two, "current_step", 2)
        assert_integer_field(step_two, "consecutive_failed_sbt", 0)
        assert step_two["liberation_eligible"] is True

        after_first_failure = fixtures.failed_sbt(
            api, plan["id"], sbt_hours=1, vent_hours_since_last=1
        )

        assert after_first_failure["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(after_first_failure, "current_step", 2)
        assert_integer_field(after_first_failure, "consecutive_failed_sbt", 1)
        assert_integer_field(after_first_failure, "sbt_attempt_count", 3)
        assert_vent_hours(after_first_failure, "vent_hours_total", 96.0)
        assert after_first_failure["liberation_eligible"] is True

        reread = fixtures.read_plan(api, plan["id"])
        assert reread["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(reread, "current_step", 2)
        assert_integer_field(reread, "consecutive_failed_sbt", 1)

    def test_the_second_consecutive_failure_regresses_the_plan_to_step_one(self, api):
        """The second failure in a row is the one that drops the plan out of PROGRESSING.

        With `consecutive_failed_sbt` already at 1, a second failed trial takes it to 2,
        which is the threshold: `current_step` is reduced by 1, from 2 to 1, the plan moves
        `PROGRESSING → REGRESSED`, and `liberation_eligible` is recomputed against the
        two-step requirement, so a plan sitting at step 1 loses its eligibility. The
        ventilator total keeps climbing across the regression, to 97.0 hours.

        PRD 3.4: "If the resulting `consecutive_failed_sbt` reaches 2 or more, the plan regresses: `current_step` is reduced by 1 but never below 0, `liberation_eligible` is recomputed against the 2-step requirement, and the plan moves `SBT_TRIAL → REGRESSED` or `PROGRESSING → REGRESSED`."
        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."

        Design: Difficulty/non_linear_state_machine/weaning_plan_progresses_regresses_and_progresses_again
        """
        _admission, plan, _step_one, step_two = _plan_progressed_twice(api)
        assert step_two["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(step_two, "current_step", 2)

        after_first_failure = fixtures.failed_sbt(
            api, plan["id"], sbt_hours=1, vent_hours_since_last=1
        )
        assert after_first_failure["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(after_first_failure, "consecutive_failed_sbt", 1)

        after_second_failure = fixtures.failed_sbt(
            api, plan["id"], sbt_hours=1, vent_hours_since_last=1
        )

        assert after_second_failure["status"] == WeaningPlanStatus.REGRESSED
        assert_integer_field(after_second_failure, "current_step", 1)
        assert_integer_field(after_second_failure, "consecutive_failed_sbt", 2)
        assert_integer_field(after_second_failure, "sbt_attempt_count", 4)
        assert after_second_failure["liberation_eligible"] is False
        assert_vent_hours(after_second_failure, "vent_hours_total", 97.0)
        assert_vent_hours(after_second_failure, "max_tolerated_sbt_hours", 4)

        reread = fixtures.read_plan(api, plan["id"])
        assert reread["status"] == WeaningPlanStatus.REGRESSED
        assert_integer_field(reread, "current_step", 1)
        assert reread["liberation_eligible"] is False

    def test_a_tolerated_trial_returns_the_regressed_plan_to_progressing_at_step_two(self, api):
        """The regression is not terminal: the next tolerated trial climbs straight back.

        The whole walk is one plan: `SBT_TRIAL → PROGRESSING` on the first tolerated trial,
        a self-loop in `PROGRESSING` on the second, a self-loop again when the first failure
        is absorbed, `PROGRESSING → REGRESSED` on the second consecutive failure, and finally
        `REGRESSED → PROGRESSING` on the fifth record. That last record is a progression like
        any other, so `current_step` rises from 1 back to 2, `consecutive_failed_sbt` resets
        to 0 and `liberation_eligible` becomes true again. Its `sbt_hours` of 3 does not
        displace the 4 already banked, because the field keeps the larger of the two.

        PRD 3.4: "A `TOLERATED` record is a progression."
        PRD 3.4: "It increases `current_step` by 1, resets `consecutive_failed_sbt` to 0, sets `max_tolerated_sbt_hours` to the larger of its previous value and this trial's `sbt_hours`, stamps `last_progression_at` with the current logical instant, and recomputes `liberation_eligible` as true exactly when `current_step` has reached at least 2."
        PRD 3.4: "From `SBT_TRIAL` the plan moves to `PROGRESSING`; from `PROGRESSING` it takes the self-loop back to `PROGRESSING`; from `REGRESSED` it moves back to `PROGRESSING`."
        PRD 3.4: "Because a tolerated record resets the consecutive counter, a plan may oscillate `PROGRESSING → REGRESSED → PROGRESSING` indefinitely."

        Design: Difficulty/non_linear_state_machine/weaning_plan_progresses_regresses_and_progresses_again
        """
        admission, plan, step_one, step_two = _plan_progressed_twice(api)

        assert plan["status"] == WeaningPlanStatus.SBT_TRIAL
        assert_integer_field(plan, "current_step", 0)
        assert step_one["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(step_one, "current_step", 1)
        assert step_two["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(step_two, "current_step", 2)
        assert_vent_hours(step_two, "max_tolerated_sbt_hours", 4)

        absorbed = fixtures.failed_sbt(api, plan["id"], sbt_hours=1, vent_hours_since_last=1)
        assert absorbed["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(absorbed, "current_step", 2)

        regressed = fixtures.failed_sbt(api, plan["id"], sbt_hours=1, vent_hours_since_last=1)
        assert regressed["status"] == WeaningPlanStatus.REGRESSED
        assert_integer_field(regressed, "current_step", 1)

        recovered = fixtures.tolerated_sbt(
            api, admission.stay_id, plan["id"], sbt_hours=3, vent_hours_since_last=0
        )

        assert recovered["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(recovered, "current_step", 2)
        assert_integer_field(recovered, "consecutive_failed_sbt", 0)
        assert recovered["liberation_eligible"] is True
        assert_vent_hours(recovered, "max_tolerated_sbt_hours", 4)

        reread = fixtures.read_plan(api, plan["id"])
        assert reread["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(reread, "current_step", 2)
        assert_integer_field(reread, "consecutive_failed_sbt", 0)
        assert reread["liberation_eligible"] is True

    def test_the_oscillation_accumulates_five_attempts_and_ninety_seven_ventilator_hours(
        self, api
    ):
        """Every record counts, whichever direction the plan moved.

        Five trials are recorded across the oscillation — tolerated, tolerated, failed,
        failed, tolerated — so `sbt_attempt_count` reads 5. The cumulative ventilator total
        is the opening seed of 90 plus every `vent_hours_since_last` on the way, failed
        trials included: 90 + 5 + 0 + 1 + 1 + 0 = 97.0 hours, with the regression subtracting
        nothing. `last_progression_at` is re-stamped by the final tolerated record, and the
        clock has not moved, so it still reads the logical instant the stay opened at.

        PRD 3.4: "Every record, whatever its outcome, increases `sbt_attempt_count` by 1 and adds `vent_hours_since_last` to `vent_hours_total`."
        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."

        Design: Difficulty/non_linear_state_machine/weaning_plan_progresses_regresses_and_progresses_again
        """
        admission, plan, _step_one, step_two = _plan_progressed_twice(api)
        assert_integer_field(step_two, "sbt_attempt_count", 2)
        assert_vent_hours(step_two, "vent_hours_total", 95.0)

        third = fixtures.failed_sbt(api, plan["id"], sbt_hours=1, vent_hours_since_last=1)
        assert_integer_field(third, "sbt_attempt_count", 3)
        assert_vent_hours(third, "vent_hours_total", 96.0)

        fourth = fixtures.failed_sbt(api, plan["id"], sbt_hours=1, vent_hours_since_last=1)
        assert_integer_field(fourth, "sbt_attempt_count", 4)
        assert_vent_hours(fourth, "vent_hours_total", 97.0)

        fifth = fixtures.tolerated_sbt(
            api, admission.stay_id, plan["id"], sbt_hours=3, vent_hours_since_last=0
        )

        assert_integer_field(fifth, "sbt_attempt_count", 5)
        assert_vent_hours(fifth, "vent_hours_total", 97.0)
        assert_instant_equals(fifth["last_progression_at"], CLOCK_EPOCH, "last_progression_at")

        reread = fixtures.read_plan(api, plan["id"])
        assert_integer_field(reread, "sbt_attempt_count", 5)
        assert_vent_hours(reread, "vent_hours_total", 97.0)
        assert_unset(reread, "closed_at", "closed_by_physician_id")


# ── The stay reopened by recombination ───────────────
# The parent stay is backdated to 2026-07-18 and discharged at the clock epoch, which is
# fourteen calendar days later; the readmission lands two days after that discharge, well
# inside the three-day recombination window, and the reopened parent runs six further days.
_PARENT_ADMITTED_AT = "2026-07-18T00:00:00.000Z"
_CHILD_ADMITTED_AT = "2026-08-03T00:00:00.000Z"
_SECOND_DISCHARGE_AT = "2026-08-09T00:00:00.000Z"
_ESTIMATED_COST_CENTS = 1000000
# 90,000 IPPS-comparable cents per diem x 14 covered days x 1.20, the smallest of the three
# short-stay candidates for this DRG.
_FIRST_DETERMINATION_CENTS = 1512000


def _finalized_parent_stay(api):
    """A stay admitted on 2026-07-18, discharged at the epoch, cleared and finalized.

    No interdisciplinary notes are filed, which is what keeps the denial-risk score at 67
    and the band at `MODERATE`, so the discharge cascade auto-issues no query and the review
    can be resolved `CLEARED` straight from `OPEN`.
    """
    admission = fixtures.admitted_stay(api, admitted_at=_PARENT_ADMITTED_AT)
    fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.ACUTE_TRANSFER,
        estimated_cost_cents=_ESTIMATED_COST_CENTS,
        file_notes=False,
    )
    fixtures.resolve_review(
        api,
        fixtures.sole_review(api, admission.stay_id)["id"],
        outcome=ReviewOutcome.CLEARED,
        resolution_note="Acute transfer documented; the moderate band is accepted.",
    )
    fixtures.finalize(
        api, fixtures.sole_determination(api, admission.stay_id)["id"], headers=ANALYST_2_HEADERS
    )
    return admission


def _readmit_same_patient(api, admission):
    """Re-refer and readmit the same patient at 2026-08-03, two days after the discharge."""
    fixtures.advance_clock(api, _CHILD_ADMITTED_AT)
    patient = fixtures.read_patient(api, admission.world.patient_id)
    referral = fixtures.qualified_referral(
        api, admission.world, patient_version=patient["version"]
    )
    return fixtures.admit(api, referral["id"])


class TestRecombinationReopensADischargedStay:
    """`DISCHARGED → ADMITTED`, a transition only another stay's fold can cause."""

    def test_the_fold_reopens_the_parent_and_terminates_the_child(self, api):
        """One recombine call moves both stays, in opposite directions.

        The parent is a stay that had reached `DISCHARGED`, been priced, cleared and
        finalized — as far along the lifecycle as a stay goes. Folding the later readmission
        into it reopens it: `clinical_status` returns to `ADMITTED`, `discharged_at` and
        `discharge_disposition` are cleared, `resumed_at` takes the child's `admitted_at` of
        2026-08-03, `carried_los_days` freezes at the fourteen days from 2026-07-18 to the
        first discharge, and `payment_review_status` reverts to `PENDING`. The child takes the
        terminal `RECOMBINED` and stops counting as an admission.

        PRD 3.5: "The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."
        PRD 3.5: "The **parent** is reopened, moving `DISCHARGED → ADMITTED`."
        PRD 3.5: "Its `carried_los_days` is frozen at the whole-day count from its `admitted_at` to its `discharged_at` — the covered days already banked from the pre-recombination segment — its `resumed_at` is stamped with the child's `admitted_at`, and both its `discharged_at` and its `discharge_disposition` are cleared to null."
        PRD 3.5: "Its `payment_review_status` reverts to `PENDING`."

        Design: Difficulty/non_linear_state_machine/recombination_returns_discharged_stay_to_admitted
        """
        admission = _finalized_parent_stay(api)
        parent_before = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(
            parent_before, ClinicalStatus.DISCHARGED, PaymentReviewStatus.FINALIZED
        )
        assert_integer_field(parent_before, "covered_los_days", 14)
        assert_integer_field(parent_before, "carried_los_days", 0)
        assert_instant_equals(parent_before["discharged_at"], CLOCK_EPOCH, "discharged_at")

        child = _readmit_same_patient(api, admission)
        assert_stay_dimensions(child, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_instant_equals(child["admitted_at"], _CHILD_ADMITTED_AT, "admitted_at")

        fixtures.recombine(api, child["id"], admission.stay_id)

        folded_child = fixtures.read_stay(api, child["id"])
        assert folded_child["clinical_status"] == ClinicalStatus.RECOMBINED
        assert folded_child["counts_toward_admission_threshold"] is False
        assert folded_child["interrupted_parent_stay_id"] == admission.stay_id

        reopened = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(reopened, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_unset(reopened, "discharged_at", "discharge_disposition")
        assert_instant_equals(reopened["resumed_at"], _CHILD_ADMITTED_AT, "resumed_at")
        assert_instant_equals(reopened["resumed_at"], child["admitted_at"], "resumed_at")
        assert_integer_field(reopened, "carried_los_days", 14)

    def test_the_reopened_parent_combines_its_banked_days_with_the_second_segment(self, api):
        """The second discharge continues the length-of-stay count instead of restarting it.

        After the fold the parent carries fourteen banked days and a `resumed_at` of
        2026-08-03. The second discharge is stamped at 2026-08-09, so the new segment is the
        six whole days from `resumed_at`, measured from `resumed_at` rather than from the
        original `admitted_at`. With no interruption days to net out, `covered_los_days`
        settles at 14 + 6 = 20, which is still at or below this DRG's short-stay threshold of
        twenty-five days, so the short-stay flag is raised again.

        PRD 3.6: "The segment start is the stay's `resumed_at` when that field is non-null, and otherwise its `admitted_at`."
        PRD 3.6: "The stay's `covered_los_days` is then `carried_los_days` plus that segment length, minus `interruption_days_total`."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."

        Design: Difficulty/non_linear_state_machine/recombination_returns_discharged_stay_to_admitted
        """
        admission = _finalized_parent_stay(api)
        child = _readmit_same_patient(api, admission)
        fixtures.recombine(api, child["id"], admission.stay_id)

        reopened = fixtures.read_stay(api, admission.stay_id)
        assert reopened["clinical_status"] == ClinicalStatus.ADMITTED
        assert_integer_field(reopened, "carried_los_days", 14)
        assert_integer_field(reopened, "interruption_days_total", 0)
        # PRD 3.5 enumerates exactly what the fold clears on the reopened parent —
        # `discharged_at` and `discharge_disposition` — and does not name
        # `covered_los_days` or `sso_threshold_days`, so their post-fold value is not
        # uniquely derivable. The second discharge recomputes both, and that is what
        # the assertions below pin.

        fixtures.advance_clock(api, _SECOND_DISCHARGE_AT)
        discharged = fixtures.discharge(
            api,
            admission.stay_id,
            discharge_disposition=DischargeDisposition.SNF,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        assert discharged["clinical_status"] == ClinicalStatus.DISCHARGED
        assert_instant_equals(
            discharged["discharged_at"], _SECOND_DISCHARGE_AT, "discharged_at"
        )
        assert_integer_field(discharged, "carried_los_days", 14)
        assert_integer_field(discharged, "covered_los_days", 20)
        assert_integer_field(discharged, "sso_threshold_days", 25)
        assert discharged["short_stay_outlier_applied"] is True

        reread = fixtures.read_stay(api, admission.stay_id)
        assert_integer_field(reread, "covered_los_days", 20)
        assert reread["short_stay_outlier_applied"] is True

    def test_the_second_discharge_prices_the_combined_length_of_stay(self, api):
        """The re-entry is visible in money as well as in status.

        The first discharge priced fourteen covered days at 1,512,000 cents — 90,000 IPPS
        per-diem cents times 14 days times 1.20, the smallest of the three short-stay
        candidates — and finalization put exactly that figure into the period ledger. The fold
        reopens the stay and the second discharge prices the combined twenty days: the same
        candidate is still the smallest, at 90,000 x 20 x 1.20 = 2,160,000 cents, against an
        LTCH per-diem candidate of 4,000,000 and an IPPS-comparable full amount of 2,400,000.
        The estimated cost of 1,000,000 cents is far below the 5,160,000-cent outlier
        threshold, so no add-on applies and the total equals the base. The percentage is the
        base over the full standard amount of 6,000,000 cents, which is 36.00.

        PRD 3.7: "The second candidate is the DRG's `ipps_comparable_per_diem_cents` multiplied by the `covered_los_days` and then by 1.20, rounded half up to whole cents — that is, 120 percent of the IPPS-comparable per diem for the days actually delivered."
        PRD 3.7: "The standard base is the minimum of those three."
        PRD 3.7: "Third, if the excess is less than or equal to zero the add-on is 0; otherwise the add-on is 0.80 multiplied by the excess, rounded half up to whole cents."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/recombination_returns_discharged_stay_to_admitted
        """
        admission = _finalized_parent_stay(api)
        first_determination = fixtures.determinations_of(api, admission.stay_id)[0]
        assert_integer_field(first_determination, "covered_los_days_used", 14)
        assert_cents(first_determination, "total_payment_cents", _FIRST_DETERMINATION_CENTS)
        assert_period_ledger(
            fixtures.read_period(api, admission.world.period_id),
            _FIRST_DETERMINATION_CENTS,
            1,
        )

        child = _readmit_same_patient(api, admission)
        fixtures.recombine(api, child["id"], admission.stay_id)
        fixtures.advance_clock(api, _SECOND_DISCHARGE_AT)
        fixtures.discharge(
            api,
            admission.stay_id,
            discharge_disposition=DischargeDisposition.SNF,
            estimated_cost_cents=_ESTIMATED_COST_CENTS,
        )

        drafts = fixtures.determinations_of(api, admission.stay_id, status="DRAFT")
        assert len(drafts) == 1, "expected one draft determination, got {}".format(len(drafts))
        second = drafts[0]

        assert_integer_field(second, "covered_los_days_used", 20)
        assert second["short_stay_outlier_applied"] is True
        assert_cents(second, "base_payment_cents", 2160000)
        assert_cents(second, "outlier_payment_cents", 0)
        assert_cents(second, "total_payment_cents", 2160000)
        assert_pct(second, "discharge_payment_pct", 36.00)

        reread = fixtures.read_stay(api, admission.stay_id)
        assert_pct(reread, "discharge_payment_pct", 36.00)
