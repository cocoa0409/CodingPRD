"""
Validation rules: precedence between competing gates, inclusive boundaries, and the
requirement that a refused write mutate nothing.

Every scenario here arms a rule that can only be reached by a request that is wrong in a
specific, narrow way — a discharge into a period that was closed underneath its stay, an
admission instant exactly equal to the acute discharge it follows, a documentation query
answered on the last legal second and then one second later. Where two rules are violated
at once, only the single error id the fixed evaluation order produces is accepted, and
where a call is refused the affected entities are re-read to prove nothing moved.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_REFERRAL_THRESHOLD_PCT,
    CLOCK_EPOCH,
    ClinicalStatus,
    CriteriaSetStatus,
    DeterminationStatus,
    EXPANDED_REFERRAL_THRESHOLD_PCT,
    HospitalType,
    InterruptionDestination,
    InterruptionStatus,
    MonitoringState,
    PaymentReviewStatus,
    PaymentVariant,
    PeriodStatus,
    QualifyingTrack,
    QueryStatus,
    QueryType,
    ReferralStatus,
    ReviewOutcome,
    ReviewStatus,
    WeaningCloseOutcome,
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
    day_count,
    factories,
    fixtures,
    shift_hours,
    shift_seconds,
    validate_error,
    validate_paginated,
    validate_success,
)

# A prior acute discharge one day before the clock epoch, so that an admission instant
# equal to it is legal and one day earlier than it is not.
PRIOR_ACUTE_JULY_31 = "2026-07-31T00:00:00Z"

CLINICALS_JULY_31 = dict(
    factories.PMV_CLINICALS, prior_acute_discharge_at=PRIOR_ACUTE_JULY_31
)


def _stays_of_patient(api, patient_id, headers):
    """Every stay the store holds for one patient, through the public list endpoint."""
    data, meta = validate_paginated(
        api.list_stays(params={"patient_id": patient_id}, headers=headers)
    )
    return data, meta


class TestDischargeIntoAClosedPeriod:
    """A period closed underneath an admitted stay turns its discharge into a refusal."""

    def test_discharging_a_stay_whose_period_closed_underneath_it_reports_period_closed(
        self, api, nurse, officer
    ):
        """A discharge on an `ADMITTED` stay in a `CLOSED` period is refused, not priced.

        The stay is admitted at the clock epoch and the period is then closed while the
        stay is still `ADMITTED` — a legal close, because an admitted stay holds no draft
        determination and the ledger of an unpriced period reconciles trivially. The
        period the stay owns is now `CLOSED`, so the period-openness gate fires on the
        later discharge before any clinical consideration: the answer is
        `ERR_PERIOD_CLOSED`, and the stay must still read `ADMITTED` with a null
        `discharged_at` and a `payment_review_status` of `PENDING`, because a refused
        cascade leaves no partial level behind.

        PRD 2.7: "Once a period is `CLOSED`, every further mutation touching a stay in that period — discharge, re-pricing, finalization, void, and share recomputation — is refused with `ERR_PERIOD_CLOSED` (HTTP 409), as is an attempt to close an already-closed period."
        PRD 3.3: "The new stay's `patient_id` and `referral_id` are copied from the admitting referral, its `cost_reporting_period_id` is the selected open period, its `clinical_status` is `ADMITTED`, its `payment_review_status` is `PENDING`, its `admitted_at` is the supplied value or the current logical instant, and its `counts_toward_admission_threshold` is true."

        Design: Corner/validations/discharge_into_a_closed_period_returns_period_closed
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        assert admission.stay["cost_reporting_period_id"] == admission.world.period_id

        closed = fixtures.close_period(api, admission.world.period_id)
        assert closed["status"] == PeriodStatus.CLOSED

        response = api.discharge_stay(
            admission.stay_id,
            factories.discharge_payload(estimated_cost_cents=1000000),
            headers=nurse,
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_CLOSED)

        after = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(
            after, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )
        assert_unset(
            after,
            "discharged_at",
            "discharge_disposition",
            "covered_los_days",
            "sso_threshold_days",
            "short_stay_outlier_applied",
            "discharge_payment_pct",
        )
        determinations = fixtures.determinations_of(api, admission.stay_id)
        assert determinations == [], (
            "the refused discharge priced the stay anyway: {}".format(determinations)
        )

    def test_closing_an_already_closed_period_is_refused_with_the_same_error(
        self, api, officer
    ):
        """A second close on a `CLOSED` period reports `ERR_PERIOD_CLOSED`.

        The same rule that blocks mutations inside a closed period also blocks a repeat
        close, so the operation is not idempotent: the first close moves the period to
        `CLOSED` and stamps `closed_at`, and the second is refused outright. The period's
        own `closed_at` must still read the instant of the first close afterwards.

        PRD 2.7: "Once a period is `CLOSED`, every further mutation touching a stay in that period — discharge, re-pricing, finalization, void, and share recomputation — is refused with `ERR_PERIOD_CLOSED` (HTTP 409), as is an attempt to close an already-closed period."

        Design: Corner/validations/discharge_into_a_closed_period_returns_period_closed
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        closed = fixtures.close_period(api, admission.world.period_id)
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")

        response = api.close_period(admission.world.period_id, headers=officer)
        validate_error(response, ApiErrorId.ERR_PERIOD_CLOSED)

        again = fixtures.read_period(api, admission.world.period_id)
        assert again["status"] == PeriodStatus.CLOSED
        assert_instant_equals(again["closed_at"], CLOCK_EPOCH, "closed_at")


class TestAdmissionAtThePriorAcuteDischargeInstant:
    """The admission-instant rule is inclusive at its lower bound."""

    def test_an_admitted_at_equal_to_the_prior_acute_discharge_instant_is_accepted(
        self, api, intake
    ):
        """An `admitted_at` exactly equal to `prior_acute_discharge_at` is admitted.

        The referral records a prior acute discharge at 2026-07-31T00:00:00Z and the
        admission supplies that very instant, a same-instant transfer from the acute bed
        into the LTCH bed. The rule bounds `admitted_at` from below by
        `prior_acute_discharge_at` with a greater-than-or-equal comparison, so equality
        satisfies it; the same instant also sits a full day before the logical clock, so
        the upper bound is satisfied too. The stay is created with the supplied instant
        stored verbatim rather than replaced by the clock reading.

        PRD 2.8: "`admitted_at`, whether supplied or defaulted from the logical clock, must be greater than or equal to the referral's `prior_acute_discharge_at`, else `ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE` (422); and must not be after the current logical instant, else `ERR_ADMISSION_IN_FUTURE` (422)."
        PRD 3.3: "Supplying one lets the admission proceed, records `admitted_with_override` as true on the resulting stay and stores the justification in `override_reason`; admissions that did not need an override carry `admitted_with_override` false and `override_reason` null."

        Design: Corner/validations/admit_exactly_at_the_prior_acute_discharge_instant_is_accepted
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world, clinicals=CLINICALS_JULY_31)
        assert_instant_equals(
            referral["prior_acute_discharge_at"],
            PRIOR_ACUTE_JULY_31,
            "prior_acute_discharge_at",
        )

        response = api.admit_referral(
            referral["id"],
            factories.admit_payload(admitted_at=PRIOR_ACUTE_JULY_31),
            headers=intake,
        )
        stay = validate_success(response, expected_status=201)

        assert_instant_equals(stay["admitted_at"], PRIOR_ACUTE_JULY_31, "admitted_at")
        assert_stay_dimensions(
            stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )
        assert stay["admitted_with_override"] is False
        assert_unset(stay, "override_reason")

        assert (
            fixtures.read_referral(api, referral["id"])["status"]
            == ReferralStatus.ADMITTED
        )


