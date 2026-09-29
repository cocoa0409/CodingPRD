"""Variant-selected calculations and multi-input formulas."""

from test_helpers import assert_close, assert_missed_class_budget_conserved, created, ok
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    AUDIT_AT_CERTIFICATION,
    AUDIT_AT_ENTRY,
    BENCHMARK_PASS,
    RISK_CUMULATIVE,
    RISK_TERM_SNAPSHOT,
    RISK_TIER_1,
    RISK_TIER_2,
    RISK_TIER_3,
    SUPPORT_MANDATED,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    INSTRUCTOR_HIST_1,
    INSTRUCTOR_KINE_1,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    SPECIALIST,
)


def _two_catalog_world(api):
    """A student whose two completed courses swap applicability between years.

    KINE-101 (12 credits) is CORE in catalog 2026 and NOT_APPLICABLE in 2027;
    HIST-210 (6 credits) is the mirror image.  The student entered under
    catalog 2026 and holds an enrollment in the 2027 term, so the two audit
    variants read different rule rows for the same enrollment set.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fx.make_term(api, index=1, catalog_year=2026)
    term2 = fx.make_term(api, index=2, catalog_year=2027)
    program = fx.make_program(
        api, code="BSKINE", name="BS Kinesiology", catalog_year=2026,
        total_required_credits=60.0,
    )
    kine = fx.make_course(
        api, subject_code="KINE", course_number="101",
        title="Foundations of Kinesiology", credit_hours=12.0,
        instructor_user_id=INSTRUCTOR_KINE_1,
    )
    hist = fx.make_course(
        api, subject_code="HIST", course_number="210",
        title="Modern World History", credit_hours=6.0,
        instructor_user_id=INSTRUCTOR_HIST_1,
    )
    fx.make_rule(api, program["id"], kine["id"], 2026, "CORE")
    fx.make_rule(api, program["id"], kine["id"], 2027, "NOT_APPLICABLE")
    fx.make_rule(api, program["id"], hist["id"], 2026, "NOT_APPLICABLE")
    fx.make_rule(api, program["id"], hist["id"], 2027, "CORE")

    student = fx.make_student(
        api, full_name="Sam One", sport_code="MBB", entry_term_index=1,
        entry_catalog_year=2026,
    )
    fx.declare_major(api, student["id"], program["id"], term1["id"])

    e_kine = fx.make_enrollment(api, student["id"], kine["id"], term1["id"])
    fx.record_grade(api, e_kine["id"], "B")
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    e_hist = fx.make_enrollment(api, student["id"], hist["id"], term2["id"])
    fx.record_grade(api, e_hist["id"], "B")
    return fx.Ctx(
        term1=term1, term2=term2, program=program, student_id=student["id"]
    )


def test_audit_variant_at_entry_reads_the_entry_catalog_year(api):
    """PRD 3.3: "Under `CATALOG_AT_ENTRY` the year read is the student's
    `entry_catalog_year`, so the rules the student enrolled under are honoured
    for life."

    Design: Difficulty/dual_variant_calc/catalog_variant_divergence_on_degree_audit
    """
    world = _two_catalog_world(api)

    summary = ok(
        api.eligibility_summary(
            world.student_id, CERT_OFFICER, {"audit_variant": AUDIT_AT_ENTRY}
        )
    )

    assert summary["audit_variant"] == AUDIT_AT_ENTRY
    # Only KINE-101 is CORE under catalog 2026, so 12.00 of 60.00 credits count.
    assert_close(summary["degree_applicable_credits"], 12.00)
    assert_close(summary["progress_pct"], 0.2000, tolerance=0.00005)
    assert_close(summary["cumulative_gpa"], 3.00)
    assert summary["completed_full_time_terms"] == 1
    assert_close(summary["required_progress_pct"], 0.0000, tolerance=0.00005)
    assert summary["benchmark_result"] == BENCHMARK_PASS


def test_audit_variant_at_certification_reads_the_latest_enrolled_term(api):
    """PRD 3.3: "When the audit runs outside any certification — for the
    on-demand summary of §3.6 — and the caller asks for
    `CATALOG_AT_CERTIFICATION`, the year read is the `catalog_year` of the term
    with the greatest `term_index` that holds at least one enrollment of this
    student."

    Design: Difficulty/dual_variant_calc/catalog_variant_divergence_on_degree_audit
    """
    world = _two_catalog_world(api)

    at_entry = ok(
        api.eligibility_summary(
            world.student_id, CERT_OFFICER, {"audit_variant": AUDIT_AT_ENTRY}
        )
    )
    at_certification = ok(
        api.eligibility_summary(
            world.student_id,
            CERT_OFFICER,
            {"audit_variant": AUDIT_AT_CERTIFICATION},
        )
    )

    assert at_certification["audit_variant"] == AUDIT_AT_CERTIFICATION
    # The latest enrolled term carries catalog_year 2027, where only HIST-210
    # is CORE, so 6.00 credits count instead of 12.00.
    assert_close(at_certification["degree_applicable_credits"], 6.00)
    assert_close(at_certification["progress_pct"], 0.1000, tolerance=0.00005)
    assert_close(at_certification["cumulative_gpa"], 3.00)
    assert at_certification["completed_full_time_terms"] == 1
    assert at_certification["benchmark_result"] == BENCHMARK_PASS
    assert (
        at_entry["degree_applicable_credits"]
        != at_certification["degree_applicable_credits"]
    )


def _declining_then_recovering_student(api):
    """A student with two F grades in term 1 and one A grade in term 2.

    cumulative_gpa is 0.80 (24.00 quality points over 30.00 attempted credits)
    while the highest-ordinal completed term stands alone at 4.00, so the two
    risk variants read the identical enrollment set very differently.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fx.make_term(api, index=1, catalog_year=2026)
    term2 = fx.make_term(api, index=2, catalog_year=2027)
    math = fx.make_course(
        api, subject_code="MATH", course_number="110", title="College Algebra",
        credit_hours=12.0,
    )
    chem = fx.make_course(
        api, subject_code="CHEM", course_number="120",
        title="General Chemistry", credit_hours=12.0,
    )
    arts = fx.make_course(
        api, subject_code="ARTS", course_number="130", title="Studio Drawing",
        credit_hours=6.0,
    )
    student = fx.make_student(
        api, full_name="Sam Two", sport_code="WBB", entry_term_index=1,
        entry_catalog_year=2026,
    )
    for course in (math, chem):
        row = fx.make_enrollment(api, student["id"], course["id"], term1["id"])
        fx.record_grade(api, row["id"], "F")
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    row = fx.make_enrollment(api, student["id"], arts["id"], term2["id"])
    fx.record_grade(api, row["id"], "A")
    return student["id"]


