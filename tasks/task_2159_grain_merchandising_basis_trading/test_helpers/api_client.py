"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Grain merchandising desk API. Every collection is a peer under /grain."""

    # ─── TradingDesk ──────────────────────────────────
    def create_trading_desk(self, payload, headers):
        return self._request("POST", "/grain/trading-desks", payload, headers)

    def list_trading_desks(self, headers, params=None):
        return self._request("GET", "/grain/trading-desks", headers=headers, params=params)

    def get_trading_desk(self, desk_id, headers):
        return self._request("GET", f"/grain/trading-desks/{desk_id}", headers=headers)

    def get_position_report(self, desk_id, headers, params=None):
        return self._request(
            "GET", f"/grain/trading-desks/{desk_id}/position-report",
            headers=headers, params=params,
        )

    # ─── ElevatorLocation ─────────────────────────────
    def create_elevator_location(self, payload, headers):
        return self._request("POST", "/grain/elevator-locations", payload, headers)

    def list_elevator_locations(self, headers, params=None):
        return self._request("GET", "/grain/elevator-locations", headers=headers, params=params)

    def get_elevator_location(self, location_id, headers):
        return self._request("GET", f"/grain/elevator-locations/{location_id}", headers=headers)

    # ─── DiscountSchedule ─────────────────────────────
    def create_discount_schedule(self, payload, headers):
        return self._request("POST", "/grain/discount-schedules", payload, headers)

    def activate_discount_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/grain/discount-schedules/{schedule_id}/activate", {}, headers
        )

    def list_discount_schedules(self, headers, params=None):
        return self._request("GET", "/grain/discount-schedules", headers=headers, params=params)

    def get_discount_schedule(self, schedule_id, headers):
        return self._request("GET", f"/grain/discount-schedules/{schedule_id}", headers=headers)

    # ─── RiskLimit ────────────────────────────────────
    def create_risk_limit(self, payload, headers):
        return self._request("POST", "/grain/risk-limits", payload, headers)

    def list_risk_limits(self, headers, params=None):
        return self._request("GET", "/grain/risk-limits", headers=headers, params=params)

    def get_risk_limit(self, risk_limit_id, headers):
        return self._request("GET", f"/grain/risk-limits/{risk_limit_id}", headers=headers)

    # ─── RailFleet ────────────────────────────────────
    def create_rail_fleet(self, payload, headers):
        return self._request("POST", "/grain/rail-fleets", payload, headers)

    def list_rail_fleets(self, headers, params=None):
        return self._request("GET", "/grain/rail-fleets", headers=headers, params=params)

    def get_rail_fleet(self, fleet_id, headers):
        return self._request("GET", f"/grain/rail-fleets/{fleet_id}", headers=headers)

    # ─── Bid ──────────────────────────────────────────
    def create_bid(self, payload, headers):
        return self._request("POST", "/grain/bids", payload, headers)

    def activate_bid(self, bid_id, headers):
        return self._request("POST", f"/grain/bids/{bid_id}/activate", {}, headers)

    def suspend_bid(self, bid_id, headers):
        return self._request("POST", f"/grain/bids/{bid_id}/suspend", {}, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/grain/bids/{bid_id}/withdraw", {}, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/grain/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/grain/bids/{bid_id}", headers=headers)

    # ─── HedgePosition ────────────────────────────────
    def create_hedge_position(self, payload, headers):
        return self._request("POST", "/grain/hedge-positions", payload, headers)

    def add_lots(self, position_id, payload, headers):
        return self._request(
            "POST", f"/grain/hedge-positions/{position_id}/add-lots", payload, headers
        )

    def mark_to_market(self, position_id, payload, headers):
        return self._request(
            "POST", f"/grain/hedge-positions/{position_id}/mark-to-market", payload, headers
        )

    def liquidate_hedge_position(self, position_id, payload, headers):
        return self._request(
            "POST", f"/grain/hedge-positions/{position_id}/liquidate", payload, headers
        )

    def list_hedge_positions(self, headers, params=None):
        return self._request("GET", "/grain/hedge-positions", headers=headers, params=params)

    def get_hedge_position(self, position_id, headers):
        return self._request("GET", f"/grain/hedge-positions/{position_id}", headers=headers)

    # ─── PurchaseContract ─────────────────────────────
    def create_purchase_contract(self, payload, headers):
        return self._request("POST", "/grain/purchase-contracts", payload, headers)

    def roll_purchase_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grain/purchase-contracts/{contract_id}/roll", payload, headers
        )

    def cancel_purchase_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grain/purchase-contracts/{contract_id}/cancel", payload, headers
        )

    def declare_default(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/grain/purchase-contracts/{contract_id}/declare-default", payload, headers
        )

    def list_purchase_contracts(self, headers, params=None):
        return self._request("GET", "/grain/purchase-contracts", headers=headers, params=params)

    def get_purchase_contract(self, contract_id, headers):
        return self._request("GET", f"/grain/purchase-contracts/{contract_id}", headers=headers)

    # ─── PricingOrder ─────────────────────────────────
    def create_pricing_order(self, payload, headers):
        return self._request("POST", "/grain/pricing-orders", payload, headers)

    def list_pricing_orders(self, headers, params=None):
        return self._request("GET", "/grain/pricing-orders", headers=headers, params=params)

    def get_pricing_order(self, pricing_order_id, headers):
        return self._request("GET", f"/grain/pricing-orders/{pricing_order_id}", headers=headers)

    # ─── MarginCall ───────────────────────────────────
    def cure_margin_call(self, margin_call_id, payload, headers):
        return self._request(
            "POST", f"/grain/margin-calls/{margin_call_id}/cure", payload, headers
        )

    def list_margin_calls(self, headers, params=None):
        return self._request("GET", "/grain/margin-calls", headers=headers, params=params)

    def get_margin_call(self, margin_call_id, headers):
        return self._request("GET", f"/grain/margin-calls/{margin_call_id}", headers=headers)

    # ─── DeliveryTicket ───────────────────────────────
    def create_delivery_ticket(self, payload, headers):
        return self._request("POST", "/grain/delivery-tickets", payload, headers)

    def apply_delivery_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/grain/delivery-tickets/{ticket_id}/apply", {}, headers
        )

    def reject_delivery_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/grain/delivery-tickets/{ticket_id}/reject", payload, headers
        )

    def reverse_delivery_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/grain/delivery-tickets/{ticket_id}/reverse", payload, headers
        )

    def list_delivery_tickets(self, headers, params=None):
        return self._request("GET", "/grain/delivery-tickets", headers=headers, params=params)

    def get_delivery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/grain/delivery-tickets/{ticket_id}", headers=headers)

    # ─── FreightBooking ───────────────────────────────
    def create_freight_booking(self, payload, headers):
        return self._request("POST", "/grain/freight-bookings", payload, headers)

    def confirm_freight_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/grain/freight-bookings/{booking_id}/confirm", {}, headers
        )

    def substitute_freight_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/grain/freight-bookings/{booking_id}/substitute", payload, headers
        )

    def cancel_freight_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/grain/freight-bookings/{booking_id}/cancel", payload, headers
        )

    def list_freight_bookings(self, headers, params=None):
        return self._request("GET", "/grain/freight-bookings", headers=headers, params=params)

    def get_freight_booking(self, booking_id, headers):
        return self._request("GET", f"/grain/freight-bookings/{booking_id}", headers=headers)

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Raw escape hatch (headerless / malformed requests) ───
    def raw_post(self, path, payload=None, headers=None):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
