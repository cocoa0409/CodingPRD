"""Lock chambers and lockage reservations."""
from flask import Blueprint

import calc
from common import (ALL_ROLES, ApiError, apply_filters, authenticate, caller_id,
                    caller_role, created, dec, f_dt, f_enum, f_int, f_num,
                    f_str, fetch, floor_int, get_body, make_record, ok,
                    paged_response, pagination, sorted_rows, store, touch)
from schema import ser_lock, ser_reservation

bp = Blueprint("lock", __name__)

LOCK_STATUSES = ["OPEN", "RESTRICTED", "CLOSED"]
PRIORITY_CLASSES = ["PRIORITY", "COMMERCIAL", "RECREATIONAL"]


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------
@bp.post("/locks")
def create_lock():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    rec = make_record({
        "lock_name": f_str(body, "lock_name"),
        "river_mile": f_num(body, "river_mile"),
        "chamber_capacity_barges": f_int(body, "chamber_capacity_barges", gt=0),
        "cycle_minutes": f_int(body, "cycle_minutes", gt=0),
        "turnback_buffer_minutes": f_int(body, "turnback_buffer_minutes", ge=0),
        "status": "OPEN",
        "granted_reservation_count": 0,
    })
    store.locks[rec["id"]] = rec
    return created(ser_lock(rec))


@bp.post("/locks/<lock_id>/set-status")
def set_lock_status(lock_id):
    authenticate(["LockMaster", "WaterwayAdmin"])
    body = get_body()
    new_status = f_enum(body, "status", LOCK_STATUSES)
    lock = fetch(store.locks, lock_id, "ERR_LOCK_NOT_FOUND")
    # priority 7 - a LockMaster may only reposture its own chamber
    if caller_role() == "LockMaster" and caller_id() != lock["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    was_closed = lock["status"] == "CLOSED"
    lock["status"] = new_status
    touch(lock)
    if new_status == "CLOSED" and not was_closed:
        _close_chamber(lock)
    return ok(ser_lock(lock))


def _close_chamber(lock):
    """Closing cancels every live reservation and charges each affected tow the
    flat closure delay, cascading exactly as a cleared lockage would."""
    live = [r for r in store.lock_reservations.values()
            if r["lock_id"] == lock["id"] and r["status"] in ("REQUESTED", "GRANTED")]
    live.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for res in live:
        was_granted = res["status"] == "GRANTED"
        res["status"] = "CANCELLED"
        touch(res)
        if was_granted:
            lock["granted_reservation_count"] = max(
                0, lock["granted_reservation_count"] - 1)
            touch(lock)
        tow = store.tows.get(res["tow_id"])
        if tow is not None:
            tow["pending_lock_reservation_count"] = max(
                0, tow["pending_lock_reservation_count"] - 1)
            calc.attribute_delay(tow, calc.LOCK_CLOSURE_DELAY_MINUTES)


@bp.get("/locks/<lock_id>")
def get_lock(lock_id):
    authenticate(ALL_ROLES)
    return ok(ser_lock(fetch(store.locks, lock_id, "ERR_LOCK_NOT_FOUND")))


@bp.get("/locks")
def list_locks():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.locks), [("status", "status")])
    return paged_response(rows, ser_lock, limit, offset)


