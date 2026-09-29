"""Dispatch readiness, the rework cycle and the ordering of the sign-off gates."""

import pytest

from test_helpers import (
    MANAGER,
    OPERATOR,
    TECHNICIAN,
    api_client,
    assert_dispatch_readiness_shape,
    assert_instant_equals,
    assert_inspection_counters,
    fixtures,
    make_qualified_inspector_headers,
    validate_error,
    validate_success,
)


def _template_with_lines(attraction_id, lines, effective_from_date):
    """Author and activate one revision carrying the supplied (severity, text) lines."""
    template = fixtures.create_template(
        attraction_id, effective_from_date=effective_from_date
    )
    items = []
    for index, (severity_class, description) in enumerate(lines, start=1):
        items.append(
            fixtures.append_line(
                template["id"],
                sequence_no=index,
                severity_class=severity_class,
                description=description,
            )
        )
    activated = fixtures.activate_template(template["id"], attraction_id)
    return {"template": activated, "items": items}


def _skyline_flyer_signed_off():
    """A signed-off walk with one essential failure and four graded operators."""
    attraction = fixtures.create_attraction(
        name="Skyline Flyer",
        park_area="SKYLINE",
        manufacturer="Zamperla",
        model_code="AF-9",
        ride_class="FAMILY",
        theoretical_hourly_capacity=600,
        min_operators_required=2,
        parts_budget_cents=2000000,
    )
    graded = [
        ("op-1", 92, 88),
        ("op-2", 87, 81),
        ("op-3", 100, 95),
        ("op-4", 84, 90),
    ]
    certifications = [
        fixtures.create_certification(
            attraction["id"],
            operator_user_id=badge,
            effective_from="2026-07-01T00:00:00.000Z",
            expires_at="2026-12-31T00:00:00.000Z",
            restraint_verification_score=restraint,
            dispatch_procedure_score=dispatch,
        )
        for badge, restraint, dispatch in graded
    ]
    _template_with_lines(
        attraction["id"],
        [
            ("ESSENTIAL", "Restraint actuator stroke check"),
            ("ESSENTIAL", "Air gauge reading within band"),
            ("ADVISORY", "Queue signage legible"),
        ],
        "2026-07-01",
    )
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "tech-1")
    results = fixtures.list_item_results(inspection["id"])
    fixtures.record_outcomes(
        results,
        [("FAIL", "Stroke 2mm short of band, shimmed and re-measured"), "PASS", "PASS"],
        technician_badge="tech-1",
    )
    fixtures.submit_inspection(inspection["id"], "tech-1")
    signed = fixtures.sign_off_inspection(inspection["id"], "insp-9")
    return {
        "attraction": fixtures.read_attraction(attraction["id"]),
        "certifications": certifications,
        "inspection": signed,
    }


def test_dispatch_readiness_caps_the_staffing_ratio_at_one():
    """Surplus certified operators do not inflate the index.

    PRD §3.7: "The **staffing ratio** is the `certified_operator_count` divided by
    the attraction's `min_operators_required`, capped at 1.0 so that surplus
    operators do not inflate the score."
    PRD §3.7: "Otherwise, if `restraint_verification_score` is at least 85 **and**
    `dispatch_procedure_score` is at least 80, the status is `CERTIFIED`."

    Design: Difficulty/combinatorial_formula/dispatch_readiness_nested_min_max_with_capped_penalty
    """
    bundle = _skyline_flyer_signed_off()

    data = validate_success(
        api_client.get_dispatch_readiness(bundle["attraction"]["id"], OPERATOR)
    )
    assert_dispatch_readiness_shape(data)

    assert data["operational_posture"] == "OPEN"
    assert data["certified_operator_count"] == 3, (
        "the operator scoring 84 on the restraint practical stays a trainee"
    )
    assert data["mean_restraint_score"] == pytest.approx(93.00, abs=0.01)
    assert data["dispatch_readiness_index"] == pytest.approx(81.50, abs=0.01)
    assert data["dispatch_readiness_index"] != pytest.approx(126.25, abs=0.01), (
        "an uncapped staffing ratio of 1.5 would give 126.25"
    )


