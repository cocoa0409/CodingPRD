"""Invariant tests: conserved quantities across failure and success paths."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_received_delivery,
    make_landfill,
    make_pending_shipment,
    complete_shipment,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
EO = TEST_USERS["environmental_officer_headers"]


class TestLandfillCapacityConserved:
    def _setup(self):
        landfill = make_landfill(remaining_capacity_tonnes=1000, daily_receipt_limit_tonnes=500)
        s1, _ = make_pending_shipment(
            landfill["id"], passed=True, tonnes=10, shipped_on="2026-09-06"
        )
        # Give S1 a failing test so its completion must fail with ERR_ASH_TEST_FAILED.
        get_success_data(
            api_client.create_ash_test(
                s1["id"], {"parameter": "TCLP-lead", "measured_value": 6.0, "limit_value": 5.0}, EO
            )
        )
        s2, landfill = make_pending_shipment(
            landfill["id"], passed=True, tonnes=10, shipped_on="2026-09-07"
        )
        return landfill, s1, s2

    def test_failed_completion_and_rejection_conserve_capacity_exactly(self):
        """PRD §3.9: "At least one ash test must have been recorded for the shipment — completing with none is rejected with `ERR_TEST_REQUIRED` — and every recorded test must have `passed`; a failing test rejects completion with `ERR_ASH_TEST_FAILED`."
        PRD §3.9: "On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`, and if that brings it to exactly zero the landfill's status becomes `CLOSED`, after which further shipments to it are rejected; both the shipment's and the landfill's `version` increment. A shipment under testing that will not proceed is instead moved to the terminal `REJECTED` status with a `reject_reason` supplied."

        Design: Difficulty/compensating_invariant/landfill_capacity_conserved_through_failure_and_success
        """
        landfill, s1, s2 = self._setup()

        resp = api_client.complete_ash_shipment(
            s1["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_ASH_TEST_FAILED)

        get_success_data(
            api_client.reject_ash_shipment(s1["id"], {"reject_reason": "failed TCLP"}, EO)
        )

        mid = validate_success(api_client.get_landfill(landfill["id"], EO))
        # Failed completion plus rejection: zero debit.
        assert mid["remaining_capacity_tonnes"] == pytest.approx(1000, abs=1e-9)

    def test_successful_completion_debits_exactly_the_shipment_tonnes(self):
        """PRD §3.9: "On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`"
        PRD §3.9: "the daily receipt cap must hold: the sum of tonnes of shipments already `DISPOSED` at that landfill on the same `shipped_on` day, plus this shipment's tonnes, must be at most the landfill's `daily_receipt_limit_tonnes`."

        Design: Difficulty/compensating_invariant/landfill_capacity_conserved_through_failure_and_success
        """
        landfill, s1, s2 = self._setup()

        resp = api_client.complete_ash_shipment(
            s1["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_ASH_TEST_FAILED)
        get_success_data(
            api_client.reject_ash_shipment(s1["id"], {"reject_reason": "failed TCLP"}, EO)
        )

        mid = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert mid["remaining_capacity_tonnes"] == pytest.approx(1000, abs=1e-9)

        completed = complete_shipment(s2, mid)
        assert completed["status"] == "DISPOSED"

        final = validate_success(api_client.get_landfill(landfill["id"], EO))
        # 1000 - 10 from S2; the REJECTED S1 contributed zero.
        assert final["remaining_capacity_tonnes"] == pytest.approx(990, abs=1e-9)


class TestAgreementTonnageConservedThroughRejectCycle:
    def _setup(self):
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(
            municipality_id=m1["id"],
            guaranteed_annual_tonnage=1000,
            tipping_fee_per_tonne_cents=8500,
        )
        d1 = make_received_delivery(
            agreement["id"], manifest_ref="MAN-A", tonnes=400, delivered_at="2026-09-01T08:00:00Z"
        )
        d2 = make_received_delivery(
            agreement["id"], manifest_ref="MAN-B", tonnes=300, delivered_at="2026-09-02T08:00:00Z"
        )
        return agreement, d1, d2

    def test_rejected_delivery_contributes_zero_to_cumulative_tonnage(self):
        """PRD §3.2: "Thereafter the agreement accumulates delivered tonnage in its computed `cumulative_delivered_tonnes` field, which is the sum of tonnes on `ACCEPTED` deliveries for the agreement since `term_start` and is recomputed on every delivery state change."
        PRD §3.11: "The delivered base is the sum of tonnes of the agreement's deliveries in `ACCEPTED` status whose `delivered_at` falls inside the period — the period end exclusive — with `REJECTED` and `DIVERTED` rows excluded, carried to three decimal places."

        Design: Difficulty/compensating_invariant/agreement_tonnage_conserved_through_reject_cycle
        """
        agreement, d1, d2 = self._setup()
        get_success_data(
            api_client.accept_waste_delivery(
                d1["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )
        get_success_data(
            api_client.reject_waste_delivery(d2["id"], {"reject_reason": "contaminated load"}, PO)
        )

        fresh = validate_success(api_client.get_waste_supply_agreement(agreement["id"], CM))
        assert fresh["cumulative_delivered_tonnes"] == pytest.approx(400, abs=1e-9)

    def test_settlement_base_tracks_the_accepted_tonnage_ledger(self):
        """PRD §3.11: "The delivered base is the sum of tonnes of the agreement's deliveries in `ACCEPTED` status whose `delivered_at` falls inside the period — the period end exclusive — with `REJECTED` and `DIVERTED` rows excluded, carried to three decimal places."
        PRD §3.11: "The shortfall in cents is the shortfall tonnage multiplied by the `tipping_fee_per_tonne_cents`, rounded half-up to whole cents."

        Design: Difficulty/compensating_invariant/agreement_tonnage_conserved_through_reject_cycle
        """
        agreement, d1, d2 = self._setup()
        get_success_data(
            api_client.accept_waste_delivery(
                d1["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )
        get_success_data(
            api_client.reject_waste_delivery(d2["id"], {"reject_reason": "contaminated load"}, PO)
        )

        settlement = validate_success(
            api_client.run_put_or_pay_settlement({"agreement_id": agreement["id"]}, CM)
        )
        assert settlement["delivered_base_tonnes"] == pytest.approx(400, abs=1e-9)
        # 1000 - 400 = 600 t shortfall.
        assert settlement["shortfall_tonnes"] == pytest.approx(600, abs=1e-9)
