"""Review scores, quorums, thresholds, and the submission fork (PRD §3.2-§3.3)."""
from test_helpers import (
    ApiErrorId,
    application_transition_payload,
    assert_application,
    assert_review_score,
    close_cycle,
    create_draft_application,
    create_score_payload,
    endorse_application,
    get_application,
    make_applicant_headers,
    make_campus_reviewer_headers,
    make_national_reviewer_headers,
    post_campus_quorum_scores,
    post_national_quorum_scores,
    post_national_score,
    recommend_application,
    register_applicant,
    register_enrolled_applicant,
    setup_open_cycle,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

CAMPUS_REVIEWER_1 = "cr-1"
NATIONAL_REVIEWER_1 = "nr-1"
NATIONAL_REVIEWER_2 = "nr-2"


def test_score_post_records_system_fields_without_version(api):
    """PRD §3.3: "Each posted score records the `application_id` it belongs
    to, a `stage` derived from the application's status at posting time
    (CAMPUS while the application is in CAMPUS_REVIEW, NATIONAL while it is in
    NATIONAL_SCREENING), and the posting `reviewer_id` taken from the caller's
    `X-User-ID`."
    PRD §2.5: "One entity is exempt from this convention: a posted review
    score is immutable and carries only `id` and `created_at`; both
    `updated_at` and `version` are absent from it."
    PRD §2.6: "Screening scores and their averages are decimal numbers carried
    to exactly 2 decimal places with round-half-up rounding."

    Design: Corner/entities/score_post_records_system_fields_without_version
    """
    bundle = setup_submitted_application(applicant_type="ENROLLED_STUDENT")
    assert bundle["application"]["status"] == "CAMPUS_REVIEW"

    resp = api.post_score(
        bundle["application"]["id"],
        create_score_payload(
            feasibility_score=71, country_fit_score=66, language_score=82,
            comment="Strong feasibility",
        ),
        make_campus_reviewer_headers("cr-9"),
    )
    data = validate_success(resp, 201)
    assert_review_score(data)
    assert data["stage"] == "CAMPUS", (
        f"stage must be derived from the application state, got {data['stage']}"
    )
    assert data["reviewer_id"] == "cr-9", (
        "reviewer_id must come from the X-User-ID header, not the payload"
    )
    assert data["feasibility_score"] == 71
    assert data["application_id"] == bundle["application"]["id"]


def test_duplicate_score_from_same_reviewer_rejected(api):
    """PRD §3.3: "A reviewer may score a given application at a given stage
    only once: a second posting for the same application, stage, and reviewer
    is rejected with `ERR_DUPLICATE_SCORE`."

    Design: Corner/state_machines/duplicate_score_from_same_reviewer_rejected
    """
    bundle = setup_submitted_application()  # NATIONAL_SCREENING
    app = bundle["application"]
    post_national_score(app, NATIONAL_REVIEWER_1, score=80)

    dup = api.post_score(
        app["id"], create_score_payload(
            feasibility_score=90, country_fit_score=90, language_score=90,
        ),
        make_national_reviewer_headers(NATIONAL_REVIEWER_1),
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_SCORE)

    other = api.post_score(
        app["id"], create_score_payload(
            feasibility_score=80, country_fit_score=80, language_score=80,
        ),
        make_national_reviewer_headers(NATIONAL_REVIEWER_2),
    )
    validate_success(other, 201)


def test_campus_endorse_without_quorum_rejected(api):
    """PRD §3.3: "A campus endorsement — a CampusReviewer's DECIDE with
    `outcome` ENDORSE — requires the cycle to be in OPEN, CLOSED, or SCREENING
    (`ERR_CYCLE_PHASE_FORBIDS`) and at least two CAMPUS-stage scores on the
    application, the campus quorum (`ERR_SCORE_QUORUM_NOT_MET`); it moves the
    application CAMPUS_REVIEW → NATIONAL_SCREENING."

    Design: Corner/state_machines/campus_endorse_without_quorum_rejected
    """
    bundle = setup_submitted_application(applicant_type="ENROLLED_STUDENT")
    app = bundle["application"]
    api.post_score(
        app["id"], create_score_payload(
            feasibility_score=75, country_fit_score=75, language_score=75,
        ),
        make_campus_reviewer_headers(CAMPUS_REVIEWER_1),
    )

    resp = api.transition_application(
        app["id"], application_transition_payload("DECIDE", outcome="ENDORSE"),
        make_campus_reviewer_headers(CAMPUS_REVIEWER_1),
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_QUORUM_NOT_MET)

    assert get_application(app)["status"] == "CAMPUS_REVIEW"


def test_decide_with_outcome_foreign_to_stage_returns_invalid_outcome(api):
    """PRD §3.3: "And the `outcome` must belong to the current stage's
    vocabulary — ENDORSE or REJECT in CAMPUS_REVIEW, RECOMMEND or REJECT in
    NATIONAL_SCREENING, and SELECT, ALTERNATE, or REJECT in HOST_REVIEW —
    otherwise the request is rejected with `ERR_INVALID_OUTCOME` (400)."

    Design: Corner/state_machines/decide_with_outcome_foreign_to_stage_returns_invalid_outcome
    """
    bundle = setup_submitted_application()  # NATIONAL_SCREENING
    app = bundle["application"]

    resp = api.transition_application(
        app["id"], application_transition_payload("DECIDE", outcome="SELECT"),
        make_national_reviewer_headers(NATIONAL_REVIEWER_1),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_OUTCOME)

    assert get_application(app)["status"] == "NATIONAL_SCREENING"


def test_campus_reviewer_cannot_score_during_national_stage(
    api, program_officer_headers,
):
    """PRD §3.3: "Stage binding is strict — a `CampusReviewer` may post only
    during CAMPUS_REVIEW and a `NationalReviewer` only during
    NATIONAL_SCREENING, with violations rejected as `ERR_UNAUTHORIZED`."

    Design: Corner/validations/campus_reviewer_cannot_score_during_national_stage
    """
    bundle = setup_submitted_application()  # INDEPENDENT -> NATIONAL_SCREENING
    app = bundle["application"]

    resp = api.post_score(
        app["id"], create_score_payload(
            feasibility_score=70, country_fit_score=70, language_score=70,
        ),
        make_campus_reviewer_headers(CAMPUS_REVIEWER_1),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    rows, meta = validate_paginated(
        api.list_scores(app["id"], program_officer_headers)
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a stage-bound violation must not persist any score"
    )


def test_weighted_score_literal_computation_74_25(api, program_officer_headers):
    """PRD §3.3: "The moment the quorum-reaching national score is posted, the
    system computes and stores the application's `national_weighted_score`:
    first the mean of the `feasibility_score` values across all of the
    application's NATIONAL-stage scores, rounded half up to two decimal
    places; then, independently, the means of the `country_fit_score` and
    `language_score` values on the same rounding; then the weighted sum of
    0.40 times the feasibility average plus 0.35 times the country-fit average
    plus 0.25 times the language average, rounded half up once more to two
    decimal places."

    Scores (80,70,90) and (60,80,70) give averages (70.00, 75.00, 80.00) and
    0.40*70.00 + 0.35*75.00 + 0.25*80.00 = 74.25.

    Design: Corner/calculations/weighted_score_literal_computation_74_25
    """
    bundle = setup_submitted_application()  # NATIONAL_SCREENING
    app = bundle["application"]

    api.post_score(
        app["id"], create_score_payload(
            feasibility_score=80, country_fit_score=70, language_score=90,
        ),
        make_national_reviewer_headers(NATIONAL_REVIEWER_1),
    )
    before = get_application(app)
    assert before.get("national_weighted_score") is None, (
        "the weighted score is computed only when the quorum-reaching score lands"
    )

    api.post_score(
        app["id"], create_score_payload(
            feasibility_score=60, country_fit_score=80, language_score=70,
        ),
        make_national_reviewer_headers(NATIONAL_REVIEWER_2),
    )
    after = get_application(app)
    assert after["national_weighted_score"] is not None
    assert abs(after["national_weighted_score"] - 74.25) < 1e-9, (
        f"expected 74.25, got {after['national_weighted_score']}"
    )


def test_language_gate_proficient_blocks_recommend(api):
    """PRD §3.3: "On top of that stands the country language gate keyed on the
    program's `language_requirement`: PROFICIENT demands a language average of
    at least 80, BASIC demands at least 60, and NONE imposes no language gate
    at all (`ERR_LANGUAGE_CRITERION_UNMET`)."

    Two (80,80,75) national scores give language average 75 < 80 while the
    weighted score 78.75 clears 70.00 — the gate is conjunctive.

    Design: Corner/calculations/language_gate_proficient_blocks_recommend
    """
    bundle = setup_submitted_application(
        program_overrides={"country_code": "CN", "language_requirement": "PROFICIENT"},
    )
    app = bundle["application"]
    for reviewer in (NATIONAL_REVIEWER_1, NATIONAL_REVIEWER_2):
        resp = api.post_score(
            app["id"],
            create_score_payload(
                feasibility_score=80, country_fit_score=80, language_score=75,
            ),
            make_national_reviewer_headers(reviewer),
        )
        validate_success(resp, 201)
    close_cycle(bundle["cycle"])

    scored = get_application(app)
    assert abs(scored["national_weighted_score"] - 78.75) < 1e-9

    resp = api.transition_application(
        app["id"], application_transition_payload("DECIDE", outcome="RECOMMEND"),
        make_national_reviewer_headers(NATIONAL_REVIEWER_1),
    )
    validate_error(resp, ApiErrorId.ERR_LANGUAGE_CRITERION_UNMET)

    assert get_application(app)["status"] == "NATIONAL_SCREENING"


def test_submit_fork_enrolled_goes_to_campus_review_then_joins(api):
    """PRD §3.2: "When an ENROLLED_STUDENT submits, the application moves
    DRAFT → CAMPUS_REVIEW; when an INDEPENDENT submits, it moves DRAFT →
    NATIONAL_SCREENING."
    PRD §3.3: "A campus endorsement — a CampusReviewer's DECIDE with `outcome`
    ENDORSE — requires the cycle to be in OPEN, CLOSED, or SCREENING
    (`ERR_CYCLE_PHASE_FORBIDS`) and at least two CAMPUS-stage scores on the
    application, the campus quorum (`ERR_SCORE_QUORUM_NOT_MET`); it moves the
    application CAMPUS_REVIEW → NATIONAL_SCREENING."

    Design: Difficulty/non_linear_state_machine/application_enrolled_vs_independent_fork_join
    """
    base = setup_open_cycle(slot_quota=2)
    eli = register_enrolled_applicant()
    ingrid = register_applicant()
    app_e = create_draft_application(
        eli, base["cycle"], base["program"], project_title="Forest Pathology",
    )
    app_i = create_draft_application(
        ingrid, base["cycle"], base["program"], project_title="Urban Beekeeping",
    )

    app_e = submit_application(app_e, eli)
    app_i = submit_application(app_i, ingrid)
    assert app_e["status"] == "CAMPUS_REVIEW", (
        f"enrolled submission must fork to CAMPUS_REVIEW, got {app_e['status']}"
    )
    assert app_i["status"] == "NATIONAL_SCREENING", (
        f"independent submission must fork to NATIONAL_SCREENING, got {app_i['status']}"
    )

    post_campus_quorum_scores(app_e, score=75)
    app_e = endorse_application(app_e)
    assert app_e["status"] == "NATIONAL_SCREENING", (
        "endorsement with quorum must rejoin the shared pipeline"
    )


def test_submit_fork_both_branches_converge_at_host_review(api):
    """PRD §3.3: "A successful recommendation moves the application
    NATIONAL_SCREENING → HOST_REVIEW and assigns its `recommend_seq`: one more
    than the current maximum recommendation order among applications of the
    same country program, starting at 1 for the first recommended application
    — a per-program, strictly increasing sequence that never ties."

    Design: Difficulty/non_linear_state_machine/application_enrolled_vs_independent_fork_join
    """
    base = setup_open_cycle(slot_quota=2)
    eli = register_enrolled_applicant()
    ingrid = register_applicant()
    app_e = create_draft_application(
        eli, base["cycle"], base["program"], project_title="Forest Pathology",
    )
    app_i = create_draft_application(
        ingrid, base["cycle"], base["program"], project_title="Urban Beekeeping",
    )
    app_e = submit_application(app_e, eli)
    app_i = submit_application(app_i, ingrid)

    post_campus_quorum_scores(app_e, score=75)
    app_e = endorse_application(app_e)
    post_national_quorum_scores(app_e, score=80)
    post_national_quorum_scores(app_i, score=80)
    close_cycle(base["cycle"])

    app_e = recommend_application(app_e, reviewer_id=NATIONAL_REVIEWER_1)
    app_i = recommend_application(app_i, reviewer_id=NATIONAL_REVIEWER_2)

    assert app_e["status"] == "HOST_REVIEW", "enrolled branch must converge at HOST_REVIEW"
    assert app_i["status"] == "HOST_REVIEW", "independent branch must converge at HOST_REVIEW"
    assert app_e["recommend_seq"] == 1, (
        f"first recommendation of the program must take seq 1, got {app_e['recommend_seq']}"
    )
    assert app_i["recommend_seq"] == 2, (
        f"second recommendation must take seq 2, got {app_i['recommend_seq']}"
    )
    assert_application(app_e)
    assert_application(app_i)
