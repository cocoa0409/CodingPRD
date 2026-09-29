"""
State machines: initial states, legal transitions, guarded transitions, terminal lockdown.

Every entity in this service carries a declared lifecycle, and this module pins the
lifecycles themselves rather than the arithmetic hanging off them: where a machine starts,
which triggers it accepts from each state, which triggers it must refuse, what a refusal
leaves behind, and how the review cycle closes back on itself.

Three habits run through the file. A stay is read on both of its status dimensions at
once, because `clinical_status` and `payment_review_status` advance independently and a
transition that moves one must be shown not to have moved the other. Every refusal is
followed by a re-read of the subject, because an error response is only half the claim —
the other half is that nothing was written. And every scenario is built from scratch
through the public endpoints, because the server restarts with an empty store and the
logical clock at `2026-08-01T00:00:00Z` before each test.
"""

from test_helpers import (
    CLOCK_EPOCH,
    INTERRUPTION_WINDOW_DAYS,
    MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT,
    NURSE_2_ID,
    NURSE_ID,
    PROGRESSION_STEPS_REQUIRED,
    QUERY_RESPONSE_WINDOW_HOURS,
    SYSTEM_ACTOR,
    ApiErrorId,
    ClinicalStatus,
    CredentialStatus,
    CriteriaSetStatus,
    DeterminationStatus,
    Discipline,
    DischargeDisposition,
    InterruptionDestination,
    InterruptionStatus,
    PaymentReviewStatus,
    PeriodStatus,
    QualifyingTrack,
    QueryStatus,
    QueryType,
    ReferralStatus,
    ReviewStatus,
    RiskBand,
    SbtOutcome,
    Specialty,
    VoidReason,
    WeaningCloseOutcome,
    WeaningPlanStatus,
    assert_instant_equals,
    assert_integer_field,
    assert_period_ledger,
    assert_stay_dimensions,
    assert_unset,
    assert_vent_hours,
    factories,
    fixtures,
    get_success_data,
    make_attending_physician_headers,
    shift_hours,
    validate_error,
)

# The instant every scenario in this module discharges at, fourteen calendar days after
# the admission at the clock epoch.
DISCHARGE_INSTANT = "2026-08-15T00:00:00Z"


