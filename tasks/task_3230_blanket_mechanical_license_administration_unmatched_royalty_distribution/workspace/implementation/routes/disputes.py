"""Dispute endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_dispute, get_work, get_claim
from postings import queue_matched_postings, drop_postings_for_line
from response import ok_list, ok_object
from util import body_json, make_record, touch, ts_now

bp = Blueprint("disputes", __name__)

ADMIN = ("MLCAdministrator",)
WRITE = ("MLCAdministrator", "MemberUser")
READ = ("MLCAdministrator", "MemberUser", "PublicSearcher")


def dispute_view(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def open_dispute_internal(work_id, share_context, initiating_claim_id,
                          extra_claim_ids=()):
    """Shared logic for POST /mlc/disputes and the contested-validate branch."""
    work = db.works[work_id]
    claim_ids = [initiating_claim_id] + list(extra_claim_ids)
    rec = make_record()
    rec.update({
        "work_id": work_id,
        "share_context": share_context,
        "claim_ids": claim_ids,
        "status": "OPEN",
        "resolution_note": None,
        "_opened_at_dt": db.now(),
    })
    db.disputes[rec["id"]] = rec
    # Fold claims -> DISPUTED; freeze their lines
    for cid in claim_ids:
        c = db.claims.get(cid)
        if c is None:
            continue
        c["status"] = "DISPUTED"
        touch(c)
        accrual = db.accruals.get(c["accrual_id"])
        if accrual is not None:
            line = db.usage_lines.get(accrual["usage_line_id"])
            if line is not None and line["status"] in ("CLAIMED_MATCHED", "UNMATCHED"):
                line["status"] = "DISPUTE_HELD"
                touch(line)
    # Work -> UNDER_DISPUTE; contested shares ACTIVE -> DISPUTED
    if work["status"] == "ACTIVE":
        work["status"] = "UNDER_DISPUTE"
        touch(work)
    for s in db.work_shares.values():
        if s["work_id"] == work_id and s["status"] == "ACTIVE":
            s["status"] = "DISPUTED"
            touch(s)
    return rec


@bp.route("/mlc/disputes", methods=["POST"])
@require_roles(*WRITE)
def create_dispute(_user_id, _role):
    body = body_json(required=("work_id", "share_context", "initiating_claim_id"))
    work = get_work(body["work_id"])
    claim = get_claim(body["initiating_claim_id"])
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    rec = open_dispute_internal(work["id"], body["share_context"], claim["id"])
    return ok_object(dispute_view(rec), 201)


@bp.route("/mlc/disputes", methods=["GET"])
@require_roles(*READ)
def list_disputes(_user_id, _role):
    items = sorted(db.disputes.values(), key=lambda d: d["created_at"])
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    work_id = request.args.get("work_id")
    if work_id:
        items = [d for d in items if d["work_id"] == work_id]
    return ok_list([dispute_view(d) for d in items])


@bp.route("/mlc/disputes/<dispute_id>", methods=["GET"])
@require_roles(*READ)
def get_one_dispute(dispute_id, _user_id, _role):
    return ok_object(dispute_view(get_dispute(dispute_id)))


def _settle_claim(claim, won):
    """Settle accrual/line per dispute outcome for one folded claim."""
    accrual = db.accruals.get(claim["accrual_id"])
    if accrual is None:
        return
    line = db.usage_lines.get(accrual["usage_line_id"])
    if won:
        if accrual["status"] == "HELD" and line is not None and line["status"] == "DISPUTE_HELD":
            accrual["status"] = "CLAIMED"
            accrual["matched_work_id"] = claim["claimed_work_id"]
            touch(accrual)
            line["status"] = "CLAIMED_MATCHED"
            line["matched_work_id"] = claim["claimed_work_id"]
            touch(line)
            report = db.usage_reports.get(line["report_id"])
            if report is not None:
                queue_matched_postings(line, report, "CLAIM_EARNINGS")
    else:
        if accrual["status"] in ("CLAIMED", "HELD"):
            accrual["status"] = "HELD"
            accrual["matched_work_id"] = None
            touch(accrual)
        if line is not None and line["status"] == "DISPUTE_HELD":
            line["status"] = "UNMATCHED"
            line["matched_work_id"] = None
            touch(line)
            drop_postings_for_line(line["id"], "CLAIM_EARNINGS")


@bp.route("/mlc/disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles(*ADMIN)
def resolve_dispute(dispute_id, _user_id, _role):
    d = get_dispute(dispute_id)
    body = body_json(required=("winning_claim_id", "resolution_note"))
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")
    winner_id = body["winning_claim_id"]
    if winner_id not in d["claim_ids"]:
        raise err("ERR_DISPUTE_WINNER_NOT_IN_SET")
    d["status"] = "RESOLVED"
    d["resolution_note"] = body["resolution_note"]
    touch(d)
    for cid in d["claim_ids"]:
        c = db.claims.get(cid)
        if c is None:
            continue
        won = (cid == winner_id)
        c["status"] = "RESOLVED" if won else "REJECTED"
        touch(c)
        _settle_claim(c, won)
    # Work -> ACTIVE when no other OPEN dispute remains
    work = db.works.get(d["work_id"])
    if work is not None:
        other_open = any(
            x["work_id"] == work["id"] and x["status"] == "OPEN" and x["id"] != d["id"]
            for x in db.disputes.values())
        if not other_open and work["status"] == "UNDER_DISPUTE":
            work["status"] = "ACTIVE"
            touch(work)
        # Disputed shares return to ACTIVE (resolved in share's favor is
        # approximated: shares stay DISPUTED only while a dispute is open)
        if not other_open:
            for s in db.work_shares.values():
                if s["work_id"] == work["id"] and s["status"] == "DISPUTED":
                    s["status"] = "ACTIVE"
                    touch(s)
    return ok_object(dispute_view(d))


@bp.route("/mlc/disputes/<dispute_id>/escalate", methods=["POST"])
@require_roles(*ADMIN)
def escalate_dispute(dispute_id, _user_id, _role):
    d = get_dispute(dispute_id)
    body_json()
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")
    if db.now() < d["_opened_at_dt"] + timedelta(days=90):
        raise err("ERR_DISPUTE_TOO_FRESH")
    d["status"] = "ESCALATED"
    touch(d)
    return ok_object(dispute_view(d))
