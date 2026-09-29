"""Derivations, cascades and cross-entity gates.

Everything here is pure dict manipulation over the in-memory store; nothing is
persisted and nothing is seeded.
"""

from datetime import timedelta
from decimal import Decimal

import calc
from core import (
    all_rows,
    db,
    minutes_between,
    now,
    ordered,
    touch,
    update,
)
from serialize import cert_status, issue_sla_breached

FILLED_ATTENDANCE = ("SCHEDULED", "CHECKED_IN", "COMPLETED")
LIVE_ATTENDANCE = ("SCHEDULED", "CHECKED_IN")
LIVE_BID = ("SUBMITTED", "WAITLISTED")
COMMITTED_BOOKING = ("CONFIRMED", "IN_SERVICE")


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------

def plans_of_event(event):
    return [p for p in all_rows("staffing_plans") if p["event_id"] == event["id"]]


def slots_of_plan(plan):
    return [s for s in all_rows("position_slots") if s["plan_id"] == plan["id"]]


def assignments_of_slot(slot):
    return [
        a
        for a in all_rows("staff_assignments")
        if a["position_slot_id"] == slot["id"]
    ]


def bids_of_slot(slot):
    return [b for b in all_rows("shift_bids") if b["position_slot_id"] == slot["id"]]


def assignments_of_member(member):
    return [
        a
        for a in all_rows("staff_assignments")
        if a["staff_member_id"] == member["id"]
    ]


def bids_of_member(member):
    return [b for b in all_rows("shift_bids") if b["staff_member_id"] == member["id"]]


def certs_of_member(member_id):
    return [
        c for c in all_rows("certifications") if c["staff_member_id"] == member_id
    ]


def issues_of_event(event):
    return [i for i in all_rows("guest_issues") if i["event_id"] == event["id"]]


def responses_of_event(event):
    return [
        r
        for r in all_rows("satisfaction_responses")
        if r["event_id"] == event["id"]
    ]


def bookings_of_resource(resource):
    return [
        r
        for r in all_rows("accessibility_requests")
        if r["resource_id"] == resource["id"]
    ]


def plan_of_slot(slot):
    return db.staffing_plans[slot["plan_id"]]


def position_type_of_slot(slot):
    return db.position_types[slot["position_type_id"]]


def event_of_plan(plan):
    return db.events[plan["event_id"]]


def event_of_slot(slot):
    return event_of_plan(plan_of_slot(slot))


def slot_of_assignment(assignment):
    return db.position_slots[assignment["position_slot_id"]]


def member_of_assignment(assignment):
    return db.staff_members[assignment["staff_member_id"]]


def assignments_of_event(event):
    plan_ids = {p["id"] for p in plans_of_event(event)}
    slot_ids = {
        s["id"] for s in all_rows("position_slots") if s["plan_id"] in plan_ids
    }
    return [
        a
        for a in all_rows("staff_assignments")
        if a["position_slot_id"] in slot_ids
    ]


def plan_in_status(event, statuses):
    for plan in plans_of_event(event):
        if plan["status"] in statuses:
            return plan
    return None


# ---------------------------------------------------------------------------
# slot fill derivation (§2.10)
# ---------------------------------------------------------------------------

def derived_status(filled, required):
    if filled == 0:
        return "OPEN"
    if filled < required:
        return "PARTIALLY_FILLED"
    return "FILLED"


def count_filled(slot):
    return sum(
        1
        for a in assignments_of_slot(slot)
        if a["attendance_status"] in FILLED_ATTENDANCE
    )


def recount_slot(slot):
    """Re-derive filled_headcount and, unless sticky, the fill status."""
    previous = slot["filled_headcount"]
    filled = count_filled(slot)
    if slot["status"] == "CLOSED":
        update(slot, filled_headcount=filled)
        return
    if slot["status"] == "UNDERSTAFFED_ESCALATED" and filled == previous:
        update(slot, filled_headcount=filled)
        return
    update(
        slot,
        filled_headcount=filled,
        status=derived_status(filled, slot["required_headcount"]),
    )


