"""Compensating-action invariants across three conserved quantities."""

from test_helpers import (
    DCM,
    PICKER,
    create_and_approve_return,
    list_lines,
    receive_return,
    setup_allocated_order_with_two_stock_rows,
    setup_pick_shortage_with_claim,
    setup_shipped_order,
    validate_paginated,
    validate_success,
)


def stock_rows_for(api, item, dc, account):
    rows, _meta = validate_paginated(api.list_stock(
        DCM, {"item_id": item["id"], "dc_id": dc["id"], "account_id": account["id"],
              "limit": 100, "offset": 0}))
    return rows


def q_stock(rows):
    """The conserved physical ledger: the units physically on hand at the center.

    PRD 3.4 keeps `on_hand_units` fixed when an allocation reserves units — only
    `reserved_units` rises and `available_units` is recomputed as
    `on_hand_units - reserved_units` — so on-hand is the quantity that allocation
    and cancellation must leave untouched. Adding `reserved_units` here would
    double-count the reserved bucket and drift to 21 while the order is allocated.
    """
    return sum(row["on_hand_units"] for row in rows)


class TestAllocateThenCancelConservesDcStockLedger:
    """Allocation moves units into reserved; cancel moves the same units back."""

    def test_the_stock_ledger_reads_the_same_before_during_and_after(self, api):
        """PRD §3.3: "for every line still in `line_status` `ALLOCATED`, the units
        reserved at that line's distribution center are released, so the stock row's
        `reserved_units` is decremented by `allocated_units` and its `available_units`
        recomputed".
        PRD §3.4: "At the center, each affected stock row has `reserved_units` increased
        by the units allocated to it and `available_units` recomputed as the difference
        between `on_hand_units` and `reserved_units`".

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_dc_stock_ledger
        """
        scenario = setup_allocated_order_with_two_stock_rows(api, on_hand_a=12, on_hand_b=5,
                                                             qty=4, price=6500)
        item, dc, acct = scenario["items"][0], scenario["dc"], scenario["acct"]

        rows = stock_rows_for(api, item, dc, acct)
        assert q_stock(rows) == 17, "12 plus 5 on hand is the starting ledger"
        assert sum(row["reserved_units"] for row in rows) == 4
        assert sum(row["available_units"] for row in rows) == 13

        validate_success(api.cancel_order(scenario["order"]["id"], scenario["acct_headers"]))

        rows_after = stock_rows_for(api, item, dc, acct)
        assert q_stock(rows_after) == 17, "the cancel conserved the ledger"
        assert sum(row["reserved_units"] for row in rows_after) == 0
        assert sum(row["available_units"] for row in rows_after) == 17

    def test_the_cancelled_order_returns_to_its_pre_allocation_line_shape(self, api):
        """PRD §3.3: "Every line then returns to `line_status` `PENDING` with
        `allocated_units` reset to 0, `fulfillment_status` returns to `AWAITING_RELEASE`,
        `order_status` becomes `CANCELLED`".

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_dc_stock_ledger
        """
        scenario = setup_allocated_order_with_two_stock_rows(api, on_hand_a=12, on_hand_b=5,
                                                             qty=4, price=6500)

        cancelled = validate_success(api.cancel_order(scenario["order"]["id"],
                                                      scenario["acct_headers"]))
        assert cancelled["order_status"] == "CANCELLED"
        assert cancelled["fulfillment_status"] == "AWAITING_RELEASE"

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["line_status"] == "PENDING"
        assert lines[0]["allocated_units"] == 0


