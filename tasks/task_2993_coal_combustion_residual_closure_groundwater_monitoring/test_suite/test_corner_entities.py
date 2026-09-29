"""Breadth probes over the declared entity surface.

Field sets, defaults, computed blocks, pagination meta, per-family not-found
identifiers and the referential rules that hold the flat topology together.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CAP_NOT_APPLICABLE,
    CLOSURE_STATE_ACTIVE,
    DISCIPLINE_CIVIL,
    DISCIPLINE_GEOTECHNICAL,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    EVENT_TYPE_BACKGROUND,
    GHOST_UUID,
    LICENSE_ACTIVE,
    LICENSE_SUSPENDED,
    PARAM_SULFATE,
    PHASE_DETECTION,
    POSTING_ANNUAL_GW_REPORT,
    POSTING_STATUS_POSTED,
    POSTURE_COMPLIANT,
    STABILITY_ADEQUATE,
    STABILITY_UNASSESSED,
    TIMELINESS_PENDING,
    UOM_MG_PER_L,
    VERDICT_UNRESTRICTED,
    WELL_ROLE_BACKGROUND,
    WELL_ROLE_DOWNGRADIENT,
    WELL_STATUS_CERTIFIED,
)
from test_helpers.test_users import PUBLIC_VIEWER_HEADERS, UTILITY_ADMIN_HEADERS


def test_unit_registration_returns_the_whole_declared_record_and_mints_its_program(api):
    """One registration populates the computed block and the child program at once.

    PRD: `ash_in_place_tons` starts equal to `original_ash_in_place_tons` and `ash_mass_balance_ok` starts true
    PRD: Every unit gets exactly one groundwater monitoring program, cascade-created at registration in the `DETECTION` phase with `sampling_frequency` set to `SEMIANNUAL` and `network_certified` false, and the new program's identifier is returned on the unit as `monitoring_program_id`
    Design: Corner/entities/unit_creation_returns_the_full_declared_field_set_and_mints_a_monitoring_program
    """
    response = api.create_unit(
        factories.unit_payload("IMP-0101", unit_name="Ash Pond 101"), UTILITY_ADMIN_HEADERS
    )
    unit = validate_success(response, 201)
    a.assert_versioned(unit, 1, "unit")
    assert unit["unit_code"] == "IMP-0101"
    assert unit["plant_code"] == "PLNT01"
    a.assert_tons(unit["original_ash_in_place_tons"], 480000, "original_ash_in_place_tons")
    assert unit["location_restriction_verdict"] == VERDICT_UNRESTRICTED
    assert unit["demonstration_required"] is False
    assert unit["closure_state"] == CLOSURE_STATE_ACTIVE
    assert unit["cap_integrity_state"] == CAP_NOT_APPLICABLE
    a.assert_date(unit["closure_deadline_date"], "2031-03-31", "closure_deadline_date")
    assert unit["granted_extension_months"] == 0
    a.assert_tons(unit["ash_in_place_tons"], 480000, "ash_in_place_tons")
    assert unit["ash_mass_balance_ok"] is True
    assert unit["governing_stability_verdict"] == STABILITY_UNASSESSED
    assert unit["compliance_posture"] == POSTURE_COMPLIANT
    assert unit["closure_timeliness"] == TIMELINESS_PENDING
    a.assert_string_list(unit["overdue_posting_types"], [], "overdue_posting_types")
    assert unit["late_posting_count"] == 0

    program_id = unit["monitoring_program_id"]
    assert program_id is not None, "registration must return a monitoring_program_id"
    program = validate_success(api.get_program(program_id, UTILITY_ADMIN_HEADERS))
    assert program["phase"] == PHASE_DETECTION
    assert program["unit_id"] == unit["id"]


def test_well_detail_read_returns_the_interval_exactly_as_installed(api):
    """The stored row round-trips; nothing is re-derived or defaulted on read.

    PRD: The well is created with `well_status` `CERTIFIED`, meaning a licensed hydrogeologist stands behind its construction, and with `decommissioned_on` and `decommission_reason` null
    Design: Corner/entities/well_retrieval_by_id_returns_the_stored_screen_interval
    """
    world = fixtures.seed_unit(api, "IMP-0102")
    well = fixtures.install_well(
        api,
        world["unit_id"],
        world["hydro_headers"],
        "BG-01",
        WELL_ROLE_BACKGROUND,
        screen_top_ft=22.00,
        screen_bottom_ft=42.00,
    )
    stored = validate_success(api.get_well(well["id"], world["hydro_headers"]))
    assert stored["id"] == well["id"]
    assert stored["unit_id"] == world["unit_id"]
    assert stored["well_code"] == "BG-01"
    assert stored["well_role"] == WELL_ROLE_BACKGROUND
    assert stored["aquifer_zone"] == "UPPER SAND"
    a.assert_two_dp(stored["screen_top_ft"], 22.00, "screen_top_ft")
    a.assert_two_dp(stored["screen_bottom_ft"], 42.00, "screen_bottom_ft")
    a.assert_date(stored["installed_on"], "2024-06-01", "installed_on")
    assert stored["well_status"] == WELL_STATUS_CERTIFIED
    assert stored["decommissioned_on"] is None
    assert stored["decommission_reason"] is None


def test_posting_pages_report_the_pre_window_total_and_derive_has_more(api):
    """total_count counts the matches, not the page, and the ceiling on limit is 100.

    PRD: `total_count` giving the number of records matching the filters before the page window is applied, and `has_more` set true exactly when records matching the filters remain beyond the current window
    PRD: `satisfied_obligation` is true exactly when the posting's `status` is `POSTED` and the unit carries a non-null obligation date for that type — which means an annual groundwater report never satisfies an obligation
    PRD: A `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST` (HTTP 400)
    Design: Corner/entities/public_posting_listing_paginates_with_total_count_and_has_more
    """
    world = fixtures.seed_unit(api, "IMP-0103")
    first = fixtures.post_document(api, world, POSTING_ANNUAL_GW_REPORT, "2026-07-01")
    second = fixtures.post_document(
        api,
        world,
        POSTING_ANNUAL_GW_REPORT,
        "2026-07-15",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )

    page_one, meta_one = validate_paginated(
        api.list_public_postings(
            PUBLIC_VIEWER_HEADERS, {"unit_id": world["unit_id"], "limit": 1, "offset": 0}
        )
    )
    a.assert_page_meta(meta_one, 1, 0, 2, True)
    assert len(page_one) == 1

    page_two, meta_two = validate_paginated(
        api.list_public_postings(
            PUBLIC_VIEWER_HEADERS, {"unit_id": world["unit_id"], "limit": 1, "offset": 1}
        )
    )
    a.assert_page_meta(meta_two, 1, 1, 2, False)
    assert len(page_two) == 1

    assert page_one[0]["id"] != page_two[0]["id"]
    assert {page_one[0]["id"], page_two[0]["id"]} == {first["id"], second["id"]}
    for row in page_one + page_two:
        assert row["status"] == POSTING_STATUS_POSTED
        assert row["satisfied_obligation"] is False
        assert row["days_late"] == 0

    over_the_ceiling = api.list_public_postings(
        PUBLIC_VIEWER_HEADERS, {"unit_id": world["unit_id"], "limit": 200}
    )
    validate_error(over_the_ceiling, ApiErrorId.INVALID_REQUEST.value)


def test_absent_identifiers_report_the_not_found_error_of_their_own_family(api):
    """One absent identifier, five routes, five different 404 identifiers.

    PRD: Not-found refusals are grouped by family, and each family has its own error identifier
    Design: Corner/entities/unknown_ids_are_not_found_per_entity_family
    """
    probes = (
        (api.get_unit(GHOST_UUID, UTILITY_ADMIN_HEADERS), ApiErrorId.UNIT_NOT_FOUND),
        (
            api.get_closure_plan(GHOST_UUID, UTILITY_ADMIN_HEADERS),
            ApiErrorId.CLOSURE_ENTITY_NOT_FOUND,
        ),
        (api.get_program(GHOST_UUID, UTILITY_ADMIN_HEADERS), ApiErrorId.MONITORING_ENTITY_NOT_FOUND),
        (
            api.get_reuse_agreement(GHOST_UUID, UTILITY_ADMIN_HEADERS),
            ApiErrorId.REUSE_ENTITY_NOT_FOUND,
        ),
        (api.get_public_posting(GHOST_UUID, UTILITY_ADMIN_HEADERS), ApiErrorId.POSTING_NOT_FOUND),
    )
    for response, expected in probes:
        error = validate_error(response, expected.value)
        assert error["message"].strip(), f"{expected.value} must carry a non-empty message"


def test_unit_creation_rejects_a_missing_and_an_out_of_enum_liner_class(api):
    """Absence and out-of-domain are both malformed bodies, and neither writes a row.

    PRD: On every write, the request body is well formed: all required fields present, each of its declared type, enum values within range
    Design: Corner/entities/unit_creation_missing_required_liner_class_is_rejected
    """
    missing = api.create_unit(
        factories.unit_payload("IMP-0104", unit_name="Ash Pond 104", liner_class=factories.OMIT),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(missing, ApiErrorId.INVALID_REQUEST.value)

    out_of_enum = api.create_unit(
        factories.unit_payload(
            "IMP-0104", unit_name="Ash Pond 104", liner_class="GEOMEMBRANE_ONLY"
        ),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(out_of_enum, ApiErrorId.INVALID_REQUEST.value)

    _page, meta = validate_paginated(api.list_units(UTILITY_ADMIN_HEADERS, {"plant_code": "PLNT01"}))
    assert meta["total_count"] == 0, "a rejected registration must not leave a unit behind"


def test_license_status_defaults_to_active_and_an_explicit_status_stands(api):
    """The default applies when the field is absent and never overwrites a supplied one.

    PRD: An optional `license_status` may be supplied at registration and defaults to `ACTIVE`; the alternatives are `SUSPENDED` and `LAPSED`
    Design: Corner/entities/professional_created_without_license_status_defaults_to_active
    """
    defaulted = validate_success(
        api.create_professional(
            factories.professional_payload("Dana Reyes", "PE-11001", DISCIPLINE_GEOTECHNICAL),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    assert defaulted["license_status"] == LICENSE_ACTIVE

    explicit = validate_success(
        api.create_professional(
            factories.professional_payload(
                "Owen Park", "PE-22002", DISCIPLINE_CIVIL, license_status=LICENSE_SUSPENDED
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    assert explicit["license_status"] == LICENSE_SUSPENDED

    active_rows, active_meta = validate_paginated(
        api.list_professionals(UTILITY_ADMIN_HEADERS, {"license_status": LICENSE_ACTIVE})
    )
    assert active_meta["total_count"] == 1
    a.assert_ids(active_rows, [defaulted["id"]], "active professionals")


def test_bad_enum_inverted_screen_interval_and_over_precise_pga_are_all_malformed(api):
    """Three different type constraints, three 400s, and no coercion of any of them.

    PRD: The top of the screen must be at least 0 feet and the bottom must be strictly deeper than the top; both accept at most 2 decimal places
    PRD: A separation, distance, screen depth, settlement or percentage figure accepts at most 2 decimal places; a seismic peak ground acceleration accepts at most 3
    PRD: A payload that exceeds the declared precision for a field, or that falls outside a field's declared numeric bounds, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)
    Design: Corner/entities/well_role_outside_the_enum_and_over_precise_pga_are_rejected
    """
    world = fixtures.seed_unit(api, "IMP-0107")

    bad_role = api.create_well(
        factories.well_payload(world["unit_id"], "SG-01", "SIDEGRADIENT"), world["hydro_headers"]
    )
    validate_error(bad_role, ApiErrorId.INVALID_REQUEST.value)

    inverted = api.create_well(
        factories.well_payload(
            world["unit_id"], "BG-09", WELL_ROLE_BACKGROUND, screen_top_ft=42.00, screen_bottom_ft=22.00
        ),
        world["hydro_headers"],
    )
    validate_error(inverted, ApiErrorId.INVALID_REQUEST.value)

    over_precise = api.create_unit(
        factories.unit_payload("IMP-0108", unit_name="Ash Pond 108", seismic_pga_g=0.0501),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(over_precise, ApiErrorId.INVALID_REQUEST.value)

    _wells, well_meta = validate_paginated(
        api.list_wells(world["hydro_headers"], {"unit_id": world["unit_id"]})
    )
    assert well_meta["total_count"] == 0

    unit_rows, unit_meta = validate_paginated(
        api.list_units(UTILITY_ADMIN_HEADERS, {"plant_code": "PLNT01"})
    )
    assert unit_meta["total_count"] == 1
    a.assert_ids(unit_rows, [world["unit_id"]], "units at PLNT01")


def test_stability_assessments_are_append_only_and_the_newest_one_governs(api):
    """Correction is by superseding append: no version counter, no edit, no delete.

    PRD: The governing row carries `superseded` false and every other row of that unit carries `superseded` true
    PRD: It sets `stability_posting_due_date` to the governing assessment's `assessed_on` plus 30 days
    Design: Corner/entities/stability_assessment_is_immutable_and_carries_no_version_field
    """
    world = fixtures.seed_unit(api, "IMP-0109")

    first = validate_success(
        api.create_stability_assessment(
            factories.stability_payload(world["unit_id"], "2026-07-15"), world["geotech_headers"]
        ),
        201,
    )
    second = validate_success(
        api.create_stability_assessment(
            factories.stability_payload(
                world["unit_id"],
                "2026-07-20",
                factor_of_safety_static=1.50,
                factor_of_safety_seismic=1.00,
                factor_of_safety_liquefaction=1.20,
            ),
            world["geotech_headers"],
        ),
        201,
    )
    a.assert_append_only(first, "first assessment")
    a.assert_append_only(second, "second assessment")

    stored_first = validate_success(
        api.get_stability_assessment(first["id"], world["geotech_headers"])
    )
    stored_second = validate_success(
        api.get_stability_assessment(second["id"], world["geotech_headers"])
    )
    assert stored_first["superseded"] is True
    assert stored_second["superseded"] is False
    assert stored_first["verdict"] == STABILITY_ADEQUATE
    a.assert_two_dp(stored_first["factor_of_safety_static"], 1.60, "superseded static factor")
    a.assert_two_dp(stored_first["factor_of_safety_seismic"], 1.10, "superseded seismic factor")
    a.assert_two_dp(
        stored_first["factor_of_safety_liquefaction"], 1.30, "superseded liquefaction factor"
    )
    assert stored_second["verdict"] == STABILITY_ADEQUATE
    a.assert_string_list(stored_second["deficient_criteria"], [], "deficient_criteria")

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["governing_stability_verdict"] == STABILITY_ADEQUATE
    a.assert_date(unit["stability_posting_due_date"], "2026-08-19", "stability_posting_due_date")


def test_well_creation_against_an_unknown_unit_is_a_unit_not_found(api):
    """The parent reference is checked before the body is honoured, and no orphan lands.

    PRD: Every referenced unit identifier exists, else `ERR_UNIT_NOT_FOUND`
    Design: Corner/entities/well_creation_against_an_unknown_unit_is_not_found
    """
    world = fixtures.seed_unit(api, "IMP-0110")

    orphan = api.create_well(
        factories.well_payload(GHOST_UUID, "BG-01", WELL_ROLE_BACKGROUND, screen_top_ft=22.00, screen_bottom_ft=42.00),
        world["hydro_headers"],
    )
    validate_error(orphan, ApiErrorId.UNIT_NOT_FOUND.value)

    accepted = validate_success(
        api.create_well(
            factories.well_payload(
                world["unit_id"], "BG-01", WELL_ROLE_BACKGROUND, screen_top_ft=22.00, screen_bottom_ft=42.00
            ),
            world["hydro_headers"],
        ),
        201,
    )
    assert accepted["unit_id"] == world["unit_id"]

    well_rows, well_meta = validate_paginated(
        api.list_wells(world["hydro_headers"], {"unit_id": world["unit_id"]})
    )
    assert well_meta["total_count"] == 1
    a.assert_ids(well_rows, [accepted["id"]], "wells of the registered unit")


def test_result_naming_a_well_of_another_unit_is_refused_as_a_cross_reference(api):
    """Both rows exist and are valid; it is the pair that the topology forbids.

    PRD: The well must belong to the same disposal unit as the round's program; a well from another unit is refused with `ERR_RESULT_WELL_NOT_IN_PROGRAM` (HTTP 422)
    PRD: A successful append increments the round's `result_count` by 1 and its `version` by 1
    PRD: For a detected result, `effective_value` is the concentration rounded half up to 4 decimal places
    Design: Corner/entities/analytical_result_naming_a_well_of_another_unit_is_rejected
    """
    world = fixtures.seed_unit(api, "IMP-0111")
    world["wells"] = fixtures.install_standard_network(
        api, world["unit_id"], world["hydro_headers"], fixtures.FOUR_BACKGROUND_WELLS
    )
    fixtures.configure_program(api, world["program_id"], world["hydro_headers"])
    fixtures.certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")

    other_unit = fixtures.create_unit(api, "IMP-0112", plant_code="PLNT02")
    foreign_well = fixtures.install_well(
        api,
        other_unit["id"],
        world["hydro_headers"],
        "DG-01",
        WELL_ROLE_DOWNGRADIENT,
        aquifer_zone="LOWER SAND",
    )

    event = fixtures.open_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "BG-R1",
        "2025-06-01",
        EVENT_TYPE_BACKGROUND,
    )
    opened_version = event["version"]

    refused = api.create_analytical_result(
        factories.result_payload(
            event["id"], foreign_well["id"], 0.5000, opened_version, PARAM_SULFATE
        ),
        world["hydro_headers"],
    )
    validate_error(refused, ApiErrorId.RESULT_WELL_NOT_IN_PROGRAM.value)

    untouched = fixtures.read_round(api, event["id"], world["hydro_headers"])
    assert untouched["result_count"] == 0
    assert untouched["version"] == opened_version

    local_well = world["wells"]["DG-01"]
    accepted = validate_success(
        api.create_analytical_result(
            factories.result_payload(
                event["id"], local_well["id"], 0.5000, opened_version, PARAM_SULFATE
            ),
            world["hydro_headers"],
        ),
        201,
    )
    assert accepted["well_id"] == local_well["id"]
    assert accepted["unit_of_measure"] == UOM_MG_PER_L
    a.assert_four_dp(accepted["effective_value"], 0.5000, "effective_value")

    advanced = fixtures.read_round(api, event["id"], world["hydro_headers"])
    assert advanced["result_count"] == 1
    assert advanced["version"] == opened_version + 1
