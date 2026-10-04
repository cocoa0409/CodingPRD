"""Priority-pair conflicts: when two rules each independently reject a request,
the PRD's fixed cascade decides which failure is reported."""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
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
    read_loan,
    register_loan,
    set_clock,
    settle_review,
    setup_two_member_pair,
    validate_error,
    validate_success,
)


class TestStateErrorPrecedesStaleVersion:
    def test_suspended_member_transfer_reports_member_not_active_not_stale(self, api):
        """PRD §2.9: "**Member state.** Where an operation requires an `ACTIVE`
        member — registering a loan, receiving a transfer, submitting a
        reconciliation run, and signer-gated actions — a member in any other
        status triggers `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."
        PRD §2.9: "**Optimistic concurrency.** The version guards of §2.8 are
        evaluated **last**. A request that is both stale and, say, addressed to a
        loan in the wrong state reports the state error — not the stale-version
        error."

        Design: Difficulty/priority_pair_validation_conflict/state_member_inactive_vs_referential_stale_version
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=80000000)
        original_version = loan["version"]
        validate_success(api.suspend_member(a["id"], ADMIN))

        # The acting member is SUSPENDED and the expected version is stale;
        # the member-state error must win over the OCC guard.
        resp = api.create_transfer(
            create_transfer_payload(
                loan["id"], b["id"], original_version + 5,
                effective_date="2026-01-05T00:00:00Z", idempotency_key="k-prio-1",
            ),
            member_rep(a["id"]),
        )
        assert resp.status_code == 409, resp.text
        err = validate_error(resp, "ERR_MEMBER_NOT_ACTIVE")
        assert err["error_id"] != "ERR_STALE_LOAN_VERSION"
        # No partial write: the loan's version is unchanged.
        assert read_loan(loan["id"])["version"] == original_version

    def test_stale_version_reported_once_state_allows(self, api):
        """PRD §2.8: "If the loan's current `version` differs — because, for
        example, another writer has since confirmed a transfer on the same loan,
        moving its rights and advancing its version — the request is rejected with
        `ERR_STALE_LOAN_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/state_member_inactive_vs_referential_stale_version
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=80000000)

        # An otherwise-valid request with a stale version reaches the OCC guard.
        resp = api.create_transfer(
            create_transfer_payload(
                loan["id"], b["id"], loan["version"] + 7,
                effective_date="2026-01-05T00:00:00Z", idempotency_key="k-prio-2",
            ),
            member_rep(a["id"]),
        )
        assert resp.status_code == 412, resp.text
        validate_error(resp, "ERR_STALE_LOAN_VERSION")
        assert read_loan(loan["id"])["version"] == loan["version"]


class TestSodPrecedesFiscalSanity:
    def _appealed_sanction(self, api):
        """Member D, one MAJOR finding, settled by qa-settler, sanction appealed."""
        set_clock("2026-01-05T00:00:00Z")
        d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
        loan = register_loan(d["id"], loan_amount_cents=40000000)
        review = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                             period_end="2026-03-31T00:00:00Z")
        add_finding(review["id"], loan["id"], field_name="PROPERTY_STATE",
                    expected_value="TX", actual_value="TN", severity="MAJOR")
        issue_review(review["id"])
        settle_review(review["id"], payload={"abatement_factor": 1.0})
        sanction = list_sanctions(review_id=review["id"])[0]
        validate_success(api.appeal_sanction(sanction["id"], member_rep(d["id"])))
        return d, review, sanction

    def test_settler_cannot_adjudicate_even_when_reduction_also_invalid(self, api):
        """PRD §2.9: "**Segregation of duties.** The auditor who created a review
        may not settle it, and the auditor who settled a review may not adjudicate
        the sanction that settlement produced; violations yield
        `ERR_SOD_SAME_ACTOR` (HTTP 403)."
        PRD §2.9 lists segregation of duties at tier 8 and fiscal sanity of
        adjudication at tier 15.

        Design: Difficulty/priority_pair_validation_conflict/safety_signer_vs_temporal_closing_date
        """
        d, review, sanction = self._appealed_sanction(api)
        total = sanction["total_amount_cents"]

        # The settling auditor adjudicates — a SOD violation — and the supplied
        # reduced total is also not lower than the current total. The earlier
        # tier's failure is the one reported.
        resp = api.adjudicate_sanction(
            sanction["id"],
            {"decision": "REDUCED", "reduced_total_cents": total + 100000},
            make_qa_auditor_headers(QA_SETTLER),
        )
        assert resp.status_code == 403, resp.text
        err = validate_error(resp, "ERR_SOD_SAME_ACTOR")
        assert err["error_id"] != "ERR_REDUCTION_NOT_LOWER"

        after = validate_success(api.get_sanction(sanction["id"], ADMIN))
        assert after["status"] == "APPEALED", after
        assert after["total_amount_cents"] == total, after

    def test_third_auditor_adjudication_passes_the_sod_gate(self, api):
        """PRD §3.5: "Adjudication of an `APPEALED` sanction belongs to a
        `QAAuditor` — but, under the same segregation-of-duties principle, not the
        auditor who settled the parent review: the adjudicator's `X-User-ID` must
        differ from the review's `settled_by`, else `ERR_SOD_SAME_ACTOR`, and
        adjudication against a sanction not `APPEALED` fails with
        `ERR_SANCTION_NOT_APPEALED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_signer_vs_temporal_closing_date
        """
        from test_helpers import QA_JUDGE
        d, review, sanction = self._appealed_sanction(api)
        total = sanction["total_amount_cents"]

        # An auditor who neither created nor settled the review adjudicates.
        adjudicated = validate_success(
            api.adjudicate_sanction(
                sanction["id"],
                {"decision": "REDUCED", "reduced_total_cents": total - 1},
                make_qa_auditor_headers(QA_JUDGE),
            )
        )
        assert adjudicated["status"] == "REDUCED", adjudicated
        assert adjudicated["total_amount_cents"] == total - 1, adjudicated
