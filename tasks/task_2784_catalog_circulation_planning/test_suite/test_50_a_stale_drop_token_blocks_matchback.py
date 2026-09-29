"""The second concurrency token behaves like the first, and it loses to the state guard.

Opening a matchback run bumps the *drop's* version, so the token that authorised the read
is spent the moment the read exists. The replay is refused and supersedes nothing. The
interesting leg is priority: a call aimed at the plan's second drop — still `PLANNED`, and
whose current version the borrowed token does not match either — reports the state
rejection, never the 412, because the transition check sits above the version check.
"""
from test_helpers import (
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER_1,
    PLANNER_2,
    allocate,
    approve_plan,
    assert_matchback_run,
    cost_plan,
    create_matchback_run_payload,
    fetch_drop,
    ingest_orders,
    iso_utc,
    mail_drop,
    new_drop,
    new_housefile_line,
    new_plan,
    new_presort_batch,
    new_season,
    new_segment,
    online_order,
    presort_drop,
    run_merge_purge,
    set_clock,
    submit_plan,
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

FIRST_IN_HOME = iso_utc("2026-09-15")
SECOND_IN_HOME = iso_utc("2026-10-20")
MAIL_CLOCK = iso_utc("2026-09-16")
READ_CLOCK = iso_utc("2026-09-25")


def _a_mailed_drop_beside_a_still_planned_one() -> dict:
    """One approved plan carrying two drops: drop 1 has been presorted and mailed, so its
    single MAIL contact event is dated 2026-09-15; drop 2 was opened while the plan was
    still a draft, carries no audience, and is therefore untouched in `PLANNED`. Two online
    orders for the mailed segment then land inside a thirty-day look-back."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"], headers=BROKER)

    first = new_drop(
        plan["id"], drop_number=1, in_home_date=FIRST_IN_HOME, page_count=64
    )
    second = new_drop(
        plan["id"], drop_number=2, in_home_date=SECOND_IN_HOME, page_count=64
    )
    new_housefile_line(first["id"], segment["id"], requested_quantity=20000)
    first = allocate(first["id"])

    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan.
    first = fetch_drop(first["id"])
    new_presort_batch(first["id"], first["planned_quantity"], "FIVE_DIGIT")

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_2)
    approve_plan(plan["id"], DIRECTOR_9)

    presort_drop(first["id"])
    set_clock(MAIL_CLOCK)
    first = mail_drop(first["id"])
    assert first["production_status"] == "MAILED"

    set_clock(READ_CLOCK)
    ingest_orders(
        [
            online_order("ORD-1", segment["id"], iso_utc("2026-09-15"), 40000),
            online_order("ORD-2", segment["id"], iso_utc("2026-09-20"), 30000),
        ]
    )

    second = fetch_drop(second["id"])
    assert second["production_status"] == "PLANNED"
    assert second["measurement_status"] == "PENDING"
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "mailed": fetch_drop(first["id"]),
        "planned": second,
    }


def _matchback(api, drop_id, token, variant="LAST_TOUCH_MAIL"):
    return api.create_matchback_run(
        drop_id, create_matchback_run_payload(token, variant, 30), ANALYST
    )


class TestTheReadSpendsItsOwnToken:
    def test_opening_the_run_bumps_the_drop_and_leaves_production_alone(self, api):
        """PRD §2.9: "When the check passes, the accepted value is persisted on the run as
        `observed_drop_version`."
        PRD §3.9: "On the measurement dimension, a drop in `PENDING` moves
        `PENDING → MATCHBACK_OPEN` and the run is created in status `OPEN`."
        PRD §3.9: "Either way the drop's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_version_blocks_a_matchback_run
        """
        world = _a_mailed_drop_beside_a_still_planned_one()
        drop_id = world["mailed"]["id"]
        first_token = world["mailed"]["version"]

        run = validate_success(_matchback(api, drop_id, first_token), 201)
        assert_matchback_run(run)
        assert run["status"] == "OPEN"
        assert run["observed_drop_version"] == first_token
        assert run["attributed_demand_cents"] == 70000

        drop = fetch_drop(drop_id, ANALYST)
        assert drop["measurement_status"] == "MATCHBACK_OPEN"
        assert drop["production_status"] == "MAILED"
        assert drop["version"] == first_token + 1


class TestTheReplayedTokenSupersedesNothing:
    def test_the_spent_token_is_a_stale_drop_version_and_the_open_run_survives(
        self, api
    ):
        """PRD §2.9: "If `expected_drop_version` does not equal the drop's current
        `version`, the request is rejected with `ERR_STALE_DROP_VERSION` and HTTP status
        412."
        PRD §3.9: "A drop already in `MATCHBACK_OPEN` takes a self-loop: every existing run
        of that drop in status `OPEN` or `FINALIZED` moves to `SUPERSEDED` with its own
        `version` incremented by one, and a fresh run is created in `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_version_blocks_a_matchback_run
        """
        world = _a_mailed_drop_beside_a_still_planned_one()
        drop_id = world["mailed"]["id"]
        first_token = world["mailed"]["version"]
        first_run = validate_success(_matchback(api, drop_id, first_token), 201)
        second_token = fetch_drop(drop_id, ANALYST)["version"]

        replay = _matchback(api, drop_id, first_token, "FRACTIONAL_MULTI_TOUCH")
        validate_error(replay, "ERR_STALE_DROP_VERSION", 412)

        rows, meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_run["id"]
        assert rows[0]["status"] == "OPEN"
        assert fetch_drop(drop_id, ANALYST)["version"] == second_token


class TestTheStateGuardOutranksTheVersionGuard:
    def test_a_matchback_on_the_planned_drop_reports_the_state_not_the_stale_token(
        self, api
    ):
        """PRD §3.9: "The drop's `production_status` must be `MAILED` or `DELIVERED`,
        otherwise `ERR_INVALID_DROP_STATE` — this is the single guard that couples the drop's
        two dimensions, and it reads `production_status` without changing it."
        PRD §2.10: "10. **The supplied expected parent version matches**, on
        `POST /catalog-circulation/circulation-plans/{id}/merge-purge-runs` and
        `POST /catalog-circulation/drops/{id}/matchback-runs` — otherwise
        `ERR_STALE_PLAN_VERSION` or `ERR_STALE_DROP_VERSION` (412)."
        PRD §2.10: "Checks run in the fixed order below; the first violated check wins and
        short-circuits every later check."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_version_blocks_a_matchback_run
        """
        world = _a_mailed_drop_beside_a_still_planned_one()
        borrowed_token = world["mailed"]["version"]
        planned = world["planned"]
        # The borrowed token is wrong for drop 2 as well, so both guards are violated.
        assert borrowed_token != planned["version"]

        refused = _matchback(api, planned["id"], borrowed_token)
        error = validate_error(refused, "ERR_INVALID_DROP_STATE", 409)
        assert error["error_id"] != "ERR_STALE_DROP_VERSION"

        still_planned = fetch_drop(planned["id"], ANALYST)
        assert still_planned["measurement_status"] == "PENDING"
        assert still_planned["production_status"] == "PLANNED"
        assert still_planned["version"] == planned["version"]

    def test_the_planned_drop_gets_no_run_row_at_all(self, api):
        """PRD §3.9: "The drop's `production_status` must be `MAILED` or `DELIVERED`,
        otherwise `ERR_INVALID_DROP_STATE` — this is the single guard that couples the drop's
        two dimensions, and it reads `production_status` without changing it."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_version_blocks_a_matchback_run
        """
        world = _a_mailed_drop_beside_a_still_planned_one()
        planned = world["planned"]

        validate_error(
            _matchback(api, planned["id"], planned["version"]),
            "ERR_INVALID_DROP_STATE",
            409,
        )

        _, meta = validate_paginated(
            api.list_matchback_runs(planned["id"], ANALYST)
        )
        assert meta["total_count"] == 0


class TestTheRefreshedTokenSupersedesTheEarlierRead:
    def test_the_retry_opens_a_second_run_and_retires_the_first(self, api):
        """PRD §3.9: "A drop already in `MATCHBACK_OPEN` takes a self-loop: every existing
        run of that drop in status `OPEN` or `FINALIZED` moves to `SUPERSEDED` with its own
        `version` incremented by one, and a fresh run is created in `OPEN`."
        PRD §3.9: "Either way the drop's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_version_blocks_a_matchback_run
        """
        world = _a_mailed_drop_beside_a_still_planned_one()
        drop_id = world["mailed"]["id"]
        first_token = world["mailed"]["version"]
        first_run = validate_success(_matchback(api, drop_id, first_token), 201)
        second_token = fetch_drop(drop_id, ANALYST)["version"]
        validate_error(
            _matchback(api, drop_id, first_token, "FRACTIONAL_MULTI_TOUCH"),
            "ERR_STALE_DROP_VERSION",
            412,
        )

        second_run = validate_success(
            _matchback(api, drop_id, second_token, "FRACTIONAL_MULTI_TOUCH"), 201
        )
        assert second_run["status"] == "OPEN"
        assert second_run["observed_drop_version"] == second_token

        rows, meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first_run["id"]]["status"] == "SUPERSEDED"
        assert by_id[second_run["id"]]["status"] == "OPEN"

        drop = fetch_drop(drop_id, ANALYST)
        assert drop["version"] == second_token + 1
        assert drop["production_status"] == "MAILED"
