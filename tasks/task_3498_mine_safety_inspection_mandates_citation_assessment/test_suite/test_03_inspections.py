"""Inspection workflow (PRD §3.3): assignment gates, the file-review loop,
half-open planned windows, the safety/engagement start gates, and the
REGULAR-completion plan gate.

Clock note: all logical-clock readings are >= the startup reading
2026-09-01T00:00:00Z (PRD §2.4); planned windows and lifecycle instants are
rebased onto 2026-09 dates with every relative interval preserved.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assign_inspection,
    assert_inspection,
    cancel_inspection_flow,
    create_inspection_payload,
    create_mine_payload,
    get_success_data,
    issue_ido,
    make_inspector_headers,
    open_cycle,
    reassign_inspection_flow,
    reassign_inspection_payload,
    refresh_cycle,
    refresh_inspection,
    refresh_mine,
    set_clock,
    setup_inspector,
    setup_mine,
    setup_registry,
    submit_and_approve_plan,
    validate_created,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]


def test_inspection_reassignment_cycle_resets_file_review(api):
    """PRD §3.3: "A `DistrictManager` may reassign an inspection that has not
    started by supplying `new_inspector_id`. From `ASSIGNED` this is a
    self-loop; from `FILE_REVIEWED` it returns the inspection to `ASSIGNED`,
    and in both cases `inspector_id` becomes the new inspector while
    `file_reviewed_at` resets to null — the new inspector must redo the file
    review, so the cycle `ASSIGNED` → `FILE_REVIEWED` → `ASSIGNED` →
    `FILE_REVIEWED` is genuinely reachable."
    PRD §3.3: "Only the inspector named on the inspection may record the
    review; any other inspector's attempt is rejected with
    `ERR_INSPECTOR_MISMATCH`."

    Design: Difficulty/non_linear_state_machine/inspection_reassignment_cycle_resets_file_review
    """
    set_clock("2026-09-05T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    i2 = setup_inspector()
    inspection = assign_inspection(
        mine, i1, kind="SPOT",
        planned_start_at="2026-09-15T08:00:00Z",
        planned_end_at="2026-09-15T17:00:00Z",
    )
    reviewed = get_success_data(
        api.file_review_inspection(inspection["id"], make_inspector_headers(i1["id"]))
    )
    assert reviewed["status"] == "FILE_REVIEWED"
    assert reviewed["file_reviewed_at"] is not None

    # FILE_REVIEWED -> ASSIGNED under reassignment; the review is wiped.
    reassigned = reassign_inspection_flow(reviewed, i2)
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["inspector_id"] == i2["id"]
    assert reassigned["file_reviewed_at"] is None, (
        "reassignment resets the file review; the old review no longer authorizes entry"
    )

    # The previous assignee can no longer act on the inspection.
    resp = api.file_review_inspection(inspection["id"], make_inspector_headers(i1["id"]))
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_MISMATCH)

    # The new inspector completes the loop: review again, then enter.
    re_reviewed = get_success_data(
        api.file_review_inspection(inspection["id"], make_inspector_headers(i2["id"]))
    )
    assert re_reviewed["status"] == "FILE_REVIEWED"
    started = get_success_data(
        api.start_inspection(inspection["id"], make_inspector_headers(i2["id"]))
    )
    assert started["status"] == "IN_PROGRESS"


def test_ido_safety_outranks_inspector_engagement(api):
    """PRD §2.5: "Every request is evaluated against an ordered cascade of
    validation tiers. When several checks would fail on the same request, the
    response reports the failure from the **earliest** tier; a request that
    fails an earlier tier never surfaces a later tier's error."
    PRD §3.3: "the safety gate refuses entry with `ERR_IMMINENT_DANGER_ACTIVE`
    while any imminent-danger order at the mine is not yet `TERMINATED`, and
    the engagement gate refuses an inspector who already holds another
    `IN_PROGRESS` inspection — capacity one — with `ERR_INSPECTOR_ENGAGED`."

    Design: Difficulty/priority_pair_validation_conflict/ido_safety_outranks_inspector_engagement
    """
    set_clock("2026-09-11T07:00:00Z")
    operator, mine1, i1 = setup_registry(mine_overrides={"mine_name": "Canyon No 14"})
    mine2 = get_success_data(
        api.create_mine(
            create_mine_payload(
                operator["id"], mine_name="Canyon No 15", mine_type="SURFACE",
                activation_date="2026-09-01",
            ),
            _ADMIN,
        )
    )
    i2 = setup_inspector()
    i1h = make_inspector_headers(i1["id"])

    insp_a = assign_inspection(
        mine1, i1, kind="SPOT",
        planned_start_at="2026-09-11T08:00:00Z",
        planned_end_at="2026-09-11T12:00:00Z",
    )
    insp_b = assign_inspection(
        mine2, i1, kind="SPOT",
        planned_start_at="2026-09-11T13:00:00Z",
        planned_end_at="2026-09-11T17:00:00Z",
    )
    get_success_data(api.file_review_inspection(insp_a["id"], i1h))
    get_success_data(api.file_review_inspection(insp_b["id"], i1h))

    set_clock("2026-09-11T09:00:00Z")
    get_success_data(api.start_inspection(insp_a["id"], i1h))  # i1 now engaged

    # A non-terminated order lands at mine2 while insp_b is still FILE_REVIEWED.
    set_clock("2026-09-11T14:00:00Z")
    issue_ido(mine2, i2, hazard_description="highwall instability")

    # Both the safety gate (tier 8) and the engagement gate (tier 10) fail;
    # the earlier tier is reported.
    resp = api.start_inspection(insp_b["id"], i1h)
    validate_error(resp, ApiErrorId.ERR_IMMINENT_DANGER_ACTIVE)
    assert refresh_inspection(insp_b["id"])["status"] == "FILE_REVIEWED"


def test_regular_completion_requires_all_plan_types_approved(api):
    """PRD §3.3: "For a `REGULAR` inspection there is one more gate, the
    required-plan gate: every plan type the mine's `mine_type` requires must be
    covered by a plan of this mine currently in `APPROVED` status — for an
    `UNDERGROUND` mine that is `VENTILATION`, `ROOF_CONTROL`, and
    `EMERGENCY_RESPONSE`; for a `SURFACE` mine it is `EMERGENCY_RESPONSE`
    alone."
    PRD §3.3: "a completion attempted without full coverage is rejected with
    `ERR_REQUIRED_PLAN_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/regular_completion_requires_all_plan_types_approved
    """
    set_clock("2026-09-05T09:00:00Z")
    operator, mine, inspector = setup_registry(mine_type="UNDERGROUND")
    cycle = open_cycle(mine)  # [2026-09-01, 2026-11-29]
    submit_and_approve_plan(mine, operator, "VENTILATION", "doc-vent-r1")
    submit_and_approve_plan(refresh_mine(mine["id"]), operator, "ROOF_CONTROL", "doc-roof-r1")
    # EMERGENCY_RESPONSE deliberately missing.

    i1h = make_inspector_headers(inspector["id"])
    inspection = assign_inspection(
        refresh_mine(mine["id"]), inspector, kind="REGULAR", cycle_id=cycle["id"],
        planned_start_at="2026-10-15T08:00:00Z",
        planned_end_at="2026-10-16T17:00:00Z",
    )
    get_success_data(api.file_review_inspection(inspection["id"], i1h))
    set_clock("2026-10-15T09:00:00Z")
    get_success_data(api.start_inspection(inspection["id"], i1h))

    set_clock("2026-10-16T10:00:00Z")
    resp = api.complete_inspection(inspection["id"], i1h)
    validate_error(resp, ApiErrorId.ERR_REQUIRED_PLAN_NOT_APPROVED)
    assert refresh_inspection(inspection["id"])["status"] == "IN_PROGRESS"

    # Approving the third required plan type unblocks the identical transition.
    submit_and_approve_plan(
        refresh_mine(mine["id"]), operator, "EMERGENCY_RESPONSE", "doc-erp-r1"
    )
    completed = get_success_data(api.complete_inspection(inspection["id"], i1h))
    assert completed["status"] == "COMPLETED"
    assert refresh_cycle(cycle["id"])["completed_inspections"] == 1, (
        "quota credit lands only after the plan gate passes"
    )


def test_inspector_planned_windows_half_open_adjacency(api):
    """PRD §3.3: "it occupies the inspector's schedule under half-open interval
    semantics: the window covers from `planned_start_at` up to but not
    including `planned_end_at`, so two windows that touch at exactly one
    endpoint do not overlap."
    PRD §3.3: "The double-booking gate rejects a planned window that overlaps
    any other window the inspector already occupies, where occupied means an
    inspection in `ASSIGNED`, `FILE_REVIEWED`, `IN_PROGRESS`, or `SUSPENDED`
    status, with `ERR_INSPECTOR_DOUBLE_BOOKED`."
    PRD §3.3: "A `DistrictManager` may also cancel an inspection from
    `ASSIGNED`, `FILE_REVIEWED`, or `SUSPENDED`, moving it to `CANCELLED` and
    releasing its planned window from the inspector's schedule."

    Design: Difficulty/resource_temporal_overlap/inspector_planned_windows_half_open_adjacency
    """
    set_clock("2026-09-05T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    insp_a = assign_inspection(
        mine, i1, kind="SPOT",
        planned_start_at="2026-09-10T08:00:00Z",
        planned_end_at="2026-09-10T12:00:00Z",
    )

    # Adjacent at exactly one endpoint ([08:00,12:00) then [12:00,17:00)): allowed.
    resp_b = api.create_inspection(
        create_inspection_payload(
            mine["id"], i1["id"], kind="SPOT",
            planned_start_at="2026-09-10T12:00:00Z",
            planned_end_at="2026-09-10T17:00:00Z",
        ),
        _DM,
    )
    validate_created(resp_b)

    # One minute of real overlap ([11:59,13:00) meets [08:00,12:00)): rejected.
    resp_c = api.create_inspection(
        create_inspection_payload(
            mine["id"], i1["id"], kind="SPOT",
            planned_start_at="2026-09-10T11:59:00Z",
            planned_end_at="2026-09-10T13:00:00Z",
        ),
        _DM,
    )
    validate_error(resp_c, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED)

    # Cancelling A releases its interval; a new window inside it succeeds.
    cancelled = cancel_inspection_flow(insp_a)
    assert cancelled["status"] == "CANCELLED"
    resp_d = api.create_inspection(
        create_inspection_payload(
            mine["id"], i1["id"], kind="SPOT",
            planned_start_at="2026-09-10T08:30:00Z",
            planned_end_at="2026-09-10T09:30:00Z",
        ),
        _DM,
    )
    validate_created(resp_d)


def test_inspection_create_with_unknown_mine_rejected(api):
    """PRD §2.5 tier 4: "Path identifiers resolve left-to-right, then body
    foreign keys resolve (`operator_id`, `mine_id`, `inspector_id`,
    `cycle_id`, `accident_id`, `citation_id`, `new_inspector_id`); the first
    unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/inspection_create_with_unknown_mine_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    inspector = setup_inspector()
    resp = api.create_inspection(
        create_inspection_payload(
            NON_EXISTENT_UUID, inspector["id"], kind="SPOT",
            planned_start_at="2026-09-10T08:00:00Z",
            planned_end_at="2026-09-10T17:00:00Z",
        ),
        _DM,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_inspection_starts_in_assigned_with_null_review(api):
    """PRD §3.3: "A successfully assigned inspection begins in `ASSIGNED`
    status."
    PRD §3.3: "the assigned inspector performs the mandatory pre-entry
    mine-file review, moving the inspection from `ASSIGNED` to `FILE_REVIEWED`
    and stamping `file_reviewed_at` with the current logical clock."
    PRD §3.3: "in both cases `inspector_id` becomes the new inspector while
    `file_reviewed_at` resets to null"

    (The reset-to-null contract proves null is the not-yet-set value for the
    review/entry/completion timestamps.)

    Design: Corner/state_machines/inspection_starts_in_assigned_with_null_review
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = assign_inspection(mine, i1, kind="SPOT")
    assert_inspection(inspection)
    assert inspection["status"] == "ASSIGNED"
    assert inspection["file_reviewed_at"] is None
    assert inspection["actual_entry_at"] is None
    assert inspection["completed_at"] is None
    assert isinstance(inspection["version"], int) and inspection["version"] >= 1


def test_inspection_complete_from_assigned_rejected(api):
    """PRD §3.3: "Completion moves an `IN_PROGRESS` inspection to `COMPLETED`
    and stamps `completed_at`."
    PRD §2.5 tier 7: "The entity is in a state that permits the transition,
    including the operating-mine requirement, the uncontested-citation
    requirement, and the potential-POV prerequisite; violations yield
    `ERR_INVALID_STATE`, `ERR_MINE_NOT_ACTIVE`, `ERR_CITATION_NOT_CONTESTABLE`,
    or `ERR_POV_NOTICE_REQUIRES_POTENTIAL` (HTTP 409)."

    Design: Corner/state_machines/inspection_complete_from_assigned_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = assign_inspection(mine, i1, kind="SPOT")
    resp = api.complete_inspection(inspection["id"], make_inspector_headers(i1["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = refresh_inspection(inspection["id"])
    assert after["status"] == "ASSIGNED"
    assert after["completed_at"] is None


def test_cancelled_inspection_rejects_all_transitions(api):
    """PRD §3.3: "`COMPLETED` and `CANCELLED` are terminal."
    PRD §2.5 tier 7: "The entity is in a state that permits the transition,
    including the operating-mine requirement, the uncontested-citation
    requirement, and the potential-POV prerequisite; violations yield
    `ERR_INVALID_STATE`, `ERR_MINE_NOT_ACTIVE`, `ERR_CITATION_NOT_CONTESTABLE`,
    or `ERR_POV_NOTICE_REQUIRES_POTENTIAL` (HTTP 409)."

    Design: Corner/state_machines/cancelled_inspection_rejects_all_transitions
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    i2 = setup_inspector()
    inspection = assign_inspection(mine, i1, kind="SPOT")
    cancelled = cancel_inspection_flow(inspection)
    assert cancelled["status"] == "CANCELLED"

    i1h = make_inspector_headers(i1["id"])
    for resp in (
        api.file_review_inspection(inspection["id"], i1h),
        api.start_inspection(inspection["id"], i1h),
        api.complete_inspection(inspection["id"], i1h),
        api.reassign_inspection(
            inspection["id"], reassign_inspection_payload(i2["id"]), _DM
        ),
    ):
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert refresh_inspection(inspection["id"])["status"] == "CANCELLED"


def test_reassign_to_conflicted_inspector_rejected(api):
    """PRD §3.3: "Reassignment re-applies the conflict and certification gates
    for the new inspector, with the same `ERR_INSPECTOR_CONFLICT` and
    `ERR_INSPECTOR_NOT_CERTIFIED` rejections."
    PRD §3.3: "The conflict gate rejects an inspector whose
    `conflicted_operator_ids` contains the mine's `operator_id` with
    `ERR_INSPECTOR_CONFLICT`."

    Design: Corner/state_machines/reassign_to_conflicted_inspector_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry()
    inspection = assign_inspection(mine, i1, kind="SPOT")
    conflicted = setup_inspector(conflicted_operator_ids=[operator["id"]])
    resp = api.reassign_inspection(
        inspection["id"], reassign_inspection_payload(conflicted["id"]), _DM
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_CONFLICT)
    after = refresh_inspection(inspection["id"])
    assert after["inspector_id"] == i1["id"], "the original assignment survives"
    assert after["status"] == "ASSIGNED"


def test_assignment_with_wrong_certification_rejected(api):
    """PRD §3.3: "The certification gate rejects an inspector whose
    `certification` does not cover the mine's `mine_type` — a
    `SURFACE`-certified inspector cannot take an underground mine, while `BOTH`
    covers either — with `ERR_INSPECTOR_NOT_CERTIFIED`."

    Design: Corner/state_machines/assignment_with_wrong_certification_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine = setup_mine(mine_type="SURFACE")
    ug_only = setup_inspector(certification="UNDERGROUND")
    resp = api.create_inspection(
        create_inspection_payload(mine["id"], ug_only["id"], kind="SPOT"),
        _DM,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED)
    inspections, meta = validate_paginated(
        api.list_inspections(_DM, params={"mine_id": mine["id"]})
    )
    assert inspections == [] and meta["total_count"] == 0


def test_err_inspector_engaged_isolated(api):
    """PRD §3.3: "the engagement gate refuses an inspector who already holds
    another `IN_PROGRESS` inspection — capacity one — with
    `ERR_INSPECTOR_ENGAGED`."

    Design: Corner/errors/err_inspector_engaged_isolated
    """
    set_clock("2026-09-10T07:00:00Z")
    operator, mine1, i1 = setup_registry(mine_overrides={"mine_name": "Canyon No 1"})
    mine2 = get_success_data(
        api.create_mine(
            create_mine_payload(
                operator["id"], mine_name="Canyon No 2", mine_type="SURFACE",
                activation_date="2026-09-01",
            ),
            _ADMIN,
        )
    )
    i1h = make_inspector_headers(i1["id"])
    insp_a = assign_inspection(
        mine1, i1, kind="SPOT",
        planned_start_at="2026-09-10T08:00:00Z",
        planned_end_at="2026-09-10T12:00:00Z",
    )
    insp_b = assign_inspection(
        mine2, i1, kind="SPOT",
        planned_start_at="2026-09-11T08:00:00Z",
        planned_end_at="2026-09-11T12:00:00Z",
    )
    get_success_data(api.file_review_inspection(insp_a["id"], i1h))
    get_success_data(api.file_review_inspection(insp_b["id"], i1h))

    # No imminent-danger order anywhere: the capacity rule fires alone.
    set_clock("2026-09-10T09:00:00Z")
    get_success_data(api.start_inspection(insp_a["id"], i1h))
    resp = api.start_inspection(insp_b["id"], i1h)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_ENGAGED)
    assert refresh_inspection(insp_b["id"])["status"] == "FILE_REVIEWED"
