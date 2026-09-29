"""The denial grid is anti-hierarchical: the role that seeds the world is not a super-user.

`PlatformAdmin` creates seasons and drives the clock, and is refused on both the
planner's authoring writes and the director's governing ones. The director, symmetrically,
cannot author the artefacts it judges. Two reads that look shared are refused to
`ListBroker`, so "all five roles share every GET" is false. And because the role check
sits at priority 20, a director's plan whose budget the schema would also reject still
comes back 403 rather than 422.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR,
    PLANNER,
    create_contact_event_payload,
    create_plan_payload,
    create_rental_line_payload,
    create_rental_payload,
    create_season_payload,
    create_segment_payload,
    fetch_plan,
    iso_utc,
    new_page_placement,
    new_rental_in_state,
    set_clock,
    set_clock_payload,
    setup_allocated_drop,
    validate_error,
    validate_paginated,
)

RIVAL_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 1000,
    "avg_order_value_cents": 9000,
    "historical_response_rate_bps": 300,
}


def _a_fully_populated_draft_plan() -> dict:
    """Season FW26, segment S_A, DRAFT plan P1, drop 1 with one allocated S_A line and
    one page placement, and rental R1 sitting in REQUESTED — every row created by the
    role that properly owns it."""
    set_clock(CLOCK_START)
    world = setup_allocated_drop(
        season_overrides={"season_code": "FW26", "fiscal_year": 2026},
        segment_overrides={"segment_code": "S_A"},
        plan_overrides={"plan_code": "P1", "budget_cents": 20000000},
    )
    world["placement"] = new_page_placement(world["drop"]["id"])
    world["rental"] = new_rental_in_state(
        world["season"]["id"], "REQUESTED", list_source_name="R1"
    )
    assert world["plan"]["status"] == "DRAFT"
    assert world["line"]["status"] == "ALLOCATED"
    return world


class TestTheAdminIsNoSuperUser:
    def test_the_role_that_seeds_the_season_can_neither_plan_nor_govern(self, api):
        """PRD §2.1: "A `PlatformAdmin` owns the configuration surface — the season rate
        card, the contact-frequency governance rules, the logical clock and the ingested
        ecommerce order feed — and deliberately cannot plan, cost, approve, buy lists or
        measure."
        PRD §2.1: "A request whose role is not listed among the endpoint's authorized roles
        is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        authoring = api.create_segment(
            create_segment_payload(
                world["season"]["id"], segment_code="S_ADMIN", **RIVAL_SCORING
            ),
            ADMIN,
        )
        validate_error(authoring, "ERR_FORBIDDEN_ROLE", 403)

        governing = api.cancel_plan(
            world["plan"]["id"], ADMIN, {"reason": "admin overreach"}
        )
        validate_error(governing, "ERR_FORBIDDEN_ROLE", 403)
        assert fetch_plan(world["plan"]["id"], PLANNER)["status"] == "DRAFT"


class TestTheDirectorCannotAuthorWhatItJudges:
    def test_the_approver_may_not_open_a_plan_or_buy_a_list(self, api):
        """PRD §2.1: "A `CirculationDirector` holds budget authority — approve, send back
        for revision, or kill the plan — and cannot author any of the artefacts being
        judged."
        PRD §2.1: "A request whose role is not listed among the endpoint's authorized roles
        is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        opening = api.create_plan(
            create_plan_payload(
                world["season"]["id"], plan_code="P_DIR", budget_cents=100000
            ),
            DIRECTOR,
        )
        validate_error(opening, "ERR_FORBIDDEN_ROLE", 403)

        buying = api.create_rental(
            create_rental_payload(
                world["season"]["id"],
                list_source_name="DIRECTOR-LIST",
                requested_gross_names=5000,
                cost_per_thousand_cents=8000,
                housefile_overlap_bps=500,
                inter_list_overlap_bps=0,
            ),
            DIRECTOR,
        )
        validate_error(buying, "ERR_FORBIDDEN_ROLE", 403)

    def test_the_role_check_outranks_the_body_schema(self, api):
        """PRD §2.10: "2. **Role authorized for the endpoint** on every endpoint —
        otherwise `ERR_FORBIDDEN_ROLE` (403)."
        PRD §2.10: "5. **Request body satisfies its schema** on every write endpoint:
        required fields present, enum values in range, integers inside their declared
        bounds, no negative money or quantities — otherwise `ERR_INVALID_REQUEST` (422)."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        response = api.create_plan(
            create_plan_payload(
                world["season"]["id"], plan_code="P_DIR", budget_cents=0
            ),
            DIRECTOR,
        )
        error = validate_error(response, "ERR_FORBIDDEN_ROLE", 403)
        assert error["error_id"] != "ERR_INVALID_REQUEST"


