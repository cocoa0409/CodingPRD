"""Three ways of naming the wrong rental, then the one link that works.

An identifier that resolves to nothing and a delivered identifier belonging to
another season are refused the same way, because the PRD makes same-season membership
part of resolution itself rather than a state check; a rental of the right season that
never left MODELED is refused as a state error instead. The link that finally lands
nets both rentals in coop-score order, and the first list in that order pays no
inter-list penalty at all, which is what makes the pinned order observable.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR,
    NON_EXISTENT_UUID,
    assert_merge_purge_names_conserved,
    assert_merge_purge_run,
    create_merge_purge_run_payload,
    fetch_plan,
    fetch_rental,
    new_plan,
    new_rental_in_state,
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


def _a_plan_facing_four_candidate_rentals() -> dict:
    """FW26 holds one 30000-name leaf segment, the plan, two DELIVERED rentals and
    one stuck in MODELED; SS27 holds a DELIVERED rental of its own that the FW26 plan
    has no business consuming."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    other_season = new_season(season_code="SS27", fiscal_year=2027)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)

    first = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score=900,
        delivered_gross_names=10000,
        list_source_name="R1",
        requested_gross_names=10000,
        cost_per_thousand_cents=9000,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=0,
    )
    second = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score=500,
        delivered_gross_names=20000,
        list_source_name="R2",
        requested_gross_names=20000,
        cost_per_thousand_cents=9000,
        housefile_overlap_bps=1500,
        inter_list_overlap_bps=3000,
    )
    modeled = new_rental_in_state(
        season["id"],
        "MODELED",
        coop_model_score=700,
        list_source_name="R3",
        requested_gross_names=5000,
        cost_per_thousand_cents=9000,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=1000,
    )
    stranger = new_rental_in_state(
        other_season["id"],
        "DELIVERED",
        coop_model_score=800,
        delivered_gross_names=8000,
        list_source_name="R_OTHER",
        requested_gross_names=8000,
        cost_per_thousand_cents=9000,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=1000,
    )
    return {
        "season": season,
        "other_season": other_season,
        "segment": segment,
        "plan": plan,
        "first": first,
        "second": second,
        "modeled": modeled,
        "stranger": stranger,
    }


def _link(api, world, rental_ids):
    """One merge-purge attempt pinned to the plan's current version."""
    plan_version = fetch_plan(world["plan"]["id"], BROKER)["version"]
    return api.create_merge_purge_run(
        world["plan"]["id"],
        create_merge_purge_run_payload(plan_version, rental_ids),
        BROKER,
    )


class TestResolutionIncludesSeasonMembership:
    def test_an_identifier_that_resolves_to_nothing_is_a_not_found(self, api):
        """PRD §3.3: "Every element of `input_rental_ids` must resolve to a prospect
        list rental belonging to the *same* season as the plan, otherwise
        `ERR_RENTAL_NOT_FOUND`."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()

        response = _link(
            api, world, [world["first"]["id"], NON_EXISTENT_UUID]
        )
        validate_error(response, "ERR_RENTAL_NOT_FOUND", 404)

    def test_a_delivered_rental_of_another_season_is_refused_as_unresolvable(
        self, api
    ):
        """PRD §3.3: "Every element of `input_rental_ids` must resolve to a prospect
        list rental belonging to the *same* season as the plan, otherwise
        `ERR_RENTAL_NOT_FOUND`."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        assert world["stranger"]["status"] == "DELIVERED"
        assert world["stranger"]["season_id"] == world["other_season"]["id"]

        response = _link(
            api, world, [world["first"]["id"], world["stranger"]["id"]]
        )
        error = validate_error(response, "ERR_RENTAL_NOT_FOUND", 404)
        assert error["error_id"] != "ERR_RENTAL_NOT_NETTED"


