"""A batch start's validity is decided by the store's derived posture."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    get_success_data,
    platform_admin_headers,
    set_clock,
    produce_case_stock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def _setup_restricted_store_with_a_startable_batch():
    """The store's case weight is pushed over capacity, so posture reads
    RESTRICTED/INVENTORY_TRIGGERED, and a fresh batch is left typed and ready."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                    slicer_count=2)
    # The startable batch is typed while the store is still OPEN, because a
    # RESTRICTED store refuses new batch creation (PRD §2.6).
    over_capacity = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": master.slicers[0]["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-101", "planned_lbs": 50},
            clerk_headers(master.a1["id"]),
        )
    )
    # Then the case weight is pushed past capacity, which is what makes the
    # posture RESTRICTED/INVENTORY_TRIGGERED.
    produce_case_stock(
        master, master.j1, [master.store["deli_case_capacity_lbs"] + 1.0],
        code_prefix="B-OV",
    )
    return master, over_capacity


def test_restricted_posture_rejects_an_otherwise_startable_batch():
    """PRD §3.1: "Planning a batch is gated by the store. A store in `RESTRICTED`
    refuses the creation with `ERR_POSTURE_RESTRICTED`."
    PRD §2.6: "A store in `RESTRICTED` blocks new production batches — creation is
    rejected with `ERR_POSTURE_RESTRICTED` and starting a batch is likewise
    refused."

    Design: Difficulty/cross_entity_state_dependency/batch_start_requires_store_posture_open
    """
    master, batch = _setup_restricted_store_with_a_startable_batch()
    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["posture"] == "RESTRICTED"
    assert store["posture_reason"] == "INVENTORY_TRIGGERED"

    response = api_client.start_batch(batch["id"], store["version"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_POSTURE_RESTRICTED)


def test_restricted_posture_blocks_new_batch_creation_but_not_ticket_creation():
    """PRD §2.6: "A store in `RESTRICTED` blocks new production batches — creation
    is rejected with `ERR_POSTURE_RESTRICTED` and starting a batch is likewise
    refused — but it deliberately does not block sub-ticket creation, so the
    counter can keep taking orders while the case is over capacity."

    Design: Difficulty/cross_entity_state_dependency/batch_start_requires_store_posture_open
    """
    master, _ = _setup_restricted_store_with_a_startable_batch()

    create_response = api_client.create_batch(
        {"store_id": master.s, "deli_item_id": master.j1["id"], "produced_by_associate_id": master.a1["id"],
         "batch_code": "B-NEWPOSTURE", "planned_lbs": 3},
        clerk_headers(master.a1["id"]),
    )
    validate_error(create_response, ApiErrorId.ERR_POSTURE_RESTRICTED)

    ticket = validate_success(
        api_client.create_sub_ticket(
            {"store_id": master.s, "deli_item_id": master.j1["id"], "bread_deli_item_id": master.b1["id"],
             "order_channel": "DIGITAL",
             "lines": [{"deli_item_id": master.j2["id"], "half_lb_units": 2,
                        "line_sequence_number": 1}]},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert ticket["status"] == "QUEUED", (
        "sub-ticket creation is deliberately not blocked by RESTRICTED posture"
    )