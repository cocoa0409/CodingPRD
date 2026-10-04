"""Compliance monitoring periods and per-term findings (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import db
import envelope
import errors
import serialize
import services
import validate

bp = Blueprint("monitoring", __name__, url_prefix="/multistate")

OUTCOMES = ("COMPLIANT", "BREACH")


@bp.route("/settlements/<settlement_id>/monitoring-periods", methods=["POST"])
def open_period(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "EXECUTED":
        raise errors.invalid_state("Monitoring periods open only against an EXECUTED settlement")
    existing = sorted(
        (p for p in db.periods.values() if p["settlement_id"] == st["id"]),
        key=lambda p: p["period_index"],
    )
    # Rung 10: contiguity — the previous period must exist and be CLOSED_*.
    if existing and existing[-1]["status"] == "OPEN":
        raise errors.ApiError(
            "ERR_PERIOD_NOT_CONTIGUOUS",
            409,
            "Previous monitoring period is still OPEN",
        )
    period_index = len(existing) + 1
    window_start = st["executed_at"] + timedelta(
        days=(period_index - 1) * calc.MONITORING_PERIOD_DAYS
    )
    # Rung 10: the period cannot open before its window_start.
    if db.now() < window_start:
        raise errors.ApiError(
            "ERR_PERIOD_NOT_STARTED",
            422,
            "Monitoring period cannot open before its window_start",
        )
    # Rung 11: period cap.
    if period_index > calc.MONITORING_MAX_PERIODS:
        raise errors.ApiError(
            "ERR_PERIOD_LIMIT_REACHED",
            422,
            "Monitoring period index would exceed MONITORING_MAX_PERIODS (6)",
        )
    period = db.new_entity(db.periods)
    period.update(
        {
            "settlement_id": st["id"],
            "period_index": period_index,
            "window_start": window_start,
            "window_end": window_start + timedelta(days=calc.MONITORING_PERIOD_DAYS),
            "findings": [],
            "breach_count": 0,
            "status": "OPEN",
            "closed_at": None,
        }
    )
    return envelope.success_object(serialize.serialize("period", period), 201)


@bp.route("/settlements/<settlement_id>/monitoring-periods", methods=["GET"])
def list_periods(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_settlement_or_404(settlement_id)
    items = [p for p in db.periods.values() if p["settlement_id"] == settlement_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("period", page), limit, offset, total
    )


@bp.route("/monitoring-periods/<period_id>/findings", methods=["POST"])
def file_finding(period_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("ComplianceMonitor",))
    body = validate.body_json()
    term_index = validate.req_int(body, "term_index")
    outcome = validate.req_enum(body, "outcome", OUTCOMES)
    note = validate.opt_str(body, "note")
    period = validate.get_period_or_404(period_id)
    if period["status"] != "OPEN":
        raise errors.invalid_state("Monitoring period is not OPEN")
    st = db.settlements.get(period["settlement_id"])
    terms = st["injunctive_terms"]
    if term_index < 0 or term_index >= len(terms):
        raise errors.ApiError(
            "ERR_INVALID_TERM_INDEX",
            422,
            "term_index is out of range of the settlement's injunctive_terms",
        )
    for finding in period["findings"]:
        if finding["term_index"] == term_index:
            raise errors.ApiError(
                "ERR_DUPLICATE_FINDING",
                409,
                "A finding for this term_index already exists in this monitoring period",
            )
    now = db.now()
    period["findings"].append(
        {
            "term_index": term_index,
            "outcome": outcome,
            "note": note,
            "filed_at": now,
            "_seq": db.next_seq(),
        }
    )
    # Auto-close the moment every injunctive term has a finding.
    if len(period["findings"]) == len(terms):
        breach_count = sum(1 for f in period["findings"] if f["outcome"] == "BREACH")
        period["breach_count"] = breach_count
        period["closed_at"] = now
        st_dirty = False
        if breach_count >= calc.BREACH_ESCALATION_THRESHOLD:
            period["status"] = "CLOSED_BREACH"
            st["compliance_hold"] = True
            st_dirty = True
            for disb in services.settlement_disbursements(st["id"]):
                if disb["status"] == "CERTIFIED":
                    disb["status"] = "HELD"
                    db.touch(disb)
        else:
            period["status"] = "CLOSED_COMPLIANT"
            if breach_count == 0:
                if st["compliance_hold"]:
                    st["compliance_hold"] = False
                    st_dirty = True
                    for disb in services.settlement_disbursements(st["id"]):
                        if disb["status"] == "HELD":
                            disb["status"] = "CERTIFIED"
                            db.touch(disb)
                if (
                    period["period_index"] == calc.MONITORING_MAX_PERIODS
                    and st["fund_status"] == "DISBURSED"
                ):
                    st["term_status"] = "CLOSED_OUT"
                    st_dirty = True
                    inv = db.investigations.get(st["investigation_id"])
                    if inv is not None and inv["phase"] == "MONITORING":
                        inv["phase"] = "CLOSED"
                        db.touch(inv)
        if st_dirty:
            db.touch(st)
    db.touch(period)
    return envelope.success_object(serialize.serialize("period", period), 201)
