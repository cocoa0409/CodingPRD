"""
Promotion planning, tactic lines and the four-step off-invoice pricing chain.

Every precondition is built from the declared endpoints, and every figure
asserted is one the PRD pins exactly.
"""

import pytest

from test_helpers import (
    AccrualMethod,
    ApiErrorId,
    Channel,
    CoversTacticType,
    DEFAULT_CLOCK_INSTANT,
    DeductionValidationPolicy,
    DocType,
    EventType,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    PerformanceFlag,
    PromotionLifecycleStatus,
    SpendStatus,
    TacticStatus,
    TacticType,
    assert_accrual_entry,
    assert_money,
    assert_ordered_by,
    assert_promotion,
    assert_ratio,
    assert_tactic,
    assert_tactic_line_breakdown,
    create_brand_payload,
    create_customer_payload,
    create_promotion_payload,
    create_tactic_payload,
    current_allocation_version,
    instant,
    is_iso8601_timestamp,
    is_valid_uuid,
    post_accrual,
    read_allocation,
    read_promotion,
    read_tactic,
    run_activation,
    set_clock,
    setup_allocation_context,
    setup_draft_promotion,
    setup_promotion_with_lines,
    setup_promotion_with_tpr_line,
    setup_tactic,
    setup_verified_commitment_document,
    validate_error,
    validate_paginated,
    validate_success,
)

UNASSIGNED_PROMOTION_ID = "11111111-1111-4111-8111-111111111111"


