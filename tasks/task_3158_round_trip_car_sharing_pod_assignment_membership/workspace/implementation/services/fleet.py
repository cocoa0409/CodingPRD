"""Pods, vehicles, cleanliness and relocation bundles (PRD §3.5, §3.12)."""

from db import STORE, ordered, paginate, parse_ts, whole_minutes
from errors import fail
from services import lookup
from services.calculations import shift_bundle_fee
from services.pods import recompute_pod, recompute_pods_for, FUEL_FLOORS

SITE_TYPES = ("NEIGHBORHOOD", "CAMPUS", "AIRPORT")
SITE_CYCLE = {"NEIGHBORHOOD": "CAMPUS", "CAMPUS": "AIRPORT", "AIRPORT": "NEIGHBORHOOD"}
USE_STATUSES = ("AVAILABLE", "RESERVED", "IN_USE", "CLEANING", "MAINTENANCE",
                "OUT_OF_SERVICE", "RETIRED")
CLEANLINESS_STATES = ("CLEAN", "REPORTED_DIRTY", "CLEANING", "ESCALATED",
                      "SUSPENDED_FOR_CLEANLINESS")
CLEANLINESS_RESTORE_DAYS = 180
LIVE_RESERVATION_STATES = ("HELD", "CONFIRMED", "IN_USE", "OVERDUE")
LIVE_ORDER_STATES = ("SCHEDULED", "BLOCKED", "IN_PROGRESS")


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---- pods ------------------------------------------------------------------
def create_pod(data, fields):
    """POST /car-share/pods (FleetAdmin) — PRD §3.5."""
    name = fields.field(data, "name", "string", required=True)
    site_type = fields.field(data, "site_type", "string", required=True, enum=SITE_TYPES)
    capacity = fields.field(data, "capacity", "integer", required=True)
    floor = fields.field(data, "fuel_floor_pct", "integer", default=None)

    row = STORE.create(
        STORE.pods,
        name=name,
        site_type=site_type,
        capacity=capacity,
        utilization_score=0.0,
        available_bays=capacity,
        fuel_floor_pct=floor if floor is not None else FUEL_FLOORS[site_type],
    )
    recompute_pod(row)  # a fresh pod reports available_bays == capacity, score 0
    return row


def reclassify_pod(pod_id, data, fields):
    """POST /car-share/pods/{id}/reclassify (FleetAdmin) — PRD §3.5."""
    pod = lookup.pod(pod_id)
    fields.field(data, "site_type", "string", required=True, enum=SITE_TYPES)

    if pod.get("site_type") not in SITE_TYPES:
        fail("ERR_INVALID_STATE", "The pod's site_type is outside the declared cycle.")
    for o in STORE.maintenance_orders.values():
        if o.get("pod_id") == pod["id"] and o.get("status") in ("BLOCKED", "IN_PROGRESS"):
            fail("ERR_INVALID_STATE",
                 "A pod holding a BLOCKED or IN_PROGRESS order cannot be reclassified.")

    pod["site_type"] = SITE_CYCLE[pod["site_type"]]
    pod["fuel_floor_pct"] = FUEL_FLOORS[pod["site_type"]]
    recompute_pod(pod)
    STORE.bump(pod)
    return pod


def list_pods(site_type, limit, offset):
    rows = ordered(STORE.pods.values())
    if site_type:
        rows = [r for r in rows if r.get("site_type") == site_type]
    return paginate(rows, limit, offset)


def get_pod(pod_id):
    return lookup.pod(pod_id)


def pod_vehicles(pod_id):
    lookup.pod(pod_id)
    return ordered([v for v in STORE.vehicles.values() if v.get("home_pod_id") == pod_id])


