"""Runners and repository security boundaries: heartbeat gating, org-suspend
cascade, runner removal while in use, label subset, public-repo boundary and
its priority over cross-org references, visibility SSO gate, archive lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_and_complete_run,
    create_runner_and_activate,
    create_workflow_run,
    create_organization,
    create_repository,
    org_transition,
    run_transition,
    setup_enterprise_with_org,
    setup_org_with_repo,
    sso_transition,
    validate_error,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]
RA = TEST_USERS["runner_agent_headers"]


class TestRunnerLifecycle:
    def test_runner_heartbeat_blocked_on_suspended_org(self, api):
        """PRD §3.6: "A `RunnerAgent` heartbeat moves a runner from `REGISTERED`
        or `OFFLINE` to `ACTIVE` (rejected with `ERR_RUNNER_NOT_ACTIVATABLE`
        from any other state) and requires the owning organization to be
        `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/runner_heartbeat_requires_org_active
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        runner = create_runner_and_activate(org["id"], name="r1", os_type="LINUX")
        org_transition(org["id"], "SUSPEND")
        resp = api.runner_heartbeat(runner["id"], RA)
        validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE, 409)

    def test_suspension_cascade_leaves_runner_offline_after_revival_attempt(self, api):
        """PRD §3.9: "At depth one, every `ACTIVE` self-hosted runner of the
        organization moves to `OFFLINE`." PRD §3.9: "Self-hosted runners, by
        contrast, are **not** automatically revived: they remain `OFFLINE` until
        their next heartbeat, which the runner agent must issue explicitly."

        Design: Difficulty/cross_entity_state_dependency/runner_heartbeat_requires_org_active
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        runner = create_runner_and_activate(org["id"], name="r1", os_type="LINUX")
        assert runner["status"] == "ACTIVE"
        org_transition(org["id"], "SUSPEND")
        # Heartbeat against the suspended org must fail; the runner cannot
        # have been revived.
        resp = api.runner_heartbeat(runner["id"], RA)
        validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE, 409)
        # Unsuspend, then the explicit heartbeat succeeds from OFFLINE.
        org_transition(org["id"], "UNSUSPEND")
        resp = api.runner_heartbeat(runner["id"], RA)
        revived = validate_success(resp)
        assert revived["status"] == "ACTIVE"

    def test_runner_removal_blocked_while_run_running(self, api):
        """PRD §3.6: "removal from `ACTIVE` is blocked while any workflow run
        referencing the runner is `RUNNING`, surfacing as `ERR_RUNNER_IN_USE`."

        Design: Corner/endpoints/runner_removal_blocked_while_running
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(org["id"], name="r1", os_type="LINUX")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="SELF_HOSTED", os_type="LINUX", requested_minutes=10,
            runner_id=runner["id"],
        )
        run_transition(run["id"], "START")
        resp = api.delete_runner(runner["id"], OA)
        validate_error(resp, ApiErrorId.ERR_RUNNER_IN_USE, 409)

    def test_runner_removal_succeeds_after_run_completes(self, api):
        """PRD §3.6: "Runners may be removed by an `OrgAdmin` from `REGISTERED`,
        `ACTIVE`, or `OFFLINE`; removal from `ACTIVE` is blocked while any
        workflow run referencing the runner is `RUNNING`, surfacing as
        `ERR_RUNNER_IN_USE`."

        Design: Corner/endpoints/runner_removal_blocked_while_running
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(org["id"], name="r1", os_type="LINUX")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="SELF_HOSTED", os_type="LINUX", requested_minutes=10,
            runner_id=runner["id"],
        )
        run_transition(run["id"], "START")
        run_transition(run["id"], "COMPLETE")
        removed = validate_success(api.delete_runner(runner["id"], OA))
        assert removed["status"] == "REMOVED"


class TestRunnerLabelSubset:
    def test_required_labels_not_covered_rejected(self, api):
        """PRD §3.6: "The label subset check: every entry of `required_labels`
        must appear in the runner's `labels`; a missing entry yields
        `ERR_RUNNER_LABEL_MISMATCH`."

        Design: Corner/errors/runner_label_mismatch_rejected
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(
            org["id"], name="r1", os_type="LINUX", labels=["gpu"]
        )
        resp = api.create_workflow_run(
            repo["id"],
            {
                "runner_kind": "SELF_HOSTED",
                "os_type": "LINUX",
                "requested_minutes": 10,
                "runner_id": runner["id"],
                "required_labels": ["gpu", "large"],
                "expected_repository_version": repo["version"],
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_RUNNER_LABEL_MISMATCH, 409)


class TestPublicRepoSecurityBoundary:
    def _setup_public_repo_and_foreign_runner(self, api):
        ent = api.create_enterprise(
            {"name": "E1", "purchased_seats": 9}, EA
        )
        from test_helpers import get_success_data
        ent_data = get_success_data(ent)
        org_a = create_organization(ent_data["id"], login="orgA", plan_tier="TEAM")
        org_b = create_organization(ent_data["id"], login="orgB", plan_tier="TEAM")
        repo = create_repository(org_a["id"], name="pubrepo")
        runner = create_runner_and_activate(
            org_b["id"], name="rB", os_type="LINUX", allowed_on_public_repos=False
        )
        sso_transition(ent_data["id"], "CONFIGURE")
        sso_transition(ent_data["id"], "ENFORCE")
        updated = validate_success(
            api.update_repository(repo["id"], {"visibility": "PUBLIC"}, OA)
        )
        return ent_data, org_a, org_b, repo, runner, updated

    def test_self_hosted_on_public_repo_with_disallowed_runner_forbidden(self, api):
        """PRD §3.6: "if the repository's `visibility` is `PUBLIC` and the run
        is `SELF_HOSTED`, the referenced runner's `allowed_on_public_repos` must
        be true; otherwise the dispatch is rejected with
        `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/runner_safety_vs_referential_priority
        """
        ent, org_a, org_b, repo, runner, updated = (
            self._setup_public_repo_and_foreign_runner(api)
        )
        resp = api.create_workflow_run(
            repo["id"],
            {
                "runner_kind": "SELF_HOSTED",
                "os_type": "LINUX",
                "requested_minutes": 10,
                "runner_id": runner["id"],
                "expected_repository_version": updated["version"],
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_PUBLIC_REPO_RUNNER_FORBIDDEN, 403)

    def test_safety_error_wins_over_cross_org_reference(self, api):
        """PRD §2.9: "7. Public-repository runner boundary: a self-hosted
        workflow run on a `PUBLIC` repository requires the runner's
        `allowed_on_public_repos` flag to be true, else
        `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN`. ... 11. Cross-organization
        referential integrity: every foreign key in the request body must
        reference a resource owned by the same organization as the path, else
        `ERR_CROSS_ORG_REFERENCE`." PRD §2.9: "A request that fails an earlier
        rule is rejected with that rule's error and never reaches later rules."

        Design: Difficulty/priority_pair_validation_conflict/runner_safety_vs_referential_priority
        """
        ent, org_a, org_b, repo, runner, updated = (
            self._setup_public_repo_and_foreign_runner(api)
        )
        # The runner belongs to orgB while the repo belongs to orgA — the
        # cross-org rule also fails, but rule 7 surfaces first.
        assert runner["organization_id"] != repo["organization_id"]
        resp = api.create_workflow_run(
            repo["id"],
            {
                "runner_kind": "SELF_HOSTED",
                "os_type": "LINUX",
                "requested_minutes": 10,
                "runner_id": runner["id"],
                "expected_repository_version": updated["version"],
            },
            OA,
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_PUBLIC_REPO_RUNNER_FORBIDDEN
        assert resp.status_code == 403


class TestVisibilitySsoGate:
    def test_visibility_public_rejected_while_sso_disabled(self, api):
        """PRD §3.5: "Moving to `PUBLIC` requires the owning organization's
        enterprise to have `sso_enforcement` not equal to `DISABLED`; a public
        surface requires at minimum a configured identity baseline, and the
        patch is rejected with `ERR_VISIBILITY_REQUIRES_SSO` while the
        enterprise is still `DISABLED`."

        Design: Corner/validations/visibility_public_requires_sso
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        resp = api.update_repository(repo["id"], {"visibility": "PUBLIC"}, OA)
        validate_error(resp, ApiErrorId.ERR_VISIBILITY_REQUIRES_SSO, 409)

    def test_visibility_public_accepted_once_sso_configuring(self, api):
        """PRD §2.8: "And while `sso_enforcement` is `DISABLED`, changing a
        repository's `visibility` to `PUBLIC` is rejected with
        `ERR_VISIBILITY_REQUIRES_SSO` (HTTP 409) — a public surface requires at
        minimum an identity baseline above `DISABLED`."

        Design: Corner/validations/visibility_public_requires_sso
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        sso_transition(ent["id"], "CONFIGURE")
        data = validate_success(
            api.update_repository(repo["id"], {"visibility": "PUBLIC"}, OA)
        )
        assert data["visibility"] == "PUBLIC"


class TestArchivedRepositoryLockdown:
    def test_dispatch_against_archived_repository_rejected(self, api):
        """PRD §3.5: "The same patch surface may instead set `status` to
        `ARCHIVED`, which is terminal for writes; the patch is rejected with
        `ERR_REPO_NOT_ACTIVE` if the repository is not currently `ACTIVE`."

        Design: Corner/state_machines/archived_repository_terminal_lockdown
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        archived = validate_success(
            api.update_repository(repo["id"], {"status": "ARCHIVED"}, OA)
        )
        assert archived["status"] == "ARCHIVED"
        resp = api.create_workflow_run(
            repo["id"],
            {
                "runner_kind": "HOSTED",
                "os_type": "LINUX",
                "requested_minutes": 5,
                "expected_repository_version": archived["version"],
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_REPO_NOT_ACTIVE, 409)
