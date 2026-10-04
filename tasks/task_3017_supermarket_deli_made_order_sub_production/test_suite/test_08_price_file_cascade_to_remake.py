"""Activating a successor price file voids labels and remakes their tickets."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_success,
)


def _setup_completed_ticket():
    """Store with one ACTIVE price file and one COMPLETED ticket carrying a label."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=2, clerk_allergy_set=("MILK", "WHEAT"))
    first_file = master.price_file
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])

    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="IN_STORE",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 4, "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    get_success_data(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))
    completed = get_success_data(
        api_client.complete_sub_ticket(ticket["id"], 2, clerk_headers(master.a1["id"]))
    )

    successor = setup_price_file(
        master.s, file_label="PF-0902",
        effective_from="2026-09-02T06:00:00Z", effective_to="2026-10-01T00:00:00Z",
        item_price_count=8, activate=False,
    )
    return master, first_file, successor, completed


def test_superseding_a_price_file_voids_the_label_and_remakes_the_ticket():
    """PRD §3.6: "Superseding cascades: the previously ACTIVE file moves to
    `SUPERSEDED`, every `ISSUED` label written against it moves to `VOIDED`,
    every sub ticket whose label was voided moves to `REMADE`."

    Design: Difficulty/transitive_cascade/price_file_activation_cascade_to_ticket_remake
    """
    master, first_file, successor, ticket = _setup_completed_ticket()
    label_id = ticket["label_id"]

    label_before = validate_success(api_client.get_label(label_id, platform_admin_headers()))
    assert label_before["status"] == "ISSUED"
    assert label_before["total_price_cents"] == 1798, "2.0 lbs at the item's 899 cents per pound"

    validate_success(api_client.activate_price_file(successor["id"], scale_operator_headers()))

    file_after = validate_success(api_client.get_price_file(first_file["id"], platform_admin_headers()))
    assert file_after["status"] == "SUPERSEDED"
    label_after = validate_success(api_client.get_label(label_id, platform_admin_headers()))
    assert label_after["status"] == "VOIDED"
    ticket_after = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert ticket_after["status"] == "REMADE", (
        "the third hop is caused by the second hop's label write, not by the activation directly"
    )


def test_remake_moves_through_the_forward_state_and_counts_exactly_once():
    """PRD §3.4: "When a label issued for a ticket is voided, the ticket's
    fulfillment dimension moves from `COMPLETED` to `REMADE`. This increments its
    `remake_count` by one."
    PRD §3.4: "The remake carries its original `ticket_number` forward, so the
    customer's number does not change."

    Design: Difficulty/transitive_cascade/price_file_activation_cascade_to_ticket_remake
    """
    master, _, successor, ticket = _setup_completed_ticket()
    original_number = ticket["ticket_number"]
    assert ticket["remake_count"] == 0

    validate_success(api_client.activate_price_file(successor["id"], scale_operator_headers()))

    ticket_after = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert ticket_after["status"] == "REMADE", (
        "the ticket takes the forward REMADE transition rather than reverting the label"
    )
    assert ticket_after["remake_count"] == 1
    assert ticket_after["ticket_number"] == original_number, (
        "the remake reuses the original ticket number"
    )