"""ProtectionProduct pricing (rule C), lifecycle machine, protected cancellation,
change events, rebooking options and destination options."""

from datetime import timedelta
from decimal import Decimal

from db import iso, DB, dec, new_row, r2, r3, touch
from errors import fail
from middleware import as_bool, as_int, as_str, as_ts
from services import calc
from services.routes_svc import arrival_fare, derive_itinerary, route_base_fare

PROTECTION_TYPES = ("CANCELLATION", "CHANGE")
LIFECYCLE_STATUSES = ("QUOTED", "ACTIVE", "CHANGE_IN_PROGRESS", "CANCELLED_PROTECTED",
                      "REBOOKED", "TERMINATED", "EXPIRED")
QUOTED_STATUSES = ("QUOTED", "QUOTED_FROZEN", "QUOTED_ACTIVE",
                   "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE")


def protection_or_404(protection_id):
    product = DB.protections.get(protection_id)
    if product is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no protection product %s" % protection_id)
    return product


def covering_freeze(itinerary_id, freeze_id=None):
    """The covering freeze of an itinerary: DRAFT/HELD/FROZEN/CLAIM_PENDING."""
    if freeze_id is not None:
        freeze = DB.price_freezes.get(freeze_id)
        if freeze is None:
            fail("ERR_FREEZE_NOT_FOUND", "no price freeze %s" % freeze_id)
        if freeze["status"] in ("DRAFT", "HELD", "FROZEN", "CLAIM_PENDING"):
            return freeze
        return None
    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] == itinerary_id and freeze["status"] in (
                "DRAFT", "HELD", "FROZEN", "CLAIM_PENDING"):
            return freeze
    return None


# --------------------------------------------------------------------------
# Rule C — protection_pricing
# --------------------------------------------------------------------------

def price_product(product, itinerary, route, freeze):
    declared = calc.clamp_declared(product["cancellation_disruption_probability"])
    product["cancellation_disruption_probability"] = float(declared) if isinstance(
        product["cancellation_disruption_probability"], float) else \
        product["cancellation_disruption_probability"]

    if freeze is not None:
        exposure = int(freeze.get("exposure_cents") or 0)
        hedged = int(freeze.get("hedged_exposure_cents") or 0)
        rate = calc.hedge_share_rate(hedged, exposure)
        product["disruption_probability"] = float(rate)
        product["bonus_days_total"] = 0
    else:
        product["disruption_probability"] = float(declared)
        product["bonus_days_total"] = calc.bonus_days_from_band(declared)

    effective = dec(product["disruption_probability"])
    product["minimum_disruption_met"] = bool(
        effective >= dec(route["cancel_minimum_disruption"]))
    product["change_disruption_probability"] = float(
        calc.change_disruption_probability(effective))

    disruption_fare = int(itinerary.get("each_day_disruption_fare_cents") or 0)
    probable_loss, premium = calc.protection_pricing(
        route, disruption_fare, effective, product["product_type"], freeze is not None)

    if product["product_type"] == "CHANGE":
        minimum = r2(dec(route["protection_floor_rate"]) * dec(disruption_fare) *
                     calc.CHANGE_PRODUCT_RATE)
        if premium < minimum:
            premium = minimum
            product["change_minimum_applied"] = True
        else:
            product["change_minimum_applied"] = False

    product["quote_probable_loss_cents"] = probable_loss
    product["premium_cents"] = premium
    product["suspended_under_cap"] = bool(
        freeze is not None and
        calc.hedge_share_rate(int(freeze.get("hedged_exposure_cents") or 0),
                              int(freeze.get("exposure_cents") or 0)) <
        calc.HEDGE_SUSPEND_THRESHOLD)

    depth = calc.depth_ratio(
        int(freeze.get("unhedged_exposure_cents") or 0) if freeze else 0,
        int(freeze.get("capped_impact_cents") or 0) if freeze else 0)
    product["_depth_ratio"] = float(depth)
    product["_continuum_absorbed_cents"] = calc.continuum_absorbed_cents(
        int(freeze.get("overshoot_cents") or 0) if freeze else 0, depth)

    product["bonus_days_remaining"] = int(product["bonus_days_total"]) - int(
        product["redeemed_value_cents"])
    return product


