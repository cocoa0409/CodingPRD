"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over the framework client — one method per catalog operation."""

    def _req(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)

    # --- logical clock -----------------------------------------------------------
    def set_current_utc(self, payload: dict, headers: dict):
        return self._req("POST", "/_clock/set_current_utc", payload, headers)

    # --- distribution centers ----------------------------------------------------
    def create_distribution_center(self, payload: dict, headers: dict):
        return self._req("POST", "/distribution-centers", payload, headers)

    def list_distribution_centers(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/distribution-centers", headers=headers, params=params)

    def get_distribution_center(self, dc_id: str, headers: dict):
        return self._req("GET", f"/distribution-centers/{dc_id}", headers=headers)

    def roll_cutoff(self, dc_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/distribution-centers/{dc_id}/roll_cutoff", payload or {}, headers)

    def reeducate(self, dc_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/distribution-centers/{dc_id}/reeducate", payload, headers)

    def list_dc_order_lines(self, dc_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/distribution-centers/{dc_id}/order-lines", headers=headers, params=params)

    # --- suppliers ---------------------------------------------------------------
    def create_supplier(self, payload: dict, headers: dict):
        return self._req("POST", "/suppliers", payload, headers)

    def list_suppliers(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id: str, headers: dict):
        return self._req("GET", f"/suppliers/{supplier_id}", headers=headers)

    def list_supplier_availability_reports(self, supplier_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/suppliers/{supplier_id}/availability-reports", headers=headers, params=params)

    def create_availability_report(self, supplier_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/suppliers/{supplier_id}/availability-reports", payload, headers)

    # --- catalog items / curation ------------------------------------------------
    def create_item(self, payload: dict, headers: dict):
        return self._req("POST", "/items", payload, headers)

    def list_items(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/items", headers=headers, params=params)

    def get_item(self, item_id: str, headers: dict):
        return self._req("GET", f"/items/{item_id}", headers=headers)

    def list_item_order_lines(self, item_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/items/{item_id}/order-lines", headers=headers, params=params)

    def list_item_availability_reports(self, item_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/items/{item_id}/availability-reports", headers=headers, params=params)

    def create_item_attribute(self, item_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/items/{item_id}/attributes", payload, headers)

    def list_item_attributes(self, item_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/items/{item_id}/attributes", headers=headers, params=params)

    def create_item_cross_reference(self, item_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/items/{item_id}/cross-references", payload, headers)

    def list_item_cross_references(self, item_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/items/{item_id}/cross-references", headers=headers, params=params)

    def create_curation_review(self, payload: dict, headers: dict):
        return self._req("POST", "/curation-reviews", payload, headers)

    def list_curation_reviews(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/curation-reviews", headers=headers, params=params)

    def get_curation_review(self, review_id: str, headers: dict):
        return self._req("GET", f"/curation-reviews/{review_id}", headers=headers)

    def list_curation_review_items(self, review_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/curation-reviews/{review_id}/items", headers=headers, params=params)

    def revoke_curation_review(self, review_id: str, headers: dict):
        return self._req("POST", f"/curation-reviews/{review_id}/revoke", {}, headers)

    def list_item_curation_review_items(self, item_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/items/{item_id}/curation-review-items", headers=headers, params=params)

    # --- stock -------------------------------------------------------------------
    def create_stock(self, payload: dict, headers: dict):
        return self._req("POST", "/stock", payload, headers)

    def list_stock(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/stock", headers=headers, params=params)

    def get_stock(self, stock_id: str, headers: dict):
        return self._req("GET", f"/stock/{stock_id}", headers=headers)

    # --- accounts ----------------------------------------------------------------
    def create_account(self, payload: dict, headers: dict):
        return self._req("POST", "/accounts", payload, headers)

    def list_accounts(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id: str, headers: dict):
        return self._req("GET", f"/accounts/{account_id}", headers=headers)

    # --- orders ------------------------------------------------------------------
    def create_order(self, payload: dict, headers: dict):
        return self._req("POST", "/orders", payload, headers)

    def list_orders(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: dict):
        return self._req("GET", f"/orders/{order_id}", headers=headers)

    def release_order(self, order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/orders/{order_id}/release", payload or {}, headers)

    def allocate_order(self, order_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/orders/{order_id}/allocate", payload, headers)

    def cancel_order(self, order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    def list_order_lines(self, order_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def list_order_lines_across_orders(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/order-lines", headers=headers, params=params)

    def pick_line(self, order_id: str, line_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/orders/{order_id}/lines/{line_id}/pick", payload, headers)

    def complete_pick(self, order_id: str, line_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/orders/{order_id}/lines/{line_id}/pick_complete", payload, headers)

    def confirm_cutoff(self, order_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/orders/{order_id}/confirm_cutoff", payload, headers)

    # --- pick tasks / shipments --------------------------------------------------
    def list_pick_tasks(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/pick-tasks", headers=headers, params=params)

    def get_pick_task(self, task_id: str, headers: dict):
        return self._req("GET", f"/pick-tasks/{task_id}", headers=headers)

    def list_shipments(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id: str, headers: dict):
        return self._req("GET", f"/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/shipments/{shipment_id}/dispatch", payload or {}, headers)

    # --- returns -----------------------------------------------------------------
    def create_return(self, payload: dict, headers: dict):
        return self._req("POST", "/returns", payload, headers)

    def list_returns(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/returns", headers=headers, params=params)

    def get_return(self, return_id: str, headers: dict):
        return self._req("GET", f"/returns/{return_id}", headers=headers)

    def approve_return(self, return_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/returns/{return_id}/approve", payload or {}, headers)

    def receive_return(self, return_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/returns/{return_id}/receive", payload, headers)

    def cancel_return(self, return_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/returns/{return_id}/cancel", payload or {}, headers)

    # --- damage claims -----------------------------------------------------------
    def list_damage_claims(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id: str, headers: dict):
        return self._req("GET", f"/damage-claims/{claim_id}", headers=headers)

    def resume_claim_fulfillment(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/damage-claims/{claim_id}/resume_fulfillment", payload or {}, headers)

    def resolve_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/damage-claims/{claim_id}/resolve", payload or {}, headers)

    def reject_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/damage-claims/{claim_id}/reject", payload or {}, headers)

    def void_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._req("POST", f"/damage-claims/{claim_id}/void", payload or {}, headers)

    # --- square-footage consignments ---------------------------------------------
    def create_square_footage_request(self, payload: dict, headers: dict):
        return self._req("POST", "/square-footage-requests", payload, headers)

    def list_square_footage_requests(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/square-footage-requests", headers=headers, params=params)

    def get_square_footage_request(self, request_id: str, headers: dict):
        return self._req("GET", f"/square-footage-requests/{request_id}", headers=headers)

    def list_square_footage_request_lines(self, request_id: str, headers: dict, params: Optional[dict] = None):
        return self._req("GET", f"/square-footage-requests/{request_id}/lines", headers=headers, params=params)

    def list_square_footage_lines(self, headers: dict, params: Optional[dict] = None):
        return self._req("GET", "/square-footage-lines", headers=headers, params=params)

    def cut_square_footage_request(self, request_id: str, payload: dict, headers: dict):
        return self._req("POST", f"/square-footage-requests/{request_id}/cut", payload, headers)


api_client = ApiClient()