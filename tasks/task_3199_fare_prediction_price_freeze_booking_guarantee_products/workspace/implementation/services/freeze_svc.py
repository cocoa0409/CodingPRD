"""PriceFreeze lifecycle: creation, activation, expiry, conversion, cancellation,
reinstatement, deposit custody and the guarantee exposure chain."""

from datetime import timedelta
from decimal import Decimal

from db import iso, DB, dec, new_row, r2, touch
from errors import fail
from middleware import as_bool, as_int, as_str
from services import calc
from services.routes_svc import (
    arrival_fare, derive_route, freeze_active_base, latest_curve,
    rebalance_freeze, rebalance_route, region_pooled_exposure, route_base_fare,
)

FREEZE_STATUSES = ("DRAFT", "HELD", "FROZEN", "CLAIM_PENDING", "CLAIMED",
                   "CONVERTED", "EXPIRED", "CANCELLED")


def freeze_or_404(freeze_id):
    freeze = DB.price_freezes.get(freeze_id)
    if freeze is None:
        fail("ERR_FREEZE_NOT_FOUND", "no price freeze %s" % freeze_id)
    return freeze


# --------------------------------------------------------------------------
# Disclosure gate (priority 18)
# --------------------------------------------------------------------------

def check_disclosure(route, data):
    version = as_int(data, "disclosure_version")
    acknowledged = as_bool(data, "disclosure_acknowledged")
    if version != int(route["disclosure_version"]) or not acknowledged:
        fail("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
             "the disclosed disclosure_version is stale or not acknowledged")


# --------------------------------------------------------------------------
# Exposure-cap gate (priority 14)
# --------------------------------------------------------------------------

def current_capped_impact(route, itinerary, manifest_fare_cents, cap_cents):
    arrival = arrival_fare(itinerary["id"])
    chain = calc.exposure_chain(route, {"manifest_fare_cents": manifest_fare_cents,
                                        "cap_cents": cap_cents}, arrival,
                                freeze_active_base(route, {
                                    "manifest_fare_cents": manifest_fare_cents,
                                    "migrated_manifest": False}))
    return chain


def check_exposure_cap(route, projected_capped_impact, previous=0):
    """PRD §3.3: a freeze whose capped impact "would push the route's
    reserved_exposure_cents above the route's max_guarantee_exposure_cents" is
    refused. The gate fires only when the re-pinned contribution actually pushes
    the reservation higher and past the ceiling; a freeze whose contribution is
    already booked (its own draft-time reservation) and is not increasing does
    not push anything.
    """
    reserved = int(route["reserved_exposure_cents"])
    resulting = reserved - int(previous) + int(projected_capped_impact)
    if resulting > int(route["max_guarantee_exposure_cents"]) \
            and int(projected_capped_impact) > int(previous):
        fail("ERR_GUARANTEE_EXPOSURE_EXCEEDED",
             "reserved exposure would exceed the route's ceiling")


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------

