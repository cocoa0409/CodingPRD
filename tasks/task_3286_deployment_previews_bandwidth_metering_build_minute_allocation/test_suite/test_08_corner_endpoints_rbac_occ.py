"""Corner-queue tests: endpoints, errors, rbac, cross_cutting_layers, consistency."""
from test_helpers import (
    ADMIN,
    BILLING,
    DEVELOPER,
    OWNER,
    VIEWER,
    WEBHOOK,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_deployment,
    create_deployment,
    create_domain,
    create_spend_cap,
    get_certificate,
    get_domain,
    get_project,
    list_domain_certificates,
    set_clock,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
)


class TestGetMissingDeployment:
    def test_get_missing_deployment_returns_not_found(self, api):
        """PRD §2.7: "the first segment that fails to resolve produces the
        corresponding not-found error (such as `ERR_TEAM_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`,
        `ERR_DOMAIN_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
        `ERR_ENV_VAR_NOT_FOUND`, `ERR_REDIRECT_NOT_FOUND`,
        `ERR_USAGE_PERIOD_NOT_FOUND`, `ERR_ALERT_RULE_NOT_FOUND`,
        `ERR_SPEND_CAP_NOT_FOUND`, or `ERR_MEMBER_NOT_FOUND`, each HTTP 404)"

        Design: Corner/endpoints/get_missing_deployment_returns_not_found
        """
        resp = api.get_deployment("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", VIEWER)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND)


