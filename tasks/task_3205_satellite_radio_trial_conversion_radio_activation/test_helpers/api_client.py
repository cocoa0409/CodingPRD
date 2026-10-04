"""API client: one method per endpoint of the PRD endpoint table."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock & ops -------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/api/v1/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_renewals(self, headers):
        return self._request("POST", "/api/v1/_billing/run_renewals", {}, headers)

    def dispatch_signals(self, headers):
        return self._request("POST", "/api/v1/_signals/dispatch", {}, headers)

    # --- reference data ----------------------------------------------------
    def create_automaker(self, payload, headers):
        return self._request("POST", "/api/v1/automakers", payload, headers)

    def get_automaker(self, automaker_id, headers):
        return self._request("GET", f"/api/v1/automakers/{automaker_id}", headers=headers)

    def create_dealer(self, payload, headers):
        return self._request("POST", "/api/v1/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/api/v1/dealers/{dealer_id}", headers=headers)

    def enroll_used_program(self, dealer_id, headers):
        return self._request(
            "POST", f"/api/v1/dealers/{dealer_id}/enroll-used-program", {}, headers
        )

    def create_customer(self, payload, headers=None):
        return self._request("POST", "/api/v1/customers", payload, headers or {})

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/v1/customers/{customer_id}", headers=headers)

    def list_customer_subscriptions(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/customers/{customer_id}/api/v1/subscriptions",
            headers=headers, params=params,
        )

    def list_customer_vehicles(self, customer_id, headers):
        return self._request(
            "GET", f"/api/v1/customers/{customer_id}/vehicles", headers=headers
        )

    def list_customer_redemptions(self, customer_id, headers):
        return self._request(
            "GET", f"/api/v1/customers/{customer_id}/redemptions", headers=headers
        )

    def create_package_tier(self, payload, headers):
        return self._request("POST", "/api/v1/package-tiers", payload, headers)

    def get_package_tier(self, tier_id, headers):
        return self._request("GET", f"/api/v1/package-tiers/{tier_id}", headers=headers)

    def list_tier_plans(self, tier_id, headers):
        return self._request(
            "GET", f"/api/v1/package-tiers/{tier_id}/subscription-plans",
            headers=headers,
        )

    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/api/v1/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/api/v1/subscription-plans/{plan_id}", headers=headers
        )

    def list_plan_subscriptions(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/subscription-plans/{plan_id}/subscriptions",
            headers=headers, params=params,
        )

    # --- vehicles & radios --------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/v1/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_radios(self, vehicle_id, headers):
        return self._request(
            "GET", f"/api/v1/vehicles/{vehicle_id}/api/v1/radios", headers=headers
        )

    def transfer_ownership(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/vehicles/{vehicle_id}/transfer_ownership",
            payload, headers,
        )

    def create_radio(self, payload, headers):
        return self._request("POST", "/api/v1/radios", payload, headers)

    def get_radio(self, radio_id, headers):
        return self._request("GET", f"/api/v1/radios/{radio_id}", headers=headers)

    def list_radio_subscriptions(self, radio_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/radios/{radio_id}/api/v1/subscriptions",
            headers=headers, params=params,
        )

    def list_radio_signal_commands(self, radio_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/radios/{radio_id}/api/v1/signal-commands",
            headers=headers, params=params,
        )

    # --- trial provisioning --------------------------------------------------
    def provision_trial(self, radio_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/radios/{radio_id}/trials", payload, headers
        )

    def submit_data_feed(self, automaker_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/automakers/{automaker_id}/data-feeds", payload, headers
        )

    def used_reactivation(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/dealers/{dealer_id}/used-reactivations", payload, headers
        )

    # --- subscription lifecycle ---------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/v1/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/api/v1/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscription_ledger(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/subscriptions/{subscription_id}/ledger",
            headers=headers, params=params,
        )

    def list_subscription_disclosures(self, subscription_id, headers):
        return self._request(
            "GET", f"/api/v1/subscriptions/{subscription_id}/disclosures",
            headers=headers,
        )

    def suspend_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/suspend", {}, headers
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/resume", {}, headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/cancel", payload, headers
        )

    def accept_save_offer(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/save-offers/accept",
            payload, headers,
        )

    def send_disclosure(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/disclosures/send",
            payload, headers,
        )

    def acknowledge_disclosure(self, subscription_id, disclosure_id, headers):
        return self._request(
            "POST",
            f"/api/v1/subscriptions/{subscription_id}/disclosures/{disclosure_id}/acknowledge",
            {}, headers,
        )

    def requeue_signal(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/signals/requeue",
            payload, headers,
        )

    def list_subscription_signal_commands(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/subscriptions/{subscription_id}/signal-commands",
            headers=headers, params=params,
        )

    def list_subscription_redemptions(self, subscription_id, headers):
        return self._request(
            "GET", f"/api/v1/subscriptions/{subscription_id}/redemptions",
            headers=headers,
        )

    # --- signals --------------------------------------------------------------
    def ack_signal(self, signal_id, headers):
        return self._request(
            "POST", f"/api/v1/signal-commands/{signal_id}/ack", {}, headers
        )

    def fail_signal(self, signal_id, headers):
        return self._request(
            "POST", f"/api/v1/signal-commands/{signal_id}/fail", {}, headers
        )

    def get_signal_command(self, signal_id, headers):
        return self._request(
            "GET", f"/api/v1/signal-commands/{signal_id}", headers=headers
        )

    # --- offers -----------------------------------------------------------------
    def create_offer_campaign(self, payload, headers):
        return self._request("POST", "/api/v1/offer-campaigns", payload, headers)

    def get_offer_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/api/v1/offer-campaigns/{campaign_id}", headers=headers
        )

    def list_campaign_steps(self, campaign_id, headers):
        return self._request(
            "GET", f"/api/v1/offer-campaigns/{campaign_id}/steps", headers=headers
        )

    def list_campaign_redemptions(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/offer-campaigns/{campaign_id}/redemptions",
            headers=headers, params=params,
        )

    def add_offer_step(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/offer-campaigns/{campaign_id}/steps", payload, headers
        )

    def activate_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/api/v1/offer-campaigns/{campaign_id}/activate", {}, headers
        )

    def pause_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/api/v1/offer-campaigns/{campaign_id}/pause", {}, headers
        )

    def archive_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/api/v1/offer-campaigns/{campaign_id}/archive", {}, headers
        )

    def redeem_offer(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/offer-campaigns/{campaign_id}/redeem", payload, headers
        )

    def get_offer_step(self, step_id, headers):
        return self._request("GET", f"/api/v1/offer-steps/{step_id}", headers=headers)

    def list_offer_steps(self, headers, params=None):
        return self._request("GET", "/api/v1/offer-steps", headers=headers, params=params)

    def list_offer_step_redemptions(self, step_id, headers):
        return self._request(
            "GET", f"/api/v1/offer-steps/{step_id}/redemptions", headers=headers
        )

    def list_automaker_vehicles(self, automaker_id, headers):
        return self._request(
            "GET", f"/api/v1/automakers/{automaker_id}/vehicles", headers=headers
        )


api_client = ApiClient()
