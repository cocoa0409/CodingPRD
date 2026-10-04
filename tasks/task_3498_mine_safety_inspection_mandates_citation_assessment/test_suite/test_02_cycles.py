"""Statutory inspection cycles (PRD §2.6, §3.2): window geometry, opening,
closing, delinquency, and the pinned oldest-DELINQUENT-first crediting order.

Clock note: the logical clock starts at 2026-09-01T00:00:00Z (PRD §2.4), so all
cycle arithmetic in this file is rebased onto that start (activation
2026-09-01); relative geometry is preserved — UNDERGROUND spans of exactly 90
inclusive days ([2026-09-01, 2026-11-29], then [2026-11-30, 2027-02-27]) and a
SURFACE span of exactly 180 inclusive days ([2026-09-01, 2027-02-27]).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_inspection_cycle,
    close_cycle,
    completed_regular_inspection,
    create_inspection_cycle_payload,
    open_cycle,
    refresh_cycle,
    refresh_mine,
    set_clock,
    setup_mine,
    setup_mine_with_delinquent_cycle,
    setup_registry,
    setup_required_plans,
    submit_and_approve_plan,
    validate_created,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_quota_crediting_oldest_delinquent_first_order(api):
    """PRD §3.2: "First, the server builds the candidate set of the mine's
    cycles in `DELINQUENT` status whose `completed_inspections` is still below
    their `required_inspections`, ordered by `period_start` ascending with ties
    broken by `created_at` ascending. If that set is non-empty, the first
    candidate — and only the first — receives the credit. Otherwise the credit
    goes to the unique `OPEN` cycle whose inclusive window from `period_start`
    to `period_end` contains the completion date; non-overlapping cycle
    geometry guarantees at most one such cycle."
    PRD §3.2: "Whenever a credit raises a `DELINQUENT` cycle's
    `completed_inspections` up to its `required_inspections`, that cycle
    transitions from `DELINQUENT` to `CURED`."

    Rebase note: cycle 1 [2026-09-01, 2026-11-29] is closed DELINQUENT at
    2026-11-30; cycle 2 [2026-11-30, 2027-02-27] is OPEN; the REGULAR
    inspection completes at 2026-12-09 (inside cycle 2's window), yet the
    pinned order credits the older delinquent cycle.

    Design: Difficulty/combinatorial_formula/quota_crediting_oldest_delinquent_first_order
    """
    bundle = setup_mine_with_delinquent_cycle(mine_type="UNDERGROUND")
    operator, mine, inspector = bundle["operator"], bundle["mine"], bundle["inspector"]
    cycle1, cycle2 = bundle["cycle1"], bundle["cycle2"]
    assert cycle1["status"] == "DELINQUENT" and cycle1["completed_inspections"] == 0
    assert cycle2["status"] == "OPEN"

    # All three plan types APPROVED so the REGULAR-completion gate passes.
    setup_required_plans(mine, operator)

    set_clock("2026-12-09T12:00:00Z")
    inspection = completed_regular_inspection(
        refresh_mine(mine["id"]),
        cycle2,
        inspector,
        planned_start_at="2026-12-08T08:00:00Z",
        planned_end_at="2026-12-09T12:00:00Z",
    )
    assert inspection["status"] == "COMPLETED"

    cycle1_after = refresh_cycle(cycle1["id"])
    cycle2_after = refresh_cycle(cycle2["id"])
    assert cycle1_after["status"] == "CURED", (
        "the oldest DELINQUENT cycle is credited first and cured"
    )
    assert cycle1_after["completed_inspections"] == 1
    assert cycle2_after["status"] == "OPEN" and cycle2_after["completed_inspections"] == 0, (
        "the OPEN cycle containing the completion date is NOT credited while a "
        "delinquent candidate exists"
    )


def test_mine_idle_reactivate_round_trip_preserves_pov_axis(api):
    """PRD §3.1: "An administrator may idle a mine, moving its `status` from
    `ACTIVE` to `IDLED`, and later reactivate it back to `ACTIVE`; each
    transition increments the mine's `version`. Idling is an operational
    annotation only — an `IDLED` mine remains fully subject to its statutory
    inspection cycles, which continue to open, close, and fall delinquent on
    schedule — but an `IDLED` mine cannot accept an accident report or a new
    imminent-danger order (§3.5, §3.7)."

    Design: Difficulty/non_linear_state_machine/mine_idle_reactivate_round_trip_preserves_pov_axis
    """
    set_clock("2026-09-05T09:00:00Z")
    _operator, mine = setup_mine(mine_type="UNDERGROUND", activation_date="2026-09-01")
    v_created = mine["version"]

    idled = validate_success(api.idle_mine(mine["id"], _ADMIN))
    assert idled["status"] == "IDLED"
    assert idled["version"] == v_created + 1, "idle increments the mine version by one"

    # Statutory cycle creation keeps working while the mine is IDLED.
    cycle = open_cycle(refresh_mine(mine["id"]))
    assert_inspection_cycle(cycle)
    assert cycle["status"] == "OPEN"
    assert cycle["period_start"] == "2026-09-01" and cycle["period_end"] == "2026-11-29"
    assert cycle["required_inspections"] == 1 and cycle["completed_inspections"] == 0

    reactivated = validate_success(api.reactivate_mine(mine["id"], _ADMIN))
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["version"] == idled["version"] + 1, (
        "reactivate increments the mine version by one"
    )
    assert reactivated["pov_status"] == "NONE", (
        "the idle/reactivate round trip leaves the orthogonal POV axis untouched"
    )
    assert reactivated["production_status"] == "NORMAL"


def test_cycle_close_early_requires_met_requirement(api):
    """PRD §3.2: "When `completed_inspections` has reached
    `required_inspections`, closing transitions the cycle from `OPEN` to
    `COMPLIANT`, and this early close is permitted at any time, even before
    `period_end`. When the requirement is unmet, closing is refused with
    `ERR_CYCLE_CLOSE_TOO_EARLY` while the current logical date is on or before
    `period_end`; only once the current logical date is strictly later than
    `period_end` may an unmet cycle be closed, and it then closes as
    `DELINQUENT`."
    PRD §3.2: "The `CURED` state preserves the delinquency history — the cycle
    is never re-opened — and `COMPLIANT` and `CURED` are the terminal states of
    the cycle axis."

    Design: Corner/state_machines/cycle_close_early_requires_met_requirement
    """
    set_clock("2026-09-05T09:00:00Z")
    operator, mine, inspector = setup_registry(mine_type="SURFACE")
    cycle = open_cycle(mine)  # [2026-09-01, 2027-02-27] inclusive (180 days)
    assert cycle["period_start"] == "2026-09-01" and cycle["period_end"] == "2027-02-27"

    # Approve the one plan type a SURFACE mine requires before any completion.
    submit_and_approve_plan(mine, operator, "EMERGENCY_RESPONSE")

    # Unmet close attempt while the period is still running -> too early.
    set_clock("2026-11-01T09:00:00Z")
    resp = api.close_inspection_cycle(cycle["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_CYCLE_CLOSE_TOO_EARLY)
    assert refresh_cycle(cycle["id"])["status"] == "OPEN"

    # Complete the statutory REGULAR inspection, then the early close succeeds.
    set_clock("2026-11-20T16:00:00Z")
    completed_regular_inspection(
        refresh_mine(mine["id"]),
        refresh_cycle(cycle["id"]),
        inspector,
        planned_start_at="2026-11-20T08:00:00Z",
        planned_end_at="2026-11-20T17:00:00Z",
    )
    closed = close_cycle(refresh_cycle(cycle["id"]))
    assert closed["status"] == "COMPLIANT"
    assert closed["completed_inspections"] == 1
    assert closed["required_inspections"] == 1

    # COMPLIANT is terminal: a second close is a state error.
    resp = api.close_inspection_cycle(cycle["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cycle_geometry_and_open_cycle_enforced(api):
    """PRD §2.6: "An `UNDERGROUND` mine's cycle spans exactly 90 days; a
    `SURFACE` mine's cycle spans exactly 180 days. Both `period_start` and
    `period_end` are inclusive bounds, so `period_end` falls 89 days after
    `period_start` for underground mines and 179 days after for surface mines.
    The first cycle of a mine begins exactly on the mine's `activation_date`."
    PRD §3.2: "Any geometric violation is rejected with
    `ERR_CYCLE_PERIOD_INVALID`. A new cycle may only be opened when no other
    cycle of the same mine is still `OPEN`; otherwise the request fails with
    `ERR_CYCLE_OPEN_EXISTS`."

    Design: Corner/validations/cycle_geometry_and_open_cycle_enforced
    """
    set_clock("2026-09-05T09:00:00Z")
    _operator, mine = setup_mine(mine_type="UNDERGROUND", activation_date="2026-09-01")

    # 89-day span (period_end one day short) -> geometric violation.
    resp = api.create_inspection_cycle(
        mine["id"],
        create_inspection_cycle_payload(
            "2026-09-01", mine_type="UNDERGROUND", period_end="2026-11-28"
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_PERIOD_INVALID)

    # Exact 90-day span but not starting on activation_date -> violation.
    resp = api.create_inspection_cycle(
        mine["id"],
        create_inspection_cycle_payload(
            "2026-09-02", mine_type="UNDERGROUND", period_end="2026-11-30"
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_PERIOD_INVALID)

    # Geometrically correct first cycle is accepted.
    resp = api.create_inspection_cycle(
        mine["id"],
        create_inspection_cycle_payload("2026-09-01", mine_type="UNDERGROUND"),
        _ADMIN,
    )
    cycle = validate_created(resp)
    assert cycle["period_start"] == "2026-09-01" and cycle["period_end"] == "2026-11-29"
    assert cycle["status"] == "OPEN"

    # A second cycle while the first is still OPEN -> exclusivity violation.
    resp = api.create_inspection_cycle(
        mine["id"],
        create_inspection_cycle_payload("2026-11-30", mine_type="UNDERGROUND"),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_OPEN_EXISTS)
