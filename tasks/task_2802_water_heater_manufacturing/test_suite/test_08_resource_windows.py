"""Half-open interval arithmetic on two shared plant resources.

A furnace admits exactly one batch at a time but treats touching endpoints as
free, and a test cell counts overlapping windows against its slots while
separately enforcing a per-model recovery tail that no overlap test can see.
"""

from test_helpers import (
    compliance_engineer_headers,
    data_of,
    efficiency_test_payload,
    ERR_FURNACE_WINDOW_CONFLICT,
    ERR_TEST_CELL_CAPACITY_CONFLICT,
    ERR_TEST_CELL_COOLDOWN_VIOLATION,
    furnace_payload,
    heat_pump_model_payload,
    large_gas_model_payload,
    lining_batch_payload,
    make_model,
    make_test_cell,
    plant_admin_headers,
    plant_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The window the setup batch already occupies on the first furnace.
OCCUPIED = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
#: Straddles the occupied window's exclusive end.
STRADDLES_THE_END = ("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
#: Begins exactly where the occupied window ends.
ABUTS_AFTER = ("2026-08-02T10:00:00Z", "2026-08-02T14:00:00Z")
#: Ends exactly where the occupied window begins.
ABUTS_BEFORE = ("2026-08-02T05:00:00Z", "2026-08-02T06:00:00Z")


def _two_furnaces_with_one_occupied_window(api):
    """Two identical furnaces, the first already carrying a mixed batch.

    The batch sits in `MIXED` because its firing window has not elapsed under the
    service clock, so it counts as a non-terminal occupation of that furnace.
    """
    first = data_of(
        api.create_furnace(furnace_payload(), plant_admin_headers())
    )
    second = data_of(
        api.create_furnace(
            furnace_payload(furnace_code="FURN-B"), plant_admin_headers()
        )
    )
    occupying = data_of(
        api.create_lining_batch(
            lining_batch_payload(first["id"], window=OCCUPIED, batch_code="GLB-A1"),
            plant_operator_headers(),
        )
    )
    return first["id"], second["id"], occupying


def _book(api, furnace_id, window, batch_code):
    """Attempt one batch booking, returning the raw response."""
    return api.create_lining_batch(
        lining_batch_payload(furnace_id, window=window, batch_code=batch_code),
        plant_operator_headers(),
    )


class TestFurnaceWindowExclusivity:
    """One furnace, one occupant - but touching endpoints are not occupancy."""

    def test_01_a_window_straddling_the_exclusive_end_is_refused(self, api):
        """Three hours of genuine overlap is an exclusivity breach.

        PRD: "Booking a window that does overlap any other non-terminal batch
        window — that is, any batch on the same furnace still in `MIXED` or `FIRED` —
        is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_exclusive_half_open_adjacency_allowed
        """
        furnace_a, _furnace_b, _occupying = _two_furnaces_with_one_occupied_window(api)

        response = _book(api, furnace_a, STRADDLES_THE_END, "GLB-A2")

        validate_error(response, ERR_FURNACE_WINDOW_CONFLICT, expected_status=409)

    def test_02_a_window_beginning_at_the_occupant_s_end_is_accepted(self, api):
        """The exclusive endpoint belongs to nobody, so 10:00 is free.

        PRD: "The interval is **half-open**: `firing_start` is inclusive and
        `firing_end` is exclusive, so a window that begins exactly at another window's
        `firing_end` is not an overlap and is accepted."

        Design: Difficulty/resource_temporal_overlap/furnace_window_exclusive_half_open_adjacency_allowed
        """
        furnace_a, _furnace_b, _occupying = _two_furnaces_with_one_occupied_window(api)

        booked = data_of(_book(api, furnace_a, ABUTS_AFTER, "GLB-A3"))

        assert booked["status"] == "MIXED"
        assert booked["firing_start"].startswith("2026-08-02T10:00:00")

    def test_03_a_window_ending_at_the_occupant_s_start_is_accepted(self, api):
        """The mirror adjacency: an hour that stops exactly where 06:00 begins.

        PRD: "The interval is **half-open**: `firing_start` is inclusive and
        `firing_end` is exclusive, so a window that begins exactly at another window's
        `firing_end` is not an overlap and is accepted."

        Design: Difficulty/resource_temporal_overlap/furnace_window_exclusive_half_open_adjacency_allowed
        """
        furnace_a, _furnace_b, _occupying = _two_furnaces_with_one_occupied_window(api)

        booked = data_of(_book(api, furnace_a, ABUTS_BEFORE, "GLB-A4"))

        assert booked["status"] == "MIXED"
        assert booked["firing_end"].startswith("2026-08-02T06:00:00")

    def test_04_the_identical_window_on_another_furnace_is_accepted(self, api):
        """Exclusivity is scoped to one asset, not to the plant calendar.

        PRD: "Booking a window that does overlap any other non-terminal batch
        window — that is, any batch on the same furnace still in `MIXED` or `FIRED` —
        is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_exclusive_half_open_adjacency_allowed
        """
        _furnace_a, furnace_b, _occupying = _two_furnaces_with_one_occupied_window(api)

        booked = data_of(_book(api, furnace_b, OCCUPIED, "GLB-B1"))

        assert booked["status"] == "MIXED"
        assert booked["firing_start"].startswith("2026-08-02T06:00:00")

    def test_05_each_furnace_counts_only_the_windows_booked_on_itself(self, api):
        """Three accepted occupations on the first furnace, one on the second.

        PRD: "A furnace read reports `occupied_window_count`, derived as the number
        of glass-lining batches booked on that furnace whose `status` is `MIXED` or
        `FIRED`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_exclusive_half_open_adjacency_allowed
        """
        furnace_a, furnace_b, occupying = _two_furnaces_with_one_occupied_window(api)

        _book(api, furnace_a, STRADDLES_THE_END, "GLB-A2")
        data_of(_book(api, furnace_a, ABUTS_AFTER, "GLB-A3"))
        data_of(_book(api, furnace_a, ABUTS_BEFORE, "GLB-A4"))
        data_of(_book(api, furnace_b, OCCUPIED, "GLB-B1"))

        first = validate_success(api.get_furnace(furnace_a, plant_admin_headers()))
        second = validate_success(api.get_furnace(furnace_b, plant_admin_headers()))
        untouched = validate_success(
            api.get_lining_batch(occupying["id"], plant_operator_headers())
        )

        assert first["occupied_window_count"] == 3
        assert second["occupied_window_count"] == 1
        assert untouched["status"] == "MIXED"
        assert untouched["firing_start"] == occupying["firing_start"]
        assert untouched["firing_end"] == occupying["firing_end"]


#: Fully contained inside both occupied cell windows.
CONTAINED_IN_BOTH = ("2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z")
#: Overlaps nothing, but only two hours after the first model's window ended.
TWO_HOURS_AFTER = ("2026-08-02T12:00:00Z", "2026-08-02T16:00:00Z")
#: Overlaps nothing and sits exactly twelve hours after that same end.
TWELVE_HOURS_AFTER = ("2026-08-02T22:00:00Z", "2026-08-03T02:00:00Z")


def _cell_with_both_slots_busy_from_six_to_eleven(api):
    """One two-slot cell already running two different models, plus two spare models.

    The first model's window runs 06:00-10:00 and the second's 07:00-11:00, so
    every instant between 07:00 and 10:00 has both slots in use while the whole
    span is still a single window for neither model.
    """
    trade_gas = make_model(api)["id"]
    heat_pump = make_model(api, heat_pump_model_payload())["id"]
    retail_gas = make_model(api, large_gas_model_payload())["id"]
    cell = make_test_cell(api)["id"]
    make_test_cell(api, cell_code="CELL-2", parallel_slots=1, cooldown_hours=6)
    first = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(
                trade_gas, cell, window=("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
            ),
            compliance_engineer_headers(),
        )
    )
    second = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(
                heat_pump,
                cell,
                window=("2026-08-02T07:00:00Z", "2026-08-02T11:00:00Z"),
                sample_size=2,
            ),
            compliance_engineer_headers(),
        )
    )
    models = {"trade_gas": trade_gas, "heat_pump": heat_pump, "retail_gas": retail_gas}
    return models, cell, first, second


