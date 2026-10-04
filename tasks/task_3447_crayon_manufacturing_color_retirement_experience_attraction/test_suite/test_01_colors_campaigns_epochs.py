"""Color catalog, vote campaigns, and the operations epoch."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_color, assert_vote_campaign, assert_same_instant,
)

ADMIN = fx.ADMIN
CONSUMER = fx.CONSUMER


def test_color_create_returns_201_defaults_and_envelope(api):
    """PRD section 3.1: "A new color starts in `PROPOSED` with `version` 1."
    PRD section 3.1: "an optional `is_core_curriculum` flag that defaults to false."
    PRD section 4: "Successful resource creation returns HTTP 201 with the new
    resource in `data`; reads, transitions, decisions, result recordings,
    ballots, the clock set, and the epoch checkpoint return HTTP 200."

    Design: Corner/entities/color_create_returns_201_defaults_and_envelope
    """
    fx.reset_clock()
    resp = api_client.create_color({"name": "Cerulean", "hex_code": "#02A4D3"}, ADMIN)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")
    data = body["data"]
    assert_color(data)
    assert data["status"] == "PROPOSED"
    assert data["version"] == 1
    assert data["is_core_curriculum"] is False
    assert data["introduced_on"] is None
    assert data["retired_on"] is None
    assert data["archive_after_date"] is None


def test_color_get_roundtrips_stored_fields_unchanged(api):
    """PRD section 3.1: "The catalog begins when a `PlatformAdmin` registers a
    **color** with a display `name`, an RGB `hex_code` such as `#02A4D3`, and an
    optional `is_core_curriculum` flag that defaults to false."

    Design: Corner/entities/color_get_roundtrips_stored_fields_unchanged
    """
    fx.reset_clock()
    color = fx.create_color("Atomic Tangerine", "#FF9966", True)
    resp = api_client.get_color(color["id"], fx.FORMULATOR)
    data = validate_success(resp, 200)
    assert data["name"] == "Atomic Tangerine"
    assert data["hex_code"] == "#FF9966"
    assert data["is_core_curriculum"] is True
    assert data["status"] == "PROPOSED"


def test_success_envelope_includes_meta_request_id(api):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`." and "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/endpoints/success_envelope_includes_meta_request_id
    """
    fx.reset_clock()
    resp = api_client.create_color({"name": "Cerulean", "hex_code": "#02A4D3"}, ADMIN)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"]


def test_immediate_consistency_read_after_write_shows_mutation(api):
    """PRD section 3.1: "When the campaign is accepted, it is created in
    `SCHEDULED` and the color flips into its voting posture: `PROPOSED` to
    `IN_VOTE` for an introduction, or `ACTIVE` to `RETIRE_VOTE` for a
    retirement."

    Design: Corner/consistency_model/immediate_consistency_read_after_write_shows_mutation
    """
    fx.reset_clock()
    color = fx.create_color()
    fx.open_campaign(color["id"])
    data = get_success_data(api_client.get_color(color["id"], ADMIN))
    assert data["status"] == "IN_VOTE", (
        f"the read immediately after campaign creation must show IN_VOTE, got {data['status']}")


def test_campaign_created_in_scheduled_initial_state(api):
    """PRD section 3.1: "A campaign carries the system's running ballot tallies:
    `votes_yes_weighted` and `votes_total_weighted`, both starting at 0, and
    `turnout_count`, the raw ballot count, also starting at 0. Its `outcome` —
    `PASSED` or `FAILED` — and its `tallied_at` instant remain null until the
    campaign is `TALLYED`."

    Design: Corner/state_machines/campaign_created_in_scheduled_initial_state
    """
    fx.reset_clock()
    color = fx.create_color()
    resp = api_client.create_vote_campaign(
        color["id"],
        {"kind": "INTRODUCTION", "opens_on": "2026-09-05T00:00:00Z",
         "closes_on": "2026-09-20T23:59:59Z"},
        ADMIN)
    data = validate_success(resp, 201)
    assert_vote_campaign(data)
    assert data["status"] == "SCHEDULED"
    assert data["votes_yes_weighted"] == 0
    assert data["votes_total_weighted"] == 0
    assert data["turnout_count"] == 0
    assert data["outcome"] is None
    assert data["tallied_at"] is None
    color_now = get_success_data(api_client.get_color(color["id"], ADMIN))
    assert color_now["status"] == "IN_VOTE"


