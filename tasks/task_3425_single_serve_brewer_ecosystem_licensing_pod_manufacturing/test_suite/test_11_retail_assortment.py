"""Retail assortment plans: slots, floors, slow movers, OCC, supersession."""
from test_helpers import (
    CATEGORY,
    ApiErrorId,
    create_account,
    create_brand,
    create_facility_with_line,
    create_plan,
    create_variety,
    get_account,
    get_success_data,
    make_slot,
    reserve_run,
    set_clock,
    transition_plan,
    transition_run,
    transition_variety,
    validate_error,
    validate_success,
)


def _get_plan(api, account_id, plan_id):
    """Plans have no single-resource GET; read via the account's listing."""
    rows = get_success_data(api.list_assortment_plans(account_id, CATEGORY))
    matches = [row for row in rows if row["id"] == plan_id]
    assert len(matches) == 1, f"plan {plan_id} not found in account listing"
    return matches[0]


def _variety_with_velocity_45001(name, roast_level, flavor_family,
                                 window_start="2026-09-10T00:00:00Z",
                                 window_end="2026-09-11T00:00:00Z",
                                 mid_window_instant="2026-09-10T12:00:00Z"):
    """Variety with margin 35 and exactly 45001 units of trailing velocity.

    The helper leaves the clock at ``mid_window_instant``, so a test invoking
    it twice must pass a later ``window_start``/``window_end``/
    ``mid_window_instant`` on the second call — reserving a window that opens
    before the current clock is ERR_WINDOW_IN_PAST (PRD §2.10.9).
    """
    brand = create_brand(kind="PLATFORM_OWNED", name=f"{name} Brand")
    variety = create_variety(brand["id"], name=name, roast_level=roast_level,
                             flavor_family=flavor_family, margin_cents=35)
    _, line = create_facility_with_line(capacity_pods_per_day=100000,
                                        changeover_hours=0)
    run = reserve_run(line["id"], variety["id"],
                      window_start=window_start,
                      window_end=window_end, planned_units=45001)
    set_clock(mid_window_instant)
    get_success_data(transition_run(run["id"], "IN_PROGRESS"))
    get_success_data(transition_run(run["id"], "COMPLETED", actual_units=45001))
    return variety


def test_empty_slots_rejected_and_account_version_unchanged(api, category_headers):
    """PRD §3.7: "a non-empty `slots` array; an empty array fails at creation
    with `ERR_EMPTY_SLOTS` (HTTP 400)."
    PRD §3.7: "the account's own `version` increments by one" on plan creation.

    Design: Difficulty/boundary_precision_check/empty_slots_boundary
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Empty Slot Beans")
    variety = create_variety(brand["id"], name="Solo Cup", roast_level="LIGHT")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)

    empty = api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": account["version"],
         "period": "2026-10", "slots": []},
        category_headers)
    validate_error(empty, ApiErrorId.ERR_EMPTY_SLOTS)

    # The rejected write did not consume a version bump: the originally
    # observed version still passes the OCC guard on the next attempt.
    plan = validate_success(api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": account["version"],
         "period": "2026-10", "slots": [make_slot(variety["id"], facings=1)]},
        category_headers), 201)
    assert plan["status"] == "DRAFT"


def test_single_slot_plan_is_accepted(api):
    """PRD §3.7: "Each slot names a `variety_id`, a `facings` count of at least
    1, and a `clearance_flag` marking clearance placement."
    PRD §3.7: "The new plan's `account_id` is the account in whose path it was
    created, its `status` is `DRAFT`, and its `productivity_cents` stays null
    until approval."

    Design: Difficulty/boundary_precision_check/empty_slots_boundary
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="One Slot Beans")
    variety = create_variety(brand["id"], name="Solo Cup 2", roast_level="LIGHT")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)

    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])
    assert plan["status"] == "DRAFT"
    assert plan["productivity_cents"] is None
    assert plan["account_id"] == account["id"]

    proposed = get_success_data(transition_plan(plan["id"], "PROPOSED"))
    assert proposed["status"] == "PROPOSED"


