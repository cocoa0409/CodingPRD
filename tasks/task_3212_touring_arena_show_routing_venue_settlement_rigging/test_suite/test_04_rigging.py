"""Rigging plans: revision cycle, capacity boundaries, empty-plan gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_rigging_point,
    setup_confirmed_engagement,
    setup_rigging_plan,
    validate_error,
    validate_success,
)

PE = TEST_USERS["production_engineer_headers"]
PE_B = TEST_USERS["production_engineer_b_headers"]
TM = TEST_USERS["tour_manager_headers"]


class TestRiggingPlanRevisionCycle:
    def test_revision_cycle_revise_increments_revision_no(self):
        """PRD §3.4: "Rejection returns the plan to the engineer: `SUBMITTED →
        REJECTED`. Revising a rejected plan moves it `REJECTED → DRAFT` and
        increments `revision_no` by 1, so the audit trail of how many times a
        building's steel was questioned is preserved."

        Design: Difficulty/non_linear_state_machine/rigging_plan_revision_cycle_draft_submit_reject_revise_draft
        """
        ctx = setup_confirmed_engagement()
        _, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 100}],
        )
        plan = validate_success(
            api_client.submit_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE)
        )
        assert plan["status"] == "SUBMITTED"
        plan = validate_success(
            api_client.reject_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE)
        )
        assert plan["status"] == "REJECTED"

        plan = validate_success(
            api_client.revise_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE)
        )
        assert plan["status"] == "DRAFT"
        assert plan["revision_no"] == 2

        plan = validate_success(
            api_client.submit_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE)
        )
        assert plan["status"] == "SUBMITTED"
        assert plan["revision_no"] == 2

    def test_new_plan_supersedes_prior_non_terminal_plan(self):
        """PRD §3.4: "the plan is created empty in `DRAFT` with `revision_no`
        starting at 1, and its creation immediately supersedes any prior plan
        for the same engagement sitting in `DRAFT`, `SUBMITTED`, or `REJECTED` —
        those plans move to `SUPERSEDED` without further ceremony."

        Design: Difficulty/non_linear_state_machine/rigging_plan_revision_cycle_draft_submit_reject_revise_draft
        """
        ctx = setup_confirmed_engagement()
        _, plan_a = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 500, "dynamic_load_kg": 0}],
        )
        # Creating a second plan supersedes the first DRAFT plan.
        resp = api_client.create_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        plan_b = validate_success(resp, expected_status=201)
        assert plan_b["status"] == "DRAFT"
        assert plan_b["revision_no"] == 1

        plan_a_now = validate_success(
            api_client.get_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan_a["id"], TM)
        )
        assert plan_a_now["status"] == "SUPERSEDED"


class TestRiggingPlanApprovePreconditions:
    def test_approve_from_draft_returns_plan_not_submitted(self):
        """PRD §3.4: "First, state: the plan must be `SUBMITTED`, otherwise
        `ERR_PLAN_NOT_SUBMITTED` (HTTP 409)."

        Design: Corner/state_machines/rigging_plan_approve_from_draft_returns_plan_not_submitted
        """
        ctx = setup_confirmed_engagement()
        _, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 100}],
        )
        resp = api_client.approve_rigging_plan(
            ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE_B
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_SUBMITTED)
        plan_now = validate_success(
            api_client.get_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], TM)
        )
        assert plan_now["status"] == "DRAFT"


class TestRiggingCapacityBoundary:
    def test_capacity_equality_allowed_excess_rejected(self):
        """PRD §3.4: "for every rigging point, the summed `static_load_kg` of
        all allocations in the plan targeting that point must not exceed the
        point's `max_static_load_kg`, and likewise the summed `dynamic_load_kg`
        must not exceed the point's `max_dynamic_load_kg`; an exceedance is
        rejected with `ERR_POINT_CAPACITY_EXCEEDED` (HTTP 422). Equality is
        allowed at every boundary: a sum exactly equal to a capacity passes."

        Design: Difficulty/boundary_precision_check/rigging_capacity_equality_allowed_excess_rejected
        """
        ctx = setup_confirmed_engagement()
        point = create_rigging_point(
            ctx["venue"]["id"], max_static_load_kg=5000, max_dynamic_load_kg=500,
            engineering_review_required=False,
        )

        # Plan A: 2500 + 2500 == 5000 — equality allowed. Built, submitted and
        # approved BEFORE plan B exists, because PRD §3.4 supersedes any prior
        # DRAFT/SUBMITTED/REJECTED plan the moment a newer plan is created.
        resp = api_client.create_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        plan_a = validate_success(resp, expected_status=201)
        for load in (2500, 2500):
            validate_success(
                api_client.create_rigging_allocation(
                    ctx["tour"]["id"], ctx["engagement"]["id"], plan_a["id"],
                    {"rigging_point_id": point["id"], "static_load_kg": load,
                     "dynamic_load_kg": 0, "purpose": "r"},
                    PE,
                ), expected_status=201
            )
        plan_a = validate_success(
            api_client.submit_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan_a["id"], PE)
        )
        resp = api_client.approve_rigging_plan(
            ctx["tour"]["id"], ctx["engagement"]["id"], plan_a["id"], PE_B
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"

        # Plan B: 2500 + 2501 == 5001 > 5000 (one over). APPROVED plan A is
        # terminal for supersede purposes, so creating B leaves A untouched.
        resp = api_client.create_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        plan_b = validate_success(resp, expected_status=201)
        for load in (2500, 2501):
            validate_success(
                api_client.create_rigging_allocation(
                    ctx["tour"]["id"], ctx["engagement"]["id"], plan_b["id"],
                    {"rigging_point_id": point["id"], "static_load_kg": load,
                     "dynamic_load_kg": 0, "purpose": "r"},
                    PE,
                ), expected_status=201
            )
        plan_b = validate_success(
            api_client.submit_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan_b["id"], PE)
        )
        resp = api_client.approve_rigging_plan(
            ctx["tour"]["id"], ctx["engagement"]["id"], plan_b["id"], PE_B
        )
        validate_error(resp, ApiErrorId.ERR_POINT_CAPACITY_EXCEEDED)
        plan_b_now = validate_success(
            api_client.get_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan_b["id"], TM)
        )
        assert plan_b_now["status"] == "SUBMITTED"

    def test_single_allocation_under_capacity_approved(self):
        """PRD §3.4: "for every rigging point, the summed `static_load_kg` of
        all allocations in the plan targeting that point must not exceed the
        point's `max_static_load_kg`, and likewise the summed `dynamic_load_kg`
        must not exceed the point's `max_dynamic_load_kg`; an exceedance is
        rejected with `ERR_POINT_CAPACITY_EXCEEDED` (HTTP 422). Equality is
        allowed at every boundary: a sum exactly equal to a capacity passes."

        Design: Difficulty/boundary_precision_check/rigging_capacity_equality_allowed_excess_rejected
        """
        ctx = setup_confirmed_engagement()
        point = create_rigging_point(
            ctx["venue"]["id"], max_static_load_kg=5000, max_dynamic_load_kg=500,
            engineering_review_required=False,
        )
        resp = api_client.create_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        plan = validate_success(resp, expected_status=201)
        validate_success(
            api_client.create_rigging_allocation(
                ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"],
                {"rigging_point_id": point["id"], "static_load_kg": 4999,
                 "dynamic_load_kg": 500, "purpose": "r"},
                PE,
            ), expected_status=201
        )
        plan = validate_success(
            api_client.submit_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE)
        )
        approved = validate_success(
            api_client.approve_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE_B)
        )
        assert approved["status"] == "APPROVED"
