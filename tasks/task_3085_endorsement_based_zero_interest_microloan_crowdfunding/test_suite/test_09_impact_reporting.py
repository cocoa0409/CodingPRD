"""Impact reporting and lender impact aggregation variants (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    assert_impact_report,
    create_trustee,
    make_borrower_headers,
    make_lender_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_TIMING_MISMATCH

ADMIN = TEST_USERS["admin_headers"]


def test_impact_report_wrong_months_rejected(api):
    """PRD §3.9: "The timing claim is verified:
    `months_after_disbursement` must equal the whole months actually elapsed
    since the loan's `disbursed_at`, or the filing is rejected with
    `ERR_TIMING_MISMATCH` (HTTP 409)."
    PRD §3.9: "computes `is_mid_term` — true when the report was filed no
    later than the whole-month midpoint of the loan's term (half of
    `term_months`, floored)."

    Design: Corner/validations/impact_report_wrong_months_rejected
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)

    # 2026-09-01 -> 2026-11-01 is two whole months elapsed.
    set_clock("2026-11-01T00:00:00Z")
    resp = client.create_impact_report(
        ns.loan["id"],
        {
            "months_after_disbursement": 3,
            "revenue_change_pct": 5,
            "jobs_created": 1,
            "narrative": "x",
        },
        make_borrower_headers(ns.borrower["id"]),
    )
    validate_error(resp, ERR_TIMING_MISMATCH, expected_status=409)

    report = validate_success(
        client.create_impact_report(
            ns.loan["id"],
            {
                "months_after_disbursement": 2,
                "revenue_change_pct": 5,
                "jobs_created": 1,
                "narrative": "x",
            },
            make_borrower_headers(ns.borrower["id"]),
        ),
        expected_status=201,
    )
    assert_impact_report(report)
    # term 3: floor(3/2) == 1, and month 2 is past the midpoint.
    assert report["is_mid_term"] is False


