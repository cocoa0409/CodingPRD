"""API client: one method per endpoint defined in PRD §4.

Success-status map: PRD §4 states "Endpoints that create a new resource return
201 with the created resource; the delivery-recording action on a sales
contract also returns 201 ... All other actions, transitions, computed reads,
and plain reads return 200." ENDPOINT_SUCCESS_STATUS records that per method
name so tests call validate_success(resp, ENDPOINT_SUCCESS_STATUS[...]).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        """POST /api/_clock/set_current_utc — advance the logical clock and run the sweep."""
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------------- farmers
    def create_farmer(self, payload, headers):
        return self._request("POST", "/api/farmers", payload, headers)

    # --------------------------------------------------------------- elevators
    def create_elevator(self, payload, headers):
        return self._request("POST", "/api/elevators", payload, headers)

    def get_elevator(self, elevator_id, headers):
        return self._request("GET", f"/api/elevators/{elevator_id}", headers=headers)

    def list_elevators(self, headers, params=None):
        return self._request("GET", "/api/elevators", headers=headers, params=params)

    def get_carry_assessment(self, elevator_id, headers, params=None):
        return self._request(
            "GET", f"/api/elevators/{elevator_id}/carry-assessment",
            headers=headers, params=params,
        )

    # ------------------------------------------------- quality discount schedules
    def create_quality_discount_schedule(self, payload, headers):
        return self._request("POST", "/api/quality-discount-schedules", payload, headers)

    def publish_quality_discount_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/api/quality-discount-schedules/{schedule_id}/publish",
            {}, headers,
        )

    # --------------------------------------------------- sustainability programs
    def create_sustainability_program(self, payload, headers):
        return self._request("POST", "/api/sustainability-programs", payload, headers)

    def close_sustainability_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/sustainability-programs/{program_id}/close",
            {}, headers,
        )

    # ------------------------------------------------------------ market quotes
    def create_market_quote(self, payload, headers):
        return self._request("POST", "/api/market-quotes", payload, headers)

    def list_market_quotes(self, headers, params=None):
        return self._request("GET", "/api/market-quotes", headers=headers, params=params)

    # -------------------------------------------------------------- crush plants
    def create_crush_plant(self, payload, headers):
        return self._request("POST", "/api/crush-plants", payload, headers)

    def get_crush_plant(self, plant_id, headers):
        return self._request("GET", f"/api/crush-plants/{plant_id}", headers=headers)

    # ------------------------------------------------------------------ buyers
    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/buyers/{buyer_id}", headers=headers)

    # ------------------------------------------------------ origination contracts
    def create_origination_contract(self, payload, headers):
        return self._request("POST", "/api/origination-contracts", payload, headers)

    def get_origination_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/api/origination-contracts/{contract_id}", headers=headers,
        )

    def list_origination_contracts(self, headers, params=None):
        return self._request(
            "GET", "/api/origination-contracts", headers=headers, params=params,
        )

    def create_pricing_election(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/origination-contracts/{contract_id}/pricing-elections",
            payload, headers,
        )

    def settle_origination_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/origination-contracts/{contract_id}/settle",
            {}, headers,
        )

    # ----------------------------------------------------------- delivery tickets
    def create_delivery_ticket(self, payload, headers):
        return self._request("POST", "/api/delivery-tickets", payload, headers)

    def get_delivery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/delivery-tickets/{ticket_id}", headers=headers)

    def list_delivery_tickets(self, headers, params=None):
        return self._request("GET", "/api/delivery-tickets", headers=headers, params=params)

    def apply_delivery_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/delivery-tickets/{ticket_id}/apply", {}, headers,
        )

    # --------------------------------------------------------- storage positions
    def get_storage_position(self, position_id, headers):
        return self._request(
            "GET", f"/api/storage-positions/{position_id}", headers=headers,
        )

    def list_storage_positions(self, headers, params=None):
        return self._request("GET", "/api/storage-positions", headers=headers, params=params)

    # -------------------------------------------------------------- freight lanes
    def create_freight_lane(self, payload, headers):
        return self._request("POST", "/api/freight-lanes", payload, headers)

    def get_freight_lane(self, lane_id, headers):
        return self._request("GET", f"/api/freight-lanes/{lane_id}", headers=headers)

    def list_freight_lanes(self, headers, params=None):
        return self._request("GET", "/api/freight-lanes", headers=headers, params=params)

    def create_shipment_routing_quote(self, payload, headers):
        return self._request("POST", "/api/shipment-routing-quotes", payload, headers)

    # ----------------------------------------------------------------- shipments
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/deliver", {}, headers,
        )

    def cancel_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/cancel", {}, headers,
        )

    # ---------------------------------------------------------------- crush runs
    def create_crush_run(self, payload, headers):
        return self._request("POST", "/api/crush-runs", payload, headers)

    def get_crush_run(self, run_id, headers):
        return self._request("GET", f"/api/crush-runs/{run_id}", headers=headers)

    def list_crush_runs(self, headers, params=None):
        return self._request("GET", "/api/crush-runs", headers=headers, params=params)

    def schedule_crush_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/crush-runs/{run_id}/schedule", payload, headers,
        )

    def transition_crush_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/crush-runs/{run_id}/transitions", payload, headers,
        )

    # ------------------------------------------------------- board crush positions
    def create_board_crush_position(self, payload, headers):
        return self._request("POST", "/api/board-crush-positions", payload, headers)

    def get_board_crush_position(self, position_id, headers):
        return self._request(
            "GET", f"/api/board-crush-positions/{position_id}", headers=headers,
        )

    def confirm_board_crush_position(self, position_id, headers):
        return self._request(
            "POST", f"/api/board-crush-positions/{position_id}/confirm", {}, headers,
        )

    def offset_board_crush_position(self, position_id, headers):
        return self._request(
            "POST", f"/api/board-crush-positions/{position_id}/offset", {}, headers,
        )

    # ----------------------------------------------------- product sales contracts
    def create_product_sales_contract(self, payload, headers):
        return self._request("POST", "/api/product-sales-contracts", payload, headers)

    def get_product_sales_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/api/product-sales-contracts/{contract_id}", headers=headers,
        )

    def list_product_sales_contracts(self, headers, params=None):
        return self._request(
            "GET", "/api/product-sales-contracts", headers=headers, params=params,
        )

    def deliver_product_sales_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/product-sales-contracts/{contract_id}/deliver",
            payload, headers,
        )


# -----------------------------------------------------------------------------
# Expected success HTTP status per client method (PRD §4 locator table plus the
# §4 rule: resource-creating endpoints and the sales-delivery append return 201;
# every other action, transition, computed read, and plain read returns 200).
# -----------------------------------------------------------------------------
ENDPOINT_SUCCESS_STATUS = {
    # clock sweep — action, 200
    "set_clock": 200,
    # creates — 201
    "create_farmer": 201,
    "create_elevator": 201,
    "create_quality_discount_schedule": 201,
    "create_sustainability_program": 201,
    "create_market_quote": 201,
    "create_crush_plant": 201,
    "create_buyer": 201,
    "create_origination_contract": 201,
    "create_delivery_ticket": 201,
    "create_freight_lane": 201,
    "create_shipment": 201,
    "create_crush_run": 201,
    "create_board_crush_position": 201,
    "create_product_sales_contract": 201,
    # sales-delivery append — explicitly 201 per PRD §4
    "deliver_product_sales_contract": 201,
    # actions / transitions — 200
    "publish_quality_discount_schedule": 200,
    "close_sustainability_program": 200,
    "create_pricing_election": 200,
    "settle_origination_contract": 200,
    "apply_delivery_ticket": 200,
    "create_shipment_routing_quote": 200,
    "deliver_shipment": 200,
    "cancel_shipment": 200,
    "schedule_crush_run": 200,
    "transition_crush_run": 200,
    "confirm_board_crush_position": 200,
    "offset_board_crush_position": 200,
    # reads — 200
    "get_elevator": 200,
    "list_elevators": 200,
    "get_carry_assessment": 200,
    "list_market_quotes": 200,
    "get_crush_plant": 200,
    "get_buyer": 200,
    "get_origination_contract": 200,
    "list_origination_contracts": 200,
    "get_delivery_ticket": 200,
    "list_delivery_tickets": 200,
    "get_storage_position": 200,
    "list_storage_positions": 200,
    "get_freight_lane": 200,
    "list_freight_lanes": 200,
    "get_shipment": 200,
    "list_shipments": 200,
    "get_crush_run": 200,
    "list_crush_runs": 200,
    "get_board_crush_position": 200,
    "get_product_sales_contract": 200,
    "list_product_sales_contracts": 200,
}


api_client = ApiClient()

__all__ = ["ApiClient", "api_client", "ENDPOINT_SUCCESS_STATUS"]
