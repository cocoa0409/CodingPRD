"""Difficulty depth index: combinatorial formulas — the surface-preparation
verdict's asset-typed salt branch, and the warranty split's pinned rounding
order on an odd-cent exposure.
"""
from test_helpers import (
    PREP_FAILURE_PENALTY,
    SCORE_INITIAL,
    ApiClient,
    assert_cents,
    assert_score,
    create_world,
    create_work_order,
    begin_prep_inspection,
    drive_to_completed_work_order,
    file_prep_inspection,
    issue_warranty,
    read_applicator,
    read_work_order,
)


def test_surface_prep_verdict_strict_tank_branch(api: ApiClient):
    """PRD §3.5: "Third, the `soluble_salt_ug_cm2` must be at most 10.0
    micrograms per square centimetre — a reading of exactly 10.0 passes —
    otherwise `SALT_EXCEEDED` is recorded; however, when the project's
    `asset_type` is `TANK_INTERIOR` the salt limit tightens to 5.0, so a
    reading of 7.0 that would pass on a bridge fails on an interior tank
    lining."
    PRD §3.5: "A `FAILED` filing bounces the work order back to `SCHEDULED`
    and assesses the 25-point preparation-failure penalty against the
    applicator's `quality_history_score`".

    Design: Difficulty/combinatorial_formula/surface_prep_verdict_strict_tank_branch
    """
    world = create_world(
        api,
        asset_type="TANK_INTERIOR",
        system_overrides={"system_code": "SW-PREP-TANK"},
        applicator_overrides={"company_name": "Tank Liners Inc"},
    )
    work_order = create_work_order(
        api, world["project"]["id"], world["spec"]["id"], world["applicator"]["id"],
        asset_zone="TANK-FLOOR",
    )
    begin_prep_inspection(api, world["project"]["id"], work_order["id"], world["applicator"]["id"])

    inspection = file_prep_inspection(
        api,
        work_order["id"],
        soluble_salt_ug_cm2=7.0,
        inspector_headers=None,
    )

    assert inspection["result"] == "FAILED"
    assert inspection["failure_reasons"] == ["SALT_EXCEEDED"], (
        "standard matches, profile 3.0 in [2.0, 4.0], dew spread 5.0 >= 3.0: "
        "only the STRICT_TANK salt branch may fire"
    )
    assert read_work_order(api, work_order["id"])["status"] == "SCHEDULED"
    assert_score(
        read_applicator(api, world["applicator"]["id"])["quality_history_score"],
        SCORE_INITIAL - PREP_FAILURE_PENALTY,
    )


def test_warranty_split_rounding_remainder_absorbs_cent(api: ApiClient):
    """PRD §3.7: "At issuance the manufacturer's `material_share_cents` is
    half the exposure — the exposure multiplied by 0.50, rounded half-up to a
    whole cent — and the applicator's `application_share_cents` is the
    remainder, absorbing any rounding residue."
    PRD §3.7: "The split into shares follows one invariant at all times:
    `material_share_cents` plus `application_share_cents` must equal
    `exposure_cents` exactly."

    Design: Difficulty/combinatorial_formula/warranty_split_rounding_remainder_absorbs_cent
    """
    world = create_world(
        api,
        warranty_budget_cents=500_000,
        system_overrides={"system_code": "SW-SPLIT-100"},
        applicator_overrides={"company_name": "Riverbend Applicators"},
    )
    completion = drive_to_completed_work_order(api, world, asset_zone="TRUSS-EAST")

    warranty = issue_warranty(
        api,
        world["project"]["id"],
        completion["work_order"]["id"],
        term_years=10,
        exposure_cents=100_001,
    )

    # round_half_up(100001 * 0.50) == round_half_up(50000.5) == 50001.
    assert_cents(warranty["material_share_cents"], 50_001, "material_share_cents")
    # Remainder absorbs the rounding; an independent second round would give 50001.
    assert_cents(warranty["application_share_cents"], 50_000, "application_share_cents")
    assert warranty["material_share_cents"] + warranty["application_share_cents"] == 100_001
    assert warranty["manufacturer_fault_pct"] == 50
