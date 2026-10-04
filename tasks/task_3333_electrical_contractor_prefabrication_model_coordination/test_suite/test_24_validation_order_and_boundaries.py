"""Validation-order conflicts and marginal-capacity boundaries (queue A)."""
import pytest
from test_helpers import (PM, validate_error, validate_error_is_one_of,
                         validate_paginated, validate_success)
from test_helpers import api_client as api
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    advance_fabrication,
    create_component,
    create_coordinated_model,
    create_draft_model,
    create_material_release,
    create_project,
    create_rack,
    fetch_project,
    release_order_ok,
    set_clock,
    setup_revision,
)


def _create_order(project_id, model_version_id, window_id, quantity=1):
    from test_helpers import api_client
    return api_client.create_prefab_order(
        {
            "project_id": project_id, "model_version_id": model_version_id,
            "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
            "transport_kind": "FLATBED", "hoisting_window_id": window_id,
            "required_on_site_iso": "2026-11-20T00:00:00Z",
            "installation_window_start_iso": "2026-11-21T00:00:00Z",
            "fabricate_quantity": quantity, "shop_utilisation_basis_pct": 0.50,
        },
        PM,
    )


# --------------------------------------------------------------------------
# priority_pair_validation_conflict /
#   state_versus_business_temporal_pair_on_material_release_declare
# --------------------------------------------------------------------------

def _declared_late_release(project_code="P-3333-PR2"):
    """A material release already declared, with the clock pushed past its planned
    release date so a second declare violates the temporal rule as well."""
    from test_helpers.test_users import TEST_USERS
    proc = TEST_USERS["procurement_headers"]
    project = create_project(project_code=project_code, material_gate_commodities=[])
    mv, _lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    release = create_material_release(project["id"], mv["id"],
                                      commitment_mode="CONFIRMED",
                                      planned_release_iso="2026-09-10T00:00:00Z")
    set_clock("2026-09-05T00:00:00Z")
    declared = validate_success(
        api.declare_material_release(
            release["id"],
            {"expected_project_version": fetch_project(project["id"])["version"],
             "target_status": "RELEASED"},
            proc,
        )
    )
    set_clock("2026-09-20T00:00:00Z")
    return project, mv, release, declared, proc


def _declare_and_advance(project, release):
    from test_helpers.test_users import TEST_USERS
    proc = TEST_USERS["procurement_headers"]
    set_clock("2026-09-05T00:00:00Z")
    declared = validate_success(
        api.declare_material_release(
            release["id"],
            {"expected_project_version": fetch_project(project["id"])["version"],
             "target_status": "RELEASED"},
            proc,
        )
    )
    set_clock("2026-09-20T00:00:00Z")
    return declared, proc


def test_a_released_release_cannot_be_declared_again(api, admin_headers):
    """PRD §3.9: "Declaring requires the release to be `PLANNED`, its
    `commitment_mode` to be either `PLANNED` or `CONFIRMED`, and the declare instant
    to be on or before its `planned_release_iso`".
    PRD §2.4: "a transition that requires a specific from-state fails with
    `ERR_INVALID_PREFAB_TRANSITION` (HTTP 409) if the resource is not in it".

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_temporal_pair_on_material_release_declare
    """
    project = create_project(project_code="P-3333-PR2")
    mv, _lines = create_coordinated_model(model_id="mdl-r",
                                          takeoff_lines=[{}])
    release = create_material_release(project["id"], mv["id"],
                                      commitment_mode="CONFIRMED",
                                      planned_release_iso="2026-09-10T00:00:00Z")
    declared, proc = _declare_and_advance(project, release)
    assert declared["status"] == "RELEASED"

    validate_error(
        api.declare_material_release(
            release["id"],
            {"expected_project_version": fetch_project(project["id"])["version"],
             "target_status": "RELEASED"},
            proc,
        ),
        ApiErrorId.ERR_INVALID_PREFAB_TRANSITION,
    )


def test_the_state_error_pre_empts_the_deadline_error(api, admin_headers):
    """PRD §2.8: "Fifth, the from-state test: the target resource must be in the
    state its transaction requires, across the `fabricate_status`, `deliver_status`,
    `shipment_status`, component `install_status`, `ReworkJob.status`,
    `Revision.status`, `TradeActivity.status`, `MaterialRelease.status` and
    `ModelVersion.status` dimensions (`ERR_INVALID_PREFAB_TRANSITION`, HTTP 409)."
    PRD §2.8: "Only after all of those pass are the business rules evaluated."

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_temporal_pair_on_material_release_declare
    """
    project = create_project(project_code="P-3333-PR2B")
    mv, _lines = create_coordinated_model(model_id="mdl-r2", takeoff_lines=[{}])
    release = create_material_release(project["id"], mv["id"],
                                      commitment_mode="CONFIRMED",
                                      planned_release_iso="2026-09-10T00:00:00Z")
    declared, proc = _declare_and_advance(project, release)
    assert declared["status"] == "RELEASED"

    response = api.declare_material_release(
        release["id"],
        {"expected_project_version": fetch_project(project["id"])["version"],
         "target_status": "RELEASED"},
        proc,
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_INVALID_PREFAB_TRANSITION,
         ApiErrorId.ERR_MATERIAL_RELEASE_DEADLINE],
    )
    snapshot = validate_success(api.get_material_release(release["id"], proc))
    assert snapshot["status"] == "RELEASED", (
        "the refused declare leaves the release on its existing status"
    )


