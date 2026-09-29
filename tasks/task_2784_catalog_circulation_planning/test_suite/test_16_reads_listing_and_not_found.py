"""Reading rows back: single fetches, filtered pages, and the eight 404 codes.

A read must return the stored row exactly as the create call reported it, must
never advance a version, and must be available to a role that did not author the
row. A collection read must count the filtered population rather than the table.
And an unassigned identifier must be answered by the code that belongs to the
entity family being addressed, never by one generic not-found.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_circulation_plan,
    assert_housefile_segment,
    fetch_season,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _season_with_one_segment_and_one_plan() -> dict:
    """The reference segment S_A and a DRAFT plan P1, both freshly created and
    never mutated."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    return {"season": season, "segment": segment, "plan": plan}


class TestSingleResourceReads:
    def test_an_analyst_reads_the_scored_segment_without_bumping_its_version(self, api):
        """PRD §3.1: "`rfm_score` then selects the segment's `segment_tier`:
        `BEST` at 800 or above, `CORE` at 600 or above, `OCCASIONAL` at 400 or
        above, `LAPSED` at 200 or above, and `DORMANT` below 200."

        Design: Corner/entities/single_resource_get_returns_the_stored_entity_unchanged
        """
        world = _season_with_one_segment_and_one_plan()
        created = world["segment"]

        assert created["rfm_score"] == 1000
        assert created["version"] == 1

        segment = validate_success(api.get_segment(created["id"], ANALYST), 200)

        assert_housefile_segment(segment)
        assert segment["rfm_score"] == created["rfm_score"] == 1000
        assert segment["version"] == created["version"] == 1
        assert segment["segment_tier"] == "BEST"
        assert segment["contact_strategy"] == "PREMIUM_FULL"
        assert segment["is_leaf"] is True
        assert segment["rollup_housefile_count"] == 30000
        assert segment["housefile_count"] == 30000
        assert segment["fatigue_score"] == 0
        assert segment["suppressed_at"] is None

        again = validate_success(api.get_segment(created["id"], ANALYST), 200)
        assert again["version"] == 1

    def test_a_broker_may_read_the_plan_it_did_not_author(self, api):
        """PRD §2.1: "All five roles may perform every read (`GET`) operation the
        service exposes, subject to the per-endpoint role lists in §4, which are
        narrower for a handful of reads."

        Design: Corner/entities/single_resource_get_returns_the_stored_entity_unchanged
        """
        world = _season_with_one_segment_and_one_plan()
        created = world["plan"]

        plan = validate_success(api.get_plan(created["id"], BROKER), 200)

        assert_circulation_plan(plan)
        assert plan["budget_cents"] == created["budget_cents"] == 20000000
        assert plan["status"] == "DRAFT"
        assert plan["uncommitted_budget_cents"] == 20000000
        assert plan["committed_cost_cents"] == 0
        assert plan["version"] == created["version"] == 1
        assert plan["revision_round"] == 0
        assert plan["costed_by_user_id"] is None
        assert plan["submitted_by_user_id"] is None
        assert plan["approved_by_user_id"] is None


