"""Entity representations: creation echoes, declared defaults, derived fields,
not-found paths and the append-only inspection record.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_error,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["manufacturer_admin_headers"]
CONSULTANT = TEST_USERS["design_consultant_headers"]

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_component_model_create_echoes_every_supplied_input():
    """Adding a catalogue model answers 201 and echoes the created resource.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row"

    Design: Corner/entities/component_model_create_echoes_inputs_and_returns_201
    """
    payload = f.slide_model_payload()

    response = api_client.create_component_model(payload, ADMIN)

    model = a.assert_object_envelope(response, 201)
    a.assert_component_model(model)
    for field, expected in payload.items():
        assert model[field] == expected, (
            f"{field} should echo {expected!r}, got {model.get(field)!r}"
        )
    assert model["supersedes_model_id"] is None, (
        f"a new family stores supersedes_model_id as null, got "
        f"{model.get('supersedes_model_id')!r}"
    )
    a.assert_common_fields(model, expected_version=1)


def test_component_model_create_applies_declared_defaults_for_omitted_inputs():
    """Omitting the optional inputs stores their declared defaults.

    PRD: "The boolean `accessible_transfer_ready` records whether the model provides a compliant accessible transfer point and defaults to false."

    PRD: "A newly added model is `UNCERTIFIED` with `certified_against_standard_id` null and `lifecycle_status` `ACTIVE`."

    Design: Corner/entities/component_model_create_omitting_optional_inputs_applies_declared_defaults
    """
    payload = f.drop_fields(
        f.component_model_payload(), "accessible_transfer_ready"
    )
    assert "accessible_transfer_ready" not in payload, "the optional input must be omitted"
    assert "supersedes_model_id" not in payload, "the optional reference must be omitted"

    model = a.assert_object_envelope(
        api_client.create_component_model(payload, ADMIN), 201
    )

    assert model["accessible_transfer_ready"] is False, (
        f"accessible_transfer_ready defaults to false, got "
        f"{model.get('accessible_transfer_ready')!r}"
    )
    assert model["supersedes_model_id"] is None, (
        f"supersedes_model_id is stored as null when omitted, got "
        f"{model.get('supersedes_model_id')!r}"
    )
    assert model["certification_status"] == "UNCERTIFIED", (
        f"expected UNCERTIFIED, got {model.get('certification_status')!r}"
    )
    assert model["certified_against_standard_id"] is None, (
        f"expected a null certification pin, got "
        f"{model.get('certified_against_standard_id')!r}"
    )
    assert model["lifecycle_status"] == "ACTIVE", (
        f"expected lifecycle_status ACTIVE, got {model.get('lifecycle_status')!r}"
    )
    assert model["deck_height_cm"] == 0, (
        f"a ground-level component keeps deck_height_cm 0, got {model['deck_height_cm']}"
    )
    a.assert_common_fields(model, expected_version=1)


def test_play_area_get_returns_the_stored_row_with_its_derived_defaults():
    """A fresh play area reads back PLANNED with its two derived numbers.

    PRD: "A newly created area is `PLANNED`, with `critical_fall_height_cm` at 0 and `required_surfacing_depth_cm` at the absolute floor of 15 centimetres"

    PRD: "the area's `project_id` is taken from the request path rather than the body"

    Design: Corner/entities/play_area_get_returns_stored_row_with_computed_defaults
    """
    scenario = fx.setup_project_with_toddler_area()

    area = a.assert_object_envelope(
        api_client.get_play_area(scenario["area"]["id"], CONSULTANT)
    )

    a.assert_play_area(area)
    assert area["project_id"] == scenario["project"]["id"], (
        f"project_id should come from the path, got {area['project_id']}"
    )
    assert area["age_group"] == "TODDLER_6_23M", (
        f"expected TODDLER_6_23M, got {area['age_group']!r}"
    )
    assert area["axis_origin_cm"] == 0, f"expected 0, got {area['axis_origin_cm']}"
    assert area["axis_length_cm"] == 2000, f"expected 2000, got {area['axis_length_cm']}"
    assert area["surfacing_material"] == "ENGINEERED_WOOD_FIBER", (
        f"expected ENGINEERED_WOOD_FIBER, got {area['surfacing_material']!r}"
    )
    assert area["surfacing_depth_cm"] == 30, (
        f"expected the specified depth 30, got {area['surfacing_depth_cm']}"
    )
    assert area["critical_fall_height_cm"] == 0, (
        f"an area with no placements has no fall height, got "
        f"{area['critical_fall_height_cm']}"
    )
    a.assert_required_surfacing_depth(area, "CLAY")
    a.assert_required_surfacing_depth(area, "CLAY", expected=15)
    assert area["status"] == "PLANNED", f"expected PLANNED, got {area['status']!r}"


def test_component_model_list_filter_narrows_total_count_and_pages():
    """A certification filter narrows total_count; limit and offset are echoed.

    PRD: "The `meta` block of a list response carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filter before pagination was applied, and `has_more` indicating whether any row remains beyond the current page."

    PRD: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/entities/component_models_list_filters_by_certification_status_and_paginates
    """
    fx.create_active_standard()
    certified = fx.create_certified_model(f.deck_model_payload())
    uncertified = fx.create_model(f.component_model_payload())

    filtered, filtered_meta = a.assert_paginated_list(
        api_client.list_component_models(
            CONSULTANT,
            params={"certification_status": "CERTIFIED", "limit": 1, "offset": 0},
        ),
        expected_total=1,
    )

    assert len(filtered) == 1, f"expected a single row on the page, got {len(filtered)}"
    assert filtered[0]["id"] == certified["id"], (
        f"expected the certified model, got {filtered[0]['id']}"
    )
    assert filtered_meta["limit"] == 1, f"expected limit 1, got {filtered_meta['limit']}"
    assert filtered_meta["offset"] == 0, (
        f"expected offset 0, got {filtered_meta['offset']}"
    )
    assert filtered_meta["has_more"] is False, (
        f"one match on a page of one leaves nothing beyond, got {filtered_meta['has_more']!r}"
    )

    everything, everything_meta = a.assert_paginated_list(
        api_client.list_component_models(CONSULTANT), expected_total=2
    )

    assert everything_meta["limit"] == 10, (
        f"limit defaults to 10, got {everything_meta['limit']}"
    )
    assert everything_meta["offset"] == 0, (
        f"offset defaults to 0, got {everything_meta['offset']}"
    )
    assert everything_meta["has_more"] is False, (
        f"two rows fit on a page of ten, got {everything_meta['has_more']!r}"
    )
    listed = {row["id"] for row in everything}
    assert {certified["id"], uncertified["id"]} <= listed, (
        f"the unfiltered listing must hold both models, got {listed}"
    )


def test_get_placement_with_an_unknown_id_returns_placement_not_found():
    """An unknown placement identifier answers 404 in the error envelope.

    PRD: "Each entity has its own not-found code, and all of them are HTTP 404"

    Design: Corner/entities/placement_get_with_unknown_id_returns_not_found
    """
    response = api_client.get_placement(UNKNOWN_ID, CONSULTANT)

    error = validate_error(response, ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error", (
        f"expected an error envelope, got {response.json().get('response_type')!r}"
    )
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"the error must carry a human-readable message, got {error.get('message')!r}"
    )
    assert set(error.keys()) == {"error_id", "message"}, (
        f"an error payload carries error_id and message only, got {sorted(error.keys())}"
    )


def test_placement_create_without_x_start_cm_is_refused_as_invalid_request():
    """Omitting the required anchor coordinate is a 422 and writes nothing.

    PRD: "Required fields must be present, values must be of the declared type, enum-typed values must be members of their declared set, strings must respect their declared length limits and numbers their declared ranges."

    Design: Corner/entities/placement_create_missing_x_start_cm_returns_invalid_request
    """
    scenario = fx.setup_project_with_toddler_area()
    area_id = scenario["area"]["id"]
    payload = f.drop_fields(
        f.placement_payload(scenario["deck"]["id"], color_choice="SKY_BLUE"),
        "x_start_cm",
    )

    response = api_client.create_placement(area_id, payload, CONSULTANT)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    placements, _ = a.assert_paginated_list(
        api_client.list_area_placements(area_id, CONSULTANT), expected_total=0
    )
    assert placements == [], f"the rejected write must persist nothing, got {placements}"
    area = a.assert_object_envelope(api_client.get_play_area(area_id, CONSULTANT))
    assert area["critical_fall_height_cm"] == 0, (
        f"a rejected placement leaves the fall height untouched, got "
        f"{area['critical_fall_height_cm']}"
    )
    assert area["status"] == "PLANNED", (
        f"the area stays PLANNED, got {area['status']!r}"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("surfacing_material", "ASTROTURF"),
        ("age_group", "GROWN_UPS"),
    ],
)
def test_play_area_create_with_a_value_outside_a_declared_enum_is_refused(field, value):
    """A value outside a declared enum set is a shape failure, not a new option.

    PRD: "enum-typed values must be members of their declared set"

    PRD: "Protective surfacing is specified per area by `surfacing_material`, either `ENGINEERED_WOOD_FIBER` or `POURED_RUBBER`"

    Design: Corner/entities/play_area_create_with_unknown_surfacing_material_returns_invalid_enum
    """
    fx.create_active_standard()
    project = fx.create_project_in_consultation()

    response = api_client.create_play_area(
        project["id"], f.play_area_payload(**{field: value}), CONSULTANT
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    areas, _ = a.assert_paginated_list(
        api_client.list_play_areas(project["id"], CONSULTANT), expected_total=0
    )
    assert areas == [], f"no area may be carved out by a rejected request, got {areas}"
    project_after = a.assert_object_envelope(
        api_client.get_project(project["id"], CONSULTANT)
    )
    assert project_after["design_status"] == "CONSULTATION", (
        f"the project stays in CONSULTATION, got {project_after['design_status']!r}"
    )


def test_placement_use_zone_bounds_are_derived_from_the_model_footprint():
    """The use-zone interval is derived from the anchor and the model footprint.

    PRD: "For the placement being written, `use_zone_start_cm` is the anchor coordinate `x_start_cm` less the model's `use_zone_footprint_cm`."

    PRD: "`use_zone_end_cm` is the anchor coordinate plus the model's `use_zone_footprint_cm`, plus a further 122 centimetres when and only when the model's `category` is `PLASTIC_SLIDE`"

    PRD: "all of which start at null, zero, zero, zero, zero and false respectively"

    Design: Corner/entities/placement_use_zone_bounds_are_computed_from_model_footprint
    """
    scenario = fx.setup_project_with_toddler_area()
    area_id = scenario["area"]["id"]
    deck = scenario["deck"]

    placement = a.assert_object_envelope(
        api_client.create_placement(
            area_id,
            f.placement_payload(
                deck["id"], color_choice="SKY_BLUE", x_start_cm=700, quantity=1
            ),
            CONSULTANT,
        ),
        201,
    )

    a.assert_placement(placement)
    a.assert_use_zone(placement, deck)
    assert placement["use_zone_start_cm"] == 517, (
        f"expected use_zone_start_cm 517, got {placement['use_zone_start_cm']}"
    )
    assert placement["use_zone_end_cm"] == 883, (
        f"expected use_zone_end_cm 883, got {placement['use_zone_end_cm']}"
    )
    assert placement["play_area_id"] == area_id, (
        f"play_area_id comes from the path, got {placement['play_area_id']}"
    )
    assert placement["status"] == "DRAFT", (
        f"a new placement is born DRAFT, got {placement['status']!r}"
    )
    assert placement["retrofit_model_id"] is None, (
        f"expected a null retrofit reference, got {placement['retrofit_model_id']!r}"
    )
    for field in (
        "retrofit_quantity",
        "retrofit_unit_price_cents",
        "retrofit_handling_cents",
        "retrofit_total_cents",
    ):
        assert placement[field] == 0, f"expected {field} 0, got {placement[field]}"
    assert placement["legacy_surcharge_applied"] is False, (
        f"expected legacy_surcharge_applied false, got "
        f"{placement['legacy_surcharge_applied']!r}"
    )


def test_inspection_log_under_an_unknown_job_returns_job_not_found():
    """The nested inspection log fails on its own path segment first.

    PRD: "Path segments are resolved strictly left to right, and the first segment that fails to resolve determines the error."

    Design: Corner/entities/installation_inspection_is_immutable_and_exposes_no_version_field
    """
    response = api_client.list_job_inspections(UNKNOWN_ID, CONSULTANT)

    validate_error(response, ApiErrorId.ERR_JOB_NOT_FOUND.value, 404)


def test_filed_inspection_exposes_neither_updated_at_nor_version():
    """An inspection record is append-only evidence with no revision counter.

    PRD: "Inspection records are immutable append-only evidence, so they carry only `id` and `created_at`; they have neither `updated_at` nor `version`, and neither field appears in their JSON representation."

    Design: Corner/entities/installation_inspection_is_immutable_and_exposes_no_version_field
    """
    scenario = fx.setup_installed_project()

    a.assert_append_only_fields(scenario["inspection"])
    a.assert_inspection(scenario["inspection"])

    logged, _ = a.assert_paginated_list(
        api_client.list_job_inspections(scenario["job"]["id"], CONSULTANT),
        expected_total=1,
    )
    assert len(logged) == 1, f"expected one filed record, got {len(logged)}"
    for record in logged:
        a.assert_append_only_fields(record)


@pytest.mark.parametrize(
    "body_overrides",
    [
        {},
        {"surfacing_material": "ASTROTURF"},
    ],
    ids=["well_formed_body", "body_with_an_unknown_enum_value"],
)
def test_play_area_create_under_an_unknown_project_returns_project_not_found(
    body_overrides,
):
    """An unresolvable path segment decides the error before the body is read.

    PRD: "Path segments are resolved strictly left to right, and the first segment that fails to resolve determines the error."

    Design: Corner/entities/play_area_create_under_unknown_project_returns_project_not_found
    """
    fx.create_active_standard()

    response = api_client.create_play_area(
        UNKNOWN_ID, f.play_area_payload(**body_overrides), CONSULTANT
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)
