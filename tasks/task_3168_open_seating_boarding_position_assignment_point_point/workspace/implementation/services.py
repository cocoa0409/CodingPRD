"""Business logic: boarding assignment, upgrades, credits, propagation."""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import db
from errors import ApiError
from utils import iso_out, new_row, now_iso, parse_dt, touch

# ---- constants (SCAFFOLD calculations) ----
A1_A15_POOL = 15
GROUP_CAPACITY = 60
RETIME_THRESHOLD_MINUTES = 45
BASE_UB_PRICE_CENTS = 4000
BASE_EB_PRICE_CENTS = 1500
AL_DISCOUNT_PCT = 10
ALP_DISCOUNT_PCT = 25
BAG_FEE_CENTS = 7500
MAX_BAGS_PER_JOURNEY = 10
TURN_BASE_MINUTES = 12
BAG_MINUTES_PER_BAG = 1
SECONDS_PER_PAX = 18
DELAY_RISK_BUFFER_MINUTES = 5
REQUIRED_STAFF_UNITS = 5
HIGH_LOAD_FACTOR = Decimal("0.90")
BAGS_PER_RAMP_AGENT_MAX = Decimal("15")
PROPAGATION_DEPTH_CAP = 3
DELAY_FLOOR_MINUTES = 15
MAX_CONNECTION_MINUTES = 120
MAX_DUTY_MINUTES = 840

GROUP_RANK = {"PREBOARD": 0, "A": 1, "FAMILY": 2, "B": 3, "C": 4}

TIER_PCT = {"NONE": 0, "A_LIST": AL_DISCOUNT_PCT, "A_LIST_PREFERRED": ALP_DISCOUNT_PCT}


def clock_now():
    return parse_dt(db.clock_iso)


def clock_now_iso():
    return db.clock_iso


def leg_service_date_str(leg):
    return leg["scheduled_departure_utc"][:10]


def get_journey(jid):
    return db.journeys.get(jid)


def get_leg(lid):
    return db.flight_legs.get(lid)


def get_passenger(pid):
    return db.passengers.get(pid)


def get_fare(fid):
    return db.fare_classes.get(fid)


def active_assignment_for_journey(journey_id):
    for a in db.boarding_assignments.values():
        if a["journey_id"] == journey_id and a["assignment_status"] == "ACTIVE":
            return a
    return None


def active_upgrades_for_journey(journey_id, upgrade_type=None):
    out = []
    for u in db.boarding_upgrades.values():
        if u["journey_id"] == journey_id and u["upgrade_status"] == "ACTIVE":
            if upgrade_type is None or u["upgrade_type"] == upgrade_type:
                out.append(u)
    return out


def active_ub_upgrades_on_leg(leg_id):
    out = []
    for u in db.boarding_upgrades.values():
        if u["upgrade_type"] != "UPGRADED_BOARDING" or u["upgrade_status"] != "ACTIVE":
            continue
        j = db.journeys.get(u["journey_id"])
        if j and j["flight_leg_id"] == leg_id and j["journey_status"] not in (
            "CANCELLED",
            "NO_SHOW",
        ):
            out.append(u)
    out.sort(key=lambda u: (u["created_at"], u["id"]))
    return out


def aircraft_for_leg(leg):
    """Find the aircraft assigned to this leg via an ACTIVE routing."""
    for r in db.aircraft_routings.values():
        if r["routing_status"] != "ACTIVE":
            continue
        if leg["id"] in r["leg_ids"]:
            return db.aircraft.get(r["aircraft_id"])
    return None


def upgrade_pool_cap(leg):
    ac = aircraft_for_leg(leg)
    seat_count = ac["seat_count"] if ac else leg.get("capacity_seats", 0)
    return min(A1_A15_POOL, seat_count)


def compute_upgrade_price(fare, passenger, upgrade_type):
    """Pinned multiplicative order: fare discount first (floor), then status (floor)."""
    fare_pct = fare.get("upgrade_discount_pct", 0)
    if upgrade_type == "EARLY_BIRD":
        return (BASE_EB_PRICE_CENTS * (100 - fare_pct)) // 100
    step1 = (BASE_UB_PRICE_CENTS * (100 - fare_pct)) // 100
    tier_pct = TIER_PCT.get(passenger.get("status_tier", "NONE"), 0)
    return (step1 * (100 - tier_pct)) // 100


