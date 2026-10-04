"""Core business logic: entities, pricing, state transitions, dispatch, cascades.

Implements PRD sections 2.6-2.10 and 3.1-3.10. All timestamps come from the
logical clock in db.py (never wall-clock).
"""
import math
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from db import db, now
from errors import raise_error, invalid_request, invalid_state, not_found


# ---------------------------------------------------------------------------
# Generic entity helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def touch(r):
    """Refresh updated_at and increment version on a mutated resource."""
    r["updated_at"] = now()
    r["version"] += 1


def make_record():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


# ---------------------------------------------------------------------------
# Lookup helpers (left-to-right path validation, PRD 2.9)
# ---------------------------------------------------------------------------

def get_location(location_id):
    loc = db.locations.get(location_id)
    if loc is None:
        not_found("Location not found")
    return loc


def get_stall_nested(location_id, stall_id):
    loc = get_location(location_id)
    st = db.stalls.get(stall_id)
    if st is None or st["location_id"] != loc["id"]:
        not_found("Stall not found")
    return loc, st


def get_fault_nested(location_id, stall_id, fault_id):
    loc, st = get_stall_nested(location_id, stall_id)
    f = db.equipment_faults.get(fault_id)
    if f is None or f["stall_id"] != st["id"]:
        not_found("EquipmentFault not found")
    return loc, st, f


def get_order_nested(location_id, order_id):
    loc = get_location(location_id)
    o = db.orders.get(order_id)
    if o is None or o["location_id"] != loc["id"]:
        not_found("Order not found")
    return loc, o


def get_run_nested(location_id, run_id):
    loc = get_location(location_id)
    r = db.delivery_runs.get(run_id)
    if r is None or r["location_id"] != loc["id"]:
        not_found("DeliveryRun not found")
    return loc, r


def get_offer_nested(location_id, offer_id):
    loc = get_location(location_id)
    of = db.offers.get(offer_id)
    if of is None or of["location_id"] != loc["id"]:
        not_found("Offer not found")
    return loc, of


def get_carhop_nested(location_id, carhop_id):
    loc = get_location(location_id)
    c = db.carhops.get(carhop_id)
    if c is None or c["location_id"] != loc["id"]:
        not_found("Carhop not found")
    return loc, c


def get_tip_nested(location_id, tip_id):
    loc = get_location(location_id)
    t = db.tip_records.get(tip_id)
    if t is None:
        not_found("TipRecord not found")
    o = db.orders.get(t["order_id"])
    if o is None or o["location_id"] != loc["id"]:
        not_found("TipRecord not found")
    return loc, t


# ---------------------------------------------------------------------------
# Location posture (PRD 2.7)
# ---------------------------------------------------------------------------

def recompute_location_posture(loc, touch_location=True):
    """Recompute stalls_available and lane_posture for a location."""
    occupied_or_oos = sum(
        1 for s in db.stalls.values()
        if s["location_id"] == loc["id"]
        and s["kind"] == "STALL"
        and s["status"] in ("OCCUPIED", "OUT_OF_SERVICE")
    )
    loc["stalls_available"] = loc["stall_capacity"] - occupied_or_oos
    if loc["stalls_available"] == 0 or loc["weather_mode"] == "STORM":
        loc["lane_posture"] = "CURBSIDE_ONLY"
    elif loc["stalls_available"] <= math.ceil(loc["stall_capacity"] * 0.20):
        loc["lane_posture"] = "CONGESTED"
    else:
        loc["lane_posture"] = "OPEN"
    if touch_location:
        touch(loc)


# ---------------------------------------------------------------------------
# Order pricing (PRD 3.4)
# ---------------------------------------------------------------------------

def _line_unit_price(line, item):
    price = item["base_price_cents"]
    if item["size_scheme"] == "DRINK_SIZES" and line.get("size_option_code"):
        opt = _find_option(line["size_option_code"])
        if opt is not None:
            price += opt["size_upcharge_cents"]
    for code in line.get("addin_option_codes", []):
        opt = _find_option(code)
        if opt is not None:
            price += opt["price_cents"]
    return price


def _find_option(code):
    for o in db.customization_options.values():
        if o["code"] == code:
            return o
    return None


