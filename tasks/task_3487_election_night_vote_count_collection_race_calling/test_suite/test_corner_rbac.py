"""Corner-design tests: role denials and entity-backed ownership checks
(PRD §2.1, §2.9, §3.3, §3.8, §4).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_to_candidates_locked,
    advance_to_live,
    create_assignment,
    create_call_payload,
    create_metro_news_premium,
    create_stringer,
    create_wirelite_basic,
    get_contest_version,
    make_analyst_headers,
    make_customer_headers,
    make_stringer_headers,
    setup_proposed_call,
    setup_standard_universe,
    setup_universe_with_reports,
    validate_error,
    validate_paginated,
)


def test_tabulation_clerk_cannot_publish_calls(api):
    """PRD §2.1: "If the supplied role is not among the roles an endpoint
    declares in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "Desk-chief decision: PUBLISH or RETRACT a call | DecisionDeskChief"

    Design: Corner/rbac/tabulation_clerk_cannot_publish_calls
    """
    universe = setup_proposed_call()
    contest_id = universe["contest"]["id"]
    call = universe["call"]

    resp = api.decide_call(call["id"], "PUBLISH", TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    rows, _meta = validate_paginated(
        api.list_calls(contest_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[call["id"]]["status"] == "PROPOSED"


def test_decision_analyst_cannot_review_reports(api):
    """PRD §2.1: "If the supplied role is not among the roles an endpoint
    declares in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "Tabulation desk review: ACCEPT, REJECT, or VOID | TabulationClerk"

    Design: Corner/rbac/decision_analyst_cannot_review_reports
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}, "accept": False}],
    )
    contest_id = universe["contest"]["id"]
    report = universe["reports"][0]

    resp = api.review_vote_report(
        report["id"], "ACCEPT", make_analyst_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    rows, _meta = validate_paginated(
        api.list_contest_vote_reports(contest_id, TEST_USERS["clerk_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[report["id"]]["status"] == "RECEIVED"


def test_feed_operator_cannot_propose_calls(api):
    """PRD §2.1: "If the supplied role is not among the roles an endpoint
    declares in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "Propose a winner call for the contest (TABULATION only; OCC;
    certainty not evaluated) | DecisionAnalyst"

    Design: Corner/rbac/feed_operator_cannot_propose_calls
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
        advance_to="TABULATION",
    )
    contest_id = universe["contest"]["id"]
    payload = create_call_payload(
        universe["candidates"]["wanda"]["id"], get_contest_version(contest_id),
    )
    resp = api.create_call(
        contest_id, payload, TEST_USERS["feed_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_media_customer_cannot_read_other_customers_deliveries(api):
    """PRD §3.8: "a customer touching another customer's resources fails the
    ownership check of §2.9 with `ERR_UNAUTHORIZED_ROLE`."
    PRD §2.9: "a media customer touching the resources beneath their own path
    must satisfy `X-User-ID` equal to that customer's `id`."

    Design: Corner/rbac/media_customer_cannot_read_other_customers_deliveries
    """
    wirelite = create_wirelite_basic()
    metro = create_metro_news_premium()

    resp = api.list_customer_deliveries(
        metro["id"], make_customer_headers(wirelite["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_stringer_cannot_check_in_other_stringers_assignment(api):
    """PRD §3.3: "A stringer checks in to their own assignment — `X-User-ID` must
    equal the assignment's `stringer_id`, else `ERR_UNAUTHORIZED_ROLE`"
    PRD §2.9: "a stringer acting on a stringer assignment must satisfy
    `X-User-ID` equal to the assignment's `stringer_id`"

    Design: Corner/rbac/stringer_cannot_check_in_other_stringers_assignment
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    sally = create_stringer("Sally Stringer", "CA")
    sam = create_stringer("Sam Stringer", "NV")
    assignment = create_assignment(
        event_id, universe["counties"]["alameda"]["id"],
        stringer_id=sally["id"],
    )
    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])

    resp = api.check_in_assignment(
        assignment["id"], make_stringer_headers(sam["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    rows, _meta = validate_paginated(
        api.list_event_assignments(event_id, TEST_USERS["coordinator_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[assignment["id"]]["status"] == "SCHEDULED"
