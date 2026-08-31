"""Multi-step cascades.  Each cascade is atomic with its trigger and every
record it touches gets a fresh updated_at and a version increment."""

from core import calc
from core.store import store
from services import derive


# ------------------------------------------------------------ grant money
def _award_of(alloc):
    return store.get("GrantAward", alloc["grant_award_id"])


def release_allocation(alloc):
    alloc["status"] = "RELEASED"
    alloc["settled_cents"] = None
    store.touch(alloc)
    award = _award_of(alloc)
    if award is not None:
        derive.recompute_award(award)
        store.touch(award)


def release_allocations_for_cohort(cohort):
    for alloc in store.find("FundingAllocation", cohort_id=cohort["id"]):
        if alloc["status"] == "COMMITTED":
            release_allocation(alloc)


def release_allocations_for_event(event):
    for alloc in store.find("FundingAllocation", event_id=event["id"]):
        if alloc["status"] == "COMMITTED":
            release_allocation(alloc)


def settled_cents_for_cohort(cohort):
    attended_units = 0
    for enr in derive.cohort_enrollments(cohort["id"]):
        if enr["status"] in ("COMPLETED", "WITHDRAWN"):
            attended_units += enr["sessions_attended"]
    denominator = cohort["seats_total"] * cohort["sessions_total"]
    return calc.money(calc.dec(cohort["program_cost_total_cents"]) * calc.dec(attended_units)
                      / calc.dec(denominator))


def settled_cents_for_event(event):
    ratio = calc.dec(event["confirmed_headcount"]) / calc.dec(event["expected_attendance"])
    if ratio > 1:
        ratio = calc.dec(1)
    return calc.money(calc.dec(event["program_cost_total_cents"]) * ratio)


def settle_allocation(alloc, settled_cents, basis):
    alloc["status"] = "SETTLED"
    alloc["settled_cents"] = settled_cents
    alloc["basis"] = basis
    alloc["settled_at"] = store.now_iso()
    store.touch(alloc)
    award = _award_of(alloc)
    if award is not None:
        derive.recompute_award(award)
        store.touch(award)


def settle_allocations_for_cohort(cohort):
    amount = settled_cents_for_cohort(cohort)
    for alloc in store.find("FundingAllocation", cohort_id=cohort["id"]):
        if alloc["status"] == "COMMITTED":
            settle_allocation(alloc, amount, "ACTUAL_ATTENDANCE")


def settle_allocations_for_event(event):
    amount = settled_cents_for_event(event)
    for alloc in store.find("FundingAllocation", event_id=event["id"]):
        if alloc["status"] == "COMMITTED":
            settle_allocation(alloc, amount, "CONFIRMED_HEADCOUNT")


# ----------------------------------------------------------------- cohorts
def suspend_cohort(cohort):
    """RUNNING -> SUSPENDED, releasing every COMMITTED allocation on it."""
    cohort["status"] = "SUSPENDED"
    release_allocations_for_cohort(cohort)
    store.touch(cohort)


def seat_released(cohort):
    """Recompute seats after an enrollment left a live compartment; may suspend."""
    was_running = cohort["status"] == "RUNNING"
    derive.recompute_seats(cohort)
    store.touch(cohort)
    if was_running and cohort["seats_filled"] < cohort["min_viable_enrollment"]:
        suspend_cohort(cohort)


# ------------------------------------------------------------- volunteers
def end_match(match, end_reason):
    match["status"] = "ENDED"
    match["ended_on"] = store.today().isoformat()
    match["end_reason"] = end_reason
    store.touch(match)
    volunteer = store.get("VolunteerCompanion", match["companion_id"])
    if volunteer is not None:
        derive.recompute_volunteer(volunteer)
        store.touch(volunteer)
    participant = store.get("Participant", match["participant_id"])
    if participant is not None:
        before = participant["has_active_companion"]
        derive.recompute_has_active_companion(participant)
        if participant["has_active_companion"] != before:
            store.touch(participant)


def lapse_volunteer(volunteer):
    """CERTIFIED -> LAPSED with every ACTIVE match ended.  Returns matches ended."""
    volunteer["status"] = "LAPSED"
    ended = 0
    for match in store.find("CompanionMatch", companion_id=volunteer["id"]):
        if match["status"] == "ACTIVE":
            end_match(match, "COMPANION_LAPSED")
            ended += 1
    derive.recompute_volunteer(volunteer)
    store.touch(volunteer)
    return ended


# ----------------------------------------------------------- counselling
def cancel_counseling_referral(referral):
    was_assigned = referral["status"] == "ASSIGNED"
    counselor_id = referral.get("counselor_id")
    referral["status"] = "CANCELLED"
    referral["close_reason"] = "PARTICIPANT_WITHDRAWN"
    store.touch(referral)
    if was_assigned and counselor_id:
        counselor = store.get("Counselor", counselor_id)
        if counselor is not None:
            derive.recompute_counselor(counselor)
            store.touch(counselor)


# ------------------------------------------------------------ withdrawal
def withdraw_participant(participant):
    participant["service_status"] = "WITHDRAWN"
    participant["outreach_status"] = "CLOSED"
    store.touch(participant)

    for enr in store.find("Enrollment", participant_id=participant["id"]):
        if enr["status"] in ("HELD", "CONFIRMED", "ATTENDING"):
            enr["status"] = "WITHDRAWN"
            enr["withdraw_reason"] = "PARTICIPANT_REQUEST"
            store.touch(enr)
            cohort = store.get("Cohort", enr["cohort_id"])
            if cohort is not None:
                seat_released(cohort)

    for ref in store.find("CounselingReferral", participant_id=participant["id"]):
        if ref["status"] in ("WAITLISTED", "ASSIGNED"):
            cancel_counseling_referral(ref)

    for match in store.find("CompanionMatch", participant_id=participant["id"]):
        if match["status"] == "PROPOSED":
            match["status"] = "DECLINED"
            store.touch(match)
        elif match["status"] == "ACTIVE":
            end_match(match, "PARTICIPANT_WITHDRAWN")

    for row in store.find("AnniversaryOutreach", participant_id=participant["id"]):
        if row["status"] in ("SCHEDULED", "DUE", "SENT"):
            row["status"] = "CANCELLED"
            store.touch(row)

    derive.recompute_has_active_companion(participant)
