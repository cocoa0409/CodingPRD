"""PayoutBatch and PayoutLine endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint

from calc import resolve_rate, session_rate_cents
from errors import fail
from middleware import Body, identity, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    SCHEDULES,
    all_rows,
    create_row,
    get,
    payout_balance_cents,
    require,
    set_derived,
    sort_asc,
    touch,
)
from util import fmt_ts, now, parse_ts

bp = Blueprint("payouts", __name__)

BATCH_STATUSES = {"OPEN", "LOCKED", "PAID", "RECONCILED", "SKIPPED"}
LINE_STATUSES = {"PENDING", "PAID", "CLAWED_BACK", "VOIDED"}


def _batch_or_404(batch_id):
    return require("payout_batches", batch_id, "ERR_BATCH_NOT_FOUND")


def refresh_batch_totals(batch_id):
    batch = get("payout_batches", batch_id)
    if batch is None:
        return
    lines = [
        l
        for l in all_rows("payout_lines")
        if l.get("payout_batch_id") == batch_id and l.get("line_status") != "VOIDED"
    ]
    set_derived(batch, "total_gross_cents", sum(int(l.get("gross_cents") or 0) for l in lines))
    set_derived(batch, "total_adjustment_cents", sum(int(l.get("adjustment_cents") or 0) for l in lines))
    set_derived(batch, "total_net_cents", sum(int(l.get("net_cents") or 0) for l in lines))
    set_derived(batch, "line_count", len(lines))


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- batches


@bp.post("/payout-batches")
@require_roles("OpsAdmin")
def create_batch():
    ident = identity()
    body = Body.read()
    period_start = body.instant("period_start")
    period_end = body.instant("period_end")
    schedule = body.enum("schedule", SCHEDULES)
    body.finish()
    if period_end <= period_start:
        raise fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")

    superseded = None
    for other in all_rows("payout_batches"):
        if other.get("status") != "OPEN":
            continue
        if other.get("schedule") != schedule:
            continue
        other_start = parse_ts(other.get("period_start"))
        other_end = parse_ts(other.get("period_end"))
        if other_start is None or other_end is None:
            continue
        if not _overlaps(period_start, period_end, other_start, other_end):
            continue
        if (other.get("created_at") or "") >= fmt_ts(now()) + "z":
            continue
        if superseded is None or (other.get("created_at") or "") > (superseded.get("created_at") or ""):
            superseded = other

    row = create_row(
        "payout_batches",
        period_start=fmt_ts(period_start),
        period_end=fmt_ts(period_end),
        schedule=schedule,
        status="OPEN",
        total_gross_cents=0,
        total_adjustment_cents=0,
        total_net_cents=0,
        line_count=0,
        created_by_user_id=ident["id"],
        supersedes_batch_id=None,
    )

    if superseded is not None:
        superseded["status"] = "SKIPPED"
        for line in all_rows("payout_lines"):
            if line.get("payout_batch_id") != superseded["id"]:
                continue
            if line.get("line_status") == "VOIDED":
                continue
            line["line_status"] = "VOIDED"
            touch(line)
        row["supersedes_batch_id"] = superseded["id"]
        touch(superseded)
        refresh_batch_totals(superseded["id"])
    return ok(ser("payout_batches", row), 201)


@bp.get("/payout-batches")
@require_roles("OpsAdmin", "Clinician", "PayrollService")
def list_batches():
    status = qenum("status", BATCH_STATUSES)
    schedule = qenum("schedule", SCHEDULES)
    out = [ser("payout_batches", r) for r in sort_asc(all_rows("payout_batches"))]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    if schedule is not None:
        out = [r for r in out if r.get("schedule") == schedule]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/payout-batches/<batch_id>")
@require_roles("OpsAdmin", "Clinician", "PayrollService")
def get_batch(batch_id):
    row = _batch_or_404(batch_id)
    return ok(ser("payout_batches", row), 200)


@bp.get("/payout-batches/<batch_id>/lines")
@require_roles("OpsAdmin", "Clinician", "PayrollService")
def list_lines(batch_id):
    _batch_or_404(batch_id)
    status = qenum("line_status", LINE_STATUSES)
    out = [
        ser("payout_lines", r)
        for r in sort_asc(all_rows("payout_lines"))
        if r.get("payout_batch_id") == batch_id
    ]
    if status is not None:
        out = [r for r in out if r.get("line_status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/clinicians/<clinician_id>/payout-lines")
@require_roles("OpsAdmin", "Clinician")
def list_clinician_lines(clinician_id):
    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    status = qenum("line_status", LINE_STATUSES)
    out = [
        ser("payout_lines", r)
        for r in sort_asc(all_rows("payout_lines"))
        if r.get("clinician_id") == clinician_id
    ]
    if status is not None:
        out = [r for r in out if r.get("line_status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


# ---------------------------------------------------------------- line build


def _in_window(session, start, end):
    scheduled_end = parse_ts(session.get("scheduled_end"))
    if scheduled_end is None:
        return False
    return start <= scheduled_end < end


def _newest_claim(session_id):
    claims = [c for c in all_rows("claims") if c.get("session_id") == session_id]
    if not claims:
        return None
    return sorted(claims, key=lambda c: (c.get("created_at") or "", c.get("id") or ""))[-1]


def _carried_clawback_cents(clinician, batch_id) -> int:
    """The positive magnitude of clawbacks already written on this clinician's
    *other* lines, which the batch being built takes up.  Zero when there is
    none, so the caller can distinguish "no clawback" from "a clawback of zero".
    """
    total = 0
    for line in all_rows("payout_lines"):
        if line.get("clinician_id") != clinician["id"]:
            continue
        if line.get("payout_batch_id") == batch_id:
            continue
        if line.get("line_status") in ("VOIDED", "PENDING"):
            continue
        adjustment = int(line.get("adjustment_cents") or 0)
        if adjustment < 0:
            total += -adjustment
    return total


def _eligible_sessions(clinician, start, end, cash_basis):
    included = []
    for session in all_rows("sessions"):
        if session.get("clinician_id") != clinician["id"]:
            continue
        if session.get("status") != "COMPLETED":
            continue
        if not _in_window(session, start, end):
            continue
        if cash_basis:
            claim = _newest_claim(session["id"])
            if claim is None or claim.get("claim_status") != "PAID":
                continue
        included.append(session)
    return included


def _build_line(batch, clinician, cash_basis):
    start = parse_ts(batch.get("period_start"))
    end = parse_ts(batch.get("period_end"))
    sessions = _eligible_sessions(clinician, start, end, cash_basis)
    # A line is materialised for every clinician with at least one eligible
    # session, and additionally when a carried clawback has to live somewhere;
    # such a line is the "new `PENDING` line with a `gross_cents` of 0" of §3.8.
    carried = _carried_clawback_cents(clinician, batch["id"])
    if not sessions and carried <= 0:
        return None
    sessions.sort(key=lambda s: (s.get("scheduled_end") or "", s.get("id") or ""))

    gross = 0
    session_ids = []
    claim_ids = []
    for session in sessions:
        gross += session_rate_cents(session)
        session_ids.append(session["id"])
        claim = _newest_claim(session["id"])
        if claim is not None:
            claim_ids.append(claim["id"])
            claim["assigned_payout_line_id"] = None

    residual = int(clinician.get("pending_clawback_residual_cents") or 0)
    adjustment = -carried - residual if (carried > 0 or residual > 0) else 0
    clinician["pending_clawback_residual_cents"] = 0

    newest = sessions[-1] if sessions else None
    version_used = None
    if newest is not None:
        _, chosen = resolve_rate(clinician, get("patients", newest.get("patient_id")), newest)
        version_used = int(chosen.get("rate_set_version") or 0) if chosen is not None else None

    line = create_row(
        "payout_lines",
        payout_batch_id=batch["id"],
        clinician_id=clinician["id"],
        session_ids=session_ids,
        claim_ids=claim_ids,
        gross_cents=gross,
        adjustment_cents=adjustment,
        # A carried clawback is the reversal of an earning that was already
        # disbursed, so it is allowed to drive the net negative and be seen:
        # PRD §3.6, "a `PAID` line's net may go negative when a clawback exceeds
        # its gross and the floor applies only to pending lines", and §3.6's
        # balance rule explains that this negative value "flows into the balance
        # unchanged ... the reversal carried against a future payout".  The
        # zero-floor applies only to a line whose own sessions are still unpaid.
        net_cents=(gross + adjustment) if carried > 0 else max(0, gross + adjustment),
        line_status="PENDING",
        basis="CASH_BASIS" if cash_basis else "SCHEDULED",
        rate_set_version_used=version_used,
    )
    for claim in all_rows("claims"):
        if claim.get("id") in claim_ids:
            claim["assigned_payout_line_id"] = line["id"]
    return line


@bp.post("/payout-batches/<batch_id>/lock")
@require_roles("OpsAdmin")
def lock_batch(batch_id):
    batch = _batch_or_404(batch_id)
    if batch.get("status") != "OPEN":
        raise fail("ERR_BATCH_NOT_LOCKABLE")
    period_end = parse_ts(batch.get("period_end"))
    if period_end is None or period_end > now():
        raise fail("ERR_BATCH_NOT_LOCKABLE")

    schedule = batch.get("schedule")
    cash_basis_schedule = schedule == "SEMIMONTHLY"

    planned = []
    for clinician in all_rows("clinicians"):
        cash_basis = cash_basis_schedule or bool(clinician.get("cash_basis_opt_in"))
        sessions = _eligible_sessions(
            clinician,
            parse_ts(batch.get("period_start")),
            parse_ts(batch.get("period_end")),
            cash_basis,
        )
        carried = _carried_clawback_cents(clinician, batch["id"])
        if sessions or carried > 0:
            planned.append((clinician, cash_basis))

    existing = [
        l
        for l in all_rows("payout_lines")
        if l.get("payout_batch_id") == batch_id and l.get("line_status") != "VOIDED"
    ]
    if not planned and not existing:
        raise fail("ERR_BATCH_NOT_LOCKABLE")

    for clinician, cash_basis in planned:
        _build_line(batch, clinician, cash_basis)


    batch["status"] = "LOCKED"
    refresh_batch_totals(batch_id)
    touch(batch)
    return ok(ser("payout_batches", batch), 200)


@bp.post("/payout-batches/<batch_id>/pay")
@require_roles("OpsAdmin", "PayrollService")
def pay_batch(batch_id):
    batch = _batch_or_404(batch_id)
    if batch.get("status") != "LOCKED":
        raise fail("ERR_BATCH_NOT_PAYABLE")
    lines = [
        l
        for l in all_rows("payout_lines")
        if l.get("payout_batch_id") == batch_id and l.get("line_status") != "VOIDED"
    ]
    if any(l.get("line_status") not in ("PENDING", "PAID") for l in lines):
        raise fail("ERR_BATCH_NOT_PAYABLE")

    batch["status"] = "PAID"
    for line in lines:
        if line.get("line_status") != "PENDING":
            continue
        line["line_status"] = "PAID"
        touch(line)
        clinician = get("clinicians", line.get("clinician_id"))
        if clinician is not None:
            set_derived(clinician, "payout_balance_cents", payout_balance_cents(clinician))
            touch(clinician)
    refresh_batch_totals(batch_id)
    touch(batch)
    return ok(ser("payout_batches", batch), 200)


@bp.post("/payout-batches/<batch_id>/reconcile")
@require_roles("OpsAdmin")
def reconcile_batch(batch_id):
    batch = _batch_or_404(batch_id)
    # PRD §3.6: reconciling "closes the batch ... and the batch lands terminally
    # in `RECONCILED`".  §2.9 makes a resource "already sitting in a terminal
    # state that admits no further transition" report `ERR_ALREADY_TERMINAL`
    # rather than the generic state error.
    if batch.get("status") == "RECONCILED":
        raise fail("ERR_ALREADY_TERMINAL")
    if batch.get("status") != "PAID":
        raise fail("ERR_INVALID_STATE")
    lines = [
        l
        for l in all_rows("payout_lines")
        if l.get("payout_batch_id") == batch_id and l.get("line_status") != "VOIDED"
    ]
    if any(l.get("line_status") not in ("PAID", "CLAWED_BACK") for l in lines):
        raise fail("ERR_BATCH_NOT_PAYABLE")

    batch["status"] = "RECONCILED"
    refresh_batch_totals(batch_id)
    touch(batch)
    return ok(ser("payout_batches", batch), 200)


@bp.post("/payout-batches/<batch_id>/supersede")
@require_roles("OpsAdmin")
def supersede_batch(batch_id):
    batch = _batch_or_404(batch_id)
    body = Body.read()
    expected = body.version("expected_open_batch_version")
    body.finish()

    if int(batch.get("version") or 1) != expected:
        raise fail("ERR_STALE_VERSION")
    if batch.get("status") != "OPEN":
        raise fail("ERR_INVALID_STATE")

    for line in all_rows("payout_lines"):
        if line.get("payout_batch_id") != batch_id:
            continue
        if line.get("line_status") == "VOIDED":
            continue
        line["line_status"] = "VOIDED"
        touch(line)
    batch["status"] = "SKIPPED"
    refresh_batch_totals(batch_id)
    touch(batch)
    return ok(ser("payout_batches", batch), 200)