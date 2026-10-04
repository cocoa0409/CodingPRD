"""Corner queue — calculations: size-tier band edges (PRD §3.1), the 1095-day
rating window (PRD §3.6), the scam-pattern aggregation and sort (PRD §3.8),
and round-half-up at the prepaid dues total (PRD §2.9, §3.3)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    assert_scam_pattern_row,
    create_application,
    create_bureau,
    create_business,
    create_business_payload,
    create_consumer,
    create_rating_snapshot_payload,
    decide_application_payload,
    expected_dues_amount_cents,
    expected_installments,
    file_and_forward_complaint,
    file_scam_report,
    get_business,
    make_business_rep_headers,
    parse_iso,
    publish_scam_report,
    run_daily_close,
    set_clock,
    submit_application,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def test_size_tier_boundaries_map_employee_bands(api):
    """PRD §3.1: "Second, `size_tier` is computed from headcount: `MICRO` for
    1 to 4 employees, `SMALL` for 5 to 19 employees, `MEDIUM` for 20 to 99
    employees, and `LARGE` for 100 or more employees."

    Design: Corner/calculations/size_tier_boundaries_map_employee_bands
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    expected = {4: "MICRO", 5: "SMALL", 19: "SMALL", 20: "MEDIUM",
                99: "MEDIUM", 100: "LARGE"}
    for employees, tier in expected.items():
        resp = api.create_business(
            create_business_payload(legal_name=f"E{employees} LLC",
                                    employee_count=employees), ADMIN)
        data = validate_success(resp, 201)
        assert data["size_tier"] == tier, \
            f"employee_count {employees} must map to {tier}"


def test_rating_window_1095_days_excludes_stale_complaints(api):
    """PRD §3.6: "A snapshot stamps `computed_at` with the computation instant
    and sets `window_start_at` exactly 1095 days earlier: the rating window is
    the trailing 1095 days, inclusive at both ends, and only complaints with
    `filed_at` inside that window participate."
    PRD §3.6: "`unanswered_deduction` charges 12 points for each `UNANSWERED`
    complaint in the window, capped at 36 points."

    Design: Corner/calculations/rating_window_1095_days_excludes_stale_complaints
    """
    # The logical clock may move backward; start the old complaint in 2023.
    set_clock("2023-08-01T00:00:00Z")
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    stale = file_and_forward_complaint(consumer, business, category="SERVICE",
                                       description="stale")
    set_clock("2023-08-20T00:00:00Z")
    run_daily_close(bureau["id"])  # stale -> UNANSWERED in 2023
    # A fresh complaint inside the window computed at 2026-09-16.
    set_clock(CLOCK_START_ISO)
    file_and_forward_complaint(consumer, business, category="SERVICE",
                               description="fresh")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])  # fresh -> UNANSWERED

    resp = api.create_rating_snapshot(
        business["id"], create_rating_snapshot_payload("PUBLISHED"), ADMIN)
    snap = validate_success(resp, 201)
    assert parse_iso(snap["window_start_at"]) == parse_iso(
        "2023-09-17T00:00:00Z"), "2026-09-16 minus 1095 days"
    # The 2023-08-01 complaint is outside the window: only the fresh one
    # contributes its 12 points.
    assert snap["unanswered_deduction"] == 12
    assert snap["score"] == 88
    assert snap["grade"] == "B_PLUS"
    assert get_business(business["id"])["complaints_unanswered_36m"] == 1


def test_scam_patterns_sorted_count_desc_name_asc_with_flag(api):
    """PRD §3.8: "For each business, the system counts its `PUBLISHED` scam
    reports with `published_at` within the trailing 365 days; every business
    with at least 1 such report appears as a row carrying `business_id`,
    `legal_name`, `published_report_count_12m`, and a `pattern_flag` that is
    true when the count reaches 3 or more."
    PRD §3.8: "Rows sort by `published_report_count_12m` descending, with ties
    broken by `legal_name` ascending — never by id."

    Design: Corner/calculations/scam_patterns_sorted_count_desc_name_asc_with_flag
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")

    def business_with_reports(legal_name, report_count):
        business = create_business(legal_name=legal_name,
                                   home_state_code="IA", employee_count=2,
                                   founded_on="2020-01-01T00:00:00Z")
        for _ in range(report_count):
            publish_scam_report(file_scam_report(consumer, business))
        return business

    zulu = business_with_reports("Zulu Scam Co", 3)
    alpha = business_with_reports("Alpha Scam Co", 3)
    beta = business_with_reports("Beta One Co", 1)
    clean = business_with_reports("Clean Record Co", 0)

    resp = api.list_scam_patterns(ADMIN)
    patterns = validate_success(resp, 200)["patterns"]
    for row in patterns:
        assert_scam_pattern_row(row)
    assert [(p["business_id"], p["published_report_count_12m"],
             p["pattern_flag"]) for p in patterns] == [
        (alpha["id"], 3, True),   # name ASC breaks the count tie
        (zulu["id"], 3, True),
        (beta["id"], 1, False),
    ]
    assert clean["id"] not in {p["business_id"] for p in patterns}, \
        "a business with zero published reports does not appear"
    assert [p["legal_name"] for p in patterns] == [
        "Alpha Scam Co", "Zulu Scam Co", "Beta One Co"]


def test_prepaid_discount_half_cent_rounds_half_up(api):
    """PRD §2.9: "Where rounding is required, the system uses the
    round-half-up method, and rounding occurs only at the two pinned points of
    the dues computation described in §3.3: once at the plan total, and — for
    quarterly plans — once at the per-installment amount."
    PRD §3.3: "Under `ANNUAL_PREPAID`, the business earns a 5 percent prepay
    discount: the amount due is the subtotal multiplied by 0.95, rounded
    half-up to whole cents in a single rounding at the total, and
    `installments` holds exactly one entry — installment 1 — whose
    `amount_cents` is the full amount due."

    Design: Corner/calculations/prepaid_discount_half_cent_rounds_half_up
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Fee Fifty Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=50)
    business = create_business(legal_name="Half Cent Micro LLC",
                               home_state_code="IA", employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    app = create_application(business, billing_plan="ANNUAL_PREPAID")
    app = submit_application(app)
    decided = validate_success(api.decide_application(
        app["id"], decide_application_payload(), REVIEWER), 200)
    rows, _meta = validate_paginated(api.list_dues_invoices(
        business["id"], make_business_rep_headers(business["id"])))
    invoice = [r for r in rows if r["id"] == decided["dues_invoice_id"]][0]
    assert invoice["base_amount_cents"] == 42500
    assert invoice["local_fee_cents"] == 50
    # subtotal 42550 * 0.95 = 40422.5 -> round half up -> 40423.
    assert invoice["amount_due_cents"] == 40423
    assert invoice["amount_due_cents"] == expected_dues_amount_cents(
        "MICRO", 50, "ANNUAL_PREPAID")
    assert invoice["installments"] == expected_installments(
        "MICRO", 50, "ANNUAL_PREPAID")
