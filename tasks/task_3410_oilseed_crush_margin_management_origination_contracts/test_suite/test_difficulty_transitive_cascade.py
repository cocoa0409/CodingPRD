"""Difficulty queue — transitive_cascade: the four-hop apply cascade ending
in the elevator receiving gate, and the three-hop clock-sweep cascade ending
in buyer suspension (PRD §3.3/§2.10 and §3.9/§3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_origination_contract,
    assert_product_sales_contract,
    apply_ticket,
    create_cash_contract,
    create_delivery_ticket_payload,
    create_sales_contract_payload,
    create_ticket,
    read_contract,
    setup_origination_site,
    setup_suspended_buyer,
    validate_error,
    validate_paginated,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
PRODUCT_MERCH = TEST_USERS["product_merchandiser_headers"]


class TestTicketApplyCascadesThroughPositionToElevatorGate:
    """Elevator with capacity exactly 1000 bu; a CASH contract for 1000 bu is
    filled by one clean ticket; a second 10-bu contract waits at the gate."""

    def _setup_and_apply(self):
        site = setup_origination_site(storage_capacity_bushels=1000)
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=1000
        )
        ticket = create_ticket(contract["id"], gross_bushels=1000)
        waiting = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=10
        )
        applied = apply_ticket(ticket["id"])
        return site, contract, waiting, applied

    def test_apply_creates_position_and_raises_stored_bushels(self, api):
        """PRD §3.3: "Third, a storage position is created at the elevator with
        `source_ticket_id` pointing at the ticket" with "both `bushels_initial`
        and `current_bushels` set to the ticket's `net_bushels`, in status
        `OPEN`. Fourth, the elevator's `stored_bushels` — and
        `certified_stored_bushels` when the lot is certified — grows by
        `net_bushels`".
        The 1000-net apply lands a 1000-bu lot and drives stored_bushels to
        exactly the 1000 capacity.

        Design: Difficulty/transitive_cascade/ticket_apply_cascades_through_position_to_elevator_gate
        """
        site, contract, _, applied = self._setup_and_apply()
        assert applied["status"] == "APPLIED"
        contract_after = read_contract(contract["id"])
        assert_origination_contract(contract_after)
        assert float(contract_after["delivered_bushels"]) == pytest.approx(1000)
        assert contract_after["fulfillment_status"] == "DELIVERED"

        positions, meta = validate_paginated(
            api_client.list_storage_positions(
                MERCH, params={"elevator_id": site["elevator"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        position = positions[0]
        assert position["source_ticket_id"] == applied["id"]
        assert float(position["current_bushels"]) == pytest.approx(1000)
        assert position["status"] == "OPEN"

        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(1000)

    def test_gate_closes_at_capacity_and_rejects_next_ticket(self, api):
        """PRD §2.10: "the gate is false exactly when `stored_bushels` has reached `storage_capacity_bushels`, and while it is false the elevator rejects new delivery tickets." PRD §3.3: "a full house rejects the ticket with `ERR_ELEVATOR_AT_CAPACITY` before a kernel is graded."
        The cascade's terminal effect: the next ticket create on the waiting
        contract fails 422.

        Design: Difficulty/transitive_cascade/ticket_apply_cascades_through_position_to_elevator_gate
        """
        site, _, waiting, _ = self._setup_and_apply()
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert elevator["receiving_open"] is False, (
            "1000 stored >= 1000 capacity closes the gate"
        )
        resp = api_client.create_delivery_ticket(
            create_delivery_ticket_payload(waiting["id"], gross_bushels=1),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_ELEVATOR_AT_CAPACITY)


class TestClockSweepDefaultsContractSuspendsBuyer:
    """One buyer with three SOY_OIL contracts (1000 lbs at 20 cents each,
    windows all ending 2026-09-30), no deliveries; the 2026-10-01 sweep
    defaults all three."""

    def test_sweep_defaults_each_contract_and_counts_claims(self, api):
        """PRD §3.9: "Every sales contract in `OPEN` or `DELIVERING` whose
        `delivery_window_end` has fallen behind the new clock, with
        `delivered_lbs` still short of `quantity_lbs`, moves to `DEFAULTED`."
        and "Each default sets `claim_cents` to the undelivered pounds
        multiplied by `price_cents_per_lb` multiplied by ten percent, rounded
        half up to whole cents; increments the buyer's `open_claims_count` by
        one".
        Three defaults -> three claims of 2000 and a count of 3.

        Design: Difficulty/transitive_cascade/clock_sweep_defaults_contract_suspends_buyer
        """
        state = setup_suspended_buyer()
        assert len(state["contracts"]) == 3
        for contract in state["contracts"]:
            assert_product_sales_contract(contract)
            assert contract["status"] == "DEFAULTED"
            assert contract["claim_cents"] == 2000
        assert state["buyer"]["open_claims_count"] == 3

    def test_third_claim_suspends_buyer_and_blocks_new_sales(self, api):
        """PRD §3.9: "and suspends the buyer — `ACTIVE` to `SUSPENDED`, terminal — the moment the count reaches three open claims. A suspended buyer can no longer be named on a new sales contract (`ERR_BUYER_NOT_ACTIVE`)."
        The cascade's terminal gate: a fresh sales contract for this buyer
        fails 422.

        Design: Difficulty/transitive_cascade/clock_sweep_defaults_contract_suspends_buyer
        """
        state = setup_suspended_buyer()
        assert state["buyer"]["status"] == "SUSPENDED"
        resp = api_client.create_product_sales_contract(
            create_sales_contract_payload(
                state["buyer"]["id"], state["plant"]["id"], product="SOY_OIL",
                quantity_lbs=500, price_cents_per_lb=20,
                delivery_window_start="2026-10-05T00:00:00Z",
                delivery_window_end="2026-10-20T00:00:00Z", max_ffa_pct=0.5,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_ACTIVE)
