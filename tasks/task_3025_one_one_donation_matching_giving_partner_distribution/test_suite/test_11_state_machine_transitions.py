"""Declared transitions, refused transitions and terminal locks (PRD §3.4, §3.6–§3.9)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    commit_allocation,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_order,
    create_season,
    declare_capacity,
    get_claim,
    make_auditor_headers,
    pay_order,
    register_claim,
    set_clock,
    ship_allocation,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
SERVICE = TEST_USERS["customer_service_headers"]
MARKETING = TEST_USERS["marketing_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestProductActivationGate:
    """Corner/state_machines — the gate reads the computed score, not the line payload."""

    def test_a_dual_channel_top_scores_fifty_and_cannot_activate(self, api):
        """PRD §3.4: "Activation is gated at a score of 60: a `DRAFT` product whose `design_weight_score` is at least 60 may be activated and every draft variant under it moves to `ACTIVE` with its obligation units computed, while a product below the threshold is refused with `ERR_DESIGN_WEIGHT_BELOW_MINIMUM` (HTTP 409). The gate is exactly at 60 — an apparel top that is reusable and donation-only scores 60 and is activatable, while the same top as a dual-channel product scores 50 and is refused."

        Design: Corner/state_machines/product_activate_with_a_ninety_nine_weight_line_still_needs_the_gate
        """
        product = validate_success(
            api_client.create_donation_product(
                {
                    "product_name": "Gate Probe Tee",
                    "product_kind": "APPAREL_TOP",
                    "design_channel": "DUAL_CHANNEL",
                    "obligation_model": "AT_SALE",
                    "approved_donation_ratio_units": 1,
                    "retail_price_cents": 2100,
                    "unit_cost_cents": 1400,
                    "is_reusable": True,
                },
                DESIGN,
            ),
            201,
        )
        assert product["design_weight_score"] == 50, "30 + 20 + 0"

        api_client.create_product_line(
            product["id"],
            {
                "gtin": "00000000000901",
                "unit_size_label": "M",
                "is_essential_good": False,
                "donation_eligible": True,
                "design_weight_score": 99,
            },
            DESIGN,
        )
        res = api_client.activate_donation_product(product["id"], {}, DESIGN)
        validate_error(res, "ERR_DESIGN_WEIGHT_BELOW_MINIMUM", expected_status=409)

        assert validate_success(
            api_client.get_donation_product(product["id"], AUDITOR), 200
        )["status"] == "DRAFT"


class TestSeasonTransitionGuards:
    """Corner/state_machines — closing is declared only from a frozen season."""

    def test_closing_a_planned_season_is_refused(self, api):
        """PRD §3.7: "Closing a season requires that every one of its liabilities is already `CARRIED` or `CLOSED`; closing moves them to `CLOSED` and the season to `CLOSED`."
        PRD §2.4: "Fifth, the target resource must be in a state from which the requested transition is declared (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/season_close_from_open_returns_invalid_state_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()

        res = api_client.close_season(season["id"], {}, AUDITOR)
        validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        assert validate_success(
            api_client.get_impact_season(season["id"], AUDITOR), 200
        )["status"] == "PLANNED"


