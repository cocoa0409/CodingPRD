"""Difficulty queue — compensating_invariant: the apportionment availability
identity survives the obligation/deobligation pair, and the net-federal-outlay
identity survives the reimbursement/repayment pair (PRD §2.10, §3.9)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_apportionment_invariant,
    assert_closeout_net_share_invariant,
    create_approved_voucher,
    create_audit,
    create_line_item,
    finalize_audit,
    get_success_data,
    issue_audit_findings,
    record_repayment,
    set_clock,
    setup_project_under_construction,
)

H = TEST_USERS


class TestCompensatingInvariant:
    def test_obligation_then_deobligation_preserves_apportionment_identity(self, api):
        """PRD §2.10: "One invariant holds at all times and is auditable:
        `available_cents` always equals `apportioned_cents` minus
        `obligated_cents`."
        PRD §3.9: "The Audit moves from `FINDINGS_ISSUED` to `FINAL` — and when
        `repayment_due_cents` is zero it continues immediately to `CLOSED` in
        the same operation, firing the closeout cascade below without any
        repayment step."

        Authorizing 1,000,000 against a 2,000,000 cell drops availability to
        1,000,000; the clean-audit closeout deobligates the 200,000 never
        reimbursed, restoring availability to 1,200,000 — the identity holds
        after the forward action and after its compensating reverse.

        Design: Difficulty/compensating_invariant/obligation_then_deobligation_preserves_apportionment_identity
        """
        ctx = setup_project_under_construction(
            project_cost_cents=1_500_000,
            apportioned_cents=2_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-I-1",
        )
        auth_id = ctx["authorization"]["id"]
        ap_id = ctx["authorization"]["apportionment_id"]

        after_auth = get_success_data(api.get_apportionment(ap_id, H["fhwa_reviewer"]))
        assert after_auth["available_cents"] == 1_000_000, (
            "2,000,000 - 1,000,000 obligated, got "
            f"{after_auth['available_cents']}"
        )
        assert_apportionment_invariant(after_auth)

        final_voucher = create_approved_voucher(
            auth_id,
            line_items=[create_line_item("all work", 1_000_000)],
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-04-01T00:00:00Z",
            is_final=True,
        )
        assert final_voucher["federal_reimbursable_cents"] == 800_000
        project = get_success_data(api.get_project(ctx["project"]["id"], H["fhwa_reviewer"]))
        assert project["status"] == "COMPLETE"

        audit = create_audit(project["id"])
        issue_audit_findings(audit["id"], "No findings", 0)
        set_clock("2026-12-07T00:00:00Z")
        finalized = finalize_audit(audit["id"])
        assert finalized["repayment_due_cents"] == 0, (
            "800,000 reimbursed vs 800,000 final eligible leaves nothing due, "
            f"got {finalized['repayment_due_cents']}"
        )
        assert finalized["status"] == "CLOSED", (
            "zero repayment due must auto-close the audit in the same "
            f"operation, got {finalized['status']}"
        )

        ap_final = get_success_data(api.get_apportionment(ap_id, H["fhwa_reviewer"]))
        assert ap_final["obligated_cents"] == 800_000
        assert ap_final["available_cents"] == 1_200_000, (
            "available == apportioned - obligated must survive obligation and "
            f"deobligation without drift, got {ap_final['available_cents']}"
        )
        assert_apportionment_invariant(ap_final)

        auth_final = get_success_data(api.get_authorization(auth_id, H["fhwa_reviewer"]))
        assert auth_final["status"] == "CLOSED"
        assert auth_final["obligated_cents"] == 800_000, (
            "net federal outlay = reimbursed 800,000 - repaid 0, got "
            f"{auth_final['obligated_cents']}"
        )

    def test_reimbursement_then_repayment_conserves_net_federal_outlay(self, api):
        """PRD §2.10: "A second invariant governs closeout: when an
        authorization closes, its `reimbursed_cents` minus its `repaid_cents`
        equals the audit's `final_eligible_federal_share_cents`, so the
        ledger's net federal outlay always reconciles to the audited eligible
        share."
        PRD §3.9: "`repayment_due_cents` is the excess of the Authorization's
        `reimbursed_cents` over `final_eligible_federal_share_cents`, floored
        at zero."

        The forward voucher approval posts 400,000 (0.80 x 500,000 eligible);
        the audit finds 50,000 ineligible, so final eligible is
        round(450,000 x 0.80) = 360,000 and 40,000 is due. Repaying exactly
        that closes the loop: 400,000 - 40,000 = 360,000, and the
        authorization's terminal obligation equals that net, never the
        original 500,000.

        Design: Difficulty/compensating_invariant/reimbursement_then_repayment_conserves_net_federal_outlay
        """
        ctx = setup_project_under_construction(
            project_cost_cents=700_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=500_000,
            agreement_number="FA-N-1",
        )
        auth_id = ctx["authorization"]["id"]

        final_voucher = create_approved_voucher(
            auth_id,
            line_items=[create_line_item("all work", 500_000)],
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-04-01T00:00:00Z",
            is_final=True,
        )
        assert final_voucher["federal_reimbursable_cents"] == 400_000

        audit = create_audit(ctx["project"]["id"])
        issue_audit_findings(audit["id"], "50k ineligible", 50_000)
        set_clock("2026-12-07T00:00:00Z")
        finalized = finalize_audit(audit["id"])
        assert finalized["status"] == "FINAL"
        assert finalized["final_eligible_federal_share_cents"] == 360_000
        assert finalized["repayment_due_cents"] == 40_000

        closed = record_repayment(audit["id"], 40_000)
        assert closed["status"] == "CLOSED"

        auth_final = get_success_data(api.get_authorization(auth_id, H["fhwa_reviewer"]))
        assert auth_final["status"] == "CLOSED"
        assert auth_final["reimbursed_cents"] == 400_000
        assert auth_final["repaid_cents"] == 40_000
        assert auth_final["obligated_cents"] == 360_000, (
            "terminal obligation equals the net outlay 360,000, not the "
            f"original 500,000; got {auth_final['obligated_cents']}"
        )
        assert_closeout_net_share_invariant(auth_final, finalized)
