"""Row-level contracts: what a create persists, what it stamps, what a read
returns and which reference failures each entity owns.

Every default asserted here is one the PRD names explicitly, and every not-found
code is checked on the endpoint whose body would otherwise have tripped a state
rule, so a shared generic 404 cannot pass.
"""
import pytest

from test_helpers import (
    ADMIN,
    DISPATCHER,
    NON_EXISTENT_UUID,
    OFFICER,
    OPERATOR,
    SUPPORT,
    add_robot,
    assert_common_fields,
    create_delivery_order_payload,
    create_depot_bay_payload,
    create_incident_report_payload,
    create_merchant_payload,
    create_robot_payload,
    create_service_zone_payload,
    provision_zone,
    read_bay,
    read_merchant,
    read_order,
    read_segment,
    read_zone,
    set_clock,
    setup_active_merchant,
    setup_approved_segment,
    setup_other_zone,
    survey_segment,
    validate_error,
    validate_paginated,
    validate_success,
    BASE_CLOCK_UTC,
)

BARE_SEGMENT = {
    "segment_type": "WALKWAY",
    "length_m": 150.0,
    "measured_clearance_cm": 120.0,
    "surface_grade_pct": 2.0,
}
BAYVIEW = {
    "name": "Bayview",
    "municipality_code": "SFB",
}


def _bare_segment_payload(zone_id: str, segment_code: str, **overrides) -> dict:
    """A segment payload carrying only its six required fields."""
    payload = {"zone_id": zone_id, "segment_code": segment_code}
    payload.update(BARE_SEGMENT)
    payload.update(overrides)
    return payload


