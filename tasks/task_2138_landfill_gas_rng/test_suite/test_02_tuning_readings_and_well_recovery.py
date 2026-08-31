"""Wellfield tuning: gas quality scoring, the automatic well response, and the
evidence-gated walk back to service."""

from test_helpers import (
    ApiErrorId,
    approx_2dp,
    assert_well_tuning_reading,
    alarm_reading_payload,
    fixtures,
    good_reading_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    watch_reading_payload,
)
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.test_users import TEST_USERS

TECH = TEST_USERS["wellfield_technician_headers"]


def _site_with_wells(*codes):
    set_clock(BASE_CLOCK_UTC)
    site = fixtures.create_site()
    wells = [fixtures.create_well(site["id"], well_code=code) for code in codes]
    return site, wells


class TestReadingClassification:
    def test_good_reading_scores_its_index_and_credits_the_flow_at_face_value(
        self, api, technician_headers
    ):
        """PRD §3.2: "The composite `air_intrusion_index` is built by taking the oxygen
        percentage multiplied by four, adding the nitrogen percentage multiplied by 0.35,
        subtracting a methane credit equal to the methane percentage multiplied by 0.05,
        and adding a temperature penalty equal to 0.25 for every degree Fahrenheit by
        which the wellhead temperature exceeds 130 — with that excess floored at zero, so
        a reading at or below 130 degrees contributes no temperature penalty at all."
        PRD §3.2: "An `ONLINE` well stays `ONLINE`, takes the reading's flow at face
        value as its `current_flow_scfm`, and increments `consecutive_good_readings` by
        one."

        Design: Corner/calculations/good_reading_air_intrusion_index_correct_result
        """
        site, (well,) = _site_with_wells("W-01")

        reading = validate_success(
            api.create_reading(
                well["id"],
                good_reading_payload("2026-08-10T01:00:00Z", flow_scfm=480.0),
                technician_headers,
            ),
            201,
        )
        assert_well_tuning_reading(reading)

        # 0.8 * 4 + 4.0 * 0.35 - 55.0 * 0.05 + 0.00 = 1.85
        assert reading["air_intrusion_index"] == approx_2dp(1.85)
        assert reading["quality_class"] == "GOOD"
        assert reading["resulting_well_state"] == "ONLINE"

        well_after = fixtures.read_well(well["id"])
        assert well_after["operating_state"] == "ONLINE"
        assert well_after["current_flow_scfm"] == approx_2dp(480.0)
        assert well_after["consecutive_good_readings"] == 1
        assert well_after["wellhead_vacuum_inhg"] == approx_2dp(22.5)

        site_after = fixtures.read_site(site["id"])
        assert site_after["collected_flow_scfm"] == approx_2dp(480.0)
        assert site_after["collection_efficiency_pct"] == approx_2dp(96.0)

    def test_oxygen_at_exactly_five_percent_alarms_and_isolates_the_well(
        self, api, technician_headers
    ):
        """PRD §3.2: "The reading is `ALARM` when the oxygen percentage is at least 5.00,
        or the temperature is at least 145 degrees Fahrenheit, or the air-intrusion index
        is at least 24.00."
        PRD §3.2: "The oxygen alarm threshold is an inclusive floor — exactly 5.00
        alarms, 4.99 does not — and the alarm index threshold sits at 24.00 precisely so
        that an oxygen reading just below 5.00 cannot trip the index rung by itself,
        keeping the oxygen boundary independently observable."
        PRD §3.2: "An `ALARM` reading isolates the well: from `ONLINE` or from
        `THROTTLED` the well moves to `ISOLATED`, its `current_flow_scfm` is set to 0 and
        its `consecutive_good_readings` is reset to 0."

        Design: Difficulty/boundary_precision_check/oxygen_at_exactly_five_percent_isolates_while_four_ninety_nine_throttles
        """
        site, (well,) = _site_with_wells("W-01")

        reading = validate_success(
            api.create_reading(
                well["id"], alarm_reading_payload("2026-08-10T02:00:00Z"), technician_headers
            ),
            201,
        )
        # 5.00 * 4 + 2.0 * 0.35 - 60.0 * 0.05 = 17.70, well under the 24.00 index rung.
        assert reading["air_intrusion_index"] == approx_2dp(17.70)
        assert reading["quality_class"] == "ALARM", (
            "oxygen at exactly 5.00 sits on the inclusive alarm floor"
        )
        assert reading["resulting_well_state"] == "ISOLATED"

        well_after = fixtures.read_well(well["id"])
        assert well_after["operating_state"] == "ISOLATED"
        assert well_after["current_flow_scfm"] == approx_2dp(0.0)
        assert fixtures.read_site(site["id"])["collected_flow_scfm"] == approx_2dp(0.0)

    def test_oxygen_one_hundredth_below_the_alarm_floor_only_throttles_the_well(
        self, api, technician_headers
    ):
        """PRD §3.2: "Failing that, it is `WATCH` when the oxygen percentage is at least
        2.00, or the methane percentage is below 45.00, or the air-intrusion index is at
        least 6.00."
        PRD §3.2: "A `WATCH` reading throttles it: an `ONLINE` well takes
        `ONLINE → THROTTLED` and a `THROTTLED` well stays `THROTTLED` on a self-loop, and
        in both cases the credited flow becomes the smaller of the reading's own flow and
        60 percent of the well's `target_flow_scfm`, rounded half up to two decimal
        places, while `consecutive_good_readings` resets to 0."
        PRD §3.1: "`collected_flow_scfm` is the sum of `current_flow_scfm` over the
        site's wells whose `operating_state` is either `ONLINE` or `THROTTLED`; wells in
        `ISOLATED`, `MAINTENANCE_LOCKOUT` or `DECOMMISSIONED` contribute nothing."

        Design: Difficulty/boundary_precision_check/oxygen_at_exactly_five_percent_isolates_while_four_ninety_nine_throttles
        """
        site, (well_one, well_two) = _site_with_wells("W-01", "W-02")

        watch_reading = validate_success(
            api.create_reading(
                well_one["id"],
                watch_reading_payload("2026-08-10T02:00:00Z"),
                technician_headers,
            ),
            201,
        )
        alarm_reading = validate_success(
            api.create_reading(
                well_two["id"],
                alarm_reading_payload("2026-08-10T02:00:00Z"),
                technician_headers,
            ),
            201,
        )

        # 4.99 * 4 + 2.0 * 0.35 - 60.0 * 0.05 = 17.66
        assert watch_reading["air_intrusion_index"] == approx_2dp(17.66)
        assert watch_reading["quality_class"] == "WATCH", "4.99 does not alarm"
        assert watch_reading["resulting_well_state"] == "THROTTLED"
        assert alarm_reading["quality_class"] == "ALARM"

        throttled = fixtures.read_well(well_one["id"])
        assert throttled["operating_state"] == "THROTTLED"
        # min(500.0, 500.0 * 0.60) = 300.0
        assert throttled["current_flow_scfm"] == approx_2dp(300.0)

        isolated = fixtures.read_well(well_two["id"])
        assert isolated["operating_state"] == "ISOLATED"
        assert isolated["current_flow_scfm"] == approx_2dp(0.0)

        site_after = fixtures.read_site(site["id"])
        assert site_after["collected_flow_scfm"] == approx_2dp(300.0), (
            "only the throttled well contributes; the isolated well contributes nothing"
        )


