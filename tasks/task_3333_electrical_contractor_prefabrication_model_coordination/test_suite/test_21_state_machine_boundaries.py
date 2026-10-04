"""Work-package, component and model state-machine boundaries (queue B)."""
import pytest
from test_helpers import (
    NON_EXISTENT_UUID,
    PM,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    advance_fabrication,
    create_component,
    create_coordinated_model,
    create_draft_model,
    create_project,
    create_rack,
    fetch_component,
    fetch_order,
    fabricate_component,
    release_order_ok,
    setup_fabricated_order,
)


def _fabricated_order(project_code="P-3333-SM1"):
    return setup_fabricated_order(project_code=project_code)


# --------------------------------------------------------------------------
# state_machines / initial_states_on_creation
# --------------------------------------------------------------------------

def test_new_work_package_starts_on_its_three_initial_states(api, project_manager_headers):
    """PRD §3.3: "The shop dimension is `fabricate_status`, starting at `PLANNED` and
    moving through `RELEASED`, `IN_FABRICATION` and `FABRICATED` to the terminal
    `CANCELLED`."
    PRD §3.3: "The delivery dimension is `deliver_status`, starting at `AWAITING`".
    PRD §3.3: "The transport-booking dimension is `shipment_status`, starting at
    `PENDING`".

    Design: Corner/state_machines/initial_states_on_creation
    """
    project = create_project(project_code="P-3333-SM6")
    mv, _lines = create_coordinated_model(model_id="mdl-sm6")
    order = validate_success(
        api.create_prefab_order(
            {
                "project_id": project["id"], "model_version_id": mv["id"],
                "stage_code": "TRIM_OUT", "zone_code": "Z-9",
                "transport_kind": "MIXED_LOAD", "hoisting_window_id": "HW-SM6",
                "required_on_site_iso": "2026-11-20T00:00:00Z",
                "installation_window_start_iso": "2026-11-21T00:00:00Z",
                "fabricate_quantity": 1, "shop_utilisation_basis_pct": 0.50,
            },
            project_manager_headers,
        ),
        expected_status=201,
    )
    assert order["fabricate_status"] == "PLANNED"
    assert order["deliver_status"] == "AWAITING"
    assert order["shipment_status"] == "PENDING"
    assert order["hoisting_start_iso"] is None


# --------------------------------------------------------------------------
# state_machines / cancel_from_fabricated_is_invalid
# --------------------------------------------------------------------------

def test_cancel_is_refused_once_the_package_has_left_planned(api, project_manager_headers):
    """PRD §3.3: "A package can also be cancelled outright, but only from `PLANNED`
    on the shop dimension with `deliver_status` still `AWAITING`".
    PRD §2.4: "a transition that requires a specific from-state fails with
    `ERR_INVALID_PREFAB_TRANSITION` (HTTP 409) if the resource is not in it".

    Design: Corner/state_machines/cancel_from_fabricated_is_invalid
    """
    _project, _mv, _line, _rack, order, comps = _fabricated_order("P-3333-SM1B")

    validate_error(api.cancel_prefab_order(order["id"], project_manager_headers),
                   ApiErrorId.ERR_INVALID_PREFAB_TRANSITION)

    after = fetch_order(order["id"])
    assert after["fabricate_status"] == "FABRICATED"
    assert fetch_component(comps[0]["id"])["install_status"] != "SCRAPPED", (
        "the refused cancel fires no cascade"
    )


# --------------------------------------------------------------------------
# state_machines / manual_revert_from_fabricated_clears_the_frozen_window
# --------------------------------------------------------------------------

def test_revert_returns_the_package_to_planned_and_frees_its_resources(
        api, project_manager_headers):
    """PRD §3.3: "Reverting a `FABRICATED` package back to `PLANNED` requires
    `deliver_status` to be `AWAITING`, and it releases the laydown slot back to the
    free pool, clears `hoisting_start_iso`, `hoisting_end_iso` and
    `release_to_shop_iso` to null".
    PRD §2.10: "The craft-hours balance `craft_hours_balance` is unchanged when a
    fabricated work package is reverted to planned".

    Design: Corner/state_machines/manual_revert_from_fabricated_clears_the_frozen_window
    """
    _project, _mv, _line, _rack, order, comps = _fabricated_order("P-3333-SM2")
    assert order["hoisting_start_iso"] is not None

    reverted = validate_success(
        api.ressue_prefab_order(order["id"], project_manager_headers))
    assert reverted["fabricate_status"] == "PLANNED"
    assert reverted["hoisting_start_iso"] is None
    assert reverted["laydown_slot_index"] is None
    assert fetch_component(comps[0]["id"])["install_status"] == "PLANNED"


