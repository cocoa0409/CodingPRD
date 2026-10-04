"""Calculation rules from the scaffold §1.3 / PRD §3.

All money is integer cents with round-half-up at each step; score-type values
are exactly 2 decimal places, round-half-up.
"""
import math
from datetime import timedelta
from decimal import Decimal

from errors import err_no_route
from decimal_utils import round_half_up_2dp, round_half_up_int


# --- Item listing ------------------------------------------------------------

def item_cube_score(dim_l, dim_w, dim_h):
    """0.45 * max(L,W,H) + 0.30 * cbrt(L*W*H) + 0.25 * (L+W+H), 2dp half-up."""
    L = Decimal(str(dim_l))
    W = Decimal(str(dim_w))
    H = Decimal(str(dim_h))
    longest = max(L, W, H)
    cube_root = Decimal(str((float(L) * float(W) * float(H)) ** (1.0 / 3.0)))
    total = (
        Decimal("0.45") * longest
        + Decimal("0.30") * cube_root
        + Decimal("0.25") * (L + W + H)
    )
    return round_half_up_2dp(total)


def freight_class_assignment(cube_score):
    """Inclusive-on-lower-class threshold ladder on the 2dp cube_score."""
    s = Decimal(str(cube_score))
    if s <= Decimal("40.00"):
        return "PARCEL_ELIGIBLE"
    if s <= Decimal("70.00"):
        return "LTL_250"
    if s <= Decimal("100.00"):
        return "LTL_150"
    if s <= Decimal("150.00"):
        return "LTL_125"
    return "LTL_92_5"


def declared_girth_and_parcel_gate(dim_l, dim_w, dim_h):
    """Ceil EACH dimension first, then combine (pinned order): the ceiled
    length plus twice the sum of the ceiled width and the ceiled height."""
    cl = math.ceil(float(dim_l))
    cw = math.ceil(float(dim_w))
    ch = math.ceil(float(dim_h))
    girth = cl + 2 * (cw + ch)
    return girth, (girth <= 165)


# --- Pricing & fee split -----------------------------------------------------

def shipping_price(lane, weight_lb):
    weight = math.ceil(float(weight_lb))
    return int(lane["base_rate_cents"]) + int(lane["per_lb_rate_cents"]) * weight


def order_fee_split(declared_value_cents, shipping_amount_cents, freight_class):
    order_total = int(declared_value_cents) + int(shipping_amount_cents)
    if freight_class == "PARCEL_ELIGIBLE":
        surcharge = 0
    else:
        surcharge = round_half_up_int(Decimal(order_total) * Decimal("0.05"))
    handling = round_half_up_int(Decimal(order_total - surcharge) * Decimal("0.08"))
    return order_total, surcharge, handling


def promised_date(order_creation_date, transit_days, fulfillment_mode, linehaul_misses):
    dwell = 1 if fulfillment_mode == "OWNED_FINAL_MILE" else 0
    return (
        order_creation_date
        + timedelta(days=2 + int(transit_days) + dwell + 2 * int(linehaul_misses))
    ).isoformat()


# --- Routing -----------------------------------------------------------------

def select_hub(hubs, lanes, zone, require_white_glove):
    """Candidates: ACTIVE hubs serving the zone (and white-glove capable when
    required). Selector: argmin by OWNED_FINAL_MILE lane transit_days ASC, then
    Hub.created_at ASC. The OWNED_FINAL_MILE lane for the zone ranks the
    candidates; a hub is a candidate on ACTIVE + serves_zones (+
    white-glove-capable) alone."""
    candidates = [
        hub
        for hub in hubs
        if hub["status"] == "ACTIVE"
        and zone in hub["serves_zones"]
        and (not require_white_glove or hub["white_glove_capable"])
    ]
    if not candidates:
        return None
    lane = find_active_lane(lanes, "OWNED_FINAL_MILE", zone)
    transit = int(lane["transit_days"]) if lane is not None else math.inf
    candidates.sort(key=lambda hub: (transit, hub["created_at"]))
    return candidates[0]


def find_active_lane(lanes, leg_mode, zone):
    """ACTIVE lane for (leg_mode, dest_zone); ties resolved by created_at ASC."""
    matches = [
        lane
        for lane in lanes
        if lane["leg_mode"] == leg_mode
        and lane["dest_zone"] == zone
        and lane["status"] == "ACTIVE"
    ]
    if not matches:
        return None
    matches.sort(key=lambda lane: lane["created_at"])
    return matches[0]


