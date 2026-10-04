"""Corner-queue tests: calculations and validations sections."""
from test_helpers import (
    ADMIN,
    BILLING,
    OWNER,
    VIEWER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_plan,
    create_project,
    create_team,
    create_usage_period,
    get_alert_rule,
    get_deployment,
    get_usage_period,
    set_clock,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
)


class TestBuildMinuteBilling:
    def test_build_minute_billing_ceil_and_failed_builds_bill(self, api):
        """PRD §3.4: "`billable_minutes` is the build duration in seconds
        divided by sixty and rounded up to a whole minute, `completed_at` is
        set to the clock"
        PRD §3.4: "Failed builds bill exactly like successful ones; only a
        deployment canceled while still queued bills zero minutes."

        Design: Corner/calculations/build_minute_billing_ceil_and_failed_builds_bill
        """
        plan, team, project, period = setup_team_with_project_and_period(
            build_concurrency_limit=3, seat_price_cents_monthly=0,
        )
        d1 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        d1_done = build_deployment(d1["id"], "SUCCESS", 61)
        assert d1_done["billable_minutes"] == 2
        assert d1_done["status"] == "READY"

        d2 = create_deployment(project["id"], branch="feat-b", commit_sha="bbb222")
        d2_done = build_deployment(d2["id"], "FAILURE", 30)
        assert d2_done["billable_minutes"] == 1
        assert d2_done["status"] == "ERROR"

        d3 = create_deployment(project["id"], branch="feat-c", commit_sha="ccc333")
        validate_success(api.cancel_deployment(d3["id"], OWNER))
        d3_after = get_deployment(d3["id"])
        assert d3_after["status"] == "CANCELED"
        assert d3_after["billable_minutes"] is None

        period_data = get_usage_period(period["id"])
        assert period_data["build_minutes_used"] == 3


