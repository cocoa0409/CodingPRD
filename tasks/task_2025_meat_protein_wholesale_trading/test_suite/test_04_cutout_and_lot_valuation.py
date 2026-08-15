"""Cutout valuation (booking vs grading variants), per-line rounding order,
and the aging- and grade-adjusted lot market value."""
from test_helpers import (
    WEEK_1,
    WEEK_2,
    add_sheet_line,
    assert_purchase_order,
    book_po,
    create_carcass_product,
    create_product,
    create_sheet,
    create_supplier,
    create_warehouse,
    create_yield_spec,
    get_lot,
    get_po,
    get_po_lot,
    get_sheet,
    inspect_lot,
    issue_grade_certificate,
    publish_sheet,
    receive_po,
    set_clock,
    validate_success,
)


def _setup_two_sheet_cutout():
    """CARC-A with 11%/25% yield specs; S1 (week 1: 900c/400c) PUBLISHED."""
    carc = create_carcass_product(product_code="CARC-A")
    rib = create_product(product_code="RIBEYE-A", max_fat_pct=12.0)
    chk = create_product(product_code="CHUCK-A", max_fat_pct=18.0)
    create_yield_spec(carc["id"], rib["id"], 11.0, 9.0, 13.0)
    create_yield_spec(carc["id"], chk["id"], 25.0, 23.0, 27.0)
    supplier = create_supplier(establishment_number="EST-1")
    warehouse = create_warehouse(name="WH-1")
    s1 = create_sheet(WEEK_1)
    add_sheet_line(s1["id"], rib["id"], 900, 50_000)
    add_sheet_line(s1["id"], chk["id"], 400, 50_000)
    publish_sheet(s1["id"])
    po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=2000,
                 contract_price_per_cwt_cents=25_000,
                 required_delivery_date="2026-08-05", po_number="PO-1")
    return carc, rib, chk, supplier, warehouse, s1, po


class TestCutoutBookingVsGradingBasis:
    def test_booking_estimate_uses_ordered_weight_and_latest_published_sheet(
            self):
        """PRD §3.3: "For each specification, the expected output weight is the
        basis weight — `ordered_weight_lbs` at booking — multiplied by the
        specification's `expected_yield_pct` and divided by one hundred."
        PRD §3.3: "The sheet selected at booking is the most recently published
        sheet under the §2.7 selector."

        Design: Difficulty/dual_variant_calc/po_cutout_booking_vs_grading_basis
        """
        *_, s1, po = _setup_two_sheet_cutout()
        booked = get_po(po["id"])
        assert_purchase_order(booked)
        assert booked["status"] == "BOOKED"
        # 2000 x 0.11 x 900 + 2000 x 0.25 x 400 = 198000 + 200000
        assert booked["estimated_cutout_value_cents"] == 398_000, (
            f"booking estimate must price 2000 lbs against S1, got "
            f"{booked['estimated_cutout_value_cents']}"
        )
        assert booked["actual_cutout_value_cents"] is None

    def test_grading_cutout_uses_received_weight_and_grading_week_sheet(
            self, quality_grader_headers):
        """PRD §3.4: "When the graded lot belongs to a purchase order in
        `RECEIVED` status, the grading also advances the order from `RECEIVED`
        to `GRADED`, increments the order's `version`, and computes the order's
        `actual_cutout_value_cents` using the grading-time variant of the
        cutout model: the formula is the per-line-rounded sum of §3.3, but the
        basis weight is the order's `received_weight_lbs` and the selected
        sheet is the one whose half-open week contains the certificate's
        `issue_date` — a sheet in `PUBLISHED`, `CLOSED`, or `SUPERSEDED`
        status qualifies."
        PRD §3.2: "First, the referenced sheet transitions from `PUBLISHED` to
        `SUPERSEDED`."

        Design: Difficulty/dual_variant_calc/po_cutout_booking_vs_grading_basis
        """
        _, rib, chk, _, warehouse, s1, po = _setup_two_sheet_cutout()
        set_clock("2026-08-10T00:00:00Z")
        s2 = create_sheet(WEEK_2, supersedes_sheet_id=s1["id"])
        add_sheet_line(s2["id"], rib["id"], 1000, 50_000)
        add_sheet_line(s2["id"], chk["id"], 400, 50_000)
        publish_sheet(s2["id"])
        receive_po(po["id"], warehouse["id"], 1900, lot_code="LOT-1",
                   production_date="2026-08-09")
        lot = get_po_lot(po["id"])

        issue_grade_certificate(lot["id"], "CHOICE", issue_date="2026-08-10",
                                certificate_number="CERT-1")

        graded = get_po(po["id"])
        assert graded["status"] == "GRADED"
        assert graded["estimated_cutout_value_cents"] == 398_000
        # 1900 x 0.11 x 1000 + 1900 x 0.25 x 400 = 209000 + 190000
        assert graded["actual_cutout_value_cents"] == 399_000, (
            f"grading cutout must price 1900 lbs against the sheet covering "
            f"the grading week, got {graded['actual_cutout_value_cents']}"
        )
        assert (graded["estimated_cutout_value_cents"]
                != graded["actual_cutout_value_cents"])
        assert get_sheet(s1["id"])["status"] == "SUPERSEDED"