def test_the_essential_failure_penalty_is_read_from_the_signed_off_inspection():
    """The penalty comes from the latest signed-off walk and is capped at 40 points.

    PRD §3.7: "The `essential_fail_count` figure is read from a single inspection:
    the attraction's daily inspection with the greatest `service_date` among those
    whose `status` is `SIGNED_OFF`, breaking a tie on `created_at` ascending so the
    earliest row wins."
    PRD §3.7: "The **penalty** is the `essential_fail_count` described above
    multiplied by 8 points per essential failure, capped at 40 points, so no more
    than five essential failures can ever count against the index."

    Design: Difficulty/combinatorial_formula/dispatch_readiness_nested_min_max_with_capped_penalty
    """
    bundle = _skyline_flyer_signed_off()
    assert bundle["inspection"]["status"] == "SIGNED_OFF"
    assert bundle["inspection"]["essential_fail_count"] == 1

    data = validate_success(
        api_client.get_dispatch_readiness(bundle["attraction"]["id"], OPERATOR)
    )
    assert data["essential_fail_count"] == 1
    assert bundle["attraction"]["last_signed_off_service_date"] == "2026-08-01"


def _lagoon_rapids_rejected():
    """A rejected walk carrying one failed essential line and one NA advisory line."""
    attraction = fixtures.create_attraction(
        name="Lagoon Rapids",
        park_area="LAGOON",
        manufacturer="Hafema",
        model_code="RR-12",
        ride_class="WATER",
        theoretical_hourly_capacity=950,
        min_operators_required=3,
        parts_budget_cents=3000000,
    )
    _template_with_lines(
        attraction["id"],
        [
            ("ESSENTIAL", "Water level in trough within band"),
            ("ADVISORY", "Boat bumper condition"),
            ("ADVISORY", "Splash-zone signage"),
        ],
        "2026-07-15",
    )
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "tech-7")
    results = fixtures.list_item_results(inspection["id"])
    fixtures.record_outcomes(
        results,
        [("FAIL", "Trough 40mm low, topped up"), "PASS", "NA"],
        technician_badge="tech-7",
    )
    fixtures.submit_inspection(inspection["id"], "tech-7")
    rejected = fixtures.reject_inspection(
        inspection["id"], "Re-measure trough after pump cycle", "insp-3"
    )
    return {"attraction": attraction, "inspection": rejected}


def test_reopening_resets_only_the_failed_rows_and_bumps_the_rework_round():
    """Passed and NA rows survive a reopen; failed rows return to pending.

    PRD §3.3: "Every result row of that inspection whose `outcome` is `FAIL` is
    reset to `PENDING` with its `recorded_by_user_id` and `recorded_at` cleared, and
    `pending_item_count`, `blocking_item_count` and `essential_fail_count` are then
    recomputed from the reset rows — so a reopened inspection with two prior failures
    returns with those two lines pending again and both fail counters back at zero."
    PRD §3.3: "What reopening deliberately does **not** clear is
    `recorded_by_user_ids`: the segregation-of-duties set survives every rework
    round, so a technician who recorded a finding in round zero is still barred from
    signing in round three."

    Design: Difficulty/non_linear_state_machine/inspection_reject_reopen_cycle_resets_only_fail_rows_and_bumps_rework_round
    """
    bundle = _lagoon_rapids_rejected()

    reopened = validate_success(
        api_client.reopen_daily_inspection(
            bundle["inspection"]["id"], TECHNICIAN
        )
    )
    assert_inspection_counters(
        reopened,
        status="IN_PROGRESS",
        pending=1,
        blocking=0,
        essential_fail=0,
        rework_round=1,
    )
    assert reopened["recorded_by_user_ids"] == ["tech-7"]
    assert reopened["rejection_reason"] == "Re-measure trough after pump cycle"

    results = fixtures.list_item_results(bundle["inspection"]["id"])
    assert results[0]["outcome"] == "PENDING"
    assert results[0]["recorded_by_user_id"] is None
    assert results[0]["recorded_at"] is None
    assert results[1]["outcome"] == "PASS"
    assert results[2]["outcome"] == "NA"


