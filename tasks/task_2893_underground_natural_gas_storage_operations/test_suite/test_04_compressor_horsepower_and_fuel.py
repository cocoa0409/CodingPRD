"""Compressor horsepower reservation, the per-instant capacity ceiling and the
four-factor fuel burn that draws working gas out of the reservoir."""

from types import SimpleNamespace

import pytest

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_FIELD_FROZEN,
    ERR_HORSEPOWER_OVERSUBSCRIBED,
    ERR_RUN_WINDOW_IN_PAST,
    ERR_RUN_WINDOW_NOT_ELAPSED,
)
from test_helpers.assertions import (
    assert_created,
    assert_duration_hours,
    assert_error_envelope,
    assert_field_derived_block,
    assert_money,
    assert_ok,
    assert_utilization,
    assert_volume,
)
from test_helpers.constants import (
    BAND_HIGH,
    BAND_LOW,
    BAND_MID,
    CONTRACT_ACTIVE,
    CONTRACT_DRAFT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    RUN_COMPLETED,
    RUN_MODE_INJECTION,
    RUN_MODE_WITHDRAWAL,
    RUN_SCHEDULED,
    TIER_2,
    TOL_MONEY,
    UNIT_AVAILABLE,
    UNIT_COMMITTED,
)
from test_helpers.fixtures import (
    book_run,
    complete_run,
    create_contract,
    create_field,
    create_shipper,
    create_std_field,
    create_unit,
    create_well,
    read_contract,
    read_field,
    read_unit,
    set_clock,
)
from test_helpers.test_users import FIELD_OPERATOR, SCHEDULING_COORDINATOR


def _mini_station(api, *, with_well=True, **unit_overrides):
    """The F-MINI reservoir with one 6000 hp compressor unit, optionally still
    unwelled so that its derived posture is frozen."""
    field = create_field(api)
    well = create_well(api, field["id"], well_name="MINI-1") if with_well else None
    unit = create_unit(api, field["id"], **unit_overrides)
    return SimpleNamespace(field=field, field_id=field["id"], well=well, unit=unit)


def _std_station(api, **unit_overrides):
    """The F-AUR reservoir with one 600000 Dth/day wellbore and one unit."""
    field = create_std_field(api)
    well = create_well(
        api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000,
        last_mit_passed_at="2026-06-01T00:00:00Z",
    )
    unit = create_unit(api, field["id"], unit_code="CU-01", **unit_overrides)
    return SimpleNamespace(field=field, field_id=field["id"], well=well, unit=unit)


