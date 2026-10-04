"""Corner queue, state_machines section: invalid transitions, terminal
lockdown, precondition enforcement, idempotent sweep, lifecycle side
effects."""
from test_helpers import (
    ApiErrorId,
    ELEVEN_WORDS,
    FIVE_WORDS,
    PAST_DUE_AT,
    QUESTIONNAIRE_DUE_AT,
    add_candidate_contest,
    add_filing,
    add_forum,
    advance_contest,
    assert_instant_equals,
    build_locked_candidate_contest,
    make_cycle_payload,
    make_distribute_payload,
    make_jurisdiction_payload,
    build_confirmed_forum,
    build_distributed_edition,
    build_issued_scenario,
    close_and_pin,
    contest_version,
    create_edition,
    create_questionnaire,
    fresh_league,
    get_contest,
    get_questionnaire,
    get_shell,
    get_success_data,
    issue_questionnaire,
    lock_contest,
    make_answer,
    make_filing_payload,
    move_to_questionnaire_phase,
    ready_edition,
    resubmit_answers,
    set_clock,
    submit_answers,
    validate_error,
    validate_success,
)


def test_contest_lock_from_filing_open_returns_invalid_state(api):
    """PRD §3.2: "The contest lifecycle runs `FILING_OPEN` →
    `QUESTIONNAIRE_PHASE` → `GUIDE_READY` → `LOCKED`, each step driven by a
    `ChapterCoordinator` under the optimistic-concurrency rule of §2.6 and
    each incrementing the contest's `version`."
    PRD §2.7: "then the generic from-state check (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/contest_lock_from_filing_open_returns_invalid_state
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    version = contest_version(api, ctx, contest["id"])
    resp = api.transition_contest(
        contest["id"],
        {"to": "LOCKED", "expected_contest_version": version},
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert get_contest(api, ctx, contest["id"])["status"] == "FILING_OPEN"


def test_disqualified_filing_cannot_refile(api):
    """PRD §3.2: "Disqualification (`VERIFIED` → `DISQUALIFIED`, terminal)
    requires a `reason` in the request and cascades exactly like a verified
    withdrawal." and "Refiling returns a `WITHDRAWN` filing to `FILED` and
    is deadline-gated" — refile is defined only from `WITHDRAWN`.

    Design: Corner/state_machines/disqualified_filing_cannot_refile
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    filing = add_filing(api, ctx, contest["id"])
    disqualified = get_success_data(
        api.disqualify_filing(filing["id"], {"reason": "Filing fee bounced."},
                              ctx["coordinator_h"])
    )
    assert disqualified["status"] == "DISQUALIFIED"

    resp = api.refile_filing(filing["id"], ctx["coordinator_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409


def test_questionnaire_close_before_deadline_rejected(api):
    """PRD §3.3: "Closing (`ISSUED` → `CLOSED`) requires the logical clock
    to be strictly past `due_at`; at or before the deadline the attempt is
    rejected with `ERR_CLOSE_BEFORE_DEADLINE`."

    Design: Corner/state_machines/questionnaire_close_before_deadline_rejected
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    set_clock(api, QUESTIONNAIRE_DUE_AT)  # exactly at due_at
    resp = api.close_questionnaire(q["id"], ctx["editor_h"])
    validate_error(resp, ApiErrorId.ERR_CLOSE_BEFORE_DEADLINE)
    assert resp.status_code == 422
    assert get_questionnaire(api, ctx, q["id"])["status"] == "ISSUED"


def test_resubmit_from_submitted_returns_invalid_state(api):
    """PRD §3.4: "From `OVER_LIMIT_RETURNED` the candidate resubmits a
    corrected answer set under the same four gates" — no other shell status
    is a legal resubmit source, so the generic from-state check
    (`ERR_INVALID_STATE`, PRD §2.7) rejects a resubmit of a `SUBMITTED`
    shell.

    Design: Corner/state_machines/resubmit_from_submitted_returns_invalid_state
    """
    sc = build_issued_scenario(api)
    q = sc["questionnaire"]
    filing = sc["filings"][0]
    first = submit_answers(api, q["id"], filing["id"],
                           [make_answer(1, FIVE_WORDS)])
    shell = validate_success(first, expected_status=201)
    assert shell["status"] == "SUBMITTED"

    resp = resubmit_answers(api, shell["id"], filing["id"],
                            [make_answer(1, "changed changed changed")])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    after = get_shell(api, sc["ctx"], q["id"], filing["id"])
    assert after["status"] == "SUBMITTED"
    assert after["answers"] == [{"position_index": 1, "text": FIVE_WORDS}]


def test_sweep_marks_both_buckets_then_second_sweep_marks_zero(api):
    """PRD §3.4: "It moves every `INVITED` shell to `NONRESPONSE_MARKED` and
    every `OVER_LIMIT_RETURNED` shell to `LATE_UNPUBLISHED`, recomputes the
    questionnaire's counters, and reports how many shells it moved as
    `marked_nonresponse_count` and `marked_late_count`; a second sweep over
    the same contest moves nothing and reports zeros."

    Design: Corner/state_machines/sweep_marks_both_buckets_then_second_sweep_marks_zero
    """
    sc = build_issued_scenario(
        api, filings=(("Ana One", "F-1"), ("Bob Two", "F-2")), word_limit=10
    )
    ctx, q = sc["ctx"], sc["questionnaire"]
    over = submit_answers(api, q["id"], sc["filings"][0]["id"],
                          [make_answer(1, ELEVEN_WORDS)])
    assert validate_success(over, expected_status=201)["status"] == "OVER_LIMIT_RETURNED"

    set_clock(api, PAST_DUE_AT)
    first = validate_success(api.sweep_nonresponses(sc["contest"]["id"],
                                                    ctx["coordinator_h"]))
    assert first["marked_nonresponse_count"] == 1
    assert first["marked_late_count"] == 1

    second = validate_success(api.sweep_nonresponses(sc["contest"]["id"],
                                                     ctx["coordinator_h"]))
    assert second["marked_nonresponse_count"] == 0
    assert second["marked_late_count"] == 0


def test_nonresponse_sweep_sets_did_not_respond_indicator(api):
    """PRD §3.4: "`NONRESPONSE_MARKED` shows as `DID_NOT_RESPOND`, so the
    guide states plainly that the candidate did not reply".

    Design: Corner/state_machines/nonresponse_sweep_sets_did_not_respond_indicator
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    set_clock(api, PAST_DUE_AT)
    get_success_data(api.sweep_nonresponses(sc["contest"]["id"],
                                            ctx["coordinator_h"]))
    shell = get_shell(api, ctx, q["id"], sc["filings"][0]["id"])
    assert shell["status"] == "NONRESPONSE_MARKED"
    assert shell["published_indicator"] == "DID_NOT_RESPOND"
    assert get_questionnaire(api, ctx, q["id"])["nonresponse_count"] == 1


def test_forum_held_requires_conclusion_and_minutes(api):
    """PRD §3.7: "Marking the forum held (`CONFIRMED` → `HELD`) requires
    the logical clock to have reached `scheduled_end`
    (`ERR_FORUM_NOT_CONCLUDED`) and a non-empty `minutes_text` to be
    supplied (`ERR_INVALID_REQUEST`)."

    Design: Corner/state_machines/forum_held_before_end_or_without_minutes_rejected
    """
    sc = build_confirmed_forum(api)
    forum, mod_h = sc["forum"], sc["moderator_h"]

    early = api.transition_forum(
        forum["id"], {"to": "HELD", "minutes_text": "Minutes taken early."},
        mod_h,
    )
    validate_error(early, ApiErrorId.ERR_FORUM_NOT_CONCLUDED)
    assert early.status_code == 422

    set_clock(api, "2026-10-10T13:00:00Z")  # past scheduled_end 12:00
    no_minutes = api.transition_forum(forum["id"], {"to": "HELD"}, mod_h)
    validate_error(no_minutes, ApiErrorId.ERR_INVALID_REQUEST)
    assert no_minutes.status_code == 400

    held = get_success_data(
        api.transition_forum(
            forum["id"],
            {"to": "HELD", "minutes_text": "Attendance and rulings recorded."},
            mod_h,
        )
    )
    assert held["status"] == "HELD"


def test_distributed_edition_cannot_reopen(api):
    """PRD §3.6: "Re-opening (`READY` → `ASSEMBLING`)" exists only from
    `READY`; "Retiring (`DISTRIBUTED` → `RETIRED`) closes the edition and
    recomputes that counter again."  Any other from-state is rejected by the
    generic from-state check (`ERR_INVALID_STATE`, PRD §2.7).

    Design: Corner/state_machines/distributed_edition_cannot_reopen
    """
    sc = build_distributed_edition(api)
    ctx, edition = sc["ctx"], sc["edition"]
    assert edition["status"] == "DISTRIBUTED"

    reopen = api.transition_edition(edition["id"], {"to": "ASSEMBLING"},
                                    ctx["editor_h"])
    validate_error(reopen, ApiErrorId.ERR_INVALID_STATE)
    assert reopen.status_code == 409

    retired = get_success_data(
        api.transition_edition(edition["id"], {"to": "RETIRED"}, ctx["editor_h"])
    )
    assert retired["status"] == "RETIRED"
    cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ctx["admin_h"]))
    assert cycle["distributed_edition_count"] == 0

    reopen_terminal = api.transition_edition(edition["id"], {"to": "ASSEMBLING"},
                                             ctx["editor_h"])
    validate_error(reopen_terminal, ApiErrorId.ERR_INVALID_STATE)