def test_campaign_create_with_closes_before_opens_returns_date_order(api):
    """PRD section 3.1: "The `closes_on` instant must be strictly after
    `opens_on`, else `ERR_DATE_ORDER` (HTTP 422)."

    Design: Corner/validations/campaign_create_with_closes_before_opens_returns_date_order
    """
    fx.reset_clock()
    color = fx.create_color()
    resp = api_client.create_vote_campaign(
        color["id"],
        {"kind": "INTRODUCTION", "opens_on": "2026-09-10T00:00:00Z",
         "closes_on": "2026-09-01T00:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DATE_ORDER)
    color_now = get_success_data(api_client.get_color(color["id"], ADMIN))
    assert color_now["status"] == "PROPOSED"
    assert fx.list_campaigns(color["id"]) == []


def test_campaign_on_in_vote_color_returns_color_not_active(api):
    """PRD section 3.1: "An introduction campaign requires the color to be
    `PROPOSED`; a retirement campaign requires it to be `ACTIVE`; any other
    posture is rejected with `ERR_COLOR_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/campaign_on_in_vote_color_returns_color_not_active
    """
    fx.reset_clock()
    color = fx.create_color()
    fx.open_campaign(color["id"])
    resp = api_client.create_vote_campaign(
        color["id"],
        {"kind": "INTRODUCTION", "opens_on": "2026-10-01T00:00:00Z",
         "closes_on": "2026-10-15T23:59:59Z"},
        ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_COLOR_NOT_ACTIVE)
    assert resp.status_code == 409
    campaigns = fx.list_campaigns(color["id"])
    assert len(campaigns) == 1


def test_campaign_never_opened_tallies_failed(api):
    """PRD section 3.1: "If the clock is moved so that the entire window is
    jumped — the campaign is still `SCHEDULED` when `closes_on` has already
    passed — the campaign is tallied anyway, over zero ballots, and fails on
    quorum as described below."

    Design: Corner/state_machines/campaign_never_opened_tallies_failed
    """
    fx.reset_clock()
    color = fx.create_color()
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-21T00:00:00Z")
    tally = fx.run_epoch()
    assert tally["campaigns_opened"] == 0
    assert tally["campaigns_tallied"] == 1
    camps = fx.list_campaigns(color["id"])
    assert camps[0]["status"] == "TALLYED"
    assert camps[0]["outcome"] == "FAILED"
    assert camps[0]["turnout_count"] == 0
    color_now = get_success_data(api_client.get_color(color["id"], ADMIN))
    assert color_now["status"] == "PROPOSED"


def test_retired_color_archived_by_epoch_after_archive_date(api):
    """PRD section 3.1: "when the logical clock reaches or passes
    `archive_after_date`, the epoch moves the color from `RETIRED` to
    `ARCHIVED`, closing the lifecycle." and "`archive_after_date`, which is derived as
    `retired_on` plus thirty days and drives archival".

    Design: Corner/state_machines/retired_color_archived_by_epoch_after_archive_date
    """
    fx.reset_clock()
    color = fx.make_active_color()
    fx.retire_color(color["id"])
    retired = fx.get_color(color["id"])
    assert retired["status"] == "RETIRED"
    assert_same_instant(retired["archive_after_date"], "2026-11-14T23:59:59Z", "archive_after_date")

    fx.set_clock("2026-11-14T12:00:00Z")
    early = fx.run_epoch()
    assert early["colors_archived"] == 0
    assert fx.get_color(color["id"])["status"] == "RETIRED"

    fx.set_clock("2026-11-15T00:00:00Z")
    late = fx.run_epoch()
    assert late["colors_archived"] == 1
    final = fx.get_color(color["id"])
    assert final["status"] == "ARCHIVED"
    assert_same_instant(final["archive_after_date"], "2026-11-14T23:59:59Z", "archive_after_date")


def test_run_epoch_returns_counts_object(api):
    """PRD section 3.8: "The checkpoint's response reports the epoch as
    `epoch_index` together with per-phase tallies: `campaigns_opened`,
    `campaigns_tallied`, `sessions_closed`, `allocations_expired`,
    `recalls_contained`, `recalls_closed`, and `colors_archived`, each an
    integer count of the transitions that fired in that phase during this
    epoch."

    Design: Corner/endpoints/run_epoch_returns_counts_object
    """
    fx.reset_clock()
    color = fx.create_color()
    fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    first = fx.run_epoch()
    for field in ("epoch_index", "campaigns_opened", "campaigns_tallied",
                  "sessions_closed", "allocations_expired", "recalls_contained",
                  "recalls_closed", "colors_archived"):
        assert isinstance(first[field], int), f"{field} must be an integer"
    assert first["campaigns_opened"] == 1
    second = fx.run_epoch()
    assert second["epoch_index"] == first["epoch_index"] + 1
    assert second["campaigns_opened"] == 0
    camps = fx.list_campaigns(color["id"])
    assert camps[0]["status"] == "OPEN"


def test_epoch_opens_scheduled_campaign_at_inclusive_boundary(api):
    """PRD section 3.1: "a `SCHEDULED` campaign becomes `OPEN` at the epoch when
    the logical clock has reached `opens_on` but has not yet reached
    `closes_on`".

    Design: Corner/complexity_layers/epoch_opens_scheduled_campaign_at_inclusive_boundary
    """
    fx.reset_clock()
    color = fx.create_color()
    fx.open_campaign(color["id"])  # opens 2026-09-05T00:00:00Z
    fx.set_clock("2026-09-04T23:59:59Z")
    early = fx.run_epoch()
    assert early["campaigns_opened"] == 0
    assert fx.list_campaigns(color["id"])[0]["status"] == "SCHEDULED"
    fx.set_clock("2026-09-05T00:00:00Z")
    on_time = fx.run_epoch()
    assert on_time["campaigns_opened"] == 1
    assert fx.list_campaigns(color["id"])[0]["status"] == "OPEN"


def test_color_lifecycle_failed_introduction_mid_state(api):
    """PRD section 3.1: "a failed introduction returns the color to `PROPOSED`,
    and a later campaign may retry the introduction — the revision loop is
    intentional."

    Design: Difficulty/non_linear_state_machine/color_lifecycle_failed_introduction_loops_back_to_proposed
    """
    fx.reset_clock()
    color = fx.create_color("Sunset Glow", "#FD5E53")
    camp = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    mid = fx.get_color(color["id"])
    assert mid["status"] == "PROPOSED", (
        f"the failed tally must cycle the color back to PROPOSED, got {mid['status']}")
    camps = fx.list_campaigns(color["id"])
    assert camps[0]["outcome"] == "FAILED"


def test_color_lifecycle_failed_introduction_retry_activates(api):
    """PRD section 3.1: "A passed introduction moves the color from `IN_VOTE` to
    `ACTIVE` and stamps `introduced_on` with the campaign's `closes_on`; a
    failed introduction returns the color to `PROPOSED`, and a later campaign
    may retry the introduction — the revision loop is intentional."

    Design: Difficulty/non_linear_state_machine/color_lifecycle_failed_introduction_loops_back_to_proposed
    """
    fx.reset_clock()
    color = fx.create_color("Sunset Glow", "#FD5E53")
    camp1 = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp1["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    camp2 = fx.open_campaign(color["id"], "INTRODUCTION",
                             "2026-09-25T00:00:00Z", "2026-10-10T23:59:59Z")
    fx.set_clock("2026-09-26T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp2["id"], "KIDS", "YES", 20)
    fx.set_clock("2026-10-11T00:00:00Z")
    fx.run_epoch()
    final = fx.get_color(color["id"])
    assert final["status"] == "ACTIVE"
    assert_same_instant(final["introduced_on"], "2026-10-10T23:59:59Z", "introduced_on")
    camps = fx.list_campaigns(color["id"])
    assert camps[0]["outcome"] == "FAILED"
    assert camps[1]["outcome"] == "PASSED"


def test_campaign_windows_back_to_back_legal_overlap_rejected(api):
    """PRD section 3.1: "Campaign windows are closed intervals — both bounds
    belong to the window — and a new window must not intersect any existing
    campaign window of the same color; an overlap is rejected with
    `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/campaign_windows_closed_interval_overlap
    """
    fx.reset_clock()
    color = fx.create_color("Faded Denim", "#7B9CC4")
    camp1 = fx.open_campaign(color["id"])  # [09-05, 09-20T23:59:59]
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp1["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    resp2 = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-21T00:00:00Z",
                      "closes_on": "2026-09-30T23:59:59Z"}, ADMIN)
    validate_success(resp2, 201)  # back-to-back: opens strictly after k1 closes
    camp2 = resp2.json()["data"]
    fx.set_clock("2026-09-22T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp2["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-10-01T00:00:00Z")
    fx.run_epoch()
    resp3 = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-20T12:00:00Z",
                      "closes_on": "2026-09-20T23:00:00Z"}, ADMIN)
    validate_error(resp3, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT)
    assert resp3.status_code == 409


def test_campaign_windows_overlap_keeps_color_proposed(api):
    """PRD section 3.1: "a failed introduction returns the color to `PROPOSED`"
    and "an overlap is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP 409)" —
    the rejected overlap neither persists a campaign nor moves the color.

    Design: Difficulty/resource_temporal_overlap/campaign_windows_closed_interval_overlap
    """
    fx.reset_clock()
    color = fx.create_color("Faded Denim", "#7B9CC4")
    camp1 = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp1["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    camp2 = fx.open_campaign(color["id"], "INTRODUCTION",
                             "2026-09-21T00:00:00Z", "2026-09-30T23:59:59Z")
    fx.set_clock("2026-09-22T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp2["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-10-01T00:00:00Z")
    fx.run_epoch()
    resp3 = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-20T12:00:00Z",
                      "closes_on": "2026-09-20T23:00:00Z"}, ADMIN)
    validate_error(resp3, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT)
    assert fx.get_color(color["id"])["status"] == "PROPOSED"
    assert len(fx.list_campaigns(color["id"])) == 2