class TestFrozenPostureBlocksCommitment:
    """A reservoir with no wellbores is frozen by derivation alone, and that
    blocks both the commercial and the physical commitment."""

    def test_a_derived_freeze_blocks_activation_and_booking_until_a_well_exists(self, api):
        """With no wellbore registered the posture is frozen, so contract activation
        and run booking both answer the same code; registering one wellbore reopens
        the reservoir and both calls then land unchanged.

        PRD §2.6: "While a field is `FROZEN`, no nomination on it may be confirmed,
        no gas movement ticket on it may be confirmed, no contract written against it
        may be activated, and no compressor run may be booked on it; each of those
        attempts is rejected with `ERR_FIELD_FROZEN` (HTTP 422)."

        Design: Corner/state_machines/frozen_field_blocks_contract_activation_and_horsepower_booking
        """
        station = _mini_station(api, with_well=False)
        shipper = create_shipper(api)
        contract = create_contract(api, shipper["id"], station.field_id)
        assert contract["status"] == CONTRACT_DRAFT
        assert read_field(api, station.field_id)["field_posture"] == POSTURE_FROZEN

        assert_error_envelope(
            api.activate_contract(contract["id"], SCHEDULING_COORDINATOR), ERR_FIELD_FROZEN
        )
        assert read_contract(api, contract["id"])["status"] == CONTRACT_DRAFT

        assert_error_envelope(
            api.create_compressor_run(
                F.compressor_run_payload(station.unit["id"]), FIELD_OPERATOR
            ),
            ERR_FIELD_FROZEN,
        )
        idle = read_unit(api, station.unit["id"])
        assert idle["status"] == UNIT_AVAILABLE
        assert idle["scheduled_run_count"] == 0

        create_well(api, station.field_id, well_name="MINI-1")
        assert_field_derived_block(
            read_field(api, station.field_id),
            posture=POSTURE_OPEN, withdrawal_rate=150000, injection_rate=150000,
        )

        activated = assert_ok(
            api.activate_contract(contract["id"], SCHEDULING_COORDINATOR)
        )
        assert activated["status"] == CONTRACT_ACTIVE

        run = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(station.unit["id"]), FIELD_OPERATOR
            )
        )
        assert run["status"] == RUN_SCHEDULED
        assert run["fuel_consumed_dth"] is None
        assert_duration_hours(run["duration_hours"], 8.0)

        committed = read_unit(api, station.unit["id"])
        assert committed["status"] == UNIT_COMMITTED
        assert committed["scheduled_run_count"] == 1
        assert_money(committed["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")

        _, meta = validate_paginated(
            api.list_unit_runs(station.unit["id"], FIELD_OPERATOR, {"limit": 100})
        )
        assert meta["total_count"] == 1


class TestRunCompletionDrawsWorkingGas:
    """Completion is the only point fuel is drawn, and one burn moves the unit,
    the reservoir inventory and both rate ceilings at once."""

    def test_completion_burns_the_band_rate_and_moves_the_rates_asymmetrically(self, api):
        """A mid-band eight-hour injection run burns 220.80 Dth out of working gas,
        which pulls the withdrawal ceiling down while pushing the injection ceiling
        up, and returns the unit to service.

        PRD §3.3: "On the field, `fuel_gas_used_dth` increases by the fuel burned and
        `working_gas_inventory_dth` falls by the same amount — compressor fuel is
        drawn out of working gas, which is why the conservation identity in §2.9
        subtracts it."

        Design: Corner/state_machines/compressor_run_completion_burns_field_gas_and_reprices_deliverability
        """
        station = _mini_station(api)
        run = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-02T00:00:00Z",
            window_end_at="2026-08-02T08:00:00Z",
            allocated_horsepower=3000,
            mode=RUN_MODE_INJECTION,
        )
        set_clock(api, "2026-08-02T08:00:00Z")

        completed = assert_ok(api.complete_compressor_run(run["id"], FIELD_OPERATOR))
        assert completed["status"] == RUN_COMPLETED
        assert_money(completed["effective_horsepower"], 3000.00, "effective_horsepower")
        assert_utilization(completed["utilization_ratio"], 0.500000)
        assert completed["utilization_band"] == BAND_MID
        assert_duration_hours(completed["duration_hours"], 8.0)
        assert_money(completed["fuel_consumed_dth"], 220.80, "fuel_consumed_dth")

        unit = read_unit(api, station.unit["id"])
        assert_money(unit["lifetime_fuel_dth"], 220.80, "lifetime_fuel_dth")
        assert unit["scheduled_run_count"] == 0
        assert unit["status"] == UNIT_AVAILABLE

        field = read_field(api, station.field_id)
        assert_money(field["fuel_gas_used_dth"], 220.80, "fuel_gas_used_dth")
        assert_volume(field["working_gas_inventory_dth"], 249779.200, "working_gas_inventory_dth")
        assert_field_derived_block(
            field,
            inventory_pct=49.96, pressure=1499, tier=TIER_2,
            withdrawal_rate=149880, injection_rate=150120, posture=POSTURE_OPEN,
        )
        assert_volume(field["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")

    def test_the_window_must_be_future_at_booking_and_fully_elapsed_at_completion(self, api):
        """A window that has already begun cannot be booked, and a clock sitting
        strictly inside a booked window still counts as not elapsed, so no fuel is
        drawn and the unit stays committed.

        PRD §2.11 rung 23: "The logical clock has reached or passed a run's
        `window_end_at` before the run may be completed — otherwise
        `ERR_RUN_WINDOW_NOT_ELAPSED` (409)."

        Design: Corner/state_machines/compressor_run_windows_must_be_future_at_booking_and_elapsed_at_completion
        """
        station = _mini_station(api)

        assert_error_envelope(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-07-31T00:00:00Z",
                    window_end_at="2026-08-02T08:00:00Z",
                ),
                FIELD_OPERATOR,
            ),
            ERR_RUN_WINDOW_IN_PAST,
        )
        _, empty = validate_paginated(
            api.list_unit_runs(station.unit["id"], FIELD_OPERATOR, {"limit": 100})
        )
        assert empty["total_count"] == 0, "the refused booking created no run"

        run = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(station.unit["id"]), FIELD_OPERATOR
            )
        )
        assert run["status"] == RUN_SCHEDULED
        assert run["fuel_consumed_dth"] is None

        assert_error_envelope(
            api.complete_compressor_run(run["id"], FIELD_OPERATOR),
            ERR_RUN_WINDOW_NOT_ELAPSED,
        )
        set_clock(api, "2026-08-02T04:00:00Z")
        assert_error_envelope(
            api.complete_compressor_run(run["id"], FIELD_OPERATOR),
            ERR_RUN_WINDOW_NOT_ELAPSED,
        )

        unit = read_unit(api, station.unit["id"])
        assert unit["status"] == UNIT_COMMITTED
        assert unit["scheduled_run_count"] == 1
        assert_money(unit["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")

        field = read_field(api, station.field_id)
        assert_volume(field["working_gas_inventory_dth"], 250000.000, "working_gas_inventory_dth")
        assert_money(field["fuel_gas_used_dth"], 0.00, "fuel_gas_used_dth")

        rows, meta = validate_paginated(
            api.list_unit_runs(
                station.unit["id"], FIELD_OPERATOR, {"status": RUN_SCHEDULED, "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == run["id"]
        assert rows[0]["fuel_consumed_dth"] is None


class TestFuelClamps:
    """The per-run clamp has two edges, and only the clamped figures accumulate."""

    def test_both_clamps_fire_on_one_unit_and_only_the_clamped_figures_accumulate(self, api):
        """A tiny one-hour run is lifted to the floor and a hundred-hour full-load
        run is cut to the ceiling, so the unit's lifetime total and the reservoir's
        inventory reflect the clamped burns, not the raw ones.

        PRD §3.3: "That raw figure is then clamped into the permitted range for a
        single run — never below 25.00 dekatherms and never above 5000.00 dekatherms,
        with the upper clamp applied before the lower one so that the floor always
        wins a conflict — and the clamped result is rounded half up to 2 decimal
        places to become `fuel_consumed_dth`."

        Design: Corner/calculations/fuel_burn_is_clamped_at_both_the_floor_and_the_ceiling_on_one_unit
        """
        station = _mini_station(api)
        small = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-02T00:00:00Z",
            window_end_at="2026-08-02T01:00:00Z",
            allocated_horsepower=100,
            mode=RUN_MODE_INJECTION,
        )
        large = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-03T00:00:00Z",
            window_end_at="2026-08-07T04:00:00Z",
            allocated_horsepower=6000,
            mode=RUN_MODE_INJECTION,
        )

        set_clock(api, "2026-08-02T01:00:00Z")
        floored = complete_run(api, small["id"])
        assert_duration_hours(floored["duration_hours"], 1.0)
        assert_money(floored["effective_horsepower"], 100.00, "effective_horsepower")
        assert_utilization(floored["utilization_ratio"], 0.016667)
        assert floored["utilization_band"] == BAND_LOW
        # raw 100.00 x 1 h x 0.0110 x 1.00 = 1.10 Dth, lifted to the 25.00 floor
        assert_money(floored["fuel_consumed_dth"], 25.00, "fuel_consumed_dth")

        set_clock(api, "2026-08-07T04:00:00Z")
        capped = complete_run(api, large["id"])
        assert_duration_hours(capped["duration_hours"], 100.0)
        assert_money(capped["effective_horsepower"], 6000.00, "effective_horsepower")
        assert_utilization(capped["utilization_ratio"], 1.000000)
        assert capped["utilization_band"] == BAND_HIGH
        # raw 6000.00 x 100 h x 0.0105 x 1.00 = 6300.00 Dth, cut to the 5000.00 ceiling
        assert_money(capped["fuel_consumed_dth"], 5000.00, "fuel_consumed_dth")

        unit = read_unit(api, station.unit["id"])
        assert_money(unit["lifetime_fuel_dth"], 5025.00, "lifetime_fuel_dth")
        assert unit["scheduled_run_count"] == 0
        assert unit["status"] == UNIT_AVAILABLE

        field = read_field(api, station.field_id)
        assert_money(field["fuel_gas_used_dth"], 5025.00, "fuel_gas_used_dth")
        assert_volume(field["working_gas_inventory_dth"], 244975.000, "working_gas_inventory_dth")
        assert_field_derived_block(
            field, inventory_pct=49.00, pressure=1486, tier=TIER_2,
            withdrawal_rate=147000, injection_rate=153000,
        )


class TestFuelBurnComposition:
    """One burn chains the derate, the band rate, the window length and the mode
    multiplier, in that order."""

    def _derated_station_with_two_adjacent_runs(self, api):
        station = _std_station(api, derate_factor=0.10)
        injection = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=5000,
            mode=RUN_MODE_INJECTION,
        )
        withdrawal = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T08:00:00Z",
            window_end_at="2026-08-05T16:00:00Z",
            allocated_horsepower=5000,
            mode=RUN_MODE_WITHDRAWAL,
        )
        set_clock(api, "2026-08-05T16:00:00Z")
        return station, injection, withdrawal

    def test_the_derate_moves_the_band_and_the_injection_burn_lands_on_331_20(self, api):
        """The unit's derate turns 5000 allocated horsepower into 4500 effective,
        which selects the mid band, and eight hours at the injection multiplier burns
        331.20 Dth — not the 368.00 an undereated run would burn.

        PRD §3.3: "The raw burn is the run's `effective_horsepower` multiplied by its
        `duration_hours`, multiplied by the band rate, multiplied by the mode
        multiplier."

        Design: Difficulty/combinatorial_formula/compressor_fuel_burn_composes_derate_band_and_mode_multiplier
        """
        _, injection, _ = self._derated_station_with_two_adjacent_runs(api)

        completed = complete_run(api, injection["id"])
        assert completed["status"] == RUN_COMPLETED
        assert_duration_hours(completed["duration_hours"], 8.0)
        assert_money(completed["effective_horsepower"], 4500.00, "effective_horsepower")
        assert_utilization(completed["utilization_ratio"], 0.750000)
        assert completed["utilization_band"] == BAND_MID
        assert_money(completed["fuel_consumed_dth"], 331.20, "fuel_consumed_dth")
        assert abs(float(completed["fuel_consumed_dth"]) - 368.00) > 0.005, (
            "368.00 would be the burn with the derate dropped"
        )

    def test_the_mode_multiplier_makes_the_identical_withdrawal_run_cheaper(self, api):
        """The withdrawal run has the same effective horsepower, band and duration as
        its injection twin, so only the mode multiplier separates them, and the two
        burns accumulate on one unit and one reservoir.

        PRD §3.3: "The mode then applies a multiplier of 1.00 for `INJECTION` and
        0.85 for `WITHDRAWAL`."

        Design: Difficulty/combinatorial_formula/compressor_fuel_burn_composes_derate_band_and_mode_multiplier
        """
        station, injection, withdrawal = self._derated_station_with_two_adjacent_runs(api)

        first = complete_run(api, injection["id"])
        second = complete_run(api, withdrawal["id"])
        assert second["status"] == RUN_COMPLETED
        assert_duration_hours(second["duration_hours"], 8.0)
        assert_money(second["effective_horsepower"], 4500.00, "effective_horsepower")
        assert second["utilization_band"] == BAND_MID
        assert_money(second["fuel_consumed_dth"], 281.52, "fuel_consumed_dth")
        assert abs(float(second["fuel_consumed_dth"]) - float(first["fuel_consumed_dth"])) > 0.005, (
            "a withdrawal run must not burn what its injection twin burns"
        )

        unit = read_unit(api, station.unit["id"])
        assert_money(unit["lifetime_fuel_dth"], 612.72, "lifetime_fuel_dth")
        assert unit["scheduled_run_count"] == 0
        assert unit["status"] == UNIT_AVAILABLE

        field = read_field(api, station.field_id)
        assert_money(field["fuel_gas_used_dth"], 612.72, "fuel_gas_used_dth")
        assert_volume(
            field["working_gas_inventory_dth"], 2999387.280, "working_gas_inventory_dth"
        )


