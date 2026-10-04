"""Home starts: six-gate authorization, posture boundary, starts authorization."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_community,
    create_home_payload,
    create_partner_with_commitment,
    create_series,
    execute_takedown,
    get_success_data,
    list_banked_lot_ids,
    open_community,
    publish_plan,
    schedule_takedown,
    setup_active_contract,
    setup_ready_community,
    start_home,
    validate_error,
    validate_success,
)


class TestHomeStartRequiresOpenPhase:
    def test_planning_community_rejects_start(self, api):
        """PRD §3.6: "The community's phase must be `OPEN_FOR_SALES` or
        `SELLING_OUT`; starting in `PLANNING`, `CLOSE_OUT`, or `CLOSED` is
        rejected with `ERR_COMMUNITY_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/home_start_requires_community_open_phase
        """
        env = setup_ready_community(api, open_it=False)
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][0], product_series_id=env["series"]["id"]),
            TEST_USERS["community_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_OPEN, 409)

    def test_open_community_accepts_start(self, api):
        """PRD §3.6: "The community's phase must be `OPEN_FOR_SALES` or
        `SELLING_OUT`; starting in `PLANNING`, `CLOSE_OUT`, or `CLOSED` is
        rejected with `ERR_COMMUNITY_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/home_start_requires_community_open_phase
        """
        env = setup_ready_community(api)
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][0], product_series_id=env["series"]["id"]),
            TEST_USERS["community_manager_headers"])
        home = validate_success(resp, 201)
        assert home["build_stage"] == "PERMITTED"
        assert home["sales_status"] == "UNSOLD"


class TestMonthsOfSupplyBoundary:
    def test_fifth_start_blocked_at_exactly_4_months(self, api):
        """PRD §2.10: "The posture is `OVERHELD` when months of supply reaches
        4.0 or more, `STARVED` when months of supply is below 1.5, and `NORMAL`
        otherwise."

        Design: Difficulty/boundary_precision_check/months_of_supply_exactly_4_blocks_spec_start
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        for i in range(4):
            start_home(api, env["community"]["id"], env["lot_ids"][i], env["series"]["id"])
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][4], product_series_id=env["series"]["id"]),
            TEST_USERS["community_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_STARTS_BLOCKED_OVERHELD, 409)

    def test_summary_reports_overheld_at_exactly_4_months(self, api, community_manager_headers):
        """PRD §3.12: "The `months_of_supply` divides `standing_spec_count` by
        the effective absorption — the trailing rate or the 1.0 floor, whichever
        is larger — and the posture thresholds of §2.10 apply exactly: `OVERHELD`
        at 4.0 or more, `STARVED` below 1.5, `NORMAL` in between."

        Design: Difficulty/boundary_precision_check/months_of_supply_exactly_4_blocks_spec_start
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        for i in range(4):
            start_home(api, env["community"]["id"], env["lot_ids"][i], env["series"]["id"])
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["months_of_supply"] == pytest.approx(4.0)
        assert summary["posture"] == "OVERHELD"


class TestStartsAuthorizationNestedMin:
    def test_max_starts_remaining_is_nested_min(self, api, community_manager_headers):
        """PRD §3.6: "`max_starts_remaining` is the minimum of three quantities —
        the selected framing commitment's `remaining_units` (zero when no
        eligible commitment exists), the quota remaining (zero when no
        `PUBLISHED` plan covers the clock), and the inventory allowance."

        Design: Difficulty/combinatorial_formula/starts_authorization_nested_min
        """
        env = setup_ready_community(api, lot_count=5, max_starts=5, committed_units=9)
        h_a = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        h_b = start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        # Reserving hB drops standing to 1: months 1.0 -> STARVED; allowance
        # ceil(1.0*3.0)-1 = 2; quota 3; capacity 7 -> min = 2.
        get_success_data(api.create_sales_contract(
            {"home_id": h_b["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_000_000},
            TEST_USERS["sales_agent_headers"]))
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["max_starts_remaining"] == 2

    def test_starved_posture_alongside_nested_min(self, api, community_manager_headers):
        """PRD §3.6: "The inventory allowance is the target spec depth minus what
        is already standing: the effective absorption rate times the community's
        `months_supply_target`, rounded up to a whole number, minus
        `standing_spec_count`, floored at zero — except that a `STARVED`
        community always keeps an allowance of at least 1."

        Design: Difficulty/combinatorial_formula/starts_authorization_nested_min
        """
        env = setup_ready_community(api, lot_count=5, max_starts=5, committed_units=9)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        h_b = start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        get_success_data(api.create_sales_contract(
            {"home_id": h_b["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_000_000},
            TEST_USERS["sales_agent_headers"]))
        summary = get_success_data(api.get_pacing_summary(env["community"]["id"],
                                                          community_manager_headers))
        assert summary["months_of_supply"] == pytest.approx(1.0)
        assert summary["posture"] == "STARVED"
        assert summary["max_starts_remaining"] == 2


class TestHomeStartGates:
    def test_start_without_published_plan_rejected(self, api, community_manager_headers):
        """PRD §3.6: "A `PUBLISHED` pacing plan covering the current clock must
        exist; otherwise `ERR_NO_PUBLISHED_PACING_PLAN`."

        Design: Corner/validations/home_start_without_published_plan_rejected
        """
        # Everything except the pacing plan.
        base = setup_active_contract(api)
        community = open_community(api, create_community(api)["id"])
        series = create_series(api, community["id"])
        td = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5)
        execute_takedown(api, td["id"])
        create_partner_with_commitment(api, community["id"], committed_units=10)
        lot_ids = list_banked_lot_ids(api, community["id"])
        resp = api.create_home(community["id"], create_home_payload(
            lot_id=lot_ids[0], product_series_id=series["id"]), community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_PACING_PLAN, 409)

    def test_start_without_framing_capacity_rejected(self, api, community_manager_headers):
        """PRD §3.6: "If the pool is empty — no eligible commitment, or all
        eligible commitments fully allocated — the start is rejected with
        `ERR_NO_CAPACITY_REMAINING`."

        Design: Corner/errors/error_no_capacity_remaining
        """
        base = setup_active_contract(api)
        community = open_community(api, create_community(api)["id"])
        series = create_series(api, community["id"])
        td = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5)
        execute_takedown(api, td["id"])
        publish_plan(api, community["id"], max_starts=10)
        lot_ids = list_banked_lot_ids(api, community["id"])
        resp = api.create_home(community["id"], create_home_payload(
            lot_id=lot_ids[0], product_series_id=series["id"]), community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CAPACITY_REMAINING, 409)

    def test_start_beyond_pacing_quota_rejected(self, api, community_manager_headers):
        """PRD §3.6: "The pacing quota must have room: quota remaining is the
        published plan's `max_starts` minus the community's `starts_this_period`,
        floored at zero; when quota remaining is zero the start is rejected with
        `ERR_STARTS_QUOTA_EXCEEDED`."

        Design: Corner/errors/error_starts_quota_exceeded
        """
        env = setup_ready_community(api, lot_count=5, max_starts=1, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][1], product_series_id=env["series"]["id"]),
            community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STARTS_QUOTA_EXCEEDED, 409)

    def test_second_start_on_consumed_lot_rejected(self, api, community_manager_headers):
        """PRD §3.6: "The named lot must belong to the community and be `BANKED`;
        otherwise `ERR_LOT_NOT_AVAILABLE`."

        Design: Corner/errors/error_lot_not_available_on_reuse
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][0], product_series_id=env["series"]["id"]),
            community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE, 409)


