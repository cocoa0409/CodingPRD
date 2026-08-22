"""Tag-inventory reconciliation and adjudication (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import shape
from authz import PRODUCER, STATE_OFFICIAL, require_owner, require_roles
from db import base_record, store, touch
from errors import invalid_state, stale_version, unprocessable
from respond import success
from routes._common import premises_or_404, run_or_404
from serialize import public

bp = Blueprint("recon", __name__)

VARIANCE_TOLERANCE_PCT = Decimal("0.50")


@bp.post("/reconciliation-runs")
def open_run():
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    premises_id = shape.s_str(body, "premises_id")
    period_start = shape.s_date(body, "period_start")
    period_end = shape.s_date(body, "period_end")
    expected_version = shape.s_int(body, "expected_premises_version")
    premises = premises_or_404(premises_id)
    # Band 6 - a producer reconciles only its own premises.
    require_owner(premises["producer_id"] == uid)
    # Band 9 - optimistic concurrency on the parent premises.
    if expected_version != premises["version"]:
        raise stale_version("expected_premises_version does not match the premises version")
    # Band 13 - the period must be non-degenerate.
    if period_end < period_start:
        raise unprocessable("ERR_INVALID_WINDOW",
                            "period_end may not precede period_start")

    rec = base_record()
    rec.update({
        "premises_id": premises["id"],
        "period_start": period_start,
        "period_end": period_end,
        "physical_unapplied_count": None,
        "basis": None,
        "book_unapplied_count": None,
        "variance_count": None,
        "variance_pct": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    })
    store.recon_runs[rec["id"]] = rec
    # Opening a run supersedes stale overlapping DRAFT work on the same premises.
    for other in store.recon_runs.values():
        if other["id"] == rec["id"] or other["premises_id"] != premises["id"]:
            continue
        if other["status"] != "DRAFT":
            continue
        if other["period_start"] <= period_end and period_start <= other["period_end"]:
            other["status"] = "SUPERSEDED"
            touch(other)
    premises["last_reconciliation_run_at"] = store.now()
    touch(premises)
    return success(public(rec), status=201)


@bp.post("/reconciliation-runs/<run_id>/submit")
def submit_run(run_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    physical = shape.s_int(body, "physical_unapplied_count", minimum=0)
    run = run_or_404(run_id)
    premises = store.premises.get(run["premises_id"])
    # Band 6 - the owning producer submits the count.
    require_owner(premises is not None and premises["producer_id"] == uid)
    # Band 10 - own-state gate.
    if run["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT reconciliation run may be submitted")

    basis, book = derive.book_balance(premises, run["period_start"], run["period_end"])
    variance_count, variance_pct = calc.variance(physical, book)
    run.update({
        "physical_unapplied_count": physical,
        "basis": basis,
        "book_unapplied_count": book,
        "variance_count": variance_count,
        "variance_pct": variance_pct,
        "status": "SUBMITTED",
        "submitted_by_user_id": uid,
    })
    touch(run)
    return success(public(run))


@bp.post("/reconciliation-runs/<run_id>/approve")
def approve_run(run_id):
    uid, role = require_roles(STATE_OFFICIAL)
    run = run_or_404(run_id)
    # Band 10 - own-state gate.
    if run["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED reconciliation run may be adjudicated")
    premises = store.premises.get(run["premises_id"])
    run["approved_by_user_id"] = uid
    if run["variance_pct"] <= VARIANCE_TOLERANCE_PCT:
        run["status"] = "APPROVED"
        touch(run)
        if premises is not None and premises["registration_status"] == "SUSPENDED":
            premises["registration_status"] = "ACTIVE"
            touch(premises)
            derive.mark_producer(premises["producer_id"])
    else:
        # CASCADE-D.
        run["status"] = "VARIANCE_FLAGGED"
        touch(run)
        if premises is not None and premises["registration_status"] == "ACTIVE":
            premises["registration_status"] = "SUSPENDED"
            touch(premises)
            derive.mark_producer(premises["producer_id"], allow_lapse=True)
    return success(public(run))
