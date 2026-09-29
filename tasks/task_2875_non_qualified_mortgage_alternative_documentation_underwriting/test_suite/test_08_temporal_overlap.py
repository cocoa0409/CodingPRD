"""Two contended time resources: a worksheet's statement-month intervals and a
loan file's per-valuation-type re-order slot.

The first is sibling-interval exclusion on half-open intervals plus a lookback
window anchored on the logical clock; the second is a closed 30-day buffer
measured in whole days from one order's effective date to that same clock.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_STATEMENT_PERIOD_OUT_OF_WINDOW,
    ERR_STATEMENT_PERIOD_OVERLAP,
    ERR_VALUATION_REORDER_TOO_SOON,
)
from test_helpers.test_users import APPRAISAL_REVIEWER, underwriter

INVESTOR = "INV-ATLAS"


def _worksheet_with_one_april_month(api):
    """A 12-month bank-statement worksheet holding 2026-04-01 .. 2026-05-01.

    The logical clock is left at its declared default of ``2026-08-01T00:00:00Z``,
    so the lookback window opens at ``2024-08-01T00:00:00Z`` (twice the program's
    12 statement months, in whole months) and closes on the clock date itself.
    """
    program = fx.create_program(
        api, "BANK_STATEMENT_12MO", name="12-Month Bank Statement",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Tamsin Oyelaran", fico_score=715, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=120000,
        verified_liquid_assets_cents=4000000, age_years=46)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-15")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    current = fx.get_loan_file(api, loan_file["id"], uw)
    worksheet = fx.create_worksheet(api, loan_file["id"], "BANK_STATEMENT",
                                    current["version"], uw,
                                    expense_factor_source="PROGRAM_DEFAULT")
    april = fx.attach_statement_month(api, worksheet["id"],
                                      "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z",
                                      12222221, uw)
    return worksheet, april, uw


def _months(api, worksheet_id, uw):
    return validate_success(api.list_statement_months(worksheet_id, uw))


def test_a_month_ending_on_another_months_start_instant_is_adjacent_not_overlapping(api):
    """The interval is half-open, so sharing only the boundary instant is allowed.

    PRD 3.4: "Statement periods on one worksheet are treated as half-open intervals
    that include their start instant and exclude their end instant, and no two of them
    may share an interior day: a month ending on the exact start instant of another is
    adjacent and permitted, whereas any genuine interior overlap is refused with
    `ERR_STATEMENT_PERIOD_OVERLAP`". "At creation the month fixes
    `eligible_deposit_cents` as the gross deposits less the ineligible transfers,
    floored at zero".

    Design: Difficulty/resource_temporal_overlap/statement_month_half_open_interval_adjacency_and_lookback_window
    """
    worksheet, april, uw = _worksheet_with_one_april_month(api)

    may = fx.attach_statement_month(api, worksheet["id"], "2026-05-01T00:00:00Z",
                                    "2026-06-01T00:00:00Z", 12222221, uw)

    A.assert_money(may["eligible_deposit_cents"], 12222221, "eligible_deposit_cents")
    A.assert_fields(may, {"inclusion_status": "INCLUDED",
                          "worksheet_id": worksheet["id"]})
    A.assert_is_null(may, "exclusion_reason")

    # A period straddling the May boundary on both sides shares interior days.
    straddle = api.create_statement_month(
        worksheet["id"],
        {"period_start_date": "2026-05-15T00:00:00Z",
         "period_end_date": "2026-06-15T00:00:00Z", "deposits_total_cents": 9000000},
        uw)
    validate_error(straddle, ERR_STATEMENT_PERIOD_OVERLAP)

    # Ending exactly on a neighbour's start instant is not enough on its own: this
    # period's own start instant sits inside the April month.
    inside_april = api.create_statement_month(
        worksheet["id"],
        {"period_start_date": "2026-04-15T00:00:00Z",
         "period_end_date": "2026-05-01T00:00:00Z", "deposits_total_cents": 9000000},
        uw)
    validate_error(inside_april, ERR_STATEMENT_PERIOD_OVERLAP)

    assert len(_months(api, worksheet["id"], uw)) == 2


def test_an_excluded_month_still_occupies_its_interval_and_the_window_has_both_edges(api):
    """Exclusion frees no slot, and the lookback window is refused at either end.

    PRD 3.4: "both `INCLUDED` and `EXCLUDED` months occupy their interval for this
    purpose." "Separately, a month's period must end on or before the logical clock date
    and must start no earlier than twice the program's `statement_period_months`,
    counted in whole months, before that date; a period outside that lookback window is
    refused with `ERR_STATEMENT_PERIOD_OUT_OF_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/statement_month_half_open_interval_adjacency_and_lookback_window
    """
    worksheet, april, uw = _worksheet_with_one_april_month(api)
    may = fx.attach_statement_month(api, worksheet["id"], "2026-05-01T00:00:00Z",
                                    "2026-06-01T00:00:00Z", 12222221, uw)

    june = fx.attach_statement_month(api, worksheet["id"], "2026-06-01T00:00:00Z",
                                     "2026-07-01T00:00:00Z", 12500000, uw,
                                     ineligible_transfer_cents=277780)
    A.assert_money(june["eligible_deposit_cents"], 12222220, "eligible_deposit_cents")

    excluded = fx.exclude_statement_month(api, may["id"], uw,
                                          "Owner contribution, not business revenue")
    A.assert_fields(excluded, {"inclusion_status": "EXCLUDED",
                               "exclusion_reason":
                                   "Owner contribution, not business revenue"})

    refill = api.create_statement_month(
        worksheet["id"],
        {"period_start_date": "2026-05-01T00:00:00Z",
         "period_end_date": "2026-06-01T00:00:00Z", "deposits_total_cents": 11000000},
        uw)
    validate_error(refill, ERR_STATEMENT_PERIOD_OVERLAP)

    # 2024-06-01 starts before the 2024-08-01 opening of the 24-month lookback.
    too_old = api.create_statement_month(
        worksheet["id"],
        {"period_start_date": "2024-06-01T00:00:00Z",
         "period_end_date": "2024-07-01T00:00:00Z", "deposits_total_cents": 11000000},
        uw)
    validate_error(too_old, ERR_STATEMENT_PERIOD_OUT_OF_WINDOW)

    # This one ends 2026-09-01, past the 2026-08-01 clock date.
    not_yet_closed = api.create_statement_month(
        worksheet["id"],
        {"period_start_date": "2026-08-01T00:00:00Z",
         "period_end_date": "2026-09-01T00:00:00Z", "deposits_total_cents": 11000000},
        uw)
    validate_error(not_yet_closed, ERR_STATEMENT_PERIOD_OUT_OF_WINDOW)

    rows = {row["id"]: row for row in _months(api, worksheet["id"], uw)}
    assert len(rows) == 3, f"expected exactly three statement months, got {rows!r}"
    A.assert_fields(rows[april["id"]], {"inclusion_status": "INCLUDED"})
    A.assert_fields(rows[june["id"]], {"inclusion_status": "INCLUDED"})
    A.assert_fields(rows[may["id"]], {"inclusion_status": "EXCLUDED"})
    A.assert_money(rows[april["id"]]["eligible_deposit_cents"], 12222221,
                   "eligible_deposit_cents")
    A.assert_money(rows[june["id"]]["eligible_deposit_cents"], 12222220,
                   "eligible_deposit_cents")
    # The figure is fixed at creation, so exclusion does not rewrite it.
    A.assert_money(rows[may["id"]]["eligible_deposit_cents"], 12222221,
                   "eligible_deposit_cents")


def _file_with_a_july_primary_order(api):
    """A DSCR file whose only order is a PRIMARY_APPRAISAL effective 2026-07-01.

    The order is left in ``ORDERED``: never received, never rejected, so it holds
    its type's re-order slot for the whole 30-day buffer.
    """
    fx.set_clock(api, "2026-07-01T00:00:00Z", APPRAISAL_REVIEWER)
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Padstow Coast Holdings LLC", fico_score=752,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=3000000,
        age_years=51)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=40000000, property_value_cents=55000000,
        occupancy="INVESTMENT", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=9.250, apor_pct=6.100, term_months=360,
        amortization_type="INTEREST_ONLY", monthly_taxes_cents=60000,
        monthly_insurance_cents=18000, monthly_hoa_cents=15000,
        gross_market_rent_cents=420000, lease_rent_cents=480000)
    uw = underwriter("uw-16")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    primary = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                                 "2026-07-01T00:00:00Z", APPRAISAL_REVIEWER,
                                 vendor_code="VND-ALPHA")
    return loan_file, primary, uw


def test_day_thirty_is_still_inside_the_closed_buffer_but_only_for_its_own_type(api):
    """The buffer is closed at 30 whole days and scoped per ``valuation_type``.

    PRD 3.5: "the platform computes `validity_expires_date` as the effective date plus
    exactly 120 calendar days". "A replacement order of the same `valuation_type` may not
    be placed within 30 days of the `effective_date` of the most recent order of that
    type on the loan, measured as a closed interval in whole days on the logical clock,
    and a violation is refused with `ERR_VALUATION_REORDER_TOO_SOON`."

    Design: Difficulty/resource_temporal_overlap/valuation_reorder_buffer_closed_thirty_day_interval_per_type
    """
    loan_file, primary, uw = _file_with_a_july_primary_order(api)
    A.assert_instant_equals(primary["validity_expires_date"],
                            "2026-10-29T00:00:00Z", "validity_expires_date")
    A.assert_fields(primary, {"status": "ORDERED", "valuation_type": "PRIMARY_APPRAISAL"})
    A.assert_is_null(primary, "appraised_value_cents", "rejection_reason")

    # 2026-07-31 is exactly 30 whole days after 2026-07-01, and the interval is closed.
    fx.set_clock(api, "2026-07-31T00:00:00Z", APPRAISAL_REVIEWER)
    too_soon = api.create_valuation_order(
        {"loan_file_id": loan_file["id"], "valuation_type": "PRIMARY_APPRAISAL",
         "vendor_code": "VND-GAMMA", "effective_date": "2026-07-31T00:00:00Z"},
        APPRAISAL_REVIEWER)
    validate_error(too_soon, ERR_VALUATION_REORDER_TOO_SOON)

    # A different product has its own slot, untouched by the primary's buffer.
    desk = fx.order_valuation(api, loan_file["id"], "DESK_REVIEW",
                              "2026-07-31T00:00:00Z", APPRAISAL_REVIEWER,
                              vendor_code="VND-DESK")
    A.assert_fields(desk, {"status": "ORDERED", "valuation_type": "DESK_REVIEW"})
    A.assert_instant_equals(desk["validity_expires_date"], "2026-11-28T00:00:00Z",
                            "validity_expires_date")

    orders = validate_success(api.list_valuation_orders(loan_file["id"],
                                                        APPRAISAL_REVIEWER))
    assert len(orders) == 2, f"expected exactly two valuation orders, got {orders!r}"


def test_a_rejection_vacates_the_slot_and_day_thirty_one_leaves_the_buffer(api):
    """Rejection clears its own type immediately; the primary clears on day 31.

    PRD 3.5: "The buffer counts only orders that were not rejected: an order the
    reviewer rejected does not block its own replacement, so rejection effectively clears
    the buffer for that valuation type and a fresh order of the same type may follow
    immediately." "Orders of type `DESK_REVIEW` and `FIELD_REVIEW` move through the same
    order lifecycle but publish no value into either review dimension."

    Design: Difficulty/resource_temporal_overlap/valuation_reorder_buffer_closed_thirty_day_interval_per_type
    """
    loan_file, primary, uw = _file_with_a_july_primary_order(api)
    fx.set_clock(api, "2026-07-31T00:00:00Z", APPRAISAL_REVIEWER)
    desk = fx.order_valuation(api, loan_file["id"], "DESK_REVIEW",
                              "2026-07-31T00:00:00Z", APPRAISAL_REVIEWER,
                              vendor_code="VND-DESK")
    fx.receive_valuation(api, desk["id"], 54000000, APPRAISAL_REVIEWER)

    rejected = fx.reject_valuation(api, desk["id"], APPRAISAL_REVIEWER,
                                   "Unsupported adjustments")
    A.assert_fields(rejected, {"status": "REJECTED",
                               "rejection_reason": "Unsupported adjustments"})

    # A rejected desk review publishes no value, and the setup primary was never
    # received, so both review dimensions are still at their starting values.
    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_fields(review, {"primary_review_status": "PRIMARY_NOT_ORDERED",
                             "second_valuation_status": "SECOND_NOT_REQUIRED"})
    A.assert_is_null(review, "reconciled_value_cents", "primary_value_cents",
                     "second_value_cents", "variance_pct")

    # Same clock day as the rejected order: its slot is already free.
    replacement = fx.order_valuation(api, loan_file["id"], "DESK_REVIEW",
                                     "2026-07-31T00:00:00Z", APPRAISAL_REVIEWER,
                                     vendor_code="VND-DESK2")
    A.assert_fields(replacement, {"status": "ORDERED"})

    # 2026-08-01 is day 31 after the primary's 2026-07-01 effective date.
    fx.set_clock(api, "2026-08-01T00:00:00Z", APPRAISAL_REVIEWER)
    reordered = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                                   "2026-08-01T00:00:00Z", APPRAISAL_REVIEWER,
                                   vendor_code="VND-GAMMA")
    A.assert_fields(reordered, {"status": "ORDERED"})
    A.assert_instant_equals(reordered["validity_expires_date"],
                            "2026-11-29T00:00:00Z", "validity_expires_date")

    orders = validate_success(api.list_valuation_orders(loan_file["id"],
                                                        APPRAISAL_REVIEWER))
    assert len(orders) == 4, f"expected exactly four valuation orders, got {orders!r}"
    by_id = {row["id"]: row for row in orders}
    A.assert_fields(by_id[primary["id"]],
                    {"valuation_type": "PRIMARY_APPRAISAL", "status": "ORDERED"})
    A.assert_fields(by_id[reordered["id"]],
                    {"valuation_type": "PRIMARY_APPRAISAL", "status": "ORDERED"})
    A.assert_fields(by_id[desk["id"]],
                    {"valuation_type": "DESK_REVIEW", "status": "REJECTED"})
    A.assert_fields(by_id[replacement["id"]],
                    {"valuation_type": "DESK_REVIEW", "status": "ORDERED"})
