"""Calculation rules (SCAFFOLD §1.3): impact tiers, issuance criteria,
coordination requirement, WEA rendering, verification matching/statistics,
performance band, overlap/buffer rules."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CATASTROPHIC_HAIL_INCHES,
    CATASTROPHIC_WIND_MPH,
    CONSIDERABLE_HAIL_INCHES,
    CONSIDERABLE_WIND_MPH,
    DURATION_RANGES,
    EVAC_REENTRY_BUFFER_MINUTES,
    FAR_REVIEW_THRESHOLD,
    FLOOD_ADVISORY_RAIN_IN_HR,
    FLOOD_WARNING_RAIN_IN_HR,
    HURRICANE_ADVISORY_WIND_MPH,
    HURRICANE_WARNING_WIND_MPH,
    POD_REVIEW_THRESHOLD,
    SEVERE_ADVISORY_HAIL_IN,
    SEVERE_ADVISORY_WIND_MPH,
    SEVERE_WARNING_HAIL_IN,
    SEVERE_WARNING_WIND_MPH,
    WEA_ABSOLUTE_MAX_CHARS,
    WINTER_ADVISORY_WIND_MPH,
    WINTER_WARNING_WIND_MPH,
    ZONE_INCLUSION_MIN_PCT,
)
from db import STORE
from geometry import point_in_polygon, polygon_area_sq_km, zone_overlap
from util import round_half_up_dec


def _dec(value):
    return Decimal(repr(float(value)))


# ---------------------------------------------------------------------------
# product window
# ---------------------------------------------------------------------------
def window_end(product):
    """Earliest non-null of (cancelled_at, superseded_at, expires_at)."""
    candidates = [
        product.get("cancelled_at"),
        product.get("superseded_at"),
        product.get("expires_at"),
    ]
    candidates = [c for c in candidates if c is not None]
    return min(candidates) if candidates else None


# ---------------------------------------------------------------------------
# polygon products: area + zone overlap resolution (frozen at creation)
# ---------------------------------------------------------------------------
def resolve_polygon_geometry(vertices, issuing_office):
    """Returns (polygon_area_sq_km float 2dp, resolved_zone_ids sorted by
    zone_code ascending, overlap map zone_id -> Decimal pct for pct > 0)."""
    method = issuing_office["area_method"]
    area = round_half_up_dec(polygon_area_sq_km(vertices, method), 2)
    overlaps = {}
    resolved = []
    for zone in STORE["zones"].values():
        _area_r, pct = zone_overlap(vertices, zone, method)
        if pct > 0:
            overlaps[zone["id"]] = pct
        if pct >= ZONE_INCLUSION_MIN_PCT:
            resolved.append(zone["id"])
    resolved.sort(key=lambda zid: STORE["zones"][zid]["zone_code"])
    return float(area), resolved, overlaps


# ---------------------------------------------------------------------------
# impact tier scoring (creation and again at issue)
# ---------------------------------------------------------------------------
def storm_readings(storm):
    if storm is None:
        return {
            "max_wind_mph": 0,
            "max_hail_inches": 0,
            "rainfall_rate_in_hr": 0,
            "rotation_couplet": False,
            "debris_signature": False,
        }
    return storm


def compute_impact(storm, resolved_zone_ids):
    r = storm_readings(storm)
    wind = _dec(r["max_wind_mph"])
    hail = _dec(r["max_hail_inches"])
    catastrophic = (
        wind >= CATASTROPHIC_WIND_MPH
        or hail >= CATASTROPHIC_HAIL_INCHES
        or bool(r["debris_signature"])
    )
    considerable = wind >= CONSIDERABLE_WIND_MPH or hail >= CONSIDERABLE_HAIL_INCHES
    tiers = {
        STORE["zones"][zid]["population_tier"]
        for zid in resolved_zone_ids
        if zid in STORE["zones"]
    }
    if catastrophic and (tiers & {"HIGH", "URBAN"}):
        threat = "CATASTROPHIC"
    elif considerable and (tiers & {"MEDIUM", "HIGH", "URBAN"}):
        threat = "CONSIDERABLE"
    elif catastrophic and ("MEDIUM" in tiers):
        threat = "CONSIDERABLE"
    else:
        threat = "NONE"
    return threat, threat != "NONE"


# ---------------------------------------------------------------------------
# issuance criteria (against the linked storm's CURRENT readings)
# ---------------------------------------------------------------------------
def criteria_met(product_level, hazard_type, storm):
    if product_level not in ("WARNING", "ADVISORY"):
        return True  # WATCH/OUTLOOK carry no reading-based criterion
    r = storm_readings(storm)
    wind = _dec(r["max_wind_mph"])
    hail = _dec(r["max_hail_inches"])
    rain = _dec(r["rainfall_rate_in_hr"])
    rotation = bool(r["rotation_couplet"])
    debris = bool(r["debris_signature"])
    if product_level == "WARNING":
        if hazard_type == "SEVERE_THUNDERSTORM":
            return wind >= SEVERE_WARNING_WIND_MPH or hail >= SEVERE_WARNING_HAIL_IN
        if hazard_type == "TORNADO":
            return rotation or debris
        if hazard_type == "FLASH_FLOOD":
            return rain >= FLOOD_WARNING_RAIN_IN_HR
        if hazard_type == "HURRICANE":
            return wind >= HURRICANE_WARNING_WIND_MPH
        if hazard_type == "WINTER_STORM":
            return wind >= WINTER_WARNING_WIND_MPH
    else:  # ADVISORY floors; warning-strength readings always satisfy them
        if hazard_type == "SEVERE_THUNDERSTORM":
            return wind >= SEVERE_ADVISORY_WIND_MPH or hail >= SEVERE_ADVISORY_HAIL_IN
        if hazard_type == "TORNADO":
            return rotation
        if hazard_type == "FLASH_FLOOD":
            return rain >= FLOOD_ADVISORY_RAIN_IN_HR
        if hazard_type == "HURRICANE":
            return wind >= HURRICANE_ADVISORY_WIND_MPH
        if hazard_type == "WINTER_STORM":
            return wind >= WINTER_ADVISORY_WIND_MPH
    return False


def duration_minutes(effective_from, expires_at):
    return int((expires_at - effective_from).total_seconds()) // 60


def duration_in_range(hazard_type, effective_from, expires_at):
    lo, hi = DURATION_RANGES[hazard_type]
    minutes = duration_minutes(effective_from, expires_at)
    return lo <= minutes <= hi


# ---------------------------------------------------------------------------
# coordination requirement (frozen set at creation; satisfiability is live)
# ---------------------------------------------------------------------------
def compute_required_offices(zone_ids, overlaps, issuing_office_id, hazard_type):
    """Returns {office_id: kind} where kind is 'zone', 'polygon', or
    'hurricane' (how the office was pulled into the required set)."""
    kinds = {}
    for zid in (zone_ids or []):
        zone = STORE["zones"].get(zid)
        if zone and zone["office_id"] != issuing_office_id:
            kinds.setdefault(zone["office_id"], "zone")
    for zid in overlaps:
        zone = STORE["zones"].get(zid)
        if zone and zone["office_id"] != issuing_office_id:
            kinds.setdefault(zone["office_id"], "polygon")
    if hazard_type == "HURRICANE":
        for ag in STORE["agreements"].values():
            partner = None
            if ag["office_a_id"] == issuing_office_id:
                partner = ag["office_b_id"]
            elif ag["office_b_id"] == issuing_office_id:
                partner = ag["office_a_id"]
            if partner and partner != issuing_office_id and partner not in kinds:
                kinds[partner] = "hurricane"
    return kinds


def covering_agreement(office_a_id, office_b_id, hazard_type=None):
    for ag in STORE["agreements"].values():
        if {ag["office_a_id"], ag["office_b_id"]} == {office_a_id, office_b_id}:
            if hazard_type is None or hazard_type in ag["hazard_types"]:
                return ag
    return None


def unsatisfiable_required(product):
    """Required offices lacking a hazard-covering agreement, in deterministic
    check order: zone-listed, then polygon-overlap, then hurricane partners."""
    kinds = product.get("_required_offices", {})
    issuing = product["issuing_office_id"]
    hazard = product["hazard_type"]
    result = []
    for kind in ("zone", "polygon", "hurricane"):
        for office_id, k in kinds.items():
            if k != kind:
                continue
            if covering_agreement(issuing, office_id, hazard) is None:
                result.append((office_id, k))
    return result


# ---------------------------------------------------------------------------
# WEA message rendering (record creation on WEA channels + preview)
# ---------------------------------------------------------------------------
def render_wea(product, channel):
    """Pinned evaluation order: included set computed once, render, drop the
    smallest-overlap zone (ties: lexicographically greatest zone_code) while
    over budget and >1 zone remains; threshold never recomputed. Returns
    (message, included_zone_ids, dropped_zone_ids, char_count, would_overflow).
    """
    budget = min(WEA_ABSOLUTE_MAX_CHARS, channel["max_message_chars"])
    overlaps = product.get("_overlap_pct", {})
    zones = [
        STORE["zones"][zid] for zid in product["resolved_zone_ids"] if zid in STORE["zones"]
    ]
    zones.sort(key=lambda z: z["zone_code"])

    def render(zs):
        csv = ",".join(z["zone_code"] for z in zs)
        exp = product["expires_at"]
        stamp = "{:02d}{:02d}Z".format(exp.hour, exp.minute)
        return "WEA " + product["hazard_type"] + " " + product["damage_threat"] + " " + csv + " " + stamp

    surviving = list(zones)
    dropped = []
    message = render(surviving)
    while len(message) > budget and len(surviving) > 1:
        min_pct = min(overlaps.get(z["id"], Decimal("0")) for z in surviving)
        candidates = [z for z in surviving if overlaps.get(z["id"], Decimal("0")) == min_pct]
        victim = max(candidates, key=lambda z: z["zone_code"])
        surviving.remove(victim)
        dropped.append(victim["id"])
        message = render(surviving)
    return message, [z["id"] for z in surviving], dropped, len(message), len(message) > budget


def eligible_channels(product):
    """ACTIVE channels whose supports_levels include the product's level."""
    return [
        ch
        for ch in sorted(STORE["channels"].values(), key=lambda c: c["_seq"])
        if ch["status"] == "ACTIVE" and product["product_level"] in ch["supports_levels"]
    ]


