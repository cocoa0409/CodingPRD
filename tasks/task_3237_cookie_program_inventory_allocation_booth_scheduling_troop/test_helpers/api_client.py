"""API client: one method per endpoint defined in the Cookie Program PRD."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Cookie Program API client. The base _request() handles HTTP."""

    # ---- Season lifecycle ----
    def create_season(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/cookie-program/seasons", payload, headers)

    def list_seasons(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/cookie-program/seasons", headers=headers, params=params)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/seasons/{season_id}", headers=headers)

    def open_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cookie-program/seasons/{season_id}/open", headers=headers)

    def cancel_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cookie-program/seasons/{season_id}/cancel", headers=headers)

    def begin_reconciliation(self, season_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/begin-reconciliation", headers=headers
        )

    def close_out_season(self, season_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/close-out", headers=headers
        )

    # ---- Products ----
    def create_product(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/products", payload, headers
        )

    def list_season_products(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/products", headers=headers, params=params
        )

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/products/{product_id}", headers=headers)

    def list_products(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/products", headers=headers, params=params)

    # ---- Troops ----
    def create_troop(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/cookie-program/troops", payload, headers)

    def get_troop(self, troop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/troops/{troop_id}", headers=headers)

    # ---- TroopAccount ----
    def create_account(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/accounts", payload, headers
        )

    def list_season_accounts(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/accounts", headers=headers, params=params
        )

    def list_accounts(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/accounts", headers=headers, params=params)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/accounts/{account_id}", headers=headers)

    def record_deposit(self, account_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/accounts/{account_id}/deposits", payload, headers
        )

    # ---- CookieOrders ----
    def create_order(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/orders", payload, headers
        )

    def list_season_orders(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/orders", headers=headers, params=params
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/orders/{order_id}", headers=headers)

    def list_orders(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/orders", headers=headers, params=params)

    def add_order_line(self, season_id: str, order_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/seasons/{season_id}/orders/{order_id}/lines",
            payload,
            headers,
        )

    def list_order_lines(self, order_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/orders/{order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/order-lines/{line_id}", headers=headers)

    def list_order_lines_global(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/order-lines", headers=headers, params=params)

    def submit_order(self, season_id: str, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/orders/{order_id}/submit", headers=headers
        )

    def confirm_order(self, season_id: str, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/orders/{order_id}/confirm", headers=headers
        )

    def reject_order(self, season_id: str, order_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/seasons/{season_id}/orders/{order_id}/reject",
            payload,
            headers,
        )

    def fulfill_order(self, season_id: str, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/orders/{order_id}/fulfill", headers=headers
        )

    # ---- Distribution sites & baker POs ----
    def create_site(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/sites", payload, headers
        )

    def list_season_sites(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/sites", headers=headers, params=params
        )

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/sites/{site_id}", headers=headers)

    def list_sites(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/sites", headers=headers, params=params)

    def create_baker_po(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/baker-pos", payload, headers
        )

    def list_season_baker_pos(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/baker-pos", headers=headers, params=params
        )

    def get_baker_po(self, po_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/baker-pos/{po_id}", headers=headers)

    def list_baker_pos(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/baker-pos", headers=headers, params=params)

    def place_baker_po(self, season_id: str, po_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/baker-pos/{po_id}/place", headers=headers
        )

    def record_delivery(self, season_id: str, po_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/seasons/{season_id}/baker-pos/{po_id}/record-delivery",
            payload,
            headers,
        )

    # ---- Transfers ----
    def create_transfer(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/cookie-program/transfers", payload, headers)

    def list_transfers(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/transfers/{transfer_id}", headers=headers)

    def sign_ship(self, transfer_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/transfers/{transfer_id}/sign-ship", payload, headers
        )

    def sign_receive(self, transfer_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/transfers/{transfer_id}/sign-receive", payload, headers
        )

    def complete_transfer(self, transfer_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/transfers/{transfer_id}/complete", payload, headers
        )

    def retract_ship_signature(self, transfer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/transfers/{transfer_id}/retract-ship-signature",
            headers=headers,
        )

    def decline_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/transfers/{transfer_id}/decline", headers=headers
        )

    def cancel_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/transfers/{transfer_id}/cancel", headers=headers
        )

    # ---- Booths ----
    def create_booth_location(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/booth-locations", payload, headers
        )

    def list_season_booth_locations(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET",
            f"/cookie-program/seasons/{season_id}/booth-locations",
            headers=headers,
            params=params,
        )

    def get_booth_location(self, location_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cookie-program/booth-locations/{location_id}", headers=headers
        )

    def list_booth_locations(self, headers: Dict[str, str], params=None):
        return self._request(
            "GET", "/cookie-program/booth-locations", headers=headers, params=params
        )

    def create_booth_slot(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/cookie-program/booth-slots", payload, headers)

    def list_location_slots(self, location_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET",
            f"/cookie-program/booth-locations/{location_id}/slots",
            headers=headers,
            params=params,
        )

    def get_booth_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/booth-slots/{slot_id}", headers=headers)

    def list_booth_slots(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/booth-slots", headers=headers, params=params)

    def create_booth_request(self, slot_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/booth-slots/{slot_id}/requests", payload, headers
        )

    def list_slot_requests(self, slot_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET",
            f"/cookie-program/booth-slots/{slot_id}/requests",
            headers=headers,
            params=params,
        )

    def get_booth_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cookie-program/booth-requests/{request_id}", headers=headers
        )

    def list_booth_requests(self, headers: Dict[str, str], params=None):
        return self._request(
            "GET", "/cookie-program/booth-requests", headers=headers, params=params
        )

    def draw_lottery(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/booth-slots/{slot_id}/draw-lottery", headers=headers
        )

    def approve_booth_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/booth-requests/{request_id}/approve", headers=headers
        )

    def deny_booth_request(self, request_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/booth-requests/{request_id}/deny", payload, headers
        )

    def cancel_booth_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/booth-requests/{request_id}/cancel", headers=headers
        )

    # ---- Digital orders ----
    def create_digital_order(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/digital-orders", payload, headers
        )

    def get_digital_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/digital-orders/{order_id}", headers=headers)

    def list_digital_orders(self, headers: Dict[str, str], params=None):
        return self._request(
            "GET", "/cookie-program/digital-orders", headers=headers, params=params
        )

    def record_payment(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/digital-orders/{order_id}/record-payment", headers=headers
        )

    def mark_uncollected(self, order_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/digital-orders/{order_id}/mark-uncollected",
            payload,
            headers,
        )

    def mark_delivered(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/digital-orders/{order_id}/mark-delivered", headers=headers
        )

    def refund_digital_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/digital-orders/{order_id}/refund", headers=headers
        )

    def cancel_digital_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/digital-orders/{order_id}/cancel", headers=headers
        )

    # ---- Participant agreements ----
    def create_agreement(self, troop_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/troops/{troop_id}/agreements", payload, headers
        )

    def list_troop_agreements(self, troop_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/troops/{troop_id}/agreements", headers=headers, params=params
        )

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/agreements", headers=headers, params=params)

    def settle_agreement(self, agreement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/agreements/{agreement_id}/settle", payload, headers
        )

    def dispute_agreement(self, agreement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/agreements/{agreement_id}/dispute", payload, headers
        )

    def resolve_dispute(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/agreements/{agreement_id}/resolve-dispute", headers=headers
        )

    def forfeit_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/agreements/{agreement_id}/forfeit", headers=headers
        )

    # ---- Recalls ----
    def create_recall(self, season_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cookie-program/seasons/{season_id}/recalls", payload, headers
        )

    def list_season_recalls(self, season_id: str, headers: Dict[str, str], params=None):
        return self._request(
            "GET", f"/cookie-program/seasons/{season_id}/recalls", headers=headers, params=params
        )

    def get_recall(self, recall_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cookie-program/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers: Dict[str, str], params=None):
        return self._request("GET", "/cookie-program/recalls", headers=headers, params=params)

    def activate_recall(self, season_id: str, recall_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/seasons/{season_id}/recalls/{recall_id}/activate",
            headers=headers,
        )

    def lift_recall(self, season_id: str, recall_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cookie-program/seasons/{season_id}/recalls/{recall_id}/lift",
            headers=headers,
        )

    # ---- Test-driving clock ----
    def set_clock(self, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", "/cookie-program/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