def quote(data, itinerary=None):
    if itinerary is None:
        from services.routes_svc import itinerary_or_404
        itinerary = itinerary_or_404(as_str(data, "itinerary_id"))
    route = DB.routes[itinerary["route_id"]]

    product_type = as_str(data, "product_type")
    if product_type not in PROTECTION_TYPES:
        fail("ERR_INVALID_REQUEST", "product_type must be CANCELLATION or CHANGE")
    declared = data.get("cancellation_disruption_probability")
    if declared is None:
        fail("ERR_INVALID_REQUEST", "cancellation_disruption_probability is required")
    if isinstance(declared, bool) or not isinstance(declared, (int, float)):
        fail("ERR_INVALID_REQUEST", "cancellation_disruption_probability must be a number")

    from services.freeze_svc import check_disclosure
    check_disclosure(route, data)

    freeze_id = data.get("freeze_id")
    freeze = None
    if freeze_id is not None:
        freeze = covering_freeze(itinerary["id"], freeze_id)
    else:
        freeze = covering_freeze(itinerary["id"])

    if route["curve_published"]:
        quoted_status = "QUOTED_FROZEN" if freeze is not None else "QUOTED"
    else:
        quoted_status = ("QUOTED_FROZEN_ON_UNPUBLISHED_CURVE" if freeze is not None
                         else "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE")

    product = new_row(
        itinerary_id=itinerary["id"],
        _itinerary_id=itinerary["id"],
        _route_id=route["id"],
        freeze_id=freeze["id"] if freeze is not None else None,
        product_type=product_type,
        quoted_status=quoted_status,
        lifecycle_status="QUOTED",
        cancellation_disruption_probability=declared,
        disruption_probability=0.0,
        change_disruption_probability=0.0,
        change_minimum_applied=False,
        quote_probable_loss_cents=0,
        minimum_disruption_met=False,
        bonus_days_total=0,
        bonus_days_remaining=0,
        premium_cents=0,
        cancelled_by_member=False,
        redeemed_value_cents=0,
        duration_consumed_days=0,
        terminated_hard=False,
        coverage_expires_at=itinerary["departure_date"],
        _coverage_dt=itinerary["_departure_dt"],
        suspended_under_cap=False,
        _pre_cancel_redeemed=0,
        _pre_cancel_remaining=0,
    )
    DB.insert("protections", product)

    if quoted_status == "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE":
        product["quote_probable_loss_cents"] = 0
        product["premium_cents"] = 0
        product["disruption_probability"] = 0.0
        product["bonus_days_total"] = 0
    else:
        price_product(product, itinerary, route, freeze)
    return product


