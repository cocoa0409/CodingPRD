"""Mortgage insurance premiums: LTV, vintage, UFMIP credit, annual billing,
cancellation."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_appraisal,
    bill_annual_mip,
    create_case,
    endorse_case,
    get_case,
    list_mip_entries,
    set_clock,
    setup_approved_lender,
    setup_endorsed_case,
    submit_case,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_lender_officer_headers,
    make_reviewer_headers,
    make_servicer_officer_headers,
)


# ---------------------------------------------------------------------------
# LTV and vintage
# ---------------------------------------------------------------------------
def test_ltv_bps_round_half_up_at_endorsement(api):
    """PRD §3.2: "computes `ltv_bps` as the base loan amount divided by the appraised
    value and multiplied by ten thousand, rounded half-up to an integer"

    Design: Corner/calculations/ltv_bps_round_half_up_at_endorsement
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "LTV Co"})
    case = create_case(
        lender["id"], borrower_reference="LTV-1",
        base_loan_amount_cents=30_000_001, appraised_value_cents=31_250_000,
    )
    attach_appraisal(case["id"], lender["id"], appraised_value_cents=31_250_000)
    submit_case(case["id"], lender["id"])
    endorsed = endorse_case(case["id"], reviewer="rev-1")
    assert endorsed["status"] == "ENDORSED"
    # 30,000,001 / 31,250,000 * 10,000 == 9,600.0032 -> rounds down to 9,600.
    assert endorsed["ltv_bps"] == 9600


def test_mip_vintage_boundary_at_2024_cutover(api):
    """PRD §3.2: "derives `mip_vintage` as `PRE_CUTOFF` when the endorsement date is
    before `2024-01-01T00:00:00Z` and `POST_CUTOFF` otherwise"

    Design: Corner/calculations/mip_vintage_boundary_at_2024_cutover
    """
    set_clock("2023-12-01T00:00:00Z")
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Vintage Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
        case_overrides={"borrower_reference": "VIN-1"},
        appraisal_overrides={"effective_date": "2023-11-01"},
    )
    assert case["status"] == "ENDORSED"
    assert case["mip_vintage"] == "PRE_CUTOFF"


# ---------------------------------------------------------------------------
# UFMIP refinance credit
# ---------------------------------------------------------------------------
def _endorse_case_with_appraisal(lender, borrower_reference, effective_date, **over):
    case = create_case(lender["id"], borrower_reference=borrower_reference, **over)
    attach_appraisal(
        case["id"], lender["id"],
        appraised_value_cents=over.get("appraised_value_cents", 31_250_000),
        effective_date=effective_date,
    )
    submit_case(case["id"], lender["id"])
    return endorse_case(case["id"], reviewer="rev-1")


