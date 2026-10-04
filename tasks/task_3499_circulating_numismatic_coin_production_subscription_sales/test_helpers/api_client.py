"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

Path routing (PRD §2.4): all business resources live under the `/mint` prefix;
the clock operation `POST /_clock/set_current_utc` is platform-level and sits
OUTSIDE that prefix. This client therefore auto-prefixes every path with
`/mint` EXCEPT paths beginning with `/_`, which go to the bare host.
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import MINT_API_PREFIX


class ApiClient(GenericApiClient):
    """PRD-specific client over GenericApiClient."""

    def _request(self, method, path, payload=None, headers=None, params=None):
        """Route `/_...` paths to the bare host; prefix all others with /mint."""
        if not path.startswith("/_"):
            path = f"{MINT_API_PREFIX}{path}"
        return super()._request(method, path, payload=payload, headers=headers, params=params)

    # --- Platform clock (PRD §2.4; OUTSIDE /mint) -----------------------------
    def set_clock(self, payload, headers):
        """POST /_clock/set_current_utc — body: to_iso8601 (required), spot_prices? (200)."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Denominations (PRD §3.1) ---------------------------------------------
    def create_denomination(self, payload, headers):
        """POST /mint/denominations (201)."""
        return self._request("POST", "/denominations", payload, headers)

    # --- Federal Reserve orders (PRD §3.1) --------------------------------------
    def create_fed_order(self, payload, headers):
        """POST /mint/federal-reserve-orders (201)."""
        return self._request("POST", "/federal-reserve-orders", payload, headers)

    def get_fed_order(self, order_id, headers):
        """GET /mint/federal-reserve-orders/{id} (200)."""
        return self._request("GET", f"/federal-reserve-orders/{order_id}", headers=headers)

    def cancel_fed_order(self, order_id, headers):
        """POST /mint/federal-reserve-orders/{id}/cancel (200)."""
        return self._request("POST", f"/federal-reserve-orders/{order_id}/cancel", headers=headers)

    # --- Metal procurement lots (PRD §3.2) --------------------------------------
    def create_metal_lot(self, payload, headers):
        """POST /mint/metal-procurement-lots (201)."""
        return self._request("POST", "/metal-procurement-lots", payload, headers)

    def get_metal_lot(self, lot_id, headers):
        """GET /mint/metal-procurement-lots/{id} (200)."""
        return self._request("GET", f"/metal-procurement-lots/{lot_id}", headers=headers)

    def receive_metal_lot(self, lot_id, headers):
        """POST /mint/metal-procurement-lots/{id}/receive (200)."""
        return self._request("POST", f"/metal-procurement-lots/{lot_id}/receive", headers=headers)

    # --- Production runs (PRD §3.3) ---------------------------------------------
    def create_production_run(self, payload, headers):
        """POST /mint/production-runs (201)."""
        return self._request("POST", "/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        """GET /mint/production-runs (200)."""
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        """GET /mint/production-runs/{id} (200)."""
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def start_production_run(self, run_id, headers):
        """POST /mint/production-runs/{id}/start (200)."""
        return self._request("POST", f"/production-runs/{run_id}/start", headers=headers)

    def inspect_production_run(self, run_id, payload, headers):
        """POST /mint/production-runs/{id}/inspect (200); payload: outcome, good_pieces?."""
        return self._request("POST", f"/production-runs/{run_id}/inspect", payload, headers)

    def cancel_production_run(self, run_id, headers):
        """POST /mint/production-runs/{id}/cancel (200)."""
        return self._request("POST", f"/production-runs/{run_id}/cancel", headers=headers)

    # --- Commemorative programs (PRD §3.5) ---------------------------------------
    def create_program(self, payload, headers):
        """POST /mint/commemorative-programs (201)."""
        return self._request("POST", "/commemorative-programs", payload, headers)

    def get_program(self, program_id, headers):
        """GET /mint/commemorative-programs/{id} (200)."""
        return self._request("GET", f"/commemorative-programs/{program_id}", headers=headers)

    def decide_design(self, program_id, payload, headers):
        """POST /mint/commemorative-programs/{id}/decide-design (200); payload: decision."""
        return self._request("POST", f"/commemorative-programs/{program_id}/decide-design", payload, headers)

    def disburse_surcharges(self, program_id, headers):
        """POST /mint/commemorative-programs/{id}/disburse-surcharges (200)."""
        return self._request("POST", f"/commemorative-programs/{program_id}/disburse-surcharges", headers=headers)

    # --- Products (PRD §3.6) ------------------------------------------------------
    def create_product(self, payload, headers):
        """POST /mint/products (201)."""
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        """GET /mint/products (200)."""
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        """GET /mint/products/{id} (200)."""
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def withdraw_product(self, product_id, headers):
        """POST /mint/products/{id}/withdraw (200)."""
        return self._request("POST", f"/products/{product_id}/withdraw", headers=headers)

    # --- Collectors (PRD §3.6) ----------------------------------------------------
    def create_collector(self, payload, headers):
        """POST /mint/collectors (201; Anonymous)."""
        return self._request("POST", "/collectors", payload, headers)

    # --- Orders (PRD §3.6) ----------------------------------------------------------
    def create_order(self, payload, headers):
        """POST /mint/orders (201; collector_id taken from X-User-ID)."""
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        """GET /mint/orders (200)."""
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        """GET /mint/orders/{id} (200)."""
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def pay_order(self, order_id, payload, headers):
        """POST /mint/orders/{id}/pay (200); payload: amount_cents."""
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def cancel_order(self, order_id, headers):
        """POST /mint/orders/{id}/cancel (200)."""
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # --- Subscriptions and invoices (PRD §3.7) -------------------------------------
    def create_subscription(self, payload, headers):
        """POST /mint/subscriptions (201; collector_id taken from X-User-ID)."""
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        """GET /mint/subscriptions (200)."""
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        """GET /mint/subscriptions/{id} (200)."""
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        """POST /mint/subscriptions/{id}/cancel (200)."""
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    def run_billing_cycle(self, subscription_id, payload, headers):
        """POST /mint/subscriptions/{id}/billing-cycle (201 — creates the invoice);
        payload: expected_subscription_version (OCC, PRD §2.6)."""
        return self._request("POST", f"/subscriptions/{subscription_id}/billing-cycle", payload, headers)

    def list_subscription_invoices(self, subscription_id, headers, params=None):
        """GET /mint/subscriptions/{id}/invoices (200)."""
        return self._request("GET", f"/subscriptions/{subscription_id}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        """POST /mint/subscription-invoices/{id}/pay (200); payload: outcome."""
        return self._request("POST", f"/subscription-invoices/{invoice_id}/pay", payload, headers)

    # --- Bullion issues, purchasers, allocations (PRD §3.8) ------------------------
    def create_bullion_issue(self, payload, headers):
        """POST /mint/bullion-issues (201)."""
        return self._request("POST", "/bullion-issues", payload, headers)

    def get_bullion_issue(self, issue_id, headers):
        """GET /mint/bullion-issues/{id} (200)."""
        return self._request("GET", f"/bullion-issues/{issue_id}", headers=headers)

    def create_authorized_purchaser(self, payload, headers):
        """POST /mint/authorized-purchasers (201)."""
        return self._request("POST", "/authorized-purchasers", payload, headers)

    def set_authorized_purchaser_status(self, ap_id, payload, headers):
        """POST /mint/authorized-purchasers/{id}/set-status (200); payload: to_status."""
        return self._request("POST", f"/authorized-purchasers/{ap_id}/set-status", payload, headers)

    def create_allocation(self, issue_id, payload, headers):
        """POST /mint/bullion-issues/{id}/allocations (201); payload carries
        authorized_purchaser_id, quantity_units, expected_bullion_issue_version (OCC)."""
        return self._request("POST", f"/bullion-issues/{issue_id}/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        """GET /mint/allocations (200)."""
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        """GET /mint/allocations/{id} (200)."""
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def confirm_allocation(self, allocation_id, headers):
        """POST /mint/allocations/{id}/confirm (200; BullionDealer, own allocations only)."""
        return self._request("POST", f"/allocations/{allocation_id}/confirm", headers=headers)

    def settle_allocation(self, allocation_id, headers):
        """POST /mint/allocations/{id}/settle (200; FinanceOfficer, SoD vs offerer)."""
        return self._request("POST", f"/allocations/{allocation_id}/settle", headers=headers)

    # --- Error coin cases (PRD §3.4) -------------------------------------------------
    def create_error_coin_case(self, payload, headers):
        """POST /mint/error-coin-cases (201)."""
        return self._request("POST", "/error-coin-cases", payload, headers)

    def list_error_coin_cases(self, run_id, headers, params=None):
        """GET /mint/production-runs/{id}/error-coin-cases (200)."""
        return self._request("GET", f"/production-runs/{run_id}/error-coin-cases", headers=headers, params=params)

    def destroy_error_coin_case(self, case_id, payload, headers):
        """POST /mint/error-coin-cases/{id}/destroy (200); payload: primary/secondary certifier ids."""
        return self._request("POST", f"/error-coin-cases/{case_id}/destroy", payload, headers)

    # --- Computed reports (PRD §2.9) ---------------------------------------------------
    def get_report(self, report_type, headers, params=None):
        """GET /mint/reports/{report_type} (200); report_type e.g. seigniorage | metal-exposure."""
        return self._request("GET", f"/reports/{report_type}", headers=headers, params=params)


api_client = ApiClient()
