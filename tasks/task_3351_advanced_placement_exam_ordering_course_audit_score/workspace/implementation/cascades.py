"""Counter recomputation and the cross-entity cascades.

Counters are recomputed from the rows as they stand after a transition, never
adjusted incrementally, and a parent row's version is incremented once per
affected parent rather than once per affected child.
"""

import calc
import core
from constants import ACTIVE_REGISTRATION_STATUSES, DELIVERED_REGISTRATION_STATUSES
from entities import make


def regs_of_order(order_id):
    return [r for r in core.rows("exam_registrations") if r["exam_order_id"] == order_id]


def regs_of_student(student_id):
    return [r for r in core.rows("exam_registrations") if r["student_id"] == student_id]


def scores_of_registration(registration_id):
    return [s for s in core.rows("exam_scores") if s["exam_registration_id"] == registration_id]


def recompute_registration_count(order):
    count = 0
    for reg in regs_of_order(order["id"]):
        if reg["status"] in ACTIVE_REGISTRATION_STATUSES:
            count += 1
    order["registration_count"] = count
    refresh_order_fees(order)
    return count


def refresh_order_fees(order):
    order["provisional_order_fee_cents"] = calc.order_fee_provisional(order)
    if order["status"] in ("OPEN", "SUBMITTED", "MATERIALS_SHIPPED", "MATERIALS_RECEIVED"):
        order["order_fee_cents"] = order["provisional_order_fee_cents"]


def recompute_school_audit_counters(school_id):
    count = 0
    for audit in core.rows("course_audits"):
        if audit["school_id"] == school_id and audit["status"] == "APPROVED":
            count += 1
    school = core.get("schools", school_id)
    if school is not None:
        school["designated_course_count"] = count
        school["program_label_authorized"] = count >= 1
    for audit in core.rows("course_audits"):
        if audit["school_id"] == school_id:
            audit["designated_course_count"] = count
    return count


def recompute_accrued_fees(school_id):
    school = core.get("schools", school_id)
    if school is None:
        return 0
    total = 0
    for order in core.rows("exam_orders"):
        if order["school_id"] == school_id:
            total += (order.get("order_fee_cents") or 0) + (order.get("unused_exam_charge_cents") or 0)
    school["accrued_fee_cents"] = total
    return total


def recompute_designation_slots(school_id):
    school = core.get("schools", school_id)
    if school is None:
        return 0
    student_ids = {s["id"] for s in core.rows("students") if s["school_id"] == school_id}
    count = 0
    for send in core.rows("score_sends"):
        if send["recipient_type"] != "COLLEGE":
            continue
        if send["status"] not in ("PENDING", "SENT", "ACKNOWLEDGED"):
            continue
        score = core.get("exam_scores", send["exam_score_id"])
        reg = core.get("exam_registrations", score["exam_registration_id"]) if score else None
        if reg is not None and reg["student_id"] in student_ids:
            count += 1
    school["designation_slots_used"] = count
    return count


def school_of_send(send):
    """The school whose designation budget a send's student belongs to."""
    score = core.get("exam_scores", send["exam_score_id"])
    if score is None:
        return None
    reg = core.get("exam_registrations", score["exam_registration_id"])
    if reg is None:
        return None
    student = core.get("students", reg["student_id"])
    if student is None:
        return None
    return core.get("schools", student["school_id"])


def recompute_assigned_scores(reader):
    count = 0
    for score in core.rows("exam_scores"):
        if score["reader_id"] == reader["id"] and score["status"] in ("AGGREGATED", "RELEASED"):
            count += 1
    reader["assigned_score_count"] = count
    return count


def recompute_custody_counts(shipment):
    shipment["custody_sequence_count"] = len(shipment["custody_event_types"])
    shipment["storage_checkpoint_count"] = sum(
        1 for e in shipment["custody_event_types"] if e["event_type"] == "STORAGE_CHECKPOINT"
    )


def recompute_release_blocked(registration_id):
    open_case = False
    for case in core.rows("irregularity_cases"):
        if case["exam_registration_id"] == registration_id and case["status"] in ("OPEN", "INVESTIGATING"):
            open_case = True
            break
    for score in scores_of_registration(registration_id):
        score["release_blocked"] = open_case


def refresh_student_flag(student):
    eligible = False
    for req in core.rows("accommodation_requests"):
        if req["student_id"] == student["id"] and req["status"] == "APPROVED":
            eligible = True
            break
    student["accommodation_eligible"] = eligible
    return eligible


def refresh_reader_reliability(reader):
    for score in core.rows("exam_scores"):
        if score["reader_id"] == reader["id"]:
            score["reader_reliability_index"] = reader["reliability_index"]


def approved_accommodation(student_id, exam_subject):
    for req in core.rows("accommodation_requests"):
        if req["student_id"] == student_id and req["exam_subject"] == exam_subject \
                and req["status"] == "APPROVED":
            return req
    return None


