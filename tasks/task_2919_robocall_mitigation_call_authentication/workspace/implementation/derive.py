"""Derived provider/customer state and the cascade chains (PRD 2.9 - 2.11)."""
import calc
import store
from store import db, touch

OPERATIVE_EXCLUDED = ("WITHDRAWN", "SUPERSEDED")
PENALTY_PER_DEFICIENCY = 2
PENALTY_PER_LATE_TRACEBACK = 3
NOTICE_EXPIRY_POINTS = 5
TRAFFIC_SUSPEND_THRESHOLD = calc.AUTO_SUSPEND_THRESHOLD


# --- row lookups -----------------------------------------------------------
def provider_of(row):
    return db.providers.get(row.get("provider_id"))


def plans_of(provider_id):
    return [r for r in db.plans.values() if r["provider_id"] == provider_id]


def certificates_of(provider_id):
    return [r for r in db.certificates.values()
            if r["provider_id"] == provider_id]


def customers_of(provider_id):
    return [r for r in db.customers.values()
            if r["provider_id"] == provider_id]


def assignments_of_customer(customer_id):
    return [r for r in db.assignments.values()
            if r["customer_id"] == customer_id]


def observations_of(customer_id):
    return [r for r in db.observations.values()
            if r["customer_id"] == customer_id]


def blocking_events_of_customer(customer_id):
    return [r for r in db.blocking_events.values()
            if r["customer_id"] == customer_id]


def operative_plan(provider_id):
    """The single plan outside WITHDRAWN / SUPERSEDED (PRD 2.9)."""
    rows = [r for r in plans_of(provider_id)
            if r["filing_state"] not in OPERATIVE_EXCLUDED]
    if not rows:
        return None
    return store.order_rows(rows)[-1]


def filing_status(provider_id):
    """rmd_filing_status derived purely from the operative plan (PRD 2.9)."""
    plan = operative_plan(provider_id)
    if plan is None:
        return "UNFILED"
    state = plan["filing_state"]
    if state in ("SUBMITTED", "DEFICIENT"):
        return "PARTIAL"
    if state == "ACCEPTED":
        return "COMPLETE"
    return "UNFILED"


def active_certificate_id(provider_id):
    for row in store.order_rows(certificates_of(provider_id)):
        if row["status"] == "ACTIVE":
            return row["id"]
    return None


def score_band_source(provider_id):
    """Most recent SIGNED_OFF / FILED report by period_end desc, created asc."""
    rows = [r for r in db.reports.values()
            if r["provider_id"] == provider_id
            and r["state"] in ("SIGNED_OFF", "FILED")]
    if not rows:
        return None
    rows = store.order_rows(rows)
    rows.sort(key=lambda r: r["period_end"], reverse=True)
    return rows[0]


# --- provider recompute ----------------------------------------------------
def provider_derived(provider):
    pid = provider["id"]
    plans = plans_of(pid)
    tracebacks = [r for r in db.tracebacks.values() if r["provider_id"] == pid]
    notices = [r for r in db.notices.values() if r["provider_id"] == pid]
    assignments = [r for r in db.assignments.values()
                   if r["provider_id"] == pid]
    actions = [r for r in db.enforcements.values() if r["provider_id"] == pid]
    events = [r for r in db.blocking_events.values()
              if r["provider_id"] == pid]

    penalty = PENALTY_PER_DEFICIENCY * sum(p["deficiency_count"] for p in plans)
    penalty += PENALTY_PER_LATE_TRACEBACK * len(
        [t for t in tracebacks if t["state"] in ("OVERDUE", "RESPONDED_LATE")])
    penalty += sum(n["penalty_points_assessed"] for n in notices)

    status = filing_status(pid)
    overdue = len([t for t in tracebacks if t["state"] == "OVERDUE"])
    cert_id = active_certificate_id(pid)

    return {
        "rmd_filing_status": status,
        "active_certificate_id": cert_id,
        "penalty_points": penalty,
        "overdue_traceback_count": overdue,
        "open_notice_count": len([
            n for n in notices
            if n["state"] in ("NOTIFIED", "UNDER_INVESTIGATION")]),
        "active_assigned_number_count": len([
            a for a in assignments if a["status"] == "ACTIVE"]),
        "outstanding_forfeiture_cents": sum(
            a["total_forfeiture_cents"] for a in actions
            if a["status"] in ("PROPOSED", "CONTESTED", "SUSTAINED")),
        "blocking_false_positive_rate": calc.false_positive_rate(
            len(events), len([e for e in events if e["status"] == "REVERSED"])),
        "auth_posture": calc.posture(status, penalty, overdue, cert_id),
    }


