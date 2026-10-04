"""Corner queue, validations section: auth, RBAC ordering, SoD, advocacy,
per-round review guard, OCC stale versions, isolated temporal failure,
suspension enforcement."""
from test_helpers import (
    ApiErrorId,
    FIVE_WORDS,
    NON_EXISTENT_UUID,
    PAST_DUE_AT,
    TEN_WORDS,
    add_candidate_contest,
    add_measure_contest,
    build_confirmed_forum,
    build_issued_scenario,
    build_measure_pipeline,
    contest_version,
    create_questionnaire,
    create_volunteer,
    fresh_league,
    get_measure,
    get_questionnaire,
    get_shell,
    get_success_data,
    make_answer,
    make_contest_payload,
    make_cycle_payload,
    make_measure_payload,
    make_moderator_headers,
    make_question_payload,
    make_reviewer_headers,
    make_editor_headers,
    move_to_questionnaire_phase,
    report_incident,
    set_clock,
    submit_answers,
    substantiate_incident,
    validate_error,
    validate_success,
)


def test_reviewer_cannot_create_contest_returns_unauthorized_role(api):
    """PRD §2.7: "Authentication comes first (`ERR_UNAUTHENTICATED`), then
    authorization and ownership denials (`ERR_UNAUTHORIZED_ROLE`)".
    PRD §2.7: "Only then are path identifiers resolved, strictly left to
    right, with the first unresolvable id producing `ERR_NOT_FOUND`" — so
    the role denial fires even when the jurisdiction id in the path does not
    exist.

    Design: Corner/validations/reviewer_cannot_create_contest_returns_unauthorized_role
    """
    reviewer = create_volunteer(api, "Rhea Reviewer", ["REVIEWER"],
                                chapter_code="CH2")
    resp = api.create_contest(
        NON_EXISTENT_UUID,
        make_contest_payload(),
        make_reviewer_headers(reviewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "Authentication failures — a missing or unrecognized
    `X-User-Role`, a missing `X-User-ID` for any role other than
    `PublicUser`, or an entity-backed `X-User-ID` that does not reference a
    live record of the role's backing type carrying the required capability
    tag — are rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    resp = api.create_cycle(make_cycle_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_drafter_cannot_review_own_measure(api):
    """PRD §3.5: "The reviewer must not be the measure's drafter
    (`ERR_SOD_DRAFTER_CANNOT_REVIEW`)".  The check compares identities, so
    holding both capability tags does not help.

    Design: Corner/validations/drafter_cannot_review_own_measure
    """
    ctx = fresh_league(api, editors=(), reviewers=("Rhea Reviewer",))
    dual = create_volunteer(api, "Dual Hat", ["EDITOR", "REVIEWER"])
    dual_edit_h = make_editor_headers(dual["id"])
    dual_rev_h = make_reviewer_headers(dual["id"])

    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = get_success_data(
        api.create_measure(contest["id"], make_measure_payload(), dual_edit_h),
        expected_status=201,
    )
    for side in ("PRO", "CON"):
        get_success_data(
            api.create_argument(
                measure["id"],
                {"side": side, "argument_text": TEN_WORDS,
                 "author_credit": f"{side} committee"},
                dual_edit_h,
            ),
            expected_status=201,
        )
    get_success_data(api.submit_measure_for_review(measure["id"], dual_edit_h))

    resp = api.create_review(
        measure["id"],
        {"verdict": "NEUTRAL", "notes": "Reviewing my own draft."},
        dual_rev_h,
    )
    validate_error(resp, ApiErrorId.ERR_SOD_DRAFTER_CANNOT_REVIEW)
    assert resp.status_code == 403
    after = get_success_data(api.get_measure(measure["id"], dual_edit_h))
    assert after["status"] == "IN_NEUTRALITY_REVIEW"
    assert after["approvals_this_round"] == 0


def test_moderator_cannot_select_own_authored_question(api):
    """PRD §3.7: "a moderator may never select a `MODERATOR_AUTHORED`
    question they authored themselves (`ERR_SOD_MODERATOR_OWN_QUESTION`)".

    Design: Corner/validations/moderator_cannot_select_own_authored_question
    """
    sc = build_confirmed_forum(api)
    forum, mod_h = sc["forum"], sc["moderator_h"]

    own = get_success_data(
        api.create_forum_question(
            forum["id"],
            make_question_payload(question_text="What is your housing plan?",
                                  source="MODERATOR_AUTHORED"),
            mod_h,
        ),
        expected_status=201,
    )
    public = get_success_data(
        api.create_forum_question(
            forum["id"],
            make_question_payload(question_text="How will you fund transit?",
                                  source="PUBLIC_SUBMISSION"),
            sc["ctx"]["public_h"],
        ),
        expected_status=201,
    )

    blocked = api.select_forum_question(own["id"], mod_h)
    validate_error(blocked, ApiErrorId.ERR_SOD_MODERATOR_OWN_QUESTION)
    assert blocked.status_code == 403

    selected = get_success_data(api.select_forum_question(public["id"], mod_h))
    assert selected["status"] == "SELECTED"


def test_advocacy_flagged_reviewer_rejected(api):
    """PRD §2.10: "A volunteer whose `advocacy_flag` is set may not be
    assigned as a measure drafter, a neutrality reviewer, or a forum
    moderator — voter-education work is kept separate from advocacy
    positions, and any such assignment is rejected with
    `ERR_ADVOCACY_SEPARATION`."

    Design: Corner/validations/advocacy_flagged_reviewer_rejected
    """
    sc = build_measure_pipeline(api, submit=True)
    ctx, measure = sc["ctx"], sc["measure"]
    reviewer = ctx["reviewers"][0][0]

    get_success_data(
        api.flag_advocacy(reviewer["id"], {"advocacy_flag": True},
                          ctx["admin_h"])
    )
    resp = api.create_review(
        measure["id"],
        {"verdict": "NEUTRAL", "notes": "Looks fine."},
        ctx["reviewers"][0][1],
    )
    validate_error(resp, ApiErrorId.ERR_ADVOCACY_SEPARATION)
    assert resp.status_code == 403
    assert get_measure(api, ctx, measure["id"])["approvals_this_round"] == 0


def test_duplicate_review_same_round_rejected(api):
    """PRD §3.5: "may review a given measure at most once per round
    (`ERR_DUPLICATE_REVIEW_THIS_ROUND`)" and "approval requires two distinct
    reviewers in the same round, and a lone approval leaves the measure in
    `IN_NEUTRALITY_REVIEW`."

    Design: Corner/validations/duplicate_review_same_round_rejected_then_allowed_next_round
    """
    sc = build_measure_pipeline(api, submit=True)
    ctx, measure = sc["ctx"], sc["measure"]
    mid = measure["id"]

    first = get_success_data(
        api.create_review(
            mid, {"verdict": "NEUTRAL", "notes": "First approval."},
            ctx["reviewers"][0][1],
        ),
        expected_status=201,
    )
    assert first["round_index"] == 1
    # One distinct approval is not enough.
    assert get_measure(api, ctx, mid)["status"] == "IN_NEUTRALITY_REVIEW"

    dup = api.create_review(
        mid, {"verdict": "NEUTRAL", "notes": "Me again."},
        ctx["reviewers"][0][1],
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_REVIEW_THIS_ROUND)
    assert dup.status_code == 409

    second = get_success_data(
        api.create_review(
            mid, {"verdict": "NEUTRAL", "notes": "Second distinct approval."},
            ctx["reviewers"][1][1],
        ),
        expected_status=201,
    )
    assert second["round_index"] == 1
    assert get_measure(api, ctx, mid)["status"] == "APPROVED_FOR_GUIDE"


def test_stale_contest_version_returns_412(api):
    """PRD §2.6: "when `expected_contest_version` no longer matches the
    current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and the caller must re-read the contest before retrying."

    Design: Corner/validations/stale_contest_version_returns_412
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    set_clock(api, "2026-09-16T00:00:00Z")
    version = contest_version(api, ctx, contest["id"])

    ok = get_success_data(
        api.transition_contest(
            contest["id"],
            {"to": "QUESTIONNAIRE_PHASE", "expected_contest_version": version},
            ctx["coordinator_h"],
        )
    )
    assert ok["version"] == version + 1

    stale = api.transition_contest(
        contest["id"],
        {"to": "GUIDE_READY", "expected_contest_version": version},
        ctx["coordinator_h"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412


def test_stale_questionnaire_version_returns_412(api):
    """PRD §2.6: "A questionnaire amendment must likewise carry
    `expected_questionnaire_version` equal to the questionnaire's current
    `version`. Issuing a questionnaire, every candidate submission against
    it, and every successful amendment advance the questionnaire's
    `version`; a stale amendment is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/validations/stale_questionnaire_version_returns_412
    """
    sc = build_issued_scenario(api, filings=())
    ctx = sc["ctx"]
    q = sc["questionnaire"]
    # Build a second DRAFT questionnaire is impossible (one per contest), so
    # exercise the OCC pair on the ISSUED one: amend is allowed in ISSUED.
    version = q["version"]

    first = get_success_data(
        api.amend_questionnaire(
            q["id"],
            {"expected_questionnaire_version": version,
             "due_at": "2026-10-05T17:00:00Z"},
            ctx["editor_h"],
        )
    )
    assert first["due_at"].startswith("2026-10-05")

    stale = api.amend_questionnaire(
        q["id"],
        {"expected_questionnaire_version": version,
         "due_at": "2026-10-07T17:00:00Z"},
        ctx["editor_h"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    current = get_questionnaire(api, ctx, q["id"])
    assert current["due_at"].startswith("2026-10-05")


def test_submission_after_due_single_failure_temporal(api):
    """PRD §3.4: "the logical clock must be at or before `due_at`, with a
    submission at exactly the deadline accepted
    (`ERR_SUBMISSION_WINDOW_CLOSED`)" — with the questionnaire still
    `ISSUED`, the temporal rule is the only failure.

    Design: Corner/validations/submission_after_due_single_failure_temporal
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    filing = sc["filings"][0]
    set_clock(api, PAST_DUE_AT)
    resp = submit_answers(api, q["id"], filing["id"],
                          [make_answer(1, FIVE_WORDS)])
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)
    assert resp.status_code == 422
    assert get_shell(api, ctx, q["id"], filing["id"])["status"] == "INVITED"


def test_suspended_volunteer_cannot_coordinate(api):
    """PRD §2.1: "every mutation performed under a volunteer-backed role
    additionally requires the acting volunteer — and, where a moderator is
    referenced at forum scheduling time, that referenced volunteer — to be
    in `ACTIVE` status and to hold a `CURRENT` nonpartisanship attestation
    at the current logical time; violations surface as
    `ERR_VOLUNTEER_SUSPENDED` (HTTP 403) or `ERR_ATTESTATION_LAPSED`
    (HTTP 403)."

    Design: Corner/validations/suspended_volunteer_cannot_coordinate
    """
    ctx = fresh_league(api, coordinators=("Cara One", "Cory Two"))
    c2_vol, c2_h = ctx["coordinators"][1]
    incident = report_incident(
        api, ctx, c2_vol["id"],
        description="Public endorsement recorded.",
    )
    substantiate_incident(api, ctx, incident["id"],
                          corrective_action="Suspended from coordination.")

    volunteer = get_success_data(api.get_volunteer(c2_vol["id"], ctx["admin_h"]))
    assert volunteer["status"] == "SUSPENDED"

    resp = api.create_contest(
        ctx["jurisdiction"]["id"], make_contest_payload(), c2_h
    )
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_SUSPENDED)
    assert resp.status_code == 403