class TestBandwidthPeriodLevelCeil:
    def test_bandwidth_period_level_ceil_not_per_event(self, api):
        """PRD §3.7: "Bandwidth: the period's total bytes are divided by one
        billion and rounded up to whole gigabytes"
        PRD §2.5: "Where a calculation requires a ceiling — whole gigabytes of
        bandwidth, whole millions of invocations, whole build minutes, whole
        days of a usage period — the ceiling is always applied to the raw
        quantity before any multiplication by a rate."

        Design: Corner/calculations/bandwidth_period_level_ceil_not_per_event
        """
        plan, team, project, period = setup_team_with_project_and_period(
            included_bandwidth_gb=0,
            bandwidth_tier1_rate_cents_per_gb=100,
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        for _ in range(2):
            validate_success(api.ingest_usage_event(
                team["id"],
                {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
                 "bandwidth_bytes": 400_000_000, "region": "IAD"},
                WEBHOOK,
            ), expected_status=201)
        closed = validate_success(api.close_usage_period(period["id"], BILLING))
        # period total 0.8 GB -> ceil 1 GB x 100c = 100 (per-event ceil would be 200)
        assert closed["final_bill_cents"] == 100


class TestPreviewUrlSlug:
    def test_preview_url_slug_deterministic_and_commit_sensitive(self, api):
        """PRD §3.4: "The `url_slug` is built from the branch: the branch name
        is lowercased, every character that is not a lowercase letter, digit,
        or hyphen is replaced with a hyphen, consecutive hyphens are collapsed
        into one, leading and trailing hyphens are stripped, and the result is
        truncated to at most 40 characters."
        PRD §3.4: "The full `url` is the slug followed by the literal suffix
        `.preview.example.com`. Because the digest includes the commit SHA,
        the same branch and project always produce the same slug for the same
        commit and a different slug for a different commit."

        Design: Corner/calculations/preview_url_slug_deterministic_and_commit_sensitive
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        d1 = create_deployment(project["id"], branch="Feat/A B", commit_sha="aaa111",
                               git_ref="refs/heads/Feat/A B")
        d2 = create_deployment(project["id"], branch="Feat/A B", commit_sha="bbb222",
                               git_ref="refs/heads/Feat/A B")
        assert d1["url_slug"].startswith("feat-a-b-")
        assert d1["url"].endswith(".preview.example.com")
        assert d1["url"] == d1["url_slug"] + ".preview.example.com"
        assert d1["url_slug"] != d2["url_slug"]


class TestSupersedeStaleSameBranchOnly:
    def test_supersede_stale_marks_only_same_branch_previews(self, api):
        """PRD §3.4: "On a `SUCCESS` outcome the deployment becomes `READY`,
        and if any other `PREVIEW` deployment of the same project and same
        branch is currently `READY`, that earlier deployment transitions
        `READY` → `STALE` — superseded by its successor."

        Design: Corner/calculations/supersede_stale_marks_only_same_branch_previews
        """
        plan, team, project, period = setup_team_with_project_and_period(
            build_concurrency_limit=3, seat_price_cents_monthly=0,
        )
        d1 = create_deployment(project["id"], branch="feat-a", commit_sha="a11111")
        build_deployment(d1["id"], "SUCCESS", 60)
        d2 = create_deployment(project["id"], branch="feat-b", commit_sha="b22222")
        build_deployment(d2["id"], "SUCCESS", 60)
        d3 = create_deployment(project["id"], branch="feat-a", commit_sha="a33333")
        build_deployment(d3["id"], "SUCCESS", 60)

        assert get_deployment(d1["id"])["status"] == "STALE"
        assert get_deployment(d2["id"])["status"] == "READY"
        assert get_deployment(d3["id"])["status"] == "READY"


class TestAlertRuleWindowFireAndAutoReset:
    def test_alert_rule_window_fire_and_auto_reset(self, api):
        """PRD §3.7: "When the metric meets or exceeds the threshold — the
        comparison is inclusive, so exactly at the threshold fires while one
        below does not — the rule transitions `ACTIVE` → `FIRED` and stamps
        `last_fired_at` with the clock. A fired rule auto-resets to `ACTIVE`
        once the clock has reached `last_fired_at` plus the window and the
        windowed metric has fallen back below the threshold; this reset is
        swept whenever the logical clock advances."

        Design: Corner/calculations/alert_rule_window_fire_and_auto_reset
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        rule = validate_success(api.create_alert_rule(
            team["id"],
            {"metric": "BANDWIDTH_BYTES", "threshold_value": 1000, "window_minutes": 60},
            BILLING,
        ), expected_status=201)
        dep = create_deployment(project["id"])
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 600, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        assert get_alert_rule(rule["id"])["status"] == "ACTIVE"
        validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 400, "region": "IAD"},
            WEBHOOK,
        ), expected_status=201)
        # 600 + 400 = 1000 >= 1000 -> fires (inclusive)
        assert get_alert_rule(rule["id"])["status"] == "FIRED"
        set_clock("2026-09-01T01:01:00Z")
        assert get_alert_rule(rule["id"])["status"] == "ACTIVE"


class TestUsageEventShapeViolation:
    def test_usage_event_shape_violation_rejected(self, api):
        """PRD §3.7: "Shape rules are type-consistent: a `BANDWIDTH` event must
        carry `bandwidth_bytes` of at least 1 and `invocations` of exactly 0;
        an `INVOCATION` event must carry `invocations` of at least 1 and
        `bandwidth_bytes` of exactly 0; violations are `ERR_USAGE_EVENT_SHAPE`
        (HTTP 422)."

        Design: Corner/validations/usage_event_shape_violation_rejected
        """
        plan, team, project, period = setup_team_with_project_and_period(
            seat_price_cents_monthly=0,
        )
        dep = create_deployment(project["id"])
        resp = api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1000, "invocations": 5, "region": "IAD"},
            WEBHOOK,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_EVENT_SHAPE)


class TestInvalidPeriodRange:
    def test_invalid_period_range_rejected(self, api):
        """PRD §3.7: "the end must be strictly after the start — otherwise
        `ERR_INVALID_PERIOD_RANGE` (HTTP 422)."

        Design: Corner/validations/invalid_period_range_rejected
        """
        plan, team = setup_team_with_project(seat_price_cents_monthly=0)[:2]
        resp = api.create_usage_period(
            team["id"],
            {"period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-09-01T00:00:00Z"},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD_RANGE)


