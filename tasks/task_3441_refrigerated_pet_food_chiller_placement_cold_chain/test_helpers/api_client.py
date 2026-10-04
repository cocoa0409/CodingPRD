"""API client: one method per endpoint defined in the PRD (§4).

The logical-clock endpoint `POST /_clock/set_current_utc` is an UNPREFIXED
platform endpoint (PRD §2.4): it lives outside the `/cold-chain` prefix and
must be called exactly as written here.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform logical clock (UNPREFIXED — do not add /cold-chain) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/cold-chain/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/cold-chain/stores/{store_id}", headers=headers)

    # --- Site evaluations ---
    def create_site_evaluation(self, store_id, payload, headers):
        return self._request("POST", f"/cold-chain/stores/{store_id}/site-evaluations", payload, headers)

    def list_site_evaluations(self, store_id, headers, params=None):
        return self._request("GET", f"/cold-chain/stores/{store_id}/site-evaluations", headers=headers, params=params)

    # --- Placement agreements ---
    def create_placement_agreement(self, store_id, payload, headers):
        return self._request("POST", f"/cold-chain/stores/{store_id}/placement-agreements", payload, headers)

    def list_placement_agreements(self, store_id, headers, params=None):
        return self._request("GET", f"/cold-chain/stores/{store_id}/placement-agreements", headers=headers, params=params)

    def revise_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/cold-chain/placement-agreements/{agreement_id}/revise", payload, headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cold-chain/placement-agreements/{agreement_id}/sign", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/cold-chain/placement-agreements/{agreement_id}/terminate", {}, headers)

    # --- Chillers ---
    def create_chillers(self, payload, headers):
        return self._request("POST", "/cold-chain/chillers", payload, headers)

    def list_chillers(self, headers, params=None):
        return self._request("GET", "/cold-chain/chillers", headers=headers, params=params)

    def get_chiller(self, chiller_id, headers):
        return self._request("GET", f"/cold-chain/chillers/{chiller_id}", headers=headers)

    def decommission_chiller(self, chiller_id, headers):
        return self._request("POST", f"/cold-chain/chillers/{chiller_id}/decommission", {}, headers)

    def post_temperature_reading(self, chiller_id, payload, headers):
        return self._request("POST", f"/cold-chain/chillers/{chiller_id}/temperature-readings", payload, headers)

    def list_temperature_readings(self, chiller_id, headers, params=None):
        return self._request("GET", f"/cold-chain/chillers/{chiller_id}/temperature-readings", headers=headers, params=params)

    # --- Placements ---
    def create_placement(self, payload, headers):
        return self._request("POST", "/cold-chain/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/cold-chain/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/cold-chain/placements/{placement_id}", headers=headers)

    def evaluate_performance(self, placement_id, payload, headers):
        return self._request("POST", f"/cold-chain/placements/{placement_id}/evaluate-performance", payload, headers)

    def retire_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/cold-chain/placements/{placement_id}/retire", payload, headers)

    # --- Service tickets ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/cold-chain/service-tickets", payload, headers)

    def list_service_tickets(self, chiller_id, headers, params=None):
        return self._request("GET", f"/cold-chain/chillers/{chiller_id}/service-tickets", headers=headers, params=params)

    def dispatch_service_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/cold-chain/service-tickets/{ticket_id}/dispatch", payload, headers)

    def resolve_service_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/cold-chain/service-tickets/{ticket_id}/resolve", payload, headers)

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/cold-chain/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/cold-chain/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/cold-chain/shipments/{shipment_id}", headers=headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/cold-chain/shipments/{shipment_id}/deliver", payload, headers)

    # --- Product lots ---
    def create_product_lot(self, payload, headers):
        return self._request("POST", "/cold-chain/product-lots", payload, headers)

    def get_product_lot(self, lot_id, headers):
        return self._request("GET", f"/cold-chain/product-lots/{lot_id}", headers=headers)

    def release_product_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/cold-chain/product-lots/{lot_id}/release", payload, headers)

    # --- Inventory positions ---
    def list_inventory_positions(self, headers, params=None):
        return self._request("GET", "/cold-chain/inventory-positions", headers=headers, params=params)

    def get_inventory_position(self, position_id, headers):
        return self._request("GET", f"/cold-chain/inventory-positions/{position_id}", headers=headers)

    def run_date_check_sweep(self, store_id, headers):
        return self._request("POST", f"/cold-chain/stores/{store_id}/inventory/date-check-sweep", {}, headers)

    # --- Capacity projects ---
    def create_capacity_project(self, payload, headers):
        return self._request("POST", "/cold-chain/capacity-projects", payload, headers)

    def approve_capacity_project(self, project_id, headers):
        return self._request("POST", f"/cold-chain/capacity-projects/{project_id}/approve", {}, headers)

    def commission_capacity_project(self, project_id, headers):
        return self._request("POST", f"/cold-chain/capacity-projects/{project_id}/commission", {}, headers)

    # --- Trial campaigns ---
    def create_trial_campaign(self, store_id, payload, headers):
        return self._request("POST", f"/cold-chain/stores/{store_id}/trial-campaigns", payload, headers)

    def list_trial_campaigns(self, store_id, headers, params=None):
        return self._request("GET", f"/cold-chain/stores/{store_id}/trial-campaigns", headers=headers, params=params)


api_client = ApiClient()