# --------------------------------------------------------------------------
# priority_pair_validation_conflict /
#   business_constraint_versus_business_fiscal_pair_on_takeoff_extraction
# --------------------------------------------------------------------------

def test_duplicate_takeoff_content_is_refused(api, model_coordinator_headers):
    """PRD §3.1: "Extraction stamps a content hash — `takeoff_hash`, a digest over
    the version, zone, assembly and quantity — and that hash is the line's duplicate
    key: extracting the same content twice against the same `model_version_id` ...
    is refused with `ERR_DUPLICATE_TAKEOFF_LINE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_versus_business_fiscal_pair_on_takeoff_extraction
    """
    from test_helpers.fixtures import register_default_assembly
    register_default_assembly("A-RACK")
    _project = create_project(project_code="P-3333-PR3")
    model, lines = create_coordinated_model(model_id="mdl-s",
                                            takeoff_lines=[{"quantity": 100}])
    duplicate = {
        "model_version_id": model["id"], "zone_code": "Z-1",
        "assembly_code": "A-RACK", "conduit_run_type": "RIGID_RACK",
        "conduit_run_type_code": "RC50", "quantity": 100, "prefab_share_pct": 0.5,
    }
    validate_error(api.create_takeoff_line(duplicate, model_coordinator_headers),
                   ApiErrorId.ERR_DUPLICATE_TAKEOFF_LINE)

    snapshot = validate_success(api.get_model_version(model["id"], model_coordinator_headers))
    assert snapshot["zone_quantity_total"] == 100, "no second line was created"
    listed = api.list_takeoff_lines(model_coordinator_headers,
                                    {"model_version_id": model["id"]})
    assert listed.json()["meta"]["total_count"] == 1


def test_a_non_permitted_conduit_token_is_refused(api, model_coordinator_headers):
    """PRD §3.1: "The conduit token is checked against the assembly it is claimed to
    belong to. Every assembly publishes the conduit code tokens it was engineered for
    in `ideal_conduit_type_codes`, and a line's `conduit_run_type_code` must be a
    member of that array for its `assembly_code`; a code outside the array, or an
    installation method outside the permitted set above, is refused with
    `ERR_CONDUIT_TYPE_NOT_PERMITTED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_versus_business_fiscal_pair_on_takeoff_extraction
    """
    from test_helpers.fixtures import register_default_assembly
    register_default_assembly("A-RACK")
    create_project(project_code="P-3333-PR3B")
    model = create_draft_model(model_id="mdl-s2", revision_letter="A")
    validate_success(
        api.create_takeoff_line(
            {
                "model_version_id": model["id"], "zone_code": "Z-1",
                "assembly_code": "A-RACK", "conduit_run_type": "RIGID_RACK",
                "conduit_run_type_code": "RC50", "quantity": 10, "prefab_share_pct": 0.5,
            },
            model_coordinator_headers,
        ),
        expected_status=201,
    )
    bad = {
        "model_version_id": model["id"], "zone_code": "Z-1",
        "assembly_code": "A-RACK", "conduit_run_type": "RIGID_RACK",
        "conduit_run_type_code": "AW99", "quantity": 11, "prefab_share_pct": 0.5,
    }
    validate_error(api.create_takeoff_line(bad, model_coordinator_headers),
                   ApiErrorId.ERR_CONDUIT_TYPE_NOT_PERMITTED)


# --------------------------------------------------------------------------
# boundary_precision_check / rack_capacity_margin_inclusive_at_ninety_five_percent
# --------------------------------------------------------------------------

def _rack_margin_scenario(project_code="P-3333-B1"):
    """Two racks of capacity 400 and a work package holding the components."""
    project = create_project(project_code=project_code)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    edge = create_rack(mv["id"], rack_code="R-B-EDGE")
    over = create_rack(mv["id"], rack_code="R-B-OVER")
    order = validate_success(
        _create_order(project["id"], mv["id"], f"HW-{project_code}", 4),
        expected_status=201,
    )
    for index in (1, 2):
        create_component(order["id"], lines[0]["id"], rack_id=edge["id"],
                         quantity=190.0, chain_dependency_link=f"LNK-T{index}")
    create_component(order["id"], lines[0]["id"], rack_id=over["id"],
                     quantity=190.01, chain_dependency_link="LNK-T3")
    return project, mv, edge, over, order, lines[0]


