"""Corner-design translations: volume doctrines, eligibility ranking, and
blend arithmetic.

The ledger replays recorded events with an authoritative reset semantics
(PRD §3.3) and rounds after every event (PRD §2.6); the statutory projection
applies the current slot's heat at the evaluation instant to every block
(PRD §3.3); the eligibility selector ranks deterministically and treats an
empty pool as a 200 (PRD §3.6); blend validation enforces the age statement
inclusively at the bottling date (PRD §3.5); and commit/abort move exact
volumes in and out of component ledgers (PRD §3.5).
"""
from test_helpers import (
    ApiErrorId,
    add_component,
    create_active_label,
    create_blend_batch,
    create_commissioned_rickhouse,
    create_committed_batch,
    create_program,
    create_validated_batch,
    fill_mature_barrel,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    record_evaporation_reading,
    record_quality_sample,
    rotate_barrel,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ledger_reading_is_authoritative_reset(api, warehouse_manager_headers):
    """PRD §3.3: "an `EVAPORATION_READING` assessment resets the running volume
    outright to its `measured_volume_liters` — an authoritative measurement of
    what is actually in the barrel, not a delta; a `QUALITY_SAMPLE` subtracts
    its `sample_draw_liters`".
    PRD §3.3: "Events are ordered by their event instant, ties broken by
    earliest `created_at`."
    PRD §2.6: "As the ledger replays each recorded event (§3.3), the running
    volume is floored at zero and rounded to two decimal places, round half
    up, after every single event — never once at the end."

    Design: Corner/calculations/ledger_reading_is_authoritative_reset
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-C1",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # 200.0 L at 2028-09-01

    # Same-instant pair, created reading-first: the reading resets the running
    # volume to 190.00, then the sample subtracts 2.00.
    set_clock("2029-03-01T00:00:00Z")
    record_evaporation_reading(barrel["id"], 190.0)
    record_quality_sample(barrel["id"], sample_draw_liters=2.0, quality_score=85)

    mid = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    assert mid["current_volume_ledger_liters"] == 188.00, (
        "reading resets to 190.00, then the 2.00 sample subtracts"
    )

    # A later reading discards the 188.00 intermediate outright.
    set_clock("2029-04-01T00:00:00Z")
    record_evaporation_reading(barrel["id"], 185.5)

    final = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    assert final["current_volume_ledger_liters"] == 185.50, (
        "the later reading is an authoritative reset, not a delta from 188.00"
    )


def test_statutory_recomputed_with_current_slot_heat(api, warehouse_manager_headers):
    """PRD §3.3: "The heat of the barrel's location at the evaluation instant —
    the `heat_factor` of the slot holding its `OPEN` occupancy, or of the slot
    from its most recently `CLOSED` occupancy when none is open — scales the
    rate for rickhouse microclimate."
    PRD §3.3: "It is recomputed on every read of the barrel at the current
    logical clock".
    PRD §3.2: "Rotating a barrel moves it to a different slot."

    Design: Corner/calculations/statutory_recomputed_with_current_slot_heat
    """
    ctx = create_commissioned_rickhouse(
        floors=2, rows_per_floor=1, positions_per_row=1, name="RH-C2",
    )
    # Deterministic floor-row-position order: slots[0] is floor_index 1
    # (heat 1.00, PRD §3.1), slots[1] is floor_index 2 (heat 1.05).
    slot_floor1 = ctx["slots"][0]
    slot_floor2 = ctx["slots"][1]
    barrel = fill_placed_barrel(slot_floor1["id"])  # seasoning 12, 200.0 L at 2028-09-01

    set_clock("2029-09-01T00:00:00Z")
    before = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    # Four fully elapsed 90-day blocks at heat 1.00, rates 0.012, 0.012,
    # 0.0084 (WINTER), 0.012 (base 0.01 x season x age 1.2; seasoning 12 earns
    # no discount): 200 x 0.988^3 x 0.9916 = 191.2658..., rounded once at the
    # end.
    assert before["current_volume_statutory_liters"] == 191.27
    assert before["current_volume_ledger_liters"] == 200.00

    rotate_barrel(barrel["id"], slot_floor2["id"])

    after = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    # Same clock, no new events: the evaluation-instant heat (1.05) now scales
    # every historical block — rates 0.0126, 0.0126, 0.00882, 0.0126 give
    # 200 x 0.9874^3 x 0.99118 = 190.8366... .
    assert after["current_volume_statutory_liters"] == 190.84
    assert after["current_volume_ledger_liters"] == 200.00, (
        "rotation records no volume event, so the ledger never moves"
    )


def test_eligible_barrels_ranked_score_desc_fill_asc(api, program_director_headers):
    """PRD §3.6: "The latest quality score is the `quality_score` of the
    barrel's most recent `QUALITY_SAMPLE` — greatest `assessed_at`, ties
    broken by earliest `created_at` — and a barrel with no quality sample
    scores zero."
    PRD §3.6: "Candidates rank by latest quality score descending, then
    `fill_date` ascending, then `created_at` ascending."

    Design: Corner/calculations/eligible_barrels_ranked_score_desc_fill_asc
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=3, name="RH-C3",
    )
    s1, s2, s3 = (slot["id"] for slot in ctx["slots"])
    barrel_1 = fill_mature_barrel(s1)  # fill_date 2028-09-01, score 90 below
    barrel_2 = fill_mature_barrel(s2)  # fill_date 2028-09-01, score 95 below
    set_clock("2028-09-02T00:00:00Z")
    barrel_3 = fill_mature_barrel(s3)  # fill_date 2028-09-02, score 95 below

    set_clock("2028-09-03T00:00:00Z")
    record_quality_sample(barrel_1["id"], sample_draw_liters=1.0, quality_score=90)
    record_quality_sample(barrel_2["id"], sample_draw_liters=1.0, quality_score=95)
    record_quality_sample(barrel_3["id"], sample_draw_liters=1.0, quality_score=95)

    set_clock("2028-09-04T00:00:00Z")
    program = create_program(
        name="Ranked Pick", min_quality_score=85,
        required_barrel_count=3, reservation_window_days=45,
    )

    data, meta = validate_paginated(
        api.list_eligible_barrels(program["id"], program_director_headers)
    )
    assert meta["total_count"] == 3
    assert [d["id"] for d in data] == [barrel_2["id"], barrel_3["id"], barrel_1["id"]], (
        "score 95 pair first, fill_date ascending breaks the tie "
        "(2028-09-01 before 2028-09-02), then score 90"
    )


