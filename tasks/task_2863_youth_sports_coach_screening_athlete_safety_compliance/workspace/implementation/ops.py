"""Shared cascade mechanics (PRD sections 2.10, 3.3, 3.6, 3.7, 3.8).

Every helper here mutates rows only; the callers bump Member.version exactly
once per request and finish with derive.recompute_all() so no derived counter
is ever stale (PRD section 2.10: no deferred recomputation).
"""

import calc
import clock
import derive
import store


# ------------------------------------------------------------ member stamps --
def stamp_horizons(member):
    """AUDIT_SNAPSHOT projection onto eligible_through, then retention."""
    derive.stamp_eligible_through(member)
    member["records_retained_through"] = derive.records_retained_through(member)


def bubble_membership(member):
    """PENDING -> ACTIVE, the only automatic membership advance (PRD 3.4)."""
    derive.recompute_member(member)
    if (member["membership_status"] == "PENDING"
            and member["screening_status"] == "CLEARED"
            and member["training_status"] == "CURRENT"
            and not derive.has_measure(member["id"], ("ACTIVE", "PERMANENT"))):
        member["membership_status"] = "ACTIVE"
        derive.stamp_eligible_through(member)


# ------------------------------------------------------ placement cascades --
def suspend_placements(member):
    """Hop three of the restriction cascade."""
    for a in store.coach_assignments_of_member(member["id"]):
        if a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            a["suspended_reason"] = "INTERIM_MEASURE"
            store.bump(a)


def release_is_clear(member):
    derive.recompute_member(member)
    return (not derive.has_measure(member["id"], ("ACTIVE", "PERMANENT"))
            and member["screening_status"] == "CLEARED"
            and member["training_status"] == "CURRENT")


def restore_after_release(member):
    """Compensating counterpart of suspend_placements (PRD 3.6, 3.8)."""
    if not release_is_clear(member):
        derive.recompute_member(member)
        return
    if member["membership_status"] == "SUSPENDED":
        member["membership_status"] = "ACTIVE"
    for a in store.coach_assignments_of_member(member["id"]):
        if a["status"] == "SUSPENDED" and a["suspended_reason"] == "INTERIM_MEASURE":
            a["status"] = "ACTIVE"
            a["suspended_reason"] = None
            store.bump(a)
    derive.recompute_member(member)


def terminate_placements(member, reason):
    for a in store.coach_assignments_of_member(member["id"]):
        if a["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            a["status"] = "TERMINATED"
            a["suspended_reason"] = reason
            store.bump(a)


def revoke_member(member, reason):
    """Membership dimension to REVOKED plus placement termination."""
    member["membership_status"] = "REVOKED"
    terminate_placements(member, reason)
    derive.recompute_member(member)


def make_measures_permanent(member, actor_user_id=None):
    for m in store.measures_of(member["id"]):
        if m["status"] == "ACTIVE":
            m["status"] = "PERMANENT"
            m["permanence"] = "PERMANENT"
            if actor_user_id is not None:
                m["converted_by_user_id"] = actor_user_id
            store.bump(m)


def lift_measures(member, reason):
    for m in store.measures_of(member["id"]):
        if m["status"] == "ACTIVE":
            m["status"] = "LIFTED"
            m["lifted_at"] = clock.now()
            m["lift_reason"] = reason
            store.bump(m)


# --------------------------------------------------------- window arithmetic --
def measure_window_conflict(member_id, measure_kind, requested_from, requested_to):
    """Closed endpoints, 14-day trailing cooling buffer, ACTIVE same-kind only."""
    for m in store.measures_of(member_id):
        if m["status"] != "ACTIVE" or m["measure_kind"] != measure_kind:
            continue
        if m["effective_to"] is None:
            buffered_end = None
        else:
            buffered_end = clock.plus_days(m["effective_to"], calc.MEASURE_COOLING_BUFFER_DAYS)
        starts_before_end = True if buffered_end is None else requested_from <= buffered_end
        ends_after_start = True if requested_to is None else m["effective_from"] <= requested_to
        if starts_before_end and ends_after_start:
            return True
    return False


def slot_neighbours(club_id, trip_label, room_number, check_in, check_out):
    """BOOKED stays in the same slot whose half-open interval intersects."""
    out = []
    for s in store.ROOM_STAYS.values():
        if s["club_id"] != club_id or s["status"] != "BOOKED":
            continue
        if s["trip_label"] != trip_label or s["room_number"] != room_number:
            continue
        if check_in < s["check_out"] and s["check_in"] < check_out:
            out.append(s)
    return out