def test_plan_cannot_skip_proposal(api):
    """PRD §2.10: "the requested (current, target) pair must be a declared
    transition of the entity's state machine and the current state must not be
    terminal (`ERR_INVALID_STATE`)."
    PRD §3.7 walks plans `DRAFT → PROPOSED → APPROVED → LOCKED`.

    Design: Corner/state_machines/plan_cannot_skip_proposal
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Skip Brand")
    variety = create_variety(brand["id"], name="Skip Var")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])

    resp = transition_plan(plan["id"], "APPROVED")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert _get_plan(api, account["id"], plan["id"])["status"] == "DRAFT"


def test_plan_proposed_can_revert_to_draft(api):
    """PRD §3.7: "Elsewhere in the graph, a plan may revert `PROPOSED → DRAFT`"
    PRD §2.5: "an assortment plan's `productivity_cents` is null until the
    plan is approved"

    Design: Corner/state_machines/plan_proposed_can_revert_to_draft
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Revert Plan Brand")
    variety = create_variety(brand["id"], name="Revert Plan Var")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])
    get_success_data(transition_plan(plan["id"], "PROPOSED"))

    reverted = get_success_data(transition_plan(plan["id"], "DRAFT"))
    assert reverted["status"] == "DRAFT"
    assert reverted["productivity_cents"] is None


def test_locked_plan_accepts_no_transitions(api):
    """PRD §3.7: "`LOCKED`, `CANCELLED`, and `SUPERSEDED` are the terminal
    states."
    PRD §2.9: "Terminal states are absorbing — a resource in a terminal state
    accepts no further transitions, and any attempt to drive one is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/locked_plan_accepts_no_transitions
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Lock Brand")
    variety = create_variety(brand["id"], name="Lock Var")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])
    for target in ("PROPOSED", "APPROVED", "LOCKED"):
        get_success_data(transition_plan(plan["id"], target))

    for target in ("CANCELLED", "DRAFT", "APPROVED"):
        resp = transition_plan(plan["id"], target)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert _get_plan(api, account["id"], plan["id"])["status"] == "LOCKED"


def test_plan_facings_beyond_shelf_slots_rejected(api):
    """PRD §3.7: "the summed `facings` across all slots must fit within the
    account's `shelf_slots_total` (an overflow is `ERR_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/plan_facings_beyond_shelf_slots_rejected
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Facing Brand")
    v1 = create_variety(brand["id"], name="Facing Var A")
    v2 = create_variety(brand["id"], name="Facing Var B", roast_level="DARK")
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(v1["id"], facings=6),
                              make_slot(v2["id"], facings=5)])

    resp = transition_plan(plan["id"], "PROPOSED")
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert _get_plan(api, account["id"], plan["id"])["status"] == "DRAFT"


def test_productivity_floor_blocks_approval(api):
    """PRD §3.7: "it must reach the account's `productivity_floor_cents`; a
    plan that falls short is rejected with `ERR_PRODUCTIVITY_FLOOR_UNMET`
    (HTTP 422)."
    PRD §2.5: "an assortment plan's `productivity_cents` is null until the
    plan is approved"

    Design: Corner/validations/productivity_floor_blocks_approval
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Floor Brand")
    variety = create_variety(brand["id"], name="Floor Var")  # velocity 0
    account = create_account(shelf_slots_total=10, productivity_floor_cents=1)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])
    get_success_data(transition_plan(plan["id"], "PROPOSED"))

    resp = transition_plan(plan["id"], "APPROVED")
    validate_error(resp, ApiErrorId.ERR_PRODUCTIVITY_FLOOR_UNMET)

    stayed = _get_plan(api, account["id"], plan["id"])
    assert stayed["status"] == "PROPOSED"
    assert stayed["productivity_cents"] is None


def test_slow_mover_slot_blocks_lock_unless_clearance(api, planner_headers):
    """PRD §3.7: "Moving `APPROVED → LOCKED` requires every slot holding a
    `slow_mover` variety — per the ninety-day-age and velocity definition of
    §3.3 — to carry `clearance_flag` set to true; a slow mover slotted without
    clearance protection blocks the lock with `ERR_SLOW_MOVER_SLOT`
    (HTTP 409)."

    Design: Corner/validations/slow_mover_slot_blocks_lock_unless_clearance
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Slow Brand")
    variety = create_variety(brand["id"], name="Slow Var", roast_level="LIGHT")
    account_a = create_account(shelf_slots_total=10, productivity_floor_cents=0)
    account_b = create_account(shelf_slots_total=10, productivity_floor_cents=0)

    # 91 days old with zero velocity: slow_mover is true.
    set_clock("2026-12-01T00:00:00Z")
    read_back = get_success_data(api.get_pod_variety(variety["id"], planner_headers))
    assert read_back["slow_mover"] is True

    plan_no_clearance = create_plan(
        account_a["id"], period="2026-12",
        slots=[make_slot(variety["id"], facings=1, clearance_flag=False)])
    plan_clearance = create_plan(
        account_b["id"], period="2026-12",
        slots=[make_slot(variety["id"], facings=1, clearance_flag=True)])
    for plan in (plan_no_clearance, plan_clearance):
        get_success_data(transition_plan(plan["id"], "PROPOSED"))
        get_success_data(transition_plan(plan["id"], "APPROVED"))

    blocked = transition_plan(plan_no_clearance["id"], "LOCKED")
    validate_error(blocked, ApiErrorId.ERR_SLOW_MOVER_SLOT)
    assert _get_plan(api, account_a["id"], plan_no_clearance["id"])["status"] == \
        "APPROVED"

    locked = get_success_data(transition_plan(plan_clearance["id"], "LOCKED"))
    assert locked["status"] == "LOCKED"