class TestHorsepowerCeilingBoundary:
    """The capacity test is strictly greater than the nameplate, and adjacency
    across a window edge is free."""

    def test_a_sum_exactly_at_the_nameplate_is_admitted_and_one_more_horse_is_not(self, api):
        """Two runs summing to exactly the rated horsepower over the same window are
        both accepted, and a further single horsepower over that window is refused.

        PRD §2.11 rung 25: "Adjacency is free: a run starting exactly at another
        run's `window_end_at` does not overlap it, and a sum exactly equal to
        `rated_horsepower` is accepted."

        Design: Difficulty/boundary_precision_check/horsepower_allocation_exactly_at_rated_capacity_is_admissible
        """
        station = _std_station(api)
        book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=4000,
            mode=RUN_MODE_INJECTION,
        )

        at_ceiling = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T00:00:00Z",
                    window_end_at="2026-08-05T08:00:00Z",
                    allocated_horsepower=2000,
                ),
                FIELD_OPERATOR,
            )
        )
        assert at_ceiling["status"] == RUN_SCHEDULED

        assert_error_envelope(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T00:00:00Z",
                    window_end_at="2026-08-05T08:00:00Z",
                    allocated_horsepower=1,
                ),
                FIELD_OPERATOR,
            ),
            ERR_HORSEPOWER_OVERSUBSCRIBED,
        )
        _, meta = validate_paginated(
            api.list_unit_runs(station.unit["id"], FIELD_OPERATOR, {"limit": 100})
        )
        assert meta["total_count"] == 2, "the refused booking created no run"

    def test_a_full_load_run_starting_at_the_previous_window_end_is_admitted(self, api):
        """A full nameplate allocation beginning exactly when the occupied window
        closes does not overlap it, and none of the three bookings has burned any
        fuel yet.

        PRD §3.3: "The run starts at `status` `SCHEDULED` with `fuel_consumed_dth`
        null, and the unit's `scheduled_run_count` increments while its `status`
        becomes `COMMITTED`."

        Design: Difficulty/boundary_precision_check/horsepower_allocation_exactly_at_rated_capacity_is_admissible
        """
        station = _std_station(api)
        first = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=4000,
            mode=RUN_MODE_INJECTION,
        )
        book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=2000,
            mode=RUN_MODE_INJECTION,
        )

        adjacent = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T08:00:00Z",
                    window_end_at="2026-08-05T16:00:00Z",
                    allocated_horsepower=6000,
                ),
                FIELD_OPERATOR,
            )
        )
        assert adjacent["status"] == RUN_SCHEDULED
        assert adjacent["fuel_consumed_dth"] is None

        unit = read_unit(api, station.unit["id"])
        assert unit["scheduled_run_count"] == 3
        assert unit["status"] == UNIT_COMMITTED
        assert_money(unit["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")

        rows, meta = validate_paginated(
            api.list_unit_runs(station.unit["id"], FIELD_OPERATOR, {"limit": 100})
        )
        assert meta["total_count"] == 3
        assert all(row["fuel_consumed_dth"] is None for row in rows)
        assert next(row for row in rows if row["id"] == first["id"])["status"] == RUN_SCHEDULED
        assert_money(
            read_field(api, station.field_id)["fuel_gas_used_dth"], 0.00, "fuel_gas_used_dth"
        )


class TestFuelBandJump:
    """The band table is non-monotonic, so one horsepower across the high floor
    makes the burn jump upward."""

    def _station_with_a_high_and_a_mid_run(self, api):
        station = _std_station(api)
        high = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=5100,
            mode=RUN_MODE_INJECTION,
        )
        mid = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T08:00:00Z",
            window_end_at="2026-08-05T16:00:00Z",
            allocated_horsepower=5099,
            mode=RUN_MODE_INJECTION,
        )
        set_clock(api, "2026-08-05T16:00:00Z")
        return station, high, mid

    def test_a_ratio_landing_exactly_on_the_high_floor_takes_the_high_rate(self, api):
        """5100 horsepower on a 6000 horsepower unit rounds to exactly the high-band
        floor, so the run burns at the high rate rather than the mid rate.

        PRD §3.3: "`utilization_band` is read from that six-decimal ratio — `LOW`
        below 0.50, `MID` from 0.50 up to but not including 0.85, and `HIGH` at 0.85
        or above."

        Design: Difficulty/boundary_precision_check/fuel_band_jumps_upward_across_utilization_ratio_0_850000
        """
        _, high, _ = self._station_with_a_high_and_a_mid_run(api)

        completed = complete_run(api, high["id"])
        assert_money(completed["effective_horsepower"], 5100.00, "effective_horsepower")
        assert_utilization(completed["utilization_ratio"], 0.850000)
        assert completed["utilization_band"] == BAND_HIGH
        assert_money(completed["fuel_consumed_dth"], 428.40, "fuel_consumed_dth")
        assert abs(float(completed["fuel_consumed_dth"]) - 375.36) > 0.005, (
            "375.36 would be the mid-band rate applied to 5100 horsepower"
        )

    def test_one_horsepower_below_the_floor_burns_less_and_the_gap_is_53_11(self, api):
        """The neighbouring run one horsepower lower stays in the mid band, so the
        cheaper band sits above the more heavily loaded run and the two burns
        accumulate on the unit and the reservoir.

        PRD §3.3: "Note that this table is deliberately non-monotonic: the high-band
        rate sits *above* the mid-band rate, so a run that just crosses a utilization
        of 0.85 burns more fuel than one just below it even though its effective
        horsepower barely moved."

        Design: Difficulty/boundary_precision_check/fuel_band_jumps_upward_across_utilization_ratio_0_850000
        """
        station, high, mid = self._station_with_a_high_and_a_mid_run(api)

        high_run = complete_run(api, high["id"])
        mid_run = complete_run(api, mid["id"])
        assert_money(mid_run["effective_horsepower"], 5099.00, "effective_horsepower")
        assert_utilization(mid_run["utilization_ratio"], 0.849833)
        assert mid_run["utilization_band"] == BAND_MID
        assert_money(mid_run["fuel_consumed_dth"], 375.29, "fuel_consumed_dth")
        # The gap is computed here, client-side, from two figures each already
        # asserted at 2 dp above, so only its value is meaningful -- a binary
        # float subtraction of two 2-dp decimals carries no decimal width of its
        # own (428.40 - 375.29 == 53.109999999999996).
        gap = float(high_run["fuel_consumed_dth"]) - float(mid_run["fuel_consumed_dth"])
        assert gap == pytest.approx(53.11, abs=TOL_MONEY), (
            f"The high band burns more than the mid band by 53.11 Dth, got {gap}"
        )

        unit = read_unit(api, station.unit["id"])
        assert_money(unit["lifetime_fuel_dth"], 803.69, "lifetime_fuel_dth")
        field = read_field(api, station.field_id)
        assert_money(field["fuel_gas_used_dth"], 803.69, "fuel_gas_used_dth")
        assert_volume(
            field["working_gas_inventory_dth"], 2999196.310, "working_gas_inventory_dth"
        )


