"""Two calendars with opposite endpoint conventions, and two occupancy ceilings."""

from test_helpers import (
    PLANT,
    QUALITY,
    ApiErrorId,
    api_client,
    assert_line_ledger,
    build_slot_payload,
    commit_slot,
    create_bay,
    create_line,
    create_propulsion_package,
    electric_package_payload,
    line_version,
    mint_unit,
    plan_slot,
    quality_test_payload,
    read_line,
    read_unit,
    schedule_test,
    setup_awarded_order,
    setup_nv_catalogue,
    validate_error,
    validate_paginated,
)

# An unoptioned offer: the Nevada profile mandates no lighting, mirror or safety
# equipment, so the base body and the propulsion package are the only priced items.
BASE_BID_CONFIG = {
    "offered_seat_capacity": 71,
    "offered_emergency_exit_count": 5,
    "offered_mirror_config": "STANDARD",
    "offered_lap_shoulder_belts": False,
    "offered_eight_lamp_system": False,
    "offered_crossing_arm": False,
    "offered_rollover_reinforcement": False,
}

NEVADA_LINE = {
    "line_code": "L-C1",
    "plant_code": "PLANT-C",
    "supported_body_classes": ["TYPE_C"],
    "horizon_slot_day_capacity": 60,
    "changeover_buffer_days": 3,
}


def _plan_slot_response(line_id: str, unit_id: str, start_date: str, end_date: str,
                        expected_version: int):
    """Raw planning call, so a refusal can be inspected rather than raised."""
    return api_client.create_build_slot(
        build_slot_payload(expected_version, line_id, unit_id, start_date, end_date),
        PLANT,
    )