class TestNoOpenPeriodOutranksTheEligibilityGate:
    """Two armed gates on one admit call, and the earlier one wins."""

    def test_a_criteria_not_met_referral_admitted_into_a_closed_period_names_the_period(
        self, api, intake
    ):
        """A doubly invalid admit reports `ERR_NO_OPEN_PERIOD`, not the eligibility error.

        The referral screened to `CRITERIA_NOT_MET` with `qualifying_track` `NONE`, so the
        referral-eligibility gate is armed; the only period covering the admission date has
        been closed, so the period-openness gate is armed too. Those gates sit at
        positions seven and nine of one fixed order, and the first violated rule alone
        determines the response — so the fiscal envelope is reported and the clinical gate
        is never reached. The reverse answer would mean the eligibility check ran first.

        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."
        PRD 2.7: "Admission is the one operation where the period is not yet known: when no period exists whose `status` is `OPEN` and whose date range covers the admission date, whether because none covers that date or because the covering period is already `CLOSED`, the admission is refused with `ERR_NO_OPEN_PERIOD` (HTTP 422) rather than `ERR_PERIOD_CLOSED`."
        PRD 2.8: "Admission is permitted only when the referral's `qualifying_track` is `PMV` or `COMPLEX_WOUND`, else `ERR_REFERRAL_NOT_ELIGIBLE` (422)."

        Design: Corner/validations/no_open_period_outranks_the_eligibility_gate
        """
        world = fixtures.build_world(api)
        referral = fixtures.create_referral(
            api, world, clinicals=factories.NEITHER_TRACK_CLINICALS
        )
        screened = fixtures.screen_referral(api, referral["id"])
        assert screened["status"] == ReferralStatus.CRITERIA_NOT_MET
        assert screened["qualifying_track"] == QualifyingTrack.NONE

        closed = fixtures.close_period(api, world.period_id)
        assert closed["status"] == PeriodStatus.CLOSED

        response = api.admit_referral(referral["id"], {}, headers=intake)
        validate_error(response, ApiErrorId.ERR_NO_OPEN_PERIOD)

        after = fixtures.read_referral(api, referral["id"])
        assert after["status"] == ReferralStatus.CRITERIA_NOT_MET
        stays, meta = _stays_of_patient(api, world.patient_id, intake)
        assert stays == [], "the refused admission created a stay: {}".format(stays)
        assert meta["total_count"] == 0


def _stay_with_three_failed_trials(api):
    """A stay whose weaning plan has regressed after three failed trials.

    The plan is seeded with 100 ventilator hours and each trial adds 6, so the cumulative
    total reaches 118 — past the 96-hour intensity boundary — and the three attempts are
    exactly what a `VENT_DEPENDENT` close requires.
    """
    admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
    plan = fixtures.open_weaning_plan(api, admission.stay_id, vent_hours_total=100)
    for _ in range(3):
        fixtures.failed_sbt(api, plan["id"], vent_hours_since_last=6)
    return admission, fixtures.read_plan(api, plan["id"])


