"""Route and Itinerary derivations, posture machine, demand curves.

Everything here reads/writes DB. Derived fields are recomputed on demand from
the store so that a fresh process boot yields identical answers with no
carried-over state.
"""

from decimal import Decimal

from db import iso, DB, days_later, dec, public, r2, touch
from errors import fail
from services import calc

ROUTE_DEFAULTS = {
    "travel_class": "ECO",
    "peak_price_day_index": 0,
    "seats_left": 9,
    "volatility_index": 0.20,
    "hedge_ratio_pct": 0.60,
    "max_guarantee_exposure_cents": 50000,
    "default_disruption_probability": 0.25,
    "disruption_severity_index": 0.1429,
    "protection_base_rate": 0.25,
    "protection_floor_rate": 0.20,
    "cancel_minimum_disruption": 0.30,
    "disclosure_version": 1,
}

POSTURES = ("ACTIVE", "SURGE", "RESTRICTED", "CLOSED")
TRAVEL_CLASSES = ("ECO", "PREMIUM", "BUSINESS")
TRAVEL_STATUSES = ("PLANNED", "WATCHING", "BOOKED", "CANCELLED")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def route_or_404(route_id):
    route = DB.routes.get(route_id)
    if route is None:
        fail("ERR_ROUTE_NOT_FOUND", "no route %s" % route_id)
    return route


def itinerary_or_404(itinerary_id):
    itinerary = DB.itineraries.get(itinerary_id)
    if itinerary is None:
        fail("ERR_ITINERARY_NOT_FOUND", "no itinerary %s" % itinerary_id)
    return itinerary


def latest_curve(route_id):
    """The most recently published curve for a route, or None."""
    curves = [c for c in DB.all("demand_curves") if c["route_id"] == route_id]
    if not curves:
        return None
    curves.sort(key=lambda c: (c.get("_published_seq", 0), c["id"]))
    return curves[-1]


def current_day_index():
    """Demand-curve day index for the clock reading, clamped to 0..4."""
    start = DB.clock.current.replace(hour=0, minute=0, second=0, microsecond=0)
    origin = start.replace(month=9, day=1)
    delta = int((start - origin).days)
    return max(0, min(4, delta))


def route_base_fare(route):
    """active_route_base_fare_cents = round_half_up(base x demand multiplier).

    The multiplier is the live SURGE uplift applied to the route's
    `base_fare_cents`; it is exactly 1.0 in every other posture.
    """
    value = dec(route["base_fare_cents"]) * dec(route["peak_day_demand_multiplier"])
    return calc._json_money(value)


def surge_multiplier(route):
    """Read the multiplier off the route's posture and curve state."""
    return dec("1.5") if route["posture"] == "SURGE" else dec("1.0")


def curves_of_route(route_id):
    return [c for c in DB.all("demand_curves") if c["route_id"] == route_id]


# --------------------------------------------------------------------------
# Itinerary derivations
# --------------------------------------------------------------------------

def observations_of(itinerary_id):
    obs = [o for o in DB.all("price_observations")
           if o["itinerary_id"] == itinerary_id]
    obs.sort(key=lambda o: (o["_observed_seq"], o["id"]))
    return obs


def arrival_fare(itinerary_id, at_instant=None):
    """Latest observation at or before `at_instant` (None = now). Returns None
    when the itinerary has no observation at all."""
    obs = observations_of(itinerary_id)
    if not obs:
        return None
    if at_instant is None:
        return int(obs[-1]["fare_cents"])
    eligible = [o for o in obs if o["_observed_dt"] <= at_instant]
    if not eligible:
        return None
    return int(eligible[-1]["fare_cents"])


