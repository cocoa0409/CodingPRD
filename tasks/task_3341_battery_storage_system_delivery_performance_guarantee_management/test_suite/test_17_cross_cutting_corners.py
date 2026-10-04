"""Cross-cutting corner tests: derived-field reconciliation and immediate
consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_manual_augmentation,
    create_milestone,
    get_success_data,
    record_milestone_outcome,
    setup_commissioned_project,
    setup_executed_project,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
SVC_ENG = TEST_USERS["service_engineer_headers"]


def test_derived_fields_reconcile_after_each_mutation(api):
    """PRD §3.5: "The projection starts from `commissioned_capacity_mwh`, adds
    the `added_capacity_mwh` of every augmentation event in `EXECUTED` status —
    `PLANNED` and `CANCELLED` events never contribute — and subtracts
    degradation of a per-cycle rate multiplied by the stored
    `equivalent_cycles`."
    PRD §3.5: "Cancelling a `PLANNED` event recomputes `augmentation_count` but
    leaves the projection untouched, since planned events never contributed to
    it."
    PRD §3.1: "an `augmentation_count` of its augmentation events in `PLANNED`
    or `EXECUTED` status."

    Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_each_mutation
    """
    project, esa = setup_commissioned_project(api=api)
    validate_success(
        api.recompute_projection(project["id"], {"equivalent_cycles": 0}, PERF)
    )

    a1 = create_manual_augmentation(project["id"], api=api, added_capacity_mwh=2)
    a2 = create_manual_augmentation(project["id"], api=api, added_capacity_mwh=5)
    version = get_success_data(api.get_project(project["id"], DEV))["version"]
    validate_success(
        api.execute_augmentation(
            a1["id"], {"expected_project_version": version}, SVC_ENG
        )
    )
    cancelled = validate_success(api.cancel_augmentation(a2["id"], SVC_ENG))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["origin"] == "MANUAL"

    final = get_success_data(api.get_project(project["id"], DEV))
    # 40 + 2 - 0*D = 42.0; pre-penalty 42 < 80 floor -> no penalty.
    assert final["projected_capacity_mwh"] == pytest.approx(42.0, abs=0.001), (
        f"40 + 2 == 42.0, got {final['projected_capacity_mwh']}"
    )
    assert final["augmentation_count"] == 1, (
        "cancelled event drops out of the PLANNED+EXECUTED count"
    )


def test_immediate_consistency_visible_in_same_response(api):
    """PRD §3.3: "A late recording sets `days_late` to the count of whole
    calendar days after the planned date up to and including the actual date —
    any crossing into a new calendar day counts as a full day — and accrues
    liquidated damages under the cap-aware rule below."
    PRD §3.3: "That amount is added to the agreement's `accrued_ld_cents`, and
    `net_ld_due_cents` is recomputed as accrued minus waived."

    Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
    """
    project, esa = setup_executed_project(api=api)
    m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
    outcome = validate_success(
        api.record_milestone_outcome(
            m1["id"], {"outcome": "MISSED", "actual_date": "2026-10-06T00:00:00Z"}, DEV
        )
    )
    assert outcome["days_late"] == 5
    assert outcome["ld_applied_cents"] == 200000, (
        f"5 * 40000 == 200000, got {outcome['ld_applied_cents']}"
    )

    esa_after = get_success_data(api.get_esa(esa["id"], DEV))
    assert esa_after["accrued_ld_cents"] == 200000
    assert esa_after["net_ld_due_cents"] == 200000
