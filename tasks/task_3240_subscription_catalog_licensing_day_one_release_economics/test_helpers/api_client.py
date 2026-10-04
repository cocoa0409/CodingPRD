"""API client: one method per operation in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_current_utc(self, current_utc, headers):
        return self._request("POST", "/catalog/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Publisher ---
    def create_publisher(self, payload, headers):
        return self._request("POST", "/catalog/publishers", payload, headers)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/catalog/publishers/{publisher_id}", headers=headers)

    # --- Title ---
    def create_title(self, payload, headers):
        return self._request("POST", "/catalog/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/catalog/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/catalog/titles", headers=headers, params=params)

    # --- Region ---
    def create_region(self, payload, headers):
        return self._request("POST", "/catalog/regions", payload, headers)

    def get_region(self, region_code, headers):
        return self._request("GET", f"/catalog/regions/{region_code}", headers=headers)

    # --- SubscriptionTier ---
    def create_tier(self, payload, headers):
        return self._request("POST", "/catalog/tiers", payload, headers)

    def get_tier(self, tier_code, headers):
        return self._request("GET", f"/catalog/tiers/{tier_code}", headers=headers)

    def get_tier_analytics(self, tier_code, headers):
        return self._request("GET", f"/catalog/tiers/{tier_code}/analytics", headers=headers)

    # --- LicensingDeal ---
    def create_licensing_deal(self, payload, headers):
        return self._request("POST", "/catalog/licensing-deals", payload, headers)

    def get_licensing_deal(self, deal_id, headers, params=None):
        return self._request("GET", f"/catalog/licensing-deals/{deal_id}",
                             headers=headers, params=params)

    def list_licensing_deals(self, headers, params=None):
        return self._request("GET", "/catalog/licensing-deals", headers=headers, params=params)

    def sign_licensing_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/catalog/licensing-deals/{deal_id}/sign", payload, headers)

    def renew_licensing_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/catalog/licensing-deals/{deal_id}/renew", payload, headers)

    # --- CatalogEntry ---
    def create_catalog_entry(self, payload, headers):
        return self._request("POST", "/catalog/catalog-entries", payload, headers)

    def get_catalog_entry(self, entry_id, headers):
        return self._request("GET", f"/catalog/catalog-entries/{entry_id}", headers=headers)

    def list_catalog_entries(self, headers, params=None):
        return self._request("GET", "/catalog/catalog-entries", headers=headers, params=params)

    def publish_catalog_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/catalog/catalog-entries/{entry_id}/publish",
                             payload if payload is not None else {}, headers)

    def announce_entry_removal(self, entry_id, headers, payload=None):
        return self._request("POST", f"/catalog/catalog-entries/{entry_id}/announce-removal",
                             payload if payload is not None else {}, headers)

    def cancel_entry_removal(self, entry_id, headers, payload=None):
        return self._request("POST", f"/catalog/catalog-entries/{entry_id}/cancel-removal",
                             payload if payload is not None else {}, headers)

    def retire_catalog_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/catalog/catalog-entries/{entry_id}/retire",
                             payload if payload is not None else {}, headers)

    # --- CatalogMaintenance ---
    def get_catalog_maintenance(self, maintenance_id, headers):
        return self._request("GET", f"/catalog/catalog-maintenances/{maintenance_id}",
                             headers=headers)

    def list_catalog_maintenances(self, headers, params=None):
        return self._request("GET", "/catalog/catalog-maintenances", headers=headers, params=params)

    # --- Subscriber ---
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/catalog/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/catalog/subscribers/{subscriber_id}", headers=headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/catalog/subscribers", headers=headers, params=params)

    # --- Subscription ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/catalog/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/catalog/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/catalog/subscriptions", headers=headers, params=params)

    def pay_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/catalog/subscriptions/{subscription_id}/pay",
                             payload if payload is not None else {}, headers)

    def cancel_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/catalog/subscriptions/{subscription_id}/cancel",
                             payload if payload is not None else {}, headers)

    def record_engagement_event(self, subscription_id, payload, headers):
        return self._request("POST", f"/catalog/subscriptions/{subscription_id}/engagement-events",
                             payload, headers)

    # --- EngagementEvent ---
    def get_engagement_event(self, event_id, headers):
        return self._request("GET", f"/catalog/engagement-events/{event_id}", headers=headers)

    def list_engagement_events(self, headers, params=None):
        return self._request("GET", "/catalog/engagement-events", headers=headers, params=params)

    # --- Entitlement ---
    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/catalog/entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/catalog/entitlements/{entitlement_id}", headers=headers)

    def revoke_entitlement(self, entitlement_id, headers, payload=None):
        return self._request("POST", f"/catalog/entitlements/{entitlement_id}/revoke",
                             payload if payload is not None else {}, headers)

    def restore_entitlement(self, entitlement_id, headers, payload=None):
        return self._request("POST", f"/catalog/entitlements/{entitlement_id}/restore",
                             payload if payload is not None else {}, headers)

    # --- Purchase ---
    def create_purchase(self, payload, headers):
        return self._request("POST", "/catalog/purchases", payload, headers)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/catalog/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/catalog/purchases", headers=headers, params=params)

    def reverse_purchase(self, purchase_id, headers, payload=None):
        return self._request("POST", f"/catalog/purchases/{purchase_id}/reverse",
                             payload if payload is not None else {}, headers)

    # --- AvailabilityProjection ---
    def create_availability_projection(self, payload, headers):
        return self._request("POST", "/catalog/availability-projections", payload, headers)

    def get_availability_projection(self, projection_id, headers):
        return self._request("GET", f"/catalog/availability-projections/{projection_id}",
                             headers=headers)

    def list_availability_projections(self, headers, params=None):
        return self._request("GET", "/catalog/availability-projections",
                             headers=headers, params=params)

    def finalize_availability_projection(self, projection_id, headers, payload=None):
        return self._request("POST", f"/catalog/availability-projections/{projection_id}/finalize",
                             payload if payload is not None else {}, headers)


api_client = ApiClient()