def _two_seasons_with_four_segments() -> dict:
    """Season FW26 holding S_CCC, S_AAA and S_BBB created in that deliberately
    unsorted order, plus a second season SS26 holding one S_ZZZ the filter must
    exclude."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    other_season = new_season(season_code="SS26", fiscal_year=2026)

    new_segment(season["id"], segment_code="S_CCC")
    new_segment(season["id"], segment_code="S_AAA")
    new_segment(season["id"], segment_code="S_BBB")
    new_segment(other_season["id"], segment_code="S_ZZZ")

    return {"season": season, "other_season": other_season}


class TestFilteredSegmentListing:
    def test_the_first_page_counts_the_filtered_population_not_the_table(self, api):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the request's filters across all pages and `has_more` is true
        exactly when rows remain beyond the returned page."

        Design: Corner/entities/filtered_list_paginates_with_total_count_and_has_more
        """
        world = _two_seasons_with_four_segments()
        season_id = world["season"]["id"]

        page_one, meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": season_id, "limit": 2, "offset": 0})
        )
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(page_one) == 2

        _rows, other_meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": world["other_season"]["id"]})
        )
        assert other_meta["total_count"] == 1

    def test_the_second_page_continues_the_code_ordering_and_closes_has_more(self, api):
        """PRD §2.3: "Several collections carry a domain-meaningful ordering
        instead, and these orderings are part of the contract because they
        determine which rows land on which page. Housefile segments are ordered by
        `segment_code` ascending."

        Design: Corner/entities/filtered_list_paginates_with_total_count_and_has_more
        """
        world = _two_seasons_with_four_segments()
        season_id = world["season"]["id"]

        page_one, _meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": season_id, "limit": 2, "offset": 0})
        )
        assert [row["segment_code"] for row in page_one] == ["S_AAA", "S_BBB"]

        page_two, meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": season_id, "limit": 2, "offset": 2})
        )
        assert meta["total_count"] == 3
        assert meta["offset"] == 2
        assert meta["has_more"] is False
        assert len(page_two) == 1
        assert [row["segment_code"] for row in page_two] == ["S_CCC"]
        assert "S_ZZZ" not in [
            row["segment_code"] for row in page_one + page_two
        ]


class TestEveryNotFoundCodeIsFamilySpecific:
    def test_eight_endpoints_each_answer_with_their_own_404_code(self, api):
        """PRD §2.8: "Each entity family has its own 404 code:
        `ERR_SEASON_NOT_FOUND` for a catalog season, `ERR_SEGMENT_NOT_FOUND` for a
        housefile segment, `ERR_RENTAL_NOT_FOUND` for a prospect list rental,
        `ERR_PLAN_NOT_FOUND` for a circulation plan, `ERR_DROP_NOT_FOUND` for a
        drop, `ERR_LINE_NOT_FOUND` for a circulation line,
        `ERR_PLACEMENT_NOT_FOUND` for a page placement, `ERR_TEST_CELL_NOT_FOUND`
        for a test cell, and `ERR_MATCHBACK_RUN_NOT_FOUND` for a matchback run."

        Design: Corner/entities/every_not_found_code_returns_404_for_a_nonexistent_uuid
        """
        set_clock(CLOCK_START)
        new_season(season_code="FW26", fiscal_year=2026)

        validate_error(
            api.get_season(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_SEASON_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_segment(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_SEGMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_rental(NON_EXISTENT_UUID, BROKER),
            ApiErrorId.ERR_RENTAL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_plan(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_PLAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_drop(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_DROP_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_test_cell(NON_EXISTENT_UUID, ANALYST),
            ApiErrorId.ERR_TEST_CELL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.delete_page_placement(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.finalize_matchback_run(NON_EXISTENT_UUID, ANALYST),
            ApiErrorId.ERR_MATCHBACK_RUN_NOT_FOUND.value,
            404,
        )

    def test_each_404_carries_the_error_envelope_and_the_service_stays_up(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/every_not_found_code_returns_404_for_a_nonexistent_uuid
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)

        probes = [
            (api.get_season(NON_EXISTENT_UUID, PLANNER),
             ApiErrorId.ERR_SEASON_NOT_FOUND.value),
            (api.get_drop(NON_EXISTENT_UUID, PLANNER),
             ApiErrorId.ERR_DROP_NOT_FOUND.value),
            (api.get_test_cell(NON_EXISTENT_UUID, ANALYST),
             ApiErrorId.ERR_TEST_CELL_NOT_FOUND.value),
        ]
        for response, expected_error_id in probes:
            error = validate_error(response, expected_error_id, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
            assert isinstance(error["message"], str) and error["message"].strip()
            assert error["error_id"] == expected_error_id

        alive = fetch_season(season["id"], ADMIN)
        assert alive["season_code"] == "FW26"
        assert alive["version"] == 1
