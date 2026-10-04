"""API client: one method per endpoint declared in the PRD.

All methods delegate to the framework's `GenericApiClient._request()` and
return the raw `requests.Response` so callers can assert status codes.
Paths are the PRD's own routes, mounted under `/api`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Clock ────────────────────────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ── Platform account ─────────────────────────────────────────────────
    def create_platform_account(self, payload, headers):
        return self._request("POST", "/api/platform-accounts", payload, headers)

    def get_platform_account(self, account_id, headers):
        return self._request("GET", f"/api/platform-accounts/{account_id}", headers=headers)

    # ── Artists ──────────────────────────────────────────────────────────
    def create_artist(self, payload, headers):
        return self._request("POST", "/api/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/api/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/api/artists", headers=headers, params=params)

    # ── Investors ────────────────────────────────────────────────────────
    def create_investor(self, payload, headers):
        return self._request("POST", "/api/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/api/investors/{investor_id}", headers=headers)

    def list_investors(self, headers, params=None):
        return self._request("GET", "/api/investors", headers=headers, params=params)

    def revoke_suitability(self, investor_id, payload, headers):
        return self._request("POST", f"/api/investors/{investor_id}/revoke-suitability",
                             payload, headers)

    # ── Artworks ─────────────────────────────────────────────────────────
    def create_artwork(self, payload, headers):
        return self._request("POST", "/api/artworks", payload, headers)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/api/artworks/{artwork_id}", headers=headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/api/artworks", headers=headers, params=params)

    def create_asset_report(self, artwork_id, payload, headers):
        return self._request("POST", f"/api/artworks/{artwork_id}/asset-reports",
                             payload, headers)

    def list_asset_reports(self, artwork_id, headers, params=None):
        return self._request("GET", f"/api/artworks/{artwork_id}/asset-reports",
                             headers=headers, params=params)

    def create_appraisal(self, artwork_id, payload, headers):
        return self._request("POST", f"/api/artworks/{artwork_id}/appraisals",
                             payload, headers)

    def list_appraisals(self, artwork_id, headers, params=None):
        return self._request("GET", f"/api/artworks/{artwork_id}/appraisals",
                             headers=headers, params=params)

    # ── Offerings ────────────────────────────────────────────────────────
    def create_offering(self, artwork_id, payload, headers):
        return self._request("POST", f"/api/artworks/{artwork_id}/offerings",
                             payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/api/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/api/offerings", headers=headers, params=params)

    def file_qualification(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/qualification-filing",
                             payload, headers)

    def allocate(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/allocate",
                             payload, headers)

    def waitlist_promotion(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/waitlist-promotion",
                             payload, headers)

    def waitlist_demotion(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/waitlist-demotion",
                             payload, headers)

    def withdraw_offering(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/withdraw",
                             payload, headers)

    def abandon_offering(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/abandon",
                             payload, headers)

    def get_share_ledger(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/share-ledger",
                             headers=headers, params=params)

    def get_valuation(self, offering_id, headers):
        return self._request("GET", f"/api/offerings/{offering_id}/valuation",
                             headers=headers)

    def create_cost_lot(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/cost-lots",
                             payload, headers)

    def list_cost_lots(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/cost-lots",
                             headers=headers, params=params)

    def accrue_fees(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/accrue-fees",
                             payload, headers)

    def list_fee_accruals(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/fee-accruals",
                             headers=headers, params=params)

    def create_offering_report(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/reports",
                             payload, headers)

    def list_offering_reports(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/reports",
                             headers=headers, params=params)

    def reconcile_cadence(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/reconcile-cadence",
                             payload, headers)

    def insurer_quote(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/insurer-quote",
                             payload, headers)

    def list_offering_subscriptions(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/subscriptions",
                             headers=headers, params=params)

    def create_holding_decision(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/holding-decisions",
                             payload, headers)

    def list_holding_decisions(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/holding-decisions",
                             headers=headers, params=params)

    def create_custody_record(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/custody-records",
                             payload, headers)

    def list_custody_records(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/custody-records",
                             headers=headers, params=params)

    def create_insurance_policy(self, offering_id, payload, headers):
        return self._request("POST", f"/api/offerings/{offering_id}/insurance-policies",
                             payload, headers)

    def list_insurance_policies(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/insurance-policies",
                             headers=headers, params=params)

    def pay_distribution(self, offering_id, distribution_id, payload, headers):
        return self._request(
            "POST",
            f"/api/offerings/{offering_id}/distributions/{distribution_id}/pay",
            payload, headers)

    def list_distributions(self, offering_id, headers, params=None):
        return self._request("GET", f"/api/offerings/{offering_id}/distributions",
                             headers=headers, params=params)

    # ── Subscriptions ────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def screen_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/screen",
                             payload, headers)

    def collect_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/collect",
                             payload, headers)

    def withdraw_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/withdraw",
                             payload, headers)

    # ── Custody records ──────────────────────────────────────────────────
    def get_custody_record(self, custody_id, headers):
        return self._request("GET", f"/api/custody-records/{custody_id}", headers=headers)

    def receive_custody(self, custody_id, payload, headers):
        return self._request("POST", f"/api/custody-records/{custody_id}/receive",
                             payload, headers)

    def release_custody(self, custody_id, payload, headers):
        return self._request("POST", f"/api/custody-records/{custody_id}/release",
                             payload, headers)

    # ── Insurance policies ───────────────────────────────────────────────
    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/api/insurance-policies/{policy_id}", headers=headers)

    def bind_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/api/insurance-policies/{policy_id}/bind",
                             payload, headers)

    def lapse_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/api/insurance-policies/{policy_id}/lapse",
                             payload, headers)

    # ── Holding decisions ────────────────────────────────────────────────
    def get_holding_decision(self, decision_id, headers):
        return self._request("GET", f"/api/holding-decisions/{decision_id}", headers=headers)

    def approve_decision(self, decision_id, payload, headers):
        return self._request("PATCH", f"/api/holding-decisions/{decision_id}/approve",
                             payload, headers)

    def reject_decision(self, decision_id, payload, headers):
        return self._request("PATCH", f"/api/holding-decisions/{decision_id}/reject",
                             payload, headers)

    def revise_decision(self, decision_id, payload, headers):
        return self._request("PATCH", f"/api/holding-decisions/{decision_id}/revise",
                             payload, headers)

    def execute_sale(self, decision_id, payload, headers):
        return self._request("POST", f"/api/holdings/{decision_id}/execute",
                             payload, headers)

    # ── Transfer orders ──────────────────────────────────────────────────
    def create_transfer_order(self, payload, headers):
        return self._request("POST", "/api/transfer-orders", payload, headers)

    def list_transfer_orders(self, headers, params=None):
        return self._request("GET", "/api/transfer-orders", headers=headers, params=params)

    def get_transfer_order(self, order_id, headers):
        return self._request("GET", f"/api/transfer-orders/{order_id}", headers=headers)

    def accept_transfer_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/transfer-orders/{order_id}/accept",
                             payload, headers)

    def repost_transfer_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/transfer-orders/{order_id}/repost",
                             payload, headers)

    def approve_transfer(self, order_id, payload, headers):
        return self._request("POST", f"/api/transfer-orders/{order_id}/approve-transfer",
                             payload, headers)

    def cancel_transfer_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/transfer-orders/{order_id}/cancel",
                             payload, headers)


api_client = ApiClient()