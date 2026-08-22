"""Audit reporting of credit balance liability and the closed-period separation rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_compliance_report,
    attribute,
    create_compliance_report_payload,
    create_report,
    post_txn,
    run_identify_sweep,
    seed_account,
    seed_payer,
    set_clock,
    start_review,
    validate_error,
    validate_paginated,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_closed_report_period_rejects_anything_inside_the_seven_day_buffer(api):
    """PRD §2.10: "A compliance report occupies a **closed** period with a mandatory buffer: the interval runs from `period_start_at` inclusive to `period_end_at` inclusive, and separation is enforced against every existing report — whether `DRAFT` or `FINALIZED` — that shares both the same `report_type` and the same `scope_code`."
    PRD §2.10: "The new report is acceptable only if its `period_start_at` is at or after the existing report's `period_end_at` plus seven days, or its `period_end_at` is at or before the existing report's `period_start_at` minus seven days. Because the interval is closed and a seven-day gap is required, **touching is rejected**: adjacency is forbidden, and anything closer than a full seven-day separation is rejected with `ERR_REPORT_PERIOD_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/compliance_report_closed_period_requires_seven_day_buffer_between_scopes
    """
    set_clock("2026-08-16T00:00:00Z")
    create_report(
        "CREDIT_BALANCE_LIABILITY", "ALL", "2026-07-01T00:00:00Z",
        "2026-07-31T00:00:00Z", "2026-08-16T00:00:00Z",
    )

    too_close = api.create_compliance_report(
        create_compliance_report_payload(
            "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-01T00:00:00Z",
            "2026-08-06T00:00:00Z", "2026-08-16T00:00:00Z",
        ),
        COMPLIANCE,
    )
    validate_error(too_close, ApiErrorId.ERR_REPORT_PERIOD_CONFLICT.value)

    exactly_seven_days_later = validate_success(
        api.create_compliance_report(
            create_compliance_report_payload(
                "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-07T00:00:00Z",
                "2026-08-14T00:00:00Z", "2026-08-16T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert exactly_seven_days_later["state"] == "DRAFT"


def test_report_period_separation_is_scoped_to_one_report_type(api):
    """PRD §2.10: "separation is enforced against every existing report — whether `DRAFT` or `FINALIZED` — that shares both the same `report_type` and the same `scope_code`."
    PRD §3.13: "The report is created in `state` `DRAFT` and stamped with the generating officer's `X-User-ID` as `generated_by_user_id`."

    Design: Difficulty/resource_temporal_overlap/compliance_report_closed_period_requires_seven_day_buffer_between_scopes
    """
    set_clock("2026-08-16T00:00:00Z")
    create_report(
        "CREDIT_BALANCE_LIABILITY", "ALL", "2026-07-01T00:00:00Z",
        "2026-07-31T00:00:00Z", "2026-08-16T00:00:00Z",
    )
    validate_error(
        api.create_compliance_report(
            create_compliance_report_payload(
                "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-01T00:00:00Z",
                "2026-08-06T00:00:00Z", "2026-08-16T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_REPORT_PERIOD_CONFLICT.value,
    )
    create_report(
        "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-07T00:00:00Z",
        "2026-08-14T00:00:00Z", "2026-08-16T00:00:00Z",
    )

    other_type = validate_success(
        api.create_compliance_report(
            create_compliance_report_payload(
                "MEDICARE_CBR", "ALL", "2026-08-01T00:00:00Z",
                "2026-08-06T00:00:00Z", "2026-08-16T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert other_type["report_type"] == "MEDICARE_CBR"

    _, meta = validate_paginated(
        api.list_compliance_reports(
            COMPLIANCE, params={"report_type": "CREDIT_BALANCE_LIABILITY"}
        )
    )
    assert meta["total_count"] == 2


def test_liability_report_totals_honour_the_scope_and_as_of_filters(api):
    """PRD §3.13: "A credit balance is included when its `identified_at` is at or before `as_of_at` — that bound is inclusive — its `status` is one of the four open-liability statuses `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` and `REFUND_PENDING`, and the scope matches: either `scope_code` is `ALL`, or the `payer_type` of the credit balance's payer equals `scope_code`."
    PRD §3.13: "From that population, `line_count` is the number of included rows; `total_liability_cents` is the sum of their `credit_amount_cents`; `patient_liability_cents` is the sum of their `patient_portion_cents`; and `payer_liability_cents` is the sum of their `payer_portion_cents`."
    PRD §3.13: "Finally `medicare_at_risk_cents` is the sum of `reportable_amount_cents` over the Medicare repayment obligations whose `state` is `OPEN` or `LATE`, whose `due_at` is at or before `as_of_at`, and whose credit balance is itself in the included population."

    Design: Corner/calculations/credit_balance_liability_report_totals_respect_scope_and_as_of_filters
    """
    set_clock("2026-08-01T00:00:00Z")
    medicare = seed_payer(payer_code="MCR", payer_type="MEDICARE",
                          name="Medicare Region A")
    commercial = seed_payer(payer_code="COM", payer_type="COMMERCIAL",
                            name="Meridian Commercial")
    account_a = seed_account(medicare["id"], account_number="ACCT-LR1",
                             financial_class="INPATIENT", patient_name="Lars Reed")
    account_b = seed_account(commercial["id"], account_number="ACCT-LR2",
                             state_code="TX", patient_name="Lia Reed")
    post_txn(account_a["id"], "CHARGE", 50_000, "SYSTEM")
    post_txn(account_b["id"], "CHARGE", 80_000, "SYSTEM")

    set_clock("2026-08-05T00:00:00Z")
    post_txn(account_a["id"], "PAYMENT", -62_000, "PAYER", payer_id=medicare["id"])
    post_txn(account_b["id"], "PAYMENT", -60_000, "PAYER", payer_id=commercial["id"])
    set_clock("2026-08-10T00:00:00Z")
    post_txn(account_b["id"], "PAYMENT", -40_000, "PATIENT")

    set_clock("2026-08-15T00:00:00Z")
    sweep = run_identify_sweep([account_a["id"], account_b["id"]])
    for credit_balance_id in sweep["credit_balance_ids"]:
        start_review(credit_balance_id)
        attribute(credit_balance_id, "PROPORTIONAL")

    set_clock("2026-08-16T00:00:00Z")
    all_scope = validate_success(
        api.create_compliance_report(
            create_compliance_report_payload(
                "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-01T00:00:00Z",
                "2026-08-16T00:00:00Z", "2026-08-16T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        201,
    )
    medicare_scope = validate_success(
        api.create_compliance_report(
            create_compliance_report_payload(
                "CREDIT_BALANCE_LIABILITY", "MEDICARE", "2026-08-01T00:00:00Z",
                "2026-08-16T00:00:00Z", "2026-08-16T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        201,
    )

    assert_compliance_report(all_scope)
    assert all_scope["line_count"] == 2
    assert all_scope["total_liability_cents"] == 32_000
    assert all_scope["patient_liability_cents"] == 8_000
    assert all_scope["payer_liability_cents"] == 24_000
    assert all_scope["over_180_count"] == 0
    assert all_scope["medicare_at_risk_cents"] == 0
    assert all_scope["state"] == "DRAFT"
    assert all_scope["generated_by_user_id"] == "comp-1"

    assert medicare_scope["line_count"] == 1
    assert medicare_scope["total_liability_cents"] == 12_000
    assert medicare_scope["patient_liability_cents"] == 0
    assert medicare_scope["payer_liability_cents"] == 12_000


def test_report_period_ending_after_the_valuation_instant_is_rejected(api):
    """PRD §3.13: "Ordering is enforced — `period_start_at` must be strictly before `period_end_at`, and `period_end_at` must be at or before `as_of_at`; a violation of either is `ERR_INVALID_PERIOD` (HTTP 422)"

    Design: Corner/validations/report_period_ending_after_as_of_is_rejected
    """
    response = api.create_compliance_report(
        create_compliance_report_payload(
            "ESCHEAT_HOLDER_REPORT", "CA", "2026-08-01T00:00:00Z",
            "2026-08-31T00:00:00Z", "2026-08-16T00:00:00Z",
        ),
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PERIOD.value)

    _, meta = validate_paginated(api.list_compliance_reports(COMPLIANCE))
    assert meta["total_count"] == 0
