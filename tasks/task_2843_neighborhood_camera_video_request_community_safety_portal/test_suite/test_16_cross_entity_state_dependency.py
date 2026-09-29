"""Writes whose legality is decided by another row's state.

Two guards in this contract read a state that does not live on the row being
written. Submitting a video request reads the status of the agency that owns the
canvass area behind it, and sharing footage reads the status of the camera the
solicitation names. The tests below hold everything on the written row constant
and move only the related row, so a divergence cannot be attributed to the
written row itself, and each refusal is checked to report the identifier of the
related entity's rule rather than the one a reader would guess from the written
row's own posture.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_officer_headers, make_resident_headers

# The twin canvass at the far end of the grid: three homes and three cameras
# 5000 m east and north of the first agency's block, so neither agency's cameras
# can ever fall inside the other agency's disc.
_FAR_POSITIONS = ((5000, 5010), (5000, 5020), (5000, 5030))
_FAR_CENTRE = (5000, 5000)

# 72 hours after the pinned scenario clock: the deadline a submission stamps.
_RESPOND_DEADLINE = "2026-08-15T00:00:00Z"

# One hour past that deadline, where the sweep is entitled to expire silence.
_AFTER_DEADLINE = "2026-08-15T01:00:00Z"


def _twin_agency_canvasses(api: ApiClient) -> Dict[str, Any]:
    """Two canvasses identical in every shape, one of them at a suspended agency.

    Each agency is registered with the same five configuration knobs, enrols one
    officer with the same duty role, is surrounded by three camera-owning
    households at the same three offsets from its own disc centre, and carries a
    500 m area over the same six-hour footage window, locked, with a justified
    draft request against it. The only difference the two worlds ever acquire is
    that the first agency is then suspended.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)

    suspended = fixtures.seed_agency_with_officer(
        api,
        duty_role=k.DUTY_ROLE_REQUESTER,
        badge_number="O-1",
        full_name="Officer One",
        name="Agency One",
        jurisdiction_code="A1-001",
        min_device_threshold=3,
        max_open_requests=3,
        period_request_quota=20,
        post_share_retention_days=30,
        justification_min_chars=80,
    )
    fixtures.seed_residents_with_devices(api, fixtures.STANDARD_POSITIONS, prefix="A1R")
    suspended.update(
        fixtures.seed_justified_request(
            api,
            suspended["agency_id"],
            suspended["officer_id"],
            case_number="CASE-A1",
            area_overrides={"area_label": "A1 area"},
        )
    )

    onboarded = fixtures.seed_agency_with_officer(
        api,
        duty_role=k.DUTY_ROLE_REQUESTER,
        badge_number="O-2",
        full_name="Officer Two",
        name="Agency Two",
        jurisdiction_code="A2-001",
        min_device_threshold=3,
        max_open_requests=3,
        period_request_quota=20,
        post_share_retention_days=30,
        justification_min_chars=80,
    )
    fixtures.seed_residents_with_devices(api, _FAR_POSITIONS, prefix="A2R")
    onboarded.update(
        fixtures.seed_justified_request(
            api,
            onboarded["agency_id"],
            onboarded["officer_id"],
            case_number="CASE-A2",
            area_overrides={
                "center_x_m": _FAR_CENTRE[0],
                "center_y_m": _FAR_CENTRE[1],
                "area_label": "A2 area",
            },
        )
    )

    fixtures.suspend_agency(api, suspended["agency_id"])
    return {"suspended": suspended, "onboarded": onboarded}


