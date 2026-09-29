"""Five peer roles build one chain, each contributing only what it exclusively owns.

The chain is deliberately interlocking rather than five isolated calls: the broker's
rental and the analyst's contact event both attach to rows the planner and the admin
created, and the director closes the plan the planner opened. The reads then cross the
same boundaries in the other direction — the broker reads a season it cannot write, the
analyst reads a plan it cannot write, the director lists rentals it cannot register.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR,
    PLANNER,
    assert_catalog_season,
    assert_circulation_plan,
    assert_contact_event,
    assert_housefile_segment,
    assert_prospect_list_rental,
    create_contact_event_payload,
    create_plan_payload,
    create_rental_payload,
    create_season_payload,
    create_segment_payload,
    iso_utc,
    set_clock,
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


def _the_admin_seeds_the_season(api) -> dict:
    """Nothing pre-exists; the whole chain below is built by the roles under test."""
    set_clock(CLOCK_START)
    return validate_success(
        api.create_season(
            create_season_payload(season_code="FW26", fiscal_year=2026), ADMIN
        ),
        201,
    )


class TestTheConfigurationAndPlanningZones:
    def test_the_admin_seeds_the_season_and_the_planner_authors_on_it(self, api):
        """PRD §2.1: "A `PlatformAdmin` owns the configuration surface — the season rate
        card, the contact-frequency governance rules, the logical clock and the ingested
        ecommerce order feed — and deliberately cannot plan, cost, approve, buy lists or
        measure."
        PRD §2.1: "A `CirculationPlanner` authors and executes circulation: housefile
        segments, plans, drops, audience lines, allocation, page placements, presort
        batches and the production transitions through mail and delivery; a planner may
        cost a plan and submit it for review, but may never approve one."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        season = _the_admin_seeds_the_season(api)
        assert_catalog_season(season)

        segment = validate_success(
            api.create_segment(
                create_segment_payload(season["id"], segment_code="S_A", **SCORING),
                PLANNER,
            ),
            201,
        )
        assert_housefile_segment(segment)
        assert segment["season_id"] == season["id"]

        plan = validate_success(
            api.create_plan(
                create_plan_payload(
                    season["id"], plan_code="P1", budget_cents=20000000
                ),
                PLANNER,
            ),
            201,
        )
        assert_circulation_plan(plan)
        assert plan["status"] == "DRAFT"


class TestTheProcurementAndMeasurementZones:
    def test_the_broker_buys_names_and_the_analyst_logs_contact_on_the_same_season(
        self, api
    ):
        """PRD §2.1: "A `ListBroker` owns outside-list procurement,
        cooperative-database modeling and the merge-purge universe build, but cannot
        allocate circulation against the names it delivers."
        PRD §2.1: "A `MarketingAnalyst` owns measurement: manual contact logging, test
        cells, and matchback attribution reads."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        season = _the_admin_seeds_the_season(api)
        segment = validate_success(
            api.create_segment(
                create_segment_payload(season["id"], segment_code="S_A", **SCORING),
                PLANNER,
            ),
            201,
        )

        rental = validate_success(
            api.create_rental(
                create_rental_payload(
                    season["id"],
                    list_source_name="COOP-A",
                    requested_gross_names=10000,
                    cost_per_thousand_cents=8500,
                    housefile_overlap_bps=1000,
                    inter_list_overlap_bps=0,
                ),
                BROKER,
            ),
            201,
        )
        assert_prospect_list_rental(rental)
        assert rental["status"] == "REQUESTED"

        event = validate_success(
            api.create_contact_event(
                create_contact_event_payload(
                    segment["id"], iso_utc("2026-07-20"), "EMAIL", source="MANUAL_LOG"
                ),
                ANALYST,
            ),
            201,
        )
        assert_contact_event(event)
        assert event["housefile_segment_id"] == segment["id"]
        assert event["source"] == "MANUAL_LOG"

        rows, _ = validate_paginated(
            api.list_segment_contact_events(segment["id"], ANALYST)
        )
        assert [row["id"] for row in rows] == [event["id"]]


class TestTheBudgetAuthorityZone:
    def test_only_the_director_can_close_the_plan_the_planner_opened(self, api):
        """PRD §2.1: "A `CirculationDirector` holds budget authority — approve, send back
        for revision, or kill the plan — and cannot author any of the artefacts being
        judged."
        PRD §3.6: "**Cancellation** is reachable from `DRAFT`, `COSTED`, `UNDER_REVIEW`
        and `APPROVED`, takes an optional `reason`, and is likewise barred once any drop of
        the plan has reached `MAILED` or `DELIVERED` — that attempt is rejected with
        `ERR_INVALID_PLAN_STATE`."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        season = _the_admin_seeds_the_season(api)
        plan = validate_success(
            api.create_plan(
                create_plan_payload(
                    season["id"], plan_code="P1", budget_cents=20000000
                ),
                PLANNER,
            ),
            201,
        )

        cancelled = validate_success(
            api.cancel_plan(plan["id"], DIRECTOR, {"reason": "role smoke test"}), 200
        )
        assert cancelled["status"] == "CANCELLED"


class TestTheSharedReadSurface:
    def test_each_role_reads_across_a_boundary_it_cannot_write(self, api):
        """PRD §2.1: "All five roles may perform every read (`GET`) operation the service
        exposes, subject to the per-endpoint role lists in §4, which are narrower for a
        handful of reads."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        season = _the_admin_seeds_the_season(api)
        plan = validate_success(
            api.create_plan(
                create_plan_payload(
                    season["id"], plan_code="P1", budget_cents=20000000
                ),
                PLANNER,
            ),
            201,
        )
        rental = validate_success(
            api.create_rental(
                create_rental_payload(
                    season["id"],
                    list_source_name="COOP-A",
                    requested_gross_names=10000,
                    cost_per_thousand_cents=8500,
                    housefile_overlap_bps=1000,
                    inter_list_overlap_bps=0,
                ),
                BROKER,
            ),
            201,
        )

        broker_read = validate_success(api.get_season(season["id"], BROKER), 200)
        assert broker_read["id"] == season["id"]

        analyst_read = validate_success(api.get_plan(plan["id"], ANALYST), 200)
        assert analyst_read["id"] == plan["id"]

        rows, meta = validate_paginated(
            api.list_season_rentals(
                season["id"], DIRECTOR, params={"status": "REQUESTED"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [rental["id"]]
