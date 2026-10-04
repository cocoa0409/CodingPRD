"""Shared lookups, serialisers and the occupancy-unit ledger."""

from datetime import timedelta

import db as _db
import errors
from db import (
    CLOCK_STARTUP_ISO,
    HOLD_EXPIRY_ISO,
    date_from_service_date,
    iso_from_dt,
    parse_iso,
    round_half_up,
    service_date_of,
)

# PRD section 3.6 / scaffold calculation constants.
LIFEGUARD_MAX_CONSECUTIVE_MINUTES = 120
LIFEGUARD_DAILY_SHIFT_CAP = 3
LIFEGUARD_ROTATION_BUFFER_MINUTES = 30

# PRD section 3.5.
DAY_PASS_BASE_CENTS = 4200
DAY_PASS_VOLUME_THRESHOLD_UNITS = 10
DAY_PASS_VOLUME_BLOCK_UNITS = 10
DAY_PASS_VOLUME_BLOCK_CENTS = 1000

# PRD section 3.9.
ACTIVITY_TIER_UNIT_MULTIPLIER = {"STANDARD": 1, "PREMIUM": 2, "VIP": 3}
ACTIVITY_BULK_DISCOUNT_CENTS = 500
ACTIVITY_REFUND_RATE = 0.375
OPT_IN_RATIO_THRESHOLD = 0.5

# PRD section 3.1.
ROOM_FEE_ACTUATION_CENTS = 1400

# PRD section 3.8.
GROUP_DEPOSIT_PER_MEMBER_CENTS = 500
BIRTHDAY_PARTY_MINIMUM_MEMBERS = 1

# PRD section 3.5.
SERVICE_DATE_HORIZON_DAYS = 365

KINDS = {
    "resort": "resorts",
    "room_type": "room_types",
    "reservation": "reservations",
    "day_pass": "day_passes",
    "wristband": "wristbands",
    "attraction": "attractions",
    "lifeguard_shift": "lifeguard_shifts",
    "water_quality_log": "water_quality_logs",
    "admission_event": "admission_events",
    "arcade_credit_grant": "arcade_credit_grants",
    "cabana": "cabanas",
    "cabana_booking": "cabana_bookings",
    "group_booking": "group_bookings",
    "group_member": "group_members",
    "activity_session": "activity_sessions",
    "activity_booking": "activity_bookings",
}

# Endpoints on a sub-resource must resolve the whole path left to right;
# an id that exists but belongs to a different property is not found.
PATH_SCOPE = {
    "room_type": "resort_id",
    "reservation": "resort_id",
    "day_pass": "resort_id",
    "wristband": "resort_id",
    "attraction": "resort_id",
    "lifeguard_shift": "resort_id",
    "water_quality_log": "resort_id",
    "admission_event": "resort_id",
    "cabana": "resort_id",
    "cabana_booking": "resort_id",
    "group_booking": "resort_id",
    "group_member": "group_booking_id",
    "activity_session": "resort_id",
    "activity_booking": "resort_id",
    "arcade_credit_grant": "via_wristband",
}


def table(kind):
    return getattr(_db.store(), KINDS[kind])


def get(kind, entity_id):
    return table(kind).get(entity_id)


def fetch(kind, entity_id, resort_id=None):
    """Resolve an identifier under a property, else ERR_NOT_FOUND."""
    entity = table(kind).get(entity_id)
    if entity is None:
        raise errors.not_found()
    if resort_id is not None:
        scope_field = PATH_SCOPE.get(kind)
        if scope_field == "resort_id" and entity.get("resort_id") != resort_id:
            raise errors.not_found()
        if scope_field == "group_booking_id":
            parent = get("group_booking", entity.get("group_booking_id"))
            if parent is None or parent.get("resort_id") != resort_id:
                raise errors.not_found()
        if scope_field == "via_wristband":
            band = get("wristband", entity.get("wristband_id"))
            if band is None or band.get("resort_id") != resort_id:
                raise errors.not_found()
    return entity


def get_resort(resort_id):
    return fetch("resort", resort_id)


def touch(entity, mutate=True):
    if "updated_at" in entity:
        entity["updated_at"] = _db.now_iso()
    if mutate and "version" in entity:
        entity["version"] += 1


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

def clock(resort_id):
    store = _db.store()
    if resort_id not in store.clocks:
        store.clocks[resort_id] = CLOCK_STARTUP_ISO
    return store.clocks[resort_id]


def current_utc(resort_id):
    return parse_iso(clock(resort_id))


def current_service_date(resort_id):
    return service_date_of(current_utc(resort_id))


def set_clock(resort_id, to_iso8601):
    store = _db.store()
    store.clocks[resort_id] = to_iso8601
    return parse_iso(to_iso8601)


# --------------------------------------------------------------------------
# Occupancy-unit ledger (PRD 2.5 / 3.2)
# --------------------------------------------------------------------------