class TestTheProcurementAndMeasurementZonesAreFencedOut:
    def test_the_broker_may_neither_approve_nor_add_a_line_for_its_own_names(
        self, api
    ):
        """PRD §2.1: "A `ListBroker` owns outside-list procurement,
        cooperative-database modeling and the merge-purge universe build, but cannot
        allocate circulation against the names it delivers."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        approving = api.approve_plan(world["plan"]["id"], BROKER)
        validate_error(approving, "ERR_FORBIDDEN_ROLE", 403)

        listing_its_names = api.create_line(
            world["drop"]["id"],
            create_rental_line_payload(
                world["rental"]["id"], requested_quantity=1000
            ),
            BROKER,
        )
        validate_error(listing_its_names, "ERR_FORBIDDEN_ROLE", 403)

    def test_the_analyst_may_neither_allocate_nor_move_the_clock(self, api):
        """PRD §2.1: "A `MarketingAnalyst` owns measurement: manual contact logging, test
        cells, and matchback attribution reads."
        PRD §2.1: "A `PlatformAdmin` owns the configuration surface — the season rate card,
        the contact-frequency governance rules, the logical clock and the ingested
        ecommerce order feed — and deliberately cannot plan, cost, approve, buy lists or
        measure."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        allocating = api.allocate_drop(world["drop"]["id"], ANALYST)
        validate_error(allocating, "ERR_FORBIDDEN_ROLE", 403)

        moving_the_clock = api.set_clock(
            set_clock_payload(iso_utc("2027-01-01")), ANALYST
        )
        validate_error(moving_the_clock, "ERR_FORBIDDEN_ROLE", 403)


class TestThePlannerStaysOutOfConfigurationAndMeasurement:
    def test_the_author_may_neither_seed_a_season_nor_log_a_contact(self, api):
        """PRD §2.1: "A `CirculationPlanner` authors and executes circulation: housefile
        segments, plans, drops, audience lines, allocation, page placements, presort
        batches and the production transitions through mail and delivery; a planner may
        cost a plan and submit it for review, but may never approve one."
        PRD §2.1: "A `MarketingAnalyst` owns measurement: manual contact logging, test
        cells, and matchback attribution reads."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        seeding = api.create_season(
            create_season_payload(season_code="SS27", fiscal_year=2027), PLANNER
        )
        validate_error(seeding, "ERR_FORBIDDEN_ROLE", 403)

        logging_contact = api.create_contact_event(
            create_contact_event_payload(
                world["segment"]["id"], iso_utc("2026-07-20"), "MAIL",
                source="MANUAL_LOG",
            ),
            PLANNER,
        )
        validate_error(logging_contact, "ERR_FORBIDDEN_ROLE", 403)


class TestTheReadSurfaceIsEnumeratedPerEndpoint:
    def test_two_reads_the_broker_cannot_reach(self, api):
        """PRD §2.1: "All five roles may perform every read (`GET`) operation the service
        exposes, subject to the per-endpoint role lists in §4, which are narrower for a
        handful of reads."
        PRD §2.1: "This role check happens *before* any identifier in the URL path is
        resolved, so a caller in the wrong role who also names a non-existent resource
        receives the 403 role rejection rather than a 404 — the service never confirms the
        existence of a resource to a caller who is not entitled to touch that class of
        resource at all."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()

        placements = api.list_page_placements(world["drop"]["id"], BROKER)
        validate_error(placements, "ERR_FORBIDDEN_ROLE", 403)

        profitability = api.get_plan_profitability(world["plan"]["id"], BROKER)
        validate_error(profitability, "ERR_FORBIDDEN_ROLE", 403)


