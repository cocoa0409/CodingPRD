"""Credibility disclosures and the public complaint-outcome report."""
import re
from decimal import Decimal

from flask import Blueprint

import calc
import svc
from core import (
    ApiError,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_str,
    fmt_dt,
    paginate,
    parse_dt,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("records", __name__)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Credibility disclosures
# ---------------------------------------------------------------------------
@bp.get("/credibility-disclosures/<disclosure_id>")
@endpoint("RecordsCustodian", "IACommander", "AppealsOfficer", "OfficerRepresentative")
def read_disclosure(disclosure_id):
    return respond_object(dump(svc.need_disclosure(disclosure_id)))


@bp.get("/credibility-disclosures")
@endpoint("RecordsCustodian", "IACommander", "AppealsOfficer", "OfficerRepresentative")
def list_disclosures():
    officer_id = q_str("officer_id")
    source_allegation_id = q_str("source_allegation_id")
    status = q_enum("status", calc.DISCLOSURE_STATUSES)
    basis = q_enum("basis", calc.DISCLOSURE_BASES)
    rows = sort_created(list(db.disclosures.values()))
    if officer_id is not None:
        rows = [r for r in rows if r["officer_id"] == officer_id]
    if source_allegation_id is not None:
        rows = [
            r for r in rows if r["source_allegation_id"] == source_allegation_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    return paginate(rows)


@bp.post("/credibility-disclosures/<disclosure_id>/release")
@endpoint("RecordsCustodian")
def release_disclosure(disclosure_id):
    disclosure = svc.need_disclosure(disclosure_id)
    payload = body()
    # tier 4 -- schema
    f_str(payload, "requesting_party")
    # tier 8 -- state legality
    if disclosure["status"] != "ACTIVE":
        raise ApiError("ERR_DISCLOSURE_NOT_ACTIVE")

    disclosure["release_count"] += 1
    disclosure["last_released_at"] = db.clock
    touch(disclosure)
    return respond_object(dump(disclosure))


# ---------------------------------------------------------------------------
# Complaint-outcome report
# ---------------------------------------------------------------------------
def _period(key):
    raw = q_str(key)
    if raw is None:
        bad_request("Query parameter '%s' is required." % key)
    if _DATE_ONLY.match(raw.strip()):
        raw = raw.strip() + "T00:00:00Z"
    parsed = parse_dt(raw)
    if parsed is None:
        bad_request("Query parameter '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


def _group_entry(group_key, total, sustained, suppressed):
    if suppressed:
        return {
            "group_key": group_key,
            "total_complaints": None,
            "sustained_complaints": None,
            "sustain_rate_pct": None,
            "suppressed": True,
        }
    return {
        "group_key": group_key,
        "total_complaints": total,
        "sustained_complaints": sustained,
        "sustain_rate_pct": calc.sustain_rate(sustained, total),
        "suppressed": False,
    }


@bp.get("/reports/complaint-outcomes")
@endpoint("RecordsCustodian", "IACommander", "SystemAdmin")
def complaint_outcome_report():
    # tier 4 -- schema
    period_start = _period("period_start")
    period_end = _period("period_end")
    breakdown = q_enum("breakdown", calc.BREAKDOWNS)
    # tier 11 -- temporal rules
    if period_start > period_end:
        raise ApiError("ERR_INVALID_REPORT_PERIOD")

    population = []
    for complaint in sort_created(list(db.complaints.values())):
        if complaint["status"] not in ("CLOSED", "WITHDRAWN", "PURGED"):
            continue
        closed_at = complaint.get("closed_at")
        if closed_at is None:
            continue
        if closed_at < period_start or closed_at > period_end:
            continue
        population.append(complaint)

    total_complaints = len(population)
    sustained_complaints = sum(
        1 for c in population if c["sustained_allegation_count"] >= 1
    )

    buckets = {}
    for complaint in population:
        if breakdown == "DEMOGRAPHIC":
            key = complaint["complainant_demographic_code"] or "UNKNOWN"
        elif breakdown == "CHANNEL":
            key = complaint["intake_channel"]
        else:
            key = "ALL"
        entry = buckets.setdefault(key, [0, 0])
        entry[0] += 1
        if complaint["sustained_allegation_count"] >= 1:
            entry[1] += 1

    groups = []
    suppressed_total = 0
    suppressed_sustained = 0
    any_suppressed = False
    for key in sorted(buckets.keys()):
        total, sustained = buckets[key]
        if total < calc.SUPPRESSION_MIN_CELL:
            any_suppressed = True
            suppressed_total += total
            suppressed_sustained += sustained
            groups.append(_group_entry(key, total, sustained, True))
        else:
            groups.append(_group_entry(key, total, sustained, False))
    if any_suppressed:
        groups.append(
            _group_entry("SUPPRESSED", suppressed_total, suppressed_sustained, False)
        )

    return respond_object(
        {
            "period_start": fmt_dt(period_start),
            "period_end": fmt_dt(period_end),
            "breakdown": breakdown or "ALL",
            "total_complaints": total_complaints,
            "sustained_complaints": sustained_complaints,
            "sustain_rate_pct": calc.sustain_rate(
                sustained_complaints, total_complaints
            ),
            "suppression_min_cell": calc.SUPPRESSION_MIN_CELL,
            "groups": groups,
        }
    )