def rederive_slot_status(slot):
    """Re-apply the pure fill function without touching filled_headcount."""
    if slot["status"] in ("CLOSED", "UNDERSTAFFED_ESCALATED"):
        return
    update(
        slot,
        status=derived_status(slot["filled_headcount"], slot["required_headcount"]),
    )


# ---------------------------------------------------------------------------
# sizing and costing (§3.2)
# ---------------------------------------------------------------------------

def size_slot(slot, plan=None, position_type=None, rederive=True):
    """Recompute shift_minutes, both headcounts, the cost and the fill status.

    Everything lands in one update() call so the slot's version moves once.
    """
    plan = plan or plan_of_slot(slot)
    position_type = position_type or position_type_of_slot(slot)
    ratio = calc.ratio_headcount(
        plan["basis_attendance"],
        position_type["attendance_ratio_per_1000"],
        position_type["min_headcount"],
    )
    override = slot["required_headcount_override"]
    required = override if override is not None else ratio
    shift_minutes = minutes_between(slot["shift_start"], slot["shift_end"])
    changes = {
        "ratio_derived_headcount": ratio,
        "required_headcount": required,
        "shift_minutes": shift_minutes,
        "slot_labor_cost_cents": calc.slot_labor_cost(
            required, position_type["base_hourly_rate_cents"], shift_minutes
        ),
    }
    if rederive and slot["status"] not in ("CLOSED", "UNDERSTAFFED_ESCALATED"):
        changes["status"] = derived_status(slot["filled_headcount"], required)
    update(slot, **changes)


def recost_plan(plan):
    """The six-step pass of §3.2 over the plan's non-CLOSED slots."""
    slots = [s for s in slots_of_plan(plan) if s["status"] != "CLOSED"]
    base = 0
    for slot in slots:
        position_type = position_type_of_slot(slot)
        cost = calc.slot_labor_cost(
            slot["required_headcount"],
            position_type["base_hourly_rate_cents"],
            slot["shift_minutes"],
        )
        update(slot, slot_labor_cost_cents=cost)
        base += cost
    total_headcount = sum(s["required_headcount"] for s in slots)
    bp = calc.surcharge_bp(total_headcount)
    surcharge = calc.surcharge_cents(base, bp)
    update(
        plan,
        total_required_headcount=total_headcount,
        base_labor_cost_cents=base,
        accessibility_surcharge_cents=surcharge,
        projected_labor_cost_cents=base + surcharge,
    )


# ---------------------------------------------------------------------------
# guest-recovery ledger (§2.11)
# ---------------------------------------------------------------------------

def rederive_ledger(event):
    approved = sum(
        i["refund_approved_cents"]
        for i in issues_of_event(event)
        if i["refund_status"] in ("APPROVED", "PARTIALLY_APPROVED")
    )
    update(
        event,
        refund_approved_total_cents=approved,
        refund_budget_remaining_cents=event["refund_budget_total_cents"] - approved,
    )


def ledger_fields_only(event):
    """Recompute the two derived ledger figures in place, without a version bump."""
    approved = sum(
        i["refund_approved_cents"]
        for i in issues_of_event(event)
        if i["refund_status"] in ("APPROVED", "PARTIALLY_APPROVED")
    )
    event["refund_approved_total_cents"] = approved
    event["refund_budget_remaining_cents"] = (
        event["refund_budget_total_cents"] - approved
    )


# ---------------------------------------------------------------------------
# cascades (§2.10, §3.3, §3.4)
# ---------------------------------------------------------------------------

def cancel_assignment(assignment):
    update(
        assignment,
        attendance_status="CANCELLED",
        payout_status="VOIDED",
        total_payout_cents=0,
    )


def close_slot(slot, decline_reason):
    """Link three of the cascade: close the block, then settle what hangs off it."""
    for assignment in assignments_of_slot(slot):
        if assignment["attendance_status"] in LIVE_ATTENDANCE:
            cancel_assignment(assignment)
    for bid in bids_of_slot(slot):
        if bid["status"] in LIVE_BID:
            update(
                bid,
                status="DECLINED_BY_SYSTEM",
                decision_reason=decline_reason,
            )
    update(slot, status="CLOSED", filled_headcount=count_filled(slot))


