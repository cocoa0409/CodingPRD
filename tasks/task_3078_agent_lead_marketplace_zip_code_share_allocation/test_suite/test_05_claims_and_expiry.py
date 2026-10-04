"""Credit claims, money conservation, and order expiry cascade (PRD §3.3, §3.9, §3.11)."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_claim,
    create_routed_lead,
    get_agent,
    get_market,
    get_share_order,
    make_agent_headers,
    set_clock,
    setup_assigned_lead,
    setup_market_with_active_order,
    validate_error,
    validate_success,
)


class TestClaimApprovalCascade:
    def test_invalid_claim_approval_credits_full_charge_to_order(self, api, marketplace_ops_headers):
        """PRD §3.9: "An approve resolution moves the claim to `APPROVED` and computes
        `credit_cents`: when the `claim_type` is `INVALID` the credit equals the lead's
        finalized charge; when the `claim_type` is `DUPLICATE` the credit is half of the
        finalized charge, floored to integer cents. The order's `credits_cents` increases
        by the credit, its `leads_credited` increments by one".

        Design: Difficulty/transitive_cascade/claim_approval_cascade_to_order_credit
        """
        set_clock()
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="33101", state_code="FL", consumer_key="c-claim@x.com"
        )
        claim = create_claim(lead["id"], agent["id"], claim_type="INVALID")
        resolved = validate_success(
            api.resolve_credit_claim(claim["id"], {"resolution": "APPROVED"}, marketplace_ops_headers)
        )
        assert resolved["claim_status"] == "APPROVED"
        assert resolved["credit_cents"] == 9000, "INVALID credits the full finalized charge"
        fresh_order = get_share_order(order["id"])
        assert fresh_order["credits_cents"] == 9000
        assert fresh_order["leads_credited"] == 1

    def test_duplicate_claim_approval_credits_half_charge(self, api, marketplace_ops_headers):
        """PRD §3.9: "when the `claim_type` is `DUPLICATE` the credit is half of the
        finalized charge, floored to integer cents."
        PRD §2.11: "credits computed as half of a charge round down to the nearest cent."

        Design: Difficulty/transitive_cascade/claim_approval_cascade_to_order_credit
        """
        set_clock()
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="33102", state_code="FL", consumer_key="c-dup@x.com"
        )
        claim = create_claim(lead["id"], agent["id"], claim_type="DUPLICATE")
        resolved = validate_success(
            api.resolve_credit_claim(claim["id"], {"resolution": "APPROVED"}, marketplace_ops_headers)
        )
        assert resolved["credit_cents"] == 4500, "half of 9000"
        assert get_share_order(order["id"])["credits_cents"] == 4500


class TestClaimReject:
    def test_rejected_claim_leaves_ledger_untouched(self, api, marketplace_ops_headers):
        """PRD §3.9: "A reject resolution moves the claim to `REJECTED`, sets
        `credit_cents` to zero, and leaves the ledgers untouched."

        Design: Corner/state_machines/claim_reject_leaves_ledger_untouched
        """
        set_clock()
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="97212", state_code="OR", consumer_key="c-t1@x.com"
        )
        claim = create_claim(lead["id"], agent["id"], claim_type="INVALID")
        resolved = validate_success(
            api.resolve_credit_claim(claim["id"], {"resolution": "REJECTED"}, marketplace_ops_headers)
        )
        assert resolved["claim_status"] == "REJECTED"
        assert resolved["credit_cents"] == 0
        fresh_order = get_share_order(order["id"])
        assert fresh_order["credits_cents"] == 0
        assert fresh_order["leads_credited"] == 0
        assert fresh_order["charged_cents"] == 9000

    def test_rejected_claim_does_not_increment_leads_credited(self, api, marketplace_ops_headers):
        """PRD §3.9: "A reject resolution moves the claim to `REJECTED`, sets
        `credit_cents` to zero, and leaves the ledgers untouched."

        Design: Corner/state_machines/claim_reject_leaves_ledger_untouched
        """
        set_clock()
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="97213", state_code="OR", consumer_key="c-t2@x.com"
        )
        claim = create_claim(lead["id"], agent["id"], claim_type="INVALID")
        validate_success(
            api.resolve_credit_claim(claim["id"], {"resolution": "REJECTED"}, marketplace_ops_headers)
        )
        assert get_share_order(order["id"])["leads_credited"] == 0


class TestChargeCreditConservation:
    def test_full_credit_nets_charge_to_zero_and_expiry_completes(self, api, marketplace_ops_headers):
        """PRD §3.9: "when the `claim_type` is `INVALID` the credit equals the lead's
        finalized charge".
        PRD §3.11: "Expire every `ShareOrder` in `ACTIVE` whose `ends_at` has been
        reached: orders that are settled (their `paid_cents` is at least `charged_cents`
        minus `credits_cents`) move to `COMPLETED` with `completed_at` set; orders with a
        balance due move to `CANCELLED`."

        Design: Difficulty/compensating_invariant/charge_credit_conservation
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="48201", state_code="MI", duration_days=1, consumer_key="c-claim@x.com"
        )
        claim = create_claim(lead["id"], agent["id"], claim_type="INVALID")
        validate_success(
            api.resolve_credit_claim(claim["id"], {"resolution": "APPROVED"}, marketplace_ops_headers)
        )
        set_clock("2026-09-02T00:00:01Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        final = get_share_order(order["id"])
        assert final["charged_cents"] == 9000
        assert final["credits_cents"] == 9000
        assert final["charged_cents"] - final["credits_cents"] == 0
        assert final["order_status"] == "COMPLETED", "net zero routes expiry to COMPLETED"

    def test_expiry_of_settled_order_completes_and_releases_share(self, api, marketplace_ops_headers):
        """PRD §3.11: "orders with a balance due move to `CANCELLED`. Either way the
        order's `share_bps` is released from the market".
        PRD §3.11: "orders that are settled (their `paid_cents` is at least
        `charged_cents` minus `credits_cents`) move to `COMPLETED` with `completed_at`
        set".

        Design: Difficulty/compensating_invariant/charge_credit_conservation
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="48202", state_code="MI", duration_days=1, consumer_key="c-due@x.com"
        )
        # Deposit 900000 paid covers the 9000 finalized charge: settled at expiry.
        set_clock("2026-09-02T00:00:01Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        final = get_share_order(order["id"])
        assert final["paid_cents"] >= final["charged_cents"] - final["credits_cents"]
        assert final["order_status"] == "COMPLETED"
        assert get_market(market["id"])["allocated_bps"] == 0


class TestExpiryCascade:
    def test_order_expiry_releases_share_and_reprices_market(self, api, marketplace_ops_headers):
        """PRD §3.11: "Expire every `ShareOrder` in `ACTIVE` whose `ends_at` has been
        reached: orders that are settled (their `paid_cents` is at least `charged_cents`
        minus `credits_cents`) move to `COMPLETED` with `completed_at` set ... Either way
        the order's `share_bps` is released from the market and the market's
        `current_unit_price_cents` and `version` are updated."
        PRD §3.3: "if the allocated share is less than 50 percent of capacity the demand
        `tier` is 1".

        Design: Difficulty/transitive_cascade/expiry_cascade_to_market_repricing
        """
        set_clock("2026-09-01T00:00:00Z")
        market, brokerage, agent_x, order_x = setup_market_with_active_order(
            zip_code="85001", state_code="AZ", share_bps=6000, duration_days=1
        )
        agent_y = create_agent(brokerage["id"], license_state="AZ")
        set_clock("2026-09-02T00:00:01Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        expired = get_share_order(order_x["id"])
        assert expired["order_status"] == "COMPLETED"
        market_after = get_market(market["id"])
        assert market_after["allocated_bps"] == 0
        # hop 3: a fresh order reprices at tier 1
        order_y = validate_success(
            api.create_share_order(
                {"market_id": market["id"], "buyer_agent_id": agent_y["id"],
                 "share_bps": 4000, "duration_days": 30},
                make_agent_headers(agent_y["id"]),
            ),
            201,
        )
        assert order_y["tier"] == 1
        # PRD §3.3: 4000 bps is in the 2500–4999 volume band → 5 percent discount;
        # tier 1 applies no tier multiplier: floor(10000 * 1.00 * 0.95) == 9500.
        assert order_y["unit_price_cents"] == 9500

    def test_completed_order_sets_completed_at(self, api, marketplace_ops_headers):
        """PRD §3.11: "orders that are settled (their `paid_cents` is at least
        `charged_cents` minus `credits_cents`) move to `COMPLETED` with `completed_at`
        set".

        Design: Difficulty/transitive_cascade/expiry_cascade_to_market_repricing
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, _, order = setup_market_with_active_order(
            zip_code="85002", state_code="AZ", share_bps=6000, duration_days=1
        )
        set_clock("2026-09-02T00:00:01Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        expired = get_share_order(order["id"])
        assert expired["order_status"] == "COMPLETED"
        assert expired["completed_at"] is not None


class TestDuplicateClaimRejected:
    def test_second_claim_on_credited_lead_rejected(self, api, marketplace_ops_headers):
        """PRD §3.9: "The claim is valid only when the referenced lead is in a finalized
        chargeable status, has not already been credited by another approved claim, and
        the claimant is the lead's `accepted_agent_id` — violations are rejected with
        `ERR_CREDIT_CLAIM_INVALID` (HTTP 422)."

        Design: Corner/validations/duplicate_claim_rejected_before_fiscal
        """
        set_clock()
        market, _, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="97216", state_code="OR", consumer_key="c-claim@x.com"
        )
        first = create_claim(lead["id"], agent["id"], claim_type="INVALID")
        validate_success(
            api.resolve_credit_claim(first["id"], {"resolution": "APPROVED"}, marketplace_ops_headers)
        )
        resp = api.create_credit_claim(
            {"lead_id": lead["id"], "claim_type": "DUPLICATE", "reason": "second"},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_CLAIM_INVALID, 422)
        assert get_share_order(order["id"])["credits_cents"] == 9000, (
            "rejected second claim must not move the ledger"
        )

    def test_claim_by_non_accepted_agent_rejected(self, api, marketplace_ops_headers):
        """PRD §3.9: "the claimant is the lead's `accepted_agent_id` — violations are
        rejected with `ERR_CREDIT_CLAIM_INVALID` (HTTP 422)."

        Design: Corner/validations/duplicate_claim_rejected_before_fiscal
        """
        set_clock()
        market, brokerage, agent, order, lead, _, _ = setup_assigned_lead(
            zip_code="97224", state_code="OR", consumer_key="c-stranger@x.com"
        )
        stranger = create_agent(brokerage["id"], license_state="OR")
        resp = api.create_credit_claim(
            {"lead_id": lead["id"], "claim_type": "INVALID", "reason": "not mine"},
            make_agent_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_CLAIM_INVALID, 422)
        assert get_share_order(order["id"])["credits_cents"] == 0
