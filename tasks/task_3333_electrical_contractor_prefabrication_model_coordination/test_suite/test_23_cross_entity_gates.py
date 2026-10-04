"""Cross-entity gates, throughput rules and procurement timing (queues A+B)."""
import pytest
from test_helpers import (
    GF,
    LOG,
    PM,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    validate_paginated,
)
from test_helpers import api_client as api
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    advance_fabrication,
    create_activity,
    create_apprentice,
    create_component,
    create_coordinated_model,
    create_crew_day,
    acknowledge_crew_day,
    create_material_release,
    create_project,
    create_rack,
    create_rate,
    create_worker,
    fetch_component,
    fetch_order,
    fetch_project,
    fabricate_component,
    release_order,
    release_order_ok,
    set_activity_status,
    set_clock,
    setup_posture_hierarchy,
)


def _create_order(project_id, model_version_id, window_id="HW-GEN", quantity=1):
    return validate_success(
        api_create_order(project_id, model_version_id, window_id, quantity),
        expected_status=201,
    )


def api_create_order(project_id, model_version_id, window_id, quantity,
                     project_manager_headers=None, required_on_site="2026-11-25T00:00:00Z"):
    from test_helpers import api_client
    return api_client.create_prefab_order(
        {
            "project_id": project_id, "model_version_id": model_version_id,
            "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
            "transport_kind": "FLATBED", "hoisting_window_id": window_id,
            "required_on_site_iso": required_on_site,
            "installation_window_start_iso": "2026-11-21T00:00:00Z",
            "fabricate_quantity": quantity, "shop_utilisation_basis_pct": 0.50,
        },
        PM,
    )


def _logger_sync_pair(project_code="P-3333-C1"):
    """Two electrical activities where the second's permit names the first."""
    project = create_project(project_code=project_code)
    rate = create_rate(jurisdiction_key=project["jurisdiction_key"],
                       classification="FOREMAN", hourly_rate_cents=8200, burden_pct=0.45)
    first = create_activity(project["id"], rate_id=rate["id"], work_front_code="WF-1",
                            bay_code="BAY-A", written_sequence_index=1,
                            planned_duration_days=5)
    second = create_activity(project["id"], rate_id=rate["id"], work_front_code="WF-1",
                             bay_code="BAY-B", written_sequence_index=2,
                             planned_start_iso="2026-10-10T00:00:00Z",
                             planned_duration_days=5, permit_id=first["id"])
    return project, first, second


# --------------------------------------------------------------------------
# cross_entity_state_dependency / dependent_activity_permit_gated_by_predecessor
# --------------------------------------------------------------------------

def test_permit_is_refused_while_the_permitting_activity_is_planned(api,
                                                                    general_foreman_headers):
    """PRD §3.5: "Admission to `PERMITTED` requires that the activity's permitting
    activity is either unspecified or itself `COMPLETE`".
    PRD §3.5: "A blocked request is refused with `ERR_INSTALL_SEQUENCE_VIOLATION`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/dependent_activity_permit_gated_by_predecessor_activity_state
    """
    _project, _first, second = _logger_sync_pair()
    validate_error(
        api.set_trade_activity_status(second["id"], {"status": "PERMITTED"},
                                      general_foreman_headers),
        ApiErrorId.ERR_INSTALL_SEQUENCE_VIOLATION,
    )
    listed = api.list_trade_activities(general_foreman_headers, {})
    row = {r["id"]: r for r in listed.json()["data"]}[second["id"]]
    assert row["status"] == "PLANNED", (
        "the dependent activity stays planned while its permitting activity is planned"
    )


def test_permit_is_granted_once_the_predecessor_is_complete(api, general_foreman_headers):
    """PRD §3.5: "Admission to `PERMITTED` requires that the activity's permitting
    activity is either unspecified or itself `COMPLETE`".
    PRD §2.9: "the activity whose permit unblocks it through `permit_id` — the last
    of which is a self-referential link between two activities, forming the
    installation-sequence chain."

    Design: Difficulty/cross_entity_state_dependency/dependent_activity_permit_gated_by_predecessor_activity_state
    """
    _project, first, second = _logger_sync_pair("P-3333-C1B")
    set_activity_status(first["id"], "PERMITTED")
    set_activity_status(first["id"], "ACTIVE")
    set_activity_status(first["id"], "COMPLETE")

    granted = validate_success(
        api.set_trade_activity_status(second["id"], {"status": "PERMITTED"},
                                      general_foreman_headers)
    )
    assert granted["status"] == "PERMITTED", (
        "the dependency is resolved through the permitting activity's state"
    )


# --------------------------------------------------------------------------
# cross_entity_state_dependency / order_release_gated_by_project_posture_tier
# --------------------------------------------------------------------------

