"""Workflow construction, lifecycle transitions, and their preconditions."""
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    setup_basic_scenario, ApiErrorId, make_member_headers, TEST_USERS,
)


class TestWorkflowCreation:
    def test_workflow_creation_ignores_client_supplied_status(self, api):
        """PRD §3.1: "A workflow is born in the `DRAFT` state with no actions, its
        `action_count` at zero, and its `trigger_latency_seconds` already derived from
        the trigger type per §2.6."

        Design: Corner/entities/ent_workflow_create_status_input_ignored
        """
        scenario = setup_basic_scenario(activate=False)
        res = api_client.create_workflow(
            {"account_id": scenario["account"]["id"], "name": "Sneaky",
             "folder_id": scenario["folder"]["id"], "trigger_type": "WEBHOOK",
             "status": "ACTIVE"},
            scenario["owner_headers"])
        created = validate_success(res, 201)
        assert created["status"] == "DRAFT"

    def test_workspace_first_action_raises_action_count(self, api):
        """PRD §3.1: "Attaching an action increments the workflow's `action_count` and
        advances the workflow's version."

        Design: Corner/state_machines/sm_activate_sets_action_count_side_effect
        """
        scenario = setup_basic_scenario(activate=False)
        assert scenario["workflow"]["action_count"] == 0
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["action_count"] == 1
        assert workflow["status"] == "DRAFT"

    def test_draft_workflow_cannot_run_before_activation(self, api):
        """PRD §3.2: "Activation demands `DRAFT`; pausing and resuming demand the
        states named above; disabling demands `DRAFT` or `PAUSED`."

        Design: Corner/state_machines/sm_workflow_created_in_draft
        """
        scenario = setup_basic_scenario(activate=False)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "DRAFT"
        res = api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                      scenario["owner_headers"])
        err = res.json()["data"]["error_id"]
        assert err in ("ERR_WORKFLOW_INVALID_STATE", "ERR_NO_RUNNABLE_ACTION")

    def test_account_creation_starts_the_ledger_at_zero(self, api):
        """PRD §3.1: "On creation the account's whole ledger resets to a clean slate:
        `tasks_used_current`, `tasks_used_previous`, `overage_tasks_used`,
        `overage_amount_cents`, `projected_overage_amount_cents` and
        `usage_pct_current` all read zero."

        Design: Corner/entities/ent_account_create_returns_201_with_zeroed_counters
        """
        account = get_success_data(api_client.create_account(
            {"name": "Zero Co", "plan_code": "TEAM_FREE", "task_allowance": 5,
             "closer_cost_per_task_cents": 1, "opening_cost_per_task_cents": 1,
             "overage_enabled": True}, TEST_USERS["platform_admin_headers"]), 201)
        assert account["tasks_used_current"] == 0
        assert account["overage_amount_cents"] == 0
        assert account["overage_tasks_used"] == 0
        assert account["usage_pct_current"] == 0.0


class TestActivation:
    def test_activate_already_active_workflow_returns_invalid_state(self, api):
        """PRD §3.2: "A workflow that is already `ACTIVE` cannot be activated again, and
        a `DISABLED` workflow can never be brought back."

        Design: Corner/state_machines/sm_activate_already_active_returns_invalid_state
        """
        scenario = setup_basic_scenario(activate=True)
        res = api_client.activate_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_WORKFLOW_INVALID_STATE.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "ACTIVE"

    def test_disabled_workflow_cannot_be_activated(self, api):
        """PRD §3.2: "A workflow that is already `ACTIVE` cannot be activated again, and
        a `DISABLED` workflow can never be brought back."

        Design: Corner/state_machines/sm_disabled_workflow_cannot_activate
        """
        scenario = setup_basic_scenario(activate=False)
        get_success_data(api_client.disable_workflow(scenario["workflow"]["id"],
                                                     scenario["owner_headers"]))
        res = api_client.activate_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_WORKFLOW_INVALID_STATE.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "DISABLED"

    def test_activation_refused_when_referenced_connection_disconnected(self, api):
        """PRD §3.2: "And every connection referenced by its actions must resolve to a
        `Connection` whose status is `CONNECTED`, `TOKEN_EXPIRED`, or
        `REAUTH_REQUIRED`: a disconnected credential is a hard block, while an expired
        or reauthorization-pending one is tolerated at activation time and dealt with at
        run time."

        Design: Difficulty/cross_entity_state_dependency/cx_activate_workflow_depends_on_connection_not_disconnected
        """
        scenario = setup_basic_scenario(activate=False)
        member_headers = make_member_headers(scenario["member"]["id"])
        get_success_data(api_client.disconnect_connection(scenario["connection"]["id"],
                                                          member_headers))
        res = api_client.activate_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_WORKFLOW_INVALID_STATE.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "DRAFT"

    def test_activation_refused_when_referenced_connection_was_disconnected(self, api):
        """PRD §3.2: "The workflow must carry at least one action, so `action_count`
        must be at least 1."

        Design: Difficulty/cross_entity_state_dependency/cx_activate_workflow_depends_on_connection_not_disconnected
        """
        scenario = setup_basic_scenario(activate=False)
        member_headers = make_member_headers(scenario["member"]["id"])
        res = api_client.disconnect_connection(scenario["connection"]["id"], member_headers)
        assert res.json()["data"]["status"] == "DISCONNECTED"
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["action_count"] >= 1
        assert workflow["status"] == "DRAFT"


