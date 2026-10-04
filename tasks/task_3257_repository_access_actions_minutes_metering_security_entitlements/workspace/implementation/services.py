"""Shared domain helpers: serialization, auth, seats, audit, sweeps."""
import uuid
from datetime import timedelta

from flask import request

from db import db, iso_out, parse_iso
from errors import fail

VALID_ROLES = {"EnterpriseAdmin", "OrgAdmin", "UserAccount", "RunnerAgent"}

PLAN_INCLUDED_MINUTES = {"FREE": 500, "TEAM": 3000, "ENTERPRISE": 50000}
PLAN_INCLUDED_STORAGE_GB = {"FREE": 0.5, "TEAM": 2, "ENTERPRISE": 50}
PLAN_COLLAB_LIMIT = {"FREE": 10, "TEAM": 100, "ENTERPRISE": 1000}
OS_MULTIPLIER = {"LINUX": 1.0, "WINDOWS": 2.0, "MACOS": 10.0}
OVERAGE_CENTS_PER_MIN = {"LINUX": 0.8, "WINDOWS": 1.6, "MACOS": 8.0}
PRODUCT_RATE_CENTS = {"SECRET_SCANNING": 1900, "CODE_SCANNING": 3000,
                      "DEPENDENCY_REVIEW": 400}
APP_SCOPE_CATALOG = {"ISSUES_READ", "CONTENTS_WRITE", "ACTIONS_ADMIN", "ADMIN_ORG"}
PAT_SCOPES = {"REPO", "WORKFLOW", "PACKAGES", "ADMIN_ORG"}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return iso_out(db.clock)


def actor():
    return getattr(request, "user_id", None) or "system"


def user_login_for(uid):
    u = db.users.get(uid)
    return u["login"] if u else (uid or "system")


def actor_login():
    """actor_login for audit events: user login if entity-backed, else header id."""
    role = getattr(request, "user_role", None)
    uid = getattr(request, "user_id", None)
    if role == "UserAccount":
        return user_login_for(uid)
    return uid or "system"


# ---------- auth ----------

def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-ID header missing or malformed")
    if not role or not isinstance(role, str) or not role.strip():
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-Role header missing or malformed")
    if role not in VALID_ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-Role header malformed")
    request.user_id = uid.strip()
    request.user_role = role.strip()


def require_roles(*roles):
    if request.user_role not in roles:
        fail("ERR_INSUFFICIENT_PERMISSIONS", "Role not permitted for this endpoint")


# ---------- body parsing ----------

def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", f"field {name} must be a non-empty string")
    return v.strip()


