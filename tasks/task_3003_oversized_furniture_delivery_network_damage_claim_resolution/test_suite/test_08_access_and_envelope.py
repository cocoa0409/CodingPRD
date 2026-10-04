"""Cross-cutting: authentication/authorization, error-envelope shape,
validation priority, shipment filters, and the order-cancel slot-release
invariant."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    set_clock,
    create_supplier,
    create_customer,
    create_item,
    create_freight_lane,
    create_hub,
    create_linehaul,
    setup_reference_data,
    setup_routed_network_order,
    setup_delivered_network_order,
    setup_determined_claim,
    place_order,
    get_shipment_for_order,
    open_claim,
    api_client,
    TEST_USERS,
    make_customer_headers,
    make_supplier_rep_headers,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
CARRIER = TEST_USERS["carrier_rep_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through a pair of mandatory HTTP headers."
        PRD §2.1: "A request whose headers are missing or empty is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        set_clock(SETUP_CLOCK)
        resp = api.list_items({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_customer_cannot_create_items_or_lanes(self, api):
        """PRD §2.1: "When the headers are present but the named role is not
        permitted to perform the requested operation — or when a
        `SupplierRep` attempts to act on a chargeback belonging to a
        different supplier — the request is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: "| POST | `/oversize-freight/items` | List an item (cubing,
        freight class, parcel gate computed at listing) | NetworkAdmin |"
        PRD §4: "| POST | `/oversize-freight/freight-lanes` | Create a
        freight lane (rate card entry) | NetworkAdmin |"

        Design: Corner/rbac/customer_cannot_create_items_or_lanes
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        resp1 = api.create_item(
            {"supplier_id": supplier["id"], "sku": "SKU-DENY",
             "dim_length_in": 10, "dim_width_in": 10, "dim_height_in": 10,
             "weight_lb": 5, "declared_value_cents": 1000,
             "white_glove_eligible": False},
            headers,
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)
        resp2 = api.create_freight_lane(
            {"leg_mode": "LTL", "dest_zone": "ZONE_NE", "base_rate_cents": 1000,
             "per_lb_rate_cents": 10, "transit_days": 3},
            headers,
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)
        items, _m1 = validate_paginated(api.list_items(ADMIN))
        lanes, _m2 = validate_paginated(api.list_freight_lanes(ADMIN))
        assert len(items) == 0
        assert len(lanes) == 0

    def test_hub_operator_cannot_determine_or_settle_claims(self, api):
        """PRD §2.1: "When the headers are present but the named role is not
        permitted to perform the requested operation — or when a
        `SupplierRep` attempts to act on a chargeback belonging to a
        different supplier — the request is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: "| POST | `/oversize-freight/damage-claims/{claimId}/determine`
        | Determine liability; creates a chargeback when the supplier is
        liable | ClaimsAdjuster |"
        PRD §4: "| POST | `/oversize-freight/damage-claims/{claimId}/settle` |
        Settle claim (requires linked chargeback resolved first) |
        ClaimsAdjuster |"

        Design: Corner/rbac/hub_operator_cannot_determine_or_settle_claims
        """
        refs = setup_delivered_network_order()
        claim = open_claim(refs["shipment"]["id"], refs["customer"],
                           concealment="CONCEALED")
        validate_success(
            api.inspect_damage_claim(
                claim["id"],
                {"damage_pct": 20, "is_structural": False,
                 "repair_cost_cents": 20000},
                HUB_OP,
            ),
            200,
        )
        resp_det = api.determine_damage_claim(claim["id"], HUB_OP)
        validate_error(resp_det, ApiErrorId.ERR_FORBIDDEN)
        resp_set = api.settle_damage_claim(claim["id"], HUB_OP)
        validate_error(resp_set, ApiErrorId.ERR_FORBIDDEN)
        still = validate_success(api.get_damage_claim(claim["id"], ADMIN))
        assert still["status"] == "INSPECTION"

    def test_supplier_rep_cannot_dispute_another_suppliers_chargeback(self, api):
        """PRD §3.7: "Disputing is guarded twice: the chargeback must be
        `PENDING` (else `ERR_INVALID_STATE`), and the acting `SupplierRep`'s
        `X-User-ID` must equal the chargeback's `supplier_id`, else
        `ERR_FORBIDDEN` — a supplier may never dispute another supplier's
        chargeback."

        Design: Corner/rbac/supplier_rep_cannot_dispute_another_suppliers_chargeback
        """
        refs = setup_determined_claim(concealment="CONCEALED")
        other = create_supplier("SUP-Z", legal_name="Unrelated Supplier")
        cb = refs["chargeback"]
        foreign = api.dispute_chargeback(
            cb["id"], make_supplier_rep_headers(other["id"])
        )
        validate_error(foreign, ApiErrorId.ERR_FORBIDDEN)
        own = api.dispute_chargeback(
            cb["id"], make_supplier_rep_headers(refs["supplier"]["id"])
        )
        data = validate_success(own, 200)
        assert data["status"] == "DISPUTED"


