"""
Which refusal wins when one request breaks two rules at once.

The specification fixes a single evaluation order for its preconditions and stops at the
first violated one, so a request that is wrong for two reasons has exactly one correct
answer. Two pairs are exercised here. On admission, the clinical eligibility gate outranks
the duplicate-admission check, and the state check deliberately steps aside for a referral
that screened out on clinical grounds, so all three candidates collapse onto one error id.
On interruption, the 24-hour buffer outranks the three-event cap, and because both refusals
carry HTTP 422 only the error id can distinguish them.

Each conflict test is paired with a test that fires the losing rule on its own, so a
passing conflict test cannot be explained by the winning rule being the only one an
implementation knows about.
"""

from typing import Any, Dict

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    ClinicalStatus,
    InterruptionStatus,
    QualifyingTrack,
    ReferralStatus,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

Json = Dict[str, Any]


def _complete_interruption(
    api: Any,
    stay_id: str,
    left_at: str,
    returned_at: str,
    destination: str = "HOME",
    advance_to_left_at: bool = True,
) -> Json:
    """One interruption opened at `left_at` and closed by a return at `returned_at`.

    A supplied `left_at` may not be after the current logical instant, so the clock is
    moved onto it first; the very first interruption of a stay starts at the clock's own
    epoch and therefore skips that move, which would otherwise break monotonicity.
    """
    if advance_to_left_at:
        fixtures.advance_clock(api, left_at)
    event = fixtures.interrupt(api, stay_id, destination=destination, left_at=left_at)
    fixtures.advance_clock(api, returned_at)
    return fixtures.return_from_interruption(api, event["id"])


def _stay_with_three_returned_interruptions(api: Any) -> Json:
    """An admitted stay carrying the three interruptions the cap allows, all returned.

    Each interruption runs one day and each one opens one second past the 24-hour buffer
    measured from the previous return, so the stay reaches the cap without ever having
    violated the buffer along the way.
    """
    admission = fixtures.admitted_stay(api)
    _complete_interruption(
        api,
        admission.stay_id,
        CLOCK_EPOCH,
        "2026-08-02T00:00:00Z",
        advance_to_left_at=False,
    )
    _complete_interruption(
        api, admission.stay_id, "2026-08-03T00:00:01Z", "2026-08-04T00:00:01Z"
    )
    third = _complete_interruption(
        api, admission.stay_id, "2026-08-05T00:00:02Z", "2026-08-06T00:00:02Z"
    )
    return {"admission": admission, "third_event": third}


