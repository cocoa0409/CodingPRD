"""Payment ledger and the hedging book (positions, pools, regression sweeps)."""

from datetime import timedelta
from decimal import Decimal

from db import iso, DB, dec, new_row, r2, touch
from errors import fail
from middleware import as_int, as_str, as_ts
from services import calc
from services.routes_svc import (
    derive_pool, derive_route, rebalance_freeze, region_postal_rederive,
)

PAYMENT_KINDS = ("DEPOSIT", "MEMBERSHIP_1", "MEMBERSHIP_2", "PREMIUM",
                 "CHANGE_FEE", "HEDGE_TOPUP")
PAYMENT_STATUSES = ("AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED",
                    "FORFEITED", "RETIRED")


def payment_or_404(payment_id):
    payment = DB.payments.get(payment_id)
    if payment is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no payment %s" % payment_id)
    return payment


def record_payment(data):
    from services.routes_svc import itinerary_or_404, route_or_404
    itinerary = itinerary_or_404(as_str(data, "itinerary_id"))
    kind = as_str(data, "payment_kind")
    if kind not in PAYMENT_KINDS:
        fail("ERR_INVALID_REQUEST", "payment_kind is not a declared kind")
    amount = as_int(data, "amount_cents")
    if amount < 1 or amount > 20000:
        fail("ERR_INVALID_REQUEST", "amount_cents must be between 1 and 20000")
    capture = bool(data.get("capture"))

    freeze_id = data.get("freeze_id")
    if freeze_id is not None:
        freeze_id = as_str(data, "freeze_id")
        if DB.price_freezes.get(freeze_id) is None:
            fail("ERR_FREEZE_NOT_FOUND", "no price freeze %s" % freeze_id)
    protection_id = data.get("protection_id")
    if protection_id is not None:
        protection_id = as_str(data, "protection_id")
        if DB.protections.get(protection_id) is None:
            fail("ERR_RESOURCE_NOT_FOUND", "no protection product %s" % protection_id)
    claim_id = data.get("claim_id")
    if claim_id is not None:
        claim_id = as_str(data, "claim_id")
        if DB.claims.get(claim_id) is None:
            fail("ERR_RESOURCE_NOT_FOUND", "no guarantee claim %s" % claim_id)

    payment = new_row(
        itinerary_id=itinerary["id"],
        freeze_id=freeze_id,
        protection_id=protection_id,
        claim_id=claim_id,
        payment_kind=kind,
        amount_cents=amount,
        refundable_remaining_cents=amount,
        status="AUTHORIZED",
        retired_reason="",
        allocations=[],
        _allocated=False,
    )
    DB.insert("payments", payment)
    if capture:
        capture_payment(payment)
    return payment


