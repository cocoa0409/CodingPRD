"""Endpoint-level behaviours: placement removal, model lifecycle, attachment
links and replacement-part purchases.

Every test drives real HTTP endpoints against an empty database with the logical
clock at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_paginated_list,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["manufacturer_admin_headers"]
CONSULTANT = TEST_USERS["design_consultant_headers"]


# --------------------------------------------------------------------------
# Local composites (built from fixtures primitives only)
# --------------------------------------------------------------------------
def _setup_attachment_design():
    """A toddler area holding a DRAFT post at x=200 and a DRAFT deck at x=700."""
    scenario = fx.setup_project_with_toddler_area()
    area_id = scenario["area"]["id"]
    scenario["post_placement"] = fx.create_placement(
        area_id,
        scenario["post"]["id"],
        color_choice="CEDAR",
        x_start_cm=200,
        quantity=3,
    )
    scenario["deck_placement"] = fx.create_placement(
        area_id,
        scenario["deck"]["id"],
        color_choice="CEDAR",
        x_start_cm=700,
        quantity=1,
    )
    return scenario


def _setup_retrofit_design():
    """A DRAFT deck placement, its own model, and a superseding successor model."""
    scenario = fx.setup_project_with_toddler_area()
    scenario["successor"] = fx.create_certified_model(
        f.deck_model_payload(
            sku="DECK-TDL-122-V2",
            unit_price_cents=66950,
            parts_support_until_year=2045,
            supersedes_model_id=scenario["deck"]["id"],
        )
    )
    scenario["placement"] = fx.create_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="CEDAR",
        x_start_cm=700,
        quantity=1,
    )
    return scenario


# --------------------------------------------------------------------------
# DELETE /playground/placements/{id}
# --------------------------------------------------------------------------
def test_removing_a_parent_placement_orphans_its_child_and_recomputes_the_area():
    """Removal answers 204, frees the child link and recomputes both derived numbers.

    PRD: "Removing a placement is available to a `DesignConsultant` while the project is editable and the area is not `LOCKED`, and it returns HTTP 204 with no body. Removal deletes the placement, clears `attached_to_placement_id` on any child placement that pointed at it — the children survive as free-standing placements rather than being deleted — recomputes the area's two derived numbers, and increments the area's `version` by one."

    Design: Corner/endpoints/placement_delete_clears_child_link_and_recomputes_area_derivations
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Delete Park"}
    )
    area_id = scenario["area"]["id"]
    post_placement = fx.create_placement(
        area_id,
        scenario["post"]["id"],
        color_choice="CEDAR",
        x_start_cm=200,
        quantity=3,
    )
    deck_placement = fx.create_placement(
        area_id,
        scenario["deck"]["id"],
        color_choice="CEDAR",
        x_start_cm=700,
        quantity=1,
        attached_to_placement_id=post_placement["id"],
    )

    area_before = fx.get_play_area(area_id)
    assert area_before["critical_fall_height_cm"] == 122, (
        f"expected 122, got {area_before['critical_fall_height_cm']} "
        "with a 122 cm deck in the area"
    )
    assert area_before["required_surfacing_depth_cm"] == 28, (
        f"expected 28, got {area_before['required_surfacing_depth_cm']} "
        "for engineered wood fibre under a toddler area on clay"
    )

    parent_removal = api_client.delete_placement(post_placement["id"], CONSULTANT)
    a.assert_empty_data_object(parent_removal, 204)

    orphan = fx.get_placement(deck_placement["id"])
    assert orphan["attached_to_placement_id"] is None, (
        "expected the child's attachment link to be cleared, got "
        f"{orphan['attached_to_placement_id']!r}"
    )

    area_after_parent = fx.get_play_area(area_id)
    assert area_after_parent["critical_fall_height_cm"] == 122, (
        f"expected 122, got {area_after_parent['critical_fall_height_cm']} "
        "after removing the ground-level parent only"
    )
    assert area_after_parent["required_surfacing_depth_cm"] == 28, (
        f"expected 28, got {area_after_parent['required_surfacing_depth_cm']} "
        "after removing the ground-level parent only"
    )

    child_removal = api_client.delete_placement(deck_placement["id"], CONSULTANT)
    a.assert_empty_data_object(child_removal, 204)

    area_final = fx.get_play_area(area_id)
    assert area_final["critical_fall_height_cm"] == 0, (
        f"expected 0, got {area_final['critical_fall_height_cm']} for an empty area"
    )
    assert area_final["required_surfacing_depth_cm"] == 15, (
        f"expected the 15 cm floor, got {area_final['required_surfacing_depth_cm']} "
        "for an empty area"
    )

    validate_error(
        api_client.get_placement(deck_placement["id"], CONSULTANT),
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value,
    )

    data, meta = assert_paginated_list(
        api_client.list_area_placements(area_id, CONSULTANT), 0
    )
    assert data == [], f"expected no placements to remain, got {data}"
    assert meta["has_more"] is False, (
        f"expected has_more False, got {meta['has_more']} on an empty page"
    )
    a.assert_version_bumped_by(area_before, area_final, 2)


