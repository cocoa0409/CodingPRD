# -*- coding: utf-8 -*-
"""The work order's two independent state dimensions and its part lines."""
import pytest

from test_helpers import (
    ADMIN_1, FOUR_BANDS, ONE_BAND, PLANNER_1, ApiErrorId, add_approved_part_line,
    add_part_line, api_client as api, confirm_reservation, create_bench,
    create_core, create_customer, create_order, decide_part_line,
    make_customer_headers, order_action, order_version, quote_order, read_order,
    read_quote, reserve_bench, setup_shop, submit_part_line, validate_error,
    validate_paginated, validate_success,
)


class TestApprovalRollup:

    def _quoted_with_confirmed_bench(self):
        world = setup_shop(account_code="NGM-005", asset_tag="CONV-04-GBX",
                           feature_bands=FOUR_BANDS, serial_no="SN-77005",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5, bench_code="B-1")
        quote_order(world)
        world["reservation"] = reserve_bench(
            world["order"]["id"], world["bench"]["id"],
            "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z")
        confirm_reservation(world["reservation"]["id"])
        return world

    def test_adding_a_line_drags_approval_backwards_without_touching_work_status(self):
        """PRD 3.7: "Running backwards, adding a fresh `PROPOSED` line to an order whose
        existing lines are all approved drags it `APPROVED → PARTIAL`, and revising a rejected
        line back to `PROPOSED` moves the order `REJECTED → PARTIAL` when at least one sibling
        is still approved or rejected, or all the way back to `REJECTED → PENDING` when the
        revision leaves every line of the order in `PROPOSED` or `SUBMITTED`."
        PRD 3.7: "In every one of those backward moves the order's `work_status` is left
        completely untouched — so an order that was comfortably `QUOTED` and fully approved can
        silently lose its approval and then fail the scheduling gate, even though nothing about
        its `work_status` changed."

        Design: Difficulty/non_linear_state_machine/order_approval_dimension_moves_while_work_status_stays_quoted
        """
        world = self._quoted_with_confirmed_bench()
        order_id = world["order"]["id"]

        before = read_order(order_id)
        assert before["approval_status"] == "APPROVED"
        assert before["part_revision_counter"] == 3
        assert before["quoted_part_revision"] == 3

        add_part_line(order_id, part_no="SEAL-KIT-9", source_class="OEM", qty=1,
                      unit_cost_cents=4200)

        after = read_order(order_id)
        assert after["approval_status"] == "PARTIAL"
        assert after["work_status"] == "QUOTED"
        assert after["part_revision_counter"] == 4
        assert after["quoted_part_revision"] == 3

    def test_the_approval_dimension_blocks_scheduling_on_the_work_dimension(self):
        """PRD 3.8: "Its `approval_status` must be `APPROVED`, or the attempt is
        `ERR_PART_APPROVAL_PENDING` (HTTP 409)."
        PRD 3.7: "The two state dimensions on that record evolve independently and must be
        stored independently."

        Design: Difficulty/non_linear_state_machine/order_approval_dimension_moves_while_work_status_stays_quoted
        """
        world = self._quoted_with_confirmed_bench()
        order_id = world["order"]["id"]
        add_part_line(order_id, part_no="SEAL-KIT-9", source_class="OEM", qty=1,
                      unit_cost_cents=4200)

        validate_error(api.advance_rebuild_order(order_id, {"action": "SCHEDULE"}, PLANNER_1),
                       ApiErrorId.ERR_PART_APPROVAL_PENDING.value, 409)

        after = read_order(order_id)
        assert after["work_status"] == "QUOTED", "the rejected SCHEDULE moves nothing"
        assert after["approval_status"] == "PARTIAL"

    def test_reject_then_revise_rewrites_the_line_and_reopens_the_approval_rollup(self):
        """PRD 3.7: "A rejected line is not dead: a `Planner` or `ShopAdmin` may revise it back
        `REJECTED → PROPOSED`, optionally rewriting any of `part_no`, `source_class`, `qty`,
        `unit_cost_cents` and `engineering_waiver_ref` on the same call."
        PRD 3.7: "Revision recomputes `line_total_cents` from whatever quantity and unit cost
        are then in force and increments the line's own `revision_count` by 1, and it too
        requires the parent order to be in `DRAFT` or `QUOTED`."
        PRD 3.7: "An order in which no line is `PROPOSED` or `SUBMITTED` and at least one line
        is `REJECTED` is `REJECTED`."
        PRD 3.7: "An order in which every line is either `PROPOSED` or `SUBMITTED` is
        `PENDING`."

        Design: Corner/state_machines/part_line_reject_then_revise_rewrites_the_line_and_reopens_approval
        """
        world = setup_shop(account_code="RVS-001", customer_name="Revise Mill",
                           asset_tag="RVS-01-GBX", serial_no="SN-RVS-1",
                           declared_condition_grade="GRADE_B", labor_hours=3.0)
        order_id, cust_id = world["order"]["id"], world["customer"]["id"]
        line = add_part_line(order_id)
        assert line["line_total_cents"] == 77000
        submit_part_line(line["id"])

        rejected = decide_part_line(line["id"], cust_id, "REJECT",
                                    decision_note="lead time unacceptable")
        assert rejected["approval_status"] == "REJECTED"
        assert rejected["decision_note"] == "lead time unacceptable"
        after_reject = read_order(order_id)
        assert after_reject["approval_status"] == "REJECTED"
        assert after_reject["part_revision_counter"] == 3

        revised = validate_success(api.advance_part_line(line["id"], {
            "action": "REVISE", "part_no": "AM-22324-X",
            "source_class": "AFTERMARKET", "qty": 1, "unit_cost_cents": 51000},
            PLANNER_1))
        assert revised["approval_status"] == "PROPOSED"
        assert revised["revision_count"] == 1
        assert revised["part_no"] == "AM-22324-X"
        assert revised["source_class"] == "AFTERMARKET"
        assert revised["qty"] == 1
        assert revised["line_total_cents"] == 51000

        after_revise = read_order(order_id)
        assert after_revise["approval_status"] == "PENDING"
        assert after_revise["part_revision_counter"] == 4

    def test_only_the_owning_account_may_decide_a_submitted_line(self):
        """PRD 3.7: "Deciding is the `Customer` role's exclusive action, it is only available on
        a `SUBMITTED` line, and the deciding `X-User-ID` must be the order's `customer_id` or
        the request is `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.1: "A `Customer` caller deciding a part line must be the customer of that line's
        rebuild order."

        Design: Corner/rbac/customer_cannot_decide_another_customers_part_line
        """
        world = setup_shop(account_code="OWN-001", customer_name="Owner Mill",
                           asset_tag="OWN-01-GBX", serial_no="SN-OWN-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        stranger = create_customer(name="Stranger Mill", account_code="OWN-002")
        line = add_part_line(world["order"]["id"], part_no="BRG-22324", qty=1,
                             unit_cost_cents=40000)
        submit_part_line(line["id"])

        validate_error(api.decide_part_line(
            line["id"], {"decision": "APPROVE", "decision_note": "not mine to approve"},
            make_customer_headers(stranger["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        rows, _ = validate_paginated(api.list_part_lines(world["order"]["id"], PLANNER_1))
        assert rows[0]["approval_status"] == "SUBMITTED"

        approved = validate_success(api.decide_part_line(
            line["id"], {"decision": "APPROVE", "decision_note": "approved by the owner"},
            make_customer_headers(world["customer"]["id"])))
        assert approved["approval_status"] == "APPROVED"

        order = read_order(world["order"]["id"])
        assert order["approval_status"] == "APPROVED"
        assert order["part_revision_counter"] == 3

    def test_deciding_a_proposed_line_is_a_part_line_state_error(self):
        """PRD 3.7: "A proposed line is put in front of the account by a `Planner` or
        `ShopAdmin`, moving it `PROPOSED → SUBMITTED`; this is only possible while the parent
        order is in `DRAFT` or `QUOTED`, and the line must actually be `PROPOSED`, failing which
        the attempt is `ERR_PART_LINE_INVALID_STATE`."
        PRD 3.7: "Deciding is the `Customer` role's exclusive action, it is only available on a
        `SUBMITTED` line, and the deciding `X-User-ID` must be the order's `customer_id` or the
        request is `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/state_machines/part_line_decide_before_submit_and_double_void_are_rejected
        """
        from test_helpers import post_manual_note, read_credit_note, read_customer, void_note
        world = setup_shop(account_code="VOD-001", customer_name="Void Mill",
                           asset_tag="VOD-01-GBX", serial_no="SN-VOD-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        order_id, cust_id = world["order"]["id"], world["customer"]["id"]
        line = add_part_line(order_id, part_no="BRG-22324", qty=1, unit_cost_cents=40000)

        note = post_manual_note(cust_id, 5000, memo="issued in error")
        void_note(note["id"], "first and only void")

        validate_error(api.decide_part_line(line["id"], {"decision": "APPROVE"},
                                            make_customer_headers(cust_id)),
                       ApiErrorId.ERR_PART_LINE_INVALID_STATE.value, 409)
        rows, _ = validate_paginated(api.list_part_lines(order_id, PLANNER_1))
        assert rows[0]["approval_status"] == "PROPOSED"
        assert read_order(order_id)["part_revision_counter"] == 1

        validate_error(api.void_credit_note(note["id"], {"void_reason": "voiding it twice"},
                                            ADMIN_1),
                       ApiErrorId.ERR_CREDIT_NOTE_INVALID_STATE.value, 409)
        voided = read_credit_note(note["id"])
        assert voided["status"] == "VOID"
        assert voided["voided_at"] is not None

        customer = read_customer(cust_id)
        assert customer["manual_credit_balance_cents"] == 0
        assert customer["total_credit_balance_cents"] == 67500

        _, meta = validate_paginated(api.list_rebuild_orders(
            PLANNER_1, params={"customer_id": cust_id, "work_status": "DRAFT"}))
        assert meta["total_count"] == 1


class TestOrderSequencing:

    def test_out_of_sequence_and_post_terminal_order_actions_are_rejected(self):
        """PRD 3.7: "`work_status` is driven by shop-floor actions and runs `DRAFT → QUOTED →
        SCHEDULED → IN_PROGRESS → COMPLETED → DELIVERED`, with `CANCELLED` reachable from any
        of the first four; `DELIVERED` and `CANCELLED` are terminal."
        PRD 3.9: "Cancellation is available from `DRAFT`, `QUOTED`, `SCHEDULED` or
        `IN_PROGRESS`, takes a `cancel_reason`, and unwinds in four hops."
        PRD 3.9: "Completing the work moves the order `IN_PROGRESS → COMPLETED` and the core
        `REBUILDING → REBUILT`, and it is the moment the core's `rebuild_count` is incremented
        by 1 — not at start, and never on a cancellation."

        Design: Corner/state_machines/order_actions_out_of_sequence_and_after_terminal_are_rejected
        """
        from test_helpers import (inspect_order, read_bench, read_core,
                                  run_order_to, schedule_order)
        world = setup_shop(account_code="SEQ-001", customer_name="Sequence Mill",
                           asset_tag="SEQ-01-GBX", serial_no="SN-SEQ-1",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5, bench_code="B-SEQ")
        core_b = world["core"]

        draft_core = create_core(world["customer"]["id"], world["standard"]["id"],
                                 serial_no="SN-SEQ-2", rebuild_count=1,
                                 declared_condition_grade="GRADE_D")
        order_draft = create_order(world["customer"]["id"], draft_core["id"],
                                   world["asset"]["id"], labor_hours=3.0)

        quote_order(world)
        inspect_order(world, measurements=(("BORE", 85),))
        schedule_order(world, "2026-09-08T08:00:00Z", "2026-09-08T12:00:00Z")
        run_order_to(world, target="DELIVERED")

        validate_error(api.advance_rebuild_order(order_draft["id"], {"action": "DELIVER"},
                                                 PLANNER_1),
                       ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
        validate_error(api.advance_rebuild_order(order_draft["id"], {"action": "SCHEDULE"},
                                                 PLANNER_1),
                       ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
        validate_error(api.cancel_rebuild_order(world["order"]["id"],
                                                {"cancel_reason": "too late"}, PLANNER_1),
                       ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)

        assert read_order(order_draft["id"])["work_status"] == "DRAFT"
        assert read_order(world["order"]["id"])["work_status"] == "DELIVERED"

        core = read_core(core_b["id"])
        assert core["status"] == "SHIPPED"
        assert core["rebuild_count"] == 2

        rows, _ = validate_paginated(
            api.list_order_bench_reservations(world["order"]["id"], PLANNER_1))
        assert rows[0]["status"] == "CONSUMED"
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 0


class TestQuoteComposition:

    def test_the_quote_counts_only_approved_lines_and_halves_aftermarket_coverage(self):
        """PRD 3.8: "For each part line of the order whose `approval_status` is `APPROVED` — and
        only those — the line's `qty` is multiplied by its `unit_cost_cents`, and those per-line
        products are summed into `parts_subtotal_cents`."
        PRD 3.8: "Second, the labour: the order's `labor_hours` is multiplied by the shop rate
        of $145.00 per hour and rounded half up to whole cents, giving `labor_cents`."
        PRD 3.8: "`covered_base_cents` is `labor_cents` plus, for each `APPROVED` part line,
        that line's `qty` multiplied by its `unit_cost_cents` multiplied by 1 when the line's
        `source_class` is `OEM` or by one half when it is `AFTERMARKET`, with each such line
        rounded half up to whole cents before the lines are summed."

        Design: Corner/calculations/quote_counts_only_approved_lines_and_halves_aftermarket_coverage
        """
        world = setup_shop(account_code="CVR-001", customer_name="Coverage Mill",
                           asset_tag="CVR-01-GBX", serial_no="SN-CVR-1",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5)
        order_id, cust_id = world["order"]["id"], world["customer"]["id"]

        pl_oem = add_part_line(order_id, part_no="BRG-22324", source_class="OEM",
                               qty=2, unit_cost_cents=38500)
        pl_am = add_part_line(order_id, part_no="AM-SEAL-7", source_class="AFTERMARKET",
                              qty=1, unit_cost_cents=20000)
        pl_open = add_part_line(order_id, part_no="SHIM-KIT-2", source_class="OEM",
                                qty=1, unit_cost_cents=9000)
        for line in (pl_oem, pl_am, pl_open):
            submit_part_line(line["id"])
        decide_part_line(pl_oem["id"], cust_id, "APPROVE")
        decide_part_line(pl_am["id"], cust_id, "APPROVE")

        order = order_action(order_id, "QUOTE")
        assert order["approval_status"] == "PARTIAL"
        assert order["parts_subtotal_cents"] == 97000
        assert order["labor_cents"] == 94250
        assert order["pre_credit_subtotal_cents"] == 191250
        assert order["expedite_surcharge_cents"] == 0
        assert order["core_credit_applied_cents"] == 10800
        assert order["quote_total_cents"] == 180450
        assert order["covered_base_cents"] == 181250

        quote = read_quote(order_id)
        assert quote["credit_cap_cents"] == 76500

        rows, _ = validate_paginated(api.list_part_lines(order_id, PLANNER_1))
        still_open = [r for r in rows if r["id"] == pl_open["id"]][0]
        assert still_open["approval_status"] == "SUBMITTED"

    def test_the_quote_read_exposes_the_cap_and_the_live_staleness_flag(self):
        """PRD 3.8: "The order's pricing chain is readable at any time as a computed view that
        reports `work_status`, `approval_status`, `parts_subtotal_cents`, `labor_cents`,
        `pre_credit_subtotal_cents`, `expedite_surcharge_cents`, `gross_total_cents`,
        `credit_cap_cents`, `core_credit_applied_cents`, `quote_total_cents`,
        `covered_base_cents`, `quoted_part_revision`, `part_revision_counter` and a live
        `quote_stale` boolean, the last being true exactly when the snapshotted revision and the
        live counter disagree."
        PRD 3.8: "The cap is forty percent of `gross_total_cents`, truncated downward to a whole
        cent rather than rounded — this is the one place in the document where a floor replaces
        round-half-up on money — and it is surfaced on the quote read as `credit_cap_cents`."

        Design: Corner/endpoints/quote_computed_read_exposes_cap_and_staleness
        """
        world = setup_shop(account_code="STL-001", customer_name="Stale Mill",
                           asset_tag="STL-01-GBX", serial_no="SN-STL-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        order_id, cust_id = world["order"]["id"], world["customer"]["id"]
        add_approved_part_line(order_id, cust_id, part_no="BRG-22324", qty=1,
                               unit_cost_cents=40000)
        order_action(order_id, "QUOTE")

        first = read_quote(order_id)
        assert first["labor_cents"] == 58000
        assert first["parts_subtotal_cents"] == 40000
        assert first["pre_credit_subtotal_cents"] == 98000
        assert first["credit_cap_cents"] == 39200
        assert first["core_credit_applied_cents"] == 39200
        assert first["quote_total_cents"] == 58800
        assert first["quote_stale"] is False
        assert first["quoted_part_revision"] == 3
        assert first["part_revision_counter"] == 3

        add_part_line(order_id, part_no="SHIM-1", source_class="OEM", qty=1,
                      unit_cost_cents=500)

        second = read_quote(order_id)
        assert second["quote_stale"] is True
        assert second["quoted_part_revision"] == 3
        assert second["part_revision_counter"] == 4
        assert second["quote_total_cents"] == 58800, (
            "adding a line does not re-price the order"
        )


class TestSubstitutionPolicy:

    def test_rebuild_ceiling_and_un_waivered_aftermarket_lines_are_refused(self):
        """PRD 3.7: "There is one hard gate at creation: the core's `rebuild_count` must be
        strictly less than the governing spec's `max_rebuild_count`. A core that has already
        reached the ceiling is not re-manufacturable, and the attempt is
        `ERR_REBUILD_LIMIT_REACHED` (HTTP 422)."
        PRD 3.7: "A line whose `source_class` is `AFTERMARKET` on an order whose destination
        asset has a `criticality` of `CRITICAL` is only permitted when the line carries a
        non-empty `engineering_waiver_ref`; without one the request is
        `ERR_AFTERMARKET_NOT_PERMITTED` (HTTP 422)."

        Design: Corner/errors/rebuild_limit_and_aftermarket_waiver_policy_are_rejected
        """
        world = setup_shop(account_code="POL-001", customer_name="Policy Mill",
                           asset_tag="POL-01-GBX", criticality="CRITICAL",
                           serial_no="SN-POL-MAX", rebuild_count=3,
                           declared_condition_grade="GRADE_B", with_order=False)
        cust_id, asset_id, std_id = (world["customer"]["id"], world["asset"]["id"],
                                     world["standard"]["id"])
        core_max = world["core"]
        core_ok = create_core(cust_id, std_id, serial_no="SN-POL-OK", rebuild_count=2,
                              declared_condition_grade="GRADE_B")

        validate_error(api.create_rebuild_order({
            "customer_id": cust_id, "core_unit_id": core_max["id"],
            "customer_asset_id": asset_id, "labor_hours": 4.0}, PLANNER_1),
            ApiErrorId.ERR_REBUILD_LIMIT_REACHED.value, 422)

        order = create_order(cust_id, core_ok["id"], asset_id, labor_hours=4.0)
        v1 = order_version(order["id"])

        validate_error(api.create_part_line(order["id"], {
            "part_no": "AM-BRG-1", "source_class": "AFTERMARKET", "qty": 1,
            "unit_cost_cents": 30000, "expected_order_version": v1}, PLANNER_1),
            ApiErrorId.ERR_AFTERMARKET_NOT_PERMITTED.value, 422)

        waivered = validate_success(api.create_part_line(order["id"], {
            "part_no": "AM-BRG-1", "source_class": "AFTERMARKET", "qty": 1,
            "unit_cost_cents": 30000, "engineering_waiver_ref": "ENG-WVR-2211",
            "expected_order_version": v1}, PLANNER_1), 201)
        assert waivered["engineering_waiver_ref"] == "ENG-WVR-2211", (
            "the refused line never advanced the order, so the same version still applies"
        )

        _, meta = validate_paginated(api.list_part_lines(order["id"], PLANNER_1))
        assert meta["total_count"] == 1