def _hold_tier_hierarchy(project_code="P-3333-C2", clock_iso="2026-11-03T00:00:00Z",
                         ladder=None):
    return setup_posture_hierarchy(project_code=project_code, planned_duration_days=15,
                                   ladder=ladder, clock_iso=clock_iso)


def test_release_is_refused_while_the_project_is_on_hold(api, admin_headers,
                                                         project_manager_headers):
    """PRD §3.3: "the project's posture must be `ON_TRACK`, `RELEASE_PENDING` or
    `RECOVERY_MODE` — `HOLD` and `FROZEN` both block release."
    PRD §3.2: "When it is at most `SLIP_HOLD_AT` the posture is `RECOVERY_MODE`."
    PRD §3.2: "When it is at most `SLIP_FREEZE_AT` the posture is `HOLD`."

    Design: Difficulty/cross_entity_state_dependency/order_release_gated_by_project_posture_tier
    """
    # slippage is 18 days of shortfall over a 15 day span = 1.2, so the freeze
    # tier must sit at or above 1.2 for the ladder to land on HOLD (PRD §3.2:
    # "When it is at most `SLIP_FREEZE_AT` the posture is `HOLD`.")
    project, _activity, _mv, _rack, order = _hold_tier_hierarchy(
        ladder={"SLIP_RELEASE_AT": 0.02, "SLIP_RECOVERY_AT": 0.05,
                "SLIP_HOLD_AT": 0.10, "SLIP_FREEZE_AT": 1.50})
    assert project["slippage_pct"] == 1.2
    assert project["project_posture"] == "HOLD"

    error = validate_error_is_one_of(
        release_order(order), [ApiErrorId.ERR_INVALID_PREFAB_TRANSITION]
    )
    assert error == "ERR_INVALID_PREFAB_TRANSITION"
    assert fetch_order(order["id"])["fabricate_status"] == "PLANNED"


def test_release_succeeds_after_the_posture_returns_on_track(api, admin_headers,
                                                             project_manager_headers):
    """PRD §3.3: "the project's posture must be `ON_TRACK`, `RELEASE_PENDING` or
    `RECOVERY_MODE` — `HOLD` and `FROZEN` both block release."
    PRD §3.2: "When `slippage_pct` is at most `SLIP_RELEASE_AT` the posture is
    `ON_TRACK`."
    PRD §3.2: "Activities in status `COMPLETE` are excluded from both the span and
    the shortfall, so completing work shortens the span as well as removing itself
    from the shortfall."

    Design: Difficulty/cross_entity_state_dependency/order_release_gated_by_project_posture_tier
    """
    project, activity, _mv, _rack, order = _hold_tier_hierarchy(
        project_code="P-3333-C2B",
        ladder={"SLIP_RELEASE_AT": 0.02, "SLIP_RECOVERY_AT": 0.05,
                "SLIP_HOLD_AT": 0.10, "SLIP_FREEZE_AT": 1.50})
    assert project["project_posture"] == "HOLD"

    set_activity_status(activity["id"], "PERMITTED")
    set_activity_status(activity["id"], "ACTIVE")
    set_activity_status(activity["id"], "COMPLETE")

    after = fetch_project(project["id"])
    assert after["slippage_pct"] == 0.0, (
        "the completed activity leaves neither span nor shortfall behind"
    )
    assert after["project_posture"] == "ON_TRACK"

    released = release_order_ok(fetch_order(order["id"]))
    assert released["fabricate_status"] == "RELEASED"


# --------------------------------------------------------------------------
# cross_entity_state_dependency / component_set_gated_by_project_freeze_tier
# --------------------------------------------------------------------------

def _loaded_component_in_frozen_project(project_code="P-3333-C3", admin_headers=None):
    """A LOADED component under a project whose posture has crossed into FROZEN."""
    from test_helpers.test_users import TEST_USERS
    admin_headers = admin_headers or TEST_USERS["admin_headers"]
    project = create_project(project_code=project_code)
    rate = create_rate(jurisdiction_key=project["jurisdiction_key"])
    activity = create_activity(project["id"], rate_id=rate["id"],
                               planned_duration_days=10)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    order = _create_order(project["id"], mv["id"], f"HW-{project_code}", 1)
    comp = create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                            quantity=100)
    order = release_order_ok(order)
    order = advance_fabrication(order, target="IN_FABRICATION")
    fabricate_component(comp["id"])
    order = advance_fabrication(order, target="FABRICATED")
    for status in ("STAGED", "LOADED"):
        order = validate_success(
            api.set_delivery_status(
                order["id"], {"deliver_status": status, "shipment_status": status},
                LOG),
            expected_status=200,
        )
    set_clock("2026-10-31T00:00:00Z")
    project = validate_success(api.recompute_posture(project["id"], admin_headers))
    return project, activity, mv, order, comp