def _planning_context(api, planned_amount=100000.00, planned_incremental_units=20000,
                      total_budget_amount=500000.00,
                      accrual_default=AccrualMethod.SHIPMENT.value):
    """An `APPROVED` funding cell with one brand and one customer behind it."""
    return setup_allocation_context(
        api,
        program_overrides={
            "fiscal_year": 2026,
            "name": "FY2026 National Trade Fund",
            "total_budget_amount": total_budget_amount,
            "accrual_method_default": accrual_default,
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
        planned_amount=planned_amount,
        baseline_units=40000,
        planned_incremental_units=planned_incremental_units,
    )


class TestPlannedSpendChainsTheTierLookup:
    """The band is read from the subtotal, and the total is built on top of it."""

    def test_the_chain_runs_subtotal_then_band_then_allowance_then_total(
        self, api, key_account_manager
    ):
        """
        One 8000-case line at 1.25 gives 10000.00, band 0.020, allowance 200.00, total 10200.00.

        PRD: "`line_planned_spend` is the line's own planned cost: for a `TPR` line it is `planned_units` multiplied by `rate_per_case`, rounded half up to 2 decimal places (and that rounding is load-bearing, because the rate may carry a third decimal); for a `DISPLAY` or `FEATURE` line it is simply `fixed_fee` rounded half up to 2 decimal places."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."
        PRD: "The band is chosen from the subtotal, never from `planned_total_spend`, and the evaluation order is subtotal, then band, then allowance, then total — there is no fixed point to iterate."

        Design: Difficulty/combinatorial_formula/planned_spend_chains_tier_lookup_on_its_own_subtotal
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_tpr_line(
            api, context,
            promotion_overrides={
                "name": "Chain Under Test",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )

        line = context["tactic"]
        assert_tactic(line)
        assert_money(line["line_planned_spend"], 10000.00, "line_planned_spend")

        promotion = context["promotion"]
        assert_promotion(promotion)
        assert_money(promotion["tactic_subtotal_amount"], 10000.00,
                     "tactic_subtotal_amount")
        assert_ratio(promotion["allowance_rate"], 0.020, "allowance_rate")
        assert_money(promotion["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount")
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert promotion["committed_units"] == 8000

    def test_the_band_is_never_re_read_against_the_total(self, api, key_account_manager):
        """
        Charging the allowance on the total instead of the subtotal would give 10204.00.

        PRD: "It is tempting to read the allowance as a percentage of the promotion's total spend, and trade-marketing prose often does; that reading is wrong here."
        PRD: "The band is chosen from the subtotal, never from `planned_total_spend`, and the evaluation order is subtotal, then band, then allowance, then total — there is no fixed point to iterate."

        Design: Difficulty/combinatorial_formula/planned_spend_chains_tier_lookup_on_its_own_subtotal
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_tpr_line(
            api, context,
            promotion_overrides={
                "name": "No Fixed Point",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )

        promotion = context["promotion"]
        assert_money(promotion["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount")
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert abs(float(promotion["planned_total_spend"]) - 10204.00) > 0.005, (
            "the allowance was taken on the total rather than on the subtotal"
        )

    def test_a_priced_draft_promotion_still_reserves_nothing(self, api):
        """
        The chain prices the plan, but a `DRAFT` promotion commits no money at all.

        PRD: "`planned_total_spend` is the figure that will be committed against the allocation at approval."
        PRD: "`committed_amount` is the sum of `planned_total_spend` across child promotions whose `lifecycle_status` is `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, rounded half up to 2 decimal places; promotions in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `WITHDRAWN` reserve nothing."

        Design: Difficulty/combinatorial_formula/planned_spend_chains_tier_lookup_on_its_own_subtotal
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_tpr_line(
            api, context,
            promotion_overrides={
                "name": "Priced But Unapproved",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )
        assert context["promotion"]["lifecycle_status"] == \
            PromotionLifecycleStatus.DRAFT.value
        assert_money(context["promotion"]["planned_total_spend"], 10200.00,
                     "planned_total_spend")

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["committed_amount"], 0.00, "committed_amount")
        assert_money(allocation["available_amount"], 100000.00, "available_amount")
        assert allocation["committed_units"] == 0
        assert allocation["unreserved_units"] == 20000


class TestPromotionServerMintedFields:
    """What the client may send, and what the server mints for itself."""

    def test_the_copied_and_derived_fields_come_from_the_server(
        self, api, key_account_manager
    ):
        """
        `customer_id` and `brand_id` are copied from the cell, and the plan starts empty.

        PRD: "What it must **not** carry is either `customer_id` or `brand_id`: both are copied from the funding allocation at creation, are never editable afterwards, and are rejected as unknown fields if supplied."
        PRD: "A freshly planned promotion sits in `lifecycle_status` `DRAFT` with `spend_status` `WITHIN_BUDGET`, `performance_flag` `UNRATED` and `revision_round` 0, and its `approved_by_user_id` is null."
        PRD: "When the promotion's `planned_total_spend` is 0.00, `spend_ratio` is 0.0000 and `spend_status` is `WITHIN_BUDGET`."
        PRD: "Almost every resource additionally carries `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and is incremented by exactly 1 on every mutation of that row — including mutations that are side effects of an operation aimed at a different resource."

        Design: Corner/entities/promotion_system_and_copied_fields_are_server_minted
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        allocation = context["allocation"]

        promotion = validate_success(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], allocation["version"],
                    name="Server Minted Plan",
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                ),
                key_account_manager,
            ),
            201,
        )

        assert_promotion(promotion)
        assert is_valid_uuid(promotion["id"])
        assert promotion["allocation_id"] == allocation["id"]
        assert promotion["customer_id"] == context["customer"]["id"]
        assert promotion["brand_id"] == context["brand"]["id"]
        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value
        assert promotion["performance_flag"] == PerformanceFlag.UNRATED.value
        assert promotion["revision_round"] == 0
        assert promotion["approved_by_user_id"] is None
        assert_money(promotion["tactic_subtotal_amount"], 0.00, "tactic_subtotal_amount")
        assert_ratio(promotion["allowance_rate"], 0.000, "allowance_rate")
        assert_money(promotion["off_invoice_allowance_amount"], 0.00,
                     "off_invoice_allowance_amount")
        assert_money(promotion["planned_total_spend"], 0.00, "planned_total_spend")
        assert promotion["committed_units"] == 0
        assert_ratio(promotion["spend_ratio"], 0.0000, "spend_ratio")
        assert promotion["version"] == 1
        assert is_iso8601_timestamp(promotion["created_at"])

    def test_supplying_a_copied_field_is_an_unknown_field(self, api, key_account_manager):
        """
        Sending `customer_id` on a promotion create is rejected outright.

        PRD: "What it must **not** carry is either `customer_id` or `brand_id`: both are copied from the funding allocation at creation, are never editable afterwards, and are rejected as unknown fields if supplied."
        PRD: "A monetary field in a request body must be a number that is at or above 0.00 and carries at most 2 decimal places; a rate must carry at most 3; a unit count must be an integer at or above 0; a timestamp must be an RFC 3339 UTC instant ending in `Z`; an enum field must carry one of its declared values; every required field must be present and non-null; and unknown fields are rejected outright. Any of these failures is reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/promotion_system_and_copied_fields_are_server_minted
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        allocation = context["allocation"]

        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], allocation["version"],
                    name="Illegally Explicit",
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    customer_id=context["customer"]["id"],
                ),
                key_account_manager,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )
        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], allocation["version"],
                    name="Illegally Explicit",
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    brand_id=context["brand"]["id"],
                ),
                key_account_manager,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )


class TestPromotionReadByIdentifier:
    """A read returns the stored planning row, priced across both of its lines."""

    def test_the_read_returns_the_priced_planning_row(self, api):
        """
        Two `TPR` lines add to 12000.00 before the band is read, giving a 12240.00 total.

        PRD: "**Step one:** `tactic_subtotal_amount` is the sum of `line_planned_spend` across the promotion's tactic lines whose `status` is `PLANNED`, `ACTIVE` or `COMPLETED` — each line's amount already rounded to 2 decimal places before the addition, never summed raw and rounded once at the end."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."
        PRD: "**Step four:** `planned_total_spend` is `tactic_subtotal_amount` plus `off_invoice_allowance_amount`, rounded half up to 2 decimal places, and `committed_units` is the sum of `planned_units` across the same `PLANNED`, `ACTIVE` and `COMPLETED` lines."

        Design: Corner/entities/promotion_read_by_id_returns_the_stored_planning_row
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_lines(
            api, context,
            lines=[
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_17,
                },
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 8000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_17,
                    "window_end": MONDAY_AUG_31,
                },
            ],
            promotion_overrides={
                "name": "Two Line Plan",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )

        stored = read_promotion(api, context["promotion"]["id"])

        assert_promotion(stored)
        assert stored["id"] == context["promotion"]["id"]
        assert stored["allocation_id"] == context["allocation"]["id"]
        assert stored["window_start"] == MONDAY_AUG_03
        assert stored["window_end"] == MONDAY_AUG_31
        assert stored["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value
        assert_money(stored["tactic_subtotal_amount"], 12000.00, "tactic_subtotal_amount")
        assert_ratio(stored["allowance_rate"], 0.020, "allowance_rate")
        assert_money(stored["off_invoice_allowance_amount"], 240.00,
                     "off_invoice_allowance_amount")
        assert_money(stored["planned_total_spend"], 12240.00, "planned_total_spend")
        assert stored["committed_units"] == 12000


class TestTacticListingUnderOnePromotion:
    """The lines of one promotion page in `created_at` order."""

    def test_the_first_page_holds_the_two_oldest_lines(self, api, key_account_manager):
        """
        A `limit` of 2 returns the first two lines created, and reports one row beyond.

        PRD: "Tactic lines, whether listed under one promotion or across promotions, are returned by `created_at` ascending — the same order the accrual ledger uses when it decomposes a posting into per-line amounts."
        PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/tactic_list_of_a_promotion_is_paginated_and_ordered_by_created_at
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_lines(
            api, context,
            lines=[
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_17,
                    "window_end": MONDAY_AUG_24,
                },
                {
                    "tactic_type": TacticType.DISPLAY.value,
                    "planned_units": 500,
                    "fixed_fee": 900.00,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
            ],
            promotion_overrides={
                "name": "Three Line Plan",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        created = context["tactics"]

        rows, meta = validate_paginated(
            api.list_promotion_tactics(
                context["promotion"]["id"], key_account_manager,
                {"limit": 2, "offset": 0},
            )
        )

        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert [row["id"] for row in rows] == [created[0]["id"], created[1]["id"]]
        assert_ordered_by(rows, "created_at")

    def test_the_second_page_holds_the_display_line_alone(self, api, key_account_manager):
        """
        The tail page carries the newest line, whose fee and week count are its own.

        PRD: "Tactic lines, whether listed under one promotion or across promotions, are returned by `created_at` ascending — the same order the accrual ledger uses when it decomposes a posting into per-line amounts."
        PRD: "`week_count` is the number of days between the line's `window_end` and its `window_start` divided by 7 — always a whole positive number, because both ends are Monday-aligned."
        PRD: "`line_planned_spend` is the line's own planned cost: for a `TPR` line it is `planned_units` multiplied by `rate_per_case`, rounded half up to 2 decimal places (and that rounding is load-bearing, because the rate may carry a third decimal); for a `DISPLAY` or `FEATURE` line it is simply `fixed_fee` rounded half up to 2 decimal places."

        Design: Corner/entities/tactic_list_of_a_promotion_is_paginated_and_ordered_by_created_at
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        context = setup_promotion_with_lines(
            api, context,
            lines=[
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
                {
                    "tactic_type": TacticType.TPR.value,
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_17,
                    "window_end": MONDAY_AUG_24,
                },
                {
                    "tactic_type": TacticType.DISPLAY.value,
                    "planned_units": 500,
                    "fixed_fee": 900.00,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
            ],
            promotion_overrides={
                "name": "Three Line Plan",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        created = context["tactics"]

        rows, meta = validate_paginated(
            api.list_promotion_tactics(
                context["promotion"]["id"], key_account_manager,
                {"limit": 2, "offset": 2},
            )
        )

        assert meta["total_count"] == 3
        assert meta["offset"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [created[2]["id"]]
        display_line = rows[0]
        assert_tactic(display_line)
        assert display_line["tactic_type"] == TacticType.DISPLAY.value
        assert display_line["week_count"] == 1
        assert_money(display_line["line_planned_spend"], 900.00, "line_planned_spend")
        assert display_line["status"] == TacticStatus.PLANNED.value


class TestUndeclaredAndOverPreciseFieldValues:
    """The shape gate rejects a value outside its declared domain."""

    def test_a_channel_outside_the_declared_enum_is_refused(self, api, director):
        """
        `BODEGA` is not one of the four declared channels.

        PRD: "**Retail customers** are likewise registered under a program with a `program_id`, a `name` of 1 to 120 characters, a `channel` of `GROCERY`, `MASS`, `CLUB` or `DOLLAR`, and optionally a `deduction_validation_policy` of `EVIDENCE_BASED` or `AGREEMENT_CAP`, defaulting to `EVIDENCE_BASED` when omitted."
        PRD: "A monetary field in a request body must be a number that is at or above 0.00 and carries at most 2 decimal places; a rate must carry at most 3; a unit count must be an integer at or above 0; a timestamp must be an RFC 3339 UTC instant ending in `Z`; an enum field must carry one of its declared values; every required field must be present and non-null; and unknown fields are rejected outright. Any of these failures is reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/customer_create_with_undeclared_channel_value_fails_request_shape
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        program_id = context["program"]["id"]

        validate_error(
            api.create_customer(
                create_customer_payload(program_id, name="Corner Bodega",
                                        channel="BODEGA"),
                director,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

    def test_an_over_precise_money_or_rate_value_is_refused(
        self, api, director, key_account_manager
    ):
        """
        Three decimals on money and four on a rate both fail the shape gate.

        PRD: "A monetary field in a request body must be a number that is at or above 0.00 and carries at most 2 decimal places; a rate must carry at most 3; a unit count must be an integer at or above 0; a timestamp must be an RFC 3339 UTC instant ending in `Z`; an enum field must carry one of its declared values; every required field must be present and non-null; and unknown fields are rejected outright. Any of these failures is reported as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD: "a `TPR` line — a per-case temporary price reduction — must carry `rate_per_case`, strictly positive with at most 3 decimal places, and must omit `fixed_fee`; a `DISPLAY` or `FEATURE` line — a fixed-fee placement — must carry `fixed_fee`, strictly positive with exactly 2 decimal places, and must omit `rate_per_case`."

        Design: Corner/entities/customer_create_with_undeclared_channel_value_fails_request_shape
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api)
        program_id = context["program"]["id"]

        validate_error(
            api.create_brand(
                create_brand_payload(program_id, name="Over Precise Cost",
                                     list_price_per_case=24.00, cogs_per_case=8.705,
                                     baseline_units_per_week=1200),
                director,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        context = setup_draft_promotion(
            api, context, name="Shape Gate Plan",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
        )
        validate_error(
            api.create_tactic(
                context["promotion"]["id"],
                create_tactic_payload(
                    TacticType.TPR.value, planned_units=1000, rate_per_case=1.2345,
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
                ),
                key_account_manager,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        unpriced = read_promotion(api, context["promotion"]["id"])
        assert_money(unpriced["tactic_subtotal_amount"], 0.00, "tactic_subtotal_amount")
        assert_money(unpriced["planned_total_spend"], 0.00, "planned_total_spend")


class TestTacticUnderAnUnknownPromotion:
    """A path identifier that resolves to nothing outranks every later rung."""

    def test_the_unknown_promotion_wins_over_the_money_field_mismatch(
        self, api, key_account_manager
    ):
        """
        A `TPR` body carrying `fixed_fee` under an unassigned promotion id reports not found.

        PRD: "**Rung 20** — every path identifier resolves, left to right, on every endpoint with path parameters: the not-found family of §2.7."
        PRD: "**Rung 81** — the tactic type carries the right money field, on tactic create and tactic patch: `ERR_TACTIC_TYPE_RATE_MISMATCH`."
        PRD: "A single malformed or ill-timed request commonly violates several rules at once. The response must be deterministic, so all validation rules carry an explicit precedence and **the first rule that fails determines the response; no later rule is evaluated**."

        Design: Corner/entities/tactic_create_under_an_unassigned_promotion_id_fails_existence
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        validate_error(
            api.create_tactic(
                UNASSIGNED_PROMOTION_ID,
                create_tactic_payload(
                    TacticType.TPR.value, planned_units=1000, rate_per_case=1.000,
                    fixed_fee=900.00,
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
                ),
                key_account_manager,
            ),
            ApiErrorId.PROMOTION_NOT_FOUND.value,
        )


class TestAllowanceTierBoundaries:
    """The band schedule is read at both of its declared lower bounds."""

    def _tpr_promotion(self, api, context, name, planned_units, window_start, window_end):
        """One `DRAFT` promotion carrying a single `TPR` line at a rate of 1.000."""
        context = setup_promotion_with_tpr_line(
            api, context,
            promotion_overrides={
                "name": name,
                "window_start": window_start,
                "window_end": window_end,
            },
            planned_units=planned_units,
            rate_per_case=1.000,
            window_start=window_start,
            window_end=window_end,
        )
        return context["promotion"]

    def test_the_first_boundary_admits_the_two_percent_band(self, api):
        """
        9999.00 earns no allowance while exactly 10000.00 earns 0.020.

        PRD: "**Step two:** the off-invoice `allowance_rate` is selected from a three-band schedule read against `tactic_subtotal_amount` and **nothing else** — a subtotal below ten thousand dollars earns no allowance at all, a rate of 0.000; a subtotal from ten thousand dollars up to but not including fifty thousand dollars earns 2.0 percent, a rate of 0.020; a subtotal of fifty thousand dollars or more earns 3.5 percent, a rate of 0.035."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."
        PRD: "**Step three:** `off_invoice_allowance_amount` is `tactic_subtotal_amount` multiplied by `allowance_rate`, rounded half up to 2 decimal places."

        Design: Corner/calculations/allowance_tier_is_selected_at_both_declared_boundaries
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api, planned_incremental_units=200000)

        below = self._tpr_promotion(api, context, "One Cent Below The Band",
                                    9999, MONDAY_AUG_03, MONDAY_AUG_10)
        assert_money(below["tactic_subtotal_amount"], 9999.00, "tactic_subtotal_amount")
        assert_ratio(below["allowance_rate"], 0.000, "allowance_rate")
        assert_money(below["off_invoice_allowance_amount"], 0.00,
                     "off_invoice_allowance_amount")
        assert_money(below["planned_total_spend"], 9999.00, "planned_total_spend")

        at_boundary = self._tpr_promotion(api, context, "Exactly On The Band",
                                          10000, MONDAY_AUG_10, MONDAY_AUG_17)
        assert_money(at_boundary["tactic_subtotal_amount"], 10000.00,
                     "tactic_subtotal_amount")
        assert_ratio(at_boundary["allowance_rate"], 0.020, "allowance_rate")
        assert_money(at_boundary["off_invoice_allowance_amount"], 200.00,
                     "off_invoice_allowance_amount")
        assert_money(at_boundary["planned_total_spend"], 10200.00, "planned_total_spend")

    def test_the_second_boundary_admits_the_three_and_a_half_percent_band(self, api):
        """
        49999.00 stays on 0.020 even though its total crosses fifty thousand.

        PRD: "**Step two:** the off-invoice `allowance_rate` is selected from a three-band schedule read against `tactic_subtotal_amount` and **nothing else** — a subtotal below ten thousand dollars earns no allowance at all, a rate of 0.000; a subtotal from ten thousand dollars up to but not including fifty thousand dollars earns 2.0 percent, a rate of 0.020; a subtotal of fifty thousand dollars or more earns 3.5 percent, a rate of 0.035."
        PRD: "Both band boundaries are inclusive on the lower bound, so a subtotal of exactly 10000.00 earns 0.020 and a subtotal of exactly 50000.00 earns 0.035."
        PRD: "The band is chosen from the subtotal, never from `planned_total_spend`, and the evaluation order is subtotal, then band, then allowance, then total — there is no fixed point to iterate."

        Design: Corner/calculations/allowance_tier_is_selected_at_both_declared_boundaries
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api, planned_incremental_units=200000)

        below = self._tpr_promotion(api, context, "One Dollar Below Fifty Thousand",
                                    49999, MONDAY_AUG_17, MONDAY_AUG_24)
        assert_money(below["tactic_subtotal_amount"], 49999.00, "tactic_subtotal_amount")
        assert_ratio(below["allowance_rate"], 0.020, "allowance_rate")
        assert_money(below["off_invoice_allowance_amount"], 999.98,
                     "off_invoice_allowance_amount")
        assert_money(below["planned_total_spend"], 50998.98, "planned_total_spend")

        at_boundary = self._tpr_promotion(api, context, "Exactly Fifty Thousand",
                                          50000, MONDAY_AUG_24, MONDAY_AUG_31)
        assert_money(at_boundary["tactic_subtotal_amount"], 50000.00,
                     "tactic_subtotal_amount")
        assert_ratio(at_boundary["allowance_rate"], 0.035, "allowance_rate")
        assert_money(at_boundary["off_invoice_allowance_amount"], 1750.00,
                     "off_invoice_allowance_amount")
        assert_money(at_boundary["planned_total_spend"], 51750.00, "planned_total_spend")


class TestDisplayFeeAmortisation:
    """A flat placement fee is spread evenly across the weeks it runs."""

    def test_the_weekly_component_rounds_half_up(
        self, api, director, key_account_manager, finance_analyst
    ):
        """
        A 1000.05 fee over two weeks accrues 500.03 in its first week.

        PRD: "a `DISPLAY` or `FEATURE` line contributes its `fixed_fee` divided by its own `week_count`, rounded half up to 2 decimal places, which amortises the flat placement fee evenly across the weeks the placement runs."
        PRD: "First, `fact_units` is the sum of `units` across volume facts matching the promotion's own `customer_id` and `brand_id`, carrying the `fact_type` the method selected, and whose `period_start` equals the **requested** period exactly — a single week, never a range and never aggregated across weeks."
        PRD: "Finally, `amount` is the sum of those already-rounded components, rounded half up to 2 decimal places, and `tactic_line_amounts` is stored as an ordered array of objects each pairing a `tactic_id` with that line's `amount`, in the same `created_at` ascending order."
        PRD: "`accrued_balance` is `gross_accrued_amount` minus `reversed_accrual_amount` minus `consumed_deduction_amount`, rounded to 2 decimal places, and it may legitimately be negative when a retailer has deducted more than was ever accrued."

        Design: Corner/calculations/display_fee_amortises_per_week_with_half_up_rounding
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api, accrual_default=AccrualMethod.CONSUMPTION.value)
        context = setup_promotion_with_lines(
            api, context,
            lines=[
                {
                    "tactic_type": TacticType.DISPLAY.value,
                    "planned_units": 500,
                    "fixed_fee": 1000.05,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_17,
                },
            ],
            promotion_overrides={
                "name": "Endcap Placement",
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
                "accrual_method": AccrualMethod.CONSUMPTION.value,
            },
        )
        promotion_id = context["promotion"]["id"]
        display_line = context["tactics"][0]
        assert display_line["week_count"] == 2
        assert_money(display_line["line_planned_spend"], 1000.05, "line_planned_spend")
        assert_money(context["promotion"]["planned_total_spend"], 1000.05,
                     "planned_total_spend")

        setup_verified_commitment_document(
            api, promotion_id,
            doc_type=DocType.PORTAL_ACK.value,
            covers_tactic_type=CoversTacticType.DISPLAY.value,
            received_at=instant("2026-07-30", 11),
        )
        validate_success(api.submit_promotion(promotion_id, key_account_manager))
        validate_success(api.approve_promotion(promotion_id, director))

        set_clock(api, instant(MONDAY_AUG_03))
        run_activation(api)
        assert read_promotion(api, promotion_id)["lifecycle_status"] == \
            PromotionLifecycleStatus.LIVE.value

        rows, meta = validate_paginated(api.list_volume_facts(finance_analyst))
        assert meta["total_count"] == 0

        entry = post_accrual(api, promotion_id, MONDAY_AUG_03)

        assert_accrual_entry(entry)
        assert entry["method"] == AccrualMethod.CONSUMPTION.value
        assert entry["fact_units"] == 0
        assert_money(entry["amount"], 500.03, "accrual amount")
        assert_tactic_line_breakdown(entry, [(display_line["id"], 500.03)])

        accrued = read_promotion(api, promotion_id)
        assert_money(accrued["gross_accrued_amount"], 500.03, "gross_accrued_amount")
        assert_money(accrued["accrued_balance"], 500.03, "accrued_balance")
        assert_money(accrued["planned_total_spend"], 1000.05, "planned_total_spend")
        assert_ratio(accrued["spend_ratio"], 0.5000, "spend_ratio")
        assert accrued["spend_status"] == SpendStatus.WITHIN_BUDGET.value


class TestPromotionWindowMondayAlignment:
    """A window that misses Monday is refused before any money is touched."""

    def test_a_tuesday_start_is_refused_and_the_parent_stands_still(
        self, api, key_account_manager
    ):
        """
        A Tuesday `window_start` is refused, and the funding cell is left untouched.

        PRD: "The whole system is organised on fiscal weeks that begin on Monday. Every promotion window, every tactic window, every volume-fact period and every accrual period is expressed as an ISO 8601 calendar date that must fall on a Monday, and — where the field is compared against the logical clock or stored as an instant — is interpreted as that Monday at `00:00:00Z`."
        PRD: "A date that is not a Monday, or an end that is not strictly after its start, is refused with `ERR_WINDOW_NOT_WEEK_ALIGNED` (HTTP 422)."
        PRD: "Creating it increments the funding allocation's `version` by 1 — the parent version advances on every child create, which is exactly why replaying an `expected_allocation_version` that has already been used fails."

        Design: Corner/errors/promotion_window_must_land_on_monday_boundaries
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = _planning_context(api, planned_amount=50000.00,
                                   planned_incremental_units=10000)
        allocation = context["allocation"]
        assert allocation["version"] == 2

        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], allocation["version"],
                    name="Tuesday Launch",
                    window_start="2026-08-04",
                    window_end=MONDAY_AUG_31,
                ),
                key_account_manager,
            ),
            ApiErrorId.WINDOW_NOT_WEEK_ALIGNED.value,
        )

        rows, meta = validate_paginated(
            api.list_promotions(key_account_manager, {"allocation_id": allocation["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert current_allocation_version(api, allocation["id"]) == 2
