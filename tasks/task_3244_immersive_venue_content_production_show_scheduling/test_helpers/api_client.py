"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/venue/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/venue/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/venue/productions/{production_id}", headers=headers)

    def activate_production(self, production_id, headers):
        return self._request("POST", f"/venue/productions/{production_id}/activate", {}, headers)

    def deactivate_production(self, production_id, headers):
        return self._request("POST", f"/venue/productions/{production_id}/deactivate", {}, headers)

    def retire_production(self, production_id, headers):
        return self._request("POST", f"/venue/productions/{production_id}/retire", {}, headers)

    # --- Assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/venue/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/venue/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/venue/assets/{asset_id}", headers=headers)

    def qc_approve_asset(self, asset_id, headers):
        return self._request("POST", f"/venue/assets/{asset_id}/qc/approve", {}, headers)

    def qc_fail_asset(self, asset_id, headers):
        return self._request("POST", f"/venue/assets/{asset_id}/qc/fail", {}, headers)

    def retry_asset(self, asset_id, headers):
        return self._request("POST", f"/venue/assets/{asset_id}/retry", {}, headers)

    def archive_asset(self, asset_id, headers):
        return self._request("POST", f"/venue/assets/{asset_id}/archive", {}, headers)

    # --- Render batches ---
    def create_render_batch(self, payload, headers):
        return self._request("POST", "/venue/render-batches", payload, headers)

    def get_render_batch(self, batch_id, headers):
        return self._request("GET", f"/venue/render-batches/{batch_id}", headers=headers)

    def dispatch_render_batch(self, batch_id, headers):
        return self._request("POST", f"/venue/render-batches/{batch_id}/dispatch", {}, headers)

    def settle_render_batch(self, batch_id, headers):
        return self._request("POST", f"/venue/render-batches/{batch_id}/settle", {}, headers)

    def abort_render_batch(self, batch_id, headers):
        return self._request("POST", f"/venue/render-batches/{batch_id}/abort", {}, headers)

    # --- Shows ---
    def create_show(self, payload, headers):
        return self._request("POST", "/venue/shows", payload, headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/venue/shows", headers=headers, params=params)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/venue/shows/{show_id}", headers=headers)

    def schedule_rehearsal(self, show_id, headers):
        return self._request("POST", f"/venue/shows/{show_id}/schedule-rehearsal", {}, headers)

    def confirm_show(self, show_id, payload, headers):
        return self._request("POST", f"/venue/shows/{show_id}/confirm", payload, headers)

    def complete_show(self, show_id, headers):
        return self._request("POST", f"/venue/shows/{show_id}/complete", {}, headers)

    def cancel_show(self, show_id, headers):
        return self._request("POST", f"/venue/shows/{show_id}/cancel", {}, headers)

    # --- Bookings ---
    def create_booking(self, show_id, payload, headers):
        return self._request("POST", f"/venue/shows/{show_id}/bookings", payload, headers)

    def list_bookings(self, show_id, headers, params=None):
        return self._request("GET", f"/venue/shows/{show_id}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/venue/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/venue/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/venue/bookings/{booking_id}/cancel", {}, headers)

    # --- Settlement ---
    def get_settlement(self, show_id, headers):
        return self._request("GET", f"/venue/shows/{show_id}/settlement", headers=headers)

    # --- Venue systems ---
    def create_venue_system(self, payload, headers):
        return self._request("POST", "/venue-systems", payload, headers)

    def list_venue_systems(self, headers, params=None):
        return self._request("GET", "/venue-systems", headers=headers, params=params)

    def get_venue_system(self, system_id, headers):
        return self._request("GET", f"/venue-systems/{system_id}", headers=headers)

    def repair_venue_system(self, system_id, headers):
        return self._request("POST", f"/venue-systems/{system_id}/repair", {}, headers)

    # --- Maintenance windows ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/venue/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/venue/maintenance-windows", headers=headers, params=params)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/venue/maintenance-windows/{window_id}", headers=headers)

    def complete_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/venue/maintenance-windows/{window_id}/complete", {}, headers)

    def fail_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/venue/maintenance-windows/{window_id}/fail", {}, headers)

    # --- Sponsors & campaigns ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/venue/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/venue/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/venue/sponsors/{sponsor_id}", headers=headers)

    def create_campaign(self, payload, headers):
        return self._request("POST", "/venue/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/venue/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/venue/campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/venue/campaigns/{campaign_id}/activate", payload, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/venue/campaigns/{campaign_id}/pause", {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/venue/campaigns/{campaign_id}/cancel", {}, headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/venue/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