class TestWeaningPlanBlocksDischargeUntilClosed:
    """An unresolved ventilator weaning plan is a hard bar on discharge."""

    def test_discharge_is_refused_while_the_weaning_plan_is_still_in_sbt_trial(
        self, api, nurse
    ):
        """A plan in `SBT_TRIAL` blocks the discharge with `ERR_WEANING_PLAN_OPEN`.

        A newly opened plan enters `SBT_TRIAL`, which is one of the three unresolved
        statuses the discharge precondition names. The stay is otherwise perfectly
        dischargeable — `ADMITTED`, no open interruption, an `OPEN` period — so the plan is
        the sole cause. Because the refusal happens before the cascade runs, the stay must
        still read `ADMITTED` and `PENDING` with no determination and no review behind it.

        PRD 2.8: "A stay that has a `WeaningPlan` cannot be discharged while that plan is in `SBT_TRIAL`, `PROGRESSING` or `REGRESSED`, else `ERR_WEANING_PLAN_OPEN` (422)."

        Design: Corner/validations/discharge_is_blocked_while_the_weaning_plan_is_open_and_allowed_once_closed
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        plan = fixtures.open_weaning_plan(api, admission.stay_id)
        assert plan["status"] == WeaningPlanStatus.SBT_TRIAL

        response = api.discharge_stay(
            admission.stay_id, factories.discharge_payload(), headers=nurse
        )
        validate_error(response, ApiErrorId.ERR_WEANING_PLAN_OPEN)

        after = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(
            after, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )
        assert_unset(after, "discharged_at", "discharge_disposition")
        assert fixtures.determinations_of(api, admission.stay_id) == []
        assert fixtures.reviews_of(api, admission.stay_id) == []

    def test_discharge_is_refused_while_the_plan_is_regressed_and_accepted_once_closed(
        self, api, nurse
    ):
        """The same discharge is refused in `REGRESSED` and succeeds after the close.

        Three failed trials drive the plan to `REGRESSED`, still one of the three
        unresolved statuses, so the discharge is refused. The attending physician then
        closes the plan `VENT_DEPENDENT` — reachable from `REGRESSED` and permitted because
        the plan has the three attempts that close requires — and the identical discharge
        request now succeeds. That contrast is the whole point of the rule: the close is
        what lifts the bar, not the passage of time. The stay ran from 2026-08-01 to
        2026-08-20 with no interruptions, so its covered length of stay is the 19 whole
        days between those two calendar dates.

        PRD 3.6: "The stay must be in `clinical_status` `ADMITTED`, no interruption event on it may still be `OPEN`, its cost reporting period must be `OPEN`, and if the stay has a weaning plan that plan must already have reached `LIBERATED` or `VENT_DEPENDENT`; a plan still in `SBT_TRIAL`, `PROGRESSING` or `REGRESSED` blocks the discharge with `ERR_WEANING_PLAN_OPEN`."
        PRD 3.4: "A `VENT_DEPENDENT` close is reachable from `SBT_TRIAL`, from `PROGRESSING` and from `REGRESSED`, and requires `sbt_attempt_count` of at least 3; a plan with fewer attempts is refused with `ERR_INSUFFICIENT_SBT_ATTEMPTS`."
        PRD 3.4: "A closed plan no longer blocks discharge, which is the practical reason the close exists."

        Design: Corner/validations/discharge_is_blocked_while_the_weaning_plan_is_open_and_allowed_once_closed
        """
        admission, plan = _stay_with_three_failed_trials(api)
        assert plan["status"] == WeaningPlanStatus.REGRESSED
        assert_integer_field(plan, "sbt_attempt_count", 3)

        fixtures.advance_clock(api, "2026-08-20T00:00:00Z")
        blocked = api.discharge_stay(
            admission.stay_id, factories.discharge_payload(), headers=nurse
        )
        validate_error(blocked, ApiErrorId.ERR_WEANING_PLAN_OPEN)

        closed = fixtures.close_plan(
            api,
            plan["id"],
            WeaningCloseOutcome.VENT_DEPENDENT,
            admission.world.physician_headers,
        )
        assert closed["status"] == WeaningPlanStatus.VENT_DEPENDENT

        discharged = fixtures.discharge(api, admission.stay_id)
        assert_stay_dimensions(
            discharged, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED
        )
        assert_instant_equals(
            discharged["discharged_at"], "2026-08-20T00:00:00Z", "discharged_at"
        )
        assert_integer_field(discharged, "covered_los_days", 19)
        assert day_count("2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z") == 19

    def test_the_ventilator_hours_accrued_on_the_plan_select_the_standard_variant(
        self, api, nurse
    ):
        """A plan closed at 118 ventilator hours prices the stay as `STANDARD_LTCH_PPS`.

        The plan opened with a 100-hour seed and three failed trials each added 6 hours,
        because every trial record adds its `vent_hours_since_last` whatever its outcome.
        The cumulative 118 hours clears the 96-hour intensity criterion, and the referral
        records a prior acute discharge, so the determination the discharge cascade writes
        selects the standard variant rather than the site-neutral one.

        PRD 3.4: "The cumulative total is therefore the create-time seed plus the sum of `vent_hours_since_last` across every trial record on the plan, failed trials included; there is no decay and regression never subtracts ventilator hours."
        PRD 3.7: "When the referral records a prior acute discharge and at least one intensity criterion holds, `payment_variant` is `STANDARD_LTCH_PPS`; in every other case it is `SITE_NEUTRAL`."

        Design: Corner/validations/discharge_is_blocked_while_the_weaning_plan_is_open_and_allowed_once_closed
        """
        admission, plan = _stay_with_three_failed_trials(api)
        assert_vent_hours(plan, "vent_hours_total", 118)

        fixtures.close_plan(
            api,
            plan["id"],
            WeaningCloseOutcome.VENT_DEPENDENT,
            admission.world.physician_headers,
        )
        fixtures.advance_clock(api, "2026-08-20T00:00:00Z")
        fixtures.discharge(api, admission.stay_id)

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assert determination["status"] == DeterminationStatus.DRAFT
        assert_integer_field(determination, "covered_los_days_used", 19)


class TestQueryResponseWindowAtSeventyTwoHours:
    """The 72-hour response window is inclusive at its far end, to the second."""

    def test_an_answer_at_exactly_seventy_two_hours_is_accepted(self, api, nurse):
        """An answer stamped at exactly `due_at` is accepted and credits the review.

        The query is issued at the clock epoch, so its `due_at` is 2026-08-04T00:00:00Z —
        the epoch plus 72 hours. The clock is advanced to precisely that instant and the
        physician answers. The comparison is at-or-before, so the boundary instant is
        inside the window: the query moves to `ANSWERED`, `answered_at` takes the clock
        reading, the answering physician is recorded, and the review's answered-query count
        rises to 1 because an `ANSWERED` query earns the credit.

        PRD 2.8: "A query may be answered only within 72 hours of its `issued_at`, measured inclusively; at exactly 72 hours the answer is accepted, one second later it is refused with `ERR_QUERY_RESPONSE_WINDOW_EXPIRED` (422) and the query is marked `EXPIRED`."
        PRD 3.8: "On success the query moves `ISSUED → ANSWERED`, `answered_at` is stamped from the logical clock, `answered_by_physician_id` records the acting physician's `X-User-ID`, the review's `answered_query_count` increases by 1, and the denial-risk score is recomputed, so the `risk_band` may fall."

        Design: Corner/validations/query_answered_at_exactly_72_hours_passes_and_one_second_later_expires
        """
        admission = fixtures.discharged_stay(api)
        query = fixtures.issue_query(
            api, admission.review["id"], query_type=QueryType.IDT_PARTICIPATION
        )
        assert query["status"] == QueryStatus.ISSUED
        due_at = shift_hours(CLOCK_EPOCH, 72)
        assert_instant_equals(query["issued_at"], CLOCK_EPOCH, "issued_at")
        assert_instant_equals(query["due_at"], due_at, "due_at")

        fixtures.advance_clock(api, due_at)
        answered = fixtures.answer_query(
            api, query["id"], admission.world.physician_headers
        )

        assert answered["status"] == QueryStatus.ANSWERED
        assert_instant_equals(answered["answered_at"], due_at, "answered_at")
        assert answered["answered_by_physician_id"] == admission.world.physician_id
        assert answered["response_text"] is not None

        review = fixtures.read_review(api, admission.review["id"])
        assert_integer_field(review, "answered_query_count", 1)

    def test_an_answer_one_second_past_the_window_expires_the_query(self, api, nurse):
        """One second past `due_at` the answer is refused and the query flips to `EXPIRED`.

        The setup is identical to the accepted case except that the clock reads
        2026-08-04T00:00:01Z, one second beyond the inclusive boundary. The answer is
        refused with `ERR_QUERY_RESPONSE_WINDOW_EXPIRED`, and the refusal is not inert: the
        query is marked `EXPIRED` as the window closes. None of the answer's own fields may
        be written, and an `EXPIRED` query earns no credit, so the review's answered-query
        count stays at zero.

        PRD 3.8: "The query must be in `ISSUED`, the current logical instant must be at or before `due_at` — measured inclusively, so an answer at exactly 72 hours is accepted and one at 72 hours and one second is refused with `ERR_QUERY_RESPONSE_WINDOW_EXPIRED` and the query flips to `EXPIRED` — and the acting physician must have `credential_status` `ACTIVE`, regardless of specialty."
        PRD 3.8: "The count of answered queries, `answered_query_count`, counts the review's `DocumentationQuery` rows whose `status` is `ANSWERED` or `CLOSED`; queries in `ISSUED`, `EXPIRED` or `VOIDED` earn no credit."

        Design: Corner/validations/query_answered_at_exactly_72_hours_passes_and_one_second_later_expires
        """
        admission = fixtures.discharged_stay(api)
        query = fixtures.issue_query(
            api, admission.review["id"], query_type=QueryType.IDT_PARTICIPATION
        )
        due_at = shift_hours(CLOCK_EPOCH, 72)
        assert_instant_equals(query["due_at"], due_at, "due_at")

        fixtures.advance_clock(api, shift_seconds(due_at, 1))
        response = api.answer_query(
            query["id"],
            factories.answer_query_payload(),
            headers=admission.world.physician_headers,
        )
        validate_error(response, ApiErrorId.ERR_QUERY_RESPONSE_WINDOW_EXPIRED)

        after = fixtures.read_query(api, query["id"])
        assert after["status"] == QueryStatus.EXPIRED
        assert_unset(after, "response_text", "answered_at", "answered_by_physician_id")

        review = fixtures.read_review(api, admission.review["id"])
        assert_integer_field(review, "answered_query_count", 0)


class TestFourthInterruptionExhaustsThePerStayCap:
    """Three completed interruptions exhaust the stay's allowance for good."""

    def test_a_fourth_interruption_is_refused_on_the_count_even_though_all_returned(
        self, api, nurse
    ):
        """Three `RETURNED` interruptions fill the cap and the fourth is refused.

        The three absences are deliberately spaced two days apart, so the fourth request on
        2026-08-10 clears the previous return on 2026-08-08 by two full days and the buffer
        rule — which is evaluated before the count cap and would otherwise mask it — is
        satisfied. The cap is therefore the sole cause, and it counts the stay's whole
        interruption history rather than its currently open rows: all three earlier events
        are `RETURNED`, yet they still occupy their slots. The refusal leaves the stay
        `ADMITTED` with exactly three events and an unchanged three-day absence total.

        PRD 2.8: "The stay has fewer than three interruption events, else `ERR_INTERRUPTION_LIMIT_EXCEEDED` (422)."
        PRD 3.5: "The stay must carry fewer than three interruption events — and every event counts toward that cap regardless of its `status`, so an `EXPIRED` one still occupies a slot."
        PRD 3.5: "The buffer check is evaluated before the count cap, so a request that violates both returns `ERR_INTERRUPTION_BUFFER_VIOLATION` rather than `ERR_INTERRUPTION_LIMIT_EXCEEDED`."

        Design: Corner/validations/fourth_interruption_is_refused_by_the_per_stay_cap
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        stay_id = admission.stay_id

        first = fixtures.interrupt_and_return(
            api,
            stay_id,
            CLOCK_EPOCH,
            "2026-08-02T00:00:00Z",
            destination=InterruptionDestination.ACUTE_CARE,
        )
        fixtures.advance_clock(api, "2026-08-04T00:00:00Z")
        second = fixtures.interrupt_and_return(
            api,
            stay_id,
            "2026-08-04T00:00:00Z",
            "2026-08-05T00:00:00Z",
            destination=InterruptionDestination.ACUTE_CARE,
        )
        fixtures.advance_clock(api, "2026-08-07T00:00:00Z")
        third = fixtures.interrupt_and_return(
            api,
            stay_id,
            "2026-08-07T00:00:00Z",
            "2026-08-08T00:00:00Z",
            destination=InterruptionDestination.ACUTE_CARE,
        )
        for event in (first, second, third):
            assert event["status"] == InterruptionStatus.RETURNED
            assert_integer_field(event, "interruption_days", 1)
            assert event["within_window"] is True

        fixtures.advance_clock(api, "2026-08-10T00:00:00Z")
        response = api.interrupt_stay(
            stay_id,
            factories.interrupt_payload(
                destination=InterruptionDestination.ACUTE_CARE
            ),
            headers=nurse,
        )
        validate_error(response, ApiErrorId.ERR_INTERRUPTION_LIMIT_EXCEEDED)

        events, meta = validate_paginated(
            api.list_interruptions(stay_id, headers=nurse)
        )
        assert len(events) == 3, "expected three interruptions, found {}".format(
            len(events)
        )
        assert meta["total_count"] == 3
        assert first["id"] in [event["id"] for event in events]

        after = fixtures.read_stay(api, stay_id)
        assert after["clinical_status"] == ClinicalStatus.ADMITTED
        assert_integer_field(after, "interruption_days_total", 3)
        assert_integer_field(after, "interruption_count", 3)


_OVERRIDE_REASON = (
    "Sole regional ventilator-weaning capability; medical director approved."
)


def _breached_source_world(api):
    """Four admissions split evenly between a 25%-capped source and a 50%-capped one.

    Metro General is an ordinary acute-care source, so its ceiling is 25.00 and a half of
    the mix breaches it. Rural Access is critical-access, so its ceiling is 50.00 and the
    identical half share only warns. A fifth patient is referred by Metro and screened, so
    the caller has a `CRITERIA_MET` referral from a breached source ready to admit.
    """
    world = fixtures.build_world(api)
    rural = fixtures.add_hospital(
        api, name="Rural Access", hospital_type=HospitalType.CRITICAL_ACCESS
    )
    for hospital_id in (
        world.hospital_id,
        world.hospital_id,
        rural["id"],
        rural["id"],
    ):
        patient = fixtures.add_patient(api)
        fixtures.admitted_stay(
            api,
            world,
            clinicals=CLINICALS_JULY_31,
            patient_id=patient["id"],
            patient_version=patient["version"],
            hospital_id=hospital_id,
        )
    fixtures.recompute_shares(api, world.period_id)

    fifth = fixtures.add_patient(api)
    referral = fixtures.qualified_referral(
        api,
        world,
        clinicals=CLINICALS_JULY_31,
        patient_id=fifth["id"],
        patient_version=fifth["version"],
    )
    return world, rural, referral


class TestBreachedReferralSourceNeedsAnOverride:
    """A breached source is not barred outright; it is barred without a justification."""

    def test_admitting_from_a_breached_source_without_an_override_is_refused(
        self, api, intake
    ):
        """Metro General at 50.00% against a 25.00% ceiling blocks the bare admit.

        Four admissions make the period's mix thick enough to judge, and both sources sit
        at exactly half of it. Metro General's ceiling is 25.00 because it is neither
        co-located nor critical-access, and 50.00 is strictly greater than that, so it is
        `BREACHED`. Rural Access holds the identical share against a 50.00 ceiling: not
        strictly greater, so no breach, but greater than 45.00, so `WARNING`. The rule keys
        on `BREACHED` alone, so the admit from Metro is refused while the same share at
        Rural would not be, and the referral must still read `CRITERIA_MET`.

        PRD 3.1: "Two of those inputs determine how much of the LTCH's admission mix this hospital is allowed to supply: a hospital's `threshold_pct` is 50.00 when `is_colocated` is true **or** its `hospital_type` is `CRITICAL_ACCESS`, and 25.00 otherwise."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."
        PRD 3.3: "When the referring hospital of the referral being admitted has `monitoring_state` `BREACHED`, admission is refused with `ERR_REFERRAL_SOURCE_BREACHED` unless the request supplies a non-empty `override_reason`."

        Design: Corner/validations/a_breached_referral_source_admits_only_with_an_override_reason
        """
        world, rural, referral = _breached_source_world(api)

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 4)
        metro = fixtures.read_hospital(api, world.hospital_id)
        assert_pct(metro, "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(metro, 2, 50.00, MonitoringState.BREACHED)
        rural_now = fixtures.read_hospital(api, rural["id"])
        assert_pct(rural_now, "threshold_pct", EXPANDED_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(rural_now, 2, 50.00, MonitoringState.WARNING)

        response = api.admit_referral(referral["id"], {}, headers=intake)
        validate_error(response, ApiErrorId.ERR_REFERRAL_SOURCE_BREACHED)

        assert (
            fixtures.read_referral(api, referral["id"])["status"]
            == ReferralStatus.CRITERIA_MET
        )

    def test_the_same_admit_succeeds_with_a_non_empty_override_reason(
        self, api, intake
    ):
        """A justified admit from the same breached source is accepted and flagged.

        Nothing about the source changes between the refusal and this call — only the
        justification is added. The admission proceeds and records the exception on the
        stay itself: `admitted_with_override` true and the supplied text stored verbatim in
        `override_reason`, so an auditor can find every admission taken against a breached
        referral source. The override waives the mix ceiling, not the counting: the stay
        still counts toward the admission threshold.

        PRD 2.8: "When the referral's `ReferringHospital` has `monitoring_state` `BREACHED`, the admit request must carry a non-empty `override_reason`; without it the admission is refused with `ERR_REFERRAL_SOURCE_BREACHED` (422)."
        PRD 3.3: "Supplying one lets the admission proceed, records `admitted_with_override` as true on the resulting stay and stores the justification in `override_reason`; admissions that did not need an override carry `admitted_with_override` false and `override_reason` null."

        Design: Corner/validations/a_breached_referral_source_admits_only_with_an_override_reason
        """
        world, rural, referral = _breached_source_world(api)

        refused = api.admit_referral(referral["id"], {}, headers=intake)
        validate_error(refused, ApiErrorId.ERR_REFERRAL_SOURCE_BREACHED)

        response = api.admit_referral(
            referral["id"],
            factories.admit_payload(override_reason=_OVERRIDE_REASON),
            headers=intake,
        )
        stay = validate_success(response, expected_status=201)

        assert stay["admitted_with_override"] is True
        assert stay["override_reason"] == _OVERRIDE_REASON
        assert stay["counts_toward_admission_threshold"] is True
        assert_stay_dimensions(
            stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )

    def test_an_empty_override_reason_is_rejected_exactly_like_the_absent_field(
        self, api, intake
    ):
        """`override_reason` of `""` does not satisfy the rule, which demands a non-empty one.

        The field is present but carries no justification, which is the same audit position
        as omitting it: nobody has explained why a breached source was used. The rule is
        written as a demand for a *non-empty* reason, so the empty string is refused with
        the same `ERR_REFERRAL_SOURCE_BREACHED`, and the referral is left untouched in
        `CRITERIA_MET` for a genuine justification to be supplied later.

        PRD 2.8: "When the referral's `ReferringHospital` has `monitoring_state` `BREACHED`, the admit request must carry a non-empty `override_reason`; without it the admission is refused with `ERR_REFERRAL_SOURCE_BREACHED` (422)."

        Design: Corner/validations/a_breached_referral_source_admits_only_with_an_override_reason
        """
        world, rural, referral = _breached_source_world(api)

        response = api.admit_referral(
            referral["id"], {"override_reason": ""}, headers=intake
        )
        validate_error(response, ApiErrorId.ERR_REFERRAL_SOURCE_BREACHED)

        after = fixtures.read_referral(api, referral["id"])
        assert after["status"] == ReferralStatus.CRITERIA_MET
        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 4)


def _priced_but_unfinalized_stay(api):
    """A stay discharged on 2026-08-15 whose determination is still `DRAFT`.

    Fourteen covered days against a 25-day short-stay threshold make the reduced standard
    base the binding one, so the draft prices at 1,512,000 cents: 120 percent of the
    IPPS-comparable per diem for the days delivered, the smallest of the three candidates.
    """
    admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
    fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
    return fixtures.discharged_stay(
        api, admission=admission, estimated_cost_cents=1000000, file_notes=False
    )


class TestPeriodCloseGatesCascade:
    """The close runs its two gates in order and never reaches the second early."""

    def test_an_outstanding_draft_determination_blocks_the_close_before_any_ledger_check(
        self, api, officer
    ):
        """A `DRAFT` determination in the period refuses the close on the first gate.

        The discharge cascade left one determination in `DRAFT`, which means the period's
        total is provisional: an unfinished pricing could still change. That is the first of
        the two gates the close evaluates, so it answers
        `ERR_PERIOD_HAS_DRAFT_DETERMINATIONS` and the ledger comparison behind it is never
        reached. The refusal must leave the period exactly as it was, `OPEN` with a null
        `closed_at`, and the determination still in `DRAFT`.

        PRD 3.9: "First, no stay in the period may still hold a `PaymentDetermination` in `status` `DRAFT`; an unfinished pricing means the period's total is provisional, and the close is refused with `ERR_PERIOD_HAS_DRAFT_DETERMINATIONS`."
        PRD 2.7: "A period's `status` is `OPEN` while it accrues admissions and payments and `CLOSED` once an operator closes it; `closed_at` records the logical instant of the close and is null while the period is `OPEN`."

        Design: Corner/validations/period_close_reports_the_draft_determination_before_the_ledger
        """
        admission = _priced_but_unfinalized_stay(api)
        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["status"] == DeterminationStatus.DRAFT
        assert_cents(determination, "total_payment_cents", 1512000)

        response = api.close_period(admission.world.period_id, headers=officer)
        validate_error(response, ApiErrorId.ERR_PERIOD_HAS_DRAFT_DETERMINATIONS)

        period = fixtures.read_period(api, admission.world.period_id)
        assert period["status"] == PeriodStatus.OPEN
        assert_unset(period, "closed_at")
        assert_period_ledger(period, 0, 0)
        assert (
            fixtures.read_determination(api, determination["id"])["status"]
            == DeterminationStatus.DRAFT
        )

    def test_once_the_determination_is_final_the_ledger_gate_passes_and_the_close_lands(
        self, api, officer
    ):
        """Resolving the review and finalizing the determination unblocks the same close.

        The review is cleared and the draft is accepted, which moves the determination to
        `FINAL` and, as a side effect of that acceptance, adds its 1,512,000 cents to the
        period's ledger and its one determination to the count. The identical close request
        now passes the first gate and reaches the second, where the incrementally
        maintained ledger is compared against a full recomputation — and matches, which is
        what proves the earlier refusal came from the draft gate rather than from drift.

        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."
        PRD 3.9: "Second, the incrementally maintained ledger must equal a full recomputation: the period's `total_payment_cents` must equal the sum of the `total_payment_cents` of every determination whose `status` is `FINAL` and whose stay belongs to this period, and its `final_determination_count` must equal the count of those same determinations."
        PRD 3.9: "On a successful close the period moves `OPEN → CLOSED`, `closed_at` is stamped from the logical clock, and `share_pct`, `threshold_pct` and `monitoring_state` are recomputed one final time for every referring hospital so that the closed period's admission mix is frozen at its audited values."

        Design: Corner/validations/period_close_reports_the_draft_determination_before_the_ledger
        """
        admission = _priced_but_unfinalized_stay(api)
        refused = api.close_period(admission.world.period_id, headers=officer)
        validate_error(refused, ApiErrorId.ERR_PERIOD_HAS_DRAFT_DETERMINATIONS)

        resolved = fixtures.resolve_review(
            api,
            admission.review["id"],
            outcome=ReviewOutcome.CLEARED,
            resolution_note="Documented short-stay outlier; no denial exposure.",
        )
        assert resolved["status"] == ReviewStatus.CLEARED

        final = fixtures.finalize(
            api, fixtures.sole_determination(api, admission.stay_id)["id"]
        )
        assert final["status"] == DeterminationStatus.FINAL

        closed = validate_success(
            api.close_period(admission.world.period_id, headers=officer)
        )
        assert closed["status"] == PeriodStatus.CLOSED
        assert_period_ledger(closed, 1512000, 1)
        assert_instant_equals(
            closed["closed_at"], "2026-08-15T00:00:00Z", "closed_at"
        )
        assert (
            fixtures.read_stay(api, admission.stay_id)["payment_review_status"]
            == PaymentReviewStatus.FINALIZED
        )


def _world_with_a_future_criteria_set(api):
    """A world whose only criteria set is `ACTIVE` but not yet in force."""
    return fixtures.build_world(
        api, criteria_set={"label": "CS-2026B", "effective_from": "2026-09-01"}
    )


class TestScreeningBeforeTheCriteriaSetTakesEffect:
    """An `ACTIVE` criteria set dated in the future is not yet a candidate."""

    def test_screening_against_a_set_dated_in_the_future_is_refused(self, api, intake):
        """A set effective 2026-09-01 cannot be pinned by a screen run on 2026-08-01.

        The set exists and its `status` is `ACTIVE`, but existence is not sufficient — the
        candidate list also demands an `effective_from` on or before the current logical
        date, and 2026-09-01 is a month past the clock. With no candidates the screen is
        refused and, crucially, pins nothing: the referral stays in `RECEIVED` with a null
        `pinned_criteria_set_id` and a screened count still at zero, so the refused attempt
        did not consume the evaluation.

        PRD 2.8: "At least one `AdmissionCriteriaSet` has `status` `ACTIVE` and an `effective_from` on or before the current logical date, else `ERR_NO_EFFECTIVE_CRITERIA_SET` (422)."
        PRD 3.2: "If there are no candidates at all, screening is refused with `ERR_NO_EFFECTIVE_CRITERIA_SET` and nothing is pinned."
        PRD 3.2: "Every screening evaluation, whatever its verdict, increases `screened_count` by 1."

        Design: Corner/validations/screen_before_the_criteria_set_takes_effect_is_refused
        """
        world = _world_with_a_future_criteria_set(api)
        assert world.criteria_set["status"] == CriteriaSetStatus.ACTIVE
        referral = fixtures.create_referral(api, world, clinicals=CLINICALS_JULY_31)
        assert referral["status"] == ReferralStatus.RECEIVED
        assert_unset(referral, "pinned_criteria_set_id")

        response = api.screen_referral(referral["id"], headers=intake)
        validate_error(response, ApiErrorId.ERR_NO_EFFECTIVE_CRITERIA_SET)

        after = fixtures.read_referral(api, referral["id"])
        assert after["status"] == ReferralStatus.RECEIVED
        assert_integer_field(after, "screened_count", 0)
        assert_unset(after, "pinned_criteria_set_id")
        # PRD 3.2: "A newly created referral enters `RECEIVED` with `qualifying_track`
        # `NONE`" — the refused screen resolved no track, so the creation value stands.
        assert after["qualifying_track"] == QualifyingTrack.NONE

    def test_the_same_screen_succeeds_on_the_effective_date_itself(self, api, intake):
        """On 2026-09-01 exactly, the set becomes a candidate and is pinned.

        The candidate test is written as on-or-before, so the effective date is inclusive: a
        clock reading of exactly 2026-09-01T00:00:00Z admits the set. Nothing else about the
        referral changes, so the identical screen now selects that one set, writes its id to
        `pinned_criteria_set_id` and reaches a verdict — 240 ventilator hours against a
        96-hour minimum and 5 ICU days against a 3-day minimum both clear, so the referral
        qualifies on the prolonged-mechanical-ventilation track.

        PRD 3.2: "The candidates are every `AdmissionCriteriaSet` whose `status` is `ACTIVE` and whose `effective_from` falls on or before the current logical calendar date."
        PRD 3.2: "The prolonged-mechanical-ventilation criterion is met when `vent_hours_at_referral` is at least the pinned set's `pmv_min_vent_hours` **and** `icu_days_at_referral` is at least its `pmv_min_icu_days`."

        Design: Corner/validations/screen_before_the_criteria_set_takes_effect_is_refused
        """
        world = _world_with_a_future_criteria_set(api)
        referral = fixtures.create_referral(api, world, clinicals=CLINICALS_JULY_31)
        validate_error(
            api.screen_referral(referral["id"], headers=intake),
            ApiErrorId.ERR_NO_EFFECTIVE_CRITERIA_SET,
        )

        fixtures.advance_clock(api, "2026-09-01T00:00:00Z")
        screened = fixtures.screen_referral(api, referral["id"])

        assert screened["status"] == ReferralStatus.CRITERIA_MET
        assert screened["qualifying_track"] == QualifyingTrack.PMV
        assert screened["pinned_criteria_set_id"] == world.criteria_set_id
        assert_integer_field(screened, "screened_count", 1)


class TestAdmittedAtOutsideItsLegalWindow:
    """One rule, two bounds, and a distinct error id for each."""

    @pytest.mark.parametrize(
        "admitted_at, error_id",
        [
            ("2026-07-30T00:00:00Z", ApiErrorId.ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE),
            ("2026-08-02T00:00:00Z", ApiErrorId.ERR_ADMISSION_IN_FUTURE),
        ],
        ids=["a_day_before_the_acute_discharge", "a_day_past_the_logical_clock"],
    )
    def test_an_admitted_at_past_either_bound_is_refused_with_its_own_error(
        self, api, intake, admitted_at, error_id
    ):
        """One day early names the acute discharge; one day late names the future.

        The referral records a prior acute discharge at 2026-07-31T00:00:00Z and the clock
        reads 2026-08-01T00:00:00Z, so the legal window for `admitted_at` is exactly those
        two instants and everything between them. An instant one day below the window
        crosses the lower bound and one day above it crosses the upper, and the single rule
        that owns both bounds reports a different error for each — the wall clock is
        irrelevant, only the logical instant counts. Neither refusal may leave a trace: the
        referral stays `CRITERIA_MET` and the patient still has no stay.

        PRD 2.8: "`admitted_at`, whether supplied or defaulted from the logical clock, must be greater than or equal to the referral's `prior_acute_discharge_at`, else `ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE` (422); and must not be after the current logical instant, else `ERR_ADMISSION_IN_FUTURE` (422)."
        PRD 3.3: "`admitted_at` must be on or after the referral's `prior_acute_discharge_at` — an LTCH stay cannot begin before the acute discharge that feeds it — and must not be after the current logical instant."

        Design: Corner/validations/admitted_at_outside_its_legal_window_is_refused_at_both_ends
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world, clinicals=CLINICALS_JULY_31)

        response = api.admit_referral(
            referral["id"],
            factories.admit_payload(admitted_at=admitted_at),
            headers=intake,
        )
        validate_error(response, error_id)

        assert (
            fixtures.read_referral(api, referral["id"])["status"]
            == ReferralStatus.CRITERIA_MET
        )
        stays, meta = _stays_of_patient(api, world.patient_id, intake)
        assert stays == []
        assert meta["total_count"] == 0

    def test_the_default_admit_lands_on_the_clock_instant_after_both_refusals(
        self, api, intake
    ):
        """With `admitted_at` omitted the admission takes the clock reading and succeeds.

        Both bounds are crossed in turn and then the field is simply left out, which is the
        proof that the referral itself was never the problem. The default is the current
        logical instant, 2026-08-01T00:00:00Z, which sits inside the window by construction:
        equal to the upper bound and one day above the lower.

        PRD 3.3: "`admitted_at` supplies the admission instant as an ISO 8601 UTC value with three fractional digits; when omitted it defaults to the current logical instant, and when supplied it may be backdated to record a late data entry."

        Design: Corner/validations/admitted_at_outside_its_legal_window_is_refused_at_both_ends
        """
        world = fixtures.build_world(api)
        referral = fixtures.qualified_referral(api, world, clinicals=CLINICALS_JULY_31)

        validate_error(
            api.admit_referral(
                referral["id"],
                factories.admit_payload(admitted_at="2026-07-30T00:00:00Z"),
                headers=intake,
            ),
            ApiErrorId.ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE,
        )
        validate_error(
            api.admit_referral(
                referral["id"],
                factories.admit_payload(admitted_at="2026-08-02T00:00:00Z"),
                headers=intake,
            ),
            ApiErrorId.ERR_ADMISSION_IN_FUTURE,
        )

        stay = validate_success(
            api.admit_referral(referral["id"], {}, headers=intake), expected_status=201
        )
        assert_instant_equals(stay["admitted_at"], CLOCK_EPOCH, "admitted_at")
        assert_stay_dimensions(
            stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )


class TestBackdatedInterruptionInstant:
    """`left_at` is the only route to the interruption-instant rule, and it has two bounds."""

    @pytest.mark.parametrize(
        "left_at, error_id",
        [
            ("2026-07-31T12:00:00Z", ApiErrorId.ERR_INTERRUPTION_BEFORE_ADMISSION),
            ("2026-08-02T00:00:00Z", ApiErrorId.ERR_ADMISSION_IN_FUTURE),
        ],
        ids=["twelve_hours_before_the_admission", "one_day_past_the_logical_clock"],
    )
    def test_a_left_at_outside_the_stay_window_is_refused_and_records_nothing(
        self, api, nurse, left_at, error_id
    ):
        """A `left_at` before `admitted_at` or after the clock creates no event.

        The stay was admitted at 2026-08-01T00:00:00Z and the clock still reads that
        instant, so a departure twelve hours earlier would precede the admission it belongs
        to, and one a day later would be recorded before it happened. The rule bounds
        `left_at` from below by the stay's `admitted_at` and from above by the current
        logical instant, naming a different error for each side. Because a refused
        interruption must not consume one of the stay's three slots, the stay is re-read to
        confirm it holds no events at all and is still `ADMITTED`.

        PRD 2.8: "`left_at`, whether supplied or defaulted, must be greater than or equal to the stay's `admitted_at` and, when the stay has been resumed, greater than or equal to its `resumed_at`, else `ERR_INTERRUPTION_BEFORE_ADMISSION` (422); it must also not be after the current logical instant, in which case `ERR_ADMISSION_IN_FUTURE` (422) is returned."
        PRD 3.5: "When `left_at` is omitted it defaults to the current logical instant; when supplied it may be backdated to record an interruption discovered late, but it must be on or after the stay's `admitted_at` and, for a stay that has been resumed by recombination, on or after its `resumed_at`, and it must not be after the current logical instant."

        Design: Corner/validations/a_backdated_interruption_before_the_admission_is_refused
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        assert_instant_equals(admission.stay["admitted_at"], CLOCK_EPOCH, "admitted_at")

        response = api.interrupt_stay(
            admission.stay_id,
            factories.interrupt_payload(
                destination=InterruptionDestination.ACUTE_CARE, left_at=left_at
            ),
            headers=nurse,
        )
        validate_error(response, error_id)

        events, meta = validate_paginated(
            api.list_interruptions(admission.stay_id, headers=nurse)
        )
        assert events == [], "the refused interruption was recorded: {}".format(events)
        assert meta["total_count"] == 0
        after = fixtures.read_stay(api, admission.stay_id)
        assert after["clinical_status"] == ClinicalStatus.ADMITTED
        assert_integer_field(after, "interruption_count", 0)

    def test_omitting_left_at_defaults_it_to_the_clock_and_opens_the_interruption(
        self, api, nurse
    ):
        """With `left_at` left out the departure is stamped at 2026-08-01T00:00:00Z.

        The same stay that refused both out-of-window instants accepts the request that
        supplies none, because the default is the current logical instant and that instant
        equals the stay's `admitted_at` — inside the window at its lower edge. The event
        opens with its return, day count and window verdict all still unknown, and the stay
        moves out of `ADMITTED` into `INTERRUPTED`.

        PRD 3.5: "A `UtilizationReviewNurse` records the departure, moving the stay `ADMITTED → INTERRUPTED` and creating an `InterruptionEvent` carrying that `stay_id`."
        PRD 3.5: "The new event enters `status` `OPEN` with `returned_at`, `interruption_days` and `within_window` all null, and the stay's `interruption_count` increases by 1."
        PRD 3.5: "The destination sets the event's `window_days` directly: 9 days for `ACUTE_CARE`, 27 days for both `IRF` and `SNF`, and 3 days for `HOME`."

        Design: Corner/validations/a_backdated_interruption_before_the_admission_is_refused
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        validate_error(
            api.interrupt_stay(
                admission.stay_id,
                factories.interrupt_payload(
                    destination=InterruptionDestination.ACUTE_CARE,
                    left_at="2026-07-31T12:00:00Z",
                ),
                headers=nurse,
            ),
            ApiErrorId.ERR_INTERRUPTION_BEFORE_ADMISSION,
        )

        event = fixtures.interrupt(
            api,
            admission.stay_id,
            destination=InterruptionDestination.ACUTE_CARE,
        )
        assert event["status"] == InterruptionStatus.OPEN
        assert_instant_equals(event["left_at"], CLOCK_EPOCH, "left_at")
        assert_integer_field(event, "window_days", 9)
        assert_unset(event, "returned_at", "interruption_days", "within_window")

        after = fixtures.read_stay(api, admission.stay_id)
        assert after["clinical_status"] == ClinicalStatus.INTERRUPTED
        assert_integer_field(after, "interruption_count", 1)


