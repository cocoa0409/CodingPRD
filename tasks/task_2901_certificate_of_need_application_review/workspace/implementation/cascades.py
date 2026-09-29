"""Server-initiated cascades (PRD §2.11, §3.8, §3.9)."""

import calc
import clock
import services
import store


class Touch:
    """Collects rows mutated by one cascade so each row's version moves exactly once."""

    def __init__(self):
        self._rows = {}

    def mark(self, record):
        if record is not None:
            self._rows[id(record)] = record

    def flush(self):
        for record in self._rows.values():
            store.touch(record)


# --- progress reporting (PRD §3.8) -------------------------------------------

def apply_progress_report(cert, report):
    """Supersede the prior period report, refresh the money axis, run both cascades."""
    for other in store.rows("progress_reports"):
        if (other["id"] != report["id"]
                and other["certificate_id"] == cert["id"]
                and other["status"] == "ACCEPTED"
                and other["period_end_date"] == report["period_end_date"]):
            other["status"] = "SUPERSEDED"
            store.touch(other)

    services.recompute_certificate_fiscal(cert)
    store.touch(cert)

    latest = cert["latest_completion_pct"]
    if float(latest) == 100.0 and cert["lifecycle_status"] == "ISSUED":
        cert["lifecycle_status"] = "IMPLEMENTED"
        store.touch(cert)
        area = services.area_of_certificate(cert)
        beds = cert["authorized_bed_count"]
        services.credit_area(area, beds=-beds, licensed=beds)
        if area is not None:
            store.touch(area)

    if (cert["expenditure_status"] == "LIMIT_BREACHED"
            and cert["lifecycle_status"] in ("ISSUED", "IMPLEMENTED")):
        cert["lifecycle_status_before_suspension"] = cert["lifecycle_status"]
        cert["lifecycle_status"] = "SUSPENDED"
        store.touch(cert)
        services.charge_strike(services.applicant_of_certificate(cert))


# --- lapse sweep (PRD §3.8) --------------------------------------------------

def run_lapse_sweep():
    issued = store.sort_created(
        [c for c in store.rows("certificates") if c["lifecycle_status"] == "ISSUED"])
    today = clock.now().date()
    lapsed_ids = []
    for cert in issued:
        milestone = clock.parse_date(cert["implementation_milestone_date"])
        if milestone is None or not (milestone < today):
            continue
        if not (float(cert["latest_completion_pct"])
                < float(cert["required_completion_pct_at_milestone"])):
            continue
        cert["lifecycle_status"] = "LAPSED"
        store.touch(cert)
        beds = cert["authorized_bed_count"]
        area = services.area_of_certificate(cert)
        services.credit_area(area, beds=-beds, cents=-cert["approved_expenditure_limit_cents"])
        if area is not None:
            store.touch(area)
        app = store.get("applications", cert["application_id"])
        cycle_row = services.cycle_of_application(app) if app else None
        if cycle_row is not None:
            services.credit_pool(cycle_row, beds)
            store.touch(cycle_row)
        if app is not None:
            app["allocated_bed_count"] = 0
            store.touch(app)
        services.charge_strike(services.applicant_of_certificate(cert))
        lapsed_ids.append(cert["id"])
    return {
        "evaluated_count": len(issued),
        "lapsed_count": len(lapsed_ids),
        "lapsed_certificate_ids": lapsed_ids,
    }


# --- appeal dispositions (PRD §3.9) ------------------------------------------

def _stale_sheets_and_rescore(cycle_row, touch):
    for app in services.applications_of_cycle(cycle_row):
        for sheet in services.sheets_of_application(app["id"], "ACTIVE"):
            sheet["status"] = "STALE"
            touch.mark(sheet)
    for app in services.applications_of_cycle(cycle_row):
        if services.recompute_application_score(app):
            touch.mark(app)


def _clear_decision_fields(app):
    app["denial_reason"] = None
    app["decision_at"] = None
    app["appeal_window_closes_at"] = None


