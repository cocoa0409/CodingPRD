"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Advertiser accounts ---
    def create_advertiser_account(self, payload, headers):
        return self._request("POST", "/advertiser-accounts", payload, headers)

    def get_advertiser_account(self, account_id, headers):
        return self._request("GET", f"/advertiser-accounts/{account_id}", headers=headers)

    def suspend_advertiser_account(self, account_id, payload, headers):
        return self._request("POST", f"/advertiser-accounts/{account_id}/suspend", payload, headers)

    # --- Identity verifications ---
    def create_identity_verification(self, account_id, payload, headers):
        return self._request(
            "POST", f"/advertiser-accounts/{account_id}/identity-verifications", payload, headers
        )

    def list_identity_verifications(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/advertiser-accounts/{account_id}/identity-verifications", headers=headers, params=params
        )

    def decide_identity_verification(self, verification_id, payload, headers):
        return self._request(
            "POST", f"/identity-verifications/{verification_id}/decide", payload, headers
        )

    # --- Appeals ---
    def create_appeal(self, account_id, payload, headers):
        return self._request("POST", f"/advertiser-accounts/{account_id}/appeals", payload, headers)

    def list_appeals(self, account_id, headers, params=None):
        return self._request("GET", f"/advertiser-accounts/{account_id}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # --- Billing ---
    def create_billing_profile(self, account_id, payload, headers):
        return self._request("POST", f"/advertiser-accounts/{account_id}/billing-profile", payload, headers)

    def get_account_billing_profile(self, account_id, headers):
        return self._request("GET", f"/advertiser-accounts/{account_id}/billing-profile", headers=headers)

    def get_billing_profile(self, billing_profile_id, headers):
        return self._request("GET", f"/billing-profiles/{billing_profile_id}", headers=headers)

    def close_month(self, billing_profile_id, payload, headers):
        return self._request("POST", f"/billing-profiles/{billing_profile_id}/close-month", payload, headers)

    def list_invoices(self, billing_profile_id, headers, params=None):
        return self._request("GET", f"/billing-profiles/{billing_profile_id}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    # --- Campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def update_campaign(self, campaign_id, payload, headers):
        return self._request("PUT", f"/campaigns/{campaign_id}", payload, headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/activate", {}, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/pause", {}, headers)

    def list_daily_spend_records(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/campaigns/{campaign_id}/daily-spend-records", headers=headers, params=params
        )

    # --- Ad groups ---
    def create_ad_group(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/ad-groups", payload, headers)

    def list_ad_groups(self, campaign_id, headers, params=None):
        return self._request("GET", f"/campaigns/{campaign_id}/ad-groups", headers=headers, params=params)

    def get_ad_group(self, ad_group_id, headers):
        return self._request("GET", f"/ad-groups/{ad_group_id}", headers=headers)

    # --- Ads ---
    def create_ad(self, ad_group_id, payload, headers):
        return self._request("POST", f"/ad-groups/{ad_group_id}/ads", payload, headers)

    def list_ads(self, ad_group_id, headers, params=None):
        return self._request("GET", f"/ad-groups/{ad_group_id}/ads", headers=headers, params=params)

    def get_ad(self, ad_id, headers):
        return self._request("GET", f"/ads/{ad_id}", headers=headers)

    def update_ad(self, ad_id, payload, headers):
        return self._request("PUT", f"/ads/{ad_id}", payload, headers)

    def submit_ad_review(self, ad_id, headers):
        return self._request("POST", f"/ads/{ad_id}/submit-review", {}, headers)

    def list_policy_reviews(self, ad_id, headers, params=None):
        return self._request("GET", f"/ads/{ad_id}/policy-reviews", headers=headers, params=params)

    def list_ad_auction_events(self, ad_id, headers, params=None):
        return self._request("GET", f"/ads/{ad_id}/auction-events", headers=headers, params=params)

    # --- Policy reviews ---
    def decide_policy_review(self, review_id, payload, headers):
        return self._request("POST", f"/policy-reviews/{review_id}/decide", payload, headers)

    # --- Keywords ---
    def create_keyword(self, ad_group_id, payload, headers):
        return self._request("POST", f"/ad-groups/{ad_group_id}/keywords", payload, headers)

    def list_keywords(self, ad_group_id, headers, params=None):
        return self._request("GET", f"/ad-groups/{ad_group_id}/keywords", headers=headers, params=params)

    # --- Auctions ---
    def run_auction(self, payload, headers):
        return self._request("POST", "/auctions", payload, headers)

    def get_auction_event(self, auction_event_id, headers):
        return self._request("GET", f"/auction-events/{auction_event_id}", headers=headers)

    def flag_auction_event_invalid(self, auction_event_id, headers):
        return self._request("POST", f"/auction-events/{auction_event_id}/flag-invalid", {}, headers)


api_client = ApiClient()