# ---- vehicles ---------------------------------------------------------------
def create_vehicle(data, fields):
    """POST /car-share/vehicles (FleetAdmin) — PRD §3.5."""
    pod_id = fields.field(data, "pod_id", "string", required=True)
    vin = fields.field(data, "vin", "string", required=True)
    model = fields.field(data, "model", "string", required=True)
    seats = fields.field(data, "capacity_seats", "integer", required=True)
    next_service = fields.field(data, "next_service_miles", "integer", default=0)

    pod = lookup.pod(pod_id)  # an unknown pod_id is ERR_POD_NOT_FOUND

    # PRD §3.5: "The `vin` is unique across all vehicles". A duplicate VIN is the
    # malformed request it is rather than the pod's capacity; the guard sits below
    # the pod-resolution existence check so an unknown pod still reports itself.
    if int(pod.get("available_bays") or 0) > 0:
        for v in STORE.vehicles.values():
            if v.get("vin") == vin:
                fail("ERR_INVALID_REQUEST", "A vehicle with this vin already exists.")

    if int(pod.get("available_bays") or 0) <= 0:
        fail("ERR_POD_CAPACITY_EXCEEDED", "The destination pod has no free bay.")

    row = STORE.create(
        STORE.vehicles,
        pod_id=pod["id"],
        vin=vin,
        model=model,
        home_pod_id=pod["id"],
        capacity_seats=seats,
        odometer_miles=0,
        next_service_miles=next_service if next_service is not None else 0,
        use_status="AVAILABLE",
        cleanliness_state="CLEAN",
        fuel_level_pct=100,
        last_known_odometer_at=None,
        charge_total_cents=0,
    )
    recompute_pod(pod)
    STORE.bump(pod)
    return row


def get_vehicle(vehicle_id):
    return lookup.vehicle(vehicle_id)


def list_vehicles(pod_id, home_pod_id, use_status, cleanliness_state, limit, offset):
    rows = ordered(STORE.vehicles.values())
    if pod_id:
        rows = [r for r in rows if r.get("pod_id") == pod_id]
    if home_pod_id:
        rows = [r for r in rows if r.get("home_pod_id") == home_pod_id]
    if use_status:
        rows = [r for r in rows if r.get("use_status") == use_status]
    if cleanliness_state:
        rows = [r for r in rows if r.get("cleanliness_state") == cleanliness_state]
    return paginate(rows, limit, offset)


def availability_event(vehicle_id, data, fields):
    """POST /car-share/vehicles/{id}/availability-events — PRD §3.5."""
    vehicle = lookup.vehicle(vehicle_id)
    event = fields.field(data, "event", "string", required=True,
                         enum=("OUT_OF_SERVICE", "RETIRE"))
    status = vehicle["use_status"]

    if event == "OUT_OF_SERVICE":
        if status not in ("AVAILABLE", "RESERVED"):
            fail("ERR_INVALID_STATE", "Only an AVAILABLE or RESERVED vehicle may be taken out of service.")
        if _has_live_in_use(vehicle["id"]):
            fail("ERR_INVALID_STATE", "A vehicle with an IN_USE reservation cannot be taken out of service.")
        vehicle["use_status"] = "OUT_OF_SERVICE"
    else:
        if status != "OUT_OF_SERVICE":
            fail("ERR_INVALID_STATE", "Only an OUT_OF_SERVICE vehicle may be retired.")
        vehicle["use_status"] = "RETIRED"

    recompute_pod(lookup.pod(vehicle["home_pod_id"]))
    STORE.bump(vehicle)
    return vehicle


def _has_live_in_use(vehicle_id):
    return any(r.get("vehicle_id") == vehicle_id and r.get("status") == "IN_USE"
               for r in STORE.reservations.values())


def cleanliness_restore(vehicle_id):
    """POST /car-share/vehicles/{id}/cleanliness-restore — PRD §3.12."""
    vehicle = lookup.vehicle(vehicle_id)
    if vehicle.get("cleanliness_state") != "SUSPENDED_FOR_CLEANLINESS":
        fail("ERR_INVALID_STATE",
             "Only a SUSPENDED_FOR_CLEANLINESS vehicle may be restored.")

    cutoff = STORE.now().timestamp() - CLEANLINESS_RESTORE_DAYS * 86400
    for s in STORE.community_signals.values():
        if s.get("vehicle_id") != vehicle["id"] or s.get("signal_type") != "CLEANLINESS":
            continue
        if parse_ts(s["created_at_signal"]).timestamp() >= cutoff:
            fail("ERR_INVALID_STATE", "The cleanliness reporting window has not cleared.")

    vehicle["cleanliness_state"] = "CLEAN"
    if vehicle["use_status"] == "OUT_OF_SERVICE":
        vehicle["use_status"] = "AVAILABLE"
    recompute_pod(lookup.pod(vehicle["home_pod_id"]))
    STORE.bump(vehicle)
    return vehicle


