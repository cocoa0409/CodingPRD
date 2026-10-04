"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Rights properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/platform/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/platform/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/platform/properties", headers=headers, params=params)

    def activate_property(self, property_id, headers):
        return self._request("POST", f"/platform/properties/{property_id}/activate", {}, headers)

    def suspend_property(self, property_id, headers):
        return self._request("POST", f"/platform/properties/{property_id}/suspend", {}, headers)

    def unsuspend_property(self, property_id, headers):
        return self._request("POST", f"/platform/properties/{property_id}/unsuspend", {}, headers)

    def terminate_property(self, property_id, headers):
        return self._request("POST", f"/platform/properties/{property_id}/terminate", {}, headers)

    def list_property_windows(self, property_id, headers, params=None):
        return self._request("GET", f"/platform/properties/{property_id}/windows", headers=headers, params=params)

    # --- Streaming windows ---
    def create_window(self, payload, headers):
        return self._request("POST", "/platform/windows", payload, headers)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/platform/windows/{window_id}", headers=headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/platform/windows", headers=headers, params=params)

    def go_live_window(self, window_id, headers):
        return self._request("POST", f"/platform/windows/{window_id}/go-live", {}, headers)

    def complete_window(self, window_id, headers):
        return self._request("POST", f"/platform/windows/{window_id}/complete", {}, headers)

    def cancel_window(self, window_id, headers):
        return self._request("POST", f"/platform/windows/{window_id}/cancel", {}, headers)

    def get_window_pods(self, window_id, headers):
        return self._request("GET", f"/platform/windows/{window_id}/pods", headers=headers)

    def create_view_grant(self, window_id, payload, headers):
        return self._request("POST", f"/platform/windows/{window_id}/view-grants", payload, headers)

    # --- Territory rules ---
    def create_territory_rule(self, payload, headers):
        return self._request("POST", "/platform/territory-rules", payload, headers)

    def get_territory_rule(self, rule_id, headers):
        return self._request("GET", f"/platform/territory-rules/{rule_id}", headers=headers)

    def list_territory_rules(self, headers, params=None):
        return self._request("GET", "/platform/territory-rules", headers=headers, params=params)

    def lift_territory_rule(self, rule_id, headers):
        return self._request("POST", f"/platform/territory-rules/{rule_id}/lift", {}, headers)

    # --- Viewers ---
    def create_viewer(self, payload, headers):
        return self._request("POST", "/platform/viewers", payload, headers)

    def get_viewer(self, viewer_id, headers):
        return self._request("GET", f"/platform/viewers/{viewer_id}", headers=headers)

    def list_viewers(self, headers, params=None):
        return self._request("GET", "/platform/viewers", headers=headers, params=params)

    def reactivate_viewer(self, viewer_id, headers):
        return self._request("POST", f"/platform/viewers/{viewer_id}/reactivate", {}, headers)

    def suspend_billing_viewer(self, viewer_id, headers):
        return self._request("POST", f"/platform/viewers/{viewer_id}/suspend-billing", {}, headers)

    def cancel_viewer(self, viewer_id, headers):
        return self._request("POST", f"/platform/viewers/{viewer_id}/cancel", {}, headers)

    # --- View grants ---
    def get_view_grant(self, grant_id, headers):
        return self._request("GET", f"/platform/view-grants/{grant_id}", headers=headers)

    def list_view_grants(self, headers, params=None):
        return self._request("GET", "/platform/view-grants", headers=headers, params=params)

    # --- Capacity ---
    def create_capacity_pool(self, payload, headers):
        return self._request("POST", "/platform/capacity-pools", payload, headers)

    def get_capacity_pool(self, pool_id, headers):
        return self._request("GET", f"/platform/capacity-pools/{pool_id}", headers=headers)

    def list_capacity_pools(self, headers, params=None):
        return self._request("GET", "/platform/capacity-pools", headers=headers, params=params)

    def create_capacity_reservation(self, payload, headers):
        return self._request("POST", "/platform/capacity-reservations", payload, headers)

    def get_capacity_reservation(self, reservation_id, headers):
        return self._request("GET", f"/platform/capacity-reservations/{reservation_id}", headers=headers)

    def list_capacity_reservations(self, headers, params=None):
        return self._request("GET", "/platform/capacity-reservations", headers=headers, params=params)

    def confirm_capacity_reservation(self, reservation_id, headers):
        return self._request("POST", f"/platform/capacity-reservations/{reservation_id}/confirm", {}, headers)

    def release_capacity_reservation(self, reservation_id, headers):
        return self._request("POST", f"/platform/capacity-reservations/{reservation_id}/release", {}, headers)

    # --- Ad campaigns ---
    def create_ad_campaign(self, payload, headers):
        return self._request("POST", "/platform/ad-campaigns", payload, headers)

    def get_ad_campaign(self, campaign_id, headers):
        return self._request("GET", f"/platform/ad-campaigns/{campaign_id}", headers=headers)

    def book_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/book", {}, headers)

    def pause_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/pause", {}, headers)

    def resume_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/platform/ad-campaigns/{campaign_id}/resume", {}, headers)

    # --- Ad slots ---
    def create_ad_slot(self, payload, headers):
        return self._request("POST", "/platform/ad-slots", payload, headers)

    def get_ad_slot(self, slot_id, headers):
        return self._request("GET", f"/platform/ad-slots/{slot_id}", headers=headers)

    def list_ad_slots(self, headers, params=None):
        return self._request("GET", "/platform/ad-slots", headers=headers, params=params)

    def fill_ad_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/platform/ad-slots/{slot_id}/fill", payload, headers)

    def release_ad_slot(self, slot_id, headers):
        return self._request("POST", f"/platform/ad-slots/{slot_id}/release", {}, headers)

    def mark_ad_slot_unfillable(self, slot_id, headers):
        return self._request("POST", f"/platform/ad-slots/{slot_id}/mark-unfillable", {}, headers)

    def serve_ad_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/platform/ad-slots/{slot_id}/serve", payload, headers)

    # --- Impressions ---
    def get_impression(self, impression_id, headers):
        return self._request("GET", f"/platform/impressions/{impression_id}", headers=headers)

    def list_impressions(self, headers, params=None):
        return self._request("GET", "/platform/impressions", headers=headers, params=params)

    # --- Partners / promo codes ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/platform/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/platform/partners/{partner_id}", headers=headers)

    def issue_promo_code(self, partner_id, headers):
        return self._request("POST", f"/platform/partners/{partner_id}/promo-codes", {}, headers)

    def get_promo_code(self, code_id, headers):
        return self._request("GET", f"/platform/promo-codes/{code_id}", headers=headers)

    def list_promo_codes(self, headers, params=None):
        return self._request("GET", "/platform/promo-codes", headers=headers, params=params)

    def redeem_promo_code(self, payload, headers):
        return self._request("POST", "/platform/promo-codes/redeem", payload, headers)

    def revoke_promo_code(self, code_id, headers):
        return self._request("POST", f"/platform/promo-codes/{code_id}/revoke", {}, headers)

    # --- Entitlements ---
    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/platform/entitlements/{entitlement_id}", headers=headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/platform/entitlements", headers=headers, params=params)

    # --- Replay assets ---
    def get_replay_asset(self, asset_id, headers):
        return self._request("GET", f"/platform/replay-assets/{asset_id}", headers=headers)

    def list_replay_assets(self, headers, params=None):
        return self._request("GET", "/platform/replay-assets", headers=headers, params=params)

    def pull_replay_asset(self, asset_id, headers):
        return self._request("POST", f"/platform/replay-assets/{asset_id}/pull", {}, headers)

    # --- Reports ---
    def get_property_economics(self, headers, params=None):
        return self._request("GET", "/platform/reports/property-economics", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/platform/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
