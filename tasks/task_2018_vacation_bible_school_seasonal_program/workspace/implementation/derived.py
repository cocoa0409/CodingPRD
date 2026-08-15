"""Derived fields, computed from source rows at read time (PRD §2.10, §3).

Nothing here is cached; every serializer recomputes its derived fields from the
live store so reads are immediately consistent with prior mutations.
"""

import store
from util import ceil_div, fmt_dt, fmt_date

CHILD_FACING_ROLES = {"LEAD_TEACHER", "ASSISTANT_TEACHER"}
REQUIRED_CHECK_TYPES = {"BACKGROUND", "REFERENCE", "SAFE_MINISTRY_TRAINING"}


# ---------------------------------------------------------------- registrations

def regs_of_classroom(classroom_id):
    return [r for r in store.all_of("registrations") if r["classroom_id"] == classroom_id]


def regs_of_child(child_id):
    return [r for r in store.all_of("registrations") if r["child_id"] == child_id]


def enrolled_count(classroom):
    return sum(1 for r in regs_of_classroom(classroom["id"]) if r["status"] == "ENROLLED")


def offered_count(classroom):
    return sum(1 for r in regs_of_classroom(classroom["id"]) if r["status"] == "OFFERED")


def waitlist_count(classroom):
    return sum(1 for r in regs_of_classroom(classroom["id"]) if r["status"] == "WAITLISTED")


def open_seats(classroom):
    return classroom["capacity"] - enrolled_count(classroom) - offered_count(classroom)


def waitlist_position(reg):
    """1-based dense rank among the classroom's WAITLISTED, created_at ASC."""
    if reg["status"] != "WAITLISTED":
        return None
    queue = store.by_seq(
        r
        for r in regs_of_classroom(reg["classroom_id"])
        if r["status"] == "WAITLISTED"
    )
    for idx, item in enumerate(queue, start=1):
        if item["id"] == reg["id"]:
            return idx
    return None


# ---------------------------------------------------------------- programs

def classrooms_of_program(program_id):
    return [c for c in store.all_of("classrooms") if c["program_id"] == program_id]


def days_of_program(program_id):
    return [d for d in store.all_of("program_days") if d["program_id"] == program_id]


def volunteers_of_program(program_id):
    return [v for v in store.all_of("volunteers") if v["program_id"] == program_id]


def enrolled_total(program):
    total = 0
    for c in classrooms_of_program(program["id"]):
        if c["status"] == "CLOSED":
            continue
        total += enrolled_count(c)
    return total


def waitlist_total(program):
    total = 0
    for c in classrooms_of_program(program["id"]):
        total += waitlist_count(c)
    return total


def budget_remaining_cents(program):
    spent = sum(
        o["quantity"] * o["unit_cost_cents"]
        for o in store.all_of("supply_orders")
        if o["program_id"] == program["id"] and o["status"] == "APPROVED"
    )
    return program["supply_budget_cents"] - spent


def kit_base(program):
    """ceil(enrolled_total * 1.10) in exact integer arithmetic."""
    n = enrolled_total(program)
    return ceil_div(n * 11, 10)


def non_closed_classrooms(program):
    return [c for c in classrooms_of_program(program["id"]) if c["status"] != "CLOSED"]


def kit_required_final(program):
    return kit_base(program) + len(non_closed_classrooms(program))


def craft_packs_for_classroom(classroom):
    """ceil(enrolled_count * 3 / 10) — per-classroom ceil, pinned before summing."""
    return ceil_div(enrolled_count(classroom) * 3, 10)


# ---------------------------------------------------------------- staffing

def required_adults(classroom):
    n = enrolled_count(classroom)
    if n == 0:
        return 0
    program = store.get("programs", classroom["program_id"])
    ratio = program["child_staff_ratio"]
    return max(2, ceil_div(n, ratio))


def confirmed_adult_count(classroom):
    count = 0
    for ra in store.all_of("role_assignments"):
        if ra["classroom_id"] != classroom["id"]:
            continue
        if ra["status"] != "CONFIRMED" or ra["role"] not in CHILD_FACING_ROLES:
            continue
        vol = store.get("volunteers", ra["volunteer_id"])
        if vol is None:
            continue
        if vol["status"] == "CLEARED" and not vol["is_minor"]:
            count += 1
    return count


def staffing_status(classroom):
    req = required_adults(classroom)
    conf = confirmed_adult_count(classroom)
    if req == 0 or conf >= req:
        return "ADEQUATE"
    if conf == 0:
        return "UNSTAFFED"
    return "UNDERSTAFFED"


# ---------------------------------------------------------------- allergies

