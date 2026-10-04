"""Flask entry point and route registration."""
import os
from datetime import timedelta

from flask import Flask, request

from db import db, parse_iso, iso_out
from errors import ApiError, fail
from response import ok, error_response, paginate
from services import (
    require_auth, require_roles, body, req_str, req_int, req_enum, opt_enum,
    opt_str_list, stamp_new, touch, now_iso, actor_login,
    get_enterprise, get_org, get_user, get_team, get_repo, get_runner,
    get_run, get_artifact, get_entitlement, get_token, get_app_install,
    get_collab, require_org_active, emit_audit,
    user_holds_seat, recompute_seat_fields, consume_seat, reclaim_seat,
    recompute_active_committer, storage_add, storage_remove, round_storage,
    sweep_collaborator, sweep_artifact, sweep_all,
    meter_run, settle_run, refund_queued_run, cancel_run_cascade,
    refresh_repo_security_flag,
    ser_enterprise, ser_org, ser_user, ser_commit_event, ser_team,
    ser_membership, ser_repo, ser_collab, ser_runner, ser_run,
    ser_artifact, ser_entitlement, ser_token, ser_audit_event,
    ser_app_install,
    PLAN_INCLUDED_MINUTES, PLAN_INCLUDED_STORAGE_GB, PLAN_COLLAB_LIMIT,
    PRODUCT_RATE_CENTS, APP_SCOPE_CATALOG, PAT_SCOPES,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)


@app.errorhandler(Exception)
def handle_exc(e):
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


@app.before_request
def _auth():
    require_auth()


# ================= Enterprise =================

@app.route("/enterprises", methods=["POST"])
def create_enterprise():
    require_roles("EnterpriseAdmin")
    data = body()
    name = req_str(data, "name")
    purchased = req_int(data, "purchased_seats", minimum=0)
    pat_policy = opt_enum(data, "pat_policy",
                          {"UNRESTRICTED", "ADMIN_APPROVAL_REQUIRED", "DISALLOWED"},
                          "UNRESTRICTED")
    anchor = data.get("billing_cycle_anchor_day", 1)
    if isinstance(anchor, bool) or not isinstance(anchor, int) \
            or not (1 <= anchor <= 28):
        fail("ERR_INVALID_REQUEST", "billing_cycle_anchor_day must be 1-28")
    e = stamp_new({
        "name": name, "purchased_seats": purchased,
        "used_seats": 0, "available_seats": purchased,
        "sso_enforcement": "DISABLED", "pat_policy": pat_policy,
        "audit_log_stream_status": "INACTIVE",
        "billing_cycle_anchor_day": anchor,
    })
    db.enterprises[e["id"]] = e
    return ok(ser_enterprise(e), 201)


@app.route("/enterprises/<eid>", methods=["GET"])
def get_enterprise_route(eid):
    return ok(ser_enterprise(get_enterprise(eid)))


@app.route("/enterprises/<eid>/seat-usage", methods=["GET"])
def seat_usage(eid):
    require_roles("EnterpriseAdmin", "OrgAdmin")
    ent = get_enterprise(eid)
    mode = request.args.get("mode", "CYCLE")
    if mode not in ("CYCLE", "PROJECTED"):
        fail("ERR_INVALID_REQUEST", "mode must be CYCLE or PROJECTED")
    if mode == "CYCLE":
        recompute_seat_fields(ent)
        used = ent["used_seats"]
    else:
        org_ids = {o["id"] for o in db.organizations.values()
                   if o["enterprise_id"] == eid}
        window_start = db.clock - timedelta(days=90)
        proj_start = db.clock + timedelta(days=30) - timedelta(days=90)
        used = 0
        for u in db.users.values():
            commits = [parse_iso(ce["committed_at"])
                       for ce in db.commit_events.values()
                       if ce["author_user_id"] == u["id"]
                       and ce["organization_id"] in org_ids]
            recent = [c for c in commits if window_start <= c <= db.clock]
            if not recent:
                continue
            latest = max(commits)
            if latest >= proj_start:
                used += 1
    return ok({
        "used_seats": used,
        "available_seats": ent["purchased_seats"] - used,
        "purchased_seats": ent["purchased_seats"],
        "mode": mode,
    })


@app.route("/enterprises/<eid>/sso/transition", methods=["POST"])
def sso_transition(eid):
    require_roles("EnterpriseAdmin")
    ent = get_enterprise(eid)
    data = body()
    action = req_enum(data, "action", {"CONFIGURE", "ENFORCE", "SUSPEND"})
    if action == "CONFIGURE":
        if ent["sso_enforcement"] != "DISABLED":
            fail("ERR_SSO_ALREADY_CONFIGURED",
                 "sso_enforcement is not DISABLED")
        ent["sso_enforcement"] = "CONFIGURING"
        touch(ent)
        emit_audit(ent, "sso.configuration_started")
    elif action == "ENFORCE":
        if ent["sso_enforcement"] == "CONFIGURING":
            orgs = [o for o in db.organizations.values()
                    if o["enterprise_id"] == eid]
            if any(o["status"] != "ACTIVE" for o in orgs):
                fail("ERR_ORG_SUSPENDED_BLOCKS_SSO",
                     "every organization must be ACTIVE")
            # depth 1+2: revoke ACTIVE PATs created under UNRESTRICTED policy
            for t in db.tokens.values():
                if t["enterprise_id"] == eid and t["status"] == "ACTIVE" \
                        and t.get("_created_under_unrestricted"):
                    t["status"] = "REVOKED"
                    touch(t)
                    emit_audit(ent, "pat.revoked_by_sso")
            # depth 3: suspend INSTALLED apps with ADMIN_ORG scope
            org_ids = {o["id"] for o in orgs}
            for a in db.app_installations.values():
                if a["organization_id"] in org_ids \
                        and a["status"] == "INSTALLED" \
                        and "ADMIN_ORG" in a["permission_scopes"]:
                    a["status"] = "SUSPENDED"
                    touch(a)
            ent["sso_enforcement"] = "ENFORCED"
            touch(ent)
            emit_audit(ent, "sso.enforced")
        elif ent["sso_enforcement"] == "SUSPENDED":
            orgs = [o for o in db.organizations.values()
                    if o["enterprise_id"] == eid]
            if any(o["status"] != "ACTIVE" for o in orgs):
                fail("ERR_ORG_SUSPENDED_BLOCKS_SSO",
                     "every organization must be ACTIVE")
            ent["sso_enforcement"] = "ENFORCED"
            touch(ent)
            emit_audit(ent, "sso.reenforced")
        else:
            fail("ERR_SSO_NOT_CONFIGURING",
                 "ENFORCE requires sso_enforcement == CONFIGURING")
    else:  # SUSPEND
        if ent["sso_enforcement"] != "ENFORCED":
            fail("ERR_SSO_NOT_ENFORCED",
                 "SUSPEND requires sso_enforcement == ENFORCED")
        ent["sso_enforcement"] = "SUSPENDED"
        touch(ent)
        emit_audit(ent, "sso.suspended")
    return ok(ser_enterprise(ent))


