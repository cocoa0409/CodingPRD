"""Request payload builders.

Every monetary field is emitted as a JSON integer in minor units, and every
instant is emitted as a full ISO-8601 UTC instant.
"""

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    ACCESSIBILITY_MAX_SUGGESTIONS,
    AUDIT_RESULT_PASS,
    ATTESTATION_FAR_FUTURE,
    BURGER_BASE_CENTS,
    CATEGORY_ENTREE,
    CERT_UNTIL_FAR_FUTURE,
    DEFAULT_CURRENCY,
    DEVICE_CODE_K001,
    DEVICE_KIOSK,
    DISCOUNT_PERCENT_OFF,
    FIRMWARE_VERSION,
    LUNCH_BUFFER,
    LUNCH_CODE,
    LUNCH_END,
    LUNCH_LAYOUT,
    LUNCH_START,
    MIN_PROMPT_SECONDS,
    ROUNDING_NINE_ENDING,
    RULE_KIND_UPSELL,
    STACKING_GROUP_BASE,
    STORE_CODE_S001,
    STORE_OFFSET_MINUTES,
    TENDER_CARD,
    TIER_STANDARD,
    ZONE_A_CODE,
    ZONE_A_MAX_UPLIFT_BP,
    ZONE_A_MULTIPLIER_BP,
    ZONE_A_TAX_BP,
)
from .types import JSON


