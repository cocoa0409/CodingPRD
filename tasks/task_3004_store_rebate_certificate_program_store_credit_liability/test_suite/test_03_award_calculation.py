"""The rebate award calculation: dual variants, per-line rounding, selectors,
exclusions, and the minimum-quantity gate."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId,
    set_clock, create_store, create_account, create_receipt, cash_line,
    create_active_program, create_program_item, create_program,
    submit_receipt, approve_submission, reject_submission, resubmit_submission,
    list_receipt_lines, process_return,
    setup_store_with_program, setup_account_with_receipt,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _lines_by_number(api, store_id, submission_id):
    lines = get_success_data(api.list_submission_lines(store_id, submission_id, GUEST))
    return {l["receipt_line_id"]: l for l in lines}, lines


class TestProvisionalVsAdjudicatedDivergence:

    def test_provisional_counts_returned_units_adjudicated_does_not(self, api):
        """PRD §3.5: "The provisional variant — computed on submission
        creation and on each resubmit — skips the minimum-quantity check,
        ignores returns, and stores its result in `provisional_award_cents`.
        The adjudicated variant — computed when guest service approves —
        subtracts the current `returned_quantity`, enforces `min_quantity`,
        and freezes its result into `award_cents`, which is null until
        adjudication."

        Design: Difficulty/dual_variant_calc/rebate_award_provisional_vs_adjudicated_diverge_after_return
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-DV1")
        program, _ = create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.11, "min_quantity": 1},
            {"sku": "BBB", "rebate_pct": 0.11, "min_quantity": 1},
            {"sku": "CCC", "rebate_pct": 0.5, "min_quantity": 1,
             "per_receipt_cap_cents": 2000},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(1, "AAA", "TOOLS", 3, 5000),
                cash_line(2, "BBB", "TOOLS", 4, 2500),
                cash_line(3, "CCC", "TOOLS", 2, 3000),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-DV1",
        )
        process_return(store["id"], receipt["id"],
                       [{"line_number": 1, "quantity": 1}])

        submission = submit_receipt(store["id"], receipt["id"], account)
        assert submission["provisional_award_cents"] == 4750, (
            f"provisional must treat returned_quantity as 0: "
            f"3*5000*0.11 + 4*2500*0.11 + min(2*3000*0.5, 2000) = "
            f"1650 + 1100 + 2000 = 4750, got "
            f"{submission['provisional_award_cents']}"
        )
        assert submission["award_cents"] is None, (
            "award_cents is null until adjudication"
        )

        submission = approve_submission(store["id"], submission["id"])
        assert submission["status"] == "APPROVED"
        assert submission["award_cents"] == 4200, (
            f"adjudicated nets the returned unit out: 2*5000*0.11 + 1100 + "
            f"2000 = 1100 + 1100 + 2000 = 4200, got {submission['award_cents']}"
        )
        assert submission["provisional_award_cents"] == 4750

        account_read = validate_success(
            api.get_account(store["id"], account["id"], FINANCE)
        )
        assert account_read["pending_award_cents"] == 4200
        assert account_read["lifetime_rebate_cents"] == 4200

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 4200, (
            "an APPROVED award enters gross liability before issuance"
        )

    def test_variants_agree_when_no_returns_predate_adjudication(self, api):
        """PRD §3.5: "The provisional variant — computed on submission
        creation and on each resubmit — skips the minimum-quantity check,
        ignores returns, and stores its result in `provisional_award_cents`.
        The adjudicated variant — computed when guest service approves —
        subtracts the current `returned_quantity`, enforces `min_quantity`,
        and freezes its result into `award_cents`, which is null until
        adjudication."

        Design: Difficulty/dual_variant_calc/rebate_award_provisional_vs_adjudicated_diverge_after_return
        """
        # with no returns and min_quantity 1, both variants see the same
        # inputs, so provisional and adjudicated awards must coincide
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-DV1B")
        create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.11, "min_quantity": 1},
            {"sku": "BBB", "rebate_pct": 0.11, "min_quantity": 1},
            {"sku": "CCC", "rebate_pct": 0.5, "min_quantity": 1,
             "per_receipt_cap_cents": 2000},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(1, "AAA", "TOOLS", 3, 5000),
                cash_line(2, "BBB", "TOOLS", 4, 2500),
                cash_line(3, "CCC", "TOOLS", 2, 3000),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-DV1B",
        )
        submission = submit_receipt(store["id"], receipt["id"], account)
        assert submission["provisional_award_cents"] == 4750
        submission = approve_submission(store["id"], submission["id"])
        assert submission["award_cents"] == 4750, (
            "the two variants diverge only when a return predates "
            "adjudication (or a min_quantity gate engages)"
        )

    def test_store_liability_gross_vs_net_diverge_by_breakage_rate(self, api):
        """PRD §3.7: "The net liability, `net_liability_cents`, is the gross
        figure multiplied by one minus the store's `expected_breakage_rate`,
        with a single round-half-up to whole cents applied at the very end."
        PRD §3.3: "`credit_balance_cents`, the sum of
        `remaining_balance_cents` over the account's certificates in `ACTIVE`
        or `PARTIALLY_REDEEMED` status"

        Design: Difficulty/dual_variant_calc/store_liability_gross_vs_net_diverge_by_breakage_rate
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-DV2")
        create_active_program(store["id"], [{"sku": "AAA", "rebate_pct": 0.11}])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        r1 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 2, 50000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-DV2-1",
        )
        sub1 = approve_submission(
            store["id"], submit_receipt(store["id"], r1["id"], account)["id"]
        )
        cert1 = validate_success(
            api.issue_certificate(store["id"], sub1["id"], GUEST)
        )
        assert cert1["issued_amount_cents"] == 11000
        assert cert1["status"] == "ACTIVE"
        assert cert1["remaining_balance_cents"] == 11000

    def test_gross_and_net_liability_diverge_on_shared_account(self, api):
        """PRD §3.7: "The net liability, `net_liability_cents`, is the gross
        figure multiplied by one minus the store's `expected_breakage_rate`,
        with a single round-half-up to whole cents applied at the very end."
        PRD §3.3: "`credit_balance_cents`, the sum of
        `remaining_balance_cents` over the account's certificates in `ACTIVE`
        or `PARTIALLY_REDEEMED` status"

        Design: Difficulty/dual_variant_calc/store_liability_gross_vs_net_diverge_by_breakage_rate
        """
        from test_helpers import redeem_certificate
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-DV2")
        create_active_program(store["id"], [{"sku": "AAA", "rebate_pct": 0.11}])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")

        r1 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 2, 50000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-DV2-1",
        )
        sub1 = approve_submission(
            store["id"], submit_receipt(store["id"], r1["id"], account)["id"]
        )
        cert1 = validate_success(
            api.issue_certificate(store["id"], sub1["id"], GUEST)
        )
        assert cert1["issued_amount_cents"] == 11000

        r2 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 50000)],
            purchase_at="2026-09-08T11:00:00Z", receipt_number="R-DV2-2",
        )
        sub2 = approve_submission(
            store["id"], submit_receipt(store["id"], r2["id"], account)["id"]
        )
        cert2 = validate_success(
            api.issue_certificate(store["id"], sub2["id"], GUEST)
        )
        assert cert2["issued_amount_cents"] == 5500

        set_clock("2026-09-09T12:00:00Z")
        r3 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 5000)],
            purchase_at="2026-09-09T10:00:00Z", receipt_number="R-DV2-3",
        )
        cert1 = redeem_certificate(store["id"], cert1["id"], r3["id"], 500)
        assert cert1["status"] == "PARTIALLY_REDEEMED"
        assert cert1["remaining_balance_cents"] == 10500

        cert2_read = validate_success(
            api.get_certificate(store["id"], cert2["id"], GUEST)
        )
        assert cert2_read["status"] == "ACTIVE"
        assert cert2_read["remaining_balance_cents"] == 5500

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 16000, (
            f"gross = 10500 + 5500 = 16000, got "
            f"{store_read['outstanding_liability_cents']}"
        )
        assert store_read["net_liability_cents"] == 12000, (
            f"net = round_half_up(16000 * (1 - 0.25)) = 12000, got "
            f"{store_read['net_liability_cents']}"
        )
        account_read = validate_success(
            api.get_account(store["id"], account["id"], FINANCE)
        )
        assert account_read["credit_balance_cents"] == 16000
        assert account_read["pending_award_cents"] == 0


class TestCombinatorialFormula:

    def test_rebate_award_five_input_interactions_single_line(self, api):
        """PRD §3.5: "5. The gross base is the net quantity multiplied by
        `unit_price_cents`. The provisional variant computes this with
        returns invisible — `returned_quantity` treated as 0 — because
        returns cannot be known at submission time."
        PRD §3.5: "8. When the item's `per_receipt_cap_cents` is set, the raw
        award is capped at that value — the cap compares against the
        unrounded award."
        PRD §3.5: "9. The line's `awarded_cents` is the raw award rounded
        half-up to whole cents."

        Design: Difficulty/combinatorial_formula/rebate_award_five_input_interactions_single_line
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CF1")
        create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.1, "min_quantity": 2,
             "per_receipt_cap_cents": 1000},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(
                    1, "AAA", "TOOLS", 5, 3000,
                    extra_tenders=[{
                        "tender_type": "STORE_CREDIT_CERTIFICATE",
                        "amount_cents": 800,
                    }],
                ),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CF1",
        )
        process_return(store["id"], receipt["id"],
                       [{"line_number": 1, "quantity": 2}])

        submission = submit_receipt(store["id"], receipt["id"], account)
        assert submission["provisional_award_cents"] == 1000, (
            f"provisional: 5*3000 - 800 = 14200 * 0.10 = 1420 capped at "
            f"1000, got {submission['provisional_award_cents']}"
        )
        submission = approve_submission(store["id"], submission["id"])
        assert submission["award_cents"] == 820, (
            f"adjudicated: 3*3000 - 800 = 8200 * 0.10 = 820 (below the 1000 "
            f"cap, so the cap branch is NOT taken), got "
            f"{submission['award_cents']}"
        )
        _, lines = _lines_by_number(api, store["id"], submission["id"])
        assert len(lines) == 1
        assert lines[0]["eligible_base_cents"] == 8200
        assert lines[0]["awarded_cents"] == 820
        assert lines[0]["exclusion_reason"] is None

    def test_excluded_category_checked_before_cap_and_base(self, api):
        """PRD §3.5: "2. If the line's `category` appears in the matched
        item's `excluded_categories`, the line is excluded with reason
        `EXCLUDED_CATEGORY` and base 0 — the category overrides the SKU
        match."

        Design: Difficulty/combinatorial_formula/rebate_award_five_input_interactions_single_line
        """
        # same program-item shape (cap, min_quantity) but with the category
        # excluded: the line is excluded before any base or cap arithmetic
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CF1B")
        create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.1, "min_quantity": 2,
             "per_receipt_cap_cents": 1000,
             "excluded_categories": ["TOOLS"]},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(
                    1, "AAA", "TOOLS", 5, 3000,
                    extra_tenders=[{
                        "tender_type": "STORE_CREDIT_CERTIFICATE",
                        "amount_cents": 800,
                    }],
                ),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CF1B",
        )
        submission = approve_submission(
            store["id"], submit_receipt(store["id"], receipt["id"], account)["id"]
        )
        lines = get_success_data(
            api.list_submission_lines(store["id"], submission["id"], GUEST)
        )
        assert lines[0]["eligible_base_cents"] == 0
        assert lines[0]["awarded_cents"] == 0
        assert lines[0]["exclusion_reason"] == "EXCLUDED_CATEGORY"
        assert submission["award_cents"] == 0

    def test_per_line_rounding_then_sum_beats_sum_then_round(self, api):
        """PRD §3.5: "Rounding is pinned per line: each line rounds first,
        and the submission's award is the sum of the rounded line awards —
        never the other way around."
        PRD §2.5: "the value is rounded to a whole number of cents using the
        round-half-up method."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CF2")
        create_active_program(store["id"], [{"sku": "AAA", "rebate_pct": 0.11}])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")

        r1 = create_receipt(
            store["id"], account["id"], [
                cash_line(1, "AAA", "TOOLS", 1, 333),
                cash_line(2, "AAA", "TOOLS", 1, 333),
                cash_line(3, "AAA", "TOOLS", 1, 333),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CF2-1",
        )
        r2 = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 999)],
            purchase_at="2026-09-08T11:00:00Z", receipt_number="R-CF2-2",
        )
        sub1 = approve_submission(
            store["id"], submit_receipt(store["id"], r1["id"], account)["id"]
        )
        sub2 = approve_submission(
            store["id"], submit_receipt(store["id"], r2["id"], account)["id"]
        )
        assert sub1["award_cents"] == 111, (
            f"round_half_up(333*0.11)=37 per line, summed 3x = 111, got "
            f"{sub1['award_cents']}"
        )
        assert sub2["award_cents"] == 110, (
            f"round_half_up(999*0.11)=110 on a single line, got "
            f"{sub2['award_cents']}"
        )

    def test_per_line_rounding_order_pinned_at_provisional_stage(self, api):
        """PRD §3.5: "Rounding is pinned per line: each line rounds first,
        and the submission's award is the sum of the rounded line awards —
        never the other way around."
        PRD §3.5: "The provisional variant — computed on submission creation
        and on each resubmit — skips the minimum-quantity check, ignores
        returns, and stores its result in `provisional_award_cents`."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        # the pinned rounding order also governs the provisional variant:
        # three lines of 1x333 at 0.11 sum to 111, not 110
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CF2B")
        create_active_program(store["id"], [{"sku": "AAA", "rebate_pct": 0.11}])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Rita Retail")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(1, "AAA", "TOOLS", 1, 333),
                cash_line(2, "AAA", "TOOLS", 1, 333),
                cash_line(3, "AAA", "TOOLS", 1, 333),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CF2B",
        )
        submission = submit_receipt(store["id"], receipt["id"], account)
        assert submission["provisional_award_cents"] == 111, (
            f"round_half_up(333*0.11)=37 per line, summed 3x = 111 already "
            f"at the provisional stage, got "
            f"{submission['provisional_award_cents']}"
        )


