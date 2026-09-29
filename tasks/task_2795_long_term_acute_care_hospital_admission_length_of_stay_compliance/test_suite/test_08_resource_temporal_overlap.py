"""
Two contended resources whose intervals meet at a shared instant, under opposite conventions.

The patient is a resource occupied over a half-open interval, so a readmission whose
`admitted_at` falls exactly on the prior stay's `discharged_at` is adjacent and legal while
one a second earlier overlaps and is refused. The fiscal calendar is a resource occupied
over an interval that is inclusive at both ends, so a period beginning exactly on an
earlier period's `end_date` overlaps on that single day — and before overlap is even
reached, the one-open-period rule refuses a range that overlaps nothing at all.
"""

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    ClinicalStatus,
    PeriodStatus,
    ReferralStatus,
    assert_cents,
    assert_instant_equals,
    assert_integer_field,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

FIRST_ADMITTED_AT = "2026-07-01T00:00:00Z"
DISCHARGE_INSTANT = "2026-08-15T00:00:00Z"
ONE_SECOND_INSIDE = "2026-08-14T23:59:59Z"
FIRST_COVERED_LOS_DAYS = 45


def _patient_with_one_closed_occupancy(api):
    """A patient whose only stay ran [2026-07-01, 2026-08-15), plus a referral ready to admit.

    The first stay is backdated to 2026-07-01, which is what makes a genuine overlap
    reachable at all, and discharged once the clock reads 2026-08-15T00:00:00Z. A second
    referral for the same patient is then screened to `CRITERIA_MET` and left un-admitted,
    with the clock still at the discharge instant so that neither candidate `admitted_at`
    is future-dated.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world, admitted_at=FIRST_ADMITTED_AT)
    fixtures.advance_clock(api, DISCHARGE_INSTANT)
    discharged = fixtures.discharge(api, admission.stay_id)
    patient = fixtures.read_patient(api, world.patient_id)
    pending = fixtures.qualified_referral(
        api, world, patient_version=patient["version"]
    )
    return world, admission, discharged, pending


class TestPatientOccupancyAtTheDischargeInstant:
    """The patient's occupancy interval excludes its own closing instant."""

    def test_an_admission_one_second_before_the_prior_discharge_is_refused_as_an_overlap(
        self, api, intake
    ):
        """2026-08-14T23:59:59Z lies inside [2026-07-01T00:00:00Z, 2026-08-15T00:00:00Z).

        The first stay was admitted on 2026-07-01 and discharged when the clock read
        2026-08-15T00:00:00Z, so it covers 45 whole days and its occupancy runs up to but
        excludes that discharge instant. A candidate `admitted_at` one second earlier is
        therefore still inside the occupied interval and the admission is refused. Because
        a refused admission creates nothing, the period still reports the single admission
        the first stay contributed, the patient still has exactly one stay, and the second
        referral is left in `CRITERIA_MET` — still admissible.

        PRD 3.3: "A stay occupies the **half-open** interval that begins at its `admitted_at` and runs up to but does not include its `discharged_at`."
        PRD 3.3: "A new admission whose `admitted_at` is exactly equal to a prior stay's `discharged_at` is adjacent, not overlapping, and is allowed; an admission one second earlier than that instant overlaps and is refused with `ERR_PATIENT_STAY_OVERLAP`."
        PRD 3.6: "Since `carried_los_days` is 0 for any stay that was never reopened, and `interruption_days_total` sums `interruption_days` only over this stay's events whose `status` is `RETURNED` — open and expired events contribute nothing — a simple uninterrupted stay yields exactly the whole-day count from admission to discharge."

        Design: Difficulty/resource_temporal_overlap/patient_occupancy_is_half_open_at_the_discharge_instant
        """
        world, _admission, discharged, pending = _patient_with_one_closed_occupancy(api)

        assert_instant_equals(
            discharged["discharged_at"], DISCHARGE_INSTANT, "discharged_at"
        )
        assert_integer_field(discharged, "covered_los_days", FIRST_COVERED_LOS_DAYS)

        refused = api.admit_referral(
            pending["id"],
            factories.admit_payload(admitted_at=ONE_SECOND_INSIDE),
            headers=intake,
        )
        validate_error(refused, ApiErrorId.ERR_PATIENT_STAY_OVERLAP)

        still_admissible = fixtures.read_referral(api, pending["id"])
        assert still_admissible["status"] == ReferralStatus.CRITERIA_MET

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 1)

        stays, meta = validate_paginated(
            api.list_stays(params={"patient_id": world.patient_id}, headers=intake)
        )
        assert meta["total_count"] == 1
        assert len(stays) == 1

    def test_the_overlap_rule_only_becomes_the_operative_refusal_once_the_stay_is_discharged(
        self, api, intake
    ):
        """The same request names the concurrency rule first and the overlap rule after.

        One candidate `admitted_at`, 2026-08-14T23:59:59Z, is attempted twice against the
        same patient. While the first stay is still `ADMITTED` the no-concurrent-admission
        check outranks the occupancy check, so the refusal names that rule and carries its
        own status. After the stay is discharged that check no longer fires, and the very
        same request is refused by the occupancy rule instead — which is the proof that the
        second refusal is about the interval and not about a live stay.

        PRD 2.8: "The patient has no `Stay` whose `clinical_status` is `ADMITTED` or `INTERRUPTED`, else `ERR_PATIENT_ALREADY_ADMITTED` (409)."
        PRD 2.8: "The new stay's occupancy interval must not overlap any existing non-recombined stay of the same patient, else `ERR_PATIENT_STAY_OVERLAP` (422)."
        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."

        Design: Difficulty/resource_temporal_overlap/patient_occupancy_is_half_open_at_the_discharge_instant
        """
        world = fixtures.build_world(api)
        admission = fixtures.admitted_stay(api, world, admitted_at=FIRST_ADMITTED_AT)
        fixtures.advance_clock(api, DISCHARGE_INSTANT)
        patient = fixtures.read_patient(api, world.patient_id)
        pending = fixtures.qualified_referral(
            api, world, patient_version=patient["version"]
        )

        live = fixtures.read_stay(api, admission.stay_id)
        assert live["clinical_status"] == ClinicalStatus.ADMITTED

        while_live = api.admit_referral(
            pending["id"],
            factories.admit_payload(admitted_at=ONE_SECOND_INSIDE),
            headers=intake,
        )
        validate_error(while_live, ApiErrorId.ERR_PATIENT_ALREADY_ADMITTED)

        closed = fixtures.discharge(api, admission.stay_id)
        assert closed["clinical_status"] == ClinicalStatus.DISCHARGED

        after_discharge = api.admit_referral(
            pending["id"],
            factories.admit_payload(admitted_at=ONE_SECOND_INSIDE),
            headers=intake,
        )
        validate_error(after_discharge, ApiErrorId.ERR_PATIENT_STAY_OVERLAP)

        assert (
            fixtures.read_referral(api, pending["id"])["status"]
            == ReferralStatus.CRITERIA_MET
        )

    def test_an_admission_exactly_at_the_prior_discharge_instant_is_adjacent_and_allowed(
        self, api, intake
    ):
        """Retrying at 2026-08-15T00:00:00Z itself succeeds: the intervals only touch.

        The refusal one second earlier is retried at the discharge instant, which the
        prior stay's half-open interval does not include, so the two occupancies are merely
        adjacent and the admission is accepted. The new stay is an ordinary fresh
        admission, not a continuation: `carried_los_days` is 0 because adjacency is not
        recombination. The period's admission counter now reads 2 and the patient has two
        stays, so the failed attempt in between left no trace.

        PRD 3.3: "A new admission whose `admitted_at` is exactly equal to a prior stay's `discharged_at` is adjacent, not overlapping, and is allowed; an admission one second earlier than that instant overlaps and is refused with `ERR_PATIENT_STAY_OVERLAP`."
        PRD 3.3: "Its `carried_los_days` starts at 0, its `interruption_days_total` at 0, its `interruption_count` at 0, and its `interrupted_parent_stay_id`, `resumed_at`, `discharged_at`, `covered_los_days`, `sso_threshold_days`, `short_stay_outlier_applied` and `discharge_payment_pct` all start null."
        PRD 3.3: "The admission also does four things beyond the stay itself: the referral's `status` becomes `ADMITTED`, `Patient.open_referral_count` is recomputed to 0, the period's `total_admissions` is increased by 1, and the referring hospital's `admissions_in_period` is increased by 1."

        Design: Difficulty/resource_temporal_overlap/patient_occupancy_is_half_open_at_the_discharge_instant
        """
        world, _admission, _discharged, pending = _patient_with_one_closed_occupancy(api)

        refused = api.admit_referral(
            pending["id"],
            factories.admit_payload(admitted_at=ONE_SECOND_INSIDE),
            headers=intake,
        )
        validate_error(refused, ApiErrorId.ERR_PATIENT_STAY_OVERLAP)

        readmitted = fixtures.admit(
            api, pending["id"], admitted_at=DISCHARGE_INSTANT
        )
        assert readmitted["clinical_status"] == ClinicalStatus.ADMITTED
        assert_instant_equals(
            readmitted["admitted_at"], DISCHARGE_INSTANT, "admitted_at"
        )
        assert_integer_field(readmitted, "carried_los_days", 0)
        assert readmitted["interrupted_parent_stay_id"] is None

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 2)

        stays, meta = validate_paginated(
            api.list_stays(params={"patient_id": world.patient_id}, headers=intake)
        )
        assert meta["total_count"] == 2
        assert len(stays) == 2