def test_ufmip_refund_credit_at_month_one(api):
    """PRD §3.3: "If that count is at least 1 and at most 36, the refund percentage is
    the greater of 1,000 basis points and 8,000 basis points reduced by 200 basis
    points for each month beyond the first; the credit is the prior case's gross
    upfront premium — the `amount_cents` plus the `credit_cents` of the prior case's
    `UPFRONT` row, that is, the gross before any credit was taken — multiplied by that
    percentage and divided by ten thousand, rounded half-up to whole cents."
    PRD §3.3: "The new case's `UPFRONT` row then carries an `amount_cents` equal to its
    gross premium minus the credit, with the credit recorded in `credit_cents` and the
    rate of 175 in `rate_bps`."

    Design: Corner/calculations/ufmip_refund_credit_at_month_one
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Refi Co"})
    # Prior case endorsed at the 2026-09-01 startup clock: gross 525,000, no credit.
    prior = _endorse_case_with_appraisal(
        lender, "RF-OLD", "2026-07-01", base_loan_amount_cents=30_000_000,
    )
    # One complete month later: refund percentage is the 8,000 bps maximum tier.
    set_clock("2026-10-01T00:00:00Z")
    new_case = _endorse_case_with_appraisal(
        lender, "RF-NEW", "2026-09-01",
        base_loan_amount_cents=30_000_000, appraised_value_cents=33_000_000,
        refinance_of_case_id=prior["id"],
    )
    entries = list_mip_entries(new_case["id"])
    upfront = [e for e in entries if e["entry_type"] == "UPFRONT"][0]
    # credit = round_half_up(525,000 * 8,000 / 10,000) = 420,000.
    assert upfront["credit_cents"] == 420_000
    assert upfront["amount_cents"] == 525_000 - 420_000
    assert upfront["rate_bps"] == 175
    assert get_case(new_case["id"])["mip_retained_cents"] == 105_000


def test_ufmip_refund_credit_at_month_36_floor(api):
    """PRD §3.3: "If that count is at least 1 and at most 36, the refund percentage is
    the greater of 1,000 basis points and 8,000 basis points reduced by 200 basis
    points for each month beyond the first"

    Design: Corner/calculations/ufmip_refund_credit_at_month_36_floor
    """
    set_clock("2023-09-01T00:00:00Z")
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Refi Floor Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
    )
    prior = _endorse_case_with_appraisal(
        lender, "RF36-OLD", "2023-08-01", base_loan_amount_cents=30_000_000,
    )
    # Exactly 36 complete months later: 8,000 - 200*35 = 1,000 sits at the floor.
    set_clock("2026-09-01T00:00:00Z")
    new_case = _endorse_case_with_appraisal(
        lender, "RF36-NEW", "2026-08-01",
        base_loan_amount_cents=30_000_000, appraised_value_cents=33_000_000,
        refinance_of_case_id=prior["id"],
    )
    entries = list_mip_entries(new_case["id"])
    upfront = [e for e in entries if e["entry_type"] == "UPFRONT"][0]
    # credit = round_half_up(525,000 * 1,000 / 10,000) = 52,500.
    assert upfront["credit_cents"] == 52_500
    assert upfront["amount_cents"] == 525_000 - 52_500


def test_ufmip_no_credit_beyond_36_month_window(api):
    """PRD §3.3: "Outside the 36-month window the credit is zero."

    Design: Corner/calculations/ufmip_no_credit_beyond_36_month_window
    """
    set_clock("2023-08-01T00:00:00Z")
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Refi Late Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
    )
    prior = _endorse_case_with_appraisal(
        lender, "RF37-OLD", "2023-07-01", base_loan_amount_cents=30_000_000,
    )
    # 37 complete months later: outside the window, so no credit even though the
    # refinance reference is set.
    set_clock("2026-09-01T00:00:00Z")
    new_case = _endorse_case_with_appraisal(
        lender, "RF37-NEW", "2026-08-01",
        base_loan_amount_cents=30_000_000, appraised_value_cents=33_000_000,
        refinance_of_case_id=prior["id"],
    )
    entries = list_mip_entries(new_case["id"])
    upfront = [e for e in entries if e["entry_type"] == "UPFRONT"][0]
    assert upfront["credit_cents"] == 0
    assert upfront["amount_cents"] == 525_000


# ---------------------------------------------------------------------------
# Annual billing rates
# ---------------------------------------------------------------------------
def test_annual_bill_pre_cutoff_flat_55bps(api):
    """PRD §3.3: "For a `PRE_CUTOFF` case the annual amount is the current balance
    multiplied by 55 basis points and divided by ten thousand, rounded half-up."

    Design: Corner/calculations/annual_bill_pre_cutoff_flat_55bps
    """
    set_clock("2023-12-01T00:00:00Z")
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Pre Bill Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
        case_overrides={"borrower_reference": "PB-1"},
        appraisal_overrides={"effective_date": "2023-11-01"},
    )
    response = api_client.mip_event(
        case["id"],
        {"event_type": "ANNUAL_BILL", "current_balance_cents": 28_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["entry_type"] == "ANNUAL"
    assert data["period_index"] == 1
    assert data["rate_bps"] == 55
    # round_half_up(28,000,000 * 55 / 10,000) == 154,000.
    assert data["amount_cents"] == 154_000


def test_annual_bill_post_cutoff_mid_tier_55bps(api):
    """PRD §3.3: "For a `POST_CUTOFF` case the rate depends on the case's original
    `ltv_bps`: 50 basis points when the LTV is at most 9,000 basis points, 55 basis
    points when it is above 9,000 and at most 9,500, and 80 basis points above 9,500;
    the billed amount is again the current balance times the rate over ten thousand,
    rounded half-up."

    Design: Corner/calculations/annual_bill_post_cutoff_mid_tier_55bps
    """
    # ltv_bps = round_half_up(28,000,000 / 30,000,000 * 10,000) = 9,333 -> mid band.
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Mid Tier Co"},
        case_overrides={
            "borrower_reference": "MT-1",
            "base_loan_amount_cents": 28_000_000,
            "appraised_value_cents": 30_000_000,
        },
        appraisal_overrides={"appraised_value_cents": 30_000_000},
    )
    response = api_client.mip_event(
        case["id"],
        {"event_type": "ANNUAL_BILL", "current_balance_cents": 25_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["rate_bps"] == 55
    assert data["amount_cents"] == 137_500


def test_annual_bill_post_cutoff_high_tier_80bps(api):
    """PRD §3.3: "For a `POST_CUTOFF` case the rate depends on the case's original
    `ltv_bps`: 50 basis points when the LTV is at most 9,000 basis points, 55 basis
    points when it is above 9,000 and at most 9,500, and 80 basis points above 9,500"

    Design: Corner/calculations/annual_bill_post_cutoff_high_tier_80bps
    """
    # Standard case: ltv_bps = 9,600 -> high band.
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "High Tier Co"},
        case_overrides={"borrower_reference": "HT-1"},
    )
    response = api_client.mip_event(
        case["id"],
        {"event_type": "ANNUAL_BILL", "current_balance_cents": 25_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["rate_bps"] == 80
    # round_half_up(25,000,000 * 80 / 10,000) == 200,000.
    assert data["amount_cents"] == 200_000


def test_mip_ledger_entries_list_shows_upfront_after_endorsement(api):
    """PRD §3.3: "The gross upfront amount is the `base_loan_amount_cents` multiplied
    by 175 basis points — that is, by 175 and divided by ten thousand — rounded half-up
    to whole cents."
    PRD §3.3: "Each row has an `entry_type` of `UPFRONT`, `ANNUAL`, or `REFUND`; a
    `period_index` that is 0 for upfront rows and a 1-based annual period number for
    annual and refund rows; a signed `amount_cents` (positive for billed premiums,
    negative for refunds); a `credit_cents` field that defaults to 0; the `rate_bps`
    applied; and a `status` that starts at `BILLED` and can reach `CANCELLED`."

    Design: Corner/endpoints/mip_ledger_entries_list_shows_upfront_after_endorsement
    """
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Ledger Co"},
        case_overrides={"borrower_reference": "LED-1"},
    )
    data, meta = validate_paginated(
        api_client.list_mip_ledger_entries(case["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1
    entry = data[0]
    assert entry["entry_type"] == "UPFRONT"
    assert entry["period_index"] == 0
    # round_half_up(30,000,000 * 175 / 10,000) == 525,000.
    assert entry["amount_cents"] == 525_000
    assert entry["rate_bps"] == 175
    assert entry["status"] == "BILLED"


# ---------------------------------------------------------------------------
# Vintage cancellation
# ---------------------------------------------------------------------------
def _setup_pre_cutoff_case_with_bills(api, legal_name, borrower_reference,
                                      appraised_value_cents=31_250_000, bills=0,
                                      bill_balance=28_000_000):
    """PRE_CUTOFF endorsed case at clock 2023-12-01 with `bills` annual premiums."""
    set_clock("2023-12-01T00:00:00Z")
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": legal_name},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
        case_overrides={
            "borrower_reference": borrower_reference,
            "appraised_value_cents": appraised_value_cents,
        },
        appraisal_overrides={
            "effective_date": "2023-11-01",
            "appraised_value_cents": appraised_value_cents,
        },
    )
    for _ in range(bills):
        bill_annual_mip(case["id"], lender["id"], bill_balance)
    return lender, case


def test_error_mip_cancellation_ineligible_pre_cutoff_age(api):
    """PRD §3.3: "For a `PRE_CUTOFF` case, cancellation is permitted only when the
    `current_balance_cents` is at most 78 percent of the original
    `appraised_value_cents` — computed as the appraised value multiplied by 7,800 and
    divided by ten thousand, rounded half-up — and the endorsement is at least 60
    complete calendar months old; otherwise the request is rejected with
    `ERR_MIP_CANCELLATION_INELIGIBLE`."

    Design: Corner/errors/error_mip_cancellation_ineligible_pre_cutoff_age
    """
    lender, case = _setup_pre_cutoff_case_with_bills(
        api, "MIP Age Co", "MA-1"
    )
    # 59 complete months: one short of the 60-month minimum.
    set_clock("2028-11-01T00:00:00Z")
    # Balance 24,000,000 is within the 78% cap (24,375,000), so only age can fail.
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 24_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MIP_CANCELLATION_INELIGIBLE)
    assert get_case(case["id"])["mip_cancelled"] is False


def test_error_mip_cancellation_ineligible_pre_cutoff_balance(api):
    """PRD §3.3: "For a `PRE_CUTOFF` case, cancellation is permitted only when the
    `current_balance_cents` is at most 78 percent of the original
    `appraised_value_cents` — computed as the appraised value multiplied by 7,800 and
    divided by ten thousand, rounded half-up — and the endorsement is at least 60
    complete calendar months old; otherwise the request is rejected with
    `ERR_MIP_CANCELLATION_INELIGIBLE`."

    Design: Corner/errors/error_mip_cancellation_ineligible_pre_cutoff_balance
    """
    lender, case = _setup_pre_cutoff_case_with_bills(
        api, "MIP Bal Co", "MB-1"
    )
    # 61 complete months: age passes; balance 24,375,001 is one cent over the
    # 78% cap round_half_up(31,250,000 * 7,800 / 10,000) == 24,375,000.
    set_clock("2029-01-01T00:00:00Z")
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 24_375_001},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MIP_CANCELLATION_INELIGIBLE)


def test_error_vintage_life_of_loan(api):
    """PRD §3.3: "For a `POST_CUTOFF` case whose original LTV exceeded 9,000 basis
    points, the premium runs for the life of the loan and cancellation is always
    rejected with `ERR_VINTAGE_LIFE_OF_LOAN`"

    Design: Corner/errors/error_vintage_life_of_loan
    """
    # Standard case: ltv_bps 9,600 > 9,000 -> never cancellable.
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Life Of Loan Co"},
        case_overrides={"borrower_reference": "LL-1"},
    )
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 1_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VINTAGE_LIFE_OF_LOAN)


def test_mip_cancel_success_posts_prorated_refund(api):
    """PRD §3.3: "The current annual period index is the endorsement age in months
    divided by 12, rounded down, plus 1; the months already consumed in that period are
    the age in months minus 12 times one less than the period index; and the unused
    months are 12 minus the consumed count. The refund is the `amount_cents` of the
    case's `ANNUAL` row for that period in `BILLED` status, multiplied by the unused
    months and divided by 12, rounded half-up to whole cents. A `REFUND` row carrying
    the negated refund amount is created for that period, and the case's
    `mip_cancelled` flag is set to true, reducing `mip_retained_cents` per the
    summation invariant above."

    Design: Corner/errors/mip_cancel_success_posts_prorated_refund
    """
    # PRE_CUTOFF case endorsed 2023-12-01 with six annual bills of 154,000 (periods
    # 1..6, so the period-6 row the refund reads actually exists).
    lender, case = _setup_pre_cutoff_case_with_bills(
        api, "Refund Co", "RFD-1", bills=6, bill_balance=28_000_000
    )
    # 61 complete months: period 6, 1 month consumed, 11 unused.
    set_clock("2029-01-01T00:00:00Z")
    # Balance 24,000,000 <= 24,375,000 cap and age 61 >= 60: cancellation passes.
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 24_000_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["entry_type"] == "REFUND"
    assert data["period_index"] == 6
    # refund = round_half_up(154,000 * 11 / 12) == 141,167; the row is negated.
    assert data["amount_cents"] == -141_167
    case_after = get_case(case["id"])
    assert case_after["mip_cancelled"] is True
    # 525,000 UPFRONT + 6 * 154,000 ANNUAL - 141,167 REFUND == 1,307,833.
    assert case_after["mip_retained_cents"] == 1_307_833


# ---------------------------------------------------------------------------
# Difficulty: vintage dual-variant divergence on identical loan amounts
# ---------------------------------------------------------------------------
def _setup_two_vintage_cases(api):
    """One lender, two identical cases (base 30,000,000 / appraised 40,000,000,
    LTV 7,500 bps): case A endorsed 2023-06-01 (PRE_CUTOFF) and billed; case B
    endorsed 2024-06-01 (POST_CUTOFF). Returns (lender, case_a, bill_a, case_b)."""
    set_clock("2023-06-01T00:00:00Z")
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Meridian Home Lending"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
    )
    lid = lender["id"]
    case_a = _endorse_case_with_appraisal(
        lender, "BOR-A", "2023-05-15",
        base_loan_amount_cents=30_000_000, appraised_value_cents=40_000_000,
    )
    bill_a = bill_annual_mip(case_a["id"], lid, 30_000_000)
    set_clock("2024-06-01T00:00:00Z")
    case_b = _endorse_case_with_appraisal(
        lender, "BOR-B", "2024-05-15",
        base_loan_amount_cents=30_000_000, appraised_value_cents=40_000_000,
    )
    return lender, case_a, bill_a, case_b


def test_vintage_divergence_pre_cutoff_leg(api):
    """PRD §3.2: "derives `mip_vintage` as `PRE_CUTOFF` when the endorsement date is
    before `2024-01-01T00:00:00Z` and `POST_CUTOFF` otherwise"
    PRD §3.3: "For a `PRE_CUTOFF` case the annual amount is the current balance
    multiplied by 55 basis points and divided by ten thousand, rounded half-up."

    Design: Difficulty/dual_variant_calc/annual_mip_rate_diverges_by_vintage_for_identical_loan_amounts
    """
    _lender, case_a, bill_a, _case_b = _setup_two_vintage_cases(api)
    assert get_case(case_a["id"])["mip_vintage"] == "PRE_CUTOFF"
    # 30,000,000 * 55 / 10,000 == 165,000.
    assert bill_a["entry_type"] == "ANNUAL"
    assert bill_a["amount_cents"] == 165_000
    assert bill_a["rate_bps"] == 55


def test_vintage_divergence_post_cutoff_leg(api):
    """PRD §3.3: "For a `POST_CUTOFF` case the rate depends on the case's original
    `ltv_bps`: 50 basis points when the LTV is at most 9,000 basis points, 55 basis
    points when it is above 9,000 and at most 9,500, and 80 basis points above 9,500"

    Design: Difficulty/dual_variant_calc/annual_mip_rate_diverges_by_vintage_for_identical_loan_amounts
    """
    lender, case_a, bill_a, case_b = _setup_two_vintage_cases(api)
    assert get_case(case_b["id"])["mip_vintage"] == "POST_CUTOFF"
    bill_b = bill_annual_mip(case_b["id"], lender["id"], 30_000_000)
    # LTV 7,500 bps <= 9,000 -> 50 bps: 30,000,000 * 50 / 10,000 == 150,000.
    assert bill_b["amount_cents"] == 150_000
    assert bill_b["rate_bps"] == 50
    # Identical loan amounts diverge purely by vintage.
    assert bill_a["amount_cents"] != bill_b["amount_cents"]


# ---------------------------------------------------------------------------
# Difficulty: tiered UFMIP refinance credit
# ---------------------------------------------------------------------------
def _setup_tiered_credit_cases(api):
    """Prior case (base 2,000,000 -> gross UFMIP 35,000) endorsed 2023-06-01; the
    refinance (base 3,000,000) is prepared and endorsed 2024-01-15, seven complete
    months later -> refund percentage 8,000 - 200*6 == 6,800 bps."""
    set_clock("2023-06-01T00:00:00Z")
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Tiered Refi Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
    )
    prior = _endorse_case_with_appraisal(
        lender, "BOR-REFI-A", "2023-05-15",
        base_loan_amount_cents=2_000_000, appraised_value_cents=2_200_000,
    )
    set_clock("2024-01-15T00:00:00Z")
    new_case = _endorse_case_with_appraisal(
        lender, "BOR-REFI-B", "2024-01-02",
        base_loan_amount_cents=3_000_000, appraised_value_cents=3_300_000,
        refinance_of_case_id=prior["id"],
    )
    return lender, prior, new_case


def test_ufmip_tiered_credit_on_refinance_entry(api):
    """PRD §3.3: "If that count is at least 1 and at most 36, the refund percentage is
    the greater of 1,000 basis points and 8,000 basis points reduced by 200 basis
    points for each month beyond the first; the credit is the prior case's gross
    upfront premium — the `amount_cents` plus the `credit_cents` of the prior case's
    `UPFRONT` row, that is, the gross before any credit was taken — multiplied by that
    percentage and divided by ten thousand, rounded half-up to whole cents."
    PRD §3.3: "The new case's `UPFRONT` row then carries an `amount_cents` equal to its
    gross premium minus the credit, with the credit recorded in `credit_cents` and the
    rate of 175 in `rate_bps`."

    Design: Difficulty/combinatorial_formula/ufmip_refund_credit_tiered_on_elapsed_months
    """
    _lender, _prior, new_case = _setup_tiered_credit_cases(api)
    upfront = [e for e in list_mip_entries(new_case["id"]) if e["entry_type"] == "UPFRONT"][0]
    # Seven months elapsed -> 6,800 bps tier; credit = round_half_up(35,000 * 0.68).
    assert upfront["entry_type"] == "UPFRONT"
    assert upfront["credit_cents"] == 23_800
    # gross round_half_up(3,000,000 * 175 / 10,000) = 52,500; amount = 52,500 - 23,800.
    assert upfront["amount_cents"] == 28_700
    assert upfront["rate_bps"] == 175


def test_ufmip_tiered_credit_prior_case_ungredited(api):
    """PRD §3.3: "The gross upfront amount is the `base_loan_amount_cents` multiplied
    by 175 basis points — that is, by 175 and divided by ten thousand — rounded half-up
    to whole cents."
    PRD §3.3: "The case's `mip_retained_cents` is at all times the sum of `amount_cents`
    over the case's ledger rows whose status is not `CANCELLED`"

    Design: Difficulty/combinatorial_formula/ufmip_refund_credit_tiered_on_elapsed_months
    """
    _lender, prior, new_case = _setup_tiered_credit_cases(api)
    prior_upfront = [e for e in list_mip_entries(prior["id"]) if e["entry_type"] == "UPFRONT"][0]
    # The non-refinance prior carries its gross premium and no credit.
    assert prior_upfront["amount_cents"] == 35_000
    assert prior_upfront["credit_cents"] == 0
    # The new case retains exactly its net upfront amount.
    assert get_case(new_case["id"])["mip_retained_cents"] == 28_700


# ---------------------------------------------------------------------------
# Difficulty: MIP cancellation at the exact 78 percent boundary
# ---------------------------------------------------------------------------
def _setup_78pct_case(api):
    """PRE_CUTOFF case (endorsed 2023-06-01, appraised 32,000,000 -> 78% cap is
    24,960,000) with six annual bills of 165,000 (periods 1..6)."""
    set_clock("2023-06-01T00:00:00Z")
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Boundary Cancel Co"},
        filing_overrides={"fiscal_year_end": "2022-12-31"},
        case_overrides={
            "borrower_reference": "BOR-PRE",
            "base_loan_amount_cents": 30_000_000,
            "appraised_value_cents": 32_000_000,
        },
        appraisal_overrides={
            "effective_date": "2023-05-15",
            "appraised_value_cents": 32_000_000,
        },
    )
    for _ in range(6):
        bill_annual_mip(case["id"], lender["id"], 30_000_000)
    # 62 complete months: age passes; period 6, 2 months consumed, 10 unused.
    set_clock("2028-08-01T00:00:00Z")
    return lender, case


def test_mip_cancel_one_cent_over_78_percent_rejected(api):
    """PRD §3.3: "For a `PRE_CUTOFF` case, cancellation is permitted only when the
    `current_balance_cents` is at most 78 percent of the original
    `appraised_value_cents` — computed as the appraised value multiplied by 7,800 and
    divided by ten thousand, rounded half-up — and the endorsement is at least 60
    complete calendar months old; otherwise the request is rejected with
    `ERR_MIP_CANCELLATION_INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/mip_cancel_at_exactly_78_percent_balance
    """
    lender, case = _setup_78pct_case(api)
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 24_960_001},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MIP_CANCELLATION_INELIGIBLE)
    assert get_case(case["id"])["mip_cancelled"] is False


def test_mip_cancel_at_exactly_78_percent_succeeds(api):
    """PRD §3.3: "cancellation is permitted only when the `current_balance_cents` is at
    most 78 percent of the original `appraised_value_cents`"
    PRD §3.3: "A `REFUND` row carrying the negated refund amount is created for that
    period, and the case's `mip_cancelled` flag is set to true, reducing
    `mip_retained_cents` per the summation invariant above."

    Design: Difficulty/boundary_precision_check/mip_cancel_at_exactly_78_percent_balance
    """
    lender, case = _setup_78pct_case(api)
    response = api_client.mip_event(
        case["id"],
        {"event_type": "CANCEL", "current_balance_cents": 24_960_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["entry_type"] == "REFUND"
    # 62 months old: period 6, 10 unused months; refund = round(165,000 * 10 / 12).
    assert data["period_index"] == 6
    assert data["amount_cents"] == -137_500
    case_after = get_case(case["id"])
    assert case_after["mip_cancelled"] is True
    # 525,000 UPFRONT + 6 * 165,000 ANNUAL - 137,500 REFUND == 1,377,500.
    assert case_after["mip_retained_cents"] == 1_377_500