def derive_itinerary(itinerary):
    """Re-derive the curve fields and the observation ladder of an itinerary."""
    route = DB.routes.get(itinerary["route_id"])
    obs = observations_of(itinerary["id"])
    itinerary["observed_fares_cents"] = [int(o["fare_cents"]) for o in obs]
    if obs:
        itinerary["last_observed_fare_cents"] = int(obs[-1]["fare_cents"])
        itinerary["listed_fare_cents"] = int(obs[-1]["fare_cents"])

    curve = latest_curve(itinerary["route_id"])
    if route is None or curve is None:
        itinerary["demand_curve_price_cents"] = 0
        itinerary["each_day_disruption_fare_cents"] = 0
        itinerary["fare_tier_ceiling_cents"] = 0
        return itinerary

    prices = curve["each_day_prices_cents"]
    idx = max(0, min(len(prices) - 1, current_day_index()))
    day_price = int(prices[idx])
    itinerary["demand_curve_price_cents"] = day_price
    # The disruption fare is the day's CURVE price scaled by the route's
    # disruption severity, not the live observation: it is the published
    # forecast the product is priced against and is stable across observation
    # appends (PRD §2.14, §3.8).
    itinerary["each_day_disruption_fare_cents"] = r2(
        dec(day_price) * dec(route["disruption_severity_index"]))
    itinerary["fare_tier_ceiling_cents"] = calc.tier_ceiling(day_price)
    return itinerary


def derive_route(route):
    """Re-derive every route-level computed field from the store."""
    # The live demand multiplier is read off the posture, so the base fare a
    # freeze pins (and the exposure chain measures against) is the uplifted one
    # while the route is in SURGE.
    route["peak_day_demand_multiplier"] = float(surge_multiplier(route))
    freezes = [f for f in DB.all("price_freezes") if f["_route_id"] == route["id"]]
    open_states = ("HELD", "FROZEN", "CLAIM_PENDING")
    route["open_freeze_count"] = len([f for f in freezes if f["status"] in open_states])

    curves = curves_of_route(route["id"])
    route["curve_published"] = bool(curves)
    highest = 0
    for curve in curves:
        if curve["each_day_prices_cents"]:
            highest = max(highest, max(curve["each_day_prices_cents"]))
    route["highest_curve_price_cents"] = highest

    reserved = 0
    pooled = 0
    for freeze in freezes:
        if freeze["status"] in ("EXPIRED", "CANCELLED", "CONVERTED"):
            continue
        largest_payout = 0
        for claim in DB.all("claims"):
            if claim["freeze_id"] != freeze["id"]:
                continue
            if claim["claim_status"] in ("REJECTED", "SETTLED_WITH_PURCHASE"):
                continue
            largest_payout = max(largest_payout, int(claim.get("payout_cents") or 0))
        reserved += max(int(freeze.get("capped_impact_cents") or 0), largest_payout)
        pooled += int(freeze.get("unhedged_exposure_cents") or 0)

    route["reserved_exposure_cents"] = reserved
    route["pooled_exposure_cents"] = pooled
    route["available_exposure_cents"] = int(route["war_chest_cents"]) - reserved
    return route


def region_postal_rederive(region, directly_mutated=None):
    """Full regional postural re-derivation (PRD §2.11).

    Visits every route sharing `region` in ascending created_at order, applies
    the pool-driven drives, increments each re-derived route's version, and
    clears the reason code of any route that leaves RESTRICTED (a second
    version bump for that route).
    """
    pool = pool_for_region(region)
    absorbed = int(pool["absorbed_regression_cents"]) if pool else 0
    pooled = region_pooled_exposure(region)

    routes = [r for r in DB.all("routes") if r["region"] == region]
    routes.sort(key=lambda r: (r["created_at"], r["id"]))

    for route in routes:
        if route["posture"] == "CLOSED":
            continue
        before = route["posture"]
        if before == "RESTRICTED" and absorbed == 0 and route.get("_pool_driven"):
            # RESTRICTED -> ACTIVE is the pool's release arc: a route the
            # region's absorbed regression drove into RESTRICTED recovers once
            # that regression returns to zero (PRD §2.11 / §3.10). A RESTRICTED
            # posture an operator set for its own reason is left alone. A SURGE
            # route is never demoted here either — the sanctioned SURGE ->
            # ACTIVE recovery is a separate transition with its own
            # precondition (the region's pooled exposure recomputing to zero).
            route["posture"] = "ACTIVE"
            route["posture_reason_code"] = ""
            route["_pool_driven"] = False
        elif absorbed > 0 and before in ("ACTIVE", "SURGE"):
            route["posture"] = "RESTRICTED"
            route["posture_reason_code"] = "REGIONAL_POOL_BREACH"
            route["_pool_driven"] = True
        route["peak_day_demand_multiplier"] = float(surge_multiplier(route))
        if route is not directly_mutated:
            touch(route)
        if before == "RESTRICTED" and route["posture"] != "RESTRICTED":
            touch(route)
        rebalance_route(route)