class TestWellRecoveryCycle:
    def test_alarm_isolates_the_well_and_the_isolated_self_loop_banks_good_readings(
        self, api, technician_headers
    ):
        """PRD §3.2: "An `ALARM` reading isolates the well: from `ONLINE` or from
        `THROTTLED` the well moves to `ISOLATED`, its `current_flow_scfm` is set to 0 and
        its `consecutive_good_readings` is reset to 0."
        PRD §3.2: "An `ISOLATED` well stays `ISOLATED` on any class of reading, and its
        `current_flow_scfm` stays 0 no matter how good the gas looks; a `GOOD` reading
        there increments `consecutive_good_readings` by one and a `WATCH` or `ALARM`
        reading resets it to 0."

        Design: Difficulty/non_linear_state_machine/gas_well_isolation_and_recovery_cycle
        """
        site, (well,) = _site_with_wells("W-01")
        fixtures.post_good_reading(well["id"], "2026-08-10T01:00:00Z", flow_scfm=480.0)

        alarm = validate_success(
            api.create_reading(
                well["id"], alarm_reading_payload("2026-08-10T02:00:00Z"), technician_headers
            ),
            201,
        )
        assert alarm["quality_class"] == "ALARM"
        assert alarm["resulting_well_state"] == "ISOLATED"

        isolated = fixtures.read_well(well["id"])
        assert isolated["operating_state"] == "ISOLATED"
        assert isolated["current_flow_scfm"] == approx_2dp(0.0)
        assert isolated["consecutive_good_readings"] == 0

        for index, taken_at in enumerate(
            ("2026-08-10T03:00:00Z", "2026-08-10T04:00:00Z"), start=1
        ):
            fixtures.post_good_reading(well["id"], taken_at, flow_scfm=460.0)
            banked = fixtures.read_well(well["id"])
            assert banked["operating_state"] == "ISOLATED", (
                "a GOOD reading never promotes an isolated well by itself"
            )
            assert banked["current_flow_scfm"] == approx_2dp(0.0)
            assert banked["consecutive_good_readings"] == index

        assert fixtures.read_site(site["id"])["collected_flow_scfm"] == approx_2dp(0.0)

    def test_well_walks_the_isolated_throttled_online_recovery_cycle(
        self, api, technician_headers
    ):
        """PRD §3.2: "Moving `ISOLATED → THROTTLED` requires the well's
        `last_quality_class` to be `GOOD` and its `consecutive_good_readings` to be at
        least 2; the credited flow becomes the smaller of `last_reading_flow_scfm` and 60
        percent of `target_flow_scfm`, rounded half up to two decimal places. Moving
        `THROTTLED → ONLINE` requires `last_quality_class` to be `GOOD` and
        `consecutive_good_readings` to be at least 3, and the credited flow becomes
        `last_reading_flow_scfm` in full."
        PRD §3.2: "A `THROTTLED` well stays `THROTTLED` and increments
        `consecutive_good_readings` by one, but its credited flow is still capped at the
        smaller of the reading's flow and 60 percent of target — a good reading never
        lifts a throttled well above its throttled cap."

        Design: Difficulty/non_linear_state_machine/gas_well_isolation_and_recovery_cycle
        """
        site, (well,) = _site_with_wells("W-01")
        fixtures.post_good_reading(well["id"], "2026-08-10T01:00:00Z", flow_scfm=480.0)
        api.create_reading(
            well["id"], alarm_reading_payload("2026-08-10T02:00:00Z"), technician_headers
        )
        fixtures.post_good_reading(well["id"], "2026-08-10T03:00:00Z", flow_scfm=460.0)
        fixtures.post_good_reading(well["id"], "2026-08-10T04:00:00Z", flow_scfm=460.0)

        throttled = validate_success(
            api.set_well_status(
                well["id"],
                {
                    "to_state": "THROTTLED",
                    "reason": "Two consecutive good readings after isolation",
                },
                technician_headers,
            )
        )
        assert throttled["operating_state"] == "THROTTLED"
        # min(460.0, 500.0 * 0.60) = 300.0
        assert throttled["current_flow_scfm"] == approx_2dp(300.0)

        fixtures.post_good_reading(well["id"], "2026-08-10T05:00:00Z", flow_scfm=460.0)
        still_capped = fixtures.read_well(well["id"])
        assert still_capped["operating_state"] == "THROTTLED"
        assert still_capped["current_flow_scfm"] == approx_2dp(300.0)
        assert still_capped["consecutive_good_readings"] == 3

        online = validate_success(
            api.set_well_status(
                well["id"],
                {"to_state": "ONLINE", "reason": "Third consecutive good reading"},
                technician_headers,
            )
        )
        assert online["operating_state"] == "ONLINE", (
            "the well has returned to the state it started in"
        )
        assert online["current_flow_scfm"] == approx_2dp(460.0)

        assert fixtures.read_site(site["id"])["collected_flow_scfm"] == approx_2dp(460.0)

    def test_return_to_service_on_a_single_good_reading_is_refused(
        self, api, technician_headers
    ):
        """PRD §3.2: "Moving `ISOLATED → THROTTLED` requires the well's
        `last_quality_class` to be `GOOD` and its `consecutive_good_readings` to be at
        least 2; the credited flow becomes the smaller of `last_reading_flow_scfm` and 60
        percent of `target_flow_scfm`, rounded half up to two decimal places."
        PRD §3.2: "Attempting either without the required run of consecutive good
        readings is rejected with `ERR_WELL_NOT_RECOVERED`."

        Design: Corner/state_machines/well_return_to_service_without_two_good_readings_is_rejected
        """
        site, (well,) = _site_with_wells("W-01")
        api.create_reading(
            well["id"], alarm_reading_payload("2026-08-10T02:00:00Z"), technician_headers
        )
        fixtures.post_good_reading(well["id"], "2026-08-10T03:00:00Z", flow_scfm=460.0)

        validate_error(
            api.set_well_status(
                well["id"],
                {
                    "to_state": "THROTTLED",
                    "reason": "Technician believes the well has recovered",
                },
                technician_headers,
            ),
            ApiErrorId.ERR_WELL_NOT_RECOVERED.value,
        )

        unchanged = fixtures.read_well(well["id"])
        assert unchanged["operating_state"] == "ISOLATED"
        assert unchanged["consecutive_good_readings"] == 1
        assert unchanged["current_flow_scfm"] == approx_2dp(0.0)


