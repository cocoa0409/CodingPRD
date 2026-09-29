"""Error-catalogue behaviours: pagination bounds, per-entity not-found codes,
placement creation gates, warranty and parts-availability gates, and the
cancellation / provisional-quote gates.

Every test drives real HTTP endpoints against an empty database with the logical
clock at 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_paginated_list,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["manufacturer_admin_headers"]
CONSULTANT = TEST_USERS["design_consultant_headers"]
CLIENT = TEST_USERS["client_representative_headers"]


# --------------------------------------------------------------------------
# Local composites (built from fixtures primitives only)
# --------------------------------------------------------------------------
def _setup_three_models():
    """Three catalogue rows — certification is irrelevant to a listing."""
    return [
        fx.create_model(f.post_model_payload()),
        fx.create_model(f.deck_model_payload()),
        fx.create_model(f.slide_model_payload()),
    ]


def _assert_list_meta(response):
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        f"expected a meta.api_request_id string, got {meta.get('api_request_id')!r}"
    )
    assert isinstance(meta.get("api_request_timestamp"), str), (
        "expected a meta.api_request_timestamp string, got "
        f"{meta.get('api_request_timestamp')!r}"
    )
    a.canonical_instant(meta["api_request_timestamp"])


def _setup_uninstalled_deck_design(project_overrides=None):
    """A CONSULTATION project (never installed) holding one DRAFT deck placement."""
    scenario = fx.setup_project_with_toddler_area(project_overrides=project_overrides)
    scenario["placement"] = fx.create_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="CEDAR",
        x_start_cm=700,
        quantity=1,
    )
    return scenario


def _setup_provisional_quote_design():
    """A RENDERED project with one VALIDATED post placement and an ISSUED
    PROVISIONAL quote."""
    scenario = fx.setup_single_placement_design(
        model_key="post",
        project_overrides={"client_name": "Cancel Park"},
        placement_overrides={"x_start_cm": 200, "quantity": 3},
    )
    scenario["quote"] = fx.issue_quote(
        scenario["project"]["id"],
        scenario["rendering"]["id"],
        variant="PROVISIONAL",
        valid_until="2026-12-31",
    )
    return scenario


# --------------------------------------------------------------------------
# Pagination bounds
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
    ids=["limit_below_minimum", "limit_above_maximum", "offset_below_minimum"],
)
def test_pagination_arguments_outside_the_declared_range_are_refused(params):
    """limit 0, limit 101 and offset -1 are each refused as invalid pagination.

    PRD: "A `limit` that is not an integer, or is below 1, or above 100, and an `offset` that is not an integer or is below 0, are both rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/list_pagination_bounds_are_enforced_at_zero_and_one_hundred_one
    """
    _setup_three_models()
    refused = api_client.list_component_models(ADMIN, params=params)
    validate_error(refused, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_pagination_accepts_its_declared_minimum_and_maximum():
    """limit 1 and limit 100 are admissible, and the meta block echoes them.

    PRD: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0, with no upper bound."

    Design: Corner/errors/list_pagination_bounds_are_enforced_at_zero_and_one_hundred_one
    """
    _setup_three_models()

    first_page = api_client.list_component_models(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = assert_paginated_list(first_page, 3)
    _assert_list_meta(first_page)
    assert len(data) == 1, f"expected one row on a page of one, got {len(data)}"
    assert meta["limit"] == 1, f"expected limit 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"expected offset 0, got {meta['offset']}"
    assert meta["has_more"] is True, (
        f"expected has_more True, got {meta['has_more']} with two rows still to come"
    )

    last_page = api_client.list_component_models(ADMIN, params={"limit": 1, "offset": 2})
    data, meta = assert_paginated_list(last_page, 3)
    _assert_list_meta(last_page)
    assert len(data) == 1, f"expected one row on the final page, got {len(data)}"
    assert meta["has_more"] is False, (
        f"expected has_more False, got {meta['has_more']} on the final page"
    )

    whole_page = api_client.list_component_models(
        ADMIN, params={"limit": 100, "offset": 0}
    )
    data, meta = assert_paginated_list(whole_page, 3)
    _assert_list_meta(whole_page)
    assert len(data) == 3, f"expected all three rows, got {len(data)}"
    assert meta["limit"] == 100, f"expected limit 100, got {meta['limit']}"
    assert meta["has_more"] is False, (
        f"expected has_more False, got {meta['has_more']} when the page holds everything"
    )


# --------------------------------------------------------------------------
# Per-entity not-found codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("/standards/", ApiErrorId.ERR_STANDARD_NOT_FOUND),
        ("/component-models/", ApiErrorId.ERR_MODEL_NOT_FOUND),
        ("/projects/", ApiErrorId.ERR_PROJECT_NOT_FOUND),
        ("/play-areas/", ApiErrorId.ERR_PLAY_AREA_NOT_FOUND),
        ("/renderings/", ApiErrorId.ERR_RENDERING_NOT_FOUND),
        ("/quotes/", ApiErrorId.ERR_QUOTE_NOT_FOUND),
        ("/pledges/", ApiErrorId.ERR_PLEDGE_NOT_FOUND),
        ("/orders/", ApiErrorId.ERR_ORDER_NOT_FOUND),
        ("/installers/", ApiErrorId.ERR_INSTALLER_NOT_FOUND),
        ("/installation-jobs/", ApiErrorId.ERR_JOB_NOT_FOUND),
        ("/warranty-claims/", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ],
)
def test_unknown_ids_report_the_owning_entity_not_found_code(path, expected_error):
    """Each collection answers an unknown id with its own 404 code.

    PRD: "Each entity has its own not-found code, and all of them are HTTP 404: `ERR_STANDARD_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PLAY_AREA_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_RENDERING_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALLER_NOT_FOUND`, `ERR_JOB_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_resolve_to_the_owning_entity_not_found_code
    """
    fx.create_model(f.deck_model_payload())
    refused = api_client.raw_get(f"{path}{NON_EXISTENT_UUID}", ADMIN)
    validate_error(refused, expected_error.value)


def test_a_nested_create_resolves_its_left_hand_segment_first():
    """Creating a play area under an unknown project is a missing project.

    PRD: "Path segments are resolved strictly left to right, and the first segment that fails to resolve determines the error."

    Design: Corner/errors/unknown_ids_resolve_to_the_owning_entity_not_found_code
    """
    fx.create_model(f.deck_model_payload())

    refused = api_client.raw_post(
        f"/projects/{NON_EXISTENT_UUID}/play-areas",
        f.play_area_payload(),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)

    _, meta = assert_paginated_list(api_client.list_component_models(ADMIN), 1)
    assert meta["total_count"] == 1, (
        f"expected the catalogue to still hold one row, got {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Placement creation gates
# --------------------------------------------------------------------------
def _setup_gate_catalogue():
    """A toddler area plus an uncertified deck and a certified preschool post."""
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Gate Park"}
    )
    scenario["uncertified"] = fx.create_model(
        f.deck_model_payload(sku="DECK-TDL-122-UC")
    )
    scenario["preschool"] = fx.create_certified_model(
        f.post_model_payload(sku="POST-PRE-000", age_group="PRESCHOOL_2_5")
    )
    return scenario


def _place_the_certified_deck(scenario):
    """The control placement: the certified toddler deck at x=700."""
    accepted = validate_success(
        api_client.create_placement(
            scenario["area"]["id"],
            f.placement_payload(
                scenario["deck"]["id"],
                color_choice="CEDAR",
                x_start_cm=700,
                quantity=1,
            ),
            CONSULTANT,
        ),
        201,
    )
    assert accepted["use_zone_start_cm"] == 517, (
        f"expected 517, got {accepted['use_zone_start_cm']}"
    )
    assert accepted["use_zone_end_cm"] == 883, (
        f"expected 883, got {accepted['use_zone_end_cm']}"
    )
    _, meta = assert_paginated_list(
        api_client.list_area_placements(scenario["area"]["id"], CONSULTANT), 1
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one accepted placement, got {meta['total_count']}"
    )


def test_placement_create_refuses_an_uncertified_model():
    """An UNCERTIFIED catalogue model cannot be placed.

    PRD: "The model must be `CERTIFIED`, or the placement is refused with `ERR_MODEL_NOT_CERTIFIED`; it must not have reached `DISCONTINUED`, or the placement is refused with `ERR_MODEL_DISCONTINUED`."

    Design: Corner/errors/placement_create_gates_report_certification_age_and_bounds_codes
    """
    scenario = _setup_gate_catalogue()
    refused = api_client.create_placement(
        scenario["area"]["id"],
        f.placement_payload(
            scenario["uncertified"]["id"],
            color_choice="CEDAR",
            x_start_cm=700,
            quantity=1,
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_MODEL_NOT_CERTIFIED.value)
    _place_the_certified_deck(scenario)


def test_placement_create_refuses_a_model_from_another_age_band():
    """A preschool model cannot be dropped into a toddler area.

    PRD: "The model's `age_group` must equal the owning area's `age_group`, otherwise `ERR_AGE_GROUP_MISMATCH` (HTTP 422) — a preschool slide cannot be dropped into a toddler area."

    Design: Corner/errors/placement_create_gates_report_certification_age_and_bounds_codes
    """
    scenario = _setup_gate_catalogue()
    refused = api_client.create_placement(
        scenario["area"]["id"],
        f.placement_payload(
            scenario["preschool"]["id"],
            color_choice="CEDAR",
            x_start_cm=700,
            quantity=1,
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_AGE_GROUP_MISMATCH.value)
    _place_the_certified_deck(scenario)


def test_placement_create_refuses_a_zone_outside_the_area_interval():
    """A use zone that starts left of the area origin is out of bounds.

    PRD: "That whole interval must lie inside the owning area's half-open axis interval, meaning the start must be at or after `axis_origin_cm` and the end must be strictly before `axis_origin_cm` plus `axis_length_cm`; a zone that pokes outside its area is refused with `ERR_USE_ZONE_OUT_OF_BOUNDS` (HTTP 422)."

    Design: Corner/errors/placement_create_gates_report_certification_age_and_bounds_codes
    """
    scenario = _setup_gate_catalogue()
    refused = api_client.create_placement(
        scenario["area"]["id"],
        f.placement_payload(
            scenario["deck"]["id"],
            color_choice="CEDAR",
            x_start_cm=10,
            quantity=1,
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_USE_ZONE_OUT_OF_BOUNDS.value)
    _place_the_certified_deck(scenario)


# --------------------------------------------------------------------------
# Warranty and parts-availability gates
# --------------------------------------------------------------------------
def test_a_warranty_claim_against_an_uninstalled_project_is_refused():
    """A project that was never installed cannot carry a warranty claim.

    PRD: "The project must actually have been installed, meaning its `installed_on` is non-null; a claim against an uninstalled project is refused with `ERR_PROJECT_NOT_INSTALLED` (HTTP 422)."

    Design: Corner/errors/warranty_and_parts_availability_gates_fire_without_an_installed_project
    """
    scenario = _setup_uninstalled_deck_design(
        project_overrides={"client_name": "Uninstalled Park"}
    )
    assert scenario["project"]["installed_on"] is None, (
        f"expected installed_on null, got {scenario['project']['installed_on']!r}"
    )

    refused = api_client.create_warranty_claim(
        f.warranty_claim_payload(
            scenario["project"]["id"],
            scenario["placement"]["id"],
            "2026-08-01",
            quantity=1,
        ),
        CLIENT,
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_INSTALLED.value)

    _, meta = assert_paginated_list(api_client.list_warranty_claims(ADMIN), 0)
    assert meta["total_count"] == 0, (
        f"expected no claim to have been recorded, got {meta['total_count']}"
    )


def test_a_parts_purchase_after_the_support_year_is_refused():
    """The same purchase succeeds in 2026 and is refused once the clock reads 2041.

    PRD: "The logical clock's current year must be no later than the replacement model's `parts_support_until_year`, since the plant stops sourcing parts for a family after that year, and a late purchase is refused with `ERR_PARTS_NO_LONGER_AVAILABLE`."

    Design: Corner/errors/warranty_and_parts_availability_gates_fire_without_an_installed_project
    """
    scenario = _setup_uninstalled_deck_design(
        project_overrides={"client_name": "Uninstalled Park"}
    )
    placement_id = scenario["placement"]["id"]
    assert scenario["deck"]["parts_support_until_year"] == 2040, (
        "expected parts support through 2040, got "
        f"{scenario['deck']['parts_support_until_year']}"
    )

    in_support = validate_success(
        api_client.retrofit_placement(
            placement_id, f.retrofit_payload(scenario["deck"]["id"], 1), CONSULTANT
        )
    )
    assert in_support["retrofit_unit_price_cents"] == 64350, (
        f"expected 64350, got {in_support['retrofit_unit_price_cents']}"
    )
    assert in_support["retrofit_handling_cents"] == 3500, (
        f"expected 3500, got {in_support['retrofit_handling_cents']}"
    )
    assert in_support["retrofit_total_cents"] == 67850, (
        f"expected 67850, got {in_support['retrofit_total_cents']}"
    )
    assert in_support["legacy_surcharge_applied"] is False, (
        "expected no surcharge on an ACTIVE model, got "
        f"{in_support['legacy_surcharge_applied']!r}"
    )

    fx.set_clock("2041-01-01T00:00:00Z")
    refused = api_client.retrofit_placement(
        placement_id, f.retrofit_payload(scenario["deck"]["id"], 1), CONSULTANT
    )
    validate_error(refused, ApiErrorId.ERR_PARTS_NO_LONGER_AVAILABLE.value)

    unchanged = fx.get_placement(placement_id)
    assert unchanged["retrofit_model_id"] == scenario["deck"]["id"], (
        f"expected the first purchase to stand, got {unchanged['retrofit_model_id']!r}"
    )
    assert unchanged["retrofit_quantity"] == 1, (
        f"expected 1, got {unchanged['retrofit_quantity']}"
    )
    assert unchanged["retrofit_unit_price_cents"] == 64350, (
        f"expected 64350, got {unchanged['retrofit_unit_price_cents']}"
    )
    assert unchanged["retrofit_handling_cents"] == 3500, (
        f"expected 3500, got {unchanged['retrofit_handling_cents']}"
    )
    assert unchanged["retrofit_total_cents"] == 67850, (
        f"expected 67850, got {unchanged['retrofit_total_cents']}"
    )
    assert unchanged["version"] == in_support["version"], (
        f"expected version {in_support['version']} to stand after the refused call, "
        f"got {unchanged['version']}"
    )


# --------------------------------------------------------------------------
# Provisional-quote and cancelled-project gates
# --------------------------------------------------------------------------
def test_a_provisional_quote_cannot_be_accepted():
    """A budgetary quote is refused at acceptance and stays ISSUED.

    PRD: "its `variant` must be `FIRM`, since a budgetary number is not contractually acceptable and attempting it is refused with `ERR_PROVISIONAL_QUOTE_NOT_ACCEPTABLE`"

    Design: Corner/errors/provisional_accept_and_cancelled_project_gates_report_their_own_codes
    """
    scenario = _setup_provisional_quote_design()
    quote_id = scenario["quote"]["id"]
    assert scenario["quote"]["variant"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {scenario['quote']['variant']}"
    )

    refused = api_client.accept_quote(quote_id, CLIENT)
    validate_error(refused, ApiErrorId.ERR_PROVISIONAL_QUOTE_NOT_ACCEPTABLE.value)

    still_issued = fx.get_quote(quote_id)
    assert still_issued["status"] == "ISSUED", (
        f"expected ISSUED, got {still_issued['status']} after the refused acceptance"
    )


def test_a_cancelled_project_cannot_be_cancelled_again():
    """The first cancellation lands; the second is refused.

    PRD: "a project already `INSTALLED`, `AUDITED` or `CANCELLED` cannot be cancelled and the attempt is refused with `ERR_PROJECT_NOT_CANCELLABLE`"

    Design: Corner/errors/provisional_accept_and_cancelled_project_gates_report_their_own_codes
    """
    scenario = _setup_provisional_quote_design()
    project_id = scenario["project"]["id"]

    cancelled = validate_success(api_client.cancel_project(project_id, CONSULTANT))
    assert cancelled["design_status"] == "CANCELLED", (
        f"expected CANCELLED, got {cancelled['design_status']}"
    )

    refused = api_client.cancel_project(project_id, CONSULTANT)
    validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_CANCELLABLE.value)


def test_cancelling_a_project_expires_its_issued_quote_and_leaves_no_funds():
    """Cancellation carries the ISSUED quote to EXPIRED and recomputes the money.

    PRD: "Alongside the hops, every `FundraisingPledge` of the project whose `status` is `PLEDGED` or `COLLECTED` moves to `REFUNDED`, after which `funds_collected_cents` and all four allocation buckets are recomputed and therefore all become 0; and every `Quote` of the project still in `ISSUED` moves to `EXPIRED`."

    Design: Corner/errors/provisional_accept_and_cancelled_project_gates_report_their_own_codes
    """
    scenario = _setup_provisional_quote_design()
    project_id = scenario["project"]["id"]

    validate_success(api_client.cancel_project(project_id, CONSULTANT))

    quote = fx.get_quote(scenario["quote"]["id"])
    assert quote["status"] == "EXPIRED", (
        f"expected EXPIRED, got {quote['status']} after the project was cancelled"
    )
    project = fx.get_project(project_id)
    assert project["funds_collected_cents"] == 0, (
        f"expected 0, got {project['funds_collected_cents']}"
    )
    a.assert_cents(project["funds_collected_cents"], "funds_collected_cents")


def test_a_cancelled_project_refuses_new_pledges():
    """A cancelled project is not fundable and records no pledge.

    PRD: "A project accepts pledges only while its `design_status` is outside `CANCELLED`, `INSTALLED` and `AUDITED`; in any of those three it is refused with `ERR_PROJECT_NOT_FUNDABLE`."

    Design: Corner/errors/provisional_accept_and_cancelled_project_gates_report_their_own_codes
    """
    scenario = _setup_provisional_quote_design()
    project_id = scenario["project"]["id"]
    validate_success(api_client.cancel_project(project_id, CONSULTANT))

    refused = api_client.create_pledge(
        project_id,
        f.pledge_payload(amount_cents=25000, pledged_at="2026-08-01"),
        CLIENT,
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_FUNDABLE.value)

    _, meta = assert_paginated_list(
        api_client.list_project_pledges(project_id, ADMIN), 0
    )
    assert meta["total_count"] == 0, (
        f"expected no pledge to have been recorded, got {meta['total_count']}"
    )
