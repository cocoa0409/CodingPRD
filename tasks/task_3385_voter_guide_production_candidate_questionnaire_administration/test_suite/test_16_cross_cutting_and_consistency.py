"""Corner queue, cross_cutting_layers + consistency_model sections:
common-fields mutation contract and immediate visibility of computed
fields."""
import pytest

from test_helpers import (
    CLOCK_START,
    FIVE_WORDS,
    TEST_USERS,
    assert_instant_equals,
    build_issued_scenario,
    get_contest,
    get_success_data,
    make_answer,
    set_clock,
    submit_answers,
    validate_success,
)


def test_version_increments_and_updated_at_refreshes_on_mutation(api):
    """PRD §2.5: "`version`, an integer that increments by exactly 1 on
    every mutation of that resource."
    PRD §2.5: "`updated_at`, refreshed on every mutation".
    PRD §2.5: "`created_at`, an ISO 8601 UTC timestamp with three fractional
    digits recording the logical creation time".

    Design: Corner/cross_cutting_layers/version_increments_and_updated_at_refreshes_on_mutation
    """
    set_clock(api, CLOCK_START)
    volunteer = get_success_data(
        api.create_volunteer(
            {"volunteer_name": "Vic Volunteer", "chapter_code": "CH9",
             "roles": ["EDITOR"]},
            TEST_USERS["admin_headers"],
        ),
        expected_status=201,
    )
    created_version = volunteer["version"]
    created_at = volunteer["created_at"]

    set_clock(api, "2026-09-02T00:00:00Z")
    flagged = get_success_data(
        api.flag_advocacy(volunteer["id"], {"advocacy_flag": True},
                          TEST_USERS["admin_headers"])
    )
    assert flagged["advocacy_flag"] is True
    assert flagged["version"] == created_version + 1
    assert_instant_equals(flagged["updated_at"], "2026-09-02T00:00:00Z",
                          "updated_at")
    assert_instant_equals(flagged["created_at"], created_at, "created_at")


def test_submit_returns_computed_fields_immediately(api):
    """PRD §2.5: "Consistency is immediate: every mutation is atomic and its
    full effect is visible in the response of the same request."
    PRD §3.4: "`SUBMITTED` shows as `PUBLISHED_UNEDITED`" and "the shell
    lands in `SUBMITTED` with `submitted_at` stamped from the logical clock,
    `over_limit_positions` empty, the questionnaire's `submitted_count`
    recomputed".

    Design: Corner/consistency_model/submit_returns_computed_fields_immediately
    """
    sc = build_issued_scenario(api)
    ctx, q = sc["ctx"], sc["questionnaire"]
    filing = sc["filings"][0]

    resp = submit_answers(api, q["id"], filing["id"],
                          [make_answer(1, FIVE_WORDS)])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED"
    assert data["per_answer_word_counts"] == [5]
    assert data["over_limit_positions"] == []
    assert data["published_indicator"] == "PUBLISHED_UNEDITED"
    assert_instant_equals(data["submitted_at"], "2026-09-16T00:00:00Z",
                          "submitted_at")

    contest = get_contest(api, ctx, sc["contest"]["id"])
    assert contest["completion_index"] == pytest.approx(100.0)
