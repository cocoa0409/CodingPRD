"""Boundary precision tests: capacity equality, emissions equality, the empty
test set, and the tip-floor inclusive cap with host override."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_host_municipality,
    make_host_agreement,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_landfill,
    make_emissions_permit,
    make_emissions_reading,
    create_daily_throughput_report_payload,
    create_ash_shipment_payload,
    create_ash_test_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

PO = TEST_USERS["plant_operator_headers"]
EO = TEST_USERS["environmental_officer_headers"]


class TestCapacityCheckBoundary:
    def _setup(self):
        make_boiler(max_thermal_capacity_mw=150, max_steam_tph=500)

    def test_thermal_input_exactly_at_capacity_finalizes(self):
        """PRD §3.6: "the check is `OK` when the thermal input is less than or equal to that sum — a report landing exactly at capacity passes — and `EXCEEDS` otherwise."
        PRD §3.6: "Finalizing a report moves it from `DRAFT` to the terminal `FINALIZED` status and is permitted only when the report's `capacity_check` is `OK`"

        Design: Difficulty/boundary_precision_check/capacity_check_equality_is_ok_and_one_unit_over_fails
        """
        self._setup()
        # 540 * 10.0 * 1000 / 3600 / 10 = 150.000 MW == 150 MW capacity.
        report = get_success_data(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-11",
                    waste_processed_tonnes=540,
                    avg_heating_value_mj_per_kg=10.0,
                    operating_hours=10,
                ),
                PO,
            )
        )
        assert report["thermal_input_mw"] == pytest.approx(150.0, abs=1e-9)
        assert report["capacity_check"] == "OK"

        finalized = get_success_data(api_client.finalize_daily_throughput_report(report["id"], PO))
        assert finalized["status"] == "FINALIZED"

    def test_one_step_over_capacity_is_exceeds_and_finalize_rejected(self):
        """PRD §3.6: "the check is `OK` when the thermal input is less than or equal to that sum — a report landing exactly at capacity passes — and `EXCEEDS` otherwise."
        PRD §3.6: "finalizing a report whose thermal input exceeds effective boiler capacity is rejected with `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/capacity_check_equality_is_ok_and_one_unit_over_fails
        """
        self._setup()
        # 541 * 10.0 * 1000 / 3600 / 10 = 150.277... MW > 150 MW.
        report = get_success_data(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-12",
                    waste_processed_tonnes=541,
                    avg_heating_value_mj_per_kg=10.0,
                    operating_hours=10,
                ),
                PO,
            )
        )
        assert report["thermal_input_mw"] == pytest.approx(150.278, abs=1e-3)
        assert report["capacity_check"] == "EXCEEDS"

        resp = api_client.finalize_daily_throughput_report(report["id"], PO)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

        fresh = validate_success(api_client.get_daily_throughput_report(report["id"], PO))
        assert fresh["status"] == "DRAFT"


class TestEmissionsLimitEquality:
    def _setup_permit(self):
        return make_emissions_permit(
            pollutant="NOx", hourly_limit=200, daily_limit=150, rolling_avg_window_hours=24
        )

    def test_reading_exactly_at_hourly_limit_is_not_a_breach(self):
        """PRD §3.10: "An hourly breach occurs when the reading's `value` is strictly greater than the permit's `hourly_limit` — a value exactly equal to the limit is not a breach."

        Design: Difficulty/boundary_precision_check/emissions_limit_equality_is_not_a_breach
        """
        permit = self._setup_permit()
        make_emissions_reading(permit["id"], value=100, measured_at="2026-09-02T06:00:00Z")
        make_emissions_reading(permit["id"], value=100, measured_at="2026-09-02T12:00:00Z")

        reading = make_emissions_reading(permit["id"], value=200, measured_at="2026-09-02T18:00:00Z")
        # 200 is not > 200; rolling average (100+100+200)/3 = 133.333333 <= 150.
        assert reading["exceedance"] is False

    def test_hourly_limit_breach_requires_strictly_greater_value(self):
        """PRD §3.10: "A daily breach occurs when that rolling average is strictly greater than the permit's `daily_limit`. The reading's `exceedance` is true when either breach fires."
        PRD §3.10: "An hourly breach occurs when the reading's `value` is strictly greater than the permit's `hourly_limit` — a value exactly equal to the limit is not a breach."

        Design: Difficulty/boundary_precision_check/emissions_limit_equality_is_not_a_breach
        """
        # daily_limit=250 keeps the daily rolling average below the daily limit so
        # the exceedance outcome is decided by the hourly comparison alone.
        permit = make_emissions_permit(
            pollutant="SO2", hourly_limit=200, daily_limit=250, rolling_avg_window_hours=24
        )
        at_limit = make_emissions_reading(permit["id"], value=200, measured_at="2026-09-02T06:00:00Z")
        assert at_limit["exceedance"] is False

        # 201 > 200 is an hourly breach.
        over = make_emissions_reading(permit["id"], value=201, measured_at="2026-09-02T12:00:00Z")
        assert over["exceedance"] is True


class TestEmptyTestSetBlocksCompletion:
    def _setup(self):
        landfill = make_landfill(remaining_capacity_tonnes=1000, daily_receipt_limit_tonnes=500)
        shipment = get_success_data(
            api_client.create_ash_shipment(
                create_ash_shipment_payload(
                    landfill_id=landfill["id"], tonnes=10, shipped_on="2026-09-06"
                ),
                EO,
            )
        )
        get_success_data(api_client.submit_ash_shipment_testing(shipment["id"], EO))
        return landfill, shipment

    def test_zero_tests_rejected_with_test_required(self):
        """PRD §3.9: "At least one ash test must have been recorded for the shipment — completing with none is rejected with `ERR_TEST_REQUIRED`"

        Design: Difficulty/boundary_precision_check/empty_test_set_blocks_ash_completion
        """
        landfill, shipment = self._setup()
        resp = api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_TEST_REQUIRED)

        fresh = validate_success(api_client.get_ash_shipment(shipment["id"], EO))
        assert fresh["status"] == "TEST_PENDING"

    def test_one_passing_test_flips_completion_to_success(self):
        """PRD §3.9: "At least one ash test must have been recorded for the shipment — completing with none is rejected with `ERR_TEST_REQUIRED` — and every recorded test must have `passed`; a failing test rejects completion with `ERR_ASH_TEST_FAILED`."
        PRD §3.9: "On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`, and if that brings it to exactly zero the landfill's status becomes `CLOSED`, after which further shipments to it are rejected; both the shipment's and the landfill's `version` increment."

        Design: Difficulty/boundary_precision_check/empty_test_set_blocks_ash_completion
        """
        landfill, shipment = self._setup()
        resp = api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_TEST_REQUIRED)

        get_success_data(
            api_client.create_ash_test(
                shipment["id"], create_ash_test_payload(measured_value=4.0, limit_value=5.0), EO
            )
        )
        completed = get_success_data(
            api_client.complete_ash_shipment(
                shipment["id"], {"expected_landfill_version": landfill["version"]}, EO
            )
        )
        assert completed["status"] == "DISPOSED"

        fresh_landfill = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert fresh_landfill["remaining_capacity_tonnes"] == pytest.approx(990, abs=1e-9)


class TestTipFloorInclusiveBoundaryAndHostOverride:
    def _setup(self):
        m1 = make_municipality()
        h1 = make_host_municipality()
        make_host_agreement(h1["id"])
        a1 = make_active_agreement(
            municipality_id=m1["id"], guaranteed_annual_tonnage=5000
        )
        a2 = make_active_agreement(
            municipality_id=h1["id"], guaranteed_annual_tonnage=5000
        )
        make_delivery(a1["id"], manifest_ref="MAN-990", tonnes=990, delivered_at="2026-09-03T08:00:00Z")
        d10 = make_delivery(a1["id"], manifest_ref="MAN-10", tonnes=10, delivered_at="2026-09-03T09:00:00Z")
        dh = make_delivery(a2["id"], manifest_ref="MAN-H20", tonnes=20, delivered_at="2026-09-04T11:00:00Z")
        return a1, d10, dh

    def test_delivery_landing_exactly_at_the_cap_is_allowed(self):
        """PRD §3.3: "The plant accepts at most 1000 tonnes per UTC calendar day: the total tonnes of same-day deliveries in `SCHEDULED` or `RECEIVED` status — deliveries already `ACCEPTED`, `REJECTED`, or `DIVERTED` do not count against the cap — plus this delivery's tonnes must be at most 1000. The comparison is inclusive: a delivery that lands the day exactly at the cap is allowed through."

        Design: Corner/calculations/tip_floor_cap_inclusive_boundary_and_host_override
        """
        a1, d10, _dh = self._setup()
        # 990 + 10 = 1000 — the day lands exactly at the cap, inclusive: allowed.
        received = get_success_data(api_client.receive_waste_delivery(d10["id"], PO))
        assert received["status"] == "RECEIVED"

        # 1000 + 11 > 1000 for a STANDARD municipality.
        d11 = make_delivery(a1["id"], manifest_ref="MAN-11", tonnes=11, delivered_at="2026-09-03T10:00:00Z")
        resp = api_client.receive_waste_delivery(d11["id"], PO)
        validate_error(resp, ApiErrorId.ERR_PRIORITY_NOT_AVAILABLE)

    def test_host_priority_overrides_the_exhausted_cap(self):
        """PRD §3.3: "When the delivery's municipality is the host community and holds a host community agreement whose effective window contains the logical clock now and whose `local_waste_priority_enabled` is `true`, the cap check is skipped entirely and the receive is always allowed — host waste takes priority. When the cap is exceeded and no effective priority agreement covers the delivery, the receive is rejected with `ERR_PRIORITY_NOT_AVAILABLE`."

        Design: Corner/calculations/tip_floor_cap_inclusive_boundary_and_host_override
        """
        a1, d10, dh = self._setup()
        get_success_data(api_client.receive_waste_delivery(d10["id"], PO))
        d11 = make_delivery(a1["id"], manifest_ref="MAN-11", tonnes=11, delivered_at="2026-09-03T10:00:00Z")
        resp = api_client.receive_waste_delivery(d11["id"], PO)
        validate_error(resp, ApiErrorId.ERR_PRIORITY_NOT_AVAILABLE)

        # Exhaust dh's own UTC day with a STANDARD delivery of 1000 tonnes.
        make_delivery(a1["id"], manifest_ref="MAN-1000-D2", tonnes=1000, delivered_at="2026-09-04T08:00:00Z")

        # Host-community delivery: 1000 + 20 > 1000, but the cap check is skipped.
        received = get_success_data(api_client.receive_waste_delivery(dh["id"], PO))
        assert received["status"] == "RECEIVED"
