"""Business logic: derived fields, zone recompute, blackout, timers, clocks."""
import math
import uuid
from datetime import datetime, timezone, timedelta

import db
from util import now_ts, zip_miles, bump


# ---------------------------------------------------------------- clock rules

def hold_minutes(entry):
    return 25 if entry.get("kickoff_override") else 15


def blackout_active_for(event, venue):
    """Whether the blackout window is currently active for an event at a venue.

    Active when: now within [start-30m, end+60m], kind != PPV, venue within
    radius, and league license ACTIVE.
    """
    if event.get("kind") == "PPV":
        return False
    lic = find_license(venue["id"], event["league"])
    if lic is None or lic["status"] != "ACTIVE":
        return False
    radius = lic.get("blackout_radius_miles")
    if radius is None and event["league"] == "NCAA":
        radius = 75
    if radius is None:
        return False
    if zip_miles(venue["market_zip"], event["home_market_zip"]) > radius:
        return False
    now = db.now()
    return (event["scheduled_start"] - timedelta(minutes=30)) <= now <= \
           (event["scheduled_end"] + timedelta(minutes=60))


def find_license(venue_id, league):
    for lic in db.licenses.values():
        if lic["venue_id"] == venue_id and lic["league"] == league:
            return lic
    return None


# ---------------------------------------------------------------- zone recompute

def zone_assignments(zone_id):
    return [a for a in db.screen_assignments.values() if a["zone_id"] == zone_id]


def recompute_zone(zone):
    """Recompute primary_event_id and posture. Applies blackout teardown and
    FULL->OPEN / OPEN->FULL transitions. Returns nothing; mutates zone."""
    venue = db.venues[zone["venue_id"]]
    assignments = zone_assignments(zone["id"])

    # Blackout check first: if any shown event (assigned, INGESTED) has an
    # active blackout window at this venue, the zone locks and assignments
    # for the blacked-out event are removed.
    locked_event = None
    for a in assignments:
        ev = db.events.get(a["event_id"])
        if ev is not None and ev["status"] == "INGESTED" and \
                blackout_active_for(ev, venue):
            locked_event = ev
            break

    if locked_event is not None:
        # Remove assignments for the blacked-out event
        for a in list(zone_assignments(zone["id"])):
            if a["event_id"] == locked_event["id"]:
                del db.screen_assignments[a["id"]]
        assignments = zone_assignments(zone["id"])

    # Primary event selection among remaining candidates
    candidates = []
    for a in assignments:
        ev = db.events.get(a["event_id"])
        if ev is not None and ev["status"] == "INGESTED":
            candidates.append((ev, a))
    if not candidates:
        primary = None
    else:
        candidates.sort(key=lambda ea: (-ea[0]["expected_attendance"],
                                        ea[0]["scheduled_start"],
                                        ea[1]["created_at"]))
        primary = candidates[0][0]
    new_primary_id = primary["id"] if primary else None

    if locked_event is not None:
        new_posture = "BLACKOUT_LOCKED"
        zone["_blackout_event_id"] = locked_event["id"]
    elif primary is None:
        new_posture = "OPEN"
        zone.pop("_blackout_event_id", None)
    elif primary["expected_attendance"] >= venue["capacity_seats"]:
        new_posture = "FULL"
        zone.pop("_blackout_event_id", None)
    else:
        new_posture = "OPEN"
        zone.pop("_blackout_event_id", None)

    if zone.get("primary_event_id") != new_primary_id or \
            zone.get("posture") != new_posture:
        zone["primary_event_id"] = new_primary_id
        zone["posture"] = new_posture
        bump(zone)


def recompute_all_zones():
    for zone in list(db.zones.values()):
        recompute_zone(zone)


# ---------------------------------------------------------------- waitlist timers

def process_waitlist_timers():
    """Expire called entries whose hold has elapsed."""
    now = db.now()
    for entry in list(db.waitlist_entries.values()):
        if entry["status"] == "CALLED" and entry.get("called_at") is not None:
            deadline = entry["called_at"] + timedelta(minutes=hold_minutes(entry))
            if now > deadline:
                entry["status"] = "EXPIRED"
                bump(entry)
                guest = db.guests.get(entry["guest_id"])
                if guest is not None:
                    guest["no_show_count"] += 1
                    bump(guest)


