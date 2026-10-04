"""Cross-entity state dependency tests: delivery acceptance gated on boiler
availability, and batch settlement gated on the parent contract's state."""
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
    make_outage_with_approved_plan,
    start_outage,
    create_metals_recovery_contract_payload,
    create_metals_recovery_batch_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


class TestDeliveryAcceptBlockedWhenAllBoilersDown:
    def _setup(self):
        m1 = make_municipality()
        boiler = make_boiler(max_thermal_capacity_mw=150, max_steam_tph=500)
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery = make_received_delivery(agreement["id"], manifest_ref="MAN-1")
        outage, plan = make_outage_with_approved_plan(boiler=boiler)
        return agreement, delivery, outage, boiler

    def test_accept_rejected_while_sole_boiler_is_in_outage(self):
        """PRD §3.3: "A `PlantOperator` accepts a delivery only while its agreement is `ACTIVE` and at least one boiler is in `ONLINE` or `DERATED` status; with no boiler able to take the load, the accept is rejected with `ERR_NO_BOILER_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/delivery_accept_blocked_when_all_boilers_down
        """
        agreement, delivery, outage, boiler = self._setup()
        start_outage(outage, boiler)

        resp = api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_NO_BOILER_AVAILABLE)

        fresh = validate_success(api_client.get_waste_delivery(delivery["id"], PO))
        assert fresh["status"] == "RECEIVED"

    def test_completing_the_outage_unblocks_the_same_accept(self):
        """PRD §3.4: "Completing an `ACTIVE` outage returns the boiler to `ONLINE` and clears its `derated_capacity_mw` to null, again incrementing both versions."
        PRD §3.3: "A `PlantOperator` accepts a delivery only while its agreement is `ACTIVE` and at least one boiler is in `ONLINE` or `DERATED` status; with no boiler able to take the load, the accept is rejected with `ERR_NO_BOILER_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/delivery_accept_blocked_when_all_boilers_down
        """
        agreement, delivery, outage, boiler = self._setup()
        started, _ = start_outage(outage, boiler)

        resp = api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_NO_BOILER_AVAILABLE)

        get_success_data(api_client.complete_outage_window(outage["id"], PO))

        accepted = get_success_data(
            api_client.accept_waste_delivery(
                delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["tipping_fee_cents"] == 80000


class TestBatchSettleBlockedWhenContractSuspended:
    def _setup(self):
        contract = get_success_data(
            api_client.create_metals_recovery_contract(create_metals_recovery_contract_payload(), CM)
        )
        batch = get_success_data(
            api_client.create_metals_recovery_batch(
                create_metals_recovery_batch_payload(contract_id=contract["id"]), PO
            )
        )
        get_success_data(api_client.suspend_metals_recovery_contract(contract["id"], CM))
        return contract, batch

    def test_settle_against_suspended_contract_is_invalid_state(self):
        """PRD §3.8: "Settling moves a `RECORDED` batch to the terminal `SETTLED` status, but only while its contract is `ACTIVE`."
        PRD §2.6: "this category also covers referenced parents that must be in a permitting state (for example, an agreement that must be `ACTIVE` before a delivery under it can be accepted)."

        Design: Difficulty/cross_entity_state_dependency/batch_settle_blocked_when_contract_suspended
        """
        contract, batch = self._setup()
        resp = api_client.settle_metals_recovery_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_settle_leaves_batch_recorded(self):
        """PRD §3.8: "Settling moves a `RECORDED` batch to the terminal `SETTLED` status, but only while its contract is `ACTIVE`. Disputing moves a `RECORDED` batch to `DISPUTED`, and resolving moves a `DISPUTED` batch back to `RECORDED`, recomputing every settlement field from the contract's current rates at resolution time."

        Design: Difficulty/cross_entity_state_dependency/batch_settle_blocked_when_contract_suspended
        """
        contract, batch = self._setup()
        resp = api_client.settle_metals_recovery_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        fresh = validate_success(api_client.get_metals_recovery_batch(batch["id"], CM))
        assert fresh["status"] == "RECORDED"