class TestConfigurationRowShapes:
    def test_zone_create_returns_the_ordinance_terms_and_every_declared_default(self, api):
        """PRD §3.1: "A `PlatformAdmin` provisions the zone first, with the
        ordinance terms and planning assumptions described in §2.7; the zone lands
        in `permit_state` `PROVISIONED`, every derived ledger at zero,
        `remedy_budget_remaining_cents` equal to the authorised
        `remedy_budget_cents`, `lid_code_sequence` at zero and
        `restriction_reason` null."
        PRD §2.7: "`max_crossing_risk` is the crossing-safety ceiling, a value
        between 0.0 and 100.0 that defaults to 45.0 when the caller does not
        supply it; no segment may be approved while its computed risk sits above
        that ceiling."
        PRD §2.7: "`takeover_confidence_threshold_pct` is the autonomy-confidence
        breakpoint at or below which a remote takeover becomes mandatory, a whole
        number between 0 and 100 that defaults to 35."
        PRD §2.7: "`insurer_notify_threshold_cents` is the estimated-damage level
        at or above which an incident must be escalated to the insurer; it must be
        zero or greater and defaults to 25000."

        Design: Corner/entities/zone_create_returns_ordinance_config_and_declared_defaults
        """
        set_clock(BASE_CLOCK_UTC)

        zone = validate_success(
            api.create_service_zone(create_service_zone_payload(), ADMIN), 201
        )

        assert_common_fields(zone, "ServiceZone")
        assert zone["name"] == "Mission District"
        assert zone["municipality_code"] == "SF"
        assert zone["permit_state"] == "PROVISIONED"
        assert zone["ordinance_min_clearance_cm"] == 90.0
        assert zone["ordinance_max_speed_cm_s"] == 160
        assert zone["operating_window_start_utc_hhmm"] == "0700"
        assert zone["operating_window_end_utc_hhmm"] == "2100"
        assert zone["max_concurrent_robots"] == 2
        assert zone["max_crossing_risk"] == 45.0
        assert zone["takeover_confidence_threshold_pct"] == 35
        assert zone["insurer_notify_threshold_cents"] == 25000
        assert zone["remedy_budget_cents"] == 50000
        assert zone["remedy_spent_cents"] == 0
        assert zone["remedy_budget_remaining_cents"] == 50000
        assert zone["reserved_bay_minutes"] == 0
        assert zone["open_incident_count"] == 0
        assert zone["on_mission_robot_count"] == 0
        assert zone["lid_code_sequence"] == 0
        assert zone["restriction_reason"] is None
        assert zone["version"] == 1
        assert zone["created_at"] == zone["updated_at"]
        assert read_zone(zone["id"]) == zone

    def test_segment_read_returns_the_full_geometry_row(self, api):
        """PRD §3.1: "Its physical description comprises `length_m`, the
        centreline length used later by route distance and duration arithmetic,
        which must be greater than zero; `measured_clearance_cm`, the narrowest
        passable clearance on the element, also greater than zero; and
        `surface_grade_pct`, the steepest running grade as a percentage, between
        0.0 and 25.0."
        PRD §3.1: "The pedestrian-flow term is `pedestrian_flow_per_min`
        multiplied by 1.4, but never more than 28; whichever of the two is smaller
        is the term."
        PRD §3.1: "The ramp term is negative 6 when `curb_ramp_present` is true
        and 0 otherwise."
        PRD §3.1: "Those five terms are added together, the total is then clamped
        into the range 0.0 through 100.0, and only after clamping is it rounded
        half up to one decimal place — which is why a raw total of negative 6.0
        stores as 0.0 rather than as a negative score."
        PRD §2.4: "`version` (integer): 1 immediately after creation, and
        increased by exactly 1 on every mutation of that row."

        Design: Corner/entities/segment_read_returns_the_full_geometry_row
        """
        ctx = setup_approved_segment()

        segment = validate_success(api.get_sidewalk_segment(ctx["s1"], DISPATCHER))

        assert segment["zone_id"] == ctx["z"]
        assert segment["segment_code"] == "S1"
        assert segment["segment_type"] == "WALKWAY"
        assert segment["crossing_control"] == "NONE"
        assert segment["length_m"] == 320.0
        assert segment["measured_clearance_cm"] == 118.0
        assert segment["surface_grade_pct"] == 3.0
        assert segment["sightline_m"] == 40.0
        assert segment["pedestrian_flow_per_min"] == 6.0
        assert segment["curb_ramp_present"] is True
        assert segment["crossing_risk_score"] == pytest.approx(2.4)
        assert segment["status"] == "APPROVED"
        assert segment["connected_segment_ids"] == []
        assert segment["blocked_by_closure_id"] is None
        assert segment["version"] == 3

    def test_robot_listing_pages_with_the_unpaginated_total(self, api):
        """PRD §2.3: "Both are echoed back to the caller together with the size of
        the unpaginated result set and a boolean indicating whether more rows
        follow: the `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`."
        PRD §2.3: "`offset` is the number of rows to skip before the window
        begins; when omitted it defaults to 0 and its minimum accepted value is
        0."

        Design: Corner/entities/robot_listing_pages_with_total_count_and_has_more
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        for tag in ("RBT-001", "RBT-002", "RBT-003"):
            add_robot(zone["id"], asset_tag=tag, stage=False, make_available=False)

        first, meta_one = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": zone["id"], "limit": 2, "offset": 0})
        )
        second, meta_two = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": zone["id"], "limit": 2, "offset": 2})
        )

        assert len(first) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True
        assert len(second) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False
        tags = [row["asset_tag"] for row in first + second]
        assert sorted(tags) == ["RBT-001", "RBT-002", "RBT-003"]

        _offline, offline_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": zone["id"], "duty_state": "OFFLINE"})
        )
        available, available_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": zone["id"], "duty_state": "AVAILABLE"})
        )
        assert offline_meta["total_count"] == 3
        assert available_meta["total_count"] == 0
        assert available == []


class TestUnknownIdentifiersPerLayer:
    def test_mapping_layer_unknown_ids_each_report_their_own_code(self, api):
        """PRD §2.9: "Each entity has its own not-found code, all of them HTTP
        404: `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`,
        `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_MISSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_INTERVENTION_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND`."
        PRD §2.9: "When a request carries several identifiers — whether in the path
        or in the body — they are resolved strictly left to right, path before
        body, and the first identifier that resolves to no row decides the
        rejection."

        Design: Corner/entities/mapping_layer_unknown_ids_return_not_found
        """
        set_clock(BASE_CLOCK_UTC)
        provision_zone()

        validate_error(
            api.get_service_zone(NON_EXISTENT_UUID, DISPATCHER), "ERR_ZONE_NOT_FOUND", 404
        )
        validate_error(
            api.get_sidewalk_segment(NON_EXISTENT_UUID, DISPATCHER),
            "ERR_SEGMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api.closure_transition(NON_EXISTENT_UUID, {"action": "LIFT"}, ADMIN),
            "ERR_CLOSURE_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_merchant(NON_EXISTENT_UUID, SUPPORT), "ERR_MERCHANT_NOT_FOUND", 404
        )

    def test_fleet_layer_unknown_ids_each_report_their_own_code(self, api):
        """PRD §2.9: "Each entity has its own not-found code, all of them HTTP
        404: `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`,
        `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_MISSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_INTERVENTION_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND`."
        PRD §2.10: "The existence band resolves references in the order zone,
        segment, closure, merchant, robot, bay, reservation, order, mission, route
        plan, intervention event, incident report."

        Design: Corner/entities/fleet_layer_unknown_ids_return_not_found
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        add_robot(zone["id"], asset_tag="RBT-001", stage=False, make_available=False)
        bay = validate_success(
            api.create_depot_bay(
                create_depot_bay_payload(zone["id"], "B1", power_kw=22.0), ADMIN
            ),
            201,
        )

        validate_error(
            api.get_robot(NON_EXISTENT_UUID, DISPATCHER), "ERR_ROBOT_NOT_FOUND", 404
        )
        validate_error(
            api.get_depot_bay(NON_EXISTENT_UUID, DISPATCHER), "ERR_BAY_NOT_FOUND", 404
        )
        validate_error(
            api.bay_reservation_transition(
                NON_EXISTENT_UUID, {"action": "CANCEL"}, DISPATCHER
            ),
            "ERR_RESERVATION_NOT_FOUND",
            404,
        )

        assert read_bay(bay["id"])["committed_minutes"] == 0

    def test_delivery_layer_unknown_ids_each_report_their_own_code(self, api):
        """PRD §2.9: "Each entity has its own not-found code, all of them HTTP
        404: `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`,
        `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_MISSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_INTERVENTION_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND`."
        PRD §2.10: "The ladder is walked from the top and stops at the first
        violated rule, and its bands are, in order: authentication and
        authorisation; request-payload syntax; existence of referenced rows;
        parent-version pinning; state of the target row and of the rows it depends
        on; safety and ordinance compliance; structural consistency of the
        submitted graph; and finally capacity, caps and budgets."

        Design: Corner/entities/delivery_layer_unknown_ids_return_not_found
        """
        set_clock(BASE_CLOCK_UTC)
        provision_zone()

        validate_error(
            api.get_delivery_order(NON_EXISTENT_UUID, SUPPORT), "ERR_ORDER_NOT_FOUND", 404
        )
        validate_error(
            api.get_delivery_mission(NON_EXISTENT_UUID, DISPATCHER),
            "ERR_MISSION_NOT_FOUND",
            404,
        )
        validate_error(
            api.route_plan_transition(NON_EXISTENT_UUID, {"action": "VALIDATE"}, DISPATCHER),
            "ERR_PLAN_NOT_FOUND",
            404,
        )
        validate_error(
            api.intervention_transition(
                NON_EXISTENT_UUID, {"action": "ACKNOWLEDGE"}, OPERATOR
            ),
            "ERR_INTERVENTION_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_incident_report(NON_EXISTENT_UUID, OFFICER), "ERR_INCIDENT_NOT_FOUND", 404
        )


