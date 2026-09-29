"""Corner cases of the error catalogue: eleven collection-specific not-found codes
and the state errors that name the attempted action rather than only the resource."""
from test_helpers import (
    CO,
    IA,
    PO,
    RC,
    ApiErrorId,
    api_client,
    close_cycle,
    create_agreement_payload,
    create_batch,
    create_diligence_review_payload,
    create_ledger_entry_payload,
    create_partner,
    dispose_alert,
    dispose_complaint,
    draft_wind_down_plan,
    file_complaint,
    file_marketing_review,
    fund_batch,
    get_success_data,
    make_fintech_partner_headers,
    raise_alert,
    read_custody_account,
    read_partner,
    reconcile_batch,
    setup_live_partner,
    set_clock,
    terminate_agreement,
    validate_error,
)

ABSENT_ID = "00000000-0000-0000-0000-0000000000ff"


class TestEveryCollectionAnswersItsOwnNotFoundCode:
    def test_the_same_absent_uuid_yields_eleven_different_collection_specific_codes(self):
        """The not-found error is specific to the collection that segment addresses:
        `ERR_PARTNER_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` for a diligence review,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_MARKETING_REVIEW_NOT_FOUND`,
        `ERR_CUSTODY_ACCOUNT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND` for a settlement batch,
        `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
        `ERR_CYCLE_NOT_FOUND` or `ERR_PLAN_NOT_FOUND` for a wind-down plan. All are HTTP 404.

        Design: Corner/errors/every_collection_answers_its_own_not_found_code_and_never_a_neighbours
        """
        probes = [
            (api_client.get_partner, ApiErrorId.ERR_PARTNER_NOT_FOUND),
            (api_client.get_diligence_review, ApiErrorId.ERR_REVIEW_NOT_FOUND),
            (api_client.get_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api_client.get_marketing_review, ApiErrorId.ERR_MARKETING_REVIEW_NOT_FOUND),
            (api_client.get_custody_account, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_FOUND),
            (api_client.get_settlement_batch, ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api_client.get_ledger_entry, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
            (api_client.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
            (api_client.get_alert, ApiErrorId.ERR_ALERT_NOT_FOUND),
            (api_client.get_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND),
            (api_client.get_wind_down_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
        ]
        seen = []
        for read, expected in probes:
            response = read(ABSENT_ID, PO)
            validate_error(response, expected, 404)
            body = response.json()
            assert body["response_type"] == "error", body["response_type"]
            assert body["data"]["message"], f"{expected.value} carries a human-readable message"
            seen.append(body["data"]["error_id"])

        assert len(set(seen)) == 11, (
            "the very same absent uuid is answered by eleven distinct codes, so no generic "
            f"not-found code is shared between collections, got {sorted(set(seen))}"
        )
        assert "ERR_REVIEW_NOT_FOUND" in seen and "ERR_MARKETING_REVIEW_NOT_FOUND" in seen, (
            "the catalogue deliberately names the diligence collection ERR_REVIEW_NOT_FOUND "
            "while the marketing collection is ERR_MARKETING_REVIEW_NOT_FOUND"
        )


class TestStateErrorsNameTheAttemptedAction:
    def test_one_row_in_one_state_answers_a_different_code_for_each_action_attempted(self):
        """The target resource must currently be in a state from which the requested transition is
        declared. The code is specific to the machine and the endpoint: `ERR_REVIEW_NOT_SUBMITTED`,
        `ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED`, `ERR_AGREEMENT_NOT_DRAFT`,
        `ERR_AGREEMENT_NOT_PENDING_APPROVAL`, `ERR_AGREEMENT_NOT_EXECUTED`,
        `ERR_MARKETING_NOT_DECIDABLE`, `ERR_MARKETING_NOT_CHANGES_REQUESTED`.

        Design: Corner/errors/the_review_and_agreement_state_errors_name_the_endpoint_not_just_the_resource
        """
        partner_a = create_partner(legal_name="Hallowmere Trust Inc")
        partner_b = create_partner(legal_name="Ivyford Cash Inc")
        a_id, b_id = partner_a["id"], partner_b["id"]

        review = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(a_id, partner_a["version"]), PO
            )
        )
        assert review["status"] == "DRAFT"
        validate_error(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO),
            ApiErrorId.ERR_REVIEW_NOT_SUBMITTED,
            409,
        )

        submitted = get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
        assert submitted["status"] == "SUBMITTED"
        validate_error(
            api_client.submit_diligence_review(review["id"], {}, PO),
            ApiErrorId.ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED,
            409,
        )
        decided = get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO)
        )
        assert decided["status"] == "PASSED"
        assert read_partner(a_id)["status"] == "DILIGENCE_PASSED"

        current = read_partner(a_id)
        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(a_id, current["version"]), PO
            )
        )
        assert agreement["status"] == "DRAFT"
        validate_error(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, RC),
            ApiErrorId.ERR_AGREEMENT_NOT_PENDING_APPROVAL,
            409,
        )
        validate_error(
            api_client.terminate_agreement(
                agreement["id"], {"termination_trigger": "VOLUNTARY", "notice_days": 30}, RC
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED,
            409,
        )

        validate_error(
            api_client.create_marketing_review(
                {
                    "partner_id": b_id,
                    "agreement_id": agreement["id"],
                    "material_type": "DISCLOSURE",
                    "placement_channel": "PARTNER_SITE",
                    "disclosure_elements": ["BANK_NAME", "FEE_SCHEDULE", "DISPUTE_RIGHTS"],
                    "apr_disclosed": False,
                    "fdic_signage_correct": True,
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_until": "2026-09-10T00:00:00Z",
                },
                PO,
            ),
            ApiErrorId.ERR_AGREEMENT_PARTNER_MISMATCH,
            409,
        )

        filing = file_marketing_review(a_id, agreement["id"])
        assert filing["status"] == "SUBMITTED"
        assert filing["risk_flags"] == [], filing["risk_flags"]
        validate_error(
            api_client.resubmit_marketing_review(
                filing["id"],
                {
                    "disclosure_elements": ["BANK_NAME", "FEE_SCHEDULE", "DISPUTE_RIGHTS"],
                    "apr_disclosed": False,
                    "fdic_signage_correct": True,
                    "effective_from": "2026-09-02T00:00:00Z",
                    "effective_until": "2026-09-11T00:00:00Z",
                },
                make_fintech_partner_headers(a_id),
            ),
            ApiErrorId.ERR_MARKETING_NOT_CHANGES_REQUESTED,
            409,
        )

        routed = get_success_data(
            api_client.submit_agreement_for_approval(agreement["id"], {}, PO)
        )
        assert routed["status"] == "PENDING_RISK_APPROVAL"
        validate_error(
            api_client.submit_agreement_for_approval(agreement["id"], {}, PO),
            ApiErrorId.ERR_AGREEMENT_NOT_DRAFT,
            409,
        )

        approved = get_success_data(
            api_client.decide_marketing_review(filing["id"], {"decision": "APPROVE"}, CO)
        )
        assert approved["status"] == "APPROVED"
        validate_error(
            api_client.decide_marketing_review(filing["id"], {"decision": "REJECT"}, CO),
            ApiErrorId.ERR_MARKETING_NOT_DECIDABLE,
            409,
        )


class TestBatchComplaintAlertCycleAndPlanStateErrors:
    def test_each_dimension_of_each_machine_answers_its_own_code_exactly_once(self):
        """Because this rank sits well above every fiscal rank, a batch that has already been funded
        reports `ERR_BATCH_ALREADY_FUNDED` even when it also has a reserve shortfall that would fail
        at rank 86. The code is specific to the machine and the endpoint: `ERR_BATCH_NOT_UNRECONCILED`,
        `ERR_BATCH_NO_OPEN_VARIANCE`, `ERR_BATCH_ALREADY_FUNDED`, `ERR_BATCH_NOT_FUNDED`,
        `ERR_COMPLAINT_NOT_DISPOSABLE`, `ERR_ALERT_TERMINAL`, `ERR_CYCLE_NOT_OPEN`,
        `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_PENDING_APPROVAL` and `ERR_PLAN_NOT_APPROVED`.

        Design: Corner/errors/the_batch_complaint_alert_cycle_and_plan_state_errors_are_each_reachable_exactly_once
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Jessamine Rails Inc",
                "business_model": "CARD_ISSUING",
                "end_user_account_count": 7_000,
            },
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]
        batch = create_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        assert batch["reconciliation_status"] == "UNRECONCILED"
        assert batch["funding_status"] == "UNFUNDED"

        validate_error(
            api_client.clawback_settlement_batch(
                batch["id"], {"clawback_reason": "RECONCILIATION_ERROR"}, PO
            ),
            ApiErrorId.ERR_BATCH_NOT_FUNDED,
            409,
        )
        validate_error(
            api_client.clear_settlement_variance(
                batch["id"],
                {"variance_adjustment_cents": 50_000, "root_cause_note": "nothing to explain"},
                IA,
            ),
            ApiErrorId.ERR_BATCH_NO_OPEN_VARIANCE,
            409,
        )

        reconciled = reconcile_batch(batch["id"], 8_100_000)
        assert reconciled["reconciliation_status"] == "MATCHED"
        validate_error(
            api_client.reconcile_settlement_batch(
                batch["id"], {"bank_reported_net_cents": 8_100_000}, IA
            ),
            ApiErrorId.ERR_BATCH_NOT_UNRECONCILED,
            409,
        )

        stale_fbo_version = read_custody_account(ctx["fbo"]["id"])["version"]
        funded = fund_batch(batch["id"], funding_reference="WIRE-ERR-1")
        assert funded["funding_status"] == "FUNDED"
        validate_error(
            api_client.fund_settlement_batch(
                batch["id"], {"funding_reference": "WIRE-ERR-2"}, PO
            ),
            ApiErrorId.ERR_BATCH_ALREADY_FUNDED,
            409,
        )
        validate_error(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    ctx["fbo"]["id"],
                    stale_fbo_version,
                    entry_type="VARIANCE_ADJUSTMENT",
                    amount_cents=1_000,
                ),
                PO,
            ),
            ApiErrorId.ERR_STALE_CUSTODY_ACCOUNT_VERSION,
            412,
        )

        complaint = file_complaint(partner_id)
        assert complaint["status"] == "RECEIVED"
        withdrawn = dispose_complaint(
            complaint["id"], "WITHDRAWN", resolution_note="the consumer withdrew it"
        )
        assert withdrawn["status"] == "WITHDRAWN"
        validate_error(
            api_client.dispose_complaint(
                complaint["id"], {"outcome": "WITHDRAWN", "resolution_note": "again"}, CO
            ),
            ApiErrorId.ERR_COMPLAINT_NOT_DISPOSABLE,
            409,
        )

        alert = raise_alert(partner_id)
        assert alert["disposition"] == "OPEN"
        cleared = dispose_alert(alert["id"], "CLEARED")
        assert cleared["disposition"] == "CLEARED"
        validate_error(
            api_client.dispose_alert(
                alert["id"],
                {
                    "disposition": "CLEARED",
                    # A closing disposition needs at least twenty characters, so the note is long
                    # enough for the source-state guard to be the reason for the refusal.
                    "disposition_note": "a second clearing attempt on an already closed alert",
                },
                CO,
            ),
            ApiErrorId.ERR_ALERT_TERMINAL,
            409,
        )

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["status"] == "CLOSED"
        validate_error(
            api_client.close_cycle(ctx["cycle"]["id"], {}, PO),
            ApiErrorId.ERR_CYCLE_NOT_OPEN,
            409,
        )

        terminated = terminate_agreement(ctx["agreement"]["id"])
        assert terminated["status"] == "TERMINATED"
        assert read_partner(partner_id)["status"] == "WIND_DOWN"

        plan = draft_wind_down_plan(partner_id)
        assert plan["status"] == "DRAFT"
        validate_error(
            api_client.decide_wind_down_plan(plan["id"], {"decision": "APPROVE"}, RC),
            ApiErrorId.ERR_PLAN_NOT_PENDING_APPROVAL,
            409,
        )
        validate_error(
            api_client.execute_wind_down_plan(plan["id"], {}, PO),
            ApiErrorId.ERR_PLAN_NOT_APPROVED,
            409,
        )
        pending = get_success_data(api_client.submit_wind_down_plan(plan["id"], {}, PO))
        assert pending["status"] == "PENDING_APPROVAL"
        validate_error(
            api_client.submit_wind_down_plan(plan["id"], {}, PO),
            ApiErrorId.ERR_PLAN_NOT_DRAFT,
            409,
        )
