"""Account routes: account record, sanctions, posts, appeals and the appeals flow."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles, require_account_owner, current
from services import community as community_svc
from services import content
from services import appeals as appeal_svc

bp = Blueprint("accounts", __name__)

APPEAL_STATES = ("FILED", "SUBMITTED", "UNDER_WATCH", "GRANTED", "DENIED")
POST_STATUSES = ("PUBLISHED", "REMOVED", "LOCKED")


def _ownership(account_id):
    """An Account role reaches only its own account; other roles are unscoped."""
    actor = current()
    if actor.role == "Account" and account_id != actor.user_id:
        fail("ERR_FORBIDDEN_ROLE", "an account may reach only its own records")


@bp.get("/api/accounts/<account_id>")
def get_account(account_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    _ownership(account_id)
    account = content.load_account(account_id)
    content.recompute_account(account_id, touch=False)
    return R.ok(R.to_json(account))


@bp.get("/api/accounts/<account_id>/sanctions")
def list_sanctions(account_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    _ownership(account_id)
    # §3.4: the subject account's `karma_points` and `account_sanction_index` are
    # recomputed as the sanction write completes, so the account row exists as
    # soon as any sanction names it and its registry read reflects that write.
    content.recompute_account(account_id)
    records = [s for s in db.all_of("AccountSanction") if s["account_id"] == account_id]
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, ("ACTIVE", "LIFTED"))
    community = R.query_str(request.args, "community_id")
    if community is not None:
        records = [s for s in records if s["community_id"] == community]
    return R.ok_list(records, request.args)


@bp.get("/api/accounts/<account_id>/posts")
def list_account_posts(account_id):
    require_roles("Account", "Moderator", "PlatformAdmin", "ContentReviewer")
    _ownership(account_id)
    content.recompute_account(account_id)
    records = [p for p in db.all_of("Post") if p["author_account_id"] == account_id]
    community = R.query_str(request.args, "community_id")
    if community is not None:
        records = [p for p in records if p["community_id"] == community]
    status = R.query_str(request.args, "status")
    records = R.filter_enum(records, "status", status, POST_STATUSES)
    return R.ok_list(records, request.args)


# --------------------------------------------------------------------------
# Appeals (§3.6)
# --------------------------------------------------------------------------
@bp.post("/api/accounts/<account_id>/appeals")
def file_appeal(account_id):
    require_roles("Account", "PlatformAdmin")
    data = R.body(request)
    _ownership(account_id)
    content.recompute_account(account_id)
    R.as_str(data, "sanction_id")
    R.as_enum(data, "ground_code", appeal_svc.GROUND_CODES)
    R.as_str(data, "new_evidence_url", required_=False)
    R.as_bool(data, "sanction_misapplication_present", default=False)
    appeal = appeal_svc.file_appeal(account_id, data)
    return R.ok(R.to_json(appeal), status=201)


@bp.get("/api/accounts/<account_id>/appeals")
def list_appeals(account_id):
    require_roles("Account", "PlatformAdmin", "ContentReviewer")
    _ownership(account_id)
    content.recompute_account(account_id)
    records = [a for a in db.all_of("Appeal") if a["account_id"] == account_id]
    state = R.query_str(request.args, "state")
    records = R.filter_enum(records, "state", state, APPEAL_STATES)
    return R.ok_list(records, request.args)


def _load_appeal(account_id, appeal_id):
    _ownership(account_id)
    content.recompute_account(account_id)
    appeal = db.find("Appeal", appeal_id)
    if appeal is None or appeal["account_id"] != account_id:
        fail("ERR_NOT_FOUND")
    return appeal


@bp.get("/api/accounts/<account_id>/appeals/<appeal_id>")
def get_appeal(account_id, appeal_id):
    require_roles("Account", "PlatformAdmin", "ContentReviewer")
    appeal = _load_appeal(account_id, appeal_id)
    return R.ok(R.to_json(appeal))


@bp.post("/api/accounts/<account_id>/appeals/<appeal_id>/submit")
def submit_appeal(account_id, appeal_id):
    require_roles("Account", "PlatformAdmin")
    appeal = _load_appeal(account_id, appeal_id)
    appeal = appeal_svc.submit_appeal(appeal, current())
    return R.ok(R.to_json(appeal))


@bp.post("/api/accounts/<account_id>/appeals/<appeal_id>/decide")
def decide_appeal(account_id, appeal_id):
    require_roles("PlatformAdmin")
    data = R.body(request)
    appeal = _load_appeal(account_id, appeal_id)
    decision = R.as_str(data, "decision")
    appeal = appeal_svc.decide_appeal(appeal, decision)
    return R.ok(R.to_json(appeal))