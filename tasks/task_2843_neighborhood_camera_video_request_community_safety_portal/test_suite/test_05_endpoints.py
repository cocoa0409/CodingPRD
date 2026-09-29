"""Endpoint behaviour: partial camera updates, declining a solicitation, the
retention sweep as a no-op, revising a post and opening a moderation case.

Each test drives one declared route and asserts the full final state the
contract names for it — the fields that moved, the fields that must not have
moved, the counters on every row the operation touched, and the version each
of them now carries.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_HEADERS,
    MODERATOR_ID,
    PLATFORM_ADMIN_HEADERS,
    make_resident_headers,
)


# ── Local setup helpers ────────────────────────────────────────────────────

def _resident_with_two_cameras(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """One resident owning two cameras at two distinct grid positions.

    The first camera takes the defaults for both auto-decline fields; the second
    asks for a blanket refusal outright, so the two rows start from different
    auto-decline postures.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    resident = fixtures.register_resident(
        api,
        display_name="R1",
        email="r1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    front = fixtures.register_device(
        api,
        resident["id"],
        label="Front door",
        grid_x_m=0,
        grid_y_m=10,
        retention_window_days=30,
    )
    back = fixtures.register_device(
        api,
        resident["id"],
        label="Back gate",
        grid_x_m=0,
        grid_y_m=11,
        retention_window_days=7,
        auto_decline_requests=True,
    )
    return resident, front, back


def _pinned_clock_with_two_residents(api: ApiClient) -> Dict[str, Any]:
    """The clock pinned and two resident accounts, and nothing else at all.

    Nothing in this world can ever be swept: there is no canvass, no
    solicitation and no shared clip anywhere in the portal.
    """
    clock_state = fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    first = fixtures.register_resident(
        api,
        display_name="R1",
        email="r1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    second = fixtures.register_resident(
        api,
        display_name="R2",
        email="r2@example.test",
        home_x_m=0,
        home_y_m=20,
        alert_radius_m=0,
    )
    return {"clock_state": clock_state, "residents": [first, second]}


# ── Partial camera update ──────────────────────────────────────────────────

