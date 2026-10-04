"""Pre-qualification decisions and the modeled-approval-odds walk."""

import math

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited, rhu
from errors import fail

bp = Blueprint("prequal", __name__)

READ_ROLES = ["Consumer", "LenderOps", "Referee", "ComplianceOfficer",
              "PlatformAdmin", "DataProtectionOfficer"]

ODDS_BASE = 0.90
ODDS_HARD_MATCH_BONUS = 0.04
ODDS_SOFT_MATCH_BONUS = 0.06
ODDS_UTILIZATION_FREE_PCT = 30.0
ODDS_UTILIZATION_PENALTY_PER_10PCT = 0.05
ODDS_MIN = 0.01
ODDS_MAX = 0.99

INCLUDED_STATUSES = ("NEEDS_SNAPSHOT", "ELIGIBLE", "INELIGIBLE", "PREQUALIFIED",
                     "CONSENTED", "CONSUMED")


def compute_modeled_odds(crit_list, cns, snap):
    """Returns (p, hard_failed_list). p is None when a hard criterion failed."""
    hard_pass = 0
    hard_failed = []
    soft_pass = 0
    soft_total = 0
    for crit in crit_list:
        matched = helpers.criterion_matches(crit, cns, snap)
        if crit["is_hard_requirement"]:
            if matched:
                hard_pass += 1
            else:
                hard_failed.append(crit)
        else:
            soft_total += 1
            if matched:
                soft_pass += 1
    if hard_failed:
        return None, hard_failed
    p = ODDS_BASE - ODDS_HARD_MATCH_BONUS * hard_pass
    if soft_total > 0:
        p = p - ODDS_SOFT_MATCH_BONUS * (soft_pass / float(soft_total))
    utilization = snap.get("overall_credit_utilization_pct")
    if utilization is not None and utilization > ODDS_UTILIZATION_FREE_PCT:
        groups = math.floor((float(utilization) - ODDS_UTILIZATION_FREE_PCT) / 10.0)
        p = p + ODDS_UTILIZATION_PENALTY_PER_10PCT * groups
    p = min(p, ODDS_MAX)
    p = max(p, ODDS_MIN)
    return p, []


def _disqualifying(crit_list):
    out = [{"criterion_field": c["criterion_field"], "operator": c["operator"],
            "criterion_value": c["criterion_value"]} for c in crit_list]
    out.sort(key=lambda c: c["criterion_field"])
    return out


def _program_product_kind(prog):
    item = store.product_catalog_items.get(prog["product_catalog_item_id"])
    return item["product_kind"] if item else None


def evaluate_into(dec, cns, prog):
    """Run the evaluation walk and write the outcome onto an existing decision."""
    moment = store.now()
    snap = helpers.active_snapshot(cns["id"])
    if snap is None:
        dec["decision_status"] = "NEEDS_SNAPSHOT"
        dec["reason"] = "NO_ACTIVE_SNAPSHOT"
        dec["modeled_odds_pct"] = None
        dec["snapshot_id"] = None
        dec["snapshot_ordinal_used"] = None
        dec["disqualifying_criteria"] = []
        dec["decided_at"] = moment
        dec["fresh_until"] = moment + _cache_window()
        return dec
    crit_list = helpers.criteria_of(prog["id"])
    p, hard_failed = compute_modeled_odds(crit_list, cns, snap)
    dec["snapshot_id"] = snap["id"]
    dec["snapshot_ordinal_used"] = snap["snapshot_ordinal"]
    dec["decided_at"] = moment
    dec["fresh_until"] = moment + _cache_window()
    if p is None:
        excluded = any(c["criterion_field"] == "STATE_CODE" for c in hard_failed)
        dec["decision_status"] = "INELIGIBLE"
        dec["modeled_odds_pct"] = None
        dec["disqualifying_criteria"] = _disqualifying(hard_failed)
        dec["reason"] = "CONSUMER_STATE_EXCLUDED" if excluded else "HARD_CRITERIA_FAILED"
    else:
        dec["decision_status"] = "ELIGIBLE"
        dec["modeled_odds_pct"] = rhu(p, 2)
        dec["disqualifying_criteria"] = []
        dec["reason"] = "NOT_PREQUALIFIED"
    dec["modeled_odds_settled"] = False
    return dec


def _cache_window():
    from datetime import timedelta
    return timedelta(days=store.PREQUAL_CACHE_DAYS)


