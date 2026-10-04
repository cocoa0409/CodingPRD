"""Corner queue, endpoints section: envelope contract, kind routing,
one-artifact-per-contest, cycle gate, snapshot staleness, review intake
gates, argument word boundary."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEN_WORDS,
    add_candidate_contest,
    add_filing,
    add_forum,
    add_measure_contest,
    build_confirmed_forum,
    build_measure_pipeline,
    create_measure,
    create_questionnaire,
    create_volunteer,
    fresh_league,
    get_contest,
    get_edition,
    get_measure,
    get_success_data,
    issue_questionnaire,
    make_contest_payload,
    make_coordinator_headers,
    make_cycle_payload,
    make_distribute_payload,
    make_edition_payload,
    make_answer,
    make_forum_payload,
    make_jurisdiction_payload,
    make_measure_payload,
    make_question_payload,
    make_questionnaire_payload,
    move_to_questionnaire_phase,
    report_incident,
    submit_answers,
    substantiate_incident,
    validate_error,
    validate_success,
)


def test_error_envelope_shape_on_failure_and_success_meta(api, admin_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources." and for errors "The
    `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`." with "`error_id`" and "`message`" in `data`.

    Design: Corner/endpoints/error_envelope_shape_on_failure_and_success_meta
    """
    ctx = fresh_league(api)
    created = api.create_cycle(make_cycle_payload(), admin_headers)
    body = created.json()
    assert created.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"]

    missing = api.get_contest(NON_EXISTENT_UUID, ctx["coordinator_h"])
    err = missing.json()
    assert missing.status_code == 404
    assert err["response_type"] == "error"
    assert err["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["data"]["message"], str) and err["data"]["message"]
    assert err["meta"]["api_request_id"]


def test_kind_mismatch_rejected_both_directions(api):
    """PRD §3.3: "attempting it on a ballot-measure contest is rejected with
    `ERR_CONTEST_KIND_MISMATCH`" (the questionnaire).
    PRD §3.5: "creating a measure on a candidate race with
    `ERR_CONTEST_KIND_MISMATCH`".

    Design: Corner/endpoints/kind_mismatch_rejected_both_directions
    """
    ctx = fresh_league(api)
    race = add_candidate_contest(api, ctx)
    meas_contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, race["id"])
    move_to_questionnaire_phase(api, ctx, meas_contest["id"])

    wrong_measure = api.create_measure(
        race["id"], make_measure_payload(), ctx["editor_h"]
    )
    validate_error(wrong_measure, ApiErrorId.ERR_CONTEST_KIND_MISMATCH)
    assert wrong_measure.status_code == 422

    wrong_questionnaire = api.create_questionnaire(
        meas_contest["id"], make_questionnaire_payload(), ctx["editor_h"]
    )
    validate_error(wrong_questionnaire, ApiErrorId.ERR_CONTEST_KIND_MISMATCH)
    assert wrong_questionnaire.status_code == 422


def test_duplicate_questionnaire_and_duplicate_measure_rejected(api):
    """PRD §3.3: "a `QuestionnaireEditor` creates the contest's single
    questionnaire, a second attempt meeting `ERR_DUPLICATE_QUESTIONNAIRE`".
    PRD §3.5: "a second measure on the same contest with
    `ERR_DUPLICATE_MEASURE`".

    Design: Corner/endpoints/duplicate_questionnaire_and_duplicate_measure_rejected
    """
    ctx = fresh_league(api)
    race = add_candidate_contest(api, ctx)
    meas_contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, race["id"])
    move_to_questionnaire_phase(api, ctx, meas_contest["id"])
    create_questionnaire(api, ctx, race["id"])
    create_measure(api, ctx, meas_contest["id"])

    dup_q = api.create_questionnaire(
        race["id"], make_questionnaire_payload(), ctx["editor_h"]
    )
    validate_error(dup_q, ApiErrorId.ERR_DUPLICATE_QUESTIONNAIRE)
    assert dup_q.status_code == 409

    dup_m = api.create_measure(
        meas_contest["id"],
        make_measure_payload(measure_title="M2"),
        ctx["editor_h"],
    )
    validate_error(dup_m, ApiErrorId.ERR_DUPLICATE_MEASURE)
    assert dup_m.status_code == 409