@app.route("/enterprises/<eid>/billing-cycle/reset", methods=["POST"])
def billing_cycle_reset(eid):
    require_roles("EnterpriseAdmin")
    ent = get_enterprise(eid)
    orgs = [o for o in db.organizations.values() if o["enterprise_id"] == eid]
    import math
    for o in orgs:
        overage_gb = max(0, o["consumed_storage_gb"] - o["included_storage_gb"])
        o["_last_storage_overage_cents"] = math.ceil(overage_gb * 25)
        o["consumed_actions_minutes"] = 0
        live_mb = sum(a["size_mb"] for a in db.artifacts.values()
                      if a["organization_id"] == o["id"]
                      and a["status"] == "RETAINED")
        o["_storage_mb"] = live_mb
        o["consumed_storage_gb"] = round_storage(live_mb / 1024.0)
        touch(o)
    # seat reclamation sweep
    org_ids = {o["id"] for o in orgs}
    reclaimed = 0
    from services import (user_has_active_commit, user_has_membership,
                          user_has_accepted_collab)
    for u in db.users.values():
        if u.get("seat_held_enterprise_id") != eid:
            continue
        recompute_active_committer(u)
        if (not user_has_active_commit(u["id"], org_ids, db.clock)
                and not user_has_membership(u["id"], org_ids)
                and not user_has_accepted_collab(u["id"], org_ids)):
            reclaim_seat(ent, u)
            reclaimed += 1
    touch(ent)
    return ok({"reclaimed_seats": reclaimed, "orgs_reset": len(orgs)})


@app.route("/enterprises/<eid>/audit-log-stream/toggle", methods=["POST"])
def audit_stream_toggle(eid):
    require_roles("EnterpriseAdmin")
    ent = get_enterprise(eid)
    cur = ent["audit_log_stream_status"]
    nxt = {"INACTIVE": "STREAMING", "STREAMING": "PAUSED",
           "PAUSED": "STREAMING"}[cur]
    ent["audit_log_stream_status"] = nxt
    touch(ent)
    return ok(ser_enterprise(ent))


@app.route("/enterprises/<eid>/audit-log-events", methods=["GET"])
def audit_log_events(eid):
    require_roles("EnterpriseAdmin")
    get_enterprise(eid)
    events = [ev for ev in db.audit_events.values()
              if ev["enterprise_id"] == eid]
    flt = request.args.get("streamed")
    if flt is not None:
        if flt.lower() in ("true", "1", "yes"):
            events = [ev for ev in events if ev["streamed"]]
        elif flt.lower() in ("false", "0", "no"):
            events = [ev for ev in events if not ev["streamed"]]
        else:
            fail("ERR_INVALID_REQUEST", "streamed must be boolean")
    events.sort(key=lambda ev: ev["created_at"])
    page, pmeta = paginate(events, request.args)
    return ok([ser_audit_event(ev) for ev in page], pagination=pmeta)


# ================= Organization =================

@app.route("/organizations", methods=["POST"])
def create_org():
    require_roles("EnterpriseAdmin")
    data = body()
    ent = get_enterprise(req_str(data, "enterprise_id"))
    login = req_str(data, "login")
    plan = opt_enum(data, "plan_tier", {"FREE", "TEAM", "ENTERPRISE"}, "TEAM")
    windows = data.get("retention_freeze_windows", [])
    if windows is None:
        windows = []
    if not isinstance(windows, list):
        fail("ERR_INVALID_REQUEST", "retention_freeze_windows must be a list")
    norm_windows = []
    for w in windows:
        if not isinstance(w, dict) or "start" not in w or "end" not in w:
            fail("ERR_INVALID_REQUEST",
                 "each freeze window needs start and end")
        try:
            s = parse_iso(w["start"])
            e = parse_iso(w["end"])
        except Exception:
            fail("ERR_INVALID_REQUEST", "freeze window start/end must be ISO8601")
        norm_windows.append({"start": iso_out(s), "end": iso_out(e)})
    o = stamp_new({
        "enterprise_id": ent["id"], "login": login, "plan_tier": plan,
        "included_actions_minutes": PLAN_INCLUDED_MINUTES[plan],
        "included_storage_gb": PLAN_INCLUDED_STORAGE_GB[plan],
        "consumed_actions_minutes": 0,
        "consumed_storage_gb": 0.0,
        "outside_collaborator_limit": PLAN_COLLAB_LIMIT[plan],
        "retention_freeze_windows": norm_windows,
        "status": "ACTIVE", "_storage_mb": 0,
    })
    db.organizations[o["id"]] = o
    return ok(ser_org(o), 201)


@app.route("/organizations/<oid>", methods=["GET"])
def get_org_route(oid):
    return ok(ser_org(get_org(oid)))


