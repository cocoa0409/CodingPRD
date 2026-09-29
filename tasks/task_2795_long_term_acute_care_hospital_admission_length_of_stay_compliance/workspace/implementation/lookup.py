"""Existence lookups (PRD 2.8 rules 3 and 4) and list paging."""

from errors import ApiError
from store import db


def _get(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def hospital(row_id):
    return _get(db.hospitals, row_id, "ERR_HOSPITAL_NOT_FOUND")


def period(row_id):
    return _get(db.periods, row_id, "ERR_PERIOD_NOT_FOUND")


def patient(row_id):
    return _get(db.patients, row_id, "ERR_PATIENT_NOT_FOUND")


def physician(row_id):
    return _get(db.physicians, row_id, "ERR_PHYSICIAN_NOT_FOUND")


def criteria_set(row_id):
    return _get(db.criteria_sets, row_id, "ERR_CRITERIA_SET_NOT_FOUND")


def drg_rate(row_id):
    return _get(db.drg_rates, row_id, "ERR_DRG_RATE_NOT_FOUND")


def referral(row_id):
    return _get(db.referrals, row_id, "ERR_REFERRAL_NOT_FOUND")


def stay(row_id):
    return _get(db.stays, row_id, "ERR_STAY_NOT_FOUND")


def weaning_plan(row_id):
    return _get(db.weaning_plans, row_id, "ERR_WEANING_PLAN_NOT_FOUND")


def interruption(row_id):
    return _get(db.interruptions, row_id, "ERR_INTERRUPTION_NOT_FOUND")


def determination(row_id):
    return _get(db.determinations, row_id, "ERR_DETERMINATION_NOT_FOUND")


def review(row_id):
    return _get(db.reviews, row_id, "ERR_REVIEW_NOT_FOUND")


def query(row_id):
    return _get(db.queries, row_id, "ERR_QUERY_NOT_FOUND")


def page(rows, limit, offset):
    return rows[offset:offset + limit]


# ---- domain relationship helpers ----------------------------------------- #

def stay_weaning_plan(stay_id):
    for plan in db.weaning_plans.values():
        if plan["stay_id"] == stay_id:
            return plan
    return None


def stay_live_determination(stay_id):
    """The stay's determination whose status is DRAFT or FINAL; at most one exists."""
    for det in db.determinations.values():
        if det["stay_id"] == stay_id and det["status"] in ("DRAFT", "FINAL"):
            return det
    return None


def stay_determinations(stay_id):
    return [d for d in db.determinations.values() if d["stay_id"] == stay_id]


def stay_live_review(stay_id):
    """The stay's live denial-risk review; VOIDED reviews are not live."""
    for row in db.reviews.values():
        if row["stay_id"] == stay_id and row["status"] != "VOIDED":
            return row
    return None


def review_queries(review_id):
    return [q for q in db.queries.values() if q["denial_risk_review_id"] == review_id]


def stay_interruptions(stay_id):
    return [i for i in db.interruptions.values() if i["stay_id"] == stay_id]


def stay_notes(stay_id):
    return [n for n in db.idt_notes.values() if n["stay_id"] == stay_id]


def period_stays(period_id):
    return [s for s in db.stays.values() if s["cost_reporting_period_id"] == period_id]


def open_period():
    for row in db.periods.values():
        if row["status"] == "OPEN":
            return row
    return None