class TestTwelveRefusalsLeaveTheWorldExactlyAsItWas:
    def test_no_row_was_created_and_the_plan_is_still_a_draft(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's authorized
        roles is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.4: "`updated_at` is refreshed to the current instant on every mutation of
        the row, and `version` is an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation — including mutations the row's owner did not request,
        such as a cascade reaching it from another aggregate."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operations
        """
        world = _a_fully_populated_draft_plan()
        season_id = world["season"]["id"]
        plan_id = world["plan"]["id"]
        drop_id = world["drop"]["id"]
        opening_plan_version = fetch_plan(plan_id, PLANNER)["version"]

        refusals = [
            api.create_season(
                create_season_payload(season_code="SS27", fiscal_year=2027), PLANNER
            ),
            api.create_segment(
                create_segment_payload(
                    season_id, segment_code="S_ADMIN", **RIVAL_SCORING
                ),
                ADMIN,
            ),
            api.cancel_plan(plan_id, ADMIN, {"reason": "admin overreach"}),
            api.create_plan(
                create_plan_payload(
                    season_id, plan_code="P_DIR", budget_cents=100000
                ),
                DIRECTOR,
            ),
            api.approve_plan(plan_id, BROKER),
            api.allocate_drop(drop_id, ANALYST),
            api.set_clock(set_clock_payload(iso_utc("2027-01-01")), ANALYST),
            api.create_contact_event(
                create_contact_event_payload(
                    world["segment"]["id"], iso_utc("2026-07-20"), "MAIL",
                    source="MANUAL_LOG",
                ),
                PLANNER,
            ),
            api.create_line(
                drop_id,
                create_rental_line_payload(
                    world["rental"]["id"], requested_quantity=1000
                ),
                BROKER,
            ),
            api.create_rental(
                create_rental_payload(
                    season_id,
                    list_source_name="DIRECTOR-LIST",
                    requested_gross_names=5000,
                    cost_per_thousand_cents=8000,
                    housefile_overlap_bps=500,
                    inter_list_overlap_bps=0,
                ),
                DIRECTOR,
            ),
            api.list_page_placements(drop_id, BROKER),
            api.get_plan_profitability(plan_id, BROKER),
        ]
        assert len(refusals) == 12
        for response in refusals:
            validate_error(response, "ERR_FORBIDDEN_ROLE", 403)

        plan = fetch_plan(plan_id, PLANNER)
        assert plan["status"] == "DRAFT"
        assert plan["version"] == opening_plan_version

        _, segment_meta = validate_paginated(
            api.list_segments(PLANNER, params={"season_id": season_id})
        )
        assert segment_meta["total_count"] == 1
        _, plan_meta = validate_paginated(api.list_season_plans(season_id, PLANNER))
        assert plan_meta["total_count"] == 1
        _, rental_meta = validate_paginated(
            api.list_season_rentals(season_id, BROKER)
        )
        assert rental_meta["total_count"] == 1
        _, line_meta = validate_paginated(
            api.list_lines(PLANNER, params={"drop_id": drop_id})
        )
        assert line_meta["total_count"] == 1
        _, event_meta = validate_paginated(
            api.list_segment_contact_events(world["segment"]["id"], ANALYST)
        )
        assert event_meta["total_count"] == 0
        _, placement_meta = validate_paginated(
            api.list_page_placements(drop_id, PLANNER)
        )
        assert placement_meta["total_count"] == 1
