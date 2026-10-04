"""Methodology lifecycle and chart freeze tests: activation cascades, the
freeze/resolve diamond, the chart-week invalidation loop, and OCC guards.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_methodology,
    compute_week,
    create_chart,
    create_methodology_version,
    create_recurrent_rule,
    create_week,
    freeze_chart,
    get_chart,
    get_success_data,
    get_week,
    set_clock,
    setup_locked_week_with_sales,
    setup_open_week_scenario,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["chart_manager_headers"]


class TestChartWeekInvalidationLoop:
    def test_activation_invalidates_computed_week_back_to_locked(self, api):
        """PRD §3.2:"every week of the chart in `COMPUTED` status is
        invalidated back to `LOCKED` with its `computed_methodology_version_id`
        cleared and every entry of such a week reset (points to 0, rank
        cleared to null)"

    Design: Difficulty/non_linear_state_machine/chart_week_branching_invalidation_loop"""
        scenario = setup_locked_week_with_sales(sales_quantity=10)
        chart = scenario["chart"]
        week = scenario["week"]
        mv1 = scenario["mv"]
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        compute_week(week["id"])
        assert get_week(week["id"])["status"] == "COMPUTED"
        activate_methodology(chart, mv2)
        week_after = get_week(week["id"])
        assert week_after["status"] == "LOCKED", (
            f"COMPUTED week must be invalidated back to LOCKED, "
            f"got {week_after['status']}")
        assert week_after["computed_methodology_version_id"] is None

    def test_activation_supersedes_prior_active_version(self, api):
        """PRD §3.2:"the chart's prior `ACTIVE` revision, if any, transitions
        `ACTIVE → SUPERSEDED`; the chart's `current_methodology_version_id` is
        re-pointed to the newly activated revision"

    Design: Difficulty/non_linear_state_machine/chart_week_branching_invalidation_loop"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        mv1 = scenario["mv"]
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        activate_methodology(chart, mv2)
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        status_by_id = {v["id"]: v["status"] for v in versions}
        assert status_by_id[mv1["id"]] == "SUPERSEDED"
        assert status_by_id[mv2["id"]] == "ACTIVE"
        assert get_chart(chart["id"])["current_methodology_version_id"] == mv2["id"]


