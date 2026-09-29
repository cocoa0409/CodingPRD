"""
Trade-calendar contention: display exclusivity, feature cooldown, TPR capacity.

The three contention rules of PRD §3.4 all read the same candidate population of
`PLANNED`, `ACTIVE` and `COMPLETED` lines but differ in scope and geometry, and
they sit on different rungs of the §2.8 ladder than the window-containment rule
of §3.3. This module also covers forward-only rate maintenance.
"""

from test_helpers import (
    ApiErrorId,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    MONDAY_SEP_07,
    MONDAY_SEP_14,
    assert_money,
    assert_ratio,
    create_display_tactic_payload,
    create_feature_tactic_payload,
    create_tpr_tactic_payload,
    current_promotion_version,
    instant,
    patch_tactic_payload,
    read_promotion,
    read_tactic,
    set_clock,
    setup_allocation_context,
    setup_approved_allocation,
    setup_draft_promotion,
    setup_promotion_with_feature_line,
    setup_promotion_with_lines,
    setup_promotion_with_tpr_line,
    setup_second_customer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDisplayExclusivity:
    """Display exclusivity reads half-open windows on one customer and brand."""

    def test_adjacent_display_windows_both_survive_the_exclusivity_check(
        self, api, key_account_manager, director
    ):
        """
        Two `DISPLAY` lines that meet on one Monday do not overlap and are both accepted.

        PRD: "**Display exclusivity.** No other `DISPLAY` line on the same `customer_id` **and** the same `brand_id` may have a window that overlaps the requested window."
        PRD: "Because windows are half-open, a line ending on a given Monday and a line starting on that same Monday do not overlap, and both are allowed."
        PRD: "Second, a window that ends on the same Monday another window begins does **not** overlap it, so two such tactic lines may coexist."

        Design: Difficulty/resource_temporal_overlap/display_exclusivity_uses_half_open_windows_on_customer_and_brand
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31
        )
        promotion_id = context["promotion"]["id"]

        first = validate_success(
            api.create_tactic(
                promotion_id,
                create_display_tactic_payload(
                    planned_units=3000,
                    fixed_fee=4000.00,
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_17,
                ),
                key_account_manager,
            ),
            expected_status=201,
        )
        assert first["status"] == "PLANNED"
        assert first["week_count"] == 2
        assert_money(first["line_planned_spend"], 4000.00, "line_planned_spend")

        second = validate_success(
            api.create_tactic(
                promotion_id,
                create_display_tactic_payload(
                    planned_units=3000,
                    fixed_fee=4000.00,
                    window_start=MONDAY_AUG_17,
                    window_end=MONDAY_AUG_31,
                ),
                key_account_manager,
            ),
            expected_status=201,
        )
        assert second["week_count"] == 2

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_id, director)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

        promotion = read_promotion(api, promotion_id)
        assert_money(
            promotion["tactic_subtotal_amount"], 8000.00, "tactic_subtotal_amount"
        )
        assert_ratio(promotion["allowance_rate"], 0.000, "allowance_rate")
        assert_money(
            promotion["off_invoice_allowance_amount"],
            0.00,
            "off_invoice_allowance_amount",
        )
        assert_money(promotion["planned_total_spend"], 8000.00, "planned_total_spend")
        assert promotion["commitment_verified"] is False

    def test_straddling_display_window_is_refused_and_changes_nothing(
        self, api, key_account_manager, director
    ):
        """
        A third `DISPLAY` window that genuinely overlaps both neighbours is refused.

        PRD: "**Display exclusivity.** No other `DISPLAY` line on the same `customer_id` **and** the same `brand_id` may have a window that overlaps the requested window."
        PRD: "A genuine overlap is refused with `ERR_DISPLAY_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/display_exclusivity_uses_half_open_windows_on_customer_and_brand
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31
        )
        promotion_id = context["promotion"]["id"]
        accepted = []
        for window in ((MONDAY_AUG_03, MONDAY_AUG_17), (MONDAY_AUG_17, MONDAY_AUG_31)):
            accepted.append(
                validate_success(
                    api.create_tactic(
                        promotion_id,
                        create_display_tactic_payload(
                            planned_units=3000,
                            fixed_fee=4000.00,
                            window_start=window[0],
                            window_end=window[1],
                        ),
                        key_account_manager,
                    ),
                    expected_status=201,
                )
            )

        validate_error(
            api.create_tactic(
                promotion_id,
                create_display_tactic_payload(
                    planned_units=3000,
                    fixed_fee=4000.00,
                    window_start=MONDAY_AUG_10,
                    window_end=MONDAY_AUG_24,
                ),
                key_account_manager,
            ),
            ApiErrorId.DISPLAY_WINDOW_CONFLICT.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_id, director)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {line["id"] for line in accepted}

        promotion = read_promotion(api, promotion_id)
        assert_money(
            promotion["tactic_subtotal_amount"], 8000.00, "tactic_subtotal_amount"
        )
        assert_money(promotion["planned_total_spend"], 8000.00, "planned_total_spend")


