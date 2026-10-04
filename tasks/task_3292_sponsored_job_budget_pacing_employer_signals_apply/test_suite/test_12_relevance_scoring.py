"""Relevance scoring for the on-demand matches view.

The relevance score sums a keyword component, a location component and a
freshness component, and only postings still in play are ever ranked.
"""
import json

import pytest

from test_helpers import (
    api_client, validate_paginated, get_success_data, TEST_USERS,
    set_clock, create_employer, create_seeker, create_posting, get_posting,
    assert_relevance_score_shape,
    KEYWORD_FULL, LOCATION_EXACT, FRESHNESS_FRESH, RELEVANCE_MAX,
)

ADMIN = TEST_USERS["admin_headers"]


def test_full_keyword_and_location_match_scores_the_maximum(api):
    """PRD §3.9: "The keyword component contributes 40 points when the
    subscription's keywords match the posting's title fully, 20 points when they
    match partially, and 0 points when they do not match."
    PRD §3.9: "The location component contributes 35 points when the seeker's
    location matches the posting's location exactly ... The freshness component
    contributes 25 points when the posting's `current_freshness` is `FRESH`."
    PRD §3.9: "The score is the sum of the three and is therefore an integer with
    a maximum of 100 for a fully matching, fresh posting."

    Design: Corner/calculations/relevance_score_full_match_scores_hundred
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Match Co", domain="match.example")
    seeker = create_seeker(full_name="Match Seeker", location="Austin, TX")
    posting = create_posting(employer, title="Platform Engineer",
                             location="Austin, TX")

    data, meta = validate_paginated(api.get_seeker_matches(
        seeker["id"], ADMIN, params={"keywords": "engineer", "location": "Austin, TX"}))

    assert meta["total_count"] == 1
    match = data[0]
    assert posting["id"] in json.dumps(match), "the match row must identify the posting"
    assert match["relevance_score"] == KEYWORD_FULL + LOCATION_EXACT + FRESHNESS_FRESH
    assert match["relevance_score"] == RELEVANCE_MAX
    assert_relevance_score_shape(match)


def test_expired_posting_drops_out_of_the_match_pool(api):
    """PRD §3.9: "Only postings whose `state` is `ACTIVE` or `STALE` are ever
    ranked — expired and suspended postings are excluded from the pool entirely,
    so they can never be matched or delivered regardless of how well they would
    score."

    Design: Corner/calculations/relevance_match_excludes_expired_posting
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Filter Co", domain="flt.example")
    seeker = create_seeker(full_name="Filter Seeker", location="Austin, TX")
    posting = create_posting(employer, title="Filter Engineer",
                             location="Austin, TX")

    before, before_meta = validate_paginated(api.get_seeker_matches(
        seeker["id"], ADMIN, params={"keywords": "engineer", "location": "Austin, TX"}))
    assert before_meta["total_count"] == 1

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))
    assert get_posting(posting["id"])["state"] == "EXPIRED"

    after, after_meta = validate_paginated(api.get_seeker_matches(
        seeker["id"], ADMIN, params={"keywords": "engineer", "location": "Austin, TX"}))
    assert after_meta["total_count"] == 0
    assert all(row.get("id") != posting["id"] for row in after)