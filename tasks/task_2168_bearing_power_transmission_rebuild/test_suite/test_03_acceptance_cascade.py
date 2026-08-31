# -*- coding: utf-8 -*-
"""Four-eyes acceptance, its five-hop ledger cascade, and undoing a grade."""
import pytest

from test_helpers import (
    ADMIN_1, FOUR_BANDS, INSP_1, INSP_2, INSP_3, INSP_9, ONE_BAND, PLANNER_1,
    ApiErrorId, accept_inspection, add_measurement, api_client as api,
    create_reading, credit_notes, inspect_order, open_inspection, quote_order,
    read_core, read_customer, read_inspection, read_order, reopen_inspection,
    return_inspection, setup_shop, submit_inspection, validate_error,
    validate_paginated, validate_success,
)


def _canonical_quoted_world(account_code="NGM-007", serial_no="SN-77007"):
    world = setup_shop(account_code=account_code, asset_tag="CONV-04-GBX",
                       feature_bands=FOUR_BANDS, serial_no=serial_no,
                       rebuild_count=1, declared_condition_grade="GRADE_D",
                       labor_hours=6.5)
    quote_order(world)
    return world


class TestAcceptanceCascade:

    def test_accept_moves_the_inspection_the_core_and_the_ledger_together(self):
        """PRD 3.6: "Acceptance then unwinds as a five-hop cascade, and every hop is
        observable. The inspection itself moves `SUBMITTED → ACCEPTED` and records the caller
        as `accepted_by_user_id`."
        PRD 3.6: "Caused by that, the core takes on the bench verdict: its `condition_grade` is
        set from the inspection's `remaining_life_grade`, its status moves `INSPECTING →
        GRADED`, and its `final_core_credit_cents` is computed."
        PRD 2.9: "`core_credit_balance_cents` is the sum of `amount_cents` over the customer's
        `POSTED` notes whose `kind` is `CORE_EXCHANGE`"

        Design: Difficulty/transitive_cascade/inspection_accept_five_hop_ledger_cascade
        """
        world = _canonical_quoted_world()
        inspect_order(world, accept=False)

        before = read_order(world["order"]["id"])
        assert before["core_credit_applied_cents"] == 10800
        assert before["quote_total_cents"] == 160450

        accepted = accept_inspection(world["inspection"]["id"], user_id="insp-2")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "insp-2"

        core = read_core(world["core"]["id"])
        assert core["status"] == "GRADED"
        assert core["condition_grade"] == "GRADE_A"
        assert core["final_core_credit_cents"] == 81450

        rows, meta = credit_notes(customer_id=world["customer"]["id"], status="POSTED")
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 81450

        customer = read_customer(world["customer"]["id"])
        assert customer["total_credit_balance_cents"] == 81450

    def test_the_quoted_order_repriced_only_its_credit_draw_and_total(self):
        """PRD 3.6: "And caused by that in turn, every rebuild order of that same account whose
        `work_status` is `QUOTED` re-derives `core_credit_applied_cents` and
        `quote_total_cents` — those two figures only, as §2.9 requires — with each such order's
        `version` advancing."
        PRD 2.9: "The parts subtotal, the labour figure, the surcharge and the quoted revision
        snapshot are deliberately **not** re-taken, because the order's parts and labour have
        not changed; only the money available to draw down has."

        Design: Difficulty/transitive_cascade/inspection_accept_five_hop_ledger_cascade
        """
        world = _canonical_quoted_world()
        inspect_order(world, accept=False)
        accept_inspection(world["inspection"]["id"], user_id="insp-2")

        order = read_order(world["order"]["id"])
        assert order["core_credit_applied_cents"] == 68500, (
            "the draw is capped at floor(171250 * 0.40)"
        )
        assert order["quote_total_cents"] == 102750
        assert order["parts_subtotal_cents"] == 77000
        assert order["labor_cents"] == 94250
        assert order["covered_base_cents"] == 171250
        assert order["work_status"] == "QUOTED"

    def test_the_cascade_is_visible_in_the_reads_that_follow_the_accept_response(self):
        """PRD 2.9: "The response body returns the primary resource of the endpoint; the
        secondary movements are observable only by reading the affected records afterwards, and
        §3 states each of them explicitly."
        PRD 3.6: "Acceptance then unwinds as a five-hop cascade, and every hop is observable."
        PRD 2.9: "A `CreditNote` is never edited in place and never deleted: it is created
        `POSTED` and, if it must be undone, transitioned to `VOID`."

        Design: Corner/consistency_model/cascaded_fields_are_visible_in_the_response_that_caused_them
        """
        world = setup_shop(account_code="IMD-001", customer_name="Immediate Mill",
                           asset_tag="IMD-01-GBX", feature_bands=ONE_BAND,
                           serial_no="SN-IMD-1", rebuild_count=0,
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        inspect_order(world, measurements=(("BORE", 85),), accept=False)

        accepted = accept_inspection(world["inspection"]["id"], user_id="insp-2")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["remaining_life_grade"] == "GRADE_A"

        core = read_core(world["core"]["id"])
        assert core["status"] == "GRADED"
        assert core["condition_grade"] == "GRADE_A"
        assert core["final_core_credit_cents"] == 90000

        customer = read_customer(world["customer"]["id"])
        assert customer["core_credit_balance_cents"] == 90000
        assert customer["total_credit_balance_cents"] == 90000

        rows, meta = credit_notes(customer_id=world["customer"]["id"])
        assert meta["total_count"] == 2
        by_amount = {row["amount_cents"]: row for row in rows}
        assert by_amount[67500]["status"] == "VOID"
        assert by_amount[90000]["status"] == "POSTED"


class TestAcceptanceGuards:

    def test_an_inspector_may_not_accept_their_own_submission(self):
        """PRD 3.6: "Only an `Inspector` or a `ShopAdmin` may accept, the inspection must be
        `SUBMITTED`, and the accepting `X-User-ID` must differ from the `submitted_by_user_id`
        recorded at submission — an attempt to accept one's own work is
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/an_inspector_cannot_accept_their_own_submission
        """
        world = setup_shop(account_code="DTY-001", customer_name="Duty Mill",
                           asset_tag="DTY-01-GBX", serial_no="SN-DTY-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        inspect_order(world, measurements=(("BORE", 85),), accept=False)
        insp_id = world["inspection"]["id"]

        validate_error(api.advance_inspection(insp_id, {"action": "ACCEPT"}, INSP_1),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        assert read_inspection(insp_id)["status"] == "SUBMITTED"
        assert read_core(world["core"]["id"])["status"] == "INSPECTING"
        assert read_customer(world["customer"]["id"])["core_credit_balance_cents"] == 67500

        accepted = validate_success(
            api.advance_inspection(insp_id, {"action": "ACCEPT"}, INSP_9))
        assert accepted["accepted_by_user_id"] == "insp-9"
        assert read_core(world["core"]["id"])["final_core_credit_cents"] == 90000
        assert read_customer(world["customer"]["id"])["core_credit_balance_cents"] == 90000

    def test_a_sibling_inspection_cannot_be_accepted_once_one_is_accepted(self):
        """PRD 3.6: "Because an order may accumulate several inspections, acceptance is also
        exclusive: if any sibling inspection under the same `rebuild_order_id` already sits in
        `ACCEPTED`, the attempt is `ERR_INSPECTION_ALREADY_ACCEPTED` (HTTP 409)."
        PRD 3.4: "Opening a *second* inspection on an order whose core is already `INSPECTING`
        is allowed and creates a second inspection record, but no core transition fires and the
        core's state is left exactly as it was."

        Design: Corner/errors/second_inspection_cannot_be_accepted_while_one_is_already_accepted
        """
        world = setup_shop(account_code="TWN-001", customer_name="Twin Mill",
                           asset_tag="TWN-01-GBX", serial_no="SN-TWN-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        reading = create_reading(world["asset"]["id"])

        insp_a = open_inspection(world["order"]["id"],
                                 linked_vibration_reading_id=reading["id"])
        add_measurement(insp_a["id"], "BORE", 85)
        submit_inspection(insp_a["id"])

        insp_b = open_inspection(world["order"]["id"],
                                 linked_vibration_reading_id=reading["id"])
        add_measurement(insp_b["id"], "BORE", 70)
        submit_inspection(insp_b["id"])

        accept_inspection(insp_a["id"], user_id="insp-2")

        error = validate_error(
            api.advance_inspection(insp_b["id"], {"action": "ACCEPT"}, INSP_2),
            ApiErrorId.ERR_INSPECTION_ALREADY_ACCEPTED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_INSPECTION_INVALID_STATE.value

        assert read_inspection(insp_b["id"])["status"] == "SUBMITTED"
        assert read_inspection(insp_a["id"])["status"] == "ACCEPTED"
        core = read_core(world["core"]["id"])
        assert core["status"] == "GRADED" and core["condition_grade"] == "GRADE_A"

        rows, meta = credit_notes(core_unit_id=world["core"]["id"], status="POSTED")
        assert meta["total_count"] == 1 and rows[0]["amount_cents"] == 90000

    def test_replaying_accept_on_an_accepted_inspection_fires_no_second_cascade(self):
        """PRD 2.8: "The target record's own state admitting the requested action —
        `ERR_ORDER_INVALID_STATE`, `ERR_CORE_UNIT_INVALID_STATE`,
        `ERR_INSPECTION_INVALID_STATE`, `ERR_PART_LINE_INVALID_STATE`,
        `ERR_RESERVATION_INVALID_STATE`, `ERR_INSTALLATION_INVALID_STATE`,
        `ERR_CLAIM_INVALID_STATE` and `ERR_CREDIT_NOTE_INVALID_STATE`, all HTTP 409."
        PRD 3.6: "Only an `Inspector` or a `ShopAdmin` may accept, the inspection must be
        `SUBMITTED`, and the accepting `X-User-ID` must differ from the `submitted_by_user_id`
        recorded at submission"

        Design: Corner/state_machines/second_accept_on_an_accepted_inspection_returns_inspection_invalid_state
        """
        world = setup_shop(account_code="RPL-001", customer_name="Replay Mill",
                           asset_tag="RPL-01-GBX", feature_bands=FOUR_BANDS,
                           serial_no="SN-RPL-1", rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5)
        inspect_order(world)
        insp_id = world["inspection"]["id"]

        validate_error(api.advance_inspection(insp_id, {"action": "ACCEPT"}, INSP_3),
                       ApiErrorId.ERR_INSPECTION_INVALID_STATE.value, 409)

        assert read_inspection(insp_id)["accepted_by_user_id"] == "insp-2"
        assert read_customer(world["customer"]["id"])["total_credit_balance_cents"] == 81450
        rows, meta = credit_notes(core_unit_id=world["core"]["id"])
        assert meta["total_count"] == 2
        assert len([r for r in rows if r["status"] == "POSTED"]) == 1
        assert read_core(world["core"]["id"])["status"] == "GRADED"


class TestReturnAndRegrade:

    def test_return_then_reopen_wipes_every_computed_grading_output(self):
        """PRD 3.5: "A `ReliabilityEngineer` — and only that role, apart from a `ShopAdmin` —
        may send a `SUBMITTED` inspection back with a `return_reason`, moving it `SUBMITTED →
        RETURNED`. Returning grades nothing: no core is graded, no credit note is written, and
        no balance moves."
        PRD 3.5: "Reopening increments `revision_count` by 1, clears `submitted_by_user_id`
        back to null, and wipes all five computed grading outputs — `remaining_life_score`,
        `remaining_life_grade`, `life_score_variant`, `failure_cause_code` and
        `cause_confidence` are all set back to null so that the next submission recomputes them
        from scratch."

        Design: Corner/state_machines/inspection_return_then_reopen_clears_every_grading_field
        """
        world = setup_shop(account_code="LOP-001", customer_name="Loop Mill",
                           asset_tag="LOP-01-GBX", serial_no="SN-LOP-1",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=3.0)
        inspect_order(world, measurements=(("BORE", 85),), accept=False)
        insp_id = world["inspection"]["id"]

        returned = return_inspection(insp_id, "re-shoot the bore at temperature")
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == "re-shoot the bore at temperature"

        reopened = reopen_inspection(insp_id)
        assert reopened["status"] == "DRAFT"
        assert reopened["revision_count"] == 1
        assert reopened["remaining_life_score"] is None
        assert reopened["remaining_life_grade"] is None
        assert reopened["life_score_variant"] is None
        assert reopened["failure_cause_code"] is None
        assert reopened["cause_confidence"] is None
        assert reopened["submitted_by_user_id"] is None

        core = read_core(world["core"]["id"])
        assert core["status"] == "INSPECTING"
        assert core["condition_grade"] is None

        rows, meta = credit_notes(customer_id=world["customer"]["id"], status="POSTED")
        assert meta["total_count"] == 1 and rows[0]["amount_cents"] == 10800

        _, m_meta = validate_paginated(api.list_measurements(insp_id, ADMIN_1))
        assert m_meta["total_count"] == 1, "measurements survive the return loop"

    def test_reinspect_returns_a_graded_core_to_inspecting_and_clears_its_verdict(self):
        """PRD 3.6: "A grade is not irreversible. An `Inspector` or `ShopAdmin` may order a
        re-inspection, moving the core `GRADED → INSPECTING` again, provided the core is
        currently `GRADED` and no rebuild order referencing that core has reached `IN_PROGRESS`,
        `COMPLETED` or `DELIVERED`; a violation of either condition is
        `ERR_CORE_UNIT_INVALID_STATE` (HTTP 409)."
        PRD 3.6: "Re-inspection sends the accepted inspection back to `RETURNED` with a
        `return_reason` of "core re-inspection ordered", clears the core's `condition_grade` and
        `final_core_credit_cents` back to null, voids the core's `POSTED` `CORE_EXCHANGE` note,
        recomputes the account's balances, and re-derives `core_credit_applied_cents` and
        `quote_total_cents` on the account's `QUOTED` orders."

        Design: Difficulty/non_linear_state_machine/core_unit_regrade_cycle_returns_graded_core_to_inspecting
        """
        world = _canonical_quoted_world(account_code="NGM-006", serial_no="SN-77006")
        inspect_order(world)

        validate_success(api.advance_core_unit(
            world["core"]["id"], {"action": "REINSPECT"}, INSP_3))

        core = read_core(world["core"]["id"])
        assert core["status"] == "INSPECTING"
        assert core["condition_grade"] is None
        assert core["final_core_credit_cents"] is None
        assert read_inspection(world["inspection"]["id"])["status"] == "RETURNED"

    def test_reinspect_drives_the_balance_and_the_quoted_order_back_down(self):
        """PRD 2.9: "A customer's four balance fields — `core_credit_balance_cents`,
        `warranty_credit_balance_cents`, `manual_credit_balance_cents` and
        `total_credit_balance_cents` — are always recomputed in full from that customer's
        surviving `POSTED` notes, never adjusted by a delta."
        PRD 2.9: "Whenever a cascade posts or voids a note for a customer, every `RebuildOrder`
        of that customer whose `work_status` is `QUOTED` recomputes `core_credit_applied_cents`
        and `quote_total_cents` — and only those two."

        Design: Difficulty/non_linear_state_machine/core_unit_regrade_cycle_returns_graded_core_to_inspecting
        """
        world = _canonical_quoted_world(account_code="NGM-006", serial_no="SN-77006")
        inspect_order(world)

        validate_success(api.advance_core_unit(
            world["core"]["id"], {"action": "REINSPECT"}, INSP_3))

        customer = read_customer(world["customer"]["id"])
        assert customer["core_credit_balance_cents"] == 0
        assert customer["total_credit_balance_cents"] == 0

        order = read_order(world["order"]["id"])
        assert order["core_credit_applied_cents"] == 0
        assert order["quote_total_cents"] == 171250
        assert order["work_status"] == "QUOTED"
