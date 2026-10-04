"""MusicalWork + WorkShare endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_work, get_share, check_child
from response import ok_list, ok_object
from util import body_json, make_record, touch, parse_iso, ts_now
from postings import recompute_work_total_share

bp = Blueprint("works", __name__)

READ = ("MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher")
WRITE = ("MLCAdministrator", "MemberUser")
ADMIN = ("MLCAdministrator",)


def work_view(w):
    return {k: v for k, v in w.items() if not k.startswith("_")}


def share_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def _intervals_overlap(a_from, a_to, b_from, b_to):
    """Half-open overlap: [a,b) vs [c,d) overlap iff a < d AND c < b.
    None end = infinity."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    # a < d
    if b_end is not None and not (a_from < b_end):
        return False
    # c < b
    if a_end is not None and not (b_from < a_end):
        return False
    return True


@bp.route("/mlc/works", methods=["POST"])
@require_roles(*WRITE)
def create_work(_user_id, _role):
    body = body_json(required=("title",))
    iswc = body.get("iswc")
    if iswc is not None:
        dup = any(w.get("iswc") == iswc for w in db.works.values())
        if dup:
            raise err("ERR_INVALID_REQUEST", "iswc must be unique")
    rec = make_record()
    rec.update({
        "title": body["title"],
        "iswc": iswc,
        "status": "ACTIVE",
        "withdrawn_at": None,
        "total_share_percent": 0,
        "match_run_count": 0,
    })
    db.works[rec["id"]] = rec
    return ok_object(work_view(rec), 201)


@bp.route("/mlc/works", methods=["GET"])
@require_roles(*READ)
def list_works(_user_id, _role):
    items = sorted(db.works.values(), key=lambda w: w["created_at"])
    title = request.args.get("title")
    if title is not None:
        items = [w for w in items if w["title"] == title]
    iswc = request.args.get("iswc")
    if iswc is not None:
        items = [w for w in items if w.get("iswc") == iswc]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    return ok_list([work_view(w) for w in items])


@bp.route("/mlc/works/<work_id>", methods=["GET"])
@require_roles(*READ)
def get_one_work(work_id, _user_id, _role):
    return ok_object(work_view(get_work(work_id)))


@bp.route("/mlc/works/<work_id>/withdraw", methods=["POST"])
@require_roles(*ADMIN)
def withdraw_work(work_id, _user_id, _role):
    w = get_work(work_id)
    if w["status"] not in ("ACTIVE", "UNDER_DISPUTE"):
        raise err("ERR_INVALID_STATE")
    blocking_lines = any(
        l.get("matched_work_id") == work_id and
        l["status"] in ("PENDING_MATCH", "MATCHED", "CLAIMED_MATCHED", "DISPUTE_HELD")
        for l in db.usage_lines.values())
    if blocking_lines:
        raise err("ERR_WORK_HAS_ACTIVE_USAGE")
    held_accruals = any(
        a.get("matched_work_id") == work_id and a["status"] == "HELD"
        for a in db.accruals.values())
    if held_accruals:
        raise err("ERR_WORK_HAS_HELD_ACCRUALS")
    # Cascade: OPEN disputes -> ESCALATED with WORK_WITHDRAWN note
    for d in db.disputes.values():
        if d["work_id"] == work_id and d["status"] == "OPEN":
            d["status"] = "ESCALATED"
            d["resolution_note"] = "WORK_WITHDRAWN"
            touch(d)
    # Cascade: ACTIVE/DISPUTED shares -> WITHDRAWN
    for s in db.work_shares.values():
        if s["work_id"] == work_id and s["status"] in ("ACTIVE", "DISPUTED"):
            s["status"] = "WITHDRAWN"
            touch(s)
    w["status"] = "WITHDRAWN"
    w["withdrawn_at"] = ts_now()
    recompute_work_total_share(w)
    touch(w)
    return ok_object(work_view(w))


