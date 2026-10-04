"""Aggregate recomputation and the cascading side effects they drive."""

from datetime import timedelta

from db import DB, touch, iso, parse_iso
import calc


# --------------------------------------------------------------- aggregates --
def recompute_station(store, station_id, recompute_posture=True):
    station = store.stations.get(station_id)
    if station is None:
        return
    station["active_bag_count"] = calc.active_bag_count(store, station_id)
    station["manual_queue_depth"] = calc.manual_queue_depth(store, station_id)
    open_sum, settled_sum = calc.liability_ledger(store, station_id)
    station["open_liability_cents"] = open_sum
    station["settled_liability_cents"] = settled_sum
    if recompute_posture:
        station["posture"] = calc.station_posture(store, station)
    station["updated_at"] = iso(store.now())
    station["version"] = station.get("version", 0) + 1


def recompute_area(store, area_id):
    area = store.makeup_areas.get(area_id)
    if area is None:
        return
    occupied, released, free = calc.area_occupancy(store, area)
    area["occupied_slots"] = occupied
    area["released_slots"] = released
    area["free_slots"] = free
    area["updated_at"] = iso(store.now())
    area["version"] = area.get("version", 0) + 1


def recompute_lane(store, lane_id):
    lane = store.lanes.get(lane_id)
    if lane is None:
        return
    ends = [s["end_utc"] for s in store.screenings.values()
            if s["lane_id"] == lane_id and s["status"] != "FAILED" and s.get("end_utc")]
    lane["last_event_end_utc"] = max(ends) if ends else None
    lane["updated_at"] = iso(store.now())
    lane["version"] = lane.get("version", 0) + 1


def recompute_flight(store, flight_id):
    flight = store.flights.get(flight_id)
    if flight is None:
        return
    flight["loaded_bag_count"] = calc.flight_loaded_bag_count(store, flight_id)
    flight["makeup_ready"] = calc.flight_makeup_ready(store, flight_id)
    flight["updated_at"] = iso(store.now())
    flight["version"] = flight.get("version", 0) + 1


def recompute_bag_derived(store, bag):
    """Refresh every derived bag field; bumps the row's version."""
    bag["linear_in"] = (bag.get("length_in") or 0) + (bag.get("width_in") or 0) + (bag.get("height_in") or 0)
    bag["duplicate_flag"] = calc.duplicate_flag(store, bag)
    bag["rush_declared"] = calc.rush_declared(store, bag)
    bag["priority_score"] = calc.priority_score(store, bag)
    bag["manual_sortation_delay_minutes"] = calc.manual_sortation_delay(store, bag)
    bag["screen_alarm_resolution_time_minutes"] = calc.screen_alarm_resolution_time(store, bag)
    touch(store, bag)


def recompute_report_money(store, report):
    report["compensation_offer_cents"] = calc.compensation_offer(store, report)
    report["final_liability_cents"] = calc.final_liability(store, report)


def recompute_after_bag_write(store, bag, flight=True, area=True, station=True):
    """Refresh the aggregates a custody write ripples into."""
    if area and bag.get("makeup_area_id"):
        recompute_area(store, bag["makeup_area_id"])
    if flight and bag.get("flight_id"):
        recompute_flight(store, bag["flight_id"])
    if station and bag.get("station_id"):
        recompute_station(store, bag["station_id"])


def recompute_after_task_write(store, task, face_bag=None):
    bag = face_bag or bag_for_task(store, task)
    if bag is not None:
        bag["priority_score"] = calc.priority_score(store, bag)
        touch(store, bag)
        if bag.get("flight_id"):
            recompute_flight(store, bag["flight_id"])
    if task.get("station_id"):
        recompute_station(store, task["station_id"])


# ----------------------------------------------------------------- lookups --
def bag_for_task(store, task):
    event = store.screenings.get(task.get("screening_event_id"))
    if event is None:
        return None
    return store.bags.get(event.get("bag_id"))


def latest_screening_event(store, bag_id):
    events = calc.screenings_of(store, bag_id)
    if not events:
        return None
    events.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)))
    return events[-1]


def open_task_for_bag(store, bag_id):
    for task in calc.tasks_of_bag(store, bag_id):
        if task["status"] in ("QUEUED", "IN_PROGRESS"):
            return task
    return None


# --------------------------------------------------------- cascade helpers --
def ensure_delivery(store, bag, status="PENDING", method="PASSENGER_PICKUP"):
    """A bag reaching HELD or OFFLOADED without a delivery row gets one."""
    existing = calc.delivery_of(store, bag["id"])
    if existing is not None:
        return existing
    from db import new_row
    row = new_row(store, {
        "bag_id": bag["id"],
        "mishandled_report_id": None,
        "method": method,
        "address_note": None,
        "scheduled_utc": None,
        "status": status,
        "delivered_utc": None,
        "courier_ref": None,
        "proof_required": False,
    })
    return store.add("deliveries", row)


def append_scan(store, bag, scan_point, forced_manual=False):
    from db import new_row
    station = calc.station_of(store, bag)
    outage = bool(station and station.get("outage_active"))
    source = "MANUAL" if (outage or forced_manual) else "AUTOMATED"
    row = new_row(store, {
        "bag_id": bag["id"],
        "scan_point": scan_point,
        "scan_source": source,
        "scan_utc": iso(store.now()),
        "result": "OK",
        "_outage_manual": bool(outage and source == "MANUAL"),
    })
    store.add("scans", row)
    return row


def special_item_safeguard(store, bag):
    """cascade C: a manual-screening special item without an open task gains one."""
    if bag.get("flight_id") is None:
        pass
    items = calc.special_items_of(store, bag["id"])
    if not any(i["requires_manual_screening"] for i in items):
        return None
    event = latest_screening_event(store, bag["id"])
    if event is None:
        return None
    existing = [t for t in store.inspections.values()
                if t["screening_event_id"] == event["id"] and t["status"] in ("QUEUED", "IN_PROGRESS")]
    if existing:
        return None
    station_id = bag["station_id"]
    depth = calc.manual_queue_depth(store, station_id)
    from db import new_row
    row = new_row(store, {
        "screening_event_id": event["id"],
        "station_id": station_id,
        "queue_position": depth + 1,
        "status": "QUEUED",
        "assigned_to": None,
        "due_utc": iso(store.now() + timedelta(minutes=30)),
        "resolution": None,
    })
    store.add("inspections", row)
    return row


def restamp_overdue_tasks(store, station_id):
    """Fired when a make-up area reaches exactly zero free slots."""
    now = store.now()
    for task in store.inspections.values():
        if task["station_id"] != station_id or task["status"] != "QUEUED":
            continue
        due = task.get("due_utc")
        if due and parse_iso(due) <= now:
            task["queue_position"] = 0
            task["priority_flag"] = True
            touch(store, task)