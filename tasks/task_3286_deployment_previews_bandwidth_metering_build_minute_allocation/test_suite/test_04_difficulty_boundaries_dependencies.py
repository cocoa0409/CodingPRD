"""Difficulty-queue tests: boundary_precision_check and cross_entity_state_dependency."""
from test_helpers import (
    BILLING,
    OWNER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_spend_cap,
    create_usage_period,
    get_deployment,
    get_project,
    get_spend_cap,
    get_usage_period,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
)


class TestSpendCapTripsAtExactEquality:
    def _setup(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            included_bandwidth_gb=10,
            bandwidth_tier1_rate_cents_per_gb=100,
            seat_price_cents_monthly=0,
        )
        cap = create_spend_cap(team["id"], cap_cents=1000, action="BLOCK_DEPLOYS_AND_SUSPEND")
        dep = create_deployment(project["id"])
        return team, project, period, cap, dep

    def test_projected_bill_below_cap_leaves_cap_active(self, api):
        """PRD §3.7: "Whenever the open period's `projected_bill_cents` is
        recomputed, an `ACTIVE` cap compares it against `cap_cents`; meeting
        or exceeding the cap — an inclusive comparison — trips it: the cap
        transitions `ACTIVE` → `TRIPPED` and stamps `tripped_at`."

        Design: Difficulty/boundary_precision_check/spend_cap_trips_at_exact_equality_via_usage_ingest
        """
        team, project, period, cap, dep = self._setup(api)
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 19_000_000_000, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        data = get_usage_period(period["id"])
        # ceil(19e9/1e9)=19; overage 9 GB x 100c = 900 < 1000
        assert data["projected_bill_cents"] == 900
        assert get_spend_cap(cap["id"])["status"] == "ACTIVE"

    def test_projected_bill_at_cap_trips_inclusively(self, api):
        """PRD §3.7: "meeting or exceeding the cap — an inclusive comparison —
        trips it: the cap transitions `ACTIVE` → `TRIPPED` and stamps
        `tripped_at`."

        Design: Difficulty/boundary_precision_check/spend_cap_trips_at_exact_equality_via_usage_ingest
        """
        team, project, period, cap, dep = self._setup(api)
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 19_000_000_000, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1_000_000_000, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        data = get_usage_period(period["id"])
        # 20 GB total; overage 10 x 100c = 1000 == cap -> trips
        assert data["projected_bill_cents"] == 1000
        assert get_spend_cap(cap["id"])["status"] == "TRIPPED"


class TestBuildConcurrencyBoundary:
    def _setup(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            build_concurrency_limit=1,
        )
        d1 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        d2 = create_deployment(project["id"], branch="feat-b", commit_sha="bbb222")
        return team, project, d1, d2

    def test_first_build_start_admitted_below_limit(self, api):
        """PRD §3.4: "the team's count of `BUILDING` deployments must be below
        its `build_concurrency_limit` — when the count has reached the limit,
        the claim is rejected with `ERR_BUILD_CONCURRENCY_EXCEEDED` (HTTP 409)
        and the caller retries later; the boundary is a strict at-least
        comparison."

        Design: Difficulty/boundary_precision_check/build_concurrency_boundary_at_limit_via_build_start
        """
        team, project, d1, d2 = self._setup(api)
        started = validate_success(api.build_start(d1["id"], WEBHOOK))
        assert started["status"] == "BUILDING"
        assert get_deployment(d2["id"])["status"] == "QUEUED"

    def test_build_start_at_limit_rejected_and_queue_unchanged(self, api):
        """PRD §3.4: "the team's count of `BUILDING` deployments must be below
        its `build_concurrency_limit` — when the count has reached the limit,
        the claim is rejected with `ERR_BUILD_CONCURRENCY_EXCEEDED` (HTTP 409)
        and the caller retries later; the boundary is a strict at-least
        comparison."

        Design: Difficulty/boundary_precision_check/build_concurrency_boundary_at_limit_via_build_start
        """
        team, project, d1, d2 = self._setup(api)
        validate_success(api.build_start(d1["id"], WEBHOOK))
        resp = api.build_start(d2["id"], WEBHOOK)
        validate_error(resp, ApiErrorId.ERR_BUILD_CONCURRENCY_EXCEEDED)
        assert get_deployment(d2["id"])["status"] == "QUEUED"


class TestPromoteBlockedByProjectSuspension:
    def _setup(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            included_build_minutes=10,
            overage_build_minute_rate_cents=100,
            seat_price_cents_monthly=0,
        )
        cap = create_spend_cap(team["id"], cap_cents=200, action="BLOCK_DEPLOYS_AND_SUSPEND")
        # d2 completes first at 1 minute: no overage yet, stays READY
        d2 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        build_deployment(d2["id"], "SUCCESS", 60)
        # d1 completes 13 minutes: overage (1+13-10)=4 min x 100c = 400 >= 200 -> trips
        d1 = create_deployment(project["id"], branch="feat-b", commit_sha="bbb222")
        build_deployment(d1["id"], "SUCCESS", 780)
        return team, project, d1, d2

    def test_promote_under_suspended_project_rejected(self, api):
        """PRD §3.5: "The owning project must be `ACTIVE`; promotion under a
        suspended project is rejected with `ERR_PROJECT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/promote_blocked_by_project_suspension_project_to_deployment
        """
        team, project, d1, d2 = self._setup(api)
        assert get_project(project["id"])["status"] == "SUSPENDED"
        resp = api.promote_deployment(d2["id"], OWNER)
        validate_error(resp, ApiErrorId.ERR_PROJECT_SUSPENDED)

    def test_failed_promote_leaves_deployment_ready(self, api):
        """PRD §3.5: "The owning project must be `ACTIVE`; promotion under a
        suspended project is rejected with `ERR_PROJECT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/promote_blocked_by_project_suspension_project_to_deployment
        """
        team, project, d1, d2 = self._setup(api)
        api.promote_deployment(d2["id"], OWNER)
        assert get_deployment(d2["id"])["status"] == "READY"


class TestUsageIngestBlockedByPeriodState:
    def _setup_closed(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        validate_success(api.close_usage_period(period["id"], BILLING))
        return team, project, period, dep

    def test_ingest_after_close_rejected(self, api):
        """PRD §3.7: "Ingesting when the team has no `OPEN` period is rejected
        with `ERR_USAGE_PERIOD_CLOSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/usage_ingest_blocked_by_period_state_period_to_event
        """
        team, project, period, dep = self._setup_closed(api)
        resp = api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1000, "region": "IAD"},
            WEBHOOK,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_PERIOD_CLOSED)

    def test_ingest_before_any_period_opened_rejected(self, api):
        """PRD §3.7: "Ingesting when the team has no `OPEN` period is rejected
        with `ERR_USAGE_PERIOD_CLOSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/usage_ingest_blocked_by_period_state_period_to_event
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        dep = create_deployment(project["id"])
        resp = api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1000, "region": "IAD"},
            WEBHOOK,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_PERIOD_CLOSED)
