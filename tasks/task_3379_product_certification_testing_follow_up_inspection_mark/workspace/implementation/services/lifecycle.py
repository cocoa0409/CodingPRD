"""Cross-aggregate lifecycle logic: project auto-advancement, factory
conformity recomputation, and certification suspension/reinstatement/
withdrawal cascades (PRD 2.10, 3.2, 3.6, 3.9)."""
import clock
import db
from services import calc


# ---------------------------------------------------------------------------
# Project readiness: TESTING -> EVALUATION (fee snapshot stored on entry)
# ---------------------------------------------------------------------------

def maybe_advance_project(project):
    if project["status"] != "TESTING":
        return
    if not calc.evaluation_ready(project):
        return
    standard = db.standards[project["standard_id"]]
    project["fee_snapshot_cents"] = calc.compute_fee_snapshot(project, standard)
    project["status"] = "EVALUATION"
    db.mutate(project)


# ---------------------------------------------------------------------------
# Factory conformity posture (score, regime, criticals, interval)
# ---------------------------------------------------------------------------

def recompute_factory(factory, event=None, inspection=None, mutate=True):
    """Pinned order: score -> regime -> interval -> next due date.
    event is 'complete', 'void', or None (clock sweep: STANDARD regimes only,
    score only)."""
    now = clock.now()
    factory_id = factory["id"]
    completed = calc.completed_inspections(factory_id)

    win_score = calc.windowed_score(factory_id, now)
    all_score = calc.all_time_score(factory_id)
    open_critical = calc.open_critical_count(factory_id)

    if event is None:
        # Clock sweep: only the STANDARD-regime score ages; regime untouched.
        if factory["conformity_regime"] == "STANDARD":
            if factory["conformity_score"] != float(win_score):
                factory["conformity_score"] = float(win_score)
                db.mutate(factory)
        return

    regime = factory["conformity_regime"]
    if regime == "STANDARD":
        new_critical = (
            event == "complete" and inspection is not None
            and any(f["severity"] == "CRITICAL" for f in inspection["findings"])
        )
        if new_critical or win_score < calc.PROBATION_THRESHOLD:
            regime = "PROBATION"
    else:  # PROBATION
        clean_completion = (
            event == "complete" and inspection is not None
            and len(inspection["findings"]) == 0
        )
        healed_by_void = (
            event == "void" and open_critical == 0
            and win_score >= calc.PROBATION_THRESHOLD
        )
        if clean_completion or healed_by_void:
            regime = "STANDARD"

    final_score = win_score if regime == "STANDARD" else all_score

    if completed:
        last_completed = max(i["completed_on"] for i in completed)
    else:
        last_completed = None

    interval_months = calc.derive_interval_months(regime, final_score)
    next_due = calc.add_months(last_completed, interval_months) if last_completed else None

    factory["conformity_regime"] = regime
    factory["conformity_score"] = float(calc.round_half_up(final_score, 2))
    factory["open_critical_findings"] = open_critical
    factory["last_inspection_completed_on"] = last_completed
    factory["next_inspection_due_on"] = next_due
    db.mutate(factory)


# ---------------------------------------------------------------------------
# Certification suspension / reinstatement / withdrawal cascades
# ---------------------------------------------------------------------------

def _licenses_of(certification_id):
    return [lic for lic in db.mark_licenses.values()
            if lic["certification_id"] == certification_id]


def suspend_certification(cert, cause):
    """ACTIVE -> SUSPENDED with the given cause; cascades to licenses.
    An already-SUSPENDED certification merely accumulates the cause."""
    if cert["status"] in ("WITHDRAWN", "EXPIRED"):
        return
    if cause not in cert["suspension_causes"]:
        cert["suspension_causes"].append(cause)
    if cert["status"] == "ACTIVE":
        cert["status"] = "SUSPENDED"
        db.mutate(cert)
        for lic in _licenses_of(cert["id"]):
            if lic["status"] in ("ACTIVE", "EXHAUSTED"):
                lic["status"] = "SUSPENDED"
                db.mutate(lic)
    else:
        db.mutate(cert)


def reinstate_certification(cert):
    """SUSPENDED -> ACTIVE; causes cleared; licenses return to ACTIVE or
    EXHAUSTED according to quota consumption."""
    cert["status"] = "ACTIVE"
    cert["suspension_causes"] = []
    db.mutate(cert)
    for lic in _licenses_of(cert["id"]):
        if lic["status"] == "SUSPENDED":
            if lic["used_quantity"] < lic["authorized_quantity"]:
                lic["status"] = "ACTIVE"
            else:
                lic["status"] = "EXHAUSTED"
            db.mutate(lic)


def withdraw_certification(cert):
    """-> WITHDRAWN; every non-REVOKED license -> REVOKED; on each revoked
    license every ISSUED batch -> VOIDED and used_quantity recomputed."""
    cert["status"] = "WITHDRAWN"
    db.mutate(cert)
    for lic in _licenses_of(cert["id"]):
        if lic["status"] == "REVOKED":
            continue
        lic["status"] = "REVOKED"
        for batch in db.label_batches.values():
            if batch["license_id"] == lic["id"] and batch["status"] == "ISSUED":
                batch["status"] = "VOIDED"
                db.mutate(batch)
        lic["used_quantity"] = sum(
            b["quantity"] for b in db.label_batches.values()
            if b["license_id"] == lic["id"] and b["status"] == "ISSUED"
        )
        db.mutate(lic)


def compensate_voided_inspection(inspection):
    """Void compensation: remove this inspection's finding-derived suspension
    causes from every SUSPENDED certification; a certification left with no
    causes at all is automatically reinstated (cascading to licenses)."""
    refs = {f["finding_ref"] for f in inspection["findings"]}
    removed = {"CRITICAL_FINDING:%s" % ref for ref in refs}
    for cert in db.certifications.values():
        if cert["status"] != "SUSPENDED":
            continue
        remaining = [c for c in cert["suspension_causes"] if c not in removed]
        if len(remaining) == len(cert["suspension_causes"]):
            continue
        if remaining:
            cert["suspension_causes"] = remaining
            db.mutate(cert)
        else:
            reinstate_certification(cert)
