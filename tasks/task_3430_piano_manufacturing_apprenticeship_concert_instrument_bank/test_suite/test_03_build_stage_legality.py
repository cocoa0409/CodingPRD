"""Build advance: stage legality, shape bounds, and priority-ordered failures."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_build_payload,
    create_apprentice,
    get_build_order,
    make_apprentice_headers,
    make_master_craftsman_headers,
    setup_build_in_stage,
    setup_commissioned_build,
    validate_error,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_advance_same_stage_rejected(api):
    """PRD section 3.2: "Asking for any target other than the legal next stage —
    skipping ahead, or repeating the current stage — is rejected with
    `ERR_BUILD_STAGE_INVALID`".

    Design: Corner/state_machines/advance_same_stage_rejected
    """
    ctx = setup_build_in_stage("MODEL_O", "RIM_BENT", {"RIM_BENT": 100})
    build = ctx["build"]
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("RIM_BENT", 10, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["RIM_BENDING"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BUILD_STAGE_INVALID)
    after = get_build_order(build["id"])
    assert after["status"] == "RIM_BENT"
    assert after["version"] == build["version"]


def test_rework_path_not_drivable_via_advance(api):
    """PRD section 3.2: "the backward move from `SEASONING` to `RIM_BENT` exists only
    as the system-driven rework path and can never be requested by a caller."

    Design: Corner/state_machines/rework_path_not_drivable_via_advance
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("RIM_BENT", 10, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["RIM_BENDING"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BUILD_STAGE_INVALID)
    after = get_build_order(build["id"])
    assert after["status"] == "SEASONING"
    assert after["wood_batch_id"] == ctx["batch"]["id"]


def test_advance_hours_over_500_rejected(api):
    """PRD section 3.2: "`hours_applied` must be greater than 0 and at most 500, else
    the request fails with `ERR_VALIDATION`."

    Design: Corner/endpoints/advance_hours_over_500_rejected
    """
    ctx = setup_build_in_stage("MODEL_O", "COMMISSIONED")
    build = ctx["build"]
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("RIM_BENT", 501, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["RIM_BENDING"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    after = get_build_order(build["id"])
    assert after["status"] == "COMMISSIONED"
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert logs == []


def test_shape_validation_beats_state_check(api):
    """PRD section 2.8: "(3) existence of path and body identifiers together with
    request shape — required fields present, types valid, enum members valid, and
    numeric ranges such as `hours_applied` greater than 0 and at most 500" precedes
    "(4) state validity"; "the server applies them in a fixed priority order and
    reports the earliest failure rather than an arbitrary one."

    Design: Corner/validations/shape_validation_beats_state_check
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("VOICING", 0, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["SEASONING_CHECK"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    after = get_build_order(build["id"])
    assert after["status"] == "SEASONING"
    assert after["version"] == build["version"]


def test_invalid_stage_beats_missing_endorsement(api):
    """PRD section 2.8: state validity is tier "(4)" while "actor endorsement" is a
    tier-"(6)" business constraint, and the server "reports the earliest failure
    rather than an arbitrary one." An endorsement-less apprentice asking for the
    illegal SEASONING -> VOICING skip must see ERR_BUILD_STAGE_INVALID.

    Design: Difficulty/priority_pair_validation_conflict/advance_invalid_stage_beats_missing_endorsement
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    apprentice = create_apprentice("Apr Three")
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("VOICING", 10, build["version"]),
        make_apprentice_headers(apprentice["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BUILD_STAGE_INVALID)
    after = get_build_order(build["id"])
    assert after["status"] == "SEASONING"
    assert after["version"] == build["version"]


def test_legal_stage_surfaces_missing_endorsement(api):
    """PRD section 3.2: "an `Apprentice` whose track is still `IN_TRAINING` or
    `PENDING_ASSESSMENT` provided the payload names a `supervising_craftsman_id`
    whose specialty matches the operation; any other actor is rejected with
    `ERR_ENDORSEMENT_REQUIRED`." Same setup as the stage-priority test but with the
    legal next stage, isolating the tier-6 actor gate on its own.

    Design: Difficulty/priority_pair_validation_conflict/advance_invalid_stage_beats_missing_endorsement
    """
    ctx = setup_build_in_stage("MODEL_B", "SEASONING", {"RIM_BENT": 100, "SEASONING": 30})
    build = ctx["build"]
    apprentice = create_apprentice("Apr Three")
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("ACTION_REGULATION", 10, build["version"]),
        make_apprentice_headers(apprentice["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_REQUIRED)
    after = get_build_order(build["id"])
    assert after["status"] == "SEASONING"
    assert after["version"] == build["version"]