def _family_pairs(journeys):
    """Return dict adult_journey_id -> child journey and set of pair member ids."""
    pairs = {}
    members = set()
    for j in journeys:
        anchor_id = j.get("family_anchor_journey_id")
        if anchor_id:
            child = db.journeys.get(anchor_id)
            if child and child in journeys:
                pairs[j["id"]] = child
                members.add(j["id"])
                members.add(child["id"])
    return pairs, members


def is_family_journey(journey):
    """PRD §3.4 Phase 5: journeys with accommodation FAMILY plus the
    child-and-adult pairs participating in the family accommodation board in
    group FAMILY — so the anchor (child) journey qualifies too."""
    if journey.get("accommodation") == "FAMILY":
        return True
    if journey.get("family_anchor_journey_id"):
        return True
    for other in db.journeys.values():
        if other.get("family_anchor_journey_id") == journey["id"]:
            return True
    return False


def _make_assignment(journey, leg, group, position, source):
    row = new_row()
    row.update(
        {
            "journey_id": journey["id"],
            "flight_leg_id": leg["id"],
            "boarding_group": group,
            "boarding_position": position,
            "assignment_source": source,
            "assignment_status": "ACTIVE",
            "release_reason": "NONE",
        }
    )
    db.boarding_assignments[row["id"]] = row
    return row


def assign_for_new_checkin(journey, leg):
    """Create a BoardingAssignment for a single newly checked-in journey."""
    jmap = db.journeys
    # gather current checked-in journeys on the leg
    ci = [
        j
        for j in jmap.values()
        if j["flight_leg_id"] == leg["id"] and j["journey_status"] == "CHECKED_IN"
    ]

    # accommodation
    if journey.get("accommodation") == "PREBOARD":
        n = sum(
            1
            for a in db.boarding_assignments.values()
            if a["flight_leg_id"] == leg["id"]
            and a["assignment_status"] == "ACTIVE"
            and a["boarding_group"] == "PREBOARD"
        )
        return _make_assignment(journey, leg, "PREBOARD", n + 1, "PREBOARD_ACCOMMODATION")

    pairs, _members = _family_pairs(ci)
    if is_family_journey(journey):
        # family positions continue after existing FAMILY rows
        n = sum(
            1
            for a in db.boarding_assignments.values()
            if a["flight_leg_id"] == leg["id"]
            and a["assignment_status"] == "ACTIVE"
            and a["boarding_group"] == "FAMILY"
        )
        if journey["id"] in pairs:
            # adult of a pair: place adjacent to child if child already placed
            child = pairs[journey["id"]]
            child_asg = active_assignment_for_journey(child["id"])
            if child_asg and child_asg["boarding_group"] == "FAMILY":
                return _make_assignment(
                    journey, leg, "FAMILY", child_asg["boarding_position"] + 1,
                    "FAMILY_ACCOMMODATION",
                )
        return _make_assignment(journey, leg, "FAMILY", n + 1, "FAMILY_ACCOMMODATION")

    # upgrade UB pool
    ub = active_upgrades_for_journey(journey["id"], "UPGRADED_BOARDING")
    if ub:
        u = ub[0]
        pos = u.get("position_granted")
        if pos is None:
            pos = _next_ub_position(leg)
            u["position_granted"] = pos
            touch(u)
        return _make_assignment(journey, leg, "A", pos, "UPGRADE_PURCHASE")

    # Phases 3-4 (status priority, then regular) are evaluated over the
    # leg's whole CHECKED_IN population — the PRD's declared input set — so a
    # later higher-priority check-in renumbers earlier regular rows in place.
    # Positions number after the full A1-A15 pool (PRD §3.4: "Positions in
    # group A continue numbering after the A1-A15 pool").
    return _assign_regular(journey, leg)


def _assign_regular(journey, leg):
    """Create the new journey's assignment, then re-run phases 3-4 over the
    leg's CHECKED_IN non-accommodation, non-UB population, renumbering the
    existing ACTIVE rows in place (no new rows, no status changes)."""
    tier = _tier(journey)
    source = ("STATUS_PRIORITY" if tier in ("A_LIST", "A_LIST_PREFERRED")
              else "CHECKIN_TIME")
    row = _make_assignment(journey, leg, "A", 0, source)
    _recompute_phases_3_4(leg)
    return row


