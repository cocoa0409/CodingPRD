"""Read endpoints answering exactly the slice their filters name.

The plant's read side is where the contract's ordering rules, pagination
counters and derived views are visible: the logical clock decides what every
stamped instant says, a run list separates two independent state dimensions,
the consumption junction is walkable from either end, and the recall view is
recomputed on every read rather than served from what was true at close.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    RECEIVING_CLERK_HEADERS,
    SHIPPING_CLERK_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_TECH_B,
)

FIRST_VERSION = 1

# The two rows that straddle the first clock move.
EPOCH_PROBE_CODE = "EPOCH-1"
EPOCH_PROBE_NAME = "Epoch Probe"
LATE_LINE_CODE = "LX"


def test_the_untouched_clock_reads_the_epoch_and_a_set_rewrites_nothing(api):
    """A product written before the first set keeps the epoch after it.

    PRD: Before that capability is ever called, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it only ever moves forward within a given session.
    PRD: Setting the clock changes no stored row; it changes what every subsequent creation, mutation and window evaluation observes as "now".
    PRD: `version`, an integer that begins at 1 and increases by exactly 1 on every mutation of that row.

    Design: Corner/endpoints/corner_logical_clock_drives_every_system_timestamp
    """
    probe = fx.create_product(api, code=EPOCH_PROBE_CODE, name=EPOCH_PROBE_NAME)
    a.assert_common_fields(probe, "product")
    a.assert_created_equals_updated(probe, "product")
    a.assert_instant_equals(probe["created_at"], c.EPOCH_CLOCK_CANONICAL, "created_at")
    a.assert_instant_equals(probe["updated_at"], c.EPOCH_CLOCK_CANONICAL, "updated_at")
    a.assert_version_is(probe, FIRST_VERSION, "product")

    moved = a.assert_object_envelope(
        api.set_clock(f.clock_payload(c.CLOCK_MASTER_DATA), PLANT_ADMIN_HEADERS)
    )
    a.assert_instant_equals(moved["current_utc"], c.CLOCK_MASTER_DATA, "current_utc")

    # A row written after the move reads the new logical instant.
    line = fx.create_line(api, line_code=LATE_LINE_CODE)
    a.assert_instant_equals(line["created_at"], c.CLOCK_MASTER_DATA, "created_at")
    a.assert_created_equals_updated(line, "line")

    # The move stored nothing on the product and bumped no version.
    unchanged = get_success_data(api.get_product(probe["id"], PLANT_ADMIN_HEADERS))
    a.assert_instant_equals(
        unchanged["created_at"], c.EPOCH_CLOCK_CANONICAL, "created_at"
    )
    a.assert_instant_equals(
        unchanged["updated_at"], c.EPOCH_CLOCK_CANONICAL, "updated_at"
    )
    a.assert_version_is(unchanged, FIRST_VERSION, "product")


# The two further runs planned on the standing line for the following days.
RUN_B_START_AT = "2026-08-04T07:00:00Z"
RUN_B_END_AT = "2026-08-04T12:00:00Z"
RUN_C_START_AT = "2026-08-05T07:00:00Z"
RUN_C_END_AT = "2026-08-05T12:00:00Z"
SETUP_RUN_COUNT = 2
ONE_RUN = 1
ONE_ROW_PER_PAGE = 1
FIRST_PAGE_OFFSET = 0
SECOND_PAGE_OFFSET = 1


def test_the_run_list_filters_each_state_dimension_and_pages_inside_the_filter(api):
    """CLOSED finds one run, HELD finds the same one, SETUP pages through two.

    PRD: A **processing run** is the unit of production, and it carries two state dimensions that advance independently of each other.
    PRD: The new run begins with `run_status` of `SETUP` and `disposition_status` of `UNRESTRICTED`, and `started_at`, `closed_at`, `target_ppm_at_start` and `required_dwell_seconds_at_start` all null.
    PRD: and processing runs by `line_id`, `product_id`, `customer_spec_id`, `wash_system_id`, `rework_source_run_id`, `run_status` and `disposition_status`.
    PRD: The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied.

    Design: Corner/endpoints/corner_run_list_filters_on_both_state_dimensions
    """
    world = fx.closed_world(api)

    planned = []
    for start_at, end_at in (
        (RUN_B_START_AT, RUN_B_END_AT),
        (RUN_C_START_AT, RUN_C_END_AT),
    ):
        run = fx.plan_run(
            api,
            world.line_id,
            world.product_id,
            world.spec_id,
            world.wash_system_id,
            planned_start_at=start_at,
            planned_end_at=end_at,
        )
        assert run["run_status"] == c.RUN_SETUP
        assert run["disposition_status"] == c.DISPOSITION_UNRESTRICTED
        planned.append(run["id"])

    closed = a.assert_page(
        api.list_process_runs(QA_MANAGER_HEADERS, {"run_status": c.RUN_CLOSED}),
        expected_total=ONE_RUN,
        expected_has_more=False,
        expected_count=ONE_RUN,
    )
    assert closed[0]["id"] == world.run_id
    assert closed[0]["disposition_status"] == c.DISPOSITION_HELD

    # The quality dimension alone finds the same single run.
    held = a.assert_page(
        api.list_process_runs(
            QA_MANAGER_HEADERS, {"disposition_status": c.DISPOSITION_HELD}
        ),
        expected_total=ONE_RUN,
        expected_count=ONE_RUN,
    )
    assert held[0]["id"] == world.run_id

    first_page = a.assert_page(
        api.list_process_runs(
            QA_MANAGER_HEADERS,
            {
                "run_status": c.RUN_SETUP,
                "limit": ONE_ROW_PER_PAGE,
                "offset": FIRST_PAGE_OFFSET,
            },
        ),
        expected_total=SETUP_RUN_COUNT,
        expected_has_more=True,
        expected_count=ONE_ROW_PER_PAGE,
        expected_limit=ONE_ROW_PER_PAGE,
        expected_offset=FIRST_PAGE_OFFSET,
    )
    second_page = a.assert_page(
        api.list_process_runs(
            QA_MANAGER_HEADERS,
            {
                "run_status": c.RUN_SETUP,
                "limit": ONE_ROW_PER_PAGE,
                "offset": SECOND_PAGE_OFFSET,
            },
        ),
        expected_total=SETUP_RUN_COUNT,
        expected_has_more=False,
        expected_count=ONE_ROW_PER_PAGE,
        expected_offset=SECOND_PAGE_OFFSET,
    )
    assert first_page[0]["run_status"] == c.RUN_SETUP
    assert first_page[0]["id"] != second_page[0]["id"], (
        "the two pages walk the filtered rows rather than repeating one"
    )
    assert {first_page[0]["id"], second_page[0]["id"]} == set(planned)

    # Two filters combined, read by a role that only ships.
    unrestricted = a.assert_page(
        api.list_process_runs(
            SHIPPING_CLERK_HEADERS,
            {
                "line_id": world.line_id,
                "disposition_status": c.DISPOSITION_UNRESTRICTED,
            },
        ),
        expected_total=SETUP_RUN_COUNT,
        expected_has_more=False,
        expected_count=SETUP_RUN_COUNT,
    )
    a.assert_row_ids(unrestricted, planned)

    a.assert_empty_page(
        api.list_process_runs(QA_MANAGER_HEADERS, {"run_status": c.RUN_RUNNING})
    )


# The second, smaller draw on the same load, recorded and then voided.
SECOND_DRAW_LB = 1000.00
JUNCTION_ROW_COUNT = 2
ONE_JUNCTION_ROW = 1
REMAINING_AFTER_FIRST_DRAW_LB = c.RECEIPT_ACCEPTED_LB - c.CONSUMED_LB


def test_the_junction_lists_the_same_two_rows_from_the_run_and_the_load(api):
    """One active draw and one voided draw, reachable from either end.

    PRD: Raw pounds reach a run through **lot consumption** records, which form the many-to-many join between runs and received loads and are the backbone of traceability in both directions.
    PRD: From that moment the voided row is invisible to every aggregate in this document: it contributes no pounds to either balance, no organic load to the flume, no temperature grade to the shelf-life calculation and no harvest date to the harvest-lag calculation — though the row itself remains readable as part of the audit trail, and the consumption listings on both the run side and the load side will still return it when the `status` filter permits.
    PRD: lot consumptions, whether viewed from the run side or from the receipt side, by `status`
    PRD: the loads received against a grower lot by `status` and `temp_grade`

    Design: Corner/endpoints/corner_consumption_junction_lists_from_both_sides
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_CONSUMED)

    before_second = fx.read_run(api, world.run_id)
    second = fx.consume(
        api,
        world.run_id,
        world.receipt_id,
        before_second["version"],
        consumed_lb=SECOND_DRAW_LB,
    )
    after_second = fx.read_run(api, world.run_id)
    voided = fx.void_consumption(api, second["id"], after_second["version"])
    assert voided["status"] == c.CONSUMPTION_VOIDED

    run_side = a.assert_page(
        api.list_run_lot_consumptions(world.run_id, QA_TECHNICIAN_HEADERS),
        expected_total=JUNCTION_ROW_COUNT,
        expected_has_more=False,
        expected_count=JUNCTION_ROW_COUNT,
    )
    a.assert_row_ids(run_side, [world.consumption_id, second["id"]])
    for row in run_side:
        assert row["raw_receipt_id"] == world.receipt_id
        assert row["process_run_id"] == world.run_id

    receipt_side = a.assert_page(
        api.list_receipt_lot_consumptions(world.receipt_id, QA_TECHNICIAN_HEADERS),
        expected_total=JUNCTION_ROW_COUNT,
        expected_count=JUNCTION_ROW_COUNT,
    )
    a.assert_row_ids(receipt_side, [world.consumption_id, second["id"]])

    # The status filter separates the two rows, from either side of the join.
    active = a.assert_page(
        api.list_run_lot_consumptions(
            world.run_id, QA_TECHNICIAN_HEADERS, {"status": c.CONSUMPTION_ACTIVE}
        ),
        expected_total=ONE_JUNCTION_ROW,
        expected_count=ONE_JUNCTION_ROW,
    )
    assert active[0]["id"] == world.consumption_id
    assert active[0]["consumed_lb"] == c.CONSUMED_LB

    hidden = a.assert_page(
        api.list_receipt_lot_consumptions(
            world.receipt_id, QA_TECHNICIAN_HEADERS, {"status": c.CONSUMPTION_VOIDED}
        ),
        expected_total=ONE_JUNCTION_ROW,
        expected_count=ONE_JUNCTION_ROW,
    )
    assert hidden[0]["id"] == second["id"]
    assert hidden[0]["consumed_lb"] == SECOND_DRAW_LB
    a.assert_instant_equals(hidden[0]["voided_at"], c.CLOCK_START, "voided_at")

    # The load's own list answers to the temperature grade it was given.
    in_spec = a.assert_page(
        api.list_lot_raw_receipts(
            world.grower_lot_id, RECEIVING_CLERK_HEADERS, {"temp_grade": c.TEMP_IN_SPEC}
        ),
        expected_total=ONE_JUNCTION_ROW,
        expected_count=ONE_JUNCTION_ROW,
    )
    assert in_spec[0]["id"] == world.receipt_id
    assert in_spec[0]["temp_grade"] == c.TEMP_IN_SPEC
    assert in_spec[0]["remaining_lb"] == REMAINING_AFTER_FIRST_DRAW_LB, (
        "the void gave back its thousand pounds exactly"
    )

    a.assert_empty_page(
        api.list_lot_raw_receipts(
            world.grower_lot_id,
            RECEIVING_CLERK_HEADERS,
            {"temp_grade": c.TEMP_OUT_OF_SPEC},
        )
    )


