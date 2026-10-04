"""Difficulty queue — boundary precision (PRD §3.2, §3.6).

The inclusive 60-day appeal window (day 60 passes, day 61 fails) and the
at-least-available credit reservation boundary (exact fit passes, one
epsilon over fails).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    AppealStatus,
    CreditTxnStatus,
    assert_bank_inventory_conserved,
    create_appeal_payload,
    create_applicant,
    create_credit_transaction_payload,
    create_plan,
    create_site,
    create_and_issue_jd,
    file_appeal,
    iso_add_days,
    make_applicant_headers,
    reserve_credits,
    review_plan,
    set_clock,
    setup_aa_accepted,
    setup_operational_bank,
    submit_plan,
    validate_error,
    validate_success,
)


def test_appeal_window_exactly_sixty_days(api, reviewer_headers):
    """PRD §3.2: "the filing must fall inside the appeal window, meaning the
    gap between the filing clock and the determination's `issued_date` is at
    most 60 days — exactly 60 days is allowed, one day more is rejected with
    `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)".

    Both determinations issue at the 2026-09-01 startup clock: a filing at
    2026-10-31 (exactly 60 days) succeeds; a filing at 2026-11-01 (61 days)
    is rejected.

    Design: Difficulty/boundary_precision_check/appeal_window_exactly_sixty_days
    """
    applicant = create_applicant()
    site1 = create_site(applicant)
    jd1 = create_and_issue_jd(site1)
    site2 = create_site(
        applicant, site_name="Cedar Run Lot", watershed_code="18020102",
        total_acres=18.0, resource_types_present=["STREAM"],
    )
    jd2 = create_and_issue_jd(site2)
    issued = jd1["issued_date"]

    set_clock(iso_add_days(issued, 60))
    appeal = file_appeal(jd1, applicant, "Filed on day 60")
    assert appeal["status"] == AppealStatus.FILED.value, (
        "filing exactly 60 days after issuance succeeds (inclusive boundary)"
    )

    set_clock(iso_add_days(issued, 61))
    resp = api.create_appeal(
        create_appeal_payload(jd2["id"], grounds_text="Filed on day 61"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


def test_credit_inventory_exact_availability(api, reviewer_headers):
    """PRD §3.6: "the bank's `available_credits_by_type` for the resource
    type must be at least the requested credits, with exact equality allowed,
    else `ERR_INSUFFICIENT_CREDIT_INVENTORY` (HTTP 422)".

    Capacity 5: a 5.0-credit reservation succeeds (>= semantics) and drains
    availability to exactly 0.0; a further 0.5-credit reservation is
    rejected.

    Design: Difficulty/boundary_precision_check/credit_inventory_exact_availability
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank(capacity=5.0)

    txn = reserve_credits(bank, plan, applicant, credits=5.0)
    assert txn["status"] == CreditTxnStatus.RESERVED.value, (
        "requesting exactly the available 5.0 succeeds (>= semantics)"
    )

    resp = api.create_credit_transaction(
        create_credit_transaction_payload(
            bank["id"], plan["id"], resource_type="FORESTED_WETLAND", credits=0.5
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT_INVENTORY)

    bank_after = validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))
    assert bank_after["available_credits_by_type"]["FORESTED_WETLAND"] == pytest.approx(
        0.0, abs=1e-6
    ), "the exact-size reservation drained availability to zero"
    assert_bank_inventory_conserved(bank_after)
