"""
Transitions whose legality is decided by a sibling entity rather than by the subject.

Two of them are pinned here. A tolerated spontaneous-breathing trial is legal or illegal
according to the `documented_at` of interdisciplinary notes that belong to the plan's
stay, compared against the plan's own `last_progression_at` — so the very same two notes
license the first progression and are stale for the second, with no state change on the
plan in between. And an admission is legal or illegal according to the `status` of the
`AdmissionCriteriaSet` the referral pinned at screening time, which a third party flips to
`SUPERSEDED` by publishing a newer set; the referral itself never moves.
"""

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    ClinicalStatus,
    CriteriaSetStatus,
    Discipline,
    QualifyingTrack,
    ReferralStatus,
    WeaningPlanStatus,
    assert_instant_equals,
    assert_integer_field,
    assert_vent_hours,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

FIRST_PROGRESSION_AT = "2026-08-02T00:00:00Z"
SECOND_TRIAL_AT = "2026-08-03T00:00:00Z"


def _plan_at_first_progression(api):
    """Admit a stay, file both progression notes, open a plan and take one tolerated trial.

    The two notes and the plan are all created at the clock epoch, so the notes satisfy
    the pre-first-progression window by falling exactly on the plan's `created_at`. The
    trial itself is recorded a day later, which is the instant `last_progression_at` then
    carries.
    """
    admission = fixtures.admitted_stay(api)
    respiratory_note = fixtures.file_note(
        api, admission.stay_id, Discipline.RESPIRATORY_THERAPY
    )
    physician_note = fixtures.file_note(api, admission.stay_id, Discipline.PHYSICIAN)
    plan = fixtures.open_weaning_plan(api, admission.stay_id)
    fixtures.advance_clock(api, FIRST_PROGRESSION_AT)
    progressed = fixtures.record_sbt(
        api, plan["id"], outcome="TOLERATED", sbt_hours=2, vent_hours_since_last=4
    )
    return admission, (respiratory_note, physician_note), plan, progressed


