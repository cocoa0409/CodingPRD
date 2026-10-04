"""Corner-design tests: entity creation, defaults, computed fields, identity
reads, and pagination of the core records (PRD §2.2, §2.3, §2.4, §3.1, §3.3).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    alameda_payload,
    assert_contest,
    assert_contest_county_link,
    assert_county,
    assert_election_event,
    assert_feed_source,
    assert_media_customer,
    assert_stringer,
    contra_costa_payload,
    create_contest,
    create_contest_payload,
    create_county,
    create_county_payload,
    create_event,
    create_event_payload,
    create_feed_source_payload,
    create_stringer_payload,
    create_wirelite_basic,
    make_customer_headers,
    marin_payload,
    reset_clock_to_setup,
    setup_standard_universe,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_event_create_returns_posture_setup_and_envelope_meta(api):
    """PRD §3.1: "A new event begins in posture `SETUP`."
    PRD §3.1: "The event's `stringer_selection_mode`, either `CAREER` or
    `RECENT_FORM`, chooses which reliability variant the assignment auto-selector
    of §3.3 ranks by, and it defaults to `CAREER` when omitted."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.4: "All notions of "now" — window checks, timestamp stamping, delivery
    dating — read a server-side logical clock."

    Design: Corner/entities/event_create_returns_posture_setup_and_envelope_meta
    """
    reset_clock_to_setup()
    resp = api.create_event(create_event_payload(), TEST_USERS["admin_headers"])
    data = validate_success(resp, 201)
    assert_election_event(data)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert data["posture"] == "SETUP"
    assert data["stringer_selection_mode"] == "CAREER"
    assert data["created_at"].startswith("2026-10-15T00:00:00")


def test_contest_created_with_zeroed_computed_fields(api):
    """PRD §3.1: "A new contest starts with `tabulation_status` `AWAITING` and
    `call_status` `UNCALLED`, and its rollup fields `reported_precincts`,
    `total_votes`, `margin_pct`, and `outstanding_estimate` read as zero."
    PRD §3.1: "`seats` — the number of winners the contest elects, at least 1 and
    defaulting to 1."

    Design: Corner/entities/contest_created_with_zeroed_computed_fields
    """
    reset_clock_to_setup()
    event = create_event()
    resp = api.create_contest(
        event["id"], create_contest_payload(), TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, 201)
    assert_contest(data)
    assert data["seats"] == 1
    assert data["tabulation_status"] == "AWAITING"
    assert data["call_status"] == "UNCALLED"
    assert data["reported_precincts"] == 0
    assert data["total_votes"] == 0
    assert data["margin_pct"] == 0.0
    assert data["outstanding_estimate"] == 0
    assert data["called_candidate_id"] is None


def test_county_create_applies_nullable_defaults(api):
    """PRD §3.1: "Two optional baselines refine the desk's picture:
    `survey_turnout_estimate`, a survey-based turnout estimate for election night
    that may be null, and `historical_dem_share`, the historical two-party DEM
    share as a fraction between 0 and 1, also nullable"
    PRD §3.1: "A county exposes two computed fields from the outset,
    `reported_precincts` and `status`, initially zero and `PENDING` respectively
    (§3.5)."

    Design: Corner/entities/county_create_applies_nullable_defaults
    """
    reset_clock_to_setup()
    event = create_event()
    alameda = create_county(event["id"], alameda_payload())
    contra_costa = create_county(event["id"], contra_costa_payload())
    assert_county(alameda)
    assert_county(contra_costa)
    assert alameda["survey_turnout_estimate"] == 8000
    assert alameda["historical_dem_share"] == 0.6
    assert contra_costa["survey_turnout_estimate"] is None
    assert contra_costa["historical_dem_share"] is None
    assert contra_costa["status"] == "PENDING"
    assert contra_costa["reported_precincts"] == 0


def test_county_create_missing_required_returns_invalid_request(api):
    """PRD §2.9: "Payload shape on every endpoint: required fields present, enum
    values in range, integer bounds respected (`expected_precincts` at least 1,
    vote figures non-negative, `allocated_stringer_hours` at least 1,
    `candidate_votes` non-empty, `state_codes` and `licensed_states` non-empty),
    else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/county_create_missing_required_returns_invalid_request
    """
    reset_clock_to_setup()
    event = create_event()
    payload = marin_payload()
    del payload["expected_precincts"]
    resp = api.create_county(event["id"], payload, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    _rows, meta = validate_paginated(
        api.list_counties(event["id"], TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 0


def test_contest_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "Path identifiers resolve left to right, and every referenced id
    must exist. The first unresolved segment determines the not-found error:
    `ERR_EVENT_NOT_FOUND` for the event, then `ERR_CONTEST_NOT_FOUND` or
    `ERR_COUNTY_NOT_FOUND` at the second tier"

    Design: Corner/entities/contest_get_unknown_id_returns_not_found
    """
    reset_clock_to_setup()
    create_event()
    resp = api.get_contest(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTEST_NOT_FOUND)