def blocked_allergens(classroom_id):
    """Union of allergens over APPROVED FOOD_ALLERGY plans of ENROLLED children."""
    enrolled_child_ids = {
        r["child_id"]
        for r in regs_of_classroom(classroom_id)
        if r["status"] == "ENROLLED"
    }
    blocked = set()
    for plan in store.all_of("accommodation_plans"):
        if (
            plan["child_id"] in enrolled_child_ids
            and plan["status"] == "APPROVED"
            and plan["severity"] == "FOOD_ALLERGY"
        ):
            blocked.update(plan.get("allergens") or [])
    return blocked


def child_has_approved_plan(child_id):
    return any(
        p["child_id"] == child_id and p["status"] == "APPROVED"
        for p in store.all_of("accommodation_plans")
    )


# ---------------------------------------------------------------- supply items

def reserved_quantity(item):
    return sum(
        d["quantity"]
        for d in store.all_of("supply_distributions")
        if d["supply_item_id"] == item["id"] and d["status"] == "PLANNED"
    )


# ---------------------------------------------------------------- attendance

def records_of_day(program_day_id):
    return [r for r in store.all_of("attendance_records") if r["program_day_id"] == program_day_id]


def record_for(child_id, program_day_id):
    for r in store.all_of("attendance_records"):
        if r["child_id"] == child_id and r["program_day_id"] == program_day_id:
            return r
    return None


def tags_of_day(program_day_id):
    return [t for t in store.all_of("security_tags") if t["program_day_id"] == program_day_id]


def next_tag_code(program_day_id):
    """Deterministic per-day issuance sequence, zero-padded, from 000001."""
    return "%06d" % (len(tags_of_day(program_day_id)) + 1)


def attended_days(program_id, child_id):
    day_ids = {d["id"] for d in days_of_program(program_id)}
    return sum(
        1
        for r in store.all_of("attendance_records")
        if r["child_id"] == child_id
        and r["program_day_id"] in day_ids
        and r["status"] == "CHECKED_OUT"
    )


# ---------------------------------------------------------------- serializers