class TestToleratedTrialsAndTheFreshnessOfInterdisciplinaryNotes:
    """The documentation window restarts at every progression."""

    def test_notes_filed_at_the_plans_creation_instant_license_the_first_progression(
        self, api
    ):
        """Notes dated exactly on the plan's `created_at` clear the pre-progression window.

        The plan is opened at the clock epoch, immediately after a respiratory-therapy and
        a physician note stamped at that same instant. Before any progression the window
        is measured against the plan's `created_at`, and the comparison is inclusive, so
        notes falling exactly on that instant are fresh and the tolerated trial is
        accepted. It advances the plan to step 1 and stamps `last_progression_at` with the
        instant the trial was recorded, one day later, which is what leaves the notes
        behind.

        PRD 3.4: "A tolerated record is, however, gated on fresh interdisciplinary documentation: the stay must have at least one note with `discipline` `RESPIRATORY_THERAPY` **and** at least one note with `discipline` `PHYSICIAN` whose `documented_at` is on or after the plan's `last_progression_at`, or — before the first progression, while `last_progression_at` is still null — on or after the plan's `created_at`."
        PRD 3.4: "It increases `current_step` by 1, resets `consecutive_failed_sbt` to 0, sets `max_tolerated_sbt_hours` to the larger of its previous value and this trial's `sbt_hours`, stamps `last_progression_at` with the current logical instant, and recomputes `liberation_eligible` as true exactly when `current_step` has reached at least 2."

        Design: Difficulty/cross_entity_state_dependency/tolerated_sbt_blocked_until_the_idt_notes_are_refreshed
        """
        _admission, notes, plan, progressed = _plan_at_first_progression(api)

        for note in notes:
            assert_instant_equals(note["documented_at"], CLOCK_EPOCH, "documented_at")
        assert_instant_equals(plan["created_at"], CLOCK_EPOCH, "created_at")

        assert progressed["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(progressed, "current_step", 1)
        assert_integer_field(progressed, "sbt_attempt_count", 1)
        assert_integer_field(progressed, "consecutive_failed_sbt", 0)
        assert_vent_hours(progressed, "vent_hours_total", 4.0)
        assert_vent_hours(progressed, "max_tolerated_sbt_hours", 2)
        assert progressed["liberation_eligible"] is False
        assert_instant_equals(
            progressed["last_progression_at"], FIRST_PROGRESSION_AT, "last_progression_at"
        )

    def test_a_second_tolerated_trial_is_refused_while_the_notes_predate_the_progression(
        self, api, nurse
    ):
        """The first progression makes its own licensing notes stale and records nothing.

        Nothing about the plan changed between the accepted trial and the refused one: it
        is still `PROGRESSING` at step 1, and the same respiratory-therapy and physician
        notes are still on file. What moved is `last_progression_at`, which the first
        trial stamped at 2026-08-02, one day after the notes. The second tolerated trial
        therefore finds no note on or after that instant and is refused, and because a
        refused trial is not recorded the attempt count, the step and the cumulative
        ventilator hours all stand where the first trial left them.

        PRD 2.8: "A tolerated spontaneous-breathing trial may be recorded only when the interdisciplinary team has documented the stay since the last progression, else `ERR_IDT_DOCUMENTATION_STALE` (422)."
        PRD 3.4: "Because each tolerated record re-stamps `last_progression_at`, the documentation window restarts every time: two progressions require two rounds of respiratory-therapy and physician notes."

        Design: Difficulty/cross_entity_state_dependency/tolerated_sbt_blocked_until_the_idt_notes_are_refreshed
        """
        _admission, _notes, plan, _progressed = _plan_at_first_progression(api)
        fixtures.advance_clock(api, SECOND_TRIAL_AT)

        refused = api.record_sbt(
            plan["id"],
            factories.sbt_payload(
                outcome="TOLERATED", sbt_hours=3, vent_hours_since_last=2
            ),
            headers=nurse,
        )
        validate_error(refused, ApiErrorId.ERR_IDT_DOCUMENTATION_STALE)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(unchanged, "current_step", 1)
        assert_integer_field(unchanged, "sbt_attempt_count", 1)
        assert_vent_hours(unchanged, "vent_hours_total", 4.0)
        assert_instant_equals(
            unchanged["last_progression_at"], FIRST_PROGRESSION_AT, "last_progression_at"
        )

    def test_refiling_both_disciplines_after_the_progression_unblocks_the_second_trial(
        self, api
    ):
        """A fresh round of both notes restores the window and the retry progresses.

        The refusal is cured on the sibling collection, not on the plan: one new
        respiratory-therapy note and one new physician note are filed at 2026-08-03, on or
        after the `last_progression_at` the first trial stamped, and the identical retry
        then succeeds. Its effects are the ordinary tolerated ones — step 2, so
        `liberation_eligible` turns true, a second attempt counted, `vent_hours_total`
        grown from 4.0 to 6.0 by this trial's 2.0 hours, and `max_tolerated_sbt_hours`
        raised from 2 to this trial's 3. The stay now carries four notes, the two newest
        stamped at the retry instant.

        PRD 3.4: "Missing either note yields `ERR_IDT_DOCUMENTATION_STALE`."
        PRD 3.4: "Every record, whatever its outcome, increases `sbt_attempt_count` by 1 and adds `vent_hours_since_last` to `vent_hours_total`."
        PRD 3.4: "It increases `current_step` by 1, resets `consecutive_failed_sbt` to 0, sets `max_tolerated_sbt_hours` to the larger of its previous value and this trial's `sbt_hours`, stamps `last_progression_at` with the current logical instant, and recomputes `liberation_eligible` as true exactly when `current_step` has reached at least 2."

        Design: Difficulty/cross_entity_state_dependency/tolerated_sbt_blocked_until_the_idt_notes_are_refreshed
        """
        admission, _notes, plan, _progressed = _plan_at_first_progression(api)
        fixtures.advance_clock(api, SECOND_TRIAL_AT)

        fixtures.file_note(api, admission.stay_id, Discipline.RESPIRATORY_THERAPY)
        fixtures.file_note(
            api,
            admission.stay_id,
            Discipline.PHYSICIAN,
            headers=admission.world.physician_headers,
        )

        retried = fixtures.record_sbt(
            api, plan["id"], outcome="TOLERATED", sbt_hours=3, vent_hours_since_last=2
        )
        assert retried["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(retried, "current_step", 2)
        assert_integer_field(retried, "sbt_attempt_count", 2)
        assert_integer_field(retried, "consecutive_failed_sbt", 0)
        assert_vent_hours(retried, "vent_hours_total", 6.0)
        assert_vent_hours(retried, "max_tolerated_sbt_hours", 3)
        assert retried["liberation_eligible"] is True
        assert_instant_equals(
            retried["last_progression_at"], SECOND_TRIAL_AT, "last_progression_at"
        )

        notes, meta = validate_paginated(
            api.list_idt_notes(admission.stay_id, headers=admission.world.physician_headers)
        )
        assert meta["total_count"] == 4
        assert len(notes) == 4
        for note in notes[2:]:
            assert_instant_equals(note["documented_at"], SECOND_TRIAL_AT, "documented_at")


NEWER_CRITERIA_SET = {
    "label": "CS-2026B",
    "effective_from": "2026-02-01",
    "pmv_min_vent_hours": 120,
    "pmv_min_icu_days": 4,
    "wound_min_stage": 4,
    "wound_min_count": 3,
}


def _referral_pinned_to_a_superseded_set(api):
    """A `CRITERIA_MET` referral whose pinned criteria set a later publication superseded.

    The referral is screened against CS-2026A and pins it. The compliance officer then
    publishes CS-2026B with a strictly later `effective_from`, which flips CS-2026A to
    `SUPERSEDED` without touching the referral.
    """
    world = fixtures.build_world(api)
    referral = fixtures.qualified_referral(api, world)
    newer = fixtures.publish_criteria_set(api, **NEWER_CRITERIA_SET)
    return world, referral, newer


class TestAdmissionAgainstAPinnedCriteriaSetAThirdPartySuperseded:
    """Publishing reference data retroactively invalidates a pending admission."""

    def test_admitting_a_referral_pinned_to_a_superseded_set_is_refused(self, api, intake):
        """The pinned set going `SUPERSEDED` blocks the admit and creates nothing.

        The referral is untouched: it screened to `CRITERIA_MET` on the ventilation track,
        it is still `CRITERIA_MET`, and every earlier admission gate passes — the track
        qualifies, the patient holds no live stay, the source is compliant and the default
        admission instant is neither future-dated nor before the acute discharge. The only
        violated rule is the freshness of the criteria set the referral pinned, and because
        the admit is refused no stay comes into being and the period's admission counter
        stays at zero.

        PRD 2.8: "A referral may not be admitted when its `pinned_criteria_set_id` references an `AdmissionCriteriaSet` whose `status` is `SUPERSEDED`; the referral must be re-screened first."
        PRD 3.3: "The admission also does four things beyond the stay itself: the referral's `status` becomes `ADMITTED`, `Patient.open_referral_count` is recomputed to 0, the period's `total_admissions` is increased by 1, and the referring hospital's `admissions_in_period` is increased by 1."

        Design: Difficulty/cross_entity_state_dependency/admit_blocked_after_a_newer_criteria_set_supersedes_the_pinned_one
        """
        world, referral, _newer = _referral_pinned_to_a_superseded_set(api)

        refused = api.admit_referral(referral["id"], {}, headers=intake)
        validate_error(refused, ApiErrorId.ERR_CRITERIA_SET_SUPERSEDED)

        still_open = fixtures.read_referral(api, referral["id"])
        assert still_open["status"] == ReferralStatus.CRITERIA_MET

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 0)

        stays, meta = validate_paginated(
            api.list_stays(params={"patient_id": world.patient_id}, headers=intake)
        )
        assert meta["total_count"] == 0
        assert stays == []

    def test_publishing_a_newer_set_flips_the_older_one_while_the_referral_still_points_at_it(
        self, api
    ):
        """The dependency is one-way: the reference data moved, the referral did not.

        CS-2026B carries an `effective_from` of 2026-02-01, strictly later than
        CS-2026A's 2026-01-01, so its publication is accepted and demotes CS-2026A. The
        referral's `pinned_criteria_set_id` still names CS-2026A, which is precisely why
        the admission became illegal without any transition on the referral itself.

        PRD 3.1: "On publication, the new set takes `status` `ACTIVE` and every previously `ACTIVE` set flips to `SUPERSEDED` — which is exactly why a referral that pinned an older set can no longer be admitted until it is re-screened."
        PRD 3.1: "The new set's `effective_from` must be strictly later than the `effective_from` of every set currently `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/admit_blocked_after_a_newer_criteria_set_supersedes_the_pinned_one
        """
        world, referral, newer = _referral_pinned_to_a_superseded_set(api)

        assert referral["pinned_criteria_set_id"] == world.criteria_set_id

        older_now = fixtures.read_criteria_set(api, world.criteria_set_id)
        assert older_now["status"] == CriteriaSetStatus.SUPERSEDED
        newer_now = fixtures.read_criteria_set(api, newer["id"])
        assert newer_now["status"] == CriteriaSetStatus.ACTIVE

        unchanged = fixtures.read_referral(api, referral["id"])
        assert unchanged["pinned_criteria_set_id"] == world.criteria_set_id

    def test_a_replacement_referral_re_pins_the_newer_set_and_admits_on_the_same_data(
        self, api
    ):
        """The recovery is a re-screen through a fresh referral, not a retry of the admit.

        A new referral for the same patient carries the identical clinical data and is
        screened against the current logical date, so it pins CS-2026B. That set demands
        120 ventilator hours and 4 ICU days rather than 96 and 3, and the referral's 240
        hours and 5 days still clear the stricter thresholds, so it resolves to the
        ventilation track and admits. Creating the replacement is what finally moves the
        blocked referral: it is superseded, not admitted, and the period ends with the one
        admission the successful stay produced.

        PRD 3.2: "**the criteria set is re-selected against the current logical date, not against the date of the original screen.**"
        PRD 3.2: "Creation also does something destructive, which is what §2.6's version check protects: any other referral of the same patient whose `status` is `RECEIVED`, `INFO_REQUESTED` or `CRITERIA_MET` is flipped to `SUPERSEDED` (a terminal status), the patient's `version` advances by 1, and the patient's `open_referral_count` settles at 1 — one decrement for the superseded referral, one increment for the new one, so the net stays at 1."
        PRD 3.2: "The prolonged-mechanical-ventilation criterion is met when `vent_hours_at_referral` is at least the pinned set's `pmv_min_vent_hours` **and** `icu_days_at_referral` is at least its `pmv_min_icu_days`."

        Design: Difficulty/cross_entity_state_dependency/admit_blocked_after_a_newer_criteria_set_supersedes_the_pinned_one
        """
        world, blocked, newer = _referral_pinned_to_a_superseded_set(api)

        patient = fixtures.read_patient(api, world.patient_id)
        replacement = fixtures.qualified_referral(
            api, world, patient_version=patient["version"]
        )
        assert replacement["pinned_criteria_set_id"] == newer["id"]
        assert replacement["qualifying_track"] == QualifyingTrack.PMV

        superseded = fixtures.read_referral(api, blocked["id"])
        assert superseded["status"] == ReferralStatus.SUPERSEDED

        stay = fixtures.admit(api, replacement["id"])
        assert stay["clinical_status"] == ClinicalStatus.ADMITTED
        assert stay["referral_id"] == replacement["id"]

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 1)
