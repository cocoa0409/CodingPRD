"""Domain logic: entity CRUD helpers, cascades, clock-driven transitions, calculations."""
from datetime import timedelta

from helpers import ApiError, new_id, iso_now, parse_iso, fmt_ts
from store import STATE, LOCK

_seq_counter = [0]


def _next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# ---------------------------------------------------------------------------
# generic entity helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Bump updated_at/version on an entity that carries common fields."""
    entity["updated_at"] = iso_now()
    entity["_updated_dt"] = STATE["clock"]
    if "version" in entity:
        entity["version"] += 1


def new_entity(kind, common_fields=True):
    e = {"id": new_id(), "created_at": iso_now(), "_seq": _next_seq()}
    if common_fields:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
        e["_updated_dt"] = STATE["clock"]
    STATE[kind][e["id"]] = e
    return e


def get_tenant_or_404(tid):
    t = STATE["tenants"].get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", 404, "Tenant not found")
    return t


def get_or_404(kind, oid, message="Resource not found"):
    obj = STATE[kind].get(oid)
    if not obj:
        raise ApiError("ERR_NOT_FOUND", 404, message)
    return obj


def require_tenant_active(tenant):
    if tenant["status"] != "ACTIVE":
        raise ApiError("ERR_TENANT_NOT_ACTIVE", 409, "Tenant is not ACTIVE")


def check_cross_tenant(obj, tid, label="resource"):
    """FK body references must resolve inside the same tenant scope."""
    if obj is None:
        raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, f"Referenced {label} does not exist in tenant scope")
    if obj.get("tenant_id") != tid:
        raise ApiError("ERR_CROSS_TENANT_REFERENCE", 422, f"Referenced {label} belongs to a different tenant")


# ---------------------------------------------------------------------------
# org hierarchy helpers
# ---------------------------------------------------------------------------

def direct_headcount(unit_id):
    return sum(
        1
        for w in STATE["workers"].values()
        if w.get("org_unit_id") == unit_id and w["status"] == "ACTIVE"
    )


def unit_active_descendants(unit_id):
    """All descendant unit ids (any depth) that are ACTIVE, given unit tree."""
    result = []
    stack = [unit_id]
    while stack:
        cur = stack.pop()
        for u in STATE["organization_units"].values():
            if u.get("parent_unit_id") == cur:
                result.append(u["id"])
                stack.append(u["id"])
    return [uid for uid in result if STATE["organization_units"][uid]["status"] == "ACTIVE"]


def subtree_headcount(unit_id):
    total = direct_headcount(unit_id)
    for did in unit_active_descendants(unit_id):
        total += direct_headcount(did)
    return total


def would_create_unit_cycle(unit_id, new_parent_id):
    cur = new_parent_id
    seen = set()
    while cur is not None:
        if cur == unit_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        parent = STATE["organization_units"].get(cur)
        if not parent:
            return False
        cur = parent.get("parent_unit_id")
    return False


def would_create_manager_cycle(worker_id, new_manager_id):
    cur = new_manager_id
    seen = set()
    while cur is not None:
        if cur == worker_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        mgr = STATE["workers"].get(cur)
        if not mgr:
            return False
        cur = mgr.get("manager_worker_id")
    return False


# ---------------------------------------------------------------------------
# security groups / memberships
# ---------------------------------------------------------------------------

def active_memberships_of_group(group_id):
    return [
        m for m in STATE["memberships"].values()
        if m["security_group_id"] == group_id and m["status"] == "ACTIVE"
    ]


def _invalidate_membership(m):
    if m["status"] != "ACTIVE":
        return False
    m["status"] = "INVALIDATED"
    touch(m)
    # decrement tenant counter
    group = STATE["security_groups"].get(m["security_group_id"])
    if group:
        tenant = STATE["tenants"].get(group["tenant_id"])
        if tenant:
            tenant["active_membership_count"] = max(0, tenant.get("active_membership_count", 0) - 1)
            touch(tenant)
    return True


