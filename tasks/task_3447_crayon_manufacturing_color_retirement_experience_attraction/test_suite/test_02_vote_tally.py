"""Vote intake, weighted tallying, thresholds, and quorum."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_same_instant,
)

ADMIN = fx.ADMIN
CONSUMER = fx.CONSUMER


def test_defaults_applied_when_optional_fields_omitted(api):
    """PRD section 3.7: "an optional `is_charter` flag, defaulting to false".
    PRD section 3.1: "an optional `count` that imports that many identical
    ballots and defaults to 1" and "The response confirms `accepted`, echoes the
    `campaign_id`, and reports the `weight_applied`."

    Design: Corner/entities/defaults_applied_when_optional_fields_omitted
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    session = fx.create_session()
    assert session["is_charter"] is False
    resp = api_client.cast_vote(
        {"campaign_id": camp["id"], "voter_segment": "KIDS", "choice": "YES"}, CONSUMER)
    data = validate_success(resp, 200)
    assert data["accepted"] is True
    assert data["campaign_id"] == camp["id"]
    assert data["weight_applied"] == 1.0
    camps = fx.list_campaigns(color["id"])
    assert camps[0]["turnout_count"] == 1


def test_tally_intro_weights_and_quorum_applied(api):
    """PRD section 3.1: "For `INTRODUCTION`: `KIDS` weigh 1.0, `PARENTS` 1.5,
    `EDUCATORS` 2.0, and `COLLECTORS` 1.2." and "Each accepted ballot adds its
    segment weight to `votes_total_weighted`; `YES` ballots additionally add the
    same weight to `votes_yes_weighted`; and `turnout_count` grows by the raw
    `count`."

    Design: Corner/calculations/tally_intro_weights_and_quorum_applied
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "YES", 10)
    fx.cast_votes(camp["id"], "PARENTS", "YES", 4)
    fx.cast_votes(camp["id"], "PARENTS", "NO", 2)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    tallied = fx.list_campaigns(color["id"])[0]
    assert tallied["votes_yes_weighted"] == 16.0   # 10*1.0 + 4*1.5
    assert tallied["votes_total_weighted"] == 19.0  # + 2*1.5
    assert tallied["turnout_count"] == 16
    assert tallied["outcome"] == "PASSED"  # 16/19 = 0.842 >= 0.55
    assert fx.get_color(color["id"])["status"] == "ACTIVE"


def test_tally_below_quorum_fails_despite_unanimous_yes(api):
    """PRD section 3.1: "The campaign `PASSED` exactly when two conditions both
    hold — `turnout_count` reaches the minimum turnout `MIN_TURNOUT` of 10
    ballots, and the exact ratio is at least the kind's threshold".

    Design: Corner/calculations/tally_below_quorum_fails_despite_unanimous_yes
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "YES", 5)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    tallied = fx.list_campaigns(color["id"])[0]
    assert tallied["outcome"] == "FAILED"
    assert tallied["turnout_count"] == 5
    assert fx.get_color(color["id"])["status"] == "PROPOSED"


