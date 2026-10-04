"""Workflow run metering: allowance waterfall variants, per-run ceil rounding,
partial crossing, boundary at exact remaining, self-hosted zero billing,
parallel state dimensions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_and_complete_run,
    create_repository,
    create_runner_and_activate,
    create_workflow_run,
    get_org,
    run_transition,
    setup_org_with_repo,
    validate_error,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]
RA = TEST_USERS["runner_agent_headers"]


def _complete_fresh_run(api, repo, expected_version, **overrides):
    """Dispatch + START + COMPLETE; returns final run data."""
    run = create_workflow_run(repo, expected_version, **overrides)
    run_transition(run["id"], "START")
    return run_transition(run["id"], "COMPLETE")


class TestAllowanceVsOverageVariants:
    def test_run_within_allowance_settles_allowance_applied(self, api):
        """PRD §3.6: "Fourth, the run's `billing_status` moves from `METERED` to
        `ALLOWANCE_APPLIED` when `overage_minutes` is zero, or to `BILLED` when
        it is positive". PRD §3.2: "`included_actions_minutes` is 500 on `FREE`".

        Design: Difficulty/dual_variant_calc/minutes_allowance_vs_overage_variants
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        run1 = _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        assert run1["billing_status"] == "ALLOWANCE_APPLIED"
        assert run1["overage_cost_cents"] == 0

    def test_run_past_allowance_settles_billed_with_ceil_overage(self, api):
        """PRD §3.6: "`overage_cost_cents` is the ceiling of `overage_minutes`
        multiplied by the per-minute overage rate: 0.8 cents per minute for
        `LINUX`, 1.6 cents per minute for `WINDOWS`, 8.0 cents per minute for
        `MACOS`." PRD §3.6: "First, `remaining_allowance` is the greater of zero
        and `included_actions_minutes` minus the `consumed_actions_minutes`
        value just before this run's contribution."

        Design: Difficulty/dual_variant_calc/minutes_allowance_vs_overage_variants
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        run2 = _complete_fresh_run(
            api, repo, repo["version"] + 1,
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        assert run2["billing_status"] == "BILLED"
        assert run2["overage_cost_cents"] == 400  # ceil(500 * 0.8)
        assert get_org(org["id"])["consumed_actions_minutes"] == 1000


class TestPerRunCeilRoundingOrder:
    def test_five_one_minute_overage_runs_cost_five_cents(self, api):
        """PRD §2.6: "Continuous-integration minutes are metered as **whole
        minutes per run**, with the rounding applied to each individual run
        before any aggregation — never summed first and rounded afterward."
        PRD §3.6: "This per-run rounding order is pinned: round each run first,
        then sum across runs, never the other way around."

        Design: Difficulty/combinatorial_formula/minutes_per_run_ceil_rounding_order
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        overages = []
        for i in range(1, 6):
            run = _complete_fresh_run(
                api, repo, repo["version"] + i,
                runner_kind="HOSTED", os_type="LINUX", requested_minutes=1,
            )
            overages.append(run["overage_cost_cents"])
        assert overages == [1, 1, 1, 1, 1], (
            f"each 1-minute LINUX overage run must cost ceil(1 x 0.8) = 1 cent; got {overages}"
        )
        assert sum(overages) == 5, (
            "round-per-run-then-sum must yield 5 cents; sum-then-round would yield 4"
        )

    def test_consumed_minutes_accumulate_metered_amounts(self, api):
        """PRD §3.6: "The computed `billed_minutes` is added to the
        organization's `consumed_actions_minutes` immediately at the start
        transition."

        Design: Difficulty/combinatorial_formula/minutes_per_run_ceil_rounding_order
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        for i in range(1, 6):
            _complete_fresh_run(
                api, repo, repo["version"] + i,
                runner_kind="HOSTED", os_type="LINUX", requested_minutes=1,
            )
        assert get_org(org["id"])["consumed_actions_minutes"] == 505


class TestPartialCrossingWaterfall:
    def test_windows_multiplier_applies_to_billed_minutes(self, api):
        """PRD §3.6: "a `HOSTED` run is billed its `requested_minutes`
        multiplied by the operating-system multiplier — 1.0 for `LINUX`, 2.0 for
        `WINDOWS`, 10.0 for `MACOS`".

        Design: Difficulty/combinatorial_formula/minutes_allowance_waterfall_partial_crossing
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=2990,
        )
        run = create_workflow_run(
            repo, repo["version"] + 1,
            runner_kind="HOSTED", os_type="WINDOWS", requested_minutes=10,
        )
        started = run_transition(run["id"], "START")
        assert started["billed_minutes"] == 20

    def test_partial_crossing_splits_allowance_and_overage(self, api):
        """PRD §3.6: "a partial crossing is split, not all-or-nothing."
        PRD §3.6: "`overage_cost_cents` is the ceiling of `overage_minutes`
        multiplied by the per-minute overage rate: 0.8 cents per minute for
        `LINUX`, 1.6 cents per minute for `WINDOWS`, 8.0 cents per minute for
        `MACOS`."

        Design: Difficulty/combinatorial_formula/minutes_allowance_waterfall_partial_crossing
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=2990,
        )
        run = _complete_fresh_run(
            api, repo, repo["version"] + 1,
            runner_kind="HOSTED", os_type="WINDOWS", requested_minutes=10,
        )
        assert run["billing_status"] == "BILLED"
        assert run["overage_cost_cents"] == 16  # ceil((20 - 10) * 1.6)
        assert get_org(org["id"])["consumed_actions_minutes"] == 3010


class TestAllowanceExactBoundary:
    def test_run_exactly_consuming_remaining_allowance_settles_applied(self, api):
        """PRD §3.6: "Second, `allowance_applied` is the smaller of
        `remaining_allowance` and this run's `billed_minutes`. Third,
        `overage_minutes` is `billed_minutes` minus `allowance_applied`. Fourth,
        the run's `billing_status` moves from `METERED` to `ALLOWANCE_APPLIED`
        when `overage_minutes` is zero, or to `BILLED` when it is positive".

        Design: Difficulty/boundary_precision_check/minutes_allowance_exact_zero_remaining
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        run_transition(run["id"], "START")
        done = run_transition(run["id"], "COMPLETE")
        assert done["billing_status"] == "ALLOWANCE_APPLIED"
        assert done["overage_cost_cents"] == 0

    def test_one_minute_run_at_zero_remaining_fully_billed(self, api):
        """PRD §3.6: "First, `remaining_allowance` is the greater of zero and
        `included_actions_minutes` minus the `consumed_actions_minutes` value
        just before this run's contribution." PRD §3.6: "`overage_cost_cents` is
        the ceiling of `overage_minutes` multiplied by the per-minute overage
        rate: 0.8 cents per minute for `LINUX`".

        Design: Difficulty/boundary_precision_check/minutes_allowance_exact_zero_remaining
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="FREE")
        _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=500,
        )
        run2 = _complete_fresh_run(
            api, repo, repo["version"] + 1,
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=1,
        )
        assert run2["billing_status"] == "BILLED"
        assert run2["overage_cost_cents"] == 1  # ceil(1 * 0.8)


class TestSelfHostedZeroBilling:
    def test_self_hosted_run_bills_zero_minutes(self, api):
        """PRD §3.6: "a `SELF_HOSTED` run is billed zero minutes".

        Design: Corner/calculations/self_hosted_runs_bill_zero_minutes
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(org["id"], name="mac1", os_type="MACOS")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="SELF_HOSTED", os_type="MACOS", requested_minutes=100,
            runner_id=runner["id"],
        )
        started = run_transition(run["id"], "START")
        assert started["billed_minutes"] == 0

    def test_self_hosted_run_leaves_consumption_unchanged(self, api):
        """PRD §3.6: "a `SELF_HOSTED` run is billed zero minutes; a `HOSTED` run
        is billed its `requested_minutes` multiplied by the operating-system
        multiplier". PRD §3.6: "The computed `billed_minutes` is added to the
        organization's `consumed_actions_minutes` immediately at the start
        transition."

        Design: Corner/calculations/self_hosted_runs_bill_zero_minutes
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        runner = create_runner_and_activate(org["id"], name="mac1", os_type="MACOS")
        run = _complete_fresh_run(
            api, repo, repo["version"],
            runner_kind="SELF_HOSTED", os_type="MACOS", requested_minutes=100,
            runner_id=runner["id"],
        )
        assert run["billing_status"] == "ALLOWANCE_APPLIED"
        assert run["overage_cost_cents"] == 0
        assert get_org(org["id"])["consumed_actions_minutes"] == 0


class TestParallelDimensionsAndCancel:
    def test_queued_run_starts_metered_then_cancel_flips_refunded(self, api):
        """PRD §3.6: "Cancelling a `QUEUED` run — by an `OrgAdmin` action, or by
        the organization-suspension or repository-archive cascades — moves it to
        `CANCELLED`, transitions `billing_status` from `METERED` or
        `ALLOWANCE_APPLIED` to `REFUNDED`, and **re-credits** the organization's
        `consumed_actions_minutes` by the run's `billed_minutes`. Queued runs
        never actually consume minutes, so the refund is exact."

        Design: Difficulty/non_linear_state_machine/workflow_run_parallel_dimensions
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="MACOS", requested_minutes=60,
        )
        assert run["billing_status"] == "METERED"
        cancelled = run_transition(run["id"], "CANCEL", headers=OA)
        assert cancelled["execution_status"] == "CANCELLED"
        assert cancelled["billing_status"] == "REFUNDED"

    def test_cancelled_queued_run_never_consumed_minutes(self, api):
        """PRD §3.6: "Metering happens at this moment, not at completion." (on
        START) and "Queued runs never actually consume minutes, so the refund is
        exact."

        Design: Difficulty/non_linear_state_machine/workflow_run_parallel_dimensions
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="MACOS", requested_minutes=60,
        )
        assert run["billed_minutes"] == 0
        run_transition(run["id"], "CANCEL", headers=OA)
        assert get_org(org["id"])["consumed_actions_minutes"] == 0


class TestRunStateValidation:
    def test_complete_from_queued_rejected(self, api):
        """PRD §3.6: "Both transitions are rejected with `ERR_RUN_NOT_RUNNING`
        if the run is not currently `RUNNING`."

        Design: Corner/state_machines/run_complete_from_queued_rejected
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        run = create_workflow_run(
            repo, repo["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=5,
        )
        resp = api.workflow_run_transition(run["id"], "COMPLETE", RA)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_RUNNING, 409)

    def test_dispatch_bumps_repo_version_and_stale_dispatch_rejected(self, api):
        """PRD §2.5: "Dispatching a `WorkflowRun` against a repository requires
        `expected_repository_version`. If the repository's `version` has
        advanced since the client last observed it — for example because a
        visibility change or archive intervened — the dispatch is rejected; this
        prevents runner-eligibility and security-boundary decisions from being
        made from a stale view."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_workflow_run_dispatch
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        renamed = validate_success(
            api.update_repository(repo["id"], {"name": "r1-renamed"}, OA)
        )
        assert renamed["version"] == repo["version"] + 1
        resp = api.create_workflow_run(
            repo["id"],
            {
                "runner_kind": "HOSTED",
                "os_type": "LINUX",
                "requested_minutes": 5,
                "expected_repository_version": repo["version"],
            },
            OA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_dispatch_with_current_version_accepted(self, api):
        """PRD §2.5: "Successful writes on these endpoints increment the
        parent's `version` by exactly one, so the next client holding the
        previous `version` is naturally rejected."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_workflow_run_dispatch
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5, plan_tier="TEAM")
        resp = api.update_repository(repo["id"], {"name": "r1-renamed"}, OA)
        renamed = validate_success(resp)
        run = create_workflow_run(
            {**repo, "version": renamed["version"]},
            renamed["version"],
            runner_kind="HOSTED", os_type="LINUX", requested_minutes=5,
        )
        assert run["execution_status"] == "QUEUED"
        after = validate_success(api.get_repository(repo["id"], EA))
        assert after["version"] == renamed["version"] + 1
