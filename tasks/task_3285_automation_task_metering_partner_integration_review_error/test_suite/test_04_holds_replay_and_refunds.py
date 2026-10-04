"""Held tasks, manual replay, and the compensation register."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_basic_scenario, hold_run, recover_downstream, account_tasks,
    validate_paginated,
)


def _hold_scenario(allowance=100):
    scenario = setup_basic_scenario(allowance=allowance)
    run = hold_run(scenario["workflow"]["id"], scenario["owner"]["id"])
    return scenario, run


class TestHeldRun:
    def test_hold_run_marks_the_run_held_and_names_the_action(self, api):
        """PRD §3.5: "a held action ends its run harmlessly rather than failing it, and
        the run that held an action is marked `HELD` and names that action through
        `held_action_id`."

        Design: Difficulty/non_linear_state_machine/nl_workflow_action_held_replay_cycle
        """
        scenario, run = _hold_scenario()
        assert run["status"] == "HELD"
        assert run["held_action_id"] == scenario["action"]["id"]

    def test_held_run_has_charged_the_action_before_releasing_it(self, api):
        """PRD §3.5: "the account has already been charged for the positions the run
        reached."

        Design: Difficulty/compensating_invariant/ci_replay_refund_restores_account_task_count
        """
        scenario, run = _hold_scenario()
        assert run["status"] == "HELD"
        assert account_tasks(scenario) == 8

    def test_held_run_mints_an_unconsumed_refund_grant(self, api):
        """PRD §3.5: "the platform immediately mints a `RefundGrant` of kind `REFUND`
        against the run, with `refunded_at` set to the current instant and
        `consuming_job_event_id` deliberately left null so the grant is visibly
        unconsumed."

        Design: Corner/cross_cutting_complexity_layers/dfl_replay_consumes_refund_grant_derived_fields
        """
        scenario, run = _hold_scenario()
        grants, meta = validate_paginated(api_client.list_refund_grants(
            scenario["owner_headers"], params={"run_id": run["id"]}))
        assert meta["total_count"] >= 1
        assert grants[0]["kind"] == "REFUND"
        assert grants[0]["consuming_job_event_id"] is None


class TestReplayCompensation:
    def test_replay_after_recovery_reopens_the_held_action(self, api):
        """PRD §3.5: "The run must contain an action in status `HELD`, the connection
        must genuinely be back to `CONNECTED`, and an unconsumed grant of kind `REFUND`
        with a null `consuming_job_event_id` must exist for that run; only then does the
        action undergo the `HELD → RUNNING` transition and record a `REPLAYED` event."

        Design: Difficulty/non_linear_state_machine/nl_workflow_action_held_replay_cycle
        """
        scenario, _ = _hold_scenario()
        recover_downstream(scenario["connection"]["id"])
        res = api_client.replay_action(scenario["action"]["id"], scenario["owner_headers"])
        replayed = validate_success(res, 200)
        assert replayed["status"] == "RUNNING"

    def test_job_events_record_the_hold_then_the_replay(self, api):
        """PRD §3.4: "an `outcome` drawn from `SUCCEEDED`, `FAILED_RETRYABLE`,
        `FAILED_PERMANENT`, `HELD`, `REPLAYED` or `SKIPPED`"

        Design: Difficulty/non_linear_state_machine/nl_workflow_action_held_replay_cycle
        """
        scenario, _ = _hold_scenario()
        recover_downstream(scenario["connection"]["id"])
        api_client.replay_action(scenario["action"]["id"], scenario["owner_headers"])
        events = get_success_data(
            api_client.list_action_events(scenario["action"]["id"], scenario["owner_headers"]))
        outcomes = [e["outcome"] for e in events]
        assert "HELD" in outcomes
        assert "REPLAYED" in outcomes
        assert outcomes.index("HELD") < outcomes.index("REPLAYED")

    def test_replay_consumes_the_oldest_unconsumed_refund_grant(self, api):
        """PRD §3.5: "the oldest unconsumed refund grant for the run is updated to kind
        `REPLAY`, stamped with `consumed_at` at the current instant, and pointed at the
        newly created `REPLAYED` event through `consuming_job_event_id`."

        Design: Corner/cross_cutting_complexity_layers/dfl_replay_consumes_refund_grant_derived_fields
        """
        scenario, run = _hold_scenario()
        recover_downstream(scenario["connection"]["id"])
        api_client.replay_action(scenario["action"]["id"], scenario["owner_headers"])
        grants, meta = validate_paginated(api_client.list_refund_grants(
            scenario["owner_headers"], params={"run_id": run["id"]}))
        assert meta["total_count"] >= 1
        assert grants[0]["consuming_job_event_id"] is not None
        assert grants[0]["consumed_at"] is not None
        assert all(g["consuming_job_event_id"] is not None for g in grants)

    def test_replay_restores_the_account_task_count_with_zero_drift(self, api):
        """PRD §3.5: "the customer should neither lose the work nor pay for it."

        Design: Difficulty/compensating_invariant/ci_replay_refund_restores_account_task_count
        """
        scenario, _ = _hold_scenario()
        recover_downstream(scenario["connection"]["id"])
        res = api_client.replay_action(scenario["action"]["id"], scenario["owner_headers"])
        assert validate_success(res, 200)["status"] == "RUNNING"
        assert account_tasks(scenario) == 0