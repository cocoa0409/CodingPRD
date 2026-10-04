"""API client: one method per endpoint defined in the PRD (Section 4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock and catalogue -------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/retail/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def create_product(self, payload, headers):
        return self._request("POST", "/retail/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/retail/products", params, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/retail/products/{product_id}", headers=headers)

    # --- franchisees and routes ---------------------------------------------
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/retail/franchisees", payload, headers)

    def list_franchisees(self, headers, params=None):
        return self._request("GET", "/retail/franchisees", params, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request("GET", f"/retail/franchisees/{franchisee_id}", headers=headers)

    def get_draft_summary(self, franchisee_id, headers):
        return self._request("GET", f"/retail/franchisees/{franchisee_id}/draft-summary",
                             headers=headers)

    def advance_training(self, franchisee_id, payload, headers):
        return self._request("POST", f"/retail/franchisees/{franchisee_id}/training",
                             payload, headers)

    def create_route(self, franchisee_id, payload, headers):
        return self._request("POST", f"/retail/franchisees/{franchisee_id}/routes",
                             payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/retail/routes", params, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/retail/routes/{route_id}", headers=headers)

    def update_route(self, route_id, payload, headers):
        return self._request("PUT", f"/retail/routes/{route_id}", payload, headers)

    def advance_route_status(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/status", payload, headers)

    def advance_territory(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/territory", payload, headers)

    def resale_action(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/resale", payload, headers)

    # --- shops and technicians ----------------------------------------------
    def create_shop(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/shop-locations",
                             payload, headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/retail/shop-locations", params, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/retail/shop-locations/{shop_id}", headers=headers)

    def update_shop(self, shop_id, payload, headers):
        return self._request("PUT", f"/retail/shop-locations/{shop_id}", payload, headers)

    def list_shop_technicians(self, shop_id, headers, params=None):
        return self._request("GET", f"/retail/shop-locations/{shop_id}/technicians",
                             params, headers)

    def create_technician(self, payload, headers):
        return self._request("POST", "/retail/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/retail/technicians", params, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/retail/technicians/{technician_id}", headers=headers)

    def update_technician(self, technician_id, payload, headers):
        return self._request("PUT", f"/retail/technicians/{technician_id}", payload, headers)

    def advance_technician_status(self, technician_id, payload, headers):
        return self._request("POST", f"/retail/technicians/{technician_id}/status",
                             payload, headers)

    # --- credit applications and accounts -----------------------------------
    def file_credit_application(self, shop_id, payload, headers):
        return self._request("POST", f"/retail/shop-locations/{shop_id}/credit-applications",
                             payload, headers)

    def list_credit_applications(self, headers, params=None):
        return self._request("GET", "/retail/credit-applications", params, headers)

    def get_credit_application(self, application_id, headers):
        return self._request("GET", f"/retail/credit-applications/{application_id}",
                             headers=headers)

    def advance_application(self, application_id, payload, headers):
        return self._request("POST", f"/retail/credit-applications/{application_id}/status",
                             payload, headers)

    def mint_credit_account(self, application_id, payload, headers):
        return self._request("POST", f"/retail/credit-applications/{application_id}/accounts",
                             payload, headers)

    def list_credit_accounts(self, headers, params=None):
        return self._request("GET", "/retail/credit-accounts", params, headers)

    def get_credit_account(self, account_id, headers):
        return self._request("GET", f"/retail/credit-accounts/{account_id}", headers=headers)

    def advance_account_status(self, account_id, payload, headers):
        return self._request("POST", f"/retail/credit-accounts/{account_id}/status",
                             payload, headers)

    def book_payment(self, account_id, payload, headers):
        return self._request("POST", f"/retail/credit-accounts/{account_id}/payments",
                             payload, headers)

    def list_payments(self, account_id, headers, params=None):
        return self._request("GET", f"/retail/credit-accounts/{account_id}/payments",
                             params, headers)

    def list_finance_charges(self, account_id, headers, params=None):
        return self._request("GET", f"/retail/credit-accounts/{account_id}/finance-charges",
                             params, headers)

    def advance_payment(self, account_id, payment_id, payload, headers):
        return self._request(
            "POST", f"/retail/credit-accounts/{account_id}/payments/{payment_id}/status",
            payload, headers)

    def list_account_pledges(self, account_id, headers, params=None):
        return self._request("GET", f"/retail/credit-accounts/{account_id}/pledges",
                             params, headers)

    # --- sales orders and warranty claims -----------------------------------
    def create_sales_order(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/sales-orders",
                             payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/retail/sales-orders", params, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/retail/sales-orders/{order_id}", headers=headers)

    def edit_sales_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/retail/sales-orders/{order_id}", payload, headers)

    def advance_sales_order(self, order_id, payload, headers):
        return self._request("POST", f"/retail/sales-orders/{order_id}/status",
                             payload, headers)

    def file_warranty_claim(self, order_id, payload, headers):
        return self._request("POST", f"/retail/sales-orders/{order_id}/warranty-claims",
                             payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/retail/warranty-claims", params, headers)

    def advance_warranty_claim(self, order_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/retail/sales-orders/{order_id}/warranty-claims/{claim_id}/status",
            payload, headers)

    # --- inventory and replenishment ----------------------------------------
    def write_inventory_position(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/inventory-positions",
                             payload, headers)

    def list_inventory_positions(self, headers, params=None):
        return self._request("GET", "/retail/inventory-positions", params, headers)

    def create_product_order(self, route_id, payload, headers):
        return self._request("POST", f"/retail/routes/{route_id}/product-orders",
                             payload, headers)

    def list_product_orders(self, headers, params=None):
        return self._request("GET", "/retail/product-orders", params, headers)

    def get_product_order(self, product_order_id, headers):
        return self._request("GET", f"/retail/product-orders/{product_order_id}",
                             headers=headers)

    def advance_product_order(self, product_order_id, payload, headers):
        return self._request("POST", f"/retail/product-orders/{product_order_id}/status",
                             payload, headers)

    def file_pledge(self, product_order_id, payload, headers):
        return self._request("POST", f"/retail/product-orders/{product_order_id}/pledges",
                             payload, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/retail/pledges", params, headers)

    def advance_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/retail/pledges/{pledge_id}/status", payload, headers)

    # --- product launches ---------------------------------------------------
    def plan_launch(self, product_id, payload, headers):
        return self._request("POST", f"/retail/products/{product_id}/launch-allocations",
                             payload, headers)

    def list_launch_allocations(self, headers, params=None):
        return self._request("GET", "/retail/launch-allocations", params, headers)

    def reallocate_launch(self, allocation_id, payload, headers):
        return self._request("POST", f"/retail/launch-allocations/{allocation_id}/reallocate",
                             payload, headers)

    def review_launch(self, allocation_id, payload, headers):
        return self._request("POST", f"/retail/launch-allocations/{allocation_id}/review",
                             payload, headers)


api_client = ApiClient()
