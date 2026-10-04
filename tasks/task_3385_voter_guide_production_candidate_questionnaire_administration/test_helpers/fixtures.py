"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly
restarted server (empty database, logical clock at the startup default of
2026-09-01T00:00:00Z) using only PRD-declared endpoints.  Setup calls go
through get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading: after a volunteer or filing is created, every call made
under its entity-backed role uses make_*_headers(entity["id"]) — never the
shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CLOCK_START,
    EXPLANATION_TEXT,
    FILING_DEADLINE,
    PAST_DUE_AT,
    PAST_FILING_DEADLINE,
    QUESTIONNAIRE_DUE_AT,
    TEN_WORDS,
)
from .factories import (
    make_argument_payload,
    make_clock_payload,
    make_contest_payload,
    make_cycle_payload,
    make_edition_payload,
    make_filing_payload,
    make_forum_payload,
    make_incident_payload,
    make_jurisdiction_payload,
    make_measure_contest_payload,
    make_measure_payload,
    make_questionnaire_payload,
    make_review_payload,
    make_volunteer_payload,
)
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_coordinator_headers,
    make_editor_headers,
    make_moderator_headers,
    make_reviewer_headers,
)


# ── Clock ───────────────────────────────────────────────────────────────

def set_clock(api, instant):
    return get_success_data(
        api.set_clock(make_clock_payload(instant), TEST_USERS["admin_headers"])
    )


# ── Volunteers ──────────────────────────────────────────────────────────

def create_volunteer(api, name, roles, chapter_code="CH1", advocacy_flag=None):
    payload = make_volunteer_payload(
        volunteer_name=name, chapter_code=chapter_code, roles=list(roles)
    )
    if advocacy_flag is not None:
        payload["advocacy_flag"] = advocacy_flag
    return get_success_data(api.create_volunteer(payload, TEST_USERS["admin_headers"]))


# ── League base: volunteers + OPEN cycle + jurisdiction ────────────────

def fresh_league(api, *, languages=("EN",), metric="FLESCH_KINCAID",
                 clock=CLOCK_START, coordinators=("Cara Coordinator",),
                 editors=("Edna Editor",), reviewers=(), moderators=(),
                 fips_code="06001"):
    """Clock pinned; volunteers created; cycle created and opened; one
    jurisdiction added.  Returns a ctx dict.  Per-role entries are lists of
    (volunteer, headers) tuples; the singular keys hold the first of each."""
    set_clock(api, clock)
    ctx = {
        "admin_h": TEST_USERS["admin_headers"],
        "public_h": TEST_USERS["public_headers"],
    }

    def _build(names, roles, make_headers):
        pairs = []
        for name in names:
            vol = create_volunteer(api, name, roles)
            pairs.append((vol, make_headers(vol["id"])))
        return pairs

    ctx["coordinators"] = _build(coordinators, ["COORDINATOR"], make_coordinator_headers)
    ctx["editors"] = _build(editors, ["EDITOR"], make_editor_headers)
    ctx["reviewers"] = _build(reviewers, ["REVIEWER"], make_reviewer_headers)
    ctx["moderators"] = _build(moderators, ["MODERATOR"], make_moderator_headers)
    for singular, key in (("coordinator", "coordinators"), ("editor", "editors"),
                          ("reviewer", "reviewers"), ("moderator", "moderators")):
        pairs = ctx[key]
        ctx[singular] = pairs[0][0] if pairs else None
        ctx[singular + "_h"] = pairs[0][1] if pairs else None

    cycle = get_success_data(
        api.create_cycle(make_cycle_payload(), ctx["admin_h"])
    )
    cycle = get_success_data(
        api.transition_cycle(cycle["id"], {"to": "OPEN"}, ctx["admin_h"])
    )
    jur = get_success_data(
        api.create_jurisdiction(
            cycle["id"],
            make_jurisdiction_payload(
                supported_language_codes=list(languages),
                reading_level_metric=metric,
                fips_code=fips_code,
            ),
            ctx["admin_h"],
        )
    )
    ctx["cycle"] = cycle
    ctx["jurisdiction"] = jur
    return ctx


# ── Contests ────────────────────────────────────────────────────────────