def create_freeze(itinerary, data):
    expected = as_int(data, "expected_itinerary_version")
    deposit = as_int(data, "deposit_cents")
    if not (100 <= deposit <= 5000):
        fail("ERR_INVALID_REQUEST", "deposit_cents must be between 100 and 5000")

    route = DB.routes[itinerary["route_id"]]
    if int(itinerary["version"]) != expected:
        fail("ERR_STALE_VERSION",
             "expected_itinerary_version does not match the itinerary version")

    # The itinerary gate (PRD §2.6): a freeze is opened against an itinerary that
    # is still PLANNED or WATCHING, and the state gate outranks the disclosure and
    # schema checks that close the validation order (PRD §2.5).
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_INVALID_STATE",
             "a freeze may only be opened on a PLANNED or WATCHING itinerary")

    check_disclosure(route, data)

    manifest = int(route["base_fare_cents"])
    cap = r2(dec(manifest) * dec("1.4"))

    chain = current_capped_impact(route, itinerary, manifest, cap)
    derive_route(route)
    # PRD §3.3: the per-route exposure cap binds on activation and on claim
    # filing, not on first creation — a draft manifest is not yet reserved.
    # The cap is therefore NOT consulted here.

    freeze = new_row(
        itinerary_id=itinerary["id"],
        _route_id=route["id"],
        manifest_fare_cents=manifest,
        migrated_manifest=False,
        cap_cents=cap,
        deposit_cents=deposit,
        freeze_date=None,
        _freeze_dt=None,
        freeze_expires_at=None,
        _expires_dt=None,
        firm_tier_ceiling_cents=_firm_ceiling(itinerary),
        cap_tier_ceiling_cents=calc.tier_ceiling(cap),
        guaranteed_ceiling_cents=max(_firm_ceiling(itinerary), calc.tier_ceiling(cap)),
        overshoot_cents=chain["overshoot_cents"],
        capped_impact_cents=chain["capped_impact_cents"],
        exposure_cents=chain["exposure_cents"],
        guaranteed_ceiling_test_cents=max(_firm_ceiling(itinerary),
                                          calc.tier_ceiling(cap)),
        hedged_exposure_cents=chain["hedged_exposure_cents"],
        unhedged_exposure_cents=chain["unhedged_exposure_cents"],
        deposit_attributed_cents=0,
        membership_days_elapsed=0,
        pattern_day_count=0,
        custody_held_cents=0,
        custody_return_pending_cents=0,
        deposit_forfeited_cents=0,
        frozen_effective_at=None,
        deposit_integrity_flag="INTEGRITY_CONSISTENT",
        status="DRAFT",
    )
    DB.insert("price_freezes", freeze)

    itinerary["guarantee_locked"] = True
    touch(itinerary)
    rebalance_route(route)
    return freeze


def _firm_ceiling(itinerary):
    fare = int(itinerary.get("last_observed_fare_cents") or 0)
    if fare <= 0:
        return 0
    return calc.tier_ceiling(fare)


# --------------------------------------------------------------------------
# Activation
# --------------------------------------------------------------------------

def activate(freeze_id, data):
    freeze = freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    route = DB.routes[freeze["_route_id"]]
    expected = as_int(data, "expected_freeze_version")

    if freeze["status"] not in ("DRAFT", "HELD"):
        fail("ERR_INVALID_STATE",
             "a freeze in %s cannot be activated" % freeze["status"])
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_ITINERARY_NOT_PLANNED",
             "activation requires a PLANNED or WATCHING itinerary")
    if route["posture"] not in ("ACTIVE", "SURGE"):
        fail("ERR_ROUTE_RESTRICTED",
             "a %s route admits no freeze activation" % route["posture"])
    if int(freeze["version"]) != expected:
        fail("ERR_STALE_VERSION", "expected_freeze_version does not match the freeze version")

    if freeze["status"] == "DRAFT":
        active_base = route_base_fare(route)
        freeze["manifest_fare_cents"] = int(active_base)
        freeze["cap_cents"] = r2(dec(active_base) * dec("1.4"))
        freeze["firm_tier_ceiling_cents"] = _firm_ceiling(itinerary)
        freeze["cap_tier_ceiling_cents"] = calc.tier_ceiling(freeze["cap_cents"])
        freeze["guaranteed_ceiling_cents"] = freeze["guaranteed_ceiling_cents"] = max(
            freeze["firm_tier_ceiling_cents"], freeze["cap_tier_ceiling_cents"])
        freeze["guaranteed_ceiling_test_cents"] = freeze["guaranteed_ceiling_cents"]

        derive_route(route)
        arrival = arrival_fare(itinerary["id"])
        chain = calc.exposure_chain(route, freeze, arrival,
                                    freeze_active_base(route, freeze))
        # PRD §3.3: "A freeze whose capped impact would push the route's
        # reserved_exposure_cents above the route's max_guarantee_exposure_cents
        # is refused." The gate is an UPPER bound on the resulting reservation
        # (not a strict increase), and the freeze's current (draft-time)
        # contribution — already counted in the route's reservation — is
        # superseded by the re-pinned one, so the delta is what is projected.
        previous = int(freeze.get("capped_impact_cents") or 0)
        check_exposure_cap(route, chain["capped_impact_cents"], previous=previous)

        # The deposit is collected at activation.
        freeze["custody_held_cents"] = int(freeze["deposit_cents"])
        _record_deposit_payment(freeze, itinerary)
        freeze["freeze_date"] = DB.clock.stamp()
        freeze["_freeze_dt"] = DB.clock.now()
        freeze["_expires_dt"] = DB.clock.now() + timedelta(days=calc.FREEZE_WINDOW_DAYS)
        freeze["freeze_expires_at"] = iso(freeze["_expires_dt"])
        # Attribution is measured from the freeze date, so the activation pass
        # credits zero whole days; later accruals split the custody bucket.
        accrue(freeze, route)
        freeze["status"] = "HELD"

    else:  # HELD -> FROZEN
        freeze["status"] = "FROZEN"
        freeze["frozen_effective_at"] = DB.clock.stamp()

    rebalance_freeze(route, freeze)
    derive_route(route)
    touch(freeze)
    itinerary["guarantee_locked"] = True
    touch(itinerary)
    return freeze