# --------------------------------------------------------------------------
# state_machines / rework_job_reopen_returns_component_to_rework
# --------------------------------------------------------------------------

def test_rework_job_transition_on_a_missing_job_is_refused(api, shop_foreman_headers):
    """PRD §2.8: "then every other referenced entity id, meaning a worker, trade
    activity, crew day, rack, takeoff line, foreman or revision-impact reference
    (`ERR_REFERENCED_ENTITY_NOT_FOUND`, HTTP 404)".
    PRD §2.4: "The service never applies a partial mutation: if any precondition of
    an operation fails, no field of the target resource, and no cascaded field of any
    related resource, is changed."

    Design: Corner/state_machines/rework_job_reopen_returns_component_to_rework
    """
    project, _mv, _line, _rack, order, comps = _fabricated_order("P-3333-SM3")
    before = fetch_component(comps[0]["id"])["install_status"]

    validate_error(
        api.set_rework_job_status(
            NON_EXISTENT_UUID, {"status": "IN_PROGRESS", "resolution": "OPENED"},
            shop_foreman_headers,
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
    )
    assert fetch_component(comps[0]["id"])["install_status"] == before, (
        "the refused call fires no cascade on the component"
    )
    listed = api.list_rework_jobs(shop_foreman_headers, {"project_id": project["id"]})
    assert listed.json()["meta"]["total_count"] == 0


# --------------------------------------------------------------------------
# state_machines / model_coordinate_requires_non_empty_extraction
# --------------------------------------------------------------------------

def test_coordinating_an_empty_extraction_set_is_refused(api, model_coordinator_headers):
    """PRD §3.1: "Coordinating the version — the act of freezing it as the model
    everyone will take quantities from — requires that the version's extraction set
    is not empty: `zone_quantity_total` must be at least 1 and `empty_takeoff` must
    be false, otherwise the request is refused with
    `ERR_MODEL_QUANTITY_UNRESOLVED` (HTTP 409)".

    Design: Corner/state_machines/model_coordinate_requires_non_empty_extraction
    """
    create_project(project_code="P-3333-SM4")
    model = create_draft_model(model_id="mdl-sm4", revision_letter="A")

    validate_error(api.coordinate_model_version(model["id"], model_coordinator_headers),
                   ApiErrorId.ERR_MODEL_QUANTITY_UNRESOLVED)

    after = validate_success(api.get_model_version(model["id"], model_coordinator_headers))
    assert after["status"] == "DRAFT"
    assert after["coordinated_at_iso"] is None
    assert after["empty_takeoff"] is True


# --------------------------------------------------------------------------
# state_machines / prefab_component_terminal_state_lockdown
# --------------------------------------------------------------------------

def test_set_component_cannot_be_moved_again(api, install_foreman_headers):
    """PRD §3.4: "The install dimension is a single state machine over
    `install_status` with members `PLANNED`, `FABRICATED`, `LOADED`, `SET`, `REWORK`
    and `SCRAPPED`, starting at `PLANNED` and terminating at `SET`."
    PRD §2.4: "a resource in a terminal condition for that dimension cannot be moved
    out of it".

    Design: Corner/state_machines/prefab_component_terminal_state_lockdown
    """
    from test_helpers.fixtures import setup_set_component
    _project, _mv, _line, _rack, _order, comp = setup_set_component(
        project_code="P-3333-SM5")
    assert comp["install_status"] == "SET"

    validate_error(
        api.set_component_install_status(comp["id"], {"install_status": "SET"},
                                         install_foreman_headers),
        ApiErrorId.ERR_INVALID_PREFAB_TRANSITION,
    )
    assert fetch_component(comp["id"])["install_status"] == "SET"