class TestNotEligibleOutranksAlreadyAdmitted:
    """One admit call that is both clinically ineligible and a duplicate admission."""

    def test_an_ineligible_referral_on_an_already_admitted_patient_names_the_clinical_reason(
        self, api, intake
    ):
        """A doubly-invalid admit returns ERR_REFERRAL_NOT_ELIGIBLE, not the duplicate error.

        The patient is admitted on a qualifying referral and that stay is still ADMITTED,
        so the duplicate-admission check would fire. A second referral for the same patient
        is then screened on complete but non-qualifying data, so it sits in
        CRITERIA_NOT_MET with no qualifying track, which makes the eligibility gate fire as
        well. The eligibility gate is evaluated first and stops the request, so the single
        correct answer is the clinical one; the state check does not intervene either,
        because CRITERIA_NOT_MET is the one status it hands on.

        PRD 2.8: "Admission is permitted only when the referral's `qualifying_track` is `PMV` or `COMPLEX_WOUND`, else `ERR_REFERRAL_NOT_ELIGIBLE` (422)."
        PRD 2.8: "This is a patient-safety gate and deliberately outranks the duplicate-admission check below it, so a request that violates both returns this error rather than `ERR_PATIENT_ALREADY_ADMITTED`."
        PRD 2.8: "There is one deliberate carve-out: an admission attempt on a referral whose `status` is `CRITERIA_NOT_MET` is **not** reported here, but deferred to rule 9 so the caller learns the clinical reason rather than a generic state error."

        Design: Difficulty/priority_pair_validation_conflict/admit_rejected_with_not_eligible_outranking_already_admitted
        """
        world = fixtures.build_world(api)
        first = fixtures.admitted_stay(api, world)
        assert first.stay["clinical_status"] == ClinicalStatus.ADMITTED

        patient = fixtures.read_patient(api, world.patient_id)
        second = fixtures.create_referral(
            api,
            world,
            clinicals=factories.NEITHER_TRACK_CLINICALS,
            patient_version=patient["version"],
        )
        screened = fixtures.screen_referral(api, second["id"])
        assert screened["status"] == ReferralStatus.CRITERIA_NOT_MET
        assert screened["qualifying_track"] == QualifyingTrack.NONE

        refusal = api.admit_referral(second["id"], headers=intake)
        validate_error(refusal, ApiErrorId.ERR_REFERRAL_NOT_ELIGIBLE)

    def test_the_refused_admit_creates_no_second_stay_and_moves_no_counter(
        self, api, intake
    ):
        """The refusal leaves the first stay and the period's admission count untouched.

        Because the eligibility gate fires before anything is written, the patient must
        still hold exactly one stay, that stay must still be ADMITTED, and the period must
        still count a single admission. A partially applied admission would show up here as
        a second stay or as a denominator of two.

        PRD 2.8: "Admission is permitted only when the referral's `qualifying_track` is `PMV` or `COMPLEX_WOUND`, else `ERR_REFERRAL_NOT_ELIGIBLE` (422)."
        PRD 3.3: "The denominator is the period's `total_admissions`, which counts every `Stay` in the period whose `counts_toward_admission_threshold` is true."

        Design: Difficulty/priority_pair_validation_conflict/admit_rejected_with_not_eligible_outranking_already_admitted
        """
        world = fixtures.build_world(api)
        first = fixtures.admitted_stay(api, world)

        patient = fixtures.read_patient(api, world.patient_id)
        second = fixtures.create_referral(
            api,
            world,
            clinicals=factories.NEITHER_TRACK_CLINICALS,
            patient_version=patient["version"],
        )
        fixtures.screen_referral(api, second["id"])
        validate_error(
            api.admit_referral(second["id"], headers=intake),
            ApiErrorId.ERR_REFERRAL_NOT_ELIGIBLE,
        )

        surviving = fixtures.read_stay(api, first.stay_id)
        assert surviving["clinical_status"] == ClinicalStatus.ADMITTED

        period = fixtures.read_period(api, world.period_id)
        assertions.assert_integer_field(period, "total_admissions", 1)

        stays, _meta = validate_paginated(
            api.list_stays(params={"patient_id": world.patient_id}, headers=intake)
        )
        assertions.assert_ids_equal(stays, [first.stay_id])

    def test_the_duplicate_admission_check_fires_on_its_own_for_a_qualifying_referral(
        self, api, intake
    ):
        """With eligibility satisfied, the same patient's second admit is the duplicate error.

        This is the losing rule in isolation. The second referral screens through to
        CRITERIA_MET on the ventilation track, so the eligibility gate passes and the next
        check in the order is the one that refuses: the patient still holds a stay in
        ADMITTED. Seeing ERR_PATIENT_ALREADY_ADMITTED here is what proves the conflict test
        above was a genuine contest rather than a rule the server never evaluates.

        PRD 2.8: "The patient has no `Stay` whose `clinical_status` is `ADMITTED` or `INTERRUPTED`, else `ERR_PATIENT_ALREADY_ADMITTED` (409)."
        PRD 2.8: "A readmission is legal only after the prior stay reached `DISCHARGED`; folding it back into the earlier stay is a separate recombination call."

        Design: Difficulty/priority_pair_validation_conflict/admit_rejected_with_not_eligible_outranking_already_admitted
        """
        world = fixtures.build_world(api)
        fixtures.admitted_stay(api, world)

        patient = fixtures.read_patient(api, world.patient_id)
        second = fixtures.qualified_referral(
            api, world, patient_version=patient["version"]
        )
        assert second["status"] == ReferralStatus.CRITERIA_MET
        assert second["qualifying_track"] == QualifyingTrack.PMV

        validate_error(
            api.admit_referral(second["id"], headers=intake),
            ApiErrorId.ERR_PATIENT_ALREADY_ADMITTED,
        )

    def test_the_state_check_fires_on_its_own_for_a_referral_that_was_never_screened(
        self, api, intake
    ):
        """An admit from RECEIVED is the generic state error, so the carve-out is narrow.

        The state check is the other rule the conflict scenario silences. It is not absent:
        a referral that has never been screened sits in RECEIVED, which the specification
        lists explicitly as still yielding the state error. Only CRITERIA_NOT_MET is handed
        on to the eligibility gate.

        PRD 2.8: "Admission attempted on a referral in `RECEIVED`, `INFO_REQUESTED`, `ADMITTED`, `WITHDRAWN` or `SUPERSEDED` is still `ERR_INVALID_STATE`."
        PRD 3.3: "The referral must be in `CRITERIA_MET`; an attempt from `RECEIVED`, `INFO_REQUESTED`, `ADMITTED`, `WITHDRAWN` or `SUPERSEDED` is an illegal state transition."

        Design: Difficulty/priority_pair_validation_conflict/admit_rejected_with_not_eligible_outranking_already_admitted
        """
        world = fixtures.build_world(api)
        referral = fixtures.create_referral(api, world)
        assert referral["status"] == ReferralStatus.RECEIVED

        validate_error(
            api.admit_referral(referral["id"], headers=intake),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_ineligibility_fires_on_its_own_for_a_patient_holding_no_stay(
        self, api, intake
    ):
        """The winning rule also fires alone, so the conflict answer is not an artefact.

        A patient with no stay at all is offered a referral screened on complete
        non-qualifying data. Nothing else about the request is wrong, and the refusal is
        the same clinical one the doubly-invalid request produced.

        PRD 2.8: "Admission is permitted only when the referral's `qualifying_track` is `PMV` or `COMPLEX_WOUND`, else `ERR_REFERRAL_NOT_ELIGIBLE` (422)."
        PRD 3.2: "A referral meeting neither takes `qualifying_track` `NONE`."

        Design: Difficulty/priority_pair_validation_conflict/admit_rejected_with_not_eligible_outranking_already_admitted
        """
        world = fixtures.build_world(api)
        referral = fixtures.create_referral(
            api, world, clinicals=factories.NEITHER_TRACK_CLINICALS
        )
        screened = fixtures.screen_referral(api, referral["id"])
        assert screened["status"] == ReferralStatus.CRITERIA_NOT_MET

        validate_error(
            api.admit_referral(referral["id"], headers=intake),
            ApiErrorId.ERR_REFERRAL_NOT_ELIGIBLE,
        )


class TestInterruptionBufferOutranksTheCountCap:
    """A fourth interruption that also sits exactly on the 24-hour buffer."""

    def test_a_fourth_interruption_on_the_buffer_boundary_reports_the_buffer_violation(
        self, api, nurse
    ):
        """Breaking the cap and the buffer at once returns ERR_INTERRUPTION_BUFFER_VIOLATION.

        The stay already carries the three interruptions the cap allows, all returned, so a
        fourth request breaks the count cap. Its `left_at` defaults to the logical clock,
        which has been moved to exactly 24 hours after the third event's `returned_at` — the
        buffer is measured on closed intervals, so exactly 24 hours is not yet clear of the
        earlier event and the buffer is broken too. Both refusals carry HTTP 422, so only
        the error id says which rule was evaluated first, and the temporal rule is the one
        that outranks the cap.

        PRD 2.8: "A new interruption must clear every earlier interruption of the same stay by at least 24 hours, else `ERR_INTERRUPTION_BUFFER_VIOLATION` (422)."
        PRD 2.8: "This temporal rule deliberately outranks the per-stay count cap below it."
        PRD 3.5: "That buffer is measured treating interruption intervals as **closed on both ends**, from `left_at` through `returned_at` inclusive, so a `left_at` falling exactly 24 hours after a previous event's `returned_at` is rejected while one second later is accepted."
        PRD 3.5: "The buffer check is evaluated before the count cap, so a request that violates both returns `ERR_INTERRUPTION_BUFFER_VIOLATION` rather than `ERR_INTERRUPTION_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/fourth_interruption_rejected_by_buffer_not_by_the_count_cap
        """
        built = _stay_with_three_returned_interruptions(api)
        admission = built["admission"]
        third = built["third_event"]
        assert third["status"] == InterruptionStatus.RETURNED
        assertions.assert_integer_field(third, "interruption_days", 1)

        on_the_boundary = assertions.shift_hours(third["returned_at"], 24)
        fixtures.advance_clock(api, on_the_boundary)

        refusal = api.interrupt_stay(
            admission.stay_id, factories.interrupt_payload(destination="HOME"), headers=nurse
        )
        validate_error(refusal, ApiErrorId.ERR_INTERRUPTION_BUFFER_VIOLATION)

    def test_the_refused_fourth_interruption_leaves_the_stay_and_its_counters_untouched(
        self, api, nurse
    ):
        """The stay keeps three interruptions, three interruption days and ADMITTED status.

        A refusal at the buffer check must write nothing: the count stays at three, the day
        total stays at the three returned days it accumulated, the clinical status stays
        ADMITTED rather than moving to INTERRUPTED, and the listing still holds exactly
        three events, all RETURNED. A fourth row here would mean the event was created
        before the buffer was checked.

        PRD 2.8: "A new interruption must clear every earlier interruption of the same stay by at least 24 hours, else `ERR_INTERRUPTION_BUFFER_VIOLATION` (422)."
        PRD 3.5: "When the return is inside the window, the event moves `OPEN → RETURNED` with `within_window` true, its `interruption_days` are added to the stay's `interruption_days_total`, and the stay moves `INTERRUPTED → ADMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/fourth_interruption_rejected_by_buffer_not_by_the_count_cap
        """
        built = _stay_with_three_returned_interruptions(api)
        admission = built["admission"]
        third = built["third_event"]

        fixtures.advance_clock(api, assertions.shift_hours(third["returned_at"], 24))
        validate_error(
            api.interrupt_stay(
                admission.stay_id,
                factories.interrupt_payload(destination="HOME"),
                headers=nurse,
            ),
            ApiErrorId.ERR_INTERRUPTION_BUFFER_VIOLATION,
        )

        stay = fixtures.read_stay(api, admission.stay_id)
        assertions.assert_integer_field(stay, "interruption_count", 3)
        assertions.assert_integer_field(stay, "interruption_days_total", 3)
        assert stay["clinical_status"] == ClinicalStatus.ADMITTED

        events = fixtures.interruptions_of(api, admission.stay_id)
        assert len(events) == 3
        assert [e["status"] for e in events] == [InterruptionStatus.RETURNED] * 3

    def test_the_count_cap_fires_on_its_own_once_the_buffer_is_clear(self, api, nurse):
        """One second past the buffer, the same fourth interruption is the cap violation.

        This is the losing rule in isolation. The scenario is identical except that the
        clock stands 24 hours and one second after the third event's return, which the
        specification says is accepted by the buffer. With the temporal rule satisfied the
        next check in the order refuses, and it names the cap. That the same request yields
        a different error id one second later is what makes the ordering observable.

        PRD 3.5: "That buffer is measured treating interruption intervals as **closed on both ends**, from `left_at` through `returned_at` inclusive, so a `left_at` falling exactly 24 hours after a previous event's `returned_at` is rejected while one second later is accepted."
        PRD 2.8: "The stay has fewer than three interruption events, else `ERR_INTERRUPTION_LIMIT_EXCEEDED` (422)."
        PRD 3.5: "The stay must carry fewer than three interruption events — and every event counts toward that cap regardless of its `status`, so an `EXPIRED` one still occupies a slot."

        Design: Difficulty/priority_pair_validation_conflict/fourth_interruption_rejected_by_buffer_not_by_the_count_cap
        """
        built = _stay_with_three_returned_interruptions(api)
        admission = built["admission"]
        third = built["third_event"]

        one_second_clear = assertions.shift_seconds(
            assertions.shift_hours(third["returned_at"], 24), 1
        )
        fixtures.advance_clock(api, one_second_clear)

        refusal = api.interrupt_stay(
            admission.stay_id, factories.interrupt_payload(destination="HOME"), headers=nurse
        )
        validate_error(refusal, ApiErrorId.ERR_INTERRUPTION_LIMIT_EXCEEDED)

    def test_the_buffer_fires_on_its_own_for_a_second_interruption_far_below_the_cap(
        self, api, nurse
    ):
        """With only one earlier event, the boundary instant is still a buffer violation.

        Here the cap is nowhere near reached — the stay carries a single returned
        interruption — so the buffer is the only rule that can refuse. Its verdict at
        exactly 24 hours past the return is the same one the doubly-invalid request
        produced, which is what shows the conflict answer came from the buffer rule and not
        from a cap rule mislabelled.

        PRD 3.5: "That buffer is measured treating interruption intervals as **closed on both ends**, from `left_at` through `returned_at` inclusive, so a `left_at` falling exactly 24 hours after a previous event's `returned_at` is rejected while one second later is accepted."
        PRD 3.5: "And a new interruption must clear every earlier interruption of the same stay by at least 24 hours."

        Design: Difficulty/priority_pair_validation_conflict/fourth_interruption_rejected_by_buffer_not_by_the_count_cap
        """
        admission = fixtures.admitted_stay(api)
        first = _complete_interruption(
            api,
            admission.stay_id,
            CLOCK_EPOCH,
            "2026-08-02T00:00:00Z",
            advance_to_left_at=False,
        )
        assert first["status"] == InterruptionStatus.RETURNED

        stay = fixtures.read_stay(api, admission.stay_id)
        assertions.assert_integer_field(stay, "interruption_count", 1)

        fixtures.advance_clock(api, assertions.shift_hours(first["returned_at"], 24))
        refusal = api.interrupt_stay(
            admission.stay_id, factories.interrupt_payload(destination="HOME"), headers=nurse
        )
        validate_error(refusal, ApiErrorId.ERR_INTERRUPTION_BUFFER_VIOLATION)
