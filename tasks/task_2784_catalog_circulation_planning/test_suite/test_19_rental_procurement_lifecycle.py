"""The four broker edges of a prospect list rental, and the fifth nobody calls.

Procurement is deliberately staged so that each step writes exactly one thing:
modeling prices the response rate, ordering freezes the per-name cost, delivery
records what the list owner actually shipped, and the netting that ends the walk
is performed by a merge-purge run rather than by any rental endpoint. An
implementation that computes a field early — or that lets a broker re-model a
list it has already bought — collapses that staging.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    assert_merge_purge_run,
    assert_prospect_list_rental,
    create_merge_purge_run_payload,
    create_rental_payload,
    deliver_rental_payload,
    fetch_rental,
    model_rental_payload,
    new_plan,
    new_rental_in_state,
    new_season,
    plan_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

RENTAL_TERMS = {
    "list_source_name": "COOP-A",
    "requested_gross_names": 25000,
    "cost_per_thousand_cents": 8500,
    "housefile_overlap_bps": 2000,
    "inter_list_overlap_bps": 0,
}


def _season_plan_and_a_fresh_rental(api) -> dict:
    """Season FW26, plan P1 at a 20000000-cent budget, and one rental of 25000
    names at a CPM of 8500 cents still sitting where it was registered."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    rental = validate_success(
        api.create_rental(create_rental_payload(season["id"], **RENTAL_TERMS), BROKER),
        201,
    )
    return {"season": season, "plan": plan, "rental": rental}


class TestForwardProcurementEdges:
    def test_modeling_prices_the_response_rate_and_touches_nothing_else(self, api):
        """PRD §3.2: "A score of 800 or above earns a lift of positive 4000 basis
        points; 600 or above earns positive 2000; 400 or above earns no lift at
        all; and anything below 400 earns a lift of *negative* 3000 basis points,
        so an unmodelled-quality list responds below the season base. The rental's
        `expected_response_rate_bps` is then the season's
        `prospect_base_response_bps` multiplied by the quantity ten thousand plus
        the lift, divided by ten thousand, with the result rounded half up to a
        whole basis point."

        Design: Corner/state_machines/rental_lifecycle_advances_requested_through_netted
        """
        world = _season_plan_and_a_fresh_rental(api)
        created = world["rental"]

        assert_prospect_list_rental(created)
        assert created["status"] == "REQUESTED"
        assert created["coop_model_score"] == 0
        assert created["expected_response_rate_bps"] == 0
        assert created["unit_cost_cents_per_name"] == 0
        assert created["gross_names"] == 0
        assert created["net_names_delivered"] == 0
        assert created["version"] == 1

        modeled = validate_success(
            api.model_rental(created["id"], model_rental_payload(640), BROKER), 200
        )

        assert modeled["status"] == "MODELED"
        assert modeled["coop_model_score"] == 640
        assert modeled["expected_response_rate_bps"] == 132
        assert modeled["unit_cost_cents_per_name"] == 0
        assert modeled["gross_names"] == 0
        assert modeled["version"] == 2

    def test_ordering_freezes_the_per_name_price_at_nine_whole_cents(self, api):
        """PRD §3.2: "**Ordering** moves the rental `MODELED → ORDERED` and takes
        no payload. It freezes the rental's per-name price:
        `unit_cost_cents_per_name` becomes `cost_per_thousand_cents` divided by
        one thousand, rounded half up to whole cents."

        Design: Corner/state_machines/rental_lifecycle_advances_requested_through_netted
        """
        world = _season_plan_and_a_fresh_rental(api)
        rental_id = world["rental"]["id"]

        validate_success(
            api.model_rental(rental_id, model_rental_payload(640), BROKER), 200
        )
        ordered = validate_success(api.order_rental(rental_id, BROKER), 200)

        assert ordered["status"] == "ORDERED"
        assert ordered["unit_cost_cents_per_name"] == 9
        assert ordered["expected_response_rate_bps"] == 132
        assert ordered["gross_names"] == 0
        assert ordered["version"] == 3

    def test_the_merge_purge_run_and_no_rental_endpoint_performs_the_netting(
        self, api
    ):
        """PRD §3.2: "The final procurement step is not a broker action at all: a
        rental moves `DELIVERED → NETTED` as a consequence of a merge-purge run
        completing with that rental in its input set, at which point
        `net_names_delivered` is written as the rental's `gross_names` less its own
        housefile and inter-list duplicate removals."

        Design: Corner/state_machines/rental_lifecycle_advances_requested_through_netted
        """
        world = _season_plan_and_a_fresh_rental(api)
        rental_id = world["rental"]["id"]
        plan_id = world["plan"]["id"]

        validate_success(
            api.model_rental(rental_id, model_rental_payload(640), BROKER), 200
        )
        validate_success(api.order_rental(rental_id, BROKER), 200)
        delivered = validate_success(
            api.deliver_rental(rental_id, deliver_rental_payload(24000), BROKER), 200
        )

        assert delivered["status"] == "DELIVERED"
        assert delivered["gross_names"] == 24000
        assert delivered["requested_gross_names"] == 25000
        assert delivered["net_names_delivered"] == 0
        assert delivered["version"] == 4

        run = validate_success(
            api.create_merge_purge_run(
                plan_id,
                create_merge_purge_run_payload(plan_version(plan_id), [rental_id]),
                BROKER,
            ),
            201,
        )
        assert_merge_purge_run(run)
        assert run["status"] == "COMPLETED"

        netted = fetch_rental(rental_id)
        assert netted["status"] == "NETTED"
        assert netted["net_names_delivered"] == 19200
        assert netted["gross_names"] == 24000
        assert netted["version"] == 5


