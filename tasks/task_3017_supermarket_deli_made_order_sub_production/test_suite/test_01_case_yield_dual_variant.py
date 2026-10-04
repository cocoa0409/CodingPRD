"""Case-yield cost: the provisional and final variants of one batch's cost."""

from test_helpers import (
    api_client,
    clerk_headers,
    close_markdown_window,
    create_waste_record,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    setup_deli_master_data,
    start_batch,
    store_version,
    validate_success,
)


def _setup_16lb_cold_cut_batch():
    """Store + one 16.0 lb cold-cut batch produced on a slicer whose cut counter
    lands at 5."""
    master = setup_deli_master_data(slicer_count=1)
    slicer = master.slicers[0]
    batch = get_success_data(
        api_client.create_batch(
            {
                "store_id": master.s,
                "deli_item_id": master.j2["id"],
                "slicer_id": slicer["id"],
                "produced_by_associate_id": master.a1["id"],
                "batch_code": "B-001",
                "planned_lbs": 16,
            },
            clerk_headers(master.a1["id"]),
        )
    )
    start_batch(batch["id"], master.a1["id"], store_version(master.s))
    completed = get_success_data(
        api_client.complete_batch(batch["id"], 16, clerk_headers(master.a1["id"]))
    )
    return master, slicer, completed


def test_batch_completion_writes_provisional_and_final_cost_on_one_row():
    """PRD §3.3: "The provisional figure, `case_yield_cost_provisional_cents`, is
    the subtotal reduced by a waste-recovery credit: 0.70 multiplied by the
    batch's `discard_lbs` multiplied by the item's `unit_cost_cents`, subtracted
    from the subtotal, with the whole result rounded half up to two decimal
    places."
    PRD §3.3: "The final figure, `case_yield_cost_final_cents`, is reported once
    at least one waste record for the batch has reached `VERIFIED`, and it adds
    two further terms to the same base."

    Completion writes both dual-variant outputs of the same batch on one row.

    Design: Difficulty/dual_variant_calc/case_yield_cost_dual_variant_on_batch
    """
    batch = _setup_16lb_cold_cut_batch()[2]
    result = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert result["case_yield_cost_provisional_cents"] == 8365, (
        "completion must write the provisional variant of the case-yield cost"
    )
    assert result["case_yield_cost_final_cents"] == 8365, (
        "both variant outputs are written on the same row at completion"
    )


def test_verification_moves_batch_to_final_cost_and_leaves_provisional_untouched():
    """PRD §3.3: "The first addition is the sum of `handling_fee_cents` over every
    waste record for this batch that has reached `VERIFIED`, rounded half up to
    two decimal places."
    PRD §3.3: "Records that have been `DISCARDED` but not yet verified contribute
    nothing to the final variant, which is why verification is the moment the
    final cost settles."

    Design: Difficulty/dual_variant_calc/case_yield_cost_dual_variant_on_batch
    """
    master, _, batch = _setup_16lb_cold_cut_batch()

    record = create_waste_record(
        master.s,
        batch["id"],
        master.a2["id"],
        reason="QUALITY",
        acting_associate_id=master.a1["id"],
    )
    # PRD 3.3 allows the direct discard from DRAFT only after the half-open
    # markdown window has closed at the logical clock.
    close_markdown_window(batch, master.j2)
    get_success_data(
        api_client.discard_waste_record(record["id"], 14, clerk_headers(master.a1["id"]))
    )
    before_verify = get_success_data(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert before_verify["case_yield_cost_final_cents"] == 8365, (
        "a DISCARDED-but-unverified record contributes nothing to the final variant"
    )

    verified = get_success_data(
        api_client.verify_waste_record(
            record["id"],
            master.a3["id"],
            master.c_a3_fh["id"],
            before_verify["version"],
            manager_headers(master.a2["id"]),
        )
    )
    assert verified["discard_value_cents"] == 7280
    assert verified["handling_fee_cents"] == 250, (
        "the blended tier base of 5096 falls in the 250-cent band"
    )
    assert verified["total_liability_cents"] == 7530

    after_verify = get_success_data(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert after_verify["case_yield_cost_provisional_cents"] == 8365, (
        "verification does not rewrite the provisional variant"
    )
    assert after_verify["case_yield_cost_final_cents"] == 8615, (
        "verification adds the verified record's handling fee to the final variant"
    )
    assert (
        after_verify["case_yield_cost_final_cents"]
        - after_verify["case_yield_cost_provisional_cents"]
        == 250
    ), "the two variants must differ by exactly the verified record's handling fee"