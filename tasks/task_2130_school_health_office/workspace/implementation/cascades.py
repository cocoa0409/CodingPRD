"""Cascades, conserved-counter movements and system-driven transitions.

Cascades are hop-by-hop and causal: each hop's own side effects (counter
movements, version increments, derived-field refresh) complete before the next
hop begins.  School and visit derived figures are evaluated from live state, so
"recompute" hops are always observed fresh.
"""
import calc
from store import db, touch


# ---------------------------------------------------------------------------
# Lot helpers
# ---------------------------------------------------------------------------

def refresh_lot_state(lot):
    """AVAILABLE -> DEPLETED at zero on hand; DEPLETED -> AVAILABLE above zero."""
    if lot["status"] == "AVAILABLE" and lot["quantity_on_hand"] == 0:
        lot["status"] = "DEPLETED"
        touch(lot)
    elif lot["status"] == "DEPLETED" and lot["quantity_on_hand"] > 0 \
            and lot["expiration_date"] > db.now():
        lot["status"] = "AVAILABLE"
        touch(lot)


def move_units(lot, source, target, units):
    lot[source] -= units
    lot[target] += units
    touch(lot)


# ---------------------------------------------------------------------------
# Student observed risk
# ---------------------------------------------------------------------------

def recompute_observed(student):
    if student is None:
        return
    score = calc.observed_risk_score(student)
    if student.get("observed_risk_score") != score:
        student["observed_risk_score"] = score
        touch(student)


def recompute_observed_for_visit(visit):
    recompute_observed(db.students.get(visit["student_id"]))


# ---------------------------------------------------------------------------
# AdministrationRecord void (manual and system-driven)
# ---------------------------------------------------------------------------

def void_record(record, reason_code=None):
    """Compensate the lot exactly according to the source state."""
    source = record["status"]
    lot = db.medication_stock_lots.get(record["lot_id"])
    record["status"] = "VOIDED"
    record["voided_at"] = db.now()
    if reason_code is not None:
        record["reason_code"] = reason_code
    touch(record)
    if lot is not None:
        if source == "PREPARED":
            move_units(lot, "quantity_reserved", "quantity_on_hand", record["units"])
        elif source == "ADMINISTERED":
            move_units(lot, "quantity_administered", "quantity_on_hand", record["units"])
        elif source == "WASTED":
            move_units(lot, "quantity_wasted", "quantity_on_hand", record["units"])
        refresh_lot_state(lot)
    visit = db.health_visits.get(record["visit_id"])
    if visit is not None:
        recompute_observed(db.students.get(visit["student_id"]))
    return record


def void_prepared_records(predicate):
    """Void every PREPARED record matching the predicate; return their ids."""
    voided = []
    for record in list(db.administration_records.values()):
        if record["status"] != "PREPARED":
            continue
        if not predicate(record):
            continue
        void_record(record)
        voided.append(record["id"])
    return voided


def void_prepared_for_authorization(auth_id):
    return void_prepared_records(lambda r: r.get("authorization_id") == auth_id)


def void_prepared_for_lot(lot_id):
    return void_prepared_records(lambda r: r.get("lot_id") == lot_id)


# ---------------------------------------------------------------------------
# MedicationAuthorization suspension
# ---------------------------------------------------------------------------

def suspend_authorization(auth):
    """VERIFIED -> SUSPENDED with its PREPARED records released."""
    auth["clinical_status"] = "SUSPENDED"
    touch(auth)
    return void_prepared_for_authorization(auth["id"])


def suspend_orders_for_plan(plan, from_statuses):
    voided = []
    for auth in list(db.medication_authorizations.values()):
        if auth.get("action_plan_id") != plan["id"]:
            continue
        if auth["clinical_status"] not in from_statuses:
            continue
        voided.extend(suspend_authorization(auth))
    return voided


# ---------------------------------------------------------------------------
# The four-hop supersede cascade
# ---------------------------------------------------------------------------

def supersede_cascade(predecessor):
    """Hop 1 ACTIVE -> SUPERSEDED; hop 2 verified orders suspend; hop 3 their
    prepared records void and release; hop 4 touched lots recover and the
    building's stock figures refresh."""
    predecessor["status"] = "SUPERSEDED"
    touch(predecessor)
    # hop 2 and hop 3 (each release also runs hop 4 for its own lot)
    suspend_orders_for_plan(predecessor, ("VERIFIED",))


# ---------------------------------------------------------------------------
# The four-hop quarantine cascade
# ---------------------------------------------------------------------------

def quarantine_cascade(lot):
    """Hop 1 the lot is quarantined; hop 2 its prepared records void and their
    reservations return; hop 3 the building's days of supply and protocol
    status refresh; hop 4 the posture refreshes."""
    lot["status"] = "QUARANTINED"
    touch(lot)
    void_prepared_for_lot(lot["id"])