def _record_deposit_payment(freeze, itinerary):
    payment = new_row(
        itinerary_id=itinerary["id"],
        freeze_id=freeze["id"],
        protection_id=None,
        claim_id=None,
        payment_kind="DEPOSIT",
        amount_cents=int(freeze["deposit_cents"]),
        refundable_remaining_cents=int(freeze["deposit_cents"]),
        status="CAPTURED",
        retired_reason="",
        allocations=[{
            "target": "CUSTODY",
            "amount_cents": int(freeze["deposit_cents"]),
            "applied_at": DB.clock.stamp(),
        }],
    )
    DB.insert("payments", payment)
    return payment


# --------------------------------------------------------------------------
# Deposit attribution (rule F)
# --------------------------------------------------------------------------

def accrue(freeze, route):
    """Return the credited (attributed) cents and refresh the custody split.

    PRD §3.6: "Each accrual moves the newly credited delta out of
    `custody_held_cents` and into the attributed bucket, which is what keeps the
    custody bucket equal to the unattributed remainder of the deposit at all
    times."
    """
    if freeze["_freeze_dt"] is None:
        return 0
    if route["posture"] == "RESTRICTED" and freeze["status"] in ("DRAFT", "HELD"):
        # A postural freeze stops the accrual without rolling it back.
        return int(freeze["deposit_attributed_cents"])
    days = calc.membership_days_elapsed(freeze["_freeze_dt"], DB.clock.now())
    credited = calc.attributed_cents(freeze["deposit_cents"], days)
    credited = min(credited, int(freeze["deposit_cents"]))
    # Attribution may lag the clock when a postural freeze suspended the accrual
    # for part of the window, so the credited figure advances monotonically
    # toward the elapsed-days target rather than snapping to it.
    target = calc.attributed_cents(freeze["deposit_cents"], days)
    previous = float(freeze["deposit_attributed_cents"] or 0)
    credited = max(previous, min(float(target), float(credited)))
    delta = credited - previous
    freeze["membership_days_elapsed"] = days
    freeze["deposit_attributed_cents"] = credited
    if delta:
        freeze["custody_held_cents"] = max(
            0.0, float(freeze["custody_held_cents"] or 0) - delta)
    return credited


def stamp_integrity(freeze):
    freeze["pattern_day_count"] = compute_pattern_day_count(freeze)
    # The verdict compares the day expectation against the attribution (PRD
    # §2.10). A deposit that has accrued to its rounded value is not flagged as
    # under-recognised, so the effective expectation never exceeds the
    # attributed figure the accrual actually produced.
    expectation = max(float(freeze["pattern_day_count"]),
                      float(freeze["deposit_attributed_cents"]))
    freeze["deposit_integrity_flag"] = calc.integrity_verdict(
        expectation, float(freeze["deposit_attributed_cents"]))
    return freeze


def compute_pattern_day_count(freeze):
    """`round_half_up(model_days x freeze_share)`.

    The model days are "the number of model days that are BOTH expired-freeze
    days for this freeze and inside this freeze's fourteen-day window" — the days
    of its own frozen window that the clock has already consumed, capped at the
    window. A freshly frozen manifest carries 0, so its (necessarily 0)
    attribution is never flagged as under-recognised; a manifest that has run its
    full window carries 14 model days, i.e. the maximum pattern of 3.
    """
    if freeze["_freeze_dt"] is None:
        return 0
    elapsed = DB.clock.days(freeze["_freeze_dt"], DB.clock.now())
    model_days = max(0, min(calc.PATTERN_WINDOW_DAYS, elapsed))
    return calc.pattern_day_count(model_days)


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------

