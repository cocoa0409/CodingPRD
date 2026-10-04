"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- items ---
    def create_item(self, payload: Dict, headers: Dict):
        return self._request("POST", "/items", payload, headers)

    def list_items(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/items", headers=headers, params=params)

    def get_item(self, item_id: str, headers: Dict):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def activate_item(self, item_id: str, headers: Dict):
        return self._request("POST", f"/items/{item_id}/activate", {}, headers)

    def reprice_item(self, item_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/items/{item_id}/reprice", payload, headers)

    def discontinue_item(self, item_id: str, headers: Dict):
        return self._request("POST", f"/items/{item_id}/discontinue", {}, headers)

    # --- purchase orders ---
    def create_purchase_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id: str, headers: Dict):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def issue_purchase_order(self, po_id: str, headers: Dict):
        return self._request("POST", f"/purchase-orders/{po_id}/issue", {}, headers)

    def cancel_purchase_order(self, po_id: str, headers: Dict):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", {}, headers)

    # --- containers ---
    def create_container(self, payload: Dict, headers: Dict):
        return self._request("POST", "/containers", payload, headers)

    def list_containers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/containers", headers=headers, params=params)

    def get_container(self, container_id: str, headers: Dict):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def depart_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/depart", {}, headers)

    def arrive_port_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/arrive-port", {}, headers)

    def hold_customs_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/hold-customs", {}, headers)

    def release_customs_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/release-customs", {}, headers)

    def clear_customs_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/clear-customs", {}, headers)

    def receive_container(self, container_id: str, payload: Optional[Dict], headers: Dict):
        return self._request("POST", f"/containers/{container_id}/receive", payload or {}, headers)

    def cancel_container(self, container_id: str, headers: Dict):
        return self._request("POST", f"/containers/{container_id}/cancel", {}, headers)

    # --- stores ---
    def create_store(self, payload: Dict, headers: Dict):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id: str, headers: Dict):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # --- store allocations ---
    def create_store_allocation(self, store_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/stores/{store_id}/allocations", payload, headers)

    def list_store_allocations(self, store_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/stores/{store_id}/allocations", headers=headers, params=params)

    def list_allocations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/store-allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id: str, headers: Dict):
        return self._request("GET", f"/store-allocations/{allocation_id}", headers=headers)

    def commit_allocation(self, allocation_id: str, expected_container_version: int, headers: Dict):
        return self._request("POST", f"/store-allocations/{allocation_id}/commit",
                             {"expected_container_version": expected_container_version}, headers)

    def decommit_allocation(self, allocation_id: str, headers: Dict):
        return self._request("POST", f"/store-allocations/{allocation_id}/decommit", {}, headers)

    def release_allocation(self, allocation_id: str, headers: Dict):
        return self._request("POST", f"/store-allocations/{allocation_id}/release", {}, headers)

    # --- customers & membership ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_membership(self, customer_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/customers/{customer_id}/membership", payload, headers)

    def get_customer_membership(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/customers/{customer_id}/membership", headers=headers)

    def get_membership(self, membership_id: str, headers: Dict):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def renew_membership(self, membership_id: str, headers: Dict):
        return self._request("POST", f"/memberships/{membership_id}/renew", {}, headers)

    def cancel_membership(self, membership_id: str, headers: Dict):
        return self._request("POST", f"/memberships/{membershipId}/cancel".format(membershipId=membership_id), {}, headers)

    # --- coupons ---
    def create_coupon(self, payload: Dict, headers: Dict):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id: str, headers: Dict):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def activate_coupon(self, coupon_id: str, headers: Dict):
        return self._request("POST", f"/coupons/{coupon_id}/activate", {}, headers)

    def pause_coupon(self, coupon_id: str, headers: Dict):
        return self._request("POST", f"/coupons/{coupon_id}/pause", {}, headers)

    # --- sales ---
    def create_sale(self, payload: Dict, headers: Dict):
        return self._request("POST", "/sales", payload, headers)

    def get_sale(self, sale_id: str, headers: Dict):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def add_sale_line(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/sales/{sale_id}/lines", payload, headers)

    def list_sale_lines(self, sale_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/sales/{sale_id}/lines", headers=headers, params=params)

    def get_sale_line(self, line_id: str, headers: Dict):
        return self._request("GET", f"/sale-lines/{line_id}", headers=headers)

    def list_all_sale_lines(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/sale-lines", headers=headers, params=params)

    def apply_coupon(self, sale_id: str, coupon_code: str, headers: Dict):
        return self._request("POST", f"/sales/{sale_id}/apply-coupon",
                             {"coupon_code": coupon_code}, headers)

    def complete_sale(self, sale_id: str, payload: Optional[Dict], headers: Dict):
        return self._request("POST", f"/sales/{sale_id}/complete", payload or {}, headers)

    def void_sale(self, sale_id: str, headers: Dict):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers)

    def return_sale(self, sale_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/sales/{sale_id}/returns", payload, headers)

    # --- warranty claims ---
    def create_warranty_claim(self, payload: Dict, headers: Dict):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id: str, headers: Dict):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def start_review_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/warranty-claims/{claim_id}/start-review", {}, headers)

    def approve_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", {}, headers)

    def appeal_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/warranty-claims/{claim_id}/appeal", {}, headers)

    def settle_claim(self, claim_id: str, settled_amount_cents: int, headers: Dict):
        return self._request("POST", f"/warranty-claims/{claim_id}/settle",
                             {"settled_amount_cents": settled_amount_cents}, headers)

    # --- recalls ---
    def create_recall(self, payload: Dict, headers: Dict):
        return self._request("POST", "/recalls", payload, headers)

    def list_recalls(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def get_recall(self, recall_id: str, headers: Dict):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def activate_recall(self, recall_id: str, headers: Dict):
        return self._request("POST", f"/recalls/{recall_id}/activate", {}, headers)

    def close_recall(self, recall_id: str, headers: Dict):
        return self._request("POST", f"/recalls/{recall_id}/close", {}, headers)


api_client = ApiClient()
