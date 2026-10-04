"""Flask entry point: route registration, validation ordering, and all endpoints."""
import os
from datetime import timedelta

from flask import Flask, request

from helpers import (
    ApiError, success_object, error_response, get_body, require_roles,
    paginate, pagination_params, success_list, parse_iso, iso_now, fmt_ts,
    strip_internal,
)
from store import STATE, LOCK
import domain as D

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body, status = error_response(err)
    return body, status


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err)
    import traceback
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


def _present(obj):
    return strip_internal(dict(obj))


# ===========================================================================
# logical clock
# ===========================================================================

@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformOperator")
    body = get_body()
    to = body.get("to_iso8601")
    if not to:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is required")
    with LOCK:
        STATE["clock"] = parse_iso(to)
        D.fire_due_transitions()
        current = fmt_ts(STATE["clock"])
    return success_object({"current_utc": current})


# ===========================================================================
# tenants
# ===========================================================================

TENANT_KINDS = {"PRODUCTION", "SANDBOX", "IMPLEMENTATION"}
SERVICE_TIERS = {"STANDARD", "PREMIUM"}


@app.post("/tenants")
def create_tenant():
    require_roles("PlatformOperator")
    body = get_body()
    name = body.get("tenant_name")
    kind = body.get("tenant_kind")
    slot = body.get("maintenance_slot_utc")
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "tenant_name is required")
    if kind not in TENANT_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "tenant_kind must be PRODUCTION, SANDBOX, or IMPLEMENTATION")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0 or slot > 23:
        raise ApiError("ERR_INVALID_REQUEST", 400, "maintenance_slot_utc must be an integer 0-23")
    tier = body.get("service_level_tier", "STANDARD")
    if tier not in SERVICE_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_level_tier must be STANDARD or PREMIUM")
    auto_apply = body.get("weekly_update_auto_apply", True)
    if not isinstance(auto_apply, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "weekly_update_auto_apply must be boolean")
    refresh_source = body.get("refresh_source_tenant_id")
    if refresh_source is not None:
        src = STATE["tenants"].get(refresh_source)
        if not src:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "refresh_source_tenant_id does not reference an existing tenant")
    with LOCK:
        for t in STATE["tenants"].values():
            if t["tenant_name"] == name:
                raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "tenant_name must be unique across the platform")
        tenant = D.new_entity("tenants")
        tenant.update({
            "tenant_name": name,
            "tenant_kind": kind,
            "service_level_tier": tier,
            "code_version": STATE["code_version"],
            "weekly_update_auto_apply": auto_apply,
            "maintenance_slot_utc": slot,
            "refresh_source_tenant_id": refresh_source if kind == "SANDBOX" else None,
            "handoff_state": "IN_BUILD",
            "adopted_feature_count": 0,
            "active_membership_count": 0,
            "status": "ACTIVE",
            "_weekly_pending": False,
            "_handoff_partner_worker_id": None,
        })
        # bootstrap admin worker (null org unit)
        worker = D.new_entity("workers")
        worker.update({
            "tenant_id": tenant["id"],
            "worker_ref": "BOOTSTRAP-ADMIN",
            "full_name": "Bootstrap Administrator",
            "org_unit_id": None,
            "manager_worker_id": None,
            "hire_date": iso_now(),
            "status": "ACTIVE",
        })
        tenant["bootstrap_admin_worker_id"] = worker["id"]
        return success_object(_present(tenant), 201)


@app.get("/tenants")
def list_tenants():
    require_roles("PlatformOperator", "TenantAdministrator", "ImplementationPartner")
    items = list(STATE["tenants"].values())
    kind = request.args.get("tenant_kind")
    status = request.args.get("status")
    rsrc = request.args.get("refresh_source_tenant_id")
    badm = request.args.get("bootstrap_admin_worker_id")
    if kind:
        items = [t for t in items if t["tenant_kind"] == kind]
    if status:
        items = [t for t in items if t["status"] == status]
    if rsrc:
        items = [t for t in items if t.get("refresh_source_tenant_id") == rsrc]
    if badm:
        items = [t for t in items if t.get("bootstrap_admin_worker_id") == badm]
    return paginate([_present(t) for t in items])


@app.get("/tenants/<tid>")
def get_tenant(tid):
    require_roles("PlatformOperator", "TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    return success_object(_present(t))


@app.put("/tenants/<tid>")
def update_tenant(tid):
    require_roles("TenantAdministrator", "PlatformOperator")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    expected = body.get("expected_tenant_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_tenant_version is required")
    # validate scalar fields first (priority 17 before 18)
    if "maintenance_slot_utc" in body:
        slot = body["maintenance_slot_utc"]
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0 or slot > 23:
            raise ApiError("ERR_INVALID_REQUEST", 400, "maintenance_slot_utc must be an integer 0-23")
    if "service_level_tier" in body and body["service_level_tier"] not in SERVICE_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_level_tier must be STANDARD or PREMIUM")
    if "weekly_update_auto_apply" in body and not isinstance(body["weekly_update_auto_apply"], bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "weekly_update_auto_apply must be boolean")
    if "tenant_name" in body:
        nn = body["tenant_name"]
        if not nn or not isinstance(nn, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "tenant_name must be a non-empty string")
        for other in STATE["tenants"].values():
            if other["id"] != tid and other["tenant_name"] == nn:
                raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "tenant_name must be unique")
    # OCC last (priority 18)
    if expected != t["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_tenant_version does not match current version")
    with LOCK:
        if "tenant_name" in body:
            t["tenant_name"] = body["tenant_name"]
        if "weekly_update_auto_apply" in body:
            t["weekly_update_auto_apply"] = body["weekly_update_auto_apply"]
        if "maintenance_slot_utc" in body:
            t["maintenance_slot_utc"] = body["maintenance_slot_utc"]
        if "service_level_tier" in body:
            t["service_level_tier"] = body["service_level_tier"]
        D.touch(t)
    return success_object(_present(t))


@app.post("/tenants/<tid>/suspend")
def suspend_tenant(tid):
    require_roles("PlatformOperator")
    t = D.get_tenant_or_404(tid)
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Tenant is not ACTIVE")
    for job in STATE["refresh_jobs"].values():
        if (job.get("source_tenant_id") == tid or job.get("target_tenant_id") == tid) \
                and job["status"] in ("PLANNED", "RUNNING"):
            raise ApiError("ERR_REFRESH_IN_FLIGHT", 409, "A refresh job involving this tenant is in flight")
    with LOCK:
        t["status"] = "SUSPENDED"
        for conn in STATE["connectors"].values():
            if conn["tenant_id"] == tid and conn["status"] == "ACTIVE":
                conn["status"] = "SUSPENDED"
                D.touch(conn)
                for run in STATE["runs"].values():
                    if run["connector_id"] == conn["id"] and run["status"] == "QUEUED":
                        run["status"] = "DEAD_LETTERED"
                        D.touch(run)
        D.touch(t)
    return success_object(_present(t))


@app.post("/tenants/<tid>/resume")
def resume_tenant(tid):
    require_roles("PlatformOperator")
    t = D.get_tenant_or_404(tid)
    if t["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Tenant is not SUSPENDED")
    with LOCK:
        t["status"] = "ACTIVE"
        D.touch(t)
    return success_object(_present(t))


@app.post("/tenants/<tid>/retire")
def retire_tenant(tid):
    require_roles("PlatformOperator")
    t = D.get_tenant_or_404(tid)
    if t["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Tenant already RETIRED")
    if t["tenant_kind"] == "PRODUCTION":
        raise ApiError("ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN", 422, "PRODUCTION tenants cannot be retired")
    for inst in STATE["instances"].values():
        if inst["tenant_id"] == tid and inst["status"] == "IN_PROGRESS":
            raise ApiError("ERR_OPEN_TRANSACTIONS_EXIST", 409, "Open transaction instances exist on this tenant")
    with LOCK:
        for conn in STATE["connectors"].values():
            if conn["tenant_id"] == tid and conn["status"] not in ("RETIRED",):
                conn["status"] = "RETIRED"
                D.touch(conn)
        for group in STATE["security_groups"].values():
            if group["tenant_id"] == tid and group["status"] != "DISABLED":
                group["status"] = "DISABLED"
                D.touch(group)
        for m in STATE["memberships"].values():
            g = STATE["security_groups"].get(m["security_group_id"])
            if g and g["tenant_id"] == tid and m["status"] == "ACTIVE":
                m["status"] = "INVALIDATED"
                D.touch(m)
        t["active_membership_count"] = 0
        t["status"] = "RETIRED"
        D.touch(t)
    return success_object(_present(t))


