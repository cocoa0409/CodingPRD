"""A test design may not consume more names than its line actually won.

Every individual quantity below is trivially small; only the running sum crosses
the line's allocation, so the cap has to be evaluated as an aggregate over the cells
already on the line. Two of the refused calls violate two rules at once, and the
answer must come from the higher-priority rule: a second CONTROL cell that would also
overflow reports the duplicate control, and a reused cell_code outranks both.
"""
from test_helpers import (
    ANALYST,
    assert_test_cell,
    create_test_cell_payload,
    fetch_line,
    new_test_cell,
    setup_allocated_line_for_test_cells,
    setup_clock_at_start,
    validate_error,
    validate_paginated,
    validate_success,
)


def _a_line_of_ten_thousand_with_nine_thousand_designed() -> dict:
    """C_CTRL (CONTROL, 4000) then C_T1 (TEST, 5000) leave exactly 1000 of the
    line's 10000 allocated names unassigned."""
    setup_clock_at_start()
    world = setup_allocated_line_for_test_cells(requested_quantity=10000)
    line_id = world["line"]["id"]
    world["control"] = new_test_cell(
        line_id, 4000, "CONTROL", cell_code="C_CTRL", test_type="OFFER"
    )
    world["first_test"] = new_test_cell(
        line_id, 5000, "TEST", cell_code="C_T1", test_type="OFFER"
    )
    return world


class TestTheCapIsAnAggregateOverTheLine:
    def test_a_thousand_and_one_more_names_overflow_the_allocation(self, api):
        """PRD §3.9: "The names a test design consumes cannot exceed the names the
        line actually won: the sum of `quantity` across all of a line's cells may not
        exceed that line's `allocated_quantity`, and a breach is rejected with
        `ERR_TEST_CELL_QUANTITY_EXCEEDS_LINE`."

        Design: Corner/validations/test_cell_quantities_are_capped_per_line_and_extra_cells_rejected
        """
        world = _a_line_of_ten_thousand_with_nine_thousand_designed()
        line = fetch_line(world["line"]["id"])
        assert line["allocated_quantity"] == 10000

        response = api.create_test_cell(
            line["id"],
            create_test_cell_payload(1001, "TEST", cell_code="C_T2"),
            ANALYST,
        )
        validate_error(response, "ERR_TEST_CELL_QUANTITY_EXCEEDS_LINE", 422)

        _, meta = validate_paginated(api.list_test_cells(line["id"], ANALYST))
        assert meta["total_count"] == 2

    def test_a_sum_landing_exactly_on_the_allocation_is_permitted(self, api):
        """PRD §3.9: "A new cell lands in status `PLANNED` with `significance`
        `UNMEASURED` and with `responders`, `demand_cents`, `response_rate_bps` and
        `lift_bps` all 0."

        Design: Corner/validations/test_cell_quantities_are_capped_per_line_and_extra_cells_rejected
        """
        world = _a_line_of_ten_thousand_with_nine_thousand_designed()
        line_id = world["line"]["id"]

        cell = validate_success(
            api.create_test_cell(
                line_id,
                create_test_cell_payload(1000, "TEST", cell_code="C_T2"),
                ANALYST,
            ),
            201,
        )
        assert_test_cell(cell)
        assert cell["quantity"] == 1000
        assert cell["status"] == "PLANNED"
        assert cell["significance"] == "UNMEASURED"
        assert cell["responders"] == 0
        assert cell["demand_cents"] == 0
        assert cell["response_rate_bps"] == 0
        assert cell["lift_bps"] == 0

        rows, meta = validate_paginated(api.list_test_cells(line_id, ANALYST))
        assert meta["total_count"] == 3
        assert sum(row["quantity"] for row in rows) == 10000
        assert sum(row["quantity"] for row in rows) == fetch_line(line_id)[
            "allocated_quantity"
        ]


class TestTheRulesThatOutrankTheQuantityCap:
    def test_a_second_control_cell_reports_the_duplicate_not_the_overflow(self, api):
        """PRD §3.9: "A line may carry at most one cell whose `cell_role` is
        `CONTROL`, and a second is rejected with `ERR_DUPLICATE_CONTROL_CELL`."

        Design: Corner/validations/test_cell_quantities_are_capped_per_line_and_extra_cells_rejected
        """
        world = _a_line_of_ten_thousand_with_nine_thousand_designed()

        response = api.create_test_cell(
            world["line"]["id"],
            create_test_cell_payload(9000, "CONTROL", cell_code="C_CTRL2"),
            ANALYST,
        )
        error = validate_error(response, "ERR_DUPLICATE_CONTROL_CELL", 409)
        assert error["error_id"] != "ERR_TEST_CELL_QUANTITY_EXCEEDS_LINE"

    def test_a_reused_cell_code_outranks_both_of_the_other_guards(self, api):
        """PRD §3.9: "It carries a `cell_code` such as `OFFER_FREESHIP_T1`, unique
        within its line with a repeat rejected as `ERR_DUPLICATE_TEST_CELL_CODE`; a
        `test_type` naming what the cell varies, one of `SEGMENT`, `FORMAT` or `OFFER`;
        a `cell_role` of `TEST`, `CONTROL` or `HOLDOUT`; and a `quantity` of names
        greater than zero."

        Design: Corner/validations/test_cell_quantities_are_capped_per_line_and_extra_cells_rejected
        """
        world = _a_line_of_ten_thousand_with_nine_thousand_designed()

        response = api.create_test_cell(
            world["line"]["id"],
            create_test_cell_payload(
                9000, "TEST", cell_code="C_T1", test_type="FORMAT"
            ),
            ANALYST,
        )
        error = validate_error(response, "ERR_DUPLICATE_TEST_CELL_CODE", 409)
        assert error["error_id"] != "ERR_TEST_CELL_QUANTITY_EXCEEDS_LINE"

        _, meta = validate_paginated(
            api.list_test_cells(world["line"]["id"], ANALYST)
        )
        assert meta["total_count"] == 2
