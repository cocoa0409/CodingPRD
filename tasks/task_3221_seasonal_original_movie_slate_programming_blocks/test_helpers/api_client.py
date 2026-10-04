"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # --- Studio ---
    def create_studio(self, payload, headers):
        return self._request("POST", "/slate/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/slate/studios/{studio_id}", headers=headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/slate/studios", headers=headers, params=params)

    # --- Season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/slate/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/slate/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/slate/seasons", headers=headers, params=params)

    def lock_season(self, season_id, headers):
        return self._request("POST", f"/slate/seasons/{season_id}/lock", {}, headers)

    def archive_season(self, season_id, headers):
        return self._request("POST", f"/slate/seasons/{season_id}/archive", {}, headers)

    # --- Title ---
    def create_title(self, payload, headers):
        return self._request("POST", "/slate/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/slate/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/slate/titles", headers=headers, params=params)

    def approve_title(self, title_id, payload, headers):
        return self._request("POST", f"/slate/titles/{title_id}/approve", payload, headers)

    def reject_title(self, title_id, headers):
        return self._request("POST", f"/slate/titles/{title_id}/reject", {}, headers)

    def cancel_title(self, title_id, headers):
        return self._request("POST", f"/slate/titles/{title_id}/cancel", {}, headers)

    def deliver_title(self, title_id, headers):
        return self._request("POST", f"/slate/titles/{title_id}/deliver", {}, headers)

    # --- Talent ---
    def create_talent(self, payload, headers):
        return self._request("POST", "/slate/talent", payload, headers)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/slate/talent/{talent_id}", headers=headers)

    def list_talent(self, headers, params=None):
        return self._request("GET", "/slate/talent", headers=headers, params=params)

    # --- TalentDeal ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/slate/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/slate/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/slate/deals", headers=headers, params=params)

    # --- Casting ---
    def create_casting(self, payload, headers):
        return self._request("POST", "/slate/castings", payload, headers)

    def get_casting(self, casting_id, headers):
        return self._request("GET", f"/slate/castings/{casting_id}", headers=headers)

    def list_castings(self, headers, params=None):
        return self._request("GET", "/slate/castings", headers=headers, params=params)

    def confirm_casting(self, casting_id, headers):
        return self._request("POST", f"/slate/castings/{casting_id}/confirm", {}, headers)

    def release_casting(self, casting_id, headers):
        return self._request("POST", f"/slate/castings/{casting_id}/release", {}, headers)

    # --- Location ---
    def create_location(self, payload, headers):
        return self._request("POST", "/slate/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/slate/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/slate/locations", headers=headers, params=params)

    # --- ProductionSlot ---
    def create_production_slot(self, payload, headers):
        return self._request("POST", "/slate/production-slots", payload, headers)

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/slate/production-slots/{slot_id}", headers=headers)

    def list_production_slots(self, headers, params=None):
        return self._request("GET", "/slate/production-slots", headers=headers, params=params)

    def wrap_production_slot(self, slot_id, headers):
        return self._request("POST", f"/slate/production-slots/{slot_id}/wrap", {}, headers)

    def cancel_production_slot(self, slot_id, headers):
        return self._request("POST", f"/slate/production-slots/{slot_id}/cancel", {}, headers)

    # --- ProgramBlock ---
    def create_program_block(self, payload, headers):
        return self._request("POST", "/slate/program-blocks", payload, headers)

    def get_program_block(self, block_id, headers):
        return self._request("GET", f"/slate/program-blocks/{block_id}", headers=headers)

    def list_program_blocks(self, headers, params=None):
        return self._request("GET", "/slate/program-blocks", headers=headers, params=params)

    def publish_program_block(self, block_id, headers):
        return self._request("POST", f"/slate/program-blocks/{block_id}/publish", {}, headers)

    # --- AirSlot ---
    def create_air_slot(self, payload, headers):
        return self._request("POST", "/slate/air-slots", payload, headers)

    def get_air_slot(self, air_slot_id, headers):
        return self._request("GET", f"/slate/air-slots/{air_slot_id}", headers=headers)

    def list_air_slots(self, headers, params=None):
        return self._request("GET", "/slate/air-slots", headers=headers, params=params)

    def mark_air_slot_aired(self, air_slot_id, headers):
        return self._request("POST", f"/slate/air-slots/{air_slot_id}/mark-aired", {}, headers)

    def cancel_air_slot(self, air_slot_id, headers):
        return self._request("POST", f"/slate/air-slots/{air_slot_id}/cancel", {}, headers)

    # --- Sponsorship ---
    def create_sponsorship(self, payload, headers):
        return self._request("POST", "/slate/sponsorships", payload, headers)

    def get_sponsorship(self, sponsorship_id, headers):
        return self._request("GET", f"/slate/sponsorships/{sponsorship_id}", headers=headers)

    def list_sponsorships(self, headers, params=None):
        return self._request("GET", "/slate/sponsorships", headers=headers, params=params)

    def reconcile_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/slate/sponsorships/{sponsorship_id}/reconcile", {}, headers)

    def cancel_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/slate/sponsorships/{sponsorship_id}/cancel", {}, headers)

    # --- StreamingWindow ---
    def create_streaming_window(self, payload, headers):
        return self._request("POST", "/slate/streaming-windows", payload, headers)

    def get_streaming_window(self, window_id, headers):
        return self._request("GET", f"/slate/streaming-windows/{window_id}", headers=headers)

    def list_streaming_windows(self, headers, params=None):
        return self._request("GET", "/slate/streaming-windows", headers=headers, params=params)

    def open_streaming_window(self, window_id, headers):
        return self._request("POST", f"/slate/streaming-windows/{window_id}/open", {}, headers)

    def close_streaming_window(self, window_id, headers):
        return self._request("POST", f"/slate/streaming-windows/{window_id}/close", {}, headers)

    # --- LicenseGrant ---
    def create_license(self, payload, headers):
        return self._request("POST", "/slate/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/slate/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/slate/licenses", headers=headers, params=params)

    def audit_license(self, license_id, headers):
        return self._request("POST", f"/slate/licenses/{license_id}/audit", {}, headers)


api_client = ApiClient()
