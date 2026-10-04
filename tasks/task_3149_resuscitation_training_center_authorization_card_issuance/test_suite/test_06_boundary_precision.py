"""Boundary precision: exact thresholds on skills scoring and certification."""
import pytest

from test_helpers import (
    ADMIN,
    TC,
    ApiErrorId,
    create_center_with_faculty,
    create_instructor_payload,
    create_monitoring_payload,
    create_scheduled_session,
    create_teaching_evaluation_payload,
    enroll_student,
    get_success_data,
    make_faculty_headers,
    make_instructor_headers,
    setup_teaching_scenario,
    start_session,
    validate_error,
    validate_success,
)


def _checklist(passed: int, failed: int) -> list:
    """Checklist of `passed` passed items and `failed` failed items; the
    critical item is always first and always passes."""
    items = [{"item_code": "I01", "critical": True, "passed": True}]
    for i in range(2, passed + 1):
        items.append({"item_code": f"I{i:02d}", "critical": False,
                      "passed": True})
    for j in range(1, failed + 1):
        items.append({"item_code": f"F{j:02d}", "critical": False,
                      "passed": False})
    return items


class TestSkillsScoreExactly84Passes:
    def test_84_boundary_passes_83_33_requires_remediation(self, api):
        """PRD §3.6: "An initial attempt yields `PASS` when no critical item
        has `passed` false *and* `score_percent` is at least 84.00; otherwise
        it yields `REMEDIATION_REQUIRED`."
        PRD §3.6: "The server derives `total_items` as the number of items,
        `passed_items` as the count of items whose `passed` is `true`, and
        `score_percent` as `passed_items` multiplied by 100 and divided by
        `total_items`, rounded half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/skills_score_exactly_84_passes
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry_a = enroll_student(session["id"], "Sam Student", "sam@x.example")
        entry_b = enroll_student(session["id"], "Rita Rescuer", "rita@x.example")
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])

        # 21/25 = 84.00 exactly -> PASS (boundary inclusive).
        eval_a = validate_success(
            api.create_skills_evaluation(
                entry_a["id"], {"items": _checklist(21, 4)}, lead_headers),
            expected_status=201)
        assert eval_a["score_percent"] == pytest.approx(84.0, abs=0.001)
        assert eval_a["outcome"] == "PASS"
        assert validate_success(
            api.get_roster_entry(entry_a["id"], TC))["status"] == "PASSED"

        # 20/24 = 83.33 -> REMEDIATION_REQUIRED (one rounding point below).
        eval_b = validate_success(
            api.create_skills_evaluation(
                entry_b["id"], {"items": _checklist(20, 4)}, lead_headers),
            expected_status=201)
        assert eval_b["score_percent"] == pytest.approx(83.33, abs=0.001)
        assert eval_b["outcome"] == "REMEDIATION_REQUIRED"
        entry_b_now = validate_success(api.get_roster_entry(entry_b["id"], TC))
        assert entry_b_now["status"] == "ENROLLED"
        assert entry_b_now["remediation_used"] is True

    def test_failed_critical_item_overrides_high_percentage(self, api):
        """PRD §3.6: "An initial attempt yields `PASS` when no critical item
        has `passed` false *and* `score_percent` is at least 84.00; otherwise
        it yields `REMEDIATION_REQUIRED`."

        Design: Difficulty/boundary_precision_check/skills_score_exactly_84_passes
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])

        # 99% score but a failed critical item -> REMEDIATION_REQUIRED.
        items = _checklist(98, 1)
        items[-1]["critical"] = True  # the failed item is critical
        # Restore a passing critical item too (the checklist needs >=1 critical,
        # which items[-1] now provides).
        eval_resp = validate_success(
            api.create_skills_evaluation(
                entry["id"], {"items": items}, lead_headers),
            expected_status=201)
        assert eval_resp["outcome"] == "REMEDIATION_REQUIRED"


class TestCertifyExactlyTwoEvaluationsAtAvg4:
    def test_one_evaluation_rejected_then_avg_4_succeeds(self, api):
        """PRD §3.2: "Certification requires the instructor to currently be in
        `MONITORED` status (otherwise `ERR_INSTRUCTOR_NOT_MONITORED`), at least
        two `TeachingEvaluation` rows recorded across the instructor's entire
        history (otherwise `ERR_INSUFFICIENT_TEACHING_EVALUATIONS` — there is
        no time window on this count, and rows persist across candidacy
        resets), and a certification evaluation average of at least 4.00
        (otherwise `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD`)."
        PRD §3.2: "Successful certification sets `certified_since` to the
        current clock, sets `renewal_due_at` to twenty-four months after the
        current clock."

        Design: Difficulty/boundary_precision_check/certify_exactly_two_evaluations_at_avg_4
        """
        center, faculty = create_center_with_faculty()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        fac = make_faculty_headers(faculty["id"])
        get_success_data(api.monitor_instructor(
            cand["id"], create_monitoring_payload(), fac))
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=5, notes="Outstanding first observation."), fac))

        # Count boundary: 1 < 2 evaluations -> 409.
        resp = api.certify_instructor(cand["id"], TC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TEACHING_EVALUATIONS)

        # Add a second evaluation of 3: average (5+3)/2 = 4.00 exactly.
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=3, notes="Adequate second observation."), fac))
        certified = validate_success(api.certify_instructor(cand["id"], TC))
        assert certified["status"] == "CERTIFIED"
        assert certified["renewal_due_at"] == "2028-09-01T00:00:00Z"
        assert certified["renewal_count"] == 0

    def test_average_just_below_threshold_rejected(self, api):
        """PRD §3.2: "a certification evaluation average of at least 4.00
        (otherwise `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD`). The average is
        the sum of all `score` values divided by the number of evaluations,
        rounded half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/certify_exactly_two_evaluations_at_avg_4
        """
        center, faculty = create_center_with_faculty()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        fac = make_faculty_headers(faculty["id"])
        get_success_data(api.monitor_instructor(
            cand["id"], create_monitoring_payload(), fac))
        # Scores 5, 4, 2 -> average 11/3 = 3.67 < 4.00.
        for score in (5, 4, 2):
            get_success_data(api.create_teaching_evaluation(
                cand["id"], create_teaching_evaluation_payload(score=score),
                fac))
        resp = api.certify_instructor(cand["id"], TC)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD)
        still = validate_success(api.get_instructor(cand["id"], TC))
        assert still["status"] == "MONITORED"