def recompute_provider(provider, force=False):
    """Full recompute over the qualifying sets; one version bump at most."""
    if provider is None:
        return False
    values = provider_derived(provider)
    changed = any(provider.get(k) != v for k, v in values.items())
    if changed or force:
        provider.update(values)
        touch(provider)
    return changed


def recompute_provider_by_id(provider_id, force=False):
    return recompute_provider(db.providers.get(provider_id), force=force)


# --- customer recompute ----------------------------------------------------
def customer_derived(customer):
    cid = customer["id"]
    observations = observations_of(cid)
    index = calc.traffic_risk_index(observations)
    return {
        "traffic_risk_index": float(index),
        "risk_tier": calc.risk_tier(index),
        "observation_count": len(observations),
        "false_positive_count": len([
            e for e in blocking_events_of_customer(cid)
            if e["status"] == "REVERSED"]),
    }


def recompute_customer(customer, force=False):
    if customer is None:
        return False
    values = customer_derived(customer)
    changed = any(customer.get(k) != v for k, v in values.items())
    if changed or force:
        customer.update(values)
        touch(customer)
    return changed


# --- cascade primitives ----------------------------------------------------
def _mark_suspended(customer, cause, source_id):
    customer["origination_state"] = "SUSPENDED"
    customer["suspension_cause"] = cause
    customer["suspension_source_id"] = source_id


def cascade_suspend_assignments(customer):
    """Hop 3 of the canonical chain: ACTIVE -> SUSPENDED_BY_CUSTOMER."""
    for row in store.order_rows(assignments_of_customer(customer["id"])):
        if row["status"] == "ACTIVE":
            row["status"] = "SUSPENDED_BY_CUSTOMER"
            touch(row)


def cascade_reactivate_assignments(customer):
    for row in store.order_rows(assignments_of_customer(customer["id"])):
        if row["status"] == "SUSPENDED_BY_CUSTOMER":
            row["status"] = "ACTIVE"
            touch(row)


def cascade_revoke_assignments(customer, only_number=None):
    stamp = db.now()
    for row in store.order_rows(assignments_of_customer(customer["id"])):
        if row["status"] not in ("ACTIVE", "SUSPENDED_BY_CUSTOMER"):
            continue
        if only_number is not None and row["telephone_number"] != only_number:
            continue
        row["status"] = "REVOKED"
        row["revoked_at"] = stamp
        row["_raw"].pop("revoked_at", None)
        touch(row)


# --- full cascade chains ---------------------------------------------------
def suspend_customer(customer, cause, source_id):
    """ENABLED -> SUSPENDED, then assignments, then provider counters."""
    _mark_suspended(customer, cause, source_id)
    touch(customer)
    cascade_suspend_assignments(customer)
    recompute_provider_by_id(customer["provider_id"])


def restore_customer(customer):
    customer["origination_state"] = "ENABLED"
    customer["suspension_cause"] = None
    customer["suspension_source_id"] = None
    touch(customer)
    cascade_reactivate_assignments(customer)
    recompute_provider_by_id(customer["provider_id"])


def terminate_customer(customer):
    customer["origination_state"] = "TERMINATED"
    customer["suspension_cause"] = None
    customer["suspension_source_id"] = None
    touch(customer)
    cascade_revoke_assignments(customer)
    recompute_provider_by_id(customer["provider_id"])
