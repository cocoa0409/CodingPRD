"""Analytical compensation: fee-independent by construction.

SCAFFOLD state_machines -> AnalystCompensation / LookBackReview,
PRD section 3.9.
"""

from db import base_row, db, now, touch
from errors import fail
from services import calculations, common


def create(analyst_id, base_salary_cents, rating_accuracy_score, comp_period):
    row = base_row()
    row.update(
        {
            "analyst_id": analyst_id,
            "base_salary_cents": int(base_salary_cents or 0),
            "compensation_separation_pct": 1.0,
            "fee_generation_bonus_cents": 0,
            "rating_accuracy_score": rating_accuracy_score,
            "accuracy_bonus_cents": 0,
            "comp_period": comp_period,
            "total_compensation_cents": 0,
            "status": "DRAFT",
        }
    )
    db.compensation_records[row["id"]] = row
    return row


def _confirmed_in_period(analyst_id, comp_period):
    """A CONFIRMED assignment is in the comp period when the period label
    matches either the current logical-clock period or the period the
    assignment's own engagement falls in."""
    current = _period_label(now())
    for assignment in db.team_assignments.values():
        if assignment["status"] != "CONFIRMED":
            continue
        if analyst_id not in (
            assignment["lead_analyst_id"],
            assignment["support_analyst_id"],
        ):
            continue
        if comp_period == current:
            return assignment
        request = db.rating_requests.get(assignment["rating_request_id"])
        if request is None:
            continue
        engagement = db.engagement_letters.get(request["engagement_letter_id"])
        anchor = None
        if engagement is not None:
            anchor = engagement["signed_at"] or engagement["created_at"]
        if anchor is None:
            anchor = assignment.get("window_start") or assignment["created_at"]
        if _period_label(anchor) == comp_period:
            return assignment
    return None


def _period_label(instant):
    if instant is None:
        instant = now()
    if instant.month <= 6:
        return "%d-H1" % instant.year
    return "%d-H2" % instant.year


def approve(row):
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a draft compensation record can be approved.")

    # A fee-generation component can never legitimately exist.
    if int(row.get("fee_generation_bonus_cents") or 0) != 0:
        fail("ERR_COMPENSATION_FEE_LINKAGE")

    analyst = db.analysts.get(row["analyst_id"])
    if analyst is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    if _confirmed_in_period(row["analyst_id"], row["comp_period"]) is not None:
        fail("ERR_COMPENSATION_CONFLICT")

    if analyst.get("is_departed"):
        fail("ERR_COMPENSATION_ANALYST_DEPARTED")

    _recompute(row)
    row["status"] = "APPROVED"
    return touch(row)


def _recompute(row):
    accuracy_bonus, fee_bonus, total, separation = calculations.compensation_components(
        row["base_salary_cents"], row["rating_accuracy_score"]
    )
    row["accuracy_bonus_cents"] = accuracy_bonus
    row["fee_generation_bonus_cents"] = fee_bonus
    row["total_compensation_cents"] = total
    row["compensation_separation_pct"] = float(separation)
    return row


def pay(row):
    if row["status"] != "APPROVED":
        fail("ERR_COMPENSATION_NOT_APPROVED")
    row["status"] = "PAID"
    return touch(row)


def revise(row):
    if row["status"] != "APPROVED":
        fail("ERR_COMPENSATION_NOT_APPROVED")
    _recompute(row)
    row["status"] = "DRAFT"
    return touch(row)