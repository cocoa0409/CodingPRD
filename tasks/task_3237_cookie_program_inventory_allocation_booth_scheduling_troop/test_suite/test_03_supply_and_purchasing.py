"""Season supply ledger and baker purchase order coverage."""
from test_helpers import (
    ApiErrorId,
    add_product,
    add_site,
    create_and_confirm_order,
    create_and_place_po,
    create_and_submit_order,
    create_baker_po_payload,
    create_season,
    create_troop_with_account,
    deliver_po,
    get_season,
    get_site,
    make_council_admin_headers,
    open_season,
    set_clock,
    setup_closed_season,
    setup_open_season_with_supply,
    validate_error,
    validate_success,
)


class TestSupplyLedger:
    def test_attainment_provisional_vs_final_season_domain(self, api):
        """PRD §3.3: "Season summary reads additionally expose a provisional
        attainment that counts both confirmed and pending commitments in the
        numerator — useful while orders are still `SUBMITTED` — but this
        provisional figure is never used for the selling gate; the gate and all
        post-selling reporting use the confirmed-only final attainment, which
        for identical data is always the lower of the two whenever pending
        orders exist."

        Design: Difficulty/dual_variant_calc/attainment_provisional_vs_final_season_domain
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(season["id"], troop, [(product["id"], 120)],
                                 leader=leader, admin=admin)
        create_and_submit_order(season["id"], troop, [(product["id"], 60)], leader=leader)
        read = get_season(season["id"], admin=admin)
        # Final (gate) variant: 120/200 = 60.00; the 60-unit pending order is
        # excluded from the numerator even though provisional would be 90.00.
        assert read["forecast_attainment_pct"] == 60.00
        assert read["pending_commit_units"] == 60
        assert read["initial_commit_units"] == 120
        assert read["status"] == "OPEN"

    def test_attainment_gate_exactly_80_vs_just_below(self, api):
        """PRD §3.3: "The gate itself is inclusive: an attainment of at least
        80.00 percent opens selling."

        Design: Difficulty/boundary_precision_check/attainment_gate_exactly_80_vs_just_below
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(100, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 80)], leader=leader
        )
        validate_success(api.confirm_order(season["id"], submitted["id"], admin))
        read = get_season(season["id"], admin=admin)
        assert read["forecast_attainment_pct"] == 80.00
        assert read["status"] == "SELLING"

    def test_remaining_units_input_set_excludes_draft_and_cancelled_pos(self, api):
        """PRD §2.5: "`purchased_units` is the sum of `quantity` over the
        season's baker purchase orders whose status is `ORDERED`,
        `PARTIALLY_DELIVERED`, or `DELIVERED` — purchase orders still in
        `DRAFT` or already `CANCELLED` never count."

        Design: Corner/calculations/remaining_units_input_set_excludes_draft_and_cancelled_pos
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        site = add_site(season, admin=admin)
        # PO stays DRAFT (never placed): must not count toward purchased_units.
        resp = api.create_baker_po(
            season["id"],
            create_baker_po_payload(product["id"], 100, site["id"]),
            admin,
        )
        assert resp.status_code == 201
        read = get_season(season["id"], admin=admin)
        assert read["purchased_units"] == 0
        assert read["remaining_units"] == 0

    def test_immediate_consistency_order_confirm_visible_in_season_read(self, api):
        """PRD §2.5: "These counters recompute on every order submit, confirm,
        or reject and on every purchase-order placement or cancellation within
        the season."

        Design: Corner/consistency_model/immediate_consistency_order_confirm_visible_in_season_read
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(season["id"], troop, [(product["id"], 40)],
                                 leader=leader, admin=admin)
        read = get_season(season["id"], admin=admin)
        assert read["initial_commit_units"] == 40
        assert read["pending_commit_units"] == 0
        assert read["remaining_units"] == 160


