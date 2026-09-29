"""Role admission, control ownership and row-level scoping.

Every refusal here is caused by identity alone: the payloads are well formed and
the named rows exist, so an implementation that authorises per entity instead of
per endpoint, or that treats a role as a licence over another user's takeover,
fails these tests.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OPERATOR,
    OFFICER,
    SUPPORT,
    add_merchant,
    add_order,
    assert_error_envelope_shape,
    create_delivery_mission_payload,
    create_delivery_order_payload,
    create_route_plan_payload,
    duty_transition_payload,
    intervention_action,
    intervention_transition_payload,
    load_payload,
    make_merchant_operator_headers,
    make_remote_operator_headers,
    mission_transition_payload,
    open_intervention,
    read_intervention,
    read_merchant,
    read_mission,
    read_order,
    read_robot,
    read_segment,
    read_zone,
    segment_transition_payload,
    setup_active_merchant,
    setup_available_robot,
    setup_en_route_mission,
    setup_planned_mission,
    validate_error,
    validate_paginated,
    validate_success,
)

CORRIDOR_LENGTH_M = 774.0
#: The teleoperator who did not assume control.
OTHER_OPERATOR = make_remote_operator_headers("ro-2")


class TestRoleAdmissionIsDeclaredPerEndpoint:
    def test_five_senior_callers_are_each_refused_on_a_foreign_endpoint(self, api):
        """PRD §2.1: "If `X-User-Role` names something that is not a recognised
        role, or names a role that the target endpoint does not admit, the request is
        refused with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §2.10: "The ladder is walked from the top and stops at the first
        violated rule, and its bands are, in order: authentication and authorisation;
        request-payload syntax; existence of referenced rows; parent-version pinning;
        state of the target row and of the rows it depends on; safety and ordinance
        compliance; structural consistency of the submitted graph; and finally
        capacity, caps and budgets."

        The support dispatch also carries the order's pre-dispatch version, so the
        role band is visibly ahead of the version band.

        Design: Corner/rbac/forbidden_writes_are_rejected_per_endpoint_not_per_entity
        """
        ctx = setup_planned_mission()
        corridor = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
        stale_order_version = 1

        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], stale_order_version),
                SUPPORT,
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )
        validate_error(
            api.segment_transition(
                ctx["s3"], segment_transition_payload("RETIRE"), DISPATCHER
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )
        validate_error(
            api.create_route_plan(
                create_route_plan_payload(ctx["mi"], corridor, ctx["mission"]["version"]),
                OPERATOR,
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )
        validate_error(
            api.robot_duty_transition(
                ctx["r"], duty_transition_payload("RETIRE"), OFFICER
            ),
            "ERR_ROLE_FORBIDDEN",
            403,
        )
        validate_error(
            api.get_service_zone(ctx["z"], make_merchant_operator_headers(ctx["m"])),
            "ERR_ROLE_FORBIDDEN",
            403,
        )

        _plans, plan_meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"]})
        )
        assert read_segment(ctx["s3"])["status"] == "APPROVED"
        assert read_robot(ctx["r"])["duty_state"] == "ON_MISSION"
        assert plan_meta["total_count"] == 0

    def test_the_dispatcher_the_endpoint_declares_writes_the_same_plan(self, api):
        """PRD §4: "Submit a candidate route for a mission; derives the plan geometry
        and runs the six geometry gates, with optimistic concurrency on the parent
        mission."
        PRD §3.6: "`total_length_m` is the sum of `length_m` over the sequence in the
        given order, carried to one decimal place."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order that
        is dispatched a second time shows a count of two."

        Design: Corner/rbac/forbidden_writes_are_rejected_per_endpoint_not_per_entity
        """
        ctx = setup_planned_mission()
        corridor = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
        validate_error(
            api.create_route_plan(
                create_route_plan_payload(ctx["mi"], corridor, ctx["mission"]["version"]),
                OPERATOR,
            ),
            "ERR_ROLE_FORBIDDEN",
        )

        plan = validate_success(
            api.create_route_plan(
                create_route_plan_payload(ctx["mi"], corridor, ctx["mission"]["version"]),
                DISPATCHER,
            ),
            201,
        )

        assert plan["plan_state"] == "DRAFT"
        assert plan["total_length_m"] == CORRIDOR_LENGTH_M
        assert read_order(ctx["o"])["order_state"] == "DISPATCHED"
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 1


def _a_takeover_held_by_the_first_operator() -> dict:
    """An `ACTIVE`, non-mandatory takeover whose `operator_user_id` is ro-1."""
    ctx = setup_en_route_mission()
    event = open_intervention(ctx["mi"], 60, trigger_reason="CROSSING_ASSIST")
    intervention_action(event["id"], "ACKNOWLEDGE")
    ctx["event"] = intervention_action(event["id"], "ASSUME")
    ctx["ev"] = event["id"]
    return ctx


class TestTakeoverControlIsHeldByAUserNotARole:
    def test_a_second_operator_cannot_release_a_takeover_it_never_assumed(self, api):
        """PRD §2.1: "Last in the band comes the takeover-control check: escalating a
        takeover, or releasing one as a `RemoteOperator`, requires `X-User-ID` to equal
        `operator_user_id`, and a mismatch is refused with `ERR_NOT_RESOURCE_OWNER`; a
        `SafetyOfficer` releasing an escalated takeover is exempt from that
        comparison."
        PRD §3.7: "The takeover procedure walks `REQUESTED` to `ACKNOWLEDGED` on the
        `ACKNOWLEDGE` action and then to `ACTIVE` on the `ASSUME` action, which
        additionally requires the mission to be in `EN_ROUTE` or `BLOCKED` and which
        stamps `assumed_at_utc` and latches `operator_user_id` to the calling
        operator."

        Design: Corner/rbac/a_remote_operator_cannot_release_another_operators_takeover
        """
        ctx = _a_takeover_held_by_the_first_operator()

        refused = api.intervention_transition(
            ctx["ev"], intervention_transition_payload("RELEASE"), OTHER_OPERATOR
        )

        validate_error(refused, "ERR_NOT_RESOURCE_OWNER", 403)
        event = read_intervention(ctx["ev"])
        assert event["takeover_state"] == "ACTIVE"
        assert event["operator_user_id"] == OPERATOR["X-User-ID"]
        assert event["version"] == 3

    def test_only_the_holder_releases_and_thereby_unblocks_arrival(self, api):
        """PRD §3.7: "From `ACTIVE` the operator named in `operator_user_id`
        releases; from `ESCALATED` a `SafetyOfficer` may release regardless of who
        assumed control, while a `RemoteOperator` still needs to be that named
        operator."
        PRD §3.7: "Both of those forms set `control_seconds` to the whole seconds
        elapsed from `assumed_at_utc` to the current instant."
        PRD §3.7: "Arrival is a `FleetDispatcher` action carrying the mission from
        `EN_ROUTE` to `HANDOFF_READY`, and it is gated on the intervention set: no
        event of this mission may still be in `REQUESTED`, `ACKNOWLEDGED`, `ACTIVE` or
        `ESCALATED`, or the arrival is refused with `ERR_TAKEOVER_REQUIRED`."

        Design: Corner/rbac/a_remote_operator_cannot_release_another_operators_takeover
        """
        ctx = _a_takeover_held_by_the_first_operator()
        validate_error(
            api.intervention_transition(
                ctx["ev"], intervention_transition_payload("RELEASE"), OTHER_OPERATOR
            ),
            "ERR_NOT_RESOURCE_OWNER",
        )

        released = validate_success(
            api.intervention_transition(
                ctx["ev"], intervention_transition_payload("RELEASE"), OPERATOR
            )
        )
        arrived = validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("ARRIVE"), DISPATCHER
            )
        )

        assert released["takeover_state"] == "RELEASED"
        assert released["version"] == 4
        assert released["control_seconds"] == 0
        assert arrived["mission_state"] == "HANDOFF_READY"
        assert arrived["intervention_count"] == 1


def _two_merchants_with_one_order_each() -> dict:
    """Two active merchants in one zone, each holding a single 22-litre order."""
    ctx = setup_active_merchant()
    stranger = add_merchant(ctx["z"], name="Second Baker")
    ctx["m2"] = stranger["id"]
    ctx["stranger_headers"] = make_merchant_operator_headers(stranger["id"])
    ctx["order"] = add_order(ctx["m"], ctx["s5"], customer_ref="C-1")
    ctx["o"] = ctx["order"]["id"]
    ctx["order2"] = add_order(ctx["m2"], ctx["s5"], customer_ref="C-2")
    ctx["o2"] = ctx["order2"]["id"]
    return ctx


class TestMerchantReadsAreRowScoped:
    def test_an_unfiltered_listing_still_shows_a_merchant_only_its_own_row(self, api):
        """PRD §2.1: "That ownership rule guards order intake, order cancellation,
        container loading, the single-merchant read and the order list; on the order
        list and the merchant list a `MerchantOperator` sees only its own rows
        regardless of any filter it supplies."
        PRD §4: "List delivery orders, filtered by `merchant_id`,
        `dropoff_segment_id`, `order_state` and `exception_reason`."

        Design: Corner/rbac/merchant_operator_reads_are_scoped_to_its_own_rows
        """
        ctx = _two_merchants_with_one_order_each()

        mine, mine_meta = validate_paginated(
            api.list_delivery_orders(make_merchant_operator_headers(ctx["m"]))
        )
        _every_row, admin_meta = validate_paginated(api.list_delivery_orders(ADMIN))

        assert [row["id"] for row in mine] == [ctx["o"]]
        assert mine_meta["total_count"] == 1
        assert admin_meta["total_count"] == 2
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 850
        assert read_merchant(ctx["m2"])["escrowed_fee_cents"] == 850

    def test_a_cross_merchant_single_read_is_forbidden_rather_than_missing(self, api):
        """PRD §2.1: "Concretely, a `MerchantOperator` request is refused with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403) whenever `X-User-ID` does not equal the
        `Merchant` `id` that owns the target row — the merchant row itself, the
        `merchant_id` of a target order, or the `merchant_id` of the order behind a
        target mission."
        PRD §4: "Retrieve one delivery order with its quote, settlement, exception
        and remedy fields."

        Design: Corner/rbac/merchant_operator_reads_are_scoped_to_its_own_rows
        """
        ctx = _two_merchants_with_one_order_each()

        refused = api.get_delivery_order(
            ctx["o2"], make_merchant_operator_headers(ctx["m"])
        )
        owned = api.get_delivery_order(ctx["o2"], ctx["stranger_headers"])

        validate_error(refused, "ERR_NOT_RESOURCE_OWNER", 403)
        assert_error_envelope_shape(refused.json())
        order = validate_success(owned)
        assert order["id"] == ctx["o2"]
        assert order["merchant_id"] == ctx["m2"]


class TestPlatformAdminActsForAnyMerchant:
    def test_an_admin_intake_carries_the_merchant_grade_and_the_escrow(self, api):
        """PRD §3.3: "Order intake belongs to the merchant's own staff, and a
        `PlatformAdmin` may also perform it on any merchant's behalf without being
        subject to the ownership restriction."
        PRD §3.3: "Immediately afterwards the quoted amount is escrowed: the
        merchant's `escrowed_fee_cents` increases by `quoted_fee_cents` and the
        merchant's `version` advances by one."
        PRD §3.3: "`urgency_flag` is true when the interval from the order's
        `created_at` to its `promised_by_utc` is at most 45 minutes, and false
        otherwise."

        A 40-minute promise is urgent, so the gross is 176 + 349 + 120 + 180 + 70 and
        the preferred grade takes 5 percent off it.

        Design: Corner/rbac/platform_admin_acts_on_behalf_of_any_merchant
        """
        ctx = setup_available_robot()

        order = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"], ctx["s5"], customer_ref="C-ADMIN"
                ),
                ADMIN,
            ),
            201,
        )

        assert order["merchant_id"] == ctx["m"]
        assert order["urgency_flag"] is True
        assert order["quoted_fee_cents"] == 850
        assert order["order_state"] == "RECEIVED"
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 850

    def test_an_admin_may_also_perform_the_container_handoff(self, api):
        """PRD §2.1: "`MerchantOperator` is the one exception: when `X-User-Role` is
        `MerchantOperator`, `X-User-ID` is the `id` of the acting `Merchant` row, and
        ownership checks on any resource that references a merchant compare that
        reference to `X-User-ID`."
        PRD §3.7: "A successful handoff carries the mission from `PLANNED` to
        `LOADED`, stores `actual_payload_liters` and mints the lid access code from a
        per-zone monotonic counter: the zone's `lid_code_sequence` advances by one, and
        `lid_access_code` becomes the six-digit zero-padded decimal representation of
        100000 plus the new value of that sequence, so the first code minted in a zone
        is 100001."
        PRD §3.7: "The handoff is also timed against the merchant's promise:
        `handoff_late` is set to true when the elapsed time from the mission's
        `created_at` to the current instant strictly exceeds the merchant's
        `handoff_sla_seconds`, and false otherwise, so a handoff at exactly the SLA
        boundary is on time."

        Design: Corner/rbac/platform_admin_acts_on_behalf_of_any_merchant
        """
        ctx = setup_available_robot()
        order = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"], ctx["s5"], customer_ref="C-ADMIN"
                ),
                ADMIN,
            ),
            201,
        )
        mission = validate_success(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    order["id"], ctx["r"], order["version"]
                ),
                DISPATCHER,
            ),
            201,
        )

        loaded = validate_success(
            api.load_delivery_mission(mission["id"], load_payload(22.0), ADMIN)
        )

        assert mission["mission_state"] == "PLANNED"
        assert loaded["mission_state"] == "LOADED"
        assert loaded["lid_access_code"] == "100001"
        assert loaded["handoff_late"] is False
        assert read_zone(ctx["z"])["lid_code_sequence"] == 1
        assert read_mission(mission["id"])["actual_payload_liters"] == 22.0
