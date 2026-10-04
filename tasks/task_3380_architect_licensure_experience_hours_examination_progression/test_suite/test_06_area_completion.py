"""Experience completion gate: area minima, jurisdiction override, and the
verify-driven depth-2 cascade (PRD §3.3, §3.6)."""
from test_helpers import (
    AREA_MIN_HOURS, NATIONAL_TOTAL_HOURS_REQUIRED, SIX_AREA_PERIODS,
    authorize_exams, create_active_supervisor, create_candidate,
    create_jurisdiction, create_submitted_report, create_verified_report,
    make_candidate_headers, pass_all_six_divisions, satisfy_education,
    validate_success, verify_report,
)

J1 = "J1"


def _registry(api, code=J1, **jurisdiction_overrides):
    create_jurisdiction(code=code, **jurisdiction_overrides)
    candidate = create_candidate(home_jurisdiction_code=code)
    supervisor = create_active_supervisor(jurisdiction_code=code)
    return candidate, supervisor


def _summary(api, candidate):
    return validate_success(api.get_candidate_summary(
        candidate["id"], make_candidate_headers(candidate["id"]),
    ))


class TestAreaMinimumBoundary:
    def test_area_below_minimum_not_satisfied(self, api):
        """PRD §3.3: "every one of the six areas must meet its minimum
        credited hours — at least 160 in `PRACTICE_MANAGEMENT`, at least 360
        in `PROJECT_MANAGEMENT`, at least 260 in `PROGRAMMING_ANALYSIS`, at
        least 1360 in `PROJECT_PLANNING_DESIGN`, at least 1520 in
        `PROJECT_DEVELOPMENT_DOCUMENTATION`, and at least 80 in
        `CONSTRUCTION_EVALUATION`".
        PRD §3.3: "Link one: if this is the candidate's first `VERIFIED`
        report, `experience_status` moves from `NOT_STARTED` to `IN_PROGRESS`
        (refreshing the candidate's `updated_at`); then the completion gate
        below is re-evaluated, and if it now holds, `experience_status`
        advances to `COMPLETE`."

        Design: Difficulty/boundary_precision_check/area_minimum_exact_1360_inclusive
        """
        candidate, supervisor = _registry(api)
        create_verified_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 999,
            "2026-01-05", "2026-03-31",
        )
        summary = _summary(api, candidate)
        assert summary["area_progress"]["PROJECT_PLANNING_DESIGN"] == 999
        assert summary["experience_status"] == "IN_PROGRESS", (
            "999 < 1360: area gate unsatisfied"
        )

    def test_area_at_exact_minimum_satisfied(self, api):
        """PRD §3.3: "The six area minima sum to exactly 3740 hours, so a
        jurisdiction that never overrides the national total asks for
        precisely a full-credit profile; an area sitting exactly at its
        minimum counts."

        Design: Difficulty/boundary_precision_check/area_minimum_exact_1360_inclusive
        """
        candidate, supervisor = _registry(api)
        create_verified_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 999,
            "2026-01-05", "2026-03-31",
        )
        create_verified_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 361,
            "2026-04-01", "2026-06-30",
        )
        summary = _summary(api, candidate)
        assert summary["area_progress"]["PROJECT_PLANNING_DESIGN"] == 1360, (
            "999 + 361 == 1360, the inclusive boundary"
        )
        # The other five areas are still at zero, so the full gate is open.
        assert summary["experience_status"] == "IN_PROGRESS"


