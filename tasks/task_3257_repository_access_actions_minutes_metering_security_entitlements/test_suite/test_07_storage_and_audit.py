"""Storage artifacts: retention-freeze half-open overlap, lazy expiry sweep,
upload/delete storage conservation, billing-cycle reset summary, PAT policy,
app scope catalog, audit stream toggle, workflow-run list pagination, team
chain."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_artifact,
    create_enterprise,
    create_organization,
    create_user,
    get_org,
    set_clock,
    setup_enterprise_with_org,
    setup_org_with_repo,
    create_repository,
    create_team,
    make_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]


class TestRetentionFreezeHalfOpen:
    def _setup_frozen_org(self, api):
        ent = create_enterprise(purchased_seats=5)
        org = create_organization(
            ent["id"],
            login="org1",
            plan_tier="TEAM",
            retention_freeze_windows=[
                {"start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"}
            ],
        )
        repo = create_repository(org["id"], name="repo1")
        set_clock("2026-09-01T00:00:00Z")
        return ent, org, repo

    def test_artifact_expiring_exactly_at_freeze_start_accepted(self, api):
        """PRD §3.7: "Adjacent windows do not overlap — an artifact whose
        `expires_at` exactly equals a freeze's `start` is permitted."

        Design: Difficulty/resource_temporal_overlap/artifact_retention_freeze_half_open_adjacency
        """
        ent, org, repo = self._setup_frozen_org(api)
        # 30 days from 2026-09-01 expires exactly at the freeze start.
        artifact = create_artifact(repo["id"], name="adjacent-ok", size_mb=100,
                                   retention_days=30)
        assert artifact["status"] == "RETAINED"

    def test_artifact_one_day_into_freeze_rejected(self, api):
        """PRD §3.7: "If the artifact's retention window — the half-open
        interval from `created_at` up to but not including `expires_at` —
        overlaps any declared freeze window, the create is rejected with
        `ERR_RETENTION_FREEZE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/artifact_retention_freeze_half_open_adjacency
        """
        ent, org, repo = self._setup_frozen_org(api)
        create_artifact(repo["id"], name="adjacent-ok", size_mb=100, retention_days=30)
        # 31 days crosses one second into the freeze window.
        resp = api.create_artifact(
            repo["id"], {"name": "overlap-bad", "size_mb": 100, "retention_days": 31}, OA
        )
        validate_error(resp, ApiErrorId.ERR_RETENTION_FREEZE_CONFLICT, 409)


class TestArtifactLazyExpiry:
    def test_artifact_expires_at_exact_deadline_and_recredits_storage(self, api):
        """PRD §2.7: "a `StorageArtifact` moves from `RETAINED` to `EXPIRED`
        once the logical clock is at or after the row's `expires_at`. Both
        transitions are applied whenever the affected row is read or acted on
        after expiry, and both are swept in bulk when the clock is advanced.
        The artifact sweep re-credits the organization's storage counter for
        each artifact that expires."

        Design: Corner/cross_cutting_layers/artifact_lazy_expiry_on_clock_sweep
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        set_clock("2026-09-01T00:00:00Z")
        artifact = create_artifact(repo["id"], name="a1", size_mb=2048, retention_days=10)
        set_clock("2026-09-11T00:00:00Z")  # exactly expires_at
        resp = api.list_artifacts(repo["id"], EA)
        items = validate_success(resp)
        matching = [a for a in items if a["id"] == artifact["id"]]
        assert len(matching) == 1
        assert matching[0]["status"] == "EXPIRED"
        assert get_org(org["id"])["consumed_storage_gb"] == 0.0


class TestStorageUploadDeleteInvariant:
    def test_upload_increments_consumed_storage(self, api):
        """PRD §3.7: "The server sets `expires_at` to the artifact's
        `created_at` plus `retention_days` on the logical clock, starts the row
        in `RETAINED`, and immediately increments the organization's
        `consumed_storage_gb` by the artifact's `size_mb` divided by 1024
        (storage is accounted in GB at three decimal places, round half up)."

        Design: Difficulty/compensating_invariant/storage_upload_delete_invariant
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        create_artifact(repo["id"], name="a1", size_mb=512, retention_days=90)
        assert get_org(org["id"])["consumed_storage_gb"] == 0.5

    def test_delete_returns_storage_to_pre_upload_value(self, api):
        """PRD §3.7: "Deletion and expiry both re-credit storage. An `OrgAdmin`
        delete moves a `RETAINED` artifact to `DELETED`. ... Both transitions
        decrement the organization's `consumed_storage_gb` by the artifact's
        `size_mb` divided by 1024."

        Design: Difficulty/compensating_invariant/storage_upload_delete_invariant
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        artifact = create_artifact(repo["id"], name="a1", size_mb=512, retention_days=90)
        assert get_org(org["id"])["consumed_storage_gb"] == 0.5
        deleted = validate_success(api.delete_artifact(artifact["id"], OA))
        assert deleted["status"] == "DELETED"
        assert get_org(org["id"])["consumed_storage_gb"] == 0.0


class TestBillingCycleReset:
    def test_reset_zeroes_minutes_and_reports_summary(self, api):
        """PRD §3.2: "A reset performs three things: it zeroes
        `consumed_actions_minutes` on every organization of the enterprise; it
        recomputes `consumed_storage_gb` from live `RETAINED` artifacts (so
        expired or deleted rows no longer count); and it runs a seat-reclamation
        sweep that returns seats held by users whose only justification was a
        ninety-day committer window that has since lapsed." PRD §3.2: "The
        response reports `reclaimed_seats` and `orgs_reset`."

        Design: Corner/endpoints/billing_cycle_reset_returns_summary
        """
        from test_helpers import create_workflow_run, run_transition
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=100,
        )
        run_transition(run["id"], "START")
        run_transition(run["id"], "COMPLETE")
        assert get_org(org["id"])["consumed_actions_minutes"] == 100
        summary = validate_success(api.billing_cycle_reset(ent["id"], EA))
        assert summary["reclaimed_seats"] == 0
        assert summary["orgs_reset"] == 1
        assert get_org(org["id"])["consumed_actions_minutes"] == 0


class TestPatPolicy:
    def test_pat_creation_rejected_when_policy_disallowed(self, api):
        """PRD §3.10: "`DISALLOWED` rejects the create outright with
        `ERR_PAT_POLICY_DISALLOWED` (HTTP 403)."

        Design: Corner/validations/pat_policy_disallowed_rejects_creation
        """
        ent = create_enterprise(purchased_seats=5, pat_policy="DISALLOWED")
        user = create_user("u1")
        resp = api.create_personal_access_token(
            user["id"],
            {"enterprise_id": ent["id"], "scopes": ["REPO"]},
            make_user_headers(user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAT_POLICY_DISALLOWED, 403)


class TestAppScopeCatalog:
    def test_scope_outside_catalog_rejected(self, api):
        """PRD §3.10: "An `OrgAdmin` submits an installation request with an
        `app_slug` and a `permission_scopes` list drawn from the catalog
        `ISSUES_READ`, `CONTENTS_WRITE`, `ACTIONS_ADMIN`, `ADMIN_ORG`; a scope
        outside the catalog is rejected with `ERR_INVALID_APP_SCOPE` (HTTP 400)."

        Design: Corner/validations/invalid_app_scope_rejected
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        resp = api.create_app_installation(
            org["id"],
            {"app_slug": "evil-app", "permission_scopes": ["DELETE_EVERYTHING"]},
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_APP_SCOPE, 400)


class TestTeamParentChain:
    def test_acyclic_parent_chain_accepted(self, api):
        """PRD §3.4: "When a team is created or its parent pointer is updated,
        the server walks the chain of `parent_team_id` references; if the walk
        ever revisits a team id, the operation is rejected with
        `ERR_TEAM_CYCLE`."

        Design: Corner/validations/team_cycle_rejected
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        t1 = create_team(org["id"], name="t1")
        t2 = create_team(org["id"], name="t2", parent_team_id=t1["id"])
        t3 = create_team(org["id"], name="t3", parent_team_id=t2["id"])
        assert t3["parent_team_id"] == t2["id"]


class TestWorkflowRunListPagination:
    def test_list_envelope_and_pagination_window(self, api):
        """PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`; `total_count` is the total
        number of matching records before pagination, and `has_more` is true
        exactly when `offset + limit` is less than `total_count`."

        Design: Corner/endpoints/workflow_run_list_pagination_envelope
        """
        from test_helpers import create_workflow_run
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        create_workflow_run(repo, repo["version"],
                            runner_kind="HOSTED", os_type="LINUX", requested_minutes=3)
        create_workflow_run(repo, repo["version"] + 1,
                            runner_kind="HOSTED", os_type="LINUX", requested_minutes=4)
        resp = api.list_workflow_runs(repo["id"], EA, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

    def test_list_response_type_is_array_with_request_id(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." PRD §2.2: "The
        `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."

        Design: Corner/endpoints/workflow_run_list_pagination_envelope
        """
        from test_helpers import create_workflow_run
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        create_workflow_run(repo, repo["version"],
                            runner_kind="HOSTED", os_type="LINUX", requested_minutes=3)
        resp = api.list_workflow_runs(repo["id"], EA)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")


