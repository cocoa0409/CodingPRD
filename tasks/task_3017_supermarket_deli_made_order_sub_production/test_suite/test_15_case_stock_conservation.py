"""Case weight is a conserved quantity across production, discard and rework."""

from test_helpers import (
    api_client,
    clerk_headers,
    close_markdown_window,
    create_waste_record,
    get_success_data,
    open_markdown_window,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    start_batch,
    store_version,
    validate_success,
)


def _waste_record_for(master, batch_id):
    """The store's waste record drawn from `batch_id` (mark-down synthesizes it)."""
    listing = get_success_data(
        api_client.list_waste_records(
            platform_admin_headers(), {"store_id": master.s, "production_batch_id": batch_id}
        )
    )
    return listing[0]


def _setup_case_stock_scenario():
    """3.0 lbs of HOLDING stock and a second 6.0 lb batch still PLANNED."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    produce_batch(master.s, master.j1["id"], master.a1["id"], "B-A1", 3, produced_lbs=3)
    pending = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j1["id"], "produced_by_associate_id": master.a1["id"],
             "batch_code": "B-A2", "planned_lbs": 6},
            clerk_headers(master.a1["id"]),
        )
    )
    return master, pending


def test_case_weight_reads_only_the_holding_and_marked_down_batches():
    """PRD §2.4: "Derived fields are mutated fields. Recomputing `case_on_hand_lbs`,
    `posture`, `posture_reason`, `active_price_file_id`, `targeted_promo_id`,
    `covered_allergen_set`, `available_bread_units`,
    `certified_slicer_operator_count`, `verified_waste_liability_cents` or
    `pending_waste_verification_count` on a `Store` is a mutation of that store."

    Design: Difficulty/compensating_invariant/case_stock_conservation_under_production_and_rework
    """
    master, _ = _setup_case_stock_scenario()
    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["case_on_hand_lbs"] == 3.0, (
        "only the completed batch contributes; the PLANNED one has produced nothing"
    )


def test_case_weight_rises_with_the_second_production():
    """PRD §3.1: "The batch's produced weight in pounds multiplied by the item's
    `unit_cost_cents` gives the raw product cost."
    PRD §2.4: "The `version` field is an integer that begins at 1 on creation and
    is incremented by exactly one on each mutation."

    Design: Difficulty/compensating_invariant/case_stock_conservation_under_production_and_rework
    """
    master, pending = _setup_case_stock_scenario()
    before = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    start_batch(pending["id"], master.a1["id"], before["version"])
    validate_success(api_client.complete_batch(pending["id"], 6, clerk_headers(master.a1["id"])))

    after = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert after["case_on_hand_lbs"] == 9.0, (
        "the conserved quantity equals the sum over HOLDING and MARKED_DOWN batches"
    )
    assert after["version"] >= before["version"]


def test_discarding_the_batch_drives_the_conserved_weight_back_down():
    """PRD §3.3: "All of this is recomputed whenever a discard happens, and the
    parent batch's `hold_status` moves to `DISCARDED` as a direct consequence."

    Design: Difficulty/compensating_invariant/case_stock_conservation_under_production_and_rework
    """
    master, pending = _setup_case_stock_scenario()
    start_batch(pending["id"], master.a1["id"], store_version(master.s))
    completed = validate_success(
        api_client.complete_batch(pending["id"], 6, clerk_headers(master.a1["id"]))
    )
    # PRD §3.3: with the markdown window closed, the DRAFT record discards
    # directly and the batch follows it to DISCARDED.
    close_markdown_window(completed, master.j1)
    record = create_waste_record(
        master.s, pending["id"], master.a1["id"], reason="QUALITY",
        acting_associate_id=master.a1["id"],
    )
    validate_success(api_client.discard_waste_record(record["id"], 6, clerk_headers(master.a1["id"])))

    after = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert after["case_on_hand_lbs"] == 3.0, (
        "the discard leg drove the conserved quantity back to its pre-production value"
    )
    discarded = validate_success(api_client.get_batch(pending["id"], platform_admin_headers()))
    assert discarded["hold_status"] == "DISCARDED"


def test_rework_pushes_the_conserved_weight_back_up_without_reversing_the_predecessor():
    """PRD §3.1: "It creates a successor `ProductionBatch` whose
    `rework_of_batch_id` names the discarded predecessor, whose
    `production_status` starts at `PLANNED`, and whose `hold_status` starts at
    `HOLDING`. The discarded row keeps its `DISCARDED` status forever, which
    means the rework loop is an induced cycle running from a batch through its
    waste record and back to a new batch, never a state reversal."

    Design: Difficulty/compensating_invariant/case_stock_conservation_under_production_and_rework
    """
    master, pending = _setup_case_stock_scenario()
    start_batch(pending["id"], master.a1["id"], store_version(master.s))
    completed = validate_success(
        api_client.complete_batch(pending["id"], 6, clerk_headers(master.a1["id"]))
    )
    # PRD 3.3: with the markdown window closed, the DRAFT record discards
    # directly and the batch follows it to DISCARDED.
    close_markdown_window(completed, master.j1)
    record = create_waste_record(
        master.s, pending["id"], master.a1["id"], reason="QUALITY",
        acting_associate_id=master.a1["id"],
    )
    validate_success(api_client.discard_waste_record(record["id"], 6, clerk_headers(master.a1["id"])))

    successor = validate_success(
        api_client.rework_batch(
            pending["id"],
            {"planned_lbs": 6, "produced_by_associate_id": master.a1["id"], "batch_code": "B-A2R"},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert successor["production_status"] == "PLANNED"
    assert successor["rework_of_batch_id"] == pending["id"]

    start_batch(successor["id"], master.a1["id"], store_version(master.s))
    validate_success(api_client.complete_batch(successor["id"], 6, clerk_headers(master.a1["id"])))

    after = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert after["case_on_hand_lbs"] == 9.0, "the successor's weight re-enters the conserved sum"

    predecessor = validate_success(api_client.get_batch(pending["id"], platform_admin_headers()))
    assert predecessor["hold_status"] == "DISCARDED", (
        "the discarded row is never reversed by the rework"
    )