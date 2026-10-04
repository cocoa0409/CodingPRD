"""Validation precedence, folder rules and optimistic concurrency control."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    setup_basic_scenario, setup_team, setup_snapshot_scenario,
    create_folder, register_member, create_connection, create_workflow,
    create_integration, expire_token, publish_integration_version, declare_endpoint,
    ApiErrorId, make_member_headers, validate_paginated, TEST_USERS,
)

PARTNER = TEST_USERS["partner_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


class TestValidationPrecedence:
    def test_token_expiry_is_reported_before_allowance_exhaustion(self, api):
        """PRD §2.13: "Of the business gates, the safety rules come before the fiscal
        ones, so a submission against a non-`OAUTH2` integration reports
        `ERR_AUTH_METHOD_NOT_OAUTH2` rather than the coverage shortfall that may also be
        present, and a run charge evaluated against an expired credential reports
        `ERR_CONNECTION_TOKEN_EXPIRED` rather than an allowance complaint."

        Design: Difficulty/priority_pair_validation_conflict/pp_token_expired_beats_allowance_exhausted
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=False)
        expire_token(scenario["connection"]["id"])
        res = api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                     scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_CONNECTION_TOKEN_EXPIRED.value)

    def test_expired_credential_charge_consumes_no_task(self, api):
        """PRD §2.13: "a request can violate several rules at once and only one error is
        returned."

        Design: Difficulty/priority_pair_validation_conflict/pp_token_expired_beats_allowance_exhausted
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=False)
        expire_token(scenario["connection"]["id"])
        api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                scenario["owner_headers"])
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 0
        assert account["overage_amount_cents"] == 0

    def test_foreign_folder_takes_precedence_over_duplicate_position(self, api):
        """PRD §2.13: "then resource state, then business-safety and fiscal rules, and
        only lastly the uniqueness and consistency constraints."

        Design: Difficulty/priority_pair_validation_conflict/pp_folder_permitted_beats_duplicate_action_position
        """
        team = setup_team()
        account = team["account"]
        owner = team["owner"]
        member = team["member"]
        member_headers = make_member_headers(member["id"])
        integration = create_integration()
        connection = create_connection(account["id"], integration["id"], member["id"])
        folder = create_folder(account["id"], "Ops", owner["id"])
        workflow = create_workflow(account["id"], folder["id"], owner["id"])
        api_client.create_action(
            workflow["id"],
            {"position": 1, "integration_id": integration["id"],
             "connection_id": connection["id"], "action_type": "send_message"},
            team["owner_headers"])
        res = api_client.create_action(
            workflow["id"],
            {"position": 1, "integration_id": integration["id"],
             "connection_id": connection["id"], "action_type": "send_message"},
            member_headers)
        validate_error(res, ApiErrorId.ERR_FOLDER_NOT_PERMITTED.value)
        actions = get_success_data(api_client.list_workflow_actions(workflow["id"],
                                                                    team["owner_headers"]))
        assert len(actions) == 1

    def test_action_using_another_accounts_connection_is_refused(self, api):
        """PRD §3.1: "The connection named must belong to the same account that owns the
        workflow; an action that would wire a workflow to another account's credentials
        is refused with `ERR_CONNECTION_ACCOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/val_action_connection_account_mismatch_rejected
        """
        scenario = setup_basic_scenario(activate=False)
        other = setup_basic_scenario(account_name="Other Co", activate=False)
        res = api_client.create_action(
            scenario["workflow"]["id"],
            {"position": 2, "integration_id": scenario["integration"]["id"],
             "connection_id": other["connection"]["id"], "action_type": "send_message"},
            scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_CONNECTION_ACCOUNT_MISMATCH.value)

    def test_action_position_collision_within_the_same_workflow(self, api):
        """PRD §3.1: "Position is 1-based, must be at least 1, and must be unique within
        the workflow — a second action at an occupied position is refused with
        `ERR_DUPLICATE_ACTION_POSITION` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/pp_folder_permitted_beats_duplicate_action_position
        """
        scenario = setup_basic_scenario(activate=False)
        res = api_client.create_action(
            scenario["workflow"]["id"],
            {"position": 1, "integration_id": scenario["integration"]["id"],
             "connection_id": scenario["connection"]["id"], "action_type": "send_message"},
            scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTION_POSITION.value)


class TestFolderRules:
    def test_duplicate_folder_name_within_one_account_is_refused(self, api):
        """PRD §3.1: "the name must be non-empty and unique within that account, and a
        second folder with the same name in the same account is refused with
        `ERR_DUPLICATE_FOLDER_NAME` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/bp_duplicate_folder_name_vs_empty_collection
        """
        team = setup_team()
        create_folder(team["account"]["id"], "Ops", team["owner"]["id"])
        res = api_client.create_folder(
            {"account_id": team["account"]["id"], "name": "Ops"}, team["owner_headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FOLDER_NAME.value)
        folders, meta = validate_paginated(api_client.list_folders(
            team["owner_headers"], params={"account_id": team["account"]["id"]}))
        assert meta["total_count"] == 1

    def test_repeated_folder_name_reports_a_conflict(self, api):
        """PRD §3.1: "a second folder with the same name in the same account is refused
        with `ERR_DUPLICATE_FOLDER_NAME` (HTTP 409)."

        Design: Corner/validations/val_duplicate_folder_name_returns_conflict
        """
        team = setup_team()
        create_folder(team["account"]["id"], "Ops", team["owner"]["id"])
        res = api_client.create_folder(
            {"account_id": team["account"]["id"], "name": "Ops"}, team["owner_headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FOLDER_NAME.value)
        folders, meta = validate_paginated(api_client.list_folders(
            team["owner_headers"], params={"account_id": team["account"]["id"]}))
        assert meta["total_count"] == 1

    def test_first_folder_of_a_fresh_account_is_accepted(self, api):
        """PRD §3.1: "the name must be non-empty and unique within that account, and a
        second folder with the same name in the same account is refused with
        `ERR_DUPLICATE_FOLDER_NAME` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/bp_duplicate_folder_name_vs_empty_collection
        """
        first_account = get_success_data(api_client.create_account(
            {"name": "Other", "plan_code": "TEAM_PRO", "task_allowance": 5,
             "closer_cost_per_task_cents": 1, "opening_cost_per_task_cents": 1,
             "overage_enabled": True}, PLATFORM), 201)
        member = register_member(first_account["id"], "a@b.test", "A B", "OWNER")
        created = create_folder(first_account["id"], "Ops", member["id"])
        assert created["name"] == "Ops"

    def test_folder_creation_without_an_account_is_refused(self, api):
        """PRD §2.12: "Where a create operation accepts both a parent identifier in
        its path and a reference to some other resource in its body, the path parent is
        resolved first."

        Design: Corner/entities/ent_folder_create_missing_required_account_id_returns_400
        """
        team = setup_team()
        res = api_client.create_folder({"name": "No Owner"}, team["owner_headers"])
        assert res.status_code >= 400
        assert res.json().get("response_type") == "error"


class TestOptimisticConcurrency:
    def test_stale_account_version_on_action_charge_is_rejected(self, api):
        """PRD §2.8: "If another writer has advanced the account's version since the
        client read it — because a cascade such as an automatic workflow pause or an
        overage recompute already bumped it, or because a competing charge did — the
        request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_action_charge_rejected
        """
        scenario = setup_basic_scenario()
        stale_version = scenario["account"]["version"]
        # Activation advanced the account's version, so the captured one is stale.
        res = api_client.simulate_action_charge(
            {"account_id": scenario["account"]["id"], "action_id": scenario["action"]["id"],
             "attempt_no": 1, "service_latency_ms": 10,
             "expected_account_version": stale_version},
            PLATFORM)
        validate_error(res, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 0

    def test_stale_workflow_version_on_migration_is_rejected(self, api):
        """PRD §2.8: "A mismatch means an activation cascade or an automatic pause has
        already advanced the workflow since the client looked at it, and the migration is
        rejected with `ERR_STALE_WORKFLOW_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_workflow_version_on_migrate_rejected
        """
        scenario = setup_snapshot_scenario(account_name="OCC Co")
        integration = scenario["integration"]
        declare_endpoint(integration["id"], "/v1/gap", has_response_schema=False)
        publish_integration_version(integration["id"], 2)
        target = publish_integration_version(integration["id"], 3)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        stale_version = workflow["version"]
        # A pause/resume pair advances the workflow's version past the captured one.
        api_client.pause_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        api_client.resume_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        res = api_client.migrate_workflow_version(
            scenario["workflow"]["id"],
            {"target_integration_version_id": target["id"],
             "expected_workflow_version": stale_version},
            scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_STALE_WORKFLOW_VERSION.value)
        snapshot = get_success_data(
            api_client.get_workflow_version(scenario["snapshot"]["id"], scenario["owner_headers"]))
        assert snapshot["status"] == "MIGRATION_REQUIRED"