def _recompute_phases_3_4(leg):
    pool = upgrade_pool_cap(leg)
    rows = []
    for a in db.boarding_assignments.values():
        if a["flight_leg_id"] != leg["id"] or a["assignment_status"] != "ACTIVE":
            continue
        if a["boarding_group"] in ("PREBOARD", "FAMILY"):
            continue
        if a["assignment_source"] in ("UPGRADE_PURCHASE", "RETIME"):
            continue  # phase 2 rows keep their granted positions
        j = db.journeys.get(a["journey_id"])
        if not j or j["journey_status"] != "CHECKED_IN":
            continue
        rows.append((a, j))
    alp = sorted(
        (r for r in rows if _tier(r[1]) == "A_LIST_PREFERRED"),
        key=lambda r: (r[1].get("checked_in_at") or "", r[1]["created_at"],
                       r[1]["_seq"]),
    )
    al = sorted(
        (r for r in rows if _tier(r[1]) == "A_LIST"),
        key=lambda r: (r[1].get("checked_in_at") or "", r[1]["created_at"],
                       r[1]["_seq"]),
    )
    regular = sorted(
        (r for r in rows if _tier(r[1]) not in ("A_LIST", "A_LIST_PREFERRED")),
        key=lambda r: (r[1].get("checked_in_at") or "", r[1]["created_at"],
                       r[1]["_seq"]),
    )
    a_pos = pool
    b_pos = 0
    c_pos = 0
    for a, j in alp + al + regular:
        if a_pos < GROUP_CAPACITY:
            a_pos += 1
            new_group, new_pos = "A", a_pos
        elif b_pos < GROUP_CAPACITY:
            b_pos += 1
            new_group, new_pos = "B", b_pos
        else:
            c_pos += 1
            new_group, new_pos = "C", c_pos
        if a["boarding_group"] != new_group or a["boarding_position"] != new_pos:
            a["boarding_group"] = new_group
            a["boarding_position"] = new_pos
            touch(a)


def _next_ub_position(leg):
    # PRD §3.5: "The freed A-position is **not** backfilled — later
    # purchasers do not slide up." The granted-position counter is monotone:
    # every UB assignment row ever issued on the leg — ACTIVE or released
    # (VOIDED/RETIMED) — permanently consumes its position.
    taken = set()
    for a in db.boarding_assignments.values():
        if (
            a["flight_leg_id"] == leg["id"]
            and a["boarding_group"] == "A"
            and a["assignment_source"] in ("UPGRADE_PURCHASE", "RETIME")
        ):
            taken.add(a["boarding_position"])
    cap = upgrade_pool_cap(leg)
    pos = 1
    while pos in taken:
        pos += 1
    if pos > cap:
        return None
    return pos


def grant_ub_position(leg, journey, upgrade):
    """Grant next A1-A15 position for an UPGRADED_BOARDING purchase."""
    pos = _next_ub_position(leg)
    if pos is None:
        raise ApiError("ERR_UPGRADE_SOLD_OUT", 409, "A1-A15 pool exhausted")
    upgrade["position_granted"] = pos
    # if journey already checked in, replace assignment
    if journey["journey_status"] == "CHECKED_IN":
        old = active_assignment_for_journey(journey["id"])
        if old:
            old["assignment_status"] = "VOIDED"
            old["release_reason"] = "UPGRADE"
            touch(old)
        _make_assignment(journey, leg, "A", pos, "UPGRADE_PURCHASE")
    return pos


