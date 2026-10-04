"""Endorsement crediting math: per-entry rounding, FAIL scaling, SoD, conserved totals."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assess_endorsement,
    assess_payload,
    create_craftsman,
    get_endorsement,
    log_supervised_hours,
    make_master_craftsman_headers,
    review_endorsement,
    setup_endorsement_with_entries,
    setup_endorsed_track,
    setup_pending_endorsement,
    validate_error,
    validate_paginated,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_mismatched_entries_credit_per_entry_rounding(api):
    """PRD section 3.3: "two 7-hour mismatched entries credit 4 plus 4 equals 8 under
    the pinned order, against 7 from rounding their 7.0 sum once."

    Design: Difficulty/combinatorial_formula/effective_hours_per_entry_rounding_mode_b
    """
    ctx = setup_endorsement_with_entries("RIM_BENDING", ((7, "VOICING"), (7, "VOICING")))
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["effective_hours"] == 8  # round_half_up(3.5) twice, then summed
    assert track["logged_hours"] == 14
    assert track["status"] == "IN_TRAINING"


def test_threshold_auto_advances_to_pending_assessment(api):
    """PRD section 3.3: "When `effective_hours` reaches the bar for the operation —
    at least 600 for `RIM_BENDING`, at least 300 for `SEASONING_CHECK`, with
    equality passing — the track auto-advances from `IN_TRAINING` to
    `PENDING_ASSESSMENT` with its `version` incremented."
    Per-entry order: 4 + 4 + 592 = 600 exactly.

    Design: Difficulty/combinatorial_formula/effective_hours_per_entry_rounding_mode_b
    """
    ctx = setup_endorsement_with_entries("RIM_BENDING", ((7, "VOICING"), (7, "VOICING")))
    cr_rim = create_craftsman("RIM_BENDING", "Rim Master")
    track = log_supervised_hours(
        ctx["endorsement"]["id"], ctx["apprentice"]["id"], 592, cr_rim["id"]
    )
    assert track["effective_hours"] == 600
    assert track["logged_hours"] == 606
    assert track["status"] == "PENDING_ASSESSMENT"


def test_assess_fail_scales_hours_per_entry_floor(api):
    """PRD section 3.3: "A `FAIL` outcome sends the track back to `IN_TRAINING` and
    scales every supervision entry's hours down to the whole-hour floor of three
    quarters of their value — a 0.75 retain ratio applied per entry, rounded down —
    after which `logged_hours` and `effective_hours` are recomputed."
    Entries 592/7/7 scale to 444/5/5; effective 444 + round(2.5) + round(2.5) = 450.

    Design: Corner/calculations/assess_fail_scales_hours_per_entry_floor
    """
    ctx = setup_endorsement_with_entries(
        "RIM_BENDING", ((7, "VOICING"), (7, "VOICING"), (592, "RIM_BENDING"))
    )
    assert ctx["endorsement"]["status"] == "PENDING_ASSESSMENT"
    assessor = create_craftsman("SEASONING_CHECK", "Sea Assessor")
    track = assess_endorsement(ctx["endorsement"]["id"], assessor, "FAIL")
    assert track["status"] == "IN_TRAINING"
    assert track["logged_hours"] == 454
    assert track["effective_hours"] == 450


def test_sod_assessor_is_top_supervisor(api):
    """PRD section 3.3: "the assessing craftsman, resolved from the caller's
    `X-User-ID`, must not be the track's top supervisor by raw `supervision_log`
    hours"; "A violating assessment is rejected with
    `ERR_SOD_ASSESSOR_IS_SUPERVISOR`, for either outcome."
    PRD section 3.3: "An `ENDORSE` outcome moves the track to `ENDORSED` and records
    the assessor as `endorsed_by_craftsman_id`".

    Design: Corner/validations/sod_assessor_is_top_supervisor
    """
    ctx = setup_pending_endorsement("RIM_BENDING")
    endorsement_id = ctx["endorsement"]["id"]
    resp = api.assess_endorsement(
        endorsement_id,
        assess_payload("ENDORSE"),
        make_master_craftsman_headers(ctx["supervisor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_ASSESSOR_IS_SUPERVISOR)
    other = create_craftsman("SEASONING_CHECK", "Sea Master")
    endorsed = assess_endorsement(endorsement_id, other, "ENDORSE")
    assert endorsed["status"] == "ENDORSED"
    assert endorsed["endorsed_by_craftsman_id"] == other["id"]


def test_revoke_excludes_hours_from_endorsed_totals(api):
    """PRD section 3.3: REVOKE is "retaining its `effective_hours` in storage but
    excluding them from endorsed totals".

    Design: Difficulty/compensating_invariant/endorsed_hours_revoke_reopen_conserved
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    apprentice_id = ctx["apprentice"]["id"]
    rows, meta = validate_paginated(
        api.list_skill_endorsements(
            WM, params={"apprentice_id": apprentice_id, "status": "ENDORSED"}
        )
    )
    assert meta["total_count"] == 1
    assert sum(row["effective_hours"] for row in rows) == 600
    review_endorsement(ctx["endorsement"]["id"], "REVOKE")
    rows, meta = validate_paginated(
        api.list_skill_endorsements(
            WM, params={"apprentice_id": apprentice_id, "status": "ENDORSED"}
        )
    )
    assert meta["total_count"] == 0 and rows == []
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["effective_hours"] == 600 and track["logged_hours"] == 600


def test_reopen_restores_endorsed_hours_total(api):
    """PRD section 3.3: "an `action` of `REOPEN` reinstates a `REVOKED` track to
    `ENDORSED` with its hours intact."

    Design: Difficulty/compensating_invariant/endorsed_hours_revoke_reopen_conserved
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    apprentice_id = ctx["apprentice"]["id"]
    review_endorsement(ctx["endorsement"]["id"], "REVOKE")
    review_endorsement(ctx["endorsement"]["id"], "REOPEN")
    rows, meta = validate_paginated(
        api.list_skill_endorsements(
            WM, params={"apprentice_id": apprentice_id, "status": "ENDORSED"}
        )
    )
    assert meta["total_count"] == 1
    assert sum(row["effective_hours"] for row in rows) == 600
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["status"] == "ENDORSED"
    assert track["effective_hours"] == 600