def test_delisted_variety_not_listable_in_plan(api):
    """PRD §3.7: "Moving `DRAFT → PROPOSED` re-asserts the basics: the `slots`
    array must still be non-empty (`ERR_EMPTY_SLOTS`), every slot's variety
    must currently be in `ACTIVE` or `PHASE_OUT` (`ERR_VARIETY_NOT_LISTABLE`,
    HTTP 409)"

    Design: Corner/validations/delisted_variety_not_listable_in_plan
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Delist Brand")
    variety = create_variety(brand["id"], name="Delist Var")
    get_success_data(transition_variety(variety["id"], brand["id"], "DELISTED"))
    account = create_account(shelf_slots_total=10, productivity_floor_cents=0)

    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(variety["id"], facings=1)])
    assert plan["status"] == "DRAFT"

    resp = transition_plan(plan["id"], "PROPOSED")
    validate_error(resp, ApiErrorId.ERR_VARIETY_NOT_LISTABLE)


def test_occ_assortment_plan_stale_version(api, category_headers):
    """PRD §2.7: "Creating an assortment plan under a retail account requires
    the request to carry `expected_retail_account_version`, equal to the
    account's current `version`; a mismatch is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412), since plan creation can supersede a
    previously approved plan and must not do so from a stale view of the
    account."

    Design: Corner/cross_cutting_layers/occ_assortment_plan_stale_version
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="OCC Plan Brand")
    variety = create_variety(brand["id"], name="OCC Plan Var")
    account = create_account(shelf_slots_total=50, productivity_floor_cents=0)
    stale_version = account["version"]

    first = validate_success(api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": stale_version, "period": "2026-10",
         "slots": [make_slot(variety["id"], facings=1)]},
        category_headers), 201)
    assert first["status"] == "DRAFT"

    stale = api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": stale_version, "period": "2026-11",
         "slots": [make_slot(variety["id"], facings=1)]},
        category_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    refreshed = get_account(account["id"])
    assert refreshed["version"] == stale_version + 1

    second = validate_success(api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": refreshed["version"],
         "period": "2026-11", "slots": [make_slot(variety["id"], facings=2)]},
        category_headers), 201)
    assert second["status"] == "DRAFT"

    rows = get_success_data(api.list_assortment_plans(account["id"], CATEGORY))
    # Neither plan reached APPROVED, so no supersession fired.
    assert {row["status"] for row in rows} == {"DRAFT"}
    assert len(rows) == 2


