"""Care plan authoring, clinical review, goals and interventions."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, UNKNOWN_UUID, add_goal, assert_care_plan,
    assert_care_plan_goal, assert_intervention, author_plan,
    complete_intervention, create_goal_payload, create_intervention_payload,
    make_care_manager_headers, make_clinical_reviewer_headers, plan_intervention,
    read_care_plan, read_goal, read_program, setup_active_care_plan,
    setup_draft_care_plan, submit_plan, validate_error, validate_paginated,
    validate_success,
)


def test_requesting_a_revision_returns_the_plan_to_draft_and_bumps_counters(api):
    """PRD §3.5: "The plan moves from `PENDING_REVIEW` back to `DRAFT`, closing
    the revision cycle. `review_decision` records `REVISION_REQUESTED`, the
    supplied note is stored in `revision_note`, `reviewed_by_care_manager_id`
    records the reviewer's `X-User-ID`, `plan_version_no` increases by one,
    `revision_count` increases by one, and `submitted_at` is cleared back to null
    so the plan reads as unsubmitted again."

    Design: Difficulty/non_linear_state_machine/care_plan_revision_cycle_returns_to_draft_then_activates
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Revision Cycle Program"},
        member_overrides={"external_member_id": "MBR-6001", "full_name": "Sam Iyer",
                          "birth_date": "1960-08-08"},
        goal_specs=[{"domain": "MEDICATION", "description": "Reconcile medications",
                     "target_date": "2026-11-15"}],
        plan_title="Revision cycle plan",
    )
    plan = scenario["plan"]
    assert plan["plan_version_no"] == 1
    assert plan["revision_count"] == 0

    submit_plan(plan["id"], scenario["care_manager"]["id"])
    data = validate_success(
        api.review_care_plan(
            plan["id"],
            {"decision": "REQUEST_REVISION",
             "revision_note": "Add a medication adherence goal."},
            make_clinical_reviewer_headers(scenario["reviewer"]["id"]),
        )
    )
    assert_care_plan(data)
    assert data["status"] == "DRAFT"
    assert data["plan_version_no"] == 2
    assert data["revision_count"] == 1
    assert data.get("submitted_at") is None
    assert data["review_decision"] == "REVISION_REQUESTED"
    assert data["revision_note"] == "Add a medication adherence goal."
    assert data["reviewed_by_care_manager_id"] == scenario["reviewer"]["id"]


def test_resubmitted_plan_activates_carrying_the_bumped_counters(api):
    """PRD §3.5: "Approval moves the plan from `PENDING_REVIEW` to `ACTIVE`,
    stamps `approved_at` with the logical clock, sets `review_decision` to
    `APPROVED`, records `reviewed_by_care_manager_id` as the reviewer's
    `X-User-ID`, and computes `next_review_due_at` as `approved_at` advanced by
    the program's `care_plan_review_interval_days` days."
    PRD §3.5: "The cycle `DRAFT` → `PENDING_REVIEW` → `DRAFT` may repeat as many
    times as the reviewer insists, each pass advancing both counters."

    Design: Difficulty/non_linear_state_machine/care_plan_revision_cycle_returns_to_draft_then_activates
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Revision Cycle Program",
                           "care_plan_review_interval_days": 90},
        member_overrides={"external_member_id": "MBR-6002", "full_name": "Sam Iyer",
                          "birth_date": "1960-08-08"},
        goal_specs=[{"domain": "MEDICATION", "description": "Reconcile medications",
                     "target_date": "2026-11-15"}],
        plan_title="Revision cycle plan",
    )
    plan_id = scenario["plan"]["id"]
    author_id = scenario["care_manager"]["id"]
    reviewer_id = scenario["reviewer"]["id"]

    submit_plan(plan_id, author_id)
    validate_success(
        api.review_care_plan(
            plan_id,
            {"decision": "REQUEST_REVISION", "revision_note": "Add another goal."},
            make_clinical_reviewer_headers(reviewer_id),
        )
    )
    add_goal(plan_id, author_id, domain="BEHAVIORAL",
             description="Adherence coaching", target_date="2026-11-15")
    submit_plan(plan_id, author_id)

    data = validate_success(
        api.review_care_plan(plan_id, {"decision": "APPROVE"},
                             make_clinical_reviewer_headers(reviewer_id))
    )
    assert data["status"] == "ACTIVE"
    assert data["plan_version_no"] == 2, "approval does not advance the revision counters"
    assert data["revision_count"] == 1
    assert data["review_decision"] == "APPROVED"
    assert data["reviewed_by_care_manager_id"] == reviewer_id
    assert data["approved_at"] == "2026-08-01T00:00:00.000Z"
    assert data["next_review_due_at"] == "2026-10-30T00:00:00.000Z"
    assert data["compliance_posture"] == "COMPLIANT"


def test_submitting_a_plan_on_a_pending_enrollment_is_rejected(api):
    """PRD §3.5: "And the owning enrollment's `enrollment_status` must be
    `ACTIVE`, else `ERR_ENROLLMENT_NOT_ACTIVE`."
    PRD §2.6: "a care plan may be submitted or reviewed only while its
    enrollment's `enrollment_status` is `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/care_plan_submit_gated_by_enrollment_status
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Submit Gate Program"},
        member_overrides={"external_member_id": "MBR-1801", "full_name": "Hal Berg",
                          "birth_date": "1958-12-24"},
        goal_specs=[{"domain": "MEDICATION", "description": "Fill gap closure"}],
        plan_title="Pending-enrollment plan",
        activate_it=False,
    )
    assert scenario["enrollment"]["enrollment_status"] == "PENDING"

    response = api.submit_care_plan(
        scenario["plan"]["id"],
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)
    assert response.status_code == 409
    assert read_care_plan(scenario["plan"]["id"])["status"] == "DRAFT"


