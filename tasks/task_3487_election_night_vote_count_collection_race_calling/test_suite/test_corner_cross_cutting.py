"""Corner-design tests: optimistic concurrency on the contest aggregate,
selector policy, license-tiered delivery fan-out, and immediate read-after-write
visibility (PRD §2.7, §3.3, §3.4, §3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    advance_to_tabulation,
    alameda_payload,
    assert_result_delivery,
    create_assignment,
    create_assignment_payload,
    create_call_payload,
    create_county,
    create_event,
    create_stringer,
    create_stringer_with_no_show_history,
    create_vote_report_payload,
    expected_delivery_fee_cents,
    get_contest,
    get_contest_version,
    list_customer_deliveries,
    make_analyst_headers,
    propose_call,
    reset_clock_to_setup,
    setup_published_call,
    setup_standard_universe,
    setup_universe_with_reports,
    submit_feed_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_occ_stale_version_on_vote_report_rejected(api):
    """PRD §2.7: "If the value does not match the contest's current `version` —
    because an intervening vote report, review decision, call proposal,
    publication, retraction, or configuration edit advanced it — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read
    the contest before writing."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_vote_report_rejected
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    stale_version = universe["contest"]["version"]
    votes_a = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    first = api.create_vote_report(
        contest_id,
        create_vote_report_payload(
            universe["counties"]["alameda"]["id"], 5, votes_a, stale_version,
            source="FEED",
        ),
        TEST_USERS["feed_operator_headers"],
    )
    validate_success(first, 201)
    assert get_contest(contest_id)["version"] == stale_version + 1

    votes_b = {
        universe["candidates"]["wanda"]["id"]: 1300,
        universe["candidates"]["tom"]["id"]: 1200,
    }
    second = api.create_vote_report(
        contest_id,
        create_vote_report_payload(
            universe["counties"]["contra_costa"]["id"], 2, votes_b,
            stale_version, source="FEED",
        ),
        TEST_USERS["feed_operator_headers"],
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_version_on_call_proposal_rejected(api):
    """PRD §2.7: "Exactly two write operations carry optimistic concurrency
    control, both guarded on the contest's `version`: submitting a vote report
    (`POST /contests/{id}/vote-reports`) and proposing a race call (`POST
    /contests/{id}/calls`)."
    PRD §2.7: "If the value does not match the contest's current `version` —
    because an intervening vote report, review decision, call proposal,
    publication, retraction, or configuration edit advanced it — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_stale_version_on_call_proposal_rejected
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
        advance_to="TABULATION",
    )
    contest_id = universe["contest"]["id"]
    stale_version = get_contest_version(contest_id)

    first = api.create_call(
        contest_id,
        create_call_payload(
            universe["candidates"]["wanda"]["id"], stale_version,
        ),
        make_analyst_headers(),
    )
    validate_success(first, 201)

    second = api.create_call(
        contest_id,
        create_call_payload(
            universe["candidates"]["tom"]["id"], stale_version,
        ),
        make_analyst_headers(),
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)


def test_contest_version_increments_on_every_mutation(api):
    """PRD §2.7: "The writes that themselves advance the contest's `version` by
    one are: vote-report submission, call proposal, the ACCEPT and VOID review
    decisions, call publication, retraction of a published call, and pre-lock
    contest configuration edits."

    Design: Corner/cross_cutting_layers/contest_version_increments_on_every_mutation
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    v0 = universe["contest"]["version"]

    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    report = submit_feed_report(
        contest_id, universe["counties"]["alameda"]["id"], 5, votes,
    )
    assert get_contest(contest_id)["version"] == v0 + 1

    accept_report(report["id"])
    assert get_contest(contest_id)["version"] == v0 + 2

    advance_to_tabulation(universe["event"]["id"])
    propose_call(contest_id, universe["candidates"]["wanda"]["id"])
    assert get_contest(contest_id)["version"] == v0 + 3


def test_selector_picks_highest_career_reliability(api):
    """PRD §3.3: "the eligible pool is every rostered stringer with no
    overlapping `SCHEDULED` or `ACTIVE` assignment for the requested window,
    ranked by the reliability variant named by the event's
    `stringer_selection_mode` — highest score first, ties broken by earliest
    roster registration"
    PRD §3.3: "The assignment records `auto_selected` as true when the selector
    ran and false when the coordinator named the stringer."

    Design: Corner/cross_cutting_layers/selector_picks_highest_career_reliability
    """
    history = create_stringer_with_no_show_history()
    sally = history["stringer"]
    reset_clock_to_setup()
    event = create_event()
    alameda = create_county(event["id"], alameda_payload())
    sam = create_stringer("Sam Stringer", "NV")

    assignment = create_assignment(event["id"], alameda["id"])
    assert assignment["stringer_id"] == sam["id"]
    assert assignment["auto_selected"] is True


def test_selector_tie_breaks_by_earliest_created_at(api):
    """PRD §3.3: "the eligible pool is every rostered stringer with no
    overlapping `SCHEDULED` or `ACTIVE` assignment for the requested window,
    ranked by the reliability variant named by the event's
    `stringer_selection_mode` — highest score first, ties broken by earliest
    roster registration"

    Design: Corner/cross_cutting_layers/selector_tie_breaks_by_earliest_created_at
    """
    reset_clock_to_setup()
    event = create_event()
    alameda = create_county(event["id"], alameda_payload())
    sally = create_stringer("Sally Stringer", "CA")
    create_stringer("Sam Stringer", "NV")

    assignment = create_assignment(event["id"], alameda["id"])
    assert assignment["stringer_id"] == sally["id"]
    assert assignment["auto_selected"] is True


def test_selector_empty_pool_returns_no_eligible_stringer(api):
    """PRD §3.3: "an empty pool rejects the request with
    `ERR_NO_ELIGIBLE_STRINGER`."
    PRD §3.3: "the eligible pool is every rostered stringer with no overlapping
    `SCHEDULED` or `ACTIVE` assignment for the requested window"

    Design: Corner/cross_cutting_layers/selector_empty_pool_returns_no_eligible_stringer
    """
    reset_clock_to_setup()
    event = create_event()
    alameda = create_county(event["id"], alameda_payload())
    sally = create_stringer()
    create_assignment(
        event["id"], alameda["id"], stringer_id=sally["id"],
        window_start="2026-11-03T08:00:00Z", window_end="2026-11-03T20:00:00Z",
    )

    payload = create_assignment_payload(
        alameda["id"],
        window_start="2026-11-03T19:00:00Z",
        window_end="2026-11-03T23:00:00Z",
    )
    resp = api.create_assignment(
        event["id"], payload, TEST_USERS["coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STRINGER)


def test_call_deliveries_reach_premium_but_not_basic(api):
    """PRD §3.8: "Publishing a race call creates one `CALL` delivery per customer
    whose `licensed_states` contains the contest's `state_code` and whose tier is
    `STANDARD` or `PREMIUM`."
    PRD §3.8: "Accepting a vote report creates one `VOTE_UPDATE` delivery per
    customer whose `licensed_states` contains the reporting county's
    `state_code`, at every license tier."
    PRD §3.8: "a `BASIC` customer only ever receives `VOTE_UPDATE` content, while
    `CALL` and `CALL_CREDIT` content requires `STANDARD` or `PREMIUM`."

    Design: Corner/cross_cutting_layers/call_deliveries_reach_premium_but_not_basic
    """
    universe = setup_published_call(
        link_contra_costa=False, customers=("basic", "premium"),
    )
    premium = universe["customers"]["premium"]
    basic = universe["customers"]["basic"]

    premium_rows, premium_meta = list_customer_deliveries(premium["id"])
    assert premium_meta["total_count"] == 2
    premium_by_type = {row["content_type"]: row for row in premium_rows}
    for row in premium_rows:
        assert_result_delivery(row)
    assert premium_by_type["VOTE_UPDATE"]["status"] == "SENT"
    assert premium_by_type["VOTE_UPDATE"]["fee_cents"] == (
        expected_delivery_fee_cents("VOTE_UPDATE", "PREMIUM")
    )
    assert premium_by_type["CALL"]["status"] == "SENT"
    assert premium_by_type["CALL"]["fee_cents"] == (
        expected_delivery_fee_cents("CALL", "PREMIUM")
    )

    basic_rows, basic_meta = list_customer_deliveries(basic["id"])
    assert basic_meta["total_count"] == 1
    assert basic_rows[0]["content_type"] == "VOTE_UPDATE"
    assert basic_rows[0]["status"] == "SENT"
    assert basic_rows[0]["fee_cents"] == (
        expected_delivery_fee_cents("VOTE_UPDATE", "BASIC")
    )


def test_immediate_consistency_read_after_report_write(api):
    """PRD §3.4: "Acceptance into the intake queue has three immediate effects.
    The contest's `version` increments by one. If this is the contest's first
    report, its `tabulation_status` moves from `AWAITING` to `REPORTING`
    regardless of the status the report itself lands in."

    Design: Corner/consistency_model/immediate_consistency_read_after_report_write
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    version_before = universe["contest"]["version"]

    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    submit_feed_report(
        contest_id, universe["counties"]["alameda"]["id"], 5, votes,
    )

    contest = get_contest(contest_id)
    assert contest["tabulation_status"] == "REPORTING"
    assert contest["version"] == version_before + 1
