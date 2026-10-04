"""Depth tests: the parallel standing dimensions that coexist on one Patient row."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    schedule_dose,
    mark_missed,
    create_diversion_case_payload,
    set_clock,
    validate_success,
)


class TestParallelStandingDimensions:
    """A diversion case moves one dimension while the clinical status stands still."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=10,
                              lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        doses = []
        for date in ("2026-09-02", "2026-09-03", "2026-09-04"):
            dose = schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                 inventory_lot_id=clinic["lot"]["id"])
            mark_missed(clinic, dose["id"])
            doses.append(dose)
        set_clock("2026-12-15T00:00:00Z")
        case = validate_success(api_client.create_diversion_case(
            create_diversion_case_payload(clinic["program"]["id"], patient["id"],
                                          related_dose_dispense_id=doses[2]["id"],
                                          detection_source="COUNT_MISMATCH", severity="MAJOR"),
            clinic["auditor_headers"]), 201)
        return clinic, patient, order, doses, case

    def test_the_clinical_suspension_and_the_parallel_standings_coexist(self):
        """PRD 3.5: "When the recomputed `missed_dose_streak` reaches 3 or more,
        the patient's own transition to `SUSPENDED_NON_COMPLIANT` fires
        automatically."
        PRD 3.5: "The patient's `denial_count_12mo` is recomputed over the
        trailing 365 days at the logical clock, so the window slides rather than
        accumulating forever."
        PRD 3.2: "None of the three is a state of the patient's main `status`
        field; they are orthogonal readings that coexist with it."

        Design: Difficulty/non_linear_state_machine/patient_parallel_standing_dimensions_evolve_independently
        """
        clinic, patient, order, doses, case = self._setup()
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["status"] == "SUSPENDED_NON_COMPLIANT"
        assert read["missed_dose_streak"] == 3
        assert read["denial_count_12mo"] == 3
        # No phase change was ever recorded, so the phase dimension still sits
        # at its registration default.
        assert read["treatment_phase"] == "INDUCTION"
        # The diversion dimension has not yet been moved by a review.
        assert read["diversion_standing"] == "CLEAR"

    def test_beginning_review_moves_only_the_diversion_dimension(self):
        """PRD 3.10: "Beginning review moves the case to `UNDER_REVIEW` and sets
        the patient's `diversion_standing` to `UNDER_INVESTIGATION` — note this
        alone does not revoke anything, it merely warns the system and penalises
        the patient's readiness channel by ten points."
        PRD 3.2: "The `diversion_standing` dimension takes `CLEAR`,
        `UNDER_INVESTIGATION` or `CONFIRMED_DIVERSION`, defaults to `CLEAR`,
        and is driven by the disposition of diversion cases in §3.11."

        Design: Difficulty/non_linear_state_machine/patient_parallel_standing_dimensions_evolve_independently
        """
        clinic, patient, order, doses, case = self._setup()
        reviewed = validate_success(
            api_client.begin_review(case["id"], clinic["auditor_headers"]))
        assert reviewed["status"] == "UNDER_REVIEW"

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["diversion_standing"] == "UNDER_INVESTIGATION"
        # The diversion machine owns the standing dimension only.
        assert read["status"] == "SUSPENDED_NON_COMPLIANT"
        assert read["treatment_phase"] == "INDUCTION"