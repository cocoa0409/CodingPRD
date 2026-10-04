"""Warranty claims: adjudication exits, the bounded info-request loop, filing
windows, damage-in-transit chargebacks, and the parts bubble-up (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_licensee_ledger_consistent,
    create_licensee_order,
    deliver_freight_order,
    deliver_order,
    file_claim,
    get_claim,
    get_licensee,
    get_order,
    list_parts_orders_for_claim,
    make_licensee_manager_headers,
    pick_order,
    run_cycle,
    set_clock,
    setup_delivered_freight_order,
    setup_open_cycle,
    ship_order,
    submit_order,
    transition_claim,
    transition_parts_order,
    validate_error,
    validate_success,
)


class TestClaimTerminalLockdown:
    def test_claim_denied_terminal_lockdown(self, api, warranty_admin_headers):
        """PRD §3.7: "Denial moves the claim to `DENIED` with a `decision_note`, and
        `decision` becomes `DENIED`. `RESOLVED` and `DENIED` are both terminal."
        PRD §2.8: "Transition validity (`ERR_INVALID_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/claim_denied_terminal_lockdown
        """
        ctx, order = setup_delivered_freight_order(quantity=1)
        claim = file_claim(order, claim_type="DEFECT", description="Frame cracked")
        denied = transition_claim(
            claim["id"], {"to_state": "DENIED", "decision_note": "Wear and tear, not a defect"}
        )
        assert denied["status"] == "DENIED"
        assert denied["decision"] == "DENIED"
        resp = api.transition_warranty_claim(
            claim["id"],
            {"to_state": "RESOLVED", "decision_note": "reconsidered"},
            warranty_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
        assert get_claim(claim["id"])["status"] == "DENIED"


class TestPartsBubbleUp:
    def test_parts_order_full_flow_bubbles_claim_to_resolved(self, api, platform_admin_headers):
        """PRD §3.7: "Approval with parts moves the claim to `PARTS_ORDERED`: the
        request must carry a non-empty `approved_parts` list of entries each naming a
        `sku` and a `quantity` greater than zero — an absent or empty list is
        `ERR_VALIDATION` — `decision` becomes `APPROVED`, and one parts order per entry
        is created in `QUEUED` status with `claim_id` set to this claim."
        PRD §3.7: "when a parts order reaches `DELIVERED` and every other parts order
        with the same `claim_id` is already `DELIVERED` — that is, the claim's last
        outstanding parts order has landed — the claim transitions `PARTS_ORDERED →
        RESOLVED` and `resolved_at` is stamped."
        PRD §3.7: "for approved claims of the other two types it stays null."

        Design: Corner/state_machines/parts_order_full_flow_bubbles_claim_to_resolved
        """
        ctx, order = setup_delivered_freight_order(quantity=1)
        claim = file_claim(
            order, claim_type="MISSING_PARTS", description="Two bed legs missing"
        )
        approved = transition_claim(
            claim["id"],
            {
                "to_state": "PARTS_ORDERED",
                "approved_parts": [{"sku": "LEG-42", "quantity": 2}],
                "decision_note": "shipping replacement legs",
            },
        )
        assert approved["status"] == "PARTS_ORDERED"
        assert approved["decision"] == "APPROVED"

        parts = list_parts_orders_for_claim(claim["id"])
        assert len(parts) == 1
        part = parts[0]
        assert part["sku"] == "LEG-42"
        assert part["quantity"] == 2
        assert part["status"] == "QUEUED"

        transition_parts_order(part["id"], "SHIPPED")
        transition_parts_order(part["id"], "DELIVERED")

        resolved = get_claim(claim["id"])
        assert resolved["status"] == "RESOLVED", (
            "last DELIVERED parts order must bubble the claim to RESOLVED"
        )
        assert resolved["resolved_at"] is not None
        assert resolved["chargeback_cents"] is None, (
            "MISSING_PARTS carries no chargeback"
        )


class TestDamageInTransitChargeback:
    def test_dit_approval_chargeback_adjusts_net_royalty(self, api, platform_admin_headers):
        """PRD §3.7: "When an approved claim — whether approved with or without parts —
        has `claim_type` `DAMAGE_IN_TRANSIT`, the licensee is charged back the order's
        `final_total_cents` times the `CHARGEBACK_RATE` of 0.15, rounded half-up to
        cents. The claim's `chargeback_cents` stores exactly this amount; for approved
        claims of the other two types it stays null."
        PRD §3.7: "and `net_royalty_cents` is `royalty_accrued_cents` minus
        `chargeback_cents`."

        Design: Corner/state_machines/dit_approval_chargeback_adjusts_net_royalty
        """
        ctx, order = setup_delivered_freight_order(
            line_over={
                "name": "Birch Bedroom Set",
                "category": "CASEGOODS",
                "price_point_cents": 59900,
                "style_code": "BR-BED-01",
            },
            quantity=2,
        )
        # final_total 83860 -> royalty round_half_up(83860 * 0.04) == 3354.
        claim = file_claim(
            order,
            claim_type="DAMAGE_IN_TRANSIT",
            description="Headboard crushed in transit",
        )
        resolved = transition_claim(
            claim["id"],
            {"to_state": "RESOLVED", "decision_note": "approved, carrier fault"},
        )
        assert resolved["decision"] == "APPROVED"
        # round_half_up(83860 * 0.15) == 12579.
        assert resolved["chargeback_cents"] == 12579, (
            f"expected chargeback 12579, got {resolved['chargeback_cents']}"
        )
        licensee = get_licensee(ctx["licensee"]["id"])
        assert licensee["royalty_accrued_cents"] == 3354
        assert licensee["chargeback_cents"] == 12579
        assert licensee["net_royalty_cents"] == -9225  # 3354 - 12579
        assert_licensee_ledger_consistent(licensee)


class TestWarrantyFilingWindows:
    def _setup_order_delivered_at(self, delivered_at):
        """Freight order delivered with delivered_at pinned to the given logical
        time (the clock is moved before DELIVER)."""
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=1
        )
        submit_order(order)
        run_cycle(ctx["cycle"]["id"])
        pick_order(order["id"])
        ship_order(order["id"])
        set_clock(delivered_at)
        deliver_order(order["id"])
        return ctx, get_order(order["id"])

    def test_warranty_defect_window_day365_passes_day366_fails(self, api, platform_admin_headers):
        """PRD §3.7: "Filing windows are measured from the order's `delivered_at`:
        `DEFECT` and `MISSING_PARTS` claims may be filed within 365 days of delivery,
        and `DAMAGE_IN_TRANSIT` claims within 30 days. Filing exactly on the boundary
        day still passes; anything later is rejected with
        `ERR_WARRANTY_WINDOW_EXPIRED`."

        Design: Corner/errors/warranty_defect_window_day365_passes_day366_fails
        """
        # delivered_at == 2026-09-05T10:00:00Z; +365 days == 2027-09-05T10:00:00Z.
        _ctx, order = self._setup_order_delivered_at("2026-09-05T10:00:00Z")
        owner = make_licensee_manager_headers(order["licensee_id"])
        set_clock("2027-09-05T10:00:00Z")  # exactly the boundary day
        ok = api.create_warranty_claim(
            {
                "supply_order_id": order["id"],
                "claim_type": "DEFECT",
                "description": "Filed exactly on day 365",
            },
            owner,
        )
        validate_success(ok, 201)
        set_clock("2027-09-06T10:00:00Z")  # a full day past the boundary
        late = api.create_warranty_claim(
            {
                "supply_order_id": order["id"],
                "claim_type": "DEFECT",
                "description": "Filed on day 366",
            },
            owner,
        )
        validate_error(late, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED.value)

    def test_damage_in_transit_window_day30_passes_day31_fails(self, api, platform_admin_headers):
        """PRD §3.7: "and `DAMAGE_IN_TRANSIT` claims within 30 days. Filing exactly on
        the boundary day still passes; anything later is rejected with
        `ERR_WARRANTY_WINDOW_EXPIRED`."

        Design: Corner/errors/damage_in_transit_window_day30_passes_day31_fails
        """
        # delivered_at == 2026-09-05T10:00:00Z; +30 days == 2026-10-05T10:00:00Z.
        _ctx, order = self._setup_order_delivered_at("2026-09-05T10:00:00Z")
        owner = make_licensee_manager_headers(order["licensee_id"])
        set_clock("2026-10-05T10:00:00Z")  # exactly the boundary day
        ok = api.create_warranty_claim(
            {
                "supply_order_id": order["id"],
                "claim_type": "DAMAGE_IN_TRANSIT",
                "description": "Filed exactly on day 30",
            },
            owner,
        )
        validate_success(ok, 201)
        set_clock("2026-10-06T10:00:00Z")  # a full day past the boundary
        late = api.create_warranty_claim(
            {
                "supply_order_id": order["id"],
                "claim_type": "DAMAGE_IN_TRANSIT",
                "description": "Filed on day 31",
            },
            owner,
        )
        validate_error(late, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED.value)


class TestInfoRequestBudget:
    def test_info_request_third_cycle_rejected(self, api, warranty_admin_headers):
        """PRD §3.7: "A `WarrantyAdmin` may push a claim from `UNDER_REVIEW` to
        `INFO_REQUESTED` — optionally recording a `decision_note` — at most
        `INFO_REQUEST_MAX` (2) times: each request increments `info_request_count` by
        one, and a third attempt is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED`. The
        owning `LicenseeManager` answers an information request with an `info_note`,
        moving the claim `INFO_REQUESTED → UNDER_REVIEW`"

        Design: Corner/errors/info_request_third_cycle_rejected
        """
        ctx, order = setup_delivered_freight_order(quantity=1)
        claim = file_claim(order, claim_type="DEFECT", description="Cushion foam collapsed")
        owner = make_licensee_manager_headers(ctx["licensee"]["id"])

        first = transition_claim(
            claim["id"], {"to_state": "INFO_REQUESTED", "decision_note": "Need photos"}
        )
        assert first["info_request_count"] == 1
        transition_claim(
            claim["id"],
            {"to_state": "UNDER_REVIEW", "info_note": "Photos attached"},
            as_admin=False,
            licensee_id=ctx["licensee"]["id"],
        )
        second = transition_claim(
            claim["id"], {"to_state": "INFO_REQUESTED", "decision_note": "Need receipt"}
        )
        assert second["info_request_count"] == 2
        transition_claim(
            claim["id"],
            {"to_state": "UNDER_REVIEW", "info_note": "Receipt attached"},
            as_admin=False,
            licensee_id=ctx["licensee"]["id"],
        )
        resp = api.transition_warranty_claim(
            claim["id"],
            {"to_state": "INFO_REQUESTED", "decision_note": "Need more"},
            warranty_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED.value)
        final = get_claim(claim["id"])
        assert final["status"] == "UNDER_REVIEW"
        assert final["info_request_count"] == 2
