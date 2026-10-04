"""CarrierAgreement: filing, competitive monitoring reports (pinned HHI
rounding), go-effective (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_AGREEMENT_MEMBERSHIP,
    ERR_MEMBER_SET_MISMATCH,
    ERR_MONITORING_PERIOD_OVERLAP,
    ERR_AGREEMENT_NOT_AWAITING_REVIEW,
    ERR_WAITING_PERIOD_NOT_ELAPSED,
    ERR_COMPETITIVE_CONCERN_UNRESOLVED,
)
from serialization import ser_agreement
from services import calc
from store import touch
from util import body, req_str, req_int, req_enum, req_dt
from constants import AGREEMENT_WAITING_PERIOD_DAYS, HHI_THRESHOLD

bp = Blueprint("agreements", __name__)

AGREEMENT_TYPES = (
    "VESSEL_SHARING",
    "RATE_DISCUSSION",
    "EQUIPMENT_POOLING",
    "SPACE_CHARTER",
)


@bp.post("/fmc/carrier-agreements")
def file_agreement():
    uid, _role = require_roles("CarrierRep")
    b = body()
    mcids = b.get("member_carrier_ids")
    # Rung 5 (body-reference existence) precedes rung 6 (scalar sanity).
    if isinstance(mcids, list):
        for m in mcids:
            if isinstance(m, str) and m not in store.carriers:
                fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % m)
    agreement_number = req_str(b, "agreement_number")
    agreement_type = req_enum(b, "agreement_type", AGREEMENT_TYPES)
    if (
        not isinstance(mcids, list)
        or any(not isinstance(m, str) for m in mcids)
    ):
        fail(ERR_INVALID_REQUEST,
             "member_carrier_ids must be an array of carrier id strings")
    distinct = set(mcids)
    if len(distinct) < 2:
        fail(ERR_INVALID_AGREEMENT_MEMBERSHIP,
             "an agreement requires at least two distinct member carriers")
    for m in distinct:
        c = store.carriers.get(m)
        if c is None or c["org_type"] != "VOCC" or c["status"] != "ACTIVE":
            fail(ERR_INVALID_AGREEMENT_MEMBERSHIP,
                 "every member must be a vessel-operating common carrier in "
                 "ACTIVE standing")
    if uid not in distinct:
        fail(ERR_INVALID_AGREEMENT_MEMBERSHIP,
             "the filing carrier's own organization must appear among the members")

    now = CLOCK.now()
    rec = store.base_record()
    rec.update(
        agreement_number=agreement_number,
        agreement_type=agreement_type,
        member_carrier_ids=list(mcids),
        filed_by_carrier_id=uid,
        filed_at=now,
        waiting_period_ends_at=now + timedelta(days=AGREEMENT_WAITING_PERIOD_DAYS),
        review_status="AWAITING_REVIEW",
        monitoring_reports=[],
        market_concentration_hhi=None,
        competitive_concern_flag=False,
    )
    store.agreements[rec["id"]] = rec
    return ok_object(ser_agreement(rec), 201)


@bp.get("/fmc/carrier-agreements")
def list_agreements():
    any_role()
    member = request.args.get("member_carrier_ids")
    filed_by = request.args.get("filed_by_carrier_id")
    recs = list(store.agreements.values())
    if member is not None:
        recs = [a for a in recs if member in a["member_carrier_ids"]]
    if filed_by is not None:
        recs = [a for a in recs if a["filed_by_carrier_id"] == filed_by]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_agreement(a) for a in page], limit, offset, total)


@bp.get("/fmc/carrier-agreements/<agreementId>")
def get_agreement(agreementId):
    any_role()
    a = store.agreements.get(agreementId)
    if a is None:
        fail(ERR_AGREEMENT_NOT_FOUND, "carrier agreement not found: %s" % agreementId)
    return ok_object(ser_agreement(a))


@bp.post("/fmc/carrier-agreements/<agreementId>/go-effective")
def go_effective(agreementId):
    require_roles("ComplianceReviewer")
    a = store.agreements.get(agreementId)
    if a is None:
        fail(ERR_AGREEMENT_NOT_FOUND, "carrier agreement not found: %s" % agreementId)
    if a["review_status"] != "AWAITING_REVIEW":
        fail(ERR_AGREEMENT_NOT_AWAITING_REVIEW,
             "go-effective requires review_status AWAITING_REVIEW")
    if CLOCK.now() < a["waiting_period_ends_at"]:
        fail(ERR_WAITING_PERIOD_NOT_ELAPSED,
             "the 45-day waiting period has not elapsed")
    if a["competitive_concern_flag"]:
        fail(ERR_COMPETITIVE_CONCERN_UNRESOLVED,
             "the latest monitoring report's HHI is at or above 2500")
    a["review_status"] = "EFFECTIVE"
    touch(a)
    return ok_object(ser_agreement(a))


@bp.post("/fmc/carrier-agreements/<agreementId>/monitoring-reports")
def append_monitoring_report(agreementId):
    uid, _role = require_roles("CarrierRep")
    a = store.agreements.get(agreementId)
    if a is None:
        fail(ERR_AGREEMENT_NOT_FOUND, "carrier agreement not found: %s" % agreementId)
    if uid not in set(a["member_carrier_ids"]):
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only a member carrier may file monitoring reports on an agreement")
    b = body()
    start = req_dt(b, "reporting_period_start")
    end = req_dt(b, "reporting_period_end")
    total_market_teus = req_int(b, "total_market_teus", lo=1)
    mv = b.get("member_volumes")
    if not isinstance(mv, list):
        fail(ERR_INVALID_REQUEST, "member_volumes must be an array")
    entries = []
    for e in mv:
        if not isinstance(e, dict):
            fail(ERR_INVALID_REQUEST, "member_volumes entries must be objects")
        entries.append({
            "carrier_id": req_str(e, "carrier_id"),
            "carried_teus": req_int(e, "carried_teus", lo=0),
        })
    if not end > start:
        fail(ERR_INVALID_REQUEST,
             "reporting_period_end must be later than reporting_period_start")
    # member_volumes must cover exactly the member set (referential integrity
    # flows through the agreement, not a table FK — no separate 404 here).
    member_set = set(a["member_carrier_ids"])
    entry_ids = [e["carrier_id"] for e in entries]
    if set(entry_ids) != member_set or len(entry_ids) != len(set(entry_ids)):
        fail(ERR_MEMBER_SET_MISMATCH,
             "member_volumes must cover exactly the agreement's member set")
    for r in a["monitoring_reports"]:
        if start < r["reporting_period_end"] and r["reporting_period_start"] < end:
            fail(ERR_MONITORING_PERIOD_OVERLAP,
                 "reporting periods are half-open [start, end) and must not "
                 "overlap within the agreement")

    hhi = calc.monitoring_hhi(entries, total_market_teus)
    report = {
        "reporting_period_start": start,
        "reporting_period_end": end,
        "total_market_teus": total_market_teus,
        "member_volumes": entries,
        "hhi": hhi,
    }
    a["monitoring_reports"].append(report)
    latest = max(a["monitoring_reports"], key=lambda r: r["reporting_period_end"])
    a["market_concentration_hhi"] = latest["hhi"]
    a["competitive_concern_flag"] = latest["hhi"] >= HHI_THRESHOLD
    touch(a)
    return ok_object(ser_agreement(a), 201)