def routing_decision(item, supplier, customer, service_level, hubs, lanes):
    """Constraint-propagation routing; branches evaluated strictly in order."""
    zone = customer["destination_zone"]
    # Branch 1 — PARCEL
    if (
        item["freight_class"] == "PARCEL_ELIGIBLE"
        and item["parcel_ok"]
        and find_active_lane(lanes, "PARCEL", zone) is not None
    ):
        return {
            "fulfillment_mode": "PARCEL",
            "leg_mode": "PARCEL",
            "hub": None,
        }
    # Branch 2 — ROOM_OF_CHOICE service
    if service_level == "ROOM_OF_CHOICE":
        hub = select_hub(hubs, lanes, zone, require_white_glove=True)
        if hub is None:
            raise err_no_route()
        return {
            "fulfillment_mode": "OWNED_FINAL_MILE",
            "leg_mode": "OWNED_FINAL_MILE",
            "hub": hub,
        }
    # Branch 3 — DROP_SHIP
    if supplier["drop_ship_enabled"] and supplier["status"] == "ACTIVE":
        return {
            "fulfillment_mode": "DROP_SHIP",
            "leg_mode": "LTL",
            "hub": None,
        }
    # Branch 4 — LTL network fallback
    hub = select_hub(hubs, lanes, zone, require_white_glove=False)
    if hub is None:
        raise err_no_route()
    return {
        "fulfillment_mode": "OWNED_FINAL_MILE",
        "leg_mode": "LTL",
        "hub": hub,
    }


def select_linehaul(linehauls, hub_id, shipments=()):
    """PLANNED linehaul into the hub with committed_count < capacity; earliest
    planned_arrival_date, tie-break created_at ASC.

    PRD §3.2 defines committed_count as a DERIVED counter — the number of
    shipments currently bound to the linehaul whose current_state is neither
    DELIVERED nor EXCEPTION — so capacity eligibility must be computed from
    live shipment state, not the stored counter (which is written for the
    serialization but cannot by itself exclude completed deliveries)."""
    def effective_committed(linehaul):
        return sum(
            1
            for s in shipments
            if s.get("linehaul_id") == linehaul["id"]
            and s["current_state"] not in ("DELIVERED", "EXCEPTION")
        )

    candidates = [
        lh
        for lh in linehauls
        if lh["hub_id"] == hub_id
        and lh["status"] == "PLANNED"
        and effective_committed(lh) < int(lh["capacity"])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda lh: (lh["planned_arrival_date"], lh["created_at"]))
    return candidates[0]


# --- Damage triage & liability -----------------------------------------------

def damage_triage(is_structural, damage_pct, repair_cost_cents, replacement_cost_cents):
    if is_structural or int(damage_pct) > 40:
        return "FULL_REPLACEMENT"
    if int(repair_cost_cents) > int(replacement_cost_cents):
        return "FULL_REPLACEMENT"
    if int(repair_cost_cents) >= 20000:
        return "REPAIR"
    return "REPLACEMENT_PART"


def chargeback_allocation(concealment, repair_cost_cents, replacement_cost_cents):
    repair = Decimal(int(repair_cost_cents))
    replacement = Decimal(int(replacement_cost_cents))
    if concealment == "CONCEALED":
        amount = round_half_up_int(repair * Decimal("1.00") + replacement * Decimal("0.35"))
        return "SUPPLIER", amount
    amount = round_half_up_int(repair * Decimal("0.40"))
    return "CARRIER", amount


def chargeback_reason_code(resolution_type):
    return {
        "REPLACEMENT_PART": "CONCEALED_DAMAGE",
        "REPAIR": "REPAIR_OVERRUN",
        "FULL_REPLACEMENT": "FULL_REPLACEMENT",
    }[resolution_type]


# --- Return disposition ------------------------------------------------------

_REFURB_PCT = {
    "DAMAGE": Decimal("0.10"),
    "BUYERS_REMORSE": Decimal("0.40"),
    "WRONG_ITEM": Decimal("0.90"),
}


def return_disposition(reason, declared_value_cents, ltl_lane_base_rate_cents):
    reverse_haul = round_half_up_int(Decimal(int(ltl_lane_base_rate_cents)) * Decimal("1.20"))
    refurb = round_half_up_int(Decimal(int(declared_value_cents)) * _REFURB_PCT[reason])
    # Ties resolve to FIELD_DISPOSAL (disposal wins at break-even).
    disposition = "RETURN_TO_HUB" if refurb > reverse_haul else "FIELD_DISPOSAL"
    return reverse_haul, refurb, disposition
