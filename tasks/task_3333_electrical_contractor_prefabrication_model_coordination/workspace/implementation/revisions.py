"""Design revisions, their cost memos and the rework loop they drive."""

from core import (CLOCK, DB, fail, new_record, num, rhu, to_dt, touch)
from calculations import (component_crafted_hours, revision_cost_impact,
                          revision_equipment_delta, revision_flow_hours,
                          update_project_pipeline, craft_hours_credit,
                          craft_hours_balance, idle_capacity, rack_capacity_ok,
                          rack_value_capacity_check)
from projects import compute_slippage, posture_for_slippage

QUALIFICATION_LENGTH = 40
TERMINAL_REVISION_STATUSES = ("APPROVED", "REJECTED", "SUPERSEDED")

REWORK_TRANSITIONS = {
    ("OPEN", "IN_PROGRESS"): "start",
    ("IN_PROGRESS", "CLOSED"): "close",
    ("OPEN", "CLOSED"): "close_zero",
    ("IN_PROGRESS", "RECUT_DEFERRED"): "scrap",
    ("CLOSED", "IN_PROGRESS"): "reopen",
}


# --------------------------------------------------------------------------
# Impact-key resolution
# --------------------------------------------------------------------------

def resolve_impact_key(key):
    """Resolve a business key to (kind, record) or (None, None)."""
    for line in DB.all("takeoff_lines"):
        if line.get("takeoff_hash") == key:
            return "takeoff_line", line
    for component in DB.all("prefab_components"):
        if component.get("component_code") == key or component.get("assembly_code") == key:
            return "component", component
    for rack in DB.all("racks"):
        if rack.get("rack_code") == key:
            return "rack", rack
    return None, None


def resolve_impact_keys(impact_keys):
    resolved = []
    for key in impact_keys or []:
        kind, record = resolve_impact_key(key)
        if kind is None:
            fail("ERR_AFFECTED_REF_NOT_FOUND")
        resolved.append((key, kind, record))
    return resolved


def commodities_for_impacts(resolved):
    commodities = set()
    for _key, kind, record in resolved:
        if kind == "takeoff_line":
            if record.get("conduit_run_type"):
                commodities.add(record["conduit_run_type"])
        elif kind == "component":
            line = DB.find("takeoff_lines", record.get("takeoff_line_id"))
            if line is not None and line.get("conduit_run_type"):
                commodities.add(line["conduit_run_type"])
            assembly = DB.find("assemblies", record.get("assembly_code"))
            if assembly is not None and assembly.get("is_switchgear"):
                commodities.add("SWITCHGEAR")
        elif kind == "rack":
            for component in DB.all("prefab_components"):
                if component.get("rack_id") == record["id"]:
                    line = DB.find("takeoff_lines", component.get("takeoff_line_id"))
                    if line is not None and line.get("conduit_run_type"):
                        commodities.add(line["conduit_run_type"])
    return commodities


# --------------------------------------------------------------------------
# Revision validation helpers
# --------------------------------------------------------------------------

def _fabricated_content_present(revision):
    codes = revision.get("label_codes") or []
    fabricated_codes = revision.get("fabricated_content_codes") or []
    return any(code in fabricated_codes for code in codes)


def affects_fabricated_content(revision):
    if not _fabricated_content_present(revision):
        return False
    return num(revision.get("label_percentage"), 0.0) > 0


def check_label_codes(revision):
    if _fabricated_content_present(revision):
        percentage = revision.get("label_percentage")
        if percentage is None or num(percentage, 0.0) <= 0:
            fail("ERR_LABEL_CODE_MISSING")


def check_lifecycle(revision):
    replacement = num(revision.get("replacement_lifecycle_percent"), 0.0)
    prior = num(revision.get("prior_lifecycle_percent"), 0.0)
    if replacement < prior:
        fail("ERR_SERVICE_LIFECYCLE_INVALID")


def check_impact_required(revision):
    if not (revision.get("impact_keys") or []):
        fail("ERR_REVISION_IMPACT_REQUIRED")


def check_craft_hours_ceiling(revision):
    tied = num(revision.get("tied_shipment_hours"), 0.0)
    revised = num(revision.get("revised_trade_hours"), 0.0)
    adjusted = num(revision.get("adjusted_flow_hours"), 0.0)
    if tied + revised > adjusted:
        fail("ERR_CRAFT_HOURS_EXCEEDED")


