"""Nonconformance reports, the repair rework loop and the recast scrap cascade."""

from test_helpers import (
    ApiErrorId,
    PRODUCTION_SUPERVISOR_USER,
    QUALITY_ENGINEER_USER,
    TEST_USERS,
    assert_piece_dimensions_status,
    assert_project_counters,
    assert_repair_disposition,
    assert_slot_occupancy,
    create_repair_disposition_payload,
    decide_disposition,
    list_piece_repair_dispositions,
    make_production_supervisor_headers,
    open_ncr,
    read_piece,
    read_project,
    read_repair_disposition,
    read_yard_placement,
    read_yard_slot,
    setup_dispositioned_ncr,
    setup_ncr_in_reinspection,
    setup_piece_with_open_ncr,
    start_repair,
    submit_reinspection,
    validate_error,
    validate_paginated,
    validate_success,
)

QC = TEST_USERS["qc_technician_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]


def test_opening_a_report_moves_only_the_quality_dimension(api):
    """PRD §3.9: "The piece moves to `qc_status` `NONCONFORMING` with
    `qc_hold_reason` set to `OPEN_NCR`, and its `version` increments by 1."
    PRD §3.2: "The two piece status dimensions run independently of one another
    for the whole life of the piece, and neither one is derived from the other."
    PRD §3.9: "The report is written with `status` `OPEN`, its `disposition`
    null, its `reinspection_fail_count` 0, its `opened_by_user_id` taken from the
    acting `X-User-ID`, and its `dispositioned_by_user_id` and
    `repaired_by_user_id` both null."

    Design: Difficulty/non_linear_state_machine/piece_production_and_qc_dimensions_advance_independently
    """
    ctx = setup_piece_with_open_ncr(
        stage="yarded",
        ncr_overrides={
            "defect_type": "SPALL",
            "severity": "MINOR",
            "description": "Edge spall at south bearing",
        },
    )

    assert_repair_disposition(ctx["ncr"])
    assert ctx["ncr"]["status"] == "OPEN"
    assert ctx["ncr"]["disposition"] is None
    assert ctx["ncr"]["reinspection_fail_count"] == 0
    assert_piece_dimensions_status(
        read_piece(ctx["pieces"][0]["id"]), "YARDED", "NONCONFORMING", "OPEN_NCR"
    )


def test_opening_a_report_leaves_the_yard_placement_and_slot_untouched(api):
    """PRD §3.9: "The owning project also recomputes `cleared_piece_count`, since
    a piece that was `CLEARED` or `REPAIRED` no longer counts as cleared once it
    is nonconforming."
    PRD §3.7: "The slot is then recomputed from its active placements alone:
    `occupied_weight_lb` becomes the exact sum of `weight_lb` over the pieces of
    the slot's `ACTIVE` placements, with no rounding whatsoever; `stacked_count`
    becomes the number of those active placements"

    Design: Difficulty/non_linear_state_machine/piece_production_and_qc_dimensions_advance_independently
    """
    ctx = setup_piece_with_open_ncr(stage="yarded")
    piece = ctx["pieces"][0]
    placement = ctx["placements"][0]

    assert read_yard_placement(piece["id"], placement["id"])["status"] == "ACTIVE"
    assert_slot_occupancy(read_yard_slot(ctx["slot"]["id"]), 48200, 1, "PARTIAL")
    assert_project_counters(
        read_project(ctx["project"]["id"]), cleared_piece_count=0, held_piece_count=0
    )


def test_repair_loop_closes_after_one_failed_reinspection(api):
    """PRD §3.9: "A `FAIL` increments `reinspection_fail_count` by 1. The plant
    tolerates a limited number of failed reinspections: while the incremented
    `reinspection_fail_count` remains below the limit of 2, the report returns
    `REINSPECTION → REPAIR_IN_PROGRESS` for another attempt, which makes
    `REPAIR_IN_PROGRESS → REINSPECTION → REPAIR_IN_PROGRESS` the repair rework
    loop."
    PRD §3.9: "A `PASS` moves the report `REINSPECTION → CLOSED_ACCEPTED`, moves
    the piece `qc_status` `NONCONFORMING → REPAIRED` with `qc_hold_reason`
    cleared to null, recomputes the piece's `repair_count` and recomputes the
    owning project's `cleared_piece_count`."

    Design: Difficulty/non_linear_state_machine/repair_disposition_reinspection_loop_closes_on_second_pass
    """
    ctx = setup_ncr_in_reinspection(
        stage="yarded",
        ncr_overrides={
            "defect_type": "HONEYCOMB",
            "severity": "MAJOR",
            "description": "Honeycombing on the stem face",
        },
    )
    ncr_id = ctx["ncr"]["id"]

    failed = validate_success(api.reinspect(ncr_id, {"result": "FAIL"}, ENGINEER))
    assert failed["status"] == "REPAIR_IN_PROGRESS"
    assert failed["reinspection_fail_count"] == 1

    submit_reinspection(ncr_id)
    passed = validate_success(api.reinspect(ncr_id, {"result": "PASS"}, ENGINEER))

    assert passed["status"] == "CLOSED_ACCEPTED"
    assert passed["reinspection_fail_count"] == 1


def test_closed_report_records_both_signatures_and_repairs_the_piece(api):
    """PRD §3.9: "In every branch the acting `X-User-ID` is written to
    `dispositioned_by_user_id`."
    PRD §3.9: "A `ProductionSupervisor` **starts the repair**, moving the report
    `DISPOSITIONED → REPAIR_IN_PROGRESS` and writing the acting `X-User-ID` to
    `repaired_by_user_id`"
    PRD §3.9: "A piece's `repair_count` is the number of reports raised against it
    whose `status` is either `CLOSED_ACCEPTED` or `REJECTED_RECAST`."

    Design: Difficulty/non_linear_state_machine/repair_disposition_reinspection_loop_closes_on_second_pass
    """
    ctx = setup_ncr_in_reinspection(
        stage="yarded",
        ncr_overrides={
            "defect_type": "HONEYCOMB",
            "severity": "MAJOR",
            "description": "Honeycombing on the stem face",
        },
    )
    ncr_id = ctx["ncr"]["id"]
    piece_id = ctx["pieces"][0]["id"]

    validate_success(api.reinspect(ncr_id, {"result": "FAIL"}, ENGINEER))
    submit_reinspection(ncr_id)
    validate_success(api.reinspect(ncr_id, {"result": "PASS"}, ENGINEER))

    report = read_repair_disposition(piece_id, ncr_id)
    assert report["disposition"] == "STRUCTURAL_REPAIR"
    assert report["dispositioned_by_user_id"] == QUALITY_ENGINEER_USER
    assert report["repaired_by_user_id"] == PRODUCTION_SUPERVISOR_USER

    assert_piece_dimensions_status(read_piece(piece_id), "YARDED", "REPAIRED", None)
    assert read_piece(piece_id)["repair_count"] == 1
    assert_project_counters(read_project(ctx["project"]["id"]), cleared_piece_count=1)


def test_reject_recast_scraps_the_piece_and_empties_the_slot(api):
    """PRD §3.9: "A `disposition` of `REJECT_RECAST` condemns the piece and moves
    the report `OPEN → REJECTED_RECAST` through a four-hop cascade. In the first
    hop the `disposition` and `dispositioned_by_user_id` are written. In the
    second hop, caused by the first, the piece moves `qc_status` to `REJECTED`
    and `production_status` to `SCRAPPED` — reachable from `PLANNED`,
    `SCHEDULED`, `CAST`, `STRIPPED` or `YARDED`. In the third hop, caused by the
    second, any `ACTIVE` yard placement of that piece moves `ACTIVE → RELEASED`
    with `release_reason` `SCRAP`, and its yard slot decrements
    `occupied_weight_lb` by the piece's `weight_lb`, decrements `stacked_count`
    by 1 and recomputes its `status`."

    Design: Difficulty/transitive_cascade/reject_recast_cascade_piece_to_placement_to_slot_to_project
    """
    ctx = setup_piece_with_open_ncr(
        stage="yarded",
        ncr_overrides={
            "defect_type": "CRACK",
            "severity": "STRUCTURAL",
            "description": "Full-depth crack through the stem",
        },
    )
    piece_id = ctx["pieces"][0]["id"]
    placement_id = ctx["placements"][0]["id"]

    condemned = validate_success(
        api.decide_disposition(ctx["ncr"]["id"], {"disposition": "REJECT_RECAST"}, ENGINEER)
    )

    assert condemned["status"] == "REJECTED_RECAST"
    assert condemned["disposition"] == "REJECT_RECAST"
    assert_piece_dimensions_status(read_piece(piece_id), "SCRAPPED", "REJECTED", None)

    placement = read_yard_placement(piece_id, placement_id)
    assert placement["status"] == "RELEASED"
    assert placement["release_reason"] == "SCRAP"
    assert placement["released_at"].startswith("2026-08-03T06:00:00")
    assert_slot_occupancy(read_yard_slot(ctx["slot"]["id"]), 0, 0, "EMPTY")


def test_reject_recast_recomputes_the_project_counters(api):
    """PRD §3.9: "In the fourth hop, caused by the third, the owning project
    recomputes both `scrapped_piece_count` and `cleared_piece_count`."
    PRD §2.11: "`scrapped_piece_count` counts the project's pieces whose
    `production_status` is `SCRAPPED`"
    PRD §2.11: "`total_piece_count` counts every piece of the project in any
    status"

    Design: Difficulty/transitive_cascade/reject_recast_cascade_piece_to_placement_to_slot_to_project
    """
    ctx = setup_piece_with_open_ncr(
        stage="yarded",
        ncr_overrides={
            "defect_type": "CRACK",
            "severity": "STRUCTURAL",
            "description": "Full-depth crack through the stem",
        },
    )

    validate_success(
        api.decide_disposition(ctx["ncr"]["id"], {"disposition": "REJECT_RECAST"}, ENGINEER)
    )

    assert_project_counters(
        read_project(ctx["project"]["id"]),
        scrapped_piece_count=1,
        cleared_piece_count=0,
        total_piece_count=1,
    )


def test_disposition_actions_follow_the_declared_order(api):
    """PRD §3.9: "a start issued from any other status is refused with
    `ERR_DISPOSITION_INVALID_STATE`"
    PRD §2.8: "**Primary state.** The row the request targets is in a state the
    requested transition accepts, or the request fails with that entity family's
    409 Conflict state code"
    PRD §3.9: "Opening a report on a piece that is already `NONCONFORMING` is a
    legitimate self-loop that leaves the piece `NONCONFORMING` and supersedes the
    earlier paperwork: every earlier report on the same piece whose `status` is
    `OPEN`, `DISPOSITIONED`, `REPAIR_IN_PROGRESS` or `REINSPECTION` moves to
    `SUPERSEDED`."
    PRD §3.9: "A `disposition` of `USE_AS_IS` closes the report immediately,
    moving it `OPEN → CLOSED_ACCEPTED`. The piece moves `qc_status`
    `NONCONFORMING → REPAIRED` with `qc_hold_reason` cleared to null, its
    `repair_count` is recomputed, and the owning project recomputes
    `cleared_piece_count`."

    Design: Corner/state_machines/repair_disposition_action_order_is_enforced
    """
    ctx = setup_piece_with_open_ncr(
        ncr_overrides={
            "defect_type": "DIMENSIONAL",
            "severity": "MINOR",
            "description": "Bearing plate 6 mm out of position",
        }
    )
    piece_id = ctx["pieces"][0]["id"]
    first_ncr = ctx["ncr"]["id"]

    validate_error(
        api.start_repair(first_ncr, SUPERVISOR),
        ApiErrorId.ERR_DISPOSITION_INVALID_STATE.value,
        409,
    )

    decide_disposition(first_ncr, "PATCH_MINOR")
    validate_error(
        api.submit_reinspection(first_ncr, SUPERVISOR),
        ApiErrorId.ERR_DISPOSITION_INVALID_STATE.value,
        409,
    )

    before = read_repair_disposition(piece_id, first_ncr)
    assert before["status"] == "DISPOSITIONED"
    assert before["disposition"] == "PATCH_MINOR"
    assert before["repaired_by_user_id"] is None

    second_ncr = open_ncr(
        piece_id,
        defect_type="FINISH",
        severity="MINOR",
        description="Superseding report after re-inspection of the same defect",
    )
    assert read_repair_disposition(piece_id, first_ncr)["status"] == "SUPERSEDED"

    closed = decide_disposition(second_ncr["id"], "USE_AS_IS")
    assert closed["status"] == "CLOSED_ACCEPTED"
    assert closed["disposition"] == "USE_AS_IS"

    piece = read_piece(piece_id)
    assert_piece_dimensions_status(piece, "PLANNED", "REPAIRED", None)
    assert piece["repair_count"] == 1
    assert_project_counters(read_project(ctx["project"]["id"]), cleared_piece_count=1)


def test_the_disposition_signer_may_not_start_the_repair(api):
    """PRD §2.10: "The second governs repair work. The `X-User-ID` of the
    `ProductionSupervisor` starting a repair must differ from the
    `dispositioned_by_user_id` written when the `QualityEngineer` decided the
    disposition."
    PRD §3.9: "and a start whose `X-User-ID` equals the report's
    `dispositioned_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, as
    §2.10 requires."

    Design: Corner/state_machines/start_repair_by_the_disposition_signer_returns_segregation_of_duties
    """
    ctx = setup_dispositioned_ncr(
        disposition="STRUCTURAL_REPAIR",
        ncr_overrides={
            "defect_type": "SPALL",
            "severity": "MAJOR",
            "description": "Corner spall at the lifting insert",
        },
    )
    ncr_id = ctx["ncr"]["id"]
    piece_id = ctx["pieces"][0]["id"]

    conflicted = api.start_repair(
        ncr_id, make_production_supervisor_headers(QUALITY_ENGINEER_USER)
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    blocked = read_repair_disposition(piece_id, ncr_id)
    assert blocked["status"] == "DISPOSITIONED"
    assert blocked["repaired_by_user_id"] is None

    started = validate_success(api.start_repair(ncr_id, SUPERVISOR))
    assert started["status"] == "REPAIR_IN_PROGRESS"
    assert started["repaired_by_user_id"] == PRODUCTION_SUPERVISOR_USER
    assert started["dispositioned_by_user_id"] == QUALITY_ENGINEER_USER


def test_second_reinspection_failure_forces_reject_recast(api):
    """PRD §3.9: "When the increment would bring `reinspection_fail_count` to
    exactly 2, patience is exhausted: the report moves `REINSPECTION →
    REJECTED_RECAST` with `reinspection_fail_count` at 2, and exactly the same
    four-hop scrap cascade described for a `REJECT_RECAST` disposition fires — the
    piece to `REJECTED` and `SCRAPPED`, its `ACTIVE` placement released with
    `release_reason` `SCRAP`, its slot decremented and recomputed, and its
    project's `scrapped_piece_count` and `cleared_piece_count` recomputed."
    PRD §3.9: "A piece's `repair_count` is the number of reports raised against it
    whose `status` is either `CLOSED_ACCEPTED` or `REJECTED_RECAST`."

    Design: Corner/state_machines/second_reinspection_failure_forces_reject_recast
    """
    ctx = setup_ncr_in_reinspection(
        ncr_overrides={
            "defect_type": "HONEYCOMB",
            "severity": "MAJOR",
            "description": "Voids along the bottom flange",
        }
    )
    ncr_id = ctx["ncr"]["id"]
    piece_id = ctx["pieces"][0]["id"]

    first_fail = validate_success(api.reinspect(ncr_id, {"result": "FAIL"}, ENGINEER))
    assert first_fail["status"] == "REPAIR_IN_PROGRESS"
    assert first_fail["reinspection_fail_count"] == 1

    submit_reinspection(ncr_id)
    second_fail = validate_success(api.reinspect(ncr_id, {"result": "FAIL"}, ENGINEER))

    assert second_fail["status"] == "REJECTED_RECAST"
    assert second_fail["reinspection_fail_count"] == 2
    assert_piece_dimensions_status(read_piece(piece_id), "SCRAPPED", "REJECTED", None)
    assert read_piece(piece_id)["repair_count"] == 1
    assert_project_counters(read_project(ctx["project"]["id"]), scrapped_piece_count=1)

    _, meta = validate_paginated(api.list_piece_yard_placements(piece_id, SUPERVISOR))
    assert meta["total_count"] == 0, "the piece was never yarded, so no placement cascade fires"


def test_stale_piece_version_rejects_the_second_report(api):
    """PRD §2.9: "A `POST /repair-dispositions` request must carry
    `expected_piece_version`, a required field, holding the client's last
    observed `version` of the `Piece` named by `piece_id`."
    PRD §2.9: "If `expected_piece_version` does not equal the piece's current
    `version`, the request is rejected with `ERR_STALE_PIECE_VERSION` and HTTP
    412 Precondition Failed. On success the operation increments the piece's
    `version` by 1, so a client that replays the same expected value a second
    time is refused."

    Design: Corner/cross_cutting_layers/stale_piece_version_rejects_a_second_nonconformance_report
    """
    ctx = setup_piece_with_open_ncr(
        ncr_overrides={
            "defect_type": "SPALL",
            "severity": "MINOR",
            "description": "First report",
        }
    )
    piece_id = ctx["pieces"][0]["id"]
    first_ncr = ctx["ncr"]["id"]
    stale_version = read_piece(piece_id)["version"] - 1

    stale = api.create_repair_disposition(
        create_repair_disposition_payload(
            piece_id,
            stale_version,
            defect_type="FINISH",
            description="Second report with a stale view",
        ),
        QC,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PIECE_VERSION.value, 412)

    fresh_version = read_piece(piece_id)["version"]
    assert fresh_version == stale_version + 1, (
        "creating the first report incremented the piece version by exactly 1"
    )

    second_ncr = validate_success(
        api.create_repair_disposition(
            create_repair_disposition_payload(
                piece_id,
                fresh_version,
                defect_type="FINISH",
                description="Second report with a fresh view",
            ),
            QC,
        ),
        201,
    )

    assert read_repair_disposition(piece_id, first_ncr)["status"] == "SUPERSEDED"
    assert read_repair_disposition(piece_id, second_ncr["id"])["status"] == "OPEN"
    assert len(list_piece_repair_dispositions(piece_id)) == 2
    assert_piece_dimensions_status(read_piece(piece_id), "PLANNED", "NONCONFORMING", "OPEN_NCR")
