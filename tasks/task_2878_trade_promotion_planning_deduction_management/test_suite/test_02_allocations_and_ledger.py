"""
Budget allocations, the allocation ledger and the two conservation identities.

Each test builds every precondition it needs from the declared endpoints and
asserts only the figures the PRD pins.
"""

import pytest

from test_helpers import (
    AccrualMethod,
    AllocationPosture,
    AllocationStatus,
    ApiErrorId,
    Channel,
    DEFAULT_CLOCK_INSTANT,
    DeductionValidationPolicy,
    EventType,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_31,
    PerformanceFlag,
    ProgramStatus,
    PromotionLifecycleStatus,
    SpendStatus,
    TacticStatus,
    assert_allocation,
    assert_money,
    assert_program,
    assert_promotion,
    assert_ratio,
    assert_tactic,
    create_allocation_payload,
    create_brand_payload,
    create_promotion_payload,
    current_allocation_version,
    get_by_id,
    read_allocation,
    read_program,
    read_promotion,
    read_tactic,
    set_clock,
    setup_allocation_context,
    setup_approved_promotion,
    setup_brand,
    setup_customer,
    setup_draft_allocation,
    setup_program,
    setup_submitted_promotion,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_promotion_payload,
)


def _seasonal_reference_data(api, budget=5000000.00,
                             accrual_default=AccrualMethod.SHIPMENT.value):
    """A program with one brand and one customer, all under one director."""
    program = setup_program(
        api, fiscal_year=2026, name="FY2026 National Trade Fund",
        total_budget_amount=budget, accrual_method_default=accrual_default,
    )
    brand = setup_brand(
        api, program["id"], name="Crisp Oat Cereal",
        list_price_per_case=24.00, cogs_per_case=8.70,
        baseline_units_per_week=1200,
    )
    customer = setup_customer(
        api, program["id"], name="MegaMart", channel=Channel.GROCERY.value,
        deduction_validation_policy=DeductionValidationPolicy.EVIDENCE_BASED.value,
    )
    return program, brand, customer


