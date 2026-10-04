"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/sleep/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/sleep/stores/{store_id}", headers=headers)

    # --- product models ---
    def create_product_model(self, payload, headers):
        return self._request("POST", "/sleep/product-models", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/sleep/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/sleep/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/sleep/customers", headers=headers, params=params)

    def update_subscription(self, customer_id, payload, headers):
        return self._request("PATCH", f"/sleep/customers/{customer_id}/subscription",
                             payload, headers)

    # --- fit assessments ---
    def create_fit_assessment(self, payload, headers):
        return self._request("POST", "/sleep/fit-assessments", payload, headers)

    def get_fit_assessment(self, assessment_id, headers):
        return self._request("GET", f"/sleep/fit-assessments/{assessment_id}",
                             headers=headers)

    def list_fit_assessments(self, headers, params=None):
        return self._request("GET", "/sleep/fit-assessments", headers=headers,
                             params=params)

    def complete_fit_assessment(self, assessment_id, headers):
        return self._request("POST",
                             f"/sleep/fit-assessments/{assessment_id}/complete",
                             {}, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/sleep/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/sleep/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/sleep/orders", headers=headers, params=params)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/sleep/orders/{order_id}", payload, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/sleep/orders/{order_id}/confirm",
                             payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/sleep/orders/{order_id}/cancel", {}, headers)

    # --- delivery windows ---
    def create_delivery_window(self, payload, headers):
        return self._request("POST", "/sleep/delivery-windows", payload, headers)

    def get_delivery_window(self, window_id, headers):
        return self._request("GET", f"/sleep/delivery-windows/{window_id}",
                             headers=headers)

    def list_delivery_windows(self, headers, params=None):
        return self._request("GET", "/sleep/delivery-windows", headers=headers,
                             params=params)

    # --- delivery visits ---
    def create_delivery_visit(self, payload, headers):
        return self._request("POST", "/sleep/delivery-visits", payload, headers)

    def get_delivery_visit(self, visit_id, headers):
        return self._request("GET", f"/sleep/delivery-visits/{visit_id}",
                             headers=headers)

    def list_delivery_visits(self, headers, params=None):
        return self._request("GET", "/sleep/delivery-visits", headers=headers,
                             params=params)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/sleep/delivery-visits/{visit_id}/reschedule",
                             payload, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/sleep/delivery-visits/{visit_id}/complete",
                             payload, headers)

    # --- devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/sleep/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/sleep/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/sleep/devices", headers=headers, params=params)

    def pair_device(self, device_id, payload, headers):
        return self._request("POST", f"/sleep/devices/{device_id}/pair",
                             payload, headers)

    # --- sleep nights ---
    def ingest_sleep_night(self, device_id, payload, headers):
        return self._request("POST", f"/sleep/devices/{device_id}/sleep-nights",
                             payload, headers)

    def get_sleep_night(self, night_id, headers):
        return self._request("GET", f"/sleep/sleep-nights/{night_id}",
                             headers=headers)

    def list_sleep_nights(self, headers, params=None):
        return self._request("GET", "/sleep/sleep-nights", headers=headers,
                             params=params)

    # --- trial returns ---
    def initiate_trial_return(self, order_id, payload, headers):
        return self._request("POST", f"/sleep/orders/{order_id}/trial-return",
                             payload, headers)

    def get_trial_return(self, return_id, headers):
        return self._request("GET", f"/sleep/trial-returns/{return_id}",
                             headers=headers)

    def list_trial_returns(self, headers, params=None):
        return self._request("GET", "/sleep/trial-returns", headers=headers,
                             params=params)

    def inspect_trial_return(self, return_id, payload, headers):
        return self._request("POST", f"/sleep/trial-returns/{return_id}/inspect",
                             payload, headers)

    # --- warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/sleep/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/sleep/warranty-claims/{claim_id}",
                             headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/sleep/warranty-claims", headers=headers,
                             params=params)

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/sleep/warranty-claims/{claim_id}/review",
                             payload, headers)

    def appeal_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/sleep/warranty-claims/{claim_id}/appeal",
                             {}, headers)

    # --- financing plans ---
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/sleep/financing-plans", payload, headers)

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"/sleep/financing-plans/{plan_id}",
                             headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/sleep/financing-plans", headers=headers,
                             params=params)

    def accept_financing_plan(self, plan_id, headers):
        return self._request("POST", f"/sleep/financing-plans/{plan_id}/accept",
                             {}, headers)

    def record_payment(self, plan_id, payload, headers):
        return self._request("POST", f"/sleep/financing-plans/{plan_id}/payments",
                             payload, headers)


api_client = ApiClient()
