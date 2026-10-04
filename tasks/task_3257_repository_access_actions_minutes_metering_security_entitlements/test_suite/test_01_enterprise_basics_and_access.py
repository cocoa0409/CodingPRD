"""Enterprise creation defaults, auth header validation, RBAC denials,
immediate read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_enterprise,
    create_enterprise_payload,
    create_organization_payload,
    create_repository_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]
RA = TEST_USERS["runner_agent_headers"]


class TestEnterpriseDefaults:
    def test_enterprise_creation_applies_pat_and_anchor_defaults(self, api):
        """PRD §3.1: "the request may also pin `pat_policy` (one of
        `UNRESTRICTED`, `ADMIN_APPROVAL_REQUIRED`, `DISALLOWED`, defaulting to
        `UNRESTRICTED`) and `billing_cycle_anchor_day` (an integer from 1 to 28
        naming the day of month on which billing counters reset, defaulting to 1).
        Newly created enterprises carry `sso_enforcement` of `DISABLED`,
        `used_seats` of 0, and `audit_log_stream_status` of `INACTIVE`."

        Design: Corner/entities/enterprise_creation_applies_defaults
        """
        ent = create_enterprise(purchased_seats=10)
        data = validate_success(api.get_enterprise(ent["id"], EA))
        assert data["pat_policy"] == "UNRESTRICTED"
        assert data["billing_cycle_anchor_day"] == 1
        assert data["used_seats"] == 0
        assert data["sso_enforcement"] == "DISABLED"
        assert data["audit_log_stream_status"] == "INACTIVE"

    def test_enterprise_system_fields_minted_by_server(self, api):
        """PRD §2.4: "Every persistent resource carries an `id` field: a
        server-minted UUID with no type prefix." PRD §2.4: "`version` (an integer
        starting at 1 and incremented on every mutation)". PRD §2.7: "At server
        startup the clock reads exactly `2026-09-01T00:00:00Z` and continues to
        do so until it is explicitly advanced; the server does not fall back to
        wall-clock time."

        Design: Corner/entities/system_fields_ignored_on_create
        """
        resp = api.create_enterprise(
            create_enterprise_payload(name="E1", purchased_seats=5), EA
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert data["version"] == 1
        assert data["created_at"].startswith("2026-09-01T00:00:00"), (
            f"created_at must be stamped from the logical clock default, got {data['created_at']}"
        )


class TestOrganizationAllowances:
    def test_organization_enterprise_tier_allowances_computed(self, api):
        """PRD §3.2: "`included_actions_minutes` is 500 on `FREE`, 3000 on
        `TEAM`, and 50000 on `ENTERPRISE`. `included_storage_gb` is half a
        gigabyte on `FREE` (internally stored as 500 megabyte units), 2
        gigabytes on `TEAM`, and 50 gigabytes on `ENTERPRISE`.
        `outside_collaborator_limit` is 10 on `FREE`, 100 on `TEAM`, and 1000 on
        `ENTERPRISE`."

        Design: Corner/entities/organization_allowances_computed_from_plan_tier
        """
        ent = create_enterprise(purchased_seats=10)
        resp = api.create_organization(
            create_organization_payload(ent["id"], login="org1", plan_tier="ENTERPRISE"), EA
        )
        data = validate_success(resp, expected_status=201)
        assert data["included_actions_minutes"] == 50000
        assert data["included_storage_gb"] == 50
        assert data["outside_collaborator_limit"] == 1000

    def test_organization_creation_effects_immediately_visible(self, api):
        """PRD §3.2: "`included_actions_minutes` is 500 on `FREE`, 3000 on
        `TEAM`, and 50000 on `ENTERPRISE`." PRD §2.4: "`version` (an integer
        starting at 1 and incremented on every mutation)".

        Design: Corner/consistency_model/immediate_visibility_of_mutation
        """
        ent = create_enterprise(purchased_seats=5)
        resp = api.create_organization(
            create_organization_payload(ent["id"], login="org1", plan_tier="FREE"), EA
        )
        validate_success(resp, expected_status=201)
        org_id = resp.json()["data"]["id"]
        data = validate_success(api.get_organization(org_id, EA))
        assert data["included_actions_minutes"] == 500
        assert data["version"] == 1


class TestRepositoryDefaults:
    def test_repository_visibility_defaults_private(self, api):
        """PRD §3.5: "An `OrgAdmin` creates a repository by supplying
        `organization_id`, a `name` unique within the organization, and an
        optional `visibility` of `PRIVATE`, `INTERNAL`, or `PUBLIC`, defaulting
        to `PRIVATE`."

        Design: Corner/entities/repository_visibility_default_private
        """
        ent = create_enterprise(purchased_seats=5)
        resp = api.create_organization(
            create_organization_payload(ent["id"], login="org1"), EA
        )
        org = validate_success(resp, expected_status=201)
        data = validate_success(
            api.create_repository(create_repository_payload(org["id"], name="r1"), OA),
            expected_status=201,
        )
        assert data["visibility"] == "PRIVATE"


class TestNotFoundAndAuth:
    def test_get_enterprise_not_found(self, api):
        """PRD §2.4: "the enterprise is resolved first (yielding
        `ERR_ENTERPRISE_NOT_FOUND`)". PRD §5: ERR_ENTERPRISE_NOT_FOUND → 404.

        Design: Corner/entities/get_enterprise_not_found
        """
        resp = api.get_enterprise(NON_EXISTENT_UUID, EA)
        validate_error(resp, ApiErrorId.ERR_ENTERPRISE_NOT_FOUND)

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.get_enterprise(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRbacDenials:
    def test_org_admin_cannot_drive_sso_transition(self, api):
        """PRD §2.1: "Once the headers are well-formed, the role is matched
        against the endpoint's authorized role list; a role that is not listed
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4:
        POST /enterprises/{enterpriseId}/sso/transition is authorized for
        EnterpriseAdmin only.

        Design: Corner/rbac/org_admin_cannot_enforce_sso
        """
        ent = create_enterprise(purchased_seats=5)
        resp = api.sso_transition(ent["id"], "CONFIGURE", OA)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_runner_agent_cannot_create_repository(self, api):
        """PRD §2.1: "a role that is not listed is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4: POST /repositories
        is authorized for OrgAdmin only.

        Design: Corner/rbac/runner_agent_cannot_create_repositories
        """
        ent = create_enterprise(purchased_seats=5)
        resp = api.create_organization(
            create_organization_payload(ent["id"], login="org1"), EA
        )
        org = validate_success(resp, expected_status=201)
        resp = api.create_repository(
            create_repository_payload(org["id"], name="r1"), RA
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
