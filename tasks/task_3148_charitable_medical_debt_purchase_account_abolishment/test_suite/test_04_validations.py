"""Validation pipeline: priority ordering, covenant checks, segregation of
duties, price drift, funding coverage, reversibility, and uniqueness."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_contract_payload,
    create_eligibility_policy_payload,
    create_source_organization_payload,
    get_success_data,
    make_contract_manager_headers,
    make_donor_relations_headers,
    make_eligibility_officer_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
    set_clock,
    setup_committed_batch,
    setup_finalized_batch,
    setup_standard_priced,
    setup_standard_settled,
    stage_batch,
    validate_error,
    validate_success,
)


class TestValidationPriorityOrdering:
    def test_request_error_beats_not_found_when_both_fail(self, api):
        """PRD §2.7: "When several checks could fail on one request, the
        earliest tier's error is returned — so, for example, a malformed body
        surfaces as `ERR_INVALID_REQUEST` even if the caller is also
        unauthorized, and a state conflict surfaces before any money check on
        the same call."

        Design: Corner/validations/request_error_beats_not_found_when_both_fail
        """
        set_clock()
        resp = api.create_donation(
            NON_EXISTENT_UUID,
            {"donor_name": "X", "donor_email": "x@x.com"},
            make_donor_relations_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_batch_recommit_state_error_beats_fiscal_error(self, api):
        """PRD §2.7: "When several checks could fail on one request, the
        earliest tier's error is returned — so, for example, a malformed body
        surfaces as `ERR_INVALID_REQUEST` even if the caller is also
        unauthorized, and a state conflict surfaces before any money check on
        the same call."
        PRD §3.6: "Committing the batch runs the earmark waterfall of §3.5
        against `total_abolished_cents`. A successful commit moves the batch to
        `COMMITTED`"

        Design: Difficulty/priority_pair_validation_conflict/batch_recommit_state_error_beats_fiscal_error
        """
        ctx = setup_committed_batch()
        batch = ctx["batch"]
        assert batch["status"] == "COMMITTED"
        resp = api.commit_abolishment_batch(
            batch["id"], make_finance_officer_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = get_success_data(
            api.get_abolishment_batch(batch["id"], make_finance_officer_headers())
        )
        assert fetched["status"] == "COMMITTED"
        assert fetched["funding_allocations"] == batch["funding_allocations"]

    def test_uncommitted_batch_recommits_after_staging(self, api):
        """PRD §3.6: "Uncommitting is the compensating action: it returns a
        `COMMITTED` batch to `STAGING`, releases every drawn campaign's
        reservation by subtracting each allocation from that campaign's
        `committed_cents`, and clears the batch's `funding_allocations`."
        PRD §3.6: "Committing the batch runs the earmark waterfall of §3.5
        against `total_abolished_cents`. A successful commit moves the batch to
        `COMMITTED`"

        Design: Difficulty/priority_pair_validation_conflict/batch_recommit_state_error_beats_fiscal_error
        """
        ctx = setup_committed_batch()
        batch = ctx["batch"]
        fin = make_finance_officer_headers()
        # Return the batch to STAGING so it is once again in a legal source
        # state for commit.
        get_success_data(api.uncommit_abolishment_batch(batch["id"], fin))
        resp = api.commit_abolishment_batch(batch["id"], fin)
        data = validate_success(resp, 200)
        assert data["status"] == "COMMITTED"
        campaign = get_success_data(
            api.get_donor_campaign(ctx["campaign"]["id"], fin)
        )
        assert campaign["committed_cents"] == 1550000

    def test_campaign_create_safety_error_beats_referential_error(self, api):
        """PRD §2.7: "When several checks could fail on one request, the
        earliest tier's error is returned"
        PRD §3.1: "any attempt to create a donor campaign earmarked to that
        seller as a hospital is rejected with `ERR_EARMARK_TARGET_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/campaign_create_safety_error_beats_referential_error
        """
        set_clock()
        admin = make_platform_admin_headers()
        db_org = get_success_data(
            api.create_source_organization(
                create_source_organization_payload(
                    name="Apex Receivables LLC", org_type="DEBT_BUYER",
                    state_code="FL",
                ),
                admin,
            )
        )
        get_success_data(api.suspend_source_organization(db_org["id"], admin))
        resp = api.create_donor_campaign(
            {
                "name": "Bad Earmark",
                "earmark_type": "HOSPITAL",
                "goal_cents": 500000,
                "earmark_source_org_id": db_org["id"],
            },
            make_donor_relations_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_EARMARK_TARGET_SUSPENDED, 409)
        from test_helpers import validate_paginated

        rows, meta = validate_paginated(
            api.list_donor_campaigns(make_donor_relations_headers())
        )
        assert meta["total_count"] == 0, "no campaign may be created"

    def test_campaign_earmark_to_active_hospital_accepted(self, api):
        """PRD §3.1: "Suspension has two immediate consequences: any attempt to
        submit one of that seller's portfolios is rejected with
        `ERR_SOURCE_ORG_SUSPENDED`, and any attempt to create a donor campaign
        earmarked to that seller as a hospital is rejected with
        `ERR_EARMARK_TARGET_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/campaign_create_safety_error_beats_referential_error
        """
        set_clock()
        admin = make_platform_admin_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        resp = api.create_donor_campaign(
            {
                "name": "Good Earmark",
                "earmark_type": "HOSPITAL",
                "goal_cents": 500000,
                "earmark_source_org_id": org["id"],
            },
            make_donor_relations_headers(),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "OPEN"
        assert data["earmark_source_org_id"] == org["id"]


class TestContractCovenants:
    def test_execute_with_covenant_false_rejected(self, api):
        """PRD §3.4: "Both covenants must be true; a missing covenant is
        rejected with `ERR_COLLECTION_COVENANT_MISSING`."

        Design: Corner/validations/contract_execute_covenant_false_rejected
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        contract = get_success_data(
            api.create_contract(
                pf["id"],
                create_contract_payload(
                    pf["version"], collection_prohibition=False, no_resale=True
                ),
                make_contract_manager_headers(),
            )
        )
        resp = api.execute_contract(
            contract["id"], make_contract_manager_headers()
        )
        validate_error(resp, ApiErrorId.ERR_COLLECTION_COVENANT_MISSING, 422)
        fetched = get_success_data(
            api.get_contract(contract["id"], make_contract_manager_headers())
        )
        assert fetched["status"] == "DRAFT"
        portfolio = get_success_data(
            api.get_portfolio(pf["id"], make_contract_manager_headers())
        )
        assert portfolio["status"] == "PRICED"


