"""Corner coverage — immediate consistency: mutation responses carry the
post-mutation state (PRD §2.2, §2.4).
"""
from test_helpers import (
    validate_success, get_success_data,
    create_site, create_approved_assessment, create_conversion_plan_payload,
    MANAGER,
)


def test_mutation_response_carries_post_mutation_state(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by
    exactly 1 on every mutation of the resource, including mutations caused by
    automatic state transitions and cascades."

    Design: Corner/consistency_model/immediate_visibility_in_same_response
    """
    site = create_site(code="S-CM1")
    create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = get_success_data(api.create_conversion_plan(
        site["id"], create_conversion_plan_payload(
            name="Wave CM", baseline_productivity_units_per_hour=40.0,
            expected_productivity_gain_pct=5), MANAGER))
    v0 = plan["version"]
    scheduled = validate_success(api.schedule_plan(
        site["id"], plan["id"], {"expected_plan_version": v0}, MANAGER))
    assert scheduled["status"] == "SCHEDULED", (
        "the schedule response itself shows the post-mutation state")
    assert scheduled["version"] == v0 + 1, (
        "the version increment is visible in the same response body")
