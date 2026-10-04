"""State-machine transitions: initial states, guarded transitions, cycles,
and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    create_account_payload,
    create_eligibility_policy_payload,
    create_hospital_partnership_payload,
    create_partnership_milestone_payload,
    create_portfolio_payload,
    create_source_organization_payload,
    get_success_data,
    make_contract_manager_headers,
    make_donor_relations_headers,
    make_eligibility_officer_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
    set_clock,
    setup_finalized_batch,
    setup_standard_priced,
    setup_standard_settled,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPolicyLifecycle:
    def test_policy_initial_state_draft_and_activation(self, api):
        """PRD §3.2: "A policy is born `DRAFT`."
        PRD §3.2: "An `ACTIVE` policy becomes selectable for screening runs"

        Design: Corner/state_machines/policy_initial_state_draft_and_activation
        """
        set_clock()
        eo = make_eligibility_officer_headers()
        policy = get_success_data(
            api.create_eligibility_policy(create_eligibility_policy_payload(), eo)
        )
        assert policy["status"] == "DRAFT"
        resp = api.activate_eligibility_policy(policy["id"], eo)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"
        fetched = get_success_data(api.get_eligibility_policy(policy["id"], eo))
        assert fetched["status"] == "ACTIVE"

    def test_screening_with_draft_policy_rejected_not_active(self, api):
        """PRD §3.2: "Screening begins when an `EligibilityOfficer` opens a
        `ScreeningRun` against a portfolio, supplying the `policy_id` to apply
        — a reference that must exist (`ERR_POLICY_NOT_FOUND`) and be `ACTIVE`
        (`ERR_POLICY_NOT_ACTIVE`)."

        Design: Corner/state_machines/screening_with_draft_policy_rejected_not_active
        """
        set_clock()
        admin = make_platform_admin_headers()
        eo = make_eligibility_officer_headers()
        analyst = make_portfolio_analyst_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        policy = get_success_data(
            api.create_eligibility_policy(create_eligibility_policy_payload(), eo)
        )
        assert policy["status"] == "DRAFT"
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        get_success_data(
            api.import_accounts(
                pf["id"],
                [
                    create_account_payload(
                        "S1", debtor_household_key="HS1", debtor_zip="75050",
                        annual_income_cents=100, balance_cents=1000,
                    )
                ],
                analyst,
            )
        )
        get_success_data(api.submit_portfolio(pf["id"], analyst))
        resp = api.create_screening_run(pf["id"], policy["id"], eo)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE, 409)
        runs, meta = validate_paginated(
            api.list_screening_runs(eo, params={"portfolio_id": pf["id"]})
        )
        assert runs == [], "no screening run is created"
        portfolio = get_success_data(api.get_portfolio(pf["id"], eo))
        assert portfolio["status"] == "SUBMITTED"


class TestPortfolioInvalidTransitions:
    def test_portfolio_submit_from_priced_is_invalid(self, api):
        """PRD §3.1: "Submitting the portfolio — allowed only from `DRAFT` —
        requires at least one imported account"

        Design: Corner/state_machines/portfolio_submit_from_priced_is_invalid_transition
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        assert pf["status"] == "PRICED"
        assert pf["quoted_price_cents"] == 37500
        resp = api.submit_portfolio(pf["id"], make_portfolio_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(
            api.get_portfolio(pf["id"], make_portfolio_analyst_headers())
        )
        assert after["status"] == "PRICED"
        assert after["quoted_price_cents"] == 37500


class TestContractTerminalLockdown:
    def test_terminate_after_settle_rejected(self, api):
        """PRD §3.4: "A contract that should not settle may be terminated by a
        `ContractManager` from `EXECUTED`, supplying a `reason` that is recorded
        as `terminated_reason`; the contract lands in terminal `TERMINATED` and
        the portfolio falls back from `CONTRACTED` to `PRICED`"

        Design: Corner/state_machines/contract_settled_terminal_lockdown
        """
        ctx = setup_standard_settled()
        contract = ctx["contract"]
        resp = api.terminate_contract(
            contract["id"], "changed mind", make_contract_manager_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = get_success_data(
            api.get_contract(contract["id"], make_contract_manager_headers())
        )
        assert fetched["status"] == "SETTLED"
        assert fetched["terminated_reason"] is None
        portfolio = get_success_data(
            api.get_portfolio(ctx["portfolio"]["id"], make_finance_officer_headers())
        )
        assert portfolio["status"] == "SETTLED"


class TestDonationIdempotency:
    def test_double_receive_rejected_and_credited_once(self, api):
        """PRD §3.5: "A `FinanceOfficer` marks a pledge received, which moves
        the donation from `PLEDGED` to `RECEIVED` and adds its `net_cents` to
        the campaign's `raised_cents`."
        PRD §3.5: "A campaign's `raised_cents` is always exactly the sum of
        `net_cents` over its `RECEIVED` donations."

        Design: Corner/state_machines/donation_double_receive_rejected_idempotency
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Idem Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 100000},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        resp = api.receive_donation(donation["id"], fin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        refreshed = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert refreshed["raised_cents"] == 97100, (
            "raised_cents must be credited exactly once"
        )


class TestLetterRequeueGuards:
    def test_requeue_only_from_bounced(self, api):
        """PRD §3.7: "A `BOUNCED` letter may be requeued by the officer,
        optionally supplying a `corrected_address`"

        Design: Corner/state_machines/letter_requeue_only_from_bounced
        """
        ctx = setup_finalized_batch()
        letter = ctx["letters"][0]
        assert letter["status"] == "QUEUED"
        resp = api.requeue_notification_letter(
            letter["id"], make_donor_relations_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = get_success_data(
            api.get_notification_letter(
                letter["id"], make_donor_relations_headers()
            )
        )
        assert fetched["status"] == "QUEUED"


class TestPartnershipSuspensionCycle:
    def test_suspend_blocks_milestones_and_resume_restores(self, api):
        """PRD §3.9: "The officer activates a `PROPOSED` partnership to
        `ACTIVE`, may suspend an `ACTIVE` one to `SUSPENDED`, and may resume a
        `SUSPENDED` one back to `ACTIVE`; each step requires exactly the named
        source state (`ERR_INVALID_STATE`). While a partnership is `SUSPENDED`,
        all milestone transitions are blocked with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/partnership_suspend_resume_cycle_and_milestone_gate
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        hp = get_success_data(
            api.create_hospital_partnership(
                create_hospital_partnership_payload(
                    org["id"], fap_baseline_score=40, fap_target_score=80
                ),
                dro,
            )
        )
        get_success_data(api.activate_hospital_partnership(hp["id"], dro))
        milestone = get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                create_partnership_milestone_payload(
                    "FAP-1",
                    description="Publish plain-language FAP",
                    weight=100,
                    due_date="2026-12-31",
                ),
                dro,
            )
        )
        get_success_data(api.suspend_hospital_partnership(hp["id"], dro))
        resp = api.mark_milestone_met(milestone["id"], dro)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        get_success_data(api.resume_hospital_partnership(hp["id"], dro))
        resp = api.mark_milestone_met(milestone["id"], dro)
        data = validate_success(resp, 200)
        assert data["status"] == "MET"
        partnership = get_success_data(api.get_hospital_partnership(hp["id"], dro))
        assert partnership["fap_current_score"] == 100


