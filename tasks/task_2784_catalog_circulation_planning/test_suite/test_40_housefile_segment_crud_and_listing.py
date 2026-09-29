"""Writing one segment moves fields on another, and the reads see all of it.

The update leg carries the weight here. Amending only `housefile_count` on a child
leaves the child's score alone but re-derives the *parent's* roll-up, while amending
only `recency_days` re-runs the whole recency-frequency-monetary scoring and re-derives
the tier and the tier's default strategy. The collection is then filtered on two
columns no request ever set — `is_leaf` and `segment_tier` — so the filters have to run
against the derived state rather than against the stored payload.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    DIRECTOR,
    PLANNER,
    assert_housefile_segment,
    assert_instant_equals,
    assert_ordered_by,
    fetch_segment,
    new_season,
    new_segment,
    set_clock,
    validate_paginated,
    validate_success,
)

BEST_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand() -> dict:
    """Both segments carry the same scoring inputs — recency 45, seven orders and
    62000 cents of lifetime value — so only the name counts and the tree shape
    distinguish them."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    parent = new_segment(
        season["id"], segment_code="S_PARENT", housefile_count=10000, **BEST_SCORING
    )
    child = new_segment(
        season["id"],
        segment_code="S_CHILD",
        housefile_count=20000,
        parent_segment_id=parent["id"],
        **BEST_SCORING,
    )
    return {"season": season, "parent": parent, "child": child}


