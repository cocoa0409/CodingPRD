"""PrefabOrder: release gate, hoisting window, laydown slot and the three state
dimensions (fabricate_status, deliver_status, shipment_status)."""

from core import (CLOCK, DB, fail, new_record, num, rhu, shift_days, to_dt,
                  touch, whole_days_between)
from calculations import (APPLIANCE_LAG, DEFAULT_SHOP_TAT_DAYS,
                          hoisting_window_derivation, idle_capacity,
                          material_release_timing, update_project_pipeline,
                          craft_hours_credit, craft_hours_balance,
                          component_crafted_hours)
from projects import (refresh_project, refresh_project_soft, posture_for_slippage,
                      compute_slippage)

TRANSPORT_LAG = {
    "FLATBED": {"travel_days": 1, "unload_days": 1},
    "MIXED_LOAD": {"travel_days": 2, "unload_days": 2},
}

RELEASABLE_MEMBERS = ("ENGINEERING_HOLD", "MATERIAL_HOLD", "READY", "PERMITTED", "ALLOWED")
RELEASABLE_ACCEPTED = ("READY", "PERMITTED", "ALLOWED")

DELIVER_TRANSITIONS = {
    ("AWAITING", "STAGED"): "stage",
    ("STAGED", "LOADED"): "load",
    ("LOADED", "AWAITING"): "unload",
    ("LOADED", "IN_TRANSIT"): "dispatch",
    ("IN_TRANSIT", "DELIVERED"): "deliver",
    ("IN_TRANSIT", "LOADED"): "loss_recovery",
}

FABRICATE_TRANSITIONS = {
    ("RELEASED", "IN_FABRICATION"): "start",
    ("IN_FABRICATION", "FABRICATED"): "finish",
}

NON_TERMINAL_SHIPMENT_STATES = ("PENDING", "RESERVED", "STAGED", "LOADED",
                                "IN_TRANSIT", "LOCKED")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def require_order(order_id):
    if not order_id:
        fail("ERR_PREFAB_ORDER_NOT_FOUND")
    order = DB.find("prefab_orders", order_id)
    if order is None:
        fail("ERR_PREFAB_ORDER_NOT_FOUND")
    return order


def order_components(order):
    return [c for c in DB.all("prefab_components") if c.get("prefab_order_id") == order["id"]]


def component_takeoff_line(component):
    return DB.find("takeoff_lines", component.get("takeoff_line_id"))


def order_artifact_keys(order):
    """Business keys that name this package's assembly set."""
    keys = set()
    for component in order_components(order):
        if component.get("assembly_code"):
            keys.add(component["assembly_code"])
        if component.get("component_code"):
            keys.add(component["component_code"])
        line = component_takeoff_line(component)
        if line is not None and line.get("takeoff_hash"):
            keys.add(line["takeoff_hash"])
        rack = DB.find("racks", component.get("rack_id"))
        if rack is not None and rack.get("rack_code"):
            keys.add(rack["rack_code"])
    return keys


def order_commodities(order):
    commodities = set()
    for component in order_components(order):
        line = component_takeoff_line(component)
        if line is not None and line.get("conduit_run_type"):
            commodities.add(line["conduit_run_type"])
        assembly = DB.find("assemblies", component.get("assembly_code"))
        if assembly is not None and assembly.get("is_switchgear"):
            commodities.add("SWITCHGEAR")
    return commodities


def non_terminal_orders(project_id):
    out = []
    for order in DB.all("prefab_orders"):
        if order.get("project_id") != project_id:
            continue
        if order.get("fabricate_status") == "CANCELLED":
            continue
        if order.get("deliver_status") == "DELIVERED":
            continue
        out.append(order)
    return out


# --------------------------------------------------------------------------
# Derived rollups on the order
# --------------------------------------------------------------------------

def refresh_order_derived(order):
    components = order_components(order)
    order["assembly_count"] = len(components)
    order["crafted_hours_total"] = rhu(
        sum(component_crafted_hours(c) for c in components), 2)
    rework_jobs = [j for j in DB.all("rework_jobs") if j.get("prefab_component_id") in {c["id"] for c in components}]
    order["rework_order_count"] = len(rework_jobs)
    order["rework_hours"] = rhu(sum(component_crafted_hours(c) for c in components
                                    if c.get("install_status") == "REWORK"), 2)
    return order