def test_submit_reports_the_suspended_agency_not_the_requests_own_withdrawn_state(
    api: ApiClient,
) -> None:
    """Submitting a request whose agency is suspended reports the agency rule.

    PRD: "Rules are evaluated strictly in the order below, the first violated rule decides the response, and no later rule is evaluated once one has fired."
    PRD: "The agency owning the resource is `ONBOARDED` — otherwise `ERR_AGENCY_NOT_ONBOARDED` (HTTP 409)."
    PRD: "The gates are evaluated in the order of §2.9, which matters here more than anywhere else in the portal."
    PRD: "At level two — caused by level one — every video request of that agency whose `lifecycle_state` is `DRAFT` or `SOLICITING` is driven to `WITHDRAWN` with `withdraw_reason` set to `AGENCY_SUSPENDED`, again in ascending `created_at`."

    Design: Difficulty/cross_entity_state_dependency/video_request_submit_gated_on_agency_status_not_on_its_own_state
    """
    worlds = _twin_agency_canvasses(api)
    suspended = worlds["suspended"]

    agency_before = fixtures.read_agency(api, suspended["agency_id"])
    assertions.assert_subset(
        agency_before,
        {
            "status": k.AGENCY_STATUS_SUSPENDED,
            "open_request_count": 0,
            "requests_submitted_count": 0,
        },
    )

    area_before = fixtures.read_area(api, suspended["area"]["id"])
    assertions.assert_subset(
        area_before,
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_AGENCY_SUSPENDED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "radius_m": 500,
        },
    )

    request_before = fixtures.read_request(api, suspended["request_id"])
    assertions.assert_subset(
        request_before,
        {
            "lifecycle_state": k.LIFECYCLE_WITHDRAWN,
            "withdraw_reason": k.WITHDRAW_REASON_AGENCY_SUSPENDED,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 0,
            "submitted_at": None,
            "expires_at": None,
        },
    )

    response = api.submit_video_request(
        suspended["request_id"], make_officer_headers(suspended["officer_id"])
    )
    error = validate_error(response, ApiErrorId.AGENCY_NOT_ONBOARDED.value, 409)

    assert error["error_id"] != ApiErrorId.AREA_INVALIDATED.value, (
        "The invalidated canvass area is a lower-priority rule than the agency's "
        "own status, so it must not decide the response"
    )
    assert error["error_id"] != ApiErrorId.REQUEST_NOT_IN_DRAFT.value, (
        "The request's own withdrawn lifecycle state is a lower-priority rule "
        "than the agency's status, so it must not decide the response"
    )

    request_after = fixtures.read_request(api, suspended["request_id"])
    assertions.assert_version_unchanged(request_after, request_before["version"])
    assertions.assert_subset(
        request_after,
        {
            "lifecycle_state": k.LIFECYCLE_WITHDRAWN,
            "withdraw_reason": k.WITHDRAW_REASON_AGENCY_SUSPENDED,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 0,
            "submitted_at": None,
            "expires_at": None,
        },
    )
    assertions.assert_solicitation_buckets(request_after, 0, 0, 0, 0, 0)
    assert fixtures.list_solicitations(
        api, video_request_id=suspended["request_id"]
    ) == [], "A refused submission dispatches no solicitation at all"

    area_after = fixtures.read_area(api, suspended["area"]["id"])
    assertions.assert_version_unchanged(area_after, area_before["version"])
    assertions.assert_subset(
        area_after,
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_AGENCY_SUSPENDED,
        },
    )

    agency_after = fixtures.read_agency(api, suspended["agency_id"])
    assertions.assert_version_unchanged(agency_after, agency_before["version"])
    assertions.assert_subset(
        agency_after,
        {
            "status": k.AGENCY_STATUS_SUSPENDED,
            "open_request_count": 0,
            "requests_submitted_count": 0,
        },
    )


