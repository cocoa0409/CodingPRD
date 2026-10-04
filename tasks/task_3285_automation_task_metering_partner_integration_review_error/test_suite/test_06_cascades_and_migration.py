"""Cascading side effects: auto-pause, snapshot demotion, and version migration."""
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    setup_basic_scenario, setup_snapshot_scenario, declare_endpoint,
    publish_integration_version, force_reauth, dispatch_run,
    ApiErrorId, make_member_headers,
)


class TestSoftCapCascade:
    def test_failed_soft_cap_charge_pauses_the_workflow_at_the_soft_cap(self, api):
        """PRD §3.3: "transitioning the workflow from `ACTIVE` to `PAUSED`, setting
        `pause_reason` to `AUTO_SOFT_CAP`, and marking the offending action `SKIPPED`
        with its task released unconsumed."

        Design: Difficulty/transitive_cascade/tc_charge_pauses_workflow_then_expires_connection_then_blocks_migration
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=False)
        res = dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"])
        validate_error(res, ApiErrorId.ERR_TASK_ALLOWANCE_EXHAUSTED.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "PAUSED"
        assert workflow["pause_reason"] == "AUTO_SOFT_CAP"

    def test_soft_cap_charge_consumes_no_task(self, api):
        """PRD §3.3: "If the charge would push `tasks_used_current` beyond
        `task_allowance` and the account's `overage_enabled` is false, the request is
        refused with `ERR_TASK_ALLOWANCE_EXHAUSTED` (HTTP 402) and no task is consumed."

        Design: Corner/errors/err_run_over_allowance_returns_payment_required
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=False)
        res = dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"])
        validate_error(res, ApiErrorId.ERR_TASK_ALLOWANCE_EXHAUSTED.value)
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 0


class TestSnapshotDemotion:
    def test_refresh_cap_exhaustion_demotes_a_pinned_snapshot(self, api):
        """PRD §3.6: "every workflow snapshot that pins this connection and is currently
        `CURRENT` is set to `MIGRATION_REQUIRED`"

        Design: Difficulty/transitive_cascade/tc_charge_pauses_workflow_then_expires_connection_then_blocks_migration
        """
        scenario = setup_snapshot_scenario(account_name="Snap Co")
        assert scenario["snapshot"]["status"] == "CURRENT"
        force_reauth(scenario["connection"]["id"], scenario["member"]["id"])
        snapshot = get_success_data(
            api_client.get_workflow_version(scenario["snapshot"]["id"], scenario["owner_headers"]))
        assert snapshot["status"] == "MIGRATION_REQUIRED"

    def test_low_coverage_revision_demotes_a_pinned_snapshot(self, api):
        """PRD §3.8: "The first is a partner publishing a revision whose
        `schema_coverage` is below 1.0 while the integration is referenced by at least
        one snapshot still in `CURRENT`"

        Design: Difficulty/cross_entity_state_dependency/cx_migrate_depends_on_integration_version_schema_coverage
        """
        scenario = setup_snapshot_scenario(account_name="Migrate Co")
        integration = scenario["integration"]
        declare_endpoint(integration["id"], "/v1/gap", has_response_schema=False)
        revision = publish_integration_version(integration["id"], 2)
        assert revision["schema_coverage"] < 1.0
        snapshot = get_success_data(
            api_client.get_workflow_version(scenario["snapshot"]["id"], scenario["owner_headers"]))
        assert snapshot["status"] == "MIGRATION_REQUIRED"

    def test_reauthorization_returns_a_demoted_snapshot_to_current(self, api):
        """PRD §3.8: "a credential-triggered demotion melts away on its own the moment
        the owner reauthorizes the connection."

        Design: Difficulty/transitive_cascade/tc_charge_pauses_workflow_then_expires_connection_then_blocks_migration
        """
        scenario = setup_snapshot_scenario(account_name="Reauth Co")
        force_reauth(scenario["connection"]["id"], scenario["member"]["id"])
        member_headers = make_member_headers(scenario["member"]["id"])
        get_success_data(api_client.reauthorize_connection(scenario["connection"]["id"],
                                                           member_headers))
        snapshot = get_success_data(
            api_client.get_workflow_version(scenario["snapshot"]["id"], scenario["owner_headers"]))
        assert snapshot["status"] == "CURRENT"


class TestMigration:
    def test_migrate_refused_while_the_snapshot_is_current(self, api):
        """PRD §3.8: "The snapshot itself must currently be `MIGRATION_REQUIRED`, and no
        action of its workflow may be mid-flight in status `RUNNING`; a snapshot that is
        not required for migration, or one whose workflow has an action running, is
        refused with `ERR_WORKFLOW_VERSION_NOT_MIGRATABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/cx_migrate_depends_on_integration_version_schema_coverage
        """
        scenario = setup_snapshot_scenario(account_name="Migrate Co")
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        res = api_client.migrate_workflow_version(
            scenario["workflow"]["id"],
            {"target_integration_version_id": scenario["revision"]["id"],
             "expected_workflow_version": workflow["version"]},
            scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_WORKFLOW_VERSION_NOT_MIGRATABLE.value)

    def test_migrate_succeeds_once_a_low_coverage_revision_requires_it(self, api):
        """PRD §3.8: "the snapshot undergoes the `MIGRATION_REQUIRED → MIGRATED`
        transition, the workflow's version advances, and every action of the workflow is
        refreshed against the target revision"

        Design: Difficulty/cross_entity_state_dependency/cx_migrate_depends_on_integration_version_schema_coverage
        """
        # The snapshot pins a fully-covered revision; a schema-less endpoint then
        # drags the integration to 0.80 and the published release is below 1.0,
        # which demotes the pinned snapshot (PRD §3.8) without dropping under the
        # 0.8 bar the migration itself applies.
        scenario = setup_basic_scenario(
            account_name="Migrate Co",
            endpoints=[("/v1/op1", True), ("/v1/op2", True),
                       ("/v1/op3", True), ("/v1/op4", True)],
            snapshot=True, activate=True)
        integration = scenario["integration"]
        declare_endpoint(integration["id"], "/v1/op5", has_response_schema=False)
        target_revision = publish_integration_version(integration["id"], 2)
        assert target_revision["schema_coverage"] == 0.8
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        res = api_client.migrate_workflow_version(
            scenario["workflow"]["id"],
            {"target_integration_version_id": target_revision["id"],
             "expected_workflow_version": workflow["version"]},
            scenario["owner_headers"])
        migrated = validate_success(res, 200)
        assert migrated["status"] == "MIGRATED"