def retime_recompute(leg):
    """When delay >= RETIME_THRESHOLD: recompute phases 2-4; accommodation rows frozen."""
    # collect non-accommodation ACTIVE assignments on this leg
    affected = []
    for a in db.boarding_assignments.values():
        if a["flight_leg_id"] != leg["id"] or a["assignment_status"] != "ACTIVE":
            continue
        if a["boarding_group"] in ("PREBOARD", "FAMILY"):
            continue
        j = db.journeys.get(a["journey_id"])
        if not j or j["journey_status"] != "CHECKED_IN":
            continue
        affected.append(a)
    if not affected:
        return
    # void old rows
    for a in affected:
        a["assignment_status"] = "RETIMED"
        a["release_reason"] = "DELAY_RETIME"
        touch(a)

    journeys = [db.journeys[a["journey_id"]] for a in affected]
    # Phase 2: UB pool in upgrade purchase order
    ub_upgrades = active_ub_upgrades_on_leg(leg["id"])
    ub_by_journey = {u["journey_id"]: u for u in ub_upgrades}
    upgraded = [j for j in journeys if j["id"] in ub_by_journey]
    upgraded.sort(key=lambda j: (ub_by_journey[j["id"]]["created_at"], ub_by_journey[j["id"]]["id"]))
    rest = [j for j in journeys if j["id"] not in ub_by_journey]
    for j in upgraded:
        u = ub_by_journey[j["id"]]
        pos = u.get("position_granted")
        if pos is None:
            pos = _next_ub_position(leg)
            u["position_granted"] = pos
            touch(u)
        _make_assignment(j, leg, "A", pos, "RETIME")

    # Phase 3: status priority
    alp = [j for j in rest if _tier(j) == "A_LIST_PREFERRED"]
    al = [j for j in rest if _tier(j) == "A_LIST"]
    regular = [j for j in rest if _tier(j) not in ("A_LIST", "A_LIST_PREFERRED")]
    key = lambda j: (j.get("checked_in_at") or "", j["created_at"])
    alp.sort(key=key)
    al.sort(key=key)
    regular.sort(key=key)

    a_used = set()
    for a in db.boarding_assignments.values():
        if (
            a["flight_leg_id"] == leg["id"]
            and a["assignment_status"] == "ACTIVE"
            and a["boarding_group"] == "A"
        ):
            a_used.add(a["boarding_position"])

    # Status-priority and regular positions number after the full A1-A15
    # pool (PRD §3.4), not merely after the positions currently taken.
    pos_counter = max(
        [upgrade_pool_cap(leg)] + [p for p in a_used if p > upgrade_pool_cap(leg)]
    )

    def alloc_a():
        nonlocal pos_counter
        pos_counter += 1
        return pos_counter

    b_count = sum(
        1
        for a in db.boarding_assignments.values()
        if a["flight_leg_id"] == leg["id"]
        and a["assignment_status"] == "ACTIVE"
        and a["boarding_group"] == "B"
    )
    c_count = sum(
        1
        for a in db.boarding_assignments.values()
        if a["flight_leg_id"] == leg["id"]
        and a["assignment_status"] == "ACTIVE"
        and a["boarding_group"] == "C"
    )

    for j in alp + al:
        p = alloc_a()
        _make_assignment(j, leg, "A", p, "RETIME")
    for j in regular:
        if pos_counter < GROUP_CAPACITY:
            p = alloc_a()
            _make_assignment(j, leg, "A", p, "RETIME")
        elif b_count < GROUP_CAPACITY:
            b_count += 1
            _make_assignment(j, leg, "B", b_count, "RETIME")
        else:
            c_count += 1
            _make_assignment(j, leg, "C", c_count, "RETIME")


def _tier(journey):
    p = get_passenger(journey["passenger_id"])
    return p["status_tier"] if p else "NONE"


def boarding_order_sort(a):
    j = db.journeys.get(a["journey_id"], {})
    return (
        GROUP_RANK.get(a["boarding_group"], 9),
        a["boarding_position"],
        j.get("checked_in_at") or "",
        j.get("created_at") or "",
    )


def mint_travel_credit(passenger_id, source_journey, amount_cents, fare, leg):
    """Mint a TravelCredit. amount already computed by caller (floored >=0)."""
    if amount_cents <= 0:
        return None
    service_date = parse_dt(leg["scheduled_departure_utc"]).date()
    expires = service_date + timedelta(days=fare.get("credit_validity_days", 365))
    row = new_row()
    row.update(
        {
            "passenger_id": passenger_id,
            "source_journey_id": source_journey["id"],
            "initial_amount_cents": amount_cents,
            "remaining_amount_cents": amount_cents,
            "expires_on": expires.isoformat(),
            "credit_status": "OPEN",
        }
    )
    db.travel_credits[row["id"]] = row
    return row


