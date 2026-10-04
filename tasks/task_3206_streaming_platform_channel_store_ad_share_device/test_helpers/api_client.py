"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Publishers ---
    def create_publisher(self, payload, headers):
        return self._request("POST", "/publishers", payload, headers)

    def list_publishers(self, headers, params=None):
        return self._request("GET", "/publishers", headers=headers, params=params)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/publishers/{publisher_id}", headers=headers)

    def set_publisher_standing(self, publisher_id, payload, headers):
        return self._request(
            "POST", f"/publishers/{publisher_id}/standing", payload, headers,
        )

    def list_publisher_channels(self, publisher_id, headers, params=None):
        return self._request(
            "GET", f"/publishers/{publisher_id}/channels", headers=headers,
            params=params,
        )

    def list_publisher_campaigns(self, publisher_id, headers, params=None):
        return self._request(
            "GET", f"/publishers/{publisher_id}/campaigns", headers=headers,
            params=params,
        )

    def list_publisher_statements(self, publisher_id, headers, params=None):
        return self._request(
            "GET", f"/publishers/{publisher_id}/statements", headers=headers,
            params=params,
        )

    # --- Channels ---
    def create_channel(self, payload, headers):
        return self._request("POST", "/channels", payload, headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/channels", headers=headers, params=params)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def publish_channel(self, channel_id, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/publish", {}, headers,
        )

    def suspend_channel(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/suspend", payload, headers,
        )

    def reinstate_channel(self, channel_id, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/reinstate", {}, headers,
        )

    def remove_channel(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/remove", payload, headers,
        )

    def set_channel_policy_hold(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/policy-hold", payload, headers,
        )

    def list_channel_versions(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/versions", headers=headers,
            params=params,
        )

    def list_channel_subscriptions(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/subscriptions", headers=headers,
            params=params,
        )

    def list_channel_ad_slot_grants(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/ad-slot-grants", headers=headers,
            params=params,
        )

    def list_channel_campaigns(self, channel_id, headers, params=None):
        return self._request(
            "GET", f"/channels/{channel_id}/campaigns", headers=headers,
            params=params,
        )

    # --- Channel versions ---
    def create_channel_version(self, channel_id, payload, headers):
        return self._request(
            "POST", f"/channels/{channel_id}/versions", payload, headers,
        )

    def get_channel_version(self, version_id, headers):
        return self._request(
            "GET", f"/channel-versions/{version_id}", headers=headers,
        )

    def review_channel_version(self, version_id, headers):
        return self._request(
            "POST", f"/channel-versions/{version_id}/review", {}, headers,
        )

    def decide_channel_version(self, version_id, payload, headers):
        return self._request(
            "POST", f"/channel-versions/{version_id}/decide", payload, headers,
        )

    # --- Viewer accounts ---
    def create_viewer_account(self, payload, headers):
        return self._request("POST", "/viewer-accounts", payload, headers)

    def get_viewer_account(self, viewer_id, headers):
        return self._request(
            "GET", f"/viewer-accounts/{viewer_id}", headers=headers,
        )

    def update_viewer_privacy(self, viewer_id, payload, headers):
        return self._request(
            "PATCH", f"/viewer-accounts/{viewer_id}/privacy", payload, headers,
        )

    def list_viewer_subscriptions(self, viewer_id, headers, params=None):
        return self._request(
            "GET", f"/viewer-accounts/{viewer_id}/subscriptions",
            headers=headers, params=params,
        )

    def list_viewer_device_units(self, viewer_id, headers, params=None):
        return self._request(
            "GET", f"/viewer-accounts/{viewer_id}/device-units",
            headers=headers, params=params,
        )

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request(
            "GET", "/subscriptions", headers=headers, params=params,
        )

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers,
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers,
        )

    def refund_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/refund", {}, headers,
        )

    # --- Ad slot grants ---
    def create_ad_slot_grant(self, payload, headers):
        return self._request("POST", "/ad-slot-grants", payload, headers)

    def list_ad_slot_grants(self, headers, params=None):
        return self._request(
            "GET", "/ad-slot-grants", headers=headers, params=params,
        )

    def get_ad_slot_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/ad-slot-grants/{grant_id}", headers=headers,
        )

    def record_ad_slot_revenue(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/ad-slot-grants/{grant_id}/record-revenue", payload,
            headers,
        )

    def resplit_ad_slot_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/ad-slot-grants/{grant_id}/resplit", payload, headers,
        )

    def close_ad_slot_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/ad-slot-grants/{grant_id}/close", {}, headers,
        )

    # --- Ad campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def schedule_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/schedule", {}, headers,
        )

    def start_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/start", {}, headers,
        )

    def pause_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/pause", {}, headers,
        )

    def resume_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/resume", {}, headers,
        )

    def cancel_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/cancel", {}, headers,
        )

    def record_campaign_impressions(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/impressions", payload, headers,
        )

    def list_campaign_placement_bookings(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/campaigns/{campaign_id}/placement-bookings",
            headers=headers, params=params,
        )

    # --- Placement bookings ---
    def create_placement_booking(self, payload, headers):
        return self._request("POST", "/placement-bookings", payload, headers)

    def list_placement_bookings(self, headers, params=None):
        return self._request(
            "GET", "/placement-bookings", headers=headers, params=params,
        )

    def get_placement_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/placement-bookings/{booking_id}", headers=headers,
        )

    def confirm_placement_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/placement-bookings/{booking_id}/confirm", {}, headers,
        )

    def release_placement_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/placement-bookings/{booking_id}/release", {}, headers,
        )

    # --- TV manufacturers ---
    def create_manufacturer(self, payload, headers):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id, headers):
        return self._request(
            "GET", f"/manufacturers/{manufacturer_id}", headers=headers,
        )

    def suspend_manufacturer(self, manufacturer_id, payload, headers):
        return self._request(
            "POST", f"/manufacturers/{manufacturer_id}/suspend", payload,
            headers,
        )

    def reinstate_manufacturer(self, manufacturer_id, headers):
        return self._request(
            "POST", f"/manufacturers/{manufacturer_id}/reinstate", {}, headers,
        )

    def list_manufacturer_device_models(self, manufacturer_id, headers, params=None):
        return self._request(
            "GET", f"/manufacturers/{manufacturer_id}/device-models",
            headers=headers, params=params,
        )

    def list_manufacturer_lab_bookings(self, manufacturer_id, headers, params=None):
        return self._request(
            "GET", f"/manufacturers/{manufacturer_id}/lab-bookings",
            headers=headers, params=params,
        )

    # --- Device models ---
    def create_device_model(self, payload, headers):
        return self._request("POST", "/device-models", payload, headers)

    def get_device_model(self, model_id, headers):
        return self._request("GET", f"/device-models/{model_id}", headers=headers)

    def create_lab_booking(self, model_id, payload, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/lab-bookings", payload, headers,
        )

    def list_device_model_lab_bookings(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/device-models/{model_id}/lab-bookings", headers=headers,
            params=params,
        )

    def certify_device_model(self, model_id, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/certify", {}, headers,
        )

    def reject_device_model(self, model_id, payload, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/reject", payload, headers,
        )

    def resubmit_device_model(self, model_id, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/resubmit", {}, headers,
        )

    def decertify_device_model(self, model_id, payload, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/decertify", payload, headers,
        )

    def refresh_device_model_compliance(self, model_id, headers):
        return self._request(
            "POST", f"/device-models/{model_id}/refresh-compliance", {}, headers,
        )

    def list_device_model_device_units(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/device-models/{model_id}/device-units", headers=headers,
            params=params,
        )

    # --- OS updates ---
    def create_os_update(self, payload, headers):
        return self._request("POST", "/os-updates", payload, headers)

    def list_os_updates(self, headers, params=None):
        return self._request("GET", "/os-updates", headers=headers, params=params)

    def get_os_update(self, update_id, headers):
        return self._request("GET", f"/os-updates/{update_id}", headers=headers)

    def withdraw_os_update(self, update_id, headers):
        return self._request(
            "POST", f"/os-updates/{update_id}/withdraw", {}, headers,
        )

    # --- Device units ---
    def create_device_unit(self, payload, headers):
        return self._request("POST", "/device-units", payload, headers)

    def list_device_units(self, headers, params=None):
        return self._request(
            "GET", "/device-units", headers=headers, params=params,
        )

    def get_device_unit(self, unit_id, headers):
        return self._request("GET", f"/device-units/{unit_id}", headers=headers)

    def sell_device_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/sell", {}, headers,
        )

    def activate_device_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/activate", {}, headers,
        )

    def deactivate_device_unit(self, unit_id, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/deactivate", {}, headers,
        )

    def apply_os_update(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/apply-os-update", payload, headers,
        )

    def record_device_ad_revenue(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/record-ad-revenue", payload,
            headers,
        )

    def accrue_straight_line(self, unit_id, headers):
        return self._request(
            "POST", f"/device-units/{unit_id}/accrue-straight-line", {}, headers,
        )

    # --- Revenue statements ---
    def generate_statements(self, payload, headers):
        return self._request("POST", "/statements/generate", payload, headers)

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", "/statements", headers=headers, params=params,
        )

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/statements/{statement_id}", headers=headers,
        )

    def finalize_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/finalize", {}, headers,
        )

    def settle_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/settle", {}, headers,
        )

    def create_statement_dispute(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/disputes", payload, headers,
        )

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def triage_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/triage", {}, headers,
        )

    def request_dispute_evidence(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/request-evidence", {}, headers,
        )

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/decide", payload, headers,
        )

    def appeal_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/appeal", payload, headers,
        )

    def close_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/close", {}, headers,
        )


api_client = ApiClient()