def test_submitting_the_same_plan_succeeds_once_the_enrollment_is_active(api):
    """PRD §3.5: "A successful submission moves `status` from `DRAFT` to
    `PENDING_REVIEW` and stamps `submitted_at`."
    PRD §3.4: "Either plan operations or a care manager may activate it, moving
    `enrollment_status` from `PENDING` to `ACTIVE`; attempting this on an
    enrollment in any other state yields `ERR_ENROLLMENT_NOT_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/care_plan_submit_gated_by_enrollment_status
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Submit Gate Program"},
        member_overrides={"external_member_id": "MBR-1802", "full_name": "Hal Berg",
                          "birth_date": "1958-12-24"},
        goal_specs=[{"domain": "MEDICATION", "description": "Fill gap closure"}],
        plan_title="Pending-enrollment plan",
        activate_it=False,
    )
    plan_id = scenario["plan"]["id"]
    author_headers = make_care_manager_headers(scenario["care_manager"]["id"])

    blocked = api.submit_care_plan(plan_id, author_headers)
    validate_error(blocked, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)

    activated = validate_success(
        api.activate_enrollment(scenario["enrollment"]["id"], PROGRAM_ADMIN)
    )
    assert activated["enrollment_status"] == "ACTIVE"

    data = validate_success(api.submit_care_plan(plan_id, author_headers))
    assert data["status"] == "PENDING_REVIEW"
    assert data["submitted_at"] == "2026-08-01T00:00:00.000Z"


def test_planning_an_intervention_commits_staff_minutes_and_freezes_cost(api):
    """PRD §3.5: "On acceptance, the intervention's `cost_cents` is computed once
    and frozen: multiply `staff_minutes` by the program's `hourly_cost_cents`,
    divide by 60, and round half up to whole cents."
    PRD §3.5: "Creation adds the intervention's `staff_minutes` to the program's
    `committed_staff_minutes` and increments the goal's
    `planned_intervention_count` by one."

    Design: Difficulty/compensating_invariant/program_committed_staff_minutes_conserved_across_intervention_void
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Budget Invariant Program",
                           "staff_minute_budget": 100000, "hourly_cost_cents": 9000},
        member_overrides={"external_member_id": "MBR-2401", "full_name": "Ira Wells",
                          "birth_date": "1967-03-13"},
        goal_specs=[{"domain": "CLINICAL",
                     "description": "Self-management education"}],
        plan_title="Budget plan",
    )
    assert scenario["program"]["committed_staff_minutes"] == 0
    care_manager_id = scenario["care_manager"]["id"]

    kept = validate_success(
        api.create_intervention(
            scenario["goal"]["id"],
            create_intervention_payload(modality="EDUCATION", staff_minutes=45),
            make_care_manager_headers(care_manager_id),
        ),
        201,
    )
    assert_intervention(kept)
    assert kept["cost_cents"] == 6750
    assert kept["status"] == "PLANNED"

    program = read_program(scenario["program"]["id"])
    assert program["committed_staff_minutes"] == 45
    assert program["delivered_staff_minutes"] == 0
    assert read_goal(scenario["goal"]["id"])["planned_intervention_count"] == 1