# ---------------------------------------------------------------------------
# Lock reservations
# ---------------------------------------------------------------------------
@bp.post("/lock-reservations")
def request_reservation():
    authenticate(["TowboatDispatcher"])
    body = get_body()
    lock_id = f_str(body, "lock_id")
    tow_id = f_str(body, "tow_id")
    requested_start_at = f_dt(body, "requested_start_at")
    expected_tow_version = f_int(body, "expected_tow_version")
    priority_class = f_enum(body, "priority_class", PRIORITY_CLASSES,
                            required=False, default="COMMERCIAL")
    lock = fetch(store.locks, lock_id, "ERR_LOCK_NOT_FOUND")
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    # priority 10 - optimistic concurrency on the parent tow
    if expected_tow_version != tow["version"]:
        raise ApiError("ERR_STALE_TOW_VERSION")
    cuts, start_at, end_at, occupied = calc.window_for(tow, lock, requested_start_at)
    # priority 20 sits above priority 24 on the rejection ladder
    if calc.window_conflicts(lock_id, start_at, occupied):
        raise ApiError("ERR_LOCK_WINDOW_CONFLICT")
    if lock["status"] == "CLOSED":
        raise ApiError("ERR_LOCK_CLOSED")
    rec = make_record({
        "lock_id": lock_id,
        "tow_id": tow_id,
        "requested_start_at": requested_start_at,
        "cut_count": cuts,
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "occupied_until_at": occupied,
        "actual_start_at": None,
        "actual_end_at": None,
        "delay_minutes": 0,
        "priority_class": priority_class,
        "status": "REQUESTED",
    })
    store.lock_reservations[rec["id"]] = rec
    tow["pending_lock_reservation_count"] += 1
    touch(tow)
    return created(ser_reservation(rec))