def test_a_second_reopen_is_refused_because_in_progress_has_no_reopen_edge():
    """Only a REJECTED inspection may be reopened, and the counter does not drift.

    PRD §3.3: "A `MaintenanceTechnician` reopens an inspection that is `REJECTED`,
    moving it `REJECTED` → `IN_PROGRESS` and completing the cycle `IN_PROGRESS` →
    `PENDING_SIGN_OFF` → `REJECTED` → `IN_PROGRESS`."
    PRD §2.6: "**Declared-transition check.** The target row is in a state from
    which the requested transition is declared."

    Design: Difficulty/non_linear_state_machine/inspection_reject_reopen_cycle_resets_only_fail_rows_and_bumps_rework_round
    """
    bundle = _lagoon_rapids_rejected()
    fixtures.reopen_inspection(bundle["inspection"]["id"], "tech-7")

    response = api_client.reopen_daily_inspection(
        bundle["inspection"]["id"], TECHNICIAN
    )
    validate_error(response, "ERR_INSPECTION_STATE_INVALID", 409)

    again = validate_success(
        api_client.get_daily_inspection(bundle["inspection"]["id"], TECHNICIAN)
    )
    assert again["rework_round"] == 1
    assert again["status"] == "IN_PROGRESS"


def _boardwalk_bullet_blocked():
    """A blocked walk whose only recorder also holds the inspector badge `u-77`."""
    attraction = fixtures.create_attraction(
        name="Boardwalk Bullet",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="BW-31",
        ride_class="FAMILY",
        theoretical_hourly_capacity=640,
        min_operators_required=2,
        parts_budget_cents=1200000,
    )
    _template_with_lines(
        attraction["id"],
        [
            ("SAFETY_CRITICAL", "Restraint lock proof load"),
            ("ADVISORY", "Queue rail fasteners"),
        ],
        "2026-07-01",
    )
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "u-77")
    results = fixtures.list_item_results(inspection["id"])
    fixtures.record_outcomes(
        results,
        [("FAIL", "Lock did not hold proof load"), "PASS"],
        technician_badge="u-77",
    )
    return {
        "attraction": attraction,
        "inspection": validate_success(
            api_client.get_daily_inspection(inspection["id"], TECHNICIAN)
        ),
    }


def test_the_declared_transition_check_outranks_the_blocking_item_gate():
    """A blocked inspection is refused on its state, not on its blocking finding.

    PRD §2.6: "First, because the declared-transition check sits at priority 7 and
    the blocking-item gate at priority 8, an inspection that is not in
    `PENDING_SIGN_OFF` at all fails with `ERR_INSPECTION_STATE_INVALID` before
    `ERR_SAFETY_CRITICAL_ITEM_FAILED` is ever considered."
    PRD §3.3: "The inspection must be `PENDING_SIGN_OFF`."

    Design: Difficulty/priority_pair_validation_conflict/signoff_state_check_priority_7_wins_over_blocking_item_8_and_segregation_11
    """
    bundle = _boardwalk_bullet_blocked()
    assert_inspection_counters(bundle["inspection"], status="BLOCKED", blocking=1)

    response = api_client.sign_off_daily_inspection(
        bundle["inspection"]["id"], make_qualified_inspector_headers("u-77")
    )
    validate_error(response, "ERR_INSPECTION_STATE_INVALID", 409)


def test_the_refused_sign_off_leaves_the_inspection_and_the_attraction_unstamped():
    """Nothing is stamped by a refused statutory act.

    PRD §3.3: "Its `signed_off_by_user_id` is stamped with the signing badge and its
    `signed_off_at` with the current logical clock instant."
    PRD §3.3: "The attraction's `last_signed_off_service_date` is set to this
    inspection's `service_date`, and the attraction's `operational_posture` is
    recomputed".

    Design: Difficulty/priority_pair_validation_conflict/signoff_state_check_priority_7_wins_over_blocking_item_8_and_segregation_11
    """
    bundle = _boardwalk_bullet_blocked()
    api_client.sign_off_daily_inspection(
        bundle["inspection"]["id"], make_qualified_inspector_headers("u-77")
    )

    inspection = validate_success(
        api_client.get_daily_inspection(bundle["inspection"]["id"], MANAGER)
    )
    assert_inspection_counters(
        inspection, status="BLOCKED", blocking=1, pending=0
    )
    assert inspection["recorded_by_user_ids"] == ["u-77"]
    assert inspection["signed_off_by_user_id"] is None
    assert_instant_equals(inspection["signed_off_at"], None, "signed_off_at")

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["last_signed_off_service_date"] is None
