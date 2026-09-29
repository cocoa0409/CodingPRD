"""Which error surfaces when one request breaks two rules at once.

The API declares a normative rejection order, so a placement validation that is
both geometrically illegal and fired from a non-editable project must report the
state error, and a FIRM quote issuance that is both unsafe and over budget must
report the safety error.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_paginated_list,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ==========================================================================
# A VALIDATED deck plus an unattached DRAFT climber that overlaps its use zone
# ==========================================================================
def _setup_overlapping_draft_climber() -> dict:
    """One VALIDATED deck at x=700 and one DRAFT climber at x=900 in the same area.

    The deck's closed use zone is 517..883 and the climber's is 687..1113, so the
    two intervals overlap on 687..883.  The climber declares no attachment
    parent, so the attachment exemption cannot apply to the pair.
    """
    scenario = fx.setup_project_with_toddler_area()
    area_id = scenario["area"]["id"]
    scenario["deck_placement"] = fx.create_validated_placement(
        area_id,
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    scenario["climber_placement"] = fx.create_placement(
        area_id,
        scenario["climber"]["id"],
        color_choice="CRIMSON",
        x_start_cm=900,
        quantity=1,
    )
    return scenario


def test_use_zone_overlap_is_reported_while_the_project_is_still_editable():
    """Validating an unattached placement that overlaps a VALIDATED zone is refused with the overlap error.

    PRD: "Any overlap with another `VALIDATED` placement in the same area is refused with `ERR_USE_ZONE_OVERLAP` (HTTP 409), with exactly one exemption: a pair is exempt when one of the two is the other's attachment parent, because a slide bolted to its deck must by construction overlap that deck's zone."

    Design: Difficulty/priority_pair_validation_conflict/placement_validate_state_error_precedes_use_zone_overlap
    """
    scenario = _setup_overlapping_draft_climber()
    deck_placement = scenario["deck_placement"]
    climber_placement = scenario["climber_placement"]

    a.assert_use_zone(deck_placement, scenario["deck"])
    a.assert_use_zone(climber_placement, scenario["climber"])
    assert climber_placement["attached_to_placement_id"] is None, (
        "the climber must be free-standing, otherwise the attachment exemption applies"
    )
    assert climber_placement["use_zone_start_cm"] <= deck_placement["use_zone_end_cm"], (
        f"zones must overlap: climber starts at {climber_placement['use_zone_start_cm']}, "
        f"deck ends at {deck_placement['use_zone_end_cm']}"
    )

    response = api_client.validate_placement(climber_placement["id"], fx.CONSULTANT)
    validate_error(response, ApiErrorId.ERR_USE_ZONE_OVERLAP.value, 409)

    climber_after = fx.get_placement(climber_placement["id"])
    deck_after = fx.get_placement(deck_placement["id"])
    assert climber_after["status"] == "DRAFT", (
        f"expected DRAFT, got {climber_after['status']} after the rejected validation"
    )
    assert deck_after["status"] == "VALIDATED", (
        f"expected VALIDATED, got {deck_after['status']} for the untouched deck"
    )


def test_project_not_editable_outranks_the_persisting_use_zone_overlap():
    """Once a rendering has moved the project out of an editable status, the same validation reports the state error, not the geometric one.

    PRD: "When a request violates more than one rule, the response must carry the error of the **highest-priority** violated rule, evaluated in the following order."
    PRD: "**Editability and locking of design content:** design content may be mutated only while the owning project's `design_status` is `CONSULTATION` or `REVISION_REQUESTED` (`ERR_PROJECT_NOT_EDITABLE`), and a `LOCKED` play area accepts no further placement writes (`ERR_PLAY_AREA_LOCKED`)."
    PRD: "**Business constraints,** in this order: the rework ceiling (`ERR_REWORK_LIMIT_EXCEEDED`), use-zone overlap inside an area (`ERR_USE_ZONE_OVERLAP`), use-zone containment inside the area's axis interval (`ERR_USE_ZONE_OUT_OF_BOUNDS`)"

    Design: Difficulty/priority_pair_validation_conflict/placement_validate_state_error_precedes_use_zone_overlap
    """
    scenario = _setup_overlapping_draft_climber()
    project_id = scenario["project"]["id"]
    climber_id = scenario["climber_placement"]["id"]

    geometry_response = api_client.validate_placement(climber_id, fx.CONSULTANT)
    validate_error(geometry_response, ApiErrorId.ERR_USE_ZONE_OVERLAP.value, 409)

    rendering_response = api_client.issue_rendering(
        project_id, f.rendering_payload(scenario["standard"]["id"]), fx.CONSULTANT
    )
    rendering = validate_success(rendering_response, 201)
    assert rendering["status"] == "ISSUED", (
        f"expected ISSUED, got {rendering['status']} for the freshly issued rendering"
    )
    project = fx.get_project(project_id)
    assert project["design_status"] == "RENDERED", (
        f"expected RENDERED, got {project['design_status']} after issuing the rendering"
    )

    state_response = api_client.validate_placement(climber_id, fx.CONSULTANT)
    validate_error(state_response, ApiErrorId.ERR_PROJECT_NOT_EDITABLE.value, 409)

    climber_after = fx.get_placement(climber_id)
    deck_after = fx.get_placement(scenario["deck_placement"]["id"])
    assert climber_after["status"] == "DRAFT", (
        f"expected DRAFT, got {climber_after['status']} after the second rejected validation"
    )
    assert deck_after["status"] == "VALIDATED", (
        f"expected VALIDATED, got {deck_after['status']} for the untouched deck"
    )
    assert climber_after["use_zone_start_cm"] <= deck_after["use_zone_end_cm"], (
        "the geometric violation must still be present when the state error is reported: "
        f"climber starts at {climber_after['use_zone_start_cm']}, deck ends at "
        f"{deck_after['use_zone_end_cm']}"
    )


def test_two_rejected_validations_leave_the_placement_and_derived_numbers_untouched():
    """Neither rejected validation mutates the placement row or the area's two derived numbers.

    PRD: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row"
    PRD: "`critical_fall_height_cm` is the largest `deck_height_cm` among the models of the area's placements whose `status` is `DRAFT` or `VALIDATED`; when that set is empty the value is 0."

    Design: Difficulty/priority_pair_validation_conflict/placement_validate_state_error_precedes_use_zone_overlap
    """
    scenario = _setup_overlapping_draft_climber()
    climber_id = scenario["climber_placement"]["id"]
    version_before = scenario["climber_placement"]["version"]

    validate_error(
        api_client.validate_placement(climber_id, fx.CONSULTANT),
        ApiErrorId.ERR_USE_ZONE_OVERLAP.value,
        409,
    )
    validate_success(
        api_client.issue_rendering(
            scenario["project"]["id"],
            f.rendering_payload(scenario["standard"]["id"]),
            fx.CONSULTANT,
        ),
        201,
    )
    validate_error(
        api_client.validate_placement(climber_id, fx.CONSULTANT),
        ApiErrorId.ERR_PROJECT_NOT_EDITABLE.value,
        409,
    )

    climber_after = fx.get_placement(climber_id)
    a.assert_placement(climber_after)
    assert climber_after["version"] == version_before, (
        f"expected version {version_before}, got {climber_after['version']} "
        "after two rejected validations"
    )

    area = fx.get_play_area(scenario["area"]["id"])
    assert area["critical_fall_height_cm"] == 122, (
        f"expected 122, got {area['critical_fall_height_cm']} for the area's critical fall height"
    )
    a.assert_required_surfacing_depth(area, "CLAY", expected=28)


# ==========================================================================
# A FIRM quote that is both under-surfaced and over budget
# ==========================================================================
def _setup_firm_quote_candidate(
    catalogue: dict, client_name: str, surfacing_depth_cm: int
) -> dict:
    """A RENDERED project holding one VALIDATED deck, priced against a 100000-cent budget.

    The single SKY_BLUE deck is not the model's first colour option, so its raw
    line carries the seven percent surcharge: subtotal 68855 cents, freight
    49250 cents, no discount, total 118105 cents against a 100000-cent ceiling.
    The area's critical fall height is 122 cm, so its required surfacing depth is
    28 cm and a 20-cm area is under-surfaced while a 30-cm area is not.
    """
    project = fx.create_project_in_consultation(
        client_name=client_name, budget_cents=100000
    )
    area = fx.create_play_area(project["id"], surfacing_depth_cm=surfacing_depth_cm)
    placement = fx.create_validated_placement(
        area["id"],
        catalogue["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    rendering = fx.issue_rendering(project["id"], catalogue["standard"]["id"])
    return {
        "project": fx.get_project(project["id"]),
        "area": fx.get_play_area(area["id"]),
        "placement": placement,
        "rendering": rendering,
    }


def _issue_firm_quote(project_id: str, rendering_id: str):
    """Fire a FIRM quote issuance at the project's live version and return the raw response."""
    payload = f.quote_payload(
        project_id, rendering_id, fx.project_version(project_id), variant="FIRM"
    )
    return api_client.create_quote(payload, fx.CONSULTANT)