def close_plan_slots(plan, decline_reason):
    for slot in slots_of_plan(plan):
        if slot["status"] != "CLOSED":
            close_slot(slot, decline_reason)
    recost_plan(plan)


def supersede_plan(plan):
    update(plan, status="SUPERSEDED")
    close_plan_slots(plan, "PLAN_SUPERSEDED")


def void_plan(plan, decline_reason="EVENT_CANCELLED"):
    update(plan, status="VOIDED")
    close_plan_slots(plan, decline_reason)


def remove_member_from_floor(member):
    """The identical removal cascade shared by SUSPENDED and TERMINATED."""
    for assignment in assignments_of_member(member):
        if assignment["attendance_status"] == "SCHEDULED":
            cancel_assignment(assignment)
            recount_slot(slot_of_assignment(assignment))
    for bid in bids_of_member(member):
        if bid["status"] in LIVE_BID:
            update(bid, status="DECLINED_BY_SYSTEM", decision_reason="MEMBER_SUSPENDED")


# ---------------------------------------------------------------------------
# credentials and eligibility (§3.5)
# ---------------------------------------------------------------------------

def has_valid_cert(member_id, cert_type):
    for cert in certs_of_member(member_id):
        if cert["cert_type"] == cert_type and cert_status(cert) == "VALID":
            return True
    return False


def missing_certs(member_id, position_type):
    return [
        code
        for code in position_type["required_certifications"]
        if not has_valid_cert(member_id, code)
    ]


def live_assignments_of_member(member_id):
    return [
        a
        for a in all_rows("staff_assignments")
        if a["staff_member_id"] == member_id
        and a["attendance_status"] in LIVE_ATTENDANCE
    ]


def has_live_assignment_on_slot(member_id, slot):
    return any(
        a["position_slot_id"] == slot["id"]
        for a in live_assignments_of_member(member_id)
    )


def violates_rest_buffer(member_id, slot, include_same_slot=True):
    """A gap of exactly 30 minutes is accepted; 29 minutes is a conflict."""
    buffer = timedelta(minutes=calc.REST_BUFFER_MINUTES)
    for assignment in live_assignments_of_member(member_id):
        other = slot_of_assignment(assignment)
        if other["id"] == slot["id"]:
            if include_same_slot:
                return True
            continue
        if other["shift_end"] <= slot["shift_start"]:
            gap = slot["shift_start"] - other["shift_end"]
        elif slot["shift_end"] <= other["shift_start"]:
            gap = other["shift_start"] - slot["shift_end"]
        else:
            return True
        if gap < buffer:
            return True
    return False


def has_capacity(slot):
    return slot["filled_headcount"] < slot["required_headcount"]


def batch_eligibility_reason(member, slot, position_type):
    """The batch decline reasons, in the fixed order of §3.5."""
    if member["status"] != "ACTIVE":
        return "MEMBER_NOT_ACTIVE"
    if missing_certs(member["id"], position_type):
        return "CERTIFICATION_MISSING"
    if violates_rest_buffer(member["id"], slot):
        return "REST_CONFLICT"
    return None


# ---------------------------------------------------------------------------
# assignment creation
# ---------------------------------------------------------------------------

def create_assignment(slot, member, source, shift_bid_id=None):
    from core import new_record

    assignment = new_record(
        "staff_assignments",
        {
            "position_slot_id": slot["id"],
            "staff_member_id": member["id"],
            "shift_bid_id": shift_bid_id,
            "source": source,
            "attendance_status": "SCHEDULED",
            "payout_status": "PENDING",
            "check_in_at": None,
            "checked_out_at": None,
            "late_check_in": False,
            "worked_minutes": 0,
            "base_pay_cents": 0,
            "gratuity_cents": 0,
            "total_payout_cents": 0,
        },
    )
    filled = slot["filled_headcount"] + 1
    if slot["status"] == "CLOSED":
        update(slot, filled_headcount=filled)
    else:
        update(
            slot,
            filled_headcount=filled,
            status=derived_status(filled, slot["required_headcount"]),
        )
    return assignment