def test_eligible_barrels_empty_pool_returns_empty_array(api, program_director_headers):
    """PRD §3.6: "The selector read returns this ranking; an empty candidate
    pool is not an error and answers 200 with an empty array."
    PRD §3.6: "a barrel with no quality sample scores zero."

    Design: Corner/calculations/eligible_barrels_empty_pool_returns_empty_array
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-C4",
    )
    fill_mature_barrel(ctx["slots"][0]["id"])  # never sampled -> latest score 0
    program = create_program(
        name="Picky Pick", min_quality_score=100,
        required_barrel_count=1, reservation_window_days=45,
    )

    data, meta = validate_paginated(
        api.list_eligible_barrels(program["id"], program_director_headers)
    )
    assert data == [], "min_quality_score 100 excludes the score-0 barrel"
    assert meta["total_count"] == 0, "an empty pool is a 200, not an error"


def test_age_one_day_short_of_statement_fails(api, master_blender_headers):
    """PRD §3.5: "Then every component is examined: the barrel's age at the
    `scheduled_bottling_date` — the days between `fill_date` and that date,
    divided by 365, rounded down to whole years — must be at least the label's
    `age_statement_years`; a component whose age is exactly the statement
    satisfies the obligation, and any younger component fails validation with
    `ERR_AGE_STATEMENT_VIOLATION` (HTTP 422)."

    Design: Corner/calculations/age_one_day_short_of_statement_fails
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-C5",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # fill_date 2028-09-01
    label = create_active_label(name="Four Year Short", age_statement_years=4, spirit_type="BOURBON")

    set_clock("2032-08-15T00:00:00Z")
    batch = create_blend_batch(label["id"], "2032-08-30T00:00:00Z")
    add_component(batch["id"], barrel["id"], 10.0)

    # 2028-09-01 -> 2032-08-30 spans 1459 days: floor(1459/365) == 3, one day
    # short of the 4 x 365 = 1460 days the statement demands.
    validate_error(
        api.validate_blend_batch(batch["id"], master_blender_headers),
        ApiErrorId.ERR_AGE_STATEMENT_VIOLATION,
    )

    after = get_blend_batch_fresh(batch["id"])
    assert after["state"] == "PROPOSED", "a failed validation leaves the batch PROPOSED"


