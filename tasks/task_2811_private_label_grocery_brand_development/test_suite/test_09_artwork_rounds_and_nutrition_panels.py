"""Printing the panel: banded label rounding, and the gates a round must pass
before it can go to review."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_artwork_state,
    assert_declared_panel,
    assert_panel_not_generated,
    assert_version_is,
)
from test_helpers.constants import (
    ARTWORK_DRAFT,
    ITEM_BENCHMARKED,
    ITEM_CONCEPT,
    NUTRITION_NOT_GENERATED,
    NUTRITION_VALID,
    REVIEW_APPROVE,
)
from test_helpers.fixtures import build_chain, read_artwork_round, read_item
from test_helpers.test_users import (
    DESIGNER_HEADERS,
    REGULATORY_HEADERS,
    SOURCING_HEADERS,
)


def _draft_round_on_a_concept_item(api):
    """A first artwork round opened against an item still at CONCEPT."""
    ctx = build_chain(api, upto=4)
    item = validate_success(
        api.create_item(f.item_payload(ctx["gap_id"]), SOURCING_HEADERS),
        expected_status=201,
    )
    round_ = validate_success(
        api.create_artwork_round(f.artwork_round_payload(item["id"]), DESIGNER_HEADERS),
        expected_status=201,
    )
    ctx["item"] = item
    ctx["item_id"] = item["id"]
    ctx["artwork_round"] = round_
    ctx["artwork_round_id"] = round_["id"]
    return ctx


def test_declared_calories_come_from_the_unrounded_per_serving_amounts(api):
    """Summing the already-rounded macros would print 210; the panel prints 200.

    PRD 3.5: "Second, calories are computed from those unrounded amounts: dietary
    fiber is counted at 2 calories per gram and is therefore subtracted from total
    carbohydrate before the remaining carbohydrate is counted at 4 calories per
    gram; protein is counted at 4 calories per gram and fat at 9 calories per
    gram; the four terms are added together."

    PRD 3.5: "Consider a 50-gram serving of a product carrying, per 100 grams,
    13.0 g fat, 5.0 g saturated fat, 65.2 g carbohydrate, 2.8 g fiber, 30.0 g
    sugars, 24.0 g added sugars, 6.8 g protein and 640 mg sodium: the exact
    calorie figure is 199.7 and `declared_calories` is 200, whereas summing the
    already-rounded macros would give 206.0 and declare 210. Calories must come
    from the unrounded amounts."

    Design: Difficulty/combinatorial_formula/nutrition_calories_from_unrounded_macros
    """
    ctx = _draft_round_on_a_concept_item(api)
    assert_panel_not_generated(ctx["artwork_round"])

    generated = validate_success(
        api.generate_nutrition_panel(ctx["artwork_round_id"], DESIGNER_HEADERS)
    )

    assert generated["declared_calories"] == 200, (
        "the calorie figure must be banded from 199.7, never from rounded macros"
    )
    assert generated["declared_calories"] != 210
    assert_artwork_state(generated, ARTWORK_DRAFT, NUTRITION_VALID)


def test_each_declared_figure_is_banded_once_from_its_own_amount(api):
    """Calories band to tens, macros to halves or wholes, sodium to tens.

    PRD 3.5: "Each macronutrient gram figure is declared as 0.0 when the unrounded
    per-serving amount is below 0.5, as the nearest half gram when it is below 5,
    and as the nearest whole gram at 5 or above; this rule produces
    `declared_fat_g`, `declared_satfat_g`, `declared_carb_g`, `declared_fiber_g`,
    `declared_sugars_g`, `declared_added_sugars_g` and `declared_protein_g`, each
    from its own unrounded per-serving amount."

    PRD 3.5: "Sodium is declared as 0 when the unrounded per-serving amount is
    below 5 milligrams, as the nearest multiple of 5 when it is at most 140, and
    as the nearest multiple of 10 above that, and stored in
    `declared_sodium_mg`."

    PRD 3.5: "Generation carries `nutrition_status` from `NOT_GENERATED → VALID`,
    and re-generation carries it from `INVALIDATED → VALID`; both paths recompute
    all nine declared figures and increment the round's `version`."

    Design: Difficulty/combinatorial_formula/nutrition_calories_from_unrounded_macros
    """
    ctx = _draft_round_on_a_concept_item(api)

    generated = validate_success(
        api.generate_nutrition_panel(ctx["artwork_round_id"], DESIGNER_HEADERS)
    )

    assert_declared_panel(
        generated,
        calories=200,
        fat_g=7,
        satfat_g=2.5,
        carb_g=33,
        fiber_g=1.5,
        sugars_g=15,
        added_sugars_g=12,
        protein_g=3.5,
        sodium_mg=320,
    )
    assert_artwork_state(generated, ARTWORK_DRAFT, NUTRITION_VALID)
    assert_version_is(generated, 2, "artwork round")
    assert read_item(api, ctx["item_id"])["development_status"] == ITEM_CONCEPT


def test_reviewing_a_round_that_is_still_draft_is_rejected(api):
    """Review is defined only from IN_REVIEW, so a DRAFT round cannot be approved.

    PRD 3.5: "Round review belongs to a `RegulatoryReviewer` and requires the round
    to be `IN_REVIEW`; from any other status it is refused with
    `ERR_ARTWORK_STATE_INVALID` (HTTP 409)."

    PRD 3.5: "The creating designer's identifier is captured in
    `designer_user_id`; `reviewer_user_id` stays null until a reviewer decides the
    round. A new round opens at `status` `DRAFT` and `nutrition_status`
    `NOT_GENERATED` with all nine declared panel figures null."

    Design: Corner/state_machines/artwork_review_from_draft_rejected
    """
    ctx = _draft_round_on_a_concept_item(api)

    response = api.review_artwork_round(
        ctx["artwork_round_id"], f.review_payload(REVIEW_APPROVE), REGULATORY_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ARTWORK_STATE_INVALID.value, 409)

    round_ = read_artwork_round(api, ctx["artwork_round_id"])
    assert_artwork_state(round_, ARTWORK_DRAFT, NUTRITION_NOT_GENERATED)
    assert round_["reviewer_user_id"] is None
    assert round_["round_number"] == 1
    assert read_item(api, ctx["item_id"])["development_status"] == ITEM_CONCEPT


def test_submitting_a_round_before_the_panel_is_generated_is_rejected(
    api, draft_artwork_round
):
    """A printed panel has to exist before a reviewer can be asked to clear it.

    PRD 3.5: "It requires the round's `nutrition_status` to be `VALID`; a round
    whose panel is `NOT_GENERATED` or `INVALIDATED` is refused with
    `ERR_NUTRITION_PANEL_INVALID` (HTTP 422)."

    Design: Corner/validations/artwork_submit_before_nutrition_panel_generated_rejected
    """
    round_id = draft_artwork_round["artwork_round_id"]

    response = api.submit_artwork_round(round_id, DESIGNER_HEADERS)
    validate_error(response, ApiErrorId.ERR_NUTRITION_PANEL_INVALID.value, 422)

    round_ = read_artwork_round(api, round_id)
    assert_artwork_state(round_, ARTWORK_DRAFT, NUTRITION_NOT_GENERATED)
    assert_panel_not_generated(round_)
    assert_version_is(round_, 1, "artwork round")
    assert (
        read_item(api, draft_artwork_round["item_id"])["development_status"]
        == ITEM_BENCHMARKED
    )


def test_submitting_a_round_carrying_no_claims_is_rejected(api, valid_panel_round):
    """A valid panel is not enough: a round with nothing to review cannot go up.

    PRD 3.5: "It also requires at least one label claim to exist on the round; a
    round with no claims at all is refused with `ERR_UNAPPROVED_CLAIM_PRESENT`
    (HTTP 422)."

    Design: Corner/validations/artwork_submit_with_no_claims_rejected
    """
    round_id = valid_panel_round["artwork_round_id"]

    response = api.submit_artwork_round(round_id, DESIGNER_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAPPROVED_CLAIM_PRESENT.value, 422)

    round_ = read_artwork_round(api, round_id)
    assert_artwork_state(round_, ARTWORK_DRAFT, NUTRITION_VALID)
    assert round_["declared_calories"] == 200, "the generated panel is untouched"
    _rows, meta = validate_paginated(
        api.list_label_claims(REGULATORY_HEADERS, params={"artwork_round_id": round_id})
    )
    assert meta["total_count"] == 0
    assert (
        read_item(api, valid_panel_round["item_id"])["development_status"]
        == ITEM_BENCHMARKED
    )
