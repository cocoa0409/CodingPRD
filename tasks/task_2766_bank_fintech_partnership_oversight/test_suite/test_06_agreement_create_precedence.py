"""Creating a program agreement: the partner stale-version guard is evaluated
ahead of the terminal-partner guard."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_diligence_review_payload,
    create_partner,
    get_success_data,
    open_cycle,
    read_partner,
    validate_error,
)
from test_helpers.fixtures import CO, PO


def _failed_diligence_with_stale_token():
    """Returns the partner id and the version observed before the FAILED decision."""
    open_cycle()
    partner = create_partner(
        legal_name="Bitterroot Neo Inc",
        business_model="DEPOSIT_WALLET",
        funding_stage="SEED",
        months_runway=6,
        disclosed_complaints_per_10k=30.00,
        end_user_account_count=0,
    )
    review = get_success_data(
        api_client.create_diligence_review(
            create_diligence_review_payload(
                partner["id"],
                partner["version"],
                review_type="INITIAL",
                business_model_score=30,
                funding_score=30,
                compliance_capability_score=30,
                complaint_history_score=30,
            ),
            PO,
        )
    )
    get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
    mid = read_partner(partner["id"])
    assert mid["status"] == "IN_DILIGENCE"
    stale_version = mid["version"]
    decided = get_success_data(
        api_client.decide_diligence_review(review["id"], {"outcome": "FAILED"}, CO)
    )
    assert decided["status"] == "FAILED"
    return partner["id"], review["id"], stale_version


class TestAgreementCreatePrecedence:
    def test_a_stale_partner_token_is_reported_ahead_of_the_terminal_partner_guard(self):
        """**Rank 28 — Partner stale-version guard** on `POST /oversight/diligence-reviews` and
        `POST /oversight/agreements`: `expected_partner_version` equals the partner's current
        `version`, else `ERR_STALE_PARTNER_VERSION` (412).

        Design: Difficulty/priority_pair_validation_conflict/stale_partner_occ_outranks_terminal_partner_guard_on_agreement_create
        """
        partner_id, _review_id, stale_version = _failed_diligence_with_stale_token()
        response = api_client.create_agreement(
            create_agreement_payload(
                partner_id,
                stale_version,
                oversight_rights_level="STANDARD",
                audit_access_notice_days=15,
                termination_triggers=["VOLUNTARY"],
                monthly_growth_cap_pct=20.00,
                concentration_cap_pct=30.00,
                max_end_user_balance_cents=100_000,
                reserve_requirement_bps=500,
            ),
            PO,
        )
        error = validate_error(response, ApiErrorId.ERR_STALE_PARTNER_VERSION, 412)
        assert error["error_id"] != ApiErrorId.ERR_PARTNER_TERMINAL

        partner = read_partner(partner_id)
        assert partner["status"] == "DILIGENCE_FAILED"
        assert partner["version"] > stale_version
        assert get_success_data(api_client.list_agreements(PO, {"partner_id": partner_id})) == []

    def test_the_terminal_partner_guard_surfaces_once_the_token_is_fresh(self):
        """**Rank 32 — Partner terminality.** No `DiligenceReview`, `ProgramAgreement`,
        `MarketingReview`, `SettlementBatch`, `LedgerEntry`, `Complaint`,
        `TransactionMonitoringAlert` or `WindDownPlan` may be created for a partner whose `status`
        is `DILIGENCE_FAILED` or `TERMINATED`, else `ERR_PARTNER_TERMINAL` (409).

        Design: Difficulty/priority_pair_validation_conflict/stale_partner_occ_outranks_terminal_partner_guard_on_agreement_create
        """
        partner_id, _review_id, stale_version = _failed_diligence_with_stale_token()
        validate_error(
            api_client.create_agreement(
                create_agreement_payload(partner_id, stale_version), PO
            ),
            ApiErrorId.ERR_STALE_PARTNER_VERSION,
            412,
        )
        fresh_version = read_partner(partner_id)["version"]
        assert fresh_version > stale_version

        response = api_client.create_agreement(
            create_agreement_payload(
                partner_id,
                fresh_version,
                oversight_rights_level="STANDARD",
                audit_access_notice_days=15,
                termination_triggers=["VOLUNTARY"],
                monthly_growth_cap_pct=20.00,
                concentration_cap_pct=30.00,
                max_end_user_balance_cents=100_000,
                reserve_requirement_bps=500,
            ),
            PO,
        )
        validate_error(response, ApiErrorId.ERR_PARTNER_TERMINAL, 409)

        after = read_partner(partner_id)
        assert after["version"] == fresh_version, "neither refused create bumped the version"
        assert after["status"] == "DILIGENCE_FAILED"
        assert get_success_data(api_client.list_agreements(PO, {"partner_id": partner_id})) == []