@app.post("/tenants/<tid>/acknowledge-weekly-update")
def acknowledge_weekly(tid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    D.require_tenant_active(t)
    with LOCK:
        if t.get("_weekly_pending") or t["code_version"] != STATE["code_version"]:
            t["code_version"] = STATE["code_version"]
            t["_weekly_pending"] = False
            D.touch(t)
    return success_object(_present(t))


@app.post("/tenants/<tid>/handoff/advance")
def handoff_advance(tid):
    user_id, role = require_roles("ImplementationPartner", "TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    D.require_tenant_active(t)
    if t["tenant_kind"] != "IMPLEMENTATION":
        raise ApiError("ERR_NOT_IMPLEMENTATION_TENANT", 422, "Handoff applies only to IMPLEMENTATION tenants")
    with LOCK:
        if t["handoff_state"] == "IN_BUILD":
            if role != "ImplementationPartner":
                raise ApiError("ERR_UNAUTHORIZED", 403, "IN_BUILD -> HANDOFF_READY requires ImplementationPartner")
            has_active_def = any(
                d["tenant_id"] == tid and d["status"] == "ACTIVE"
                for d in STATE["definitions"].values()
            )
            if not has_active_def:
                raise ApiError("ERR_NO_ACTIVE_BP_DEFINITION", 422, "No ACTIVE business process definition on this tenant")
            t["handoff_state"] = "HANDOFF_READY"
            t["_handoff_partner_worker_id"] = user_id
            D.touch(t)
        elif t["handoff_state"] == "HANDOFF_READY":
            if role != "TenantAdministrator":
                raise ApiError("ERR_UNAUTHORIZED", 403, "HANDOFF_READY -> ACCEPTED requires TenantAdministrator")
            # segregation of duties: acceptor must belong to a different
            # tenant-scoped security group than the partner who advanced it.
            partner_worker = t.get("_handoff_partner_worker_id")
            if partner_worker is not None:
                partner_groups = {
                    m["security_group_id"] for m in STATE["memberships"].values()
                    if m["worker_id"] == partner_worker and m["status"] == "ACTIVE"
                }
                acceptor_groups = {
                    m["security_group_id"] for m in STATE["memberships"].values()
                    if m["worker_id"] == user_id and m["status"] == "ACTIVE"
                }
                if partner_groups & acceptor_groups or user_id == partner_worker:
                    raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                                   "Handoff acceptor must not be the partner who advanced the handoff")
            t["handoff_state"] = "ACCEPTED"
            D.touch(t)
        else:
            raise ApiError("ERR_INVALID_STATE", 409, "Handoff already ACCEPTED")
    return success_object(_present(t))


@app.get("/tenants/<tid>/adoption-health")
def adoption_health(tid):
    require_roles("TenantAdministrator", "PlatformOperator")
    t = D.get_tenant_or_404(tid)
    base = 100
    enrolled_count = 0
    deferred_count = 0
    late_count = 0
    now = STATE["clock"]
    for ad in STATE["feature_adoptions"].values():
        if ad["tenant_id"] != tid:
            continue
        if ad["status"] in ("ENROLLED", "TESTING_PASSED"):
            base -= 5
            enrolled_count += 1
        elif ad["status"] == "DEFERRED":
            base -= 15
            deferred_count += 1
    # late-enrollment penalty on trains currently OPT_IN_OPEN
    for ad in STATE["feature_adoptions"].values():
        if ad["tenant_id"] != tid or ad["status"] != "ENROLLED":
            continue
        train = STATE["release_trains"].get(ad["release_train_id"])
        if not train or train["status"] != "OPT_IN_OPEN":
            continue
        start = parse_iso(train["opt_in_window_start"])
        end = parse_iso(train["opt_in_window_end"])
        window_days = round((end - start).total_seconds() / 86400)
        effective = window_days + (14 if t["service_level_tier"] == "PREMIUM" else 0)
        threshold = start + timedelta(days=effective * 0.75)
        if now > threshold:
            base -= 10
            late_count += 1
    score = max(0, min(100, base))
    return success_object({
        "score": score,
        "enrolled_count": enrolled_count,
        "deferred_count": deferred_count,
        "late_count": late_count,
    })


@app.get("/tenants/<tid>/refreshed-sandboxes")
def refreshed_sandboxes(tid):
    require_roles("PlatformOperator", "TenantAdministrator")
    D.get_tenant_or_404(tid)
    items = [t for t in STATE["tenants"].values()
             if t["tenant_kind"] == "SANDBOX" and t.get("refresh_source_tenant_id") == tid]
    return paginate([_present(t) for t in items])


@app.get("/tenants/<tid>/bootstrap-tenant")
def bootstrap_tenant(tid):
    require_roles("PlatformOperator")
    # tid here is a worker id per PRD: tenant whose bootstrap_admin_worker_id == id
    items = [t for t in STATE["tenants"].values() if t.get("bootstrap_admin_worker_id") == tid]
    return paginate([_present(t) for t in items])


# ===========================================================================
# organization units
# ===========================================================================

UNIT_TYPES = {"COMPANY", "COST_CENTER", "DIVISION", "TEAM"}


def _unit_view(u):
    v = _present(u)
    v["headcount"] = D.direct_headcount(u["id"])
    return v


@app.post("/tenants/<tid>/organization-units")
def create_org_unit(tid):
    require_roles("TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    name = body.get("unit_name")
    utype = body.get("unit_type")
    eff = body.get("effective_date")
    parent_id = body.get("parent_unit_id")
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit_name is required")
    if utype not in UNIT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit_type invalid")
    if not eff:
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_date is required")
    eff_dt = parse_iso(eff)
    parent = None
    if parent_id is not None:
        parent = STATE["organization_units"].get(parent_id)
        if not parent:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "parent_unit_id not found in tenant scope")
        D.check_cross_tenant(parent, tid, "parent unit")
        # date-range rule (priority 14)
        parent_eff = parse_iso(parent["effective_date"]) if isinstance(parent["effective_date"], str) else parent["effective_date"]
        if eff_dt < parent_eff:
            raise ApiError("ERR_INVALID_DATE_RANGE", 422, "child effective_date earlier than parent's")
    # uniqueness among non-INACTIVE units of this tenant (priority 16)
    for u in STATE["organization_units"].values():
        if u["tenant_id"] == tid and u["unit_name"] == name and u["status"] != "INACTIVE":
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "unit_name must be unique per tenant among non-INACTIVE units")
    with LOCK:
        u = D.new_entity("organization_units")
        u.update({
            "tenant_id": tid,
            "parent_unit_id": parent_id,
            "unit_name": name,
            "unit_type": utype,
            "effective_date": eff_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{eff_dt.microsecond // 1000:03d}Z",
            "status": "PROPOSED",
        })
        # activate immediately if clock already at/past effective date and parent OK
        now = STATE["clock"]
        if now >= eff_dt and (parent_id is None or
                              (parent and parent["status"] == "ACTIVE")):
            u["status"] = "ACTIVE"
            D.synthesize_role_derived_for_unit(u)
        return success_object(_unit_view(u), 201)


@app.get("/tenants/<tid>/organization-units")
def list_org_units(tid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [u for u in STATE["organization_units"].values() if u["tenant_id"] == tid]
    status = request.args.get("status")
    parent = request.args.get("parent_unit_id")
    if status:
        items = [u for u in items if u["status"] == status]
    if parent is not None:
        items = [u for u in items if u.get("parent_unit_id") == parent]
    return paginate([_unit_view(u) for u in items])


@app.get("/tenants/<tid>/organization-units/<uid>")
def get_org_unit(tid, uid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator")
    D.get_tenant_or_404(tid)
    u = STATE["organization_units"].get(uid)
    if not u or u["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Organization unit not found")
    return success_object(_unit_view(u))


@app.post("/tenants/<tid>/organization-units/<uid>/deactivate")
def deactivate_org_unit(tid, uid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    u = STATE["organization_units"].get(uid)
    if not u or u["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Organization unit not found")
    D.require_tenant_active(t)
    if u["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Unit is not ACTIVE")
    # no ACTIVE descendants (direct children that are ACTIVE, transitively)
    descendants = D.unit_active_descendants(uid)
    if descendants:
        raise ApiError("ERR_HAS_ACTIVE_CHILDREN", 409, "Unit has ACTIVE descendant units")
    if D.direct_headcount(uid) > 0:
        raise ApiError("ERR_UNIT_NOT_EMPTY", 409, "Unit headcount is not zero")
    with LOCK:
        u["status"] = "INACTIVE"
        D.touch(u)
        # hop 1: invalidate ROLE_DERIVED memberships of ROLE_BASED groups on this unit
        for group in STATE["security_groups"].values():
            if (group["tenant_id"] == tid and group["assignment_mode"] == "ROLE_BASED"
                    and group.get("org_unit_id") == uid):
                for m in D.active_memberships_of_group(group["id"]):
                    if m["membership_source"] == "ROLE_DERIVED":
                        D._invalidate_membership(m)
                # hop 2
                D._maybe_disable_group(group)
    return success_object(_unit_view(u))


# ===========================================================================
# workers
# ===========================================================================

@app.post("/tenants/<tid>/workers")
def create_worker(tid):
    require_roles("TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    ref = body.get("worker_ref")
    name = body.get("full_name")
    org_unit_id = body.get("org_unit_id")
    hire_date = body.get("hire_date")
    manager_id = body.get("manager_worker_id")
    if not ref or not isinstance(ref, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "worker_ref is required")
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "full_name is required")
    if not hire_date:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hire_date is required")
    hire_dt = parse_iso(hire_date)
    if not org_unit_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "org_unit_id is required")
    unit = STATE["organization_units"].get(org_unit_id)
    if not unit:
        raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "org_unit_id not found in tenant scope")
    D.check_cross_tenant(unit, tid, "org unit")
    if manager_id is not None:
        mgr = STATE["workers"].get(manager_id)
        if not mgr:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "manager_worker_id not found in tenant scope")
        D.check_cross_tenant(mgr, tid, "manager worker")
    if unit["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "org unit must be ACTIVE at assignment time")
    for w in STATE["workers"].values():
        if w["tenant_id"] == tid and w["worker_ref"] == ref:
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "worker_ref must be unique per tenant")
    with LOCK:
        w = D.new_entity("workers")
        w.update({
            "tenant_id": tid,
            "worker_ref": ref,
            "full_name": name,
            "org_unit_id": org_unit_id,
            "manager_worker_id": manager_id,
            "hire_date": hire_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{hire_dt.microsecond // 1000:03d}Z",
            "status": "ACTIVE",
        })
        D.synthesize_role_derived_for_worker(w)
        return success_object(_present(w), 201)


@app.get("/tenants/<tid>/workers")
def list_workers(tid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [w for w in STATE["workers"].values() if w["tenant_id"] == tid]
    status = request.args.get("status")
    ou = request.args.get("org_unit_id")
    if status:
        items = [w for w in items if w["status"] == status]
    if ou:
        items = [w for w in items if w.get("org_unit_id") == ou]
    return paginate([_present(w) for w in items])


@app.get("/tenants/<tid>/workers/<wid>")
def get_worker(tid, wid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    w = STATE["workers"].get(wid)
    if not w or w["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Worker not found")
    return success_object(_present(w))


@app.post("/tenants/<tid>/workers/<wid>/terminate")
def terminate_worker(tid, wid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    w = STATE["workers"].get(wid)
    if not w or w["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Worker not found")
    D.require_tenant_active(t)
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Worker is not ACTIVE")
    for other in STATE["workers"].values():
        if (other["tenant_id"] == tid and other.get("manager_worker_id") == wid
                and other["status"] == "ACTIVE"):
            raise ApiError("ERR_HAS_ACTIVE_REPORTS", 409, "Worker has ACTIVE direct reports")
    with LOCK:
        w["status"] = "TERMINATED"
        D.touch(w)
        affected_groups = set()
        for m in STATE["memberships"].values():
            if m["worker_id"] == wid and m["status"] == "ACTIVE":
                group = STATE["security_groups"].get(m["security_group_id"])
                D._invalidate_membership(m)
                if group:
                    affected_groups.add(group["id"])
        for gid in affected_groups:
            group = STATE["security_groups"].get(gid)
            if group and group["assignment_mode"] == "USER_BASED":
                D._maybe_disable_group(group)
        # pending steps whose only remaining eligible approver was this worker escalate
        for inst in STATE["instances"].values():
            if inst["tenant_id"] != tid or inst["status"] != "IN_PROGRESS":
                continue
            step = D.current_step(inst)
            if not step or step["step_kind"] not in ("APPROVAL", "REVIEW"):
                continue
            group = STATE["security_groups"].get(step.get("approver_security_group_id"))
            if not group:
                continue
            remaining = [
                m for m in D.active_memberships_of_group(group["id"])
                if m["worker_id"] != inst["initiator_worker_id"]
                and STATE["workers"].get(m["worker_id"])
                and STATE["workers"][m["worker_id"]]["status"] == "ACTIVE"
            ]
            if not remaining:
                D.escalate_instance(inst, group)
    return success_object(_present(w))


# ===========================================================================
# security groups and memberships
# ===========================================================================

@app.post("/tenants/<tid>/security-groups")
def create_security_group(tid):
    require_roles("TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    name = body.get("group_name")
    mode = body.get("assignment_mode")
    org_unit_id = body.get("org_unit_id")
    min_approvers = body.get("min_approvers", 1)
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "group_name is required")
    if mode not in ("ROLE_BASED", "USER_BASED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "assignment_mode must be ROLE_BASED or USER_BASED")
    if not isinstance(min_approvers, int) or isinstance(min_approvers, bool) or min_approvers < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "min_approvers must be >= 1")
    unit = None
    if mode == "ROLE_BASED":
        if not org_unit_id:
            raise ApiError("ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE", 422,
                           "ROLE_BASED group requires org_unit_id referencing an ACTIVE unit")
        unit = STATE["organization_units"].get(org_unit_id)
        if not unit:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "org_unit_id not found in tenant scope")
        D.check_cross_tenant(unit, tid, "org unit")
        if unit["status"] != "ACTIVE":
            raise ApiError("ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE", 422,
                           "ROLE_BASED group requires an ACTIVE org unit")
    elif org_unit_id is not None:
        unit = STATE["organization_units"].get(org_unit_id)
        if not unit:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "org_unit_id not found in tenant scope")
        D.check_cross_tenant(unit, tid, "org unit")
    for g in STATE["security_groups"].values():
        if g["tenant_id"] == tid and g["group_name"] == name and g["status"] != "DISABLED":
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "group_name must be unique per tenant among non-DISABLED groups")
    with LOCK:
        g = D.new_entity("security_groups")
        g.update({
            "tenant_id": tid,
            "group_name": name,
            "assignment_mode": mode,
            "org_unit_id": org_unit_id,
            "min_approvers": min_approvers,
            "status": "ACTIVE",
        })
        if mode == "ROLE_BASED" and unit:
            covered = {unit["id"]} | set(D.unit_active_descendants(unit["id"]))
            for w in STATE["workers"].values():
                if (w["tenant_id"] == tid and w["status"] == "ACTIVE"
                        and w.get("org_unit_id") in covered):
                    D._add_membership(g, w["id"], "ROLE_DERIVED")
        return success_object(_present(g), 201)


@app.get("/tenants/<tid>/security-groups")
def list_security_groups(tid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [g for g in STATE["security_groups"].values() if g["tenant_id"] == tid]
    status = request.args.get("status")
    mode = request.args.get("assignment_mode")
    if status:
        items = [g for g in items if g["status"] == status]
    if mode:
        items = [g for g in items if g["assignment_mode"] == mode]
    return paginate([_present(g) for g in items])


@app.get("/tenants/<tid>/security-groups/<gid>")
def get_security_group(tid, gid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator")
    D.get_tenant_or_404(tid)
    g = STATE["security_groups"].get(gid)
    if not g or g["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Security group not found")
    return success_object(_present(g))


@app.post("/tenants/<tid>/security-groups/<gid>/disable")
def disable_security_group(tid, gid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    g = STATE["security_groups"].get(gid)
    if not g or g["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Security group not found")
    D.require_tenant_active(t)
    if g["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Group is not ACTIVE")
    for definition in STATE["definitions"].values():
        if definition["tenant_id"] != tid or definition["status"] != "ACTIVE":
            continue
        for step in STATE["steps"].values():
            if (step["definition_id"] == definition["id"] and step["status"] == "ACTIVE"
                    and step.get("approver_security_group_id") == gid):
                raise ApiError("ERR_GROUP_IN_USE", 409,
                               "Group is referenced by an ACTIVE step of an ACTIVE definition")
    with LOCK:
        g["status"] = "DISABLED"
        D.touch(g)
        for m in D.active_memberships_of_group(gid):
            D._invalidate_membership(m)
    return success_object(_present(g))


@app.post("/tenants/<tid>/security-groups/<gid>/memberships")
def create_membership(tid, gid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    g = STATE["security_groups"].get(gid)
    if not g or g["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Security group not found")
    body = get_body()
    D.require_tenant_active(t)
    if g["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Group is not ACTIVE")
    worker_id = body.get("worker_id")
    if not worker_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "worker_id is required")
    w = STATE["workers"].get(worker_id)
    if not w:
        raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "worker_id not found in tenant scope")
    D.check_cross_tenant(w, tid, "worker")
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Worker must be ACTIVE")
    with LOCK:
        m = D._add_membership(g, worker_id, "USER_ASSIGNED")
        return success_object(_present(m), 201)


@app.get("/tenants/<tid>/security-groups/<gid>/memberships")
def list_memberships(tid, gid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    g = STATE["security_groups"].get(gid)
    if not g or g["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Security group not found")
    items = [m for m in STATE["memberships"].values() if m["security_group_id"] == gid]
    status = request.args.get("status")
    worker_id = request.args.get("worker_id")
    if status:
        items = [m for m in items if m["status"] == status]
    if worker_id:
        items = [m for m in items if m["worker_id"] == worker_id]
    return paginate([_present(m) for m in items])


@app.delete("/tenants/<tid>/security-groups/<gid>/memberships/<mid>")
def delete_membership(tid, gid, mid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    g = STATE["security_groups"].get(gid)
    if not g or g["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Security group not found")
    m = STATE["memberships"].get(mid)
    if not m or m["security_group_id"] != gid:
        raise ApiError("ERR_NOT_FOUND", 404, "Membership not found")
    D.require_tenant_active(t)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Membership is not ACTIVE")
    if m["membership_source"] != "USER_ASSIGNED":
        raise ApiError("ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE", 422,
                       "ROLE_DERIVED memberships cannot be removed via this endpoint")
    with LOCK:
        D._invalidate_membership(m)
        D._maybe_disable_group(g)
    return "", 204


# ===========================================================================
# business process definitions and steps
# ===========================================================================

TRANSACTION_TYPES = {"HIRE", "TERMINATION", "EXPENSE", "ORG_CHANGE"}
STEP_KINDS = {"APPROVAL", "REVIEW", "NOTIFICATION"}
INCLUSION_CONDITIONS = {"ALWAYS", "IF_HEADCOUNT_GE_50", "IF_CROSS_UNIT", "IF_AMOUNT_GT_1000"}
PIN_POLICIES = {"PIN_ON_INITIATE", "LATEST"}


@app.post("/tenants/<tid>/business-process-definitions")
def create_definition(tid):
    require_roles("TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    ttype = body.get("transaction_type")
    name = body.get("definition_name")
    if ttype not in TRANSACTION_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "transaction_type invalid")
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "definition_name is required")
    notify_on = body.get("notify_on_initiate", True)
    if not isinstance(notify_on, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "notify_on_initiate must be boolean")
    esc = body.get("escalation_after_hours", 72)
    if not isinstance(esc, int) or isinstance(esc, bool) or esc < 24:
        raise ApiError("ERR_INVALID_REQUEST", 400, "escalation_after_hours must be >= 24")
    pin = body.get("version_pin_policy", "PIN_ON_INITIATE")
    if pin not in PIN_POLICIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "version_pin_policy invalid")
    with LOCK:
        d = D.new_entity("definitions")
        d.update({
            "tenant_id": tid,
            "transaction_type": ttype,
            "definition_name": name,
            "notify_on_initiate": notify_on,
            "escalation_after_hours": esc,
            "version_pin_policy": pin,
            "status": "DRAFT",
        })
        return success_object(_present(d), 201)


@app.get("/tenants/<tid>/business-process-definitions")
def list_definitions(tid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [d for d in STATE["definitions"].values() if d["tenant_id"] == tid]
    ttype = request.args.get("transaction_type")
    status = request.args.get("status")
    if ttype:
        items = [d for d in items if d["transaction_type"] == ttype]
    if status:
        items = [d for d in items if d["status"] == status]
    return paginate([_present(d) for d in items])


@app.get("/tenants/<tid>/business-process-definitions/<did>")
def get_definition(tid, did):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    d = STATE["definitions"].get(did)
    if not d or d["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Definition not found")
    return success_object(_present(d))


@app.post("/tenants/<tid>/business-process-definitions/<did>/steps")
def create_step(tid, did):
    require_roles("TenantAdministrator", "ImplementationPartner")
    t = D.get_tenant_or_404(tid)
    d = STATE["definitions"].get(did)
    if not d or d["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Definition not found")
    body = get_body()
    D.require_tenant_active(t)
    if d["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Steps may only be added to a DRAFT definition")
    step_order = body.get("step_order")
    step_kind = body.get("step_kind")
    group_id = body.get("approver_security_group_id")
    condition = body.get("inclusion_condition", "ALWAYS")
    return_target = body.get("return_target_step_order")
    if not isinstance(step_order, int) or isinstance(step_order, bool) or step_order < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "step_order must be a positive integer")
    if step_kind not in STEP_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "step_kind invalid")
    if condition not in INCLUSION_CONDITIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "inclusion_condition invalid")
    if step_kind in ("APPROVAL", "REVIEW"):
        if not group_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "approver_security_group_id is required for APPROVAL and REVIEW steps")
        group = STATE["security_groups"].get(group_id)
        if not group:
            raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "approver group not found in tenant scope")
        D.check_cross_tenant(group, tid, "security group")
    if return_target is not None:
        if step_kind != "APPROVAL":
            raise ApiError("ERR_HIERARCHY_VIOLATION", 422, "return_target_step_order only valid on APPROVAL steps")
        if not isinstance(return_target, int) or return_target >= step_order:
            raise ApiError("ERR_HIERARCHY_VIOLATION", 422, "return_target_step_order must be < step_order")
    # contiguity: new step_order must extend the existing sequence by exactly 1
    existing = [s for s in STATE["steps"].values()
                if s["definition_id"] == did and s["status"] == "ACTIVE"]
    expected_next = max([s["step_order"] for s in existing], default=0) + 1
    if step_order != expected_next:
        raise ApiError("ERR_HIERARCHY_VIOLATION", 422, "step_order must be a contiguous 1..N sequence")
    with LOCK:
        s = D.new_entity("steps")
        s.update({
            "definition_id": did,
            "step_order": step_order,
            "step_kind": step_kind,
            "approver_security_group_id": group_id,
            "inclusion_condition": condition,
            "return_target_step_order": return_target,
            "status": "ACTIVE",
        })
        return success_object(_present(s), 201)