class TestAuditStreamToggle:
    def test_toggle_cycles_streaming_paused_streaming(self, api):
        """PRD §3.1: "Audit log streaming is an independent axis on the
        enterprise, cycling `INACTIVE` → `STREAMING` → `PAUSED` → `STREAMING`
        with no terminal state."

        Design: Corner/cross_cutting_layers/audit_stream_toggle_cycles_statuses
        """
        ent = create_enterprise(purchased_seats=5)
        s1 = validate_success(api.audit_log_stream_toggle(ent["id"], EA))[
            "audit_log_stream_status"
        ]
        s2 = validate_success(api.audit_log_stream_toggle(ent["id"], EA))[
            "audit_log_stream_status"
        ]
        s3 = validate_success(api.audit_log_stream_toggle(ent["id"], EA))[
            "audit_log_stream_status"
        ]
        assert s1 == "STREAMING"
        assert s2 == "PAUSED"
        assert s3 == "STREAMING"

    def test_event_written_while_streaming_marked_streamed(self, api):
        """PRD §3.1: "While the status is `STREAMING`, every newly written
        `AuditLogEvent` is marked `streamed` as true at write time; events
        written while the status is `INACTIVE` or `PAUSED` are left `streamed`
        false and remain pending delivery."

        Design: Corner/cross_cutting_layers/audit_stream_toggle_cycles_statuses
        """
        from test_helpers import list_audit_events, sso_transition
        ent = create_enterprise(purchased_seats=5)
        validate_success(api.audit_log_stream_toggle(ent["id"], EA))
        sso_transition(ent["id"], "CONFIGURE")  # emits sso.configuration_started
        events = list_audit_events(ent["id"])
        by_action = {e["action"]: e for e in events}
        assert "sso.configuration_started" in by_action
        assert by_action["sso.configuration_started"]["streamed"] is True
