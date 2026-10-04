"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted at the API root (api_prefix "/"), so paths below
already carry their leading slash. Multi-field action bodies (deviation,
study, inspection, disposition) take a payload dict; single-field action
bodies (advance/hold/shipment action) take the value directly.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # --- Bioreactor trains ---
    def create_train(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/trains", payload, headers)

    def list_trains(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/trains", headers=headers, params=params)

    # --- Material lots ---
    def create_material(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/materials", payload, headers)

    def list_materials(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/materials", headers=headers, params=params)

    def hold_material(self, material_id, quarantined, headers):
        return self._request("POST", f"/materials/{material_id}/hold", {"quarantined": quarantined}, headers)

    # --- Regulatory inspections ---
    def create_inspection(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/inspections", payload, headers)

    def list_inspections(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/inspections", headers=headers, params=params)

    def inspection_action(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/action", payload, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- Comparability studies ---
    def create_comparability_study(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/comparability-studies", payload, headers)

    def list_comparability_studies(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/comparability-studies", headers=headers, params=params)

    def study_action(self, study_id, payload, headers):
        return self._request("POST", f"/comparability-studies/{study_id}/action", payload, headers)

    # --- Campaigns ---
    def create_campaign(self, train_id, payload, headers):
        return self._request("POST", f"/trains/{train_id}/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def advance_campaign(self, campaign_id, to_status, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/advance", {"to_status": to_status}, headers)

    # --- Seed train stages ---
    def create_seed_stage(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/seed-stages", payload, headers)

    def list_seed_stages(self, campaign_id, headers, params=None):
        return self._request("GET", f"/campaigns/{campaign_id}/seed-stages", headers=headers, params=params)

    def advance_seed_stage(self, stage_id, to_status, headers):
        return self._request("POST", f"/seed-stages/{stage_id}/advance", {"to_status": to_status}, headers)

    # --- Batch lots ---
    def create_batch(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/batches", payload, headers)

    def list_batches(self, campaign_id, headers, params=None):
        return self._request("GET", f"/campaigns/{campaign_id}/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def advance_batch(self, batch_id, to_status, headers):
        return self._request("POST", f"/batches/{batch_id}/advance", {"to_status": to_status}, headers)

    def submit_batch_for_review(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/submit-for-review", headers=headers)

    def disposition_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/disposition", payload, headers)

    # --- In-process tests (OCC endpoint: expected_batch_version in payload) ---
    def create_test(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/tests", payload, headers)

    def list_tests(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/tests", headers=headers, params=params)

    def verify_test(self, test_id, headers):
        return self._request("POST", f"/tests/{test_id}/verify", headers=headers)

    # --- Deviations ---
    def create_deviation(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/deviations", payload, headers)

    def list_deviations(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/deviations", headers=headers, params=params)

    def deviation_action(self, deviation_id, payload, headers):
        return self._request("POST", f"/deviations/{deviation_id}/action", payload, headers)

    # --- Shipments & cold chain ---
    def create_shipment(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/shipments", payload, headers)

    def list_shipments(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def shipment_action(self, shipment_id, action, headers):
        return self._request("POST", f"/shipments/{shipment_id}/action", {"action": action}, headers)

    def create_reading(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/readings", payload, headers)

    def list_readings(self, shipment_id, headers, params=None):
        return self._request("GET", f"/shipments/{shipment_id}/readings", headers=headers, params=params)

    def evaluate_excursion(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/evaluate-excursion", headers=headers)


api_client = ApiClient()
