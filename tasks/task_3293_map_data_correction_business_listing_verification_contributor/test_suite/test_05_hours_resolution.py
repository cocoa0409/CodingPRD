"""Hours observation conflict resolution tests."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_region,
    make_contributor,
    make_hours_observation,
    make_listing,
    make_region,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MOD1 = TEST_USERS["moderator_headers"]


def test_hours_winner_promoted_contributor_loses_to_stale_feed(api):
    """PRD §3.7: "Source priority dominates, scaled by 100: an owner
    observation is worth 5, a third-party feed 4, a web crawl 3, imagery 2,
    and a contributor 1 — with one conditional branch: a contributor
    observation whose author holds level `EXPERT` or `MASTER` is promoted to
    priority 3."
    PRD §3.7: "Recency adds up to 30 points: the observation's age in whole
    days (fractions discarded) is subtracted from 30, floored at zero.
    Corroboration adds ten points per corroborating observation, capped at
    five corroborations."
    PRD §3.7: "The highest score wins and its `accepted` flag becomes true;
    every other observation in the set is marked unaccepted."

    Design: Difficulty/combinatorial_formula/hours_winner_mode_a_promoted_contributor_beats_feed
    """
    region = make_region(name="R3")
    listing = make_listing(region["id"], name="Shop Three")
    expert = make_contributor(region["id"], display_name="C4", email="c4@x.com",
                              seed_points=1000)
    assert expert["level"] == "EXPERT"

    set_clock("2026-09-01T00:00:00Z")
    feed = make_hours_observation(listing["id"], "THIRD_PARTY_FEED",
                                  day_mask="1111100", open_time="09:00",
                                  close_time="17:00")
    set_clock("2026-10-11T00:00:00Z")
    promoted = make_hours_observation(listing["id"], "CONTRIBUTOR",
                                      day_mask="1111100", open_time="08:00",
                                      close_time="18:00",
                                      as_contributor_id=expert["id"])
    # Five identical corroborating observations for the promoted one.
    for _ in range(5):
        make_hours_observation(listing["id"], "CONTRIBUTOR", day_mask="1111100",
                               open_time="08:00", close_time="18:00",
                               as_contributor_id=expert["id"])

    resp = api.resolve_listing_hours(listing["id"], {"day_mask": "1111100"}, MOD1)
    outcome = validate_success(resp)
    # Feed: 4*100 + 0 recency + 0 corroboration = 400.
    # Promoted contributor: 3*100 + 30 recency + 50 corroboration (capped) = 380.
    assert outcome["accepted_observation_id"] == feed["id"], (
        f"feed score 400 beats promoted contributor score 380, "
        f"got winner {outcome['accepted_observation_id']}"
    )
    assert outcome["accepted_count"] == 1

    feed_read = validate_success(api.get_hours_observation(feed["id"], ADMIN))
    promoted_read = validate_success(api.get_hours_observation(promoted["id"], ADMIN))
    assert feed_read["accepted"] is True
    assert promoted_read["accepted"] is False


def test_hours_winner_recency_picks_fresh_promoted_contributor(api):
    """PRD §3.7: "Source priority dominates, scaled by 100: an owner
    observation is worth 5, a third-party feed 4, a web crawl 3, imagery 2,
    and a contributor 1 — with one conditional branch: a contributor
    observation whose author holds level `EXPERT` or `MASTER` is promoted to
    priority 3."
    PRD §3.7: "Recency adds up to 30 points: the observation's age in whole
    days (fractions discarded) is subtracted from 30, floored at zero.
    Corroboration adds ten points per corroborating observation, capped at
    five corroborations."
    PRD §3.7: "The highest score wins and its `accepted` flag becomes true;
    every other observation in the set is marked unaccepted."

    Design: Difficulty/combinatorial_formula/hours_winner_mode_a_promoted_contributor_beats_feed
    """
    region = make_region(name="R3b")
    listing = make_listing(region["id"], name="Shop Three B")
    expert = make_contributor(region["id"], display_name="C4b", email="c4b@x.com",
                              seed_points=1000)
    assert expert["level"] == "EXPERT"

    set_clock("2026-09-01T00:00:00Z")
    crawl = make_hours_observation(listing["id"], "WEB_CRAWL", day_mask="1111100",
                                   open_time="09:00", close_time="17:00")
    set_clock("2026-10-11T00:00:00Z")
    promoted = make_hours_observation(listing["id"], "CONTRIBUTOR",
                                      day_mask="1111100", open_time="08:00",
                                      close_time="18:00",
                                      as_contributor_id=expert["id"])

    resp = api.resolve_listing_hours(listing["id"], {"day_mask": "1111100"}, MOD1)
    outcome = validate_success(resp)
    # Crawl: 3*100 + 0 + 0 = 300. Promoted contributor: 3*100 + 30 + 0 = 330.
    assert outcome["accepted_observation_id"] == promoted["id"], (
        f"promoted contributor score 330 beats stale crawl score 300, "
        f"got winner {outcome['accepted_observation_id']}"
    )
    assert outcome["accepted_count"] == 1
    crawl_read = validate_success(api.get_hours_observation(crawl["id"], ADMIN))
    promoted_read = validate_success(api.get_hours_observation(promoted["id"], ADMIN))
    assert promoted_read["accepted"] is True
    assert crawl_read["accepted"] is False


def test_hours_resolve_empty_candidate_set_is_noop(api):
    """PRD §3.7: "When a listing and day mask have no observations at all,
    resolution is not an error — it simply reports an empty accepted list."

    Design: Difficulty/boundary_precision_check/contributor_level_exactly_250_is_trusted_empty_resolve_noop
    """
    region = make_region(name="R12c")
    listing = make_listing(region["id"], name="Depot Twelve C")
    resp = api.resolve_listing_hours(listing["id"], {"day_mask": "1111111"}, MOD1)
    outcome = validate_success(resp)
    assert outcome["accepted_count"] == 0, (
        f"empty candidate set must report accepted_count 0, "
        f"got {outcome['accepted_count']}"
    )