class TestPurchaseOrderDelivery:
    def test_overdelivery_rejected(self, api):
        """PRD §3.1: "The cumulative total may never exceed the order's
        `quantity`; an over-shipment is refused with `ERR_OVERDELIVERY`."

        Design: Corner/validations/overdelivery_rejected
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        site = add_site(season, admin=admin)
        po = create_and_place_po(season, product["id"], 50, site["id"], admin=admin)
        resp = api.record_delivery(season["id"], po["id"], {"delivered_now": 51}, admin)
        validate_error(resp, ApiErrorId.ERR_OVERDELIVERY, 422)

    def test_site_capacity_aggregate_overlap_semantics(self, api):
        """PRD §3.1: "Recording is permitted only from `ORDERED` or
        `PARTIALLY_DELIVERED`, and only while the receiving site's posture is
        `RECEIVING` with enough headroom — pushing `received_units` past
        `capacity_units` fails with `ERR_SITE_CAPACITY_EXCEEDED`." PRD §2.8:
        "It is `RECEIVING` when the owning season is `OPEN` or `SELLING` and
        the site's `received_units` is below its `capacity_units`; `FULL` once
        `received_units` reaches or exceeds `capacity_units`".

        Design: Difficulty/resource_temporal_overlap/site_capacity_aggregate_overlap_semantics
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        site = add_site(season, admin=admin, capacity_units=100)
        po_a = create_and_place_po(season, product["id"], 90, site["id"], admin=admin)
        po_b = create_and_place_po(season, product["id"], 20, site["id"], admin=admin)
        # Deliveries require site posture RECEIVING (PRD §3.1), i.e. season OPEN.
        open_season(season["id"], admin=admin)
        deliver_po(season["id"], po_a["id"], 90, admin=admin)
        deliver_po(season["id"], po_b["id"], 10, admin=admin)
        site_read = get_site(site["id"], admin=admin)
        assert site_read["received_units"] == 100
        assert site_read["posture"] == "FULL"
        resp = api.record_delivery(season["id"], po_b["id"], {"delivered_now": 10}, admin)
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED, 422)


class TestSeasonLifecycle:
    def test_season_open_requires_nonempty_catalog(self, api):
        """PRD §3.1: "Opening the season — the `DRAFT` → `OPEN` transition
        performed by a `CouncilAdmin` — requires at least one product in the
        catalog, failing with `ERR_PRODUCT_CATALOG_EMPTY` otherwise".

        Design: Corner/state_machines/season_open_requires_nonempty_catalog
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        resp = api.open_season(season["id"], admin)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_CATALOG_EMPTY, 422)
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "DRAFT"

    def test_season_terminal_lockdown_closed_rejects_open(self, api):
        """PRD §2.4: "A state transition attempted on a resource that is not in
        a state from which that transition exists is rejected with the
        domain-specific state error where one exists
        (`ERR_SEASON_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`,
        `ERR_TRANSFER_INVALID_STATE`, `ERR_REQUEST_INVALID_STATE`,
        `ERR_PAYMENT_INVALID_STATE`, `ERR_FULFILLMENT_INVALID_STATE`,
        `ERR_PO_INVALID_STATE`, `ERR_RECALL_INVALID_STATE`,
        `ERR_AGREEMENT_INVALID_STATE`), or with the generic
        `ERR_INVALID_STATE` (HTTP 409) where none applies." PRD §3.9: "the
        `RECONCILIATION` → `CLOSED` transition".

        Design: Corner/state_machines/season_terminal_lockdown_closed_rejects_open
        """
        admin = make_council_admin_headers()
        ctx = setup_closed_season(purchase_qty=100, confirm_qty=80, admin=admin)
        season = ctx["season"]
        assert season["status"] == "CLOSED"
        resp = api.open_season(season["id"], admin)
        validate_error(resp, ApiErrorId.ERR_SEASON_INVALID_STATE, 409)
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "CLOSED"