class TestClaimTransitionGuards:
    """Corner/state_machines — a draft claim cannot be revoked or re-substantiated."""

    def test_revoking_a_draft_claim_is_refused(self, api):
        """PRD §3.8: "A `MarketingManager` may revoke a claim in `SUBSTANTIATED` or `OVERSTATED` — supplying a `reason` — provided the claim has not already been finalized inside an impact audit."
        PRD §2.4: "Fifth, the target resource must be in a state from which the requested transition is declared (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/claim_revoke_from_draft_returns_invalid_state_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        product = create_active_product()
        partner = create_approved_partner()
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        assert claim["status"] == "DRAFT"

        res = api_client.revoke_claim(
            claim["id"], {"reason": "Legal review requested a takedown"}, MARKETING
        )
        validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

    def test_a_revoked_claim_locks_out_further_substantiation(self, api):
        """PRD §3.8: "A revoked claim can never return to `SUBSTANTIATED`, and any further substantiation or derive-build call against it is refused with `ERR_CLAIM_ALREADY_REVOKED` (HTTP 409)."
        PRD §3.8: "A `MarketingManager` may revoke a claim in `SUBSTANTIATED` or `OVERSTATED` — supplying a `reason` — provided the claim has not already been finalized inside an impact audit."

        Design: Corner/state_machines/revoked_claim_is_terminal_and_refuses_further_substantiation
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        # PRD §3.8 counts the partner's allocations "in the four counted
        # statuses — `APPROVED`, `SHIPPED`, `PARTIALLY_RECEIVED` or `RECEIVED`"
        # toward substantiation, so a commitment backs the stated 1000 units.
        claim_allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=1000, priority_tier="CRITICAL",
        )
        assert claim_allocation["status"] == "APPROVED"
        validate_success(api_client.substantiate_claim(claim["id"], {}, MARKETING), 200)
        assert get_claim(claim["id"])["status"] == "SUBSTANTIATED"

        validate_success(
            api_client.revoke_claim(
                claim["id"],
                {"reason": "Public statement withdrawn after a partner suspension"},
                MARKETING,
            ),
            200,
        )
        assert get_claim(claim["id"])["status"] == "REVOKED"

        again = api_client.revoke_claim(claim["id"], {"reason": "repeat"}, MARKETING)
        validate_error(again, "ERR_CLAIM_ALREADY_REVOKED", expected_status=409)

        substantiate = api_client.substantiate_claim(claim["id"], {}, MARKETING)
        validate_error(substantiate, "ERR_CLAIM_ALREADY_REVOKED", expected_status=409)


class TestAllocationCancellationGuards:
    """Corner/state_machines — a shipped allocation can no longer be cancelled."""

    def test_a_cancel_after_a_shipment_is_refused_by_the_state_rung(self, api):
        """PRD §3.2: "Cancelling an approved allocation requires the `expected_allocation_version` and that no distribution against it has shipped any units; a cancel after a shipment is refused with `ERR_ALLOCATION_DISTRIBUTION_EXISTS` (HTTP 409)."
        PRD §2.4: "Fifth, the target resource must be in a state from which the requested transition is declared (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/allocation_cancel_after_a_shipment_returns_invalid_state_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        add_product_line(product["id"], "00000000000601", "M", True)
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=10, priority_tier="HIGH",
        )
        distribution = ship_allocation(allocation["id"], 10, "TRK-SM-1", "UPS")

        current = validate_success(api_client.get_allocation(allocation["id"], PLANNER), 200)
        assert current["status"] == "SHIPPED"

        res = api_client.cancel_allocation(
            allocation["id"], {"expected_allocation_version": current["version"]}, PLANNER
        )
        validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        assert validate_success(
            api_client.get_distribution(distribution["id"], FULFILL), 200
        )["status"] == "SHIPPED"


class TestAuditTransitionGuards:
    """Corner/state_machines — fieldwork restarts only from a scheduled audit."""

    def test_restarting_a_finalized_audit_is_refused(self, api):
        """PRD §3.9: "Starting fieldwork or rewriting an exception count against an audit that is already `FINALIZED` is refused with `ERR_AUDIT_ALREADY_FINALIZED` (HTTP 409)."

        Design: Corner/state_machines/audit_start_from_a_finalized_audit_returns_invalid_state_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        add_product_line(product["id"], "00000000000602", "M", True)
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=100)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-AS-1", "UPS")
        confirm_receipt(distribution["id"], 100, "RCV-AS-1")

        set_clock("2026-12-02T00:00:00Z")
        audit = validate_success(
            api_client.create_impact_audit(
                {
                    "impact_season_id": season["id"],
                    "claim_id": claim["id"],
                    "audit_kind": "ANNUAL_IMPACT",
                },
                AUDITOR,
            ),
            201,
        )
        started = validate_success(
            api_client.start_audit(audit["id"], {}, make_auditor_headers("aud-alpha")), 200
        )
        finalized = validate_success(
            api_client.finalize_audit(
                audit["id"],
                {
                    "transaction_test_sample_size": 20,
                    "transaction_test_exceptions": 0,
                    "claimed_donation_units": 100,
                    "expected_audit_version": started["version"],
                },
                make_auditor_headers("aud-beta"),
            ),
            200,
        )
        assert finalized["status"] == "FINALIZED"

        res = api_client.start_audit(audit["id"], {}, AUDITOR)
        validate_error(res, "ERR_AUDIT_ALREADY_FINALIZED", expected_status=409)


