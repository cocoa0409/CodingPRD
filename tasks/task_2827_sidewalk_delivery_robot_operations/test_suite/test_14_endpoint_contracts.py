"""Endpoint-surface contracts: the response envelope, filter composition,
offset paging, child-listing scope, plan history and the projection read.

These tests read the transport layer rather than the domain: the same rows are
addressed through create, single read, list and computed-read faces to pin what
each face is obliged to return.
"""
from test_helpers import (
    ADMIN,
    BASE_CLOCK_UTC,
    DISPATCHER,
    OPERATOR,
    SUPPORT,
    UNKNOWN_UUID,
    add_order,
    add_segment,
    assert_common_fields,
    assert_error_envelope_shape,
    assert_zone_economics,
    create_service_zone_payload,
    dispatch_mission,
    load_mission,
    map_segment,
    mission_action,
    provision_zone,
    read_economics,
    read_mission,
    read_merchant,
    read_order,
    read_plan,
    read_zone,
    set_clock,
    setup_active_merchant,
    setup_en_route_mission,
    setup_loaded_mission,
    setup_second_robot,
    submit_route_plan,
    survey_segment,
    validate_error,
    validate_paginated,
    validate_success,
    validate_and_activate_plan,
)

#: The midblock crossing of the filter scenario, scored above the zone ceiling.
S4_MIDBLOCK = {
    "segment_type": "CROSSING",
    "crossing_control": "MIDBLOCK",
    "length_m": 12.0,
    "measured_clearance_cm": 96.0,
    "surface_grade_pct": 2.0,
    "sightline_m": 18.0,
    "pedestrian_flow_per_min": 9.0,
    "curb_ramp_present": True,
}
S1_WALKWAY = {
    "segment_type": "WALKWAY",
    "length_m": 320.0,
    "measured_clearance_cm": 118.0,
    "surface_grade_pct": 3.0,
    "sightline_m": 40.0,
    "pedestrian_flow_per_min": 6.0,
    "curb_ramp_present": True,
}
S2_SIGNALIZED = {
    "segment_type": "CROSSING",
    "crossing_control": "SIGNALIZED",
    "length_m": 14.0,
    "measured_clearance_cm": 150.0,
    "surface_grade_pct": 1.5,
    "sightline_m": 35.0,
    "pedestrian_flow_per_min": 10.0,
    "curb_ramp_present": True,
}
#: Two hours out from the base clock, so `urgency_flag` stays false.
RELAXED_PROMISE_UTC = "2026-08-03T11:00:00.000Z"
SECOND_ORDER_CLOCK_UTC = "2026-08-03T09:05:00.000Z"
THIRD_ORDER_CLOCK_UTC = "2026-08-03T09:10:00.000Z"
ARRIVAL_CLOCK_UTC = "2026-08-03T09:12:00.000Z"


