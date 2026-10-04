"""Shared business logic: posture/coverage derivation, cascades, run_ops."""

from datetime import date

from constants import (
    COVERAGE_OPEN_THRESHOLD_DEN,
    COVERAGE_OPEN_THRESHOLD_NUM,
    RENEWAL_WINDOW_DAYS,
    STRIKE_LIMIT,
)
from helpers import bump, now, today
from storage import STORE


# ---------------------------------------------------------------------------
# Center posture / coverage (PRD 2.6, confirmed-only variant)
# ---------------------------------------------------------------------------

def confirmed_slots_today(center):
    """Count of CONFIRMED assignments whose shift start falls on the clock date."""
    d = today()
    count = 0
    for a in STORE.assignments.values():
        if a["status"] != "CONFIRMED":
            continue
        s = STORE.shifts.get(a["shift_id"])
        if s is None or s["center_id"] != center["id"]:
            continue
        if s["start_at"].date() == d:
            count += 1
    return count


def recompute_center(center, bump_center=True):
    """Recompute coverage_ratio and posture; store them (version bump per PRD 2.6)."""
    confirmed = confirmed_slots_today(center)
    required = center["required_daily_confirmed_assignments"]
    center["coverage_ratio"] = confirmed / required

    active = None
    ag_id = center.get("active_agreement_id")
    if ag_id is not None:
        ag = STORE.agreements.get(ag_id)
        if ag is not None and ag["status"] == "ACTIVE":
            active = ag

    if active is None:
        posture = "CLOSED"
    elif confirmed * COVERAGE_OPEN_THRESHOLD_DEN >= required * COVERAGE_OPEN_THRESHOLD_NUM:
        posture = "OPEN"
    else:
        posture = "RESTRICTED"
    center["posture"] = posture
    if bump_center:
        bump(center)


def active_agreement(center):
    ag_id = center.get("active_agreement_id")
    if ag_id is None:
        return None
    ag = STORE.agreements.get(ag_id)
    if ag is not None and ag["status"] == "ACTIVE":
        return ag
    return None


# ---------------------------------------------------------------------------
# Shift status derivation (OPEN <-> FILLED)
# ---------------------------------------------------------------------------

def refresh_shift_status(shift):
    shift["status"] = "FILLED" if shift["confirmed_count"] >= shift["capacity"] else "OPEN"


# ---------------------------------------------------------------------------
# Volunteer cascades (PRD 3.2)
# ---------------------------------------------------------------------------