AUGUST_PERIOD = {
    "period_label": "AUG2026",
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
}
NON_OVERLAPPING_PERIOD = {
    "period_label": "DEC2026",
    "start_date": "2026-12-01",
    "end_date": "2026-12-31",
}
TOUCHING_PERIOD = {
    "period_label": "SEP2026",
    "start_date": "2026-08-31",
    "end_date": "2026-11-30",
}
FOLLOWING_PERIOD = {
    "period_label": "SEP2026",
    "start_date": "2026-09-01",
    "end_date": "2026-11-30",
}


class TestTheFiscalCalendarAsAContendedResource:
    """Period ranges are inclusive at both ends, and only one may be open."""

    def test_a_second_period_is_refused_even_though_its_dates_overlap_nothing(
        self, api, officer
    ):
        """December 2026 collides with nothing on the calendar, and is still refused.

        AUG2026 covers 2026-08-01 through 2026-08-31 and is `OPEN`. The candidate covers
        2026-12-01 through 2026-12-31, four clear months later, so no day is claimed twice
        — the refusal comes from the other half of the same rule, that at most one period
        may be open at a time. AUG2026 is untouched by the attempt and remains the one open
        period.

        PRD 2.7: "At most one period may hold `status` `OPEN` at any moment, and periods may not overlap in calendar coverage."
        PRD 2.8: "`DrgRateEntry.drg_code`, `ReferringHospital.npi`, `Physician.npi`, `Patient.mrn`, `AdmissionCriteriaSet.label` and `CostReportingPeriod.period_label` are each unique; a new criteria set's `effective_from` must be strictly after the `effective_from` of every `ACTIVE` set; a new period's `start_date` through `end_date` range must not overlap an existing period and only one period may be `OPEN` at a time."

        Design: Difficulty/resource_temporal_overlap/cost_reporting_periods_may_not_overlap_or_be_open_together
        """
        august = fixtures.open_period(api, **AUGUST_PERIOD)
        assert august["status"] == PeriodStatus.OPEN
        assert august["closed_at"] is None

        refused = api.create_period(
            factories.period_payload(**NON_OVERLAPPING_PERIOD), headers=officer
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_KEY)

        unchanged = fixtures.read_period(api, august["id"])
        assert unchanged["status"] == PeriodStatus.OPEN
        assert unchanged["closed_at"] is None
        assert unchanged["version"] == august["version"]

    def test_a_range_starting_on_the_closed_periods_end_date_overlaps_on_that_single_day(
        self, api, officer
    ):
        """Closing AUG2026 removes the open-period obstacle and exposes the overlap one.

        The database holds no stays, determinations or notes, so AUG2026 closes at will;
        the close stamps `closed_at` from the logical clock, which no one has advanced, so
        it reads the epoch instant 2026-08-01T00:00:00Z. With nothing open, the candidate
        range 2026-08-31 through 2026-11-30 is now judged only on coverage — and because a
        period's dates are inclusive at both ends, its first day is the very day AUG2026's
        `end_date` claims. One shared day is an overlap, and being `CLOSED` does not release
        the calendar.

        PRD 2.7: "A period's `status` is `OPEN` while it accrues admissions and payments and `CLOSED` once an operator closes it; `closed_at` records the logical instant of the close and is null while the period is `OPEN`."
        PRD 2.7: "Every stay belongs to exactly one cost reporting period, recorded on the stay as `cost_reporting_period_id` and selected once, at admission, as the single period whose `status` is `OPEN` and whose `start_date` and `end_date` bracket the admission date inclusively."
        PRD 2.8: "`DrgRateEntry.drg_code`, `ReferringHospital.npi`, `Physician.npi`, `Patient.mrn`, `AdmissionCriteriaSet.label` and `CostReportingPeriod.period_label` are each unique; a new criteria set's `effective_from` must be strictly after the `effective_from` of every `ACTIVE` set; a new period's `start_date` through `end_date` range must not overlap an existing period and only one period may be `OPEN` at a time."

        Design: Difficulty/resource_temporal_overlap/cost_reporting_periods_may_not_overlap_or_be_open_together
        """
        august = fixtures.open_period(api, **AUGUST_PERIOD)
        closed = fixtures.close_period(api, august["id"])
        assert closed["status"] == PeriodStatus.CLOSED
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")

        refused = api.create_period(
            factories.period_payload(**TOUCHING_PERIOD), headers=officer
        )
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_KEY)

        still_closed = fixtures.read_period(api, august["id"])
        assert still_closed["status"] == PeriodStatus.CLOSED

    def test_a_range_starting_the_day_after_the_closed_period_opens_with_an_empty_ledger(
        self, api
    ):
        """Moving the start date one day later clears both halves of the rule.

        2026-09-01 is the first day AUG2026 does not claim, so the successor period shares
        no coverage with it and, with AUG2026 already `CLOSED`, it is also the only open
        period. It opens with the ledger every new period starts from — no admissions, no
        payments and no finalized determinations. Opening the successor is not a reopening:
        AUG2026 still reads `CLOSED`, because `CLOSED` is terminal.

        PRD 2.7: "A newly opened period begins with `total_admissions` 0, `total_payment_cents` 0 and `final_determination_count` 0."
        PRD 2.7: "At most one period may hold `status` `OPEN` at any moment, and periods may not overlap in calendar coverage."
        PRD 3.9: "`CLOSED` is terminal."

        Design: Difficulty/resource_temporal_overlap/cost_reporting_periods_may_not_overlap_or_be_open_together
        """
        august = fixtures.open_period(api, **AUGUST_PERIOD)
        fixtures.close_period(api, august["id"])

        september = fixtures.open_period(api, **FOLLOWING_PERIOD)
        assert september["status"] == PeriodStatus.OPEN
        assert september["start_date"] == FOLLOWING_PERIOD["start_date"]
        assert september["end_date"] == FOLLOWING_PERIOD["end_date"]
        assert september["closed_at"] is None
        assert_integer_field(september, "total_admissions", 0)
        assert_cents(september, "total_payment_cents", 0)
        assert_integer_field(september, "final_determination_count", 0)

        assert (
            fixtures.read_period(api, august["id"])["status"] == PeriodStatus.CLOSED
        )