class TestStatePriorityBeatsFiscalQuota:
    def test_closed_community_reports_not_open_over_quota(self, api, community_manager_headers,
                                                          division_president_headers):
        """PRD §2.9: "6. The target resource's own state or phase permits the
        operation (`ERR_INVALID_STATE`, `ERR_COMMUNITY_NOT_OPEN`,
        `ERR_INVALID_PHASE_TRANSITION`, `ERR_HOME_NOT_COMPLETE`)." and
        "Business-fiscal checks — the overheld posture block (`ERR_STARTS_BLOCKED_OVERHELD`), pacing quota (`ERR_STARTS_QUOTA_EXCEEDED`), framing capacity (`ERR_NO_CAPACITY_REMAINING`)".

        Design: Difficulty/priority_pair_validation_conflict/home_start_state_beats_fiscal_quota
        """
        env = setup_ready_community(api, lot_count=5, max_starts=1, committed_units=20)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        # Drive the community to CLOSED (quota is also exhausted).
        for _ in range(3):
            get_success_data(api.advance_phase(env["community"]["id"], division_president_headers))
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][1], product_series_id=env["series"]["id"]),
            community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_OPEN, 409)

    def test_state_error_also_wins_when_only_state_fails(self, api, community_manager_headers,
                                                         division_president_headers):
        """PRD §2.9: "6. The target resource's own state or phase permits the
        operation (`ERR_INVALID_STATE`, `ERR_COMMUNITY_NOT_OPEN`,
        `ERR_INVALID_PHASE_TRANSITION`, `ERR_HOME_NOT_COMPLETE`)." and
        "Business-fiscal checks — the overheld posture block (`ERR_STARTS_BLOCKED_OVERHELD`), pacing quota (`ERR_STARTS_QUOTA_EXCEEDED`), framing capacity (`ERR_NO_CAPACITY_REMAINING`)".

        Design: Difficulty/priority_pair_validation_conflict/home_start_state_beats_fiscal_quota
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=20)
        for _ in range(3):
            get_success_data(api.advance_phase(env["community"]["id"], division_president_headers))
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][0], product_series_id=env["series"]["id"]),
            community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_OPEN, 409)


class TestIdempotentHomeCreate:
    def test_replay_same_key_and_body_returns_same_home(self, api, community_manager_headers):
        """PRD §2.6: "Re-sending a POST with the same `Idempotency-Key` and an
        identical request body returns the original result without re-executing
        side effects."

        Design: Corner/cross_cutting/idempotent_home_create_replay
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        payload = create_home_payload(lot_id=env["lot_ids"][0],
                                      product_series_id=env["series"]["id"])
        first = validate_success(api.create_home(env["community"]["id"], payload,
                                                 community_manager_headers,
                                                 idem_key="idem-home-1"), 201)
        second = validate_success(api.create_home(env["community"]["id"], payload,
                                                  community_manager_headers,
                                                  idem_key="idem-home-1"), 201)
        assert second["id"] == first["id"]
        community = get_success_data(api.get_community(env["community"]["id"],
                                                       community_manager_headers))
        assert community["standing_spec_count"] == 1

    def test_same_key_different_body_rejected(self, api, community_manager_headers):
        """PRD §2.6: "Reusing the same key with a different request body is
        rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409)."

        Design: Corner/cross_cutting/idempotent_home_create_replay
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        payload = create_home_payload(lot_id=env["lot_ids"][0],
                                      product_series_id=env["series"]["id"])
        validate_success(api.create_home(env["community"]["id"], payload,
                                         community_manager_headers,
                                         idem_key="idem-home-2"), 201)
        replay = api.create_home(env["community"]["id"],
                                 create_home_payload(lot_id=env["lot_ids"][1],
                                                     product_series_id=env["series"]["id"],
                                                     base_price_cents=41_000_000),
                                 community_manager_headers, idem_key="idem-home-2")
        validate_error(replay, ApiErrorId.ERR_IDEMPOTENCY_REPLAY_MISMATCH, 409)


class TestImmediateConsistency:
    def test_counters_visible_immediately_after_start(self, api, community_manager_headers):
        """PRD §3.6: "the community's `standing_spec_count` increases by 1,
        `starts_this_period` increases by 1, the selected framing commitment's
        `allocated_units` increases by 1 (and its `remaining_units` decreases by
        1, preserving the invariant that `committed_units` always equals
        allocated plus remaining), the community's posture is recomputed, and
        the community's `version` increments by 1."

        Design: Corner/consistency/write_then_read_immediate_consistency
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        community = get_success_data(api.get_community(env["community"]["id"],
                                                       community_manager_headers))
        assert community["standing_spec_count"] == 1
        assert community["starts_this_period"] == 1

    def test_commitment_allocation_visible_immediately(self, api, community_manager_headers):
        """PRD §3.6: "the community's `standing_spec_count` increases by 1,
        `starts_this_period` increases by 1, the selected framing commitment's
        `allocated_units` increases by 1 (and its `remaining_units` decreases by
        1, preserving the invariant that `committed_units` always equals
        allocated plus remaining), the community's posture is recomputed, and
        the community's `version` increments by 1."

        Design: Corner/consistency/write_then_read_immediate_consistency
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        commitment = get_success_data(api.get_capacity_commitment(
            env["commitment"]["id"], community_manager_headers))
        assert commitment["allocated_units"] == 1
        assert commitment["remaining_units"] == 9