def _add_membership(group, worker_id, source):
    tenant = STATE["tenants"].get(group["tenant_id"])
    # avoid duplicate ACTIVE membership for same worker in same group
    for m in STATE["memberships"].values():
        if (m["security_group_id"] == group["id"] and m["worker_id"] == worker_id
                and m["status"] == "ACTIVE"):
            return m
    m = new_entity("memberships")
    m.update({
        "security_group_id": group["id"],
        "worker_id": worker_id,
        "membership_source": source,
        "status": "ACTIVE",
    })
    if tenant:
        tenant["active_membership_count"] = tenant.get("active_membership_count", 0) + 1
        touch(tenant)
    return m


def synthesize_role_derived_for_unit(unit):
    """When a unit activates: synthesize ROLE_DERIVED memberships for ROLE_BASED
    groups referencing this unit, for ACTIVE workers in this unit or descendant
    ACTIVE units."""
    unit_ids = {unit["id"]} | set(unit_active_descendants(unit["id"]))
    for group in STATE["security_groups"].values():
        if (group["tenant_id"] == unit["tenant_id"]
                and group["assignment_mode"] == "ROLE_BASED"
                and group.get("org_unit_id") == unit["id"]
                and group["status"] == "ACTIVE"):
            for w in STATE["workers"].values():
                if (w["tenant_id"] == unit["tenant_id"] and w["status"] == "ACTIVE"
                        and w.get("org_unit_id") in unit_ids):
                    _add_membership(group, w["id"], "ROLE_DERIVED")


def synthesize_role_derived_for_worker(worker):
    """On worker create: synthesize ROLE_DERIVED memberships for ROLE_BASED groups
    whose org subtree covers the worker's unit."""
    uid = worker.get("org_unit_id")
    if not uid:
        return
    for group in STATE["security_groups"].values():
        if (group["tenant_id"] == worker["tenant_id"]
                and group["assignment_mode"] == "ROLE_BASED"
                and group["status"] == "ACTIVE"
                and group.get("org_unit_id")):
            covered = {group["org_unit_id"]} | set(unit_active_descendants(group["org_unit_id"]))
            if uid in covered:
                _add_membership(group, worker["id"], "ROLE_DERIVED")


def _handle_group_disabled(group):
    """Cascade hop 3 for a group that just became DISABLED."""
    for step in STATE["steps"].values():
        if step.get("approver_security_group_id") != group["id"] or step["status"] != "ACTIVE":
            continue
        definition = STATE["definitions"].get(step["definition_id"])
        if not definition:
            continue
        if definition["status"] == "DRAFT":
            step["status"] = "REMOVED"
            touch(step)
        elif definition["status"] == "ACTIVE":
            definition["_flagged"] = True
            for inst in STATE["instances"].values():
                if (inst.get("definition_id") == definition["id"]
                        and inst["status"] == "IN_PROGRESS"):
                    escalate_instance(inst, group)


def _maybe_disable_group(group):
    if group["status"] != "ACTIVE":
        return
    if len(active_memberships_of_group(group["id"])) < group.get("min_approvers", 1):
        group["status"] = "DISABLED"
        touch(group)
        _handle_group_disabled(group)


def notify(tenant_id, recipient_worker_id, kind, reference_entity, reference_id):
    n = new_entity("notifications", common_fields=False)
    n.update({
        "tenant_id": tenant_id,
        "recipient_worker_id": recipient_worker_id,
        "notification_kind": kind,
        "reference_entity": reference_entity,
        "reference_id": reference_id,
    })
    return n


def add_step_event(instance, step_order, action, actor_worker_id=None, comment=None):
    e = new_entity("step_events", common_fields=False)
    e.update({
        "instance_id": instance["id"],
        "step_order": step_order,
        "action": action,
        "actor_worker_id": actor_worker_id,
        "comment": comment,
        "occurred_at": iso_now(),
        "_occ_dt": STATE["clock"],
    })
    return e


