"""Derived (computed) field evaluation.

Every field the scaffold marks `source: computed` and which is a pure function
of other rows is evaluated here at read time, so a read is never stale.
"""
from decimal import Decimal

import store
from constants import (
    CONDUCT_PROBATION_THRESHOLD, CONDUCT_SUSPENSION_THRESHOLD,
    COVERAGE_ALERT_THRESHOLD, DUTY_POINTS,
)
from store import DB


# ---------------------------------------------------------------- topology
def floors_of(building_id):
    return [f for f in store.all_rows("floors") if f["building_id"] == building_id]


def rooms_of_floor(floor_id):
    return [r for r in store.all_rows("rooms") if r["floor_id"] == floor_id]


def rooms_of_building(building_id):
    ids = {f["id"] for f in floors_of(building_id)}
    return [r for r in store.all_rows("rooms") if r["floor_id"] in ids]


def floor_of_room(room):
    return DB["floors"].get(room["floor_id"])


def building_of_floor(floor):
    return DB["buildings"].get(floor["building_id"])


def building_of_room(room):
    floor = floor_of_room(room)
    return building_of_floor(floor) if floor else None


# ------------------------------------------------------------------- Room
def room_occupied_beds(room):
    return sum(
        1 for s in DB["students"].values() if s.get("current_room_id") == room["id"]
    )


def room_condition_score(room):
    best = None
    for insp in DB["inspections"].values():
        if insp["room_id"] != room["id"] or insp["status"] != "COMPLETED":
            continue
        key = (insp.get("completed_at") or "", insp["created_at"], insp["_seq"])
        if best is None or key > best[0]:
            best = (key, insp)
    if best is None:
        return 100
    score = best[1].get("condition_score")
    return 100 if score is None else score


def room_break_hold_count(room):
    return sum(
        1 for b in DB["breaks"].values()
        if b["room_id"] == room["id"] and b["status"] in ("APPROVED", "CHECKED_IN")
    )


def room_derived(room):
    return {
        "occupied_beds": room_occupied_beds(room),
        "condition_score": room_condition_score(room),
        "break_hold_count": room_break_hold_count(room),
    }


def room_has_free_bed(room):
    return room_occupied_beds(room) < room["bed_capacity"]


# ------------------------------------------------------------------ Floor
def floor_bed_capacity(floor):
    return sum(r["bed_capacity"] for r in rooms_of_floor(floor["id"]))


def floor_occupied_beds(floor):
    return sum(room_occupied_beds(r) for r in rooms_of_floor(floor["id"]))


def floor_events(floor_id):
    return [e for e in store.all_rows("events") if e["floor_id"] == floor_id]


def floor_encumbered(floor):
    return sum(
        e["encumbered_amount_cents"] for e in floor_events(floor["id"])
        if e["status"] in ("APPROVED", "HELD")
    )


def floor_spent(floor):
    return sum(
        (e.get("reimbursed_amount_cents") or 0) for e in floor_events(floor["id"])
        if e["status"] == "REIMBURSED"
    )


def floor_qualifying_events(floor):
    return [e for e in floor_events(floor["id"]) if e["status"] in ("HELD", "REIMBURSED")]


def floor_compliance(floor):
    qualifying = floor_qualifying_events(floor)
    held = len(qualifying)
    has_edu = any(e["category"] == "EDUCATIONAL" for e in qualifying)
    has_well = any(e["category"] == "WELLNESS" for e in qualifying)
    if held >= floor["required_programs_per_term"] and has_edu and has_well:
        status = "COMPLIANT"
    elif floor.get("programming_frozen"):
        status = "DEFICIENT"
    else:
        status = "PENDING"
    return held, status, has_edu, has_well


def floor_uncovered_shift_count(floor):
    current = store.now()
    total = 0
    for s in DB["shifts"].values():
        if s["floor_id"] != floor["id"] or s["status"] != "OPEN":
            continue
        if store.parse_iso(s["start_at"]) >= current:
            total += 1
    return total