def test_vote_with_invalid_segment_or_choice_returns_vote_invalid(api):
    """PRD section 3.1: "an unknown segment, an unknown choice, or a `count`
    below 1 is rejected with `ERR_VOTE_INVALID` (HTTP 422)."

    Design: Corner/validations/vote_with_invalid_segment_or_choice_returns_vote_invalid
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    resp1 = api_client.cast_vote(
        {"campaign_id": camp["id"], "voter_segment": "GRANDPARENTS", "choice": "YES"}, CONSUMER)
    validate_error(resp1, ApiErrorId.ERR_VOTE_INVALID)
    assert resp1.status_code == 422
    resp2 = api_client.cast_vote(
        {"campaign_id": camp["id"], "voter_segment": "KIDS", "choice": "MAYBE"}, CONSUMER)
    validate_error(resp2, ApiErrorId.ERR_VOTE_INVALID)
    assert fx.list_campaigns(color["id"])[0]["turnout_count"] == 0


def test_vote_before_open_or_after_tally_returns_campaign_not_open(api):
    """PRD section 3.1: "A ballot cast on a campaign that is `SCHEDULED` or
    `TALLYED` is rejected with `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409)".

    Design: Corner/errors/vote_before_open_or_after_tally_returns_campaign_not_open
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    resp1 = api_client.cast_vote(
        {"campaign_id": camp["id"], "voter_segment": "KIDS", "choice": "YES"}, CONSUMER)
    validate_error(resp1, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)
    assert resp1.status_code == 409
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "YES", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    resp2 = api_client.cast_vote(
        {"campaign_id": camp["id"], "voter_segment": "KIDS", "choice": "YES"}, CONSUMER)
    validate_error(resp2, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)
    assert fx.list_campaigns(color["id"])[0]["turnout_count"] == 20


def test_tally_identical_ballots_pass_introduction(api):
    """PRD section 3.1: "Because the weight tables and thresholds differ, an
    identical set of ballots can pass an introduction yet fail a retirement." —
    the introduction leg: 10 KIDS yes + 1 COLLECTORS yes + 4 COLLECTORS no
    yields yes 11.2 of 16.0 (0.70 >= 0.55), PASSED.

    Design: Difficulty/dual_variant_calc/vote_tally_identical_ballots_pass_introduction_but_fail_retirement
    """
    fx.reset_clock()
    c1 = fx.create_color("Mango Tango", "#FF8244")
    k1 = fx.open_campaign(c1["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(k1["id"], "KIDS", "YES", 10)
    fx.cast_votes(k1["id"], "COLLECTORS", "YES", 1)
    fx.cast_votes(k1["id"], "COLLECTORS", "NO", 4)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    tallied = fx.list_campaigns(c1["id"])[0]
    assert tallied["outcome"] == "PASSED"
    assert tallied["votes_yes_weighted"] == 11.2
    assert tallied["votes_total_weighted"] == 16.0
    assert tallied["turnout_count"] == 15
    assert fx.get_color(c1["id"])["status"] == "ACTIVE"


def test_tally_identical_ballots_fail_retirement(api):
    """PRD section 3.1: "For `RETIREMENT`: `KIDS` weigh 1.0, `PARENTS` 1.0,
    `EDUCATORS` 1.5, and `COLLECTORS` 2.5." and "a failed retirement returns the
    color to `ACTIVE`" — the identical ballot multiset (10 KIDS yes, 1
    COLLECTORS yes, 4 COLLECTORS no) yields yes 12.5 of 22.5 (0.5556 < 0.60),
    FAILED.

    Design: Difficulty/dual_variant_calc/vote_tally_identical_ballots_pass_introduction_but_fail_retirement
    """
    fx.reset_clock()
    c2 = fx.make_active_color("Retro Mauve", "#915C83")
    k3 = fx.open_campaign(c2["id"], "RETIREMENT",
                          "2026-10-01T00:00:00Z", "2026-10-15T23:59:59Z")
    fx.set_clock("2026-10-02T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(k3["id"], "KIDS", "YES", 10)
    fx.cast_votes(k3["id"], "COLLECTORS", "YES", 1)
    fx.cast_votes(k3["id"], "COLLECTORS", "NO", 4)
    fx.set_clock("2026-10-16T00:00:00Z")
    fx.run_epoch()
    camps = fx.list_campaigns(c2["id"])
    retirement = camps[1]
    assert retirement["outcome"] == "FAILED"
    assert retirement["votes_yes_weighted"] == 12.5
    assert retirement["votes_total_weighted"] == 22.5
    assert retirement["turnout_count"] == 15
    assert fx.get_color(c2["id"])["status"] == "ACTIVE"


def test_tally_ratio_exactly_at_threshold_passes(api):
    """PRD section 3.1: "The threshold comparison is inclusive, so a ratio
    landing exactly on the threshold passes." — 11 KIDS yes vs 9 KIDS no gives
    exactly 11/20 = 0.55 = INTRO_THRESHOLD.

    Design: Difficulty/boundary_precision_check/tally_ratio_exactly_at_threshold_passes
    """
    fx.reset_clock()
    color = fx.create_color("Boundary Blue", "#0F7B8A")
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "YES", 11)
    fx.cast_votes(camp["id"], "KIDS", "NO", 9)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    tallied = fx.list_campaigns(color["id"])[0]
    assert tallied["outcome"] == "PASSED"
    assert tallied["votes_yes_weighted"] == 11.0
    assert tallied["votes_total_weighted"] == 20.0
    assert tallied["turnout_count"] == 20


def test_tally_at_threshold_activates_and_stamps_introduced_on(api):
    """PRD section 3.1: "A passed introduction moves the color from `IN_VOTE` to
    `ACTIVE` and stamps `introduced_on` with the campaign's `closes_on`".

    Design: Difficulty/boundary_precision_check/tally_ratio_exactly_at_threshold_passes
    """
    fx.reset_clock()
    color = fx.create_color("Boundary Blue", "#0F7B8A")
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "YES", 11)
    fx.cast_votes(camp["id"], "KIDS", "NO", 9)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    final = fx.get_color(color["id"])
    assert final["status"] == "ACTIVE"
    assert_same_instant(final["introduced_on"], "2026-09-20T23:59:59Z", "introduced_on")
