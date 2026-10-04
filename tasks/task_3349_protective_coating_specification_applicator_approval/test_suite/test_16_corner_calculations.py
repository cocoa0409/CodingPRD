"""Corner breadth index (calculations): the gage 80/20 DFT variant selected
by power-tool preparation, the inclusive holiday-density boundary, and the
interior-tank salt tightening.
"""
from test_helpers import (
    ApiClient,
    begin_prep_inspection,
    create_work_order,
    create_world,
    drive_to_cured_coat,
    file_inspection_report,
    file_prep_inspection,
    read_work_order,
)


def test_dft_gage_8020_variant_applies_for_power_tool_prep(api: ApiClient):
    """PRD §3.6: "Under the gage 80/20 variant, used when the system's
    `surface_prep_standard` is `SSPC_SP11_POWER_TOOL`, the verdict is
    count-based rather than average-based: the coat passes when the number of
    spots individually within the closed band from `total_dft_min_mils` to
    `total_dft_max_mils` is at least the result of rounding up eighty percent
    of the total number of readings — so with five readings at least four
    must be in band — and under this variant the average may fall below the
    specification minimum while the coat still passes."

    Design: Corner/calculations/dft_gage_8020_variant_applies_for_power_tool_prep
    """
    world = create_world(
        api,
        asset_type="STRUCTURAL_STEEL",
        system_overrides={
            "system_code": "SW-SP11",
            "surface_prep_standard": "SSPC_SP11_POWER_TOOL",
            "min_surface_profile_mils": 1.0,
            "max_surface_profile_mils": 3.0,
            "coat_count": 2,
            "total_dft_min_mils": 6.0,
            "total_dft_max_mils": 12.0,
            "adhesion_min_psi": 400,
        },
        applicator_overrides={"company_name": "Gage Coaters"},
    )
    coat = drive_to_cured_coat(api, world, asset_zone="Z1")

    report = file_inspection_report(
        api, coat["work_order"]["id"], coat["application"]["id"],
        spot_dft_readings_mils=[7.0, 8.0, 9.0, 10.0, 5.0],
        adhesion_readings_psi=[500],
    )

    # 4 of 5 spots within [6.0, 12.0] >= ceil(0.8 * 5) == 4; the 5.0 spot is
    # tolerated by the count-based variant.
    assert report["dft_verdict"] == "PASS"


def test_holiday_density_boundary_inclusive_pass(api: ApiClient):
    """PRD §3.6: "passes when the density is at most the applicable limit —
    an inclusive boundary, so a density exactly equal to the limit passes.
    The limit is 0.1 holidays per square metre for every asset type except
    `TANK_INTERIOR`, where it tightens to 0.0 and any single holiday fails
    the coat."

    Design: Corner/calculations/holiday_density_boundary_inclusive_pass
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-HOL"},
        applicator_overrides={"company_name": "Holiday Coaters"},
    )
    coat = drive_to_cured_coat(api, world, asset_zone="Z1")

    report = file_inspection_report(
        api, coat["work_order"]["id"], coat["application"]["id"],
        holiday_count=1, tested_area_m2=10.0,
    )

    assert report["holiday_verdict"] == "PASS", "density 1/10 == 0.1 <= 0.1 inclusive"
    assert report["overall_verdict"] == "ACCEPTED"


def test_surface_prep_strict_tank_salt_limit_tightens(api: ApiClient):
    """PRD §3.5: "when the project's `asset_type` is `TANK_INTERIOR` the salt
    limit tightens to 5.0, so a reading of 7.0 that would pass on a bridge
    fails on an interior tank lining."
    PRD §3.5: "A `FAILED` filing bounces the work order back to `SCHEDULED`".

    Design: Corner/calculations/surface_prep_strict_tank_salt_limit_tightens
    """
    world = create_world(
        api,
        asset_type="TANK_INTERIOR",
        system_overrides={"system_code": "SW-TANK"},
        applicator_overrides={"company_name": "Tank Coaters"},
    )
    work_order = create_work_order(
        api, world["project"]["id"], world["spec"]["id"], world["applicator"]["id"],
        asset_zone="Z1",
    )
    begin_prep_inspection(api, world["project"]["id"], work_order["id"], world["applicator"]["id"])

    inspection = file_prep_inspection(api, work_order["id"], soluble_salt_ug_cm2=7.0)

    assert inspection["result"] == "FAILED"
    assert "SALT_EXCEEDED" in inspection["failure_reasons"]
    assert read_work_order(api, work_order["id"])["status"] == "SCHEDULED"