def project_for(order):
    project = DB.find("projects", order.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    return project


# --------------------------------------------------------------------------
# releasable_status
# --------------------------------------------------------------------------

def revision_names_order(project, order):
    keys = order_artifact_keys(order)
    if not keys:
        return False
    for revision in DB.all("revisions"):
        if revision.get("project_id") != project["id"]:
            continue
        if revision.get("status") in ("APPROVED", "REJECTED", "SUPERSEDED"):
            continue
        for key in (revision.get("impact_keys") or []):
            if key in keys:
                return True
    return False


def material_gate_blocks(project):
    for commodity in (project.get("material_gate_commodities") or []):
        declared = False
        for release in DB.all("material_releases"):
            if release.get("project_id") != project["id"]:
                continue
            if release.get("material_commodity") != commodity:
                continue
            if release.get("declared_for_procurement"):
                declared = True
                break
        if not declared:
            return True
    return False


def compute_releasable_status(order, project):
    if order.get("fabricate_status") == "CANCELLED":
        order["releasable_status"] = "ENGINEERING_HOLD"
        return order["releasable_status"]
    if int(order.get("rework_order_count") or 0) > 0:
        order["releasable_status"] = "ENGINEERING_HOLD"
        return order["releasable_status"]
    if project.get("fabricated_revision_active") and revision_names_order(project, order):
        order["releasable_status"] = "ENGINEERING_HOLD"
        return order["releasable_status"]
    if project.get("project_posture") == "FROZEN":
        order["releasable_status"] = "ENGINEERING_HOLD"
        return order["releasable_status"]
    if material_gate_blocks(project):
        order["releasable_status"] = "MATERIAL_HOLD"
        return order["releasable_status"]
    posture = project.get("project_posture")
    if posture == "RELEASE_PENDING":
        order["releasable_status"] = "PERMITTED"
    elif posture == "ON_TRACK":
        order["releasable_status"] = "ALLOWED"
    else:
        order["releasable_status"] = "READY"
    return order["releasable_status"]


def recompute_all_releasable(project):
    for order in DB.all("prefab_orders"):
        if order.get("project_id") != project["id"]:
            continue
        if order.get("fabricate_status") == "CANCELLED":
            continue
        refresh_order_derived(order)
        compute_releasable_status(order, project)
    return project


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------

def create_prefab_order(body):
    project = DB.find("projects", body.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    model_version = DB.find("model_versions", body.get("model_version_id"))
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")

    for key in ("impact_keys",):
        pass
    if revision_names_model_version(project, model_version):
        fail("ERR_ENGINEERING_HOLD_ACTIVE")

    order = new_record(
        project_id=project["id"],
        model_version_id=model_version["id"],
        stage_code=body.get("stage_code"),
        zone_code=body.get("zone_code"),
        fabricate_status="PLANNED",
        deliver_status="AWAITING",
        shipment_status="PENDING",
        transport_kind=body.get("transport_kind"),
        hoisting_window_id=body.get("hoisting_window_id"),
        required_on_site_iso=body.get("required_on_site_iso"),
        installation_window_start_iso=body.get("installation_window_start_iso"),
        fabricate_quantity=num(body.get("fabricate_quantity"), 0.0),
        shop_utilisation_basis_pct=num(body.get("shop_utilisation_basis_pct"), 0.0),
        release_to_shop_iso=None,
        releasable_status="READY",
        laydown_slot_index=None,
        rework_order_count=0,
        assembly_count=0,
        crafted_hours_total=0.0,
        crafted_hours_credit=0.0,
        rework_hours=0.0,
        hoisting_duration_days=None,
        hoisting_start_iso=None,
        hoisting_end_iso=None,
        planned_delivery_iso=None,
        fabrication_utilisation_pct=0.0,
    )
    DB.put("prefab_orders", order)
    refresh_order_derived(order)
    compute_releasable_status(order, project)
    refresh_project(project)
    return order


def revision_names_model_version(project, model_version):
    """A non-terminal revision naming an artifact laid out in this model version."""
    keys = set()
    for line in DB.all("takeoff_lines"):
        if line.get("model_version_id") == model_version["id"] and line.get("takeoff_hash"):
            keys.add(line["takeoff_hash"])
    for rack in DB.all("racks"):
        if rack.get("model_version_id") == model_version["id"] and rack.get("rack_code"):
            keys.add(rack["rack_code"])
    if not keys:
        return False
    for revision in DB.all("revisions"):
        if revision.get("project_id") != project["id"]:
            continue
        if revision.get("status") in ("APPROVED", "REJECTED", "SUPERSEDED"):
            continue
        for key in (revision.get("impact_keys") or []):
            if key in keys:
                return True
    return False


# --------------------------------------------------------------------------
# Laydown and hoisting guards
# --------------------------------------------------------------------------

def laydown_slot_for(order, project):
    slots = int(num(project.get("laydown_slots"), 0))
    if slots <= 0:
        fail("ERR_LAYDOWN_SLOT_UNAVAILABLE")
    occupied = set()
    for other in non_terminal_orders(project["id"]):
        if other["id"] == order["id"]:
            continue
        index = other.get("laydown_slot_index")
        if index is None:
            continue
        if other.get("release_to_shop_iso") is None:
            continue
        occupied.add(int(index))
    for index in range(1, slots + 1):
        if index not in occupied:
            return index
    fail("ERR_LAYDOWN_SLOT_UNAVAILABLE")


def hoisting_conflict(order, project, start, end):
    if start is None or end is None:
        return
    window_id = order.get("hoisting_window_id")
    for other in DB.all("prefab_orders"):
        if other["id"] == order["id"]:
            continue
        if other.get("project_id") != project["id"]:
            continue
        if other.get("release_to_shop_iso") is None:
            continue
        other_start = to_dt(other.get("hoisting_start_iso"))
        other_end = to_dt(other.get("hoisting_end_iso"))
        if other_start is None or other_end is None:
            continue
        if window_id is not None and other.get("hoisting_window_id") == window_id:
            if start < other_end and other_start < end:
                fail("ERR_HOISTING_WINDOW_CONFLICT")
        if other_start == start and other.get("fabricate_status") != "CANCELLED":
            fail("ERR_HOISTING_WINDOW_CONFLICT")


def required_on_site_in_window(order):
    required = to_dt(order.get("required_on_site_iso"))
    start = to_dt(order.get("hoisting_start_iso"))
    end = to_dt(order.get("hoisting_end_iso"))
    if required is None:
        return True
    if start is None or end is None:
        return True
    return start <= required < end


def compute_planned_delivery(order, project):
    required = to_dt(order.get("required_on_site_iso"))
    if required is None:
        order["planned_delivery_iso"] = None
        return None
    lead_days = 0
    commodities = order_commodities(order)
    for release in DB.all("material_releases"):
        if release.get("project_id") != project["id"]:
            continue
        if release.get("material_commodity") in commodities or not commodities:
            lead_days = max(lead_days, int(num(release.get("lead_time_days"), 0)))
    lag = TRANSPORT_LAG.get(order.get("transport_kind"), {"travel_days": 1, "unload_days": 1})
    planned = shift_days(required, -(lead_days + lag["travel_days"] + lag["unload_days"]))
    order["planned_delivery_iso"] = planned
    return planned


# --------------------------------------------------------------------------
# Release
# --------------------------------------------------------------------------

def release_order(order, body):
    project = project_for(order)

    expected = body.get("expected_prefab_order_version")
    if expected is None:
        fail("ERR_STALE_VERSION")
    if int(expected) != int(order.get("version", 0)):
        fail("ERR_STALE_VERSION")

    if order.get("fabricate_status") != "PLANNED":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    if project.get("project_posture") not in ("ON_TRACK", "RELEASE_PENDING", "RECOVERY_MODE"):
        fail("ERR_INVALID_PREFAB_TRANSITION")

    recompute_all_releasable(project)
    if order.get("releasable_status") == "ENGINEERING_HOLD":
        fail("ERR_ENGINEERING_HOLD_ACTIVE")
    if order.get("releasable_status") == "MATERIAL_HOLD":
        fail("ERR_MATERIAL_HOLD_ACTIVE")
    if order.get("releasable_status") not in RELEASABLE_ACCEPTED:
        fail("ERR_INVALID_PREFAB_TRANSITION")

    refresh_order_derived(order)
    window = hoisting_window_derivation(order, project)
    hoisting_conflict(order, project, window["hoisting_start"], window["hoisting_end"])

    if order.get("release_to_shop_iso") is not None:
        fail("ERR_WINDOW_ALREADY_FROZEN")

    start = window["hoisting_start"]
    if start is not None and start < CLOCK.now():
        fail("ERR_FABRICATION_WINDOW_LAPSED")

    slot = laydown_slot_for(order, project)

    order["fabricate_status"] = "RELEASED"
    order["release_to_shop_iso"] = CLOCK.now_iso()
    order["laydown_slot_index"] = slot
    order["hoisting_duration_days"] = window["hoisting_duration_days"]
    order["hoisting_start_iso"] = start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if start else None
    end = window["hoisting_end"]
    order["hoisting_end_iso"] = end.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if end else None
    compute_planned_delivery(order, project)
    order["fabrication_utilisation_pct"] = (num(order.get("shop_utilisation_basis_pct"), 0.0)
                                            if order.get("release_to_shop_iso") else 0.0)

    for release in DB.all("material_releases"):
        if release.get("project_id") != project["id"]:
            continue
        if release.get("status") == "RECEIVED":
            continue
        material_release_timing(release, project)

    touch(order)
    refresh_order_derived(order)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    recompute_all_releasable(project)
    return order


# --------------------------------------------------------------------------
# Shop dimension
# --------------------------------------------------------------------------

def set_fabrication_status(order, body):
    project = project_for(order)
    target = body.get("fabricate_status")
    if target is None:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    current = order.get("fabricate_status")
    if current == "CANCELLED":
        fail("ERR_INVALID_PREFAB_TRANSITION")
    key = (current, target)
    if key not in FABRICATE_TRANSITIONS:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    handler = FABRICATE_TRANSITIONS[key]

    if handler == "finish" and int(order.get("assembly_count") or 0) <= 0:
        refresh_order_derived(order)
        if int(order.get("assembly_count") or 0) <= 0:
            fail("ERR_INVALID_PREFAB_TRANSITION")

    order["fabricate_status"] = target
    if handler == "start":
        order["queue_released_components"] = True
    if handler == "finish":
        craft_hours_credit(project)
    touch(order)
    refresh_order_derived(order)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    return order


def ressue_order(order):
    project = project_for(order)
    if order.get("fabricate_status") != "FABRICATED":
        fail("ERR_INVALID_PREFAB_TRANSITION")
    if order.get("deliver_status") != "AWAITING":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    order["fabricate_status"] = "PLANNED"
    order["laydown_slot_index"] = None
    order["hoisting_start_iso"] = None
    order["hoisting_end_iso"] = None
    order["hoisting_duration_days"] = None
    order["release_to_shop_iso"] = None
    order["fabrication_utilisation_pct"] = 0.0
    order["planned_delivery_iso"] = None

    for component in order_components(order):
        if component.get("install_status") == "FABRICATED":
            component["install_status"] = "PLANNED"
            component["crafted_hours_credit"] = 0.0
            touch(component)
    touch(order)
    refresh_order_derived(order)
    refresh_project(project)
    recompute_all_releasable(project)
    return order


def cancel_order(order):
    project = project_for(order)
    if order.get("fabricate_status") != "PLANNED":
        fail("ERR_INVALID_PREFAB_TRANSITION")
    if order.get("deliver_status") != "AWAITING":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    order["fabricate_status"] = "CANCELLED"
    affected_racks = []
    for component in order_components(order):
        if component.get("install_status") in ("PLANNED", "FABRICATED"):
            rack_id = component.get("rack_id")
            component["rack_id"] = None
            component["install_status"] = "SCRAPPED"
            touch(component)
            if rack_id:
                affected_racks.append(rack_id)
    from calculations import rack_value_capacity_check
    for rack_id in set(affected_racks):
        rack = DB.find("racks", rack_id)
        if rack is not None:
            rack_value_capacity_check(rack)
    touch(order)
    refresh_order_derived(order)
    refresh_project(project)
    recompute_all_releasable(project)
    return order


# --------------------------------------------------------------------------
# Delivery dimension
# --------------------------------------------------------------------------

def set_delivery_status(order, body):
    project = project_for(order)
    deliver_target = body.get("deliver_status")
    ship_target = body.get("shipment_status")
    current = order.get("deliver_status")

    if deliver_target in (None, current) and ship_target:
        if order.get("shipment_status") == "DELIVERED":
            fail("ERR_INVALID_PREFAB_TRANSITION")
        order["shipment_status"] = ship_target
        touch(order)
        return order

    if deliver_target is None:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    key = (current, deliver_target)
    if key not in DELIVER_TRANSITIONS:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    handler = DELIVER_TRANSITIONS[key]

    if handler == "stage":
        if order.get("fabricate_status") != "FABRICATED":
            fail("ERR_INVALID_PREFAB_TRANSITION")
    elif handler == "load":
        if order.get("shipment_status") not in ("PENDING", "RESERVED", "STAGED"):
            fail("ERR_INVALID_PREFAB_TRANSITION")
        if not required_on_site_in_window(order):
            fail("ERR_INVALID_PREFAB_TRANSITION")
        recompute_all_releasable(project)
        if order.get("releasable_status") == "ENGINEERING_HOLD":
            fail("ERR_ENGINEERING_HOLD_ACTIVE")
        if order.get("releasable_status") == "MATERIAL_HOLD":
            fail("ERR_MATERIAL_HOLD_ACTIVE")
    elif handler == "dispatch":
        planned = to_dt(order.get("planned_delivery_iso"))
        if planned is not None and CLOCK.now() < planned:
            fail("ERR_INVALID_PREFAB_TRANSITION")
    elif handler == "loss_recovery":
        if not (order.get("shipment_status") == "LOST" or ship_target == "LOST"):
            fail("ERR_INVALID_PREFAB_TRANSITION")

    if handler == "deliver":
        delivered_quantity = num(order.get("fabricate_quantity"), 0.0)
        order["fabricate_quantity"] = max(0.0, num(order.get("fabricate_quantity"), 0.0) - delivered_quantity)
        order["deleted_from_shop_queue"] = True

    order["deliver_status"] = deliver_target
    if handler in ("stage",):
        pass
    elif handler == "load":
        order["shipment_status"] = "LOADED"
    elif handler == "unload":
        order["shipment_status"] = "STAGED"
    elif handler == "dispatch":
        order["shipment_status"] = "IN_TRANSIT"
    elif handler == "deliver":
        order["shipment_status"] = "DELIVERED"
    elif handler == "loss_recovery":
        order["shipment_status"] = "LOADED"

    if ship_target and handler != "loss_recovery":
        order["shipment_status"] = ship_target

    if handler == "load":
        _cascade_components_to_loaded(order, project)
    elif handler == "unload":
        for component in order_components(order):
            if component.get("install_status") == "LOADED":
                component["install_status"] = "FABRICATED"
                touch(component)
    elif handler == "loss_recovery":
        from revisions import open_reship_rework_job
        open_reship_rework_job(order, project)

    touch(order)
    refresh_order_derived(order)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    recompute_all_releasable(project)
    return order


def _cascade_components_to_loaded(order, project):
    from calculations import rack_capacity_ok, component_prefab_value
    for component in order_components(order):
        if component.get("install_status") != "FABRICATED":
            continue
        rack = DB.find("racks", component.get("rack_id"))
        if rack is not None and not rack_capacity_ok(rack):
            continue
        component["install_status"] = "LOADED"
        component["prefab_value_cents"] = component_prefab_value(component, project)
        component["contractual_credit_cents"] = _contractual_credit(component)
        touch(component)


def _contractual_credit(component):
    assembly = DB.find("assemblies", component.get("assembly_code"))
    quantity = num(component.get("quantity"), 0.0)
    if assembly is None:
        return 0
    value = num(component.get("prefab_value_cents"), 0.0)
    return int(value + quantity * num(assembly.get("core_charge_cents"), 0.0)
               - quantity * num(assembly.get("recycled_credit_cents"), 0.0))


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------

def filter_orders(args):
    records = DB.all("prefab_orders")
    for key in ("project_id", "model_version_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records