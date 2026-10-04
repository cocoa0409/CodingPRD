"""Difficulty-queue tests: dual_variant_calc and combinatorial_formula."""
from test_helpers import (
    BILLING,
    OWNER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_env_var_payload,
    create_member_payload,
    get_team,
    get_usage_period,
    set_clock,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_success,
    api_client,
)


class TestDualVariantCalcUsagePeriod:
    def test_provisional_projection_includes_estimated_event(self, api):
        """PRD §3.7: "The projected bill — the provisional variant of the
        overage charge, computed while the period is `OPEN` over both
        `RECORDED` and `ESTIMATED` events — combines four components."
        PRD §3.7: "Bandwidth: the period's total bytes are divided by one
        billion and rounded up to whole gigabytes; the team's
        `included_bandwidth_gb` is subtracted (never below zero) to yield
        overage gigabytes; the first `bandwidth_tier2_threshold_gb` overage
        gigabytes are charged at `bandwidth_tier1_rate_cents_per_gb`"

        Design: Difficulty/dual_variant_calc/usage_provisional_vs_final_bill_on_usageperiod
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep = create_deployment(project["id"])
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 100_000_000_000, "region": "IAD"},
            WEBHOOK,
        )
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1_000_000_000, "region": "IAD", "status": "ESTIMATED"},
            WEBHOOK,
        )
        data = validate_success(api.get_usage_period(period["id"], BILLING))
        # ceil(101e9 / 1e9) = 101 GB; overage 101-100 = 1 GB x 10c tier1 = 10
        assert data["projected_bill_cents"] == 10

    def test_final_bill_converts_estimated_events_on_close(self, api):
        """PRD §3.8: "At close, every `ESTIMATED` event in the period converts
        to `RECORDED`, and the final overage charge is computed by the same
        four-component formula as the projected bill but over `RECORDED` events
        only; the result is stored in `final_bill_cents`."

        Design: Difficulty/dual_variant_calc/usage_provisional_vs_final_bill_on_usageperiod
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep = create_deployment(project["id"])
        est = validate_success(api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 1_000_000_000, "region": "IAD", "status": "ESTIMATED"},
            WEBHOOK,
        ), expected_status=201)
        assert est["status"] == "ESTIMATED"
        closed = validate_success(api.close_usage_period(period["id"], BILLING))
        assert closed["status"] == "CLOSED"
        # 1 GB total, included 100 GB -> no overage
        assert closed["final_bill_cents"] == 0
        events = api.list_period_usage_events(period["id"], BILLING)
        ev_list = validate_success(events)
        assert ev_list[0]["status"] == "RECORDED"


class TestDualVariantCalcDeployment:
    def test_first_deployment_uses_default_estimate(self, api):
        """PRD §3.4: "At creation the deployment's `estimated_build_minutes` is
        reserved: it equals the `billable_minutes` of the most recent `READY`
        deployment of the same project (the latest by `created_at`), or two
        minutes — the default estimate — when the project has never produced a
        `READY` deployment."

        Design: Difficulty/dual_variant_calc/deployment_estimated_vs_actual_build_minutes_on_deployment
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep1 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        assert dep1["estimated_build_minutes"] == 2

    def test_estimate_from_prior_ready_but_billing_uses_actual(self, api):
        """PRD §3.4: "`billable_minutes` is the build duration in seconds
        divided by sixty and rounded up to a whole minute"
        PRD §3.4: "it equals the `billable_minutes` of the most recent `READY`
        deployment of the same project (the latest by `created_at`), or two
        minutes — the default estimate — when the project has never produced a
        `READY` deployment."

        Design: Difficulty/dual_variant_calc/deployment_estimated_vs_actual_build_minutes_on_deployment
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep1 = create_deployment(project["id"], branch="feat-a", commit_sha="aaa111")
        build_deployment(dep1["id"], "SUCCESS", 300)  # billable 5
        dep2 = create_deployment(project["id"], branch="feat-a", commit_sha="bbb222")
        assert dep2["estimated_build_minutes"] == 5
        dep2_done = build_deployment(dep2["id"], "SUCCESS", 30)
        assert dep2_done["billable_minutes"] == 1


