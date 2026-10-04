"""Business logic: posture engine, cascades, and the five calculation rules.

Every rule here traces to PRD §3 / SCAFFOLD §1.3. Monetary arithmetic uses
decimal.Decimal with ROUND_HALF_UP; allocation arithmetic stays in integer
dozens.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import (
    DB, err, find, find_one, get, iso, now, parse_date, table, today_str, touch,
)

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
DOZEN_CREDIT_BASE_CENTS = 1200
STALE_TIER1_DOZENS = 6
STALE_TIER2_DOZENS = 24
TIER0_RATE = Decimal("0.50")
TIER1_RATE = Decimal("0.65")
TIER2_RATE = Decimal("0.80")
LATE_PENALTY_FACTOR = Decimal("0.9")
DISPUTE_WINDOW_HOURS = 48
MIN_YIELD_RATE = Decimal("0.85")
FRESHNESS_HOURS = 12
TIER_A_MAX = 25
TIER_B_MAX = 100
TIER_A_PRICE_CENTS = 700
TIER_B_PRICE_CENTS = 650
TIER_C_PRICE_CENTS = 600
CHARITY_DISCOUNT_PCT = Decimal("0.10")
DEMAND_LOW_THRESHOLD = 30
DEMAND_HIGH_THRESHOLD = 120
EXTEND_CAP_HIGH_MINUTES = 90
EXTEND_CAP_LOW_MINUTES = 45
LEAD_TIME_HOURS = 8
PICKUP_GRACE_HOURS = 4


def round_half_up_0(value):
    """Round a Decimal to integer with ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Field validators for request payloads