def _parent_and_child_four_days_apart(api):
    """One patient, two stays, with four whole days between the discharge and the readmit.

    The parent runs 2026-08-01 to 2026-08-05 and the child is admitted 2026-08-09. The
    second referral is created against the patient's re-read `version`, because the first
    referral and admission already moved it.
    """
    world = fixtures.build_world(api)
    parent_admission = fixtures.admitted_stay(api, world, clinicals=CLINICALS_JULY_31)
    fixtures.advance_clock(api, "2026-08-05T00:00:00Z")
    parent = fixtures.discharge(
        api, parent_admission.stay_id, estimated_cost_cents=1000000
    )

    patient = fixtures.read_patient(api, world.patient_id)
    child_referral = fixtures.qualified_referral(
        api,
        world,
        clinicals=dict(
            factories.PMV_CLINICALS, prior_acute_discharge_at="2026-08-05T00:00:00Z"
        ),
        patient_version=patient["version"],
    )
    fixtures.advance_clock(api, "2026-08-09T00:00:00Z")
    child = fixtures.admit(api, child_referral["id"])
    return world, parent, child


class TestRecombinationFourDaysAfterTheParentDischarge:
    """Three whole days folds; four does not."""

    def test_a_four_day_gap_is_refused_and_the_child_keeps_its_own_identity(
        self, api, officer
    ):
        """A readmission four whole days after the discharge cannot be folded back.

        The parent was discharged on 2026-08-05 and the child admitted on 2026-08-09. Whole
        days are counted as the difference of the two UTC calendar dates, which is four —
        one past the three-day window, where the boundary itself would still be accepted. The
        fold is therefore refused, and because it is the child that the operation mutates
        first, the child is re-read to prove it was not touched: still `ADMITTED`, still
        counting toward the admission threshold, and still parentless.

        PRD 2.8: "`interrupted_parent_stay_id` must reference a *different* stay of the *same* patient whose `clinical_status` is `DISCHARGED` and whose `discharged_at` is no more than 3 whole days before the child stay's `admitted_at`; otherwise `ERR_RECOMBINATION_WINDOW_EXCEEDED` (422)."
        PRD 2.5: "The day count between two instants is the difference between their UTC *calendar dates*, expressed in whole days; the later day is not itself counted."
        PRD 3.5: "The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."

        Design: Corner/validations/recombination_four_days_after_the_parent_discharge_is_refused
        """
        world, parent, child = _parent_and_child_four_days_apart(api)
        assert_instant_equals(
            parent["discharged_at"], "2026-08-05T00:00:00Z", "discharged_at"
        )
        assert_integer_field(parent, "covered_los_days", 4)
        assert_instant_equals(child["admitted_at"], "2026-08-09T00:00:00Z", "admitted_at")
        assert day_count("2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z") == 4

        response = api.recombine_stay(
            child["id"],
            factories.recombine_payload(parent["id"]),
            headers=officer,
        )
        validate_error(response, ApiErrorId.ERR_RECOMBINATION_WINDOW_EXCEEDED)

        after_child = fixtures.read_stay(api, child["id"])
        assert after_child["clinical_status"] == ClinicalStatus.ADMITTED
        assert after_child["counts_toward_admission_threshold"] is True
        assert_unset(after_child, "interrupted_parent_stay_id")

    def test_the_refused_fold_leaves_the_parent_discharged_and_carrying_no_days(
        self, api, officer
    ):
        """The parent absorbs nothing: still `DISCHARGED`, `carried_los_days` still 0.

        A successful fold would clear the parent's `discharged_at` and freeze its
        pre-recombination days into `carried_los_days`. Neither may happen here, so the
        parent must still read `DISCHARGED` with a zero carry, and a listing filtered on the
        parent as a recombination target must come back empty because no child names it.

        PRD 3.5: "Its `carried_los_days` is frozen at the whole-day count from its `admitted_at` to its `discharged_at` — the covered days already banked from the pre-recombination segment — its `resumed_at` is stamped with the child's `admitted_at`, and both its `discharged_at` and its `discharge_disposition` are cleared to null."

        Design: Corner/validations/recombination_four_days_after_the_parent_discharge_is_refused
        """
        world, parent, child = _parent_and_child_four_days_apart(api)
        validate_error(
            api.recombine_stay(
                child["id"],
                factories.recombine_payload(parent["id"]),
                headers=officer,
            ),
            ApiErrorId.ERR_RECOMBINATION_WINDOW_EXCEEDED,
        )

        after_parent = fixtures.read_stay(api, parent["id"])
        assert after_parent["clinical_status"] == ClinicalStatus.DISCHARGED
        assert_integer_field(after_parent, "carried_los_days", 0)
        assert_instant_equals(
            after_parent["discharged_at"], "2026-08-05T00:00:00Z", "discharged_at"
        )
        assert_unset(after_parent, "resumed_at")

        children, meta = validate_paginated(
            api.list_stays(
                params={"interrupted_parent_stay_id": parent["id"]}, headers=officer
            )
        )
        assert children == [], "a child was folded into the parent: {}".format(children)
        assert meta["total_count"] == 0