def test_attestation_lapse_blocks_then_attest_cures(api):
    """PRD §3.1: "whenever the logical clock has passed
    `attestation_expires_at`, `attestation_status` reads `LAPSED`, and
    privileged mutations attempted by that volunteer fail with
    `ERR_ATTESTATION_LAPSED` until renewal."
    PRD §2.1: "The lone exception is attestation renewal itself, which
    remains open to a lapsed volunteer as the cure path."
    PRD §3.1: renewal "resets `attestation_expires_at` to ninety days after
    the current logical time, restoring `CURRENT`".

    Design: Corner/state_machines/attestation_lapse_blocks_then_attest_cures
    """
    ctx = fresh_league(api)  # coordinator created 2026-09-01, expires 2026-11-30
    set_clock(api, "2026-12-01T00:00:00Z")  # attestation lapsed

    blocked = api.create_contest(
        ctx["jurisdiction"]["id"],
        {"kind": "CANDIDATE_RACE", "office_name": "Mayor",
         "filing_deadline": "2027-01-15T17:00:00Z"},
        ctx["coordinator_h"],
    )
    validate_error(blocked, ApiErrorId.ERR_ATTESTATION_LAPSED)
    assert blocked.status_code == 403

    renewed = get_success_data(
        api.attest_volunteer(ctx["coordinator"]["id"], ctx["coordinator_h"])
    )
    assert renewed["attestation_status"] == "CURRENT"
    # 2026-12-01 + 90 days == 2027-03-01
    assert_instant_equals(renewed["attestation_expires_at"], "2027-03-01T00:00:00Z",
                          "attestation_expires_at")

    contest = api.create_contest(
        ctx["jurisdiction"]["id"],
        {"kind": "CANDIDATE_RACE", "office_name": "Mayor",
         "filing_deadline": "2027-01-15T17:00:00Z"},
        ctx["coordinator_h"],
    )
    validate_success(contest, expected_status=201)