def test_device_patch_updates_only_supplied_fields_and_advances_version(
    api: ApiClient,
) -> None:
    """Patching label and retention leaves the grid position and auto-decline posture alone.

    PRD: "Updating a camera is a partial write over `label`, `retention_window_days`, `auto_decline_requests` and `status`, and omitted fields are left untouched."
    PRD: "It takes one of `NONE`, `OWNER_MANUAL` or `OPT_OUT` and starts at `NONE`."
    PRD: "Most resources carry the full set of common properties: `id`, `created_at` (the ISO 8601 UTC instant of creation, with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/device_patch_updates_supplied_fields_only_and_bumps_version
    """
    resident, front, _back = _resident_with_two_cameras(api)
    assertions.assert_created_equals_updated(front)
    assertions.assert_subset(
        front,
        {
            "grid_x_m": 0,
            "grid_y_m": 10,
            "retention_window_days": 30,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )

    patched = validate_success(
        api.update_device(
            front["id"],
            f.device_patch_payload(label="Front porch", retention_window_days=90),
            make_resident_headers(resident["id"]),
        )
    )

    assertions.assert_subset(
        patched,
        {
            "id": front["id"],
            "label": "Front porch",
            "retention_window_days": 90,
            "grid_x_m": 0,
            "grid_y_m": 10,
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            "owner_resident_id": resident["id"],
        },
    )
    assertions.assert_zero_counters(
        patched, "solicitations_received_count", "pending_solicitation_count"
    )
    assertions.assert_version_advanced(patched, front["version"])

    reread = fixtures.read_device(api, front["id"])
    assertions.assert_subset(
        reread,
        {
            "label": "Front porch",
            "retention_window_days": 90,
            "grid_x_m": 0,
            "grid_y_m": 10,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            "version": front["version"] + 1,
        },
    )


def test_device_patch_is_visible_in_the_owner_filtered_camera_list(
    api: ApiClient,
) -> None:
    """The owner's camera list carries the patched row and the untouched second camera.

    PRD: "The pagination block echoed in `meta` carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, which is true exactly when rows remain beyond the current page."
    PRD: "When an owner who has *not* opted out submits `auto_decline_requests` as true, the source is recorded as `OWNER_MANUAL`."
    PRD: "Updating a camera is a partial write over `label`, `retention_window_days`, `auto_decline_requests` and `status`, and omitted fields are left untouched."

    Design: Corner/endpoints/device_patch_updates_supplied_fields_only_and_bumps_version
    """
    resident, front, back = _resident_with_two_cameras(api)
    assertions.assert_subset(
        back,
        {
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OWNER_MANUAL,
            "retention_window_days": 7,
            "grid_x_m": 0,
            "grid_y_m": 11,
        },
    )

    fixtures.update_device(
        api,
        front["id"],
        resident["id"],
        label="Front porch",
        retention_window_days=90,
    )

    rows, meta = validate_paginated(
        api.list_devices(
            make_resident_headers(resident["id"]),
            f.page(limit=10, offset=0, owner_resident_id=resident["id"]),
        )
    )

    assert meta["total_count"] == 2, (
        f"The owner has exactly two cameras, got total_count {meta['total_count']}"
    )
    assert meta["limit"] == 10 and meta["offset"] == 0, f"Unexpected page block: {meta!r}"
    assert meta["has_more"] is False, f"Two rows fit on one page of ten: {meta!r}"
    assert len(rows) == 2, f"Expected both cameras on the page, got {len(rows)}"

    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {front["id"], back["id"]}, (
        f"Expected the owner's two cameras, got {sorted(by_id)}"
    )
    assertions.assert_subset(
        by_id[front["id"]],
        {
            "label": "Front porch",
            "retention_window_days": 90,
            "grid_x_m": 0,
            "grid_y_m": 10,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            "version": front["version"] + 1,
        },
    )
    assertions.assert_subset(
        by_id[back["id"]],
        {
            "label": "Back gate",
            "retention_window_days": 7,
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OWNER_MANUAL,
            "version": back["version"],
        },
    )


# ── Declining a consent solicitation ───────────────────────────────────────

def test_decline_moves_one_unit_from_pending_to_declined_and_leaves_the_request_soliciting(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """One owner's refusal is recorded, moves one bucket unit, and touches only that camera.

    PRD: "The solicitation moves `SOLICITED → DECLINED`, `responded_at` is stamped from the clock, one unit moves out of `pending_count` and into `declined_count` on the request, the camera's `pending_solicitation_count` is decremented by 1, `provisional_share_rate_bps` is recomputed, and the solicitation's `version` advances by 1."
    PRD: "The payload carries a `decline_reason`, but a resident-initiated refusal is always recorded as `OWNER_DECLINE`; the other two values of that field, `OWNER_OPT_OUT` and `ACCOUNT_DEACTIVATED`, are written only by the account-level data-control cascades of §3.2."
    PRD: "Whenever any of these five paths leaves a request's `pending_count` at 0, the lifecycle dimension resolves itself immediately."

    Design: Corner/endpoints/consent_solicitation_decline_records_reason_and_moves_counters
    """
    request_id = canvass["request_id"]
    first_device, second_device, third_device = canvass["devices"]
    first_resident = canvass["residents"][0]

    assertions.assert_subset(
        canvass["request"],
        {"lifecycle_state": k.LIFECYCLE_SOLICITING, "solicitation_count": 3},
    )
    assertions.assert_solicitation_buckets(
        canvass["request"], pending=3, shared=0, declined=0, expired=0, withdrawn=0
    )

    solicitation = fixtures.solicitation_for_device(api, request_id, first_device["id"])
    assertions.assert_subset(
        solicitation,
        {
            "dispatch_rank": 1,
            "status": k.SOLICITATION_SOLICITED,
            "resident_id": first_resident["id"],
            "clip_count": 0,
        },
    )

    declined = validate_success(
        api.decline_solicitation(
            solicitation["id"],
            f.decline_payload(),
            make_resident_headers(first_resident["id"]),
        )
    )

    assertions.assert_subset(
        declined,
        {
            "id": solicitation["id"],
            "status": k.SOLICITATION_DECLINED,
            "decline_reason": k.DECLINE_OWNER_DECLINE,
            "clip_count": 0,
        },
    )
    assertions.assert_instant(declined["responded_at"], canvass["clock"], "responded_at")
    assertions.assert_version_advanced(declined, solicitation["version"])

    request = fixtures.read_request(api, request_id)
    assert request["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        "Two neighbours are still pending, so the request may not resolve: "
        f"{request['lifecycle_state']}"
    )
    assertions.assert_solicitation_buckets(
        request, pending=2, shared=0, declined=1, expired=0, withdrawn=0
    )
    assertions.assert_solicitation_ledger(request, total=3)
    assertions.assert_bps(
        request["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )

    assertions.assert_subset(
        fixtures.read_device(api, first_device["id"]),
        {"pending_solicitation_count": 0, "solicitations_received_count": 1},
    )
    for untouched in (second_device, third_device):
        assertions.assert_subset(
            fixtures.read_device(api, untouched["id"]),
            {"pending_solicitation_count": 1, "solicitations_received_count": 1},
        )

    assert fixtures.read_agency(api, canvass["agency_id"])["open_request_count"] == 1, (
        "The request is still soliciting, so it still counts against the open quota"
    )


def test_second_decline_of_a_resolved_solicitation_is_refused(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """A solicitation already declined is closed, and the repeat answer changes nothing.

    PRD: "Declining is the recorded refusal, and it is a strictly narrower operation than sharing: it is accepted only while the solicitation is in `SOLICITED`, only from the solicitation's own `resident_id`, only while the owning request is `SOLICITING`, and only strictly before `respond_deadline_utc`."
    PRD: "The consent solicitation is still open to the attempted answer — otherwise `ERR_SOLICITATION_ALREADY_RESOLVED` (HTTP 409)."

    Design: Corner/endpoints/consent_solicitation_decline_records_reason_and_moves_counters
    """
    request_id = canvass["request_id"]
    first_device = canvass["devices"][0]
    first_resident = canvass["residents"][0]

    solicitation = fixtures.solicitation_for_device(api, request_id, first_device["id"])
    after_first = fixtures.decline_solicitation(
        api, solicitation["id"], first_resident["id"]
    )
    assert after_first["status"] == k.SOLICITATION_DECLINED, (
        f"The first decline must be accepted: {after_first!r}"
    )

    validate_error(
        api.decline_solicitation(
            solicitation["id"],
            f.decline_payload(),
            make_resident_headers(first_resident["id"]),
        ),
        ApiErrorId.SOLICITATION_ALREADY_RESOLVED.value,
        409,
    )

    reread = fixtures.read_solicitation(api, solicitation["id"])
    assertions.assert_subset(
        reread,
        {
            "status": k.SOLICITATION_DECLINED,
            "decline_reason": k.DECLINE_OWNER_DECLINE,
        },
    )
    assertions.assert_version_unchanged(reread, after_first["version"])
    assertions.assert_instant(
        reread["responded_at"], after_first["responded_at"], "responded_at"
    )

    request = fixtures.read_request(api, request_id)
    assert request["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        f"The refused answer must not resolve the request: {request['lifecycle_state']}"
    )
    assertions.assert_solicitation_buckets(
        request, pending=2, shared=0, declined=1, expired=0, withdrawn=0
    )
    assertions.assert_subset(
        fixtures.read_device(api, first_device["id"]),
        {"pending_solicitation_count": 0, "solicitations_received_count": 1},
    )


# ── The retention sweep with nothing to sweep ───────────────────────────────

def _assert_sweep_reported_nothing(sweep: Dict[str, Any], run_at: str) -> None:
    """Every one of the four sweep counters sits at zero for this clock instant."""
    assertions.assert_instant(sweep["run_at_utc"], run_at, "run_at_utc")
    assertions.assert_zero_counters(
        sweep,
        "solicitations_expired_count",
        "clips_purged_count",
        "clips_held_count",
        "requests_auto_closed_count",
    )


def test_retention_sweep_on_a_portal_with_nothing_to_sweep_reports_four_zeroes(
    api: ApiClient,
) -> None:
    """The sweep is a legal no-op: it echoes the clock and reports four zero counters.

    PRD: "The sweep reports what it did: `run_at_utc` echoing the logical clock instant it ran at, `solicitations_expired_count`, `clips_purged_count`, `clips_held_count` — the legal-hold clips it deliberately skipped — and `requests_auto_closed_count`."
    PRD: "The sweep increments the `version` of every entity it mutates by 1."

    Design: Corner/endpoints/retention_sweep_on_empty_portal_returns_zero_counts
    """
    world = _pinned_clock_with_two_residents(api)
    assertions.assert_instant(
        world["clock_state"]["current_utc"], fixtures.SCENARIO_CLOCK, "current_utc"
    )
    assert world["clock_state"]["residents_daily_counter_reset_count"] == 0, (
        "No resident held a non-zero daily counter, so none was reset: "
        f"{world['clock_state']!r}"
    )

    sweep = validate_success(api.run_retention_sweep(PLATFORM_ADMIN_HEADERS))
    _assert_sweep_reported_nothing(sweep, fixtures.SCENARIO_CLOCK)

    for resident in world["residents"]:
        reread = fixtures.read_resident(api, resident["id"])
        assertions.assert_version_unchanged(reread, 1)
        assertions.assert_subset(
            reread,
            {
                "status": k.RESIDENT_STATUS_ACTIVE,
                "notifications_sent_today": 0,
                "fatigue_state": k.FATIGUE_NORMAL,
            },
        )


def test_retention_sweep_repeated_at_the_same_clock_instant_reports_zeroes_again(
    api: ApiClient,
) -> None:
    """A second sweep without moving the clock is accepted and reports the same zeroes.

    PRD: "It is idempotent at a fixed clock: run it twice without moving the clock and the second run reports zeroes across the board, because everything it was entitled to act on has already moved."
    PRD: "The sweep reports what it did: `run_at_utc` echoing the logical clock instant it ran at, `solicitations_expired_count`, `clips_purged_count`, `clips_held_count` — the legal-hold clips it deliberately skipped — and `requests_auto_closed_count`."

    Design: Corner/endpoints/retention_sweep_on_empty_portal_returns_zero_counts
    """
    world = _pinned_clock_with_two_residents(api)

    first = validate_success(api.run_retention_sweep(PLATFORM_ADMIN_HEADERS))
    _assert_sweep_reported_nothing(first, fixtures.SCENARIO_CLOCK)

    second = validate_success(api.run_retention_sweep(PLATFORM_ADMIN_HEADERS))
    _assert_sweep_reported_nothing(second, fixtures.SCENARIO_CLOCK)

    for resident in world["residents"]:
        assertions.assert_version_unchanged(
            fixtures.read_resident(api, resident["id"]), 1
        )


# ── Revising a post ────────────────────────────────────────────────────────

_PROFILING_BODY = (
    "The man who parks by the corner house every night keeps circling the block."
)
_REWRITTEN_BODY = (
    "A car has been circling our block repeatedly late at night; please keep an eye out."
)


def _post_sent_back_for_revision(api: ApiClient) -> Dict[str, Any]:
    """An author's post carried to REVISION_REQUESTED by two flags and a moderator.

    The author and both neighbours keep an alert radius of zero, so no candidate
    ever enters a fan-out and the alert counters stay observable.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first_neighbour = fixtures.register_resident(
        api,
        display_name="Near One",
        email="n1@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    second_neighbour = fixtures.register_resident(
        api,
        display_name="Near Two",
        email="n2@example.test",
        home_x_m=20,
        home_y_m=0,
        alert_radius_m=0,
    )

    created = fixtures.create_post(
        api,
        author["id"],
        body=_PROFILING_BODY,
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        location_profiling_count=4,
    )
    fixtures.flag_post(api, created["id"], first_neighbour["id"])
    flagged = fixtures.flag_post(api, created["id"], second_neighbour["id"])
    case = fixtures.open_case(api, flagged)
    fixtures.decide_case(api, case["id"], decision=k.DECISION_REQUEST_REVISION)

    return {
        "author": author,
        "author_id": author["id"],
        "created": created,
        "flagged": flagged,
        "post_id": created["id"],
        "post": fixtures.read_post(api, created["id"]),
    }


def test_revise_from_revision_requested_rescores_and_republishes_the_post(
    api: ApiClient,
) -> None:
    """A clean rewrite scores zero, returns the post to the feed and counts one revision.

    PRD: "The revision replaces the `body` and the four classifier signals, re-runs the score, and increments `revision_count` by 1."
    PRD: "If the new score is below 0.49 the post returns `REVISION_REQUESTED → PUBLISHED`, `auto_flag_reason` is cleared, and a fresh fan-out batch is emitted with the three alert counters rewritten from scratch against the post's possibly-changed position."
    PRD: "An empty candidate pool is entirely legal, never an error: all three counters read 0, no dispatches are created, and the post is still returned with HTTP 201."
    PRD: "`flag_count` is monotonic — it is never decremented, not even when a revision cycle returns the post to the feed, so a post that has once been flagged twice carries that history for good."

    Design: Corner/endpoints/resident_post_revise_outside_revision_requested_rejected
    """
    world = _post_sent_back_for_revision(api)
    assertions.assert_score(world["created"]["discrimination_score"], "0.46")
    assertions.assert_subset(
        world["created"], {"state": k.POST_PUBLISHED, "flag_count": 0}
    )
    assertions.assert_subset(
        world["flagged"],
        {
            "state": k.POST_FLAGGED,
            "flag_count": 2,
            "auto_flag_reason": k.AUTO_FLAG_RESIDENT_FLAGS,
            "version": 3,
        },
    )
    before = world["post"]
    assertions.assert_subset(
        before, {"state": k.POST_REVISION_REQUESTED, "revision_count": 0}
    )

    revised = validate_success(
        api.revise_post(
            world["post_id"],
            f.revise_payload(
                body=_REWRITTEN_BODY,
                protected_class_term_count=0,
                unverified_assertion_count=0,
                location_profiling_count=0,
                hostile_tone_count=0,
            ),
            make_resident_headers(world["author_id"]),
        )
    )

    assertions.assert_score(revised["discrimination_score"], "0.00")
    assertions.assert_subset(
        revised,
        {
            "id": world["post_id"],
            "state": k.POST_PUBLISHED,
            "revision_count": 1,
            "auto_flag_reason": None,
            "body": _REWRITTEN_BODY,
            "location_profiling_count": 0,
            "flag_count": 2,
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )
    assertions.assert_version_advanced(revised, before["version"])


def test_revise_from_published_is_refused_and_changes_nothing(api: ApiClient) -> None:
    """Once the rewrite has republished the post, a second rewrite is out of state.

    PRD: "The author revises a post that is in `REVISION_REQUESTED`, and only the author may do so; a post in any other state is refused with `ERR_POST_NOT_REVISABLE`, and an author whose privileges have since been suspended is refused with `ERR_POSTING_SUSPENDED`."
    PRD: "The post being revised is in `REVISION_REQUESTED` — otherwise `ERR_POST_NOT_REVISABLE` (HTTP 409)."

    Design: Corner/endpoints/resident_post_revise_outside_revision_requested_rejected
    """
    world = _post_sent_back_for_revision(api)
    revision_payload = f.revise_payload(
        body=_REWRITTEN_BODY,
        protected_class_term_count=0,
        unverified_assertion_count=0,
        location_profiling_count=0,
        hostile_tone_count=0,
    )
    author_headers = make_resident_headers(world["author_id"])

    republished = validate_success(
        api.revise_post(world["post_id"], revision_payload, author_headers)
    )
    assert republished["state"] == k.POST_PUBLISHED, (
        f"The first revision must republish the post: {republished!r}"
    )

    validate_error(
        api.revise_post(world["post_id"], revision_payload, author_headers),
        ApiErrorId.POST_NOT_REVISABLE.value,
        409,
    )

    reread = fixtures.read_post(api, world["post_id"])
    assertions.assert_subset(
        reread,
        {
            "state": k.POST_PUBLISHED,
            "revision_count": 1,
            "auto_flag_reason": None,
            "body": _REWRITTEN_BODY,
        },
    )
    assertions.assert_score(reread["discrimination_score"], "0.00")
    assertions.assert_version_unchanged(reread, republished["version"])


# ── Opening a moderation case ──────────────────────────────────────────────

def _flagged_profiling_post(api: ApiClient) -> Dict[str, Any]:
    """An author's post driven to FLAGGED by two distinct neighbours' flags."""
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first_neighbour = fixtures.register_resident(
        api,
        display_name="Near One",
        email="n1@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    second_neighbour = fixtures.register_resident(
        api,
        display_name="Near Two",
        email="n2@example.test",
        home_x_m=20,
        home_y_m=0,
        alert_radius_m=0,
    )
    created = fixtures.create_post(
        api,
        author["id"],
        body=_PROFILING_BODY,
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        location_profiling_count=4,
    )
    fixtures.flag_post(api, created["id"], first_neighbour["id"])
    flagged = fixtures.flag_post(api, created["id"], second_neighbour["id"])
    return {
        "author": author,
        "author_id": author["id"],
        "created": created,
        "flagged": flagged,
        "post_id": created["id"],
    }


def test_opening_a_case_links_the_post_and_snapshots_its_score(api: ApiClient) -> None:
    """A new case names its post, freezes the post's score and takes the post into review.

    PRD: "The new case is created in `OPEN` with `decision` `NONE`, `opened_by_user_id` set to the acting `X-User-ID`, and `post_discrimination_score_at_open` snapshotted from the post's `discrimination_score` at that instant — a frozen figure that stays put however often the post is later revised."
    PRD: "The post moves `FLAGGED → UNDER_REVIEW`, or `UNDER_REVIEW → UNDER_REVIEW` when it was already under review — a re-triage that supersedes the open case without changing the post's state, and its `version` advances by 1 in either case."
    PRD: "The pagination block echoed in `meta` carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/endpoints/moderation_case_open_links_post_and_requires_it_to_be_flagged
    """
    world = _flagged_profiling_post(api)
    flagged = world["flagged"]
    assertions.assert_score(flagged["discrimination_score"], "0.46")
    assertions.assert_subset(
        flagged, {"state": k.POST_FLAGGED, "flag_count": 2, "version": 3}
    )

    case = validate_success(
        api.open_moderation_case(
            f.moderation_case_payload(
                flagged["id"],
                flagged["version"],
                opened_reason=k.OPENED_REASON_RESIDENT_FLAGS,
            ),
            MODERATOR_HEADERS,
        ),
        201,
    )

    assertions.assert_created_equals_updated(case)
    assertions.assert_subset(
        case,
        {
            "resident_post_id": world["post_id"],
            "state": k.CASE_OPEN,
            "decision": k.DECISION_NONE,
            "opened_by_user_id": MODERATOR_ID,
            "opened_reason": k.OPENED_REASON_RESIDENT_FLAGS,
        },
    )
    assertions.assert_score(
        case["post_discrimination_score_at_open"],
        "0.46",
        "post_discrimination_score_at_open",
    )

    post = fixtures.read_post(api, world["post_id"])
    assertions.assert_subset(post, {"state": k.POST_UNDER_REVIEW, "flag_count": 2})
    assertions.assert_version_advanced(post, flagged["version"])
    assertions.assert_score(post["discrimination_score"], "0.46")

    rows, meta = validate_paginated(
        api.list_moderation_cases(
            MODERATOR_HEADERS,
            f.page(limit=10, offset=0, resident_post_id=world["post_id"]),
        )
    )
    assert meta["total_count"] == 1, (
        f"Exactly one case has been raised on this post, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, f"One row fits on one page of ten: {meta!r}"
    assertions.assert_ids_in_order(rows, [case["id"]])


def test_opening_a_case_against_a_published_post_is_refused(api: ApiClient) -> None:
    """A post nobody has flagged is not triageable, however plainly it exists.

    PRD: "A moderator opens a case against a post in `FLAGGED` or already in `UNDER_REVIEW`; a post in any other state is refused with `ERR_POST_NOT_FLAGGED`."
    PRD: "The post a moderation case is opened against is `FLAGGED` or `UNDER_REVIEW` — otherwise `ERR_POST_NOT_FLAGGED` (HTTP 409)."

    Design: Corner/endpoints/moderation_case_open_links_post_and_requires_it_to_be_flagged
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    published = fixtures.create_post(
        api,
        author["id"],
        body="Reminder that the recycling collection moved to Thursday mornings.",
        category=k.CATEGORY_GENERAL,
        post_x_m=0,
        post_y_m=0,
    )
    assertions.assert_subset(
        published, {"state": k.POST_PUBLISHED, "flag_count": 0, "auto_flag_reason": None}
    )

    validate_error(
        api.open_moderation_case(
            f.moderation_case_payload(published["id"], published["version"]),
            MODERATOR_HEADERS,
        ),
        ApiErrorId.POST_NOT_FLAGGED.value,
        409,
    )

    reread = fixtures.read_post(api, published["id"])
    assertions.assert_subset(
        reread, {"state": k.POST_PUBLISHED, "flag_count": 0, "auto_flag_reason": None}
    )
    assertions.assert_version_unchanged(reread, published["version"])