def capture_payment(payment):
    if payment["status"] in ("RETIRED", "FORFEITED"):
        fail("ERR_PAYMENT_RETIRED", "this payment can no longer be allocated")
    if payment["status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE",
             "only an AUTHORIZED payment can be captured")
    if payment["payment_kind"] not in PAYMENT_KINDS:
        fail("ERR_INVALID_REQUEST", "payment_kind is not a declared kind")

    amount = int(payment["amount_cents"])
    target = payment["payment_kind"]
    if payment.get("_allocated"):
        payment["status"] = "PARTIALLY_REFUNDED" if int(
            payment["refundable_remaining_cents"]) > 0 else "REFUNDED"
        touch(payment)
        return payment

    if target in ("DEPOSIT", "MEMBERSHIP_1"):
        freeze = DB.price_freezes.get(payment["freeze_id"])
        if freeze is not None:
            freeze["custody_held_cents"] = float(freeze["custody_held_cents"]) + amount
            touch(freeze)
        allocation_target = "CUSTODY"
    elif target == "MEMBERSHIP_2":
        itinerary = DB.itineraries[payment["itinerary_id"]]
        route = DB.routes[itinerary["route_id"]]
        route["war_chest_cents"] = int(route["war_chest_cents"]) + amount
        derive_route(route)
        allocation_target = "WAR_CHEST"
        # PRD §3.6: the war chest grows only through a hedge-rebalance event,
        # so the reserved exposure booked against it is recomputed here.
        for freeze in DB.all("price_freezes"):
            if freeze["_route_id"] == route["id"]:
                rebalance_freeze(route, freeze)
    elif target == "PREMIUM":
        product = DB.protections.get(payment["protection_id"])
        if product is not None:
            product["_premium_paid_cents"] = int(
                product.get("_premium_paid_cents", 0)) + amount
            touch(product)
        allocation_target = "PREMIUM"
    elif target == "CHANGE_FEE":
        allocation_target = "CHANGE_FEE"
        event = None
        for candidate in DB.all("change_events"):
            if candidate["_itinerary_id"] == payment["itinerary_id"]:
                event = candidate
        if event is not None:
            event["_change_fee_paid_cents"] = int(
                event.get("_change_fee_paid_cents", 0)) + amount
            touch(event)
    else:  # HEDGE_TOPUP is held for the next marks and credited nowhere.
        allocation_target = "HELD"

    payment["allocations"].append({
        "target": allocation_target,
        "amount_cents": amount,
        "applied_at": DB.clock.stamp(),
    })
    payment["_allocated"] = True
    payment["status"] = "CAPTURED"
    touch(payment)
    return payment


def capture(payment_id, data):
    payment = payment_or_404(payment_id)
    if payment["status"] in ("RETIRED", "FORFEITED"):
        fail("ERR_PAYMENT_RETIRED", "this payment can no longer be allocated")
    if payment["status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE", "only an AUTHORIZED payment can be captured")
    return capture_payment(payment)


def refund(payment_id, data):
    payment = payment_or_404(payment_id)
    refund_cents = as_int(data, "refund_cents")

    if payment["status"] in ("RETIRED", "FORFEITED"):
        fail("ERR_PAYMENT_RETIRED",
             "a retired or forfeited payment can neither be allocated nor refunded")
    # The §1.2 machine only admits a refund out of CAPTURED or PARTIALLY_REFUNDED.
    if payment["status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        fail("ERR_INVALID_STATE",
             "a payment in %s cannot be refunded" % payment["status"])
    if refund_cents < 1:
        fail("ERR_INVALID_REQUEST", "refund_cents must be at least 1")
    if refund_cents > int(payment["refundable_remaining_cents"]):
        fail("ERR_PAYMENT_OVER_ALLOCATED",
             "the refund would take refundable_remaining_cents below zero")

    payment["refundable_remaining_cents"] = (
        int(payment["refundable_remaining_cents"]) - refund_cents)
    payment["allocations"].append({
        "target": "REFUND",
        "amount_cents": refund_cents,
        "applied_at": DB.clock.stamp(),
    })
    if int(payment["refundable_remaining_cents"]) > 0:
        payment["status"] = "PARTIALLY_REFUNDED"
    else:
        payment["status"] = "REFUNDED"
    touch(payment)
    return payment


def retire_aged():
    now = DB.clock.now()
    for payment in DB.all("payments"):
        if payment["status"] != "AUTHORIZED":
            continue
        created = payment.get("_created_dt")
        if created is None:
            continue
        if now > created + timedelta(days=7):
            payment["status"] = "RETIRED"
            payment["retired_reason"] = "AUTHORIZATION_AGED"
            touch(payment)


# --------------------------------------------------------------------------
# Hedging positions
# --------------------------------------------------------------------------

def position_or_404(position_id):
    position = DB.hedging_positions.get(position_id)
    if position is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no hedging position %s" % position_id)
    return position


