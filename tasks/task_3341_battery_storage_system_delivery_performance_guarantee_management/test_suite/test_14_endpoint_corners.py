"""Endpoint corner tests: filtered child listings and conditional actions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_esa,
    create_milestone,
    create_project,
    get_success_data,
    setup_executed_project,
    submit_permit,
    validate_error,
    validate_paginated,
)

DEV = TEST_USERS["project_developer_headers"]


def test_filtered_lists_find_children_from_parent_ids(api):
    """PRD §4: "GET `/delivery-milestones` List milestones, optionally filtered
    by agreement"
    PRD §4: "GET `/safety-permits` List permits, optionally filtered by
    project"
    PRD §2.9: "Resources reference one another through foreign-key fields in
    request bodies — a payload containing `project_id`, `esa_id`,
    `service_agreement_id`, or `warranty_claim_id` names the parent it attaches
    to."

    Design: Corner/endpoints/filtered_lists_find_children_from_parent_ids
    """
    project = create_project(api=api)
    submit_permit(project["id"], "FIRE_CODE", api=api)
    other = create_project(
        api=api, name="Other", rated_power_mw=5, rated_energy_mwh=10,
        budget_cents=5000000,
    )
    submit_permit(other["id"], "LOCAL_APPROVAL", api=api)
    # Milestones can only be scheduled on an EXECUTED ESA (PRD §3.3), so the
    # milestone child hangs off a fully executed project of its own.
    _, esa = setup_executed_project(api=api)
    create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)

    milestones, meta = validate_paginated(
        api.list_milestones(DEV, params={"esa_id": esa["id"]})
    )
    assert len(milestones) == 1 and meta["total_count"] == 1

    permits, meta = validate_paginated(
        api.list_permits(DEV, params={"project_id": project["id"]})
    )
    assert len(permits) == 1 and meta["total_count"] == 1, (
        "only P1's permit, not P2's"
    )
    assert permits[0]["project_id"] == project["id"]


def test_waiver_on_draft_esa_rejected_state(api):
    """PRD §3.3: "Separately, the developer may waive accrued damages on a
    non-`DRAFT` agreement by supplying an `amount_cents`"

    Design: Corner/endpoints/waiver_on_draft_esa_rejected_state
    """
    project = create_project(api=api)
    esa = create_esa(project["id"], api=api)
    resp = api.waive_ld(esa["id"], {"amount_cents": 1}, DEV)
    validate_error(resp, ApiErrorId.ERR_ESA_NOT_DRAFT)
    after = get_success_data(api.get_esa(esa["id"], DEV))
    assert after["waived_ld_cents"] == 0
