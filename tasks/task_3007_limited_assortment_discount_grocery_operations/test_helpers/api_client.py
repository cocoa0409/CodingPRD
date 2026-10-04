"""HTTP client for the Limited-Assortment Grocery API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination go through ``params``; request bodies as ``payload``. All business
routes are mounted under the ``/v1`` prefix; the logical clock endpoint sits
outside it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock (outside the /v1 prefix) ─────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Categories ─────────────────────────────────────────────────────────

    def create_category(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/categories", payload, headers)

    def list_categories(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/categories", headers=headers, params=params)

    def get_category(self, category_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/categories/{category_id}", headers=headers)

    def update_category(self, category_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"/v1/categories/{category_id}", payload, headers)

    # ── Suppliers ──────────────────────────────────────────────────────────

    def create_supplier(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/suppliers/{supplier_id}", headers=headers)

    def list_supplier_products(self, supplier_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/suppliers/{supplier_id}/products", headers=headers, params=params)

    def list_supplier_bids(self, supplier_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/suppliers/{supplier_id}/bids", headers=headers, params=params)

    # ── Products ───────────────────────────────────────────────────────────

    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/products", payload, headers)

    def list_products(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/products", headers=headers, params=params)

    def get_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/products/{product_id}/discontinue", headers=headers)

    def reactivate_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/products/{product_id}/reactivate", headers=headers)

    def list_product_tenders(self, product_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/products/{product_id}/tenders", headers=headers, params=params)

    # ── Tenders ────────────────────────────────────────────────────────────

    def create_tender(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/tenders", payload, headers)

    def get_tender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/tenders/{tender_id}", headers=headers)

    def open_tender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/open", headers=headers)

    def close_tender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/close", headers=headers)

    def evaluate_tender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/evaluate", headers=headers)

    def award_tender(self, tender_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/award", payload, headers)

    def retender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/retender", headers=headers)

    def cancel_tender(self, tender_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/cancel", headers=headers)

    # ── Bids ───────────────────────────────────────────────────────────────

    def create_bid(self, tender_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/tenders/{tender_id}/bids", payload, headers)

    def list_tender_bids(self, tender_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/tenders/{tender_id}/bids", headers=headers, params=params)

    def get_bid(self, bid_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/bids/{bid_id}", headers=headers)

    # ── Blind quality panels ───────────────────────────────────────────────

    def create_panel(self, bid_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/bids/{bid_id}/panels", payload, headers)

    def list_panels(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/panels", headers=headers, params=params)

    def get_panel(self, panel_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/panels/{panel_id}", headers=headers)

    def score_panel(self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/panels/{panel_id}/score", payload, headers)

    # ── Stores ─────────────────────────────────────────────────────────────

    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/stores", payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}", headers=headers)

    # ── Employees ──────────────────────────────────────────────────────────

    def create_employee(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/stores/{store_id}/employees", payload, headers)

    def list_employees(self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/employees", headers=headers, params=params)

    def get_employee(self, employee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/employees/{employee_id}", headers=headers)

    # ── Finds buys and allocations ─────────────────────────────────────────

    def create_finds_buy(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/finds-buys", payload, headers)

    def list_finds_buys(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/finds-buys", headers=headers, params=params)

    def get_finds_buy(self, buy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/finds-buys/{buy_id}", headers=headers)

    def plan_allocations(self, buy_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/finds-buys/{buy_id}/allocations", payload, headers)

    def list_buy_allocations(self, buy_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/finds-buys/{buy_id}/allocations", headers=headers, params=params)

    def activate_finds_buy(self, buy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/finds-buys/{buy_id}/activate", headers=headers)

    def close_finds_buy(self, buy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/finds-buys/{buy_id}/close", headers=headers)

    def get_allocation(self, allocation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/allocations/{allocation_id}", headers=headers)

    def sell_allocation(self, allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/allocations/{allocation_id}/sell", payload, headers)

    def clearance_allocation(self, allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/allocations/{allocation_id}/clearance", payload, headers)

    def list_store_allocations(self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/finds-allocations", headers=headers, params=params)

    # ── Cart coin ledger ───────────────────────────────────────────────────

    def create_cart_coin_event(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/stores/{store_id}/cart-coin-events", payload, headers)

    def list_cart_coin_events(self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/cart-coin-events", headers=headers, params=params)

    def get_cart_reconciliation(self, store_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/cart-reconciliation", headers=headers)

    # ── Register shifts ────────────────────────────────────────────────────

    def create_register_shift(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/stores/{store_id}/register-shifts", payload, headers)

    def list_register_shifts(self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/register-shifts", headers=headers, params=params)

    def get_register_shift(self, shift_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/register-shifts/{shift_id}", headers=headers)

    def list_employee_shifts(self, employee_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/employees/{employee_id}/register-shifts", headers=headers, params=params)

    def scan_shift(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/register-shifts/{shift_id}/scan", payload, headers)

    def close_shift(self, shift_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/register-shifts/{shift_id}/close", headers=headers)

    # ── Labor windows ──────────────────────────────────────────────────────

    def create_labor_window(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/stores/{store_id}/labor-windows", payload, headers)

    def list_labor_windows(self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/v1/stores/{store_id}/labor-windows", headers=headers, params=params)

    def get_labor_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/labor-windows/{window_id}", headers=headers)

    def confirm_labor_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/labor-windows/{window_id}/confirm", headers=headers)

    def cancel_labor_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/labor-windows/{window_id}/cancel", headers=headers)

    # ── Quality claims ─────────────────────────────────────────────────────

    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/v1/claims", payload, headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/v1/claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/v1/claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/review", headers=headers)

    def approve_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/approve", headers=headers)

    def reject_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/reject", headers=headers)

    def dispute_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/dispute", headers=headers)

    def pay_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/pay", headers=headers)

    def rescind_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/v1/claims/{claim_id}/rescind", headers=headers)


api_client = ApiClient()
