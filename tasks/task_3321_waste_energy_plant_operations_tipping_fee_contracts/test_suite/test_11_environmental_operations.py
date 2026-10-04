"""Environmental operations tests: emissions rolling averages, put-or-pay
monthly rollover, diversion capacity, and landfill capacity rules."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_accepted_delivery,
    make_outage_with_approved_plan,
    start_outage,
    make_landfill,
    make_pending_shipment,
    make_emissions_permit,
    make_emissions_reading,
    create_waste_supply_agreement_payload,
    create_ash_shipment_payload,
    create_ash_test_payload,
    set_clock,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
EO = TEST_USERS["environmental_officer_headers"]


class TestEmissionsRollingDailyAverageBreach:
    def test_rolling_average_crossing_daily_limit_flags_exceedance(self):
        """PRD §3.10: "The daily rolling average is the mean of the values of all readings for the same permit whose `measured_at` falls inside the window from the new reading's `measured_at` minus the permit's `rolling_avg_window_hours` hours up to and including the new reading's `measured_at` — both ends inclusive, and the new reading itself is included in the mean — carried to six decimal places. A daily breach occurs when that rolling average is strictly greater than the permit's `daily_limit`."

        Design: Corner/calculations/emissions_rolling_daily_average_breach
        """
        permit = make_emissions_permit(
            pollutant="NOx", hourly_limit=200, daily_limit=130, rolling_avg_window_hours=24
        )
        r1 = make_emissions_reading(permit["id"], value=120, measured_at="2026-09-02T06:00:00Z")
        assert r1["exceedance"] is False

        r2 = make_emissions_reading(permit["id"], value=140, measured_at="2026-09-02T12:00:00Z")
        # average (120+140)/2 = 130, not > 130 — strict comparison.
        assert r2["exceedance"] is False

        r3 = make_emissions_reading(permit["id"], value=140, measured_at="2026-09-02T18:00:00Z")
        # average (120+140+140)/3 = 133.333333 > 130.
        assert r3["exceedance"] is True


class TestPutOrPayMonthlyRolloverDeduction:
    def _setup(self):
        m1 = make_municipality()
        make_boiler()
        agreement = get_success_data(
            api_client.create_waste_supply_agreement(
                create_waste_supply_agreement_payload(
                    municipality_id=m1["id"],
                    guaranteed_annual_tonnage=1200,
                    tipping_fee_per_tonne_cents=9000,
                    put_or_pay_settlement_cadence="MONTHLY",
                ),
                CM,
            )
        )
        agreement = get_success_data(api_client.activate_waste_supply_agreement(agreement["id"], CM))
        return agreement

    def test_october_billing_deducted_from_november_shortfall(self):
        """PRD §3.11: "Under the monthly cadence, earlier periods must not be billed twice: the amounts already billed for earlier periods of the same agreement are converted back to a tonnage equivalent by dividing the already-billed cents by the agreement's current `tipping_fee_per_tonne_cents`, and the shortfall is the guarantee minus the delivered base minus that tonnage equivalent, floored at zero — never negative."
        PRD §3.11: "The guarantee for the period is the agreement's `guaranteed_annual_tonnage` for an annual cadence, or one twelfth of it for a monthly cadence."

        Design: Corner/calculations/put_or_pay_monthly_rollover_deduction
        """
        agreement = self._setup()

        set_clock("2026-10-15T00:00:00Z")
        _, agreement = make_accepted_delivery(
            agreement, manifest_ref="MAN-OCT", tonnes=40, delivered_at="2026-10-10T08:00:00Z"
        )
        oct_run = validate_success(
            api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM)
        )
        # guarantee 1200/12 = 100; delivered 40 -> shortfall 60 t.
        assert oct_run["shortfall_tonnes"] == pytest.approx(60, abs=1e-9)
        assert oct_run["shortfall_cents"] == 540000

        set_clock("2026-11-15T00:00:00Z")
        _, agreement = make_accepted_delivery(
            agreement, manifest_ref="MAN-NOV", tonnes=30, delivered_at="2026-11-10T08:00:00Z"
        )
        nov_run = validate_success(
            api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM)
        )
        assert nov_run["already_billed_cents"] == 540000
        # 100 - 30 - (540000 / 9000 = 60) = 10 t.
        assert nov_run["shortfall_tonnes"] == pytest.approx(10, abs=1e-9)
        assert nov_run["shortfall_cents"] == 90000


class TestDiversionCapacityExceeded:
    def _setup(self):
        m1 = make_municipality()
        boiler = make_boiler(max_thermal_capacity_mw=150, max_steam_tph=500)
        agreement = make_active_agreement(
            municipality_id=m1["id"], guaranteed_annual_tonnage=5000
        )
        # 3-day window: 09-05 .. 09-08; cap 200 t/day -> 600 t total.
        outage, plan = make_outage_with_approved_plan(
            boiler=boiler, max_diversion_tpd=200, leg_tonnes=600
        )
        start_outage(outage, boiler)
        d1 = make_delivery(
            agreement["id"], manifest_ref="MAN-D1", tonnes=500, delivered_at="2026-09-05T08:00:00Z"
        )
        get_success_data(api_client.divert_waste_delivery(d1["id"], {"outage_id": outage["id"]}, PO))
        d2 = make_delivery(
            agreement["id"], manifest_ref="MAN-D2", tonnes=200, delivered_at="2026-09-06T08:00:00Z"
        )
        return outage, d2

    def test_divert_beyond_per_day_cap_times_outage_length_rejected(self):
        """PRD §3.5: "Diversion is capacity-bounded: the total tonnes of deliveries already `DIVERTED` under that outage, plus this delivery's tonnes, must be at most the plan's `max_diversion_tpd` multiplied by the outage's length in whole days — the length being the number of days in the exclusive-end interval from `starts_at` to `ends_at`, computed as the ceiling of the interval's seconds divided by 86400. Breaching that bound, or naming an outage that is not `ACTIVE` or has no approved plan, is rejected with `ERR_DIVERSION_CAPACITY_EXCEEDED`."

        Design: Corner/errors/error_diversion_capacity_exceeded_triggered
        """
        outage, d2 = self._setup()
        # 500 + 200 = 700 > 200 * 3 = 600.
        resp = api_client.divert_waste_delivery(d2["id"], {"outage_id": outage["id"]}, PO)
        validate_error(resp, ApiErrorId.ERR_DIVERSION_CAPACITY_EXCEEDED)

        fresh = validate_success(api_client.get_waste_delivery(d2["id"], PO))
        assert fresh["status"] == "SCHEDULED"


class TestLandfillCapacityExceeded:
    def test_daily_receipt_limit_breach_rejected_and_state_unchanged(self):
        """PRD §3.9: "the daily receipt cap must hold: the sum of tonnes of shipments already `DISPOSED` at that landfill on the same `shipped_on` day, plus this shipment's tonnes, must be at most the landfill's `daily_receipt_limit_tonnes`. Breaching the capacity or daily-cap checks is rejected with `ERR_LANDFILL_CAPACITY`."

        Design: Corner/errors/error_landfill_capacity_triggered
        """
        landfill = make_landfill(remaining_capacity_tonnes=1000, daily_receipt_limit_tonnes=50)
        shipment, landfill = make_pending_shipment(
            landfill["id"], passed=True, tonnes=60, shipped_on="2026-09-06"
        )

        resp = api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_LANDFILL_CAPACITY)

        fresh_shipment = validate_success(api_client.get_ash_shipment(shipment["id"], EO))
        fresh_landfill = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert fresh_shipment["status"] == "TEST_PENDING"
        assert fresh_landfill["remaining_capacity_tonnes"] == pytest.approx(1000, abs=1e-9)


class TestLandfillAutoCloseAtZero:
    def test_draining_to_zero_closes_landfill_and_blocks_next_completion(self):
        """PRD §3.9: "On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`, and if that brings it to exactly zero the landfill's status becomes `CLOSED`, after which further shipments to it are rejected; both the shipment's and the landfill's `version` increment."
        PRD §2.6: "this category also covers referenced parents that must be in a permitting state (for example, an agreement that must be `ACTIVE` before a delivery under it can be accepted)."

        Design: Corner/errors/landfill_auto_closes_at_zero_and_rejects_new_completions
        """
        landfill = make_landfill(remaining_capacity_tonnes=30, daily_receipt_limit_tonnes=100)
        s1, landfill = make_pending_shipment(
            landfill["id"], passed=True, tonnes=30, shipped_on="2026-09-06"
        )
        s2, _ = make_pending_shipment(
            landfill["id"], passed=True, tonnes=1, shipped_on="2026-09-07"
        )

        get_success_data(
            api_client.complete_ash_shipment(
                s1["id"], {"expected_landfill_version": landfill["version"]}, EO
            )
        )
        drained = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert drained["remaining_capacity_tonnes"] == pytest.approx(0, abs=1e-9)
        assert drained["status"] == "CLOSED"

        resp = api_client.complete_ash_shipment(
            s2["id"], {"expected_landfill_version": drained["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