# The chain behind the standing run: one lot, one load, one active draw.
ONE_LOT = 1
ONE_ACTIVE_CONSUMPTION = 1
NO_VOIDED_CONSUMPTIONS = 0
NO_CASES = 0
ONE_CASE_SHIPPED = 1


def test_the_recall_view_is_recomputed_on_every_read(api):
    """The tally and the code date both move when the hold clears and a case ships.

    PRD: It returns the run's own `process_run_id`, the `product_code` of the product it packed and the `customer_code` of the specification it packed to, the identifiers and grower codes of every lot that fed it as `grower_lot_ids` and `grower_codes`, the `raw_receipt_ids` of every load drawn, the `active_consumption_count` and `voided_consumption_count` of its consumption records, the `case_count` of cases it produced together with the `shipped_case_count`, `on_hold_case_count` and `destroyed_case_count` breakdown, the `effective_code_date` currently in force on the run's product, and the rework ancestry as the immediate `rework_source_run_id` plus the full chain of `rework_ancestor_run_ids`.
    PRD: The results are written to `final_shelf_life_days` and `final_code_date`, and because both changes can only shorten the window, the final code date is never later than the provisional one.
    PRD: A successful shipment stamps `shipped_at` from the logical clock, decrements the run's `cases_available`, increments its `cases_shipped`, and increments the case's `version` by 1.

    Design: Corner/endpoints/corner_traceability_read_recomputes_the_whole_chain
    """
    world = fx.closed_world(api)
    held_run = fx.read_run(api, world.run_id)
    assert held_run["provisional_code_date"] == c.BASE_PROVISIONAL_CODE_DATE
    assert held_run["final_code_date"] is None

    trace = fx.read_traceability(api, world.run_id, QA_MANAGER_HEADERS)
    assert trace["process_run_id"] == world.run_id
    assert trace["product_code"] == c.PRODUCT_CODE
    assert trace["customer_code"] == c.SPEC_CUSTOMER_CODE
    assert trace["grower_lot_ids"] == [world.grower_lot_id]
    assert trace["grower_codes"] == [c.GROWER_CODE]
    assert trace["raw_receipt_ids"] == [world.receipt_id]
    assert len(trace["grower_lot_ids"]) == ONE_LOT, "one hop back reaches one lot only"
    assert trace["active_consumption_count"] == ONE_ACTIVE_CONSUMPTION
    assert trace["voided_consumption_count"] == NO_VOIDED_CONSUMPTIONS
    assert trace["case_count"] == c.CLOSE_CASES_PRODUCED
    assert trace["shipped_case_count"] == NO_CASES
    assert trace["on_hold_case_count"] == c.CLOSE_CASES_PRODUCED
    assert trace["destroyed_case_count"] == NO_CASES
    # No final code date exists yet, so the provisional one is in force.
    a.assert_calendar_date(trace["effective_code_date"], "effective_code_date")
    assert trace["effective_code_date"] == c.BASE_PROVISIONAL_CODE_DATE
    # A first-generation run reports an empty ancestry rather than omitting it.
    assert trace["rework_source_run_id"] is None
    assert trace["rework_ancestor_run_ids"] == []

    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )
    released_run = fx.read_run(api, world.run_id)
    assert released_run["final_code_date"] == c.FINAL_CODE_DATE_LOW_APC

    first_case = fx.list_cases(api, world.run_id, {"limit": ONE_CASE_SHIPPED})[0]
    assert fx.ship_case(api, first_case["id"])["status"] == c.CASE_SHIPPED

    recomputed = fx.read_traceability(api, world.run_id, QA_TECHNICIAN_HEADERS)
    assert recomputed["case_count"] == c.CLOSE_CASES_PRODUCED
    assert recomputed["shipped_case_count"] == ONE_CASE_SHIPPED
    assert recomputed["on_hold_case_count"] == NO_CASES
    assert recomputed["destroyed_case_count"] == NO_CASES
    assert recomputed["active_consumption_count"] == ONE_ACTIVE_CONSUMPTION
    assert recomputed["effective_code_date"] == c.FINAL_CODE_DATE_LOW_APC, (
        "the view reports the code date now in force, not the one it first read"
    )


