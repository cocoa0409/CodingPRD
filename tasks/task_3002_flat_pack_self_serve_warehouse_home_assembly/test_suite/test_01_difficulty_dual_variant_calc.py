"""Difficulty rule: dual_variant_calc — assembly billing and refund bases."""
import pytest

from test_helpers import (
    ADMIN,
    OPS,
    PROVIDER,
    add_return_line,
    create_return,
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


class TestAssemblyEstimateVsCappedBilling:
    """Instance: assembly_estimate_vs_capped_billing_diverge."""

    def test_estimate_actual_and_billed_are_three_distinct_numbers(self, api):
        """PRD §3.6: "The job's `estimated_minutes` is the sum, over every line
        whose article requires assembly, of the line quantity times that
        article's standard `minutes_per_unit`"
        PRD §3.6: "the crew reports `actual_minutes`, and `billed_minutes` is
        set to the lesser of that report and the estimate scaled by one and a
        half, the scaled cap rounded up to a whole minute — identical inputs
        can bill less than the capped estimate, never more."

        Design: Difficulty/dual_variant_calc/assembly_estimate_vs_capped_billing_diverge
        """
        store, member = setup_store_and_customer(member=True)
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=45,
        )
        order, _, job = setup_in_progress_job(
            member, store, article, qty=2,
            window_start="2026-09-10T10:00:00Z", window_end="2026-09-10T12:00:00Z",
        )
        assert job["estimated_minutes"] == 90, (
            f"estimate should be the table sum 2 x 45 = 90, got {job['estimated_minutes']}"
        )

        completed = validate_success(
            api.complete_assembly_job(job["id"], {"actual_minutes": 200}, PROVIDER)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["estimated_minutes"] == 90
        assert completed["billed_minutes"] == 135, (
            "billed = min(200, ceil(90 * 1.5)) = 135 — the capped actual, "
            f"got {completed['billed_minutes']}"
        )
        assert completed["billed_minutes"] != 200
        assert completed["billed_minutes"] != completed["estimated_minutes"]

    def test_actual_under_cap_bills_actual_and_estimate_ignores_actuals(self, api):
        """PRD §3.6: "the crew reports `actual_minutes`, and `billed_minutes` is
        set to the lesser of that report and the estimate scaled by one and a
        half, the scaled cap rounded up to a whole minute — identical inputs
        can bill less than the capped estimate, never more."

        Design: Difficulty/dual_variant_calc/assembly_estimate_vs_capped_billing_diverge
        """
        store, customer = setup_store_and_customer()
        article, _, _ = setup_article_with_stock(
            store, on_hand=5, price_cents=1000, category="FURNITURE",
            requires_assembly=True, register_standard_minutes=45,
        )
        _, _, job = setup_in_progress_job(customer, store, article, qty=2)
        assert job["estimated_minutes"] == 90
        completed = validate_success(
            api.complete_assembly_job(job["id"], {"actual_minutes": 60}, PROVIDER)
        )
        # 60 < ceil(90 * 1.5) = 135, so the lesser report is billed.
        assert completed["billed_minutes"] == 60
        assert completed["status"] == "COMPLETED"


class TestReceiptedVsNoReceiptRefund:
    """Instance: receipted_vs_no_receipt_refund_diverge."""

    def test_identical_price_and_grade_refund_differ_by_variant(self, api):
        """PRD §3.8: "a receipted line's `unit_basis_cents` is the order line's
        `effective_unit_paid_cents` — the price actually paid; a no-receipt
        line's basis starts from the article's `lowest_price_365d_cents` when
        set, falling back to its current `price_cents`, and is then discounted
        by a 10 percent no-receipt penalty with a single rounding half-up, so
        the identical article and grade refunds less without a receipt."
        PRD §3.8: "a no-receipt line writes off nothing."

        Design: Difficulty/dual_variant_calc/receipted_vs_no_receipt_refund_diverge
        """
        store, member = setup_store_and_customer(member=True)
        art_a, _, _ = setup_article_with_stock(store, on_hand=5, price_cents=1000)
        art_b = get_success_data(api.create_article(
            {"article_number": "ART-B-DIV", "name": "Lamp", "category": "ACCESSORY",
             "pick_policy": "SELF_SERVE", "price_cents": 1000,
             "lowest_price_365d_cents": 1000},
            ADMIN,
        ))

        order, order_lines = setup_fulfilled_order(member, store, [(art_a, 2)])

        # Receipted return: 1 x A graded OPEN_BOX -> round(1000 x 0.85) = 850.
        r1 = create_return(member, order_id=order["id"])
        rl1 = add_return_line(member, r1["id"], art_a["id"], qty=1,
                              order_line_id=order_lines[0]["id"])
        submit_return(member, r1["id"])
        grade_line(r1["id"], rl1["id"], "OPEN_BOX")
        settled1 = settle_return(r1["id"])

        # No-receipt return: 1 x B graded OPEN_BOX -> round(900 x 0.85) = 765.
        r2 = create_return(member)
        rl2 = add_return_line(member, r2["id"], art_b["id"], qty=1)
        submit_return(member, r2["id"])
        grade_line(r2["id"], rl2["id"], "OPEN_BOX")
        settled2 = settle_return(r2["id"])

        assert settled1["refund_total_cents"] == 850
        assert settled2["refund_total_cents"] == 765
        assert settled1["refund_total_cents"] != settled2["refund_total_cents"]
        assert settled1["writeoff_total_cents"] == 150
        assert settled2["writeoff_total_cents"] == 0

    def test_no_receipt_line_basis_is_lowest_price_discounted_ten_percent(self, api):
        """PRD §3.8: "a no-receipt line's basis starts from the article's
        `lowest_price_365d_cents` when set, falling back to its current
        `price_cents`, and is then discounted by a 10 percent no-receipt
        penalty with a single rounding half-up"
        PRD §3.8: "The condition factor applied to the basis is 100 percent
        for `LIKE_NEW`, 85 percent for `OPEN_BOX`, 50 percent for `DAMAGED`,
        and nothing for `SCRAP`, using the effective grade after the assembly
        cap"

        Design: Difficulty/dual_variant_calc/receipted_vs_no_receipt_refund_diverge
        """
        store, member = setup_store_and_customer(member=True)
        article = get_success_data(api.create_article(
            {"article_number": "ART-B-BASIS", "name": "Lamp", "category": "ACCESSORY",
             "pick_policy": "SELF_SERVE", "price_cents": 1000,
             "lowest_price_365d_cents": 1000},
            ADMIN,
        ))
        ret = create_return(member)
        line = add_return_line(member, ret["id"], article["id"], qty=1)
        submit_return(member, ret["id"])
        graded = grade_line(ret["id"], line["id"], "OPEN_BOX")
        settled = settle_return(ret["id"])

        graded_line = get_success_data(api.get_return_line(line["id"], OPS))
        assert graded_line["unit_basis_cents"] == 900, (
            f"basis = round_half_up(1000 x 0.9) = 900, got {graded_line['unit_basis_cents']}"
        )
        assert graded_line["refund_cents"] == 765
        assert settled["refund_total_cents"] == 765
        assert settled["writeoff_total_cents"] == 0
