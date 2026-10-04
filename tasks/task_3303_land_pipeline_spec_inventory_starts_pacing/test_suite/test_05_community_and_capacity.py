"""Community lifecycle, pacing plans, absorption summary, capacity commitments."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_home_to,
    approve_contract,
    assert_capacity_invariant,
    create_capacity_commitment_payload,
    create_community,
    create_community_payload,
    create_partner_with_commitment,
    create_pacing_plan_payload,
    create_series,
    create_trade_partner_payload,
    get_success_data,
    make_trade_partner_headers,
    open_community,
    publish_plan,
    sell_and_close_home,
    setup_ready_community,
    start_home,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

_CM = TEST_USERS["community_manager_headers"]
_DP = TEST_USERS["division_president_headers"]
_SA = TEST_USERS["sales_agent_headers"]


class TestCommunityCreationDefaults:
    def test_community_born_planning_with_zero_counters(self, api, division_president_headers):
        """PRD §3.4: "A community is born with its `phase` in `PLANNING` and all
        counters at zero: `standing_spec_count`, `starts_this_period`, and
        `lifetime_closed_sales` all start at 0."

        Design: Corner/entities/create_community_applies_defaults
        """
        community = get_success_data(api.create_community(
            create_community_payload(), division_president_headers))
        assert community["phase"] == "PLANNING"
        assert community["standing_spec_count"] == 0
        assert community["starts_this_period"] == 0
        assert community["lifetime_closed_sales"] == 0

    def test_community_born_at_version_one(self, api, division_president_headers):
        """PRD §2.4: "`version` starts at 1 on creation and increments by exactly
        1 on every mutation of that row".

        Design: Corner/entities/create_community_applies_defaults
        """
        community = get_success_data(api.create_community(
            create_community_payload(), division_president_headers))
        assert community["version"] == 1


class TestPhaseLadder:
    def test_advance_from_closed_rejected(self, api, division_president_headers,
                                          community_manager_headers):
        """PRD §3.4: "Skipping a rung — `PLANNING` straight to `CLOSED`, for
        instance — or advancing from `CLOSED` is rejected with
        `ERR_INVALID_PHASE_TRANSITION` (HTTP 409)."

        Design: Corner/errors/error_invalid_phase_transition_from_closed
        """
        community = create_community(api)
        open_community(api, community["id"])
        for _ in range(3):
            get_success_data(api.advance_phase(community["id"], division_president_headers))
        resp = api.advance_phase(community["id"], division_president_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PHASE_TRANSITION, 409)

    def test_ladder_walks_one_step_at_a_time(self, api, division_president_headers):
        """PRD §3.4: "From there, a `DIVISION_PRESIDENT` advances the phase one
        step at a time: `OPEN_FOR_SALES` to `SELLING_OUT`, `SELLING_OUT` to
        `CLOSE_OUT`, and `CLOSE_OUT` to `CLOSED`."

        Design: Corner/errors/error_invalid_phase_transition_from_closed
        """
        community = open_community(api, create_community(api)["id"])
        phases = []
        for _ in range(3):
            community = get_success_data(api.advance_phase(community["id"],
                                                           division_president_headers))
            phases.append(community["phase"])
        assert phases == ["SELLING_OUT", "CLOSE_OUT", "CLOSED"]


class TestPacingPlanOccAndSupersede:
    def test_stale_community_version_rejected(self, api, division_president_headers):
        """PRD §2.7: "Creating a pacing plan for a community requires the request
        to carry `expected_community_version` holding the community's current
        `version` as the client last observed it. If the community's version has
        advanced since — because counters moved, a phase changed, or another plan
        was published — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting/pacing_plan_create_stale_version_rejected
        """
        community = open_community(api, create_community(api)["id"])
        stale_v = community["version"]
        publish_plan(api, community["id"], max_starts=10)  # bumps version
        resp = api.create_pacing_plan(community["id"], create_pacing_plan_payload(
            period_start="2026-10-01T00:00:00Z", period_end="2026-10-31T00:00:00Z",
            max_starts=8, expected_community_version=stale_v), division_president_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_fresh_version_supersedes_prior_plan(self, api, division_president_headers):
        """PRD §3.11: "Publication supersedes: the prior `PUBLISHED` plan for the
        community, if any, flips to `SUPERSEDED`, the new plan is born
        `PUBLISHED`, and the community's `version` increments by 1."

        Design: Corner/cross_cutting/pacing_plan_create_stale_version_rejected
        """
        community = open_community(api, create_community(api)["id"])
        plan1 = publish_plan(api, community["id"], max_starts=10)
        publish_plan(api, community["id"], max_starts=8,
                     period_start="2026-10-01T00:00:00Z",
                     period_end="2026-10-31T00:00:00Z")
        plans = get_success_data(api.list_pacing_plans(community["id"],
                                                       division_president_headers))
        by_id = {p["id"]: p["state"] for p in plans}
        assert by_id[plan1["id"]] == "SUPERSEDED"
        states = sorted(p["state"] for p in plans)
        assert states == ["PUBLISHED", "SUPERSEDED"]

    def test_missing_expected_version_returns_400(self, api, division_president_headers):
        """PRD §2.9: "A malformed payload — a missing required field, an invalid
        enum value, or a mistyped value — is rejected with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/validations/pacing_plan_create_without_community_version_returns_400
        """
        community = create_community(api)
        resp = api.create_pacing_plan(community["id"], {
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-09-30T00:00:00Z",
            "max_starts": 10,
        }, division_president_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestStartsCounterResetOnSupersede:
    def test_new_plan_resets_starts_this_period(self, api, division_president_headers):
        """PRD §3.11: "When no `PUBLISHED` plan exists the counter reads zero,
        and when a new plan supersedes the old one the counter resets to match
        the new plan's period."

        Design: Corner/consistency/pacing_plan_supersede_resets_starts_counter
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        before = get_success_data(api.get_community(env["community"]["id"], _DP))
        assert before["starts_this_period"] == 1
        publish_plan(api, env["community"]["id"], max_starts=5,
                     period_start="2026-10-01T00:00:00Z",
                     period_end="2026-10-31T00:00:00Z")
        after = get_success_data(api.get_community(env["community"]["id"], _DP))
        assert after["starts_this_period"] == 0

    def test_plan_states_after_supersede(self, api, division_president_headers):
        """PRD §3.11: "Publication supersedes: the prior `PUBLISHED` plan for the
        community, if any, flips to `SUPERSEDED`, the new plan is born
        `PUBLISHED`, and the community's `version` increments by 1.
        `SUPERSEDED` is terminal."

        Design: Corner/consistency/pacing_plan_supersede_resets_starts_counter
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        plan2 = publish_plan(api, env["community"]["id"], max_starts=5,
                             period_start="2026-10-01T00:00:00Z",
                             period_end="2026-10-31T00:00:00Z")
        plans = get_success_data(api.list_pacing_plans(env["community"]["id"], _DP))
        by_id = {p["id"]: p["state"] for p in plans}
        assert by_id[env["plan"]["id"]] == "SUPERSEDED"
        assert by_id[plan2["id"]] == "PUBLISHED"


class TestAbsorptionVariants:
    def _setup_three_closes_one_pending(self, api):
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        homes = []
        for i in range(4):
            homes.append(start_home(api, env["community"]["id"], env["lot_ids"][i],
                                    env["series"]["id"]))
        for h in homes[:3]:
            advance_home_to(api, h["id"], "COMPLETE")
            sell_and_close_home(api, h["id"], 41_200_000)
        create = api.create_sales_contract(
            {"home_id": homes[3]["id"], "buyer_name": "Buyer Four",
             "contract_price_cents": 40_000_000}, _SA)
        get_success_data(create)
        return env

    def test_trailing_rate_counts_only_closed(self, api, community_manager_headers):
        """PRD §3.12: "The `trailing_absorption_rate` is the count of the
        community's sales contracts in state `CLOSED` whose `closed_at` falls
        inside that window, divided by 3.0 — a backward-looking monthly pace."

        Design: Difficulty/dual_variant_calc/absorption_trailing_vs_forward_pace
        """
        env = self._setup_three_closes_one_pending(api)
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["trailing_absorption_rate"] == pytest.approx(1.0)

    def test_forward_pace_also_counts_open_pipeline(self, api, community_manager_headers):
        """PRD §3.12: "The `forward_pace_rate` adds the contracts currently
        `PENDING` or `APPROVED` to the same closed count before dividing by
        3.0 — a forward-looking pace that diverges from the trailing rate
        whenever an open pipeline exists."

        Design: Difficulty/dual_variant_calc/absorption_trailing_vs_forward_pace
        """
        env = self._setup_three_closes_one_pending(api)
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["forward_pace_rate"] == pytest.approx(4.0 / 3.0)
        assert summary["forward_pace_rate"] != summary["trailing_absorption_rate"]


class TestHomesPagination:
    def test_limit_and_has_more(self, api, community_manager_headers):
        """PRD §2.3: "List responses include the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in `meta`."

        Design: Corner/endpoints/homes_list_pagination_envelope
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        for i in range(3):
            start_home(api, env["community"]["id"], env["lot_ids"][i], env["series"]["id"])
        data, meta = validate_paginated(api.list_homes(
            community_manager_headers,
            params={"community_id": env["community"]["id"], "limit": 2}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_offset_returns_remaining(self, api, community_manager_headers):
        """PRD §2.3: "List endpoints accept the query parameters `limit` and
        `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
        100; `offset` defaults to 0."

        Design: Corner/endpoints/homes_list_pagination_envelope
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        for i in range(3):
            start_home(api, env["community"]["id"], env["lot_ids"][i], env["series"]["id"])
        data, meta = validate_paginated(api.list_homes(
            community_manager_headers,
            params={"community_id": env["community"]["id"], "limit": 2, "offset": 2}))
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestCapacityAllocationInvariant:
    def test_start_allocates_one_unit(self, api, community_manager_headers):
        """PRD §3.7: "releases the framing allocation back to the commitment
        that funded the start — `allocated_units` decreases by 1 and
        `remaining_units` increases by 1 on that same commitment" and PRD §3.10:
        "a start allocates one unit, and the advance into `COMPLETE` releases
        exactly one unit back to the same commitment."

        Design: Difficulty/compensating_invariant/capacity_units_conserved_under_start_complete_pair
        """
        env = setup_ready_community(api, lot_count=5, max_starts=20, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        commitment = get_success_data(api.get_capacity_commitment(
            env["commitment"]["id"], community_manager_headers))
        assert commitment["allocated_units"] == 1
        assert commitment["remaining_units"] == 9
        assert_capacity_invariant(commitment)

    def test_complete_releases_unit_restoring_pair(self, api, community_manager_headers):
        """PRD §3.10: "a start allocates one unit, and the advance into
        `COMPLETE` releases exactly one unit back to the same commitment."

        Design: Difficulty/compensating_invariant/capacity_units_conserved_under_start_complete_pair
        """
        env = setup_ready_community(api, lot_count=5, max_starts=20, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "COMPLETE")
        commitment = get_success_data(api.get_capacity_commitment(
            env["commitment"]["id"], community_manager_headers))
        assert commitment["allocated_units"] == 0
        assert commitment["remaining_units"] == 10
        assert_capacity_invariant(commitment)


class TestCapacityPeriodOverlap:
    def test_interior_overlap_rejected_adjacency_allowed(self, api):
        """PRD §3.10: "Periods for the same partner serving the same community
        may not overlap; because the interval is half-open, adjacency — one
        commitment's `period_end` equal to the next's `period_start` — is
        allowed, and only true overlap is rejected with
        `ERR_CAPACITY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/capacity_commitment_half_open_adjacency
        """
        community = create_community(api)
        cap = create_partner_with_commitment(api, community["id"], committed_units=10)
        tp_headers = make_trade_partner_headers(cap["partner"]["id"])
        overlap = api.create_capacity_commitment(cap["partner"]["id"],
                                                 create_capacity_commitment_payload(
                                                     community_id=community["id"],
                                                     period_start="2026-09-15T00:00:00Z",
                                                     period_end="2026-10-15T00:00:00Z",
                                                     committed_units=5),
                                                 tp_headers)
        validate_error(overlap, ApiErrorId.ERR_CAPACITY_PERIOD_OVERLAP, 409)
        adjacent = api.create_capacity_commitment(cap["partner"]["id"],
                                                  create_capacity_commitment_payload(
                                                      community_id=community["id"],
                                                      period_start="2026-10-01T00:00:00Z",
                                                      period_end="2026-11-01T00:00:00Z",
                                                      committed_units=5),
                                                  tp_headers)
        validate_success(adjacent, 201)

    def test_back_to_back_adjacency_still_rejected_when_overlapping(self, api):
        """PRD §3.10: "Periods for the same partner serving the same community
        may not overlap; because the interval is half-open, adjacency — one
        commitment's `period_end` equal to the next's `period_start` — is
        allowed, and only true overlap is rejected with
        `ERR_CAPACITY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/capacity_commitment_half_open_adjacency
        """
        community = create_community(api)
        cap = create_partner_with_commitment(api, community["id"], committed_units=10)
        tp_headers = make_trade_partner_headers(cap["partner"]["id"])
        contained = api.create_capacity_commitment(cap["partner"]["id"],
                                                   create_capacity_commitment_payload(
                                                       community_id=community["id"],
                                                       period_start="2026-09-05T00:00:00Z",
                                                       period_end="2026-09-20T00:00:00Z",
                                                       committed_units=5),
                                                   tp_headers)
        validate_error(contained, ApiErrorId.ERR_CAPACITY_PERIOD_OVERLAP, 409)


class TestReduceCommitment:
    def test_reduce_below_allocated_rejected(self, api):
        """PRD §3.10: "A partner can also reduce a commitment by posting a
        smaller `new_committed_units`, but never below the units already
        allocated to started, not-yet-complete homes; a reduction that would put
        `committed_units` under `allocated_units` is rejected with
        `ERR_CAPACITY_BELOW_ALLOCATED`."

        Design: Corner/validations/reduce_below_allocated_rejected
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        resp = api.reduce_capacity_commitment(env["commitment"]["id"],
                                              {"new_committed_units": 0},
                                              make_trade_partner_headers(env["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_ALLOCATED, 409)

    def test_reduce_to_allocated_succeeds(self, api):
        """PRD §3.10: "A partner can also reduce a commitment by posting a
        smaller `new_committed_units`, but never below the units already
        allocated to started, not-yet-complete homes; a reduction that would put
        `committed_units` under `allocated_units` is rejected with
        `ERR_CAPACITY_BELOW_ALLOCATED`."

        Design: Corner/validations/reduce_below_allocated_rejected
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        reduced = get_success_data(api.reduce_capacity_commitment(
            env["commitment"]["id"], {"new_committed_units": 1},
            make_trade_partner_headers(env["partner"]["id"])))
        assert reduced["committed_units"] == 1
        assert reduced["allocated_units"] == 1
        assert reduced["remaining_units"] == 0


class TestReduceCascadeHaltsStarts:
    def test_reduce_to_allocated_halts_starts(self, api, community_manager_headers):
        """PRD §3.10: "A successful reduction recomputes `remaining_units`, and
        because capacity is one of the three terms in the starts authorization,
        it can push the community's `max_starts_remaining` to zero and set
        `starts_halted`."

        Design: Difficulty/transitive_cascade/capacity_reduce_cascade_plan_recompute_to_starts_halted
        """
        env = setup_ready_community(api, lot_count=5, max_starts=5, committed_units=9)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        h_b = start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        get_success_data(api.create_sales_contract(
            {"home_id": h_b["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_000_000}, _SA))
        reduced = get_success_data(api.reduce_capacity_commitment(
            env["commitment"]["id"], {"new_committed_units": 2},
            make_trade_partner_headers(env["partner"]["id"])))
        assert reduced["remaining_units"] == 0
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["max_starts_remaining"] == 0
        assert summary["starts_halted"] is True

    def test_halt_holds_even_with_quota_and_allowance_positive(
            self, api, community_manager_headers):
        """PRD §3.6: "`max_starts_remaining` is the minimum of three quantities —
        the selected framing commitment's `remaining_units` (zero when no
        eligible commitment exists), the quota remaining (zero when no
        `PUBLISHED` plan covers the clock), and the inventory allowance."

        Design: Difficulty/transitive_cascade/capacity_reduce_cascade_plan_recompute_to_starts_halted
        """
        env = setup_ready_community(api, lot_count=5, max_starts=5, committed_units=9)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        h_b = start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        get_success_data(api.create_sales_contract(
            {"home_id": h_b["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_000_000}, _SA))
        # Quota remaining = 5-2 = 3; allowance = ceil(1.0*3.0)-1 = 2 before reduce.
        get_success_data(api.reduce_capacity_commitment(
            env["commitment"]["id"], {"new_committed_units": 2},
            make_trade_partner_headers(env["partner"]["id"])))
        community = get_success_data(api.get_community(env["community"]["id"],
                                                       community_manager_headers))
        assert community["max_starts_remaining"] == 0
        assert community["starts_halted"] is True
