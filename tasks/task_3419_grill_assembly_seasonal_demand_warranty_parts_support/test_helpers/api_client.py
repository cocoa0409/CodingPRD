"""API client: one method per endpoint defined in PRD section 4.

All paths live under the /grillops prefix. Methods return raw requests.Response
objects; callers validate with validate_success / validate_error / get_success_data.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD 2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/grillops/_clock/set_current_utc", payload, headers)

    # --- Seasons / lots (PRD 3.1, 3.3) ---
    def create_season(self, payload, headers):
        return self._request("POST", "/grillops/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/grillops/seasons/{season_id}", headers=headers)

    def advance_season(self, season_id, payload, headers):
        return self._request("POST", f"/grillops/seasons/{season_id}/advance", payload, headers)

    def create_lot(self, season_id, payload, headers):
        return self._request("POST", f"/grillops/seasons/{season_id}/lots", payload, headers)

    def list_season_lots(self, season_id, headers, params=None):
        return self._request("GET", f"/grillops/seasons/{season_id}/lots", headers=headers, params=params)

    def list_model_lots(self, model_id, headers, params=None):
        return self._request("GET", f"/grillops/models/{model_id}/lots", headers=headers, params=params)

    # --- Grill models (PRD 3.2) ---
    def create_model(self, payload, headers):
        return self._request("POST", "/grillops/models", payload, headers)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/grillops/models/{model_id}", headers=headers)

    def model_lifecycle(self, model_id, payload, headers):
        return self._request("POST", f"/grillops/models/{model_id}/lifecycle", payload, headers)

    # --- Channel accounts (PRD 3.4) ---
    def create_channel(self, payload, headers):
        return self._request("POST", "/grillops/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/grillops/channels/{channel_id}", headers=headers)

    # --- Allocations (PRD 3.4) ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/grillops/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/grillops/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/grillops/allocations", headers=headers, params=params)

    def respond_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/grillops/allocations/{allocation_id}/respond", payload, headers)

    # --- Assemblers (PRD 3.6) ---
    def create_assembler(self, payload, headers):
        return self._request("POST", "/grillops/assemblers", payload, headers)

    def get_assembler(self, assembler_id, headers):
        return self._request("GET", f"/grillops/assemblers/{assembler_id}", headers=headers)

    def assembler_status(self, assembler_id, payload, headers):
        return self._request("POST", f"/grillops/assemblers/{assembler_id}/status", payload, headers)

    # --- Assembly jobs (PRD 3.6) ---
    def create_assembly_job(self, payload, headers):
        return self._request("POST", "/grillops/assembly-jobs", payload, headers)

    def get_assembly_job(self, job_id, headers):
        return self._request("GET", f"/grillops/assembly-jobs/{job_id}", headers=headers)

    def list_assembly_jobs(self, headers, params=None):
        return self._request("GET", "/grillops/assembly-jobs", headers=headers, params=params)

    def transition_assembly_job(self, job_id, payload, headers):
        return self._request("POST", f"/grillops/assembly-jobs/{job_id}/transition", payload, headers)

    # --- Sales (PRD 3.5) ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/grillops/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/grillops/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/grillops/sales", headers=headers, params=params)

    def transition_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/grillops/sales/{sale_id}/transition", payload, headers)

    # --- Warranty claims (PRD 3.7) ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/grillops/warranty-claims", payload, headers)

    def list_sale_warranty_claims(self, sale_id, headers, params=None):
        return self._request("GET", f"/grillops/sales/{sale_id}/warranty-claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/grillops/warranty-claims/{claim_id}/adjudicate", payload, headers)

    # --- Parts catalog (PRD 3.8) ---
    def create_part(self, payload, headers):
        return self._request("POST", "/grillops/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/grillops/parts/{part_id}", headers=headers)

    def transition_part(self, part_id, payload, headers):
        return self._request("POST", f"/grillops/parts/{part_id}/transition", payload, headers)

    # --- Parts orders (PRD 3.8) ---
    def create_parts_order(self, payload, headers):
        return self._request("POST", "/grillops/parts-orders", payload, headers)

    def get_parts_order(self, order_id, headers):
        return self._request("GET", f"/grillops/parts-orders/{order_id}", headers=headers)

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", "/grillops/parts-orders", headers=headers, params=params)

    def transition_parts_order(self, order_id, payload, headers):
        return self._request("POST", f"/grillops/parts-orders/{order_id}/transition", payload, headers)

    # --- Connected devices (PRD 3.9) ---
    def pair_device(self, payload, headers):
        return self._request("POST", "/grillops/devices/pair", payload, headers)

    def device_firmware(self, device_id, payload, headers):
        return self._request("POST", f"/grillops/devices/{device_id}/firmware", payload, headers)

    def list_sale_devices(self, sale_id, headers, params=None):
        return self._request("GET", f"/grillops/sales/{sale_id}/devices", headers=headers, params=params)


api_client = ApiClient()