def _brand_wide_feature_context(api):
    """
    One brand with two customers, an approved allocation each, a `FEATURE` line
    on the first customer's promotion and a second promotion ready on the other
    customer's allocation.
    """
    context = setup_allocation_context(api, planned_amount=100000.00)
    customer_b = setup_second_customer(api, context, channel="MASS")
    allocation_b = setup_approved_allocation(
        api,
        context["program"]["id"],
        customer_b["id"],
        context["brand"]["id"],
        planned_amount=100000.00,
    )
    context = setup_promotion_with_feature_line(
        api,
        context,
        promotion_overrides={
            "window_start": MONDAY_AUG_03,
            "window_end": MONDAY_AUG_17,
        },
        planned_units=5000,
        fixed_fee=6000.00,
        window_start=MONDAY_AUG_03,
        window_end=MONDAY_AUG_17,
    )
    context["feature_a"] = context.pop("tactic")
    context["promotion_a"] = context.pop("promotion")
    context = setup_draft_promotion(
        api,
        context,
        allocation_id=allocation_b["id"],
        window_start=MONDAY_AUG_17,
        window_end=MONDAY_SEP_14,
    )
    context["promotion_b"] = context.pop("promotion")
    context["customer_b"] = customer_b
    context["allocation_b"] = allocation_b
    return context


class TestFeatureCooldown:
    """Feature cooldown is a seven-day buffer on the brand, across customers."""

    def test_bare_adjacency_on_another_customer_is_still_refused(
        self, api, key_account_manager, director
    ):
        """
        A `FEATURE` window starting the Monday another brand feature ends is refused.

        PRD: "**Feature cooldown.** Feature advertising is scoped more broadly: no other `FEATURE` line on the same `brand_id` — **across all customers**, unlike the display rule — may lie within one week of the requested window."
        PRD: "A gap of exactly 7 days passes; a gap of 6 days is refused; and bare adjacency, a gap of zero days, is refused as well even though such windows do not overlap."
        PRD: "The refusal is `ERR_FEATURE_COOLDOWN_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/feature_cooldown_is_a_seven_day_buffer_on_brand_across_customers
        """
        context = _brand_wide_feature_context(api)
        promotion_b_id = context["promotion_b"]["id"]

        validate_error(
            api.create_tactic(
                promotion_b_id,
                create_feature_tactic_payload(
                    planned_units=5000,
                    fixed_fee=6000.00,
                    window_start=MONDAY_AUG_17,
                    window_end=MONDAY_AUG_31,
                ),
                key_account_manager,
            ),
            ApiErrorId.FEATURE_COOLDOWN_CONFLICT.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_b_id, director)
        )
        assert rows == []
        assert meta["total_count"] == 0

        feature_a = read_tactic(api, context["feature_a"]["id"])
        assert feature_a["status"] == "PLANNED"
        assert feature_a["window_start"] == MONDAY_AUG_03
        assert feature_a["window_end"] == MONDAY_AUG_17
        assert_money(feature_a["fixed_fee"], 6000.00, "fixed_fee")

        promotion_b = read_promotion(api, promotion_b_id)
        assert_money(
            promotion_b["tactic_subtotal_amount"], 0.00, "tactic_subtotal_amount"
        )

    def test_a_gap_of_exactly_seven_days_clears_the_cooldown(
        self, api, key_account_manager, director
    ):
        """
        A `FEATURE` window starting 7 days after the other line's end is accepted.

        PRD: "Concretely, the requested window is acceptable only if its `window_start` is at or after the other line's `window_end` plus 7 days, or its `window_end` plus 7 days is at or before the other line's `window_start`."
        PRD: "A gap of exactly 7 days passes; a gap of 6 days is refused; and bare adjacency, a gap of zero days, is refused as well even though such windows do not overlap."

        Design: Difficulty/resource_temporal_overlap/feature_cooldown_is_a_seven_day_buffer_on_brand_across_customers
        """
        context = _brand_wide_feature_context(api)
        promotion_b_id = context["promotion_b"]["id"]

        feature_b = validate_success(
            api.create_tactic(
                promotion_b_id,
                create_feature_tactic_payload(
                    planned_units=5000,
                    fixed_fee=6000.00,
                    window_start=MONDAY_AUG_24,
                    window_end=MONDAY_SEP_07,
                ),
                key_account_manager,
            ),
            expected_status=201,
        )
        assert feature_b["status"] == "PLANNED"
        assert feature_b["week_count"] == 2
        assert_money(feature_b["line_planned_spend"], 6000.00, "line_planned_spend")

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_b_id, director)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == feature_b["id"]

        promotion_b = read_promotion(api, promotion_b_id)
        assert_money(
            promotion_b["tactic_subtotal_amount"], 6000.00, "tactic_subtotal_amount"
        )
        assert_ratio(promotion_b["allowance_rate"], 0.000, "allowance_rate")
        assert_money(
            promotion_b["planned_total_spend"], 6000.00, "planned_total_spend"
        )

        feature_a = read_tactic(api, context["feature_a"]["id"])
        assert feature_a["status"] == "PLANNED"
        assert_money(feature_a["fixed_fee"], 6000.00, "fixed_fee")