def test_project_enter_frozen_on_a_deep_shortfall(api, admin_headers):
    """PRD §3.2: "The critical path shortfall is the sum, over those same
    activities, of the number of whole days by which the logical clock has passed the
    activity's planned finish".
    PRD §3.2: "Otherwise the posture is `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/component_set_gated_by_project_freeze_tier
    """
    project, _activity, _mv, order, comp = _loaded_component_in_frozen_project(
        "P-3333-C3A", admin_headers)
    assert project["slippage_pct"] == 2.0, (
        "a 20 day shortfall over a 10 day span is two point zero"
    )
    assert project["project_posture"] == "FROZEN"
    assert fetch_component(comp["id"])["install_status"] == "LOADED"


def test_component_set_is_refused_while_the_project_is_frozen(api, admin_headers,
                                                              install_foreman_headers):
    """PRD §3.4: "Setting a component in the field is the InstallForeman's action, and
    it requires the component to be `LOADED`, the project's posture not to be
    `FROZEN`, and the component's zone to have no pending disallowed predecessor
    activity under the written installation sequence agreement".
    PRD §2.4: "The service never applies a partial mutation: if any precondition of
    an operation fails, no field of the target resource, and no cascaded field of any
    related resource, is changed."

    Design: Difficulty/cross_entity_state_dependency/component_set_gated_by_project_freeze_tier
    """
    project, _activity, _mv, order, comp = _loaded_component_in_frozen_project(
        "P-3333-C3B", admin_headers)
    assert project["project_posture"] == "FROZEN"

    validate_error_is_one_of(
        api.set_component_install_status(comp["id"], {"install_status": "SET"},
                                         install_foreman_headers),
        [ApiErrorId.ERR_ENGINEERING_HOLD_ACTIVE, ApiErrorId.ERR_INVALID_PREFAB_TRANSITION],
    )
    assert fetch_component(comp["id"])["install_status"] == "LOADED"
    assert fetch_project(project["id"])["completed_value_cents"] == 0


# --------------------------------------------------------------------------
# transitive_cascade / revision_approval_to_rework_to_order_gate_to_project_posture
# --------------------------------------------------------------------------

def _approved_revision_scenario(project_code="P-3333-CAS1"):
    """A fabricated component, its released package and a DRAFT revision naming the
    component's takeoff hash, approved by the caller."""
    from test_helpers.fixtures import setup_revision_ready
    return setup_revision_ready(project_code=project_code)


def test_approval_moves_the_named_component_into_rework(api, project_manager_headers):
    """PRD §3.7: "each naming impact drives the affected `FABRICATED` component to
    `REWORK` and creates an open rework job for it".
    PRD §3.7: "a `FABRICATED` component whose assembly is named by an approved
    revision moves to `REWORK`".

    Design: Difficulty/transitive_cascade/revision_approval_to_rework_to_order_gate_to_project_posture
    """
    _project, model_a, _successor, _order, comp, revision = _approved_revision_scenario()
    validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    assert fetch_component(comp["id"])["install_status"] == "REWORK"

    jobs, meta = validate_paginated(
        api.list_rework_jobs(project_manager_headers, {"prefab_component_id": comp["id"]})
    )
    assert meta["total_count"] == 1
    assert jobs[0]["status"] == "OPEN", "an open rework job is created for the naming impact"


def test_the_owning_package_recomputes_its_release_gate(api, project_manager_headers):
    """PRD §3.7: "the owning packages' `rework_order_count` and `releasable_status`
    are recomputed".
    PRD §3.7: "`ENGINEERING_HOLD` is written when the project posture is `ON_TRACK`
    or `RELEASE_PENDING` and `rework_order_count` is greater than zero".

    Design: Difficulty/transitive_cascade/revision_approval_to_rework_to_order_gate_to_project_posture
    """
    _project, model_a, _successor, order, _comp, revision = _approved_revision_scenario(
        "P-3333-CAS1B")
    validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    after = fetch_order(order["id"])
    assert after["rework_order_count"] == 1, (
        "the mutation of the component recomputes the owning package in turn"
    )
    assert after["releasable_status"] == "ENGINEERING_HOLD"