def test_voiding_an_intervention_releases_its_committed_staff_minutes(api):
    """PRD §3.5: "A care manager voids a `PLANNED` intervention by supplying a
    `void_reason`; the intervention moves to `VOIDED`, the reason is stored, and
    its `staff_minutes` is released from the program's `committed_staff_minutes`
    while `delivered_staff_minutes` is left untouched."
    PRD §3.5: "Critically, and in deliberate contrast to completion, **no goal
    auto-transition fires from a void** — a goal whose last planned intervention
    was voided rather than completed stays exactly where it was, even though its
    `planned_intervention_count` has reached 0."

    Design: Difficulty/compensating_invariant/program_committed_staff_minutes_conserved_across_intervention_void
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Budget Invariant Program",
                           "staff_minute_budget": 100000, "hourly_cost_cents": 9000},
        member_overrides={"external_member_id": "MBR-2402", "full_name": "Ira Wells",
                          "birth_date": "1967-03-13"},
        goal_specs=[{"domain": "CLINICAL",
                     "description": "Self-management education"}],
        plan_title="Budget plan",
    )
    goal_id = scenario["goal"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    program_id = scenario["program"]["id"]

    kept = plan_intervention(goal_id, care_manager_id, modality="EDUCATION",
                             staff_minutes=45)
    committed_before = read_program(program_id)["committed_staff_minutes"]
    assert committed_before == 45

    doomed = plan_intervention(goal_id, care_manager_id, modality="PHONE",
                               staff_minutes=30)
    assert doomed["cost_cents"] == 4500
    assert read_program(program_id)["committed_staff_minutes"] == 75

    voided = validate_success(
        api.void_intervention(doomed["id"], {"void_reason": "Duplicate outreach entry."},
                              make_care_manager_headers(care_manager_id))
    )
    assert voided["status"] == "VOIDED"
    assert voided["cost_cents"] == 4500, "the frozen cost survives the void"

    program = read_program(program_id)
    assert program["committed_staff_minutes"] == committed_before
    assert program["delivered_staff_minutes"] == 0

    goal = read_goal(goal_id)
    assert goal["planned_intervention_count"] == 1
    assert goal["status"] == "OPEN", "a void fires no goal auto-transition"

    still_planned, meta = validate_paginated(
        api.list_interventions(goal_id, PROGRAM_ADMIN, params={"status": "PLANNED"})
    )
    assert meta["total_count"] == 1
    assert still_planned[0]["id"] == kept["id"]


def test_goal_under_an_unknown_care_plan_is_not_found(api):
    """PRD §2.6: "**Path resolution** — every identifier embedded in the request
    path is resolved from left to right, and the first segment that resolves to
    nothing decides the error."
    PRD §3.5: "Each goal names the `care_plan_id` it belongs to, a `domain`, a
    free-text `description` stating the goal, and a `target_date` — an ISO 8601
    calendar date the goal aims to be met by."

    Design: Corner/entities/goal_creation_under_unknown_care_plan_returns_care_plan_not_found
    """
    from test_helpers import create_care_manager

    care_manager = create_care_manager(full_name="Rita Nolan", capacity_points=10.0)
    response = api.create_goal(
        UNKNOWN_UUID,
        create_goal_payload(domain="CLINICAL", description="Ghost goal"),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CARE_PLAN_NOT_FOUND.value)
    assert response.status_code == 404


def test_reviewing_a_draft_plan_is_rejected(api):
    """PRD §3.5: "The plan must be in `PENDING_REVIEW`, else
    `ERR_CARE_PLAN_NOT_IN_REVIEW`."
    PRD §3.5: "A fresh plan opens in `DRAFT` with `plan_version_no` at 1,
    `revision_count` at 0, `at_risk_goal_count` at 0, `compliance_posture` at
    `COMPLIANT`, and `review_decision`, `revision_note`,
    `reviewed_by_care_manager_id`, `submitted_at`, `approved_at`, `closed_at` and
    `next_review_due_at` all null."

    Design: Corner/state_machines/care_plan_review_from_draft_returns_not_in_review
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Review Guard Program"},
        member_overrides={"external_member_id": "MBR-4301", "full_name": "Rev Ray",
                          "birth_date": "1976-06-06"},
        goal_specs=[{"domain": "CLINICAL", "description": "Guard goal"}],
        plan_title="Guard plan",
    )
    response = api.review_care_plan(
        scenario["plan"]["id"], {"decision": "APPROVE"},
        make_clinical_reviewer_headers(scenario["reviewer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CARE_PLAN_NOT_IN_REVIEW.value)
    assert response.status_code == 409

    plan = read_care_plan(scenario["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan.get("review_decision") is None
    assert plan.get("approved_at") is None


def test_goal_meets_only_when_its_last_planned_intervention_completes(api):
    """PRD §3.5: "When a completion leaves the goal with
    `planned_intervention_count` at 0 and `completed_intervention_count` of at
    least 1, the goal itself moves to `MET`. A goal in `OPEN` simply becomes
    `MET`."
    PRD §3.5: "Completion sets `status` to `COMPLETED`, stamps `delivered_at` with
    the logical clock, moves the intervention's `staff_minutes` out of the
    program's `committed_staff_minutes` and into its `delivered_staff_minutes`,
    decrements the goal's `planned_intervention_count` by one and increments its
    `completed_intervention_count` by one."

    Design: Corner/state_machines/goal_auto_meets_when_last_planned_intervention_completes
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Bubble Up Program", "hourly_cost_cents": 9000},
        member_overrides={"external_member_id": "MBR-4501", "full_name": "Bub Bea",
                          "birth_date": "1978-08-08"},
        goal_specs=[{"domain": "MEDICATION", "description": "Adherence"}],
        plan_title="Bubble plan",
    )
    goal_id = scenario["goal"]["id"]
    care_manager_id = scenario["care_manager"]["id"]

    first = plan_intervention(goal_id, care_manager_id, modality="PHONE",
                              staff_minutes=15)
    second = plan_intervention(goal_id, care_manager_id,
                               modality="MEDICATION_REVIEW", staff_minutes=25)
    assert first["cost_cents"] == 2250
    assert second["cost_cents"] == 3750

    complete_intervention(first["id"], care_manager_id)
    midway = read_goal(goal_id)
    assert_care_plan_goal(midway)
    assert midway["status"] == "OPEN"
    assert midway["planned_intervention_count"] == 1
    assert midway["completed_intervention_count"] == 1

    complete_intervention(second["id"], care_manager_id)
    finished = read_goal(goal_id)
    assert finished["status"] == "MET"
    assert finished["planned_intervention_count"] == 0
    assert finished["completed_intervention_count"] == 2

    program = read_program(scenario["program"]["id"])
    assert program["committed_staff_minutes"] == 0
    assert program["delivered_staff_minutes"] == 40


def test_intervention_over_the_program_budget_is_rejected(api):
    """PRD §3.5: "Adding up the program's current `committed_staff_minutes`, its
    current `delivered_staff_minutes`, and the new intervention's `staff_minutes`
    must produce a figure no larger than the program's `staff_minute_budget`;
    equality fits, and only a strict overshoot is rejected with
    `ERR_PROGRAM_STAFF_BUDGET_EXCEEDED`."

    Design: Corner/validations/intervention_over_program_budget_returns_staff_budget_exceeded
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Budget Ceiling Program", "staff_minute_budget": 60,
                           "hourly_cost_cents": 9000},
        member_overrides={"external_member_id": "MBR-7401", "full_name": "Bud Bram",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Budget goal"}],
        plan_title="Budget plan",
    )
    goal_id = scenario["goal"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    author_headers = make_care_manager_headers(care_manager_id)

    plan_intervention(goal_id, care_manager_id, modality="HOME_VISIT",
                      staff_minutes=45)

    over = api.create_intervention(
        goal_id, create_intervention_payload(modality="PHONE", staff_minutes=30),
        author_headers,
    )
    validate_error(over, ApiErrorId.ERR_PROGRAM_STAFF_BUDGET_EXCEEDED.value)
    assert over.status_code == 409

    exact = validate_success(
        api.create_intervention(
            goal_id, create_intervention_payload(modality="PHONE", staff_minutes=15),
            author_headers,
        ),
        201,
    )
    assert exact["cost_cents"] == 2250
    assert read_program(scenario["program"]["id"])["committed_staff_minutes"] == 60


def test_care_plan_listing_filters_by_author_and_reviewer(api):
    """PRD §3.5: "Plans may later be listed and narrowed by `enrollment_id`, by
    `authored_by_care_manager_id`, by `reviewed_by_care_manager_id`, or by
    `status`."
    PRD §3.5: "The acting care manager's `X-User-ID` is recorded on the plan as
    `authored_by_care_manager_id`, which is the anchor for both the ownership
    check on submission and the segregation-of-duties check on review."

    Design: Corner/endpoints/care_plan_list_filters_by_author_and_reviewer
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Author Filter Program"},
        member_overrides={"external_member_id": "MBR-8301", "full_name": "Auth Abe",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Filter goal"}],
        plan_title="Author filter plan",
    )
    plan_id = scenario["plan"]["id"]
    author_id = scenario["care_manager"]["id"]
    reviewer_id = scenario["reviewer"]["id"]
    assert scenario["plan"]["authored_by_care_manager_id"] == author_id
    assert scenario["plan"].get("reviewed_by_care_manager_id") is None

    submit_plan(plan_id, author_id)
    validate_success(
        api.review_care_plan(plan_id, {"decision": "APPROVE"},
                             make_clinical_reviewer_headers(reviewer_id))
    )

    by_author, author_meta = validate_paginated(
        api.list_care_plans(PROGRAM_ADMIN,
                            params={"authored_by_care_manager_id": author_id})
    )
    assert author_meta["total_count"] == 1
    assert by_author[0]["id"] == plan_id

    by_reviewer, reviewer_meta = validate_paginated(
        api.list_care_plans(
            PROGRAM_ADMIN,
            params={"reviewed_by_care_manager_id": reviewer_id, "status": "ACTIVE"},
        )
    )
    assert reviewer_meta["total_count"] == 1
    assert by_reviewer[0]["id"] == plan_id

    _, enrollment_meta = validate_paginated(
        api.list_care_plans(PROGRAM_ADMIN,
                            params={"enrollment_id": scenario["enrollment"]["id"]})
    )
    assert enrollment_meta["total_count"] == 1


def test_plan_goal_and_intervention_state_errors_after_completion(api):
    """PRD §3.5: "**Goals** are added to a plan while it is still in `DRAFT`; an
    attempt to add a goal to a plan in any other status is refused with
    `ERR_CARE_PLAN_NOT_DRAFT`."
    PRD §3.5: "The goal itself must be in `OPEN` or `AT_RISK`; a goal already
    `MET` or `CLOSED_UNMET` takes no new work, and the attempt returns
    `ERR_GOAL_NOT_OPEN`."
    PRD §3.5: "The intervention must be in `PLANNED` — a second completion, or a
    completion of something already voided, returns
    `ERR_INTERVENTION_NOT_PLANNED` — and its plan must still be `ACTIVE`, else
    `ERR_CARE_PLAN_NOT_ACTIVE`."

    Design: Corner/errors/goal_and_plan_state_errors_after_activation_and_completion
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "State Error Program", "hourly_cost_cents": 9000},
        member_overrides={"external_member_id": "MBR-8601", "full_name": "Sta Sue",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Only goal"}],
        plan_title="State error plan",
    )
    goal_id = scenario["goal"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    author_headers = make_care_manager_headers(care_manager_id)

    intervention = plan_intervention(goal_id, care_manager_id, modality="PHONE",
                                     staff_minutes=20)
    completed = complete_intervention(intervention["id"], care_manager_id)
    assert completed["status"] == "COMPLETED"
    assert read_goal(goal_id)["status"] == "MET"

    late_goal = api.create_goal(
        scenario["plan"]["id"],
        create_goal_payload(domain="BEHAVIORAL", description="Late goal"),
        author_headers,
    )
    validate_error(late_goal, ApiErrorId.ERR_CARE_PLAN_NOT_DRAFT.value)
    assert late_goal.status_code == 409

    late_intervention = api.create_intervention(
        goal_id, create_intervention_payload(modality="PHONE", staff_minutes=10),
        author_headers,
    )
    validate_error(late_intervention, ApiErrorId.ERR_GOAL_NOT_OPEN.value)
    assert late_intervention.status_code == 409

    late_void = api.void_intervention(
        intervention["id"], {"void_reason": "Changed my mind."}, author_headers
    )
    validate_error(late_void, ApiErrorId.ERR_INTERVENTION_NOT_PLANNED.value)
    assert late_void.status_code == 409

    program = read_program(scenario["program"]["id"])
    assert program["committed_staff_minutes"] == 0
    assert program["delivered_staff_minutes"] == 20