def test_campaign_date_order_beats_window_conflict(api):
    """PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins, and a request that would fail several checks surfaces the
    earliest one's error." — date ordering (stage 8, `ERR_DATE_ORDER`) precedes
    capacity/structural window conflict (stage 9,
    `ERR_CAMPAIGN_WINDOW_CONFLICT`).

    Design: Difficulty/priority_pair_validation_conflict/campaign_date_order_beats_window_conflict
    """
    fx.reset_clock()
    color = fx.create_color("Faded Denim", "#7B9CC4")
    camp1 = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp1["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    resp = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-10T00:00:00Z",
                      "closes_on": "2026-09-01T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DATE_ORDER)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != "ERR_CAMPAIGN_WINDOW_CONFLICT"


def test_campaign_after_date_order_error_valid_retry_succeeds(api):
    """PRD section 3.1: "a failed introduction returns the color to `PROPOSED`,
    and a later campaign may retry the introduction" — a well-ordered,
    non-overlapping retry after the rejected attempt is accepted.

    Design: Difficulty/priority_pair_validation_conflict/campaign_date_order_beats_window_conflict
    """
    fx.reset_clock()
    color = fx.create_color("Faded Denim", "#7B9CC4")
    camp1 = fx.open_campaign(color["id"])
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.run_epoch()
    fx.cast_votes(camp1["id"], "KIDS", "NO", 20)
    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_epoch()
    bad = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-10T00:00:00Z",
                      "closes_on": "2026-09-01T00:00:00Z"}, ADMIN)
    validate_error(bad, ApiErrorId.ERR_DATE_ORDER)
    good = api_client.create_vote_campaign(
        color["id"], {"kind": "INTRODUCTION", "opens_on": "2026-09-21T00:00:00Z",
                      "closes_on": "2026-09-30T23:59:59Z"}, ADMIN)
    validate_success(good, 201)
    assert fx.get_color(color["id"])["status"] == "IN_VOTE"
    assert len(fx.list_campaigns(color["id"])) == 2