class TestSecondWeaningPlanOnTheSameStay:
    """One stay, one weaning plan, for the whole life of the stay."""

    def test_a_second_weaning_plan_is_refused_and_the_first_is_left_untouched(
        self, api, nurse
    ):
        """A second create returns `ERR_WEANING_PLAN_EXISTS` even with a different payload.

        The first plan opened as `STANDARD_SBT` seeded with 12 ventilator hours. The second
        request asks for a different protocol and a far larger seed, which is exactly the
        request that would be dangerous if it were treated as an update: the ventilator-hour
        counter drives the payment variant. The rule is one plan per stay, so the request is
        refused outright, the stored plan keeps both of its original values, and the stay
        still holds exactly one plan.

        PRD 3.4: "A `UtilizationReviewNurse` opens at most one ventilator weaning plan per stay; a second attempt on the same stay is refused with `ERR_WEANING_PLAN_EXISTS`."
        PRD 3.4: "Two optional inputs are accepted: `protocol_label`, a 1-to-40-character protocol identifier that defaults to `STANDARD_SBT`, and `vent_hours_total`, which seeds the plan's cumulative ventilator-hour counter and defaults to 0."

        Design: Corner/validations/a_second_weaning_plan_on_the_same_stay_is_refused
        """
        admission = fixtures.admitted_stay(api, clinicals=CLINICALS_JULY_31)
        plan = fixtures.open_weaning_plan(
            api, admission.stay_id, protocol_label="STANDARD_SBT", vent_hours_total=12
        )
        assert plan["protocol_label"] == "STANDARD_SBT"
        assert_vent_hours(plan, "vent_hours_total", 12)

        response = api.create_weaning_plan(
            admission.stay_id,
            factories.weaning_plan_payload(
                protocol_label="ACCELERATED_SBT", vent_hours_total=200
            ),
            headers=nurse,
        )
        validate_error(response, ApiErrorId.ERR_WEANING_PLAN_EXISTS)

        after = fixtures.read_plan(api, plan["id"])
        assert after["protocol_label"] == "STANDARD_SBT"
        assert_vent_hours(after, "vent_hours_total", 12)
        assert after["status"] == WeaningPlanStatus.SBT_TRIAL

        plans, meta = validate_paginated(
            api.list_weaning_plans(
                params={"stay_id": admission.stay_id}, headers=nurse
            )
        )
        assert len(plans) == 1, "expected one plan on the stay, found {}".format(
            len(plans)
        )
        assert meta["total_count"] == 1
        assert plans[0]["id"] == plan["id"]