def escalate_instance(instance, group=None):
    add_step_event(instance, instance["current_step_order"], "ESCALATE", None, None)
    instance["escalation_count"] = instance.get("escalation_count", 0) + 1
    touch(instance)
    if group is None:
        step = current_step(instance)
        if step:
            group = STATE["security_groups"].get(step.get("approver_security_group_id"))
    if group:
        for m in active_memberships_of_group(group["id"]):
            notify(instance["tenant_id"], m["worker_id"], "ESCALATED",
                   "TransactionInstance", instance["id"])


# ---------------------------------------------------------------------------
# business process definitions / steps
# ---------------------------------------------------------------------------

def steps_of_definition(definition_id, status="ACTIVE"):
    steps = [s for s in STATE["steps"].values() if s["definition_id"] == definition_id]
    if status:
        steps = [s for s in steps if s["status"] == status]
    return sorted(steps, key=lambda s: s["step_order"])


def current_step(instance):
    order = instance.get("current_step_order", 0)
    if not order:
        return None
    for s in STATE["steps"].values():
        if (s["definition_id"] == instance["definition_id"]
                and s["step_order"] == order):
            return s
    return None


def _condition_holds(step, instance, variant):
    cond = step.get("inclusion_condition", "ALWAYS")
    if cond == "ALWAYS":
        return True
    if cond == "IF_HEADCOUNT_GE_50":
        target = STATE["organization_units"].get(instance.get("target_org_unit_id"))
        if not target:
            return False
        if variant == "OPTIMISTIC":
            hc = direct_headcount(target["id"])
        else:
            hc = subtree_headcount(target["id"])
        return hc >= 50
    if cond == "IF_CROSS_UNIT":
        return instance.get("source_org_unit_id") != instance.get("target_org_unit_id")
    if cond == "IF_AMOUNT_GT_1000":
        return (instance.get("amount") or 0) > 1000
    return True


def effective_chain(instance, variant):
    steps = steps_of_definition(instance["definition_id"], status="ACTIVE")
    out = []
    for s in steps:
        if _condition_holds(s, instance, variant):
            out.append(s)
    return out


def advance_instance(instance):
    """Evaluate next-step chain after an approval or initiation. Skips conditionals,
    auto-passes NOTIFICATION steps, sets current_step_order or completes."""
    steps = steps_of_definition(instance["definition_id"], status="ACTIVE")
    current_order = instance.get("current_step_order", 0)
    for s in steps:
        if s["step_order"] <= current_order:
            continue
        if not _condition_holds(s, instance, "CONSERVATIVE"):
            add_step_event(instance, s["step_order"], "SKIP", None, None)
            continue
        if s["step_kind"] == "NOTIFICATION":
            add_step_event(instance, s["step_order"], "NOTIFY", None, None)
            # notify initiator for notification steps
            notify(instance["tenant_id"], instance["initiator_worker_id"],
                   "STEP_ASSIGNED", "TransactionInstance", instance["id"])
            continue
        # APPROVAL or REVIEW: becomes pending
        instance["current_step_order"] = s["step_order"]
        touch(instance)
        add_step_event(instance, s["step_order"], "ADVANCE", None, None)
        group = STATE["security_groups"].get(s.get("approver_security_group_id"))
        if group:
            for m in active_memberships_of_group(group["id"]):
                notify(instance["tenant_id"], m["worker_id"], "STEP_ASSIGNED",
                       "TransactionInstance", instance["id"])
        return
    # no further pending step -> COMPLETED
    instance["current_step_order"] = 0
    instance["status"] = "COMPLETED"
    touch(instance)
    for conn in STATE["connectors"].values():
        if (conn["tenant_id"] == instance["tenant_id"]
                and conn["trigger_mode"] == "EVENT_DRIVEN"
                and conn.get("subscribed_event") == "TRANSACTION_COMPLETED"
                and conn["status"] == "ACTIVE"):
            enqueue_run(conn, "EVENT")