class TestMethodologyFreezeResolveDiamond:
    def test_freeze_resolve_named_version_emerges_active(self, api):
        """PRD §3.2:"the named revision must already be one of the chart's
        frozen revisions, and on resolution it alone transitions
        `FROZEN → ACTIVE` while every other revision of the chart transitions
        `FROZEN → SUPERSEDED`; the chart's `current_methodology_version_id`
        is re-pointed to the named revision"

    Design: Difficulty/non_linear_state_machine/methodology_version_diamond_freeze_resolve"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        mv1 = create_methodology_version(chart, version_label="v1")
        activate_methodology(chart, mv1)
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        freeze = freeze_chart(chart["id"])
        resp = api.resolve_freeze(
            chart["id"], freeze["id"],
            {"resolved_by_methodology_version_id": mv2["id"]}, MANAGER)
        resolved = validate_success(resp, expected_status=200)
        assert resolved["status"] == "RESOLVED"
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        status_by_id = {v["id"]: v["status"] for v in versions}
        assert status_by_id[mv2["id"]] == "ACTIVE", "FROZEN->ACTIVE join branch"
        assert status_by_id[mv1["id"]] == "SUPERSEDED", (
            "all other frozen versions become SUPERSEDED")
        chart_after = get_chart(chart["id"])
        assert chart_after["current_methodology_version_id"] == mv2["id"]

    def test_freeze_moves_all_versions_to_frozen_and_blocks_activation(self, api):
        """PRD §3.2:"it creates a `ChartFreeze` in `ACTIVE` status, moves
        every methodology revision of the chart — whether `DRAFT` or
        `ACTIVE` — into `FROZEN`, and increments the chart's `version`"
    PRD §2.9:"While a `ChartFreeze` with status `ACTIVE` exists for a
        chart, five operations are blocked with `ERR_CHART_FROZEN` (HTTP 409):
        locking a week, computing a week, publishing a week, accepting a
        consumption report, and activating a methodology version"

    Design: Difficulty/non_linear_state_machine/methodology_version_diamond_freeze_resolve"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        mv1 = create_methodology_version(chart, version_label="v1")
        activate_methodology(chart, mv1)
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        freeze_chart(chart["id"])
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        status_by_id = {v["id"]: v["status"] for v in versions}
        assert status_by_id[mv1["id"]] == "FROZEN"
        assert status_by_id[mv2["id"]] == "FROZEN"
        chart_now = get_chart(chart["id"])
        resp = api.activate_methodology_version(
            chart["id"], mv2["id"],
            {"expected_chart_version": chart_now["version"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)


class TestWeekLockGatedByFreeze:
    def test_lock_blocked_while_frozen_succeeds_after_resolve(self, api):
        """PRD §2.9:"While a `ChartFreeze` with status `ACTIVE` exists for a
        chart, five operations are blocked with `ERR_CHART_FROZEN` (HTTP 409):
        locking a week, computing a week, publishing a week, accepting a
        consumption report, and activating a methodology version"

    Design: Difficulty/cross_entity_state_dependency/week_lock_gated_by_chart_freeze"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        week = scenario["week"]
        set_clock(week["closes_at"])
        freeze = freeze_chart(chart["id"])
        resp = api.lock_week(week["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)
        get_success_data(api.resolve_freeze(
            chart["id"], freeze["id"],
            {"resolved_by_methodology_version_id": scenario["mv"]["id"]},
            MANAGER))
        resp = api.lock_week(week["id"], MANAGER)
        locked = validate_success(resp, expected_status=200)
        assert locked["status"] == "LOCKED"

    def test_lock_after_close_on_unfrozen_chart_succeeds(self, api):
        """PRD §3.5: "Locking requires the logical clock's current time to
        have reached the week's `closes_at` (a premature lock is rejected
        with `ERR_WEEK_NOT_CLOSED`, HTTP 409) and no active freeze on the
        chart"

        Design: Difficulty/cross_entity_state_dependency/week_lock_gated_by_chart_freeze"""
        scenario = setup_open_week_scenario()
        week = scenario["week"]
        set_clock(week["closes_at"])
        resp = api.lock_week(week["id"], MANAGER)
        locked = validate_success(resp, expected_status=200)
        assert locked["status"] == "LOCKED"


class TestFreezeOcc:
    def test_second_freeze_with_stale_version_rejected(self, api):
        """PRD §2.7:"If the chart's current `version` has advanced past the
        supplied value — for example because another writer has since
        activated a methodology revision or changed the chart's freeze
        posture — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

    Design: Corner/cross_cutting_layers/freeze_occ_stale_version_rejected"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        v_obs = get_chart(chart["id"])["version"]
        freeze1 = freeze_chart(chart["id"], reason="first freeze")
        assert freeze1["status"] == "ACTIVE"
        resp = api.freeze_chart(
            chart["id"],
            {"reason": "second freeze with stale view",
             "expected_chart_version": v_obs},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        freezes, meta = __import__("test_helpers").validate_paginated(
            api.list_chart_freezes(chart["id"], MANAGER,
                                   params={"status": "ACTIVE"}))
        assert len(freezes) == 1 and freezes[0]["id"] == freeze1["id"]

    def test_activation_with_stale_chart_version_rejected(self, api):
        """PRD §2.7: "Each requires the request to carry
        `expected_chart_version`, a non-optional integer holding the caller's
        last-observed `version` of the chart"
        PRD §2.7: "the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), preventing the caller from acting on a chart state it has not
        observed"

        Design: Corner/errors/stale_version_error_triggerable_on_activate"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        mv = create_methodology_version(chart)
        activate_methodology(chart, mv)
        stale_version = get_chart(chart["id"])["version"] - 1
        resp = api.activate_methodology_version(
            chart["id"], mv["id"],
            {"expected_chart_version": stale_version}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestChartVersionIncrements:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4:"The `version` starts at 1 on creation and increments by
        exactly 1 on every mutation of the resource, including system-driven
        cascades"

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        assert chart["version"] == 1
        mv1 = create_methodology_version(chart, version_label="v1")
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        activate_methodology(chart, mv1)
        assert get_chart(chart["id"])["version"] == 2
        activate_methodology(chart, mv2)
        assert get_chart(chart["id"])["version"] == 3


class TestMethodologyActiveSingletonInvariant:
    def test_single_active_version_across_activation_pair(self, api):
        """PRD §3.2: "Its side effects are sweeping: the chart's prior
        `ACTIVE` revision, if any, transitions `ACTIVE → SUPERSEDED`; the
        chart's `current_methodology_version_id` is re-pointed to the newly
        activated revision"

        Design: Difficulty/compensating_invariant/methodology_activation_supersession_singleton_invariant"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        mv1 = create_methodology_version(chart, version_label="v1")
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        activate_methodology(chart, mv1)
        chart_now = get_chart(chart["id"])
        assert chart_now["current_methodology_version_id"] == mv1["id"]
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        active = [v for v in versions if v["status"] == "ACTIVE"]
        assert len(active) == 1 and active[0]["id"] == mv1["id"]
        activate_methodology(chart, mv2)
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        active = [v for v in versions if v["status"] == "ACTIVE"]
        assert len(active) == 1 and active[0]["id"] == mv2["id"]
        assert get_chart(chart["id"])["current_methodology_version_id"] == mv2["id"]

    def test_freeze_resolve_preserves_active_singleton(self, api):
        """PRD §3.2:"on resolution it alone transitions `FROZEN → ACTIVE`
        while every other revision of the chart transitions
        `FROZEN → SUPERSEDED`"

    Design: Difficulty/compensating_invariant/methodology_activation_supersession_singleton_invariant"""
        rr = create_recurrent_rule()
        chart = create_chart(rr["id"])
        mv1 = create_methodology_version(chart, version_label="v1")
        activate_methodology(chart, mv1)
        mv2 = create_methodology_version(chart, version_label="v2", w_sales=2.0)
        freeze = freeze_chart(chart["id"])
        get_success_data(api.resolve_freeze(
            chart["id"], freeze["id"],
            {"resolved_by_methodology_version_id": mv1["id"]}, MANAGER))
        versions = get_success_data(
            api.list_methodology_versions(chart["id"], MANAGER,
                                          params={"limit": 100}))
        active = [v for v in versions if v["status"] == "ACTIVE"]
        assert len(active) == 1 and active[0]["id"] == mv1["id"]
        assert get_chart(chart["id"])["current_methodology_version_id"] == mv1["id"]
