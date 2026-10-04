"""Each corner error is reachable through its own named violation."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_catering_order_payload,
    create_sub_ticket_payload,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def test_an_empty_lines_array_triggers_the_cart_error():
    """PRD §3.4: "A ticket must carry at least one line and every line's
    `half_lb_units` must be at least 1; an empty ticket is rejected with
    `ERR_EMPTY_CART`."

    Design: Corner/errors/empty_cart_error_is_triggered_by_a_zero_line_ticket
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)

    empty = api_client.create_sub_ticket(
        create_sub_ticket_payload(
            store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
            order_channel="DIGITAL", lines=[],
        ),
        clerk_headers(master.a1["id"]),
    )
    validate_error(empty, ApiErrorId.ERR_EMPTY_CART)

    ok = validate_success(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 1,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert ok["status"] == "QUEUED", "the error is specific to the empty collection"


def test_a_withdrawn_catalog_item_triggers_the_unavailable_error():
    """PRD §3.1: "Items carry a `status` of `ACTIVE` or `DISCONTINUED`, and a
    referenced item that is missing or discontinued blocks the ticket or batch
    that named it with `ERR_DELI_ITEM_UNAVAILABLE`."

    Design: Corner/errors/deli_item_uavailable_error_is_triggered_by_a_discontinued_item
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)

    current = validate_success(api_client.get_item(master.j2["id"], platform_admin_headers()))
    patched = validate_success(
        api_client.update_item(
            master.j2["id"],
            {"status": "DISCONTINUED", "expected_item_version": current["version"]},
            platform_admin_headers(),
        )
    )
    assert patched["status"] == "DISCONTINUED"

    withdrawn = api_client.create_sub_ticket(
        create_sub_ticket_payload(
            store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
            order_channel="DIGITAL",
            lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 2, "line_sequence_number": 1}],
        ),
        clerk_headers(master.a1["id"]),
    )
    validate_error(withdrawn, ApiErrorId.ERR_DELI_ITEM_UNAVAILABLE)

    active = validate_success(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j3["id"], "half_lb_units": 2,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert active["status"] == "QUEUED", "the trigger is the status, not the identifier"


def test_losing_every_clean_slicer_triggers_the_no_clean_slicer_error():
    """PRD §3.4: "It is refused when any line names an item whose `slicer_required`
    flag is true and the store has no `CLEAN` slicer at all, with
    `ERR_NO_CLEAN_SLICER`."

    Design: Corner/errors/no_clean_slicer_error_is_triggered_when_every_slicer_needs_sanitation
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    slicer = master.slicers[0]
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-C", 125, produced_lbs=125,
                  slicer_id=slicer["id"])

    ticket = validate_success(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 4,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        ), expected_status=201)
    refused = api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    validate_error(refused, ApiErrorId.ERR_NO_CLEAN_SLICER)

    clean = api_client.list_slicers(
        clerk_headers(master.a1["id"]), {"store_id": master.s, "sanitation_status": "CLEAN"}
    )
    assert clean.json()["data"] == [], "the read corroborates that no slicer is eligible"


def test_a_file_carrying_issued_labels_cannot_be_withdrawn():
    """PRD §3.6: "It is refused with `ERR_PRICE_FILE_IN_USE` when any `ISSUED`
    label references the file."

    Design: Corner/errors/price_file_in_use_error_blocks_withdrawal_while_labels_exist
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    price_file = master.price_file
    label = validate_success(
        api_client.create_label(
            {"store_id": master.s, "subject_type": "CATERING_PLATTER",
             "subject_ref_id": master.p1["id"], "net_weight_lbs": 2, "unit_price_cents": 1800},
            scale_operator_headers(),
        ),
        expected_status=201,
    )
    assert label["status"] == "ISSUED"

    refused = api_client.retract_price_file(price_file["id"], scale_operator_headers())
    validate_error(refused, ApiErrorId.ERR_PRICE_FILE_IN_USE)

    unchanged = validate_success(api_client.get_price_file(price_file["id"], platform_admin_headers()))
    assert unchanged["status"] == "ACTIVE", "the rejected retract wrote nothing"

    labels = api_client.list_labels(
        platform_admin_headers(), {"store_id": master.s, "price_file_id": price_file["id"]}
    )
    assert len(labels.json()["data"]) == 1, "the precondition that produced the error"


def test_a_pickup_at_the_exclusive_window_end_is_refused():
    """PRD §3.7: "Picking up requires the logical clock to sit strictly inside the
    half-open pickup window; a pickup requested at or after `pickup_window_end` is
    refused with `ERR_PICKUP_WINDOW_MISSED`."

    Design: Corner/errors/pickup_window_missed_is_triggered_at_the_exclusive_window_end
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    order = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"], customer_name="Window Party",
                lead_time_hours=6, pickup_window_start="2026-09-02T14:00:00Z",
                pickup_window_end="2026-09-02T15:00:00Z",
                certified_planner_associate_id=master.a1["id"], request_id="REQ-WIN",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.start_catering_production(order["id"], clerk_headers(master.a1["id"])))
    # PRD §3.7: marking ready requires the clock within two hours of the window start.
    set_clock("2026-09-02T12:30:00Z")
    validate_success(api_client.mark_catering_ready(order["id"], clerk_headers(master.a1["id"])))

    set_clock("2026-09-02T14:59:59Z")
    inside = validate_success(api_client.pickup_catering_order(order["id"], clerk_headers(master.a1["id"])))
    assert inside["status"] == "PICKED_UP", "one second before the bound is still inside the window"


def test_a_missed_pickup_window_freezes_the_stores_fresh_work():
    """PRD §3.7: "While a catering order sits past its `pickup_window_end` but
    short of `PICKED_UP`, the store is under a half-open pickup-window lockout."
    PRD §3.7: "The freeze lifts when the order is finally picked up or cancelled."

    Design: Corner/errors/overnight_window_error_is_triggered_by_a_missed_pickup_order
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    order = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"], customer_name="Missed Party",
                lead_time_hours=4, pickup_window_start="2026-09-02T10:00:00Z",
                pickup_window_end="2026-09-02T11:00:00Z",
                certified_planner_associate_id=master.a1["id"], request_id="REQ-MISS",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.start_catering_production(order["id"], clerk_headers(master.a1["id"])))
    # PRD §3.7: marking ready requires the store to be within two hours of the
    # pickup window start, and the lockout engages once the window end has passed.
    set_clock("2026-09-02T09:00:00Z")
    validate_success(api_client.mark_catering_ready(order["id"], clerk_headers(master.a1["id"])))
    set_clock("2026-09-02T11:30:00Z")

    frozen = api_client.create_batch(
        {"store_id": master.s, "deli_item_id": master.j1["id"],
         "produced_by_associate_id": master.a1["id"], "batch_code": "B-FREEZE", "planned_lbs": 3},
        clerk_headers(master.a1["id"]),
    )
    validate_error(frozen, ApiErrorId.ERR_HACCP_WINDOW_FREEZE)

    validate_success(
        api_client.cancel_catering_order(order["id"], "unclaimed", manager_headers(master.a2["id"]))
    )
    thawed = validate_success(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j1["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-THAW", "planned_lbs": 3},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert thawed["production_status"] == "PLANNED"