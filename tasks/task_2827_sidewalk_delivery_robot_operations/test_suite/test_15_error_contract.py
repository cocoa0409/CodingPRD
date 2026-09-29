"""The error contract: which code fires, at which status, and what the refusal
is forbidden to leak or to change.

Authentication, role admission and merchant ownership are exercised on endpoints
where a later rule would also have failed, so a refusal that reports the wrong
band is visible; the last pair walks the four status families this API uses.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    NO_AUTH_HEADERS,
    OFFICER,
    UNKNOWN_UUID,
    add_merchant,
    assert_error_envelope_shape,
    create_delivery_order_payload,
    create_robot_payload,
    create_service_zone_payload,
    health_transition_payload,
    load_payload,
    make_merchant_operator_headers,
    permit_transition_payload,
    provision_zone,
    read_mission,
    read_robot,
    read_zone,
    setup_active_merchant,
    setup_available_robot,
    setup_planned_mission,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A volume with no payload tier, refused at the input layer.
UNTIERED_LITERS = 46.0
OVER_ORDINANCE_SPEED_CM_S = 200


class TestUnauthenticatedIsTheFirstGate:
    def test_a_read_a_write_and_a_transition_all_answer_the_same_way(self, api):
        """PRD §2.1: "Every request — including the logical-clock endpoint — must
        carry two headers: `X-User-ID`, which identifies the acting principal, and
        `X-User-Role`, which declares the capacity in which that principal is
        acting."
        PRD §2.1: "If `X-User-Role` is absent or empty the request is refused with
        `ERR_UNAUTHENTICATED` (HTTP 401); this is the very first check the server
        performs, ahead of every other rule in the system."
        PRD §3.1: "The `ACTIVATE_PERMIT` step carries the zone from `PROVISIONED` to
        `PERMITTED`, and it requires that at least one segment in the zone has already
        reached `APPROVED` — a zone whose network has been mapped but never approved
        cannot be permitted, and the attempt is refused with
        `ERR_INVALID_STATE_TRANSITION`."

        The zone has no approved segment, so the unauthenticated activation would
        have failed its own precondition as well.

        Design: Corner/errors/unauthenticated_requests_are_rejected_before_role_and_state
        """
        zone = provision_zone()

        read = api.get_service_zone(zone["id"], NO_AUTH_HEADERS)
        write = api.create_service_zone(
            create_service_zone_payload(name="Sunset", municipality_code="SFS"),
            NO_AUTH_HEADERS,
        )
        transition = api.zone_permit_transition(
            zone["id"], permit_transition_payload("ACTIVATE_PERMIT"), NO_AUTH_HEADERS
        )

        for response in (read, write, transition):
            validate_error(response, "ERR_UNAUTHENTICATED", 401)
            assert_error_envelope_shape(response.json())

    def test_the_refused_calls_leave_the_zone_and_the_table_alone(self, api):
        """PRD §2.1: "If `X-User-Role` is absent or empty the request is refused with
        `ERR_UNAUTHENTICATED` (HTTP 401); this is the very first check the server
        performs, ahead of every other rule in the system."
        PRD §3.1: "A `PlatformAdmin` provisions the zone first, with the ordinance
        terms and planning assumptions described in §2.7; the zone lands in
        `permit_state` `PROVISIONED`, every derived ledger at zero,
        `remedy_budget_remaining_cents` equal to the authorised `remedy_budget_cents`,
        `lid_code_sequence` at zero and `restriction_reason` null."

        Design: Corner/errors/unauthenticated_requests_are_rejected_before_role_and_state
        """
        zone = provision_zone()
        validate_error(
            api.create_service_zone(
                create_service_zone_payload(name="Sunset", municipality_code="SFS"),
                NO_AUTH_HEADERS,
            ),
            "ERR_UNAUTHENTICATED",
        )
        validate_error(
            api.zone_permit_transition(
                zone["id"], permit_transition_payload("ACTIVATE_PERMIT"), NO_AUTH_HEADERS
            ),
            "ERR_UNAUTHENTICATED",
        )

        after = read_zone(zone["id"])
        _rows, meta = validate_paginated(api.list_service_zones(ADMIN))
        assert after["permit_state"] == "PROVISIONED"
        assert after["version"] == 1
        assert meta["total_count"] == 1


class TestRoleAdmissionIsPerEndpoint:
    def test_a_dispatcher_may_neither_provision_a_zone_nor_drive_health(self, api):
        """PRD §2.1: "If `X-User-Role` names something that is not a recognised
        role, or names a role that the target endpoint does not admit, the request is
        refused with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §4: "Provision a service zone with its ordinance envelope, operating
        window, planning assumptions and remedy budget."
        PRD §4: "Drive the health dimension with the `DOWNGRADE`, `IMPAIR`,
        `QUARANTINE` and `CLEAR` actions; `QUARANTINE` runs the four-link cascade."

        Design: Corner/errors/wrong_role_on_a_write_is_rejected_with_role_forbidden
        """
        ctx = setup_available_robot()

        validate_error(
            api.create_service_zone(
                create_service_zone_payload(name="Sunset", municipality_code="SFS"),
                DISPATCHER,
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )
        validate_error(
            api.robot_health_transition(
                ctx["r"],
                health_transition_payload("DOWNGRADE", reason="wheel slip"),
                DISPATCHER,
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )

        robot = read_robot(ctx["r"])
        assert robot["health_state"] == "NOMINAL"
        assert robot["version"] == 3

    def test_the_officer_the_endpoint_admits_moves_only_the_health_dimension(self, api):
        """PRD §3.5: "Health is driven explicitly by a `SafetyOfficer` supplying an
        `action` and an optional `reason`."
        PRD §3.5: "`DOWNGRADE` carries `NOMINAL` to `DEGRADED`."
        PRD §3.5: "Every health transition advances the robot's `version` by one and,
        apart from the quarantine cascade, leaves `duty_state` exactly as it was."

        Design: Corner/errors/wrong_role_on_a_write_is_rejected_with_role_forbidden
        """
        ctx = setup_available_robot()
        validate_error(
            api.robot_health_transition(
                ctx["r"],
                health_transition_payload("DOWNGRADE", reason="wheel slip"),
                DISPATCHER,
            ),
            "ERR_ROLE_FORBIDDEN",
        )

        downgraded = validate_success(
            api.robot_health_transition(
                ctx["r"],
                health_transition_payload("DOWNGRADE", reason="wheel slip"),
                OFFICER,
            )
        )

        assert downgraded["health_state"] == "DEGRADED"
        assert downgraded["duty_state"] == "AVAILABLE"
        assert downgraded["version"] == 4


def _two_active_merchants_and_one_planned_mission() -> dict:
    """The mission's own merchant plus an unrelated active merchant in the same
    zone, whose operator identity is the second merchant row."""
    ctx = setup_planned_mission()
    stranger = add_merchant(ctx["z"], name="Second Baker")
    ctx["m2"] = stranger["id"]
    ctx["stranger_headers"] = make_merchant_operator_headers(stranger["id"])
    return ctx


class TestMerchantOwnershipIsNotRoleAdmission:
    def test_a_stranger_merchant_can_neither_order_nor_hand_off(self, api):
        """PRD §2.1: "Concretely, a `MerchantOperator` request is refused with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403) whenever `X-User-ID` does not equal the
        `Merchant` `id` that owns the target row — the merchant row itself, the
        `merchant_id` of a target order, or the `merchant_id` of the order behind a
        target mission."
        PRD §2.1: "That ownership rule guards order intake, order cancellation,
        container loading, the single-merchant read and the order list; on the order
        list and the merchant list a `MerchantOperator` sees only its own rows
        regardless of any filter it supplies."

        Design: Corner/errors/a_merchant_operator_touching_another_merchants_rows_is_forbidden
        """
        ctx = _two_active_merchants_and_one_planned_mission()

        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(ctx["m"], ctx["s5"], customer_ref="C-X"),
                ctx["stranger_headers"],
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api.load_delivery_mission(
                ctx["mi"], load_payload(22.0), ctx["stranger_headers"]
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        assert read_mission(ctx["mi"])["mission_state"] == "PLANNED"
        assert read_zone(ctx["z"])["lid_code_sequence"] == 0

    def test_the_owning_merchant_completes_the_identical_handoff(self, api):
        """PRD §3.7: "A successful handoff carries the mission from `PLANNED` to
        `LOADED`, stores `actual_payload_liters` and mints the lid access code from a
        per-zone monotonic counter: the zone's `lid_code_sequence` advances by one, and
        `lid_access_code` becomes the six-digit zero-padded decimal representation of
        100000 plus the new value of that sequence, so the first code minted in a zone
        is 100001."
        PRD §2.1: "That ownership rule guards order intake, order cancellation,
        container loading, the single-merchant read and the order list; on the order
        list and the merchant list a `MerchantOperator` sees only its own rows
        regardless of any filter it supplies."

        Design: Corner/errors/a_merchant_operator_touching_another_merchants_rows_is_forbidden
        """
        ctx = _two_active_merchants_and_one_planned_mission()
        validate_error(
            api.load_delivery_mission(
                ctx["mi"], load_payload(22.0), ctx["stranger_headers"]
            ),
            "ERR_NOT_RESOURCE_OWNER",
        )

        loaded = validate_success(
            api.load_delivery_mission(
                ctx["mi"], load_payload(22.0), ctx["merchant_headers"]
            )
        )

        _rows, meta = validate_paginated(
            api.list_delivery_orders(DISPATCHER, {"merchant_id": ctx["m2"]})
        )
        assert loaded["mission_state"] == "LOADED"
        assert loaded["lid_access_code"] == "100001"
        assert read_zone(ctx["z"])["lid_code_sequence"] == 1
        assert meta["total_count"] == 0


class TestEveryStatusFamilyUsesOneEnvelope:
    def test_the_four_families_differ_only_in_status_and_identifier(self, api):
        """PRD §3.3: "A volume above 45.0 litres has no payload tier and is refused
        with `ERR_INVALID_REQUEST`."
        PRD §2.9: "Each entity has its own not-found code, all of them HTTP 404:
        `ERR_ZONE_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`,
        `ERR_MERCHANT_NOT_FOUND`, `ERR_ROBOT_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_MISSION_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND` and
        `ERR_INCIDENT_NOT_FOUND`."
        PRD §3.1: "The `ACTIVATE_PERMIT` step carries the zone from `PROVISIONED` to
        `PERMITTED`, and it requires that at least one segment in the zone has already
        reached `APPROVED` — a zone whose network has been mapped but never approved
        cannot be permitted, and the attempt is refused with
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.4: "Registration is also the first of two places where the zone
        ordinance is enforced against the machine: a robot whose `max_speed_cm_s`
        exceeds the zone's `ordinance_max_speed_cm_s` cannot be registered at all and
        the attempt is refused with `ERR_ORDINANCE_SPEED_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/every_status_family_uses_the_same_error_envelope
        """
        ctx = setup_active_merchant()

        malformed = api.create_delivery_order(
            create_delivery_order_payload(
                ctx["m"],
                ctx["s5"],
                customer_ref="C-BIG",
                payload_liters=UNTIERED_LITERS,
            ),
            ctx["merchant_headers"],
        )
        missing = api.get_robot(UNKNOWN_UUID, DISPATCHER)
        replayed = api.zone_permit_transition(
            ctx["z"], permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
        )
        over_speed = api.create_robot(
            create_robot_payload(
                ctx["z"], "RBT-FAST", max_speed_cm_s=OVER_ORDINANCE_SPEED_CM_S
            ),
            ADMIN,
        )

        validate_error(malformed, "ERR_INVALID_REQUEST", 400)
        validate_error(missing, "ERR_ROBOT_NOT_FOUND", 404)
        validate_error(replayed, "ERR_INVALID_STATE_TRANSITION", 409)
        validate_error(over_speed, "ERR_ORDINANCE_SPEED_EXCEEDED", 422)
        for response in (malformed, missing, replayed, over_speed):
            body = response.json()
            assert_error_envelope_shape(body)
            assert body["meta"]["api_request_id"].startswith("req_")
            assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_none_of_the_four_refusals_wrote_a_row(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §3.1: "Activation also clears `restriction_reason` back to null."
        PRD §3.3: "A volume above 45.0 litres has no payload tier and is refused with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/every_status_family_uses_the_same_error_envelope
        """
        ctx = setup_active_merchant()
        before = read_zone(ctx["z"])["version"]

        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    customer_ref="C-BIG",
                    payload_liters=UNTIERED_LITERS,
                ),
                ctx["merchant_headers"],
            ),
            "ERR_INVALID_REQUEST",
        )
        validate_error(
            api.zone_permit_transition(
                ctx["z"], permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
            ),
            "ERR_INVALID_STATE_TRANSITION",
        )
        validate_error(
            api.create_robot(
                create_robot_payload(
                    ctx["z"], "RBT-FAST", max_speed_cm_s=OVER_ORDINANCE_SPEED_CM_S
                ),
                ADMIN,
            ),
            "ERR_ORDINANCE_SPEED_EXCEEDED",
        )

        zone = read_zone(ctx["z"])
        _robots, robot_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"]})
        )
        _orders, order_meta = validate_paginated(
            api.list_delivery_orders(DISPATCHER, {"merchant_id": ctx["m"]})
        )
        assert zone["permit_state"] == "PERMITTED"
        assert zone["restriction_reason"] is None
        assert zone["version"] == before
        assert robot_meta["total_count"] == 0
        assert order_meta["total_count"] == 0
