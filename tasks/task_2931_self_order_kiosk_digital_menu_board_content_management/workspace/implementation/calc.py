"""Pure calculations (PRD 2.6, 3.2, 3.5, 3.6, 3.7, 3.8, 3.9)."""
import hashlib
from decimal import Decimal, ROUND_HALF_UP

import constants as C
import logical_clock as clockmod
from db import DB, ordered


def round_half_up(numerator, denominator=1):
    """Every division in this document rounds half up to the nearest whole unit."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount, bp):
    return round_half_up(Decimal(amount) * Decimal(bp), C.BP_DENOMINATOR)


# --------------------------------------------------------------------------
# effective_zone_price (PRD 3.2)
# --------------------------------------------------------------------------

def psychological_round(raw_cents, style):
    if style == "NEAREST_05":
        return round_half_up(raw_cents, 5) * 5
    if style == "NINE_ENDING":
        y = (raw_cents // 10) * 10 + 9
        return y if y >= raw_cents else y + 10
    return raw_cents


def zone_override_entry(item, price_zone_id):
    for entry in item.get("zone_price_overrides", []):
        if entry.get("price_zone_id") == price_zone_id:
            return entry
    return None


def effective_zone_price(item, zone):
    """Step 1 picks the basis (override wins); step 2 applies psychological
    rounding in BOTH branches."""
    override = zone_override_entry(item, zone["id"])
    if override is not None:
        raw_cents = int(override["price_cents"])
    else:
        raw_cents = apply_bp(item["base_price_cents"], zone["price_multiplier_bp"])
    return psychological_round(raw_cents, zone.get("psychological_rounding") or "NONE")


# --------------------------------------------------------------------------
# cluster inheritance chain (PRD 2.8)
# --------------------------------------------------------------------------

def cluster_chain_ids(cluster_id):
    """The chain beginning with this cluster and continuing through its
    ancestors, nearest first, at most five clusters, never revisiting one."""
    chain = []
    current = cluster_id
    while current and len(chain) < C.MAX_CLUSTER_CHAIN_DEPTH:
        if current in chain:
            break
        cluster = DB.clusters.get(current)
        if cluster is None:
            break
        chain.append(current)
        current = cluster.get("parent_cluster_id")
    return chain


def store_chain_ids(store):
    return cluster_chain_ids(store.get("cluster_id"))


def published_bundle_of_cluster(cluster_id):
    """That cluster's PUBLISHED bundle with the highest bundle_version."""
    best = None
    for bundle in DB.bundles.values():
        if bundle.get("cluster_id") != cluster_id or bundle.get("state") != "PUBLISHED":
            continue
        if best is None or bundle["bundle_version"] > best["bundle_version"]:
            best = bundle
    return best


def resolved_bundle_for_store(store):
    for cluster_id in store_chain_ids(store):
        bundle = published_bundle_of_cluster(cluster_id)
        if bundle is not None:
            return bundle
    return None


def chain_has_published_bundle(store):
    return resolved_bundle_for_store(store) is not None


# --------------------------------------------------------------------------
# daypart_resolution (PRD 3.5)
# --------------------------------------------------------------------------

def effective_slots(store):
    slots = []
    seen = set()
    for cluster_id in store_chain_ids(store):
        bundle = published_bundle_of_cluster(cluster_id)
        if bundle is None:
            continue
        for slot in bundle.get("daypart_slots", []):
            if slot["daypart_code"] in seen:
                continue
            seen.add(slot["daypart_code"])
            slots.append(slot)
    return slots


def local_minute_of_day(store, at_minute_of_day=None):
    if at_minute_of_day is not None:
        return at_minute_of_day
    base = clockmod.minutes_of_day(clockmod.now())
    return (base + int(store.get("timezone_offset_minutes", 0))) % C.MINUTES_PER_DAY


