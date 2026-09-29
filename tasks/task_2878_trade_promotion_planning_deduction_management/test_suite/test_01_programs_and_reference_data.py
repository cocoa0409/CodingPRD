"""
Trade programs, brands, retail customers and the program budget envelope.

Each test builds every precondition it needs from the declared endpoints and
asserts only the figures the PRD pins.
"""

import pytest

from test_helpers import (
    AccrualMethod,
    AllocationStatus,
    ApiErrorId,
    AuditStatus,
    Channel,
    DEFAULT_CLOCK_INSTANT,
    DeductionValidationPolicy,
    EventType,
    MONDAY_AUG_03,
    MONDAY_AUG_31,
    PerformanceFlag,
    ProgramStatus,
    PromotionLifecycleStatus,
    SpendStatus,
    TradingStatus,
    assert_allocation,
    assert_brand,
    assert_customer,
    assert_money,
    assert_program,
    create_allocation_payload,
    create_brand_payload,
    create_customer_payload,
    create_program_payload,
    create_promotion_payload,
    current_allocation_version,
    get_by_id,
    is_iso8601_timestamp,
    read_program,
    set_clock,
    setup_approved_allocation,
    setup_brand,
    setup_customer,
    setup_draft_allocation,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTradeProgramCreation:
    """Opening an annual trade program and the defaults that come with it."""

    def test_program_create_returns_every_declared_field(self, api, director):
        """
        A create carrying only the three required fields returns the whole row.

        PRD: "A newly opened program has `status` `OPEN`, an `allocated_amount` of 0.00 and an `unallocated_amount` equal to its `total_budget_amount`."
        PRD: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly three fractional digits, recorded when the row is first written."
        PRD: "Almost every resource additionally carries `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and is incremented by exactly 1 on every mutation of that row — including mutations that are side effects of an operation aimed at a different resource."

        Design: Corner/entities/program_creation_returns_the_full_declared_field_set
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        payload = create_program_payload(
            fiscal_year=2026,
            name="FY2026 National Trade Fund",
            total_budget_amount=100000.00,
        )
        payload.pop("accrual_method_default")

        program = validate_success(api.create_program(payload, director), 201)

        assert_program(program)
        assert program["fiscal_year"] == 2026
        assert program["name"] == "FY2026 National Trade Fund"
        assert_money(program["total_budget_amount"], 100000.00, "total_budget_amount")
        assert program["status"] == ProgramStatus.OPEN.value
        assert_money(program["allocated_amount"], 0.00, "allocated_amount")
        assert_money(program["unallocated_amount"], 100000.00, "unallocated_amount")
        assert program["version"] == 1
        assert is_iso8601_timestamp(program["created_at"])

    def test_omitted_accrual_method_default_reaches_the_promotion_as_shipment(
        self, api, director, key_account_manager
    ):
        """
        One omission applies the same default twice: on the program and on its promotion.

        PRD: "When `accrual_method_default` is omitted it is `SHIPMENT`."
        PRD: "The payload may carry an `accrual_method` of `SHIPMENT` or `CONSUMPTION`; when it is omitted the promotion inherits the owning program's `accrual_method_default`."
        PRD: "A freshly planned promotion sits in `lifecycle_status` `DRAFT` with `spend_status` `WITHIN_BUDGET`, `performance_flag` `UNRATED` and `revision_round` 0, and its `approved_by_user_id` is null."

        Design: Corner/entities/program_omitting_accrual_method_default_inherits_shipment
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program_payload = create_program_payload(
            fiscal_year=2026,
            name="FY2026 Default Basis Fund",
            total_budget_amount=500000.00,
        )
        program_payload.pop("accrual_method_default")
        program = validate_success(api.create_program(program_payload, director), 201)
        assert program["accrual_method_default"] == AccrualMethod.SHIPMENT.value

        brand = setup_brand(
            api, program["id"], name="Crisp Oat Cereal",
            list_price_per_case=24.00, cogs_per_case=8.70,
            baseline_units_per_week=1200,
        )
        customer = setup_customer(api, program["id"], name="MegaMart",
                                  channel=Channel.GROCERY.value)
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )

        promotion_payload = create_promotion_payload(
            allocation["id"],
            current_allocation_version(api, allocation["id"]),
            name="Inherited Basis Event",
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )
        assert "accrual_method" not in promotion_payload
        promotion = validate_success(
            api.create_promotion(promotion_payload, key_account_manager), 201
        )

        assert promotion["accrual_method"] == AccrualMethod.SHIPMENT.value
        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value
        assert promotion["performance_flag"] == PerformanceFlag.UNRATED.value
        assert promotion["revision_round"] == 0
        assert promotion["approved_by_user_id"] is None


