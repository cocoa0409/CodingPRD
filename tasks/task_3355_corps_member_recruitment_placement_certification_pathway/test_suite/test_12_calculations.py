"""Derived-value calculations: hour sums, fees, deadline bands and ratio clamps."""
import pytest

from test_helpers import validate_success

from test_helpers.fixtures import (
    COMPLETER,
    PLACEMENT_COORDINATOR,
    VERIFIER,
    complete_milestone,
    create_matched_placement,
    get_certification_milestone,
    get_district,
    get_member,
    milestones_by_type,
    record_practice_hours,
    set_clock,
    setup_member_scenario,
    start_milestone,
    verify_milestone,
)


class TestCertificationHoursVerified:
    def test_completed_alone_contributes_nothing(self, api):
        """PRD §3.5: "Verifying a milestone recomputes the member's `certification_hours_verified`, which sums the `required_hours` of every milestone of that member that is simultaneously `COMPLETED` and `VERIFIED`; a milestone that is complete but unverified contributes nothing"

        Design: Corner/calculations/certification_hours_verified_requires_completed_and_verified
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]

        start_milestone(milestone_id)
        completed = complete_milestone(milestone_id, COMPLETER)
        assert completed["required_hours"] == 60

        mid = get_member(member_id)
        assert mid["certification_hours_verified"] == 0, (
            "COMPLETED alone is not enough to contribute hours"
        )

        verify_milestone(milestone_id, "VERIFY", VERIFIER)
        after = get_member(member_id)
        assert after["certification_hours_verified"] == 60

    def test_rejected_milestone_contributes_zero(self, api):
        """PRD §3.5: "a milestone that is complete but unverified contributes nothing, and a rejected milestone contributes nothing even though its completion stands."

        Design: Corner/calculations/certification_hours_verified_excludes_rejected_milestones
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestones = milestones_by_type(member_id)

        practicum = milestones["PRACTICUM"]["id"]
        start_milestone(practicum)
        complete_milestone(practicum, COMPLETER)
        verify_milestone(practicum, "VERIFY", VERIFIER)

        coursework = milestones["COURSEWORK"]["id"]
        start_milestone(coursework)
        complete_milestone(coursework, COMPLETER)
        rejected = verify_milestone(coursework, "REJECT", VERIFIER)
        assert rejected["verification_status"] == "REJECTED"
        assert rejected["progress_status"] == "COMPLETED"

        member = get_member(member_id)
        assert member["certification_hours_verified"] == 120, (
            "the rejected 60-hour milestone contributes 0; the verified 120-hour one still counts"
        )


class TestCourseworkHoursCompleted:
    def test_practicum_never_moves_coursework_hours(self, api):
        """PRD §3.3: "a `PRACTICUM` milestone takes the pathway's `required_practice_hours`, a `COURSEWORK` or `ORIENTATION` milestone takes the pathway's `required_coursework_hours`, and an `EXAM` milestone is worth 0 hours."
        PRD §3.5: "Both completion edges stamp `completed_at` with the current logical clock and record the officer in `completed_by_user_id`, and both recompute the member's `readiness_score` and `coursework_hours_completed`."

        Design: Corner/calculations/coursework_hours_completed_excludes_practicum
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestones = milestones_by_type(member_id)

        practicum = milestones["PRACTICUM"]["id"]
        start_milestone(practicum)
        complete_milestone(practicum, COMPLETER)
        after_practicum = get_member(member_id)
        assert after_practicum["coursework_hours_completed"] == 0, (
            "a 120-hour PRACTICUM is practice, not coursework"
        )

        coursework = milestones["COURSEWORK"]["id"]
        start_milestone(coursework)
        complete_milestone(coursework, COMPLETER)
        after_coursework = get_member(member_id)
        assert after_coursework["coursework_hours_completed"] == 60


class TestPlacementFee:
    def test_high_need_subject_takes_the_uplift(self, api):
        """PRD §3.7: "When the placement's `subject_area` is `MATH`, `SCIENCE` or `SPED`, the resolved base is multiplied by 1.15 and rounded half up to 0 decimal places."
        PRD §3.7: "The result is stored as an integer number of cents in `placement_fee_cents`, and the uplift is applied exactly once, to the base that has already been resolved."

        Design: Corner/calculations/placement_fee_high_need_subject_uplift
        """
        scenario = setup_member_scenario()
        placement = create_matched_placement(scenario["member_id"], scenario["school"]["id"])
        confirmed = validate_success(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["placement_fee_cents"] == 402500, (
            "round_half_up(350000 * 1.15, 0) = 402500"
        )
        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 1

    def test_zero_district_fee_falls_back_to_the_region_default(self, api):
        """PRD §3.7: "The base is the district's `placement_fee_per_member_cents`; if that value is zero or less, the region's `base_placement_fee_cents` is used instead."

        ENGLISH is not a high-need subject, so no uplift applies.

        Design: Corner/calculations/placement_fee_falls_back_to_region_default
        """
        scenario = setup_member_scenario(
            district_overrides={
                "name": "Delta ISD",
                "placement_fee_per_member_cents": 0,
                "unfilled_slot_penalty_cents": 50000,
            },
            school_overrides={
                "name": "Delta High",
                "subject_needs": ["ENGLISH"],
            },
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
        )
        placement = create_matched_placement(
            scenario["member_id"], scenario["school"]["id"], subject_area="ENGLISH"
        )
        confirmed = validate_success(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["placement_fee_cents"] == 300000, (
            "the region default, not the district's zero"
        )


class TestDeadlineStatusShortCircuit:
    def test_satisfied_short_circuits_the_day_count(self, api):
        """PRD §3.5: "The `deadline_status` band is then assigned with a short-circuit: a milestone that is both `COMPLETED` and `VERIFIED` reports `SATISFIED` regardless of the calendar, so a milestone verified after its due date reports `SATISFIED` rather than `OVERDUE`."
        PRD §3.5: "Only for a milestone that is not yet satisfied does the day count decide — fewer than zero days remaining is `OVERDUE`, up to and including 14 days remaining is `AT_RISK`, and anything beyond that is `ON_TRACK`."

        Design: Corner/calculations/deadline_status_satisfied_short_circuits_overdue
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestones = milestones_by_type(member_id)

        coursework = milestones["COURSEWORK"]["id"]
        start_milestone(coursework)
        complete_milestone(coursework, COMPLETER)
        verify_milestone(coursework, "VERIFY", VERIFIER)

        exam = milestones["EXAM"]["id"]
        set_clock("2026-12-15T00:00:00Z")

        verified = get_certification_milestone(coursework)
        assert verified["days_remaining"] == -44
        assert verified["deadline_status"] == "SATISFIED"

        pending = get_certification_milestone(exam)
        assert pending["days_remaining"] == -44
        assert pending["deadline_status"] == "OVERDUE"


