"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc},
            headers=headers,
        )

    # --- Licensors ---
    def create_licensor(self, payload, headers):
        return self._request("POST", "/licensors", payload, headers)

    def get_licensor(self, licensor_id, headers):
        return self._request("GET", f"/licensors/{licensor_id}", headers=headers)

    def list_settlements(self, licensor_id, headers, params=None):
        return self._request(
            "GET", f"/licensors/{licensor_id}/minimum-guarantee-settlements",
            headers=headers, params=params,
        )

    def apply_settlement(self, licensor_id, payload, headers):
        return self._request(
            "POST", f"/licensors/{licensor_id}/minimum-guarantee/apply",
            payload, headers,
        )

    def reverse_settlement(self, licensor_id, payload, headers):
        return self._request(
            "POST", f"/licensors/{licensor_id}/minimum-guarantee/reverse",
            payload, headers,
        )

    # --- Designs ---
    def create_design(self, payload, headers):
        return self._request("POST", "/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/designs/{design_id}", headers=headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", "/designs", headers=headers, params=params)

    def submit_design(self, design_id, payload, headers):
        return self._request("PUT", f"/designs/{design_id}/submit", payload, headers)

    def licensor_decision(self, design_id, payload, headers):
        return self._request(
            "PUT", f"/designs/{design_id}/licensor-decision", payload, headers,
        )

    # --- Production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/production-orders", payload, headers)

    def get_production_order(self, production_order_id, headers):
        return self._request(
            "GET", f"/production-orders/{production_order_id}", headers=headers,
        )

    def list_production_orders(self, headers, params=None):
        return self._request(
            "GET", "/production-orders", headers=headers, params=params,
        )

    def author_layers(self, production_order_id, payload, headers):
        return self._request(
            "POST", f"/production-orders/{production_order_id}/layers",
            payload, headers,
        )

    def retire_production_order(self, production_order_id, payload, headers):
        return self._request(
            "POST", f"/production-orders/{production_order_id}/retire",
            payload, headers,
        )

    # --- Print layers ---
    def print_layer(self, print_layer_id, payload, headers):
        return self._request(
            "POST", f"/print-layers/{print_layer_id}/print", payload, headers,
        )

    def print_failure(self, print_layer_id, payload, headers):
        return self._request(
            "POST", f"/print-layers/{print_layer_id}/print-failure", payload, headers,
        )

    def list_print_layers(self, headers, params=None):
        return self._request("GET", "/print-layers", headers=headers, params=params)

    def get_print_layer(self, print_layer_id, headers):
        return self._request(
            "GET", f"/print-layers/{print_layer_id}", headers=headers,
        )

    # --- Print capacity ---
    def create_print_capacity(self, payload, headers):
        return self._request("POST", "/print-capacity", payload, headers)

    def get_print_capacity(self, print_capacity_id, headers):
        return self._request(
            "GET", f"/print-capacity/{print_capacity_id}", headers=headers,
        )

    def reserve_capacity(self, payload, headers):
        return self._request("POST", "/print-capacity:reserve", payload, headers)

    def list_reservations(self, print_capacity_id, headers, params=None):
        return self._request(
            "GET", f"/print-capacity/{print_capacity_id}/reservations",
            headers=headers, params=params,
        )

    # --- Fulfillment orders ---
    def create_fulfillment_order(self, payload, headers):
        return self._request("POST", "/fulfillment-orders", payload, headers)

    def get_fulfillment_order(self, fulfillment_order_id, headers):
        return self._request(
            "GET", f"/fulfillment-orders/{fulfillment_order_id}", headers=headers,
        )

    def list_fulfillment_orders(self, headers, params=None):
        return self._request(
            "GET", "/fulfillment-orders", headers=headers, params=params,
        )

    def pick(self, fulfillment_order_id, payload, headers):
        return self._request(
            "POST", f"/fulfillment-orders/{fulfillment_order_id}/pick",
            payload, headers,
        )

    def ship(self, fulfillment_order_id, payload, headers):
        return self._request(
            "POST", f"/fulfillment-orders/{fulfillment_order_id}/ship",
            payload, headers,
        )

    def deliver(self, fulfillment_order_id, payload, headers):
        return self._request(
            "POST", f"/fulfillment-orders/{fulfillment_order_id}/deliver",
            payload, headers,
        )

    def return_order(self, fulfillment_order_id, payload, headers):
        return self._request(
            "POST", f"/fulfillment-orders/{fulfillment_order_id}/return",
            payload, headers,
        )

    def distress(self, fulfillment_order_id, payload, headers):
        return self._request(
            "POST", f"/fulfillment-orders/{fulfillment_order_id}/distress",
            payload, headers,
        )

    def list_shipments(self, fulfillment_order_id, headers, params=None):
        return self._request(
            "GET", f"/fulfillment-orders/{fulfillment_order_id}/shipments",
            headers=headers, params=params,
        )

    # --- Royalty accruals ---
    def list_royalty_accruals(self, headers, params=None):
        return self._request(
            "GET", "/royalty-accruals", headers=headers, params=params,
        )

    def get_royalty_accrual(self, accrual_id, headers):
        return self._request(
            "GET", f"/royalty-accruals/{accrual_id}", headers=headers,
        )

    # --- Counterfeit reports ---
    def create_counterfeit_report(self, payload, headers):
        return self._request("POST", "/counterfeit-reports", payload, headers)

    def enforce_counterfeit_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/counterfeit-reports/{report_id}/enforce", payload, headers,
        )

    def get_counterfeit_report(self, report_id, headers):
        return self._request(
            "GET", f"/counterfeit-reports/{report_id}", headers=headers,
        )

    def list_counterfeit_reports(self, headers, params=None):
        return self._request(
            "GET", "/counterfeit-reports", headers=headers, params=params,
        )


api_client = ApiClient()