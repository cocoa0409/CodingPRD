"""Pod occupancy and bay accounting (PRD §2.4, scaffold C4 pod_utilization)."""

from decimal import Decimal, ROUND_HALF_UP

from db import STORE

UTILIZATION_MULTIPLIER = 12
PERIODIC_DEMAND_MULTIPLIER = 5
STALENESS_K = 60

FUEL_FLOORS = {"NEIGHBORHOOD": 25, "CAMPUS": 20, "AIRPORT": 35}


def _parked(pod_id):
    return [v for v in STORE.vehicles.values()
            if v.get("home_pod_id") == pod_id and v.get("use_status") != "RETIRED"]


def recompute_pod(pod):
    """Recompute utilization_score and available_bays for one pod (PRD §2.4)."""
    active_member_count = len(_parked(pod["id"]))
    periodic_demand = 0
    window_start = STORE.now().timestamp() - 24 * 3600
    for r in STORE.reservations.values():
        if r.get("status") != "CONFIRMED":
            continue
        stamp = r.get("reservation_at")
        if not stamp:
            continue
        from db import parse_ts
        if parse_ts(stamp).timestamp() >= window_start:
            periodic_demand += 1

    raw = active_member_count * UTILIZATION_MULTIPLIER + periodic_demand * PERIODIC_DEMAND_MULTIPLIER
    if raw == 0:
        score = Decimal(0)
    else:
        score = (Decimal(raw) / Decimal(raw + STALENESS_K)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    pod["utilization_score"] = float(score)
    pod["available_bays"] = max(0, int(pod.get("capacity", 0)) - active_member_count)
    STORE.touch(pod)
    return pod


def recompute_all():
    for pod in STORE.pods.values():
        recompute_pod(pod)


def recompute_pods_for(*pod_ids):
    seen = set()
    for pid in pod_ids:
        if pid and pid not in seen:
            seen.add(pid)
            pod = STORE.pods.get(pid)
            if pod is not None:
                recompute_pod(pod)


def fuel_floor(pod):
    """The pod's declared minimum acceptable fuel level at return."""
    if pod.get("fuel_floor_pct") is not None:
        return int(pod["fuel_floor_pct"])
    return FUEL_FLOORS.get(pod.get("site_type"), 25)