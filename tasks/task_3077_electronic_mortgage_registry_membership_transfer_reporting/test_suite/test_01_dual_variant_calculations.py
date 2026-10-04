"""Dual-variant calculations: one set of inputs, two published figures.

The annual report publishes a count-based and an amount-weighted timeliness
rate side by side, and a QA review's discrepancy score freezes at issue while
a corrective re-review freezes a different value on re-issue.
"""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
    QA_SETTLER,
    add_finding,
    api_client,
    create_active_member,
    create_loan_payload,
    create_transfer_payload,
    get_success_data,
    issue_review,
    list_sanctions,
    make_member_rep_headers,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    read_loan,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_success,
)


def _report(api, member_id, year):
    return validate_success(
        api.create_annual_report(member_id, {"report_year": year}, ADMIN),
        expected_status=201,
    )


class TestReportingRateCountVsAmountWeighted:
    def test_late_large_loan_drags_amount_weighted_rate_below_count_rate(self, api):
        """PRD §3.6: "identical inputs can therefore legitimately yield different
        published rates (two on-time transfers out of three give 0.6667 by count
        but 0.5000 by amount when the late transfer carried the largest loan)."

        Design: Difficulty/dual_variant_calc/reporting_rate_count_vs_amount_weighted_diverge
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan1 = register_loan(a["id"], loan_amount_cents=100000000)
        loan2 = register_loan(a["id"], loan_amount_cents=200000000)
        loan3 = register_loan(a["id"], loan_amount_cents=300000000)

        # On-time report at the effective date itself.
        set_clock("2026-02-01T00:00:00Z")
        api.create_transfer(
            create_transfer_payload(
                loan1["id"], b["id"], loan1["version"],
                effective_date="2026-02-01T00:00:00Z", idempotency_key="k-rate-1",
            ),
            member_rep(a["id"]),
        )
        # Reported exactly on the tenth day after the effective date: on time.
        set_clock("2026-02-20T00:00:00Z")
        api.create_transfer(
            create_transfer_payload(
                loan2["id"], b["id"], loan2["version"],
                effective_date="2026-02-10T00:00:00Z", idempotency_key="k-rate-2",
            ),
            member_rep(a["id"]),
        )
        # The largest loan reported twenty days late (eleventh day onward is late).
        set_clock("2026-03-02T00:00:00Z")
        tr3 = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan3["id"], b["id"], loan3["version"],
                    effective_date="2026-02-10T00:00:00Z", idempotency_key="k-rate-3",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        set_clock("2026-12-31T00:00:00Z")
        report = _report(api, a["id"], 2026)

        assert report["reporting_rate"] == pytest.approx(0.6667), report
        assert report["reporting_rate_amount_weighted"] == pytest.approx(0.5000), report
        assert report["reporting_rate"] != report["reporting_rate_amount_weighted"]
        assert tr3["days_late"] == 10, tr3
        assert tr3["late_fee_cents"] == 25000, tr3
        assert report["open_exceptions"] == 3, report

    def test_all_on_time_transfers_publish_both_variants_at_one(self, api):
        """PRD §3.6: "`reporting_rate_amount_weighted` is the investor-materiality
        view of the same question, published alongside: the sum of `loan_amount_cents`
        over the on-time transferred loans divided by the sum over all transferred
        loans in the set, rounded half-up to four decimal places, again 1.0 when
        there were no confirmed transfers."

        Design: Difficulty/dual_variant_calc/reporting_rate_count_vs_amount_weighted_diverge
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan1 = register_loan(a["id"], loan_amount_cents=100000000)
        loan2 = register_loan(a["id"], loan_amount_cents=300000000)
        # Both transfers reported on the tenth day after the effective date.
        set_clock("2026-01-15T00:00:00Z")
        for i, loan in enumerate((loan1, loan2)):
            resp = api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key=f"k-ontime-{i}",
                ),
                member_rep(a["id"]),
            )
            tr = validate_success(resp, expected_status=201)
            assert tr["days_late"] == 0, tr

        report = _report(api, a["id"], 2026)
        assert report["reporting_rate"] == pytest.approx(1.0), report
        assert report["reporting_rate_amount_weighted"] == pytest.approx(1.0), report


