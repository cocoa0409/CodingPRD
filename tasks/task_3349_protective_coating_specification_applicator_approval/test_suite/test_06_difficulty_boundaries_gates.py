"""Difficulty depth index: inclusive numeric boundaries (holiday density,
warranty budget) and cross-entity state gates (qualification-gated work-order
creation, cure-gated inspection filing).
"""
from test_helpers import (
    INSPECTOR_HEADERS,
    PROJECT_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    advance_clock_and_mark_cured,
    assert_cents,
    certify_qualification,
    create_world,
    drive_to_cured_coat,
    drive_to_prep_approved,
    drive_to_completed_work_order,
    file_inspection_report,
    inspection_report_payload,
    issue_warranty,
    read_application,
    read_project,
    read_qualification,
    record_application,
    validate_error,
    validate_success,
    work_order_payload,
)


def test_holiday_density_inclusive_boundary(api: ApiClient):
    """PRD §3.6: "The **holiday verdict** `holiday_verdict` computes the
    defect density as `holiday_count` divided by `tested_area_m2`, in full
    precision, and passes when the density is at most the applicable limit —
    an inclusive boundary, so a density exactly equal to the limit passes."

    Design: Difficulty/boundary_precision_check/holiday_density_inclusive_boundary
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-HOL-100"},
        applicator_overrides={"company_name": "Holiday Testers"},
    )
    coat = drive_to_cured_coat(api, world, asset_zone="SPAN-WEST")

    report = file_inspection_report(
        api, coat["work_order"]["id"], coat["application"]["id"],
        holiday_count=1, tested_area_m2=10.0,
    )

    # density == 1 / 10.0 == 0.1 exactly; 0.1 <= 0.1 satisfies the boundary.
    assert report["holiday_verdict"] == "PASS"
    assert report["dft_verdict"] == "PASS"
    assert report["overall_verdict"] == "ACCEPTED"


def test_warranty_budget_inclusive_equality(api: ApiClient):
    """PRD §3.7: "The project's budget gate runs at issuance: the project's
    `committed_warranty_exposure_cents` plus the new `exposure_cents` must not
    exceed its `warranty_budget_cents`; the boundary is inclusive, so landing
    exactly on the budget is allowed and only a strictly greater sum is
    rejected with `ERR_WARRANTY_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/warranty_budget_inclusive_equality
    """
    world = create_world(
        api,
        warranty_budget_cents=100_000,
        system_overrides={"system_code": "SW-BUD-100"},
        applicator_overrides={"company_name": "Budget Bridge Coaters"},
    )
    completion = drive_to_completed_work_order(api, world, asset_zone="DECK-MAIN")

    warranty = issue_warranty(
        api, world["project"]["id"], completion["work_order"]["id"],
        term_years=10, exposure_cents=100_000,
    )

    assert warranty["status"] == "ACTIVE", "committed 0 + 100000 == budget 100000 is allowed"
    assert_cents(warranty["material_share_cents"], 50_000, "material_share_cents")
    assert_cents(warranty["application_share_cents"], 50_000, "application_share_cents")
    assert read_project(api, world["project"]["id"])["committed_warranty_exposure_cents"] == 100_000


def test_work_order_gated_by_qualification_state(api: ApiClient):
    """PRD §3.5: "the named applicator must hold a `CERTIFIED` qualification
    under a program whose `coating_system_id` matches the specification's
    coating system (`ERR_QUALIFICATION_NOT_CERTIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/work_order_gated_by_qualification_state
    """
    world = create_world(
        api,
        certifying=False,
        asset_type="STRUCTURAL_STEEL",
        system_overrides={"system_code": "SW-GATE-100"},
        applicator_overrides={"company_name": "Gatecheck Applicators"},
    )
    applicator_id = world["applicator"]["id"]
    qualification_id = world["qualification"]["id"]
    payload = work_order_payload(
        world["spec"]["id"], applicator_id, asset_zone="ZONE-1",
        window_start="2026-09-05T00:00:00Z", window_end="2026-09-15T00:00:00Z",
    )

    refused = api.create_work_order(world["project"]["id"], payload, PROJECT_ENGINEER_HEADERS)
    validate_error(refused, ApiErrorId.ERR_QUALIFICATION_NOT_CERTIFIED, expected_status=409)

    certify_qualification(api, applicator_id, qualification_id)
    assert read_qualification(api, applicator_id, qualification_id)["status"] == "CERTIFIED"

    accepted = api.create_work_order(world["project"]["id"], payload, PROJECT_ENGINEER_HEADERS)
    work_order = validate_success(accepted, expected_status=201)
    assert work_order["status"] == "SCHEDULED", (
        "the byte-identical payload succeeds once the cross-entity gate opens"
    )


def test_inspection_report_gated_by_cure_state(api: ApiClient):
    """PRD §3.6: "Otherwise an `Inspector` files an **inspection report**
    against a cured coat — filing against a coat not yet `CURED` fails with
    `ERR_COAT_NOT_CURED`".
    PRD §3.6: "Filing the report computes three sub-verdicts, moves the coat's
    acceptance dimension from `UNTESTED` to `TESTED`, and updates the
    applicator's score and streak per §3.3".

    Design: Difficulty/cross_entity_state_dependency/inspection_report_gated_by_cure_state
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-CURE-100"},
        applicator_overrides={"company_name": "Cure Watchers"},
    )
    work_order = drive_to_prep_approved(api, world, asset_zone="SPAN-CURE")
    application = record_application(api, work_order["id"], world["applicator"]["id"])

    refused = api.create_inspection_report(
        work_order["id"], application["id"], inspection_report_payload(), INSPECTOR_HEADERS
    )
    validate_error(refused, ApiErrorId.ERR_COAT_NOT_CURED, expected_status=409)

    advance_clock_and_mark_cured(api, work_order["id"], application["id"], world["applicator"]["id"])
    report = file_inspection_report(api, work_order["id"], application["id"])

    assert report["overall_verdict"] == "ACCEPTED"
    application_after = read_application(api, application["id"])
    assert application_after["cure_state"] == "CURED"
    assert application_after["acceptance_state"] == "TESTED"