class TestBuildSlotWindowsAndChangeoverBuffer:
    """Build-slot windows are half-open, and a propulsion change costs idle days."""

    def _nevada_plant_with_two_orders(self) -> dict:
        """Three diesel buses and one electric bus on one Nevada line, with the
        first diesel bus already holding a planned week."""
        catalogue = setup_nv_catalogue()
        model_id = catalogue["model"]["id"]
        electric_package = create_propulsion_package(
            electric_package_payload(model_id)
        )
        diesel = setup_awarded_order(
            catalogue,
            unit_count=3,
            solicitation_overrides={
                "solicitation_code": "SOL-NV-D",
                "buyer_type": "COOPERATIVE",
                "buyer_name": "Washoe County Cooperative",
                "price_cap_cents_per_unit": 32_000_000,
            },
            bid_config=BASE_BID_CONFIG,
        )
        diesel_units = [
            mint_unit(diesel["order"]["id"], vin)
            for vin in (
                "1NVDSL0000000001",
                "1NVDSL0000000002",
                "1NVDSL0000000003",
            )
        ]
        electric = setup_awarded_order(
            dict(catalogue, package=electric_package),
            unit_count=1,
            submit_clock=None,
            award_clock=None,
            solicitation_overrides={
                "solicitation_code": "SOL-NV-E",
                "buyer_type": "COOPERATIVE",
                "buyer_name": "Clark County Cooperative",
                "price_cap_cents_per_unit": 32_000_000,
            },
            bid_config=BASE_BID_CONFIG,
        )
        electric_unit = mint_unit(electric["order"]["id"], "1NVELE0000000001")

        line = create_line(**NEVADA_LINE)
        first = plan_slot(
            line["id"], diesel_units[0]["id"], "2026-09-07", "2026-09-14"
        )
        return {
            "line": line,
            "diesel_units": diesel_units,
            "electric_unit": electric_unit,
            "first_slot": first,
        }

    def test_an_adjacent_window_is_free_but_a_shared_day_overlaps(self):
        """A slot starting on the day the previous slot's exclusive end falls is
        planned; a slot reaching back into an occupied day is refused.

        PRD: "the requested window must not overlap any slot on the same line that
        has not been released — a slot ending on the 14th and a slot starting on the
        14th do not overlap, since the end is exclusive".

        Design: Difficulty/resource_temporal_overlap/build_slot_half_open_windows_and_propulsion_changeover_buffer
        """
        plant = self._nevada_plant_with_two_orders()
        line_id = plant["line"]["id"]
        units = plant["diesel_units"]
        assert plant["first_slot"]["slot_days"] == 7
        assert plant["first_slot"]["status"] == "PLANNED"
        assert plant["first_slot"]["propulsion_type"] == "DIESEL"

        adjacent = plan_slot(line_id, units[1]["id"], "2026-09-14", "2026-09-21")
        assert adjacent["slot_days"] == 7
        assert adjacent["status"] == "PLANNED"

        version = line_version(line_id)
        refused = _plan_slot_response(
            line_id, units[2]["id"], "2026-09-20", "2026-09-27", version
        )
        validate_error(refused, ApiErrorId.ERR_SLOT_WINDOW_OVERLAP.value)

        line = read_line(line_id)
        assert line["version"] == version
        # Neither plan booked any capacity: a plan is a request, not a booking.
        assert_line_ledger(line, 0)

    def test_a_propulsion_change_needs_the_full_changeover_gap(self):
        """An electric slot butted against a diesel predecessor is refused, and the
        same slot pushed out to exactly three idle days is planned.

        PRD: "When that preceding slot's frozen `propulsion_type` differs from the
        new slot's, the gap between the preceding slot's `end_date` and the new
        slot's `start_date`, measured in whole days, must be at least the line's
        `changeover_buffer_days`, otherwise `ERR_CHANGEOVER_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/build_slot_half_open_windows_and_propulsion_changeover_buffer
        """
        plant = self._nevada_plant_with_two_orders()
        line_id = plant["line"]["id"]
        electric_unit_id = plant["electric_unit"]["id"]
        plan_slot(line_id, plant["diesel_units"][1]["id"], "2026-09-14", "2026-09-21")
        version = line_version(line_id)

        refused = _plan_slot_response(
            line_id, electric_unit_id, "2026-09-21", "2026-09-28", version
        )
        validate_error(refused, ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION.value)
        assert read_line(line_id)["version"] == version

        # Three idle days after the diesel week closes on the 21st.
        accepted = plan_slot(
            line_id, electric_unit_id, "2026-09-24", "2026-10-01",
            expected_version=version,
        )
        assert accepted["status"] == "PLANNED"
        assert accepted["slot_days"] == 7
        assert accepted["propulsion_type"] == "ELECTRIC"
        assert_line_ledger(read_line(line_id), 0)


