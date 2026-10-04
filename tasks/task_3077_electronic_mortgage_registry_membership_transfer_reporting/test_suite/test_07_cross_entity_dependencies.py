"""Cross-entity state dependencies: the receiving member's lifecycle gates a
transfer's creation, and the review creator's identity gates its settlement."""
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
    setup_two_member_pair,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTransferRequiresActiveRecipient:
    def test_transfer_to_suspended_member_rejected_without_side_effects(self, api):
        """PRD §3.4: "The receiving member must exist and be `ACTIVE`
        (`ERR_MEMBER_NOT_ACTIVE`) and must differ from the current holder of the
        moved right or rights (`ERR_SELF_TRANSFER`)."

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_to_member_active
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=50000000)
        validate_success(api.suspend_member(b["id"], ADMIN))

        resp = api.create_transfer(
            create_transfer_payload(
                loan["id"], b["id"], loan["version"],
                effective_date="2026-01-05T00:00:00Z", idempotency_key="k-xs-1",
            ),
            member_rep(a["id"]),
        )
        assert resp.status_code == 409, resp.text
        validate_error(resp, "ERR_MEMBER_NOT_ACTIVE")

        rows, meta = validate_paginated(
            api.list_transfers(ADMIN, params={"loan_id": loan["id"]})
        )
        assert rows == [], rows
        assert read_loan(loan["id"])["current_servicer_id"] == a["id"]

    def test_transfer_to_pending_activation_member_rejected(self, api):
        """PRD §2.9: "**Member state.** Where an operation requires an `ACTIVE`
        member — registering a loan, receiving a transfer, submitting a
        reconciliation run, and signer-gated actions — a member in any other
        status triggers `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_to_member_active
        """
        from test_helpers import create_member
        set_clock("2026-01-05T00:00:00Z")
        a = create_active_member(org_id="1000000")
        b = create_member(org_id="1000001", org_id_type="LEI",
                          member_type="INVESTOR")  # stays PENDING_ACTIVATION
        loan = register_loan(a["id"], loan_amount_cents=50000000)

        resp = api.create_transfer(
            create_transfer_payload(
                loan["id"], b["id"], loan["version"],
                effective_date="2026-01-05T00:00:00Z", idempotency_key="k-xs-2",
            ),
            member_rep(a["id"]),
        )
        assert resp.status_code == 409, resp.text
        validate_error(resp, "ERR_MEMBER_NOT_ACTIVE")
        assert read_loan(loan["id"])["current_servicer_id"] == a["id"]


class TestSettleBlockedByCreatorIdentity:
    def _issued_review(self, api):
        set_clock("2026-01-05T00:00:00Z")
        d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
        loan = register_loan(d["id"], loan_amount_cents=40000000)
        review = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                             period_end="2026-03-31T00:00:00Z")
        add_finding(review["id"], loan["id"], severity="MINOR")
        issue_review(review["id"])
        return d, review

    def test_creator_cannot_settle_but_another_auditor_can(self, api):
        """PRD §3.5: "Segregation of duties applies: the settling auditor's
        `X-User-ID` must differ from the review's `created_by`, else
        `ERR_SOD_SAME_ACTOR`."
        PRD §3.5: "On settlement the review moves to `SETTLED`, `settled_by`
        records the settler, `settled_at` stamps the clock, and exactly one
        Sanction is created in `ASSESSED` status against the reviewed member."

        Design: Difficulty/cross_entity_state_dependency/review_settle_blocked_by_creator_identity
        """
        d, review = self._issued_review(api)

        resp = api.settle_review(review["id"], {}, make_qa_auditor_headers(QA_CREATOR))
        assert resp.status_code == 403, resp.text
        validate_error(resp, "ERR_SOD_SAME_ACTOR")

        settled = validate_success(
            api.settle_review(review["id"], {}, make_qa_auditor_headers(QA_SETTLER))
        )
        assert settled["status"] == "SETTLED", settled
        assert settled["settled_by"] == QA_SETTLER, settled

        sanctions = list_sanctions(review_id=review["id"])
        assert len(sanctions) == 1, sanctions
        assert sanctions[0]["status"] == "ASSESSED", sanctions
        assert sanctions[0]["total_amount_cents"] == 25005, sanctions

    def test_rejected_settle_leaves_review_issued_and_creates_no_sanction(self, api):
        """PRD §2.9: "**Segregation of duties.** The auditor who created a review
        may not settle it, and the auditor who settled a review may not adjudicate
        the sanction that settlement produced; violations yield
        `ERR_SOD_SAME_ACTOR` (HTTP 403)."

        Design: Difficulty/cross_entity_state_dependency/review_settle_blocked_by_creator_identity
        """
        d, review = self._issued_review(api)

        resp = api.settle_review(review["id"], {}, make_qa_auditor_headers(QA_CREATOR))
        assert resp.status_code == 403, resp.text
        validate_error(resp, "ERR_SOD_SAME_ACTOR")

        reread = validate_success(api.get_qa_review(review["id"], ADMIN))
        assert reread["status"] == "FINDINGS_ISSUED", reread
        assert list_sanctions(review_id=review["id"]) == []
