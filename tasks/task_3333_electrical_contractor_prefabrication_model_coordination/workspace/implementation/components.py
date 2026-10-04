"""PrefabComponent: creation, shop fabrication, field installation and the
rack capacity guard."""

from core import DB, fail, new_record, num, rhu, touch
from calculations import (component_crafted_hours, component_prefab_value,
                          rack_capacity_ok, rack_value_capacity_check,
                          update_project_pipeline, craft_hours_credit,
                          craft_hours_balance, idle_capacity)
from projects import compute_slippage, posture_for_slippage

OTHER_TRADE_KINDS = ("MECHANICAL_ROUGH", "PLUMBING_ROUGH", "SPRINKLER_MAIN",
                     "DRYWALL_CLOSEOUT")
BLOCKING_STATUSES = ("PLANNED", "PERMITTED", "ACTIVE", "DISALLOWED")


def require_component(component_id):
    if not component_id:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    component = DB.find("prefab_components", component_id)
    if component is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return component


def component_quantity_contribution(component):
    return num(component.get("quantity"), 0.0)


def create_component(body):
    order = DB.find("prefab_orders", body.get("prefab_order_id"))
    if order is None:
        fail("ERR_PREFAB_ORDER_NOT_FOUND")
    project = DB.find("projects", order.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")

    rack_id = body.get("rack_id")
    if rack_id:
        if DB.find("racks", rack_id) is None:
            fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    takeoff_line_id = body.get("takeoff_line_id")
    if takeoff_line_id and DB.find("takeoff_lines", takeoff_line_id) is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    predecessor_id = body.get("predecessor_component_id")
    if predecessor_id and DB.find("prefab_components", predecessor_id) is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    assembly_code = body.get("assembly_code")
    if assembly_code and DB.find("assemblies", assembly_code) is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    component_code = body.get("component_code") or assembly_code
    component = new_record(
        prefab_order_id=order["id"],
        rack_id=rack_id,
        takeoff_line_id=takeoff_line_id,
        predecessor_component_id=predecessor_id,
        assembly_code=assembly_code,
        component_code=component_code,
        quantity=num(body.get("quantity"), 0.0),
        install_status="PLANNED",
        chain_mode=body.get("chain_mode"),
        chain_dependency_link=body.get("chain_dependency_link"),
        crafted_hours=0.0,
        prefab_value_cents=0,
        contractual_credit_cents=0,
        crafted_hours_credit=0.0,
    )
    component["crafted_hours"] = component_crafted_hours(component)
    DB.put("prefab_components", component)

    rack = DB.find("racks", rack_id) if rack_id else None
    if rack is not None:
        rack_value_capacity_check(rack)
        if not rack_capacity_ok(rack):
            del DB.prefab_components[component["id"]]
            rack_value_capacity_check(rack)
            fail("ERR_RACK_CAPACITY_EXCEEDED")

    from orders import refresh_order_derived, recompute_all_releasable
    refresh_order_derived(order)
    update_project_pipeline(project)
    recompute_all_releasable(project)
    return component


def fabricate_component(component):
    order = DB.find("prefab_orders", component.get("prefab_order_id"))
    if order is None:
        fail("ERR_PREFAB_ORDER_NOT_FOUND")
    project = DB.find("projects", order.get("project_id"))

    if component.get("install_status") != "PLANNED":
        fail("ERR_INVALID_PREFAB_TRANSITION")
    if order.get("fabricate_status") != "IN_FABRICATION":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    from orders import refresh_order_derived, compute_releasable_status
    refresh_order_derived(order)
    compute_releasable_status(order, project)
    if order.get("releasable_status") == "ENGINEERING_HOLD":
        fail("ERR_ENGINEERING_HOLD_ACTIVE")

    predecessor_id = component.get("predecessor_component_id")
    if predecessor_id:
        predecessor = DB.find("prefab_components", predecessor_id)
        chain_ok = (predecessor is not None and predecessor.get("install_status") == "SET")
        if component.get("chain_mode") == "PARALLEL_FABRICATION":
            chain_ok = True
        if not chain_ok:
            fail("ERR_INVALID_PREFAB_TRANSITION")

    component["install_status"] = "FABRICATED"
    component["crafted_hours"] = component_crafted_hours(component)
    component["crafted_hours_credit"] = rhu(component["crafted_hours"], 2)
    touch(component)
    refresh_order_derived(order)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    return component


def zone_has_disallowed_predecessor(order, project):
    work_front = order.get("zone_code")
    for activity in DB.all("trade_activities"):
        if activity.get("project_id") != project["id"]:
            continue
        if activity.get("activity_kind") not in OTHER_TRADE_KINDS:
            continue
        if activity.get("status") != "DISALLOWED":
            continue
        if work_front and activity.get("work_front_code") != work_front:
            continue
        return True
    return False


def set_install_status(component, body):
    target = body.get("install_status")
    if target is None:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    current = component.get("install_status")
    if (current, target) != ("LOADED", "SET"):
        fail("ERR_INVALID_PREFAB_TRANSITION")

    order = DB.find("prefab_orders", component.get("prefab_order_id"))
    if order is None:
        fail("ERR_PREFAB_ORDER_NOT_FOUND")
    project = DB.find("projects", order.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")

    if project.get("project_posture") == "FROZEN":
        fail("ERR_INVALID_PREFAB_TRANSITION")

    from orders import compute_releasable_status, refresh_order_derived
    refresh_order_derived(order)
    compute_releasable_status(order, project)
    if order.get("releasable_status") == "ENGINEERING_HOLD":
        fail("ERR_ENGINEERING_HOLD_ACTIVE")

    if zone_has_disallowed_predecessor(order, project):
        fail("ERR_INSTALL_SEQUENCE_VIOLATION")

    component["install_status"] = "SET"
    touch(component)

    from orders import refresh_order_derived as _r
    _r(order)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    recompute_all_releasable_quiet(project)
    return component


def recompute_all_releasable_quiet(project):
    from orders import recompute_all_releasable
    return recompute_all_releasable(project)


def filter_components(args):
    records = DB.all("prefab_components")
    for key in ("prefab_order_id", "rack_id", "takeoff_line_id", "predecessor_component_id", "install_status"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records