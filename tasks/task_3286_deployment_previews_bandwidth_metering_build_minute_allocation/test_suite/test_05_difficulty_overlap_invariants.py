"""Difficulty-queue tests: resource_temporal_overlap and compensating_invariant."""
from test_helpers import (
    BILLING,
    OWNER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_member_payload,
    get_project,
    get_team,
    set_clock,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
    create_usage_period,
)


class TestUsagePeriodHalfOpenIntervalOverlap:
    def _setup_closed_first_period(self, api):
        plan, team = setup_team_with_project(seat_price_cents_monthly=0)[:2]
        p1 = create_usage_period(
            team["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z",
        )
        validate_success(api.close_usage_period(p1["id"], BILLING))
        return team

    def test_adjacent_period_sharing_endpoint_is_admitted(self, api):
        """PRD §3.7: "A team may have only one `OPEN` period at a time, and no
        two periods of a team may have overlapping half-open intervals (start
        inclusive, end exclusive); either violation is
        `ERR_USAGE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/usage_period_half_open_interval_overlap_on_team
        """
        team = self._setup_closed_first_period(api)
        # half-open adjacency: [2026-10-01, ...) does not overlap [..., 2026-10-01)
        p2 = validate_success(api.create_usage_period(
            team["id"],
            {"period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-11-01T00:00:00Z"},
            BILLING,
        ), expected_status=201)
        assert p2["status"] == "OPEN"

    def test_period_one_second_inside_prior_rejected(self, api):
        """PRD §3.7: "A team may have only one `OPEN` period at a time, and no
        two periods of a team may have overlapping half-open intervals (start
        inclusive, end exclusive); either violation is
        `ERR_USAGE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/usage_period_half_open_interval_overlap_on_team
        """
        team = self._setup_closed_first_period(api)
        resp = api.create_usage_period(
            team["id"],
            {"period_start": "2026-09-30T23:59:59Z",
             "period_end": "2026-12-01T00:00:00Z"},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_PERIOD_OVERLAP)


class TestEnvVarScopeSetOverlap:
    def _setup(self, api):
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        validate_success(api.create_env_var(
            project["id"],
            {"key": "API_KEY", "value": "prod-key", "scopes": ["PRODUCTION"]},
            OWNER,
        ), expected_status=201)
        return project

    def test_disjoint_scopes_for_same_key_coexist(self, api):
        """PRD §3.3: "Two variables in the same project with the same `key`
        must cover disjoint scopes: if any requested scope is already covered
        by another same-key variable in the project, creation (or a
        scopes-changing update) is rejected with `ERR_ENV_SCOPE_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/env_var_scope_set_overlap_on_project
        """
        project = self._setup(api)
        resp = api.create_env_var(
            project["id"],
            {"key": "API_KEY", "value": "prev-key", "scopes": ["PREVIEW", "DEVELOPMENT"]},
            OWNER,
        )
        data = validate_success(resp, expected_status=201)
        assert data["key"] == "API_KEY"

    def test_overlapping_scope_rejected(self, api):
        """PRD §3.3: "Two variables in the same project with the same `key`
        must cover disjoint scopes: if any requested scope is already covered
        by another same-key variable in the project, creation (or a
        scopes-changing update) is rejected with `ERR_ENV_SCOPE_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/env_var_scope_set_overlap_on_project
        """
        project = self._setup(api)
        validate_success(api.create_env_var(
            project["id"],
            {"key": "API_KEY", "value": "prev-key", "scopes": ["PREVIEW", "DEVELOPMENT"]},
            OWNER,
        ), expected_status=201)
        resp = api.create_env_var(
            project["id"],
            {"key": "API_KEY", "value": "dup-key", "scopes": ["DEVELOPMENT", "PRODUCTION"]},
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_ENV_SCOPE_OVERLAP)


class TestPromoteRollbackPairConservesProductionCount:
    def _setup(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        d1 = create_deployment(project["id"], branch="main", commit_sha="aaa111")
        build_deployment(d1["id"], "SUCCESS", 60)
        validate_success(api.promote_deployment(d1["id"], OWNER))
        d2 = create_deployment(project["id"], branch="main", commit_sha="bbb222")
        build_deployment(d2["id"], "SUCCESS", 60)
        return project, d1, d2

    def test_pair_leaves_exactly_one_promoted_and_pointer_restored(self, api):
        """PRD §3.5: "The effect is atomic: the currently `PROMOTED` deployment
        transitions `PROMOTED` → `ROLLED_BACK` with its
        `previous_promoted_deployment_id` recording the chosen prior, the
        chosen prior deployment transitions back to `PROMOTED` with its
        `previous_promoted_deployment_id` recording the displaced current
        deployment, and the project's `production_deployment_id` is updated to
        the chosen prior."

        Design: Difficulty/compensating_invariant/promote_rollback_pair_conserves_production_deployment_count
        """
        project, d1, d2 = self._setup(api)
        validate_success(api.promote_deployment(d2["id"], OWNER))
        validate_success(api.rollback_project(project["id"], OWNER))

        data = validate_success(api.list_deployments(
            OWNER, params={"project_id": project["id"], "status": "PROMOTED"},
        ))
        assert len(data) == 1
        assert data[0]["id"] == d1["id"]
        assert get_project(project["id"])["production_deployment_id"] == d1["id"]

    def test_displaced_deployment_ends_rolled_back(self, api):
        """PRD §3.5: "the currently `PROMOTED` deployment transitions
        `PROMOTED` → `ROLLED_BACK` with its
        `previous_promoted_deployment_id` recording the chosen prior"

        Design: Difficulty/compensating_invariant/promote_rollback_pair_conserves_production_deployment_count
        """
        from test_helpers import get_deployment
        project, d1, d2 = self._setup(api)
        validate_success(api.promote_deployment(d2["id"], OWNER))
        validate_success(api.rollback_project(project["id"], OWNER))
        d2_after = get_deployment(d2["id"])
        assert d2_after["status"] == "ROLLED_BACK"
        assert d2_after["previous_promoted_deployment_id"] == d1["id"]


class TestMemberAddRemovePairConservesSeatCount:
    def _setup(self, api):
        plan, team = setup_team_with_project(seat_price_cents_monthly=2000)[:2]
        validate_success(api.create_usage_period(
            team["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z"},
            BILLING,
        ), expected_status=201)
        set_clock("2026-09-16T00:00:00Z")
        return team

    def test_add_then_remove_restores_seats_used(self, api):
        """PRD §3.2: "A successful add increments `seats_used` by 1 and bumps
        the team's `version` by 1."
        PRD §3.2: "removal of a member by a `TeamOwner` decrements `seats_used`
        by 1 and again bumps the team's `version`."

        Design: Difficulty/compensating_invariant/member_add_remove_pair_conserves_seat_count
        """
        team = self._setup(api)
        member = validate_success(api.add_member(
            team["id"], create_member_payload(user_email="dev@acme.com"), OWNER,
        ), expected_status=201)
        assert get_team(team["id"])["seats_used"] == 1
        resp = api.delete_member(team["id"], member["id"], OWNER)
        assert resp.status_code == 204
        assert get_team(team["id"])["seats_used"] == 0

    def test_prorated_charge_not_refunded_on_removal(self, api):
        """PRD §3.2: "Removal performs no refund — prorated charges already
        accumulated remain on the team until they settle into an invoice."

        Design: Difficulty/compensating_invariant/member_add_remove_pair_conserves_seat_count
        """
        team = self._setup(api)
        member = validate_success(api.add_member(
            team["id"], create_member_payload(user_email="dev@acme.com"), OWNER,
        ), expected_status=201)
        # 2000 * 15 / 30 = 1000
        assert get_team(team["id"])["prorated_charges_cents"] == 1000
        api.delete_member(team["id"], member["id"], OWNER)
        assert get_team(team["id"])["prorated_charges_cents"] == 1000
