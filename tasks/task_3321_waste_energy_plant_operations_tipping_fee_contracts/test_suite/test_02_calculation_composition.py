"""Combinatorial formula tests: capacity payment proration, metals settlement
rounding order, and the pinned report evaluation order."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    make_boiler,
    make_active_ppa,
    create_energy_delivery_payload,
    create_metals_recovery_contract_payload,
    create_metals_recovery_batch_payload,
    create_daily_throughput_report_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
ET = TEST_USERS["energy_trader_headers"]


class TestCapacityPaymentDeratedProration:
    def _setup(self):
        make_boiler(name="Boiler-A")  # ONLINE 50 MW
        b2 = make_boiler(name="Boiler-B")
        get_success_data(api_client.derate_boiler(b2["id"], {"derated_capacity_mw": 30}, PO))
        ppa = make_active_ppa()  # contracted 60 MW, 200000 c/MW-month
        return ppa

    def test_derated_boiler_clamps_available_mw_in_prorated_payment(self):
        """PRD §3.7: "For a `PPA` agreement it is the prorated capacity payment: the lesser of the agreement's `contracted_mw` and the plant's available megawatts at submission time — available megawatts being the sum over boilers of effective capacity, counting a `DERATED` boiler at its `derated_capacity_mw`, an `ONLINE` boiler at its `max_thermal_capacity_mw`, and any other boiler at zero — multiplied by the agreement's `capacity_payment_cents_per_mw_month`, multiplied by the period fraction."
        PRD §3.7: "The period fraction is the length of the delivery's period in seconds divided by the number of seconds in the UTC calendar month containing `period_start`, computed to six decimal places and capped at one so an over-long period can never bill more than a full month."

        Design: Difficulty/combinatorial_formula/capacity_payment_derated_proration
        """
        ppa = self._setup()
        # available_mw = 50 (ONLINE) + 30 (DERATED) = 80; min(60, 80) = 60;
        # fraction = 10 days / 31 October days = 0.322581; 60 * 200000 * 0.322581
        # = 3870972 (round_half_up).
        ed = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(
                    ppa_id=ppa["id"],
                    period_start="2026-10-01T00:00:00Z",
                    period_end="2026-10-11T00:00:00Z",
                    delivered_mwh=500,
                ),
                ET,
            ),
            expected_status=201,
        )
        assert ed["capacity_payment_cents"] == 3870972
        assert ed["billed_amount_cents"] == 3750000

    def test_contracted_mw_below_available_mw_still_prorates_by_period_fraction(self):
        """PRD §3.7: "the lesser of the agreement's `contracted_mw` and the plant's available megawatts at submission time"
        PRD §3.7: "The result is rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/capacity_payment_derated_proration
        """
        ppa = self._setup()
        # Repeating the same 10-of-31-day period yields the identical proration:
        # the min() input that clamps here is contracted_mw (60 < 80).
        ed = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(
                    ppa_id=ppa["id"],
                    period_start="2026-10-01T00:00:00Z",
                    period_end="2026-10-11T00:00:00Z",
                    delivered_mwh=100,
                ),
                ET,
            ),
            expected_status=201,
        )
        assert ed["capacity_payment_cents"] == 3870972
        # Billing uses the contracted rate regardless of the capacity payment.
        assert ed["billed_amount_cents"] == 750000


class TestMetalsSettlementPerLineRoundingOrder:
    def _setup_contract(self):
        return get_success_data(
            api_client.create_metals_recovery_contract(create_metals_recovery_contract_payload(), CM)
        )

    def test_per_line_rounding_produces_pinned_settlement_figures(self):
        """PRD §3.8: "Settlement fields are computed with a pinned rounding order: each recovered-tonnage line is rounded to three decimal places first, then multiplied by its price, then each revenue line is rounded half-up to whole cents, then summed — summing raw values and rounding once at the end produces different cents and is forbidden."

        Design: Difficulty/combinatorial_formula/metals_settlement_per_line_rounding_order
        """
        contract = self._setup_contract()
        batch = validate_success(
            api_client.create_metals_recovery_batch(
                create_metals_recovery_batch_payload(contract_id=contract["id"]), PO
            ),
            expected_status=201,
        )
        # ferrous = round3(100 * 0.10) = 10; revenue = round_half_up(10 * 30000) = 300000
        # nonferrous = round3(100 * 0.02) = 2; revenue = round_half_up(2 * 120000) = 240000
        assert batch["ferrous_tonnes"] == pytest.approx(10.0, abs=1e-9)
        assert batch["nonferrous_tonnes"] == pytest.approx(2.0, abs=1e-9)
        assert batch["gross_revenue_cents"] == 540000

    def test_fee_and_net_derive_from_the_same_pinned_lines(self):
        """PRD §3.8: "The `processing_fee_cents` is the `ash_input_tonnes` multiplied by the contract's `processing_fee_cents_per_tonne`, rounded half-up to whole cents, and `net_settlement_cents` is the gross revenue minus the processing fee."

        Design: Difficulty/combinatorial_formula/metals_settlement_per_line_rounding_order
        """
        contract = self._setup_contract()
        batch = validate_success(
            api_client.create_metals_recovery_batch(
                create_metals_recovery_batch_payload(contract_id=contract["id"]), PO
            ),
            expected_status=201,
        )
        assert batch["processing_fee_cents"] == 250000
        assert batch["net_settlement_cents"] == 290000
        assert batch["net_settlement_cents"] == (
            batch["gross_revenue_cents"] - batch["processing_fee_cents"]
        )


class TestSteamOutputPinnedEvaluationOrder:
    def _setup_boilers(self):
        make_boiler(name="Boiler-A")
        make_boiler(name="Boiler-B")

    def test_report_exceeds_capacity_yet_still_computes_all_fields_in_order(self):
        """PRD §3.6: "Four computed fields are produced in a pinned evaluation order. First, `thermal_input_mw` is computed as the `waste_processed_tonnes` multiplied by the `avg_heating_value_mj_per_kg`, multiplied by 1000 kilograms per tonne, divided by 3600 seconds per hour, divided by the `operating_hours`, rounded half-up to three decimal places."
        PRD §3.6: "Second, the `capacity_check` compares that thermal input against the sum of effective capacities over all boilers, where a `DERATED` boiler contributes its `derated_capacity_mw`, an `ONLINE` boiler contributes its `max_thermal_capacity_mw`, and a boiler in `OUTAGE` or `OFFLINE` contributes zero; the check is `OK` when the thermal input is less than or equal to that sum — a report landing exactly at capacity passes — and `EXCEEDS` otherwise."

        Design: Difficulty/combinatorial_formula/steam_output_pinned_evaluation_order
        """
        self._setup_boilers()
        # 2400 * 6.0 * 1000 / 3600 / 24 = 166.667 MW > 100 MW effective capacity.
        report = validate_success(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-10",
                    waste_processed_tonnes=2400,
                    avg_heating_value_mj_per_kg=6.0,
                    operating_hours=24,
                ),
                PO,
            ),
            expected_status=201,
        )
        assert report["thermal_input_mw"] == pytest.approx(166.667, abs=1e-9)
        assert report["capacity_check"] == "EXCEEDS"
        assert report["status"] == "DRAFT"

    def test_steam_and_ash_computed_from_the_uncapped_thermal_input(self):
        """PRD §3.6: "Third, `steam_output_tph` is the raw steam figure — the thermal input from the first step multiplied by the plant's steam efficiency of 0.32 tonnes of steam per hour per megawatt — capped at the boiler steam cap, which is the sum of `max_steam_tph` over boilers in `ONLINE` or `DERATED` status; the result is rounded half-up to three decimal places."
        PRD §3.6: "Fourth, `ash_generated_tonnes` is one quarter of the `waste_processed_tonnes`, rounded half-up to three decimal places."

        Design: Difficulty/combinatorial_formula/steam_output_pinned_evaluation_order
        """
        self._setup_boilers()
        # raw steam = 166.667 * 0.32 = 53.333 tph; steam cap 120 tph non-binding;
        # ash = 2400 * 0.25 = 600 t.
        report = validate_success(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-10",
                    waste_processed_tonnes=2400,
                    avg_heating_value_mj_per_kg=6.0,
                    operating_hours=24,
                ),
                PO,
            ),
            expected_status=201,
        )
        assert report["steam_output_tph"] == pytest.approx(53.333, abs=1e-9)
        assert report["ash_generated_tonnes"] == pytest.approx(600.0, abs=1e-9)