# ---------------------------------------------------------------------------
# integration runs
# ---------------------------------------------------------------------------

def enqueue_run(connector, trigger_source):
    run = new_entity("runs")
    run.update({
        "connector_id": connector["id"],
        "tenant_id": connector["tenant_id"],
        "trigger_source": trigger_source,
        "attempt_count": 1,
        "records_processed": 0,
        "status": "QUEUED",
    })
    if trigger_source == "MANUAL":
        # manual runs bypass blackout and dispatch immediately
        if connector["status"] == "ACTIVE":
            run["status"] = "RUNNING"
            touch(run)
    return run


def try_dispatch_queued_runs():
    """Dispatcher: QUEUED runs whose connector is ACTIVE and (for SCHEDULE) outside
    the blackout window move to RUNNING."""
    hour = STATE["clock"].hour
    for run in STATE["runs"].values():
        if run["status"] != "QUEUED":
            continue
        conn = STATE["connectors"].get(run["connector_id"])
        if not conn or conn["status"] != "ACTIVE":
            continue
        if run["trigger_source"] == "SCHEDULE":
            start = conn.get("blackout_window_start_utc")
            end = conn.get("blackout_window_end_utc")
            if start is not None and end is not None:
                if start <= end:
                    in_blackout = start <= hour < end
                else:
                    # wrap-around window (e.g. 22 -> 2)
                    in_blackout = hour >= start or hour < end
                if in_blackout:
                    continue
        run["status"] = "RUNNING"
        touch(run)


# ---------------------------------------------------------------------------
# clock-driven system transitions
# ---------------------------------------------------------------------------

def fire_due_transitions():
    """Run all due system transitions after a clock advance. Iterates until stable."""
    now = STATE["clock"]

    # 1. org unit activation
    for unit in list(STATE["organization_units"].values()):
        if unit["status"] != "PROPOSED":
            continue
        eff = parse_iso(unit["effective_date"]) if isinstance(unit["effective_date"], str) else unit["effective_date"]
        if now >= eff:
            parent_id = unit.get("parent_unit_id")
            if parent_id is None or (
                STATE["organization_units"].get(parent_id)
                and STATE["organization_units"][parent_id]["status"] == "ACTIVE"
            ):
                unit["status"] = "ACTIVE"
                touch(unit)
                synthesize_role_derived_for_unit(unit)

    # 2. release trains
    for train in list(STATE["release_trains"].values()):
        if train["status"] == "ANNOUNCED":
            if train["release_kind"] == "WEEKLY_SERVICE":
                train["status"] = "MANDATORY_LIVE"
                touch(train)
                _apply_weekly_train(train)
            elif train["release_kind"] == "FEATURE_RELEASE":
                start = parse_iso(train["opt_in_window_start"])
                if now >= start:
                    train["status"] = "OPT_IN_OPEN"
                    touch(train)
        if train["status"] == "OPT_IN_OPEN" and train["release_kind"] == "FEATURE_RELEASE":
            end = parse_iso(train["opt_in_window_end"])
            # inclusive boundary: enrollments accepted at exactly end; closes after
            if now > end:
                train["status"] = "OPT_IN_CLOSED"
                touch(train)
                _close_opt_in_window(train)
        if train["status"] == "OPT_IN_CLOSED":
            mandatory = parse_iso(train["mandatory_date"])
            if now >= mandatory:
                train["status"] = "MANDATORY_LIVE"
                touch(train)
                _mandatory_cascade(train)

    # 3. escalation sweep
    _escalation_sweep()

    # 4. refresh jobs reaching scheduled_at
    for job in list(STATE["refresh_jobs"].values()):
        if job["status"] != "PLANNED":
            continue
        sched = parse_iso(job["scheduled_at"])
        if now >= sched:
            source = STATE["tenants"].get(job["source_tenant_id"])
            target = STATE["tenants"].get(job["target_tenant_id"])
            if source and target and source["status"] == "ACTIVE" and target["status"] == "ACTIVE":
                job["status"] = "RUNNING"
                touch(job)

    # 5. dispatch queued runs
    try_dispatch_queued_runs()