def open_position(data):
    from services.routes_svc import route_or_404, pool_for_region
    route = route_or_404(as_str(data, "route_id"))
    coverage_date = as_ts(data, "coverage_date")
    hedge_price = as_int(data, "hedge_price_cents")
    quantity = as_int(data, "contract_quantity_cents")
    expected = as_int(data, "expected_route_version")

    if route["posture"] not in ("ACTIVE", "SURGE"):
        fail("ERR_ROUTE_RESTRICTED",
             "a %s route admits no hedging position" % route["posture"])
    if int(route["version"]) != expected:
        fail("ERR_STALE_VERSION",
             "expected_route_version does not match the route version")

    pool = pool_for_region(route["region"])
    derive_pool(pool) if pool is not None else None
    if pool is not None and pool["status"] == "BOUND":
        fail("ERR_HEDGE_DUPLICATE_COVERAGE",
             "the region's bound position cap is reached")

    for existing in DB.all("hedging_positions"):
        if (existing["route_id"] == route["id"]
                and existing["_coverage_dt"] == coverage_date
                and int(existing["hedge_price_cents"]) == hedge_price):
            fail("ERR_HEDGE_DUPLICATE_COVERAGE",
                 "a position already exists for this route, date and fare")

    if pool is not None:
        bound = _region_bound_count(route["region"])
        if bound >= 4:
            fail("ERR_HEDGE_DUPLICATE_COVERAGE",
                 "the region's bound position cap of four is reached")

    position = new_row(
        route_id=route["id"],
        coverage_date=iso(coverage_date),
        _coverage_dt=coverage_date,
        hedge_price_cents=hedge_price,
        contract_quantity_cents=quantity,
        status="OPEN",
        projected_day_cost_cents=0,
        pool_id=pool["id"] if pool is not None else None,
        mark_value_cents=0,
        regression_reversed=False,
        absorption_released_cents=0,
        pool_binding_count=0,
    )
    position["pool_binding_count"] = _region_bound_count(route["region"]) + (
        1 if position["status"] in ("OPEN", "HEDGED") else 0)
    DB.insert("hedging_positions", position)
    touch(route)
    if pool is not None:
        _maybe_bind_pool(pool, route["region"])
    return position


def _region_bound_count(region):
    route_ids = {r["id"] for r in DB.all("routes") if r["region"] == region}
    dates = set()
    for position in DB.all("hedging_positions"):
        if position["route_id"] in route_ids and position["status"] in ("OPEN", "HEDGED"):
            dates.add((position["route_id"], position["_coverage_dt"]))
    return len(dates)


def _maybe_bind_pool(pool, region):
    if _region_bound_count(region) >= 4 and pool["status"] != "OPEN":
        pool["status"] = "BOUND"
        touch(pool)


def mark_position(position_id, data):
    position = position_or_404(position_id)
    route = DB.routes[position["route_id"]]
    projected = as_int(data, "projected_day_cost_cents")

    if route["posture"] not in ("ACTIVE", "SURGE"):
        fail("ERR_ROUTE_RESTRICTED",
             "a %s route admits no hedge mark" % route["posture"])

    if position["status"] == "OPEN":
        position["status"] = "HEDGED"
        position["projected_day_cost_cents"] = projected
        position["mark_value_cents"] = max(
            0, projected - int(position["hedge_price_cents"]))
    elif position["status"] == "HEDGED":
        pool = DB.risk_pools.get(position.get("pool_id")) if position.get("pool_id") else None
        absorbed = int(pool["absorbed_regression_cents"]) if pool else 0
        if projected < int(position["hedge_price_cents"]):
            if absorbed > 0:
                fail("ERR_INVALID_STATE",
                     "a HEDGED -> OPEN reversal is blocked while the pool has absorbed a regression")
            if not _region_has_surge(route["region"]):
                fail("ERR_INVALID_STATE",
                     "a HEDGED -> OPEN reversal requires a SURGE route in the region")
            position["status"] = "OPEN"
            position["mark_value_cents"] = 0
            position["regression_reversed"] = True
            position["projected_day_cost_cents"] = projected
        else:
            position["projected_day_cost_cents"] = projected
            position["mark_value_cents"] = max(
                0, projected - int(position["hedge_price_cents"]))
    else:
        fail("ERR_INVALID_STATE",
             "a position in %s cannot be marked" % position["status"])

    touch(position)
    return position


