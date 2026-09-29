"""Two contended resources, two opposite interval conventions.

One camera's footage timeline is guarded by half-open intervals with no buffer,
so a segment that starts exactly where an earlier one ended is accepted while a
single second of true overlap is refused. One agency's ground is guarded by
closed windows with a trailing-only buffer, so a shared instant is already a
collision and a probe placed just before an existing window is admitted while
the mirror-image probe placed just after it is refused.

Every refusal here is asserted to leave nothing behind: the collection count is
unchanged and the row the write would have touched keeps its state and version.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    PLATFORM_ADMIN_HEADERS,
    make_officer_headers,
    make_resident_headers,
)

# ── The footage timeline of one camera ─────────────────────────────────────

# The first segment offered from camera D1: the half-open interval
# [2026-08-08T01:00:00Z, 2026-08-08T01:30:00Z).
CLIP_A_START = "2026-08-08T01:00:00Z"
CLIP_A_SECONDS = 1800

# A second segment that begins exactly where the first one ends:
# [2026-08-08T01:30:00Z, 2026-08-08T01:40:00Z).
CLIP_B_START = "2026-08-08T01:30:00Z"
CLIP_B_SECONDS = 600

# A segment that ends exactly where the first one begins:
# [2026-08-08T00:30:00Z, 2026-08-08T01:00:00Z).
CLIP_C_START = "2026-08-08T00:30:00Z"
CLIP_C_SECONDS = 1800

# The camera retention window of every seeded household, in whole days, which
# is what anchors a DEVICE_ANCHORED clip's expiry to its recorded start.
DEVICE_RETENTION_DAYS = 30

# recorded_start_utc advanced by those 30 whole days, keeping the time of day.
CLIP_A_EXPIRY = "2026-09-07T01:00:00Z"
CLIP_B_EXPIRY = "2026-09-07T01:30:00Z"
CLIP_C_EXPIRY = "2026-09-07T00:30:00Z"

# ── The ground of one agency ───────────────────────────────────────────────

# The baseline canvass window: thirty hours ending well before the clock.
BASELINE_WINDOW_START = "2026-08-07T00:00:00Z"
BASELINE_WINDOW_END = "2026-08-08T06:00:00Z"

# The instant the baseline window's 24-hour trailing extension reaches.
BUFFERED_END = "2026-08-09T06:00:00Z"

# A six-hour probe window sitting wholly inside the buffered occupancy.
INSIDE_WINDOW_START = "2026-08-08T12:00:00Z"
INSIDE_WINDOW_END = "2026-08-08T18:00:00Z"


# ── Local setup ────────────────────────────────────────────────────────────

def _submitted_canvass(api: ApiClient) -> Dict[str, Any]:
    """The clock pinned, one agency, three camera owners and one soliciting request."""
    world = fixtures.seed_standard_canvass(api)
    household = world["households"][0]
    world["owner_id"] = household["resident_id"]
    world["camera_id"] = household["device_id"]
    world["solicitation"] = fixtures.solicitation_for_device(
        api, world["request_id"], world["camera_id"]
    )
    world["solicitation_id"] = world["solicitation"]["id"]
    return world


def _offer_footage(
    api: ApiClient,
    solicitation_id: str,
    owner_id: str,
    recorded_start_utc: str,
    duration_seconds: int,
):
    """Offer one footage segment against a solicitation, returning the raw response."""
    return api.share_footage(
        solicitation_id,
        f.share_payload(
            recorded_start_utc=recorded_start_utc, duration_seconds=duration_seconds
        ),
        make_resident_headers(owner_id),
    )


def _clip_page(api: ApiClient, camera_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every clip shared from one camera, with the pagination block."""
    return validate_paginated(
        api.list_shared_clips(
            PLATFORM_ADMIN_HEADERS, f.page(limit=100, offset=0, device_id=camera_id)
        )
    )


def _agency_with_officer(api: ApiClient) -> Dict[str, Any]:
    """The clock pinned and one onboarded agency with one requesting officer."""
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    return fixtures.seed_agency_with_officer(api, min_device_threshold=3)


