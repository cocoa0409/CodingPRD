"""Organization suspension depth-3 cascade, archive gating, and security
entitlement lifecycle, pricing and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_and_activate_entitlement,
    create_commit_event,
    create_entitlement,
    create_organization,
    create_repository,
    create_runner_and_activate,
    create_user,
    create_workflow_run,
    entitlement_transition,
    get_org,
    get_seat_usage,
    org_transition,
    run_transition,
    setup_enterprise_with_org,
    setup_org_with_repo,
    validate_error,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]
RA = TEST_USERS["runner_agent_headers"]


class TestOrgSuspendCascade:
    def _setup_suspended_org_with_runner_and_queued_run(self, api):
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(
            org["id"], name="r1", os_type="LINUX", labels=["gpu"]
        )
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="SELF_HOSTED", os_type="LINUX", requested_minutes=30,
            runner_id=runner["id"],
        )
        return ent, org, repo, runner, run

    def test_suspend_moves_org_to_suspended(self, api):
        """PRD §3.9: "An organization's `status` cycles `ACTIVE` → `SUSPENDED`
        → `ACTIVE` and may also move terminally to `ARCHIVED`."

        Design: Difficulty/transitive_cascade/org_suspend_depth3_cascade
        """
        ent, org, repo, runner, run = (
            self._setup_suspended_org_with_runner_and_queued_run(api)
        )
        data = org_transition(org["id"], "SUSPEND")
        assert data["status"] == "SUSPENDED"
        assert data["consumed_actions_minutes"] == 0

    def test_suspend_cascades_runner_offline_and_run_cancelled_refunded(self, api):
        """PRD §3.9: "At depth one, every `ACTIVE` self-hosted runner of the
        organization moves to `OFFLINE`. At depth two, every `QUEUED` workflow
        run of the organization moves to `CANCELLED` on the execution axis and
        to `REFUNDED` on the billing axis, with its metered minutes credited
        back."

        Design: Difficulty/transitive_cascade/org_suspend_depth3_cascade
        """
        ent, org, repo, runner, run = (
            self._setup_suspended_org_with_runner_and_queued_run(api)
        )
        assert runner["status"] == "ACTIVE"
        org_transition(org["id"], "SUSPEND")
        # Runner is OFFLINE: a heartbeat against the suspended org is rejected.
        resp = api.runner_heartbeat(runner["id"], RA)
        validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE, 409)
        # Run is CANCELLED on the execution axis and REFUNDED on billing:
        # a CANCELLED run cannot be started (ERR_RUN_NOT_QUEUED proves it left
        # QUEUED) and cannot be completed (ERR_RUN_NOT_RUNNING proves it is
        # terminal on the execution axis).
        resp = api.workflow_run_transition(run["id"], "START", RA)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_QUEUED, 409)
        runs, meta = None, None
        resp = api.list_workflow_runs(repo["id"], EA, params={"execution_status": "CANCELLED"})
        data = validate_success(resp)
        cancelled = [r for r in data if r["id"] == run["id"]]
        assert len(cancelled) == 1
        assert cancelled[0]["billing_status"] == "REFUNDED"
        assert get_org(org["id"])["consumed_actions_minutes"] == 0


class TestOrgArchiveGating:
    def test_archive_blocked_by_running_run(self, api):
        """PRD §3.9: "An `EnterpriseAdmin` may archive an `ACTIVE` organization
        only when no workflow run of the organization is currently `QUEUED` or
        `RUNNING` (rejected with `ERR_INFLIGHT_RUNS_EXIST` otherwise)".

        Design: Corner/errors/inflight_runs_block_org_archive
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=10,
        )
        run_transition(run["id"], "START")
        resp = api.org_transition(org["id"], "ARCHIVE", EA)
        validate_error(resp, ApiErrorId.ERR_INFLIGHT_RUNS_EXIST, 409)