def req_int(data, name, minimum=None, maximum=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", f"field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", f"field {name} below minimum {minimum}")
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", f"field {name} above maximum {maximum}")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", f"field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, name, allowed, default):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def opt_str_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default) if default else []
    v = data[name]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        fail("ERR_INVALID_REQUEST", f"field {name} must be a list of strings")
    return list(v)


def stamp_new(entity):
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------- lookups ----------

def get_enterprise(eid):
    e = db.enterprises.get(eid)
    if not e:
        fail("ERR_ENTERPRISE_NOT_FOUND", "enterprise not found")
    return e


def get_org(oid):
    o = db.organizations.get(oid)
    if not o:
        fail("ERR_ORG_NOT_FOUND", "organization not found")
    return o


def get_user(uid):
    u = db.users.get(uid)
    if not u:
        fail("ERR_USER_NOT_FOUND", "user not found")
    return u


def get_team(tid):
    t = db.teams.get(tid)
    if not t:
        fail("ERR_TEAM_NOT_FOUND", "team not found")
    return t


def get_repo(rid):
    r = db.repositories.get(rid)
    if not r:
        fail("ERR_REPO_NOT_FOUND", "repository not found")
    return r


def get_runner(rid):
    r = db.runners.get(rid)
    if not r:
        fail("ERR_RUNNER_NOT_FOUND", "runner not found")
    return r


def get_run(rid):
    r = db.workflow_runs.get(rid)
    if not r:
        fail("ERR_RUN_NOT_FOUND", "workflow run not found")
    return r


def get_artifact(aid):
    a = db.artifacts.get(aid)
    if not a:
        fail("ERR_ARTIFACT_NOT_FOUND", "artifact not found")
    return a


def get_entitlement(eid):
    e = db.entitlements.get(eid)
    if not e:
        fail("ERR_ENTITLEMENT_NOT_FOUND", "entitlement not found")
    return e


def get_token(tid):
    t = db.tokens.get(tid)
    if not t:
        fail("ERR_TOKEN_NOT_FOUND", "token not found")
    return t


def get_app_install(iid):
    a = db.app_installations.get(iid)
    if not a:
        fail("ERR_APP_INSTALLATION_NOT_FOUND", "app installation not found")
    return a


def get_collab(cid):
    c = db.collaborators.get(cid)
    if not c:
        fail("ERR_COLLABORATOR_NOT_FOUND", "collaborator not found")
    return c


def org_of(entity):
    return db.organizations[entity["organization_id"]]


def enterprise_of_org(org):
    return db.enterprises[org["enterprise_id"]]


def require_org_active(org):
    if org["status"] != "ACTIVE":
        fail("ERR_ORG_NOT_ACTIVE", "organization must be ACTIVE")


# ---------- audit ----------

def emit_audit(enterprise, action, actor_login=None):
    ev = {
        "id": new_id(),
        "enterprise_id": enterprise["id"],
        "action": action,
        "actor_login": actor_login if actor_login is not None else actor_login_fn(),
        "streamed": enterprise["audit_log_stream_status"] == "STREAMING",
        "created_at": now_iso(),
    }
    db.audit_events[ev["id"]] = ev
    return ev


def actor_login_fn():
    return actor_login()


# ---------- seat / committer logic ----------

def org_ids_of_enterprise(enterprise_id):
    return {o["id"] for o in db.organizations.values()
            if o["enterprise_id"] == enterprise_id}


def user_has_active_commit(user_id, org_ids, clock):
    """(a) active committer within trailing 90-day window ending at clock."""
    window_start = clock - timedelta(days=90)
    for ce in db.commit_events.values():
        if ce["author_user_id"] != user_id:
            continue
        if ce["organization_id"] not in org_ids:
            continue
        ct = parse_iso(ce["committed_at"])
        if window_start <= ct <= clock:
            return True
    return False


def user_has_membership(user_id, org_ids):
    for m in db.memberships.values():
        if m["user_id"] != user_id:
            continue
        team = db.teams.get(m["team_id"])
        if team and team["organization_id"] in org_ids:
            return True
    return False


def user_has_accepted_collab(user_id, org_ids):
    for c in db.collaborators.values():
        if c["user_id"] == user_id and c["status"] == "ACCEPTED" \
                and c["organization_id"] in org_ids:
            return True
    return False


def user_holds_seat(user_id, enterprise_id):
    org_ids = org_ids_of_enterprise(enterprise_id)
    return (user_has_active_commit(user_id, org_ids, db.clock)
            or user_has_membership(user_id, org_ids)
            or user_has_accepted_collab(user_id, org_ids))


def recompute_seat_fields(ent):
    ent["used_seats"] = sum(
        1 for u in db.users.values()
        if u.get("seat_held_enterprise_id") == ent["id"])
    ent["available_seats"] = ent["purchased_seats"] - ent["used_seats"]


def consume_seat(ent, user, reason_action=None):
    """Consume a seat for user on enterprise ent if user holds none."""
    if user.get("seat_held_enterprise_id"):
        return False
    if ent["available_seats"] <= 0:
        fail("ERR_NO_SEATS_AVAILABLE", "no seats available on enterprise")
    user["seat_held_enterprise_id"] = ent["id"]
    touch(user)
    recompute_seat_fields(ent)
    touch(ent)
    if reason_action:
        emit_audit(ent, reason_action)
    return True


def reclaim_seat(ent, user, reason_action=None):
    if user.get("seat_held_enterprise_id") == ent["id"]:
        user["seat_held_enterprise_id"] = None
        touch(user)
        recompute_seat_fields(ent)
        touch(ent)
        if reason_action:
            emit_audit(ent, reason_action)
        return True
    return False


def recompute_active_committer(user):
    """Recompute is_active_committer across ALL enterprises' orgs (global window)."""
    window_start = db.clock - timedelta(days=90)
    active = False
    for ce in db.commit_events.values():
        if ce["author_user_id"] != user["id"]:
            continue
        ct = parse_iso(ce["committed_at"])
        if window_start <= ct <= db.clock:
            active = True
            break
    if user["is_active_committer"] != active:
        user["is_active_committer"] = active
        touch(user)


def storage_add(org, size_mb):
    org["_storage_mb"] = org.get("_storage_mb", 0) + size_mb
    org["consumed_storage_gb"] = round_storage(org["_storage_mb"] / 1024.0)


def storage_remove(org, size_mb):
    org["_storage_mb"] = max(0, org.get("_storage_mb", 0) - size_mb)
    org["consumed_storage_gb"] = round_storage(org["_storage_mb"] / 1024.0)


def round_storage(gb):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(gb)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---------- lazy expiry ----------

def sweep_collaborator(c):
    if c["status"] == "INVITED" and db.clock >= parse_iso(c["invite_expires_at"]):
        c["status"] = "EXPIRED"
        touch(c)


def sweep_artifact(a):
    if a["status"] == "RETAINED" and db.clock >= parse_iso(a["expires_at"]):
        a["status"] = "EXPIRED"
        touch(a)
        org = db.organizations.get(a["organization_id"])
        if org:
            storage_remove(org, a["size_mb"])
            touch(org)


def sweep_all():
    for c in db.collaborators.values():
        sweep_collaborator(c)
    for a in db.artifacts.values():
        sweep_artifact(a)


# ---------- serializers ----------

def ser_enterprise(e):
    return {
        "id": e["id"], "name": e["name"],
        "purchased_seats": e["purchased_seats"],
        "used_seats": e["used_seats"],
        "available_seats": e["available_seats"],
        "sso_enforcement": e["sso_enforcement"],
        "pat_policy": e["pat_policy"],
        "audit_log_stream_status": e["audit_log_stream_status"],
        "billing_cycle_anchor_day": e["billing_cycle_anchor_day"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_org(o):
    return {
        "id": o["id"], "enterprise_id": o["enterprise_id"],
        "login": o["login"], "plan_tier": o["plan_tier"],
        "included_actions_minutes": o["included_actions_minutes"],
        "included_storage_gb": o["included_storage_gb"],
        "consumed_actions_minutes": o["consumed_actions_minutes"],
        "consumed_storage_gb": o["consumed_storage_gb"],
        "outside_collaborator_limit": o["outside_collaborator_limit"],
        "retention_freeze_windows": o["retention_freeze_windows"],
        "status": o["status"],
        "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_user(u):
    return {
        "id": u["id"], "login": u["login"], "email": u["email"],
        "is_active_committer": u["is_active_committer"],
        "seat_held_enterprise_id": u["seat_held_enterprise_id"],
        "status": u["status"],
        "created_at": u["created_at"], "updated_at": u["updated_at"],
        "version": u["version"],
    }


def ser_commit_event(ce):
    return {
        "id": ce["id"], "author_user_id": ce["author_user_id"],
        "organization_id": ce["organization_id"],
        "committed_at": ce["committed_at"],
        "created_at": ce["created_at"],
    }


def ser_team(t):
    return {
        "id": t["id"], "organization_id": t["organization_id"],
        "name": t["name"], "parent_team_id": t["parent_team_id"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_membership(m):
    return {
        "id": m["id"], "team_id": m["team_id"],
        "user_id": m["user_id"], "role": m["role"],
        "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_repo(r):
    return {
        "id": r["id"], "organization_id": r["organization_id"],
        "name": r["name"], "visibility": r["visibility"],
        "advanced_security_enabled": r["advanced_security_enabled"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_collab(c):
    return {
        "id": c["id"], "organization_id": c["organization_id"],
        "user_id": c["user_id"], "repository_id": c["repository_id"],
        "invite_expires_at": c["invite_expires_at"],
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_runner(r):
    return {
        "id": r["id"], "organization_id": r["organization_id"],
        "name": r["name"], "os_type": r["os_type"],
        "labels": r["labels"],
        "allowed_on_public_repos": r["allowed_on_public_repos"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_run(r):
    return {
        "id": r["id"], "repository_id": r["repository_id"],
        "organization_id": r["organization_id"],
        "runner_id": r["runner_id"], "runner_kind": r["runner_kind"],
        "os_type": r["os_type"],
        "requested_minutes": r["requested_minutes"],
        "billed_minutes": r["billed_minutes"],
        "overage_cost_cents": r["overage_cost_cents"],
        "execution_status": r["execution_status"],
        "billing_status": r["billing_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_artifact(a):
    return {
        "id": a["id"], "repository_id": a["repository_id"],
        "organization_id": a["organization_id"],
        "name": a["name"], "size_mb": a["size_mb"],
        "retention_days": a["retention_days"],
        "expires_at": a["expires_at"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_entitlement(e):
    return {
        "id": e["id"], "organization_id": e["organization_id"],
        "repository_id": e["repository_id"], "product": e["product"],
        "committer_count": e["committer_count"],
        "monthly_price_cents": e["monthly_price_cents"],
        "status": e["status"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_token(t):
    return {
        "id": t["id"], "user_id": t["user_id"],
        "enterprise_id": t["enterprise_id"], "scopes": t["scopes"],
        "status": t["status"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_audit_event(ev):
    return {
        "id": ev["id"], "enterprise_id": ev["enterprise_id"],
        "action": ev["action"], "actor_login": ev["actor_login"],
        "streamed": ev["streamed"], "created_at": ev["created_at"],
    }


def ser_app_install(a):
    return {
        "id": a["id"], "organization_id": a["organization_id"],
        "app_slug": a["app_slug"],
        "permission_scopes": a["permission_scopes"],
        "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ---------- workflow run billing ----------

def meter_run(run):
    """START transition: compute billed_minutes, add to org consumed."""
    if run["runner_kind"] == "SELF_HOSTED":
        billed = 0
    else:
        import math
        billed = math.ceil(run["requested_minutes"] * OS_MULTIPLIER[run["os_type"]])
    run["billed_minutes"] = billed
    run["_consumed_before"] = None
    org = db.organizations[run["organization_id"]]
    run["_consumed_before"] = org["consumed_actions_minutes"]
    org["consumed_actions_minutes"] += billed
    touch(org)


def settle_run(run):
    """COMPLETE/FAIL (or RUNNING->CANCELLED): allowance waterfall."""
    if run["billing_status"] != "METERED":
        return
    org = db.organizations[run["organization_id"]]
    billed = run["billed_minutes"]
    before = run.get("_consumed_before")
    if before is None:
        before = max(0, org["consumed_actions_minutes"] - billed)
    remaining = max(0, org["included_actions_minutes"] - before)
    applied = min(remaining, billed)
    overage = billed - applied
    if overage == 0:
        run["billing_status"] = "ALLOWANCE_APPLIED"
        run["overage_cost_cents"] = 0
    else:
        import math
        run["billing_status"] = "BILLED"
        run["overage_cost_cents"] = math.ceil(
            overage * OVERAGE_CENTS_PER_MIN[run["os_type"]])


def refund_queued_run(run):
    """QUEUED -> CANCELLED: refund metered minutes (0 for never-started runs)."""
    org = db.organizations[run["organization_id"]]
    if run["billing_status"] in ("METERED", "ALLOWANCE_APPLIED"):
        org["consumed_actions_minutes"] -= run["billed_minutes"]
        if org["consumed_actions_minutes"] < 0:
            org["consumed_actions_minutes"] = 0
        run["billing_status"] = "REFUNDED"
        touch(org)


def cancel_run_cascade(run):
    """Cascade cancel (org suspend / repo archive): QUEUED -> CANCELLED + refund."""
    if run["execution_status"] == "QUEUED":
        refund_queued_run(run)
        run["execution_status"] = "CANCELLED"
        touch(run)


def refresh_repo_security_flag(repo):
    flag = any(
        e["repository_id"] == repo["id"] and e["status"] == "ACTIVE"
        for e in db.entitlements.values())
    repo["advanced_security_enabled"] = flag
