"""Corner breadth index (endpoints): nested work-order creation shape and
the computed 50/50 warranty split exposed on read.
"""
from test_helpers import (
    ApiClient,
    assert_cents,
    assert_warranty,
    assert_work_order,
    create_world,
    create_work_order,
    drive_to_completed_work_order,
    issue_warranty,
    read_warranty,
)


def test_work_order_creation_nested_under_project_happy_path(api: ApiClient):
    """PRD §3.5: "A new work order begins `SCHEDULED` with
    `hold_point_prep_released` false."
    PRD §3.5: "A `ProjectEngineer` creates it with the `specification_id` of
    the specification being executed, the `applicator_id` of the company
    doing the work, a free-form `asset_zone` label, and the closed
    application window `window_start` through `window_end`; the `project_id`
    comes from the path."

    Design: Corner/endpoints/work_order_creation_nested_under_project_happy_path
    """
    world = create_world(api, system_overrides={"system_code": "SW-EP-WO"})

    work_order = create_work_order(
        api, world["project"]["id"], world["spec"]["id"], world["applicator"]["id"],
        asset_zone="Z1", window_start="2026-10-01T00:00:00Z", window_end="2026-10-10T00:00:00Z",
    )

    assert_work_order(work_order)
    assert work_order["status"] == "SCHEDULED"
    assert work_order["hold_point_prep_released"] is False
    assert work_order["project_id"] == world["project"]["id"]


def test_warranty_get_exposes_computed_50_50_split(api: ApiClient):
    """PRD §3.7: "Liability between the two parties is expressed as the
    warranty's `manufacturer_fault_pct`, which begins at 50 and stays there
    until a failure investigation decides otherwise."
    PRD §3.7: "At issuance the manufacturer's `material_share_cents` is half
    the exposure — the exposure multiplied by 0.50, rounded half-up to a
    whole cent — and the applicator's `application_share_cents` is the
    remainder, absorbing any rounding residue."
    PRD §3.7: "A warranty is born `ACTIVE`."

    Design: Corner/endpoints/warranty_get_exposes_computed_50_50_split
    """
    # Budget equals the exposure exactly: §3.7's boundary is inclusive, so
    # landing exactly on the budget is allowed.
    world = create_world(
        api,
        system_overrides={"system_code": "SW-EP-WAR"},
        warranty_budget_cents=2_000_000,
    )
    completion = drive_to_completed_work_order(api, world, asset_zone="Z1")
    issued = issue_warranty(
        api, world["project"]["id"], completion["work_order"]["id"],
        term_years=5, exposure_cents=2_000_000,
    )

    warranty = read_warranty(api, issued["id"])

    assert_warranty(warranty)
    assert warranty["status"] == "ACTIVE"
    assert warranty["manufacturer_fault_pct"] == 50
    assert_cents(warranty["material_share_cents"], 1_000_000, "material_share_cents")
    assert_cents(warranty["application_share_cents"], 1_000_000, "application_share_cents")
    assert warranty["material_share_cents"] + warranty["application_share_cents"] == 2_000_000