@bp.route("/consumers/<cid>/pre-qualifications", methods=["POST"])
def create_prequalification(cid):
    uid, role = require(["Consumer"])
    cns = helpers.consumer(cid)
    helpers.owned(cns, uid, role, field="id")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    pid = data.get("lender_program_id")
    if not pid:
        fail("ERR_INVALID_REQUEST", "lender_program_id is required.")
    prog = helpers.program(str(pid))
    sponsor = helpers.lender(prog["lender_id"])
    if cns["state_code"] not in (sponsor.get("states_served") or []):
        fail("ERR_LENDER_SERVES_STATE_REQUIRED")
    existing = None
    for dec in store.pre_qual_decisions.values():
        if dec["consumer_id"] == cid and dec["lender_program_id"] == pid:
            existing = dec
            break
    if existing is None:
        row = store.make_row({
            "consumer_id": cid,
            "lender_program_id": pid,
            "snapshot_id": None,
            "snapshot_ordinal_used": None,
            "modeled_odds_pct": None,
            "modeled_odds_settled": False,
            "decision_status": "NEEDS_SNAPSHOT",
            "disqualifying_criteria": [],
            "reason": "NO_ACTIVE_SNAPSHOT",
            "decided_at": None,
            "fresh_until": None,
        })
        store.pre_qual_decisions[row["id"]] = row
        evaluate_into(row, cns, prog)
        models.touch(row)
        return ok(models.decision(row), store.now(), 201)
    if existing["decision_status"] not in ("NEEDS_SNAPSHOT", "ELIGIBLE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "This decision cannot be re-evaluated from its current status.")
    if existing["decision_status"] == "NEEDS_SNAPSHOT":
        pinned = store.bureau_snapshots.get(existing.get("snapshot_id"))
        if pinned is not None and pinned["status"] != "ACTIVE":
            fresh = helpers.active_snapshot(cid)
            if fresh is not None:
                existing["snapshot_id"] = fresh["id"]
    evaluate_into(existing, cns, prog)
    models.touch(existing)
    return ok(models.decision(existing), store.now(), 200)


@bp.route("/pre-qualification-decisions", methods=["GET"])
def list_decisions():
    require(READ_ROLES)
    rows = list(store.pre_qual_decisions.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    pid = request.args.get("lender_program_id")
    if pid:
        rows = [r for r in rows if r["lender_program_id"] == pid]
    status = request.args.get("decision_status")
    if status:
        rows = [r for r in rows if r["decision_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.decision(r) for r in window], store.now(), pagination)


@bp.route("/pre-qualification-decisions/<did>", methods=["GET"])
def get_decision(did):
    uid, role = require(READ_ROLES)
    row = helpers.decision(did)
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.decision(row), store.now())


@bp.route("/consumers/<cid>/pre-qualification-decisions", methods=["GET"])
def list_consumer_decisions(cid):
    require(["Consumer", "LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = [r for r in store.pre_qual_decisions.values() if r["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.decision(r) for r in window], store.now(), pagination)


@bp.route("/lender-programs/<pid>/pre-qualification-decisions", methods=["GET"])
def list_program_decisions(pid):
    require(["LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.program(pid)
    rows = [r for r in store.pre_qual_decisions.values() if r["lender_program_id"] == pid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.decision(r) for r in window], store.now(), pagination)


@bp.route("/bureau-snapshots/<sid>/pre-qualification-decisions", methods=["GET"])
def list_snapshot_decisions(sid):
    require(["LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.snapshot(sid)
    rows = [r for r in store.pre_qual_decisions.values() if r["snapshot_id"] == sid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.decision(r) for r in window], store.now(), pagination)


@bp.route("/pre-qualification-decisions/<did>/qualify", methods=["POST"])
def qualify_decision(did):
    require(["Referee", "PlatformAdmin"])
    row = helpers.decision(did)
    if row["decision_status"] != "ELIGIBLE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ELIGIBLE decision may be qualified.")
    prog = helpers.program(row["lender_program_id"])
    product_kind = _program_product_kind(prog)
    if helpers.is_over_presentation(row["consumer_id"], product_kind):
        fail("ERR_QUALIFY_OVER_REPRESENTED")
    row["decision_status"] = "PREQUALIFIED"
    models.touch(row)
    return ok(models.decision(row), store.now())