def program_view(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "program_year": p["program_year"],
        "start_date": fmt_date(p["start_date"]),
        "end_date": fmt_date(p["end_date"]),
        "registration_opens_at": fmt_dt(p["registration_opens_at"]),
        "registration_closes_at": fmt_dt(p["registration_closes_at"]),
        "supply_budget_cents": p["supply_budget_cents"],
        "child_staff_ratio": p["child_staff_ratio"],
        "waitlist_offer_ttl_hours": p["waitlist_offer_ttl_hours"],
        "pickup_cutoff_time": p["pickup_cutoff_time"].strftime("%H:%M"),
        "status": p["status"],
        "current_day_index": p["current_day_index"],
        "enrolled_total": enrolled_total(p),
        "waitlist_total": waitlist_total(p),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def classroom_view(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "name": c["name"],
        "age_min": c["age_min"],
        "age_max": c["age_max"],
        "capacity": c["capacity"],
        "status": c["status"],
        "enrolled_count": enrolled_count(c),
        "offered_count": offered_count(c),
        "waitlist_count": waitlist_count(c),
        "open_seats": open_seats(c),
        "required_adults": required_adults(c),
        "confirmed_adult_count": confirmed_adult_count(c),
        "staffing_status": staffing_status(c),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def family_view(f):
    return {
        "id": f["id"],
        "household_name": f["household_name"],
        "primary_contact_name": f["primary_contact_name"],
        "email": f["email"],
        "phone": f["phone"],
        "preferred_contact": f["preferred_contact"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def child_view(ch):
    return {
        "id": ch["id"],
        "family_id": ch["family_id"],
        "first_name": ch["first_name"],
        "last_name": ch["last_name"],
        "birth_date": fmt_date(ch["birth_date"]),
        "grade_completed": ch["grade_completed"],
        "has_special_needs": ch["has_special_needs"],
        "allergy_summary": ch["allergy_summary"],
        "created_at": ch["created_at"],
        "updated_at": ch["updated_at"],
        "version": ch["version"],
    }


def registration_view(r):
    return {
        "id": r["id"],
        "child_id": r["child_id"],
        "classroom_id": r["classroom_id"],
        "status": r["status"],
        "age_at_registration": r["age_at_registration"],
        "waitlist_position": waitlist_position(r),
        "offer_expires_at": fmt_dt(r["offer_expires_at"]),
        "enrolled_at": fmt_dt(r["enrolled_at"]),
        "cancellation_reason": r["cancellation_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def volunteer_view(v):
    return {
        "id": v["id"],
        "program_id": v["program_id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "phone": v["phone"],
        "birth_date": fmt_date(v["birth_date"]),
        "family_id": v["family_id"],
        "is_minor": v["is_minor"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def screening_check_view(sc):
    return {
        "id": sc["id"],
        "volunteer_id": sc["volunteer_id"],
        "check_type": sc["check_type"],
        "status": sc["status"],
        "decision_notes": sc["decision_notes"],
        "response_notes": sc["response_notes"],
        "resubmission_count": sc["resubmission_count"],
        "reviewer_id": sc["reviewer_id"],
        "decided_at": fmt_dt(sc["decided_at"]),
        "created_at": sc["created_at"],
        "updated_at": sc["updated_at"],
        "version": sc["version"],
    }


def role_assignment_view(ra):
    return {
        "id": ra["id"],
        "volunteer_id": ra["volunteer_id"],
        "classroom_id": ra["classroom_id"],
        "role": ra["role"],
        "status": ra["status"],
        "confirmed_at": fmt_dt(ra["confirmed_at"]),
        "released_at": fmt_dt(ra["released_at"]),
        "created_at": ra["created_at"],
        "updated_at": ra["updated_at"],
        "version": ra["version"],
    }


def plan_view(p):
    return {
        "id": p["id"],
        "child_id": p["child_id"],
        "severity": p["severity"],
        "allergens": p["allergens"],
        "instructions": p["instructions"],
        "requires_epinephrine": p["requires_epinephrine"],
        "status": p["status"],
        "revision_notes": p["revision_notes"],
        "reviewed_by": p["reviewed_by"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def supply_order_view(o):
    program = store.get("programs", o["program_id"])
    return {
        "id": o["id"],
        "program_id": o["program_id"],
        "kit_name": o["kit_name"],
        "vendor": o["vendor"],
        "quantity": o["quantity"],
        "unit_cost_cents": o["unit_cost_cents"],
        "status": o["status"],
        "total_cost_cents": o["quantity"] * o["unit_cost_cents"],
        "recommended_provisional": kit_base(program) if program else 0,
        "required_final": kit_required_final(program) if program else 0,
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def supply_item_view(item):
    reserved = reserved_quantity(item)
    return {
        "id": item["id"],
        "program_id": item["program_id"],
        "name": item["name"],
        "category": item["category"],
        "unit": item["unit"],
        "quantity_on_hand": item["quantity_on_hand"],
        "reserved_quantity": reserved,
        "available_quantity": item["quantity_on_hand"] - reserved,
        "allergen_tags": list(item["allergen_tags"]),
        "restock_threshold": item["restock_threshold"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "version": item["version"],
    }


def distribution_view(d):
    return {
        "id": d["id"],
        "supply_item_id": d["supply_item_id"],
        "classroom_id": d["classroom_id"],
        "program_day_id": d["program_day_id"],
        "quantity": d["quantity"],
        "status": d["status"],
        "issued_at": fmt_dt(d["issued_at"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def program_day_view(d):
    recs = records_of_day(d["id"])
    return {
        "id": d["id"],
        "program_id": d["program_id"],
        "day_index": d["day_index"],
        "date": fmt_date(d["date"]),
        "status": d["status"],
        "checked_in_count": sum(1 for r in recs if r["status"] in ("CHECKED_IN", "CHECKED_OUT")),
        "checked_out_count": sum(1 for r in recs if r["status"] == "CHECKED_OUT"),
        "absent_count": sum(1 for r in recs if r["status"] == "ABSENT"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def security_tag_view(t):
    return {
        "id": t["id"],
        "child_id": t["child_id"],
        "program_day_id": t["program_day_id"],
        "tag_code": t["tag_code"],
        "status": t["status"],
        "void_reason": t["void_reason"],
        "issued_at": fmt_dt(t["issued_at"]),
        "redeemed_at": fmt_dt(t["redeemed_at"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def attendance_view(r):
    return {
        "id": r["id"],
        "child_id": r["child_id"],
        "program_day_id": r["program_day_id"],
        "registration_id": r["registration_id"],
        "status": r["status"],
        "tag_code": r["tag_code"],
        "checked_in_at": fmt_dt(r["checked_in_at"]),
        "checked_out_at": fmt_dt(r["checked_out_at"]),
        "checked_in_by": r["checked_in_by"],
        "checked_out_by": r["checked_out_by"],
        "pickup_person": r["pickup_person"],
        "late_pickup": r["late_pickup"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def message_view(m):
    return {
        "id": m["id"],
        "program_id": m["program_id"],
        "subject": m["subject"],
        "body": m["body"],
        "audience": m["audience"],
        "classroom_id": m["classroom_id"],
        "status": m["status"],
        "recipient_count": m["recipient_count"],
        "sent_at": fmt_dt(m["sent_at"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def retention_entry_view(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "child_id": e["child_id"],
        "attended_days": e["attended_days"],
        "attendance_rate": e["attendance_rate"],
        "family_volunteer_bonus": e["family_volunteer_bonus"],
        "priority_tier": e["priority_tier"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