def on_clock_change():
    process_waitlist_timers()
    recompute_all_zones()


# ---------------------------------------------------------------- venues

def volatility_score(wing_cost_cents_per_lb):
    return abs(wing_cost_cents_per_lb - 180) / 180


# ---------------------------------------------------------------- checks/pricing

def pieces_for_guest_last_30d(guest_id, venue_id, as_of):
    """Sum pieces ordered by guest at venue on settled checks in prior 30 days."""
    cutoff = as_of - timedelta(days=30)
    total = 0
    for check in db.checks.values():
        if check["guest_id"] != guest_id or check["venue_id"] != venue_id:
            continue
        if check["status"] != "SETTLED":
            continue
        settled_dt = check.get("_settled_at")
        if settled_dt is None or settled_dt < cutoff or settled_dt > as_of:
            continue
        for line in db.order_lines.values():
            if line["check_id"] == check["id"] and line["status"] != "VOID":
                total += line["portion_count"] * 10
    return total


def find_promo(wing_kind, event_date):
    """Find a promo rule matching wing_kind, weekday of event_date, and date range."""
    for rule in db.promo_rules.values():
        if rule["wing_kind"] != wing_kind:
            continue
        if rule["day_of_week"] != event_date.weekday():
            continue
        if rule["start_date"].date() <= event_date.date() <= rule["end_date"].date():
            return rule
    return None


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_pricing(check, kind, portion_count):
    """Compute unit_price_cents and line_total_cents for a new order line."""
    from decimal import Decimal, ROUND_HALF_UP
    venue = db.venues[check["venue_id"]]
    now = db.now()
    promo = find_promo(kind, now)
    if promo is not None:
        base_unit = Decimal(promo["promo_price_cents_per_10"]) / Decimal(10)
    else:
        base_unit = Decimal(150)

    pieces = portion_count * 10
    tier_mult = Decimal("0.95") if pieces >= 50 else Decimal("1.0")

    last_30d = pieces_for_guest_last_30d(check["guest_id"], check["venue_id"], now)
    surcharge = Decimal("1.10") if last_30d > 5000 else Decimal("1.0")

    unit = (base_unit * surcharge).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    line_total = (unit * pieces * tier_mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(unit), int(line_total)


def recompute_check_subtotal(check):
    total = 0
    for line in db.order_lines.values():
        if line["check_id"] == check["id"] and line["status"] != "VOID":
            total += line["line_total_cents"]
    if check["subtotal_cents"] != total:
        check["subtotal_cents"] = total
        bump(check)


def cover_charge(check):
    if check["kind"] != "PPV":
        return 0
    for ppv in db.ppv_events.values():
        if ppv["event_id"] == check.get("event_id") and ppv["venue_id"] == check["venue_id"]:
            return check["guest_count"] * ppv["cover_charge_cents"]
    return 0


def guest_count_total_for_event(venue_id, event_id):
    total = 0
    for check in db.checks.values():
        if check["venue_id"] == venue_id and check.get("event_id") == event_id and \
                check["kind"] == "PPV" and check["status"] != "VOIDED":
            total += check["guest_count"]
    return total


def recompute_ppv_posture(venue_id, event_id):
    for ppv in db.ppv_events.values():
        if ppv["venue_id"] == venue_id and ppv["event_id"] == event_id:
            total_guests = guest_count_total_for_event(venue_id, event_id)
            posture = int(total_guests * (ppv["commercial_fee_cents"] * 1.20 +
                                          ppv["cover_charge_cents"]))
            if ppv["capacity_posture_cents"] != posture:
                ppv["capacity_posture_cents"] = posture
                bump(ppv)


# ---------------------------------------------------------------- staffing

def recompute_staffing(plan):
    foh = 0
    boh = 0
    for shift in db.shifts.values():
        if shift["plan_id"] != plan["id"]:
            continue
        covers_x04 = shift["expected_covers"] * 4  # expected_covers * 0.4 * 10
        foh += math.ceil((shift["expected_covers"] * 0.4) / 60)
        boh += math.ceil((shift["expected_covers"] * 0.4) / 100)
    if plan["foh_required"] != foh or plan["boh_required"] != boh:
        plan["foh_required"] = foh
        plan["boh_required"] = boh
        bump(plan)


# ---------------------------------------------------------------- ids

def new_id():
    return str(uuid.uuid4())