# The three pages the pack is read through, and the codes on their edges.
HEAD_PAGE_SIZE = 3
TAIL_PAGE_SIZE = 2
TAIL_PAGE_OFFSET = 898
FIRST_THREE_SEQUENCES = (1, 2, 3)
TAIL_SEQUENCES = (899, 900)
SECOND_CASE_CODE = "L1-20260803-0002"
THIRD_CASE_CODE = "L1-20260803-0003"
ONE_EXTRA_CENT = 1


def test_the_case_page_is_sequence_ordered_and_allocates_every_cent(api):
    """Offset 898 reaches cases 899 and 900, and the pack sums to the run total.

    PRD: Finished cases are returned in `case_sequence` ascending order, which is the pack order.
    PRD: Each case carries `process_run_id`, a `case_code` composed of the line's `line_code`, a hyphen, the pack date rendered as eight digits in year-month-day order, another hyphen, and the case's `case_sequence` zero-padded to four digits — where the pack date is the UTC calendar date of the run's `started_at`.
    PRD: Each case copies the specification's `case_net_weight_lb` into its own `net_weight_lb`, receives the run's `provisional_code_date` as its `code_date`, and receives a `code_date_label` rendering that code date in the format the specification's `code_date_format` demands: for `CALENDAR`, the ISO form `YYYY-MM-DD`; for `JULIAN`, a seven-character string of the four-digit year followed by the zero-padded three-digit day of the year.
    PRD: `per_case_cost_cents` is the total divided by `cases_produced` with any fraction discarded, `cost_remainder_cents` is the total less the per-case figure multiplied by the case count, and the remainder is distributed as a waterfall over `case_sequence` ascending — each case whose `case_sequence` is less than or equal to `cost_remainder_cents` receives `per_case_cost_cents` plus one cent in its `allocated_cost_cents`, and every other case receives exactly `per_case_cost_cents`.
    PRD: The sum of `allocated_cost_cents` across the run's cases therefore equals `total_run_cost_cents` exactly.
    PRD: When the product's `hold_and_release_required` is true, the close opens a hold record with `reason` of `HOLD_AND_RELEASE_TESTING`, moves the run's disposition `UNRESTRICTED → HELD`, and moves every newly created case `IN_INVENTORY → ON_HOLD`.

    Design: Corner/endpoints/corner_finished_case_page_is_sequence_ordered_and_cost_complete
    """
    world = fx.closed_world(api)
    run = fx.read_run(api, world.run_id)
    a.assert_cost_totals(
        run,
        total_run_cost_cents=c.BASE_TOTAL_RUN_COST_CENTS,
        per_case_cost_cents=c.BASE_PER_CASE_COST_CENTS,
        cost_remainder_cents=c.BASE_COST_REMAINDER_CENTS,
    )

    head = a.assert_page(
        api.list_finished_cases(
            world.run_id,
            LINE_OPERATOR_HEADERS,
            {"limit": HEAD_PAGE_SIZE, "offset": FIRST_PAGE_OFFSET},
        ),
        expected_total=c.CLOSE_CASES_PRODUCED,
        expected_has_more=True,
        expected_count=HEAD_PAGE_SIZE,
    )
    a.assert_field_sequence(head, "case_sequence", FIRST_THREE_SEQUENCES)
    a.assert_field_sequence(
        head,
        "case_code",
        (c.BASE_FIRST_CASE_CODE, SECOND_CASE_CODE, THIRD_CASE_CODE),
    )
    first_case = head[0]
    assert first_case["code_date"] == c.BASE_PROVISIONAL_CODE_DATE
    assert first_case["code_date_label"] == c.BASE_PROVISIONAL_JULIAN_LABEL
    assert first_case["net_weight_lb"] == c.SPEC_CASE_NET_WEIGHT_LB
    assert first_case["status"] == c.CASE_ON_HOLD
    assert first_case["process_run_id"] == world.run_id
    assert (
        first_case["allocated_cost_cents"]
        == run["per_case_cost_cents"] + ONE_EXTRA_CENT
    ), "sequence 1 is inside the remainder, so it carries the extra cent"

    tail = a.assert_page(
        api.list_finished_cases(
            world.run_id,
            LINE_OPERATOR_HEADERS,
            {"limit": TAIL_PAGE_SIZE, "offset": TAIL_PAGE_OFFSET},
        ),
        expected_total=c.CLOSE_CASES_PRODUCED,
        expected_has_more=False,
        expected_count=TAIL_PAGE_SIZE,
    )
    a.assert_field_sequence(tail, "case_sequence", TAIL_SEQUENCES)
    assert tail[-1]["case_code"] == c.BASE_LAST_CASE_CODE
    assert tail[-1]["allocated_cost_cents"] == run["per_case_cost_cents"], (
        "sequence 900 is past the remainder, so it carries the floored share"
    )

    every_case = fx.all_cases(api, world.run_id, c.CLOSE_CASES_PRODUCED)
    assert len(every_case) == c.CLOSE_CASES_PRODUCED
    a.assert_ordered_by(every_case, "case_sequence")
    a.assert_cost_waterfall(
        every_case, run["total_run_cost_cents"], run["per_case_cost_cents"]
    )
    assert (
        sum(case["allocated_cost_cents"] for case in every_case)
        == run["total_run_cost_cents"]
    ), "not one cent is invented or lost across the pack"

    a.assert_empty_page(
        api.list_finished_cases(
            world.run_id, LINE_OPERATOR_HEADERS, {"status": c.CASE_IN_INVENTORY}
        )
    )
