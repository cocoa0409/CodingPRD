"""The two non-linear state machines: the settlement dispute loop and the
store transfer dimension."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, ADMIN,
    assert_split_legs_sum_to_gross_profit, create_two_franchisees_and_store,
    setup_settlement_with_lines, reconcile_settlement, get_success_data,
    make_franchisee_headers,
)


class TestSettlementDisputeLoop:
    """A reconciled settlement can be challenged and returned to RECONCILED."""

    def test_a_reconciled_settlement_re_enters_reconciled_after_a_dispute_is_resolved(self):
        """PRD §3.9: "A successful dispute moves the settlement from
        `RECONCILED` to `DISPUTED` and records the reason."
        PRD §3.9: "A `FranchisorAdmin` clears a `DISPUTED` settlement back to
        `RECONCILED`, and the resolution recomputes the settlement's
        `waste_charge_cents` under the resolved waste share and then its
        `net_settlement_cents`."

        Design: Difficulty/non_linear_state_machine/settlement_reconcile_dispute_resolve_cycle
        """
        context = setup_settlement_with_lines(
            lines=[("SERVICES", 2_000_000, 800_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T12:00:00Z",
        )
        settle_id = context["settlement"]["id"]

        reconciled = reconcile_settlement(settle_id)
        reconciled = reconcile_settlement(settle_id)
        assert reconciled["status"] == "RECONCILED"
        version_before = reconciled["version"]

        reason = ("Sanitation closure suppressed store hours for two days; "
                  "the services split base is understated.")
        disputed = validate_success(api_client.dispute_settlement(
            settle_id, {"dispute_reason": reason},
            make_franchisee_headers(context["franchisee"]["id"])), 201)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == reason

        resolved = validate_success(api_client.resolve_dispute(settle_id, ADMIN), 200)
        # The settlement re-entered a state it had already held.
        assert resolved["status"] == "RECONCILED"
        assert_split_legs_sum_to_gross_profit(resolved)

        read = get_success_data(api_client.get_settlement(settle_id, ADMIN))
        assert read["status"] == "RECONCILED"
        assert read["version"] > version_before

    def test_resolving_a_settlement_that_is_no_longer_disputed_is_a_state_error(self):
        """PRD §3.9: "Resolving a dispute is the back office's counterpart act.
        A `FranchisorAdmin` clears a `DISPUTED` settlement back to `RECONCILED`".
        PRD §3.9: "The resolution moves money only between the charge buckets —
        it never changes the split base, and the invariant that the operator's
        share plus the franchisor's share equals the settlement's gross profit
        is preserved exactly through the resolution."

        Design: Difficulty/non_linear_state_machine/settlement_reconcile_dispute_resolve_cycle
        """
        context = setup_settlement_with_lines(
            lines=[("SERVICES", 2_000_000, 800_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T12:00:00Z",
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        reconcile_settlement(settle_id)

        api_client.dispute_settlement(
            settle_id, {"dispute_reason": "Hours were suppressed by a closure."},
            make_franchisee_headers(context["franchisee"]["id"]))
        first_resolution = validate_success(api_client.resolve_dispute(settle_id, ADMIN), 200)
        assert first_resolution["status"] == "RECONCILED"

        # A second resolution has nothing to clear.
        validate_error(api_client.resolve_dispute(settle_id, ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)

        # The resolution moved money between buckets but never the split base.
        settle = get_success_data(api_client.get_settlement(settle_id, ADMIN))
        assert_split_legs_sum_to_gross_profit(settle)


class TestStoreTransferDimensionCycles:
    """DENIED is not a terminal resting point on the transfer dimension."""

    def test_a_denied_transfer_returns_to_pending_on_a_fresh_request(self):
        """PRD §3.9: "Denying a pending transfer returns the store's transfer
        dimension to `DENIED` and leaves the store's `franchisee_id` untouched,
        so the incumbent operator continues to trade. A denied transfer can be
        reopened: a fresh transfer request on a store whose dimension stands at
        `DENIED` returns it to `PENDING`".
        PRD §2.4: "A `TERMINATED` store has `transfer_status` reset to `NONE`."

        Design: Difficulty/non_linear_state_machine/store_transfer_denied_then_reopened_cycles_the_transfer_dimension
        """
        context = create_two_franchisees_and_store(
            minimum_net_worth_cents=10_000_000)
        store_id = context["store"]["id"]
        transferee_id = context["transferee"]["id"]
        incumbent_id = context["incumbent"]["id"]

        requested = validate_success(api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": transferee_id,
                       "transfer_price_cents": 45_000_000}, ADMIN), 200)
        assert requested["transfer_status"] == "PENDING"

        denied = validate_success(api_client.decide_store_transfer(
            store_id, {"decision": "DENY", "expected_store_version": requested["version"]},
            ADMIN), 200)
        assert denied["transfer_status"] == "DENIED"
        assert denied["franchisee_id"] == incumbent_id, "the store did not move"

        reopened = validate_success(api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": transferee_id,
                       "transfer_price_cents": 42_000_000}, ADMIN), 200)
        assert reopened["transfer_status"] == "PENDING", "DENIED is not terminal"
        assert reopened["transfer_price_cents"] == 42_000_000
        assert reopened["franchisee_id"] == incumbent_id

        # The reopened request carries the new terms.
        read = get_success_data(api_client.get_store(store_id, ADMIN))
        assert read["transfer_price_cents"] == 42_000_000

    def test_the_transfer_dimension_moves_without_disturbing_the_status_dimension(self):
        """PRD §2.4: "Two independent dimensions ride on a single store row, and
        neither gates the other's transitions except where a precondition names
        it."
        PRD §3.9: "An approval is the substantial branch and it moves several
        things at once."
        PRD §3.9: "The target must not be the store's current operator, and it
        must not already hold an agreement on that store — either situation is
        rejected with `ERR_TRANSFER_CONFLICT` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/store_transfer_denied_then_reopened_cycles_the_transfer_dimension
        """
        context = create_two_franchisees_and_store(
            minimum_net_worth_cents=10_000_000)
        store_id = context["store"]["id"]
        transferee_id = context["transferee"]["id"]

        requested = validate_success(api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": transferee_id,
                       "transfer_price_cents": 45_000_000}, ADMIN), 200)
        denied = validate_success(api_client.decide_store_transfer(
            store_id, {"decision": "DENY", "expected_store_version": requested["version"]},
            ADMIN), 200)
        assert denied["transfer_status"] == "DENIED"

        reopened = validate_success(api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": transferee_id,
                       "transfer_price_cents": 42_000_000}, ADMIN), 200)

        # The status dimension never moved, and neither did the incumbent agreement.
        assert reopened["status"] == "ACTIVE"
        final_store = get_success_data(api_client.get_store(store_id, ADMIN))
        assert final_store["status"] == "ACTIVE"
        agreement = get_success_data(
            api_client.get_agreement(context["agreement"]["id"], ADMIN))
        assert agreement["status"] == "ACTIVE"

    def test_a_transfer_to_the_stores_current_operator_is_a_conflict(self):
        """PRD §3.9: "The target must not be the store's current operator, and it
        must not already hold an agreement on that store — either situation is
        rejected with `ERR_TRANSFER_CONFLICT` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/store_transfer_denied_then_reopened_cycles_the_transfer_dimension
        """
        context = create_two_franchisees_and_store(
            minimum_net_worth_cents=10_000_000)
        store_id = context["store"]["id"]
        incumbent_id = context["incumbent"]["id"]

        response = api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": incumbent_id,
                       "transfer_price_cents": 45_000_000}, ADMIN)
        validate_error(response, ApiErrorId.ERR_TRANSFER_CONFLICT, expected_status=409)
        assert get_success_data(
            api_client.get_store(store_id, ADMIN))["transfer_status"] == "NONE"