# ---- shift bundles ---------------------------------------------------------
def _count_not_moved(pod_id, exclude_ids):
    return len([v for v in STORE.vehicles.values()
                if v.get("home_pod_id") == pod_id and v.get("use_status") != "RETIRED"
                and v["id"] not in exclude_ids])


def _count_at_pod(pod_id):
    return len([v for v in STORE.vehicles.values()
                if v.get("home_pod_id") == pod_id and v.get("use_status") != "RETIRED"])


def _window_overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: exactly adjacent windows do not collide."""
    a_s, a_e = parse_ts(a_start), parse_ts(a_end)
    b_s, b_e = parse_ts(b_start), parse_ts(b_end)
    return a_s < b_e and b_s < a_e


def apply_shift_bundle(data, fields):
    """POST /car-share/shift-bundles (PodOperator) — PRD §3.5."""
    source_id = fields.field(data, "source_pod_id", "string", required=True)
    dest_id = fields.field(data, "dest_pod_id", "string", required=True)
    start = fields.field(data, "scheduled_start", "datetime", required=True)
    end = fields.field(data, "scheduled_end", "datetime", required=True)
    monthly = fields.field(data, "monthly_pods", "array", required=True)
    expected_version = fields.field(data, "expected_pod_version_profile", "integer", required=True)

    source = lookup.pod(source_id)
    dest = lookup.pod(dest_id)

    vehicles = [lookup.vehicle(v) for v in monthly]

    for v in vehicles:
        if v.get("use_status") != "AVAILABLE":
            fail("ERR_INVALID_STATE", "Every relocated vehicle must be AVAILABLE.")
        for r in STORE.reservations.values():
            if r.get("vehicle_id") != v["id"] or r.get("status") not in LIVE_RESERVATION_STATES:
                continue
            if _window_overlaps(start, end, r["start_at"], r["end_at"]):
                fail("ERR_BUNDLE_WINDOW_CONFLICT",
                     "A live reservation for a source vehicle falls inside the bundle window.")
        for o in STORE.maintenance_orders.values():
            if o.get("vehicle_id") != v["id"] or o.get("status") not in LIVE_ORDER_STATES:
                continue
            if _window_overlaps(start, end, o["scheduled_start"], o["scheduled_end"]):
                fail("ERR_BUNDLE_WINDOW_CONFLICT",
                     "A live maintenance order for a source vehicle falls inside the bundle window.")

    if int(dest.get("available_bays") or 0) <= 0 or int(dest.get("available_bays") or 0) < len(vehicles):
        fail("ERR_POD_CAPACITY_EXCEEDED", "The destination pod has no free bay for the bundle.")

    if int(expected_version) != int(dest.get("version") or 0):
        fail("ERR_STALE_VERSION", "The destination pod version is stale.")

    moved_ids = {v["id"] for v in vehicles}
    source_available = _count_not_moved(source["id"], moved_ids)
    dest_available = _count_at_pod(dest["id"])
    fee = shift_bundle_fee(len(vehicles), source_available, dest_available)

    for v in vehicles:
        v["pod_id"] = dest["id"]
        v["home_pod_id"] = dest["id"]
        STORE.bump(v)

    bundle = STORE.create(
        STORE.shift_bundles,
        source_pod_id=source["id"],
        dest_pod_id=dest["id"],
        scheduled_start=start,
        scheduled_end=end,
        monthly_pods=list(monthly),
        bundle_fee_cents=fee,
        status="APPLIED",
    )
    recompute_pods_for(source["id"], dest["id"])
    STORE.bump(dest)
    return bundle


def list_shift_bundles(source_pod_id, dest_pod_id, limit, offset):
    rows = ordered(STORE.shift_bundles.values())
    if source_pod_id:
        rows = [r for r in rows if r.get("source_pod_id") == source_pod_id]
    if dest_pod_id:
        rows = [r for r in rows if r.get("dest_pod_id") == dest_pod_id]
    return paginate(rows, limit, offset)


def bundles_for_pod(pod_id):
    lookup.pod(pod_id)
    return ordered([b for b in STORE.shift_bundles.values()
                    if b.get("source_pod_id") == pod_id or b.get("dest_pod_id") == pod_id])