def _stay_with_open_weaning_plan(api, notes=True):
    """Reference data, a stay admitted at the clock epoch, and a fresh weaning plan.

    When `notes` is set, one `RESPIRATORY_THERAPY` and one `PHYSICIAN` note are filed
    before the plan is opened, which is what a tolerated trial requires before the first
    progression. A scenario that records only failed trials needs neither.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world)
    if notes:
        fixtures.file_note(api, admission.stay_id, Discipline.RESPIRATORY_THERAPY)
        fixtures.file_note(
            api,
            admission.stay_id,
            Discipline.PHYSICIAN,
            headers=world.physician_headers,
        )
    plan = fixtures.open_weaning_plan(api, admission.stay_id)
    return world, admission, plan


def _discharged_without_notes(api, world=None, disposition=DischargeDisposition.HOME,
                              discharge_instant=DISCHARGE_INSTANT):
    """A stay admitted at the clock epoch and discharged at `discharge_instant`.

    No interdisciplinary notes are filed, so all four mandatory disciplines are missing
    and the denial-risk score lands at 67 — inside `MODERATE`, which is what keeps the
    cascade from auto-issuing a query and leaves the review `OPEN`.
    """
    admission = fixtures.admitted_stay(api, world if world is not None else fixtures.build_world(api))
    fixtures.advance_clock(api, discharge_instant)
    return fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=disposition,
        estimated_cost_cents=1000000,
        file_notes=False,
    )


class TestInterruptionCycleResumesTheStay:
    """A five-day acute-care absence inside the nine-day window returns the stay to ADMITTED."""

    def test_recording_the_departure_opens_a_nine_day_acute_care_window(self, api, nurse):
        """Interrupting an admitted stay defaults left_at to the clock and sets a nine-day window.

        The stay is admitted at the clock epoch and the nurse records a departure to
        `ACUTE_CARE` without supplying `left_at`, so the event must take the current
        logical instant. The destination alone fixes the tolerance, and nine days is the
        figure declared for an acute-care transfer. The event opens with its three
        outcome fields still unknown, and the stay's clinical dimension leaves `ADMITTED`
        while its payment dimension stays where admission left it.

        PRD 3.5: "A `UtilizationReviewNurse` records the departure, moving the stay `ADMITTED → INTERRUPTED` and creating an `InterruptionEvent` carrying that `stay_id`."
        PRD 3.5: "The destination sets the event's `window_days` directly: 9 days for `ACUTE_CARE`, 27 days for both `IRF` and `SNF`, and 3 days for `HOME`."
        PRD 3.5: "The new event enters `status` `OPEN` with `returned_at`, `interruption_days` and `within_window` all null, and the stay's `interruption_count` increases by 1."

        Design: Corner/state_machines/interrupt_then_return_within_the_window_resumes_the_stay
        """
        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)

        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )

        assert event["status"] == InterruptionStatus.OPEN, (
            "a new interruption event must open in OPEN, got {!r}".format(event["status"])
        )
        assert_instant_equals(event["left_at"], CLOCK_EPOCH, "left_at")
        assert_integer_field(
            event, "window_days", INTERRUPTION_WINDOW_DAYS[InterruptionDestination.ACUTE_CARE]
        )
        assert_unset(event, "returned_at", "interruption_days", "within_window")

        stay = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(stay, ClinicalStatus.INTERRUPTED, PaymentReviewStatus.PENDING)
        assert_integer_field(stay, "interruption_count", 1)

    def test_a_five_day_return_lands_inside_the_window_and_readmits_the_stay(self, api, nurse):
        """A return five days later is inside a nine-day window, so the stay comes back to ADMITTED.

        The departure is stamped at the epoch and the clock is moved to 2026-08-06 before
        the return, so the whole-day count between the two UTC calendar dates is exactly
        five. Five is not greater than nine, so the inclusive comparison puts the absence
        inside the window: the event ends `RETURNED`, its days are banked on the stay's
        running total, and the clinical dimension goes back to `ADMITTED` rather than
        being discharged retroactively.

        PRD 3.5: "The system stamps `returned_at` with the current logical instant and computes `interruption_days` as the whole-day count from `left_at` to `returned_at`."
        PRD 3.5: "The comparison is inclusive: `within_window` is true when `interruption_days` is less than or equal to `window_days`, so an absence of exactly 9 days falls inside a 9-day window while 10 days does not."
        PRD 3.5: "When the return is inside the window, the event moves `OPEN → RETURNED` with `within_window` true, its `interruption_days` are added to the stay's `interruption_days_total`, and the stay moves `INTERRUPTED → ADMITTED`."

        Design: Corner/state_machines/interrupt_then_return_within_the_window_resumes_the_stay
        """
        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)
        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )

        fixtures.advance_clock(api, "2026-08-06T00:00:00Z")
        returned = fixtures.return_from_interruption(api, event["id"], headers=nurse)

        assert returned["status"] == InterruptionStatus.RETURNED, (
            "a within-window return must reach RETURNED, got {!r}".format(returned["status"])
        )
        assert_integer_field(returned, "interruption_days", 5)
        assert returned["within_window"] is True, (
            "within_window must be true for 5 days against a 9-day window, got {!r}".format(
                returned["within_window"]
            )
        )
        assert_instant_equals(returned["returned_at"], "2026-08-06T00:00:00Z", "returned_at")

        stay = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_integer_field(stay, "interruption_days_total", 5)
        assert_unset(stay, "discharged_at", "discharge_disposition")

    def test_the_stays_interruption_listing_filters_on_the_events_status(self, api, nurse):
        """One event exists after the cycle, and it is found under RETURNED but not under OPEN.

        The stay recorded a single departure and a single return, so its interruption
        collection holds exactly one row whatever filter is applied. Filtering on the
        status the event now holds returns it; filtering on the status it has left behind
        returns nothing, which is what proves the listing reads the event's live status
        rather than the status it was created with.

        PRD 3.5: "A stay's interruption events are listable, optionally filtered by `status`."

        Design: Corner/state_machines/interrupt_then_return_within_the_window_resumes_the_stay
        """
        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world)
        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
            headers=nurse,
        )
        fixtures.advance_clock(api, "2026-08-06T00:00:00Z")
        fixtures.return_from_interruption(api, event["id"], headers=nurse)

        unfiltered = fixtures.interruptions_of(api, admission.stay_id, headers=nurse)
        assert len(unfiltered) == 1, "expected one interruption event, got {}".format(
            len(unfiltered)
        )
        assert unfiltered[0]["id"] == event["id"]

        returned_only = fixtures.interruptions_of(
            api, admission.stay_id, headers=nurse, status=InterruptionStatus.RETURNED
        )
        assert len(returned_only) == 1, (
            "the RETURNED filter must find the event, got {} rows".format(len(returned_only))
        )
        assert returned_only[0]["id"] == event["id"]

        open_only = fixtures.interruptions_of(
            api, admission.stay_id, headers=nurse, status=InterruptionStatus.OPEN
        )
        assert open_only == [], (
            "the event has left OPEN, so the OPEN filter must be empty, got {}".format(open_only)
        )


class TestLiberatedCloseRequiresTwoProgressions:
    """The progression gate on a LIBERATED close, refused at step one and passed at step two."""

    def test_a_liberated_close_at_step_one_is_refused_and_leaves_the_plan_progressing(
        self, api, nurse
    ):
        """One tolerated trial reaches step 1, which is below the two-step liberation requirement.

        The plan has recorded a single tolerated trial, so `current_step` is 1 and
        `liberation_eligible` is false. A `LIBERATED` close is gated on that flag, not on
        the physician's judgement, so the request must be refused by name rather than
        quietly downgraded. The re-read is the second half of the claim: the plan is still
        `PROGRESSING` and carries no close stamps, so the refusal wrote nothing.

        PRD 3.4: "A `TOLERATED` record is a progression."
        PRD 3.4: "It increases `current_step` by 1, resets `consecutive_failed_sbt` to 0, sets `max_tolerated_sbt_hours` to the larger of its previous value and this trial's `sbt_hours`, stamps `last_progression_at` with the current logical instant, and recomputes `liberation_eligible` as true exactly when `current_step` has reached at least 2."
        PRD 3.4: "A `LIBERATED` close is reachable only from `PROGRESSING` and only when `liberation_eligible` is true, meaning `current_step` has reached at least 2; otherwise it is refused with `ERR_WEANING_PROGRESSION_INSUFFICIENT`."

        Design: Corner/state_machines/close_weaning_plan_as_liberated_before_the_second_step_is_rejected
        """
        world, _admission, plan = _stay_with_open_weaning_plan(api)

        after_first = fixtures.record_sbt(
            api,
            plan["id"],
            outcome=SbtOutcome.TOLERATED,
            sbt_hours=2,
            vent_hours_since_last=5,
            headers=nurse,
        )
        assert after_first["status"] == WeaningPlanStatus.PROGRESSING
        assert_integer_field(after_first, "current_step", 1)
        assert after_first["liberation_eligible"] is False, (
            "one progression is below the {}-step requirement, got liberation_eligible {!r}".format(
                PROGRESSION_STEPS_REQUIRED, after_first["liberation_eligible"]
            )
        )

        refused = api.close_weaning_plan(
            plan["id"],
            factories.close_plan_payload(outcome=WeaningCloseOutcome.LIBERATED),
            headers=world.physician_headers,
        )
        validate_error(refused, ApiErrorId.ERR_WEANING_PROGRESSION_INSUFFICIENT)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.PROGRESSING, (
            "a refused close must leave the plan in PROGRESSING, got {!r}".format(
                unchanged["status"]
            )
        )
        assert_unset(unchanged, "closed_at", "closed_by_physician_id")
        assert_integer_field(unchanged, "current_step", 1)
        assert_integer_field(unchanged, "sbt_attempt_count", 1)

    def test_the_second_tolerated_trial_unlocks_the_liberated_close(self, api, nurse):
        """A second progression reaches step 2, and the same close then succeeds and stamps.

        Nothing about the request changes between the refusal and the success: the same
        physician sends the same payload against the same plan. Only the plan's step count
        moves, from 1 to 2, which flips `liberation_eligible` and is therefore shown to be
        the sole gate. The close stamps the acting physician's identity and the current
        logical instant, and the counters carry the two trials' figures: eight ventilator
        hours seeded from nothing plus five and three, two attempts, and the larger of the
        two tolerated durations.

        PRD 3.4: "A `LIBERATED` close is reachable only from `PROGRESSING` and only when `liberation_eligible` is true, meaning `current_step` has reached at least 2; otherwise it is refused with `ERR_WEANING_PROGRESSION_INSUFFICIENT`."
        PRD 3.4: "Both closes stamp `closed_at` from the logical clock and write the acting physician's `X-User-ID` into `closed_by_physician_id`, and both require the acting physician to have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`."
        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."

        Design: Corner/state_machines/close_weaning_plan_as_liberated_before_the_second_step_is_rejected
        """
        world, _admission, plan = _stay_with_open_weaning_plan(api)
        fixtures.record_sbt(
            api,
            plan["id"],
            outcome=SbtOutcome.TOLERATED,
            sbt_hours=2,
            vent_hours_since_last=5,
            headers=nurse,
        )

        after_second = fixtures.record_sbt(
            api,
            plan["id"],
            outcome=SbtOutcome.TOLERATED,
            sbt_hours=4,
            vent_hours_since_last=3,
            headers=nurse,
        )
        assert_integer_field(after_second, "current_step", PROGRESSION_STEPS_REQUIRED)
        assert after_second["liberation_eligible"] is True, (
            "two progressions must set liberation_eligible, got {!r}".format(
                after_second["liberation_eligible"]
            )
        )

        closed = fixtures.close_plan(
            api, plan["id"], WeaningCloseOutcome.LIBERATED, world.physician_headers
        )

        assert closed["status"] == WeaningPlanStatus.LIBERATED, (
            "an eligible plan must close into LIBERATED, got {!r}".format(closed["status"])
        )
        assert closed["closed_by_physician_id"] == world.physician_id, (
            "closed_by_physician_id must be the acting physician {!r}, got {!r}".format(
                world.physician_id, closed["closed_by_physician_id"]
            )
        )
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")
        assert_vent_hours(closed, "vent_hours_total", 8.0)
        assert_integer_field(closed, "sbt_attempt_count", 2)
        assert_vent_hours(closed, "max_tolerated_sbt_hours", 4)


class TestVentDependentCloseRequiresThreeAttempts:
    """The attempt floor on a VENT_DEPENDENT close, and its independence from the step gate."""

    def test_two_failed_trials_regress_the_plan_from_its_initial_state(self, api):
        """The first failure self-loops in SBT_TRIAL; the second reaches two in a row and regresses.

        The plan has never progressed, so it opens in `SBT_TRIAL` at step 0. One failed
        trial leaves `consecutive_failed_sbt` at 1, which is below the two-in-a-row
        threshold, so the plan stays exactly where it was. The second failure takes the
        counter to 2 and forces the regression, and because `current_step` was already 0
        the reduction is absorbed by the floor rather than going negative.

        PRD 3.4: "A new plan carries `stay_id`, enters `status` `SBT_TRIAL` with `current_step` 0, `sbt_attempt_count` 0, `consecutive_failed_sbt` 0, `max_tolerated_sbt_hours` 0, `liberation_eligible` false, and `last_progression_at`, `closed_at` and `closed_by_physician_id` all null."
        PRD 3.4: "If the resulting `consecutive_failed_sbt` is still below 2, the plan simply stays where it was — `SBT_TRIAL` self-loops to `SBT_TRIAL`, `PROGRESSING` self-loops to `PROGRESSING` — and `current_step` is untouched."
        PRD 3.4: "A plan that fails twice before ever progressing regresses exactly like one that had progressed, with its `current_step` simply staying at 0."

        Design: Corner/state_machines/close_weaning_plan_as_vent_dependent_with_two_attempts_is_rejected
        """
        _world, _admission, plan = _stay_with_open_weaning_plan(api, notes=False)
        assert plan["status"] == WeaningPlanStatus.SBT_TRIAL, (
            "a new plan must open in SBT_TRIAL, got {!r}".format(plan["status"])
        )

        after_first = fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        assert after_first["status"] == WeaningPlanStatus.SBT_TRIAL, (
            "one failure is below the two-in-a-row threshold, so the plan must self-loop "
            "in SBT_TRIAL, got {!r}".format(after_first["status"])
        )
        assert_integer_field(after_first, "consecutive_failed_sbt", 1)
        assert_integer_field(after_first, "sbt_attempt_count", 1)
        assert_integer_field(after_first, "current_step", 0)

        after_second = fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        assert after_second["status"] == WeaningPlanStatus.REGRESSED, (
            "two consecutive failures must regress the plan, got {!r}".format(
                after_second["status"]
            )
        )
        assert_integer_field(after_second, "consecutive_failed_sbt", 2)
        assert_integer_field(after_second, "sbt_attempt_count", 2)
        assert_integer_field(after_second, "current_step", 0)

    def test_a_vent_dependent_close_at_two_attempts_is_refused_and_changes_nothing(
        self, api, nurse
    ):
        """Two recorded trials are one short of the three a VENT_DEPENDENT close requires.

        The plan is in `REGRESSED`, which is one of the three states a `VENT_DEPENDENT`
        close may be reached from, so the state itself is legal and the only thing standing
        in the way is the attempt count. Two is below three, so the refusal must name the
        attempt floor rather than the state machine, and the plan must be left in
        `REGRESSED` with its counters and its null close stamps untouched.

        PRD 3.4: "A `VENT_DEPENDENT` close is reachable from `SBT_TRIAL`, from `PROGRESSING` and from `REGRESSED`, and requires `sbt_attempt_count` of at least 3; a plan with fewer attempts is refused with `ERR_INSUFFICIENT_SBT_ATTEMPTS`."

        Design: Corner/state_machines/close_weaning_plan_as_vent_dependent_with_two_attempts_is_rejected
        """
        world, _admission, plan = _stay_with_open_weaning_plan(api, notes=False)
        fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)

        refused = api.close_weaning_plan(
            plan["id"],
            factories.close_plan_payload(outcome=WeaningCloseOutcome.VENT_DEPENDENT),
            headers=world.physician_headers,
        )
        validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_SBT_ATTEMPTS)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.REGRESSED, (
            "a refused close must leave the plan in REGRESSED, got {!r}".format(
                unchanged["status"]
            )
        )
        assert_unset(unchanged, "closed_at", "closed_by_physician_id")
        assert_integer_field(
            unchanged, "sbt_attempt_count", MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT - 1
        )
        assert_vent_hours(unchanged, "vent_hours_total", 48.0)

    def test_a_liberated_close_on_the_same_plan_names_the_progression_gate_instead(
        self, api, nurse
    ):
        """The two close gates are independent: the same plan fails each one on its own terms.

        The plan sits in `REGRESSED` with two attempts and no progression at all. Asking
        for `VENT_DEPENDENT` is short of the attempt floor; asking for `LIBERATED` is short
        of the two-step progression requirement, and is additionally reached from a state
        no `LIBERATED` close accepts. The two requests must therefore be refused under
        different names, which is what shows neither gate is a proxy for the other.

        PRD 3.4: "A `LIBERATED` close is reachable only from `PROGRESSING` and only when `liberation_eligible` is true, meaning `current_step` has reached at least 2; otherwise it is refused with `ERR_WEANING_PROGRESSION_INSUFFICIENT`."
        PRD 3.4: "A `VENT_DEPENDENT` close is reachable from `SBT_TRIAL`, from `PROGRESSING` and from `REGRESSED`, and requires `sbt_attempt_count` of at least 3; a plan with fewer attempts is refused with `ERR_INSUFFICIENT_SBT_ATTEMPTS`."

        Design: Corner/state_machines/close_weaning_plan_as_vent_dependent_with_two_attempts_is_rejected
        """
        world, _admission, plan = _stay_with_open_weaning_plan(api, notes=False)
        fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        regressed = fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        assert regressed["liberation_eligible"] is False

        refused_liberated = api.close_weaning_plan(
            plan["id"],
            factories.close_plan_payload(outcome=WeaningCloseOutcome.LIBERATED),
            headers=world.physician_headers,
        )
        validate_error(refused_liberated, ApiErrorId.ERR_WEANING_PROGRESSION_INSUFFICIENT)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.REGRESSED
        assert_unset(unchanged, "closed_at", "closed_by_physician_id")

    def test_the_third_failed_trial_unlocks_the_vent_dependent_close(self, api):
        """A third attempt reaches the floor, and the close then lands on a plan that never weaned.

        The third failure takes the plan around its own `REGRESSED → REGRESSED` self-loop
        rather than anywhere new, so the only thing that changes is the attempt count going
        from 2 to 3. That alone unlocks the close. The closed plan records a patient who
        never tolerated a single trial: the step count is at its floor, the best tolerated
        duration is still zero, and all three failures' ventilator hours have accumulated
        without any of them being given back.

        PRD 3.4: "A plan already in `REGRESSED` takes the self-loop `REGRESSED → REGRESSED` on every further failed record, decreasing `current_step` by 1 each time with the same floor at 0."
        PRD 3.4: "A `VENT_DEPENDENT` close is reachable from `SBT_TRIAL`, from `PROGRESSING` and from `REGRESSED`, and requires `sbt_attempt_count` of at least 3; a plan with fewer attempts is refused with `ERR_INSUFFICIENT_SBT_ATTEMPTS`."
        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."

        Design: Corner/state_machines/close_weaning_plan_as_vent_dependent_with_two_attempts_is_rejected
        """
        world, _admission, plan = _stay_with_open_weaning_plan(api, notes=False)
        for _ in range(2):
            fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)

        after_third = fixtures.failed_sbt(api, plan["id"], sbt_hours=0, vent_hours_since_last=24)
        assert after_third["status"] == WeaningPlanStatus.REGRESSED, (
            "a further failure self-loops in REGRESSED, got {!r}".format(after_third["status"])
        )
        assert_integer_field(
            after_third, "sbt_attempt_count", MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT
        )
        assert_integer_field(after_third, "consecutive_failed_sbt", 3)

        closed = fixtures.close_plan(
            api, plan["id"], WeaningCloseOutcome.VENT_DEPENDENT, world.physician_headers
        )

        assert closed["status"] == WeaningPlanStatus.VENT_DEPENDENT, (
            "three attempts must let the close reach VENT_DEPENDENT, got {!r}".format(
                closed["status"]
            )
        )
        assert_integer_field(closed, "current_step", 0)
        assert_vent_hours(closed, "max_tolerated_sbt_hours", 0)
        assert_vent_hours(closed, "vent_hours_total", 72.0)
        assert closed["closed_by_physician_id"] == world.physician_id
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")


class TestScreeningIsNotRepeatable:
    """A referral that has reached CRITERIA_MET has left the screening loop for good."""

    def test_screening_a_referral_already_in_criteria_met_is_refused(self, api, intake):
        """Screening is declared only from RECEIVED, so a second screen on CRITERIA_MET is illegal.

        The referral was screened once, met the ventilation criterion and moved out of
        `RECEIVED` into `CRITERIA_MET` with `screened_count` at 1. A second screen is a
        transition the machine does not declare from that state, so it is refused as an
        illegal state transition rather than being allowed to re-evaluate the same inputs.
        Because every screening evaluation increments the counter, an accepted second screen
        would show up as `screened_count` 2 — so the counter still reading 1 is what proves
        no evaluation ran.

        PRD 2.8: "The subject entity occupies a state from which the requested transition is declared: screening only from `RECEIVED`, information submission only from `INFO_REQUESTED`, admission only from `CRITERIA_MET`, interruption only from `ADMITTED`, return only from an `OPEN` interruption, trial recording only from `SBT_TRIAL`, `PROGRESSING` or `REGRESSED`, finalization only from `DRAFT`, answering only from `ISSUED`, query closure only from `ANSWERED`, and review resolution only from `OPEN` or `QUERIES_ISSUED`."
        PRD 3.2: "Every screening evaluation, whatever its verdict, increases `screened_count` by 1."

        Design: Corner/state_machines/screen_an_already_screened_referral_returns_invalid_state
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world)
        assert referral["status"] == ReferralStatus.CRITERIA_MET
        assert_integer_field(referral, "screened_count", 1)

        refused = api.screen_referral(referral["id"], headers=intake)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fixtures.read_referral(api, referral["id"])
        assert unchanged["status"] == ReferralStatus.CRITERIA_MET, (
            "a refused screen must leave the referral in CRITERIA_MET, got {!r}".format(
                unchanged["status"]
            )
        )
        assert_integer_field(unchanged, "screened_count", 1)

    def test_submitting_information_on_a_referral_in_criteria_met_writes_nothing(
        self, api, intake
    ):
        """Late data is accepted only from INFO_REQUESTED, so the overwrite must not happen.

        This referral never bounced through `INFO_REQUESTED`: it was complete on the first
        screen and went straight to `CRITERIA_MET`. Submitting a new `vent_hours_at_referral`
        of 300 is therefore refused on state grounds, and the refusal has to be total. The
        submission's declared behaviour is that supplied values overwrite the stored ones,
        so the referral still reporting the 240 hours it was created with is the proof that
        the endpoint rejected the request before touching the row.

        PRD 3.2: "Submitting information on a referral in any status other than `INFO_REQUESTED` is refused as an illegal state transition, and submission is subject to the same effective-criteria-set precondition as the initial screen."
        PRD 3.2: "The submission accepts the same five optional inputs — `vent_hours_at_referral`, `icu_days_at_referral`, `wound_stage`, `wound_count`, `prior_acute_discharge_at` — and whichever are supplied overwrite the referral's stored values."

        Design: Corner/state_machines/screen_an_already_screened_referral_returns_invalid_state
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world)
        assert_vent_hours(referral, "vent_hours_at_referral", 240)

        refused = api.submit_referral_info(
            referral["id"],
            factories.submit_info_payload(vent_hours_at_referral=300),
            headers=intake,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fixtures.read_referral(api, referral["id"])
        assert unchanged["status"] == ReferralStatus.CRITERIA_MET
        assert_vent_hours(unchanged, "vent_hours_at_referral", 240)
        assert_integer_field(unchanged, "screened_count", 1)


class TestDeclaredInitialStates:
    """Every machine in the service starts where the specification says it starts."""

    def test_client_created_entities_open_in_their_declared_initial_states(self, api, intake):
        """A period, a criteria set, a referral and a stay each open in their own first state.

        These four machines are entered by four different requests, and each has a single
        declared entry point: a period accrues while `OPEN` and its close stamp is still
        unwritten; a freshly published criteria set is the live one, so it is `ACTIVE`; a
        new referral has not been evaluated, so it is `RECEIVED` with no track, no
        evaluation on its counter, incomplete data and no pinned set; and a new stay is
        `ADMITTED` on its clinical dimension while its independent payment dimension has
        not moved off `PENDING`.

        PRD 2.7: "A period's `status` is `OPEN` while it accrues admissions and payments and `CLOSED` once an operator closes it; `closed_at` records the logical instant of the close and is null while the period is `OPEN`."
        PRD 3.1: "On publication, the new set takes `status` `ACTIVE` and every previously `ACTIVE` set flips to `SUPERSEDED` — which is exactly why a referral that pinned an older set can no longer be admitted until it is re-screened."
        PRD 3.2: "A newly created referral enters `RECEIVED` with `qualifying_track` `NONE`, `screened_count` 0, `data_complete` false and `pinned_criteria_set_id` null."
        PRD 3.3: "The new stay's `patient_id` and `referral_id` are copied from the admitting referral, its `cost_reporting_period_id` is the selected open period, its `clinical_status` is `ADMITTED`, its `payment_review_status` is `PENDING`, its `admitted_at` is the supplied value or the current logical instant, and its `counts_toward_admission_threshold` is true."

        Design: Corner/state_machines/new_entities_start_in_their_declared_initial_states
        """
        world = fixtures.build_world(api)

        assert world.period["status"] == PeriodStatus.OPEN, (
            "a new cost reporting period must open in OPEN, got {!r}".format(
                world.period["status"]
            )
        )
        assert_unset(world.period, "closed_at")
        assert world.criteria_set["status"] == CriteriaSetStatus.ACTIVE, (
            "the newest criteria set is the live one, so it must be ACTIVE, got {!r}".format(
                world.criteria_set["status"]
            )
        )

        referral = fixtures.create_referral(api, world, headers=intake)
        assert referral["status"] == ReferralStatus.RECEIVED, (
            "a new referral must enter RECEIVED, got {!r}".format(referral["status"])
        )
        assert referral["qualifying_track"] == QualifyingTrack.NONE
        assert_integer_field(referral, "screened_count", 0)
        assert referral["data_complete"] is False, (
            "an unscreened referral must report data_complete false, got {!r}".format(
                referral["data_complete"]
            )
        )
        assert_unset(referral, "pinned_criteria_set_id")

        fixtures.screen_referral(api, referral["id"], headers=intake)
        stay = fixtures.admit(api, referral["id"], headers=intake)

        assert_stay_dimensions(stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_instant_equals(stay["admitted_at"], CLOCK_EPOCH, "admitted_at")
        assert stay["counts_toward_admission_threshold"] is True
        assert_unset(stay, "discharged_at", "resumed_at", "interrupted_parent_stay_id")

    def test_the_cascade_opens_its_determination_in_draft_and_its_review_in_open(
        self, api, nurse
    ):
        """The two entities a discharge creates start in DRAFT and OPEN, with no query issued.

        The stay ran from the clock epoch to 2026-08-15, so fourteen covered days against a
        DRG whose average is thirty. No interdisciplinary note was ever filed, so all four
        mandatory disciplines are missing, and the stay has no weaning plan: 32 points plus
        15, plus 20 for the short-stay-outlier flag the fourteen-day stay raises, with
        nothing from the site-neutral flag and nothing from a length-of-stay excess a
        below-average stay cannot have. Sixty-seven sits in `MODERATE`, which is what keeps
        the fourth level of the cascade from firing, so the review must be left `OPEN` with
        no query behind it. The determination is machine-priced, so its pricing actor is the
        literal system identity rather than the nurse who discharged the stay.

        PRD 3.6: "*Level two* follows because the stay became `DISCHARGED`: a `PaymentDetermination` is created for it with `status` `DRAFT` and `priced_by_user_id` set to the literal `SYSTEM` rather than to any human `X-User-ID`."
        PRD 3.6: "*Level three* follows because a determination now exists: a `DenialRiskReview` is opened for the stay with `status` `OPEN`, `opened_by_user_id` recording the user whose action triggered the cascade (or `SYSTEM` where no human acted), `resolved_by_user_id` and `resolution_note` null, and its `as_documented_score`, `missing_discipline_count`, `answered_query_count`, `effective_score` and `risk_band` computed as set out in §3.8."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."
        PRD 3.6: "When the band is `MODERATE` or `LOW`, no query is issued and the review stays `OPEN`."

        Design: Corner/state_machines/new_entities_start_in_their_declared_initial_states
        """
        admission = _discharged_without_notes(api)

        assert_stay_dimensions(
            admission.stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED
        )

        determination = admission.determination
        assert determination["status"] == DeterminationStatus.DRAFT, (
            "the cascade must open its determination in DRAFT, got {!r}".format(
                determination["status"]
            )
        )
        assert determination["priced_by_user_id"] == SYSTEM_ACTOR, (
            "a machine-priced determination must record {!r}, got {!r}".format(
                SYSTEM_ACTOR, determination["priced_by_user_id"]
            )
        )
        assert_unset(determination, "void_reason", "recalculation_reason")

        review = admission.review
        assert review["status"] == ReviewStatus.OPEN, (
            "a MODERATE review must be left OPEN, got {!r}".format(review["status"])
        )
        assert_unset(review, "resolved_by_user_id", "resolution_note")
        assert_integer_field(review, "missing_discipline_count", 4)
        assert_integer_field(review, "as_documented_score", 67)
        assert_integer_field(review, "effective_score", 67)
        assert_integer_field(review, "answered_query_count", 0)
        assert review["risk_band"] == RiskBand.MODERATE, (
            "an effective score of 67 sits in MODERATE, got {!r}".format(review["risk_band"])
        )

        assert fixtures.queries_of(api, stay_id=admission.stay_id) == [], (
            "no query may be auto-issued below the HIGH band, got {}".format(
                fixtures.queries_of(api, stay_id=admission.stay_id)
            )
        )


class TestTerminalStatesAcceptNoFurtherTransition:
    """WITHDRAWN and VOIDED are dead ends: no repeat, no continuation, no side effect."""

    def test_a_withdrawn_referral_accepts_neither_a_second_withdrawal_nor_an_admission(
        self, api, intake
    ):
        """Withdrawal is terminal, so both the withdrawal itself and admission are refused after it.

        The referral was screened to `CRITERIA_MET` and then abandoned, which is one of the
        three states withdrawal is legal from and which leaves it in a status the
        specification calls terminal. Two different transitions are then attempted against
        it. A second withdrawal has no legal source state left. An admission attempt is the
        interesting one, because admission on a clinically failed referral is deliberately
        deferred to the clinical rule instead — but `WITHDRAWN` is named explicitly among
        the statuses that still return the generic state error, so the caller learns the
        referral is closed rather than anything about its clinical fit.

        PRD 3.2: "Withdrawal is legal from `RECEIVED`, from `INFO_REQUESTED` and from `CRITERIA_MET`; it moves the referral to the terminal status `WITHDRAWN` and decreases `Patient.open_referral_count` by 1, settling it at 0."
        PRD 2.8: "Admission attempted on a referral in `RECEIVED`, `INFO_REQUESTED`, `ADMITTED`, `WITHDRAWN` or `SUPERSEDED` is still `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdrawn_referral_and_voided_determination_reject_further_transitions
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world)
        withdrawn = get_success_data(api.withdraw_referral(referral["id"], headers=intake))
        assert withdrawn["status"] == ReferralStatus.WITHDRAWN, (
            "withdrawal from CRITERIA_MET must reach WITHDRAWN, got {!r}".format(
                withdrawn["status"]
            )
        )

        second_withdrawal = api.withdraw_referral(referral["id"], headers=intake)
        validate_error(second_withdrawal, ApiErrorId.ERR_INVALID_STATE)

        admission_attempt = api.admit_referral(
            referral["id"], factories.admit_payload(), headers=intake
        )
        validate_error(admission_attempt, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fixtures.read_referral(api, referral["id"])
        assert unchanged["status"] == ReferralStatus.WITHDRAWN, (
            "two refused transitions must leave the referral WITHDRAWN, got {!r}".format(
                unchanged["status"]
            )
        )
        patient = fixtures.read_patient(api, world.patient_id)
        assert_integer_field(patient, "open_referral_count", 0)

    def test_a_voided_determination_accepts_neither_a_second_void_nor_a_finalization(
        self, api, third_analyst, second_analyst
    ):
        """VOIDED is terminal, and the reason recorded by the first void survives both refusals.

        The discharge cascade priced the stay in `DRAFT`, and an analyst reversed it with a
        data-entry reason of her own choosing. Voiding is declared only from `DRAFT` and
        `FINAL`, so a second void has no legal source; finalization is declared only from
        `DRAFT`, so it has none either. Neither refusal may overwrite the reason the first
        void recorded — the second attempt supplies a different one, so a surviving
        `DATA_ENTRY_ERROR` is what shows the request was rejected before the write.

        PRD 3.7: "A `RevenueIntegrityAnalyst` may reverse a determination in either `DRAFT` or `FINAL`, supplying a required `void_reason`."
        PRD 3.7: "`VOIDED` is terminal."
        PRD 3.7: "The `void_reason` field holds the analyst's supplied reason for a human void, the literal `SUPERSEDED` for a draft displaced by a re-price, and the literal `RECOMBINED` for one unwound by a recombination; it is null on a determination that was never voided."

        Design: Corner/state_machines/withdrawn_referral_and_voided_determination_reject_further_transitions
        """
        admission = _discharged_without_notes(api)
        voided = fixtures.void(
            api,
            admission.determination_id,
            void_reason="DATA_ENTRY_ERROR",
            headers=third_analyst,
        )
        assert voided["status"] == DeterminationStatus.VOIDED, (
            "voiding a DRAFT determination must reach VOIDED, got {!r}".format(voided["status"])
        )
        assert voided["void_reason"] == "DATA_ENTRY_ERROR"

        second_void = api.void_determination(
            admission.determination_id,
            factories.void_payload("AUDIT_CORRECTION"),
            headers=third_analyst,
        )
        validate_error(second_void, ApiErrorId.ERR_INVALID_STATE)

        finalization = api.finalize_determination(
            admission.determination_id, headers=second_analyst
        )
        validate_error(finalization, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fixtures.read_determination(api, admission.determination_id)
        assert unchanged["status"] == DeterminationStatus.VOIDED
        assert unchanged["void_reason"] == "DATA_ENTRY_ERROR", (
            "the refused second void must not overwrite the reason, got {!r}".format(
                unchanged["void_reason"]
            )
        )
        assert_unset(unchanged, "finalized_by_user_id")

    def test_the_draft_void_returns_the_stay_to_pending_and_leaves_the_ledger_empty(
        self, api, third_analyst
    ):
        """Voiding the only draft unwinds the stay's payment dimension and touches no ledger figure.

        Nothing on this stay was ever finalized, so there is nothing for the ledger to give
        back: a draft void is declared to touch no ledger, and only `FINAL` determinations
        contribute to a period's money and count in the first place. What the void does move
        is the stay: with no determination left in `DRAFT` or `FINAL`, the payment dimension
        falls back to `PENDING` and the mirrored payment percentage is cleared, while the
        clinical dimension stays `DISCHARGED`. The period keeps the one admission it
        counted, because a void reverses pricing and not an admission.

        PRD 3.7: "Voiding a `DRAFT` determination is `DRAFT → VOIDED` and touches no ledger; when no other determination on the stay remains in `DRAFT` or `FINAL`, the stay's `payment_review_status` reverts `PRICED → PENDING` and its `discharge_payment_pct` is cleared to null."
        PRD 3.9: "Determinations in `DRAFT` or `VOIDED` contribute nothing to either figure."
        PRD 3.3: "The admission also does four things beyond the stay itself: the referral's `status` becomes `ADMITTED`, `Patient.open_referral_count` is recomputed to 0, the period's `total_admissions` is increased by 1, and the referring hospital's `admissions_in_period` is increased by 1."

        Design: Corner/state_machines/withdrawn_referral_and_voided_determination_reject_further_transitions
        """
        admission = _discharged_without_notes(api)
        fixtures.void(
            api,
            admission.determination_id,
            void_reason="DATA_ENTRY_ERROR",
            headers=third_analyst,
        )

        stay = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PENDING)
        assert_unset(stay, "discharge_payment_pct")

        period = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(period, total_payment_cents=0, final_determination_count=0)
        assert_integer_field(period, "total_admissions", 1)


class TestDischargeIsNotRepeatable:
    """A discharged stay refuses a second discharge, and the cascade does not run twice."""

    def test_a_second_discharge_is_refused_and_overwrites_nothing(self, api, nurse):
        """The replay carries a different disposition and cost, and neither reaches the stay.

        Discharge is declared only from `ADMITTED`, and the first call moved the stay to
        `DISCHARGED`, so the source state no longer exists. The replay deliberately differs
        from the original in both of its required inputs — `SNF` instead of `HOME`, and a
        cost nearly ten times larger — so if the endpoint were to process the request at all
        the difference would be visible. The stay still reporting the original disposition
        and cost, on an unchanged `version`, is what shows the refusal happened before any
        write.

        PRD 3.6: "The transition is `ADMITTED → DISCHARGED` and `discharged_at` is stamped from the logical clock."
        PRD 2.8: "Violations return `ERR_INVALID_STATE` (409)."
        PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row."

        Design: Corner/state_machines/discharging_the_same_stay_twice_is_refused
        """
        admission = _discharged_without_notes(api)
        settled = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(settled, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)
        assert_instant_equals(settled["discharged_at"], DISCHARGE_INSTANT, "discharged_at")
        version_before = settled["version"]

        replay = api.discharge_stay(
            admission.stay_id,
            factories.discharge_payload(
                discharge_disposition=DischargeDisposition.SNF,
                estimated_cost_cents=9999999,
            ),
            headers=nurse,
        )
        validate_error(replay, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(unchanged, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)
        assert unchanged["discharge_disposition"] == DischargeDisposition.HOME, (
            "the refused replay must not overwrite the disposition, got {!r}".format(
                unchanged["discharge_disposition"]
            )
        )
        assert_instant_equals(unchanged["discharged_at"], DISCHARGE_INSTANT, "discharged_at")
        assert unchanged["version"] == version_before, (
            "a refused discharge is not a mutation, so version must stay at {}, got {}".format(
                version_before, unchanged["version"]
            )
        )

    def test_the_refused_replay_does_not_run_the_cascade_a_second_time(self, api, nurse):
        """One discharge produced one determination and one review, and the replay adds neither.

        The cascade is the expensive part of a discharge: it prices the stay and opens a
        review. If the second call were processed even partially it would leave a second
        determination alongside the first, or a second review, and the specification allows
        at most one live review per stay. Counting both collections after the refusal is
        therefore the direct test that the replay was inert, and the surviving determination
        still carries the original cost the first discharge priced it from.

        PRD 3.6: "*Level two* follows because the stay became `DISCHARGED`: a `PaymentDetermination` is created for it with `status` `DRAFT` and `priced_by_user_id` set to the literal `SYSTEM` rather than to any human `X-User-ID`."
        PRD 3.6: "At most one live review exists per stay."

        Design: Corner/state_machines/discharging_the_same_stay_twice_is_refused
        """
        admission = _discharged_without_notes(api)

        replay = api.discharge_stay(
            admission.stay_id,
            factories.discharge_payload(
                discharge_disposition=DischargeDisposition.SNF,
                estimated_cost_cents=9999999,
            ),
            headers=nurse,
        )
        validate_error(replay, ApiErrorId.ERR_INVALID_STATE)

        determinations = fixtures.determinations_of(api, admission.stay_id)
        assert len(determinations) == 1, (
            "one discharge prices the stay once, so exactly one determination must exist, "
            "got {}".format(len(determinations))
        )
        assert determinations[0]["id"] == admission.determination_id
        assert determinations[0]["status"] == DeterminationStatus.DRAFT

        reviews = fixtures.reviews_of(api, admission.stay_id)
        assert len(reviews) == 1, (
            "at most one live review exists per stay, got {}".format(len(reviews))
        )
        assert reviews[0]["id"] == admission.review_id
        assert reviews[0]["status"] == ReviewStatus.OPEN


class TestReviewQueryCycleReturnsToOpen:
    """OPEN → QUERIES_ISSUED → OPEN, driven by one query issued, answered, closed and rescored."""

    def test_issuing_a_query_moves_the_open_review_to_queries_issued(self, api, nurse):
        """A nurse-issued query is stamped from the clock, due in 72 hours, and owned by that nurse.

        The cascade left this review `OPEN` because its score of 67 is below the highest
        band, so no query exists until a human asks for one. The nurse issues it at the
        discharge instant, which fixes both stamps: the issue instant is read from the
        logical clock, and the response deadline is exactly three full days later. The
        issuing identity matters because it is the identity a later close must differ from,
        and this query was asked for by a person, so it must carry that person's user id and
        not the system literal a cascade-issued query would carry. The review follows the
        query out of `OPEN`.

        PRD 3.8: "The new query carries `denial_risk_review_id` naming the issuing review and `stay_id` copied from that review for direct filtering, enters `status` `ISSUED` with `issued_at` stamped from the logical clock and `due_at` computed as `issued_at` plus 72 hours — three full days — and records the acting nurse's `X-User-ID` as `issued_by_user_id`."
        PRD 3.8: "A review in `OPEN` moves `OPEN → QUERIES_ISSUED`; a review already in `QUERIES_ISSUED` stays there."

        Design: Corner/state_machines/review_returns_to_open_after_its_query_is_answered_and_closed
        """
        admission = _discharged_without_notes(api)
        assert admission.review["status"] == ReviewStatus.OPEN
        assert_integer_field(admission.review, "effective_score", 67)

        query = fixtures.issue_query(
            api,
            admission.review_id,
            query_type=QueryType.IDT_PARTICIPATION,
            headers=nurse,
        )

        assert query["status"] == QueryStatus.ISSUED, (
            "a new query must enter ISSUED, got {!r}".format(query["status"])
        )
        assert query["denial_risk_review_id"] == admission.review_id
        assert query["stay_id"] == admission.stay_id
        assert_instant_equals(query["issued_at"], DISCHARGE_INSTANT, "issued_at")
        assert_instant_equals(
            query["due_at"],
            shift_hours(DISCHARGE_INSTANT, QUERY_RESPONSE_WINDOW_HOURS),
            "due_at",
        )
        assert query["issued_by_user_id"] == NURSE_ID, (
            "a nurse-issued query must record {!r}, not the system literal, got {!r}".format(
                NURSE_ID, query["issued_by_user_id"]
            )
        )
        assert query["issued_by_user_id"] != SYSTEM_ACTOR
        assert_unset(
            query, "response_text", "answered_at", "answered_by_physician_id", "closed_by_user_id"
        )

        review = fixtures.read_review(api, admission.review_id)
        assert review["status"] == ReviewStatus.QUERIES_ISSUED, (
            "issuing from OPEN must move the review to QUERIES_ISSUED, got {!r}".format(
                review["status"]
            )
        )

    def test_the_answer_credits_the_review_but_leaves_the_cycle_open(self, api, nurse):
        """Answering drops the effective score by twelve, and the review stays in QUERIES_ISSUED.

        The physician answers inside the window, so the query moves off `ISSUED` and records
        who answered it. That answer earns the review its credit: the raw total is unchanged
        at 67, but one answered query subtracts twelve, and the effective score is the
        query-adjusted variant as soon as the answered count is above zero — 55, still inside
        the same band. What the answer does not do is close the querying cycle: returning the
        review to `OPEN` is the rescore's job, and no rescore has run, so the review is still
        in `QUERIES_ISSUED`.

        PRD 3.8: "On success the query moves `ISSUED → ANSWERED`, `answered_at` is stamped from the logical clock, `answered_by_physician_id` records the acting physician's `X-User-ID`, the review's `answered_query_count` increases by 1, and the denial-risk score is recomputed, so the `risk_band` may fall."
        PRD 3.8: "The review's `effective_score` is the `query_adjusted_score` when `answered_query_count` is greater than 0, and the `as_documented_score` otherwise."
        PRD 3.8: "`risk_band` is `HIGH` when `effective_score` is at least 70, `MODERATE` when `effective_score` is at least 40 but below 70, and `LOW` below 40."

        Design: Corner/state_machines/review_returns_to_open_after_its_query_is_answered_and_closed
        """
        admission = _discharged_without_notes(api)
        query = fixtures.issue_query(
            api,
            admission.review_id,
            query_type=QueryType.IDT_PARTICIPATION,
            headers=nurse,
        )

        answered = fixtures.answer_query(
            api, query["id"], admission.world.physician_headers
        )

        assert answered["status"] == QueryStatus.ANSWERED, (
            "an answer inside the window must reach ANSWERED, got {!r}".format(
                answered["status"]
            )
        )
        assert answered["answered_by_physician_id"] == admission.world.physician_id, (
            "answered_by_physician_id must be the acting physician {!r}, got {!r}".format(
                admission.world.physician_id, answered["answered_by_physician_id"]
            )
        )
        assert_instant_equals(answered["answered_at"], DISCHARGE_INSTANT, "answered_at")

        review = fixtures.read_review(api, admission.review_id)
        assert_integer_field(review, "answered_query_count", 1)
        assert_integer_field(review, "as_documented_score", 67)
        assert_integer_field(review, "effective_score", 55)
        assert review["risk_band"] == RiskBand.MODERATE, (
            "an effective score of 55 is still MODERATE, got {!r}".format(review["risk_band"])
        )
        assert review["status"] == ReviewStatus.QUERIES_ISSUED, (
            "the answer alone does not return the review to OPEN, got {!r}".format(
                review["status"]
            )
        )

    def test_closing_the_query_keeps_its_credit_and_the_rescore_reopens_the_review(
        self, api, nurse, second_nurse
    ):
        """A second nurse closes the answered query, and the rescore then completes the cycle.

        Closing is declared only from `ANSWERED` and only by someone other than the issuer,
        so the first nurse issues and the second closes. The close is not a withdrawal of the
        answer: an answered query keeps its credit once closed, and the credit is counted for
        queries in `ANSWERED` and `CLOSED` alike, so the effective score stays at 55 rather
        than springing back to 67. With nothing left in `ISSUED`, the rescore finds no query
        blocking the review and returns it to `OPEN`, which is the closing leg of the cycle.

        PRD 3.8: "The transition is `ANSWERED → CLOSED`, `closed_by_user_id` records the acting nurse's `X-User-ID`, and the query keeps its answered-query credit in the score."
        PRD 3.8: "The count of answered queries, `answered_query_count`, counts the review's `DocumentationQuery` rows whose `status` is `ANSWERED` or `CLOSED`; queries in `ISSUED`, `EXPIRED` or `VOIDED` earn no credit."
        PRD 3.8: "When the review was in `QUERIES_ISSUED` and no query remains in `ISSUED` after the sweep, the rescore returns the review to `OPEN` — the cycle `OPEN → QUERIES_ISSUED → OPEN` may repeat for as many rounds of querying as the case needs."

        Design: Corner/state_machines/review_returns_to_open_after_its_query_is_answered_and_closed
        """
        admission = _discharged_without_notes(api)
        query = fixtures.issue_query(
            api,
            admission.review_id,
            query_type=QueryType.IDT_PARTICIPATION,
            headers=nurse,
        )
        fixtures.answer_query(api, query["id"], admission.world.physician_headers)

        closed = fixtures.close_query(api, query["id"], headers=second_nurse)
        assert closed["status"] == QueryStatus.CLOSED, (
            "closing an answered query must reach CLOSED, got {!r}".format(closed["status"])
        )
        assert closed["closed_by_user_id"] == NURSE_2_ID, (
            "closed_by_user_id must be the closing nurse {!r}, got {!r}".format(
                NURSE_2_ID, closed["closed_by_user_id"]
            )
        )

        rescored = fixtures.rescore(api, admission.review_id)
        assert rescored["status"] == ReviewStatus.OPEN, (
            "with no query left in ISSUED the rescore must return the review to OPEN, "
            "got {!r}".format(rescored["status"])
        )
        assert_integer_field(rescored, "answered_query_count", 1)
        assert_integer_field(rescored, "effective_score", 55)
        assert rescored["risk_band"] == RiskBand.MODERATE


def _eligible_plan_and_uncredentialed_physicians(api):
    """A plan at step two, plus a suspended pulmonologist and an active wound-care physician.

    The world's own physician is an active pulmonologist, so the returned trio covers all
    three combinations the close gate distinguishes: right specialty but suspended, active
    but wrong specialty, and both correct.
    """
    world, admission, plan = _stay_with_open_weaning_plan(api)
    suspended = fixtures.add_physician(api, specialty=Specialty.PULMONOLOGY)
    suspended = fixtures.suspend_physician(api, suspended["id"])
    wound_care = fixtures.add_physician(api, specialty=Specialty.WOUND_CARE)
    fixtures.record_sbt(api, plan["id"], outcome=SbtOutcome.TOLERATED, sbt_hours=2)
    plan = fixtures.record_sbt(api, plan["id"], outcome=SbtOutcome.TOLERATED, sbt_hours=5)
    assert plan["liberation_eligible"] is True, (
        "two tolerated trials must leave the plan liberation-eligible, got {!r}".format(
            plan["liberation_eligible"]
        )
    )
    return world, admission, plan, suspended, wound_care


class TestWeaningCloseChecksTheClosingPhysician:
    """The close gate reads the physician's specialty and credential status, not just the plan."""

    def test_a_suspended_pulmonologist_may_not_close_the_plan(self, api, officer):
        """The right specialty is not enough: a suspended credential blocks the close.

        This physician is a pulmonologist, so the specialty half of the requirement is
        satisfied, and the plan is liberation-eligible, so the progression gate is satisfied
        too. The only defect is that the officer has toggled her credential to `SUSPENDED`,
        and a suspended physician is explicitly barred from closing weaning plans. The
        refusal must therefore name the credentialing rule rather than the plan's state, and
        the plan must be left open with its close stamps unwritten.

        PRD 3.1: "A `ComplianceOfficer` may later toggle that field to `SUSPENDED` or back to `ACTIVE` by submitting the desired `credential_status`; a suspended physician can no longer close weaning plans or answer documentation queries."
        PRD 2.8: "The physician closing a weaning plan must have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`; the physician answering a documentation query must have `credential_status` `ACTIVE` regardless of specialty."

        Design: Corner/state_machines/weaning_close_by_a_suspended_or_wrong_specialty_physician_is_rejected
        """
        _world, _admission, plan, suspended, _wound_care = (
            _eligible_plan_and_uncredentialed_physicians(api)
        )
        assert suspended["credential_status"] == CredentialStatus.SUSPENDED
        assert suspended["specialty"] == Specialty.PULMONOLOGY

        refused = api.close_weaning_plan(
            plan["id"],
            factories.close_plan_payload(outcome=WeaningCloseOutcome.LIBERATED),
            headers=make_attending_physician_headers(suspended["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_PHYSICIAN_NOT_CREDENTIALED)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.PROGRESSING, (
            "a refused close must leave the plan in PROGRESSING, got {!r}".format(
                unchanged["status"]
            )
        )
        assert_unset(unchanged, "closed_at", "closed_by_physician_id")
        assert unchanged["version"] == plan["version"], (
            "a refused close is not a mutation, so version must stay at {}, got {}".format(
                plan["version"], unchanged["version"]
            )
        )

    def test_an_active_wound_care_physician_may_not_close_the_plan(self, api):
        """An active credential is not enough either: the close is reserved to pulmonology.

        This physician has never been suspended, so the credential half of the requirement
        is satisfied. Her specialty is `WOUND_CARE`, which is a legitimate specialty on this
        service — it is the one the complex-wound qualifying track exists for — but the
        weaning close names `PULMONOLOGY` specifically. The refusal shares an error id with
        the suspended case because both are the same credentialing rule, and again nothing
        may be written to the plan.

        PRD 2.8: "The physician closing a weaning plan must have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`; the physician answering a documentation query must have `credential_status` `ACTIVE` regardless of specialty."
        PRD 2.8: "Violations return `ERR_PHYSICIAN_NOT_CREDENTIALED` (422)."

        Design: Corner/state_machines/weaning_close_by_a_suspended_or_wrong_specialty_physician_is_rejected
        """
        _world, _admission, plan, _suspended, wound_care = (
            _eligible_plan_and_uncredentialed_physicians(api)
        )
        assert wound_care["credential_status"] == CredentialStatus.ACTIVE
        assert wound_care["specialty"] == Specialty.WOUND_CARE

        refused = api.close_weaning_plan(
            plan["id"],
            factories.close_plan_payload(outcome=WeaningCloseOutcome.LIBERATED),
            headers=make_attending_physician_headers(wound_care["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_PHYSICIAN_NOT_CREDENTIALED)

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["status"] == WeaningPlanStatus.PROGRESSING
        assert_unset(unchanged, "closed_at", "closed_by_physician_id")
        assert unchanged["version"] == plan["version"]

    def test_the_active_pulmonologist_closes_the_plan_after_both_refusals(self, api):
        """The same request from a credentialed pulmonologist succeeds and records her identity.

        The plan, the payload and the outcome are identical across all three attempts; only
        the acting physician changes. Two refusals leave the plan exactly as the second
        tolerated trial left it, and then the world's own physician — active and a
        pulmonologist — closes it. Because `closed_by_physician_id` records the acting
        physician, the field is the direct evidence that the successful close was attributed
        to the third physician rather than to either of the two the gate turned away.

        PRD 2.8: "The physician closing a weaning plan must have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`; the physician answering a documentation query must have `credential_status` `ACTIVE` regardless of specialty."
        PRD 3.4: "Both closes stamp `closed_at` from the logical clock and write the acting physician's `X-User-ID` into `closed_by_physician_id`, and both require the acting physician to have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`."

        Design: Corner/state_machines/weaning_close_by_a_suspended_or_wrong_specialty_physician_is_rejected
        """
        world, _admission, plan, suspended, wound_care = (
            _eligible_plan_and_uncredentialed_physicians(api)
        )

        for physician_id in (suspended["id"], wound_care["id"]):
            refused = api.close_weaning_plan(
                plan["id"],
                factories.close_plan_payload(outcome=WeaningCloseOutcome.LIBERATED),
                headers=make_attending_physician_headers(physician_id),
            )
            validate_error(refused, ApiErrorId.ERR_PHYSICIAN_NOT_CREDENTIALED)

        before_close = fixtures.read_plan(api, plan["id"])
        assert before_close["version"] == plan["version"], (
            "two refused closes must leave version at {}, got {}".format(
                plan["version"], before_close["version"]
            )
        )
        assert_unset(before_close, "closed_at", "closed_by_physician_id")

        closed = fixtures.close_plan(
            api, plan["id"], WeaningCloseOutcome.LIBERATED, world.physician_headers
        )

        assert closed["status"] == WeaningPlanStatus.LIBERATED, (
            "the credentialed pulmonologist must be able to close, got {!r}".format(
                closed["status"]
            )
        )
        assert closed["closed_by_physician_id"] == world.physician_id, (
            "closed_by_physician_id must be {!r}, got {!r}".format(
                world.physician_id, closed["closed_by_physician_id"]
            )
        )
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")


def _parent_with_one_closed_and_one_issued_query(api):
    """A discharged parent stay carrying two queries in different states, plus a readmission.

    The period is deliberately a single August so both stays fall inside it, which is one of
    the recombination preconditions. The parent runs 2026-08-01 to 2026-08-10 and its review
    is left `MODERATE`, so both queries on it were asked for by a nurse rather than by the
    cascade. One is carried all the way to `CLOSED`; the other is left sitting in `ISSUED`.
    The child is admitted on 2026-08-12, two whole days after the parent's discharge.
    """
    world = fixtures.build_world(
        api,
        period={
            "period_label": "AUG2026",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        },
    )
    parent = _discharged_without_notes(
        api,
        world=world,
        disposition=DischargeDisposition.ACUTE_TRANSFER,
        discharge_instant="2026-08-10T00:00:00Z",
    )
    query_a = fixtures.issue_query(
        api, parent.review_id, query_type=QueryType.IDT_PARTICIPATION
    )
    fixtures.answer_query(api, query_a["id"], world.physician_headers)
    query_a = fixtures.close_query(api, query_a["id"])
    query_b = fixtures.issue_query(
        api,
        parent.review_id,
        query_type=QueryType.VENT_WEANING_RATIONALE,
        prompt_text="Explain why no ventilator weaning plan was opened on this stay.",
    )

    fixtures.advance_clock(api, "2026-08-12T00:00:00Z")
    patient = fixtures.read_patient(api, world.patient_id)
    child = fixtures.admitted_stay(
        api,
        world,
        patient_version=patient["version"],
        prior_acute_discharge_at="2026-08-10T00:00:00Z",
    )
    return world, parent, child, query_a, query_b


class TestRecombinationVoidsOnlyTheLiveQuery:
    """The fold reopens the parent and voids its review, sparing the query already closed."""

    def test_the_fold_retires_the_child_and_reopens_the_parent(self, api, officer):
        """The child becomes terminal and stops counting; the parent goes back to ADMITTED.

        The readmission on 2026-08-12 follows the parent's discharge on 2026-08-10 by two
        whole days, inside the three-day window, so the officer may declare the two a single
        continuous stay. The operation is addressed to the child and names the parent, and it
        has two halves. The child is retired into a terminal status, points at its parent and
        stops counting as an admission. The parent is reopened: its discharge stamps are
        cleared so it looks admitted again, its resume instant is taken from the child's
        admission, and the nine covered days it had already banked are frozen onto
        `carried_los_days` so the eventual second discharge can add to them rather than start
        over. Its payment dimension falls back to `PENDING` because the pricing behind it has
        just been unwound.

        PRD 3.5: "The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."
        PRD 3.5: "The **parent** is reopened, moving `DISCHARGED → ADMITTED`."
        PRD 3.5: "Its `carried_los_days` is frozen at the whole-day count from its `admitted_at` to its `discharged_at` — the covered days already banked from the pre-recombination segment — its `resumed_at` is stamped with the child's `admitted_at`, and both its `discharged_at` and its `discharge_disposition` are cleared to null."
        PRD 3.5: "Its `payment_review_status` reverts to `PENDING`."

        Design: Corner/state_machines/recombination_voids_the_issued_query_but_leaves_the_closed_one
        """
        _world, parent, child, _query_a, _query_b = (
            _parent_with_one_closed_and_one_issued_query(api)
        )

        folded = fixtures.recombine(api, child.stay_id, parent.stay_id, headers=officer)

        assert_stay_dimensions(folded, ClinicalStatus.RECOMBINED, PaymentReviewStatus.PENDING)
        assert folded["interrupted_parent_stay_id"] == parent.stay_id, (
            "the child must record its parent {!r}, got {!r}".format(
                parent.stay_id, folded["interrupted_parent_stay_id"]
            )
        )
        assert folded["counts_toward_admission_threshold"] is False, (
            "a recombined child stops counting as an admission, got {!r}".format(
                folded["counts_toward_admission_threshold"]
            )
        )

        reopened = fixtures.read_stay(api, parent.stay_id)
        assert_stay_dimensions(reopened, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_unset(reopened, "discharged_at", "discharge_disposition")
        assert_instant_equals(reopened["resumed_at"], "2026-08-12T00:00:00Z", "resumed_at")
        assert_integer_field(reopened, "carried_los_days", 9)

    def test_the_fold_voids_the_issued_query_and_the_review_but_not_the_closed_query(
        self, api, officer
    ):
        """Only the query still in flight is voided; the one already closed keeps its status.

        The cascade unwinds downward: the parent's draft determination is voided, that voids
        the review built on it, and that in turn voids the queries hanging off the review —
        but only those still in `ISSUED` or `ANSWERED`. The first query was answered and then
        closed, and `CLOSED` is terminal for a query, so it is out of reach of the sweep. The
        second was left in `ISSUED`, so it is squarely inside it. Listing the review's queries
        afterwards must therefore return both rows, one in each terminal status, which is
        what shows the sweep discriminated on status rather than voiding everything it found.

        PRD 3.5: "Voiding the determinations in turn voids the compliance work built on them: the parent's `DenialRiskReview` becomes `VOIDED`, and every `DocumentationQuery` on that review whose `status` is `ISSUED` or `ANSWERED` becomes `VOIDED` as well."
        PRD 3.8: "`CLOSED`, `EXPIRED` and `VOIDED` are all terminal for a query."

        Design: Corner/state_machines/recombination_voids_the_issued_query_but_leaves_the_closed_one
        """
        _world, parent, child, query_a, query_b = (
            _parent_with_one_closed_and_one_issued_query(api)
        )
        assert query_a["status"] == QueryStatus.CLOSED
        assert query_b["status"] == QueryStatus.ISSUED

        fixtures.recombine(api, child.stay_id, parent.stay_id, headers=officer)

        after_a = fixtures.read_query(api, query_a["id"])
        assert after_a["status"] == QueryStatus.CLOSED, (
            "a query already CLOSED is terminal and must survive the fold, got {!r}".format(
                after_a["status"]
            )
        )
        after_b = fixtures.read_query(api, query_b["id"])
        assert after_b["status"] == QueryStatus.VOIDED, (
            "a query still ISSUED must be voided by the fold, got {!r}".format(
                after_b["status"]
            )
        )

        review = fixtures.read_review(api, parent.review_id)
        assert review["status"] == ReviewStatus.VOIDED, (
            "the parent's review must be voided by the fold, got {!r}".format(review["status"])
        )

        determination = fixtures.read_determination(api, parent.determination_id)
        assert determination["status"] == DeterminationStatus.VOIDED
        assert determination["void_reason"] == VoidReason.RECOMBINED

        listed = fixtures.queries_of(api, denial_risk_review_id=parent.review_id)
        assert len(listed) == 2, (
            "the review still owns both queries, got {}".format(len(listed))
        )
        assert sorted(q["status"] for q in listed) == [QueryStatus.CLOSED, QueryStatus.VOIDED], (
            "the two queries must end in different terminal statuses, got {}".format(
                sorted(q["status"] for q in listed)
            )
        )