def test_publish_blocked_by_reported_incident(api):
    """PRD §3.9: "no policy incident involving any volunteer referenced by
    the cycle's activity may remain `REPORTED`
    (`ERR_UNRESOLVED_INCIDENTS_EXIST`)".

    Design: Corner/state_machines/publish_blocked_by_reported_incident
    """
    # A forum's `moderator_volunteer_id` is a declared volunteer reference on
    # a resource of the cycle (PRD §3.7), so the moderator is unambiguously
    # "a volunteer referenced by the cycle's activity".
    ctx = fresh_league(api, moderators=("Mod One",))
    sc = build_issued_scenario(api, ctx)
    contest = sc["contest"]
    mod_vol = ctx["moderators"][0][0]
    add_forum(api, ctx, contest["id"], mod_vol["id"])
    close_and_pin(api, ctx, sc["questionnaire"]["id"])
    lock_contest(api, ctx, contest["id"])
    edition = create_edition(api, ctx)
    ready_edition(api, ctx, edition["id"])
    get_success_data(
        api.distribute_edition(
            edition["id"], make_distribute_payload(), ctx["editor_h"]
        )
    )

    incident = get_success_data(
        api.create_incident(
            {"volunteer_id": mod_vol["id"],
             "incident_type": "MODERATOR_BIAS",
             "description": "Alleged moderator bias."},
            ctx["coordinator_h"],
        )
    )
    blocked = api.transition_cycle(ctx["cycle"]["id"], {"to": "PUBLISHED"},
                                   ctx["admin_h"])
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_INCIDENTS_EXIST)
    assert blocked.status_code == 422
    assert get_success_data(
        api.get_cycle(ctx["cycle"]["id"], ctx["admin_h"])
    )["status"] == "OPEN"

    get_success_data(
        api.transition_incident(incident["id"], {"to": "DISMISSED"}, ctx["admin_h"])
    )
    published = get_success_data(
        api.transition_cycle(ctx["cycle"]["id"], {"to": "PUBLISHED"}, ctx["admin_h"])
    )
    assert published["status"] == "PUBLISHED"