def _apply_weekly_train(train):
    new_version = train["release_label"]
    STATE["code_version"] = new_version
    for tenant in STATE["tenants"].values():
        if tenant.get("weekly_update_auto_apply", True):
            tenant["code_version"] = new_version
            touch(tenant)
        else:
            tenant["_weekly_pending"] = True


def _close_opt_in_window(train):
    for ad in STATE["feature_adoptions"].values():
        if (ad["release_train_id"] == train["id"] and ad["status"] == "ENROLLED"
                and not ad.get("sandbox_test_evidence_id")):
            ad["status"] = "DEFERRED"
            touch(ad)


def _mandatory_cascade(train):
    # Hop 1: ENROLLED or TESTING_PASSED -> FORCE_ENABLED
    flipped = []
    for ad in list(STATE["feature_adoptions"].values()):
        if ad["release_train_id"] == train["id"] and ad["status"] in ("ENROLLED", "TESTING_PASSED"):
            ad["status"] = "FORCE_ENABLED"
            touch(ad)
            tenant = STATE["tenants"].get(ad["tenant_id"])
            if tenant:
                tenant["adopted_feature_count"] = tenant.get("adopted_feature_count", 0) + 1
                touch(tenant)
            flipped.append(ad)
    # Hop 2: retire deprecated predecessors
    for ad in flipped:
        pred = ad.get("deprecates_feature_key")
        if not pred:
            continue
        for other in STATE["feature_adoptions"].values():
            if (other["tenant_id"] == ad["tenant_id"]
                    and other["feature_key"] == pred
                    and other["status"] in ("ADOPTED", "FORCE_ENABLED")):
                other["status"] = "ROLLED_BACK"
                touch(other)
                tenant = STATE["tenants"].get(ad["tenant_id"])
                if tenant:
                    tenant["adopted_feature_count"] = max(0, tenant.get("adopted_feature_count", 0) - 1)
                    touch(tenant)
                # FORCE_ENABLED notification to tenant admins
                for admin in _tenant_admin_workers(ad["tenant_id"]):
                    notify(ad["tenant_id"], admin["id"], "FORCE_ENABLED",
                           "TenantFeatureAdoption", ad["id"])
    # Hop 3: DEFERRED rows -> FORCE_ENABLED with RETIREMENT_WARNING
    for ad in list(STATE["feature_adoptions"].values()):
        if ad["release_train_id"] == train["id"] and ad["status"] == "DEFERRED":
            ad["status"] = "FORCE_ENABLED"
            touch(ad)
            tenant = STATE["tenants"].get(ad["tenant_id"])
            if tenant:
                tenant["adopted_feature_count"] = tenant.get("adopted_feature_count", 0) + 1
                touch(tenant)
            for admin in _tenant_admin_workers(ad["tenant_id"]):
                notify(ad["tenant_id"], admin["id"], "RETIREMENT_WARNING",
                       "TenantFeatureAdoption", ad["id"])
            # predecessor still retired
            pred = ad.get("deprecates_feature_key")
            if pred:
                for other in STATE["feature_adoptions"].values():
                    if (other["tenant_id"] == ad["tenant_id"]
                            and other["feature_key"] == pred
                            and other["status"] in ("ADOPTED", "FORCE_ENABLED")):
                        other["status"] = "ROLLED_BACK"
                        touch(other)
                        tenant = STATE["tenants"].get(ad["tenant_id"])
                        if tenant:
                            tenant["adopted_feature_count"] = max(0, tenant.get("adopted_feature_count", 0) - 1)
                            touch(tenant)


