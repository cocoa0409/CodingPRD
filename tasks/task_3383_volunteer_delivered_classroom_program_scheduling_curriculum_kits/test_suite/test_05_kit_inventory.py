"""Curriculum kit stock: counters, uniqueness, lifecycle, ledger (PRD §2.9, §3.6)."""
from test_helpers import (
    ADMIN,
    COORDINATOR,
    LOGISTICS,
    ApiErrorId,
    TUESDAYS_5,
    api_client,
    assert_delivery,
    assert_kit_inventory,
    assert_kit_ledger_invariant,
    base_world,
    get_delivery,
    get_inventory,
    kit_inventory_payload,
    make_area_office,
    make_delivery,
    make_inventory,
    make_program,
    plan_delivery,
    planned_delivery,
    record_session_delivery,
    schedule_delivery,
    scheduled_delivery,
    add_session,
    transition_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_kit_inventory_create_zeroes_counters(api):
    """PRD §3.6: "A `LogisticsCoordinator` creates a row by naming
    `area_office_id` and `program_catalog_id`; the pair is unique, and a
    duplicate create is rejected with `ERR_DUPLICATE_INVENTORY`. All six
    counters start at zero."

    Design: Corner/entities/corner_kit_inventory_create_zeroes_counters
    """
    office = make_area_office()
    program = make_program()
    resp = api_client.create_kit_inventory(kit_inventory_payload(office["id"], program["id"]), LOGISTICS)
    data = validate_success(resp, 201)
    assert_kit_inventory(data)
    for counter in (
        "assembled_count", "available_count", "reserved_count",
        "distributed_count", "written_off_count", "consumed_count",
    ):
        assert data[counter] == 0, f"{counter} must start at zero, got {data[counter]}"


def test_duplicate_inventory_rejected(api):
    """PRD §3.6: "Kit stock lives in inventory rows owned by the warehouse
    office. A `LogisticsCoordinator` creates a row by naming `area_office_id`
    and `program_catalog_id`; the pair is unique, and a duplicate create is
    rejected with `ERR_DUPLICATE_INVENTORY`."

    Design: Corner/validations/corner_duplicate_inventory_rejected
    """
    office = make_area_office()
    program = make_program()
    first = api_client.create_kit_inventory(kit_inventory_payload(office["id"], program["id"]), LOGISTICS)
    validate_success(first, 201)
    resp = api_client.create_kit_inventory(kit_inventory_payload(office["id"], program["id"]), LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVENTORY)
    rows, _ = validate_paginated(
        api_client.list_kit_inventories(
            LOGISTICS, params={"area_office_id": office["id"], "program_catalog_id": program["id"]}
        )
    )
    assert len(rows) == 1


def test_write_off_exceeds_available_rejected(api):
    """PRD §3.6: "WRITE_OFF takes a `quantity` no greater than
    `available_count`, else `ERR_WRITE_OFF_EXCEEDS_AVAILABLE`, and moves that
    many kits from `available_count` into `written_off_count`."

    Design: Corner/validations/corner_write_off_exceeds_available_rejected
    """
    office = make_area_office()
    program = make_program()
    inventory = make_inventory(office["id"], program["id"], assemble=15)

    resp = api_client.transition_kit_inventory(
        inventory["id"], {"action": "WRITE_OFF", "quantity": 16}, LOGISTICS
    )
    validate_error(resp, ApiErrorId.ERR_WRITE_OFF_EXCEEDS_AVAILABLE)

    ok = api_client.transition_kit_inventory(
        inventory["id"], {"action": "WRITE_OFF", "quantity": 15}, LOGISTICS
    )
    data = validate_success(ok, 200)
    assert data["available_count"] == 0, "writing off exactly available is allowed"
    assert data["written_off_count"] == 15
    assert_kit_ledger_invariant(data)


def test_program_coordinator_kit_transition_forbidden(api):
    """PRD §2.1: "A `LogisticsCoordinator` owns kit inventory rows and stock
    movements."
    PRD §2.1: "Once authenticated, a role may invoke only the operations
    assigned to it; any other attempt is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/corner_program_coordinator_kit_transition_forbidden
    """
    office = make_area_office()
    program = make_program()
    inventory = make_inventory(office["id"], program["id"])
    resp = api_client.transition_kit_inventory(
        inventory["id"], {"action": "ASSEMBLE", "quantity": 10}, COORDINATOR
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_inventory(inventory["id"])["assembled_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: per-session-then-sum kit rounding (two tests)
# ---------------------------------------------------------------------------

def _kit_rounding_world():
    """5-session program (floor 200000), ACTIVE agreement, eligible lead."""
    return base_world(session_count=5, program_code="JA-ECO", min_students=10)


def test_kit_requirement_create_response_uses_per_session_rounding(api):
    """PRD §3.4: "For 27 enrolled students in a five-session program, the
    per-session count is 27 times 0.20, which is 5.4 rounded up to 6, and the
    requirement is 3 plus 5 times 6: 33 kits. The forbidden sum-then-round
    order would yield 30; the two differ, and per-session-first is law."

    Design: Difficulty/combinatorial_formula/kit_requirement_rounds_per_session_then_sums
    """
    world = _kit_rounding_world()
    delivery = make_delivery(
        world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=27
    )
    assert delivery["required_kits"] == 33, (
        f"per-session-then-sum is law: expected 33, got {delivery['required_kits']}"
    )
    assert delivery["required_kits"] != 30, "sum-then-round (30) is the forbidden order"


def test_kit_requirement_persisted_on_readback(api):
    """PRD §3.4: "The kit requirement is computed once, at creation, with the
    rounding order pinned."
    PRD §3.4: "starts the delivery in DRAFT with `kit_status` NONE,
    `teacher_confirmed` false, `kits_consumed` zero, and both session counters
    at zero."

    Design: Difficulty/combinatorial_formula/kit_requirement_rounds_per_session_then_sums
    """
    world = _kit_rounding_world()
    created = make_delivery(
        world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=27
    )
    data = get_delivery(created["id"])
    assert_delivery(data)
    assert data["required_kits"] == 33
    assert data["status"] == "DRAFT"
    assert data["kit_status"] == "NONE"
    assert data["teacher_confirmed"] is False
    assert data["kits_consumed"] == 0


# ---------------------------------------------------------------------------
# Difficulty: exact-availability reserve boundary (two tests)
# ---------------------------------------------------------------------------

def _reserve_boundary_world():
    """Inventory assembled to exactly the 23 kits a 20-student 5-session
    delivery requires; two PLANNED deliveries each needing 23."""
    world = base_world(session_count=5, program_code="JA-ECO5", min_students=10, assemble=23)
    d1 = planned_delivery(world, enrolled_count=20, classroom_label="Room 9")
    d2 = planned_delivery(world, enrolled_count=20, classroom_label="Room 10")
    assert d1["required_kits"] == 23 and d2["required_kits"] == 23
    return world, d1, d2


def test_kit_reserve_succeeds_at_exact_availability(api):
    """PRD §3.6: "RESERVE_KITS moves `kit_status` from NONE to RESERVED while
    the delivery is PLANNED, else `ERR_INVALID_STATE`, and requires the
    inventory's `available_count` to be at least `required_kits` — a missing
    inventory row counts as zero stock — with any shortfall rejected as
    `ERR_KIT_SHORTAGE`; success moves `required_kits` from `available_count`
    into `reserved_count` and bumps the inventory row's `version`."

    Design: Difficulty/boundary_precision_check/kit_reserve_succeeds_at_exact_availability_then_shortage
    """
    world, d1, _d2 = _reserve_boundary_world()
    resp = api_client.transition_delivery(d1["id"], {"action": "RESERVE_KITS"}, COORDINATOR)
    data = validate_success(resp, 200)
    assert data["kit_status"] == "RESERVED", "23 >= 23: exact-fill reservation succeeds"
    inv = get_inventory(world["inventory"]["id"])
    assert inv["available_count"] == 0
    assert inv["reserved_count"] == 23
    assert_kit_ledger_invariant(inv)


def test_kit_reserve_after_exact_fill_reports_shortage(api):
    """PRD §3.6: "requires the inventory's `available_count` to be at least
    `required_kits` — a missing inventory row counts as zero stock — with any
    shortfall rejected as `ERR_KIT_SHORTAGE`"

    Design: Difficulty/boundary_precision_check/kit_reserve_succeeds_at_exact_availability_then_shortage
    """
    world, d1, d2 = _reserve_boundary_world()
    transition_delivery(d1["id"], "RESERVE_KITS")  # drains the pool to 0
    resp = api_client.transition_delivery(d2["id"], {"action": "RESERVE_KITS"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_KIT_SHORTAGE)
    assert get_delivery(d2["id"])["kit_status"] == "NONE"


# ---------------------------------------------------------------------------
# Difficulty: kit ledger invariant across the lifecycle (two tests)
# ---------------------------------------------------------------------------

def _ledger_setup():
    """Inventory assembled 50 then 5 written off; delivery (23 kits) planned
    with 5 confirmed 90-minute sessions."""
    world = base_world(session_count=5, program_code="JA-ECO7", min_students=10, assemble=50)
    inv_id = world["inventory"]["id"]
    resp = api_client.transition_kit_inventory(inv_id, {"action": "WRITE_OFF", "quantity": 5}, LOGISTICS)
    after_write_off = validate_success(resp, 200)
    assert (after_write_off["available_count"], after_write_off["written_off_count"]) == (45, 5)
    delivery = planned_delivery(world, enrolled_count=20)
    assert delivery["required_kits"] == 23
    sessions = [
        add_session(delivery["id"], world["volunteer"]["id"], d, start_minutes=540, end_minutes=630, confirm=True)
        for d in TUESDAYS_5
    ]
    return world, delivery, sessions, after_write_off


def test_kit_ledger_invariant_through_reserve_and_distribute(api):
    """PRD §2.9: "one invariant holds at all times: the lifetime
    `assembled_count` always equals the sum of the other five counters."
    PRD §3.6: "DISTRIBUTE_KITS moves RESERVED to DISTRIBUTED while the delivery
    is SCHEDULED, else `ERR_INVALID_STATE`, moving `required_kits` from
    `reserved_count` into `distributed_count`."

    Design: Difficulty/compensating_invariant/kit_ledger_invariant_through_reserve_distribute_reconcile
    """
    world, delivery, _sessions, after_write_off = _ledger_setup()
    assert_kit_ledger_invariant(after_write_off)  # (45, 0, 0, 5, 0)

    transition_delivery(delivery["id"], "CONFIRM_TEACHER")
    transition_delivery(delivery["id"], "RESERVE_KITS")
    inv_reserved = get_inventory(world["inventory"]["id"])
    assert (inv_reserved["available_count"], inv_reserved["reserved_count"]) == (22, 23)
    assert_kit_ledger_invariant(inv_reserved)

    transition_delivery(delivery["id"], "SCHEDULE")
    transition_delivery(delivery["id"], "DISTRIBUTE_KITS")
    inv_distributed = get_inventory(world["inventory"]["id"])
    assert (inv_distributed["reserved_count"], inv_distributed["distributed_count"]) == (0, 23)
    assert inv_distributed["available_count"] == 22
    assert_kit_ledger_invariant(inv_distributed)


def test_kit_ledger_invariant_through_reconcile_with_consumption(api):
    """PRD §3.6: "RECONCILE_KITS moves DISTRIBUTED to RECONCILED while the
    delivery is COMPLETED, else `ERR_INVALID_STATE`, and carries a
    `kits_consumed` between zero and `required_kits` inclusive, else
    `ERR_VALIDATION`; the delivery records `kits_consumed`, `distributed_count`
    decreases by `required_kits`, `consumed_count` increases by
    `kits_consumed`, and the unconsumed remainder returns to
    `available_count`."

    Design: Difficulty/compensating_invariant/kit_ledger_invariant_through_reserve_distribute_reconcile
    """
    world, delivery, sessions, _ = _ledger_setup()
    transition_delivery(delivery["id"], "CONFIRM_TEACHER")
    transition_delivery(delivery["id"], "RESERVE_KITS")
    transition_delivery(delivery["id"], "SCHEDULE")
    transition_delivery(delivery["id"], "DISTRIBUTE_KITS")
    for session, date in zip(sessions, TUESDAYS_5):
        record_session_delivery(session["id"], date)
    completed = transition_delivery(delivery["id"], "COMPLETE")
    assert completed["status"] == "COMPLETED"

    reconciled = transition_delivery(delivery["id"], "RECONCILE_KITS", kits_consumed=20)
    assert reconciled["kit_status"] == "RECONCILED"
    assert reconciled["kits_consumed"] == 20
    inv = get_inventory(world["inventory"]["id"])
    assert inv["available_count"] == 25, "3 unconsumed kits return to the shelf"
    assert inv["distributed_count"] == 0
    assert inv["consumed_count"] == 20
    assert inv["written_off_count"] == 5
    assert inv["assembled_count"] == 50
    assert_kit_ledger_invariant(inv)
