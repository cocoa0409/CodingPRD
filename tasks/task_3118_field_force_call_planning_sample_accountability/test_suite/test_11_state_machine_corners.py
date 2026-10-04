"""State machine corner coverage: publish transitions, publish preconditions,
terminal-state lockdowns, initial states, and the plan-lock side effect.

Queue B — corner design section ``state_machines``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestPlanPublish:
    def _setup_draft_plan_with_entry(self, api):
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api)
        entry = fx.add_target_entry(
            api,
            territory["id"],
            prescriber["id"],
            product["id"],
            manager,
            tier="C",
            planned_sample_units=10,
        )
        plan = fx.create_plan(api, territory["id"], territory["version"], manager)
        return {
            "territory": territory,
            "manager": manager,
            "entry": entry,
            "plan": plan,
        }

    def test_publish_moves_draft_to_published(self, api):
        """PRD section 3.3: "Publishing is a separate step by the DistrictManager,
        moving the plan from DRAFT to PUBLISHED and stamping published_at from the
        logical clock."

        Design: Corner/state_machines/call_plan_publish_moves_draft_to_published_and_sets_territory_posture
        """
        ctx = self._setup_draft_plan_with_entry(api)
        data = fx.publish_plan(api, ctx["plan"]["id"], ctx["manager"])
        assert data["status"] == "PUBLISHED"
        assert data["published_at"] is not None
        assert str(data["published_at"]).startswith("2026-09-01T00:00:00")

    def test_publish_sets_territory_alignment_posture(self, api):
        """PRD section 3.3: "On publish, the territory's alignment_posture becomes
        PUBLISHED."

        Design: Corner/state_machines/call_plan_publish_moves_draft_to_published_and_sets_territory_posture
        """
        ctx = self._setup_draft_plan_with_entry(api)
        fx.publish_plan(api, ctx["plan"]["id"], ctx["manager"])
        territory = get_success_data(
            api.get_territory(
                ctx["territory"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert territory["alignment_posture"] == "PUBLISHED"

    def test_publish_with_empty_target_list_rejected(self, api):
        """PRD section 3.3: "the plan must have at least one ACTIVE target-list entry
        (otherwise ERR_EMPTY_TARGET_LIST)."

        Design: Corner/state_machines/publish_with_empty_target_list_rejected
        """
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        plan = fx.create_plan(api, territory["id"], territory["version"], manager)
        response = api.publish_call_plan(
            plan["id"], headers=make_district_manager_headers(manager["id"])
        )
        validate_error(response, ApiErrorId.ERR_EMPTY_TARGET_LIST)
        plan_after = get_success_data(
            api.get_call_plan(
                plan["id"], headers=make_district_manager_headers(manager["id"])
            )
        )
        assert plan_after["status"] == "DRAFT"


class TestVisitTerminalStates:
    def test_double_complete_rejected_and_not_double_counted(self, api):
        """PRD section 3.4: "Completing a visit — the transition from SCHEDULED to
        COMPLETED" and PRD section 2.6: "state-machine legality of the requested
        trigger from the entity's current state, producing ERR_INVALID_STATE." A
        COMPLETED visit is terminal, so a second complete is not a permitted trigger.

        Design: Corner/state_machines/double_complete_of_visit_returns_invalid_state
        """
        ctx = fx.setup_published_plan_with_rep(api, tier="B", planned_sample_units=20)
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        response = api.complete_call_visit(
            visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        entry = get_success_data(
            api.get_target_list_entry(
                ctx["entry"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert entry["delivered_calls"] == 1

    def test_cancelled_visit_rejects_mark_no_show(self, api):
        """PRD section 3.4: "A visit's call_status enumeration is SCHEDULED,
        COMPLETED, CANCELLED, and NO_SHOW" and PRD section 2.6: "state-machine
        legality of the requested trigger from the entity's current state, producing
        ERR_INVALID_STATE." CANCELLED is terminal, so mark-no-show from CANCELLED is
        not permitted.

        Design: Corner/state_machines/cancelled_visit_is_terminal_and_rejects_no_show
        """
        ctx = fx.setup_published_plan_with_rep(api, tier="C", planned_sample_units=10)
        visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-09-02T08:00:00Z",
            scheduled_end="2026-09-02T09:00:00Z",
        )
        get_success_data(
            api.cancel_call_visit(
                visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
            )
        )
        response = api.mark_visit_no_show(
            visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        visit_after = get_success_data(
            api.get_call_visit(
                visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
            )
        )
        assert visit_after["call_status"] == "CANCELLED"


class TestInitialStates:
    def test_new_transfer_starts_requested(self, api):
        """PRD section 3.6: "On creation the transfer is REQUESTED."

        Design: Corner/state_machines/new_transfer_starts_in_requested_and_new_session_in_open
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        transfer = fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 2
        )
        assert transfer["status"] == "REQUESTED"
        assert transfer["version"] == 1

    def test_new_count_session_starts_open(self, api):
        """PRD section 3.6: "On creation the session is OPEN."

        Design: Corner/state_machines/new_transfer_starts_in_requested_and_new_session_in_open
        """
        ctx = fx.setup_count_session_cast(api)
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-21T00:00:00Z",
        )
        assert session["status"] == "OPEN"
        assert session["version"] == 1


class TestFirstCompletedVisitLocksPlan:
    def test_first_completion_locks_plan(self, api):
        """PRD section 3.3: "The first visit on a published plan to reach COMPLETED
        locks the plan: it transitions from PUBLISHED to LOCKED."

        Design: Corner/state_machines/first_completed_visit_locks_plan_and_territory_posture
        """
        ctx = fx.setup_published_plan_with_rep(api, tier="B", planned_sample_units=20)
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        plan = get_success_data(
            api.get_call_plan(
                ctx["plan"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert plan["status"] == "LOCKED"

    def test_first_completion_locks_territory_posture(self, api):
        """PRD section 3.3: "the territory's alignment_posture becomes LOCKED, and no
        further target-list edits are permitted for the territory while the plan is
        locked."

        Design: Corner/state_machines/first_completed_visit_locks_plan_and_territory_posture
        """
        ctx = fx.setup_published_plan_with_rep(api, tier="B", planned_sample_units=20)
        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        territory = get_success_data(
            api.get_territory(
                ctx["territory"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert territory["alignment_posture"] == "LOCKED"
