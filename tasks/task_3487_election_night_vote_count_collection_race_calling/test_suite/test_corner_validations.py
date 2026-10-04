"""Corner-design tests: the §2.9 validation ladder — auth, role admission,
posture gates, intake bounds, membership, collection authority, segregation of
duties, and license gating (PRD §2.1, §2.5, §2.9, §3.3, §3.4, §3.6, §3.8).
"""
import pytest

from test_helpers import (
    ANALYST_NINA_ID,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_to_candidates_locked,
    advance_to_live,
    create_assignment,
    create_candidate,
    create_contest,
    create_vote_report_payload,
    create_wirelite_basic,
    get_contest,
    get_contest_version,
    link_county,
    make_analyst_headers,
    make_chief_headers,
    make_customer_headers,
    make_stringer_headers,
    marin_payload,
    patch_contest,
    setup_proposed_call,
    setup_standard_universe,
    setup_universe_with_reports,
    submit_feed_report,
    validate_error,
    validate_paginated,
    washoe_nv_payload,
    create_stringer,
)


def test_request_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or blank, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    resp = api.get_contest(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_stringer_cannot_create_counties(api):
    """PRD §2.1: "If the supplied role is not among the roles an endpoint
    declares in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/validations/stringer_cannot_create_counties
    """
    universe = setup_standard_universe(advance_to="SETUP")
    sally = create_stringer()
    resp = api.create_county(
        universe["event"]["id"], marin_payload(),
        make_stringer_headers(sally["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_posture_forbids_county_creation_after_lock(api):
    """PRD §2.5: "Registering counties, contests, candidates, county links, and
    feed sources, and editing contest configuration, require `SETUP`."
    PRD §2.5: "Any operation attempted in a posture that does not admit it is
    rejected with `ERR_POSTURE_FORBIDS` (HTTP 409)."

    Design: Corner/validations/posture_forbids_county_creation_after_lock
    """
    universe = setup_standard_universe(advance_to="CANDIDATES_LOCKED")
    event_id = universe["event"]["id"]
    resp = api.create_county(
        event_id, marin_payload(), TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)
    _rows, meta = validate_paginated(
        api.list_counties(event_id, TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 2


def test_patch_contest_after_lock_forbidden(api):
    """PRD §3.1: "Before candidate lock the administrator may still edit the
    contest's `office_name` and `seats`"
    PRD §2.5: "Registering counties, contests, candidates, county links, and
    feed sources, and editing contest configuration, require `SETUP`."
    PRD §2.5: "Any operation attempted in a posture that does not admit it is
    rejected with `ERR_POSTURE_FORBIDS` (HTTP 409)."

    Design: Corner/validations/patch_contest_after_lock_forbidden
    """
    universe = setup_standard_universe(advance_to="SETUP")
    contest_id = universe["contest"]["id"]
    patched = patch_contest(contest_id, office_name="United States Senator")
    assert patched["office_name"] == "United States Senator"

    advance_to_candidates_locked(universe["event"]["id"])
    resp = api.patch_contest(
        contest_id, {"office_name": "US Senate (renamed late)"},
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)
    assert get_contest(contest_id)["office_name"] == "United States Senator"


def test_precincts_above_expected_rejected(api):
    """PRD §3.4: "the `precincts_reporting` count, at least 1 and never more than
    the county's `expected_precincts` (else `ERR_PRECINCTS_EXCEED_EXPECTED`)"
    PRD §3.4: "three intake failures are hard rejections rather than flags: a
    precinct count above the county's expectation, a candidate identifier foreign
    to the contest, and negative vote figures."

    Design: Corner/validations/precincts_above_expected_rejected
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    votes = {
        universe["candidates"]["wanda"]["id"]: 6000,
        universe["candidates"]["tom"]["id"]: 4000,
    }
    payload = create_vote_report_payload(
        universe["counties"]["alameda"]["id"], 11, votes,
        get_contest_version(contest_id), source="FEED",
    )
    resp = api.create_vote_report(
        contest_id, payload, TEST_USERS["feed_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PRECINCTS_EXCEED_EXPECTED)
    _rows, meta = validate_paginated(
        api.list_contest_vote_reports(contest_id, TEST_USERS["clerk_headers"])
    )
    assert meta["total_count"] == 0


def test_report_with_foreign_candidate_rejected(api):
    """PRD §3.4: "every `candidate_id` must belong to the contest (else
    `ERR_CANDIDATE_NOT_IN_CONTEST`)"

    Design: Corner/validations/report_with_foreign_candidate_rejected
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    governor = create_contest(event_id, office_name="Governor", contest_type="STATE")
    link_county(governor["id"], universe["counties"]["contra_costa"]["id"])
    gail = create_candidate(governor["id"], "Gail Govern", "DEM")
    create_candidate(governor["id"], "Ron Rival", "REP")
    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])

    contest_id = universe["contest"]["id"]
    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        gail["id"]: 3000,
    }
    payload = create_vote_report_payload(
        universe["counties"]["alameda"]["id"], 5, votes,
        get_contest_version(contest_id), source="FEED",
    )
    resp = api.create_vote_report(
        contest_id, payload, TEST_USERS["feed_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_IN_CONTEST)


def test_report_for_unlinked_county_rejected(api):
    """PRD §3.4: "Each report names the reporting `county_id`, which must be
    linked to the contest through its geography (else
    `ERR_COUNTY_NOT_IN_CONTEST`)"

    Design: Corner/validations/report_for_unlinked_county_rejected
    """
    universe = setup_standard_universe(
        advance_to="LIVE", link_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    votes = {
        universe["candidates"]["wanda"]["id"]: 1300,
        universe["candidates"]["tom"]["id"]: 1200,
    }
    payload = create_vote_report_payload(
        universe["counties"]["contra_costa"]["id"], 2, votes,
        get_contest_version(contest_id), source="FEED",
    )
    resp = api.create_vote_report(
        contest_id, payload, TEST_USERS["feed_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_COUNTY_NOT_IN_CONTEST)


def test_stringer_report_without_active_assignment_rejected(api):
    """PRD §3.4: "A `STRINGER` report requires an `ACTIVE` assignment covering
    exactly this stringer — identified by `X-User-ID` — this county, and this
    event; without one the submission is rejected with
    `ERR_STRINGER_NOT_DEPLOYED`"

    Design: Corner/validations/stringer_report_without_active_assignment_rejected
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    contest_id = universe["contest"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    sally = create_stringer()
    create_assignment(event_id, alameda_id, stringer_id=sally["id"])
    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])

    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    payload = create_vote_report_payload(
        alameda_id, 5, votes, get_contest_version(contest_id),
        source="STRINGER",
    )
    resp = api.create_vote_report(
        contest_id, payload, make_stringer_headers(sally["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STRINGER_NOT_DEPLOYED)


def test_feed_report_without_state_coverage_rejected(api):
    """PRD §3.4: "A `FEED` report requires a feed source of the event whose
    `state_codes` contains the county's `state_code`; without coverage it is
    rejected with `ERR_FEED_COVERAGE_MISSING`"

    Design: Corner/validations/feed_report_without_state_coverage_rejected
    """
    # PRD §3.1 ("every linked county shares the contest's `state_code`") bars
    # linking NV Washoe into the CA contest, and §3.4's guard order evaluates
    # membership before collection authority — so the coverage rejection is
    # only reachable with Washoe linked into an NV contest of the same event
    # while the event's only feed source (StateWire CA) covers CA alone.
    universe = setup_standard_universe(
        advance_to="SETUP",
        extra_counties=[("washoe", washoe_nv_payload())],
        link_extra_counties=False,
    )
    nv_contest = create_contest(
        universe["event"]["id"],
        office_name="NV Governor", state_code="NV", contest_type="STATE",
    )
    link_county(nv_contest["id"], universe["counties"]["washoe"]["id"])
    nancy = create_candidate(nv_contest["id"], "Nancy North", "DEM")
    randy = create_candidate(nv_contest["id"], "Randy South", "REP")
    advance_to_candidates_locked(universe["event"]["id"])
    advance_to_live(universe["event"]["id"], universe["event"]["event_date"])

    votes = {nancy["id"]: 1000, randy["id"]: 900}
    payload = create_vote_report_payload(
        universe["counties"]["washoe"]["id"], 2, votes,
        get_contest_version(nv_contest["id"]), source="FEED",
    )
    resp = api.create_vote_report(
        nv_contest["id"], payload, TEST_USERS["feed_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FEED_COVERAGE_MISSING)


def test_publisher_equal_to_proposer_rejected(api):
    """PRD §2.1: "the decision desk chief may never publish a call whose
    `proposed_by` equals the chief's own `X-User-ID`."
    PRD §3.6: "then segregation of duties, under which a chief whose `X-User-ID`
    equals the call's `proposed_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)"

    Design: Corner/validations/publisher_equal_to_proposer_rejected
    """
    universe = setup_proposed_call()
    contest_id = universe["contest"]["id"]
    call = universe["call"]

    resp = api.decide_call(
        call["id"], "PUBLISH", make_chief_headers(ANALYST_NINA_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    rows, _meta = validate_paginated(
        api.list_calls(contest_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[call["id"]]["status"] == "PROPOSED"


def test_basic_customer_querying_call_content_forbidden(api):
    """PRD §3.8: "A `BASIC` customer may not query the `CALL` or `CALL_CREDIT`
    content types at all — the attempt is rejected with
    `ERR_LICENSE_TIER_FORBIDS` (HTTP 403)."

    Design: Corner/validations/basic_customer_querying_call_content_forbidden
    """
    customer = create_wirelite_basic()
    resp = api.list_customer_deliveries(
        customer["id"], make_customer_headers(customer["id"]),
        params={"content_type": "CALL"},
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_TIER_FORBIDS)

    _rows, meta = validate_paginated(
        api.list_customer_deliveries(
            customer["id"], make_customer_headers(customer["id"]),
            params={"content_type": "VOTE_UPDATE"},
        )
    )
    assert meta["total_count"] == 0