@app.route("/organizations/<oid>/transition", methods=["POST"])
def org_transition(oid):
    require_roles("EnterpriseAdmin")
    org = get_org(oid)
    data = body()
    action = req_enum(data, "action", {"SUSPEND", "UNSUSPEND", "ARCHIVE"})
    ent = db.enterprises[org["enterprise_id"]]
    if action == "SUSPEND":
        if org["status"] != "ACTIVE":
            fail("ERR_ORG_NOT_ACTIVE", "organization must be ACTIVE")
        org["status"] = "SUSPENDED"
        touch(org)
        for r in db.runners.values():
            if r["organization_id"] == oid and r["status"] == "ACTIVE":
                r["status"] = "OFFLINE"
                touch(r)
        refunded = False
        for run in db.workflow_runs.values():
            if run["organization_id"] == oid \
                    and run["execution_status"] == "QUEUED":
                cancel_run_cascade(run)
                refunded = True
        if refunded:
            touch(ent)
        for e in db.entitlements.values():
            if e["organization_id"] == oid and e["status"] == "ACTIVE":
                e["status"] = "SUSPENDED"
                touch(e)
                repo = db.repositories.get(e["repository_id"])
                if repo:
                    refresh_repo_security_flag(repo)
                    touch(repo)
        emit_audit(ent, "org.suspended")
    elif action == "UNSUSPEND":
        if ent["sso_enforcement"] == "CONFIGURING":
            fail("ERR_SSO_CONFIGURATION_IN_FLIGHT",
                 "enterprise SSO configuration in flight")
        if org["status"] != "SUSPENDED":
            fail("ERR_ORG_NOT_SUSPENDED", "organization must be SUSPENDED")
        org["status"] = "ACTIVE"
        touch(org)
        for e in db.entitlements.values():
            if e["organization_id"] == oid and e["status"] == "SUSPENDED":
                e["status"] = "ACTIVE"
                touch(e)
                repo = db.repositories.get(e["repository_id"])
                if repo:
                    refresh_repo_security_flag(repo)
                    touch(repo)
        emit_audit(ent, "org.unsuspended")
    else:  # ARCHIVE
        if org["status"] != "ACTIVE":
            fail("ERR_ORG_NOT_ACTIVE", "organization must be ACTIVE")
        for run in db.workflow_runs.values():
            if run["organization_id"] == oid and run["execution_status"] \
                    in ("QUEUED", "RUNNING"):
                fail("ERR_INFLIGHT_RUNS_EXIST",
                     "org has QUEUED or RUNNING workflow runs")
        for e in db.entitlements.values():
            if e["organization_id"] == oid and e["status"] != "CANCELLED":
                fail("ERR_ACTIVE_ENTITLEMENTS_EXIST",
                     "all entitlements must be CANCELLED")
        org["status"] = "ARCHIVED"
        touch(org)
        for r in db.repositories.values():
            if r["organization_id"] == oid and r["status"] == "ACTIVE":
                r["status"] = "ARCHIVED"
                touch(r)
        for c in db.collaborators.values():
            if c["organization_id"] == oid \
                    and c["status"] in ("INVITED", "ACCEPTED"):
                c["status"] = "REVOKED"
                touch(c)
        for a in db.app_installations.values():
            if a["organization_id"] == oid \
                    and a["status"] in ("INSTALLED", "SUSPENDED"):
                a["status"] = "UNINSTALLED"
                touch(a)
        emit_audit(ent, "org.archived")
    return ok(ser_org(org))


# ================= Users & Commit Events =================

@app.route("/users", methods=["POST"])
def create_user():
    require_roles("EnterpriseAdmin")
    data = body()
    login = req_str(data, "login")
    email = req_str(data, "email")
    u = stamp_new({
        "login": login, "email": email,
        "is_active_committer": False,
        "seat_held_enterprise_id": None,
        "status": "ACTIVE",
    })
    db.users[u["id"]] = u
    return ok(ser_user(u), 201)


@app.route("/users/<uid>", methods=["GET"])
def get_user_route(uid):
    return ok(ser_user(get_user(uid)))


@app.route("/users/<uid>/transition", methods=["POST"])
def user_transition(uid):
    require_roles("EnterpriseAdmin")
    u = get_user(uid)
    data = body()
    action = req_enum(data, "action", {"SUSPEND", "UNSUSPEND"})
    if action == "SUSPEND":
        if u["status"] != "ACTIVE":
            fail("ERR_USER_NOT_ACTIVE", "user must be ACTIVE")
        ent_id = u.get("seat_held_enterprise_id")
        if ent_id:
            ent = db.enterprises.get(ent_id)
            if ent:
                reclaim_seat(ent, u, "seat.reclaimed")
        u["status"] = "SUSPENDED"
        touch(u)
        for t in db.tokens.values():
            if t["user_id"] == uid and t["status"] in ("PENDING_APPROVAL",
                                                       "ACTIVE"):
                t["status"] = "REVOKED"
                touch(t)
        for c in db.collaborators.values():
            if c["user_id"] == uid and c["status"] in ("INVITED", "ACCEPTED"):
                c["status"] = "REVOKED"
                touch(c)
    else:  # UNSUSPEND
        if u["status"] != "SUSPENDED":
            fail("ERR_USER_NOT_SUSPENDED", "user must be SUSPENDED")
        u["status"] = "ACTIVE"
        touch(u)
    return ok(ser_user(u))


@app.route("/commit-events", methods=["POST"])
def create_commit_event():
    require_roles("OrgAdmin", "EnterpriseAdmin")
    data = body()
    author = get_user(req_str(data, "author_user_id"))
    org = get_org(req_str(data, "organization_id"))
    committed_raw = req_str(data, "committed_at")
    try:
        committed = parse_iso(committed_raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "committed_at must be ISO8601")
    ent = db.enterprises[org["enterprise_id"]]
    had_seat = user_holds_seat(author["id"], ent["id"])
    if not had_seat:
        consume_seat(ent, author, "seat.consumed")
    ce = {
        "id": __import__("services").new_id(),
        "author_user_id": author["id"],
        "organization_id": org["id"],
        "committed_at": iso_out(committed),
        "created_at": now_iso(),
    }
    db.commit_events[ce["id"]] = ce
    recompute_active_committer(author)
    return ok(ser_commit_event(ce), 201)


