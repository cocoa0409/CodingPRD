"""Difficulty queue: dual_variant_calc.

Two counting/grading algorithms are selected by configuration, and the same
input text must produce the variant-specific result.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    EXPLANATION_GRADE_FK,
    EXPLANATION_GRADE_SMOG,
    EXPLANATION_TEXT,
    POLICY_SPLIT_TEXT,
    add_argument,
    add_candidate_contest,
    add_filing,
    advance_contest,
    create_measure,
    create_questionnaire,
    fresh_league,
    get_contest,
    get_edition,
    get_measure,
    get_questionnaire,
    get_success_data,
    issue_questionnaire,
    make_answer,
    make_cycle_payload,
    make_jurisdiction_payload,
    make_measure_contest_payload,
    move_to_questionnaire_phase,
    ready_edition,
    submit_answers,
    validate_error,
    validate_success,
)


def _dual_policy_scenario(api):
    """One league; two candidate contests differing only in word-count
    policy (STRICT vs LENIENT, limit 7); each with one verified filing and
    an ISSUED one-question questionnaire, in-window."""
    ctx = fresh_league(api)
    contest_s = add_candidate_contest(
        api, ctx, office_name="Mayor", questionnaire_word_limit=7,
        word_count_policy="STRICT",
    )
    filing_s = add_filing(api, ctx, contest_s["id"],
                          candidate_name="Ana Strict", filing_reference="F-S-1")
    contest_l = add_candidate_contest(
        api, ctx, office_name="City Clerk", questionnaire_word_limit=7,
        word_count_policy="LENIENT",
    )
    filing_l = add_filing(api, ctx, contest_l["id"],
                          candidate_name="Len Eient", filing_reference="F-L-1")
    move_to_questionnaire_phase(api, ctx, contest_s["id"])
    move_to_questionnaire_phase(api, ctx, contest_l["id"])
    q_s = issue_questionnaire(
        api, ctx, create_questionnaire(api, ctx, contest_s["id"])["id"]
    )
    q_l = issue_questionnaire(
        api, ctx, create_questionnaire(api, ctx, contest_l["id"])["id"]
    )
    return ctx, contest_s, filing_s, q_s, contest_l, filing_l, q_l


def test_strict_policy_counts_hyphenated_parts_and_skips_urls(api):
    """PRD §2.9: "Under the `STRICT` policy, a URL token counts as 0 words,
    and any other token counts as the number of hyphen-separated parts it
    contains, so a hyphenated compound contributes one word per part."
    PRD §3.4: "an answer is over limit only when its count strictly exceeds
    that limit; a count exactly at the limit passes."

    Design: Difficulty/dual_variant_calc/word_count_strict_vs_lenient_same_answer
    """
    _ctx, _cs, filing_s, q_s, _cl, _fl, _ql = _dual_policy_scenario(api)
    resp = submit_answers(
        api, q_s["id"], filing_s["id"],
        [make_answer(1, POLICY_SPLIT_TEXT)],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "OVER_LIMIT_RETURNED"
    # STRICT: My(1) pro-tenant(2) anti-sprawl(2) record(1) URL(0) proves(1) it(1) = 8
    assert data["per_answer_word_counts"] == [8]
    assert data["over_limit_positions"] == [1]


def test_lenient_policy_counts_each_token_once(api):
    """PRD §2.9: "Under the `LENIENT` policy every token counts as exactly
    1 word, whether it is a URL or a hyphenated compound, so identical text
    always yields a LENIENT count lower than or equal to its STRICT count."
    PRD §3.4: "the shell lands in `SUBMITTED` with `submitted_at` stamped
    from the logical clock, `over_limit_positions` empty, the
    questionnaire's `submitted_count` recomputed"

    Design: Difficulty/dual_variant_calc/word_count_strict_vs_lenient_same_answer
    """
    ctx, _cs, _fs, _qs, contest_l, filing_l, q_l = _dual_policy_scenario(api)
    resp = submit_answers(
        api, q_l["id"], filing_l["id"],
        [make_answer(1, POLICY_SPLIT_TEXT)],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED"
    # LENIENT: seven tokens, one word each.
    assert data["per_answer_word_counts"] == [7]
    assert data["over_limit_positions"] == []
    assert data["published_indicator"] == "PUBLISHED_UNEDITED"
    questionnaire = get_questionnaire(api, ctx, q_l["id"])
    assert questionnaire["submitted_count"] == 1
    contest = get_contest(api, ctx, contest_l["id"])
    assert contest["completion_index"] == pytest.approx(100.0)


def _open_cycle_with_measure_jurisdiction(api, ctx, *, name, fips, metric):
    cycle = get_success_data(
        api.create_cycle(make_cycle_payload(cycle_name=name), ctx["admin_h"])
    )
    cycle = get_success_data(
        api.transition_cycle(cycle["id"], {"to": "OPEN"}, ctx["admin_h"])
    )
    jur = get_success_data(
        api.create_jurisdiction(
            cycle["id"],
            make_jurisdiction_payload(
                jurisdiction_name=name, fips_code=fips,
                supported_language_codes=["EN"], reading_level_metric=metric,
            ),
            ctx["admin_h"],
        )
    )
    return cycle, jur


def _locked_measure_contest(api, ctx, jurisdiction):
    contest = get_success_data(
        api.create_contest(
            jurisdiction["id"], make_measure_contest_payload(),
            ctx["coordinator_h"],
        )
    )
    move_to_questionnaire_phase(api, ctx, contest["id"])
    measure = create_measure(api, ctx, contest["id"],
                             explanation=EXPLANATION_TEXT)
    add_argument(api, ctx, measure["id"], side="PRO",
                 text="one two three four five six seven eight nine ten",
                 credit="Committee for it")
    add_argument(api, ctx, measure["id"], side="CON",
                 text="one two three four five six seven eight nine ten",
                 credit="Committee against it")
    get_success_data(api.submit_measure_for_review(measure["id"], ctx["editor_h"]))
    get_success_data(
        api.create_review(
            measure["id"],
            {"verdict": "NEUTRAL", "notes": "Balanced and plain."},
            ctx["reviewers"][0][1],
        )
    )
    get_success_data(
        api.create_review(
            measure["id"],
            {"verdict": "NEUTRAL", "notes": "Second independent approval."},
            ctx["reviewers"][1][1],
        )
    )
    advance_contest(api, ctx, contest["id"], "GUIDE_READY")
    contest = advance_contest(api, ctx, contest["id"], "LOCKED")
    return contest, get_measure(api, ctx, measure["id"])


def _two_metric_cycles(api):
    """Two OPEN cycles in one league, one FLESCH_KINCAID jurisdiction and
    one SMOG jurisdiction, each carrying the identical explanation text on
    an APPROVED_FOR_GUIDE measure whose contest is LOCKED."""
    ctx = fresh_league(api, reviewers=("Rhea Reviewer", "Ray ReviewerTwo"))
    cycle_a = ctx["cycle"]
    contest_a, measure_a = _locked_measure_contest(api, ctx, ctx["jurisdiction"])
    cycle_b, jur_b = _open_cycle_with_measure_jurisdiction(
        api, ctx, name="Smog County", fips="06012", metric="SMOG"
    )
    contest_b, measure_b = _locked_measure_contest(api, ctx, jur_b)
    return ctx, cycle_a, contest_a, measure_a, cycle_b, contest_b, measure_b


def test_same_text_stores_both_reading_grades(api):
    """PRD §3.5: "The Flesch-Kincaid grade equals 0.39 multiplied by the
    number of words divided by the number of sentences, plus 11.8 multiplied
    by the total number of syllables divided by the number of words, minus
    15.59. The SMOG grade equals 1.043 multiplied by the square root of the
    polysyllable count multiplied by 30 and divided by the number of
    sentences, plus 3.1291."
    PRD §3.5: "Both readability grades are computed at creation and on every
    later revision and are stored as `grade_fk` and `grade_smog`."

    Design: Difficulty/dual_variant_calc/reading_grade_fk_passes_smog_fails_same_text
    """
    _ctx, _ca, _cta, measure_a, _cb, _ctb, measure_b = _two_metric_cycles(api)
    for measure in (measure_a, measure_b):
        assert measure["grade_fk"] == pytest.approx(EXPLANATION_GRADE_FK, abs=1e-9)
        assert measure["grade_smog"] == pytest.approx(EXPLANATION_GRADE_SMOG, abs=1e-9)
        assert measure["status"] == "APPROVED_FOR_GUIDE"


def test_accessibility_gate_follows_the_jurisdiction_metric(api):
    """PRD §3.6: "when the `accessibility_format` is anything other than
    `STANDARD`, every `APPROVED_FOR_GUIDE` measure in the cycle must grade
    at most 8.0 under the `reading_level_metric` of the jurisdiction that
    owns the measure's contest — a grade of exactly 8.0 passes, while 8.01
    fails (`ERR_ACCESSIBILITY_GRADE_EXCEEDED`)."

    Design: Difficulty/dual_variant_calc/reading_grade_fk_passes_smog_fails_same_text
    """
    ctx, cycle_a, _ca, _ma, cycle_b, _cb, _mb = _two_metric_cycles(api)
    ed_a = get_success_data(
        api.create_edition(
            cycle_a["id"],
            {"language_code": "EN", "channel": "PRINT",
             "accessibility_format": "LARGE_PRINT"},
            ctx["editor_h"],
        )
    )
    ed_b = get_success_data(
        api.create_edition(
            cycle_b["id"],
            {"language_code": "EN", "channel": "PRINT",
             "accessibility_format": "LARGE_PRINT"},
            ctx["editor_h"],
        )
    )
    ready_a = ready_edition(api, ctx, ed_a["id"])
    assert ready_a["status"] == "READY"  # FLESCH_KINCAID 2.65 <= 8.0 passes

    resp_b = api.transition_edition(ed_b["id"], {"to": "READY"}, ctx["editor_h"])
    validate_error(resp_b, ApiErrorId.ERR_ACCESSIBILITY_GRADE_EXCEEDED)
    assert get_edition(api, ctx, ed_b["id"])["status"] == "ASSEMBLING"
