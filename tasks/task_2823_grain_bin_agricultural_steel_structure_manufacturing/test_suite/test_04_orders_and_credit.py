"""Dealer orders and the credit ledger: three orthogonal state dimensions, the
confirmation gate ladder, the deposit, and the compensating cancel cascade."""

from test_helpers import (
    assert_credit_conservation,
    assert_dealer_ledger_invariants,
    assert_instant_equals,
    assert_order_price_buildup,
    assign_crew,
    cancel_order,
    confirm_order,
    create_dealer_order_payload,
    create_design,
    create_design_under_review,
    dealer_headers,
    order_payment_payload,
    pay_deposit,
    place_confirmed_order,
    place_order,
    place_paid_confirmed_order,
    read_dealer,
    read_order,
    register_crew,
    reset_credit_limit,
    seal_design,
    set_clock,
    setup_credit_hold_pair,
    setup_credit_ledger_orders,
    setup_reference_data,
    setup_unsealed_confirm_conflict,
    validate_error,
    validate_success,
)

# The canonical 12.0 m x 9.6 m CORN / G115 kit, booked OFFSEASON by a BASE dealer.
D1_TOTAL_CENTS = 2499667
D1_DEPOSIT_CENTS = 499933
D1_HOLD_CENTS = 1999734
ALPHA_LIMIT_CENTS = 900000000


class TestOrderDimensionsAdvanceIndependently:
    def test_confirm_deposit_and_crew_assignment_each_move_exactly_one_dimension(
        self, api
    ):
        """PRD §3.4: "A fresh order begins with `production_status` `DRAFT`,
        `financial_status` `AWAITING_DEPOSIT` and `installation_readiness` `UNASSIGNED`,
        with `freight_load_id` and `installation_crew_id` both null, `deposit_paid_cents` 0,
        `allocated_freight_cents` 0 and `freight_sequence` null."
        PRD §3.6: "A `DealerPrincipal` confirming its own order moves that order's
        `production_status` from `DRAFT` to `QUEUED`; an order in any other production state
        is refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "Confirmation is untouched by the financial dimension — the order's
        `financial_status` remains whatever it was, typically `AWAITING_DEPOSIT`."
        PRD §3.6: "On success the order enters `QUEUED` and the dealership's credit ledger is
        recomputed, advancing both the order's `version` and the dealership's `version` by 1 each."
        PRD §3.6: "On success the order's `deposit_paid_cents` is set to the posted
        `amount_cents`, its `financial_status` becomes `DEPOSIT_PAID`, and its `version` bumps by 1."
        PRD §3.9: "Assigning a crew to an order is a `PlantAdmin` action naming the crew with
        `installation_crew_id`, and it moves that order's `installation_readiness` from
        `UNASSIGNED` to `ASSIGNED`, bumping the order's `version` by 1."
        PRD §3.9: "The tier fixes the crew's diameter envelope, written onto the row as
        `max_diameter_m`: a `T1` crew may erect bins up to 9.5 metres, a `T2` crew up to
        15.5 metres, and a `T3` crew up to 30.0 metres."

        Design: Difficulty/non_linear_state_machine/dealer_order_production_and_financial_dimensions_advance_independently
        """
        ref = setup_reference_data()
        crew = register_crew(ref)
        assert crew["max_diameter_m"] == 30.0
        assert crew["status"] == "CERTIFIED"
        design = create_design_under_review(ref)
        order = place_order(ref, design)
        assert order["total_cents"] == D1_TOTAL_CENTS
        assert order["required_deposit_cents"] == D1_DEPOSIT_CENTS
        assert order["credit_hold_cents"] == D1_HOLD_CENTS
        assert_order_price_buildup(order)
        assert order["production_status"] == "DRAFT"
        assert order["financial_status"] == "AWAITING_DEPOSIT"
        assert order["installation_readiness"] == "UNASSIGNED"
        assert order["version"] == 1

        confirmed = confirm_order(ref, order)
        assert confirmed["production_status"] == "QUEUED"
        assert confirmed["financial_status"] == "AWAITING_DEPOSIT"
        assert confirmed["installation_readiness"] == "UNASSIGNED"
        assert confirmed["deposit_paid_cents"] == 0
        assert confirmed["installation_crew_id"] is None
        assert confirmed["version"] == 2
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == ALPHA_LIMIT_CENTS - D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == 898000266
        assert dealer["status"] == "ACTIVE"
        assert_dealer_ledger_invariants(dealer)

        paid = pay_deposit(ref, order)
        assert paid["financial_status"] == "DEPOSIT_PAID"
        assert paid["deposit_paid_cents"] == D1_DEPOSIT_CENTS
        assert paid["production_status"] == "QUEUED"
        assert paid["installation_readiness"] == "UNASSIGNED"
        assert paid["credit_hold_cents"] == D1_HOLD_CENTS
        assert paid["version"] == 3

        assigned = assign_crew(order, crew)
        assert assigned["installation_readiness"] == "ASSIGNED"
        assert assigned["installation_crew_id"] == crew["id"]
        assert assigned["production_status"] == "QUEUED"
        assert assigned["financial_status"] == "DEPOSIT_PAID"
        assert assigned["deposit_paid_cents"] == D1_DEPOSIT_CENTS
        assert assigned["version"] == 4

    def test_the_same_three_dimensions_reach_the_same_triple_in_the_reverse_order(
        self, api
    ):
        """PRD §3.6: "The production dimension is untouched, which means a `DRAFT` order may
        legitimately pay its deposit before it is ever confirmed."
        PRD §3.9: "The order must not already have an `installation_crew_id`, and its
        `production_status` must be neither `CANCELLED` nor `SHIPPED`; either condition is
        refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "Confirmation is untouched by the financial dimension — the order's
        `financial_status` remains whatever it was, typically `AWAITING_DEPOSIT`."
        PRD §3.6: "A `DealerPrincipal` confirming its own order moves that order's
        `production_status` from `DRAFT` to `QUEUED`; an order in any other production state
        is refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "`DRAFT` orders are excluded, because credit is committed by confirmation and
        not by pricing — an unconfirmed order carries a fully populated `credit_hold_cents` yet
        contributes nothing to the ledger."

        Design: Difficulty/non_linear_state_machine/dealer_order_production_and_financial_dimensions_advance_independently
        """
        ref = setup_reference_data()
        crew = register_crew(ref)
        design = create_design_under_review(ref)
        order = place_order(ref, design)

        # Deposit first, while the order is still DRAFT.
        paid = pay_deposit(ref, order)
        assert paid["financial_status"] == "DEPOSIT_PAID"
        assert paid["deposit_paid_cents"] == D1_DEPOSIT_CENTS
        assert paid["production_status"] == "DRAFT"
        assert paid["installation_readiness"] == "UNASSIGNED"
        assert paid["version"] == 2
        # Paying does not commit credit: only confirmation does.
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 0
        assert dealer["credit_available_cents"] == ALPHA_LIMIT_CENTS

        # Crew assignment second, still on a DRAFT order.
        assigned = assign_crew(order, crew)
        assert assigned["installation_readiness"] == "ASSIGNED"
        assert assigned["installation_crew_id"] == crew["id"]
        assert assigned["production_status"] == "DRAFT"
        assert assigned["financial_status"] == "DEPOSIT_PAID"
        assert assigned["version"] == 3

        # Confirmation last, and it perturbs neither of the other two dimensions.
        confirmed = confirm_order(ref, order)
        assert confirmed["production_status"] == "QUEUED"
        assert confirmed["financial_status"] == "DEPOSIT_PAID"
        assert confirmed["deposit_paid_cents"] == D1_DEPOSIT_CENTS
        assert confirmed["installation_readiness"] == "ASSIGNED"
        assert confirmed["installation_crew_id"] == crew["id"]
        assert confirmed["version"] == 4

        final = read_order(order["id"])
        assert final["production_status"] == "QUEUED"
        assert final["financial_status"] == "DEPOSIT_PAID"
        assert final["installation_readiness"] == "ASSIGNED"
        assert final["credit_hold_cents"] == D1_HOLD_CENTS
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == 898000266
        assert_credit_conservation(dealer, [final])