def test_risk_term_snapshot_reads_only_the_highest_ordinal_completed_term(api):
    """PRD 3.6: "Under `TERM_SNAPSHOT` the grade component is the
    credit-weighted grade-point average over only the enrollments in the
    student's highest-ordinal term that holds at least one `COMPLETED`
    enrollment, so a single bad term dominates."

    Design: Difficulty/dual_variant_calc/risk_score_variant_divergence_term_snapshot_vs_cumulative
    """
    student_id = _declining_then_recovering_student(api)

    summary = ok(
        api.eligibility_summary(
            student_id, SPECIALIST, {"risk_variant": RISK_TERM_SNAPSHOT}
        )
    )

    # The snapshot term holds only the 6-credit A, i.e. a 4.00 GPA, which is
    # above the 2.30 floor, so the grade component contributes nothing.
    assert_close(summary["risk_score"], 0.00)
    assert summary["risk_tier"] == RISK_TIER_1
    assert_close(summary["cumulative_gpa"], 0.80)
    assert summary["completed_full_time_terms"] == 1
    assert_close(summary["progress_pct"], 0.0000, tolerance=0.00005)
    assert_close(summary["required_progress_pct"], 0.0000, tolerance=0.00005)


def test_risk_cumulative_variant_diverges_from_the_term_snapshot(api):
    """PRD 3.6: "Under `CUMULATIVE` the grade component is the lifetime
    `cumulative_gpa` over every completed enrollment, so an improving student
    scores lower risk than the term snapshot would suggest and a declining
    student scores higher."

    Design: Difficulty/dual_variant_calc/risk_score_variant_divergence_term_snapshot_vs_cumulative
    """
    student_id = _declining_then_recovering_student(api)

    snapshot = ok(
        api.eligibility_summary(
            student_id, SPECIALIST, {"risk_variant": RISK_TERM_SNAPSHOT}
        )
    )
    cumulative = ok(
        api.eligibility_summary(
            student_id, SPECIALIST, {"risk_variant": RISK_CUMULATIVE}
        )
    )

    # (2.30 - 0.80) / 2.30 * 100 = 65.22 grade points, weighted 0.40 -> 26.09.
    assert_close(cumulative["risk_score"], 26.09)
    assert cumulative["risk_tier"] == RISK_TIER_2
    assert_close(cumulative["cumulative_gpa"], 0.80)
    assert cumulative["completed_full_time_terms"] == 1
    assert_close(cumulative["progress_pct"], 0.0000, tolerance=0.00005)
    assert cumulative["risk_score"] != snapshot["risk_score"]
    assert cumulative["risk_tier"] != snapshot["risk_tier"]


