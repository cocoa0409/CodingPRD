"""The token that just worked is the token that must now fail.

A completed merge-purge run increments the plan's own `version`, so the run invalidates
the very concurrency token that authorised it. Replaying that token is refused, and the
refusal is inert in three separate ways: no run row appears, the previously completed
universe is still `COMPLETED`, and the plan's version has not moved. Retrying with the
refreshed token then supersedes exactly one prior run, and a token far *ahead* of reality
is refused identically, so the guard is equality rather than a lower bound.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR,
    assert_merge_purge_run,
    create_merge_purge_run_payload,
    fetch_plan,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_draft_plan_over_a_thirty_thousand_name_housefile() -> dict:
    """One leaf segment of 30000 names and nothing suppressed, so an empty input set
    still yields a positive universe and the run takes the completed branch."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    assert plan["status"] == "DRAFT"
    return {"season": season, "segment": segment, "plan": plan}


def _run_against(api, plan_id, token):
    return api.create_merge_purge_run(
        plan_id, create_merge_purge_run_payload(token, []), BROKER
    )


class TestTheRunInvalidatesItsOwnToken:
    def test_the_accepted_token_is_persisted_and_then_immediately_outdated(self, api):
        """PRD §2.9: "When the check passes, the accepted value is persisted on the run as
        `observed_plan_version`."
        PRD §3.3: "When `net_mailable_names` is greater than zero the run takes the
        `PENDING → COMPLETED` branch: `gross_input_names`, `suppressed_names`,
        `duplicates_removed`, `net_mailable_names`, `processing_order` and
        `housefile_leaf_segment_count` are all persisted; every rental in the input set
        moves `DELIVERED → NETTED` with its `net_names_delivered` written to its post-dedup
        count; every *other* merge-purge run of the same plan sitting in `COMPLETED` moves
        to `SUPERSEDED`; the accepted version is stored as `observed_plan_version`; and the
        plan's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_plan_version_blocks_a_merge_purge_run
        """
        world = _a_draft_plan_over_a_thirty_thousand_name_housefile()
        plan_id = world["plan"]["id"]
        first_token = fetch_plan(plan_id, BROKER)["version"]

        run = validate_success(_run_against(api, plan_id, first_token), 201)
        assert_merge_purge_run(run)
        assert run["status"] == "COMPLETED"
        assert run["observed_plan_version"] == first_token
        assert run["net_mailable_names"] == 30000

        second_token = fetch_plan(plan_id, BROKER)["version"]
        assert second_token == first_token + 1


class TestTheReplayIsRefusedAndInert:
    def test_replaying_the_spent_token_is_a_stale_plan_version(self, api):
        """PRD §2.9: "If `expected_plan_version` does not equal the plan's current
        `version`, the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP status
        412."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_plan_version_blocks_a_merge_purge_run
        """
        world = _a_draft_plan_over_a_thirty_thousand_name_housefile()
        plan_id = world["plan"]["id"]
        first_token = fetch_plan(plan_id, BROKER)["version"]
        validate_success(_run_against(api, plan_id, first_token), 201)

        replay = _run_against(api, plan_id, first_token)
        validate_error(replay, "ERR_STALE_PLAN_VERSION", 412)

    def test_the_refusal_creates_no_run_supersedes_nothing_and_spends_no_version(
        self, api
    ):
        """PRD §3.3: "A run moves `COMPLETED → SUPERSEDED` when a later run on the same
        plan takes the completed branch, or when the plan itself is cancelled; nothing
        happens beyond the status change and the row's `updated_at` refresh."
        PRD §2.10: "Checks run in the fixed order below; the first violated check wins and
        short-circuits every later check."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_plan_version_blocks_a_merge_purge_run
        """
        world = _a_draft_plan_over_a_thirty_thousand_name_housefile()
        plan_id = world["plan"]["id"]
        first_token = fetch_plan(plan_id, BROKER)["version"]
        first_run = validate_success(_run_against(api, plan_id, first_token), 201)
        second_token = fetch_plan(plan_id, BROKER)["version"]

        validate_error(
            _run_against(api, plan_id, first_token), "ERR_STALE_PLAN_VERSION", 412
        )

        rows, meta = validate_paginated(api.list_merge_purge_runs(plan_id, DIRECTOR))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_run["id"]
        assert rows[0]["status"] == "COMPLETED"
        assert fetch_plan(plan_id, BROKER)["version"] == second_token


class TestTheRefreshedTokenSupersedesExactlyOneRun:
    def test_the_retry_completes_and_retires_the_previous_universe(self, api):
        """PRD §3.3: "When `net_mailable_names` is greater than zero the run takes the
        `PENDING → COMPLETED` branch: `gross_input_names`, `suppressed_names`,
        `duplicates_removed`, `net_mailable_names`, `processing_order` and
        `housefile_leaf_segment_count` are all persisted; every rental in the input set
        moves `DELIVERED → NETTED` with its `net_names_delivered` written to its post-dedup
        count; every *other* merge-purge run of the same plan sitting in `COMPLETED` moves
        to `SUPERSEDED`; the accepted version is stored as `observed_plan_version`; and the
        plan's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_plan_version_blocks_a_merge_purge_run
        """
        world = _a_draft_plan_over_a_thirty_thousand_name_housefile()
        plan_id = world["plan"]["id"]
        first_token = fetch_plan(plan_id, BROKER)["version"]
        first_run = validate_success(_run_against(api, plan_id, first_token), 201)
        second_token = fetch_plan(plan_id, BROKER)["version"]
        validate_error(
            _run_against(api, plan_id, first_token), "ERR_STALE_PLAN_VERSION", 412
        )

        second_run = validate_success(_run_against(api, plan_id, second_token), 201)
        assert second_run["status"] == "COMPLETED"
        assert second_run["observed_plan_version"] == second_token

        rows, meta = validate_paginated(api.list_merge_purge_runs(plan_id, DIRECTOR))
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first_run["id"]]["status"] == "SUPERSEDED"
        assert [row["status"] for row in rows].count("COMPLETED") == 1
        assert fetch_plan(plan_id, BROKER)["version"] == second_token + 1


class TestTheGuardIsEqualityNotALowerBound:
    def test_a_token_far_ahead_of_reality_is_refused_the_same_way(self, api):
        """PRD §2.9: "If `expected_plan_version` does not equal the plan's current
        `version`, the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP status
        412."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_plan_version_blocks_a_merge_purge_run
        """
        world = _a_draft_plan_over_a_thirty_thousand_name_housefile()
        plan_id = world["plan"]["id"]
        current = fetch_plan(plan_id, BROKER)["version"]

        ahead = _run_against(api, plan_id, current + 50)
        validate_error(ahead, "ERR_STALE_PLAN_VERSION", 412)

        _, meta = validate_paginated(api.list_merge_purge_runs(plan_id, DIRECTOR))
        assert meta["total_count"] == 0
        assert fetch_plan(plan_id, BROKER)["version"] == current