# ================= Teams & Memberships =================

def _check_team_cycle(org_id, start_parent_id, exclude_team_id=None):
    seen = set()
    if exclude_team_id:
        seen.add(exclude_team_id)
    cur = start_parent_id
    while cur:
        if cur in seen:
            fail("ERR_TEAM_CYCLE", "parent_team_id chain forms a cycle")
        seen.add(cur)
        t = db.teams.get(cur)
        if not t:
            fail("ERR_TEAM_NOT_FOUND", "parent team not found")
        if t["organization_id"] != org_id:
            fail("ERR_CROSS_ORG_REFERENCE",
                 "parent team belongs to another organization")
        cur = t.get("parent_team_id")


@app.route("/teams", methods=["POST"])
def create_team():
    require_roles("OrgAdmin")
    data = body()
    org = get_org(req_str(data, "organization_id"))
    require_org_active(org)
    name = req_str(data, "name")
    parent_id = data.get("parent_team_id")
    if parent_id is not None:
        if not isinstance(parent_id, str):
            fail("ERR_INVALID_REQUEST", "parent_team_id must be a string")
        _check_team_cycle(org["id"], parent_id)
    t = stamp_new({
        "organization_id": org["id"], "name": name,
        "parent_team_id": parent_id,
    })
    db.teams[t["id"]] = t
    return ok(ser_team(t), 201)


@app.route("/organizations/<oid>/teams", methods=["GET"])
def list_teams(oid):
    get_org(oid)
    teams = [t for t in db.teams.values() if t["organization_id"] == oid]
    teams.sort(key=lambda t: t["created_at"])
    page, pmeta = paginate(teams, request.args)
    return ok([ser_team(t) for t in page], pagination=pmeta)


@app.route("/teams/<tid>/memberships", methods=["POST"])
def add_membership(tid):
    require_roles("OrgAdmin")
    team = get_team(tid)
    org = db.organizations[team["organization_id"]]
    require_org_active(org)
    data = body()
    user = get_user(req_str(data, "user_id"))
    role = opt_enum(data, "role", {"MEMBER", "MAINTAINER"}, "MEMBER")
    existing = next((m for m in db.memberships.values()
                     if m["team_id"] == tid and m["user_id"] == user["id"]),
                    None)
    if existing:
        existing["role"] = role
        touch(existing)
        return ok(ser_membership(existing), 201)
    ent = db.enterprises[org["enterprise_id"]]
    if not user_holds_seat(user["id"], ent["id"]):
        consume_seat(ent, user, "seat.consumed")
    m = stamp_new({
        "team_id": tid, "user_id": user["id"], "role": role,
    })
    db.memberships[m["id"]] = m
    return ok(ser_membership(m), 201)


# ================= Repositories =================

@app.route("/repositories", methods=["POST"])
def create_repo():
    require_roles("OrgAdmin")
    data = body()
    org = get_org(req_str(data, "organization_id"))
    require_org_active(org)
    name = req_str(data, "name")
    visibility = opt_enum(data, "visibility",
                          {"PRIVATE", "INTERNAL", "PUBLIC"}, "PRIVATE")
    if visibility == "PUBLIC":
        ent = db.enterprises[org["enterprise_id"]]
        if ent["sso_enforcement"] == "DISABLED":
            fail("ERR_VISIBILITY_REQUIRES_SSO",
                 "PUBLIC visibility requires sso_enforcement != DISABLED")
    r = stamp_new({
        "organization_id": org["id"], "name": name,
        "visibility": visibility,
        "advanced_security_enabled": False,
        "status": "ACTIVE",
    })
    db.repositories[r["id"]] = r
    return ok(ser_repo(r), 201)


@app.route("/repositories/<rid>", methods=["GET"])
def get_repo_route(rid):
    return ok(ser_repo(get_repo(rid)))


@app.route("/repositories/<rid>", methods=["PATCH"])
def patch_repo(rid):
    require_roles("OrgAdmin")
    repo = get_repo(rid)
    org = db.organizations[repo["organization_id"]]
    ent = db.enterprises[org["enterprise_id"]]
    require_org_active(org)
    data = body()
    status = data.get("status")
    if status is not None:
        if status != "ARCHIVED":
            fail("ERR_INVALID_REQUEST", "status may only be set to ARCHIVED")
        if repo["status"] != "ACTIVE":
            fail("ERR_REPO_NOT_ACTIVE", "repository must be ACTIVE")
        repo["status"] = "ARCHIVED"
        touch(repo)
        for run in db.workflow_runs.values():
            if run["repository_id"] == rid \
                    and run["execution_status"] == "QUEUED":
                cancel_run_cascade(run)
        for a in db.artifacts.values():
            if a["repository_id"] == rid and a["status"] == "RETAINED":
                a["status"] = "DELETED"
                touch(a)
                storage_remove(org, a["size_mb"])
        touch(org)
        return ok(ser_repo(repo))
    if repo["status"] != "ACTIVE":
        fail("ERR_REPO_NOT_ACTIVE", "repository must be ACTIVE")
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str) or not data["name"].strip():
            fail("ERR_INVALID_REQUEST", "name must be a non-empty string")
        repo["name"] = data["name"].strip()
    if "visibility" in data and data["visibility"] is not None:
        vis = data["visibility"]
        if vis not in ("PRIVATE", "INTERNAL", "PUBLIC"):
            fail("ERR_INVALID_REQUEST", "invalid visibility")
        if vis != repo["visibility"]:
            if vis == "PUBLIC" and ent["sso_enforcement"] == "DISABLED":
                fail("ERR_VISIBILITY_REQUIRES_SSO",
                     "PUBLIC visibility requires sso_enforcement != DISABLED")
            repo["visibility"] = vis
            emit_audit(ent, "repo.visibility_changed")
    touch(repo)
    return ok(ser_repo(repo))


