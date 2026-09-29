"""Launching a program depends on the agreement's state first and on custody
adequacy second."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_partner,
    custody_accounts,
    get_success_data,
    open_cycle,
    pass_diligence,
    post_ledger_entry,
    read_custody_account,
    read_partner,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PO, RC

PARTNER_OVERRIDES = {
    "legal_name": "Sextant Deposits Inc",
    "business_model": "DEPOSIT_WALLET",
    "funding_stage": "SERIES_B_PLUS",
    "months_runway": 30,
    "disclosed_complaints_per_10k": 1.00,
    "end_user_account_count": 900,
}


def _partner_with_a_pending_agreement():
    open_cycle()
    partner = create_partner(**PARTNER_OVERRIDES)
    _review, partner = pass_diligence(partner)
    assert partner["status"] == "DILIGENCE_PASSED"
    assert partner["capability_tier"] == "TIER_1"
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                partner["id"], partner["version"], reserve_requirement_bps=500
            ),
            PO,
        )
    )
    agreement = get_success_data(
        api_client.submit_agreement_for_approval(agreement["id"], {}, PO)
    )
    assert agreement["status"] == "PENDING_RISK_APPROVAL"
    return partner, agreement


class TestProgramLaunchDependencies:
    def test_launch_reports_the_partner_status_before_it_looks_at_the_agreement(self):
        """The partner's own `status` must be exactly `CONTRACTED`, reported as
        `ERR_PARTNER_NOT_CONTRACTED` when it is not; that guard is deliberately evaluated ahead of
        the readiness sweep so a partner still sitting in `DILIGENCE_PASSED` with no agreement
        whatsoever reports its status rather than a confusing readiness failure.

        Design: Difficulty/cross_entity_state_dependency/go_live_depends_on_agreement_state_and_reserve_adequacy_in_that_order
        """
        partner, agreement = _partner_with_a_pending_agreement()
        response = api_client.go_live(partner["id"], {}, PO)
        error = validate_error(response, ApiErrorId.ERR_PARTNER_NOT_CONTRACTED, 409)
        assert error["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_READY_FOR_LAUNCH

        unchanged = read_partner(partner["id"])
        assert unchanged["status"] == "DILIGENCE_PASSED"
        still_pending = get_success_data(api_client.get_agreement(agreement["id"], PO))
        assert still_pending["status"] == "PENDING_RISK_APPROVAL"

    def test_launch_waits_for_the_reserve_account_once_the_agreement_is_executed(self):
        """The readiness sweep then requires exactly one program agreement for that partner in
        `EXECUTED` and both of the partner's custody accounts in `ACTIVE`, refused as
        `ERR_PROGRAM_NOT_READY_FOR_LAUNCH` otherwise. Beyond readiness, launch requires
        `reserve_shortfall_cents` to be exactly 0 and the partner's `oversight_posture` to be `OPEN`
        or `HEIGHTENED`.

        Design: Difficulty/cross_entity_state_dependency/go_live_depends_on_agreement_state_and_reserve_adequacy_in_that_order
        """
        partner, agreement = _partner_with_a_pending_agreement()
        executed = get_success_data(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, RC)
        )
        assert executed["status"] == "EXECUTED"

        contracted = read_partner(partner["id"])
        assert contracted["status"] == "CONTRACTED"
        assert contracted["required_reserve_cents"] == 250_000, (
            "the absolute floor ties the end-user branch at a zero balance, got "
            f"{contracted['required_reserve_cents']}"
        )
        assert contracted["reserve_shortfall_cents"] == 250_000
        fbo, reserve = custody_accounts(partner["id"])
        assert fbo["status"] == "ACTIVE" and reserve["status"] == "ACTIVE"

        validate_error(
            api_client.go_live(partner["id"], {}, PO),
            ApiErrorId.ERR_PROGRAM_NOT_READY_FOR_LAUNCH,
            409,
        )
        assert read_partner(partner["id"])["status"] == "CONTRACTED"

        validate_success(
            post_ledger_entry(partner["id"], reserve, "RESERVE_FUND", 312_500), 201
        )
        funded = read_partner(partner["id"])
        assert funded["reserve_shortfall_cents"] == 0

        launched = validate_success(api_client.go_live(partner["id"], {}, PO))
        assert launched["status"] == "LIVE"
        assert launched["oversight_posture"] == "OPEN"
        assert read_custody_account(reserve["id"])["balance_cents"] == 312_500
        assert get_success_data(api_client.get_agreement(agreement["id"], PO))["status"] == "EXECUTED"
