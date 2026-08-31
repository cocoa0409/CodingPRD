"""Lookups, derived counters, the segment posture gate and every cascade."""

import calc
import store
from errors import fail
from store import ordered, touch

SEGMENT_BLOCKING_POSTURES = ("SEASONAL_CLOSED", "INCIDENT_CLOSED")
PARTY_ACTIVE_SCHEDULES = ("PLANNED", "CONFIRMED")
SHIFT_REGISTERED_COUNT_STATUSES = ("REGISTERED", "CHECKED_IN", "CHECKED_OUT",
                                   "HOURS_DISPUTED", "HOURS_VERIFIED", "HOURS_CERTIFIED")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def _get(collection, entity_id, error_id):
    row = collection.get(entity_id) if isinstance(entity_id, str) else None
    if row is None:
        fail(error_id, "Resource %s was not found." % entity_id)
    return row


def get_land_manager(entity_id):
    return _get(store.land_managers, entity_id, "ERR_LAND_MANAGER_NOT_FOUND")


def get_volunteer(entity_id):
    return _get(store.volunteers, entity_id, "ERR_VOLUNTEER_NOT_FOUND")


def get_segment(entity_id):
    return _get(store.segments, entity_id, "ERR_TRAIL_SEGMENT_NOT_FOUND")


def get_agreement(entity_id):
    return _get(store.agreements, entity_id, "ERR_AGREEMENT_NOT_FOUND")


def get_plan(entity_id):
    return _get(store.plans, entity_id, "ERR_WORK_PLAN_NOT_FOUND")


def get_report(entity_id):
    return _get(store.reports, entity_id, "ERR_CONDITION_REPORT_NOT_FOUND")


def get_permit(entity_id):
    return _get(store.permits, entity_id, "ERR_PERMIT_NOT_FOUND")


def get_party(entity_id):
    return _get(store.parties, entity_id, "ERR_WORK_PARTY_NOT_FOUND")


def get_shift(entity_id):
    return _get(store.shifts, entity_id, "ERR_SHIFT_NOT_FOUND")


def get_order(entity_id):
    return _get(store.orders, entity_id, "ERR_MATERIAL_ORDER_NOT_FOUND")