# ================= Outside Collaborators =================

@app.route("/organizations/<oid>/outside-collaborators", methods=["POST"])
def invite_collaborator(oid):
    require_roles("OrgAdmin")
    org = get_org(oid)
    require_org_active(org)
    data = body()
    user = get_user(req_str(data, "user_id"))
    repo_id = req_str(data, "repository_id")
    repo = db.repositories.get(repo_id)
    if not repo:
        fail("ERR_REPO_NOT_FOUND", "repository not found")
    if repo["organization_id"] != oid:
        fail("ERR_CROSS_ORG_REFERENCE",
             "repository belongs to another organization")
    active = sum(1 for c in db.collaborators.values()
                 if c["organization_id"] == oid
                 and c["status"] in ("INVITED", "ACCEPTED"))
    if active >= org["outside_collaborator_limit"]:
        fail("ERR_COLLABORATOR_LIMIT_REACHED",
             "outside collaborator limit reached")
    expires = db.clock + timedelta(days=7)
    c = stamp_new({
        "organization_id": oid, "user_id": user["id"],
        "repository_id": repo_id,
        "invite_expires_at": iso_out(expires),
        "status": "INVITED",
    })
    db.collaborators[c["id"]] = c
    return ok(ser_collab(c), 201)


@app.route("/outside-collaborators/<cid>/accept", methods=["POST"])
def accept_collaborator(cid):
    require_roles("UserAccount")
    c = get_collab(cid)
    sweep_collaborator(c)
    org = db.organizations[c["organization_id"]]
    if c["user_id"] != request.user_id:
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "only the invited user may accept")
    if c["status"] != "INVITED":
        if c["status"] == "EXPIRED":
            fail("ERR_INVITE_EXPIRED", "invitation has expired")
        fail("ERR_INVALID_REQUEST", "invitation is not in INVITED state")
    require_org_active(org)
    user = db.users[c["user_id"]]
    if user["status"] != "ACTIVE":
        fail("ERR_USER_NOT_ACTIVE", "invited user must be ACTIVE")
    if db.clock >= parse_iso(c["invite_expires_at"]):
        c["status"] = "EXPIRED"
        touch(c)
        fail("ERR_INVITE_EXPIRED", "invitation has expired")
    ent = db.enterprises[org["enterprise_id"]]
    if not user_holds_seat(user["id"], ent["id"]) \
            and not user["is_active_committer"]:
        consume_seat(ent, user, "seat.consumed")
        c["_provisional_seat"] = True
    c["status"] = "ACCEPTED"
    touch(c)
    return ok(ser_collab(c))


@app.route("/outside-collaborators/<cid>", methods=["DELETE"])
def revoke_collaborator(cid):
    require_roles("OrgAdmin")
    c = get_collab(cid)
    sweep_collaborator(c)
    org = db.organizations[c["organization_id"]]
    ent = db.enterprises[org["enterprise_id"]]
    prev = c["status"]
    if prev in ("INVITED", "ACCEPTED"):
        c["status"] = "REVOKED"
        touch(c)
        if prev == "ACCEPTED" and c.get("_provisional_seat"):
            user = db.users[c["user_id"]]
            from services import (user_has_membership,
                                  user_has_accepted_collab,
                                  user_has_active_commit)
            org_ids = {o["id"] for o in db.organizations.values()
                       if o["enterprise_id"] == ent["id"]}
            if not user_has_accepted_collab(user["id"], org_ids) \
                    and not user_has_membership(user["id"], org_ids):
                reclaim_seat(ent, user)
    return ok(ser_collab(c))


# ================= Self-Hosted Runners =================

@app.route("/organizations/<oid>/runners", methods=["POST"])
def create_runner(oid):
    require_roles("OrgAdmin")
    org = get_org(oid)
    require_org_active(org)
    data = body()
    name = req_str(data, "name")
    os_type = req_enum(data, "os_type", {"LINUX", "WINDOWS", "MACOS"})
    labels = opt_str_list(data, "labels")
    allowed = data.get("allowed_on_public_repos", False)
    if not isinstance(allowed, bool):
        fail("ERR_INVALID_REQUEST", "allowed_on_public_repos must be boolean")
    r = stamp_new({
        "organization_id": oid, "name": name, "os_type": os_type,
        "labels": labels, "allowed_on_public_repos": allowed,
        "status": "REGISTERED",
    })
    db.runners[r["id"]] = r
    return ok(ser_runner(r), 201)


@app.route("/runners/<rid>/heartbeat", methods=["POST"])
def runner_heartbeat(rid):
    require_roles("RunnerAgent")
    r = get_runner(rid)
    org = db.organizations[r["organization_id"]]
    if r["status"] not in ("REGISTERED", "OFFLINE"):
        fail("ERR_RUNNER_NOT_ACTIVATABLE",
             "runner must be REGISTERED or OFFLINE")
    require_org_active(org)
    r["status"] = "ACTIVE"
    touch(r)
    return ok(ser_runner(r))


@app.route("/runners/<rid>", methods=["DELETE"])
def delete_runner(rid):
    require_roles("OrgAdmin")
    r = get_runner(rid)
    if r["status"] == "REMOVED":
        fail("ERR_RUNNER_NOT_FOUND", "runner already removed")
    if r["status"] == "ACTIVE":
        for run in db.workflow_runs.values():
            if run.get("runner_id") == rid \
                    and run["execution_status"] == "RUNNING":
                fail("ERR_RUNNER_IN_USE",
                     "runner referenced by a RUNNING workflow run")
    r["status"] = "REMOVED"
    touch(r)
    return ok(ser_runner(r))


# ================= Workflow Runs =================