class TestDeclaredDefaultsAndStampedFields:
    def test_a_bare_segment_takes_every_declared_default_and_scores_at_survey(self, api):
        """PRD §3.1: "A `crossing_control` value describes the traffic-control
        regime — `NONE`, `SIGNALIZED`, `UNSIGNALIZED` or `MIDBLOCK` — and is stored
        on every element even though it is only meaningful on a crossing; it
        defaults to `NONE`."
        PRD §3.1: "Three observation fields may be recorded at mapping time or
        deferred to the survey: `sightline_m` and `pedestrian_flow_per_min`, both
        defaulting to 0.0 and both required to be zero or greater, and the
        accessibility flag `curb_ramp_present`, defaulting to false."
        PRD §3.1: "It defaults to an empty set, and the server enforces symmetric
        closure: naming a neighbour when a segment is mapped also adds the new
        segment's own id to that neighbour's own `connected_segment_ids`, and each
        such neighbour is a mutation in its own right, so each of their versions
        advances by one."
        PRD §3.1: "A newly mapped element sits in `status` `MAPPED` with
        `crossing_risk_score` still null and `blocked_by_closure_id` null."
        PRD §3.1: "The surveyor may override any of `sightline_m`,
        `pedestrian_flow_per_min`, `curb_ramp_present` and `measured_clearance_cm`;
        each of the four is optional, and an omitted field keeps whatever value was
        recorded when the element was mapped, so a survey that supplies no
        overrides simply scores the mapped values."

        Design: Corner/entities/segment_optional_inputs_fall_back_to_declared_defaults
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()

        created = validate_success(
            api.create_sidewalk_segment(_bare_segment_payload(zone["id"], "SD"), ADMIN), 201
        )

        assert created["crossing_control"] == "NONE"
        mapped = read_segment(created["id"])
        assert mapped["sightline_m"] == 0.0
        assert mapped["pedestrian_flow_per_min"] == 0.0
        assert mapped["curb_ramp_present"] is False
        assert mapped["connected_segment_ids"] == []
        assert mapped["status"] == "MAPPED"
        assert mapped["crossing_risk_score"] is None
        assert mapped["blocked_by_closure_id"] is None

        surveyed = survey_segment(created["id"])

        assert surveyed["status"] == "SURVEYED"
        assert surveyed["crossing_risk_score"] == pytest.approx(30.0)
        assert surveyed["sightline_m"] == 0.0
        assert surveyed["version"] == 2

    def test_robot_registration_stamps_every_server_owned_field(self, api):
        """PRD §3.4: "A newly registered robot has `duty_state` `OFFLINE`,
        `health_state` `NOMINAL`, `battery_pct` 100.0, `odometer_m` 0.0,
        `yield_event_count` 0, `tamper_flag` false, `lifetime_mission_count`,
        `lifetime_intervention_count`, `lifetime_escalation_count` and
        `clean_mission_count` all zero, both `rolling_autonomy_index` and
        `lifetime_autonomy_index` at 100, and `active_mission_id` and
        `current_bay_reservation_id` both null."
        PRD §2.4: "`version` (integer): 1 immediately after creation, and
        increased by exactly 1 on every mutation of that row."

        Design: Corner/entities/robot_create_stamps_every_system_field
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()

        robot = validate_success(
            api.create_robot(create_robot_payload(zone["id"], "RBT-001"), ADMIN), 201
        )

        assert_common_fields(robot, "Robot")
        assert robot["battery_pct"] == 100.0
        assert robot["duty_state"] == "OFFLINE"
        assert robot["health_state"] == "NOMINAL"
        assert robot["odometer_m"] == 0.0
        assert robot["yield_event_count"] == 0
        assert robot["tamper_flag"] is False
        assert robot["lifetime_mission_count"] == 0
        assert robot["lifetime_intervention_count"] == 0
        assert robot["lifetime_escalation_count"] == 0
        assert robot["clean_mission_count"] == 0
        assert robot["rolling_autonomy_index"] == 100
        assert robot["lifetime_autonomy_index"] == 100
        assert robot["active_mission_id"] is None
        assert robot["current_bay_reservation_id"] is None
        assert robot["version"] == 1
        assert robot["created_at"] == robot["updated_at"]
        assert read_zone(zone["id"])["on_mission_robot_count"] == 0

    def test_order_intake_freezes_the_tier_the_urgency_and_the_quote(self, api):
        """PRD §3.3: "`payload_tier` is `SMALL` when `payload_liters` is at most
        15.0 litres, `MEDIUM` when it is above 15.0 but at most 30.0, and `LARGE`
        when it is above 30.0 but at most 45.0."
        PRD §3.3: "`urgency_flag` is true when the interval from the order's
        `created_at` to its `promised_by_utc` is at most 45 minutes, and false
        otherwise."
        PRD §3.3: "The order itself lands in `order_state` `RECEIVED`, with
        `settled_fee_cents`, `exception_reason`, `remedy_kind`,
        `remedy_reason_code` and `remedy_amount_cents` all null and
        `dispatch_attempt_count` at zero."
        PRD §3.3: "Immediately afterwards the quoted amount is escrowed: the
        merchant's `escrowed_fee_cents` increases by `quoted_fee_cents` and the
        merchant's `version` advances by one."
        PRD §3.3: "The credit is subtracted from the gross fee, and the merchant
        grade discount is applied exactly once to that whole remaining basis —
        nothing for `STANDARD`, 5 percent off for `PREFERRED` and 12 percent off
        for `ANCHOR` — never per component."

        Design: Corner/entities/order_create_freezes_tier_urgency_and_quote
        """
        ctx = setup_active_merchant(merchant_overrides={"merchant_grade": "STANDARD"})

        order = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    customer_ref="C-7",
                    payload_liters=10.0,
                    declared_value_cents=4000,
                    promised_by_utc="2026-08-03T11:00:00.000Z",
                ),
                ctx["merchant_headers"],
            ),
            201,
        )

        assert order["payload_tier"] == "SMALL"
        assert order["urgency_flag"] is False
        assert order["quoted_fee_cents"] == 595
        assert order["settled_fee_cents"] is None
        assert order["order_state"] == "RECEIVED"
        assert order["exception_reason"] is None
        assert order["remedy_kind"] is None
        assert order["remedy_amount_cents"] is None
        assert order["dispatch_attempt_count"] == 0
        assert order["version"] == 1

        merchant = read_merchant(ctx["m"])
        assert merchant["escrowed_fee_cents"] == 595
        assert merchant["recognized_fee_cents"] == 0
        assert merchant["released_fee_cents"] == 0


