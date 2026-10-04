"""API client: one method per endpoint in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Channel ─────────────────────────────────────
    def create_channel(self, payload, headers):
        return self._request("POST", "/api/channels", payload, headers)

    def list_channels(self, headers, params=None):
        return self._request("GET", "/api/channels", headers=headers, params=params)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/api/channels/{channel_id}", headers=headers)

    def patch_channel(self, channel_id, payload, headers):
        return self._request("PATCH", f"/api/channels/{channel_id}", payload, headers)

    # ─── Monetization application & review ───────────
    def apply_monetization(self, channel_id, headers):
        return self._request("POST", f"/api/channels/{channel_id}/monetization-applications",
                             {}, headers)

    def review_monetization(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/monetization-review",
                             payload, headers)

    def get_review_queue(self, headers, params=None):
        return self._request("GET", "/api/review-queue", headers=headers, params=params)

    # ─── Content item ────────────────────────────────
    def create_content_item(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/content-items",
                             payload, headers)

    def list_channel_content_items(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/content-items",
                             headers=headers, params=params)

    def list_content_items(self, headers, params=None):
        return self._request("GET", "/api/content-items", headers=headers, params=params)

    def get_content_item(self, item_id, headers):
        return self._request("GET", f"/api/content-items/{item_id}", headers=headers)

    def request_review(self, channel_id, item_id, headers):
        return self._request(
            "POST", f"/api/channels/{channel_id}/content-items/{item_id}/requests-review",
            {}, headers)

    def appeal_classification(self, channel_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/api/channels/{channel_id}/content-items/{item_id}/classification-appeals",
            payload, headers)

    def classify_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/content-items/{item_id}/classifications",
                             payload, headers)

    def settle_item(self, item_id, headers):
        return self._request("POST", f"/api/content-items/{item_id}/settle", {}, headers)

    def set_revenue_lock(self, item_id, payload, headers):
        return self._request("PATCH", f"/api/content-items/{item_id}/revenue-lock",
                             payload, headers)

    def list_ad_reviews(self, item_id, headers, params=None):
        return self._request("GET", f"/api/content-items/{item_id}/ad-reviews",
                             headers=headers, params=params)

    # ─── Reference file ──────────────────────────────
    def create_reference_file(self, payload, headers):
        return self._request("POST", "/api/reference-files", payload, headers)

    def list_reference_files(self, headers, params=None):
        return self._request("GET", "/api/reference-files", headers=headers, params=params)

    def get_reference_file(self, reference_file_id, headers):
        return self._request("GET", f"/api/reference-files/{reference_file_id}",
                             headers=headers)

    # ─── Claim ───────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def dispute_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/dispute", payload, headers)

    def list_claim_disputes(self, claim_id, headers, params=None):
        return self._request("GET", f"/api/claims/{claim_id}/disputes",
                             headers=headers, params=params)

    def resolve_dispute(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/dispute/resolve",
                             payload, headers)

    def file_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/appeals", payload, headers)

    def list_claim_appeals(self, claim_id, headers, params=None):
        return self._request("GET", f"/api/claims/{claim_id}/appeals",
                             headers=headers, params=params)

    def decide_appeal(self, claim_id, appeal_id, payload, headers):
        return self._request("POST",
                             f"/api/claims/{claim_id}/appeals/{appeal_id}/decide",
                             payload, headers)

    def file_counter_notification(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/counter-notifications",
                             payload, headers)

    def take_down_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/takedown", {}, headers)

    def list_claim_copyright_strikes(self, claim_id, headers, params=None):
        return self._request("GET", f"/api/claims/{claim_id}/copyright-strikes",
                             headers=headers, params=params)

    # ─── Copyright strike ────────────────────────────
    def list_channel_copyright_strikes(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/copyright-strikes",
                             headers=headers, params=params)

    def list_item_copyright_strikes(self, item_id, headers, params=None):
        return self._request("GET", f"/api/content-items/{item_id}/copyright-strikes",
                             headers=headers, params=params)

    # ─── Channel strike ──────────────────────────────
    def issue_strike(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/strikes",
                             payload, headers)

    def list_channel_strikes(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/strikes",
                             headers=headers, params=params)

    # ─── Revenue ─────────────────────────────────────
    def create_revenue_event(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/revenue-events",
                             payload, headers)

    def list_channel_revenue_events(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/revenue-events",
                             headers=headers, params=params)

    def list_item_revenue_events(self, item_id, headers, params=None):
        return self._request("GET", f"/api/content-items/{item_id}/revenue-events",
                             headers=headers, params=params)

    def create_revenue_routing(self, payload, headers):
        return self._request("POST", "/api/revenue-routings", payload, headers)

    def list_item_routings(self, item_id, headers, params=None):
        return self._request("GET", f"/api/content-items/{item_id}/revenue-routings",
                             headers=headers, params=params)

    def list_claim_routings(self, claim_id, headers, params=None):
        return self._request("GET", f"/api/claims/{claim_id}/revenue-routings",
                             headers=headers, params=params)

    def list_channel_routings(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/revenue-routings",
                             headers=headers, params=params)

    # ─── Membership & payout ─────────────────────────
    def create_membership_schedule(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/membership-schedules",
                             payload, headers)

    def list_membership_schedules(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/membership-schedules",
                             headers=headers, params=params)

    def create_membership(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/memberships",
                             payload, headers)

    def list_memberships(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/memberships",
                             headers=headers, params=params)

    def run_member_payouts(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/member-payout-runs",
                             payload, headers)

    def lock_payout(self, channel_id, payload, headers):
        return self._request("POST", f"/api/channels/{channel_id}/payouts/lock",
                             payload, headers)

    def release_payout(self, channel_id, batch_id, payload, headers):
        return self._request("POST",
                             f"/api/channels/{channel_id}/payouts/{batch_id}/release",
                             payload, headers)

    def get_payout(self, batch_id, headers):
        return self._request("GET", f"/api/payouts/{batch_id}", headers=headers)

    def get_payout_route_batch(self, batch_id, headers):
        return self._request("GET", f"/api/payouts/{batch_id}/route-batch", headers=headers)

    def list_channel_payouts(self, channel_id, headers, params=None):
        return self._request("GET", f"/api/channels/{channel_id}/payouts",
                             headers=headers, params=params)

    def get_channel_payout(self, channel_id, batch_id, headers):
        return self._request("GET", f"/api/channels/{channel_id}/payouts/{batch_id}",
                             headers=headers)


api_client = ApiClient()