@app.route("/repositories/<rid>/workflow-runs", methods=["POST"])
def dispatch_run(rid):
    require_roles("OrgAdmin", "UserAccount")
    repo = get_repo(rid)
    org = db.organizations[repo["organization_id"]]
    require_org_active(org)
    if repo["status"] != "ACTIVE":
        fail("ERR_REPO_NOT_ACTIVE", "repository must be ACTIVE")
    data = body()
    expected = req_int(data, "expected_repository_version", minimum=0)
    if expected != repo["version"]:
        fail("ERR_STALE_VERSION", "repository version mismatch")
    runner_kind = req_enum(data, "runner_kind", {"HOSTED", "SELF_HOSTED"})
    os_type = req_enum(data, "os_type", {"LINUX", "WINDOWS", "MACOS"})
    requested = req_int(data, "requested_minutes", minimum=1)
    runner_id = data.get("runner_id")
    required_labels = opt_str_list(data, "required_labels")
    runner = None
    if runner_kind == "SELF_HOSTED":
        if not runner_id:
            fail("ERR_INVALID_REQUEST",
                 "runner_id required for SELF_HOSTED runs")
        runner = db.runners.get(runner_id)
        if not runner:
            fail("ERR_RUNNER_NOT_FOUND", "runner not found")
        if repo["visibility"] == "PUBLIC" \
                and not runner["allowed_on_public_repos"]:
            fail("ERR_PUBLIC_REPO_RUNNER_FORBIDDEN",
                 "self-hosted runner not allowed on public repos")
        if not set(required_labels).issubset(set(runner["labels"])):
            fail("ERR_RUNNER_LABEL_MISMATCH",
                 "runner labels do not cover required_labels")
        if runner["organization_id"] != org["id"]:
            fail("ERR_CROSS_ORG_REFERENCE",
                 "runner belongs to another organization")
    else:
        if runner_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "runner_id must be null for HOSTED runs")
    run = stamp_new({
        "repository_id": rid, "organization_id": org["id"],
        "runner_id": runner_id, "runner_kind": runner_kind,
        "os_type": os_type, "requested_minutes": requested,
        "billed_minutes": 0, "overage_cost_cents": 0,
        "execution_status": "QUEUED", "billing_status": "METERED",
    })
    db.workflow_runs[run["id"]] = run
    touch(repo)
    return ok(ser_run(run), 201)


@app.route("/repositories/<rid>/workflow-runs", methods=["GET"])
def list_runs(rid):
    get_repo(rid)
    runs = [r for r in db.workflow_runs.values()
            if r["repository_id"] == rid]
    ef = request.args.get("execution_status")
    bf = request.args.get("billing_status")
    if ef:
        runs = [r for r in runs if r["execution_status"] == ef]
    if bf:
        runs = [r for r in runs if r["billing_status"] == bf]
    runs.sort(key=lambda r: r["created_at"])
    page, pmeta = paginate(runs, request.args)
    return ok([ser_run(r) for r in page], pagination=pmeta)


@app.route("/workflow-runs/<rid>/transition", methods=["POST"])
def run_transition(rid):
    require_roles("RunnerAgent", "OrgAdmin")
    run = get_run(rid)
    data = body()
    action = req_enum(data, "action", {"START", "COMPLETE", "FAIL", "CANCEL"})
    if action == "START":
        if request.user_role != "RunnerAgent":
            fail("ERR_INSUFFICIENT_PERMISSIONS",
                 "START requires RunnerAgent role")
        if run["execution_status"] != "QUEUED":
            fail("ERR_RUN_NOT_QUEUED", "run must be QUEUED")
        if run["runner_kind"] == "SELF_HOSTED":
            runner = db.runners.get(run["runner_id"])
            if not runner or runner["status"] != "ACTIVE":
                fail("ERR_RUNNER_NOT_ACTIVE", "runner must be ACTIVE")
        meter_run(run)
        run["execution_status"] = "RUNNING"
        touch(run)
    elif action in ("COMPLETE", "FAIL"):
        if request.user_role != "RunnerAgent":
            fail("ERR_INSUFFICIENT_PERMISSIONS",
                 f"{action} requires RunnerAgent role")
        if run["execution_status"] != "RUNNING":
            fail("ERR_RUN_NOT_RUNNING", "run must be RUNNING")
        settle_run(run)
        run["execution_status"] = "COMPLETED" if action == "COMPLETE" \
            else "FAILED"
        touch(run)
    else:  # CANCEL
        if run["execution_status"] == "QUEUED":
            refund_queued_run(run)
            run["execution_status"] = "CANCELLED"
            touch(run)
        elif run["execution_status"] == "RUNNING":
            settle_run(run)
            run["execution_status"] = "CANCELLED"
            touch(run)
        else:
            fail("ERR_INVALID_REQUEST",
                 "run cannot be cancelled from its current state")
    return ok(ser_run(run))


# ================= Storage Artifacts =================

@app.route("/repositories/<rid>/artifacts", methods=["POST"])
def create_artifact(rid):
    require_roles("OrgAdmin", "UserAccount")
    repo = get_repo(rid)
    org = db.organizations[repo["organization_id"]]
    require_org_active(org)
    if repo["status"] != "ACTIVE":
        fail("ERR_REPO_NOT_ACTIVE", "repository must be ACTIVE")
    data = body()
    name = req_str(data, "name")
    size_mb = req_int(data, "size_mb", minimum=1)
    retention = data.get("retention_days", 90)
    if isinstance(retention, bool) or not isinstance(retention, int) \
            or not (1 <= retention <= 400):
        fail("ERR_INVALID_REQUEST", "retention_days must be 1-400")
    created = db.clock
    expires = created + timedelta(days=retention)
    for w in org["retention_freeze_windows"]:
        fs = parse_iso(w["start"])
        fe = parse_iso(w["end"])
        if created < fe and fs < expires:
            fail("ERR_RETENTION_FREEZE_CONFLICT",
                 "retention window overlaps a freeze window")
    a = stamp_new({
        "repository_id": rid, "organization_id": org["id"],
        "name": name, "size_mb": size_mb, "retention_days": retention,
        "expires_at": iso_out(expires), "status": "RETAINED",
    })
    db.artifacts[a["id"]] = a
    storage_add(org, size_mb)
    touch(org)
    return ok(ser_artifact(a), 201)


