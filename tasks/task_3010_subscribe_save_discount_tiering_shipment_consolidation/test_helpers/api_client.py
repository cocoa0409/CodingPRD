"""API client: one method per endpoint defined in the PRD (mounted under /sns)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/sns/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/sns/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/sns/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/sns/customers/{customer_id}", payload, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/sns/customers/{customer_id}/suspend", {}, headers)

    def unsuspend_customer(self, customer_id, headers):
        return self._request("POST", f"/sns/customers/{customer_id}/unsuspend", {}, headers)

    def list_customer_subscriptions(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/sns/customers/{customer_id}/subscriptions",
            headers=headers, params=params,
        )

    def list_customer_plans(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/sns/customers/{customer_id}/delivery-plans",
            headers=headers, params=params,
        )

    def list_customer_notifications(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/sns/customers/{customer_id}/notifications",
            headers=headers, params=params,
        )

    def list_customer_damage_claims(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/sns/customers/{customer_id}/damage-claims",
            headers=headers, params=params,
        )

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/sns/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/sns/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/sns/products", headers=headers, params=params)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/sns/products/{product_id}", payload, headers)

    def create_price_event(self, product_id, payload, headers):
        return self._request(
            "POST", f"/sns/products/{product_id}/price-events", payload, headers,
        )

    def list_price_events(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/sns/products/{product_id}/price-events",
            headers=headers, params=params,
        )

    def list_product_subscriptions(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/sns/products/{product_id}/subscriptions",
            headers=headers, params=params,
        )

    # --- inventory placements ---
    def create_inventory_placement(self, payload, headers):
        return self._request("POST", "/sns/inventory-placements", payload, headers)

    def get_inventory_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/sns/inventory-placements/{placement_id}", headers=headers,
        )

    def list_inventory_placements(self, headers, params=None):
        return self._request(
            "GET", "/sns/inventory-placements", headers=headers, params=params,
        )

    def receive_inventory(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/sns/inventory-placements/{placement_id}/receive",
            payload, headers,
        )

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/sns/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/sns/subscriptions/{subscription_id}", headers=headers,
        )

    def patch_subscription(self, subscription_id, payload, headers):
        return self._request(
            "PATCH", f"/sns/subscriptions/{subscription_id}", payload, headers,
        )

    def pause_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/sns/subscriptions/{subscription_id}/pause", {}, headers,
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/sns/subscriptions/{subscription_id}/resume", {}, headers,
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/sns/subscriptions/{subscription_id}/cancel", {}, headers,
        )

    def list_subscription_offers(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/sns/subscriptions/{subscription_id}/retention-offers",
            headers=headers, params=params,
        )

    # --- retention offers ---
    def get_retention_offer(self, offer_id, headers):
        return self._request(
            "GET", f"/sns/retention-offers/{offer_id}", headers=headers,
        )

    def accept_retention_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/sns/retention-offers/{offer_id}/accept", {}, headers,
        )

    def decline_retention_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/sns/retention-offers/{offer_id}/decline", {}, headers,
        )

    # --- coupons ---
    def create_coupon(self, payload, headers):
        return self._request("POST", "/sns/coupons", payload, headers)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/sns/coupons/{coupon_id}", headers=headers)

    def disable_coupon(self, coupon_id, headers):
        return self._request("POST", f"/sns/coupons/{coupon_id}/disable", {}, headers)

    # --- promotions ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/sns/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/sns/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/sns/promotions", headers=headers, params=params)

    def disable_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/sns/promotions/{promotion_id}/disable", {}, headers,
        )

    # --- ops ---
    def generate_plans(self, payload, headers):
        return self._request("POST", "/sns/ops/generate-plans", payload, headers)

    def recompute_forecasts(self, payload, headers):
        return self._request("POST", "/sns/ops/recompute-forecasts", payload, headers)

    # --- demand forecasts ---
    def list_demand_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/sns/demand-forecasts", headers=headers, params=params,
        )

    def get_demand_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/sns/demand-forecasts/{forecast_id}", headers=headers,
        )

    # --- delivery plans ---
    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/sns/delivery-plans/{plan_id}", headers=headers)

    def list_plan_lines(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/sns/delivery-plans/{plan_id}/lines",
            headers=headers, params=params,
        )

    def refresh_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/refresh", payload, headers,
        )

    def lock_plan(self, plan_id, headers):
        return self._request("POST", f"/sns/delivery-plans/{plan_id}/lock", {}, headers)

    def ship_plan(self, plan_id, headers):
        return self._request("POST", f"/sns/delivery-plans/{plan_id}/ship", {}, headers)

    def mark_plan_delivered(self, plan_id, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/mark-delivered", {}, headers,
        )

    def resolve_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/resolve", {}, headers,
        )

    def cancel_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/cancel", {}, headers,
        )

    def skip_line(self, plan_id, line_id, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/lines/{line_id}/skip", {}, headers,
        )

    def unskip_line(self, plan_id, line_id, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/lines/{line_id}/unskip", {}, headers,
        )

    def attach_coupon(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/coupons", payload, headers,
        )

    def create_damage_claim(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/sns/delivery-plans/{plan_id}/damage-claims", payload, headers,
        )

    def list_plan_damage_claims(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/sns/delivery-plans/{plan_id}/damage-claims",
            headers=headers, params=params,
        )

    # --- plan lines ---
    def get_plan_line(self, line_id, headers):
        return self._request("GET", f"/sns/plan-lines/{line_id}", headers=headers)

    def list_plan_lines_global(self, headers, params=None):
        return self._request("GET", "/sns/plan-lines", headers=headers, params=params)

    # --- damage claims ---
    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/sns/damage-claims/{claim_id}", headers=headers)

    def review_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/sns/damage-claims/{claim_id}/review", payload, headers,
        )

    def list_claim_reshipments(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/sns/damage-claims/{claim_id}/reshipments",
            headers=headers, params=params,
        )

    # --- reshipments ---
    def get_reshipment(self, reshipment_id, headers):
        return self._request("GET", f"/sns/reshipments/{reshipment_id}", headers=headers)

    def dispatch_reshipment(self, reshipment_id, headers):
        return self._request(
            "POST", f"/sns/reshipments/{reshipment_id}/dispatch", {}, headers,
        )

    def mark_reshipment_delivered(self, reshipment_id, headers):
        return self._request(
            "POST", f"/sns/reshipments/{reshipment_id}/mark-delivered", {}, headers,
        )


api_client = ApiClient()
