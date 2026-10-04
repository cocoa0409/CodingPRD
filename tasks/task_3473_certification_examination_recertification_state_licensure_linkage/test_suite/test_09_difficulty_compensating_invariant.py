"""Queue A — compensating_invariant: a forward action consumes a conserved
quantity and the compensating action restores it (attempt budget restored by a
disciplinary void; credited CE hours restored by an audit rejection).
"""
from test_helpers import (
    advance_clock,
    api_client,
    assert_attempt_budget_invariant,
    audit_verdict,
    iso_days_after,
    open_case,
    record_audit_outcome,
    refresh_certification,
    refresh_case,
    refresh_completion_record,
    setup_audit_pending_recert,
    setup_candidate_with_consumed_attempts,
    walk_case_to_decided,
)
from test_helpers import get_success_data


def test_attempt_budget_void_restores(api):
    """PRD §3.3: "Two live counters summarize the budget: `attempts_consumed`,
    the number of delivered attempts booked against this basis (only
    `SCORED_PASS` and `SCORED_FAIL` count; `NO_SHOW` and `VOIDED` never do),
    and `attempts_remaining`, the hard cap of six minus that count."
    PRD §3.4: "When a disciplinary case finalizes with an exam-security
    violation implicating the attempt at sanction severity `SUSPENSION_12M` or
    higher, a scored attempt becomes `VOIDED`: `voided_by_case_id` is set,
    certifications whose `basis_attempt_id` names the attempt and that stand
    `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`, license applications in
    `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those certifications are
    `DENIED`, and — because `VOIDED` never counts toward `attempts_consumed` —
    the attempt budget is restored."

    Three failed deliveries consume 3 of 6; finalizing an exam-security case
    that implicates the second attempt voids it and restores exactly one unit.

    Design: Difficulty/compensating_invariant/attempt_budget_void_restores
    """
    ctx = setup_candidate_with_consumed_attempts(3)
    record_id = ctx["completion_record"]["id"]
    before = refresh_completion_record(record_id)
    assert before["attempts_consumed"] == 3
    assert before["attempts_remaining"] == 3
    assert_attempt_budget_invariant(before)

    case = open_case(
        ctx["candidate"]["id"], violation_type="EXAM_SECURITY",
        description="Attempt delivered with unauthorized assistance",
        implicated_attempt_ids=[ctx["attempts"][1]["id"]],
    )
    walk_case_to_decided(
        case["id"], ctx["candidate"]["id"],
        sanction_type="SUSPENSION_12M", findings="Security violation substantiated",
    )
    case_now = refresh_case(case["id"])
    sweep = advance_clock(iso_days_after(case_now["appeal_deadline"], 1))
    assert sweep["cases_finalized_count"] == 1

    voided = get_success_data(
        api_client.get_cognitive_exam_attempt(ctx["attempts"][1]["id"], ctx["candidate_headers"])
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_case_id"] == case["id"]

    after = refresh_completion_record(record_id)
    assert after["attempts_consumed"] == 2, (
        f"voiding the second attempt restores exactly one unit, got {after['attempts_consumed']}"
    )
    assert after["attempts_remaining"] == 4
    assert_attempt_budget_invariant(after)


def test_ce_audit_reject_restores_credited_total(api):
    """PRD §3.6: "`SINGLE_PROVIDER_CONCENTRATION` fires when the largest
    single-`provider_name` share of the application's entry hours reaches at
    least twenty hours."
    PRD §3.6: "The waterfall is then recomputed over the `VERIFIED` entries
    only. When sufficiency still holds — and the certification is still
    `ACTIVE` — the application is `APPROVED` with the same anniversary
    extension; when the surviving credits fall short, the application becomes
    `AUDIT_FAILED` and the certification is not extended."

    A 20-hour single-provider entry drives the portfolio into audit; rejecting
    exactly that entry recomputes the credited total to the remaining 20 hours
    — identical to a portfolio that never contained the entry.

    Design: Difficulty/compensating_invariant/ce_audit_reject_restores_credited_total
    """
    ctx = setup_audit_pending_recert()
    application = ctx["recert_application"]
    assert application["status"] == "AUDIT_PENDING"
    assert application["audit_selected"] is True
    assert "SINGLE_PROVIDER_CONCENTRATION" in application["audit_reasons"]
    assert application["total_credited_hours"] == 40, (
        "RECORDED entries credit 40 at submit time"
    )
    cert_before = refresh_certification(ctx["certification"]["id"])

    entries = ctx["entries"]  # [NATIONAL 20 MegaCE, LOCAL 10, INDIVIDUAL 10]
    outcome = record_audit_outcome(application["id"], [
        audit_verdict(entries[0]["id"], "REJECTED", reason="Provider could not produce rosters"),
        audit_verdict(entries[1]["id"], "VERIFIED"),
        audit_verdict(entries[2]["id"], "VERIFIED"),
    ])
    assert outcome["status"] == "AUDIT_FAILED", (
        f"national credited 0 < 20 over VERIFIED entries, got {outcome['status']}"
    )
    assert outcome["national_credited_hours"] == 0
    assert outcome["local_credited_hours"] == 10
    assert outcome["individual_credited_hours"] == 10
    assert outcome["total_credited_hours"] == 20

    cert_after = refresh_certification(ctx["certification"]["id"])
    assert cert_after["expires_on"] == cert_before["expires_on"], (
        "an audit-failed application does not extend the certification"
    )
    assert cert_after["renewed_count"] == 0