class TestWindowContainmentOutranksTprCapacity:
    """Window containment sits above the TPR capacity cap on the §2.8 ladder."""

    def test_containment_failure_wins_over_the_capacity_failure(
        self, api, key_account_manager, director
    ):
        """
        A line that breaks containment and the day cap at once reports containment.

        PRD: "The response must be deterministic, so all validation rules carry an explicit precedence and **the first rule that fails determines the response; no later rule is evaluated**."
        PRD: "**Rung 71** — a tactic window is contained in its promotion's window, on tactic create and tactic patch: `ERR_TACTIC_WINDOW_OUTSIDE_PROMOTION`."
        PRD: "**Rung 80** — the per-day temporary-price-reduction concurrency cap, on tactic create and tactic patch: `ERR_TPR_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/tactic_window_temporal_outranks_tpr_capacity_constraint
        """
        context = setup_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 4000,
                    "rate_per_case": 1.250,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_31,
                },
                {
                    "tactic_type": "TPR",
                    "planned_units": 4000,
                    "rate_per_case": 0.500,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_31,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        first_line_ids = [line["id"] for line in context["tactics"]]

        context = setup_draft_promotion(
            api, context, window_start=MONDAY_AUG_10, window_end=MONDAY_AUG_24
        )
        promotion_two_id = context["promotion"]["id"]

        validate_error(
            api.create_tactic(
                promotion_two_id,
                create_tpr_tactic_payload(
                    planned_units=1000,
                    rate_per_case=0.250,
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_24,
                ),
                key_account_manager,
            ),
            ApiErrorId.TACTIC_WINDOW_OUTSIDE_PROMOTION.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_two_id, director)
        )
        assert rows == []
        assert meta["total_count"] == 0

        promotion_two = read_promotion(api, promotion_two_id)
        assert_money(
            promotion_two["tactic_subtotal_amount"], 0.00, "tactic_subtotal_amount"
        )
        assert_money(
            promotion_two["planned_total_spend"], 0.00, "planned_total_spend"
        )
        for line_id in first_line_ids:
            assert read_tactic(api, line_id)["status"] == "PLANNED"

    def test_capacity_cap_fires_once_containment_is_satisfied(
        self, api, key_account_manager, director
    ):
        """
        The same third line, kept inside its promotion window, reports the day cap.

        PRD: "**Temporary-price-reduction capacity.** On any single day, at most two `TPR` lines may cover the same `customer_id` and `brand_id`, counted across promotions rather than within one."
        PRD: "Each individual candidate line is perfectly legal on its own; only the collective count on a day fails, and a third overlapping line is refused with `ERR_TPR_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/tactic_window_temporal_outranks_tpr_capacity_constraint
        """
        context = setup_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 4000,
                    "rate_per_case": 1.250,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_31,
                },
                {
                    "tactic_type": "TPR",
                    "planned_units": 4000,
                    "rate_per_case": 0.500,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_31,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        context = setup_draft_promotion(
            api, context, window_start=MONDAY_AUG_10, window_end=MONDAY_AUG_24
        )
        promotion_two_id = context["promotion"]["id"]

        validate_error(
            api.create_tactic(
                promotion_two_id,
                create_tpr_tactic_payload(
                    planned_units=1000,
                    rate_per_case=0.250,
                    window_start=MONDAY_AUG_10,
                    window_end=MONDAY_AUG_24,
                ),
                key_account_manager,
            ),
            ApiErrorId.TPR_CAPACITY_EXCEEDED.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_two_id, director)
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestTprCapacityAcrossSiblingPromotions:
    """The day cap counts lines across promotions, not within one."""

    def test_tpr_concurrency_cap_counts_lines_across_sibling_promotions(
        self, api, key_account_manager, director
    ):
        """
        Two sibling promotions already cover the week, so a third line is refused.

        PRD: "**Temporary-price-reduction capacity.** On any single day, at most two `TPR` lines may cover the same `customer_id` and `brand_id`, counted across promotions rather than within one."
        PRD: "Each individual candidate line is perfectly legal on its own; only the collective count on a day fails, and a third overlapping line is refused with `ERR_TPR_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/tpr_concurrency_cap_counts_lines_across_sibling_promotions
        """
        context = setup_allocation_context(
            api, planned_amount=90000.00, planned_incremental_units=30000
        )
        context = setup_promotion_with_tpr_line(
            api,
            context,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
            },
            planned_units=4000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_17,
        )
        promotion_one_id = context["promotion"]["id"]
        tactic_one_id = context["tactic"]["id"]

        context = setup_promotion_with_tpr_line(
            api,
            context,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_10,
            },
            planned_units=3000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )
        tactic_two_id = context["tactic"]["id"]

        validate_error(
            api.create_tactic(
                promotion_one_id,
                create_tpr_tactic_payload(
                    planned_units=1000,
                    rate_per_case=0.500,
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_10,
                ),
                key_account_manager,
            ),
            ApiErrorId.TPR_CAPACITY_EXCEEDED.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_one_id, director)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == tactic_one_id
        assert read_tactic(api, tactic_two_id)["status"] == "PLANNED"

        promotion_one = read_promotion(api, promotion_one_id)
        assert_money(
            promotion_one["tactic_subtotal_amount"], 4000.00, "tactic_subtotal_amount"
        )
        assert promotion_one["committed_units"] == 4000


