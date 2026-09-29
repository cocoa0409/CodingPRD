"""Booking the line: the chain of agreements a run must satisfy, the pro-rated
capacity ceiling and the buffered line window."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_money_cents,
    assert_shelf_slots,
    assert_status,
)
from test_helpers.constants import (
    ITEM_CONCEPT,
    ITEM_SPEC_LOCKED,
    POSTURE_SUSPENDED,
    RUN_ONGOING,
    RUN_SCHEDULED,
    SPEC_DRAFT,
    SPEC_LOCKED,
    SUPPLIER_SUSPENDED,
)
from test_helpers.fixtures import (
    build_chain,
    read_budget_ledger,
    read_gap,
    read_item,
    read_run,
    read_specification,
    read_supplier,
    suspend_supplier,
)
from test_helpers.test_users import SOURCING_HEADERS


def _runs_for(api, item_id):
    rows, meta = validate_paginated(
        api.list_production_runs(SOURCING_HEADERS, params={"item_id": item_id})
    )
    return rows, meta


def test_scheduling_against_a_draft_revision_of_the_specification_is_rejected(api):
    """The item being SPEC_LOCKED is not enough; the named revision must be LOCKED.

    PRD 3.7: "The named specification must belong to the same item as the run, or
    the request is refused with `ERR_SPECIFICATION_ITEM_MISMATCH` (HTTP 409), and it
    must stand at `LOCKED` — a `DRAFT`, `SUPERSEDE_PENDING` or `SUPERSEDED`
    specification is refused with `ERR_SPECIFICATION_NOT_LOCKED` (HTTP 409)."

    Design: Corner/validations/run_schedule_against_draft_specification_rejected
    """
    ctx = build_chain(api, upto=25)
    item_version = read_item(api, ctx["item_id"])["version"]
    second = validate_success(
        api.create_specification(
            f.specification_payload(
                ctx["item_id"],
                ctx["cost_model_id"],
                ctx["artwork_round_id"],
                item_version,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    response = api.create_production_run(
        f.production_run_payload(ctx["item_id"], second["id"], ctx["plant_line_id"]),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_NOT_LOCKED.value, 409)

    draft = read_specification(api, second["id"])
    assert_status(draft, SPEC_DRAFT, "specification")
    assert draft["revision_no"] == 2
    assert_status(
        read_specification(api, ctx["specification_id"]), SPEC_LOCKED, "specification"
    )
    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0, "no tooling is committed by a refused schedule"
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_scheduling_a_run_against_another_items_specification_is_rejected(api):
    """A specification governs exactly the item it names.

    PRD 3.7: "The named specification must belong to the same item as the run, or
    the request is refused with `ERR_SPECIFICATION_ITEM_MISMATCH` (HTTP 409)"

    Design: Corner/validations/run_schedule_with_another_items_specification_rejected
    """
    ctx = build_chain(api, upto=25)
    other = validate_success(
        api.create_item(
            f.item_payload(
                ctx["gap_id"],
                item_name="Harvest Lane Sesame Crackers",
                pack_size_desc="10 oz carton",
                trailing_90d_units=0,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    response = api.create_production_run(
        f.production_run_payload(
            other["id"], ctx["specification_id"], ctx["plant_line_id"]
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_ITEM_MISMATCH.value, 409)

    unrelated = read_item(api, other["id"])
    assert unrelated["development_status"] == ITEM_CONCEPT
    assert unrelated["supplier_id"] is None
    assert read_specification(api, ctx["specification_id"])["item_id"] == ctx["item_id"]
    _rows, meta = _runs_for(api, other["id"])
    assert meta["total_count"] == 0
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]), slots_consumed=2, slots_open=0, shelf_slots_quota=2
    )


def test_scheduling_a_run_on_another_suppliers_line_is_rejected(api):
    """Ample capacity on the wrong plant is still the wrong plant.

    PRD 3.7: "The named line must belong to the item's awarded supplier; a line at
    some other plant is refused with `ERR_PLANT_LINE_SUPPLIER_MISMATCH` (HTTP 409)."

    Design: Corner/validations/run_schedule_on_another_suppliers_line_rejected
    """
    ctx = build_chain(api, upto=25)
    other_supplier = validate_success(
        api.create_supplier(
            f.supplier_payload(
                ctx["program_id"],
                legal_name="Eastvale Snack Works",
                gfsi_certificate_expiry="2027-09-30T00:00:00Z",
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )
    other_line = validate_success(
        api.create_plant_line(
            f.plant_line_payload(
                other_supplier["id"],
                line_code="CRK-9",
                daily_capacity_units=90000,
                changeover_buffer_minutes=60,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"], ctx["specification_id"], other_line["id"]
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PLANT_LINE_SUPPLIER_MISMATCH.value, 409)

    assert other_line["supplier_id"] == other_supplier["id"]
    assert read_item(api, ctx["item_id"])["supplier_id"] == ctx["supplier_id"]
    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_a_first_production_run_one_unit_below_the_moq_is_rejected(api):
    """The MOQ floor is inclusive, so 11,999 against 12,000 is short.

    PRD 3.7: "A `FIRST_PRODUCTION` run must additionally plan at least as many
    units as the pinned cost model's `moq_units`; planning fewer is refused with
    `ERR_BELOW_MOQ` (HTTP 422). This minimum applies only to first-production runs,
    not to `ONGOING` replenishment."

    Design: Corner/validations/first_production_run_below_moq_rejected
    """
    ctx = build_chain(api, upto=25)
    assert ctx["cost_model"]["moq_units"] == 12000

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"],
            ctx["specification_id"],
            ctx["plant_line_id"],
            planned_units=11999,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_BELOW_MOQ.value, 422)

    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_planned_units_above_the_prorated_window_capacity_are_rejected(api):
    """Capacity is pro-rated by window minutes, not read off the daily headline.

    PRD 3.7: "**Line capacity**: `planned_units` must not exceed the line's
    pro-rated capacity for the requested window, which is the line's
    `daily_capacity_units` multiplied by the window's duration in minutes, divided by
    1,440 — the number of minutes in a twenty-four-hour day — and floored to a whole
    number of units. Exceeding it is refused with `ERR_LINE_CAPACITY_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/run_planned_units_above_prorated_line_capacity_rejected
    """
    ctx = build_chain(api, upto=25)
    assert ctx["plant_line"]["daily_capacity_units"] == 60000

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"],
            ctx["specification_id"],
            ctx["plant_line_id"],
            planned_units=30001,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value, 409)

    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0, "a 720-minute window allows exactly 30000 units"
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_scheduling_whose_tooling_would_overrun_the_budget_is_rejected(api):
    """The same fiscal error id is reachable from the run endpoint.

    PRD 3.7: "`committed_tooling_cents` is snapshotted from the pinned cost model's
    `tooling_cents` as it stands at that instant, and the program's
    `committed_budget_cents` and `lifetime_committed_cents` both increase by that
    amount — which means the same budget headroom test applies here as at lock time:
    the program's `committed_budget_cents` plus the pinned model's tooling must not
    exceed `dev_budget_cents`, or scheduling is refused with
    `ERR_PROGRAM_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/run_schedule_beyond_program_budget_rejected
    """
    ctx = build_chain(api, upto=25, program={"dev_budget_cents": 500000})

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"], ctx["specification_id"], ctx["plant_line_id"]
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED.value, 422)

    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        dev_budget_cents=500000,
        committed_budget_cents=266980,
        available_budget_cents=233020,
        lifetime_released_cents=0,
    )


def test_a_run_whose_buffered_window_touches_another_is_rejected(api):
    """Both windows grow by 120 minutes and meet exactly at 20:00 — a collision.

    PRD 3.7: "**Line exclusivity**: the requested window, expanded by the line's
    `changeover_buffer_minutes` at both ends, must not intersect the equally expanded
    window of any other run on the same line whose status is `SCHEDULED`, `APPROVED`,
    `HOLD` or `COMPLETED`. Run windows are closed intervals, so touching endpoints
    count as an intersection, and a held run still occupies its line. A conflict is
    refused with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409); a cancelled run's window, by
    contrast, is free and never conflicts."

    Design: Difficulty/resource_temporal_overlap/line_run_closed_interval_with_changeover_buffer
    """
    ctx = build_chain(api, upto=26)
    assert ctx["plant_line"]["changeover_buffer_minutes"] == 120

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"],
            ctx["specification_id"],
            ctx["plant_line_id"],
            run_type=RUN_ONGOING,
            window_start="2026-09-07T20:00:00Z",
            window_end="2026-09-08T02:00:00Z",
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_LINE_WINDOW_CONFLICT.value, 409)

    assert_status(read_run(api, ctx["run_id"]), RUN_SCHEDULED, "production run")
    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 1, "the refused run commits no tooling"
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=666980
    )


def test_a_run_beginning_one_minute_clear_of_the_buffer_is_accepted(api):
    """22:01 expands to 20:01, one minute past the incumbent's 20:00 edge.

    PRD 3.7: "**Line exclusivity**: the requested window, expanded by the line's
    `changeover_buffer_minutes` at both ends, must not intersect the equally expanded
    window of any other run on the same line whose status is `SCHEDULED`, `APPROVED`,
    `HOLD` or `COMPLETED`."

    PRD 3.7: "A newly scheduled run opens at `SCHEDULED` with `produced_units`,
    `completed_on_time`, `completed_at`, `approved_by_user_id` and `hold_reason` all
    null."

    Design: Difficulty/resource_temporal_overlap/line_run_closed_interval_with_changeover_buffer
    """
    ctx = build_chain(api, upto=26)

    accepted = validate_success(
        api.create_production_run(
            f.production_run_payload(
                ctx["item_id"],
                ctx["specification_id"],
                ctx["plant_line_id"],
                run_type=RUN_ONGOING,
                window_start="2026-09-07T22:01:00Z",
                window_end="2026-09-08T04:01:00Z",
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    assert_status(accepted, RUN_SCHEDULED, "production run")
    assert_money_cents(
        accepted["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert accepted["produced_units"] is None
    assert accepted["completed_on_time"] is None
    assert accepted["completed_at"] is None
    assert accepted["approved_by_user_id"] is None
    assert accepted["hold_reason"] is None
    assert_status(read_run(api, ctx["run_id"]), RUN_SCHEDULED, "production run")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=1066980
    )


def test_scheduling_a_run_for_a_suspended_item_is_rejected(api):
    """Suspending the supplier suspends the item, and that outranks every later check.

    PRD 3.7: "The item's `quality_posture` must not be `SUSPENDED`, or the request
    is refused with `ERR_ITEM_QUALITY_SUSPENDED` (HTTP 422)."

    PRD 2.9: "item quality suspension; awarded-supplier qualification; GFSI
    certificate validity"

    Design: Corner/validations/run_schedule_for_suspended_item_rejected
    """
    ctx = build_chain(api, upto=25)
    suspend_supplier(api, ctx["supplier_id"])

    response = api.create_production_run(
        f.production_run_payload(
            ctx["item_id"], ctx["specification_id"], ctx["plant_line_id"]
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ITEM_QUALITY_SUSPENDED.value, 422)

    item = read_item(api, ctx["item_id"])
    assert item["quality_posture"] == POSTURE_SUSPENDED
    assert item["development_status"] == ITEM_SPEC_LOCKED
    assert (
        read_supplier(api, ctx["supplier_id"])["qualification_status"]
        == SUPPLIER_SUSPENDED
    )
    _rows, meta = _runs_for(api, ctx["item_id"])
    assert meta["total_count"] == 0
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )
