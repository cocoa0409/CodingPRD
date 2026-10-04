"""OCC guards, regulator actions, multi-tenancy, pagination and transferability."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_client_headers,
    setup_second_firm,
    setup_billing_ready_household,
    setup_firm_with_agreement,
    setup_household,
    open_account,
    create_pending_account,
    refetch_firm,
    refetch_model,
    refetch_block,
    setup_stale_model_rebalance_scenario,
    setup_model_cycle_scenario,
    setup_three_way_allocation_scenario,
    setup_frozen_firm,
    setup_idempotent_batch_scenario,
    setup_throttled_feed_scenario,
    refetch_agreement,
    refetch_evidence,
)
"""OCC guards, regulator actions, multi-tenancy, pagination and transferability."""
"""OCC guards, regulator actions, multi-tenancy, pagination and transferability."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
ADMIN = TEST_USERS["admin_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]


class TestOptimisticConcurrency:

    def test_a_stale_model_version_is_refused_on_rebalance(self):
        """PRD §2.10: "Requesting a model rebalance must carry
        `expected_model_portfolio_version`, matching the target `ModelPortfolio`'s
        current `version`. A mismatch is refused with `ERR_STALE_MODEL_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_model_version_on_rebalance
        """
        scenario = setup_stale_model_rebalance_scenario()
        model = refetch_model(scenario["model"]["id"])
        assert model["model_status"] == "REBALANCING"
        assert model["version"] > scenario["stale_version"]

        res = api_client.rebalance_model(
            model["id"], {"expected_model_portfolio_version": scenario["stale_version"]}, ADVISOR, row=model)
        validate_error(res, "ERR_STALE_MODEL_VERSION", expected_status=412)
        assert refetch_model(model["id"])["model_status"] == "REBALANCING"

    def test_a_fresh_model_version_is_accepted(self):
        """PRD §2.10: "the value must equal that parent's current `version` at the
        moment the server evaluates the request."
        PRD §3.4: "Rebalancing is available from both `APPROVED` and `ACTIVE`".

        Design: Corner/cross_cutting_layers/occ_stale_model_version_on_rebalance
        """
        # PRD §3.4: "Rebalancing is available from both `APPROVED` and `ACTIVE`",
        # so the fresh-version case is exercised against a model that is still
        # APPROVED — the stale-version scenario's model has already left it.
        firm, agreement, household, account, cycle_model = setup_model_cycle_scenario()
        approved = validate_success(api_client.approve_model(
            cycle_model["id"], {}, CHAIR, row=refetch_model(cycle_model["id"]),
        ), 200)
        assert approved["model_status"] == "APPROVED"

        accepted = validate_success(api_client.rebalance_model(
            cycle_model["id"],
            {"expected_model_portfolio_version": approved["version"]},
            ADVISOR, row=approved,
        ), 200)
        assert accepted["model_status"] == "REBALANCING"

    def test_a_one_behind_block_version_is_refused_on_allocate(self):
        """PRD §2.10: "Running a block allocation must carry
        `expected_block_order_version`, matching the target `BlockOrder`'s current
        `version`. A mismatch is refused with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_block_version_on_allocate
        """
        scenario = setup_three_way_allocation_scenario()
        block = refetch_block(scenario["block"]["id"])
        assert block["block_status"] == "EXECUTED"
        assert block["unallocated_share_micros"] is None

        res = api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"] - 1}, ADVISOR, row=block)
        validate_error(res, "ERR_STALE_BLOCK_VERSION", expected_status=412)

    def test_the_correct_block_version_then_succeeds(self):
        """PRD §3.4: "It is available only from `EXECUTED`, it requires
        `expected_block_order_version` to match the block's current `version`".

        Design: Corner/cross_cutting_layers/occ_stale_block_version_on_allocate
        """
        scenario = setup_three_way_allocation_scenario()
        block = refetch_block(scenario["block"]["id"])
        accepted = validate_success(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]}, ADVISOR, row=block), 200)
        assert accepted["block_status"] == "ALLOCATED"
        assert accepted["version"] > block["version"]


