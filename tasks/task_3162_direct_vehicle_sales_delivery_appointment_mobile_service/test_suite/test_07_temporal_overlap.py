"""Interval placement: buffered handover bays versus unbuffered van windows."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    dispatch_and_arrive,
    dispatch_mobile_visit,
    get_order,
    get_success_data,
    lock_order,
    next_vin,
    place_order,
    set_clock,
    settle_order_fee,
    setup_triaged_mobile_appointment,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TECH = TEST_USERS["service_technician_headers"]


def _two_orders_at_one_center(api, bay_count=1):
    """Two fully arrived orders at a single center with the given bay count."""
    jur = create_and_enact_jurisdiction(delivery_buffer_minutes=60)
    center = create_center(center_name="El Paso Delivery", bay_count=bay_count,
                           van_count=0)
    config, _ = create_published_configuration()
    batch, _unit = create_and_start_batch(unit_capacity=2,
                                          planned_completion_at="2026-09-10T00:00:00Z")

    orders = []
    for name in ("Kim Buffer", "Lee Buffer"):
        buyer = create_verified_buyer(full_name=name,
                                      email=f"{name.lower().replace(' ', '.')}"
                                            f"@example.com")
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        placed = place_order(order["id"], order["version"], buyer["id"])
        locked = lock_order(order["id"], placed["version"])
        get_success_data(api.mint_allocation_unit(batch["id"], next_vin(), ADMIN))
        get_success_data(api.allocate_order(order["id"], batch["id"], locked["version"], ADMIN))
        dispatch_and_arrive(order["id"])
        orders.append((buyer, get_order(order["id"])))
    return jur, center, orders


class TestHandoverBayBuffer:
    """PRD §2.6: handover bays are widened by the jurisdiction buffer."""

    def test_a_gap_inside_the_buffer_is_refused(self, api):
        """PRD §2.6: "Before that test is applied, the incoming interval is
        widened at both ends by the applicable buffer: `delivery_buffer_minutes`
        for handover bays"
        PRD §2.6: "Any two buffered intervals that share a single instant fail the
        test."

        Design: Difficulty/resource_temporal_overlap/delivery_bay_buffered_gap_rejects_sub_buffer_booking
        """
        set_clock()
        jur, center, orders = _two_orders_at_one_center(api, bay_count=1)
        (buyer_a, order_a), (buyer_b, order_b) = orders

        first = get_success_data(api.book_delivery_appointment(
            {"order_id": order_a["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:07:00Z",
             "scheduled_end": "2026-09-22T16:00:00Z",
             "expected_order_version": order_a["version"]},
            ADVISOR))
        get_success_data(api.confirm_delivery_appointment(first["id"], ADVISOR))

        challenged = api.book_delivery_appointment(
            {"order_id": order_b["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T16:30:00Z",
             "scheduled_end": "2026-09-22T17:30:00Z",
             "expected_order_version": order_b["version"]},
            ADVISOR)
        validate_error(challenged, "ERR_DELIVERY_SLOT_CONFLICT")

    def test_a_gap_equal_to_the_buffer_is_accepted(self, api):
        """PRD §2.6: "a slot ending at 10:00 and another starting at 10:00 do not
        collide"
        PRD §3.6: "A successful center booking increments `booked_slot_count` by one"
        PRD §3.6: "captures `buffer_minutes` from the governing regime and freezes
        it for the life of the appointment"

        Design: Difficulty/resource_temporal_overlap/delivery_bay_buffered_gap_rejects_sub_buffer_booking
        """
        set_clock()
        jur, center, orders = _two_orders_at_one_center(api, bay_count=1)
        (buyer_a, order_a), (buyer_b, order_b) = orders

        first = get_success_data(api.book_delivery_appointment(
            {"order_id": order_a["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T15:07:00Z",
             "scheduled_end": "2026-09-22T16:00:00Z",
             "expected_order_version": order_a["version"]},
            ADVISOR))
        get_success_data(api.confirm_delivery_appointment(first["id"], ADVISOR))

        # Both intervals are widened by the 60-minute buffer, so the incoming
        # window has to clear the outgoing one's buffered end: a start of 18:00
        # makes the two buffered intervals meet at 17:00 without sharing it.
        accepted = get_success_data(api.book_delivery_appointment(
            {"order_id": order_b["id"], "delivery_center_id": center["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-22T18:00:00Z",
             "scheduled_end": "2026-09-22T19:00:00Z",
             "expected_order_version": order_b["version"]},
            ADVISOR))

        assert accepted["buffer_minutes"] == 60
        assert first["buffer_minutes"] == 60
        assert get_success_data(
            api.get_delivery_center(center["id"], ADMIN))["booked_slot_count"] == 2


class TestVanWindowAdjacency:
    """PRD §2.6: van windows use plain half-open intervals with no buffer."""

    def test_a_window_overlapping_the_prior_one_is_refused(self, api):
        """PRD §2.6: "Two mobile dispatch windows assigned to the same `van_code`
        must not overlap; the colliding request is refused with
        `ERR_VAN_SCHEDULE_CONFLICT` (HTTP 409)."
        PRD §2.6: "A booked interval runs from an inclusive start instant to an
        exclusive end instant, so a slot ending at 10:00 and another starting at
        10:00 do not collide."

        Design: Difficulty/resource_temporal_overlap/mobile_van_adjacent_intervals_rejected_without_buffer
        """
        set_clock()
        ctx = setup_triaged_mobile_appointment(fault_code="TK-2201", severity="MEDIUM",
                                               buyer_name="Ada Van")
        second = setup_triaged_mobile_appointment(fault_code="TK-2202", severity="MEDIUM",
                                                  buyer_name="Ben Van")

        dispatch_mobile_visit(ctx["appointment"]["id"], ctx["hub"]["id"],
                              ctx["appointment"]["version"], van_code="VAN-ADJ-1",
                              start="2026-09-28T13:00:00Z",
                              end="2026-09-28T16:00:00Z",
                              labor_hours=2.0, parts_cost_cents=0, visit_miles=10)

        # Both dispatches name the same van, and the second window begins inside
        # the first: the intervals share more than a single instant, which is the
        # collision the van rule refuses.
        challenged = api.dispatch_mobile_visit(
            {"service_appointment_id": second["appointment"]["id"],
             "parts_hub_id": second["hub"]["id"],
             "van_code": "VAN-ADJ-1",
             "visit_start": "2026-09-28T15:00:00Z",
             "visit_end": "2026-09-28T18:00:00Z",
             "labor_hours": 2.0,
             "parts_cost_cents": 0,
             "visit_miles": 10,
             "expected_service_appointment_version": second["appointment"]["version"]},
            TECH)
        validate_error(challenged, "ERR_VAN_SCHEDULE_CONFLICT")

    def test_a_window_fifteen_minutes_later_is_accepted(self, api):
        """PRD §2.6: "A booked interval runs from an inclusive start instant to an
        exclusive end instant"
        PRD §3.9: "A successful dispatch moves the appointment to
        `MOBILE_DISPATCHED`"

        Design: Difficulty/resource_temporal_overlap/mobile_van_adjacent_intervals_rejected_without_buffer
        """
        set_clock()
        ctx = setup_triaged_mobile_appointment(fault_code="TK-2201", severity="MEDIUM",
                                               buyer_name="Ada Van")
        second = setup_triaged_mobile_appointment(fault_code="TK-2202", severity="MEDIUM",
                                                  buyer_name="Ben Van")

        dispatch_mobile_visit(ctx["appointment"]["id"], ctx["hub"]["id"],
                              ctx["appointment"]["version"], van_code="VAN-ADJ-1",
                              start="2026-09-28T13:00:00Z",
                              end="2026-09-28T16:00:00Z",
                              labor_hours=2.0, parts_cost_cents=0, visit_miles=10)

        accepted = dispatch_mobile_visit(second["appointment"]["id"],
                                         second["hub"]["id"],
                                         second["appointment"]["version"],
                                         van_code="VAN-ADJ-1",
                                         start="2026-09-28T16:15:00Z",
                                         end="2026-09-28T18:15:00Z",
                                         labor_hours=2.0, parts_cost_cents=0,
                                         visit_miles=10)
        assert accepted["status"] == "DRAFT"
        dispatched = get_success_data(api.get_service_appointment(
            second["appointment"]["id"], TECH))
        assert dispatched["status"] == "MOBILE_DISPATCHED"
