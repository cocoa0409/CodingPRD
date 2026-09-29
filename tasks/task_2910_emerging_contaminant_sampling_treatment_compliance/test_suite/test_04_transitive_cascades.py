"""Chains of consequence fired by a single write.

Accepting one lab result reaches four levels deep; invalidating one sample runs
the same distance in reverse and stops short of retracting the mandate.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    QUARTER_ANALYZED_AT,
    accept_result,
    accepted_quarters,
    build_registry,
    read_entry_point,
    read_lab_result,
    read_sample,
    received_sample,
    submit_result,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS
from prd_bench_local_runner.testing import validate_success


def _four_clean_quarters_with_a_pending_reduction(api):
    """Four quarters at 1.50, an ANNUAL reduction request, and a fifth result awaiting review."""
    registry = build_registry(api)
    accepted_quarters(
        api,
        registry,
        [("2025Q3", 1.50), ("2025Q4", 1.50), ("2026Q1", 1.50), ("2026Q2", 1.50)],
    )
    validate_success(
        api.request_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_request_payload(
                target_status="ANNUAL",
                justification="Four consecutive quarters below the trigger level.",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        monitoring_period="2026Q3",
        preservative_lot="LOT-Q5",
    )
    result = submit_result(
        api,
        registry["laboratory_id"],
        sample["id"],
        registry["contaminant_id"],
        reported_ng_per_l=18.00,
        detection_limit_ng_per_l=1.00,
        analyzed_at=QUARTER_ANALYZED_AT["2026Q3"],
    )
    return registry, sample, result


def test_accepting_the_fifth_result_carries_the_sample_and_the_entry_point_with_it(api):
    """One review closes the panel and lifts the ratio from 0.3750 to 1.4075.

    Before the review the entry point sat at a compliance ratio of 0.3750 and a
    COMPLIANT posture; accepting the 18.00 reading of the 2026Q3 sample completes
    that sample's panel, brings the quarter inside the four-period window and
    re-derives the ratio to 1.4075, which is a violation posture.

    PRD: "The parent sample advances `RECEIVED → ANALYZED` when, and only when,
    every contaminant identifier in its `panel_contaminant_ids` now has exactly
    one accepted result; a partially analysed sample stays in `RECEIVED`."

    Design: Difficulty/transitive_cascade/accepting_a_high_result_cascades_through_sample_entry_point_and_mandated_evaluation
    """
    registry, sample, result = _four_clean_quarters_with_a_pending_reduction(api)
    before = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(before, posture="COMPLIANT", max_compliance_ratio=0.3750)
    assert_status(read_sample(api, sample["id"]), "RECEIVED")

    accepted = accept_result(api, result["id"])

    assert_status(accepted, "ACCEPTED")
    assert_decimal(accepted["compliance_value_ng_per_l"], 18.00, label="compliance_value_ng_per_l")
    assert_status(read_sample(api, sample["id"]), "ANALYZED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="VIOLATION_PENDING",
        accepted_result_count=5,
        max_compliance_ratio=1.4075,
        consecutive_qualifying_quarters=0,
        open_violation_count=0,
    )


def test_the_violation_posture_mandates_an_evaluation_and_denies_the_reduction(api):
    """The fourth link fires only because the third one landed on a violation.

    No treatment evaluation exists while the posture is COMPLIANT and the ANNUAL
    reduction request is outstanding at REDUCTION_PENDING; the single ACCEPT that
    pushes the posture to VIOLATION_PENDING opens one mandated evaluation in
    SCREENING and sends the entry point back to QUARTERLY with its request
    cleared.

    PRD: "The entry point's running averages, `max_compliance_ratio`,
    `hazard_index`, `consecutive_qualifying_quarters` and `compliance_posture`
    are then all re-derived, and if that re-derivation lands the posture on
    `VIOLATION_PENDING` two further consequences fire: a mandated treatment
    evaluation is opened when none is already open for the entry point, and any
    monitoring reduction awaiting a regulator's decision is auto-denied."

    Design: Difficulty/transitive_cascade/accepting_a_high_result_cascades_through_sample_entry_point_and_mandated_evaluation
    """
    registry, _, result = _four_clean_quarters_with_a_pending_reduction(api)
    before = read_entry_point(api, registry["entry_point_id"])
    assert_equals(before, "monitoring_status", "REDUCTION_PENDING")
    assert_equals(before, "requested_monitoring_status", "ANNUAL")
    assert_total_count(
        api.list_treatment_evaluations(
            COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": registry["entry_point_id"]}
        ),
        0,
    )

    accept_result(api, result["id"])

    after = read_entry_point(api, registry["entry_point_id"])
    assert_equals(after, "monitoring_status", "QUARTERLY")
    assert_is_null(after, "requested_monitoring_status")
    assert_equals(after, "treatment_status", "NONE")

    rows = assert_total_count(
        api.list_treatment_evaluations(
            COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": registry["entry_point_id"]}
        ),
        1,
    )
    assert_equals(rows[0], "mandated", True)
    assert_status(rows[0], "SCREENING")
    assert_money_cents(rows[0]["residuals_budget_cents"], 250000, "residuals_budget_cents")


def _violating_entry_point(api):
    """Four quarters averaging 4.50, so a mandate already exists at VIOLATION_PENDING."""
    registry = build_registry(api)
    quarters = accepted_quarters(
        api,
        registry,
        [("2025Q3", 3.00), ("2025Q4", 3.00), ("2026Q1", 3.00), ("2026Q2", 9.00)],
    )
    return registry, quarters


def test_invalidating_the_high_quarter_supersedes_its_result_and_deescalates(api):
    """Withdrawing one sample shortens the input set and walks the posture back one step.

    Invalidating the ANALYZED 2026Q2 sample for a quality-control failure records
    ANALYZED as the status it left, drives its accepted result to SUPERSEDED and
    leaves three quarters of 3.00 in the window, so the ratio falls from 1.1250 to
    0.7500 and the posture de-escalates to TRIGGERED.

    PRD: "Every result of that sample in `ACCEPTED` status is driven `ACCEPTED →
    SUPERSEDED`, which removes it from every running-average input set; the entry
    point's `accepted_result_count` falls by the number of results superseded,
    and its running averages, `max_compliance_ratio`, `hazard_index`,
    `consecutive_qualifying_quarters` and `compliance_posture` are all
    re-derived."

    Design: Difficulty/transitive_cascade/invalidating_a_sample_cascades_supersede_and_deescalates_the_posture
    """
    registry, quarters = _violating_entry_point(api)
    before = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(
        before,
        posture="VIOLATION_PENDING",
        accepted_result_count=4,
        max_compliance_ratio=1.1250,
        consecutive_invalidated_samples=0,
    )

    invalidated = validate_success(
        api.invalidate_sample(
            quarters[3]["sample_id"],
            f.invalidate_sample_payload(invalidation_reason="QC_FAILURE"),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert_status(invalidated, "INVALIDATED")
    assert_equals(invalidated, "status_before_invalidation", "ANALYZED")
    assert_equals(invalidated, "invalidation_reason", "QC_FAILURE")
    assert_status(read_lab_result(api, quarters[3]["result_id"]), "SUPERSEDED")
    assert_status(read_lab_result(api, quarters[2]["result_id"]), "ACCEPTED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="TRIGGERED",
        accepted_result_count=3,
        max_compliance_ratio=0.7500,
        consecutive_invalidated_samples=1,
        monitoring_status="QUARTERLY",
    )


def test_deescalating_the_posture_does_not_retract_the_mandated_evaluation(api):
    """The cascade stops one link short of undoing the mandate.

    The mandated evaluation the earlier escalation created is still the single
    evaluation at the entry point after the invalidation drops the posture to
    TRIGGERED, still flagged mandated and still in SCREENING.

    PRD: "De-escalation is asymmetric and intentionally so: on
    `VIOLATION_PENDING → TRIGGERED`, reached when a compensating write leaves
    `max_compliance_ratio` at least 0.5 and at most 1.0, existing treatment
    evaluations are left untouched — de-escalation never retracts a mandated
    evaluation."

    Design: Difficulty/transitive_cascade/invalidating_a_sample_cascades_supersede_and_deescalates_the_posture
    """
    registry, quarters = _violating_entry_point(api)
    assert_total_count(
        api.list_treatment_evaluations(
            COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": registry["entry_point_id"]}
        ),
        1,
    )

    validate_success(
        api.invalidate_sample(
            quarters[3]["sample_id"],
            f.invalidate_sample_payload(invalidation_reason="QC_FAILURE"),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    rows = assert_total_count(
        api.list_treatment_evaluations(
            COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": registry["entry_point_id"]}
        ),
        1,
    )
    assert_equals(rows[0], "mandated", True)
    assert_status(rows[0], "SCREENING")