class TestCutoutPerLineRoundingOrder:
    def _setup(self):
        carc = create_carcass_product(product_code="CARC-B")
        pa = create_product(product_code="PA-B", max_fat_pct=12.0)
        pb = create_product(product_code="PB-B", max_fat_pct=14.0)
        create_yield_spec(carc["id"], pa["id"], 12.5, 10.0, 15.0)
        create_yield_spec(carc["id"], pb["id"], 12.5, 10.0, 15.0)
        supplier = create_supplier(establishment_number="EST-4")
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], pa["id"], 202, 10_000)
        add_sheet_line(s1["id"], pb["id"], 206, 10_000)
        publish_sheet(s1["id"])
        return carc, supplier

    def test_per_line_round_then_sum_at_ten_lbs(self):
        """PRD §3.3: "Each per-product line value is rounded half-up to whole
        cents first, and only then are the rounded lines summed — the rounding
        order is pinned per-line-then-sum and is never sum-then-round."

        Design: Difficulty/combinatorial_formula/cutout_per_line_rounding_order
        """
        carc, supplier = self._setup()
        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=10,
                     contract_price_per_cwt_cents=30_000,
                     required_delivery_date="2026-08-06", po_number="PO-4")
        booked = get_po(po["id"])
        # round_half_up(1.25 x 202) + round_half_up(1.25 x 206) = 253 + 258;
        # the forbidden sum-then-round order would give 510.
        assert booked["estimated_cutout_value_cents"] == 511, (
            f"per-line-then-sum must give 511 (not the sum-then-round 510), "
            f"got {booked['estimated_cutout_value_cents']}"
        )

    def test_per_line_round_then_sum_at_thirty_lbs(self):
        """PRD §3.3: "Each per-product line value is rounded half-up to whole
        cents first, and only then are the rounded lines summed — the rounding
        order is pinned per-line-then-sum and is never sum-then-round."

        Design: Difficulty/combinatorial_formula/cutout_per_line_rounding_order
        """
        carc, supplier = self._setup()
        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=30,
                     contract_price_per_cwt_cents=30_000,
                     required_delivery_date="2026-08-06")
        booked = get_po(po["id"])
        # round_half_up(3.75 x 202) + round_half_up(3.75 x 206) = 758 + 773;
        # sum-then-round would give 1530.
        assert booked["estimated_cutout_value_cents"] == 1531, (
            f"per-line-then-sum must give 1531 (not the sum-then-round 1530), "
            f"got {booked['estimated_cutout_value_cents']}"
        )


