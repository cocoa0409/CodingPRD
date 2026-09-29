"""Typed HTTP client for the Landscape Supply Yard bulk-material API.

One method per operation. Every method returns the raw ``requests.Response`` so the
caller decides whether to assert success or an error.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Endpoint methods for every path the API exposes."""

    # ------------------------------------------------------------------ materials
    def create_material(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/materials", payload=payload, headers=headers)

    def list_materials(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/materials", params=params, headers=headers)

    def get_material(self, material_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/materials/{material_id}", headers=headers)

    def patch_material(
        self, material_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/materials/{material_id}", payload=payload, headers=headers)

    # ------------------------------------------------------------ price schedules
    def create_price_schedule(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/price-schedules", payload=payload, headers=headers)

    def list_price_schedules(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/price-schedules", params=params, headers=headers)

    def get_price_schedule(
        self, price_schedule_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/price-schedules/{price_schedule_id}", headers=headers)

    # ------------------------------------------------------------- inventory lots
    def create_inventory_lot(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/inventory-lots", payload=payload, headers=headers)

    def list_inventory_lots(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/inventory-lots", params=params, headers=headers)

    def get_inventory_lot(self, inventory_lot_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/inventory-lots/{inventory_lot_id}", headers=headers)

    def create_moisture_reading(
        self, inventory_lot_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/inventory-lots/{inventory_lot_id}/moisture-readings", payload=payload, headers=headers
        )

    # ------------------------------------------------------- contractor accounts
    def create_contractor_account(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/contractor-accounts", payload=payload, headers=headers)

    def list_contractor_accounts(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/contractor-accounts", params=params, headers=headers)

    def get_contractor_account(
        self, contractor_account_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/contractor-accounts/{contractor_account_id}", headers=headers)

    def create_credit_adjustment(
        self, contractor_account_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/contractor-accounts/{contractor_account_id}/credit-adjustments",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------ job purchase orders
    def create_job_purchase_order(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/job-purchase-orders", payload=payload, headers=headers)

    def list_job_purchase_orders(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/job-purchase-orders", params=params, headers=headers)

    def get_job_purchase_order(
        self, job_purchase_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/job-purchase-orders/{job_purchase_order_id}", headers=headers)

    def close_job_purchase_order(
        self, job_purchase_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/job-purchase-orders/{job_purchase_order_id}/close", payload={}, headers=headers
        )

    # --------------------------------------------------------- prebuy contracts
    def create_prebuy_contract(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/prebuy-contracts", payload=payload, headers=headers)

    def list_prebuy_contracts(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/prebuy-contracts", params=params, headers=headers)

    def get_prebuy_contract(
        self, prebuy_contract_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/prebuy-contracts/{prebuy_contract_id}", headers=headers)

    def activate_prebuy_contract(
        self, prebuy_contract_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/prebuy-contracts/{prebuy_contract_id}/activate", payload={}, headers=headers
        )

    # ----------------------------------------------------------- material orders
    def create_material_order(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/material-orders", payload=payload, headers=headers)

    def list_material_orders(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/material-orders", params=params, headers=headers)

    def get_material_order(self, material_order_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/material-orders/{material_order_id}", headers=headers)

    def confirm_material_order(
        self, material_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/material-orders/{material_order_id}/confirm", payload={}, headers=headers)

    def cancel_material_order(
        self, material_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/material-orders/{material_order_id}/cancel", payload={}, headers=headers)

    def invoice_material_order(
        self, material_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/material-orders/{material_order_id}/invoice", payload={}, headers=headers)

    def settle_material_order(
        self, material_order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/material-orders/{material_order_id}/settle", payload=payload, headers=headers
        )

    # --------------------------------------------------------------- order lines
    def create_order_line(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/order-lines", payload=payload, headers=headers)

    def list_order_lines(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/order-lines", params=params, headers=headers)

    def get_order_line(self, order_line_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    # ------------------------------------------------------------ delivery trucks
    def create_delivery_truck(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/delivery-trucks", payload=payload, headers=headers)

    def list_delivery_trucks(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-trucks", params=params, headers=headers)

    def get_delivery_truck(self, delivery_truck_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/delivery-trucks/{delivery_truck_id}", headers=headers)

    def patch_delivery_truck(
        self, delivery_truck_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/delivery-trucks/{delivery_truck_id}", payload=payload, headers=headers)

    # ------------------------------------------------------------- delivery loads
    def create_delivery_load(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/delivery-loads", payload=payload, headers=headers)

    def list_delivery_loads(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-loads", params=params, headers=headers)

    def get_delivery_load(self, delivery_load_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/delivery-loads/{delivery_load_id}", headers=headers)

    def dispatch_delivery_load(
        self, delivery_load_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-loads/{delivery_load_id}/dispatch", payload={}, headers=headers
        )

    def deliver_delivery_load(
        self, delivery_load_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-loads/{delivery_load_id}/deliver", payload=payload, headers=headers
        )

    def refuse_delivery_load(
        self, delivery_load_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-loads/{delivery_load_id}/refuse", payload=payload, headers=headers
        )

    def replan_delivery_load(
        self, delivery_load_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-loads/{delivery_load_id}/replan", payload=payload, headers=headers
        )

    def cancel_delivery_load(self, delivery_load_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", f"/delivery-loads/{delivery_load_id}/cancel", payload={}, headers=headers)

    # ---------------------------------------------------------- will-call tickets
    def create_will_call_ticket(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/will-call-tickets", payload=payload, headers=headers)

    def list_will_call_tickets(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/will-call-tickets", params=params, headers=headers)

    def get_will_call_ticket(
        self, will_call_ticket_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/will-call-tickets/{will_call_ticket_id}", headers=headers)

    def stage_next_will_call_ticket(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/will-call-tickets/stage-next", payload=payload, headers=headers)

    def safety_ack_will_call_ticket(
        self, will_call_ticket_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/will-call-tickets/{will_call_ticket_id}/safety-ack", payload=payload, headers=headers
        )

    def load_will_call_ticket(
        self, will_call_ticket_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/will-call-tickets/{will_call_ticket_id}/load", payload=payload, headers=headers
        )

    def release_will_call_ticket(
        self, will_call_ticket_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/will-call-tickets/{will_call_ticket_id}/release", payload={}, headers=headers
        )

    def cancel_will_call_ticket(
        self, will_call_ticket_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/will-call-tickets/{will_call_ticket_id}/cancel", payload={}, headers=headers
        )

    # ---------------------------------------------------------------- claim cases
    def create_claim_case(self, payload: Payload, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", "/claim-cases", payload=payload, headers=headers)

    def list_claim_cases(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/claim-cases", params=params, headers=headers)

    def get_claim_case(self, claim_case_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("GET", f"/claim-cases/{claim_case_id}", headers=headers)

    def start_review_claim_case(self, claim_case_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", f"/claim-cases/{claim_case_id}/start-review", payload={}, headers=headers)

    def request_info_claim_case(
        self, claim_case_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/claim-cases/{claim_case_id}/request-info", payload=payload, headers=headers
        )

    def provide_info_claim_case(
        self, claim_case_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/claim-cases/{claim_case_id}/provide-info", payload=payload, headers=headers
        )

    def decide_claim_case(
        self, claim_case_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", f"/claim-cases/{claim_case_id}/decide", payload=payload, headers=headers)

    def settle_claim_case(self, claim_case_id: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request("POST", f"/claim-cases/{claim_case_id}/settle", payload={}, headers=headers)

    # ----------------------------------------------------------- container returns
    def list_container_returns(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/container-returns", params=params, headers=headers)

    def get_container_return(
        self, container_return_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/container-returns/{container_return_id}", headers=headers)

    def receive_container_return(
        self, container_return_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/container-returns/{container_return_id}/receive", payload=payload, headers=headers
        )

    def forfeit_container_return(
        self, container_return_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/container-returns/{container_return_id}/forfeit", payload={}, headers=headers
        )

    # ------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601: str, headers: Optional[Headers] = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload={"to_iso8601": to_iso8601}, headers=headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
