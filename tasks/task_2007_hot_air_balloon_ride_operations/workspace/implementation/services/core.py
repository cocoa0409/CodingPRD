"""Core record lifecycle, computed fields, and serializers (PRD 2.4, 2.6, 2.10)."""
from datetime import timedelta
from decimal import Decimal

from db import db, next_seq
from util import new_id, now_ts, parse_date, CLOCK, rhu1

# Booking statuses that consume seats (Flight.seats_sold, PRD 3.4)
SEAT_STATUSES = {"PENDING", "CONFIRMED", "CHECKED_IN", "FLOWN", "COMPLETED"}
# Booking statuses whose passenger weights count toward payload (PRD 3.5)
PAYLOAD_STATUSES = {"CHECKED_IN", "FLOWN", "COMPLETED"}
# Flight states that pin the balloon / pilot for schedule-conflict checks
ACTIVE_FLIGHT_STATES = {"SCHEDULED", "WEATHER_REVIEW", "CLEARED_FOR_LAUNCH", "AIRBORNE"}


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.4/2.8)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def strip_internal(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Flight computed fields (PRD 3.2/3.4/3.5)
# ---------------------------------------------------------------------------

def season_tier_for(scheduled_date_str: str) -> str:
    """PEAK when scheduled_date falls within October 1-14, else REGULAR."""
    d = parse_date(scheduled_date_str)
    return "PEAK" if d.month == 10 and 1 <= d.day <= 14 else "REGULAR"


def flight_reservations(flight_id):
    return [r for r in db["reservations"].values() if r["flight_id"] == flight_id]


def flight_seats_sold(flight_id) -> int:
    return sum(
        r["party_size"]
        for r in flight_reservations(flight_id)
        if r["booking_status"] in SEAT_STATUSES
    )


def flight_payload_used(flight) -> int:
    balloon = db["balloons"].get(flight["balloon_id"])
    empty = balloon["empty_weight_lbs"] if balloon else 0
    passenger_lbs = 0
    for p in db["passengers"].values():
        r = db["reservations"].get(p["reservation_id"])
        if r is None or r["flight_id"] != flight["id"]:
            continue
        if r["booking_status"] in PAYLOAD_STATUSES:
            passenger_lbs += p["weight_lbs"]
    return empty + flight["fuel_lbs"] + passenger_lbs


def public_flight(f):
    out = strip_internal(f)
    out["season_tier"] = season_tier_for(f["scheduled_date"])
    balloon = db["balloons"].get(f["balloon_id"])
    cap = balloon["basket_capacity_passengers"] if balloon else 0
    sold = flight_seats_sold(f["id"])
    out["seats_sold"] = sold
    out["seats_available"] = cap - sold
    out["payload_used_lbs"] = flight_payload_used(f)
    return out


# ---------------------------------------------------------------------------
# Pilot currency (PRD 2.10): recomputed on read, at PUBLISH, and at CLOSE.
# Internal figures come from this operator's CLOSED flights whose
# scheduled_date falls inside the trailing 180-day (hours) / 90-day
# (takeoffs/landings) windows relative to the logical clock's current date.
# ---------------------------------------------------------------------------

def compute_currency(pilot) -> dict:
    today = CLOCK.today()
    h180 = Decimal(0)
    t90 = 0
    for f in db["flights"].values():
        if f["pilot_id"] != pilot["id"] or f["status"] != "CLOSED":
            continue
        d = parse_date(f["scheduled_date"])
        if today - timedelta(days=180) <= d <= today:
            if f.get("duration_hours") is not None:
                h180 += Decimal(str(f["duration_hours"]))
        if today - timedelta(days=90) <= d <= today:
            t90 += 1
    internal_hours = rhu1(h180)
    total_hours = rhu1(Decimal(str(pilot["external_pic_hours_180d"])) + h180)
    total_t = int(pilot["external_takeoffs_landings_90d"]) + t90
    faa_met = total_t >= 3
    operator_met = total_hours >= Decimal("12.0")
    return {
        "internal_pic_hours_180d": float(internal_hours),
        "internal_takeoffs_landings_90d": t90,
        "pic_hours_180d_total": float(total_hours),
        "takeoffs_landings_90d_total": total_t,
        "faa_currency_met": faa_met,
        "operator_currency_met": operator_met,
        "currency_status": "CURRENT" if (faa_met and operator_met) else "EXPIRED",
    }


def public_pilot(p):
    out = strip_internal(p)
    out.update(compute_currency(p))
    return out


# ---------------------------------------------------------------------------
# Other serializers
# ---------------------------------------------------------------------------

def public_launch_site(s):
    return strip_internal(s)


def public_balloon(b):
    return strip_internal(b)


def public_customer(c):
    return strip_internal(c)


def public_reservation(r):
    out = strip_internal(r)
    out["retained_revenue_cents"] = r["paid_cents"] - r["refunded_cents"]
    return out


def public_passenger(p):
    return strip_internal(p)


def public_briefing(w):
    return strip_internal(w)


def public_chase(a):
    return strip_internal(a)


def public_refund(rf):
    return strip_internal(rf)


def public_photo(pp):
    return strip_internal(pp)


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