def add_candidate_contest(api, ctx, *, office_name="Mayor",
                          filing_deadline=FILING_DEADLINE,
                          questionnaire_word_limit=None, word_count_policy=None):
    payload = make_contest_payload(
        office_name=office_name, filing_deadline=filing_deadline
    )
    if questionnaire_word_limit is not None:
        payload["questionnaire_word_limit"] = questionnaire_word_limit
    if word_count_policy is not None:
        payload["word_count_policy"] = word_count_policy
    return get_success_data(
        api.create_contest(ctx["jurisdiction"]["id"], payload, ctx["coordinator_h"])
    )


def add_measure_contest(api, ctx, *, filing_deadline=FILING_DEADLINE):
    return get_success_data(
        api.create_contest(
            ctx["jurisdiction"]["id"],
            make_measure_contest_payload(filing_deadline=filing_deadline),
            ctx["coordinator_h"],
        )
    )


def get_contest(api, ctx, contest_id):
    return get_success_data(api.get_contest(contest_id, ctx["coordinator_h"]))


def contest_version(api, ctx, contest_id):
    return get_contest(api, ctx, contest_id)["version"]


def advance_contest(api, ctx, contest_id, to):
    """Version-gated contest transition; always re-reads the version first."""
    version = contest_version(api, ctx, contest_id)
    return get_success_data(
        api.transition_contest(
            contest_id,
            {"to": to, "expected_contest_version": version},
            ctx["coordinator_h"],
        )
    )


def move_to_questionnaire_phase(api, ctx, contest_id, *, at=PAST_FILING_DEADLINE):
    set_clock(api, at)
    return advance_contest(api, ctx, contest_id, "QUESTIONNAIRE_PHASE")


def lock_contest(api, ctx, contest_id):
    advance_contest(api, ctx, contest_id, "GUIDE_READY")
    return advance_contest(api, ctx, contest_id, "LOCKED")


# ── Filings ─────────────────────────────────────────────────────────────

def add_filing(api, ctx, contest_id, *, candidate_name="Ana One",
               filing_reference="F-1", verify=True):
    filing = get_success_data(
        api.create_filing(
            contest_id,
            make_filing_payload(
                candidate_name=candidate_name, filing_reference=filing_reference
            ),
            ctx["coordinator_h"],
        )
    )
    if verify:
        filing = get_success_data(
            api.verify_filing(filing["id"], ctx["coordinator_h"])
        )
    return filing


# ── Questionnaires and responses ────────────────────────────────────────

def create_questionnaire(api, ctx, contest_id, *, due_at=QUESTIONNAIRE_DUE_AT,
                         questions=None):
    payload = make_questionnaire_payload()
    payload["due_at"] = due_at
    if questions is not None:
        payload["questions"] = questions
    return get_success_data(
        api.create_questionnaire(contest_id, payload, ctx["editor_h"])
    )


def get_questionnaire(api, ctx, questionnaire_id):
    return get_success_data(api.get_questionnaire(questionnaire_id, ctx["editor_h"]))


def issue_questionnaire(api, ctx, questionnaire_id):
    return get_success_data(
        api.issue_questionnaire(questionnaire_id, ctx["editor_h"])
    )


def close_and_pin(api, ctx, questionnaire_id, *, at=PAST_DUE_AT):
    """Advance the clock strictly past due_at, then close and pin."""
    set_clock(api, at)
    get_success_data(api.close_questionnaire(questionnaire_id, ctx["editor_h"]))
    return get_success_data(api.pin_questionnaire(questionnaire_id, ctx["editor_h"]))


def submit_answers(api, questionnaire_id, filing_id, answers):
    """Raw response — may be 201 or an error envelope."""
    return api.submit_response(
        questionnaire_id, {"answers": answers}, make_candidate_headers(filing_id)
    )


def resubmit_answers(api, response_id, filing_id, answers):
    return api.resubmit_response(
        response_id, {"answers": answers}, make_candidate_headers(filing_id)
    )


def list_shells(api, ctx, questionnaire_id, params=None):
    return get_success_data(
        api.list_responses(questionnaire_id, ctx["coordinator_h"], params=params)
    )


def get_shell(api, ctx, questionnaire_id, filing_id):
    shells = list_shells(api, ctx, questionnaire_id)
    for shell in shells:
        if shell["filing_id"] == filing_id:
            return shell
    raise AssertionError(
        f"no response shell for filing {filing_id} on questionnaire {questionnaire_id}"
    )