class TestUsageSummaryComputedRead:
    def test_usage_summary_computed_read_matches_period(self, api):
        """PRD §3.7: "A computed per-team usage summary exposes the current
        open period's aggregates and projected bill to the same three roles."

        Design: Corner/endpoints/usage_summary_computed_read_matches_period
        """
        plan, team, project, period = setup_team_with_project_and_period(
            included_bandwidth_gb=0,
            bandwidth_tier1_rate_cents_per_gb=100,
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1_000_000_000, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        summary = validate_success(api.get_usage_summary(team["id"], BILLING))
        assert summary["bandwidth_bytes"] == 1_000_000_000
        assert summary["projected_bill_cents"] == 100


class TestDeploymentsListFilters:
    def test_deployments_list_filters_by_branch_and_status(self, api):
        """PRD §3.4: "Deployments can be listed with filters on `project_id`,
        `branch`, `status`, and `target`, and fetched individually, by any
        declared role."

        Design: Corner/endpoints/deployments_list_filters_by_branch_and_status
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        create_deployment(project["id"], branch="feat-b", commit_sha="bbb222")
        data = validate_success(api.list_deployments(
            VIEWER, params={"project_id": project["id"], "branch": "feat-a"},
        ))
        assert len(data) == 1
        assert data[0]["branch"] == "feat-a"


class TestSeatLimitExceededAtBoundary:
    def test_error_seat_limit_exceeded_at_boundary(self, api):
        """PRD §3.2: "Capacity is enforced before insertion: if the team's
        `seats_used` already equals its `seat_limit`, the add is rejected with
        `ERR_SEAT_LIMIT_EXCEEDED` (HTTP 422); the boundary is inclusive, so a
        team exactly at its limit cannot add even one more seat."

        Design: Corner/errors/error_seat_limit_exceeded_at_boundary
        """
        from test_helpers import create_plan, create_team, get_team
        create_plan(**{
            "tier": "HOBBY", "seat_limit": 1, "included_build_minutes": 100,
            "build_concurrency_limit": 1, "included_bandwidth_gb": 10,
            "included_invocations_millions": 1,
            "bandwidth_tier1_rate_cents_per_gb": 20,
            "bandwidth_tier2_rate_cents_per_gb": 10,
            "bandwidth_tier2_threshold_gb": 100,
            "invocation_rate_cents_per_million": 100,
            "seat_price_cents_monthly": 0, "overage_build_minute_rate_cents": 10,
        })
        team = create_team(plan_tier="HOBBY", name="Tiny")
        validate_success(api.add_member(
            team["id"], {"user_email": "a@x.com", "role": "DEVELOPER"}, OWNER,
        ), expected_status=201)
        resp = api.add_member(
            team["id"], {"user_email": "b@x.com", "role": "VIEWER"}, OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_LIMIT_EXCEEDED)
        assert get_team(team["id"])["seats_used"] == 1


class TestViewerCannotCreateProject:
    def test_viewer_cannot_create_project(self, api):
        """PRD §2.1: "`Viewer` — a read-only team member with access only to
        read (list and get) endpoints across the surface."
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/viewer_cannot_create_project
        """
        plan, team = setup_team_with_project()[:2]
        resp = api.create_project(
            team["id"], {"name": "web2", "production_branch": "main"}, VIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestDeveloperCannotManageSpendCaps:
    def test_developer_cannot_manage_spend_caps(self, api):
        """PRD §2.1: "`TeamBillingManager` — the billing manager. This role
        exclusively invoices closed usage periods and manages alert rules and
        spend caps"
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/developer_cannot_manage_spend_caps
        """
        plan, team = setup_team_with_project()[:2]
        resp = api.create_spend_cap(
            team["id"], {"cap_cents": 1000, "action": "ALERT_ONLY"}, DEVELOPER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestBillingManagerCannotRollback:
    def test_billing_manager_cannot_rollback(self, api):
        """PRD §2.1: "`TeamOwner` — the team owner. This role exclusively adds
        and removes members, archives and resumes projects, performs
        production rollbacks, renames or removes domains, and revokes
        certificates"
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/billing_manager_cannot_rollback
        """
        plan, team, project = setup_team_with_project()
        resp = api.rollback_project(project["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestTeamRoleCannotGitWebhook:
    def test_team_role_cannot_git_webhook(self, api):
        """PRD §2.1: "`SystemWebhook` — the git-integration and build-worker
        identity. It exclusively emits git events, starts builds, completes
        builds, and completes certificate issuance"
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/team_role_cannot_git_webhook
        """
        plan, team, project = setup_team_with_project()
        resp = api.create_git_event(
            {"project_id": project["id"], "branch": "feat-a",
             "git_ref": "refs/heads/feat-a", "commit_sha": "aaa111", "region": "IAD"},
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestOccDomainPatchStaleVersion:
    def test_occ_domain_patch_stale_version_rejected(self, api):
        """PRD §2.6: "A request to rename a domain must carry
        `expected_domain_version`, holding the domain `version` the client
        last observed. If the domain's current `version` no longer matches —
        for instance because a verification cascade has issued a certificate
        and legitimately rewritten the domain's `certificate_id` and `status`
        — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_domain_patch_stale_version_rejected
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        domain = create_domain(project["id"], name="example.com")
        dom_v = domain["version"]
        # verify SUCCESS spawns a certificate, which legitimately rewrites the domain
        validate_success(api.verify_domain(domain["id"], {"outcome": "SUCCESS"}, DEVELOPER))
        resp = api.update_domain(
            domain["id"],
            {"name": "www.example.com", "expected_domain_version": dom_v},
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_domain(domain["id"])["name"] == "example.com"


class TestOccProjectPatch:
    def test_occ_project_patch_current_version_succeeds_then_stale_fails(self, api):
        """PRD §2.6: "A request to update a project's configuration must carry
        `expected_project_version`, holding the project `version` the client
        last observed. If the project's current `version` no longer matches —
        because a promote, rollback, suspend, archive, or build-start cascade
        has legitimately rewritten the project between the client's read and
        this write — the update is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "a successful update increments the project's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_project_patch_current_version_succeeds_then_stale_fails
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        proj_v = project["version"]
        updated = validate_success(api.update_project(
            project["id"],
            {"preview_protection": "NONE", "expected_project_version": proj_v},
            OWNER,
        ))
        assert updated["version"] == proj_v + 1
        resp = api.update_project(
            project["id"],
            {"preview_protection": "TEAM_ONLY", "expected_project_version": proj_v},
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_project(project["id"])["preview_protection"] == "NONE"


class TestCertificateExpiryAndRenewal:
    def test_certificate_expiry_and_renewal_scheduled_action(self, api):
        """PRD §3.6: "Expiry is driven by the logical clock: when the clock
        reaches or passes a certificate's `not_after`, the certificate
        transitions `ACTIVE` → `EXPIRED`, the domain's `certificate_id` is
        cleared and the domain — identified to the certificate through its
        `domain_id` — transitions to `SUSPENDED`, and — only when the domain's
        `verification_status` is `VERIFIED` — the system automatically issues
        a renewal: a fresh certificate enters `ISSUING` with its
        `auto_renewed_from_id` pointing at the expired one."

        Design: Corner/cross_cutting_layers/certificate_expiry_and_renewal_scheduled_action
        """
        from test_helpers import setup_domain_with_active_certificate
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        domain, cert = setup_domain_with_active_certificate(project["id"], name="example.com")
        assert cert["status"] == "ACTIVE"
        set_clock("2026-12-01T00:00:00Z")
        assert get_certificate(cert["id"])["status"] == "EXPIRED"
        dom = get_domain(domain["id"])
        assert dom["status"] == "SUSPENDED"
        assert dom["certificate_id"] is None
        certs = list_domain_certificates(domain["id"])
        renewals = [c for c in certs if c["status"] == "ISSUING"]
        assert len(renewals) == 1
        assert renewals[0]["auto_renewed_from_id"] == cert["id"]


class TestClockDefaultFixedEpoch:
    def test_clock_default_is_fixed_epoch(self, api):
        """PRD §2.9: "At server startup the clock reads exactly
        `2026-09-01T00:00:00Z`, and before any clock-setting call it continues
        to read that default — the server never falls back to wall-clock
        time."
        PRD §3.6: "moves the certificate to `ACTIVE`, stamps `not_before` with
        the clock, and sets `not_after` ninety days later"

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_epoch
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        domain = create_domain(project["id"], name="example.com")
        validate_success(api.verify_domain(domain["id"], {"outcome": "SUCCESS"}, DEVELOPER))
        certs = list_domain_certificates(domain["id"])
        cert = validate_success(api.complete_certificate(certs[0]["id"], WEBHOOK))
        assert cert["not_before"].startswith("2026-09-01T00:00:00")
        assert cert["not_after"].startswith("2026-11-30T00:00:00")


class TestImmediateConsistency:
    def test_immediate_visibility_of_mutation_in_same_and_next_read(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "A new project starts in `ACTIVE` status with
        `suspended_reason` unset and no `production_deployment_id`."

        Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_and_next_read
        """
        plan, team = setup_team_with_project()[:2]
        created = validate_success(api.create_project(
            team["id"],
            {"name": "web2", "production_branch": "main", "preview_protection": "NONE"},
            OWNER,
        ), expected_status=201)
        fetched = validate_success(api.get_project(created["id"], VIEWER))
        assert fetched["name"] == created["name"] == "web2"
        assert fetched["production_branch"] == created["production_branch"] == "main"
        assert fetched["preview_protection"] == created["preview_protection"] == "NONE"
        assert fetched["status"] == created["status"] == "ACTIVE"
