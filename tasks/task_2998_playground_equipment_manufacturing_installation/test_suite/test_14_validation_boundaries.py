"""Inclusive boundaries on the safety, accessibility and calendar validations.

Each test drives both sides of the boundary it names: the value that is still
admitted and the neighbouring value that is refused.
"""

from test_helpers import (
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
OFFICER = TEST_USERS["compliance_officer_headers"]
CLIENT = TEST_USERS["client_representative_headers"]


# --------------------------------------------------------------------------
# Local setup helpers
# --------------------------------------------------------------------------
def _validated_post_design(standard_id, post_model_id, client_name, **project_overrides):
    """A CONSULTATION project with one toddler area holding one VALIDATED post
    placement of three units, plus an ISSUED rendering."""
    project = fx.create_project_in_consultation(
        client_name=client_name, **project_overrides
    )
    area = fx.create_play_area(project["id"])
    fx.create_validated_placement(
        area["id"], post_model_id, x_start_cm=200, quantity=3
    )
    rendering = fx.issue_rendering(project["id"], standard_id)
    return project, area, rendering


def _firm_quote(project_id, rendering_id, valid_until):
    response = api_client.create_quote(
        f.quote_payload(
            project_id,
            rendering_id,
            fx.project_version(project_id),
            variant="FIRM",
            valid_until=valid_until,
        ),
        CONSULTANT,
    )
    return validate_success(response, 201)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_cross_age_group_clearance_holds_at_exactly_the_minimum_clearance():
    """A gap of 169 clear centimetres is refused and a gap of exactly 183 is admitted.

    PRD: "Clear separation is counted as the number of whole centimetres strictly between the two intervals: take the later interval's start, subtract the earlier interval's end, subtract one more, and the result must be greater than or equal to `min_use_zone_clearance_cm`."

    PRD: "Two spatial checks then run, and both are deliberately restricted to placements already in `VALIDATED` status"

    Design: Corner/validations/cross_age_group_clearance_holds_at_exactly_min_use_zone_clearance_cm
    """
    scenario = fx.setup_two_area_project(
        project_overrides={"client_name": "Clearance Park"},
        toddler_area_overrides={"axis_origin_cm": 0, "axis_length_cm": 400},
        preschool_area_overrides={"axis_origin_cm": 400, "axis_length_cm": 1000},
    )
    standard = scenario["standard"]
    preschool_area = scenario["preschool_area"]
    assert standard["min_use_zone_clearance_cm"] == 183, (
        "the governing edition demands 183 clear centimetres, got "
        f"{standard['min_use_zone_clearance_cm']}"
    )

    anchor = fx.create_validated_placement(
        scenario["toddler_area"]["id"],
        scenario["toddler_post"]["id"],
        x_start_cm=200,
        quantity=3,
    )
    assert anchor["status"] == "VALIDATED", (
        f"expected VALIDATED, got {anchor['status']}"
    )
    assert anchor["use_zone_start_cm"] == 170, (
        f"expected use_zone_start_cm 170, got {anchor['use_zone_start_cm']}"
    )
    assert anchor["use_zone_end_cm"] == 230, (
        f"expected use_zone_end_cm 230, got {anchor['use_zone_end_cm']}"
    )

    too_close = fx.create_placement(
        preschool_area["id"], scenario["preschool_post"]["id"], x_start_cm=430
    )
    exactly_clear = fx.create_placement(
        preschool_area["id"], scenario["preschool_post"]["id"], x_start_cm=444
    )
    assert (too_close["use_zone_start_cm"], too_close["use_zone_end_cm"]) == (400, 460), (
        "expected the near zone at 400..460, got "
        f"{too_close['use_zone_start_cm']}..{too_close['use_zone_end_cm']}"
    )
    assert (
        exactly_clear["use_zone_start_cm"],
        exactly_clear["use_zone_end_cm"],
    ) == (414, 474), (
        "expected the far zone at 414..474, got "
        f"{exactly_clear['use_zone_start_cm']}..{exactly_clear['use_zone_end_cm']}"
    )
    assert (
        a.separation_cm(anchor["use_zone_end_cm"], too_close["use_zone_start_cm"]) == 169
    ), "the near zone leaves only 169 clear centimetres"
    assert (
        a.separation_cm(anchor["use_zone_end_cm"], exactly_clear["use_zone_start_cm"])
        == 183
    ), "the far zone leaves exactly 183 clear centimetres"

    refused = api_client.validate_placement(too_close["id"], CONSULTANT)
    validate_error(refused, ApiErrorId.ERR_AGE_GROUP_SEPARATION_VIOLATION)
    unchanged = fx.get_placement(too_close["id"])
    assert unchanged["status"] == "DRAFT", (
        f"the refused placement stays DRAFT, got {unchanged['status']}"
    )
    assert unchanged["version"] == too_close["version"], (
        f"expected version {too_close['version']} unchanged, got {unchanged['version']}"
    )

    assert (
        too_close["use_zone_start_cm"] <= exactly_clear["use_zone_end_cm"]
        and exactly_clear["use_zone_start_cm"] <= too_close["use_zone_end_cm"]
    ), "the two preschool zones do overlap, so only their DRAFT status can clear the way"

    promoted = validate_success(
        api_client.validate_placement(exactly_clear["id"], CONSULTANT)
    )
    assert promoted["status"] == "VALIDATED", (
        "a separation of exactly the minimum satisfies the rule, got "
        f"{promoted['status']}"
    )
    a.assert_version_bumped_by(exactly_clear, promoted, 1)

    preschool_now = fx.get_play_area(preschool_area["id"])
    assert preschool_now["critical_fall_height_cm"] == 0, (
        "ground-level posts contribute no fall height, got "
        f"{preschool_now['critical_fall_height_cm']}"
    )


def test_fall_height_ceiling_is_per_age_band_and_admits_the_exact_maximum():
    """A toddler deck of exactly 122 cm is admitted while 140 cm is refused, yet the same 140 cm geometry clears the school-age column.

    PRD: "The substantive check is dimensional: the model's `deck_height_cm` must not exceed the resolved edition's ceiling for the model's own `age_group` — `max_fall_height_cm_toddler` for `TODDLER_6_23M`, `max_fall_height_cm_preschool` for `PRESCHOOL_2_5`, `max_fall_height_cm_school_age` for `SCHOOL_AGE_5_12` — and a model that stands taller than its band permits is refused with `ERR_FALL_HEIGHT_EXCEEDS_STANDARD`."

    PRD: "`critical_fall_height_cm` is the largest `deck_height_cm` among the models of the area's placements whose `status` is `DRAFT` or `VALIDATED`; when that set is empty the value is 0."

    Design: Corner/validations/fall_height_limit_is_per_age_band_and_admits_the_exact_maximum
    """
    standard = fx.create_active_standard()
    assert standard["max_fall_height_cm_toddler"] == 122, (
        f"expected a toddler ceiling of 122, got {standard['max_fall_height_cm_toddler']}"
    )
    assert standard["max_fall_height_cm_school_age"] == 244, (
        "expected a school-age ceiling of 244, got "
        f"{standard['max_fall_height_cm_school_age']}"
    )

    at_the_ceiling = fx.create_certified_model(f.deck_model_payload())
    assert at_the_ceiling["deck_height_cm"] == 122, (
        f"expected a 122 cm deck, got {at_the_ceiling['deck_height_cm']}"
    )
    assert at_the_ceiling["certification_status"] == "CERTIFIED", (
        "a height equal to the band ceiling is admitted, got "
        f"{at_the_ceiling['certification_status']}"
    )

    over_the_ceiling = fx.create_model(
        f.deck_model_payload(
            sku="DECK-TDL-140", deck_height_cm=140, unit_price_cents=71500
        )
    )
    refused = api_client.certify_component_model(over_the_ceiling["id"], OFFICER)
    validate_error(refused, ApiErrorId.ERR_FALL_HEIGHT_EXCEEDS_STANDARD)
    unchanged = validate_success(
        api_client.get_component_model(over_the_ceiling["id"], ADMIN)
    )
    assert unchanged["certification_status"] == "UNCERTIFIED", (
        f"the refused model stays UNCERTIFIED, got {unchanged['certification_status']}"
    )
    assert unchanged["certified_against_standard_id"] is None, (
        "a refused certification pins nothing, got "
        f"{unchanged['certified_against_standard_id']}"
    )
    assert unchanged["version"] == over_the_ceiling["version"], (
        f"expected version {over_the_ceiling['version']} unchanged, "
        f"got {unchanged['version']}"
    )

    same_height_other_band = fx.create_certified_model(
        f.deck_model_payload(
            sku="DECK-SCH-140",
            age_group="SCHOOL_AGE_5_12",
            deck_height_cm=140,
            unit_price_cents=71500,
        )
    )
    assert same_height_other_band["deck_height_cm"] == 140, (
        f"expected a 140 cm deck, got {same_height_other_band['deck_height_cm']}"
    )
    assert same_height_other_band["certification_status"] == "CERTIFIED", (
        "140 cm is legal in the school-age band, so the bound is read per band, got "
        f"{same_height_other_band['certification_status']}"
    )

    project = fx.create_project_in_consultation(client_name="Height Park")
    area = fx.create_play_area(project["id"])
    placement = validate_success(
        api_client.create_placement(
            area["id"],
            f.placement_payload(at_the_ceiling["id"], x_start_cm=700, quantity=1),
            CONSULTANT,
        ),
        201,
    )
    assert placement["status"] == "DRAFT", (
        f"a new placement is born DRAFT, got {placement['status']}"
    )
    assert placement["use_zone_start_cm"] == 517, (
        f"expected use_zone_start_cm 517, got {placement['use_zone_start_cm']}"
    )
    assert placement["use_zone_end_cm"] == 883, (
        f"expected use_zone_end_cm 883, got {placement['use_zone_end_cm']}"
    )

    area_now = fx.get_play_area(area["id"])
    assert area_now["critical_fall_height_cm"] == 122, (
        "the area carries the tallest admitted deck, got "
        f"{area_now['critical_fall_height_cm']}"
    )
    assert area_now["required_surfacing_depth_cm"] == 28, (
        f"expected required_surfacing_depth_cm 28, got "
        f"{area_now['required_surfacing_depth_cm']}"
    )
    a.assert_required_surfacing_depth(area_now, "CLAY", expected=28)


def test_accessible_route_check_fires_only_when_the_project_flag_is_set():
    """Two structurally identical designs diverge on the project flag alone while the governing edition waives the route.

    PRD: "And accessibility: when either the project's `accessible_route_required` is true **or** the `ACTIVE` edition's `requires_accessible_route` is true, every play area must hold at least one placement in `DRAFT` or `VALIDATED` whose model has `accessible_transfer_ready` set to true; a shortfall is refused with `ERR_ACCESSIBLE_ROUTE_MISSING` (HTTP 422)."

    PRD: "The optional boolean `accessible_route_required` records whether the client's contract independently mandates an accessible transfer point in every play area and defaults to true when omitted."

    Design: Corner/validations/accessible_route_check_fires_only_when_the_project_flag_is_set
    """
    standard = fx.create_active_standard()
    assert standard["requires_accessible_route"] is False, (
        "the governing edition must waive the route so the project flag decides, got "
        f"{standard['requires_accessible_route']}"
    )
    post = fx.create_certified_model(f.post_model_payload())
    assert post["accessible_transfer_ready"] is False, (
        "the only placed model offers no accessible transfer point, got "
        f"{post['accessible_transfer_ready']}"
    )

    required = validate_success(
        api_client.create_project(
            f.drop_fields(
                f.project_payload(client_name="Route Required Park"),
                "accessible_route_required",
            ),
            CONSULTANT,
        ),
        201,
    )
    assert required["accessible_route_required"] is True, (
        "an omitted accessible_route_required defaults to true, got "
        f"{required['accessible_route_required']}"
    )
    fx.start_consultation(required["id"])
    required_area = fx.create_play_area(required["id"])
    fx.create_validated_placement(
        required_area["id"], post["id"], x_start_cm=200, quantity=3
    )
    before = fx.get_project(required["id"])

    refused = api_client.issue_rendering(
        required["id"], f.rendering_payload(standard["id"]), CONSULTANT
    )
    validate_error(refused, ApiErrorId.ERR_ACCESSIBLE_ROUTE_MISSING)
    after = fx.get_project(required["id"])
    assert after["version"] == before["version"], (
        f"the refused call leaves the project at version {before['version']}, "
        f"got {after['version']}"
    )
    assert after["design_status"] == "CONSULTATION", (
        f"the refused call leaves the project in CONSULTATION, got {after['design_status']}"
    )
    assert_paginated_list(
        api_client.list_project_renderings(required["id"], CONSULTANT), 0
    )

    waived, waived_area, waived_rendering = _validated_post_design(
        standard["id"],
        post["id"],
        "Route Waived Park",
        accessible_route_required=False,
    )
    assert waived["accessible_route_required"] is False, (
        "the waived project carries the flag it was given, got "
        f"{waived['accessible_route_required']}"
    )
    area_now = fx.get_play_area(waived_area["id"])
    assert area_now["critical_fall_height_cm"] == 0, (
        f"expected critical_fall_height_cm 0, got {area_now['critical_fall_height_cm']}"
    )
    assert area_now["required_surfacing_depth_cm"] == 15, (
        "the absolute floor applies with nothing to fall from, got "
        f"{area_now['required_surfacing_depth_cm']}"
    )
    assert area_now["surfacing_depth_cm"] == 30, (
        f"expected the specified depth 30, got {area_now['surfacing_depth_cm']}"
    )

    quote = _firm_quote(waived["id"], waived_rendering["id"], "2026-12-31")
    assert quote["status"] == "ISSUED", (
        f"expected ISSUED, got {quote['status']}"
    )
    assert quote["variant"] == "FIRM", f"expected FIRM, got {quote['variant']}"
    assert quote["subtotal_cents"] == 32250, (
        f"expected subtotal 32250, got {quote['subtotal_cents']}"
    )
    assert quote["freight_cents"] == 51750, (
        f"expected freight 51750, got {quote['freight_cents']}"
    )
    assert quote["discount_cents"] == 0, (
        f"expected no discount, got {quote['discount_cents']}"
    )
    assert quote["total_cents"] == 84000, (
        f"expected total 84000, got {quote['total_cents']}"
    )
    a.assert_quote_arithmetic(quote)
    a.assert_freight(quote)


def test_quote_accept_allowed_on_the_valid_until_date_and_refused_the_next_day():
    """The last second of valid_until still accepts and the first second of the next day does not.

    PRD: "the logical clock's date must be on or before `valid_until`, or the attempt is refused with `ERR_QUOTE_EXPIRED`"

    Design: Corner/validations/quote_accept_allowed_on_valid_until_date_and_refused_the_next_day
    """
    standard = fx.create_active_standard()
    post = fx.create_certified_model(f.post_model_payload())

    on_time_project, _, on_time_rendering = _validated_post_design(
        standard["id"], post["id"], "Deadline Quote Park One"
    )
    late_project, _, late_rendering = _validated_post_design(
        standard["id"], post["id"], "Deadline Quote Park Two"
    )
    on_time_quote = _firm_quote(
        on_time_project["id"], on_time_rendering["id"], "2026-08-10"
    )
    late_quote = _firm_quote(late_project["id"], late_rendering["id"], "2026-08-10")

    for quote in (on_time_quote, late_quote):
        assert quote["valid_until"] == "2026-08-10", (
            f"expected valid_until 2026-08-10, got {quote['valid_until']}"
        )
        assert quote["status"] == "ISSUED", (
            f"expected ISSUED, got {quote['status']}"
        )
        assert quote["total_cents"] == 84000, (
            f"expected total 84000, got {quote['total_cents']}"
        )

    rendered_before = fx.get_project(on_time_project["id"])["design_status"]
    fx.set_clock("2026-08-10T23:59:59Z")
    accepted = validate_success(
        api_client.accept_quote(on_time_quote["id"], CLIENT)
    )
    assert accepted["status"] == "ACCEPTED", (
        "the clock's date equals valid_until, so acceptance stands, got "
        f"{accepted['status']}"
    )
    a.assert_version_bumped_by(on_time_quote, accepted, 1)
    assert fx.get_project(on_time_project["id"])["design_status"] == rendered_before, (
        "accepting a quote moves no project status"
    )

    fx.set_clock_to_date("2026-08-11")
    refused = api_client.accept_quote(late_quote["id"], CLIENT)
    validate_error(refused, ApiErrorId.ERR_QUOTE_EXPIRED)
    still_issued = fx.get_quote(late_quote["id"])
    assert still_issued["status"] == "ISSUED", (
        f"the refused quote stays ISSUED, got {still_issued['status']}"
    )
    assert still_issued["version"] == late_quote["version"], (
        f"expected version {late_quote['version']} unchanged, "
        f"got {still_issued['version']}"
    )
    assert fx.get_project(late_project["id"])["design_status"] == rendered_before, (
        "the refused acceptance moves no project status either"
    )


def test_pledge_collection_allowed_on_the_deadline_date_and_refused_after():
    """A collection on the deadline date lands and the same call the next day is refused.

    PRD: "The logical clock's date must be on or before the project's `fundraising_deadline`, or the collection is refused with `ERR_FUNDRAISING_DEADLINE_PASSED`."

    Design: Corner/validations/pledge_collection_allowed_on_the_deadline_date_and_refused_after
    """
    project = fx.create_project(
        client_name="Deadline Fund Park", fundraising_deadline="2026-08-10"
    )
    assert project["fundraising_deadline"] == "2026-08-10", (
        f"expected the deadline 2026-08-10, got {project['fundraising_deadline']}"
    )
    assert project["funds_collected_cents"] == 0, (
        f"a new project holds no funds, got {project['funds_collected_cents']}"
    )

    on_time = fx.create_pledge(
        project["id"], amount_cents=25000, pledged_at="2026-08-01"
    )
    late = fx.create_pledge(
        project["id"], amount_cents=25000, pledged_at="2026-08-01"
    )
    for pledge in (on_time, late):
        assert pledge["status"] == "PLEDGED", (
            f"a recorded pledge is born PLEDGED, got {pledge['status']}"
        )
    assert fx.get_project(project["id"])["funds_collected_cents"] == 0, (
        "a pledge contributes nothing until it is collected"
    )

    fx.set_clock("2026-08-10T12:00:00Z")
    collected = validate_success(api_client.collect_pledge(on_time["id"], CLIENT))
    assert collected["status"] == "COLLECTED", (
        "the clock's date equals the deadline, so the collection stands, got "
        f"{collected['status']}"
    )
    after_first = fx.get_project(project["id"])
    assert after_first["funds_collected_cents"] == 25000, (
        f"expected funds_collected_cents 25000, got "
        f"{after_first['funds_collected_cents']}"
    )

    fx.set_clock_to_date("2026-08-11")
    refused = api_client.collect_pledge(late["id"], CLIENT)
    validate_error(refused, ApiErrorId.ERR_FUNDRAISING_DEADLINE_PASSED)
    still_pledged = validate_success(api_client.get_pledge(late["id"], CLIENT))
    assert still_pledged["status"] == "PLEDGED", (
        f"the refused pledge stays PLEDGED, got {still_pledged['status']}"
    )
    unchanged = fx.get_project(project["id"])
    assert unchanged["funds_collected_cents"] == 25000, (
        "the refused collection adds nothing, got "
        f"{unchanged['funds_collected_cents']}"
    )
    assert unchanged["version"] == after_first["version"], (
        f"expected version {after_first['version']} unchanged, "
        f"got {unchanged['version']}"
    )
