"""Endorsement lifecycle: creation constraints, duplicates, assessment, review."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assess_payload,
    create_apprentice,
    create_craftsman,
    create_endorsement,
    create_endorsement_payload,
    get_endorsement,
    make_master_craftsman_headers,
    review_endorsement,
    setup_endorsement,
    setup_endorsement_with_entries,
    setup_endorsed_track,
    validate_error,
    validate_paginated,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_create_endorsement_master_only_operation_rejected(api):
    """PRD section 3.3: "only `RIM_BENDING` and `SEASONING_CHECK` are
    apprentice-trainable, so a request for `ACTION_REGULATION` or `VOICING` fails
    with `ERR_VALIDATION`."

    Design: Corner/entities/create_endorsement_master_only_operation_rejected
    """
    apprentice = create_apprentice("Apr X")
    resp = api.create_skill_endorsement(
        create_endorsement_payload(apprentice["id"], "ACTION_REGULATION"), WM
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, meta = validate_paginated(
        api.list_skill_endorsements(WM, params={"apprentice_id": apprentice["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_duplicate_endorsement_rejected(api):
    """PRD section 3.3: "while any track for the pair is `IN_TRAINING`,
    `PENDING_ASSESSMENT`, or `ENDORSED`, a new one is refused with
    `ERR_DUPLICATE_ENDORSEMENT`".

    Design: Corner/validations/duplicate_endorsement_rejected
    """
    ctx = setup_endorsement("RIM_BENDING")
    apprentice_id = ctx["apprentice"]["id"]
    resp = api.create_skill_endorsement(
        create_endorsement_payload(apprentice_id, "RIM_BENDING"), WM
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENDORSEMENT)
    rows, meta = validate_paginated(
        api.list_skill_endorsements(WM, params={"apprentice_id": apprentice_id})
    )
    assert meta["total_count"] == 1


def test_revoked_endorsement_allows_new_track(api):
    """PRD section 3.3: "though a `REVOKED` track frees the pair for a fresh start."

    Design: Corner/validations/revoked_endorsement_allows_new_track
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    apprentice_id = ctx["apprentice"]["id"]
    revoked = review_endorsement(ctx["endorsement"]["id"], "REVOKE")
    assert revoked["status"] == "REVOKED"
    fresh = create_endorsement(apprentice_id, "RIM_BENDING")
    assert fresh["id"] != ctx["endorsement"]["id"]
    assert fresh["status"] == "IN_TRAINING"
    assert fresh["logged_hours"] == 0
    rows, meta = validate_paginated(
        api.list_skill_endorsements(WM, params={"apprentice_id": apprentice_id})
    )
    assert meta["total_count"] == 2


def test_assess_before_threshold_returns_invalid_state(api):
    """PRD section 3.3: the auto-advance fires only "When `effective_hours` reaches
    the bar for the operation — at least 600 for `RIM_BENDING`", and section 4
    scopes assess to "a `PENDING_ASSESSMENT` track", so an IN_TRAINING track cannot
    be assessed (state validity, ERR_INVALID_STATE).

    Design: Corner/state_machines/assess_before_threshold_returns_invalid_state
    """
    ctx = setup_endorsement_with_entries("RIM_BENDING", ((100, "RIM_BENDING"),))
    assessor = create_craftsman("ACTION_REGULATION", "Assessor")
    resp = api.assess_endorsement(
        ctx["endorsement"]["id"],
        assess_payload("ENDORSE"),
        make_master_craftsman_headers(assessor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["status"] == "IN_TRAINING"
    assert track["effective_hours"] == 100


def test_endorsement_revoke_retains_hours(api):
    """PRD section 3.3: "an `action` of `REVOKE` moves an `ENDORSED` track to
    `REVOKED`, retaining its `effective_hours` in storage but excluding them from
    endorsed totals".

    Design: Difficulty/non_linear_state_machine/endorsement_revoke_reopen_cycle
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    revoked = review_endorsement(ctx["endorsement"]["id"], "REVOKE")
    assert revoked["status"] == "REVOKED"
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["status"] == "REVOKED"
    assert track["effective_hours"] == 600
    assert track["logged_hours"] == 600


def test_endorsement_reopen_reinstates_endorsed(api):
    """PRD section 3.3: "an `action` of `REOPEN` reinstates a `REVOKED` track to
    `ENDORSED` with its hours intact."

    Design: Difficulty/non_linear_state_machine/endorsement_revoke_reopen_cycle
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    review_endorsement(ctx["endorsement"]["id"], "REVOKE")
    reopened = review_endorsement(ctx["endorsement"]["id"], "REOPEN")
    assert reopened["status"] == "ENDORSED"
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["effective_hours"] == 600
    assert track["logged_hours"] == 600