def region_pooled_exposure(region):
    """Sum of unhedged_exposure over the region's routes with open freezes."""
    total = 0
    open_states = ("HELD", "FROZEN", "CLAIM_PENDING")
    route_ids = {r["id"] for r in DB.all("routes") if r["region"] == region}
    for freeze in DB.all("price_freezes"):
        if freeze["_route_id"] in route_ids and freeze["status"] in open_states:
            total += int(freeze.get("unhedged_exposure_cents") or 0)
    return total


def pool_for_region(region):
    for pool in DB.all("risk_pools"):
        if pool["region"] == region:
            return pool
    return None


# --------------------------------------------------------------------------
# Freeze exposure plumbing (thin wrapper: the rule itself lives in calc)
# --------------------------------------------------------------------------

def freeze_active_base(route, freeze):
    if freeze.get("migrated_manifest"):
        return int(freeze.get("manifest_fare_cents") or 0)
    return route_base_fare(route)


def rebalance_freeze(route, freeze):
    """guarantee_hedge_rebalance for one freeze."""
    itinerary_id = freeze["itinerary_id"]
    if freeze["status"] in ("DRAFT", "HELD"):
        arrival = arrival_fare(itinerary_id)
        chain = calc.exposure_chain(
            route, freeze, arrival, freeze_active_base(route, freeze))
        freeze.update({
            "overshoot_cents": chain["overshoot_cents"],
            "capped_impact_cents": chain["capped_impact_cents"],
            "exposure_cents": chain["exposure_cents"],
            "hedged_exposure_cents": chain["hedged_exposure_cents"],
            "unhedged_exposure_cents": chain["unhedged_exposure_cents"],
            "guaranteed_ceiling_cents": chain["guaranteed_ceiling_cents"],
        })
    elif freeze["status"] in ("FROZEN", "CLAIM_PENDING", "CLAIMED"):
        # PRD §3.4: a FROZEN/CLAIM_PENDING/CLAIMED freeze "re-derives the whole
        # chain against the live arrival observation". Only `exposure_cents` is
        # pinned to the freeze-time figures and never re-derived.
        arrival = arrival_fare(itinerary_id)
        chain = calc.exposure_chain(
            route, freeze, arrival, freeze_active_base(route, freeze))
        for key in ("overshoot_cents", "capped_impact_cents", "hedged_exposure_cents",
                    "unhedged_exposure_cents", "guaranteed_ceiling_cents"):
            freeze[key] = chain[key]
    return freeze


def rebalance_route(route):
    """Re-derive the exposure chain for every open freeze on a route."""
    for freeze in DB.all("price_freezes"):
        if freeze["_route_id"] != route["id"]:
            continue
        if freeze["status"] in ("DRAFT", "HELD", "FROZEN", "CLAIM_PENDING", "CLAIMED"):
            rebalance_freeze(route, freeze)
    derive_route(route)
    return route


def rebalance_region(region):
    for route in DB.all("routes"):
        if route["region"] == region:
            rebalance_route(route)


# --------------------------------------------------------------------------
# Route lifecycle
# --------------------------------------------------------------------------

