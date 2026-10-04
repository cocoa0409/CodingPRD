"""Domain calculations per SCAFFOLD calculations table (PRD 2.8, 3.3-3.5, 3.8)."""

from decimal import ROUND_HALF_UP, Decimal

from db import store
from models import fmt_iso

PLAN_CONGESTION_WEIGHT = Decimal("0.10")
EXEC_CONGESTION_WEIGHT = Decimal("0.25")
CONGESTION_CAP = 3
DETOUR_FLAT = Decimal("4")

NEW_SLOT_ACCESS_BASE = Decimal("3")

LATENESS_WEIGHT = 5
DISRUPTION_WEIGHT = 2
FATIGUE_WEIGHT = 1
STATION_BASE_RATE_SECONDS = 120

RATE_T1 = Decimal("0.5")
RATE_T2 = Decimal("0.3")
RATE_T3 = Decimal("0.1")

PICKS_PER_PICKER_HOUR = 120
UNITS_PER_TRIP = 6
TRIPS_PER_HOUR = 4
HOURS_IN_SHIFT = 8

BATTERY_MIN_DISPATCH = 20
CYCLE_PENALTY = 1
MAINTENANCE_CYCLE_THRESHOLD = 5
MAINT_BUFFER_MINUTES = 15


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def manhattan(x1, y1, x2, y2):
    return abs(x1 - x2) + abs(y1 - y2)


def zone_of(entity_zone_id):
    return store.zones.get(entity_zone_id)


def _corridor_bbox(zone_a, zone_b):
    return (
        min(zone_a["grid_x"], zone_b["grid_x"]),
        min(zone_a["grid_y"], zone_b["grid_y"]),
        max(zone_a["grid_x"], zone_b["grid_x"]),
        max(zone_a["grid_y"], zone_b["grid_y"]),
    )


def _intersects_bbox(zone, bbox):
    x1, y1, x2, y2 = bbox
    return x1 <= zone["grid_x"] <= x2 and y1 <= zone["grid_y"] <= y2


def congestion_count(pod_zone, station_zone, exclude_unit_id=None):
    """EN_ROUTE units whose in-flight task's pod zone intersects the corridor bbox."""
    bbox = _corridor_bbox(pod_zone, station_zone)
    count = 0
    for task in store.pick_tasks.values():
        if task["status"] != "DISPATCHED":
            continue
        unit_id = task.get("drive_unit_id")
        if not unit_id or unit_id == exclude_unit_id:
            continue
        unit = store.drive_units.get(unit_id)
        if not unit or unit["status"] != "EN_ROUTE":
            continue
        task_pod = store.pods.get(task["pod_id"])
        if not task_pod:
            continue
        task_pod_zone = store.zones.get(task_pod["zone_id"])
        if not task_pod_zone:
            continue
        if _intersects_bbox(task_pod_zone, bbox):
            count += 1
    return count


def travel_cost_estimate(task, variant, carrying_unit=None):
    """planning variant -> est_cost; execution variant -> actual_cost."""
    pod = store.pods[task["pod_id"]]
    station = store.pick_stations[task["station_id"]]
    pod_zone = store.zones[pod["zone_id"]]
    station_zone = store.zones[station["zone_id"]]
    base = Decimal(
        manhattan(
            pod_zone["grid_x"], pod_zone["grid_y"], station_zone["grid_x"], station_zone["grid_y"]
        )
    )
    exclude = carrying_unit["id"] if carrying_unit else None
    cong = congestion_count(pod_zone, station_zone, exclude_unit_id=exclude)
    if variant == "planning":
        capped = min(cong, CONGESTION_CAP)
        cost = base * (Decimal(1) + PLAN_CONGESTION_WEIGHT * Decimal(capped))
    else:
        cost = base * (Decimal(1) + EXEC_CONGESTION_WEIGHT * Decimal(cong))
        if carrying_unit is not None:
            home_zone = store.zones.get(carrying_unit["home_zone_id"])
            if home_zone is not None and home_zone.get("posture") == "RESTRICTED":
                cost = cost + DETOUR_FLAT
    return round2(cost)


