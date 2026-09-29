"""Composite scenario builders and pytest fixtures.

The server is restarted before every test, so every builder here creates its
preconditions from an empty database through the declared endpoints only.
Setup calls use the lenient get_success_data helper; the strict validators are
reserved for the assertions a test actually makes.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import KioskOpsClient
from .constants import (
    ACTION_PUBLISH,
    ACTION_VALIDATE,
    AUDIT_RESULT_PASS,
    BURGER_BASE_CENTS,
    CATEGORY_DESSERT,
    CATEGORY_DRINK,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    COLA_BASE_CENTS,
    DEVICE_CODE_K001,
    DEVICE_KIOSK,
    FRIES_BASE_CENTS,
    LUNCH_CODE,
    PIE_BASE_CENTS,
    SKU_BURGER,
    SKU_COLA,
    SKU_FRIES,
    SKU_PIE,
    STORE_CODE_S001,
    ZONE_A_CODE,
)
from .test_users import (
    ADMIN,
    COMPLIANCE,
    CONTENT_MANAGER,
    make_device_agent_headers,
)
from .types import JSON


class World:
    """A thin scenario builder over the API: every method performs one call."""

    def __init__(self, api: KioskOpsClient) -> None:
        self.api = api

    # --- clock ----------------------------------------------------------
    def set_clock(self, current_utc: str) -> JSON:
        return get_success_data(self.api.set_clock(current_utc, ADMIN))

    # --- topology -------------------------------------------------------
    def zone(self, zone_code: str = ZONE_A_CODE, **kwargs: Any) -> JSON:
        payload = f.price_zone_payload(zone_code, **kwargs)
        return get_success_data(self.api.create_price_zone(payload, ADMIN))

    def cluster(self, cluster_code: str, parent_cluster_id: Optional[str] = None,
                **kwargs: Any) -> JSON:
        payload = f.store_cluster_payload(cluster_code, parent_cluster_id, **kwargs)
        return get_success_data(self.api.create_store_cluster(payload, ADMIN))

    def store(self, cluster_id: str, price_zone_id: str, store_code: str = STORE_CODE_S001,
              **kwargs: Any) -> JSON:
        payload = f.store_payload(cluster_id, price_zone_id, store_code, **kwargs)
        return get_success_data(self.api.create_store(payload, ADMIN))

    def get_store(self, store_id: str, headers: Optional[JSON] = None) -> JSON:
        return get_success_data(self.api.get_store(store_id, headers or ADMIN))

    # --- catalogue ------------------------------------------------------
    def item(self, sku: str, category: str = CATEGORY_ENTREE,
             base_price_cents: int = BURGER_BASE_CENTS, **kwargs: Any) -> JSON:
        payload = f.menu_item_payload(sku, category=category,
                                      base_price_cents=base_price_cents, **kwargs)
        return get_success_data(self.api.create_menu_item(payload, CONTENT_MANAGER))

    def get_item(self, menu_item_id: str) -> JSON:
        return get_success_data(self.api.get_menu_item(menu_item_id, CONTENT_MANAGER))

    def accessibility_copy(self, menu_item_id: str, expected_menu_item_version: int,
                           screen_reader_text: str, contrast_ratio: float) -> JSON:
        payload = f.accessibility_copy_payload(expected_menu_item_version,
                                               screen_reader_text, contrast_ratio)
        return get_success_data(
            self.api.write_accessibility_copy(menu_item_id, payload, CONTENT_MANAGER)
        )

    # --- bundles --------------------------------------------------------
    def bundle(self, cluster_id: str, **kwargs: Any) -> JSON:
        payload = f.content_bundle_payload(cluster_id, **kwargs)
        return get_success_data(self.api.create_content_bundle(payload, CONTENT_MANAGER))

    def slot(self, bundle_id: str, expected_content_bundle_version: int, **kwargs: Any) -> JSON:
        payload = f.daypart_slot_payload(expected_content_bundle_version, **kwargs)
        return get_success_data(self.api.append_daypart_slot(bundle_id, payload, CONTENT_MANAGER))

    def audit_pass(self, bundle_id: str, audit_result: str = AUDIT_RESULT_PASS) -> JSON:
        payload = f.audit_action_payload(audit_result)
        return get_success_data(self.api.content_bundle_action(bundle_id, payload, COMPLIANCE))

    def validate(self, bundle_id: str) -> JSON:
        payload = f.action_payload(ACTION_VALIDATE)
        return get_success_data(self.api.content_bundle_action(bundle_id, payload, CONTENT_MANAGER))

    def publish(self, bundle_id: str) -> JSON:
        payload = f.action_payload(ACTION_PUBLISH)
        return get_success_data(self.api.content_bundle_action(bundle_id, payload, CONTENT_MANAGER))

    def get_bundle(self, bundle_id: str) -> JSON:
        return get_success_data(self.api.get_content_bundle(bundle_id, CONTENT_MANAGER))

    # --- inventory ------------------------------------------------------
    def availability(self, store_id: str, menu_item_id: str, on_hand_units: int = 40,
                     par_units: int = 20, reserved_units: int = 0, **kwargs: Any) -> JSON:
        payload = f.availability_payload(menu_item_id, on_hand_units, par_units,
                                        reserved_units, **kwargs)
        return get_success_data(self.api.create_item_availability(store_id, payload, ADMIN))

    def sync_on_hand(self, availability_id: str, on_hand_units: int,
                     reserved_units: int = 0) -> JSON:
        payload = f.sync_on_hand_payload(on_hand_units, reserved_units)
        return get_success_data(self.api.item_availability_action(availability_id, payload, ADMIN))

    # --- suggestion rules ----------------------------------------------
    def upsell_rule(self, cluster_id: str, trigger_item_id: str, suggested_item_id: str,
                    **kwargs: Any) -> JSON:
        payload = f.upsell_rule_payload(cluster_id, trigger_item_id, suggested_item_id, **kwargs)
        return get_success_data(self.api.create_upsell_rule(payload, CONTENT_MANAGER))

    # --- campaigns ------------------------------------------------------
    def campaign(self, campaign_code: str, cluster_id: str, window_start_utc: str,
                 window_end_utc: str, **kwargs: Any) -> JSON:
        payload = f.campaign_version_payload(campaign_code, cluster_id, window_start_utc,
                                             window_end_utc, **kwargs)
        return get_success_data(self.api.create_campaign_version(payload, CONTENT_MANAGER))

    def schedule_campaign(self, version_id: str) -> JSON:
        from .constants import ACTION_SCHEDULE

        payload = f.action_payload(ACTION_SCHEDULE)
        return get_success_data(
            self.api.campaign_version_action(version_id, payload, CONTENT_MANAGER)
        )

    # --- devices --------------------------------------------------------
    def device(self, store_id: str, device_code: str = DEVICE_CODE_K001,
               device_kind: str = DEVICE_KIOSK, **kwargs: Any) -> JSON:
        payload = f.device_payload(store_id, device_code, device_kind, **kwargs)
        return get_success_data(self.api.register_device(payload, ADMIN))

    def heartbeat(self, device_id: str, **kwargs: Any) -> JSON:
        payload = f.heartbeat_payload(**kwargs)
        return get_success_data(
            self.api.send_heartbeat(device_id, payload, make_device_agent_headers(device_id))
        )

    def attest(self, device_id: str, **kwargs: Any) -> JSON:
        payload = f.attestation_payload(**kwargs)
        return get_success_data(self.api.payment_attestation(device_id, payload, COMPLIANCE))

    def cache_sync(self, device_id: str, bundle_id: str,
                   flush_offline_orders: Optional[bool] = None) -> JSON:
        payload = f.cache_sync_payload(bundle_id, flush_offline_orders)
        return get_success_data(
            self.api.cache_sync(device_id, payload, make_device_agent_headers(device_id))
        )

    def get_device(self, device_id: str) -> JSON:
        return get_success_data(self.api.get_device(device_id, ADMIN))

    # --- orders ---------------------------------------------------------
    def order(self, device_id: str, line_items: List[JSON], **kwargs: Any) -> JSON:
        payload = f.order_payload(line_items, **kwargs)
        return get_success_data(
            self.api.create_order(device_id, payload, make_device_agent_headers(device_id))
        )

    # --- price change requests -----------------------------------------
    def price_change_request(self, menu_item_id: str, price_zone_id: str,
                             proposed_price_cents: int, effective_from_utc: str,
                             expected_menu_item_version: int, headers: JSON,
                             **kwargs: Any) -> JSON:
        payload = f.price_change_request_payload(menu_item_id, price_zone_id,
                                                 proposed_price_cents, effective_from_utc,
                                                 expected_menu_item_version, **kwargs)
        return get_success_data(self.api.create_price_change_request(payload, headers))

    def pcr_action(self, request_id: str, action: str, headers: JSON, **kwargs: Any) -> JSON:
        payload = f.action_payload(action, **kwargs)
        return get_success_data(
            self.api.price_change_request_action(request_id, payload, headers)
        )

    # --- audit ----------------------------------------------------------
    def audit(self, headers: Optional[JSON] = None, **params: Any) -> List[JSON]:
        response = self.api.list_audit_events(headers or ADMIN, params=params or None)
        return get_success_data(response)


ALL_CATEGORIES = [CATEGORY_ENTREE, CATEGORY_SIDE, CATEGORY_DRINK, CATEGORY_DESSERT]

CATALOGUE = (
    (SKU_BURGER, CATEGORY_ENTREE, BURGER_BASE_CENTS, 7.1),
    (SKU_FRIES, CATEGORY_SIDE, FRIES_BASE_CENTS, 6.2),
    (SKU_PIE, CATEGORY_DESSERT, PIE_BASE_CENTS, 5.4),
    (SKU_COLA, CATEGORY_DRINK, COLA_BASE_CENTS, 5.9),
)


def build_catalogue(world: World, skus: Optional[Sequence[str]] = None) -> Dict[str, JSON]:
    """Create the shared four-item catalogue, all with READY accessibility copy."""
    wanted = set(skus) if skus is not None else {sku for sku, _, _, _ in CATALOGUE}
    items: Dict[str, JSON] = {}
    for sku, category, base_price_cents, contrast in CATALOGUE:
        if sku in wanted:
            items[sku] = world.item(sku, category=category,
                                    base_price_cents=base_price_cents,
                                    contrast_ratio=contrast)
    return items


def publish_bundle_with_slot(world: World, cluster_id: str,
                             category_codes: Optional[Sequence[str]] = None,
                             **slot_kwargs: Any) -> JSON:
    """Open a bundle, append one slot, pass the audit, validate and publish."""
    bundle = world.bundle(cluster_id)
    bundle = world.slot(bundle["id"], bundle["version"],
                        category_codes=list(category_codes or ALL_CATEGORIES), **slot_kwargs)
    world.audit_pass(bundle["id"])
    world.validate(bundle["id"])
    return world.publish(bundle["id"])


def build_baseline(api: KioskOpsClient) -> Dict[str, Any]:
    """One price zone, one cluster, one store, the four-item catalogue on a published
    LUNCH bundle, stocked availability rows and one healthy attested kiosk."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ROOT")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    items = build_catalogue(world)
    bundle = publish_bundle_with_slot(world, cluster["id"])
    availabilities = {
        sku: world.availability(store["id"], item["id"]) for sku, item in items.items()
    }
    device = world.device(store["id"])
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    return {
        "world": world,
        "zone": zone,
        "cluster": cluster,
        "store": store,
        "items": items,
        "burger": items[SKU_BURGER],
        "fries": items[SKU_FRIES],
        "pie": items[SKU_PIE],
        "cola": items[SKU_COLA],
        "bundle": bundle,
        "availabilities": availabilities,
        "device": device,
        "daypart_code": LUNCH_CODE,
    }


# --- pytest fixtures ------------------------------------------------------
@pytest.fixture
def api() -> KioskOpsClient:
    """A client against the server the harness restarted for this test."""
    return KioskOpsClient()


@pytest.fixture
def world(api: KioskOpsClient) -> World:
    return World(api)


@pytest.fixture
def baseline(api: KioskOpsClient) -> Dict[str, Any]:
    return build_baseline(api)
