"""Non-linear state machines: the dispute rework loop and Policy's parallel axes."""

from test_helpers import (
    TEST_USERS, class_code_entry, create_and_bind_policy, create_employer,
    dispute_under_review, get_policy, make_employer_admin_headers,
    make_role_headers, payroll_line, set_clock, setup_rating_table,
    sole_invoice_for_report, submit_report, validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]


def _cyclic_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Cyclic Cabinets Corp",
                               fein="44-5555666",
                               contact_email="risk@cyclic.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-CYC-004",
        class_codes=[class_code_entry("CA", "8810", 1000000)])
    return employer, policy


def test_dispute_review_can_return_to_filed_and_reopen(api):
    """PRD §3.6: "Review is a rework loop: the underwriter may return the dispute
    from UNDER_REVIEW to FILED and open it again as analysis proceeds."

    Design: Difficulty/non_linear_state_machine/dispute_review_rework_cycle_then_approval
    """
    employer, policy = _cyclic_policy()
    dispute, _v = dispute_under_review(policy["id"], employer["id"])
    assert dispute["status"] == "UNDER_REVIEW"

    back = validate_success(api.return_dispute_to_filed(dispute["id"], UW), 200)
    assert back["status"] == "FILED", "the cycle closes back to FILED"

    again = validate_success(api.open_dispute_review(dispute["id"], UW), 200)
    assert again["status"] == "UNDER_REVIEW", "the loop can be re-entered"


def test_dispute_rework_loop_terminates_in_approval_with_reassignment(api):
    """PRD §3.6: "An approval moves it to APPROVED and triggers the retroactive
    cascade: the disputed assignment becomes REASSIGNED; a new PolicyClassCode is
    created carrying the requested_class_code with assignment_status of ACTIVE and
    an effective_from equal to the dispute's effective_from".

    Design: Difficulty/non_linear_state_machine/dispute_review_rework_cycle_then_approval
    """
    employer, policy = _cyclic_policy()
    dispute, _v = dispute_under_review(policy["id"], employer["id"],
                                       requested_class_code="8812",
                                       effective_from="2026-09-01T00:00:00Z")
    validate_success(api.return_dispute_to_filed(dispute["id"], UW), 200)
    validate_success(api.open_dispute_review(dispute["id"], UW), 200)
    version = get_policy(policy["id"])["version"]

    decided = validate_success(api.decide_dispute(
        dispute["id"],
        {"decision": "APPROVED", "expected_policy_version": version},
        make_role_headers("uw-pat", "Underwriter")), 200)
    assert decided["status"] == "APPROVED"

    rows, _meta = validate_paginated(api.list_policy_class_codes(policy["id"], UW))
    by_status = {}
    for row in rows:
        by_status.setdefault(row["assignment_status"], []).append(row)
    assert len(by_status.get("REASSIGNED", [])) == 1
    assert by_status["REASSIGNED"][0]["class_code"] == "8810"
    new_active = [r for r in by_status.get("ACTIVE", [])
                  if r["class_code"] == "8812"]
    assert len(new_active) == 1
    assert new_active[0]["effective_from"] == "2026-09-01T00:00:00.000Z"


def _parallel_policy_with_invoice():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Parallel Packers Inc",
                               fein="55-6666777",
                               contact_email="ap@parallel.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-PAR-005", experience_mod=1.1,
        class_codes=[class_code_entry("CA", "8810", 1000000)])
    report = submit_report(policy["id"], "par-run-001",
                           lines=[payroll_line("CA", "8810",
                                               gross_wages_cents=10000000)])
    invoice = sole_invoice_for_report(policy["id"], report["id"])
    return employer, policy, invoice


def test_overdue_billing_leaves_coverage_active_and_reporting_compliant(api):
    """PRD §3.4: "The moment any ISSUED invoice passes its due_date unpaid,
    billing_status moves from CURRENT to OVERDUE."
    PRD §3.2: "A new policy's coverage_status is PENDING, while its
    reporting_status starts COMPLIANT, its billing_status starts CURRENT".

    Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_evolve_independently
    """
    _employer, policy, invoice = _parallel_policy_with_invoice()
    # Manual round(10000000 * 125 / 10000) = 125000; post-mod round(125000*1.1)
    # = 137500 >= threshold 10000 so no substitution; + 1*250 + 30000.
    assert invoice["total_cents"] == 167750

    # Invoice issued 09-01, due 09-08; at 09-10 it is past due and unpaid.
    set_clock("2026-09-10T00:00:00Z")
    now = get_policy(policy["id"])
    assert now["billing_status"] == "OVERDUE"
    assert now["coverage_status"] == "ACTIVE", (
        "the billing axis moved without touching coverage")
    assert now["reporting_status"] == "COMPLIANT", (
        "an accepted report keeps the reporting axis compliant")


def test_full_payment_returns_billing_to_current_without_touching_other_axes(api):
    """PRD §3.4: "when no unpaid ISSUED invoice remains, a policy in OVERDUE or
    SUSPENDED returns to CURRENT, and payroll submissions are accepted again."

    Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_evolve_independently
    """
    employer, policy, invoice = _parallel_policy_with_invoice()
    set_clock("2026-09-10T00:00:00Z")

    paid = validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": 167750},
        make_employer_admin_headers(employer["id"])), 200)
    assert paid["status"] == "PAID"

    now = get_policy(policy["id"])
    assert now["billing_status"] == "CURRENT"
    assert now["coverage_status"] == "ACTIVE"
    assert now["reporting_status"] == "COMPLIANT", (
        "the three axes evolved independently through the whole sequence")