@bp.route("/mlc/works/<work_id>/shares", methods=["POST"])
@require_roles(*WRITE)
def create_share(work_id, _user_id, _role):
    w = get_work(work_id)
    body = body_json(required=("claimant_member_id", "share_percent",
                               "effective_from", "expected_work_version"))
    claimant = body["claimant_member_id"]
    if claimant not in db.members:
        raise err("ERR_MEMBER_NOT_FOUND")
    admin_id = body.get("administered_by_member_id")
    if admin_id is not None and admin_id not in db.members:
        raise err("ERR_MEMBER_NOT_FOUND")
    share_percent = body["share_percent"]
    if not isinstance(share_percent, (int, float)) or share_percent <= 0 or share_percent > 100:
        raise err("ERR_INVALID_REQUEST", "share_percent must be > 0 and <= 100")
    ef = parse_iso(body["effective_from"], "effective_from")
    et = parse_iso(body["effective_to"], "effective_to") if body.get("effective_to") else None
    # Priority 16 OCC: expected_work_version
    if body["expected_work_version"] != w["version"]:
        raise err("ERR_STALE_VERSION")
    # Priority 8: interval well-formed
    if et is not None and not (et > ef):
        raise err("ERR_INVALID_SHARE_INTERVAL")
    # Priority 10: share sum <= 100
    current_sum = sum(
        s["share_percent"] for s in db.work_shares.values()
        if s["work_id"] == work_id and s["status"] == "ACTIVE")
    if current_sum + share_percent > 100:
        raise err("ERR_SHARE_SUM_EXCEEDS_100")
    # Priority 11: same-claimant overlap requires supersedes_share_id
    supersedes_id = body.get("supersedes_share_id")
    overlapping = [
        s for s in db.work_shares.values()
        if s["work_id"] == work_id and s["status"] == "ACTIVE"
        and s["claimant_member_id"] == claimant
        and _intervals_overlap(ef, et, s["_effective_from_dt"], s["_effective_to_dt"])
    ]
    if overlapping and supersedes_id is None:
        raise err("ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE")
    # Priority 12: supersedes target must be ACTIVE or WITHDRAWN share of same work
    superseded = None
    if supersedes_id is not None:
        superseded = db.work_shares.get(supersedes_id)
        if (superseded is None or superseded["work_id"] != work_id
                or superseded["status"] not in ("ACTIVE", "WITHDRAWN")):
            raise err("ERR_SUPERSEDES_NOT_FOUND")
    rec = make_record()
    rec.update({
        "work_id": work_id,
        "claimant_member_id": claimant,
        "administered_by_member_id": admin_id,
        "share_percent": share_percent,
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "status": "ACTIVE",
        "supersedes_share_id": supersedes_id,
        "_effective_from_dt": ef,
        "_effective_to_dt": et,
    })
    db.work_shares[rec["id"]] = rec
    if superseded is not None and superseded["status"] == "ACTIVE":
        superseded["status"] = "WITHDRAWN"
        touch(superseded)
    recompute_work_total_share(w)
    touch(w)
    return ok_object(share_view(rec), 201)


@bp.route("/mlc/works/<work_id>/shares", methods=["GET"])
@require_roles(*READ)
def list_shares(work_id, _user_id, _role):
    get_work(work_id)
    items = sorted(
        (s for s in db.work_shares.values() if s["work_id"] == work_id),
        key=lambda s: s["created_at"])
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    claimant = request.args.get("claimant_member_id")
    if claimant:
        items = [s for s in items if s["claimant_member_id"] == claimant]
    return ok_list([share_view(s) for s in items])


@bp.route("/mlc/works/<work_id>/shares/<share_id>", methods=["GET"])
@require_roles(*READ)
def get_one_share(work_id, share_id, _user_id, _role):
    get_work(work_id)
    s = get_share(share_id)
    check_child(s, "work_id", work_id, "ERR_SHARE_NOT_FOUND")
    return ok_object(share_view(s))


@bp.route("/mlc/works/<work_id>/shares/<share_id>/withdraw", methods=["POST"])
@require_roles(*WRITE)
def withdraw_share(work_id, share_id, _user_id, _role):
    w = get_work(work_id)
    s = get_share(share_id)
    check_child(s, "work_id", work_id, "ERR_SHARE_NOT_FOUND")
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE")
    s["status"] = "WITHDRAWN"
    touch(s)
    recompute_work_total_share(w)
    touch(w)
    return ok_object(share_view(s))


@bp.route("/mlc/shares", methods=["GET"])
@require_roles(*READ)
def list_shares_flat(_user_id, _role):
    items = sorted(db.work_shares.values(), key=lambda s: s["created_at"])
    for field in ("claimant_member_id", "administered_by_member_id",
                  "supersedes_share_id", "status"):
        v = request.args.get(field)
        if v:
            items = [s for s in items if s.get(field) == v]
    return ok_list([share_view(s) for s in items])


@bp.route("/mlc/shares/<share_id>", methods=["GET"])
@require_roles(*READ)
def get_share_flat(share_id, _user_id, _role):
    return ok_object(share_view(get_share(share_id)))


@bp.route("/mlc/works/<work_id>/disputes", methods=["GET"])
@require_roles("MLCAdministrator", "MemberUser", "PublicSearcher")
def list_work_disputes(work_id, _user_id, _role):
    get_work(work_id)
    items = sorted(
        (d for d in db.disputes.values() if d["work_id"] == work_id),
        key=lambda d: d["created_at"])
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    from routes.disputes import dispute_view
    return ok_list([dispute_view(d) for d in items])