def test_retirement_tally_cascades_color_retired_dates(api):
    """PRD section 3.1: "A passed retirement moves the color from `RETIRE_VOTE`
    to `RETIRED`, stamps `retired_on` with the campaign's `closes_on`, and
    derives `archive_after_date` as `closes_on` plus thirty days".

    Design: Difficulty/transitive_cascade/retirement_tally_cascades_color_spec_run
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.retire_color(env["color"]["id"])
    color = fx.get_color(env["color"]["id"])
    assert color["status"] == "RETIRED"
    assert_same_instant(color["retired_on"], "2026-10-15T23:59:59Z", "retired_on")
    assert_same_instant(color["archive_after_date"], "2026-11-14T23:59:59Z", "archive_after_date")


def test_retirement_cascade_deprecates_spec_cancels_run(api):
    """PRD section 3.1: "Retirement also cascades at that moment: every
    assortment spec whose entries contain the retired color becomes
    `DEPRECATED`, and every `PLANNED` production run of a newly deprecated spec
    is `CANCELLED`."

    Design: Difficulty/transitive_cascade/retirement_tally_cascades_color_spec_run
    """
    fx.reset_clock()
    env = fx.production_setup()
    run = fx.create_run(env["spec"]["id"], env["batch"]["id"])
    fx.retire_color(env["color"]["id"])
    spec = fx.get_spec(env["spec"]["id"])
    assert spec["status"] == "DEPRECATED"
    run_now = fx.get_run(run["id"])
    assert run_now["stage"] == "CANCELLED"
