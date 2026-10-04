"""Certificates: issuance, renewal/reinstatement, CE entries (PRD 3.6, 3.7)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from dates import add_days, add_months, parse_date
from envelope import ok, ok_list, paginate
from errors import fail
from serializers import ser_ce_entry, ser_certificate
from services import (CE_PERIOD_MONTHS, RENEWAL_OPEN_DAYS,
                      REINSTATEMENT_WINDOW_MONTHS, ce_reinstatement_ok,
                      ce_renewal_ok, certificates_of, jurisdiction_by_code,
                      mint_serial, open_disciplinary_count)
from store import db, new_id, now_iso, stamp_new, today, touch

bp = Blueprint("certificate", __name__)


def _get_certificate_or_404(cert_id):
    c = db["certificates"].get(cert_id)
    if c is None:
        fail("ERR_NOT_FOUND", "certificate not found")
    return c


@bp.post("/candidates/<cid>/certificate")
def issue_certificate(cid):
    require_roles("NcarbAdministrator")
    cand = db["candidates"].get(cid)
    if cand is None:
        fail("ERR_NOT_FOUND", "candidate not found")
    # Tier 4: no non-REVOKED certificate already held.
    for c in certificates_of(cid):
        if c["status"] != "REVOKED":
            fail("ERR_CERTIFICATE_EXISTS",
                 "candidate already holds a non-REVOKED certificate")
    # Tier 5 (PRD 2.6 order): open disciplinary block, then eligibility.
    if open_disciplinary_count(cid) > 0:
        fail("ERR_OPEN_DISCIPLINARY_BLOCK",
             "an OPEN disciplinary report blocks certificate issuance")
    if not cand["certificate_eligible"]:
        fail("ERR_ELIGIBILITY_NOT_MET", "certificate_eligible is false")
    juris = jurisdiction_by_code(cand["home_jurisdiction_code"])
    issue_date = today()
    rec = stamp_new({
        "id": new_id(),
        "candidate_id": cid,
        "serial_number": mint_serial(),
        "home_jurisdiction_code": cand["home_jurisdiction_code"],
        # Snapshots: later board edits do not retroactively change obligations.
        "ce_hours_required": juris["ce_hours_required"] if juris else 24,
        "ce_hsw_hours_required": juris["ce_hsw_hours_required"] if juris else 12,
        "status": "ACTIVE",
        "issued_at": now_iso(),
        "period_start": issue_date.isoformat(),
        "period_end": add_months(issue_date, CE_PERIOD_MONTHS).isoformat(),
        "renewal_count": 0,
        # Internal carry bookkeeping (not serialized): previous period bounds.
        "_prev_period": None,
    })
    db["certificates"][rec["id"]] = rec
    return ok(ser_certificate(rec), 201)


@bp.get("/candidates/<cid>/certificate")
def get_candidate_certificate(cid):
    uid, role = require_roles("Candidate", "NcarbAdministrator", "BoardAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    rows = sorted(certificates_of(cid), key=lambda c: c["created_at"])
    certs = [ser_certificate(c) for c in rows]
    return ok_list(certs, len(certs), 10, 0)


@bp.get("/certificates/<cert_id>")
def get_certificate(cert_id):
    uid, role = require_roles("Candidate", "NcarbAdministrator", "BoardAdministrator")
    cert = _get_certificate_or_404(cert_id)
    if role == "Candidate":
        require_candidate_identity(uid, cert["candidate_id"])
    return ok(ser_certificate(cert))


@bp.post("/certificates/<cert_id>/renew")
def renew_certificate(cert_id):
    uid, _ = require_roles("Candidate")
    cert = _get_certificate_or_404(cert_id)
    require_candidate_identity(uid, cert["candidate_id"])
    current = today()
    if cert["status"] == "ACTIVE":
        pe = parse_date(cert["period_end"])
        # Half-open renewal window: [period_end - 60 days, period_end).
        if not (add_days(pe, -RENEWAL_OPEN_DAYS) <= current < pe):
            fail("ERR_RENEWAL_WINDOW_NOT_OPEN",
                 "renewal is open only within 60 days before period_end")
        if not ce_renewal_ok(cert):
            fail("ERR_CE_HOURS_INSUFFICIENT",
                 "CE totals do not meet the renewal requirements")
        old_start, old_end = cert["period_start"], cert["period_end"]
        cert["period_start"] = old_end
        cert["period_end"] = add_months(parse_date(old_end),
                                        CE_PERIOD_MONTHS).isoformat()
        cert["renewal_count"] += 1
        cert["_prev_period"] = (old_start, old_end)
        touch(cert)
    elif cert["status"] == "LAPSED":
        pe = parse_date(cert["period_end"])
        # Reinstatement window is inclusive through period_end + 12 months.
        if current > add_months(pe, REINSTATEMENT_WINDOW_MONTHS):
            fail("ERR_REINSTATEMENT_WINDOW_CLOSED",
                 "more than 12 calendar months have passed since period_end")
        if not ce_reinstatement_ok(cert):
            fail("ERR_CE_HOURS_INSUFFICIENT",
                 "reinstatement CE requirements (strict, +4 HSW penalty) not met")
        cert["status"] = "ACTIVE"
        cert["period_start"] = current.isoformat()
        cert["period_end"] = add_months(current, CE_PERIOD_MONTHS).isoformat()
        cert["renewal_count"] += 1
        cert["_prev_period"] = None  # carry resets to zero after reinstatement
        touch(cert)
    else:
        fail("ERR_INVALID_STATE", "a REVOKED certificate cannot be renewed")
    return ok(ser_certificate(cert))


@bp.post("/certificates/<cert_id>/ce-entries")
def create_ce_entry(cert_id):
    uid, _ = require_roles("Candidate")
    cert = _get_certificate_or_404(cert_id)
    require_candidate_identity(uid, cert["candidate_id"])
    # Entries may be logged while the certificate is ACTIVE or LAPSED.
    if cert["status"] not in ("ACTIVE", "LAPSED"):
        fail("ERR_INVALID_STATE",
             "CE entries may be logged only while ACTIVE or LAPSED")
    body = get_body()
    completed_raw = body.get("completed_date")
    completed = None
    if completed_raw is not None:
        try:
            completed = parse_date(completed_raw)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", "completed_date must be an ISO date")
    # Tier 7: completed_date must not be in the future.
    if completed is not None and completed > today():
        fail("ERR_CE_ENTRY_INVALID", "completed_date is in the future")
    # Tier 8: required fields and ranges.
    hours = body.get("hours")
    if not isinstance(hours, int) or isinstance(hours, bool):
        fail("ERR_INVALID_REQUEST", "hours must be an integer")
    if hours < 1 or hours > 24:
        fail("ERR_CE_ENTRY_INVALID", "hours must be between 1 and 24")
    hsw = body.get("hsw")
    if not isinstance(hsw, bool):
        fail("ERR_INVALID_REQUEST", "hsw must be a boolean")
    if completed is None:
        fail("ERR_INVALID_REQUEST", "completed_date is required")
    provider = body.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        fail("ERR_INVALID_REQUEST", "provider is required")
    rec = stamp_new({
        "id": new_id(),
        "certificate_id": cert_id,
        "hours": hours,
        "hsw": hsw,
        "completed_date": completed.isoformat(),
        "provider": provider,
        "voided": False,
    })
    db["ce_entries"][rec["id"]] = rec
    return ok(ser_ce_entry(rec), 201)


@bp.get("/certificates/<cert_id>/ce-entries")
def list_ce_entries(cert_id):
    uid, role = require_roles("Candidate", "NcarbAdministrator")
    cert = _get_certificate_or_404(cert_id)
    if role == "Candidate":
        require_candidate_identity(uid, cert["candidate_id"])
    voided_raw = request.args.get("voided")
    rows = [e for e in db["ce_entries"].values()
            if e["certificate_id"] == cert_id]
    if voided_raw is not None:
        low = voided_raw.strip().lower()
        if low in ("true", "1"):
            rows = [e for e in rows if e["voided"]]
        elif low in ("false", "0"):
            rows = [e for e in rows if not e["voided"]]
        else:
            fail("ERR_INVALID_REQUEST", "voided must be true or false")
    return paginate([ser_ce_entry(e) for e in rows])


@bp.post("/ce-entries/<eid>/void")
def void_ce_entry(eid):
    uid, _ = require_roles("Candidate")
    e = db["ce_entries"].get(eid)
    if e is None:
        fail("ERR_NOT_FOUND", "CE entry not found")
    cert = db["certificates"].get(e["certificate_id"])
    if cert is not None:
        require_candidate_identity(uid, cert["candidate_id"])
    e["voided"] = True
    touch(e)
    return ok(ser_ce_entry(e))