def test_stringer_create_initializes_counters_and_both_scores(api):
    """PRD §3.3: "The roster entry accumulates three lifetime counters —
    `no_show_count`, `accepted_report_count`, and `voided_report_count`, each
    starting at 0 — and two reliability scores, `reliability_career` and
    `reliability_recent_form`, each starting at 100."

    Design: Corner/entities/stringer_create_initializes_counters_and_both_scores
    """
    resp = api.create_stringer(
        create_stringer_payload(), TEST_USERS["coordinator_headers"],
    )
    data = validate_success(resp, 201)
    assert_stringer(data)
    assert data["no_show_count"] == 0
    assert data["accepted_report_count"] == 0
    assert data["voided_report_count"] == 0
    assert data["reliability_career"] == 100
    assert data["reliability_recent_form"] == 100


def test_customer_create_and_self_read_roundtrip(api):
    """PRD §3.8: "A customer may read their own record, their own delivery feed,
    and their own invoices — with `X-User-ID` equal to the customer's `id` — and
    an administrator may read any customer's"
    PRD §3.8: "Media customers are registered by an `ElectionOpsAdmin` with a
    `customer_name`, a `license_tier` of `BASIC`, `STANDARD`, or `PREMIUM`, and a
    non-empty `licensed_states` array of two-letter state codes."

    Design: Corner/entities/customer_create_and_self_read_roundtrip
    """
    customer = create_wirelite_basic()
    resp = api.get_media_customer(
        customer["id"], make_customer_headers(customer["id"]),
    )
    data = validate_success(resp)
    assert_media_customer(data)
    assert data["id"] == customer["id"]
    assert data["license_tier"] == "BASIC"
    assert data["licensed_states"] == ["CA"]


def test_contests_list_paginates_total_count_and_has_more(api):
    """PRD §2.3: "All list endpoints accept the optional query parameters `limit`
    and `offset`."
    PRD §2.3: "List responses report the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/contests_list_paginates_total_count_and_has_more
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    main = universe["contest"]
    governor = create_contest(
        event_id, office_name="Governor", contest_type="STATE",
    )

    page1, meta1 = validate_paginated(
        api.list_contests(
            event_id, TEST_USERS["admin_headers"],
            params={"limit": 1, "offset": 0},
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_contests(
            event_id, TEST_USERS["admin_headers"],
            params={"limit": 1, "offset": 1},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    assert {page1[0]["id"], page2[0]["id"]} == {main["id"], governor["id"]}


def test_county_link_is_immutable_without_version(api):
    """PRD §2.4: "County links, candidates, feed sources, result deliveries, and
    media invoices carry only `id` and `created_at`: both `updated_at` and
    `version` are absent on those five resource types."

    Design: Corner/entities/county_link_is_immutable_without_version
    """
    universe = setup_standard_universe(
        advance_to="SETUP", link_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    county_id = universe["counties"]["contra_costa"]["id"]
    resp = api.create_county_link(contest_id, county_id, TEST_USERS["admin_headers"])
    data = validate_success(resp, 201)
    assert_contest_county_link(data)
    assert data["contest_id"] == contest_id
    assert data["county_id"] == county_id
    assert "version" not in data
    assert "updated_at" not in data


def test_feed_create_defaults_priority_tier_secondary(api):
    """PRD §3.1: "a `priority_tier` of `PRIMARY` or `SECONDARY`, defaulting to
    `SECONDARY`, which serves purely as a desk priority label and gates nothing."

    Design: Corner/entities/feed_create_defaults_priority_tier_secondary
    """
    universe = setup_standard_universe(advance_to="SETUP", with_feed=False)
    event_id = universe["event"]["id"]
    resp = api.create_feed_source(
        event_id, create_feed_source_payload(), TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, 201)
    assert_feed_source(data)
    assert data["priority_tier"] == "SECONDARY"
    rows, meta = validate_paginated(
        api.list_feed_sources(event_id, TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == data["id"]