def test_the_identically_shaped_twin_submits_once_its_agency_is_onboarded(
    api: ApiClient,
) -> None:
    """The same submission succeeds where the owning agency is still onboarded.

    PRD: "The owning agency must be `ONBOARDED`, and the acting officer must be the request's `submitting_officer_id`."
    PRD: "`lifecycle_state` moves `DRAFT → SOLICITING`, `submitted_at` is stamped from the logical clock, and `expires_at` is set to exactly 72 hours after `submitted_at` — three days is the whole window a camera owner gets to answer."
    PRD: "On the request itself, `solicitation_count` and `pending_count` are both set to the number of solicitations created, the other four bucket counters stay at 0, and `provisional_share_rate_bps` is 0."
    PRD: "On success both counters move, but only the first can ever come back down — `open_request_count` is incremented by 1 and is decremented again when the request resolves, whereas `requests_submitted_count` is incremented by 1 and is never decremented."

    Design: Difficulty/cross_entity_state_dependency/video_request_submit_gated_on_agency_status_not_on_its_own_state
    """
    worlds = _twin_agency_canvasses(api)
    suspended = worlds["suspended"]
    onboarded = worlds["onboarded"]

    refused_area = fixtures.read_area(api, suspended["area"]["id"])
    permitting_area = fixtures.read_area(api, onboarded["area"]["id"])
    for field in ("radius_m", "eligible_device_count", "effective_min_devices"):
        assert permitting_area[field] == refused_area[field], (
            f"The two canvass areas must be identical in {field} so that only the "
            f"owning agency's status can explain a divergence: "
            f"{permitting_area[field]!r} against {refused_area[field]!r}"
        )
    assertions.assert_subset(
        permitting_area,
        {
            "status": k.AREA_STATUS_LOCKED,
            "invalidated_reason": None,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
        },
    )
    assertions.assert_instant(
        permitting_area["window_start_utc"],
        refused_area["window_start_utc"],
        "window_start_utc",
    )
    assertions.assert_instant(
        permitting_area["window_end_utc"],
        refused_area["window_end_utc"],
        "window_end_utc",
    )

    request_before = fixtures.read_request(api, onboarded["request_id"])
    assertions.assert_subset(
        request_before,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 0,
        },
    )

    response = api.submit_video_request(
        onboarded["request_id"], make_officer_headers(onboarded["officer_id"])
    )
    submitted = validate_success(response, 200)

    assertions.assert_subset(
        submitted,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 3,
            "withdraw_reason": None,
        },
    )
    assertions.assert_solicitation_buckets(submitted, 3, 0, 0, 0, 0)
    assertions.assert_bps(
        submitted["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )
    assertions.assert_instant(
        submitted["submitted_at"], fixtures.SCENARIO_CLOCK, "submitted_at"
    )
    assertions.assert_instant(submitted["expires_at"], _RESPOND_DEADLINE, "expires_at")
    assertions.assert_version_advanced(submitted, request_before["version"])

    solicitations = fixtures.list_solicitations(
        api, video_request_id=onboarded["request_id"]
    )
    assert len(solicitations) == 3, (
        f"One solicitation per roster camera was expected, got {len(solicitations)}"
    )
    assertions.assert_field_sequence(solicitations, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(
        solicitations, "status", [k.SOLICITATION_SOLICITED] * 3
    )

    permitting_agency = fixtures.read_agency(api, onboarded["agency_id"])
    assertions.assert_subset(
        permitting_agency,
        {
            "status": k.AGENCY_STATUS_ONBOARDED,
            "open_request_count": 1,
            "requests_submitted_count": 1,
        },
    )

    refusing_agency = fixtures.read_agency(api, suspended["agency_id"])
    assertions.assert_subset(
        refusing_agency,
        {
            "status": k.AGENCY_STATUS_SUSPENDED,
            "open_request_count": 0,
            "requests_submitted_count": 0,
        },
    )
    assertions.assert_subset(
        fixtures.read_request(api, suspended["request_id"]),
        {"lifecycle_state": k.LIFECYCLE_WITHDRAWN, "solicitation_count": 0},
    )


def _canvass_with_a_decommissioned_lead_camera(api: ApiClient) -> Dict[str, Any]:
    """A soliciting canvass whose nearest camera has since been decommissioned.

    The clock is pinned, one agency with a device floor of three is onboarded,
    three households each own one camera on the roster, and the request is
    justified and submitted so that all three solicitations sit unanswered. The
    owner of the nearest camera then decommissions it, which is the only change
    made to the world.
    """
    world = fixtures.seed_standard_canvass(api, min_device_threshold=3)
    lead, sibling, third = world["households"]
    world["lead"] = lead
    world["sibling"] = sibling
    world["third"] = third

    world["lead_solicitation_id"] = fixtures.solicitation_for_device(
        api, world["request_id"], lead["device_id"]
    )["id"]
    world["sibling_solicitation_id"] = fixtures.solicitation_for_device(
        api, world["request_id"], sibling["device_id"]
    )["id"]
    world["third_solicitation_id"] = fixtures.solicitation_for_device(
        api, world["request_id"], third["device_id"]
    )["id"]

    world["lead_device"] = fixtures.update_device(
        api,
        lead["device_id"],
        lead["resident_id"],
        status=k.DEVICE_STATUS_DECOMMISSIONED,
    )
    return world


def test_share_reports_the_decommissioned_camera_not_the_open_solicitations_state(
    api: ApiClient,
) -> None:
    """Sharing from a decommissioned camera reports the camera rule, not the row's.

    PRD: "The camera named by the solicitation must still have `status` `ACTIVE` at this moment: a camera the owner has since decommissioned cannot produce footage even though the solicitation is still open, and the answer is `ERR_DEVICE_DECOMMISSIONED`."
    PRD: "Setting `status` to `DECOMMISSIONED` is deliberately just as inert: every solicitation on that camera stays in `SOLICITED`, `pending_solicitation_count` is left exactly where it was, and the owner is simply unable to share from the dead camera — the solicitations sit there until their response deadline lapses and the retention sweep expires them."
    PRD: "Whenever a roster member or its owner loses eligibility — the camera's status changes, the owner opts out, the owner deactivates — the eligible count is recomputed against the frozen roster, and if the recomputed count falls below the area's `effective_min_devices`, the area moves `LOCKED → INVALIDATED` with `invalidated_reason` `ELIGIBILITY_BELOW_THRESHOLD` and its `version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/share_gated_on_device_status_while_solicitation_stays_open
    """
    world = _canvass_with_a_decommissioned_lead_camera(api)
    lead = world["lead"]

    device_before = fixtures.read_device(api, lead["device_id"])
    assertions.assert_subset(
        device_before,
        {
            "status": k.DEVICE_STATUS_DECOMMISSIONED,
            "pending_solicitation_count": 1,
            "solicitations_received_count": 1,
        },
    )

    area = fixtures.read_area(api, world["area"]["id"])
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_ELIGIBILITY,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
        },
    )

    solicitation_before = fixtures.read_solicitation(
        api, world["lead_solicitation_id"]
    )
    assertions.assert_subset(
        solicitation_before,
        {
            "status": k.SOLICITATION_SOLICITED,
            "clip_count": 0,
            "responded_at": None,
            "decline_reason": None,
            "device_id": lead["device_id"],
            "resident_id": lead["resident_id"],
        },
    )
    assertions.assert_instant(
        solicitation_before["respond_deadline_utc"],
        _RESPOND_DEADLINE,
        "respond_deadline_utc",
    )

    request_before = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        request_before, {"lifecycle_state": k.LIFECYCLE_SOLICITING}
    )
    assertions.assert_solicitation_buckets(request_before, 3, 0, 0, 0, 0)

    response = api.share_footage(
        world["lead_solicitation_id"],
        f.share_payload(),
        make_resident_headers(lead["resident_id"]),
    )
    error = validate_error(response, ApiErrorId.DEVICE_DECOMMISSIONED.value, 409)

    assert error["error_id"] != ApiErrorId.SOLICITATION_ALREADY_RESOLVED.value, (
        "The solicitation itself is still open to the attempted answer, so its own "
        "state must not be what the refusal reports"
    )
    assert error["error_id"] != ApiErrorId.AREA_INVALIDATED.value, (
        "A share is not a submission, so the invalidated canvass area must not be "
        "what the refusal reports"
    )

    solicitation_after = fixtures.read_solicitation(api, world["lead_solicitation_id"])
    assertions.assert_version_unchanged(
        solicitation_after, solicitation_before["version"]
    )
    assertions.assert_subset(
        solicitation_after,
        {
            "status": k.SOLICITATION_SOLICITED,
            "clip_count": 0,
            "responded_at": None,
            "decline_reason": None,
        },
    )

    request_after = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(request_after, request_before["version"])
    assertions.assert_subset(
        request_after,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "shared_clip_count": 0,
        },
    )
    assertions.assert_solicitation_buckets(request_after, 3, 0, 0, 0, 0)

    device_after = fixtures.read_device(api, lead["device_id"])
    assertions.assert_version_unchanged(device_after, device_before["version"])
    assertions.assert_subset(
        device_after,
        {
            "status": k.DEVICE_STATUS_DECOMMISSIONED,
            "pending_solicitation_count": 1,
        },
    )

    assertions.assert_footage_ledger(
        fixtures.read_resident(api, lead["resident_id"]),
        lifetime=0,
        retained=0,
        purged=0,
    )
    assert fixtures.list_clips_for_device(api, lead["device_id"]) == [], (
        "A refused share creates no clip"
    )