class TestSettlementPartition:
    def test_settle_partitions_accounts_purchased_vs_excluded(self, api):
        """PRD §3.4: "Settlement stamps `settled_by`, copies the pinned
        `contract_price_cents` into the portfolio's `purchased_price_cents`,
        moves the portfolio to `SETTLED`, and partitions the accounts: every
        account whose `eligibility_status` is `ELIGIBLE` at settlement moves
        from `AVAILABLE` to `PURCHASED` and becomes valid input for abolishment
        batches, while every other account — `INELIGIBLE`, `NEEDS_REVIEW`, or
        still `UNSCREENED` — moves from `AVAILABLE` to terminal `EXCLUDED`."

        Design: Corner/state_machines/settle_partitions_accounts_purchased_vs_excluded
        """
        ctx = setup_standard_settled()
        a1, _a2, a3 = ctx["accounts"]
        account_a1 = get_success_data(
            api.get_account(a1["id"], make_finance_officer_headers())
        )
        account_a3 = get_success_data(
            api.get_account(a3["id"], make_finance_officer_headers())
        )
        assert account_a1["lifecycle_status"] == "PURCHASED"
        assert account_a3["lifecycle_status"] == "EXCLUDED"
        portfolio = get_success_data(
            api.get_portfolio(ctx["portfolio"]["id"], make_finance_officer_headers())
        )
        assert portfolio["status"] == "SETTLED"
        assert portfolio["purchased_price_cents"] == 37500
        contract = get_success_data(
            api.get_contract(ctx["contract"]["id"], make_finance_officer_headers())
        )
        assert contract["settled_by"] == "fin-9"


class TestBatchUncommit:
    def test_uncommit_releases_campaign_reservation(self, api):
        """PRD §3.6: "Uncommitting is the compensating action: it returns a
        `COMMITTED` batch to `STAGING`, releases every drawn campaign's
        reservation by subtracting each allocation from that campaign's
        `committed_cents`, and clears the batch's `funding_allocations`."

        Design: Corner/state_machines/batch_uncommit_releases_campaign_reservation
        """
        from test_helpers import setup_committed_batch

        ctx = setup_committed_batch()
        batch = ctx["batch"]
        assert batch["status"] == "COMMITTED"
        fin = make_finance_officer_headers()
        resp = api.uncommit_abolishment_batch(batch["id"], fin)
        data = validate_success(resp, 200)
        assert data["status"] == "STAGING"
        assert data["funding_allocations"] == []
        campaign = get_success_data(
            api.get_donor_campaign(ctx["campaign"]["id"], fin)
        )
        assert campaign["committed_cents"] == 0
        assert campaign["raised_cents"] == 1553600
