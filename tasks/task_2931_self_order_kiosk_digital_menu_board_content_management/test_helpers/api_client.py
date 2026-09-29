"""HTTP client: one method per declared endpoint, all under the /kiosk-ops prefix.

Every method returns the raw requests.Response so the caller decides which
validator to apply. The response envelope is unwrapped in exactly one place —
the framework validators (validate_success / validate_error / validate_paginated
/ get_success_data) — and never here.
"""

from typing import Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import JSON, Headers


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO-8601 UTC instant so sub-second width never matters.

    '2026-08-05T17:00:00Z', '2026-08-05T17:00:00.000Z' and
    '2026-08-05T17:00:00+00:00' all canonicalise to the same string.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except ValueError:
        return value


class KioskOpsClient(GenericApiClient):
    """Typed client for the Self-Order Kiosk Content Ops API."""

    # --- logical clock ------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            json={"current_utc": current_utc},
            headers=headers,
        )

    # --- price zones -------------------------------------------------------
    def create_price_zone(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/price-zones", json=payload, headers=headers)

    def list_price_zones(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/price-zones", headers=headers, params=params)

    def get_price_zone(self, price_zone_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/price-zones/{price_zone_id}", headers=headers)

    # --- store clusters ----------------------------------------------------
    def create_store_cluster(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/store-clusters", json=payload, headers=headers)

    def list_store_clusters(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/store-clusters", headers=headers, params=params)

    def get_store_cluster(self, cluster_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/store-clusters/{cluster_id}", headers=headers)

    # --- stores ------------------------------------------------------------
    def create_store(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/stores", json=payload, headers=headers)

    def list_stores(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/stores", headers=headers, params=params)

    def get_store(self, store_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/stores/{store_id}", headers=headers)

    def get_menu_projection(
        self, store_id: str, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/stores/{store_id}/menu-projection", headers=headers, params=params
        )

    # --- menu items --------------------------------------------------------
    def create_menu_item(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/menu-items", json=payload, headers=headers)

    def list_menu_items(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/menu-items/{menu_item_id}", headers=headers)

    def write_accessibility_copy(
        self, menu_item_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/menu-items/{menu_item_id}/accessibility-copy",
            json=payload,
            headers=headers,
        )

    # --- price change requests --------------------------------------------
    def create_price_change_request(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/price-change-requests", json=payload, headers=headers)

    def list_price_change_requests(
        self, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/price-change-requests", headers=headers, params=params)

    def get_price_change_request(self, request_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/price-change-requests/{request_id}", headers=headers)

    def price_change_request_action(
        self, request_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/price-change-requests/{request_id}/actions",
            json=payload,
            headers=headers,
        )

    # --- availability ------------------------------------------------------
    def create_item_availability(
        self, store_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/stores/{store_id}/item-availabilities", json=payload, headers=headers
        )

    def list_item_availabilities(
        self, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/item-availabilities", headers=headers, params=params)

    def get_item_availability(self, availability_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/item-availabilities/{availability_id}", headers=headers)

    def item_availability_action(
        self, availability_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/item-availabilities/{availability_id}/actions",
            json=payload,
            headers=headers,
        )

    # --- campaign versions -------------------------------------------------
    def create_campaign_version(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/campaign-versions", json=payload, headers=headers)

    def list_campaign_versions(
        self, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/campaign-versions", headers=headers, params=params)

    def get_campaign_version(self, version_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/campaign-versions/{version_id}", headers=headers)

    def campaign_version_action(
        self, version_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/campaign-versions/{version_id}/actions", json=payload, headers=headers
        )

    # --- upsell rules ------------------------------------------------------
    def create_upsell_rule(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/upsell-rules", json=payload, headers=headers)

    def list_upsell_rules(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/upsell-rules", headers=headers, params=params)

    def get_upsell_rule(self, rule_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/upsell-rules/{rule_id}", headers=headers)

    # --- content bundles ---------------------------------------------------
    def create_content_bundle(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/content-bundles", json=payload, headers=headers)

    def list_content_bundles(
        self, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/content-bundles", headers=headers, params=params)

    def get_content_bundle(self, bundle_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/content-bundles/{bundle_id}", headers=headers)

    def append_daypart_slot(
        self, bundle_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/content-bundles/{bundle_id}/daypart-slots", json=payload, headers=headers
        )

    def content_bundle_action(
        self, bundle_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/content-bundles/{bundle_id}/actions", json=payload, headers=headers
        )

    # --- devices -----------------------------------------------------------
    def register_device(self, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/devices", json=payload, headers=headers)

    def list_devices(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/devices", headers=headers, params=params)

    def get_device(self, device_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/devices/{device_id}", headers=headers)

    def send_heartbeat(self, device_id: str, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/devices/{device_id}/heartbeat", json=payload, headers=headers
        )

    def cache_sync(self, device_id: str, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/devices/{device_id}/cache-sync", json=payload, headers=headers
        )

    def payment_attestation(
        self, device_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/devices/{device_id}/payment-attestation", json=payload, headers=headers
        )

    def create_order(self, device_id: str, payload: JSON, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/devices/{device_id}/orders", json=payload, headers=headers)

    # --- order handoffs ----------------------------------------------------
    def list_order_handoffs(
        self, headers: Headers, params: Optional[JSON] = None
    ) -> requests.Response:
        return self.get(f"{API_PREFIX}/order-handoffs", headers=headers, params=params)

    def get_order_handoff(self, order_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/order-handoffs/{order_id}", headers=headers)

    def order_handoff_action(
        self, order_id: str, payload: JSON, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/order-handoffs/{order_id}/actions", json=payload, headers=headers
        )

    # --- audit trail -------------------------------------------------------
    def list_audit_events(self, headers: Headers, params: Optional[JSON] = None) -> requests.Response:
        return self.get(f"{API_PREFIX}/audit-events", headers=headers, params=params)
