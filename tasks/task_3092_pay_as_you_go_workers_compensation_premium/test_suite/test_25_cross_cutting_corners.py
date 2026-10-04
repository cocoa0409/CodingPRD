"""Cross-cutting corners: policy version increments and immediate consistency."""

from test_helpers import (
    TEST_USERS, api_client, class_code_entry, create_employer, create_policy,
    get_policy, payroll_line, set_clock, setup_rating_table, submit_report,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_policy_version_increments_once_per_mutation(api):
    """PRD §2.4: "**`version` (integer):** a system-managed integer that increments
    with every mutation of the resource".
    PRD §3.3: "the policy's version increments."

    Design: Corner/cross_cutting_layers/occ_version_increments_on_every_policy_mutation
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_policy(employer["id"], policy_number="WC-VER-001",
                           class_codes=[class_code_entry("CA", "8810", 1000000)])
    v0 = policy["version"]

    validate_bind = api.bind_policy(policy["id"], UW)
    assert validate_bind.status_code == 200
    submit_report(policy["id"], "ver-run-1",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])

    final = get_policy(policy["id"])
    assert final["version"] == v0 + 2, (
        "bind (+1) and one accepted report (+1) move the version by exactly one "
        "increment per mutation")


def test_accepted_report_invoice_and_aggregates_visible_immediately(api):
    """PRD §2.8: "Issuing an invoice, voiding an invoice, and recording a payment
    each recompute the affected aggregates in the same transaction."
    PRD §3.3: "In the same transaction the system computes and issues a
    PremiumInvoice of kind PAYROLL."

    Design: Corner/consistency_model/immediate_consistency_invoice_visible_in_accept_response_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_policy(employer["id"], policy_number="WC-IMM-001",
                           class_codes=[class_code_entry("CA", "8810", 1000000)])
    assert api.bind_policy(policy["id"], UW).status_code == 200

    submit_report(policy["id"], "imm-run-1",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])

    # The very next read already sees the invoice and the recomputed aggregate:
    # round(10000000*125/10000)=125000 at mod 1.0 + 1*250 + 30000.
    now = get_policy(policy["id"])
    assert now["cumulative_billed_cents"] == 155250

    invoices, _meta = validate_paginated(
        api.list_policy_invoices(policy["id"], UW))
    assert len(invoices) == 1
    assert invoices[0]["kind"] == "PAYROLL"
    assert invoices[0]["status"] == "ISSUED"
