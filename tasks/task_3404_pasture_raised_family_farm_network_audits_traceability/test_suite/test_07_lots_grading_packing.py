"""Egg lot grading fork, quality holds, packing, and carton traceability."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_carton,
    assert_lot_conservation,
    create_active_farm,
    create_retailer,
    get_lot,
    grade_lot,
    make_retailer_buyer_headers,
    pack_cartons,
    resolve_hold,
    set_clock,
    setup_collected_lot,
    setup_graded_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import GRADE_AA_MIN, GRADE_B_MIN

PO = TEST_USERS["plant_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


def _two_held_lots(farm_id):
    """Two 120-dozen lots, both auto-held (scores 65 and 68, below 70)."""
    lot1 = setup_collected_lot(
        farm_id, route_date="2026-09-08", collected_cases=4,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=10,
    )["lot"]
    held1 = grade_lot(lot1["id"], 65)
    lot2 = setup_collected_lot(
        farm_id, route_date="2026-09-09", collected_cases=4,
        collect_at="2026-09-09T10:00:00Z", laid_start_date="2026-09-07",
        laid_end_date="2026-09-08", capacity_cases=10,
    )["lot"]
    held2 = grade_lot(lot2["id"], 68)
    return held1, held2


def test_hold_release_branch_is_packable_as_grade_b(api):
    """PRD §3.6: "The `disposition` of `RELEASE` salvages the lot: it moves
    `ON_HOLD → RELEASED` and its `grade` is set to `B` regardless of the
    original score, making it packable."
    PRD §3.6: "A score below 70.0 fails the packing standard: the lot's `grade`
    stays `NONE` and it falls `RECEIVED → ON_HOLD` instead."

    Design: Difficulty/non_linear_state_machine/egg_lot_branching_hold_release_vs_reject
    """
    farm = create_active_farm(name="Red Barn Pastures")["farm"]
    held1, held2 = _two_held_lots(farm["id"])
    assert held1["status"] == "ON_HOLD" and held1["grade"] == "NONE"
    assert held2["status"] == "ON_HOLD", "both lots enter ON_HOLD from RECEIVED (fork entry)"

    released = resolve_hold(held1["id"], "RELEASE")
    assert released["status"] == "RELEASED"
    assert released["grade"] == "B", "a hold release salvages the lot as grade B"

    pack_cartons(held1["id"], 10, "MEDIUM")
    lot = get_lot(held1["id"])
    assert lot["status"] == "RELEASED"
    assert lot["remaining_dozens"] == 110, f"120 - 10 packed, got {lot['remaining_dozens']}"
    assert lot["packed_dozens"] == 10
    assert_lot_conservation(lot)


def test_hold_reject_branch_destroys_and_pack_is_rejected(api):
    """PRD §3.6: "The `disposition` of `REJECT` destroys the lot: it moves
    `ON_HOLD → REJECTED`, its `destroyed_dozens` becomes everything that
    remained, and `remaining_dozens` drops to zero, preserving the conservation
    invariant of §2.9."
    PRD §3.6: "A `PlantOperator` packs from a lot in `GRADED` or `RELEASED`
    status — packing from any other state, including a `REJECTED` lot, is
    `ERR_INVALID_STATE`"

    Design: Difficulty/non_linear_state_machine/egg_lot_branching_hold_release_vs_reject
    """
    farm = create_active_farm(name="Red Barn Pastures")["farm"]
    held1, held2 = _two_held_lots(farm["id"])
    assert held1["status"] == "ON_HOLD" and held2["status"] == "ON_HOLD"

    rejected = resolve_hold(held2["id"], "REJECT")
    assert rejected["status"] == "REJECTED"
    assert rejected["destroyed_dozens"] == 120
    assert rejected["remaining_dozens"] == 0
    assert_lot_conservation(rejected)

    resp = api.pack_cartons(held2["id"], {"carton_count": 1, "pack_size": "MEDIUM"}, PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_lot_conservation_across_packs_to_packed_terminal(api):
    """PRD §2.9: "`received_dozens` always equals `remaining_dozens` plus
    `packed_dozens` plus `destroyed_dozens`"
    PRD §3.6: "when `remaining_dozens` reaches exactly zero the lot
    automatically transitions to the terminal `PACKED` state"

    Design: Difficulty/compensating_invariant/lot_dozen_conservation_pack_and_destroy
    """
    farm = create_active_farm(name="Ledger Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=4,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=10,
    )["lot"]
    assert lot["received_dozens"] == 120

    pack_cartons(lot["id"], 40, "LARGE")
    after_first = get_lot(lot["id"])
    assert after_first["remaining_dozens"] == 80
    assert after_first["packed_dozens"] == 40
    assert_lot_conservation(after_first)

    pack_cartons(lot["id"], 80, "LARGE")
    after_second = get_lot(lot["id"])
    assert after_second["status"] == "PACKED", "remaining hits exactly zero -> PACKED"
    assert after_second["remaining_dozens"] == 0
    assert after_second["packed_dozens"] == 120
    assert after_second["destroyed_dozens"] == 0
    assert_lot_conservation(after_second)


def test_lot_conservation_destroy_is_compensating_action(api):
    """PRD §2.9: "rejecting a held lot moves everything left into
    `destroyed_dozens`"
    PRD §2.9: "`received_dozens` always equals `remaining_dozens` plus
    `packed_dozens` plus `destroyed_dozens`"

    Design: Difficulty/compensating_invariant/lot_dozen_conservation_pack_and_destroy
    """
    farm = create_active_farm(name="Ledger Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 60, route_date="2026-09-09", collected_cases=2,
        collect_at="2026-09-09T10:00:00Z", laid_start_date="2026-09-07",
        laid_end_date="2026-09-08", capacity_cases=10,
    )["lot"]
    assert lot["received_dozens"] == 60
    assert lot["status"] == "ON_HOLD"

    rejected = resolve_hold(lot["id"], "REJECT")
    assert rejected["remaining_dozens"] == 0
    assert rejected["packed_dozens"] == 0
    assert rejected["destroyed_dozens"] == 60
    assert_lot_conservation(rejected)


def test_grade_threshold_boundaries_aa_vs_just_below_a(api):
    """PRD §3.6: "A score of at least 95.0 earns grade `AA`; a score of at least
    85.0 but below 95.0 earns `A`; a score of at least 70.0 but below 85.0 earns
    `B`."
    PRD §3.6: "Exactly 95.0 is `AA`, exactly 85.0 is `A`, and exactly 70.0 is
    `B`."

    Design: Corner/calculations/grade_threshold_boundaries_aa_vs_just_below_a
    """
    farm = create_active_farm(name="Threshold Farm")["farm"]
    lot1 = setup_collected_lot(
        farm["id"], route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    lot2 = setup_collected_lot(
        farm["id"], route_date="2026-09-09", collected_cases=1,
        collect_at="2026-09-09T10:00:00Z", laid_start_date="2026-09-07",
        laid_end_date="2026-09-08", capacity_cases=4,
    )["lot"]

    graded1 = grade_lot(lot1["id"], GRADE_AA_MIN)
    assert graded1["grade"] == "AA" and graded1["status"] == "GRADED"

    graded2 = grade_lot(lot2["id"], 84.99)
    assert graded2["grade"] == "B" and graded2["status"] == "GRADED", (
        "84.99 is below the A threshold (85.0) but at or above the B floor (70.0)"
    )


def test_quality_floor_boundary_70_vs_below(api):
    """PRD §3.6: "Exactly 95.0 is `AA`, exactly 85.0 is `A`, and exactly 70.0 is
    `B`. A score below 70.0 fails the packing standard: the lot's `grade` stays
    `NONE` and it falls `RECEIVED → ON_HOLD` instead."

    Design: Corner/calculations/quality_floor_boundary_70_vs_below
    """
    farm = create_active_farm(name="Floor Farm")["farm"]
    lot1 = setup_collected_lot(
        farm["id"], route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    lot2 = setup_collected_lot(
        farm["id"], route_date="2026-09-09", collected_cases=1,
        collect_at="2026-09-09T10:00:00Z", laid_start_date="2026-09-07",
        laid_end_date="2026-09-08", capacity_cases=4,
    )["lot"]

    graded1 = grade_lot(lot1["id"], GRADE_B_MIN)
    assert graded1["grade"] == "B" and graded1["status"] == "GRADED", (
        "exactly at the floor ships as B (inclusive boundary)"
    )

    graded2 = grade_lot(lot2["id"], 69.99)
    assert graded2["grade"] == "NONE" and graded2["status"] == "ON_HOLD", (
        "0.01 below the floor diverts the lot to the hold fork"
    )


def test_lot_grade_from_received_required(api):
    """PRD §3.6: "Grading is only legal from `RECEIVED` — re-grading a lot in
    any other state is `ERR_LOT_NOT_GRADABLE` (HTTP 409)"

    Design: Corner/errors_remaining_triggers/lot_grade_from_received_required
    """
    farm = create_active_farm(name="Regrade Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    assert lot["grade"] == "A"

    resp = api.grade_lot(lot["id"], {"quality_score": 97}, QM)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_GRADABLE, 409)

    reread = get_lot(lot["id"])
    assert reread["quality_score"] == 90 and reread["grade"] == "A", (
        "the rejected re-grade writes nothing"
    )


def test_lot_resolve_hold_requires_hold_state(api):
    """PRD §3.6: "A held lot awaits disposition by a `QualityManager`, legal
    only from `ON_HOLD` (otherwise `ERR_LOT_NOT_ON_HOLD`, HTTP 409)."

    Design: Corner/errors_remaining_triggers/lot_resolve_hold_requires_hold_state
    """
    farm = create_active_farm(name="No Hold Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    assert lot["status"] == "GRADED"

    resp = api.resolve_hold(lot["id"], {"disposition": "RELEASE"}, QM)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_ON_HOLD, 409)


def test_pack_exceeding_remaining_returns_insufficient_dozens(api):
    """PRD §3.6: "The `carton_count` may not exceed the lot's `remaining_dozens`;
    a larger request is rejected with `ERR_INSUFFICIENT_LOT_DOZENS` (HTTP 422)."

    Design: Corner/errors_remaining_triggers/pack_exceeding_remaining_returns_insufficient_dozens
    """
    farm = create_active_farm(name="Overpack Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    assert lot["remaining_dozens"] == 30

    resp = api.pack_cartons(lot["id"], {"carton_count": 31, "pack_size": "LARGE"}, PO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_DOZENS, 422)

    reread = get_lot(lot["id"])
    assert reread["remaining_dozens"] == 30 and reread["packed_dozens"] == 0, (
        "the rejected pack is atomic"
    )


def test_lot_and_carton_codes_use_deterministic_sequences(api):
    """PRD §3.5: "the server mints the next sequential human-facing `lot_code`
    (`LOT-000001`, `LOT-000002`, and so on)"
    PRD §3.6: "carrying a consumer-facing `carton_code` built from the lot's
    code plus a per-lot three-digit sequence, as in `LOT-000001-C001`,
    `LOT-000001-C002`"

    Design: Corner/entities/lot_and_carton_codes_use_deterministic_sequences
    """
    farm = create_active_farm(name="Sequence Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=2,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=10,
    )["lot"]
    assert lot["lot_code"] == "LOT-000001", (
        f"first lot minted on a fresh server is LOT-000001, got {lot['lot_code']}"
    )

    cartons = pack_cartons(lot["id"], 2, "MEDIUM")
    assert cartons[0]["carton_code"] == "LOT-000001-C001"
    assert cartons[1]["carton_code"] == "LOT-000001-C002"


def test_carton_is_immutable_without_version_field(api):
    """PRD §2.4: "Two resources are exceptions to this convention: a carton and
    a production forecast are immutable records that carry only `id` and
    `created_at`."
    PRD §2.4: "Both `updated_at` and `version` are absent on those two
    resources, and neither is ever modified after creation."
    PRD §3.6: "Each packed unit becomes a carton record containing exactly 1
    dozen in its `dozens` field"

    Design: Corner/entities/carton_is_immutable_without_version_field
    """
    farm = create_active_farm(name="Immutable Carton Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=2,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=10,
    )["lot"]
    cartons = pack_cartons(lot["id"], 2, "LARGE")
    code = cartons[0]["carton_code"]

    resp = api.get_carton(code, TEST_USERS["network_manager_headers"])
    carton = validate_success(resp, 200)
    assert_carton(carton)
    assert carton["carton_code"] == code
    assert "version" not in carton, "carton carries no version (immutable record)"
    assert "updated_at" not in carton, "carton carries no updated_at (immutable record)"
    assert carton["dozens"] == 1
    assert carton["lot_id"] == lot["id"]


def test_pack_response_matches_immediate_reread(api):
    """PRD §3.6: "Packing decrements the lot's `remaining_dozens` and increments
    its `packed_dozens` by the `carton_count`"

    Design: Corner/consistency_model/pack_response_matches_immediate_reread
    """
    farm = create_active_farm(name="Consistent Farm")["farm"]
    lot = setup_graded_lot(
        farm["id"], 90, route_date="2026-09-08", collected_cases=4,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=10,
    )["lot"]

    resp = api.pack_cartons(lot["id"], {"carton_count": 40, "pack_size": "LARGE"}, PO)
    cartons = validate_success(resp, 201)
    assert len(cartons) == 40, f"pack response carries 40 cartons, got {len(cartons)}"
    codes = {c["carton_code"] for c in cartons}
    assert len(codes) == 40, "carton codes are distinct"

    reread = validate_success(api.get_lot(lot["id"], QM), 200)
    assert reread["remaining_dozens"] == 80
    assert reread["packed_dozens"] == 40
    assert reread["destroyed_dozens"] == 0


def test_carton_trace_identifies_originating_farm(api):
    """PRD §3.6: "For traceability the carton also denormalizes `source_farm_id`
    and `source_farm_name` from the originating farm at pack time, while the
    authoritative lineage link remains the `lot_id` back to its lot."
    PRD §3.6: "A consumer, auditor, buyer, or operator holding a carton code can
    read the carton back — the one read open to every one of the six roles"

    Design: Corner/endpoints/carton_trace_identifies_originating_farm
    """
    farm = create_active_farm(name="Traceable Farm")["farm"]
    retailer = create_retailer()
    lot = setup_graded_lot(
        farm["id"], 96, route_date="2026-09-08", collected_cases=1,
        collect_at="2026-09-08T10:00:00Z", capacity_cases=4,
    )["lot"]
    cartons = pack_cartons(lot["id"], 3, "EXTRA_LARGE")
    code = cartons[0]["carton_code"]

    resp = api.get_carton(code, make_retailer_buyer_headers(retailer["id"]))
    carton = validate_success(resp, 200)
    assert carton["carton_code"] == code
    assert carton["source_farm_id"] == farm["id"]
    assert carton["source_farm_name"] == "Traceable Farm", (
        "the consumer can identify the originating farm"
    )
    assert carton["lot_id"] == lot["id"]
    assert carton["packed_at"].startswith("2026-09-08T10:00:00"), (
        f"packed_at is stamped from the logical clock, got {carton['packed_at']}"
    )