class TestFinalAreaVerifyCascade:
    def _setup_final_area_pending(self, api):
        """Education SATISFIED, five areas verified at minima, all six exam
        divisions PASSED; CONSTRUCTION_EVALUATION's 80-hour report is
        SUBMITTED but not yet verified."""
        candidate, supervisor = _registry(api)
        satisfy_education(candidate)
        for area, minimum in AREA_MIN_HOURS.items():
            if area == "CONSTRUCTION_EVALUATION":
                continue
            start, end = SIX_AREA_PERIODS[area]
            create_verified_report(
                candidate, supervisor, area, minimum, start, end,
            )
        start, end = SIX_AREA_PERIODS["CONSTRUCTION_EVALUATION"]
        final_report = create_submitted_report(
            candidate, supervisor, "CONSTRUCTION_EVALUATION", 80, start, end,
        )
        auth = authorize_exams(candidate, jurisdiction_code=J1)
        pass_all_six_divisions(candidate, auth["divisions"])
        return candidate, supervisor, final_report

    def test_final_verify_completes_experience(self, api):
        """PRD §3.3: "then the completion gate below is re-evaluated, and if
        it now holds, `experience_status` advances to `COMPLETE`."
        PRD §3.3: "every one of the six areas must meet its minimum credited
        hours — at least 160 in `PRACTICE_MANAGEMENT`, at least 360 in
        `PROJECT_MANAGEMENT`, at least 260 in `PROGRAMMING_ANALYSIS`, at least
        1360 in `PROJECT_PLANNING_DESIGN`, at least 1520 in
        `PROJECT_DEVELOPMENT_DOCUMENTATION`, and at least 80 in
        `CONSTRUCTION_EVALUATION` — and the total credited across all areas
        must reach the greater of the national floor of 3740 hours or the home
        jurisdiction's `min_total_experience_hours` override."

        Design: Difficulty/transitive_cascade/final_area_verify_depth2
        """
        candidate, supervisor, final_report = self._setup_final_area_pending(api)
        summary = _summary(api, candidate)
        assert summary["experience_status"] == "IN_PROGRESS"
        verified = verify_report(supervisor, final_report["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["credited_hours"] == 80
        summary = _summary(api, candidate)
        assert summary["experience_status"] == "COMPLETE", (
            "link 1: final area reaches its 80-hour minimum; total 3740"
        )
        assert summary["total_credited_hours"] == NATIONAL_TOTAL_HOURS_REQUIRED

    def test_final_verify_flips_certificate_eligible(self, api):
        """PRD §3.3: "Link two: `certificate_eligible` is recomputed."
        PRD §3.6: "The flag is true exactly when the candidate's
        `education_status` is `SATISFIED`, the candidate's
        `experience_status` is `COMPLETE`, all six examination divisions are
        `PASSED`, the home jurisdiction either does not require a supplemental
        exam or the candidate holds a `PASSED` supplemental exam for that home
        jurisdiction, and the candidate's `record_standing` is `CLEAR`."

        Design: Difficulty/transitive_cascade/final_area_verify_depth2
        """
        candidate, supervisor, final_report = self._setup_final_area_pending(api)
        before = _summary(api, candidate)
        assert before["certificate_eligible"] is False, (
            "experience incomplete before the trigger"
        )
        assert before["exam_status"] == "ALL_PASSED"
        verify_report(supervisor, final_report["id"])
        after = _summary(api, candidate)
        assert after["certificate_eligible"] is True, (
            "link 2: all four inputs now hold"
        )
        assert after["exam_status"] == "ALL_PASSED", (
            "verify cascade leaves the examination track untouched"
        )


class TestJurisdictionTotalOverride:
    def test_jurisdiction_total_hours_override_gate(self, api):
        """PRD §3.3: "the total credited across all areas must reach the
        greater of the national floor of 3740 hours or the home jurisdiction's
        `min_total_experience_hours` override."

        Design: Corner/validations/jurisdiction_total_hours_override_gate
        """
        candidate, supervisor = _registry(
            api, code="JB", min_total_experience_hours=4000,
        )
        for area, minimum in AREA_MIN_HOURS.items():
            start, end = SIX_AREA_PERIODS[area]
            create_verified_report(
                candidate, supervisor, area, minimum, start, end,
            )
        summary = _summary(api, candidate)
        # All six area minima met at the national total 3740, yet the home
        # jurisdiction overrides the total to 4000.
        assert summary["total_credited_hours"] == NATIONAL_TOTAL_HOURS_REQUIRED
        assert summary["experience_status"] == "IN_PROGRESS"
        extra = create_submitted_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 260,
            "2026-08-17", "2026-08-28",
        )
        verify_report(supervisor, extra["id"])
        summary = _summary(api, candidate)
        assert summary["total_credited_hours"] == 4000
        assert summary["experience_status"] == "COMPLETE", (
            "4000 >= max(3740, 4000)"
        )