@app.get("/tenants/<tid>/business-process-definitions/<did>/steps")
def list_steps(tid, did):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    d = STATE["definitions"].get(did)
    if not d or d["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Definition not found")
    items = [s for s in STATE["steps"].values() if s["definition_id"] == did]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return paginate([_present(s) for s in items])


@app.post("/tenants/<tid>/business-process-definitions/<did>/activate")
def activate_definition(tid, did):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    d = STATE["definitions"].get(did)
    if not d or d["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Definition not found")
    body = get_body()
    D.require_tenant_active(t)
    if d["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Definition is not DRAFT")
    active_steps = D.steps_of_definition(did, status="ACTIVE")
    # priority 15: at least one ACTIVE APPROVAL step
    if not any(s["step_kind"] == "APPROVAL" for s in active_steps):
        raise ApiError("ERR_NO_APPROVAL_STEP", 422, "Definition has no ACTIVE APPROVAL step")
    # group eligibility
    for s in active_steps:
        if s["step_kind"] in ("APPROVAL", "REVIEW"):
            group = STATE["security_groups"].get(s.get("approver_security_group_id"))
            if not group or group["status"] != "ACTIVE":
                raise ApiError("ERR_GROUP_INELIGIBLE", 422, "Approver group is not ACTIVE")
            if len(D.active_memberships_of_group(group["id"])) < group.get("min_approvers", 1):
                raise ApiError("ERR_GROUP_INELIGIBLE", 422, "Approver group below min_approvers")
    # priority 16: no other ACTIVE definition for same (tenant, transaction_type)
    for other in STATE["definitions"].values():
        if (other["tenant_id"] == tid and other["id"] != did
                and other["transaction_type"] == d["transaction_type"]
                and other["status"] == "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409,
                           "An ACTIVE definition already exists for this transaction type")
    # OCC last
    expected = body.get("expected_definition_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_definition_version is required")
    if expected != d["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_definition_version does not match current version")
    with LOCK:
        d["status"] = "ACTIVE"
        D.touch(d)
    return success_object(_present(d))


