"""Transitive cascades: a plan flipping OVERDUE drops the school to PROBATION
and suspends its UNDER_REVIEW application; a credential revocation overrides
led classrooms, recomputes the compliant count, and auto-creates an
improvement plan for an ACCREDITED school.
"""

from test_helpers import (
    expected_plan_due_date,
    list_plans_for_school,
    make_plan_overdue,
    read_application,
    read_classroom,
    read_credential,
    read_improvement_plan,
    read_school,
    reset_clock,
    revoke_credential,
    setup_accredited_school,
    setup_credentialed_teacher,
    setup_school_with_reported_visit,
)


def _school_with_overdue_plan():
    """School with an UNDER_REVIEW AFFILIATION application and a plan filed
    from an IMPROVEMENT_REQUIRED visit report at 2026-10-01, flipped OVERDUE
    by the clock."""
    staged = setup_school_with_reported_visit(
        verdict="IMPROVEMENT_REQUIRED",
        findings=["Restore compliant materials inventory"],
        with_pending_application=True,
    )
    return staged


def test_plan_overdue_flips_and_drops_school_to_probation(api):
    """PRD section 2.5: "An `ImprovementPlan` in `OPEN` flips to `OVERDUE` when
    the current logical date becomes strictly greater than its `due_date`,
    firing the school-standing cascade described in §3.7." PRD section 3.7:
    "when one of the school's plans flips from `OPEN` to `OVERDUE`, the school
    drops from `GOOD_STANDING` to `PROBATION`".

    Design: Difficulty/transitive_cascade/plan_overdue_cascade_suspends_application
    """
    reset_clock()
    staged = _school_with_overdue_plan()
    plan = staged.plan
    assert plan["status"] == "OPEN"
    assert plan["due_date"] == expected_plan_due_date("2026-10-01")

    make_plan_overdue(plan)
    assert read_improvement_plan(plan["id"])["status"] == "OVERDUE"
    assert read_school(staged.school["id"])["standing"] == "PROBATION"


def test_plan_overdue_suspends_under_review_application(api):
    """PRD section 3.7: "Leaving `GOOD_STANDING` suspends each of the school's
    `UNDER_REVIEW` applications to `SUSPENDED` — idempotently, so an
    already-suspended application stays". Standing is a parallel dimension:
    the school's membership level is untouched by the cascade.

    Design: Difficulty/transitive_cascade/plan_overdue_cascade_suspends_application
    """
    reset_clock()
    staged = _school_with_overdue_plan()
    assert staged.application["status"] == "UNDER_REVIEW"

    make_plan_overdue(staged.plan)
    application = read_application(staged.application["id"])
    assert application["status"] == "SUSPENDED"
    school = read_school(staged.school["id"])
    assert school["standing"] == "PROBATION"
    assert school["membership_level"] == "APPLICANT"


def _accredited_school_with_led_classroom():
    """An ACCREDITED school whose single classroom is led by a credentialed
    teacher; the school carries one in-window COMPLIANT audit, so its
    compliant classroom count reads 1 before the revocation."""
    teacher = setup_credentialed_teacher(learner_name="Teacher One")
    accredited = setup_accredited_school(
        ensure_catalog=False,
        classroom_overrides={"lead_credential_id": teacher.credential["id"]},
    )
    return teacher, accredited


def test_credential_revocation_overrides_led_classroom_and_recounts(api):
    """PRD section 3.5: "Every classroom whose `lead_credential_id` names the
    revoked credential is mutated to `compliance_override` `NONCOMPLIANT_LEAD`.
    Each school owning an affected classroom then recomputes its
    `compliant_classroom_count`, since an overridden room no longer counts as
    compliant."

    Design: Difficulty/transitive_cascade/credential_revocation_cascade_creates_improvement_plan
    """
    reset_clock()
    teacher, accredited = _accredited_school_with_led_classroom()
    assert accredited.school["compliant_classroom_count"] == 1

    revoke_credential(teacher.credential["id"], reason="Falsified practicum records")

    classroom = read_classroom(accredited.classroom["id"])
    assert classroom["compliance_override"] == "NONCOMPLIANT_LEAD"
    school = read_school(accredited.school["id"])
    assert school["compliant_classroom_count"] == 0
    assert read_credential(teacher.credential["id"])["status"] == "REVOKED"


def test_credential_revocation_auto_creates_improvement_plan(api):
    """PRD section 3.5: "when an affected school's membership level is
    `ACCREDITED` and at least one of its classrooms flipped, the system
    auto-creates an `ImprovementPlan` for that school with `visit_id` null, a
    `required_actions` list reading \"Restore a credentialed lead teacher of
    matching age level\", and a `due_date` set to the current logical date
    plus the `ACTIVE` catalog's `plan_response_days` — an obligation on the
    school even though no visit occurred".

    Design: Difficulty/transitive_cascade/credential_revocation_cascade_creates_improvement_plan
    """
    reset_clock()
    teacher, accredited = _accredited_school_with_led_classroom()
    revoke_credential(teacher.credential["id"], reason="Falsified practicum records")

    plans = list_plans_for_school(accredited.school["id"])
    assert len(plans) == 1, "exactly one plan is auto-created"
    plan = plans[0]
    assert plan["visit_id"] is None
    assert plan["status"] == "OPEN"
    assert plan["required_actions"] == ["Restore a credentialed lead teacher of matching age level"]
    assert plan["due_date"] == expected_plan_due_date("2027-10-20")

    school = read_school(accredited.school["id"])
    assert school["membership_level"] == "ACCREDITED"
    assert school["standing"] == "GOOD_STANDING", "revocation alone does not touch standing"