def test_sibling_camera_still_active_shares_under_the_same_canvass(
    api: ApiClient,
) -> None:
    """The same share succeeds from the neighbouring camera that is still active.

    PRD: "On a first share, the solicitation moves `SOLICITED → SHARED`, its `responded_at` is stamped, and its `clip_count` becomes 1; on the request, one unit moves out of `pending_count` and into `shared_count`; and the camera's `pending_solicitation_count` is decremented by 1."
    PRD: "In every other compliance posture — `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED` or `AUDIT_CLEARED` — the clip is `DEVICE_ANCHORED`: its `retention_expires_at` is the **earliest** of all three candidates, so whichever of the resident's own camera retention, the agency's window and the portal grace period runs out first wins, and the clip's initial `status` is `RETAINED`."
    PRD: "One share out of three solicitations is 3333 basis points; two out of three is 6667; two out of five is 4000; one out of four is 2500."

    Design: Difficulty/cross_entity_state_dependency/share_gated_on_device_status_while_solicitation_stays_open
    """
    world = _canvass_with_a_decommissioned_lead_camera(api)
    sibling = world["sibling"]

    sibling_device_before = fixtures.read_device(api, sibling["device_id"])
    assertions.assert_subset(
        sibling_device_before,
        {"status": k.DEVICE_STATUS_ACTIVE, "pending_solicitation_count": 1},
    )
    solicitation_before = fixtures.read_solicitation(
        api, world["sibling_solicitation_id"]
    )
    assertions.assert_subset(
        solicitation_before, {"status": k.SOLICITATION_SOLICITED, "clip_count": 0}
    )

    response = api.share_footage(
        world["sibling_solicitation_id"],
        f.share_payload(),
        make_resident_headers(sibling["resident_id"]),
    )
    clip = validate_success(response, 201)

    assertions.assert_subset(
        clip,
        {
            "status": k.CLIP_RETAINED,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "duration_seconds": 1800,
            "consent_solicitation_id": world["sibling_solicitation_id"],
            "video_request_id": world["request_id"],
            "device_id": sibling["device_id"],
            "owner_resident_id": sibling["resident_id"],
            "purged_at": None,
            "purge_reason": None,
        },
    )
    assertions.assert_instant(
        clip["recorded_start_utc"], "2026-08-08T01:00:00Z", "recorded_start_utc"
    )
    assertions.assert_instant(clip["shared_at"], fixtures.SCENARIO_CLOCK, "shared_at")

    solicitation_after = fixtures.read_solicitation(
        api, world["sibling_solicitation_id"]
    )
    assertions.assert_version_advanced(
        solicitation_after, solicitation_before["version"]
    )
    assertions.assert_subset(
        solicitation_after,
        {"status": k.SOLICITATION_SHARED, "clip_count": 1, "decline_reason": None},
    )
    assertions.assert_instant(
        solicitation_after["responded_at"], fixtures.SCENARIO_CLOCK, "responded_at"
    )

    request_after = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        request_after,
        {"lifecycle_state": k.LIFECYCLE_SOLICITING, "shared_clip_count": 1},
    )
    assertions.assert_solicitation_buckets(request_after, 2, 1, 0, 0, 0)
    assertions.assert_bps(
        request_after["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )

    sibling_device_after = fixtures.read_device(api, sibling["device_id"])
    assertions.assert_subset(
        sibling_device_after,
        {"status": k.DEVICE_STATUS_ACTIVE, "pending_solicitation_count": 0},
    )

    assertions.assert_footage_ledger(
        fixtures.read_resident(api, sibling["resident_id"]),
        lifetime=1800,
        retained=1800,
        purged=0,
    )


def test_the_retention_sweep_and_not_the_decommission_closes_the_dead_cameras_ask(
    api: ApiClient,
) -> None:
    """The dead camera's solicitation lapses at its deadline under the sweep.

    PRD: "It moves every solicitation still in `SOLICITED` whose `respond_deadline_utc` is at or before the clock to `EXPIRED`, processed in ascending `respond_deadline_utc` and then ascending `created_at`, with the counter movements of §3.5."
    PRD: "When the retention sweep of §3.6 finds a solicitation still in `SOLICITED` whose `respond_deadline_utc` is at or before the logical clock, it moves it `SOLICITED → EXPIRED`, stamps `responded_at`, and — diverging from the decline branch — leaves `decline_reason` null, because the owner said nothing and the portal records nothing on their behalf."
    PRD: "Finally, every video request whose `pending_count` has reached 0 is auto-resolved out of `SOLICITING` into `FULFILLED` or `EXHAUSTED` under the rule of §3.5, with the agency's `open_request_count` decremented for each."
    PRD: "If at least one of the request's solicitations is `SHARED`, the request moves `SOLICITING → FULFILLED` and its `provisional_share_rate_bps` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/share_gated_on_device_status_while_solicitation_stays_open
    """
    world = _canvass_with_a_decommissioned_lead_camera(api)
    lead = world["lead"]
    sibling = world["sibling"]

    clip = fixtures.share_footage(
        api, world["sibling_solicitation_id"], sibling["resident_id"]
    )

    fixtures.set_clock(api, _AFTER_DEADLINE)
    sweep = fixtures.run_sweep(api)

    assertions.assert_instant(sweep["run_at_utc"], _AFTER_DEADLINE, "run_at_utc")
    assertions.assert_subset(
        sweep,
        {
            "solicitations_expired_count": 2,
            "clips_purged_count": 0,
            "clips_held_count": 0,
            "requests_auto_closed_count": 1,
        },
    )

    lead_solicitation = fixtures.read_solicitation(api, world["lead_solicitation_id"])
    assertions.assert_subset(
        lead_solicitation,
        {
            "status": k.SOLICITATION_EXPIRED,
            "clip_count": 0,
            "decline_reason": None,
        },
    )
    assertions.assert_instant(
        lead_solicitation["responded_at"], _AFTER_DEADLINE, "responded_at"
    )

    assertions.assert_subset(
        fixtures.read_solicitation(api, world["third_solicitation_id"]),
        {"status": k.SOLICITATION_EXPIRED, "clip_count": 0, "decline_reason": None},
    )
    assertions.assert_subset(
        fixtures.read_solicitation(api, world["sibling_solicitation_id"]),
        {"status": k.SOLICITATION_SHARED, "clip_count": 1},
    )

    assertions.assert_subset(
        fixtures.read_device(api, lead["device_id"]),
        {
            "status": k.DEVICE_STATUS_DECOMMISSIONED,
            "pending_solicitation_count": 0,
            "solicitations_received_count": 1,
        },
    )

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        request,
        {
            "lifecycle_state": k.LIFECYCLE_FULFILLED,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "shared_clip_count": 1,
        },
    )
    assertions.assert_solicitation_buckets(request, 0, 1, 0, 2, 0)
    assertions.assert_solicitation_ledger(request, 3)
    assertions.assert_bps(
        request["provisional_share_rate_bps"], 3333, "provisional_share_rate_bps"
    )

    assertions.assert_subset(
        fixtures.read_agency(api, world["agency_id"]),
        {
            "status": k.AGENCY_STATUS_ONBOARDED,
            "open_request_count": 0,
            "requests_submitted_count": 1,
        },
    )

    assertions.assert_subset(
        fixtures.read_clip(api, clip["id"]),
        {"status": k.CLIP_RETAINED, "purge_reason": None, "purged_at": None},
    )