def cancel_future_assignments(volunteer, ref_now, affected_centers, suppressed_centers):
    """Cancel the volunteer's future-dated ASSIGNED/CONFIRMED assignments."""
    for a in list(STORE.assignments.values()):
        if a["volunteer_id"] != volunteer["id"]:
            continue
        if a["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        s = STORE.shifts.get(a["shift_id"])
        if s is None:
            continue
        if s["start_at"] <= ref_now:
            continue
        if a["status"] == "CONFIRMED":
            s["confirmed_count"] -= 1
            refresh_shift_status(s)
            bump(s)
            if s["center_id"] not in suppressed_centers:
                affected_centers.add(s["center_id"])
        a["status"] = "CANCELLED"
        bump(a)


def suspend_volunteer(volunteer, ref_now, affected_centers, suppressed_centers):
    """ACTIVE -> SUSPENDED at the strike limit, with the cancellation cascade."""
    volunteer["status"] = "SUSPENDED"
    bump(volunteer)
    cancel_future_assignments(volunteer, ref_now, affected_centers, suppressed_centers)


def apply_no_show(assignment, shift, ref_now, affected_centers, suppressed_centers):
    """CONFIRMED -> NO_SHOW with strike, shift release, and possible suspension."""
    assignment["status"] = "NO_SHOW"
    bump(assignment)

    volunteer = STORE.volunteers.get(assignment["volunteer_id"])
    if volunteer is not None:
        volunteer["no_show_strikes"] += 1
        bump(volunteer)

    shift["confirmed_count"] -= 1
    refresh_shift_status(shift)
    bump(shift)
    if shift["center_id"] not in suppressed_centers:
        affected_centers.add(shift["center_id"])

    if (
        volunteer is not None
        and volunteer["status"] == "ACTIVE"
        and volunteer["no_show_strikes"] >= STRIKE_LIMIT
    ):
        suspend_volunteer(volunteer, ref_now, affected_centers, suppressed_centers)


def settle_affected_centers(affected_centers):
    for cid in affected_centers:
        c = STORE.centers.get(cid)
        if c is not None:
            recompute_center(c)


# ---------------------------------------------------------------------------
# run_ops sweeps (PRD 2.9) for a single center
# ---------------------------------------------------------------------------

def run_ops(center):
    ref_now = now()
    d = ref_now.date()
    cid = center["id"]
    suppressed = {cid}      # this center gets exactly one version bump at the end
    affected = set()        # other centers touched by cascades

    # 1. Screenings: CLEARED whose expires_at has been reached -> EXPIRED,
    #    then lapse volunteers with no unexpired CLEARED screening.
    for vol in list(STORE.volunteers.values()):
        if vol["home_center_id"] != cid:
            continue
        for sc in list(STORE.screenings.values()):
            if sc["volunteer_id"] != vol["id"]:
                continue
            if (
                sc["status"] == "CLEARED"
                and sc["expires_at"] is not None
                and sc["expires_at"] <= ref_now
            ):
                sc["status"] = "EXPIRED"
                bump(sc)
        if vol["status"] in ("CLEARED", "ACTIVE", "SUSPENDED"):
            has_valid = any(
                s["volunteer_id"] == vol["id"]
                and s["status"] == "CLEARED"
                and s["expires_at"] is not None
                and s["expires_at"] > ref_now
                for s in STORE.screenings.values()
            )
            if not has_valid:
                if vol["status"] == "ACTIVE":
                    cancel_future_assignments(vol, ref_now, affected, suppressed)
                vol["status"] = "INACTIVE"
                bump(vol)

    # 2. Site agreements: expiry first, then renewal-window flagging.
    for ag in list(STORE.agreements.values()):
        if ag["center_id"] != cid:
            continue
        end = date_from_str(ag["end_date"])
        if ag["status"] in ("ACTIVE", "RENEWAL_DUE") and d > end:
            ag["status"] = "EXPIRED"
            bump(ag)
            if center.get("active_agreement_id") == ag["id"]:
                center["active_agreement_id"] = None
        elif ag["status"] == "ACTIVE" and 0 <= (end - d).days <= RENEWAL_WINDOW_DAYS:
            ag["status"] = "RENEWAL_DUE"
            bump(ag)

    # 3. Donation lots: expired AVAILABLE lots -> DISCARDED_EXPIRED.
    for lot in list(STORE.lots.values()):
        if lot["center_id"] != cid:
            continue
        if lot["status"] == "AVAILABLE" and date_from_str(lot["expiry_date"]) < d:
            lot["status"] = "DISCARDED_EXPIRED"
            bump(lot)

    # 4. Assignments: auto no-show for CONFIRMED past shift end.
    for a in list(STORE.assignments.values()):
        if a["status"] != "CONFIRMED":
            continue
        s = STORE.shifts.get(a["shift_id"])
        if s is None or s["center_id"] != cid:
            continue
        if s["end_at"] <= ref_now:
            apply_no_show(a, s, ref_now, affected, suppressed)

    # 5. Visit check-ins: day-end sweep of stale CHECKED_IN visits.
    for ci in list(STORE.checkins.values()):
        if ci["center_id"] != cid or ci["status"] != "CHECKED_IN":
            continue
        if ci["checked_in_at"].date() < d:
            ci["status"] = "CHECKED_OUT"
            ci["checked_out_at"] = ref_now
            bump(ci)
            center["current_occupancy"] -= 1

    # 6. Service bookings: BOOKED with end_at passed -> COMPLETED.
    for bk in list(STORE.bookings.values()):
        if bk["center_id"] != cid or bk["status"] != "BOOKED":
            continue
        if bk["end_at"] <= ref_now:
            bk["status"] = "COMPLETED"
            bump(bk)

    # 7. Events: CONFIRMED past end -> EXECUTED; stale unconfirmed -> CANCELLED.
    for ev in list(STORE.events.values()):
        if ev["center_id"] != cid:
            continue
        if ev["status"] == "CONFIRMED" and ev["end_at"] <= ref_now:
            ev["status"] = "EXECUTED"
            bump(ev)
        elif ev["status"] in ("PLANNED", "SECURITY_REVIEW", "SECURITY_APPROVED") and ev["start_at"] <= ref_now:
            ev["status"] = "CANCELLED"
            bump(ev)

    # 8. Funding grants: ACTIVE past spend-by -> EXPIRED.
    for gr in list(STORE.grants.values()):
        if gr["center_id"] != cid:
            continue
        if gr["status"] == "ACTIVE" and date_from_str(gr["spend_by_date"]) < d:
            gr["status"] = "EXPIRED"
            bump(gr)

    # Finalize: coverage/posture recompute; exactly one center version bump.
    recompute_center(center, bump_center=False)
    settle_affected_centers(affected)
    center["ops_run_count"] += 1
    center["version"] += 1
    center["updated_at"] = ref_now


def date_from_str(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