# ---------------------------------------------------------------------------
# product window overlap conflict (issue time)
# ---------------------------------------------------------------------------
def find_overlap_conflict(product, effective_from):
    for other in STORE["products"].values():
        if other["id"] == product["id"]:
            continue
        if other["issuing_office_id"] != product["issuing_office_id"]:
            continue
        if other["hazard_type"] != product["hazard_type"]:
            continue
        if other["product_level"] != product["product_level"]:
            continue
        if other["status"] != "ISSUED":
            continue
        if product.get("supersedes_product_id") and other["id"] == product["supersedes_product_id"]:
            continue
        # half-open window intersection; mere adjacency is allowed
        if not (effective_from < other["expires_at"] and other["effective_from"] < product["expires_at"]):
            continue
        if set(product["resolved_zone_ids"]) & set(other["resolved_zone_ids"]):
            return other
    return None


# ---------------------------------------------------------------------------
# verification matching + statistics aggregation (PRD §3.8)
# ---------------------------------------------------------------------------
def event_matches_product(event, product, variant):
    if event["status"] != "CONFIRMED":
        return False
    if event["hazard_type"] != product["hazard_type"]:
        return False
    if product["product_level"] != "WARNING":
        return False
    if product.get("issued_at") is None:
        return False
    we = window_end(product)
    if we is None:
        return False
    if not (product["issued_at"] <= event["observed_at"] < we):
        return False
    if variant == "POLYGON_STRICT":
        polygon = product.get("polygon")
        if not polygon:
            return False
        return point_in_polygon(event["location_lat"], event["location_lon"], polygon["vertices"])
    return event["zone_id"] in product["resolved_zone_ids"]  # COUNTY_FALLBACK


