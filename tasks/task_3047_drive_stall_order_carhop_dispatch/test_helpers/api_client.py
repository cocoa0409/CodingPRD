"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Location ---
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def set_weather(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/weather", payload, headers)

    def advance_rush(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/advance_rush", {}, headers)

    def get_metrics(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/metrics", headers=headers, params=params)

    # --- MenuItem ---
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    def retire_menu_item(self, item_id, headers):
        return self._request("POST", f"/menu-items/{item_id}/retire", {}, headers)

    # --- CustomizationOption ---
    def create_customization_option(self, payload, headers):
        return self._request("POST", "/customization-options", payload, headers)

    def list_customization_options(self, headers, params=None):
        return self._request("GET", "/customization-options", headers=headers, params=params)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def adjust_wallet(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/wallet/adjust", payload, headers)

    # --- Stall ---
    def create_stall(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/stalls", payload, headers)

    def list_stalls(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/stalls", headers=headers, params=params)

    def get_stall(self, location_id, stall_id, headers):
        return self._request("GET", f"/locations/{location_id}/stalls/{stall_id}", headers=headers)

    def checkin(self, location_id, stall_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/stalls/{stall_id}/checkin", payload, headers)

    def app_checkin(self, location_id, stall_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/stalls/{stall_id}/app-checkin", payload, headers)

    def report_fault(self, location_id, stall_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/stalls/{stall_id}/faults", payload, headers)

    def list_faults(self, location_id, stall_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/stalls/{stall_id}/faults", headers=headers, params=params)

    def resolve_fault(self, location_id, stall_id, fault_id, headers):
        return self._request(
            "POST", f"/locations/{location_id}/stalls/{stall_id}/faults/{fault_id}/resolve", {}, headers
        )

    def set_out_of_service(self, location_id, stall_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/stalls/{stall_id}/set_out_of_service", payload, headers)

    def return_to_service(self, location_id, stall_id, headers):
        return self._request("POST", f"/locations/{location_id}/stalls/{stall_id}/return_to_service", {}, headers)

    # --- Order ---
    def create_order(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/orders", payload, headers)

    def list_orders(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/orders", headers=headers, params=params)

    def get_order(self, location_id, order_id, headers):
        return self._request("GET", f"/locations/{location_id}/orders/{order_id}", headers=headers)

    def add_order_line(self, location_id, order_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, location_id, order_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/orders/{order_id}/lines", headers=headers, params=params)

    def remove_order_line(self, location_id, order_id, line_id, headers):
        return self._request(
            "DELETE", f"/locations/{location_id}/orders/{order_id}/lines/{line_id}", headers=headers
        )

    def place_order(self, location_id, order_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/place", payload, headers)

    def start_preparation(self, location_id, order_id, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/start_preparation", {}, headers)

    def mark_ready(self, location_id, order_id, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/mark_ready", {}, headers)

    def authorize_payment(self, location_id, order_id, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/authorize_payment", {}, headers)

    def capture_payment(self, location_id, order_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/capture_payment", payload, headers)

    def refund_order(self, location_id, order_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/refund", payload, headers)

    def cancel_order(self, location_id, order_id, headers):
        return self._request("POST", f"/locations/{location_id}/orders/{order_id}/cancel", {}, headers)

    # --- Offer ---
    def create_offer(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/offers", payload, headers)

    def list_offers(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/offers", headers=headers, params=params)

    def get_offer(self, location_id, offer_id, headers):
        return self._request("GET", f"/locations/{location_id}/offers/{offer_id}", headers=headers)

    def disable_offer(self, location_id, offer_id, headers):
        return self._request("POST", f"/locations/{location_id}/offers/{offer_id}/disable", {}, headers)

    # --- ServiceTargetProfile ---
    def create_service_target(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/service-targets", payload, headers)

    def list_service_targets(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/service-targets", headers=headers, params=params)

    # --- Carhop ---
    def create_carhop(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/carhops", payload, headers)

    def list_carhops(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/carhops", headers=headers, params=params)

    def get_carhop(self, location_id, carhop_id, headers):
        return self._request("GET", f"/locations/{location_id}/carhops/{carhop_id}", headers=headers)

    # --- DeliveryRun ---
    def create_delivery_run(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/delivery-runs", payload, headers)

    def list_delivery_runs(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/delivery-runs", headers=headers, params=params)

    def get_delivery_run(self, location_id, run_id, headers):
        return self._request("GET", f"/locations/{location_id}/delivery-runs/{run_id}", headers=headers)

    def depart_run(self, location_id, run_id, headers):
        return self._request("POST", f"/locations/{location_id}/delivery-runs/{run_id}/depart", {}, headers)

    def void_run(self, location_id, run_id, headers):
        return self._request("POST", f"/locations/{location_id}/delivery-runs/{run_id}/void", {}, headers)

    def deliver_order(self, location_id, run_id, order_id, headers):
        return self._request(
            "POST",
            f"/locations/{location_id}/delivery-runs/{run_id}/orders/{order_id}/deliver",
            {},
            headers,
        )

    # --- TipRecord ---
    def list_tip_records(self, location_id, headers, params=None):
        return self._request("GET", f"/locations/{location_id}/tip-records", headers=headers, params=params)

    def settle_tip(self, location_id, tip_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/tip-records/{tip_id}/settle", payload, headers)

    # --- Flat alias reads ---
    def get_stall_flat(self, stall_id, headers):
        return self._request("GET", f"/locations/stalls/{stall_id}", headers=headers)

    def get_carhop_flat(self, carhop_id, headers):
        return self._request("GET", f"/locations/carhops/{carhop_id}", headers=headers)

    def get_order_flat(self, order_id, headers):
        return self._request("GET", f"/locations/orders/{order_id}", headers=headers)

    def get_offer_flat(self, offer_id, headers):
        return self._request("GET", f"/locations/offers/{offer_id}", headers=headers)

    def get_service_target_flat(self, profile_id, headers):
        return self._request("GET", f"/locations/service-targets/{profile_id}", headers=headers)

    def get_delivery_run_flat(self, run_id, headers):
        return self._request("GET", f"/locations/delivery-runs/{run_id}", headers=headers)

    def get_tip_record_flat(self, tip_id, headers):
        return self._request("GET", f"/locations/tip-records/{tip_id}", headers=headers)

    def get_order_line_flat(self, line_id, headers):
        return self._request("GET", f"/locations/order-lines/{line_id}", headers=headers)

    def get_fault_flat(self, fault_id, headers):
        return self._request("GET", f"/locations/faults/{fault_id}", headers=headers)

    # --- Flat filtered lists ---
    def list_stalls_flat(self, headers, params=None):
        return self._request("GET", "/locations/stalls", headers=headers, params=params)

    def list_carhops_flat(self, headers, params=None):
        return self._request("GET", "/locations/carhops", headers=headers, params=params)

    def list_orders_flat(self, headers, params=None):
        return self._request("GET", "/locations/orders", headers=headers, params=params)

    def list_offers_flat(self, headers, params=None):
        return self._request("GET", "/locations/offers", headers=headers, params=params)

    def list_service_targets_flat(self, headers, params=None):
        return self._request("GET", "/locations/service-targets", headers=headers, params=params)

    def list_delivery_runs_flat(self, headers, params=None):
        return self._request("GET", "/locations/delivery-runs", headers=headers, params=params)

    def list_tip_records_flat(self, headers, params=None):
        return self._request("GET", "/locations/tip-records", headers=headers, params=params)

    def list_order_lines_flat(self, headers, params=None):
        return self._request("GET", "/locations/order-lines", headers=headers, params=params)

    def list_faults_flat(self, headers, params=None):
        return self._request("GET", "/locations/faults", headers=headers, params=params)


api_client = ApiClient()
