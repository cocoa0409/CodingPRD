"""The permitting dimension: its own cycle, its inclusive unit threshold and the
jurisdiction's aggregate inspection capacity.

`permit_status` advances on triggers of its own and may loop through a failed
inspection any number of times while the execution and money dimensions stand still.
"""

import pytest

from test_helpers import (
    PROJECT_COORDINATOR,
    ApiErrorId,
    FinancialStatus,
    FulfillmentStatus,
    PermitResponsibleParty,
    PermitStatus,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_units,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
)

DEPOSIT = 59002

FIRST_SLOT = ("2026-08-06T09:00:00.000Z", "2026-08-06T11:00:00.000Z")
SECOND_SLOT = ("2026-08-08T09:00:00.000Z", "2026-08-08T11:00:00.000Z")


def test_permit_dimension_cycles_through_a_failed_inspection(api):
    """A failed inspection clears the booked slot, a second booking is accepted, and
    the passing verdict lands the permit at CLOSED inside the same request.

    PRD 3.5: "A `FAILED` result moves `permit_status` to `INSPECTION_FAILED` and clears
    `inspection_slot_start` and `inspection_slot_end` back to null, which releases the
    jurisdiction capacity for the next project in the queue."

    Design: Difficulty/non_linear_state_machine/project_permit_dimension_cycles_while_fulfillment_and_financial_hold_still
    """
    ctx = fx.permit_issued_project(api, 18500, "2026-08-04T00:00:00.000Z")
    project_id = ctx["project"]["id"]
    assert_project_dimensions(ctx["project"], permit=PermitStatus.ISSUED)

    project = get_success_data(
        api.reserve_inspection_slot(project_id,
                                    f.inspection_slot_payload(*FIRST_SLOT),
                                    PROJECT_COORDINATOR)
    )
    assert_project_dimensions(project, permit=PermitStatus.INSPECTION_SCHEDULED)
    assert_instant(project["inspection_slot_start"], FIRST_SLOT[0],
                   "inspection_slot_start")

    project = get_success_data(
        api.record_inspection_result(
            project_id,
            f.inspection_result_payload(
                "FAILED",
                inspector_note="Missing transition strip at the hall threshold"),
            PROJECT_COORDINATOR)
    )
    assert_project_dimensions(project, permit=PermitStatus.INSPECTION_FAILED)
    assert project["inspection_slot_start"] is None
    assert project["inspection_slot_end"] is None
    assert project["inspection_attempt_count"] == 1

    project = get_success_data(
        api.reserve_inspection_slot(project_id,
                                    f.inspection_slot_payload(*SECOND_SLOT),
                                    PROJECT_COORDINATOR)
    )
    assert_project_dimensions(project, permit=PermitStatus.INSPECTION_SCHEDULED)

    project = get_success_data(
        api.record_inspection_result(project_id,
                                     f.inspection_result_payload("PASSED"),
                                     PROJECT_COORDINATOR)
    )
    # There is no separate close-permit operation: the pass lands on CLOSED directly.
    assert_project_dimensions(project, permit=PermitStatus.CLOSED)
    assert project["inspection_result"] == "PASSED"
    assert project["inspection_attempt_count"] == 2
    # The slot instants are left in place on a pass.
    assert_instant(project["inspection_slot_start"], SECOND_SLOT[0],
                   "inspection_slot_start after the pass")
    assert_instant(project["inspection_slot_end"], SECOND_SLOT[1],
                   "inspection_slot_end after the pass")


