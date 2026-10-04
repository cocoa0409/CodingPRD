"""Scheduled sweeps executed as part of every logical-clock advance (PRD 2.10)."""

from db import DB
from errors import fmt


def run_all():
    expire_estimates()
    expire_trade_in_offers()
    expire_trial_entitlements()
    complete_service_appointments()
    progress_mobile_visits()
    apply_configuration_locks()


def _set_state(row, state):
    row["status"] = state
    row["updated_at"] = fmt(DB.now)
    row["version"] = row.get("version", 1) + 1


def expire_estimates():
    """Estimates whose window has closed stop being a live promise."""
    for estimate in DB.estimates.values():
        if estimate["estimate_state"] not in ("PROVISIONAL", "FIRM"):
            continue
        if estimate["window_end"] < DB.now:
            estimate["estimate_state"] = "SUPERSEDED"
            estimate["updated_at"] = fmt(DB.now)
            estimate["version"] += 1


def expire_trade_in_offers():
    """A lapsed offer owes the compensating reversal the expiry always carries."""
    from services import ledger
    for appraisal in DB.appraisals.values():
        if appraisal["status"] != "OFFERED":
            continue
        if appraisal["offer_valid_until"] < DB.now:
            appraisal["status"] = "EXPIRED"
            ledger.write_entry(appraisal["order_id"], "TRADE_IN_CREDIT_REVERSAL",
                               -appraisal["net_credit_cents"], "TRADE_IN_OFFER_LAPSED")
            appraisal["updated_at"] = fmt(DB.now)
            appraisal["version"] += 1


def expire_trial_entitlements():
    for entitlement in DB.entitlements.values():
        if entitlement["status"] != "ACTIVE":
            continue
        expires_at = entitlement.get("expires_at")
        if expires_at is not None and DB.now > expires_at:
            entitlement["status"] = "EXPIRED"
            entitlement["updated_at"] = fmt(DB.now)
            entitlement["version"] += 1


def complete_service_appointments():
    from services.service_ops import complete_scheduled_appointment
    for appointment in list(DB.service_appointments.values()):
        if appointment["status"] != "CENTER_SCHEDULED":
            continue
        if DB.now >= appointment["scheduled_end"]:
            complete_scheduled_appointment(appointment)


def progress_mobile_visits():
    from services.service_ops import begin_progress
    for visit in list(DB.visits.values()):
        if visit["status"] != "EN_ROUTE":
            continue
        if DB.now >= visit["visit_start"]:
            begin_progress(visit)


def apply_configuration_locks():
    from services.order_flow import apply_deferred_lock
    for order in DB.orders.values():
        apply_deferred_lock(order)