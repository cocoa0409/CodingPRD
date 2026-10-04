"""Difficulty queue — boundary_precision_check: the bushel-capacity boundary
at exact elevator fill, and the zero-signal boundary of the carry decision
(PRD §2.10/§3.3).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    apply_ticket,
    assert_carry_assessment,
    create_cash_contract,
    create_ticket,
    post_bean_quote,
    read_contract,
    set_clock,
    setup_origination_site,
    setup_site,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
TRADER = TEST_USERS["crush_trader_headers"]


class TestElevatorCapacityExactFillThenGate:
    """Elevator capacity 1000 bu; CASH contract for 1000 bu; ticket A gross
    999.999 and ticket B gross 0.001, both clean."""

    def _setup(self):
        site = setup_origination_site(storage_capacity_bushels=1000)
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=1000
        )
        ticket_a = create_ticket(contract["id"], gross_bushels=999.999)
        ticket_b = create_ticket(contract["id"], gross_bushels=0.001)
        return site, contract, ticket_a, ticket_b

    def test_one_tick_below_capacity_keeps_gate_open(self, api):
        """PRD §2.10: "the gate is false exactly when `stored_bushels` has reached `storage_capacity_bushels". At 999.999 stored of 1000 the gate
        must still be open — the boundary sits at exact equality, not before
        it.

        Design: Difficulty/boundary_precision_check/elevator_capacity_exact_fill_then_gate
        """
        site, _, ticket_a, _ = self._setup()
        applied = apply_ticket(ticket_a["id"])
        assert applied["status"] == "APPLIED"
        assert float(applied["net_bushels"]) == pytest.approx(999.999)
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(999.999)
        assert elevator["receiving_open"] is True

    def test_exact_fill_accepted_then_gate_flips(self, api):
        """PRD §3.3: "Storage headroom is refused when the elevator's `stored_bushels` plus `net_bushels` would exceed `storage_capacity_bushels` — `ERR_ELEVATOR_AT_CAPACITY`." The exact 0.001 remainder reaches 1000 ==
        capacity without exceeding it, so it applies; only then does
        receiving_open flip false (§2.10) and the contract lands DELIVERED.

        Design: Difficulty/boundary_precision_check/elevator_capacity_exact_fill_then_gate
        """
        site, contract, ticket_a, ticket_b = self._setup()
        apply_ticket(ticket_a["id"])
        applied_b = apply_ticket(ticket_b["id"])
        assert applied_b["status"] == "APPLIED", (
            "stored 999.999 + net 0.001 == 1000 is allowed, not rejected"
        )
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(1000)
        assert elevator["receiving_open"] is False
        refreshed = read_contract(contract["id"])
        assert float(refreshed["delivered_bushels"]) == pytest.approx(1000)
        assert refreshed["fulfillment_status"] == "DELIVERED"


class TestCarrySignalZeroIsFlatNotCarry:
    """Elevator; BEAN 2026-11 = 1200 and 2027-01 = 1210 as-of 2026-09-01 — a
    10-cent deferred premium against a 2-month x 5-cent storage cost leaves
    the signal at exactly zero."""

    def _setup(self):
        site = setup_site()
        post_bean_quote("2026-11", 1200, "2026-09-01T00:00:00Z")
        post_bean_quote("2027-01", 1210, "2026-09-01T00:00:00Z")
        return site

    def test_signal_exactly_zero_decides_flat(self, api):
        """PRD §3.3: "the `decision` is `CARRY` exactly when the signal is strictly positive — a signal of exactly zero is `FLAT`, because the market must pay strictly more than the cost of storage before holding bushels is worth the space." Signal 1210 - 1200 - 10 == 0 -> FLAT.

        Design: Difficulty/boundary_precision_check/carry_signal_zero_is_flat_not_carry
        """
        site = self._setup()
        data = validate_success(
            api_client.get_carry_assessment(
                site["elevator"]["id"], TRADER,
                params={"nearby_month": "2026-11", "deferred_month": "2027-01"},
            )
        )
        assert_carry_assessment(data)
        assert data["nearby_price_cents"] == 1200
        assert data["deferred_price_cents"] == 1210
        assert data["storage_cost_cents_per_bushel"] == 10
        assert data["signal_cents_per_bushel"] == 0
        assert data["decision"] == "FLAT"

    def test_one_cent_above_breakeven_decides_carry(self, api):
        """PRD §3.3: "The `signal_cents_per_bushel` is the deferred quote minus the nearby quote minus that storage cost, and the `decision` is `CARRY` exactly when the signal is strictly positive". Re-quoting the deferred
        leg one cent higher (1211 as-of 2026-09-02) moves the signal to 1 and
        flips the decision to CARRY.

        Design: Difficulty/boundary_precision_check/carry_signal_zero_is_flat_not_carry
        """
        site = self._setup()
        set_clock("2026-09-02T00:00:00Z")
        post_bean_quote("2027-01", 1211, "2026-09-02T00:00:00Z")
        data = validate_success(
            api_client.get_carry_assessment(
                site["elevator"]["id"], TRADER,
                params={"nearby_month": "2026-11", "deferred_month": "2027-01"},
            )
        )
        assert data["signal_cents_per_bushel"] == 1
        assert data["decision"] == "CARRY"