def test_the_other_two_dimensions_do_not_move_while_the_permit_cycles(api):
    """Four permit transitions later, the execution dimension is still MEASURED and the
    money dimension is still DEPOSIT_HELD.

    PRD 2.9: "A deposit may be taken while execution is still at `DRAFT`,
    `MEASURE_PENDING`, `MEASURED` or `CHANGE_PENDING`; a permit may progress while the
    install has not started."

    Design: Difficulty/non_linear_state_machine/project_permit_dimension_cycles_while_fulfillment_and_financial_hold_still
    """
    ctx = fx.permit_issued_project(api, 18500, "2026-08-04T00:00:00.000Z")
    project_id = ctx["project"]["id"]

    def _steady(project, where):
        assert project["fulfillment_status"] == FulfillmentStatus.MEASURED, (
            f"fulfillment_status moved {where}"
        )
        assert project["financial_status"] == FinancialStatus.DEPOSIT_HELD, (
            f"financial_status moved {where}"
        )
        assert_money(project["deposit_held_cents"], DEPOSIT, "deposit_held_cents")

    _steady(ctx["project"], "on the permit issue")
    project = get_success_data(
        api.reserve_inspection_slot(project_id,
                                    f.inspection_slot_payload(*FIRST_SLOT),
                                    PROJECT_COORDINATOR)
    )
    _steady(project, "on the first booking")
    project = get_success_data(
        api.record_inspection_result(project_id,
                                     f.inspection_result_payload("FAILED"),
                                     PROJECT_COORDINATOR)
    )
    _steady(project, "on the failed inspection")
    project = get_success_data(
        api.reserve_inspection_slot(project_id,
                                    f.inspection_slot_payload(*SECOND_SLOT),
                                    PROJECT_COORDINATOR)
    )
    _steady(project, "on the second booking")
    project = get_success_data(
        api.record_inspection_result(project_id,
                                     f.inspection_result_payload("PASSED"),
                                     PROJECT_COORDINATOR)
    )
    _steady(project, "on the passing inspection")

    assert_money(project["permit_fee_cents_billed"], 18500,
                 "permit_fee_cents_billed")
    assert project["final_labor_cents"] is None
    # total_due_cents is zero while final_labor_cents is null, permit fee included.
    assert_money(project["total_due_cents"], 0, "total_due_cents")
    assert_money(project["balance_due_cents"], 0, "balance_due_cents")