def _tenant_admin_workers(tenant_id):
    """Workers on the tenant holding an ACTIVE membership in any of the tenant's
    groups; used as the TenantAdministrator notification set. Bootstrap admin is
    always included."""
    tenant = STATE["tenants"].get(tenant_id)
    ids = set()
    if tenant and tenant.get("bootstrap_admin_worker_id"):
        b = STATE["workers"].get(tenant["bootstrap_admin_worker_id"])
        if b:
            ids.add(b["id"])
    for m in STATE["memberships"].values():
        if m["status"] != "ACTIVE":
            continue
        group = STATE["security_groups"].get(m["security_group_id"])
        if group and group["tenant_id"] == tenant_id:
            ids.add(m["worker_id"])
    return [STATE["workers"][i] for i in ids if i in STATE["workers"]]


def _escalation_sweep():
    now = STATE["clock"]
    for inst in list(STATE["instances"].values()):
        if inst["status"] != "IN_PROGRESS" or not inst.get("current_step_order"):
            continue
        definition = STATE["definitions"].get(inst["definition_id"])
        if not definition:
            continue
        # find the ADVANCE event that made the current step pending (latest one)
        advances = [
            e for e in STATE["step_events"].values()
            if e["instance_id"] == inst["id"]
            and e["action"] == "ADVANCE"
            and e["step_order"] == inst["current_step_order"]
        ]
        if not advances:
            continue
        adv = max(advances, key=lambda e: e["_seq"])
        # escalate at most once per pending-step episode: skip if an ESCALATE
        # event already exists after this advance for the same step
        already = any(
            e for e in STATE["step_events"].values()
            if e["instance_id"] == inst["id"]
            and e["action"] == "ESCALATE"
            and e["step_order"] == inst["current_step_order"]
            and e["_seq"] > adv["_seq"]
        )
        if already:
            continue
        start = adv["_occ_dt"]
        hours = definition.get("escalation_after_hours", 72)
        due = start + timedelta(hours=hours)
        # escalate iff logical clock strictly past due (exact tie is not escalated)
        if now > due:
            escalate_instance(inst)


# ---------------------------------------------------------------------------
# refresh: drift score
# ---------------------------------------------------------------------------

def provisional_drift(source_id, target_id):
    drift = 0
    src_defs = [d for d in STATE["definitions"].values()
                if d["tenant_id"] == source_id and d["status"] == "ACTIVE"]
    tgt_defs = [d for d in STATE["definitions"].values()
                if d["tenant_id"] == target_id and d["status"] == "ACTIVE"]
    for sd in src_defs:
        counterpart = next((td for td in tgt_defs if td["transaction_type"] == sd["transaction_type"]), None)
        if counterpart is None:
            drift += 2
        elif sd["version"] > counterpart["version"]:
            drift += 1
    src_groups = [g for g in STATE["security_groups"].values()
                  if g["tenant_id"] == source_id and g["status"] == "ACTIVE"]
    tgt_groups = [g for g in STATE["security_groups"].values()
                  if g["tenant_id"] == target_id and g["status"] != "DISABLED"]
    for sg in src_groups:
        if not any(tg["group_name"] == sg["group_name"] for tg in tgt_groups):
            drift += 1
    return drift


def final_drift(source_id, target_id, migration_mode, include_workers, last_completed_at):
    src_defs = [d for d in STATE["definitions"].values()
                if d["tenant_id"] == source_id and d["status"] == "ACTIVE"]
    src_groups = [g for g in STATE["security_groups"].values()
                  if g["tenant_id"] == source_id and g["status"] == "ACTIVE"]
    if migration_mode == "DELTA_ONLY" and last_completed_at is not None:
        src_defs = [d for d in src_defs if d.get("_updated_dt") and d["_updated_dt"] > last_completed_at]
        src_groups = [g for g in src_groups if g.get("_updated_dt") and g["_updated_dt"] > last_completed_at]
    steps_count = sum(
        1 for d in src_defs for s in STATE["steps"].values()
        if s["definition_id"] == d["id"] and s["status"] == "ACTIVE"
    )
    score = len(src_defs) + steps_count + len(src_groups)
    if include_workers:
        score += 1
    return score