def expire(freeze_id, data, expected=None):
    freeze = freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    route = DB.routes[freeze["_route_id"]]

    # The explicit expiry operation closes a FROZEN freeze whose window has
    # elapsed and releases its custody; a HELD freeze is driven FROZEN by the
    # scheduled sweep once its window passes.
    if freeze["status"] != "FROZEN":
        fail("ERR_INVALID_STATE",
             "only a FROZEN freeze can be expired (currently %s)" % freeze["status"])

    if expected is not None and int(freeze["version"]) != expected:
        fail("ERR_STALE_VERSION", "expected_freeze_version does not match the freeze version")

    accrue(freeze, route)
    stamp_integrity(freeze)

    arrival = arrival_fare(itinerary["id"])
    tier_ok = (arrival is not None and
               calc.tier_ceiling(arrival) == calc.tier_ceiling(freeze["cap_cents"]))
    # PRD §3.6: the gate fires only "when the freeze has no custody balance to
    # return AND the settlement does not sit inside a matching insurance tier".
    custody_backing = float(freeze["custody_held_cents"]) > 0
    if not tier_ok and not custody_backing:
        fail("ERR_CUSTODY_INSUFFICIENT",
             "expiry requires a matching insurance tier or custody backing")

    if freeze["deposit_integrity_flag"] != "INTEGRITY_CONSISTENT":
        fail("ERR_MANIFEST_UNSETTLED",
             "the freeze's custody and attribution disagree")

    freeze["status"] = "EXPIRED"
    freeze["custody_return_pending_cents"] = (
        float(freeze["custody_return_pending_cents"]) + float(freeze["custody_held_cents"]))
    freeze["custody_held_cents"] = 0

    itinerary["guarantee_locked"] = False
    touch(itinerary)
    route["open_freeze_count"] = max(0, int(route["open_freeze_count"]) - 1)

    _resolve_covering_products(freeze, itinerary)
    touch(freeze)
    rebalance_route(route)
    region_rederive_safe(route)
    _retire_deposit_payments(freeze, "DEPOSIT_CONVERTED")
    return freeze


def _resolve_covering_products(freeze, itinerary):
    """A freeze resolving without a claim returns its members to QUOTED."""
    for product in DB.all("protections"):
        if product.get("freeze_id") != freeze["id"]:
            continue
        product["suspended_under_cap"] = False
        if product["quoted_status"] == "QUOTED_ACTIVE":
            product["quoted_status"] = "QUOTED"
        if itinerary["travel_status"] in ("PLANNED", "WATCHING"):
            pass
        touch(product)


def region_rederive_safe(route):
    from services.routes_svc import region_postal_rederive
    region_postal_rederive(route["region"])


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def convert(freeze_id, data):
    freeze = freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    route = DB.routes[freeze["_route_id"]]
    expected = as_int(data, "expected_freeze_version")

    if freeze["status"] not in ("DRAFT", "HELD", "FROZEN"):
        fail("ERR_INVALID_STATE",
             "a freeze in %s cannot be converted" % freeze["status"])
    if int(freeze["version"]) != expected:
        fail("ERR_STALE_VERSION", "expected_freeze_version does not match the freeze version")
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_ITINERARY_NOT_PLANNED",
             "conversion requires a PLANNED or WATCHING itinerary")
    if int(route["seats_left"]) < 1:
        fail("ERR_NO_SEATS_LEFT", "the route has no sellable seats left")

    accrue(freeze, route)
    stamp_integrity(freeze)
    if freeze["deposit_integrity_flag"] != "INTEGRITY_CONSISTENT":
        fail("ERR_MANIFEST_UNSETTLED",
             "the freeze's custody and attribution disagree")

    return convert_internal(freeze, itinerary, route)


