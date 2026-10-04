"""Corner coverage of the cross-cutting layers (the sanction ledger's
compensating write) and the immediate-consistency model."""
import pytest

from test_helpers import (
    ADMIN,
    QA_JUDGE,
    QA_SETTLER,
    add_finding,
    api_client,
    create_active_member,
    create_transfer_payload,
    issue_review,
    list_sanctions,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    register_loan,
    set_clock,
    settle_review,
    setup_two_member_pair,
    validate_success,
)


def test_vacated_sanction_zeroes_total_and_is_not_a_proven_prior(api):
    """PRD §3.5: "Vacating zeroes the total, a compensating write that keeps the
    sanction ledger consistent rather than deleting the record."
    PRD §3.5: "A repeat-offender multiplier is determined from the member's
    sanction history: if the member has any prior sanction in `UPHELD`,
    `REDUCED`, or `PAID` status — proven priors — the multiplier is 1.5;
    otherwise it is 1.0."

    Design: Corner/cross_cutting_layers/duplicate_report_without_force_and_vacated_sanction_zeroes_total
    """
    set_clock("2026-01-05T00:00:00Z")
    d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
    loan = register_loan(d["id"], loan_amount_cents=40000000)

    review1 = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                          period_end="2026-03-31T00:00:00Z")
    add_finding(review1["id"], loan["id"], field_name="PROPERTY_STATE",
                expected_value="TX", actual_value="TN", severity="MAJOR")
    issue_review(review1["id"])
    settle_review(review1["id"])
    sanc1 = list_sanctions(review_id=review1["id"])[0]

    validate_success(api.appeal_sanction(sanc1["id"], member_rep(d["id"])))
    vacated = validate_success(
        api.adjudicate_sanction(
            sanc1["id"], {"decision": "VACATED"}, make_qa_auditor_headers(QA_JUDGE)
        )
    )
    assert vacated["status"] == "VACATED", vacated
    assert vacated["total_amount_cents"] == 0, vacated

    # A vacated prior is not a proven prior: the next settle prices at base.
    review2 = open_review(d["id"], period_start="2026-04-01T00:00:00Z",
                          period_end="2026-06-30T00:00:00Z")
    add_finding(review2["id"], loan["id"], field_name="PROPERTY_STATE",
                expected_value="TX", actual_value="TN", severity="MAJOR")
    issue_review(review2["id"])
    settle_review(review2["id"], settler=QA_SETTLER)
    sanc2 = list_sanctions(review_id=review2["id"])[0]
    assert sanc2["total_amount_cents"] == 100000, sanc2
    assert sanc2["line_count"] == 1, sanc2


def test_transfer_effects_visible_in_same_request_response(api):
    """PRD §3.4: "On acceptance the transfer is born in `CONFIRMED` status
    (there is no pending state for the transfer itself), the rights move
    immediately — `current_investor_id` takes the receiving member for
    `BENEFICIAL` or `BOTH`, `current_servicer_id` for `SERVICING` or `BOTH` —
    and the loan's `version` advances by one with `updated_at` refreshed."
    PRD §3.4: "the logical clock and the `effective_date` are each truncated to
    their calendar day, the difference in days is taken, the reporting grace
    window of ten days is subtracted, and the result is floored at zero."

    Design: Corner/consistency_model/transfer_effects_visible_in_same_request_response
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    # Clock 2026-01-20 vs effective 2026-01-05: 15 calendar days apart, minus
    # the ten-day window -> 5 days late, 5 x 2500 = 12500.
    set_clock("2026-01-20T00:00:00Z")
    tr = validate_success(
        api.create_transfer(
            create_transfer_payload(
                loan["id"], b["id"], loan["version"],
                effective_date="2026-01-05T00:00:00Z", idempotency_key="k-imm-1",
            ),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )

    # No re-read needed: the create response already carries every effect.
    assert tr["status"] == "CONFIRMED", tr
    assert tr["from_member_id"] == a["id"], tr
    assert tr["to_member_id"] == b["id"], tr
    assert tr["days_late"] == 5, tr
    assert tr["late_fee_cents"] == 12500, tr
    assert tr["version"] == 1, tr