def test_surfacing_depth_error_outranks_the_budget_overrun_on_a_firm_quote():
    """A FIRM quote that is both under-surfaced and over budget reports the surfacing error.

    PRD: "**Fiscal checks last.** Only after every safety and constraint check has passed does the system look at money"
    PRD: "Every play area of the project must have a specified `surfacing_depth_cm` greater than or equal to its `required_surfacing_depth_cm`, or the issuance is refused with `ERR_SURFACING_DEPTH_INSUFFICIENT` (HTTP 422)."
    PRD: "And the resulting `total_cents` must not exceed the project's `budget_cents`, or the issuance is refused with `ERR_QUOTE_EXCEEDS_BUDGET` (HTTP 422) — fiscal checks of this kind run only after every safety and constraint check has already passed."

    Design: Difficulty/priority_pair_validation_conflict/firm_quote_surfacing_safety_error_precedes_budget_overrun
    """
    catalogue = fx.setup_toddler_catalogue()
    scenario = _setup_firm_quote_candidate(catalogue, "Alder Court School", 20)
    project = scenario["project"]
    area = scenario["area"]

    assert area["surfacing_depth_cm"] == 20, (
        f"expected 20, got {area['surfacing_depth_cm']} for the specified surfacing depth"
    )
    a.assert_required_surfacing_depth(area, "CLAY", expected=28)
    assert project["budget_cents"] == 100000, (
        f"expected 100000, got {project['budget_cents']}; the 118105-cent FIRM total "
        "must also breach the budget ceiling"
    )
    version_before = project["version"]

    response = _issue_firm_quote(project["id"], scenario["rendering"]["id"])
    validate_error(response, ApiErrorId.ERR_SURFACING_DEPTH_INSUFFICIENT.value, 422)

    assert_paginated_list(
        api_client.list_quotes(fx.CONSULTANT, {"project_id": project["id"]}),
        expected_total=0,
    )
    project_after = fx.get_project(project["id"])
    assert project_after["design_status"] == "RENDERED", (
        f"expected RENDERED, got {project_after['design_status']} after the rejected issuance"
    )
    assert project_after["version"] == version_before, (
        f"expected version {version_before}, got {project_after['version']} "
        "after the rejected issuance"
    )