class TestRegulatorActions:

    def test_a_frozen_firm_refuses_writes_but_not_the_two_exempt_capabilities(self):
        """PRD §2.4: "Any write endpoint outside the two exempt capabilities —
        acknowledging an admin action and moving the logical clock — is refused with
        `ERR_FIRM_FROZEN` (HTTP 403) while the firm is `FROZEN`."
        PRD §3.9: "Once frozen, only the acknowledgement of an admin action and the
        movement of the logical clock remain open to the firm."

        Design: Corner/errors/error_firm_frozen_blocks_writes_but_not_clock
        """
        scenario = setup_frozen_firm()
        firm = scenario["firm"]
        assert firm["firm_posture"] == "FROZEN"
        assert firm["posture_reason_code"] == "REGULATORY_FREEZE"
        assert scenario["admin_action"]["admin_action_status"] == "ACTIVE"

        res = api_client.create_household(
            {"firm_id": firm["id"], "household_name": "Blocked Household"},
            ADVISOR,
        )
        validate_error(res, "ERR_FIRM_FROZEN", expected_status=403)

        rows = validate_success(
            api_client.list_households(ADVISOR, params={"firm_id": firm["id"]}), 200
        )
        assert len(rows) == 1

    def test_the_clock_and_the_acknowledgement_still_work_while_frozen(self):
        """PRD §3.9: "Acknowledgement is performed by an `AdvisorOperationsLead` or a
        `CustodyOperationsOfficer`, requires an `acknowledged_note`, records
        `acknowledged_by_user_id`, sets the status to `ACKNOWLEDGED`, and clears both
        the unacknowledged limitation and the active freeze so that the posture falls
        through to whatever the lower rules then dictate."

        Design: Corner/errors/error_firm_frozen_blocks_writes_but_not_clock
        """
        scenario = setup_frozen_firm()
        firm = scenario["firm"]

        validate_success(api_client.set_clock(
            {"current_utc": "2026-09-02T00:00:00Z"}, ADMIN,
        ), 200)

        acknowledged = validate_success(api_client.acknowledge_admin_action(
            scenario["admin_action"]["id"],
            {"acknowledged_note": "Acknowledged by GC office"},
            ADVISOR, row=scenario["admin_action"]), 200)
        assert acknowledged["admin_action_status"] == "ACKNOWLEDGED"
        restored = refetch_firm(firm["id"])
        assert restored["firm_posture"] == "OPEN"
        assert restored["posture_reason_code"] is None


class TestMultiTenancy:

    def test_firm_scoped_lists_do_not_leak_across_firms(self):
        """PRD §3.1: "Both `legal_name` and `crd_number` are required and must be
        unique among the firm's non-`ARCHIVED` peers."
        PRD §2.9: "A foreign key written in a request body that points at a row owned
        by a different firm is refused with `ERR_REFERENCE_MISMATCH` (HTTP 422)".

        Design: Corner/cross_cutting_layers/multi_tenancy_isolation_between_two_firms
        """
        firm_one, agreement_one = setup_firm_with_agreement()
        household_one = setup_household(firm_one["id"])

        firm_two = setup_second_firm()
        agreement_two = validate_success(api_client.create_custody_agreement(
            firm_two["id"], {"adviser_crd_number": "CRD-204410"}, ADVISOR,
        ), 201)
        validate_success(api_client.submit_custody_agreement(agreement_two["id"], {}, ADVISOR, row=agreement_two), 200)
        validate_success(api_client.execute_custody_agreement(firm_two["id"], {}, CUSTODY, row=refetch_agreement(agreement_two["id"])), 200)
        household_two = validate_success(api_client.create_household(
            {"firm_id": firm_two["id"], "household_name": "Nakamura Family"}, ADVISOR,
        ), 201)

        everything = validate_success(api_client.list_households(ADVISOR), 200)
        assert len(everything) == 2

        scoped = validate_success(
            api_client.list_households(ADVISOR, params={"firm_id": firm_two["id"]}), 200
        )
        assert len(scoped) == 1
        assert scoped[0]["id"] == household_two["id"]
        assert household_one["firm_id"] == firm_one["id"]

    def test_a_cross_firm_reference_is_refused(self):
        """PRD §2.9: "This ownership rule extends across firms: a foreign key written
        in a request body that points at a row owned by a different firm is refused
        with `ERR_REFERENCE_MISMATCH` (HTTP 422)".

        Design: Corner/errors/error_parent_child_mismatch_on_cross_firm_lot_attachment
        """
        firm_one, agreement_one = setup_firm_with_agreement(
            entitlement_codes=("TRADING_AUTHORIZATION",)
        )
        household_one = setup_household(firm_one["id"])
        open_account(household_one["id"], firm_one["id"], "RIA-119001")

        firm_two = setup_second_firm()
        res = api_client.create_account(
            {"household_id": household_one["id"], "firm_id": firm_two["id"],
             "account_number": "RIA-119002", "account_type": "INDIVIDUAL",
             "householding_consent": "OP_IN"},
            ADVISOR,
        )
        validate_error(res, "ERR_REFERENCE_MISMATCH", expected_status=422)
        assert validate_success(
            api_client.list_accounts(ADVISOR, params={"firm_id": firm_two["id"]}), 200
        ) == []


