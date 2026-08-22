"""Systematic plan creation, supersession, revision and execution."""

from test_helpers import (
    ApiErrorId,
    assert_systematic_plan,
    create_plan,
    create_systematic_plan_payload,
    money,
    open_active_account,
    read_account,
    read_plan,
    read_trade,
    setup_account_with_investment_plan,
    setup_due_investment_plan,
    setup_reference_data,
    setup_underfunded_withdrawal_plan,
    shares,
    validate_error,
    validate_paginated,
    validate_success,
    SINGLE_TIER_BREAKPOINT_TIERS,
    WEDNESDAY,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestPlanVersionGate:
    def test_a_stale_account_version_blocks_a_second_plan_creation(self, api):
        """PRD §2.8: "Creating a systematic plan — `POST /systematic-plans` — requires
        `expected_account_version` in the request body — it is a required field, not an
        optional one — carrying the `version` of the target `ShareholderAccount` as the
        client last observed it. If that value does not equal the account's current
        `version`, the creation is rejected with `ERR_STALE_ACCOUNT_VERSION` and HTTP 412."
        PRD §2.8: "Note that a successful plan creation itself increments the account's
        `version`, so a client creating two plans in sequence must re-read the account
        between them."

        Design: Corner/cross_cutting_complexity_layers/stale_account_version_blocks_a_second_systematic_plan_creation
        """
        setup = setup_account_with_investment_plan(amount=300.00)
        stale_version = setup["account_version_at_activation"]

        response = api.create_systematic_plan(
            create_systematic_plan_payload(
                setup["account"]["id"], setup["share_class"]["id"], stale_version,
                plan_type="SYSTEMATIC_INVESTMENT", amount=900.00,
                frequency="MONTHLY", next_run_date="2026-09-01",
            ),
            OPERATOR,
        )
        assert response.status_code == 412
        validate_error(response, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)

        first = read_plan(setup["plan"]["id"])
        assert first["status"] == "ACTIVE"
        assert first["amount"] == money(300.00)

        _, meta = validate_paginated(
            api.list_systematic_plans(
                OPERATOR, params={"account_id": setup["account"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert read_account(setup["account"]["id"])["version"] == stale_version + 1

    def test_a_fresh_account_version_lets_the_new_plan_supersede_the_prior_one(self, api):
        """PRD §2.8: "The protection matters because a new plan of the same `plan_type` and
        `source_share_class_id` terminates the account's prior `ACTIVE` plan of that shape;
        without the gate, a client working from an out-of-date view of the account would
        silently terminate a plan it never saw."
        PRD §3.8: "Creation also requires `expected_account_version` under the version gate
        of §2.8, because a new plan of the same `plan_type` and `source_share_class_id` on
        that account terminates the account's prior `ACTIVE` plan of that shape, moving it to
        `TERMINATED`; a successful creation increments the owning account's `version`."

        Design: Corner/cross_cutting_complexity_layers/fresh_account_version_lets_the_new_plan_supersede_the_prior_one
        """
        setup = setup_account_with_investment_plan(amount=300.00)
        current = read_account(setup["account"]["id"])

        response = api.create_systematic_plan(
            create_systematic_plan_payload(
                setup["account"]["id"], setup["share_class"]["id"], current["version"],
                plan_type="SYSTEMATIC_INVESTMENT", amount=900.00,
                frequency="MONTHLY", next_run_date="2026-09-01",
            ),
            OPERATOR,
        )
        new_plan = validate_success(response, 201)
        assert_systematic_plan(new_plan)
        assert new_plan["status"] == "ACTIVE"
        assert new_plan["amount"] == money(900.00)

        assert read_plan(setup["plan"]["id"])["status"] == "TERMINATED"

        _, meta = validate_paginated(
            api.list_systematic_plans(
                OPERATOR,
                params={"account_id": setup["account"]["id"], "status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1
        assert read_account(setup["account"]["id"])["version"] == current["version"] + 1


class TestPlanLifecycle:
    def test_restricting_the_account_suspends_the_plan_and_reinstating_does_not_resume_it(self, api):
        """PRD §3.2: "A `ComplianceOfficer` may place a restriction, moving
        `ACTIVE → RESTRICTED`; the supplied `restriction_reason` is stamped onto the account,
        every systematic plan on the account that was `ACTIVE` moves to `SUSPENDED` with its
        `suspension_reason` set to `ACCOUNT_RESTRICTED`, and the account's `version`
        increments."
        PRD §3.2: "The same officer may reinstate the account, moving `RESTRICTED → ACTIVE`,
        which clears `restriction_reason` back to null and increments `version`; plans
        suspended by the restriction are deliberately *not* resumed automatically, and must be
        resumed explicitly if the shareholder wants them back."

        Design: Corner/state_machines/restrict_suspends_active_plans_and_reinstate_does_not_resume_them
        """
        setup = setup_account_with_investment_plan(amount=500.00)

        validate_success(
            api.restrict_shareholder_account(
                setup["account"]["id"],
                {"restriction_reason": "Suspicious activity report filed"},
                COMPLIANCE,
            ),
            200,
        )
        suspended = read_plan(setup["plan"]["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "ACCOUNT_RESTRICTED"

        reinstated = validate_success(
            api.reinstate_shareholder_account(setup["account"]["id"], COMPLIANCE), 200
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("restriction_reason") is None
        assert read_plan(setup["plan"]["id"])["status"] == "SUSPENDED"

    def test_a_terminated_plan_cannot_be_revived(self, api):
        """PRD §3.8: "Submitting `TERMINATED` moves the plan `ACTIVE → TERMINATED` or
        `SUSPENDED → TERMINATED` depending on where it stood, after which no further
        execution is possible."
        PRD §3.8: "Any transition not declared here — resuming a plan that is already
        `ACTIVE`, reviving a `TERMINATED` one — answers `ERR_INVALID_PLAN_STATE`."

        Design: Corner/state_machines/terminated_systematic_plan_cannot_be_resumed
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        account = open_active_account(
            registration_type="IRA_TRADITIONAL", primary_owner_name="Tim Terminal"
        )
        plan = create_plan(
            account["id"], base["share_class"]["id"],
            plan_type="SYSTEMATIC_WITHDRAWAL", amount=250.00,
            frequency="QUARTERLY", next_run_date="2026-09-01",
        )
        validate_success(
            api.update_systematic_plan(plan["id"], {"status": "TERMINATED"}, OPERATOR),
            200,
        )

        response = api.update_systematic_plan(plan["id"], {"status": "ACTIVE"}, OPERATOR)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value)

        after = read_plan(plan["id"])
        assert after["status"] == "TERMINATED"
        assert after["executed_count"] == 0


class TestPlanExecution:
    def test_executing_a_due_investment_plan_generates_an_order_and_advances_the_run_date(self, api):
        """PRD §3.8: "A successful run generates one order carrying `originating_plan_id`
        pointing back at the plan: a `PURCHASE` for a `SYSTEMATIC_INVESTMENT` whose
        `gross_amount` is the plan's `amount`, a `REDEMPTION` for a `SYSTEMATIC_WITHDRAWAL`,
        or an `EXCHANGE` for a `SYSTEMATIC_EXCHANGE`."
        PRD §3.8: "The plan's `executed_count` increments, its `last_run_date` is stamped
        with the run date, and its `next_run_date` advances by one month for a `MONTHLY` plan
        or by three months for a `QUARTERLY` plan, with the day-of-month clamped to the last
        day of the target month when the target month is too short to hold it."
        PRD §3.8: "The generated order follows the ordinary capture path: it is created with
        an `execution_status` of `RECEIVED` and a `settlement_status` of `UNSETTLED`, its
        `trade_date` comes from the forward-pricing rule, and a generated purchase reserves
        state-registration capacity exactly as a hand-captured one would."

        Design: Corner/endpoints/plan_execution_generates_a_trade_and_advances_the_next_run_date
        """
        setup = setup_due_investment_plan()

        executed = validate_success(
            api.execute_systematic_plan(setup["plan"]["id"], OPERATOR), 200
        )
        assert executed["executed_count"] == 1
        assert executed["last_run_date"] == WEDNESDAY
        assert executed["next_run_date"] == "2026-09-05"
        assert executed["status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"originating_plan_id": setup["plan"]["id"]})
        )
        assert meta["total_count"] == 1
        generated = read_trade(rows[0]["id"])
        assert generated["trade_type"] == "PURCHASE"
        assert generated["gross_amount"] == money(500.00)
        assert generated["trade_date"] == WEDNESDAY
        assert generated["execution_status"] == "RECEIVED"
        assert generated["settlement_status"] == "UNSETTLED"

    def test_a_withdrawal_plan_worth_more_than_the_position_auto_suspends(self, api):
        """PRD §3.8: "When a `SYSTEMATIC_WITHDRAWAL` runs against a source position whose
        `market_value_amount` is below the plan's `amount`, there is not enough value to
        liquidate: no order is created, `executed_count` and `next_run_date` are both left
        exactly as they were, and the plan moves `ACTIVE → SUSPENDED` with
        `suspension_reason` set to `INSUFFICIENT_POSITION_VALUE`."

        Design: Corner/endpoints/withdrawal_plan_below_position_value_auto_suspends_instead_of_trading
        """
        setup = setup_underfunded_withdrawal_plan()
        assert setup["position"]["market_value_amount"] == money(28275.00)
        assert setup["position"]["shares"] == shares(2827.500)

        executed = validate_success(
            api.execute_systematic_plan(setup["plan"]["id"], OPERATOR), 200
        )
        assert executed["status"] == "SUSPENDED"
        assert executed["suspension_reason"] == "INSUFFICIENT_POSITION_VALUE"
        assert executed["executed_count"] == 0
        assert executed["next_run_date"] == WEDNESDAY

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"originating_plan_id": setup["plan"]["id"]})
        )
        assert meta["total_count"] == 0
