"""Corner coverage for invalid transitions, initial states and terminal
lockdowns across the state machines.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    onboard_partner,
    setup_program,
    issue_account,
    draft_agreement,
    open_negotiation,
    setup_negotiation_agreement,
    setup_active_agreement,
    setup_program_with_account,
    setup_closed_program,
    setup_wound_down_program_with_transfer,
    issue_program,
    post_promo_purchase,
    post_purchase,
    apply_principal,
    get_plan_for_transaction,
    roll_into_winding_down,
    propose_transfer,
    accept_transfer,
    close_program,
    make_cardholder_headers,
)

SERVICE = TEST_USERS["cardholder_service_headers"]


class TestInvalidTransitions:

    def test_executing_a_still_drafted_agreement_is_invalid_state(self, api, admin_headers):
        """PRD §3.1: "Executing a negotiated agreement into force requires the
        agreement to be in `NEGOTIATION` and requires the caller to supply the
        agreement's expected version".

        Design: Corner/state_machines/agreement_execute_from_draft_returns_invalid_state
        """
        partner = onboard_partner(api)
        agreement = draft_agreement(api, partner["id"])
        resp = api.execute_agreement(agreement["id"], agreement["version"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        refreshed = validate_success(api.get_agreement(agreement["id"], admin_headers), 200)
        assert refreshed["agreement_status"] == "DRAFT"
        assert refreshed["version"] == agreement["version"]

    def test_resolving_an_open_dispute_is_invalid_state(self, api, admin_headers):
        """PRD §3.8: "A `CardholderService` operator moves an `OPEN` case to
        `UNDER_REVIEW`, and the instant the case leaves `UNDER_REVIEW` is stamped
        on it as `resolved_at`. From `UNDER_REVIEW` the operator resolves the case".

        Design: Corner/state_machines/dispute_resolve_from_open_returns_invalid_state
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_purchase(api, account["id"], amount_cents=40000)
        dispute = get_success_data(
            api.create_dispute({"transaction_id": transaction["id"],
                                "account_id": account["id"],
                                "dispute_reason": "DUPLICATE_CHARGE"}, SERVICE)
        )
        resp = api.resolve_dispute(dispute["id"], "CARDHOLDER", SERVICE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        refreshed = validate_success(api.get_dispute(dispute["id"], admin_headers), 200)
        assert refreshed["case_status"] == "OPEN"
        assert refreshed["chargeback_amount_cents"] is None

    def test_replaying_agreement_execute_is_invalid_state(self, api, admin_headers):
        """PRD §3.1: "on success the agreement becomes `ACTIVE` and its `version`
        increments by one." PRD §3.1: "Executing a negotiated agreement into force
        requires the agreement to be in `NEGOTIATION`".

        Design: Corner/state_machines/agreement_execute_replayed_returns_invalid_state
        """
        partner = onboard_partner(api)
        agreement, neg_version = setup_negotiation_agreement(api, partner["id"])
        active = validate_success(
            api.execute_agreement(agreement["id"], neg_version, admin_headers), 200
        )
        assert active["agreement_status"] == "ACTIVE"

        replay = api.execute_agreement(agreement["id"], active["version"], admin_headers)
        validate_error(replay, ApiErrorId.ERR_INVALID_STATE, 409)

        refreshed = validate_success(api.get_agreement(agreement["id"], admin_headers), 200)
        assert refreshed["agreement_status"] == "ACTIVE"
        assert refreshed["version"] == active["version"], "the replay did not bump the version"


class TestInitialStates:

    def test_a_newly_issued_program_starts_active_at_version_one(self, api, admin_headers):
        """PRD §3.2: "New programs start in `ACTIVE`." PRD §3.2: "`outstanding_receivable_cents`
        is the sum of `outstanding_balance_cents` across every account on the
        program whose `account_status` is not `CHARGED_OFF`."

        Design: Corner/state_machines/program_create_starts_active_at_version_one
        """
        partner, agreement, _program = setup_program(api)
        program = validate_success(
            api.create_credit_program({"partner_id": partner["id"], "agreement_id": agreement["id"],
                                       "cycle_day": 31}, admin_headers),
            201,
        )
        assert program["program_status"] == "ACTIVE"
        assert program["version"] == 1
        assert program["cycle_day"] == 31
        assert program["outstanding_receivable_cents"] == 0


class TestTerminalLockdown:

    def test_a_closed_program_admits_no_further_transition(self, api, admin_headers):
        """PRD §3.2: "On success the program's `free_look_exposure_cents` is
        forced to zero, the version increments, and the program becomes `CLOSED`."
        PRD §3.2: "Moving from `WINDING_DOWN` to the terminal `CLOSED` state
        requires that every wind-down transfer with this `program_id` has reached
        `COMPLETED`".

        Design: Corner/state_machines/closed_credit_program_is_terminal_lockdown
        """
        _partner, _agreement, closed, _account, _transfer = setup_closed_program(api)
        assert closed["program_status"] == "CLOSED"

        resp = api.open_renewal(closed["id"], closed["version"], "RENEWAL_NEGOTIATION", admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        refreshed = validate_success(api.get_credit_program(closed["id"], admin_headers), 200)
        assert refreshed["program_status"] == "CLOSED"
        assert refreshed["version"] == closed["version"]


class TestPreconditionEnforcement:

    def test_loyalty_posting_is_refused_when_the_partner_link_is_disabled(self, api, admin_headers):
        """PRD §3.1: "while it is false, every attempt to post a loyalty benefit
        against an account on this retailer's program is rejected with
        `ERR_LOYALTY_LINK_DISABLED` (HTTP 422)."

        Design: Corner/state_machines/benefit_posting_rejected_when_partner_loyalty_link_disabled
        """
        _partner, _agreement, program = setup_program(api, loyalty_link_enabled=False)
        account = issue_account(api, program["id"])
        transaction = post_purchase(api, account["id"], amount_cents=40000)

        resp = api.create_benefit_posting(
            {"account_id": account["id"], "transaction_id": transaction["id"],
             "posting_reason": "PURCHASE_EARN", "points_amount": 800,
             "posts_to_retailer_loyalty": True}, SERVICE)
        validate_error(resp, ApiErrorId.ERR_LOYALTY_LINK_DISABLED, 422)

        postings, _meta = validate_paginated(
            api.list_benefit_postings(admin_headers, {"transaction_id": transaction["id"]})
        )
        assert postings == []
        loyalty = get_success_data(api.get_account_loyalty(account["id"], SERVICE))
        assert loyalty["linked_loyalty_balance"] == 0

    def test_executing_a_transfer_with_unsettled_accounts_is_invalid_state(self, api, admin_headers):
        """PRD §3.9: "Execution then follows from `AGREEMENT_REACHED` and requires
        that every account whose `program_id` names this program is already in
        `PAID_OFF` or `TRANSFERRED` — a program still carrying live accounts cannot
        complete its transfer."

        Design: Corner/state_machines/transfer_execute_before_accounts_settled_returns_invalid_state
        """
        _partner, _agreement, program, account, transfer = setup_wound_down_program_with_transfer(
            api, account_balance_cents=80000, accepted=True
        )
        resp = api.execute_transfer(transfer["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        refreshed = validate_success(api.get_transfer(transfer["id"], admin_headers), 200)
        assert refreshed["transfer_status"] == "AGREEMENT_REACHED"
        acct = validate_success(api.get_account(account["id"], admin_headers), 200)
        assert acct["account_status"] == "ACTIVE"

    def test_expiring_a_plan_before_its_expiry_instant_is_refused(self, api, admin_headers):
        """PRD §3.4: "A cardholder-service operator can also expire a plan
        explicitly, but only once the clock is at or after `promo_expires_at`; an
        attempt to expire a plan early is rejected with `ERR_PROMO_NOT_EXPIRED`
        (HTTP 422)".

        Design: Corner/state_machines/promo_expire_before_expiry_boundary_rejected
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])

        resp = api.expire_promo_plan(plan["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_PROMO_NOT_EXPIRED, 422)

        refreshed = validate_success(api.get_promo_plan(plan["id"], admin_headers), 200)
        assert refreshed["plan_status"] == "ACTIVE"
        assert refreshed["subsidy_at_risk_cents"] == 5756