def void_journey_redemptions_compensate(journey):
    """Step 1 of travel_credit_mint: void ACTIVE redemptions paying this journey,
    restoring each source credit's balance."""
    for r in db.credit_redemptions.values():
        if (
            r["journey_id"] == journey["id"]
            and r["redemption_status"] == "ACTIVE"
        ):
            r["redemption_status"] = "VOIDED"
            touch(r)
            credit = db.travel_credits.get(r["credit_id"])
            if credit:
                credit["remaining_amount_cents"] += r["amount_cents"]
                if (
                    credit["credit_status"] == "PARTIALLY_REDEEMED"
                    and credit["remaining_amount_cents"] >= credit["initial_amount_cents"]
                ):
                    credit["credit_status"] = "OPEN"
                elif (
                    credit["credit_status"] == "PARTIALLY_REDEEMED"
                    and credit["remaining_amount_cents"] == credit["initial_amount_cents"]
                ):
                    credit["credit_status"] = "OPEN"
                touch(credit)


def compute_mint_amount(journey):
    """Step 2: base fare + ACTIVE upgrade prices (never redemption balances)."""
    amount = journey["base_fare_cents"]
    for u in active_upgrades_for_journey(journey["id"]):
        amount += u["price_cents"]
    return max(0, amount)


def cancel_journey_cascade(journey, flight_cancelled=False):
    """Journey cancellation side effects: credit mint, upgrades refunded,
    assignment voided. Caller sets journey_status first."""
    leg = get_leg(journey["flight_leg_id"])
    fare = get_fare(journey["fare_class_id"])
    void_journey_redemptions_compensate(journey)
    amount = compute_mint_amount(journey)
    if leg is not None and fare is not None:
        mint_travel_credit(journey["passenger_id"], journey, amount, fare, leg)
    for u in active_upgrades_for_journey(journey["id"]):
        u["upgrade_status"] = "REFUNDED"
        touch(u)
    asg = active_assignment_for_journey(journey["id"])
    if asg:
        asg["assignment_status"] = "VOIDED"
        asg["release_reason"] = (
            "FLIGHT_CANCELLED" if flight_cancelled else "JOURNEY_CANCELLED"
        )
        touch(asg)
    maybe_cancel_booking(journey["booking_id"])


def maybe_cancel_booking(booking_id):
    b = db.bookings.get(booking_id)
    if not b or b["booking_status"] != "ACTIVE":
        return
    journeys = [j for j in db.journeys.values() if j["booking_id"] == booking_id]
    if journeys and all(
        j["journey_status"] in ("CANCELLED", "NO_SHOW") for j in journeys
    ):
        b["booking_status"] = "CANCELLED"
        touch(b)


def refresh_booking_journeys(booking_id):
    b = db.bookings.get(booking_id)
    if not b:
        return
    journeys = [j for j in db.journeys.values() if j["booking_id"] == booking_id]
    # PRD §3.3: journey_ids are ordered by journey creation time ascending;
    # _seq breaks millisecond ties in submission order (UUIDs are random).
    journeys.sort(key=lambda j: (j["created_at"], j.get("_seq", 0)))
    b["journey_count"] = len(journeys)
    b["journey_ids"] = [j["id"] for j in journeys]


def no_show_journey(journey):
    """Convert a CHECKED_IN journey to NO_SHOW with standing/credit consequences."""
    journey["journey_status"] = "NO_SHOW"
    touch(journey)
    p = get_passenger(journey["passenger_id"])
    if p:
        p["no_show_count"] = p.get("no_show_count", 0) + 1
        p["standing"] = "NO_SHOW_FLAGGED" if p["no_show_count"] >= 2 else "GOOD"
        touch(p)
    fare = get_fare(journey["fare_class_id"])
    leg = get_leg(journey["flight_leg_id"])
    if fare and fare.get("change_fee_cents", 0) == 0:
        # flexible: mint credit for base fare
        mint_travel_credit(
            journey["passenger_id"], journey, journey["base_fare_cents"], fare, leg
        )
    else:
        journey["no_show_penalty_cents"] = journey["base_fare_cents"]
    for u in active_upgrades_for_journey(journey["id"]):
        u["upgrade_status"] = "VOIDED"
        touch(u)
    maybe_cancel_booking(journey["booking_id"])


# ---------- delay propagation ----------


def post_disruption_event(leg, disruption_type, cause, delay_minutes, depth):
    row = new_row()
    row.update(
        {
            "flight_leg_id": leg["id"],
            "disruption_type": disruption_type,
            "cause": cause,
            "delay_minutes": delay_minutes,
            "posted_utc": clock_now_iso(),
            "propagation_depth": depth,
        }
    )
    db.disruption_events[row["id"]] = row
    return row