class TestOrderCancelRequeuesAHeldSibling:
    def test_cancel_releases_credit_reactivates_the_dealer_and_requeues_the_other_order(
        self, api
    ):
        """PRD §3.6: "A `DealerPrincipal` may cancel an order whose `production_status` is
        `DRAFT`, `QUEUED`, `KITTED`, `HOLD_CREDIT` or `HOLD_ENGINEERING`; an order already in
        `SHIPPED` or `CANCELLED` is refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "The second hop, caused by the credit hold being released rather than by the
        cancellation request, recomputes the dealership's ledger, which may drive that dealership
        from `CREDIT_HOLD` back to `ACTIVE` and thereby requeue its other held orders."
        PRD §3.6: "Raising the limit back so that `credit_available_cents` returns to zero or
        above drives the dealership from `CREDIT_HOLD` back to `ACTIVE`, and that transition in
        turn moves every one of that dealership's orders in `HOLD_CREDIT` back to `QUEUED`, again
        bumping each affected order's `version`."
        PRD §3.6: "The dealership's `status` is `CREDIT_HOLD` whenever `credit_available_cents`
        is below zero and `ACTIVE` otherwise."
        PRD §3.6: "Its `credit_available_cents` is the `credit_limit_cents` minus that committed
        sum, and it may legitimately go negative when the limit is lowered beneath the existing
        commitment."

        Design: Difficulty/transitive_cascade/order_cancel_cascades_credit_release_to_dealer_reactivation_to_held_order_requeue
        """
        env = setup_credit_hold_pair()
        ref, first, second = env["ref"], env["first"], env["second"]
        assert env["committed"] == 3999468

        # Hop 0 — the world before the trigger.
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_limit_cents"] == 3999467
        assert dealer["credit_committed_cents"] == 3999468
        assert dealer["credit_available_cents"] == -1
        assert dealer["status"] == "CREDIT_HOLD"
        assert first["production_status"] == "HOLD_CREDIT"
        assert second["production_status"] == "HOLD_CREDIT"
        assert second["version"] == 3

        # Hop 1 — the cancelled order releases its own hold.
        cancelled = cancel_order(ref, first)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOIDED"
        assert cancelled["credit_hold_cents"] == 0

        # Hop 2 — caused by hop 1, the re-derived ledger lifts the dealer back to ACTIVE.
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == 1999733
        assert dealer["status"] == "ACTIVE"
        assert_dealer_ledger_invariants(dealer)

        # Hop 3 — caused by hop 2, the sibling order it never referenced is requeued.
        survivor = read_order(second["id"])
        assert survivor["production_status"] == "QUEUED"
        assert survivor["credit_hold_cents"] == D1_HOLD_CENTS
        assert survivor["financial_status"] == "AWAITING_DEPOSIT"
        assert survivor["version"] == 4
        assert_credit_conservation(dealer, [read_order(first["id"]), survivor])

    def test_the_requeue_hop_does_not_fire_when_the_release_leaves_the_ledger_negative(
        self, api
    ):
        """PRD §3.6: "Lowering the limit below the committed amount drives the dealership from
        `ACTIVE` to `CREDIT_HOLD`, and that state change — the second hop of the credit chain,
        caused by the dealership's own transition rather than by the limit request — moves every
        one of that dealership's orders whose `production_status` is `QUEUED` into `HOLD_CREDIT`,
        bumping each affected order's `version` by 1."
        PRD §3.6: "The dealership's `status` is `CREDIT_HOLD` whenever `credit_available_cents`
        is below zero and `ACTIVE` otherwise."
        PRD §3.6: "`CANCELLED` orders are excluded, and cancellation independently forces that
        order's `credit_hold_cents` to 0, so the exclusion and the zeroing always agree."
        PRD §3.6: "Only `QUEUED` orders are swept into the hold and only `HOLD_CREDIT` orders are
        swept back out; orders in `KITTED`, `SHIPPED`, `HOLD_ENGINEERING`, `DRAFT` or `CANCELLED`
        are untouched in both directions."

        Design: Difficulty/transitive_cascade/order_cancel_cascades_credit_release_to_dealer_reactivation_to_held_order_requeue
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        first = place_confirmed_order(ref, design)
        second = place_confirmed_order(ref, design)

        # One cent short of a single hold rather than of the pair: after the release the
        # ledger is still negative, so hop 2 never fires and hop 3 cannot follow.
        held = reset_credit_limit(ref["alpha"], D1_HOLD_CENTS - 1)
        assert held["credit_limit_cents"] == 1999733
        assert held["credit_committed_cents"] == 3999468
        assert held["credit_available_cents"] == -1999735
        assert held["status"] == "CREDIT_HOLD"
        assert read_order(first["id"])["production_status"] == "HOLD_CREDIT"
        assert read_order(second["id"])["production_status"] == "HOLD_CREDIT"

        cancelled = cancel_order(ref, first)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOIDED"
        assert cancelled["credit_hold_cents"] == 0

        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == -1
        assert dealer["status"] == "CREDIT_HOLD"
        assert_dealer_ledger_invariants(dealer)

        survivor = read_order(second["id"])
        assert survivor["production_status"] == "HOLD_CREDIT"
        assert survivor["credit_hold_cents"] == D1_HOLD_CENTS
        assert survivor["version"] == 3
        assert_credit_conservation(dealer, [read_order(first["id"]), survivor])


class TestCreditConservationUnderCancellation:
    def test_cancelling_a_confirmed_order_zeroes_and_rederives_without_double_release(
        self, api
    ):
        """PRD §3.6: "The ledger is an aggregate, recomputed from scratch rather than adjusted
        incrementally."
        PRD §3.6: "A dealership's `credit_committed_cents` is the sum of `credit_hold_cents` over
        every order belonging to that dealership whose `production_status` is one of `QUEUED`,
        `KITTED`, `SHIPPED`, `HOLD_CREDIT` or `HOLD_ENGINEERING`."
        PRD §3.6: "After every mutation, forward or compensating, the invariant must hold exactly:
        a dealership's stored `credit_committed_cents` equals the sum of `credit_hold_cents` over
        that dealership's orders in the five participating production states."
        PRD §3.6: "Cancellation sets `production_status` to `CANCELLED` and `financial_status` to
        `VOIDED` as its first hop, zeroes `credit_hold_cents`, and detaches the order from any
        freight load still in `PLANNED` — clearing `freight_load_id`, zeroing
        `allocated_freight_cents` and nulling `freight_sequence` — after which the load's
        aggregates and per-order freight shares are re-derived over the orders that remain."
        PRD §3.6: "All of this is exact integer arithmetic in whole cents with no rounding
        anywhere."

        Design: Difficulty/compensating_invariant/cancelling_confirmed_orders_restores_the_dealer_credit_conservation_identity_without_double_release
        """
        env = setup_credit_ledger_orders()
        ref, confirmed, draft = env["ref"], env["confirmed"], env["draft"]

        # Checkpoint 0 — three confirmed holds, not four.
        for order in confirmed:
            assert order["production_status"] == "QUEUED"
            assert order["credit_hold_cents"] == D1_HOLD_CENTS
        assert draft["production_status"] == "DRAFT"
        assert draft["credit_hold_cents"] == D1_HOLD_CENTS
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 5999202
        assert dealer["credit_available_cents"] == 894000798
        assert dealer["credit_committed_cents"] != 4 * D1_HOLD_CENTS
        assert dealer["status"] == "ACTIVE"
        assert_credit_conservation(dealer, confirmed + [draft])

        # Checkpoint 1 — the zeroing and the re-derivation agree exactly.
        cancelled = cancel_order(ref, confirmed[1])
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOIDED"
        assert cancelled["credit_hold_cents"] == 0
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 3999468
        assert dealer["credit_available_cents"] == 896000532
        assert dealer["status"] == "ACTIVE"
        assert_dealer_ledger_invariants(dealer)

        survivors = [read_order(confirmed[0]["id"]), read_order(confirmed[2]["id"])]
        for order in survivors:
            assert order["production_status"] == "QUEUED"
            assert order["credit_hold_cents"] == D1_HOLD_CENTS
        assert sum(o["credit_hold_cents"] for o in survivors) == 3999468
        assert_credit_conservation(
            dealer, survivors + [read_order(cancelled["id"]), read_order(draft["id"])]
        )

    def test_cancelling_a_draft_order_moves_the_ledger_by_zero_and_a_replay_releases_nothing(
        self, api
    ):
        """PRD §3.6: "`DRAFT` orders are excluded, because credit is committed by confirmation and
        not by pricing — an unconfirmed order carries a fully populated `credit_hold_cents` yet
        contributes nothing to the ledger."
        PRD §3.6: "A `DealerPrincipal` may cancel an order whose `production_status` is `DRAFT`,
        `QUEUED`, `KITTED`, `HOLD_CREDIT` or `HOLD_ENGINEERING`; an order already in `SHIPPED` or
        `CANCELLED` is refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "After every mutation, forward or compensating, the invariant must hold exactly:
        a dealership's stored `credit_committed_cents` equals the sum of `credit_hold_cents` over
        that dealership's orders in the five participating production states."
        PRD §3.6: "Its `credit_available_cents` is the `credit_limit_cents` minus that committed
        sum, and it may legitimately go negative when the limit is lowered beneath the existing
        commitment."

        Design: Difficulty/compensating_invariant/cancelling_confirmed_orders_restores_the_dealer_credit_conservation_identity_without_double_release
        """
        env = setup_credit_ledger_orders()
        ref, confirmed, draft = env["ref"], env["confirmed"], env["draft"]
        cancel_order(ref, confirmed[1])
        baseline = read_dealer(ref["alpha"]["id"])
        assert baseline["credit_committed_cents"] == 3999468
        assert baseline["credit_available_cents"] == 896000532

        # Checkpoint 2 — compensating a priced but never-committed hold moves nothing.
        cancelled_draft = cancel_order(ref, draft)
        assert cancelled_draft["production_status"] == "CANCELLED"
        assert cancelled_draft["financial_status"] == "VOIDED"
        assert cancelled_draft["credit_hold_cents"] == 0
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 3999468
        assert dealer["credit_available_cents"] == 896000532
        assert dealer["status"] == "ACTIVE"

        # A replayed compensation is refused and releases nothing a second time.
        validate_error(
            api.cancel_dealer_order(confirmed[1]["id"], dealer_headers(ref)),
            "ERR_ORDER_STATE_INVALID",
            409,
        )
        # Checkpoint 3 — credit_available_cents never climbs above the limit.
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 3999468
        assert dealer["credit_available_cents"] == 896000532
        assert dealer["credit_available_cents"] <= dealer["credit_limit_cents"]
        assert dealer["credit_limit_cents"] == ALPHA_LIMIT_CENTS
        assert_dealer_ledger_invariants(dealer)
        assert_credit_conservation(
            dealer,
            [read_order(o["id"]) for o in confirmed] + [read_order(draft["id"])],
        )


class TestUnsealedDesignOutranksTheCreditShortfall:
    def test_the_state_error_answers_first_even_though_the_dealer_is_broke(self, api):
        """PRD §3.6: "Three gates guard the transition, and they are evaluated in the order given.
        First the engineering posture of the referenced design: when the design's `seal_required`
        is true the design must have reached `SEALED`, and when `seal_required` is false the design
        must be in either `UNDER_REVIEW` or `SEALED`. A design that satisfies neither reading is
        refused with `ERR_DESIGN_NOT_SEALED`. Second the permit clock, which applies only when the
        design's `seal_required` is true: the current logical clock must be at or after the
        design's `permit_ready_at`, and an earlier attempt is refused with
        `ERR_PERMIT_REVIEW_PENDING`. A design in a jurisdiction whose `seal_required` is false
        skips the permit gate entirely. Third the money: the dealership's `credit_available_cents`
        must be at least the order's `credit_hold_cents`, and a shortfall is refused with
        `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402."
        PRD §2.11: "7. State admissibility, on every state-transition endpoint: the addressed row,
        and any row the operation reads as a gate, must be in a state that admits the transition."
        PRD §2.11: "33. Dealer credit sufficiency, on order confirmation —
        `ERR_CREDIT_LIMIT_EXCEEDED`, 402."
        PRD §3.2: "its own `seal_required` flag is copied from the referenced jurisdiction's
        `seal_required` at the moment of creation and thereafter never re-read from the
        jurisdiction"

        Design: Difficulty/priority_pair_validation_conflict/unsealed_design_state_error_precedes_credit_limit_fiscal_error_on_order_confirm
        """
        env = setup_unsealed_confirm_conflict()
        ref, design, order = env["ref"], env["design"], env["order"]
        assert design["seal_required"] is True
        assert design["status"] == "UNDER_REVIEW"
        assert design["permit_ready_at"] is None
        assert order["credit_hold_cents"] == D1_HOLD_CENTS

        broke = read_dealer(ref["dealers"]["gamma"]["id"])
        assert broke["credit_limit_cents"] == 0
        assert broke["credit_available_cents"] == 0
        # The fiscal defect is genuinely live at the same time as the state defect.
        assert broke["credit_available_cents"] < order["credit_hold_cents"]

        validate_error(
            api.confirm_dealer_order(order["id"], dealer_headers(ref, "gamma")),
            "ERR_DESIGN_NOT_SEALED",
            409,
        )
        after = read_order(order["id"])
        assert after["production_status"] == "DRAFT"
        assert after["version"] == 1
        unchanged = read_dealer(ref["dealers"]["gamma"]["id"])
        assert unchanged["credit_committed_cents"] == 0
        assert unchanged["status"] == "ACTIVE"

    def test_repairing_the_state_defect_exposes_the_fiscal_error_underneath(self, api):
        """PRD §3.3: "Sealing writes the acting engineer's identifier into
        `sealed_by_engineer_id`, sets `sealed_at` to the current logical clock value, and sets
        `permit_ready_at` to `sealed_at` advanced by the jurisdiction's `permit_review_days` whole
        days."
        PRD §3.6: "Third the money: the dealership's `credit_available_cents` must be at least the
        order's `credit_hold_cents`, and a shortfall is refused with `ERR_CREDIT_LIMIT_EXCEEDED`
        and HTTP 402."
        PRD §2.11: "24. Permit review readiness, on order confirmation —
        `ERR_PERMIT_REVIEW_PENDING`, 422."
        PRD §2.4: "It maintains a **logical clock** whose startup value is exactly
        `2026-08-01T00:00:00Z`, and every deadline comparison in this specification — permit review
        readiness, crew certification expiry, the commercial season window, roll-forming line
        occupation windows and dealer-yard staging windows — reads that clock."

        Design: Difficulty/priority_pair_validation_conflict/unsealed_design_state_error_precedes_credit_limit_fiscal_error_on_order_confirm
        """
        env = setup_unsealed_confirm_conflict()
        ref, design, order = env["ref"], env["design"], env["order"]
        validate_error(
            api.confirm_dealer_order(order["id"], dealer_headers(ref, "gamma")),
            "ERR_DESIGN_NOT_SEALED",
            409,
        )

        sealed = seal_design(ref, design)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ref["sealer"]["id"]
        assert_instant_equals(sealed["sealed_at"], "2026-08-01T00:00:00Z", "sealed_at")
        assert_instant_equals(
            sealed["permit_ready_at"], "2026-08-22T00:00:00Z", "permit_ready_at"
        )
        assert sealed["seal_required"] is True

        # Clear the permit gate so nothing masks the money check.
        set_clock("2026-08-22T00:00:00Z")
        validate_error(
            api.confirm_dealer_order(order["id"], dealer_headers(ref, "gamma")),
            "ERR_CREDIT_LIMIT_EXCEEDED",
            402,
        )
        after = read_order(order["id"])
        assert after["production_status"] == "DRAFT"
        dealer = read_dealer(ref["dealers"]["gamma"]["id"])
        assert dealer["status"] == "ACTIVE"
        assert dealer["credit_committed_cents"] == 0
        assert dealer["credit_available_cents"] == 0


class TestDepositExactness:
    def test_the_deposit_must_match_to_the_cent_and_cannot_be_posted_twice(self, api):
        """PRD §3.4: "Step eight computes `required_deposit_cents` as twenty percent of
        `total_cents`, rounded half up to whole cents, and sets `credit_hold_cents` to
        `total_cents` minus `required_deposit_cents`."
        PRD §3.6: "A `DealerPrincipal` posts a deposit with `amount_cents`, and that amount must
        equal the order's `required_deposit_cents` exactly — partial payments and overpayments are
        both rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`."
        PRD §3.6: "The order's `financial_status` must be `AWAITING_DEPOSIT`; a second attempt
        against an order already in `DEPOSIT_PAID`, `RELEASED` or `VOIDED` is rejected with
        `ERR_DEPOSIT_ALREADY_PAID`."
        PRD §3.6: "On success the order's `deposit_paid_cents` is set to the posted `amount_cents`,
        its `financial_status` becomes `DEPOSIT_PAID`, and its `version` bumps by 1."

        Design: Corner/validations/deposit_must_equal_the_required_amount_exactly_and_cannot_be_paid_twice
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design)
        assert order["total_cents"] == D1_TOTAL_CENTS
        assert order["required_deposit_cents"] == D1_DEPOSIT_CENTS
        assert order["credit_hold_cents"] == D1_TOTAL_CENTS - D1_DEPOSIT_CENTS
        headers = dealer_headers(ref)

        for wrong in (D1_DEPOSIT_CENTS - 1, D1_DEPOSIT_CENTS + 1):
            validate_error(
                api.post_order_payment(
                    order["id"], order_payment_payload(wrong), headers
                ),
                "ERR_DEPOSIT_AMOUNT_MISMATCH",
                422,
            )
            assert read_order(order["id"])["deposit_paid_cents"] == 0

        paid = validate_success(
            api.post_order_payment(
                order["id"], order_payment_payload(D1_DEPOSIT_CENTS), headers
            )
        )
        assert paid["financial_status"] == "DEPOSIT_PAID"
        assert paid["deposit_paid_cents"] == D1_DEPOSIT_CENTS
        assert paid["production_status"] == "DRAFT"
        assert paid["credit_hold_cents"] == D1_HOLD_CENTS

        validate_error(
            api.post_order_payment(
                order["id"], order_payment_payload(D1_DEPOSIT_CENTS), headers
            ),
            "ERR_DEPOSIT_ALREADY_PAID",
            409,
        )
        assert read_order(order["id"])["deposit_paid_cents"] == D1_DEPOSIT_CENTS


