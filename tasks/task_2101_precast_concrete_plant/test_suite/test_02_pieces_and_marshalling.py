"""Piece creation, the two independent status dimensions and run marshalling."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_piece,
    assert_requires_haul_permit,
    TEST_USERS,
    assign_piece,
    create_bed_run,
    create_high_performance_mix_payload,
    create_legal_piece_payload,
    create_piece,
    create_piece_payload,
    create_qualified_mix,
    read_bed_run,
    read_piece,
    read_project,
    setup_plant,
    setup_production_line,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["production_supervisor_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]


def test_new_piece_derives_permit_flag_and_starts_planned_pending(api):
    """PRD §3.2: "At creation the server derives `requires_haul_permit` from the
    dimensions alone: it is true when `width_ft` is greater than 8.50 feet, or
    `height_ft` is greater than 13.50 feet, or `length_ft` is greater than 53.00
    feet, and false otherwise."
    PRD §3.2: "A new piece begins with `production_status` `PLANNED` and
    `qc_status` `PENDING`; its `qc_hold_reason` is null, its `bed_run_id` is
    null, its `allocated_cost_cents` is null and its `repair_count` is 0."
    PRD §2.11: "`total_piece_count` counts every piece of the project in any
    status"

    Design: Corner/entities/create_piece_computes_permit_flag_and_mints_system_fields
    """
    ctx = setup_plant()

    legal = validate_success(
        api.create_piece(
            create_legal_piece_payload(ctx["project"]["id"], ctx["mix"]["id"]), SUPERVISOR
        ),
        201,
    )
    tall = validate_success(
        api.create_piece(
            create_legal_piece_payload(
                ctx["project"]["id"],
                ctx["mix"]["id"],
                piece_mark="TALL-1",
                erection_sequence_no=20,
                height_ft=13.51,
            ),
            SUPERVISOR,
        ),
        201,
    )

    assert_piece(legal)
    assert_requires_haul_permit(legal)
    assert_requires_haul_permit(tall)
    assert legal["requires_haul_permit"] is False, (
        "53.00 x 8.50 x 13.50 ft sits exactly on every limit and needs no permit"
    )
    assert tall["requires_haul_permit"] is True, "13.51 ft is above the 13.50 ft limit"
    assert legal["production_status"] == "PLANNED"
    assert legal["qc_status"] == "PENDING"
    assert legal["qc_hold_reason"] is None
    assert legal["bed_run_id"] is None
    assert legal["allocated_cost_cents"] is None
    assert legal["repair_count"] == 0
    assert legal["version"] == 1
    assert read_project(ctx["project"]["id"])["total_piece_count"] == 2


def test_piece_listing_paginates_and_filters(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; when it is
    omitted it defaults to 10, its minimum accepted value is 1 and its maximum
    accepted value is 100."
    PRD §2.3: "Pieces may be narrowed by `project_id`, by `bed_run_id`, by
    `mix_design_id`, by `replaces_piece_id`, and by either of the two
    independent piece status dimensions — `production_status` and `qc_status`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_pieces_paginates_and_filters_by_project_and_status
    """
    ctx = setup_plant()
    for index, mark in enumerate(["DT-101", "DT-102", "DT-103"]):
        create_piece(
            ctx["project"]["id"],
            ctx["mix"]["id"],
            piece_mark=mark,
            erection_sequence_no=(index + 1) * 10,
        )

    first_page, meta = validate_paginated(
        api.list_pieces(SUPERVISOR, {"project_id": ctx["project"]["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0

    second_page, meta2 = validate_paginated(
        api.list_pieces(SUPERVISOR, {"project_id": ctx["project"]["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"the tail page holds 1 row, got {len(second_page)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    cast_rows, cast_meta = validate_paginated(
        api.list_pieces(SUPERVISOR, {"production_status": "CAST"})
    )
    assert cast_rows == [], "no piece has been cast yet"
    assert cast_meta["total_count"] == 0
    assert cast_meta["has_more"] is False


def test_recast_replacement_records_and_filters_by_replaces_piece_id(api):
    """PRD §3.2: "A recast replacement additionally names the piece it supersedes
    through the optional `replaces_piece_id`, which points at another piece and
    is otherwise null."
    PRD §2.3: "Pieces may be narrowed by `project_id`, by `bed_run_id`, by
    `mix_design_id`, by `replaces_piece_id`, and by either of the two
    independent piece status dimensions — `production_status` and `qc_status`."
    PRD §3.6: "The pieces that share the cost are those on the run whose
    `production_status` is `CAST`, taken in order of `erection_sequence_no`
    ascending and, where two share a sequence number, `created_at` ascending."

    Design: Corner/entities/piece_recast_replacement_self_reference_is_queryable
    """
    ctx = setup_plant()
    original = create_piece(ctx["project"]["id"], ctx["mix"]["id"], piece_mark="DT-101")

    replacement = validate_success(
        api.create_piece(
            create_piece_payload(
                ctx["project"]["id"],
                ctx["mix"]["id"],
                piece_mark="DT-101R1",
                erection_sequence_no=10,
                replaces_piece_id=original["id"],
            ),
            SUPERVISOR,
        ),
        201,
    )

    assert replacement["replaces_piece_id"] == original["id"]
    assert read_piece(original["id"])["replaces_piece_id"] is None
    # Two pieces of one project legitimately share erection_sequence_no 10; the
    # PRD only ever ties that number, and only piece_mark is unique per project.
    assert replacement["erection_sequence_no"] == 10

    rows, meta = validate_paginated(
        api.list_pieces(SUPERVISOR, {"replaces_piece_id": original["id"]})
    )
    assert meta["total_count"] == 1, f"exactly one recast replacement, got {meta['total_count']}"
    assert [r["id"] for r in rows] == [replacement["id"]]


def test_assigning_an_already_scheduled_piece_is_rejected(api):
    """PRD §3.2: "The piece must currently be `PLANNED`, and a piece in any other
    production status is refused with `ERR_PIECE_INVALID_STATE`."
    PRD §3.2: "On success the piece's `bed_run_id` is set and the run's
    `piece_count` is recomputed as the number of pieces assigned to it whose
    `production_status` is anything other than `SCRAPPED`."

    Design: Corner/state_machines/assign_run_twice_returns_piece_invalid_state
    """
    ctx = setup_production_line(stage="scheduled")
    piece = ctx["pieces"][0]

    response = api.assign_piece_to_run(
        piece["id"], {"bed_run_id": ctx["run"]["id"]}, SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_PIECE_INVALID_STATE.value, 409)

    assert read_bed_run(ctx["run"]["id"])["piece_count"] == 1, (
        "a rejected re-assignment must not double-count the run"
    )
    assert read_piece(piece["id"])["production_status"] == "SCHEDULED"


def test_assign_run_with_a_different_mix_returns_mix_class_mismatch(api):
    """PRD §3.2: "Finally the piece's own `mix_design_id` must equal the run's
    `mix_design_id`; a mismatch is rejected with `ERR_MIX_CLASS_MISMATCH`."
    PRD §3.2: "Marshalling a piece onto a bed is the `ProductionSupervisor`'s act
    of binding it to a run, moving `production_status` from `PLANNED` to
    `SCHEDULED`."

    Design: Corner/validations/assign_run_with_mismatched_mix_returns_mix_class_mismatch
    """
    ctx = setup_plant()
    high_performance = create_qualified_mix(**create_high_performance_mix_payload())
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])
    piece = create_piece(ctx["project"]["id"], high_performance["id"], piece_mark="HP-201")

    response = api.assign_piece_to_run(piece["id"], {"bed_run_id": run["id"]}, SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_MIX_CLASS_MISMATCH.value, 409)

    reread = read_piece(piece["id"])
    assert reread["bed_run_id"] is None
    assert reread["production_status"] == "PLANNED"
    assert read_bed_run(run["id"])["piece_count"] == 0


def test_body_reference_existence_is_checked_before_piece_state(api):
    """PRD §2.8: "**Body reference existence.** Every foreign identifier supplied
    in the body resolves, or the request fails with the matching 404 code. This
    applies to the ten endpoints listed in §2.6."
    PRD §2.8: "**Primary state.** The row the request targets is in a state the
    requested transition accepts, or the request fails with that entity family's
    409 Conflict state code"

    Design: Corner/validations/body_foreign_key_existence_precedes_state_precondition
    """
    ctx = setup_production_line(stage="scheduled")
    piece = ctx["pieces"][0]

    response = api.assign_piece_to_run(
        piece["id"], {"bed_run_id": NON_EXISTENT_UUID}, SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_BED_RUN_NOT_FOUND.value, 404)

    assert read_piece(piece["id"])["bed_run_id"] == ctx["run"]["id"], (
        "the rejected re-assignment must leave the original run binding in place"
    )
