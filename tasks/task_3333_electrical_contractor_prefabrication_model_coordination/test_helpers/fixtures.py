"""Composite setup helpers for the prefabrication & model coordination service.

Every helper builds its preconditions from scratch through the public endpoints,
because the harness restarts the service before every individual test.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
PM = TEST_USERS["project_manager_headers"]
MC = TEST_USERS["model_coordinator_headers"]
SF = TEST_USERS["shop_foreman_headers"]
LOG = TEST_USERS["logistics_headers"]
PROC = TEST_USERS["procurement_headers"]
GF = TEST_USERS["general_foreman_headers"]
INSTALL = TEST_USERS["install_foreman_headers"]


def _ok(response, what):
    assert 200 <= response.status_code < 300, (
        f"Setup failed: {what} returned {response.status_code}: {response.text[:400]}"
    )
    return get_success_data(response)


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

def register_assembly(assembly: dict, headers=MC):
    """Register an assembly catalog row (falls back to the direct read path)."""
    response = api_client._request("POST", "/prefab/assemblies", dict(assembly), headers)
    if 200 <= response.status_code < 300:
        return get_success_data(response)
    return None


def register_default_assembly(code: str = None, **overrides):
    """Ensure the named assembly exists in the catalog; returns its definition."""
    key = code or F.DEFAULT_ASSEMBLY["assembly_code"]
    assembly = dict(F.ASSEMBLY_CATALOG.get(key, F.DEFAULT_ASSEMBLY))
    assembly.update(overrides)
    register_assembly(assembly)
    return assembly


def set_clock(to_iso8601: str, headers=ADMIN):
    return _ok(api_client.set_current_utc(to_iso8601, headers), f"set clock to {to_iso8601}")


# --------------------------------------------------------------------------
# Tier 1 — state progression
# --------------------------------------------------------------------------

def create_project(project_code="P-3333-GEN", **overrides):
    """Register a jobsite and return it. Defaults are a healthy ON_TRACK site."""
    payload = F.project_payload(project_code=project_code, **overrides)
    return _ok(api_client.create_project(payload, ADMIN), "create project")


def create_coordinated_model(revision_letter="A", model_id="mdl-gen",
                             takeoff_lines=None, register_assembly_row=True):
    """Create a model version, extract its lines and coordinate it.

    `takeoff_lines` is a list of takeoff payload overrides. Returns
    (model_version, [takeoff_line, ...]).
    """
    if register_assembly_row:
        for spec in takeoff_lines or [{}]:
            register_default_assembly(spec.get("assembly_code"))
    mv = _ok(
        api_client.create_model_version(
            F.model_version_payload(model_id=model_id, revision_letter=revision_letter),
            MC,
        ),
        "create model version",
    )
    lines = []
    for spec in takeoff_lines or [{}]:
        payload = F.takeoff_line_payload(model_version_id=mv["id"], **spec)
        lines.append(_ok(api_client.create_takeoff_line(payload, MC), "create takeoff line"))
    mv = _ok(
        api_client.coordinate_model_version(mv["id"], MC), "coordinate model version"
    )
    return mv, lines


def create_draft_model(revision_letter="A", model_id="mdl-gen"):
    """Register a DRAFT model version with no extraction set."""
    return _ok(
        api_client.create_model_version(
            F.model_version_payload(model_id=model_id, revision_letter=revision_letter),
            MC,
        ),
        "create model version",
    )


def create_rack(model_version_id, rack_code="R-GEN", zone_code="Z-1", **overrides):
    payload = F.rack_payload(
        model_version_id=model_version_id, rack_code=rack_code,
        zone_code=zone_code, **overrides
    )
    return _ok(api_client.create_rack(payload, MC), "create rack")


def create_worker(worker_code="W-GEN-1", classification="JOURNEYMAN", **overrides):
    payload = F.worker_payload(
        worker_code=worker_code, classification=classification, **overrides
    )
    return _ok(api_client.create_worker(payload, GF), "create worker")


def create_apprentice(worker_code="W-GEN-AP", apprentice_period=2, **overrides):
    payload = F.apprentice_payload(
        worker_code=worker_code, apprentice_period=apprentice_period, **overrides
    )
    return _ok(api_client.create_worker(payload, GF), "create apprentice")


def create_rate(jurisdiction_key="J1", classification="JOURNEYMAN",
                hourly_rate_cents=6800, burden_pct=0.42, **overrides):
    payload = F.trade_contract_rate_payload(
        jurisdiction_key=jurisdiction_key, classification=classification,
        hourly_rate_cents=hourly_rate_cents, burden_pct=burden_pct, **overrides
    )
    return _ok(api_client.create_trade_contract_rate(payload, ADMIN), "create rate row")


def create_activity(project_id, rate_id=None, **overrides):
    payload = F.trade_activity_payload(project_id=project_id, rate_id=rate_id, **overrides)
    return _ok(api_client.create_trade_activity(payload, GF), "create trade activity")


def set_activity_status(activity_id, status):
    return _ok(
        api_client.set_trade_activity_status(activity_id, {"status": status}, GF),
        f"set activity status {status}",
    )


def create_crew_day(project_id, worker_id, activity_id, foreman_id=None,
                    regular_hours=8.0, overtime_hours=0.0, report_sequence=1,
                    acknowledge_mode="FINAL", **overrides):
    payload = F.crew_day_payload(
        project_id=project_id, worker_id=worker_id,
        foreman_id=foreman_id or worker_id, trade_activity_id=activity_id,
        regular_hours=regular_hours, overtime_hours=overtime_hours,
        report_sequence=report_sequence, acknowledge_mode=acknowledge_mode,
        **overrides,
    )
    return _ok(api_client.create_crew_day(payload, GF), "create crew day")


def acknowledge_crew_day(crew_day):
    payload = {
        "expected_crew_day_version": crew_day["version"],
        "acknowledge_mode": "FINAL",
    }
    return _ok(
        api_client.acknowledge_crew_day(crew_day["id"], payload, GF),
        "acknowledge crew day",
    )


def create_component(prefab_order_id, takeoff_line_id, rack_id=None,
                     assembly_code=None, quantity=50, chain_mode="PARALLEL_FABRICATION",
                     chain_dependency_link="LNK-GEN", predecessor_component_id=None):
    payload = F.prefab_component_payload(
        prefab_order_id=prefab_order_id, takeoff_line_id=takeoff_line_id,
        rack_id=rack_id, assembly_code=assembly_code or F.DEFAULT_ASSEMBLY["assembly_code"],
        quantity=quantity, chain_mode=chain_mode,
        chain_dependency_link=chain_dependency_link,
        predecessor_component_id=predecessor_component_id,
    )
    return _ok(api_client.create_prefab_component(payload, SF), "create component")


def fabricate_component(component_id):
    return _ok(
        api_client.fabricate_prefab_component(component_id, SF), "fabricate component"
    )


def create_material_release(project_id, model_version_id, **overrides):
    payload = F.material_release_payload(
        project_id=project_id, model_version_id=model_version_id, **overrides
    )
    return _ok(api_client.create_material_release(payload, PROC), "create material release")


# --------------------------------------------------------------------------
# Tier 2 — entity hierarchy: project + coordinated model + rack + order
# --------------------------------------------------------------------------

def setup_project_with_model(project_code="P-3333-GEN", model_id="mdl-gen",
                             takeoff_lines=None, project_overrides=None,
                             register_assembly_row=True):
    """Project + coordinated model version + its takeoff lines.

    Returns (project, model_version, takeoff_lines).
    """
    project = create_project(project_code=project_code, **(project_overrides or {}))
    mv, lines = create_coordinated_model(
        model_id=model_id, takeoff_lines=takeoff_lines,
        register_assembly_row=register_assembly_row,
    )
    return project, mv, lines


def setup_order(project=None, model_version=None, takeoff_line=None,
                rack=None, n_components=1, component_quantity=100,
                chain_mode="PARALLEL_FABRICATION", component_overrides=None,
                **order_overrides):
    """A full work package hierarchy ready for a release attempt.

    Returns (project, model_version, takeoff_line, rack, order, [components]).
    """
    if project is None:
        project, model_version, lines = setup_project_with_model()
        takeoff_line = lines[0]
    if model_version is None:
        raise AssertionError("setup_order requires a model version")
    if takeoff_line is None:
        raise AssertionError("setup_order requires a takeoff line")
    if rack is None:
        rack = create_rack(model_version["id"], rack_code=order_overrides.pop(
            "rack_code", "R-GEN"), zone_code=order_overrides.get("zone_code", "Z-1"))

    payload = F.prefab_order_payload(
        project_id=project["id"], model_version_id=model_version["id"], **order_overrides
    )
    order = _ok(api_client.create_prefab_order(payload, PM), "create work package")

    components = []
    for index in range(n_components):
        spec = dict(component_overrides or {})
        link = spec.pop("chain_dependency_link", f"LNK-{index + 1}")
        components.append(
            create_component(
                order["id"], takeoff_line["id"],
                rack_id=spec.pop("rack_id", rack["id"] if rack else None),
                assembly_code=spec.pop("assembly_code", takeoff_line["assembly_code"]),
                quantity=spec.pop("quantity", component_quantity),
                chain_mode=spec.pop("chain_mode", chain_mode),
                chain_dependency_link=link,
                predecessor_component_id=spec.pop(
                    "predecessor_component_id",
                    components[index - 1]["id"] if index else None,
                ),
            )
        )
    return project, model_version, takeoff_line, rack, order, components


def release_order(order, expected_version=None, headers=PM):
    payload = {
        "expected_prefab_order_version": (
            expected_version if expected_version is not None else order["version"]
        )
    }
    return api_client.release_prefab_order(order["id"], payload, headers)


def release_order_ok(order, expected_version=None):
    return _ok(release_order(order, expected_version), "release work package")


def setup_released_order(**kwargs):
    """Full hierarchy through RELEASED. Returns
    (project, model_version, takeoff_line, rack, order, components)."""
    project, mv, line, rack, order, comps = setup_order(**kwargs)
    order = release_order_ok(order)
    return project, mv, line, rack, order, comps


# PRD §4 assigns PATCH /prefab-orders/{id}/fabrication-status to ShopForeman
# only; §2.1 makes the acting operator opaque, so the shared ShopForeman headers
# are the canonical identity for every shop-progress step.
SHOP = SF


def advance_fabrication(order, target="FABRICATED", headers=SHOP):
    """Walk the shop dimension from RELEASED to IN_FABRICATION or FABRICATED.

    Each step is applied only when the package is not already in the target
    state, so calling this twice is idempotent rather than a second (illegal)
    self-transition.
    """
    if (target in ("IN_FABRICATION", "FABRICATED")
            and order.get("fabricate_status") != "IN_FABRICATION"):
        order = _ok(
            api_client.set_fabrication_status(
                order["id"], {"fabricate_status": "IN_FABRICATION"}, headers),
            "move order to IN_FABRICATION",
        )
    if target == "FABRICATED" and order.get("fabricate_status") != "FABRICATED":
        order = _ok(
            api_client.set_fabrication_status(
                order["id"], {"fabricate_status": "FABRICATED"}, headers),
            "move order to FABRICATED",
        )
    return order


def setup_fabricated_order(component_quantity=100, n_components=1, **kwargs):
    """Full hierarchy through FABRICATED. Returns
    (project, model_version, takeoff_line, rack, order, components)."""
    project, mv, line, rack, order, comps = setup_released_order(
        n_components=n_components, component_quantity=component_quantity, **kwargs)
    order = advance_fabrication(order)
    comps = [get_success_data(api_client.get_prefab_component(c["id"], SF)) for c in comps]
    return project, mv, line, rack, order, comps


def setup_fabricated_component(**kwargs):
    """A released, in-fabrication order with its first component FABRICATED."""
    project, mv, line, rack, order, comps = setup_released_order(**kwargs)
    order = advance_fabrication(order, target="IN_FABRICATION")
    comp = fabricate_component(comps[0]["id"])
    return project, mv, line, rack, order, comp


# PRD §3.3: loading "requires ... the package's `required_on_site_iso` to fall
# inside its frozen hoisting window". For the default jobsite (power_on
# 2026-12-01) a FIRST_STAGE package holding one component freezes the window
# [2026-11-21, 2026-11-28), so the LOADED fixtures must book arrival inside it.
LOADED_REQUIRED_ON_SITE_ISO = "2026-11-25T00:00:00Z"


def setup_loaded_component(**kwargs):
    """Component driven all the way to LOADED (order deliver_status LOADED)."""
    kwargs.setdefault("required_on_site_iso", LOADED_REQUIRED_ON_SITE_ISO)
    project, mv, line, rack, order, comps = setup_released_order(**kwargs)
    # PRD §3.4: fabricating a component "requires the owning package to be in
    # `IN_FABRICATION` on the shop dimension", so the shop dimension only reaches
    # FABRICATED after the components have been built.
    order = advance_fabrication(order, target="IN_FABRICATION")
    for comp in comps:
        fabricate_component(comp["id"])
    order = advance_fabrication(order, target="FABRICATED")
    order = _ok(
        api_client.set_delivery_status(
            order["id"], {"deliver_status": "STAGED", "shipment_status": "STAGED"}, LOG),
        "stage order",
    )
    order = _ok(
        api_client.set_delivery_status(
            order["id"], {"deliver_status": "LOADED", "shipment_status": "LOADED"}, LOG),
        "load order",
    )
    comp = get_success_data(api_client.get_prefab_component(comps[0]["id"], SF))
    return project, mv, line, rack, order, comp


def setup_set_component(**kwargs):
    """Component driven to the terminal SET install status."""
    project, mv, line, rack, order, comp = setup_loaded_component(**kwargs)
    comp = _ok(
        api_client.set_component_install_status(comp["id"], {"install_status": "SET"}, INSTALL),
        "set component",
    )
    return project, mv, line, rack, order, comp


# --------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts for the revision / rework loop
# --------------------------------------------------------------------------

def setup_revision(project, model_version, takeoff_line, successor_version_id,
                   impact_keys=None, **overrides):
    """Raise a DRAFT revision against a model version."""
    payload = F.revision_payload(
        project_id=project["id"], model_version_id=model_version["id"],
        revised_version_id=successor_version_id,
        impact_keys=impact_keys if impact_keys is not None else [takeoff_line["takeoff_hash"]],
        **overrides,
    )
    return _ok(api_client.create_revision(payload, PM), "create revision")


def setup_revision_ready(project_code="P-3333-REV", with_fabricated_component=True,
                         **revision_overrides):
    """Project + coordinated version + fabricated order + SUBMITTED revision.

    PRD §3.7: "A revision can be submitted only from `DRAFT`, only when its
    `revised_version_id` names a model version whose zone quantity total is at
    least 1" — so the successor carries one extraction line before the submit,
    and approval (which "requires the revision to be `SUBMITTED`") is legal.

    Returns (project, model_a, successor_b, order, component, revision).
    """
    project = create_project(project_code=project_code)
    model_a, lines = create_coordinated_model(model_id=f"mdl-{project_code}", revision_letter="A")
    successor_b = create_draft_model(
        model_id=f"mdl-{project_code}", revision_letter="B")
    register_default_assembly()
    _ok(
        api_client.create_takeoff_line(
            F.takeoff_line_payload(model_version_id=successor_b["id"]), MC),
        "create successor takeoff line",
    )
    rack = create_rack(model_a["id"], rack_code="R-REV")
    order = _ok(
        api_client.create_prefab_order(
            F.prefab_order_payload(project_id=project["id"], model_version_id=model_a["id"]),
            PM),
        "create work package",
    )
    comp = create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                            quantity=100)
    order = release_order_ok(order)
    order = advance_fabrication(order, target="IN_FABRICATION")
    if with_fabricated_component:
        comp = fabricate_component(comp["id"])
    revision = setup_revision(
        project, model_a, lines[0], successor_b["id"], **revision_overrides)
    revision = _ok(api_client.submit_revision(revision["id"], PM), "submit revision")
    return project, model_a, successor_b, order, comp, revision


# --------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# --------------------------------------------------------------------------

def setup_crew_pair(project_code="P-3333-CREW", journeyman_hours=4.0,
                    apprentice_hours=5.0, planned_duration_days=5,
                    jurisdiction_key="J1", ratio_max=1.0, wait_max=1.0,
                    acknowledge=True, project_journeyman_hours=0.0):
    """An ACTIVE electrical activity served by one journeyman and one apprentice.

    PRD §3.6 refuses a crew-day report whose apprentice hours would push the
    project-wide apprentice total past `ratio_limit` x the project-wide
    journeyman total, so `project_journeyman_hours` books that many journeyman
    hours on a second activity of the same project. The reported crew can then
    breach its own activity's cap (which is what §3.5 suspends the activity on)
    while the project as a whole stays inside the agreement.

    Returns (project, rate, journeyman, apprentice, activity, jm_day, ap_day).
    """
    project = create_project(
        project_code=project_code, jurisdiction_key=jurisdiction_key)
    rate = create_rate(jurisdiction_key=jurisdiction_key, apprentice_ratio_max=ratio_max,
                       wait_ratio_max=wait_max)
    jm = create_worker(worker_code=f"{project_code}-JM",
                       home_jurisdiction_key=jurisdiction_key)
    ap = create_apprentice(worker_code=f"{project_code}-AP",
                           home_jurisdiction_key=jurisdiction_key)
    activity = create_activity(
        project["id"], rate_id=rate["id"], planned_duration_days=planned_duration_days)
    set_activity_status(activity["id"], "PERMITTED")
    activity = set_activity_status(activity["id"], "ACTIVE")

    if project_journeyman_hours:
        ballast_activity = create_activity(
            project["id"], rate_id=rate["id"], work_front_code="WF-BALLAST",
            bay_code="BAY-BALLAST", written_sequence_index=2,
            planned_duration_days=planned_duration_days)
        ballast_worker = create_worker(
            worker_code=f"{project_code}-JMB",
            home_jurisdiction_key=jurisdiction_key)
        create_crew_day(project["id"], ballast_worker["id"], ballast_activity["id"],
                        foreman_id=ballast_worker["id"],
                        regular_hours=project_journeyman_hours, report_sequence=1)

    jm_day = create_crew_day(project["id"], jm["id"], activity["id"],
                             foreman_id=jm["id"], regular_hours=journeyman_hours,
                             report_sequence=1)
    ap_day = create_crew_day(project["id"], ap["id"], activity["id"],
                             foreman_id=jm["id"], regular_hours=apprentice_hours,
                             report_sequence=2)
    if acknowledge:
        jm_day = acknowledge_crew_day(jm_day)
        ap_day = acknowledge_crew_day(ap_day)
    # Acknowledgment is what drives the ratio cascade on the activity (PRD §3.5),
    # so the fixture hands back the live row rather than the creation-time
    # snapshot taken before the crew days were reported.
    activity = next(
        row for row in _paginated(api_client.list_trade_activities(GF, {}))[0]
        if row["id"] == activity["id"]
    )
    return project, rate, jm, ap, activity, jm_day, ap_day


def setup_balanced_crew_pair(project_code="P-3333-BAL", hours=4.0, **kwargs):
    """A crew whose apprentice hours land exactly on the ratio cap (zero excess)."""
    return setup_crew_pair(project_code=project_code, journeyman_hours=hours,
                           apprentice_hours=hours, **kwargs)


def setup_slippage(project_code="P-3333-SLIP", planned_duration_days=15,
                   clock_iso="2026-11-03T00:00:00Z", ladder=None, **project_overrides):
    """Project with a single non-COMPLETE activity and the clock pushed past it.

    Returns (project, activity, rate). The posture is recomputed from the clock.
    """
    ladder_overrides = {}
    if ladder:
        ladder_overrides["posture_thresholds"] = ladder
    project = create_project(
        project_code=project_code, **{**ladder_overrides, **project_overrides})
    rate = create_rate(jurisdiction_key=project["jurisdiction_key"])
    activity = create_activity(
        project["id"], rate_id=rate["id"], planned_duration_days=planned_duration_days)
    set_clock(clock_iso)
    project = _ok(
        api_client.recompute_posture(project["id"], ADMIN), "recompute posture")
    return project, activity, rate


def setup_posture_hierarchy(project_code="P-3333-POST", planned_duration_days=15,
                            ladder=None, clock_iso="2026-11-03T00:00:00Z",
                            laydown_slots=2, **project_overrides):
    """Project + activity + coordinated model + rack + PLANNED work package,
    with the clock pushed so the posture ladder can be walked.

    Returns (project, activity, model_version, rack, order).
    """
    ladder_overrides = {}
    if ladder:
        ladder_overrides["posture_thresholds"] = ladder
    project = create_project(
        project_code=project_code, laydown_slots=laydown_slots,
        **{**ladder_overrides, **project_overrides})
    rate = create_rate(jurisdiction_key=project["jurisdiction_key"])
    activity = create_activity(
        project["id"], rate_id=rate["id"], planned_duration_days=planned_duration_days)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code="R-POST")
    order = _ok(
        api_client.create_prefab_order(
            F.prefab_order_payload(project_id=project["id"], model_version_id=mv["id"]),
            PM),
        "create work package",
    )
    create_component(order["id"], lines[0]["id"], rack_id=rack["id"], quantity=100)
    set_clock(clock_iso)
    project = _ok(api_client.recompute_posture(project["id"], ADMIN), "recompute posture")
    return project, activity, mv, rack, order


# --------------------------------------------------------------------------
# Convenience reads
# --------------------------------------------------------------------------

def fetch_project(project_id, headers=ADMIN):
    return get_success_data(api_client.get_project(project_id, headers))


def fetch_order(order_id, headers=PM):
    return get_success_data(api_client.get_prefab_order(order_id, headers))


def fetch_component(component_id, headers=SF):
    return get_success_data(api_client.get_prefab_component(component_id, headers))


def fetch_ledger(project_id, headers=GF):
    data, _meta = _paginated(api_client.list_compliance_ledger(
        headers, {"project_id": project_id}))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def fetch_ledger_row(project_id, worker_id, headers=GF):
    for row in fetch_ledger(project_id, headers):
        if row.get("worker_id") == worker_id:
            return row
    return None


def list_rework_jobs(project_id, headers=PM):
    return _paginated(api_client.list_rework_jobs(headers, {"project_id": project_id}))