def resolve_daypart(store, at_minute_of_day=None):
    minute = local_minute_of_day(store, at_minute_of_day)
    candidates = [s for s in effective_slots(store)
                  if s["start_minute_of_day"] <= minute < s["end_minute_of_day"]]
    if not candidates:
        return {
            "daypart_code": None,
            "layout_code": C.STATIC_FALLBACK_LAYOUT_CODE,
            "phase": "FALLBACK",
            "local_minute_of_day": minute,
        }
    winner = min(candidates, key=lambda s: (
        s["end_minute_of_day"] - s["start_minute_of_day"],
        s["start_minute_of_day"],
        s.get("created_at") or "",
        s.get("_seq") or 0,
    ))
    phase = "TRANSITIONING" if minute >= winner["end_minute_of_day"] - winner.get("buffer_minutes", 0) else "ACTIVE"
    return {
        "daypart_code": winner["daypart_code"],
        "layout_code": winner["layout_code"],
        "phase": phase,
        "local_minute_of_day": minute,
    }


# --------------------------------------------------------------------------
# campaign_selection (PRD 3.7)
# --------------------------------------------------------------------------

def select_campaign(store):
    chain = store_chain_ids(store)
    now = clockmod.now()
    candidates = []
    for version in DB.campaigns.values():
        if version.get("state") != "ACTIVE":
            continue
        if version.get("cluster_id") not in chain:
            continue
        start = clockmod.parse_instant(version["window_start_utc"])
        end = clockmod.parse_instant(version["window_end_utc"])
        if start is None or end is None:
            continue
        if start <= now <= end:
            candidates.append(version)
    if not candidates:
        return None
    return min(candidates, key=lambda v: (
        v["priority_rank"], -int(v["discount_value"]), v.get("created_at") or "", v.get("_seq") or 0))


# --------------------------------------------------------------------------
# availability_rollup (PRD 3.6)
# --------------------------------------------------------------------------

def low_threshold(par_units):
    return apply_bp(par_units, C.LOW_STOCK_RATIO_BP)


def derive_stock_fields(row):
    available = int(row["on_hand_units"]) - int(row["reserved_units"])
    if available < 0:
        available = 0
    threshold = low_threshold(row["par_units"])
    if available <= 0:
        supply = "DEPLETED"
    elif available <= threshold:
        supply = "LOW"
    else:
        supply = "IN_STOCK"
    if row.get("listing_state") in ("EIGHTY_SIXED", "DISCONTINUED") or supply == "DEPLETED":
        availability = "UNAVAILABLE"
    elif supply == "LOW":
        availability = "LIMITED"
    else:
        availability = "AVAILABLE"
    return available, supply, availability


def rollup_chainwide(menu_item_id):
    rows = [r for r in DB.availabilities.values() if r.get("menu_item_id") == menu_item_id]
    if not rows:
        return "UNAVAILABLE"
    states = [r.get("availability_state") for r in rows]
    if all(s == "UNAVAILABLE" for s in states):
        return "UNAVAILABLE"
    if "AVAILABLE" not in states and "LIMITED" in states:
        return "LIMITED"
    return "AVAILABLE"


# --------------------------------------------------------------------------
# device_health_score (PRD 3.8)
# --------------------------------------------------------------------------

def health_base_score(device):
    if device.get("device_kind") == "MENU_BOARD":
        printer = C.WEIGHT_PRINTER
        touch = C.WEIGHT_TOUCH
    else:
        printer = C.WEIGHT_PRINTER if device.get("printer_ok") else 0
        touch = C.WEIGHT_TOUCH if device.get("touch_ok") else 0
    base = printer + touch
    base += C.WEIGHT_SCREEN_READER if device.get("screen_reader_ok") else 0
    base += C.WEIGHT_NETWORK if device.get("network_ok") else 0
    return base


def missed_heartbeats(device):
    last = clockmod.parse_instant(device.get("last_heartbeat_utc")) if device.get("last_heartbeat_utc") else None
    if last is None:
        return 0
    minutes = clockmod.whole_minutes_between(last, clockmod.now())
    return minutes // C.HEARTBEAT_INTERVAL_MINUTES