class TestTestCellSlotsAndCooldown:
    """Two constraints on one booking: concurrent slots, and a per-model tail."""

    def test_06_a_fully_contained_window_still_exhausts_the_slots(self, api):
        """A single hour inside both occupied windows is a third concurrent test.

        PRD: "Two cell constraints are checked together, ahead of the
        window-orientation check: the requested window must leave a free slot, meaning
        the number of non-terminal tests on that cell whose windows overlap the
        requested one must stay within `parallel_slots`, or the booking is refused with
        `ERR_TEST_CELL_CAPACITY_CONFLICT`; and the requested `window_start` must be at
        least `cooldown_hours` after the end of that cell's previous window for the
        **same** product model, or the booking is refused with
        `ERR_TEST_CELL_COOLDOWN_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/test_cell_parallel_slots_plus_cooldown_buffer
        """
        models, cell, _first, _second = _cell_with_both_slots_busy_from_six_to_eleven(api)

        response = api.create_efficiency_test(
            efficiency_test_payload(
                models["retail_gas"], cell, window=CONTAINED_IN_BOTH
            ),
            compliance_engineer_headers(),
        )

        validate_error(response, ERR_TEST_CELL_CAPACITY_CONFLICT, expected_status=409)

    def test_07_a_window_overlapping_nothing_can_still_break_the_cooldown(self, api):
        """Two hours after its own model's window ends is inside the recovery tail.

        PRD: "A `PlantAdmin` registers one with a plant-unique `cell_code` (non-empty,
        at most 20 characters, colliding as `ERR_DUPLICATE_CODE`), a `parallel_slots` count
        between 1 and 8 inclusive stating how many test windows the cell may run overlapping
        at one instant, and a `cooldown_hours` value between 0 and 72 inclusive giving the
        mandatory thermal recovery buffer the cell needs between two tests of the **same**
        product model."

        Design: Difficulty/resource_temporal_overlap/test_cell_parallel_slots_plus_cooldown_buffer
        """
        models, cell, _first, _second = _cell_with_both_slots_busy_from_six_to_eleven(api)

        response = api.create_efficiency_test(
            efficiency_test_payload(
                models["trade_gas"],
                cell,
                window=TWO_HOURS_AFTER,
                test_type="FIRST_HOUR_RATING",
            ),
            compliance_engineer_headers(),
        )

        validate_error(response, ERR_TEST_CELL_COOLDOWN_VIOLATION, expected_status=409)

    def test_08_the_same_rejected_window_is_free_for_a_different_model(self, api):
        """The recovery tail follows the model, while the slot count does not.

        PRD: "Two cell constraints are checked together, ahead of the
        window-orientation check: the requested window must leave a free slot, meaning
        the number of non-terminal tests on that cell whose windows overlap the
        requested one must stay within `parallel_slots`, or the booking is refused with
        `ERR_TEST_CELL_CAPACITY_CONFLICT`; and the requested `window_start` must be at
        least `cooldown_hours` after the end of that cell's previous window for the
        **same** product model, or the booking is refused with
        `ERR_TEST_CELL_COOLDOWN_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/test_cell_parallel_slots_plus_cooldown_buffer
        """
        models, cell, _first, _second = _cell_with_both_slots_busy_from_six_to_eleven(api)

        booked = data_of(
            api.create_efficiency_test(
                efficiency_test_payload(
                    models["retail_gas"],
                    cell,
                    window=TWO_HOURS_AFTER,
                    test_type="FIRST_HOUR_RATING",
                ),
                compliance_engineer_headers(),
            )
        )

        assert booked["status"] == "SCHEDULED"
        assert booked["product_model_id"] == models["retail_gas"]
        assert booked["test_type"] == "FIRST_HOUR_RATING"

    def test_09_a_start_exactly_one_cooldown_after_the_end_is_accepted(self, api):
        """Twelve hours after a 10:00 end satisfies a twelve-hour buffer.

        PRD: "Every scheduled test starts at `status` `SCHEDULED` with
        `measured_value`, `effective_minimum`, `margin` and `recorded_at` all null."

        Design: Difficulty/resource_temporal_overlap/test_cell_parallel_slots_plus_cooldown_buffer
        """
        models, cell, _first, _second = _cell_with_both_slots_busy_from_six_to_eleven(api)

        booked = data_of(
            api.create_efficiency_test(
                efficiency_test_payload(
                    models["trade_gas"],
                    cell,
                    window=TWELVE_HOURS_AFTER,
                    test_type="FIRST_HOUR_RATING",
                ),
                compliance_engineer_headers(),
            )
        )

        assert booked["status"] == "SCHEDULED"
        assert booked["measured_value"] is None
        assert booked["effective_minimum"] is None
        assert booked["margin"] is None
        assert booked["recorded_at"] is None

    def test_10_neither_refused_booking_leaves_a_row_behind(self, api):
        """The cell still holds exactly the two windows it started with.

        PRD: "Every scheduled test starts at `status` `SCHEDULED` with
        `measured_value`, `effective_minimum`, `margin` and `recorded_at` all null."

        Design: Difficulty/resource_temporal_overlap/test_cell_parallel_slots_plus_cooldown_buffer
        """
        models, cell, first, second = _cell_with_both_slots_busy_from_six_to_eleven(api)

        api.create_efficiency_test(
            efficiency_test_payload(models["retail_gas"], cell, window=CONTAINED_IN_BOTH),
            compliance_engineer_headers(),
        )
        api.create_efficiency_test(
            efficiency_test_payload(
                models["trade_gas"],
                cell,
                window=TWO_HOURS_AFTER,
                test_type="FIRST_HOUR_RATING",
            ),
            compliance_engineer_headers(),
        )

        rows, _meta = validate_paginated(
            api.list_efficiency_tests(
                compliance_engineer_headers(), {"limit": 100, "offset": 0}
            )
        )

        assert len(rows) == 2
        for row, original in zip(rows, (first, second)):
            assert row["status"] == "SCHEDULED"
            assert row["window_start"] == original["window_start"]
            assert row["window_end"] == original["window_end"]