def _draw_area(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    center_x_m: int,
    window_start_utc: str,
    window_end_utc: str,
    area_label: str,
):
    """Attempt one canvass area at a 500 m disc on the x axis, raw response."""
    return api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=center_x_m,
            center_y_m=0,
            radius_m=500,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            area_label=area_label,
        ),
        make_officer_headers(world["officer_id"]),
    )


def _baseline_area(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """The area every probe is measured against, left in draft at the origin."""
    return validate_success(
        _draw_area(
            api,
            world,
            center_x_m=0,
            window_start_utc=BASELINE_WINDOW_START,
            window_end_utc=BASELINE_WINDOW_END,
            area_label="Baseline canvass",
        ),
        201,
    )


def _area_page(api: ApiClient, agency_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every canvass area of one agency, with the pagination block."""
    return validate_paginated(
        api.list_request_areas(
            PLATFORM_ADMIN_HEADERS, f.page(limit=100, offset=0, agency_id=agency_id)
        )
    )


# ── One camera's footage timeline: half-open, unbuffered ────────────────────

def test_share_starting_exactly_where_the_previous_clip_ended_is_accepted(
    api: ApiClient,
) -> None:
    """Two adjacent half-open segments from one camera both become retained clips.

    PRD: "The segment occupies the **half-open** interval that begins at `recorded_start_utc` and ends `duration_seconds` later, excluding that end instant."
    PRD: "Intervals that merely touch at an endpoint do not conflict — a segment ending exactly where another begins is fine — but one second of true overlap is refused with `ERR_DEVICE_WINDOW_CONFLICT`."
    PRD: "In every other compliance posture — `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED` or `AUDIT_CLEARED` — the clip is `DEVICE_ANCHORED`: its `retention_expires_at` is the **earliest** of all three candidates, so whichever of the resident's own camera retention, the agency's window and the portal grace period runs out first wins, and the clip's initial `status` is `RETAINED`."

    Design: Difficulty/resource_temporal_overlap/device_clip_windows_half_open_adjacent_allowed_one_second_overlap_rejected
    """
    world = _submitted_canvass(api)

    clip_a = validate_success(
        _offer_footage(
            api,
            world["solicitation_id"],
            world["owner_id"],
            CLIP_A_START,
            CLIP_A_SECONDS,
        ),
        201,
    )
    assertions.assert_instant(
        clip_a["recorded_start_utc"], CLIP_A_START, "clip A recorded_start_utc"
    )
    assertions.assert_instant(clip_a["shared_at"], fixtures.SCENARIO_CLOCK, "clip A shared_at")
    assertions.assert_instant(
        clip_a["retention_expires_at"], CLIP_A_EXPIRY, "clip A retention_expires_at"
    )
    assertions.assert_subset(
        clip_a,
        {
            "duration_seconds": CLIP_A_SECONDS,
            "device_id": world["camera_id"],
            "owner_resident_id": world["owner_id"],
            "consent_solicitation_id": world["solicitation_id"],
            "video_request_id": world["request_id"],
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "status": k.CLIP_RETAINED,
        },
    )
    assertions.assert_nulls(clip_a, "purged_at", "purge_reason")

    clip_b = validate_success(
        _offer_footage(
            api,
            world["solicitation_id"],
            world["owner_id"],
            CLIP_B_START,
            CLIP_B_SECONDS,
        ),
        201,
    )
    assertions.assert_instant(
        clip_b["recorded_start_utc"], CLIP_B_START, "clip B recorded_start_utc"
    )
    assertions.assert_instant(
        clip_b["retention_expires_at"], CLIP_B_EXPIRY, "clip B retention_expires_at"
    )
    assertions.assert_subset(
        clip_b,
        {
            "duration_seconds": CLIP_B_SECONDS,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "status": k.CLIP_RETAINED,
        },
    )
    assert clip_b["id"] != clip_a["id"], "The touching segment must create its own clip"

    solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assertions.assert_subset(
        solicitation, {"status": k.SOLICITATION_SHARED, "clip_count": 2}
    )

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(request, 2, 1, 0, 0, 0)
    assertions.assert_solicitation_ledger(request, 3)
    assert request["shared_clip_count"] == 2, (
        f"Expected shared_clip_count 2, got {request['shared_clip_count']}"
    )
    assertions.assert_bps(
        request["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )

    owner = fixtures.read_resident(api, world["owner_id"])
    assertions.assert_footage_ledger(
        owner,
        lifetime=CLIP_A_SECONDS + CLIP_B_SECONDS,
        retained=CLIP_A_SECONDS + CLIP_B_SECONDS,
        purged=0,
    )

    rows, meta = _clip_page(api, world["camera_id"])
    assert meta["total_count"] == 2, (
        f"Expected two clips on this camera, got {meta['total_count']}"
    )
    assertions.assert_field_sequence(
        rows, "status", [k.CLIP_RETAINED, k.CLIP_RETAINED]
    )


def test_share_overlapping_an_existing_clip_by_sixty_seconds_is_refused(
    api: ApiClient,
) -> None:
    """A segment shifted one minute earlier collides with the clip it touched.

    PRD: "Second, non-collision: the offered half-open segment must not intersect the half-open interval of any existing clip on the **same camera** whose `status` is not `PURGED`."
    PRD: "Intervals that merely touch at an endpoint do not conflict — a segment ending exactly where another begins is fine — but one second of true overlap is refused with `ERR_DEVICE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/device_clip_windows_half_open_adjacent_allowed_one_second_overlap_rejected
    """
    world = _submitted_canvass(api)
    clip_a = validate_success(
        _offer_footage(
            api, world["solicitation_id"], world["owner_id"], CLIP_A_START, CLIP_A_SECONDS
        ),
        201,
    )
    clip_b = validate_success(
        _offer_footage(
            api, world["solicitation_id"], world["owner_id"], CLIP_B_START, CLIP_B_SECONDS
        ),
        201,
    )

    before_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    before_request = fixtures.read_request(api, world["request_id"])
    before_owner = fixtures.read_resident(api, world["owner_id"])

    # [2026-08-08T01:29:00Z, 2026-08-08T01:39:00Z) overlaps clip A's final minute.
    refused = _offer_footage(
        api, world["solicitation_id"], world["owner_id"], "2026-08-08T01:29:00Z", 600
    )
    validate_error(refused, ApiErrorId.DEVICE_WINDOW_CONFLICT.value, 409)

    rows, meta = _clip_page(api, world["camera_id"])
    assert meta["total_count"] == 2, (
        f"The refused share must create no clip: expected 2, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {clip_a["id"], clip_b["id"]}, (
        "Only the two accepted clips may exist on this camera"
    )

    after_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assertions.assert_subset(
        after_solicitation, {"status": k.SOLICITATION_SHARED, "clip_count": 2}
    )
    assertions.assert_version_unchanged(
        after_solicitation, before_solicitation["version"]
    )

    after_request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_request, 2, 1, 0, 0, 0)
    assert after_request["shared_clip_count"] == 2, (
        f"Expected shared_clip_count 2, got {after_request['shared_clip_count']}"
    )
    assertions.assert_bps(
        after_request["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )
    assertions.assert_version_unchanged(after_request, before_request["version"])

    after_owner = fixtures.read_resident(api, world["owner_id"])
    assertions.assert_footage_ledger(
        after_owner,
        lifetime=CLIP_A_SECONDS + CLIP_B_SECONDS,
        retained=CLIP_A_SECONDS + CLIP_B_SECONDS,
        purged=0,
    )
    assertions.assert_version_unchanged(after_owner, before_owner["version"])


def test_share_overlapping_an_existing_clip_by_exactly_one_second_is_refused(
    api: ApiClient,
) -> None:
    """A one-second intersection with a retained clip is already a conflict.

    PRD: "Second, non-collision: the offered half-open segment must not intersect the half-open interval of any existing clip on the **same camera** whose `status` is not `PURGED`."
    PRD: "Intervals that merely touch at an endpoint do not conflict — a segment ending exactly where another begins is fine — but one second of true overlap is refused with `ERR_DEVICE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/device_clip_windows_half_open_adjacent_allowed_one_second_overlap_rejected
    """
    world = _submitted_canvass(api)
    clip_a = validate_success(
        _offer_footage(
            api, world["solicitation_id"], world["owner_id"], CLIP_A_START, CLIP_A_SECONDS
        ),
        201,
    )

    before_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    before_request = fixtures.read_request(api, world["request_id"])
    before_owner = fixtures.read_resident(api, world["owner_id"])

    # [2026-08-08T01:29:59Z, 2026-08-08T01:30:00Z) shares clip A's last second only.
    refused = _offer_footage(
        api, world["solicitation_id"], world["owner_id"], "2026-08-08T01:29:59Z", 1
    )
    validate_error(refused, ApiErrorId.DEVICE_WINDOW_CONFLICT.value, 409)

    rows, meta = _clip_page(api, world["camera_id"])
    assert meta["total_count"] == 1, (
        f"The refused share must create no clip: expected 1, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [clip_a["id"]])

    after_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assertions.assert_subset(
        after_solicitation, {"status": k.SOLICITATION_SHARED, "clip_count": 1}
    )
    assertions.assert_version_unchanged(
        after_solicitation, before_solicitation["version"]
    )

    after_request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(after_request, 2, 1, 0, 0, 0)
    assert after_request["shared_clip_count"] == 1, (
        f"Expected shared_clip_count 1, got {after_request['shared_clip_count']}"
    )
    assertions.assert_bps(
        after_request["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )
    assertions.assert_version_unchanged(after_request, before_request["version"])

    after_owner = fixtures.read_resident(api, world["owner_id"])
    assertions.assert_footage_ledger(
        after_owner, lifetime=CLIP_A_SECONDS, retained=CLIP_A_SECONDS, purged=0
    )
    assertions.assert_version_unchanged(after_owner, before_owner["version"])

    still_retained = fixtures.read_clip(api, clip_a["id"])
    assertions.assert_subset(still_retained, {"status": k.CLIP_RETAINED})
    assertions.assert_instant(
        still_retained["retention_expires_at"], CLIP_A_EXPIRY, "clip A retention_expires_at"
    )


def test_share_ending_exactly_where_an_existing_clip_begins_is_accepted(
    api: ApiClient,
) -> None:
    """A segment butted against the start of an existing clip is admitted too.

    PRD: "Intervals that merely touch at an endpoint do not conflict — a segment ending exactly where another begins is fine — but one second of true overlap is refused with `ERR_DEVICE_WINDOW_CONFLICT`."
    PRD: "On a subsequent share against an already-`SHARED` solicitation — the self-loop `SHARED → SHARED`, which is how one consent covers several non-overlapping segments from the same camera — every consent counter is left alone, because the consent decision was already counted; only `clip_count` on the solicitation and `shared_clip_count` on the request advance."

    Design: Difficulty/resource_temporal_overlap/device_clip_windows_half_open_adjacent_allowed_one_second_overlap_rejected
    """
    world = _submitted_canvass(api)
    camera = fixtures.read_device(api, world["camera_id"])
    assertions.assert_subset(
        camera, {"retention_window_days": DEVICE_RETENTION_DAYS}
    )

    validate_success(
        _offer_footage(
            api, world["solicitation_id"], world["owner_id"], CLIP_A_START, CLIP_A_SECONDS
        ),
        201,
    )

    earlier = validate_success(
        _offer_footage(
            api, world["solicitation_id"], world["owner_id"], CLIP_C_START, CLIP_C_SECONDS
        ),
        201,
    )
    assertions.assert_instant(
        earlier["recorded_start_utc"], CLIP_C_START, "earlier clip recorded_start_utc"
    )
    assertions.assert_instant(
        earlier["retention_expires_at"], CLIP_C_EXPIRY, "earlier clip retention_expires_at"
    )
    assertions.assert_subset(
        earlier,
        {
            "duration_seconds": CLIP_C_SECONDS,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "status": k.CLIP_RETAINED,
            "device_id": world["camera_id"],
        },
    )

    solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assertions.assert_subset(
        solicitation, {"status": k.SOLICITATION_SHARED, "clip_count": 2}
    )

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_solicitation_buckets(request, 2, 1, 0, 0, 0)
    assert request["shared_clip_count"] == 2, (
        f"Expected shared_clip_count 2, got {request['shared_clip_count']}"
    )
    assertions.assert_bps(
        request["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )

    owner = fixtures.read_resident(api, world["owner_id"])
    assertions.assert_footage_ledger(
        owner,
        lifetime=CLIP_A_SECONDS + CLIP_C_SECONDS,
        retained=CLIP_A_SECONDS + CLIP_C_SECONDS,
        purged=0,
    )

    _rows, meta = _clip_page(api, world["camera_id"])
    assert meta["total_count"] == 2, (
        f"Expected two clips on this camera, got {meta['total_count']}"
    )


# ── One agency's ground: closed windows, trailing-only buffer ───────────────

def _assert_baseline_untouched(api: ApiClient, area: Dict[str, Any]) -> None:
    """The area a refused probe was measured against keeps its draft posture."""
    reread = fixtures.read_area(api, area["id"])
    assertions.assert_subset(
        reread, {"status": k.AREA_STATUS_DRAFT, "derived_request_count": 0}
    )
    assertions.assert_version_unchanged(reread, area["version"])
    assertions.assert_instant(
        reread["window_start_utc"], BASELINE_WINDOW_START, "baseline window_start_utc"
    )
    assertions.assert_instant(
        reread["window_end_utc"], BASELINE_WINDOW_END, "baseline window_end_utc"
    )


def test_canvass_probe_inside_the_trailing_buffer_is_refused(api: ApiClient) -> None:
    """A nearby probe whose window sits inside the buffered occupancy is refused.

    PRD: "The new area is rejected with `ERR_AREA_CANVASS_OVERLAP` when there exists another area belonging to the **same** agency, in any status other than `INVALIDATED`, that satisfies both of the following."
    PRD: "Second, temporal collision: take the existing area's footage window and extend it by nothing at all before its `window_start_utc` and by 24 hours after its `window_end_utc`; if that extended interval and the new area's own window share at least one instant, treating both intervals as closed at both ends, the two collide."

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)
    assertions.assert_subset(baseline, {"status": k.AREA_STATUS_DRAFT, "version": 1})

    refused = _draw_area(
        api,
        world,
        center_x_m=200,
        window_start_utc=INSIDE_WINDOW_START,
        window_end_utc=INSIDE_WINDOW_END,
        area_label="P1 inside buffer at 200 m",
    )
    validate_error(refused, ApiErrorId.AREA_CANVASS_OVERLAP.value, 409)

    rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 1, (
        f"The refused probe must create no area: expected 1, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [baseline["id"]])
    _assert_baseline_untouched(api, baseline)


def test_canvass_probe_at_exactly_three_hundred_metres_is_refused(api: ApiClient) -> None:
    """The proximity disc is closed, so a probe exactly 300 m away still collides.

    PRD: "First, proximity: the squared grid distance between the two centres is less than or equal to 300 multiplied by 300 — a closed disc of 300 metres."
    PRD: "Because the coordinates are whole metres, **every distance test in this system is performed on squared distances using exact integer arithmetic, and no square root is ever taken.**"

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)

    refused = _draw_area(
        api,
        world,
        center_x_m=k.CANVASS_PROXIMITY_M,
        window_start_utc=INSIDE_WINDOW_START,
        window_end_utc=INSIDE_WINDOW_END,
        area_label="P2 exactly 300 m",
    )
    validate_error(refused, ApiErrorId.AREA_CANVASS_OVERLAP.value, 409)

    rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 1, (
        f"The refused probe must create no area: expected 1, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [baseline["id"]])
    _assert_baseline_untouched(api, baseline)


def test_canvass_probe_sharing_only_the_buffered_end_instant_is_refused(
    api: ApiClient,
) -> None:
    """Both windows are closed, so one shared instant is already a collision.

    PRD: "Second, temporal collision: take the existing area's footage window and extend it by nothing at all before its `window_start_utc` and by 24 hours after its `window_end_utc`; if that extended interval and the new area's own window share at least one instant, treating both intervals as closed at both ends, the two collide."

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)

    # The probe starts at the very instant the 24-hour trailing extension ends.
    refused = _draw_area(
        api,
        world,
        center_x_m=200,
        window_start_utc=BUFFERED_END,
        window_end_utc="2026-08-09T12:00:00Z",
        area_label="P3 touches buffered end",
    )
    validate_error(refused, ApiErrorId.AREA_CANVASS_OVERLAP.value, 409)

    rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 1, (
        f"The refused probe must create no area: expected 1, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [baseline["id"]])
    _assert_baseline_untouched(api, baseline)


def test_canvass_probe_just_outside_three_hundred_metres_is_accepted(
    api: ApiClient,
) -> None:
    """One metre past the closed disc, the identical colliding window is irrelevant.

    PRD: "First, proximity: the squared grid distance between the two centres is less than or equal to 300 multiplied by 300 — a closed disc of 300 metres."
    PRD: "The acting officer's identity is stamped onto the row as `created_by_officer_id`, and the area is created in `status` `DRAFT` with `version` 1, `eligible_device_count` 0, `effective_min_devices` null, `derived_request_count` 0, `locked_at` null and `invalidated_reason` null."

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)

    accepted = validate_success(
        _draw_area(
            api,
            world,
            center_x_m=k.CANVASS_PROXIMITY_M + 1,
            window_start_utc=INSIDE_WINDOW_START,
            window_end_utc=INSIDE_WINDOW_END,
            area_label="P4 just outside 300 m",
        ),
        201,
    )
    assertions.assert_subset(
        accepted,
        {
            "agency_id": world["agency_id"],
            "created_by_officer_id": world["officer_id"],
            "center_x_m": 301,
            "center_y_m": 0,
            "radius_m": 500,
            "status": k.AREA_STATUS_DRAFT,
            "eligible_device_count": 0,
            "derived_request_count": 0,
            "version": 1,
        },
    )
    assertions.assert_nulls(
        accepted, "effective_min_devices", "locked_at", "invalidated_reason"
    )
    assertions.assert_instant(
        accepted["window_start_utc"], INSIDE_WINDOW_START, "probe window_start_utc"
    )
    assertions.assert_instant(
        accepted["window_end_utc"], INSIDE_WINDOW_END, "probe window_end_utc"
    )

    _rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 2, (
        f"Expected the baseline and the accepted probe, got {meta['total_count']}"
    )
    _assert_baseline_untouched(api, baseline)


def test_canvass_buffer_refuses_the_hour_after_but_admits_the_hour_before(
    api: ApiClient,
) -> None:
    """Two mirror-image probes one hour off each edge diverge, so the buffer is trailing-only.

    PRD: "Second, temporal collision: take the existing area's footage window and extend it by nothing at all before its `window_start_utc` and by 24 hours after its `window_end_utc`; if that extended interval and the new area's own window share at least one instant, treating both intervals as closed at both ends, the two collide."
    PRD: "The buffer sits only on the trailing edge because an agency that has just canvassed a block is expected to work with what it received for a day before asking the same households again, whereas footage from *before* a previous canvass window is fresh ground."

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)

    # Eleven hours starting one hour after the baseline window's end: inside the
    # 24-hour trailing extension.
    refused = _draw_area(
        api,
        world,
        center_x_m=100,
        window_start_utc="2026-08-08T07:00:00Z",
        window_end_utc="2026-08-08T18:00:00Z",
        area_label="One hour after the window",
    )
    validate_error(refused, ApiErrorId.AREA_CANVASS_OVERLAP.value, 409)

    rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 1, (
        f"The refused probe must create no area: expected 1, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [baseline["id"]])
    _assert_baseline_untouched(api, baseline)

    # The same eleven hours at the same 100 m offset, ending one hour before the
    # baseline window's start: nothing extends the leading edge.
    accepted = validate_success(
        _draw_area(
            api,
            world,
            center_x_m=100,
            window_start_utc="2026-08-06T12:00:00Z",
            window_end_utc="2026-08-06T23:00:00Z",
            area_label="One hour before the window",
        ),
        201,
    )
    assertions.assert_subset(
        accepted,
        {"center_x_m": 100, "status": k.AREA_STATUS_DRAFT, "version": 1},
    )
    assertions.assert_instant(
        accepted["window_start_utc"], "2026-08-06T12:00:00Z", "leading probe window_start_utc"
    )
    assertions.assert_instant(
        accepted["window_end_utc"], "2026-08-06T23:00:00Z", "leading probe window_end_utc"
    )

    _rows, after_meta = _area_page(api, world["agency_id"])
    assert after_meta["total_count"] == 2, (
        f"Expected the baseline and the leading probe, got {after_meta['total_count']}"
    )
    _assert_baseline_untouched(api, baseline)


def test_canvass_probe_one_hour_past_the_buffer_clears_every_live_area(
    api: ApiClient,
) -> None:
    """The rule is evaluated against every non-invalidated area of the agency, not just the first.

    PRD: "The new area is rejected with `ERR_AREA_CANVASS_OVERLAP` when there exists another area belonging to the **same** agency, in any status other than `INVALIDATED`, that satisfies both of the following."
    PRD: "The buffer sits only on the trailing edge because an agency that has just canvassed a block is expected to work with what it received for a day before asking the same households again, whereas footage from *before* a previous canvass window is fresh ground."

    Design: Difficulty/resource_temporal_overlap/same_agency_canvass_closed_windows_with_trailing_only_buffer
    """
    world = _agency_with_officer(api)
    baseline = _baseline_area(api, world)

    distant = validate_success(
        _draw_area(
            api,
            world,
            center_x_m=301,
            window_start_utc=INSIDE_WINDOW_START,
            window_end_utc=INSIDE_WINDOW_END,
            area_label="P4 just outside 300 m",
        ),
        201,
    )
    leading = validate_success(
        _draw_area(
            api,
            world,
            center_x_m=100,
            window_start_utc="2026-08-06T12:00:00Z",
            window_end_utc="2026-08-06T23:00:00Z",
            area_label="P5 before the window",
        ),
        201,
    )

    # (150, 0) is within 300 m of the baseline, of the 301 m area and of the
    # leading area, so only the time dimension can admit this probe.
    trailing = validate_success(
        _draw_area(
            api,
            world,
            center_x_m=150,
            window_start_utc="2026-08-09T19:00:00Z",
            window_end_utc="2026-08-10T01:00:00Z",
            area_label="P6 one hour past the buffer",
        ),
        201,
    )
    assertions.assert_subset(
        trailing,
        {"center_x_m": 150, "status": k.AREA_STATUS_DRAFT, "version": 1},
    )
    assertions.assert_instant(
        trailing["window_start_utc"], "2026-08-09T19:00:00Z", "trailing probe window_start_utc"
    )
    assertions.assert_instant(
        trailing["window_end_utc"], "2026-08-10T01:00:00Z", "trailing probe window_end_utc"
    )

    rows, meta = _area_page(api, world["agency_id"])
    assert meta["total_count"] == 4, (
        f"Expected the baseline and three accepted probes, got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(
        rows, [baseline["id"], distant["id"], leading["id"], trailing["id"]]
    )

    reread_distant = fixtures.read_area(api, distant["id"])
    assertions.assert_subset(
        reread_distant, {"center_x_m": 301, "status": k.AREA_STATUS_DRAFT}
    )
    reread_leading = fixtures.read_area(api, leading["id"])
    assertions.assert_instant(
        reread_leading["window_end_utc"],
        "2026-08-06T23:00:00Z",
        "leading area window_end_utc",
    )
    reread_trailing = fixtures.read_area(api, trailing["id"])
    assertions.assert_instant(
        reread_trailing["window_start_utc"],
        "2026-08-09T19:00:00Z",
        "trailing area window_start_utc",
    )
    _assert_baseline_untouched(api, baseline)