class TestPromotionCreateGatedOnAllocationStatus:
    """Whether a promotion may exist at all is decided on the parent cell."""

    def test_create_against_a_draft_cell_is_refused_and_writes_nothing(
        self, api, director, key_account_manager
    ):
        """
        A promotion create against a `DRAFT` cell is refused and leaves no row behind.

        PRD: "Promotions may be created against a cell only once it is `APPROVED`; a promotion create or submit against a `DRAFT` cell is refused with `ERR_ALLOCATION_NOT_APPROVED` (HTTP 409)."
        PRD: "A newly created allocation has `status` `DRAFT`, `posture` `OPEN` and an `overspend_event_count` of 0, and its ledger is initialised so that `committed_amount` is 0.00, `available_amount` equals `planned_amount`, `committed_units` is 0 and `unreserved_units` equals `planned_incremental_units`; `accrued_amount`, `settled_amount` and `at_risk_amount` all start at 0.00."

        Design: Difficulty/cross_entity_state_dependency/promotion_create_gated_on_budget_allocation_status
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(api)
        allocation = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        assert allocation["status"] == AllocationStatus.DRAFT.value

        response = api.create_promotion(
            create_promotion_payload(
                allocation["id"], allocation["version"],
                name="Gated Event", window_start=MONDAY_AUG_03,
                window_end=MONDAY_AUG_31,
                accrual_method=AccrualMethod.SHIPMENT.value,
            ),
            key_account_manager,
        )
        validate_error(response, ApiErrorId.ALLOCATION_NOT_APPROVED.value)

        rows, meta = validate_paginated(
            api.list_promotions(director, {"allocation_id": allocation["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_refused_create_does_not_bump_the_parent_version(
        self, api, director, key_account_manager
    ):
        """
        A create the parent's own state refuses must not advance the parent's `version`.

        PRD: "Promotions may be created against a cell only once it is `APPROVED`; a promotion create or submit against a `DRAFT` cell is refused with `ERR_ALLOCATION_NOT_APPROVED` (HTTP 409)."
        PRD: "Creating it increments the funding allocation's `version` by 1 — the parent version advances on every child create, which is exactly why replaying an `expected_allocation_version` that has already been used fails."

        Design: Difficulty/cross_entity_state_dependency/promotion_create_gated_on_budget_allocation_status
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(api)
        allocation = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        version_before = allocation["version"]

        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], version_before,
                    name="Gated Event", window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    accrual_method=AccrualMethod.SHIPMENT.value,
                ),
                key_account_manager,
            ),
            ApiErrorId.ALLOCATION_NOT_APPROVED.value,
        )

        unchanged = read_allocation(api, allocation["id"])
        assert unchanged["version"] == version_before
        assert unchanged["status"] == AllocationStatus.DRAFT.value

    def test_the_same_payload_lands_once_the_cell_is_approved(
        self, api, director, key_account_manager
    ):
        """
        Approving the parent admits the identical create, and the draft child reserves nothing.

        PRD: "Promotions may be created against a cell only once it is `APPROVED`; a promotion create or submit against a `DRAFT` cell is refused with `ERR_ALLOCATION_NOT_APPROVED` (HTTP 409)."
        PRD: "A freshly planned promotion sits in `lifecycle_status` `DRAFT` with `spend_status` `WITHIN_BUDGET`, `performance_flag` `UNRATED` and `revision_round` 0, and its `approved_by_user_id` is null."
        PRD: "`committed_amount` is the sum of `planned_total_spend` across child promotions whose `lifecycle_status` is `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, rounded half up to 2 decimal places; promotions in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `WITHDRAWN` reserve nothing."

        Design: Difficulty/cross_entity_state_dependency/promotion_create_gated_on_budget_allocation_status
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(api)
        allocation = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )

        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], allocation["version"],
                    name="Gated Event", window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    accrual_method=AccrualMethod.SHIPMENT.value,
                ),
                key_account_manager,
            ),
            ApiErrorId.ALLOCATION_NOT_APPROVED.value,
        )

        approved = validate_success(
            api.approve_budget_allocation(allocation["id"], director)
        )
        assert approved["status"] == AllocationStatus.APPROVED.value

        promotion = validate_success(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], approved["version"],
                    name="Gated Event", window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    accrual_method=AccrualMethod.SHIPMENT.value,
                ),
                key_account_manager,
            ),
            201,
        )
        assert_promotion(promotion)
        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value
        assert promotion["performance_flag"] == PerformanceFlag.UNRATED.value
        assert promotion["revision_round"] == 0

        parent = read_allocation(api, allocation["id"])
        assert parent["status"] == AllocationStatus.APPROVED.value
        assert_money(parent["committed_amount"], 0.00, "committed_amount")


def _approved_promotion_reserving_eight_thousand_units(api):
    """
    An `APPROVED` promotion of 10200.00 and 8000 cases on a 100000.00 / 20000 cell.

    Nothing has been activated or accrued, so `gross_accrued_amount` is still
    0.00 and the withdrawal precondition is satisfied.
    """
    context = setup_allocation_context(
        api,
        program_overrides={
            "fiscal_year": 2026,
            "name": "FY2026 National Trade Fund",
            "total_budget_amount": 5000000.00,
            "accrual_method_default": AccrualMethod.SHIPMENT.value,
        },
        brand_overrides={
            "name": "Crisp Oat Cereal",
            "list_price_per_case": 24.00,
            "cogs_per_case": 8.70,
            "baseline_units_per_week": 1200,
        },
        customer_overrides={
            "name": "MegaMart",
            "channel": Channel.GROCERY.value,
            "deduction_validation_policy":
                DeductionValidationPolicy.EVIDENCE_BASED.value,
        },
        event_type=EventType.SEASONAL.value,
        planned_amount=100000.00,
        baseline_units=40000,
        planned_incremental_units=20000,
    )
    return setup_approved_promotion(
        api, context,
        promotion_overrides={
            "name": "Cancelled Fall Event",
            "window_start": MONDAY_AUG_03,
            "window_end": MONDAY_AUG_31,
            "accrual_method": AccrualMethod.SHIPMENT.value,
        },
        planned_units=8000,
        rate_per_case=1.25,
        window_start=MONDAY_AUG_03,
        window_end=MONDAY_AUG_31,
    )


class TestPromotionWithdrawalRestoresTheUnitIdentity:
    """Approval reserves units and dollars; withdrawal gives every one of them back."""

    def test_approval_reserves_both_quantities_and_the_unit_identity_holds(self, api):
        """
        Mid-flight the cell shows 8000 of 20000 cases and 10200.00 of 100000.00 dollars committed.

        PRD: "The allocation then reserves both quantities at once: `committed_amount` rises by the promotion's `planned_total_spend`, `committed_units` rises by the promotion's `committed_units`, and `available_amount` and `unreserved_units` are recomputed from those."
        PRD: "From those, `available_amount` is `planned_amount` minus `committed_amount`, rounded to 2 decimal places, and `unreserved_units` is `planned_incremental_units` minus `committed_units`."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."

        Design: Difficulty/compensating_invariant/promotion_withdrawal_restores_the_allocation_unit_identity
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _approved_promotion_reserving_eight_thousand_units(api)
        promotion = context["promotion"]
        allocation = context["allocation"]

        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.APPROVED.value
        assert_money(promotion["tactic_subtotal_amount"], 10000.00,
                     "tactic_subtotal_amount")
        assert promotion["allowance_rate"] == pytest.approx(0.020, abs=1e-9)
        assert_money(promotion["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount")
        assert_money(promotion["planned_total_spend"], 10200.00,
                     "planned_total_spend")
        assert promotion["committed_units"] == 8000

        assert_allocation(allocation)
        assert_money(allocation["committed_amount"], 10200.00, "committed_amount")
        assert_money(allocation["available_amount"], 89800.00, "available_amount")
        assert allocation["committed_units"] == 8000
        assert allocation["unreserved_units"] == 12000
        assert allocation["planned_incremental_units"] == (
            allocation["committed_units"] + allocation["unreserved_units"]
        )

    def test_withdrawal_returns_every_dollar_and_every_case(
        self, api, key_account_manager
    ):
        """
        After withdrawal the cell is byte-for-byte back at its pre-approval capacity.

        PRD: "Withdrawing an approved promotion, by contrast, is a genuinely complete compensation: it restores the allocation's `available_amount` and `unreserved_units` to exactly their pre-approval values."
        PRD: "A `KeyAccountManager` withdraws a promotion that is currently `APPROVED`, optionally recording a `withdraw_reason`, and the move `APPROVED` → `WITHDRAWN` is terminal."
        PRD: "`committed_amount` is the sum of `planned_total_spend` across child promotions whose `lifecycle_status` is `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, rounded half up to 2 decimal places; promotions in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `WITHDRAWN` reserve nothing."

        Design: Difficulty/compensating_invariant/promotion_withdrawal_restores_the_allocation_unit_identity
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _approved_promotion_reserving_eight_thousand_units(api)
        promotion_id = context["promotion"]["id"]
        allocation_id = context["allocation"]["id"]

        withdrawn = validate_success(
            api.withdraw_promotion(
                promotion_id, key_account_manager,
                withdraw_promotion_payload(
                    withdraw_reason="Retailer cancelled the event before it started"
                ),
            )
        )
        assert withdrawn["lifecycle_status"] == PromotionLifecycleStatus.WITHDRAWN.value

        released = read_allocation(api, allocation_id)
        assert_allocation(released)
        assert_money(released["committed_amount"], 0.00, "committed_amount")
        assert_money(released["available_amount"], 100000.00, "available_amount")
        assert released["committed_units"] == 0
        assert released["unreserved_units"] == 20000
        assert released["planned_incremental_units"] == (
            released["committed_units"] + released["unreserved_units"]
        )

    def test_withdrawal_cancels_the_line_and_zeroes_the_promotion_figures(
        self, api, key_account_manager
    ):
        """
        The cascade cancels the line, which drops the whole planning rollup to zero.

        PRD: "Withdrawal cascades conditionally through the tactic lines: every line whose `status` is `PLANNED` or `ACTIVE` becomes `CANCELLED`, while `COMPLETED` lines are left untouched."
        PRD: "Because those lines have left the `PLANNED`/`ACTIVE`/`COMPLETED` population, the promotion's `committed_units` recomputes to 0 and its `planned_total_spend` recomputes to 0.00; and because the promotion itself has left the `APPROVED`/`LIVE`/`ENDED`/`ANALYZED` population, the allocation drops this promotion's contribution from `committed_amount` and `committed_units`, restoring `available_amount` and `unreserved_units` to exactly their pre-approval values."
        PRD: "When the promotion's `planned_total_spend` is 0.00, `spend_ratio` is 0.0000 and `spend_status` is `WITHIN_BUDGET`."

        Design: Difficulty/compensating_invariant/promotion_withdrawal_restores_the_allocation_unit_identity
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _approved_promotion_reserving_eight_thousand_units(api)
        promotion_id = context["promotion"]["id"]
        tactic_id = context["tactic"]["id"]
        program_id = context["program"]["id"]

        validate_success(
            api.withdraw_promotion(
                promotion_id, key_account_manager,
                withdraw_promotion_payload(
                    withdraw_reason="Retailer cancelled the event before it started"
                ),
            )
        )

        cancelled_line = read_tactic(api, tactic_id)
        assert cancelled_line["status"] == TacticStatus.CANCELLED.value

        promotion = read_promotion(api, promotion_id)
        assert_promotion(promotion)
        assert_money(promotion["tactic_subtotal_amount"], 0.00,
                     "tactic_subtotal_amount")
        assert promotion["allowance_rate"] == pytest.approx(0.000, abs=1e-9)
        assert_money(promotion["off_invoice_allowance_amount"], 0.00,
                     "off_invoice_allowance_amount")
        assert_money(promotion["planned_total_spend"], 0.00, "planned_total_spend")
        assert promotion["committed_units"] == 0
        assert_ratio(promotion["spend_ratio"], 0.0000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        program = read_program(api, program_id)
        assert_money(program["allocated_amount"], 100000.00, "allocated_amount")


class TestAllocationCreateRequestShape:
    """`planned_amount` has no default, so shape validation runs before any fiscal rule."""

    def test_omitted_and_explicit_null_planned_amount_both_fail_the_shape_gate(
        self, api, director
    ):
        """
        Neither the omitted nor the null form of `planned_amount` creates a cell.

        PRD: "A `TradeMarketingDirector` or a `TradeFinanceAnalyst` creates one by supplying `program_id`, `customer_id`, `brand_id`, an `event_type` of `SEASONAL`, `EVERYDAY` or `NEW_ITEM`, a `planned_amount` in USD (strictly positive, exactly 2 decimal places), a `baseline_units` figure (a whole number at or above zero) recording the non-promoted case volume the cell assumes for the year, and a `planned_incremental_units` figure (also a whole number at or above zero) recording the incremental case volume the money is expected to buy."
        PRD: "A monetary field in a request body must be a number that is at or above 0.00 and carries at most 2 decimal places; a rate must carry at most 3; a unit count must be an integer at or above 0; a timestamp must be an RFC 3339 UTC instant ending in `Z`; an enum field must carry one of its declared values; every required field must be present and non-null; and unknown fields are rejected outright."
        PRD: "Any of these failures is reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/allocation_create_with_null_planned_amount_fails_request_shape
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(
            api, budget=500000.00,
            accrual_default=AccrualMethod.CONSUMPTION.value,
        )

        omitted = create_allocation_payload(
            program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value,
            baseline_units=40000, planned_incremental_units=20000,
        )
        omitted.pop("planned_amount")
        validate_error(
            api.create_budget_allocation(omitted, director),
            ApiErrorId.INVALID_REQUEST.value,
        )

        explicit_null = create_allocation_payload(
            program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=None,
            baseline_units=40000, planned_incremental_units=20000,
        )
        assert explicit_null["planned_amount"] is None
        validate_error(
            api.create_budget_allocation(explicit_null, director),
            ApiErrorId.INVALID_REQUEST.value,
        )

        rows, meta = validate_paginated(
            api.list_budget_allocations(director, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

        untouched = read_program(api, program["id"])
        assert_money(untouched["allocated_amount"], 0.00, "allocated_amount")
        assert_money(untouched["unallocated_amount"], 500000.00, "unallocated_amount")


class TestProgramLockCascade:
    """The year-end lock drives the posture axis without touching the approval axis."""

    def test_lock_freezes_both_child_postures_and_leaves_each_status_alone(
        self, api, director
    ):
        """
        Both cells land in `FROZEN`, while the draft one stays `DRAFT` and the approved one `APPROVED`.

        PRD: "The lock may only be applied to a program that is currently `OPEN`, and it does far more than flip a flag: every budget allocation whose `program_id` names this program is repostured, and because a locked program outranks every other posture consideration, each of those allocations lands in `FROZEN` posture and has its own `version` incremented by 1 and its `updated_at` refreshed."
        PRD: "It is recomputed when the owning program is locked, when a child promotion reaches `OVERSPENT`, and whenever the allocation is read, using a strict precedence of `FROZEN` over `RESTRICTED` over `OPEN`: if the owning program's `status` is `LOCKED` the posture is `FROZEN`; otherwise, if the allocation's `overspend_event_count` is 1 or more the posture is `RESTRICTED`; otherwise it is `OPEN`."
        PRD: "Allocations may be listed with optional `program_id`, `customer_id`, `brand_id`, `event_type`, `status` and `posture` filters."

        Design: Corner/state_machines/program_lock_freezes_every_open_allocation_posture
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(
            api, budget=500000.00,
            accrual_default=AccrualMethod.CONSUMPTION.value,
        )
        draft_cell = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=30000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        second_cell = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.EVERYDAY.value, planned_amount=20000.00,
            baseline_units=10000, planned_incremental_units=5000,
        )
        approved_cell = validate_success(
            api.approve_budget_allocation(second_cell["id"], director)
        )
        assert approved_cell["posture"] == AllocationPosture.OPEN.value

        locked = validate_success(api.lock_program(program["id"], director))
        assert locked["status"] == ProgramStatus.LOCKED.value

        rows, meta = validate_paginated(
            api.list_budget_allocations(
                director,
                {"program_id": program["id"],
                 "posture": AllocationPosture.FROZEN.value},
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {draft_cell["id"], approved_cell["id"]}

        frozen_draft = read_allocation(api, draft_cell["id"])
        assert frozen_draft["status"] == AllocationStatus.DRAFT.value
        assert frozen_draft["posture"] == AllocationPosture.FROZEN.value

        frozen_approved = read_allocation(api, approved_cell["id"])
        assert frozen_approved["status"] == AllocationStatus.APPROVED.value
        assert frozen_approved["posture"] == AllocationPosture.FROZEN.value

        after_lock = read_program(api, program["id"])
        assert_program(after_lock)
        assert_money(after_lock["allocated_amount"], 50000.00, "allocated_amount")
        assert_money(after_lock["unallocated_amount"], 450000.00, "unallocated_amount")

    def test_lock_refuses_a_further_brand_registration(self, api, director):
        """
        The brand create that succeeded while the program was `OPEN` is now refused.

        PRD: "Once a program is `LOCKED`, three further writes under it are refused with `ERR_PROGRAM_LOCKED` (HTTP 409): registering a new brand, creating a new budget allocation, and approving an existing one."
        PRD: "Brands may be listed with an optional `program_id` filter, which is how the brands of one program are found."

        Design: Corner/errors/program_lock_blocks_further_program_level_writes
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program = setup_program(
            api, fiscal_year=2026, name="FY2026 National Trade Fund",
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        first_brand = setup_brand(
            api, program["id"], name="Crisp Oat Cereal",
            list_price_per_case=24.00, cogs_per_case=8.70,
            baseline_units_per_week=1200,
        )

        locked = validate_success(api.lock_program(program["id"], director))
        assert locked["status"] == ProgramStatus.LOCKED.value

        validate_error(
            api.create_brand(
                create_brand_payload(
                    program["id"], name="Honey Nut Clusters",
                    list_price_per_case=26.00, cogs_per_case=9.40,
                    baseline_units_per_week=800,
                ),
                director,
            ),
            ApiErrorId.PROGRAM_LOCKED.value,
        )

        rows, meta = validate_paginated(
            api.list_brands(director, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_brand["id"]]


class TestAllocationApproveAction:
    """A bodiless action endpoint whose whole meaning is in its side effects."""

    def test_approve_moves_the_status_bumps_the_version_and_seeds_the_ledger(
        self, api, director, finance_analyst
    ):
        """
        `DRAFT` becomes `APPROVED` at version 2, with the ledger seeded from the plan.

        PRD: "A `TradeMarketingDirector` approves an allocation that is currently `DRAFT` under a program that is currently `OPEN`, moving `status` `DRAFT` → `APPROVED`; the whole ledger rollup is recomputed and the allocation's `version` is incremented by 1 with `updated_at` refreshed."
        PRD: "A newly created allocation has `status` `DRAFT`, `posture` `OPEN` and an `overspend_event_count` of 0, and its ledger is initialised so that `committed_amount` is 0.00, `available_amount` equals `planned_amount`, `committed_units` is 0 and `unreserved_units` equals `planned_incremental_units`; `accrued_amount`, `settled_amount` and `at_risk_amount` all start at 0.00."
        PRD: "From those, `available_amount` is `planned_amount` minus `committed_amount`, rounded to 2 decimal places, and `unreserved_units` is `planned_incremental_units` minus `committed_units`."

        Design: Corner/endpoints/allocation_approve_action_seeds_the_ledger_rollup
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer = _seasonal_reference_data(
            api, budget=500000.00,
            accrual_default=AccrualMethod.CONSUMPTION.value,
        )

        cell = validate_success(
            api.create_budget_allocation(
                create_allocation_payload(
                    program["id"], customer["id"], brand["id"],
                    event_type=EventType.NEW_ITEM.value, planned_amount=75000.00,
                    baseline_units=30000, planned_incremental_units=12000,
                ),
                finance_analyst,
            ),
            201,
        )
        assert cell["status"] == AllocationStatus.DRAFT.value
        assert cell["version"] == 1

        approved = validate_success(
            api.approve_budget_allocation(cell["id"], director)
        )

        assert_allocation(approved)
        assert approved["status"] == AllocationStatus.APPROVED.value
        assert approved["version"] == 2
        assert_money(approved["available_amount"], 75000.00, "available_amount")
        assert approved["unreserved_units"] == 12000
        assert_money(approved["committed_amount"], 0.00, "committed_amount")
        assert_money(approved["accrued_amount"], 0.00, "accrued_amount")
        assert_money(approved["settled_amount"], 0.00, "settled_amount")
        assert_money(approved["at_risk_amount"], 0.00, "at_risk_amount")
        assert approved["posture"] == AllocationPosture.OPEN.value
        assert approved["overspend_event_count"] == 0


class TestUnitReservationIsIndependentOfTheMoney:
    """A promotion can clear the money gate and still fail on incremental cases."""

    def test_units_fail_while_the_money_still_fits(self, api, director):
        """
        500.00 of spend fits inside 100000.00, yet 1000 cases do not fit inside 100.

        PRD: "A `TradeMarketingDirector` approves a promotion that is currently `SUBMITTED`, provided that: the funding allocation is `APPROVED` and its `posture` is `OPEN`; the allocation's customer is in `trading_status` `ACTIVE`; the promotion's `commitment_verified` is true, meaning every `DISPLAY` or `FEATURE` tactic type on the promotion is covered by a `VERIFIED` `COMMITMENT` document whose `covers_tactic_type` is that type or `ALL` — a failure here is `ERR_COMMITMENT_DOCUMENTATION_MISSING` (HTTP 422), and a promotion with only `TPR` lines passes it vacuously; the allocation's `available_amount` is at or above the promotion's `planned_total_spend`, since `available_amount` still excludes this not-yet-committed promotion — a failure here is `ERR_ALLOCATION_BALANCE_INSUFFICIENT` (HTTP 422); and the promotion's `committed_units` is at or below the allocation's `unreserved_units` — a failure here is `ERR_UNITS_EXCEED_UNRESERVED` (HTTP 422)."
        PRD: "`unreserved_units` is `planned_incremental_units` minus `committed_units`."

        Design: Corner/errors/unit_reservation_can_fail_while_the_money_still_fits
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "fiscal_year": 2026,
                "name": "FY2026 National Trade Fund",
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.CONSUMPTION.value,
            },
            brand_overrides={
                "name": "Crisp Oat Cereal",
                "list_price_per_case": 24.00,
                "cogs_per_case": 8.70,
                "baseline_units_per_week": 1200,
            },
            customer_overrides={
                "name": "MegaMart",
                "channel": Channel.GROCERY.value,
                "deduction_validation_policy":
                    DeductionValidationPolicy.EVIDENCE_BASED.value,
            },
            event_type=EventType.EVERYDAY.value,
            planned_amount=100000.00,
            baseline_units=60000,
            planned_incremental_units=100,
        )
        assert_money(context["allocation"]["available_amount"], 100000.00,
                     "available_amount before approval")
        assert context["allocation"]["unreserved_units"] == 100

        context = setup_submitted_promotion(
            api, context,
            promotion_overrides={
                "name": "Thin Reservation Event",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
                "accrual_method": AccrualMethod.CONSUMPTION.value,
            },
            planned_units=1000,
            rate_per_case=0.500,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_17,
        )
        submitted = context["promotion"]
        assert_money(submitted["planned_total_spend"], 500.00, "planned_total_spend")
        assert submitted["committed_units"] == 1000

        validate_error(
            api.approve_promotion(submitted["id"], director),
            ApiErrorId.UNITS_EXCEED_UNRESERVED.value,
        )

        untouched = read_allocation(api, context["allocation"]["id"])
        assert untouched["committed_units"] == 0
        assert untouched["unreserved_units"] == 100


class TestApprovalResponseCarriesTheCommittedLedger:
    """The approve response is the committed truth, not a stale snapshot."""

    def test_the_approval_response_and_the_follow_up_read_agree(self, api, director):
        """
        Approval returns the promotion already priced and already committed.

        PRD: "The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."
        PRD: "The allocation then reserves both quantities at once: `committed_amount` rises by the promotion's `planned_total_spend`, `committed_units` rises by the promotion's `committed_units`, and `available_amount` and `unreserved_units` are recomputed from those."
        PRD: "The **money and units identity** on a budget allocation: `planned_amount` always equals `committed_amount` plus `available_amount`, and `planned_incremental_units` always equals `committed_units` plus `unreserved_units`."

        Design: Corner/consistency_model/the_approval_response_already_carries_the_committed_ledger
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "fiscal_year": 2026,
                "name": "FY2026 National Trade Fund",
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.SHIPMENT.value,
            },
            brand_overrides={
                "name": "Crisp Oat Cereal",
                "list_price_per_case": 24.00,
                "cogs_per_case": 8.70,
                "baseline_units_per_week": 1200,
            },
            customer_overrides={
                "name": "MegaMart",
                "channel": Channel.GROCERY.value,
                "deduction_validation_policy":
                    DeductionValidationPolicy.EVIDENCE_BASED.value,
            },
            event_type=EventType.SEASONAL.value,
            planned_amount=100000.00,
            baseline_units=40000,
            planned_incremental_units=20000,
        )
        assert_money(context["allocation"]["available_amount"], 100000.00,
                     "available_amount before approval")
        assert context["allocation"]["unreserved_units"] == 20000

        context = setup_submitted_promotion(
            api, context,
            promotion_overrides={
                "name": "Back To School Feature",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_10,
                "accrual_method": AccrualMethod.SHIPMENT.value,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )
        promotion_id = context["promotion"]["id"]

        approved = validate_success(api.approve_promotion(promotion_id, director))

        assert_promotion(approved)
        assert approved["lifecycle_status"] == PromotionLifecycleStatus.APPROVED.value
        assert_money(approved["tactic_subtotal_amount"], 10000.00,
                     "tactic_subtotal_amount")
        assert_ratio(approved["allowance_rate"], 0.020, "allowance_rate")
        assert_money(approved["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount")
        assert_money(approved["planned_total_spend"], 10200.00, "planned_total_spend")
        assert approved["committed_units"] == 8000

        reread = read_promotion(api, promotion_id)
        assert reread["lifecycle_status"] == approved["lifecycle_status"]
        assert_money(reread["tactic_subtotal_amount"], 10000.00,
                     "tactic_subtotal_amount on re-read")
        assert_ratio(reread["allowance_rate"], 0.020, "allowance_rate on re-read")
        assert_money(reread["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount on re-read")
        assert_money(reread["planned_total_spend"], 10200.00,
                     "planned_total_spend on re-read")
        assert reread["committed_units"] == 8000

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_allocation(allocation)
        assert_money(allocation["committed_amount"], 10200.00, "committed_amount")
        assert_money(allocation["available_amount"], 89800.00, "available_amount")
        assert allocation["committed_units"] == 8000
        assert allocation["unreserved_units"] == 12000

        program = read_program(api, context["program"]["id"])
        assert_program(program)
        assert_money(program["allocated_amount"], 100000.00, "allocated_amount")
        assert_money(program["unallocated_amount"], 400000.00, "unallocated_amount")

    def test_the_response_object_matches_the_read_field_for_field(self, api, director):
        """
        Nothing in the committed ledger changes between the action and a later read.

        PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD: "`planned_total_spend` is the figure that will be committed against the allocation at approval."

        Design: Corner/consistency_model/the_approval_response_already_carries_the_committed_ledger
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "fiscal_year": 2026,
                "name": "FY2026 National Trade Fund",
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.SHIPMENT.value,
            },
            event_type=EventType.SEASONAL.value,
            planned_amount=100000.00,
            baseline_units=40000,
            planned_incremental_units=20000,
        )
        context = setup_submitted_promotion(
            api, context,
            promotion_overrides={
                "name": "Back To School Feature",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_10,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )

        approved = validate_success(
            api.approve_promotion(context["promotion"]["id"], director)
        )
        reread = read_promotion(api, context["promotion"]["id"])

        for field in (
            "lifecycle_status",
            "spend_status",
            "allowance_rate",
            "committed_units",
            "revision_round",
            "version",
        ):
            assert approved[field] == reread[field], (
                f"{field} differs between the approve response and the read"
            )
        for money_field in (
            "tactic_subtotal_amount",
            "off_invoice_allowance_amount",
            "planned_total_spend",
        ):
            assert_money(approved[money_field], reread[money_field], money_field)