def reservation_is_non_terminal(res):
    return res.get("booking_status") in ("RESERVED", "CHECKED_OUT")


def room_units_reserved(resort_id, service_date):
    """Sum of reserved_units across non-terminal reservations spanning the date."""
    total = 0
    rows = [
        r for r in _db.store().reservations.values()
        if r.get("resort_id") == resort_id and reservation_is_non_terminal(r)
        and r.get("arrival_date") is not None and r.get("departure_date") is not None
        and service_date >= r["arrival_date"] and service_date < r["departure_date"]
    ]
    rows.sort(key=lambda r: (r.get("created_at") or "",))
    for res in rows:
        total += res.get("reserved_units") or 0
    return total


def day_pass_units(d, resort_id=None):
    total = 0
    for dp in _db.store().day_passes.values():
        if resort_id is not None and dp.get("resort_id") != resort_id:
            continue
        if dp.get("service_date") == d and dp.get("day_pass_status") in ("RESERVED", "ADMITTED"):
            total += dp.get("units_requested") or 0
    return total


def day_pass_reserved_units(resort_id, service_date):
    return day_pass_units(service_date, resort_id)


def group_reserved_units(group_booking_id):
    group = get("group_booking", group_booking_id)
    if group is None:
        return 0
    if group.get("group_status") != "CONFIRMED":
        return 0
    total = 0
    for member in _db.store().group_members.values():
        if member.get("group_booking_id") == group_booking_id and member.get("checked_in"):
            total += member.get("member_units") or 0
    return total


def group_units(resort_id, service_date):
    total = 0
    for group in _db.store().group_bookings.values():
        if group.get("resort_id") != resort_id:
            continue
        if group.get("service_date") != service_date:
            continue
        total += group_reserved_units(group["id"])
    return total


def cabana_day_units(resort_id, service_date):
    total = 0
    for booking in _db.store().cabana_bookings.values():
        if booking.get("resort_id") != resort_id:
            continue
        if booking.get("service_date") == service_date and \
                booking.get("cabana_booking_status") in ("HELD", "BOOKED"):
            total += booking.get("member_units") or 0
    return total


def capacity_ledger(resort_id, service_date):
    resort = get_resort(resort_id)
    room = room_units_reserved(resort_id, service_date)
    passes = day_pass_reserved_units(resort_id, service_date)
    groups = group_units(resort_id, service_date)
    cabanas = cabana_day_units(resort_id, service_date)
    occupancy = room + passes + groups + cabanas
    return {
        "service_date": service_date,
        "room_units_reserved": room,
        "day_pass_reserved_units": passes,
        "group_reserved_units": groups,
        "cabana_day_units": cabanas,
        "occupancy_units": occupancy,
        "park_capacity_occupancy_units": resort["park_capacity_occupancy_units"],
        "day_pass_cap_units": resort["day_pass_cap_units"],
        "capacity_remaining_units": resort["park_capacity_occupancy_units"] - occupancy,
    }


def opt_in_denominator(resort_id):
    """Room + day-pass + group contributions over the current service date."""
    d = current_service_date(resort_id)
    return (
        room_units_reserved(resort_id, d)
        + day_pass_reserved_units(resort_id, d)
        + group_units(resort_id, d)
    )


# --------------------------------------------------------------------------
# Pool posture (PRD 3.7)
# --------------------------------------------------------------------------

def recompute_pool_posture(resort_id):
    resort = get_resort(resort_id)
    closed = False
    for log in _db.store().water_quality_logs.values():
        if log.get("resort_id") != resort_id:
            continue
        if log.get("log_status") == "FAIL" and log.get("superseded_at") is None:
            closed = True
            break
    resort["pool_posture"] = "CLOSED" if closed else "OPEN"
    return resort["pool_posture"]


def current_service_date_has_standing_fail(resort_id):
    d = current_service_date(resort_id)
    for log in _db.store().water_quality_logs.values():
        if log.get("resort_id") != resort_id:
            continue
        if log.get("log_status") != "FAIL" or log.get("superseded_at") is not None:
            continue
        sampled = parse_iso(log.get("sampled_at"))
        if sampled is not None and service_date_of(sampled) == d:
            return True
    return False


def standing_fail_for_attraction_on(resort_id, attraction_id, service_date):
    for log in _db.store().water_quality_logs.values():
        if log.get("resort_id") != resort_id:
            continue
        if log.get("attraction_id") != attraction_id:
            continue
        if log.get("log_status") != "FAIL" or log.get("superseded_at") is not None:
            continue
        sampled = parse_iso(log.get("sampled_at"))
        if sampled is not None and service_date_of(sampled) == service_date:
            return True
    return False


# --------------------------------------------------------------------------
# Attraction staffing (PRD 3.6)
# --------------------------------------------------------------------------

def roster_has_entry(resort_id, staffer_name, actor_role):
    resort = get_resort(resort_id)
    wanted = "%s:%s" % (actor_role, staffer_name)
    return wanted in (resort.get("managers") or [])