def test_publish_blocked_by_unlocked_contest_and_by_missing_distribution(api):
    """PRD §3.9: "the cycle must contain at least one contest and every
    contest of the cycle must be `LOCKED` (`ERR_CONTESTS_NOT_LOCKED`); no
    policy incident involving any volunteer referenced by the cycle's
    activity may remain `REPORTED` (`ERR_UNRESOLVED_INCIDENTS_EXIST`); and
    at least one edition must actually have reached the public, meaning
    `distributed_edition_count` must be at least 1
    (`ERR_NO_DISTRIBUTED_EDITION`)."

    Design: Corner/state_machines/publish_blocked_by_unlocked_contest_and_by_missing_distribution
    """
    ctx = fresh_league(api)
    # Cycle A (the fresh_league cycle): one contest still FILING_OPEN.
    add_candidate_contest(api, ctx)

    # Cycle B: one LOCKED contest, nothing distributed.
    cycle_b = get_success_data(
        api.create_cycle(make_cycle_payload(cycle_name="Cycle B"), ctx["admin_h"])
    )
    cycle_b = get_success_data(
        api.transition_cycle(cycle_b["id"], {"to": "OPEN"}, ctx["admin_h"])
    )
    jur_b = get_success_data(
        api.create_jurisdiction(
            cycle_b["id"],
            make_jurisdiction_payload(jurisdiction_name="Springfield B",
                                      fips_code="06002"),
            ctx["admin_h"],
        )
    )
    contest_b = get_success_data(
        api.create_contest(
            jur_b["id"],
            {"kind": "CANDIDATE_RACE", "office_name": "Mayor",
             "filing_deadline": "2026-09-15T17:00:00Z"},
            ctx["coordinator_h"],
        )
    )
    move_to_questionnaire_phase(api, ctx, contest_b["id"])
    q_b = issue_questionnaire(
        api, ctx, create_questionnaire(api, ctx, contest_b["id"])["id"]
    )
    close_and_pin(api, ctx, q_b["id"])
    advance_contest(api, ctx, contest_b["id"], "GUIDE_READY")
    advance_contest(api, ctx, contest_b["id"], "LOCKED")

    err_a = api.transition_cycle(ctx["cycle"]["id"], {"to": "PUBLISHED"},
                                 ctx["admin_h"])
    validate_error(err_a, ApiErrorId.ERR_CONTESTS_NOT_LOCKED)
    assert err_a.status_code == 422

    err_b = api.transition_cycle(cycle_b["id"], {"to": "PUBLISHED"},
                                 ctx["admin_h"])
    validate_error(err_b, ApiErrorId.ERR_NO_DISTRIBUTED_EDITION)
    assert err_b.status_code == 422