class TestQaScoreFreezesAtIssue:
    def _gamma_with_two_loans(self):
        set_clock("2026-01-05T00:00:00Z")
        g = create_active_member(org_id="1000001", member_type="SERVICER",
                                 org_id_type="CHARTER_NUMBER")
        loan1 = register_loan(g["id"], loan_amount_cents=50000000)
        loan2 = register_loan(g["id"], loan_amount_cents=50000000)
        return g, loan1, loan2

    def test_reissue_after_corrective_reopen_freezes_a_new_score(self, api):
        """PRD §3.5: "A review that needs correction can be reopened —
        `FINDINGS_ISSUED` back to `DRAFT` — retaining its findings; the cycle may
        repeat, and each re-issue recomputes and refreezes `sample_size` and
        `discrepancy_score` afresh."
        PRD §3.5: "the findings are tallied by severity, with each `CRITICAL`
        finding contributing a full weight of 1.0, each `MAJOR` a half, and each
        `MINOR` a fifth; the weighted total is divided by the sample size and
        rounded half-up to four decimal places."

        Design: Difficulty/dual_variant_calc/qa_score_provisional_draft_vs_frozen_issue_diverge
        """
        g, loan1, loan2 = self._gamma_with_two_loans()
        review = open_review(g["id"])
        add_finding(review["id"], loan1["id"], field_name="CURRENT_SERVICER",
                    expected_value="1000001", actual_value="1000999", severity="MAJOR")
        add_finding(review["id"], loan2["id"], field_name="CURRENT_INVESTOR",
                    expected_value="1000001", actual_value="1000888", severity="MAJOR")

        issued = validate_success(
            api.issue_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        assert issued["sample_size"] == 2, issued
        # Two MAJOR findings: (0.5 + 0.5) / 2 = 0.5.
        assert issued["discrepancy_score"] == pytest.approx(0.5000), issued

        reopened = validate_success(
            api.reopen_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        assert reopened["status"] == "DRAFT", reopened

        add_finding(review["id"], loan1["id"], field_name="MIN",
                    expected_value="100000100000000014",
                    actual_value="100000100000000099", severity="CRITICAL")
        add_finding(review["id"], loan2["id"], field_name="CLOSING_DATE",
                    expected_value="2026-01-05", actual_value="2026-01-06",
                    severity="MINOR")

        reissued = validate_success(
            api.issue_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        assert reissued["sample_size"] == 2, reissued
        # (1*1.0 + 2*0.5 + 1*0.2) / 2 = 1.1 — the score is not capped at 1.0.
        assert reissued["discrepancy_score"] == pytest.approx(1.1000), reissued
        assert reissued["discrepancy_score"] != issued["discrepancy_score"]

    def test_first_issue_freezes_score_while_draft_keeps_accepting_findings(self, api):
        """PRD §3.5: "Issuing the review — moving it from `DRAFT` to
        `FINDINGS_ISSUED` — requires at least one finding (`ERR_NO_FINDINGS`) and
        freezes the review's two computed measures. `sample_size` is the count of
        loans in the sample at issue time."

        Design: Difficulty/dual_variant_calc/qa_score_provisional_draft_vs_frozen_issue_diverge
        """
        g, loan1, loan2 = self._gamma_with_two_loans()
        review = open_review(g["id"])
        add_finding(review["id"], loan1["id"], severity="MINOR")

        issued = validate_success(
            api.issue_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        # 1 MINOR finding over a two-loan sample: 0.2 / 2 = 0.1.
        assert issued["sample_size"] == 2, issued
        assert issued["discrepancy_score"] == pytest.approx(0.1000), issued

        # The frozen score is what a subsequent read returns.
        reread = validate_success(api.get_qa_review(review["id"], ADMIN))
        assert reread["discrepancy_score"] == pytest.approx(0.1000), reread
        assert reread["status"] == "FINDINGS_ISSUED", reread