class TestHorsepowerPerInstantAggregation:
    """The ceiling is enforced at every instant a window covers, summed over
    every run that covers it."""

    def _station_with_one_morning_run(self, api):
        station = _std_station(api)
        first = book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T00:00:00Z",
            window_end_at="2026-08-05T08:00:00Z",
            allocated_horsepower=4000,
            mode=RUN_MODE_INJECTION,
        )
        return station, first

    def test_a_two_hour_overlap_is_enough_to_oversubscribe_while_adjacency_is_free(self, api):
        """The same 3000 horsepower request is refused when it shares two hours with
        the booked run and accepted when it starts exactly at that run's end.

        PRD §2.11 rung 25: "For every instant covered by the new compressor run's
        half-open window, the sum of `allocated_horsepower` over `SCHEDULED` and
        `COMPLETED` runs on the same unit that cover that instant, plus the new
        allocation, is no greater than the unit's `rated_horsepower` — otherwise
        `ERR_HORSEPOWER_OVERSUBSCRIBED` (409)."

        Design: Difficulty/resource_temporal_overlap/compressor_horsepower_aggregated_over_partially_overlapping_windows
        """
        station, _ = self._station_with_one_morning_run(api)

        assert_error_envelope(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T06:00:00Z",
                    window_end_at="2026-08-05T12:00:00Z",
                    allocated_horsepower=3000,
                ),
                FIELD_OPERATOR,
            ),
            ERR_HORSEPOWER_OVERSUBSCRIBED,
        )

        accepted = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T08:00:00Z",
                    window_end_at="2026-08-05T12:00:00Z",
                    allocated_horsepower=3000,
                ),
                FIELD_OPERATOR,
            )
        )
        assert accepted["status"] == RUN_SCHEDULED
        assert_duration_hours(accepted["duration_hours"], 4.0)

        unit = read_unit(api, station.unit["id"])
        assert unit["scheduled_run_count"] == 2
        assert_money(unit["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")

    def test_the_ceiling_sums_every_covering_run_not_just_a_pair(self, api):
        """A nested run fits under the ceiling alongside its host, and a fourth
        booking overlapping both of them is refused on the three-run aggregate rather
        than on any single pair.

        PRD §3.3: "The window must fit within the unit's nameplate at every instant
        it covers, per rung 25 of §2.11."

        Design: Difficulty/resource_temporal_overlap/compressor_horsepower_aggregated_over_partially_overlapping_windows
        """
        station, _ = self._station_with_one_morning_run(api)
        book_run(
            api, station.unit["id"],
            window_start_at="2026-08-05T08:00:00Z",
            window_end_at="2026-08-05T12:00:00Z",
            allocated_horsepower=3000,
            mode=RUN_MODE_INJECTION,
        )

        nested = assert_created(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T09:00:00Z",
                    window_end_at="2026-08-05T11:00:00Z",
                    allocated_horsepower=2000,
                    mode=RUN_MODE_WITHDRAWAL,
                ),
                FIELD_OPERATOR,
            )
        )
        assert nested["status"] == RUN_SCHEDULED
        assert_duration_hours(nested["duration_hours"], 2.0)

        assert_error_envelope(
            api.create_compressor_run(
                F.compressor_run_payload(
                    station.unit["id"],
                    window_start_at="2026-08-05T10:00:00Z",
                    window_end_at="2026-08-05T10:30:00Z",
                    allocated_horsepower=1001,
                ),
                FIELD_OPERATOR,
            ),
            ERR_HORSEPOWER_OVERSUBSCRIBED,
        )

        unit = read_unit(api, station.unit["id"])
        assert unit["scheduled_run_count"] == 3
        assert unit["status"] == UNIT_COMMITTED
        assert_money(unit["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")
        _, meta = validate_paginated(
            api.list_unit_runs(station.unit["id"], FIELD_OPERATOR, {"limit": 100})
        )
        assert meta["total_count"] == 3