# ---------------------------------------------------------------------------
# reliability and automatic probation (§3.4, §3.6)
# ---------------------------------------------------------------------------

def reliability_rows(member):
    rows = [
        a
        for a in assignments_of_member(member)
        if a["attendance_status"] in ("COMPLETED", "NO_SHOW")
    ]
    rows.sort(
        key=lambda a: (slot_of_assignment(a)["shift_start"], a["created_at"]),
        reverse=True,
    )
    return rows


def recompute_reliability(member, triggering_assignment=None):
    rows = reliability_rows(member)
    update(
        member,
        reliability_score=calc.reliability_of(rows[: calc.ROLLING_WINDOW_SIZE]),
        season_reliability_score=calc.reliability_of(rows),
    )
    if (
        member["status"] == "ACTIVE"
        and member["reliability_score"] < calc.RELIABILITY_PROBATION_FLOOR
    ):
        auto_probation(member, triggering_assignment)


def auto_probation(member, triggering_assignment=None):
    update(
        member,
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
    )
    trigger_id = triggering_assignment["id"] if triggering_assignment else None
    for assignment in assignments_of_member(member):
        if assignment["id"] == trigger_id:
            continue
        if assignment["attendance_status"] != "SCHEDULED":
            continue
        slot = slot_of_assignment(assignment)
        position_type = position_type_of_slot(slot)
        if "ELEVATOR_OPERATION" not in position_type["required_certifications"]:
            continue
        cancel_assignment(assignment)
        recount_slot(slot)


# ---------------------------------------------------------------------------
# accessibility capacity (§3.9)
# ---------------------------------------------------------------------------

def committed_bookings(resource, exclude_id=None):
    return [
        r
        for r in bookings_of_resource(resource)
        if r["status"] in COMMITTED_BOOKING and r["id"] != exclude_id
    ]


def recompute_peak(resource):
    update(
        resource,
        peak_committed_units=calc.peak_occupancy(committed_bookings(resource)),
    )


def peak_with_candidate(resource, candidate):
    rows = committed_bookings(resource, exclude_id=candidate["id"])
    rows.append(candidate)
    return calc.peak_occupancy(rows)


# ---------------------------------------------------------------------------
# staffed zones for a SEAT_RELOCATION resolution (§3.8)
# ---------------------------------------------------------------------------

def staffed_zones(event):
    zones = set()
    for plan in plans_of_event(event):
        if plan["status"] not in ("ACTIVE", "LOCKED"):
            continue
        for slot in slots_of_plan(plan):
            if slot["status"] != "CLOSED":
                zones.add(slot["zone_code"])
    return zones


# ---------------------------------------------------------------------------
# satisfaction summary (§3.10)
# ---------------------------------------------------------------------------

def satisfaction_summary(event, zone_code=None):
    rows = responses_of_event(event)
    scoped = [r for r in rows if zone_code is None or r["zone_code"] == zone_code]
    scores = [r["score"] for r in scoped]
    average = calc.average_score(scores)
    zones = {}
    for row in scoped:
        zones.setdefault(row["zone_code"], []).append(row["score"])
    breakdown = []
    for zone in sorted(zones):
        zone_scores = zones[zone]
        zone_average = calc.average_score(zone_scores)
        breakdown.append(
            {
                "zone_code": zone,
                "response_count": len(zone_scores),
                "average_score": float(zone_average)
                if zone_average is not None
                else None,
            }
        )
    issues = issues_of_event(event)
    return {
        "response_count": len(scoped),
        "average_score": float(average) if average is not None else None,
        "promoter_share_bp": calc.promoter_share_bp(scores),
        "zone_breakdown": breakdown,
        "resolved_issue_count": sum(
            1 for i in issues if i["status"] in ("RESOLVED", "CLOSED")
        ),
        "sla_breached_issue_count": sum(1 for i in issues if issue_sla_breached(i)),
    }


