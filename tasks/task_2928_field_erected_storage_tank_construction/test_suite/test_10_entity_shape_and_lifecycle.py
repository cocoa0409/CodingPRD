"""Envelope shape, server-minted fields, declared defaults and referential integrity.

Every resource family shares one success envelope, one error envelope and the
same four common properties, and the flat topology means a cross-reference is a
validation rather than a URL shape.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CROSS_TANK_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_SHELL_COURSE_NOT_FOUND,
    ERR_TANK_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_bare_uuid,
    assert_instant,
    assert_common_fields,
    assert_error_envelope_meta,
    assert_list_total,
    assert_money,
    assert_object_envelope,
    assert_spacing,
    assert_thickness,
)
from test_helpers.constants import (
    APP_NOZZLE,
    BASE_EXAMINATION_PCT,
    CLOCK_BASE,
    DESIGN_STANDARD_API_650_BASIC,
    DEFAULT_CONTINUITY_LIMIT_DAYS,
    PKG_PLANNED,
    GHOST_UUID,
    METHOD_ADJACENT_PAIR,
    PHASE_DESIGN_REGISTERED,
    POSTURE_OPEN,
    ROOF_CONE_SUPPORTED,
    SEAM_FIT_READY,
    SEAM_WELDED,
    TANK_MIN_NOMINAL_0_250,
)
from test_helpers.factories import (
    OMIT,
    appurtenance_payload,
    nde_report_payload,
    settlement_survey_payload,
    tank_payload,
    weld_seam_payload,
)
from test_helpers.test_users import AI1, CC1, ES1, PE1, QC1


class TestCreateReadAndListEnvelopes:
    def test_the_tank_create_returns_the_whole_row_in_the_object_envelope(self, api):
        """201 with every input echoed and every computed field already present.

        PRD: "The `data` field contains the resource object or an array of resource
        objects. For 2xx responses with no data, it contains an empty object. Unless
        otherwise noted, operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/entities/tank_creation_returns_full_entity_in_success_envelope
        """
        X.set_clock(api, CLOCK_BASE)

        response = api.create_tank(tank_payload(), PE1)
        tank = assert_object_envelope(response, 201)

        assert tank["tank_tag"] == "TK-101"
        assert tank["diameter_ft"] == pytest.approx(100.0)
        assert tank["shell_height_ft"] == pytest.approx(40.0)
        assert tank["design_liquid_level_ft"] == pytest.approx(40.0)
        assert tank["product_specific_gravity"] == pytest.approx(0.85)
        assert tank["joint_efficiency"] == pytest.approx(1.00)
        assert_thickness(tank["corrosion_allowance_in"], 0.0625, "corrosion allowance")
        assert_thickness(tank["bottom_thickness_in"], 0.25, "bottom thickness")
        assert_thickness(tank["bottom_minimum_thickness_in"], 0.10, "bottom minimum")
        assert tank["assumed_corrosion_rate_ipy"] == pytest.approx(0.01)

        assert_common_fields(tank, expected_version=1)
        assert_thickness(
            tank["min_nominal_thickness_in"], TANK_MIN_NOMINAL_0_250, "min nominal thickness"
        )
        assert tank["construction_phase"] == PHASE_DESIGN_REGISTERED
        assert tank["quality_posture"] == POSTURE_OPEN
        assert tank["open_nonconformance_count"] == 0
        assert tank["weld_reject_rate"] == pytest.approx(0.0)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)
        assert_money(tank["steel_received_lb"], 0.0, "steel received")
        assert_money(tank["steel_allocated_lb"], 0.0, "steel allocated")
        assert tank["active_hydrotest_plan_id"] is None

    def test_reading_a_water_source_returns_the_stored_row_without_bumping_version(self, api):
        """The three ledger fields read back at their initial values, twice over.

        PRD: "A new source starts with `reserved_volume_gal` and
        `consumed_volume_gal` at 0.0 and `available_volume_gal` equal to
        `permitted_volume_gal`."

        Design: Corner/entities/water_source_retrieval_returns_stored_row
        """
        created = X.create_water_source(api, source_name="Municipal Hydrant 12")

        first = assert_object_envelope(api.get_water_source(created["id"], AI1))
        assert first["id"] == created["id"]
        assert first["source_name"] == "Municipal Hydrant 12"
        assert_money(first["permitted_volume_gal"], 2000000.00, "permitted volume")
        assert_money(first["max_concurrent_rate_gpm"], 900.0, "max concurrent rate")
        assert_money(first["water_cost_usd_per_kgal"], 3.33, "water unit cost")
        assert_money(first["disposal_cost_usd_per_kgal"], 2.10, "disposal unit cost")
        assert_money(first["reserved_volume_gal"], 0.00, "reserved volume")
        assert_money(first["consumed_volume_gal"], 0.00, "consumed volume")
        assert_money(first["available_volume_gal"], 2000000.00, "available volume")
        assert first["version"] == 1

        second = X.read_water_source(api, created["id"])
        assert second == first

    def test_the_seam_listing_paginates_with_the_declared_default_limit(self, api):
        """Twelve seams, a default page of ten, then a filtered last page of two.

        PRD: "`limit` defaults to 10 when omitted, may not be smaller than 1, and
        may not be larger than 100."

        Design: Corner/entities/weld_seam_listing_paginates_with_total_count_and_has_more
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        course = X.create_course(api, tank["id"], 1)
        for index in range(1, 13):
            X.create_seam(api, course["id"], f"V{index:02d}", index)

        rows, meta = validate_paginated(api.list_weld_seams(QC1))
        assert meta["total_count"] == 12
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(rows) == 10

        page, page_meta = validate_paginated(
            api.list_weld_seams(QC1, {"shell_course_id": course["id"], "limit": 5, "offset": 10})
        )
        assert page_meta["limit"] == 5
        assert page_meta["offset"] == 10
        assert page_meta["total_count"] == 12
        assert page_meta["has_more"] is False
        assert len(page) == 2
        for row in page:
            assert row["status"] == SEAM_FIT_READY
            assert row["repair_cycle_count"] == 0
            assert row["welder_id"] is None
            assert row["shell_course_id"] == course["id"]