class TestTieredBandwidthWithRegionalEdgeFee:
    def test_final_bill_combines_tiers_invocations_and_edge(self, api):
        """PRD §3.7: "the first `bandwidth_tier2_threshold_gb` overage gigabytes
        are charged at `bandwidth_tier1_rate_cents_per_gb`, and any overage
        beyond that threshold is charged at the cheaper
        `bandwidth_tier2_rate_cents_per_gb` — the threshold is marginal, not a
        cliff."
        PRD §3.7: "Invocations: the period's total invocations are divided by
        one million and rounded up to whole millions; the team's
        `included_invocations_millions` is subtracted (never below zero); the
        remainder is charged at `invocation_rate_cents_per_million`."
        PRD §3.7: "Regional edge execution: for each individual event with
        `edge_execution` true, the event's own invocations are divided by one
        million and rounded up, then multiplied by the regional multiplier —
        1 for `IAD`, 1 for `SFO`, 2 for `FRA`, and 3 for `SIN` — and these
        per-event fees are summed."

        Design: Difficulty/combinatorial_formula/tiered_bandwidth_with_regional_edge_fee_mode_a
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep = create_deployment(project["id"])
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 160_000_000_000, "region": "IAD"},
            WEBHOOK,
        )
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "INVOCATION",
             "invocations": 5_000_000, "region": "IAD"},
            WEBHOOK,
        )
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "INVOCATION",
             "invocations": 2_000_000, "region": "SIN", "edge_execution": True},
            WEBHOOK,
        )
        closed = validate_success(api.close_usage_period(period["id"], BILLING))
        # bandwidth: overage 60 GB -> 50*10 + 10*5 = 550
        # invocations: ceil(7e6/1e6)=7 - 5 = 2M x 40c = 80
        # edge: ceil(2e6/1e6)=2 x 3 = 6
        # total: 550 + 80 + 6 = 636
        assert closed["final_bill_cents"] == 636

    def test_projected_bill_matches_four_component_sum_while_open(self, api):
        """PRD §3.7: "The projected bill is the sum of the four components, all
        in integer cents, with every ceiling applied before any multiplication."

        Design: Difficulty/combinatorial_formula/tiered_bandwidth_with_regional_edge_fee_mode_a
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep = create_deployment(project["id"])
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "BANDWIDTH",
             "bandwidth_bytes": 160_000_000_000, "region": "IAD"},
            WEBHOOK,
        )
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "INVOCATION",
             "invocations": 5_000_000, "region": "IAD"},
            WEBHOOK,
        )
        api.ingest_usage_event(
            team["id"],
            {"deployment_id": dep["id"], "event_type": "INVOCATION",
             "invocations": 2_000_000, "region": "SIN", "edge_execution": True},
            WEBHOOK,
        )
        data = validate_success(api.get_usage_period(period["id"], BILLING))
        # 550 (bandwidth) + 80 (invocations) + 6 (edge) = 636
        assert data["projected_bill_cents"] == 636


class TestSeatProrationEvaluationOrder:
    def test_mid_period_add_prorates_with_single_final_round(self, api):
        """PRD §3.2: "first the total length of the period in whole days is
        computed as the difference between `period_end` and `period_start`,
        floored to whole days, but never less than one day; then the remaining
        length of the period in whole days is computed as the difference
        between `period_end` and the current clock, floored to whole days, but
        never less than zero; then the plan's `seat_price_cents_monthly` is
        multiplied by the remaining days and divided by the total days; and
        finally the result is rounded half-up to integer cents, exactly once,
        at the end."

        Design: Difficulty/combinatorial_formula/seat_proration_evaluation_order_mode_c
        """
        plan, team = setup_team_with_project()[:2]
        period = validate_success(api.create_usage_period(
            team["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z"},
            BILLING,
        ), expected_status=201)
        set_clock("2026-09-14T00:00:00Z")
        validate_success(api.add_member(
            team["id"], create_member_payload(user_email="dev@acme.com", role="DEVELOPER"), OWNER
        ), expected_status=201)
        team_data = get_team(team["id"])
        # remaining = 2026-10-01 - 2026-09-14 = 17 days; total 30
        # 2000 * 17 / 30 = 1133.33 -> single round_half_up -> 1133
        assert team_data["prorated_charges_cents"] == 1133
        assert team_data["seats_used"] == 1

    def test_proration_reads_plan_price_before_charge(self, api):
        """PRD §3.2: "Because the team's `seat_limit` derives from its plan,
        the plan's seat price is read from the catalog entry before the
        proration runs — never after."
        PRD §3.2: "When the team has an `OPEN` usage period at the moment of
        the add, a prorated charge is computed and accumulated into the team's
        `prorated_charges_cents`."

        Design: Difficulty/combinatorial_formula/seat_proration_evaluation_order_mode_c
        """
        plan, team = setup_team_with_project()[:2]
        validate_success(api.create_usage_period(
            team["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z"},
            BILLING,
        ), expected_status=201)
        set_clock("2026-09-16T00:00:00Z")
        validate_success(api.add_member(
            team["id"], create_member_payload(user_email="a@x.com", role="DEVELOPER"), OWNER
        ), expected_status=201)
        validate_success(api.add_member(
            team["id"], create_member_payload(user_email="b@x.com", role="VIEWER"), OWNER
        ), expected_status=201)
        team_data = get_team(team["id"])
        # each add: 2000 * 15 / 30 = 1000; two adds accumulate to 2000
        assert team_data["prorated_charges_cents"] == 2000
        assert team_data["seats_used"] == 2
