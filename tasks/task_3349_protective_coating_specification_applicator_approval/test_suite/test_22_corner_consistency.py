"""Corner breadth index (consistency model): a warranty issuance is visible
in the project's committed exposure on the immediately following read.
"""
from test_helpers import (
    ApiClient,
    create_world,
    drive_to_completed_work_order,
    issue_warranty,
    read_project,
)


def test_warranty_issuance_immediately_visible_in_project_exposure(api: ApiClient):
    """PRD §3.7: "The `project_id` comes from the path, and issuance
    increments the project's committed exposure by the new warranty's
    `exposure_cents`."
    PRD §3.4: "that committed figure is recomputed as the sum of
    `exposure_cents` across all of the project's warranties in `ACTIVE` or
    `CLAIMED` status."

    Design: Corner/consistency_model/warranty_issuance_immediately_visible_in_project_exposure
    """
    world = create_world(api, system_overrides={"system_code": "SW-CONS"})
    completion = drive_to_completed_work_order(api, world, asset_zone="Z1")
    project_id = world["project"]["id"]
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 0

    warranty = issue_warranty(
        api, project_id, completion["work_order"]["id"], term_years=5, exposure_cents=750_000
    )

    assert warranty["status"] == "ACTIVE"
    project_after = read_project(api, project_id)
    assert project_after["committed_warranty_exposure_cents"] == 750_000, (
        "the read in the same sweep already reflects the incremented exposure"
    )
