"""The proctor corps: training attempts, derived certification and affidavits."""
from test_helpers import (
    ApiErrorId,
    add_proctor,
    assert_proctor,
    assert_security_affidavit,
    complete_training,
    create_security_affidavit_payload,
    create_training_completion_payload,
    make_proctor_headers,
    make_officer_headers,
    make_school_coordinator_headers,
    read_proctor,
    setup_program,
    sign_affidavit,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_training_score_exactly_at_the_pass_mark_certifies_the_proctor(api):
    """PRD §3.1: "A score of at least 80.0 percent sets `training_status` to
    `PASSED`; anything below sets it to `FAILED`. The boundary itself passes: a
    score of exactly 80.0 is a pass."
    PRD §3.1: "The submitted score always overwrites `quiz_score_pct`, whatever
    the outcome, but `training_completed_at` is stamped with the current
    logical-clock instant **only** when the attempt passes — a later failed
    attempt flips `training_status` to `FAILED` while leaving the earlier
    passing timestamp untouched."
    PRD §3.1: "If `revoked_at` is not null, `certification_status` is `REVOKED`.
    Otherwise, if `training_status` is anything other than `PASSED`, it is
    `NOT_CERTIFIED`. Otherwise, if the logical clock has reached or passed the
    instant 365 days after `training_completed_at`, it is `EXPIRED`. Otherwise
    it is `CERTIFIED`."

    Design: Difficulty/boundary_precision_check/training_quiz_score_exactly_at_threshold_passes
    """
    ctx = setup_program(district_code="NG-0011", school_code="KH-01",
                        open_the_window=False, ship_a_lot=False)
    proctor = add_proctor(ctx["school"]["id"], full_name="Ada Boundary",
                          email="ada@ng.gov")

    updated = validate_success(api.record_training_completion(
        proctor["id"], create_training_completion_payload(quiz_score_pct=80.0),
        make_school_coordinator_headers(ctx["school"]["id"])))

    assert_proctor(updated)
    assert updated["training_status"] == "PASSED", "80.0 is on the pass side"
    assert updated["quiz_score_pct"] == 80.0
    assert updated["certification_status"] == "CERTIFIED"
    assert updated["training_completed_at"] == "2026-09-01T08:00:00.000Z", (
        "a passing attempt stamps training_completed_at from the logical clock")


def test_training_score_just_below_the_pass_mark_leaves_no_completion_stamp(api):
    """PRD §3.1: "A score of at least 80.0 percent sets `training_status` to
    `PASSED`; anything below sets it to `FAILED`. The boundary itself passes: a
    score of exactly 80.0 is a pass."
    PRD §3.1: "The submitted score always overwrites `quiz_score_pct`, whatever
    the outcome, but `training_completed_at` is stamped with the current
    logical-clock instant **only** when the attempt passes — a later failed
    attempt flips `training_status` to `FAILED` while leaving the earlier
    passing timestamp untouched."

    Design: Difficulty/boundary_precision_check/training_quiz_score_exactly_at_threshold_passes
    """
    ctx = setup_program(district_code="NG-0011", school_code="KH-01",
                        open_the_window=False, ship_a_lot=False)
    proctor = add_proctor(ctx["school"]["id"], full_name="Ben Boundary",
                          email="ben@ng.gov")
    assert proctor["training_status"] == "NOT_TRAINED"
    assert proctor["certification_status"] == "NOT_CERTIFIED"
    assert proctor["strike_count"] == 0

    updated = validate_success(api.record_training_completion(
        proctor["id"], create_training_completion_payload(quiz_score_pct=79.9),
        make_school_coordinator_headers(ctx["school"]["id"])))

    assert updated["training_status"] == "FAILED", "79.9 falls below the pass mark"
    assert updated["quiz_score_pct"] == 79.9, (
        "the submitted score always overwrites quiz_score_pct")
    assert updated["certification_status"] == "NOT_CERTIFIED"
    assert updated["training_completed_at"] is None, (
        "a failed attempt must not stamp training_completed_at")


def test_resigning_the_affidavit_supersedes_the_previous_one(api):
    """PRD §3.1: "Re-signing is legitimate and expected: when a new affidavit
    lands for a proctor and window pair that already has an `ACTIVE` one, the
    older affidavit moves `ACTIVE → SUPERSEDED` and takes a `version` increment
    of its own, the proctor's `latest_affidavit_id` is repointed at the newer
    affidavit, and the proctor's `version` increments as well."
    PRD §3.1: "The server stamps `signed_at` from the logical clock and records
    the signer's `X-User-ID` as `signer_user_id`; the new affidavit is created
    with `status` `ACTIVE` and a null `revoked_reason`."

    Design: Corner/state_machines/resigning_the_affidavit_supersedes_the_previous_one
    """
    ctx = setup_program(district_code="NG-1016", school_code="CN-01",
                        open_the_window=False, ship_a_lot=False)
    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    first = sign_affidavit(proctor["id"], ctx["window"]["id"],
                           expected_proctor_version=proctor["version"])

    current = read_proctor(proctor["id"])
    second = validate_success(api.create_security_affidavit(
        create_security_affidavit_payload(proctor["id"], ctx["window"]["id"],
                                          current["version"],
                                          affidavit_version="2026.2"),
        make_proctor_headers(proctor["id"])), expected_status=201)

    assert_security_affidavit(second)
    assert second["status"] == "ACTIVE"
    assert second["affidavit_version"] == "2026.2"
    assert second["signed_at"] == "2026-09-01T08:00:00.000Z"
    assert second["signer_user_id"] == proctor["id"]
    assert second["revoked_reason"] is None

    superseded = validate_success(
        api.get_security_affidavit(first["id"], make_officer_headers()))
    assert superseded["status"] == "SUPERSEDED", (
        "the older affidavit for the same proctor and window is superseded")

    refreshed = read_proctor(proctor["id"])
    assert refreshed["latest_affidavit_id"] == second["id"]

    data, meta = validate_paginated(api.list_security_affidavits(
        make_officer_headers(),
        params={"proctor_id": proctor["id"], "window_id": ctx["window"]["id"]}))
    assert meta["total_count"] == 2, (
        "the full set for a proctor is discoverable by listing affidavits")


def test_affidavit_signed_with_a_stale_proctor_version_is_refused(api):
    """PRD §2.8: "Signing a security affidavit — the write served by
    `POST /security-affidavits` — requires `expected_proctor_version` in the
    request body, carrying the `version` of the Proctor as the client last read
    it."
    PRD §2.8: "If that value does not equal the proctor's current `version` —
    because another affidavit or a training completion has advanced it since —
    the request is rejected with `ERR_STALE_PROCTOR_VERSION` and HTTP 412."
    PRD §3.1: "Re-signing is legitimate and expected: when a new affidavit lands
    for a proctor and window pair that already has an `ACTIVE` one, the older
    affidavit moves `ACTIVE → SUPERSEDED` and takes a `version` increment of its
    own, the proctor's `latest_affidavit_id` is repointed at the newer
    affidavit, and the proctor's `version` increments as well."

    Design: Corner/cross_cutting_complexity_layers/affidavit_signed_with_stale_proctor_version_returns_412
    """
    ctx = setup_program(district_code="NG-1040", school_code="AR-01",
                        open_the_window=False, ship_a_lot=False)
    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    observed_version = proctor["version"]

    first = validate_success(api.create_security_affidavit(
        create_security_affidavit_payload(proctor["id"], ctx["window"]["id"],
                                          observed_version),
        make_proctor_headers(proctor["id"])), expected_status=201)
    assert first["status"] == "ACTIVE"

    after_first = read_proctor(proctor["id"])
    assert after_first["version"] == observed_version + 1, (
        "a successful signing increments the proctor's version by exactly one")

    replay = api.create_security_affidavit(
        create_security_affidavit_payload(proctor["id"], ctx["window"]["id"],
                                          observed_version,
                                          affidavit_version="2026.2"),
        make_proctor_headers(proctor["id"]))
    validate_error(replay, ApiErrorId.ERR_STALE_PROCTOR_VERSION.value, 412)

    still_active = validate_success(
        api.get_security_affidavit(first["id"], make_officer_headers()))
    assert still_active["status"] == "ACTIVE", (
        "the rejected replay must not supersede the standing affidavit")

    data, meta = validate_paginated(api.list_security_affidavits(
        make_officer_headers(), params={"proctor_id": proctor["id"]}))
    assert meta["total_count"] == 1
    assert read_proctor(proctor["id"])["latest_affidavit_id"] == first["id"]