def reversal_cascade(appeal_row, touch):
    """Links 2-5: the application, its certificate, the planning area and the cycle."""
    app = store.get("applications", appeal_row["application_id"])
    if app is None:
        return
    cycle_row = services.cycle_of_application(app)
    cycle_dirty = False
    reopen = False

    if app["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        released = app["allocated_bed_count"]
        app["allocated_bed_count"] = 0
        app["denial_reason"] = "APPEAL_REVERSED"
        app["status"] = "DENIED"
        touch.mark(app)
        if released:
            services.credit_pool(cycle_row, released)
            cycle_dirty = True
        for cert in services.certificates_of_application(app["id"]):
            if cert["lifecycle_status"] not in services.ACTIVE_CERT_STATES:
                continue
            cert["lifecycle_status"] = "REVOKED"
            touch.mark(cert)
            area = services.area_of_certificate(cert)
            services.credit_area(
                area,
                beds=-cert["authorized_bed_count"],
                cents=-cert["approved_expenditure_limit_cents"],
            )
            touch.mark(area)
        if cycle_row is not None and cycle_row["status"] == "DECIDED":
            reopen = True
    elif app["status"] == "DENIED":
        _clear_decision_fields(app)
        app["status"] = "DEEMED_COMPLETE"
        touch.mark(app)

    if reopen:
        cycle_row["status"] = "COMPARATIVE_REVIEW"
        cycle_row["reopened_count"] = cycle_row["reopened_count"] + 1
        cycle_dirty = True
        for other in services.applications_of_cycle(cycle_row):
            if (other["id"] != app["id"] and other["status"] == "DENIED"
                    and other["denial_reason"] == "INSUFFICIENT_NEED"):
                _clear_decision_fields(other)
                other["status"] = "DEEMED_COMPLETE"
                touch.mark(other)
        _stale_sheets_and_rescore(cycle_row, touch)

    if cycle_dirty:
        touch.mark(cycle_row)


def remand_cascade(appeal_row, touch):
    """The appealed application is remanded; the rest of the batch is put back in contention."""
    app = store.get("applications", appeal_row["application_id"])
    if app is None:
        return
    cycle_row = services.cycle_of_application(app)
    cycle_dirty = False

    released = app["allocated_bed_count"]
    app["allocated_bed_count"] = 0
    _clear_decision_fields(app)
    app["status"] = "REMANDED"
    touch.mark(app)
    if released:
        services.credit_pool(cycle_row, released)
        cycle_dirty = True

    if cycle_row is not None:
        for other in services.applications_of_cycle(cycle_row):
            if other["id"] == app["id"]:
                continue
            if other["status"] not in ("APPROVED", "APPROVED_WITH_CONDITIONS", "DENIED"):
                continue
            released_other = other["allocated_bed_count"]
            other["allocated_bed_count"] = 0
            if released_other:
                services.credit_pool(cycle_row, released_other)
                cycle_dirty = True
            _clear_decision_fields(other)
            other["status"] = "DEEMED_COMPLETE"
            touch.mark(other)

        if cycle_row["status"] == "DECIDED":
            cycle_row["status"] = "COMPARATIVE_REVIEW"
            cycle_row["reopened_count"] = cycle_row["reopened_count"] + 1
            cycle_dirty = True
        _stale_sheets_and_rescore(cycle_row, touch)

    if cycle_dirty:
        touch.mark(cycle_row)


# --- comparative decision (PRD §3.7) ----------------------------------------

def run_comparative_decision(cycle_row, candidates):
    results, remaining = calc.allocation_waterfall(
        candidates, cycle_row["unmet_bed_need_at_open"])
    decided_at = clock.now()
    decision_at = clock.fmt(decided_at)
    window_closes = clock.fmt(clock.plus_days(decided_at, calc.APPEAL_WINDOW_DAYS))
    for app, outcome, beds in results:
        app["allocated_bed_count"] = beds
        app["status"] = outcome
        app["denial_reason"] = "INSUFFICIENT_NEED" if outcome == "DENIED" else None
        app["decision_at"] = decision_at
        app["appeal_window_closes_at"] = window_closes
        store.touch(app)
    cycle_row["unallocated_bed_need"] = remaining
    cycle_row["status"] = "DECIDED"
    store.touch(cycle_row)
    return results
