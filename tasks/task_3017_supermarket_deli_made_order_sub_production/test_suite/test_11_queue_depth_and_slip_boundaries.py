"""The queue-depth gate and the slip-lock boundary at the promised time."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def _setup_store_ready_to_ticket():
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=4, clerk_allergy_set=("MILK", "WHEAT"))
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])
    return master


def _create_ticket(master, half_lb_units):
    return get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": half_lb_units,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )


def test_empty_eligible_queue_reads_a_depth_of_zero():
    """PRD §3.4: "The store's queue depth is the count of gate-eligible tickets,
    and it reads zero for an empty eligible set."

    Design: Difficulty/boundary_precision_check/queue_latency_boundaries_on_empty_and_exact_match
    """
    master = _setup_store_ready_to_ticket()
    queue = validate_success(
        api_client.get_sub_queue(platform_admin_headers(), {"store_id": master.s})
    )
    assert queue["queue_depth"] == 0
    assert queue["ordered_total_count"] == 0


def test_the_ninth_gate_eligible_ticket_is_refused_at_the_depth_boundary():
    """PRD §3.4: "it is refused when the store's eligible queue already holds
    eight or more gate-eligible tickets, with `ERR_QUEUE_DEPTH_BREACH` — the gate
    counts only tickets already at `TICKETED` or `IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/queue_latency_boundaries_on_empty_and_exact_match
    """
    master = _setup_store_ready_to_ticket()
    tickets = [_create_ticket(master, 2) for _ in range(9)]

    for ticket in tickets[:8]:
        validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))

    queue = validate_success(api_client.get_sub_queue(platform_admin_headers(), {"store_id": master.s}))
    assert queue["queue_depth"] == 8, "the eighth ticketing is the last one admitted"

    response = api_client.ticket_sub_ticket(tickets[8]["id"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_QUEUE_DEPTH_BREACH)

    refused = validate_success(api_client.get_sub_ticket(tickets[8]["id"], platform_admin_headers()))
    assert refused["status"] == "QUEUED", "the rejected ticketing left the ticket untouched"


def test_a_late_completion_sets_the_slip_basis_and_an_equal_lateness_passes():
    """PRD §3.4: "The second is the slip lock: once any ticket in the store has
    completed late by some number of minutes, every later completion in that
    store must land within that same number of minutes of its own `promised_at`."

    The first ticket promises 06:17Z and completes at 06:22Z, so the store's
    slip basis becomes 5 minutes; the second ticket promises 06:18Z and completes
    at exactly 06:23Z, whose 5-minute lateness equals the basis and is admitted.

    Design: Difficulty/boundary_precision_check/queue_latency_boundaries_on_empty_and_exact_match
    """
    master = _setup_store_ready_to_ticket()
    first = _create_ticket(master, 5)
    second = _create_ticket(master, 6)

    validate_success(api_client.ticket_sub_ticket(first["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.ticket_sub_ticket(second["id"], clerk_headers(master.a1["id"])))

    set_clock("2026-09-02T06:22:00Z")
    late = validate_success(
        api_client.complete_sub_ticket(first["id"], 2.5, clerk_headers(master.a1["id"]))
    )
    assert late["lateness_minutes"] == 5, (
        "06:22Z against a 06:17Z promise is five whole minutes late"
    )

    set_clock("2026-09-02T06:23:00Z")
    equal = validate_success(
        api_client.complete_sub_ticket(second["id"], 3, clerk_headers(master.a1["id"]))
    )
    assert equal["status"] == "COMPLETED", (
        "a completion exactly at the basis of five minutes is within the lock"
    )
    assert equal["lateness_minutes"] == 5


def test_a_completion_one_minute_past_the_slip_basis_is_refused():
    """PRD §3.4: "Taken together, the two rules mean a store is allowed exactly
    one late completion, and the grace it grants is the grace it must then keep."

    Design: Difficulty/boundary_precision_check/queue_latency_boundaries_on_empty_and_exact_match
    """
    master = _setup_store_ready_to_ticket()
    first = _create_ticket(master, 5)
    second = _create_ticket(master, 6)

    validate_success(api_client.ticket_sub_ticket(first["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.ticket_sub_ticket(second["id"], clerk_headers(master.a1["id"])))

    set_clock("2026-09-02T06:22:00Z")
    validate_success(api_client.complete_sub_ticket(first["id"], 2.5, clerk_headers(master.a1["id"])))

    set_clock("2026-09-02T06:24:00Z")
    response = api_client.complete_sub_ticket(second["id"], 3, clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_SLIP_LOCK_VIOLATED)