def test_contest_creation_on_draft_cycle_rejected(api, admin_headers):
    """PRD §3.2: "Within an `OPEN` cycle, a `ChapterCoordinator` creates
    contests under a jurisdiction; attempting this while the cycle is not
    `OPEN` is rejected with `ERR_CYCLE_NOT_OPEN`."

    Design: Corner/endpoints/contest_creation_on_draft_cycle_rejected
    """
    coord = create_volunteer(api, "Cara Coordinator", ["COORDINATOR"])
    cycle = get_success_data(api.create_cycle(make_cycle_payload(), admin_headers))
    # Jurisdictions may be added while the cycle is in any status (PRD
    # §3.1); the cycle stays DRAFT.
    jur = get_success_data(
        api.create_jurisdiction(cycle["id"], make_jurisdiction_payload(),
                                admin_headers),
        expected_status=201,
    )
    resp = api.create_contest(
        jur["id"], make_contest_payload(), make_coordinator_headers(coord["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)
    assert resp.status_code == 409


def test_stale_snapshot_blocks_distribute_after_incident_unlock(api):
    """PRD §3.6: "every contest id in `snapshot_contest_ids` must still be
    `LOCKED`, and every pinned questionnaire version must still equal that
    questionnaire's current `version`, otherwise the attempt is rejected
    with `ERR_STALE_SNAPSHOT` — this is the enforcement point through which
    the incident-driven contest revert of §3.8 blocks a stale print run."

    Design: Corner/endpoints/stale_snapshot_blocks_distribute_after_incident_unlock
    """
    ctx = fresh_league(api, editors=("Edna Editor", "Eli Editor"),
                       reviewers=("Rhea Reviewer", "Ray ReviewerTwo"))
    sc = build_measure_pipeline(api, ctx, approve=True, lock=True)
    edition = get_success_data(
        api.create_edition(ctx["cycle"]["id"], make_edition_payload(),
                           ctx["editor_h"]),
        expected_status=201,
    )
    ready = get_success_data(
        api.transition_edition(edition["id"], {"to": "READY"}, ctx["editor_h"])
    )
    assert ready["snapshot_contest_ids"] == [sc["contest"]["id"]]

    # The cascade reverts the snapshot contest out of LOCKED (and suspends
    # the drafter), so a second, still-active editor drives the distribute.
    incident = report_incident(api, ctx, ctx["editor"]["id"],
                               description="Drafter made an endorsement.")
    substantiate_incident(api, ctx, incident["id"])
    assert get_contest(api, ctx, sc["contest"]["id"])["status"] == "QUESTIONNAIRE_PHASE"

    second_editor_h = ctx["editors"][1][1]
    resp = api.distribute_edition(
        edition["id"], make_distribute_payload(), second_editor_h
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SNAPSHOT)
    assert resp.status_code == 422
    assert get_edition(api, ctx, edition["id"])["status"] == "READY"


def test_submit_for_review_without_con_side_rejected(api):
    """PRD §3.5: "submitting it for review requires the caller to be the
    measure's own drafter (`ERR_ONLY_DRAFTER_MAY_REVISE`) and requires at
    least one `ACCEPTED` `PRO` argument and at least one `ACCEPTED` `CON`
    argument (`ERR_MISSING_PRO_OR_CON`)."

    Design: Corner/endpoints/submit_for_review_without_con_side_rejected
    """
    ctx = fresh_league(api)
    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = create_measure(api, ctx, contest["id"])
    get_success_data(
        api.create_argument(
            measure["id"],
            {"side": "PRO", "argument_text": "one two three four five",
             "author_credit": "Yes on N"},
            ctx["editor_h"],
        ),
        expected_status=201,
    )
    resp = api.submit_measure_for_review(measure["id"], ctx["editor_h"])
    validate_error(resp, ApiErrorId.ERR_MISSING_PRO_OR_CON)
    assert resp.status_code == 422
    after = get_measure(api, ctx, measure["id"])
    assert after["status"] == "DRAFTING"
    assert after["review_round_count"] == 0


def test_argument_word_limit_boundary_250_accepted_251_rejected(api):
    """PRD §3.5: "An argument's `word_count` is computed with the `STRICT`
    policy regardless of contest settings, and the verdict is automatic at
    creation: a count of at most 250 words makes the argument `ACCEPTED`,
    while anything more makes it `REJECTED`." and "Only accepted arguments
    feed the measure's totals".

    Design: Corner/endpoints/argument_word_limit_boundary_250_accepted_251_rejected
    """
    ctx = fresh_league(api)
    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = create_measure(api, ctx, contest["id"])

    # One STRICT token per hyphen-separated part: 250 parts / 251 parts.
    text_250 = "-".join(["a"] * 250)
    text_251 = "-".join(["a"] * 251)
    accepted = get_success_data(
        api.create_argument(
            measure["id"],
            {"side": "PRO", "argument_text": text_250,
             "author_credit": "Yes on W"},
            ctx["editor_h"],
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["word_count"] == 250

    rejected = get_success_data(
        api.create_argument(
            measure["id"],
            {"side": "CON", "argument_text": text_251,
             "author_credit": "No on W"},
            ctx["editor_h"],
        ),
        expected_status=201,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["word_count"] == 251

    after = get_measure(api, ctx, measure["id"])
    assert after["pro_word_total"] == 250
    assert after["con_word_total"] == 0  # rejected arguments never count


def test_non_drafter_cannot_revise_or_submit(api):
    """PRD §3.5: "From `REMANDED` — or while still `DRAFTING` — the drafter,
    and only the drafter, revises" and "submitting it for review requires
    the caller to be the measure's own drafter
    (`ERR_ONLY_DRAFTER_MAY_REVISE`)".

    Design: Corner/endpoints/non_drafter_cannot_revise_or_submit
    """
    ctx = fresh_league(api, editors=("Ed One", "Ed Two"))
    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = create_measure(api, ctx, contest["id"])  # drafter: editors[0]

    ed2_h = ctx["editors"][1][1]
    revise = api.revise_measure(
        measure["id"],
        {"explanation_text": "Rewritten by another editor."},
        ed2_h,
    )
    validate_error(revise, ApiErrorId.ERR_ONLY_DRAFTER_MAY_REVISE)
    assert revise.status_code == 403

    submit = api.submit_measure_for_review(measure["id"], ed2_h)
    validate_error(submit, ApiErrorId.ERR_ONLY_DRAFTER_MAY_REVISE)
    assert submit.status_code == 403
    assert get_measure(api, ctx, measure["id"])["status"] == "DRAFTING"


def test_candidate_submit_to_foreign_contest_returns_not_found(api):
    """PRD §3.4: "the server identifies the shell by the questionnaire in
    the path and the caller's filing id — the shell is the join of
    `questionnaire_id` and `filing_id` — and when no such shell exists the
    request is rejected with `ERR_NOT_FOUND`, which is also what a candidate
    encounters when probing another filing's slot."

    Design: Corner/endpoints/candidate_submit_to_foreign_contest_returns_not_found
    """
    ctx = fresh_league(api)
    contest_a = add_candidate_contest(api, ctx, office_name="Mayor")
    filing_a = add_filing(api, ctx, contest_a["id"], candidate_name="Ana One",
                          filing_reference="F-A1")
    contest_b = add_candidate_contest(api, ctx, office_name="Clerk")
    move_to_questionnaire_phase(api, ctx, contest_a["id"])
    move_to_questionnaire_phase(api, ctx, contest_b["id"])
    q_a = issue_questionnaire(
        api, ctx, create_questionnaire(api, ctx, contest_a["id"])["id"]
    )
    q_b = issue_questionnaire(
        api, ctx, create_questionnaire(api, ctx, contest_b["id"])["id"]
    )

    # The candidate's filing belongs to contest A; contest B's questionnaire
    # holds no shell for it.
    resp = submit_answers(api, q_b["id"], filing_a["id"],
                          [make_answer(1, "one two three four five")])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404

    unaffected = get_success_data(
        api.get_questionnaire(q_b["id"], ctx["editor_h"])
    )
    assert unaffected["invited_count"] == 0
    assert unaffected["submitted_count"] == 0


def test_public_user_question_sourcing_rules(api, public_headers):
    """PRD §3.7: "A `PublicUser` submits a question with `question_text`
    and a `source` of `PUBLIC_SUBMISSION`, leaving `author_volunteer_id`
    null" and "each question records the `forum_id` it was submitted to and
    is born `SUBMITTED`."

    Design: Corner/endpoints/public_user_question_sourcing_rules
    """
    ctx = fresh_league(api, moderators=("Mod One",))
    contest = add_candidate_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    forum = add_forum(api, ctx, contest["id"], ctx["moderator"]["id"])

    resp = api.create_forum_question(
        forum["id"],
        make_question_payload(question_text="What is your budget priority?",
                              source="PUBLIC_SUBMISSION"),
        public_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["source"] == "PUBLIC_SUBMISSION"
    assert data["author_volunteer_id"] is None
    assert data["status"] == "SUBMITTED"
    assert data["forum_id"] == forum["id"]


def test_question_select_on_planned_forum_returns_invalid_state(api, public_headers):
    """PRD §3.7: "the assigned moderator selects or rejects questions
    (`SUBMITTED` → `SELECTED` or `SUBMITTED` → `REJECTED`, both terminal)
    only while the forum is `CONFIRMED` (`ERR_INVALID_STATE`)."

    Design: Corner/endpoints/question_select_on_planned_forum_returns_invalid_state
    """
    ctx = fresh_league(api, moderators=("Mod One",))
    contest = add_candidate_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    forum = add_forum(api, ctx, contest["id"], ctx["moderator"]["id"])
    question = get_success_data(
        api.create_forum_question(
            forum["id"],
            make_question_payload(question_text="Transit funding?"),
            public_headers,
        ),
        expected_status=201,
    )

    _mod_h = ctx["moderator_h"]
    resp = api.select_forum_question(question["id"], _mod_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    listed = get_success_data(
        api.list_forum_questions(forum["id"], _mod_h)
    )
    assert listed[0]["status"] == "SUBMITTED"


def test_moderator_without_moderator_role_tag_rejected(api):
    """PRD §3.7: "The referenced moderator must hold the `MODERATOR`
    capability (`ERR_MODERATOR_NOT_QUALIFIED`), be `ACTIVE`
    (`ERR_VOLUNTEER_SUSPENDED`), hold a `CURRENT` attestation
    (`ERR_ATTESTATION_LAPSED`), and be free of the advocacy flag
    (`ERR_ADVOCACY_SEPARATION`)."

    Design: Corner/endpoints/moderator_without_moderator_role_tag_rejected
    """
    ctx = fresh_league(api)  # editor Edna holds EDITOR, not MODERATOR
    contest = add_candidate_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    resp = api.create_forum(
        contest["id"],
        make_forum_payload(moderator_volunteer_id=ctx["editor"]["id"]),
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_MODERATOR_NOT_QUALIFIED)
    assert resp.status_code == 422


def test_sixth_question_select_rejected(api, public_headers):
    """PRD §3.7: "a forum may carry at most five `SELECTED` questions, so an
    attempt to select a sixth is rejected with `ERR_QUESTION_CAP_REACHED`."

    Design: Corner/endpoints/sixth_question_select_rejected
    """
    sc = build_confirmed_forum(api)
    forum, mod_h = sc["forum"], sc["moderator_h"]
    questions = []
    for i in range(1, 7):
        q = get_success_data(
            api.create_forum_question(
                forum["id"],
                make_question_payload(question_text=f"Question {i}?"),
                public_headers,
            ),
            expected_status=201,
        )
        questions.append(q)

    for q in questions[:5]:
        selected = get_success_data(api.select_forum_question(q["id"], mod_h))
        assert selected["status"] == "SELECTED"

    sixth = api.select_forum_question(questions[5]["id"], mod_h)
    validate_error(sixth, ApiErrorId.ERR_QUESTION_CAP_REACHED)
    assert sixth.status_code == 422

    listed = get_success_data(api.list_forum_questions(forum["id"], mod_h))
    sixth_after = [q for q in listed if q["id"] == questions[5]["id"]][0]
    assert sixth_after["status"] == "SUBMITTED"
