"""Breadth tests: readiness channel arithmetic, counseling cadence and the
look-back discount."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    setup_approvable_carry_patient,
    ensure_counseling_current,
    register_patient,
    hold_privilege,
    evaluate_privilege,
    schedule_dose,
    attend_counseling,
    set_clock,
    validate_success,
    validate_error,
    ApiErrorId,
)


class TestJournalLookbackDiscount:
    """Only entries inside the trailing journal window are discounted."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=10, with_counselor=True)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        # The two journal entries are dated *after* the advanced clock rather than
        # before it. PRD 3.5 sweeps any dose left `SCHEDULED` past its own
        # `dose_date` to `MISSED` on the next request, and `MISSED` is terminal,
        # so a row dated 2026-12-01 or 2026-12-10 would be swept and could never
        # be cancelled. Dating them on open days beyond the clock keeps them
        # cancellable while their `created_at` still lands inside the trailing
        # 28-day journal window.
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "STABILIZATION", "reconciled_days": 1},
            clinic["physician_headers"]))
        for date in ("2026-12-16", "2026-12-17"):
            dose = schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                 inventory_lot_id=clinic["lot"]["id"])
            validate_success(api_client.cancel_dose(dose["id"], clinic["nurse_headers"]))
        # Bring the counseling standing to CURRENT so the discount is the only
        # readiness penalty in play (PRD 3.8). The review and the session both
        # bump the patient's version, so the version the privilege request must
        # cite (PRD 2.10) is read only after they are recorded.
        validate_success(api_client.create_plan_review({
            "patient_id": patient["id"], "reviewer_physician_id": clinic["physician"]["id"],
            "reviewed_at": "2026-12-15T00:00:00Z", "signed_off": True},
            clinic["physician_headers"]), 201)
        # A completed session's `completed_at` is stamped from the logical clock
        # (PRD 3.8), so the clock is stepped back for the completion and
        # restored. Landing it 29 whole days before the evaluation clock puts
        # the session inside the 30-day MAINTENANCE cadence window that PRD 3.8
        # reads for the standing while sitting one day outside the trailing
        # 28-day window PRD 2.5 reads for Direction A's one-point-per-session
        # credit — otherwise the published figure the assertions pin would pick
        # up a stray point.
        set_clock("2026-11-16T00:00:00Z")
        attend_counseling(clinic, patient["id"], 60, "2026-11-16T09:00:00Z")
        set_clock("2026-12-15T00:00:00Z")
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv = hold_privilege(clinic, patient["id"], current["version"], requested_carries=2)
        return clinic, patient, order, priv, current

    def test_the_two_window_entries_discount_two_point_zero_and_one_point_five(self):
        """PRD 2.5: "The channel then applies a journal look-back discount over
        the patient's dose journal window, removing exactly two entries from the
        regulation journal window when both are present: the entry whose
        `created_at` is earliest in the window costs two points, and the entry
        whose `created_at` is latest costs one and a half points."
        PRD 2.5: "It starts from a base of 50.0 and credits the patient for time
        in treatment."

        Design: Corner/calculations/readiness_journal_lookback_discount_removes_two_entries
        """
        clinic, patient, order, priv, current = self._setup()
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["time_in_treatment_days"] == 105
        assert read["stability_score"] == pytest.approx(75.0, abs=0.05)

        priv_after = validate_success(api_client.get_privilege(priv["id"],
                                                               clinic["director_headers"]))
        assert priv_after["timetable_reconciled"] is True

    def test_the_discounted_reading_falls_below_the_stabilization_floor(self):
        """PRD 2.5: "the readiness reading must be at least 70.0 when the
        patient's `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every
        other phase."
        PRD 3.6: "The privilege's `timetable_reconciled` must be true, else
        `ERR_TIMETABLE_LOOKAHEAD_FAILED` (HTTP 422)."
        PRD 3.6: "The denial branch fires when at least one of those approval
        conditions fails."

        Design: Corner/calculations/readiness_journal_lookback_discount_removes_two_entries
        """
        clinic, patient, order, priv, current = self._setup()
        validate_error(evaluate_privilege(clinic, priv["id"]),
                       ApiErrorId.ERR_STABILITY_BELOW_THRESHOLD.value)
        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "DENIED"
        assert after["denial_reason_code"] == "STABILITY_BELOW_THRESHOLD"