class TestDeadlineBandBoundary:
    """The AT_RISK window is inclusive at 14 days remaining."""

    def test_fifteen_days_is_on_track_and_fourteen_is_at_risk(self, api):
        """PRD §3.5: "Only for a milestone that is not yet satisfied does the day count decide — fewer than zero days remaining is `OVERDUE`, up to and including 14 days remaining is `AT_RISK`, and anything beyond that is `ON_TRACK`."

        Every synthesized milestone is due 2026-11-01, so the clock at
        2026-10-17 leaves 15 days and 2026-10-18 leaves exactly 14.

        Design: Difficulty/boundary_precision_check/deadline_band_boundary_at_14_days
        """
        scenario = setup_member_scenario()
        milestone_id = milestones_by_type(scenario["member_id"])["ORIENTATION"]["id"]

        set_clock("2026-10-17T00:00:00Z")
        at_15 = get_certification_milestone(milestone_id)
        assert at_15["days_remaining"] == 15
        assert at_15["deadline_status"] == "ON_TRACK"

        set_clock("2026-10-18T00:00:00Z")
        at_14 = get_certification_milestone(milestone_id)
        assert at_14["days_remaining"] == 14
        assert at_14["deadline_status"] == "AT_RISK", (
            "the window test is days_remaining <= 14, not < 14"
        )

    def test_one_day_past_due_is_overdue(self, api):
        """PRD §3.5: "fewer than zero days remaining is `OVERDUE`"
        PRD §3.5: "The `days_remaining` is the whole number of days between the clock's current UTC date and the milestone's `due_date` UTC date, computed after truncating both to their date components."

        Design: Difficulty/boundary_precision_check/deadline_band_boundary_at_14_days
        """
        scenario = setup_member_scenario()
        milestone_id = milestones_by_type(scenario["member_id"])["ORIENTATION"]["id"]

        set_clock("2026-11-02T00:00:00Z")
        overdue = get_certification_milestone(milestone_id)
        assert overdue["days_remaining"] == -1
        assert overdue["deadline_status"] == "OVERDUE"


class TestReadinessRatioClamp:
    def test_practice_ratio_is_clamped_at_one(self, api):
        """PRD §3.5: "The practice ratio compares the member's `practice_teaching_hours` against the selected pathway's `required_practice_hours`, capped at 1.0."

        At 120 practice hours the ratio reaches its cap; quadrupling the hours
        to 480 leaves the score untouched, whereas an unclamped practice term
        would have produced 100 * 0.3 * 4 = 120 before the ceiling.

        Design: Corner/calculations/readiness_score_ratios_clamped_at_one
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        at_120 = record_practice_hours(member_id, 120)
        assert at_120["readiness_score"] == pytest.approx(30.00, abs=0.01)

        at_480 = record_practice_hours(member_id, 360)
        assert at_480["practice_teaching_hours"] == 480
        assert at_480["readiness_score"] == pytest.approx(30.00, abs=0.01), (
            "the clamped practice term cannot grow past its cap"
        )