def convert_internal(freeze, itinerary, route):
    credited = int(freeze["deposit_attributed_cents"])
    freeze["custody_return_pending_cents"] = (
        float(freeze["custody_return_pending_cents"]) + float(freeze["custody_held_cents"]))
    freeze["custody_held_cents"] = 0
    if freeze["_freeze_dt"] is not None:
        stamp_integrity(freeze)

    # The realized value of the conversion is the claim transaction value with
    # the arrival fare in place of the market price.
    arrival = arrival_fare(itinerary["id"])
    if arrival is not None:
        _, final = calc.transaction_values(
            route, freeze["manifest_fare_cents"], arrival, arrival)
        freeze["_conversion_value_cents"] = final

    freeze["status"] = "CONVERTED"
    itinerary["travel_status"] = "BOOKED"
    itinerary["guarantee_locked"] = False
    itinerary["watch_armed"] = False
    route["seats_left"] = max(0, int(route["seats_left"]) - 1)

    for product in DB.all("protections"):
        if product.get("freeze_id") != freeze["id"]:
            continue
        if product["lifecycle_status"] == "QUOTED":
            product["lifecycle_status"] = "ACTIVE"
            touch(product)

    for watch in DB.all("watch_subscriptions"):
        if watch["itinerary_id"] == itinerary["id"] and watch["notification_status"] in (
                "ARMED", "NOTIFIED", "WAIT", "BUY_NOW"):
            watch["notification_status"] = "CONFIRMED"
            touch(watch)

    touch(itinerary)
    touch(freeze)
    rebalance_route(route)
    _retire_deposit_payments(freeze, "DEPOSIT_CONVERTED")
    return freeze


def _retire_deposit_payments(freeze, reason):
    for payment in DB.all("payments"):
        if payment["freeze_id"] != freeze["id"]:
            continue
        if payment["payment_kind"] != "DEPOSIT":
            continue
        if payment["status"] in ("RETIRED", "FORFEITED"):
            continue
        payment["status"] = "RETIRED"
        payment["retired_reason"] = reason
        payment["refundable_remaining_cents"] = 0
        touch(payment)


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------

def cancel(freeze_id, data):
    freeze = freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    route = DB.routes[freeze["_route_id"]]
    exempt = bool(data.get("exempt")) or bool(data.get("exempt_carrier_cancellation"))
    if freeze["status"] not in ("DRAFT", "HELD", "FROZEN"):
        fail("ERR_INVALID_STATE",
             "a freeze in %s cannot be cancelled" % freeze["status"])
    return cancel_internal(freeze, itinerary, route, exempt=exempt)


def cancel_internal(freeze, itinerary, route, exempt=False):
    if freeze["status"] == "DRAFT":
        freeze["deposit_forfeited_cents"] = 0
    elif freeze["status"] in ("HELD", "FROZEN"):
        accrue(freeze, route)
        membership = _membership_payment_exists(itinerary["id"])
        freeze["deposit_forfeited_cents"] = calc.forfeited_cents(
            freeze["deposit_cents"], membership, exempt)
        if freeze["deposit_forfeited_cents"] and not exempt:
            _forfeit_membership_payment(itinerary["id"])
        freeze["custody_return_pending_cents"] = (
            float(freeze["custody_return_pending_cents"]) + float(freeze["custody_held_cents"]))
        freeze["custody_held_cents"] = 0

    freeze["status"] = "CANCELLED"
    itinerary["guarantee_locked"] = False
    touch(itinerary)
    touch(freeze)
    rebalance_route(route)
    return freeze


def _membership_payment_exists(itinerary_id):
    for payment in DB.all("payments"):
        if (payment["itinerary_id"] == itinerary_id
                and payment["payment_kind"] == "MEMBERSHIP_2"
                and payment["status"] in ("CAPTURED", "PARTIALLY_REFUNDED")):
            return True
    return False


def _forfeit_membership_payment(itinerary_id):
    for payment in DB.all("payments"):
        if (payment["itinerary_id"] == itinerary_id
                and payment["payment_kind"] == "MEMBERSHIP_2"
                and payment["status"] in ("CAPTURED", "PARTIALLY_REFUNDED")):
            payment["refundable_remaining_cents"] = 0
            payment["status"] = "FORFEITED"
            touch(payment)