def register_route(data):
    from middleware import as_int, as_int_array, as_num, as_str, as_enum, field
    origin = as_str(data, "origin_airport")
    destination = as_str(data, "destination_airport")
    flight_number = as_str(data, "flight_number")
    region = as_str(data, "region")
    base_fare_cents = as_int(data, "base_fare_cents")
    band = as_int_array(data, "fare_band_cents")
    headline = as_str(data, "disclosure_headline")

    if len(origin) != 3 or not origin.isupper() or not origin.isalpha():
        fail("ERR_INVALID_REQUEST", "origin_airport must be three uppercase IATA letters")
    if len(destination) != 3 or not destination.isupper() or not destination.isalpha():
        fail("ERR_INVALID_REQUEST", "destination_airport must be three uppercase IATA letters")
    if base_fare_cents < 1:
        fail("ERR_INVALID_REQUEST", "base_fare_cents must be at least 1 cent")
    if len(band) != 5:
        fail("ERR_INVALID_REQUEST", "fare_band_cents must have exactly five entries")

    travel_class = as_enum(data, "travel_class", TRAVEL_CLASSES, required=False,
                           default=ROUTE_DEFAULTS["travel_class"])
    hedge_ratio = as_num(data, "hedge_ratio_pct", required=False,
                         default=ROUTE_DEFAULTS["hedge_ratio_pct"])
    if not (0 < dec(hedge_ratio) <= dec("0.90")):
        fail("ERR_INVALID_REQUEST", "hedge_ratio_pct must satisfy 0 < value <= 0.90")

    row = {
        "origin_airport": origin,
        "destination_airport": destination,
        "flight_number": flight_number,
        "travel_class": travel_class,
        "region": region,
        "base_fare_cents": base_fare_cents,
        "fare_band_cents": band,
        "peak_price_day_index": as_int(data, "peak_price_day_index", required=False,
                                       default=ROUTE_DEFAULTS["peak_price_day_index"]),
        "seats_left": as_int(data, "seats_left", required=False,
                             default=ROUTE_DEFAULTS["seats_left"]),
        "volatility_index": as_num(data, "volatility_index", required=False,
                                   default=ROUTE_DEFAULTS["volatility_index"]),
        "hedge_ratio_pct": hedge_ratio,
        "max_guarantee_exposure_cents": as_int(
            data, "max_guarantee_exposure_cents", required=False,
            default=ROUTE_DEFAULTS["max_guarantee_exposure_cents"]),
        "default_disruption_probability": as_num(
            data, "default_disruption_probability", required=False,
            default=ROUTE_DEFAULTS["default_disruption_probability"]),
        "disruption_severity_index": as_num(
            data, "disruption_severity_index", required=False,
            default=ROUTE_DEFAULTS["disruption_severity_index"]),
        "protection_base_rate": as_num(data, "protection_base_rate", required=False,
                                       default=ROUTE_DEFAULTS["protection_base_rate"]),
        "protection_floor_rate": as_num(data, "protection_floor_rate", required=False,
                                        default=ROUTE_DEFAULTS["protection_floor_rate"]),
        "cancel_minimum_disruption": as_num(
            data, "cancel_minimum_disruption", required=False,
            default=ROUTE_DEFAULTS["cancel_minimum_disruption"]),
        "disclosure_version": ROUTE_DEFAULTS["disclosure_version"],
        "peak_day_demand_multiplier": 1.0,
        "disclosure_headline": headline,
        "war_chest_cents": 0,
        "reserved_exposure_cents": 0,
        "available_exposure_cents": 0,
        "pooled_exposure_cents": 0,
        "posture": "ACTIVE",
        "posture_reason_code": "",
        "_pool_driven": False,
        "open_freeze_count": 0,
        "curve_published": False,
        "highest_curve_price_cents": 0,
    }
    from db import new_row
    row = new_row(**row)
    DB.insert("routes", row)
    return row


def patch_route(route, data):
    from middleware import as_int, as_int_array, as_num, as_str
    touched = False
    if "base_fare_cents" in data:
        value = as_int(data, "base_fare_cents")
        if value < 1:
            fail("ERR_INVALID_REQUEST", "base_fare_cents must be at least 1 cent")
        route["base_fare_cents"] = value
        touched = True
    if "fare_band_cents" in data:
        band = as_int_array(data, "fare_band_cents")
        if len(band) != 5:
            fail("ERR_INVALID_REQUEST", "fare_band_cents must have exactly five entries")
        route["fare_band_cents"] = band
        touched = True
    if "hedge_ratio_pct" in data:
        value = as_num(data, "hedge_ratio_pct")
        if not (0 < dec(value) <= dec("0.90")):
            fail("ERR_INVALID_REQUEST", "hedge_ratio_pct must satisfy 0 < value <= 0.90")
        route["hedge_ratio_pct"] = value
        touched = True
    if "max_guarantee_exposure_cents" in data:
        route["max_guarantee_exposure_cents"] = as_int(data, "max_guarantee_exposure_cents")
        touched = True
    if "disclosure_headline" in data:
        headline = as_str(data, "disclosure_headline")
        if headline != route["disclosure_headline"]:
            route["disclosure_headline"] = headline
            route["disclosure_version"] = int(route["disclosure_version"]) + 1
            touched = True

    if touched:
        rebalance_route(route)
        touch(route)
    return route


