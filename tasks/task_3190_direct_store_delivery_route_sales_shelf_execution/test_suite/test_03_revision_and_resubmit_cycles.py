"""Cyclic state machines: the order revision loop and the credit resubmit loop."""
from test_helpers import (
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    create_stale_credit,
    deliver_line,
    deliver_order,
    get_credit,
    get_lot_by_code,
    get_order,
    get_route_day,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_paginated,
    validate_success,
)


def _list_order_lines(order_id):
    lines, _ = validate_paginated(
        api_client.list_order_lines(make_supervisor_headers(), params={"order_id": order_id})
    )
    return lines


class TestOrderSubmitUnsubmitRevisionCycle:
    def _setup(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 100)], rep
        )
        start_route_day(day["id"], rep)
        return rep, store, product, day

    def test_revision_cycle_delivers_revised_lines(self, api):
        """PRD §3.4: "The revision loop is explicit: the rep may pull a
        SUBMITTED order back to DRAFT (version increments again) to edit on the
        handheld."
        PRD §2.4: "an integer version that starts at 1 and increments by
        exactly 1 on every mutation of that resource."

        Design: Difficulty/non_linear_state_machine/order_submit_unsubmit_revision_cycle
        """
        rep, store, product, day = self._setup()

        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 30)], rep
        )
        submit_order(order["id"], rep)
        resp = api.unsubmit_order(order["id"], make_rep_headers(rep["id"]))
        unsubmitted = validate_success(resp)
        assert unsubmitted["status"] == "DRAFT"

        # create(1) -> submit(2) -> unsubmit(3)
        order_v3 = unsubmitted["version"]
        resp = api.revise_order(
            order["id"],
            {
                "lines": [{"product_id": product["id"], "qty_ordered_cases": 12}],
                "expected_store_order_version": order_v3,
            },
            make_rep_headers(rep["id"]),
        )
        validate_success(resp)
        submit_order(order["id"], rep)
        resp = api.deliver_order(
            order["id"],
            deliver_payload_for(product["id"], 12),
            make_rep_headers(rep["id"]),
        )
        delivered = validate_success(resp)

        # revise(4) -> submit(5) -> deliver(6)
        assert delivered["status"] == "DELIVERED"
        assert delivered["version"] == 6
        assert delivered["gross_total_cents"] == 6000

        lines = _list_order_lines(order["id"])
        assert len(lines) == 1
        assert lines[0]["qty_ordered_cases"] == 12
        assert lines[0]["qty_delivered_cases"] == 12

    def test_unsubmit_returns_to_draft_before_revision(self, api):
        """PRD §3.4: "Submission converts a DRAFT order to SUBMITTED."
        PRD §3.4: "The revision loop is explicit: the rep may pull a SUBMITTED
        order back to DRAFT (version increments again) to edit on the handheld,
        and may cancel an order from either DRAFT or SUBMITTED, moving it to
        CANCELLED."

        Design: Difficulty/non_linear_state_machine/order_submit_unsubmit_revision_cycle
        """
        rep, store, product, day = self._setup()

        order = create_order(
            day["id"], store["id"], [order_line(product["id"], 30)], rep
        )
        submitted = submit_order(order["id"], rep)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None

        resp = api.unsubmit_order(order["id"], make_rep_headers(rep["id"]))
        unsubmitted = validate_success(resp)
        assert unsubmitted["status"] == "DRAFT"
        assert unsubmitted["version"] == submitted["version"] + 1


def deliver_payload_for(product_id, qty):
    return {"lines": [{"product_id": product_id, "qty_delivered_cases": qty}]}


class TestStaleCreditRejectResubmitLoop:
    def _setup_rejected_credit(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 20)], rep
        )
        start_route_day(day["id"], rep)
        credit = create_stale_credit(
            day["id"], store["id"], product["id"], 4, make_rep_headers(rep["id"])
        )
        resp = api_client.reject_stale_credit(
            credit["id"], {"reject_reason": "photo unclear"}, make_supervisor_headers()
        )
        validate_success(resp)
        return rep, store, product, day, credit

    def test_resubmit_then_approve_mutates_lot_once(self, api):
        """PRD §3.7: "the rep may resubmit a REJECTED credit, returning it to
        PENDING_APPROVAL with reject_reason and decided_by_user_id cleared — the
        reject–resubmit loop may cycle any number of times."
        PRD §3.7: "Approval stamps decided_by_user_id, moves the credit to
        APPROVED (terminal), and only now mutates inventory: the pinned lot's
        stale_pulled_cases increases by qty_cases."

        Design: Difficulty/non_linear_state_machine/stale_credit_reject_resubmit_loop
        """
        rep, store, product, day, credit = self._setup_rejected_credit()

        resp = api.resubmit_stale_credit(credit["id"], make_rep_headers(rep["id"]))
        resubmitted = validate_success(resp)
        assert resubmitted["status"] == "PENDING_APPROVAL"
        assert resubmitted["reject_reason"] is None
        assert resubmitted["decided_by_user_id"] is None

        resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
        approved = validate_success(resp)

        # create(1) -> reject(2) -> resubmit(3) -> approve(4)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == 4
        assert approved["reject_reason"] is None
        assert approved["decided_by_user_id"] == "sup-1"

        # The lot mutation fired exactly once, at the final approval.
        lot = get_lot_by_code(day["id"], "L-ST")
        assert lot["stale_pulled_cases"] == 4
        assert get_route_day(day["id"])["stale_pulled_cases"] == 4

    def test_resubmit_clears_reject_fields_without_lot_mutation(self, api):
        """PRD §3.7: "Rejection requires a reject_reason (ERR_VALIDATION when
        omitted), stamps decided_by_user_id, and leaves lots and settlement
        untouched."

        Design: Difficulty/non_linear_state_machine/stale_credit_reject_resubmit_loop
        """
        rep, store, product, day, credit = self._setup_rejected_credit()

        rejected = get_credit(credit["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "photo unclear"
        # Rejection alone leaves the lot untouched.
        lot = get_lot_by_code(day["id"], "L-ST")
        assert lot["stale_pulled_cases"] == 0

        resp = api.resubmit_stale_credit(credit["id"], make_rep_headers(rep["id"]))
        resubmitted = validate_success(resp)
        assert resubmitted["status"] == "PENDING_APPROVAL"
        assert resubmitted["reject_reason"] is None
        # Still no lot mutation before approval.
        lot = get_lot_by_code(day["id"], "L-ST")
        assert lot["stale_pulled_cases"] == 0
        assert get_route_day(day["id"])["stale_pulled_cases"] == 0
