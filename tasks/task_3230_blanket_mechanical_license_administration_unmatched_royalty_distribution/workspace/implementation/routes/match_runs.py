"""MatchRun endpoints."""
from flask import Blueprint

import db
from auth import require_roles
from calc import deterministic_match, spawn_accrual
from lookups import get_sp
from postings import queue_matched_postings, recompute_report_totals
from response import ok_list, ok_object
from util import make_record, touch

bp = Blueprint("match_runs", __name__)

ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "MemberUser", "PublicSearcher")


def match_run_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.route("/mlc/match-runs", methods=["POST"])
@require_roles(*ADMIN)
def create_match_run(_user_id, _role):
    lines = sorted(
        (l for l in db.usage_lines.values()
         if l["status"] in ("PENDING_MATCH", "UNMATCHED")),
        key=lambda l: l["created_at"])
    total = len(lines)
    matched = 0
    promoted_unmatched = 0
    for line in lines:
        report = db.usage_reports.get(line["report_id"])
        sp = db.service_providers.get(report["service_provider_id"]) if report else None
        work = deterministic_match(line)
        if work is not None:
            was_unmatched = line["status"] == "UNMATCHED"
            line["status"] = "MATCHED"
            line["matched_work_id"] = work["id"]
            touch(line)
            work["match_run_count"] += 1
            touch(work)
            if was_unmatched:
                # Release the HELD accrual
                acc = next(
                    (a for a in db.accruals.values()
                     if a["usage_line_id"] == line["id"] and a["status"] == "HELD"),
                    None)
                if acc is not None:
                    acc["status"] = "RELEASED"
                    touch(acc)
                matched += 1
                if report is not None:
                    queue_matched_postings(line, report, "MATCHED_EARNINGS")
            else:
                matched += 1
                if report is not None:
                    queue_matched_postings(line, report, "MATCHED_EARNINGS")
        else:
            if line["status"] == "PENDING_MATCH":
                line["status"] = "UNMATCHED"
                touch(line)
                if report is not None and sp is not None:
                    spawn_accrual(line, report, sp)
                promoted_unmatched += 1
    bps = (matched * 10000 // total) if total else 0
    # Re-partition every report whose lines were re-evaluated: a re-matched
    # line's cents return to the matched-royalty stream (PRD §3.4), and the
    # matched+unmatched == total invariant must keep holding (PRD §2.9).
    for rep_id in {l["report_id"] for l in lines}:
        rep = db.usage_reports.get(rep_id)
        if rep is not None:
            recompute_report_totals(rep)
            touch(rep)
    rec = make_record()
    rec.update({
        "initiated_by": _user_id,
        "total_lines_evaluated": total,
        "lines_matched": matched,
        "lines_promoted_unmatched": promoted_unmatched,
        "match_rate_bps": bps,
        "status": "COMPLETED",
        "_evaluated_line_ids": {l["id"] for l in lines},
    })
    db.match_runs[rec["id"]] = rec
    return ok_object(match_run_view(rec), 201)


@bp.route("/mlc/match-runs", methods=["GET"])
@require_roles(*READ)
def list_match_runs(_user_id, _role):
    items = sorted(db.match_runs.values(), key=lambda r: r["created_at"])
    return ok_list([match_run_view(r) for r in items])


@bp.route("/mlc/match-runs/<run_id>", methods=["GET"])
@require_roles(*READ)
def get_match_run(run_id, _user_id, _role):
    r = db.match_runs.get(run_id)
    if r is None:
        from errors import err
        raise err("ERR_INVALID_REQUEST", "Match run not found")
    return ok_object(match_run_view(r))