def _one_requested_and_one_ordered_rental() -> dict:
    """Two rentals in the same season: R_NEW left where it was registered, and
    R_ORD walked as far as ORDERED on a coop score of 640."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    fresh = new_rental_in_state(
        season["id"], "REQUESTED", **{**RENTAL_TERMS, "list_source_name": "COOP-NEW"}
    )
    ordered = new_rental_in_state(
        season["id"],
        "ORDERED",
        coop_model_score=640,
        **{**RENTAL_TERMS, "list_source_name": "COOP-ORD"},
    )
    return {"season": season, "fresh": fresh, "ordered": ordered}


class TestRejectedProcurementEdges:
    def test_two_skipped_edges_and_one_backwards_edge_are_all_refused(self, api):
        """PRD §2.10: "**The requested transition exists from the entity's current
        state**, on every action endpoint — otherwise the matching 409 code:
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DROP_STATE`,
        `ERR_INVALID_MEASUREMENT_STATE`, `ERR_INVALID_RENTAL_STATE`,
        `ERR_INVALID_LINE_STATE`, `ERR_INVALID_TEST_CELL_STATE` or
        `ERR_INVALID_MATCHBACK_STATE`."

        Design: Corner/state_machines/a_rental_transition_from_the_wrong_state_is_rejected
        """
        world = _one_requested_and_one_ordered_rental()
        fresh_id = world["fresh"]["id"]
        ordered_id = world["ordered"]["id"]

        assert world["fresh"]["status"] == "REQUESTED"
        assert world["ordered"]["status"] == "ORDERED"

        validate_error(
            api.order_rental(fresh_id, BROKER),
            ApiErrorId.ERR_INVALID_RENTAL_STATE.value,
            409,
        )
        validate_error(
            api.deliver_rental(fresh_id, deliver_rental_payload(24000), BROKER),
            ApiErrorId.ERR_INVALID_RENTAL_STATE.value,
            409,
        )
        validate_error(
            api.model_rental(ordered_id, model_rental_payload(900), BROKER),
            ApiErrorId.ERR_INVALID_RENTAL_STATE.value,
            409,
        )

    def test_the_rejected_calls_leave_both_rental_rows_exactly_as_they_were(
        self, api
    ):
        """PRD §3.2: "A rental then walks a four-step procurement path —
        `REQUESTED → MODELED → ORDERED → DELIVERED` — before a fifth,
        system-driven step retires it into `NETTED`. Each step is a broker action,
        and each increments the rental's `version` by one."

        Design: Corner/state_machines/a_rental_transition_from_the_wrong_state_is_rejected
        """
        world = _one_requested_and_one_ordered_rental()
        fresh_id = world["fresh"]["id"]
        ordered_id = world["ordered"]["id"]
        ordered_version = world["ordered"]["version"]
        assert ordered_version == 3

        for response in (
            api.order_rental(fresh_id, BROKER),
            api.deliver_rental(fresh_id, deliver_rental_payload(24000), BROKER),
            api.model_rental(ordered_id, model_rental_payload(900), BROKER),
        ):
            validate_error(
                response, ApiErrorId.ERR_INVALID_RENTAL_STATE.value, 409
            )

        fresh = fetch_rental(fresh_id)
        assert fresh["status"] == "REQUESTED"
        assert fresh["coop_model_score"] == 0
        assert fresh["unit_cost_cents_per_name"] == 0
        assert fresh["gross_names"] == 0
        assert fresh["version"] == 1

        ordered = fetch_rental(ordered_id)
        assert ordered["status"] == "ORDERED"
        assert ordered["coop_model_score"] == 640
        assert ordered["expected_response_rate_bps"] == 132
        assert ordered["unit_cost_cents_per_name"] == 9
        assert ordered["version"] == ordered_version == 3

        rentals, meta = validate_paginated(
            api.list_season_rentals(world["season"]["id"], PLANNER)
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rentals) == ["ORDERED", "REQUESTED"]