def _owned_reservation(reservation_id):
    res = fetch(store.lock_reservations, reservation_id,
                "ERR_LOCK_RESERVATION_NOT_FOUND")
    if caller_id() != res["lock_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return res


@bp.post("/lock-reservations/<lock_reservation_id>/grant")
def grant_reservation(lock_reservation_id):
    authenticate(["LockMaster"])
    res = _owned_reservation(lock_reservation_id)
    if res["status"] != "REQUESTED":
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    tow = store.tows.get(res["tow_id"])
    if tow is not None and tow["status"] not in ("BUILDING", "SEALED", "UNDERWAY",
                                                 "DELAYED"):
        raise ApiError("ERR_TOW_INVALID_STATE")
    if calc.window_conflicts(res["lock_id"], res["scheduled_start_at"],
                             res["occupied_until_at"], exclude_id=res["id"]):
        raise ApiError("ERR_LOCK_WINDOW_CONFLICT")
    lock = store.locks.get(res["lock_id"])
    if lock is not None and lock["status"] == "CLOSED":
        raise ApiError("ERR_LOCK_CLOSED")
    res["status"] = "GRANTED"
    touch(res)
    if lock is not None:
        lock["granted_reservation_count"] += 1
        touch(lock)
    return ok(ser_reservation(res))


@bp.post("/lock-reservations/<lock_reservation_id>/deny")
def deny_reservation(lock_reservation_id):
    authenticate(["LockMaster"])
    body = get_body()
    reason = f_str(body, "reason", required=False)
    res = _owned_reservation(lock_reservation_id)
    if res["status"] != "REQUESTED":
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    res["status"] = "DENIED"
    if reason is not None:
        res["reason"] = reason
    touch(res)
    tow = store.tows.get(res["tow_id"])
    if tow is not None:
        tow["pending_lock_reservation_count"] = max(
            0, tow["pending_lock_reservation_count"] - 1)
        touch(tow)
    return ok(ser_reservation(res))


@bp.post("/lock-reservations/<lock_reservation_id>/reschedule")
def reschedule_reservation(lock_reservation_id):
    authenticate(["LockMaster"])
    body = get_body()
    requested_start_at = f_dt(body, "requested_start_at")
    res = _owned_reservation(lock_reservation_id)
    if res["status"] != "GRANTED":
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    lock = store.locks.get(res["lock_id"])
    tow = store.tows.get(res["tow_id"])
    if lock is not None and tow is not None:
        cuts, start_at, end_at, occupied = calc.window_for(tow, lock,
                                                           requested_start_at)
        res["cut_count"] = cuts
        res["scheduled_start_at"] = start_at
        res["scheduled_end_at"] = end_at
        res["occupied_until_at"] = occupied
    res["requested_start_at"] = requested_start_at
    res["status"] = "REQUESTED"
    touch(res)
    if lock is not None:
        lock["granted_reservation_count"] = max(
            0, lock["granted_reservation_count"] - 1)
        touch(lock)
    return ok(ser_reservation(res))


@bp.post("/lock-reservations/<lock_reservation_id>/enter-chamber")
def enter_chamber(lock_reservation_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    actual_start_at = f_dt(body, "actual_start_at")
    res = fetch(store.lock_reservations, lock_reservation_id,
                "ERR_LOCK_RESERVATION_NOT_FOUND")
    if res["status"] != "GRANTED":
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    tow = store.tows.get(res["tow_id"])
    if tow is not None and tow["status"] not in ("UNDERWAY", "DELAYED"):
        raise ApiError("ERR_TOW_INVALID_STATE")
    lock = store.locks.get(res["lock_id"])
    if lock is not None and lock["status"] == "CLOSED":
        raise ApiError("ERR_LOCK_CLOSED")
    res["status"] = "IN_CHAMBER"
    res["actual_start_at"] = actual_start_at
    touch(res)
    return ok(ser_reservation(res))


@bp.post("/lock-reservations/<lock_reservation_id>/clear")
def clear_chamber(lock_reservation_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    actual_end_at = f_dt(body, "actual_end_at")
    res = fetch(store.lock_reservations, lock_reservation_id,
                "ERR_LOCK_RESERVATION_NOT_FOUND")
    if res["status"] != "IN_CHAMBER":
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    if res["actual_start_at"] is not None and actual_end_at < res["actual_start_at"]:
        raise ApiError("ERR_UNLOAD_SEQUENCE_INVALID")
    res["status"] = "CLEARED"
    res["actual_end_at"] = actual_end_at
    raw = dec((actual_end_at - res["scheduled_end_at"]).total_seconds()) / 60
    res["delay_minutes"] = max(0, floor_int(raw))
    touch(res)
    lock = store.locks.get(res["lock_id"])
    if lock is not None:
        lock["granted_reservation_count"] = max(
            0, lock["granted_reservation_count"] - 1)
        touch(lock)
    tow = store.tows.get(res["tow_id"])
    if tow is not None:
        tow["pending_lock_reservation_count"] = max(
            0, tow["pending_lock_reservation_count"] - 1)
        calc.attribute_delay(tow, res["delay_minutes"])
    return ok(ser_reservation(res))


@bp.post("/lock-reservations/<lock_reservation_id>/cancel")
def cancel_reservation(lock_reservation_id):
    authenticate(["TowboatDispatcher"])
    res = fetch(store.lock_reservations, lock_reservation_id,
                "ERR_LOCK_RESERVATION_NOT_FOUND")
    if res["status"] not in ("REQUESTED", "GRANTED"):
        raise ApiError("ERR_LOCK_RESERVATION_INVALID_STATE")
    was_granted = res["status"] == "GRANTED"
    res["status"] = "CANCELLED"
    touch(res)
    if was_granted:
        lock = store.locks.get(res["lock_id"])
        if lock is not None:
            lock["granted_reservation_count"] = max(
                0, lock["granted_reservation_count"] - 1)
            touch(lock)
    tow = store.tows.get(res["tow_id"])
    if tow is not None:
        tow["pending_lock_reservation_count"] = max(
            0, tow["pending_lock_reservation_count"] - 1)
        touch(tow)
    return ok(ser_reservation(res))


@bp.get("/lock-reservations/<lock_reservation_id>")
def get_reservation(lock_reservation_id):
    authenticate(ALL_ROLES)
    return ok(ser_reservation(fetch(store.lock_reservations, lock_reservation_id,
                                    "ERR_LOCK_RESERVATION_NOT_FOUND")))


@bp.get("/lock-reservations")
def list_reservations():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.lock_reservations),
                         [("lock_id", "lock_id"), ("tow_id", "tow_id"),
                          ("status", "status")])
    return paged_response(rows, ser_reservation, limit, offset)
