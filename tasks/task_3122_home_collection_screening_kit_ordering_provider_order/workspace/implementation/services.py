from decimal import Decimal, ROUND_HALF_UP
import db

ADHERENT_OUTCOMES = {"ADHERENT_NEGATIVE", "ADHERENT_POSITIVE_NAVIGATED"}
IN_FLIGHT_ORDER_STATUSES = {
    "ELIGIBLE", "KIT_ORDERED", "KIT_SHIPPED", "KIT_RETURNED", "IN_LAB",
    "RECOLLECTION_REQUESTED",
}


def compute_quality_outcome(order):
    """Per quality_measure_attribution mapping."""
    result = None
    for r in db.STORE["results"].values():
        if r["order_id"] == order["id"]:
            result = r  # at most one result per order in practice
    if result is None:
        return "UNRESOLVED"
    if result["outcome"] == "NEGATIVE":
        return "ADHERENT_NEGATIVE"
    ns = result["navigation_status"]
    if ns == "COMPLETED":
        completed_date = db.date_of(result["navigation_completed_at"])
        if result["navigation_due_at"] is not None and completed_date <= result["navigation_due_at"]:
            return "ADHERENT_POSITIVE_NAVIGATED"
        return "POSITIVE_NAVIGATION_LAPSED"
    if ns in ("PENDING", "SCHEDULED"):
        return "POSITIVE_NAVIGATION_PENDING"
    if ns == "LAPSED":
        return "POSITIVE_NAVIGATION_LAPSED"
    return "UNRESOLVED"


def _program_of_cohort(cohort):
    return db.STORE["programs"].get(cohort["program_id"])


def _cohorts_of_program(program_id):
    return [c for c in db.STORE["cohorts"].values() if c["program_id"] == program_id]


def recompute_program_counters(program_id):
    program = db.STORE["programs"].get(program_id)
    if program is None:
        return
    cohorts = _cohorts_of_program(program_id)
    attributed = [c for c in cohorts if c["attributed"] and c["status"] != "EXCLUDED"]
    attributed_ids = {c["id"] for c in attributed}
    adherent = 0
    for o in db.STORE["orders"].values():
        if o.get("cohort_id") in attributed_ids and o["quality_outcome"] in ADHERENT_OUTCOMES:
            adherent += 1
    program["population_size"] = sum(1 for c in cohorts if c["status"] == "ELIGIBLE")
    program["attributed_count"] = len(attributed)
    program["adherent_count"] = adherent


def update_order_quality_outcome(order, bump_version=False):
    new_qo = compute_quality_outcome(order)
    if new_qo != order["quality_outcome"]:
        order["quality_outcome"] = new_qo
        if bump_version:
            db.touch(order)
    if order.get("program_id"):
        recompute_program_counters(order["program_id"])


def evaluate_time_transitions():
    """Sweep all time-based auto-transitions. Called after every clock advance."""
    today = db.date_of(db.now())
    # 1) KIT_SHIPPED -> ABANDONED when abandonment_due_at reached
    for order in list(db.STORE["orders"].values()):
        if order["status"] == "KIT_SHIPPED" and order["abandonment_due_at"] is not None:
            if today >= order["abandonment_due_at"]:
                order["status"] = "ABANDONED"
                kit = db.STORE["kits"].get(order["active_kit_id"]) if order["active_kit_id"] else None
                if kit is not None and kit["status"] == "SHIPPED":
                    kit["status"] = "EXPIRED_STABILIZATION"
                    db.touch(kit)
                order["active_kit_id"] = None
                for rem in db.STORE["reminders"].values():
                    if rem["order_id"] == order["id"] and rem["status"] == "SCHEDULED":
                        rem["status"] = "SKIPPED"
                db.touch(order)
    # 2) RECOLLECTION_REQUESTED -> ABANDONED when entry date + 30 days reached
    for order in list(db.STORE["orders"].values()):
        if order["status"] == "RECOLLECTION_REQUESTED":
            entered = db.date_of(order["updated_at"])
            if today >= db.add_days(entered, db.RECOLLECTION_ABANDON_DAYS):
                order["status"] = "ABANDONED"
                db.touch(order)
    # 3) navigation PENDING/SCHEDULED -> LAPSED when date > navigation_due_at
    for result in list(db.STORE["results"].values()):
        if result["navigation_status"] in ("PENDING", "SCHEDULED") and result["navigation_due_at"] is not None:
            if today > result["navigation_due_at"]:
                result["navigation_status"] = "LAPSED"
                order = db.STORE["orders"].get(result["order_id"])
                if order is not None:
                    order["quality_outcome"] = "POSITIVE_NAVIGATION_LAPSED"
                    db.touch(order)
                    if order.get("program_id"):
                        recompute_program_counters(order["program_id"])


def adherence_rate(numerator, denominator):
    if denominator == 0:
        return 0.0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)
