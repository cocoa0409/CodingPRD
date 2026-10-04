"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- SupplyCenter ---
    def create_supply_center(self, payload, headers):
        return self._request("POST", "/supply-centers", payload, headers)

    def get_supply_center(self, center_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}", headers=headers)

    def activate_supply_center(self, center_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/activate", headers=headers)

    def suspend_supply_center(self, center_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/suspend", payload, headers)

    def decommission_supply_center(self, center_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/decommission", headers=headers)

    def run_ops(self, center_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/run_ops", headers=headers)

    # --- Store ---
    def create_store(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores", payload, headers)

    def get_store(self, center_id, store_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/stores/{store_id}", headers=headers)

    def list_stores(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/stores", headers=headers, params=params)

    def activate_store(self, center_id, store_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/activate", headers=headers)

    def suspend_store(self, center_id, store_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/suspend", payload, headers)

    def terminate_store(self, center_id, store_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/terminate", headers=headers)

    # --- Product ---
    def create_product(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/products", payload, headers)

    def get_product(self, center_id, product_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/products/{product_id}", headers=headers)

    def list_products(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/products", headers=headers, params=params)

    def discontinue_product(self, center_id, product_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/products/{product_id}/discontinue", headers=headers)

    def recall_product(self, center_id, product_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/products/{product_id}/recall", payload, headers)

    # --- PriceBook ---
    def create_price_book(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/price-books", payload, headers)

    def get_price_book(self, center_id, price_book_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/price-books/{price_book_id}", headers=headers)

    def list_price_books(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/price-books", headers=headers, params=params)

    # --- DeliveryRoute ---
    def create_route(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/routes", payload, headers)

    def get_route(self, center_id, route_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/routes/{route_id}", headers=headers)

    def list_routes(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/routes", headers=headers, params=params)

    def dispatch_route(self, center_id, route_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/routes/{route_id}/dispatch", headers=headers)

    def cancel_route(self, center_id, route_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/routes/{route_id}/cancel", payload, headers)

    # --- DeliveryStop ---
    def get_stop(self, center_id, route_id, stop_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/routes/{route_id}/stops/{stop_id}", headers=headers)

    def list_stops(self, center_id, route_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/routes/{route_id}/stops", headers=headers, params=params)

    def arrive_stop(self, center_id, route_id, stop_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/routes/{route_id}/stops/{stop_id}/arrive", headers=headers)

    def complete_stop(self, center_id, route_id, stop_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/routes/{route_id}/stops/{stop_id}/complete", headers=headers)

    def skip_stop(self, center_id, route_id, stop_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/routes/{route_id}/stops/{stop_id}/skip", payload, headers)

    # --- PurchaseOrder ---
    def create_purchase_order(self, center_id, store_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/purchase-orders", payload, headers)

    def get_purchase_order(self, center_id, order_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/purchase-orders/{order_id}", headers=headers)

    def list_purchase_orders(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/purchase-orders", headers=headers, params=params)

    def add_order_line(self, center_id, store_id, order_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/purchase-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, center_id, order_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/purchase-orders/{order_id}/lines", headers=headers, params=params)

    def submit_purchase_order(self, center_id, store_id, order_id, expected_store_version, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/purchase-orders/{order_id}/submit",
                             {"expected_store_version": expected_store_version}, headers)

    def confirm_purchase_order(self, center_id, order_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/confirm", headers=headers)

    def load_purchase_order(self, center_id, order_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/load", headers=headers)

    def deliver_purchase_order(self, center_id, order_id, actual_usage_cents, headers):
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/deliver",
                             {"actual_usage_cents": actual_usage_cents}, headers)

    def settle_purchase_order(self, center_id, order_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/settle", headers=headers)

    def cancel_purchase_order(self, center_id, store_id, order_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/purchase-orders/{order_id}/cancel", payload, headers)

    def reject_purchase_order(self, center_id, order_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/reject", payload, headers)

    def mark_line_shorted(self, center_id, order_id, line_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/purchase-orders/{order_id}/lines/{line_id}/mark-shorted", headers=headers)

    # --- PromotionEvent ---
    def create_promotion(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/promotions", payload, headers)

    def get_promotion(self, center_id, promotion_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/promotions", headers=headers, params=params)

    def confirm_promotion(self, center_id, promotion_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/promotions/{promotion_id}/confirm", headers=headers)

    def close_promotion(self, center_id, promotion_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/promotions/{promotion_id}/close", headers=headers)

    def cancel_promotion(self, center_id, promotion_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/promotions/{promotion_id}/cancel", payload, headers)

    # --- RebatePool ---
    def create_rebate_pool(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/rebate-pools", payload, headers)

    def get_rebate_pool(self, center_id, pool_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/rebate-pools/{pool_id}", headers=headers)

    def list_rebate_pools(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/rebate-pools", headers=headers, params=params)

    def calculate_rebate_pool(self, center_id, pool_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/rebate-pools/{pool_id}/calculate", headers=headers)

    def settle_rebate_pool(self, center_id, pool_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/rebate-pools/{pool_id}/settle", headers=headers)

    # --- RebateLedger ---
    def get_rebate_ledger(self, center_id, ledger_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/rebate-ledgers/{ledger_id}", headers=headers)

    def list_rebate_ledgers(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/rebate-ledgers", headers=headers, params=params)

    def void_rebate_ledger(self, center_id, ledger_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/supply-centers/{center_id}/rebate-ledgers/{ledger_id}/void", payload, headers)

    # --- ComplianceAgreement ---
    def create_compliance_agreement(self, center_id, store_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/compliance-agreements", payload, headers)

    def get_compliance_agreement(self, center_id, agreement_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/compliance-agreements/{agreement_id}", headers=headers)

    def list_compliance_agreements(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/compliance-agreements", headers=headers, params=params)

    def activate_compliance_agreement(self, center_id, store_id, agreement_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/compliance-agreements/{agreement_id}/activate", headers=headers)

    def cure_compliance_agreement(self, center_id, store_id, agreement_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/compliance-agreements/{agreement_id}/cure", headers=headers)

    def terminate_compliance_agreement(self, center_id, store_id, agreement_id, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/compliance-agreements/{agreement_id}/terminate", headers=headers)

    # --- CapacityPlan ---
    def create_capacity_plan(self, center_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/capacity-plans", payload, headers)

    def get_capacity_plan(self, center_id, plan_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/capacity-plans/{plan_id}", headers=headers)

    def list_capacity_plans(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/capacity-plans", headers=headers, params=params)

    def lock_capacity_plan(self, center_id, plan_id, expected_center_version, headers):
        return self._request("POST", f"/supply-centers/{center_id}/capacity-plans/{plan_id}/lock",
                             {"expected_center_version": expected_center_version}, headers)

    # --- FoodCostVariance ---
    def get_food_cost_variance(self, center_id, store_id, variance_id, headers):
        return self._request("GET", f"/supply-centers/{center_id}/stores/{store_id}/food-cost-variances/{variance_id}", headers=headers)

    def list_food_cost_variances(self, center_id, headers, params=None):
        return self._request("GET", f"/supply-centers/{center_id}/food-cost-variances", headers=headers, params=params)

    def create_food_cost_variance(self, center_id, store_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/food-cost-variances", payload, headers)

    # --- Compliance report ---
    def submit_compliance_report(self, center_id, store_id, payload, headers):
        return self._request("POST", f"/supply-centers/{center_id}/stores/{store_id}/compliance-reports", payload, headers)


api_client = ApiClient()