class TestPickThenPartialReturnConservesRecoverableUnits:
    """Picking consumes the shelf; receiving the return puts the units back."""

    def test_the_recoverable_ledger_returns_to_its_pre_pick_value(self, api):
        """PRD §3.9: "Each line's `restocked_units` is set to the lesser of its authorized
        units and the restock cap of 5, and its `damaged_units` is set to the authorized
        units minus that restocked figure."
        PRD §3.9: "The center's stock row for each line's item has its `on_hand_units`
        increased by the line's `restocked_units`, and its `available_units` is
        recomputed."
        PRD §3.9: "the fraction of returned material that can go straight back on the
        shelf declines predictably as the return grows".

        Design: Difficulty/compensating_invariant/pick_then_partial_return_conserves_recoverable_units
        """
        scenario = setup_shipped_order(api, qty=5, price=2000, on_hand=10, sku="SKU-9101")
        line = scenario["lines"][0]
        stock_id = scenario["stock_rows"][0]["id"]

        before = validate_success(api.get_stock(stock_id, DCM))
        lines_before = list_lines(api, scenario["acct"], scenario["order"])
        assert before["on_hand_units"] == 5, "five of the ten units were picked"
        assert lines_before[0]["damaged_units"] == 0

        ret = create_and_approve_return(api, scenario, requested_units=5)
        approved = validate_success(api.get_return(ret["id"], DCM))
        assert approved["restock_units"] == 4
        assert approved["damaged_units"] == 1

        receive_return(api, ret=ret, line=line, part_number="WS-20-CS")

        after = validate_success(api.get_stock(stock_id, DCM))
        lines_after = list_lines(api, scenario["acct"], scenario["order"])
        assert after["on_hand_units"] == 9
        assert lines_after[0]["damaged_units"] == 1
        assert after["on_hand_units"] + lines_after[0]["damaged_units"] == 10, (
            "no unit was lost or invented by the pick/return pair"
        )

    def test_the_line_records_its_restocked_share_and_its_friction(self, api):
        """PRD §3.9: "The line's `return_friction_units` is the units returned but not
        restocked — the damaged units plus any non-restockable units".

        Design: Difficulty/compensating_invariant/pick_then_partial_return_conserves_recoverable_units
        """
        scenario = setup_shipped_order(api, qty=5, price=2000, on_hand=10, sku="SKU-9102")
        line = scenario["lines"][0]
        ret = create_and_approve_return(api, scenario, requested_units=5)
        receive_return(api, ret=ret, line=line, part_number="WS-20-CS")

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["restocked_units"] == 4
        assert lines[0]["return_friction_units"] == 1


class TestShortfallClaimResumeVoidRestoresClaimCounter:
    """A short pick raises the claim counter; the resume/void pair lowers it again."""

    def test_the_claim_counter_returns_to_zero_while_the_reservation_holds(self, api):
        """PRD §3.6: "When a line's `shortage_units` is greater than 0 and the line's item
        has `long_tail` false, a claim is opened against the order and that line, carrying
        a `claim_units` count that is permitted to be 0 — a claim may legitimately assert
        that nothing was recoverable — and the owning account's `open_claim_count` is
        incremented by 1."
        PRD §3.6: "From `RESUMED`, a manager may instead void the claim, setting
        `claim_status` `VOIDED` and decrementing the account's `open_claim_count`."

        Design: Difficulty/compensating_invariant/shortfall_claim_resume_void_restores_claim_counter
        """
        scenario = setup_pick_shortage_with_claim(api, line_units=3, actual_units=1,
                                                  price=3000, on_hand=3, sku="SKU-9201")
        claim = scenario["claim"]
        line_id = scenario["lines"][0]["id"]

        acct = validate_success(api.get_account(scenario["acct"]["id"], DCM))
        assert acct["open_claim_count"] == 1
        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["line_status"] == "SHORT"
        assert lines[0]["allocated_units"] == 3

        resumed = validate_success(api.resume_claim_fulfillment(claim["id"], PICKER))
        assert resumed["claim_status"] == "RESUMED"
        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "ALLOCATED"
        still = validate_success(api.get_account(scenario["acct"]["id"], DCM))
        assert still["open_claim_count"] == 1, "resuming does not yet move the counter"

        validate_success(api.void_claim(claim["id"], DCM))
        after = validate_success(api.get_account(scenario["acct"]["id"], DCM))
        assert after["open_claim_count"] == 0, (
            "the resume/void pair compensated the counter exactly"
        )

    def test_the_shortfall_never_released_the_reservation(self, api):
        """PRD §3.6: "the task records `picked_units` as that value and computes
        `shortage_units` as `requested_units` minus `actual_units` when the pick fell
        short, and as 0 otherwise".

        Design: Difficulty/compensating_invariant/shortfall_claim_resume_void_restores_claim_counter
        """
        scenario = setup_pick_shortage_with_claim(api, line_units=3, actual_units=1,
                                                  price=3000, on_hand=3, sku="SKU-9202")
        claim = scenario["claim"]

        task = validate_success(api.get_pick_task(scenario["tasks"][0]["id"], DCM))
        assert task["picked_units"] == 1
        assert task["shortage_units"] == 2

        validate_success(api.resume_claim_fulfillment(claim["id"], PICKER))
        validate_success(api.void_claim(claim["id"], DCM))

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["allocated_units"] == 3, (
            "the shortfall never released the reservation it could not fill"
        )