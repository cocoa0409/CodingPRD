"""Resource booking guards: hoisting windows and laydown slots (queue A)."""
import pytest
from test_helpers import PM, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_component,
    create_coordinated_model,
    create_project,
    create_rack,
    fetch_order,
    release_order,
    release_order_ok,
)


def _order_payload(project_id, model_version_id, window_id, quantity=1,
                   required_on_site="2026-11-20T00:00:00Z",
                   stage_code="FIRST_STAGE"):
    return {
        "project_id": project_id, "model_version_id": model_version_id,
        "stage_code": stage_code, "zone_code": "Z-1",
        "transport_kind": "FLATBED", "hoisting_window_id": window_id,
        "required_on_site_iso": required_on_site,
        "installation_window_start_iso": "2026-11-21T00:00:00Z",
        "fabricate_quantity": quantity, "shop_utilisation_basis_pct": 0.50,
    }


def _two_orders_same_window(project_code="P-3333-OV1", laydown_slots=4,
                            window_id="HW-OV1"):
    """Two work packages booked against the same hoisting window identity."""
    project = create_project(project_code=project_code, laydown_slots=laydown_slots)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    first = validate_success(
        api_create_order(project["id"], mv["id"], window_id), expected_status=201)
    create_component(first["id"], lines[0]["id"], rack_id=rack["id"],
                     quantity=100, chain_dependency_link="LNK-Z1")
    second = validate_success(
        api_create_order(project["id"], mv["id"], window_id), expected_status=201)
    create_component(second["id"], lines[0]["id"], rack_id=rack["id"],
                     quantity=100, chain_dependency_link="LNK-Z2")
    return project, mv, release_order_ok(first), second


def api_create_order(project_id, model_version_id, window_id,
                     stage_code="FIRST_STAGE"):
    from test_helpers import api_client
    return api_client.create_prefab_order(
        _order_payload(project_id, model_version_id, window_id,
                       stage_code=stage_code), PM)


# --------------------------------------------------------------------------
# resource_temporal_overlap / hoisting_window_frozen_overlap_on_same_window_id
# --------------------------------------------------------------------------

def test_first_release_freezes_a_forward_hoisting_window(api, project_manager_headers):
    """PRD §3.3: "The window's start `hoisting_start_iso` is the project's
    `power_on_iso` shifted earlier by the base day count plus the package's
    `assembly_count` multiplied by a rack staging duration factor of 3 and rounded
    up to whole days; the window's end `hoisting_end_iso` is the start shifted later
    by `hoisting_duration_days`."

    Design: Difficulty/resource_temporal_overlap/hoisting_window_frozen_overlap_on_same_window_id
    """
    _project, _mv, released, _second = _two_orders_same_window()
    assert released["hoisting_start_iso"] is not None
    assert released["hoisting_end_iso"] is not None
    assert released["hoisting_start_iso"] < released["hoisting_end_iso"], (
        "the frozen window is a forward half-open interval"
    )
    assert 1 <= released["hoisting_duration_days"] <= 10


def test_second_release_on_the_same_window_identity_is_refused(api, project_manager_headers):
    """PRD §2.11: "A hoisting window may not overlap. A proposed window — the
    half-open interval from `hoisting_start_iso` inclusive to `hoisting_end_iso`
    exclusive — must not overlap any already-frozen window booked under the same
    `hoisting_window_id`".
    PRD §2.4: "The service never applies a partial mutation: if any precondition of
    an operation fails, no field of the target resource, and no cascaded field of
    any related resource, is changed."

    Design: Difficulty/resource_temporal_overlap/hoisting_window_frozen_overlap_on_same_window_id
    """
    _project, _mv, _released, second = _two_orders_same_window()
    error = validate_error(
        release_order(second), ApiErrorId.ERR_HOISTING_WINDOW_CONFLICT
    )
    assert error["error_id"] == "ERR_HOISTING_WINDOW_CONFLICT"

    after = fetch_order(second["id"])
    assert after["hoisting_start_iso"] is None, (
        "the refusal is all-or-nothing and leaves no derived window behind"
    )
    assert after["laydown_slot_index"] is None
    assert after["fabricate_status"] == "PLANNED"


# --------------------------------------------------------------------------
# resource_temporal_overlap / laydown_slot_exclusive_end_boundary_across_orders
# --------------------------------------------------------------------------

def _capacity_one_scenario(project_code="P-3333-OV2"):
    """A project with a single laydown slot and two work packages.

    The two packages are booked under different `hoisting_window_id` values and
    different `stage_code` values, so their derived `hoisting_start_iso` dates
    differ and the hoisting-window guard of §2.11 is satisfied. Only the
    laydown-slot guard is left to fire — the hoisting test precedes it in the
    §2.8 business-rule order, so a shared window would mask the slot refusal.
    """
    project = create_project(project_code=project_code, laydown_slots=1)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    first = validate_success(
        api_create_order(project["id"], mv["id"], "HW-AA1"), expected_status=201)
    create_component(first["id"], lines[0]["id"], rack_id=rack["id"],
                     quantity=100, chain_dependency_link="LNK-Y1")
    second = validate_success(
        api_create_order(project["id"], mv["id"], "HW-AA2",
                         stage_code="SECOND_STAGE"), expected_status=201)
    create_component(second["id"], lines[0]["id"], rack_id=rack["id"],
                     quantity=100, chain_dependency_link="LNK-Y2")
    return project, mv, release_order_ok(first), second


def test_the_only_laydown_slot_is_occupied_until_delivery(api, project_manager_headers):
    """PRD §2.11: "A slot at an index between 1 and the project's `laydown_slots`
    counts as free when the window from the release instant inclusive to the
    delivery instant exclusive of every other non-terminal work package on the
    project is excluded."
    PRD §3.3: "`laydown_slot_index` is assigned as the lowest free slot index
    between 1 and the project's `laydown_slots`".

    Design: Difficulty/resource_temporal_overlap/laydown_slot_exclusive_end_boundary_across_orders
    """
    _project, _mv, released, _second = _capacity_one_scenario()
    assert released["laydown_slot_index"] == 1, (
        "the only slot is claimed because the order is not yet delivered"
    )
    assert released["fabricate_status"] == "RELEASED"


def test_second_release_with_no_free_slot_is_refused(api, project_manager_headers):
    """PRD §2.11: "If no such slot survives that exclusion the release fails with
    `ERR_LAYDOWN_SLOT_UNAVAILABLE` (HTTP 409); the assigned index is recorded on the
    order as `laydown_slot_index`."

    Design: Difficulty/resource_temporal_overlap/laydown_slot_exclusive_end_boundary_across_orders
    """
    _project, _mv, _released, second = _capacity_one_scenario(project_code="P-3333-OV2B")
    validate_error(release_order(second), ApiErrorId.ERR_LAYDOWN_SLOT_UNAVAILABLE)

    after = fetch_order(second["id"])
    assert after["laydown_slot_index"] is None
    assert after["fabricate_status"] == "PLANNED"