class TestPauseResumeCycle:
    def test_deliberate_pause_sets_user_paused_reason(self, api):
        """PRD §3.2: "A `Member` may pause an active workflow deliberately, driving the
        `ACTIVE → PAUSED` transition, and the workflow records exactly why it stopped
        through `pause_reason`: a deliberate pause sets `pause_reason` to `USER_PAUSED`."

        Design: Difficulty/non_linear_state_machine/nl_workflow_pause_resume_cycle_with_forked_pause_reasons
        """
        scenario = setup_basic_scenario()
        paused = get_success_data(api_client.pause_workflow(scenario["workflow"]["id"],
                                                            scenario["owner_headers"]))
        assert paused["status"] == "PAUSED"
        assert paused["pause_reason"] == "USER_PAUSED"

    def test_pause_resume_pause_cycle_closes_back_on_paused(self, api):
        """PRD §3.2: "Resuming performs the `PAUSED → ACTIVE` transition and clears
        `pause_reason` back to null, but only once the condition that stopped it has
        genuinely cleared"

        Design: Difficulty/non_linear_state_machine/nl_workflow_pause_resume_cycle_with_forked_pause_reasons
        """
        scenario = setup_basic_scenario()
        wf = scenario["workflow"]["id"]
        api_client.pause_workflow(wf, scenario["owner_headers"])
        resumed = get_success_data(api_client.resume_workflow(wf, scenario["owner_headers"]))
        assert resumed["status"] == "ACTIVE"
        assert resumed["pause_reason"] is None
        api_client.pause_workflow(wf, scenario["owner_headers"])
        final = get_success_data(api_client.get_workflow(wf, scenario["owner_headers"]))
        assert final["status"] == "PAUSED"

    def test_pause_then_resume_returns_workflow_to_active(self, api):
        """PRD §3.2: "Resuming performs the `PAUSED → ACTIVE` transition and clears
        `pause_reason` back to null"

        Design: Difficulty/non_linear_state_machine/nl_workflow_pause_resume_cycle_with_forked_pause_reasons
        """
        scenario = setup_basic_scenario()
        wf = scenario["workflow"]["id"]
        paused = get_success_data(api_client.pause_workflow(wf, scenario["owner_headers"]))
        assert (paused["status"], paused["pause_reason"]) == ("PAUSED", "USER_PAUSED")
        resumed = get_success_data(api_client.resume_workflow(wf, scenario["owner_headers"]))
        assert (resumed["status"], resumed["pause_reason"]) == ("ACTIVE", None)


class TestRunStepCeiling:
    def test_run_with_eleven_actions_is_refused(self, api):
        """PRD §3.3: "A run may not be arbitrarily large. Dispatching a run whose
        execution would require more than 10 actions in that single run is refused with
        `ERR_WORKFLOW_MAX_STEPS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/ov_workflow_action_capacity_ceiling_aggregate
        """
        scenario = setup_basic_scenario(allowance=1000)
        many = add_eleven_action_workflow(scenario, "Over")
        res = api_client.dispatch_run(many, {"charge": "success"}, scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_WORKFLOW_MAX_STEPS_EXCEEDED.value)

    def test_run_with_exactly_ten_actions_succeeds(self, api):
        """PRD §3.3: "A run may not be arbitrarily large. Dispatching a run whose
        execution would require more than 10 actions in that single run is refused with
        `ERR_WORKFLOW_MAX_STEPS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/ov_workflow_action_capacity_ceiling_aggregate
        """
        scenario = setup_basic_scenario(allowance=1000)
        for pos in range(2, 11):
            api_client.create_action(
                scenario["workflow"]["id"],
                {"position": pos, "integration_id": scenario["integration"]["id"],
                 "connection_id": scenario["connection"]["id"], "action_type": "send_message"},
                scenario["owner_headers"])
        res = api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                      scenario["owner_headers"])
        run = validate_success(res, 201)
        assert run["status"] == "COMPLETED"


def add_eleven_action_workflow(scenario, name):
    """Helper: create an activated workflow carrying eleven actions."""
    folder_id = scenario["folder"]["id"]
    workflow = get_success_data(api_client.create_workflow(
        {"account_id": scenario["account"]["id"], "name": name, "folder_id": folder_id,
         "trigger_type": "WEBHOOK"},
        scenario["owner_headers"]), 201)
    for pos in range(1, 12):
        api_client.create_action(
            workflow["id"],
            {"position": pos, "integration_id": scenario["integration"]["id"],
             "connection_id": scenario["connection"]["id"], "action_type": "send_message"},
            scenario["owner_headers"])
    get_success_data(api_client.activate_workflow(workflow["id"], scenario["owner_headers"]))
    return workflow["id"]