def build_issued_scenario(api, ctx=None, *, filings=(("Ana One", "F-1"),),
                          word_limit=None, policy=None,
                          due_at=QUESTIONNAIRE_DUE_AT, questions=None,
                          languages=("EN",), metric="FLESCH_KINCAID",
                          office_name="Mayor"):
    """Candidate contest carried to QUESTIONNAIRE_PHASE with an ISSUED
    questionnaire and INVITED shells for each verified filing."""
    if ctx is None:
        ctx = fresh_league(api, languages=languages, metric=metric)
    # A reused ctx may carry a clock already advanced past the filing
    # deadline by an earlier contest's pipeline; rewind so the new
    # contest's filing window is open (PRD 3.2 deadline rule).
    set_clock(api, CLOCK_START)
    contest = add_candidate_contest(
        api, ctx, office_name=office_name,
        questionnaire_word_limit=word_limit, word_count_policy=policy,
    )
    filing_rows = [
        add_filing(api, ctx, contest["id"], candidate_name=name,
                   filing_reference=ref)
        for name, ref in filings
    ]
    move_to_questionnaire_phase(api, ctx, contest["id"])
    questionnaire = create_questionnaire(
        api, ctx, contest["id"], due_at=due_at, questions=questions
    )
    questionnaire = issue_questionnaire(api, ctx, questionnaire["id"])
    return {
        "ctx": ctx,
        "contest": get_contest(api, ctx, contest["id"]),
        "questionnaire": questionnaire,
        "filings": filing_rows,
    }


def build_locked_candidate_contest(api, ctx=None, *,
                                   filings=(("Ana One", "F-1"),),
                                   submissions=None, word_limit=None,
                                   policy=None, questions=None):
    """Full pipeline through LOCKED: issue, optional per-filing submissions
    (dict mapping filing_reference -> answers list), close+pin, GUIDE_READY,
    LOCKED."""
    sc = build_issued_scenario(
        api, ctx, filings=filings, word_limit=word_limit, policy=policy,
        questions=questions,
    )
    ctx = sc["ctx"]
    qid = sc["questionnaire"]["id"]
    responses = {}
    if submissions:
        by_ref = {f["filing_reference"]: f for f in sc["filings"]}
        for ref, answers in submissions.items():
            resp = submit_answers(api, qid, by_ref[ref]["id"], answers)
            responses[ref] = get_success_data(resp)
    close_and_pin(api, ctx, qid)
    sc["questionnaire"] = get_questionnaire(api, ctx, qid)
    sc["contest"] = lock_contest(api, ctx, sc["contest"]["id"])
    sc["responses"] = responses
    return sc


# ── Ballot measures ─────────────────────────────────────────────────────

def create_measure(api, ctx, contest_id, *, explanation=EXPLANATION_TEXT,
                   editor_idx=0):
    return get_success_data(
        api.create_measure(
            contest_id,
            make_measure_payload(explanation_text=explanation),
            ctx["editors"][editor_idx][1],
        )
    )


def add_argument(api, ctx, measure_id, *, side="PRO", text=TEN_WORDS,
                 credit="Committee", editor_idx=0):
    return get_success_data(
        api.create_argument(
            measure_id,
            make_argument_payload(side=side, argument_text=text,
                                  author_credit=credit),
            ctx["editors"][editor_idx][1],
        )
    )


def get_measure(api, ctx, measure_id):
    return get_success_data(api.get_measure(measure_id, ctx["editor_h"]))


def review_measure(api, ctx, measure_id, reviewer_idx=0, *, verdict="NEUTRAL",
                   notes="Balanced and plain."):
    return api.create_review(
        measure_id,
        make_review_payload(verdict=verdict, notes=notes),
        ctx["reviewers"][reviewer_idx][1],
    )


def build_measure_pipeline(api, ctx=None, *, explanation=EXPLANATION_TEXT,
                           submit=True, approve=False, lock=False,
                           pro_text=TEN_WORDS, con_text=TEN_WORDS):
    """Measure contest in QUESTIONNAIRE_PHASE with a drafted measure carrying
    one ACCEPTED argument on each side; optionally submitted for review,
    approved by two distinct reviewers, and its contest carried to LOCKED."""
    if ctx is None:
        ctx = fresh_league(
            api, reviewers=("Rhea Reviewer", "Ray ReviewerTwo")
        )
    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = create_measure(api, ctx, contest["id"], explanation=explanation)
    add_argument(api, ctx, measure["id"], side="PRO", text=pro_text,
                 credit="Yes committee")
    add_argument(api, ctx, measure["id"], side="CON", text=con_text,
                 credit="No committee")
    if submit or approve or lock:
        measure = get_success_data(
            api.submit_measure_for_review(measure["id"], ctx["editor_h"])
        )
    if approve or lock:
        get_success_data(review_measure(api, ctx, measure["id"], 0))
        get_success_data(review_measure(api, ctx, measure["id"], 1))
        measure = get_measure(api, ctx, measure["id"])
    if lock:
        lock_contest(api, ctx, contest["id"])
    return {
        "ctx": ctx,
        "contest": get_contest(api, ctx, contest["id"]),
        "measure": get_measure(api, ctx, measure["id"]),
    }


