"""Derived state, recomputation and the ordered cascades (PRD 2.5, 2.9, 3.x).

Nothing in here is ever accepted from a client.  A derived field being
recomputed is a mutation: the row that actually changed refreshes updated_at
and increments version by exactly 1.
"""
from datetime import timedelta

import calc
import constants as C
import logical_clock as clockmod
from db import DB, append_audit, ordered, touch

SYSTEM_ROLE = "system"


def apply_changes(row, values, bump=True):
    """Write values, returning True when at least one stored value moved."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed and bump:
        touch(row)
    return changed


# --------------------------------------------------------------------------
# menu items (PRD 3.2)
# --------------------------------------------------------------------------

def accessibility_state_of(screen_reader_text, contrast_ratio):
    text = (screen_reader_text or "").strip()
    if not text:
        return "MISSING_ALT_TEXT"
    if float(contrast_ratio or 0) >= C.MIN_CONTRAST_RATIO:
        return "READY"
    return "CONTRAST_FAIL"


def item_derived_values(item):
    pending = 0
    for req in DB.price_requests.values():
        if req.get("menu_item_id") == item["id"] and req.get("state") in C.PRICE_REQUEST_PENDING_STATES:
            pending += 1
    total = sum(int(e["price_cents"]) for e in item.get("zone_price_overrides", []))
    return {
        "accessibility_state": accessibility_state_of(
            item.get("screen_reader_text"), item.get("contrast_ratio")),
        "zone_override_total_cents": total,
        "pending_price_request_count": pending,
        "pricing_lock_state": "PENDING_CHANGE" if pending >= 1 else "UNLOCKED",
        "chainwide_availability_state": calc.rollup_chainwide(item["id"]),
    }


def recompute_item(item, bump=True):
    return apply_changes(item, item_derived_values(item), bump=bump)


# --------------------------------------------------------------------------
# content bundles (PRD 3.4)
# --------------------------------------------------------------------------

def zones_of_cluster(cluster_id):
    """Exactly the zones referenced by at least one store of this cluster."""
    zone_ids = []
    for store in ordered(list(DB.stores.values())):
        if store.get("cluster_id") != cluster_id:
            continue
        if store.get("price_zone_id") not in zone_ids:
            zone_ids.append(store["price_zone_id"])
    zones = [DB.price_zones[z] for z in zone_ids if z in DB.price_zones]
    return ordered(zones)


def live_price_checksum(bundle):
    total = 0
    for entry in bundle.get("price_snapshot", []):
        item = DB.menu_items.get(entry["menu_item_id"])
        zone = DB.price_zones.get(entry["price_zone_id"])
        if item is None or zone is None:
            continue
        total += calc.effective_zone_price(item, zone)
    return total


def cluster_has_suspended_rule(cluster_id):
    for rule in DB.upsell_rules.values():
        if rule.get("cluster_id") == cluster_id and rule.get("state") == "SUSPENDED":
            return True
    return False


def recompute_bundle(bundle, bump=True):
    if bundle.get("state") != "PUBLISHED":
        return False
    live = live_price_checksum(bundle)
    stale = (live != bundle.get("price_snapshot_checksum")) or cluster_has_suspended_rule(bundle.get("cluster_id"))
    return apply_changes(bundle, {"live_price_checksum": live, "stale_flag": bool(stale)}, bump=bump)


def cluster_published_bundle_version(cluster_id):
    best = 0
    for bundle in DB.bundles.values():
        if bundle.get("cluster_id") == cluster_id and bundle.get("state") == "PUBLISHED":
            if bundle["bundle_version"] > best:
                best = bundle["bundle_version"]
    return best


def recompute_cluster(cluster, bump=True):
    return apply_changes(cluster, {
        "chain_depth": len(calc.cluster_chain_ids(cluster["id"])),
        "published_bundle_version": cluster_published_bundle_version(cluster["id"]),
    }, bump=bump)


# --------------------------------------------------------------------------
# devices (PRD 3.8)
# --------------------------------------------------------------------------

def cache_state_of(device):
    bundle_id = device.get("cached_bundle_id")
    if not bundle_id:
        return "MISSING"
    bundle = DB.bundles.get(bundle_id)
    if bundle is None:
        return "STALE"
    if (bundle.get("state") == "PUBLISHED" and not bundle.get("stale_flag")
            and bundle.get("bundle_version") == device.get("cached_bundle_version")):
        return "FRESH"
    return "STALE"


def recompute_device_cache(device, bump=True):
    return apply_changes(device, {"cache_state": cache_state_of(device)}, bump=bump)


def rescore_device(device, bump=True, audit=True):
    missed, rolling, worst = calc.health_scores(device)
    band = calc.health_band(device, missed, rolling, worst)
    was = device.get("health_state")
    changed = apply_changes(device, {
        "consecutive_missed_heartbeats": missed,
        "rolling_health_score": rolling,
        "worst_case_health_score": worst,
        "health_state": band,
    }, bump=bump)
    if audit and band == "QUARANTINED" and was != "QUARANTINED":
        append_audit("DEVICE", device["id"], "DEVICE_QUARANTINED", SYSTEM_ROLE, None,
                     detail="WORST_CASE_HEALTH_BELOW_THRESHOLD")
    return changed


def recompute_device_payment(device, bump=True):
    return apply_changes(device, {"payment_compliance_state": calc.payment_band(device)}, bump=bump)


def recompute_offline_order_count(device, bump=True):
    count = 0
    for order in DB.orders.values():
        if order.get("device_id") == device["id"] and order.get("handoff_state") == "CACHED_OFFLINE":
            count += 1
    return apply_changes(device, {"offline_order_count": count}, bump=bump)


# --------------------------------------------------------------------------
# stores (PRD 2.9, 3.1)
# --------------------------------------------------------------------------

def devices_of_store(store_id):
    return ordered([d for d in DB.devices.values() if d.get("store_id") == store_id])


def store_posture(store):
    devices = devices_of_store(store["id"])
    kiosks = [d for d in devices if d.get("device_kind") == "KIOSK"]
    if not calc.chain_has_published_bundle(store):
        return "FROZEN"
    if kiosks and all(d.get("health_state") in ("OFFLINE", "QUARANTINED") for d in kiosks):
        return "FROZEN"
    for device in devices:
        if device.get("cache_state") == "STALE" or device.get("health_state") == "DEGRADED":
            return "DEGRADED"
    for device in kiosks:
        if device.get("payment_compliance_state") in ("UNATTESTED", "EXPIRING", "NON_COMPLIANT"):
            return "DEGRADED"
    return "OPEN"


def open_order_count(store_id):
    device_ids = set(d["id"] for d in DB.devices.values() if d.get("store_id") == store_id)
    count = 0
    for order in DB.orders.values():
        if order.get("device_id") in device_ids and order.get("handoff_state") in C.OPEN_HANDOFF_STATES:
            count += 1
    return count


def recompute_store(store, bump=True, audit=True):
    posture = store_posture(store)
    was = store.get("content_posture")
    changed = apply_changes(store, {
        "content_posture": posture,
        "open_order_count": open_order_count(store["id"]),
    }, bump=bump)
    if audit and posture == "FROZEN" and was != "FROZEN":
        append_audit("STORE", store["id"], "STORE_CONTENT_FROZEN", SYSTEM_ROLE, None,
                     detail="NO_PUBLISHED_CONTENT_OR_ALL_KIOSKS_DOWN")
    return changed


def reconcile():
    """The shared tail of every cascade: bundle drift, device caches, cluster
    published versions, then store postures."""
    for bundle in list(DB.bundles.values()):
        recompute_bundle(bundle)
    for device in list(DB.devices.values()):
        recompute_device_cache(device)
    for cluster in list(DB.clusters.values()):
        recompute_cluster(cluster)
    for store in list(DB.stores.values()):
        recompute_store(store)


# --------------------------------------------------------------------------
# availability rows, the 86 list and its cascades (PRD 3.6)
# --------------------------------------------------------------------------

def recompute_availability(row, bump=True):
    available, supply, availability = calc.derive_stock_fields(row)
    return apply_changes(row, {
        "available_units": available,
        "supply_state": supply,
        "availability_state": availability,
    }, bump=bump)


def sync_upsell_rules_for_item(item_id):
    """Link 3 of the 86 cascade and its compensation."""
    chainwide = calc.rollup_chainwide(item_id)
    for rule in ordered(list(DB.upsell_rules.values())):
        if rule.get("suggested_item_id") != item_id:
            continue
        if chainwide == "UNAVAILABLE":
            if rule.get("state") == "ACTIVE":
                apply_changes(rule, {"state": "SUSPENDED",
                                     "suspended_reason": "SUGGESTED_ITEM_UNAVAILABLE"})
        else:
            if rule.get("state") == "SUSPENDED" and rule.get("suspended_reason") == "SUGGESTED_ITEM_UNAVAILABLE":
                apply_changes(rule, {"state": "ACTIVE", "suspended_reason": None})


def availability_cascade(row):
    """Links 2 to 5: the item rollup, the suggestion rules, the published
    bundles that snapshotted them, the caching devices and their stores."""
    item = DB.menu_items.get(row.get("menu_item_id"))
    if item is not None:
        recompute_item(item)
        sync_upsell_rules_for_item(item["id"])
        recompute_item(item)
    reconcile()


def auto_eighty_six(row, actor_role, actor_user_id):
    """A sync that drives the sellable count to 0 or below fires the auto-86."""
    until = clockmod.now() + timedelta(minutes=C.AUTO_86_HOLD_MINUTES)
    apply_changes(row, {
        "listing_state": "EIGHTY_SIXED",
        "eighty_six_state": "AUTO_86",
        "eighty_six_reason": "INVENTORY_DEPLETED",
        "eighty_six_until_utc": clockmod.iso(until),
    })
    recompute_availability(row)
    append_audit("ITEM_AVAILABILITY", row["id"], "ITEM_AUTO_EIGHTY_SIXED",
                 actor_role, actor_user_id, detail="INVENTORY_DEPLETED")
    availability_cascade(row)


def release_auto_hold(row):
    """The clock lapses an 86 only when the 86 was automatic."""
    if row.get("eighty_six_state") != "AUTO_86":
        return False
    until = clockmod.parse_instant(row.get("eighty_six_until_utc"))
    if until is None or clockmod.now() < until:
        return False
    apply_changes(row, {
        "listing_state": "LISTED",
        "eighty_six_state": "NONE",
        "eighty_six_until_utc": None,
        "eighty_six_reason": None,
    })
    recompute_availability(row)
    append_audit("ITEM_AVAILABILITY", row["id"], "ITEM_AUTO_86_LAPSED", SYSTEM_ROLE, None,
                 detail="AUTO_86_HOLD_ELAPSED")
    availability_cascade(row)
    return True


def release_expired_holds():
    released = 0
    for row in ordered(list(DB.availabilities.values())):
        if release_auto_hold(row):
            released += 1
    return released


def adjust_reservation(row, delta):
    """Order capture reserves units; a void releases exactly the same units."""
    reserved = int(row.get("reserved_units", 0)) + delta
    if reserved < 0:
        reserved = 0
    apply_changes(row, {"reserved_units": reserved})
    recompute_availability(row)


# --------------------------------------------------------------------------
# campaign versions (PRD 3.7)
# --------------------------------------------------------------------------

def advance_campaign(version):
    """Activation and expiry are clock-driven and the boundaries are closed."""
    state = version.get("state")
    if state not in ("SCHEDULED", "ACTIVE"):
        return False
    now = clockmod.now()
    start = clockmod.parse_instant(version.get("window_start_utc"))
    end = clockmod.parse_instant(version.get("window_end_utc"))
    if start is None or end is None:
        return False
    if now > end:
        apply_changes(version, {"state": "EXPIRED"})
        append_audit("CAMPAIGN_VERSION", version["id"], "CAMPAIGN_EXPIRED", SYSTEM_ROLE, None,
                     detail="WINDOW_CLOSED")
        return True
    if state == "SCHEDULED" and start <= now <= end:
        apply_changes(version, {"state": "ACTIVE"})
        append_audit("CAMPAIGN_VERSION", version["id"], "CAMPAIGN_ACTIVATED", SYSTEM_ROLE, None,
                     detail="WINDOW_OPENED")
        return True
    return False


def advance_all_campaigns():
    advanced = 0
    for version in ordered(list(DB.campaigns.values())):
        if advance_campaign(version):
            advanced += 1
    return advanced


def rescore_all_devices():
    rescored = 0
    for device in ordered(list(DB.devices.values())):
        rescore_device(device)
        recompute_device_payment(device)
        rescored += 1
    return rescored


# --------------------------------------------------------------------------
# price change application (PRD 3.3)
# --------------------------------------------------------------------------

def apply_price_request(row, actor_role=SYSTEM_ROLE, actor_user_id=None):
    """Link 0 to link 5 of the apply cascade, shared by the verb and the clock.

    PRD 3.3: "Applying is available to the PricingAnalyst and, as a
    break-glass operator, to a PlatformAdmin; the system also applies an
    approved request of its own accord when the logical clock is moved to or
    past that request's effective_from_utc."
    """
    item = DB.menu_items.get(row.get("menu_item_id"))
    zone = DB.price_zones.get(row.get("price_zone_id"))
    applied = calc.psychological_round(
        int(row["proposed_price_cents"]),
        (zone or {}).get("psychological_rounding") or "NONE")
    row["applied_price_cents"] = applied
    row["state"] = "APPLIED"
    touch(row)
    overrides = [e for e in item.get("zone_price_overrides", [])
                 if e.get("price_zone_id") != row["price_zone_id"]]
    overrides.append({
        "price_zone_id": row["price_zone_id"],
        "price_cents": applied,
        "applied_request_id": row["id"],
        "applied_at_utc": clockmod.now_iso(),
    })
    item["zone_price_overrides"] = overrides
    touch(item)
    recompute_item(item, bump=False)
    append_audit("MENU_ITEM", item["id"], "PRICE_OVERRIDE_APPLIED", actor_role, actor_user_id,
                 detail=row.get("justification"),
                 before_value_cents=row.get("baseline_price_cents"),
                 after_value_cents=applied)
    reconcile()
    return applied


def auto_apply_due_requests():
    """The clock applies every APPROVED request whose effective instant it reached."""
    applied = 0
    for row in ordered(DB.price_requests.values()):
        if row.get("state") != "APPROVED":
            continue
        effective = clockmod.parse_instant(row.get("effective_from_utc"))
        if effective is None or clockmod.now() < effective:
            continue
        item = DB.menu_items.get(row.get("menu_item_id"))
        if item is None or item.get("version") != row.get("pinned_menu_item_version"):
            continue
        if len(row.get("approval_user_ids", [])) < int(row.get("required_approvals", 1)):
            continue
        apply_price_request(row)
        applied += 1
    return applied