@pytest.mark.parametrize(
    "estimated_units,quoted,deposit,permit_status,responsibility",
    [
        (249.99, 120228, 36068, PermitStatus.NOT_REQUIRED,
         PermitResponsibleParty.NOT_REQUIRED),
        (250.00, 120233, 36070, PermitStatus.PENDING_APPLICATION,
         PermitResponsibleParty.RETAILER),
    ],
)
def test_units_exactly_at_the_permit_threshold_need_a_permit(
        api, estimated_units, quoted, deposit, permit_status, responsibility):
    """A project sold at exactly the jurisdiction's `permit_unit_threshold` needs a
    permit; one sold a hundredth of a unit below it does not.

    PRD 3.5: "That unit test is an **inclusive** lower bound — `effective_units`
    exactly equal to `permit_unit_threshold` does require a permit."

    Design: Difficulty/boundary_precision_check/estimated_units_exactly_at_permit_unit_threshold_requires_a_permit
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=estimated_units)

    assert_units(project["effective_units"], estimated_units, "effective_units")
    assert project["permit_status"] == permit_status
    assert project["permit_responsibility"] == responsibility
    assert_money(project["quoted_labor_cents"], quoted, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], deposit,
                 "deposit_required_cents")
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING,
                              financial=FinancialStatus.QUOTED)


def test_the_threshold_decision_does_not_disturb_the_other_dimensions(api):
    """The two sides of the threshold differ on the permitting dimension alone: the
    execution and money dimensions open identically.

    PRD 3.5: "Second, when no permit is needed, both `permit_responsibility` and
    `permit_status` are set to `NOT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/estimated_units_exactly_at_permit_unit_threshold_requires_a_permit
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    below = fx.sell_project(api, base, estimated_units=249.99)
    at_threshold = fx.sell_project(api, base, estimated_units=250.00,
                                   site_address="20 Larch Way")

    assert below["permit_status"] == PermitStatus.NOT_REQUIRED
    assert at_threshold["permit_status"] == PermitStatus.PENDING_APPLICATION
    for project in (below, at_threshold):
        assert_project_dimensions(project,
                                  fulfillment=FulfillmentStatus.MEASURE_PENDING,
                                  financial=FinancialStatus.QUOTED)
        assert_money(project["deposit_paid_cents"], 0, "deposit_paid_cents")
        assert project["final_labor_cents"] is None
    # One extra hundredth of a unit is charged in the second tier at 391 cents and
    # then multiplied by 1.15, so the two frozen quotes differ by five cents.
    assert at_threshold["quoted_labor_cents"] - below["quoted_labor_cents"] == 5


def _three_permitted_projects(api):
    """Three projects in one jurisdiction whose permits have all been issued, so all
    three are eligible to book an inspection slot."""
    base = fx.program_baseline(api, f.quick_category_payload(),
                               f.jurisdiction_payload(inspection_required=True))
    projects = []
    for address, reference in (("1 Beacon Row", "MC-2026-0001"),
                               ("3 Beacon Row", "MC-2026-0002"),
                               ("5 Beacon Row", "MC-2026-0003")):
        project = fx.sell_project(api, base, site_address=address)
        get_success_data(api.apply_permit(project["id"],
                                          f.permit_apply_payload(reference),
                                          PROJECT_COORDINATOR))
        project = get_success_data(
            api.issue_permit(project["id"],
                             f.permit_issue_payload(18500,
                                                    "2026-08-01T00:00:00.000Z"),
                             PROJECT_COORDINATOR)
        )
        projects.append(project)
    base["projects"] = projects
    return base


def test_a_slot_touching_end_to_start_counts_against_the_capacity(api):
    """Two projects already hold overlapping slots; a third slot that merely touches
    the first one's end is still an overlap, so the jurisdiction is full.

    PRD 3.5: "The overlap test treats each slot as a **closed, inclusive** interval, so
    two slots that merely touch end-to-start do count as overlapping."

    Design: Difficulty/resource_temporal_overlap/jurisdiction_inspection_slots_are_closed_intervals_counted_in_aggregate
    """
    ctx = _three_permitted_projects(api)
    first, second, third = ctx["projects"]

    get_success_data(
        api.reserve_inspection_slot(
            first["id"],
            f.inspection_slot_payload("2026-08-10T09:00:00.000Z",
                                      "2026-08-10T11:00:00.000Z"),
            PROJECT_COORDINATOR)
    )
    get_success_data(
        api.reserve_inspection_slot(
            second["id"],
            f.inspection_slot_payload("2026-08-10T10:00:00.000Z",
                                      "2026-08-10T12:00:00.000Z"),
            PROJECT_COORDINATOR)
    )

    # 11:00:00 is the closed end of the first slot and sits inside the second, so the
    # count of other overlapping scheduled inspections reaches max_concurrent 2.
    response = api.reserve_inspection_slot(
        third["id"],
        f.inspection_slot_payload("2026-08-10T11:00:00.000Z",
                                  "2026-08-10T13:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSPECTION_CAPACITY_FULL)

    refused = fx.read_project(api, third["id"])
    assert_project_dimensions(refused, permit=PermitStatus.ISSUED)
    assert refused["inspection_slot_start"] is None
    assert refused["inspection_slot_end"] is None


def test_one_second_clear_of_the_closed_end_leaves_capacity(api):
    """Moving the third slot one second past the first slot's close drops the
    overlapping count to one, which is strictly below the cap.

    PRD 3.5: "The capacity limit counts **other** projects in the same jurisdiction
    whose `permit_status` is `INSPECTION_SCHEDULED` and whose recorded slot overlaps
    the requested one; when that count has already reached the jurisdiction's
    `max_concurrent_inspections`, the request is refused with
    `ERR_INSPECTION_CAPACITY_FULL`."

    Design: Difficulty/resource_temporal_overlap/jurisdiction_inspection_slots_are_closed_intervals_counted_in_aggregate
    """
    ctx = _three_permitted_projects(api)
    first, second, third = ctx["projects"]

    get_success_data(
        api.reserve_inspection_slot(
            first["id"],
            f.inspection_slot_payload("2026-08-10T09:00:00.000Z",
                                      "2026-08-10T11:00:00.000Z"),
            PROJECT_COORDINATOR)
    )
    get_success_data(
        api.reserve_inspection_slot(
            second["id"],
            f.inspection_slot_payload("2026-08-10T10:00:00.000Z",
                                      "2026-08-10T12:00:00.000Z"),
            PROJECT_COORDINATOR)
    )
    booked = get_success_data(
        api.reserve_inspection_slot(
            third["id"],
            f.inspection_slot_payload("2026-08-10T11:00:01.000Z",
                                      "2026-08-10T13:00:00.000Z"),
            PROJECT_COORDINATOR)
    )

    assert_project_dimensions(booked, permit=PermitStatus.INSPECTION_SCHEDULED)
    assert_instant(booked["inspection_slot_start"], "2026-08-10T11:00:01.000Z",
                   "inspection_slot_start")
    assert_instant(booked["inspection_slot_end"], "2026-08-10T13:00:00.000Z",
                   "inspection_slot_end")

    # The two incumbents are untouched by the third booking, and no inspection has
    # been recorded against any of the three.
    for project_id in (first["id"], second["id"]):
        incumbent = fx.read_project(api, project_id)
        assert_project_dimensions(incumbent,
                                  permit=PermitStatus.INSPECTION_SCHEDULED)
    for project_id in (first["id"], second["id"], third["id"]):
        project = fx.read_project(api, project_id)
        assert project["permit_responsibility"] == PermitResponsibleParty.RETAILER
        assert_money(project["permit_fee_cents_billed"], 18500,
                     "permit_fee_cents_billed")
        assert project["inspection_attempt_count"] == 0
        assert_project_dimensions(project,
                                  fulfillment=FulfillmentStatus.MEASURED,
                                  financial=FinancialStatus.QUOTED)
