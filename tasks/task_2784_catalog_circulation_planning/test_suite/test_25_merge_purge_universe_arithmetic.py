"""How many distinct mailable names actually exist, and in what order they are
counted.

Two independent filters decide the housefile contribution: only leaves count, and
a leaf whose strategy is SUPPRESS_ONLY is counted into gross and then subtracted
rather than quietly skipped. The rental side is order-sensitive, because only the
first list in processing order escapes the inter-list penalty — so the sort key is
observable in the universe itself, not merely in an array field.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    assert_merge_purge_names_conserved,
    assert_merge_purge_run,
    create_merge_purge_run_payload,
    fetch_rental,
    fetch_segment,
    new_plan,
    new_rental_in_state,
    new_season,
    new_segment,
    set_clock,
    validate_success,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

DORMANT_SCORING = {
    "recency_days": 731,
    "orders_12mo": 0,
    "ltv_cents": 4999,
    "avg_order_value_cents": 6000,
    "historical_response_rate_bps": 40,
}


def _a_three_deep_chain_one_dormant_leaf_and_a_housefile_only_run(api) -> dict:
    """S_TOP (10000) -> S_MID (20000) -> S_LEAF (30000) plus the unrelated
    dormant leaf S_SUP (5000), with one housefile-only merge-purge run over
    them."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    top = new_segment(
        season["id"], segment_code="S_TOP", housefile_count=10000, **SCORING
    )
    mid = new_segment(
        season["id"],
        segment_code="S_MID",
        housefile_count=20000,
        parent_segment_id=top["id"],
        **SCORING,
    )
    leaf = new_segment(
        season["id"],
        segment_code="S_LEAF",
        housefile_count=30000,
        parent_segment_id=mid["id"],
        **SCORING,
    )
    suppressed = new_segment(
        season["id"], segment_code="S_SUP", housefile_count=5000, **DORMANT_SCORING
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run = validate_success(
        api.create_merge_purge_run(
            plan["id"], create_merge_purge_run_payload(plan["version"], []), BROKER
        ),
        201,
    )
    return {
        "top": top,
        "mid": mid,
        "leaf": leaf,
        "suppressed": suppressed,
        "plan": plan,
        "run": run,
    }


class TestOnlyLeavesContributeNames:
    def test_the_two_rollup_parents_are_counted_out_of_the_gross(self, api):
        """PRD §3.3: "It starts by collecting every **leaf** housefile segment in
        the plan's season — every segment for which no other segment of that season
        names it as parent — and records how many such segments entered the
        computation as `housefile_leaf_segment_count`. The housefile gross
        contribution is the sum of `housefile_count` over those leaf segments;
        roll-up nodes contribute nothing, because their names are already counted
        through their children."

        Design: Corner/calculations/merge_purge_counts_leaf_segments_only_and_removes_suppressed_ones
        """
        world = _a_three_deep_chain_one_dormant_leaf_and_a_housefile_only_run(api)
        run = world["run"]

        assert_merge_purge_run(run)
        assert run["housefile_leaf_segment_count"] == 2
        assert run["gross_input_names"] == 35000
        assert run["gross_input_names"] != 65000

        assert fetch_segment(world["top"]["id"])["is_leaf"] is False
        assert fetch_segment(world["mid"]["id"])["is_leaf"] is False
        assert fetch_segment(world["leaf"]["id"])["is_leaf"] is True
        assert fetch_segment(world["suppressed"]["id"])["is_leaf"] is True

    def test_the_dormant_leaf_is_subtracted_rather_than_excluded(self, api):
        """PRD §3.3: "`suppressed_names` is the sum of `housefile_count` over just
        those leaf segments whose `contact_strategy` is `SUPPRESS_ONLY`.
        `gross_input_names` is the housefile gross contribution plus the sum of
        `gross_names` over every rental in the input set."

        Design: Corner/calculations/merge_purge_counts_leaf_segments_only_and_removes_suppressed_ones
        """
        world = _a_three_deep_chain_one_dormant_leaf_and_a_housefile_only_run(api)
        run = world["run"]

        assert world["suppressed"]["contact_strategy"] == "SUPPRESS_ONLY"
        assert run["suppressed_names"] == 5000
        assert run["gross_input_names"] == 35000
        assert run["duplicates_removed"] == 0
        assert run["processing_order"] == []

    def test_the_net_universe_and_its_conservation_identity(self, api):
        """PRD §3.3: "`net_mailable_names` is `gross_input_names` less
        `suppressed_names` less `duplicates_removed`, and it is the finite universe
        the allocation waterfall in §3.5 draws from. The conservation invariant of
        §2.7 must hold on the persisted figures."

        Design: Corner/calculations/merge_purge_counts_leaf_segments_only_and_removes_suppressed_ones
        """
        world = _a_three_deep_chain_one_dormant_leaf_and_a_housefile_only_run(api)
        run = world["run"]

        assert run["net_mailable_names"] == 30000
        assert run["status"] == "COMPLETED"
        assert_merge_purge_names_conserved(run)
        assert run["gross_input_names"] == (
            run["net_mailable_names"]
            + run["suppressed_names"]
            + run["duplicates_removed"]
        )


def _two_rentals_created_in_the_opposite_order_to_their_scores(api) -> dict:
    """R_LOW is registered first and modeled at 500, R_HIGH second at 900, and the
    run is handed the pair in creation order so the payload order cannot be
    mistaken for the processing order."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    new_segment(season["id"], segment_code="S_A", housefile_count=30000, **SCORING)

    low = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score=500,
        delivered_gross_names=10000,
        list_source_name="R_LOW",
        requested_gross_names=10000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=4000,
    )
    high = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score=900,
        delivered_gross_names=20000,
        list_source_name="R_HIGH",
        requested_gross_names=20000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=1500,
        inter_list_overlap_bps=3000,
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run = validate_success(
        api.create_merge_purge_run(
            plan["id"],
            create_merge_purge_run_payload(plan["version"], [low["id"], high["id"]]),
            BROKER,
        ),
        201,
    )
    return {"season": season, "low": low, "high": high, "plan": plan, "run": run}


class TestProcessingOrderIsScoreDescending:
    def test_the_order_reverses_both_the_creation_and_the_payload_order(self, api):
        """PRD §3.3: "The rentals are sorted by `coop_model_score` descending, with
        `created_at` ascending breaking ties, and the resulting sequence of rental
        identifiers is persisted as the run's `processing_order`. The housefile is
        always deduplicated against first, so every rental is compared against the
        housefile; rentals are then additionally compared against rentals already
        processed earlier in the same run."

        Design: Corner/calculations/merge_purge_processing_order_is_coop_score_desc_not_creation_order
        """
        world = _two_rentals_created_in_the_opposite_order_to_their_scores(api)
        run = world["run"]
        low_id = world["low"]["id"]
        high_id = world["high"]["id"]

        assert run["processing_order"] == [high_id, low_id]

        assert fetch_rental(high_id)["net_names_delivered"] == 17000
        assert fetch_rental(low_id)["net_names_delivered"] == 5400
        assert fetch_rental(high_id)["status"] == "NETTED"
        assert fetch_rental(low_id)["status"] == "NETTED"

    def test_only_the_first_list_escapes_the_inter_list_penalty(self, api):
        """PRD §3.3: "Walking the processing order from its first element, each
        rental's housefile duplicates are its `gross_names` multiplied by its
        `housefile_overlap_bps`, divided by ten thousand, floored to a whole number
        of names. Its inter-list duplicates are zero for the very first rental in
        processing order — by construction there is no previously-processed rental to
        collide with — and for every later rental they are its `gross_names` less its
        housefile duplicates, multiplied by its `inter_list_overlap_bps`, divided by
        ten thousand, floored."

        Design: Corner/calculations/merge_purge_processing_order_is_coop_score_desc_not_creation_order
        """
        world = _two_rentals_created_in_the_opposite_order_to_their_scores(api)
        run = world["run"]

        assert run["gross_input_names"] == 60000
        assert run["suppressed_names"] == 0
        assert run["duplicates_removed"] == 7600
        assert run["net_mailable_names"] == 52400

        assert run["duplicates_removed"] != 9100
        assert run["net_mailable_names"] != 50900
        assert_merge_purge_names_conserved(run)
