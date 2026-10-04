"""Corner-design tests: list-endpoint pagination and filtering, the tabulation
board's inline read shape, and error-envelope / error-selection behavior
(PRD §2.2, §2.3, §2.9, §3.5, §3.7, §4).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_tabulation_board,
    create_county_payload,
    create_event,
    get_event,
    get_tabulation,
    reset_clock_to_setup,
    setup_universe_with_reports,
    validate_error,
    validate_paginated,
)


def test_vote_reports_list_paginates_and_filters(api):
    """PRD §2.3: "List responses report the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."
    PRD §4: "List vote reports of a contest, filterable by status and county_id"

    Design: Corner/endpoints/vote_reports_list_paginates_and_filters
    """
    universe = setup_universe_with_reports(
        [
            {"county": "alameda", "precincts_reporting": 5,
             "votes": {"wanda": 4000, "tom": 3000}, "accept": False},
            {"county": "contra_costa", "precincts_reporting": 2,
             "votes": {"wanda": 1000, "tom": 800}, "accept": False},
            {"county": "alameda", "precincts_reporting": 8,
             "votes": {"wanda": 6500, "tom": 2500}, "accept": False},
        ],
    )
    contest_id = universe["contest"]["id"]
    flagged = universe["reports"][1]
    assert flagged["status"] == "FLAGGED"

    page1, meta1 = validate_paginated(
        api.list_contest_vote_reports(
            contest_id, TEST_USERS["clerk_headers"],
            params={"limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_contest_vote_reports(
            contest_id, TEST_USERS["clerk_headers"],
            params={"limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    expected_ids = {report["id"] for report in universe["reports"]}
    assert {row["id"] for row in page1 + page2} == expected_ids

    filtered, meta3 = validate_paginated(
        api.list_contest_vote_reports(
            contest_id, TEST_USERS["clerk_headers"],
            params={"status": "FLAGGED"},
        )
    )
    assert meta3["total_count"] == 1
    assert [row["id"] for row in filtered] == [flagged["id"]]


def test_tabulation_board_returns_full_inline_shape(api):
    """PRD §3.5: "A read of the board returns `contest_id`, `tabulation_status`,
    `call_status`, `reported_precincts`, `expected_precincts_total`, the ranked
    `candidate_totals`, `total_votes`, `margin_pct`, `outstanding_estimate`, and
    the per-county `outstanding_detail`."

    Design: Corner/endpoints/tabulation_board_returns_full_inline_shape
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
    )
    contest_id = universe["contest"]["id"]

    board = get_tabulation(contest_id)
    assert_tabulation_board(board)
    assert board["contest_id"] == contest_id
    assert board["tabulation_status"] == "REPORTING"
    assert board["call_status"] == "UNCALLED"
    assert board["reported_precincts"] == 5
    assert board["expected_precincts_total"] == 15
    assert len(board["candidate_totals"]) == 2
    assert board["total_votes"] == 7000
    assert board["margin_pct"] == 0.142857
    assert len(board["outstanding_detail"]) == 2


def test_error_envelope_carries_error_id_and_message(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.9: "Payload shape on every endpoint: required fields present, enum
    values in range, integer bounds respected (`expected_precincts` at least 1"

    Design: Corner/endpoints/error_envelope_carries_error_id_and_message
    """
    reset_clock_to_setup()
    event = create_event()
    payload = create_county_payload(
        county_fips="06041", county_name="Marin", expected_precincts=0,
        expected_vote_total=3000,
    )
    resp = api.create_county(event["id"], payload, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_invalid_enum_value_rejected(api):
    """PRD §2.9: "Payload shape on every endpoint: required fields present, enum
    values in range, integer bounds respected (`expected_precincts` at least 1,
    vote figures non-negative, `allocated_stringer_hours` at least 1,
    `candidate_votes` non-empty, `state_codes` and `licensed_states` non-empty),
    else `ERR_INVALID_REQUEST`."

    Design: Corner/errors/invalid_enum_value_rejected
    """
    reset_clock_to_setup()
    event = create_event()
    resp = api.transition_posture(
        event["id"], "FROZEN", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_event(event["id"])["posture"] == "SETUP"


def test_recount_file_on_incomplete_contest_returns_invalid_state(api):
    """PRD §3.7: "Filing requires the contest's `tabulation_status` to be
    `COMPLETE` — a contest still collecting reports is rejected with
    `ERR_INVALID_STATE`"

    Design: Corner/errors/recount_file_on_incomplete_contest_returns_invalid_state
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
        advance_to="TABULATION",
    )
    contest_id = universe["contest"]["id"]
    assert universe["contest"]["tabulation_status"] == "REPORTING"

    resp = api.create_recount_case(
        contest_id, TEST_USERS["recount_officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    _rows, meta = validate_paginated(
        api.list_recount_cases(contest_id, TEST_USERS["recount_officer_headers"])
    )
    assert meta["total_count"] == 0