def approved_revision_targets(model_version_id, exclude_revision=None):
    for revision in DB.all("revisions"):
        if revision.get("model_version_id") != model_version_id:
            continue
        if revision.get("status") != "APPROVED":
            continue
        if exclude_revision is not None and revision["id"] == exclude_revision["id"]:
            continue
        return revision
    return None


def check_supersession(model_version, revision=None):
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")
    if model_version.get("status") == "SUPERSEDED":
        fail("ERR_MODEL_SUPERSEDED")
    if approved_revision_targets(model_version["id"], revision) is not None:
        fail("ERR_MODEL_SUPERSEDED")


def check_model_quantities(model_version):
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")
    if num(model_version.get("zone_quantity_total"), 0.0) < 1 or model_version.get("empty_takeoff"):
        fail("ERR_MODEL_QUANTITY_UNRESOLVED")


# --------------------------------------------------------------------------
# Create / re-draft
# --------------------------------------------------------------------------

def create_revision(body):
    existing_id = body.get("revision_id") or body.get("id")
    if existing_id:
        existing = DB.find("revisions", existing_id)
        if existing is not None and existing.get("status") == "REJECTED":
            return redraft_revision(existing, body)

    project = DB.find("projects", body.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    model_version = DB.find("model_versions", body.get("model_version_id"))
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")
    revised_version = DB.find("model_versions", body.get("revised_version_id"))
    if revised_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")

    rebuild_revision_payload(body)
    revision = new_record(**body)
    revision["id"] = str(revision["id"])
    revision["impact_keys"] = list(body.get("impact_keys") or [])
    revision["status"] = "DRAFT"
    revision["engineering_hold"] = True
    revision["affects_fabricated_content"] = affects_fabricated_content(revision)
    revision["approved_change_value_cents"] = 0
    revision["equipment_value_delta_cents"] = 0
    revision["revised_trade_hours"] = rhu(num(revision.get("impact_qualified_hours"), 0.0), 2)
    revision["tied_shipment_hours"] = 0.0
    revision["shipment_tied_flag"] = False
    revision["required_actions"] = []
    revision["base_flow_hours"] = 0.0
    revision["peak_multiplier"] = 1.0
    revision["adjusted_flow_hours"] = 0.0
    revision["excess_flow_hours"] = 0.0
    revision["impact_values"] = []
    revision["number"] = "REV-%s-%04d" % (project.get("project_code") or "JOB", DB.next_seq())

    # PRD §2.4: "The service never applies a partial mutation: if any
    # precondition of an operation fails, no field of the target resource, and no
    # cascaded field of any related resource, is changed." A refused creation
    # therefore writes no revision row at all, so the payload is validated before
    # the record is stored.
    _validate_revision_payload(revision, project, model_version)
    DB.put("revisions", revision)
    revision_derived(revision, project)
    restrict_material_releases(revision, project)
    refresh_after_revision(project)
    return revision


def rebuild_revision_payload(body):
    """Normalise the incoming revision body into stored form."""
    body["project_id"] = body.get("project_id")
    body["model_version_id"] = body.get("model_version_id")
    body["revised_version_id"] = body.get("revised_version_id")
    body["revision_kind"] = body.get("revision_kind")
    body["safety_gate_status"] = body.get("safety_gate_status") or "OPEN"
    body["label_verified_status"] = body.get("label_verified_status") or "UNVERIFIED"
    body["safety_verified_status"] = body.get("safety_verified_status") or "UNVERIFIED"
    body["percent_complete_mode"] = body.get("percent_complete_mode") or "FLOW"
    body["label_codes"] = list(body.get("label_codes") or [])
    body["fabricated_content_codes"] = list(body.get("fabricated_content_codes") or [])
    body["impact_keys"] = list(body.get("impact_keys") or [])
    return body


def _validate_revision_payload(revision, project, model_version):
    check_model_quantities(model_version)
    resolve_impact_keys(revision.get("impact_keys"))
    check_label_codes(revision)
    check_impact_required(revision)
    check_supersession(model_version, revision)
    check_lifecycle(revision)


def redraft_revision(revision, body):
    project = DB.find("projects", revision.get("project_id"))
    new_keys = body.get("impact_keys")
    if new_keys is not None:
        let = resolve_impact_keys(new_keys)
        revision["impact_keys"] = list(new_keys)
    revision["status"] = "DRAFT"
    revision["impact_values"] = []
    revision["engineering_hold"] = True
    touch(revision)
    return revision


def revision_derived(revision, project):
    revision["affects_fabricated_content"] = affects_fabricated_content(revision)
    revision["engineering_hold"] = revision.get("status") not in ("APPROVED", "REJECTED", "SUPERSEDED")
    revision_cost_impact(revision)
    revision_equipment_delta(revision)
    revision_flow_hours(revision, project)
    revision["revised_trade_hours"] = rhu(num(revision.get("impact_qualified_hours"), 0.0), 2)
    revision["tied_shipment_hours"] = rhu(_tied_shipment_hours(revision), 2)
    revision["shipment_tied_flag"] = revision["tied_shipment_hours"] > 0
    revision["excess_flow_hours"] = rhu(
        num(revision.get("adjusted_flow_hours"), 0.0) - num(revision.get("rework_hours"), 0.0), 2)
    return revision


def _tied_shipment_hours(revision):
    keys = set(revision.get("impact_keys") or [])
    total = 0.0
    for key in keys:
        kind, record = resolve_impact_key(key)
        if kind == "takeoff_line":
            for component in DB.all("prefab_components"):
                if component.get("takeoff_line_id") == record["id"] and component.get("install_status") in ("FABRICATED", "LOADED", "SET"):
                    total += component_crafted_hours(component)
    return total


# --------------------------------------------------------------------------
# Submit
# --------------------------------------------------------------------------

def submit_revision(revision, body=None):
    project = DB.find("projects", revision.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")

    if revision.get("status") != "DRAFT":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    check_impact_required(revision)
    resolved = resolve_impact_keys(revision.get("impact_keys"))
    revised_version = DB.find("model_versions", revision.get("revised_version_id"))
    if revised_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")
    check_model_quantities(revised_version)
    check_label_codes(revision)
    check_lifecycle(revision)

    revision["status"] = "SUBMITTED"
    revision["engineering_hold"] = True
    revision_derived(revision, project)
    restart_material_releases(revision, project, resolved)
    close_affected_release_gates(revision, project, resolved)
    touch(revision)
    refresh_after_revision(project)
    return revision


def commodity_releases(project, commodities):
    return [release for release in DB.all("material_releases")
            if release.get("project_id") == project["id"]
            and release.get("material_commodity") in commodities]


def restrict_material_releases(revision, project):
    resolved = resolve_impact_keys(revision.get("impact_keys"))
    commodities = commodities_for_impacts(resolved)
    for release in commodity_releases(project, commodities):
        if release.get("status") == "RECEIVED":
            continue
        if release.get("status") != "RESTRICTED":
            release["status"] = "RESTRICTED"
            release["restriction_since_iso"] = CLOCK.now_iso()
            touch(release)


def restart_material_releases(revision, project, resolved):
    """Submission puts every affected commodity release into RESTRICTED."""
    commodities = commodities_for_impacts(resolved)
    for release in commodity_releases(project, commodities):
        if release.get("status") == "RECEIVED":
            continue
        release["status"] = "RESTRICTED"
        if release.get("restriction_since_iso") is None:
            release["restriction_since_iso"] = CLOCK.now_iso()
        travel = DB.find("material_releases", release["id"])
        from calculations import material_release_timing
        material_release_timing(release, project)
        touch(release)
        # keep a module-level reference so the timing import stays local
        _ = travel


def close_affected_release_gates(revision, project, resolved):
    from orders import refresh_order_derived, compute_releasable_status
    affected_orders = affected_orders_for(revision, resolved)
    for order in affected_orders:
        refresh_order_derived(order)
        compute_releasable_status(order, project)
    return affected_orders


def affected_components(kind, record):
    """The component rows a single resolved impact key names."""
    if kind == "component":
        return [record]
    if kind == "takeoff_line":
        return [c for c in DB.all("prefab_components")
                if c.get("takeoff_line_id") == record["id"]]
    if kind == "rack":
        return [c for c in DB.all("prefab_components")
                if c.get("rack_id") == record["id"]]
    return []


def affected_orders_for(revision, resolved=None):
    if resolved is None:
        resolved = resolve_impact_keys(revision.get("impact_keys"))
    order_ids = set()
    for _key, kind, record in resolved:
        if kind == "component":
            order_ids.add(record.get("prefab_order_id"))
        elif kind == "takeoff_line":
            for component in DB.all("prefab_components"):
                if component.get("takeoff_line_id") == record["id"]:
                    order_ids.add(component.get("prefab_order_id"))
        elif kind == "rack":
            for component in DB.all("prefab_components"):
                if component.get("rack_id") == record["id"]:
                    order_ids.add(component.get("prefab_order_id"))
    return [DB.find("prefab_orders", oid) for oid in order_ids if DB.find("prefab_orders", oid)]


def refresh_after_revision(project):
    from orders import recompute_all_releasable
    from projects import fabrication_locked
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    project["fabricated_revision_active"] = any(
        r.get("project_id") == project["id"]
        and r.get("status") not in TERMINAL_REVISION_STATUSES
        and r.get("affects_fabricated_content")
        for r in DB.all("revisions")
    )
    recompute_all_releasable(project)
    fabrication_locked(project)
    project["approved_change_value_cents"] = sum(
        int(r.get("approved_change_value_cents") or 0)
        for r in DB.all("revisions")
        if r.get("project_id") == project["id"] and r.get("status") == "APPROVED"
    )
    return project


# --------------------------------------------------------------------------
# Approve / reject
# --------------------------------------------------------------------------

def approve_revision(revision, body):
    project = DB.find("projects", revision.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    model_version = DB.find("model_versions", revision.get("model_version_id"))
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")

    expected = body.get("expected_model_version_version")
    if expected is None:
        fail("ERR_STALE_VERSION")
    if int(expected) != int(model_version.get("version", 0)):
        fail("ERR_STALE_VERSION")

    if revision.get("status") != "SUBMITTED":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    resolution = body.get("resolution")
    is_rejection = bool(resolution) and "REJECT" in str(resolution).upper()

    check_impact_required(revision)
    resolved = resolve_impact_keys(revision.get("impact_keys"))

    if is_rejection:
        return _reject_revision(revision, project, resolution)

    check_model_quantities(model_version)
    check_label_codes(revision)
    check_supersession(model_version, revision)
    revision_derived(revision, project)
    check_craft_hours_ceiling(revision)
    check_lifecycle(revision)
    if revision.get("safety_gate_status") == "BLOCKED":
        fail("ERR_REVISION_SAFETY_BLOCKED")

    revision["status"] = "APPROVED"
    revision["engineering_hold"] = False
    revision["impact_values"] = revision_cost_impact(revision)
    revision["approved_change_value_cents"] = int(
        sum(v["negotiated_value_cents"] for v in revision["impact_values"]))
    touch(revision)

    from models import supersede_model_version, mark_line_superseded, recompute_model_version_quantities
    supersede_model_version(model_version)
    recompute_model_version_quantities(model_version)

    for key in (revision.get("impact_keys") or []):
        kind, record = resolve_impact_key(key)
        if kind == "takeoff_line":
            mark_line_superseded(record)

    # PRD §3.7: "each naming impact drives the affected `FABRICATED` component to
    # `REWORK` and creates an open rework job for it". An impact key may name a
    # takeoff hash or a rack code rather than a component code, so the key is
    # expanded to the components it reaches before the rework is queued.
    for key, kind, record in resolved:
        for component in affected_components(kind, record):
            _queue_rework(component, revision, key)

    refresh_after_revision(project)
    return revision


def _reject_revision(revision, project, resolution):
    revision["status"] = "REJECTED"
    revision["engineering_hold"] = False
    revision["resolution"] = resolution
    touch(revision)
    resolved = resolve_impact_keys(revision.get("impact_keys"))
    commodities = commodities_for_impacts(resolved)
    for release in commodity_releases(project, commodities):
        if release.get("status") == "RESTRICTED":
            release["status"] = "RELEASED"
            release["restriction_since_iso"] = None
            touch(release)
    refresh_after_revision(project)
    return revision


def _queue_rework(component, revision, impact_key):
    order = DB.find("prefab_orders", component.get("prefab_order_id"))
    if component.get("install_status") == "FABRICATED":
        component["install_status"] = "REWORK"
        touch(component)
    elif component.get("install_status") == "SCRAPPED":
        create_rework_job(component, revision, impact_key,
                          status="RECUT_DEFERRED", project_id=(order or {}).get("project_id"))
        return
    create_rework_job(component, revision, impact_key, status="OPEN",
                      project_id=(order or {}).get("project_id"))


# --------------------------------------------------------------------------
# ReworkJob
# --------------------------------------------------------------------------

def rework_hours_for(component):
    assembly = DB.find("assemblies", component.get("assembly_code"))
    if assembly is None:
        return 0.0
    return rhu(num(component.get("quantity"), 0.0) * num(assembly.get("prefab_hours_per_unit"), 0.0), 2)


def create_rework_job(component, revision, impact_key, status="OPEN", project_id=None):
    order = DB.find("prefab_orders", component.get("prefab_order_id"))
    project_id = project_id or (order or {}).get("project_id")
    job = new_record(
        project_id=project_id,
        prefab_component_id=component["id"],
        revision_id=(revision or {}).get("id"),
        impact_key=impact_key,
        reason_code="DESIGN_REVISION",
        reason_question_code="REWORK_SCOPE",
        reason_option_code="RECUT_AND_REINSTALL",
        confirmation_mode="SHOP_CONFIRMATION",
        confirmation_mode_effective="SHOP_CONFIRMATION",
        scheduled_start_iso=CLOCK.now_iso(),
        rework_hours=rework_hours_for(component),
        status=status,
    )
    DB.put("rework_jobs", job)
    if order is not None:
        from orders import refresh_order_derived, compute_releasable_status
        refresh_order_derived(order)
        if project_id:
            project = DB.find("projects", project_id)
            if project is not None:
                compute_releasable_status(order, project)
    return job


def open_reship_rework_job(order, project):
    components = [c for c in DB.all("prefab_components")
                  if c.get("prefab_order_id") == order["id"]]
    if not components:
        return None
    component = components[0]
    return create_rework_job(component, None, component.get("component_code"), status="OPEN",
                             project_id=project["id"])


def require_rework_job(job_id):
    if not job_id:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    job = DB.find("rework_jobs", job_id)
    if job is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return job


def set_rework_status(job, body):
    target = body.get("status")
    if target is None:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    current = job.get("status")
    key = (current, target)
    if key not in REWORK_TRANSITIONS:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    handler = REWORK_TRANSITIONS[key]

    component = DB.find("prefab_components", job.get("prefab_component_id"))
    if component is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    order = DB.find("prefab_orders", component.get("prefab_order_id"))
    project = DB.find("projects", job.get("project_id"))

    if handler == "start":
        if job.get("reason_option_code") is None:
            fail("ERR_INVALID_PREFAB_TRANSITION")
        job["status"] = "IN_PROGRESS"
    elif handler == "close":
        if num(job.get("rework_hours"), 0.0) <= 0:
            fail("ERR_INVALID_PREFAB_TRANSITION")
        job["status"] = "CLOSED"
        component["install_status"] = "FABRICATED"
        touch(component)
    elif handler == "close_zero":
        if num(job.get("rework_hours"), 0.0) != 0:
            fail("ERR_INVALID_PREFAB_TRANSITION")
        job["status"] = "CLOSED"
        component["install_status"] = "FABRICATED"
        touch(component)
    elif handler == "scrap":
        job["status"] = "RECUT_DEFERRED"
        component["install_status"] = "SCRAPPED"
        touch(component)
        rack = DB.find("racks", component.get("rack_id"))
        if rack is not None:
            rack_value_capacity_check(rack)
    elif handler == "reopen":
        if component.get("install_status") != "FABRICATED":
            fail("ERR_INVALID_PREFAB_TRANSITION")
        job["status"] = "IN_PROGRESS"
        component["install_status"] = "REWORK"
        touch(component)

    if body.get("resolution"):
        job["resolution"] = body["resolution"]
    touch(job)

    if order is not None:
        from orders import refresh_order_derived, compute_releasable_status
        refresh_order_derived(order)
        if project is not None:
            compute_releasable_status(order, project)
    if project is not None:
        refresh_after_revision(project)
    return job


def filter_revisions(args):
    records = DB.all("revisions")
    for key in ("project_id", "model_version_id", "revised_version_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records


def filter_rework_jobs(args):
    records = DB.all("rework_jobs")
    for key in ("project_id", "prefab_component_id", "revision_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records