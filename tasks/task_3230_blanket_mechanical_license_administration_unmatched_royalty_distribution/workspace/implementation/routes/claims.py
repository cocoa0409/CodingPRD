"""Claim endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_accrual, get_claim, get_member, get_work
from postings import queue_matched_postings
from response import ok_list, ok_object
from util import body_json, make_record, touch

bp = Blueprint("claims", __name__)

ADMIN = ("MLCAdministrator",)
MEMBER = ("MemberUser",)
READ = ("MLCAdministrator", "MemberUser", "PublicSearcher")


def claim_view(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


@bp.route("/mlc/claims", methods=["POST"])
@require_roles(*MEMBER)
def create_claim(_user_id, _role):
    body = body_json(required=("accrual_id", "claimant_member_id",
                               "claimed_work_id", "share_percent_claimed"))
    accrual = get_accrual(body["accrual_id"])
    member = get_member(body["claimant_member_id"])
    work = get_work(body["claimed_work_id"])
    pct = body["share_percent_claimed"]
    if not isinstance(pct, (int, float)) or pct <= 0 or pct > 100:
        raise err("ERR_INVALID_REQUEST", "share_percent_claimed must be > 0 and <= 100")
    if member["status"] != "ACTIVE":
        raise err("ERR_DSP_NOT_ACTIVE")
    rec = make_record()
    rec.update({
        "accrual_id": accrual["id"],
        "claimant_member_id": member["id"],
        "claimed_work_id": work["id"],
        "share_percent_claimed": pct,
        "status": "PENDING",
    })
    db.claims[rec["id"]] = rec
    return ok_object(claim_view(rec), 201)


@bp.route("/mlc/claims", methods=["GET"])
@require_roles(*READ)
def list_claims(_user_id, _role):
    items = sorted(db.claims.values(), key=lambda c: c["created_at"])
    for field in ("claimant_member_id", "claimed_work_id", "status"):
        v = request.args.get(field)
        if v:
            items = [c for c in items if c.get(field) == v]
    return ok_list([claim_view(c) for c in items])


@bp.route("/mlc/claims/<claim_id>", methods=["GET"])
@require_roles(*READ)
def get_one_claim(claim_id, _user_id, _role):
    return ok_object(claim_view(get_claim(claim_id)))


def _line_accrual(accrual):
    line = db.usage_lines.get(accrual["usage_line_id"])
    return line


def _validate_core(claim, _user_id):
    """Validation checks in the PRD-enumerated order (§3.6)."""
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    accrual = db.accruals[claim["accrual_id"]]
    if accrual["status"] != "HELD":
        raise err("ERR_ACCRUAL_NOT_HELD")
    work = db.works.get(claim["claimed_work_id"])
    covering = None
    if work is not None:
        covering = next(
            (s for s in db.work_shares.values()
             if s["work_id"] == work["id"] and s["status"] == "ACTIVE"
             and s["claimant_member_id"] == claim["claimant_member_id"]
             and s["share_percent"] >= claim["share_percent_claimed"]),
            None)
    if covering is None:
        raise err("ERR_CLAIMANT_SHARE_NOT_FOUND")
    if accrual["_hold_expires_dt"] <= db.now():
        raise err("ERR_HOLD_EXPIRED")
    # SoD: validator may not be the initiator of the most recent match run
    # that touched the claim's accrual's usage line.
    line = _line_accrual(accrual)
    if line is not None:
        runs = sorted(
            (r for r in db.match_runs.values()),
            key=lambda r: r["created_at"])
        # A run "touched" the line if the line was evaluated in it. We track
        # line ids evaluated per run in a private field.
        for r in reversed(runs):
            if line["id"] in r.get("_evaluated_line_ids", set()):
                if r["initiated_by"] == _user_id:
                    raise err("ERR_SOD_CONFLICT")
                break
    return accrual, work, line


@bp.route("/mlc/claims/<claim_id>/validate", methods=["POST"])
@require_roles(*ADMIN)
def validate_claim(claim_id, _user_id, _role):
    claim = get_claim(claim_id)
    body_json()
    accrual, work, line = _validate_core(claim, _user_id)
    # Contested branch: another PENDING claim against the same accrual exists
    others = [
        c for c in db.claims.values()
        if c["accrual_id"] == accrual["id"] and c["status"] == "PENDING"
        and c["id"] != claim["id"]
    ]
    if others:
        # Fold both into a new dispute over the claimed work
        from routes.disputes import open_dispute_internal
        open_dispute_internal(work["id"],
                              f"accrual {accrual['id']} contested",
                              claim["id"],
                              extra_claim_ids=[c["id"] for c in others])
        return ok_object(claim_view(db.claims[claim_id]))
    claim["status"] = "VALIDATED"
    touch(claim)
    accrual["status"] = "CLAIMED"
    accrual["matched_work_id"] = claim["claimed_work_id"]
    touch(accrual)
    if line is not None:
        line["status"] = "CLAIMED_MATCHED"
        line["matched_work_id"] = claim["claimed_work_id"]
        touch(line)
        report = db.usage_reports.get(line["report_id"])
        if report is not None:
            queue_matched_postings(line, report, "CLAIM_EARNINGS")
    return ok_object(claim_view(claim))


@bp.route("/mlc/claims/<claim_id>/reject", methods=["POST"])
@require_roles(*ADMIN)
def reject_claim(claim_id, _user_id, _role):
    claim = get_claim(claim_id)
    body_json()
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    claim["status"] = "REJECTED"
    touch(claim)
    return ok_object(claim_view(claim))


@bp.route("/mlc/claims/<claim_id>/withdraw", methods=["POST"])
@require_roles(*MEMBER)
def withdraw_claim(claim_id, _user_id, _role):
    claim = get_claim(claim_id)
    body_json()
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    if claim["claimant_member_id"] != _user_id:
        raise err("ERR_NOT_CLAIM_OWNER")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return ok_object(claim_view(claim))
