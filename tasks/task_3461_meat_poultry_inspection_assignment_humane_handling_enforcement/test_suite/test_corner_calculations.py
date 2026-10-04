"""Breadth tests: calculations — escalation threshold counting, recall
closure arithmetic, coverage-gap interval arithmetic, and label documentation
minimums."""

import pytest

from test_helpers import (
    ApiErrorId,
    LABEL_OFFICER_HEADERS,
    assert_enforcement_action,
    factories as f,
    fixtures as fx,
    make_establishment_manager_headers,
    validate_error,
    validate_success,
)


def test_nr_escalation_third_record_auto_proposes_suspension(api):
    """PRD §3.3: "If that count reaches 3 — exactly at threshold fires — the
    system automatically creates an enforcement action against the
    establishment: `action_type` `SUSPENSION`, `basis` `NR_LINKAGE`,
    `regulation_family` set to the escalating record's family, `status`
    `PROPOSED`, and `auto_created` true. This automatic proposal still requires
    district-manager activation before it bites; see §3.4."

    Design: Corner/calculations/nr_escalation_third_record_auto_proposes_suspension
    """
    est = fx.create_establishment(api, name="CA1 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    # Two escalations: qualifying count 2, below the threshold.
    fx.issue_and_escalate_nrs(api, est["id"], inspector["id"], "SANITATION", 2)
    assert fx.list_enforcement_actions(api, est["id"]) == [], "count 2 is below threshold 3"

    third = fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION",
                        description="sanitation finding three")
    escalated = fx.escalate_nr(api, third["id"], inspector["id"])
    assert escalated["status"] == "ESCALATED"

    actions = fx.list_enforcement_actions(api, est["id"])
    assert len(actions) == 1, "the third escalation fires the automatic proposal"
    action = actions[0]
    assert_enforcement_action(action)
    assert action["action_type"] == "SUSPENSION"
    assert action["basis"] == "NR_LINKAGE"
    assert action["regulation_family"] == "SANITATION"
    assert action["status"] == "PROPOSED"
    assert action["auto_created"] is True


def test_recall_close_at_exact_ratio_threshold_is_effective(api):
    """PRD §3.8: "The `RecallCoordinator` closes a `CLASS_DETERMINED` recall
    (otherwise `ERR_INVALID_STATE`); with fewer than `required_min_checks`
    checks performed, the close is rejected with
    `ERR_EFFECTIVENESS_CRITERIA_NOT_MET` (HTTP 409). Otherwise the outcome
    falls out of the ratio: an `effectiveness_ratio` greater than or equal to
    `required_effectiveness_ratio` closes the recall as `CLOSED_EFFECTIVE` —
    equality closes as effective — and a ratio below the requirement closes it
    as `CLOSED_INEFFECTIVE`."
    PRD §3.8: "`effectiveness_ratio` is recomputed as `checks_effective`
    divided by `checks_performed`, rounded half-up to 2 decimal places."

    Design: Corner/calculations/recall_close_at_exact_ratio_threshold_is_effective
    """
    est = fx.create_establishment(api, name="CA2 Plant", species_classes=["CATTLE"])
    recall = fx.create_class_determined_recall(
        api, est["id"], "CLASS_II", product_description="bacon lot 5", quantity_lbs=950,
        reason_code="MISBRANDING",
    )
    # CLASS_II requires at least 5 checks and ratio >= 0.80.
    fx.record_effectiveness_checks(api, recall["id"], ["EFFECTIVE"] * 4)

    early = api.close_recall(recall["id"], fx.RECALL_COORDINATOR_HEADERS)
    validate_error(early, ApiErrorId.ERR_EFFECTIVENESS_CRITERIA_NOT_MET)

    fx.record_effectiveness_check(api, recall["id"], consignee_name="Depot 5", outcome="INEFFECTIVE")
    mid = fx.get_recall(api, recall["id"])
    assert mid["checks_performed"] == 5
    assert mid["checks_effective"] == 4
    # round_half_up(4/5, 2) == 0.80 — exactly the requirement.
    assert mid["effectiveness_ratio"] == pytest.approx(0.80, abs=0.0001)

    closed = fx.close_recall(api, recall["id"])
    assert closed["status"] == "CLOSED_EFFECTIVE", "equality closes as effective"


def test_coverage_gap_partial_interval_arithmetic(api):
    """PRD §3.2: "The gap algorithm runs per line: for each line number from 1
    to `planned_line_count`, collect the window's non-`CANCELLED` assignments
    on that line, merge their half-open intervals, and measure the minutes of
    the window's own interval left uncovered; adjacent intervals, where one
    assignment's `end_utc` equals the next's `start_utc`, leave zero uncovered
    minutes between them. The window's gap is the sum of uncovered minutes
    across all lines."

    Design: Corner/calculations/coverage_gap_partial_interval_arithmetic
    """
    base = fx.setup_granted_with_window(api, species_classes=["CATTLE"], name="CA3 Plant")
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    fx.create_and_confirm_assignment(
        api, base["window"]["id"], inspector["id"],
        start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T08:00:00Z",
    )

    verified = fx.verify_coverage(api, base["window"]["id"], inspector["id"])

    # 480-minute window, 120 confirmed minutes on the only line -> 360 uncovered.
    assert verified["provisional_gap_minutes"] == 360
    assert verified["final_gap_minutes"] == 360
    assert verified["status"] == "COVERAGE_GAP_FLAGGED"


def test_label_documentation_minimum_exact_boundary(api):
    """PRD §3.7: "Approval carries three gates beyond state, reported in
    pipeline order: the establishment's `grant_status` must be `GRANTED`
    (otherwise `ERR_ESTABLISHMENT_NOT_GRANTED`), its `inspection_status` must
    not be `SUSPENDED` (otherwise `ERR_ESTABLISHMENT_SUSPENDED`), and the count
    of `documentation_refs` must meet the minimum for the claim — 2 references
    for `GRASS_FED`, 2 for `NO_ANTIBIOTICS`, 3 for `ORGANIC`, and 1 for
    `BREED_SPECIFIC`; exactly at the minimum passes, and a shortfall is
    rejected with `ERR_INSUFFICIENT_DOCUMENTATION` (HTTP 422)."

    Design: Corner/calculations/label_documentation_minimum_exact_boundary
    """
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="CA4 Plant")
    est_id = base["establishment"]["id"]
    label = fx.create_label_in_review(
        api, est_id, product_name="Organic Roast", label_claim="ORGANIC",
        documentation_refs=["doc-o1", "doc-o2"],
    )

    short = api.decide_label_application(
        label["id"], f.label_decision_payload("APPROVE"), LABEL_OFFICER_HEADERS
    )
    validate_error(short, ApiErrorId.ERR_INSUFFICIENT_DOCUMENTATION)

    # RETURN -> resubmit with exactly 3 refs -> begin-review -> APPROVE passes.
    fx.decide_label(api, label["id"], "RETURN")
    resp = api.resubmit_label_application(
        label["id"],
        f.label_resubmit_payload(["doc-o1", "doc-o2", "doc-o3"]),
        make_establishment_manager_headers(est_id),
    )
    validate_success(resp, 200)
    fx.begin_label_review(api, label["id"])
    approved = api.decide_label_application(
        label["id"], f.label_decision_payload("APPROVE"), LABEL_OFFICER_HEADERS
    )
    data = validate_success(approved, 200)
    assert data["status"] == "APPROVED", "exactly at the minimum passes"
    assert data["revision_count"] == 1