class TestDomainGlobalUniqueness:
    def test_domain_global_uniqueness_enforced(self, api):
        """PRD §3.6: "Hostnames are unique globally across all projects: a
        name already assigned anywhere is rejected with
        `ERR_DOMAIN_ALREADY_ASSIGNED` (HTTP 409)."

        Design: Corner/validations/domain_global_uniqueness_enforced
        """
        create_plan(seat_price_cents_monthly=0)
        t1 = create_team(name="Acme")
        t2 = create_team(name="Globex")
        p1 = create_project(t1["id"], name="web")
        p2 = create_project(t2["id"], name="site")
        validate_success(api.create_domain(p1["id"], {"name": "example.com"}, OWNER), expected_status=201)
        resp = api.create_domain(p2["id"], {"name": "example.com"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_DOMAIN_ALREADY_ASSIGNED)


class TestRedirectPriorityConflict:
    def test_redirect_priority_conflict_within_project(self, api):
        """PRD §3.3: "Lower priority values match first, and two redirects in
        the same project may not share a priority — a duplicate is rejected
        with `ERR_REDIRECT_PRIORITY_CONFLICT` (HTTP 409)."

        Design: Corner/validations/redirect_priority_conflict_within_project
        """
        plan, team, project = setup_team_with_project(seat_price_cents_monthly=0)
        validate_success(api.create_redirect(
            project["id"],
            {"source": "/old", "target": "/new", "status_code": 308, "priority": 10},
            OWNER,
        ), expected_status=201)
        resp = api.create_redirect(
            project["id"],
            {"source": "/other", "target": "/elsewhere", "status_code": 301, "priority": 10},
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_REDIRECT_PRIORITY_CONFLICT)


class TestSecondSpendCapRejected:
    def test_second_spend_cap_rejected(self, api):
        """PRD §3.7: "A `TeamBillingManager` creates at most one cap per team —
        a second live cap is `ERR_SPEND_CAP_EXISTS` (HTTP 409)"

        Design: Corner/validations/second_spend_cap_rejected
        """
        plan, team = setup_team_with_project(seat_price_cents_monthly=0)[:2]
        validate_success(api.create_spend_cap(
            team["id"], {"cap_cents": 1000, "action": "ALERT_ONLY"}, BILLING,
        ), expected_status=201)
        resp = api.create_spend_cap(
            team["id"], {"cap_cents": 2000, "action": "BLOCK_DEPLOYS_AND_SUSPEND"}, BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_SPEND_CAP_EXISTS)


class TestBuildMinutesExhaustedBoundary:
    def test_build_minutes_exhausted_boundary_strict_greater_than(self, api):
        """PRD §3.4: "If that total strictly exceeds the team's
        `included_build_minutes`, creation is rejected with
        `ERR_BUILD_MINUTES_EXHAUSTED` (HTTP 402) — there is no queueing beyond
        the plan; the boundary is strict, so a total exactly equal to the
        included allotment is admitted."

        Design: Corner/validations/build_minutes_exhausted_boundary_strict_greater_than
        """
        plan, team, project, period = setup_team_with_project_and_period(
            included_build_minutes=5, seat_price_cents_monthly=0,
        )
        d1 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        build_deployment(d1["id"], "SUCCESS", 120)  # used = 2
        d2 = create_deployment(project["id"], branch="feat-b", commit_sha="bbb222")
        # estimate from d1's billable 2; reserved 2 + 2 = 4 <= 5 -> admitted
        assert d2["estimated_build_minutes"] == 2
        build_deployment(d2["id"], "SUCCESS", 120)  # used = 4
        # next creation: reserved 4 + estimate 2 = 6 > 5 -> rejected
        resp = api.create_git_event(
            {"project_id": project["id"], "branch": "feat-c",
             "git_ref": "refs/heads/feat-c", "commit_sha": "ccc333", "region": "IAD"},
            WEBHOOK,
        )
        validate_error(resp, ApiErrorId.ERR_BUILD_MINUTES_EXHAUSTED)
        resp2 = api.create_git_event(
            {"project_id": project["id"], "branch": "feat-d",
             "git_ref": "refs/heads/feat-d", "commit_sha": "ddd444", "region": "IAD"},
            WEBHOOK,
        )
        validate_error(resp2, ApiErrorId.ERR_BUILD_MINUTES_EXHAUSTED)


class TestMissingUserContextHeader:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "If either header is missing, or if the role value is not
        one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api.list_teams(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