def posture_transition(route, data):
    """Operator-controlled posture move. The derived SURGE->RESTRICTED arc is
    not reachable here (PRD §3.10)."""
    from middleware import as_int, as_str
    to_posture = as_str(data, "to_posture")
    reason = as_str(data, "posture_reason_code")
    expected = as_int(data, "expected_route_version")

    if to_posture not in POSTURES:
        fail("ERR_INVALID_REQUEST", "to_posture is not a declared posture")
    if expected != int(route["version"]):
        fail("ERR_STALE_VERSION", "expected_route_version does not match the route version")

    current = route["posture"]
    if to_posture == current:
        # A request to move a route to the posture it already holds is a no-op
        # rather than a self-transition error: the region's re-derivation may
        # already have applied the operator's intended posture.
        return route
    allowed = {
        "ACTIVE": {"SURGE", "RESTRICTED", "CLOSED"},
        "SURGE": {"ACTIVE", "RESTRICTED", "CLOSED"},
        # PRD §3.10: the reachable operator transitions from RESTRICTED are the
        # CLOSED terminal move; the RESTRICTED -> ACTIVE recovery "is driven by
        # the sweep" (a full postural re-derivation once the region's pool's
        # absorbed regression returns to zero), not by the operator endpoint.
        "RESTRICTED": {"ACTIVE", "CLOSED"},
        "CLOSED": set(),
    }
    if to_posture not in allowed.get(current, set()):
        fail("ERR_INVALID_STATE",
             "cannot move a route from %s to %s" % (current, to_posture))

    if to_posture == "CLOSED":
        for freeze in DB.all("price_freezes"):
            if freeze["_route_id"] == route["id"] and freeze["status"] in (
                    "FROZEN", "CLAIM_PENDING", "CLAIMED"):
                fail("ERR_INVALID_STATE",
                     "route closure requires no freeze in FROZEN/CLAIM_PENDING/CLAIMED")
        close_route_cascade(route)

    if to_posture == "SURGE":
        route["posture"] = "SURGE"
        route["posture_reason_code"] = reason
        route["peak_day_demand_multiplier"] = float(surge_multiplier(route))
        touch(route)
        region_postal_rederive(route["region"], directly_mutated=route)
        return route

    if to_posture == "RESTRICTED":
        route["posture"] = "RESTRICTED"
        route["posture_reason_code"] = reason
        route["_pool_driven"] = False
        route["peak_day_demand_multiplier"] = float(surge_multiplier(route))
        touch(route)
        region_postal_rederive(route["region"], directly_mutated=route)
        return route

    if to_posture == "ACTIVE":
        if current == "SURGE" and region_pooled_exposure(route["region"]) != 0:
            fail("ERR_INVALID_STATE",
                 "SURGE -> ACTIVE requires the region's pooled exposure to be zero")
        route["posture"] = "ACTIVE"
        route["posture_reason_code"] = ""
        route["_pool_driven"] = False
        route["peak_day_demand_multiplier"] = float(surge_multiplier(route))
        touch(route)
        region_postal_rederive(route["region"], directly_mutated=route)
        return route

    return route


def close_route_cascade(route):
    route["posture"] = "CLOSED"
    route["posture_reason_code"] = "CLOSED"
    itinerary_ids = {i["id"] for i in DB.all("itineraries") if i["route_id"] == route["id"]}
    for product in DB.all("protections"):
        if product["_itinerary_id"] in itinerary_ids and product["lifecycle_status"] in (
                "QUOTED", "ACTIVE"):
            product["lifecycle_status"] = "TERMINATED"
            product["terminated_hard"] = True
            touch(product)
    touch(route)
    return route