class TestReadingRejections:
    def test_composition_summing_above_one_hundred_is_refused_before_classification(
        self, api, technician_headers
    ):
        """PRD §3.2: "The three composition percentages together may not exceed 100,
        since gas that is more than entirely itself is a bad instrument rather than a bad
        well; a sum above 100 is rejected with `ERR_GAS_COMPOSITION_INVALID`."
        PRD §2.5: "**Gas composition coherence (priority 55).** On a tuning reading, the
        methane, oxygen and nitrogen percentages must sum to no more than 100, or
        `ERR_GAS_COMPOSITION_INVALID` with HTTP 422."

        Design: Corner/validations/gas_composition_summing_over_one_hundred_is_rejected
        """
        site, (well,) = _site_with_wells("W-01")

        validate_error(
            api.create_reading(
                well["id"],
                good_reading_payload(
                    "2026-08-10T01:00:00Z",
                    methane_pct=90.0,
                    oxygen_pct=8.0,
                    nitrogen_pct=10.0,
                ),
                technician_headers,
            ),
            ApiErrorId.ERR_GAS_COMPOSITION_INVALID.value,
        )

        unchanged = fixtures.read_well(well["id"])
        assert unchanged["operating_state"] == "ONLINE", (
            "the coherence rung runs before the classification ladder, so the "
            "alarm-level oxygen never reaches the state machine"
        )
        assert unchanged["last_quality_class"] == "NONE"

        _, meta = validate_paginated(
            api.list_readings(
                well["id"], technician_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0

    def test_reading_not_strictly_after_the_previous_taken_at_is_refused(
        self, api, technician_headers
    ):
        """PRD §3.2: "Readings must arrive in chronological order: `taken_at` must be
        strictly after the well's current `last_reading_at`, and a reading that is not is
        rejected with `ERR_READING_OUT_OF_ORDER`."

        Design: Corner/validations/reading_not_after_previous_taken_at_is_rejected
        """
        site, (well,) = _site_with_wells("W-01")
        fixtures.post_good_reading(well["id"], "2026-08-10T01:00:00Z", flow_scfm=480.0)

        validate_error(
            api.create_reading(
                well["id"],
                good_reading_payload(
                    "2026-08-10T01:00:00Z",
                    methane_pct=54.0,
                    oxygen_pct=0.9,
                    nitrogen_pct=4.0,
                    temperature_f=119.0,
                    flow_scfm=470.0,
                    vacuum_inhg=22.0,
                ),
                technician_headers,
            ),
            ApiErrorId.ERR_READING_OUT_OF_ORDER.value,
        )

        unchanged = fixtures.read_well(well["id"])
        assert unchanged["current_flow_scfm"] == approx_2dp(480.0)
        assert unchanged["consecutive_good_readings"] == 1

        _, meta = validate_paginated(
            api.list_readings(
                well["id"], technician_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1

    def test_reading_against_a_well_locked_out_for_maintenance_is_refused(
        self, api, technician_headers
    ):
        """PRD §3.2: "A well that is currently locked out for maintenance accepts no
        readings at all and reports `ERR_WELL_IN_LOCKOUT`."
        PRD §3.3: "On success, `actual_start_at` is stamped from `current_utc`, the well
        moves from whichever of those three states it occupied into
        `MAINTENANCE_LOCKOUT`, the well's `lockout_work_order_id` is set to the job's
        identifier, its `current_flow_scfm` drops to 0, and the site's collected flow and
        efficiency are recomputed — which, as always, may starve an upgrading plant and
        fire the shortfall cascade."

        Design: Corner/state_machines/tuning_reading_on_locked_out_well_returns_well_in_lockout
        """
        site, (well,) = _site_with_wells("W-01")
        work_order = fixtures.setup_work_order_in_progress(
            well["id"], work_type="LATERAL_REPAIR"
        )

        validate_error(
            api.create_reading(
                well["id"],
                good_reading_payload("2026-08-10T01:00:00Z", flow_scfm=480.0),
                technician_headers,
            ),
            ApiErrorId.ERR_WELL_IN_LOCKOUT.value,
        )

        locked = fixtures.read_well(well["id"])
        assert locked["operating_state"] == "MAINTENANCE_LOCKOUT"
        assert locked["lockout_work_order_id"] == work_order["id"]

        _, meta = validate_paginated(
            api.list_readings(
                well["id"], technician_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