def test_budget_overrun_surfaces_once_the_surfacing_requirement_is_met():
    """With the same pricing but a compliant surfacing depth, the identical FIRM quote reports the fiscal error.

    PRD: "And the resulting `total_cents` must not exceed the project's `budget_cents`, or the issuance is refused with `ERR_QUOTE_EXCEEDS_BUDGET` (HTTP 422) — fiscal checks of this kind run only after every safety and constraint check has already passed."

    Design: Difficulty/priority_pair_validation_conflict/firm_quote_surfacing_safety_error_precedes_budget_overrun
    """
    catalogue = fx.setup_toddler_catalogue()
    scenario = _setup_firm_quote_candidate(catalogue, "Birch Lane School", 30)
    project = scenario["project"]
    area = scenario["area"]

    assert area["surfacing_depth_cm"] == 30, (
        f"expected 30, got {area['surfacing_depth_cm']} for the specified surfacing depth"
    )
    a.assert_required_surfacing_depth(area, "CLAY", expected=28)
    version_before = project["version"]

    response = _issue_firm_quote(project["id"], scenario["rendering"]["id"])
    validate_error(response, ApiErrorId.ERR_QUOTE_EXCEEDS_BUDGET.value, 422)

    assert_paginated_list(
        api_client.list_quotes(fx.CONSULTANT, {"project_id": project["id"]}),
        expected_total=0,
    )
    project_after = fx.get_project(project["id"])
    assert project_after["design_status"] == "RENDERED", (
        f"expected RENDERED, got {project_after['design_status']} after the rejected issuance"
    )
    assert project_after["version"] == version_before, (
        f"expected version {version_before}, got {project_after['version']} "
        "after the rejected issuance"
    )


