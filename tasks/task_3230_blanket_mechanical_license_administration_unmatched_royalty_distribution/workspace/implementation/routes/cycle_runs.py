"""CycleRun + DistributionLine endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_cycle_run, get_distribution_line
from response import ok_list, ok_object
from util import body_json, make_record, touch, month_bounds

bp = Blueprint("cycle_runs", __name__)

ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "MemberUser", "PublicSearcher")


def cycle_view(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


def dist_view(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


@bp.route("/mlc/cycle-runs", methods=["POST"])
@require_roles(*ADMIN)
def create_cycle(_user_id, _role):
    body = body_json(required=("cycle_month", "pool_from_month",
                               "pool_to_month", "methodology"))
    for f in ("cycle_month", "pool_from_month", "pool_to_month"):
        month_bounds(body[f])
    if body["methodology"] not in ("MARKET_SHARE_USAGE", "MARKET_SHARE_PRIOR"):
        raise err("ERR_INVALID_REQUEST", "methodology invalid")
    dup = any(c["cycle_month"] == body["cycle_month"] for c in db.cycle_runs.values())
    if dup:
        raise err("ERR_INVALID_REQUEST", "cycle_month must be unique")
    rec = make_record()
    rec.update({
        "cycle_month": body["cycle_month"],
        "pool_from_month": body["pool_from_month"],
        "pool_to_month": body["pool_to_month"],
        "status": "OPEN",
        "pool_cents": 0,
        "residual_cents": 0,
        "methodology": body["methodology"],
    })
    db.cycle_runs[rec["id"]] = rec
    return ok_object(cycle_view(rec), 201)


@bp.route("/mlc/cycle-runs", methods=["GET"])
@require_roles(*READ)
def list_cycles(_user_id, _role):
    items = sorted(db.cycle_runs.values(), key=lambda c: c["created_at"])
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return ok_list([cycle_view(c) for c in items])


@bp.route("/mlc/cycle-runs/<run_id>", methods=["GET"])
@require_roles(*READ)
def get_cycle(run_id, _user_id, _role):
    return ok_object(cycle_view(get_cycle_run(run_id)))


def _sweep(run):
    """Sweep expired accruals into the pool (or forfeit). Returns pool cents."""
    pool = 0
    now = db.now()
    for a in db.accruals.values():
        if a["status"] != "HELD":
            continue
        if a["_hold_expires_dt"] > now:
            continue
        in_window = run["pool_from_month"] <= a["reporting_month"] <= run["pool_to_month"]
        if in_window:
            a["status"] = "DISTRIBUTED"
            pool += a["amount_cents"]
            line = db.usage_lines.get(a["usage_line_id"])
            if line is not None and line["status"] == "UNMATCHED":
                line["status"] = "DISTRIBUTED"
                touch(line)
        else:
            a["status"] = "FORFEITED"
        touch(a)
    # MATCHED lines whose earnings posted to a FINALIZED statement and whose
    # reporting month is inside the pool window -> DISTRIBUTED
    finalized_stmt_ids = {
        s["id"] for s in db.statements.values() if s["status"] in ("FINALIZED", "DELIVERED")
    }
    posted_line_ids = {
        l["usage_line_id"] for l in db.statement_lines.values()
        if l["statement_id"] in finalized_stmt_ids and l["usage_line_id"]
    }
    for line in db.usage_lines.values():
        if line["status"] != "MATCHED":
            continue
        report = db.usage_reports.get(line["report_id"])
        if report is None:
            continue
        if not (run["pool_from_month"] <= report["reporting_month"] <= run["pool_to_month"]):
            continue
        if line["id"] in posted_line_ids:
            line["status"] = "DISTRIBUTED"
            touch(line)
    return pool


def _weight_usage(member):
    if not member["is_signatory"]:
        return 1
    count = 0
    for w in db.works.values():
        if w["match_run_count"] <= 0:
            continue
        linked = any(
            s["work_id"] == w["id"] and s["claimant_member_id"] == member["id"]
            and s["status"] in ("ACTIVE", "DISPUTED")
            for s in db.work_shares.values())
        if linked:
            count += 1
    return count


def _weight_prior(member):
    if member["prior_market_share_denominator"] > 0:
        return member["prior_market_share_numerator"]
    return 1


def _waterfall(run, pool):
    """Allocate pool across ACTIVE members; create DistributionLines.
    Returns list of created line records."""
    members = sorted(
        (m for m in db.members.values() if m["status"] == "ACTIVE"),
        key=lambda m: m["created_at"])
    weigh = _weight_usage if run["methodology"] == "MARKET_SHARE_USAGE" else _weight_prior
    weights = [(m, weigh(m)) for m in members]
    W = sum(w for _, w in weights)
    lines = []
    if W == 0:
        for m, w in weights:
            lines.append(_make_dist_line(run, m, 0, w, W, 0))
        run["residual_cents"] = pool
        return lines
    total_base = 0
    for m, w in weights:
        base = (pool * w) // W
        total_base += base
        lines.append(_make_dist_line(run, m, base, w, W, 0))
    remainder = pool - total_base
    i = 0
    while remainder > 0 and i < len(lines):
        lines[i]["residual_cents"] += 1
        remainder -= 1
        i += 1
    run["residual_cents"] = 0
    return lines


def _make_dist_line(run, member, allocated, w_num, w_den, residual):
    rec = make_record(full_common=False)
    rec.update({
        "cycle_run_id": run["id"],
        "member_id": member["id"],
        "allocated_cents": allocated,
        "weight_numerator": w_num,
        "weight_denominator": w_den,
        "residual_cents": residual,
    })
    db.distribution_lines[rec["id"]] = rec
    return rec


def _freeze_prior_epoch(run, dist_lines):
    """member_prior_epoch_snapshot after the waterfall."""
    matched_works = [w for w in db.works.values() if w["match_run_count"] > 0]
    total_matched = len(matched_works)
    recipients = {
        l["member_id"] for l in dist_lines
        if l["allocated_cents"] > 0 or l["residual_cents"] > 0
    }
    for m in db.members.values():
        if m["is_signatory"]:
            num = 0
            for w in matched_works:
                linked = any(
                    s["work_id"] == w["id"] and s["claimant_member_id"] == m["id"]
                    for s in db.work_shares.values())
                if linked:
                    num += 1
            m["prior_market_share_numerator"] = num
            m["prior_market_share_denominator"] = total_matched
        else:
            m["prior_market_share_numerator"] = 1
            m["prior_market_share_denominator"] = len(recipients)
        touch(m)


@bp.route("/mlc/cycle-runs/<run_id>/close", methods=["POST"])
@require_roles(*ADMIN)
def close_cycle(run_id, _user_id, _role):
    run = get_cycle_run(run_id)
    body_json()
    if run["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")
    earlier_open = any(
        c["cycle_month"] < run["cycle_month"] and c["status"] == "OPEN"
        for c in db.cycle_runs.values())
    if earlier_open:
        raise err("ERR_CYCLE_OUT_OF_ORDER")
    pool = _sweep(run)
    run["pool_cents"] = pool
    dist_lines = _waterfall(run, pool)
    _freeze_prior_epoch(run, dist_lines)
    # Queue DISTRIBUTION postings
    for l in dist_lines:
        total = l["allocated_cents"] + l["residual_cents"]
        if total > 0:
            db.postings.append({
                "member_id": l["member_id"],
                "period_month": run["cycle_month"],
                "usage_line_id": None,
                "allocated_cents": total,
                "line_type": "DISTRIBUTION",
            })
    run["status"] = "CLOSED"
    touch(run)
    return ok_object(cycle_view(run))


@bp.route("/mlc/cycle-runs/<run_id>/distribution-lines", methods=["GET"])
@require_roles(*READ)
def list_cycle_dist_lines(run_id, _user_id, _role):
    get_cycle_run(run_id)
    items = sorted(
        (d for d in db.distribution_lines.values() if d["cycle_run_id"] == run_id),
        key=lambda d: d["created_at"])
    member_id = request.args.get("member_id")
    if member_id:
        items = [d for d in items if d["member_id"] == member_id]
    return ok_list([dist_view(d) for d in items])


@bp.route("/mlc/distribution-lines", methods=["GET"])
@require_roles(*READ)
def list_dist_lines_flat(_user_id, _role):
    items = sorted(db.distribution_lines.values(), key=lambda d: d["created_at"])
    for field in ("cycle_run_id", "member_id"):
        v = request.args.get(field)
        if v:
            items = [d for d in items if d.get(field) == v]
    return ok_list([dist_view(d) for d in items])


@bp.route("/mlc/distribution-lines/<line_id>", methods=["GET"])
@require_roles(*READ)
def get_dist_line(line_id, _user_id, _role):
    return ok_object(dist_view(get_distribution_line(line_id)))
