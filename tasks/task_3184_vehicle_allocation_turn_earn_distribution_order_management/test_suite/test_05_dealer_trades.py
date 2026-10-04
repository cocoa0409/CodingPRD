"""Dealer-to-dealer trade negotiation and execution (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_trade,
    create_dealer,
    create_dealer_trade_payload,
    create_trade,
    create_region,
    execute_trade,
    get_dealer_allocation,
    get_dealer_model_line,
    lock_all_children,
    make_dealer_headers,
    setup_dealer_run,
    validate_error,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]


class TestTradeCounterLoop:
    def test_counter_loop_then_accept(self, api):
        """PRD §3.9: "The counterpart may alternatively counter with a different `counter_units` (at least 1), transitioning `PROPOSED → COUNTERED` and recording the amended `counter_units`. The original proposer may then re-counter, transitioning `COUNTERED → PROPOSED` and updating `units` to the new `counter_units`. This `PROPOSED ↔ COUNTERED` loop may iterate any number of times before expiry."

        Design: Difficulty/non_linear_state_machine/dealer_trade_counter_loop_and_multi_terminal
        """
        fx = setup_dealer_run(num_dealers=2, base_units=10)
        dealer_f, dealer_g = fx["dealers"]
        run = fx["run"]
        trade = create_trade(dealer_f, dealer_g, run["id"], units=2)
        assert trade["state"] == "PROPOSED"
        countered = validate_success(
            api.counter_dealer_trade(trade["id"], {"counter_units": 1},
                                     make_dealer_headers(dealer_g["id"])),
            200,
        )
        assert countered["state"] == "COUNTERED"
        assert countered["counter_units"] == 1
        reproposed = validate_success(
            api.counter_dealer_trade(trade["id"], {"counter_units": 2},
                                     make_dealer_headers(dealer_f["id"])),
            200,
        )
        assert reproposed["state"] == "PROPOSED"
        assert reproposed["units"] == 2
        accepted = validate_success(
            api.accept_dealer_trade(trade["id"], make_dealer_headers(dealer_g["id"])), 200
        )
        assert accepted["state"] == "ACCEPTED"

    def test_accept_and_decline_rejected_after_accepted(self, api):
        """PRD §3.9: "The counterpart may accept a `PROPOSED` trade, transitioning it to `ACCEPTED`."
        PRD §3.9: "Either party may decline from `PROPOSED` or `COUNTERED`, transitioning to `DECLINED`."
        PRD §2.5: "Target resource is in a state from which the requested transition exists — otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/non_linear_state_machine/dealer_trade_counter_loop_and_multi_terminal
        """
        fx = setup_dealer_run(num_dealers=2, base_units=10)
        dealer_f, dealer_g = fx["dealers"]
        trade = create_accepted_trade(dealer_f, dealer_g, fx["run"]["id"], units=2)
        assert trade["state"] == "ACCEPTED"
        second_accept = api.accept_dealer_trade(trade["id"], make_dealer_headers(dealer_g["id"]))
        validate_error(second_accept, ApiErrorId.ERR_INVALID_STATE, 409)
        decline = api.decline_dealer_trade(trade["id"], make_dealer_headers(dealer_g["id"]))
        validate_error(decline, ApiErrorId.ERR_INVALID_STATE, 409)


class TestTradeValidation:
    def test_cross_region_trade_rejected(self, api):
        """PRD §3.9: "Cross-region trades, self-trades, and `units` below 1 are rejected with `ERR_TRADE_INVALID`."

        Design: Corner/validations/cross_region_trade_rejected
        """
        fx = setup_dealer_run(num_dealers=1, base_units=6)
        dealer_a = fx["dealers"][0]
        dealer_b = create_dealer(create_region()["id"])
        resp = api.create_dealer_trade(
            create_dealer_trade_payload(dealer_a["id"], dealer_b["id"], fx["run"]["id"], units=1),
            make_dealer_headers(dealer_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_INVALID, 422)


class TestTradeExecutionConservation:
    def test_execute_moves_pool_pairwise(self, api):
        """PRD §3.9: "On execution, the trade transitions to `EXECUTED`, stamps `executed_at`, decrements the from-dealer's `final_units` by `units`, increments the to-dealer's `final_units` by `units`, bumps the `AllocationRun`'s `version` by 1 and both affected `DealerAllocation` versions by 1".

        Design: Difficulty/compensating_invariant/trade_execute_pairwise_pool_conservation
        """
        fx = setup_dealer_run(num_dealers=2, base_units=10)
        dealer_q, dealer_r = fx["dealers"]
        run = fx["run"]
        da_q_before = get_dealer_allocation(run["id"], dealer_q["id"])
        da_r_before = get_dealer_allocation(run["id"], dealer_r["id"])
        trade = create_accepted_trade(dealer_q, dealer_r, run["id"], units=2)
        executed = validate_success(execute_trade(trade["id"], run["id"]), 200)
        assert executed["state"] == "EXECUTED"
        assert executed["executed_at"] is not None
        da_q_after = get_dealer_allocation(run["id"], dealer_q["id"])
        da_r_after = get_dealer_allocation(run["id"], dealer_r["id"])
        assert da_q_after["final_units"] == da_q_before["final_units"] - 2
        assert da_r_after["final_units"] == da_r_before["final_units"] + 2
        assert (da_q_after["final_units"] + da_r_after["final_units"]) == (
            da_q_before["final_units"] + da_r_before["final_units"]
        ), "pairwise pool sum must be conserved across a trade"

    def test_execute_applies_earn_penalty_to_from_dealer(self, api):
        """PRD §3.9: "the from-dealer's `DealerModelLine.earned_credit_units` is reduced by `units * 0.5`, floored at 0, rounded half-up to 2 decimals. The to-dealer receives no earned credit for traded-in units — trades do not earn."

        Design: Difficulty/compensating_invariant/trade_execute_pairwise_pool_conservation
        """
        # Seed earned credit for the from-dealer by locking a prior run with surplus.
        fx = setup_dealer_run(num_dealers=2, base_units=10)
        dealer_q, dealer_r = fx["dealers"]
        line = fx["model_line"]
        run0 = fx["run"]
        # Consume nothing on dealer Q's allocation so the full want is surplus at lock.
        lock_all_children(run0["id"])
        validate_success(api.lock_allocation_run(run0["id"], ALLOC), 200)
        credit_before = get_dealer_model_line(dealer_q["id"], line["id"])["earned_credit_units"]
        assert credit_before >= 1.0, "setup: prior lock must have produced earned credit"
        # Next run (published by supersede semantics: create a new run for the line).
        run1 = validate_success(api.create_allocation_run(
            {"period": "2026-10", "model_line_id": line["id"], "base_units": 10,
             "lookback_start": "2026-06-01T00:00:00Z", "lookback_end": "2026-09-01T00:00:00Z",
             "retail_priority_pct": 0},
            ALLOC,
        ), 201)
        validate_success(api.publish_allocation_run(run1["id"], ALLOC), 200)
        # Dealer Q (from-dealer) is the one whose credit the trade penalty hits.
        # Trade direction must be Q -> R for the penalty assertion below.
        trade = create_accepted_trade(dealer_q, dealer_r, run1["id"], units=2)
        validate_success(execute_trade(trade["id"], run1["id"]), 200)
        credit_after = get_dealer_model_line(dealer_q["id"], line["id"])["earned_credit_units"]
        assert credit_after == credit_before - 1.0, (
            f"2 traded units must cost 2 * 0.5 = 1.0 earned credit: {credit_before} -> {credit_after}"
        )
