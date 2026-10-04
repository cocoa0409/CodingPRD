"""Interval occupancy of the departing home's marketing slot (PRD section 3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, setup_funded_program, occupy_new_home, complete_repairs, draft_listing,
    get_program, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def _live_listing_scenario(api):
    """A funded program occupying the new home whose first listing is live."""
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "34 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    occupy_new_home(sc["program"]["id"], sc["homeowner"]["id"])
    complete_repairs(sc["departing"]["id"], visits=3)
    l1 = draft_listing(sc["departing"]["id"], sc["program"]["id"], list_price_cents=44_000_000)
    live = validate_success(api.go_live_listing(l1["id"], COORD), 200)
    assert live["status"] == "LIVE", "Setup failed: first listing did not go live"
    sc["listing_live"] = live
    return sc


def test_second_listing_may_be_drafted_while_the_first_is_live(api):
    """PRD section 3.6: "A new listing may perfectly well be drafted while an older one is
    still `LIVE`; what is forbidden is going live on the second one before the first has
    closed."

    Design: Difficulty/resource_temporal_overlap/listing_closed_interval_slot_reuse
    """
    reset_clock()
    sc = _live_listing_scenario(api)
    l2 = draft_listing(sc["departing"]["id"], sc["program"]["id"], list_price_cents=43_000_000)
    assert l2["id"] != sc["listing_live"]["id"]
    assert l2["status"] == "DRAFT", "drafting a second listing is permitted"
    assert sc["listing_live"]["status"] == "LIVE", "the older listing is undisturbed"


def test_going_live_on_a_second_listing_overlaps_the_live_slot(api):
    """PRD section 3.6: "Overlapping go-lives on the same property are refused with
    `ERR_LISTING_SLOT_OVERLAP`."

    PRD section 3.6: "Only one listing may be marketed at a time, and the rule is stated as
    an interval, not a flag."

    Design: Difficulty/resource_temporal_overlap/listing_closed_interval_slot_reuse
    """
    reset_clock()
    sc = _live_listing_scenario(api)
    l2 = draft_listing(sc["departing"]["id"], sc["program"]["id"], list_price_cents=43_000_000)

    res = api.go_live_listing(l2["id"], COORD)
    validate_error(res, ApiErrorId.ERR_LISTING_SLOT_OVERLAP.value, expected_status=409)
    still = validate_success(api.get_listing(l2["id"], COORD), 200)
    assert still["status"] == "DRAFT", "the refused go-live left the second listing drafted"