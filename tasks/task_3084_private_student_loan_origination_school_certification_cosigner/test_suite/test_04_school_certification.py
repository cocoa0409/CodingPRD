"""School certification — the waterfall allocation and the cost-of-attendance ceiling."""
from test_helpers import (
    ERR_CERTIFICATION_LIMIT_EXCEEDED,
    TEST_USERS,
    approve,
    assert_certification,
    build_origination,
    certify_payload,
    file_and_certify,
    file_certification,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def test_waterfall_allocates_the_ceiling_in_arrival_order(api):
    """PRD §3.3: "The eligible children — those in `CERTIFIED` or `PARTIAL_CERTIFIED`
    status, excluded of anything `REJECTED` or `EXPIRED` — are then walked in
    ascending `certified_date` order, breaking ties by ascending `created_at`, and
    each child's certified amount is allocated against the remaining ceiling: each
    child keeps the lesser of its own certified amount and the remaining ceiling,
    and the ceiling is reduced by whatever that child was allocated."

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        application_overrides={
            "requested_amount_cents": 1000000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 80000,
            "interest_accrual_option": "INTEREST_ONLY",
        },
    )
    approve(orig)
    first = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=500000
    )
    second = file_certification(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=500000,
        period_end_date="2027-05-15T00:00:00Z",
    )

    certified_first = validate_success(
        client.certify(first["id"], certify_payload(certified_amount_cents=500000),
                       orig.school_headers)
    )
    assert certified_first["certified_amount_cents"] == 500000
    assert certified_first["certification_status"] == "CERTIFIED"
    assert_certification(certified_first)

    # The ceiling is 1000000 - 80000 = 920000, so the 500000 first child leaves
    # 420000 for the second in the pinned (certified_date, created_at) order.
    certified_second = validate_success(
        client.certify(second["id"], certify_payload(certified_amount_cents=500000),
                       orig.school_headers)
    )
    assert certified_second["certified_amount_cents"] == 420000
    assert certified_second["certification_status"] == "PARTIAL_CERTIFIED"


def test_waterfall_shortfall_moves_the_loan_certified_total_not_the_ceiling(api):
    """PRD §3.3: "The loan's `certified_amount_cents` is then the post-allocation sum
    of the children's certified amounts, and the loan's remaining headroom is the
    certified total minus the disbursed total, floored at zero."
    PRD §3.3: "When the sum of the requested certifications exceeds the ceiling, the
    *last* child in that ordered walk absorbs the shortfall, which is why a child in
    that position is recorded `PARTIAL_CERTIFIED`"

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        application_overrides={
            "requested_amount_cents": 1000000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 80000,
        },
    )
    approve(orig)
    first = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=500000
    )
    second = file_certification(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=500000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    get_success_data(client.certify(first["id"], certify_payload(certified_amount_cents=500000),
                                    orig.school_headers))
    get_success_data(client.certify(second["id"], certify_payload(certified_amount_cents=500000),
                                    orig.school_headers))

    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["certified_amount_cents"] == 920000, "500000 + 420000"
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 920000, "nothing disbursed yet"


def test_a_single_certification_may_not_exceed_the_application_ceiling(api):
    """PRD §3.3: "First, a single certification may never certify more than the
    application's `certified_limit_cents`; this is a standalone check on the
    certification's own amount, and an amount that would exceed the application's
    whole ceiling is refused with `ERR_CERTIFICATION_LIMIT_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        application_overrides={
            "requested_amount_cents": 1000000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 200000,
        },
    )
    approve(orig)
    certification = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=1000000
    )
    response = client.certify(
        certification["id"], certify_payload(certified_amount_cents=1000000),
        orig.school_headers,
    )
    validate_error(response, ERR_CERTIFICATION_LIMIT_EXCEEDED)


def test_aggregate_certified_total_counts_only_live_children(api):
    """PRD §3.3: "it recomputes the application's certified total over the
    non-rejected, non-expired children."
    PRD §2.10: "The loan's `certified_amount_cents` is the running total of its
    certifications in `CERTIFIED` or `PARTIAL_CERTIFIED` status"

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        application_overrides={
            "requested_amount_cents": 900000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    live = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    rejected = file_certification(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=300000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    get_success_data(
        client.reject_certification(rejected["id"], {"rejection_reason": "PROGRAM_INELIGIBLE"},
                                    orig.school_headers)
    )
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["certified_amount_cents"] == 400000, "the rejected sibling contributes nothing"
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 400000


def test_an_application_reverts_to_approved_once_every_certification_is_rejected(api):
    """PRD §3.3: "When every sibling certification on the application is `REJECTED`
    or `EXPIRED`, the application reverts from `SCHOOL_CERT_PENDING` to `APPROVED`."

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        application_overrides={
            "requested_amount_cents": 400000,
            "cost_of_attendance_cents": 480000,
            "other_aid_cents": 80000,
        },
    )
    approve(orig)
    first = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    second = file_certification(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=400000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    get_success_data(
        client.reject_certification(second["id"], {"rejection_reason": "COST_EXCEEDED"},
                                    orig.school_headers)
    )
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "SCHOOL_CERT_PENDING", "a live sibling still holds the state"

    get_success_data(
        client.reject_certification(first["id"], {"rejection_reason": "NOT_ENROLLED"},
                                    orig.school_headers)
    )
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "APPROVED"
    assert validate_success(
        client.get_certification(first["id"], TEST_USERS["school_headers"])
    )["certification_status"] == "REJECTED"


def test_certification_is_refused_when_the_school_is_inactive(api):
    """PRD §3.3: "Both outcomes are gated by the same set of conditions: the parent
    application must be `APPROVED` or `SCHOOL_CERT_PENDING`, the acting school must
    be the certification's own school, the school's `active` flag must be true"

    Design: Difficulty/combinatorial_formula/certified_limit_waterfall_allocation_order_pins_the_partial_period
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=795,
        school_overrides={"active": False},
        application_overrides={
            "requested_amount_cents": 400000,
            "cost_of_attendance_cents": 480000,
            "other_aid_cents": 80000,
        },
    )
    approve(orig)
    certification = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    response = client.certify(
        certification["id"], certify_payload(certified_amount_cents=400000),
        orig.school_headers,
    )
    from test_helpers import ERR_INVALID_STATE
    validate_error(response, ERR_INVALID_STATE)
    assert validate_success(
        client.get_certification(certification["id"], TEST_USERS["school_headers"])
    )["certification_status"] == "REQUESTED"