class TestForwardOnlyRateMaintenance:
    """Rate maintenance is accepted only for a week that has not begun."""

    def test_rate_maintenance_is_accepted_only_for_a_future_week(
        self, api, key_account_manager
    ):
        """
        The same repricing is refused on the running week and accepted on the next one.

        PRD: "On top of those, rate maintenance is **forward-only**: a patch that changes either `rate_per_case` or `fixed_fee` is accepted only when the line's `window_start` is strictly after the current logical clock instant, so a rate can never be revised for a week that has already begun."
        PRD: "A patch that attempts it is refused with `ERR_RATE_CHANGE_NOT_FUTURE` (HTTP 422)."
        PRD: "When a rate or fee did change, the server stamps `effective_from_period` with the line's `window_start` — the Monday of the first period the new rate applies to — which stays null on a line that has never been repriced."

        Design: Corner/validations/rate_maintenance_is_accepted_only_for_a_future_week
        """
        context = setup_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 2000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
                {
                    "tactic_type": "TPR",
                    "planned_units": 2000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_10,
                    "window_end": MONDAY_AUG_17,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
            },
        )
        promotion_id = context["promotion"]["id"]
        started_id = context["tactics"][0]["id"]
        future_id = context["tactics"][1]["id"]

        set_clock(api, instant(MONDAY_AUG_03))
        promotion_version = current_promotion_version(api, promotion_id)

        validate_error(
            api.patch_tactic(
                started_id,
                patch_tactic_payload(promotion_version, rate_per_case=1.500),
                key_account_manager,
            ),
            ApiErrorId.RATE_CHANGE_NOT_FUTURE.value,
        )
        started_line = read_tactic(api, started_id)
        assert_ratio(started_line["rate_per_case"], 1.000, "rate_per_case")
        assert started_line["effective_from_period"] is None

        patched = validate_success(
            api.patch_tactic(
                future_id,
                patch_tactic_payload(promotion_version, rate_per_case=1.500),
                key_account_manager,
            )
        )
        assert_ratio(patched["rate_per_case"], 1.500, "rate_per_case")
        assert patched["effective_from_period"] == MONDAY_AUG_10
        assert_money(patched["line_planned_spend"], 3000.00, "line_planned_spend")

        promotion = read_promotion(api, promotion_id)
        assert_money(
            promotion["tactic_subtotal_amount"], 5000.00, "tactic_subtotal_amount"
        )
        assert_ratio(promotion["allowance_rate"], 0.000, "allowance_rate")
        assert_money(promotion["planned_total_spend"], 5000.00, "planned_total_spend")