def stow_density_score(pod, sku):
    """Score a candidate pod under the variant chosen by sku.velocity_class."""
    zone = store.zones[pod["zone_id"]]
    density_term = Decimal(pod["slots_used"]) / Decimal(pod["slot_capacity"])
    distance_term = Decimal(manhattan(zone["grid_x"], zone["grid_y"], 0, 0))
    sku_slots = [
        s
        for s in store.inventory_slots.values()
        if s["pod_id"] == pod["id"] and s["sku_id"] == sku["id"]
    ]
    if sku_slots:
        access_term = Decimal(sum(s["accessibility_rank"] for s in sku_slots)) / Decimal(
            len(sku_slots)
        )
    else:
        access_term = NEW_SLOT_ACCESS_BASE
    if sku["velocity_class"] == "LOW":
        score = (
            Decimal("0.6") * density_term
            - Decimal("0.3") * distance_term * Decimal("0.01")
            - Decimal("0.1") * access_term * Decimal("0.1")
        )
    else:
        score = (
            Decimal("0.6") * (Decimal(1) - access_term * Decimal("0.1"))
            - Decimal("0.3") * distance_term * Decimal("0.01")
            + Decimal("0.1") * density_term
        )
    return round4(score)


def fleet_selector_score(unit, pod):
    home_zone = store.zones.get(unit["home_zone_id"])
    pod_zone = store.zones.get(pod["zone_id"])
    if home_zone is None or pod_zone is None:
        return Decimal("-999999")
    dist = manhattan(
        home_zone["grid_x"], home_zone["grid_y"], pod_zone["grid_x"], pod_zone["grid_y"]
    )
    return (
        Decimal(unit["battery_pct"]) * 2
        - Decimal(dist)
        - Decimal(unit["charge_cycle_count"]) * Decimal(CYCLE_PENALTY)
    )


def charge_cycle_credit(started_at_dt, ended_at_dt):
    """Per-tier round-half-up-then-sum per PRD 2.8."""
    delta_seconds = (ended_at_dt - started_at_dt).total_seconds()
    duration_minutes = int(delta_seconds // 60)
    tier1 = round0(Decimal(min(duration_minutes, 30)) * RATE_T1)
    tier2 = round0(Decimal(max(0, min(duration_minutes, 90) - 30)) * RATE_T2)
    tier3 = round0(Decimal(max(0, duration_minutes - 90)) * RATE_T3)
    return tier1 + tier2 + tier3


def throughput_projection(plan):
    """Pessimistic variant per PRD 3.8 pinned evaluation order."""
    active_statuses = {"ACTIVE", "EN_ROUTE", "AT_STATION", "PARKED"}
    active_fleet = sum(1 for u in store.drive_units.values() if u["status"] in active_statuses)
    picker_capacity = plan["staffed_pickers"] * PICKS_PER_PICKER_HOUR * HOURS_IN_SHIFT
    fleet_capacity = active_fleet * UNITS_PER_TRIP * TRIPS_PER_HOUR * HOURS_IN_SHIFT
    open_demand = 0
    for order in store.orders.values():
        if order["status"] not in {"RECEIVED", "PLANNED", "IN_PROGRESS"}:
            continue
        cutoff = order.get("_cutoff_dt")
        if cutoff is None:
            continue
        if cutoff.strftime("%Y-%m-%d") != plan["plan_date"]:
            continue
        for line in store.order_lines.values():
            if line["order_id"] != order["id"]:
                continue
            open_demand += max(0, line["quantity"] - line["quantity_picked"])
    projected = min(picker_capacity, fleet_capacity, open_demand)
    feasible = projected >= plan["planned_units"]
    return projected, feasible


def recompute_shift_plans():
    for plan in store.shift_plans.values():
        projected, feasible = throughput_projection(plan)
        plan["projected_units"] = projected
        plan["feasible"] = feasible