class TestSegregationOfDuties:
    def test_settle_by_executor_rejected_then_other_officer_succeeds(self, api):
        """PRD §3.4: "Settlement belongs to a `FinanceOfficer` — and segregation
        of duties is enforced: the settler's `X-User-ID` must differ from
        `executed_by`, or the settle is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/contract_settle_same_user_as_executor_rejected
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers("cm-1")
        contract = get_success_data(
            api.create_contract(
                pf["id"], create_contract_payload(pf["version"]), cm
            )
        )
        get_success_data(api.execute_contract(contract["id"], cm))
        # A FinanceOfficer presenting the executor's id is rejected.
        resp = api.settle_contract(
            contract["id"], make_finance_officer_headers("cm-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)
        # A different FinanceOfficer settles successfully.
        resp = api.settle_contract(
            contract["id"], make_finance_officer_headers("fin-9")
        )
        data = validate_success(resp, 200)
        assert data["status"] == "SETTLED"
        assert data["settled_by"] == "fin-9"
        portfolio = get_success_data(
            api.get_portfolio(pf["id"], make_finance_officer_headers())
        )
        assert portfolio["status"] == "SETTLED"


class TestPriceDrift:
    def test_execute_blocked_after_repricing(self, api):
        """PRD §3.4: "The portfolio's current `quoted_price_cents` must still
        equal the pinned `contract_price_cents`; if a re-quote has drifted the
        price, execution is rejected with `ERR_PRICE_DRIFT`."
        PRD §3.3: "Re-quoting a `PRICED` portfolio recomputes under the same
        screening-completeness preconditions and overwrites the quote; any
        `DRAFT` contract keeps the snapshot it pinned, with the divergence
        surfaced later at execution as a price-drift failure."

        Design: Corner/validations/price_drift_blocks_execute_after_repricing
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers()
        contract = get_success_data(
            api.create_contract(
                pf["id"], create_contract_payload(pf["version"]), cm
            )
        )
        assert contract["contract_price_cents"] == 37500
        # Looser policy (multiplier 10) makes every account eligible, then a
        # re-screen back-edge plus re-quote drifts the pinned price.
        eo = make_eligibility_officer_headers()
        loose = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="TX Loose 1000%",
                    state_code="NM",
                    fpl_multiplier=10.0,
                ),
                eo,
            )
        )
        get_success_data(api.activate_eligibility_policy(loose["id"], eo))
        run2 = get_success_data(
            api.create_screening_run(pf["id"], loose["id"], eo)
        )
        get_success_data(api.execute_screening_run(run2["id"], eo))
        analyst_resp = api.price_quote_portfolio(
            pf["id"], make_portfolio_analyst_headers()
        )
        repriced = validate_success(analyst_resp, 200)
        assert repriced["quoted_price_cents"] == 55000  # 2200000 * 0.025 * 1.0
        resp = api.execute_contract(contract["id"], cm)
        validate_error(resp, ApiErrorId.ERR_PRICE_DRIFT, 409)
        fetched = get_success_data(api.get_contract(contract["id"], cm))
        assert fetched["status"] == "DRAFT"


