"""Program-attributed spend: pinned price book, pipeline/delivered counters,
the lot-QC-failure cascade, deliver/return conservation, the program-state
gate on submission, and the state-beats-fiscal validation order
(PRD sections 2.9, 3.3, 3.4, 3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_active_program,
    create_kit,
    create_order,
    create_passed_lot,
    create_submitted_program,
    deliver_order,
    lot_qc_payload,
    make_lab_operator_headers,
    order_advance_payload,
    order_line,
    setup_breached_account,
    setup_program_order_pipeline,
    ship_order,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client

SP = TEST_USERS["supply_planner_headers"]
FA = TEST_USERS["finance_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _get_program(program_id: str) -> dict:
    return validate_success(api_client.get_placement_program(program_id, FA))


def _get_account(account_id: str) -> dict:
    return validate_success(api_client.get_account(account_id, AM))


def _submit(order_id: str, account_id: str):
    return api_client.advance_reagent_order(
        order_id,
        order_advance_payload("SUBMIT"),
        make_lab_operator_headers(account_id),
    )


class TestLotQcFailureCascade:
    def test_lot_failure_releases_reservation_and_backorders_order(self, api):
        """A FAILED verdict on a released lot pulls its reservations back and
        pushes the unfulfillable order ALLOCATED -> BACKORDERED.

        PRD §3.4: "Every reservation held on the lot is released — the entries come out of each order's `line_reservations` and the lot's `reserved_units` drops accordingly — and then every order that held a reservation on the lot and cannot be fully re-allocated from the remaining usable lots transitions from `ALLOCATED` to `BACKORDERED`, subtracting its `attributed_total_cents` from its program's `pipeline_spend_cents`."
        PRD §3.5: "An `ALLOCATED` order slides to `BACKORDERED` when a lot cascade (§3.4) releases its reservations and full re-allocation proves impossible — its reservations are gone and its attributed amount leaves `pipeline_spend_cents`."

        Design: Difficulty/transitive_cascade/lot_qc_failure_cascade
        """
        bag = setup_program_order_pipeline(
            kit_price_cents=5000, lot_quantity=10, order_quantity=2,
            advance_to="ALLOCATED",
        )
        lot_after = validate_success(
            api_client.post_lot_qc(bag["lot"]["id"], lot_qc_payload("FAILED"), SP)
        )
        assert lot_after["qc_status"] == "QC_FAILED"
        assert lot_after["reserved_units"] == 0
        order_after = validate_success(
            api_client.get_reagent_order(bag["order"]["id"], SP)
        )
        assert order_after["order_state"] == "BACKORDERED"
        assert order_after["line_reservations"] == []

    def test_lot_failure_debits_program_pipeline(self, api):
        """The same cascade subtracts the order's attributed 10,000c from the
        program's pipeline_spend_cents while delivered spend stays 0.

        PRD §3.4: "Every reservation held on the lot is released — the entries come out of each order's `line_reservations` and the lot's `reserved_units` drops accordingly — and then every order that held a reservation on the lot and cannot be fully re-allocated from the remaining usable lots transitions from `ALLOCATED` to `BACKORDERED`, subtracting its `attributed_total_cents` from its program's `pipeline_spend_cents`."

        Design: Difficulty/transitive_cascade/lot_qc_failure_cascade
        """
        bag = setup_program_order_pipeline(
            kit_price_cents=5000, lot_quantity=10, order_quantity=2,
            advance_to="ALLOCATED",
        )
        before = _get_program(bag["program"]["id"])
        assert before["pipeline_spend_cents"] == 10_000, (
            "2 units x pinned 5,000c must sit in the pipeline"
        )
        validate_success(
            api_client.post_lot_qc(bag["lot"]["id"], lot_qc_payload("FAILED"), SP)
        )
        after = _get_program(bag["program"]["id"])
        assert after["pipeline_spend_cents"] == 0
        assert after["delivered_spend_cents"] == 0


class TestDeliverReturnConservation:
    def test_deliver_then_return_conserves_delivered_spend(self, api):
        """Delivery posts +10,000c of attributed spend; the return subtracts
        it again, restoring the counter to exactly its pre-delivery value.

        PRD §3.5: "For a program-attributed order, delivery moves `attributed_total_cents` out of the program's `pipeline_spend_cents` and into its `delivered_spend_cents`, then checks the auto-completion rule of §3.3."
        PRD §3.5: "Returning is allowed from `DELIVERED` and lands in `RETURNED`: for a program-attributed order the program's `delivered_spend_cents` decreases by `attributed_total_cents`, preserving the invariant that a delivery followed by a return leaves delivered spend unchanged; the account's `credit_balance_cents` increases by the order's `total_cents` as a refund in account credit; and the returned units are never restocked to any lot."

        Design: Difficulty/compensating_invariant/deliver_return_conserves_delivered_spend
        """
        bag = setup_program_order_pipeline(
            kit_price_cents=5000, lot_quantity=10, order_quantity=2,
            advance_to="DELIVERED",
        )
        mid = _get_program(bag["program"]["id"])
        assert mid["delivered_spend_cents"] == 10_000
        assert mid["program_state"] == "ACTIVE", (
            "10,000c is far below the 12,000,000c commitment — no auto-complete"
        )
        resp = api_client.advance_reagent_order(
            bag["order"]["id"],
            order_advance_payload("RETURN"),
            make_lab_operator_headers(bag["account"]["id"]),
        )
        assert validate_success(resp)["order_state"] == "RETURNED"
        end = _get_program(bag["program"]["id"])
        assert end["delivered_spend_cents"] == 0, (
            "deliver-then-return must conserve delivered_spend_cents exactly"
        )

    def test_return_refunds_to_account_credit_not_delivered_spend(self, api):
        """The return refunds the order's 10,000c total to the account's
        credit balance; that refund does not flow through delivered spend.

        PRD §3.5: "Returning is allowed from `DELIVERED` and lands in `RETURNED`: for a program-attributed order the program's `delivered_spend_cents` decreases by `attributed_total_cents`, preserving the invariant that a delivery followed by a return leaves delivered spend unchanged; the account's `credit_balance_cents` increases by the order's `total_cents` as a refund in account credit; and the returned units are never restocked to any lot."

        Design: Difficulty/compensating_invariant/deliver_return_conserves_delivered_spend
        """
        bag = setup_program_order_pipeline(
            kit_price_cents=5000, lot_quantity=10, order_quantity=2,
            advance_to="DELIVERED",
        )
        validate_success(
            api_client.advance_reagent_order(
                bag["order"]["id"],
                order_advance_payload("RETURN"),
                make_lab_operator_headers(bag["account"]["id"]),
            )
        )
        account = _get_account(bag["account"]["id"])
        assert account["credit_balance_cents"] == 10_000, (
            f"refund must post total_cents to account credit, got "
            f"{account['credit_balance_cents']}"
        )
        assert _get_program(bag["program"]["id"])["delivered_spend_cents"] == 0


class TestOrderSubmitRequiresProgramActive:
    def test_pending_approval_program_blocks_submit(self, api):
        """A PENDING_APPROVAL program gates the order's DRAFT -> ALLOCATED
        transition; the order stays DRAFT and nothing is reserved.

        PRD §3.5: "Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_program_active
        """
        account = create_account()
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=10)
        program = create_submitted_program(account_id=account["id"])
        assert program["program_state"] == "PENDING_APPROVAL"
        order = create_order(
            account["id"], [order_line(kit["kit_code"], 1)],
            program_id=program["id"],
        )
        resp = _submit(order["id"], account["id"])
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        order_after = validate_success(
            api_client.get_reagent_order(order["id"], SP)
        )
        assert order_after["order_state"] == "DRAFT"
        lot_after = validate_success(api_client.get_reagent_lot(lot["id"], SP))
        assert lot_after["reserved_units"] == 0

    def test_completed_program_blocks_submit(self, api):
        """A program that auto-completed on an exact-commitment delivery
        rejects every later order referencing it.

        PRD §3.3: "When a delivery posts attributed spend and the program's `delivered_spend_cents` reaches at least its `committed_total_cents`, the program transitions itself from `ACTIVE` to `COMPLETED` as a side effect of the delivery; from then on, any order referencing it fails submission with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_program_active
        """
        account = create_account()
        kit = create_kit(price_cents=600_000)
        create_passed_lot(kit_id=kit["id"], quantity_units=5)
        # committed_total = 1,200,000 * 12 / 12 = 1,200,000; one 2-unit order
        # at the pinned 600,000c delivers exactly the commitment.
        program = create_active_program(
            account_id=account["id"], committed_annual_reagent_cents=1_200_000
        )
        first = create_order(
            account["id"], [order_line(kit["kit_code"], 2)],
            program_id=program["id"],
        )
        submit_order(first["id"], account["id"])
        ship_order(first["id"])
        deliver_order(first["id"])
        assert _get_program(program["id"])["program_state"] == "COMPLETED"
        second = create_order(
            account["id"], [order_line(kit["kit_code"], 1)],
            program_id=program["id"],
        )
        resp = _submit(second["id"], account["id"])
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


class TestStateBeatsFiscalOnOrderSubmit:
    def test_program_not_active_wins_over_credit_hold(self, api):
        """One request violates both the program-state gate (program B is
        PENDING_APPROVAL) and the fiscal gate (account on credit hold from
        program A's breach); the state error is reported.

        PRD §3.5: "Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere."
        PRD §2.9: "Only after all eight tiers pass do the domain rules of §3 evaluate: state-specific gates first, then regulatory and safety gates, then uniqueness and compatibility constraints including segregation of duties and optimistic concurrency, then temporal window rules, and finally fiscal gates."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_submit
        """
        bag = setup_breached_account()
        account = bag["account"]
        assert account["credit_hold"] is True
        program_b = create_submitted_program(account_id=account["id"])
        kit = create_kit()
        create_passed_lot(kit_id=kit["id"], quantity_units=10)
        order = create_order(
            account["id"], [order_line(kit["kit_code"], 1)],
            program_id=program_b["id"],
        )
        resp = _submit(order["id"], account["id"])
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        order_after = validate_success(
            api_client.get_reagent_order(order["id"], SP)
        )
        assert order_after["order_state"] == "DRAFT"

    def test_breached_program_reference_also_yields_state_error(self, api):
        """Referencing the BREACHED program itself (the very source of the
        account's credit hold) still surfaces the state error, not the
        fiscal one.

        PRD §3.5: "Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere."
        PRD §2.9: "Only after all eight tiers pass do the domain rules of §3 evaluate: state-specific gates first, then regulatory and safety gates, then uniqueness and compatibility constraints including segregation of duties and optimistic concurrency, then temporal window rules, and finally fiscal gates."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_submit
        """
        bag = setup_breached_account()
        account = bag["account"]
        assert bag["program"]["program_state"] == "BREACHED"
        kit = create_kit()
        create_passed_lot(kit_id=kit["id"], quantity_units=10)
        order = create_order(
            account["id"], [order_line(kit["kit_code"], 1)],
            program_id=bag["program"]["id"],
        )
        resp = _submit(order["id"], account["id"])
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


class TestPinnedPriceBook:
    def test_program_orders_bill_at_pinned_prices(self, api):
        """After approval pins the kit at 5,000c and the catalog moves to
        7,000c, the attributed order bills 5,000c while an unattributed order
        bills the current 7,000c.

        PRD §3.3: "A successful approval snapshots `pinned_kit_prices` — the current `price_cents` of every kit in the catalog, keyed by kit code — and records `approved_by_user_id`; attributed orders will bill at those pinned prices even if catalog prices move afterwards (§3.1)."
        PRD §3.5: "Pricing happens at submission: with `program_id` set, each line prices at the program's `pinned_kit_prices`, otherwise at the kit's current `price_cents`; the server stores `total_cents` as the sum over lines of quantity times unit price, and `attributed_total_cents` equal to `total_cents` when a program is referenced and 0 otherwise."

        Design: Corner/calculations/pinned_kit_price_used_for_program_orders
        """
        account = create_account()
        kit = create_kit(price_cents=5000)
        create_passed_lot(kit_id=kit["id"], quantity_units=10)
        program = create_active_program(account_id=account["id"])
        validate_success(
            api_client.update_reagent_kit(
                kit["id"], {"price_cents": 7000},
                TEST_USERS["platform_admin_headers"],
            )
        )
        order_pinned = create_order(
            account["id"], [order_line(kit["kit_code"], 1)],
            program_id=program["id"],
        )
        order_plain = create_order(
            account["id"], [order_line(kit["kit_code"], 1)]
        )
        pinned = submit_order(order_pinned["id"], account["id"])
        plain = submit_order(order_plain["id"], account["id"])
        assert pinned["total_cents"] == 5000
        assert pinned["attributed_total_cents"] == 5000
        assert plain["total_cents"] == 7000
        assert plain["attributed_total_cents"] == 0


class TestCreditHoldBlocksSubmit:
    def test_credit_hold_blocks_unattributed_order_submit(self, api):
        """With no program referenced, only the account's credit hold (from
        an unrelated breached program) can reject the SUBMIT — and it does.

        PRD §3.2: "The `credit_hold` flag is computed, not set directly: it is true exactly when the account has at least one placement program in `BREACHED` state, and while true it blocks reagent order submission (§3.5)."
        PRD §3.5: "Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere."

        Design: Corner/validations/credit_hold_blocks_order_submit
        """
        bag = setup_breached_account()
        account = bag["account"]
        assert account["credit_hold"] is True
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=10)
        order = create_order(account["id"], [order_line(kit["kit_code"], 1)])
        resp = _submit(order["id"], account["id"])
        validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)
        order_after = validate_success(
            api_client.get_reagent_order(order["id"], SP)
        )
        assert order_after["order_state"] == "DRAFT"
        lot_after = validate_success(api_client.get_reagent_lot(lot["id"], SP))
        assert lot_after["reserved_units"] == 0