def test_commit_draw_equal_to_ledger_succeeds(api, master_blender_headers):
    """PRD §3.5: "the draw may not exceed the barrel's current ledger volume,
    else `ERR_INSUFFICIENT_VOLUME` (HTTP 422); the volume check is made when
    the component is added and made again at commit."
    PRD §3.5: "The batch freezes `final_blend_volume_liters` as the sum of its
    components' drawn volumes, stamps `committed_at`, moves to `COMMITTED`,
    and increments its own `version`."
    PRD §3.3: "the commit of a blend batch containing the barrel subtracts
    that component's `drawn_volume_liters` at the batch's `committed_at`
    instant".

    Design: Corner/calculations/commit_draw_equal_to_ledger_succeeds
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-C6",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])  # 200.0 L ledger
    label = create_active_label(name="Full Draw", age_statement_years=1, spirit_type="BOURBON")
    batch = create_validated_batch(label["id"], barrel["id"], 200.0)

    committed = validate_success(api.commit_blend_batch(batch["id"], master_blender_headers))
    assert committed["state"] == "COMMITTED"
    assert committed["final_blend_volume_liters"] == 200.00

    barrel_after = get_barrel_fresh(barrel["id"])
    # Equality is permitted ("may not exceed", not "must be less"): the draw
    # 200.00 - 200.00 drives the ledger exactly to its zero floor.
    assert barrel_after["current_volume_ledger_liters"] == 0.00


def test_abort_committed_batch_restores_component_volumes(api, master_blender_headers):
    """PRD §3.5: "From `COMMITTED`, aborting performs full compensation: every
    component's `drawn_volume_liters` is added back to its barrel's ledger —
    an abort-restore ledger event at the abort instant — and each barrel's
    `version` increments, with the compensating invariant that each barrel's
    ledger volume returns exactly to its pre-commit value; the batch moves to
    `ABORTED` and increments its `version`."

    Design: Corner/calculations/abort_committed_batch_restores_component_volumes
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-C7",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])  # 200.0 L ledger
    label = create_active_label(name="Abort Restore", age_statement_years=1, spirit_type="BOURBON")
    batch = create_committed_batch(label["id"], barrel["id"], 120.0)
    assert batch["state"] == "COMMITTED"
    assert get_barrel_fresh(barrel["id"])["current_volume_ledger_liters"] == 80.00, (
        "commit drew 120.00 out of 200.00"
    )

    aborted = validate_success(api.abort_blend_batch(batch["id"], master_blender_headers))
    assert aborted["state"] == "ABORTED"
    assert aborted["final_blend_volume_liters"] == 120.00, (
        "frozen at commit and retained as history"
    )

    barrel_after = get_barrel_fresh(barrel["id"])
    assert barrel_after["current_volume_ledger_liters"] == 200.00, (
        "the abort-restore event returns the ledger exactly to its pre-commit value"
    )