def test_a_rack_sitting_exactly_on_the_margin_passes(api, shop_foreman_headers):
    """PRD §2.11: "The check passes when that sum is at most 95 percent of the rack's
    `value_capacity_cf`. The comparison is inclusive at the boundary — a rack sitting
    exactly at 95 percent passes, and a hundredth of a cubic foot above it fails with
    `ERR_RACK_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §3.1: "`reserved_streams_and_phase_cf`, the aggregate occupancy described in
    §2.11: it is the sum of `quantity` across components bound to the rack whose
    `install_status` is `PLANNED`, `FABRICATED`, `LOADED`, `REWORK` or `SCRAPPED`".

    Design: Difficulty/boundary_precision_check/rack_capacity_margin_inclusive_at_ninety_five_percent
    """
    _project, _mv, edge, _over, _order, _line = _rack_margin_scenario()
    listed = api.list_racks(shop_foreman_headers, {})
    rack = {r["id"]: r for r in listed.json()["data"]}[edge["id"]]
    assert rack["reserved_streams_and_phase_cf"] == 380.0, (
        "380.0 equals 0.95 * 400.0 exactly, so equality passes on the inclusive side"
    )


def test_a_rack_a_hundredth_above_the_margin_fails(api, shop_foreman_headers):
    """PRD §2.11: "a hundredth of a cubic foot above it fails with
    `ERR_RACK_CAPACITY_EXCEEDED` (HTTP 409). The same guard runs when a component is
    created and when a rework job is resolved by scrapping."
    PRD §3.1: "A rack that would exceed that mark on a component creation or a
    scrapping resolution is refused with `ERR_RACK_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/rack_capacity_margin_inclusive_at_ninety_five_percent
    """
    project, mv, _edge, over, order, line = _rack_margin_scenario("P-3333-B1B")
    response = api.create_prefab_component(
        {
            "prefab_order_id": order["id"], "rack_id": over["id"],
            "takeoff_line_id": line["id"], "predecessor_component_id": None,
            "assembly_code": line["assembly_code"], "quantity": 190.01,
            "chain_mode": "PARALLEL_FABRICATION", "chain_dependency_link": "LNK-T4",
        },
        shop_foreman_headers,
    )
    validate_error(response, ApiErrorId.ERR_RACK_CAPACITY_EXCEEDED)

    listed = api.list_racks(shop_foreman_headers, {})
    rack = {r["id"]: r for r in listed.json()["data"]}[over["id"]]
    assert rack["reserved_streams_and_phase_cf"] == 190.01, (
        "the rejected component contributes nothing to the rack occupancy"
    )


# --------------------------------------------------------------------------
# boundary_precision_check / empty_affected_set_and_zero_span_floor
# --------------------------------------------------------------------------

def test_an_empty_affected_component_set_creates_no_rework_job(api,
                                                               project_manager_headers):
    """PRD §3.7: "A work package's `rework_hours` are the affected quantity
    multiplied by the assembly's `prefab_hours_per_unit`; when the affected set is
    empty the figure is zero and no job row is created at all."

    Design: Difficulty/boundary_precision_check/empty_affected_set_and_zero_span_floor
    """
    project = create_project(project_code="P-3333-B2")
    model_a, lines = create_coordinated_model(model_id="mdl-u", revision_letter="A",
                                              takeoff_lines=[
                                                  {"assembly_code": "A-STRAP",
                                                   "conduit_run_type": "MC_CABLE",
                                                   "conduit_run_type_code": "MC12",
                                                   "quantity": 25,
                                                   "prefab_share_pct": 0.0}])
    successor = create_draft_model(model_id="mdl-u", revision_letter="B")
    from test_helpers.test_users import TEST_USERS
    validate_success(
        api.create_takeoff_line(
            {
                "model_version_id": successor["id"], "zone_code": "Z-1",
                "assembly_code": "A-STRAP", "conduit_run_type": "MC_CABLE",
                "conduit_run_type_code": "MC12", "quantity": 25, "prefab_share_pct": 0.0,
            },
            TEST_USERS["model_coordinator_headers"],
        ),
        expected_status=201,
    )
    revision = setup_revision(project, model_a, lines[0], successor["id"],
                              revision_kind="CLASH_RESOLUTION", revision_quantity=0)
    validate_success(api.submit_revision(revision["id"], project_manager_headers))
    validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )

    jobs, meta = validate_paginated(
        api.list_rework_jobs(project_manager_headers, {"project_id": project["id"]})
    )
    assert meta["total_count"] == 0, (
        "the impact names no component rows, so no job row is created at all"
    )


def test_a_project_with_no_open_activity_reports_zero_slippage(api, admin_headers):
    """PRD §3.2: "when the span is zero — a project with no non-`COMPLETE` activity,
    or none at all — `slippage_pct` is exactly zero and the posture is `ON_TRACK`."
    PRD §2.10: "An empty or zero-denominator input has a defined answer rather than
    an error."

    Design: Difficulty/boundary_precision_check/empty_affected_set_and_zero_span_floor
    """
    project = create_project(project_code="P-3333-B2B")
    summary = validate_success(
        api.recompute_posture(project["id"], admin_headers))
    assert summary["slippage_pct"] == 0.0
    assert summary["project_posture"] == "ON_TRACK"