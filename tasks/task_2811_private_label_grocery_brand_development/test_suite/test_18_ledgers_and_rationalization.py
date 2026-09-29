"""Two conserved quantities: the money a cancelled run gives back, the shelf slot
a rationalized item gives back, and the slotting fee that neither of them does."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_item_state,
    assert_money_cents,
    assert_shelf_slots,
    assert_status,
)
from test_helpers.constants import (
    ACTION_CLOSE,
    ACTION_START_RELAUNCH,
    DISPOSITION_DISCONTINUE,
    DISPOSITION_REPLACE,
    ITEM_CONCEPT,
    ITEM_DISCONTINUED,
    ITEM_LAUNCHED,
    ITEM_SPEC_LOCKED,
    POSTURE_GREEN,
    PROGRAM_ACTIVE,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_SCHEDULED,
    SPEC_LOCKED,
)
from test_helpers.fixtures import (
    add_ongoing_run,
    build_chain,
    read_budget_ledger,
    read_gap,
    read_item,
    read_run,
    read_specification,
)
from test_helpers.test_users import DIRECTOR_HEADERS, SOURCING_HEADERS


def test_cancelling_a_scheduled_run_returns_its_tooling_and_no_shelf_slot(api):
    """400,000 comes back to the budget; the 266,980 fee and the facing do not move.

    PRD 3.7: "Cancellation is available to a `SourcingManager` or a
    `ProgramDirector` from any of `SCHEDULED`, `APPROVED` or `HOLD`, and it is the
    system's one compensating action on the money ledger: the run moves to
    `CANCELLED`, the program's `committed_budget_cents` decreases by the run's
    `committed_tooling_cents` while `lifetime_released_cents` increases by the same
    amount, and the run's line window is freed for future overlap checks."

    PRD 2.11: "Cancelling a production run releases its committed tooling but no
    shelf slot."

    PRD 2.11: "For money, `committed_budget_cents` on a program must at all times
    equal `lifetime_committed_cents` minus `lifetime_released_cents`, where both
    lifetime figures are monotonically increasing and never decrease."

    Design: Difficulty/compensating_invariant/run_cancel_restores_program_committed_budget_cents
    """
    ctx = build_chain(api, upto=26)
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        dev_budget_cents=5000000,
        committed_budget_cents=666980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=0,
        available_budget_cents=4333020,
        active_item_count=1,
    )

    cancelled = validate_success(
        api.cancel_production_run(ctx["run_id"], SOURCING_HEADERS)
    )

    assert_status(cancelled, RUN_CANCELLED, "production run")
    assert_money_cents(
        cancelled["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        dev_budget_cents=5000000,
        committed_budget_cents=266980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=400000,
        available_budget_cents=4733020,
        active_item_count=1,
    )
    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_LOCKED, "specification")
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=1,
        slots_released_lifetime=0,
        slots_open=1,
    )
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_SPEC_LOCKED, POSTURE_GREEN)


def test_completing_a_run_never_releases_its_tooling_and_blocks_the_compensation(api):
    """The compensating action exists only from the three live statuses.

    PRD 2.11: "Completing a run does not release its tooling either: only
    cancellation does."

    PRD 3.7: "Cancelling a run that is already `COMPLETED` or `CANCELLED` is refused
    with `ERR_RUN_STATE_INVALID` (HTTP 409)."

    PRD 2.11: "Equivalently, `committed_budget_cents` is the sum of
    `slotting_fee_cents` over the program's specifications whose status is `LOCKED`,
    `SUPERSEDE_PENDING` or `SUPERSEDED`, plus the sum of `committed_tooling_cents`
    over the program's production runs whose status is `SCHEDULED`, `APPROVED`,
    `HOLD` or `COMPLETED`."

    Design: Difficulty/compensating_invariant/run_cancel_restores_program_committed_budget_cents
    """
    ctx = build_chain(api, upto=29)
    assert_status(ctx["run"], RUN_COMPLETED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=0,
    )

    response = api.cancel_production_run(ctx["run_id"], SOURCING_HEADERS)
    validate_error(response, ApiErrorId.ERR_RUN_STATE_INVALID.value, 409)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_COMPLETED, "production run")
    assert_money_cents(
        run["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=0,
        available_budget_cents=4333020,
    )


def test_discontinuing_a_launched_item_returns_the_facing_but_not_the_fee(api):
    """The slot ledger releases one unit while the money ledger stands still.

    PRD 3.9: "Both dispositions do the same accounting. The gap's `slots_consumed`
    decreases by 1 and its `slots_released_lifetime` increases by 1, so `slots_open`
    rises and the facing becomes available to a successor item; the program's
    `active_item_count` decreases by 1"

    PRD 3.9: "The slotting fee of the item's locked specification, however, stays
    committed permanently: the shelf slot comes back, the slotting fee does not."

    PRD 2.11: "For shelf space, `slots_consumed` on a category gap must at all times
    equal `slots_consumed_lifetime` minus `slots_released_lifetime`, and `slots_open`
    is `shelf_slots_quota` minus `slots_consumed`."

    Design: Difficulty/compensating_invariant/item_rationalize_restores_gap_shelf_slot_count
    """
    ctx = build_chain(api, upto=30)
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=1,
        slots_open=1,
        slots_consumed_lifetime=1,
        slots_released_lifetime=0,
    )

    retired = validate_success(
        api.rationalize_item(
            ctx["item_id"],
            f.rationalize_payload(DISPOSITION_DISCONTINUE),
            DIRECTOR_HEADERS,
        )
    )

    assert_item_state(retired, ITEM_DISCONTINUED, POSTURE_GREEN)
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=0,
        slots_open=2,
        slots_consumed_lifetime=1,
        slots_released_lifetime=1,
        shelf_slots_quota=2,
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=0,
        available_budget_cents=4333020,
        active_item_count=0,
    )
    assert_status(read_run(api, ctx["run_id"]), RUN_COMPLETED, "production run")
    assert_status(
        read_specification(api, ctx["specification_id"]), SPEC_LOCKED, "specification"
    )


def test_rationalizing_cancels_the_open_run_and_gives_back_both_quantities(api):
    """One request releases a facing and a tooling commitment, and keeps the fee.

    PRD 3.9: "and every production run of the item standing at `SCHEDULED`,
    `APPROVED` or `HOLD` transitions to `CANCELLED`, each one releasing its
    `committed_tooling_cents` back to the program — decreasing
    `committed_budget_cents` and increasing `lifetime_released_cents` — and each one
    having its `version` incremented. Runs already `COMPLETED` or `CANCELLED` are
    untouched."

    PRD 2.11: "Rationalizing or discontinuing an item releases its shelf slot and
    cancels its non-terminal runs — thereby releasing their tooling too — but the
    slotting fee of that item's locked specification stays committed forever."

    Design: Difficulty/compensating_invariant/item_rationalize_restores_gap_shelf_slot_count
    """
    ctx = build_chain(api, upto=30)
    ongoing = add_ongoing_run(
        api, ctx, "2026-09-10T06:00:00Z", "2026-09-10T12:00:00Z", planned_units=6000
    )
    assert_status(ongoing, RUN_SCHEDULED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=1066980,
        lifetime_committed_cents=1066980,
        lifetime_released_cents=0,
    )

    retired = validate_success(
        api.rationalize_item(
            ctx["item_id"],
            f.rationalize_payload(DISPOSITION_DISCONTINUE),
            DIRECTOR_HEADERS,
        )
    )

    assert_item_state(retired, ITEM_DISCONTINUED, POSTURE_GREEN)
    assert_status(read_run(api, ongoing["id"]), RUN_CANCELLED, "production run")
    assert_status(read_run(api, ctx["run_id"]), RUN_COMPLETED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_committed_cents=1066980,
        lifetime_released_cents=400000,
        available_budget_cents=4333020,
        active_item_count=0,
    )
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=0,
        slots_open=2,
        slots_released_lifetime=1,
    )
    spec = read_specification(api, ctx["specification_id"])
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert_status(spec, SPEC_LOCKED, "specification")


def test_the_ledger_read_commits_nothing_for_an_item_that_only_exists(api):
    """An item raises the active count and spends nothing at all.

    PRD 2.11: "The budget-ledger read returns `program_id`, `dev_budget_cents`,
    `committed_budget_cents`, `available_budget_cents`, `lifetime_committed_cents`,
    `lifetime_released_cents` and `active_item_count`."

    PRD 2.11: "The program-level `active_item_count` is the same count taken across
    every gap of the program."

    Design: Corner/endpoints/budget_ledger_computed_read_before_any_commitment
    """
    ctx = build_chain(api, upto=10)
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_CONCEPT, POSTURE_GREEN)

    ledger = read_budget_ledger(api, ctx["program_id"])

    assert ledger["program_id"] == ctx["program_id"]
    assert_budget_ledger(
        ledger,
        dev_budget_cents=5000000,
        committed_budget_cents=0,
        available_budget_cents=5000000,
        lifetime_committed_cents=0,
        lifetime_released_cents=0,
        active_item_count=1,
    )


def test_the_ledger_is_a_running_total_and_not_a_recount(api):
    """After a commit and a release the lifetime figures both stand still or rise.

    PRD 2.11: "For money, `committed_budget_cents` on a program must at all times
    equal `lifetime_committed_cents` minus `lifetime_released_cents`, where both
    lifetime figures are monotonically increasing and never decrease."

    PRD 2.11: "The program's available budget is `dev_budget_cents` minus
    `committed_budget_cents`."

    PRD 3.7: "the run moves to `CANCELLED`, the program's `committed_budget_cents`
    decreases by the run's `committed_tooling_cents` while `lifetime_released_cents`
    increases by the same amount"

    Design: Corner/calculations/budget_ledger_running_total_reconciles_after_commit_and_release
    """
    ctx = build_chain(api, upto=26)
    validate_success(api.cancel_production_run(ctx["run_id"], SOURCING_HEADERS))

    ledger = read_budget_ledger(api, ctx["program_id"])

    assert_budget_ledger(
        ledger,
        dev_budget_cents=5000000,
        committed_budget_cents=266980,
        available_budget_cents=4733020,
        lifetime_committed_cents=666980,
        lifetime_released_cents=400000,
        active_item_count=1,
    )
    assert_status(read_run(api, ctx["run_id"]), RUN_CANCELLED, "production run")


def test_replacing_an_item_with_itself_is_rejected(api):
    """A replacement must be a different article, so the ledgers never move.

    PRD 3.9: "With `disposition` set to `REPLACE` a `replacement_item_id` must
    accompany it, naming a different item that shares this item's `gap_id` and whose
    own `development_status` is neither `RATIONALIZED` nor `DISCONTINUED`; the field
    is stored on the item and the item moves to the terminal `RATIONALIZED`."

    PRD 3.9: "A replacement that is missing, self-referential, drawn from another gap
    or itself already retired — or a replacement supplied alongside a `DISCONTINUE`
    disposition — is refused with `ERR_REPLACEMENT_ITEM_INVALID` (HTTP 409)."

    Design: Corner/validations/rationalize_replace_pointing_at_itself_rejected
    """
    ctx = build_chain(api, upto=30)
    payload = f.rationalize_payload(DISPOSITION_REPLACE)
    payload["replacement_item_id"] = ctx["item_id"]

    response = api.rationalize_item(ctx["item_id"], payload, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_REPLACEMENT_ITEM_INVALID.value, 409)

    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_LAUNCHED, POSTURE_GREEN)
    assert item["replacement_item_id"] is None
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]), slots_consumed=1, slots_released_lifetime=0
    )
    assert_status(read_run(api, ctx["run_id"]), RUN_COMPLETED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        active_item_count=1,
    )


def test_rationalizing_an_item_that_never_reached_the_shelf_is_rejected(api):
    """Pruning is defined from the shelf, not from the drawing board.

    PRD 3.9: "Rationalization is available from `LAUNCHED` and from
    `RELAUNCH_PENDING`; from any other development status it is refused with
    `ERR_ITEM_STATE_INVALID` (HTTP 409)."

    PRD 2.11: "Each item counts as exactly one slot: `slots_consumed` is the count of
    the gap's items whose `development_status` is neither `RATIONALIZED` nor
    `DISCONTINUED`."

    Design: Corner/state_machines/item_rationalize_from_concept_rejected
    """
    ctx = build_chain(api, upto=10)

    response = api.rationalize_item(
        ctx["item_id"],
        f.rationalize_payload(DISPOSITION_DISCONTINUE),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ITEM_STATE_INVALID.value, 409)

    assert_item_state(read_item(api, ctx["item_id"]), ITEM_CONCEPT, POSTURE_GREEN)
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=1,
        slots_open=1,
        slots_released_lifetime=0,
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=0,
        active_item_count=1,
    )


def test_closing_a_program_with_a_live_run_is_rejected(api):
    """A scheduled run is an obligation the closure would abandon.

    PRD 3.1: "With `action` set to `CLOSE` the program moves `ACTIVE → CLOSED`, which
    is terminal, and this is permitted only when no production run anywhere in the
    program is still `SCHEDULED`, `APPROVED` or `HOLD`; otherwise the closure is
    refused with `ERR_ACTIVE_RUNS_PRESENT` (HTTP 409)."

    Design: Corner/state_machines/program_close_with_scheduled_run_rejected
    """
    ctx = build_chain(api, upto=26)

    response = api.program_lifecycle(
        ctx["program_id"], f.program_lifecycle_payload(ACTION_CLOSE), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ACTIVE_RUNS_PRESENT.value, 409)

    program = validate_success(api.get_program(ctx["program_id"], DIRECTOR_HEADERS))
    assert_status(program, PROGRAM_ACTIVE, "program")
    assert_status(read_run(api, ctx["run_id"]), RUN_SCHEDULED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_released_cents=0,
    )


def test_starting_a_relaunch_with_nothing_on_the_shelf_is_rejected(api):
    """A concept article gives the relaunch nothing to freeze.

    PRD 3.1: "With `action` set to `START_RELAUNCH` the program moves `ACTIVE →
    RELAUNCH_FREEZE`, but only if at least one item under the program is `LAUNCHED`
    or `RELAUNCH_PENDING` — there is nothing to relaunch otherwise, and the attempt
    is refused with `ERR_NO_LAUNCHED_ITEMS` (HTTP 409)."

    Design: Corner/state_machines/program_start_relaunch_without_launched_items_rejected
    """
    ctx = build_chain(api, upto=10)

    response = api.program_lifecycle(
        ctx["program_id"],
        f.program_lifecycle_payload(ACTION_START_RELAUNCH),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_NO_LAUNCHED_ITEMS.value, 409)

    program = validate_success(api.get_program(ctx["program_id"], DIRECTOR_HEADERS))
    assert_status(program, PROGRAM_ACTIVE, "program")
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_CONCEPT, POSTURE_GREEN)