def derive_all():
    """Full derivation pass: region postures, itineraries, freeze chains."""
    regions = {r["region"] for r in DB.all("routes")}
    for region in sorted(regions):
        region_postal_rederive(region)
    for itinerary in DB.all("itineraries"):
        route = DB.routes.get(itinerary["route_id"])
        derive_itinerary(itinerary)
        if route is not None:
            itinerary["guarantee_locked"] = freeze_locks(itinerary["id"])
            itinerary["watch_armed"] = any(
                w["itinerary_id"] == itinerary["id"] and
                w["notification_status"] in ("ARMED", "NOTIFIED", "WAIT", "BUY_NOW")
                for w in DB.all("watch_subscriptions"))
    for route in DB.all("routes"):
        rebalance_route(route)
    for pool in DB.all("risk_pools"):
        derive_pool(pool)


def freeze_locks(itinerary_id):
    return any(
        f["itinerary_id"] == itinerary_id and f["status"] in ("HELD", "FROZEN")
        for f in DB.all("price_freezes"))


def derive_pool(pool):
    region_routes = [r for r in DB.all("routes") if r["region"] == pool["region"]]
    route_ids = {r["id"] for r in region_routes}
    pool["available_capacity_cents"] = (
        sum(int(r["war_chest_cents"]) for r in region_routes) -
        int(pool["absorbed_regression_cents"]))
    pool["bound_position_count"] = len([
        p for p in DB.all("hedging_positions")
        if p["route_id"] in route_ids and p["status"] in ("OPEN", "HEDGED")])
    return pool


# --------------------------------------------------------------------------
# Demand curves and observations
# --------------------------------------------------------------------------

def publish_curve(data):
    from middleware import as_int, as_int_array, as_str, as_ts
    route = route_or_404(as_str(data, "route_id"))
    price_date = as_ts(data, "price_date")
    prices = as_int_array(data, "each_day_prices_cents", length=5)
    seats = as_int_array(data, "seats_left_at_each_day", length=5)
    if any(p < 1 for p in prices):
        fail("ERR_INVALID_REQUEST",
             "each_day_prices_cents must have exactly 5 strictly positive entries")
    if seats[0] < seats[4]:
        fail("ERR_INVALID_REQUEST",
             "seats_left_at_each_day[0] must be >= seats_left_at_each_day[4]")

    existing = None
    for curve in DB.all("demand_curves"):
        if curve["route_id"] == route["id"] and curve["price_date"] == price_date:
            existing = curve
            break

    if existing is not None:
        existing["each_day_prices_cents"] = prices
        existing["seats_left_at_each_day"] = seats
        existing["published_at"] = DB.clock.stamp()
        existing["_published_seq"] = DB.next_seq()
        curve = touch(existing)
    else:
        from db import new_row
        curve = new_row(
            route_id=route["id"],
            price_date=price_date,
            each_day_prices_cents=prices,
            seats_left_at_each_day=seats,
            published_at=DB.clock.stamp(),
            _published_seq=DB.next_seq(),
            _price_date_iso=iso(price_date),
        )
        DB.insert("demand_curves", curve)

    derive_route(route)
    for itinerary in DB.all("itineraries"):
        if itinerary["route_id"] != route["id"]:
            continue
        derive_itinerary(itinerary)
        touch(itinerary)
    return curve


def append_observation(data):
    from middleware import as_int, as_str
    route = route_or_404(as_str(data, "route_id"))
    itinerary = itinerary_or_404(as_str(data, "itinerary_id"))
    fare_cents = as_int(data, "fare_cents")
    seats_left = as_int(data, "seats_left")

    if fare_cents < 1:
        fail("ERR_INVALID_REQUEST", "fare_cents must be at least 1 cent")
    if itinerary["route_id"] != route["id"]:
        fail("ERR_ROUTE_ITINERARY_MISMATCH",
             "the itinerary does not belong to the named route")

    from db import new_row
    observation = new_row(
        route_id=route["id"],
        itinerary_id=itinerary["id"],
        fare_cents=fare_cents,
        seats_left=seats_left,
        observed_at=DB.clock.stamp(),
        _observed_seq=DB.next_seq(),
        _observed_dt=DB.clock.now(),
    )
    DB.insert("price_observations", observation)
    route["seats_left"] = seats_left

    derive_itinerary(itinerary)
    touch(itinerary)

    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] != itinerary["id"]:
            continue
        if freeze["status"] in ("FROZEN", "CLAIM_PENDING", "CLAIMED"):
            rebalance_freeze(route, freeze)
    rebalance_route(route)
    return observation