def test_the_project_flag_reacts_to_the_non_terminal_revision(api, project_manager_headers):
    """PRD §3.2: "`fabricated_revision_active`, which is true while the project has a
    revision that affects fabricated content and has not reached any of the terminal
    members `APPROVED`, `REJECTED` or `SUPERSEDED`."
    PRD §3.7: "`engineering_hold` is true while the revision's status is not a member
    of the set `APPROVED`, `REJECTED`, `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/revision_approval_to_rework_to_order_gate_to_project_posture
    """
    project, model_a, _successor, _order, _comp, revision = _approved_revision_scenario(
        "P-3333-CAS1C")
    assert fetch_project(project["id"])["fabricated_revision_active"] is True, (
        "the revision is non-terminal while it is still in DRAFT"
    )
    assert revision["engineering_hold"] is True

    approve = validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    assert approve["engineering_hold"] is False


def test_the_project_posture_is_re_derived_after_the_cascade(api, admin_headers,
                                                             project_manager_headers):
    """PRD §3.7: "the project's posture is recomputed through the ladder".
    PRD §3.2: "when the span is zero — a project with no non-`COMPLETE` activity, or
    none at all — `slippage_pct` is exactly zero and the posture is `ON_TRACK`."

    Design: Difficulty/transitive_cascade/revision_approval_to_rework_to_order_gate_to_project_posture
    """
    project, model_a, _successor, _order, _comp, revision = _approved_revision_scenario(
        "P-3333-CAS1D")
    validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    summary = fetch_project(project["id"])
    assert summary["slippage_pct"] == 0.0
    assert summary["project_posture"] == "ON_TRACK"
    superseded = validate_success(
        api.get_model_version(model_a["id"], project_manager_headers))
    assert superseded["status"] == "SUPERSEDED"


# --------------------------------------------------------------------------
# transitive_cascade / material_release_declaration_to_order_gate_to_shop_eligibility
# --------------------------------------------------------------------------

def _gated_order(project_code="P-3333-CAS2"):
    """A PLANNED package whose project gates on an undeclared commodity."""
    project = create_project(project_code=project_code,
                             material_gate_commodities=["MC_CABLE"])
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    order = _create_order(project["id"], mv["id"], f"HW-{project_code}", 1)
    create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                     quantity=100)
    return project, mv, order


def test_an_undeclared_gate_commodity_holds_the_package(api, project_manager_headers):
    """PRD §3.9: "A work package whose gate commodity is a member of the owning
    project's `material_gate_commodities` cannot be released while that commodity has
    no release in the declared-for-procurement state; the package's
    `releasable_status` reads `MATERIAL_HOLD` and the release is refused with
    `ERR_MATERIAL_HOLD_ACTIVE` (HTTP 409)."

    Design: Difficulty/transitive_cascade/material_release_declaration_to_order_gate_to_shop_eligibility
    """
    _project, _mv, order = _gated_order()
    assert fetch_order(order["id"])["releasable_status"] == "MATERIAL_HOLD"
    validate_error(release_order(order), ApiErrorId.ERR_MATERIAL_HOLD_ACTIVE)
    assert fetch_order(order["id"])["fabricate_status"] == "PLANNED"


def test_declaring_the_commodity_opens_the_release_gate(api, project_manager_headers,
                                                        procurement_headers):
    """PRD §3.9: "The hold lifts as soon as the commodity's release is declared, at
    which point the affected packages' `releasable_status` recomputes from
    `MATERIAL_HOLD` to `READY`."
    PRD §3.9: "On success the release becomes `RELEASED`, its
    `declared_for_procurement` flag recomputes to true".
    PRD §3.9: "the release is refused with `ERR_MATERIAL_HOLD_ACTIVE` (HTTP 409)."

    Design: Difficulty/transitive_cascade/material_release_declaration_to_order_gate_to_shop_eligibility
    """
    project, mv, order = _gated_order("P-3333-CAS2B")
    release = create_material_release(project["id"], mv["id"], material_commodity="MC_CABLE")

    declared = validate_success(
        api.declare_material_release(
            release["id"],
            {"expected_project_version": fetch_project(project["id"])["version"],
             "target_status": "RELEASED"},
            procurement_headers,
        )
    )
    assert declared["status"] == "RELEASED"
    assert declared["declared_for_procurement"] is True

    # PRD §3.3 fixes the precedence: absent an engineering or material hold,
    # "`PERMITTED` is written when the posture is `RELEASE_PENDING`, `ALLOWED`
    # when the posture is `ON_TRACK` and every gate passes". This jobsite has no
    # non-COMPLETE activity, so its posture is ON_TRACK and the declared
    # commodity leaves the gate at the ON_TRACK value.
    assert fetch_order(order["id"])["releasable_status"] == "ALLOWED", (
        "the gate lifts out of MATERIAL_HOLD once the commodity is declared"
    )
    released = release_order_ok(fetch_order(order["id"]))
    assert released["fabricate_status"] == "RELEASED"