def requote(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    route = DB.routes[itinerary["route_id"]]

    if "cancellation_disruption_probability" in data and \
            data["cancellation_disruption_probability"] is not None:
        declared = data["cancellation_disruption_probability"]
        if isinstance(declared, bool) or not isinstance(declared, (int, float)):
            fail("ERR_INVALID_REQUEST",
                 "cancellation_disruption_probability must be a number")
        product["cancellation_disruption_probability"] = declared

    if product["quoted_status"] == "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE":
        if not route["curve_published"]:
            fail("ERR_PREMIUM_NOT_PAYABLE", "the route still has no published curve")
        product["quoted_status"] = "QUOTED"

    freeze = covering_freeze(itinerary["id"], product.get("freeze_id"))
    if freeze is None and product.get("freeze_id"):
        freeze = None
    if freeze is not None:
        product["freeze_id"] = freeze["id"]
        if product["quoted_status"] == "QUOTED":
            product["quoted_status"] = "QUOTED_FROZEN"
    price_product(product, itinerary, route, freeze)
    touch(product)
    return product


def activate(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    route = DB.routes[itinerary["route_id"]]
    expected = as_int(data, "expected_protection_version")

    if product["lifecycle_status"] != "QUOTED":
        fail("ERR_INVALID_STATE",
             "a product in %s cannot be activated" % product["lifecycle_status"])
    if product["quoted_status"] not in ("QUOTED", "QUOTED_ACTIVE"):
        fail("ERR_PREMIUM_NOT_PAYABLE",
             "a product quoted on an unpublished curve cannot be activated")
    if route["posture"] not in ("ACTIVE", "SURGE"):
        fail("ERR_ROUTE_RESTRICTED",
             "a %s route admits no protection activation" % route["posture"])
    if int(product["version"]) != expected:
        fail("ERR_STALE_VERSION",
             "expected_protection_version does not match the product version")

    product["lifecycle_status"] = "ACTIVE"
    touch(product)
    return product


def protected_cancel(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    route = DB.routes[itinerary["route_id"]]

    # PRD §3.8 names the already-exercised condition among the exercise gates;
    # the durable record of it is `cancelled_by_member`, so a replay must report
    # that specific condition rather than a generic state refusal.
    if product["cancelled_by_member"] or \
            product["lifecycle_status"] == "CANCELLED_PROTECTED":
        fail("ERR_CANCELLATION_ALREADY_EXERCISED",
             "this product has already exercised its cancellation")
    if product["lifecycle_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE",
             "a product in %s cannot exercise cancellation" % product["lifecycle_status"])
    if product["product_type"] != "CANCELLATION":
        fail("ERR_PRODUCT_TYPE_MISMATCH",
             "only a CANCELLATION product exercises protected cancellation")
    if not product["minimum_disruption_met"]:
        fail("ERR_DISRUPTION_BELOW_MINIMUM",
             "the product's disruption probability is below the route minimum")
    if itinerary["travel_status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "protected cancellation requires a PLANNED itinerary")

    product["_pre_cancel_redeemed"] = int(product["redeemed_value_cents"])
    product["_pre_cancel_remaining"] = int(product["bonus_days_remaining"])

    disruption_fare = int(itinerary.get("each_day_disruption_fare_cents") or 0)
    consumed = calc.cancel_consumption(
        product["bonus_days_total"], product["premium_cents"], disruption_fare)
    product["redeemed_value_cents"] = consumed
    product["bonus_days_remaining"] = int(product["bonus_days_total"]) - consumed
    product["lifecycle_status"] = "CANCELLED_PROTECTED"
    product["cancelled_by_member"] = True
    touch(product)

    itinerary["travel_status"] = "CANCELLED"
    itinerary["watch_armed"] = False
    itinerary["guarantee_locked"] = False
    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] != itinerary["id"]:
            continue
        if freeze["status"] in ("DRAFT", "HELD"):
            strike = DB.clock.stamp()
            freeze["status"] = "CANCELLED"
            freeze["deposit_forfeited_cents"] = 0
            freeze["_pre_cancel_status"] = "DRAFT" if freeze["custody_held_cents"] == 0 else "HELD"
            freeze["updated_at"] = strike
            freeze["version"] = int(freeze["version"]) + 1
    touch(itinerary)
    return product


def reinstate(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    expected = as_int(data, "expected_protection_version")

    if product["lifecycle_status"] != "CANCELLED_PROTECTED":
        fail("ERR_INVALID_STATE",
             "only a CANCELLED_PROTECTED product can be reinstated")
    if itinerary["travel_status"] != "CANCELLED":
        fail("ERR_INVALID_STATE", "reinstatement requires a CANCELLED itinerary")
    if int(product["version"]) != expected:
        fail("ERR_STALE_VERSION",
             "expected_protection_version does not match the product version")

    product["lifecycle_status"] = "ACTIVE"
    product["cancelled_by_member"] = False
    product["redeemed_value_cents"] = int(product["_pre_cancel_redeemed"])
    product["bonus_days_remaining"] = int(product["bonus_days_total"]) - int(
        product["redeemed_value_cents"])
    touch(product)

    itinerary["travel_status"] = "PLANNED"
    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] != itinerary["id"]:
            continue
        if freeze["status"] == "CANCELLED" and freeze.get("_pre_cancel_status"):
            freeze["status"] = freeze["_pre_cancel_status"]
            touch(freeze)
    touch(itinerary)
    return product


def terminate(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    reason = as_str(data, "termination_reason")

    if product["lifecycle_status"] not in ("QUOTED", "ACTIVE", "CHANGE_IN_PROGRESS"):
        fail("ERR_INVALID_STATE",
             "a product in %s cannot be terminated" % product["lifecycle_status"])

    if itinerary["travel_status"] == "CANCELLED":
        product["lifecycle_status"] = "TERMINATED"
        product["terminated_hard"] = True
    elif int(product["bonus_days_remaining"]) > 0:
        product["lifecycle_status"] = "TERMINATED"
        product["terminated_hard"] = True
    else:
        product["lifecycle_status"] = "TERMINATED"
        product["terminated_hard"] = True
    touch(product)
    return product


# --------------------------------------------------------------------------
# Change events
# --------------------------------------------------------------------------

def change_event_or_404(change_event_id):
    event = DB.change_events.get(change_event_id)
    if event is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no change event %s" % change_event_id)
    return event


def file_change_event(protection_id, data):
    product = protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    new_departure = as_ts(data, "new_departure_date")
    gap_direction = data.get("gap_direction", "ORIGIN_DIRECTION")
    if gap_direction not in ("ORIGIN_DIRECTION", "DESTINATION_DIRECTION"):
        fail("ERR_INVALID_REQUEST", "gap_direction is not a declared direction")

    if product["lifecycle_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE",
             "a product in %s admits no change event" % product["lifecycle_status"])
    if product["product_type"] != "CHANGE":
        fail("ERR_PRODUCT_TYPE_MISMATCH", "only a CHANGE product admits a change event")
    for event in DB.all("change_events"):
        if event["protection_id"] == product["id"] and event["status"] in (
                "OPEN", "OPTION_SELECTED", "HELD"):
            fail("ERR_CHANGE_ALREADY_OPEN",
                 "another change event for this protection is still open")

    old_departure = itinerary["_departure_dt"]
    if new_departure == old_departure:
        fail("ERR_PRODUCT_TYPE_MISMATCH",
             "the replacement departure date must differ from the current one")

    day_shift = abs(int((new_departure - old_departure).days))
    event = new_row(
        protection_id=product["id"],
        itinerary_id=itinerary["id"],
        _itinerary_id=itinerary["id"],
        old_departure_date=itinerary["departure_date"],
        new_departure_date=iso(new_departure),
        _new_departure_dt=new_departure,
        day_shift=day_shift,
        disruption_days=calc.duration_metric(day_shift),
        unrecovered_travel_fare_cents=0,
        remaining_days=int(product["bonus_days_remaining"]),
        status="OPEN",
        selected_option_id=None,
        option_hold_expires_at=None,
        _hold_dt=None,
        _lapse_count=0,
        gap_direction=gap_direction,
    )
    DB.insert("change_events", event)

    product["lifecycle_status"] = "CHANGE_IN_PROGRESS"
    touch(product)
    return event


def create_rebooking_option(data):
    event = change_event_or_404(as_str(data, "change_event_id"))
    departure = as_ts(data, "departure_date")
    fare = as_int(data, "option_fare_cents")
    if fare < 1:
        fail("ERR_INVALID_REQUEST", "option_fare_cents must be at least 1 cent")

    product = DB.protections[event["protection_id"]]
    itinerary = DB.itineraries[event["_itinerary_id"]]
    if event["status"] in ("SETTLED", "CANCELLED"):
        fail("ERR_INVALID_STATE", "the change event is no longer open")
    old = itinerary["_departure_dt"]
    if departure == old:
        fail("ERR_PRODUCT_TYPE_MISMATCH",
             "an option's departure date must be a legal replacement")

    siblings = [o for o in DB.all("rebooking_options")
                if o["change_event_id"] == event["id"]]
    for sibling in siblings:
        if sibling["_departure_dt"] == departure and \
                int(sibling["option_fare_cents"]) == fare and \
                sibling["_created_at_dt"] == DB.clock.now():
            fail("ERR_DUPLICATE_SEQUENCE_INDEX",
                 "an option with this sequence key already exists")

    option = new_row(
        change_event_id=event["id"],
        _change_event_id=event["id"],
        departure_date=iso(departure),
        _departure_dt=departure,
        option_fare_cents=fare,
        sequence_index=0,
        hold_expires_at=None,
        _hold_dt=None,
        status="OFFERED",
        _created_at_dt=DB.clock.now(),
    )
    DB.insert("rebooking_options", option)
    resequence(event)
    return option


def resequence(event):
    """protect_change_schedule Step 1 — the total sort key."""
    options = [o for o in DB.all("rebooking_options")
               if o["change_event_id"] == event["id"]]
    options.sort(key=lambda o: (o["_departure_dt"], o["_created_at_dt"],
                                int(o["option_fare_cents"]), o["id"]))
    seen = set()
    for position, option in enumerate(options, start=1):
        if position in seen:
            fail("ERR_DUPLICATE_SEQUENCE_INDEX", "sequence_index collision")
        option["sequence_index"] = position
        seen.add(position)
    return options


def display_schedule(event):
    product = DB.protections[event["protection_id"]]
    itinerary = DB.itineraries[event["_itinerary_id"]]
    route = DB.routes[itinerary["route_id"]]
    now = DB.clock.now()
    rows = []
    for option in [o for o in DB.all("rebooking_options")
                   if o["change_event_id"] == event["id"]]:
        if option["status"] in ("EXPIRED", "SUPERSEDED"):
            continue
        days_until = max(0, int((option["_departure_dt"] - now).days))
        rate = calc.displayed_discount_rate(
            product["disruption_probability"], route["disruption_severity_index"],
            days_until)
        rows.append({
            "option": option,
            "display_price_cents": calc.display_price_cents(
                option["option_fare_cents"], rate),
        })
    rows.sort(key=lambda r: (r["display_price_cents"], r["option"]["_created_at_dt"],
                             r["option"]["id"]))
    return rows


def select_option(change_event_id, data):
    event = change_event_or_404(change_event_id)
    option_id = as_str(data, "option_id")
    option = DB.rebooking_options.get(option_id)
    if option is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no rebooking option %s" % option_id)
    if option["change_event_id"] != event["id"]:
        fail("ERR_OPTION_NOT_IN_EVENT",
             "the named option does not belong to this change event")
    if event["status"] not in ("OPEN", "OPTION_SELECTED"):
        fail("ERR_INVALID_STATE",
             "a change event in %s admits no selection" % event["status"])
    if option["status"] != "OFFERED":
        fail("ERR_OPTION_NOT_OFFERED",
             "the named option is not in OFFERED status")

    for sibling in DB.all("rebooking_options"):
        if sibling["change_event_id"] == event["id"]:
            if sibling["id"] == option["id"]:
                sibling["status"] = "SELECTED"
            else:
                sibling["status"] = "SUPERSEDED"
            touch(sibling)

    event["status"] = "OPTION_SELECTED"
    event["selected_option_id"] = option["id"]
    touch(event)
    return event


def accept_option(option_id, data):
    option = DB.rebooking_options.get(option_id)
    if option is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no rebooking option %s" % option_id)
    event = change_event_or_404(option["change_event_id"])
    now = DB.clock.now()

    if option["status"] != "SELECTED" or event["status"] != "OPTION_SELECTED":
        fail("ERR_INVALID_STATE", "the option is not awaiting acceptance")
    if option["_departure_dt"] <= now:
        fail("ERR_OPTION_HOLD_LAPSED", "the option's departure date is not in the future")

    instant = now + timedelta(hours=calc.BUY_NOW_WINDOW_HOURS)
    option["status"] = "HELD"
    option["_hold_dt"] = instant
    option["hold_expires_at"] = iso(instant)
    event["status"] = "HELD"
    event["_hold_dt"] = instant
    event["option_hold_expires_at"] = iso(instant)
    touch(option)
    touch(event)
    return option


def revert_option(option_id, data):
    option = DB.rebooking_options.get(option_id)
    if option is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no rebooking option %s" % option_id)
    event = change_event_or_404(option["change_event_id"])
    if option["status"] != "HELD":
        fail("ERR_INVALID_STATE", "only a HELD option can be reverted")

    option["status"] = "EXPIRED"
    event["status"] = "OPTION_SELECTED"
    event["_hold_dt"] = None
    event["option_hold_expires_at"] = None
    _stamp_unrecovered(event)
    touch(option)
    touch(event)
    return option


def _stamp_unrecovered(event):
    """`unrecovered_travel_fare_cents` is written only when a change event is
    abandoned after its hold lapses: "the itinerary's old departure fare
    re-rated at the arrival observation" — the itinerary's departure fare scaled
    by the arrival fare's rating, i.e. by the route's disruption severity."""
    itinerary = DB.itineraries[event["_itinerary_id"]]
    route = DB.routes.get(itinerary["route_id"])
    old_fare = (itinerary.get("_old_departure_fare_cents")
                or itinerary.get("listed_fare_cents")
                or itinerary.get("demand_curve_price_cents")
                or (route["base_fare_cents"] if route is not None else 0))
    severity = dec(route["disruption_severity_index"]) if route is not None else dec("0")
    event["unrecovered_travel_fare_cents"] = int(
        r2(dec(old_fare or 0) * severity))
    return event


def settle_change(change_event_id, data):
    event = change_event_or_404(change_event_id)
    product = DB.protections[event["protection_id"]]
    itinerary = DB.itineraries[event["_itinerary_id"]]
    now = DB.clock.now()

    if "expected_change_event_version" in data and \
            data["expected_change_event_version"] is not None:
        expected = as_int(data, "expected_change_event_version")
        if expected != int(event["version"]):
            fail("ERR_STALE_VERSION",
                 "expected_change_event_version does not match the change event version")

    if event["status"] != "HELD":
        fail("ERR_INVALID_STATE", "the change event is not holding an option")

    option = DB.rebooking_options.get(event["selected_option_id"])
    if option is None or option["status"] != "HELD":
        fail("ERR_INVALID_STATE", "no held option is selected")
    if option["_hold_dt"] is not None and now > option["_hold_dt"]:
        fail("ERR_NOTIFICATION_SUPPRESSED", "the option's hold has lapsed")
    if "option_fare_cents" not in option or option.get("option_fare_cents") is None:
        fail("ERR_PRICE_FIELD_MISSING", "the billed option price is absent")

    disruption_days = calc.duration_metric(event["day_shift"])
    remaining = int(product["bonus_days_remaining"]) - disruption_days
    if remaining < 0:
        fail("ERR_INSUFFICIENT_BONUS_DAYS",
             "the settlement would consume more bonus days than remain")

    event["disruption_days"] = disruption_days
    event["remaining_days"] = remaining
    event["status"] = "SETTLED"
    product["redeemed_value_cents"] = int(product["redeemed_value_cents"]) + disruption_days
    product["duration_consumed_days"] = int(product["duration_consumed_days"]) + disruption_days
    product["bonus_days_remaining"] = int(product["bonus_days_total"]) - int(
        product["redeemed_value_cents"])
    product["lifecycle_status"] = "REBOOKED"

    option["status"] = "ACCEPTED"
    itinerary["departure_date"] = option["departure_date"]
    itinerary["_departure_dt"] = option["_departure_dt"]

    for dest in DB.all("destination_options"):
        if dest["itinerary_id"] == itinerary["id"] and dest["status"] == "BOUND":
            dest["status"] = "TAKEN"
            touch(dest)

    touch(option)
    touch(event)
    touch(product)
    touch(itinerary)
    return event


def cancel_change_event(change_event_id, data):
    event = change_event_or_404(change_event_id)
    product = DB.protections[event["protection_id"]]
    if event["status"] not in ("OPEN", "OPTION_SELECTED", "HELD"):
        fail("ERR_INVALID_STATE",
             "a change event in %s cannot be cancelled" % event["status"])

    was_selected = event["status"] == "OPTION_SELECTED"
    event["status"] = "CANCELLED"
    event["_hold_dt"] = None
    event["option_hold_expires_at"] = None
    if was_selected:
        for sibling in DB.all("rebooking_options"):
            if sibling["change_event_id"] == event["id"]:
                sibling["status"] = "SUPERSEDED"
                touch(sibling)
    else:
        for sibling in DB.all("rebooking_options"):
            if sibling["change_event_id"] == event["id"] and sibling["status"] == "HELD":
                sibling["status"] = "EXPIRED"
                touch(sibling)

    if product["lifecycle_status"] == "CHANGE_IN_PROGRESS":
        product["lifecycle_status"] = "ACTIVE"
    touch(product)
    touch(event)
    return event


def lapse_change_holds():
    now = DB.clock.now()
    for event in DB.all("change_events"):
        if event["status"] != "HELD":
            continue
        if event["_hold_dt"] is None or now <= event["_hold_dt"]:
            continue
        event["_lapse_count"] = int(event.get("_lapse_count", 0)) + 1
        if event["_lapse_count"] >= 2:
            # The terminal override: a second lapse settles with no rebooking.
            product = DB.protections[event["protection_id"]]
            event["status"] = "SETTLED"
            event["disruption_days"] = 0
            event["remaining_days"] = int(product["bonus_days_remaining"])
            event["option_hold_expires_at"] = None
            event["_hold_dt"] = None
            touch(event)
            continue
        event["status"] = "OPTION_SELECTED"
        event["option_hold_expires_at"] = None
        event["_hold_dt"] = None
        _stamp_unrecovered(event)
        option = DB.rebooking_options.get(event["selected_option_id"])
        if option is not None and option["status"] == "HELD":
            option["status"] = "EXPIRED"
            touch(option)
        for dest in DB.all("destination_options"):
            if dest["itinerary_id"] == event["_itinerary_id"] and dest["status"] == "BOUND":
                dest["status"] = "AVAILABLE"
                touch(dest)
        touch(event)

    for event in DB.all("change_events"):
        if event["status"] == "OPEN":
            opened = event.get("_created_at_dt")
            if opened is not None and (now - opened).days > 45:
                product = DB.protections[event["protection_id"]]
                event["status"] = "SETTLED"
                event["disruption_days"] = 0
                event["remaining_days"] = int(product["bonus_days_remaining"])
                touch(event)


# --------------------------------------------------------------------------
# Destination options
# --------------------------------------------------------------------------

def destination_option_or_404(option_id):
    option = DB.destination_options.get(option_id)
    if option is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no destination option %s" % option_id)
    return option


def create_destination_option(data):
    from services.routes_svc import itinerary_or_404
    itinerary = itinerary_or_404(as_str(data, "itinerary_id"))
    departure = as_ts(data, "departure_date")
    fare = as_int(data, "option_fare_cents")
    direction = data.get("direction", "ORIGIN_DIRECTION")
    if direction not in ("ORIGIN_DIRECTION", "DESTINATION_DIRECTION"):
        fail("ERR_INVALID_REQUEST", "direction is not a declared direction")

    option = new_row(
        itinerary_id=itinerary["id"],
        _itinerary_id=itinerary["id"],
        departure_date=iso(departure),
        _departure_dt=departure,
        option_fare_cents=fare,
        direction=direction,
        eligible=departure > DB.clock.now(),
        status="AVAILABLE",
    )
    DB.insert("destination_options", option)
    return option


def bind_destination_option(option_id, data):
    option = destination_option_or_404(option_id)
    itinerary = DB.itineraries[option["_itinerary_id"]]
    now = DB.clock.now()

    if option["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE",
             "a destination option in %s cannot be bound" % option["status"])
    if option["_departure_dt"] <= now:
        option["eligible"] = False
        fail("ERR_INVALID_STATE", "the option's departure date is not in the future")
    option["eligible"] = True
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_ITINERARY_NOT_PLANNED",
             "the itinerary must be PLANNED or WATCHING to bind an option")

    pending = None
    for event in DB.all("change_events"):
        if event["_itinerary_id"] == itinerary["id"] and event["status"] == "OPTION_SELECTED":
            pending = event
            break
    if pending is None:
        fail("ERR_INVALID_STATE",
             "no change event on this itinerary is awaiting acceptance")

    listed = int(itinerary.get("listed_fare_cents") or 0)
    if listed > 0 and int(option["option_fare_cents"]) > listed:
        ratio = dec(option["option_fare_cents"]) / dec(listed)
        if ratio > dec("1.5"):
            fail("ERR_DESK_ODD_RATIO",
                 "the option's fare exceeds the itinerary's listed fare by more than the "
                 "desk's odd-ratio tolerance")

    option["status"] = "BOUND"
    touch(option)
    return option


def release_destination_option(option_id, data):
    option = destination_option_or_404(option_id)
    if option["status"] != "BOUND":
        fail("ERR_INVALID_STATE",
             "a destination option in %s cannot be released" % option["status"])
    option["status"] = "AVAILABLE"
    touch(option)
    return option