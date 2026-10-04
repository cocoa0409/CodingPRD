"""Threshold-boundary precision: the utilization band floor at eight completed cases, and
the empty-conflict-set boundary that a cancelled sibling creates."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_utilization_band_matches_count,
    create_case,
    cancel_case,
    get_success_data,
    setup_commissioned_system,
    setup_commissioned_system_with_cases,
    validate_error,
    validate_success,
)


def test_seventh_completed_case_leaves_the_cycle_underutilized(api):
    """PRD §2.11: "The band is `UNDERUTILIZED` when the completed count is 7 or fewer".

    Design: Difficulty/boundary_precision_check/utilization_band_floor_at_eight_completed_cases
    """
    ctx = setup_commissioned_system_with_cases(case_count=7, complete=True)

    cycle = get_success_data(api_client.get_current_utilization_cycle(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))

    assert cycle["completed_case_count"] == 7
    assert cycle["utilization_band"] == "UNDERUTILIZED", (
        "one case below the floor still reads UNDERUTILIZED"
    )


def test_eighth_completed_case_crosses_the_cycle_into_baseline(api):
    """PRD §2.11: "The band is `UNDERUTILIZED` when the completed count is 7 or fewer,
    `BASELINE` from 8 through 14 inclusive, `HIGH` from 15 through 21 inclusive, and
    `EXPANSION_READY` at 22 or more."
    PRD §2.11: "Both lower edges are inclusive where it matters: a count of exactly 8 is
    `BASELINE` and not `UNDERUTILIZED`".

    Design: Difficulty/boundary_precision_check/utilization_band_floor_at_eight_completed_cases
    """
    ctx = setup_commissioned_system_with_cases(case_count=8, complete=True)

    cycle = get_success_data(api_client.get_current_utilization_cycle(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))

    assert cycle["completed_case_count"] == 8
    assert_utilization_band_matches_count(cycle)
    assert cycle["utilization_band"] == "BASELINE", (
        "the boundary flips exactly at 8: the floor is inclusive on the lower edge"
    )


def test_cancelling_the_blocking_sibling_frees_its_exact_slot(api):
    """PRD §3.4: "Occupancy is exclusive on a system. The conflict rule is evaluated in a
    pinned order: compute the candidate's buffered occupancy, then reject the booking when
    that occupancy overlaps the buffered occupancy of any non-cancelled case on the same
    `robot_system_id`, using the sibling's own `duration_minutes` and the same 30-minute buffer."
    PRD §3.4: "A case may be cancelled by either the `AccountOwner` or a
    `HospitalProcurementOfficer`, which moves it to `CANCELLED` and releases its instrument
    load back into the accessory-set accumulator."

    Design: Difficulty/boundary_precision_check/empty_collection_boundary_on_cancelled_case_reversal
    """
    ctx = setup_commissioned_system()
    blocker = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                          case_started_at="2026-09-10T08:00:00Z", duration_minutes=120,
                          instrument_load=0)

    # The buffered occupancy [08:00, 10:30) makes the identical slot a conflict.
    conflict = api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-10T08:00:00Z", "duration_minutes": 120,
         "instrument_load": 1, "is_emergency": False},
        ctx.account_headers)
    validate_error(conflict, "ERR_CASE_SCHEDULE_CONFLICT", expected_status=409)

    cancelled = validate_success(api_client.cancel_procedure_case(
        blocker["id"], {"expected_case_version": blocker["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    assert cancelled["case_status"] == "CANCELLED"

    replacement = validate_success(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-10T08:00:00Z", "duration_minutes": 120,
         "instrument_load": 1, "is_emergency": False},
        ctx.account_headers), 201)

    assert replacement["case_status"] == "SCHEDULED", (
        "the cancelled sibling contributes no occupancy, so the exact slot is free again"
    )


def test_a_cancelled_case_is_excluded_from_the_band_regardless_of_row_existence(api):
    """PRD §2.11: "only `COMPLETED` rows ever move it — `SCHEDULED` rows count toward the
    scheduled count but never toward the band."

    Design: Difficulty/boundary_precision_check/empty_collection_boundary_on_cancelled_case_reversal
    """
    ctx = setup_commissioned_system_with_cases(case_count=1, complete=False)
    case = ctx.cases[0]
    cancel_case(case, ctx.account["id"])

    cycle = get_success_data(api_client.get_current_utilization_cycle(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))

    assert cycle["completed_case_count"] == 0
    assert cycle["utilization_band"] == "UNDERUTILIZED"