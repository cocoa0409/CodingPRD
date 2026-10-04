"""Cascade tests: outage start reducing effective capacity, and delivery
acceptance growing the put-or-pay settlement base."""
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
    make_received_delivery,
    make_accepted_delivery,
    make_outage_with_approved_plan,
    start_outage,
    create_daily_throughput_report_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


class TestOutageStartCascadesToCapacityCheck:
    def _setup(self):
        boiler = make_boiler(max_thermal_capacity_mw=150, max_steam_tph=60)
        # 540 * 10.0 * 1000 / 3600 / 10 = 150.000 MW — exactly at capacity.
        report = get_success_data(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-04",
                    waste_processed_tonnes=540,
                    avg_heating_value_mj_per_kg=10.0,
                    operating_hours=10,
                ),
                PO,
            )
        )
        outage, plan = make_outage_with_approved_plan(boiler=boiler)
        return boiler, report, outage

    def test_outage_start_flips_report_capacity_check_to_exceeds(self):
        """PRD §3.4: "On start, the boiler's status becomes `OUTAGE`, which drops it out of the effective capacity pool used by daily throughput reporting, so the next report's capacity check is computed against the reduced capacity; both the outage's and the boiler's `version` increment."
        PRD §3.6: "a boiler in `OUTAGE` or `OFFLINE` contributes zero"

        Design: Difficulty/transitive_cascade/outage_start_cascades_to_boiler_and_capacity_check
        """
        boiler, report, outage = self._setup()
        assert report["capacity_check"] == "OK"

        start_outage(outage, boiler)
        fresh_boiler = validate_success(api_client.get_boiler(boiler["id"], PO))
        assert fresh_boiler["status"] == "OUTAGE"

        updated = get_success_data(
            api_client.update_daily_throughput_report(report["id"], {"waste_processed_tonnes": 500}, PO)
        )
        assert updated["capacity_check"] == "EXCEEDS"

    def test_report_over_capacity_after_outage_cannot_be_finalized(self):
        """PRD §3.6: "finalizing a report whose thermal input exceeds effective boiler capacity is rejected with `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/transitive_cascade/outage_start_cascades_to_boiler_and_capacity_check
        """
        boiler, report, outage = self._setup()
        start_outage(outage, boiler)
        updated = get_success_data(
            api_client.update_daily_throughput_report(report["id"], {"waste_processed_tonnes": 500}, PO)
        )
        assert updated["capacity_check"] == "EXCEEDS"

        resp = api_client.finalize_daily_throughput_report(report["id"], PO)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestDeliveryAcceptCascadesToSettlementBase:
    def _setup(self):
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(
            municipality_id=m1["id"],
            guaranteed_annual_tonnage=1000,
            tipping_fee_per_tonne_cents=8500,
        )
        agreement = make_accepted_delivery(
            agreement, manifest_ref="MAN-400", tonnes=400, delivered_at="2026-09-01T08:00:00Z"
        )[1]
        agreement = make_accepted_delivery(
            agreement, manifest_ref="MAN-300", tonnes=300, delivered_at="2026-09-02T08:00:00Z"
        )[1]
        delivery = make_received_delivery(
            agreement["id"], manifest_ref="MAN-FINAL", tonnes=300, delivered_at="2026-09-03T08:00:00Z"
        )
        return agreement, delivery

    def test_accept_drops_shortfall_from_three_hundred_tonnes_to_zero(self):
        """PRD §3.3: "The agreement's `cumulative_delivered_tonnes` grows by the delivery's `tonnes`, so the put-or-pay base grows immediately, and both the delivery's and the agreement's `version` increment by one."
        PRD §3.11: "The delivered base is the sum of tonnes of the agreement's deliveries in `ACCEPTED` status whose `delivered_at` falls inside the period — the period end exclusive — with `REJECTED` and `DIVERTED` rows excluded, carried to three decimal places."

        Design: Difficulty/transitive_cascade/delivery_accept_cascades_to_settlement_base
        """
        agreement, delivery = self._setup()

        s1 = validate_success(api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM))
        assert s1["shortfall_tonnes"] == pytest.approx(300, abs=1e-9)
        assert s1["shortfall_cents"] == 2550000

        accepted = get_success_data(
            api_client.accept_waste_delivery(
                delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )
        assert accepted["status"] == "ACCEPTED"

        s2 = validate_success(api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM))
        assert s2["shortfall_tonnes"] == pytest.approx(0, abs=1e-9)
        assert s2["shortfall_cents"] == 0

    def test_cumulative_tonnage_reflects_every_accepted_delivery(self):
        """PRD §3.2: "Thereafter the agreement accumulates delivered tonnage in its computed `cumulative_delivered_tonnes` field, which is the sum of tonnes on `ACCEPTED` deliveries for the agreement since `term_start` and is recomputed on every delivery state change."
        PRD §3.11: "a re-run for the same period supersedes the earlier record, and only the latest record per period counts toward the already-billed total."

        Design: Difficulty/transitive_cascade/delivery_accept_cascades_to_settlement_base
        """
        agreement, delivery = self._setup()

        s1 = validate_success(api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM))
        assert s1["delivered_base_tonnes"] == pytest.approx(700, abs=1e-9)

        get_success_data(
            api_client.accept_waste_delivery(
                delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )

        fresh = validate_success(api_client.get_waste_supply_agreement(agreement["id"], CM))
        assert fresh["cumulative_delivered_tonnes"] == pytest.approx(1000, abs=1e-9)
