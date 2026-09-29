"""Read-after-write agreement across every aggregate a write touched.

The portal runs every level of a cascade to completion inside the request that
caused it, so the body a write returns is already exactly what a read issued
immediately afterwards reports — on the row written, on the rows the cascade
created, and on the cross-aggregate counters the write reconciled. These tests
drive the two widest fan-out writes in the portal, submitting a video request
and sharing footage, and compare the write response against the reads that
follow it.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.test_users import (
    PLATFORM_ADMIN_HEADERS,
    make_agency_admin_headers,
    make_officer_headers,
    make_resident_headers,
)

# The instant 72 hours after the scenario clock, which is where a submitted
# request's response deadline lands.
EXPECTED_DEADLINE = "2026-08-15T00:00:00Z"

# The offered footage segment: half-open, thirty minutes inside the justified
# six-hour window.
SEGMENT_START = "2026-08-08T01:00:00Z"
SEGMENT_SECONDS = 1800

# The device candidate for that segment: recorded_start_utc advanced by the
# camera's thirty-day on-device retention window.
EXPECTED_CLIP_EXPIRY = "2026-09-07T01:00:00Z"

# The three roster cameras sit 10, 20 and 30 metres from the area centre.
EXPECTED_DISTANCES_SQ = [100, 400, 900]

# The fields the video-request write response and the read that follows it must
# agree on exactly.
REQUEST_ECHO_FIELDS = (
    "lifecycle_state",
    "compliance_state",
    "solicitation_count",
    "pending_count",
    "shared_count",
    "declined_count",
    "expired_count",
    "withdrawn_count",
    "shared_clip_count",
    "provisional_share_rate_bps",
    "version",
)

# The fields the shared-clip write response and its read-back must agree on.
CLIP_ECHO_FIELDS = (
    "id",
    "consent_solicitation_id",
    "video_request_id",
    "device_id",
    "owner_resident_id",
    "duration_seconds",
    "status",
    "retention_variant",
    "version",
)


def _justified_canvass(api: ApiClient) -> Dict[str, Any]:
    """One onboarded agency with three roster cameras and a justified draft request."""
    return fixtures.seed_standard_canvass(api, submit=False)


def _share_first_camera(
    api: ApiClient, world: Dict[str, Any]
) -> Dict[str, Any]:
    """Offer one thirty-minute segment from the nearest roster camera."""
    household = world["households"][0]
    solicitation = fixtures.solicitation_for_device(
        api, world["request_id"], household["device_id"]
    )
    response = api.share_footage(
        solicitation["id"],
        f.share_payload(
            recorded_start_utc=SEGMENT_START, duration_seconds=SEGMENT_SECONDS
        ),
        make_resident_headers(household["resident_id"]),
    )
    return {
        "household": household,
        "solicitation": solicitation,
        "response": response,
    }


def test_submit_response_already_carries_the_fanout_it_performed(api: ApiClient) -> None:
    """The submit response itself reports the states, buckets and deadline it just created.

    PRD: "`lifecycle_state` moves `DRAFT → SOLICITING`, `submitted_at` is stamped from the logical clock, and `expires_at` is set to exactly 72 hours after `submitted_at` — three days is the whole window a camera owner gets to answer."
    PRD: "On the request itself, `solicitation_count` and `pending_count` are both set to the number of solicitations created, the other four bucket counters stay at 0, and `provisional_share_rate_bps` is 0."
    PRD: "Cascades in this document are numbered by level — L1 is caused directly by the operation, L2 is caused by L1, and so on — and **every level runs to completion within the same request**; there is no deferred or eventual work anywhere in the portal except the retention sweep, which is an explicitly invoked operation."

    Design: Corner/consistency_model/submit_response_already_carries_every_counter_the_fanout_changed
    """
    world = _justified_canvass(api)
    officer_headers = make_officer_headers(world["officer_id"])
    draft = world["request"]

    written = validate_success(
        api.submit_video_request(world["request_id"], officer_headers)
    )

    assert written["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        f"Submission moves the lifecycle dimension to SOLICITING, got "
        f"{written['lifecycle_state']!r}"
    )
    assert written["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_LOGGED, (
        f"A 500 m area with three eligible cameras triggers no audit, so the "
        f"compliance dimension stays at JUSTIFICATION_LOGGED, got "
        f"{written['compliance_state']!r}"
    )
    assertions.assert_solicitation_buckets(
        written, pending=3, shared=0, declined=0, expired=0, withdrawn=0
    )
    assertions.assert_solicitation_ledger(written, total=3)
    assert written["shared_clip_count"] == 0, (
        f"No footage has been offered yet: {written['shared_clip_count']!r}"
    )
    assertions.assert_bps(
        written["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )
    assertions.assert_instant(written["submitted_at"], world["clock"], "submitted_at")
    assertions.assert_instant(written["expires_at"], EXPECTED_DEADLINE, "expires_at")
    assertions.assert_version_advanced(written, draft["version"])

    read_back = validate_success(
        api.get_video_request(world["request_id"], officer_headers)
    )
    for field in REQUEST_ECHO_FIELDS:
        assert read_back[field] == written[field], (
            f"The read issued straight after the write disagrees on {field}: "
            f"write reported {written[field]!r}, read reported {read_back[field]!r}"
        )
    assertions.assert_instant(
        read_back["submitted_at"], written["submitted_at"], "submitted_at on read-back"
    )
    assertions.assert_instant(
        read_back["expires_at"], written["expires_at"], "expires_at on read-back"
    )
    assertions.assert_solicitation_ledger(read_back, total=3)


def test_every_solicitation_row_is_listable_the_instant_submit_returns(
    api: ApiClient,
) -> None:
    """The three solicitation rows the fan-out created are already discoverable and ranked.

    PRD: "One consent solicitation is then created per roster camera, in the pinned roster order of §3.3 (squared distance ascending, then camera `created_at` ascending), each carrying its `video_request_id`, its `device_id`, the `resident_id` of that camera's owner as at this moment, a `status` of `SOLICITED`, its `distance_sq_m2` — the exact integer squared grid distance from the camera to the area centre — its 1-based `dispatch_rank` within the batch, and a `respond_deadline_utc` copied from the request's `expires_at`."
    PRD: "The solicitation collection filters on `video_request_id`, `device_id`, `resident_id`, `status` and `notification_suppressed`, and is ordered by ascending `dispatch_rank` within a request."
    PRD: "For every camera solicited, `solicitations_received_count` and `pending_solicitation_count` are each incremented by 1."

    Design: Corner/consistency_model/submit_response_already_carries_every_counter_the_fanout_changed
    """
    world = _justified_canvass(api)
    officer_headers = make_officer_headers(world["officer_id"])

    written = validate_success(
        api.submit_video_request(world["request_id"], officer_headers)
    )

    rows, meta = validate_paginated(
        api.list_solicitations(
            officer_headers,
            f.page(limit=10, offset=0, video_request_id=world["request_id"]),
        )
    )
    assert meta["total_count"] == 3, (
        f"Every solicitation row is already listable, expected total_count 3, got "
        f"{meta['total_count']}"
    )
    assert len(rows) == 3, f"Expected three rows on the page, got {len(rows)}"
    assertions.assert_field_sequence(rows, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(
        rows, "status", [k.SOLICITATION_SOLICITED] * 3
    )
    assertions.assert_field_sequence(rows, "distance_sq_m2", EXPECTED_DISTANCES_SQ)
    expected_owners = [household["resident_id"] for household in world["households"]]
    assertions.assert_field_sequence(rows, "resident_id", expected_owners)
    expected_devices = [household["device_id"] for household in world["households"]]
    assertions.assert_field_sequence(rows, "device_id", expected_devices)
    for row in rows:
        assert row["video_request_id"] == world["request_id"], (
            f"Solicitation {row['id']} names the wrong request: "
            f"{row['video_request_id']!r}"
        )
        assertions.assert_instant(
            row["respond_deadline_utc"],
            written["expires_at"],
            "respond_deadline_utc",
        )
        assert row["clip_count"] == 0, (
            f"A fresh solicitation carries no clips: {row['clip_count']!r}"
        )
        assertions.assert_nulls(row, "responded_at", "decline_reason")

    for household in world["households"]:
        device = fixtures.read_device(api, household["device_id"])
        assert device["solicitations_received_count"] == 1, (
            f"Camera {device['id']} should have been solicited once, got "
            f"{device['solicitations_received_count']}"
        )
        assert device["pending_solicitation_count"] == 1, (
            f"Camera {device['id']} should hold one unanswered solicitation, got "
            f"{device['pending_solicitation_count']}"
        )


def test_agency_and_officer_counters_are_current_before_submit_returns(
    api: ApiClient,
) -> None:
    """Both quota counters on the agency and the officer's own tally move inside the submit.

    PRD: "On success both counters move, but only the first can ever come back down — `open_request_count` is incremented by 1 and is decremented again when the request resolves, whereas `requests_submitted_count` is incremented by 1 and is never decremented."
    PRD: "The submitting officer's own `requests_submitted_count` is incremented by 1 at the same moment."

    Design: Corner/consistency_model/submit_response_already_carries_every_counter_the_fanout_changed
    """
    world = _justified_canvass(api)
    officer_headers = make_officer_headers(world["officer_id"])
    agency_headers = make_agency_admin_headers(world["agency_id"])

    agency_before = validate_success(
        api.get_agency(world["agency_id"], PLATFORM_ADMIN_HEADERS)
    )
    officer_before = validate_success(
        api.get_officer(world["officer_id"], agency_headers)
    )
    assertions.assert_zero_counters(
        agency_before, "open_request_count", "requests_submitted_count"
    )
    assertions.assert_zero_counters(officer_before, "requests_submitted_count")

    validate_success(api.submit_video_request(world["request_id"], officer_headers))

    agency_after = validate_success(
        api.get_agency(world["agency_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert agency_after["open_request_count"] == 1, (
        f"The one request now soliciting should already be counted as open, got "
        f"{agency_after['open_request_count']}"
    )
    assert agency_after["requests_submitted_count"] == 1, (
        f"The lifetime allotment should already be charged, got "
        f"{agency_after['requests_submitted_count']}"
    )
    assert agency_after["status"] == k.AGENCY_STATUS_ONBOARDED, (
        f"Submission does not disturb the agency's onboarding posture: "
        f"{agency_after['status']!r}"
    )

    officer_after = validate_success(
        api.get_officer(world["officer_id"], agency_headers)
    )
    assert officer_after["requests_submitted_count"] == 1, (
        f"The submitting officer's own tally should already have moved, got "
        f"{officer_after['requests_submitted_count']}"
    )
    assert officer_after["audits_completed_count"] == 0, (
        f"Submission is not an audit: {officer_after['audits_completed_count']!r}"
    )


def test_share_response_and_clip_readback_agree_on_the_retention_decision(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """The clip the share created is already complete, readable and listable under its request.

    PRD: "Note that sharing footage responds with 201 because it creates a shared clip, while declining, purging, flagging, revising and every other transition responds with 200."
    PRD: "The clip records its `consent_solicitation_id`, the `video_request_id` and `device_id` copied from the solicitation, the `owner_resident_id` of the camera's owner as at this moment — the anchor of the footage-seconds ledger — the supplied `recorded_start_utc` and `duration_seconds`, and `shared_at` stamped from the logical clock."
    PRD: "In every other compliance posture — `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED` or `AUDIT_CLEARED` — the clip is `DEVICE_ANCHORED`: its `retention_expires_at` is the **earliest** of all three candidates, so whichever of the resident's own camera retention, the agency's window and the portal grace period runs out first wins, and the clip's initial `status` is `RETAINED`."
    PRD: "The **device candidate** is the clip's `recorded_start_utc` advanced by the source camera's `retention_window_days` whole days."

    Design: Corner/consistency_model/share_response_and_immediate_readbacks_agree_across_four_aggregates
    """
    world = canvass
    shared = _share_first_camera(api, world)
    household = shared["household"]
    resident_headers = make_resident_headers(household["resident_id"])

    clip = validate_success(shared["response"], 201)

    assert clip["status"] == k.CLIP_RETAINED, (
        f"A clip shared under JUSTIFICATION_LOGGED starts RETAINED, got "
        f"{clip['status']!r}"
    )
    assert clip["retention_variant"] == k.RETENTION_DEVICE_ANCHORED, (
        f"No audit escalation is in force, so the variant is DEVICE_ANCHORED, got "
        f"{clip['retention_variant']!r}"
    )
    assert clip["duration_seconds"] == SEGMENT_SECONDS, (
        f"Expected duration_seconds {SEGMENT_SECONDS}, got {clip['duration_seconds']!r}"
    )
    assert clip["consent_solicitation_id"] == shared["solicitation"]["id"], (
        f"The clip names the wrong solicitation: {clip['consent_solicitation_id']!r}"
    )
    assert clip["video_request_id"] == world["request_id"], (
        f"The clip names the wrong request: {clip['video_request_id']!r}"
    )
    assert clip["device_id"] == household["device_id"], (
        f"The clip names the wrong camera: {clip['device_id']!r}"
    )
    assert clip["owner_resident_id"] == household["resident_id"], (
        f"The clip names the wrong owner: {clip['owner_resident_id']!r}"
    )
    assertions.assert_instant(clip["recorded_start_utc"], SEGMENT_START, "recorded_start_utc")
    assertions.assert_instant(clip["shared_at"], world["clock"], "shared_at")
    assertions.assert_instant(
        clip["retention_expires_at"], EXPECTED_CLIP_EXPIRY, "retention_expires_at"
    )
    assertions.assert_nulls(clip, "purged_at", "purge_reason")
    assertions.assert_created_equals_updated(clip)

    read_back = validate_success(api.get_shared_clip(clip["id"], resident_headers))
    for field in CLIP_ECHO_FIELDS:
        assert read_back[field] == clip[field], (
            f"The read issued straight after the share disagrees on {field}: "
            f"write reported {clip[field]!r}, read reported {read_back[field]!r}"
        )
    assertions.assert_instant(
        read_back["retention_expires_at"],
        clip["retention_expires_at"],
        "retention_expires_at on read-back",
    )
    assertions.assert_instant(
        read_back["recorded_start_utc"],
        clip["recorded_start_utc"],
        "recorded_start_utc on read-back",
    )

    rows, meta = validate_paginated(
        api.list_shared_clips(
            make_officer_headers(world["officer_id"]),
            f.page(limit=10, offset=0, video_request_id=world["request_id"]),
        )
    )
    assert meta["total_count"] == 1, (
        f"The clip is already listable under its request, expected total_count 1, "
        f"got {meta['total_count']}"
    )
    assertions.assert_ids_in_order(rows, [clip["id"]])


def test_share_is_visible_on_the_solicitation_and_its_request_on_the_next_read(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """One consent answer already reads through to the solicitation, the request and the camera.

    PRD: "On a first share, the solicitation moves `SOLICITED → SHARED`, its `responded_at` is stamped, and its `clip_count` becomes 1; on the request, one unit moves out of `pending_count` and into `shared_count`; and the camera's `pending_solicitation_count` is decremented by 1."
    PRD: "For every video request, `solicitation_count` equals the sum of `pending_count`, `shared_count`, `declined_count`, `expired_count` and `withdrawn_count`."
    PRD: "One share out of three solicitations is 3333 basis points; two out of three is 6667; two out of five is 4000; one out of four is 2500."

    Design: Corner/consistency_model/share_response_and_immediate_readbacks_agree_across_four_aggregates
    """
    world = canvass
    shared = _share_first_camera(api, world)
    household = shared["household"]
    solicitation = shared["solicitation"]
    resident_headers = make_resident_headers(household["resident_id"])

    clip = validate_success(shared["response"], 201)

    answered = validate_success(api.get_solicitation(solicitation["id"], resident_headers))
    assert answered["status"] == k.SOLICITATION_SHARED, (
        f"A first share moves the solicitation to SHARED, got {answered['status']!r}"
    )
    assert answered["clip_count"] == 1, (
        f"The consent now covers one segment, got {answered['clip_count']!r}"
    )
    assertions.assert_instant(answered["responded_at"], world["clock"], "responded_at")
    assert answered["decline_reason"] is None, (
        f"A share records no decline reason: {answered['decline_reason']!r}"
    )
    assertions.assert_version_advanced(answered, solicitation["version"])

    request_after = validate_success(
        api.get_video_request(world["request_id"], make_officer_headers(world["officer_id"]))
    )
    assert request_after["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        f"Two solicitations are still pending, so the request keeps soliciting, got "
        f"{request_after['lifecycle_state']!r}"
    )
    assertions.assert_solicitation_buckets(
        request_after, pending=2, shared=1, declined=0, expired=0, withdrawn=0
    )
    assertions.assert_solicitation_ledger(request_after, total=3)
    assert request_after["shared_clip_count"] == 1, (
        f"Exactly one clip has been shared against this request, got "
        f"{request_after['shared_clip_count']!r}"
    )
    assertions.assert_bps(
        request_after["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )

    device_after = fixtures.read_device(api, household["device_id"])
    assert device_after["pending_solicitation_count"] == 0, (
        f"The answered camera holds no unanswered solicitation, got "
        f"{device_after['pending_solicitation_count']}"
    )
    assert device_after["solicitations_received_count"] == 1, (
        f"The monotonic tally of asks stays at 1, got "
        f"{device_after['solicitations_received_count']}"
    )
    assert clip["consent_solicitation_id"] == solicitation["id"], (
        f"The clip belongs to the answered solicitation: "
        f"{clip['consent_solicitation_id']!r}"
    )


def test_share_moves_the_owner_footage_ledger_within_the_same_request(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """The owner's three footage-seconds counters are already reconciled when the 201 returns.

    PRD: "In both cases `shared_clip_count` on the request is incremented by 1, the request's `provisional_share_rate_bps` is recomputed, the resident's `lifetime_shared_footage_seconds` and `retained_footage_seconds` are each increased by `duration_seconds` — preserving the footage-seconds ledger of §2.11 — and the solicitation's `version` advances by 1."
    PRD: "For every resident, `lifetime_shared_footage_seconds` equals `retained_footage_seconds` plus `purged_footage_seconds`."

    Design: Corner/consistency_model/share_response_and_immediate_readbacks_agree_across_four_aggregates
    """
    world = canvass
    household = world["households"][0]
    resident_headers = make_resident_headers(household["resident_id"])

    before = validate_success(api.get_resident(household["resident_id"], resident_headers))
    assertions.assert_footage_ledger(before, lifetime=0, retained=0, purged=0)

    shared = _share_first_camera(api, world)
    clip = validate_success(shared["response"], 201)

    after = validate_success(api.get_resident(household["resident_id"], resident_headers))
    assertions.assert_footage_ledger(
        after, lifetime=SEGMENT_SECONDS, retained=SEGMENT_SECONDS, purged=0
    )
    assert clip["duration_seconds"] == SEGMENT_SECONDS, (
        f"The seconds credited are the segment's own length: {clip['duration_seconds']!r}"
    )
    assert after["status"] == k.RESIDENT_STATUS_ACTIVE, (
        f"Sharing does not disturb the account posture: {after['status']!r}"
    )

    unanswered = world["households"][1]
    untouched = validate_success(
        api.get_resident(
            unanswered["resident_id"], make_resident_headers(unanswered["resident_id"])
        )
    )
    assertions.assert_footage_ledger(untouched, lifetime=0, retained=0, purged=0)
