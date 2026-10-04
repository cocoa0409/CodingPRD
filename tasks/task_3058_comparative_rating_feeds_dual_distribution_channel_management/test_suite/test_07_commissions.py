"""Agent economics: commission schedules (OCC), statement generation with
marginal-tier per-policy rounding, finalize/pay/claw-back, and the conserved
commission ledger."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    bind_agent_policy_via_referral,
    create_agent,
    create_agent_quote,
    create_appointment,
    create_appointed_agent,
    create_consumer,
    create_schedule,
    get_success_data,
    make_agent_headers,
    set_clock,
    setup_bound_agent_policy,
    setup_product_with_feed,
    submit_agent_quote,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["carrier_admin_headers"]

FLAT_PRODUCT = {
    "coverage_rates": {"FLAT": {"TIER_C": 99995, "TIER_D": 730000}},
    "min_premium_cents": 0,
}


def _bind_flat_policy(agent, consumer, product_id, tier="TIER_C"):
    return bind_agent_policy_via_referral(
        consumer, agent, product_id,
        coverages=[{"coverage_code": "FLAT", "tier": tier}],
    )["policy"]


class TestCommissionScheduleOCC:
    def test_occ_commission_schedule_stale_agent_version_rejected(self, api):
        """PRD §2.7: "Creating a commission schedule for an agent requires the
        request to carry `expected_agent_version`, equal to the agent's current
        `version` as the client last observed it. If the agent's `version` has
        advanced since that observation, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_commission_schedule_stale_agent_version_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_appointed_agent()
        agent_now = get_success_data(api.get_agent(agent["id"], ADMIN))
        observed_version = agent_now["version"]

        schedule1 = create_schedule(agent["id"])

        resp = api.create_commission_schedule(
            agent["id"],
            {
                "line_of_business": "AUTO",
                "effective_start": "2026-01-01T00:00:00Z",
                "tiers": [{"up_to_cents": None, "rate_pct": 0.12}],
                "contingent_bonus_eligible": False,
                "expected_agent_version": observed_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        rows, meta = validate_paginated(
            api.list_agent_commission_schedules(agent["id"], ADMIN, params={"status": "ACTIVE"})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == schedule1["id"]


class TestStatementGeneration:
    def test_commission_earned_per_policy_rounding_order_mode_b(self, api):
        """PRD §2.6: "Statement commissions are rounded **per policy first**, then
        summed across the statement."
        PRD §3.6: "The policy's commission is rounded half-up to integer cents
        **per policy** and recorded as the policy's `per_policy_commission_cents`;
        the statement's `commission_cents` is the sum of those rounded per-policy
        values."

        Design: Difficulty/combinatorial_formula/commission_earned_per_policy_rounding_order_mode_b
        """
        set_clock("2026-01-05T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            },
            feed_start="2026-01-01T00:00:00Z",
        )
        agent = create_appointed_agent()
        create_schedule(
            agent["id"],
            tiers=[{"up_to_cents": 1000000, "rate_pct": 0.10},
                   {"up_to_cents": None, "rate_pct": 0.12}],
        )
        consumer = create_consumer()
        pol1 = _bind_flat_policy(agent, consumer, ctx["product"]["id"])
        pol2 = _bind_flat_policy(agent, consumer, ctx["product"]["id"])

        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        assert stmt["written_premium_cents"] == 199990
        # round_half_up(99995 * 0.10) = round_half_up(9999.5) = 10000 per policy
        assert stmt["commission_cents"] == 20000
        assert stmt["commission_cents"] != 19999

        pol1_after = get_success_data(api.get_policy(pol1["id"], ADMIN))
        pol2_after = get_success_data(api.get_policy(pol2["id"], ADMIN))
        assert pol1_after["per_policy_commission_cents"] == 10000
        assert pol2_after["per_policy_commission_cents"] == 10000

    def test_commission_earned_line_items_carry_per_policy_rounded_commission(self, api):
        """PRD §3.6: "The statement is born `DRAFT` with its `line_items` — one
        line per included policy carrying `policy_id`, `premium_cents`, and
        `commission_cents`, ordered by policy `created_at` ascending — plus its
        `written_premium_cents` total and a `clawback_cents` of 0"
        PRD §2.6: "Statement commissions are rounded **per policy first**, then
        summed across the statement."

        Design: Difficulty/combinatorial_formula/commission_earned_per_policy_rounding_order_mode_b
        """
        set_clock("2026-01-05T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            },
            feed_start="2026-01-01T00:00:00Z",
        )
        agent = create_appointed_agent()
        create_schedule(
            agent["id"],
            tiers=[{"up_to_cents": 1000000, "rate_pct": 0.10},
                   {"up_to_cents": None, "rate_pct": 0.12}],
        )
        consumer = create_consumer()
        pol1 = _bind_flat_policy(agent, consumer, ctx["product"]["id"])
        # distinct policy created_at values so the created_at-ASC line order is
        # not decided by the (random-uuid) tie-break
        set_clock("2026-01-06T00:00:00Z")
        pol2 = _bind_flat_policy(agent, consumer, ctx["product"]["id"])

        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        assert stmt["status"] == "DRAFT"
        assert len(stmt["line_items"]) == 2
        # line_items ordered by policy created_at ascending
        assert stmt["line_items"][0]["policy_id"] == pol1["id"]
        assert stmt["line_items"][1]["policy_id"] == pol2["id"]
        for line in stmt["line_items"]:
            # round_half_up(99995 * 0.10) = 10000 per policy, not 9999
            assert line["premium_cents"] == 99995
            assert line["commission_cents"] == 10000

    def test_commission_statement_includes_only_policies_bound_in_half_open_period(self, api):
        """PRD §3.6: "The eligible policies are the agent's bound policies whose
        policy `created_at` falls within the window, processed strictly in policy
        `created_at` ascending order — never by id."
        PRD §3.6: "A `CarrierAdmin` requests a statement for a half-open window
        from `period_start` to `period_end`; the window must satisfy `period_end`
        after `period_start` and not in the future relative to the logical clock
        (`ERR_INVALID_REQUEST`), and it must not overlap any `FINALIZED`, `PAID`,
        or `CLAWED_BACK` statement of the same agent
        (`ERR_STATEMENT_PERIOD_OVERLAP`)."

        Design: Corner/calculations/commission_statement_includes_only_policies_bound_in_half_open_period
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            },
        )
        agent = create_appointed_agent()
        create_schedule(agent["id"])
        consumer = create_consumer()

        pol_in = _bind_flat_policy(agent, consumer, ctx["product"]["id"])

        set_clock("2026-02-01T00:00:00Z")
        pol_out = _bind_flat_policy(agent, consumer, ctx["product"]["id"])

        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        assert len(stmt["line_items"]) == 1
        assert stmt["line_items"][0]["policy_id"] == pol_in["id"]
        assert pol_out["id"] not in [li["policy_id"] for li in stmt["line_items"]]
        assert stmt["written_premium_cents"] == 99995
        assert stmt["commission_cents"] == 10000


class TestStatementLifecycle:
    def test_zero_net_finalized_statement_pay_returns_nothing_to_pay(self, api):
        """PRD §3.6: "Payment moves `FINALIZED → PAID` and requires a positive
        `net_payable_cents` — paying a zero-net statement fails with
        `ERR_NOTHING_TO_PAY`."

        Design: Corner/validations/zero_net_finalized_statement_pay_returns_nothing_to_pay
        """
        set_clock("2026-03-01T00:00:00Z")
        agent = create_appointed_agent()
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-02-01T00:00:00Z",
             "period_end": "2026-03-01T00:00:00Z"},
            ADMIN,
        ))
        finalized = validate_success(api.finalize_commission_statement(stmt["id"], ADMIN))
        assert finalized["status"] == "FINALIZED"

        resp = api.pay_commission_statement(stmt["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_PAY, 409)
        after = get_success_data(api.get_commission_statement(stmt["id"], ADMIN))
        assert after["status"] == "FINALIZED"

    def test_state_beats_business_fiscal_on_draft_statement_clawback(self, api):
        """PRD §2.8: "When a request would fail several checks, the checks are
        evaluated in a fixed priority order and the error of the **lowest**
        priority number is returned."
        PRD §2.8: "6. State-transition legality, including the lazy-state
        errors — quote expiry (`ERR_QUOTE_EXPIRED`), stale rate pin
        (`ERR_RATE_STALE`), product not active (`ERR_PRODUCT_NOT_ACTIVE`), feed
        not published (`ERR_FEED_NOT_PUBLISHED`), policy not in force
        (`ERR_POLICY_NOT_IN_FORCE`) — grouped under the state category whose
        generic member is `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.8: "10. Money rules, always checked last: the direct premium cap
        (`ERR_PREMIUM_CAP_EXCEEDED`), paying an empty statement
        (`ERR_NOTHING_TO_PAY`), a claw-back that would drive a statement negative
        (`ERR_NEGATIVE_COMMISSION`), and terminating an agent holding active
        placements (`ERR_AGENT_HAS_ACTIVE_PLACEMENTS`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_draft_statement_clawback
        """
        set_clock("2026-03-01T00:00:00Z")
        agent = create_appointed_agent()
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-02-01T00:00:00Z",
             "period_end": "2026-03-01T00:00:00Z"},
            ADMIN,
        ))
        assert stmt["status"] == "DRAFT"
        assert stmt["net_payable_cents"] == 0

        resp = api.pay_commission_statement(stmt["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_commission_statement(stmt["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_zero_net_draft_statement_pay_is_state_error_not_fiscal_error(self, api):
        """PRD §2.8: "6. State-transition legality, including the lazy-state
        errors — quote expiry (`ERR_QUOTE_EXPIRED`), stale rate pin
        (`ERR_RATE_STALE`), product not active (`ERR_PRODUCT_NOT_ACTIVE`), feed
        not published (`ERR_FEED_NOT_PUBLISHED`), policy not in force
        (`ERR_POLICY_NOT_IN_FORCE`) — grouped under the state category whose
        generic member is `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.8: "10. Money rules, always checked last: the direct premium cap
        (`ERR_PREMIUM_CAP_EXCEEDED`), paying an empty statement
        (`ERR_NOTHING_TO_PAY`), a claw-back that would drive a statement negative
        (`ERR_NEGATIVE_COMMISSION`), and terminating an agent holding active
        placements (`ERR_AGENT_HAS_ACTIVE_PLACEMENTS`)."
        PRD §3.6: "Payment moves `FINALIZED → PAID` and requires a positive
        `net_payable_cents` — paying a zero-net statement fails with
        `ERR_NOTHING_TO_PAY`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_draft_statement_clawback
        """
        set_clock("2026-03-01T00:00:00Z")
        agent = create_appointed_agent()
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-02-01T00:00:00Z",
             "period_end": "2026-03-01T00:00:00Z"},
            ADMIN,
        ))
        assert stmt["net_payable_cents"] == 0

        resp = api.pay_commission_statement(stmt["id"], ADMIN)
        # Both the state rule (pay requires FINALIZED) and the fiscal rule
        # (net > 0) are violated; the state error reports first.
        assert resp.status_code == 409
        body = resp.json()["data"]
        assert body["error_id"] == "ERR_INVALID_STATE_TRANSITION"
        assert body["error_id"] != "ERR_NOTHING_TO_PAY"

        after = get_success_data(api.get_commission_statement(stmt["id"], ADMIN))
        assert after["status"] == "DRAFT"
        assert after["net_payable_cents"] == 0

    def test_statement_period_overlapping_finalized_statement_rejected(self, api):
        """PRD §3.6: "it must not overlap any `FINALIZED`, `PAID`, or
        `CLAWED_BACK` statement of the same agent (`ERR_STATEMENT_PERIOD_OVERLAP`)."

        Design: Corner/validations/statement_period_overlapping_finalized_statement_rejected
        """
        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        agent = create_appointed_agent()
        stmt1 = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        validate_success(api.finalize_commission_statement(stmt1["id"], ADMIN))

        resp = api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-15T00:00:00Z",
             "period_end": "2026-02-15T00:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP, 409)

        rows, meta = validate_paginated(
            api.list_agent_commission_statements(agent["id"], ADMIN)
        )
        assert len(rows) == 1


class TestClawbackConservation:
    def test_cancel_and_clawback_leave_commission_ledger_conserved(self, api):
        """PRD §3.6: "The clawed amount is the policy's
        `per_policy_commission_cents` minus the portion earned for the days
        actually in force — that earned portion being the per-policy commission
        multiplied by the days in force and divided by `term_days`, rounded
        half-up — and is recorded on both the policy's `clawback_cents` and the
        statement's `clawback_cents`, with `net_payable_cents` recomputed as
        `commission_cents` minus `clawback_cents`."

        Design: Difficulty/compensating_invariant/cancel_and_clawback_leave_commission_ledger_conserved
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_D": 730000}},
                "min_premium_cents": 0,
            },
        )
        agent = create_appointed_agent()
        create_schedule(agent["id"])
        consumer = create_consumer()
        policy = _bind_flat_policy(agent, consumer, ctx["product"]["id"], tier="TIER_D")

        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        validate_success(api.finalize_commission_statement(stmt["id"], ADMIN))
        validate_success(api.pay_commission_statement(stmt["id"], ADMIN))

        set_clock("2026-04-11T00:00:00Z")
        validate_success(api.cancel_policy(policy["id"], ADMIN))

        clawed = validate_success(api.claw_back_commission_statement(
            stmt["id"], {"policy_id": policy["id"]}, ADMIN
        ))
        assert clawed["status"] == "CLAWED_BACK"
        # per-policy commission 73000; earned portion round(73000*100/365) = 20000
        assert clawed["clawback_cents"] == 53000
        assert clawed["net_payable_cents"] == 20000

        policy_after = get_success_data(api.get_policy(policy["id"], ADMIN))
        assert policy_after["earned_premium_cents"] == 200000
        assert policy_after["unearned_premium_cents"] == 530000
        assert policy_after["per_policy_commission_cents"] == 73000
        assert policy_after["clawback_cents"] == 53000
        # conservation: retained 20000 + clawback 53000 == credited 73000
        assert (
            policy_after["per_policy_commission_cents"]
            - policy_after["clawback_cents"]
            + clawed["clawback_cents"]
        ) == 73000

    def test_clawback_recomputes_statement_net_payable(self, api):
        """PRD §3.6: "and is recorded on both the policy's `clawback_cents` and
        the statement's `clawback_cents`, with `net_payable_cents` recomputed as
        `commission_cents` minus `clawback_cents`."

        Design: Difficulty/compensating_invariant/cancel_and_clawback_leave_commission_ledger_conserved
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_D": 730000}},
                "min_premium_cents": 0,
            },
        )
        agent = create_appointed_agent()
        create_schedule(agent["id"])
        consumer = create_consumer()
        policy = _bind_flat_policy(agent, consumer, ctx["product"]["id"], tier="TIER_D")

        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ))
        validate_success(api.finalize_commission_statement(stmt["id"], ADMIN))
        paid = validate_success(api.pay_commission_statement(stmt["id"], ADMIN))
        assert paid["net_payable_cents"] == 73000

        set_clock("2026-04-11T00:00:00Z")
        validate_success(api.cancel_policy(policy["id"], ADMIN))

        clawed = validate_success(api.claw_back_commission_statement(
            stmt["id"], {"policy_id": policy["id"]}, ADMIN
        ))
        # net recomputed: 73000 commission - 53000 clawback
        assert clawed["commission_cents"] == 73000
        assert clawed["clawback_cents"] == 53000
        assert clawed["net_payable_cents"] == 20000
