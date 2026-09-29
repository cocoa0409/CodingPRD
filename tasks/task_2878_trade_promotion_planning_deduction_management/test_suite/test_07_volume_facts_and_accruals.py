"""
Volume facts and the weekly accrual ledger.

Covers the append-only volume journal and its four-part grain, the two accrual
bases and the 14-day shipment lead shift, the per-line round-then-sum assembly
of an accrual amount, the compensating reversal and the dollar identity it
restores, and the ledger figures the promotion and its allocation must show on
the read immediately after a posting.
"""

from typing import Any, Dict, Tuple

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    KAM_HEADERS,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    AccrualEntryStatus,
    AccrualMethod,
    ApiErrorId,
    Channel,
    DeductionValidationPolicy,
    EntryType,
    EventType,
    FactSource,
    FactType,
    SpendStatus,
    assert_accrual_entry,
    assert_append_only_fields,
    assert_field_absent,
    assert_money,
    assert_ratio,
    assert_tactic_line_breakdown,
    assert_volume_fact,
    create_accrual_payload,
    create_promotion_payload,
    create_tpr_tactic_payload,
    create_volume_fact_payload,
    current_allocation_version,
    instant,
    read_accrual,
    read_allocation,
    read_promotion,
    reverse_accrual_payload,
    run_activation,
    set_clock,
    setup_approved_allocation,
    setup_brand,
    setup_customer,
    setup_program,
    setup_volume_fact,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Local builders (the frozen fixtures are used where they fit) ─────────────

def _reference_data(api, *, budget: float, accrual_default: str,
                    brand: Dict[str, Any] = None,
                    customer: Dict[str, Any] = None) -> Tuple[dict, dict, dict]:
    """A program with one brand and one customer, all figures pinned."""
    program = setup_program(api, total_budget_amount=budget,
                            accrual_method_default=accrual_default)
    brand_fields = {
        "name": "Crisp Oat Cereal",
        "list_price_per_case": 24.00,
        "cogs_per_case": 8.70,
        "baseline_units_per_week": 1200,
    }
    brand_fields.update(brand or {})
    customer_fields = {
        "name": "MegaMart",
        "channel": Channel.GROCERY.value,
        "deduction_validation_policy": DeductionValidationPolicy.EVIDENCE_BASED.value,
    }
    customer_fields.update(customer or {})
    brand_row = setup_brand(api, program["id"], **brand_fields)
    customer_row = setup_customer(api, program["id"], **customer_fields)
    return program, brand_row, customer_row


def _plan_promotion(api, allocation_id: str, *, name: str, window_start: str,
                    window_end: str, accrual_method: str) -> Dict[str, Any]:
    """A `DRAFT` promotion planned against the allocation's live version."""
    expected_version = current_allocation_version(api, allocation_id)
    return validate_success(
        api.create_promotion(
            create_promotion_payload(
                allocation_id, expected_version, name=name,
                window_start=window_start, window_end=window_end,
                accrual_method=accrual_method,
            ),
            KAM_HEADERS,
        ),
        expected_status=201,
    )


def _add_tpr_line(api, promotion_id: str, *, planned_units: int, rate_per_case: float,
                  window_start: str, window_end: str) -> Dict[str, Any]:
    """One `TPR` line on a `DRAFT` promotion."""
    return validate_success(
        api.create_tactic(
            promotion_id,
            create_tpr_tactic_payload(
                planned_units=planned_units, rate_per_case=rate_per_case,
                window_start=window_start, window_end=window_end,
            ),
            KAM_HEADERS,
        ),
        expected_status=201,
    )


def _submit_and_approve(api, promotion_id: str) -> Dict[str, Any]:
    """Take a `DRAFT` promotion to `APPROVED`."""
    validate_success(api.submit_promotion(promotion_id, KAM_HEADERS))
    return validate_success(api.approve_promotion(promotion_id, DIRECTOR_HEADERS))


def _post_accrual(api, promotion_id: str, period_start: str) -> Dict[str, Any]:
    """Post one week of accrual and return the created entry."""
    return validate_success(
        api.create_accrual(promotion_id, create_accrual_payload(period_start),
                           ANALYST_HEADERS),
        expected_status=201,
    )


def _single_tpr_promotion_fixture(api, *, accrual_default: str, promotion_name: str,
                                  accrual_method: str, window_start: str,
                                  window_end: str, planned_units: int,
                                  rate_per_case: float,
                                  tactic_window_end: str = None,
                                  budget: float = 500000.00,
                                  planned_amount: float = 50000.00,
                                  baseline_units: int = 20000,
                                  planned_incremental_units: int = 10000,
                                  event_type: str = None) -> Dict[str, Any]:
    """An `APPROVED` promotion carrying exactly one `TPR` line, plus its parents."""
    program, brand, customer = _reference_data(
        api, budget=budget, accrual_default=accrual_default
    )
    allocation = setup_approved_allocation(
        api, program["id"], customer["id"], brand["id"],
        event_type=event_type or EventType.SEASONAL.value,
        planned_amount=planned_amount, baseline_units=baseline_units,
        planned_incremental_units=planned_incremental_units,
    )
    promotion = _plan_promotion(
        api, allocation["id"], name=promotion_name, window_start=window_start,
        window_end=window_end, accrual_method=accrual_method,
    )
    tactic = _add_tpr_line(
        api, promotion["id"], planned_units=planned_units, rate_per_case=rate_per_case,
        window_start=window_start, window_end=tactic_window_end or window_end,
    )
    promotion = _submit_and_approve(api, promotion["id"])
    return {
        "program": program,
        "brand": brand,
        "customer": customer,
        "allocation": read_allocation(api, allocation["id"]),
        "promotion": promotion,
        "tactic": tactic,
    }


class TestAccrualBasisDivergence:
    """The accrual basis decides which journal is read and which week is tested."""

    @staticmethod
    def _fixture(api) -> Dict[str, Any]:
        set_clock(api, instant(MONDAY_AUG_03))
        program, brand, customer = _reference_data(
            api, budget=5000000.00, accrual_default=AccrualMethod.SHIPMENT.value
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        shipment_promotion = _plan_promotion(
            api, allocation["id"], name="Shipment Basis Event",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.SHIPMENT.value,
        )
        consumption_promotion = _plan_promotion(
            api, allocation["id"], name="Consumption Basis Event",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        for promotion in (shipment_promotion, consumption_promotion):
            _add_tpr_line(
                api, promotion["id"], planned_units=8000, rate_per_case=1.25,
                window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            )
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.SHIPMENT.value,
            period_start=MONDAY_AUG_03, units=2000, source=FactSource.EDI_856.value,
        )
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=1600, source=FactSource.EDI_852.value,
        )
        _submit_and_approve(api, shipment_promotion["id"])
        _submit_and_approve(api, consumption_promotion["id"])
        run_activation(api)
        return {
            "allocation": allocation,
            "shipment_promotion": shipment_promotion,
            "consumption_promotion": consumption_promotion,
        }

    def test_shipment_basis_reads_the_shipment_journal_and_shifts_the_week(self, api):
        """
        The shipment basis accrues the 2000-case shipment fact and tests the window 14 days on.

        PRD: "On the `SHIPMENT` basis the effective period is the requested `period_start` shifted forward by 14 days, and the facts read are those with `fact_type` `SHIPMENT`; the week that funds promoted sell-through is the week the goods left the plant, a fortnight before the consumer saw the price."
        PRD: "First, `fact_units` is the sum of `units` across volume facts matching the promotion's own `customer_id` and `brand_id`, carrying the `fact_type` the method selected, and whose `period_start` equals the **requested** period exactly — a single week, never a range and never aggregated across weeks."

        Design: Difficulty/dual_variant_calc/accrual_shipment_basis_vs_consumption_basis_diverge
        """
        context = self._fixture(api)
        promotion_id = context["shipment_promotion"]["id"]

        entry = _post_accrual(api, promotion_id, MONDAY_AUG_03)

        assert_accrual_entry(entry)
        assert entry["method"] == AccrualMethod.SHIPMENT.value
        assert entry["fact_units"] == 2000
        assert_money(entry["amount"], 2500.00, "amount")
        assert entry["period_start"] == MONDAY_AUG_03

        promotion = read_promotion(api, promotion_id)
        assert_money(promotion["gross_accrued_amount"], 2500.00, "gross_accrued_amount")
        assert_money(promotion["accrued_balance"], 2500.00, "accrued_balance")

    def test_consumption_basis_reads_the_point_of_sale_journal_without_a_shift(self, api):
        """
        The consumption basis accrues the 1600-case point-of-sale fact in the requested week.

        PRD: "On the `CONSUMPTION` basis the effective period is the requested `period_start` itself with no shift, and the facts read are those with `fact_type` `CONSUMPTION`."
        PRD: "Third, each line yields its own rounded component: a `TPR` line contributes `fact_units` multiplied by that line's `rate_per_case`, rounded half up to 2 decimal places; a `DISPLAY` or `FEATURE` line contributes its `fixed_fee` divided by its own `week_count`, rounded half up to 2 decimal places, which amortises the flat placement fee evenly across the weeks the placement runs."

        Design: Difficulty/dual_variant_calc/accrual_shipment_basis_vs_consumption_basis_diverge
        """
        context = self._fixture(api)
        promotion_id = context["consumption_promotion"]["id"]

        entry = _post_accrual(api, promotion_id, MONDAY_AUG_03)

        assert_accrual_entry(entry)
        assert entry["method"] == AccrualMethod.CONSUMPTION.value
        assert entry["fact_units"] == 1600
        assert_money(entry["amount"], 2000.00, "amount")
        assert entry["period_start"] == MONDAY_AUG_03

        promotion = read_promotion(api, promotion_id)
        assert_money(promotion["gross_accrued_amount"], 2000.00, "gross_accrued_amount")
        assert_money(promotion["accrued_balance"], 2000.00, "accrued_balance")

    def test_identical_requests_diverge_by_exactly_the_accrual_method(self, api):
        """
        Byte-identical fact data and payloads accrue 2500.00 against 2000.00.

        PRD: "For byte-identical fact data the two bases therefore accrue different amounts in different weeks, and a given promotion is only ever on one basis."
        PRD: "Which week the money belongs to, and which facts pay for it, is the promotion's `accrual_method` — and the two bases behave differently in both respects."

        Design: Difficulty/dual_variant_calc/accrual_shipment_basis_vs_consumption_basis_diverge
        """
        context = self._fixture(api)

        shipment_entry = _post_accrual(
            api, context["shipment_promotion"]["id"], MONDAY_AUG_03
        )
        consumption_entry = _post_accrual(
            api, context["consumption_promotion"]["id"], MONDAY_AUG_03
        )

        assert shipment_entry["period_start"] == consumption_entry["period_start"]
        assert_money(shipment_entry["amount"], 2500.00, "shipment amount")
        assert_money(consumption_entry["amount"], 2000.00, "consumption amount")
        assert_money(
            round(float(shipment_entry["amount"]) - float(consumption_entry["amount"]), 2),
            500.00,
            "basis delta",
        )

        shipment_promotion = read_promotion(api, context["shipment_promotion"]["id"])
        consumption_promotion = read_promotion(api, context["consumption_promotion"]["id"])
        assert_money(shipment_promotion["gross_accrued_amount"], 2500.00, "gross S")
        assert_money(consumption_promotion["gross_accrued_amount"], 2000.00, "gross C")


class TestAccrualPerLineRounding:
    """Each tactic component is rounded to the cent before the components are added."""

    @staticmethod
    def _fixture(api) -> Dict[str, Any]:
        set_clock(api, instant(MONDAY_AUG_03))
        program, brand, customer = _reference_data(
            api, budget=5000000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.EVERYDAY.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        promotion = _plan_promotion(
            api, allocation["id"], name="Split Rate Everyday TPR",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        first_line = _add_tpr_line(
            api, promotion["id"], planned_units=8000, rate_per_case=0.375,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
        )
        second_line = _add_tpr_line(
            api, promotion["id"], planned_units=8000, rate_per_case=0.125,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
        )
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=333, source=FactSource.EDI_852.value,
        )
        _submit_and_approve(api, promotion["id"])
        run_activation(api)
        return {
            "allocation": allocation,
            "promotion": promotion,
            "first_line": first_line,
            "second_line": second_line,
        }

    def test_each_line_is_rounded_to_its_own_cent_before_the_sum(self, api):
        """
        333 cases at 0.375 and at 0.125 give components of 124.88 and 41.63 in line order.

        PRD: "Whenever a total is assembled from several component lines, **each line is rounded to 2 decimal places first and the rounded line amounts are then added**."
        PRD: "Finally, `amount` is the sum of those already-rounded components, rounded half up to 2 decimal places, and `tactic_line_amounts` is stored as an ordered array of objects each pairing a `tactic_id` with that line's `amount`, in the same `created_at` ascending order."

        Design: Difficulty/combinatorial_formula/accrual_rounds_each_tactic_line_before_summing
        """
        context = self._fixture(api)

        entry = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)

        assert_accrual_entry(entry)
        assert entry["fact_units"] == 333
        assert_tactic_line_breakdown(entry, [
            (context["first_line"]["id"], 124.88),
            (context["second_line"]["id"], 41.63),
        ])
        assert_money(entry["amount"], 166.51, "amount")

    def test_entry_amount_is_not_the_sum_then_round_result(self, api):
        """
        The rounded-line total 166.51 is a cent above the 166.50 an aggregate-then-round order gives.

        PRD: "Summing unrounded products and rounding once at the end is a different — and incorrect — result."
        PRD: "This pinned order governs the assembly of a promotion's tactic subtotal from its individual tactic lines, and the assembly of a weekly accrual amount from its per-tactic components."

        Design: Difficulty/combinatorial_formula/accrual_rounds_each_tactic_line_before_summing
        """
        context = self._fixture(api)

        entry = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)

        amount = round(float(entry["amount"]), 2)
        assert amount == 166.51, f"expected the per-line rounded total, got {amount}"
        assert amount != 166.50, "the sum-then-round order is excluded"
        components = [round(float(line["amount"]), 2)
                      for line in entry["tactic_line_amounts"]]
        assert round(sum(components), 2) == pytest.approx(166.51, abs=0.001)

    def test_promotion_ledger_carries_the_per_line_rounded_total(self, api):
        """
        The promotion and its allocation both show the 166.51 assembled from rounded lines.

        PRD: "`gross_accrued_amount` is the sum of `amount` over the promotion's entries whose `entry_type` is `ACCRUAL`, **regardless of their status** — a reversed accrual stays in the gross figure and is offset by its twin — rounded to 2 decimal places."
        PRD: "`accrued_amount` is the sum, across **all** child promotions regardless of lifecycle, of each promotion's `gross_accrued_amount` minus its `reversed_accrual_amount`, rounded to 2 decimal places."

        Design: Difficulty/combinatorial_formula/accrual_rounds_each_tactic_line_before_summing
        """
        context = self._fixture(api)

        _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 166.51, "gross_accrued_amount")
        assert_money(promotion["accrued_balance"], 166.51, "accrued_balance")

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["accrued_amount"], 166.51, "accrued_amount")


class TestAccrualReversalIdentity:
    """A reversal is a compensating write, so accrual dollars are conserved."""

    REVERSAL_REASON = "Point-of-sale week restated by the retailer"

    @staticmethod
    def _fixture(api) -> Dict[str, Any]:
        set_clock(api, instant(MONDAY_AUG_03))
        program, brand, customer = _reference_data(
            api, budget=5000000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        promotion = _plan_promotion(
            api, allocation["id"], name="Reversible Accrual Event",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        _add_tpr_line(
            api, promotion["id"], planned_units=2000, rate_per_case=1.25,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
        )
        _submit_and_approve(api, promotion["id"])
        run_activation(api)
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=2000, source=FactSource.EDI_852.value,
        )
        accrual = _post_accrual(api, promotion["id"], MONDAY_AUG_03)
        return {
            "allocation": allocation,
            "promotion": promotion,
            "accrual": accrual,
        }

    def test_posted_accrual_puts_the_promotion_at_the_inclusive_ratio_boundary(self, api):
        """
        A 2500.00 accrual against a 2500.00 plan is a warning, not an overspend.

        PRD: "Otherwise `spend_ratio` is `recognized_spend_amount` divided by `planned_total_spend`, rounded half up to 4 decimal places, and `spend_status` follows exact boundaries: a ratio strictly greater than 1.0000 is `OVERSPENT`; a ratio at or above 0.9000 but not exceeding 1.0000 is `OVERSPEND_WARNING`; anything below 0.9000 is `WITHIN_BUDGET`."
        PRD: "A ratio of exactly 0.9000 is therefore `OVERSPEND_WARNING`, a ratio of exactly 1.0000 is still `OVERSPEND_WARNING`, and a ratio of 1.0001 is `OVERSPENT`."

        Design: Difficulty/compensating_invariant/accrual_reversal_restores_the_accrual_dollar_identity
        """
        context = self._fixture(api)

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 2500.00, "gross_accrued_amount")
        assert_money(promotion["reversed_accrual_amount"], 0.00, "reversed_accrual_amount")
        assert_money(promotion["accrued_balance"], 2500.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 2500.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 1.0000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.OVERSPEND_WARNING.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["accrued_amount"], 2500.00, "accrued_amount")

    def test_reversal_preserves_the_original_and_returns_the_mirror_entry(self, api):
        """
        The reversed original stays readable at its amount while the mirror entry comes back.

        PRD: "The original entry's `status` moves `POSTED` → `REVERSED`, and a second entry is created carrying `entry_type` `REVERSAL`, `status` `POSTED`, an `amount` equal to the reversed entry's `amount`, a `reverses_entry_id` naming the reversed entry, a `fact_units` of 0 and an empty `tactic_line_amounts` array — and it is that new mirror entry, not the reversed original, that comes back as the response body."
        PRD: "Accrual entries may be listed with optional `promotion_id`, `reverses_entry_id`, `entry_type` and `status` filters — the second of which is the reverse lookup from an original to its compensating twin."

        Design: Difficulty/compensating_invariant/accrual_reversal_restores_the_accrual_dollar_identity
        """
        context = self._fixture(api)
        accrual_id = context["accrual"]["id"]

        mirror = validate_success(
            api.reverse_accrual(
                accrual_id,
                reverse_accrual_payload(2500.00, reversal_reason=self.REVERSAL_REASON),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert_accrual_entry(mirror)
        assert mirror["entry_type"] == EntryType.REVERSAL.value
        assert mirror["status"] == AccrualEntryStatus.POSTED.value
        assert_money(mirror["amount"], 2500.00, "mirror amount")
        assert mirror["reverses_entry_id"] == accrual_id
        assert mirror["fact_units"] == 0
        assert mirror["tactic_line_amounts"] == []
        assert mirror["id"] != accrual_id

        original = read_accrual(api, accrual_id)
        assert original["status"] == AccrualEntryStatus.REVERSED.value
        assert original["entry_type"] == EntryType.ACCRUAL.value
        assert_money(original["amount"], 2500.00, "original amount")

        rows, meta = validate_paginated(
            api.list_accruals(ANALYST_HEADERS,
                              params={"promotion_id": context["promotion"]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {accrual_id, mirror["id"]}

    def test_reversal_restores_the_accrual_dollar_identity(self, api):
        """
        Gross stays at 2500.00, reversed rises to 2500.00 and the balance returns to 0.00.

        PRD: "The **accrual identity** on a promotion: `gross_accrued_amount` always equals `reversed_accrual_amount` plus `consumed_deduction_amount` plus `accrued_balance`."
        PRD: "`accrued_balance` is `gross_accrued_amount` minus `reversed_accrual_amount` minus `consumed_deduction_amount`, rounded to 2 decimal places, and it may legitimately be negative when a retailer has deducted more than was ever accrued."

        Design: Difficulty/compensating_invariant/accrual_reversal_restores_the_accrual_dollar_identity
        """
        context = self._fixture(api)

        validate_success(
            api.reverse_accrual(
                context["accrual"]["id"],
                reverse_accrual_payload(2500.00, reversal_reason=self.REVERSAL_REASON),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 2500.00, "gross_accrued_amount")
        assert_money(promotion["reversed_accrual_amount"], 2500.00, "reversed_accrual_amount")
        assert_money(promotion["consumed_deduction_amount"], 0.00, "consumed_deduction_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")
        assert_money(
            round(
                float(promotion["reversed_accrual_amount"])
                + float(promotion["consumed_deduction_amount"])
                + float(promotion["accrued_balance"]),
                2,
            ),
            float(promotion["gross_accrued_amount"]),
            "accrual identity",
        )
        assert_money(promotion["recognized_spend_amount"], 0.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.0000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["accrued_amount"], 0.00, "accrued_amount")
        assert_money(allocation["committed_amount"], 2500.00, "committed_amount")
        assert_money(allocation["available_amount"], 97500.00, "available_amount")


class TestVolumeFactAppendOnly:
    """The volume journal has no writer beyond create."""

    def test_volume_fact_is_append_only_with_no_version_and_no_writer_beyond_create(self, api):
        """
        A fact row carries only `id` and `created_at`, and a correction is a second row.

        PRD: "`VolumeFact` is the single exception. Weekly shipment and consumption facts are an append-only journal: a fact row carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it. There is no update and no delete for a fact; a correction is posted as an additional fact row, never as an edit of an existing one."
        PRD: "Recording a fact recomputes nothing: accruals read facts when a period is posted, and post-event analysis reads them when it runs."

        Design: Corner/entities/volume_fact_is_append_only_with_no_version_and_no_writer_beyond_create
        """
        program, brand, customer = _reference_data(
            api, budget=500000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )

        first_fact = setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=2500, source=FactSource.EDI_852.value,
        )
        second_fact = setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_10, units=2300, source=FactSource.MANUAL.value,
        )

        assert_volume_fact(first_fact)
        assert first_fact["id"]
        assert first_fact["created_at"]
        assert_append_only_fields(first_fact)
        assert_field_absent(first_fact, "version")
        assert_field_absent(first_fact, "updated_at")

        stored = validate_success(api.get_volume_fact(first_fact["id"], ANALYST_HEADERS))
        assert stored["units"] == 2500
        assert stored["source"] == FactSource.EDI_852.value
        assert stored["period_start"] == MONDAY_AUG_03
        assert_append_only_fields(stored)

        assert second_fact["units"] == 2300
        assert second_fact["source"] == FactSource.MANUAL.value
        assert second_fact["period_start"] == MONDAY_AUG_10
        assert second_fact["id"] != first_fact["id"]

        unchanged = validate_success(api.get_volume_fact(first_fact["id"], ANALYST_HEADERS))
        assert unchanged["units"] == 2500
        assert unchanged["created_at"] == stored["created_at"]


class TestAccrualLedgerReconciliation:
    """A posting moves the accrual figures and leaves the commitment figures alone."""

    def test_accrual_posting_reconciles_the_allocation_ledger(self, api):
        """
        A 1500.00 posting is visible on the promotion and rolls into the allocation.

        PRD: "`gross_accrued_amount` is the sum of `amount` over the promotion's entries whose `entry_type` is `ACCRUAL`, **regardless of their status** — a reversed accrual stays in the gross figure and is offset by its twin — rounded to 2 decimal places."
        PRD: "`accrued_amount` is the sum, across **all** child promotions regardless of lifecycle, of each promotion's `gross_accrued_amount` minus its `reversed_accrual_amount`, rounded to 2 decimal places."
        PRD: "From those, `available_amount` is `planned_amount` minus `committed_amount`, rounded to 2 decimal places, and `unreserved_units` is `planned_incremental_units` minus `committed_units`."

        Design: Corner/state_machines/accrual_posting_reconciles_the_allocation_ledger
        """
        context = _single_tpr_promotion_fixture(
            api, accrual_default=AccrualMethod.CONSUMPTION.value,
            promotion_name="August Cereal Event",
            accrual_method=AccrualMethod.CONSUMPTION.value,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            planned_units=2000, rate_per_case=1.000,
            tactic_window_end=MONDAY_AUG_10,
            budget=500000.00, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        before = context["allocation"]
        assert_money(before["committed_amount"], 2000.00, "committed_amount")
        assert_money(before["available_amount"], 98000.00, "available_amount")
        assert_money(before["accrued_amount"], 0.00, "accrued_amount")

        set_clock(api, instant(MONDAY_AUG_03))
        run_activation(api)
        setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
            units=1500, source=FactSource.EDI_852.value,
        )

        entry = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)

        assert_accrual_entry(entry)
        assert entry["entry_type"] == EntryType.ACCRUAL.value
        assert entry["status"] == AccrualEntryStatus.POSTED.value
        assert_money(entry["amount"], 1500.00, "amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 1500.00, "gross_accrued_amount")
        assert_money(promotion["reversed_accrual_amount"], 0.00, "reversed_accrual_amount")
        assert_money(promotion["accrued_balance"], 1500.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 1500.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.7500, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["accrued_amount"], 1500.00, "accrued_amount")
        assert_money(allocation["committed_amount"], 2000.00, "committed_amount")
        assert_money(allocation["available_amount"], 98000.00, "available_amount")
        assert_money(allocation["settled_amount"], 0.00, "settled_amount")
        assert allocation["committed_units"] == 2000
        assert allocation["unreserved_units"] == 18000


class TestAccrualInputSetFiltering:
    """The fact set an accrual reads is narrowed on week, type, customer and brand."""

    def test_accrual_reads_only_the_exact_week_the_type_and_the_brand(self, api):
        """
        Only the promoted brand's `CONSUMPTION` fact for the requested week pays the accrual.

        PRD: "First, `fact_units` is the sum of `units` across volume facts matching the promotion's own `customer_id` and `brand_id`, carrying the `fact_type` the method selected, and whose `period_start` equals the **requested** period exactly — a single week, never a range and never aggregated across weeks."
        PRD: "On the `CONSUMPTION` basis the effective period is the requested `period_start` itself with no shift, and the facts read are those with `fact_type` `CONSUMPTION`."

        Design: Corner/calculations/accrual_reads_only_the_exact_week_the_type_and_the_brand
        """
        program, brand_a, customer = _reference_data(
            api, budget=500000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        brand_b = setup_brand(
            api, program["id"], name="Honey Nut Clusters",
            list_price_per_case=26.00, cogs_per_case=9.40,
            baseline_units_per_week=800,
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand_a["id"],
            event_type=EventType.SEASONAL.value, planned_amount=50000.00,
            baseline_units=20000, planned_incremental_units=10000,
        )
        promotion = _plan_promotion(
            api, allocation["id"], name="Cereal Scan Event",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        _add_tpr_line(
            api, promotion["id"], planned_units=5000, rate_per_case=1.000,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
        )
        _submit_and_approve(api, promotion["id"])
        set_clock(api, instant(MONDAY_AUG_03))
        run_activation(api)

        setup_volume_fact(
            api, customer["id"], brand_a["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=1000, source=FactSource.EDI_852.value,
        )
        setup_volume_fact(
            api, customer["id"], brand_a["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_10, units=5000, source=FactSource.EDI_852.value,
        )
        setup_volume_fact(
            api, customer["id"], brand_a["id"], fact_type=FactType.SHIPMENT.value,
            period_start=MONDAY_AUG_03, units=7000, source=FactSource.EDI_856.value,
        )
        setup_volume_fact(
            api, customer["id"], brand_b["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=9000, source=FactSource.EDI_852.value,
        )

        entry = _post_accrual(api, promotion["id"], MONDAY_AUG_03)

        assert entry["fact_units"] == 1000
        assert_money(entry["amount"], 1000.00, "amount")
        assert entry["period_start"] == MONDAY_AUG_03

        rows, meta = validate_paginated(
            api.list_volume_facts(
                ANALYST_HEADERS,
                params={"customer_id": customer["id"], "brand_id": brand_a["id"]},
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

        promotion_after = read_promotion(api, promotion["id"])
        assert_money(promotion_after["gross_accrued_amount"], 1000.00, "gross_accrued_amount")
        assert_money(promotion_after["accrued_balance"], 1000.00, "accrued_balance")


def _scan_accrual_fixture(api, *, promotion_name: str) -> Dict[str, Any]:
    """A `LIVE` `CONSUMPTION` promotion whose 2026-08-03 week is accrued at 1000.00."""
    context = _single_tpr_promotion_fixture(
        api, accrual_default=AccrualMethod.CONSUMPTION.value,
        promotion_name=promotion_name,
        accrual_method=AccrualMethod.CONSUMPTION.value,
        window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
        planned_units=5000, rate_per_case=1.000,
    )
    set_clock(api, instant(MONDAY_AUG_03))
    run_activation(api)
    setup_volume_fact(
        api, context["customer"]["id"], context["brand"]["id"],
        fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
        units=1000, source=FactSource.EDI_852.value,
    )
    context["accrual"] = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)
    return context


class TestVolumeFactGrainUniqueness:
    """The journal's grain is the four-part key, and only that key."""

    def test_volume_fact_grain_is_unique_on_its_four_part_key(self, api):
        """
        A repeat of customer, brand, type and week is refused while a different type is accepted.

        PRD: "The combination of `customer_id`, `brand_id`, `fact_type` and `period_start` must be unique across the whole journal; a repeat is refused with `ERR_VOLUME_FACT_DUPLICATE` (HTTP 409)."

        Design: Corner/errors/volume_fact_grain_is_unique_on_its_four_part_key
        """
        program, brand, customer = _reference_data(
            api, budget=500000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        first_fact = setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=1000, source=FactSource.EDI_852.value,
        )

        validate_error(
            api.create_volume_fact(
                create_volume_fact_payload(
                    customer["id"], brand["id"],
                    fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
                    units=2500, source=FactSource.MANUAL.value,
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.VOLUME_FACT_DUPLICATE.value,
        )
        shipment_fact = validate_success(
            api.create_volume_fact(
                create_volume_fact_payload(
                    customer["id"], brand["id"],
                    fact_type=FactType.SHIPMENT.value, period_start=MONDAY_AUG_03,
                    units=2500, source=FactSource.EDI_856.value,
                ),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        unchanged = validate_success(api.get_volume_fact(first_fact["id"], ANALYST_HEADERS))
        assert unchanged["units"] == 1000
        assert unchanged["source"] == FactSource.EDI_852.value
        assert shipment_fact["fact_type"] == FactType.SHIPMENT.value
        assert shipment_fact["units"] == 2500

        rows, meta = validate_paginated(
            api.list_volume_facts(
                ANALYST_HEADERS,
                params={"customer_id": customer["id"], "brand_id": brand["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first_fact["id"], shipment_fact["id"]}


class TestOneAccrualPerPromotionWeek:
    """A promotion accrues a given week exactly once."""

    def test_one_accrual_per_promotion_week(self, api):
        """
        Re-posting the same legal week is a duplicate and leaves the gross figure undoubled.

        PRD: "At most one accrual may exist per promotion and week: a second posting for the same `period_start` is refused with `ERR_ACCRUAL_PERIOD_DUPLICATE` (HTTP 409) **even after the first has been reversed**, because the reversal preserves the original for audit rather than erasing it."

        Design: Corner/errors/one_accrual_per_promotion_week
        """
        context = _scan_accrual_fixture(api, promotion_name="Scan Accrual Event")
        assert_money(context["accrual"]["amount"], 1000.00, "first amount")

        validate_error(
            api.create_accrual(
                context["promotion"]["id"], create_accrual_payload(MONDAY_AUG_03),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ACCRUAL_PERIOD_DUPLICATE.value,
        )

        rows, meta = validate_paginated(
            api.list_accruals(ANALYST_HEADERS,
                              params={"promotion_id": context["promotion"]["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [context["accrual"]["id"]]

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 1000.00, "gross_accrued_amount")


class TestReversalMustMatchToTheCent:
    """A reversal is all of the entry or none of it."""

    def test_reversal_must_match_the_entry_to_the_cent(self, api):
        """
        A 400.00 reversal of a 1000.00 entry is refused, and the matching 1000.00 one lands.

        PRD: "Partial reversals are not supported: the supplied `amount` must be strictly greater than 0.00 and must equal the reversed entry's `amount` exactly, or the request is refused with `ERR_REVERSAL_EXCEEDS_ENTRY_AMOUNT` (HTTP 422)."
        PRD: "The original entry's `status` moves `POSTED` → `REVERSED`, and a second entry is created carrying `entry_type` `REVERSAL`, `status` `POSTED`, an `amount` equal to the reversed entry's `amount`, a `reverses_entry_id` naming the reversed entry, a `fact_units` of 0 and an empty `tactic_line_amounts` array — and it is that new mirror entry, not the reversed original, that comes back as the response body."

        Design: Corner/errors/reversal_must_match_the_entry_to_the_cent
        """
        context = _scan_accrual_fixture(api, promotion_name="Scan Reversal Event")
        accrual_id = context["accrual"]["id"]
        assert_money(context["accrual"]["amount"], 1000.00, "entry amount")

        validate_error(
            api.reverse_accrual(
                accrual_id,
                reverse_accrual_payload(400.00, reversal_reason="Partial claw-back attempt."),
                ANALYST_HEADERS,
            ),
            ApiErrorId.REVERSAL_EXCEEDS_ENTRY_AMOUNT.value,
        )

        mirror = validate_success(
            api.reverse_accrual(
                accrual_id,
                reverse_accrual_payload(1000.00, reversal_reason="Scan data restated to zero."),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )
        assert_money(mirror["amount"], 1000.00, "mirror amount")
        assert mirror["entry_type"] == EntryType.REVERSAL.value
        assert mirror["reverses_entry_id"] == accrual_id

        original = read_accrual(api, accrual_id)
        assert original["status"] == AccrualEntryStatus.REVERSED.value

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["reversed_accrual_amount"], 1000.00, "reversed_accrual_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")


class TestEntryReversedOnlyOnce:
    """Neither a reversed entry nor a reversal itself can be reversed."""

    def test_an_entry_can_only_be_reversed_once(self, api):
        """
        A second reversal of the original and a reversal of the mirror are both refused.

        PRD: "Only an entry whose `entry_type` is `ACCRUAL` and whose `status` is `POSTED` may be reversed: a `REVERSAL` entry cannot itself be reversed and an already-`REVERSED` entry cannot be reversed twice, either attempt being refused with `ERR_ACCRUAL_ENTRY_ALREADY_REVERSED` (HTTP 409)."

        Design: Corner/errors/an_entry_can_only_be_reversed_once
        """
        context = _scan_accrual_fixture(api, promotion_name="Scan Double Reversal Event")
        accrual_id = context["accrual"]["id"]
        mirror = validate_success(
            api.reverse_accrual(
                accrual_id,
                reverse_accrual_payload(1000.00, reversal_reason="Scan data restated to zero."),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        validate_error(
            api.reverse_accrual(
                accrual_id,
                reverse_accrual_payload(1000.00, reversal_reason="Duplicate claw-back."),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ACCRUAL_ENTRY_ALREADY_REVERSED.value,
        )
        validate_error(
            api.reverse_accrual(
                mirror["id"],
                reverse_accrual_payload(1000.00, reversal_reason="Reversing the reversal."),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ACCRUAL_ENTRY_ALREADY_REVERSED.value,
        )

        rows, meta = validate_paginated(
            api.list_accruals(ANALYST_HEADERS,
                              params={"promotion_id": context["promotion"]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {accrual_id, mirror["id"]}

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["reversed_accrual_amount"], 1000.00, "reversed_accrual_amount")
        assert_money(promotion["accrued_balance"], 0.00, "accrued_balance")


class TestShipmentLeadShiftWindowMismatch:
    """The 14-day lead shift is applied before the window test, not after it."""

    def test_shipment_lead_shift_can_push_a_week_past_the_window(self, api):
        """
        The 08-24 week shifts to 09-07 and falls outside the window, while 08-03 accrues.

        PRD: "On the `SHIPMENT` basis the effective period is the requested `period_start` shifted forward by 14 days, and the facts read are those with `fact_type` `SHIPMENT`; the week that funds promoted sell-through is the week the goods left the plant, a fortnight before the consumer saw the price."
        PRD: "The effective period must land inside the promotion's half-open window — at or after `window_start` and strictly before `window_end` — or the posting is refused with `ERR_ACCRUAL_WINDOW_MISMATCH` (HTTP 422)."

        Design: Corner/errors/shipment_lead_shift_can_push_a_week_past_the_window
        """
        context = _single_tpr_promotion_fixture(
            api, accrual_default=AccrualMethod.SHIPMENT.value,
            promotion_name="Ship Basis Event",
            accrual_method=AccrualMethod.SHIPMENT.value,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            planned_units=5000, rate_per_case=1.000,
        )
        set_clock(api, instant(MONDAY_AUG_24))
        run_activation(api)
        setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.SHIPMENT.value, period_start=MONDAY_AUG_24,
            units=2000, source=FactSource.EDI_856.value,
        )
        setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.SHIPMENT.value, period_start=MONDAY_AUG_03,
            units=1500, source=FactSource.EDI_856.value,
        )

        validate_error(
            api.create_accrual(
                context["promotion"]["id"], create_accrual_payload(MONDAY_AUG_24),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ACCRUAL_WINDOW_MISMATCH.value,
        )

        entry = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)
        assert entry["period_start"] == MONDAY_AUG_03
        assert entry["fact_units"] == 1500
        assert_money(entry["amount"], 1500.00, "amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 1500.00, "gross_accrued_amount")


class TestAccrualImmediateReadAgreement:
    """The posting response and the reads that follow it carry the same cents."""

    def test_the_accrual_response_and_an_immediate_read_agree_to_the_cent(self, api):
        """
        A 3000.00 posting is already visible on the promotion, its allocation and the entry.

        PRD: "`recognized_spend_amount` is the **greater** of two views — the accrual-book view, `gross_accrued_amount` minus `reversed_accrual_amount`, and the deduction-book view, `consumed_deduction_amount` — rounded to 2 decimal places."
        PRD: "`accrued_amount` is the sum, across **all** child promotions regardless of lifecycle, of each promotion's `gross_accrued_amount` minus its `reversed_accrual_amount`, rounded to 2 decimal places."

        Design: Corner/consistency_model/the_accrual_response_and_an_immediate_read_agree_to_the_cent
        """
        context = _single_tpr_promotion_fixture(
            api, accrual_default=AccrualMethod.CONSUMPTION.value,
            promotion_name="Immediate Accrual Event",
            accrual_method=AccrualMethod.CONSUMPTION.value,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
            planned_units=8000, rate_per_case=1.250,
            planned_amount=100000.00, baseline_units=20000,
            planned_incremental_units=20000,
        )
        assert_money(context["promotion"]["planned_total_spend"], 10200.00, "planned_total_spend")
        fact = setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
            units=2400, source=FactSource.EDI_852.value,
        )
        set_clock(api, instant("2026-08-05"))
        run_activation(api)

        entry = _post_accrual(api, context["promotion"]["id"], MONDAY_AUG_03)

        assert entry["entry_type"] == EntryType.ACCRUAL.value
        assert entry["status"] == AccrualEntryStatus.POSTED.value
        assert entry["method"] == AccrualMethod.CONSUMPTION.value
        assert_money(entry["amount"], 3000.00, "amount")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["gross_accrued_amount"], 3000.00, "gross_accrued_amount")
        assert_money(promotion["reversed_accrual_amount"], 0.00, "reversed_accrual_amount")
        assert_money(promotion["accrued_balance"], 3000.00, "accrued_balance")
        assert_money(promotion["recognized_spend_amount"], 3000.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.2941, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["accrued_amount"], 3000.00, "accrued_amount")
        assert_money(allocation["settled_amount"], 0.00, "settled_amount")
        assert_money(allocation["at_risk_amount"], 0.00, "at_risk_amount")

        stored_entry = read_accrual(api, entry["id"])
        assert_money(stored_entry["amount"], 3000.00, "stored amount")
        assert stored_entry["period_start"] == MONDAY_AUG_03

        stored_fact = validate_success(api.get_volume_fact(fact["id"], ANALYST_HEADERS))
        assert stored_fact["units"] == 2400