class TestTheWriteLegDerivesTheTreeShape:
    def test_registering_a_child_flips_the_parent_and_rolls_its_names_up(self, api):
        """PRD §3.1: "`is_leaf` is true exactly when no other segment in the service
        names this segment as its parent; a newly registered segment is therefore always
        a leaf, and registering a child immediately turns its parent's `is_leaf` false.
        `rollup_housefile_count` is a segment's own `housefile_count` plus the transitive
        sum of every descendant segment's `housefile_count`, so it is recomputed for a
        parent whenever a descendant is added, re-parented, or has its own count
        amended."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)
        parent = new_segment(
            season["id"],
            segment_code="S_PARENT",
            housefile_count=10000,
            **BEST_SCORING,
        )
        assert_housefile_segment(parent)
        assert parent["is_leaf"] is True
        assert parent["rollup_housefile_count"] == 10000
        assert parent["parent_segment_id"] is None

        child = new_segment(
            season["id"],
            segment_code="S_CHILD",
            housefile_count=20000,
            parent_segment_id=parent["id"],
            **BEST_SCORING,
        )
        assert child["is_leaf"] is True
        assert child["rollup_housefile_count"] == 20000

        reread = fetch_segment(parent["id"], ANALYST)
        assert reread["is_leaf"] is False
        assert reread["rollup_housefile_count"] == 30000

    def test_a_count_amendment_on_the_child_moves_the_parents_rollup(self, api):
        """PRD §3.1: "`rollup_housefile_count` is a segment's own `housefile_count`
        plus the transitive sum of every descendant segment's `housefile_count`, so it is
        recomputed for a parent whenever a descendant is added, re-parented, or has its
        own count amended."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()

        validate_success(
            api.update_segment(
                world["child"]["id"], {"housefile_count": 25000}, PLANNER
            ),
            200,
        )
        parent = fetch_segment(world["parent"]["id"], PLANNER)
        assert parent["housefile_count"] == 10000
        assert parent["rollup_housefile_count"] == 35000

    def test_a_count_amendment_leaves_the_recency_frequency_monetary_score_alone(
        self, api
    ):
        """PRD §3.1: "A planner may revise `recency_days`, `orders_12mo`, `ltv_cents`,
        `housefile_count`, `avg_order_value_cents`, `historical_response_rate_bps`,
        `parent_segment_id` or `contact_strategy` on an existing segment; the amendment
        re-runs the recency-frequency-monetary scoring and rewrites `rfm_score` and
        `segment_tier`."
        PRD §2.4: "`updated_at` is refreshed to the current instant on every mutation of
        the row, and `version` is an integer that starts at 1 on creation and increments
        by exactly 1 on every mutation — including mutations the row's owner did not
        request, such as a cascade reaching it from another aggregate."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()
        child = world["child"]
        assert child["rfm_score"] == 1000

        amended = validate_success(
            api.update_segment(child["id"], {"housefile_count": 25000}, PLANNER), 200
        )
        assert_housefile_segment(amended)
        assert amended["housefile_count"] == 25000
        assert amended["rfm_score"] == 1000
        assert amended["segment_tier"] == "BEST"
        assert amended["version"] == child["version"] + 1
        assert_instant_equals(
            amended["created_at"], child["created_at"], "segment created_at"
        )


class TestTheWriteLegReDerivesTheScoringColumns:
    def test_a_single_recency_amendment_re_runs_the_whole_score(self, api):
        """PRD §3.1: "A planner may revise `recency_days`, `orders_12mo`, `ltv_cents`,
        `housefile_count`, `avg_order_value_cents`, `historical_response_rate_bps`,
        `parent_segment_id` or `contact_strategy` on an existing segment; the amendment
        re-runs the recency-frequency-monetary scoring and rewrites `rfm_score` and
        `segment_tier`."
        PRD §3.1: "Recency is worth 40 points when `recency_days` is 90 or fewer, 30
        points when it is 180 or fewer, 18 points when it is 365 or fewer, 8 points when
        it is 730 or fewer, and 0 points beyond that."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()
        child = world["child"]

        amended = validate_success(
            api.update_segment(child["id"], {"recency_days": 400}, PLANNER), 200
        )
        assert amended["recency_days"] == 400
        assert amended["rfm_score"] == 680
        assert amended["rfm_score"] == (8 + 30 + 30) * 10
        assert amended["segment_tier"] == "CORE"
        assert amended["version"] == child["version"] + 1

    def test_the_re_derived_tier_supplies_its_own_default_strategy(self, api):
        """PRD §3.1: "The tier in turn supplies a default `contact_strategy` when the
        planner does not name one: `BEST` defaults to `PREMIUM_FULL`, both `CORE` and
        `OCCASIONAL` default to `STANDARD`, `LAPSED` defaults to `REACTIVATION`, and
        `DORMANT` defaults to `SUPPRESS_ONLY`."
        PRD §3.1: "An explicit `contact_strategy` in the amendment overrides the tier
        default, and this is the **only** way to lift a suppression that the
        contact-fatigue cascade has imposed."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()
        child = world["child"]
        assert child["segment_tier"] == "BEST"
        assert child["contact_strategy"] == "PREMIUM_FULL"

        amended = validate_success(
            api.update_segment(child["id"], {"recency_days": 400}, PLANNER), 200
        )
        assert amended["segment_tier"] == "CORE"
        assert amended["contact_strategy"] == "STANDARD"
        assert amended["suppressed_at"] is None


class TestTheCollectionFiltersRunAgainstDerivedColumns:
    def test_the_leaf_filter_returns_the_child_and_excludes_the_roll_up_node(
        self, api
    ):
        """PRD §3.1: "The collection read accepts `season_id`, `parent_segment_id`,
        `segment_tier`, `contact_strategy` and `is_leaf` as optional filters, which
        together serve as the reverse lookup from a season to its segments and from a
        parent to its children."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()

        rows, meta = validate_paginated(
            api.list_segments(
                DIRECTOR,
                params={"season_id": world["season"]["id"], "is_leaf": "true"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [world["child"]["id"]]

    def test_the_tier_filter_follows_the_amendment_that_moved_the_tier(self, api):
        """PRD §3.1: "The collection read accepts `season_id`, `parent_segment_id`,
        `segment_tier`, `contact_strategy` and `is_leaf` as optional filters, which
        together serve as the reverse lookup from a season to its segments and from a
        parent to its children."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()
        validate_success(
            api.update_segment(
                world["child"]["id"], {"recency_days": 400}, PLANNER
            ),
            200,
        )

        rows, meta = validate_paginated(
            api.list_segments(
                DIRECTOR,
                params={"season_id": world["season"]["id"], "segment_tier": "CORE"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [world["child"]["id"]]

        best_rows, best_meta = validate_paginated(
            api.list_segments(
                DIRECTOR,
                params={"season_id": world["season"]["id"], "segment_tier": "BEST"},
            )
        )
        assert best_meta["total_count"] == 1
        assert [row["id"] for row in best_rows] == [world["parent"]["id"]]


class TestTheListEnvelopeAndItsOrdering:
    def test_a_page_of_one_reports_the_full_match_count_and_more_to_come(self, api):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows matching the
        request's filters across all pages and `has_more` is true exactly when rows
        remain beyond the returned page."
        PRD §2.3: "Housefile segments are ordered by `segment_code` ascending."

        Design: Corner/endpoints/housefile_segment_crud_reads_writes_lists_and_has_no_delete
        """
        world = _a_parent_of_ten_thousand_and_a_child_of_twenty_thousand()

        rows, meta = validate_paginated(
            api.list_segments(
                PLANNER,
                params={"season_id": world["season"]["id"], "limit": 1, "offset": 0},
            )
        )
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(rows) == 1
        assert rows[0]["segment_code"] == "S_CHILD"

        second_page, second_meta = validate_paginated(
            api.list_segments(
                PLANNER,
                params={"season_id": world["season"]["id"], "limit": 1, "offset": 1},
            )
        )
        assert second_meta["has_more"] is False
        assert second_page[0]["segment_code"] == "S_PARENT"
        assert_ordered_by(rows + second_page, "segment_code")