class TestPermitReviewGate:
    def test_confirmation_waits_for_permit_ready_at_and_admits_that_exact_instant(
        self, api
    ):
        """PRD §3.6: "Second the permit clock, which applies only when the design's
        `seal_required` is true: the current logical clock must be at or after the design's
        `permit_ready_at`, and an earlier attempt is refused with `ERR_PERMIT_REVIEW_PENDING`."
        PRD §3.3: "Sealing writes the acting engineer's identifier into `sealed_by_engineer_id`,
        sets `sealed_at` to the current logical clock value, and sets `permit_ready_at` to
        `sealed_at` advanced by the jurisdiction's `permit_review_days` whole days."
        PRD §3.2: "the design's `sealed_by_engineer_id`, `sealed_at` and `permit_ready_at` all
        begin null, its `revision_round` begins at 0, its `status` begins at `DRAFT`, and its own
        `seal_required` flag is copied from the referenced jurisdiction's `seal_required` at the
        moment of creation and thereafter never re-read from the jurisdiction"
        PRD §2.4: "A `PlantAdmin` may move the clock forward or backward by supplying a
        `to_iso8601` instant; the response reports the new value as `current_utc`."

        Design: Corner/validations/permit_review_blocks_confirmation_until_the_clock_reaches_permit_ready_at
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref, jurisdiction="IA-CENTRAL")
        assert design["permit_ready_at"] is None
        sealed = seal_design(ref, design)
        assert sealed["status"] == "SEALED"
        assert_instant_equals(sealed["sealed_at"], "2026-08-01T00:00:00Z", "sealed_at")
        assert_instant_equals(
            sealed["permit_ready_at"], "2026-08-22T00:00:00Z", "permit_ready_at"
        )

        order = place_order(ref, design)
        headers = dealer_headers(ref)
        validate_error(
            api.confirm_dealer_order(order["id"], headers),
            "ERR_PERMIT_REVIEW_PENDING",
            422,
        )
        assert read_order(order["id"])["production_status"] == "DRAFT"

        set_clock("2026-08-21T23:59:59Z")
        validate_error(
            api.confirm_dealer_order(order["id"], headers),
            "ERR_PERMIT_REVIEW_PENDING",
            422,
        )
        assert read_order(order["id"])["production_status"] == "DRAFT"

        set_clock("2026-08-22T00:00:00Z")
        confirmed = validate_success(api.confirm_dealer_order(order["id"], headers))
        assert confirmed["production_status"] == "QUEUED"
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == D1_HOLD_CENTS
        assert dealer["credit_available_cents"] == 898000266


class TestSeasonWindow:
    def test_the_booked_season_must_match_the_clock_month_at_every_boundary(self, api):
        """PRD §3.4: "The season must be one of `PRESEASON`, `HARVEST_PEAK` or `OFFSEASON`, and it
        must equal the season the plant derives from the logical clock rather than whichever season
        the dealer would prefer: calendar months 1 through 6 derive `PRESEASON`, months 9, 10 and 11
        derive `HARVEST_PEAK`, and months 7, 8 and 12 derive `OFFSEASON`."
        PRD §3.4: "Month boundaries are UTC calendar months. A mismatch is rejected with
        `ERR_SEASON_WINDOW_MISMATCH`."
        PRD §3.4: "Step two computes `season_uplift_cents` as the `kit_subtotal_cents` multiplied
        by the season rate and rounded half up to whole cents, where the rate is negative five
        percent for `PRESEASON` — a genuine discount for buying before harvest — positive seven
        percent for `HARVEST_PEAK`, and zero for `OFFSEASON`; a preseason order therefore carries a
        negative `season_uplift_cents`."
        PRD §2.4: "Because the startup default falls in calendar month 8, the season derived from an
        untouched clock is `OFFSEASON`."

        Design: Corner/validations/order_season_must_match_the_clock_month_at_every_season_boundary
        """
        ref = setup_reference_data()
        design = create_design(ref)
        headers = dealer_headers(ref)
        accepted = []

        def book(season):
            return api.create_dealer_order(
                create_dealer_order_payload(
                    ref["alpha"]["id"], design["id"], order_season=season
                ),
                headers,
            )

        # Month 8 derives OFFSEASON.
        validate_error(book("HARVEST_PEAK"), "ERR_SEASON_WINDOW_MISMATCH", 422)
        offseason = validate_success(book("OFFSEASON"), 201)
        assert offseason["season_uplift_cents"] == 0
        accepted.append(offseason)

        # The last second of month 6 is still PRESEASON.
        set_clock("2026-06-30T23:59:59Z")
        preseason = validate_success(book("PRESEASON"), 201)
        assert preseason["season_uplift_cents"] == -119601
        accepted.append(preseason)

        # One second later month 7 belongs to OFFSEASON.
        set_clock("2026-07-01T00:00:00Z")
        validate_error(book("PRESEASON"), "ERR_SEASON_WINDOW_MISMATCH", 422)

        # The last second of month 11 is still HARVEST_PEAK.
        set_clock("2026-11-30T23:59:59Z")
        harvest = validate_success(book("HARVEST_PEAK"), 201)
        assert harvest["season_uplift_cents"] == 167442
        accepted.append(harvest)

        # One second later month 12 belongs to OFFSEASON.
        set_clock("2026-12-01T00:00:00Z")
        validate_error(book("HARVEST_PEAK"), "ERR_SEASON_WINDOW_MISMATCH", 422)
        december = validate_success(book("OFFSEASON"), 201)
        assert december["season_uplift_cents"] == 0
        accepted.append(december)

        # Only the uplift moved with the season; the kit itself never changed.
        for order in accepted:
            assert order["kit_subtotal_cents"] == 2392026
            assert_order_price_buildup(order)


class TestCreditLimitReset:
    def test_one_endpoint_drives_the_hold_cascade_down_and_back_up_again(self, api):
        """PRD §3.6: "A `PlantAdmin` may reset a dealership's line by supplying a new
        `credit_limit_cents`, which recomputes the ledger and bumps the dealership's `version` by 1."
        PRD §3.6: "Lowering the limit below the committed amount drives the dealership from `ACTIVE`
        to `CREDIT_HOLD`, and that state change — the second hop of the credit chain, caused by the
        dealership's own transition rather than by the limit request — moves every one of that
        dealership's orders whose `production_status` is `QUEUED` into `HOLD_CREDIT`, bumping each
        affected order's `version` by 1."
        PRD §3.6: "Raising the limit back so that `credit_available_cents` returns to zero or above
        drives the dealership from `CREDIT_HOLD` back to `ACTIVE`, and that transition in turn moves
        every one of that dealership's orders in `HOLD_CREDIT` back to `QUEUED`, again bumping each
        affected order's `version`."
        PRD §3.6: "Only `QUEUED` orders are swept into the hold and only `HOLD_CREDIT` orders are
        swept back out; orders in `KITTED`, `SHIPPED`, `HOLD_ENGINEERING`, `DRAFT` or `CANCELLED`
        are untouched in both directions."
        PRD §3.6: "The dealership's `status` is `CREDIT_HOLD` whenever `credit_available_cents` is
        below zero and `ACTIVE` otherwise."

        Design: Corner/endpoints/resetting_the_credit_limit_drives_the_hold_cascade_in_both_directions_from_one_endpoint
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        first = place_confirmed_order(ref, design)
        second = place_confirmed_order(ref, design)
        before = read_dealer(ref["alpha"]["id"])
        assert before["status"] == "ACTIVE"
        assert before["credit_committed_cents"] == 3999468
        assert before["credit_available_cents"] == 896000532
        dealer_version = before["version"]

        # Down: one cent short of the commitment.
        cut = reset_credit_limit(ref["alpha"], 3999467)
        assert cut["status"] == "CREDIT_HOLD"
        assert cut["credit_committed_cents"] == 3999468
        assert cut["credit_available_cents"] == -1
        assert cut["version"] == dealer_version + 1
        assert_dealer_ledger_invariants(cut)
        held_first = read_order(first["id"])
        held_second = read_order(second["id"])
        assert held_first["production_status"] == "HOLD_CREDIT"
        assert held_first["credit_hold_cents"] == D1_HOLD_CENTS
        assert held_second["production_status"] == "HOLD_CREDIT"
        assert held_second["credit_hold_cents"] == D1_HOLD_CENTS

        # Further down: an order already in HOLD_CREDIT is not re-cascaded.
        deeper = reset_credit_limit(ref["alpha"], 1000000)
        assert deeper["status"] == "CREDIT_HOLD"
        assert deeper["credit_available_cents"] == -2999468
        assert deeper["version"] == dealer_version + 2
        assert read_order(second["id"])["version"] == held_second["version"]

        # Up: reactivation tests credit_available_cents >= 0, so exactly 0 reactivates.
        restored = reset_credit_limit(ref["alpha"], 3999468)
        assert restored["credit_available_cents"] == 0
        assert restored["status"] == "ACTIVE"
        assert restored["version"] == dealer_version + 3
        assert read_order(first["id"])["production_status"] == "QUEUED"
        assert read_order(second["id"])["production_status"] == "QUEUED"

        # Re-setting the limit already in force still bumps the dealership's version.
        idempotent = reset_credit_limit(ref["alpha"], 3999468)
        assert idempotent["status"] == "ACTIVE"
        assert idempotent["credit_available_cents"] == 0
        assert idempotent["version"] == dealer_version + 4
        assert read_order(first["id"])["production_status"] == "QUEUED"
        assert read_order(second["id"])["production_status"] == "QUEUED"
        assert_credit_conservation(
            idempotent, [read_order(first["id"]), read_order(second["id"])]
        )