def get_incident(entity_id):
    return _get(store.incidents, entity_id, "ERR_INCIDENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# relationship walks
# ---------------------------------------------------------------------------
def segment_manager(segment):
    return store.land_managers.get(segment["land_manager_id"])


def plan_agreement(plan):
    return store.agreements.get(plan["adoption_agreement_id"])


def plan_segment(plan):
    agreement = plan_agreement(plan)
    return store.segments.get(agreement["trail_segment_id"]) if agreement else None


def party_plan(party):
    return store.plans.get(party["work_plan_id"])


def party_agreement(party):
    plan = party_plan(party)
    return plan_agreement(plan) if plan else None


def party_segment(party):
    return store.segments.get(party["trail_segment_id"])


def party_manager(party):
    segment = party_segment(party)
    return segment_manager(segment) if segment else None


def party_permit(party):
    return store.permits.get(party["work_permit_id"]) if party.get("work_permit_id") else None


def plans_of_agreement(agreement):
    return ordered([p for p in store.plans.values()
                    if p["adoption_agreement_id"] == agreement["id"]])


def parties_of_agreement(agreement):
    plan_ids = {p["id"] for p in store.plans.values()
                if p["adoption_agreement_id"] == agreement["id"]}
    return ordered([w for w in store.parties.values() if w["work_plan_id"] in plan_ids])


def parties_of_plan(plan):
    return ordered([w for w in store.parties.values() if w["work_plan_id"] == plan["id"]])


def parties_of_segment(segment):
    return ordered([w for w in store.parties.values()
                    if w["trail_segment_id"] == segment["id"]])


def parties_of_permit(permit):
    return ordered([w for w in store.parties.values()
                    if w.get("work_permit_id") == permit["id"]])


def shifts_of_party(party):
    return ordered([s for s in store.shifts.values() if s["work_party_id"] == party["id"]])


def shifts_of_volunteer(volunteer_id):
    return ordered([s for s in store.shifts.values() if s["volunteer_id"] == volunteer_id])


def agreements_of_segment(segment):
    return ordered([a for a in store.agreements.values()
                    if a["trail_segment_id"] == segment["id"]])


def reports_of_segment(segment):
    return ordered([r for r in store.reports.values()
                    if r["trail_segment_id"] == segment["id"]])


def orders_of_plan(plan):
    return ordered([o for o in store.orders.values() if o["work_plan_id"] == plan["id"]])


def incidents_of_segment(segment):
    return ordered([i for i in store.incidents.values()
                    if i["trail_segment_id"] == segment["id"]])


# ---------------------------------------------------------------------------
# derived counters (pure functions of stored rows; never bump version)
# ---------------------------------------------------------------------------
def refresh_party(party):
    rows = shifts_of_party(party)
    party["registered_count"] = sum(
        1 for s in rows if s["status"] in SHIFT_REGISTERED_COUNT_STATUSES)
    party["checked_in_count"] = sum(1 for s in rows if s["status"] == "CHECKED_IN")
    party["first_aid_capable_count"] = sum(
        1 for s in rows if s["status"] in ("REGISTERED", "CHECKED_IN")
        and volunteer_first_aid_current(store.volunteers.get(s["volunteer_id"])))
    party["linked_report_count"] = sum(
        1 for r in store.reports.values()
        if r.get("linked_work_party_id") == party["id"] and r["status"] == "SCHEDULED")
    party["roster_capacity"] = compute_roster_capacity(party)
    return party


def compute_roster_capacity(party):
    permit = party_permit(party)
    if permit and permit["status"] == "ISSUED" and permit.get("max_party_size") is not None:
        return min(int(party["max_participants"]), int(permit["max_party_size"]))
    return int(party["max_participants"])


def volunteer_first_aid_current(volunteer):
    if not volunteer:
        return False
    certs = set(volunteer.get("certifications") or [])
    if not certs & set(calc.FIRST_AID_CERTS):
        return False
    expires = store.parse_date(volunteer.get("first_aid_expires_on"))
    if expires is None:
        return False
    return expires >= store.clock_date()


def refresh_permit(permit):
    permit["consumed_party_count"] = sum(
        1 for w in store.parties.values()
        if w.get("work_permit_id") == permit["id"] and w["schedule_status"] == "COMPLETED")
    return permit


def refresh_manager(manager):
    manager["adopted_segment_count"] = sum(
        1 for s in store.segments.values()
        if s["land_manager_id"] == manager["id"] and s["adoption_status"] == "ADOPTED")
    return manager


def waiver_current(volunteer, on_date=None):
    if not volunteer or not volunteer.get("waiver_signed_on"):
        return False
    expires = store.parse_date(volunteer.get("waiver_expires_on"))
    if expires is None:
        return False
    return expires >= (on_date or store.clock_date())


# ---------------------------------------------------------------------------
# segment posture (PRD 2.6)
# ---------------------------------------------------------------------------
def _in_seasonal_window(segment):
    start = segment.get("seasonal_closure_start_mmdd")
    end = segment.get("seasonal_closure_end_mmdd")
    if not start:
        return False
    if not end:
        end = start
    current = store.clock_date().strftime("%m-%d")
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _wet_clause(segment):
    index = segment.get("latest_soil_moisture_index")
    observed = store.parse_dt(segment.get("latest_moisture_observed_at"))
    if index is None or observed is None:
        return False
    manager = segment_manager(segment)
    threshold = manager["wet_threshold_index"] if manager else 0.65
    if float(index) < float(threshold):
        return False
    return store.hours_between(observed, store.now()) < calc.MOISTURE_FRESH_HOURS


def compute_posture(segment):
    if int(segment.get("open_severe_incident_count") or 0) >= 1:
        return "INCIDENT_CLOSED"
    if _in_seasonal_window(segment):
        return "SEASONAL_CLOSED"
    if _wet_clause(segment):
        return "WET_RESTRICTED"
    if int(segment.get("hazard_index") or 0) >= calc.HAZARD_RESTRICT_THRESHOLD:
        return "HAZARD_RESTRICTED"
    return "OPEN"


def posture_allows_work_type(posture, work_type):
    """Clause 2 of the clearance predicate / the confirm-and-start restriction."""
    if posture in SEGMENT_BLOCKING_POSTURES:
        return False
    if posture == "WET_RESTRICTED":
        return work_type in calc.WET_ALLOWED_WORK_TYPES
    if posture == "HAZARD_RESTRICTED":
        return work_type != "CHAINSAW"
    return True


def settle_segment(segment, recompute_hazard=False, force_touch=False, blocked=None):
    """Recompute hazard/posture, bump the segment once, and run posture cascades."""
    changed = bool(force_touch)
    if recompute_hazard:
        included = [r for r in reports_of_segment(segment)
                    if r["status"] in calc.HAZARD_INCLUDED_STATUSES]
        index, escalated = calc.hazard_index(included)
        if segment["hazard_index"] != index or segment["escalated_hazard_count"] != escalated:
            segment["hazard_index"] = index
            segment["escalated_hazard_count"] = escalated
            changed = True
    previous = segment["posture"]
    current = compute_posture(segment)
    posture_changed = current != previous
    if posture_changed:
        segment["posture"] = current
        changed = True
    if changed:
        touch(segment)
    if posture_changed:
        _posture_cascade(segment, previous, current, blocked)
    return posture_changed


def _posture_cascade(segment, previous, current, blocked=None):
    if current == "INCIDENT_CLOSED":
        for agreement in agreements_of_segment(segment):
            if agreement["status"] == "ACTIVE":
                suspend_agreement(agreement, "SEGMENT_INCIDENT", blocked)
    elif current == "SEASONAL_CLOSED":
        for party in parties_of_segment(segment):
            if party["schedule_status"] in PARTY_ACTIVE_SCHEDULES:
                block_party(party, "SEGMENT_CLOSED", blocked)
    elif current == "WET_RESTRICTED":
        for party in parties_of_segment(segment):
            if (party["schedule_status"] in PARTY_ACTIVE_SCHEDULES
                    and party["work_type"] not in calc.WET_ALLOWED_WORK_TYPES):
                block_party(party, "SEGMENT_CLOSED", blocked)
    elif current == "HAZARD_RESTRICTED":
        for party in parties_of_segment(segment):
            if party["schedule_status"] == "PLANNED" and party["work_type"] == "CHAINSAW":
                block_party(party, "SEGMENT_CLOSED", blocked)

    if previous == "INCIDENT_CLOSED" and current != "INCIDENT_CLOSED":
        for agreement in agreements_of_segment(segment):
            if (agreement["status"] == "SUSPENDED"
                    and agreement.get("suspension_reason") == "SEGMENT_INCIDENT"):
                resume_agreement(agreement)


def recompute_severe_incidents(segment):
    segment["open_severe_incident_count"] = sum(
        1 for i in incidents_of_segment(segment)
        if i["severity_class"] == "SEVERE" and i["status"] in ("OPEN", "UNDER_REVIEW"))


# ---------------------------------------------------------------------------
# work-party readiness (PRD 3.6)
# ---------------------------------------------------------------------------
def block_party(party, reason, blocked=None):
    if party["readiness_status"] == "BLOCKED" and party.get("block_reason") == reason:
        return False
    party["readiness_status"] = "BLOCKED"
    party["block_reason"] = reason
    touch(party)
    if blocked is not None:
        blocked.add(party["id"])
    return True


def clearance_holds(party):
    manager = party_manager(party)
    segment = party_segment(party)
    agreement = party_agreement(party)
    if manager is None or segment is None or agreement is None:
        return False
    if manager["permit_required"]:
        permit = party_permit(party)
        if permit is None or permit["status"] != "ISSUED":
            return False
        if party["work_type"] not in (permit.get("allowed_work_types") or []):
            return False
        if not party_dates_inside_permit(party, permit):
            return False
    if not posture_allows_work_type(segment["posture"], party["work_type"]):
        return False
    return agreement["status"] == "ACTIVE"


def party_dates_inside_permit(party, permit):
    start = store.parse_dt(party["start_at"]).date()
    end = store.parse_dt(party["end_at"]).date()
    window_start = store.parse_date(permit["window_start_date"])
    window_end = store.parse_date(permit["window_end_date"])
    return window_start <= start <= window_end and window_start <= end <= window_end


def blocking_cause(party):
    """The blocking causes named in PRD 3.6, in declaration order."""
    manager = party_manager(party)
    permit = party_permit(party)
    if permit is not None:
        if permit["status"] in ("REVOKED", "DENIED"):
            return "PERMIT_REVOKED"
        if permit["status"] == "EXPIRED":
            return "PERMIT_EXPIRED"
    segment = party_segment(party)
    if segment is not None and not posture_allows_work_type(segment["posture"], party["work_type"]):
        return "SEGMENT_CLOSED"
    agreement = party_agreement(party)
    if agreement is not None and agreement["status"] == "SUSPENDED":
        return "AGREEMENT_SUSPENDED"
    if manager is None:
        return None
    return None


def try_clear(party):
    if party["readiness_status"] == "BRIEFED" and clearance_holds(party):
        party["readiness_status"] = "CLEARED"
        touch(party)
        return True
    return False


# ---------------------------------------------------------------------------
# agreement suspension cascade (PRD 2.10 / 3.2)
# ---------------------------------------------------------------------------
def agreement_suspension_causes(agreement):
    causes = []
    segment = store.segments.get(agreement["trail_segment_id"])
    if segment is not None and segment["posture"] == "INCIDENT_CLOSED":
        causes.append("SEGMENT_INCIDENT")
    for plan in plans_of_agreement(agreement):
        if plan["budget_posture"] == "OVER_COMMITTED":
            causes.append("BUDGET_OVER_COMMIT")
            break
    return causes


def suspend_agreement(agreement, reason, blocked=None):
    if agreement["status"] != "ACTIVE":
        return False
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = reason
    touch(agreement)
    for party in parties_of_agreement(agreement):
        if party["schedule_status"] == "CONFIRMED":
            party["schedule_status"] = "SUSPENDED"
            party["readiness_status"] = "BLOCKED"
            party["block_reason"] = "AGREEMENT_SUSPENDED"
            touch(party)
            if blocked is not None:
                blocked.add(party["id"])
            withdraw_registered_shifts(party)
        elif party["schedule_status"] == "PLANNED":
            block_party(party, "AGREEMENT_SUSPENDED", blocked)
    return True


def resume_agreement(agreement):
    if agreement["status"] != "SUSPENDED":
        return False
    if agreement_suspension_causes(agreement):
        return False
    agreement["status"] = "ACTIVE"
    agreement["suspension_reason"] = None
    touch(agreement)
    for party in parties_of_agreement(agreement):
        if party.get("block_reason") != "AGREEMENT_SUSPENDED":
            continue
        party["readiness_status"] = "BRIEFED"
        party["block_reason"] = None
        if party["schedule_status"] == "SUSPENDED":
            manager = party_manager(party)
            permit = party_permit(party)
            permit_ok = (manager is not None and not manager["permit_required"]) or (
                permit is not None and permit["status"] == "ISSUED")
            if permit_ok:
                party["schedule_status"] = "CONFIRMED"
        touch(party)
    return True


def withdraw_registered_shifts(party):
    for shift in shifts_of_party(party):
        if shift["status"] != "REGISTERED":
            continue
        shift["status"] = "WITHDRAWN"
        touch(shift)
        volunteer = store.volunteers.get(shift["volunteer_id"])
        if volunteer is not None:
            volunteer["active_registration_count"] = max(
                0, int(volunteer["active_registration_count"]) - 1)
            touch(volunteer)


# ---------------------------------------------------------------------------
# work-plan budget ledger (PRD 3.3)
# ---------------------------------------------------------------------------
def recompute_ledger(plan):
    rows = orders_of_plan(plan)
    committed = sum(o["total_cents"] for o in rows
                    if o["status"] in ("DRAFT", "SUBMITTED", "APPROVED"))
    spent = sum(o["total_cents"] for o in rows if o["status"] == "DELIVERED")
    plan["committed_cents"] = committed
    plan["spent_cents"] = spent
    plan["available_cents"] = int(plan["approved_budget_cents"]) - committed - spent
    plan["budget_posture"] = calc.budget_posture(plan["available_cents"],
                                                 int(plan["approved_budget_cents"]))
    return plan["budget_posture"]


def propagate_budget(plan):
    """Drive the adoption suspend/resume cascade off the plan's budget posture."""
    agreement = plan_agreement(plan)
    if agreement is None:
        return
    if plan["budget_posture"] == "OVER_COMMITTED":
        if agreement["status"] == "ACTIVE":
            suspend_agreement(agreement, "BUDGET_OVER_COMMIT")
    else:
        if (agreement["status"] == "SUSPENDED"
                and agreement.get("suspension_reason") == "BUDGET_OVER_COMMIT"):
            resume_agreement(agreement)


# ---------------------------------------------------------------------------
# permit lifecycle helpers
# ---------------------------------------------------------------------------
def consume_permit_if_done(permit):
    refresh_permit(permit)
    if permit["status"] != "ISSUED":
        return False
    if permit["consumed_party_count"] < 1:
        return False
    for party in parties_of_permit(permit):
        if party["schedule_status"] in ("PLANNED", "CONFIRMED", "IN_PROGRESS"):
            return False
    permit["status"] = "CONSUMED"
    touch(permit)
    return True


def block_parties_for_permit(permit, reason, suspend_confirmed=False, blocked=None):
    for party in parties_of_permit(permit):
        if party["schedule_status"] not in PARTY_ACTIVE_SCHEDULES:
            continue
        was_confirmed = party["schedule_status"] == "CONFIRMED"
        moved = block_party(party, reason, blocked)
        if suspend_confirmed and was_confirmed:
            party["schedule_status"] = "SUSPENDED"
            if not moved:
                touch(party)
            withdraw_registered_shifts(party)


# ---------------------------------------------------------------------------
# volunteer hour buckets (INV_HOURS)
# ---------------------------------------------------------------------------
def move_hours(volunteer, **deltas):
    for bucket, delta in deltas.items():
        volunteer[bucket] = calc.add_hours(volunteer[bucket], delta)
    touch(volunteer)


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def s_manager(manager):
    refresh_manager(manager)
    return store.public(manager)


def s_volunteer(volunteer):
    volunteer["active_registration_count"] = sum(
        1 for s in store.shifts.values()
        if s["volunteer_id"] == volunteer["id"] and s["status"] in ("REGISTERED", "CHECKED_IN"))
    return store.public(volunteer)


def s_segment(segment):
    return store.public(segment)


def s_agreement(agreement):
    return store.public(agreement)


def s_plan(plan):
    return store.public(plan)


def s_report(report):
    return store.public(report)


def s_permit(permit):
    refresh_permit(permit)
    return store.public(permit)


def s_party(party):
    refresh_party(party)
    return store.public(party)


def s_shift(shift):
    return store.public(shift)


def s_order(order):
    return store.public(order)


def s_incident(incident):
    return store.public(incident)