def event_average_score(event):
    """The unfiltered sentiment average, as an exact Decimal or None."""
    return calc.average_score([r["score"] for r in responses_of_event(event)])


# ---------------------------------------------------------------------------
# staffing model recommendation (§3.10)
# ---------------------------------------------------------------------------

def staffing_recommendation(event):
    plan = plan_in_status(event, ("LOCKED",))
    understaffed = 0
    groups = {}
    if plan is not None:
        plan_slots = slots_of_plan(plan)
        understaffed = sum(
            1 for s in plan_slots if s["status"] == "UNDERSTAFFED_ESCALATED"
        )
        for slot in plan_slots:
            if slot["status"] == "CLOSED":
                continue
            groups.setdefault(slot["position_type_id"], []).append(slot)
    average = event_average_score(event)
    recommendations = []
    keyed = sorted(
        groups.items(), key=lambda item: db.position_types[item[0]]["code"]
    )
    for position_type_id, slots in keyed:
        position_type = db.position_types[position_type_id]
        planned = sum(s["required_headcount"] for s in slots)
        worked = 0
        no_shows = 0
        for slot in slots:
            for assignment in assignments_of_slot(slot):
                if assignment["attendance_status"] == "COMPLETED":
                    worked += 1
                elif assignment["attendance_status"] == "NO_SHOW":
                    no_shows += 1
        rate_bp = calc.fill_rate_bp(worked, planned)
        if rate_bp < calc.FILL_RATE_UPLIFT_FLOOR_BP:
            factor, direction = calc.UPLIFT_FACTOR, "INCREASE"
        elif (
            no_shows == 0
            and understaffed == 0
            and average is not None
            and average >= calc.TRIM_SATISFACTION_FLOOR
        ):
            factor, direction = calc.TRIM_FACTOR, "DECREASE"
        else:
            factor, direction = Decimal("1.00"), "HOLD"
        recommendations.append(
            {
                "position_type_id": position_type_id,
                "code": position_type["code"],
                "planned_headcount": planned,
                "worked_headcount": worked,
                "no_show_count": no_shows,
                "fill_rate_bp": rate_bp,
                "direction": direction,
                "recommended_ratio_per_1000": float(
                    calc.recommended_ratio(
                        position_type["attendance_ratio_per_1000"], factor
                    )
                ),
            }
        )
    return {
        "event_id": event["id"],
        "understaffed_slot_count": understaffed,
        "average_score": float(average) if average is not None else None,
        "position_recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# payout runs (§3.10)
# ---------------------------------------------------------------------------

def gratuity_eligible(assignment):
    slot = slot_of_assignment(assignment)
    position_type = position_type_of_slot(slot)
    member = member_of_assignment(assignment)
    return (
        assignment["payout_status"] == "ACCRUED"
        and position_type["is_tip_eligible"]
        and position_type["is_contracted_position"]
        and member["employment_type"] == "CONTRACTED"
    )


def rank_gratuity_rows(rows):
    return sorted(
        rows,
        key=lambda a: (
            -a["worked_minutes"],
            member_of_assignment(a)["seniority_date"],
            a["created_at"],
        ),
    )


def run_gratuity_allocation(event):
    eligible = rank_gratuity_rows(
        [a for a in assignments_of_event(event) if gratuity_eligible(a)]
    )
    weights = [a["worked_minutes"] for a in eligible]
    pool = event["gratuity_pool_cents"] - event["gratuity_allocated_cents"]
    shares = calc.gratuity_shares(pool, weights)
    if shares is None:
        return []
    for assignment, share in zip(eligible, shares):
        update(
            assignment,
            gratuity_cents=share,
            total_payout_cents=assignment["base_pay_cents"] + share,
            payout_status="GRATUITY_ALLOCATED",
        )
    update(event, gratuity_allocated_cents=event["gratuity_allocated_cents"] + pool)
    return eligible


def run_payroll(event):
    rows = rank_gratuity_rows(
        [
            a
            for a in assignments_of_event(event)
            if a["payout_status"] in ("ACCRUED", "GRATUITY_ALLOCATED")
        ]
    )
    for assignment in rows:
        update(assignment, payout_status="PAID")
    return rows


def slot_computed(plan, position_type, override, shift_start, shift_end):
    """The pinned sizing order of §3.2, as a plain dict of computed fields."""
    ratio = calc.ratio_headcount(
        plan["basis_attendance"],
        position_type["attendance_ratio_per_1000"],
        position_type["min_headcount"],
    )
    required = override if override is not None else ratio
    shift_minutes = minutes_between(shift_start, shift_end)
    return {
        "ratio_derived_headcount": ratio,
        "required_headcount": required,
        "shift_minutes": shift_minutes,
        "slot_labor_cost_cents": calc.slot_labor_cost(
            required, position_type["base_hourly_rate_cents"], shift_minutes
        ),
    }


# ---------------------------------------------------------------------------
# backfill candidate selection (§3.6, calculations.backfill_candidate_selection)
# ---------------------------------------------------------------------------

def backfill_candidates(slot, position_type, excluded_member_id=None):
    """The whole workforce, filtered then ranked; no identifier is consulted."""
    candidates = []
    for member in all_rows("staff_members"):
        if member["status"] != "ACTIVE":
            continue
        if not member["in_backfill_pool"]:
            continue
        if excluded_member_id is not None and member["id"] == excluded_member_id:
            continue
        if missing_certs(member["id"], position_type):
            continue
        if has_live_assignment_on_slot(member["id"], slot):
            continue
        if violates_rest_buffer(member["id"], slot, include_same_slot=False):
            continue
        candidates.append(member)
    candidates.sort(
        key=lambda m: (
            -m["reliability_score"],
            m["seniority_date"],
            m["created_at"],
            m["_seq"],
        )
    )
    return candidates


def open_backfill_request(slot, triggering_assignment):
    from core import new_record

    return new_record(
        "backfill_requests",
        {
            "position_slot_id": slot["id"],
            "triggering_assignment_id": triggering_assignment["id"],
            "filled_assignment_id": None,
            "selected_staff_member_id": None,
            "attempt_count": 0,
            "cancel_reason": None,
            "status": "OPEN",
        },
    )


def backfill_of_filled_assignment(assignment):
    for row in all_rows("backfill_requests"):
        if row["filled_assignment_id"] == assignment["id"]:
            return row
    return None


def elevator_cascade(member, triggering_assignment=None):
    """Links 4 and 5 of the demotion cascade, shared by every ACTIVE -> PROBATION."""
    trigger_id = triggering_assignment["id"] if triggering_assignment else None
    for assignment in assignments_of_member(member):
        if assignment["id"] == trigger_id:
            continue
        if assignment["attendance_status"] != "SCHEDULED":
            continue
        slot = slot_of_assignment(assignment)
        position_type = position_type_of_slot(slot)
        if "ELEVATOR_OPERATION" not in position_type["required_certifications"]:
            continue
        cancel_assignment(assignment)
        recount_slot(slot)


def settle_reliability(member, extra_changes=None, triggering_assignment=None):
    """One update() per member per request: counters, both scores and any demotion."""
    rows = reliability_rows(member)
    changes = dict(extra_changes or {})
    changes["reliability_score"] = calc.reliability_of(
        rows[: calc.ROLLING_WINDOW_SIZE]
    )
    changes["season_reliability_score"] = calc.reliability_of(rows)
    demote = (
        member["status"] == "ACTIVE"
        and changes["reliability_score"] < calc.RELIABILITY_PROBATION_FLOOR
    )
    if demote:
        changes["status"] = "PROBATION"
        changes["in_backfill_pool"] = False
        changes["last_status_reason"] = "AUTO_PROBATION_RELIABILITY"
    update(member, **changes)
    if demote:
        elevator_cascade(member, triggering_assignment)