def roster_roles_for(resort_id, staffer_name):
    resort = get_resort(resort_id)
    prefix = ":" + str(staffer_name)
    roles = []
    for entry in resort.get("managers") or []:
        if isinstance(entry, str) and entry.endswith(prefix):
            roles.append(entry[: -len(prefix)])
    return roles


def staffer_is_rostered(resort_id, staffer_name):
    return len(roster_roles_for(resort_id, staffer_name)) > 0


def completed_today(resort_id, staffer_name, shift_date):
    count = 0
    for shift in _db.store().lifeguard_shifts.values():
        if shift.get("resort_id") != resort_id:
            continue
        if shift.get("staffer_name") != staffer_name:
            continue
        if shift.get("shift_date") != shift_date:
            continue
        if shift.get("shift_status") == "COMPLETED":
            count += 1
    return count


def staffer_exhausted(resort_id, name, shift_date):
    return completed_today(resort_id, name, shift_date) >= LIFEGUARD_DAILY_SHIFT_CAP


def staffer_count(resort_id, attraction_id, shift_date, pool_closed):
    if pool_closed:
        return 0
    count = 0
    for shift in _db.store().lifeguard_shifts.values():
        if shift.get("resort_id") != resort_id:
            continue
        if shift.get("attraction_id") != attraction_id:
            continue
        if shift.get("shift_status") not in ("ON_DUTY", "ROTATED"):
            continue
        if shift.get("shift_date") != shift_date:
            continue
        if staffer_is_rostered(resort_id, shift.get("staffer_name")):
            count += 1
    return count


def rostered_staffers(resort_id, shift_date):
    """Names the property's rotation roster carries.

    PRD 3.6: "A count of 0 makes it LIMITED when at least one rostered staffer
    for that date has not yet exhausted their daily cap, and CLOSED when every
    rostered staffer has."  The roster is the property's `managers` array, so a
    rostered staffer who has not yet reached the three-shift cap keeps an
    unstaffed attraction at LIMITED.
    """
    resort = get_resort(resort_id)
    names = set()
    for entry in resort.get("managers") or []:
        if isinstance(entry, str) and ":" in entry:
            names.add(entry.split(":", 1)[1])
    return names


def recompute_attraction_status(resort_id, attraction_id, shift_date=None):
    attraction = get("attraction", attraction_id)
    if attraction is None:
        return None
    if shift_date is None:
        shift_date = current_service_date(resort_id)
    pool_closed = standing_fail_for_attraction_on(
        resort_id, attraction_id, current_service_date(resort_id)
    )
    count = staffer_count(resort_id, attraction_id, shift_date, pool_closed)
    effective_min = 1 if attraction.get("min_occupancy_units") == 0 \
        else attraction.get("min_occupancy_units")
    if pool_closed:
        # A standing FAIL closes the body of water outright: coverage that
        # cannot be delivered is not coverage (PRD 3.7).
        status = "CLOSED"
    elif count >= effective_min:
        status = "OPEN"
    elif count >= 1:
        status = "LIMITED"
    else:
        names = rostered_staffers(resort_id, shift_date)
        if any(not staffer_exhausted(resort_id, n, shift_date) for n in names):
            status = "LIMITED"
        else:
            status = "CLOSED"
    attraction["attraction_status"] = status
    return status


def attraction_is_open(attraction):
    return attraction.get("attraction_status") == "OPEN"


def attraction_has_min_staff(resort_id, attraction):
    """Attraction readiness for gate admission and session creation.

    PRD 3.6 derives `attraction_status` from staffing coverage; the readiness
    check therefore reads the status rather than re-deriving a floor, so an
    attraction that is merely short of a floor above 1 is LIMITED (and blocks)
    while an unstaffed-but-unexhausted one is LIMITED as well.  Only an
    attraction whose derived status is OPEN is ready.
    """
    return attraction_is_open(attraction)


def recompute_attractions_for_resort(resort_id):
    for attraction in list(_db.store().attractions.values()):
        if attraction.get("resort_id") == resort_id:
            recompute_attraction_status(resort_id, attraction["id"])


# --------------------------------------------------------------------------
# Serialisers (server-managed fields are the only additions)
# --------------------------------------------------------------------------

# Bookkeeping fields the platform keeps for itself and never publishes.
_HIDDEN_FIELDS = ("_persisted",)


def serialise(kind, entity):
    if entity is None:
        return None
    out = dict(entity)
    for field in _HIDDEN_FIELDS:
        out.pop(field, None)
    if kind == "group_member":
        group = get("group_booking", entity.get("group_booking_id"))
        out["resort_id"] = group.get("resort_id") if group else None
    return out


def serialise_many(kind, entities):
    return [serialise(kind, e) for e in entities]


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset: offset + limit]
    return window, total


def created_at_sort(entities):
    return sorted(entities, key=lambda e: (e.get("created_at") or "",))