@app.route("/repositories/<rid>/artifacts", methods=["GET"])
def list_artifacts(rid):
    get_repo(rid)
    arts = [a for a in db.artifacts.values() if a["repository_id"] == rid]
    for a in arts:
        sweep_artifact(a)
    sf = request.args.get("status")
    if sf:
        arts = [a for a in arts if a["status"] == sf]
    arts.sort(key=lambda a: a["created_at"])
    page, pmeta = paginate(arts, request.args)
    return ok([ser_artifact(a) for a in page], pagination=pmeta)


@app.route("/artifacts/<aid>", methods=["DELETE"])
def delete_artifact(aid):
    require_roles("OrgAdmin")
    a = get_artifact(aid)
    sweep_artifact(a)
    if a["status"] == "RETAINED":
        a["status"] = "DELETED"
        touch(a)
        org = db.organizations[a["organization_id"]]
        storage_remove(org, a["size_mb"])
        touch(org)
    return ok(ser_artifact(a))


# ================= Security Entitlements =================

@app.route("/organizations/<oid>/security-entitlements", methods=["POST"])
def create_entitlement(oid):
    require_roles("OrgAdmin")
    org = get_org(oid)
    require_org_active(org)
    data = body()
    expected = req_int(data, "expected_organization_version", minimum=0)
    if expected != org["version"]:
        fail("ERR_STALE_VERSION", "organization version mismatch")
    repo_id = req_str(data, "repository_id")
    repo = db.repositories.get(repo_id)
    if not repo:
        fail("ERR_REPO_NOT_FOUND", "repository not found")
    if repo["organization_id"] != oid:
        fail("ERR_CROSS_ORG_REFERENCE",
             "repository belongs to another organization")
    product = req_enum(data, "product",
                       {"SECRET_SCANNING", "CODE_SCANNING",
                        "DEPENDENCY_REVIEW"})
    for e in db.entitlements.values():
        if e["repository_id"] == repo_id and e["product"] == product \
                and e["status"] in ("ACTIVE", "PENDING_ACTIVATION"):
            fail("ERR_DUPLICATE_ENTITLEMENT",
                 "live entitlement exists for repository+product")
    e = stamp_new({
        "organization_id": oid, "repository_id": repo_id,
        "product": product, "committer_count": 0,
        "monthly_price_cents": 0, "status": "PENDING_ACTIVATION",
    })
    db.entitlements[e["id"]] = e
    touch(org)
    return ok(ser_entitlement(e), 201)


@app.route("/security-entitlements/<eid>/transition", methods=["POST"])
def entitlement_transition(eid):
    require_roles("OrgAdmin")
    e = get_entitlement(eid)
    org = db.organizations[e["organization_id"]]
    data = body()
    action = req_enum(data, "action",
                      {"ACTIVATE", "SUSPEND", "RESUME", "CANCEL"})
    repo = db.repositories.get(e["repository_id"])
    if action == "ACTIVATE":
        if org["plan_tier"] not in ("TEAM", "ENTERPRISE"):
            fail("ERR_PLAN_TIER_INSUFFICIENT",
                 "plan tier must be TEAM or ENTERPRISE")
        require_org_active(org)
        if e["status"] != "PENDING_ACTIVATION":
            fail("ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION",
                 "entitlement must be PENDING_ACTIVATION")
        window_start = db.clock - timedelta(days=90)
        authors = {ce["author_user_id"] for ce in db.commit_events.values()
                   if ce["organization_id"] == e["organization_id"]
                   and window_start <= parse_iso(ce["committed_at"]) <= db.clock}
        count = len(authors)
        if count < 1:
            fail("ERR_NO_ACTIVE_COMMITTERS",
                 "at least one active committer required")
        e["committer_count"] = count
        e["monthly_price_cents"] = count * PRODUCT_RATE_CENTS[e["product"]]
        e["status"] = "ACTIVE"
        touch(e)
        if repo:
            refresh_repo_security_flag(repo)
            touch(repo)
    elif action == "SUSPEND":
        if e["status"] != "ACTIVE":
            fail("ERR_INVALID_REQUEST", "SUSPEND requires ACTIVE entitlement")
        e["status"] = "SUSPENDED"
        touch(e)
        if repo:
            refresh_repo_security_flag(repo)
            touch(repo)
    elif action == "RESUME":
        require_org_active(org)
        if e["status"] != "SUSPENDED":
            fail("ERR_INVALID_REQUEST", "RESUME requires SUSPENDED entitlement")
        e["status"] = "ACTIVE"
        touch(e)
        if repo:
            refresh_repo_security_flag(repo)
            touch(repo)
    else:  # CANCEL
        if e["status"] not in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_REQUEST",
                 "CANCEL requires a non-terminal entitlement")
        was_active = e["status"] == "ACTIVE"
        e["status"] = "CANCELLED"
        touch(e)
        if was_active and repo:
            refresh_repo_security_flag(repo)
            touch(repo)
    return ok(ser_entitlement(e))


# ================= Personal Access Tokens =================

@app.route("/users/<uid>/personal-access-tokens", methods=["POST"])
def create_token(uid):
    require_roles("UserAccount")
    user = get_user(uid)
    if request.user_id != uid:
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "X-User-ID must equal the path userId")
    data = body()
    ent = get_enterprise(req_str(data, "enterprise_id"))
    scopes = data.get("scopes")
    if not isinstance(scopes, list) or not scopes \
            or not all(isinstance(s, str) for s in scopes):
        fail("ERR_INVALID_REQUEST", "scopes must be a non-empty list")
    if not set(scopes).issubset(PAT_SCOPES):
        fail("ERR_INVALID_REQUEST", "scope outside declared set")
    if ent["pat_policy"] == "DISALLOWED":
        fail("ERR_PAT_POLICY_DISALLOWED",
             "enterprise disallows personal access tokens")
    status = "ACTIVE" if ent["pat_policy"] == "UNRESTRICTED" \
        else "PENDING_APPROVAL"
    t = stamp_new({
        "user_id": user["id"], "enterprise_id": ent["id"],
        "scopes": list(scopes), "status": status,
        "_created_under_unrestricted": ent["pat_policy"] == "UNRESTRICTED",
    })
    db.tokens[t["id"]] = t
    return ok(ser_token(t), 201)