def _three_meeting_travel_world(api):
    """Three fully overlapped 50-minute meetings inside one approved trip.

    SOCI-150 meets on ISO weekdays 1, 3 and 5 at minute 600 for 50 minutes.
    The trip runs from 2026-09-14T08:00:00Z (a Monday) to 2026-09-19T00:00:00Z,
    covering the Monday, Wednesday and Friday meetings and nothing else.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fx.make_term(api, index=1, catalog_year=2026)
    soci = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1, meeting_days=[1, 3, 5],
        meeting_start_minute_utc=600, meeting_duration_minutes=50,
    )
    student = fx.make_student(
        api, full_name="Sam Three", sport_code="MBB", entry_term_index=1,
        entry_catalog_year=2026,
    )
    enrollment = fx.make_enrollment(
        api, student["id"], soci["id"], term1["id"]
    )
    event = fx.make_event(
        api, term1["id"], "2026-09-14T08:00:00Z", "2026-09-19T00:00:00Z",
        sport_code="MBB",
    )
    fx.event_action(api, event["id"], "APPROVE_TRAVEL")
    return fx.Ctx(
        term1=term1, student_id=student["id"], enrollment_id=enrollment["id"],
        event_id=event["id"],
    )


def test_missed_units_round_each_meeting_before_summing(api):
    """PRD 3.8: "Fourth, `missed_units_gross` is the sum of those
    already-rounded per-occurrence figures; the rounding is deliberately
    applied per occurrence and only then summed, and summing raw overlap
    minutes first and rounding once at the end is **not** the specified order
    and will produce a different answer."

    Design: Difficulty/combinatorial_formula/missed_units_round_per_meeting_then_sum
    """
    world = _three_meeting_travel_world(api)

    request = created(
        api.create_missed_class_request(
            f.missed_class_request(world.event_id, world.enrollment_id),
            ADVISOR,
        )
    )

    assert request["missed_meeting_count"] == 3
    # 50 / 60 = 0.8333 -> 0.83 per meeting, so three meetings sum to 2.49.
    assert_close(request["missed_units_gross"], 2.49)
    assert_close(request["missed_units"], 2.49)
    # 150 raw minutes summed first would round once to 2.50.
    assert abs(float(request["missed_units"]) - 2.50) > 0.001
    assert request["status"] == "DRAFT"


def test_missed_units_charge_posts_the_per_meeting_rounded_total(api):
    """PRD 3.8: "The charge posts immediately: the student's
    `missed_class_units_charged` increases by `missed_units`,
    `missed_class_units_remaining` becomes the `missed_class_units_allowance`
    minus the new charged total, and the event's `charged_units_total`
    increases by `missed_units`."

    Design: Difficulty/combinatorial_formula/missed_units_round_per_meeting_then_sum
    """
    world = _three_meeting_travel_world(api)

    fx.make_request(api, world.event_id, world.enrollment_id)

    student = fx.read_student(api, world.student_id)
    event = ok(api.get_event(world.event_id, OPERATIONS))
    assert_close(student["missed_class_units_charged"], 2.49)
    assert_close(student["missed_class_units_remaining"], 6.51)
    assert_close(event["charged_units_total"], 2.49)
    assert_missed_class_budget_conserved(student)


def _tier_three_with_proposed_assignment(api):
    """A TIER_3 student carrying 6.00 charged units and a PROPOSED assignment.

    SOCI-150 meets for 180 minutes on ISO weekdays 1, 3 and 5; the trip covers
    the Monday and the Wednesday meeting only, so 3.00 + 3.00 = 6.00 units are
    charged against the 9.00 allowance.  The tutor assignment reserves 8.00
    weekly hours but is still PROPOSED, so it holds no tutoring credit yet.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fx.make_term(api, index=1, catalog_year=2026)
    soci = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1, meeting_days=[1, 3, 5],
        meeting_start_minute_utc=600, meeting_duration_minutes=180,
    )
    student = fx.make_student(
        api, full_name="Sam Four", sport_code="FB", entry_term_index=1,
        entry_catalog_year=2026,
    )
    enrollment = fx.make_enrollment(
        api, student["id"], soci["id"], term1["id"]
    )
    event = fx.make_event(
        api, term1["id"], "2026-09-14T08:00:00Z", "2026-09-17T00:00:00Z",
        sport_code="FB",
    )
    fx.event_action(api, event["id"], "APPROVE_TRAVEL")
    fx.make_request(api, event["id"], enrollment["id"])
    tutor = fx.make_trained_tutor(
        api, term1["id"], ["SOCI"], full_name="Tia Tutor"
    )
    assignment = fx.make_assignment(
        api, tutor["id"], enrollment["id"], weekly_hours=8.0
    )
    return fx.Ctx(
        term1=term1, student_id=student["id"], enrollment_id=enrollment["id"],
        tutor_id=tutor["id"], assignment_id=assignment["id"],
    )