# --- cascades ---------------------------------------------------------------

def approve_audit_cascade(audit, school):
    """Audit APPROVED -> open DRAFT orders -> confirm their clean registrations."""
    opened = []
    for order in core.rows("exam_orders"):
        if order["course_audit_id"] == audit["id"] and order["status"] == "DRAFT":
            order["status"] = "OPEN"
            order["ordering_window"] = calc.ordering_window()
            core.touch(order)
            opened.append(order)
    for order in opened:
        for reg in regs_of_order(order["id"]):
            if reg["status"] != "REGISTERED":
                continue
            student = core.get("students", reg["student_id"])
            if student is not None and student["accommodation_eligible"]:
                continue
            reg["status"] = "CONFIRMED"
            reg["accommodation_flag"] = bool(student and student["accommodation_eligible"])
            core.touch(reg)
    if school is not None:
        core.touch(school)


def expire_audit(audit):
    audit["status"] = "EXPIRED"
    core.touch(audit)
    recompute_school_audit_counters(audit["school_id"])
    for order in core.rows("exam_orders"):
        if order["course_audit_id"] == audit["id"] and order["status"] == "DRAFT":
            order["status"] = "VOIDED"
            core.touch(order)


def seal_break_cascade(order):
    """Order MATERIALS_SHIPPED -> SUBMITTED plus one case per assigned exam."""
    order["status"] = "SUBMITTED"
    order["materials_sealed"] = False
    core.touch(order)
    for reg in regs_of_order(order["id"]):
        if reg["status"] != "MATERIAL_ASSIGNED":
            continue
        core.insert("irregularity_cases", make(
            "irregularity_cases",
            exam_registration_id=reg["id"],
            test_center_id=order["school_id"],
            irregularity_type="MATERIAL_COMPROMISE",
            status="OPEN",
        ))


def invalidation_cascade(registration):
    """Registration INVALIDATED -> score INVALIDATED -> its sends CANCELLED.

    PRD §3.9: "every score send of that score transitions to `CANCELLED` with
    `credit_back_cents` set to its `fee_cents`, restoring the designation budget
    those sends had consumed." The budget is the school counter, so it is
    recomputed from the rows as they stand after the transition (§2.5).
    """
    registration["status"] = "INVALIDATED"
    core.touch(registration)
    for score in scores_of_registration(registration["id"]):
        score["status"] = "INVALIDATED"
        core.touch(score)
        touched_schools = set()
        for send in core.rows("score_sends"):
            if send["exam_score_id"] == score["id"] and send["status"] != "CANCELLED":
                send["status"] = "CANCELLED"
                send["credit_back_cents"] = send["fee_cents"]
                core.touch(send)
            school = school_of_send(send)
            if school is not None:
                touched_schools.add(school["id"])
        for school_id in touched_schools:
            recompute_designation_slots(school_id)


def deliver_order(order):
    """Final fee, then the unused-exam charge, then cancel the leftovers."""
    final_fee, _marginal, _delivered = calc.order_fee_consolidated(order)
    order["order_fee_cents"] = final_fee
    confirmed = [r for r in regs_of_order(order["id"]) if r["status"] == "CONFIRMED"]
    order["unused_exam_charge_cents"] = calc.unused_exam_charge(len(confirmed))
    for reg in confirmed:
        reg["status"] = "CANCELLED"
        reg["refundable_cents"] = 0
        core.touch(reg)
    order["status"] = "DELIVERED"
    core.touch(order)
    recompute_registration_count(order)
    recompute_accrued_fees(order["school_id"])


def maybe_auto_deliver(order):
    """An order whose every registration has a released score auto-delivers."""
    if order["status"] != "MATERIALS_RECEIVED":
        return False
    regs = regs_of_order(order["id"])
    if not regs:
        return False
    for reg in regs:
        if reg["status"] != "SCORE_RELEASED":
            return False
    deliver_order(order)
    return True


def registration_material_assignable(reg):
    """A flagged registration needs its approved provision recorded first."""
    if not reg.get("accommodation_flag"):
        return True
    approved = approved_accommodation(reg["student_id"], reg["exam_subject"])
    return approved is not None and approved.get("extended_time_multiplier") is not None


def count_active_registrations_for_year(student_id, administration_year):
    count = 0
    for reg in regs_of_student(student_id):
        order = core.get("exam_orders", reg["exam_order_id"])
        if order is None or order["administration_year"] != administration_year:
            continue
        if reg["status"] == "CANCELLED":
            continue
        count += 1
    return count


def registrations_reaching(reg, statuses):
    return [r for r in regs_of_student(reg["student_id"]) if r["status"] in statuses]


def delivered_statuses():
    return DELIVERED_REGISTRATION_STATUSES
