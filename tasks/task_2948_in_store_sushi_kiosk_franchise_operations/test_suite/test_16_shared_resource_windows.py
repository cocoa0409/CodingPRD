"""Resources shared across time or across siblings: hold stations, periods, one case."""

from test_helpers import (
    ApiErrorId,
    BATCH_APPROVED,
    BATCH_MIXING,
    BATCH_REJECTED,
    DISCARD_SHELF_LIFE_EXPIRED,
    PACK_DISCARDED,
    PACK_ON_SHELF,
    REJECTION_TTC_HARD_FAIL,
    SETTLEMENT_DRAFT,
    SETTLEMENT_VOID,
    acidification_reading_payload,
    add_draft_statement,
    add_kiosk,
    add_mixing_rice_batch,
    add_released_plan,
    assert_close,
    assert_instant_equals,
    base_world,
    discard_payload,
    fish_lot_payload,
    ids_of,
    pack_lot_payload,
    packed_world,
    production_plan_payload,
    rice_batch_payload,
    settlement_statement_payload,
    settlement_void_payload,
    validate_error,
    validate_list,
    validate_success,
)

SMALL_BATCH = {"rice_kg": 6.0, "vinegar_liters": 0.6}
MORNING_HOLD = {
    "hold_start_at": "2026-08-03T07:00:00Z",
    "hold_end_at": "2026-08-03T10:00:00Z",
}
LATE_PH_READING = {"ph_measured_at": "2026-08-03T10:00:00Z"}
FIRST_HALF_MONTH = {"period_start": "2026-08-01", "period_end": "2026-08-15"}
SECOND_HALF_MONTH = {"period_start": "2026-08-15", "period_end": "2026-08-31"}
SIBLING_KIOSK_CODE = "K-418-B"
SIBLING_CHEF_NAME = "Mika Sato"
SIBLING_TRAFFIC = 5612
SIBLING_BUILD = {"sku_code": "SPICY-6", "produced_at": "2026-08-03T09:00:00Z"}


def _sibling_kiosk_ready_to_build(api, world):
    """Second kiosk of the same host store, carrying its own rice and its own fish."""
    sibling = add_kiosk(world, SIBLING_KIOSK_CODE, SIBLING_CHEF_NAME)
    shell = validate_success(api.get_kiosk(sibling["kiosk_id"], world["ops_headers"]))
    plan = validate_success(
        api.create_production_plan(
            production_plan_payload(
                sibling["kiosk_id"], shell["version"], traffic_forecast=SIBLING_TRAFFIC
            ),
            sibling["chef_headers"],
        ),
        201,
    )
    validate_success(
        api.release_production_plan(plan["id"], sibling["chef_headers"])
    )
    batch = validate_success(
        api.create_rice_batch(
            rice_batch_payload(
                plan["id"], sibling["chef_id"], rice_kg=12.0, vinegar_liters=1.2
            ),
            sibling["chef_headers"],
        ),
        201,
    )
    validate_success(
        api.record_acidification_reading(
            batch["id"], acidification_reading_payload(), sibling["chef_headers"]
        )
    )
    approved = validate_success(api.verify_ttc(batch["id"], sibling["chef_headers"]))
    lot = validate_success(
        api.create_fish_lot(
            fish_lot_payload(sibling["kiosk_id"]), sibling["chef_headers"]
        ),
        201,
    )
    released = validate_success(
        api.release_fish_lot(lot["id"], world["auditor_headers"])
    )
    sibling.update({"plan": plan, "rice_batch": approved, "fish_lot": released})
    return sibling