class TestDistributionCompletionGuards:
    """Corner/state_machines — completion needs a full receipt."""

    def test_a_partial_receipt_cannot_be_completed(self, api):
        """PRD §3.3: "A fully received distribution is closed by the operator, which requires that `received_units` equals `shipped_units` and that a receipt confirmation timestamp is set; closing it moves the distribution to `COMPLETED`, recomputes the partner's `avg_distribution_completion_days`, and lands the allocation at `RECEIVED`."
        PRD §3.3: "A `FulfillmentOperator` raises a discrepancy against a distribution whose `received_units` is below `shipped_units`, supplying an `exception_reason`; the distribution moves to `DISCREPANCY_CLAIMED` and `discrepancy_units` is computed as `shipped_units` minus `received_units`."

        Design: Corner/state_machines/distribution_complete_requires_a_full_receipt
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-DC-1", "UPS")
        confirm_receipt(distribution["id"], 60, "RCV-DC-1")

        current = validate_success(
            api_client.get_distribution(distribution["id"], FULFILL), 200
        )
        assert current["status"] == "PARTIALLY_RECEIVED"
        assert current["received_units"] == 60

        res = api_client.complete_distribution(distribution["id"], {}, FULFILL)
        validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        raised = validate_success(
            api_client.raise_discrepancy(
                distribution["id"],
                {"exception_reason": "Six units short of the manifest"},
                FULFILL,
            ),
            200,
        )
        assert raised["status"] == "DISCREPANCY_CLAIMED"


class TestLineReturnWindowLockdown:
    """Corner/state_machines — exemption closes the window but keeps the obligation."""

    def test_exempting_a_line_retains_its_obligation(self, api):
        """PRD §3.6: "Finally, an `OPEN` line can be exempted from the return window entirely by supplying a `request_reason` of `GOODWILL` or `DEFECT`; the exemption moves the line to `EXEMPTED`, closes its return window, and retains its `obligated_units`."

        Design: Corner/state_machines/exempted_line_locks_the_return_window_while_keeping_the_obligation
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000603", "M", True)
        order = create_order(order_number="SO-CORNER-1", channel="RETAIL_ECOM")
        soline = add_line(order["id"], line["id"], quantity=2, unit_price_cents=1600)
        pay_order(order["id"])

        validate_success(
            api_client.exempt_line(
                order["id"], soline["id"], {"request_reason": "GOODWILL"}, SERVICE
            ),
            200,
        )

        exempted = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )
        assert exempted["status"] == "EXEMPTED"
        assert exempted["obligated_units"] == 2

        refreshed_order = validate_success(
            api_client.get_sales_order(order["id"], SERVICE), 200
        )
        assert refreshed_order["refunded_cents"] == 0

        liability = validate_success(
            api_client.list_liabilities(
                AUDITOR,
                {"donation_product_id": product["id"], "impact_season_id": season["id"]},
            ),
            200,
        )[0]
        assert liability["final_liability_units"] == 2


class TestSettlementIsNotRepeatable:
    """Corner/state_machines — repeating a settle is a state error, not a second accrual."""

    def test_the_second_settle_does_not_double_count(self, api):
        """PRD §2.4: "Fifth, the target resource must be in a state from which the requested transition is declared (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.5: "Settling a line's obligation out of the warehouse is the operator's act."

        Design: Corner/state_machines/second_line_settle_on_the_same_line_returns_invalid_state_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000604", "M", True)
        order = create_order(order_number="SO-CORNER-2", channel="RETAIL_ECOM")
        soline = add_line(order["id"], line["id"], quantity=2, unit_price_cents=1600)
        pay_order(order["id"])
        validate_success(
            api_client.settle_line(order["id"], soline["id"], {"shipped_units": 2}, FULFILL), 200
        )

        res = api_client.settle_line(order["id"], soline["id"], {"shipped_units": 2}, FULFILL)
        assert res.status_code == 409, "the line has left OPEN"

        liability = validate_success(
            api_client.list_liabilities(
                AUDITOR,
                {"donation_product_id": product["id"], "impact_season_id": season["id"]},
            ),
            200,
        )[0]
        assert liability["final_liability_units"] == 2, "no second accrual"
        # PRD §3.5: settling "recomputes the season's `final_liability_units`,
        # and recomputes `total_shipped_units`"; the season's shipped figure is
        # defined by §3.7 as the sum over the season's distributions.
        assert validate_success(
            api_client.get_impact_season(season["id"], AUDITOR), 200
        )["total_shipped_units"] == 0