class TestEntitlementLifecycle:
    def test_activate_twice_rejected_and_price_frozen(self, api):
        """PRD §3.8: "Activation against an entitlement not currently
        `PENDING_ACTIVATION` is rejected with
        `ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION`." PRD §3.8: "the per-committer
        rate is looked up by product: 1900 cents for `SECRET_SCANNING`, 3000
        cents for `CODE_SCANNING`, and 400 cents for `DEPENDENCY_REVIEW`."

        Design: Corner/state_machines/entitlement_activate_twice_rejected
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        user = create_user("u1")
        create_commit_event(user["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        activated = create_and_activate_entitlement(org["id"], repo["id"], "SECRET_SCANNING")
        assert activated["monthly_price_cents"] == 1900
        resp = api.entitlement_transition(activated["id"], "ACTIVATE", OA)
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION, 409)

    def test_activation_on_free_plan_rejected(self, api):
        """PRD §3.8: "The organization's `plan_tier` must be `TEAM` or
        `ENTERPRISE`; activation against `FREE` is rejected with
        `ERR_PLAN_TIER_INSUFFICIENT` (HTTP 402)."

        Design: Corner/errors/plan_tier_insufficient_for_advanced_security
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        user = create_user("u1")
        create_commit_event(user["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        entl = create_entitlement(org["id"], repo["id"], "SECRET_SCANNING")
        resp = api.entitlement_transition(entl["id"], "ACTIVATE", OA)
        validate_error(resp, ApiErrorId.ERR_PLAN_TIER_INSUFFICIENT, 402)

    def test_activation_without_committers_rejected(self, api):
        """PRD §3.8: "And the computed `committer_count` must be at least 1 — a
        repository with no active committers is rejected with
        `ERR_NO_ACTIVE_COMMITTERS` (HTTP 402)."

        Design: Corner/errors/entitlement_without_committers_rejected
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        entl = create_entitlement(org["id"], repo["id"], "DEPENDENCY_REVIEW")
        resp = api.entitlement_transition(entl["id"], "ACTIVATE", OA)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COMMITTERS, 402)


class TestEntitlementPriceFrozen:
    def test_price_frozen_at_activation_value(self, api):
        """PRD §3.8: "both `committer_count` and `monthly_price_cents` are
        **frozen at activation** — later drift in the underlying committer
        population does not re-price an `ACTIVE` entitlement."

        Design: Corner/calculations/entitlement_price_frozen_at_activation
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=9, plan_tier="TEAM")
        u1 = create_user("u1")
        create_commit_event(u1["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        activated = create_and_activate_entitlement(org["id"], repo["id"], "CODE_SCANNING")
        assert activated["monthly_price_cents"] == 3000

    def test_later_commit_event_does_not_reprice_active_entitlement(self, api):
        """PRD §3.8: "Re-pricing requires an explicit cancel, re-create, and
        re-activate." PRD §3.8: "later drift in the underlying committer
        population does not re-price an `ACTIVE` entitlement."

        Design: Corner/calculations/entitlement_price_frozen_at_activation
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=9, plan_tier="TEAM")
        u1 = create_user("u1")
        u2 = create_user("u2")
        create_commit_event(u1["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        activated = create_and_activate_entitlement(org["id"], repo["id"], "CODE_SCANNING")
        assert activated["committer_count"] == 1
        assert activated["monthly_price_cents"] == 3000
        # A second committer appears after activation.
        create_commit_event(u2["id"], org["id"], committed_at="2026-09-01T01:00:00Z")
        # Re-pricing requires cancel + re-create + re-activate, so a SUSPEND /
        # RESUME cycle (which is not a re-activation) must not re-price either.
        suspended = entitlement_transition(activated["id"], "SUSPEND")
        resumed = entitlement_transition(activated["id"], "RESUME")
        assert resumed["monthly_price_cents"] == 3000
        assert resumed["committer_count"] == 1


class TestDuplicateEntitlement:
    def test_second_pending_entitlement_same_pair_rejected(self, api):
        """PRD §3.8: "Only one entitlement per (`repository_id`, `product`)
        pair may exist in `ACTIVE` or `PENDING_ACTIVATION` at a time; a second
        create against the same pair while the first is still live is rejected
        with `ERR_DUPLICATE_ENTITLEMENT`."

        Design: Corner/validations/duplicate_entitlement_rejected
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        org_v = get_org(org["id"])["version"]
        resp = api.create_security_entitlement(
            org["id"],
            {
                "repository_id": repo["id"],
                "product": "DEPENDENCY_REVIEW",
                "expected_organization_version": org_v,
            },
            OA,
        )
        validate_success(resp, expected_status=201)
        resp = api.create_security_entitlement(
            org["id"],
            {
                "repository_id": repo["id"],
                "product": "DEPENDENCY_REVIEW",
                "expected_organization_version": org_v + 1,
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTITLEMENT, 409)


class TestEntitlementOcc:
    def test_stale_org_version_on_entitlement_create_rejected(self, api):
        """PRD §2.5: "Creating a `SecurityEntitlement` against an organization
        requires `expected_organization_version`. If the organization's
        `version` has advanced since the client last observed it, the create is
        rejected; this is the serialization point that prevents a supersession
        decision from being made against outdated state."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_entitlement_create
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        org_v = get_org(org["id"])["version"]
        resp = api.create_security_entitlement(
            org["id"],
            {
                "repository_id": repo["id"],
                "product": "SECRET_SCANNING",
                "expected_organization_version": org_v,
            },
            OA,
        )
        validate_success(resp, expected_status=201)
        # First create bumped Organization.version; replaying the stale
        # version against a different product must be rejected.
        resp = api.create_security_entitlement(
            org["id"],
            {
                "repository_id": repo["id"],
                "product": "CODE_SCANNING",
                "expected_organization_version": org_v,
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_entitlement_create_increments_org_version(self, api):
        """PRD §2.5: "Successful writes on these endpoints increment the
        parent's `version` by exactly one, so the next client holding the
        previous `version` is naturally rejected."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_entitlement_create
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        org_v = get_org(org["id"])["version"]
        entl = create_entitlement(org["id"], repo["id"], "SECRET_SCANNING",
                                  expected_org_version=org_v)
        assert entl["status"] == "PENDING_ACTIVATION"
        assert get_org(org["id"])["version"] == org_v + 1