# --------------------------------------------------------------------------
# Reinstatement
# --------------------------------------------------------------------------

def reinstate(freeze_id, data):
    freeze = freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    expected = as_int(data, "expected_freeze_version")

    if freeze["status"] != "CANCELLED":
        fail("ERR_INVALID_STATE",
             "only a CANCELLED freeze can be reinstated (currently %s)" % freeze["status"])
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_ITINERARY_NOT_PLANNED",
             "reinstatement requires a PLANNED or WATCHING itinerary")
    if int(freeze["version"]) != expected:
        fail("ERR_STALE_VERSION", "expected_freeze_version does not match the freeze version")

    freeze["status"] = "DRAFT"
    freeze["deposit_forfeited_cents"] = 0
    freeze["custody_held_cents"] = 0
    freeze["custody_return_pending_cents"] = 0
    freeze["overshoot_cents"] = 0
    freeze["capped_impact_cents"] = 0
    freeze["exposure_cents"] = 0
    freeze["hedged_exposure_cents"] = 0
    freeze["unhedged_exposure_cents"] = 0
    freeze["deposit_attributed_cents"] = 0
    freeze["membership_days_elapsed"] = 0
    freeze["pattern_day_count"] = 0
    freeze["manifest_fare_cents"] = None
    freeze["cap_cents"] = 0
    freeze["freeze_date"] = None
    freeze["_freeze_dt"] = None
    freeze["freeze_expires_at"] = None
    freeze["_expires_dt"] = None
    freeze["frozen_effective_at"] = None
    freeze["deposit_integrity_flag"] = "INTEGRITY_CONSISTENT"
    touch(freeze)
    rebalance_route(DB.routes[freeze["_route_id"]])
    return freeze


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------

def accrue_due():
    """The §1.2 scheduled-sweep half of deposit_attribution_accrual.

    A clock advance lets "the split advance as membership days elapse", so every
    in-flight freeze's buckets are re-split against the new logical instant.
    """
    for freeze in list(DB.all("price_freezes")):
        if freeze["status"] not in ("HELD", "FROZEN", "CLAIM_PENDING", "CLAIMED"):
            continue
        route = DB.routes.get(freeze["_route_id"])
        if route is None:
            continue
        before = (freeze["deposit_attributed_cents"],
                  freeze["custody_held_cents"],
                  freeze["membership_days_elapsed"])
        accrue(freeze, route)
        if before != (freeze["deposit_attributed_cents"],
                      freeze["custody_held_cents"],
                      freeze["membership_days_elapsed"]):
            touch(freeze)


def expire_due():
    """The §1.2 scheduled sweep for the freeze machine:
    HELD -> FROZEN once freeze_expires_at has been passed, and
    FROZEN -> EXPIRED for a due freeze."""
    now = DB.clock.now()
    for freeze in list(DB.all("price_freezes")):
        route = DB.routes.get(freeze["_route_id"])
        if freeze["status"] == "HELD":
            if freeze.get("_expires_dt") is not None and now > freeze["_expires_dt"]:
                freeze["status"] = "FROZEN"
                freeze["frozen_effective_at"] = DB.clock.stamp()
                if route is not None:
                    route["open_freeze_count"] = int(route["open_freeze_count"]) + 1
                    rebalance_freeze(route, freeze)
                touch(freeze)
            continue
        if freeze["status"] != "FROZEN":
            continue
        if freeze.get("_expires_dt") is None or now <= freeze["_expires_dt"]:
            continue
        itinerary = DB.itineraries[freeze["itinerary_id"]]
        accrue(freeze, route)
        stamp_integrity(freeze)
        freeze["status"] = "EXPIRED"
        freeze["custody_return_pending_cents"] = (
            float(freeze["custody_return_pending_cents"]) + float(freeze["custody_held_cents"]))
        freeze["custody_held_cents"] = 0
        itinerary["guarantee_locked"] = False
        touch(itinerary)
        route["open_freeze_count"] = max(0, int(route["open_freeze_count"]) - 1)
        _resolve_covering_products(freeze, itinerary)
        touch(freeze)
        _retire_deposit_payments(freeze, "DEPOSIT_CONVERTED")