def _without(payload: dict, field: str) -> dict:
    """The same payload with exactly one declared-required field removed."""
    return {key: value for key, value in payload.items() if key != field}


class TestRejectedCreatesWriteNothing:
    def test_malformed_values_are_refused_in_the_payload_band(self, api):
        """PRD §2.10: "Within the payload band, all of whose findings carry
        `ERR_INVALID_REQUEST` at HTTP 400, the order is: required fields present;
        enum values recognised; numeric ranges respected; the payload-volume upper
        bound; datetime format; interval endpoint ordering; the action being one
        the endpoint declares; the fields that a particular action requires; the
        parent-version field being present at all; and the well-formedness of a
        submitted segment sequence or adjacency array."
        PRD §2.7: "`max_crossing_risk` is the crossing-safety ceiling, a value
        between 0.0 and 100.0 that defaults to 45.0 when the caller does not supply
        it; no segment may be approved while its computed risk sits above that
        ceiling."
        PRD §3.1: "Each element is recorded against its `zone_id` with a survey
        code in `segment_code`, which must be unique among the segments of that
        zone, and a `segment_type` of `WALKWAY`, `CROSSING` or `RAMP`."
        PRD §3.4: "The three physical measurements must each be greater than
        zero."
        PRD §3.3: "A volume above 45.0 litres has no payload tier and is refused
        with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/malformed_field_values_are_rejected_by_type_constraints
        """
        ctx = setup_active_merchant()

        validate_error(
            api.create_service_zone(
                create_service_zone_payload(name="Bad Zone", max_crossing_risk=145.0), ADMIN
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_sidewalk_segment(
                _bare_segment_payload(ctx["z"], "SX", segment_type="PATHWAY", length_m=100.0),
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_robot(
                create_robot_payload(ctx["z"], "RBT-BAD", width_cm=-5.0), ADMIN
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    customer_ref="C-8",
                    payload_liters=45.1,
                    declared_value_cents=100,
                    promised_by_utc="2026-08-03T11:00:00.000Z",
                ),
                ctx["merchant_headers"],
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _zones, zone_meta = validate_paginated(api.list_service_zones(ADMIN))
        _segments, segment_meta = validate_paginated(
            api.list_sidewalk_segments(DISPATCHER, {"zone_id": ctx["z"]})
        )
        _robots, robot_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"]})
        )
        assert zone_meta["total_count"] == 1
        assert segment_meta["total_count"] == 4
        assert robot_meta["total_count"] == 0
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 0

    def test_an_absent_required_field_is_refused_before_any_value_is_examined(self, api):
        """PRD §2.10: "Within the payload band, all of whose findings carry
        `ERR_INVALID_REQUEST` at HTTP 400, the order is: required fields present;
        enum values recognised; numeric ranges respected; the payload-volume upper
        bound; datetime format; interval endpoint ordering; the action being one
        the endpoint declares; the fields that a particular action requires; the
        parent-version field being present at all; and the well-formedness of a
        submitted segment sequence or adjacency array."
        PRD §3.9: "The report is created in `report_state` `DRAFT`,
        `filed_by_user_id` latches the calling user so the later submission can
        enforce separation of duties, and the zone's `open_incident_count` advances
        by one along with the zone's `version`."

        Design: Corner/entities/create_without_required_fields_is_rejected
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        robot = add_robot(zone["id"], asset_tag="RBT-001", stage=False, make_available=False)

        validate_error(
            api.create_service_zone(
                _without(create_service_zone_payload(name="No Code"), "municipality_code"),
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_sidewalk_segment(
                _without(_bare_segment_payload(zone["id"], "SY"), "length_m"), ADMIN
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_robot(
                _without(create_robot_payload(zone["id"], "RBT-009"), "max_speed_cm_s"), ADMIN
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_incident_report(
                _without(
                    create_incident_report_payload(
                        zone["id"], robot["id"], category="OBSTRUCTION", severity="MINOR"
                    ),
                    "narrative",
                ),
                OFFICER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _zones, zone_meta = validate_paginated(api.list_service_zones(ADMIN))
        _robots, robot_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": zone["id"]})
        )
        _reports, report_meta = validate_paginated(
            api.list_incident_reports(OFFICER, {"zone_id": zone["id"]})
        )
        assert zone_meta["total_count"] == 1
        assert robot_meta["total_count"] == 1
        assert report_meta["total_count"] == 0
        assert read_zone(zone["id"])["open_incident_count"] == 0

    def test_an_unknown_parent_zone_is_refused_before_the_ordinance_gate(self, api):
        """PRD §2.10: "The ladder is walked from the top and stops at the first
        violated rule, and its bands are, in order: authentication and
        authorisation; request-payload syntax; existence of referenced rows;
        parent-version pinning; state of the target row and of the rows it depends
        on; safety and ordinance compliance; structural consistency of the
        submitted graph; and finally capacity, caps and budgets."
        PRD §3.4: "Registration is also the first of two places where the zone
        ordinance is enforced against the machine: a robot whose `max_speed_cm_s`
        exceeds the zone's `ordinance_max_speed_cm_s` cannot be registered at all
        and the attempt is refused with `ERR_ORDINANCE_SPEED_EXCEEDED` (HTTP 422)."
        PRD §2.9: "Each entity has its own not-found code, all of them HTTP 404:
        `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`,
        `ERR_MERCHANT_NOT_FOUND`, `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_MISSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_INTERVENTION_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND`."

        Design: Corner/entities/child_create_with_unknown_parent_zone_is_rejected
        """
        set_clock(BASE_CLOCK_UTC)
        provision_zone()

        validate_error(
            api.create_sidewalk_segment(
                _bare_segment_payload(NON_EXISTENT_UUID, "SZ", length_m=100.0), ADMIN
            ),
            "ERR_ZONE_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_robot(
                create_robot_payload(NON_EXISTENT_UUID, "RBT-777", max_speed_cm_s=900), ADMIN
            ),
            "ERR_ZONE_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_merchant(
                create_merchant_payload(NON_EXISTENT_UUID, name="Ghost Cafe"), ADMIN
            ),
            "ERR_ZONE_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_depot_bay(
                create_depot_bay_payload(NON_EXISTENT_UUID, "BX", bay_type="CHARGE"), ADMIN
            ),
            "ERR_ZONE_NOT_FOUND",
            404,
        )

        _segments, segment_meta = validate_paginated(api.list_sidewalk_segments(DISPATCHER))
        _robots, robot_meta = validate_paginated(api.list_robots(DISPATCHER))
        _merchants, merchant_meta = validate_paginated(api.list_merchants(SUPPORT))
        _bays, bay_meta = validate_paginated(api.list_depot_bays(DISPATCHER))
        assert segment_meta["total_count"] == 0
        assert robot_meta["total_count"] == 0
        assert merchant_meta["total_count"] == 0
        assert bay_meta["total_count"] == 0


class TestCrossZoneReferences:
    def test_a_dropoff_outside_the_merchants_zone_is_refused_and_the_same_zone_one_is_quoted(
        self, api
    ):
        """PRD §3.3: "The merchant must be `ACTIVE`, or the intake is refused with
        `ERR_MERCHANT_NOT_ACTIVE`; and the dropoff segment must sit in the
        merchant's own zone, or the intake is refused with `ERR_ZONE_MISMATCH`."
        PRD §3.3: "The payload names the `merchant_id` that originated the order,
        the `dropoff_segment_id` on which the customer will take delivery, a
        `customer_ref` of 1 to 64 characters used later for remedy correspondence,
        the declared cargo volume `payload_liters`, which must be greater than
        zero, the customer-declared cargo value `declared_value_cents`, which must
        be zero or greater, and `promised_by_utc`, the promised delivery instant,
        which must be strictly after the current logical-clock instant."

        Design: Corner/entities/order_dropoff_must_lie_in_merchant_zone
        """
        ctx = setup_active_merchant()
        other = setup_other_zone(segment_code="F1", permit=False, municipality_code="SFB")

        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(ctx["m"], other["segment"]["id"]),
                ctx["merchant_headers"],
            ),
            "ERR_ZONE_MISMATCH",
            422,
        )
        order = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(ctx["m"], ctx["s5"]), ctx["merchant_headers"]
            ),
            201,
        )

        _orders, order_meta = validate_paginated(
            api.list_delivery_orders(ADMIN, {"merchant_id": ctx["m"]})
        )
        assert order_meta["total_count"] == 1
        assert order["quoted_fee_cents"] == 850
        assert read_order(order["id"])["dropoff_segment_id"] == ctx["s5"]
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 850

    def test_a_cross_zone_neighbour_is_refused_while_a_same_zone_link_is_symmetric(self, api):
        """PRD §3.1: "Three well-formedness rules apply to the array. It may not
        contain the segment's own id, which is refused with `ERR_INVALID_REQUEST`;
        every element must resolve to a real segment, and an unresolvable element
        is refused with `ERR_SEGMENT_NOT_FOUND`; and every named neighbour must sit
        in the same zone as the segment being mapped, with a cross-zone neighbour
        refused as `ERR_ZONE_MISMATCH`."
        PRD §3.1: "It defaults to an empty set, and the server enforces symmetric
        closure: naming a neighbour when a segment is mapped also adds the new
        segment's own id to that neighbour's own `connected_segment_ids`, and each
        such neighbour is a mutation in its own right, so each of their versions
        advances by one."

        Design: Corner/entities/segment_adjacency_may_not_cross_zone_boundaries
        """
        ctx = setup_approved_segment()
        bayview = provision_zone(**BAYVIEW)

        validate_error(
            api.create_sidewalk_segment(
                _bare_segment_payload(
                    bayview["id"], "F1", connected_segment_ids=[ctx["s1"]]
                ),
                ADMIN,
            ),
            "ERR_ZONE_MISMATCH",
            422,
        )

        mission_s1 = read_segment(ctx["s1"])
        assert mission_s1["connected_segment_ids"] == []
        assert mission_s1["version"] == 3

        first = validate_success(
            api.create_sidewalk_segment(_bare_segment_payload(bayview["id"], "F1"), ADMIN), 201
        )
        assert first["connected_segment_ids"] == []

        second = validate_success(
            api.create_sidewalk_segment(
                _bare_segment_payload(
                    bayview["id"], "F2", length_m=100.0, connected_segment_ids=[first["id"]]
                ),
                ADMIN,
            ),
            201,
        )

        assert second["connected_segment_ids"] == [first["id"]]
        neighbour = read_segment(first["id"])
        assert neighbour["connected_segment_ids"] == [second["id"]]
        assert neighbour["version"] == 2
