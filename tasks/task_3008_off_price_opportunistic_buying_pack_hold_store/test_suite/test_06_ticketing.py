"""Ticketing: 9-ending rounding, compare-at substantiation gate, immutability,
and the in-use void guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    accept_lot,
    evaluate_lot,
    make_accepted_lot,
    make_lot,
    make_lot_line,
    make_ticket,
    open_season,
    setup_base,
    setup_floor_sku,
    validate_error,
    validate_success,
)

PRICING = TEST_USERS["pricing_analyst_headers"]
STORE_OPS = TEST_USERS["store_ops_lead_headers"]


class TestTicketIssuance:
    def test_ticket_is_immutable_ledger_entry_with_9_ending_price(self, api):
        """PRD §2.4: "Three resources are deliberately lighter: **Ticket**,
        **ReceiptLine**, and **MarkdownEvent** carry only `id` and `created_at`
        — both `updated_at` and `version` are absent from these entities".

        Design: Corner/entities/ticket_is_immutable_no_version_field_and_no_update_endpoint
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(
            base["vendor"]["id"], base["season"]["id"],
            line_overrides={"target_retail_cents": 10_000, "compare_at_claim_cents": 25_000},
        )
        ticket = validate_success(
            api.create_ticket({"lot_line_id": accepted["line"]["id"], "zone_code": "MT"}, PRICING), 201)
        assert ticket["id"] is not None
        assert ticket["created_at"] is not None
        assert "version" not in ticket
        assert "updated_at" not in ticket
        assert ticket["status"] == "ACTIVE"

    def test_ticket_retail_adjusted_down_to_9_ending(self, api):
        """PRD §2.7: "whenever a retail price is computed — at ticket issuance
        and at every markdown or clearance step — the value is first rounded
        half-up to integer cents and then adjusted downward to the nearest price
        ending in 9 cents (so 2452 becomes 2449, and 2400 becomes 2399)."

        Design: Corner/entities/ticket_is_immutable_no_version_field_and_no_update_endpoint
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(
            base["vendor"]["id"], base["season"]["id"],
            line_overrides={"target_retail_cents": 10_000, "compare_at_claim_cents": 25_000},
        )
        ticket = make_ticket(accepted["line"]["id"], zone_code="MT")
        assert ticket["ticket_retail_cents"] == 9_999


class TestCompareAtSubstantiation:
    def _issued_tickets_at_gate(self, api):
        """Accepted lot with two lines: line A claim 19998 (exactly the gate),
        line B claim 19997 (one cent below). Both lines are added while the lot
        is still OFFERED (PRD §3.2), before evaluation and acceptance."""
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(base["vendor"]["id"], base["season"]["id"])
        line_a = make_lot_line(lot["id"], style_code="CA-A", quantity=50,
                               unit_cost_cents=11_500, compare_at_claim_cents=19_998,
                               target_retail_cents=10_000)
        line_b = make_lot_line(lot["id"], style_code="CA-B", quantity=50,
                               unit_cost_cents=11_500, compare_at_claim_cents=19_997,
                               target_retail_cents=10_000)
        evaluate_lot(lot["id"])
        accept_lot(lot["id"], base["season"]["id"])
        return base, line_a, line_b

    def test_claim_at_exactly_the_gate_substantiates(self, api):
        """PRD §3.3: "The gate is: the claimed compare-at must be at least the
        ticket retail multiplied by the zone's `compare_at_multiplier`, with the
        product rounded up to integer cents so the boundary is exact." PRD §3.3:
        "A claim that passes is recorded as `compare_at_cents` with
        `compare_at_omitted` false".

        Design: Corner/calculations/compare_at_substantiation_gate_and_omission_boundary
        """
        base, line_a, _line_b = self._issued_tickets_at_gate(api)
        ticket_a = make_ticket(line_a["id"], zone_code="MT")
        assert ticket_a["compare_at_cents"] == 19_998
        assert ticket_a["compare_at_omitted"] is False
        assert ticket_a["ticket_retail_cents"] == 9_999

    def test_claim_one_cent_below_gate_omitted_without_rejection(self, api):
        """PRD §3.3: "a claim that fails is **not rejected** — the ticket is
        printed without a compare-at price, with `compare_at_cents` null and
        `compare_at_omitted` true."

        Design: Corner/calculations/compare_at_substantiation_gate_and_omission_boundary
        """
        base, _line_a, line_b = self._issued_tickets_at_gate(api)
        ticket_b = validate_success(
            api.create_ticket({"lot_line_id": line_b["id"], "zone_code": "MT"}, PRICING), 201)
        assert ticket_b["compare_at_cents"] is None
        assert ticket_b["compare_at_omitted"] is True
        assert ticket_b["ticket_retail_cents"] == 9_999


class TestTicketVoidGuard:
    def test_void_blocked_while_live_stock_references_ticket(self, api):
        """PRD §3.3: "the `PricingAnalyst` may void it (`ACTIVE → VOIDED`) only
        while no store SKU in `ON_FLOOR`, `MARKED_DOWN`, or `CLEARANCE`
        references it — live stock protects the ticket with `ERR_TICKET_IN_USE`."

        Design: Corner/validations/ticket_void_blocked_while_live_stock_references_it
        """
        env = setup_floor_sku(units_on_hand=3)
        res = api.void_ticket(env["ticket"]["id"], PRICING)
        validate_error(res, ApiErrorId.ERR_TICKET_IN_USE)

    def test_void_succeeds_after_stock_sold_out(self, api):
        """PRD §3.3: "live stock protects the ticket with `ERR_TICKET_IN_USE`" —
        once the stock is `SOLD_OUT` the ticket is no longer protected.

        Design: Corner/validations/ticket_void_blocked_while_live_stock_references_it
        """
        env = setup_floor_sku(units_on_hand=3)
        validate_success(api.deplete_store_sku(env["sku"]["id"], {"units_sold": 3}, STORE_OPS))
        voided = validate_success(api.void_ticket(env["ticket"]["id"], PRICING))
        assert voided["status"] == "VOIDED"


class TestPlacementRequiresTicket:
    def test_manual_placement_with_unknown_ticket_rejected(self, api):
        """PRD §3.6: "The `ticket_id` is required at placement precisely so that
        every sellable unit traces to a ticketed price."

        Design: Corner/validations/store_sku_placement_requires_active_ticket
        """
        base = setup_base()
        open_season(base["season"])
        accepted = make_accepted_lot(base["vendor"]["id"], base["season"]["id"])
        store_res = api.create_store(
            {"store_code": "ST-NT", "cluster_code": "SUBURBAN_FAMILY",
             "zone_code": "MT", "storage_capacity_units": 500},
            TEST_USERS["allocation_manager_headers"],
        )
        store = validate_success(store_res, 201)
        res = api.create_store_sku(
            {"store_id": store["id"], "lot_line_id": accepted["line"]["id"],
             "ticket_id": "00000000-0000-4000-8000-000000000000",
             "season_id": base["season"]["id"], "units_on_hand": 5},
            STORE_OPS,
        )
        assert res.status_code in (404, 422)
        body = res.json()
        assert body["data"]["error_id"] in ("ERR_NOT_FOUND", "ERR_TICKET_NOT_ISSUED")
        from test_helpers import validate_paginated
        skus, _meta = validate_paginated(api.list_store_store_skus(store["id"], STORE_OPS))
        assert len(skus) == 0

    def test_manual_placement_with_active_ticket_succeeds(self, api):
        """PRD §3.6: "Manual placement carries `allocation_plan_id` null, stamps
        `floor_date` and `weeks_on_floor` the same way, initializes
        `current_price_cents` from the referenced ticket".

        Design: Corner/validations/store_sku_placement_requires_active_ticket
        """
        env = setup_floor_sku(units_on_hand=5, target_retail_cents=10_000)
        sku = env["sku"]
        assert sku["allocation_plan_id"] is None
        assert sku["current_price_cents"] == env["ticket"]["ticket_retail_cents"]
        assert sku["status"] == "ON_FLOOR"