class TestResponseEnvelopes:
    def test_a_create_and_a_read_wear_the_object_envelope(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."
        PRD §2.4: "`version` (integer): 1 immediately after creation, and increased
        by exactly 1 on every mutation of that row."
        PRD §2.4: "A read never changes a `version`, and a mutation always refreshes
        `updated_at` alongside it."
        PRD §3.1: "A `PlatformAdmin` provisions the zone first, with the ordinance
        terms and planning assumptions described in §2.7; the zone lands in
        `permit_state` `PROVISIONED`, every derived ledger at zero,
        `remedy_budget_remaining_cents` equal to the authorised
        `remedy_budget_cents`, `lid_code_sequence` at zero and `restriction_reason`
        null."

        Design: Corner/endpoints/success_and_error_envelopes_carry_the_declared_meta_shape
        """
        set_clock(BASE_CLOCK_UTC)

        created = api.create_service_zone(create_service_zone_payload(), ADMIN)
        zone = validate_success(created, 201)
        body = created.json()
        read_back = api.get_service_zone(zone["id"], SUPPORT)

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert_common_fields(zone, "ServiceZone")
        assert zone["version"] == 1
        assert zone["created_at"] == BASE_CLOCK_UTC
        assert zone["updated_at"] == BASE_CLOCK_UTC
        assert zone["permit_state"] == "PROVISIONED"
        assert zone["remedy_budget_remaining_cents"] == 50000
        assert validate_success(read_back)["version"] == 1
        assert read_back.json()["response_type"] == "object"

    def test_a_listing_and_a_missing_row_wear_their_own_envelopes(self, api):
        """PRD §2.3: "Both are echoed back to the caller together with the size of
        the unpaginated result set and a boolean indicating whether more rows follow:
        the `meta` object of a list response carries `limit`, `offset`, `total_count`
        and `has_more`."
        PRD §2.3: "`offset` is the number of rows to skip before the window begins;
        when omitted it defaults to 0 and its minimum accepted value is 0."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.9: "Each entity has its own not-found code, all of them HTTP 404:
        `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`,
        `ERR_MERCHANT_NOT_FOUND`, `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_MISSION_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND` and
        `ERR_INCIDENT_NOT_FOUND`."

        Design: Corner/endpoints/success_and_error_envelopes_carry_the_declared_meta_shape
        """
        set_clock(BASE_CLOCK_UTC)
        provision_zone()

        listed = api.list_service_zones(SUPPORT)
        rows, meta = validate_paginated(listed)
        missing = api.get_service_zone(UNKNOWN_UUID, SUPPORT)

        assert listed.json()["response_type"] == "array"
        assert len(rows) == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        validate_error(missing, "ERR_ZONE_NOT_FOUND", 404)
        assert_error_envelope_shape(missing.json())


def _three_segments_of_two_kinds_and_two_statuses() -> dict:
    """One approved walkway, one approved signalized crossing and one midblock
    crossing left `SURVEYED` because its risk score is above the ceiling."""
    zone = provision_zone()
    walkway = add_segment(zone["id"], "S1", None, **S1_WALKWAY)
    crossing = add_segment(zone["id"], "S2", [walkway["id"]], **S2_SIGNALIZED)
    midblock = map_segment(zone["id"], "S4", [crossing["id"]], **S4_MIDBLOCK)
    return {
        "z": zone["id"],
        "s1": walkway["id"],
        "s2": crossing["id"],
        "s4": survey_segment(midblock["id"])["id"],
    }


class TestListingFiltersCompose:
    def test_two_filters_narrow_to_their_intersection(self, api):
        """PRD §4: "List sidewalk segments, filtered by `zone_id`, `status` and
        `segment_type`."

        Only the approved signalized crossing satisfies both filters, while each
        filter on its own admits two of the three segments.

        Design: Corner/endpoints/listing_filters_intersect_conjunctively
        """
        ctx = _three_segments_of_two_kinds_and_two_statuses()

        both, both_meta = validate_paginated(
            api.list_sidewalk_segments(
                DISPATCHER,
                {"zone_id": ctx["z"], "status": "APPROVED", "segment_type": "CROSSING"},
            )
        )
        _status_rows, status_meta = validate_paginated(
            api.list_sidewalk_segments(
                DISPATCHER, {"zone_id": ctx["z"], "status": "APPROVED"}
            )
        )
        _type_rows, type_meta = validate_paginated(
            api.list_sidewalk_segments(
                DISPATCHER, {"zone_id": ctx["z"], "segment_type": "CROSSING"}
            )
        )
        _all_rows, all_meta = validate_paginated(
            api.list_sidewalk_segments(DISPATCHER, {"zone_id": ctx["z"]})
        )

        assert both_meta["total_count"] == 1
        assert [row["id"] for row in both] == [ctx["s2"]]
        assert both[0]["status"] == "APPROVED"
        assert both[0]["segment_type"] == "CROSSING"
        assert status_meta["total_count"] == 2
        assert type_meta["total_count"] == 2
        assert all_meta["total_count"] == 3

    def test_the_unapproved_crossing_is_the_whole_surveyed_page(self, api):
        """PRD §4: "List sidewalk segments, filtered by `zone_id`, `status` and
        `segment_type`."
        PRD §3.1: "Those five terms are added together, the total is then clamped
        into the range 0.0 through 100.0, and only after clamping is it rounded half
        up to one decimal place — which is why a raw total of negative 6.0 stores as
        0.0 rather than as a negative score."
        PRD §3.1: "If the frozen `crossing_risk_score` is above the zone's
        `max_crossing_risk` the approval is refused with `ERR_CROSSING_RISK_EXCEEDED`;
        that comparison is inclusive too, so a score exactly equal to the ceiling
        passes."

        An 18-metre sightline contributes 18, a flow of 9.0 contributes 12.6, a
        midblock control contributes 22, a 2.0 percent grade contributes 0 and the
        curb ramp contributes negative 6, for 46.6 against a ceiling of 45.0.

        Design: Corner/endpoints/listing_filters_intersect_conjunctively
        """
        ctx = _three_segments_of_two_kinds_and_two_statuses()

        rows, meta = validate_paginated(
            api.list_sidewalk_segments(
                DISPATCHER, {"zone_id": ctx["z"], "status": "SURVEYED"}
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["s4"]
        assert rows[0]["status"] == "SURVEYED"
        assert rows[0]["crossing_risk_score"] == 46.6
        assert read_zone(ctx["z"])["max_crossing_risk"] == 45.0


def _three_orders_five_minutes_apart() -> dict:
    """One merchant with orders C-A, C-B and C-C created at 09:00, 09:05 and
    09:10, in that order."""
    ctx = setup_active_merchant()
    ctx["a"] = add_order(
        ctx["m"], ctx["s5"], customer_ref="C-A", promised_by_utc=RELAXED_PROMISE_UTC
    )
    set_clock(SECOND_ORDER_CLOCK_UTC)
    ctx["b"] = add_order(
        ctx["m"], ctx["s5"], customer_ref="C-B", promised_by_utc=RELAXED_PROMISE_UTC
    )
    set_clock(THIRD_ORDER_CLOCK_UTC)
    ctx["c"] = add_order(
        ctx["m"], ctx["s5"], customer_ref="C-C", promised_by_utc=RELAXED_PROMISE_UTC
    )
    return ctx


class TestOffsetPaging:
    def test_two_pages_walk_the_whole_set_in_creation_order(self, api):
        """PRD §2.3: "Unless a specific list declares otherwise, rows are ordered by
        `created_at` ascending."
        PRD §2.3: "Both are echoed back to the caller together with the size of the
        unpaginated result set and a boolean indicating whether more rows follow: the
        `meta` object of a list response carries `limit`, `offset`, `total_count` and
        `has_more`."
        PRD §3.3: "Immediately afterwards the quoted amount is escrowed: the
        merchant's `escrowed_fee_cents` increases by `quoted_fee_cents` and the
        merchant's `version` advances by one."

        Design: Corner/endpoints/pagination_beyond_the_last_page_returns_an_empty_page
        """
        ctx = _three_orders_five_minutes_apart()

        first, first_meta = validate_paginated(
            api.list_delivery_orders(
                SUPPORT, {"merchant_id": ctx["m"], "limit": 2, "offset": 0}
            )
        )
        second, second_meta = validate_paginated(
            api.list_delivery_orders(
                SUPPORT, {"merchant_id": ctx["m"], "limit": 2, "offset": 2}
            )
        )

        assert [row["customer_ref"] for row in first] == ["C-A", "C-B"]
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert [row["customer_ref"] for row in second] == ["C-C"]
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 2037

    def test_a_page_past_the_end_is_an_empty_success(self, api):
        """PRD §2.3: "`offset` is the number of rows to skip before the window
        begins; when omitted it defaults to 0 and its minimum accepted value is 0."
        PRD §2.3: "`limit` caps the number of rows returned; when omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is
        100."

        Design: Corner/endpoints/pagination_beyond_the_last_page_returns_an_empty_page
        """
        ctx = _three_orders_five_minutes_apart()

        beyond, beyond_meta = validate_paginated(
            api.list_delivery_orders(
                SUPPORT, {"merchant_id": ctx["m"], "limit": 2, "offset": 3}
            )
        )
        unpaged, unpaged_meta = validate_paginated(
            api.list_delivery_orders(SUPPORT, {"merchant_id": ctx["m"]})
        )

        assert beyond == []
        assert beyond_meta["offset"] == 3
        assert beyond_meta["total_count"] == 3
        assert beyond_meta["has_more"] is False
        assert len(unpaged) == 3
        assert unpaged_meta["limit"] == 10
        assert unpaged_meta["offset"] == 0
        assert unpaged_meta["has_more"] is False


def _two_loaded_missions_each_with_one_draft_plan() -> dict:
    """Two robots, two orders, two loaded missions, one DRAFT plan apiece."""
    ctx = setup_loaded_mission()
    corridor = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    ctx["pa"] = submit_route_plan(ctx["mission"], corridor)["id"]
    second_robot = setup_second_robot(ctx, asset_tag="RBT-002")
    second_order = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    second_mission = dispatch_mission(second_order, second_robot["id"])
    ctx["mi2"] = second_mission["id"]
    loaded = load_mission(second_mission["id"], ctx["m"], 22.0)
    ctx["pb"] = submit_route_plan(loaded, corridor)["id"]
    return ctx


class TestRoutePlanListingScope:
    def test_each_mission_sees_only_its_own_plan(self, api):
        """PRD §4: "List route plans, filtered by `mission_id` and `plan_state`,
        ordered by `revision_index` ascending."
        PRD §3.6: "`revision_index` is the one-based ordinal of this plan among the
        plans of the same mission ordered by `created_at` ascending, so a mission's
        first plan carries `revision_index` 1 and its first replacement carries 2."

        Design: Corner/endpoints/route_plan_listing_is_scoped_to_the_named_mission
        """
        ctx = _two_loaded_missions_each_with_one_draft_plan()

        first, first_meta = validate_paginated(
            api.list_route_plans(OPERATOR, {"mission_id": ctx["mi"]})
        )
        second, second_meta = validate_paginated(
            api.list_route_plans(OPERATOR, {"mission_id": ctx["mi2"]})
        )
        _all_rows, all_meta = validate_paginated(api.list_route_plans(OPERATOR))

        assert [row["id"] for row in first] == [ctx["pa"]]
        assert first[0]["mission_id"] == ctx["mi"]
        assert first_meta["total_count"] == 1
        assert [row["id"] for row in second] == [ctx["pb"]]
        assert second_meta["total_count"] == 1
        assert all_meta["total_count"] == 2
        assert read_plan(ctx["pa"])["revision_index"] == 1
        assert read_plan(ctx["pb"])["revision_index"] == 1

    def test_an_unknown_parent_filter_is_an_empty_page_not_a_miss(self, api):
        """PRD §2.9: "When a request carries several identifiers — whether in the
        path or in the body — they are resolved strictly left to right, path before
        body, and the first identifier that resolves to no row decides the
        rejection."
        PRD §4: "List route plans, filtered by `mission_id` and `plan_state`, ordered
        by `revision_index` ascending."
        PRD §3.6: "Creation is where all the geometry is derived and all the geometry
        gates run; the plan then lands in `plan_state` `DRAFT` and must still be
        validated and activated before the robot may move."

        Design: Corner/endpoints/route_plan_listing_is_scoped_to_the_named_mission
        """
        ctx = _two_loaded_missions_each_with_one_draft_plan()

        rows, meta = validate_paginated(
            api.list_route_plans(OPERATOR, {"mission_id": UNKNOWN_UUID})
        )

        assert rows == []
        assert meta["total_count"] == 0
        assert read_plan(ctx["pa"])["plan_state"] == "DRAFT"
        assert read_plan(ctx["pb"])["plan_state"] == "DRAFT"


class TestEconomicsIsAProjection:
    def test_two_reads_of_an_unchanged_zone_agree_and_mutate_nothing(self, api):
        """PRD §3.9: "Finally, a zone's unit economics are computed on demand and
        nothing about them is stored."
        PRD §3.9: "Missions in `PLANNED`, `LOADED`, `EN_ROUTE` or `BLOCKED` and
        orders in `RECEIVED`, `DISPATCHED`, `IN_TRANSIT`, `EXCEPTION` or `CANCELLED`
        are excluded from every step of the pipeline."
        PRD §3.9: "The second step multiplies the number of the zone's robots whose
        `duty_state` is not `RETIRED` by a nominal shift of 600 minutes each to give
        the fleet capacity minutes."
        PRD §3.9: "The sixth step counts the zone's delivered orders — those whose
        `order_state` is `DELIVERED` or `REFUNDED` — and divides the sum of allocated
        overhead and variable cost by that count, rounded half up to whole cents, to
        give the cost per delivery; when the count is zero the cost per delivery is
        null rather than zero."
        PRD §2.4: "A read never changes a `version`, and a mutation always refreshes
        `updated_at` alongside it."

        Design: Corner/endpoints/economics_reads_are_recomputed_and_never_mutate
        """
        ctx = setup_en_route_mission()
        before = read_zone(ctx["z"])["version"]

        first = validate_success(api.get_zone_economics(ctx["z"], DISPATCHER))
        second = validate_success(api.get_zone_economics(ctx["z"], ADMIN))

        assert_zone_economics(first)
        assert first == second
        assert first["robot_active_minutes"] == 0
        assert first["fleet_capacity_minutes"] == 600
        assert first["utilization_pct"] == 0.0
        assert first["allocated_overhead_cents"] == 40000
        assert first["variable_cost_cents"] == 0
        assert first["delivered_count"] == 0
        assert first["cost_per_delivery_cents"] is None
        assert first["contribution_per_delivery_cents"] is None
        assert first["throughput_per_robot_hour"] == 0.00
        assert read_zone(ctx["z"])["version"] == before

    def test_completion_moves_every_step_of_the_pipeline_at_once(self, api):
        """PRD §3.9: "The third step computes utilization as a percentage: active
        minutes divided by capacity minutes, multiplied by 100, capped at 100.0, and
        rounded half up to one decimal place — and it is exactly 0.0 when the capacity
        is zero, since a zone with no unretired robot has no denominator."
        PRD §3.9: "The fourth step allocates overhead as a base of 40000 cents plus
        150 cents for every whole utilization point, the point count being the third
        step's already-rounded percentage with its fractional part discarded; that
        consumption of a rounded value is precisely why the third step cannot be
        folded into this one."
        PRD §3.9: "The fifth step computes variable cost as 9 cents for each whole
        100-metre unit of the total distance travelled, rounding any partial unit up,
        plus 140 cents for each intervention counted, both totalled over the same
        terminal-mission set as the first step, plus the zone's `remedy_spent_cents`
        exactly as it stands."
        PRD §3.9: "The seventh step computes contribution per delivery as the
        recognised revenue divided by the same delivered count, rounded half up to
        whole cents, minus the already-rounded cost per delivery, the subtraction
        therefore happening between two integers; recognised revenue is the sum of
        `settled_fee_cents` over those orders less the sum of `remedy_amount_cents`
        over them, and contribution per delivery is null whenever the cost per
        delivery is null because both quotients share the same denominator."
        PRD §3.9: "The eighth step computes throughput as the delivered count
        divided by the fleet capacity expressed in hours, that is capacity minutes
        divided by 60, rounded half up to two decimal places, and it is 0.00 when the
        capacity is zero."

        Twelve minutes of a 600-minute capacity is 2.0 percent, so overhead is
        40000 + 300; a 774-metre haul is eight whole 100-metre units at 9 cents.

        Design: Corner/endpoints/economics_reads_are_recomputed_and_never_mutate
        """
        ctx = setup_en_route_mission()
        set_clock(ARRIVAL_CLOCK_UTC)
        mission_action(ctx["mi"], "ARRIVE")
        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        economics = read_economics(ctx["z"])

        assert economics["robot_active_minutes"] == 12
        assert economics["utilization_pct"] == 2.0
        assert economics["allocated_overhead_cents"] == 40300
        assert economics["variable_cost_cents"] == 72
        assert economics["delivered_count"] == 1
        assert economics["cost_per_delivery_cents"] == 40372
        assert economics["contribution_per_delivery_cents"] == -39555
        assert economics["throughput_per_robot_hour"] == 0.10
        assert read_order(ctx["o"])["settled_fee_cents"] == 817


def _three_revisions_of_one_corridor() -> dict:
    """The same corridor submitted three times: the first two activated in turn
    and the third left in `DRAFT`."""
    ctx = setup_loaded_mission()
    corridor = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    first = submit_route_plan(ctx["mission"], corridor)
    validate_and_activate_plan(first["id"])
    second = submit_route_plan(read_mission(ctx["mi"]), corridor)
    validate_and_activate_plan(second["id"])
    third = submit_route_plan(read_mission(ctx["mi"]), corridor)
    ctx["p1"] = first["id"]
    ctx["p2"] = second["id"]
    ctx["p3"] = third["id"]
    return ctx


class TestPlanHistory:
    def test_the_history_lists_every_revision_in_order(self, api):
        """PRD §4: "List route plans, filtered by `mission_id` and `plan_state`,
        ordered by `revision_index` ascending."
        PRD §3.6: "On success the mission's previously `ACTIVE` plan, if there was
        one, moves to `SUPERSEDED` with `rejection_reason` `REPLACED_BY_NEWER`, the new
        plan's `supersedes_plan_id` is pointed at that older plan, and the mission's
        `active_route_plan_id` is repointed at the new plan."
        PRD §3.6: "Both `SUPERSEDED` and `REJECTED` are terminal, and route plan
        lists are returned in `revision_index` ascending order so a mission's
        replanning history reads chronologically."

        Design: Corner/endpoints/plan_history_lists_every_revision_with_its_own_state
        """
        ctx = _three_revisions_of_one_corridor()

        rows, meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"]})
        )

        assert meta["total_count"] == 3
        assert [row["revision_index"] for row in rows] == [1, 2, 3]
        assert [row["id"] for row in rows] == [ctx["p1"], ctx["p2"], ctx["p3"]]
        assert rows[0]["plan_state"] == "SUPERSEDED"
        assert rows[0]["rejection_reason"] == "REPLACED_BY_NEWER"
        assert rows[1]["plan_state"] == "ACTIVE"
        assert rows[1]["supersedes_plan_id"] == ctx["p1"]
        assert rows[2]["plan_state"] == "DRAFT"
        assert rows[2]["supersedes_plan_id"] is None

    def test_the_state_filter_narrows_the_history_without_renumbering_it(self, api):
        """PRD §4: "List route plans, filtered by `mission_id` and `plan_state`,
        ordered by `revision_index` ascending."
        PRD §2.8: "A mission's `active_route_plan_id` mirrors whichever of its plans
        is currently active, and its `blocking_segment_id` mirrors the segment that
        caused a blockage."
        PRD §3.6: "`revision_index` is the one-based ordinal of this plan among the
        plans of the same mission ordered by `created_at` ascending, so a mission's
        first plan carries `revision_index` 1 and its first replacement carries 2."

        Design: Corner/endpoints/plan_history_lists_every_revision_with_its_own_state
        """
        ctx = _three_revisions_of_one_corridor()

        superseded, superseded_meta = validate_paginated(
            api.list_route_plans(
                DISPATCHER, {"mission_id": ctx["mi"], "plan_state": "SUPERSEDED"}
            )
        )
        drafts, draft_meta = validate_paginated(
            api.list_route_plans(
                DISPATCHER, {"mission_id": ctx["mi"], "plan_state": "DRAFT"}
            )
        )

        mission = read_mission(ctx["mi"])
        assert superseded_meta["total_count"] == 1
        assert superseded[0]["id"] == ctx["p1"]
        assert draft_meta["total_count"] == 1
        assert drafts[0]["id"] == ctx["p3"]
        assert drafts[0]["revision_index"] == 3
        assert mission["active_route_plan_id"] == ctx["p2"]
        assert mission["version"] == 4
        assert read_plan(ctx["p1"])["total_length_m"] == 774.0
        assert read_plan(ctx["p3"])["planned_duration_min"] == 9