class TestAgingAdjustedUnitValue:
    def _setup(self):
        """LOT-2: 100 lbs CHUCK-A2, production 2026-08-01, graded SELECT."""
        chk = create_product(product_code="CHUCK-A2", max_fat_pct=18.0)
        supplier = create_supplier(establishment_number="EST-3")
        warehouse = create_warehouse(name="WH-1")
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], chk["id"], 500, 50_000)
        publish_sheet(s1["id"])
        po = book_po(supplier["id"], chk["id"], ordered_weight_lbs=100,
                     contract_price_per_cwt_cents=18_000,
                     required_delivery_date="2026-08-03", po_number="PO-3")
        receive_po(po["id"], warehouse["id"], 100, lot_code="LOT-2",
                   production_date="2026-08-01")
        lot = get_po_lot(po["id"])
        inspect_lot(lot["id"], 15.0)
        issue_grade_certificate(lot["id"], "SELECT", issue_date="2026-08-02",
                                certificate_number="CERT-2")
        return lot

    def test_age_band_one_boundary_value_at_seven_days(
            self, desk_admin_headers):
        """PRD §3.4: "The second factor is a grade multiplier: 1.08 for
        `PRIME`, 1.00 for `CHOICE`, 0.94 for `SELECT`, 0.90 for `STANDARD`,
        0.85 for `NO_ROLL`, and 0.97 for `UNGRADED`."
        PRD §3.4: "a lot seven days old or younger multiplies by 1.00"
        PRD §2.4: "a lot's `age_days` is the whole number of days between the
        logical clock date and the lot's `production_date`, rounded down; the
        production date itself is age zero."

        Design: Difficulty/combinatorial_formula/aging_value_grade_age_band_interaction
        """
        lot = self._setup()
        set_clock("2026-08-08T00:00:00Z")
        data = get_lot(lot["id"])
        assert data["age_days"] == 7
        assert data["status"] == "AVAILABLE"
        # 500 x 0.94 x 1.00, single rounding at the end
        assert data["unit_value_cents_per_lb"] == 470, (
            f"SELECT at age 7 must value at 470, got "
            f"{data['unit_value_cents_per_lb']}"
        )

    def test_age_band_two_boundary_value_at_eight_days(self, desk_admin_headers):
        """PRD §3.4: "from its eighth through its fourteenth day, inclusive, by
        0.95"
        PRD §3.4: "The value is the product of three factors, with a single
        rounding half-up to whole cents at the very end and no rounding of
        intermediate values."

        Design: Difficulty/combinatorial_formula/aging_value_grade_age_band_interaction
        """
        lot = self._setup()
        set_clock("2026-08-09T00:00:00Z")
        data = get_lot(lot["id"])
        assert data["age_days"] == 8
        assert data["status"] == "AVAILABLE"
        # round_half_up(500 x 0.94 x 0.95) = round_half_up(446.5)
        assert data["unit_value_cents_per_lb"] == 447, (
            f"SELECT at age 8 must value at 447, got "
            f"{data['unit_value_cents_per_lb']}"
        )


class TestCutoutMissingSheetLine:
    def test_missing_sheet_line_contributes_zero(self):
        """PRD §3.3: "if the selected sheet has no line for that output
        product, the specification contributes zero cents."

        Design: Corner/calculations/cutout_missing_sheet_line_contributes_zero
        """
        carc = create_carcass_product(product_code="CARC-Z")
        rib = create_product(product_code="RIBEYE-Z", max_fat_pct=12.0)
        chk = create_product(product_code="CHUCK-Z", max_fat_pct=18.0)
        create_yield_spec(carc["id"], rib["id"], 50.0, 45.0, 55.0)
        create_yield_spec(carc["id"], chk["id"], 50.0, 45.0, 55.0)
        supplier = create_supplier(establishment_number="EST-Z")
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], rib["id"], 900, 50_000)  # no CHUCK-Z line
        publish_sheet(s1["id"])

        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=1000,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-06", po_number="PO-Z")
        booked = get_po(po["id"])
        # 1000 x 0.50 x 900 = 450000; the CHUCK-Z spec has no sheet line -> 0
        assert booked["estimated_cutout_value_cents"] == 450_000, (
            f"only the RIBEYE-Z line contributes, got "
            f"{booked['estimated_cutout_value_cents']}"
        )