# --------------------------------------------------------------------------
# PATCH /playground/component-models/{id}/lifecycle
# --------------------------------------------------------------------------
def test_lifecycle_hops_leave_the_certification_dimension_untouched():
    """ACTIVE -> LEGACY -> DISCONTINUED bumps version twice and keeps CERTIFIED.

    PRD: "Certification status and lifecycle status never affect one another: a `LEGACY` model can be perfectly `CERTIFIED`, which is exactly what makes compliance retrofits to legacy parts possible."

    Design: Corner/endpoints/component_model_lifecycle_endpoint_walks_active_legacy_discontinued
    """
    catalogue = fx.setup_toddler_catalogue()
    deck_id = catalogue["deck"]["id"]
    before = get_success_data(api_client.get_component_model(deck_id, ADMIN))

    legacy = validate_success(
        api_client.set_component_model_lifecycle(
            deck_id, f.lifecycle_payload("LEGACY"), ADMIN
        )
    )
    assert legacy["lifecycle_status"] == "LEGACY", (
        f"expected LEGACY, got {legacy['lifecycle_status']}"
    )
    assert legacy["certification_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {legacy['certification_status']} after the first hop"
    )
    a.assert_version_bumped_by(before, legacy, 1)

    discontinued = validate_success(
        api_client.set_component_model_lifecycle(
            deck_id, f.lifecycle_payload("DISCONTINUED"), ADMIN
        )
    )
    assert discontinued["lifecycle_status"] == "DISCONTINUED", (
        f"expected DISCONTINUED, got {discontinued['lifecycle_status']}"
    )
    assert discontinued["certification_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {discontinued['certification_status']} "
        "after the second hop"
    )
    a.assert_version_bumped_by(before, discontinued, 2)