class TestTestBayWindowsAndElectricalCeiling:
    """A test window is a closed interval, and only electrical tests share a bay."""

    def _bay_holding_one_brake_test(self) -> dict:
        """Three slotted diesel buses and a bay already holding a three-day brake
        window on the first of them."""
        catalogue = setup_nv_catalogue()
        scenario = setup_awarded_order(
            catalogue,
            unit_count=3,
            solicitation_overrides={
                "solicitation_code": "SOL-NV-D2",
                "buyer_type": "COOPERATIVE",
                "buyer_name": "Washoe County Cooperative",
                "price_cap_cents_per_unit": 32_000_000,
            },
            bid_config=BASE_BID_CONFIG,
        )
        units = [
            mint_unit(scenario["order"]["id"], vin)
            for vin in (
                "1NVDSL0000000011",
                "1NVDSL0000000012",
                "1NVDSL0000000013",
            )
        ]
        line = create_line(**NEVADA_LINE)
        windows = [
            ("2026-09-07", "2026-09-14"),
            ("2026-09-14", "2026-09-21"),
            ("2026-09-21", "2026-09-28"),
        ]
        for unit, (start, end) in zip(units, windows):
            commit_slot(plan_slot(line["id"], unit["id"], start, end)["id"])
        for unit in units:
            assert read_unit(unit["id"])["production_status"] == "SLOTTED"
        assert_line_ledger(read_line(line["id"]), 21)

        bay = create_bay(
            bay_code="TB-2",
            plant_code="PLANT-C",
            supported_test_types=["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"],
            max_concurrent_electrical=2,
        )
        brake = schedule_test(
            units[0]["id"], bay["id"], "BRAKE", "2026-09-15", "2026-09-17"
        )
        return {"units": units, "line": line, "bay": bay, "brake_test": brake}

    def test_two_closed_windows_sharing_one_endpoint_collide(self):
        """A brake window opening on the day another brake window closes is refused,
        and the same window moved one day later is accepted.

        PRD: "Because the interval is closed, a test ending on 10 September and a
        test starting on 10 September *do* collide, which is the opposite of the
        build-slot rule one paragraph up."

        Design: Difficulty/resource_temporal_overlap/test_bay_closed_windows_and_electrical_concurrency_ceiling
        """
        plant = self._bay_holding_one_brake_test()
        bay_id = plant["bay"]["id"]
        second_unit_id = plant["units"][1]["id"]
        assert plant["brake_test"]["status"] == "SCHEDULED"
        assert plant["brake_test"]["min_required_value"] in (None, "")

        refused = api_client.create_quality_test(
            quality_test_payload(
                second_unit_id, bay_id, "BRAKE", "2026-09-17", "2026-09-18"
            ),
            QUALITY,
        )
        validate_error(refused, ApiErrorId.ERR_TEST_BAY_CONFLICT.value)

        accepted = schedule_test(
            second_unit_id, bay_id, "BRAKE", "2026-09-18", "2026-09-19"
        )
        assert accepted["status"] == "SCHEDULED"
        assert accepted["window_start"] == "2026-09-18"
        assert accepted["window_end"] == "2026-09-19"

    def test_the_bay_shares_with_a_second_electrical_test_and_refuses_a_third(self):
        """Two overlapping electrical tests are legal; the third trips the aggregate
        ceiling, and a non-electrical test in the same window trips the pairwise
        rule instead.

        PRD: "A bay with `max_concurrent_electrical` 2 therefore accepts a second
        overlapping electrical test and refuses the third."
        PRD: "A non-electrical test never shares, not even with an electrical one."

        Design: Difficulty/resource_temporal_overlap/test_bay_closed_windows_and_electrical_concurrency_ceiling
        """
        plant = self._bay_holding_one_brake_test()
        bay_id = plant["bay"]["id"]
        first, second, third = [unit["id"] for unit in plant["units"]]

        one = schedule_test(first, bay_id, "ELECTRICAL", "2026-09-20", "2026-09-21")
        two = schedule_test(second, bay_id, "ELECTRICAL", "2026-09-21", "2026-09-22")
        assert one["status"] == "SCHEDULED"
        assert two["status"] == "SCHEDULED"

        over_ceiling = api_client.create_quality_test(
            quality_test_payload(
                third, bay_id, "ELECTRICAL", "2026-09-21", "2026-09-21"
            ),
            QUALITY,
        )
        validate_error(over_ceiling, ApiErrorId.ERR_BAY_CONCURRENCY_LIMIT.value)

        unshareable = api_client.create_quality_test(
            quality_test_payload(
                third, bay_id, "EMERGENCY_EXIT", "2026-09-21", "2026-09-21"
            ),
            QUALITY,
        )
        validate_error(unshareable, ApiErrorId.ERR_TEST_BAY_CONFLICT.value)

        electrical, meta = validate_paginated(
            api_client.list_quality_tests(
                QUALITY, {"test_bay_id": bay_id, "test_type": "ELECTRICAL"}
            )
        )
        assert meta["total_count"] == 2
        assert {item["id"] for item in electrical} == {one["id"], two["id"]}
        assert all(item["status"] == "SCHEDULED" for item in electrical)