def test_new_plan_supersedes_approved_but_not_locked(api, category_headers):
    """PRD §3.7: "if an `APPROVED` plan already exists for the same account
    and period it is automatically driven to `SUPERSEDED`, while if a `LOCKED`
    plan exists for that period the creation is refused outright with
    `ERR_INVALID_STATE`, because a locked plan can never be superseded."

    Design: Corner/cross_cutting_layers/new_plan_supersedes_approved_but_not_locked
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Supersede Brand")
    variety = create_variety(brand["id"], name="Supersede Var")
    account = create_account(shelf_slots_total=50, productivity_floor_cents=0)

    plan_a = create_plan(account["id"], period="2026-10",
                         slots=[make_slot(variety["id"], facings=1)])
    get_success_data(transition_plan(plan_a["id"], "PROPOSED"))
    get_success_data(transition_plan(plan_a["id"], "APPROVED"))

    plan_b = create_plan(account["id"], period="2026-10",
                         slots=[make_slot(variety["id"], facings=2)])
    assert plan_b["status"] == "DRAFT"
    assert _get_plan(api, account["id"], plan_a["id"])["status"] == "SUPERSEDED"

    for target in ("PROPOSED", "APPROVED", "LOCKED"):
        get_success_data(transition_plan(plan_b["id"], target))

    blocked = api.create_assortment_plan(
        account["id"],
        {"expected_retail_account_version": get_account(account["id"])["version"],
         "period": "2026-10", "slots": [make_slot(variety["id"], facings=3)]},
        category_headers)
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


def test_assortment_productivity_rounds_per_slot_then_sums(api):
    """PRD §3.7: "for each slot independently, multiply the slot's `facings`
    by the variety's `velocity_units_90d` and by its `margin_cents`, divide by
    90 (normalizing the ninety-day velocity to a per-day figure), and round
    that slot's value half-up to whole cents; only then are the per-slot
    values summed into the plan's `productivity_cents`. Summing the raw
    fractions and rounding once at the end yields a different total and is not
    the contract."

    Design: Difficulty/combinatorial_formula/assortment_per_slot_rounding_order
    """
    v1 = _variety_with_velocity_45001("House Medium", "MEDIUM", "UNFLAVORED")
    v2 = _variety_with_velocity_45001(
        "Dark Reserve", "DARK", "FLAVORED",
        window_start="2026-09-11T00:00:00Z",
        window_end="2026-09-11T12:00:00Z",
        mid_window_instant="2026-09-11T06:00:00Z")

    set_clock("2026-09-12T00:00:00Z")
    account = create_account(shelf_slots_total=100, productivity_floor_cents=70000)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(v1["id"], facings=3),
                              make_slot(v2["id"], facings=1)])
    get_success_data(transition_plan(plan["id"], "PROPOSED"))

    approved = get_success_data(transition_plan(plan["id"], "APPROVED"))
    assert approved["status"] == "APPROVED"
    # round(3*45001*35/90) + round(1*45001*35/90) == 52501 + 17500 == 70001;
    # clears the 70000 floor by exactly one cent.
    assert approved["productivity_cents"] == 70001


def test_assortment_productivity_70001_fails_a_70002_floor(api):
    """PRD §3.7: "Summing the raw fractions and rounding once at the end
    yields a different total and is not the contract."
    PRD §3.7: "it must reach the account's `productivity_floor_cents`; a plan
    that falls short is rejected with `ERR_PRODUCTIVITY_FLOOR_UNMET`
    (HTTP 422)."

    Design: Difficulty/combinatorial_formula/assortment_per_slot_rounding_order
    """
    v1 = _variety_with_velocity_45001("House Medium 2", "MEDIUM", "UNFLAVORED")
    v2 = _variety_with_velocity_45001(
        "Dark Reserve 2", "DARK", "FLAVORED",
        window_start="2026-09-11T00:00:00Z",
        window_end="2026-09-11T12:00:00Z",
        mid_window_instant="2026-09-11T06:00:00Z")

    set_clock("2026-09-12T00:00:00Z")
    # Floor 70002: per-slot-first rounding yields 70001 and must FAIL; the
    # sum-then-round alternative (70002) would pass — it is not the contract.
    account = create_account(shelf_slots_total=100, productivity_floor_cents=70002)
    plan = create_plan(account["id"], period="2026-10",
                       slots=[make_slot(v1["id"], facings=3),
                              make_slot(v2["id"], facings=1)])
    get_success_data(transition_plan(plan["id"], "PROPOSED"))

    resp = transition_plan(plan["id"], "APPROVED")
    validate_error(resp, ApiErrorId.ERR_PRODUCTIVITY_FLOOR_UNMET)