# ---------------------------------------------------------------------------
class Body:
    def __init__(self, body):
        self.body = body or {}

    def required(self, name):
        value = self.body.get(name)
        if value is None or (isinstance(value, str) and value == ""):
            err("ERR_INVALID_REQUEST", "%s is required." % name)
        return value

    def optional(self, name, default=None):
        value = self.body.get(name)
        if value is None:
            return default
        return value

    def integer(self, name, required=True, minimum=None, default=None):
        value = self.body.get(name)
        if value is None:
            if required:
                err("ERR_INVALID_REQUEST", "%s is required." % name)
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
        if minimum is not None and value < minimum:
            err("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, minimum))
        return value

    def string(self, name, required=True, default=None):
        value = self.body.get(name)
        if value is None:
            if required:
                err("ERR_INVALID_REQUEST", "%s is required." % name)
            return default
        if not isinstance(value, str) or value == "":
            err("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
        return value

    def enum(self, name, allowed, required=True):
        value = self.body.get(name)
        if value is None:
            if required:
                err("ERR_INVALID_REQUEST", "%s is required." % name)
            return None
        if value not in allowed:
            err("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
        return value


# ---------------------------------------------------------------------------
# Path-scoped resource lookups (PRD §2.7): left-to-right, child-under-parent
# mismatch is a not-found.
# ---------------------------------------------------------------------------
def require_network(network_id):
    network = get("networks", network_id)
    if network is None:
        err("ERR_NOT_FOUND", "Network not found.")
    return network


def require_hub(network_id, hub_id):
    require_network(network_id)
    hub = get("hubs", hub_id)
    if hub is None or hub["network_id"] != network_id:
        err("ERR_NOT_FOUND", "Hub not found.")
    return hub


def require_door(network_id, door_id):
    require_network(network_id)
    door = get("doors", door_id)
    if door is None or door["network_id"] != network_id:
        err("ERR_NOT_FOUND", "Door not found.")
    return door


def require_line(network_id, hub_id, line_id):
    require_hub(network_id, hub_id)
    line = get("lines", line_id)
    if line is None or line["hub_id"] != hub_id:
        err("ERR_NOT_FOUND", "Equipment line not found.")
    return line


def require_variety(network_id, variety_id):
    require_network(network_id)
    variety = get("varieties", variety_id)
    if variety is None or variety["network_id"] != network_id:
        err("ERR_NOT_FOUND", "Variety not found.")
    return variety


def require_mix_plan(network_id, door_id, plan_id):
    require_door(network_id, door_id)
    plan = get("mix_plans", plan_id)
    if plan is None or plan["door_id"] != door_id:
        err("ERR_NOT_FOUND", "Mix plan not found.")
    return plan


def require_batch(network_id, hub_id, batch_id):
    require_hub(network_id, hub_id)
    batch = get("batches", batch_id)
    if batch is None or batch["hub_id"] != hub_id:
        err("ERR_NOT_FOUND", "Production batch not found.")
    return batch


def require_route(network_id, hub_id, route_id):
    require_hub(network_id, hub_id)
    route = get("routes", route_id)
    if route is None or route["hub_id"] != hub_id:
        err("ERR_NOT_FOUND", "Route not found.")
    return route


def require_stop(network_id, hub_id, route_id, stop_id):
    require_route(network_id, hub_id, route_id)
    stop = get("stops", stop_id)
    if stop is None or stop["route_id"] != route_id:
        err("ERR_NOT_FOUND", "Route stop not found.")
    return stop


def require_shipment_row(network_id, shipment_id):
    require_network(network_id)
    shipment = get("shipments", shipment_id)
    if shipment is None:
        err("ERR_NOT_FOUND", "Shipment not found.")
    stop = get("stops", shipment["route_stop_id"])
    route = get("routes", stop["route_id"])
    hub = get("hubs", route["hub_id"])
    if hub["network_id"] != network_id:
        err("ERR_NOT_FOUND", "Shipment not found.")
    return shipment


def require_stale_credit(network_id, door_id, credit_id):
    require_door(network_id, door_id)
    credit = get("stale_credits", credit_id)
    if credit is None or credit["door_id"] != door_id:
        err("ERR_NOT_FOUND", "Stale credit not found.")
    return credit


def require_fundraiser(network_id, door_id, order_id):
    require_door(network_id, door_id)
    order = get("fundraisers", order_id)
    if order is None or order["door_id"] != door_id:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    return order


def require_window(network_id, door_id, window_id):
    require_door(network_id, door_id)
    window = get("hot_light_windows", window_id)
    if window is None or window["door_id"] != door_id:
        err("ERR_NOT_FOUND", "Hot-light window not found.")
    return window


def check_door_ownership(ctx, door_id):
    """DoorManager identity is the Door id (PRD §2.1); ownership-gated
    endpoints compare the acting door id to the door in the path."""
    if ctx.role == "DoorManager" and ctx.user_id != door_id:
        err("ERR_UNAUTHORIZED", "A door manager may only operate on their own door.")


# ---------------------------------------------------------------------------
# Equipment line derived fields
# ---------------------------------------------------------------------------
def effective_dozens(line):
    status = line["line_status"]
    if status == "OPERATIONAL":
        return line["rated_dozens_per_hour"]
    if status == "DEGRADED":
        return math.floor(line["rated_dozens_per_hour"] * 0.6)
    return 0


def hub_has_working_line(hub_id):
    return any(
        l["line_status"] in ("OPERATIONAL", "DEGRADED")
        for l in find("lines", lambda l: l["hub_id"] == hub_id)
    )


# ---------------------------------------------------------------------------
# Network posture (PRD §2.6, SCAFFOLD calculations.network_posture).
# Pinned evaluation order: SUSPENDED -> DEGRADED -> CLOSED (sticky) -> OPEN.
# ---------------------------------------------------------------------------
def recompute_posture(network_id):
    network = get("networks", network_id)
    if network is None:
        return
    if network.get("network_posture") == "CLOSED":
        return  # CLOSED is sticky and terminal.
    hubs = find("hubs", lambda h: h["network_id"] == network_id)
    suspended = False
    for hub in hubs:
        lines = find("lines", lambda l: l["hub_id"] == hub["id"])
        if not any(l["line_status"] in ("OPERATIONAL", "DEGRADED") for l in lines):
            suspended = True
            break
    if suspended:
        new_posture = "SUSPENDED"
    else:
        shortfalls_today = len(find(
            "batches",
            lambda b: b["batch_status"] == "SHORTFALL"
            and b.get("production_date") == today_str()
            and get("hubs", b["hub_id"])
            and get("hubs", b["hub_id"])["network_id"] == network_id,
        ))
        any_door_suspended = any(
            d["door_status"] == "SUSPENDED"
            for d in find("doors", lambda d: d["network_id"] == network_id)
        )
        if shortfalls_today >= 2 or any_door_suspended:
            new_posture = "DEGRADED"
        else:
            new_posture = "OPEN"
    if network["network_posture"] != new_posture:
        network["network_posture"] = new_posture
        touch(network)


# ---------------------------------------------------------------------------
# Door status derivation and cascades (PRD §3.1 / §3.6).
# ---------------------------------------------------------------------------
def door_hub_has_working_line(door):
    if door["door_kind"] == "THEATER":
        # Self-supplied: any working line on the network hubs is enough;
        # theater doors are only suspended via disputes or manual action.
        return True
    hub_id = door.get("hub_id")
    if hub_id is None:
        return False
    return hub_has_working_line(hub_id)


def maybe_suspend_door_for_hub_lines(hub_id):
    """After a line state change: doors supplied by a hub with no working line
    flip to SUSPENDED (PRD §3.2 decommission cascade)."""
    if hub_has_working_line(hub_id):
        return
    for door in find("doors", lambda d: d.get("hub_id") == hub_id):
        if door["door_status"] == "ACTIVE":
            door["door_status"] = "SUSPENDED"
            touch(door)


def maybe_unsuspend_door(door):
    """A door suspended solely on disputes returns to ACTIVE once the count
    drops below 3 and the supplying hub has a working line (PRD §3.6)."""
    if door["door_status"] != "SUSPENDED":
        return
    if door["open_dispute_count"] >= 3:
        return
    if not door_hub_has_working_line(door):
        return
    door["door_status"] = "ACTIVE"
    touch(door)


# ---------------------------------------------------------------------------
# Calculation: stale_credit (PRD §3.6, SCAFFOLD calculations.stale_credit)
# ---------------------------------------------------------------------------
def _tier_rate(pulled_dozens):
    if pulled_dozens >= STALE_TIER2_DOZENS:
        return TIER2_RATE
    if pulled_dozens >= STALE_TIER1_DOZENS:
        return TIER1_RATE
    return TIER0_RATE


def stale_credit_provisional(pulled_dozens, freshness_override):
    base = Decimal(pulled_dozens) * DOZEN_CREDIT_BASE_CENTS
    rate = _tier_rate(pulled_dozens)
    if freshness_override:
        rate = rate * Decimal("0.5")
    return round_half_up_0(base * rate)


def stale_credit_final(pulled_dozens, arrived_late):
    base = Decimal(pulled_dozens) * DOZEN_CREDIT_BASE_CENTS
    credit = base * _tier_rate(pulled_dozens)
    if arrived_late:
        credit = credit * LATE_PENALTY_FACTOR
    return round_half_up_0(credit)


def stop_arrived_late(stop):
    """True when the stop's recorded arrival instant was after window_end."""
    arrived_at = stop.get("_arrived_at")
    if arrived_at is None:
        return False
    return arrived_at > stop["_window_end_dt"]


# ---------------------------------------------------------------------------
# Calculation: mix_allocation waterfall (PRD §3.3).
# Bucket order pinned: fundraiser reservations (pickup_at ASC, created_at ASC
# tie-break), then mix plan lines (effective_date ASC, door created_at ASC,
# line created_at ASC).
# ---------------------------------------------------------------------------
def run_mix_allocation(hub_id, production_date):
    batches = find(
        "batches",
        lambda b: b["hub_id"] == hub_id
        and b["production_date"] == production_date
        and b["batch_status"] == "COMPLETED",
    )
    available = sum(int(b.get("produced_dozens") or 0) for b in batches)

    # Bucket 1: fundraiser reservations SCHEDULED/READY at doors supplied by
    # this hub (or theater doors) with pickup date == production_date.
    doors_of_hub = find(
        "doors",
        lambda d: d.get("hub_id") == hub_id or (
            d["door_kind"] == "THEATER"
            and get("networks", d["network_id"]) is not None
            and get("hubs", hub_id) is not None
            and get("networks", d["network_id"])["id"]
            == get("hubs", hub_id)["network_id"]
        ),
    )
    door_ids = {d["id"] for d in doors_of_hub}
    orders = [
        o for o in find(
            "fundraisers",
            lambda o: o["door_id"] in door_ids
            and o["fundraiser_status"] in ("SCHEDULED", "READY")
            and o["_pickup_dt"].date().isoformat() == production_date,
        )
    ]
    orders.sort(key=lambda o: (o["_pickup_dt"], o["created_at"]))

    # Bucket 2: mix plan lines of PUBLISHED/LOCKED plans for doors supplied by
    # this hub, effective_date == production_date.
    plans = [
        p for p in find(
            "mix_plans",
            lambda p: p["door_id"] in door_ids
            and p["mix_plan_status"] in ("PUBLISHED", "LOCKED")
            and p["effective_date"] == production_date,
        )
    ]
    lines = []
    for plan in plans:
        plan_lines = find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"])
        plan_lines.sort(key=lambda l: l["created_at"])
        for line in plan_lines:
            lines.append((plan, line))
    lines.sort(key=lambda pl: (
        pl[0]["effective_date"],
        get("doors", pl[0]["door_id"])["created_at"],
        pl[1]["created_at"],
    ))

    # Reset every relevant line allocation before the waterfall re-run.
    for _plan, line in lines:
        if line["allocated_dozens"] != 0:
            line["allocated_dozens"] = 0
            touch(line)

    for order in orders:
        grant = min(int(order["requested_dozens"]), available)
        available -= grant
    for _plan, line in lines:
        need = int(line["planned_dozens"])
        grant = min(need, available)
        if grant != line["allocated_dozens"]:
            line["allocated_dozens"] = grant
            touch(line)
        available -= grant


# ---------------------------------------------------------------------------
# Calculation: fundraiser_pricing (PRD §3.7) — marginal tiers, per-line
# rounding pinned before summation.
# ---------------------------------------------------------------------------
def fundraiser_quote(requested_dozens, organization_name):
    discount = Decimal("0")
    if organization_name and "charity" in str(organization_name).lower():
        discount = CHARITY_DISCOUNT_PCT
    total = 0
    for d in range(1, int(requested_dozens) + 1):
        if d <= TIER_A_MAX:
            price = TIER_A_PRICE_CENTS
        elif d <= TIER_B_MAX:
            price = TIER_B_PRICE_CENTS
        else:
            price = TIER_C_PRICE_CENTS
        total += round_half_up_0(Decimal(price) * (Decimal("1") - discount))
    return total


# ---------------------------------------------------------------------------
# Calculation: hot_light_demand_response (PRD §3.8)
# ---------------------------------------------------------------------------
def demand_response_cap(door):
    """Cap in minutes from fresh dozens at the theater door's hub today."""
    hub_id = theater_hub_for_door(door)
    fresh = 0
    if hub_id is not None:
        for b in find(
            "batches",
            lambda b: b["hub_id"] == hub_id
            and b["batch_status"] == "COMPLETED"
            and b["production_date"] == today_str()
            and b.get("_fresh_until_dt") is not None
            and b["_fresh_until_dt"] > now(),
        ):
            fresh += int(b.get("produced_dozens") or 0)
    # subtract allocated dozens across the hub's doors' lines today
    if hub_id is not None:
        doors_of_hub = find("doors", lambda d: d.get("hub_id") == hub_id)
        door_ids = {d["id"] for d in doors_of_hub} | {door["id"]}
        plans = find(
            "mix_plans",
            lambda p: p["door_id"] in door_ids
            and p["mix_plan_status"] in ("PUBLISHED", "LOCKED")
            and p["effective_date"] == today_str(),
        )
        for plan in plans:
            for line in find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"]):
                fresh -= int(line["allocated_dozens"])
    if fresh >= DEMAND_HIGH_THRESHOLD:
        return EXTEND_CAP_HIGH_MINUTES
    if fresh >= DEMAND_LOW_THRESHOLD:
        return EXTEND_CAP_LOW_MINUTES
    return 0


def theater_hub_for_door(door):
    """A THEATER door is self-supplied; its production hub for fresh-batch
    purposes is the single hub of its network when it has no hub_id."""
    if door.get("hub_id"):
        return door["hub_id"]
    hubs = find("hubs", lambda h: h["network_id"] == door["network_id"])
    if len(hubs) == 1:
        return hubs[0]["id"]
    # Fall back to any hub of the network holding a completed fresh batch.
    return hubs[0]["id"] if hubs else None


def door_has_fresh_batch_today(door):
    hub_id = theater_hub_for_door(door)
    if hub_id is None:
        return False
    return any(
        b["batch_status"] == "COMPLETED"
        and b.get("_fresh_until_dt") is not None
        and b["_fresh_until_dt"] > now()
        for b in find(
            "batches",
            lambda b: b["hub_id"] == hub_id
            and b["production_date"] == today_str(),
        )
    )


# ---------------------------------------------------------------------------
# Clock-driven system transitions (PRD §2.5): re-evaluated on every clock set.
# ---------------------------------------------------------------------------
def apply_time_transitions():
    current = now()
    today = today_str()

    # Variety expiry: EXPIRED once current time >= active_until.
    for variety in table("varieties").values():
        if variety["variety_status"] == "ACTIVE" and current >= variety["_active_until_dt"]:
            variety["variety_status"] = "EXPIRED"
            touch(variety)

    # Route auto-completion after stop transitions.
    for route in find("routes", lambda r: r["route_status"] == "DISPATCHED"):
        _maybe_complete_route(route)


def _miss_stop(stop):
    stop["stop_status"] = "MISSED"
    touch(stop)
    for shipment in find("shipments", lambda s: s["route_stop_id"] == stop["id"]):
        if shipment["delivery_status"] in ("STAGED", "IN_TRANSIT"):
            shipment["delivery_status"] = "FAILED"
            touch(shipment)
    route = get("routes", stop["route_id"])
    if route is not None:
        run_mix_allocation(route["hub_id"], route["service_date"])


def _maybe_complete_route(route):
    if route["route_status"] != "DISPATCHED":
        return
    stops = find("stops", lambda s: s["route_id"] == route["id"])
    if stops and all(s["stop_status"] in ("DELIVERED", "MISSED", "CREDITED") for s in stops):
        route["route_status"] = "COMPLETED"
        touch(route)
        hub = get("hubs", route["hub_id"])
        if hub is not None:
            recompute_posture(hub["network_id"])


# ---------------------------------------------------------------------------
# stale_credit_pool_cents recompute (PRD §3.5): sum of FINALIZED
# final_credit_cents minus RESOLVED payouts, never negative.
# ---------------------------------------------------------------------------
def recompute_pool(network_id):
    network = get("networks", network_id)
    if network is None:
        return
    doors = find("doors", lambda d: d["network_id"] == network_id)
    door_ids = {d["id"] for d in doors}
    finalized = sum(
        int(c.get("final_credit_cents") or 0)
        for c in find(
            "stale_credits",
            lambda c: c["door_id"] in door_ids and c["credit_state"] == "FINALIZED",
        )
    )
    network["stale_credit_pool_cents"] = max(0, finalized)


# ---------------------------------------------------------------------------
# Route reconcile cascade (PRD §3.5).
# ---------------------------------------------------------------------------
def reconcile_route_cascade(route):
    hub = get("hubs", route["hub_id"])
    network_id = hub["network_id"]
    stops = find("stops", lambda s: s["route_id"] == route["id"])
    stop_by_id = {s["id"]: s for s in stops}
    shipments = find("shipments", lambda s: s["route_stop_id"] in stop_by_id)
    shipment_ids = {s["id"] for s in shipments}
    for credit in find(
        "stale_credits",
        lambda c: c["shipment_id"] in shipment_ids and c["credit_state"] == "PROVISIONAL",
    ):
        stop = stop_by_id.get(get("shipments", credit["shipment_id"])["route_stop_id"])
        late = stop_arrived_late(stop) if stop else False
        final = stale_credit_final(int(credit["pulled_dozens"]), late)
        delta = final - int(credit["provisional_credit_cents"])
        credit["final_credit_cents"] = final
        credit["credit_state"] = "FINALIZED"
        touch(credit)
        door = get("doors", credit["door_id"])
        door["credit_balance_cents"] = max(0, int(door["credit_balance_cents"]) + delta)
        touch(door)
        shipment = get("shipments", credit["shipment_id"])
        if shipment["credit_status"] == "PENDING_PULL":
            shipment["credit_status"] = "CREDITED"
            touch(shipment)
    recompute_pool(network_id)


def maybe_credit_stop(stop):
    """DELIVERED -> CREDITED once all credits for the stop's shipments are
    RESOLVED and at least one exists (PRD §1.2 RouteStop)."""
    if stop["stop_status"] != "DELIVERED":
        return
    shipments = find("shipments", lambda s: s["route_stop_id"] == stop["id"])
    shipment_ids = {s["id"] for s in shipments}
    credits = find("stale_credits", lambda c: c["shipment_id"] in shipment_ids)
    if credits and all(c["credit_state"] == "RESOLVED" for c in credits):
        stop["stop_status"] = "CREDITED"
        touch(stop)


def parse_effective_date(value):
    return parse_date(value, "effective_date")


def enter_maintenance(line):
    """Maintenance cascade (PRD §3.2): cancel today's SCHEDULED/COMMITTED
    batches on the line, drain committed dozens, recompute posture."""
    line["line_status"] = "MAINTENANCE"
    line["effective_dozens_per_hour"] = 0
    touch(line)
    hub = get("hubs", line["hub_id"])
    today = today_str()
    for batch in find(
        "batches",
        lambda b: b["equipment_line_id"] == line["id"]
        and b["batch_status"] in ("SCHEDULED", "COMMITTED")
        and b["production_date"] == today,
    ):
        was_committed = batch["batch_status"] == "COMMITTED"
        batch["batch_status"] = "CANCELLED"
        touch(batch)
        if was_committed and hub is not None:
            hub["committed_dozens_today"] = max(
                0, int(hub["committed_dozens_today"]) - int(batch["planned_dozens"])
            )
            touch(hub)
    if hub is not None:
        recompute_posture(hub["network_id"])
        maybe_suspend_door_for_hub_lines(hub["id"])
