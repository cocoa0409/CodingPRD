"""Fixing the floating legs: the immutable order row, the volume-weighted leg
price, the component rules per contract type, and the two axes that advance
independently of one another."""

import pytest

from test_helpers import (
    ApiErrorId,
    apply_ticket,
    assert_contract_pricing_invariants,
    assert_pricing_order,
    create_pricing_order_payload,
    mark_position,
    new_pricing_order,
    read_contract,
    read_position,
    read_ticket,
    setup_contract_scenario,
    setup_graded_ticket_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


MERCH = TEST_USERS["merchandiser_headers"]
TRADER = TEST_USERS["futures_trader_headers"]


class TestPricingOrderRow:

    def test_a_pricing_order_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.4: "One entity is deliberately exempt. A pricing order is an
        immutable event row — once placed it is never edited — and so it carries
        only `id` and `created_at`. It has no `updated_at` and no `version` field at
        all; neither key appears in its representation."
        PRD §2.1: "`created_by_user_id` on a purchase contract captures the
        `X-User-ID` of the `Merchandiser` that struck it, `graded_by_user_id` on a
        delivery ticket captures the `X-User-ID` of the `GrainInspector` that graded
        it, and `placed_by_user_id` on a pricing order captures the `X-User-ID` of
        whoever placed the order."

        Design: Corner/entities/pricing_order_is_immutable_and_exposes_no_version_field
        """
        scenario = setup_contract_scenario(
            desk_code="CD07", desk_name="Corner Desk 7", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "HTA", "bushels": 10000},
        )

        payload = create_pricing_order_payload(
            scenario["contract"]["id"], component="BASIS", bushels=10000,
            price_cents=-30,
        )
        created = validate_success(api.create_pricing_order(payload, MERCH), 201)

        order = validate_success(api.get_pricing_order(created["id"], MERCH), 200)
        assert_pricing_order(order)
        assert "version" not in order, (
            f"a pricing order must expose no version key, got {sorted(order)}"
        )
        assert "updated_at" not in order, (
            f"a pricing order must expose no updated_at key, got {sorted(order)}"
        )
        assert order["placed_by_user_id"] == "u-merch-1"

        _, meta = validate_paginated(api.list_pricing_orders(
            MERCH, params={"contract_id": scenario["contract"]["id"]}
        ))
        assert meta["total_count"] == 1

    def test_two_basis_orders_average_by_volume_to_four_decimals(self, api):
        """PRD §3.5: "On each accepted order the server gathers every pricing order
        on that contract for that same component, including the one just placed, in
        `created_at` ascending order."
        PRD §3.5: "The leg price — `futures_price_cents` or `basis_cents`
        respectively — becomes the sum, over those orders, of each order's price
        multiplied by its bushels, divided by the total priced bushels for the
        component, rounded half-up to 4 decimal places."
        PRD §3.5: "`gross_unit_price_cents` is re-derived as the futures leg plus
        the basis leg plus `roll_adjustment_cents`, and the desk's
        `unpriced_bushels` aggregate is recomputed."

        Design: Corner/calculations/partial_basis_pricing_produces_volume_weighted_average_leg
        """
        scenario = setup_contract_scenario(
            desk_code="CD21", desk_name="Corner Desk 21", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "HTA", "bushels": 10000},
        )
        contract_id = scenario["contract"]["id"]

        new_pricing_order(contract_id, component="BASIS", bushels=6000,
                          price_cents=-30)
        after_first = read_contract(contract_id)
        assert after_first["priced_basis_bushels"] == pytest.approx(6000.00, abs=0.01)
        assert after_first["pricing_status"] == "PARTIALLY_PRICED"
        assert after_first["basis_cents"] == pytest.approx(-30.0000, abs=0.0001)

        new_pricing_order(contract_id, component="BASIS", bushels=4000,
                          price_cents=-36)
        after_second = read_contract(contract_id)

        assert after_second["basis_cents"] == pytest.approx(-32.4000, abs=0.0001), (
            f"(-30 x 6000 + -36 x 4000) / 10000 = -32.4000, got "
            f"{after_second['basis_cents']}"
        )
        assert after_second["priced_basis_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert after_second["pricing_status"] == "FULLY_PRICED"
        assert after_second["gross_unit_price_cents"] == pytest.approx(415.6, abs=0.01)
        assert after_second["unpriced_bushels"] == pytest.approx(0, abs=0.01)
        assert_contract_pricing_invariants(after_second)

        _, meta = validate_paginated(api.list_pricing_orders(
            MERCH, params={"contract_id": contract_id}
        ))
        assert meta["total_count"] == 2

    def test_a_cash_contract_accepts_no_pricing_orders_at_all(self, api):
        """PRD §3.5: "A `CASH` contract has both legs fixed at signing and accepts
        no pricing orders at all."
        PRD §3.5: "Any of those three failures — wrong component for the type,
        component already fully fixed, or an over-large order — is reported as
        `ERR_CONTRACT_ALREADY_PRICED`."

        Design: Corner/validations/pricing_order_against_a_cash_contract_returns_contract_already_priced
        """
        scenario = setup_contract_scenario(
            desk_code="CD36", desk_name="Corner Desk 36", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 10000},
        )
        contract_id = scenario["contract"]["id"]

        payload = create_pricing_order_payload(
            contract_id, component="FUTURES", bushels=5000, price_cents=455,
        )
        validate_error(api.create_pricing_order(payload, TRADER),
                       ApiErrorId.ERR_CONTRACT_ALREADY_PRICED.value, 422)

        contract = read_contract(contract_id)
        assert contract["futures_price_cents"] == pytest.approx(448, abs=0.0001)
        assert contract["pricing_status"] == "FULLY_PRICED"
        _, meta = validate_paginated(api.list_pricing_orders(
            MERCH, params={"contract_id": contract_id}
        ))
        assert meta["total_count"] == 0


class TestParallelPricingAndDeliveryAxes:
    """A BASIS contract advances its delivery axis and its pricing axis
    independently, with the lifecycle axis untouched at ACTIVE."""

    def _basis_scenario(self):
        scenario = setup_graded_ticket_scenario(
            desk_code="GD6", desk_name="Parallel Axis Desk", lots_open=10,
            contract_overrides={"contract_type": "BASIS", "bushels": 20000},
            ticket_overrides={"gross_bushels": 5000},
        )
        return scenario

    def test_applying_a_partial_load_moves_only_the_delivery_axis(self, api):
        """PRD §3.8: "`delivery_status` is then re-derived: `OPEN` while nothing has
        been delivered, `PARTIALLY_DELIVERED` once some bushels have arrived but the
        contract's full quantity has not, and `COMPLETE` once delivered bushels
        reach or exceed the contracted quantity."
        PRD §3.7: "When the contract's `gross_unit_price_cents` is null — because at
        least one leg is still floating — then `gross_contract_value_usd`,
        `service_fee_cents_per_bushel`, `net_unit_price_cents` and
        `settlement_value_usd` are all null on the ticket, and the load is still
        perfectly gradeable and appliable; it simply carries no money with it."

        Design: Difficulty/non_linear_state_machine/contract_pricing_and_delivery_axes_advance_independently
        """
        scenario = self._basis_scenario()
        contract_id = scenario["contract"]["id"]
        assert scenario["contract"]["pricing_status"] == "PARTIALLY_PRICED", (
            "a BASIS contract fixes only the basis leg at signing"
        )

        apply_ticket(scenario["ticket"]["id"])

        contract = read_contract(contract_id)
        assert contract["delivery_status"] == "PARTIALLY_DELIVERED"
        assert contract["pricing_status"] == "PARTIALLY_PRICED", (
            "the pricing axis is untouched by a delivery"
        )
        assert contract["delivered_bushels"] == pytest.approx(5000.00, abs=0.01)
        assert contract["status"] == "ACTIVE"
        assert read_ticket(scenario["ticket"]["id"])["settlement_value_usd"] is None

    def test_the_futures_order_moves_only_the_pricing_axis(self, api):
        """PRD §3.5: "`pricing_status` becomes `FULLY_PRICED` when both priced
        figures are at least the contract's bushels, `UNPRICED` when both are still
        zero, and `PARTIALLY_PRICED` in every other case."
        PRD §3.5: "`unpriced_bushels` on the contract becomes its `bushels` less the
        smaller of `priced_futures_bushels` and `priced_basis_bushels`."
        PRD §3.5: "`gross_unit_price_cents` is re-derived as the futures leg plus
        the basis leg plus `roll_adjustment_cents`, and the desk's
        `unpriced_bushels` aggregate is recomputed."

        Design: Difficulty/non_linear_state_machine/contract_pricing_and_delivery_axes_advance_independently
        """
        scenario = self._basis_scenario()
        contract_id = scenario["contract"]["id"]
        apply_ticket(scenario["ticket"]["id"])

        new_pricing_order(contract_id, headers=TRADER, component="FUTURES",
                          bushels=20000, price_cents=452)

        contract = read_contract(contract_id)
        assert contract["pricing_status"] == "FULLY_PRICED"
        assert contract["delivery_status"] == "PARTIALLY_DELIVERED", (
            "the delivery axis is untouched by a pricing order"
        )
        assert contract["status"] == "ACTIVE", (
            "delivery is not COMPLETE, so the lifecycle axis stays at ACTIVE"
        )
        assert contract["futures_price_cents"] == pytest.approx(452.0000, abs=0.0001)
        assert contract["gross_unit_price_cents"] == pytest.approx(420, abs=0.01)
        assert contract["unpriced_bushels"] == pytest.approx(0, abs=0.01)
        assert_contract_pricing_invariants(contract)


class TestFuturesLegRequiresAnOpenPosition:
    """Fixing the futures leg is gated on the contract's board position, not on
    the desk's posture."""

    def _margin_called_scenario(self):
        scenario = setup_contract_scenario(
            desk_code="GD19", desk_name="Hedge Gate Desk", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "BASIS", "bushels": 20000},
        )
        mark_position(scenario["position"]["id"], 470)
        return scenario

    def test_a_futures_order_on_a_margin_called_position_is_refused(self, api):
        """PRD §3.5: "When the component is `FUTURES`, the contract's hedge position
        must be `OPEN`, or `ERR_HEDGE_POSITION_NOT_OPEN` answers; a `BASIS` order
        carries no such requirement because it does not touch the board."
        PRD §3.3: "When equity falls below maintenance, the position moves
        `OPEN → MARGIN_CALL` and a call row is raised against it."

        Design: Difficulty/cross_entity_state_dependency/futures_pricing_order_gated_by_margin_called_hedge_position
        """
        scenario = self._margin_called_scenario()
        position = read_position(scenario["position"]["id"])
        assert position["status"] == "MARGIN_CALL"
        assert position["unrealized_pnl_usd"] == pytest.approx(-11000.00, abs=0.01)

        payload = create_pricing_order_payload(
            scenario["contract"]["id"], component="FUTURES", bushels=20000,
            price_cents=452,
        )
        resp = api.create_pricing_order(payload, TRADER)
        validate_error(resp, ApiErrorId.ERR_HEDGE_POSITION_NOT_OPEN.value, 409)
        assert resp.status_code == 409

        contract = read_contract(scenario["contract"]["id"])
        assert contract["priced_futures_bushels"] == pytest.approx(0, abs=0.01)
        assert contract["pricing_status"] == "PARTIALLY_PRICED"

    def test_the_refusal_is_the_position_gate_not_a_lock_or_a_freeze(self, api):
        """PRD §2.9: "`posture` follows directly from that ratio, and both
        breakpoints are inclusive: the desk is `FROZEN` when `credit_utilization` is
        at or above 1.0000, `RESTRICTED` when it is at or above 0.8000 but below
        1.0000, and `NORMAL` otherwise."
        PRD §3.5: "And the contract's `pricing_locked` flag must be false, or
        `ERR_PRICING_LOCKED` answers — a check that, as Section 2.8 fixes, is
        evaluated **before** the desk-posture gate, so a locked contract on a frozen
        desk reports the lock rather than `ERR_DESK_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/futures_pricing_order_gated_by_margin_called_hedge_position
        """
        scenario = self._margin_called_scenario()

        desk = validate_success(
            api.get_trading_desk(scenario["desk"]["id"], MERCH), 200
        )
        assert desk["posture"] == "NORMAL", (
            "a 5,000,000 credit line keeps utilisation far below the 0.8000 "
            "breakpoint, so no posture gate can be the answer"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["pricing_locked"] is False

        payload = create_pricing_order_payload(
            scenario["contract"]["id"], component="FUTURES", bushels=20000,
            price_cents=452,
        )
        error = validate_error(api.create_pricing_order(payload, TRADER),
                               ApiErrorId.ERR_HEDGE_POSITION_NOT_OPEN.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_PRICING_LOCKED.value
        assert error["error_id"] != ApiErrorId.ERR_DESK_FROZEN.value
