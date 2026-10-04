"""Role competence, unauthenticated access, and shared entity properties."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    setup_basic_scenario, setup_team, register_member, create_integration,
    declare_endpoint, dispatch_run, ApiErrorId,
    anonymous_headers, validate_paginated, NON_EXISTENT_UUID, TEST_USERS,
)

REVIEWER = TEST_USERS["reviewer_headers"]
PARTNER = TEST_USERS["partner_admin_headers"]


class TestRoleCompetence:
    def test_partner_admin_cannot_pause_a_member_workflow(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the operation
        it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_partner_admin_cannot_activate_workflow_returns_forbidden
        """
        scenario = setup_basic_scenario()
        res = api_client.pause_workflow(scenario["workflow"]["id"], PARTNER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "ACTIVE"

    def test_reviewer_cannot_submit_an_integration(self, api):
        """PRD §2.1: "`PartnerAdmin` is the only role that may draft an integration and
        declare its endpoints, submit it for review, or publish a new revision."

        Design: Corner/rbac/rbac_reviewer_cannot_submit_integration_returns_forbidden
        """
        integration = create_integration()
        declare_endpoint(integration["id"], "/v1/op1", has_response_schema=True)
        res = api_client.submit_integration(integration["id"], REVIEWER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        unchanged = get_success_data(api_client.get_integration(integration["id"], PARTNER))
        assert unchanged["review_status"] == "DRAFT"

    def test_request_without_a_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or that presents an
        `X-User-Role` value outside those four, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/rbac_unauthenticated_missing_role_header_returns_401
        """
        team = setup_team()
        res = api_client.get_account(team["account"]["id"], anonymous_headers())
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestUnknownResources:
    def test_unknown_account_id_is_reported_as_not_found(self, api):
        """PRD §2.12: "An unresolvable account is `ERR_ACCOUNT_NOT_FOUND`"

        Design: Corner/entities/ent_get_account_unknown_id_returns_not_found
        """
        team = setup_team()
        res = api_client.get_account(NON_EXISTENT_UUID, team["owner_headers"])
        validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


class TestEntityProperties:
    def test_new_member_mirrors_the_account_plan_code(self, api):
        """PRD §3.1: "Registration snapshots the account's current `plan_code` onto the
        member's own `plan_code` field"

        Design: Corner/entities/ent_member_register_snapshots_plan_code
        """
        team = setup_team()
        assert team["account"]["plan_code"] == "TEAM_PRO"
        member = register_member(team["account"]["id"], "snap@c1.test", "Snap Shot", "MEMBER")
        assert member["plan_code"] == "TEAM_PRO"

    def test_job_event_rows_carry_no_version_field(self, api):
        """PRD §2.10: "`FolderFolderGrant`, `JobEvent`, and `RefundGrant` are each
        declared without the composite: they carry only an `id` (a UUID) and a
        `created_at`, and they have neither an `updated_at` nor a `version` field."

        Design: Corner/entities/ent_job_event_has_no_version_field
        """
        scenario = setup_basic_scenario(trigger_type="WEBHOOK")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"])
        events, meta = validate_paginated(api_client.list_job_events(
            scenario["owner_headers"], params={"action_id": scenario["action"]["id"]}))
        assert meta["total_count"] >= 1
        assert "version" not in events[0]
        assert "updated_at" not in events[0]


class TestImmediateConsistency:
    def test_charge_is_visible_on_the_account_right_after_dispatch(self, api):
        """PRD §3.4: "A successful charge advances the account's version, because the
        account's derived fields moved"

        Design: Corner/consistency_model/cons_run_charge_visible_immediately_after_dispatch
        """
        scenario = setup_basic_scenario(trigger_type="POLLING")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 8
        assert account["version"] > scenario["account"]["version"]