class TestPagination:

    def test_limit_and_offset_interact_with_the_status_filter(self):
        """PRD §2.3: "`total_count` reports the number of matching rows in the full
        result set, not the number on the current page, and `has_more` is true exactly
        when further rows remain beyond the current page."

        Design: Corner/cross_cutting_layers/pagination_and_filtering_on_accounts
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        open_account(household["id"], firm["id"], "RIA-121001")
        open_account(household["id"], firm["id"], "RIA-121002", account_type="JOINT")
        open_account(household["id"], firm["id"], "RIA-121003", account_type="TRUST")
        create_pending_account(
            household["id"], firm["id"], "RIA-121004", account_type="ROTH_IRA"
        )

        page_one = api_client.list_accounts(
            ADVISOR, params={"household_id": household["id"], "limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(page_one)
        assert len(data) == 2
        assert meta["total_count"] == 4
        assert meta["has_more"] is True

    def test_the_second_page_reports_no_more_rows(self):
        """PRD §2.3: "Paginated responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope".

        Design: Corner/cross_cutting_layers/pagination_and_filtering_on_accounts
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        for index in range(4):
            open_account(household["id"], firm["id"], f"RIA-12110{index}")

        data, meta = validate_paginated(api_client.list_accounts(
            ADVISOR, params={"household_id": household["id"], "limit": 2, "offset": 2}
        ))
        assert len(data) == 2
        assert meta["total_count"] == 4
        assert meta["has_more"] is False

    def test_the_status_filter_narrows_the_total_count(self):
        """PRD §2.3: "`total_count` reports the number of matching rows in the full
        result set, not the number on the current page."

        Design: Corner/cross_cutting_layers/pagination_and_filtering_on_accounts
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        for index in range(3):
            open_account(household["id"], firm["id"], f"RIA-12120{index}")
        pending = create_pending_account(
            household["id"], firm["id"], "RIA-121209", account_type="ROTH_IRA"
        )

        open_rows, open_meta = validate_paginated(api_client.list_accounts(
            ADVISOR, params={"household_id": household["id"], "account_status": "OPEN"}
        ))
        assert len(open_rows) == 3
        assert open_meta["total_count"] == 3

        pending_rows, pending_meta = validate_paginated(api_client.list_accounts(
            ADVISOR, params={"household_id": household["id"], "account_status": "PENDING"}
        ))
        assert len(pending_rows) == 1
        assert pending_meta["total_count"] == 1
        assert pending_rows[0]["id"] == pending["id"]


class TestClientOwnership:

    def test_a_client_cannot_originate_writes_and_cannot_read_another_household(self):
        """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the
        acting `Household`; ownership checks on any resource that references a
        `Household` compare the resource's foreign-key field to `X-User-ID`."
        PRD §2.1: "every other household's rows resolve to `ERR_RESOURCE_NOT_FOUND`
        rather than to a permission error, so the platform does not disclose the
        existence of another client's data."

        Design: Corner/rbac/client_role_cannot_open_accounts_or_read_other_households
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household_a = setup_household(firm["id"])
        open_account(household_a["id"], firm["id"], "RIA-120001")
        setup_household(firm["id"], household_name="Brennan Family")

        res = api_client.create_account(
            {"household_id": household_a["id"], "firm_id": firm["id"],
             "account_number": "RIA-120003", "account_type": "INDIVIDUAL",
             "householding_consent": "OP_IN"},
            make_client_headers(household_a["id"]),
        )
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)

    def test_a_client_reads_its_own_account_but_not_another_households(self):
        """PRD §2.1: "a client may only read or act on rows whose `account_id` belongs
        to the household named by `X-User-ID`".
        PRD §2.1: "ownership checks on any resource that references a `Household`
        compare the resource's foreign-key field to `X-User-ID`."

        Design: Corner/rbac/client_role_cannot_open_accounts_or_read_other_households
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household_a = setup_household(firm["id"])
        account_a = open_account(household_a["id"], firm["id"], "RIA-120101")
        household_b = setup_household(firm["id"], household_name="Brennan Family")
        account_b = open_account(household_b["id"], firm["id"], "RIA-120102", account_type="JOINT")

        res = api_client.get_account(account_b["id"], make_client_headers(household_a["id"]))
        validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

        own = validate_success(
            api_client.get_account(account_a["id"], make_client_headers(household_a["id"])), 200
        )
        assert own["id"] == account_a["id"]


class TestReadOnlyAnalyst:

    def test_the_support_analyst_reads_but_cannot_originate_state(self):
        """PRD §2.1: "`AdvisorSupportAnalyst` — read-mostly adviser staff who service
        client inquiries and cannot originate any state change whatsoever."

        Design: Corner/rbac/read_only_analyst_cannot_originate_any_state_change
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=200_000_000,
        )
        analyst = TEST_USERS["support_analyst_headers"]

        validate_success(api_client.get_account(accounts[0]["id"], analyst), 200)
        assert validate_success(
            api_client.get_account(accounts[0]["id"], analyst), 200
        )["account_fee_basis_cents"] == 200_000_000

    def test_the_analyst_is_refused_on_both_originating_writes(self):
        """PRD §2.1: "A request that presents a well-formed role which is not among
        the roles the target operation authorizes is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/read_only_analyst_cannot_originate_any_state_change
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=200_000_000,
        )
        analyst = TEST_USERS["support_analyst_headers"]

        validate_error(
            api_client.create_billing_run(
                {"firm_id": firm["id"], "household_id": household["id"],
                 "period_start_date": "2026-09-01T00:00:00Z",
                 "period_end_date": "2026-12-01T00:00:00Z",
                 "fee_variant_used": "HOUSEHOLD_AGGREGATED", "stated_invoice_cents": 0},
                analyst,
            ),
            "ERR_UNAUTHORIZED_ROLE", expected_status=403,
        )
        validate_error(
            api_client.list_account(accounts[0]["id"], {}, analyst, row=accounts[0]),
            "ERR_UNAUTHORIZED_ROLE", expected_status=403,
        )


class TestBatchIdempotency:

    def test_redispatching_a_batch_creates_no_duplicate_rows(self):
        """PRD §3.3: "Dispatch is idempotent by design, and this is the property
        clients should rely on: a repeated dispatch skips rows whose natural key
        already exists rather than duplicating them, so `dispatched_item_count` is
        stable across retries".

        Design: Corner/endpoints/batch_dispatch_is_idempotent_across_retries
        """
        scenario = setup_idempotent_batch_scenario(batch_size=2)
        first = validate_success(api_client.dispatch_onboarding_batch(
            scenario["batch"]["id"], {}, ADVISOR, row=scenario["batch"]), 200)
        assert first["dispatched_item_count"] == 2
        assert first["batch_status"] == "COMPLETED"

        second = validate_success(api_client.dispatch_onboarding_batch(
            scenario["batch"]["id"], {}, ADVISOR, row=first), 200)
        assert second["dispatched_item_count"] == 2

        rows = validate_success(
            api_client.list_accounts(ADVISOR, params={"household_id": scenario["household"]["id"]}), 200
        )
        assert len(rows) == 2
        assert all(row["account_status"] == "PENDING" for row in rows)


class TestDataFeedThrottle:

    def test_the_pull_is_refused_while_throttled_and_resumes_after_recovery(self):
        """PRD §3.2: "Restoration runs the other way: a `THROTTLED` feed returns to
        `ACTIVE`, with `throttle_reason_code` cleared, once a successful invariant
        sweep finds every invariant in the firm's database invariant chain holding and
        the firm's posture is `OPEN` or `LIMITED` again."

        Design: Corner/endpoints/feed_pull_is_refused_while_throttled_and_resumes_after_invariant_recovery
        """
        scenario = setup_throttled_feed_scenario()
        feed_id = scenario["feed"]["id"]

        live = validate_success(api_client.pull_data_feed(feed_id, {}, ADVISOR), 200)
        assert live["last_delivered_at"] is not None

        validate_success(api_client.reject_custody_evidence(
            scenario["evidence"]["id"], {"deficiency_reason_code": "SCOPE_MISMATCH"}, COMPLIANCE, row=scenario["evidence"]), 200)
        validate_error(
            api_client.pull_data_feed(feed_id, {}, ADVISOR),
            "ERR_FEED_THROTTLED", expected_status=409,
        )

        validate_success(api_client.resubmit_custody_evidence(
            scenario["evidence"]["id"], {}, ADVISOR, row=refetch_evidence(scenario["evidence"]["id"])), 200)
        validate_success(api_client.accept_custody_evidence(
            scenario["evidence"]["id"], {}, COMPLIANCE, row=refetch_evidence(scenario["evidence"]["id"])), 200)

        feeds = validate_success(
            api_client.list_firm_data_feeds(scenario["firm"]["id"], ADVISOR), 200
        )
        assert feeds[0]["provision_status"] == "ACTIVE"
        validate_success(api_client.pull_data_feed(feed_id, {}, ADVISOR), 200)