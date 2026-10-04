"""Build advance actor gate: specialty match, endorsement state, supervision."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_build_by_apprentice,
    advance_build_payload,
    assert_build_stage_log,
    condition_wood_batch,
    create_apprentice,
    create_build_order,
    create_craftsman,
    create_endorsement,
    get_build_order,
    get_endorsement,
    log_supervised_hours,
    make_apprentice_headers,
    make_master_craftsman_headers,
    setup_endorsement,
    setup_endorsed_track,
    validate_error,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_apprentice_supervised_advance_credits_endorsement(api):
    """PRD section 3.2: "When the advancing caller is an apprentice, the same hours
    are additionally credited to their matching endorsement track as a supervision
    entry, recomputing its credited totals per section 3.3."
    PRD section 3.2: stage log records "the `supervising_craftsman_id` when the
    advance was supervised".

    Design: Corner/endpoints/apprentice_supervised_advance_credits_endorsement
    """
    batch = condition_wood_batch()
    cr_rim = create_craftsman("RIM_BENDING", "Rim Master")
    apprentice = create_apprentice("Apr L")
    endorsement = create_endorsement(apprentice["id"], "RIM_BENDING")
    log_supervised_hours(endorsement["id"], apprentice["id"], 10, cr_rim["id"])
    build = create_build_order("MODEL_O", batch["id"])
    advanced = advance_build_by_apprentice(
        build, "RIM_BENT", 120, apprentice, supervising_craftsman_id=cr_rim["id"]
    )
    assert advanced["status"] == "RIM_BENT"
    track = get_endorsement(endorsement["id"])
    assert track["logged_hours"] == 130
    assert track["effective_hours"] == 130  # 120h credited at the 1.0 matched ratio
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert len(logs) == 1
    assert_build_stage_log(logs[0])
    assert logs[0]["actor_role"] == "Apprentice"
    assert logs[0]["supervising_craftsman_id"] == cr_rim["id"]
    assert logs[0]["operation_type"] == "RIM_BENDING"


def test_apprentice_endorsed_advances_unsupervised(api):
    """PRD section 3.2: the actor gate accepts "an `Apprentice` holding an `ENDORSED`
    track for the operation working unsupervised".
    PRD section 3.3: "The supervisor id may be null for endorsed unsupervised work,
    and such entries always carry `specialty_match` true".

    Design: Corner/endpoints/apprentice_endorsed_advances_unsupervised
    """
    ctx = setup_endorsed_track("RIM_BENDING")
    batch = condition_wood_batch()
    build = create_build_order("MODEL_O", batch["id"])
    advanced = advance_build_by_apprentice(build, "RIM_BENT", 120, ctx["apprentice"])
    assert advanced["status"] == "RIM_BENT"
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert len(logs) == 1
    assert logs[0]["supervising_craftsman_id"] is None
    track = get_endorsement(ctx["endorsement"]["id"])
    assert track["logged_hours"] == 720  # endorsed unsupervised work still credits


def test_apprentice_in_training_unsupervised_rejected(api):
    """PRD section 3.2: an "`Apprentice` whose track is still `IN_TRAINING` or
    `PENDING_ASSESSMENT`" needs "a `supervising_craftsman_id` whose specialty matches
    the operation; any other actor is rejected with `ERR_ENDORSEMENT_REQUIRED`."

    Design: Corner/endpoints/apprentice_in_training_unsupervised_rejected
    """
    ctx = setup_endorsement("RIM_BENDING")
    batch = condition_wood_batch()
    build = create_build_order("MODEL_O", batch["id"])
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("RIM_BENT", 50, build["version"]),
        make_apprentice_headers(ctx["apprentice"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_REQUIRED)
    after = get_build_order(build["id"])
    assert after["status"] == "COMMISSIONED"
    assert after["version"] == build["version"]
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert logs == []


def test_craftsman_wrong_specialty_rejected(api):
    """PRD section 3.2: "the actor gate accepts a `MasterCraftsman` whose `specialty`
    matches the operation ... any other actor is rejected with
    `ERR_ENDORSEMENT_REQUIRED`."

    Design: Corner/endpoints/craftsman_wrong_specialty_rejected
    """
    cr_voi = create_craftsman("VOICING", "Voi Master")
    batch = condition_wood_batch()
    build = create_build_order("MODEL_O", batch["id"])
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("RIM_BENT", 100, build["version"]),
        make_master_craftsman_headers(cr_voi["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_REQUIRED)
    after = get_build_order(build["id"])
    assert after["status"] == "COMMISSIONED"
    assert after["version"] == build["version"]