def test_only_the_surfacing_depth_decides_which_error_two_identical_quotes_report():
    """Two projects priced identically differ only in surfacing depth, and only the under-surfaced one hides the budget overrun.

    PRD: "When a request violates more than one rule, the response must carry the error of the **highest-priority** violated rule, evaluated in the following order."
    PRD: "12. **Safety checks,** in this order: fall height against the ACTIVE edition's ceiling for the area's age band (`ERR_FALL_HEIGHT_EXCEEDS_STANDARD`), age-group use-zone separation (`ERR_AGE_GROUP_SEPARATION_VIOLATION`), model-to-area age-band agreement (`ERR_AGE_GROUP_MISMATCH`), surfacing depth sufficiency (`ERR_SURFACING_DEPTH_INSUFFICIENT`), and accessible-route provision (`ERR_ACCESSIBLE_ROUTE_MISSING`)."
    PRD: "15. **Fiscal checks last.** Only after every safety and constraint check has passed does the system look at money: a FIRM quote against the client's budget ceiling (`ERR_QUOTE_EXCEEDS_BUDGET`)"

    Design: Difficulty/priority_pair_validation_conflict/firm_quote_surfacing_safety_error_precedes_budget_overrun
    """
    catalogue = fx.setup_toddler_catalogue()
    shallow = _setup_firm_quote_candidate(catalogue, "Alder Court School", 20)
    compliant = _setup_firm_quote_candidate(catalogue, "Birch Lane School", 30)

    assert (
        shallow["placement"]["component_model_id"]
        == compliant["placement"]["component_model_id"]
    ), "both projects must price the same catalogue model"
    assert shallow["placement"]["color_choice"] == compliant["placement"]["color_choice"]
    assert shallow["placement"]["quantity"] == compliant["placement"]["quantity"]
    assert shallow["project"]["budget_cents"] == compliant["project"]["budget_cents"]

    validate_error(
        _issue_firm_quote(shallow["project"]["id"], shallow["rendering"]["id"]),
        ApiErrorId.ERR_SURFACING_DEPTH_INSUFFICIENT.value,
        422,
    )
    validate_error(
        _issue_firm_quote(compliant["project"]["id"], compliant["rendering"]["id"]),
        ApiErrorId.ERR_QUOTE_EXCEEDS_BUDGET.value,
        422,
    )

    assert_paginated_list(api_client.list_quotes(fx.CONSULTANT, None), expected_total=0)