def test_phase_advance_at_exact_deadline_rejected_filing_accepted(api):
    """PRD §3.2: "at exactly the deadline the advance is rejected with
    `ERR_FILING_STILL_OPEN`, and filings remain acceptable at that
    instant."

    Design: Corner/state_machines/phase_advance_at_exact_deadline_rejected_filing_at_exact_deadline_accepted
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    set_clock(api, "2026-09-15T17:00:00Z")  # exactly the filing deadline

    filing = api.create_filing(
        contest["id"],
        make_filing_payload(candidate_name="Last Minute",
                            filing_reference="F-LM"),
        ctx["coordinator_h"],
    )
    validate_success(filing, expected_status=201)

    version = contest_version(api, ctx, contest["id"])
    advance = api.transition_contest(
        contest["id"],
        {"to": "QUESTIONNAIRE_PHASE", "expected_contest_version": version},
        ctx["coordinator_h"],
    )
    validate_error(advance, ApiErrorId.ERR_FILING_STILL_OPEN)
    assert advance.status_code == 422


def test_submit_at_exact_due_at_accepted(api):
    """PRD §3.4: "the logical clock must be at or before `due_at`, with a
    submission at exactly the deadline accepted
    (`ERR_SUBMISSION_WINDOW_CLOSED`)"."

    Design: Corner/state_machines/submit_at_exact_due_at_accepted
    """
    sc = build_issued_scenario(api)
    q = sc["questionnaire"]
    filing = sc["filings"][0]
    set_clock(api, QUESTIONNAIRE_DUE_AT)  # exactly at due_at
    resp = submit_answers(api, q["id"], filing["id"],
                          [make_answer(1, FIVE_WORDS)])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED"
    assert_instant_equals(data["submitted_at"], QUESTIONNAIRE_DUE_AT,
                          "submitted_at")


def test_amend_extending_due_reinvites_nonresponse_shells(api):
    """PRD §3.3: "when the amendment extends `due_at` to a moment beyond the
    current logical time, every shell previously marked `NONRESPONSE_MARKED`
    returns to `INVITED`, its `published_indicator` returns to `PENDING`,
    and the questionnaire's `nonresponse_count` is recomputed."

    Design: Corner/state_machines/amend_extending_due_reinvites_nonresponse_shells
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    filing = sc["filings"][0]
    set_clock(api, PAST_DUE_AT)
    get_success_data(api.sweep_nonresponses(sc["contest"]["id"],
                                            ctx["coordinator_h"]))
    assert get_shell(api, ctx, q["id"], filing["id"])["status"] == "NONRESPONSE_MARKED"

    version = get_questionnaire(api, ctx, q["id"])["version"]
    amended = get_success_data(
        api.amend_questionnaire(
            q["id"],
            {"expected_questionnaire_version": version,
             "due_at": "2026-10-10T17:00:00Z"},
            ctx["editor_h"],
        )
    )
    assert_instant_equals(amended["due_at"], "2026-10-10T17:00:00Z", "due_at")

    shell = get_shell(api, ctx, q["id"], filing["id"])
    assert shell["status"] == "INVITED"
    assert shell["published_indicator"] == "PENDING"
    assert get_questionnaire(api, ctx, q["id"])["nonresponse_count"] == 0