def _merge(payload: JSON, overrides: Dict[str, Any]) -> JSON:
    """Apply overrides; a value of None removes the key so 'omitted' is expressible."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- price zones ---------------------------------------------------------
def price_zone_payload(zone_code: str = ZONE_A_CODE, **overrides: Any) -> JSON:
    payload = {
        "zone_code": zone_code,
        "currency_code": DEFAULT_CURRENCY,
        "price_multiplier_bp": ZONE_A_MULTIPLIER_BP,
        "psychological_rounding": ROUNDING_NINE_ENDING,
        "tax_rate_bp": ZONE_A_TAX_BP,
        "max_uplift_bp": ZONE_A_MAX_UPLIFT_BP,
    }
    return _merge(payload, overrides)


# --- store clusters ------------------------------------------------------
def store_cluster_payload(cluster_code: str, parent_cluster_id: Optional[str] = None,
                          **overrides: Any) -> JSON:
    payload: JSON = {"cluster_code": cluster_code, "tier": TIER_STANDARD}
    if parent_cluster_id is not None:
        payload["parent_cluster_id"] = parent_cluster_id
    return _merge(payload, overrides)


# --- stores --------------------------------------------------------------
def store_payload(cluster_id: str, price_zone_id: str, store_code: str = STORE_CODE_S001,
                  **overrides: Any) -> JSON:
    payload = {
        "store_code": store_code,
        "cluster_id": cluster_id,
        "price_zone_id": price_zone_id,
        "timezone_offset_minutes": STORE_OFFSET_MINUTES,
        "accessibility_certified_until_utc": CERT_UNTIL_FAR_FUTURE,
    }
    return _merge(payload, overrides)


# --- menu items ----------------------------------------------------------
def menu_item_payload(sku: str, display_name: Optional[str] = None,
                      category: str = CATEGORY_ENTREE,
                      base_price_cents: int = BURGER_BASE_CENTS,
                      screen_reader_text: Optional[str] = None,
                      contrast_ratio: float = 7.1,
                      allergen_tags: Optional[Sequence[str]] = None,
                      **overrides: Any) -> JSON:
    payload: JSON = {
        "sku": sku,
        "display_name": display_name if display_name is not None else sku.replace("SKU-", "").title(),
        "category": category,
        "base_price_cents": int(base_price_cents),
        "screen_reader_text": (
            screen_reader_text if screen_reader_text is not None else f"{sku} described for screen readers"
        ),
        "contrast_ratio": contrast_ratio,
    }
    if allergen_tags is not None:
        payload["allergen_tags"] = list(allergen_tags)
    return _merge(payload, overrides)


def accessibility_copy_payload(expected_menu_item_version: int, screen_reader_text: str,
                               contrast_ratio: float, **overrides: Any) -> JSON:
    payload = {
        "expected_menu_item_version": int(expected_menu_item_version),
        "screen_reader_text": screen_reader_text,
        "contrast_ratio": contrast_ratio,
    }
    return _merge(payload, overrides)


# --- price change requests ----------------------------------------------
def price_change_request_payload(menu_item_id: str, price_zone_id: str,
                                 proposed_price_cents: int, effective_from_utc: str,
                                 expected_menu_item_version: int,
                                 justification: str = "Seasonal repricing of the zone.",
                                 **overrides: Any) -> JSON:
    payload = {
        "menu_item_id": menu_item_id,
        "price_zone_id": price_zone_id,
        "proposed_price_cents": int(proposed_price_cents),
        "justification": justification,
        "effective_from_utc": effective_from_utc,
        "expected_menu_item_version": int(expected_menu_item_version),
    }
    return _merge(payload, overrides)


def action_payload(action: str, **overrides: Any) -> JSON:
    """Every workflow endpoint is driven by an action verb."""
    return _merge({"action": action}, overrides)


# --- availability --------------------------------------------------------
def availability_payload(menu_item_id: str, on_hand_units: int = 40, par_units: int = 20,
                         reserved_units: int = 0, **overrides: Any) -> JSON:
    payload = {
        "menu_item_id": menu_item_id,
        "on_hand_units": int(on_hand_units),
        "reserved_units": int(reserved_units),
        "par_units": int(par_units),
    }
    return _merge(payload, overrides)


def sync_on_hand_payload(on_hand_units: int, reserved_units: int = 0, **overrides: Any) -> JSON:
    from .constants import ACTION_SYNC_ON_HAND

    payload = {
        "action": ACTION_SYNC_ON_HAND,
        "on_hand_units": int(on_hand_units),
        "reserved_units": int(reserved_units),
    }
    return _merge(payload, overrides)


def eighty_six_payload(until_utc: str, eighty_six_reason: str = "OPERATOR_PULL",
                       **overrides: Any) -> JSON:
    from .constants import ACTION_EIGHTY_SIX

    payload = {
        "action": ACTION_EIGHTY_SIX,
        "until_utc": until_utc,
        "eighty_six_reason": eighty_six_reason,
    }
    return _merge(payload, overrides)


# --- campaign versions ---------------------------------------------------
def campaign_version_payload(campaign_code: str, cluster_id: str, window_start_utc: str,
                             window_end_utc: str, version_no: int = 1,
                             discount_kind: str = DISCOUNT_PERCENT_OFF,
                             discount_value: int = 1000,
                             stacking_group: str = STACKING_GROUP_BASE,
                             priority_rank: int = 10, **overrides: Any) -> JSON:
    payload = {
        "campaign_code": campaign_code,
        "version_no": int(version_no),
        "cluster_id": cluster_id,
        "discount_kind": discount_kind,
        "discount_value": int(discount_value),
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "stacking_group": stacking_group,
        "priority_rank": int(priority_rank),
    }
    return _merge(payload, overrides)


# --- upsell rules --------------------------------------------------------
def upsell_rule_payload(cluster_id: str, trigger_item_id: str, suggested_item_id: str,
                        suggestion_slot: int = 1, rule_kind: str = RULE_KIND_UPSELL,
                        min_cart_subtotal_cents: int = 0,
                        max_prompt_seconds: int = MIN_PROMPT_SECONDS + 5,
                        **overrides: Any) -> JSON:
    payload = {
        "cluster_id": cluster_id,
        "trigger_item_id": trigger_item_id,
        "suggested_item_id": suggested_item_id,
        "rule_kind": rule_kind,
        "min_cart_subtotal_cents": int(min_cart_subtotal_cents),
        "suggestion_slot": int(suggestion_slot),
        "max_prompt_seconds": int(max_prompt_seconds),
    }
    return _merge(payload, overrides)


# --- content bundles -----------------------------------------------------
def content_bundle_payload(cluster_id: str, **overrides: Any) -> JSON:
    return _merge({"cluster_id": cluster_id}, overrides)


def daypart_slot_payload(expected_content_bundle_version: int,
                         daypart_code: str = LUNCH_CODE,
                         start_minute_of_day: int = LUNCH_START,
                         end_minute_of_day: int = LUNCH_END,
                         layout_code: str = LUNCH_LAYOUT,
                         buffer_minutes: int = LUNCH_BUFFER,
                         category_codes: Optional[Sequence[str]] = None,
                         **overrides: Any) -> JSON:
    payload = {
        "expected_content_bundle_version": int(expected_content_bundle_version),
        "daypart_code": daypart_code,
        "start_minute_of_day": int(start_minute_of_day),
        "end_minute_of_day": int(end_minute_of_day),
        "layout_code": layout_code,
        "buffer_minutes": int(buffer_minutes),
        "category_codes": list(category_codes) if category_codes is not None else [CATEGORY_ENTREE],
    }
    return _merge(payload, overrides)


def audit_action_payload(audit_result: str = AUDIT_RESULT_PASS, **overrides: Any) -> JSON:
    from .constants import ACTION_ACCESSIBILITY_AUDIT

    payload = {"action": ACTION_ACCESSIBILITY_AUDIT, "audit_result": audit_result}
    return _merge(payload, overrides)


# --- devices -------------------------------------------------------------
def device_payload(store_id: str, device_code: str = DEVICE_CODE_K001,
                   device_kind: str = DEVICE_KIOSK, offline_cache_capacity: int = 2,
                   pin_pad_firmware_version: Optional[str] = FIRMWARE_VERSION,
                   **overrides: Any) -> JSON:
    payload: JSON = {
        "store_id": store_id,
        "device_kind": device_kind,
        "device_code": device_code,
        "offline_cache_capacity": int(offline_cache_capacity),
    }
    if device_kind == DEVICE_KIOSK and pin_pad_firmware_version is not None:
        payload["pin_pad_firmware_version"] = pin_pad_firmware_version
    return _merge(payload, overrides)


def heartbeat_payload(printer_ok: bool = True, touch_ok: bool = True,
                      screen_reader_ok: bool = True, network_ok: bool = True,
                      **overrides: Any) -> JSON:
    payload = {
        "printer_ok": bool(printer_ok),
        "touch_ok": bool(touch_ok),
        "screen_reader_ok": bool(screen_reader_ok),
        "network_ok": bool(network_ok),
    }
    return _merge(payload, overrides)


def cache_sync_payload(bundle_id: str, flush_offline_orders: Optional[bool] = None,
                       **overrides: Any) -> JSON:
    payload: JSON = {"bundle_id": bundle_id}
    if flush_offline_orders is not None:
        payload["flush_offline_orders"] = bool(flush_offline_orders)
    return _merge(payload, overrides)


def attestation_payload(p2pe_certified: bool = True,
                        attestation_expiry_utc: str = ATTESTATION_FAR_FUTURE,
                        pin_pad_firmware_version: str = FIRMWARE_VERSION,
                        **overrides: Any) -> JSON:
    payload = {
        "pin_pad_firmware_version": pin_pad_firmware_version,
        "p2pe_certified": bool(p2pe_certified),
        "attestation_expiry_utc": attestation_expiry_utc,
    }
    return _merge(payload, overrides)


# --- orders --------------------------------------------------------------
def line(menu_item_id: str, qty: int = 1) -> JSON:
    return {"menu_item_id": menu_item_id, "qty": int(qty)}


def order_payload(line_items: List[JSON], tender_kind: str = TENDER_CARD,
                  accepted_upsell_rule_ids: Optional[Sequence[str]] = None,
                  created_offline: Optional[bool] = None, **overrides: Any) -> JSON:
    payload: JSON = {"line_items": list(line_items), "tender_kind": tender_kind}
    if accepted_upsell_rule_ids is not None:
        payload["accepted_upsell_rule_ids"] = list(accepted_upsell_rule_ids)
    if created_offline is not None:
        payload["created_offline"] = bool(created_offline)
    return _merge(payload, overrides)


# --- projection query ----------------------------------------------------
def projection_params(at_minute_of_day: Optional[int] = None,
                      cart_item_ids: Optional[Sequence[str]] = None,
                      device_id: Optional[str] = None) -> JSON:
    params: JSON = {}
    if at_minute_of_day is not None:
        params["at_minute_of_day"] = int(at_minute_of_day)
    if cart_item_ids is not None:
        params["cart_item_ids"] = ",".join(cart_item_ids)
    if device_id is not None:
        params["device_id"] = device_id
    return params


MAX_SUGGESTIONS_WITH_SCREEN_READER = ACCESSIBILITY_MAX_SUGGESTIONS