class TestReferenceDataDefaults:
    """The defaults and derived figures a brand and a customer are born with."""

    def test_customer_create_lands_four_independent_defaults(self, api, director):
        """
        Omitting the policy leaves both state axes, the penalty score and the rollups at rest.

        PRD: "**Retail customers** are likewise registered under a program with a `program_id`, a `name` of 1 to 120 characters, a `channel` of `GROCERY`, `MASS`, `CLUB` or `DOLLAR`, and optionally a `deduction_validation_policy` of `EVIDENCE_BASED` or `AGREEMENT_CAP`, defaulting to `EVIDENCE_BASED` when omitted."
        PRD: "A new customer starts with `trading_status` `ACTIVE`, `audit_status` `CLEAR`, `compliance_penalty_points` of 0 and a null `credit_hold_reason`."

        Design: Corner/entities/customer_creation_defaults_policy_and_both_state_axes
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program = setup_program(
            api, fiscal_year=2026, name="FY2026 National Trade Fund",
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )

        payload = create_customer_payload(program["id"], name="MegaMart",
                                          channel=Channel.GROCERY.value)
        payload.pop("deduction_validation_policy")

        customer = validate_success(api.create_customer(payload, director), 201)

        assert_customer(customer)
        assert customer["deduction_validation_policy"] == (
            DeductionValidationPolicy.EVIDENCE_BASED.value
        )
        assert customer["trading_status"] == TradingStatus.ACTIVE.value
        assert customer["audit_status"] == AuditStatus.CLEAR.value
        assert customer["compliance_penalty_points"] == 0
        assert customer["credit_hold_reason"] is None
        assert_money(customer["open_deduction_amount"], 0.00, "open_deduction_amount")
        assert_money(customer["write_off_ytd_amount"], 0.00, "write_off_ytd_amount")

    def test_brand_unit_margin_is_derived_not_supplied(self, api, director):
        """
        The server derives `unit_margin` from list price minus cost of goods.

        PRD: "On registration the server derives `unit_margin` as `list_price_per_case` minus `cogs_per_case`, rounded half up to 2 decimal places — the figure post-event analysis later multiplies by incremental volume to obtain gross profit."

        Design: Corner/entities/brand_unit_margin_is_computed_from_price_minus_cost
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program = setup_program(
            api, fiscal_year=2026, name="FY2026 National Trade Fund",
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )

        brand = validate_success(
            api.create_brand(
                create_brand_payload(
                    program["id"], name="Crisp Oat Cereal",
                    list_price_per_case=24.00, cogs_per_case=8.70,
                    baseline_units_per_week=1200,
                ),
                director,
            ),
            201,
        )

        assert_brand(brand)
        assert_money(brand["unit_margin"], 15.30, "unit_margin")
        assert brand["baseline_units_per_week"] == 1200
        assert brand["program_id"] == program["id"]