def health_scores(device):
    base = health_base_score(device)
    missed = missed_heartbeats(device)
    rolling = max(0, base - min(missed * C.MISS_PENALTY_POINTS, C.MISS_PENALTY_CAP))
    worst = max(0, base - min((missed + C.PROJECTED_MISSES) * C.MISS_PENALTY_POINTS, C.MISS_PENALTY_CAP))
    return missed, rolling, worst


def health_band(device, missed, rolling, worst):
    if not device.get("last_heartbeat_utc"):
        return "OFFLINE"
    if missed >= C.QUARANTINE_MISS_FLOOR and worst < C.HEALTH_DEGRADED_MIN:
        return "QUARANTINED"
    if rolling < C.HEALTH_DEGRADED_MIN:
        return "OFFLINE"
    if rolling < C.HEALTH_ONLINE_MIN:
        return "DEGRADED"
    return "ONLINE"


def payment_band(device):
    if device.get("device_kind") == "MENU_BOARD":
        return "NOT_APPLICABLE"
    expiry_raw = device.get("attestation_expiry_utc")
    if not expiry_raw:
        return "UNATTESTED"
    expiry = clockmod.parse_instant(expiry_raw)
    now = clockmod.now()
    if expiry is None:
        return "UNATTESTED"
    if not device.get("p2pe_certified") or expiry <= now:
        return "NON_COMPLIANT"
    horizon = now + __import__("datetime").timedelta(days=C.ATTESTATION_EXPIRING_DAYS)
    if expiry <= horizon:
        return "EXPIRING"
    return "COMPLIANT"


# --------------------------------------------------------------------------
# receipt (PRD 3.9)
# --------------------------------------------------------------------------

def receipt_hash(order_number, subtotal, discount, tax, total, pinned_bundle_version):
    canonical = "%s|%d|%d|%d|%d|%d" % (
        order_number, subtotal, discount, tax, total, pinned_bundle_version)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def order_number_for(store_code, seq):
    return "%s-%s" % (store_code, str(seq).zfill(C.SEQ_PAD_WIDTH))


# --------------------------------------------------------------------------
# upsell_suggestion_selection (PRD 3.6)
# --------------------------------------------------------------------------

def availability_row(store_id, menu_item_id):
    for row in DB.availabilities.values():
        if row.get("store_id") == store_id and row.get("menu_item_id") == menu_item_id:
            return row
    return None


def cart_subtotal(store, cart):
    """cart: list of (menu_item_id, qty)."""
    zone = DB.price_zones.get(store.get("price_zone_id"))
    total = 0
    for menu_item_id, qty in cart:
        item = DB.menu_items.get(menu_item_id)
        if item is None or zone is None:
            continue
        total += effective_zone_price(item, zone) * qty
    return total


def eligible_upsell_rules(store, cart, screen_reader_ok):
    chain = store_chain_ids(store)
    cart_ids = [item_id for item_id, _qty in cart]
    subtotal = cart_subtotal(store, cart)
    eligible = []
    for rule in DB.upsell_rules.values():
        if rule.get("state") != "ACTIVE":
            continue
        if rule.get("cluster_id") not in chain:
            continue
        if rule.get("trigger_item_id") not in cart_ids:
            continue
        if rule.get("suggested_item_id") in cart_ids:
            continue
        row = availability_row(store["id"], rule.get("suggested_item_id"))
        if row is None or row.get("availability_state") not in ("AVAILABLE", "LIMITED"):
            continue
        if subtotal < int(rule.get("min_cart_subtotal_cents", 0)):
            continue
        if int(rule.get("max_prompt_seconds", 0)) < C.MIN_PROMPT_SECONDS:
            continue
        eligible.append(rule)
    ranked = sorted(eligible, key=lambda r: (
        r["suggestion_slot"],
        chain.index(r["cluster_id"]),
        r.get("created_at") or "",
        r.get("_seq") or 0,
    ))
    cap = C.ACCESSIBILITY_MAX_SUGGESTIONS if screen_reader_ok else C.MAX_UPSELL_SUGGESTIONS
    return ranked[:cap]


def ordered_rows(collection_name):
    return ordered(list(getattr(DB, collection_name).values()))