def apply_delay_to_leg(leg, delay_minutes, cause, propagated, depth):
    """Apply a delay to a leg and cascade. Returns event."""
    event = post_disruption_event(
        leg, "DELAY", cause, delay_minutes, depth
    )
    leg["leg_status"] = "DELAYED"
    leg["delay_minutes"] = delay_minutes
    leg["delay_cause"] = cause
    leg["delay_propagated"] = propagated
    touch(leg)
    if delay_minutes >= RETIME_THRESHOLD_MINUTES:
        retime_recompute(leg)
    _propagate(leg, depth)
    return event


def _propagate(leg, depth):
    """Aircraft hop then crew hop."""
    if depth + 1 > PROPAGATION_DEPTH_CAP:
        return
    # aircraft hop
    for r in list(db.aircraft_routings.values()):
        if r["routing_status"] != "ACTIVE" or leg["id"] not in r["leg_ids"]:
            continue
        recompute_routing_slack(r)
        idx = r["leg_ids"].index(leg["id"])
        if idx + 1 < len(r["leg_ids"]):
            nxt = get_leg(r["leg_ids"][idx + 1])
            if nxt and nxt["leg_status"] == "SCHEDULED":
                std_next = parse_dt(nxt["scheduled_departure_utc"])
                sta_prev = parse_dt(leg["scheduled_arrival_utc"])
                slack = int(
                    (std_next - sta_prev).total_seconds() // 60
                ) - nxt["turn_target_minutes"]
                if slack < leg["delay_minutes"]:
                    new_delay = leg["delay_minutes"] - max(slack, 0)
                    if new_delay >= 1:
                        apply_delay_to_leg(
                            nxt, new_delay, "INBOUND_DELAY", True, depth + 1
                        )
    # crew hop (reads post-aircraft-cascade state)
    for p in list(db.crew_pairings.values()):
        if p["pairing_status"] != "ACTIVE" or leg["id"] not in p["leg_ids"]:
            continue
        idx = p["leg_ids"].index(leg["id"])
        if idx + 1 >= len(p["leg_ids"]):
            continue
        nxt = get_leg(p["leg_ids"][idx + 1])
        if not nxt:
            continue
        # connection station = destination of the delayed leg
        conn_station = db.stations.get(leg["destination_station_id"])
        buffer = conn_station.get("min_connection_minutes", 40) if conn_station else 40
        new_dep = parse_dt(leg["scheduled_departure_utc"]) + timedelta(
            minutes=leg["delay_minutes"]
        )
        nxt_std = parse_dt(nxt["scheduled_departure_utc"])
        # unreachable if new arrival + buffer > next STD
        new_arr = parse_dt(leg["scheduled_arrival_utc"]) + timedelta(
            minutes=leg["delay_minutes"]
        )
        if new_arr + timedelta(minutes=buffer) > nxt_std:
            p["pairing_status"] = "BROKEN"
            touch(p)
            if nxt["leg_status"] == "SCHEDULED":
                gap = int((nxt_std - new_arr).total_seconds() // 60) - buffer
                crew_delay = leg["delay_minutes"] - max(gap, 0)
                if crew_delay < 1:
                    crew_delay = leg["delay_minutes"]
                apply_delay_to_leg(nxt, crew_delay, "CREW", True, depth + 1)


def recompute_routing_slack(routing):
    legs = [get_leg(lid) for lid in routing["leg_ids"]]
    legs = [l for l in legs if l]
    if len(legs) < 2:
        routing["slack_minutes"] = 0
        return
    slacks = []
    for a, b in zip(legs, legs[1:]):
        gap = int(
            (
                parse_dt(b["scheduled_departure_utc"])
                - parse_dt(a["scheduled_arrival_utc"])
            ).total_seconds()
            // 60
        )
        slacks.append(gap - b["turn_target_minutes"])
    routing["slack_minutes"] = min(slacks)


def break_routings_for_leg(leg, cause_for_downstream="INBOUND_DELAY"):
    for r in list(db.aircraft_routings.values()):
        if r["routing_status"] != "ACTIVE" or leg["id"] not in r["leg_ids"]:
            continue
        r["routing_status"] = "BROKEN"
        touch(r)


def break_pairings_for_leg(leg):
    for p in list(db.crew_pairings.values()):
        if p["pairing_status"] != "ACTIVE" or leg["id"] not in p["leg_ids"]:
            continue
        p["pairing_status"] = "BROKEN"
        touch(p)


def cancel_leg_cascade(leg):
    """Flight cancellation cascade."""
    for j in list(db.journeys.values()):
        if j["flight_leg_id"] == leg["id"] and j["journey_status"] in (
            "BOOKED",
            "CHECKED_IN",
        ):
            j["journey_status"] = "CANCELLED"
            touch(j)
            cancel_journey_cascade(j, flight_cancelled=True)
    # assignments on the leg not tied to BOOKED/CHECKED_IN journeys still void
    for a in list(db.boarding_assignments.values()):
        if a["flight_leg_id"] == leg["id"] and a["assignment_status"] == "ACTIVE":
            a["assignment_status"] = "VOIDED"
            a["release_reason"] = "FLIGHT_CANCELLED"
            touch(a)
    break_routings_for_leg(leg)
    break_pairings_for_leg(leg)
    for b in list(db.bags.values()):
        j = db.journeys.get(b["journey_id"])
        if j and j["flight_leg_id"] == leg["id"] and b["bag_status"] == "ACCEPTED":
            b["bag_status"] = "OFFLOADED"
            touch(b)


# ---------- turn projection / staffing ----------


def projected_bags(leg):
    total = 0
    for j in db.journeys.values():
        if j["flight_leg_id"] != leg["id"]:
            continue
        if j["journey_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        accepted = sum(
            1
            for b in db.bags.values()
            if b["journey_id"] == j["id"] and b["bag_status"] == "ACCEPTED"
        )
        total += accepted
        if j["journey_status"] == "BOOKED":
            fare = get_fare(j["fare_class_id"])
            total += fare.get("included_bags", 2) if fare else 2
    return min(total, 2 * leg["capacity_seats"])


def booked_journey_count(leg):
    return sum(
        1
        for j in db.journeys.values()
        if j["flight_leg_id"] == leg["id"]
        and j["journey_status"] in ("BOOKED", "CHECKED_IN")
    )


def turn_projection(leg):
    if leg["leg_status"] in ("DEPARTED", "ARRIVED"):
        # realized view
        loaded = 0
        boarded = 0
        for j in db.journeys.values():
            if j["flight_leg_id"] != leg["id"]:
                continue
            loaded += sum(
                1
                for b in db.bags.values()
                if b["journey_id"] == j["id"] and b["bag_status"] in ("LOADED", "DELIVERED")
            )
            if j["journey_status"] in ("BOARDED", "COMPLETED"):
                boarded += 1
        bag_minutes = BAG_MINUTES_PER_BAG * loaded
        pax_minutes = math.ceil(boarded * SECONDS_PER_PAX / 60)
        projected = TURN_BASE_MINUTES + bag_minutes + pax_minutes
        return {
            "projected_turn_minutes": projected,
            "projected_bags": loaded,
            "pax_minutes": pax_minutes,
            "turns_slip": projected > leg["turn_target_minutes"],
        }
    pb = projected_bags(leg)
    bag_minutes = BAG_MINUTES_PER_BAG * pb
    pax = booked_journey_count(leg)
    pax_minutes = math.ceil(pax * SECONDS_PER_PAX / 60)
    buffer = DELAY_RISK_BUFFER_MINUTES if leg["delay_minutes"] > 0 else 0
    projected = TURN_BASE_MINUTES + bag_minutes + pax_minutes + buffer
    return {
        "projected_turn_minutes": projected,
        "projected_bags": pb,
        "pax_minutes": pax_minutes,
        "turns_slip": projected > leg["turn_target_minutes"],
    }


def staffing_adequacy(leg, proj_bags):
    pax = booked_journey_count(leg)
    cap = leg["capacity_seats"]
    load_factor = (Decimal(pax) / Decimal(cap)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    staff_units = leg["gate_agent_count"] + leg["ramp_agent_count"]
    ramp = max(leg["ramp_agent_count"], 1)
    bags_per_ramp = (Decimal(proj_bags) / Decimal(ramp)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    understaffed = staff_units < REQUIRED_STAFF_UNITS or (
        load_factor >= HIGH_LOAD_FACTOR and bags_per_ramp > BAGS_PER_RAMP_AGENT_MAX
    )
    return {
        "understaffed": understaffed,
        "staff_units": staff_units,
        "load_factor": float(load_factor),
        "bags_per_ramp_agent": float(bags_per_ramp),
        "projected_bags": proj_bags,
    }