class TestOnlyDeliveredRentalsMayEnterTheUniverse:
    def test_a_rental_still_in_modeled_is_a_state_error(self, api):
        """PRD §3.3: "And every resolved rental must be sitting in `DELIVERED` — a
        rental still in `REQUESTED`, `MODELED` or `ORDERED`, or one already `CANCELLED`,
        is rejected with `ERR_RENTAL_NOT_NETTED`."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        assert world["modeled"]["status"] == "MODELED"

        response = _link(
            api, world, [world["first"]["id"], world["modeled"]["id"]]
        )
        validate_error(response, "ERR_RENTAL_NOT_NETTED", 409)

    def test_the_three_refusals_leave_no_run_no_version_and_no_netting(self, api):
        """PRD §2.9: "When the check passes, the accepted value is persisted on the run
        as `observed_plan_version`."
        PRD §3.2: "The final procurement step is not a broker action at all: a rental
        moves `DELIVERED → NETTED` as a consequence of a merge-purge run completing with
        that rental in its input set, at which point `net_names_delivered` is written as
        the rental's `gross_names` less its own housefile and inter-list duplicate
        removals."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        opening_version = fetch_plan(world["plan"]["id"], BROKER)["version"]

        validate_error(
            _link(api, world, [world["first"]["id"], NON_EXISTENT_UUID]),
            "ERR_RENTAL_NOT_FOUND",
            404,
        )
        validate_error(
            _link(api, world, [world["first"]["id"], world["modeled"]["id"]]),
            "ERR_RENTAL_NOT_NETTED",
            409,
        )
        validate_error(
            _link(api, world, [world["first"]["id"], world["stranger"]["id"]]),
            "ERR_RENTAL_NOT_FOUND",
            404,
        )

        _, meta = validate_paginated(
            api.list_merge_purge_runs(world["plan"]["id"], BROKER)
        )
        assert meta["total_count"] == 0
        assert fetch_plan(world["plan"]["id"], BROKER)["version"] == opening_version

        assert fetch_rental(world["first"]["id"])["status"] == "DELIVERED"
        assert fetch_rental(world["first"]["id"])["net_names_delivered"] == 0
        assert fetch_rental(world["modeled"]["id"])["status"] == "MODELED"
        assert fetch_rental(world["stranger"]["id"])["status"] == "DELIVERED"


class TestTheLinkThatLandsPinsItsOrder:
    def test_the_run_completes_and_persists_the_coop_score_ordering(self, api):
        """PRD §3.3: "The rentals are sorted by `coop_model_score` descending, with
        `created_at` ascending breaking ties, and the resulting sequence of rental
        identifiers is persisted as the run's `processing_order`."
        PRD §2.9: "When the check passes, the accepted value is persisted on the run as
        `observed_plan_version`."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        opening_version = fetch_plan(world["plan"]["id"], BROKER)["version"]

        run = validate_success(
            _link(api, world, [world["first"]["id"], world["second"]["id"]]), 201
        )
        assert_merge_purge_run(run)
        assert run["status"] == "COMPLETED"
        assert run["observed_plan_version"] == opening_version
        assert run["processing_order"] == [
            world["first"]["id"],
            world["second"]["id"],
        ]

    def test_the_first_list_in_the_order_pays_no_inter_list_penalty(self, api):
        """PRD §3.3: "Its inter-list duplicates are zero for the very first rental in
        processing order — by construction there is no previously-processed rental to
        collide with — and for every later rental they are its `gross_names` less its
        housefile duplicates, multiplied by its `inter_list_overlap_bps`, divided by ten
        thousand, floored."
        PRD §3.2: "The final procurement step is not a broker action at all: a rental
        moves `DELIVERED → NETTED` as a consequence of a merge-purge run completing with
        that rental in its input set, at which point `net_names_delivered` is written as
        the rental's `gross_names` less its own housefile and inter-list duplicate
        removals."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        validate_success(
            _link(api, world, [world["first"]["id"], world["second"]["id"]]), 201
        )

        first = fetch_rental(world["first"]["id"])
        assert first["status"] == "NETTED"
        assert first["gross_names"] == 10000
        assert first["net_names_delivered"] == 9000

        second = fetch_rental(world["second"]["id"])
        assert second["status"] == "NETTED"
        assert second["gross_names"] == 20000
        assert second["net_names_delivered"] == 11900

    def test_the_universe_is_gross_less_suppressed_less_duplicates(self, api):
        """PRD §3.3: "`gross_input_names` is the housefile gross contribution plus the
        sum of `gross_names` over every rental in the input set."
        PRD §3.3: "`net_mailable_names` is `gross_input_names` less `suppressed_names`
        less `duplicates_removed`, and it is the finite universe the allocation waterfall
        in §3.5 draws from."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()

        run = validate_success(
            _link(api, world, [world["first"]["id"], world["second"]["id"]]), 201
        )
        assert run["gross_input_names"] == 60000
        assert run["suppressed_names"] == 0
        assert run["duplicates_removed"] == 9100
        assert run["net_mailable_names"] == 50900
        assert run["net_mailable_names"] == 30000 + 9000 + 11900
        assert_merge_purge_names_conserved(run)

    def test_the_status_filter_returns_the_completed_run(self, api):
        """PRD §3.3: "Because `input_rental_ids` is an identifier array rather than a
        single foreign key, the plan's merge-purge run collection — filterable by
        `status` and returned newest first — is the only way to read back which rentals a
        given run consumed."

        Design: Corner/endpoints/a_merge_purge_run_links_only_delivered_rentals_of_its_own_season
        """
        world = _a_plan_facing_four_candidate_rentals()
        run = validate_success(
            _link(api, world, [world["first"]["id"], world["second"]["id"]]), 201
        )

        rows, meta = validate_paginated(
            api.list_merge_purge_runs(
                world["plan"]["id"], DIRECTOR, params={"status": "COMPLETED"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [run["id"]]
        assert rows[0]["input_rental_ids"] == [
            world["first"]["id"],
            world["second"]["id"],
        ]
