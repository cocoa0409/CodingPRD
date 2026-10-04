"""Emergency response: the cabinet-open cascade, acknowledgement rules,
maintenance gating on open events, and replenishment conservation.

Design: Difficulty/transitive_cascade/cabinet_open_cascade_five_hop,
        Difficulty/compensating_invariant/replenish_receive_conserves_pad_quantity_per_event,
        Corner/errors/err_device_in_event_blocks_maintenance,
        Corner/errors/err_event_already_acked_on_second_ack,
        Corner/validations/responder_not_certified_cannot_acknowledge.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_event,
    create_lot,
    create_responder,
    get_device,
    get_success_data,
    install_consumable,
    make_responder_headers,
    open_cabinet_event,
    resolve_event,
    set_clock,
    setup_commissioned_device,
    setup_campus_zone_cabinet_device,
    setup_resolved_event,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
    create_campus,
    create_device,
    create_device_model,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestCabinetOpenCascade:

    def test_open_acknowledge_resolve_cascade_with_pads_consumed(self, api):
        """PRD: "the cabinet's `status` becomes `ALARM_OPEN`; the device's
        `status` becomes `POST_EVENT`". PRD: "On resolution the event's `status`
        becomes `RESOLVED` and its `closed_at` is set; the cabinet's `status`
        returns to `OCCUPIED`". PRD: "When `pads_consumed` is declared true, the
        consumable cascade fires: the device's active pad install transitions to
        `CONSUMED_IN_EVENT`, the device's `current_pad_install_id` is cleared,
        and a **ReplenishmentOrder** is auto-created with `kind` equal to `PAD`,
        `quantity` equal to exactly 1 — the v1 rule pins replenishment at one
        pad unit per event — `status` equal to `PENDING`, and its
        `emergency_event_id` bound to the resolved event."

        Design: Difficulty/transitive_cascade/cabinet_open_cascade_five_hop
        """
        ctx = setup_commissioned_device(serial_number="SN-007")
        pad_install_id = ctx["pad_install"]["id"]
        event = open_cabinet_event(ctx)
        assert event["status"] == "OPEN"

        # Cascade at open: cabinet ALARM_OPEN, device POST_EVENT.
        cab = get_success_data(api.get_cabinet(ctx["cabinet"]["id"], PM))
        assert cab["status"] == "ALARM_OPEN"
        assert get_device(ctx["device"]["id"])["status"] == "POST_EVENT"

        acknowledge_event(event["id"], ctx["responder"]["id"])
        resolved = resolve_event(event["id"], ctx["responder"]["id"],
                                 hospital_code="H-7",
                                 patient_transported=True,
                                 pads_consumed=True)
        assert resolved["status"] == "RESOLVED"

        cab_after = get_success_data(api.get_cabinet(ctx["cabinet"]["id"], PM))
        assert cab_after["status"] == "OCCUPIED"
        assert get_device(ctx["device"]["id"])["status"] == "POST_EVENT"

        install_after = get_success_data(api.get_install(pad_install_id, PM))
        assert install_after["disposition"] == "CONSUMED_IN_EVENT"

        orders, _ = validate_paginated(
            api.list_replenishment_orders(
                PM, params={"campus_id": ctx["campus"]["id"],
                            "emergency_event_id": event["id"]}
            )
        )
        assert len(orders) == 1
        assert orders[0]["kind"] == "PAD"
        assert orders[0]["quantity"] == 1
        assert orders[0]["status"] == "PENDING"

    def test_resolve_without_pads_consumed_creates_no_replenishment(self, api):
        """PRD: "The replenishment-quantity rule is deliberately fixed: when
        `pads_consumed` is true the quantity is 1, otherwise no order is created
        at all."

        Design: Difficulty/transitive_cascade/cabinet_open_cascade_five_hop
        """
        ctx = setup_commissioned_device(serial_number="SN-007B")
        pad_install_id = ctx["pad_install"]["id"]
        event = open_cabinet_event(ctx)
        acknowledge_event(event["id"], ctx["responder"]["id"])
        resolved = resolve_event(event["id"], ctx["responder"]["id"],
                                 hospital_code="H-7B",
                                 patient_transported=True,
                                 pads_consumed=False)
        assert resolved["status"] == "RESOLVED"

        install_after = get_success_data(api.get_install(pad_install_id, PM))
        assert install_after["disposition"] == "ACTIVE"

        orders, meta = validate_paginated(
            api.list_replenishment_orders(
                PM, params={"campus_id": ctx["campus"]["id"],
                            "emergency_event_id": event["id"]}
            )
        )
        assert orders == []
        assert meta["total_count"] == 0


class TestMaintenanceBlockedByOpenEvent:

    def test_send_to_maintenance_rejected_while_event_open(self, api):
        """PRD: "A `ProgramManager` sends it to maintenance, but only once every
        emergency event referencing the device has reached `RESOLVED`,
        `CASE_REVIEW`, or `CLOSED` — an open event blocks the transition with
        `ERR_DEVICE_IN_EVENT`."

        Design: Corner/errors/err_device_in_event_blocks_maintenance
        """
        ctx = setup_commissioned_device(serial_number="SN-IE-1")
        open_cabinet_event(ctx)
        res = api.send_device_to_maintenance(ctx["device"]["id"], PM)
        validate_error(res, ApiErrorId.ERR_DEVICE_IN_EVENT, expected_status=409)
        assert get_device(ctx["device"]["id"])["status"] == "POST_EVENT"


class TestAcknowledgeRules:

    def test_second_acknowledge_rejected(self, api):
        """PRD: "The first acknowledgement moves the event from `OPEN` to
        `RESPONDING` and records the first-acknowledged responder; a second
        acknowledgement attempt is rejected with `ERR_EVENT_ALREADY_ACKED`."

        Design: Corner/errors/err_event_already_acked_on_second_ack
        """
        ctx = setup_commissioned_device(serial_number="SN-AA-1")
        campus = ctx["campus"]
        second = create_responder(
            campus["id"], responder_role="LAY_RESPONDER",
            full_name="R2", badge_number="R-AA-2",
        )
        from test_helpers import certify_responder
        certify_responder(campus["id"], second["id"],
                          ctx["medical_director"]["id"])

        event = open_cabinet_event(ctx)
        acknowledge_event(event["id"], ctx["responder"]["id"])
        res = api.acknowledge_emergency_event(
            event["id"], make_responder_headers(second["id"])
        )
        validate_error(res, ApiErrorId.ERR_EVENT_ALREADY_ACKED,
                       expected_status=409)

    def test_uncertified_responder_cannot_acknowledge(self, api):
        """PRD: "the acknowledging responder must have `status` equal to
        `ACTIVE` and a `certified_through` later than the current time, else the
        acknowledgement is rejected with `ERR_RESPONDER_NOT_CERTIFIED`." PRD:
        "A new responder starts with `status` equal to `ACTIVE` and
        `certified_through` null".

        Design: Corner/validations/responder_not_certified_cannot_acknowledge
        """
        ctx = setup_commissioned_device(serial_number="SN-NC-1",
                                        with_certified_responder=False)
        uncertified = create_responder(
            ctx["campus"]["id"], responder_role="LAY_RESPONDER",
            full_name="R", badge_number="R-NC",
        )
        event = open_cabinet_event(ctx)
        res = api.acknowledge_emergency_event(
            event["id"], make_responder_headers(uncertified["id"])
        )
        validate_error(res, ApiErrorId.ERR_RESPONDER_NOT_CERTIFIED,
                       expected_status=422)


class TestReplenishmentConservation:

    def test_receive_creates_lot_conserving_pad_quantity(self, api):
        """PRD: "a **ReplenishmentOrder** is auto-created with `kind` equal to
        `PAD`, `quantity` equal to exactly 1 — the v1 rule pins replenishment at
        one pad unit per event — `status` equal to `PENDING`". PRD: "On receipt
        the order's `status` becomes `RECEIVED`, a new **ConsumableLot** is
        created of the order's `kind` with `quantity_received` equal to the
        order's `quantity`, and the order's `received_lot_id` is set to the new
        lot."

        Design: Difficulty/compensating_invariant/replenish_receive_conserves_pad_quantity_per_event
        """
        ctx = setup_resolved_event(serial_number="SN-018", pads_consumed=True)
        event = ctx["event"]
        orders, _ = validate_paginated(
            api.list_replenishment_orders(
                PM, params={"campus_id": ctx["campus"]["id"],
                            "emergency_event_id": event["id"]}
            )
        )
        assert len(orders) == 1
        order = orders[0]
        assert order["quantity"] == 1

        received = validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"lot_code": "P18-new",
                 "manufacturer_expires_at": "2031-01-01T00:00:00Z"},
                PM,
            )
        )
        assert received["status"] == "RECEIVED"
        new_lot = get_success_data(
            api.get_consumable_lot(received["received_lot_id"], PM)
        )
        # Conservation: 1 pad consumed -> exactly 1 pad replenished.
        assert new_lot["quantity_received"] == 1
        assert new_lot["kind"] == "PAD"

    def test_receive_rejected_when_lot_fields_missing(self, api):
        """PRD: "Receipt is valid only while the order is still `PENDING` and
        only when both payload fields are provided; otherwise it is rejected
        with `ERR_REPLENISHMENT_INVALID`."

        Design: Difficulty/compensating_invariant/replenish_receive_conserves_pad_quantity_per_event
        """
        ctx = setup_resolved_event(serial_number="SN-018B", pads_consumed=True)
        event = ctx["event"]
        orders, _ = validate_paginated(
            api.list_replenishment_orders(
                PM, params={"campus_id": ctx["campus"]["id"],
                            "emergency_event_id": event["id"]}
            )
        )
        order = orders[0]
        res = api.receive_replenishment_order(
            order["id"], {"lot_code": "P18-only"}, PM
        )
        validate_error(res, ApiErrorId.ERR_REPLENISHMENT_INVALID,
                       expected_status=422)
