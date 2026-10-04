"""Corner-queue tests: entities and state_machines sections."""
from test_helpers import (
    ADMIN,
    BILLING,
    DEVELOPER,
    OWNER,
    VIEWER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_plan,
    create_promoted_deployment,
    create_team,
    create_usage_period,
    get_certificate,
    get_deployment,
    get_project,
    get_usage_period,
    setup_domain_with_active_certificate,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestTeamCreateCopiesPlanLimits:
    def test_team_create_copies_plan_limits_and_zeroes_counters(self, api):
        """PRD §3.1: "At creation the plan's limits and inclusions are copied
        onto the team, `seats_used` starts at zero, `prorated_charges_cents`
        starts at zero, and the team's `version` is set to 1."

        Design: Corner/entities/team_create_copies_plan_limits_and_zeroes_counters
        """
        create_plan()  # PRO defaults
        team = validate_success(
            api.create_team({"name": "Acme", "plan_tier": "PRO"}, ADMIN),
            expected_status=201,
        )
        assert team["seat_limit"] == 10
        assert team["build_concurrency_limit"] == 2
        assert team["included_build_minutes"] == 300
        assert team["seats_used"] == 0
        assert team["prorated_charges_cents"] == 0
        assert team["version"] == 1


class TestTeamCreateUnknownPlan:
    def test_team_create_with_unknown_plan_returns_not_found(self, api):
        """PRD §2.10: "Referencing a `plan_tier` with no matching catalog entry
        fails with `ERR_PLAN_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/team_create_with_unknown_plan_returns_not_found
        """
        resp = api.create_team({"name": "Acme", "plan_tier": "NOPE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)


class TestEnvVarSecretMasking:
    def test_env_var_secret_value_masked_on_read(self, api):
        """PRD §3.3: "Secret handling is strict: whenever `is_secret` is true,
        the stored `value` is masked to null in every read response, list or
        get, without exception."

        Design: Corner/entities/env_var_secret_value_masked_on_read
        """
        plan, team, project = setup_team_with_project()
        sec = validate_success(api.create_env_var(
            project["id"],
            {"key": "SECRET_KEY", "value": "s3cr3t", "scopes": ["PRODUCTION"], "is_secret": True},
            DEVELOPER,
        ), expected_status=201)
        pub = validate_success(api.create_env_var(
            project["id"],
            {"key": "PUBLIC_URL", "value": "https://x", "scopes": ["PREVIEW"]},
            DEVELOPER,
        ), expected_status=201)
        sec_read = validate_success(api.get_env_var(sec["id"], VIEWER))
        assert sec_read["value"] is None
        assert sec_read["is_secret"] is True
        pub_read = validate_success(api.get_env_var(pub["id"], VIEWER))
        assert pub_read["value"] == "https://x"


class TestDeploymentPreviewProtectionDefault:
    def test_deployment_preview_protection_default_from_project(self, api):
        """PRD §3.4: "Its effective `access_protection` is computed: it
        defaults to the project's `preview_protection` for a `PREVIEW`
        deployment, to `NONE` for a `PRODUCTION` deployment, and an explicit
        value in the creation payload overrides the default — though
        production deployments are always forced to `NONE` regardless."

        Design: Corner/entities/deployment_preview_protection_default_from_project
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        # recreate project with TEAM_ONLY default
        project2 = validate_success(api.create_project(
            team["id"],
            {"name": "web2", "production_branch": "main", "preview_protection": "TEAM_ONLY"},
            OWNER,
        ), expected_status=201)
        d1 = validate_success(api.create_git_event(
            {"project_id": project2["id"], "branch": "feat-a",
             "git_ref": "refs/heads/feat-a", "commit_sha": "aaa111", "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        assert d1["access_protection"] == "TEAM_ONLY"
        d2 = validate_success(api.create_git_event(
            {"project_id": project2["id"], "branch": "feat-b",
             "git_ref": "refs/heads/feat-b", "commit_sha": "bbb222", "region": "IAD",
             "access_protection": "NONE"},
            WEBHOOK,
        ), expected_status=201)
        assert d2["access_protection"] == "NONE"


class TestUsageEventImmutability:
    def test_usage_event_immutability_no_update_endpoint(self, api):
        """PRD §2.4: "The exception is `UsageEvent`: usage events are
        append-only metering records and carry only `id` and `created_at`;
        both `updated_at` and `version` are absent on usage events."

        Design: Corner/entities/usage_event_immutability_no_update_endpoint
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        ev = validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1000, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        assert "id" in ev
        assert "created_at" in ev
        assert "updated_at" not in ev
        assert "version" not in ev


class TestListPaginationDefaults:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1,
        and must not exceed 100. The `offset` parameter defaults to 0. List
        responses include the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object, where
        `total_count` is the full count of matching resources and `has_more`
        indicates whether further pages exist beyond the returned window."

        Design: Corner/entities/list_pagination_defaults_and_envelope
        """
        plan, team = setup_team_with_project()[:2]
        for name in ("p1", "p2", "p3"):
            validate_success(api.create_project(
                team["id"], {"name": name, "production_branch": "main"}, OWNER,
            ), expected_status=201)
        resp = api.list_team_projects(team["id"], VIEWER)
        data, meta = validate_paginated(resp)
        assert len(data) == 4  # includes the project from setup
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestCancelCanceledDeployment:
    def test_cancel_canceled_deployment_returns_invalid_state(self, api):
        """PRD §3.4: "Cancellation of a deployment not in a cancel-permitting
        state is `ERR_INVALID_STATE`; `CANCELED` and `ERROR` are the
        deployment's terminal states."

        Design: Corner/state_machines/cancel_canceled_deployment_returns_invalid_state
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        validate_success(api.cancel_deployment(dep["id"], DEVELOPER))
        assert get_deployment(dep["id"])["status"] == "CANCELED"
        resp = api.cancel_deployment(dep["id"], DEVELOPER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_deployment(dep["id"])["status"] == "CANCELED"


class TestCancelPromotedDeployment:
    def test_cancel_promoted_deployment_returns_cannot_cancel_production(self, api):
        """PRD §3.4: "While `READY`, a preview deployment may likewise be
        canceled to `CANCELED` — but only a `PREVIEW`: attempting to cancel
        anything whose target is production is rejected with
        `ERR_CANNOT_CANCEL_PRODUCTION` (HTTP 409)."

        Design: Corner/state_machines/cancel_promoted_deployment_returns_cannot_cancel_production
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_promoted_deployment(project["id"], branch="main", commit_sha="aaa111")
        resp = api.cancel_deployment(dep["id"], DEVELOPER)
        validate_error(resp, ApiErrorId.ERR_CANNOT_CANCEL_PRODUCTION)
        assert get_deployment(dep["id"])["status"] == "PROMOTED"


class TestBuildStartOnBuildingDeployment:
    def test_build_start_on_building_deployment_returns_invalid_state(self, api):
        """PRD §3.4: "A build worker claims a queued deployment through the
        build-start transition; the deployment must currently be `QUEUED`
        (otherwise `ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/build_start_on_building_deployment_returns_invalid_state
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        validate_success(api.build_start(dep["id"], WEBHOOK))
        resp = api.build_start(dep["id"], WEBHOOK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestUsagePeriodInvoiceRequiresClosed:
    def test_usage_period_invoice_requires_closed_state(self, api):
        """PRD §3.8: "A `TeamBillingManager` invoices a `CLOSED` period
        (otherwise `ERR_INVALID_STATE`), moving it to the terminal `INVOICED`
        state"

        Design: Corner/state_machines/usage_period_invoice_requires_closed_state
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        resp = api.invoice_usage_period(period["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_usage_period(period["id"])["status"] == "OPEN"


class TestPromoteIdempotentNoop:
    def test_promote_already_promoted_is_idempotent_noop(self, api):
        """PRD §3.5: "Promoting a deployment that is already `PROMOTED` is an
        idempotent no-op: it succeeds and returns the deployment unchanged,
        with no state change."

        Design: Corner/state_machines/promote_already_promoted_is_idempotent_noop
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_promoted_deployment(project["id"], branch="main", commit_sha="aaa111")
        again = validate_success(api.promote_deployment(dep["id"], OWNER))
        assert again["status"] == "PROMOTED"
        assert get_project(project["id"])["production_deployment_id"] == dep["id"]


class TestCertificateTerminalRevokedLockdown:
    def test_certificate_terminal_revoked_lockdown(self, api):
        """PRD §3.6: "a `TeamOwner` revokes an `ACTIVE` certificate (otherwise
        `ERR_INVALID_STATE`), moving it to `REVOKED`"
        PRD §3.6: "Certificate completion — reported by `SystemWebhook` for a
        certificate in `ISSUING` (otherwise `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/certificate_terminal_revoked_lockdown
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        domain, cert = setup_domain_with_active_certificate(project["id"], name="example.com")
        validate_success(api.revoke_certificate(cert["id"], OWNER))
        assert get_certificate(cert["id"])["status"] == "REVOKED"
        resp = api.complete_certificate(cert["id"], WEBHOOK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_certificate(cert["id"])["status"] == "REVOKED"


class TestRollbackWithoutPrior:
    def test_rollback_without_prior_deployment_returns_no_prior(self, api):
        """PRD §3.5: "It requires the project to have a prior production
        deployment — one whose status is `PROMOTED` or `ROLLED_BACK` — besides
        the current one; when no such prior exists the rollback is rejected
        with `ERR_NO_PRIOR_DEPLOYMENT` (HTTP 409)"

        Design: Corner/state_machines/rollback_without_prior_deployment_returns_no_prior
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_promoted_deployment(project["id"], branch="main", commit_sha="aaa111")
        resp = api.rollback_project(project["id"], OWNER)
        validate_error(resp, ApiErrorId.ERR_NO_PRIOR_DEPLOYMENT)
        assert get_project(project["id"])["production_deployment_id"] == dep["id"]