def test_impact_report_exact_month_boundary(api):
    """PRD §3.9: "`months_after_disbursement` must equal the whole months
    actually elapsed since the loan's `disbursed_at`, or the filing is
    rejected with `ERR_TIMING_MISMATCH` (HTTP 409)."

    Design: Corner/validations/impact_report_wrong_months_rejected
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)

    # Exactly two whole months after 2026-09-01: claiming 2 succeeds, and
    # month 2 is past the 3-month midpoint (floor(3/2) == 1).
    set_clock("2026-11-01T00:00:00Z")
    report = validate_success(
        client.create_impact_report(
            ns.loan["id"],
            {
                "months_after_disbursement": 2,
                "revenue_change_pct": 5,
                "jobs_created": 1,
                "narrative": "x",
            },
            make_borrower_headers(ns.borrower["id"]),
        ),
        expected_status=201,
    )
    assert report["is_mid_term"] is False

    resp = client.create_impact_report(
        ns.loan["id"],
        {
            "months_after_disbursement": 3,
            "revenue_change_pct": 5,
            "jobs_created": 1,
            "narrative": "x",
        },
        make_borrower_headers(ns.borrower["id"]),
    )
    validate_error(resp, ERR_TIMING_MISMATCH, expected_status=409)


def _funded_p_and_q():
    """Two trustee-vouched loans sharing lender KA.

    Loan P: principal 400000, term 4. KA endorses 75000 and contributes
    25000 (lent share 100000); LB and two other lenders endorse 50000 each;
    the trustee endorses 25000 (private 250000); LB contributes the closing
    125000.
    Loan Q: principal 1600000, term 4. KA endorses 100000 and contributes
    20000 (lent share 120000); LB endorses 200000 and contributes the closing
    780000; two more lenders endorse 200000 each; the trustee endorses
    100000 (private 800000).
    """
    trustee = create_trustee(
        org_name="Riverside Alliance", endorsement_limit_cents=10_000_000
    )
    ka = fx.create_lender(display_name="Kendra A", deposit_cents=1_000_000)
    lb = fx.create_lender(display_name="Lem B", deposit_cents=5_000_000)

    ns_p = fx.create_private_fundraising_application(
        trustee=trustee, requested_amount_cents=400_000, term_months=4
    )
    fx.endorse(ns_p.application, lb, 50_000)
    for _ in range(2):
        fx.endorse(ns_p.application, fx.create_lender(deposit_cents=500_000), 50_000)
    fx.trustee_endorse(ns_p.application, trustee, 25_000)
    fx.endorse(ns_p.application, ka, 75_000)
    app_p = fx.get_application(ns_p.application["id"])
    app_p = fx.open_public(app_p, ns_p.borrower)
    fx.contribute(app_p, ka, 25_000)
    fx.contribute(app_p, lb, 125_000)
    loan_p = fx.disburse(fx.get_application(app_p["id"]))

    ns_q = fx.create_private_fundraising_application(
        trustee=trustee, requested_amount_cents=1_600_000, term_months=4
    )
    fx.endorse(ns_q.application, lb, 200_000)
    for _ in range(2):
        fx.endorse(ns_q.application, fx.create_lender(deposit_cents=500_000), 200_000)
    fx.trustee_endorse(ns_q.application, trustee, 100_000)
    fx.endorse(ns_q.application, ka, 100_000)
    app_q = fx.get_application(ns_q.application["id"])
    app_q = fx.open_public(app_q, ns_q.borrower)
    fx.contribute(app_q, ka, 20_000)
    fx.contribute(app_q, lb, 780_000)
    loan_q = fx.disburse(fx.get_application(app_q["id"]))

    return ka, loan_p, ns_p, loan_q, ns_q


def test_impact_aggregation_flips_between_simple_and_weighted_variants(api):
    """PRD §3.9: "Two variants exist. When every candidate report is
    mid-term, the aggregation is a simple unweighted mean — each report
    counts equally and both figures are the average across reports, rounded
    half-up. Once any candidate report is past mid-term, the aggregation
    switches to principal-share weighting: each report is weighted by the
    lender's lent cents on that report's loan, and both figures are the
    weighted average across reports, rounded half-up."
    PRD §3.9: "computes `is_mid_term` — true when the report was filed no
    later than the whole-month midpoint of the loan's term (half of
    `term_months`, floored)."

    Design: Difficulty/dual_variant_calc/impact_report_simple_vs_principal_weighted
    """
    set_clock()
    ka, loan_p, ns_p, loan_q, ns_q = _funded_p_and_q()

    # Month 2: both reports mid-term (floor(4/2) == 2 >= 2).
    set_clock("2026-11-01T00:00:00Z")
    fx._data(
        client.create_impact_report(
            loan_p["id"],
            {
                "months_after_disbursement": 2,
                "revenue_change_pct": 10,
                "jobs_created": 4,
                "narrative": "Loom running",
            },
            make_borrower_headers(ns_p.borrower["id"]),
        ),
        "P month-2 report",
    )
    fx._data(
        client.create_impact_report(
            loan_q["id"],
            {
                "months_after_disbursement": 2,
                "revenue_change_pct": 20,
                "jobs_created": 12,
                "narrative": "First harvest",
            },
            make_borrower_headers(ns_q.borrower["id"]),
        ),
        "Q month-2 report",
    )

    # Month 3: a second Q report is past mid-term (3 > 2), which flips the
    # aggregation to principal-share weighting.
    set_clock("2026-12-01T00:00:00Z")
    q_late = validate_success(
        client.create_impact_report(
            loan_q["id"],
            {
                "months_after_disbursement": 3,
                "revenue_change_pct": 20,
                "jobs_created": 12,
                "narrative": "Second harvest",
            },
            make_borrower_headers(ns_q.borrower["id"]),
        ),
        expected_status=201,
    )
    assert q_late["is_mid_term"] is False

    impact = validate_success(
        client.get_lender_impact(ka["id"], make_lender_headers(ka["id"]))
    )
    assert impact["report_count"] == 3
    # KA lent 100000 on P and 120000 on Q; weights per report: P 100000,
    # Q 120000 (twice).
    # jobs: round_half_up((100000*4 + 120000*12 + 120000*12)/340000)
    #     = round_half_up(9.647...) = 10
    assert impact["jobs_created_weighted"] == 10
    # revenue: round_half_up((100000*10 + 120000*20 + 120000*20)/340000)
    #        = round_half_up(17.058...) = 17
    assert impact["revenue_change_pct_weighted"] == 17


def test_impact_aggregation_simple_mean_when_all_reports_mid_term(api):
    """PRD §3.9: "When every candidate report is mid-term, the aggregation
    is a simple unweighted mean — each report counts equally and both
    figures are the average across reports, rounded half-up."

    Design: Difficulty/dual_variant_calc/impact_report_simple_vs_principal_weighted
    """
    set_clock()
    ka, loan_p, ns_p, loan_q, ns_q = _funded_p_and_q()

    set_clock("2026-11-01T00:00:00Z")
    for loan, ns, jobs, revenue in (
        (loan_p, ns_p, 4, 10),
        (loan_q, ns_q, 12, 20),
    ):
        fx._data(
            client.create_impact_report(
                loan["id"],
                {
                    "months_after_disbursement": 2,
                    "revenue_change_pct": revenue,
                    "jobs_created": jobs,
                    "narrative": "update",
                },
                make_borrower_headers(ns.borrower["id"]),
            ),
            "mid-term report",
        )

    impact = validate_success(
        client.get_lender_impact(ka["id"], make_lender_headers(ka["id"]))
    )
    assert impact["report_count"] == 2
    # Unweighted mean over the two mid-term reports.
    assert impact["jobs_created_weighted"] == 8, "round_half_up((4+12)/2)"
    assert impact["revenue_change_pct_weighted"] == 15, "round_half_up((10+20)/2)"