@app.route("/users/<uid>/personal-access-tokens", methods=["GET"])
def list_tokens(uid):
    require_roles("UserAccount", "EnterpriseAdmin")
    get_user(uid)
    if request.user_role == "UserAccount" and request.user_id != uid:
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "users may only list their own tokens")
    toks = [t for t in db.tokens.values() if t["user_id"] == uid]
    sf = request.args.get("status")
    if sf:
        toks = [t for t in toks if t["status"] == sf]
    toks.sort(key=lambda t: t["created_at"])
    page, pmeta = paginate(toks, request.args)
    return ok([ser_token(t) for t in page], pagination=pmeta)


@app.route("/personal-access-tokens/<tid>/transition", methods=["POST"])
def token_transition(tid):
    require_roles("UserAccount", "EnterpriseAdmin")
    t = get_token(tid)
    data = body()
    action = req_enum(data, "action", {"APPROVE", "REVOKE"})
    ent = db.enterprises[t["enterprise_id"]]
    if action == "APPROVE":
        if request.user_role != "EnterpriseAdmin":
            fail("ERR_INSUFFICIENT_PERMISSIONS",
                 "APPROVE requires EnterpriseAdmin")
        if ent["sso_enforcement"] == "ENFORCED" \
                and "ADMIN_ORG" in t["scopes"]:
            fail("ERR_SCOPE_FORBIDDEN_UNDER_SSO",
                 "ADMIN_ORG scope forbidden while SSO enforced")
        if t["status"] != "PENDING_APPROVAL":
            fail("ERR_TOKEN_NOT_PENDING",
                 "token must be PENDING_APPROVAL")
        t["status"] = "ACTIVE"
        touch(t)
        emit_audit(ent, "pat.approved")
    else:  # REVOKE
        if request.user_role == "UserAccount" \
                and request.user_id != t["user_id"]:
            fail("ERR_INSUFFICIENT_PERMISSIONS",
                 "users may only revoke their own tokens")
        if t["status"] not in ("PENDING_APPROVAL", "ACTIVE"):
            fail("ERR_INVALID_REQUEST",
                 "token cannot be revoked from its current state")
        was_active = t["status"] == "ACTIVE"
        t["status"] = "REVOKED"
        touch(t)
        if was_active:
            emit_audit(ent, "pat.revoked")
    return ok(ser_token(t))


# ================= Marketplace App Installations =================

@app.route("/organizations/<oid>/app-installations", methods=["POST"])
def create_app_install(oid):
    require_roles("OrgAdmin")
    org = get_org(oid)
    require_org_active(org)
    data = body()
    slug = req_str(data, "app_slug")
    scopes = data.get("permission_scopes")
    if not isinstance(scopes, list) \
            or not all(isinstance(s, str) for s in scopes):
        fail("ERR_INVALID_REQUEST", "permission_scopes must be a list")
    if not set(scopes).issubset(APP_SCOPE_CATALOG):
        fail("ERR_INVALID_APP_SCOPE", "scope outside the declared catalog")
    a = stamp_new({
        "organization_id": oid, "app_slug": slug,
        "permission_scopes": list(scopes), "status": "PENDING",
    })
    db.app_installations[a["id"]] = a
    return ok(ser_app_install(a), 201)


@app.route("/app-installations/<iid>/transition", methods=["POST"])
def app_install_transition(iid):
    require_roles("OrgAdmin")
    a = get_app_install(iid)
    org = db.organizations[a["organization_id"]]
    ent = db.enterprises[org["enterprise_id"]]
    data = body()
    action = req_enum(data, "action",
                      {"INSTALL", "SUSPEND", "RESUME", "UNINSTALL"})
    if action == "INSTALL":
        if a["status"] != "PENDING":
            fail("ERR_INVALID_REQUEST", "INSTALL requires PENDING")
        if ent["sso_enforcement"] == "ENFORCED" \
                and "ADMIN_ORG" in a["permission_scopes"]:
            fail("ERR_SCOPE_FORBIDDEN_UNDER_SSO",
                 "ADMIN_ORG scope forbidden while SSO enforced")
        require_org_active(org)
        a["status"] = "INSTALLED"
        touch(a)
        emit_audit(ent, "app.installed")
    elif action == "SUSPEND":
        if a["status"] != "INSTALLED":
            fail("ERR_INVALID_REQUEST", "SUSPEND requires INSTALLED")
        a["status"] = "SUSPENDED"
        touch(a)
        emit_audit(ent, "app.suspended")
    elif action == "RESUME":
        require_org_active(org)
        if a["status"] != "SUSPENDED":
            fail("ERR_INVALID_REQUEST", "RESUME requires SUSPENDED")
        a["status"] = "INSTALLED"
        touch(a)
    else:  # UNINSTALL
        if a["status"] not in ("PENDING", "INSTALLED", "SUSPENDED"):
            fail("ERR_INVALID_REQUEST",
                 "UNINSTALL requires a non-terminal state")
        a["status"] = "UNINSTALLED"
        touch(a)
    return ok(ser_app_install(a))


# ================= Clock =================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("EnterpriseAdmin")
    data = body()
    raw = req_str(data, "to_iso8601")
    try:
        new_clock = parse_iso(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be ISO8601")
    db.clock = new_clock
    sweep_all()
    return ok({"current_utc": iso_out(db.clock)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