class TestErrorEnvelope:
    def test_error_envelope_carries_typed_error_id_and_message(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of
        what went wrong."

        Design: Corner/errors/error_envelope_carries_typed_error_id_and_message
        """
        from test_helpers import NON_EXISTENT_UUID
        set_clock(SETUP_CLOCK)
        resp = api.get_hub(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestStateBeatsFiscalOnOrderCancel:
    def _setup_in_transit(self, api):
        """Routed order departed (order_state IN_TRANSIT); no active LTL lane
        remains for the zone."""
        refs = setup_routed_network_order()
        validate_success(api.depart_shipment(refs["shipment"]["id"], CARRIER), 200)
        return refs

    def test_cancel_in_transit_order_returns_invalid_state(self, api):
        """PRD §3.3: "Cancellation is available to the ordering `Customer` or
        a `NetworkAdmin`, but only while `order_state` is `PENDING` or
        `ROUTED` — a later-stage cancel is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_cancel
        """
        refs = self._setup_in_transit(api)
        resp = api.cancel_order(
            refs["order"]["id"], make_customer_headers(refs["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        order = validate_success(api.get_order(refs["order"]["id"], ADMIN))
        assert order["order_state"] == "IN_TRANSIT"

    def test_state_failure_never_surfaces_pricing_error(self, api):
        """PRD §2.7: "Every incoming request passes through a fixed validation
        pipeline, and the order matters because the first failing check
        determines the error returned."
        PRD §3.3: "Cancellation is available to the ordering `Customer` or a
        `NetworkAdmin`, but only while `order_state` is `PENDING` or
        `ROUTED` — a later-stage cancel is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_cancel
        """
        refs = self._setup_in_transit(api)
        resp = api.cancel_order(
            refs["order"]["id"], make_customer_headers(refs["customer"]["id"])
        )
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_PRICING_UNAVAILABLE


class TestLinehaulSlotCommitReleaseConservesCapacity:
    def test_routing_consumes_one_slot(self, api):
        """PRD §3.3: "Binding increments the linehaul's `committed_count` by
        one."
        PRD §3.2: "`committed_count` is a derived counter equal to the number
        of shipments currently bound to the linehaul whose `current_state` is
        neither `DELIVERED` nor `EXCEPTION`."

        Design: Difficulty/compensating_invariant/linehaul_slot_commit_release_conserves_capacity
        """
        refs = setup_routed_network_order()
        linehaul = validate_success(api.get_linehaul(refs["linehaul"]["id"], ADMIN))
        assert linehaul["committed_count"] == 1, (
            "routing an OWNED_FINAL_MILE order consumes exactly one slot"
        )

    def test_cancel_releases_the_slot(self, api):
        """PRD §3.3: "Cancelling moves the order to `CANCELLED`, moves its
        shipment to `EXCEPTION`, decrements the bound linehaul's
        `committed_count` by one to release the slot, and leaves
        `fulfillment_state` at `NONE`."

        Design: Difficulty/compensating_invariant/linehaul_slot_commit_release_conserves_capacity
        """
        refs = setup_routed_network_order()
        before = validate_success(api.get_linehaul(refs["linehaul"]["id"], ADMIN))
        assert before["committed_count"] == 1
        resp = api.cancel_order(
            refs["order"]["id"], make_customer_headers(refs["customer"]["id"])
        )
        order = validate_success(resp, 200)
        after = validate_success(api.get_linehaul(refs["linehaul"]["id"], ADMIN))
        assert after["committed_count"] == 0, (
            "capacity - committed_count is invariant across the create+cancel pair"
        )
        assert order["order_state"] == "CANCELLED"
        assert order["fulfillment_state"] == "NONE"


class TestShipmentListFilters:
    def test_shipments_list_filters_by_state_and_hub(self, api):
        """PRD §4: "| GET | `/oversize-freight/shipments` | List shipments |
        NetworkAdmin, HubOperator, ClaimsAdjuster, SupplierRep |"
        PRD §3.3: "A successful order creation creates exactly one `Shipment`
        for the order."
        PRD §3.3: "The shipment copies its `order_id`, `item_id`, and
        `supplier_id` from the order and item, records the routed
        `fulfillment_mode` and `leg_mode`, and is born already in
        `TENDERED`"

        Design: Corner/endpoints/shipments_list_filters_by_state_and_hub
        """
        refs = setup_delivered_network_order()
        # A second, still-TENDERED network order bound to the same hub. The
        # first order's linehaul has already ARRIVED, and PRD §3.3 binds only
        # PLANNED linehauls, so a fresh PLANNED trailer must exist for the
        # second order to route.
        create_linehaul(
            refs["hub"]["id"], planned_arrival_date="2026-09-11",
            origin_ship_date="2026-09-08", capacity=10,
        )
        order_t = place_order(refs["customer"], refs["item"]["id"], "THRESHOLD")

        delivered, meta_d = validate_paginated(
            api.list_shipments(ADMIN, params={"current_state": "DELIVERED"})
        )
        assert len(delivered) == 1
        assert meta_d["total_count"] == 1

        hub_rows, meta_h = validate_paginated(
            api.list_shipments(ADMIN, params={"hub_id": refs["hub"]["id"]})
        )
        assert len(hub_rows) == 2, (
            "both hub-bound shipments match the hub filter"
        )

        order_rows, meta_o = validate_paginated(
            api.list_shipments(ADMIN, params={"order_id": order_t["id"]})
        )
        assert len(order_rows) == 1
        assert order_rows[0]["current_state"] == "TENDERED"


class TestShipmentDeliverConditionalAction:
    def test_shipment_deliver_rejected_for_owned_final_mile(self, api):
        """PRD §3.4: "Parcel and drop-ship shipments instead take a direct
        delivery confirmation from a `CarrierRep` or `SupplierRep`: the
        shipment must be `IN_TRANSIT` and its `fulfillment_mode` must not be
        `OWNED_FINAL_MILE` — hub shipments deliver via appointment, and an
        attempt to direct-deliver one is rejected with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/shipment_deliver_rejected_for_owned_final_mile
        """
        from test_helpers import setup_shipment_in_transit
        refs = setup_shipment_in_transit()
        resp = api.deliver_shipment(refs["shipment"]["id"], CARRIER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_shipment(refs["shipment"]["id"], ADMIN))
        assert still["current_state"] == "IN_TRANSIT"