class TestLookbackSkippedWhenWindowEmpty:
    """With no journal entries the discount is not applied at all."""

    def test_an_empty_window_keeps_the_reading_and_clears_the_floor(self):
        """PRD 2.5: "When the window holds fewer than two entries, only the
        entries actually present are discounted, taken in that order."
        PRD 2.5: "the readiness reading must be at least 70.0 when the patient's
        `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every other
        phase."
        PRD 3.6: "When every condition holds, the evaluation computes the grant
        size through the carry waterfall, records `evaluation_basis` as
        `TIME_IN_TREATMENT`."

        Design: Corner/calculations/readiness_discount_skips_when_the_window_is_empty
        """
        # 100 days at the clock gives a Direction A reading of 75.0 from the
        # capped treatment-days term alone, which meets the MAINTENANCE floor
        # once the look-back discount is skipped for want of journal entries.
        # The fixture's counseling session is completed 29 days back, inside the
        # 30-day cadence window that makes the standing CURRENT while sitting
        # outside Direction A's trailing 28-day window, so it contributes no
        # one-point-per-session credit and the published reading stays 75.0.
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(
            clinic, clock="2026-12-10T00:00:00Z", ordered_daily_mg=90.0)

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["time_in_treatment_days"] == 100
        assert read["treatment_phase"] == "MAINTENANCE"
        assert read["stability_score"] == pytest.approx(75.0, abs=0.05)

        rows, _meta = _list_doses(clinic, patient["id"])
        assert rows == [], "the journal window must be empty for this scenario"

        priv = hold_privilege(clinic, patient["id"], read["version"], requested_carries=1)
        approved = validate_success(evaluate_privilege(clinic, priv["id"]))
        assert approved["decision"] == "APPROVED", (
            "with an empty window the 2.0 + 1.5 look-back discount is not subtracted")
        assert approved["approved_carries"] == 1
        assert approved["denial_reason_code"] is None


class TestInspectionReadinessScore:
    """The readiness read recomputes from live dossier state."""

    def test_weighted_penalties_land_on_the_expected_score_and_tier(self):
        """PRD 3.13: "The readiness score starts at 100.0 and is reduced by a
        series of weighted penalties. Each open `CRITICAL` finding costs 12.0
        points, each open `MAJOR` finding 6.0, and each open `MINOR` finding
        2.0. Each diversion case for the program in `OPEN` or `UNDER_REVIEW`
        status costs 10.0 points."
        PRD 3.13: "the `readiness_tier` is cut from it: `READY` at 85.0 or
        above, `NEEDS_ATTENTION` at 60.0 or above (and below 85.0), and
        `NOT_READY` below 60.0."

        Design: Corner/endpoints/compliance_inspection_readiness_computed_read_returns_the_weighted_score
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        # The readiness score is reduced by 20.0 for a program holding any
        # patient whose counseling standing is COUNSELING_DEFICIENT. Nothing in
        # this scenario asserts that term, so the patient present in the program
        # is carried on the roster only if it reads CURRENT — otherwise the
        # penalty silently composes with the finding and diversion terms.
        patient = register_patient(clinic)
        admission = patient["id"]
        validate_success(api_client.confirm_diagnosis(admission, clinic["physician_headers"]))
        set_clock("2026-12-15T00:00:00Z")
        ensure_counseling_current(clinic, admission, clock_iso="2026-12-15T00:00:00Z")

        inspection = validate_success(api_client.create_inspection({
            "program_id": clinic["program"]["id"],
            "inspecting_agency": "State Opioid Treatment Authority",
            "scheduled_date": "2026-12-20",
            "inspection_type": "DIVERSION_FOCUSED"}, clinic["auditor_headers"]), 201)
        validate_success(api_client.create_finding({
            "inspection_id": inspection["id"], "requirement_code": "WASTE_WITNESSED",
            "severity": "CRITICAL"}, clinic["auditor_headers"]), 201)
        validate_success(api_client.create_finding({
            "inspection_id": inspection["id"], "requirement_code": "COUNSELING_CADENCE_MET",
            "severity": "MAJOR"}, clinic["auditor_headers"]), 201)
        case = validate_success(api_client.create_diversion_case({
            "program_id": clinic["program"]["id"], "patient_id": patient["id"],
            "detection_source": "URINE_SCREEN", "severity": "MAJOR"},
            clinic["auditor_headers"]), 201)
        validate_success(api_client.begin_review(case["id"], clinic["auditor_headers"]))

        readiness = validate_success(api_client.get_readiness(inspection["id"],
                                                              clinic["auditor_headers"]))
        assert readiness["readiness_score"] == pytest.approx(72.0, abs=0.05)
        assert readiness["readiness_tier"] == "NEEDS_ATTENTION"
        assert readiness["open_critical_findings"] == 1
        assert readiness["open_diversion_cases"] == 1


def _list_doses(clinic, patient_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_dose_dispenses(
        clinic["director_headers"], {"patient_id": patient_id}))