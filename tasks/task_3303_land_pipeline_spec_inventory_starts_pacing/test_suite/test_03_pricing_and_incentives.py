"""Home pricing variants and the incentive stacking waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_home_to,
    create_incentive,
    create_incentive_payload,
    create_series,
    get_success_data,
    set_clock,
    setup_ready_community,
    start_home,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

_CM = TEST_USERS["community_manager_headers"]
_DP = TEST_USERS["division_president_headers"]


class TestListVsNetVariant:
    def test_frame_stage_lifts_list_variant_while_price_cut_pulls_net(
            self, api, community_manager_headers):
        """PRD §3.7: "The `net_effective_price_cents` is the adjusted price minus
        the `stacked_incentive_cents` described in §3.8; it is the variant used
        as the approval price floor, and it diverges from the list variant
        whenever any applicable incentive is active."

        Design: Difficulty/dual_variant_calc/home_price_list_vs_net_variant
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        create_incentive(api, env["community"]["id"], value_cents=500_000)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        assert home["adjusted_price_cents"] == 40_400_000
        assert home["stacked_incentive_cents"] == 500_000
        assert home["net_effective_price_cents"] == 39_900_000
        assert home["adjusted_price_cents"] != home["net_effective_price_cents"]

    def test_net_equals_adjusted_minus_capped_stack(self, api, community_manager_headers):
        """PRD §3.7: "The `adjusted_price_cents` — the list-price variant, gross
        of incentives — is the gross price times the stage multiplier, rounded
        half-up to integer cents. The `net_effective_price_cents` is the adjusted
        price minus the `stacked_incentive_cents` described in §3.8".

        Design: Difficulty/dual_variant_calc/home_price_list_vs_net_variant
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        create_incentive(api, env["community"]["id"], value_cents=500_000)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        assert home["net_effective_price_cents"] == (
            home["adjusted_price_cents"] - home["stacked_incentive_cents"])


class TestRoundPerComponent:
    def test_two_rate_buydowns_rounded_individually(self, api, community_manager_headers):
        """PRD §2.8: "each incentive's component is rounded to integer cents
        individually first, then the already-rounded components are summed, then
        the cap (itself rounded half-up to integer cents) is applied. Summing
        unrounded components and rounding once at the end is the rejected
        alternative".

        Design: Difficulty/combinatorial_formula/incentive_stacking_round_per_component
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        create_incentive(api, env["community"]["id"], type="RATE_BUYDOWN",
                         value_cents=None, value_pct=0.0033)
        create_incentive(api, env["community"]["id"], type="RATE_BUYDOWN",
                         value_cents=None, value_pct=0.0147, series_code="CLASSIC")
        home = start_home(api, env["community"]["id"], env["lot_ids"][0],
                          env["series"]["id"], lot_premium_cents=100)
        # round_half_up(0.0033*40,000,100) + round_half_up(0.0147*40,000,100)
        #   = 132,000 + 588,001 = 720,001
        # The second product is 588,001.47: fractionally above .5 for any
        # faithful reader. A reader that wrongly sums unrounded components and
        # rounds once at the end computes round(720,001.80) = 720,002, one cent
        # off, so the per-component pinning of PRD §2.8 is genuinely exercised.
        # The stack stays below the 6% cap (2,400,006).
        assert home["stacked_incentive_cents"] == 720_001

    def test_net_effective_after_rounded_stack(self, api, community_manager_headers):
        """PRD §3.8: "The raw stack is the sum of those already-rounded
        components. The cap is the community's phase-dependent cap percentage
        (§3.4) times the adjusted price, itself rounded half-up to integer cents.
        The `stacked_incentive_cents` is the raw stack or the cap, whichever is
        smaller".

        Design: Difficulty/combinatorial_formula/incentive_stacking_round_per_component
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        create_incentive(api, env["community"]["id"], type="RATE_BUYDOWN",
                         value_cents=None, value_pct=0.0033)
        create_incentive(api, env["community"]["id"], type="RATE_BUYDOWN",
                         value_cents=None, value_pct=0.0147,
                         series_code="CLASSIC")
        home = start_home(api, env["community"]["id"], env["lot_ids"][0],
                          env["series"]["id"], lot_premium_cents=100)
        assert home["adjusted_price_cents"] == 40_000_100
        assert home["stacked_incentive_cents"] == 720_001
        assert home["net_effective_price_cents"] == 39_280_099


class TestHomeComputedFieldsAtCreation:
    def test_computed_prices_at_creation_without_incentives(
            self, api, community_manager_headers):
        """PRD §3.7: "The `gross_price_cents` is the `base_price_cents` plus the
        `lot_premium_cents`. A stage multiplier is then applied: 1.00 while
        `PERMITTED`, 1.00 at `FOUNDATION`, 1.01 at `FRAME`, 1.02 at `DRYWALL`,
        and 1.03 at both `COMPLETE` and `CLOSED`".

        Design: Corner/entities/home_computed_fields_at_creation
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0],
                          env["series"]["id"], lot_premium_cents=100)
        assert home["gross_price_cents"] == 40_000_100
        assert home["adjusted_price_cents"] == 40_000_100
        assert home["stacked_incentive_cents"] == 0
        assert home["net_effective_price_cents"] == 40_000_100

    def test_lot_premium_defaults_to_zero(self, api, community_manager_headers):
        """PRD §3.6: "A `COMMUNITY_MANAGER` starts a home in a community by
        naming the `lot_id` of the homesite, the `product_series_id` positioning
        the price point, the `base_price_cents`, and optionally
        `lot_premium_cents` (which defaults to 0)."

        Design: Corner/entities/home_computed_fields_at_creation
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0],
                          env["series"]["id"])
        assert home["lot_premium_cents"] == 0
        assert home["gross_price_cents"] == 40_000_000
        assert home["net_effective_price_cents"] == 40_000_000


class TestSeriesScopeFiltering:
    def test_classic_home_stacks_scoped_and_community_wide(self, api, community_manager_headers):
        """PRD §3.8: "The applicable set is the `ACTIVE` incentives of the home's
        community whose `series_code` is null or matches the home's series,
        evaluated in order of `created_at` ascending."

        Design: Corner/state_machines/incentive_series_scope_and_community_wide_both_apply
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        express = create_series(api, env["community"]["id"], series_code="EXPRESS",
                                min_price_cents=50_000_001, max_price_cents=60_000_000)
        create_incentive(api, env["community"]["id"], value_cents=500_000)
        create_incentive(api, env["community"]["id"], type="CLOSING_COST_CREDIT",
                         value_cents=200_000, series_code="CLASSIC")
        h_classic = start_home(api, env["community"]["id"], env["lot_ids"][0],
                               env["series"]["id"])
        start_home(api, env["community"]["id"], env["lot_ids"][1], express["id"],
                   base_price_cents=45_000_000, lot_premium_cents=5_000_001)
        h_classic = get_success_data(api.get_home(h_classic["id"], community_manager_headers))
        assert h_classic["stacked_incentive_cents"] == 700_000
        assert h_classic["net_effective_price_cents"] == 39_300_000

    def test_express_home_excludes_classic_scoped_credit(self, api, community_manager_headers):
        """PRD §3.8: "The applicable set is the `ACTIVE` incentives of the home's
        community whose `series_code` is null or matches the home's series,
        evaluated in order of `created_at` ascending."

        Design: Corner/state_machines/incentive_series_scope_and_community_wide_both_apply
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        express = create_series(api, env["community"]["id"], series_code="EXPRESS",
                                min_price_cents=50_000_001, max_price_cents=60_000_000)
        create_incentive(api, env["community"]["id"], value_cents=500_000)
        create_incentive(api, env["community"]["id"], type="CLOSING_COST_CREDIT",
                         value_cents=200_000, series_code="CLASSIC")
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        h_express = start_home(api, env["community"]["id"], env["lot_ids"][1], express["id"],
                               base_price_cents=45_000_000, lot_premium_cents=5_000_001)
        h_express = get_success_data(api.get_home(h_express["id"], community_manager_headers))
        assert h_express["stacked_incentive_cents"] == 500_000
        assert h_express["net_effective_price_cents"] == 49_500_001


class TestStackingCap:
    def test_cap_binds_at_six_percent(self, api, community_manager_headers):
        """PRD §3.4: "The phase transition into `CLOSE_OUT` has a pricing side
        effect: the incentive stacking cap rises from six percent of adjusted
        price to ten percent, and every applicable home's stacked incentive and
        net effective price are recomputed under the new cap. The cap values by
        phase are: `PLANNING` 0.06, `OPEN_FOR_SALES` 0.06, `SELLING_OUT` 0.06,
        `CLOSE_OUT` 0.10, `CLOSED` 0.10."

        Design: Corner/calculations/incentive_stack_capped_at_6_percent
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        create_incentive(api, env["community"]["id"], value_cents=2_000_000)
        create_incentive(api, env["community"]["id"], type="CLOSING_COST_CREDIT",
                         value_cents=1_000_000)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        assert home["adjusted_price_cents"] == 40_400_000
        # raw stack 3,000,000 vs cap round_half_up(0.06 * 40,400,000) = 2,424,000
        assert home["stacked_incentive_cents"] == 2_424_000
        assert home["net_effective_price_cents"] == 37_976_000

    def test_close_out_raises_cap_to_ten_percent(self, api, community_manager_headers,
                                                 division_president_headers):
        """PRD §3.4: "The phase transition into `CLOSE_OUT` has a pricing side
        effect: the incentive stacking cap rises from six percent of adjusted
        price to ten percent, and every applicable home's stacked incentive and
        net effective price are recomputed under the new cap."

        Design: Corner/calculations/close_out_phase_raises_cap_to_10_percent
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        create_incentive(api, env["community"]["id"], value_cents=2_000_000)
        create_incentive(api, env["community"]["id"], type="CLOSING_COST_CREDIT",
                         value_cents=1_000_000)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        assert home["stacked_incentive_cents"] == 2_424_000
        get_success_data(api.advance_phase(env["community"]["id"], division_president_headers))
        community = get_success_data(api.advance_phase(env["community"]["id"],
                                                       division_president_headers))
        assert community["phase"] == "CLOSE_OUT"
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["stacked_incentive_cents"] == 3_000_000
        assert home["net_effective_price_cents"] == 37_400_000


class TestIncentiveLifecycle:
    def test_status_clock_derivation_and_price_follows(self, api, community_manager_headers,
                                                       division_president_headers):
        """PRD §3.8: "An incentive's `status` is computed from the clock, never
        stored as input. It is `CANCELLED` when the `cancelled` flag has been
        set; otherwise `ACTIVE` when the window covers the clock, or when the
        flag is set, the community posture is `OVERHELD`, and the clock has not
        passed `window_end`; otherwise `SCHEDULED` when the clock is still before
        `window_start`; otherwise `EXPIRED`."

        Design: Corner/state_machines/incentive_expiry_and_cancel_recompute_stacks
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        inc = create_incentive(api, env["community"]["id"], value_cents=500_000,
                               window_start="2026-09-10T00:00:00Z",
                               window_end="2026-09-20T00:00:00Z")
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        listed = get_success_data(api.list_incentives(env["community"]["id"],
                                                      community_manager_headers))
        assert listed[0]["status"] == "SCHEDULED"
        set_clock(api, "2026-09-10T00:00:00Z")
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["net_effective_price_cents"] == 39_500_000

    def test_cancel_removes_incentive_from_stack_immediately(
            self, api, community_manager_headers, division_president_headers):
        """PRD §3.8: "A community manager can cancel an incentive while it is
        `SCHEDULED` or `ACTIVE`, which sets `cancelled` to true; cancelling one
        already `CANCELLED` or `EXPIRED` is rejected with `ERR_INVALID_STATE`.
        Every activation, expiry, and cancellation recomputes the incentive stack
        of every applicable home."

        Design: Corner/state_machines/incentive_expiry_and_cancel_recompute_stacks
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        inc = create_incentive(api, env["community"]["id"], value_cents=500_000,
                               window_start="2026-09-10T00:00:00Z",
                               window_end="2026-09-20T00:00:00Z")
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        set_clock(api, "2026-09-10T00:00:00Z")
        get_success_data(api.cancel_incentive(inc["id"], community_manager_headers))
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["net_effective_price_cents"] == 40_000_000
        set_clock(api, "2026-09-21T00:00:00Z")
        listed = get_success_data(api.list_incentives(env["community"]["id"],
                                                      community_manager_headers))
        assert listed[0]["status"] == "CANCELLED"


class TestIncentiveWindowConflict:
    def test_same_type_inside_buffer_rejected_exact_buffer_allowed(
            self, api, community_manager_headers):
        """PRD §3.8: "To prevent stacking two overlapping discount programs of
        the same kind, same-type incentives scoped to the same series (including
        two community-wide ones, where both series codes are null) must keep
        their windows apart: overlapping windows, or windows separated by less
        than a 7-day buffer, are rejected at creation with
        `ERR_INCENTIVE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/incentive_same_type_buffer_gap
        """
        from test_helpers import create_community
        community = create_community(api)
        create_incentive(api, community["id"], value_cents=500_000,
                         window_start="2026-09-01T00:00:00Z",
                         window_end="2026-09-15T00:00:00Z")
        # Gap of 5 days (< 7-day buffer) after window_end.
        resp = api.create_incentive(community["id"], create_incentive_payload(
            value_cents=300_000, window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-30T00:00:00Z"), community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_WINDOW_CONFLICT, 409)
        # Exactly 7 days after window_end is allowed.
        ok = api.create_incentive(community["id"], create_incentive_payload(
            value_cents=300_000, window_start="2026-09-22T00:00:00Z",
            window_end="2026-09-30T00:00:00Z"), community_manager_headers)
        validate_success(ok, 201)

    def test_different_type_may_overlap_same_window(self, api, community_manager_headers):
        """PRD §3.8: "To prevent stacking two overlapping discount programs of
        the same kind, same-type incentives scoped to the same series (including
        two community-wide ones, where both series codes are null) must keep
        their windows apart: overlapping windows, or windows separated by less
        than a 7-day buffer, are rejected at creation with
        `ERR_INCENTIVE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/incentive_same_type_buffer_gap
        """
        from test_helpers import create_community
        community = create_community(api)
        create_incentive(api, community["id"], value_cents=500_000,
                         window_start="2026-09-01T00:00:00Z",
                         window_end="2026-09-15T00:00:00Z")
        ok = api.create_incentive(community["id"], create_incentive_payload(
            type="CLOSING_COST_CREDIT", value_cents=200_000,
            window_start="2026-09-10T00:00:00Z",
            window_end="2026-09-20T00:00:00Z"), community_manager_headers)
        validate_success(ok, 201)