@app.post("/tenants/<tid>/business-process-definitions/<did>/retire")
def retire_definition(tid, did):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    d = STATE["definitions"].get(did)
    if not d or d["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Definition not found")
    D.require_tenant_active(t)
    if d["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Definition is not ACTIVE")
    for inst in STATE["instances"].values():
        if inst.get("definition_id") == did and inst["status"] == "IN_PROGRESS":
            raise ApiError("ERR_OPEN_TRANSACTIONS_EXIST", 409, "IN_PROGRESS instances exist for this definition")
    with LOCK:
        d["status"] = "RETIRED"
        D.touch(d)
    return success_object(_present(d))


# ===========================================================================
# transaction instances
# ===========================================================================

def _check_step_actor(instance, step, user_id):
    """Shared approver-membership + segregation checks for approve/return.
    Validation order: state (step pending) -> segregation (7) -> membership (9)."""
    if step["step_kind"] not in ("APPROVAL", "REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "Step is not an APPROVAL or REVIEW step")
    # segregation of duties first (priority 7 before 9)
    if user_id == instance["initiator_worker_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422, "Actor is the transaction initiator")
    group = STATE["security_groups"].get(step.get("approver_security_group_id"))
    member = False
    if group:
        for m in D.active_memberships_of_group(group["id"]):
            if m["worker_id"] == user_id:
                member = True
                break
    if not member:
        raise ApiError("ERR_NOT_STEP_APPROVER", 403, "Acting worker lacks ACTIVE membership in the step's approver group")
    # stale-definition guard
    definition = STATE["definitions"].get(instance["definition_id"])
    if definition and definition["version_pin_policy"] == "LATEST":
        live = next(
            (s for s in STATE["steps"].values()
             if s["definition_id"] == definition["id"]
             and s["step_order"] == step["step_order"] and s["status"] == "ACTIVE"),
            None,
        )
        if live is None:
            raise ApiError("ERR_STALE_DEFINITION", 409, "Definition edit removed the pending step")


@app.post("/tenants/<tid>/transaction-instances")
def create_instance(tid):
    user_id, role = require_roles("TenantAdministrator", "ImplementationPartner", "Approver")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    ttype = body.get("transaction_type")
    target_id = body.get("target_org_unit_id")
    amount = body.get("amount", 0)
    if ttype not in TRANSACTION_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "transaction_type invalid")
    if not target_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_org_unit_id is required")
    target = STATE["organization_units"].get(target_id)
    if not target:
        raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, "target_org_unit_id not found in tenant scope")
    D.check_cross_tenant(target, tid, "org unit")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount must be numeric")
    if ttype == "EXPENSE" and amount < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount must be >= 0")
    definition = next(
        (d for d in STATE["definitions"].values()
         if d["tenant_id"] == tid and d["transaction_type"] == ttype and d["status"] == "ACTIVE"),
        None,
    )
    if not definition:
        raise ApiError("ERR_NOT_FOUND", 404, "No ACTIVE definition for this transaction type")
    initiator = STATE["workers"].get(user_id)
    if not initiator or initiator.get("tenant_id") != tid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Acting worker does not belong to this tenant")
    with LOCK:
        inst = D.new_entity("instances")
        pinned = definition["version"] if definition["version_pin_policy"] == "PIN_ON_INITIATE" else None
        inst.update({
            "tenant_id": tid,
            "definition_id": definition["id"],
            "definition_version_pinned": pinned,
            "initiator_worker_id": user_id,
            "source_org_unit_id": initiator.get("org_unit_id"),
            "target_org_unit_id": target_id,
            "amount": amount,
            "current_step_order": 0,
            "escalation_count": 0,
            "status": "IN_PROGRESS",
        })
        if definition.get("notify_on_initiate", True):
            D.notify(tid, user_id, "INITIATED", "TransactionInstance", inst["id"])
        D.advance_instance(inst)
        return success_object(_present(inst), 201)


