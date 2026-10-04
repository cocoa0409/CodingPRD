"""Difficulty rule: non_linear_state_machine — the assembly hold/resume cycle
and the return settle/dispute/re-grade cycle."""
from test_helpers import (
    OPS,
    PROVIDER,
    add_return_line,
    create_return,
    cust_headers,
    get_success_data,
    grade_line,
    settle_return,
    setup_article_with_stock,
    setup_fulfilled_order,
    setup_in_progress_job,
    setup_store_and_customer,
    submit_return,
    validate_success,
)


class TestAssemblyJobHoldResumeCycle:
    """Instance: assembly_job_hold_resume_cycle."""

    def test_hold_resume_loop_then_completion_closes_order(self, api):
        """PRD §3.6: "putting the job on hold — optionally recording a
        `hold_reason` — moves it to `ON_HOLD`, and resuming returns it to
        `IN_PROGRESS`, a loop that may repeat as often as the job demands."
        PRD §3.6: "Completion moves the order's `assembly_status` to
        `COMPLETED` and immediately triggers the auto-close evaluation: an
        order sitting in `FULFILLED` or `DELIVERED` closes on the spot,
        crediting `points_earned` to an `ACTIVE` member's balance as in §3.3."

        Design: Difficulty/non_linear_state_machine/assembly_job_hold_resume_cycle
        """
        store, member = setup_store_and_customer(member=True)
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=45,
        )
        order, _, job = setup_in_progress_job(member, store, article, qty=2)

        held = validate_success(
            api.hold_assembly_job(job["id"], {"hold_reason": "missing cam locks"}, PROVIDER)
        )
        assert held["status"] == "ON_HOLD"
        resumed = validate_success(api.resume_assembly_job(job["id"], PROVIDER))
        assert resumed["status"] == "IN_PROGRESS"
        completed = validate_success(
            api.complete_assembly_job(job["id"], {"actual_minutes": 60}, PROVIDER)
        )
        assert completed["status"] == "COMPLETED"
        # cap = ceil(90 x 1.5) = 135; actual 60 is under the cap.
        assert completed["billed_minutes"] == 60

        order_after = get_success_data(api.get_order(order["id"], cust_headers(member)))
        assert order_after["assembly_status"] == "COMPLETED"
        assert order_after["status"] == "CLOSED"
        # total 2000 -> floor(2000/100) = 20 points.
        assert order_after["points_earned"] == 20
        customer_after = get_success_data(api.get_customer(member["id"], OPS))
        assert customer_after["points_balance"] == 20

    def test_hold_resume_cycle_may_repeat(self, api):
        """PRD §3.6: "putting the job on hold — optionally recording a
        `hold_reason` — moves it to `ON_HOLD`, and resuming returns it to
        `IN_PROGRESS`, a loop that may repeat as often as the job demands."

        Design: Difficulty/non_linear_state_machine/assembly_job_hold_resume_cycle
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=30,
        )
        order, _, job = setup_in_progress_job(customer, store, article, qty=1)

        for _ in range(2):
            held = validate_success(api.hold_assembly_job(job["id"], {}, PROVIDER))
            assert held["status"] == "ON_HOLD"
            resumed = validate_success(api.resume_assembly_job(job["id"], PROVIDER))
            assert resumed["status"] == "IN_PROGRESS"

        completed = validate_success(
            api.complete_assembly_job(job["id"], {"actual_minutes": 30}, PROVIDER)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["billed_minutes"] == 30  # cap ceil(30 x 1.5) = 45
        order_after = get_success_data(api.get_order(order["id"], cust_headers(customer)))
        assert order_after["status"] == "CLOSED"


class TestReturnSettleDisputeRegradeCycle:
    """Instance: return_settle_dispute_regrade_cycle."""

    def _settled_like_new_return(self, api, customer, store):
        """Order qty 1 FULFILLED; receipted return qty 1 graded LIKE_NEW and
        settled. Returns (order, order_line, article, bin_stock, ret, ret_line)."""
        article, _, stocks = setup_article_with_stock(
            store, on_hand=3, price_cents=1000)
        order, order_lines = setup_fulfilled_order(customer, store, [(article, 1)])
        ret = create_return(customer, order_id=order["id"])
        ret_line = add_return_line(customer, ret["id"], article["id"], qty=1,
                                   order_line_id=order_lines[0]["id"])
        submit_return(customer, ret["id"])
        grade_line(ret["id"], ret_line["id"], "LIKE_NEW")
        settled = settle_return(ret["id"])
        return order, order_lines[0], article, stocks[0], ret, ret_line, settled

    def test_settle_dispute_reopen_regrade_resettle_recomputes(self, api):
        """PRD §3.8: "A customer may dispute a settled return, which moves the
        request to `DISPUTED` and reverses the previous settlement in kind:
        any units restocked as `LIKE_NEW` come back off the shelf (`on_hand`
        drops by each line's `restocked_units`), and the `returned_qty`
        rollups on the referenced order lines are rolled back."
        PRD §3.8: "the next settle recomputes every refund and writeoff from
        scratch."

        Design: Difficulty/non_linear_state_machine/return_settle_dispute_regrade_cycle
        """
        store, customer = setup_store_and_customer()
        order, order_line, article, stock, ret, ret_line, settled1 = (
            self._settled_like_new_return(api, customer, store)
        )
        assert settled1["refund_total_cents"] == 1000
        after_first = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert after_first["on_hand"] == 3  # 3 - 1 checkout + 1 restock

        disputed = validate_success(api.dispute_return(ret["id"], cust_headers(customer)))
        assert disputed["status"] == "DISPUTED"
        after_dispute = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert after_dispute["on_hand"] == 2, "dispute un-restocks the LIKE_NEW unit"

        reopened = validate_success(api.reopen_return(ret["id"], OPS))
        assert reopened["status"] == "GRADING"

        grade_line(ret["id"], ret_line["id"], "OPEN_BOX")
        settled2 = settle_return(ret["id"])
        assert settled2["refund_total_cents"] == 850, (
            f"re-settled at OPEN_BOX: round(1000 x 0.85) = 850, got {settled2['refund_total_cents']}"
        )
        assert settled2["writeoff_total_cents"] == 150
        after_second = get_success_data(api.get_bin_stock(stock["id"], OPS))
        assert after_second["on_hand"] == 2, "OPEN_BOX does not restock"

    def test_dispute_rolls_back_returned_qty_rollup(self, api):
        """PRD §3.8: "the `returned_qty` rollups on the referenced order lines
        are rolled back."
        PRD §3.8: "a receipted line graded `LIKE_NEW` goes back on the shelf —
        `on_hand` increases by the quantity on every carton of the article,
        the line's `restocked_units` records how many, and the order line's
        `returned_qty` grows by the quantity."

        Design: Difficulty/non_linear_state_machine/return_settle_dispute_regrade_cycle
        """
        store, customer = setup_store_and_customer()
        order, order_line, article, stock, ret, ret_line, settled1 = (
            self._settled_like_new_return(api, customer, store)
        )
        line_after_settle = get_success_data(
            api.get_order_line(order_line["id"], cust_headers(customer)))
        assert line_after_settle["returned_qty"] == 1

        validate_success(api.dispute_return(ret["id"], cust_headers(customer)))
        line_after_dispute = get_success_data(
            api.get_order_line(order_line["id"], cust_headers(customer)))
        assert line_after_dispute["returned_qty"] == 0, (
            "dispute rolls the returned_qty rollup back to 0"
        )
