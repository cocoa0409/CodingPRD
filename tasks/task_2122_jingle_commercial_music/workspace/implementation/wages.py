"""AFM wage arithmetic (PRD 3.5 and 3.9)."""

from fractions import Fraction

import db
import money

AFM_MINIMUM_CALL_HOURS = Fraction(3)
AFM_LEADER_MULTIPLIER = 2
AFM_DOUBLING_PCT = 20
AFM_PENSION_HEALTH_PCT = 12
AFM_DAY_RATE_HOURS_CAP = Fraction(8)
AFM_CANCEL_WINDOW_HOURS = Fraction(24)
AFM_TURNAROUND_BUFFER_MINUTES = 60


def line_wage(musician, booking, hours_basis):
    """The five ordered steps of a single booking line's wage (PRD 3.5)."""
    billable_hours = max(AFM_MINIMUM_CALL_HOURS, money.frac(hours_basis))
    base_cents = money.round_half_up(money.frac(musician["scale_hourly_cents"]) * billable_hours)
    leader_factor = AFM_LEADER_MULTIPLIER if booking["is_leader"] else 1
    leader_part = money.round_half_up(money.frac(base_cents) * leader_factor)
    doubling_part = money.round_half_up(
        money.pct(base_cents, AFM_DOUBLING_PCT) * booking["doubles_count"]
    )
    line_wage_cents = leader_part + doubling_part
    pension_health_cents = money.round_half_up(money.pct(line_wage_cents, AFM_PENSION_HEALTH_PCT))
    return line_wage_cents, pension_health_cents


def call_bookings(call_id, statuses=None):
    rows = [b for b in db.bookings.values() if b["session_call_id"] == call_id]
    if statuses is not None:
        rows = [b for b in rows if b["status"] in statuses]
    return db.by_created(rows)


def wage_component(call, hours_basis, statuses=("BOOKED",)):
    """Sum of the per-line wages, iterated in created_at ascending order."""
    total = 0
    for booking in call_bookings(call["id"], statuses):
        musician = db.musicians[booking["musician_id"]]
        wage, _ = line_wage(musician, booking, hours_basis)
        total += wage
    return total


def studio_cost(call, hours_basis):
    room = db.studio_rooms[call["studio_room_id"]]
    return money.round_half_up(money.frac(room["hourly_rate_cents"]) * money.frac(hours_basis))


def pension_health(line_wage_cents):
    return money.round_half_up(money.pct(line_wage_cents, AFM_PENSION_HEALTH_PCT))


def afm_report(project, basis):
    """The AFM wage report (PRD 3.9). Every line is rounded first, then summed."""
    calls = {c["id"]: c for c in db.session_calls.values() if c["project_id"] == project["id"]}
    if basis == "SESSION":
        rows = [
            b for b in db.bookings.values()
            if b["session_call_id"] in calls and b["status"] in ("WAGE_ACCRUED", "PENALTY_ACCRUED")
        ]
        rows = db.by_created(rows)
        wage_total = sum(r["line_wage_cents"] for r in rows)
        pension_total = sum(pension_health(r["line_wage_cents"]) for r in rows)
        return {
            "basis": "SESSION",
            "wage_total_cents": wage_total,
            "pension_health_cents": pension_total,
            "session_count": len({r["session_call_id"] for r in rows}),
            "booking_count": len(rows),
        }

    completed = {cid: c for cid, c in calls.items() if c["status"] == "COMPLETED"}
    groups = {}
    for booking in db.by_created([b for b in db.bookings.values()
                                  if b["session_call_id"] in completed and b["status"] == "WAGE_ACCRUED"]):
        call = completed[booking["session_call_id"]]
        key = (booking["musician_id"], call["_start_dt"].date().isoformat())
        group = groups.setdefault(key, {"bookings": [], "calls": {}})
        group["bookings"].append(booking)
        group["calls"][call["id"]] = call

    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (db.musicians[k[0]]["created_at"], db.musicians[k[0]]["_seq"], k[1]),
    )

    wage_total = 0
    pension_total = 0
    booking_count = 0
    for key in ordered_keys:
        group = groups[key]
        musician = db.musicians[key[0]]
        day_hours = sum((c["_billed_hours"] for c in group["calls"].values()), Fraction(0))
        billable = max(AFM_MINIMUM_CALL_HOURS, min(AFM_DAY_RATE_HOURS_CAP, day_hours))
        base_cents = money.round_half_up(money.frac(musician["scale_hourly_cents"]) * billable)
        leader_factor = AFM_LEADER_MULTIPLIER if any(b["is_leader"] for b in group["bookings"]) else 1
        doubles = max(b["doubles_count"] for b in group["bookings"])
        day_wage = money.round_half_up(money.frac(base_cents) * leader_factor) + money.round_half_up(
            money.pct(base_cents, AFM_DOUBLING_PCT) * doubles
        )
        wage_total += day_wage
        pension_total += pension_health(day_wage)
        booking_count += len(group["bookings"])

    return {
        "basis": "DAY",
        "wage_total_cents": wage_total,
        "pension_health_cents": pension_total,
        "session_count": len(completed),
        "booking_count": booking_count,
    }