class TestFundingCoverage:
    def test_commit_insufficient_funding_atomic_rejection(self, api):
        """PRD §3.5: "If every candidate is exhausted with need outstanding, the
        entire commit is rejected with `ERR_INSUFFICIENT_FUNDING` — the
        reservation is atomic and no campaign is partially drawn on failure."

        Design: Corner/validations/batch_commit_insufficient_funding_atomic_rejection
        """
        ctx = setup_standard_settled()
        fin = make_finance_officer_headers()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "General Relief Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 102987},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        funded = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        # fee round_half_up(102987 * 0.029) = 2987 -> net 100000
        assert funded["raised_cents"] == 100000
        a1, a2 = ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]
        batch = stage_batch(ctx["portfolio"], [a1, a2])
        assert batch["total_abolished_cents"] == 1550000
        resp = api.commit_abolishment_batch(batch["id"], fin)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING, 402)
        fetched = get_success_data(api.get_abolishment_batch(batch["id"], fin))
        assert fetched["status"] == "STAGING"
        campaign_after = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert campaign_after["committed_cents"] == 0


class TestBatchReversibility:
    def test_reverse_blocked_when_any_letter_sent(self, api):
        """PRD §3.6: "A `FinanceOfficer` may reverse a `FINALIZED` batch,
        supplying a `reason` recorded as `reversed_reason`, only while none of
        the batch's artifacts has crossed an outer wall: no letter may be
        `SENT`, `DELIVERED`, or `UNDELIVERABLE`; no credit-deletion request may
        be `ACKNOWLEDGED`; and no tax record may be `FILED` or `EXEMPT`. Any
        such artifact makes the batch irreversible and the reversal is rejected
        with `ERR_BATCH_IRREVERSIBLE`."

        Design: Corner/validations/letter_reverse_blocked_when_any_letter_sent
        """
        ctx = setup_finalized_batch()
        batch = ctx["batch"]
        letter = ctx["letters"][0]
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        get_success_data(api.send_notification_letter(letter["id"], dro))
        resp = api.reverse_abolishment_batch(batch["id"], "too late", fin)
        validate_error(resp, ApiErrorId.ERR_BATCH_IRREVERSIBLE, 409)
        fetched = get_success_data(api.get_abolishment_batch(batch["id"], fin))
        assert fetched["status"] == "FINALIZED"
        a1 = get_success_data(
            api.get_account(ctx["accounts"][0]["id"], fin)
        )
        assert a1["lifecycle_status"] == "ABOLISHED"
        portfolio = get_success_data(api.get_portfolio(ctx["portfolio"]["id"], fin))
        assert portfolio["abolished_face_value_cents"] == 1550000


class TestMilestoneUniquenessAndCompletion:
    def test_duplicate_milestone_code_rejected_within_partnership(self, api):
        """PRD §3.9: "with a `code` unique within the partnership (a repeat is
        rejected with `ERR_DUPLICATE_MILESTONE_CODE`)"

        Design: Corner/validations/duplicate_milestone_code_rejected_within_partnership
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        hp = get_success_data(
            api.create_hospital_partnership(
                {"source_org_id": org["id"], "fap_baseline_score": 10,
                 "fap_target_score": 90},
                dro,
            )
        )
        get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                {"code": "FAP-1", "description": "first", "weight": 10,
                 "due_date": "2026-12-31"},
                dro,
            )
        )
        resp = api.create_partnership_milestone(
            hp["id"],
            {"code": "FAP-1", "description": "dupe", "weight": 20,
             "due_date": "2026-12-31"},
            dro,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MILESTONE_CODE, 409)
        from test_helpers import validate_paginated

        rows, meta = validate_paginated(
            api.list_partnership_milestones(dro, params={"partnership_id": hp["id"]})
        )
        assert meta["total_count"] == 1, "the partnership still has one milestone"

    def test_completion_gates_stack_terminal_then_target(self, api):
        """PRD §3.9: "Completion requires two gates, both enforced when the
        officer completes an `ACTIVE` partnership: every milestone must sit in a
        terminal state — `MET`, `MISSED`, or `WAIVED` — otherwise the completion
        is rejected with `ERR_MILESTONE_NOT_TERMINAL`; and the
        `fap_current_score` must be at least the `fap_target_score`, with
        equality satisfying the gate, otherwise the completion is rejected with
        `ERR_FAP_TARGET_NOT_MET`."

        Design: Corner/validations/partnership_complete_blocked_below_fap_target
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        hp = get_success_data(
            api.create_hospital_partnership(
                {"source_org_id": org["id"], "fap_baseline_score": 10,
                 "fap_target_score": 90},
                dro,
            )
        )
        get_success_data(api.activate_hospital_partnership(hp["id"], dro))
        m30 = get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                {"code": "M30", "description": "m30", "weight": 30,
                 "due_date": "2026-12-31"},
                dro,
            )
        )
        # Gate 1: a PENDING milestone blocks completion.
        resp = api.complete_hospital_partnership(hp["id"], dro)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_TERMINAL, 409)
        # Marking it MET lifts the score to 100.
        get_success_data(api.mark_milestone_met(m30["id"], dro))
        # A terminal milestone cannot transition again.
        resp = api.mark_milestone_missed(m30["id"], dro)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Gate 2 satisfied: completion succeeds.
        resp = api.complete_hospital_partnership(hp["id"], dro)
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"