def _region_has_surge(region):
    return any(r["region"] == region and r["posture"] == "SURGE"
               for r in DB.all("routes"))


def settle_position(position_id, data):
    position = position_or_404(position_id)
    route = DB.routes[position["route_id"]]
    if position["status"] != "HEDGED":
        fail("ERR_INVALID_STATE", "only a HEDGED position can be settled")

    released = int(position["mark_value_cents"]) if route["posture"] == "SURGE" else 0
    position["status"] = "SETTLED"
    position["absorption_released_cents"] = released
    route["war_chest_cents"] = int(route["war_chest_cents"]) + released
    derive_route(route)
    touch(position)
    touch(route)
    return position


def lapse_positions():
    now = DB.clock.now()
    for position in DB.all("hedging_positions"):
        if position["status"] == "OPEN" and now > position["_coverage_dt"]:
            position["status"] = "LAPSED"
            touch(position)


def unlap_positions():
    for position in DB.all("hedging_positions"):
        if position["status"] != "LAPSED":
            continue
        pool = DB.risk_pools.get(position.get("pool_id")) if position.get("pool_id") else None
        resolved = _resolved_pool(position["route_id"])
        if resolved < calc.RISK_DESK_THRESHOLD_CENTS:
            position["status"] = "OPEN"
            touch(position)


def _resolved_pool(route_id):
    route = DB.routes.get(route_id)
    if route is None:
        return 0
    total = 0
    for position in DB.all("hedging_positions"):
        if position["route_id"] == route_id and position["status"] in ("OPEN", "HEDGED"):
            total += int(position["mark_value_cents"])
    return total


# --------------------------------------------------------------------------
# Risk pools
# --------------------------------------------------------------------------

def pool_or_404(pool_id):
    pool = DB.risk_pools.get(pool_id)
    if pool is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no risk pool %s" % pool_id)
    return pool


def open_pool(data):
    region = as_str(data, "region")
    code = as_str(data, "pool_code")
    for existing in DB.all("risk_pools"):
        if existing["region"] == region:
            fail("ERR_INVALID_STATE", "a pool already exists for this region")
    pool = new_row(
        region=region,
        pool_code=code,
        absorbed_regression_cents=0,
        available_capacity_cents=0,
        bound_position_count=0,
        status="OPEN",
    )
    DB.insert("risk_pools", pool)
    derive_pool(pool)
    return pool


def regression_sweep(data):
    pool = pool_or_404(as_str(data, "pool_id"))
    route_ids = {r["id"] for r in DB.all("routes") if r["region"] == pool["region"]}

    regressed = [p for p in DB.all("hedging_positions")
                 if p["route_id"] in route_ids and p["status"] == "HEDGED"
                 and int(p["projected_day_cost_cents"]) < int(p["hedge_price_cents"])]

    if not regressed:
        if pool["status"] == "ABSORBING":
            any_stressed = any(r["region"] == pool["region"] and r["posture"] in
                               ("SURGE", "RESTRICTED") for r in DB.all("routes"))
            if not any_stressed:
                pool["status"] = "OPEN"
                pool["absorbed_regression_cents"] = 0
                touch(pool)
        derive_pool(pool)
        return pool

    slot = 140 * max(1, len(route_ids))
    pool["absorbed_regression_cents"] = int(pool["absorbed_regression_cents"]) + slot
    pool["status"] = "ABSORBING"

    for position in regressed:
        route = DB.routes[position["route_id"]]
        credit = r2(dec(140) * dec(position["mark_value_cents"]) / dec(100))
        route["war_chest_cents"] = int(route["war_chest_cents"]) + credit
        derive_route(route)

    touch(pool)
    for route in DB.all("routes"):
        if route["region"] == pool["region"]:
            region_postal_rederive(pool["region"])
            break
    derive_pool(pool)
    return pool