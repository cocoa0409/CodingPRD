"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (test-driving) ------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/streaming/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- plans -------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/streaming/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/streaming/plans", headers=headers, params=params)

    def get_plan(self, plan_code, headers):
        return self._request("GET", f"/streaming/plans/{plan_code}", headers=headers)

    # ---- subscriber accounts ------------------------------------------------
    def create_subscriber_account(self, payload, headers):
        return self._request("POST", "/streaming/subscriber-accounts", payload, headers)

    def get_subscriber_account(self, account_id, headers):
        return self._request(
            "GET", f"/streaming/subscriber-accounts/{account_id}", headers=headers
        )

    def list_subscriber_accounts(self, headers, params=None):
        return self._request(
            "GET", "/streaming/subscriber-accounts", headers=headers, params=params
        )

    def suspend_account(self, account_id, headers):
        return self._request(
            "POST", f"/streaming/subscriber-accounts/{account_id}/suspend", {}, headers
        )

    def reactivate_account(self, account_id, headers):
        return self._request(
            "POST", f"/streaming/subscriber-accounts/{account_id}/reactivate", {}, headers
        )

    def close_account(self, account_id, headers):
        return self._request(
            "POST", f"/streaming/subscriber-accounts/{account_id}/close", {}, headers
        )

    # ---- service profiles ---------------------------------------------------
    def create_service_profile(self, account_id, payload, headers):
        return self._request(
            "POST", f"/streaming/subscriber-accounts/{account_id}/service-profiles",
            payload, headers,
        )

    def list_service_profiles(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/subscriber-accounts/{account_id}/service-profiles",
            headers=headers, params=params,
        )

    def get_service_profile(self, profile_id, headers):
        return self._request(
            "GET", f"/streaming/service-profiles/{profile_id}", headers=headers
        )

    def unlink_service_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/streaming/service-profiles/{profile_id}/unlink", {}, headers
        )

    def update_service_profile(self, profile_id, payload, headers):
        return self._request(
            "PATCH", f"/streaming/service-profiles/{profile_id}", payload, headers
        )

    # ---- watchlist -----------------------------------------------------------
    def add_watchlist_item(self, profile_id, payload, headers):
        return self._request(
            "POST", f"/streaming/service-profiles/{profile_id}/watchlist-items",
            payload, headers,
        )

    def list_watchlist_items(self, profile_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/service-profiles/{profile_id}/watchlist-items",
            headers=headers, params=params,
        )

    def delete_watchlist_item(self, profile_id, item_id, headers):
        return self._request(
            "DELETE",
            f"/streaming/service-profiles/{profile_id}/watchlist-items/{item_id}",
            headers=headers,
        )

    # ---- billing accounts -----------------------------------------------------
    def create_billing_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/streaming/subscriber-accounts/{account_id}/billing-accounts",
            payload, headers,
        )

    def list_billing_accounts(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/subscriber-accounts/{account_id}/billing-accounts",
            headers=headers, params=params,
        )

    def get_billing_account(self, billing_account_id, headers):
        return self._request(
            "GET", f"/streaming/billing-accounts/{billing_account_id}", headers=headers
        )

    # ---- subscriptions ----------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/streaming/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/streaming/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request(
            "GET", "/streaming/subscriptions", headers=headers, params=params
        )

    def plan_change(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/streaming/subscriptions/{subscription_id}/plan-change",
            payload, headers,
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/streaming/subscriptions/{subscription_id}/cancel",
            payload, headers,
        )

    def rescind_cancellation(self, subscription_id, headers):
        return self._request(
            "POST",
            f"/streaming/subscriptions/{subscription_id}/rescind-cancellation",
            {}, headers,
        )

    # ---- entitlements ------------------------------------------------------------
    def list_subscription_entitlements(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/subscriptions/{subscription_id}/entitlements",
            headers=headers, params=params,
        )

    def list_profile_entitlements(self, profile_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/service-profiles/{profile_id}/entitlements",
            headers=headers, params=params,
        )

    def get_entitlement(self, entitlement_id, headers):
        return self._request(
            "GET", f"/streaming/entitlements/{entitlement_id}", headers=headers
        )

    # ---- migrations ---------------------------------------------------------------
    def create_migration(self, payload, headers):
        return self._request("POST", "/streaming/migrations", payload, headers)

    def get_migration(self, migration_id, headers):
        return self._request(
            "GET", f"/streaming/migrations/{migration_id}", headers=headers
        )

    def list_migrations(self, headers, params=None):
        return self._request(
            "GET", "/streaming/migrations", headers=headers, params=params
        )

    def confirm_migration(self, migration_id, payload, headers):
        return self._request(
            "POST", f"/streaming/migrations/{migration_id}/confirm", payload, headers
        )

    def void_migration(self, migration_id, headers):
        return self._request(
            "POST", f"/streaming/migrations/{migration_id}/void", {}, headers
        )

    # ---- retention ------------------------------------------------------------------
    def create_retention_offer(self, payload, headers):
        return self._request("POST", "/streaming/retention-offers", payload, headers)

    def list_retention_offers(self, headers, params=None):
        return self._request(
            "GET", "/streaming/retention-offers", headers=headers, params=params
        )

    def get_retention_offer(self, offer_code, headers):
        return self._request(
            "GET", f"/streaming/retention-offers/{offer_code}", headers=headers
        )

    def redeem_retention_offer(self, subscription_id, payload, headers):
        return self._request(
            "POST",
            f"/streaming/subscriptions/{subscription_id}/retention-redemptions",
            payload, headers,
        )

    def list_subscription_redemptions(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/streaming/subscriptions/{subscription_id}/retention-redemptions",
            headers=headers, params=params,
        )

    def list_account_redemptions(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/streaming/subscriber-accounts/{account_id}/retention-redemptions",
            headers=headers, params=params,
        )

    # ---- invoices & revenue -----------------------------------------------------------
    def list_subscription_invoices(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/subscriptions/{subscription_id}/invoices",
            headers=headers, params=params,
        )

    def list_billing_account_invoices(self, billing_account_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/billing-accounts/{billing_account_id}/invoices",
            headers=headers, params=params,
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/streaming/invoices/{invoice_id}", headers=headers)

    def list_revenue_allocations(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/streaming/invoices/{invoice_id}/revenue-allocations",
            headers=headers, params=params,
        )

    def retry_payment(self, invoice_id, headers):
        return self._request(
            "POST", f"/streaming/invoices/{invoice_id}/retry-payment", {}, headers
        )

    def get_revenue_report(self, headers, params=None):
        return self._request(
            "GET", "/streaming/revenue-report", headers=headers, params=params
        )

    # ---- billing run (test-driving) ---------------------------------------------------
    def run_renewal(self, payload, headers):
        return self._request("POST", "/streaming/_billing/run_renewal", payload, headers)


api_client = ApiClient()