class TestAllocationCrossReferenceIntegrity:
    """Addressing is flat, so cross-program references are caught by rule."""

    def test_allocation_refuses_a_brand_owned_by_another_program(self, api, director):
        """
        Both ids resolve, yet the cell is refused because the brand sits in the sibling program.

        PRD: "The brand named by `brand_id` and the customer named by `customer_id` must both belong to the same program as `program_id`, or the request is refused with `ERR_BRAND_PROGRAM_MISMATCH` (HTTP 422)."
        PRD: "`allocated_amount` is the sum of `planned_amount` across every budget allocation whose `program_id` names this program, rounded half up to 2 decimal places, and it counts allocations in **both** of their approval states — `DRAFT` as well as `APPROVED` — because a budget allocation has no void or cancelled state and so an unapproved allocation still reserves envelope."

        Design: Corner/entities/allocation_needs_a_brand_from_its_own_program
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program_one = setup_program(
            api, fiscal_year=2026, name="FY2026 National Trade Fund",
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        program_two = setup_program(
            api, fiscal_year=2027, name="FY2027 National Trade Fund",
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        foreign_brand = setup_brand(
            api, program_two["id"], name="Next Year Cereal",
            list_price_per_case=24.00, cogs_per_case=8.70,
            baseline_units_per_week=1200,
        )
        customer = setup_customer(
            api, program_one["id"], name="MegaMart",
            channel=Channel.GROCERY.value,
            deduction_validation_policy=DeductionValidationPolicy.EVIDENCE_BASED.value,
        )

        response = api.create_budget_allocation(
            create_allocation_payload(
                program_one["id"], customer["id"], foreign_brand["id"],
                event_type=EventType.SEASONAL.value, planned_amount=10000.00,
                baseline_units=4000, planned_incremental_units=2000,
            ),
            director,
        )

        validate_error(response, ApiErrorId.BRAND_PROGRAM_MISMATCH.value)
        assert_money(read_program(api, program_one["id"])["allocated_amount"], 0.00,
                     "program one allocated_amount")
        assert_money(read_program(api, program_two["id"])["allocated_amount"], 0.00,
                     "program two allocated_amount")


class TestProgramBudgetRollup:
    """The two envelope figures, and the population they are summed over."""

    def test_rollup_counts_a_draft_cell_as_well_as_an_approved_one(
        self, api, director, finance_analyst
    ):
        """
        An unapproved cell still reserves envelope, so both cells are counted.

        PRD: "`allocated_amount` is the sum of `planned_amount` across every budget allocation whose `program_id` names this program, rounded half up to 2 decimal places, and it counts allocations in **both** of their approval states — `DRAFT` as well as `APPROVED` — because a budget allocation has no void or cancelled state and so an unapproved allocation still reserves envelope."
        PRD: "`unallocated_amount` is the program's `total_budget_amount` minus `allocated_amount`, rounded half up to 2 decimal places."
        PRD: "A newly created allocation has `status` `DRAFT`, `posture` `OPEN` and an `overspend_event_count` of 0, and its ledger is initialised so that `committed_amount` is 0.00, `available_amount` equals `planned_amount`, `committed_units` is 0 and `unreserved_units` equals `planned_incremental_units`; `accrued_amount`, `settled_amount` and `at_risk_amount` all start at 0.00."

        Design: Corner/calculations/program_rollup_counts_draft_and_approved_allocations_alike
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program = setup_program(
            api, fiscal_year=2026, name="FY2026 National Trade Fund",
            total_budget_amount=100000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        assert_money(program["unallocated_amount"], 100000.00,
                     "unallocated_amount at start")

        brand = setup_brand(
            api, program["id"], name="Crisp Oat Cereal",
            list_price_per_case=24.00, cogs_per_case=8.70,
            baseline_units_per_week=1200,
        )
        customer = setup_customer(
            api, program["id"], name="MegaMart", channel=Channel.GROCERY.value,
            deduction_validation_policy=DeductionValidationPolicy.EVIDENCE_BASED.value,
        )

        draft_cell = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=30000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        approved_cell = validate_success(
            api.create_budget_allocation(
                create_allocation_payload(
                    program["id"], customer["id"], brand["id"],
                    event_type=EventType.EVERYDAY.value, planned_amount=20000.00,
                    baseline_units=10000, planned_incremental_units=5000,
                ),
                finance_analyst,
            ),
            201,
        )
        approved_cell = validate_success(
            api.approve_budget_allocation(approved_cell["id"], director)
        )

        assert draft_cell["status"] == AllocationStatus.DRAFT.value
        assert approved_cell["status"] == AllocationStatus.APPROVED.value

        rolled_up = read_program(api, program["id"])
        assert_program(rolled_up)
        assert_money(rolled_up["allocated_amount"], 50000.00, "allocated_amount")
        assert_money(rolled_up["unallocated_amount"], 50000.00, "unallocated_amount")

        draft_cell = validate_success(
            api.get_budget_allocation(draft_cell["id"], director)
        )
        assert_allocation(draft_cell)
        assert_money(draft_cell["available_amount"], 30000.00,
                     "draft available_amount")
        assert draft_cell["unreserved_units"] == 20000


class TestProgramReadAndFilteredList:
    """Create, single read and the `fiscal_year` filter must agree on one row."""

    def test_create_read_and_fiscal_year_filter_agree(
        self, api, director, compliance_auditor
    ):
        """
        Two programs exist, and the fiscal-year filter returns only the one it names.

        PRD: "A newly opened program has `status` `OPEN`, an `allocated_amount` of 0.00 and an `unallocated_amount` equal to its `total_budget_amount`."
        PRD: "When `accrual_method_default` is omitted it is `SHIPMENT`."
        PRD: "Programs may be listed with optional `fiscal_year` and `status` filters."

        Design: Corner/endpoints/program_create_read_and_filtered_list
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program_2026 = validate_success(
            api.create_program(
                create_program_payload(
                    fiscal_year=2026, name="FY2026 National Trade Fund",
                    total_budget_amount=500000.00,
                    accrual_method_default=AccrualMethod.CONSUMPTION.value,
                ),
                director,
            ),
            201,
        )
        assert program_2026["status"] == ProgramStatus.OPEN.value

        payload_2025 = create_program_payload(
            fiscal_year=2025, name="FY2025 National Trade Fund",
            total_budget_amount=400000.00,
        )
        payload_2025.pop("accrual_method_default")
        program_2025 = validate_success(
            api.create_program(payload_2025, director), 201
        )
        assert program_2025["accrual_method_default"] == AccrualMethod.SHIPMENT.value

        read_back = validate_success(
            api.get_program(program_2026["id"], compliance_auditor)
        )
        assert_program(read_back)
        assert read_back["id"] == program_2026["id"]
        assert_money(read_back["total_budget_amount"], 500000.00,
                     "total_budget_amount on read")
        assert_money(read_back["allocated_amount"], 0.00, "allocated_amount")
        assert_money(read_back["unallocated_amount"], 500000.00, "unallocated_amount")

        rows, meta = validate_paginated(
            api.list_programs(compliance_auditor, {"fiscal_year": 2026})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == program_2026["id"]
        assert get_by_id(rows, program_2025["id"]) is None

        sibling = validate_success(
            api.get_program(program_2025["id"], compliance_auditor)
        )
        assert sibling["id"] == program_2025["id"]


class TestProgramEnvelopeCeiling:
    """The envelope check is marginal: it bites exactly one cent past the ceiling."""

    def _pilot_program_with_six_thousand_booked(self, api, director):
        """A 10000.00 program carrying one 6000.00 cell, plus its reference data."""
        program = setup_program(
            api, fiscal_year=2026, name="FY2026 Pilot Fund",
            total_budget_amount=10000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
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
        first_cell = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=6000.00,
            baseline_units=4000, planned_incremental_units=2000,
        )
        return program, brand, customer, first_cell

    def test_one_cent_over_the_ceiling_is_refused(self, api, director, finance_analyst):
        """
        With 6000.00 of a 10000.00 envelope booked, a 4000.01 cell is refused.

        PRD: "And the program envelope must accommodate the new cell: the program's current `allocated_amount` plus the new `planned_amount` must not exceed the program's `total_budget_amount`, or the request is refused with `ERR_PROGRAM_BUDGET_EXCEEDED` (HTTP 422)."
        PRD: "`unallocated_amount` is the program's `total_budget_amount` minus `allocated_amount`, rounded half up to 2 decimal places."

        Design: Corner/errors/program_budget_ceiling_is_enforced_on_the_marginal_cent
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer, first_cell = (
            self._pilot_program_with_six_thousand_booked(api, director)
        )

        response = api.create_budget_allocation(
            create_allocation_payload(
                program["id"], customer["id"], brand["id"],
                event_type=EventType.NEW_ITEM.value, planned_amount=4000.01,
                baseline_units=1000, planned_incremental_units=500,
            ),
            finance_analyst,
        )
        validate_error(response, ApiErrorId.PROGRAM_BUDGET_EXCEEDED.value)

        rolled_up = read_program(api, program["id"])
        assert_money(rolled_up["allocated_amount"], 6000.00, "allocated_amount")
        assert_money(rolled_up["unallocated_amount"], 4000.00, "unallocated_amount")

        rows, meta = validate_paginated(
            api.list_budget_allocations(director, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_cell["id"]]

    def test_the_exact_remaining_envelope_is_accepted(
        self, api, director, finance_analyst
    ):
        """
        The same cell at 4000.00 lands, because the sum may reach the ceiling but not exceed it.

        PRD: "And the program envelope must accommodate the new cell: the program's current `allocated_amount` plus the new `planned_amount` must not exceed the program's `total_budget_amount`, or the request is refused with `ERR_PROGRAM_BUDGET_EXCEEDED` (HTTP 422)."
        PRD: "`unallocated_amount` is the program's `total_budget_amount` minus `allocated_amount`, rounded half up to 2 decimal places."

        Design: Corner/errors/program_budget_ceiling_is_enforced_on_the_marginal_cent
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program, brand, customer, first_cell = (
            self._pilot_program_with_six_thousand_booked(api, director)
        )

        second_cell = validate_success(
            api.create_budget_allocation(
                create_allocation_payload(
                    program["id"], customer["id"], brand["id"],
                    event_type=EventType.NEW_ITEM.value, planned_amount=4000.00,
                    baseline_units=1000, planned_incremental_units=500,
                ),
                finance_analyst,
            ),
            201,
        )
        assert_allocation(second_cell)

        rolled_up = read_program(api, program["id"])
        assert_money(rolled_up["allocated_amount"], 10000.00, "allocated_amount")
        assert_money(rolled_up["unallocated_amount"], 0.00, "unallocated_amount")

        rows, meta = validate_paginated(
            api.list_budget_allocations(director, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first_cell["id"], second_cell["id"]}
