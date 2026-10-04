"""API client: one method per operation in the PRD's endpoint table."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Pets -------------------------------------------------------------
    def create_pet(self, payload, headers):
        return self._request("POST", "/v1/pets", payload, headers)

    def list_pets(self, headers, params=None):
        return self._request("GET", "/v1/pets", headers=headers, params=params)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/v1/pets/{pet_id}", headers=headers)

    def record_weight(self, pet_id, payload, headers):
        return self._request("POST", f"/v1/pets/{pet_id}/weights", payload, headers)

    def report_passing(self, pet_id, payload, headers):
        return self._request("POST", f"/v1/pets/{pet_id}/passings", payload, headers)

    # --- Veterinarians ----------------------------------------------------
    def create_veterinarian(self, payload, headers):
        return self._request("POST", "/v1/veterinarians", payload, headers)

    def list_veterinarians(self, headers, params=None):
        return self._request("GET", "/v1/veterinarians", headers=headers, params=params)

    def get_veterinarian(self, vet_id, headers):
        return self._request("GET", f"/v1/veterinarians/{vet_id}", headers=headers)

    def set_vet_status(self, vet_id, payload, headers):
        return self._request("POST", f"/v1/veterinarians/{vet_id}/status", payload, headers)

    def list_vet_prescriptions(self, vet_id, headers, params=None):
        return self._request("GET", f"/v1/veterinarians/{vet_id}/prescriptions", headers=headers, params=params)

    # --- Products ---------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/v1/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/v1/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/v1/products/{product_id}", headers=headers)

    def list_product_autoship_items(self, product_id, headers, params=None):
        return self._request("GET", f"/v1/products/{product_id}/autoship-items", headers=headers, params=params)

    def list_product_order_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/v1/products/{product_id}/order-lines", headers=headers, params=params)

    def change_product_price(self, product_id, payload, headers):
        return self._request("POST", f"/v1/products/{product_id}/price", payload, headers)

    # --- Pharmacy sites ---------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/v1/pharmacy-sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/v1/pharmacy-sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/v1/pharmacy-sites/{site_id}", headers=headers)

    def list_site_shipments(self, site_id, headers, params=None):
        return self._request("GET", f"/v1/pharmacy-sites/{site_id}/shipments", headers=headers, params=params)

    def list_site_cold_pack_reservations(self, site_id, headers, params=None):
        return self._request("GET", f"/v1/pharmacy-sites/{site_id}/cold-pack-reservations", headers=headers, params=params)

    def restrict_site(self, site_id, headers):
        return self._request("POST", f"/v1/pharmacy-sites/{site_id}/restrict", headers=headers)

    def clear_site_restriction(self, site_id, headers):
        return self._request("POST", f"/v1/pharmacy-sites/{site_id}/clear-restriction", headers=headers)

    def close_site(self, site_id, headers):
        return self._request("POST", f"/v1/pharmacy-sites/{site_id}/close", headers=headers)

    # --- Autoship plans ---------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/autoship-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/autoship-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/autoship-plans/{plan_id}", headers=headers)

    def pause_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/pause", headers=headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/resume", headers=headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/suspend", headers=headers)

    def cancel_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/cancel", payload, headers)

    def compose_order(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/compose", payload, headers)

    def list_plan_orders(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/autoship-plans/{plan_id}/orders", headers=headers, params=params)

    def list_plan_items(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/autoship-plans/{plan_id}/items", headers=headers, params=params)

    # --- Autoship items ---------------------------------------------------
    def add_item(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/items", payload, headers)

    def get_item(self, plan_id, item_id, headers):
        return self._request("GET", f"/v1/autoship-plans/{plan_id}/items/{item_id}", headers=headers)

    def get_item_by_id(self, item_id, headers):
        return self._request("GET", f"/v1/autoship-items/{item_id}", headers=headers)

    def list_item_order_lines(self, item_id, headers, params=None):
        return self._request("GET", f"/v1/autoship-items/{item_id}/order-lines", headers=headers, params=params)

    def change_cadence(self, plan_id, item_id, payload, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/items/{item_id}/cadence", payload, headers)

    def pause_item(self, plan_id, item_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/items/{item_id}/pause", headers=headers)

    def resume_item(self, plan_id, item_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/items/{item_id}/resume", headers=headers)

    def cancel_item(self, plan_id, item_id, headers):
        return self._request("POST", f"/v1/autoship-plans/{plan_id}/items/{item_id}/cancel", headers=headers)

    # --- Prescriptions ----------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", "/v1/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/v1/prescriptions", headers=headers, params=params)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/v1/prescriptions/{rx_id}", headers=headers)

    def record_clinic_contact(self, rx_id, headers):
        return self._request("POST", f"/v1/prescriptions/{rx_id}/clinic-contacts", headers=headers)

    def authorize_prescription(self, rx_id, payload, headers):
        return self._request("POST", f"/v1/prescriptions/{rx_id}/clinic-authorizations", payload, headers)

    def reopen_prescription(self, rx_id, headers):
        return self._request("POST", f"/v1/prescriptions/{rx_id}/reopen", headers=headers)

    # --- Orders -----------------------------------------------------------
    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/ship", headers=headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/deliver", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/lines", headers=headers, params=params)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/v1/orders/{order_id}/shipments", headers=headers, params=params)

    def list_order_lines_all(self, headers, params=None):
        return self._request("GET", "/v1/order-lines", headers=headers, params=params)

    # --- Shipments --------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/v1/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/v1/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/v1/shipments/{shipment_id}", headers=headers)

    def list_shipment_reservations(self, shipment_id, headers, params=None):
        return self._request("GET", f"/v1/shipments/{shipment_id}/cold-pack-reservations", headers=headers, params=params)

    def list_cold_pack_reservations(self, headers, params=None):
        return self._request("GET", "/v1/cold-pack-reservations", headers=headers, params=params)

    # --- Compassionate reviews -------------------------------------------
    def decide_review(self, review_id, payload, headers):
        return self._request("POST", f"/v1/compassionate-reviews/{review_id}/decide", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/v1/compassionate-reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/v1/compassionate-reviews/{review_id}", headers=headers)

    # --- Test-driving capabilities ---------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    def find_eligible_sites(self, headers, params=None):
        return self._request("GET", "/v1/_sites/find-eligible", headers=headers, params=params)


api_client = ApiClient()