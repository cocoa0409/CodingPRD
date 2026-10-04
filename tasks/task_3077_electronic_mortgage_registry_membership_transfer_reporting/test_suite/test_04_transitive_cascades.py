"""Transitive cascades: member termination rolling through loans into an open
reconciliation run, and a rejected match escalating into a QA finding."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    create_active_member,
    create_transfer_payload,
    get_match_for_transfer,
    list_findings,
    list_sor_exceptions,
    member_rep,
    open_review,
    read_loan,
    read_member,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_paginated,
    validate_success,
)


class TestTerminationCascade:
    def test_termination_cascades_member_to_loans_to_open_run(self, api):
        """PRD §3.7: "Filing termination also deactivates the member's dormant
        portfolio in the same motion: every loan the member originally registered
        (`registering_member_id` equal to the terminating member) that is still
        `ACTIVE` cascades to `INACTIVE_TERMINATED`."
        PRD §3.7: "The cascade propagates one hop further into reconciliation:
        each loan so flipped generates a `REGISTRY_ONLY` SOR exception on the
        member's currently `OPEN` reconciliation run, if one exists."
        PRD §3.7: "The accepted request sets the member's
        `termination_effective_date` and moves it from `ACTIVE` to
        `TERMINATION_PENDING` — or directly to `TERMINATED` when the effective
        date is not after the clock, immediate termination included — and in
        either case advances the member's `version`."

        Design: Difficulty/transitive_cascade/termination_cascade_member_loan_sorexception_run
        """
        set_clock("2026-01-05T00:00:00Z")
        e = create_active_member(org_id="1000003", member_type="ORIGINATOR")
        f = create_active_member(org_id="1000004", member_type="INVESTOR")
        loan1 = register_loan(e["id"], loan_amount_cents=60000000)
        loan2 = register_loan(e["id"], loan_amount_cents=60000000)

        # Termination gate (§3.7): no loan in any status may name E as holder.
        # Move both rights on loan1 to F, confirm the match, then F satisfies
        # loan1 so it leaves the registry before the run.
        tr1 = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan1["id"], f["id"], loan1["version"],
                    transfer_type="BOTH",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-casc-0",
                ),
                member_rep(e["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.match_confirm(tr1["id"], member_rep(e["id"])))
        # Loan 1 leaves the registry by satisfaction before the run.
        validate_success(api.satisfy_loan(loan1["id"], member_rep(f["id"])))
        # Empty submission: the run opens with one REGISTRY_ONLY exception (loan2).
        run = validate_success(
            api.create_sor_run({"records": []}, member_rep(e["id"])),
            expected_status=201,
        )
        assert run["status"] == "OPEN", run
        assert run["registry_only_count"] == 1, run

        # Termination gate (§3.7): E must hold no rights anywhere. Move both
        # rights on loan2 to F and confirm the match so E's match ledger has
        # nothing PENDING.
        loan2_now = read_loan(loan2["id"])
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan2["id"], f["id"], loan2_now["version"],
                    transfer_type="BOTH",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-casc-1",
                ),
                member_rep(e["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.match_confirm(tr["id"], member_rep(e["id"])))

        current = read_member(e["id"])
        validate_success(
            api.terminate_member(
                e["id"],
                {"effective_date": "2026-01-05T00:00:00Z",
                 "expected_member_version": current["version"]},
                ADMIN,
            )
        )

        # Hop 0: effective date equal to the clock is immediate termination.
        member_after = read_member(e["id"])
        assert member_after["status"] == "TERMINATED", member_after

        # Hop 1: only the still-ACTIVE loan flips; the satisfied loan is untouched.
        assert read_loan(loan2["id"])["status"] == "INACTIVE_TERMINATED"
        assert read_loan(loan1["id"])["status"] == "INACTIVE_SATISFIED"

        # Hop 2: a new REGISTRY_ONLY exception for the flipped loan on the open run.
        exceptions = list_sor_exceptions(run_id=run["id"])
        registry_only = [x for x in exceptions if x["exception_type"] == "REGISTRY_ONLY"]
        assert any(x["loan_id"] == loan2["id"] for x in registry_only), exceptions

        # Hop 3: the run stays OPEN — termination never completes a run.
        run_after = validate_success(api.get_sor_run(run["id"], ADMIN))
        assert run_after["status"] == "OPEN", run_after

    def test_cascade_skips_members_without_open_runs(self, api):
        """PRD §3.7: "each loan so flipped generates a `REGISTRY_ONLY` SOR
        exception on the member's currently `OPEN` reconciliation run, if one
        exists."

        Design: Difficulty/transitive_cascade/termination_cascade_member_loan_sorexception_run
        """
        set_clock("2026-01-05T00:00:00Z")
        e = create_active_member(org_id="1000003", member_type="ORIGINATOR")
        loan = register_loan(e["id"], loan_amount_cents=60000000)

        # Termination gate (§3.7): E must hold no rights and no PENDING match.
        f = create_active_member(org_id="1000004", member_type="INVESTOR")
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], f["id"], loan["version"],
                    transfer_type="BOTH",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-casc-2",
                ),
                member_rep(e["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.match_confirm(tr["id"], member_rep(e["id"])))

        current = read_member(e["id"])
        validate_success(
            api.terminate_member(
                e["id"],
                {"effective_date": "2026-01-05T00:00:00Z",
                 "expected_member_version": current["version"]},
                ADMIN,
            )
        )
        # With no open run the cascade still flips the loan and terminates.
        assert read_loan(loan["id"])["status"] == "INACTIVE_TERMINATED"
        assert read_member(e["id"])["status"] == "TERMINATED"
        assert list_sor_exceptions() == []


class TestRejectMatchCascade:
    def _confirmed_transfer_with_draft_review(self, api):
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=90000000)
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(loan["id"], b["id"], loan["version"],
                                        effective_date="2026-01-05T00:00:00Z",
                                        idempotency_key="k-rej-1"),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )
        review = open_review(a["id"])
        return a, b, loan, tr, review

    def test_reject_match_flips_transfer_expires_match_and_adds_finding(self, api):
        """PRD §3.4: "the transfer itself flips from `CONFIRMED` to `REJECTED`,
        the match flips to `EXPIRED`, but the rights movement on the loan is
        **not** rolled back — the loan keeps its new holders."
        PRD §3.4: "if a QA review for the from-side member happens to be in
        `DRAFT` at that moment, the rejection appends one automatic finding to it,
        with `severity` `MAJOR` and `field_name` `CURRENT_SERVICER`, flagging the
        pair for quality assurance."

        Design: Difficulty/transitive_cascade/reject_match_cascade_transfer_match_qafinding
        """
        a, b, loan, tr, review = self._confirmed_transfer_with_draft_review(api)

        validate_success(api.reject_match(tr["id"], member_rep(a["id"])))

        transfer_after = validate_success(api.get_transfer(tr["id"], ADMIN))
        assert transfer_after["status"] == "REJECTED", transfer_after

        loan_after = read_loan(loan["id"])
        # The rights move is NOT rolled back: B keeps the servicing right.
        assert loan_after["current_servicer_id"] == b["id"], loan_after
        assert loan_after["current_investor_id"] == a["id"], loan_after

        match = get_match_for_transfer(tr["id"])
        assert match["status"] == "EXPIRED", match

        findings = list_findings(review["id"])
        assert len(findings) == 1, findings
        assert findings[0]["severity"] == "MAJOR", findings
        assert findings[0]["field_name"] == "CURRENT_SERVICER", findings

    def test_reject_without_draft_review_still_flips_transfer_and_match(self, api):
        """PRD §3.4: "Rejection is deliberately asymmetric, and the asymmetry is
        the point: the transfer itself flips from `CONFIRMED` to `REJECTED`, the
        match flips to `EXPIRED`, but the rights movement on the loan is
        **not** rolled back — the loan keeps its new holders."

        Design: Difficulty/transitive_cascade/reject_match_cascade_transfer_match_qafinding
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=90000000)
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(loan["id"], b["id"], loan["version"],
                                        effective_date="2026-01-05T00:00:00Z",
                                        idempotency_key="k-rej-2"),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        validate_success(api.reject_match(tr["id"], member_rep(a["id"])))

        transfer_after = validate_success(api.get_transfer(tr["id"], ADMIN))
        assert transfer_after["status"] == "REJECTED", transfer_after
        match = get_match_for_transfer(tr["id"])
        assert match["status"] == "EXPIRED", match
        # No DRAFT review existed for the from-side member, so no finding lands
        # anywhere: the flat findings listing is empty.
        findings, _meta = validate_paginated(api.list_findings_flat(ADMIN))
        assert findings == [], findings
