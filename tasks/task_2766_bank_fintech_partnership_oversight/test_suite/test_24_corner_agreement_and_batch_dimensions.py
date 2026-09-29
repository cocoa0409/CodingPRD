"""The EXECUTE cascade, the REJECT loop, the INFO_REQUESTED loop, the launch
readiness gate and the two orthogonal settlement dimensions."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_batch,
    create_partner,
    custody_accounts,
    execute_agreement,
    open_cycle,
    pass_diligence,
    post_ledger_entry,
    read_custody_account,
    read_partner,
    validate_error,
    validate_paginated,
    validate_success,
    CO,
    PO,
    RC,
)

NORTHBEAM = {
    "legal_name": "Northbeam Pay Inc",
    "business_model": "CARD_ISSUING",
    "funding_stage": "SERIES_B_PLUS",
    "months_runway": 24,
    "disclosed_complaints_per_10k": 12.50,
    "end_user_account_count": 100000,
}
TERMS = {
    "dispute_owner": "PARTNER",
    "concentration_cap_pct": 80.00,
    "reserve_requirement_bps": 500,
    "max_end_user_balance_cents": 500_000_000,
}


def _pending_agreement():
    """A DILIGENCE_PASSED partner with one agreement routed to the risk committee."""
    partner = create_partner(**NORTHBEAM)
    _, partner = pass_diligence(partner)
    agreement = validate_success(
        api_client.create_agreement(
            create_agreement_payload(partner["id"], partner["version"], **TERMS), PO
        ),
        201,
    )
    routed = validate_success(
        api_client.submit_agreement_for_approval(
            agreement["id"], {"submission_note": "Terms agreed; routing to risk committee."}, PO
        ),
        200,
    )
    assert routed["status"] == "PENDING_RISK_APPROVAL"
    return partner, agreement


class TestAgreementDecisionBranches:
    def test_execute_creates_both_custody_accounts_and_runs_the_reserve_posture_chain(self):
        """Exactly two custody accounts are created for that partner, one with an `account_type` of
        `FBO_END_USER` and one with an `account_type` of `RESERVE`, each with a `status` of `ACTIVE`,
        a `balance_cents` of 0 and a null `frozen_at`; custody accounts are never created any other
        way, and the filtered custody list is their only discovery channel.

        Design: Corner/state_machines/agreement_execute_creates_both_custody_accounts_and_runs_the_reserve_posture_chain
        """
        open_cycle("2026-08")
        partner, agreement = _pending_agreement()
        executed = validate_success(
            api_client.decide_agreement_risk(
                agreement["id"],
                {"decision": "EXECUTE", "decision_note": "Approved with standard caps."},
                RC,
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] is not None
        assert executed["decided_by_user_id"] == RC["X-User-ID"]

        accounts, meta = validate_paginated(
            api_client.list_custody_accounts(PO, {"partner_id": partner["id"]})
        )
        assert meta["total_count"] == 2
        assert sorted(a["account_type"] for a in accounts) == ["FBO_END_USER", "RESERVE"]
        for account in accounts:
            assert account["status"] == "ACTIVE"
            assert account["balance_cents"] == 0
            assert account["frozen_at"] is None
            assert account["version"] == 1

        after = read_partner(partner["id"])
        assert after["status"] == "CONTRACTED"
        assert after["required_reserve_cents"] == 250_000, (
            "the absolute floor is the largest of the three candidates at a zero balance"
        )
        assert after["reserve_shortfall_cents"] == 250_000
        assert after["oversight_posture"] == "HEIGHTENED"

    def test_reject_returns_the_draft_and_the_loop_stays_re_enterable(self):
        """A `REJECT` decision returns the agreement `PENDING_RISK_APPROVAL → DRAFT`, increments
        `revision_round` by 1, records `decided_by_user_id`, increments the agreement's `version` by
        1, and touches nothing else — it creates no custody accounts and does not alter the partner's
        `status` or `version`.

        Design: Corner/state_machines/risk_reject_returns_the_agreement_to_draft_without_any_execute_side_effect
        """
        open_cycle("2026-08")
        partner, agreement = _pending_agreement()
        rejected = validate_success(
            api_client.decide_agreement_risk(
                agreement["id"],
                {"decision": "REJECT", "decision_note": "Caps need rework before we can execute."},
                RC,
            ),
            200,
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["revision_round"] == 2
        assert rejected["executed_at"] is None
        assert rejected["decided_by_user_id"] == RC["X-User-ID"]

        _, meta = validate_paginated(
            api_client.list_custody_accounts(PO, {"partner_id": partner["id"]})
        )
        assert meta["total_count"] == 0, "REJECT creates no custody accounts"
        assert read_partner(partner["id"])["status"] == "DILIGENCE_PASSED"

        validate_success(
            api_client.submit_agreement_for_approval(
                agreement["id"], {"submission_note": "Caps reworked; routing again."}, PO
            ),
            200,
        )
        executed = validate_success(
            api_client.decide_agreement_risk(
                agreement["id"], {"decision": "EXECUTE", "decision_note": "Approved on the second pass."}, RC
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"
        assert executed["revision_round"] == 2, "the round count survives execution"


class TestInfoRequestedLoop:
    def test_each_lap_raises_the_round_and_clears_the_item_list(self):
        """From `INFO_REQUESTED` the officer resubmits, moving the file `INFO_REQUESTED → SUBMITTED`
        again; that resubmission requires the partner to be in `IN_DILIGENCE`, increments
        `revision_round` by 1 rather than setting it, clears `requested_info_items` back to an empty
        array, records the new `submitted_by_user_id`, and recomputes
        `effective_complaint_history_score`, `composite_score` and `tier` afresh.

        Design: Corner/state_machines/the_info_requested_loop_increments_revision_round_and_clears_the_item_list_each_pass
        """
        partner = create_partner(**NORTHBEAM)
        review = validate_success(
            api_client.create_diligence_review(
                {
                    "partner_id": partner["id"],
                    "review_type": "INITIAL",
                    "business_model_score": 80,
                    "funding_score": 80,
                    "compliance_capability_score": 90,
                    "complaint_history_score": 85,
                    "expected_partner_version": partner["version"],
                },
                PO,
            ),
            201,
        )
        validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )

        first_hold = validate_success(
            api_client.decide_diligence_review(
                review["id"],
                {
                    "outcome": "INFO_REQUESTED",
                    "requested_info_items": ["Audited FY2025 financials", "SOC 2 Type II report"],
                    "decision_note": "Two gaps before we can score funding.",
                },
                CO,
            ),
            200,
        )
        assert first_hold["status"] == "INFO_REQUESTED"
        assert first_hold["revision_round"] == 1, "the decide does not touch the round"
        assert first_hold["decided_by_user_id"] == CO["X-User-ID"]
        assert first_hold["requested_info_items"] == [
            "Audited FY2025 financials",
            "SOC 2 Type II report",
        ]

        lap_two = validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Both items attached."}, PO
            ),
            200,
        )
        assert lap_two["status"] == "SUBMITTED"
        assert lap_two["revision_round"] == 2
        assert lap_two["requested_info_items"] == []

        second_hold = validate_success(
            api_client.decide_diligence_review(
                review["id"],
                {
                    "outcome": "INFO_REQUESTED",
                    "requested_info_items": ["Signed BSA officer attestation"],
                    "decision_note": "One remaining gap.",
                },
                CO,
            ),
            200,
        )
        assert second_hold["revision_round"] == 2
        lap_three = validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Attestation attached."}, PO
            ),
            200,
        )
        assert lap_three["status"] == "SUBMITTED"
        assert lap_three["revision_round"] == 3
        assert lap_three["requested_info_items"] == []

        after = read_partner(partner["id"])
        assert after["status"] == "IN_DILIGENCE", "the partner is pinned for the whole loop"
        assert after["version"] == 3, (
            f"the loop resubmits add nothing because the partner has no INFO_REQUESTED edge, got "
            f"{after['version']}"
        )

    def test_an_empty_requested_item_list_is_a_schema_failure(self):
        """An `INFO_REQUESTED` outcome moves the file `SUBMITTED → INFO_REQUESTED` and requires
        `requested_info_items` to be a non-empty array of strings, which is stored on the row; the
        partner's `status` remains `IN_DILIGENCE` for the whole duration of the loop and no partner
        field is touched.

        Design: Corner/state_machines/an_info_requested_decide_with_an_empty_item_list_is_refused
        """
        partner = create_partner(**NORTHBEAM)
        review = validate_success(
            api_client.create_diligence_review(
                {
                    "partner_id": partner["id"],
                    "review_type": "INITIAL",
                    "business_model_score": 80,
                    "funding_score": 80,
                    "compliance_capability_score": 90,
                    "complaint_history_score": 85,
                    "expected_partner_version": partner["version"],
                },
                PO,
            ),
            201,
        )
        validate_success(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Initial underwrite package complete."}, PO
            ),
            200,
        )
        validate_error(
            api_client.decide_diligence_review(
                review["id"],
                {
                    "outcome": "INFO_REQUESTED",
                    "requested_info_items": [],
                    "decision_note": "Empty list supplied by mistake.",
                },
                CO,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        untouched = validate_success(api_client.get_diligence_review(review["id"], PO), 200)
        assert untouched["status"] == "SUBMITTED"
        assert untouched["requested_info_items"] == []
        assert untouched["decided_by_user_id"] is None


class TestLaunchReadiness:
    def test_an_unfunded_reserve_refuses_the_launch_until_it_is_topped_up(self):
        """Beyond readiness, launch requires `reserve_shortfall_cents` to be exactly 0 and the
        partner's `oversight_posture` to be `OPEN` or `HEIGHTENED`. A successful launch increments the
        partner's `version` by 1.

        Design: Corner/state_machines/go_live_with_a_nonzero_reserve_shortfall_returns_program_not_ready_for_launch
        """
        open_cycle("2026-08")
        partner = create_partner(**NORTHBEAM)
        _, partner = pass_diligence(partner)
        _, partner = execute_agreement(partner, **TERMS)
        fbo, reserve = custody_accounts(partner["id"])
        assert fbo["balance_cents"] == 0
        assert reserve["balance_cents"] == 0

        validate_error(
            api_client.go_live(
                partner["id"], {"attestation_note": "Launch readiness attested."}, PO
            ),
            ApiErrorId.ERR_PROGRAM_NOT_READY_FOR_LAUNCH,
            409,
        )
        blocked = read_partner(partner["id"])
        assert blocked["status"] == "CONTRACTED"
        assert blocked["required_reserve_cents"] == 250_000
        assert blocked["reserve_shortfall_cents"] == 250_000
        assert blocked["oversight_posture"] == "HEIGHTENED"

        post_ledger_entry(
            partner["id"], reserve, "RESERVE_FUND", 312_500, effective_at="2026-08-05T00:00:00Z"
        )
        assert read_partner(partner["id"])["reserve_shortfall_cents"] == 0
        launched = validate_success(
            api_client.go_live(
                partner["id"], {"attestation_note": "Launch readiness attested."}, PO
            ),
            200,
        )
        assert launched["status"] == "LIVE"


class TestSettlementDimensions:
    def test_funding_reads_the_reconciliation_dimension_but_reconcile_ignores_funding(self):
        """Neither dimension constrains the other except for exactly one gate: funding requires the
        reconciliation dimension to have left `UNRECONCILED`.

        Design: Corner/state_machines/settlement_batch_reconciliation_and_funding_dimensions_advance_independently
        """
        open_cycle("2026-08")
        partner = create_partner(**NORTHBEAM)
        _, partner = pass_diligence(partner)
        _, partner = execute_agreement(partner, **TERMS)
        fbo, reserve = custody_accounts(partner["id"])
        post_ledger_entry(
            partner["id"], reserve, "RESERVE_FUND", 312_500, effective_at="2026-08-05T00:00:00Z"
        )
        validate_success(
            api_client.go_live(partner["id"], {"attestation_note": "Launch readiness attested."}, PO),
            200,
        )
        post_ledger_entry(
            partner["id"],
            fbo,
            "VARIANCE_ADJUSTMENT",
            8_100_000,
            effective_at="2026-08-05T00:00:00Z",
            memo="opening end-user float carried over at conversion",
        )
        post_ledger_entry(
            partner["id"],
            reserve,
            "RESERVE_FUND",
            193_750,
            effective_at="2026-08-05T00:00:00Z",
            memo="top-up to the heightened requirement",
        )
        assert read_custody_account(reserve["id"])["balance_cents"] == 506_250
        assert read_partner(partner["id"])["reserve_shortfall_cents"] == 0

        batch = create_batch(
            partner["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        assert batch["reconciliation_status"] == "UNRECONCILED"
        assert batch["funding_status"] == "UNFUNDED"
        assert batch["variance_cents"] == 0
        assert batch["variance_adjustment_cents"] == 0
        assert batch["bank_reported_net_cents"] is None
        assert batch["funded_at"] is None

        validate_error(
            api_client.fund_settlement_batch(
                batch["id"], {"funding_reference": "WIRE-2026-08-0001"}, PO
            ),
            ApiErrorId.ERR_BATCH_NOT_RECONCILED,
            409,
        )

        reconciled = validate_success(
            api_client.reconcile_settlement_batch(
                batch["id"], {"bank_reported_net_cents": 8_100_000}, PO
            ),
            200,
        )
        assert reconciled["reconciliation_status"] == "MATCHED"
        assert reconciled["variance_cents"] == 0
        assert reconciled["funding_status"] == "UNFUNDED", (
            "reconcile never touches the funding dimension"
        )
        final = read_partner(partner["id"])
        assert final["unreconciled_variance_cents"] == 0
        assert final["oversight_posture"] == "OPEN"