def test_study_hall_credit_ceiling_comes_from_the_gross_figure(api):
    """PRD 3.6: "Third — and this is the step most easily got wrong — the
    tutoring credit ceiling is selected from the **gross** figure of base plus
    travel offset, not from the figure after any credit is applied: the ceiling
    is 4.0 hours when the gross figure is 10.0 hours or more, and 2.0 hours
    otherwise."

    Design: Difficulty/combinatorial_formula/study_hall_tutor_credit_cap_from_gross_bracket
    """
    world = _tier_three_with_proposed_assignment(api)

    fx.assignment_action(api, world.assignment_id, "ACTIVATE")

    student = fx.read_student(api, world.student_id)
    assert_close(student["missed_class_units_charged"], 6.00)
    assert_close(student["risk_score"], 53.33)
    assert student["risk_tier"] == RISK_TIER_3
    assert student["support_status"] == SUPPORT_MANDATED
    # Gross 8.0 base + 2 travel hours = 10.0, so the ceiling is 4.0 and the
    # 4.0 credit leaves 6.0.  Bracketing after the credit would leave 8.0.
    assert_close(student["required_study_hall_hours"], 6.0, tolerance=0.05)
    assert abs(float(student["required_study_hall_hours"]) - 8.0) > 0.05


def test_study_hall_tutoring_credit_counts_only_active_assignments(api):
    """PRD 3.6: "Fourth, the tutoring credit itself is half an hour of relief
    per contracted weekly tutoring hour, summed over the student's `ACTIVE`
    tutor assignments only — assignments in `PROPOSED`, `SUSPENDED`,
    `COMPLETED` or `TERMINATED` contribute nothing — and then limited to the
    ceiling just selected."

    Design: Difficulty/combinatorial_formula/study_hall_tutor_credit_cap_from_gross_bracket
    """
    world = _tier_three_with_proposed_assignment(api)

    before = fx.read_student(api, world.student_id)
    # The PROPOSED assignment contributes no credit, so the gross 10.0 stands.
    assert_close(before["required_study_hall_hours"], 10.0, tolerance=0.05)

    activated = fx.assignment_action(api, world.assignment_id, "ACTIVATE")

    assert activated["status"] == "ACTIVE"
    tutor = fx.read_tutor(api, world.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 8.00)
    after = fx.read_student(api, world.student_id)
    assert_close(after["required_study_hall_hours"], 6.0, tolerance=0.05)
    assert after["version"] == before["version"] + 1