def test_a_batch_beginning_the_instant_another_ends_shares_the_hold_station(api):
    """Touching windows are allowed at either end, while a genuine overlap is refused.

    "Hold windows are treated as half-open, running from `hold_start_at` up to but not
    including `hold_end_at`, and no two non-rejected batches of the same kiosk may
    overlap: a batch that begins at exactly the instant another ends is accepted,
    while any genuine overlap is refused with `ERR_ACIDIFICATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rice_hold_window_half_open_adjacency_allowed_on_kiosk
    """
    world = base_world()
    plan = add_released_plan(world)
    morning = add_mixing_rice_batch(world, plan["id"], **SMALL_BATCH, **MORNING_HOLD)
    assert morning["status"] == BATCH_MIXING
    assert morning["max_pack_yield"] == 50

    adjacent = add_mixing_rice_batch(
        world,
        plan["id"],
        **SMALL_BATCH,
        hold_start_at="2026-08-03T10:00:00Z",
        hold_end_at="2026-08-03T11:00:00Z",
    )
    assert adjacent["status"] == BATCH_MIXING
    assert_instant_equals(adjacent["hold_start_at"], morning["hold_end_at"])
    assert adjacent["max_pack_yield"] == 50

    validate_error(
        api.create_rice_batch(
            rice_batch_payload(
                plan["id"],
                world["chef_id"],
                **SMALL_BATCH,
                hold_start_at="2026-08-03T09:30:00Z",
                hold_end_at="2026-08-03T10:30:00Z",
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_ACIDIFICATION_WINDOW_OVERLAP.value,
        422,
    )

    earlier = add_mixing_rice_batch(
        world,
        plan["id"],
        **SMALL_BATCH,
        hold_start_at="2026-08-03T06:00:00Z",
        hold_end_at="2026-08-03T07:00:00Z",
    )
    assert earlier["status"] == BATCH_MIXING
    assert_instant_equals(earlier["hold_end_at"], morning["hold_start_at"])

    validate_list(
        api.list_rice_batches(world["ops_headers"], {"production_plan_id": plan["id"]}),
        expected_total=3,
    )


def test_a_rejected_batch_stops_holding_the_window_it_occupied(api):
    """Only non-rejected batches reserve the station, so a hard fail hands the slot back.

    "no two non-rejected batches of the same kiosk may overlap: a batch that begins at
    exactly the instant another ends is accepted, while any genuine overlap is refused
    with `ERR_ACIDIFICATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rice_hold_window_half_open_adjacency_allowed_on_kiosk
    """
    world = base_world()
    plan = add_released_plan(world)
    occupying = add_mixing_rice_batch(world, plan["id"], **SMALL_BATCH, **MORNING_HOLD)

    interior = {
        "hold_start_at": "2026-08-03T09:30:00Z",
        "hold_end_at": "2026-08-03T10:00:00Z",
    }
    validate_error(
        api.create_rice_batch(
            rice_batch_payload(plan["id"], world["chef_id"], **SMALL_BATCH, **interior),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_ACIDIFICATION_WINDOW_OVERLAP.value,
        422,
    )

    validate_success(
        api.record_acidification_reading(
            occupying["id"],
            acidification_reading_payload(measured_ph=4.85, **LATE_PH_READING),
            world["chef_headers"],
        )
    )
    hard_failed = validate_success(
        api.verify_ttc(occupying["id"], world["chef_headers"])
    )
    assert hard_failed["status"] == BATCH_REJECTED
    assert hard_failed["rejection_reason"] == REJECTION_TTC_HARD_FAIL

    reclaimed = add_mixing_rice_batch(
        world, plan["id"], **SMALL_BATCH, **interior
    )
    assert reclaimed["status"] == BATCH_MIXING
    assert reclaimed["max_pack_yield"] == 50
    assert_instant_equals(reclaimed["hold_start_at"], "2026-08-03T09:30:00Z")

    validate_list(
        api.list_rice_batches(world["ops_headers"], {"production_plan_id": plan["id"]}),
        expected_total=2,
    )


def test_two_settlement_periods_sharing_one_calendar_day_still_overlap(api):
    """A month split on the fifteenth double-counts that day, so the second draft fails.

    "Settlement periods are closed intervals on both ends, so two periods that merely
    share a single endpoint date do overlap, and a period overlapping any non-`VOID`
    statement of the same agreement is refused with `ERR_SETTLEMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/settlement_period_closed_interval_shared_endpoint_rejected
    """
    world = base_world()
    first_half = add_draft_statement(world, **FIRST_HALF_MONTH)
    assert first_half["status"] == SETTLEMENT_DRAFT
    assert first_half["period_end"] == "2026-08-15"

    observed = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    validate_error(
        api.create_settlement_statement(
            settlement_statement_payload(
                world["agreement_id"], observed["version"], **SECOND_HALF_MONTH
            ),
            world["ops_headers"],
        ),
        ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value,
        422,
    )

    listed = validate_list(
        api.list_settlement_statements(
            world["ops_headers"], {"license_agreement_id": world["agreement_id"]}
        ),
        expected_total=1,
    )
    assert ids_of(listed) == [first_half["id"]]
    untouched = validate_success(
        api.get_settlement_statement(first_half["id"], world["ops_headers"])
    )
    assert untouched["status"] == SETTLEMENT_DRAFT
    assert untouched["superseded_statement_id"] is None

    reobserved = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    second_half = validate_success(
        api.create_settlement_statement(
            settlement_statement_payload(
                world["agreement_id"],
                reobserved["version"],
                period_start="2026-08-16",
                period_end="2026-08-31",
            ),
            world["ops_headers"],
        ),
        201,
    )
    assert second_half["status"] == SETTLEMENT_DRAFT
    assert second_half["period_start"] == "2026-08-16"
    assert second_half["revision_round"] == 1
    assert second_half["superseded_statement_id"] is None


def test_voiding_the_earlier_statement_frees_the_shared_endpoint(api):
    """Once the first half-month is void it no longer reserves the fifteenth.

    "a period overlapping any non-`VOID` statement of the same agreement is refused
    with `ERR_SETTLEMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/settlement_period_closed_interval_shared_endpoint_rejected
    """
    world = base_world()
    first_half = add_draft_statement(world, **FIRST_HALF_MONTH)

    observed = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    validate_error(
        api.create_settlement_statement(
            settlement_statement_payload(
                world["agreement_id"], observed["version"], **SECOND_HALF_MONTH
            ),
            world["ops_headers"],
        ),
        ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value,
        422,
    )

    scrapped = validate_success(
        api.void_settlement_statement(
            first_half["id"], settlement_void_payload(), world["ops_headers"]
        )
    )
    assert scrapped["status"] == SETTLEMENT_VOID
    assert scrapped["void_reason"] is not None

    reobserved = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    allowed = validate_success(
        api.create_settlement_statement(
            settlement_statement_payload(
                world["agreement_id"], reobserved["version"], **SECOND_HALF_MONTH
            ),
            world["ops_headers"],
        ),
        201,
    )
    assert allowed["status"] == SETTLEMENT_DRAFT
    assert allowed["period_start"] == "2026-08-15"
    assert allowed["period_end"] == "2026-08-31"
    assert allowed["superseded_statement_id"] is None

    validate_list(
        api.list_settlement_statements(
            world["ops_headers"], {"license_agreement_id": world["agreement_id"]}
        ),
        expected_total=2,
    )


def test_a_second_kiosk_inside_its_own_cap_still_overfills_the_shared_case(api):
    """Two kiosks of one store contend for one hundred and eighty packs of frontage.

    "The aggregate live pack count across every kiosk of the host store must not exceed
    the refrigerated case capacity implied by the attested frontage, which is
    `attested_case_linear_ft` multiplied by the same nine packs per linear foot and
    rounded down to a whole pack; exceeding it is `ERR_CASE_CAPACITY_EXCEEDED`. This is
    the store-wide sibling of the kiosk-level cap, and a single kiosk inside its own cap
    can still breach it."

    Design: Difficulty/resource_temporal_overlap/host_store_case_capacity_aggregate_overlap_rejected
    """
    world = packed_world(pack_overrides={"pack_count": 100})
    holding = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert holding["status"] == PACK_ON_SHELF
    assert holding["unsold_count"] == 100

    sibling = _sibling_kiosk_ready_to_build(api, world)
    assert sibling["kiosk"]["daily_pack_cap"] == 180
    assert sibling["plan"]["planned_pack_count"] == 101
    assert sibling["rice_batch"]["status"] == BATCH_APPROVED
    assert sibling["rice_batch"]["max_pack_yield"] == 100

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(
                sibling["rice_batch"]["id"],
                sibling["fish_lot"]["id"],
                pack_count=100,
                **SIBLING_BUILD,
            ),
            sibling["chef_headers"],
        ),
        ApiErrorId.ERR_CASE_CAPACITY_EXCEEDED.value,
        422,
    )
    validate_list(
        api.list_pack_lots(
            world["ops_headers"], {"rice_batch_id": sibling["rice_batch"]["id"]}
        ),
        expected_total=0,
    )
    unspent = validate_success(
        api.get_rice_batch(sibling["rice_batch"]["id"], world["ops_headers"])
    )
    assert unspent["status"] == BATCH_APPROVED
    unallocated = validate_success(
        api.get_fish_lot(sibling["fish_lot"]["id"], world["ops_headers"])
    )
    assert_close(unallocated["allocated_kg"], 0.000, places=3)
    assert_close(unallocated["remaining_kg"], 12.000, places=3)
    undisturbed = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert undisturbed["unsold_count"] == 100

    fitted = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                sibling["rice_batch"]["id"],
                sibling["fish_lot"]["id"],
                pack_count=80,
                **SIBLING_BUILD,
            ),
            sibling["chef_headers"],
        ),
        201,
    )
    assert fitted["status"] == PACK_ON_SHELF
    assert fitted["unsold_count"] == 80
    assert_close(fitted["consumed_fish_kg"], 3.600, places=3)


