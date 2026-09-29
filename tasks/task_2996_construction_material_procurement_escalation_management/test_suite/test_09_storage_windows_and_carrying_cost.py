"""Bailed off-site storage: occupancy windows, the handling buffer and carrying cost.

Covers the closed warehouse-occupancy interval inflated by the three-day handling buffer,
the release-date floor on `stored_from` and its precedence over a warehouse collision, and
the carrying-cost accrual whose two per-month components are each rounded to 2 decimal
places before they are added.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    arrange_storage,
    assert_instant_equals,
    assert_storage_arrangement,
    build_released_scenario,
    build_stored_offsite_scenario,
    countersign_commitment,
    expected_carrying_cost,
    expected_escalation_accrued,
    expected_monthly_carrying_charge,
    file_mandatory_documents,
    issue_commitment,
    move_posture,
    open_project,
    read_commitment,
    register_package,
    register_supplier,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
    whole_months_between,
)
from test_helpers.factories import create_storage_arrangement_payload

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]

WAREHOUSE = "Harbor Yard 7"
WAREHOUSE_ADDRESS = "7 Harbor Yard Road, Bayonne NJ"
STORED_VALUE = 862500.00
MONTHLY_RATE_PCT = 0.1875


# ─── private setup helpers (not tests — no Design tag) ────────────────────

def _read_arrangement_response(arrangement_id):
    """GET one arrangement through validate_success so the 200 is checked too."""
    data = validate_success(
        api_client.get_storage_arrangement(arrangement_id, BUYOUT_MANAGER)
    )
    assert_storage_arrangement(data)
    return data


def _setup_two_released_early_buyouts(po_prefix):
    """Two early-buyout commitments RELEASED_FOR_FAB at 2026-08-05, plus arrangement A.

    Arrangement A occupies 'Harbor Yard 7' from 2026-09-20 through 2026-12-31. Neither
    commitment carries an escalation clause, so releasing them recognises no escalation
    and consumes none of the project's contingency.
    """
    project = open_project()
    package_a = register_package(project["id"])
    package_b = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        estimated_cost=300000.00,
        required_onsite_date="2027-04-01T00:00:00.000Z",
        fabrication_duration_days=40,
        delivery_transit_days=15,
        submittal_review_days=21,
    )
    supplier = register_supplier()
    quote_a = submit_quote(package_a["id"], supplier["id"], base_price=1150000.00)
    quote_b = submit_quote(package_b["id"], supplier["id"], base_price=280000.00)

    commitment_a = issue_commitment(
        project["id"],
        quote_a["id"],
        po_number=f"{po_prefix}-1",
        is_early_buyout=True,
    )
    countersign_commitment(commitment_a["id"])
    commitment_b = issue_commitment(
        project["id"],
        quote_b["id"],
        po_number=f"{po_prefix}-2",
        is_early_buyout=True,
    )
    countersign_commitment(commitment_b["id"])

    set_clock("2026-08-05T00:00:00.000Z")
    move_posture(commitment_a["id"], "RELEASED_FOR_FAB")
    move_posture(commitment_b["id"], "RELEASED_FOR_FAB")

    arrangement_a = arrange_storage(
        commitment_a["id"],
        warehouse_name=WAREHOUSE,
        warehouse_address=WAREHOUSE_ADDRESS,
        stored_value=STORED_VALUE,
        monthly_storage_rate_pct=MONTHLY_RATE_PCT,
        stored_from="2026-09-20T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
    )
    return {
        "project": project,
        "package_a": package_a,
        "package_b": package_b,
        "supplier": supplier,
        "commitment_a": commitment_a,
        "commitment_b": commitment_b,
        "arrangement_a": arrangement_a,
    }


def _second_booking_payload(commitment_id, stored_from, planned_release_date):
    """A second Harbor Yard 7 booking for the sibling commitment."""
    return create_storage_arrangement_payload(
        purchase_commitment_id=commitment_id,
        warehouse_name=WAREHOUSE,
        warehouse_address=WAREHOUSE_ADDRESS,
        stored_value=250000.00,
        monthly_storage_rate_pct=0.2,
        stored_from=stored_from,
        planned_release_date=planned_release_date,
    )


def _arrangement_count_for_commitment(commitment_id):
    _rows, meta = validate_paginated(
        api_client.list_storage_arrangements(
            BUYOUT_MANAGER, params={"purchase_commitment_id": commitment_id}
        )
    )
    return meta["total_count"]


def _arrangement_count_for_warehouse(warehouse_name):
    _rows, meta = validate_paginated(
        api_client.list_storage_arrangements(
            BUYOUT_MANAGER, params={"warehouse_name": warehouse_name}
        )
    )
    return meta["total_count"]

# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula /
#          storage_carrying_cost_rounds_per_month_before_multiplying
# ---------------------------------------------------------------------------

def test_storage_carrying_cost_rounds_each_component_before_multiplying_by_months():
    """Three whole months at 862500.00 and 0.1875 percent accrue 5304.39, not 5304.38.

    PRD §3.7: "Each of those two components is rounded half up to 2 decimal places
    **before** they are added, the two rounded figures are summed into a per-month charge,
    and the per-month charge is multiplied by the whole-month count and rounded half up to
    2 decimal places again." PRD §3.7: "For a stored value of 862500.00 at a monthly rate
    of 0.1875 percent over three whole months, the storage component rounds from 1617.1875
    to 1617.19 and the insurance component rounds from 150.9375 to 150.94, giving 1768.13
    per month and 5304.39 in total; summing the unrounded monthly values and rounding once
    at the end would give 5304.38, and that is the wrong answer." PRD §2.6: "Summing
    unrounded monthly amounts and rounding once at the end is wrong."

    Design: Difficulty/combinatorial_formula/storage_carrying_cost_rounds_per_month_before_multiplying
    """
    scenario = build_stored_offsite_scenario()
    arrangement_id = scenario["arrangement"]["id"]

    # stored_from is 2026-09-20; 2026-12-20 is exactly three whole months later.
    set_clock("2026-12-20T00:00:00.000Z")
    assert whole_months_between(
        "2026-09-20T00:00:00.000Z", "2026-12-20T00:00:00.000Z"
    ) == 3

    data = _read_arrangement_response(arrangement_id)
    assert data["status"] == "ACTIVE"
    assert data["documentation_status"] == "COMPLETE"
    assert data["carrying_cost_frozen_at"] is None
    assert data["stored_value"] == pytest.approx(STORED_VALUE, abs=0.005)
    assert data["monthly_storage_rate_pct"] == pytest.approx(MONTHLY_RATE_PCT, abs=1e-9)

    per_month = expected_monthly_carrying_charge(STORED_VALUE, MONTHLY_RATE_PCT)
    assert per_month == pytest.approx(1768.13, abs=0.005)
    expected_total = expected_carrying_cost(STORED_VALUE, MONTHLY_RATE_PCT, 3)
    assert expected_total == pytest.approx(5304.39, abs=0.005)

    assert data["carrying_cost_accrued"] == pytest.approx(expected_total, abs=0.005)
    assert data["carrying_cost_accrued"] == pytest.approx(5304.39, abs=0.005)
    # The sum-then-round path would report 5304.38 and is explicitly the wrong answer.
    assert abs(data["carrying_cost_accrued"] - 5304.38) > 0.005

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["commitment_status"] == "COMMITTED"
    assert commitment["delivery_posture"] == "STORED_OFFSITE"


def test_storage_carrying_cost_ignores_a_partial_month_after_the_first_whole_one():
    """One whole month charges 1768.13 and the following partial month adds nothing.

    PRD §3.7: "Carrying cost accrues by whole elapsed months and is reported in
    `carrying_cost_accrued`." PRD §3.7: "The month count is the number of whole months from
    `stored_from` up to that instant: counting from one upward, each month step is included
    while `stored_from` advanced by that many months still falls at or before the evaluation
    instant". PRD §3.7: "A partial month contributes nothing." PRD §3.7: "Each of those two
    components is rounded half up to 2 decimal places **before** they are added, the two
    rounded figures are summed into a per-month charge, and the per-month charge is
    multiplied by the whole-month count and rounded half up to 2 decimal places again."

    Design: Difficulty/combinatorial_formula/storage_carrying_cost_rounds_per_month_before_multiplying
    """
    scenario = build_stored_offsite_scenario()
    arrangement_id = scenario["arrangement"]["id"]
    per_month = expected_monthly_carrying_charge(STORED_VALUE, MONTHLY_RATE_PCT)
    assert per_month == pytest.approx(1768.13, abs=0.005)

    # Exactly one whole month after 2026-09-20.
    set_clock("2026-10-20T00:00:00.000Z")
    one_month = _read_arrangement_response(arrangement_id)
    assert whole_months_between(
        "2026-09-20T00:00:00.000Z", "2026-10-20T00:00:00.000Z"
    ) == 1
    assert one_month["carrying_cost_accrued"] == pytest.approx(1768.13, abs=0.005)
    assert one_month["carrying_cost_accrued"] == pytest.approx(
        expected_carrying_cost(STORED_VALUE, MONTHLY_RATE_PCT, 1), abs=0.005
    )

    # One day short of the second whole month: the partial month contributes nothing.
    set_clock("2026-11-19T00:00:00.000Z")
    still_one_month = _read_arrangement_response(arrangement_id)
    assert whole_months_between(
        "2026-09-20T00:00:00.000Z", "2026-11-19T00:00:00.000Z"
    ) == 1
    assert still_one_month["carrying_cost_accrued"] == pytest.approx(1768.13, abs=0.005)

    # The second whole month lands the very next day and doubles the per-month charge.
    set_clock("2026-11-20T00:00:00.000Z")
    two_months = _read_arrangement_response(arrangement_id)
    assert two_months["carrying_cost_accrued"] == pytest.approx(3536.26, abs=0.005)
    assert two_months["carrying_cost_accrued"] == pytest.approx(
        expected_carrying_cost(STORED_VALUE, MONTHLY_RATE_PCT, 2), abs=0.005
    )


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          storage_window_temporal_check_beats_warehouse_conflict_constraint
# ---------------------------------------------------------------------------

def test_storage_window_temporal_defect_outranks_the_warehouse_collision():
    """A booking that both predates its release and collides is a storage-window error.

    PRD §2.9: "When a storage arrangement is created whose `stored_from` precedes the
    commitment's `released_for_fab_at` *and* whose occupancy window also collides with
    another arrangement in the same warehouse, the temporal check wins and the answer is
    `ERR_STORAGE_WINDOW_INVALID`, never `ERR_WAREHOUSE_WINDOW_CONFLICT`." PRD §3.7: "When a
    proposed arrangement both starts before its commitment was released *and* collides with
    a neighbour, the answer is `ERR_STORAGE_WINDOW_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/storage_window_temporal_check_beats_warehouse_conflict_constraint
    """
    scenario = _setup_two_released_early_buyouts("PO-2996-0031")
    commitment_b = scenario["commitment_b"]
    arrangement_a = scenario["arrangement_a"]

    # 2026-07-15 precedes released_for_fab_at (2026-08-05) and the window
    # 2026-07-15 .. 2026-10-15 straddles arrangement A's 2026-09-20 .. 2026-12-31.
    response = api_client.create_storage_arrangement(
        _second_booking_payload(
            commitment_b["id"],
            "2026-07-15T00:00:00.000Z",
            "2026-10-15T00:00:00.000Z",
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_STORAGE_WINDOW_INVALID.value, 422)

    assert _arrangement_count_for_commitment(commitment_b["id"]) == 0
    assert _arrangement_count_for_warehouse(WAREHOUSE) == 1

    unchanged = _read_arrangement_response(arrangement_a["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["documentation_status"] == "INCOMPLETE"
    assert unchanged["version"] == arrangement_a["version"]

    still_released = read_commitment(commitment_b["id"])
    assert still_released["delivery_posture"] == "RELEASED_FOR_FAB"
    assert still_released["commitment_status"] == "COMMITTED"


def test_storage_warehouse_collision_alone_is_reported_as_a_window_conflict():
    """With a legal `stored_from`, the same neighbour overlap is the 409 conflict code.

    PRD §3.7: "And the occupancy interval — which is **closed** at both ends, so both
    `stored_from` and `planned_release_date` are themselves inside it — must not collide
    with the interval of any other arrangement in the same `warehouse_name` whose status is
    `DRAFT`, `ACTIVE` or `SUSPENDED`, once both intervals are inflated by a three-day
    handling buffer at each end to allow for inbound and outbound handling. A collision is
    `ERR_WAREHOUSE_WINDOW_CONFLICT`." PRD §3.7: "The `stored_from` instant may not precede
    the commitment's `released_for_fab_at`, and `planned_release_date` must be strictly
    after `stored_from`; either violation is `ERR_STORAGE_WINDOW_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/storage_window_temporal_check_beats_warehouse_conflict_constraint
    """
    scenario = _setup_two_released_early_buyouts("PO-2996-0041")
    commitment_b = scenario["commitment_b"]
    arrangement_a = scenario["arrangement_a"]

    # 2026-10-01 is after released_for_fab_at, so only the collision remains.
    response = api_client.create_storage_arrangement(
        _second_booking_payload(
            commitment_b["id"],
            "2026-10-01T00:00:00.000Z",
            "2027-01-31T00:00:00.000Z",
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_WAREHOUSE_WINDOW_CONFLICT.value, 409)

    assert _arrangement_count_for_commitment(commitment_b["id"]) == 0
    assert _arrangement_count_for_warehouse(WAREHOUSE) == 1

    unchanged = _read_arrangement_response(arrangement_a["id"])
    assert unchanged["status"] == "DRAFT"
    assert_instant_equals(unchanged["stored_from"], "2026-09-20T00:00:00.000Z")
    assert_instant_equals(unchanged["planned_release_date"], "2026-12-31T00:00:00.000Z")


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap /
#          warehouse_occupancy_buffer_blocks_a_booking_three_days_after_release
# ---------------------------------------------------------------------------

def test_storage_handling_buffer_blocks_a_booking_three_days_after_the_neighbour():
    """A booking starting three days after the neighbour's release still collides.

    The neighbour occupies Harbor Yard 7 through 2026-12-31 inclusive, so a raw interval
    comparison would clear a 2027-01-03 start; the handling buffer does not.

    PRD §3.7: "And the occupancy interval — which is **closed** at both ends, so both
    `stored_from` and `planned_release_date` are themselves inside it — must not collide
    with the interval of any other arrangement in the same `warehouse_name` whose status is
    `DRAFT`, `ACTIVE` or `SUSPENDED`, once both intervals are inflated by a three-day
    handling buffer at each end to allow for inbound and outbound handling. A collision is
    `ERR_WAREHOUSE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/warehouse_occupancy_buffer_blocks_a_booking_three_days_after_release
    """
    scenario = _setup_two_released_early_buyouts("PO-2996-0051")
    commitment_b = scenario["commitment_b"]
    arrangement_a = scenario["arrangement_a"]

    response = api_client.create_storage_arrangement(
        _second_booking_payload(
            commitment_b["id"],
            "2027-01-03T00:00:00.000Z",
            "2027-04-30T00:00:00.000Z",
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_WAREHOUSE_WINDOW_CONFLICT.value, 409)

    assert _arrangement_count_for_commitment(commitment_b["id"]) == 0
    assert _arrangement_count_for_warehouse(WAREHOUSE) == 1

    unchanged = _read_arrangement_response(arrangement_a["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == arrangement_a["version"]


def test_storage_booking_clear_of_the_handling_buffer_is_accepted():
    """A start clear of both intervals' three-day buffers is booked in the same warehouse.

    PRD §3.7: "once both intervals are inflated by a three-day handling buffer at each end
    to allow for inbound and outbound handling." PRD §3.7: "A new arrangement starts in
    `DRAFT` with `documentation_status` `INCOMPLETE`, `verified_doc_type_count` 0 and
    `carrying_cost_frozen_at` null." PRD §3.7: "an arrangement still in `DRAFT`, or one
    whose `stored_from` the clock has not yet reached, reports 0.00."

    Design: Difficulty/resource_temporal_overlap/warehouse_occupancy_buffer_blocks_a_booking_three_days_after_release
    """
    scenario = _setup_two_released_early_buyouts("PO-2996-0061")
    commitment_b = scenario["commitment_b"]

    # Arrangement A ends 2026-12-31; inflating both intervals by three days at each end
    # leaves 2027-01-07 as the first start that clears the neighbour.
    created = validate_success(
        api_client.create_storage_arrangement(
            _second_booking_payload(
                commitment_b["id"],
                "2027-01-07T00:00:00.000Z",
                "2027-04-30T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_storage_arrangement(created)
    assert created["purchase_commitment_id"] == commitment_b["id"]
    assert created["warehouse_name"] == WAREHOUSE
    assert created["status"] == "DRAFT"
    assert created["documentation_status"] == "INCOMPLETE"
    assert created["verified_doc_type_count"] == 0
    assert created["carrying_cost_frozen_at"] is None
    assert created["stored_value"] == pytest.approx(250000.00, abs=0.005)
    assert_instant_equals(created["stored_from"], "2027-01-07T00:00:00.000Z")
    assert_instant_equals(created["planned_release_date"], "2027-04-30T00:00:00.000Z")

    assert _arrangement_count_for_commitment(commitment_b["id"]) == 1
    assert _arrangement_count_for_warehouse(WAREHOUSE) == 2

    # The clock (2026-08-05) has not reached stored_from, so nothing has accrued.
    read_back = _read_arrangement_response(created["id"])
    assert read_back["carrying_cost_accrued"] == pytest.approx(0.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: calculations /
#          chronological_a_full_month_clamps_to_the_shorter_target_month
# ---------------------------------------------------------------------------

def test_storage_whole_month_from_the_31st_clamps_to_the_shorter_target_month():
    """Stored from 2026-08-31, the first whole month completes on 2026-09-30, not before.

    PRD §3.7: "The month count is the number of whole months from `stored_from` up to that
    instant: counting from one upward, each month step is included while `stored_from`
    advanced by that many months still falls at or before the evaluation instant, with the
    day-of-month clamped to the target month's length when necessary — advancing the 31st of
    January by one month lands on the 28th of February in a non-leap year." PRD §3.7: "A
    partial month contributes nothing." PRD §3.7: "For a stored value of 862500.00 at a
    monthly rate of 0.1875 percent over three whole months, the storage component rounds
    from 1617.1875 to 1617.19 and the insurance component rounds from 150.9375 to 150.94,
    giving 1768.13 per month".

    Design: Corner/calculations/chronological_a_full_month_clamps_to_the_shorter_target_month
    """
    scenario = build_released_scenario(
        release_at="2026-08-05T00:00:00.000Z",
        readings=[("2026-07", 310.00), ("2026-08", 322.00)],
        commitment_overrides={"is_early_buyout": True},
    )
    arrangement = arrange_storage(
        scenario["commitment"]["id"],
        warehouse_name=WAREHOUSE,
        warehouse_address=WAREHOUSE_ADDRESS,
        stored_value=STORED_VALUE,
        monthly_storage_rate_pct=MONTHLY_RATE_PCT,
        stored_from="2026-08-31T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
    )
    file_mandatory_documents(
        arrangement["id"],
        STORED_VALUE,
        effective_date="2026-08-01T00:00:00.000Z",
        expires_at="2027-06-01T00:00:00.000Z",
    )

    # 2026-09-29: advancing 2026-08-31 by one month clamps to 2026-09-30, which is later.
    set_clock("2026-09-29T00:00:00.000Z")
    partial = _read_arrangement_response(arrangement["id"])
    assert whole_months_between(
        "2026-08-31T00:00:00.000Z", "2026-09-29T00:00:00.000Z"
    ) == 0
    assert partial["status"] == "ACTIVE"
    assert partial["documentation_status"] == "COMPLETE"
    assert partial["carrying_cost_accrued"] == pytest.approx(0.00, abs=0.005)

    # 2026-09-30 is the clamped landing day, so the first whole month is complete.
    set_clock("2026-09-30T00:00:00.000Z")
    one_month = _read_arrangement_response(arrangement["id"])
    assert whole_months_between(
        "2026-08-31T00:00:00.000Z", "2026-09-30T00:00:00.000Z"
    ) == 1
    assert one_month["carrying_cost_accrued"] == pytest.approx(1768.13, abs=0.005)
    assert one_month["carrying_cost_accrued"] == pytest.approx(
        expected_carrying_cost(STORED_VALUE, MONTHLY_RATE_PCT, 1), abs=0.005
    )
    assert one_month["carrying_cost_frozen_at"] is None

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["commitment_status"] == "COMMITTED"
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"
    assert commitment["escalation_variant"] == "PROVISIONAL"
    assert commitment["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 310.00, 322.00, 2.0, 8.0, 40.0),
        abs=0.005,
    )
    assert commitment["escalation_accrued"] == pytest.approx(12909.90, abs=0.005)