class TestCascadeSettlementIsImmediate:
    def test_every_credit_hop_is_already_settled_in_the_response_that_caused_it(
        self, api
    ):
        """PRD §2.6: "The plant runs an immediate-consistency model: there are no queues, no
        eventual reconciliation and no background sweepers."
        PRD §2.6: "When an operation triggers a chain of consequences, every hop of that chain is
        complete before the response is written, and the response body reflects the final state of
        the addressed resource."
        PRD §2.6: "The **credit chain** starts when a dealer's available credit crosses zero in
        either direction, which holds or releases that dealer's queued orders in bulk."
        PRD §3.6: "The second hop, caused by the credit hold being released rather than by the
        cancellation request, recomputes the dealership's ledger, which may drive that dealership
        from `CREDIT_HOLD` back to `ACTIVE` and thereby requeue its other held orders."

        Design: Corner/consistency_model/every_cascade_hop_is_already_settled_in_the_response_that_caused_it
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        first = place_paid_confirmed_order(ref, design)
        second = place_paid_confirmed_order(ref, design)
        before = read_dealer(ref["alpha"]["id"])
        assert before["status"] == "ACTIVE"
        assert before["credit_committed_cents"] == 2 * D1_HOLD_CENTS == 3999468
        assert before["credit_available_cents"] == 896000532
        assert read_order(first["id"])["production_status"] == "QUEUED"
        assert read_order(second["id"])["production_status"] == "QUEUED"

        # The mutating response itself carries the cascaded ledger, not the pre-request one.
        cut = reset_credit_limit(ref["alpha"], 3999467)
        assert cut["credit_limit_cents"] == 3999467
        assert cut["credit_committed_cents"] == 3999468
        assert cut["credit_available_cents"] == -1
        assert cut["status"] == "CREDIT_HOLD"

        # The very next read, with no intervening write, is already settled — twice over.
        for _ in range(2):
            held = read_order(first["id"])
            assert held["production_status"] == "HOLD_CREDIT"
            assert held["credit_hold_cents"] == D1_HOLD_CENTS
        assert read_order(second["id"])["production_status"] == "HOLD_CREDIT"
        echo = read_dealer(ref["alpha"]["id"])
        assert echo["status"] == "CREDIT_HOLD"
        assert echo["credit_committed_cents"] == 3999468
        assert echo["credit_available_cents"] == -1

        # The same symmetry in the release direction.
        cancelled = cancel_order(ref, first)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOIDED"
        assert cancelled["credit_hold_cents"] == 0
        for _ in range(2):
            after = read_dealer(ref["alpha"]["id"])
            assert after["credit_committed_cents"] == D1_HOLD_CENTS
            assert after["credit_available_cents"] == 1999733
            assert after["status"] == "ACTIVE"
        assert read_order(second["id"])["production_status"] == "QUEUED"
        terminal = read_order(first["id"])
        assert terminal["production_status"] == "CANCELLED"
        assert terminal["financial_status"] == "VOIDED"
        assert terminal["credit_hold_cents"] == 0