class TestAwardExclusionsAndSelectors:

    def test_excluded_category_zeroes_line_despite_matching_sku(self, api):
        """PRD §3.5: "2. If the line's `category` appears in the matched
        item's `excluded_categories`, the line is excluded with reason
        `EXCLUDED_CATEGORY` and base 0 — the category overrides the SKU
        match."

        Design: Corner/calculations/excluded_category_zeroes_line_despite_matching_sku
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CAL1")
        create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.1, "excluded_categories": ["GIFT_CARD"]},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"], [
                cash_line(1, "AAA", "GIFT_CARD", 1, 10000),
                cash_line(2, "AAA", "TOOLS", 1, 10000),
            ],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CAL1",
        )
        submission = approve_submission(
            store["id"], submit_receipt(store["id"], receipt["id"], account)["id"]
        )
        receipt_lines = {
            l["id"]: l for l in list_receipt_lines(store["id"], receipt["id"])
        }
        number_by_id = {
            lid: l["line_number"] for lid, l in receipt_lines.items()
        }
        lines = get_success_data(
            api.list_submission_lines(store["id"], submission["id"], GUEST)
        )
        by_number = {
            number_by_id[l["receipt_line_id"]]: l for l in lines
        }
        assert by_number[1]["awarded_cents"] == 0
        assert by_number[1]["exclusion_reason"] == "EXCLUDED_CATEGORY"
        assert by_number[2]["awarded_cents"] == 1000
        assert by_number[2]["exclusion_reason"] is None
        assert submission["award_cents"] == 1000

    def test_min_quantity_enforced_at_adjudication_not_at_submission(self, api):
        """PRD §3.5: "3. Compute the net quantity as the line's `quantity`
        minus its `returned_quantity`. In the adjudicated variant only, if
        the net quantity is below the program item's `min_quantity`, the line
        is excluded with reason `BELOW_MIN_QUANTITY` and base 0."
        PRD §3.5: "The provisional variant — computed on submission creation
        and on each resubmit — skips the minimum-quantity check, ignores
        returns, and stores its result in `provisional_award_cents`."

        Design: Corner/calculations/min_quantity_enforced_at_adjudication_not_at_submission
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CAL2")
        create_active_program(store["id"], [
            {"sku": "AAA", "rebate_pct": 0.11, "min_quantity": 3},
        ])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 3, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CAL2",
        )
        process_return(store["id"], receipt["id"],
                       [{"line_number": 1, "quantity": 1}])

        submission = submit_receipt(store["id"], receipt["id"], account)
        assert submission["provisional_award_cents"] == 330, (
            f"provisional skips min_quantity and ignores returns: "
            f"3*1000*0.11 = 330, got {submission['provisional_award_cents']}"
        )
        submission = approve_submission(store["id"], submission["id"])
        assert submission["status"] == "APPROVED"
        assert submission["award_cents"] == 0, (
            "an all-zero award still approves"
        )
        lines = get_success_data(
            api.list_submission_lines(store["id"], submission["id"], GUEST)
        )
        assert lines[0]["awarded_cents"] == 0
        assert lines[0]["exclusion_reason"] == "BELOW_MIN_QUANTITY"

    def test_program_item_selector_picks_highest_pct_then_earliest_created(self, api):
        """PRD §3.5: "If several items match, the one with the greatest
        `rebate_pct` wins, ties broken by the program item's earlier
        `created_at`."

        Design: Corner/calculations/program_item_selector_picks_highest_pct_then_earliest_created
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CAL3")
        program = create_program(store["id"], name="W")
        item_lo = create_program_item(store["id"], program["id"],
                                      sku="AAA", rebate_pct=0.1)
        item_hi_1 = create_program_item(store["id"], program["id"],
                                        sku="AAA", rebate_pct=0.15)
        create_program_item(store["id"], program["id"],
                            sku="AAA", rebate_pct=0.15,
                            per_receipt_cap_cents=1200)
        program = validate_success(
            api.activate_program(store["id"], program["id"], ADMIN)
        )
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 10000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CAL3",
        )
        submission = approve_submission(
            store["id"], submit_receipt(store["id"], receipt["id"], account)["id"]
        )
        assert submission["award_cents"] == 1500, (
            f"the greatest rebate_pct 0.15 wins: 10000*0.15 = 1500, got "
            f"{submission['award_cents']}"
        )
        lines = get_success_data(
            api.list_submission_lines(store["id"], submission["id"], GUEST)
        )
        assert lines[0]["program_item_id"] == item_hi_1["id"], (
            "tie between the two 0.15 items is broken by earlier created_at"
        )

    def test_fully_certificate_tendered_line_earns_zero_base(self, api):
        """PRD §3.5: "4. If the line's `certificate_tendered_cents` is at
        least the line's full value — quantity multiplied by unit price —
        the line is excluded with reason `FULLY_CERTIFICATE_TENDERED` and
        base 0."
        PRD §3.4: "the recorded `certificate_tendered_cents` on a line
        reduces that line's rebate base, so the certificate-funded portion
        of a purchase never earns another rebate."

        Design: Corner/calculations/fully_certificate_tendered_line_earns_zero_base
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-CAL6")
        create_active_program(store["id"], [{"sku": "AAA", "rebate_pct": 0.1}])
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"], [{
                "line_number": 1, "sku": "AAA", "category": "TOOLS",
                "quantity": 1, "unit_price_cents": 10000,
                "tender_splits": [{
                    "tender_type": "STORE_CREDIT_CERTIFICATE",
                    "amount_cents": 10000,
                }],
            }],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-CAL6",
        )
        submission = approve_submission(
            store["id"], submit_receipt(store["id"], receipt["id"], account)["id"]
        )
        lines = get_success_data(
            api.list_submission_lines(store["id"], submission["id"], GUEST)
        )
        assert lines[0]["eligible_base_cents"] == 0
        assert lines[0]["exclusion_reason"] == "FULLY_CERTIFICATE_TENDERED"
        assert submission["award_cents"] == 0
        assert submission["status"] == "APPROVED"
