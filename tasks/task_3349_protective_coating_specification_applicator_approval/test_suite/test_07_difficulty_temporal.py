"""Difficulty depth index: temporal overlap — closed-interval work-order
windows (touching endpoints conflict) versus half-open regulation windows
(abutment required, overlap rejected).
"""
from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PROJECT_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_instant,
    create_world,
    regulation_supersede_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    voc_regulation_payload,
    work_order_payload,
)


def test_work_order_window_closed_interval_touch_conflict(api: ApiClient):
    """PRD §2.10: "Because both endpoints are inclusive, windows that merely
    touch — one starting at the exact instant another ends — still count as
    overlapping, so back-to-back scheduling on one zone is rejected."
    PRD §2.10: "The equipment-corridor exception applies across zones: two
    work orders with different `asset_zone` values never conflict, no matter
    how their times overlap."

    Design: Difficulty/resource_temporal_overlap/work_order_window_closed_interval_touch_conflict
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-WIN-100"},
        applicator_overrides={"company_name": "Window Works"},
    )
    project_id = world["project"]["id"]
    applicator_id = world["applicator"]["id"]
    spec_id = world["spec"]["id"]

    first = api.create_work_order(
        project_id,
        work_order_payload(spec_id, applicator_id, asset_zone="PIPE-RACK",
                           window_start="2026-09-05T00:00:00Z", window_end="2026-09-15T00:00:00Z"),
        PROJECT_ENGINEER_HEADERS,
    )
    work_order_1 = validate_success(first, expected_status=201)
    assert work_order_1["status"] == "SCHEDULED"

    touching = api.create_work_order(
        project_id,
        work_order_payload(spec_id, applicator_id, asset_zone="PIPE-RACK",
                           window_start="2026-09-15T00:00:00Z", window_end="2026-09-25T00:00:00Z"),
        PROJECT_ENGINEER_HEADERS,
    )
    validate_error(touching, ApiErrorId.ERR_WINDOW_CONFLICT, expected_status=409)

    other_zone = api.create_work_order(
        project_id,
        work_order_payload(spec_id, applicator_id, asset_zone="PIPE-RACK-EAST",
                           window_start="2026-09-15T00:00:00Z", window_end="2026-09-25T00:00:00Z"),
        PROJECT_ENGINEER_HEADERS,
    )
    work_order_3 = validate_success(other_zone, expected_status=201)
    assert work_order_3["status"] == "SCHEDULED", (
        "the identical touching window on a different asset_zone is legal"
    )


def test_voc_regulation_half_open_abutment(api: ApiClient):
    """PRD §2.10: "Under half-open semantics a window that begins exactly when
    its predecessor ends does not overlap it; such zero-gap abutment is not
    merely legal but is required of a successor at supersede time, where a gap
    of any size is rejected with `ERR_REGULATION_GAP`."
    PRD §3.2: "On success the existing regulation becomes `SUPERSEDED` and a
    successor regulation is created `ACTIVE` carrying the successor window,
    the new limit, and the same `jurisdiction_code` and `application_method`."

    Design: Difficulty/resource_temporal_overlap/voc_regulation_half_open_abutment
    """
    set_clock(api)
    reg1 = validate_success(
        api.create_voc_regulation(
            voc_regulation_payload(
                jurisdiction_code="US-FED", application_method="SPRAY_AIRLESS",
                voc_limit_gpl=340,
                effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        expected_status=201,
    )

    overlap = api.create_voc_regulation(
        voc_regulation_payload(
            jurisdiction_code="US-FED", application_method="SPRAY_AIRLESS",
            voc_limit_gpl=320,
            effective_from="2026-06-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(overlap, ApiErrorId.ERR_REGULATION_OVERLAP, expected_status=409)

    gap = api.supersede_voc_regulation(
        reg1["id"],
        regulation_supersede_payload(300, "2026-07-01T00:00:00Z", "2028-01-01T00:00:00Z"),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(gap, ApiErrorId.ERR_REGULATION_GAP, expected_status=409)

    abutting = api.supersede_voc_regulation(
        reg1["id"],
        regulation_supersede_payload(300, "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z"),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_success(abutting)

    predecessor = validate_success(api.get_voc_regulation(reg1["id"], PLATFORM_ADMIN_HEADERS))
    assert predecessor["status"] == "SUPERSEDED"

    rows, _meta = validate_paginated(
        api.list_voc_regulations(
            PLATFORM_ADMIN_HEADERS,
            params={"jurisdiction_code": "US-FED", "application_method": "SPRAY_AIRLESS"},
        )
    )
    successors = [row for row in rows if row["status"] == "ACTIVE" and row["id"] != reg1["id"]]
    assert len(successors) == 1, "exactly one ACTIVE successor must be created"
    successor = successors[0]
    assert successor["voc_limit_gpl"] == 300
    assert_instant(successor["effective_from"], "2027-01-01T00:00:00Z", "successor.effective_from")
    assert_instant(successor["effective_to"], "2028-01-01T00:00:00Z", "successor.effective_to")
