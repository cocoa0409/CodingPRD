"""Every derived surface a write touches is already correct in the very next read: no settling step, no
second write, no refresh call.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_backlog_report,
    assert_fields,
    assert_list_meta,
    assert_workload,
)
from test_helpers.factories import assignment_payload
from test_helpers.fixtures import (
    accept_case,
    create_validated_method,
    log_evidence,
    raise_request,
    register_analyst,
    set_clock,
    submit_case,
)
from test_helpers.test_users import CASE_MANAGER_HEADERS


def test_the_reads_that_follow_an_assignment_already_show_every_cascade(api):
    """Raising the request has already moved the case into the awaiting-assignment queue and refreshed
    its open count; the assignment that follows is immediately visible in the workload read at 8.00
    encumbered hours and 25.00 percent, in the case read as in-progress, in the filtered queue listing
    and in the backlog report — all read straight after the write with nothing re-issued.

    PRD §3.3: "The case rollup of §2.10 then runs: a case that was `ACCEPTED` becomes
    `AWAITING_ASSIGNMENT` on its first request, and `open_examination_request_count` is refreshed."

    PRD §3.4: "The request's `assigned_analyst_id` is set to the incoming examiner, its own `version`
    increments, and the case rollup runs — a case that was `ACCEPTED` or `AWAITING_ASSIGNMENT` becomes
    `IN_PROGRESS`."

    PRD §3.4: "A third figure, `casework_training_ratio`, is 0.00 when `training_hours_per_week` is 0.00
    and otherwise `projected_load_hours` divided by `training_hours_per_week`, rounded half up to 2
    decimal places."

    PRD §3.4: "The **realized** variant answers "what did the work actually consume": its numerator,
    `realized_load_hours`, ranges over the examiner's assignments whose `status` is `ACTIVE` or
    `COMPLETED` and takes, for each one, the owning request's `actual_hours_logged` whenever that figure
    is not null and the assignment's snapshotted `estimated_hours` otherwise, summing and rounding half
    up to 2 decimal places; `realized_utilization_pct` is derived from it in the same way, and is
    likewise 0.00 when the available hours are 0.00."

    PRD §3.9: "The `backlog_index` is the mean of those weighted ages — their sum divided by
    `open_request_count`, rounded half up to 2 decimal places — and is exactly 0.00 when there are no
    open requests at all, with no division attempted."

    PRD §3.9: "Alongside them, `p1_open_count` counts the open requests whose case `priority_class` is
    `P1_STATUTORY`, and `outsourcing_recommended` is true exactly when `backlog_index` is at least 45.00
    — at exactly 45.00 the recommendation is already true."

    Design: Corner/consistency_model/assignment_cascades_are_visible_in_the_immediately_following_reads
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Read After Write Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Reference Sample Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-RST-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0513",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed reference card",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    assert_fields(accept_case(api, case["id"]), workflow_status="ACCEPTED")
    assert_workload(
        validate_success(
            api.get_analyst_workload(examiner["id"], CASE_MANAGER_HEADERS)
        ),
        assigned_casework_hours=0.00,
        projected_utilization_pct=0.00,
    )

    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)
    assert_fields(request, estimated_hours=8.00, status="QUEUED")
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        workflow_status="AWAITING_ASSIGNMENT",
        open_examination_request_count=1,
    )

    assignment = validate_success(
        api.create_assignment(
            request["id"],
            assignment_payload(
                examiner["id"], request["version"], assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(assignment, status="ACTIVE", estimated_hours=8.00)

    assert_workload(
        validate_success(
            api.get_analyst_workload(examiner["id"], CASE_MANAGER_HEADERS)
        ),
        assigned_casework_hours=8.00,
        projected_load_hours=8.00,
        projected_utilization_pct=25.00,
        realized_load_hours=8.00,
        casework_training_ratio=1.00,
        active_assignment_count=1,
    )
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        workflow_status="IN_PROGRESS",
    )

    rows, meta = validate_paginated(
        api.list_examination_requests(
            CASE_MANAGER_HEADERS,
            {"assigned_analyst_id": examiner["id"], "status": "ASSIGNED"},
        )
    )
    assert_list_meta(meta, expected_total=1, expected_has_more=False)
    assert [row["id"] for row in rows] == [request["id"]], (
        "The queue listing must show the request the assignment just moved"
    )

    assert_backlog_report(
        validate_success(
            api.get_backlog_report(CASE_MANAGER_HEADERS, {"discipline": "BIOLOGY"})
        ),
        open_request_count=1,
        backlog_index=0.00,
        bucket_0_29_count=1,
        p1_open_count=0,
        outsourcing_recommended=False,
        as_of_utc="2026-08-01T00:00:00Z",
    )
