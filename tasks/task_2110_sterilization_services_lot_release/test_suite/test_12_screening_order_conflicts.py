"""Screening order: when a request violates two rules at once, the earlier
check in the PRD's ascending order is the one reported."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_cycle_scenario,
    create_cycle,
    create_lot,
    create_load_position_payload,
    get_cycle,
    get_lot,
    get_permit,
    get_qualification,
    officer,
    open_aeration_record,
    operator,
    set_chamber_status,
    set_clock,
    setup_reference_data,
    validate_error,
)

BI_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 1,
}


def test_start_reports_cycle_not_ready_before_chamber_unavailable():
    """PRD 2.7: "Requests are screened in a strictly ascending order of checks,
    and the **first** check that fails determines the error returned. This
    ordering is part of the contract: a request that violates three rules must
    surface the earliest one."
    PRD 2.7: "Specific states raise specific errors: starting a cycle that is
    not `READY` yields `ERR_CYCLE_NOT_READY`"
    PRD 2.7: "**Chamber availability.** A chamber must have `status`
    `AVAILABLE` to start a cycle, and must not be `DECOMMISSIONED` to have a
    cycle scheduled in it; otherwise `ERR_CHAMBER_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/start_state_check_outranks_chamber_maintenance_safety_check
    """
    env = build_cycle_scenario(stage="loading")
    set_chamber_status(env["chamber"]["id"], "MAINTENANCE")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_READY)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "LOADING", "the refused start left the cycle untouched"
    assert cycle["operator_user_id"] is None
    assert get_permit(env["permit"]["id"])["consumed_kg_ytd"] == pytest.approx(0, abs=1e-9)


def test_start_from_planned_also_reports_cycle_not_ready_over_maintenance():
    """PRD 3.6: "The cycle must be `READY`, and a start attempted from any
    other state is refused specifically with `ERR_CYCLE_NOT_READY`."
    PRD 2.7: "Requests are screened in a strictly ascending order of checks,
    and the **first** check that fails determines the error returned. This
    ordering is part of the contract: a request that violates three rules must
    surface the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/start_state_check_outranks_chamber_maintenance_safety_check
    """
    env = build_cycle_scenario(stage="planned")
    set_chamber_status(env["chamber"]["id"], "MAINTENANCE")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_READY)
    assert get_cycle(env["cycle"]["id"])["status"] == "PLANNED"


def _setup_bi_positive_lot_still_aerating():
    env = build_cycle_scenario(
        stage="closed",
        modality="ETO",
        product_overrides={"requires_aeration": True},
        recipe_overrides=BI_RECIPE,
        bi_result="POSITIVE",
    )
    set_clock("2026-08-12T08:00:00Z")
    env["aeration_record"] = open_aeration_record(env["lot"]["id"])
    return env


def test_release_reports_bi_positive_before_the_residual_timing_gate():
    """PRD 2.7: "**Biological indicator positivity.** On release, no
    `BIOLOGICAL` indicator on the governing cycle may have `bi_result` equal to
    `POSITIVE`, otherwise `ERR_BI_POSITIVE_BLOCKS_RELEASE` (HTTP 409)."
    PRD 2.7: "**Residual timing.** A residual test may not be recorded before
    the logical clock reaches the aeration record's `target_end_at`, and a lot
    may not be released while its `residual_status` is `PENDING_AERATION` or
    `AERATING`; either violation yields `ERR_AERATION_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/release_bi_positive_safety_check_outranks_aeration_temporal_check
    """
    env = _setup_bi_positive_lot_still_aerating()
    assert get_lot(env["lot"]["id"])["residual_status"] == "AERATING"

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "DOSIMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_BI_POSITIVE_BLOCKS_RELEASE)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["residual_status"] == "AERATING"
    assert lot["quarantine_reason"] == "BI_POSITIVE"


def test_release_reports_bi_positive_before_the_cycle_conformance_gate():
    """PRD 2.7: "**Biological indicator positivity.** On release, no
    `BIOLOGICAL` indicator on the governing cycle may have `bi_result` equal to
    `POSITIVE`, otherwise `ERR_BI_POSITIVE_BLOCKS_RELEASE` (HTTP 409)."
    PRD 2.7: "**Cycle conformance.** On release, the governing cycle's `status`
    must be `DOSE_CONFORMING`, otherwise `ERR_CYCLE_DEVIATION_BLOCKS_RELEASE`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/release_bi_positive_safety_check_outranks_aeration_temporal_check
    """
    env = _setup_bi_positive_lot_still_aerating()
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSE_DEVIATION"

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "DOSIMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_BI_POSITIVE_BLOCKS_RELEASE)
    lot = get_lot(env["lot"]["id"])
    assert lot["release_mode"] == "NONE"
    assert lot["released_at"] is None


def _setup_oversized_placement(audit_positives: int):
    env = setup_reference_data(
        chamber_overrides={"pallet_capacity": 2},
        audit_positives=audit_positives,
    )
    lot = create_lot(
        env["customer"]["id"], env["product"]["id"], total_pallet_count=4
    )
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    env.update({"lot": lot, "cycle": cycle})
    return env


def test_load_position_reports_qualification_not_current_before_capacity():
    """PRD 2.7: "**Current qualification.** A `ProductQualification` for the
    product-and-recipe pair must exist with `status` either `QUALIFIED` or
    `CONDITIONAL`, otherwise `ERR_QUALIFICATION_NOT_CURRENT` (HTTP 409). This
    check guards both load-position creation and release."
    PRD 2.7: "**Capacity.** A load position may not push the cycle's
    `loaded_pallet_count` past the chamber's `pallet_capacity`, and its
    `pallet_count` may not exceed the lot's `available_pallet_count`; either
    violation yields `ERR_CHAMBER_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/load_position_qualification_safety_check_outranks_capacity_constraint
    """
    env = _setup_oversized_placement(audit_positives=2)
    assert get_qualification(env["qualification"]["id"])["status"] == "SUSPENDED"
    version = get_cycle(env["cycle"]["id"])["version"]

    response = api_client.create_load_position(
        env["cycle"]["id"],
        create_load_position_payload(env["lot"]["id"], version, pallet_count=4),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_QUALIFICATION_NOT_CURRENT)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "PLANNED"
    assert cycle["loaded_pallet_count"] == 0
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "RECEIVED"
    assert lot["staged_pallet_count"] == 0


def test_capacity_check_is_reached_once_the_qualification_is_current():
    """PRD 3.5: "The cycle's `loaded_pallet_count` plus the requested
    `pallet_count` must not exceed the chamber's `pallet_capacity`, and the
    requested `pallet_count` must not exceed the lot's
    `available_pallet_count`; either breach is refused with
    `ERR_CHAMBER_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/load_position_qualification_safety_check_outranks_capacity_constraint
    """
    env = _setup_oversized_placement(audit_positives=0)
    assert get_qualification(env["qualification"]["id"])["status"] == "QUALIFIED"
    version = get_cycle(env["cycle"]["id"])["version"]

    response = api_client.create_load_position(
        env["cycle"]["id"],
        create_load_position_payload(env["lot"]["id"], version, pallet_count=4),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED)
    assert get_cycle(env["cycle"]["id"])["loaded_pallet_count"] == 0