def floor_derived(floor):
    budget = floor["programming_budget_cents"]
    encumbered = floor_encumbered(floor)
    spent = floor_spent(floor)
    held, compliance, _edu, _well = floor_compliance(floor)
    uncovered = floor_uncovered_shift_count(floor)
    return {
        "programming_budget_cents": budget,
        "programming_encumbered_cents": encumbered,
        "programming_spent_cents": spent,
        "programming_available_cents": budget - encumbered - spent,
        "held_program_count": held,
        "programming_compliance_status": compliance,
        "uncovered_shift_count": uncovered,
        "coverage_status": "CRITICAL" if uncovered >= COVERAGE_ALERT_THRESHOLD else "NORMAL",
        "bed_capacity": floor_bed_capacity(floor),
        "occupied_beds": floor_occupied_beds(floor),
    }


def floor_available_cents(floor):
    return (
        floor["programming_budget_cents"]
        - floor_encumbered(floor)
        - floor_spent(floor)
    )


# --------------------------------------------------------------- Building
def building_bed_capacity(building):
    return sum(r["bed_capacity"] for r in rooms_of_building(building["id"]))


def building_assigned_bed_count(building):
    ids = {r["id"] for r in rooms_of_building(building["id"])}
    return sum(
        1 for s in DB["students"].values() if s.get("current_room_id") in ids
    )


def building_derived(building):
    return {
        "bed_capacity": building_bed_capacity(building),
        "assigned_bed_count": building_assigned_bed_count(building),
    }


# ---------------------------------------------------------------- Student
def student_conduct_points(student):
    return sum(
        (c.get("sanction_points") or 0) for c in DB["conduct_cases"].values()
        if c["respondent_student_id"] == student["id"] and c["status"] == "SANCTIONED"
    )


def standing_for(points):
    if points >= CONDUCT_SUSPENSION_THRESHOLD:
        return "SUSPENDED"
    if points >= CONDUCT_PROBATION_THRESHOLD:
        return "PROBATION"
    return "GOOD"


def student_judicial_hold(student):
    return any(
        c["respondent_student_id"] == student["id"]
        and c["status"] in ("OPEN", "HEARING_SCHEDULED")
        for c in DB["conduct_cases"].values()
    )


def student_damage_balance(student):
    return sum(
        (c.get("final_amount_cents") or 0) for c in DB["charges"].values()
        if c["student_id"] == student["id"] and c["status"] in ("BILLED", "APPEALED")
    )


def student_derived(student):
    points = student_conduct_points(student)
    return {
        "conduct_points": points,
        "conduct_standing": standing_for(points),
        "judicial_hold": student_judicial_hold(student),
        "damage_balance_cents": student_damage_balance(student),
    }


def student_standing(student):
    return standing_for(student_conduct_points(student))


# --------------------------------------------------------------------- RA
def ra_credits(ra):
    from constants import MODULE_CREDITS
    return sum(MODULE_CREDITS.get(code, 0) for code in ra["completed_module_codes"])


def ra_shifts(ra_id):
    return [s for s in store.all_rows("shifts") if s.get("assigned_ra_id") == ra_id]


def ra_duty_points(ra):
    return sum(
        DUTY_POINTS[s["shift_type"]] for s in ra_shifts(ra["id"])
        if s["status"] == "COMPLETED"
    )


def ra_missed(ra):
    return sum(1 for s in ra_shifts(ra["id"]) if s["status"] == "MISSED")


def ra_derived(ra):
    return {
        "training_credits_earned": ra_credits(ra),
        "duty_points_balance": ra_duty_points(ra),
        "missed_shift_count": ra_missed(ra),
    }


# ---------------------------------------------------------------- census
def occupancy_census(building):
    rooms = rooms_of_building(building["id"])
    total_beds = sum(r["bed_capacity"] for r in rooms)
    occupied = sum(room_occupied_beds(r) for r in rooms)
    offline = sum(1 for r in rooms if r["status"] in ("OFFLINE", "CONSOLIDATED"))
    underfilled = 0
    for r in rooms:
        occ = room_occupied_beds(r)
        if r["status"] == "OCCUPIED" and 1 <= occ < r["bed_capacity"]:
            underfilled += 1
    if total_beds == 0:
        rate = Decimal("0")
    else:
        from calc import round_half_up_dec
        rate = round_half_up_dec(
            (Decimal(total_beds - occupied) / Decimal(total_beds)), 4
        )
    return {
        "total_beds": total_beds,
        "occupied_beds": occupied,
        "vacancy_rate": float(rate),
        "underfilled_room_count": underfilled,
        "offline_room_count": offline,
    }