def test_a_legacy_model_still_places_but_a_discontinued_one_is_refused():
    """A LEGACY model accepts a placement; the same model refuses one once retired.

    PRD: "`LEGACY → DISCONTINUED` retires it from new designs altogether, and a placement attempt against a discontinued model is refused with `ERR_MODEL_DISCONTINUED`."

    Design: Corner/endpoints/component_model_lifecycle_endpoint_walks_active_legacy_discontinued
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Lifecycle Park"}
    )
    area_id = scenario["area"]["id"]
    deck = scenario["deck"]
    fx.set_model_lifecycle(deck["id"], "LEGACY")

    placement = validate_success(
        api_client.create_placement(
            area_id,
            f.placement_payload(
                deck["id"], color_choice="CEDAR", x_start_cm=700, quantity=1
            ),
            CONSULTANT,
        ),
        201,
    )
    assert placement["status"] == "DRAFT", (
        f"expected DRAFT, got {placement['status']} for a fresh placement"
    )
    assert placement["use_zone_start_cm"] == 517, (
        f"expected 517, got {placement['use_zone_start_cm']}"
    )
    assert placement["use_zone_end_cm"] == 883, (
        f"expected 883, got {placement['use_zone_end_cm']}"
    )

    fx.set_model_lifecycle(deck["id"], "DISCONTINUED")
    refused = api_client.create_placement(
        area_id,
        f.placement_payload(
            deck["id"], color_choice="CEDAR", x_start_cm=1500, quantity=1
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_MODEL_DISCONTINUED.value)

    area = fx.get_play_area(area_id)
    assert area["critical_fall_height_cm"] == 122, (
        f"expected 122, got {area['critical_fall_height_cm']} from the placement "
        "made while the model was still saleable"
    )


# --------------------------------------------------------------------------
# POST /playground/play-areas/{id}/placements — attachment links
# --------------------------------------------------------------------------
def test_an_attachment_parent_must_resolve_to_an_existing_placement():
    """An unknown attachment parent is reported as a missing placement, not a bad body.

    PRD: "Every foreign key a caller sends must resolve to an existing row, and an unresolvable reference produces the not-found code of the referenced entity's type: `component_model_id`, `supersedes_model_id` and `replacement_model_id` produce `ERR_MODEL_NOT_FOUND`; `attached_to_placement_id` and `placement_id` produce `ERR_PLACEMENT_NOT_FOUND`"

    Design: Corner/endpoints/placement_attachment_link_checks_target_existence_direction_and_parent_state
    """
    scenario = _setup_attachment_design()
    refused = api_client.create_placement(
        scenario["area"]["id"],
        f.placement_payload(
            scenario["slide"]["id"],
            color_choice="CRIMSON",
            x_start_cm=1300,
            quantity=1,
            attached_to_placement_id=NON_EXISTENT_UUID,
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value)


def test_a_slide_may_attach_only_to_a_deck_placement():
    """Attaching a slide to a post is refused; attaching it to the deck succeeds.

    PRD: "Attachment direction follows the catalogue, and violating it yields `ERR_INVALID_ATTACHMENT_TARGET` (HTTP 422). A `PLASTIC_SLIDE` and a `METAL_CLIMBER` may attach only to a placement whose model `category` is `DECK`."

    Design: Corner/endpoints/placement_attachment_link_checks_target_existence_direction_and_parent_state
    """
    scenario = _setup_attachment_design()
    area_id = scenario["area"]["id"]

    refused = api_client.create_placement(
        area_id,
        f.placement_payload(
            scenario["slide"]["id"],
            color_choice="CRIMSON",
            x_start_cm=1300,
            quantity=1,
            attached_to_placement_id=scenario["post_placement"]["id"],
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_ATTACHMENT_TARGET.value)

    accepted = validate_success(
        api_client.create_placement(
            area_id,
            f.placement_payload(
                scenario["slide"]["id"],
                color_choice="CRIMSON",
                x_start_cm=1300,
                quantity=1,
                attached_to_placement_id=scenario["deck_placement"]["id"],
            ),
            CONSULTANT,
        ),
        201,
    )
    assert accepted["attached_to_placement_id"] == scenario["deck_placement"]["id"], (
        "expected the slide to hang off the deck, got "
        f"{accepted['attached_to_placement_id']!r}"
    )
    assert accepted["use_zone_start_cm"] == 1117, (
        f"expected 1117, got {accepted['use_zone_start_cm']}"
    )
    assert accepted["use_zone_end_cm"] == 1605, (
        f"expected 1605, got {accepted['use_zone_end_cm']} including the run-out"
    )
    a.assert_use_zone(accepted, scenario["slide"])


def test_a_child_placement_validates_only_after_its_parent():
    """A slide cannot be validated ahead of the deck it is bolted to.

    PRD: "If the placement declares an attachment parent, that parent must itself already be `VALIDATED`, otherwise `ERR_PARENT_PLACEMENT_NOT_VALIDATED`; the practical consequence is that a structure must be validated bottom-up, posts before decks before slides."

    Design: Corner/endpoints/placement_attachment_link_checks_target_existence_direction_and_parent_state
    """
    scenario = _setup_attachment_design()
    slide_placement = fx.create_placement(
        scenario["area"]["id"],
        scenario["slide"]["id"],
        color_choice="CRIMSON",
        x_start_cm=1300,
        quantity=1,
        attached_to_placement_id=scenario["deck_placement"]["id"],
    )

    too_early = api_client.validate_placement(slide_placement["id"], CONSULTANT)
    validate_error(too_early, ApiErrorId.ERR_PARENT_PLACEMENT_NOT_VALIDATED.value)
    still_draft = fx.get_placement(slide_placement["id"])
    assert still_draft["status"] == "DRAFT", (
        f"expected DRAFT, got {still_draft['status']} after the refused validation"
    )

    parent = validate_success(
        api_client.validate_placement(scenario["deck_placement"]["id"], CONSULTANT)
    )
    assert parent["status"] == "VALIDATED", (
        f"expected VALIDATED, got {parent['status']} for the deck"
    )
    child = validate_success(
        api_client.validate_placement(slide_placement["id"], CONSULTANT)
    )
    assert child["status"] == "VALIDATED", (
        f"expected VALIDATED, got {child['status']} once the parent was validated"
    )


# --------------------------------------------------------------------------
# POST /playground/placements/{id}/retrofit
# --------------------------------------------------------------------------
def test_retrofit_rejects_a_model_that_neither_matches_nor_supersedes():
    """An unrelated catalogue model is not an eligible replacement.

    PRD: "The replacement must be either the placement's own current model or a model whose `supersedes_model_id` points at the placement's current model; anything else is refused with `ERR_RETROFIT_MODEL_MISMATCH` (HTTP 422)."

    Design: Corner/endpoints/retrofit_swaps_the_model_only_when_the_placement_needs_recertification
    """
    scenario = _setup_retrofit_design()
    refused = api_client.retrofit_placement(
        scenario["placement"]["id"],
        f.retrofit_payload(scenario["post"]["id"], 1),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_RETROFIT_MODEL_MISMATCH.value)


def test_replacement_part_purchase_prices_the_handling_waiver_on_the_line_amount():
    """A 64350-cent line attracts flat handling; a 267800-cent line waives it.

    PRD: "When the line amount is greater than or equal to 250000 cents, `retrofit_handling_cents` is 0; otherwise it is a flat 3500 cents. A line of exactly 250000 cents therefore waives handling, while a line of 247000 cents attracts the 3500-cent charge and totals 250500 cents — above the threshold, yet handling still applies, because the decision was made on 247000. `retrofit_total_cents` is the line amount plus `retrofit_handling_cents`. The purchase also records `retrofit_model_id` as the replacement model and `retrofit_quantity` as the requested quantity."

    Design: Corner/endpoints/retrofit_swaps_the_model_only_when_the_placement_needs_recertification
    """
    scenario = _setup_retrofit_design()
    placement_id = scenario["placement"]["id"]

    own_model = validate_success(
        api_client.retrofit_placement(
            placement_id, f.retrofit_payload(scenario["deck"]["id"], 1), CONSULTANT
        )
    )
    assert own_model["retrofit_model_id"] == scenario["deck"]["id"], (
        f"expected the placement's own model, got {own_model['retrofit_model_id']!r}"
    )
    assert own_model["retrofit_quantity"] == 1, (
        f"expected 1, got {own_model['retrofit_quantity']}"
    )
    a.assert_cents(own_model["retrofit_unit_price_cents"], "retrofit_unit_price_cents")
    assert own_model["retrofit_unit_price_cents"] == 64350, (
        f"expected 64350, got {own_model['retrofit_unit_price_cents']}"
    )
    assert own_model["legacy_surcharge_applied"] is False, (
        "expected no surcharge on an ACTIVE model, got "
        f"{own_model['legacy_surcharge_applied']!r}"
    )
    assert own_model["retrofit_handling_cents"] == 3500, (
        f"expected 3500, got {own_model['retrofit_handling_cents']} on a 64350 line"
    )
    assert own_model["retrofit_total_cents"] == 67850, (
        f"expected 67850, got {own_model['retrofit_total_cents']}"
    )

    successor = validate_success(
        api_client.retrofit_placement(
            placement_id, f.retrofit_payload(scenario["successor"]["id"], 4), CONSULTANT
        )
    )
    assert successor["retrofit_model_id"] == scenario["successor"]["id"], (
        f"expected the successor model, got {successor['retrofit_model_id']!r}"
    )
    assert successor["retrofit_quantity"] == 4, (
        f"expected 4, got {successor['retrofit_quantity']}"
    )
    assert successor["retrofit_unit_price_cents"] == 66950, (
        f"expected 66950, got {successor['retrofit_unit_price_cents']}"
    )
    assert successor["retrofit_handling_cents"] == 0, (
        f"expected 0, got {successor['retrofit_handling_cents']} on a 267800 line"
    )
    assert successor["retrofit_total_cents"] == 267800, (
        f"expected 267800, got {successor['retrofit_total_cents']} — the second "
        "purchase overwrites the first rather than accumulating"
    )


def test_retrofit_leaves_a_draft_placement_model_and_status_untouched():
    """Only a NEEDS_RECERTIFICATION placement has its model rewritten by a retrofit.

    PRD: "Where the placement was in `NEEDS_RECERTIFICATION` and the replacement supersedes its model, the placement's `component_model_id` is rewritten to the replacement and its `status` moves `NEEDS_RECERTIFICATION → VALIDATED`. The owning area's `critical_fall_height_cm` and `required_surfacing_depth_cm` are recomputed in every case, since the model behind the placement may have changed height."

    Design: Corner/endpoints/retrofit_swaps_the_model_only_when_the_placement_needs_recertification
    """
    scenario = _setup_retrofit_design()
    area_id = scenario["area"]["id"]
    placement_id = scenario["placement"]["id"]

    validate_success(
        api_client.retrofit_placement(
            placement_id, f.retrofit_payload(scenario["successor"]["id"], 4), CONSULTANT
        )
    )

    placement = fx.get_placement(placement_id)
    assert placement["component_model_id"] == scenario["deck"]["id"], (
        "expected the DRAFT placement to keep its original model, got "
        f"{placement['component_model_id']!r}"
    )
    assert placement["status"] == "DRAFT", (
        f"expected DRAFT, got {placement['status']} after a parts purchase"
    )

    area = fx.get_play_area(area_id)
    assert area["critical_fall_height_cm"] == 122, (
        f"expected 122, got {area['critical_fall_height_cm']}"
    )
    assert area["required_surfacing_depth_cm"] == 28, (
        f"expected 28, got {area['required_surfacing_depth_cm']}"
    )
