"""Single-premium pricing: the financed annuity and the band movement it causes."""
import pytest

from prd_bench_local_runner.testing import validate_success, get_success_data

from test_helpers import (
    api_client, create_book, add_rate_card, submit_application, approve_delegated,
    issue_loan, UNDERWRITER,
)


def test_financing_the_single_premium_lifts_the_loan_into_a_higher_ltv_band():
    """PRD §3.3: "Where `financed_premium` is true, the premium is financed into
    the note and is therefore an annuity over the term: the coverage base is
    multiplied by the applied rate in basis points, divided by ten thousand,
    multiplied by the note term expressed in months divided by twelve, and
    multiplied by the present-value factor; the result is ceilinged to a whole
    cent."
    PRD §3.2: "financing a premium raises the ratio and can lift a loan into a
    higher band than the same base mortgage would have occupied with an
    un-financed premium. The ratio is carried to four decimal places, rounded
    half up, and the band comparison is made against that value."

    Design: Corner/calculations/single_premium_financed_note_raises_the_loan_to_value_band
    """
    book = create_book(rate_card_overrides={
        "premium_plan": "SPM", "ltv_band": "831_TO_85", "rate_bps": 128,
    })
    rc_90 = add_rate_card(book, premium_plan="SPM", ltv_band="851_TO_90", rate_bps=190)

    # Unfinanced: 34000000 on 40000000 is exactly 85.0000 percent.
    app_a = submit_application(book, borrower_reference="SPM-A", premium_plan="SPM",
                               borrower_paid=True, financed_premium=False,
                               term_months=120, rate_card_id=book["rate_card_id"])
    approve_delegated(book, app_a["id"])
    loan_a = get_success_data(api_client.get_loan(
        issue_loan(book, app_a["id"])["id"], UNDERWRITER))

    # Financed: the note includes the premium and moves to 86.5000 percent.
    app_b = submit_application(book, borrower_reference="SPM-B", premium_plan="SPM",
                               borrower_paid=True, financed_premium=True,
                               term_months=120, loan_amount_cents=34_600_000,
                               rate_card_id=rc_90["id"])
    approve_delegated(book, app_b["id"])
    loan_b = get_success_data(api_client.get_loan(
        issue_loan(book, app_b["id"])["id"], UNDERWRITER))

    assert loan_a["rate_bps_applied"] == 128
    assert loan_a["coverage_base_upb_cents"] == 8_500_000
    # Unfinanced: ceil(8500000 * 128 / 10000) = 108800.
    assert loan_a["single_premium_cents"] == 108_800

    assert loan_b["rate_bps_applied"] == 190
    assert loan_b["coverage_base_upb_cents"] == 8_650_000
    # Financed over a 120-month term: ceil(8650000 * 190 / 10000 * 10 * 0.92).
    assert loan_b["single_premium_cents"] == 1_512_020

    # The premium changed its own pricing basis.
    assert loan_a["rate_bps_applied"] != loan_b["rate_bps_applied"]


def test_the_unfinanced_single_premium_ceilings_the_plain_one_time_amount():
    """PRD §3.3: "Where `financed_premium` is false, the borrower pays a one-time
    premium computed as the plain single premium: the coverage base multiplied by
    the applied rate in basis points, divided by ten thousand, ceilinged to a
    whole cent."
    PRD §3.3: "the loan's `single_premium_cents` carries the result while
    remaining zero for `BPM` and `LPM` loans."

    Design: Corner/calculations/single_premium_financed_note_raises_the_loan_to_value_band
    """
    book = create_book()
    rc_spm = add_rate_card(book, premium_plan="SPM", rate_bps=128)

    app = submit_application(book, borrower_reference="SPM-U", premium_plan="SPM",
                             borrower_paid=True, financed_premium=False,
                             term_months=120, rate_card_id=rc_spm["id"])
    approve_delegated(book, app["id"])
    loan = get_success_data(api_client.get_loan(
        issue_loan(book, app["id"])["id"], UNDERWRITER))

    # ceil(8500000 * 128 / 10000) = ceil(108800) = 108800.
    assert loan["coverage_base_upb_cents"] == 8_500_000
    assert loan["single_premium_cents"] == 108_800

    # A BPM loan under the same policy carries no single premium.
    book_bpm = create_book()
    app_bpm = submit_application(book_bpm, borrower_reference="BPM-SP")
    approve_delegated(book_bpm, app_bpm["id"])
    loan_bpm = get_success_data(api_client.get_loan(
        issue_loan(book_bpm, app_bpm["id"])["id"], UNDERWRITER))
    assert loan_bpm["single_premium_cents"] == 0