def order_lines(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def apply_combo_pricing(lines):
    """BOGO-half on DRINK/SLUSH units (PRD 3.4). Mutates line extended prices."""
    units = []
    for line in lines:
        item = db.menu_items.get(line["menu_item_id"])
        if item is not None and item["category"] in ("DRINK", "SLUSH"):
            for i in range(line["quantity"]):
                units.append((line, i))
    units.sort(key=lambda t: (t[0]["unit_price_cents"], t[0]["created_at"], t[0]["id"]))
    discounts = {line["id"]: 0 for line in lines}
    for idx in range(0, len(units) - 1, 2):
        second = units[idx + 1][0]
        half = int(
            (Decimal(second["unit_price_cents"]) / 2).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        discounts[second["id"]] += half
    for line in lines:
        line["extended_price_cents"] = line["unit_price_cents"] * line["quantity"] - discounts[line["id"]]


def recompute_draft_pricing(order):
    """Provisional pricing for DRAFT orders (no offers, tax = 0)."""
    lines = order_lines(order["id"])
    if lines:
        apply_combo_pricing(lines)
        for line in lines:
            touch(line)
    order["subtotal_cents"] = sum(l["extended_price_cents"] for l in lines)
    order["offer_discount_cents"] = 0
    order["tax_cents"] = 0
    order["total_cents"] = order["subtotal_cents"]
    touch(order)


# ---------------------------------------------------------------------------
# Offer windows (PRD 2.6, 3.4)
# ---------------------------------------------------------------------------

def local_time_at(loc, dt):
    """Convert a UTC instant into the location's timezone; returns (hour, minute)."""
    tz = ZoneInfo(loc["timezone"])
    local = dt.astimezone(tz)
    return local.hour * 60 + local.minute


def _parse_hhmm(s):
    parts = s.split(":")
    if len(parts) != 2:
        invalid_request("Window times must be HH:MM")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        invalid_request("Window times must be HH:MM")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        invalid_request("Window times must be HH:MM within 00:00-23:59")
    return h * 60 + m


def window_contains(offer_rec, local_minutes):
    start = _parse_hhmm(offer_rec["window_start_local"])
    end = _parse_hhmm(offer_rec["window_end_local"])
    if end == start:
        return True
    if end > start:
        return start <= local_minutes < end
    return local_minutes >= start or local_minutes < end


def offer_applicable_to_order(offer_rec, order, customer):
    if offer_rec["app_only"]:
        if order["channel"] != "APP_CHECKIN":
            return False
        if customer is None or not customer["app_user"]:
            return False
    return True


# ---------------------------------------------------------------------------
# Placement (PRD 3.4)
# ---------------------------------------------------------------------------

def place_order(order, loc, offer_code, fallback_confirmed):
    if order["status"] != "DRAFT":
        invalid_state("Order is not in DRAFT")
    lines = order_lines(order["id"])
    if len(lines) == 0:
        raise_error("ERR_EMPTY_ORDER", "Cannot place an order with no lines")
    for line in lines:
        item = db.menu_items.get(line["menu_item_id"])
        if item is not None and item["status"] == "RETIRED":
            raise_error("ERR_MENU_ITEM_RETIRED", "Order contains a RETIRED menu item")

    stall = None
    if order["channel"] in ("STALL_INTERCOM", "APP_CHECKIN", "PATIO"):
        stall = db.stalls.get(order["stall_id"])
        if (
            stall is None
            or stall["status"] != "OCCUPIED"
            or stall["current_order_id"] != order["id"]
        ):
            raise_error(
                "ERR_STALL_NOT_OCCUPIED_BY_ORDER",
                "Stall is not occupied by this order",
            )

    if order["channel"] == "STALL_INTERCOM":
        if not stall["intercom_functional"]:
            has_intercom_fault = any(
                f["stall_id"] == stall["id"]
                and f["kind"] == "INTERCOM_DEAD"
                and f["status"] == "OPEN"
                for f in db.equipment_faults.values()
            )
            if not (has_intercom_fault and fallback_confirmed):
                raise_error(
                    "ERR_INTERCOM_UNAVAILABLE",
                    "Stall intercom is not functional and no fallback was confirmed",
                )
        if loc["lane_posture"] == "CURBSIDE_ONLY":
            raise_error("ERR_LANE_CLOSED", "Location is curbside-only")

    # Service-target snapshot: exact weather mode, else NORMAL fallback.
    profile = None
    for p in db.service_target_profiles.values():
        if (
            p["location_id"] == loc["id"]
            and p["status"] == "ACTIVE"
            and p["channel"] == order["channel"]
            and p["weather_mode"] == loc["weather_mode"]
        ):
            profile = p
            break
    if profile is None:
        for p in db.service_target_profiles.values():
            if (
                p["location_id"] == loc["id"]
                and p["status"] == "ACTIVE"
                and p["channel"] == order["channel"]
                and p["weather_mode"] == "NORMAL"
            ):
                profile = p
                break
    if profile is None:
        raise_error(
            "ERR_NO_SERVICE_TARGET",
            "No ACTIVE service target profile for this channel",
        )

    customer = None
    if order["customer_id"] is not None:
        customer = db.customers.get(order["customer_id"])
    local_minutes = local_time_at(loc, order["checked_in_at"])

    active_offers = [
        o
        for o in db.offers.values()
        if o["location_id"] == loc["id"] and o["status"] == "ACTIVE"
    ]

    # 1. Happy-hour repricing.
    hh_active = any(
        o["kind"] == "HAPPY_HOUR"
        and o["discount_type"] == "HALF_PRICE_DRINKS"
        and window_contains(o, local_minutes)
        for o in active_offers
    )
    hh_savings = 0
    if hh_active:
        # Provisional (pre-happy-hour) combo-adjusted subtotal, recomputed
        # from the current line state so it is exact even if the order row's
        # cached subtotal is stale.
        pre_hh_state = [
            (l["unit_price_cents"], l["extended_price_cents"], l["happy_hour_priced"])
            for l in lines
        ]
        apply_combo_pricing(lines)
        provisional = sum(l["extended_price_cents"] for l in lines)
        for line, (up, ep, hhp) in zip(lines, pre_hh_state):
            line["unit_price_cents"] = up
            line["extended_price_cents"] = ep
            line["happy_hour_priced"] = hhp

        for line in lines:
            item = db.menu_items.get(line["menu_item_id"])
            if (
                item is not None
                and item["half_price_eligible"]
                and item["category"] in ("DRINK", "SLUSH")
            ):
                new_unit = int(
                    (Decimal(line["unit_price_cents"]) / 2).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
                line["unit_price_cents"] = new_unit
                line["happy_hour_priced"] = True
        # Recompute extended prices (with combination pricing) on repriced units.
        apply_combo_pricing(lines)
        subtotal_after_hh = sum(l["extended_price_cents"] for l in lines)
        hh_savings = max(0, provisional - subtotal_after_hh)
    else:
        subtotal_after_hh = sum(l["extended_price_cents"] for l in lines)

    # 2. Offer selection (exactly one non-happy-hour offer).
    candidates = [
        o
        for o in active_offers
        if not (o["kind"] == "HAPPY_HOUR" and o["discount_type"] == "HALF_PRICE_DRINKS")
    ]
    if offer_code is not None:
        selected = None
        for o in db.offers.values():
            if o["location_id"] == loc["id"] and o["code"] == offer_code:
                selected = o
                break
        if selected is None:
            not_found("Offer not found")
        if (
            selected["status"] != "ACTIVE"
            or not window_contains(selected, local_minutes)
            or not offer_applicable_to_order(selected, order, customer)
        ):
            raise_error(
                "ERR_OFFER_NOT_APPLICABLE",
                "The named offer is not applicable to this order",
            )
        selected_discount = _offer_discount(selected, subtotal_after_hh)
    else:
        best = None
        best_discount = -1
        for o in candidates:
            if not window_contains(o, local_minutes):
                continue
            if not offer_applicable_to_order(o, order, customer):
                continue
            d = _offer_discount(o, subtotal_after_hh)
            if d > best_discount:
                best = o
                best_discount = d
        selected_discount = best_discount if best is not None else 0

    offer_discount = hh_savings + selected_discount

    order["subtotal_cents"] = subtotal_after_hh
    order["offer_discount_cents"] = offer_discount
    # PRD pins no tax rate anywhere; the frozen taxable base is subtotal minus
    # offer discount and the only derivable tax amount is zero.
    order["tax_cents"] = 0
    order["total_cents"] = (
        order["subtotal_cents"] - order["offer_discount_cents"] + order["tax_cents"]
    )
    order["service_target_seconds"] = profile["target_seconds"]
    order["placed_at"] = now()
    order["status"] = "PLACED"
    for line in lines:
        touch(line)
    touch(order)


def _offer_discount(offer_rec, subtotal):
    if offer_rec["discount_type"] == "PERCENT_OFF_ORDER":
        return int(
            (Decimal(subtotal) * Decimal(offer_rec["discount_value"]) / 100).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    if offer_rec["discount_type"] == "FIXED_OFF_CENTS":
        return min(offer_rec["discount_value"], subtotal)
    return 0


# ---------------------------------------------------------------------------
# Cancellation / stall release (PRD 3.8)
# ---------------------------------------------------------------------------

def release_stall_if_current(order):
    """If this order occupies its stall, release the stall and recompute posture."""
    if order["stall_id"] is None:
        return
    stall = db.stalls.get(order["stall_id"])
    if stall is None:
        return
    if stall["current_order_id"] == order["id"]:
        stall["current_order_id"] = None
        if stall["status"] == "OCCUPIED":
            stall["status"] = "IDLE"
        touch(stall)
        loc = db.locations.get(stall["location_id"])
        if loc is not None:
            recompute_location_posture(loc, touch_location=False)


def cancel_order(order, void_payment=True):
    """Shared cancellation cascade (PRD 3.8)."""
    if void_payment and order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    order["status"] = "CANCELLED"
    release_stall_if_current(order)
    touch(order)


# ---------------------------------------------------------------------------
# Delivery run completion (PRD 3.6)
# ---------------------------------------------------------------------------

def maybe_complete_run(run):
    orders = [o for o in db.orders.values() if o.get("delivery_run_id") == run["id"]]
    if orders and all(o["status"] in ("DELIVERED", "CANCELLED") for o in orders):
        run["status"] = "COMPLETED"
        touch(run)
        carhop = db.carhops.get(run["carhop_id"])
        if carhop is not None:
            carhop["active_run_load"] -= run["order_count"]
            touch(carhop)