def test_discarding_the_first_kiosks_packs_empties_the_shared_case(api):
    """Clearing one kiosk's shelf is what lets its sibling build the very same body.

    "The lot moves to `DISCARDED` with `discarded_count` set and `unsold_count` driven
    to zero, the owning plan recomputes `actual_pack_count`"

    Design: Difficulty/resource_temporal_overlap/host_store_case_capacity_aggregate_overlap_rejected
    """
    world = packed_world(pack_overrides={"pack_count": 100})
    sibling = _sibling_kiosk_ready_to_build(api, world)
    build = pack_lot_payload(
        sibling["rice_batch"]["id"],
        sibling["fish_lot"]["id"],
        pack_count=100,
        **SIBLING_BUILD,
    )

    validate_error(
        api.create_pack_lot(build, sibling["chef_headers"]),
        ApiErrorId.ERR_CASE_CAPACITY_EXCEEDED.value,
        422,
    )

    cleared = validate_success(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["chef_headers"],
        )
    )
    assert cleared["status"] == PACK_DISCARDED
    assert cleared["discarded_count"] == 100
    assert cleared["unsold_count"] == 0

    built = validate_success(api.create_pack_lot(build, sibling["chef_headers"]), 201)
    assert built["status"] == PACK_ON_SHELF
    assert built["unsold_count"] == 100
    assert_close(built["consumed_fish_kg"], 4.500, places=3)
    assert_instant_equals(built["shelf_expiry_at"], "2026-08-03T21:00:00Z")

    filled = validate_success(
        api.get_production_plan(sibling["plan"]["id"], world["ops_headers"])
    )
    assert filled["actual_pack_count"] == 100
    emptied = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert emptied["actual_pack_count"] == 0
