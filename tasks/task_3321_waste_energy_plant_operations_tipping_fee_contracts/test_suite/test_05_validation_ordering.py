"""Validation ordering tests: which error wins when a request fails for more
than one reason."""
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
    make_landfill,
    create_ash_shipment_payload,
    create_ash_test_payload,
    create_metals_recovery_contract_payload,
    create_metals_recovery_batch_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
EO = TEST_USERS["environmental_officer_headers"]


class TestAcceptOnTerminatedAgreementWithStaleVersion:
    def _setup(self):
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery = make_received_delivery(agreement["id"], manifest_ref="MAN-1")
        get_success_data(api_client.terminate_waste_supply_agreement(agreement["id"], CM))
        return agreement, delivery

    def test_state_error_wins_over_stale_version(self):
        """PRD §2.6: "The ordering means, for example, that a state error wins over a body-shape error: a request that is both addressed to a resource in the wrong state and missing a required field is rejected with the state error."
        PRD §2.6: "Target state — the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE`; this category also covers referenced parents that must be in a permitting state (for example, an agreement that must be `ACTIVE` before a delivery under it can be accepted)."

        Design: Difficulty/priority_pair_validation_conflict/accept_on_terminated_agreement_with_stale_version
        """
        agreement, delivery = self._setup()
        # The pre-termination version is now stale AND the agreement is TERMINATED;
        # the state check (category 5) runs before the OCC check (category 6).
        resp = api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_accept_leaves_delivery_unchanged(self):
        """PRD §3.3: "Acceptance moves a delivery from `RECEIVED` to `ACCEPTED` and is the point at which money changes hands. A `PlantOperator` accepts a delivery only while its agreement is `ACTIVE` and at least one boiler is in `ONLINE` or `DERATED` status"

        Design: Difficulty/priority_pair_validation_conflict/accept_on_terminated_agreement_with_stale_version
        """
        agreement, delivery = self._setup()
        resp = api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        fresh = validate_success(api_client.get_waste_delivery(delivery["id"], PO))
        assert fresh["status"] == "RECEIVED"
        assert fresh["tipping_fee_cents"] is None


class TestAshCompleteSafetyGateBeatsCapacityAndOcc:
    def _setup(self):
        landfill = make_landfill(remaining_capacity_tonnes=100, daily_receipt_limit_tonnes=50)
        shipment = get_success_data(
            api_client.create_ash_shipment(
                create_ash_shipment_payload(
                    landfill_id=landfill["id"], tonnes=200, shipped_on="2026-09-06"
                ),
                EO,
            )
        )
        get_success_data(api_client.submit_ash_shipment_testing(shipment["id"], EO))
        # One FAILING test: measured 5.5 > limit 5.0.
        get_success_data(
            api_client.create_ash_test(
                shipment["id"],
                create_ash_test_payload(measured_value=5.5, limit_value=5.0),
                EO,
            )
        )
        return landfill, shipment

    def test_failed_test_error_wins_over_capacity_and_stale_version(self):
        """PRD §3.9: "At least one ash test must have been recorded for the shipment — completing with none is rejected with `ERR_TEST_REQUIRED` — and every recorded test must have `passed`; a failing test rejects completion with `ERR_ASH_TEST_FAILED`."
        PRD §2.6: "When a request fails for more than one reason, the error returned is decided by a fixed evaluation order, not by whichever check happens to run first."

        Design: Difficulty/priority_pair_validation_conflict/ash_complete_safety_gate_beats_capacity_and_occ
        """
        landfill, shipment = self._setup()
        # 200 t exceeds remaining capacity 100 t AND the version is stale, but the
        # failed-test safety gate is the reported error.
        resp = api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": landfill["version"] + 7}, EO
        )
        validate_error(resp, ApiErrorId.ERR_ASH_TEST_FAILED)

    def test_failed_completion_leaves_landfill_capacity_unchanged(self):
        """PRD §3.9: "On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`, and if that brings it to exactly zero the landfill's status becomes `CLOSED`"
        PRD §3.9: "Breaching the capacity or daily-cap checks is rejected with `ERR_LANDFILL_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/ash_complete_safety_gate_beats_capacity_and_occ
        """
        landfill, shipment = self._setup()
        resp = api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": landfill["version"] + 7}, EO
        )
        validate_error(resp, ApiErrorId.ERR_ASH_TEST_FAILED)

        fresh = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert fresh["remaining_capacity_tonnes"] == pytest.approx(100, abs=1e-9)


class TestNotFoundBeatsBodyShape:
    def test_action_on_missing_delivery_reports_not_found(self):
        """PRD §2.7: "When an endpoint path contains a resource identifier, the server validates that the identifier references an existing resource before evaluating any other rule. Requests are rejected with `404` and `ERR_NOT_FOUND` at the first identifier in the path — checked left to right — that does not correspond to an existing resource."
        PRD §2.6: "3. Path existence — every identifier in the URL path must reference an existing resource, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/validations/not_found_beats_body_shape
        """
        resp = api_client.receive_waste_delivery(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", PO
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
