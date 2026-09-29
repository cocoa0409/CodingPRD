"""Outage endorsement, rejection, revision and scheduling separation.

An outage carries three signatures and a dependency graph of work steps. A
rejection voids the safety review and freezes the graph; a revision winds both
all the way back. Approval also answers to the plant's outage calendar.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_OUTAGE_WINDOW_TOO_SHORT,
    ERR_TURNAROUND_BUFFER_CONFLICT,
)
from test_helpers.assertions import assert_integer, assert_status
from test_helpers.test_users import (
    ENG_AUTHOR,
    ENGINEER,
    SO_APPROVER,
    SO_REVIEWER,
    make_process_engineer_headers,
    make_safety_officer_headers,
)


def _endorsed_outage(api, findings_count=2):
    """A submitted CATALYST_CHANGE outage with a 7-then-14 day task chain."""
    site = fx.commissioned_site(api, rated_ammonia_tpd=900.0)
    world = fx.endorsed_turnaround(
        api,
        site["plant"]["id"],
        site["train"]["id"],
        durations=(7, 14),
        findings_count=findings_count,
        scope="CATALYST_CHANGE",
        window_start="2026-11-01T00:00:00.000Z",
        window_end="2026-11-27T00:00:00.000Z",
    )
    world["site"] = site
    return world


class TestRejectionVoidsTheReviewAndFreezesTheGraph:
    def test_rejection_voids_the_endorsement_it_inherited(self, api):
        """The decision reads VOID and the findings tally is discarded.

        Design: Difficulty/non_linear_state_machine/turnaround_reject_arm_voids_review_and_blocks_task_graph
        """
        world = _endorsed_outage(api)

        rejected = fx.reject_turnaround(
            api, world["turnaround"]["id"], "SCOPE_INCOMPLETE"
        )

        assert_status(rejected, "REJECTED", label="turnaround")
        assert rejected["rejection_reason"] == "SCOPE_INCOMPLETE"
        assert_status(
            rejected, "VOID", field="psm_review_decision", label="turnaround"
        )
        assert rejected["psm_findings_count"] is None
        assert rejected["psm_reviewed_by_user_id"] == SO_REVIEWER
        assert rejected["approved_by_user_id"] is None

    def test_rejection_blocks_every_step_of_the_task_graph(self, api):
        """Both the ready-in-principle step and its successor go BLOCKED.

        Design: Difficulty/non_linear_state_machine/turnaround_reject_arm_voids_review_and_blocks_task_graph
        """
        world = _endorsed_outage(api)
        fx.reject_turnaround(api, world["turnaround"]["id"], "SCOPE_INCOMPLETE")

        for task in world["tasks"]:
            frozen = validate_success(api.get_turnaround_task(task["id"], ENGINEER))
            assert_status(frozen, "BLOCKED", label="task")

        train = validate_success(
            api.get_reformer_train(world["site"]["train"]["id"], ENGINEER)
        )
        assert_status(train, "IDLE", label="train")

    def test_rejection_leaves_the_schedule_arithmetic_standing(self, api):
        """The critical path and the window length survive the rejection.

        Design: Difficulty/non_linear_state_machine/turnaround_reject_arm_voids_review_and_blocks_task_graph
        """
        world = _endorsed_outage(api)

        rejected = fx.reject_turnaround(
            api, world["turnaround"]["id"], "SCOPE_INCOMPLETE"
        )

        assert_integer(rejected["critical_path_days"], 21, "turnaround.critical_path_days")
        assert_integer(rejected["window_days"], 26, "turnaround.window_days")


class TestRevisionWindsTheOutageBackToDraft:
    def test_revision_clears_the_rejection_and_the_review_history(self, api):
        """Back in DRAFT the outage has no rejection and no review decision.

        Design: Difficulty/non_linear_state_machine/turnaround_rejected_to_draft_loop_restores_task_graph
        """
        world = _endorsed_outage(api)
        fx.reject_turnaround(api, world["turnaround"]["id"], "SCOPE_INCOMPLETE")

        revised = validate_success(
            api.revise_turnaround(
                world["turnaround"]["id"], make_process_engineer_headers(ENG_AUTHOR)
            )
        )

        assert_status(revised, "DRAFT", label="turnaround")
        assert revised["rejection_reason"] is None
        assert_status(revised, "NONE", field="psm_review_decision", label="turnaround")
        assert revised["psm_reviewed_by_user_id"] is None
        assert revised["approved_by_user_id"] is None

    def test_revision_returns_every_blocked_step_to_pending(self, api):
        """The graph is workable again and nothing is recorded as done.

        Design: Difficulty/non_linear_state_machine/turnaround_rejected_to_draft_loop_restores_task_graph
        """
        world = _endorsed_outage(api)
        fx.reject_turnaround(api, world["turnaround"]["id"], "SCOPE_INCOMPLETE")

        revised = validate_success(
            api.revise_turnaround(
                world["turnaround"]["id"], make_process_engineer_headers(ENG_AUTHOR)
            )
        )

        for task in world["tasks"]:
            restored = validate_success(api.get_turnaround_task(task["id"], ENGINEER))
            assert_status(restored, "PENDING", label="task")

        assert_integer(revised["critical_path_days"], 21, "turnaround.critical_path_days")
        assert_integer(revised["tasks_done_count"], 0, "turnaround.tasks_done_count")


class TestCompletionWaitsForEveryStep:
    def _outage_in_progress(self, api):
        site = fx.commissioned_site(api, rated_ammonia_tpd=1000.0)
        world = fx.in_progress_turnaround(
            api,
            site["plant"]["id"],
            site["train"]["id"],
            "2026-11-01T00:00:00Z",
            durations=(7, 14),
            findings_count=0,
            scope="CATALYST_CHANGE",
            window_start="2026-11-01T00:00:00.000Z",
            window_end="2026-11-27T00:00:00.000Z",
        )
        world["site"] = site
        fx.complete_task(api, world["tasks"][0]["id"])
        return world

    def test_completion_is_refused_while_a_successor_step_is_outstanding(self, api):
        """One step done out of two is not enough to close the outage.

        Design: Difficulty/cross_entity_state_dependency/turnaround_completion_blocked_by_undone_child_task
        """
        world = self._outage_in_progress(api)

        response = api.complete_turnaround(
            world["turnaround"]["id"],
            {"new_charge_code": "CC2", "new_charge_design_life_hours": 40000.0},
            make_process_engineer_headers(ENG_AUTHOR),
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        outage = validate_success(
            api.get_turnaround(world["turnaround"]["id"], ENGINEER)
        )
        assert_status(outage, "IN_PROGRESS", label="turnaround")
        assert_integer(outage["tasks_done_count"], 1, "turnaround.tasks_done_count")
        assert_integer(outage["tasks_total_count"], 2, "turnaround.tasks_total_count")

    def test_the_finished_step_releases_its_successor_without_closing_the_outage(
        self, api
    ):
        """The first step is DONE and the second is READY, and that is all.

        Design: Difficulty/cross_entity_state_dependency/turnaround_completion_blocked_by_undone_child_task
        """
        world = self._outage_in_progress(api)
        validate_error(
            api.complete_turnaround(
                world["turnaround"]["id"],
                {"new_charge_code": "CC2", "new_charge_design_life_hours": 40000.0},
                make_process_engineer_headers(ENG_AUTHOR),
            ),
            ERR_INVALID_STATE,
            409,
        )

        first = validate_success(
            api.get_turnaround_task(world["tasks"][0]["id"], ENGINEER)
        )
        assert_status(first, "DONE", label="first task")
        second = validate_success(
            api.get_turnaround_task(world["tasks"][1]["id"], ENGINEER)
        )
        assert_status(second, "READY", label="second task")

    def test_the_refused_completion_installs_no_replacement_charge(self, api):
        """The train keeps its original charge and stays down for the outage.

        Design: Difficulty/cross_entity_state_dependency/turnaround_completion_blocked_by_undone_child_task
        """
        world = self._outage_in_progress(api)
        validate_error(
            api.complete_turnaround(
                world["turnaround"]["id"],
                {"new_charge_code": "CC2", "new_charge_design_life_hours": 40000.0},
                make_process_engineer_headers(ENG_AUTHOR),
            ),
            ERR_INVALID_STATE,
            409,
        )

        charge = validate_success(
            api.get_catalyst_charge(world["site"]["charge"]["id"], ENGINEER)
        )
        assert_status(charge, "ACTIVE", label="charge")

        charges, meta = validate_paginated(
            api.list_catalyst_charges(ENGINEER, train_id=world["site"]["train"]["id"])
        )
        assert meta["total_count"] == 1, (
            f"expected exactly one charge on the train, got {meta['total_count']}"
        )
        assert len(charges) == 1

        train = validate_success(
            api.get_reformer_train(world["site"]["train"]["id"], ENGINEER)
        )
        assert_status(train, "DOWN_FOR_TURNAROUND", label="train")


def _approved_first_outage(api, site):
    """An APPROVED vessel inspection running 2026-10-01 to 2026-10-27."""
    return fx.approved_turnaround_world(
        api,
        site["plant"]["id"],
        site["train"]["id"],
        durations=(5,),
        findings_count=0,
        scope="VESSEL_INSPECTION",
        window_start="2026-10-01T00:00:00.000Z",
        window_end="2026-10-27T00:00:00.000Z",
    )


class TestBufferConflictOutranksWindowLength:
    def _two_defect_outage(self, api):
        site = fx.commissioned_site(api, rated_ammonia_tpd=1000.0)
        first = _approved_first_outage(api, site)
        second = fx.author_turnaround(
            api,
            site["plant"]["id"],
            site["train"]["id"],
            author=ENG_AUTHOR,
            scope="VESSEL_INSPECTION",
            window_start="2026-11-05T00:00:00.000Z",
            window_end="2026-11-25T00:00:00.000Z",
        )
        head = fx.add_task(api, second["id"], 7)
        fx.submit_turnaround(api, second["id"], actor=ENG_AUTHOR)
        fx.add_task(api, second["id"], 14, predecessor_task_id=head["id"])
        fx.psm_review(
            api, second["id"], decision="ENDORSED", findings_count=1, reviewer=SO_REVIEWER
        )
        return {"site": site, "first": first, "second": second}

    def test_the_calendar_separation_failure_is_reported_first(self, api):
        """The nine-day gap is answered before the overlong critical path.

        Design: Difficulty/priority_pair_validation_conflict/turnaround_buffer_conflict_outranks_outage_window_too_short_on_approve
        """
        world = self._two_defect_outage(api)

        response = api.approve_turnaround(
            world["second"]["id"], make_safety_officer_headers(SO_APPROVER)
        )
        validate_error(response, ERR_TURNAROUND_BUFFER_CONFLICT, 409)
        assert response.json()["data"]["error_id"] != ERR_OUTAGE_WINDOW_TOO_SHORT

    def test_both_defects_are_genuinely_present_on_the_refused_outage(self, api):
        """A 21-day path in a 20-day window, nine days after the last outage.

        Design: Difficulty/priority_pair_validation_conflict/turnaround_buffer_conflict_outranks_outage_window_too_short_on_approve
        """
        world = self._two_defect_outage(api)
        validate_error(
            api.approve_turnaround(
                world["second"]["id"], make_safety_officer_headers(SO_APPROVER)
            ),
            ERR_TURNAROUND_BUFFER_CONFLICT,
            409,
        )

        second = validate_success(api.get_turnaround(world["second"]["id"], ENGINEER))
        assert_status(second, "SUBMITTED", label="second outage")
        assert second["approved_by_user_id"] is None
        assert_integer(second["window_days"], 20, "turnaround.window_days")
        assert_integer(second["critical_path_days"], 21, "turnaround.critical_path_days")

        first = validate_success(
            api.get_turnaround(world["first"]["turnaround"]["id"], ENGINEER)
        )
        assert_status(first, "APPROVED", label="first outage")


class TestOutageSeparationBuffer:
    def _calendar_world(self, api):
        site = fx.commissioned_site(api, rated_ammonia_tpd=1000.0)
        first = _approved_first_outage(api, site)
        near = fx.endorsed_turnaround(
            api,
            site["plant"]["id"],
            site["train"]["id"],
            durations=(5,),
            findings_count=0,
            scope="VESSEL_INSPECTION",
            window_start="2026-11-09T00:00:00.000Z",
            window_end="2026-11-29T00:00:00.000Z",
        )
        far = fx.endorsed_turnaround(
            api,
            site["plant"]["id"],
            site["train"]["id"],
            durations=(5,),
            findings_count=0,
            scope="VESSEL_INSPECTION",
            window_start="2026-11-10T00:00:00.000Z",
            window_end="2026-11-30T00:00:00.000Z",
        )
        return {"site": site, "first": first, "near": near, "far": far}

    def test_thirteen_whole_days_of_separation_is_refused(self, api):
        """One day short of the buffer and the approval is turned away.

        Design: Difficulty/resource_temporal_overlap/turnaround_windows_need_fourteen_whole_days_of_separation
        """
        world = self._calendar_world(api)

        response = api.approve_turnaround(
            world["near"]["turnaround"]["id"], make_safety_officer_headers(SO_APPROVER)
        )
        validate_error(response, ERR_TURNAROUND_BUFFER_CONFLICT, 409)

        near = validate_success(
            api.get_turnaround(world["near"]["turnaround"]["id"], ENGINEER)
        )
        assert_status(near, "SUBMITTED", label="near outage")
        assert near["approved_by_user_id"] is None
        assert_integer(near["window_days"], 20, "turnaround.window_days")

    def test_exactly_fourteen_whole_days_of_separation_is_accepted(self, api):
        """The buffer is satisfied on the day it is exactly met.

        Design: Difficulty/resource_temporal_overlap/turnaround_windows_need_fourteen_whole_days_of_separation
        """
        world = self._calendar_world(api)
        validate_error(
            api.approve_turnaround(
                world["near"]["turnaround"]["id"],
                make_safety_officer_headers(SO_APPROVER),
            ),
            ERR_TURNAROUND_BUFFER_CONFLICT,
            409,
        )

        approved = validate_success(
            api.approve_turnaround(
                world["far"]["turnaround"]["id"],
                make_safety_officer_headers(SO_APPROVER),
            ),
            200,
        )
        assert_status(approved, "APPROVED", label="far outage")
        assert approved["approved_by_user_id"] == SO_APPROVER
        assert_integer(approved["window_days"], 20, "turnaround.window_days")

        first = validate_success(
            api.get_turnaround(world["first"]["turnaround"]["id"], ENGINEER)
        )
        assert_status(first, "APPROVED", label="first outage")