@app.get("/tenants/<tid>/transaction-instances")
def list_instances(tid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [i for i in STATE["instances"].values() if i["tenant_id"] == tid]
    status = request.args.get("status")
    did = request.args.get("definition_id")
    if status:
        items = [i for i in items if i["status"] == status]
    if did:
        items = [i for i in items if i["definition_id"] == did]
    return paginate([_present(i) for i in items])


@app.get("/tenants/<tid>/transaction-instances/<iid>")
def get_instance(tid, iid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    return success_object(_present(inst))


@app.get("/tenants/<tid>/transaction-instances/<iid>/preview-chain")
def preview_chain(tid, iid):
    require_roles("TenantAdministrator", "ImplementationPartner", "Approver")
    D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    chain = D.effective_chain(inst, "OPTIMISTIC")
    return success_object({
        "chain": [f"{s['step_order']}:{s['step_kind']}" for s in chain],
        "variant": "OPTIMISTIC",
    })


@app.get("/tenants/<tid>/transaction-instances/<iid>/events")
def list_step_events(tid, iid):
    require_roles("TenantAdministrator", "ImplementationPartner", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    items = [e for e in STATE["step_events"].values() if e["instance_id"] == iid]
    action = request.args.get("action")
    if action:
        items = [e for e in items if e["action"] == action]
    return paginate([_present(e) for e in items])


@app.post("/tenants/<tid>/transaction-instances/<iid>/steps/<int:step_order>/approve")
def approve_step(tid, iid, step_order):
    user_id, role = require_roles("Approver")
    t = D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    get_body()
    D.require_tenant_active(t)
    if inst["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Instance is not IN_PROGRESS")
    if inst.get("current_step_order") != step_order:
        raise ApiError("ERR_STEP_NOT_PENDING", 409, "step_order is not the current pending step")
    step = D.current_step(inst)
    if not step:
        raise ApiError("ERR_STEP_NOT_PENDING", 409, "No pending step at this order")
    _check_step_actor(inst, step, user_id)
    with LOCK:
        D.add_step_event(inst, step_order, "APPROVE", user_id, None)
        D.advance_instance(inst)
    return success_object(_present(inst))


@app.post("/tenants/<tid>/transaction-instances/<iid>/steps/<int:step_order>/return")
def return_step(tid, iid, step_order):
    user_id, role = require_roles("Approver")
    t = D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    body = get_body()
    D.require_tenant_active(t)
    if inst["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Instance is not IN_PROGRESS")
    if inst.get("current_step_order") != step_order:
        raise ApiError("ERR_STEP_NOT_PENDING", 409, "step_order is not the current pending step")
    step = D.current_step(inst)
    if not step:
        raise ApiError("ERR_STEP_NOT_PENDING", 409, "No pending step at this order")
    if step["step_kind"] != "APPROVAL" or step.get("return_target_step_order") is None:
        raise ApiError("ERR_STEP_NOT_RETURNABLE", 422, "Step is not a returnable APPROVAL step")
    comment = body.get("comment")
    if not comment:
        raise ApiError("ERR_INVALID_REQUEST", 400, "comment is required for RETURN")
    _check_step_actor(inst, step, user_id)
    with LOCK:
        D.add_step_event(inst, step_order, "RETURN", user_id, comment)
        inst["current_step_order"] = step["return_target_step_order"]
        # re-pending the return target resets that step's pending clock
        D.add_step_event(inst, step["return_target_step_order"], "ADVANCE", None, None)
        D.touch(inst)
        D.notify(tid, inst["initiator_worker_id"], "RETURNED", "TransactionInstance", inst["id"])
    return success_object(_present(inst))


@app.post("/tenants/<tid>/transaction-instances/<iid>/cancel")
def cancel_instance(tid, iid):
    user_id, role = require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    inst = STATE["instances"].get(iid)
    if not inst or inst["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Transaction instance not found")
    D.require_tenant_active(t)
    if inst["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Instance is not IN_PROGRESS")
    if user_id == inst["initiator_worker_id"]:
        admin_count = sum(
            1 for w in STATE["workers"].values()
            if w["tenant_id"] == tid and w["status"] == "ACTIVE"
            and (w["id"] == t.get("bootstrap_admin_worker_id")
                 or any(
                     m["worker_id"] == w["id"] and m["status"] == "ACTIVE"
                     for m in STATE["memberships"].values()
                 ))
        )
        if admin_count < 2:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                           "A sole administrator who is also the initiator cannot cancel their own transaction")
    with LOCK:
        inst["status"] = "CANCELLED"
        inst["current_step_order"] = 0
        D.touch(inst)
    return success_object(_present(inst))


# ===========================================================================
# release trains and feature adoption
# ===========================================================================

@app.post("/release-trains")
def create_release_train():
    require_roles("PlatformOperator")
    body = get_body()
    label = body.get("release_label")
    kind = body.get("release_kind")
    mandatory = body.get("mandatory_date")
    if not label or not isinstance(label, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "release_label is required")
    if kind not in ("WEEKLY_SERVICE", "FEATURE_RELEASE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "release_kind invalid")
    if not mandatory:
        raise ApiError("ERR_INVALID_REQUEST", 400, "mandatory_date is required")
    mandatory_dt = parse_iso(mandatory)
    start = body.get("opt_in_window_start")
    end = body.get("opt_in_window_end")
    if kind == "FEATURE_RELEASE":
        if not start or not end:
            raise ApiError("ERR_INVALID_REQUEST", 400, "FEATURE_RELEASE requires opt_in_window_start and opt_in_window_end")
        start_dt = parse_iso(start)
        end_dt = parse_iso(end)
        if not (start_dt < end_dt < mandatory_dt):
            raise ApiError("ERR_INVALID_DATE_RANGE", 422, "opt_in_window_start < opt_in_window_end < mandatory_date required")
    else:
        start_dt = end_dt = None
    for tr in STATE["release_trains"].values():
        if tr["release_label"] == label:
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409, "release_label must be unique")
    with LOCK:
        tr = D.new_entity("release_trains")
        tr.update({
            "release_label": label,
            "release_kind": kind,
            "opt_in_window_start": fmt_ts(start_dt) if start_dt else None,
            "opt_in_window_end": fmt_ts(end_dt) if end_dt else None,
            "mandatory_date": fmt_ts(mandatory_dt),
            "status": "ANNOUNCED",
        })
        return success_object(_present(tr), 201)


@app.get("/release-trains")
def list_release_trains():
    require_roles("PlatformOperator", "TenantAdministrator", "ImplementationPartner")
    items = list(STATE["release_trains"].values())
    kind = request.args.get("release_kind")
    status = request.args.get("status")
    if kind:
        items = [t for t in items if t["release_kind"] == kind]
    if status:
        items = [t for t in items if t["status"] == status]
    return paginate([_present(t) for t in items])


@app.get("/release-trains/<rid>")
def get_release_train(rid):
    require_roles("PlatformOperator", "TenantAdministrator", "ImplementationPartner")
    tr = STATE["release_trains"].get(rid)
    if not tr:
        raise ApiError("ERR_NOT_FOUND", 404, "Release train not found")
    return success_object(_present(tr))


@app.post("/release-trains/<rid>/retire")
def retire_release_train(rid):
    require_roles("PlatformOperator")
    tr = STATE["release_trains"].get(rid)
    if not tr:
        raise ApiError("ERR_NOT_FOUND", 404, "Release train not found")
    if tr["status"] != "MANDATORY_LIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Train is not MANDATORY_LIVE")
    successor = any(
        o["release_kind"] == "FEATURE_RELEASE" and o["status"] == "MANDATORY_LIVE"
        and o["_seq"] > tr["_seq"]
        for o in STATE["release_trains"].values()
    )
    if not successor:
        raise ApiError("ERR_NO_SUCCESSOR_TRAIN", 422, "No later FEATURE_RELEASE train in MANDATORY_LIVE")
    with LOCK:
        tr["status"] = "RETIRED"
        D.touch(tr)
    return success_object(_present(tr))


# --- feature adoptions ---

def _require_train_opt_in_open(train):
    if not train:
        raise ApiError("ERR_NOT_FOUND", 404, "Release train not found")
    if train["status"] != "OPT_IN_OPEN":
        raise ApiError("ERR_OPT_IN_WINDOW_CLOSED", 422, "Train is not OPT_IN_OPEN")


@app.post("/tenants/<tid>/feature-adoptions")
def enroll_feature(tid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    train_id = body.get("release_train_id")
    feature_key = body.get("feature_key")
    if not train_id or not feature_key:
        raise ApiError("ERR_INVALID_REQUEST", 400, "release_train_id and feature_key are required")
    train = STATE["release_trains"].get(train_id)
    if not train:
        raise ApiError("ERR_NOT_FOUND", 404, "Release train not found")
    _require_train_opt_in_open(train)
    for ad in STATE["feature_adoptions"].values():
        if (ad["tenant_id"] == tid and ad["release_train_id"] == train_id
                and ad["feature_key"] == feature_key):
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409,
                           "feature_key must be unique per (tenant, train)")
    with LOCK:
        ad = D.new_entity("feature_adoptions")
        ad.update({
            "tenant_id": tid,
            "release_train_id": train_id,
            "feature_key": feature_key,
            "deprecates_feature_key": body.get("deprecates_feature_key"),
            "sandbox_test_evidence_id": None,
            "enrolled_at": iso_now(),
            "status": "ENROLLED",
        })
        return success_object(_present(ad), 201)


@app.get("/tenants/<tid>/feature-adoptions")
def list_feature_adoptions(tid):
    require_roles("TenantAdministrator", "PlatformOperator", "ImplementationPartner")
    D.get_tenant_or_404(tid)
    items = [a for a in STATE["feature_adoptions"].values() if a["tenant_id"] == tid]
    train_id = request.args.get("release_train_id")
    status = request.args.get("status")
    if train_id:
        items = [a for a in items if a["release_train_id"] == train_id]
    if status:
        items = [a for a in items if a["status"] == status]
    return paginate([_present(a) for a in items])


@app.get("/tenants/<tid>/feature-adoptions/<aid>")
def get_feature_adoption(tid, aid):
    require_roles("TenantAdministrator", "PlatformOperator", "ImplementationPartner")
    D.get_tenant_or_404(tid)
    ad = STATE["feature_adoptions"].get(aid)
    if not ad or ad["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Feature adoption not found")
    return success_object(_present(ad))


@app.post("/tenants/<tid>/feature-adoptions/<aid>/record-testing")
def record_testing(tid, aid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    ad = STATE["feature_adoptions"].get(aid)
    if not ad or ad["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Feature adoption not found")
    body = get_body()
    D.require_tenant_active(t)
    if ad["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Adoption is not ENROLLED")
    train = STATE["release_trains"].get(ad["release_train_id"])
    _require_train_opt_in_open(train)
    evidence = body.get("sandbox_test_evidence_id")
    ok = False
    if isinstance(evidence, str) and evidence:
        run = STATE["runs"].get(evidence)
        if run and run["status"] == "SUCCEEDED":
            ev_tenant = STATE["tenants"].get(run["tenant_id"])
            if ev_tenant and ev_tenant["tenant_kind"] == "SANDBOX":
                ok = True
            else:
                ok = False
        else:
            # free-form non-empty evidence string
            ok = True
    if not ok:
        raise ApiError("ERR_TEST_EVIDENCE_MISSING", 422, "sandbox test evidence missing or unresolvable")
    with LOCK:
        ad["sandbox_test_evidence_id"] = evidence
        ad["status"] = "TESTING_PASSED"
        D.touch(ad)
    return success_object(_present(ad))


@app.post("/tenants/<tid>/feature-adoptions/<aid>/adopt")
def adopt_feature(tid, aid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    ad = STATE["feature_adoptions"].get(aid)
    if not ad or ad["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Feature adoption not found")
    D.require_tenant_active(t)
    train = STATE["release_trains"].get(ad["release_train_id"])
    _require_train_opt_in_open(train)
    if ad["status"] != "TESTING_PASSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Adoption is not TESTING_PASSED")
    with LOCK:
        ad["status"] = "ADOPTED"
        D.touch(ad)
        t["adopted_feature_count"] = t.get("adopted_feature_count", 0) + 1
        D.touch(t)
    return success_object(_present(ad))


@app.post("/tenants/<tid>/feature-adoptions/<aid>/defer")
def defer_feature(tid, aid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    ad = STATE["feature_adoptions"].get(aid)
    if not ad or ad["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Feature adoption not found")
    D.require_tenant_active(t)
    train = STATE["release_trains"].get(ad["release_train_id"])
    _require_train_opt_in_open(train)
    if ad["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Adoption is not ENROLLED")
    with LOCK:
        ad["status"] = "DEFERRED"
        D.touch(ad)
    return success_object(_present(ad))


# ===========================================================================
# integration connectors and runs
# ===========================================================================

TRIGGER_MODES = {"SCHEDULED", "EVENT_DRIVEN"}
SUBSCRIBED_EVENTS = {"TRANSACTION_COMPLETED", "MEMBERSHIP_CHANGED", "REFRESH_COMPLETED"}
TRIGGER_SOURCES = {"SCHEDULE", "EVENT", "MANUAL"}


def _valid_hour(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 23


@app.post("/tenants/<tid>/integration-connectors")
def create_connector(tid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    name = body.get("connector_name")
    mode = body.get("trigger_mode")
    if not name or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "connector_name is required")
    if mode not in TRIGGER_MODES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "trigger_mode invalid")
    start = body.get("blackout_window_start_utc")
    end = body.get("blackout_window_end_utc")
    if not _valid_hour(start) or not _valid_hour(end):
        raise ApiError("ERR_INVALID_REQUEST", 400, "blackout window hours must be integers 0-23")
    schedule_cron = body.get("schedule_cron")
    subscribed_event = body.get("subscribed_event")
    if subscribed_event is not None and subscribed_event not in SUBSCRIBED_EVENTS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "subscribed_event invalid")
    for c in STATE["connectors"].values():
        if c["tenant_id"] == tid and c["connector_name"] == name and c["status"] != "RETIRED":
            raise ApiError("ERR_DUPLICATE_ACTIVE_DEFINITION", 409,
                           "connector_name must be unique per tenant among non-RETIRED connectors")
    with LOCK:
        c = D.new_entity("connectors")
        c.update({
            "tenant_id": tid,
            "connector_name": name,
            "trigger_mode": mode,
            "schedule_cron": schedule_cron,
            "subscribed_event": subscribed_event,
            "blackout_window_start_utc": start,
            "blackout_window_end_utc": end,
            "status": "DRAFT",
        })
        return success_object(_present(c), 201)


@app.get("/tenants/<tid>/integration-connectors")
def list_connectors(tid):
    require_roles("IntegrationDeveloper", "TenantAdministrator", "PlatformOperator")
    D.get_tenant_or_404(tid)
    items = [c for c in STATE["connectors"].values() if c["tenant_id"] == tid]
    status = request.args.get("status")
    mode = request.args.get("trigger_mode")
    if status:
        items = [c for c in items if c["status"] == status]
    if mode:
        items = [c for c in items if c["trigger_mode"] == mode]
    return paginate([_present(c) for c in items])


def _get_connector(tid, cid):
    D.get_tenant_or_404(tid)
    c = STATE["connectors"].get(cid)
    if not c or c["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Connector not found")
    return c


@app.get("/tenants/<tid>/integration-connectors/<cid>")
def get_connector(tid, cid):
    require_roles("IntegrationDeveloper", "TenantAdministrator", "PlatformOperator")
    c = _get_connector(tid, cid)
    return success_object(_present(c))


@app.post("/tenants/<tid>/integration-connectors/<cid>/activate")
def activate_connector(tid, cid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    c = STATE["connectors"].get(cid)
    if not c or c["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Connector not found")
    D.require_tenant_active(t)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Connector is not DRAFT")
    if c["trigger_mode"] == "SCHEDULED" and not c.get("schedule_cron"):
        raise ApiError("ERR_INVALID_TRIGGER_CONFIG", 422, "SCHEDULED connector requires schedule_cron")
    if c["trigger_mode"] == "EVENT_DRIVEN" and not c.get("subscribed_event"):
        raise ApiError("ERR_INVALID_TRIGGER_CONFIG", 422, "EVENT_DRIVEN connector requires subscribed_event")
    if c.get("blackout_window_start_utc") == c.get("blackout_window_end_utc"):
        raise ApiError("ERR_INVALID_BLACKOUT_WINDOW", 422, "Blackout window must be non-empty")
    with LOCK:
        c["status"] = "ACTIVE"
        D.touch(c)
    return success_object(_present(c))


@app.post("/tenants/<tid>/integration-connectors/<cid>/suspend")
def suspend_connector(tid, cid):
    require_roles("IntegrationDeveloper")
    c = _get_connector(tid, cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Connector is not ACTIVE")
    with LOCK:
        c["status"] = "SUSPENDED"
        D.touch(c)
        for run in STATE["runs"].values():
            if run["connector_id"] == cid and run["status"] == "QUEUED":
                run["status"] = "DEAD_LETTERED"
                D.touch(run)
    return success_object(_present(c))


@app.post("/tenants/<tid>/integration-connectors/<cid>/resume")
def resume_connector(tid, cid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    c = STATE["connectors"].get(cid)
    if not c or c["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Connector not found")
    D.require_tenant_active(t)
    if c["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Connector is not SUSPENDED")
    with LOCK:
        c["status"] = "ACTIVE"
        D.touch(c)
        D.try_dispatch_queued_runs()
    return success_object(_present(c))


@app.post("/tenants/<tid>/integration-connectors/<cid>/retire")
def retire_connector(tid, cid):
    require_roles("IntegrationDeveloper")
    c = _get_connector(tid, cid)
    if c["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Connector already RETIRED")
    if c["status"] == "ACTIVE":
        for run in STATE["runs"].values():
            if run["connector_id"] == cid and run["status"] in ("QUEUED", "RUNNING"):
                raise ApiError("ERR_RUNS_IN_FLIGHT", 409, "Connector has QUEUED or RUNNING runs")
    with LOCK:
        c["status"] = "RETIRED"
        D.touch(c)
    return success_object(_present(c))


# --- runs ---

@app.post("/tenants/<tid>/integration-connectors/<cid>/runs")
def create_run(tid, cid):
    require_roles("IntegrationDeveloper", "PlatformOperator")
    t = D.get_tenant_or_404(tid)
    c = STATE["connectors"].get(cid)
    if not c or c["tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Connector not found")
    body = get_body()
    D.require_tenant_active(t)
    trigger = body.get("trigger_source")
    if trigger not in TRIGGER_SOURCES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "trigger_source must be SCHEDULE, EVENT, or MANUAL")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Connector is not ACTIVE")
    with LOCK:
        run = D.enqueue_run(c, trigger)
        return success_object(_present(run), 201)


@app.get("/tenants/<tid>/integration-connectors/<cid>/runs")
def list_runs(tid, cid):
    require_roles("IntegrationDeveloper", "TenantAdministrator", "PlatformOperator")
    _get_connector(tid, cid)
    items = [r for r in STATE["runs"].values() if r["connector_id"] == cid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([_present(r) for r in items])


def _get_run(tid, cid, rid):
    _get_connector(tid, cid)
    r = STATE["runs"].get(rid)
    if not r or r["connector_id"] != cid:
        raise ApiError("ERR_NOT_FOUND", 404, "Run not found")
    return r


@app.post("/tenants/<tid>/integration-connectors/<cid>/runs/<rid>/complete")
def complete_run(tid, cid, rid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    r = _get_run(tid, cid, rid)
    body = get_body()
    D.require_tenant_active(t)
    if r["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not RUNNING")
    records = body.get("records_processed")
    if not isinstance(records, int) or isinstance(records, bool) or records < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "records_processed must be an integer >= 0")
    with LOCK:
        r["records_processed"] = r.get("records_processed", 0) + records
        r["status"] = "SUCCEEDED"
        D.touch(r)
    return success_object(_present(r))


@app.post("/tenants/<tid>/integration-connectors/<cid>/runs/<rid>/fail")
def fail_run(tid, cid, rid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    r = _get_run(tid, cid, rid)
    D.require_tenant_active(t)
    if r["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not RUNNING")
    with LOCK:
        r["status"] = "FAILED"
        D.touch(r)
    return success_object(_present(r))


@app.post("/tenants/<tid>/integration-connectors/<cid>/runs/<rid>/retry")
def retry_run(tid, cid, rid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    r = _get_run(tid, cid, rid)
    D.require_tenant_active(t)
    if r["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not FAILED")
    if r["attempt_count"] >= 3:
        raise ApiError("ERR_RETRY_LIMIT_EXCEEDED", 409, "Retry limit of 3 attempts reached")
    with LOCK:
        r["attempt_count"] += 1
        r["status"] = "RUNNING"
        D.touch(r)
    return success_object(_present(r))


@app.post("/tenants/<tid>/integration-connectors/<cid>/runs/<rid>/dead-letter")
def dead_letter_run(tid, cid, rid):
    require_roles("IntegrationDeveloper")
    t = D.get_tenant_or_404(tid)
    r = _get_run(tid, cid, rid)
    D.require_tenant_active(t)
    if r["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not FAILED")
    with LOCK:
        r["status"] = "DEAD_LETTERED"
        D.touch(r)
    return success_object(_present(r))


# ===========================================================================
# tenant refresh jobs
# ===========================================================================

@app.post("/tenants/<tid>/refresh-jobs")
def create_refresh_job(tid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    body = get_body()
    D.require_tenant_active(t)
    source_id = body.get("source_tenant_id")
    scheduled_at = body.get("scheduled_at")
    include_workers = body.get("include_workers", False)
    migration_mode = body.get("migration_mode", "FULL_COPY")
    if not source_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "source_tenant_id is required")
    if not scheduled_at:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_at is required")
    sched_dt = parse_iso(scheduled_at)
    if not isinstance(include_workers, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "include_workers must be boolean")
    if migration_mode not in ("FULL_COPY", "DELTA_ONLY"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "migration_mode invalid")
    source = STATE["tenants"].get(source_id)
    if not source:
        raise ApiError("ERR_NOT_FOUND", 404, "Source tenant not found")
    # production-tenant protections (priority 8)
    if t["tenant_kind"] != "SANDBOX" or source["tenant_kind"] != "PRODUCTION":
        raise ApiError("ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN", 422,
                       "Refresh targets must be SANDBOX and sources PRODUCTION")
    # scheduling (priority 13): must be in target maintenance hour
    if sched_dt.hour != t["maintenance_slot_utc"]:
        raise ApiError("ERR_SCHEDULE_CONFLICT", 422, "scheduled_at must fall in the target tenant's maintenance hour")
    with LOCK:
        job = D.new_entity("refresh_jobs")
        job.update({
            "tenant_id": tid,
            "source_tenant_id": source_id,
            "target_tenant_id": tid,
            "include_workers": include_workers,
            "migration_mode": migration_mode,
            "config_drift_score": D.provisional_drift(source_id, tid),
            "scheduled_at": fmt_ts(sched_dt),
            "status": "PLANNED",
        })
        return success_object(_present(job), 201)


@app.get("/tenants/<tid>/refresh-jobs")
def list_refresh_jobs(tid):
    require_roles("TenantAdministrator", "PlatformOperator")
    D.get_tenant_or_404(tid)
    items = [j for j in STATE["refresh_jobs"].values() if j["target_tenant_id"] == tid]
    status = request.args.get("status")
    if status:
        items = [j for j in items if j["status"] == status]
    return paginate([_present(j) for j in items])


@app.get("/tenants/<tid>/refresh-jobs/<jid>")
def get_refresh_job(tid, jid):
    require_roles("TenantAdministrator", "PlatformOperator")
    D.get_tenant_or_404(tid)
    j = STATE["refresh_jobs"].get(jid)
    if not j or j["target_tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Refresh job not found")
    return success_object(_present(j))


@app.post("/tenants/<tid>/refresh-jobs/<jid>/start")
def start_refresh_job(tid, jid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    j = STATE["refresh_jobs"].get(jid)
    if not j or j["target_tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Refresh job not found")
    D.require_tenant_active(t)
    if j["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Refresh job is not PLANNED")
    if STATE["clock"] < parse_iso(j["scheduled_at"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Logical clock has not reached scheduled_at")
    source = STATE["tenants"].get(j["source_tenant_id"])
    if not source or source["status"] != "ACTIVE":
        raise ApiError("ERR_TENANT_NOT_ACTIVE", 409, "Source tenant is not ACTIVE")
    with LOCK:
        j["status"] = "RUNNING"
        D.touch(j)
    return success_object(_present(j))


@app.post("/tenants/<tid>/refresh-jobs/<jid>/complete")
def complete_refresh_job(tid, jid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    j = STATE["refresh_jobs"].get(jid)
    if not j or j["target_tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Refresh job not found")
    D.require_tenant_active(t)
    if j["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Refresh job is not RUNNING")
    if parse_iso(j["scheduled_at"]).hour != t["maintenance_slot_utc"]:
        raise ApiError("ERR_SCHEDULE_CONFLICT", 422, "Refresh must execute in the maintenance hour")
    with LOCK:
        # prior completed refresh timestamp for DELTA_ONLY
        prior = [
            o for o in STATE["refresh_jobs"].values()
            if o["target_tenant_id"] == tid and o["source_tenant_id"] == j["source_tenant_id"]
            and o["status"] == "COMPLETED" and o["id"] != jid
        ]
        last_completed = max((o["_updated_dt"] for o in prior), default=None)
        # apply configuration: FULL_COPY replaces; DELTA_ONLY filters
        src_defs = [d for d in STATE["definitions"].values()
                    if d["tenant_id"] == j["source_tenant_id"] and d["status"] == "ACTIVE"]
        src_groups = [g for g in STATE["security_groups"].values()
                      if g["tenant_id"] == j["source_tenant_id"] and g["status"] == "ACTIVE"]
        if j["migration_mode"] == "DELTA_ONLY" and last_completed is not None:
            src_defs = [d for d in src_defs if d.get("_updated_dt") and d["_updated_dt"] > last_completed]
            src_groups = [g for g in src_groups if g.get("_updated_dt") and g["_updated_dt"] > last_completed]
        if j["migration_mode"] == "FULL_COPY":
            # retire existing target config, then clone
            for d in [d for d in STATE["definitions"].values()
                      if d["tenant_id"] == tid and d["status"] != "RETIRED"]:
                d["status"] = "RETIRED"
                D.touch(d)
            for g in [g for g in STATE["security_groups"].values()
                      if g["tenant_id"] == tid and g["status"] != "DISABLED"]:
                g["status"] = "DISABLED"
                D.touch(g)
        def_map = {}
        for sd in src_defs:
            nd = D.new_entity("definitions")
            nd.update({
                "tenant_id": tid,
                "transaction_type": sd["transaction_type"],
                "definition_name": sd["definition_name"],
                "notify_on_initiate": sd["notify_on_initiate"],
                "escalation_after_hours": sd["escalation_after_hours"],
                "version_pin_policy": sd["version_pin_policy"],
                "status": "ACTIVE",
            })
            def_map[sd["id"]] = nd["id"]
            for ss in D.steps_of_definition(sd["id"], status="ACTIVE"):
                ns = D.new_entity("steps")
                ns.update({
                    "definition_id": nd["id"],
                    "step_order": ss["step_order"],
                    "step_kind": ss["step_kind"],
                    "approver_security_group_id": None,
                    "inclusion_condition": ss["inclusion_condition"],
                    "return_target_step_order": ss.get("return_target_step_order"),
                    "status": "ACTIVE",
                })
        group_map = {}
        for sg in src_groups:
            ng = D.new_entity("security_groups")
            ng.update({
                "tenant_id": tid,
                "group_name": sg["group_name"],
                "assignment_mode": sg["assignment_mode"],
                "org_unit_id": None,
                "min_approvers": sg["min_approvers"],
                "status": "ACTIVE",
            })
            group_map[sg["id"]] = ng["id"]
        # rebind copied steps to copied groups
        for sd in src_defs:
            for ss in D.steps_of_definition(sd["id"], status="ACTIVE"):
                if ss.get("approver_security_group_id") in group_map:
                    for ns2 in STATE["steps"].values():
                        if (ns2["definition_id"] == def_map[sd["id"]]
                                and ns2["step_order"] == ss["step_order"]):
                            ns2["approver_security_group_id"] = group_map[ss["approver_security_group_id"]]
        if j["include_workers"]:
            for w in [w for w in STATE["workers"].values()
                      if w["tenant_id"] == j["source_tenant_id"] and w["status"] == "ACTIVE"]:
                nw = D.new_entity("workers")
                nw.update({
                    "tenant_id": tid,
                    "worker_ref": w["worker_ref"] + "-REFRESH-" + j["id"][:8],
                    "full_name": w["full_name"],
                    "org_unit_id": None,
                    "manager_worker_id": None,
                    "hire_date": w["hire_date"],
                    "status": "ACTIVE",
                })
        j["config_drift_score"] = D.final_drift(
            j["source_tenant_id"], tid, j["migration_mode"], j["include_workers"], last_completed
        )
        j["status"] = "COMPLETED"
        D.touch(j)
        # event-driven connectors on target subscribed to REFRESH_COMPLETED
        for conn in STATE["connectors"].values():
            if (conn["tenant_id"] == tid and conn["trigger_mode"] == "EVENT_DRIVEN"
                    and conn.get("subscribed_event") == "REFRESH_COMPLETED"
                    and conn["status"] == "ACTIVE"):
                D.enqueue_run(conn, "EVENT")
        for admin in D._tenant_admin_workers(tid):
            D.notify(tid, admin["id"], "REFRESH_COMPLETED", "TenantRefreshJob", j["id"])
    return success_object(_present(j))


@app.post("/tenants/<tid>/refresh-jobs/<jid>/fail")
def fail_refresh_job(tid, jid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    j = STATE["refresh_jobs"].get(jid)
    if not j or j["target_tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Refresh job not found")
    D.require_tenant_active(t)
    if j["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Refresh job is not RUNNING")
    with LOCK:
        j["status"] = "FAILED"
        D.touch(j)
    return success_object(_present(j))


@app.post("/tenants/<tid>/refresh-jobs/<jid>/cancel")
def cancel_refresh_job(tid, jid):
    require_roles("TenantAdministrator")
    t = D.get_tenant_or_404(tid)
    j = STATE["refresh_jobs"].get(jid)
    if not j or j["target_tenant_id"] != tid:
        raise ApiError("ERR_NOT_FOUND", 404, "Refresh job not found")
    D.require_tenant_active(t)
    if j["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Refresh job is not PLANNED")
    with LOCK:
        j["status"] = "CANCELLED"
        D.touch(j)
    return success_object(_present(j))


# ===========================================================================
# notifications
# ===========================================================================

@app.get("/tenants/<tid>/notifications")
def list_notifications(tid):
    require_roles("TenantAdministrator", "PlatformOperator", "Approver")
    D.get_tenant_or_404(tid)
    items = [n for n in STATE["notifications"].values() if n["tenant_id"] == tid]
    recip = request.args.get("recipient_worker_id")
    kind = request.args.get("notification_kind")
    if recip:
        items = [n for n in items if n["recipient_worker_id"] == recip]
    if kind:
        items = [n for n in items if n["notification_kind"] == kind]
    return paginate([_present(n) for n in items])


# ===========================================================================
# flat reads (cross-cutting query surface)
# ===========================================================================

def _flat_get(store_key, oid, roles, view=None):
    require_roles(*roles)
    obj = STATE[store_key].get(oid)
    if not obj:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    v = view or _present
    return success_object(v(obj))


def _flat_list(store_key, roles, filters, view=None):
    require_roles(*roles)
    items = list(STATE[store_key].values())
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            items = [x for x in items if str(x.get(field)) == val]
    v = view or _present
    return paginate([v(x) for x in items])


_FLAT_ROLES = ("PlatformOperator", "TenantAdministrator")


@app.get("/organization-units/<uid>")
def flat_get_unit(uid):
    return _flat_get("organization_units", uid, _FLAT_ROLES, _unit_view)


@app.get("/organization-units")
def flat_list_units():
    return _flat_list("organization_units", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("parent_unit_id", "parent_unit_id"),
                       ("status", "status")], _unit_view)


@app.get("/workers/<wid>")
def flat_get_worker(wid):
    return _flat_get("workers", wid, _FLAT_ROLES)


@app.get("/workers")
def flat_list_workers():
    return _flat_list("workers", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("org_unit_id", "org_unit_id"),
                       ("manager_worker_id", "manager_worker_id"), ("status", "status")])


@app.get("/security-groups/<gid>")
def flat_get_group(gid):
    return _flat_get("security_groups", gid, _FLAT_ROLES)


@app.get("/security-groups")
def flat_list_groups():
    return _flat_list("security_groups", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("org_unit_id", "org_unit_id"),
                       ("status", "status"), ("assignment_mode", "assignment_mode")])


@app.get("/security-group-memberships/<mid>")
def flat_get_membership(mid):
    return _flat_get("memberships", mid, _FLAT_ROLES)


@app.get("/security-group-memberships")
def flat_list_memberships():
    return _flat_list("memberships", _FLAT_ROLES,
                      [("security_group_id", "security_group_id"), ("worker_id", "worker_id"),
                       ("status", "status")])


@app.get("/business-process-definitions/<did>")
def flat_get_definition(did):
    return _flat_get("definitions", did, _FLAT_ROLES)


@app.get("/business-process-definitions")
def flat_list_definitions():
    return _flat_list("definitions", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("transaction_type", "transaction_type"),
                       ("status", "status")])


@app.get("/business-process-steps/<sid>")
def flat_get_step(sid):
    return _flat_get("steps", sid, _FLAT_ROLES)


@app.get("/business-process-steps")
def flat_list_steps():
    return _flat_list("steps", _FLAT_ROLES,
                      [("definition_id", "definition_id"),
                       ("approver_security_group_id", "approver_security_group_id"),
                       ("status", "status")])


@app.get("/transaction-instances/<iid>")
def flat_get_instance(iid):
    return _flat_get("instances", iid, _FLAT_ROLES)


@app.get("/transaction-instances")
def flat_list_instances():
    return _flat_list("instances", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("definition_id", "definition_id"),
                       ("initiator_worker_id", "initiator_worker_id"),
                       ("source_org_unit_id", "source_org_unit_id"),
                       ("target_org_unit_id", "target_org_unit_id"),
                       ("status", "status")])


@app.get("/transaction-step-events/<eid>")
def flat_get_event(eid):
    return _flat_get("step_events", eid, _FLAT_ROLES)


@app.get("/transaction-step-events")
def flat_list_events():
    return _flat_list("step_events", _FLAT_ROLES,
                      [("instance_id", "instance_id"), ("actor_worker_id", "actor_worker_id"),
                       ("action", "action")])


@app.get("/tenant-feature-adoptions/<aid>")
def flat_get_adoption(aid):
    return _flat_get("feature_adoptions", aid, _FLAT_ROLES)


@app.get("/tenant-feature-adoptions")
def flat_list_adoptions():
    return _flat_list("feature_adoptions", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("release_train_id", "release_train_id"),
                       ("status", "status")])


@app.get("/integration-connectors/<cid>")
def flat_get_connector(cid):
    return _flat_get("connectors", cid,
                     ("PlatformOperator", "TenantAdministrator", "IntegrationDeveloper"))


@app.get("/integration-connectors")
def flat_list_connectors():
    return _flat_list("connectors",
                      ("PlatformOperator", "TenantAdministrator", "IntegrationDeveloper"),
                      [("tenant_id", "tenant_id"), ("status", "status"),
                       ("trigger_mode", "trigger_mode")])


@app.get("/integration-runs/<rid>")
def flat_get_run(rid):
    return _flat_get("runs", rid,
                     ("PlatformOperator", "TenantAdministrator", "IntegrationDeveloper"))


@app.get("/integration-runs")
def flat_list_runs():
    return _flat_list("runs",
                      ("PlatformOperator", "TenantAdministrator", "IntegrationDeveloper"),
                      [("connector_id", "connector_id"), ("tenant_id", "tenant_id"),
                       ("status", "status")])


@app.get("/tenant-refresh-jobs/<jid>")
def flat_get_refresh_job(jid):
    return _flat_get("refresh_jobs", jid, _FLAT_ROLES)


@app.get("/tenant-refresh-jobs")
def flat_list_refresh_jobs():
    return _flat_list("refresh_jobs", _FLAT_ROLES,
                      [("target_tenant_id", "target_tenant_id"),
                       ("source_tenant_id", "source_tenant_id"),
                       ("status", "status")])


@app.get("/notifications/<nid>")
def flat_get_notification(nid):
    return _flat_get("notifications", nid, _FLAT_ROLES)


@app.get("/notifications")
def flat_list_notifications():
    return _flat_list("notifications", _FLAT_ROLES,
                      [("tenant_id", "tenant_id"), ("recipient_worker_id", "recipient_worker_id"),
                       ("notification_kind", "notification_kind")])


# ===========================================================================
# reverse-reachability sub-resource reads not already covered
# ===========================================================================

@app.get("/tenants/<tid>/tenant-refresh-jobs")
def tenant_refresh_jobs_sub(tid):
    require_roles("PlatformOperator", "TenantAdministrator")
    D.get_tenant_or_404(tid)
    items = [j for j in STATE["refresh_jobs"].values()
             if j["target_tenant_id"] == tid or j["source_tenant_id"] == tid]
    status = request.args.get("status")
    if status:
        items = [j for j in items if j["status"] == status]
    return paginate([_present(j) for j in items])


@app.get("/workers/<wid>/direct-reports")
def worker_direct_reports(wid):
    require_roles("PlatformOperator", "TenantAdministrator")
    if wid not in STATE["workers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Worker not found")
    items = [w for w in STATE["workers"].values() if w.get("manager_worker_id") == wid]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    return paginate([_present(w) for w in items])


@app.get("/workers/<wid>/notifications")
def worker_notifications(wid):
    require_roles("PlatformOperator", "TenantAdministrator", "Approver")
    if wid not in STATE["workers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Worker not found")
    items = [n for n in STATE["notifications"].values() if n["recipient_worker_id"] == wid]
    kind = request.args.get("notification_kind")
    if kind:
        items = [n for n in items if n["notification_kind"] == kind]
    return paginate([_present(n) for n in items])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
