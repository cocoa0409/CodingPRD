"""Difficulty depth index: one rule's two calculation variants diverging on
identical inputs — VOC as-supplied vs as-applied, and DFT spot-average vs
gage 80/20.
"""
from test_helpers import (
    ApiClient,
    assert_quantity,
    create_world,
    drive_to_cured_coat,
    drive_to_prep_approved,
    file_inspection_report,
    make_inspector_headers,
    read_specification,
    record_application,
)

DIVERGENT_SPOT_READINGS = [5.0, 15.0, 15.0, 15.0, 15.0]


def test_voc_as_supplied_vs_as_applied_diverge(api: ApiClient):
    """PRD §3.2: "The **as-supplied** variant is evaluated at specification
    issuance and again at substitution-approval review: the VOC figure is
    simply the coating system's `base_voc_gpl`, ignoring thinner entirely."
    PRD §3.2: "The **as-applied** variant is evaluated once per recorded coat:
    the thinner fraction `thinner_pct_used` actually used is checked against
    the system's `max_thinner_pct` and against the absolute hard cap of 0.25
    of mixed volume — exceeding either limit rejects the recording with
    `ERR_THINNER_LIMIT_EXCEEDED` — and the as-applied VOC is then the
    volume-weighted mix of the two contributions: `base_voc_gpl` scaled by one
    minus `thinner_pct_used`, plus `thinner_voc_gpl` scaled by
    `thinner_pct_used`."

    Design: Difficulty/dual_variant_calc/voc_as_supplied_vs_as_applied_diverge
    """
    world = create_world(
        api,
        jurisdiction_code="US-CA-SCAQMD",
        voc_limit_gpl=340,
        system_overrides={
            "system_code": "SW-DUAL-100",
            "base_voc_gpl": 340,
            "thinner_voc_gpl": 100,
            "max_thinner_pct": 0.10,
        },
    )
    work_order = drive_to_prep_approved(api, world, asset_zone="DECK-NORTH")
    application = record_application(
        api,
        work_order["id"],
        world["applicator"]["id"],
        applied_at="2026-09-10T09:00:00Z",
        thinner_pct_used=0.10,
    )

    spec = read_specification(api, world["spec"]["id"])
    assert_quantity(spec["voc_at_issuance_gpl"], 340.0, label="spec voc_at_issuance_gpl")
    # AS_APPLIED: 340 * (1 - 0.10) + 100 * 0.10 = 316.0
    assert_quantity(application["applied_voc_gpl"], 316.0, label="application applied_voc_gpl")
    assert application["voc_compliant"] is True, "316.0 <= 340 limit must be compliant"
    assert application["applied_voc_gpl"] != spec["voc_at_issuance_gpl"], (
        "the two VOC variants must diverge on the same system once thinner is mixed"
    )


def test_dft_spot_average_vs_gage_80_20_diverge(api: ApiClient):
    """PRD §3.6: "Under the default spot-average variant, the average of
    `spot_dft_readings_mils` is rounded half-up to 1 decimal place before any
    comparison, and the coat passes when that rounded average is at least the
    system's `total_dft_min_mils`, at most its `total_dft_max_mils`, and no
    individual spot reading falls below eighty percent of `total_dft_min_mils`".
    PRD §3.6: "Under the gage 80/20 variant, used when the system's
    `surface_prep_standard` is `SSPC_SP11_POWER_TOOL`, the verdict is
    count-based rather than average-based: the coat passes when the number of
    spots individually within the closed band from `total_dft_min_mils` to
    `total_dft_max_mils` is at least the result of rounding up eighty percent
    of the total number of readings".

    Design: Difficulty/dual_variant_calc/dft_spot_average_vs_gage_80_20_diverge
    """
    world_avg = create_world(
        api,
        system_overrides={"system_code": "SW-DFT-SP10"},
        program_overrides={"program_code": "QP-DFT-SP10"},
        applicator_overrides={"company_name": "Bridge Crew A"},
    )
    world_gage = create_world(
        api,
        with_regulation=False,
        system_overrides={
            "system_code": "SW-DFT-SP11",
            "surface_prep_standard": "SSPC_SP11_POWER_TOOL",
            "min_surface_profile_mils": 1.0,
            "max_surface_profile_mils": 2.5,
        },
        program_overrides={"program_code": "QP-DFT-SP11"},
        applicator_overrides={"company_name": "Mezzanine Crew B"},
    )
    coat_avg = drive_to_cured_coat(api, world_avg, asset_zone="GIRDER-A")
    coat_gage = drive_to_cured_coat(api, world_gage, asset_zone="MEZZ-B")

    report_avg = file_inspection_report(
        api,
        coat_avg["work_order"]["id"],
        coat_avg["application"]["id"],
        spot_dft_readings_mils=DIVERGENT_SPOT_READINGS,
        inspector_headers=make_inspector_headers("inspector-000002"),
    )
    report_gage = file_inspection_report(
        api,
        coat_gage["work_order"]["id"],
        coat_gage["application"]["id"],
        spot_dft_readings_mils=DIVERGENT_SPOT_READINGS,
        inspector_headers=make_inspector_headers("inspector-000003"),
    )

    # SPOT_AVERAGE: mean 13.0 in [8.0, 16.0] but min spot 5.0 < 0.8 * 8.0 == 6.4.
    assert report_avg["dft_verdict"] == "FAIL"
    assert report_avg["overall_verdict"] == "REJECTED"
    # GAGE_80_20: 4 of 5 spots in [8.0, 16.0] >= ceil(0.8 * 5) == 4.
    assert report_gage["dft_verdict"] == "PASS"
    assert report_gage["overall_verdict"] == "ACCEPTED"
    assert report_avg["dft_verdict"] != report_gage["dft_verdict"], (
        "byte-identical spot readings must verdict differently across the two variants"
    )
