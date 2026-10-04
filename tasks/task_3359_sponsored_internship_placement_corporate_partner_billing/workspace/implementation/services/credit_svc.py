"""Satisfaction composite, college credit and conversion bookkeeping
(PRD 3.6, 3.8)."""

import db
from services.rounding import Decimal, round_half_up

WEIGHT_SUPERVISOR = Decimal("0.50")
WEIGHT_PROJECT = Decimal("0.30")
WEIGHT_COMMUNICATION = Decimal("0.20")
RESCALE_NUMERATOR = Decimal(5)
RESCALE_DENOMINATOR = Decimal(4)
RESCALE_OFFSET = Decimal(1)

COMPOSITE_SCALE = 2
COMPOSITE_MIN = Decimal("0.00")
COMPOSITE_MAX = Decimal("5.00")

TUITION_CENTS_PER_CREDIT = 12500
TUITION_CREDIT_CAP_CENTS = 500000
GRADUATION_BONUS_CENTS = 50000
CREDIT_WINDOW_DAYS = 365


def composite_score(supervisor_rating, project_rating, communication_rating):
    """Each weighted term is rounded before summing (pinned variant)."""
    term_supervisor = round_half_up(Decimal(str(supervisor_rating)) * WEIGHT_SUPERVISOR, COMPOSITE_SCALE)
    term_project = round_half_up(Decimal(str(project_rating)) * WEIGHT_PROJECT, COMPOSITE_SCALE)
    term_communication = round_half_up(
        Decimal(str(communication_rating)) * WEIGHT_COMMUNICATION, COMPOSITE_SCALE
    )
    weighted = round_half_up(
        term_supervisor + term_project + term_communication, COMPOSITE_SCALE
    )
    rescaled = round_half_up(
        weighted * RESCALE_NUMERATOR / RESCALE_DENOMINATOR - RESCALE_OFFSET, COMPOSITE_SCALE
    )
    if rescaled < COMPOSITE_MIN:
        rescaled = COMPOSITE_MIN
    if rescaled > COMPOSITE_MAX:
        rescaled = COMPOSITE_MAX
    return rescaled


def per_grant_tuition_credit(credit_hours):
    """The per-grant cap is applied before any summing."""
    raw = round_half_up(Decimal(str(credit_hours)) * Decimal(TUITION_CENTS_PER_CREDIT), 0)
    return int(min(raw, Decimal(TUITION_CREDIT_CAP_CENTS)))


def included_grants(student_id):
    return [
        g for g in db.all_rows("credit_grants")
        if g["student_id"] == student_id and g["status"] in ("PENDING", "GRANTED")
    ]


def total_tuition_credit_cents(student):
    subtotal = sum(per_grant_tuition_credit(g["credit_hours"]) for g in included_grants(student["id"]))
    bonus = GRADUATION_BONUS_CENTS if student.get("current_phase") == "COMPLETED" else 0
    return subtotal + bonus


def mark_converted_to_hire(placement):
    """Set converted_to_hire on every satisfaction record of the placement."""
    touched = False
    for record in db.all_rows("satisfaction_records"):
        if record["placement_id"] == placement["id"] and not record.get("converted_to_hire"):
            record["converted_to_hire"] = True
            db.touch(record)
            touched = True
    return touched


def update_conversion_streak(student, converted):
    if converted:
        student["conversion_streak"] = int(student.get("conversion_streak") or 0) + 1
    else:
        student["conversion_streak"] = 0
    db.touch(student)
    return student
