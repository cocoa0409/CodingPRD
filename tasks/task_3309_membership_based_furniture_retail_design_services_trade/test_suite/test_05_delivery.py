"""Design consultations and white-glove delivery: extensions, capacity, dispatch."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_member_quote_with_consultation,
    setup_delivered_stock_order,
    create_retail_quote,
    add_line,
    confirm_order,
    schedule_appointment,
    deliver_order,
    read_order,
    set_clock,
    run_daily_cycle,
    create_design_consultation_payload,
    create_delivery_appointment_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
HUB = TEST_USERS["hub_operator_headers"]


class TestConsultationExtension:

    def test_consultation_completion_extends_quote_expiry(self, api):
        """PRD §3.6: "the consultation moves `SCHEDULED → COMPLETED`, stamps `completed_at` with the clock, and — if the attached order is still in `QUOTE` — extends the quote: `quote_expires_at` gains 14 days and `consultation_extensions_used` increments by 1."
        PRD §3.4: "The new order enters in `QUOTE` with `quote_expires_at` set to 14 days after its creation time and `consultation_extensions_used` at zero."

        Design: Corner/calculations/consultation_completion_extends_quote_expiry
        """
        setup = setup_member_quote_with_consultation(list_price_cents=10000)
        consultation = setup["consultation"]
        assert consultation["status"] == "SCHEDULED"

        get_success_data(
            api.complete_design_consultation(
                consultation["id"], {"design_plan_notes": "plan"}, ASSOCIATE
            )
        )
        order_after = read_order(setup["order"]["id"])
        assert order_after["quote_expires_at"] == "2026-09-29T00:00:00.000Z"
        assert order_after["consultation_extensions_used"] == 1

    def test_consultation_double_complete_rejected(self, api):
        """PRD §3.6: "`COMPLETED` and `CANCELLED` are both terminal."

        Design: Corner/state_machines/consultation_double_complete_rejected
        """
        setup = setup_member_quote_with_consultation(list_price_cents=10000)
        get_success_data(
            api.complete_design_consultation(
                setup["consultation"]["id"], {"design_plan_notes": "done"}, ASSOCIATE
            )
        )
        resp = api.complete_design_consultation(
            setup["consultation"]["id"], {"design_plan_notes": "again"}, ASSOCIATE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestDeliveryCapacity:

    def test_route_daily_aggregate_capacity_budget(self, api):
        """PRD §3.7: "A new appointment is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422) when the minutes already consumed on that date plus the new appointment's duration plus its 30-minute buffer would be strictly greater than the gallery's `daily_route_minutes_capacity` — landing exactly on the budget is allowed."
        PRD §3.7: "Every appointment consumes its `duration_minutes` plus a fixed 30-minute route buffer"

        Design: Difficulty/resource_temporal_overlap/route_daily_aggregate_capacity_budget
        """
        gallery = setup_gallery(name="Gallery O", daily_route_minutes_capacity=480)
        product = setup_product(list_price_cents=10000, line_kind="STOCK")

        order_ids = []
        for _ in range(3):
            order = create_retail_quote(gallery["id"])
            add_line(order["id"], product["id"], qty=1)
            confirm_order(order["id"])
            order_ids.append(order["id"])

        a1 = validate_success(
            api.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order_ids[0], gallery["id"], delivery_date="2026-09-05",
                    duration_minutes=200, room_placement=True, assembly_required=True,
                ),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert a1["status"] == "SCHEDULED"
        a2 = validate_success(
            api.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order_ids[1], gallery["id"], delivery_date="2026-09-05",
                    duration_minutes=200, room_placement=True, assembly_required=False,
                ),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert a2["status"] == "SCHEDULED"

        gallery_after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert gallery_after["booked_route_minutes"] == {"2026-09-05": 460}

        resp = api.create_delivery_appointment(
            create_delivery_appointment_payload(
                order_ids[2], gallery["id"], delivery_date="2026-09-05",
                duration_minutes=100, room_placement=False, assembly_required=False,
            ),
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)

    def test_route_capacity_exactly_at_budget_allowed(self, api):
        """PRD §3.7: "landing exactly on the budget is allowed."

        Design: Difficulty/resource_temporal_overlap/route_daily_aggregate_capacity_budget
        """
        gallery = setup_gallery(name="Gallery O2", daily_route_minutes_capacity=480)
        product = setup_product(list_price_cents=10000, line_kind="STOCK")

        order_ids = []
        for _ in range(2):
            order = create_retail_quote(gallery["id"])
            add_line(order["id"], product["id"], qty=1)
            confirm_order(order["id"])
            order_ids.append(order["id"])

        # First consumes 230 (200 + 30 buffer); second consumes 250 (220 + 30): total 480.
        validate_success(
            api.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order_ids[0], gallery["id"], delivery_date="2026-09-05",
                    duration_minutes=200,
                ),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order_ids[1], gallery["id"], delivery_date="2026-09-05",
                    duration_minutes=220,
                ),
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert second["status"] == "SCHEDULED"
        gallery_after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert gallery_after["booked_route_minutes"] == {"2026-09-05": 480}


class TestAppointmentLifecycle:

    def test_ops_run_dispatches_due_appointment(self, api):
        """PRD §3.7: "On the morning of the route, the daily ops run dispatches every `SCHEDULED` appointment whose `delivery_date` has been reached — the clock's calendar date at or past the appointment's date — moving it to `OUT_FOR_DELIVERY`."

        Design: Corner/cross_cutting_layers/ops_run_dispatches_due_appointment
        """
        gallery = setup_gallery(name="Gallery X3")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        confirm_order(order["id"])
        appointment = schedule_appointment(order["id"], gallery["id"],
                                           delivery_date="2026-09-05")
        assert appointment["status"] == "SCHEDULED"

        set_clock("2026-09-05T08:00:00Z")
        run_daily_cycle()

        after = get_success_data(api.get_delivery_appointment(appointment["id"], ADMIN))
        assert after["status"] == "OUT_FOR_DELIVERY"

    def test_completed_appointment_is_terminal(self, api):
        """PRD §3.7: "Both `COMPLETED` and `RESCHEDULED` are terminal; `FAILED` is not — it awaits replacement by a newly scheduled appointment, as above."
        PRD §3.7: "Outcome recording belongs to the `HubOperator` and applies only from `OUT_FOR_DELIVERY` (recording from any other state is `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/completed_appointment_is_terminal
        """
        setup = setup_delivered_stock_order(list_price_cents=10000)
        appointment = setup["appointment"]

        resp = api.record_appointment_outcome(
            appointment["id"], {"outcome": "FAILED", "failure_reason": "late"}, HUB
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_failed_delivery_releases_route_minutes(self, api):
        """PRD §3.7: "A `FAILED` outcome requires a `failure_reason` to be supplied and likewise releases the booked minutes."
        PRD §3.7: "Every appointment consumes its `duration_minutes` plus a fixed 30-minute route buffer, and the gallery's `booked_route_minutes` maps each ISO date to the sum of those consumed minutes over its appointments on that date in `SCHEDULED` or `OUT_FOR_DELIVERY`."

        Design: Difficulty/compensating_invariant/route_minutes_restored_on_failed_delivery
        """
        gallery = setup_gallery(name="Gallery P", daily_route_minutes_capacity=480)
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        confirm_order(order["id"])
        appointment = schedule_appointment(
            order["id"], gallery["id"], delivery_date="2026-09-05", duration_minutes=200
        )

        before = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert before["booked_route_minutes"] == {"2026-09-05": 230}

        set_clock("2026-09-05T08:00:00Z")
        run_daily_cycle()
        failed = validate_success(
            api.record_appointment_outcome(
                appointment["id"],
                {"outcome": "FAILED", "failure_reason": "customer unavailable"},
                HUB,
            )
        )
        assert failed["status"] == "FAILED"

        after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert after["booked_route_minutes"] == {}

    def test_completed_delivery_releases_route_minutes(self, api):
        """PRD §3.7: "A `COMPLETED` outcome captures whether packaging removal was performed into `packaging_removed` (the field is false until then) and releases the appointment's minutes — duration plus buffer — from the gallery's `booked_route_minutes` for that date."

        Design: Difficulty/compensating_invariant/route_minutes_restored_on_failed_delivery
        """
        gallery = setup_gallery(name="Gallery P2", daily_route_minutes_capacity=480)
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        confirm_order(order["id"])
        appointment = schedule_appointment(
            order["id"], gallery["id"], delivery_date="2026-09-05", duration_minutes=200
        )
        assert appointment["packaging_removed"] is False

        before = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert before["booked_route_minutes"] == {"2026-09-05": 230}

        set_clock("2026-09-05T08:00:00Z")
        run_daily_cycle()
        completed = validate_success(
            api.record_appointment_outcome(
                appointment["id"], {"outcome": "COMPLETED", "packaging_removed": True}, HUB
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["packaging_removed"] is True

        after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert after["booked_route_minutes"] == {}

        order_after = read_order(order["id"])
        assert order_after["status"] == "DELIVERED"
