"""Portal-wide layers: optimistic concurrency on parent versions and the
reconciliation of the two agency request counters.

Three create operations in the portal read a parent row, judge what they read
and then write a child that reshapes it, so each declares the parent `version`
it observed. Each of those three tokens is spent by the very write it guards,
which is why a replay is a 412 and a re-read is not. Alongside them sits the
pair of agency counters that move differently under the same two events: one is
a live gauge, the other a lifetime meter.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_HEADERS,
    MODERATOR_SECOND_HEADERS,
    MODERATOR_SECOND_ID,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_ID,
    make_agency_admin_headers,
    make_officer_headers,
)


# ── Local setup ────────────────────────────────────────────────────────────

def _locked_area_world(api: ApiClient) -> Dict[str, Any]:
    """One onboarded agency, one officer, three cameras and one locked area."""
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(
        api,
        min_device_threshold=3,
        max_open_requests=3,
        period_request_quota=20,
        post_share_retention_days=30,
        justification_min_chars=80,
    )
    world["households"] = fixtures.seed_residents_with_devices(api)
    world["devices"] = [household["device"] for household in world["households"]]
    world["area"] = fixtures.seed_locked_area(
        api, world["agency_id"], world["officer_id"], area_label="400 Block"
    )
    return world


def _flagged_post_world(api: ApiClient) -> Dict[str, Any]:
    """An author and two neighbours, whose two flags carry one post to flagged."""
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first_flagger = fixtures.register_resident(
        api,
        display_name="N1",
        email="n1@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    second_flagger = fixtures.register_resident(
        api,
        display_name="N2",
        email="n2@example.test",
        home_x_m=20,
        home_y_m=0,
        alert_radius_m=0,
    )
    seeded = fixtures.seed_flagged_post(
        api,
        author["id"],
        [first_flagger["id"], second_flagger["id"]],
        body="Package thefts reported on the 300 block three evenings running.",
    )
    seeded["author"] = author
    return seeded


def _list_video_requests(api: ApiClient, agency_id: str) -> List[Dict[str, Any]]:
    """Every video request of one agency, with the pagination block checked."""
    rows, meta = validate_paginated(
        api.list_video_requests(
            PLATFORM_ADMIN_HEADERS, f.page(limit=100, offset=0, agency_id=agency_id)
        )
    )
    assert meta["total_count"] == len(rows), (
        f"total_count {meta['total_count']} disagrees with the {len(rows)} rows returned"
    )
    return rows


# ── Optimistic concurrency on a canvass area ───────────────────────────────

def test_replaying_a_spent_area_version_is_refused_and_creates_no_request(
    api: ApiClient,
) -> None:
    """A second request creation quoting the version the first one spent is a 412.

    PRD: "A creation still carrying a previously observed version is rejected with `ERR_STALE_AREA_VERSION`, because the officer's picture of the canvass area — device roster, request count, lock posture — predates a change another writer made."
    PRD: "`expected_request_area_version` matches the area's current `version` — otherwise `ERR_STALE_AREA_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/video_request_created_with_a_superseded_area_version_returns_412
    """
    world = _locked_area_world(api)
    area = world["area"]
    observed_version = area["version"]
    assert area["derived_request_count"] == 0, (
        "Locking an area does not create a request against it"
    )
    assert area["eligible_device_count"] == 3
    assert area["effective_min_devices"] == 3

    first = fixtures.create_video_request(
        api, area, world["officer_id"], case_number="CASE-2040"
    )
    after_first = fixtures.read_area(api, area["id"])
    assert after_first["derived_request_count"] == 1
    assertions.assert_version_advanced(after_first, observed_version)

    response = api.create_video_request(
        f.video_request_payload(area["id"], observed_version, case_number="CASE-2041"),
        make_officer_headers(world["officer_id"]),
    )
    validate_error(response, ApiErrorId.STALE_AREA_VERSION.value, 412)

    refused = fixtures.read_area(api, area["id"])
    assert refused["derived_request_count"] == 1, (
        "A stale-version rejection creates no request, so the area's count cannot move"
    )
    assertions.assert_version_unchanged(refused, observed_version + 1)
    assert refused["status"] == k.AREA_STATUS_LOCKED
    assert refused["eligible_device_count"] == 3, (
        "A stale-version rejection never re-freezes the roster"
    )
    assert refused["effective_min_devices"] == 3

    rows = _list_video_requests(api, world["agency_id"])
    assertions.assert_ids_in_order(rows, [first["id"]])


def test_rereading_the_area_lets_the_identical_second_request_creation_succeed(
    api: ApiClient,
) -> None:
    """The same creation succeeds once the officer quotes the area's current version.

    PRD: "A locked area may back any number of video requests, and each creation advances that area's `derived_request_count` and therefore its `version`, so a second creation that carries the area's *current* version legitimately succeeds."
    PRD: "The backing area's `derived_request_count` is incremented by 1 and the area's `version` advances, which is precisely why the next officer to create a request against the same area must have read that new version."

    Design: Corner/cross_cutting_complexity_layers/video_request_created_with_a_superseded_area_version_returns_412
    """
    world = _locked_area_world(api)
    area = world["area"]
    officer_headers = make_officer_headers(world["officer_id"])

    first = fixtures.create_video_request(
        api, area, world["officer_id"], case_number="CASE-2040"
    )
    stale = api.create_video_request(
        f.video_request_payload(area["id"], area["version"], case_number="CASE-2041"),
        officer_headers,
    )
    validate_error(stale, ApiErrorId.STALE_AREA_VERSION.value, 412)

    reread = fixtures.read_area(api, area["id"])
    retry = validate_success(
        api.create_video_request(
            f.video_request_payload(
                area["id"], reread["version"], case_number="CASE-2041"
            ),
            officer_headers,
        ),
        201,
    )

    assert retry["id"] != first["id"], "The retry creates a second, distinct request"
    assert retry["lifecycle_state"] == k.LIFECYCLE_DRAFT
    assert retry["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_PENDING
    assert retry["request_area_id"] == area["id"]
    assert retry["agency_id"] == world["agency_id"]
    assert retry["submitting_officer_id"] == world["officer_id"]
    assertions.assert_created_equals_updated(retry)
    assertions.assert_solicitation_buckets(retry, 0, 0, 0, 0, 0)
    assertions.assert_bps(retry["provisional_share_rate_bps"], 0)

    after_retry = fixtures.read_area(api, area["id"])
    assert after_retry["derived_request_count"] == 2
    assertions.assert_version_advanced(after_retry, reread["version"])
    assert after_retry["eligible_device_count"] == 3
    assert after_retry["status"] == k.AREA_STATUS_LOCKED

    rows = _list_video_requests(api, world["agency_id"])
    assertions.assert_ids_in_order(rows, [first["id"], retry["id"]])


# ── Optimistic concurrency on a community post ─────────────────────────────

def test_replaying_a_spent_post_version_is_refused_and_opens_no_case(
    api: ApiClient, clock: str
) -> None:
    """A second moderator replaying the version the first case spent is a 412.

    PRD: "A creation still carrying a previously observed version is rejected with `ERR_STALE_POST_VERSION`, because a moderator's triage judgement rests on post body, flag count and discrimination score that have since changed."
    PRD: "Opening is guarded by optimistic concurrency precisely because a second case on the same post is legitimate rather than forbidden: two moderators triaging the same post concurrently would both succeed and the first case would vanish into supersession unread, so the stale version is rejected with `ERR_STALE_POST_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/moderation_case_opened_with_a_superseded_post_version_returns_412
    """
    seeded = _flagged_post_world(api)
    post = seeded["post"]
    observed_version = post["version"]
    assert post["state"] == k.POST_FLAGGED
    assert post["flag_count"] == k.RESIDENT_FLAG_THRESHOLD
    assert post["auto_flag_reason"] == k.AUTO_FLAG_RESIDENT_FLAGS

    first_case = fixtures.open_case(api, post, MODERATOR_HEADERS)
    assert first_case["state"] == k.CASE_OPEN

    response = api.open_moderation_case(
        f.moderation_case_payload(
            post["id"], observed_version, opened_reason=k.OPENED_REASON_AUTO_SCORE
        ),
        MODERATOR_SECOND_HEADERS,
    )
    validate_error(response, ApiErrorId.STALE_POST_VERSION.value, 412)

    refused = fixtures.read_post(api, post["id"])
    assert refused["state"] == k.POST_UNDER_REVIEW, (
        "Opening the first case moved the post under review; the refusal moves nothing"
    )
    assertions.assert_version_unchanged(refused, observed_version + 1)
    assert refused["flag_count"] == k.RESIDENT_FLAG_THRESHOLD

    survivor = fixtures.read_case(api, first_case["id"])
    assert survivor["state"] == k.CASE_OPEN, (
        "A rejected second opening supersedes nothing, so the first case stays open"
    )
    assertions.assert_version_unchanged(survivor, first_case["version"])

    cases = fixtures.list_cases_for_post(api, post["id"])
    assertions.assert_ids_in_order(cases, [first_case["id"]])


def test_rereading_the_post_lets_the_second_case_open_and_supersede_the_first(
    api: ApiClient, clock: str
) -> None:
    """Quoting the post's current version opens the second case and supersedes the first.

    PRD: "A new case legitimately supersedes any open case on the same post, so a second case creation carrying the post's current version succeeds and the earlier case is superseded."
    PRD: "Any case already `OPEN` on the same post moves `OPEN → SUPERSEDED`, its `superseded_by_case_created_at` set to the new case's `created_at` and its `decision` left at `NONE`."

    Design: Corner/cross_cutting_complexity_layers/moderation_case_opened_with_a_superseded_post_version_returns_412
    """
    seeded = _flagged_post_world(api)
    post = seeded["post"]
    first_case = fixtures.open_case(api, post, MODERATOR_HEADERS)

    stale = api.open_moderation_case(
        f.moderation_case_payload(
            post["id"], post["version"], opened_reason=k.OPENED_REASON_AUTO_SCORE
        ),
        MODERATOR_SECOND_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_POST_VERSION.value, 412)

    reread = fixtures.read_post(api, post["id"])
    assert reread["state"] == k.POST_UNDER_REVIEW
    second_case = validate_success(
        api.open_moderation_case(
            f.moderation_case_payload(
                post["id"], reread["version"], opened_reason=k.OPENED_REASON_AUTO_SCORE
            ),
            MODERATOR_SECOND_HEADERS,
        ),
        201,
    )

    assert second_case["id"] != first_case["id"]
    assert second_case["state"] == k.CASE_OPEN
    assert second_case["decision"] == k.DECISION_NONE
    assert second_case["opened_reason"] == k.OPENED_REASON_AUTO_SCORE
    assert second_case["opened_by_user_id"] == MODERATOR_SECOND_ID
    assert second_case["resident_post_id"] == post["id"]
    assertions.assert_score(
        second_case["post_discrimination_score_at_open"],
        "0.00",
        "post_discrimination_score_at_open",
    )
    assertions.assert_created_equals_updated(second_case)

    superseded = fixtures.read_case(api, first_case["id"])
    assert superseded["state"] == k.CASE_SUPERSEDED
    assert superseded["decision"] == k.DECISION_NONE
    assertions.assert_instant(
        superseded["superseded_by_case_created_at"],
        second_case["created_at"],
        "superseded_by_case_created_at",
    )
    assertions.assert_version_advanced(superseded, first_case["version"])

    after = fixtures.read_post(api, post["id"])
    assert after["state"] == k.POST_UNDER_REVIEW, (
        "A re-triage supersedes the open case without changing the post's state"
    )
    assertions.assert_version_advanced(after, reread["version"])

    rows, meta = validate_paginated(
        api.list_moderation_cases(
            PLATFORM_ADMIN_HEADERS,
            f.page(
                limit=10, offset=0, resident_post_id=post["id"], state=k.CASE_OPEN
            ),
        )
    )
    assert meta["total_count"] == 1, (
        "Exactly one open case survives, and the refused attempt left no third row"
    )
    assertions.assert_ids_in_order(rows, [second_case["id"]])


# ── Optimistic concurrency on an agency ────────────────────────────────────

def test_replaying_a_spent_agency_version_is_refused_and_leaves_the_pointer(
    api: ApiClient, clock: str
) -> None:
    """A second compilation on the token the first spent is a 412 and repoints nothing.

    PRD: "A compilation still carrying a previously observed version is rejected with `ERR_STALE_AGENCY_VERSION`, because the request-volume and share-rate figures it is about to publish were derived from an agency snapshot that is no longer current."
    PRD: "Compilation is guarded by optimistic concurrency on the agency, because it writes the agency's `latest_report_id`: a stale `expected_agency_version` is refused with `ERR_STALE_AGENCY_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/transparency_report_created_with_a_superseded_agency_version_returns_412
    """
    agency = fixtures.onboarded_agency(api, min_device_threshold=3)
    observed_version = agency["version"]
    assert agency["latest_report_id"] is None

    first = fixtures.compile_report(
        api,
        agency,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
    )
    assert first["variant"] == k.REPORT_PROVISIONAL

    after_first = fixtures.read_agency(api, agency["id"])
    assert after_first["latest_report_id"] == first["id"]
    assertions.assert_version_advanced(after_first, observed_version)

    response = api.compile_report(
        f.report_payload(
            agency["id"],
            observed_version,
            period_start_utc="2026-08-01T00:00:00Z",
            period_end_utc="2026-08-12T00:00:00Z",
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.STALE_AGENCY_VERSION.value, 412)

    refused = fixtures.read_agency(api, agency["id"])
    assert refused["latest_report_id"] == first["id"], (
        "The refused compilation did not repoint the agency's report pointer"
    )
    assertions.assert_version_unchanged(refused, observed_version + 1)
    assert refused["status"] == k.AGENCY_STATUS_ONBOARDED

    rows, meta = validate_paginated(
        api.list_reports(
            PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency["id"])
        )
    )
    assert meta["total_count"] == 1, "The refusal never produced a second report row"
    assertions.assert_ids_in_order(rows, [first["id"]])


def test_rereading_the_agency_lets_the_second_reporting_period_compile(
    api: ApiClient, clock: str
) -> None:
    """Quoting the agency's current version publishes the second overlapping period.

    PRD: "An agency may publish many overlapping reporting periods and each compilation repoints `Agency.latest_report_id` and advances the agency's `version`, so a second compilation carrying the current version legitimately succeeds."
    PRD: "On success the new report's identifier becomes the agency's `latest_report_id` and the agency's `version` advances by 1."

    Design: Corner/cross_cutting_complexity_layers/transparency_report_created_with_a_superseded_agency_version_returns_412
    """
    agency = fixtures.onboarded_agency(api, min_device_threshold=3)
    first = fixtures.compile_report(
        api,
        agency,
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
    )

    stale = api.compile_report(
        f.report_payload(
            agency["id"],
            agency["version"],
            period_start_utc="2026-08-01T00:00:00Z",
            period_end_utc="2026-08-12T00:00:00Z",
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_AGENCY_VERSION.value, 412)

    reread = fixtures.read_agency(api, agency["id"])
    second = validate_success(
        api.compile_report(
            f.report_payload(
                reread["id"],
                reread["version"],
                period_start_utc="2026-08-01T00:00:00Z",
                period_end_utc="2026-08-12T00:00:00Z",
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )

    assert second["id"] != first["id"], "The retry publishes a second, distinct report"
    assert second["variant"] == k.REPORT_PROVISIONAL
    assert second["agency_id"] == agency["id"]
    assert second["compiled_by_user_id"] == PLATFORM_ADMIN_ID
    assertions.assert_instant(
        second["period_start_utc"], "2026-08-01T00:00:00Z", "period_start_utc"
    )
    assertions.assert_instant(
        second["period_end_utc"], "2026-08-12T00:00:00Z", "period_end_utc"
    )
    assertions.assert_created_equals_updated(second)
    assertions.assert_zero_counters(
        second,
        "requests_submitted_count",
        "solicitations_dispatched_count",
        "suppressed_dispatch_count",
        "shared_count",
        "declined_count",
        "expired_count",
        "withdrawn_count",
        "pending_count",
        "opt_out_excluded_count",
        "purged_clip_count",
    )
    assertions.assert_bps(
        second["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )
    assertions.assert_bps(
        second["certified_share_rate_bps"], 0, "certified_share_rate_bps"
    )
    assertions.assert_bps(
        second["published_share_rate_bps"], 0, "published_share_rate_bps"
    )

    after = fixtures.read_agency(api, agency["id"])
    assert after["latest_report_id"] == second["id"]
    assertions.assert_version_advanced(after, reread["version"])

    rows, meta = validate_paginated(
        api.list_reports(
            PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency["id"])
        )
    )
    assert meta["total_count"] == 2
    assertions.assert_ids_in_order(rows, [first["id"], second["id"]])


# ── The two agency request counters ────────────────────────────────────────

def _two_justified_requests(api: ApiClient) -> Dict[str, Any]:
    """Two locked areas at the same centre, each backing one justified request.

    The two footage windows sit three days apart, so the repeat-canvass rule
    never fires even though the discs are identical.
    """
    world = _locked_area_world(api)
    first = fixtures.create_video_request(
        api, world["area"], world["officer_id"], case_number="CASE-2050"
    )
    fixtures.log_justification(api, first["id"], world["officer_id"])

    second_area = fixtures.seed_locked_area(
        api,
        world["agency_id"],
        world["officer_id"],
        area_label="Area 2",
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-05T06:00:00Z",
    )
    second = fixtures.create_video_request(
        api, second_area, world["officer_id"], case_number="CASE-2051"
    )
    fixtures.log_justification(api, second["id"], world["officer_id"])

    world["second_area"] = second_area
    world["first_request_id"] = first["id"]
    world["second_request_id"] = second["id"]
    return world


def test_open_request_gauge_falls_on_withdrawal_while_the_lifetime_meter_holds(
    api: ApiClient,
) -> None:
    """Two submits and one withdrawal leave the agency counter pair reading one and two.

    PRD: "On success both counters move, but only the first can ever come back down — `open_request_count` is incremented by 1 and is decremented again when the request resolves, whereas `requests_submitted_count` is incremented by 1 and is never decremented."
    PRD: "The request then recomputes `pending_count` and `withdrawn_count` so that the solicitation ledger still balances, recomputes `provisional_share_rate_bps`, and the agency's `open_request_count` is decremented by 1."

    Design: Corner/cross_cutting_complexity_layers/agency_open_request_counter_reconciles_across_two_submits_and_one_withdrawal
    """
    world = _two_justified_requests(api)
    assert world["agency"]["open_request_count"] == 0
    assert world["agency"]["requests_submitted_count"] == 0

    fixtures.submit_request(api, world["first_request_id"], world["officer_id"])
    after_first = fixtures.read_agency(api, world["agency_id"])
    assert after_first["open_request_count"] == 1
    assert after_first["requests_submitted_count"] == 1

    fixtures.submit_request(api, world["second_request_id"], world["officer_id"])
    after_second = fixtures.read_agency(api, world["agency_id"])
    assert after_second["open_request_count"] == 2
    assert after_second["requests_submitted_count"] == 2

    withdrawn = fixtures.withdraw_request(
        api,
        world["first_request_id"],
        make_agency_admin_headers(world["agency_id"]),
        reason="Suspect identified from another source; canvass no longer needed.",
    )
    assert withdrawn["lifecycle_state"] == k.LIFECYCLE_WITHDRAWN
    assert withdrawn["withdraw_reason"] == k.WITHDRAW_REASON_OFFICER
    assertions.assert_solicitation_buckets(withdrawn, 0, 0, 0, 0, 3)
    assertions.assert_solicitation_ledger(withdrawn, 3)
    assertions.assert_bps(withdrawn["provisional_share_rate_bps"], 0)
    assert withdrawn["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_LOGGED, (
        "Withdrawal moves the lifecycle dimension and leaves the compliance one alone"
    )

    after_withdrawal = fixtures.read_agency(api, world["agency_id"])
    assert after_withdrawal["open_request_count"] == 1, (
        "The live gauge counts only the requests still soliciting"
    )
    assert after_withdrawal["requests_submitted_count"] == 2, (
        "The lifetime meter never falls, so a withdrawal refunds no period quota"
    )


def test_withdrawing_one_request_leaves_the_sibling_canvass_untouched(
    api: ApiClient,
) -> None:
    """The withdrawal cascade reaches only its own solicitations and cameras.

    PRD: "`Agency.open_request_count` is the number of that agency's video requests currently in lifecycle state `SOLICITING` and is recomputed on every lifecycle transition of any of them; `Agency.requests_submitted_count` counts every video request of that agency that has *ever* entered `SOLICITING` and is never decremented."
    PRD: "A request in `SOLICITING` may also be withdrawn — `lifecycle_state` moves `SOLICITING → WITHDRAWN` — and there the cascade runs two levels: at level one every solicitation of that request still in `SOLICITED` moves `SOLICITED → WITHDRAWN` in ascending `dispatch_rank` with `responded_at` stamped from the clock, and at level two each of those cameras has its `pending_solicitation_count` decremented by 1."

    Design: Corner/cross_cutting_complexity_layers/agency_open_request_counter_reconciles_across_two_submits_and_one_withdrawal
    """
    world = _two_justified_requests(api)
    fixtures.submit_request(api, world["first_request_id"], world["officer_id"])
    fixtures.submit_request(api, world["second_request_id"], world["officer_id"])

    fixtures.withdraw_request(
        api,
        world["first_request_id"],
        make_agency_admin_headers(world["agency_id"]),
        reason="Suspect identified from another source; canvass no longer needed.",
    )

    cancelled = fixtures.list_solicitations(
        api, video_request_id=world["first_request_id"]
    )
    assertions.assert_field_sequence(cancelled, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(
        cancelled,
        "status",
        [k.SOLICITATION_WITHDRAWN] * 3,
    )
    for solicitation in cancelled:
        assertions.assert_instant(
            solicitation["responded_at"], fixtures.SCENARIO_CLOCK, "responded_at"
        )

    sibling = fixtures.read_request(api, world["second_request_id"])
    assert sibling["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assertions.assert_solicitation_buckets(sibling, 3, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(sibling, 3)
    assertions.assert_bps(sibling["provisional_share_rate_bps"], 0)

    survivors = fixtures.list_solicitations(
        api, video_request_id=world["second_request_id"]
    )
    assertions.assert_field_sequence(survivors, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(
        survivors,
        "status",
        [k.SOLICITATION_SOLICITED] * 3,
    )
    for solicitation in survivors:
        assertions.assert_nulls(solicitation, "responded_at", "decline_reason")

    for device in world["devices"]:
        row = fixtures.read_device(api, device["id"])
        assert row["solicitations_received_count"] == 2, (
            "The monotonic counter keeps both asks the camera received"
        )
        assert row["pending_solicitation_count"] == 1, (
            "Only the withdrawn request's ask left the camera's pending queue"
        )

    agency = fixtures.read_agency(api, world["agency_id"])
    assert agency["open_request_count"] == 1
    assert agency["requests_submitted_count"] == 2
