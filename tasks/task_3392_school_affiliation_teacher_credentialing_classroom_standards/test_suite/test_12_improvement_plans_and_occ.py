"""Improvement plans: terminal VERIFIED lockdown, the respond OCC token, the
stale-application-create OCC token, and the open-plan gate on accreditation
submission across the plan's OVERDUE and SUBMITTED states.
"""

from test_helpers import (
    ApiErrorId,
    create_accepted_self_study,
    create_application,
    create_school,
    create_school_application_payload,
    create_visit,
    file_classroom_audit,
    file_visit_report,
    get_only_plan_for_school,
    make_school_admin_headers,
    pay_dues,
    read_application,
    read_improvement_plan,
    read_school,
    reset_clock,
    respond_to_plan,
    respond_to_plan_payload,
    review_plan,
    set_clock,
    setup_member_school,
    setup_school_with_reported_visit,
    validate_error,
    validate_success,
)


def test_plan_respond_from_verified_rejected(api):
    """PRD section 3.6: "Responding is allowed from `OPEN` and, as a late
    response, from `OVERDUE`" — and "A `VERIFIED` outcome is terminal and
    stamps `verified_at`". A respond call on the terminal plan therefore fails
    the state tier (PRD section 2.7: "otherwise failing with
    `ERR_INVALID_STATE` (HTTP 409)").

    Design: Corner/state_machines/plan_respond_from_verified_rejected
    """
    reset_clock()
    staged = setup_school_with_reported_visit(
        verdict="IMPROVEMENT_REQUIRED", findings=["Fix ratio"]
    )
    plan = staged.plan
    respond_to_plan(plan["id"], staged.school["id"], response_notes="Done")
    review_plan(plan["id"], "VERIFIED")

    current = read_improvement_plan(plan["id"])
    rejected = api.respond_to_improvement_plan(
        plan["id"],
        respond_to_plan_payload("Again", current["version"]),
        headers=make_school_admin_headers(staged.school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

    plan = read_improvement_plan(plan["id"])
    assert plan["status"] == "VERIFIED"
    assert plan["verified_at"] is not None
    assert plan["version"] == current["version"], "the rejected respond did not mutate"


def test_occ_stale_application_create_returns_412_then_fresh_succeeds(api):
    """PRD section 2.8: "if the school's current `version` has advanced since
    that read — because another writer created an application or self-study,
    or mutated the school — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)." PRD section 2.4: "Recording a payment recomputes
    `dues_current` and `directory_visible` and increments the school's
    `version`."

    Design: Corner/cross_cutting_layers/occ_stale_application_create_returns_412_then_fresh_succeeds
    """
    reset_clock()
    school = create_school(name="OCC School", display_name="OCC Schoolhouse")
    version_seen = school["version"]
    paid = pay_dues(school["id"])
    version_after_payment = paid["version"]
    assert version_after_payment == version_seen + 1, "the dues payment bumps the version"

    stale = api.create_school_application(
        create_school_application_payload(school["id"], "AFFILIATION", version_seen),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = api.create_school_application(
        create_school_application_payload(school["id"], "AFFILIATION", version_after_payment),
        headers=make_school_admin_headers(school["id"]),
    )
    created = validate_success(fresh, 201)
    assert created["status"] == "DRAFT"
    assert read_school(school["id"])["version"] == version_after_payment + 1, (
        "creating the application is itself a direct school mutation"
    )


def test_occ_stale_plan_respond_returns_412(api):
    """PRD section 2.7: "the optimistic-concurrency check of §2.8 is evaluated
    first, before the state-transition check within this tier, so a stale
    replay against a since-invalidated state still answers 412 with
    `ERR_STALE_VERSION`".

    Design: Corner/cross_cutting_layers/occ_stale_plan_respond_returns_412
    """
    reset_clock()
    staged = setup_school_with_reported_visit(
        verdict="IMPROVEMENT_REQUIRED", findings=["Fix work period"]
    )
    plan = staged.plan
    captured_version = plan["version"]

    first = api.respond_to_improvement_plan(
        plan["id"],
        respond_to_plan_payload("first response", captured_version),
        headers=make_school_admin_headers(staged.school["id"]),
    )
    assert validate_success(first, 200)["status"] == "SUBMITTED"

    replay = api.respond_to_improvement_plan(
        plan["id"],
        respond_to_plan_payload("replay with stale version", captured_version),
        headers=make_school_admin_headers(staged.school["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    plan = read_improvement_plan(plan["id"])
    assert plan["status"] == "SUBMITTED"
    assert plan["response_notes"] == "first response"


def _accreditation_blocked_by_plan():
    """MEMBER school (member_since 2026-09-01, dues through 2028-09-01) with
    an ACCEPTED self-study, a visit reported IMPROVEMENT_REQUIRED on
    2026-10-01, and the clock at 2027-09-02 so the auto-created plan is
    OVERDUE and the school auto-PROBATIONED."""
    staged = setup_member_school(dues_period_end="2028-09-01")
    school_id = staged.school["id"]
    study = create_accepted_self_study(school_id)
    visit = create_visit(school_id, study["id"])
    set_clock("2026-10-01T00:00:00Z")
    file_classroom_audit(staged.classroom["id"])
    file_visit_report(
        visit["id"], verdict="IMPROVEMENT_REQUIRED", findings=["Work period fell short twice"]
    )
    plan = get_only_plan_for_school(school_id)
    set_clock("2027-09-02T00:00:00Z")
    application = create_application(school_id, "ACCREDITATION")
    return staged, study, plan, application


def test_accreditation_submit_blocked_while_plan_overdue_or_submitted(api):
    """PRD section 3.7: "no improvement plan of the school may sit in `OPEN`,
    `OVERDUE` or `SUBMITTED` (`ERR_OPEN_IMPROVEMENT_PLAN`, HTTP 409)". PRD
    section 3.6: "the plan becomes `OVERDUE` when the logical date moves
    strictly past that date".

    Design: Difficulty/cross_entity_state_dependency/accreditation_submit_blocked_by_open_improvement_plan
    """
    reset_clock()
    staged, _, plan, application = _accreditation_blocked_by_plan()
    school_id = staged.school["id"]
    assert read_improvement_plan(plan["id"])["status"] == "OVERDUE"
    assert read_school(school_id)["standing"] == "PROBATION"

    while_overdue = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school_id)
    )
    validate_error(while_overdue, ApiErrorId.ERR_OPEN_IMPROVEMENT_PLAN)

    respond_to_plan(plan["id"], school_id, response_notes="Work period restructured")
    assert read_improvement_plan(plan["id"])["status"] == "SUBMITTED"

    while_submitted = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school_id)
    )
    validate_error(while_submitted, ApiErrorId.ERR_OPEN_IMPROVEMENT_PLAN)


def test_accreditation_submit_unblocked_after_plan_verified(api):
    """PRD section 3.6: "when the school then has no remaining plan in `OPEN`,
    `OVERDUE` or `SUBMITTED` and its standing is `PROBATION`, the school's
    standing auto-restores to `GOOD_STANDING`". PRD section 3.7: "the school
    must hold an `ACCEPTED` self-study, else `ERR_SELF_STUDY_REQUIRED`
    (HTTP 422), which the submission pins onto the application as
    `supporting_self_study_id`".

    Design: Difficulty/cross_entity_state_dependency/accreditation_submit_blocked_by_open_improvement_plan
    """
    reset_clock()
    staged, study, plan, application = _accreditation_blocked_by_plan()
    school_id = staged.school["id"]

    respond_to_plan(plan["id"], school_id, response_notes="Work period restructured")
    review_plan(plan["id"], "VERIFIED")
    assert read_school(school_id)["standing"] == "GOOD_STANDING", "standing auto-restored"

    accepted = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school_id)
    )
    submitted = validate_success(accepted, 200)
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["supporting_self_study_id"] == study["id"]
    assert read_application(application["id"])["submitted_at"] is not None