# ── Guide editions ──────────────────────────────────────────────────────

def create_edition(api, ctx, *, language_code="EN", channel="PRINT",
                   accessibility_format="STANDARD"):
    return get_success_data(
        api.create_edition(
            ctx["cycle"]["id"],
            make_edition_payload(
                language_code=language_code, channel=channel,
                accessibility_format=accessibility_format,
            ),
            ctx["editor_h"],
        )
    )


def get_edition(api, ctx, edition_id):
    return get_success_data(api.get_edition(edition_id, ctx["editor_h"]))


def ready_edition(api, ctx, edition_id):
    return get_success_data(
        api.transition_edition(edition_id, {"to": "READY"}, ctx["editor_h"])
    )


def build_distributed_edition(api, ctx=None, *, print_run_total=100,
                              channel_code="LIBRARY"):
    """One LOCKED candidate contest (pinned, empty questionnaire) plus an
    edition carried through READY to DISTRIBUTED."""
    sc = build_locked_candidate_contest(api, ctx, filings=())
    ctx = sc["ctx"]
    edition = create_edition(api, ctx)
    edition = ready_edition(api, ctx, edition["id"])
    edition = get_success_data(
        api.distribute_edition(
            edition["id"],
            {
                "print_run_total": print_run_total,
                "channel_requests": [
                    {
                        "channel_code": channel_code,
                        "requested": print_run_total,
                        "priority_tier": 1,
                    }
                ],
            },
            ctx["editor_h"],
        )
    )
    sc["edition"] = edition
    return sc


# ── Forums ──────────────────────────────────────────────────────────────

def add_forum(api, ctx, contest_id, moderator_id, *,
              start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z"):
    return get_success_data(
        api.create_forum(
            contest_id,
            make_forum_payload(
                scheduled_start=start, scheduled_end=end,
                moderator_volunteer_id=moderator_id,
            ),
            ctx["coordinator_h"],
        )
    )


def confirm_forum(api, forum_id, moderator_headers):
    return get_success_data(
        api.transition_forum(forum_id, {"to": "CONFIRMED"}, moderator_headers)
    )


def build_confirmed_forum(api, ctx=None, *, filings=2, moderators=("Mod One",),
                          start="2026-10-10T10:00:00Z",
                          end="2026-10-10T12:00:00Z"):
    """Candidate contest in QUESTIONNAIRE_PHASE with `filings` verified
    filings and a CONFIRMED forum under the first moderator."""
    if ctx is None:
        ctx = fresh_league(api, moderators=moderators or ("Mod One",))
    contest = add_candidate_contest(api, ctx)
    filing_rows = [
        add_filing(api, ctx, contest["id"], candidate_name=f"Candidate {i}",
                   filing_reference=f"F-{i}")
        for i in range(1, filings + 1)
    ]
    move_to_questionnaire_phase(api, ctx, contest["id"])
    mod_vol, mod_h = ctx["moderators"][0]
    forum = add_forum(api, ctx, contest["id"], mod_vol["id"],
                      start=start, end=end)
    forum = confirm_forum(api, forum["id"], mod_h)
    return {
        "ctx": ctx, "contest": contest, "filings": filing_rows,
        "forum": forum, "moderator": mod_vol, "moderator_h": mod_h,
    }


# ── Incidents ───────────────────────────────────────────────────────────

def report_incident(api, ctx, volunteer_id, *,
                    incident_type="PARTISAN_STATEMENT",
                    description="Alleged nonpartisanship breach."):
    return get_success_data(
        api.create_incident(
            make_incident_payload(
                volunteer_id=volunteer_id, incident_type=incident_type,
                description=description,
            ),
            ctx["coordinator_h"],
        )
    )


def substantiate_incident(api, ctx, incident_id,
                          corrective_action="Removed from duties."):
    return get_success_data(
        api.transition_incident(
            incident_id,
            {"to": "SUBSTANTIATED", "corrective_action": corrective_action},
            ctx["admin_h"],
        )
    )