def matched_products_for_event(event):
    """POLYGON_STRICT across all offices' products (adjudication rule)."""
    matches = [
        p
        for p in STORE["products"].values()
        if event_matches_product(event, p, "POLYGON_STRICT")
    ]
    matches.sort(key=lambda p: p["_seq"])
    return matches


def compute_statistic(office_id, hazard_type, period_start, period_end, variant):
    warnings = [
        p
        for p in STORE["products"].values()
        if p["issuing_office_id"] == office_id
        and p["hazard_type"] == hazard_type
        and p["product_level"] == "WARNING"
        and p.get("issued_at") is not None
        and period_start <= p["issued_at"] < period_end
    ]
    events = [
        e
        for e in STORE["vevents"].values()
        if e["status"] == "CONFIRMED"
        and e["hazard_type"] == hazard_type
        and e["zone_id"] in STORE["zones"]
        and STORE["zones"][e["zone_id"]]["office_id"] == office_id
        and period_start <= e["observed_at"] < period_end
    ]
    warned_event_ids = set()
    per_event_lead = {}
    warning_matched = {w["id"]: False for w in warnings}
    for event in events:
        matching = [w for w in warnings if event_matches_product(event, w, variant)]
        if matching:
            warned_event_ids.add(event["id"])
            earliest = min(w["issued_at"] for w in matching)
            lead_seconds = int((event["observed_at"] - earliest).total_seconds())
            per_event_lead[event["id"]] = lead_seconds // 60  # floor to whole minutes FIRST
            for w in matching:
                warning_matched[w["id"]] = True
    total_warnings = len(warnings)
    events_total = len(events)
    events_warned = len(warned_event_ids)
    events_unwarned = events_total - events_warned
    false_alarms = sum(1 for matched in warning_matched.values() if not matched)
    pod = None
    if events_total > 0:
        pod = float(
            (Decimal(events_warned) / Decimal(events_total)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
        )
    far = None
    if total_warnings > 0:
        far = float(
            (Decimal(false_alarms) / Decimal(total_warnings)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
        )
    avg_lead = None
    if per_event_lead:
        mean = Decimal(sum(per_event_lead.values())) / Decimal(len(per_event_lead))
        avg_lead = float(mean.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return {
        "total_warnings": total_warnings,
        "events_total": events_total,
        "events_warned": events_warned,
        "events_unwarned": events_unwarned,
        "false_alarms": false_alarms,
        "pod": pod,
        "far": far,
        "avg_lead_time_minutes": avg_lead,
    }


def derive_performance_band(statistic):
    """Strict inequalities: far exactly 0.70 and pod exactly 0.500 stay SATISFACTORY."""
    far = statistic["far"]
    pod = statistic["pod"]
    if far is not None and _dec(far) > FAR_REVIEW_THRESHOLD:
        return "REVIEW_REQUIRED"
    if pod is not None and _dec(pod) < POD_REVIEW_THRESHOLD:
        return "REVIEW_REQUIRED"
    return "SATISFACTORY"


# ---------------------------------------------------------------------------
# evacuation re-entry buffer (order time)
# ---------------------------------------------------------------------------
def evacuation_buffer_conflict(action):
    if action["action_type"] != "EVACUATION":
        return False
    for other in STORE["emactions"].values():
        if other["id"] == action["id"]:
            continue
        if other["zone_id"] != action["zone_id"]:
            continue
        if other["action_type"] != "EVACUATION":
            continue
        if other["status"] not in ("ORDERED", "LIFTED"):
            continue
        prior_end = other["lifted_at"] if other.get("lifted_at") is not None else other["effective_until"]
        if action["effective_from"] < prior_end + timedelta(minutes=EVAC_REENTRY_BUFFER_MINUTES):
            return True
    return False
