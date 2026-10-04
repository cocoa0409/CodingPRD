"""Non-linear state machines: the foreclosure rescind loop on loans and the
issue/reopen corrective loop on QA reviews."""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
    QA_SETTLER,
    add_finding,
    api_client,
    create_active_member,
    issue_review,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    register_loan,
    set_clock,
    validate_paginated,
    validate_success,
)


def _first_signer_id(api, member_id) -> str:
    rows, _ = validate_paginated(api.list_signers(member_id, ADMIN))
    assert len(rows) >= 1, "member must have at least one signer"
    return rows[0]["id"]


class TestForeclosureRescindCycle:
    def test_foreclose_rescind_foreclose_cycle_runs_twice(self, api):
        """PRD §3.3: "The cycle `ACTIVE` → `FORECLOSING` → `ACTIVE` may repeat
        any number of times, and each re-entry into foreclosure re-runs the full
        signer gate — an authority window valid at the first foreclosure may have
        closed by the second."

        Design: Difficulty/non_linear_state_machine/loan_foreclosure_rescind_cycle_on_registered_loan
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_active_member(org_id="1000000")
        signer_id = _first_signer_id(api, a["id"])
        loan = register_loan(a["id"], loan_amount_cents=75000000)

        first = validate_success(
            api.foreclose_loan(loan["id"], {"signer_id": signer_id}, member_rep(a["id"]))
        )
        assert first["status"] == "FORECLOSING", first

        rescinded = validate_success(
            api.rescind_foreclosure(loan["id"], member_rep(a["id"]))
        )
        assert rescinded["status"] == "ACTIVE", rescinded

        second = validate_success(
            api.foreclose_loan(loan["id"], {"signer_id": signer_id}, member_rep(a["id"]))
        )
        assert second["status"] == "FORECLOSING", second
        # Registration v1 -> foreclose v2 -> rescind v3 -> foreclose v4.
        assert second["version"] == loan["version"] + 3, (loan, second)

    def test_cycle_preserves_rights_and_registry_presence(self, api):
        """PRD §3.3: "While a loan is `FORECLOSING`, its current servicer or
        investor may rescind, returning it to `ACTIVE`; a rescission attempted
        against a loan that is not `FORECLOSING` fails with
        `ERR_LOAN_NOT_FORECLOSING`, and one attempted by a non-holder fails with
        `ERR_NOT_RIGHTS_HOLDER`."

        Design: Difficulty/non_linear_state_machine/loan_foreclosure_rescind_cycle_on_registered_loan
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_active_member(org_id="1000000")
        signer_id = _first_signer_id(api, a["id"])
        loan = register_loan(a["id"], loan_amount_cents=75000000)

        validate_success(
            api.foreclose_loan(loan["id"], {"signer_id": signer_id}, member_rep(a["id"]))
        )
        validate_success(
            api.rescind_foreclosure(loan["id"], member_rep(a["id"]))
        )

        validate_success(
            api.foreclose_loan(loan["id"], {"signer_id": signer_id}, member_rep(a["id"]))
        )
        validate_success(
            api.rescind_foreclosure(loan["id"], member_rep(a["id"]))
        )

        validate_success(
            api.foreclose_loan(loan["id"], {"signer_id": signer_id}, member_rep(a["id"]))
        )
        rescinded = validate_success(
            api.rescind_foreclosure(loan["id"], member_rep(a["id"]))
        )
        # The loop returns the loan to the registry with its holders intact.
        assert rescinded["status"] == "ACTIVE"
        assert rescinded["current_investor_id"] == a["id"]
        assert rescinded["current_servicer_id"] == a["id"]
        assert rescinded["assigned_out_at"] is None


class TestQaReviewIssueReopenCycle:
    def test_issue_reopen_issue_refreezes_score(self, api):
        """PRD §3.5: "A review that needs correction can be reopened —
        `FINDINGS_ISSUED` back to `DRAFT` — retaining its findings; the cycle may
        repeat, and each re-issue recomputes and refreezes `sample_size` and
        `discrepancy_score` afresh."

        Design: Difficulty/non_linear_state_machine/qa_review_issue_reopen_issue_cycle_on_qa_review
        """
        set_clock("2026-01-05T00:00:00Z")
        g = create_active_member(org_id="1000001", org_id_type="CHARTER_NUMBER")
        loan = register_loan(g["id"], loan_amount_cents=50000000)
        review = open_review(g["id"])
        add_finding(review["id"], loan["id"], severity="MINOR")
        issued = issue_review(review["id"])
        assert issued["status"] == "FINDINGS_ISSUED", issued
        assert issued["discrepancy_score"] == pytest.approx(0.2000), issued

        reopened = validate_success(
            api.reopen_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        assert reopened["status"] == "DRAFT", reopened

        reissued = validate_success(
            api.issue_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        assert reissued["status"] == "FINDINGS_ISSUED", reissued
        # 1 MINOR finding over a one-loan sample: 0.2 / 1 = 0.2.
        assert reissued["discrepancy_score"] == pytest.approx(0.2000), reissued

        # The cycle preserved terminal reachability: settle succeeds afterwards.
        settled = validate_success(
            api.settle_review(review["id"], {}, make_qa_auditor_headers(QA_SETTLER))
        )
        assert settled["status"] == "SETTLED", settled

    def test_reopened_review_accepts_new_findings_and_refreezes(self, api):
        """PRD §3.5: "Issue and reopen each advance the review's `version`."
        PRD §3.5: "the cycle may repeat, and each re-issue recomputes and
        refreezes `sample_size` and `discrepancy_score` afresh."

        Design: Difficulty/non_linear_state_machine/qa_review_issue_reopen_issue_cycle_on_qa_review
        """
        set_clock("2026-01-05T00:00:00Z")
        g = create_active_member(org_id="1000001", org_id_type="CHARTER_NUMBER")
        loan = register_loan(g["id"], loan_amount_cents=50000000)
        review = open_review(g["id"])
        add_finding(review["id"], loan["id"], severity="MINOR")
        issued = issue_review(review["id"])
        base_version = issued["version"]

        validate_success(api.reopen_review(review["id"], make_qa_auditor_headers(QA_CREATOR)))
        # While back in DRAFT, a further finding is accepted.
        add_finding(review["id"], loan["id"], field_name="PROPERTY_STATE",
                    expected_value="TX", actual_value="TN", severity="MAJOR")
        reissued = validate_success(
            api.issue_review(review["id"], make_qa_auditor_headers(QA_CREATOR))
        )
        # (0.2 + 0.5) / 1 = 0.7 after adding one MAJOR finding to the sample.
        assert reissued["discrepancy_score"] == pytest.approx(0.7000), reissued
        assert reissued["version"] == base_version + 2, (base_version, reissued)
