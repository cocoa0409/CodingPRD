"""Corner queue, calculations section: zero-guard, per-question limit
override, balance ratio math, two-decimal grade storage."""
import pytest

from test_helpers import (
    EXPLANATION_GRADE_FK,
    EXPLANATION_GRADE_SMOG,
    EXPLANATION_TEXT,
    TEN_WORDS,
    THIRTY_WORDS,
    add_measure_contest,
    build_issued_scenario,
    build_measure_pipeline,
    fresh_league,
    get_contest,
    get_measure,
    get_success_data,
    make_answer,
    make_measure_payload,
    make_question,
    move_to_questionnaire_phase,
    resubmit_answers,
    submit_answers,
    validate_success,
)


def test_completion_index_zero_when_nobody_invited(api):
    """PRD §3.2: "`completion_index`, derived on every read — when the
    contest has a questionnaire, one hundred times the questionnaire's
    `submitted_count` divided by its `invited_count`, rounded half-up to one
    decimal place, and 0.0 when there is no questionnaire or nothing has
    ever been invited."

    Design: Corner/calculations/completion_index_zero_when_nobody_invited
    """
    sc = build_issued_scenario(api, filings=())
    ctx = sc["ctx"]
    assert sc["questionnaire"]["invited_count"] == 0
    contest = get_contest(api, ctx, sc["contest"]["id"])
    assert contest["completion_index"] == pytest.approx(0.0)


def test_per_question_override_beats_contest_default_limit(api):
    """PRD §3.4: "Each answer is measured against its effective limit — the
    question's `word_limit_override` when set, otherwise the contest's
    `questionnaire_word_limit` — and an answer is over limit only when its
    count strictly exceeds that limit; a count exactly at the limit passes."

    Design: Corner/calculations/per_question_override_beats_contest_default_limit
    """
    sc = build_issued_scenario(
        api,
        questions=[
            make_question(1, "Short answer?", word_limit_override=5),
            make_question(2, "Long answer?"),
        ],
    )
    qid = sc["questionnaire"]["id"]
    filing = sc["filings"][0]

    first = submit_answers(
        api, qid, filing["id"],
        [make_answer(1, "one two three four five six"),   # 6 > override 5
         make_answer(2, TEN_WORDS)],                       # 10 <= default 100
    )
    data = validate_success(first, expected_status=201)
    assert data["status"] == "OVER_LIMIT_RETURNED"
    assert data["over_limit_positions"] == [1]

    second = resubmit_answers(
        api, data["id"], filing["id"],
        [make_answer(1, "one two three four five"),       # exactly 5 passes
         make_answer(2, TEN_WORDS)],
    )
    fixed = validate_success(second)
    assert fixed["status"] == "SUBMITTED"
    assert fixed["over_limit_positions"] == []


def test_balance_ratio_flags_lopsided_arguments(api):
    """PRD §3.5: "From these totals, `balance_ratio` is the absolute
    difference between the two divided by the larger of them — except that
    when both totals are zero the divisor is 1 — rounded half-up to four
    decimal places. The `balance_flag` is true when the ratio is strictly
    greater than 0.15, so a ratio of exactly 0.15 does not raise the flag".

    Design: Corner/calculations/balance_ratio_flags_lopsided_arguments
    """
    sc = build_measure_pipeline(api, submit=False, con_text=THIRTY_WORDS)
    measure = sc["measure"]
    assert measure["pro_word_total"] == 10
    assert measure["con_word_total"] == 30
    # |10 - 30| / 30 = 0.6666... -> 0.6667 (4dp, round half-up)
    assert measure["balance_ratio"] == pytest.approx(0.6667, abs=1e-9)
    assert measure["balance_flag"] is True


def test_measure_grades_stored_at_two_decimal_precision(api):
    """PRD §3.5: "Both readability grades are computed at creation and on
    every later revision and are stored as `grade_fk` and `grade_smog`."
    PRD §2.9: "Reading-grade scores are rounded half-up to two decimal
    places, with rounding applied once at the very end of the formula."

    Design: Corner/calculations/measure_grades_stored_at_two_decimal_precision
    """
    ctx = fresh_league(api)
    contest = add_measure_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    resp = api.create_measure(
        contest["id"],
        make_measure_payload(measure_title="Measure G",
                             official_text="Official text G",
                             explanation_text=EXPLANATION_TEXT),
        ctx["editor_h"],
    )
    data = validate_success(resp, expected_status=201)
    # 11 words, 13 syllables, 1 polysyllable, 1 sentence:
    # FK = 0.39*11 + 11.8*(13/11) - 15.59 -> 2.65
    # SMOG = 1.043*sqrt(1*30/1) + 3.1291 -> 8.84
    assert data["grade_fk"] == pytest.approx(EXPLANATION_GRADE_FK, abs=1e-9)
    assert data["grade_smog"] == pytest.approx(EXPLANATION_GRADE_SMOG, abs=1e-9)
