"""The settlement approval chain, the agent book it feeds, and the derived
allocation fields a settlement read exposes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    settle_settlement,
    set_logical_clock,
    setup_approved_settlement,
    setup_terminated_agent_with_customer,
    validate_error,
    validate_paginated,
    validate_success,
)

SETTLEMENT_OPERATOR = TEST_USERS["settlement_operator_headers"]


class TestSettlementApprovalGuards:
    """What a settlement exposes once it has been approved."""

    def test_settlement_get_exposes_every_derived_allocation_field(self, api):
        """PRD §3.6: "A computed split can also be inspected without being
        persisted, through an evaluation that returns the settled-shaped figures
        for `agent_share_cents`, `owner_operator_share_cents`,
        `company_share_cents`, `oa_premium_cents`, `insurance_premium_cents`,
        `escrow_withholding_cents`, `maintenance_withholding_cents`,
        `advance_repayment_cents`, `net_owner_operator_pay_cents`,
        `net_agent_pay_cents`, and `settled_total_cents`."
        PRD §3.8: "If the capacity owner's escrow balance already stands at or
        above the floor of 100000 cents, the withholding is zero: a solvent
        driver is not asked to contribute again."

        Design: Corner/endpoints/settlement_get_exposes_every_derived_allocation_field
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=True)
        settlement = get_success_data(
            api.get_settlement(bundle["settlement"]["id"], SETTLEMENT_OPERATOR)
        )

        assert settlement["status"] == "APPROVED"
        assert settlement["linehaul_revenue_allocated_cents"] == 180000
        assert settlement["fuel_surcharge_allocated_cents"] == 32400
        assert settlement["accessorial_allocated_cents"] == 12000
        assert settlement["commissionable_base_cents"] == 192000
        assert settlement["oa_premium_cents"] == 2880
        assert settlement["insurance_premium_cents"] == 4461
        assert settlement["escrow_withholding_cents"] == 0
        assert settlement["advance_repayment_cents"] == 0
        assert settlement["net_owner_operator_pay_cents"] == 134691
        assert settlement["net_agent_pay_cents"] == 23040
        assert settlement["settled_total_cents"] == 224400

    def test_approved_settlement_conserves_the_union_base(self, api):
        """PRD §3.6: "Three fiscal guards ride along: the `settled_total_cents`
        must equal the sum of `linehaul_revenue_allocated_cents`,
        `fuel_surcharge_allocated_cents`, and `accessorial_allocated_cents`
        exactly (else `ERR_SETTLEMENT_ALLOCATION_IMBALANCE`);
        `net_owner_operator_pay_cents` must not be negative (else
        `ERR_OWNER_OPERATOR_PAY_NEGATIVE`)".

        Design: Corner/endpoints/settlement_get_exposes_every_derived_allocation_field
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=True)
        settlement = bundle["settlement"]

        assert settlement["status"] == "APPROVED"
        assert settlement["settled_total_cents"] == (
            settlement["linehaul_revenue_allocated_cents"]
            + settlement["fuel_surcharge_allocated_cents"]
            + settlement["accessorial_allocated_cents"]
        )
        assert settlement["net_owner_operator_pay_cents"] >= 0
        assert settlement["variant_delta_cents"] == 0


class TestSettlementLifecycle:
    """Settling closes the load and the effects read back immediately."""

    def test_settle_effects_are_visible_in_the_same_request_chain(self, api):
        """PRD §3.6: "On success the settlement becomes `SETTLED`, the load
        becomes `SETTLED`, and the ledger work runs".
        PRD §3.8: "The maintenance withholding is not a percentage at all: it is
        exactly the reserve the trip already derived from the miles actually
        run".

        Design: Corner/consistency_model/settle_effects_are_visible_in_the_same_request_chain
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        bco, load = bundle["bco"], bundle["load"]

        settled = validate_success(
            api.settle_settlement(
                bundle["settlement"]["id"],
                {"expected_network_load_version": _load_version(api, load["id"])},
                SETTLEMENT_OPERATOR,
            ), 200
        )
        assert settled["status"] == "SETTLED"

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "SETTLED"

        bco_after = get_success_data(api.get_capacity_owner(bco["id"], SETTLEMENT_OPERATOR))
        assert bco_after["maintenance_balance_cents"] == 2400

        settlement_after = get_success_data(
            api.get_settlement(bundle["settlement"]["id"], SETTLEMENT_OPERATOR)
        )
        assert settlement_after["status"] == "SETTLED"
        assert settlement_after["net_owner_operator_pay_cents"] == 137571

    def test_settling_with_a_stale_load_version_is_refused(self, api):
        """PRD §2.8: "Settling a settlement requires `expected_network_load_version`,
        carrying the operator's last observed version of the parent `Load`. A
        mismatch is rejected with `ERR_STALE_VERSION`, because the load may
        already carry the settlement effect the operator was about to apply."

        Design: Corner/cross_cutting_complexity_layers/offer_create_with_stale_load_version_is_rejected
        """
        bundle = setup_approved_settlement(settlement_method="FINAL")
        load = bundle["load"]
        observed = _load_version(api, load["id"])

        refused = api.settle_settlement(
            bundle["settlement"]["id"],
            {"expected_network_load_version": observed - 1},
            SETTLEMENT_OPERATOR,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        unchanged = get_success_data(
            api.get_settlement(bundle["settlement"]["id"], SETTLEMENT_OPERATOR)
        )
        assert unchanged["status"] == "APPROVED", "the stale settle wrote nothing"


class TestCommissionReconciliation:
    """The agent's chronological book."""

    def test_summary_counts_only_approved_and_settled_rows(self, api):
        """PRD §3.9: "The counted rows are that agent's settlements whose status
        is `APPROVED` or `SETTLED`, each contributing its `agent_share_cents` as
        gross."
        PRD §3.9: "An agent's own book is reconciled chronologically through a
        settlement summary carrying an optional `order` selector and reporting a
        gross commission figure, a settlement count, and a period label."

        Design: Corner/calculations/agent_settlement_summary_counts_only_approved_and_settled_rows
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        settle_settlement(bundle["settlement"], bundle["load"])
        agent = bundle["agent"]

        summary = validate_success(
            api.get_agent_settlement_summary(agent["id"], SETTLEMENT_OPERATOR), 200
        )
        assert summary["gross_commission_cents"] == 23040
        assert summary["settlement_count"] == 1

        by_creation = validate_success(
            api.get_agent_settlement_summary(
                agent["id"], SETTLEMENT_OPERATOR, params={"order": "CREATION"}
            ), 200
        )
        assert by_creation["gross_commission_cents"] == 23040


class TestAgentLifecycle:
    """Enrollment and the termination cascade's effect on the customer book."""

    def test_agent_create_returns_declared_fields_and_starts_pending(self, api):
        """PRD §3.1: "The row lands in `PENDING_ENROLLMENT`. Its derived
        `settlement_hold` is recomputed to true, because the status is not yet
        `ACTIVE`; its `active_customer_count` and `awarded_load_count` both start
        at zero."

        Design: Corner/entities/agent_create_returns_declared_fields_and_starts_pending
        """
        set_logical_clock()
        created = validate_success(
            api.create_agent(
                {
                    "agent_code": "AG-COR-01",
                    "legal_name": "Corner Case Freight Agency",
                    "home_state": "TX",
                    "commission_rate_pct": 0.12,
                    "territory_codes": ["TX", "OK"],
                    "customer_ownership_days": 365,
                },
                TEST_USERS["network_admin_headers"],
            ), 201
        )
        assert created["status"] == "PENDING_ENROLLMENT"
        assert created["version"] == 1
        assert created["settlement_hold"] is True
        assert created["active_customer_count"] == 0
        assert created["awarded_load_count"] == 0
        assert created["territory_codes"] == ["TX", "OK"]
        assert created["home_state"] == "TX"

    def test_active_customer_count_reconciles_after_termination(self, api):
        """PRD §3.1: "At depth two, every customer account of this agent whose
        `exclusivity_status` is `OWNED_EXCLUSIVE` receives `released_reason`
        `AGENT_TERMINATED`, which recomputes its `exclusivity_status` to
        `RELEASED` and decrements the agent's `active_customer_count`."
        PRD §3.1: "Registering the account recomputes the owning agent's
        `active_customer_count`, and that count only includes accounts evaluated
        as `OWNED_EXCLUSIVE` against the current clock."

        Design: Corner/cross_cutting_complexity_layers/agent_active_customer_count_reconciles_after_termination
        """
        state = setup_terminated_agent_with_customer()
        agent, customer = state["agent"], state["customer"]

        # PRD §2.9: the derived `exclusivity_status` is re-evaluated on the next
        # read, so the pre-termination state is the fixture's read taken before
        # the termination call.
        assert state["customer_before"]["exclusivity_status"] == "OWNED_EXCLUSIVE"
        assert state["customer_before"]["released_reason"] is None
        assert state["agent_before"]["active_customer_count"] == 1

        assert agent["active_customer_count"] == 0
        accounts_after, _meta = _agent_accounts(api, agent["id"])
        released = [a for a in accounts_after if a["id"] == customer["id"]][0]
        assert released["exclusivity_status"] == "RELEASED"
        assert released["released_reason"] == "AGENT_TERMINATED"


def _load_version(api, load_id):
    return get_success_data(api.get_load(load_id, TEST_USERS["network_admin_headers"]))["version"]


def _agent_accounts(api, agent_id):
    return validate_paginated(
        api.list_agent_customer_accounts(agent_id, TEST_USERS["network_admin_headers"])
    )