class TestNotFoundAndRequestShape:
    def test_a_well_formed_unknown_uuid_is_a_typed_404(self, api):
        """Not an empty 200 and not a 400.

        PRD: "Identifiers arriving in a URL are resolved left to right, and the resource
        family named by the path segment determines the error identifier when resolution
        fails."

        PRD: "All fourteen carry HTTP 404."

        Design: Corner/entities/get_tank_with_unknown_id_returns_not_found
        """
        X.create_tank(api)

        response = api.get_tank(GHOST_UUID, PE1)
        validate_error(response, ERR_TANK_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"
        assert_error_envelope_meta(response)
        assert_list_total(api.list_tanks(PE1), 1)

    def test_omitting_one_required_input_rejects_the_whole_create(self, api):
        """Every other field is valid, and nothing is persisted.

        PRD: "A shape violation yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/tank_creation_missing_required_field_is_rejected
        """
        validate_error(
            api.create_tank(tank_payload(assumed_corrosion_rate_ipy=OMIT), PE1),
            ERR_INVALID_REQUEST,
            400,
        )
        assert_list_total(api.list_tanks(PE1), 0)

    def test_undeclared_enums_and_out_of_range_numbers_are_all_shape_failures(self, api):
        """Three different offences, one error identifier.

        PRD: "Fifth comes request shape: every required input field present, every enum
        field carrying a declared value, numeric fields numeric and inside their declared
        ranges (weights, volumes, rates and thicknesses non-negative; `fill_percent`
        between 0 and 100 inclusive; `coverage_pct` greater than 0 and at most 100;
        `indication_count` and `film_count` non-negative integers), datetime fields
        parseable as ISO-8601 UTC instants, required arrays non-empty — this covers
        `point_readings`, `spot_readings` and `qualified_positions` — and every spot
        inside `spot_readings` carrying exactly three numeric gauge readings."

        Design: Corner/entities/undeclared_enum_and_out_of_range_numbers_are_rejected
        """
        ctx = X.welded_course(api, seam_labels=("V1",))

        validate_error(
            api.create_tank(
                tank_payload(tank_tag="TK-999", roof_type="FLOATING_ALUMINIUM_DOME"), PE1
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_settlement_survey(
                settlement_survey_payload(ctx.package_id, [100.0] * 8, 120.0), CC1
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_nde_report(
                nde_report_payload(
                    ctx.seam_id, "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z", coverage_pct=0.0
                ),
                QC1,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        assert_list_total(api.list_tanks(PE1, {"tank_tag": "TK-999"}), 0)
        assert_list_total(
            api.list_settlement_surveys(CC1, {"foundation_package_id": ctx.package_id}), 1
        )
        assert_list_total(api.list_nde_reports(QC1, {"weld_seam_id": ctx.seam_id}), 0)
        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_WELDED


class TestDeclaredDefaultsAndComputedFields:
    def test_omitting_every_optional_input_applies_the_declared_defaults(self, api):
        """And the defaulted corrosion allowance shows up inside the thickness result.

        PRD: "`continuity_limit_days` — the number of days the qualification
        survives without further welding — must be at least 1 and defaults to 180."

        Design: Corner/entities/tank_and_welder_creation_apply_declared_defaults
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(
            api, design_standard=OMIT, corrosion_allowance_in=OMIT, roof_type=OMIT
        )
        assert tank["design_standard"] == DESIGN_STANDARD_API_650_BASIC
        assert_thickness(tank["corrosion_allowance_in"], 0.0625, "corrosion allowance")
        assert tank["roof_type"] == ROOF_CONE_SUPPORTED

        welder = X.create_welder(api)
        assert welder["continuity_limit_days"] == DEFAULT_CONTINUITY_LIMIT_DAYS
        assert_instant(
            welder["continuity_expires_at_utc"], "2026-11-28T00:00:00Z", "continuity expiry"
        )

        package = X.create_foundation_package(api, tank["id"], ringwall_top_elevation_ft=OMIT)
        assert package["ringwall_top_elevation_ft"] == pytest.approx(0.0)

        course = X.create_course(api, tank["id"], 1)
        assert_thickness(
            course["required_thickness_design_in"], 0.434, "required design thickness"
        )

    def test_the_package_derives_its_spacing_and_differential_envelope(self, api):
        """Neither figure is an endpoint input, yet both come back on the create.

        PRD: "The arc distance between adjacent monitoring points, stored as
        `point_spacing_in`, is the tank circumference in inches divided by the number of
        monitoring points: take the mathematical constant pi (3.141592653589793), multiply
        by `diameter_ft`, multiply by the 12 inches in a foot, and divide by
        `monitoring_point_count`; the result is rounded half up to 4 decimal places."

        PRD: "The package is created with `status` at `PLANNED`, `baseline_survey_id`
        null, and `decided_by_user_id`, `decided_at_utc` and `decision_remarks` all null."

        Design: Corner/entities/foundation_package_computes_spacing_and_allowable_differential
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)

        package = X.create_foundation_package(
            api, tank["id"], settlement_evaluation_method=METHOD_ADJACENT_PAIR
        )

        assert_spacing(package["point_spacing_in"], 471.2389)
        assert_thickness(
            package["allowable_differential_in"], 2.356, "allowable differential"
        )
        assert package["status"] == PKG_PLANNED
        assert package["baseline_survey_id"] is None

        rows, _ = assert_list_total(
            api.list_foundation_packages(CC1, {"tank_id": tank["id"]}), 1
        )
        assert rows[0]["id"] == package["id"]

    def test_client_supplied_system_fields_are_ignored_not_honoured(self, api):
        """The server mints its own id, version and derived state.

        PRD: "Unknown fields in a body are ignored rather than rejected."

        Design: Corner/entities/tank_create_system_fields_input_ignored
        """
        seeded = "11111111-1111-4111-8111-111111111111"

        tank = assert_object_envelope(
            api.create_tank(
                tank_payload(
                    id=seeded,
                    version=99,
                    construction_phase="COMMISSIONED",
                    quality_posture="FROZEN",
                    min_nominal_thickness_in=9.999,
                ),
                PE1,
            ),
            201,
        )

        assert tank["id"] != seeded
        assert_bare_uuid(tank["id"])
        assert tank["version"] == 1
        assert tank["construction_phase"] == PHASE_DESIGN_REGISTERED
        assert tank["quality_posture"] == POSTURE_OPEN
        assert_thickness(
            tank["min_nominal_thickness_in"], TANK_MIN_NOMINAL_0_250, "min nominal thickness"
        )
        validate_error(api.get_tank(seeded, PE1), ERR_TANK_NOT_FOUND, 404)


class TestReferentialIntegrityOfBodyForeignKeys:
    def test_an_unknown_parent_course_is_a_404_on_the_parent_family(self, api):
        """The same request with the real parent succeeds, so the 404 is the link.

        PRD: "Sixth comes resolution of foreign keys supplied in the body, in the
        order the endpoint declares its inputs, using the same mapping."

        Design: Corner/entities/weld_seam_requires_an_existing_parent_shell_course
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        course = X.create_course(api, tank["id"], 1)

        validate_error(
            api.create_weld_seam(weld_seam_payload(GHOST_UUID), ES1),
            ERR_SHELL_COURSE_NOT_FOUND,
            404,
        )

        seam = assert_object_envelope(
            api.create_weld_seam(weld_seam_payload(course["id"]), ES1), 201
        )
        assert seam["shell_course_id"] == course["id"]
        assert seam["status"] == SEAM_FIT_READY
        assert_list_total(api.list_weld_seams(ES1, {"shell_course_id": course["id"]}), 1)

    def test_a_host_course_on_another_tank_is_a_cross_reference_conflict(self, api):
        """Both ids resolve, so the refusal is a validation and not a 404.

        PRD: "A `ProjectEngineer` places one against a `tank_id` and a
        `host_shell_course_id`, the course whose plate the penetration or attachment lands
        on, which must belong to the same tank or the request is rejected with
        `ERR_CROSS_TANK_REFERENCE`."

        Design: Corner/entities/appurtenance_host_course_must_belong_to_the_same_tank
        """
        X.set_clock(api, CLOCK_BASE)
        first = X.create_tank(api)
        second = X.create_tank(api, tank_tag="TK-102")
        other_course = X.create_course(api, second["id"], 1)

        validate_error(
            api.create_appurtenance(
                appurtenance_payload(
                    first["id"], other_course["id"], appurtenance_type=APP_NOZZLE
                ),
                PE1,
            ),
            ERR_CROSS_TANK_REFERENCE,
            409,
        )

        assert_list_total(api.list_appurtenances(PE1, {"tank_id": first["id"]}), 0)
        assert_list_total(
            api.list_appurtenances(PE1, {"host_shell_course_id": other_course["id"]}), 0
        )
